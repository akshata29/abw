#requires -Version 7
<#
.SYNOPSIS
  Agents Behind the Wall - operator jump box inside the VNet: deploy, verify, start, stop, connect, remove.

.DESCRIPTION
  Why it exists: every data plane in this platform is private-endpoint-only by design, so the Azure portal's data pages
  (Foundry Knowledge, AI Search explorer, Cosmos Data Explorer, Storage browser) cannot load from a laptop. This Windows VM
  lives in the VNet, resolves the private DNS zones to the 10.42.1.x private endpoints, and is reached from the portal
  through Bastion Developer (free, browser RDP). No public IP anywhere. Nothing in the demo story depends on it.

  (no switch)    deploy infra\07-jumpbox.bicep (idempotent), then verify from inside the VM. Leaves the VM running.
  -Start         start the VM and wait for its agent
  -Stop          deallocate the VM (compute billing stops; only the disk remains)
  -Status        power state, size, private IP, Bastion, password file
  -OpenPortal    open the VM page in the Azure portal (then Connect > Bastion)
  -CopyPassword  copy the local admin password to the clipboard (kept out of clipboard history; cleared after -ClipboardSeconds)
  -VerifyOnly    re-run the in-VM checks on a running VM: private DNS, TCP 443, outbound, RDP, Edge, egress IP
  -Remove        delete the VM, NIC, disk, auto-shutdown schedule, Bastion, snet-jump and its NSG (nothing else is touched)
  -WhatIf        deployment: ARM validate + what-if.  -Remove: list what would be deleted
  -Force         re-apply the template even though the VM already exists
  -VmSize        override the size (default Standard_D2as_v7; Standard_D2s_v7 then Standard_D2ads_v7 if it cannot be allocated)

  The local admin password is generated on the first deploy and kept in .secrets\jumpbox.json. It is never printed.
  Bastion Developer signs in with a password only, so this one VM uses a local admin account: demo plumbing, not part of
  the keyless story.

  Do not re-run `deploy.ps1 -Stage network` once this stage exists: that template declares its subnets inline and would try
  to remove snet-jump while the VM's NIC is still in it.

.EXAMPLE
  pwsh scripts\jumpbox.ps1
  pwsh scripts\jumpbox.ps1 -Start -OpenPortal -CopyPassword
  pwsh scripts\jumpbox.ps1 -Stop
#>
[CmdletBinding()]
param(
  [switch]$Start,
  [switch]$Stop,
  [switch]$Status,
  [switch]$OpenPortal,
  [switch]$CopyPassword,
  [switch]$VerifyOnly,
  [switch]$Remove,
  [switch]$WhatIf,
  [switch]$Force,
  [string]$VmSize,
  [ValidateRange(10, 1800)][int]$ClipboardSeconds = 120
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"

$cfg        = Get-AbwConfig
$names      = Get-AbwNames $cfg
$rg         = $cfg.rgName
$vmName     = $names.jumpVm
$template   = Join-Path $script:RepoRoot 'infra\07-jumpbox.bicep'
$secretFile = Join-Path $script:SecretsDir 'jumpbox.json'
$stateFile  = Join-Path $script:GenDir 'jumpbox.json'
$adminUser  = 'abwadmin'
$deployName = 'abw-jumpbox'
$subnetName = 'snet-jump'
$sizeOrder  = @('Standard_D2as_v7', 'Standard_D2s_v7', 'Standard_D2ads_v7')

# What the verification step tests from inside the VM.
$privateHosts = @(
  "$($names.foundry).services.ai.azure.com", "$($names.foundry).cognitiveservices.azure.com", "$($names.foundry).openai.azure.com",
  "$($names.cosmos).documents.azure.com", "$($names.asvcCosmos).documents.azure.com",
  "$($names.search).search.windows.net", "$($names.asvcSearch).search.windows.net",
  "$($names.storage).blob.core.windows.net", "$($names.asvcStorage).blob.core.windows.net",
  "$($names.kv).vault.azure.net", "$($names.apim).azure-api.net"
)
# ACR is public by design (Standard SKU, no private endpoint - see DESIGN.md), so it is checked as an outbound host.
$outboundHosts = @('login.microsoftonline.com', 'portal.azure.com', 'ai.azure.com', 'management.azure.com', 'graph.microsoft.com', "$($names.acr).azurecr.io")

# ---------------------------------------------------------------------------- helpers

function Assert-AzContext {
  $raw = & az account show -o json --only-show-errors 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $raw) { throw "az is not signed in. Run: az login --tenant $($cfg.tenantId)" }
  $acct = ($raw | Out-String) | ConvertFrom-Json
  if ($acct.tenantId -ne $cfg.tenantId) { throw "az is signed in to tenant $($acct.tenantId), but this platform lives in $($cfg.tenantId) ($($cfg.tenantDomain)). Run: az login --tenant $($cfg.tenantId)" }
  if ($acct.id -ne $cfg.subscriptionId) { throw "az is on subscription $($acct.id), but this platform lives in $($cfg.subscriptionId). Run: az account set --subscription $($cfg.subscriptionId)" }
}

