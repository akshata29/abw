# jumpbox-console-start.ps1 - starts the Agents Behind the Wall Demo Console ON the jump box.
#
# Ships in the package (C:\abw\scripts) and is run by the desktop shortcut "ABW Demo Console" as the VM's local admin
# (Windows PowerShell 5.1 or PowerShell 7). First run only: a one-time `az login` with a device code, as the operator account that deployed this platform -
# every operator token the console uses comes from that Azure CLI cache. Close this window (or press Ctrl+C) to stop the console.
[CmdletBinding()]
param([ValidateRange(1024, 65535)][int]$Port = 8787)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
try { $Host.UI.RawUI.WindowTitle = 'Agents Behind the Wall - Demo Console (jump box)' } catch { }

# The installers changed the machine PATH after this VM's last sign-in; read it fresh.
function Update-EnvPath {
  $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $u = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = (@($m, $u) | Where-Object { $_ }) -join ';'
}

function Test-Console([int]$P) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$P/api/health" -UseBasicParsing -TimeoutSec 3
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

function Open-Edge([string]$Url) {
  $edge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
  if (Test-Path $edge) { Start-Process -FilePath $edge -ArgumentList @('--new-window', '--no-first-run', $Url) } else { Start-Process $Url }
}

# Tenant of the current az sign-in, or '' when there is none. Windows PowerShell 5.1 turns native stderr into errors under 'Stop'.
function Get-AzTenant {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { $raw = & az account show -o json 2>$null } finally { $ErrorActionPreference = $prev }
  if ($LASTEXITCODE -ne 0 -or -not $raw) { return '' }
  try { return [string]((($raw | Out-String) | ConvertFrom-Json).tenantId) } catch { return '' }
}

try {
  Update-EnvPath
  Set-Location $root
  $py = Join-Path $root '.venv\Scripts\python.exe'
  if (-not (Test-Path $py)) { throw "The Python environment is missing ($py). From the laptop run: pwsh scripts\jumpbox-console.ps1" }
  $cfg = Get-Content -Raw -Path (Join-Path $root 'infra\generated\config.json') | ConvertFrom-Json
  $url = "http://127.0.0.1:$Port/"

  Write-Host ''
  Write-Host '  Agents Behind the Wall - Demo Console, running on the jump box' -ForegroundColor Cyan
  Write-Host "  Private endpoints resolve from this VM; operator: $($cfg.operatorUpn)"

  if (Test-Console $Port) {
    Write-Host "  The console is already running - opening $url"
    Open-Edge $url
    return
  }

  if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'The Azure CLI (az) was not found on this VM. From the laptop run: pwsh scripts\jumpbox-console.ps1' }

  # Plain token cache instead of the Windows broker (WAM): the console reads the Azure CLI cache for its operator tokens.
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { & az config set core.enable_broker_on_windows=false core.login_experience_v2=off --only-show-errors 2>&1 | Out-Null } finally { $ErrorActionPreference = $prev }

  if ((Get-AzTenant).ToLowerInvariant() -ne ([string]$cfg.tenantId).ToLowerInvariant()) {
    Write-Host ''
    Write-Host "  One-time Azure sign-in for this VM. Sign in as $($cfg.operatorUpn) ($($cfg.tenantDomain))." -ForegroundColor Yellow
    Write-Host '  A device code is printed below and Edge opens the code page: enter the code there, then finish the Entra sign-in.'
    Write-Host ''
    Open-Edge 'https://microsoft.com/devicelogin'
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & az login --tenant $cfg.tenantId --use-device-code | Out-Null } finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0) { throw 'The Azure sign-in did not complete. Start the console again when you are ready.' }
  }
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { & az account set --subscription $cfg.subscriptionId 2>&1 | Out-Null } finally { $ErrorActionPreference = $prev }
  if ((Get-AzTenant).ToLowerInvariant() -ne ([string]$cfg.tenantId).ToLowerInvariant()) { throw "az is not signed in to tenant $($cfg.tenantId). Start the console again and sign in as $($cfg.operatorUpn)." }

  $env:PYTHONIOENCODING = 'utf-8'
  Write-Host ''
  Write-Host "  Starting the console on $url  (leave this window open; close it to stop the console)" -ForegroundColor Green
  $proc = Start-Process -FilePath $py -ArgumentList @('console\server.py', '--no-browser', '--skip-az-check', '--port', "$Port") -WorkingDirectory $root -NoNewWindow -PassThru
  $up = $false
  for ($i = 0; $i -lt 60; $i++) {
    if ($proc.HasExited) { break }
    if (Test-Console $Port) { $up = $true; break }
    Start-Sleep -Seconds 1
  }
  if (-not $up) { throw 'The console did not start - see the message above.' }
  Open-Edge $url
  $proc.WaitForExit()
} catch {
  Write-Host ''
  Write-Host "  $($_.Exception.Message)" -ForegroundColor Yellow
  Read-Host '  Press Enter to close this window' | Out-Null
  exit 1
}
