# jumpbox-console-setup.ps1 - runs INSIDE the jump box through Azure run-command (Windows PowerShell 5.1, as SYSTEM).
#
# scripts\jumpbox-console.ps1 fills in the double-underscore placeholders below, sends this file once per step, and reads the single
# line of JSON printed at the end (run-command keeps only the last 4 KB of output, so details go to C:\abw-stage\setup.log).
# Keep this file plain ASCII and Windows PowerShell 5.1 compatible (no ??, no ternary, no &&).
#
# Phases (comma separated, run in the order given; the first failure stops the run):
#   probe     read-only: tools, package, virtual environment, shortcut, console, Azure CLI profile, the NAMES of any persona files (never their contents)
#   tools     Python, Azure CLI, PowerShell 7 - each installer must carry a valid Python Software Foundation / Microsoft signature
#   package   rebuild the uploaded zip from C:\abw-stage\parts, check its SHA-256, copy it into C:\abw (never overwrites demo\evidence)
#   venv      C:\abw\.venv and pip install -r requirements.txt -c constraints.txt (only when either file changed)
#   launcher  desktop shortcuts (ABW Demo Console, Azure portal, Foundry portal) and C:\abw\.secrets locked to SYSTEM + the local admin (empty unless persona files were copied)
#   verify    throw-away console on port 8799 (health, UI, catalog, scoreboard, policy, personas) + private DNS and an unauthenticated APIM call
#             + a silent sign-in check (never a device code) for every persona whose cached sign-in is on this VM
#   personas  opt-in: reassemble C:\abw-stage\persona-parts, check its SHA-256, install the files into C:\abw\.secrets (only the ones that are not there yet,
#             unless overwrite is on), delete the upload, empty the run-command agent's world-readable copy of the upload script
#   personas-remove   stop the console and delete every file in C:\abw\.secrets (the folder stays, locked)
#   remove    stop the console, delete C:\abw, C:\abw-stage and the shortcuts (the installed tools stay)
# Every phase can be repeated.
$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ---- filled in by the laptop script
$phases     = @('__PHASES__' -split ',' | Where-Object { $_ })
$adminUser  = '__ADMIN_USER__'
$zipSha     = '__ZIP_SHA__'
$contentSha = '__CONTENT_SHA__'
$partCount  = [int]'__PARTS__'
$tenantId   = '__TENANT_ID__'
$tenantDom  = '__TENANT_DOMAIN__'
$apimHost   = '__APIM_HOST__'
$pyVer      = '__PY_VER__'
$pyUrl      = '__PY_URL__'
$azVer      = '__AZ_VER__'
$azUrl      = '__AZ_URL__'
$psVer      = '__PS_VER__'
$psUrl      = '__PS_URL__'
$personaCount     = [int]'__PERSONA_COUNT__'
$personaSha       = '__PERSONA_SHA__'
$personaOverwrite = ('__PERSONA_OVERWRITE__' -eq '1')

# ---- locations
$stage       = 'C:\abw-stage'
$app         = 'C:\abw'
$setupLog    = Join-Path $stage 'setup.log'
$dlDir       = Join-Path $stage 'dl'
$installLogs = Join-Path $stage 'logs'
$pyDir       = 'C:\Program Files\Python' + ($pyVer -replace '^(\d+)\.(\d+)\..*$', '$1$2')
$pyExe       = Join-Path $pyDir 'python.exe'
$pwshExe     = 'C:\Program Files\PowerShell\7\pwsh.exe'
$azCmds      = @('C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd', 'C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd')
$venvPy      = Join-Path $app '.venv\Scripts\python.exe'
$desktop     = 'C:\Users\Public\Desktop'
$lnkConsole  = Join-Path $desktop 'ABW Demo Console.lnk'
$urlPortal   = Join-Path $desktop 'Azure portal (ABW tenant).url'
$urlFoundry  = Join-Path $desktop 'Foundry portal (ABW tenant).url'
# Files whose absence means the console cannot work; probe and verify both check them.
$needFiles   = @('console\server.py', 'console\web\index.html', 'src\agent\abw_agents.py', 'infra\generated\config.json', 'infra\generated\entra.json',
                 'infra\apim\policies\mcp-jwt.policy.xml', 'scripts\common.ps1', 'scripts\jumpbox-console-start.ps1', 'demo\evidence\scoreboard.json')

New-Item -ItemType Directory -Force -Path $stage, $installLogs | Out-Null

# ---------------------------------------------------------------------------------------------------- helpers
function Limit([string]$Text, [int]$Max = 600) {
  if ($Text -and $Text.Length -gt $Max) { return $Text.Substring(0, $Max) + '...' }
  return $Text
}

function Log([string]$Message) {
  try { Add-Content -Path $setupLog -Value ('{0} {1}' -f (Get-Date -Format 's'), $Message) } catch { }
}

