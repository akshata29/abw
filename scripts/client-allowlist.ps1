#requires -Version 7
<#
.SYNOPSIS
  Agents Behind the Wall - maintain the gateway's calling-application (azp) allow-list.

.DESCRIPTION
  The gateway policy (infra\apim\policies\mcp-jwt.policy.xml) accepts a validly signed Entra token only when its `azp` claim - the client application
  that asked for the token - is in the APIM named value `abw-allowed-azp`. A token minted for ANY other app (a replayed or phished token,
  a developer's script, a first-party tool) is rejected with HTTP 403 reason=client_not_allowed, and Sentinel rule ABW-004 raises an incident.

    alias   application
    agent   abw-agent-client       (Foundry agent OAuth identity passthrough)
    test    abw-test-client        (persona sign-in used by the proofs)
    azcli   Microsoft Azure CLI    (operator testing - stands in for "some other app" on stage)

  -Block takes an alias or an application (client) id and removes it from the list; -Allow adds it back; -Reset restores all three.

.EXAMPLE
  .\scripts\client-allowlist.ps1 -Show
  .\scripts\client-allowlist.ps1 -Block azcli
  .\scripts\client-allowlist.ps1 -Allow azcli
  .\scripts\client-allowlist.ps1 -Reset
#>
[CmdletBinding()]
param(
  [string]$Block,
  [string]$Allow,
  [switch]$Reset,
  [switch]$Show
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"

$cfg   = Get-AbwConfig
$names = Get-AbwNames $cfg
$ent   = Read-Json (Join-Path $script:GenDir 'entra.json')
if (-not $ent) { throw 'Run Entra phase 1 first (identity\Setup-Entra.ps1).' }
$nvId = 'abw-allowed-azp'

$aliases = [ordered]@{
  agent = $ent.clients.agent.appId.ToLowerInvariant()
  test  = $ent.clients.test.appId.ToLowerInvariant()
  azcli = '04b07795-8ddb-461a-bbee-02f9e1bf7b46'
}

function Resolve-Client([string]$Who) {
  if ($aliases.Contains($Who)) { return $aliases[$Who] }
  if ($Who -match '^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$') { return $Who.ToLowerInvariant() }
  throw "cannot resolve '$Who' - use agent, test, azcli or an application (client) id"
}

function Get-Label([string]$AppId) {
  foreach ($k in $aliases.Keys) { if ($aliases[$k] -eq $AppId) { return "$k ($AppId)" } }
  return $AppId
}

function Get-List {
  $v = (az apim nv show --service-name $names.apim -g $cfg.rgName --named-value-id $nvId --query value -o tsv --only-show-errors).Trim()
  if ($LASTEXITCODE -ne 0) { throw 'could not read the APIM named value' }
  return @($v -split ',' | Where-Object { $_ } | ForEach-Object { $_.Trim().ToLowerInvariant() })
}

function Set-List([string[]]$AppIds) {
  if ($AppIds.Count -eq 0) { throw 'refusing to write an empty allow-list (every call would be rejected, including the agents)' }
  az apim nv update --service-name $names.apim -g $cfg.rgName --named-value-id $nvId --value ($AppIds -join ',') --only-show-errors -o none
  if ($LASTEXITCODE -ne 0) { throw 'could not update the APIM named value' }
}

function Write-List([string[]]$AppIds, [string]$Title) {
  Write-Step $Title
  foreach ($a in $AppIds) { Write-Host "    +   $(Get-Label $a)" -ForegroundColor Green }
  foreach ($k in $aliases.Keys) { if ($aliases[$k] -notin $AppIds) { Write-Host "    -   $(Get-Label $aliases[$k])   (not allowed)" -ForegroundColor Yellow } }
}

$current = @(Get-List)
$stamp = (Get-Date).ToUniversalTime().ToString('HH:mm:ss') + 'Z'

if ($Show -or (-not $Block -and -not $Allow -and -not $Reset)) {
  Write-List $current "approved calling applications ($nvId on $($names.apim))"
  return
}

if ($Reset) {
  Set-List @($aliases.Values)
  Write-Ok "allow-list restored to agent + test + azcli at $stamp"
  Write-List @($aliases.Values) 'approved calling applications'
  return
}

if ($Block) {
  $id = Resolve-Client $Block
  Set-List @($current | Where-Object { $_ -ne $id })
  Write-Ok "removed $(Get-Label $id) from the allow-list at $stamp - APIM applies the named value within about a minute"
  Write-Host '    next: a perfectly valid token from that application now returns 403 reason=client_not_allowed; Sentinel rule ABW-004 raises the incident.' -ForegroundColor DarkGray
}
if ($Allow) {
  $id = Resolve-Client $Allow
  if ($id -notin $current) { $current = @($current + $id) }
  Set-List $current
  Write-Ok "added $(Get-Label $id) to the allow-list at $stamp"
}
Write-List @(Get-List) 'approved calling applications'
