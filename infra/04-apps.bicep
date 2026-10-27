// 04-apps.bicep — the six MCP servers as Azure Container Apps (one image, selected by MCP_SERVER).
//
//   research / wall / actions / legacy -> internal environment, reached through API Management (VNet integration)
//   private                            -> internal environment, reached DIRECTLY by the Foundry agent subnet
//   vendor (mock third party)          -> PUBLIC environment (simulates an external SaaS MCP)
//
// Run scripts\build-images.ps1 first so the image exists in ACR.

targetScope = 'resourceGroup'

param location string = resourceGroup().location
param tags object = {}
param tenantId string = tenant().tenantId
param workload string = 'abw'

@description('Names object (scripts/common.ps1 Get-AbwNames).')
param names object

@description('Outputs of 03-platform (uamis, acr, storage, cosmos, search, caePriv, caePub, observability).')
param platform object

@description('Entra API app (client) ids: research, wall, actions, private.')
param apiAppIds object

@description('Comma separated client app ids allowed as the token azp (the Foundry OAuth client, the test client, and — for dev — Azure CLI).')
param allowedAzp string

param imageTag string
param apimBaseUrl string
param cosmosObo bool = true
param logLevel string = 'INFO'

@secure()
@description('Shared secret of the (mock) external vendor. The vendor keeps its own copy; APIM injects it from Key Vault.')
param vendorApiKey string

// The ONE legacy static secret in the estate. Created through ARM (management plane) because the Key Vault data plane
// is firewalled; only the gateway (KV-backed named value) and the vendor mock ever hold it - never a user or an agent.
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: platform.kv.name
}

resource vendorKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'vendor-api-key'
  properties: {
    value: vendorApiKey
    contentType: 'text/plain'
  }
}
var image = '${platform.acr.loginServer}/abw-mcp:${imageTag}'

var commonEnv = [
  { name: 'TENANT_ID', value: tenantId }
  { name: 'LOG_LEVEL', value: logLevel }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appi-conn' }
  { name: 'AUDIT_STORAGE_ACCOUNT', value: platform.storage.name }
  { name: 'AUDIT_CONTAINER', value: 'worm-audit' }
  { name: 'STORAGE_ACCOUNT', value: platform.storage.name }
  { name: 'COSMOS_ENDPOINT', value: platform.cosmos.endpoint }
  { name: 'COSMOS_DATABASE', value: 'abw' }
  { name: 'SEARCH_ENDPOINT', value: platform.search.endpoint }
  { name: 'SEARCH_INDEX', value: 'deals-idx' }
  { name: 'MCP_REQUIRED_SCOPE', value: 'Tools.Read' }
  { name: 'COSMOS_OBO', value: string(cosmosObo) }
]

var appiSecret = [
  {
    name: 'appi-conn'
    value: platform.observability.appiConnectionString
  }
]

var privateFqdn = 'https://ca-${workload}-mcp-private.${platform.caePriv.defaultDomain}'

func serverEnv(server string, appId string, allowedAzp string, uamiClientId string, publicBase string) array => [
  { name: 'MCP_SERVER', value: server }
  { name: 'MCP_APP_CLIENT_ID', value: appId }
  { name: 'MCP_ALLOWED_AZP', value: allowedAzp }
  { name: 'UAMI_CLIENT_ID', value: uamiClientId }
  { name: 'PUBLIC_BASE_URL', value: publicBase }
  { name: 'OTEL_SERVICE_NAME', value: 'ca-abw-mcp-${server}' }
]

module research 'modules/mcp-app.bicep' = {
  name: 'app-research'
  params: {
    name: 'ca-${workload}-mcp-research'
    location: location
    tags: tags
    environmentId: platform.caePriv.id
    uamiId: platform.uamis.research.id
    acrServer: platform.acr.loginServer
    image: image
    env: concat(commonEnv, serverEnv('research', apiAppIds.research, allowedAzp, platform.uamis.research.clientId, '${apimBaseUrl}/research'))
    secrets: appiSecret
  }
}

