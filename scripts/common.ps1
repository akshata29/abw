<#
  Shared helpers for the Agents-Behind-the-Wall scripts (PowerShell 7).
  Dot-source:  . "$PSScriptRoot\common.ps1"
#>
$script:RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:GenDir     = Join-Path $script:RepoRoot 'infra\generated'
$script:SecretsDir = Join-Path $script:RepoRoot '.secrets'
foreach ($d in @($script:GenDir, $script:SecretsDir)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null } }

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "    ok  $Message" -ForegroundColor Green }
function Write-Warn2([string]$Message){ Write-Host "    !!  $Message" -ForegroundColor Yellow }

function Save-Json([string]$Path, $Object) {
  $json = $Object | ConvertTo-Json -Depth 30
  [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}
function Read-Json([string]$Path) {
  if (-not (Test-Path $Path)) { return $null }
  return (Get-Content -Raw -Path $Path | ConvertFrom-Json)
}

# Optional config.json keys (portable deployments set them; older files do not have them): value when present and non-empty, else the default.
function Get-CfgValue($Config, [string]$Name, $Default) {
  if ($Config -and $Config.PSObject.Properties[$Name] -and "$($Config.$Name)" -ne '') { return $Config.$Name }
  return $Default
}

function Get-AbwConfig {
  $path = Join-Path $script:GenDir 'config.json'
  $cfg = Read-Json $path
  if ($cfg) { return $cfg }
  Write-Step 'Creating config.json from current az context'
  $acct = az account show -o json | ConvertFrom-Json
  $me   = az ad signed-in-user show -o json 2>$null | ConvertFrom-Json
  $chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
  $u4 = 'k' + (-join (1..3 | ForEach-Object { $chars[[System.Security.Cryptography.RandomNumberGenerator]::GetInt32($chars.Length)] }))
  $domain = ($acct.user.name -split '@')[1]
  $owner = (($acct.user.name -split '@')[0] -replace '[^a-zA-Z0-9-]', '-').ToLowerInvariant()
  $cfg = [ordered]@{
    tenantId       = $acct.tenantId
    tenantDomain   = $domain
    subscriptionId = $acct.id
    location       = 'eastus2'
    searchLocation = 'eastus'   # AI Search region (eastus2 had no Search capacity when first built; PE stays in the VNet region)
    workload       = 'abw'
    env            = 'demo'
    regionCode     = 'eus2'
    instance       = '001'
    u4             = $u4
    rgName         = 'rg-abw-demo-eus2-001'
    operatorUpn    = $acct.user.name
    operatorOid    = $(if ($me) { $me.id } else { '' })
    tags           = [ordered]@{ workload='abw'; env='demo'; owner=$owner; purpose='se-weekly-showcase'; data='synthetic'; 'delete-after'=(Get-Date).AddDays(45).ToString('yyyy-MM-dd') }
  }
  Save-Json $path $cfg
  return (Read-Json $path)
}

# ---------- Microsoft Graph (token from az, plain REST) ----------
$script:GraphToken = $null
$script:GraphTokenAt = [datetime]::MinValue
function Get-GraphToken {
  if ($script:GraphToken -and ((Get-Date) - $script:GraphTokenAt).TotalMinutes -lt 40) { return $script:GraphToken }
  $t = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
  if ($LASTEXITCODE -ne 0 -or -not $t) { throw 'Could not get a Graph token from az' }
  $script:GraphToken = $t.Trim(); $script:GraphTokenAt = Get-Date
  return $script:GraphToken
}

function Invoke-Graph {
  [CmdletBinding()]
  param(
    [ValidateSet('GET','POST','PATCH','PUT','DELETE')][string]$Method = 'GET',
    [Parameter(Mandatory)][string]$Path,
    $Body = $null,
    [hashtable]$Query = $null,
    [switch]$Beta,
    [switch]$AllowNotFound
  )
  $base = if ($Beta) { 'https://graph.microsoft.com/beta' } else { 'https://graph.microsoft.com/v1.0' }
  $uri = if ($Path -like 'https://*') { $Path } else { "$base$Path" }
  if ($Query) {
    $qs = ($Query.GetEnumerator() | ForEach-Object { "$($_.Key)=$([uri]::EscapeDataString([string]$_.Value))" }) -join '&'
    $uri = "$uri`?$qs"
  }
  $headers = @{ Authorization = "Bearer $(Get-GraphToken)"; ConsistencyLevel = 'eventual' }
  $params = @{ Method = $Method; Uri = $uri; Headers = $headers; ErrorAction = 'Stop' }
  if ($null -ne $Body) {
    $params.Body = (ConvertTo-Json -InputObject $Body -Depth 30)
    $params.ContentType = 'application/json'
  }
  try {
    return Invoke-RestMethod @params
  } catch {
    $msg = $_.ErrorDetails.Message
    $code = $null
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
    if ($AllowNotFound -and $code -eq 404) { return $null }
    throw "Graph $Method $Path failed (HTTP $code): $msg"
  }
}

function Get-GraphAll([string]$Path, [hashtable]$Query = $null) {
  $items = @()
  $r = Invoke-Graph -Path $Path -Query $Query
  if ($null -ne $r.value) { $items += $r.value }
  while ($r.PSObject.Properties.Name -contains '@odata.nextLink' -and $r.'@odata.nextLink') {
    $r = Invoke-Graph -Path $r.'@odata.nextLink'
    $items += $r.value
  }
  return $items
}

function Invoke-Retry([scriptblock]$Script, [int]$Attempts = 8, [int]$DelaySec = 4, [string]$What = 'operation') {
  for ($i = 1; $i -le $Attempts; $i++) {
    try { return & $Script } catch {
      if ($i -eq $Attempts) { throw }
      Write-Host "    ..  $What not ready ($($_.Exception.Message.Substring(0,[Math]::Min(120,$_.Exception.Message.Length)))) retry $i/$Attempts" -ForegroundColor DarkGray
      Start-Sleep -Seconds ($DelaySec * $i)
    }
  }
}

function New-StrongPassword([int]$Length = 26) {
  $sets = @('ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnopqrstuvwxyz', '23456789', '!@#%^*-_=+')
  $all = -join $sets
  $pick = { param($s) $s[[System.Security.Cryptography.RandomNumberGenerator]::GetInt32($s.Length)] }
  $chars = New-Object System.Collections.Generic.List[char]
  foreach ($s in $sets) { $chars.Add((& $pick $s)) }
  while ($chars.Count -lt $Length) { $chars.Add((& $pick $all)) }
  $arr = $chars.ToArray()
  for ($i = $arr.Length - 1; $i -gt 0; $i--) { $j = [System.Security.Cryptography.RandomNumberGenerator]::GetInt32($i + 1); $t = $arr[$i]; $arr[$i] = $arr[$j]; $arr[$j] = $t }
  return (-join $arr)
}

function New-DetGuid([string]$Name) {
  $md5 = [System.Security.Cryptography.MD5]::Create()
  $h = $md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes("abw-demo:$Name"))
  return ([guid]::new($h)).ToString()
}


