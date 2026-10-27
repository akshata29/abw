// 06-governance.bicep - assigns and enforces the agent platform controls on the demo resource group, codifies the
// Foundry guardrail (RAI) policy, and turns on the audit trails the governance workbook / Sentinel rules read.
//
// Runs AFTER 06a-policy-definitions.bicep (subscription scope) and BEFORE 06b-observability.bicep.
// Everything here is scoped to rg-abw-demo-eus2-001.
//
//   1. Foundry guardrail policy "abw-agent-guardrails"   (content filters incl. the preview tool-response XPIA intervention)
//   2. Diagnostic settings "to-law"                      (Foundry account + project, agent-service BYO stores, the workspace itself)
//   3. Policy assignment of the initiative                (non-compliance messages tell the engineer WHY a deployment was refused)
//   4. Policy exemptions                                  (every one is explicit, time-boxed or justified, and visible in the cockpit)

targetScope = 'resourceGroup'

param names object

@description('Resource id of the subscription-scope initiative created by 06a-policy-definitions.bicep.')
param initiativeId string

@description('Deny = block non-compliant deployments; Audit = observe only (use while introducing the controls).')
@allowed([ 'Audit', 'Deny' ])
param hardControlEffect string = 'Deny'

@description('Effect for the preview Foundry data-plane tool / model policies.')
@allowed([ 'Audit', 'Deny' ])
param agentToolEffect string = 'Audit'

@description('Expiry of the legacy keyed-connection waiver (ISO-8601). scripts\\deploy.ps1 passes 90 days from the run; this default applies only to a direct deployment.')
param legacyWaiverExpiry string = '2026-11-30T00:00:00Z'

@description('Name of the Foundry guardrail policy referenced by the guarded agents.')
param guardrailPolicyName string = 'abw-agent-guardrails'

// ------------------------------------------------------------------------------------------------ existing resources
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: names.law
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: names.foundry
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' existing = {
  parent: foundry
  name: names.project
}

resource asvcStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: names.asvcStorage
}

resource asvcBlob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: asvcStorage
  name: 'default'
}

resource asvcCosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: names.asvcCosmos
}

resource asvcSearch 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: names.asvcSearch
}

resource caePriv 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: names.caePriv
}

resource caePub 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: names.caePub
}

// ------------------------------------------------------------------------------------------------ 1. guardrails
// Four harm categories on prompt + completion, jailbreak and indirect-attack (XPIA) on the prompt, and the
// preview tool-response intervention (Indirect Attack, source PostToolCall) that screens what an MCP tool
// RETURNS before the model reads it. Preview and best effort: in the lab it stopped the run (content_filter) on
// only a minority of identical requests, so it is a detection layer. The deterministic control is the wall.
var harmCategories = [ 'Hate', 'Sexual', 'Violence', 'Selfharm' ]
var harmFilters = [for (category, i) in concat(harmCategories, harmCategories): {
  name: category
  severityThreshold: 'Medium'
  blocking: true
  enabled: true
  source: i < length(harmCategories) ? 'Prompt' : 'Completion'
}]

resource guardrails 'Microsoft.CognitiveServices/accounts/raiPolicies@2026-07-15-preview' = {
  parent: foundry
  name: guardrailPolicyName
  properties: {
    basePolicyName: 'Microsoft.DefaultV2'
    mode: 'Blocking'
    contentFilters: concat(harmFilters, [
      { name: 'Jailbreak', blocking: true, enabled: true, source: 'Prompt' }
      { name: 'Indirect Attack', blocking: true, enabled: true, source: 'Prompt' }
      { name: 'Indirect Attack', blocking: true, enabled: true, source: 'PostToolCall', action: 'BLOCKING' }
      { name: 'Protected Material Text', blocking: false, enabled: true, source: 'Completion' }
    ])
  }
}

// ------------------------------------------------------------------------------------------------ 2. audit trails
resource diagFoundry 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: foundry
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logs: [ { categoryGroup: 'allLogs', enabled: true } ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

resource diagProject 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: project
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logs: [ { categoryGroup: 'allLogs', enabled: true } ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

resource diagAsvcBlob 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: asvcBlob
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logs: [ { categoryGroup: 'allLogs', enabled: true } ]
  }
}

