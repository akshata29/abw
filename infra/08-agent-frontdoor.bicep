// 08-agent-frontdoor.bicep - the agent front door: user -> APIM -> Foundry agent (additive; nothing existing is changed).
//
//   /agents/*  -> Foundry project Responses endpoint, behind validate-jwt + kill switch + per-user rate limit +
//                 per-user token budget (llm-token-limit) + token metrics per user and agent (llm-emit-token-metric).
//
// The user's own token is forwarded unchanged (Foundry still authorises the person and OAuth identity passthrough still
// reaches every MCP server as that person). Remove it with:  az apim api delete ... --api-id abw-agent-frontdoor
// Runs AFTER 05-apim (service, logger, named values abw-tenant-id / abw-deny-oids).

targetScope = 'resourceGroup'

param names object

@description('Foundry project endpoint the front door forwards to: https://<account>.services.ai.azure.com/api/projects/<project>')
param foundryProjectEndpoint string

@description('Per-user token budget per hour enforced at the front door (llm-token-limit token-quota, Hourly). Change at runtime with the abw-agent-token-quota named value. 250,000 is about fifty demo agent runs per user per hour: high enough never to trip by accident, and the console lowers it live to show the refusal.')
param tokenQuotaPerHour int = 250000

@description('Per-user agent calls per minute (rate-limit-by-key).')
param callsPerMinute int = 60

resource apim 'Microsoft.ApiManagement/service@2025-09-01-preview' existing = {
  name: names.apim
}

resource nvQuota 'Microsoft.ApiManagement/service/namedValues@2024-06-01-preview' = {
  parent: apim
  name: 'abw-agent-token-quota'
  properties: {
    displayName: 'abw-agent-token-quota'
    value: string(tokenQuotaPerHour)
    secret: false
    tags: [ 'abw', 'finops' ]
  }
}

resource nvRpm 'Microsoft.ApiManagement/service/namedValues@2024-06-01-preview' = {
  parent: apim
  name: 'abw-agent-rpm'
  properties: {
    displayName: 'abw-agent-rpm'
    value: string(callsPerMinute)
    secret: false
    tags: [ 'abw', 'finops' ]
  }
}

resource api 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = {
  parent: apim
  name: 'abw-agent-frontdoor'
  properties: {
    displayName: 'Agent front door (Foundry Responses)'
    description: 'Every user-to-agent call enters here: Entra token validated, user revocable, calls and tokens metered per user, one log. The user token is passed through to Foundry unchanged.'
    type: 'http'
    subscriptionRequired: false
    serviceUrl: foundryProjectEndpoint
    path: 'agents'
    protocols: [ 'https' ]
    isCurrent: true
  }
}

var methods = [ 'GET', 'POST', 'DELETE' ]

resource ops 'Microsoft.ApiManagement/service/apis/operations@2025-09-01-preview' = [for m in methods: {
  parent: api
  name: 'frontdoor-${toLower(m)}'
  properties: {
    displayName: 'Foundry project ${m}'
    method: m
    urlTemplate: '/*'
  }
}]

resource policy 'Microsoft.ApiManagement/service/apis/policies@2025-09-01-preview' = {
  parent: api
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('apim/policies/agent-frontdoor.policy.xml')
  }
  dependsOn: [
    nvQuota
    nvRpm
  ]
}

output frontDoorUrl string = '${apim.properties.gatewayUrl}/agents'
output openAiBaseUrl string = '${apim.properties.gatewayUrl}/agents/openai/v1'
output apiName string = api.name