# $null when the VM does not exist.
function Get-VmInfo {
  $out = & az vm show -d -g $rg -n $vmName -o json --only-show-errors 2>&1
  if ($LASTEXITCODE -ne 0) {
    $text = ($out | Out-String)
    if ($text -match 'ResourceNotFound|was not found|could not be found') { return $null }
    throw "az vm show failed: $($text.Trim())"
  }
  ($out | Out-String) | ConvertFrom-Json
}

function Get-BastionInfo {
  $raw = & az resource list -g $rg --resource-type Microsoft.Network/bastionHosts -o json --only-show-errors 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
  $first = @(($raw | Out-String) | ConvertFrom-Json) | Select-Object -First 1
  if (-not $first) { return $null }
  $full = & az resource show --ids $first.id -o json --only-show-errors 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $full) { return $first }
  ($full | Out-String) | ConvertFrom-Json
}

function Get-JumpSecret {
  $s = Read-Json $secretFile
  if ($s -and $s.password) { return $s }
  $null
}

function New-JumpPassword([int]$Length = 24) {
  # Letters, digits and - _ = + only, no look-alikes: easy to read out or retype if a clipboard paste is ever blocked.
  $sets = @('ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnopqrstuvwxyz', '23456789', '-_=+')
  $all = -join $sets
  $pick = { param($s) $s[[System.Security.Cryptography.RandomNumberGenerator]::GetInt32($s.Length)] }
  $chars = [System.Collections.Generic.List[char]]::new()
  foreach ($s in $sets) { $chars.Add((& $pick $s)) }
  while ($chars.Count -lt $Length) { $chars.Add((& $pick $all)) }
  $arr = $chars.ToArray()
  for ($i = $arr.Length - 1; $i -gt 0; $i--) {
    $j = [System.Security.Cryptography.RandomNumberGenerator]::GetInt32($i + 1)
    $t = $arr[$i]; $arr[$i] = $arr[$j]; $arr[$j] = $t
  }
  -join $arr
}

function Write-ParamFile([string]$Path, [System.Collections.IDictionary]$Params) {
  $body = [ordered]@{
    '$schema'      = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
    contentVersion = '1.0.0.0'
    parameters     = [ordered]@{}
  }
  foreach ($k in $Params.Keys) { $body.parameters[$k] = @{ value = $Params[$k] } }
  Save-Json $Path $body
}

function Update-State([System.Collections.IDictionary]$Patch) {
  $cur = [ordered]@{}
  $old = Read-Json $stateFile
  if ($old) { foreach ($p in $old.PSObject.Properties) { $cur[$p.Name] = $p.Value } }
  foreach ($k in $Patch.Keys) { $cur[$k] = $Patch[$k] }
  Save-Json $stateFile $cur
}

function Register-ProviderIfNeeded([string]$Namespace) {
  $state = (& az provider show -n $Namespace --query registrationState -o tsv --only-show-errors 2>$null)
  if ($state -eq 'Registered') { return }
  if ($WhatIf) { Write-Warn2 "$Namespace is '$state' - a real run registers it (additive, subscription-wide)"; return }
  Write-Step "registering resource provider $Namespace (additive; was '$state')"
  & az provider register -n $Namespace --wait --only-show-errors | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "could not register resource provider $Namespace" }
  Write-Ok "$Namespace registered"
}

function Write-Check([string]$Label, [bool]$Ok, [string]$Detail) {
  $line = "{0,-13} {1}" -f $Label, $Detail
  if ($Ok) { Write-Ok $line } else { Write-Warn2 $line }
}

# ---------------------------------------------------------------------------- deploy