resource diagAsvcCosmos 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: asvcCosmos
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logAnalyticsDestinationType: 'Dedicated'
    logs: [ { categoryGroup: 'allLogs', enabled: true } ]
  }
}

resource diagAsvcSearch 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: asvcSearch
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logs: [ { categoryGroup: 'allLogs', enabled: true } ]
  }
}

// Who queries the governance data? (LAQueryLogs) - the SOC's own activity is auditable too.
resource diagWorkspace 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: law
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logs: [ { category: 'Audit', enabled: true } ]
  }
}

// ------------------------------------------------------------------------------------------------ 3. assignment
var gatewayUrl = 'https://${names.apim}.azure-api.net'
var approvedMcpEndpoints = [
  '${gatewayUrl}/research/*'
  '${gatewayUrl}/wall/*'
  '${gatewayUrl}/actions/*'
  '${gatewayUrl}/vendor/*'
  'https://ca-abw-mcp-private.${caePriv.properties.defaultDomain}/*'
]

var messages = {
  default: 'Blocked by the ABW agent-platform baseline (initiative abw-agent-platform-controls). See policy/README.md for the control catalogue and how to request an exemption.'
  keys: 'No shared secrets: use Entra ID (managed identity) or OAuth user delegation. Keys, SAS tokens, PATs and passwords are not allowed on this platform.'
  targets: 'This tool endpoint is not on the approved MCP list. Publish the server behind the enterprise gateway (APIM) or the private ingress, then add it to the approved list through a reviewed change.'
  publicAccess: 'Data planes in this environment are reachable over private endpoints only. Public network access must stay disabled.'
}

resource assignment 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'abw-agent-platform-controls'
  properties: {
    displayName: 'ABW: Agent platform controls'
    description: 'No keys, private by default, approved tools and models, guardrails on. Scope: ${resourceGroup().name} only.'
    policyDefinitionId: initiativeId
    enforcementMode: 'Default'
    parameters: {
      denyEffect: { value: hardControlEffect }
      auditEffect: { value: 'Audit' }
      toolsEffect: { value: agentToolEffect }
      approvedMcpEndpoints: { value: approvedMcpEndpoints }
      approvedToolTypes: { value: [] }
      allowedModelPublishers: { value: [ 'OpenAI' ] }
    }
    nonComplianceMessages: [
      { message: messages.default }
      { message: messages.keys, policyDefinitionReferenceId: 'foundry-no-keyed-connections' }
      { message: messages.keys, policyDefinitionReferenceId: 'storage-shared-key-disabled' }
      { message: messages.keys, policyDefinitionReferenceId: 'ai-local-auth-disabled' }
      { message: messages.keys, policyDefinitionReferenceId: 'cosmos-local-auth-disabled' }
      { message: messages.keys, policyDefinitionReferenceId: 'search-local-auth-disabled' }
      { message: messages.targets, policyDefinitionReferenceId: 'foundry-approved-mcp-targets' }
      { message: messages.targets, policyDefinitionReferenceId: 'foundry-approved-tools' }
      { message: messages.publicAccess, policyDefinitionReferenceId: 'storage-no-public' }
      { message: messages.publicAccess, policyDefinitionReferenceId: 'cosmos-no-public' }
      { message: messages.publicAccess, policyDefinitionReferenceId: 'search-no-public' }
    ]
  }
}

// ------------------------------------------------------------------------------------------------ 4. exemptions
// Every exemption is a recorded, reviewable decision - the compliance view shows them as "Exempt", not as green.
resource legacyConnAccount 'Microsoft.CognitiveServices/accounts/connections@2025-04-01-preview' existing = {
  parent: foundry
  name: 'mcp-legacy-key'
}

resource legacyConnProject 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' existing = {
  parent: project
  name: 'mcp-legacy-key'
}

resource appiConnAccount 'Microsoft.CognitiveServices/accounts/connections@2025-04-01-preview' existing = {
  parent: foundry
  name: '${names.foundry}-appinsights'
}

resource appiConnProject 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' existing = {
  parent: project
  name: '${names.foundry}-appinsights'
}

var legacyReason = 'Deliberate "before" baseline for the Agents Behind the Wall demo: a keyed, ungoverned MCP connection that shows what the controls prevent. Time-boxed waiver; delete the connection (scripts\\teardown.ps1) or let it expire.'

