// 06a-policy-definitions.bicep - the "agent platform controls" policy initiative (SUBSCRIPTION scope definitions only).
//
// Deploy with:  az deployment sub create -l eastus2 -f infra\06a-policy-definitions.bicep
// (scripts\deploy.ps1 -Stage governance does this first). It only DEFINES policies; 06-governance.bicep assigns the
// initiative to the demo resource group, so nothing outside rg-abw-demo-eus2-001 is ever evaluated or blocked.
//
// Control groups (each maps to a customer / infosec question):
//   ABW-01-NO-KEYS        "Can anyone leak a key?"           -> shared-key / local-auth switched off everywhere, no keyed Foundry connections
//   ABW-02-PRIVATE        "Can data leave the private path?" -> public network access off on every data plane
//   ABW-03-TOOLS-MODELS   "What can an agent reach?"         -> agents may only use approved MCP endpoints and approved models
//   ABW-04-GUARDRAILS     "Is the guardrail on?"             -> agents must carry the jailbreak + indirect-attack (XPIA) filters
//   ABW-05-HYGIENE        "Is the workload well-formed?"     -> HTTPS only, managed identity on the container apps
//
// Two of the built-ins are PREVIEW data-plane policies (Microsoft.CognitiveServices.Data mode): foundry-approved-tools
// and the agent prompt-filter policy. Two are CUSTOM (control-plane, ARM) and are the ones that visibly Deny:
//   abw-foundry-no-keyed-connections      a Foundry connection may not store a key / SAS / PAT / password
//   abw-foundry-approved-mcp-targets      a remote-tool (MCP) connection may only point at an approved gateway URL

targetScope = 'subscription'

var builtin = {
  aiLocalAuth: '71ef260a-8f18-47b7-abcb-62d0673d94dc'
  storageSharedKey: '8c6a50c6-9ffd-4ae7-986f-5fa6111f9a54'
  cosmosLocalAuth: '5450f5bd-9c72-4390-a9c4-a7aba4edfdd2'
  searchLocalAuth: '6300012e-e9a4-4649-b41f-a85f5c43be91'
  keyVaultRbac: '12d4fa5e-1f9f-4c21-97a9-b99b3c6611b5'
  acrAdmin: 'dc921057-6b28-4fbe-9b83-f7bec05db6c2'
  aiNetwork: '037eea7a-bd0a-46c5-9a66-03aea78705d3'
  cosmosPublic: '797b37f7-06b8-444c-b1ad-fc62867f335a'
  storagePublic: 'b2982f36-99f2-4db5-8eff-283140c09693'
  searchPublic: 'ee980b6d-0eca-4501-8d54-f6290fd512c3'
  acaEnvPublic: 'd074ddf8-01a5-4b5e-a2b8-964aed452c0a'
  approvedTools: 'e7352ad2-6c86-4a07-9573-47f67b557ba8'
  approvedModels: 'aafe3651-cb78-4f68-9f81-e7e41509110f'
  promptFilters: '9224c1cc-34fc-44f1-ad08-5c4b079c9ce6'
  acaIdentity: 'b874ab2d-72dd-47f1-8cb5-4a306478a4e7'
  acaHttps: '0e80e269-43a4-4ae9-b5bc-178126b8a5cb'
}

var keyedAuthTypes = [ 'ApiKey', 'CustomKeys', 'AccessKey', 'AccountKey', 'SAS', 'PAT', 'UsernamePassword', 'ServicePrincipal' ]

var effectMetadata = {
  displayName: 'Effect'
  description: 'Audit reports non-compliance; Deny blocks the request; Disabled switches the policy off.'
}

