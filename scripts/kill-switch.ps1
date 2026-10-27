#requires -Version 7
<#
.SYNOPSIS
  Agents Behind the Wall - SOC kill switch: cut one or more users off from every MCP API at the gateway.

.DESCRIPTION
  The gateway policy (infra\apim\policies\mcp-jwt.policy.xml) rejects any token whose `oid` is listed in the APIM named value
  `abw-deny-oids` with HTTP 403 reason=revoked, whatever roles the token carries. This script maintains that list and can also revoke
  the user's Entra refresh tokens so no NEW access token can be minted from an existing session.

    Layer                          What it stops                                          Latency
    APIM named value  (always)     every MCP API call that presents a token for the user  about a minute (named value propagation)
    revokeSignInSessions (switch)  minting new tokens from the user's existing sessions   minutes (near immediate for CAE-capable clients)
    disable the Entra account      sign-in altogether                                     manual on purpose - an identity decision, not a gateway one

  -User accepts a persona alias (priya, wes, tara, carla, ian), a UPN, an object id, or 'operator' (the signed-in Azure CLI user).
  Sessions are never revoked for the operator unless -Force is added (that would also sign the Azure CLI out).

.EXAMPLE
  .\scripts\kill-switch.ps1 -Show
  .\scripts\kill-switch.ps1 -User wes
  .\scripts\kill-switch.ps1 -User wes -RevokeSessions
  .\scripts\kill-switch.ps1 -User wes -Restore
  .\scripts\kill-switch.ps1 -Reset
#>
[CmdletBinding()]
param(
  [string]$User,
  [switch]$Restore,
  [switch]$Reset,
  [switch]$Show,
  [switch]$RevokeSessions,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"

$cfg   = Get-AbwConfig
$names = Get-AbwNames $cfg
$ent   = Read-Json (Join-Path $script:GenDir 'entra.json')
if (-not $ent) { throw 'Run Entra phase 1 first (identity\Setup-Entra.ps1).' }
$nvId = 'abw-deny-oids'

function Resolve-Oid([string]$Who) {
  if ($Who -match '^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$') { return $Who.ToLowerInvariant() }
  if ($Who -eq 'operator') { return $cfg.operatorOid.ToLowerInvariant() }
  $persona = $ent.users.$Who
  if ($persona) { return $persona.oid.ToLowerInvariant() }
  if ($Who -like '*@*') {
    $u = Invoke-Graph -Path "/users/$([uri]::EscapeDataString($Who))" -Query @{ '$select' = 'id' }
    return $u.id.ToLowerInvariant()
  }
  throw "cannot resolve '$Who' - use a persona alias, UPN, object id or 'operator'"
}

function Get-Label([string]$Oid) {
  foreach ($p in $ent.users.PSObject.Properties) { if ($p.Value.oid -eq $Oid) { return "$($p.Name) ($($p.Value.upn))" } }
  if ($Oid -eq $cfg.operatorOid) { return "operator ($($cfg.operatorUpn))" }
  return $Oid
}

function Get-DenyList {
  $v = (az apim nv show --service-name $names.apim -g $cfg.rgName --named-value-id $nvId --query value -o tsv --only-show-errors).Trim()
  if ($LASTEXITCODE -ne 0) { throw 'could not read the APIM named value' }
  if (-not $v -or $v -eq 'none') { return @() }
  return @($v -split ',' | Where-Object { $_ } | ForEach-Object { $_.Trim().ToLowerInvariant() })
}

function Set-DenyList([string[]]$Oids) {
  $value = if ($Oids.Count -eq 0) { 'none' } else { $Oids -join ',' }
  az apim nv update --service-name $names.apim -g $cfg.rgName --named-value-id $nvId --value $value --only-show-errors -o none
  if ($LASTEXITCODE -ne 0) { throw 'could not update the APIM named value' }
}

function Write-List([string[]]$Oids, [string]$Title) {
  Write-Step $Title
  if ($Oids.Count -eq 0) { Write-Ok 'deny list is empty - nobody is revoked' }
  foreach ($o in $Oids) { Write-Host "    -   $(Get-Label $o)" -ForegroundColor Yellow }
}

if ($Show -or (-not $User -and -not $Reset)) {
  Write-List (Get-DenyList) "gateway deny list ($nvId on $($names.apim))"
  return
}

$current = @(Get-DenyList)
$stamp = (Get-Date).ToUniversalTime().ToString('HH:mm:ss') + 'Z'

if ($Reset) {
  Set-DenyList @()
  Write-List @() "kill switch cleared at $stamp"
  return
}

$oid = Resolve-Oid $User
$label = Get-Label $oid

if ($Restore) {
  Set-DenyList @($current | Where-Object { $_ -ne $oid })
  Write-Ok "restored $label at $stamp - gateway picks the change up in about a minute"
  Write-List @(Get-DenyList) 'gateway deny list'
  return
}

if ($oid -notin $current) { Set-DenyList @($current + $oid) }
Write-Ok "revoked $label at the gateway at $stamp - APIM applies the named value within about a minute"

if ($RevokeSessions) {
  if ($oid -eq $cfg.operatorOid.ToLowerInvariant() -and -not $Force) {
    Write-Warn2 'not revoking sign-in sessions for the operator (it would sign the Azure CLI out) - add -Force to do it anyway'
  } else {
    Invoke-Graph -Method POST -Path "/users/$oid/revokeSignInSessions" | Out-Null
    Write-Ok "revoked Entra sign-in sessions (refresh tokens) for $label"
  }
}
Write-List @(Get-DenyList) 'gateway deny list'
Write-Host '    next: the same call that worked a minute ago now returns 403 reason=revoked; Sentinel rule ABW-005 raises the incident.' -ForegroundColor DarkGray