resource exLegacyAccount 'Microsoft.Authorization/policyExemptions@2022-07-01-preview' = {
  scope: legacyConnAccount
  name: 'abw-ex-legacy-key-account'
  properties: {
    policyAssignmentId: assignment.id
    policyDefinitionReferenceIds: [ 'foundry-no-keyed-connections', 'foundry-approved-mcp-targets' ]
    exemptionCategory: 'Waiver'
    displayName: 'ABW legacy POC connection (keyed, ungoverned) - time-boxed waiver'
    description: legacyReason
    expiresOn: legacyWaiverExpiry
  }
}

resource exLegacyProject 'Microsoft.Authorization/policyExemptions@2022-07-01-preview' = {
  scope: legacyConnProject
  name: 'abw-ex-legacy-key-project'
  properties: {
    policyAssignmentId: assignment.id
    policyDefinitionReferenceIds: [ 'foundry-no-keyed-connections', 'foundry-approved-mcp-targets' ]
    exemptionCategory: 'Waiver'
    displayName: 'ABW legacy POC connection (keyed, ungoverned) - time-boxed waiver'
    description: legacyReason
    expiresOn: legacyWaiverExpiry
  }
}

var appiReason = 'The Foundry telemetry connection to Application Insights is created by the platform with an ingestion key (write-only, cannot read data). Mitigated: telemetry is ingestion-only and the workspace is queried with Entra ID. Revisit when the connection supports Entra authentication.'

resource exAppiAccount 'Microsoft.Authorization/policyExemptions@2022-07-01-preview' = {
  scope: appiConnAccount
  name: 'abw-ex-appinsights-ingestion-key-account'
  properties: {
    policyAssignmentId: assignment.id
    policyDefinitionReferenceIds: [ 'foundry-no-keyed-connections' ]
    exemptionCategory: 'Mitigated'
    displayName: 'ABW Foundry telemetry connection (ingestion key)'
    description: appiReason
  }
}

resource exAppiProject 'Microsoft.Authorization/policyExemptions@2022-07-01-preview' = {
  scope: appiConnProject
  name: 'abw-ex-appinsights-ingestion-key-project'
  properties: {
    policyAssignmentId: assignment.id
    policyDefinitionReferenceIds: [ 'foundry-no-keyed-connections' ]
    exemptionCategory: 'Mitigated'
    displayName: 'ABW Foundry telemetry connection (ingestion key)'
    description: appiReason
  }
}

resource exFoundryNetwork 'Microsoft.Authorization/policyExemptions@2022-07-01-preview' = {
  scope: foundry
  name: 'abw-ex-foundry-public-endpoint'
  properties: {
    policyAssignmentId: assignment.id
    policyDefinitionReferenceIds: [ 'ai-restrict-network' ]
    exemptionCategory: 'Mitigated'
    displayName: 'ABW Foundry account public endpoint (operator access)'
    description: 'The Foundry data-plane endpoint stays reachable so the operator laptop (rotating corporate egress) can run the agents. Mitigated: key access is disabled (Entra ID only), every agent tool call lands in private MCP servers behind APIM, and the agent runtime itself is injected into the VNet. Production: set publicNetworkAccess=Disabled and use the private endpoint.'
  }
}

resource exPublicEnv 'Microsoft.Authorization/policyExemptions@2022-07-01-preview' = {
  scope: caePub
  name: 'abw-ex-public-saas-simulator'
  properties: {
    policyAssignmentId: assignment.id
    policyDefinitionReferenceIds: [ 'aca-env-no-public' ]
    exemptionCategory: 'Waiver'
    displayName: 'ABW simulated external SaaS vendor'
    description: 'The public container-apps environment hosts the simulated third-party market-data vendor and the legacy POC server. A real vendor is outside the private network by definition; the APIM vendor gateway is the control (key injection, per-user claims).'
  }
}

// ------------------------------------------------------------------------------------------------ outputs
output assignmentId string = assignment.id
output assignmentName string = assignment.name
output guardrailPolicyId string = guardrails.id
output guardrailPolicyName string = guardrails.name
output approvedMcpEndpoints array = approvedMcpEndpoints
output exemptions array = [
  exLegacyAccount.name
  exLegacyProject.name
  exAppiAccount.name
  exAppiProject.name
  exFoundryNetwork.name
  exPublicEnv.name
]
