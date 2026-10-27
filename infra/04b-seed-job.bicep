// 04b-seed-job.bicep — in-VNet seeding of the synthetic data (blobs, AI Search index, Cosmos documents).
//
// Why a job instead of the operator laptop: Storage, Cosmos DB and AI Search are PRIVATE-ENDPOINT-ONLY
// (publicNetworkAccess = Disabled). A Container Apps Job in the internal environment reaches them over the
// private endpoints with a dedicated, scoped user-assigned identity - no firewall holes, no keys, no operator IP.
//
// The seed identity can WRITE the synthetic corpus. It is intentionally separate from the six MCP identities
// (which are read-only / per-user via OBO) and is removed by scripts\teardown.ps1.

targetScope = 'resourceGroup'

param location string = resourceGroup().location
param tags object = {}
param workload string = 'abw'
param regionCode string = 'eus2'
param instance string = '001'

@description('Outputs of 03-platform (acr, storage, cosmos, search, caePriv).')
param platform object

param imageTag string

var roleStorageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var roleAcrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var roleSearchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var roleSearchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
func roleId(id string) string => subscriptionResourceId('Microsoft.Authorization/roleDefinitions', id)

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: platform.acr.name
}

resource st 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: platform.storage.name
}

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: platform.search.name
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: platform.cosmos.name
}

resource seedId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${workload}-seed-${regionCode}-${instance}'
  location: location
  tags: tags
}

resource raAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, seedId.id, roleAcrPull)
  properties: {
    roleDefinitionId: roleId(roleAcrPull)
    principalId: seedId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource raBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: st
  name: guid(st.id, seedId.id, roleStorageBlobDataContributor)
  properties: {
    roleDefinitionId: roleId(roleStorageBlobDataContributor)
    principalId: seedId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource raSearchSvc 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, seedId.id, roleSearchServiceContributor)
  properties: {
    roleDefinitionId: roleId(roleSearchServiceContributor)
    principalId: seedId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource raSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, seedId.id, roleSearchIndexDataContributor)
  properties: {
    roleDefinitionId: roleId(roleSearchIndexDataContributor)
    principalId: seedId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cosmosSeed 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, seedId.id, 'seed-contrib')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: seedId.properties.principalId
    scope: cosmos.id
  }
}

resource seedJob 'Microsoft.App/jobs@2025-01-01' = {
  name: 'caj-${workload}-seed-${regionCode}-${instance}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${seedId.id}': {}
    }
  }
  dependsOn: [
    raAcr
    raBlob
    raSearchSvc
    raSearchData
    cosmosSeed
  ]
  properties: {
    environmentId: platform.caePriv.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 900
      replicaRetryLimit: 1
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: platform.acr.loginServer
          identity: seedId.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'seed'
          image: '${platform.acr.loginServer}/abw-seed:${imageTag}'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'AZURE_CLIENT_ID', value: seedId.properties.clientId }
            { name: 'STORAGE_ACCOUNT', value: platform.storage.name }
            { name: 'COSMOS_ENDPOINT', value: platform.cosmos.endpoint }
            { name: 'SEARCH_ENDPOINT', value: platform.search.endpoint }
          ]
        }
      ]
    }
  }
}

output seedJob object = {
  name: seedJob.name
  id: seedJob.id
  uamiName: seedId.name
  uamiPrincipalId: seedId.properties.principalId
}