# One deployment attempt. Never throws for a failed deployment: the caller decides what to do about the size or Bastion.
function Invoke-JumpDeploy([string]$Size, [string]$Password, [bool]$WithBastion) {
  $audit  = Join-Path $script:GenDir 'params.jumpbox.json'
  $secret = Join-Path $script:SecretsDir 'jumpbox.params.tmp.json'
  $p = [ordered]@{
    location       = $cfg.location
    vnetName       = $names.vnet
    natGatewayName = $names.nat
    jumpNsgName    = $names.jumpNsg
    vmName         = $vmName
    nicName        = $names.jumpNic
    osDiskName     = $names.jumpDisk
    bastionName    = $names.bastion
    deployBastion  = $WithBastion
    vmSize         = $Size
    adminUsername  = $adminUser
    tags           = $cfg.tags
  }
  Write-ParamFile $audit $p
  $p['adminPassword'] = $Password
  Write-ParamFile $secret $p
  try {
    if ($WhatIf) {
      Write-Step "validate $deployName (size $Size)"
      $val = & az deployment group validate -g $rg -n $deployName -f $template -p "@$secret" --only-show-errors -o json 2>&1
      $valExit = $LASTEXITCODE
      if ($valExit -ne 0) {
        Write-Warn2 'validation failed'
        ($val | Out-String).Replace($Password, '***') | Write-Host
        return [pscustomobject]@{ ok = $false; whatIf = $true }
      }
      Write-Ok 'template and parameters are valid (ARM preflight passed)'
      Write-Step "what-if $deployName"
      $wi = & az deployment group what-if -g $rg -n $deployName -f $template -p "@$secret" --only-show-errors --result-format ResourceIdOnly 2>&1
      ($wi | Out-String).Replace($Password, '***') | Write-Host
      return [pscustomobject]@{ ok = $true; whatIf = $true }
    }

    $bastionNote = if ($WithBastion) { 'Bastion Developer in the template' } else { 'Bastion Developer left to the portal' }
    Write-Step "deploying $deployName -> $rg  (size $Size; $bastionNote)"
    $raw = & az deployment group create -g $rg -n $deployName -f $template -p "@$secret" --only-show-errors -o json 2>&1
    $exit = $LASTEXITCODE
    $text = ($raw | Out-String).Replace($Password, '***')
    if ($exit -eq 0) {
      return [pscustomobject]@{ ok = $true; whatIf = $false; deployment = ($text | ConvertFrom-Json) }
    }

    $failed = @()
    $opsRaw = & az deployment operation group list -g $rg -n $deployName --query "[?properties.provisioningState=='Failed'].{res:properties.targetResource.resourceName,type:properties.targetResource.resourceType,code:properties.statusMessage.error.code,msg:properties.statusMessage.error.message}" -o json --only-show-errors 2>$null
    if ($opsRaw) { $failed = @(($opsRaw | Out-String).Replace($Password, '***') | ConvertFrom-Json) }
    $all = $text + ' ' + (($failed | ForEach-Object { "$($_.code) $($_.msg)" }) -join ' ')
    [pscustomobject]@{
      ok          = $false
      whatIf      = $false
      text        = $text
      failed      = $failed
      sizeProblem = [bool]($all -match 'SkuNotAvailable|NotAvailableForSubscription|AllocationFailed|Overconstrained|QuotaExceeded|exceeding approved|InsufficientCapacity')
      bastionOnly = ($failed.Count -gt 0) -and (@($failed | Where-Object { $_.type -ne 'Microsoft.Network/bastionHosts' }).Count -eq 0)
    }
  } finally {
    Remove-Item $secret -Force -ErrorAction SilentlyContinue
  }
}

function Show-DeployFailure($Result) {
  Write-Warn2 'deployment failed'
  foreach ($f in $Result.failed) { Write-Host ("    {0} ({1}): {2} {3}" -f $f.res, $f.type, $f.code, $f.msg) -ForegroundColor Yellow }
  if (-not $Result.failed -or $Result.failed.Count -eq 0) { Write-Host $Result.text }
}

