#requires -Version 7
<#
.SYNOPSIS
  Agents Behind the Wall - remove everything the demo created, in the order that actually works.

.DESCRIPTION
  Order matters (each step removes something the next one trips over):

    0. Track B identity extras             the report-only Conditional Access policy (it lives in Entra, outside the RG) and the
                                           Agent 365 role grant on APIM (scripts\extras-agent-identity.ps1 -Remove; skipped with -KeepEntra)
    1. Foundry agent capability hosts      the network-injected agent subnet is held by a service link until they are gone
    2. Log Analytics workspace (force)     otherwise the name stays reserved for 14 days in soft-delete
    3. Resource group                      everything inside: APIM, Foundry, apps, data, Sentinel, policy assignment + exemptions, alerts, workbook
    4. Soft-deleted leftovers (purge)      Foundry account, Key Vault, API Management - these keep their names for 7-90 days otherwise
    5. Subscription-scope policy objects   abw-agent-platform-controls initiative + abw-foundry-* definitions (outside the RG)
    6. Entra objects                       demo users, sg-abw-* groups, abw-* apps (identity\Setup-Entra.ps1 -Phase Teardown)

  It only touches objects it can prove belong to the demo: the resource group named in infra\generated\config.json, custom policy
  objects whose name starts with 'abw-', and Entra objects tagged 'abw-demo' / named 'sg-abw-*' / carrying the demo company marker.
  Nothing else in the subscription or tenant is read for deletion.

.PARAMETER WhatIf
  Discover and print everything that would be removed; delete nothing. Safe to run any time.
.PARAMETER Yes
  Skip the "type the resource group name" confirmation.
.PARAMETER KeepEntra
  Leave the Entra users, groups and apps in place (re-use them for the next deployment).
.PARAMETER SkipPurge
  Do not purge soft-deleted Foundry / Key Vault / API Management (their names stay reserved until the retention period ends).
.PARAMETER CleanLocal
  Also delete .secrets\ and infra\generated\ (persona passwords, client secret, stage outputs, config.json).

.EXAMPLE
  .\scripts\teardown.ps1 -WhatIf
  .\scripts\teardown.ps1
  .\scripts\teardown.ps1 -Yes -CleanLocal
