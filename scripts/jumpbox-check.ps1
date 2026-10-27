# jumpbox-check.ps1 - runs INSIDE the jump box through Azure run-command (Windows PowerShell 5.1, SYSTEM). Read-only.
#
# scripts\jumpbox.ps1 replaces __PRIVATE__ and __OUTBOUND__ with comma-separated host lists, sends this file, and reads the
# one-line JSON printed at the end. Keep the output small: run-command returns only the last 4 KB.
#
#   private  = the platform's data planes: they must resolve to 10.x private endpoints and answer on 443
#   outbound = what the portal / Entra sign-in need: they must answer on 443 through the NAT gateway
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference    = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Test-Tcp([string]$Address, [int]$Port = 443, [int]$Ms = 6000) {
  $c = New-Object System.Net.Sockets.TcpClient
  try {
    $r = $c.BeginConnect($Address, $Port, $null, $null)
    return ($r.AsyncWaitHandle.WaitOne($Ms) -and $c.Connected)
  } catch { return $false } finally { $c.Close() }
}

# HTTP status of an unauthenticated GET (401/403/404 all prove the request reached the service); -1 = no answer.
function Get-HttpStatus([string]$Url) {
  try {
    $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 12 -MaximumRedirection 0 -ErrorAction Stop
    return [int]$r.StatusCode
  } catch {
    if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
    return -1
  }
}

function Test-Endpoint([string]$Name) {
  $ips = @(Resolve-DnsName -Name $Name -Type A -DnsOnly -ErrorAction SilentlyContinue | Where-Object { $_.Type -eq 'A' } | ForEach-Object { $_.IPAddress })
  $tcp = $false
  $code = 0
  if ($ips.Count -gt 0) {
    $tcp = Test-Tcp $ips[0]
    if ($tcp) { $code = Get-HttpStatus "https://$Name/" }
  }
  [ordered]@{ h = $Name; ip = $ips; t = $tcp; c = $code }
}

$private  = @('__PRIVATE__'  -split ',' | Where-Object { $_ } | ForEach-Object { Test-Endpoint $_ })
$outbound = @('__OUTBOUND__' -split ',' | Where-Object { $_ } | ForEach-Object { Test-Endpoint $_ })

$egress = ''
try { $egress = ([string](Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 10)).Trim() } catch { }

$edgePath = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$edge = ''
if (Test-Path $edgePath) { $edge = (Get-Item $edgePath).VersionInfo.ProductVersion }

$os  = Get-CimInstance Win32_OperatingSystem
$dns = @(Get-DnsClientServerAddress -AddressFamily IPv4 | ForEach-Object { $_.ServerAddresses } | Select-Object -Unique)

[ordered]@{
  os       = "$($os.Caption) $($os.Version)"
  tz       = (Get-TimeZone).Id
  dns      = $dns
  rdp      = [bool](Get-NetTCPConnection -LocalPort 3389 -State Listen)
  edge     = $edge
  egress   = $egress
  private  = $private
  outbound = $outbound
} | ConvertTo-Json -Depth 5 -Compress