function Invoke-DeployAndVerify {
  foreach ($check in @(@('vnet', $names.vnet), @('nat gateway', $names.nat))) {
    $kind = $check[0]
    $nm = $check[1]
    $found = if ($kind -eq 'vnet') { & az network vnet show -g $rg -n $nm --query name -o tsv --only-show-errors 2>$null } else { & az network nat gateway show -g $rg -n $nm --query name -o tsv --only-show-errors 2>$null }
    if (-not $found) { throw "$kind $nm not found in $rg - run: .\scripts\deploy.ps1 -Stage network" }
  }
  Register-ProviderIfNeeded 'Microsoft.Compute'
  Register-ProviderIfNeeded 'Microsoft.DevTestLab'

  $existing = Get-VmInfo
  $secret = Get-JumpSecret
  if ($existing -and -not $Force) {
    Write-Ok "$vmName already exists ($($existing.powerState), $($existing.hardwareProfile.vmSize)); the template is not re-applied (use -Force to re-apply)"
    if ($WhatIf) { return }
    if ($existing.powerState -ne 'VM running') { Start-Jump }
    $null = Invoke-JumpVerify
    return
  }
  if ($existing -and -not $secret) {
    throw "$vmName exists but .secrets\jumpbox.json is missing, so its password is unknown. Reset it in the portal (VM > Help > Reset password), or remove and redeploy: pwsh scripts\jumpbox.ps1 -Remove"
  }

  if (-not $secret) {
    $secret = [pscustomobject]@{ vm = $vmName; username = $adminUser; password = (New-JumpPassword); created = (Get-Date).ToUniversalTime().ToString('o') }
    if (-not $WhatIf) {
      Save-Json $secretFile $secret
      Write-Ok 'generated the local admin password -> .secrets\jumpbox.json (not printed)'
    }
  }

  $candidates = if ($VmSize) { @($VmSize) } elseif ($existing) { @($existing.hardwareProfile.vmSize) } else { $sizeOrder }
  $withBastion = $true
  $done = $null
  foreach ($size in $candidates) {
    $r = Invoke-JumpDeploy $size $secret.password $withBastion
    if ($r.whatIf) { return }
    if (-not $r.ok -and $r.bastionOnly -and $withBastion) {
      Show-DeployFailure $r
      Write-Warn2 'Bastion Developer could not be created from the template. Deploying the VM without it - the portal creates Bastion Developer on the first Connect.'
      $withBastion = $false
      $r = Invoke-JumpDeploy $size $secret.password $false
    }
    if ($r.ok) { $done = $r; $chosen = $size; break }
    Show-DeployFailure $r
    if ($r.sizeProblem -and $size -ne $candidates[-1]) {
      Write-Warn2 "$size cannot be allocated here - removing the half-created VM and trying the next size"
      & az vm delete -g $rg -n $vmName --yes --only-show-errors 2>&1 | Out-Null
      continue
    }
    throw "jump box deployment failed (see above). Nothing else in the platform was touched."
  }
  if (-not $done) { throw 'No VM size could be allocated (tried: ' + ($candidates -join ', ') + ').' }

  $out = [ordered]@{}
  foreach ($p in $done.deployment.properties.outputs.PSObject.Properties) { $out[$p.Name] = $p.Value.value }
  $state = [ordered]@{
    deployedAt        = (Get-Date).ToUniversalTime().ToString('o')
    username          = $adminUser
    passwordFile      = '.secrets\jumpbox.json'
    bastionInTemplate = $withBastion
    subnet            = $subnetName
  }
  foreach ($k in $out.Keys) { $state[$k] = $out[$k] }
  Update-State $state
  Write-Ok "deployed in $($done.deployment.properties.duration): $vmName ($chosen), private IP $($out.privateIp)"

  $null = Invoke-JumpVerify
}

# ---------------------------------------------------------------------------- verify

