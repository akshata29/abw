// 03-platform.bicep — Agents Behind the Wall: shared platform.
//
// Identities (6 UAMIs), Key Vault, ACR, the demo data stores (Storage with a WORM audit container,
// Cosmos serverless, AI Search), both Container Apps environments, private endpoints, diagnostics
// and — importantly — the DATA-PLANE RBAC that makes the on-behalf-of story real:
//   * Storage / Cosmos / Search roles are granted to ENTRA GROUPS (personas), not to our servers.
//   * The servers' own UAMIs get only what a service legitimately needs (audit append, ACR pull,
//     restricted-list read). The `legacy` UAMI is deliberately over-privileged (the "typical POC").
// Everything is keyless: shared-key / local auth is disabled on Storage, Cosmos, Search, ACR.

targetScope = 'resourceGroup'

@description('Azure region.')
param location string = resourceGroup().location

@description('Region for Azure AI Search only. Empty = same as location. Search can live in a different region than the VNet (private endpoint stays in the VNet region); used when the home region has no Search capacity.')
param searchLocation string = ''

param tags object = {}
param workload string = 'abw'
param regionCode string = 'eus2'
param instance string = '001'
param tenantId string = tenant().tenantId

@description('Names object from scripts/common.ps1 Get-AbwNames (kv, acr, storage, cosmos, search, caePriv, caePub, law, appi).')
param names object

param vnetId string
param peSubnetId string
param mcpSubnetId string

@description('NAT gateway public IP (MCP servers / APIM egress) — allowed through the Key Vault firewall.')
param natPublicIp string
@description('Operator (signed-in admin) object id.')
param operatorOid string

@description('Entra group object ids: research, wallFalcon, traders, compliance, infosec, all.')
param groupIds object

var uamiKeys = [
  'research'
  'wall'
  'actions'
  'private'
  'legacy'
  'vendor'
]

// ---- built-in role definition ids ----
var roleStorageBlobDataReader = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
var roleStorageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var roleAcrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var roleAcrPush = '8311e382-0749-4cb8-b61a-304f252e45ec'
var roleKvSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'
var roleKvAdministrator = '00482a5a-887f-4fb3-b363-3b7fe8e74483'
var roleSearchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var roleSearchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var roleReader = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
var roleLogAnalyticsReader = '73c42c96-874c-492b-b04d-ab87d138a893'
var roleMonitoringReader = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'

func roleId(id string) string => subscriptionResourceId('Microsoft.Authorization/roleDefinitions', id)

// ---------------------------------------------------------------- observability (created by 02-foundry)
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: names.law
}

resource appi 'Microsoft.Insights/components@2020-02-02' existing = {
  name: names.appi
}

// ---------------------------------------------------------------- identities
resource uamis 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = [for k in uamiKeys: {
  name: 'id-${workload}-mcp-${k}-${regionCode}-${instance}'
  location: location
  tags: tags
}]

// ---------------------------------------------------------------- Key Vault
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: names.kv
  location: location
  tags: tags
  properties: {
    tenantId: tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      ipRules: [
        {
          value: natPublicIp
        }
      ]
    }
  }
}

// ---------------------------------------------------------------- Container Registry (Entra only)
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: names.acr
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

// ---------------------------------------------------------------- Storage (demo data + WORM audit)
resource st 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: names.storage
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    // PE-only. The operator laptop has no stable egress IP (corporate NAT pool), so there is no IP allow-list;
    // the data is loaded by the in-VNet seed job (04b-seed-job.bicep, deploy.ps1 -Stage seed).
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'None'
      ipRules: []
    }
  }
}

resource blobSvc 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: st
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource cResearch 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobSvc
  name: 'research-public'
  properties: {
    publicAccess: 'None'
  }
}

resource cFalcon 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobSvc
  name: 'wall-falcon'
  properties: {
    publicAccess: 'None'
  }
}

resource cOrion 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobSvc
  name: 'wall-orion'
  properties: {
    publicAccess: 'None'
  }
}

resource cWorm 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobSvc
  name: 'worm-audit'
  properties: {
    publicAccess: 'None'
  }
}

// Time-based retention, deliberately UNLOCKED (demo pattern, not a compliance attestation — DESIGN.md §10).
resource wormPolicy 'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies@2023-05-01' = {
  parent: cWorm
  name: 'default'
  properties: {
    immutabilityPeriodSinceCreationInDays: 1
    allowProtectedAppendWrites: true
  }
}

