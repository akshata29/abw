// 05-apim-apis.bicep — MCP APIs, backends, policies, discovery metadata, vendor-key named value, legacy subscription.
// Runs AFTER 04-apps (needs the container app FQDNs) and AFTER 05-apim (the service, named values, Key Vault role).
//
//   /research  /wall  /actions  /vendor   -> Entra-protected MCP APIs (validate-jwt + claim authorisation + kill switch + metrics)
//   /legacy                               -> shared subscription key ("typical POC" baseline)
//   /.well-known/oauth-protected-resource/<server>/mcp   -> RFC 9728 discovery documents (anonymous)

targetScope = 'resourceGroup'

param names object

@description('Outputs of 04-apps (apps.<key>.fqdn).')
param apps object

@description('Entra API app ids: research, wall, actions, vendorgw.')
param apiAppIds object

@description('Versionless Key Vault secret identifier of the vendor API key (APIM injects it; clients never see it).')
param vendorKeySecretUri string

@description('Validate the TLS chain of the internal Container Apps ingress certificate (default domain cert). Flip to true after verifying trust.')
param validateInternalTls bool = false

resource apim 'Microsoft.ApiManagement/service@2025-09-01-preview' existing = {
  name: names.apim
}

var servers = [
  {
    key: 'research'
    title: 'Research MCP'
    description: 'Public-side research notes and market commentary (Blob + AI Search, on-behalf-of).'
    audience: apiAppIds.research
    roles: [ 'Research.Read' ]
    fqdn: apps.research.fqdn
    validateTls: validateInternalTls
    vendor: false
    listOpen: true
  }
  {
    key: 'wall'
    title: 'Wall MCP'
    description: 'Restricted deal-room documents (MNPI) behind information barriers (Blob + Cosmos + AI Search, on-behalf-of).'
    audience: apiAppIds.wall
    roles: [ 'Wall.Falcon', 'Wall.Orion' ]
    fqdn: apps.wall.fqdn
    validateTls: validateInternalTls
    vendor: false
    listOpen: true
  }
  {
    key: 'actions'
    title: 'Trading Actions MCP'
    description: 'Positions, order draft and order placement (Cosmos, on-behalf-of); order placement requires approval and Trade.Execute.'
    audience: apiAppIds.actions
    roles: [ 'Trade.Read', 'Trade.Execute' ]
    fqdn: apps.actions.fqdn
    validateTls: validateInternalTls
    vendor: false
    listOpen: true
  }
  {
    key: 'vendor'
    title: 'Market Data Vendor MCP (external)'
    description: 'Third-party market data MCP. The user is authenticated at the gateway; the vendor key is injected from Key Vault and never reaches the agent.'
    audience: apiAppIds.vendorgw
    roles: [ 'MarketData.Read' ]
    fqdn: apps.vendor.fqdn
    validateTls: true
    vendor: true
    listOpen: false
  }
]

var vendorSection = '''<set-header name="Authorization" exists-action="delete" />
    <set-header name="x-vendor-key" exists-action="override">
      <value>{{abw-vendor-key}}</value>
    </set-header>'''

// ---------------------------------------------------------------- vendor key (Key Vault backed named value)
resource nvVendorKey 'Microsoft.ApiManagement/service/namedValues@2024-06-01-preview' = {
  parent: apim
  name: 'abw-vendor-key'
  properties: {
    displayName: 'abw-vendor-key'
    secret: true
    keyVault: {
      secretIdentifier: vendorKeySecretUri
    }
  }
}

// ---------------------------------------------------------------- backends
resource backends 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = [for s in servers: {
  parent: apim
  name: 'be-mcp-${s.key}'
  properties: {
    url: 'https://${s.fqdn}'
    protocol: 'http'
    description: 'Container App for the ${s.key} MCP server'
    tls: {
      validateCertificateChain: s.validateTls
      validateCertificateName: s.validateTls
    }
  }
}]

resource beLegacy 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = {
  parent: apim
  name: 'be-mcp-legacy'
  properties: {
    url: 'https://${apps.legacy.fqdn}'
    protocol: 'http'
    description: 'Container App for the legacy POC MCP server'
    tls: {
      validateCertificateChain: validateInternalTls
      validateCertificateName: validateInternalTls
    }
  }
}