function Invoke-JumpVerify {
  $info = Get-VmInfo
  if (-not $info) { throw 'The jump box is not deployed - run: pwsh scripts\jumpbox.ps1' }
  if ($info.powerState -ne 'VM running') { throw "$vmName is '$($info.powerState)'. Start it first: pwsh scripts\jumpbox.ps1 -Start" }

  Write-Step "verifying from inside $vmName (Azure run-command; read-only)"
  $body = (Get-Content -Raw -Path (Join-Path $PSScriptRoot 'jumpbox-check.ps1')).Replace('__PRIVATE__', ($privateHosts -join ',')).Replace('__OUTBOUND__', ($outboundHosts -join ','))
  $tmp = Join-Path ([IO.Path]::GetTempPath()) "abw-jumpcheck-$([guid]::NewGuid().ToString('N')).ps1"
  [IO.File]::WriteAllText($tmp, $body, (New-Object System.Text.UTF8Encoding($false)))
  try {
    $raw = Invoke-Retry -What 'VM agent' -Attempts 8 -DelaySec 8 -Script {
      $o = & az vm run-command invoke -g $rg -n $vmName --command-id RunPowerShellScript --scripts "@$tmp" -o json --only-show-errors 2>&1
      if ($LASTEXITCODE -ne 0) { throw (($o | Out-String).Trim()) }
      $o
    }
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }

  $obj = ($raw | Out-String) | ConvertFrom-Json
  $msg = ($obj.value | Where-Object { $_.code -like '*StdOut*' } | Select-Object -First 1).message
  if (-not $msg) { $msg = ($obj.value | Select-Object -First 1).message }
  if ($msg -match '(?s)\[stdout\](.*?)(\[stderr\]|$)') { $msg = $Matches[1] }
  $jsonLine = @($msg -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
  if (-not $jsonLine) { throw "The in-VM check printed no JSON. Output was: $(([string]$msg).Trim())" }
  $res = $jsonLine | ConvertFrom-Json

  # The same names from the laptop: they resolve to public IPs, which is why the portal data pages fail there.
  $laptop = @{}
  foreach ($h in $privateHosts) {
    try { $laptop[$h] = @((Resolve-DnsName -Name $h -Type A -DnsOnly -ErrorAction Stop | Where-Object { $_.Type -eq 'A' }).IPAddress) }
    catch { $laptop[$h] = @() }
  }

  $natIp = $null
  try {
    $nat = Get-AzJson @('network', 'nat', 'gateway', 'show', '-g', $rg, '-n', $names.nat)
    $pipId = @($nat.publicIpAddresses | ForEach-Object { $_.id }) | Select-Object -First 1
    if ($pipId) { $natIp = (& az network public-ip show --ids $pipId --query ipAddress -o tsv --only-show-errors 2>$null) }
  } catch { }

  $priv = @($res.private)
  $out  = @($res.outbound)
  $isPrivate = { param($e) (@($e.ip | Where-Object { $_ -match '^10\.42\.' }).Count -gt 0) }
  $privOk = @($priv | Where-Object { (& $isPrivate $_) -and $_.t })
  $outOk  = @($out | Where-Object { $_.t })

  Write-Host ''
  foreach ($e in $priv) {
    $good = (& $isPrivate $e) -and $e.t
    $line = "    {0,-52} VM {1,-12} laptop {2,-16} HTTP {3}" -f $e.h, (@($e.ip) -join ','), (@($laptop[$e.h]) -join ','), $e.c
    Write-Host $line -ForegroundColor $(if ($good) { 'Green' } else { 'Yellow' })
  }
  Write-Host ''
  Write-Check 'private DNS' ($privOk.Count -eq $priv.Count) "$($privOk.Count)/$($priv.Count) data-plane hosts resolve to a 10.42.x private endpoint and answer on 443 (the laptop sees public IPs)"
  Write-Check 'outbound' ($outOk.Count -eq $out.Count) "$($outOk.Count)/$($out.Count) portal, sign-in and ACR (public by design) hosts answer on 443 (via the NAT gateway)"
  $egressOk = [bool]$res.egress -and ((-not $natIp) -or $res.egress -eq $natIp)
  Write-Check 'egress IP' $egressOk $(if ($natIp) { "$($res.egress) (NAT gateway public IP: $natIp)" } else { "$($res.egress) (NAT gateway IP not looked up)" })
  Write-Check 'RDP' ([bool]$res.rdp) $(if ($res.rdp) { 'listening on 3389 (Bastion connects here)' } else { 'NOT listening on 3389' })
  Write-Check 'Edge' ([bool]$res.edge) $(if ($res.edge) { "installed ($($res.edge))" } else { 'not found at the default path' })
  Write-Check 'guest' $true "$($res.os); time zone $($res.tz); DNS $((@($res.dns)) -join ',')"

  $verify = [ordered]@{
    at              = (Get-Date).ToUniversalTime().ToString('o')
    privateDnsOk    = "$($privOk.Count)/$($priv.Count)"
    outboundOk      = "$($outOk.Count)/$($out.Count)"
    egressIp        = $res.egress
    natGatewayIp    = $natIp
    rdpListening    = [bool]$res.rdp
    edgeVersion     = $res.edge
    guest           = "$($res.os); $($res.tz)"
    dnsServers      = @($res.dns)
    hosts           = @($priv | ForEach-Object { [ordered]@{ host = $_.h; vmIps = @($_.ip); laptopIps = @($laptop[$_.h]); tcp443 = [bool]$_.t; http = $_.c } })
    outboundHosts   = @($out | ForEach-Object { [ordered]@{ host = $_.h; tcp443 = [bool]$_.t; http = $_.c } })
  }
  Update-State ([ordered]@{ verify = $verify })
  Write-Ok 'recorded in infra\generated\jumpbox.json (no secrets)'
  ($privOk.Count -eq $priv.Count) -and ($outOk.Count -eq $out.Count) -and [bool]$res.rdp
}

# ---------------------------------------------------------------------------- start / stop / status / connect

function Start-Jump {
  $info = Get-VmInfo
  if (-not $info) { throw 'The jump box is not deployed - run: pwsh scripts\jumpbox.ps1' }
  if ($info.powerState -ne 'VM running') {
    Write-Step "starting $vmName ($($info.powerState))"
    & az vm start -g $rg -n $vmName --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'az vm start failed' }
    Write-Ok 'running'
  } else {
    Write-Ok "$vmName is already running"
  }
  Write-Step 'waiting for the VM agent (the guest has booted)'
  $deadline = (Get-Date).AddMinutes(4)
  $ready = $false
  while ((Get-Date) -lt $deadline) {
    $iv = Get-AzJson @('vm', 'get-instance-view', '-g', $rg, '-n', $vmName)
    $agent = @($iv.instanceView.vmAgent.statuses) | Select-Object -First 1
    if ($agent -and $agent.displayStatus -eq 'Ready') { $ready = $true; break }
    Start-Sleep -Seconds 8
  }
  if ($ready) { Write-Ok 'ready for a Bastion connection' } else { Write-Warn2 'the agent is not Ready yet - give it a minute before you connect' }
}