// ---------------------------------------------------------------- Cosmos DB (serverless, Entra only)
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: names.cosmos
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    disableLocalAuth: true
    disableKeyBasedMetadataWriteAccess: true
    minimalTlsVersion: 'Tls12'
    publicNetworkAccess: 'Disabled'
    isVirtualNetworkFilterEnabled: false
    ipRules: []
    networkAclBypass: 'None'
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: 'abw'
  properties: {
    resource: {
      id: 'abw'
    }
  }
}

resource cosmosRestricted 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: cosmosDb
  name: 'restricted'
  properties: {
    resource: {
      id: 'restricted'
      partitionKey: {
        paths: [
          '/ticker'
        ]
        kind: 'Hash'
      }
    }
  }
}

resource cosmosOrders 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  dependsOn: [
    cosmosRestricted
  ]
  parent: cosmosDb
  name: 'orders'
  properties: {
    resource: {
      id: 'orders'
      partitionKey: {
        paths: [
          '/user_oid'
        ]
        kind: 'Hash'
      }
    }
  }
}

resource cosmosPositions 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  dependsOn: [
    cosmosOrders
  ]
  parent: cosmosDb
  name: 'positions'
  properties: {
    resource: {
      id: 'positions'
      partitionKey: {
        paths: [
          '/desk'
        ]
        kind: 'Hash'
      }
    }
  }
}

// ---------------------------------------------------------------- AI Search (demo data, Entra only)
resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: names.search
  location: empty(searchLocation) ? location : searchLocation
  tags: tags
  sku: {
    name: 'basic'
  }
  properties: {
    hostingMode: 'Default'
    partitionCount: 1
    replicaCount: 1
    semanticSearch: 'disabled'
    disableLocalAuth: true
    publicNetworkAccess: 'disabled'
    networkRuleSet: {
      bypass: 'None'
      ipRules: []
    }
  }
}

// ---------------------------------------------------------------- private endpoints
module peBlob 'modules/pe.bicep' = {
  name: 'pe-blob'
  params: {
    name: 'pe-${names.storage}-blob'
    location: location
    subnetId: peSubnetId
    privateLinkResourceId: st.id
    groupId: 'blob'
    zoneName: 'privatelink.blob.${environment().suffixes.storage}'
    tags: tags
  }
}

module peCosmos 'modules/pe.bicep' = {
  name: 'pe-cosmos'
  params: {
    name: 'pe-${names.cosmos}-sql'
    location: location
    subnetId: peSubnetId
    privateLinkResourceId: cosmos.id
    groupId: 'Sql'
    zoneName: 'privatelink.documents.azure.com'
    tags: tags
  }
}

module peSearch 'modules/pe.bicep' = {
  name: 'pe-search'
  params: {
    name: 'pe-${names.search}-search'
    location: location
    subnetId: peSubnetId
    privateLinkResourceId: search.id
    groupId: 'searchService'
    zoneName: 'privatelink.search.windows.net'
    tags: tags
  }
}

module peKv 'modules/pe.bicep' = {
  name: 'pe-kv'
  params: {
    name: 'pe-${names.kv}-vault'
    location: location
    subnetId: peSubnetId
    privateLinkResourceId: kv.id
    groupId: 'vault'
    zoneName: 'privatelink.vaultcore.azure.net'
    tags: tags
  }
}

// ---------------------------------------------------------------- Container Apps environments
resource caePriv 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: names.caePriv
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
    vnetConfiguration: {
      internal: true
      infrastructureSubnetId: mcpSubnetId
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

resource caePub 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: names.caePub
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

module acaDns 'modules/aca-dns.bicep' = {
  name: 'aca-dns'
  params: {
    defaultDomain: caePriv.properties.defaultDomain
    staticIp: caePriv.properties.staticIp
    vnetId: vnetId
    tags: tags
  }
}

// ---------------------------------------------------------------- diagnostics -> Log Analytics
resource diagCaePriv 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: caePriv
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logs: [
      {
        category: 'ContainerAppConsoleLogs'
        enabled: true
      }
      {
        category: 'ContainerAppSystemLogs'
        enabled: true
      }
    ]
  }
}

resource diagCaePub 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: caePub
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logs: [
      {
        category: 'ContainerAppConsoleLogs'
        enabled: true
      }
      {
        category: 'ContainerAppSystemLogs'
        enabled: true
      }
    ]
  }
}

