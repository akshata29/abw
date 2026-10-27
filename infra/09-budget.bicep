// 09-budget.bicep - a monthly cost budget with alerts on the demo resource group (additive; nothing existing is changed).
//
// Cost Management e-mails the resource-group Owners (and the optional alert address) at 50 / 80 / 100 % of the budget on ACTUAL spend
// and at 100 % on FORECASTED spend. It is an alert, not a cap: nothing is stopped when it fires. What actually stops runaway agent
// usage is the per-user token budget at the APIM agent front door (08-agent-frontdoor.bicep).
// Remove it with:  az consumption budget delete --budget-name <name> --resource-group <rg>   (scripts\teardown.ps1 removes the whole resource group anyway).

targetScope = 'resourceGroup'

param names object

@description('Monthly budget in USD. 1,200 is the list-price run-rate of the platform left running 24x7 (docs\\COST.md), so the 80 % alert means "you forgot to tear it down". Change it to whatever the owner wants to be told about.')
@minValue(1)
param monthlyBudgetUsd int = 1200

@description('First day of the current month: a monthly budget must start on the 1st and not before the current month.')
param startDate string = '${utcNow('yyyy-MM')}-01T00:00:00Z'

@description('Optional extra e-mail address. The resource-group Owners are always notified.')
param alertEmail string = ''

var emails = empty(alertEmail) ? [] : [ alertEmail ]

resource budget 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: names.budget
  properties: {
    category: 'Cost'
    amount: monthlyBudgetUsd
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
    }
    notifications: {
      actual50: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: emails
        contactRoles: [ 'Owner' ]
        locale: 'en-us'
      }
      actual80: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: emails
        contactRoles: [ 'Owner' ]
        locale: 'en-us'
      }
      actual100: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: emails
        contactRoles: [ 'Owner' ]
        locale: 'en-us'
      }
      forecast100: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: emails
        contactRoles: [ 'Owner' ]
        locale: 'en-us'
      }
    }
  }
}

output budget object = {
  name: budget.name
  amountUsd: monthlyBudgetUsd
  timeGrain: 'Monthly'
  startDate: startDate
  thresholds: [ '50 % actual', '80 % actual', '100 % actual', '100 % forecast' ]
}
