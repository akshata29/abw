#requires -Version 7
<#
.SYNOPSIS
  Track B - identity gaps: Entra Agent ID (record), Agent 365 RBAC pre-grant on APIM, Conditional Access (report-only).

.DESCRIPTION
  Idempotent and safe to re-run. Every run re-reads live state and rewrites infra\generated\trackb-identity.json
  (non-secret ids, names and statuses only).

    1. Entra Agent ID      READ-ONLY. abw-wall-desk runs on the new Foundry agent model, so it ALREADY owns a dedicated
                           Entra agent identity + blueprint. No legacy "Agent Application" is created: Learn labels that
                           path legacy (not in the Entra agent registry) and it would add a second identity/blueprint.
    2. Agent 365           Assigns the Azure role "A365 Gateway Policy Operator" (Learn calls it "A365 MCP Gateway Policy
                           Operator"; only the former exists) to the first-party "Agent 365" service principal at the
                           APIM instance scope. This is the RBAC half only. The tenant-level consent (M365 admin center >
                           Agents > Settings > Gateways > "Azure API Management service and AI Gateway") is a human step.
    3. Conditional Access  Creates ONE policy, state enabledForReportingButNotEnforced (never enabled), for the members of
                           sg-abw-demo-all, excluding the operator, every *Administrator directory role and any
                           break-glass-looking group; target resources = the 5 MCP API app registrations; grant = MFA.
                           Existing policies are never read for write, modified or deleted.

  -Remove rolls back exactly what this script adds: the role assignment and the report-only policy (matched by name).
  Only touches the tenant / subscription recorded in infra\generated\config.json.
#>
[CmdletBinding()]
param(
  [switch]$Remove,
  [switch]$SkipAgent365,
  [switch]$SkipConditionalAccess
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"

$cfg   = Get-AbwConfig
$names = Get-AbwNames $cfg
$ent   = Read-Json (Join-Path $script:GenDir 'entra.json')
$outPath = Join-Path $script:GenDir 'trackb-identity.json'

$agentName   = 'abw-wall-desk'
$apimScope   = "/subscriptions/$($cfg.subscriptionId)/resourceGroups/$($cfg.rgName)/providers/Microsoft.ApiManagement/service/$($names.apim)"
$projectBase = "https://$($names.foundry).services.ai.azure.com/api/projects/$($names.project)"
$caName      = 'ABW demo - require MFA for Agent Wall MCP APIs (REPORT-ONLY)'
$msFirstPartyTenant = 'f8cdef31-a31e-4b4a-93e4-5f571e91255a'
$nowUtc = { (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }

# ---------- ARM / Foundry data-plane helpers (tokens come from az, nothing is logged) ----------
function Get-AzToken([string]$Resource) {
  $t = az account get-access-token --resource $Resource --query accessToken -o tsv
  if ($LASTEXITCODE -ne 0 -or -not $t) { throw "Could not get a token for $Resource from az" }
  return $t.Trim()
}
$script:ArmToken = $null
function Invoke-Arm {
  [CmdletBinding()]
  param(
    [ValidateSet('GET','PUT','DELETE')][string]$Method = 'GET',
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string]$Api,
    $Body = $null,
    [hashtable]$Query = $null,
    [switch]$AllowNotFound
  )
  if (-not $script:ArmToken) { $script:ArmToken = Get-AzToken 'https://management.azure.com' }
  $qs = @("api-version=$Api")
  if ($Query) { $qs += ($Query.GetEnumerator() | ForEach-Object { "$($_.Key)=$([uri]::EscapeDataString([string]$_.Value))" }) }
  $params = @{ Method = $Method; Uri = "https://management.azure.com$Path`?$($qs -join '&')"; Headers = @{ Authorization = "Bearer $($script:ArmToken)" }; ErrorAction = 'Stop' }
  if ($null -ne $Body) { $params.Body = (ConvertTo-Json -InputObject $Body -Depth 20); $params.ContentType = 'application/json' }
  try { return Invoke-RestMethod @params } catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { $null }
    if ($AllowNotFound -and $code -eq 404) { return $null }
    throw "ARM $Method $Path failed (HTTP $code): $($_.ErrorDetails.Message)"
  }
}

$out = [ordered]@{
  generatedAt    = (& $nowUtc)
  mode           = $(if ($Remove) { 'remove' } else { 'apply' })
  tenantId       = $cfg.tenantId
  subscriptionId = $cfg.subscriptionId
  resourceGroup  = $cfg.rgName
}

# =====================================================================================================================
# 1. Entra Agent ID  (read-only record of what Foundry already created for the agent)
# =====================================================================================================================
if (-not $Remove) {
  Write-Step "1/3 Entra Agent ID - recording the dedicated identity of $agentName (read-only)"
  $hdr = @{ Authorization = "Bearer $(Get-AzToken 'https://ai.azure.com')"; 'Foundry-Features' = 'AgentEndpoints=V1Preview' }
  $agent = Invoke-RestMethod -Uri "$projectBase/agents/${agentName}?api-version=2025-11-15-preview" -Headers $hdr -ErrorAction Stop
  $latest = $agent.versions.latest
  $inst = $agent.instance_identity ?? $latest.instance_identity
  $bp   = $agent.blueprint ?? $latest.blueprint
  $bpRef = $agent.blueprint_reference ?? $latest.blueprint_reference
  $ep   = $agent.agent_endpoint ?? $latest.agent_endpoint

  $idObj = Invoke-Graph -Beta -Path "/servicePrincipals/$($inst.principal_id)" -Query @{ '$select' = 'id,appId,displayName,accountEnabled,createdDateTime,servicePrincipalType,tags' }
  $sponsors = @((Invoke-Graph -Path "/servicePrincipals/$($inst.principal_id)/microsoft.graph.agentIdentity/sponsors").value)
  $owners   = @((Invoke-Graph -Path "/servicePrincipals/$($inst.principal_id)/owners").value)
  $bpApp = @((Invoke-Graph -Beta -Path '/applications' -Query @{ '$filter' = "appId eq '$($bp.client_id)'"; '$select' = 'id,appId,displayName,createdDateTime' }).value) | Select-Object -First 1
  $bpSp  = Invoke-Graph -Beta -Path "/servicePrincipals/$($bp.principal_id)" -Query @{ '$select' = 'id,appId,displayName,accountEnabled' }

  $allIds = Get-GraphAll '/servicePrincipals/microsoft.graph.agentIdentity' @{ '$select' = 'id,appId,displayName,accountEnabled,createdDateTime,tags' }
  $abwIds = @($allIds | Where-Object { $_.displayName -like "$($names.foundry)-*" } | ForEach-Object {
    $an = ($_.tags | Where-Object { $_ -like 'agentName:*' } | Select-Object -First 1)
    [ordered]@{ objectId = $_.id; appId = $_.appId; displayName = $_.displayName; accountEnabled = $_.accountEnabled
                agentName = $(if ($an) { $an -replace '^agentName:', '' } else { '(project identity)' }) }
  })

  $out.entraAgentId = [ordered]@{
    status = 'LIVE-VERIFIED'
    note   = 'New Foundry agent model: the agent already has its own agent identity + blueprint. Legacy Agent Application intentionally NOT created.'
    agent  = [ordered]@{
      name = $agentName; version = $latest.version; agentGuid = $latest.agent_guid; state = $agent.state; configurationState = $agent.configuration_state
      endpoint = "$projectBase/agents/$agentName/endpoint/protocols/openai/responses"
      publishApprovalStatus = $ep.publish_approval_status; authorizationSchemes = @($ep.authorization_schemes); protocols = @($ep.protocols)
    }
    instanceIdentity = [ordered]@{
      objectId = $idObj.id; appId = $idObj.appId; displayName = $idObj.displayName; accountEnabled = $idObj.accountEnabled
      odataType = $idObj.'@odata.type'; createdDateTime = $idObj.createdDateTime
    }
    blueprint = [ordered]@{
      blueprintId = $bpRef.blueprint_id; appObjectId = $bpApp.id; appId = $bpApp.appId; servicePrincipalId = $bpSp.id
      displayName = $bpApp.displayName; odataTypeSp = $bpSp.'@odata.type'
    }
    sponsors = @($sponsors | ForEach-Object { [ordered]@{ objectId = $_.id; displayName = $_.displayName; upn = $_.userPrincipalName } })
    owners   = @($owners   | ForEach-Object { [ordered]@{ objectId = $_.id; displayName = $_.displayName; type = $_.'@odata.type' } })
    allAbwAgentIdentities = $abwIds
  }
  Write-Ok "instance identity $($idObj.id) accountEnabled=$($idObj.accountEnabled); blueprint app $($bpApp.appId)"
  Write-Ok "$($abwIds.Count) ABW agent identities in the tenant (4 agents + the shared project identity)"
}

# =====================================================================================================================
# 2. Agent 365 - Azure RBAC pre-grant at the APIM instance scope
# =====================================================================================================================
if (-not $SkipAgent365) {
  Write-Step "2/3 Agent 365 - Azure role on $($names.apim)"
  $a365 = [ordered]@{ status = 'BLOCKED'; apimScope = $apimScope }

  $spHits = @((Invoke-Graph -Path '/servicePrincipals' -Query @{ '$filter' = "displayName eq 'Agent 365'"; '$select' = 'id,appId,displayName,appOwnerOrganizationId,servicePrincipalNames' }).value |
              Where-Object { $_.appOwnerOrganizationId -eq $msFirstPartyTenant })
  $roleDef = $null
  foreach ($rn in @('A365 MCP Gateway Policy Operator', 'A365 Gateway Policy Operator')) {
    $r = Invoke-Arm -Path "/subscriptions/$($cfg.subscriptionId)/providers/Microsoft.Authorization/roleDefinitions" -Api '2022-04-01' -Query @{ '$filter' = "roleName eq '$rn'" }
    if (@($r.value).Count -gt 0) { $roleDef = @($r.value)[0]; break }
  }
  $a365.docRoleName   = 'A365 MCP Gateway Policy Operator'
  $a365.docRoleExists = [bool](@((Invoke-Arm -Path "/subscriptions/$($cfg.subscriptionId)/providers/Microsoft.Authorization/roleDefinitions" -Api '2022-04-01' -Query @{ '$filter' = "roleName eq 'A365 MCP Gateway Policy Operator'" }).value).Count)

  if ($spHits.Count -ne 1) {
    Write-Warn2 "Agent 365 service principal not found (or ambiguous: $($spHits.Count)) - skipping, nothing created"
    $a365.status = 'BLOCKED'; $a365.reason = "Agent 365 first-party service principal count = $($spHits.Count)"
  } elseif (-not $roleDef) {
    Write-Warn2 'Neither A365 role definition exists - skipping'
    $a365.status = 'BLOCKED'; $a365.reason = 'role definition not found'
  } else {
    $sp = $spHits[0]
    $roleGuid = $roleDef.name
    $a365.principal = [ordered]@{ objectId = $sp.id; appId = $sp.appId; displayName = $sp.displayName; identifierUris = @($sp.servicePrincipalNames) }
    $a365.role = [ordered]@{ name = $roleDef.properties.roleName; id = $roleGuid; type = $roleDef.properties.type; actions = @($roleDef.properties.permissions[0].actions) }
    $listQ = @{ '$filter' = "principalId eq '$($sp.id)'" }
    $found = @((Invoke-Arm -Path "$apimScope/providers/Microsoft.Authorization/roleAssignments" -Api '2022-04-01' -Query $listQ).value |
               Where-Object { $_.properties.scope -ieq $apimScope -and $_.properties.roleDefinitionId -like "*$roleGuid" })
    $assignName = New-DetGuid "a365-gateway-policy-operator@$apimScope"

    if ($Remove) {
      foreach ($f in $found) {
        Invoke-Arm -Method DELETE -Path "$apimScope/providers/Microsoft.Authorization/roleAssignments/$($f.name)" -Api '2022-04-01' | Out-Null
        Write-Ok "removed role assignment $($f.name)"
      }
      if (-not $found) { Write-Ok 'no A365 role assignment at the APIM scope (nothing to remove)' }
      $a365.status = 'REMOVED'
    } else {
      if ($found) {
        Write-Ok "role assignment already present: $($found[0].name)"
        $assignId = $found[0].name; $created = $false
      } else {
        $body = @{ properties = [ordered]@{
          roleDefinitionId = "/subscriptions/$($cfg.subscriptionId)/providers/Microsoft.Authorization/roleDefinitions/$roleGuid"
          principalId = $sp.id; principalType = 'ServicePrincipal'
          description = 'ABW demo - Agent 365 gateway governance (Learn: azure/api-management/agent-365)' } }
        Invoke-Retry -What 'role assignment' -Script { Invoke-Arm -Method PUT -Path "$apimScope/providers/Microsoft.Authorization/roleAssignments/$assignName" -Api '2022-04-01' -Body $body | Out-Null }
        Write-Ok "assigned '$($roleDef.properties.roleName)' to $($sp.displayName) at $($names.apim) -> $assignName"
        $assignId = $assignName; $created = $true
      }
      $verify = Invoke-Arm -Path "$apimScope/providers/Microsoft.Authorization/roleAssignments/$assignId" -Api '2022-04-01'
      $a365.status = 'CONFIGURED-NOT-YET-OBSERVED'
      $a365.assignment = [ordered]@{ name = $verify.name; id = $verify.id; scope = $verify.properties.scope; principalId = $verify.properties.principalId
                                     createdOn = $verify.properties.createdOn; createdThisRun = $created }
    }

    # is the tenant-level consent (the documented route) already in place? look for the role on the A365 principal at root scopes
    $rootHits = @()
    foreach ($sc in @("/providers/Microsoft.Management/managementGroups/$($cfg.tenantId)", '')) {
      try {
        $rootHits += @((Invoke-Arm -Path "$sc/providers/Microsoft.Authorization/roleAssignments" -Api '2022-04-01' -Query @{ '$filter' = "principalId eq '$($sp.id)'" }).value |
                       Where-Object { $_.properties.roleDefinitionId -like "*$roleGuid" -and $_.properties.scope -notlike '/subscriptions/*' })
      } catch { }
    }
    $a365.tenantLevelConsentObserved = ($rootHits.Count -gt 0)
  }
  $a365.humanStep = 'M365 admin center (admin.microsoft.com) > Agents > Settings > Gateways > enable "Azure API Management service and AI Gateway" (tenant admin, one-time consent)'
  $a365.inventoryView = 'admin.microsoft.com > Agents > Tools (publisher = AI Gateway); AI Gateway portal https://ai.gateway.azure.com'
  $a365.tierNote = 'APIM Standard v2: inventory + block/unblock server only; tool-level block, tool observability and threat protection need the AI Gateway tier (preview)'
  $a365.roleNote = 'The role includes service/apis/write and workspaces/toolServers/write (how Agent 365 applies block policy to the gateway). It is inert until a tenant admin enables the gateway setting above; the APIM activity log shows no Agent 365 caller since the grant. Withdraw with -Remove.'
  $out.agent365 = $a365
}

# =====================================================================================================================
# 3. Conditional Access - ONE report-only policy
# =====================================================================================================================
if (-not $SkipConditionalAccess) {
  Write-Step '3/3 Conditional Access - report-only policy'
  $ca = [ordered]@{ status = 'BLOCKED'; policyName = $caName }
  $existingAll = @(Get-GraphAll '/identity/conditionalAccess/policies')
  $mine = @($existingAll | Where-Object { $_.displayName -eq $caName })
  $others = @($existingAll | Where-Object { $_.displayName -ne $caName })
  $ca.otherPoliciesUntouched = @($others | ForEach-Object { [ordered]@{ id = $_.id; displayName = $_.displayName; state = $_.state } })

  if ($Remove) {
    foreach ($p in $mine) {
      if ($p.state -eq 'enabled') { Write-Warn2 "policy $($p.id) is ENABLED - refusing to delete automatically"; continue }
      Invoke-Graph -Method DELETE -Path "/identity/conditionalAccess/policies/$($p.id)" | Out-Null
      Write-Ok "deleted report-only policy $($p.id)"
    }
    if (-not $mine) { Write-Ok 'policy not present (nothing to remove)' }
    $ca.status = 'REMOVED'
  } elseif ($mine.Count -gt 0) {
    Write-Ok "policy already present: $($mine[0].id) state=$($mine[0].state)"
    $p = $mine[0]
    $ca.status = 'CONFIGURED-NOT-YET-OBSERVED'; $ca.createdThisRun = $false
    if ($p.state -ne 'enabledForReportingButNotEnforced') { Write-Warn2 "state is '$($p.state)' (not report-only) - left unchanged; fix it in the portal" }
  } else {
    $appIds  = @($ent.apis.PSObject.Properties | ForEach-Object { $_.Value.appId })
    $groupId = $ent.groups.'sg-abw-demo-all'
    $adminRoles = @(Get-GraphAll '/directoryRoleTemplates' | Where-Object { $_.displayName -like '*Administrator' } | ForEach-Object { $_.id })
    $bgGroups = @{}
    foreach ($t in @('break', 'glass', 'emergency')) {
      foreach ($g in @((Invoke-Graph -Path '/groups' -Query @{ '$search' = "`"displayName:$t`""; '$select' = 'id,displayName'; '$count' = 'true' }).value)) { $bgGroups[$g.id] = $g.displayName }
    }
    $users = [ordered]@{ includeGroups = @($groupId); excludeUsers = @($cfg.operatorOid); excludeRoles = $adminRoles }
    if ($bgGroups.Count -gt 0) { $users.excludeGroups = @($bgGroups.Keys) }
    $body = [ordered]@{
      displayName = $caName
      state = 'enabledForReportingButNotEnforced'
      conditions = [ordered]@{ clientAppTypes = @('all'); applications = [ordered]@{ includeApplications = $appIds }; users = $users }
      grantControls = [ordered]@{ operator = 'OR'; builtInControls = @('mfa') }
    }
    try {
      $p = Invoke-Graph -Method POST -Path '/identity/conditionalAccess/policies' -Body $body
      Write-Ok "created $($p.id) state=$($p.state)"
      $ca.status = 'CONFIGURED-NOT-YET-OBSERVED'; $ca.createdThisRun = $true
    } catch {
      $ca.status = 'BLOCKED'; $ca.error = "$($_.Exception.Message)"
      Write-Warn2 "create failed: $($ca.error)"
      $ca.portalClickPath = 'Entra admin center (entra.microsoft.com) > Protection > Conditional Access > Policies > New policy: Users = include group sg-abw-demo-all, exclude the operator user + all directory roles; Target resources = the 5 abw-mcp-* apps; Grant = Require multifactor authentication; Enable policy = Report-only > Create'
    }
    $ca.excludedBreakGlassGroups = @($bgGroups.GetEnumerator() | ForEach-Object { [ordered]@{ id = $_.Key; displayName = $_.Value } })
    $ca.excludedAdminRoleCount = $adminRoles.Count
  }
  if ($p -and -not $Remove) {
    $polId = $p.id
    # Graph CA is eventually consistent: a just-created policy can 404 for a few seconds
    $rb = Invoke-Retry -What 'policy read-back' -Attempts 6 -DelaySec 3 -Script { Invoke-Graph -Path "/identity/conditionalAccess/policies/$polId" }
    $ca.policy = [ordered]@{
      id = $rb.id; displayName = $rb.displayName; state = $rb.state; createdDateTime = $rb.createdDateTime
      includeGroups = @($rb.conditions.users.includeGroups); excludeUsers = @($rb.conditions.users.excludeUsers)
      excludeRoleCount = @($rb.conditions.users.excludeRoles).Count; excludeGroups = @($rb.conditions.users.excludeGroups)
      includeApplications = @($rb.conditions.applications.includeApplications)
      grant = @($rb.grantControls.builtInControls)
    }
    Write-Ok "read back: $($rb.id) state=$($rb.state)"
  }
  $out.conditionalAccess = $ca
}

# =====================================================================================================================
# Static block: read-only probe recipes (proven with the az CLI token) + one-off build observations.
# Lives in the script so a re-run does not drop it from the JSON.
# =====================================================================================================================
if (-not $Remove) {
  $gv1      = 'https://graph.microsoft.com/v1.0'
  $armHost  = 'https://management.azure.com'
  $agentOid = if ($out.Contains('entraAgentId')) { $out.entraAgentId.instanceIdentity.objectId } else { '{agentIdentityObjectId}' }
  $a365Oid  = if ($out.Contains('agent365') -and $out.agent365.Contains('principal')) { $out.agent365.principal.objectId } else { '{agent365SpObjectId}' }
  $polIdRec = if ($out.Contains('conditionalAccess') -and $out.conditionalAccess.Contains('policy')) { $out.conditionalAccess.policy.id } else { '{policyId}' }

  $out.probeRecipes = [ordered]@{
    note = 'All READ-ONLY and proven with the az CLI token. Python form (console\azure_probe.py): ap.graph("/path", beta=False, **params) - the path needs a LEADING slash; ap.arm(path, api, **params); ap.token(resource). Graph is eventually consistent: a read right after a write can be stale for ~10 s.'
    publishedAgentAndIdentity = [ordered]@{
      call      = 'GET ' + $projectBase + '/agents/' + $agentName + '?api-version=2025-11-15-preview   [token resource https://ai.azure.com; header Foundry-Features: AgentEndpoints=V1Preview]'
      jsonPaths = 'instance_identity.principal_id (= client_id = agent identity appId) | blueprint.client_id | blueprint_reference.blueprint_id | versions.latest.agent_guid | state | agent_endpoint.publish_approval_status | agent_endpoint.authorization_schemes[].type | agent_endpoint.protocols'
    }
    agentIdentityList = [ordered]@{
      call      = 'GET ' + $gv1 + '/servicePrincipals/microsoft.graph.agentIdentity?$select=id,appId,displayName,accountEnabled,createdDateTime,tags'
      python    = 'ap.graph("/servicePrincipals/microsoft.graph.agentIdentity", **{"$select": "id,appId,displayName,accountEnabled,createdDateTime,tags"})["value"]'
      jsonPaths = 'value[].{id,appId,displayName,accountEnabled,createdDateTime} | value[].tags[] contains "agentName:<agent>" (the row without it is the shared project identity) | ours = displayName starts with "' + $names.foundry + '-"'
      observed  = '15 agent identities in the tenant, 5 ours, all accountEnabled=true'
    }
    agentIdentityDetail = [ordered]@{
      sponsors  = 'GET ' + $gv1 + '/servicePrincipals/' + $agentOid + '/microsoft.graph.agentIdentity/sponsors   -> value[].{id,displayName,userPrincipalName}'
      owners    = 'GET ' + $gv1 + '/servicePrincipals/' + $agentOid + '/owners   -> value[].{id,displayName,@odata.type}  (operator + the project managed-identity SP)'
      enabled   = 'GET ' + $gv1 + '/servicePrincipals/' + $agentOid + '?$select=accountEnabled   -> accountEnabled'
    }
    blueprintList = [ordered]@{
      call      = 'GET ' + $gv1 + '/applications/microsoft.graph.agentIdentityBlueprint?$select=id,appId,displayName'
      jsonPaths = 'value[].{id,appId,displayName}; ours: appId = blueprint.client_id from the agent GET'
    }
    agent365ServicePrincipal = [ordered]@{
      call      = 'GET ' + $gv1 + '/servicePrincipals?$filter=displayName eq ''Agent 365''&$select=id,appId,displayName,appOwnerOrganizationId'
      jsonPaths = 'value[0].{id,appId}; appOwnerOrganizationId = ' + $msFirstPartyTenant + ' (Microsoft first party)'
    }
    agent365RoleOnApim = [ordered]@{
      call      = 'GET ' + $armHost + $apimScope + '/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01&$filter=principalId eq ''' + $a365Oid + ''''
      python    = 'ap.arm(APIM_SCOPE + "/providers/Microsoft.Authorization/roleAssignments", "2022-04-01", **{"$filter": "principalId eq ''<oid>''"})["value"]'
      jsonPaths = 'value[].name (assignment id) | value[].properties.roleDefinitionId (ends 849de3f8-3686-489c-bd02-732984d0c145 = A365 Gateway Policy Operator) | value[].properties.scope | value[].properties.createdOn'
      roleDefinition = 'GET ' + $armHost + '/subscriptions/' + $cfg.subscriptionId + '/providers/Microsoft.Authorization/roleDefinitions?api-version=2022-04-01&$filter=roleName eq ''A365 Gateway Policy Operator''   -> value[0].properties.permissions[0].actions'
    }
    conditionalAccessPolicyState = [ordered]@{
      call      = 'GET ' + $gv1 + '/identity/conditionalAccess/policies/' + $polIdRec
      jsonPaths = 'state (expect enabledForReportingButNotEnforced) | displayName | grantControls.builtInControls | conditions.applications.includeApplications | conditions.users.{includeGroups,excludeUsers,excludeRoles}'
      list      = 'GET ' + $gv1 + '/identity/conditionalAccess/policies?$select=id,displayName,state   -> value[]  (observed 7: the 6 pre-existing = enabled, ours = enabledForReportingButNotEnforced)'
      note      = 'A just-created policy can return 404 for ~1 min (eventual consistency).'
    }
    conditionalAccessEvidence = [ordered]@{
      call      = 'GET https://graph.microsoft.com/beta/auditLogs/signIns?$top=40&$filter=createdDateTime ge <UTC timestamp> and signInEventTypes/any(t: t eq ''nonInteractiveUser'')&$select=id,createdDateTime,userPrincipalName,appDisplayName,resourceDisplayName,appliedConditionalAccessPolicies'
      jsonPaths = 'value[].appliedConditionalAccessPolicies[] where id == the policy id -> result (reportOnlySuccess | reportOnlyFailure | reportOnlyNotApplied ...). Portal: Entra admin center > Entra ID > Monitoring & health > Sign-in logs > open an event > Report-only tab.'
      observed  = 'Reachable (HTTP 200, ~12 s) but 0 of 40 rows since 20:20Z reference the policy yet. ALWAYS time-bound the filter: unbounded or resourceId-filtered queries timed out at 40-60 s.'
    }
    agentRegistry = [ordered]@{
      status   = 'NOT AVAILABLE with the az CLI token'
      observed = 'GET beta/agentRegistry/agentInstances -> 404 | beta/agentRegistry/agentCards -> 400 (segment not found) | beta/agentRegistry/agentCollections -> 404 | v1.0 and beta /copilot/admin/catalog/packages -> 403 (needs CopilotPackages.Read.All; delegated AI Administrator / Global Administrator)'
    }
  }

  $out.buildObservations = [ordered]@{
    recordedAt = '2026-10-22 build session (static text, not re-derived by this script)'
    legacyAgentApplication = [ordered]@{
      decision = 'NOT created on purpose - nothing to roll back'
      why      = 'abw-wall-desk already owns a dedicated Entra agent identity + blueprint (new Foundry agent model). Learn labels Agent Applications legacy and says they are not registered in the Entra agent registry; creating one would only add a second identity/blueprint.'
      documentedShapeIfStillWanted = 'UNTESTED. ARM api-version 2026-09-15-preview. PUT .../providers/Microsoft.CognitiveServices/accounts/{acct}/projects/{proj}/applications/{app} body {"properties":{"displayName":"..","agents":[{"agentName":"abw-wall-desk"}]}}; PUT .../applications/{app}/agentdeployments/{dep} body {"properties":{"displayName":"..","deploymentType":"Managed","protocols":[{"protocol":"Responses","version":"1.0"}],"agents":[{"agentName":"abw-wall-desk","agentVersion":"2"}]}}; POST .../agentdeployments/{dep}/start.'
    }
    identityLeverTest = [ordered]@{
      toggle      = 'PATCH ' + $gv1 + '/servicePrincipals/' + $agentOid + '  body {"accountEnabled": false} / {"accountEnabled": true}  (works with the az CLI token)'
      observed    = 'Identity disabled ~20:30:30Z-20:31:46Z: agent_run.py abw-wall-desk still returned the correct answer (exit 0, wall/list_my_wall_crossings ok:true) but took 64 s vs 6-8 s before and after (n=1). APIM gateway logs show NO MCP traffic from the Foundry runtime for the first ~56 s of that run (first request 20:31:28Z, backend times <150 ms), so the delay was inside Foundry before tool discovery; cause unconfirmed.'
      conclusion  = 'Not a kill switch for the demo path: tool calls reach APIM with the signed-in user (OBO) token, not the agent identity. At most a soft lever (blocks new agent-identity token issuance; tokens already issued stay valid until they expire). The effective revoke levers remain the APIM named value abw-deny-oids (untouched) and removing the user from the sg-abw-* groups.'
      restore     = 'PATCH accountEnabled=true, then re-read after ~10 s (the first read-after-write still showed false - Graph read lag). Verified true at 20:31:58Z; P00 5/5 and a post-restore agent_run (exit 0, 7.6 s) followed. Nothing left disabled.'
    }
    proofRuns = [ordered]@{
      p00BeforeChanges = '5/5 at 20:20:45Z (demo\evidence\prove-20261022-202045.json)'
      p00AfterChanges  = '5/5 at 20:32:09Z (demo\evidence\prove-20261022-203209.json)'
      agentRun         = 'three runs of agent_run.py --agent abw-wall-desk --approve yes "List my wall crossings.": baseline 6.2 s, identity disabled 64.1 s, post-restore 7.6 s; all exit 0, call wall/list_my_wall_crossings ok:true guardrail:false, answer = Project Falcon'
    }
    notVerified = @(
      'What Agent 365 / the Entra agent registry lists: no read API reachable with the az token (404/400/403).',
      'Whether the RBAC pre-grant + the admin-center consent makes the APIM MCP servers appear in M365 admin center > Agents > Tools (consent is a human step; tenantLevelConsentObserved=false).',
      'Per-tool blocking on APIM Standard v2 (Learn: needs the AI Gateway preview tier).',
      'That the Conditional Access policy is evaluated: no sign-in-log row references it yet (needs a persona in sg-abw-demo-all to sign in to one of the 5 MCP API apps; the operator is excluded).',
      'Why the identity-disabled run took 64 s (n=1).'
    )
  }
}

Save-Json $outPath $out
Write-Step "Wrote $outPath"