#>
[CmdletBinding()]
param(
  [switch]$WhatIf,
  [switch]$Yes,
  [switch]$KeepEntra,
  [switch]$SkipPurge,
  [switch]$CleanLocal
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"

$cfg   = Get-AbwConfig
$names = Get-AbwNames $cfg
$rg    = $cfg.rgName
$sub   = $cfg.subscriptionId
$loc   = $cfg.location
$arm   = 'https://management.azure.com'

$policyInitiative = 'abw-agent-platform-controls'
$policyDefinitions = @('abw-foundry-no-keyed-connections', 'abw-foundry-approved-mcp-targets')

function Invoke-AzJson([string[]]$AzArgs) {
  $raw = & az @AzArgs -o json --only-show-errors 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
  return ($raw | Out-String | ConvertFrom-Json)
}

function Invoke-AzRest([string]$Method, [string]$Url) {
  $raw = & az rest --method $Method --url $Url --only-show-errors 2>$null
  if ($LASTEXITCODE -ne 0) { return $null }
  if (-not $raw) { return @{} }
  return ($raw | Out-String | ConvertFrom-Json)
}

function Test-RgExists { (& az group exists -n $rg --only-show-errors) -eq 'true' }

# ---------------------------------------------------------------- 0. discovery (always runs; read-only)
Write-Step "Tenant $($cfg.tenantDomain)  subscription $sub"
$acct = Invoke-AzJson @('account', 'show')
if (-not $acct -or $acct.id -ne $sub) {
  throw "az is signed in to subscription '$($acct.id)' but this deployment lives in '$sub'. Run: az account set --subscription $sub"
}

$rgExists = Test-RgExists
$resources = @()
if ($rgExists) {
  $resources = @(Invoke-AzJson @('resource', 'list', '-g', $rg, '--query', '[].{n:name,t:type}'))
}
Write-Step "Resource group $rg  ($(if ($rgExists) { "$($resources.Count) resources" } else { 'not found - already deleted' }))"
if ($resources.Count) {
  $resources | Group-Object t | Sort-Object Count -Descending | ForEach-Object { Write-Host ("    {0,3}  {1}" -f $_.Count, $_.Name) }
}

$policySets = @(); $policyDefs = @()
$setList = Invoke-AzJson @('policy', 'set-definition', 'list', '--query', "[?policyType=='Custom'].name")
if ($setList) { $policySets = @($setList | Where-Object { $_ -like 'abw-*' }) }
$defList = Invoke-AzJson @('policy', 'definition', 'list', '--query', "[?policyType=='Custom'].name")
if ($defList) { $policyDefs = @($defList | Where-Object { $_ -like 'abw-*' }) }
Write-Step "Subscription-scope policy objects: $($policySets.Count) initiative(s), $($policyDefs.Count) definition(s)"
($policySets + $policyDefs) | ForEach-Object { Write-Host "    $_" }

$entraApps = @(); $entraUsers = @(); $entraGroups = @()
if (-not $KeepEntra) {
  $entraApps   = @(Get-GraphAll '/applications' @{ '$filter' = "tags/any(t:t eq 'abw-demo')"; '$select' = 'id,displayName' })
  $entraUsers  = @(Get-GraphAll '/users' @{ '$filter' = "companyName eq 'Contoso Capital Markets (ABW demo)'"; '$select' = 'id,userPrincipalName'; '$count' = 'true' })
  $entraGroups = @(Get-GraphAll '/groups' @{ '$filter' = "startswith(displayName,'sg-abw-')"; '$select' = 'id,displayName' })
  Write-Step "Entra: $($entraApps.Count) app(s), $($entraUsers.Count) user(s), $($entraGroups.Count) group(s)"
  ($entraApps | ForEach-Object { "app   $($_.displayName)" }) + ($entraUsers | ForEach-Object { "user  $($_.userPrincipalName)" }) +
    ($entraGroups | ForEach-Object { "group $($_.displayName)" }) | ForEach-Object { Write-Host "    $_" }
}

$capBase = "$arm/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.CognitiveServices/accounts/$($names.foundry)"
$capApi  = 'api-version=2025-04-01-preview'
$capHosts = @()
if ($rgExists -and ($resources | Where-Object { $_.n -eq $names.foundry })) {
  foreach ($scope in @("$capBase/projects/$($names.project)/capabilityHosts", "$capBase/capabilityHosts")) {
    $list = Invoke-AzRest 'GET' "$scope`?$capApi"
    foreach ($h in @($list.value)) { $capHosts += [pscustomobject]@{ Scope = $scope; Name = $h.name } }
  }
}
Write-Step "Foundry capability hosts holding the agent subnet: $($capHosts.Count)"
$capHosts | ForEach-Object { Write-Host "    $($_.Name)  ($($_.Scope -replace '^.*/accounts/', ''))" }

if ($WhatIf) {
  Write-Step 'WhatIf: nothing was deleted. Steps a real run performs, in order:'
  Write-Host "    0. remove the report-only Conditional Access policy + the Agent 365 role grant$(if ($KeepEntra) { '  (skipped: -KeepEntra)' })"
  Write-Host '    1. delete Foundry capability hosts (project, then account)'
  Write-Host "    2. force-delete Log Analytics workspace $($names.law)"
  Write-Host "    3. delete resource group $rg"
  Write-Host "    4. purge soft-deleted: Foundry $($names.foundry), Key Vault $($names.kv), API Management $($names.apim)$(if ($SkipPurge) { '  (skipped: -SkipPurge)' })"
  Write-Host "    5. delete policy initiative $policyInitiative and definitions $($policyDefinitions -join ', ')"
  Write-Host "    6. delete Entra objects$(if ($KeepEntra) { '  (skipped: -KeepEntra)' })"
  Write-Host "    7. remove local secrets and generated state$(if (-not $CleanLocal) { '  (skipped: no -CleanLocal)' })"
  return
}

if (-not $Yes) {
  Write-Host ''
  Write-Host "This permanently deletes the demo. Type the resource group name ($rg) to continue:" -ForegroundColor Yellow
  if ((Read-Host) -ne $rg) { throw 'Confirmation did not match - nothing was deleted.' }
}

# ---------------------------------------------------------------- 0. Track B identity extras (the CA policy is an Entra object, outside the RG)
if (-not $KeepEntra) {
  Write-Step 'Rolling back the report-only Conditional Access policy and the Agent 365 role grant'
  try { & (Join-Path $PSScriptRoot 'extras-agent-identity.ps1') -Remove }
  catch { Write-Warn2 "extras-agent-identity.ps1 -Remove failed: $($_.Exception.Message) - delete the policy 'ABW demo - require MFA for Agent Wall MCP APIs (REPORT-ONLY)' in Entra > Protection > Conditional Access by hand" }
}

# ---------------------------------------------------------------- 1. Foundry capability hosts
if ($capHosts.Count) {
  Write-Step 'Releasing the Foundry agent subnet (capability hosts)'
  foreach ($h in $capHosts) {
    Write-Host "    deleting capability host $($h.Name)"
    Invoke-AzRest 'DELETE' "$($h.Scope)/$($h.Name)`?$capApi" | Out-Null
    $deadline = (Get-Date).AddMinutes(20)
    while ((Get-Date) -lt $deadline) {
      Start-Sleep -Seconds 20
      $still = Invoke-AzRest 'GET' "$($h.Scope)/$($h.Name)`?$capApi"
      if (-not $still) { Write-Ok "capability host $($h.Name) gone"; break }
      Write-Host '    ..  still deleting' -ForegroundColor DarkGray
    }
  }
}

# ---------------------------------------------------------------- 2. Log Analytics (force, releases the name)
if ($rgExists -and ($resources | Where-Object { $_.n -eq $names.law })) {
  Write-Step "Force-deleting Log Analytics workspace $($names.law)"
  & az monitor log-analytics workspace delete -g $rg -n $names.law --force true --yes --only-show-errors 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) { Write-Ok 'workspace removed (no soft-delete reservation)' } else { Write-Warn2 'workspace delete failed - the resource group delete below will soft-delete it instead' }
}