// ----------------------------------------------------------------------------------------------------------------
// Custom definition 1: no stored secrets in Foundry connections
// ----------------------------------------------------------------------------------------------------------------
resource noKeyedConnections 'Microsoft.Authorization/policyDefinitions@2023-04-01' = {
  name: 'abw-foundry-no-keyed-connections'
  properties: {
    displayName: 'ABW: Foundry connections must not store keys, SAS tokens, PATs or passwords'
    description: 'Blocks Foundry account / project connections whose authentication type stores a shared secret. Connections must use Entra ID (AAD / managed identity), OAuth 2.0 user delegation, or no credential.'
    policyType: 'Custom'
    mode: 'All'
    metadata: { category: 'Microsoft Foundry', version: '1.0.0', source: 'agents-behind-the-wall' }
    parameters: {
      effect: {
        type: 'String'
        allowedValues: [ 'Audit', 'Deny', 'Disabled' ]
        defaultValue: 'Deny'
        metadata: effectMetadata
      }
      keyedAuthTypes: {
        type: 'Array'
        defaultValue: keyedAuthTypes
        metadata: { displayName: 'Authentication types that store a secret', description: 'Foundry connection authType values treated as shared-secret authentication.' }
      }
    }
    policyRule: {
      if: {
        anyOf: [
          {
            allOf: [
              { field: 'type', equals: 'Microsoft.CognitiveServices/accounts/connections' }
              { field: 'Microsoft.CognitiveServices/accounts/connections/authType', in: '[parameters(\'keyedAuthTypes\')]' }
            ]
          }
          {
            allOf: [
              { field: 'type', equals: 'Microsoft.CognitiveServices/accounts/projects/connections' }
              { field: 'Microsoft.CognitiveServices/accounts/projects/connections/authType', in: '[parameters(\'keyedAuthTypes\')]' }
            ]
          }
        ]
      }
      then: { effect: '[parameters(\'effect\')]' }
    }
  }
}

// ----------------------------------------------------------------------------------------------------------------
// Custom definition 2: remote-tool (MCP) connections may only target approved endpoints
// ----------------------------------------------------------------------------------------------------------------
resource approvedMcpTargets 'Microsoft.Authorization/policyDefinitions@2023-04-01' = {
  name: 'abw-foundry-approved-mcp-targets'
  properties: {
    displayName: 'ABW: Foundry remote-tool (MCP) connections must target an approved endpoint'
    description: 'Blocks a Foundry remote-tool connection whose target URL does not match the allow-list (the enterprise MCP gateway and the private MCP server). Patterns accept one * wildcard and are matched case-insensitively.'
    policyType: 'Custom'
    mode: 'All'
    metadata: { category: 'Microsoft Foundry', version: '1.0.0', source: 'agents-behind-the-wall' }
    parameters: {
      effect: {
        type: 'String'
        allowedValues: [ 'Audit', 'Deny', 'Disabled' ]
        defaultValue: 'Deny'
        metadata: effectMetadata
      }
      approvedMcpEndpoints: {
        type: 'Array'
        metadata: { displayName: 'Approved MCP endpoint patterns', description: 'URL patterns a remote-tool connection target must match, for example https://apim.contoso.com/research/*' }
      }
      connectionCategories: {
        type: 'Array'
        defaultValue: [ 'RemoteTool' ]
        metadata: { displayName: 'Connection categories that reach a tool server', description: 'Foundry connection categories that are evaluated against the allow-list.' }
      }
    }
    policyRule: {
      if: {
        anyOf: [
          {
            allOf: [
              { field: 'type', equals: 'Microsoft.CognitiveServices/accounts/connections' }
              { field: 'Microsoft.CognitiveServices/accounts/connections/category', in: '[parameters(\'connectionCategories\')]' }
              {
                count: {
                  value: '[parameters(\'approvedMcpEndpoints\')]'
                  name: 'pattern'
                  where: {
                    value: '[field(\'Microsoft.CognitiveServices/accounts/connections/target\')]'
                    like: '[current(\'pattern\')]'
                  }
                }
                equals: 0
              }
            ]
          }
          {
            allOf: [
              { field: 'type', equals: 'Microsoft.CognitiveServices/accounts/projects/connections' }
              { field: 'Microsoft.CognitiveServices/accounts/projects/connections/category', in: '[parameters(\'connectionCategories\')]' }
              {
                count: {
                  value: '[parameters(\'approvedMcpEndpoints\')]'
                  name: 'pattern'
                  where: {
                    value: '[field(\'Microsoft.CognitiveServices/accounts/projects/connections/target\')]'
                    like: '[current(\'pattern\')]'
                  }
                }
                equals: 0
              }
            ]
          }
        ]
      }
      then: { effect: '[parameters(\'effect\')]' }
    }
  }
}