// ---------------------------------------------------------------- MCP APIs (Entra protected)
resource mcpApis 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = [for (s, i) in servers: {
  parent: apim
  name: 'abw-mcp-${s.key}'
  properties: {
    displayName: s.title
    description: s.description
    type: 'mcp'
    subscriptionRequired: false
    backendId: backends[i].name
    path: s.key
    protocols: [ 'https' ]
    mcpProperties: {
      endpoints: {
        mcp: {
          uriTemplate: '/mcp'
        }
      }
    }
    authenticationSettings: {
      oAuth2AuthenticationSettings: []
      openidAuthenticationSettings: []
    }
    isCurrent: true
  }
}]

resource mcpPolicies 'Microsoft.ApiManagement/service/apis/policies@2025-09-01-preview' = [for (s, i) in servers: {
  parent: mcpApis[i]
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: replace(replace(replace(replace(replace(replace(replace(loadTextContent('apim/policies/mcp-jwt.policy.xml'),
      '__SERVER__', s.key),
      '__PATH__', s.key),
      '__AUDIENCE__', s.audience),
      '__ROLES_CS__', join(map(s.roles, r => '"${r}"'), ', ')),
      '__LIST_OPEN__', s.listOpen ? 'true' : 'false'),
      '__VENDOR_SECTION__', s.vendor ? vendorSection : ''),
      '__TITLE__', s.title)
  }
  dependsOn: [
    nvVendorKey
  ]
}]

// ---------------------------------------------------------------- legacy POC MCP (subscription key only)
resource legacyApi 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = {
  parent: apim
  name: 'abw-mcp-legacy'
  properties: {
    displayName: 'Legacy POC MCP (shared key)'
    description: 'The typical proof-of-concept: one shared key, one broad service identity, no user context. The "before" picture.'
    type: 'mcp'
    subscriptionRequired: true
    subscriptionKeyParameterNames: {
      header: 'Ocp-Apim-Subscription-Key'
      query: 'subscription-key'
    }
    backendId: beLegacy.name
    path: 'legacy'
    protocols: [ 'https' ]
    mcpProperties: {
      endpoints: {
        mcp: {
          uriTemplate: '/mcp'
        }
      }
    }
    isCurrent: true
  }
}

resource legacyPolicy 'Microsoft.ApiManagement/service/apis/policies@2025-09-01-preview' = {
  parent: legacyApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('apim/policies/mcp-legacy.policy.xml')
  }
}

resource legacySub 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' = {
  parent: apim
  name: 'sub-abw-legacy-poc'
  properties: {
    displayName: 'ABW legacy POC (shared key)'
    scope: legacyApi.id
    state: 'active'
    allowTracing: false
  }
}

// ---------------------------------------------------------------- RFC 9728 discovery (anonymous)
resource prmApi 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = {
  parent: apim
  name: 'abw-mcp-prm-discovery'
  properties: {
    displayName: 'MCP protected resource metadata (RFC 9728)'
    description: 'Tells an MCP client which authorization server and scope protect each MCP server.'
    subscriptionRequired: false
    path: '.well-known/oauth-protected-resource'
    protocols: [ 'https' ]
  }
}

resource prmOps 'Microsoft.ApiManagement/service/apis/operations@2025-09-01-preview' = [for s in servers: {
  parent: prmApi
  name: 'prm-${s.key}'
  properties: {
    displayName: 'Protected resource metadata - ${s.key}'
    method: 'GET'
    urlTemplate: '/${s.key}/mcp'
  }
}]

resource prmPolicies 'Microsoft.ApiManagement/service/apis/operations/policies@2025-09-01-preview' = [for (s, i) in servers: {
  parent: prmOps[i]
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: replace(replace(replace(replace(loadTextContent('apim/policies/prm.policy.xml'),
      '__SERVER__', s.key),
      '__PATH__', s.key),
      '__AUDIENCE__', s.audience),
      '__TITLE__', s.title)
  }
}]

output legacySubscriptionName string = legacySub.name
output legacyUrl string = '${apim.properties.gatewayUrl}/legacy/mcp'
output gatewayApis array = [for (s, i) in servers: {
  key: s.key
  apiName: mcpApis[i].name
  url: '${apim.properties.gatewayUrl}/${s.key}/mcp'
  prm: '${apim.properties.gatewayUrl}/.well-known/oauth-protected-resource/${s.key}/mcp'
}]
