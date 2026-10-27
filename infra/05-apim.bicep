// 05-apim.bicep — the MCP gateway tier (APIM Standard v2) + the tool registry (API Center).
//
//   * Standard v2: outbound VNet integration (snet-apim, NAT) -> reaches the internal Container Apps env;
//     inbound private endpoint (privatelink.azure-api.net) -> the Foundry agent subnet reaches the gateway privately.
//     Public gateway stays enabled so the presenter's laptop / prove.py can call it (honest edge: lock it for the "fully private" scene).
//   * Telemetry: App Insights logger + diagnostics (W3C correlation, no bodies), resource logs to Log Analytics.
//   * Named values: tenant, gateway url, azp allow-list, kill-switch deny list (updated at runtime by the demo).
//   * API Center: the governed catalog of MCP servers (populated by 05-apim-apis.bicep and the apiSource sync).
//
// APIs, backends and policies are in 05-apim-apis.bicep (needs the container apps to exist).

targetScope = 'resourceGroup'

param location string = resourceGroup().location
param tags object = {}
param tenantId string = tenant().tenantId

@description('Names object (scripts/common.ps1 Get-AbwNames).')
param names object

param apimSubnetId string
param peSubnetId string

@description('Log Analytics workspace resource id.')
param workspaceId string
@description('Application Insights resource id.')
param appiId string
@secure()
param appiConnectionString string

param publisherEmail string
param publisherName string = 'ABW Capital Markets Demo'

@description('Comma separated azp allow-list shared by all gateway policies (Foundry OAuth client, test client, dev Azure CLI).')
param allowedAzp string

@description('Region for API Center (not every region offers it).')
param apicLocation string = 'eastus2'

var roleKeyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'
var roleApimServiceReader = '71522526-b88f-4d52-b57f-d31fc3546d0d'

resource apim 'Microsoft.ApiManagement/service@2025-09-01-preview' = {
  name: names.apim
  location: location
  tags: tags
  sku: {
    name: 'StandardV2'
    capacity: 1
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    virtualNetworkType: 'External'
    virtualNetworkConfiguration: {
      subnetResourceId: apimSubnetId
    }
    publicNetworkAccess: 'Enabled'
  }
}

module apimPe 'modules/pe.bicep' = {
  name: 'pe-apim'
  params: {
    name: names.apimPe
    location: location
    subnetId: peSubnetId
    privateLinkResourceId: apim.id
    groupId: 'Gateway'
    zoneName: 'privatelink.azure-api.net'
    tags: tags
  }
}

// ---------------------------------------------------------------- telemetry
resource logger 'Microsoft.ApiManagement/service/loggers@2024-06-01-preview' = {
  parent: apim
  name: 'appi'
  properties: {
    loggerType: 'applicationInsights'
    resourceId: appiId
    credentials: {
      connectionString: appiConnectionString
    }
    isBuffered: true
  }
}

resource diagAppi 'Microsoft.ApiManagement/service/diagnostics@2024-06-01-preview' = {
  parent: apim
  name: 'applicationinsights'
  properties: {
    loggerId: logger.id
    alwaysLog: 'allErrors'
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
    verbosity: 'information'
    httpCorrelationProtocol: 'W3C'
    logClientIp: true
    metrics: true
    frontend: {
      request: {
        headers: [
          'x-ms-client-request-id'
        ]
        body: {
          bytes: 0
        }
      }
      response: {
        headers: []
        body: {
          bytes: 0
        }
      }
    }
    backend: {
      request: {
        headers: []
        body: {
          bytes: 0
        }
      }
      response: {
        headers: []
        body: {
          bytes: 0
        }
      }
    }
  }
}

resource diagAzMon 'Microsoft.ApiManagement/service/diagnostics@2024-06-01-preview' = {
  parent: apim
  name: 'azuremonitor'
  properties: {
    loggerId: '${apim.id}/loggers/azuremonitor'
    logClientIp: true
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
    verbosity: 'information'
    alwaysLog: 'allErrors'
  }
}

resource apimDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-law'
  scope: apim
  properties: {
    workspaceId: workspaceId
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
  dependsOn: [
    diagAzMon
  ]
}

// ---------------------------------------------------------------- named values (shared by every policy)
resource nvTenant 'Microsoft.ApiManagement/service/namedValues@2024-06-01-preview' = {
  parent: apim
  name: 'abw-tenant-id'
  properties: {
    displayName: 'abw-tenant-id'
    value: tenantId
    secret: false
  }
}

resource nvGateway 'Microsoft.ApiManagement/service/namedValues@2024-06-01-preview' = {
  parent: apim
  name: 'abw-gateway-url'
  properties: {
    displayName: 'abw-gateway-url'
    value: apim.properties.gatewayUrl
    secret: false
  }
}

resource nvAzp 'Microsoft.ApiManagement/service/namedValues@2024-06-01-preview' = {
  parent: apim
  name: 'abw-allowed-azp'
  properties: {
    displayName: 'abw-allowed-azp'
    value: allowedAzp
    secret: false
  }
}

// Kill switch: comma separated user object ids denied at the gateway immediately (updated at runtime by demo\prove.py / the SOC runbook).
resource nvDeny 'Microsoft.ApiManagement/service/namedValues@2024-06-01-preview' = {
  parent: apim
  name: 'abw-deny-oids'
  properties: {
    displayName: 'abw-deny-oids'
    value: 'none'
    secret: false
  }
}

// ---------------------------------------------------------------- Key Vault: APIM reads the vendor key (and nothing else) as itself
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: names.kv
}

resource raApimKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, apim.id, roleKeyVaultSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleKeyVaultSecretsUser)
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------- API Center (governed MCP catalog)
resource apic 'Microsoft.ApiCenter/services@2024-06-01-preview' = {
  name: names.apic
  location: apicLocation
  tags: tags
  sku: {
    name: 'Free'
  }
  identity: {
    type: 'SystemAssigned'
  }
}

resource apicWs 'Microsoft.ApiCenter/services/workspaces@2024-06-01-preview' = {
  parent: apic
  name: 'default'
  properties: {
    title: 'Default workspace'
    description: 'Governed catalog of MCP servers the agents are allowed to use.'
  }
}

resource apicEnv 'Microsoft.ApiCenter/services/workspaces/environments@2024-06-01-preview' = {
  parent: apicWs
  name: 'prod'
  properties: {
    title: 'Production (APIM gateway)'
    kind: 'production'
    description: 'Agents reach MCP servers only through the APIM gateway (or the private ACA ingress for the private server).'
  }
}

resource raApicApim 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: apim
  name: guid(apim.id, apic.id, roleApimServiceReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleApimServiceReader)
    principalId: apic.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource apicSource 'Microsoft.ApiCenter/services/workspaces/apiSources@2024-06-01-preview' = {
  parent: apicWs
  name: 'apim-gateway'
  properties: {
    azureApiManagementSource: {
      resourceId: apim.id
    }
    importSpecification: 'always'
    targetEnvironmentId: '/workspaces/default/environments/prod'
    targetLifecycleStage: 'production'
  }
  dependsOn: [
    apicEnv
    raApicApim
  ]
}

output apim object = {
  name: apim.name
  id: apim.id
  gatewayUrl: apim.properties.gatewayUrl
  principalId: apim.identity.principalId
  privateEndpointId: apimPe.outputs.id
}
output apic object = {
  name: apic.name
  id: apic.id
  principalId: apic.identity.principalId
}