# ---------------------------------------------------------------- 3. Resource group
if ($rgExists) {
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    Write-Step "Deleting resource group $rg (attempt $attempt/3; APIM, Foundry and Container Apps make this take 20-40 minutes)"
    & az group delete -n $rg --yes --only-show-errors 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    if (-not (Test-RgExists)) { Write-Ok 'resource group deleted'; break }
    if ($attempt -eq 3) { throw "Resource group $rg is still present after 3 attempts. Read the deployment operations / activity log, then re-run this script (it resumes)." }
    Write-Warn2 'not deleted yet (a service association link on the agent subnet can hold it for a while) - waiting 5 minutes'
    Start-Sleep -Seconds 300
  }
} else {
  Write-Ok "resource group $rg already gone"
}

# ---------------------------------------------------------------- 4. purge soft-deleted leftovers
if (-not $SkipPurge) {
  Write-Step 'Purging soft-deleted leftovers'
  $del = @(Invoke-AzJson @('cognitiveservices', 'account', 'list-deleted') | Where-Object { $_.name -eq $names.foundry })
  if ($del.Count) {
    & az cognitiveservices account purge --location $loc --resource-group $rg --name $names.foundry --only-show-errors 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Ok "Foundry account $($names.foundry) purged" } else { Write-Warn2 "could not purge Foundry account $($names.foundry)" }
  }
  $delKv = @(Invoke-AzJson @('keyvault', 'list-deleted') | Where-Object { $_.name -eq $names.kv })
  if ($delKv.Count) {
    & az keyvault purge --name $names.kv --location $loc --only-show-errors 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Ok "Key Vault $($names.kv) purged" } else { Write-Warn2 "could not purge Key Vault $($names.kv) (purge protection on?)" }
  }
  $delApim = @(Invoke-AzJson @('apim', 'deletedservice', 'list') | Where-Object { $_.name -eq $names.apim })
  if ($delApim.Count) {
    & az apim deletedservice purge --service-name $names.apim --location $loc --only-show-errors 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Ok "API Management $($names.apim) purged" } else { Write-Warn2 "could not purge API Management $($names.apim)" }
  }
}

# ---------------------------------------------------------------- 5. subscription-scope policy objects
Write-Step 'Removing subscription-scope policy objects'
foreach ($s in $policySets) {
  & az policy set-definition delete --name $s --only-show-errors 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) { Write-Ok "initiative $s" } else { Write-Warn2 "initiative $s could not be deleted (still assigned somewhere?)" }
}
foreach ($d in $policyDefs) {
  & az policy definition delete --name $d --only-show-errors 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) { Write-Ok "definition $d" } else { Write-Warn2 "definition $d could not be deleted" }
}

# ---------------------------------------------------------------- 6. Entra
if (-not $KeepEntra) {
  & (Join-Path $PSScriptRoot '..\identity\Setup-Entra.ps1') -Phase Teardown
}

# ---------------------------------------------------------------- 7. local state
if ($CleanLocal) {
  Write-Step 'Removing local secrets and generated state'
  Get-ChildItem -Path $script:SecretsDir -File -ErrorAction SilentlyContinue | Remove-Item -Force
  Get-ChildItem -Path $script:GenDir -File -Filter *.json -ErrorAction SilentlyContinue | Remove-Item -Force
  Write-Ok 'done (config.json will be recreated, with a new suffix, on the next deploy)'
}

Write-Step 'Teardown complete'