# The installers changed the machine PATH after this run-command process started; read it fresh.
function Update-EnvPath {
  $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $u = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = (@($m, $u) | Where-Object { $_ }) -join ';'
}

# Native call that never throws on stderr (Windows PowerShell 5.1 turns native stderr into errors under 'Stop').
function Invoke-Native([string]$File, [string[]]$ArgList) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $out = & $File @ArgList 2>&1 | ForEach-Object { [string]$_ }
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $prev }
  [pscustomobject]@{ code = $code; out = (@($out) -join "`n") }
}

function Get-Http([string]$Url, [int]$TimeoutSec = 15) {
  try {
    $x = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
    return [pscustomobject]@{ code = [int]$x.StatusCode; body = [string]$x.Content }
  } catch {
    $c = 0
    if ($_.Exception.Response) { $c = [int]$_.Exception.Response.StatusCode }
    return [pscustomobject]@{ code = $c; body = '' }
  }
}

# POST with the same-origin header the console requires. The body of a non-2xx answer is read too (the console's messages never carry secrets).
function Invoke-HttpPost([string]$Url, [int]$TimeoutSec = 60) {
  $origin = ([Uri]$Url).GetLeftPart([UriPartial]::Authority)
  try {
    $x = Invoke-WebRequest -Uri $Url -Method Post -Body '{}' -ContentType 'application/json' -Headers @{ Origin = $origin } -UseBasicParsing -TimeoutSec $TimeoutSec
    return [pscustomobject]@{ code = [int]$x.StatusCode; body = [string]$x.Content }
  } catch {
    $c = 0
    $b = ''
    if ($_.Exception.Response) {
      $c = [int]$_.Exception.Response.StatusCode
      try {
        $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $b = $sr.ReadToEnd()
        $sr.Dispose()
      } catch { }
    }
    return [pscustomobject]@{ code = $c; body = $b }
  }
}

# C:\ lets every local user read what is under it, so the folder that holds cached persona sign-ins gets its own ACL:
# SYSTEM (full) and the console's local admin (modify) only, no inheritance. Files already in it are reset to inherit from the folder.
function Initialize-SecretsDir {
  $sec = Join-Path $app '.secrets'
  New-Item -ItemType Directory -Force -Path $sec | Out-Null
  $a = Invoke-Native 'icacls.exe' @($sec, '/grant:r', 'SYSTEM:(OI)(CI)F', '/grant:r', ($adminUser + ':(OI)(CI)M'), '/inheritance:r')
  if ($a.code -ne 0) { throw "icacls on $sec returned $($a.code): $(Limit $a.out 300)" }
  foreach ($f in @(Get-ChildItem -LiteralPath $sec -File -Force -ErrorAction SilentlyContinue)) {
    $r = Invoke-Native 'icacls.exe' @($f.FullName, '/reset', '/Q')
    if ($r.code -ne 0) { throw "icacls /reset on $($f.Name) returned $($r.code)" }
  }
  return $sec
}

