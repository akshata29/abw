#requires -Version 7
<#
.SYNOPSIS
  Agents Behind the Wall - run the Demo Console ON the jump box, so the whole demo is shown from inside the VNet.

.DESCRIPTION
  Why it exists: every data plane in this platform is private-endpoint-only, so the strongest proof is a browser inside the VNet.
  From the jump box the console's calls and the portal's data pages (Foundry Knowledge, AI Search, Cosmos, Storage) all travel over
  the private endpoints. The console stays what it is - a local app bound to 127.0.0.1 that uses the operator's own az sign-in -
  so it runs ON the VM. Hosting it in a Container App would need a second identity model, and the demo is about the first one.

  (no switch)  install or update, safe to repeat: start the VM if it is stopped; install Python 3.11, Azure CLI and PowerShell 7
               only if they are missing (every installer's signature is checked); upload the package only if it changed; build
               C:\abw\.venv only if the requirements changed; create the desktop shortcut "ABW Demo Console"; verify from inside the VM.
  -Status      read-only: what is on the VM and whether it matches this checkout
  -Verify      re-run the in-VM checks: a throw-away console on port 8799, private DNS, and a call to APIM with no token (expect 401)
  -Remove      delete C:\abw, C:\abw-stage and the shortcuts from the VM (Python, Azure CLI and PowerShell 7 stay installed; the persona files go with C:\abw)
  -IncludePersonaFiles
               opt-in, with a normal run: ALSO copy the persona sign-in files into C:\abw\.secrets on the VM - the persona list (personas.json, which holds
               the demo passwords), the one-time-code seeds (totp.json) if there are any, and the cached persona sign-ins (msal-test-*.json, refresh
               tokens). Nothing else from .secrets, ever. Only files the VM does not have yet are copied (the VM may hold newer refresh tokens); -Force
               replaces them. The folder is locked to SYSTEM and the VM's local admin, the upload is deleted from the VM, and the verify step tries a
               silent sign-in (never a device code) for every persona that has a cache.
  -RemovePersonaFiles
               delete every file in C:\abw\.secrets on the VM (the console stays installed)
  -WhatIf      build and scan the package and list what a real run would do; sends nothing and does not start the VM
  -Force       send the package even if it has not changed; with -IncludePersonaFiles replace persona files the VM already has;
               with -Remove or -RemovePersonaFiles skip the confirmation

  What goes to the VM is a whitelist (Get-PackageSources): the console, the agent and demo code, the policy XML, the KQL and Sentinel
  packs, the generated infra JSON (resource names, no keys) and the SCRUBBED proof evidence. Never .secrets (the persona files above travel
  separately, only on request), the legacy key, raw evidence, the deck or the docs. Before anything is sent the staged package is scanned
  for secret patterns and for every secret value held in .secrets (compared in memory only; values are never printed or stored).

  Not automated, and said so: the Bastion browser session and the one-time Azure sign-in on the VM (a device code, as the operator account that deployed this platform).
  The VM keeps that sign-in in the local admin's own token cache; the package carries no credential. A persona that has no cached sign-in
  signs in once on the VM with a device code (Acting as > Sign in), exactly as on the laptop.

.EXAMPLE
  pwsh scripts\jumpbox-console.ps1 -WhatIf
  pwsh scripts\jumpbox-console.ps1
  pwsh scripts\jumpbox-console.ps1 -IncludePersonaFiles
  pwsh scripts\jumpbox-console.ps1 -Status
  pwsh scripts\jumpbox-console.ps1 -RemovePersonaFiles
#>
[CmdletBinding()]
param(
  [switch]$Status,
  [switch]$Verify,
  [switch]$Remove,
  [switch]$IncludePersonaFiles,
  [switch]$RemovePersonaFiles,
  [switch]$WhatIf,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"
Add-Type -AssemblyName System.IO.Compression.FileSystem

$cfg        = Get-AbwConfig
$names      = Get-AbwNames $cfg
$rg         = $cfg.rgName
$vmName     = $names.jumpVm
$root       = $script:RepoRoot
$stateFile  = Join-Path $script:GenDir 'jumpbox.json'
$setupFile  = Join-Path $PSScriptRoot 'jumpbox-console-setup.ps1'
$adminUser  = 'abwadmin'
$apimHost   = "$($names.apim).azure-api.net"
$chunkChars = 140000   # base64 characters per upload call; a multiple of 4, and well under the run-command script limit

# What the VM installs when it is missing (each installer must carry a valid Python Software Foundation / Microsoft signature).
$tools = [ordered]@{
  python = [ordered]@{ version = '3.11.9'; url = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' }
  az     = [ordered]@{ version = '2.91.0'; url = 'https://azcliprod.blob.core.windows.net/msi/azure-cli-2.91.0-x64.msi' }
  pwsh   = [ordered]@{ version = '7.6.8';  url = 'https://github.com/PowerShell/PowerShell/releases/download/v7.6.8/PowerShell-7.6.8-win-x64.msi' }
}

# infra\generated files the console reads (resource names and ids; the jump box, parameter and track-b files are left out).
$generatedJson = @('agents', 'apim', 'apis', 'apps', 'budget', 'config', 'connections', 'entra', 'foundry', 'foundryrbac', 'frontdoor',
                   'governance', 'images', 'images-seed', 'network', 'observability', 'platform', 'policy', 'preflight', 'seed')

# ---------------------------------------------------------------------------- helpers

function Limit([string]$Text, [int]$Max = 500) { if ($Text.Length -gt $Max) { $Text.Substring(0, $Max) + '...' } else { $Text } }
function Nz($Value, [string]$Default) { if ($Value) { [string]$Value } else { $Default } }
function Format-Size([long]$Bytes) { if ($Bytes -ge 1MB) { '{0:N1} MB' -f ($Bytes / 1MB) } else { '{0:N0} KB' -f ($Bytes / 1KB) } }
function Get-Sha256Hex([byte[]]$Bytes) { [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant() }

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

# A $null value removes the key.
function Update-State([System.Collections.IDictionary]$Patch) {
  $cur = [ordered]@{}
  $old = Read-Json $stateFile
  if ($old) { foreach ($p in $old.PSObject.Properties) { $cur[$p.Name] = $p.Value } }
  foreach ($k in $Patch.Keys) { if ($null -eq $Patch[$k]) { $cur.Remove($k) } else { $cur[$k] = $Patch[$k] } }
  Save-Json $stateFile $cur
}

function Write-Check([string]$Label, [bool]$Ok, [string]$Detail) {
  $line = "{0,-11} {1}" -f $Label, $Detail
  if ($Ok) { Write-Ok $line } else { Write-Warn2 $line }
}

function Assert-VmRunning([bool]$StartIfStopped) {
  $info = Get-VmInfo
  if (-not $info) { throw 'The jump box is not deployed - run: pwsh scripts\jumpbox.ps1' }
  if ($info.powerState -eq 'VM running') { return }
  if (-not $StartIfStopped) { throw "$vmName is '$($info.powerState)'. Start it first: pwsh scripts\jumpbox.ps1 -Start" }
  & "$PSScriptRoot\jumpbox.ps1" -Start
  $info = Get-VmInfo
  if ($info.powerState -ne 'VM running') { throw "$vmName is still '$($info.powerState)'" }
}

# ---------------------------------------------------------------------------- the package (whitelist, stage, scan, hash, zip)

function Get-RelPath([string]$Full) { $Full.Substring($root.Length).TrimStart('\') }

# Everything that may go to the VM. Anything not listed here is never sent.
function Get-PackageSources {
  $list = [System.Collections.Generic.List[object]]::new()
  $skipped = [System.Collections.Generic.List[string]]::new()
  $add = {
    param([string]$Rel)
    $src = Join-Path $root $Rel
    if (Test-Path -LiteralPath $src -PathType Leaf) { $list.Add([pscustomobject]@{ Rel = $Rel; Src = $src }) } else { $skipped.Add($Rel) }
  }
  foreach ($f in Get-ChildItem (Join-Path $root 'console') -File -Filter '*.py') { & $add ('console\' + $f.Name) }
  foreach ($f in Get-ChildItem (Join-Path $root 'console\web') -File -Recurse) { & $add (Get-RelPath $f.FullName) }
  # abw_tokens.py reads the persona file at import and nothing imports it; scrub_evidence.py is the laptop-side tool that makes the scrubbed set.
  foreach ($f in Get-ChildItem (Join-Path $root 'demo') -File -Filter '*.py' | Where-Object { $_.Name -notin @('abw_tokens.py', 'scrub_evidence.py') }) { & $add ('demo\' + $f.Name) }
  & $add 'demo\stage.ps1'
  foreach ($f in Get-ChildItem (Join-Path $root 'src\agent') -File -Filter '*.py') { & $add ('src\agent\' + $f.Name) }
  foreach ($n in $generatedJson) { & $add ('infra\generated\' + $n + '.json') }
  foreach ($f in Get-ChildItem (Join-Path $root 'infra\apim\policies') -File -Filter '*.xml') { & $add ('infra\apim\policies\' + $f.Name) }
  foreach ($f in Get-ChildItem (Join-Path $root 'observability') -File -Recurse | Where-Object { $_.FullName -notmatch '\\__pycache__\\' -and $_.Extension -ne '.pyc' }) { & $add (Get-RelPath $f.FullName) }
  & $add 'identity\Use-AdminAsPersona.ps1'
  foreach ($n in @('common', 'client-allowlist', 'kill-switch', 'jumpbox-console-start')) { & $add ('scripts\' + $n + '.ps1') }
  [pscustomobject]@{ Files = $list; Skipped = $skipped }
}

function Copy-IntoStage([string]$Stage, [string]$Src, [string]$Rel) {
  $dest = Join-Path $Stage $Rel
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
  Copy-Item -LiteralPath $Src -Destination $dest -Force
}

function Write-StageText([string]$Stage, [string]$Rel, [string]$Text) {
  $dest = Join-Path $Stage $Rel
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
  [IO.File]::WriteAllText($dest, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-VmReadme {
@"
Agents Behind the Wall - Demo Console on the jump box
=====================================================
This VM sits inside the VNet, so every private endpoint resolves here. The console runs ON this VM.

Start
  Double-click "ABW Demo Console" on the desktop. Edge opens http://127.0.0.1:8787/ when the console is up.
  First start only: one Azure sign-in with a device code. Sign in as $($cfg.operatorUpn) ($($cfg.tenantDomain)).
  Closing the console window stops the console.

Where things are
  C:\abw                   the console, the agent code, the policy XML, the KQL and Sentinel packs, scrubbed proof evidence
  C:\abw\logs              console logs
  C:\abw\.secrets          persona sign-in files. Empty unless the laptop script was run with -IncludePersonaFiles.
                           Locked to SYSTEM and $adminUser only; treat whatever is in it as a secret.
  C:\abw-stage\setup.log   deployment log (C:\abw-stage\logs has the installer and pip logs)
  The package itself holds no secrets: no keys, tokens, persona passwords or one-time-code seeds.
  The Azure CLI sign-in lives in C:\Users\$adminUser\.azure, the operator's own token cache.

Personas (Act 7)
  A persona with a cached sign-in in C:\abw\.secrets acts straight away. A persona without one signs in once on this VM
  with a device code (Acting as > Sign in), the same way as on the laptop. The password and one-time-code clipboard
  helpers only work for personas whose files were copied.

Update or remove (from the laptop, in the repo)
  pwsh scripts\jumpbox-console.ps1                         install or update, only what changed
  pwsh scripts\jumpbox-console.ps1 -IncludePersonaFiles    same, and copy the persona sign-in files the VM does not have yet
  pwsh scripts\jumpbox-console.ps1 -Status                 read-only
  pwsh scripts\jumpbox-console.ps1 -Verify                 re-check from inside the VM
  pwsh scripts\jumpbox-console.ps1 -RemovePersonaFiles     delete the files in C:\abw\.secrets (the console stays)
  pwsh scripts\jumpbox-console.ps1 -Remove                 delete C:\abw and the shortcuts (Python, Azure CLI and PowerShell 7 stay)
"@
}

# Secret values held in .secrets, kept in memory only so the staged package can be checked for them.
# Properties that only describe a credential (credential_type = AccessToken, token_type, key_id ...) hold labels, not secrets.
$script:SecretMetaName = '(?i)(^|_)(type|kind|name|id|scope|scopes|environment|realm|authority|username|provider|version|algorithm|format|status|mode)$'
function Add-SecretLeaves($Node, [string]$Name, $Set) {
  if ($null -eq $Node) { return }
  if ($Node -is [string]) {
    if ($Name -match '(?i)pass|secret|seed|key|token|totp|credential' -and $Name -notmatch $script:SecretMetaName -and $Node.Length -ge 10 -and $Node -notmatch '^https?://' -and $Node -notmatch '^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$') { [void]$Set.Add($Node) }
    return
  }
  if ($Node -is [pscustomobject]) {
    foreach ($p in $Node.PSObject.Properties) { Add-SecretLeaves $p.Value $p.Name $Set }
    return
  }
  if ($Node -is [System.Collections.IEnumerable]) { foreach ($i in $Node) { Add-SecretLeaves $i $Name $Set } }
}

function Get-KnownSecretValues {
  $set = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  $files = 0
  foreach ($f in @(Get-ChildItem $script:SecretsDir -File -Force -ErrorAction SilentlyContinue)) {
    if ($f.Extension -eq '.json') {
      try { $j = Get-Content -Raw -LiteralPath $f.FullName | ConvertFrom-Json } catch { continue }
      $files++
      Add-SecretLeaves $j '' $set
    } elseif ($f.Extension -eq '.txt') {
      $t = (Get-Content -Raw -LiteralPath $f.FullName).Trim()
      $files++
      if ($t.Length -ge 10 -and $t.Length -le 300 -and $t -notmatch '\s') { [void]$set.Add($t) }
    }
  }
  [pscustomobject]@{ Values = @($set); Files = $files }
}

# Findings are "<file> : <rule>" only - never a matched value.
function Test-StageSafety([string]$Stage) {
  $known = Get-KnownSecretValues
  $blockedName = '(?i)^(personas|totp|agent-client|vendor-api-key|jumpbox)\.(json|txt)$|^msal-.*\.json$|^params\..*\.json$|\.(pfx|pem|key|tfstate)$|^\.env'
  $textExt = @('.py', '.ps1', '.js', '.css', '.html', '.json', '.xml', '.kql', '.md', '.txt', '.url', '.svg', '.csv', '.yml', '.yaml', '.toml', '.cfg', '.ini', '.bat', '.sh')
  $rules = [ordered]@{
    'private key'       = '-----BEGIN [A-Z ]*PRIVATE KEY-----'
    'jwt'               = 'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.'
    'storage account key' = '(?i)AccountKey=[A-Za-z0-9+/=]{20,}'
    'shared access key' = '(?i)SharedAccessKey=[A-Za-z0-9+/=]{20,}'
    'sas signature'     = '[?&]sig=[A-Za-z0-9%+/=]{20,}'
    'connection string' = 'DefaultEndpointsProtocol='
  }
  $jsonSecret = '(?i)"(password|secret|client_secret|primaryKey|secondaryKey|apiKey|subscriptionKey|access_token|refresh_token)"\s*:\s*"(?!\*+"|<|\[|redacted)[^"]{6,}"'
  $findings = [System.Collections.Generic.List[string]]::new()
  $scanned = 0
  foreach ($f in Get-ChildItem $Stage -Recurse -File) {
    $rel = $f.FullName.Substring($Stage.Length).TrimStart('\')
    $scanned++
    if ($f.Name -match $blockedName) { $findings.Add("$rel : blocked file name") }
    if ($textExt -notcontains $f.Extension.ToLowerInvariant()) { continue }
    $text = [IO.File]::ReadAllText($f.FullName)
    foreach ($r in $rules.Keys) { if ($text -match $rules[$r]) { $findings.Add("$rel : $r pattern") } }
    if ($f.Extension -eq '.json' -and $text -match $jsonSecret) { $findings.Add("$rel : secret-looking JSON value") }
    foreach ($v in $known.Values) {
      if ($text.IndexOf($v, [StringComparison]::Ordinal) -ge 0) { $findings.Add("$rel : contains a value held in .secrets"); break }
    }
  }
  [pscustomobject]@{ Findings = @($findings | Select-Object -Unique); Scanned = $scanned; KnownValues = $known.Values.Count; KnownFiles = $known.Files }
}

function New-Stage {
  $stage = Join-Path ([IO.Path]::GetTempPath()) ('abw-vm-stage-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $stage | Out-Null
  $src = Get-PackageSources
  foreach ($e in $src.Files) { Copy-IntoStage $stage $e.Src $e.Rel }

  # The scrubbed proof evidence is what the VM shows; raw evidence stays on the laptop.
  $evDir = Join-Path $root 'demo\evidence-scrubbed'
  if (-not (Test-Path (Join-Path $evDir 'scoreboard.json'))) { throw 'demo\evidence-scrubbed\scoreboard.json is missing - run: python demo\scrub_evidence.py' }
  foreach ($f in Get-ChildItem $evDir -File) { Copy-IntoStage $stage $f.FullName ('demo\evidence\' + $f.Name) }

  # requirements without the deck builder, plus the laptop's exact versions as constraints so the VM resolves the same tree.
  $req = @(Get-Content (Join-Path $root 'requirements.txt') | Where-Object { $_ -notmatch '^\s*python-pptx\b' })
  Write-StageText $stage 'requirements.txt' (($req -join "`n") + "`n")
  $py = Join-Path $root '.venv\Scripts\python.exe'
  $constraints = $false
  if (Test-Path $py) {
    $freeze = @(& $py -m pip freeze 2>$null)
    if ($LASTEXITCODE -eq 0) {
      $pins = @($freeze | Where-Object { $_ -match '^[A-Za-z0-9_.\-]+==\S+$' -and $_ -notmatch '^(pip|setuptools|wheel)==' } | Sort-Object)
      if ($pins.Count -gt 0) { Write-StageText $stage 'constraints.txt' (($pins -join "`n") + "`n"); $constraints = $true }
    }
  }
  if (-not $constraints) { Write-Warn2 'no .venv on this machine: the VM resolves the transitive packages itself (the direct ones stay pinned)' }
  Write-StageText $stage 'README-VM.txt' (Get-VmReadme)
  [pscustomobject]@{ Path = $stage; Skipped = @($src.Skipped); Constraints = $constraints }
}

function Get-StageItems([string]$Stage) {
  foreach ($f in Get-ChildItem $Stage -Recurse -File) {
    [pscustomobject]@{
      Rel  = $f.FullName.Substring($Stage.Length).TrimStart('\')
      Size = $f.Length
      Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $f.FullName).Hash.ToLowerInvariant()
    }
  }
}

function Show-Manifest($Items) {
  $groups = $Items | Group-Object { $p = $_.Rel -split '\\'; if ($p.Count -gt 1) { $p[0] + '\' } else { '(root)' } } | Sort-Object Name
  foreach ($g in $groups) {
    $bytes = ($g.Group | Measure-Object Size -Sum).Sum
    Write-Host ('    {0,-14} {1,4} files {2,10}' -f $g.Name, $g.Count, (Format-Size $bytes))
  }
}

# Stages the whitelist; -Scan runs the safety scan (throws on a finding); -Zip also builds the upload zip.
function Build-Package([switch]$Scan, [switch]$Zip) {
  Write-Step "staging the package from $root (whitelist only)"
  $stage = New-Stage
  $pkg = [ordered]@{ Stage = $stage.Path; ZipPath = $null; Items = @(); ContentSha = ''; Bytes = 0; ZipSha = ''; ZipBytes = 0; Parts = 0 }
  try {
    foreach ($s in $stage.Skipped) { Write-Warn2 "not found, left out: $s" }
    $items = @(Get-StageItems $stage.Path)
    $pkg.Items = $items
    $pkg.Bytes = ($items | Measure-Object Size -Sum).Sum
    $lines = ($items | Sort-Object Rel | ForEach-Object { $_.Rel + '|' + $_.Hash }) -join "`n"
    $pkg.ContentSha = Get-Sha256Hex ([Text.Encoding]::UTF8.GetBytes($lines))
    Write-Ok ("{0} files, {1}; content SHA-256 {2}" -f $items.Count, (Format-Size $pkg.Bytes), $pkg.ContentSha.Substring(0, 16))
    Show-Manifest $items

    if ($Scan) {
      $safety = Test-StageSafety $stage.Path
      if ($safety.Findings.Count -gt 0) {
        foreach ($f in $safety.Findings) { Write-Warn2 $f }
        throw "The package safety scan found $($safety.Findings.Count) problem(s) (listed above; values are never printed). Nothing was sent."
      }
      Write-Ok ("safety scan: {0} files, no blocked names, no secret patterns, none of {1} secret values from {2} .secrets files (compared in memory, never printed)" -f $safety.Scanned, $safety.KnownValues, $safety.KnownFiles)
    }

    if ($Zip) {
      $zipPath = $stage.Path + '.zip'
      if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
      $z = [IO.Compression.ZipFile]::Open($zipPath, [IO.Compression.ZipArchiveMode]::Create)
      try {
        foreach ($i in ($items | Sort-Object Rel)) {
          [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, (Join-Path $stage.Path $i.Rel), ($i.Rel -replace '\\', '/'), [IO.Compression.CompressionLevel]::Optimal)
        }
      } finally { $z.Dispose() }
      $bytes = [IO.File]::ReadAllBytes($zipPath)
      $pkg.ZipPath = $zipPath
      $pkg.ZipBytes = $bytes.Length
      $pkg.ZipSha = Get-Sha256Hex $bytes
      $b64Len = 4 * [math]::Ceiling($bytes.Length / 3)
      $pkg.Parts = [int][math]::Ceiling($b64Len / $chunkChars)
      Write-Ok ("zip {0}, SHA-256 {1}; {2} upload parts" -f (Format-Size $pkg.ZipBytes), $pkg.ZipSha.Substring(0, 16), $pkg.Parts)
    }
  } catch {
    Remove-Package ([pscustomobject]$pkg)
    throw
  }
  [pscustomobject]$pkg
}

function Remove-Package($Pkg) {
  if ($Pkg -and $Pkg.Stage -and (Test-Path $Pkg.Stage)) { Remove-Item $Pkg.Stage -Recurse -Force -ErrorAction SilentlyContinue }
  if ($Pkg -and $Pkg.ZipPath -and (Test-Path $Pkg.ZipPath)) { Remove-Item $Pkg.ZipPath -Force -ErrorAction SilentlyContinue }
}

# ---------------------------------------------------------------------------- the persona files (opt-in; never part of the package)

# Only these names are ever eligible: the persona list, the one-time-code seeds and the cached persona sign-ins.
# agent-client.json, jumpbox.json (the VM's admin password) and vendor-api-key.txt never qualify.
$personaNameRx = '^(personas|totp)\.json$|^msal-test-[a-z0-9]+\.json$'

function Get-PersonaSources {
  @(Get-ChildItem -LiteralPath $script:SecretsDir -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -match $personaNameRx } | Sort-Object Name)
}

# Zips the given persona files (flat names) into a temp file. The caller deletes it (Remove-Package). Nothing is printed from the files.
function New-PersonaZip([object[]]$Files) {
  $zipPath = Join-Path ([IO.Path]::GetTempPath()) "abw-vm-personas-$([guid]::NewGuid().ToString('N')).zip"
  $pkg = [ordered]@{ Stage = $null; ZipPath = $zipPath; ZipBytes = 0; ZipSha = ''; Parts = 0 }
  try {
    $z = [IO.Compression.ZipFile]::Open($zipPath, [IO.Compression.ZipArchiveMode]::Create)
    try {
      foreach ($f in $Files) {
        [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $f.FullName, $f.Name, [IO.Compression.CompressionLevel]::Optimal)
      }
    } finally { $z.Dispose() }
    $bytes = [IO.File]::ReadAllBytes($zipPath)
    $pkg.ZipBytes = $bytes.Length
    $pkg.ZipSha = Get-Sha256Hex $bytes
    $b64Len = 4 * [math]::Ceiling($bytes.Length / 3)
    $pkg.Parts = [int][math]::Ceiling($b64Len / $chunkChars)
  } catch {
    Remove-Package ([pscustomobject]$pkg)
    throw
  }
  [pscustomobject]$pkg
}

# ---------------------------------------------------------------------------- talking to the VM (Azure run-command, one at a time)

# Sends a script to the VM and returns its stdout / stderr text. Retries while the extension is busy or the agent is not ready.
function Invoke-VmScript([string]$Body, [string]$What) {
  $tmp = Join-Path ([IO.Path]::GetTempPath()) "abw-vmrun-$([guid]::NewGuid().ToString('N')).ps1"
  [IO.File]::WriteAllText($tmp, $Body, (New-Object System.Text.UTF8Encoding($false)))
  try {
    $raw = Invoke-Retry -What $What -Attempts 8 -DelaySec 8 -Script {
      $o = & az vm run-command invoke -g $rg -n $vmName --command-id RunPowerShellScript --scripts "@$tmp" -o json --only-show-errors 2>&1
      if ($LASTEXITCODE -ne 0) { throw (($o | Out-String).Trim()) }
      $o
    }
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
  $obj = ($raw | Out-String) | ConvertFrom-Json
  $out = ($obj.value | Where-Object { $_.code -like '*StdOut*' } | Select-Object -First 1).message
  $err = ($obj.value | Where-Object { $_.code -like '*StdErr*' } | Select-Object -First 1).message
  if (-not $out -and -not $err) { $out = ($obj.value | Select-Object -First 1).message }
  if ($out -match '(?s)\[stdout\](.*?)(\[stderr\]|$)') { $out = $Matches[1] }
  [pscustomobject]@{ Out = [string]$out; Err = [string]$err }
}

function Get-LastJsonLine([string]$Text) {
  @($Text -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
}

# Runs the in-VM phases and returns the parsed result ({ ok, phases, <phase> = {...} }).
function Send-Setup([string[]]$Phases, [int]$Parts = 0, [string]$ZipSha = '', [string]$ContentSha = '', [int]$PersonaParts = 0, [string]$PersonaZipSha = '', [bool]$PersonaOverwrite = $false) {
  $map = [ordered]@{
    '__PHASES__'       = ($Phases -join ',')
    '__ADMIN_USER__'   = $adminUser
    '__ZIP_SHA__'      = $ZipSha
    '__CONTENT_SHA__'  = $ContentSha
    '__PARTS__'        = [string]$Parts
    '__PERSONA_COUNT__'     = [string]$PersonaParts
    '__PERSONA_SHA__'       = $PersonaZipSha
    '__PERSONA_OVERWRITE__' = $(if ($PersonaOverwrite) { '1' } else { '0' })
    '__TENANT_ID__'    = $cfg.tenantId
    '__TENANT_DOMAIN__' = $cfg.tenantDomain
    '__APIM_HOST__'    = $apimHost
    '__PY_VER__'       = $tools.python.version
    '__PY_URL__'       = $tools.python.url
    '__AZ_VER__'       = $tools.az.version
    '__AZ_URL__'       = $tools.az.url
    '__PS_VER__'       = $tools.pwsh.version
    '__PS_URL__'       = $tools.pwsh.url
  }
  $body = [IO.File]::ReadAllText($setupFile)
  foreach ($k in $map.Keys) { $body = $body.Replace($k, [string]$map[$k]) }
  if ($body -match '__[A-Z][A-Z_]*__') { throw "an unfilled placeholder is left in the setup script: $($Matches[0])" }
  if ($body -match '[^\x00-\x7F]') { throw 'the in-VM setup script must be plain ASCII' }
  $r = Invoke-VmScript $body "run-command ($($Phases -join ', '))"
  $line = Get-LastJsonLine $r.Out
  if (-not $line) { throw "The VM script printed no JSON. stdout: $(Limit $r.Out.Trim() 600) stderr: $(Limit $r.Err.Trim() 600)" }
  $line | ConvertFrom-Json
}

# Uploads a zip as base64 parts (each part is one small run-command that writes a file); the 'package' phase (with -Persona: the 'personas'
# phase) reassembles it. -Persona: the parts go to a folder only SYSTEM can open, and every upload script starts with a marker comment so
# the 'personas' phase can empty the copy of that script that the run-command agent keeps.
function Send-PackageParts($Pkg, [switch]$Persona) {
  $dir = if ($Persona) { 'C:\abw-stage\persona-parts' } else { 'C:\abw-stage\parts' }
  $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($Pkg.ZipPath))
  for ($i = 0; $i -lt $Pkg.Parts; $i++) {
    $start = $i * $chunkChars
    $chunk = $b64.Substring($start, [math]::Min($chunkChars, $b64.Length - $start))
    $name = 'part-{0:D4}.b64' -f ($i + 1)
    $wrapped = for ($p = 0; $p -lt $chunk.Length; $p += 4000) { $chunk.Substring($p, [math]::Min(4000, $chunk.Length - $p)) }
    $lines = @()
    if ($Persona) { $lines += '# ABW-PERSONA-PAYLOAD' }
    $lines += '$ErrorActionPreference = ''Stop'''
    $lines += ('$d = ''' + $dir + '''')
    $lines += 'New-Item -ItemType Directory -Force -Path $d | Out-Null'
    if ($Persona) {
      $lines += '$null = icacls.exe $d /inheritance:r /grant:r ''SYSTEM:(OI)(CI)F'''
      $lines += 'if ($LASTEXITCODE -ne 0) { throw "icacls on the upload folder returned $LASTEXITCODE" }'
    }
    if ($i -eq 0) { $lines += 'Get-ChildItem -Path $d -Filter ''part-*.b64'' -ErrorAction SilentlyContinue | Remove-Item -Force' }
    $lines += '$t = @'''
    $lines += $wrapped
    $lines += '''@'
    $lines += '$t = $t -replace ''\s'', '''''
    $lines += ('[IO.File]::WriteAllText((Join-Path $d ''' + $name + '''), $t, [Text.Encoding]::ASCII)')
    $lines += ('Write-Output (''{"part":' + ($i + 1) + ',"chars":'' + $t.Length + ''}'')')
    Write-Host ("    uploading part {0}/{1} ({2} KB)" -f ($i + 1), $Pkg.Parts, [math]::Round($chunk.Length / 1024)) -ForegroundColor DarkGray
    $r = Invoke-VmScript ($lines -join "`r`n") "upload part $($i + 1)/$($Pkg.Parts)"
    $json = Get-LastJsonLine $r.Out
    if (-not $json) { throw "upload part $($i + 1) printed no JSON. stdout: $(Limit $r.Out.Trim() 400) stderr: $(Limit $r.Err.Trim() 400)" }
    $ack = $json | ConvertFrom-Json
    if ([int]$ack.chars -ne $chunk.Length) { throw "upload part $($i + 1): the VM stored $($ack.chars) characters, expected $($chunk.Length)" }
  }
  Write-Ok ("{0} parts stored on the VM (reassembled and SHA-256 checked by the {1} step)" -f $Pkg.Parts, $(if ($Persona) { 'personas' } else { 'package' }))
}

# ---------------------------------------------------------------------------- reporting

function Show-Probe($P, [string]$ContentSha) {
  $toolsOk = [bool]($P.python -and $P.az -and $P.pwsh)
  Write-Check 'tools' $toolsOk ("Python {0}, Azure CLI {1}, PowerShell {2}" -f (Nz $P.python 'missing'), (Nz $P.az 'missing'), (Nz $P.pwsh 'missing'))
  if ($P.contentSha) {
    $same = ($P.contentSha -eq $ContentSha)
    Write-Check 'package' ($same -and @($P.missing).Count -eq 0) ("{0} files on the VM, deployed {1}; {2}" -f $P.files, $P.deployedAt, $(if ($same) { 'identical to this checkout' } else { 'differs from this checkout (a normal run updates it)' }))
  } else {
    Write-Check 'package' $false 'not deployed yet'
  }
  if (@($P.missing).Count -gt 0 -and $P.contentSha) { Write-Warn2 ("files missing on the VM: {0}" -f (@($P.missing) -join ', ')) }
  Write-Check 'venv' ([bool]$P.venv) $(if ($P.venv) { 'C:\abw\.venv present' } else { 'not built yet' })
  Write-Check 'shortcut' ([bool]$P.shortcut) $(if ($P.shortcut) { 'desktop shortcut "ABW Demo Console" present' } else { 'not created yet' })
  Write-Check 'console' $true $(if ($P.consoleRunning) { 'a console is running on the VM right now' } else { 'not running (it starts from the desktop shortcut)' })
  Write-Check 'az sign-in' ([bool]$P.azUser) $(if ($P.azUser) { "$($P.azUser) (tenant $($P.azTenant)) - the one-time sign-in on the VM is done" } else { 'none yet - the first start of the console asks for it (one device code)' })
  $nPersona = [int]$P.personaFiles
  if ($nPersona -eq 0) {
    Write-Check 'persona files' $true 'none on the VM (nothing is copied unless -IncludePersonaFiles)'
  } else {
    $acl = if ($P.personaFolderLocked) { 'folder open to ' + (@($P.personaFolderPrincipals) -join ' + ') + ' only' } else { 'folder NOT locked down (open to ' + (@($P.personaFolderPrincipals) -join ', ') + '); a normal run locks it' }
    Write-Check 'persona files' ([bool]$P.personaFolderLocked) ("{0} in C:\abw\.secrets ({1}); {2}" -f $nPersona, (@($P.personaNames) -join ', '), $acl)
  }
}

function Show-Phases($Res) {
  foreach ($ph in @($Res.phases)) {
    $r = $Res.$ph
    if (-not $r.ok) { Write-Warn2 ("{0,-11} FAILED: {1}" -f $ph, (Nz $r.error 'see C:\abw-stage\setup.log on the VM')); continue }
    switch ($ph) {
      'tools' {
        Write-Check 'tools' $true ("installed: {0}; already there: {1}; Python {2}, Azure CLI {3}, PowerShell {4}" -f (Nz (@($r.installed) -join ', ') 'nothing'), (Nz (@($r.skipped) -join ', ') 'nothing'), $r.python, $r.az, $r.pwsh)
        if ($r.reboot) { Write-Warn2 'an installer asked for a reboot; restart the VM from the portal before the demo (the console itself does not need it)' }
      }
      'package' { Write-Check 'package' $true ("{0} files, zip {1}, SHA-256 matched; {2} running console process(es) stopped before the copy" -f $r.files, (Format-Size $r.zipBytes), $r.stoppedConsole) }
      'venv' { Write-Check 'venv' $true ("{0}; packages {1}; imports ok" -f $r.python, $(if ($r.pipRan) { 'installed from requirements + constraints' } else { 'unchanged since the last run' })) }
      'launcher' {
        Write-Check 'shortcut' $true ("desktop shortcut ""ABW Demo Console"" + {0} portal link(s)" -f $r.urls)
        if ($r.secretsError) { Write-Warn2 ("could not lock down C:\abw\.secrets: {0}" -f $r.secretsError) }
      }
      'personas' {
        $copied = @($r.copied)
        $kept = @($r.kept)
        Write-Check 'personas' $true ("copied {0}{1}; kept {2}{3}; C:\abw\.secrets open to {4} only; upload scratch folder deleted" -f $copied.Count, $(if ($copied.Count) { ' (' + ($copied -join ', ') + ')' } else { '' }), $kept.Count, $(if ($kept.Count) { ' that the VM already had (' + ($kept -join ', ') + ')' } else { '' }), (@($r.principals) -join ' + '))
        if ([int]$r.scriptCopiesCleared -gt 0) { Write-Ok ("emptied {0} copy(ies) of the upload script that the run-command agent keeps in C:\Packages\Plugins" -f $r.scriptCopiesCleared) }
        if ([int]$r.scriptCopiesLeft -gt 0) { Write-Warn2 ("{0} copy(ies) of the upload script could not be emptied; local users on the VM can read them until the run-command agent rotates them (it keeps the last two scripts)" -f $r.scriptCopiesLeft) }
      }
      'personas-remove' {
        Write-Check 'personas' $true ("removed {0} file(s) from C:\abw\.secrets{1}; the folder stays, locked to SYSTEM + {2}" -f @($r.removed).Count, $(if (@($r.removed).Count) { ' (' + (@($r.removed) -join ', ') + ')' } else { '' }), $adminUser)
        if ([int]$r.scriptCopiesLeft -gt 0) { Write-Warn2 ("{0} copy(ies) of the upload script could not be emptied (run-command agent folder)" -f $r.scriptCopiesLeft) }
      }
      'remove' { Write-Check 'remove' $true ("removed: {0}" -f (@($r.removed) -join ', ')) }
    }
  }
}

# Returns $true when the in-VM verification passed.
function Show-Verify($V) {
  Write-Check 'tools' ([bool]($V.python -and $V.az -and $V.pwsh)) ("Python {0}, Azure CLI {1}, PowerShell {2}" -f (Nz $V.python 'missing'), (Nz $V.az 'missing'), (Nz $V.pwsh 'missing'))
  Write-Check 'package' ([bool]$V.package) $(if ($V.package) { 'the VM copy is identical to this checkout' } else { 'the VM copy differs from this checkout (run again without -Verify to update it)' })
  Write-Check 'files' (@($V.missing).Count -eq 0) $(if (@($V.missing).Count -eq 0) { 'every key file is present' } else { 'missing: ' + (@($V.missing) -join ', ') })
  Write-Check 'venv' ([bool]$V.venv) $(if ($V.venv) { 'C:\abw\.venv present' } else { 'missing' })
  $c = $V.console
  $consoleOk = ($c.health -eq 200 -and $c.ui -eq 200 -and $c.catalog -eq 200)
  Write-Check 'console' $consoleOk ("throw-away instance on 127.0.0.1:{0}: health {1}, UI {2}, catalog {3}, scoreboard {4} ({5} proofs), policy {6}, personas {7}" -f $c.port, $c.health, $c.ui, $c.catalog, $c.scoreboard, $c.proofs, $c.policy, $c.personas)
  if ($V.consoleLog) { Write-Warn2 "console log tail: $($V.consoleLog)" }
  $a = $V.apim
  Write-Check 'APIM' ([bool]($a.private -and $a.noToken -eq 401)) ("{0} -> {1} ({2}); a call with no token answers HTTP {3}{4}" -f $a.host, (@($a.ips) -join ','), $(if ($a.private) { 'private endpoint' } else { 'NOT a 10.x address' }), $a.noToken, $(if ($a.prmHeader) { ' with the protected-resource-metadata challenge' } else { '' }))
  $rows = @($c.personaSignIns | Where-Object { $_ })
  foreach ($row in $rows) {
    $who = Nz $row.upn $row.id
    if ([int]$row.of -gt 0 -and [int]$row.ok -eq [int]$row.of) {
      Write-Check ("persona $($row.id)") $true ("silent sign-in from the VM worked: {0}/{1} MCP tokens as {2}{3}" -f $row.ok, $row.of, $who, $(if (@($row.roles).Count) { '; roles: ' + (@($row.roles) -join ', ') } else { '' }))
    } elseif ([int]$row.ok -gt 0) {
      Write-Check ("persona $($row.id)") $false ("silent sign-in worked for {0}/{1} MCP servers as {2}; failed: {3}" -f $row.ok, $row.of, $who, $row.error)
    } else {
      Write-Check ("persona $($row.id)") $false ("silent sign-in from the VM did NOT work: {0}" -f (Nz $row.error 'no detail'))
    }
  }
  if ($rows.Count -eq 0) {
    Write-Check 'personas' $true $(if ($c.personaSignInError) { 'the persona sign-in check could not run: ' + $c.personaSignInError } else { 'no persona has a cached sign-in on the VM (each signs in once with a device code: Acting as > Sign in; -IncludePersonaFiles copies the laptop caches)' })
  }
  [bool]$V.ok
}

function Write-NextSteps([string[]]$PersonaFileNames = @()) {
  $cached = @($PersonaFileNames | ForEach-Object { if ($_ -match '^msal-test-(.+)\.json$') { $Matches[1] } })
  Write-Host ''
  Write-Host '  Do once on the VM (this script cannot do these for you):' -ForegroundColor Cyan
  Write-Host '    1. Start-JumpBox.bat   (or: pwsh scripts\jumpbox.ps1 -Start -OpenPortal -CopyPassword)  ->  VM page > Connect > Bastion, user abwadmin.'
  Write-Host "    2. Double-click 'ABW Demo Console' on the VM desktop. The first start prints a device code: sign in as $($cfg.operatorUpn)."
  Write-Host '    3. Edge opens http://127.0.0.1:8787/ . The Azure portal and Foundry shortcuts on the desktop now load the private data pages.'
  if ($cached.Count -gt 0) {
    Write-Host ("  Act 7 persona scenes: cached sign-ins for {0} are on the VM; any other persona signs in once with a device code (Acting as > Sign in)." -f ($cached -join ', ')) -ForegroundColor DarkGray
  } else {
    Write-Host '  Act 7 persona scenes: each persona signs in on the VM with a device code; no persona files were copied (-IncludePersonaFiles copies them).' -ForegroundColor DarkGray
  }
  Write-Host ''
  Write-Host '  Seen from the laptop through run-command: tools, package, virtual environment, a throw-away console on port 8799, private DNS and the APIM 401.' -ForegroundColor DarkGray
  Write-Host '  [not seen] the Bastion browser session, the Azure sign-in on the VM, and the console signed in end to end on the VM.' -ForegroundColor DarkGray
  Write-Host ''
}

# ---------------------------------------------------------------------------- modes

function Invoke-DeployMode {
  $pkg = Build-Package -Scan -Zip
  try {
    if ($WhatIf) {
      Write-Step 'WhatIf: what a real run does (nothing is sent, the VM is not started)'
      $info = Get-VmInfo
      Write-Host ("    VM          {0} [{1}]{2}" -f $vmName, $(if ($info) { $info.powerState } else { 'not deployed' }), $(if ($info -and $info.powerState -ne 'VM running') { ' - a real run starts it' } else { '' }))
      Write-Host '    probe       read what is on the VM (tools, package hash, venv, shortcut, az sign-in; no tokens)'
      Write-Host ("    tools       only if missing: Python {0} (python.org), Azure CLI {1} (azcliprod.blob.core.windows.net), PowerShell {2} (github.com/PowerShell); signature checked before install" -f $tools.python.version, $tools.az.version, $tools.pwsh.version)
      Write-Host ("    upload      {0} parts of the {1} zip, only if the package differs from what is on the VM (or -Force)" -f $pkg.Parts, (Format-Size $pkg.ZipBytes))
      Write-Host '    package     rebuild + SHA-256 check, copy into C:\abw (never overwrites evidence the VM produced)'
      Write-Host '    venv        C:\abw\.venv and pip install -r requirements.txt -c constraints.txt, only if those changed'
      Write-Host '    launcher    desktop shortcuts: ABW Demo Console, Azure portal (ABW tenant), Foundry portal (ABW tenant); C:\abw\.secrets locked to SYSTEM + abwadmin'
      if ($IncludePersonaFiles) {
        $whatIfFiles = @(Get-PersonaSources)
        Write-Host ("    personas    -IncludePersonaFiles: {0} file(s) from {1} would be copied into C:\abw\.secrets (names and sizes only; contents are never shown){2}" -f $whatIfFiles.Count, $script:SecretsDir, $(if ($Force) { '; -Force replaces the ones the VM has' } else { ', and only those the VM does not have yet' }))
        foreach ($f in $whatIfFiles) { Write-Host ('                {0,-26} {1,8}' -f $f.Name, (Format-Size $f.Length)) }
        Write-Host '                sent as a zip in a folder only SYSTEM can open, unpacked in memory, upload deleted, run-command script copies emptied'
        Write-Host '                never copied: agent-client.json, jumpbox.json (the VM admin password), vendor-api-key.txt'
      }
      Write-Host '    verify      throw-away console on port 8799, private DNS, APIM answers 401 without a token, and a silent sign-in for every persona that has a cached sign-in on the VM (never a device code)'
      Write-Warn2 'WhatIf: nothing was sent'
      return
    }

    $personaSrc = @()
    if ($IncludePersonaFiles) {
      $personaSrc = @(Get-PersonaSources)
      if ($personaSrc.Count -eq 0) { throw "-IncludePersonaFiles: there are no persona files in $script:SecretsDir to copy." }
    }

    Assert-VmRunning $true

    Write-Step "reading the state of C:\abw on $vmName (Azure run-command)"
    $res = Send-Setup @('probe')
    $p = $res.probe
    if (-not $res.ok) { Show-Phases $res; throw 'The probe failed - see above.' }
    Show-Probe $p $pkg.ContentSha

    $needTools = -not (($p.python -like '3.11.*') -and $p.az -and ($p.pwsh -like '7.*'))
    $needPackage = [bool]($Force -or -not $p.contentSha -or ($p.contentSha -ne $pkg.ContentSha) -or (@($p.missing).Count -gt 0))

    # Persona files: only the ones the VM does not have yet (it may hold newer refresh tokens), or all of them with -Force.
    $haveOnVm = @($p.personaNames)
    $personaToSend = @($personaSrc | Where-Object { $Force -or ($_.Name -notin $haveOnVm) })
    $sendPersona = [bool]($IncludePersonaFiles -and $personaToSend.Count -gt 0)
    if ($IncludePersonaFiles -and -not $sendPersona) {
      Write-Ok ("the VM already has all {0} persona file(s) - not uploaded (-Force replaces them)" -f $personaSrc.Count)
    }

    if ($needTools) {
      Write-Step 'installing the missing tools on the VM (downloads and installers; several minutes the first time)'
      $res = Send-Setup @('tools')
      Show-Phases $res
      if (-not $res.ok) { throw 'The tools step failed - details in C:\abw-stage\setup.log and C:\abw-stage\logs on the VM.' }
    } else {
      Write-Ok 'tools already installed - nothing to download'
    }

    if ($needPackage) {
      Write-Step "uploading the package ($(Format-Size $pkg.ZipBytes) in $($pkg.Parts) parts)"
      Send-PackageParts $pkg
    } else {
      Write-Ok 'the VM already has this exact package - not uploaded again (-Force sends it anyway)'
    }

    $phases = @()
    if ($needPackage) { $phases += 'package' }
    $phases += 'venv', 'launcher'
    if (-not $sendPersona) { $phases += 'verify' }
    Write-Step ("on the VM: {0}" -f ($phases -join ' > '))
    $res = Send-Setup $phases -Parts $pkg.Parts -ZipSha $pkg.ZipSha -ContentSha $pkg.ContentSha
    Show-Phases $res
    $verified = $false
    if ($res.verify) { Write-Step 'verification from inside the VM'; $verified = Show-Verify $res.verify }
    if (-not $res.ok) { throw 'A step failed on the VM - see above; details in C:\abw-stage\setup.log.' }

    # Only after everything above worked: the persona files travel separately from the package, in a folder only SYSTEM can open.
    $personasRes = $null
    if ($sendPersona) {
      Write-Step 'copying the persona sign-in files (opt-in; names and sizes only are shown, never contents)'
      foreach ($f in $personaToSend) { Write-Host ('    {0,-26} {1,8}' -f $f.Name, (Format-Size $f.Length)) }
      $pz = New-PersonaZip $personaToSend
      try {
        Write-Ok ("zip {0}, SHA-256 {1}; {2} upload part(s)" -f (Format-Size $pz.ZipBytes), $pz.ZipSha.Substring(0, 16), $pz.Parts)
        Send-PackageParts $pz -Persona
        Write-Step 'on the VM: personas > verify'
        $res = Send-Setup @('personas', 'verify') -ContentSha $pkg.ContentSha -PersonaParts $pz.Parts -PersonaZipSha $pz.ZipSha -PersonaOverwrite $Force.IsPresent
      } finally {
        Remove-Package $pz
      }
      Show-Phases $res
      if ($res.verify) { Write-Step 'verification from inside the VM'; $verified = Show-Verify $res.verify }
      if (-not $res.ok) { throw 'The persona step failed - see above; details in C:\abw-stage\setup.log. Run -RemovePersonaFiles to clear anything left on the VM.' }
      $personasRes = $res.personas
    }

    $v = $res.verify
    $prev = (Read-Json $stateFile).consoleOnVm
    $onVm = if ($personasRes -and $personasRes.names) { @($personasRes.names) } else { @($p.personaNames) }
    $copiedAt = $null
    if ($personasRes) { $copiedAt = (Get-Date).ToUniversalTime().ToString('o') }
    elseif ($prev -and $prev.personaFilesCopiedAt) { $copiedAt = [string]$prev.personaFilesCopiedAt }
    $consoleState = [ordered]@{
      at         = (Get-Date).ToUniversalTime().ToString('o')
      path       = 'C:\abw'
      contentSha = $pkg.ContentSha
      zipSha     = $pkg.ZipSha
      files      = $pkg.Items.Count
      tools      = [ordered]@{ python = $v.python; azureCli = $v.az; powershell = $v.pwsh }
      verified   = $verified
      console    = $v.console
      apim       = $v.apim
      personaFilesOnVm = $onVm
    }
    if ($copiedAt) { $consoleState['personaFilesCopiedAt'] = $copiedAt }
    Update-State ([ordered]@{ consoleOnVm = $consoleState })
    Write-Ok 'recorded in infra\generated\jumpbox.json (no secrets; persona file names only)'
    Write-NextSteps $onVm
  } finally {
    Remove-Package $pkg
  }
}

function Invoke-StatusMode {
  Write-Step "console on $vmName"
  $info = Get-VmInfo
  if (-not $info) { Write-Warn2 'the jump box is not deployed - run: pwsh scripts\jumpbox.ps1'; return }
  Write-Host ("    {0,-11} {1} [{2}] {3}  private IP {4}" -f 'VM', $info.name, $info.powerState, $info.hardwareProfile.vmSize, $info.privateIps)
  $saved = (Read-Json $stateFile).consoleOnVm
  if ($saved) { Write-Host ("    {0,-11} last deployed {1}, {2} files, verified: {3}" -f 'recorded', $saved.at, $saved.files, $saved.verified) }
  if ($info.powerState -ne 'VM running') { Write-Warn2 'the VM is not running, so its contents cannot be read. Start it: pwsh scripts\jumpbox.ps1 -Start'; return }
  $pkg = Build-Package
  try {
    $res = Send-Setup @('probe') -ContentSha $pkg.ContentSha
    if (-not $res.ok) { Show-Phases $res; throw 'The probe failed - see above.' }
    Show-Probe $res.probe $pkg.ContentSha
  } finally {
    Remove-Package $pkg
  }
}

function Invoke-VerifyMode {
  Assert-VmRunning $false
  $pkg = Build-Package
  try {
    Write-Step "reading the state of C:\abw on $vmName"
    $res = Send-Setup @('probe')
    if (-not $res.ok) { Show-Phases $res; throw 'The probe failed - see above.' }
    Show-Probe $res.probe $pkg.ContentSha
    Write-Step 'verification from inside the VM (a throw-away console on port 8799 and an unauthenticated APIM call)'
    $res = Send-Setup @('verify') -ContentSha $pkg.ContentSha
    if ($res.verify) { $ok = Show-Verify $res.verify } else { $ok = $false }
    if (-not $res.ok) { Show-Phases $res; Write-Warn2 'one or more checks failed - see above' } else { Write-Ok 'verification passed' }
    $v = $res.verify
    if ($v) { Update-State ([ordered]@{ consoleOnVmVerify = [ordered]@{ at = (Get-Date).ToUniversalTime().ToString('o'); ok = $ok; console = $v.console; apim = $v.apim } }) }
  } finally {
    Remove-Package $pkg
  }
}

function Invoke-RemoveConsole {
  Write-Step "removing the console from $vmName"
  Write-Host '    - C:\abw (code, virtual environment, logs, scrubbed evidence, anything the console wrote there)'
  Write-Host '    - the persona sign-in files in C:\abw\.secrets, if -IncludePersonaFiles ever copied any (they live inside C:\abw)'
  Write-Host '    - C:\abw-stage (deployment and installer logs, any upload scratch folder)'
  Write-Host '    - desktop shortcuts: ABW Demo Console, Azure portal (ABW tenant), Foundry portal (ABW tenant)'
  Write-Host "    stays: Python, Azure CLI, PowerShell 7 and the Azure CLI sign-in in C:\Users\$adminUser\.azure"
  if ($WhatIf) { Write-Warn2 'WhatIf: nothing was deleted'; return }
  Assert-VmRunning $false
  if (-not $Force) {
    Write-Host "Type the VM name ($vmName) to continue:" -ForegroundColor Yellow
    if ((Read-Host) -ne $vmName) { throw 'Confirmation did not match - nothing was deleted.' }
  }
  $res = Send-Setup @('remove')
  Show-Phases $res
  if (-not $res.ok) { throw 'The removal did not finish - see above.' }
  Update-State ([ordered]@{ consoleOnVm = $null; consoleOnVmVerify = $null })
  Write-Ok 'removed; infra\generated\jumpbox.json updated'
}

function Invoke-RemovePersonaFiles {
  Write-Step "removing the persona sign-in files from $vmName"
  Write-Host '    - every file in C:\abw\.secrets (the persona list, one-time-code seeds, cached persona sign-ins, anything the console cached there)'
  Write-Host '    - the persona upload scratch folder C:\abw-stage\persona-parts, if one is left'
  Write-Host '    - any left-over copy of the persona upload script in the run-command agent folder'
  Write-Host "    stays: the console, its package, the Azure CLI sign-in in C:\Users\$adminUser\.azure, and the empty folder locked to SYSTEM + $adminUser"
  if ($WhatIf) { Write-Warn2 'WhatIf: nothing was deleted'; return }
  Assert-VmRunning $false
  if (-not $Force) {
    Write-Host "Type the VM name ($vmName) to continue:" -ForegroundColor Yellow
    if ((Read-Host) -ne $vmName) { throw 'Confirmation did not match - nothing was deleted.' }
  }
  $res = Send-Setup @('personas-remove')
  Show-Phases $res
  if (-not $res.ok) { throw 'The persona files were not all removed - see above.' }
  $saved = (Read-Json $stateFile).consoleOnVm
  if ($saved) {
    $cur = [ordered]@{}
    foreach ($pr in $saved.PSObject.Properties) { if ($pr.Name -notin @('personaFilesOnVm', 'personaFilesCopiedAt')) { $cur[$pr.Name] = $pr.Value } }
    $cur['personaFilesOnVm'] = @()
    Update-State ([ordered]@{ consoleOnVm = $cur })
  }
  Write-Ok 'removed; infra\generated\jumpbox.json updated'
}

# ---------------------------------------------------------------------------- dispatch

if ($Remove -and ($Status -or $Verify)) { throw '-Remove cannot be combined with -Status or -Verify.' }
if ($RemovePersonaFiles -and ($Remove -or $Status -or $Verify -or $IncludePersonaFiles)) { throw '-RemovePersonaFiles cannot be combined with -Remove, -Status, -Verify or -IncludePersonaFiles.' }
if ($IncludePersonaFiles -and ($Remove -or $Status -or $Verify)) { throw '-IncludePersonaFiles goes with a normal install or update run (not with -Remove, -Status or -Verify).' }
Assert-AzContext

if ($Remove) { Invoke-RemoveConsole; return }
if ($RemovePersonaFiles) { Invoke-RemovePersonaFiles; return }
if ($Verify) { Invoke-VerifyMode; return }
if ($Status) { Invoke-StatusMode; return }
Invoke-DeployMode
