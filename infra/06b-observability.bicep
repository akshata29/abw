// 06b-observability.bicep - the audit / detect / operate layer on top of the data the platform already emits.
//
// Runs AFTER 06-governance.bicep (which switches on the diagnostic settings the queries read).
// Everything here is scoped to rg-abw-demo-eus2-001.
//
//   1. Log Analytics functions   AbwMcpAudit, AbwGateway, AbwDenials, AbwAgentActivity, AbwUsageByUser, AbwTokenUsage, AbwZeroKeys, AbwIdentityChain,
//                                AbwFullChainCore (any request id / trace id -> the whole chain, front door to Sentinel),
//                                AbwFullChain (the same plus the Entra sign-in and token-issue rows, read from the Entra sign-in export workspace)
//                                (source of truth: observability\kql\*.kql -> pack.json)
//   2. Microsoft Sentinel        onboarding + 9 scheduled analytics rules (observability\sentinel\*.kql -> rules.json)
//   3. Operational alerts        action group + log alerts for platform health (not security - that is Sentinel's job)
//   4. Cockpit workbook          one pane: usage, identity chain, governance posture, threats, gateway, zero-keys, changes
//                                (observability\workbook\build_workbook.py -> cockpit.workbook.json)

targetScope = 'resourceGroup'

param names object

param location string = resourceGroup().location

param tags object = {}

@description('Optional e-mail receiver for the operational alerts. Empty = alerts only show in the portal.')
param alertEmail string = ''

@description('Resource id of the workspace the tenant exports Entra sign-in logs to (read only). AbwFullChain adds the Entra sign-in and token rows from it. Empty = AbwFullChain is AbwFullChainCore, no Entra rows.')
param entraWorkspaceId string = ''

var pack = loadJsonContent('../observability/kql/pack.json')
var rules = loadJsonContent('../observability/sentinel/rules.json')
var workbookTemplate = loadTextContent('../observability/workbook/cockpit.workbook.json')

// AbwFullChain.kql names the two Entra tables on lines of their own (kql\pack.py deploy_body does the same rewrite for local runs)
var entraPrefix = empty(entraWorkspaceId) ? '' : 'workspace(\'${entraWorkspaceId}\').'

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: names.law
}

// ------------------------------------------------------------------------------------------------ 1. functions
// pack.json is dependency-ordered (AbwMcpAudit first); the workspace validates each query, so deploy them one at a time.
@batchSize(1)
resource functions 'Microsoft.OperationalInsights/workspaces/savedSearches@2020-08-01' = [for fn in pack: {
  parent: law
  name: toLower('abw-${fn.name}')
  properties: {
    // etag '*' lets a re-deployment overwrite an existing function (accepted by the API, missing from the Bicep type)
    #disable-next-line BCP037
    etag: '*'
    category: 'ABW Agent Wall'
    displayName: fn.name
    query: empty(entraWorkspaceId) && !empty(fn.fallback) ? fn.fallback : replace(replace(fn.body, '= AADNonInteractiveUserSignInLogs;', '= ${entraPrefix}AADNonInteractiveUserSignInLogs;'), '= SigninLogs;', '= ${entraPrefix}SigninLogs;')
    functionAlias: fn.name
    functionParameters: fn.params
    version: 2
  }
}]

// ------------------------------------------------------------------------------------------------ 2. Microsoft Sentinel
resource sentinel 'Microsoft.SecurityInsights/onboardingStates@2024-03-01' = {
  scope: law
  name: 'default'
  properties: {}
}

// Rules are per-user where the question is "who", per-alert where it is "what happened".
resource analyticsRules 'Microsoft.SecurityInsights/alertRules@2024-03-01' = [for r in rules: {
  scope: law
  name: guid(law.id, 'abw-sentinel-rule', r.id)
  kind: 'Scheduled'
  properties: {
    displayName: 'ABW - ${r.name}'
    description: r.description
    severity: r.severity
    enabled: true
    query: r.query
    queryFrequency: r.frequency
    queryPeriod: r.period
    triggerOperator: 'GreaterThan'
    triggerThreshold: 0
    suppressionEnabled: false
    suppressionDuration: 'PT1H'
    tactics: r.tactics
    eventGroupingSettings: {
      aggregationKind: 'AlertPerResult'
    }
    entityMappings: empty(r.entities) ? null : r.entities
    customDetails: r.details
    incidentConfiguration: {
      createIncident: true
      groupingConfiguration: {
        enabled: true
        reopenClosedIncident: false
        lookbackDuration: 'PT5H'
        matchingMethod: r.group == 'Account' ? 'Selected' : 'AnyAlert'
        groupByEntities: r.group == 'Account' ? [ 'Account' ] : []
        groupByAlertDetails: []
        groupByCustomDetails: []
      }
    }
  }
  dependsOn: [
    sentinel
    functions
  ]
}]

// ------------------------------------------------------------------------------------------------ 3. operational alerts
resource opsActionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-abw-ops-eus2-001'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'abw-ops'
    enabled: true
    emailReceivers: empty(alertEmail) ? [] : [
      {
        name: 'operator'
        emailAddress: alertEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

var opsAlerts = [
  {
    key: 'mcp-server-errors'
    title: 'ABW ops - MCP server tool errors'
    description: 'An MCP tool raised an unexpected error (not a policy denial). Platform health, not a security signal.'
    severity: 2
    threshold: 0
    query: 'AbwMcpAudit(15m) | where Decision == "error"'
  }
  {
    key: 'gateway-backend-errors'
    title: 'ABW ops - APIM gateway / backend 5xx'
    description: 'More than two MCP requests in 15 minutes failed at the gateway or the backend.'
    severity: 2
    threshold: 2
    query: 'AbwGateway(15m) | where Outcome == "gateway_or_backend_error"'
  }
  {
    key: 'agent-run-failures'
    title: 'ABW ops - Foundry agent run failures'
    description: 'A Foundry agent run failed for a reason other than the content-safety guardrail (which is a security signal, handled by Sentinel).'
    severity: 3
    threshold: 0
    query: 'AppDependencies | where TimeGenerated > ago(15m) | where Name startswith "invoke_agent" | where Success == false | where tostring(Properties["error.type"]) != "content_filter"'
  }
]

resource opsAlertRules 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [for a in opsAlerts: {
  name: 'alrt-abw-${a.key}-eus2-001'
  location: location
  tags: tags
  kind: 'LogAlert'
  properties: {
    displayName: a.title
    description: a.description
    severity: a.severity
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    scopes: [ law.id ]
    autoMitigate: true
    criteria: {
      allOf: [
        {
          query: a.query
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: a.threshold
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: [ opsActionGroup.id ]
    }
  }
  dependsOn: [
    functions
  ]
}]

// ------------------------------------------------------------------------------------------------ 4. cockpit workbook
var workbookData = replace(replace(replace(workbookTemplate, '__WORKSPACE_ID__', law.id), '__SUBSCRIPTION_ID__', subscription().subscriptionId), '__RESOURCE_GROUP__', resourceGroup().name)

resource cockpit 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: guid(resourceGroup().id, 'abw-agent-wall-cockpit')
  location: location
  tags: tags
  kind: 'shared'
  properties: {
    displayName: 'Agent Wall - Cockpit'
    category: 'workbook'
    sourceId: law.id
    version: 'Notebook/1.0'
    serializedData: workbookData
  }
}

output functionNames array = [for fn in pack: fn.name]
output sentinelRuleCount int = length(rules)
output actionGroupId string = opsActionGroup.id
output workbookId string = cockpit.id
output workbookName string = cockpit.name