# Names (never contents) of what is in C:\abw\.secrets and who may open the folder.
function Get-SecretsInfo {
  $sec = Join-Path $app '.secrets'
  $info = [ordered]@{ exists = [bool](Test-Path $sec); names = @(); principals = @(); locked = $false }
  if (-not $info.exists) { return $info }
  $info.names = @(Get-ChildItem -LiteralPath $sec -File -Force -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
  $acl = Get-Acl -LiteralPath $sec
  $info.principals = @($acl.Access | ForEach-Object { ([string]$_.IdentityReference) -replace '^.*\\', '' } | Select-Object -Unique)
  $extra = @($info.principals | Where-Object { $_ -notin @('SYSTEM', $adminUser) })
  $info.locked = [bool]($acl.AreAccessRulesProtected -and $extra.Count -eq 0)
  return $info
}

# The run-command agent keeps a copy of every script it runs under C:\Packages\Plugins\...\Downloads, and Everyone can read it.
# The upload scripts that carried the persona payload start with a marker comment; once the payload is installed those copies are emptied.
function Clear-PayloadCopies {
  $mark = 'ABW-PERSONA' + '-PAYLOAD'
  $cleared = 0
  $left = 0
  foreach ($d in @(Get-ChildItem -Path 'C:\Packages\Plugins' -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*RunCommand*' })) {
    foreach ($f in @(Get-ChildItem -Path $d.FullName -Recurse -File -Filter 'script*.ps1' -ErrorAction SilentlyContinue)) {
      $hit = $false
      try { $hit = [bool](Select-String -LiteralPath $f.FullName -Pattern $mark -SimpleMatch -Quiet -ErrorAction Stop) } catch { continue }
      if (-not $hit) { continue }
      try { [IO.File]::WriteAllText($f.FullName, ''); $cleared++ } catch { $left++ }
    }
  }
  return [pscustomobject]@{ cleared = $cleared; left = $left }
}

function Get-AzCmdPath {
  foreach ($p in $azCmds) { if (Test-Path $p) { return $p } }
  return ''
}

# Versions of what is installed ('' = missing). Python and PowerShell are asked directly; the Azure CLI comes from its installer entry.
function Get-ToolState {
  $s = [ordered]@{ python = ''; az = ''; pwsh = '' }
  if (Test-Path $pyExe) {
    $v = @(& $pyExe -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null) | Select-Object -First 1
    if ($v) { $s.python = ([string]$v).Trim() }
  }
  if (Get-AzCmdPath) {
    $e = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
      Where-Object { $_.DisplayName -like 'Microsoft Azure CLI*' } | Select-Object -First 1
    if ($e -and $e.DisplayVersion) { $s.az = [string]$e.DisplayVersion } else { $s.az = 'installed' }
  }
  if (Test-Path $pwshExe) {
    $v = @(& $pwshExe -NoProfile -Command '$PSVersionTable.PSVersion.ToString()' 2>$null) | Select-Object -First 1
    if ($v) { $s.pwsh = ([string]$v).Trim() }
  }
  return $s
}

function Read-Package {
  $f = Join-Path $app 'package.json'
  if (-not (Test-Path $f)) { return $null }
  try { return (Get-Content -Raw -Path $f | ConvertFrom-Json) } catch { return $null }
}

# Console server processes (the venv launcher and the interpreter it starts); -Port narrows it to one instance.
function Get-ConsoleProcs([string]$Port = '') {
  $all = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue)
  return @($all | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*console\server.py*') -and ((-not $Port) -or ($_.CommandLine -like "*--port $Port*")) })
}

function Stop-ConsoleProcs([string]$Port = '') {
  $n = 0
  foreach ($p in (Get-ConsoleProcs $Port)) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }
  if ($n -gt 0) { Start-Sleep -Seconds 2 }
  return $n
}

function Get-Installer([string]$Url, [string]$Name, [string]$Signer) {
  New-Item -ItemType Directory -Force -Path $dlDir | Out-Null
  $dest = Join-Path $dlDir $Name
  for ($i = 1; $i -le 3; $i++) {
    try {
      if (Test-Path $dest) { Remove-Item $dest -Force }
      $wc = New-Object System.Net.WebClient
      $wc.Headers.Add('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) abw-jumpbox-setup')
      $wc.DownloadFile($Url, $dest)
      break
    } catch {
      Log "download $Name attempt $i failed: $($_.Exception.Message)"
      if ($i -eq 3) { throw "could not download $Name from $Url" }
      Start-Sleep -Seconds (5 * $i)
    }
  }
  $sig = Get-AuthenticodeSignature -FilePath $dest
  if ($sig.Status -ne 'Valid') { throw "$Name has no valid signature (status $($sig.Status)); not installed" }
  $subject = [string]$sig.SignerCertificate.Subject
  if ($subject -notlike "*$Signer*") { throw "$Name is signed by '$subject', not '$Signer'; not installed" }
  Log ('{0} downloaded ({1} MB), signature valid, signer {2}' -f $Name, [math]::Round((Get-Item $dest).Length / 1MB, 1), $Signer)
  return $dest
}

# 0 = installed, 3010 = installed and a reboot is pending, 1618 = another installer is running (retried).
function Invoke-Installer([string]$File, [string[]]$ArgList, [string]$What) {
  for ($i = 1; $i -le 6; $i++) {
    Log "$What : install attempt $i"
    $p = Start-Process -FilePath $File -ArgumentList $ArgList -Wait -PassThru
    $code = [int]$p.ExitCode
    Log "$What : exit code $code"
    if ($code -eq 0 -or $code -eq 3010) { return $code }
    if ($code -eq 1618 -and $i -lt 6) { Start-Sleep -Seconds 30; continue }
    throw "$What installer exited with code $code (log in $installLogs)"
  }
}

function New-Lnk([string]$Path, [string]$Target, [string]$Arguments, [string]$WorkDir, [string]$Icon, [string]$Description) {
  $w = New-Object -ComObject WScript.Shell
  $l = $w.CreateShortcut($Path)
  $l.TargetPath = $Target
  $l.Arguments = $Arguments
  $l.WorkingDirectory = $WorkDir
  $l.IconLocation = $Icon
  $l.Description = $Description
  $l.Save()
}

# ---------------------------------------------------------------------------------------------------- phases
function Invoke-Probe {
  $o = [ordered]@{ ok = $true }
  $t = Get-ToolState
  $o.python = $t.python
  $o.az = $t.az
  $o.pwsh = $t.pwsh
  $pk = Read-Package
  $o.contentSha = ''
  $o.zipSha = ''
  $o.deployedAt = ''
  $o.files = 0
  if ($pk) {
    $o.contentSha = [string]$pk.contentSha
    $o.zipSha = [string]$pk.zipSha
    $o.deployedAt = [string]$pk.deployedAt
    $o.files = [int]$pk.files
  }
  $o.missing = @($needFiles | Where-Object { -not (Test-Path (Join-Path $app $_)) })
  $o.venv = [bool](Test-Path $venvPy)
  $o.shortcut = [bool](Test-Path $lnkConsole)
  $o.consoleRunning = @(Get-ConsoleProcs).Count -gt 0
  $o.personaFiles = 0
  $o.personaNames = @()
  $o.personaFolderLocked = $false
  $o.personaFolderPrincipals = @()
  $si = Get-SecretsInfo
  if ($si.exists) {
    $o.personaFiles = @($si.names).Count
    $o.personaNames = @($si.names)
    $o.personaFolderLocked = [bool]$si.locked
    $o.personaFolderPrincipals = @($si.principals)
  }
  $o.azUser = ''
  $o.azTenant = ''
  $azp = "C:\Users\$adminUser\.azure\azureProfile.json"
  if (Test-Path $azp) {
    try {
      $prof = ((Get-Content -Raw -Path $azp) -replace '^\uFEFF', '') | ConvertFrom-Json
      $sub = @($prof.subscriptions) | Where-Object { $_.isDefault } | Select-Object -First 1
      if ($sub) { $o.azUser = [string]$sub.user.name; $o.azTenant = [string]$sub.tenantId }
    } catch { }
  }
  return $o
}

function Invoke-Tools {
  Update-EnvPath
  $o = [ordered]@{ ok = $false; installed = @(); skipped = @(); reboot = $false }
  $st = Get-ToolState
  $wantPy = $pyVer -replace '^(\d+\.\d+)\..*$', '$1'

  if ($st.python -like "$wantPy.*") { $o.skipped += 'python' } else {
    $f = @(Get-Installer $pyUrl ('python-' + $pyVer + '-amd64.exe') 'Python Software Foundation')[-1]
    $c = Invoke-Installer $f @('/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_launcher=0', 'Include_test=0', 'Include_doc=0', 'Include_tcltk=0', '/log', (Join-Path $installLogs 'python.log')) 'python'
    if ($c -eq 3010) { $o.reboot = $true }
    $o.installed += 'python'
  }

  if ($st.az) { $o.skipped += 'az' } else {
    $f = @(Get-Installer $azUrl ('azure-cli-' + $azVer + '-x64.msi') 'Microsoft Corporation')[-1]
    $c = Invoke-Installer 'msiexec.exe' @('/i', $f, '/qn', '/norestart', '/L*v', (Join-Path $installLogs 'azure-cli.log')) 'azure-cli'
    if ($c -eq 3010) { $o.reboot = $true }
    $o.installed += 'az'
  }

  if ($st.pwsh -like '7.*') { $o.skipped += 'pwsh' } else {
    $f = @(Get-Installer $psUrl ('PowerShell-' + $psVer + '-win-x64.msi') 'Microsoft Corporation')[-1]
    $c = Invoke-Installer 'msiexec.exe' @('/i', $f, '/qn', '/norestart', '/L*v', (Join-Path $installLogs 'powershell.log'), 'ADD_PATH=1', 'REGISTER_MANIFEST=1', 'USE_MU=0', 'ENABLE_MU=0', 'ENABLE_PSREMOTING=0', 'DISABLE_TELEMETRY=1') 'powershell'
    if ($c -eq 3010) { $o.reboot = $true }
    $o.installed += 'pwsh'
  }

  Update-EnvPath
  $st = Get-ToolState
  $o.python = $st.python
  $o.az = $st.az
  $o.pwsh = $st.pwsh
  $o.ok = [bool]($st.python -and $st.az -and $st.pwsh)
  if (-not $o.ok) { $o.error = 'a tool is still missing after the install - see C:\abw-stage\logs' }
  Remove-Item $dlDir -Recurse -Force -ErrorAction SilentlyContinue
  return $o
}

function Invoke-Package {
  $o = [ordered]@{ ok = $false }
  $partDir = Join-Path $stage 'parts'
  $parts = @(Get-ChildItem -Path $partDir -Filter 'part-*.b64' -ErrorAction SilentlyContinue | Sort-Object Name)
  if ($parts.Count -ne $partCount) { throw "expected $partCount upload parts, found $($parts.Count)" }
  $sb = New-Object System.Text.StringBuilder
  foreach ($p in $parts) { [void]$sb.Append(([IO.File]::ReadAllText($p.FullName)).Trim()) }
  $zip = Join-Path $stage 'abw-package.zip'
  [IO.File]::WriteAllBytes($zip, [Convert]::FromBase64String($sb.ToString()))
  $sha = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLowerInvariant()
  if ($sha -ne $zipSha) { throw "zip SHA-256 mismatch: the VM has $sha, the laptop sent $zipSha" }
  $o.zipSha = $sha
  $o.zipBytes = (Get-Item $zip).Length

  # A console started from an older copy would keep serving old code, so stop it before the files are replaced.
  $o.stoppedConsole = Stop-ConsoleProcs

  $pkg = Join-Path $stage 'pkg'
  if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [IO.Compression.ZipFile]::ExtractToDirectory($zip, $pkg)
  New-Item -ItemType Directory -Force -Path $app | Out-Null

  $c1 = Invoke-Native 'robocopy.exe' @($pkg, $app, '/E', '/XD', 'evidence', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:2')
  if ($c1.code -ge 8) { throw "robocopy failed with code $($c1.code): $(Limit $c1.out 300)" }
  # Evidence the VM produced itself (a proof run) is never overwritten: only files that are not there yet are copied.
  $ev = Join-Path $pkg 'demo\evidence'
  if (Test-Path $ev) {
    $c2 = Invoke-Native 'robocopy.exe' @($ev, (Join-Path $app 'demo\evidence'), '/E', '/XC', '/XN', '/XO', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:2')
    if ($c2.code -ge 8) { throw "robocopy (evidence) failed with code $($c2.code): $(Limit $c2.out 300)" }
  }
  New-Item -ItemType Directory -Force -Path (Join-Path $app 'logs') | Out-Null

  # SYSTEM wrote these files; the local admin runs the console and needs to write its logs and state there.
  $ic = Invoke-Native 'icacls.exe' @($app, '/grant', ($adminUser + ':(OI)(CI)M'), '/T', '/C', '/Q')
  if ($ic.code -ne 0) { Log "icacls returned $($ic.code): $(Limit $ic.out 300)" }

  $o.files = @(Get-ChildItem -Path $pkg -Recurse -File).Count
  $meta = [ordered]@{ contentSha = $contentSha; zipSha = $sha; deployedAt = (Get-Date).ToString('o'); files = $o.files }
  [IO.File]::WriteAllText((Join-Path $app 'package.json'), ($meta | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
  Remove-Item $partDir -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item $pkg -Recurse -Force -ErrorAction SilentlyContinue
  $o.ok = $true
  return $o
}

function Invoke-Venv {
  Update-EnvPath
  $o = [ordered]@{ ok = $false; pipRan = $false }
  if (-not (Test-Path $pyExe)) { throw 'Python is not installed - run the tools phase first' }
  $req = Join-Path $app 'requirements.txt'
  $con = Join-Path $app 'constraints.txt'
  if (-not (Test-Path $req)) { throw 'C:\abw\requirements.txt is missing - upload the package first' }
  if (-not (Test-Path $venvPy)) {
    $v = Invoke-Native $pyExe @('-m', 'venv', (Join-Path $app '.venv'))
    if ($v.code -ne 0) { throw "python -m venv failed: $(Limit $v.out 400)" }
  }
  $hash = (Get-FileHash -Algorithm SHA256 -Path $req).Hash
  if (Test-Path $con) { $hash = $hash + (Get-FileHash -Algorithm SHA256 -Path $con).Hash }
  $marker = Join-Path $app '.venv\requirements.sha256'
  $have = ''
  if (Test-Path $marker) { $have = (Get-Content -Raw -Path $marker).Trim() }
  if ($have -ne $hash) {
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $pipArgs = @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '--prefer-binary', '-r', $req)
    if (Test-Path $con) { $pipArgs += @('-c', $con) }
    $p = Invoke-Native $venvPy $pipArgs
    Set-Content -Path (Join-Path $installLogs 'pip.log') -Value $p.out
    if ($p.code -ne 0) { throw "pip install failed (code $($p.code)): $(Limit (($p.out -split "`n" | Select-Object -Last 6) -join ' | ') 500)" }
    Set-Content -Path $marker -Value $hash
    $o.pipRan = $true
  }
  $chk = Invoke-Native $venvPy @('-c', "import azure.identity, azure.ai.projects, azure.monitor.query, httpx, msal, msal_extensions, openai, jwt, requests, starlette, uvicorn; print('imports-ok')")
  $o.imports = ($chk.out -match 'imports-ok')
  if (-not $o.imports) { throw "the Python packages do not import: $(Limit $chk.out 400)" }
  $o.python = (Invoke-Native $venvPy @('--version')).out.Trim()
  $o.ok = $true
  return $o
}

function Invoke-Launcher {
  $o = [ordered]@{ ok = $false }
  if (-not (Test-Path $desktop)) { New-Item -ItemType Directory -Force -Path $desktop | Out-Null }
  $start = Join-Path $app 'scripts\jumpbox-console-start.ps1'
  if (-not (Test-Path $start)) { throw 'C:\abw\scripts\jumpbox-console-start.ps1 is missing - upload the package first' }
  $host7 = $pwshExe
  if (-not (Test-Path $host7)) { $host7 = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe' }
  New-Lnk $lnkConsole $host7 ('-NoProfile -ExecutionPolicy Bypass -File "' + $start + '"') $app ($host7 + ',0') 'Agents Behind the Wall - Demo Console, running on this jump box'
  $ascii = [Text.Encoding]::ASCII
  Get-ChildItem $desktop -Filter '*portal (*).url' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
  [IO.File]::WriteAllText($urlPortal, ("[InternetShortcut]`r`nURL=https://portal.azure.com/#@" + $tenantDom + "`r`n"), $ascii)
  [IO.File]::WriteAllText($urlFoundry, ("[InternetShortcut]`r`nURL=https://ai.azure.com/?tid=" + $tenantId + "`r`n"), $ascii)
  $readme = Join-Path $app 'README-VM.txt'
  $o.shortcut = [bool](Test-Path $lnkConsole)
  $o.urls = @($urlPortal, $urlFoundry | Where-Object { Test-Path $_ }).Count
  $o.readme = [bool](Test-Path $readme)
  $o.secretsLocked = $false
  try {
    [void](Initialize-SecretsDir)
    $o.secretsLocked = [bool](Get-SecretsInfo).locked
  } catch {
    $o.secretsError = Limit $_.Exception.Message 200
  }
  $o.ok = $o.shortcut
  return $o
}

# Silent sign-in check for every persona whose cached sign-in is on this VM: the console's own verify call, which redeems the refresh token
# from this VM. It never starts a device code. Only counts, the upn, role names and error codes leave the VM - no token, password or seed.
function Test-PersonaSignIns([string]$Base) {
  $rows = @()
  $st = Get-Http "$Base/api/personas" 30
  if ($st.code -ne 200) { return $rows }
  try { $state = $st.body | ConvertFrom-Json } catch { return $rows }
  foreach ($pp in @($state.personas)) {
    if (-not $pp.signedIn) { continue }
    $row = [ordered]@{ id = [string]$pp.id; ok = 0; of = 0; upn = ''; roles = @(); error = '' }
    $r = Invoke-HttpPost "$Base/api/personas/$($pp.id)/verify" 120
    $j = $null
    try { $j = $r.body | ConvertFrom-Json } catch { }
    if ($r.code -eq 200 -and $j -and $j.servers) {
      $srv = @($j.servers.PSObject.Properties)
      $row.of = $srv.Count
      $row.ok = @($srv | Where-Object { $_.Value.ok }).Count
      if ($j.who -and $j.who.upn) { $row.upn = [string]$j.who.upn }
      $row.roles = @($srv | Where-Object { $_.Value.ok } | ForEach-Object { @($_.Value.roles) } | Where-Object { $_ } | Select-Object -Unique | Select-Object -First 8)
      $bad = @($srv | Where-Object { -not $_.Value.ok } | ForEach-Object { $_.Name + ': ' + (Limit (([string]$_.Value.error) -replace '[^\x20-\x7E]', '?') 80) })
      if ($bad.Count -gt 0) { $row.error = Limit ($bad -join '; ') 200 }
    } else {
      $msg = ''
      if ($j -and $j.error) { $msg = ([string]$j.error) -replace '[^\x20-\x7E]', '?' }
      $row.error = Limit ("HTTP $($r.code) $msg") 220
    }
    $rows += [pscustomobject]$row
  }
  return $rows
}

function Invoke-Verify {
  Update-EnvPath
  $o = [ordered]@{ ok = $false }
  $st = Get-ToolState
  $o.python = $st.python
  $o.az = $st.az
  $o.pwsh = $st.pwsh
  $pk = Read-Package
  $o.package = [bool]($pk -and (($pk.contentSha -eq $contentSha) -or (-not $contentSha)))
  $o.missing = @($needFiles | Where-Object { -not (Test-Path (Join-Path $app $_)) })
  $o.venv = [bool](Test-Path $venvPy)
  $o.shortcut = [bool](Test-Path $lnkConsole)

  # APIM from inside the VNet: the private DNS name must resolve to a 10.x address and a call with no token must be refused.
  $ips = @(Resolve-DnsName -Name $apimHost -Type A -DnsOnly -ErrorAction SilentlyContinue | Where-Object { $_.Type -eq 'A' } | ForEach-Object { $_.IPAddress })
  $noToken = 0
  $www = ''
  try {
    $body = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"abw-vm-check","version":"1"}}}'
    $x = Invoke-WebRequest -Uri ("https://$apimHost/research/mcp") -Method Post -Body $body -ContentType 'application/json' -Headers @{ Accept = 'application/json, text/event-stream' } -UseBasicParsing -TimeoutSec 20
    $noToken = [int]$x.StatusCode
  } catch {
    if ($_.Exception.Response) {
      $noToken = [int]$_.Exception.Response.StatusCode
      $www = [string]$_.Exception.Response.Headers['WWW-Authenticate']
    }
  }
  $o.apim = [ordered]@{
    host      = $apimHost
    ips       = $ips
    private   = [bool](@($ips | Where-Object { $_ -match '^10\.' }).Count -gt 0)
    noToken   = $noToken
    prmHeader = [bool]($www -match 'resource_metadata')
  }

  $o.console = [ordered]@{ port = 8799; health = 0; ui = 0; catalog = 0; scoreboard = 0; policy = 0; personas = 0; personaSignIns = @() }
  if ($o.venv) {
    $env:PYTHONIOENCODING = 'utf-8'
    $logs = Join-Path $app 'logs'
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $out = Join-Path $logs 'verify-console.out.log'
    $err = Join-Path $logs 'verify-console.err.log'
    $proc = Start-Process -FilePath $venvPy -ArgumentList @('console\server.py', '--no-browser', '--skip-az-check', '--port', '8799') -WorkingDirectory $app -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
    try {
      $up = $false
      for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if ($proc.HasExited) { break }
        if ((Get-Http 'http://127.0.0.1:8799/api/health' 3).code -eq 200) { $up = $true; break }
      }
      if ($up) {
        $o.console.health = 200
        $o.console.ui = (Get-Http 'http://127.0.0.1:8799/').code
        $o.console.catalog = (Get-Http 'http://127.0.0.1:8799/api/catalog' 30).code
        $sb = Get-Http 'http://127.0.0.1:8799/api/scoreboard'
        $o.console.scoreboard = $sb.code
        $o.console.proofs = 0
        if ($sb.code -eq 200) { try { $parsedBoard = $sb.body | ConvertFrom-Json; $o.console.proofs = @($parsedBoard).Count } catch { } }
        $o.console.policy = (Get-Http 'http://127.0.0.1:8799/api/policy/mcp-jwt').code
        $o.console.personas = (Get-Http 'http://127.0.0.1:8799/api/personas' 30).code
        try {
          $o.console.personaSignIns = @(Test-PersonaSignIns 'http://127.0.0.1:8799')
        } catch {
          $o.console.personaSignInError = Limit $_.Exception.Message 160
        }
      } else {
        $tail = ''
        foreach ($lf in @($err, $out)) { if (Test-Path $lf) { $tail = $tail + ((Get-Content -Path $lf -Tail 6 -ErrorAction SilentlyContinue) -join ' | ') } }
        $o.consoleLog = Limit $tail 500
      }
    } finally {
      [void](Stop-ConsoleProcs '8799')
      if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    }
  }
  $c = $o.console
  $o.ok = [bool]($st.python -and $st.az -and $st.pwsh -and $o.package -and ($o.missing.Count -eq 0) -and $o.venv -and $o.shortcut -and
                 ($c.health -eq 200) -and ($c.ui -eq 200) -and ($c.catalog -eq 200))
  return $o
}

function Invoke-Personas {
  $o = [ordered]@{ ok = $false; copied = @(); kept = @() }
  if (-not (Test-Path $app)) { throw 'C:\abw is not there - upload the package first' }
  $partDir = Join-Path $stage 'persona-parts'
  $parts = @(Get-ChildItem -Path $partDir -Filter 'part-*.b64' -ErrorAction SilentlyContinue | Sort-Object Name)
  if ($personaCount -lt 1 -or $parts.Count -ne $personaCount) { throw "expected $personaCount persona upload part(s), found $($parts.Count)" }
  $sb = New-Object System.Text.StringBuilder
  foreach ($p in $parts) { [void]$sb.Append(([IO.File]::ReadAllText($p.FullName)).Trim()) }
  $bytes = [Convert]::FromBase64String($sb.ToString())
  $hasher = [Security.Cryptography.SHA256]::Create()
  $sha = [BitConverter]::ToString($hasher.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()
  if ($sha -ne $personaSha) { throw 'the persona zip SHA-256 on the VM differs from what the laptop sent; nothing was installed' }

  # The folder is locked before the first file is written, and the zip is read from memory: no copy sits anywhere readable by other users.
  $sec = Initialize-SecretsDir
  Add-Type -AssemblyName System.IO.Compression
  $nameRx = '^(personas|totp)\.json$|^msal-test-[a-z0-9]+\.json$'
  $ms = New-Object System.IO.MemoryStream(, $bytes)
  $za = New-Object System.IO.Compression.ZipArchive($ms, [System.IO.Compression.ZipArchiveMode]::Read)
  try {
    foreach ($e in @($za.Entries)) {
      if ($e.FullName -ne $e.Name -or $e.Name -notmatch $nameRx) { throw "the persona zip holds an unexpected entry: $($e.FullName)" }
    }
    foreach ($e in @($za.Entries)) {
      $dest = Join-Path $sec $e.Name
      # A file the VM already has may hold a newer refresh token than the laptop's copy, so it is kept unless overwrite is on.
      if ((Test-Path -LiteralPath $dest) -and -not $personaOverwrite) { $o.kept += $e.Name; continue }
      $in = $e.Open()
      try {
        $fs = [IO.File]::Create($dest)
        try { $in.CopyTo($fs) } finally { $fs.Dispose() }
      } finally { $in.Dispose() }
      $o.copied += $e.Name
    }
  } finally {
    $za.Dispose()
    $ms.Dispose()
  }

  $info = Get-SecretsInfo
  $o.names = @($info.names)
  $o.principals = @($info.principals)
  $o.locked = [bool]$info.locked
  Remove-Item $partDir -Recurse -Force -ErrorAction SilentlyContinue
  $o.partsDeleted = -not (Test-Path $partDir)
  $cp = Clear-PayloadCopies
  $o.scriptCopiesCleared = $cp.cleared
  $o.scriptCopiesLeft = $cp.left
  Log ('persona files installed: {0} copied, {1} kept' -f @($o.copied).Count, @($o.kept).Count)
  $o.ok = [bool]($o.locked -and $o.partsDeleted)
  if (-not $o.ok) { $o.error = 'the persona folder is not locked down or the upload was not deleted' }
  return $o
}

function Invoke-PersonasRemove {
  $o = [ordered]@{ ok = $true; removed = @() }
  $o.stoppedConsole = Stop-ConsoleProcs
  $sec = Join-Path $app '.secrets'
  if (Test-Path $sec) {
    foreach ($f in @(Get-ChildItem -LiteralPath $sec -Force -ErrorAction SilentlyContinue)) {
      Remove-Item -LiteralPath $f.FullName -Recurse -Force -ErrorAction SilentlyContinue
      if (Test-Path -LiteralPath $f.FullName) { $o.ok = $false; $o.error = 'a file in C:\abw\.secrets could not be deleted' } else { $o.removed += $f.Name }
    }
  }
  Remove-Item (Join-Path $stage 'persona-parts') -Recurse -Force -ErrorAction SilentlyContinue
  $cp = Clear-PayloadCopies
  $o.scriptCopiesCleared = $cp.cleared
  $o.scriptCopiesLeft = $cp.left
  if (Test-Path $app) { [void](Initialize-SecretsDir) }
  Log "persona files removed: $(@($o.removed).Count)"
  return $o
}

function Invoke-Remove {
  $o = [ordered]@{ ok = $true; removed = @() }
  $o.stoppedConsole = Stop-ConsoleProcs
  foreach ($f in @($lnkConsole) + @(Get-ChildItem $desktop -Filter '*portal (*).url' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })) {
    if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue; $o.removed += (Split-Path -Leaf $f) }
  }
  if (Test-Path $app) {
    Remove-Item $app -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $app) { $o.ok = $false; $o.error = 'C:\abw could not be fully deleted (a file is in use)' } else { $o.removed += 'C:\abw' }
  }
  Log 'removed C:\abw and the shortcuts'
  $cp = Clear-PayloadCopies
  $o.scriptCopiesCleared = $cp.cleared
  if ($o.ok) { Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue; $o.removed += 'C:\abw-stage' }
  return $o
}

# ---------------------------------------------------------------------------------------------------- run
$result = [ordered]@{ ok = $true; phases = @() }
foreach ($ph in $phases) {
  Log "phase $ph : start"
  try {
    $r = switch ($ph) {
      'probe'    { @(Invoke-Probe)[-1] }
      'tools'    { @(Invoke-Tools)[-1] }
      'package'  { @(Invoke-Package)[-1] }
      'venv'     { @(Invoke-Venv)[-1] }
      'launcher' { @(Invoke-Launcher)[-1] }
      'verify'   { @(Invoke-Verify)[-1] }
      'personas' { @(Invoke-Personas)[-1] }
      'personas-remove' { @(Invoke-PersonasRemove)[-1] }
      'remove'   { @(Invoke-Remove)[-1] }
      default    { throw "unknown phase '$ph'" }
    }
  } catch {
    $r = [ordered]@{ ok = $false; error = (Limit $_.Exception.Message 700) }
    Log "phase $ph : ERROR $($_.Exception.Message)"
  }
  $result[$ph] = $r
  $result.phases += $ph
  Log "phase $ph : done, ok=$($r.ok)"
  if (-not $r.ok) { $result.ok = $false; break }
}
$json = $result | ConvertTo-Json -Depth 7 -Compress
# run-command keeps only the last 4 KB of output; if the persona rows would push the line past that, drop their detail first.
if ($json.Length -gt 3800 -and $result.Contains('verify') -and $result['verify'].Contains('console')) {
  foreach ($row in @($result['verify']['console']['personaSignIns'])) {
    if ($null -eq $row) { continue }
    $row.roles = @()
    if ($row.error.Length -gt 60) { $row.error = $row.error.Substring(0, 60) }
  }
  $json = $result | ConvertTo-Json -Depth 7 -Compress
}
Write-Output $json