function Stop-Jump {
  $info = Get-VmInfo
  if (-not $info) { throw 'The jump box is not deployed.' }
  Write-Step "deallocating $vmName (compute billing stops; the disk stays)"
  & az vm deallocate -g $rg -n $vmName --only-show-errors | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'az vm deallocate failed' }
  Write-Ok 'deallocated. Start it again with: pwsh scripts\jumpbox.ps1 -Start (or Start-JumpBox.bat)'
}

function Show-Status {
  $info = Get-VmInfo
  Write-Step "jump box in $rg"
  if (-not $info) { Write-Warn2 'not deployed - run: pwsh scripts\jumpbox.ps1'; return }
  Write-Host ("    {0,-14} {1}  [{2}]  {3}  private IP {4}" -f 'VM', $info.name, $info.powerState, $info.hardwareProfile.vmSize, $info.privateIps)
  $b = Get-BastionInfo
  if ($b) {
    $sku = if ($b.sku) { $b.sku.name } else { '?' }
    $prov = if ($b.properties) { $b.properties.provisioningState } else { '?' }
    Write-Host ("    {0,-14} {1}  ({2}, {3})" -f 'Bastion', $b.name, $sku, $prov)
  } else {
    Write-Host ("    {0,-14} none yet - the portal creates Bastion Developer on the first Connect" -f 'Bastion')
  }
  Write-Host ("    {0,-14} {1}" -f 'Password', $(if (Get-JumpSecret) { '.secrets\jumpbox.json (present, not shown)' } else { 'MISSING (.secrets\jumpbox.json)' }))
  Write-Host ("    {0,-14} daily 03:00 Central (it stays off until you start it again)" -f 'Auto-shutdown')
}

function Open-Portal {
  $info = Get-VmInfo
  if (-not $info) { throw 'The jump box is not deployed - run: pwsh scripts\jumpbox.ps1' }
  $url = "https://portal.azure.com/#@$($cfg.tenantDomain)/resource$($info.id)/overview"
  Write-Step 'opening the VM in the Azure portal'
  Start-Process $url
  Write-Ok $url
}

function Copy-Password {
  $py = Join-Path $script:RepoRoot '.venv\Scripts\python.exe'
  if (-not (Test-Path $py)) { throw 'The Python environment is missing (.venv). One-time setup from the repo root: python -m venv .venv ; .venv\Scripts\python.exe -m pip install -r requirements.txt' }
  $env:PYTHONIOENCODING = 'utf-8'
  Write-Step 'copying the jump-box password'
  & $py (Join-Path $PSScriptRoot 'jumpbox_clip.py') copy $ClipboardSeconds
  if ($LASTEXITCODE -ne 0) { throw 'Could not copy the password (see the message above).' }
}