# ---------------------------------------------------------------------------
# Naming (single source of truth, mirrors DESIGN.md section 2)
# ---------------------------------------------------------------------------
function Get-AbwNames($cfg) {
  $w = $cfg.workload; $e = $cfg.env; $r = $cfg.regionCode; $i = $cfg.instance; $u = $cfg.u4
  $sfx = "$w-$e-$r-$i"
  $flat = "$w$e$r"
  [ordered]@{
    rg            = $cfg.rgName
    vnet          = "vnet-$sfx"
    nat           = "ng-$sfx"
    apimNsg       = "nsg-$w-apim-$r-$i"
    law           = "log-$sfx"
    appi          = "appi-$sfx"
    ampls         = "ampls-$sfx"
    kv            = "kv-$w-$e-$r-$u"
    acr           = "cr$flat$u"
    storage       = "st$flat$u"
    cosmos        = "cosmos-$w-$e-$r-$u"
    search        = "srch-$w-deals-$r-$u"
    caePriv       = "cae-$w-priv-$r-$i"
    caePub        = "cae-$w-pub-$r-$i"
    apim          = "apim-$w-$e-$r-$u"
    apimPe        = "pe-apim-$sfx"
    apic          = "apic-$w-$e-$r-$u"
    foundry       = "aif-$w-$e-$r-$u"
    project       = "proj-$w-wall-$u"
    asvcStorage   = "st$($w)asvc$u"
    asvcCosmos    = "cosmos-$w-asvc-$r-$u"
    asvcSearch    = "srch-$w-asvc-$r-$u"
    jumpNsg       = "nsg-$w-jump-$r-$i"
    jumpVm        = "vm-$w-jump-$r-$i"
    jumpNic       = "nic-$w-jump-$r-$i"
    jumpDisk      = "osdisk-$w-jump-$r-$i"
    bastion       = "bas-$w-$e-$r-$i"
    budget        = "budget-$sfx"
    modelDeploy   = (Get-CfgValue $cfg 'modelDeployment' 'gpt-54-mini')
    uamiKeys      = @('research','wall','actions','private','legacy','vendor')
  }
}

function Get-OperatorIp {
  try { (Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 15).Trim() } catch { $null }
}

function Get-AzJson([string[]]$AzArgs) {
  $out = & az @AzArgs --only-show-errors -o json 2>&1
  if ($LASTEXITCODE -ne 0) { throw "az $($AzArgs -join ' ') failed: $out" }
  if ([string]::IsNullOrWhiteSpace(($out | Out-String))) { return $null }
  ($out | Out-String) | ConvertFrom-Json
}