// ----------------------------------------------------------------------------------------------------------------
// The initiative
// ----------------------------------------------------------------------------------------------------------------
resource initiative 'Microsoft.Authorization/policySetDefinitions@2023-04-01' = {
  name: 'abw-agent-platform-controls'
  properties: {
    displayName: 'ABW: Agent platform controls (no keys, private by default, approved tools, guardrails)'
    description: 'The twelve-control baseline behind Agents Behind the Wall. Assigned to the demo resource group only.'
    policyType: 'Custom'
    metadata: { category: 'Microsoft Foundry', version: '1.0.0', source: 'agents-behind-the-wall' }
    parameters: {
      denyEffect: {
        type: 'String'
        allowedValues: [ 'Audit', 'Deny', 'Disabled' ]
        defaultValue: 'Deny'
        metadata: { displayName: 'Effect for hard controls (keys, public access, unapproved connections)', description: 'Deny for enforcement, Audit to observe first.' }
      }
      auditEffect: {
        type: 'String'
        allowedValues: [ 'Audit', 'Disabled' ]
        defaultValue: 'Audit'
        metadata: { displayName: 'Effect for report-only controls', description: 'Audit or Disabled (used by policies that cannot Deny).' }
      }
      toolsEffect: {
        type: 'String'
        allowedValues: [ 'Audit', 'Deny', 'Disabled' ]
        defaultValue: 'Audit'
        metadata: { displayName: 'Effect for agent tool and model controls (preview data-plane policies)', description: 'Audit or Deny.' }
      }
      approvedMcpEndpoints: {
        type: 'Array'
        metadata: { displayName: 'Approved MCP endpoint patterns', description: 'Used by the connection-target policy and the agent approved-tools policy. One * wildcard per pattern.' }
      }
      approvedToolTypes: {
        type: 'Array'
        defaultValue: []
        metadata: { displayName: 'Approved non-MCP tool types', description: 'Agent tool types allowed without an endpoint check (for example file_search).' }
      }
      allowedModelPublishers: {
        type: 'Array'
        defaultValue: [ 'OpenAI' ]
        metadata: { displayName: 'Allowed model publishers', description: 'Publishers whose models may be deployed to the Foundry account.' }
      }
      agentEntityKinds: {
        type: 'Array'
        defaultValue: [ 'prompt' ]
        metadata: { displayName: 'Agent kinds that must carry the guardrail filters', description: 'Entity kinds evaluated by the agent prompt-filter policy.' }
      }
    }
    policyDefinitionGroups: [
      { name: 'ABW-01-NO-KEYS', displayName: 'No shared keys anywhere', description: 'Local authentication / shared key access is disabled on every service; Foundry connections may not store secrets.' }
      { name: 'ABW-02-PRIVATE', displayName: 'Private by default', description: 'Data planes are reachable only over private endpoints.' }
      { name: 'ABW-03-TOOLS-MODELS', displayName: 'Approved tools and models only', description: 'Agents and connections may only reach approved MCP endpoints; only approved model publishers may be deployed.' }
      { name: 'ABW-04-GUARDRAILS', displayName: 'Agent guardrails on', description: 'Every agent carries the jailbreak and indirect-attack filters.' }
      { name: 'ABW-05-HYGIENE', displayName: 'Workload hygiene', description: 'HTTPS only and managed identity on the container apps.' }
    ]
    policyDefinitions: [
      // ---- ABW-01 no keys
      {
        policyDefinitionReferenceId: 'ai-local-auth-disabled'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.aiLocalAuth)
        parameters: { effect: { value: '[parameters(\'denyEffect\')]' } }
        groupNames: [ 'ABW-01-NO-KEYS' ]
      }
      {
        policyDefinitionReferenceId: 'storage-shared-key-disabled'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.storageSharedKey)
        parameters: { effect: { value: '[parameters(\'denyEffect\')]' } }
        groupNames: [ 'ABW-01-NO-KEYS' ]
      }
      {
        policyDefinitionReferenceId: 'cosmos-local-auth-disabled'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.cosmosLocalAuth)
        parameters: { effect: { value: '[parameters(\'denyEffect\')]' } }
        groupNames: [ 'ABW-01-NO-KEYS' ]
      }
      {
        policyDefinitionReferenceId: 'search-local-auth-disabled'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.searchLocalAuth)
        parameters: { effect: { value: '[parameters(\'denyEffect\')]' } }
        groupNames: [ 'ABW-01-NO-KEYS' ]
      }
      {
        policyDefinitionReferenceId: 'keyvault-rbac'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.keyVaultRbac)
        parameters: { effect: { value: '[parameters(\'denyEffect\')]' } }
        groupNames: [ 'ABW-01-NO-KEYS' ]
      }
      {
        policyDefinitionReferenceId: 'acr-admin-disabled'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.acrAdmin)
        parameters: { effect: { value: '[parameters(\'denyEffect\')]' } }
        groupNames: [ 'ABW-01-NO-KEYS' ]
      }
      {
        policyDefinitionReferenceId: 'foundry-no-keyed-connections'
        policyDefinitionId: noKeyedConnections.id
        parameters: { effect: { value: '[parameters(\'denyEffect\')]' } }
        groupNames: [ 'ABW-01-NO-KEYS' ]
      }
      // ---- ABW-02 private
      {
        policyDefinitionReferenceId: 'ai-restrict-network'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.aiNetwork)
        parameters: { effect: { value: '[parameters(\'auditEffect\')]' } }
        groupNames: [ 'ABW-02-PRIVATE' ]
      }
      {
        policyDefinitionReferenceId: 'cosmos-no-public'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.cosmosPublic)
        parameters: { effect: { value: '[parameters(\'denyEffect\')]' } }
        groupNames: [ 'ABW-02-PRIVATE' ]
      }
      {
        policyDefinitionReferenceId: 'storage-no-public'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.storagePublic)
        parameters: { effect: { value: '[parameters(\'denyEffect\')]' } }
        groupNames: [ 'ABW-02-PRIVATE' ]
      }
      {
        policyDefinitionReferenceId: 'search-no-public'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.searchPublic)
        parameters: { effect: { value: '[parameters(\'denyEffect\')]' } }
        groupNames: [ 'ABW-02-PRIVATE' ]
      }
      {
        policyDefinitionReferenceId: 'aca-env-no-public'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.acaEnvPublic)
        parameters: { effect: { value: '[parameters(\'auditEffect\')]' } }
        groupNames: [ 'ABW-02-PRIVATE' ]
      }
      // ---- ABW-03 tools and models
      {
        policyDefinitionReferenceId: 'foundry-approved-tools'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.approvedTools)
        definitionVersion: '1.*.*-preview'
        parameters: {
          effect: { value: '[parameters(\'toolsEffect\')]' }
          approvedToolTypes: { value: '[parameters(\'approvedToolTypes\')]' }
          approvedMcpEndpoints: { value: '[parameters(\'approvedMcpEndpoints\')]' }
        }
        groupNames: [ 'ABW-03-TOOLS-MODELS' ]
      }
      {
        policyDefinitionReferenceId: 'foundry-approved-mcp-targets'
        policyDefinitionId: approvedMcpTargets.id
        parameters: {
          effect: { value: '[parameters(\'denyEffect\')]' }
          approvedMcpEndpoints: { value: '[parameters(\'approvedMcpEndpoints\')]' }
        }
        groupNames: [ 'ABW-03-TOOLS-MODELS' ]
      }
      {
        policyDefinitionReferenceId: 'foundry-approved-models'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.approvedModels)
        parameters: {
          effect: { value: '[parameters(\'toolsEffect\')]' }
          allowedPublishers: { value: '[parameters(\'allowedModelPublishers\')]' }
        }
        groupNames: [ 'ABW-03-TOOLS-MODELS' ]
      }
      // ---- ABW-04 guardrails
      {
        policyDefinitionReferenceId: 'agent-guardrail-jailbreak'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.promptFilters)
        definitionVersion: '1.*.*-preview'
        parameters: {
          effect: { value: '[parameters(\'auditEffect\')]' }
          filterName: { value: 'Jailbreak' }
          entityKind: { value: '[parameters(\'agentEntityKinds\')]' }
        }
        groupNames: [ 'ABW-04-GUARDRAILS' ]
      }
      {
        policyDefinitionReferenceId: 'agent-guardrail-indirect-attack'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.promptFilters)
        definitionVersion: '1.*.*-preview'
        parameters: {
          effect: { value: '[parameters(\'auditEffect\')]' }
          filterName: { value: 'Indirect Attack' }
          entityKind: { value: '[parameters(\'agentEntityKinds\')]' }
        }
        groupNames: [ 'ABW-04-GUARDRAILS' ]
      }
      // ---- ABW-05 hygiene
      {
        policyDefinitionReferenceId: 'aca-managed-identity'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.acaIdentity)
        parameters: { effect: { value: '[parameters(\'auditEffect\')]' } }
        groupNames: [ 'ABW-05-HYGIENE' ]
      }
      {
        policyDefinitionReferenceId: 'aca-https-only'
        policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', builtin.acaHttps)
        parameters: { effect: { value: '[parameters(\'auditEffect\')]' } }
        groupNames: [ 'ABW-05-HYGIENE' ]
      }
    ]
  }
}

output initiativeId string = initiative.id
output initiativeName string = initiative.name
output customDefinitionIds array = [
  noKeyedConnections.id
  approvedMcpTargets.id
]