module wall 'modules/mcp-app.bicep' = {
  name: 'app-wall'
  params: {
    name: 'ca-${workload}-mcp-wall'
    location: location
    tags: tags
    environmentId: platform.caePriv.id
    uamiId: platform.uamis.wall.id
    acrServer: platform.acr.loginServer
    image: image
    env: concat(commonEnv, serverEnv('wall', apiAppIds.wall, allowedAzp, platform.uamis.wall.clientId, '${apimBaseUrl}/wall'))
    secrets: appiSecret
  }
}

module actions 'modules/mcp-app.bicep' = {
  name: 'app-actions'
  params: {
    name: 'ca-${workload}-mcp-actions'
    location: location
    tags: tags
    environmentId: platform.caePriv.id
    uamiId: platform.uamis.actions.id
    acrServer: platform.acr.loginServer
    image: image
    env: concat(commonEnv, serverEnv('actions', apiAppIds.actions, allowedAzp, platform.uamis.actions.clientId, '${apimBaseUrl}/actions'))
    secrets: appiSecret
  }
}

module privateMcp 'modules/mcp-app.bicep' = {
  name: 'app-private'
  params: {
    name: 'ca-${workload}-mcp-private'
    location: location
    tags: tags
    environmentId: platform.caePriv.id
    uamiId: platform.uamis.private.id
    acrServer: platform.acr.loginServer
    image: image
    env: concat(commonEnv, serverEnv('private', apiAppIds.private, allowedAzp, platform.uamis.private.clientId, privateFqdn))
    secrets: appiSecret
  }
}

module legacy 'modules/mcp-app.bicep' = {
  name: 'app-legacy'
  params: {
    name: 'ca-${workload}-mcp-legacy'
    location: location
    tags: tags
    environmentId: platform.caePriv.id
    uamiId: platform.uamis.legacy.id
    acrServer: platform.acr.loginServer
    image: image
    env: concat(commonEnv, [
      { name: 'MCP_SERVER', value: 'legacy' }
      { name: 'UAMI_CLIENT_ID', value: platform.uamis.legacy.clientId }
      { name: 'PUBLIC_BASE_URL', value: '${apimBaseUrl}/legacy' }
      { name: 'OTEL_SERVICE_NAME', value: 'ca-abw-mcp-legacy' }
    ])
    secrets: appiSecret
  }
}

module vendor 'modules/mcp-app.bicep' = {
  name: 'app-vendor'
  params: {
    name: 'ca-${workload}-mcp-vendor'
    location: location
    tags: tags
    environmentId: platform.caePub.id
    uamiId: platform.uamis.vendor.id
    acrServer: platform.acr.loginServer
    image: image
    env: concat(commonEnv, [
      { name: 'MCP_SERVER', value: 'vendor' }
      { name: 'UAMI_CLIENT_ID', value: platform.uamis.vendor.clientId }
      { name: 'OTEL_SERVICE_NAME', value: 'ca-abw-mcp-vendor' }
      { name: 'VENDOR_API_KEY', secretRef: 'vendor-api-key' }
    ])
    secrets: concat(appiSecret, [
      {
        name: 'vendor-api-key'
        value: vendorApiKey
      }
    ])
  }
}

output apps object = {
  research: { name: research.outputs.name, fqdn: research.outputs.fqdn, url: 'https://${research.outputs.fqdn}/mcp' }
  wall: { name: wall.outputs.name, fqdn: wall.outputs.fqdn, url: 'https://${wall.outputs.fqdn}/mcp' }
  actions: { name: actions.outputs.name, fqdn: actions.outputs.fqdn, url: 'https://${actions.outputs.fqdn}/mcp' }
  private: { name: privateMcp.outputs.name, fqdn: privateMcp.outputs.fqdn, url: 'https://${privateMcp.outputs.fqdn}/mcp' }
  legacy: { name: legacy.outputs.name, fqdn: legacy.outputs.fqdn, url: 'https://${legacy.outputs.fqdn}/mcp' }
  vendor: { name: vendor.outputs.name, fqdn: vendor.outputs.fqdn, url: 'https://${vendor.outputs.fqdn}/mcp' }
}

output vendorKeySecretUri string = vendorKeySecret.properties.secretUri
