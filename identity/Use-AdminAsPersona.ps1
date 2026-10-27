<#
.SYNOPSIS
  Dev/test helper: make the signed-in ADMIN mirror a persona's app roles + group memberships so tokens
  from `az account get-access-token --scope api://<id>/Tools.Read` look like that persona's.

.DESCRIPTION
  Both tenants this was built in force MFA for every user (the first also blocked MFA registration outside the VPN/SAW ranges), so
  scripted sign-in of the five persona accounts is not possible until their MFA is enrolled (one-time,
  manual: README "Persona sign-in"; store each TOTP secret with identity\Persona-Totp.py). This script lets
  us test the whole stack (APIM validate-jwt, MCP role
  filtering, OBO -> Storage/Cosmos/Search RBAC) with the already-MFA'd admin identity in the meantime.
  Real persona sign-in (Path A) is preferred for the live demo; the final proof run in the second tenant used this admin-as-persona path.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][ValidateSet('priya', 'wes', 'tara', 'carla', 'ian', 'none')][string]$As,
  # Union extra personas' roles/groups (e.g. -As wes -Also tara = a wall-crossed user who can also trade).
  [ValidateSet('priya', 'wes', 'tara', 'carla', 'ian')][string[]]$Also = @()
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\common.ps1')
$cfg = Get-AbwConfig
$state = Read-Json (Join-Path $script:GenDir 'entra.json')
$adminOid = $cfg.operatorOid
if (-not $adminOid) { $adminOid = (az ad signed-in-user show --query id -o tsv) }

$wantRoles = @(); $wantGroups = @()
if ($As -ne 'none') { $wantRoles = @($state.users.$As.roles); $wantGroups = @($state.users.$As.groups) }
foreach ($extra in $Also) { $wantRoles += @($state.users.$extra.roles); $wantGroups += @($state.users.$extra.groups) }
$wantRoles = @($wantRoles | Select-Object -Unique); $wantGroups = @($wantGroups | Select-Object -Unique)

# ---- app roles
$apiSpIds = @{}; foreach ($k in $state.apis.PSObject.Properties.Name) { $apiSpIds[$state.apis.$k.spId] = $k }
$have = Get-GraphAll "/users/$adminOid/appRoleAssignments" | Where-Object { $apiSpIds.ContainsKey($_.resourceId) }
$wantSet = @{}
foreach ($ra in $wantRoles) {
  $apiKey, $roleName = $ra -split ':'
  $wantSet["$($state.apis.$apiKey.spId)|$($state.apis.$apiKey.roleIds.$roleName)"] = $ra
}
foreach ($h in $have) {
  $key = "$($h.resourceId)|$($h.appRoleId)"
  if (-not $wantSet.ContainsKey($key)) { Invoke-Graph -Method DELETE -Path "/users/$adminOid/appRoleAssignments/$($h.id)" | Out-Null; Write-Ok "removed role $($apiSpIds[$h.resourceId]) $($h.appRoleId)" }
  else { $wantSet.Remove($key) }
}
foreach ($key in @($wantSet.Keys)) {
  $spId, $roleId = $key -split '\|'
  Invoke-Graph -Method POST -Path "/users/$adminOid/appRoleAssignments" -Body @{ principalId = $adminOid; resourceId = $spId; appRoleId = $roleId } | Out-Null
  Write-Ok "added role $($wantSet[$key])"
}

# ---- groups
foreach ($g in $state.groups.PSObject.Properties) {
  $gid = $g.Value
  $members = Get-GraphAll "/groups/$gid/members" @{ '$select' = 'id' }
  $isMember = [bool]($members | Where-Object { $_.id -eq $adminOid })
  $should = $wantGroups -contains $g.Name
  if ($should -and -not $isMember) { Invoke-Graph -Method POST -Path "/groups/$gid/members/`$ref" -Body @{ '@odata.id' = "https://graph.microsoft.com/v1.0/directoryObjects/$adminOid" } | Out-Null; Write-Ok "joined $($g.Name)" }
  if (-not $should -and $isMember) { Invoke-Graph -Method DELETE -Path "/groups/$gid/members/$adminOid/`$ref" | Out-Null; Write-Ok "left $($g.Name)" }
}
Write-Step "Admin now mirrors persona '$As'$(if ($Also) { ' + ' + ($Also -join ' + ') }) (roles: $($wantRoles -join ', ')) - request a NEW token to see it"
