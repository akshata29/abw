<#
.SYNOPSIS
  Idempotent Microsoft Entra setup for "Agents Behind the Wall" (synthetic demo identities).

.DESCRIPTION
  Phase 1  : security groups, persona users, MCP API apps (scopes + app roles), client apps,
             direct user->app-role assignments (group-based app-role assignment needs Entra P1, so roles go to users),
             admin consent (incl. OBO consent to Storage / Cosmos DB / AI Search).
  Phase 2  : federated identity credentials (UAMI -> app, secretless OBO) + optional redirect URIs.
             Needs infra\generated\platform.json (written by the platform deployment).
  Teardown : deletes every object tagged / named for this demo.

  Secrets (persona passwords, agent-client secret) are written ONLY to .secrets\ (git-ignored).
#>
[CmdletBinding()]
param(
  [ValidateSet('1', '2', 'Teardown')][string]$Phase = '1',
  [string[]]$AgentClientRedirectUris = @()
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\common.ps1')
$cfg = Get-AbwConfig
$tenantId = $cfg.tenantId
$domain = $cfg.tenantDomain
$entraStatePath = Join-Path $script:GenDir 'entra.json'
$companyMarker = 'Contoso Capital Markets (ABW demo)'

# ------------------------------------------------------------------ definitions
$Apis = [ordered]@{
  research = @{ name = 'abw-mcp-research'; obo = @('storage', 'search')
    scopes = @(@{ v = 'Tools.Read'; d = 'Use read-only tools on the research MCP server' })
    roles  = @(@{ v = 'Research.Read'; d = 'May read public research notes' }) }
  wall     = @{ name = 'abw-mcp-wall'; obo = @('storage', 'search')
    scopes = @(@{ v = 'Tools.Read'; d = 'Use read-only tools on the wall (MNPI) MCP server' })
    roles  = @(@{ v = 'Wall.Falcon'; d = 'Wall-crossed on Project Falcon (MNPI)' }, @{ v = 'Wall.Orion'; d = 'Wall-crossed on Project Orion (MNPI)' }) }
  actions  = @{ name = 'abw-mcp-actions'; obo = @('cosmos')
    scopes = @(@{ v = 'Tools.Read'; d = 'Use read-only tools on the actions MCP server' }, @{ v = 'Tools.Execute'; d = 'Execute state-changing tools (orders) on the actions MCP server' })
    roles  = @(@{ v = 'Trade.Read'; d = 'May view orders and the restricted list' }, @{ v = 'Trade.Execute'; d = 'May place orders' }) }
  private  = @{ name = 'abw-mcp-private'; obo = @('cosmos')
    scopes = @(@{ v = 'Tools.Read'; d = 'Use read-only tools on the private (internal-only) MCP server' })
    roles  = @(@{ v = 'Positions.Read'; d = 'May read firm positions and credit limits' }) }
  vendorgw = @{ name = 'abw-mcp-vendorgw'; obo = @()
    scopes = @(@{ v = 'Tools.Read'; d = 'Use the external market-data MCP server through the gateway' })
    roles  = @(@{ v = 'MarketData.Read'; d = 'May read external market data via the gateway' }) }
}
$OboResources = [ordered]@{ storage = 'https://storage.azure.com'; cosmos = 'https://cosmos.azure.com'; search = 'https://search.azure.com' }

$Groups = @('sg-abw-demo-all', 'sg-abw-research', 'sg-abw-wall-falcon', 'sg-abw-traders', 'sg-abw-compliance', 'sg-abw-infosec')

$Users = @(
  @{ key = 'priya'; display = 'Priya Raman (ABW)'; job = 'Research Analyst'; dept = 'Research'
     roles = @('research:Research.Read', 'vendorgw:MarketData.Read'); groups = @('sg-abw-demo-all', 'sg-abw-research') }
  @{ key = 'wes'; display = 'Wes Okafor (ABW)'; job = 'Investment Banking Associate'; dept = 'Investment Banking'
     roles = @('research:Research.Read', 'wall:Wall.Falcon', 'vendorgw:MarketData.Read'); groups = @('sg-abw-demo-all', 'sg-abw-research', 'sg-abw-wall-falcon') }
  @{ key = 'tara'; display = 'Tara Lindqvist (ABW)'; job = 'Equity Trader'; dept = 'Trading'
     roles = @('research:Research.Read', 'actions:Trade.Execute', 'private:Positions.Read', 'vendorgw:MarketData.Read'); groups = @('sg-abw-demo-all', 'sg-abw-research', 'sg-abw-traders') }
  @{ key = 'carla'; display = 'Carla Mendes (ABW)'; job = 'Compliance Officer'; dept = 'Compliance'
     roles = @('research:Research.Read', 'wall:Wall.Falcon', 'actions:Trade.Read', 'private:Positions.Read', 'vendorgw:MarketData.Read'); groups = @('sg-abw-demo-all', 'sg-abw-research', 'sg-abw-wall-falcon', 'sg-abw-compliance') }
  @{ key = 'ian'; display = 'Ian Kowalski (ABW)'; job = 'Information Security Analyst'; dept = 'InfoSec'
     roles = @(); groups = @('sg-abw-demo-all', 'sg-abw-infosec') }
)

# ------------------------------------------------------------------ helpers
function Find-One([string]$Path, [string]$Filter, [string]$Select = $null) {
  $q = @{ '$filter' = $Filter }
  if ($Select) { $q['$select'] = $Select }
  $r = Invoke-Graph -Path $Path -Query $q
  return ($r.value | Select-Object -First 1)
}

function Ensure-ServicePrincipal([string]$AppId) {
  $sp = Find-One '/servicePrincipals' "appId eq '$AppId'"
  if ($sp) { return $sp }
  return Invoke-Retry -What 'service principal' -Script {
    Invoke-Graph -Method POST -Path '/servicePrincipals' -Body @{ appId = $AppId; tags = @('abw-demo') }
  }
}

function Ensure-Grant([string]$ClientSpId, [string]$ResourceSpId, [string]$Scope) {
  $ex = Invoke-Retry -What 'grant lookup' -Attempts 6 -DelaySec 4 -Script { Get-GraphAll '/oauth2PermissionGrants' @{ '$filter' = "clientId eq '$ClientSpId' and resourceId eq '$ResourceSpId'" } } | Select-Object -First 1
  if ($ex) {
    if (($ex.scope -as [string]).Trim() -ne $Scope) { Invoke-Graph -Method PATCH -Path "/oauth2PermissionGrants/$($ex.id)" -Body @{ scope = $Scope } | Out-Null }
    return
  }
  Invoke-Retry -What 'admin consent' -Script {
    Invoke-Graph -Method POST -Path '/oauth2PermissionGrants' -Body @{ clientId = $ClientSpId; consentType = 'AllPrincipals'; resourceId = $ResourceSpId; scope = $Scope } | Out-Null
  }
}

function Get-OboTargets {
  $t = [ordered]@{}
  foreach ($k in $OboResources.Keys) {
    $spn = $OboResources[$k]
    $sp = Find-One '/servicePrincipals' "servicePrincipalNames/any(x:x eq '$spn')" 'id,appId,displayName,oauth2PermissionScopes'
    if (-not $sp) { Write-Warn2 "First-party SP for $spn not found - skipping OBO to $k"; continue }
    $scope = $sp.oauth2PermissionScopes | Where-Object { $_.value -eq 'user_impersonation' } | Select-Object -First 1
    if (-not $scope) { Write-Warn2 "$($sp.displayName) has no user_impersonation scope - skipping OBO to $k"; continue }
    $t[$k] = @{ spId = $sp.id; appId = $sp.appId; scopeId = $scope.id; name = $sp.displayName }
  }
  return $t
}

# ------------------------------------------------------------------ Phase 1
function Invoke-Phase1 {
  $state = [ordered]@{ tenantId = $tenantId; tenantDomain = $domain; apis = [ordered]@{}; clients = [ordered]@{}; users = [ordered]@{}; groups = [ordered]@{}; obo = [ordered]@{} }

  Write-Step 'Resolving first-party OBO targets (Storage / Cosmos DB / AI Search)'
  $obo = Get-OboTargets
  foreach ($k in $obo.Keys) { Write-Ok "$($obo[$k].name)  user_impersonation=$($obo[$k].scopeId)"; $state.obo[$k] = $obo[$k] }

  Write-Step 'Security groups'
  foreach ($g in $Groups) {
    $ex = Find-One '/groups' "displayName eq '$g'" 'id,displayName'
    if (-not $ex) {
      $ex = Invoke-Graph -Method POST -Path '/groups' -Body @{ displayName = $g; mailNickname = $g; mailEnabled = $false; securityEnabled = $true; description = 'Agents Behind the Wall demo (synthetic). Used for Azure RBAC.' }
      Write-Ok "created $g"
    } else { Write-Ok "exists  $g" }
    $state.groups[$g] = $ex.id
  }

  Write-Step 'API apps (one per MCP server)'
  foreach ($key in $Apis.Keys) {
    $def = $Apis[$key]
    $scopes = @(foreach ($s in $def.scopes) { @{ id = (New-DetGuid "scope:$key`:$($s.v)"); value = $s.v; type = 'Admin'; isEnabled = $true; adminConsentDisplayName = $s.d; adminConsentDescription = $s.d } })
    $roles = @(foreach ($r in $def.roles) { @{ id = (New-DetGuid "role:$key`:$($r.v)"); value = $r.v; displayName = $r.v; description = $r.d; isEnabled = $true; allowedMemberTypes = @('User') } })
    $rra = @(foreach ($o in $def.obo) { if ($obo.Contains($o)) { @{ resourceAppId = $obo[$o].appId; resourceAccess = @(@{ id = $obo[$o].scopeId; type = 'Scope' }) } } })

    $app = Find-One '/applications' "displayName eq '$($def.name)'" 'id,appId,displayName'
    $body = @{ displayName = $def.name; signInAudience = 'AzureADMyOrg'; tags = @('abw-demo'); notes = 'Agents Behind the Wall demo (synthetic)'
               api = @{ requestedAccessTokenVersion = 2; oauth2PermissionScopes = $scopes }; appRoles = $roles; requiredResourceAccess = $rra }
    if (-not $app) { $app = Invoke-Graph -Method POST -Path '/applications' -Body $body; Write-Ok "created $($def.name)" }
    else { Invoke-Graph -Method PATCH -Path "/applications/$($app.id)" -Body $body | Out-Null; Write-Ok "updated $($def.name)" }
    Invoke-Retry -What 'identifierUris' -Script { Invoke-Graph -Method PATCH -Path "/applications/$($app.id)" -Body @{ identifierUris = @("api://$($app.appId)") } | Out-Null }
    $sp = Ensure-ServicePrincipal $app.appId

    foreach ($o in $def.obo) { if ($obo.Contains($o)) { Ensure-Grant $sp.id $obo[$o].spId 'user_impersonation' } }
    $state.apis[$key] = [ordered]@{
      name = $def.name; appId = $app.appId; objectId = $app.id; spId = $sp.id; audience = $app.appId; identifierUri = "api://$($app.appId)"
      scopes = @($def.scopes | ForEach-Object { $_.v }); roles = @($def.roles | ForEach-Object { $_.v })
      roleIds = [ordered]@{}
    }
    foreach ($r in $def.roles) { $state.apis[$key].roleIds[$r.v] = New-DetGuid "role:$key`:$($r.v)" }
  }

  Write-Step 'Client apps'
  $clientRra = @(foreach ($key in $Apis.Keys) {
    @{ resourceAppId = $state.apis[$key].appId; resourceAccess = @(foreach ($s in $Apis[$key].scopes) { @{ id = (New-DetGuid "scope:$key`:$($s.v)"); type = 'Scope' } }) }
  })

  # abw-agent-client: confidential web app used by the Foundry OAuth connections
  $agent = Find-One '/applications' "displayName eq 'abw-agent-client'" 'id,appId,passwordCredentials'
  $agentBody = @{ displayName = 'abw-agent-client'; signInAudience = 'AzureADMyOrg'; tags = @('abw-demo'); notes = 'Foundry OAuth identity-passthrough client (synthetic demo)'
                  requiredResourceAccess = $clientRra; web = @{ redirectUris = @('https://localhost/abw-placeholder'); implicitGrantSettings = @{ enableAccessTokenIssuance = $false; enableIdTokenIssuance = $false } } }
  if (-not $agent) { $agent = Invoke-Graph -Method POST -Path '/applications' -Body $agentBody; Write-Ok 'created abw-agent-client' }
  else { Invoke-Graph -Method PATCH -Path "/applications/$($agent.id)" -Body @{ requiredResourceAccess = $clientRra; tags = @('abw-demo') } | Out-Null; Write-Ok 'updated abw-agent-client' }
  $agentSp = Ensure-ServicePrincipal $agent.appId

  $secretPath = Join-Path $script:SecretsDir 'agent-client.json'
  $secretObj = Read-Json $secretPath
  $needSecret = $true
  if ($secretObj -and $secretObj.appId -eq $agent.appId) {
    $live = (Invoke-Graph -Path "/applications/$($agent.id)" -Query @{ '$select' = 'passwordCredentials' }).passwordCredentials
    if ($live | Where-Object { $_.keyId -eq $secretObj.keyId -and [datetime]$_.endDateTime -gt (Get-Date).AddDays(10) }) { $needSecret = $false }
  }
  if ($needSecret) {
    $pw = Invoke-Graph -Method POST -Path "/applications/$($agent.id)/addPassword" -Body @{ passwordCredential = @{ displayName = 'foundry-connection'; endDateTime = (Get-Date).AddDays(80).ToUniversalTime().ToString('o') } }
    Save-Json $secretPath ([ordered]@{ appId = $agent.appId; keyId = $pw.keyId; secret = $pw.secretText; expires = $pw.endDateTime })
    Write-Ok 'agent-client secret created -> .secrets\agent-client.json'
  } else { Write-Ok 'agent-client secret present' }

  # abw-test-client: public client used by demo\prove.py to sign personas in (MSAL)
  $test = Find-One '/applications' "displayName eq 'abw-test-client'" 'id,appId'
  $testBody = @{ displayName = 'abw-test-client'; signInAudience = 'AzureADMyOrg'; tags = @('abw-demo'); notes = 'Persona sign-in client for demo proofs (synthetic)'
                 isFallbackPublicClient = $true; requiredResourceAccess = $clientRra
                 publicClient = @{ redirectUris = @('http://localhost') } }
  if (-not $test) { $test = Invoke-Graph -Method POST -Path '/applications' -Body $testBody; Write-Ok 'created abw-test-client' }
  else { Invoke-Graph -Method PATCH -Path "/applications/$($test.id)" -Body $testBody | Out-Null; Write-Ok 'updated abw-test-client' }
  $testSp = Ensure-ServicePrincipal $test.appId

  foreach ($pair in @(@{ n = 'agent'; sp = $agentSp; app = $agent }, @{ n = 'test'; sp = $testSp; app = $test })) {
    foreach ($key in $Apis.Keys) {
      Ensure-Grant $pair.sp.id $state.apis[$key].spId (($Apis[$key].scopes | ForEach-Object { $_.v }) -join ' ')
    }
    Write-Ok "admin consent: $($pair.n) client -> all MCP APIs"
  }
  $state.clients['agent'] = [ordered]@{ name = 'abw-agent-client'; appId = $agent.appId; objectId = $agent.id; spId = $agentSp.id }
  $state.clients['test'] = [ordered]@{ name = 'abw-test-client'; appId = $test.appId; objectId = $test.id; spId = $testSp.id }

  Write-Step 'Pre-authorize Azure CLI on the MCP APIs (dev/test tokens: az account get-access-token --scope api://<id>/Tools.Read)'
  $azCliAppId = '04b07795-8ddb-461a-bbee-02f9e1bf7b46'
  foreach ($key in $Apis.Keys) {
    $scopeObjs = @(foreach ($s in $Apis[$key].scopes) { @{ id = (New-DetGuid "scope:$key`:$($s.v)"); value = $s.v; type = 'Admin'; isEnabled = $true; adminConsentDisplayName = $s.d; adminConsentDescription = $s.d } })
    $body = @{ api = @{ requestedAccessTokenVersion = 2; oauth2PermissionScopes = $scopeObjs; preAuthorizedApplications = @(@{ appId = $azCliAppId; delegatedPermissionIds = @($scopeObjs | ForEach-Object { $_.id }) }) } }
    Invoke-Retry -What 'preAuthorizedApplications' -Script { Invoke-Graph -Method PATCH -Path "/applications/$($state.apis[$key].objectId)" -Body $body | Out-Null }
  }
  Write-Ok 'Azure CLI pre-authorized'

  Write-Step 'Persona users'
  $pwPath = Join-Path $script:SecretsDir 'personas.json'
  $personas = Read-Json $pwPath
  if (-not $personas) { $personas = [pscustomobject]@{} }
  foreach ($u in $Users) {
    $upn = "abw.$($u.key)@$domain"
    $ex = Find-One '/users' "userPrincipalName eq '$upn'" 'id,userPrincipalName'
    $known = $personas.PSObject.Properties.Name -contains $u.key
    if (-not $ex) {
      $pw = New-StrongPassword
      $ex = Invoke-Graph -Method POST -Path '/users' -Body @{
        accountEnabled = $true; displayName = $u.display; mailNickname = "abw.$($u.key)"; userPrincipalName = $upn
        usageLocation = 'US'; jobTitle = $u.job; department = $u.dept; companyName = $companyMarker; passwordPolicies = 'DisablePasswordExpiration'
        passwordProfile = @{ forceChangePasswordNextSignIn = $false; password = $pw } }
      $personas | Add-Member -NotePropertyName $u.key -NotePropertyValue ([pscustomobject]@{ upn = $upn; password = $pw; oid = $ex.id }) -Force
      Write-Ok "created $upn"
    } elseif (-not $known) {
      $pw = New-StrongPassword
      Invoke-Graph -Method PATCH -Path "/users/$($ex.id)" -Body @{ passwordProfile = @{ forceChangePasswordNextSignIn = $false; password = $pw }; passwordPolicies = 'DisablePasswordExpiration' } | Out-Null
      $personas | Add-Member -NotePropertyName $u.key -NotePropertyValue ([pscustomobject]@{ upn = $upn; password = $pw; oid = $ex.id }) -Force
      Write-Ok "exists $upn (password reset, stored)"
    } else { Write-Ok "exists  $upn" }
    $state.users[$u.key] = [ordered]@{ upn = $upn; oid = $ex.id; display = $u.display; job = $u.job; roles = @($u.roles); groups = @($u.groups) }
  }
  Save-Json $pwPath $personas

  Write-Step 'Group membership'
  foreach ($u in $Users) {
    $oid = $state.users[$u.key].oid
    foreach ($g in $u.groups) {
      $gid = $state.groups[$g]
      $members = Get-GraphAll "/groups/$gid/members" @{ '$select' = 'id' }
      if (-not ($members | Where-Object { $_.id -eq $oid })) {
        Invoke-Graph -Method POST -Path "/groups/$gid/members/`$ref" -Body @{ '@odata.id' = "https://graph.microsoft.com/v1.0/directoryObjects/$oid" } | Out-Null
        Write-Ok "$($u.key) -> $g"
      }
    }
  }

  Write-Step 'App-role assignments (direct to users)'
  foreach ($u in $Users) {
    $oid = $state.users[$u.key].oid
    $have = Get-GraphAll "/users/$oid/appRoleAssignments"
    foreach ($ra in $u.roles) {
      $apiKey, $roleName = $ra -split ':'
      $spId = $state.apis[$apiKey].spId
      $roleId = $state.apis[$apiKey].roleIds[$roleName]
      if ($have | Where-Object { $_.resourceId -eq $spId -and $_.appRoleId -eq $roleId }) { continue }
      Invoke-Retry -What 'role assignment' -Script {
        Invoke-Graph -Method POST -Path "/users/$oid/appRoleAssignments" -Body @{ principalId = $oid; resourceId = $spId; appRoleId = $roleId } | Out-Null
      }
      Write-Ok "$($u.key) <- $apiKey/$roleName"
    }
  }

  Save-Json $entraStatePath $state
  Write-Step "Phase 1 complete -> $entraStatePath"
}

# ------------------------------------------------------------------ Phase 2
function Invoke-Phase2 {
  $state = Read-Json $entraStatePath
  if (-not $state) { throw 'Run Phase 1 first.' }
  $platform = Read-Json (Join-Path $script:GenDir 'platform.json')
  if (-not $platform) { throw 'infra\generated\platform.json missing (deploy 03-platform first).' }

  Write-Step 'Federated identity credentials (UAMI -> MCP app; secretless OBO)'
  $issuer = "https://login.microsoftonline.com/$tenantId/v2.0"
  foreach ($key in @('research', 'wall', 'actions', 'private')) {
    $principalId = $platform.uamis.$key.principalId
    if (-not $principalId) { Write-Warn2 "no UAMI principal for $key"; continue }
    $app = $state.apis.$key
    $name = "uami-$key"
    $existing = (Invoke-Graph -Path "/applications/$($app.objectId)/federatedIdentityCredentials").value | Where-Object { $_.name -eq $name }
    if ($existing -and $existing.subject -eq $principalId) { Write-Ok "exists  $name"; continue }
    if ($existing) { Invoke-Graph -Method DELETE -Path "/applications/$($app.objectId)/federatedIdentityCredentials/$($existing.id)" | Out-Null }
    Invoke-Graph -Method POST -Path "/applications/$($app.objectId)/federatedIdentityCredentials" -Body @{ name = $name; issuer = $issuer; subject = $principalId; audiences = @('api://AzureADTokenExchange'); description = "UAMI id-abw-mcp-$key" } | Out-Null
    Write-Ok "created $name -> subject $principalId"
  }

  if ($AgentClientRedirectUris.Count -gt 0) {
    Write-Step 'Redirect URIs on abw-agent-client'
    $cur = (Invoke-Graph -Path "/applications/$($state.clients.agent.objectId)" -Query @{ '$select' = 'web' }).web.redirectUris
    $merged = @($cur | Where-Object { $_ -notlike 'https://localhost/abw-placeholder' }) + $AgentClientRedirectUris | Select-Object -Unique
    Invoke-Graph -Method PATCH -Path "/applications/$($state.clients.agent.objectId)" -Body @{ web = @{ redirectUris = @($merged) } } | Out-Null
    $merged | ForEach-Object { Write-Ok $_ }
  }
  Write-Step 'Phase 2 complete'
}

# ------------------------------------------------------------------ Teardown
function Invoke-Teardown {
  Write-Step 'Deleting demo apps / users / groups'
  foreach ($a in (Get-GraphAll '/applications' @{ '$filter' = "tags/any(t:t eq 'abw-demo')"; '$select' = 'id,displayName' })) {
    Invoke-Graph -Method DELETE -Path "/applications/$($a.id)" | Out-Null; Write-Ok "app $($a.displayName)"
    Invoke-Graph -Method DELETE -Path "/directory/deletedItems/$($a.id)" -AllowNotFound | Out-Null
  }
  foreach ($u in (Get-GraphAll '/users' @{ '$filter' = "companyName eq '$companyMarker'"; '$select' = 'id,userPrincipalName'; '$count' = 'true' })) {
    Invoke-Graph -Method DELETE -Path "/users/$($u.id)" | Out-Null; Write-Ok "user $($u.userPrincipalName)"
    Invoke-Graph -Method DELETE -Path "/directory/deletedItems/$($u.id)" -AllowNotFound | Out-Null
  }
  foreach ($g in (Get-GraphAll '/groups' @{ '$filter' = "startswith(displayName,'sg-abw-')"; '$select' = 'id,displayName' })) {
    Invoke-Graph -Method DELETE -Path "/groups/$($g.id)" | Out-Null; Write-Ok "group $($g.displayName)"
  }
}

switch ($Phase) {
  '1' { Invoke-Phase1 }
  '2' { Invoke-Phase2 }
  'Teardown' { Invoke-Teardown }
}