resource diagBlob 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: blobSvc
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
  }
}

resource diagCosmos 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: cosmos
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
  }
}

resource diagSearch 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: search
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
  }
}

resource diagKv 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: kv
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
  }
}

resource diagAcr 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: acr
  name: 'to-law'
  properties: {
    workspaceId: law.id
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
  }
}

// ================================================================ RBAC
// ---- servers: only what a service legitimately needs
resource raAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (k, i) in uamiKeys: {
  scope: acr
  name: guid(acr.id, uamis[i].id, roleAcrPull)
  properties: {
    roleDefinitionId: roleId(roleAcrPull)
    principalId: uamis[i].properties.principalId
    principalType: 'ServicePrincipal'
  }
}]

// audit append (worm-audit) for the five governed servers + legacy
resource raAuditAppend 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (k, i) in uamiKeys: if (k != 'vendor') {
  scope: cWorm
  name: guid(cWorm.id, uamis[i].id, roleStorageBlobDataContributor)
  properties: {
    roleDefinitionId: roleId(roleStorageBlobDataContributor)
    principalId: uamis[i].properties.principalId
    principalType: 'ServicePrincipal'
  }
}]

// vendor mock reads its key from Key Vault via ACA secret reference
resource raVendorKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, 'vendor', roleKvSecretsUser)
  properties: {
    roleDefinitionId: roleId(roleKvSecretsUser)
    principalId: uamis[5].properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---- the "typical POC" legacy identity: broad on purpose (this is the "before" in the demo)
resource raLegacyBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: st
  name: guid(st.id, 'legacy', roleStorageBlobDataReader)
  properties: {
    roleDefinitionId: roleId(roleStorageBlobDataReader)
    principalId: uamis[4].properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource raLegacySearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, 'legacy', roleSearchIndexDataReader)
  properties: {
    roleDefinitionId: roleId(roleSearchIndexDataReader)
    principalId: uamis[4].properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cosmosLegacyContrib 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  dependsOn: [
    cosmosPositions
  ]
  parent: cosmos
  name: guid(cosmos.id, 'legacy', 'contrib')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: uamis[4].properties.principalId
    scope: cosmos.id
  }
}

// ---- actions server: reads the restricted list as the SERVICE (compliance system-of-record)
resource cosmosActionsRestricted 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  dependsOn: [
    cosmosLegacyContrib
  ]
  parent: cosmos
  name: guid(cosmos.id, 'actions', 'restricted-reader')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001'
    principalId: uamis[2].properties.principalId
    scope: '${cosmos.id}/dbs/abw/colls/restricted'
  }
}

// ---- people (Entra GROUPS): evaluated by the data plane against the user's OBO token
resource raResearchBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cResearch
  name: guid(cResearch.id, groupIds.research, roleStorageBlobDataReader)
  properties: {
    roleDefinitionId: roleId(roleStorageBlobDataReader)
    principalId: groupIds.research
    principalType: 'Group'
  }
}

resource raFalconBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cFalcon
  name: guid(cFalcon.id, groupIds.wallFalcon, roleStorageBlobDataReader)
  properties: {
    roleDefinitionId: roleId(roleStorageBlobDataReader)
    principalId: groupIds.wallFalcon
    principalType: 'Group'
  }
}

// Orion: nobody — a crossed Falcon user asking for Orion is denied by Storage itself.

resource raSearchResearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, groupIds.research, roleSearchIndexDataReader)
  properties: {
    roleDefinitionId: roleId(roleSearchIndexDataReader)
    principalId: groupIds.research
    principalType: 'Group'
  }
}

resource cosmosTradersOrders 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  dependsOn: [
    cosmosActionsRestricted
  ]
  parent: cosmos
  name: guid(cosmos.id, groupIds.traders, 'orders-contrib')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: groupIds.traders
    scope: '${cosmos.id}/dbs/abw/colls/orders'
  }
}

resource cosmosComplianceOrders 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  dependsOn: [
    cosmosTradersOrders
  ]
  parent: cosmos
  name: guid(cosmos.id, groupIds.compliance, 'orders-reader')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001'
    principalId: groupIds.compliance
    scope: '${cosmos.id}/dbs/abw/colls/orders'
  }
}

resource cosmosTradersPositions 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  dependsOn: [
    cosmosComplianceOrders
  ]
  parent: cosmos
  name: guid(cosmos.id, groupIds.traders, 'positions-reader')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001'
    principalId: groupIds.traders
    scope: '${cosmos.id}/dbs/abw/colls/positions'
  }
}

