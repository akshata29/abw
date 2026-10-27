// 02-foundry-rbac.bicep - who may BUILD agents (operator) and who may only USE them (every persona).
// Deployed after the Foundry stage (needs the account + project to exist).
targetScope = 'resourceGroup'

param accountName string
param projectName string
@description('Entra object id of the human operator / agent builder.')
param operatorOid string
@description('Entra group object id that contains every demo persona (consumers of agents).')
param consumersGroupId string

// Foundry User (formerly Azure AI User) - build + run agents, manage project connections.
var roleFoundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
// Foundry Agent Consumer - interact with agents at runtime ONLY (the least-privilege end-user role).
var roleAgentConsumer = 'eed3b665-ab3a-47b6-8f48-c9382fb1dad6'

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: accountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: account
  name: projectName
}

resource raOperatorAccount 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, operatorOid, roleFoundryUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleFoundryUser)
    principalId: operatorOid
    principalType: 'User'
  }
}

resource raConsumersProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: project
  name: guid(project.id, consumersGroupId, roleAgentConsumer)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAgentConsumer)
    principalId: consumersGroupId
    principalType: 'Group'
  }
}

output operatorRoleAssignmentId string = raOperatorAccount.id
output consumersRoleAssignmentId string = raConsumersProject.id