function Write-ConnectSteps {
  Write-Host ''
  Write-Host '  Connect (the portal page for the VM is open):' -ForegroundColor Cyan
  Write-Host "    1. VM page > Connect > Bastion. User: $adminUser. Password: paste (Ctrl+V)."
  Write-Host '    2. In the VM open Edge, go to portal.azure.com and sign in as the operator account that deployed this platform.'
  Write-Host '       Foundry (ai.azure.com), AI Search, Cosmos, Storage and Key Vault pages now load: the VM resolves the private endpoints.'
  Write-Host '    3. Bastion Developer allows one session at a time. The VM stops itself at 03:00 Central.'
  Write-Host ''
}

# ---------------------------------------------------------------------------- remove

function Invoke-Remove {
  $targets = [ordered]@{
    "VM $vmName (its NIC and OS disk go with it)"               = { & az vm delete -g $rg -n $vmName --yes --only-show-errors }
    "auto-shutdown schedule shutdown-computevm-$vmName"         = { & az resource delete -g $rg -n "shutdown-computevm-$vmName" --resource-type Microsoft.DevTestLab/schedules --only-show-errors }
    "NIC $($names.jumpNic) (only if it was left behind)"        = { & az network nic delete -g $rg -n $names.jumpNic --only-show-errors }
    "OS disk $($names.jumpDisk) (only if it was left behind)"   = { & az disk delete -g $rg -n $names.jumpDisk --yes --only-show-errors }
    "Bastion Developer (any bastionHosts resource in $rg)"      = {
      foreach ($id in @(& az resource list -g $rg --resource-type Microsoft.Network/bastionHosts --query '[].id' -o tsv --only-show-errors)) {
        if ($id) { & az resource delete --ids $id --only-show-errors }
      }
    }
    "subnet $subnetName in $($names.vnet)"                      = { & az network vnet subnet delete -g $rg --vnet-name $names.vnet -n $subnetName --only-show-errors }
    "NSG $($names.jumpNsg)"                                     = { & az network nsg delete -g $rg -n $names.jumpNsg --only-show-errors }
  }
  Write-Step "removing the jump box from $rg (nothing else is touched)"
  foreach ($t in $targets.Keys) { Write-Host "    - $t" }
  Write-Host '    - local files: .secrets\jumpbox.json, infra\generated\jumpbox.json, infra\generated\params.jumpbox.json'
  if ($WhatIf) { Write-Warn2 'WhatIf: nothing was deleted'; return }
  if (-not $Force) {
    Write-Host "Type the VM name ($vmName) to continue:" -ForegroundColor Yellow
    if ((Read-Host) -ne $vmName) { throw 'Confirmation did not match - nothing was deleted.' }
  }
  foreach ($t in $targets.Keys) {
    Write-Host "    deleting $t"
    $null = & $targets[$t] 2>&1
  }
  foreach ($f in @($secretFile, $stateFile, (Join-Path $script:GenDir 'params.jumpbox.json'))) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
  Write-Ok 'removed'
  $left = @(& az resource list -g $rg --query "[?contains(name, 'jump')].name" -o tsv --only-show-errors 2>$null)
  if ($left.Count -gt 0 -and $left[0]) { Write-Warn2 "still present: $($left -join ', ')" }
}

# ---------------------------------------------------------------------------- dispatch

if ($Start -and $Stop) { throw '-Start and -Stop together make no sense.' }
Assert-AzContext

if ($Remove) { Invoke-Remove; return }

$acted = $false
if ($Stop)        { Stop-Jump;   $acted = $true }
if ($Start)       { Start-Jump;  $acted = $true }
if ($Status)      { Show-Status; $acted = $true }
if ($VerifyOnly)  { if (-not (Invoke-JumpVerify)) { Write-Warn2 'one or more checks failed - see above' }; $acted = $true }
if ($OpenPortal)  { Open-Portal; $acted = $true }
if ($CopyPassword){ Copy-Password; $acted = $true }
if (($OpenPortal -or $CopyPassword) -and -not $Stop) { Write-ConnectSteps }

if (-not $acted) { Invoke-DeployAndVerify }