resource cosmosCompliancePositions 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  dependsOn: [
    cosmosTradersPositions
  ]
  parent: cosmos
  name: guid(cosmos.id, groupIds.compliance, 'positions-reader')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001'
    principalId: groupIds.compliance
    scope: '${cosmos.id}/dbs/abw/colls/positions'
  }
}

// ---- infosec sees the platform (read-only) and the logs
resource raInfosecReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: resourceGroup()
  name: guid(resourceGroup().id, groupIds.infosec, roleReader)
  properties: {
    roleDefinitionId: roleId(roleReader)
    principalId: groupIds.infosec
    principalType: 'Group'
  }
}

resource raInfosecLaReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: law
  name: guid(law.id, groupIds.infosec, roleLogAnalyticsReader)
  properties: {
    roleDefinitionId: roleId(roleLogAnalyticsReader)
    principalId: groupIds.infosec
    principalType: 'Group'
  }
}

resource raInfosecMonitor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: resourceGroup()
  name: guid(resourceGroup().id, groupIds.infosec, roleMonitoringReader)
  properties: {
    roleDefinitionId: roleId(roleMonitoringReader)
    principalId: groupIds.infosec
    principalType: 'Group'
  }
}

// ---- operator: CONTROL PLANE ONLY. Subscription Owner is not a data-plane role: the operator has no blob, index or
// ---- document access (data planes are private-endpoint-only and RBAC'd to the wall groups + MCP identities). Seeding runs
// ---- in-VNet as id-abw-seed-eus2-001 (04b-seed-job.bicep).
resource raOpKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, operatorOid, roleKvAdministrator)
  properties: {
    roleDefinitionId: roleId(roleKvAdministrator)
    principalId: operatorOid
    principalType: 'User'
  }
}

resource raOpAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, operatorOid, roleAcrPush)
  properties: {
    roleDefinitionId: roleId(roleAcrPush)
    principalId: operatorOid
    principalType: 'User'
  }
}

resource raOpSearchSvc 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, operatorOid, roleSearchServiceContributor)
  properties: {
    roleDefinitionId: roleId(roleSearchServiceContributor)
    principalId: operatorOid
    principalType: 'User'
  }
}

// ================================================================ outputs -> infra/generated/platform.json
output uamis object = {
  research: { name: uamis[0].name, id: uamis[0].id, clientId: uamis[0].properties.clientId, principalId: uamis[0].properties.principalId }
  wall: { name: uamis[1].name, id: uamis[1].id, clientId: uamis[1].properties.clientId, principalId: uamis[1].properties.principalId }
  actions: { name: uamis[2].name, id: uamis[2].id, clientId: uamis[2].properties.clientId, principalId: uamis[2].properties.principalId }
  private: { name: uamis[3].name, id: uamis[3].id, clientId: uamis[3].properties.clientId, principalId: uamis[3].properties.principalId }
  legacy: { name: uamis[4].name, id: uamis[4].id, clientId: uamis[4].properties.clientId, principalId: uamis[4].properties.principalId }
  vendor: { name: uamis[5].name, id: uamis[5].id, clientId: uamis[5].properties.clientId, principalId: uamis[5].properties.principalId }
}
output acr object = {
  name: acr.name
  id: acr.id
  loginServer: acr.properties.loginServer
}
output kv object = {
  name: kv.name
  id: kv.id
  uri: kv.properties.vaultUri
}
output storage object = {
  name: st.name
  id: st.id
  blobEndpoint: st.properties.primaryEndpoints.blob
}
output cosmos object = {
  name: cosmos.name
  id: cosmos.id
  endpoint: cosmos.properties.documentEndpoint
}
output search object = {
  name: search.name
  id: search.id
  endpoint: 'https://${search.name}.search.windows.net'
}
output caePriv object = {
  name: caePriv.name
  id: caePriv.id
  defaultDomain: caePriv.properties.defaultDomain
  staticIp: caePriv.properties.staticIp
}
output caePub object = {
  name: caePub.name
  id: caePub.id
  defaultDomain: caePub.properties.defaultDomain
}
output observability object = {
  lawId: law.id
  lawName: law.name
  lawCustomerId: law.properties.customerId
  appiId: appi.id
  appiName: appi.name
  appiConnectionString: appi.properties.ConnectionString
}
