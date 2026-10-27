#requires -Version 7
<#
.SYNOPSIS
  Agents Behind the Wall - staged, idempotent infrastructure deployment.

.DESCRIPTION
  Stages (see DESIGN.md section 8):
    preflight  - create RG (tagged), verify providers, detect operator IP
    network    - infra\01-network.bicep   (VNet, subnets, NSG, NAT, private DNS zones + links)
    foundry    - infra\foundry\main.bicep (vendored template 19: Foundry + agent subnet injection + BYO stores + AMPLS + LA/AppI)
    platform   - infra\03-platform.bicep  (UAMIs, KV, ACR, Storage, Cosmos, Search, ACA environments, RBAC)
    apps       - infra\04-apps.bicep      (container apps; run scripts\build-images.ps1 first)
    apim       - infra\05-apim.bicep      (APIM StandardV2 + private endpoint + logger + API Center)
    apis       - infra\05-apim-apis.bicep (MCP APIs, backends, policies, PRM discovery, legacy subscription; run after apps)
    governance - infra\06a-policy-definitions.bicep (subscription: custom policy definitions + initiative)
                 infra\06-governance.bicep         (initiative assignment, exemptions, Foundry guardrail policy, diagnostic settings)
                 infra\06b-observability.bicep     (Log Analytics function pack, Sentinel + analytics rules, ops alerts, cockpit workbook)
    observability - 06b only: rebuild the function pack / Sentinel rules / workbook from their sources and redeploy (no policy re-apply)
    frontdoor  - infra\08-agent-frontdoor.bicep (additive: APIM front door for the Foundry agent, per-user token budget + token metrics; run after apim)
    budget     - infra\09-budget.bicep (additive: monthly cost budget + alerts on the resource group)

  Outputs of every stage are written to infra\generated\<stage>.json for the next stage / scripts.

.EXAMPLE
  .\scripts\deploy.ps1 -Stage preflight
  .\scripts\deploy.ps1 -Stage network -WhatIf
  .\scripts\deploy.ps1 -Stage foundry
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)]
  [ValidateSet('preflight', 'network', 'foundry', 'foundryrbac', 'platform', 'apps', 'apim', 'apis', 'seed', 'governance', 'observability', 'frontdoor', 'budget')]
  [string]$Stage,
  [switch]$WhatIf,
  [switch]$NoWait
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"

$cfg   = Get-AbwConfig
$names = Get-AbwNames $cfg
$infra = Join-Path $script:RepoRoot 'infra'
$gen   = $script:GenDir

# A parameter named here carries a secret: az reads it from a short-lived file under .secrets (removed when the call returns)
# and the copy kept in infra\generated shows *** in its place.
$script:SecretParamKeys = @('vendorApiKey')

function Write-ParamFile([string]$Path, [hashtable]$Params, [string[]]$MaskKeys = @()) {
  $body = [ordered]@{
    '$schema'      = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
    contentVersion = '1.0.0.0'
    parameters     = [ordered]@{}
  }
  foreach ($k in $Params.Keys) {
    $v = if ($MaskKeys -contains $k) { '***' } else { $Params[$k] }
    $body.parameters[$k] = @{ value = $v }
  }
  $body | ConvertTo-Json -Depth 20 | Set-Content -Path $Path -Encoding utf8
}

function New-ParamFile([string]$Name, [hashtable]$Params) {
  $audit = Join-Path $gen "params.$Name.json"
  $secretKeys = @($Params.Keys | Where-Object { $script:SecretParamKeys -contains $_ })
  Write-ParamFile $audit $Params $secretKeys
  if ($secretKeys.Count -eq 0) { return $audit }
  $live = Join-Path $script:SecretsDir "params.$Name.tmp.json"
  Write-ParamFile $live $Params
  $live
}

function Remove-SecretParamFile([string]$Path) {
  if ($Path -and $Path.StartsWith($script:SecretsDir, [System.StringComparison]::OrdinalIgnoreCase)) {
    Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
  }
}

function Invoke-Stage([string]$Name, [string]$Template, [hashtable]$Params, [string]$OutputFile) {
  $paramFile = New-ParamFile $Name $Params
  $deployName = "abw-$Name"
  try {
    if ($WhatIf) {
      Write-Step "what-if $Name"
      $wi = & az deployment group what-if -g $cfg.rgName -n $deployName -f $Template -p "@$paramFile" --only-show-errors --result-format ResourceIdOnly 2>&1
      ($wi | Out-String) | Write-Host
      return
    }
    Write-Step "deploying $Name ($deployName) -> $($cfg.rgName)"
    if ($NoWait) {
      & az deployment group create -g $cfg.rgName -n $deployName -f $Template -p "@$paramFile" --only-show-errors --no-wait | Out-Null
      Write-Ok "started (no-wait). Poll: az deployment group show -g $($cfg.rgName) -n $deployName --query properties.provisioningState -o tsv"
      return
    }
    $raw = & az deployment group create -g $cfg.rgName -n $deployName -f $Template -p "@$paramFile" --only-show-errors -o json 2>&1
    if ($LASTEXITCODE -ne 0) {
      Write-Warn2 "deployment $deployName failed"
      ($raw | Out-String) | Write-Host
      $ops = & az deployment operation group list -g $cfg.rgName -n $deployName --query "[?properties.provisioningState=='Failed'].{res:properties.targetResource.resourceName,type:properties.targetResource.resourceType,code:properties.statusMessage.error.code,msg:properties.statusMessage.error.message}" -o json 2>$null
      if ($ops) { Write-Host ($ops | Out-String) }
      throw "stage '$Name' failed"
    }
    $obj = ($raw | Out-String) | ConvertFrom-Json
    $outputs = [ordered]@{}
    if ($obj.properties.outputs) {
      foreach ($p in $obj.properties.outputs.PSObject.Properties) { $outputs[$p.Name] = $p.Value.value }
    }
    if ($OutputFile) { Save-Json (Join-Path $gen $OutputFile) $outputs }
    Write-Ok "$Name complete ($($obj.properties.duration))"
    $outputs
  }
  finally { Remove-SecretParamFile $paramFile }
}

function Invoke-SubscriptionStage([string]$Name, [string]$Template, [hashtable]$Params, [string]$OutputFile) {
  $deployName = "abw-$Name"
  $paramArgs = @()
  if ($Params -and $Params.Count -gt 0) { $paramArgs = @('-p', "@$(New-ParamFile $Name $Params)") }
  if ($WhatIf) {
    Write-Step "what-if $Name (subscription scope)"
    $wi = & az deployment sub what-if -l $cfg.location -n $deployName -f $Template @paramArgs --only-show-errors --result-format ResourceIdOnly 2>&1
    ($wi | Out-String) | Write-Host
    return
  }
  Write-Step "deploying $Name ($deployName) -> subscription"
  $raw = & az deployment sub create -l $cfg.location -n $deployName -f $Template @paramArgs --only-show-errors -o json 2>&1
  if ($LASTEXITCODE -ne 0) {
    Write-Warn2 "deployment $deployName failed"
    ($raw | Out-String) | Write-Host
    throw "stage '$Name' failed"
  }
  $obj = ($raw | Out-String) | ConvertFrom-Json
  $outputs = [ordered]@{}
  if ($obj.properties.outputs) {
    foreach ($p in $obj.properties.outputs.PSObject.Properties) { $outputs[$p.Name] = $p.Value.value }
  }
  if ($OutputFile) { Save-Json (Join-Path $gen $OutputFile) $outputs }
  Write-Ok "$Name complete ($($obj.properties.duration))"
  $outputs
}

function Get-ObservabilityIds {
  $lawId = & az resource show -g $cfg.rgName -n $names.law --resource-type Microsoft.OperationalInsights/workspaces --query id -o tsv
  $appi  = (& az resource show -g $cfg.rgName -n $names.appi --resource-type Microsoft.Insights/components --query '{id:id,cs:properties.ConnectionString}' -o json) | ConvertFrom-Json
  if (-not $lawId -or -not $appi.id) { throw 'Log Analytics / Application Insights not found - run -Stage foundry first.' }
  [pscustomobject]@{ lawId = $lawId; appiId = $appi.id; appiConnectionString = $appi.cs }
}

# The azp (authorized party) allow-list enforced at the gateway AND in every MCP server.
# 04b07795-... is the well-known Azure CLI client (used for the admin-as-persona token workaround).
# Generated artefacts first: the function pack, the Sentinel rules and the workbook are built from their sources, never hand-edited.
function Build-ObservabilityArtifacts {
  $py = Join-Path $script:RepoRoot '.venv\Scripts\python.exe'
  foreach ($builder in @('observability\kql\pack.py', 'observability\sentinel\build_rules.py', 'observability\workbook\build_workbook.py')) {
    & $py (Join-Path $script:RepoRoot $builder) build
    if ($LASTEXITCODE -ne 0) { throw "build failed: $builder" }
  }
}

# 06b - the audit/detect/operate layer. Sentinel validates analytics rules against the workspace functions, which can take a few
# minutes to become resolvable after they are created - retry once instead of failing the whole stage.
function Invoke-ObservabilityStage {
  $obsParams = @{ names = $names; location = $cfg.location; tags = $cfg.tags }
  if ($cfg.PSObject.Properties['alertEmail'] -and $cfg.alertEmail) { $obsParams.alertEmail = $cfg.alertEmail }
  # optional: the tenant's Entra sign-in export workspace (read only) - lets AbwFullChain add the Entra sign-in and token rows
  if ($cfg.PSObject.Properties['entraWorkspaceId'] -and $cfg.entraWorkspaceId) { $obsParams.entraWorkspaceId = $cfg.entraWorkspaceId }
  try {
    Invoke-Stage 'observability' (Join-Path $infra '06b-observability.bicep') $obsParams 'observability.json' | Out-Null
  }
  catch {
    if ($WhatIf -or $NoWait) { throw }
    Write-Warn2 'observability stage failed - waiting 120 s for the new workspace functions to become resolvable, then retrying once'
    Start-Sleep -Seconds 120
    Invoke-Stage 'observability' (Join-Path $infra '06b-observability.bicep') $obsParams 'observability.json' | Out-Null
  }
}

function Get-AllowedAzp($ent) {
  (@($ent.clients.agent.appId, $ent.clients.test.appId, '04b07795-8ddb-461a-bbee-02f9e1bf7b46') -join ',')
}

function Get-VendorKey {
  $f = Join-Path $script:SecretsDir 'vendor-api-key.txt'
  if (-not (Test-Path $f)) { (New-StrongPassword 40) | Set-Content -Path $f -Encoding ascii -NoNewline }
  (Get-Content $f -Raw).Trim()
}
function Get-OperatorIpCached {
  # Informational only: the laptop sits behind a rotating corporate NAT, so no data plane is IP-allow-listed (PE-only + temporary-open seeding).
  Get-OperatorIp
}

switch ($Stage) {

  'preflight' {
    Write-Step "subscription $($cfg.subscriptionId) / tenant $($cfg.tenantId)"
    & az account set --subscription $cfg.subscriptionId
    if ($LASTEXITCODE -ne 0) { throw "az account set failed for subscription $($cfg.subscriptionId) - sign in with 'az login' and check infra\generated\config.json." }
    $tagArgs = @(); foreach ($k in $cfg.tags.PSObject.Properties) { $tagArgs += "$($k.Name)=$($k.Value)" }
    & az group create -n $cfg.rgName -l $cfg.location --tags @tagArgs --only-show-errors -o none
    if ($LASTEXITCODE -ne 0) { throw "az group create failed for $($cfg.rgName) ($($cfg.location))." }
    Write-Ok "resource group $($cfg.rgName) ($($cfg.location))"
    foreach ($p in 'Microsoft.Network','Microsoft.App','Microsoft.CognitiveServices','Microsoft.ApiManagement','Microsoft.Search','Microsoft.DocumentDB','Microsoft.ContainerRegistry','Microsoft.OperationalInsights','Microsoft.Insights','Microsoft.SecurityInsights','Microsoft.KeyVault','Microsoft.Storage','Microsoft.ManagedIdentity','Microsoft.PolicyInsights','Microsoft.ApiCenter','Microsoft.Web','Microsoft.Authorization') {
      $st = & az provider show -n $p --query registrationState -o tsv 2>$null
      if ($st -ne 'Registered') {
        Write-Warn2 "$p is $st -> registering"
        & az provider register -n $p --wait | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "az provider register failed for $p." }
      }
    }
    Write-Ok 'providers registered'
    $ip = Get-OperatorIpCached
    Write-Ok "operator public IP $ip"
    Save-Json (Join-Path $gen 'preflight.json') ([ordered]@{ operatorIp = $ip; at = (Get-Date).ToString('o') })
  }

  'network' {
    $params = @{
      location        = $cfg.location
      vnetName        = $names.vnet
      natGatewayName  = $names.nat
      apimNsgName     = $names.apimNsg
      tags            = $cfg.tags
    }
    Invoke-Stage 'network' (Join-Path $infra '01-network.bicep') $params 'network.json' | Out-Null
  }

  'foundry' {
    $net = Read-Json (Join-Path $gen 'network.json')
    if (-not $net) { throw 'Run -Stage network first.' }
    $rg = $cfg.rgName
    $zones = @(
      'privatelink.services.ai.azure.com', 'privatelink.openai.azure.com', 'privatelink.cognitiveservices.azure.com',
      'privatelink.search.windows.net', 'privatelink.blob.core.windows.net', 'privatelink.documents.azure.com',
      'privatelink.fabric.microsoft.com', 'privatelink.azurecr.io', 'privatelink.vaultcore.azure.net'
    )
    $monZones = @(
      'privatelink.monitor.azure.com', 'privatelink.oms.opinsights.azure.com',
      'privatelink.ods.opinsights.azure.com', 'privatelink.agentsvc.azure-automation.net'
    )
    $existing = [ordered]@{};    foreach ($z in $zones)    { $existing[$z]    = @{ subscriptionId = ''; resourceGroup = $rg } }
    $existingMon = [ordered]@{}; foreach ($z in $monZones) { $existingMon[$z] = @{ subscriptionId = ''; resourceGroup = $rg } }

    $params = @{
      location                         = $cfg.location
      uniqueSuffix                     = $cfg.u4
      accountNameOverride              = $names.foundry
      projectNameOverride              = $names.project
      cosmosDBNameOverride             = $names.asvcCosmos
      aiSearchNameOverride             = $names.asvcSearch
      azureStorageNameOverride         = $names.asvcStorage
      modelName                        = (Get-CfgValue $cfg 'modelName' 'gpt-5.4-mini')
      modelFormat                      = 'OpenAI'
      modelVersion                     = (Get-CfgValue $cfg 'modelVersion' '2026-03-17')
      modelSkuName                     = (Get-CfgValue $cfg 'modelSku' 'GlobalStandard')
      modelCapacity                    = [int](Get-CfgValue $cfg 'modelCapacity' 100)
      modelDeploymentName              = $names.modelDeploy
      projectDescription               = 'Agents Behind the Wall - governed agents for a Capital Markets desk (synthetic demo).'
      displayName                      = 'ABW wall desk'
      existingVnetResourceId           = $net.vnetId
      existingAgentSubnetResourceId    = $net.agentSubnetId
      existingPeSubnetResourceId       = $net.peSubnetId
      existingMcpSubnetResourceId      = $net.mcpSubnetId
      existingDnsZones                 = $existing
      existingMonitorDnsZones          = $existingMon
      enableKeyVault                   = $false
      enableContainerRegistry          = $false
      foundryPublicNetworkAccess       = 'Enabled'
      logAnalyticsName                 = $names.law
      appInsightsName                  = $names.appi
      amplsName                        = $names.ampls
      amplsIngestionAccessMode         = 'Open'
      disablePublicIngestion           = $false
      searchSkuName                    = 'basic'
      searchDisableLocalAuth           = $true
      searchLocation                   = $(if ($cfg.searchLocation) { $cfg.searchLocation } else { '' })
    }
    Invoke-Stage 'foundry' (Join-Path $infra 'foundry\main.bicep') $params 'foundry.json' | Out-Null
  }

  'foundryrbac' {
    $fnd = Read-Json (Join-Path $gen 'foundry.json')
    $ent = Read-Json (Join-Path $gen 'entra.json')
    if (-not $fnd -or -not $ent) { throw 'Run -Stage foundry and identity\Setup-Entra.ps1 -Phase 1 first.' }
    $params = @{
      accountName     = $fnd.accountName
      projectName     = $fnd.projectName
      operatorOid     = $cfg.operatorOid
      consumersGroupId = $ent.groups.'sg-abw-demo-all'
    }
    Invoke-Stage 'foundryrbac' (Join-Path $infra '02-foundry-rbac.bicep') $params 'foundryrbac.json' | Out-Null
  }

  'platform' {
    $net = Read-Json (Join-Path $gen 'network.json')
    $ent = Read-Json (Join-Path $gen 'entra.json')
    if (-not $net -or -not $ent) { throw 'Run -Stage network and identity\Setup-Entra.ps1 -Phase 1 first.' }
    $g = $ent.groups
    $params = @{
      location    = $cfg.location
      searchLocation = $(if ($cfg.searchLocation) { $cfg.searchLocation } else { '' })
      workload    = $cfg.workload
      regionCode  = $cfg.regionCode
      instance    = $cfg.instance
      tags        = $cfg.tags
      names       = $names
      vnetId      = $net.vnetId
      peSubnetId  = $net.peSubnetId
      mcpSubnetId = $net.mcpSubnetId
      natPublicIp = $net.natPublicIp
      operatorOid = $cfg.operatorOid
      groupIds    = @{
        research   = $g.'sg-abw-research'
        wallFalcon = $g.'sg-abw-wall-falcon'
        traders    = $g.'sg-abw-traders'
        compliance = $g.'sg-abw-compliance'
        infosec    = $g.'sg-abw-infosec'
        all        = $g.'sg-abw-demo-all'
      }
    }
    Invoke-Stage 'platform' (Join-Path $infra '03-platform.bicep') $params 'platform.json' | Out-Null
  }

  'apps' {
    $plat = Read-Json (Join-Path $gen 'platform.json')
    $ent  = Read-Json (Join-Path $gen 'entra.json')
    $img  = Read-Json (Join-Path $gen 'images.json')
    if (-not $plat -or -not $ent) { throw 'Run -Stage platform and identity\Setup-Entra.ps1 -Phase 1 first.' }
    if (-not $img)  { throw 'Run scripts\build-images.ps1 first (writes infra\generated\images.json).' }
    $vendorKey = Get-VendorKey
    $params = @{
      location    = $cfg.location
      tags        = $cfg.tags
      names       = $names
      platform    = $plat
      apiAppIds   = @{
        research = $ent.apis.research.appId
        wall     = $ent.apis.wall.appId
        actions  = $ent.apis.actions.appId
        private  = $ent.apis.private.appId
      }
      allowedAzp  = (Get-AllowedAzp $ent)
      imageTag    = $img.tag
      apimBaseUrl = "https://$($names.apim).azure-api.net"
      cosmosObo   = $(if ($null -ne $cfg.cosmosObo) { [bool]$cfg.cosmosObo } else { $true })
      vendorApiKey = $vendorKey
    }
    Invoke-Stage 'apps' (Join-Path $infra '04-apps.bicep') $params 'apps.json' | Out-Null
  }

  'apim' {
    $net = Read-Json (Join-Path $gen 'network.json')
    $ent = Read-Json (Join-Path $gen 'entra.json')
    if (-not $net -or -not $ent) { throw 'Run -Stage network and identity\Setup-Entra.ps1 -Phase 1 first.' }
    $obs = Get-ObservabilityIds
    $params = @{
      location             = $cfg.location
      tags                 = $cfg.tags
      names                = $names
      apimSubnetId         = $net.apimSubnetId
      peSubnetId           = $net.peSubnetId
      workspaceId          = $obs.lawId
      appiId               = $obs.appiId
      appiConnectionString = $obs.appiConnectionString
      publisherEmail       = (Get-CfgValue $cfg 'publisherEmail' $cfg.operatorUpn)
      allowedAzp           = (Get-AllowedAzp $ent)
    }
    Invoke-Stage 'apim' (Join-Path $infra '05-apim.bicep') $params 'apim.json' | Out-Null
  }

  'apis' {
    $apps = Read-Json (Join-Path $gen 'apps.json')
    $ent  = Read-Json (Join-Path $gen 'entra.json')
    if (-not $apps -or -not $ent) { throw 'Run -Stage apps (and apim) first.' }
    # versionless secret identifier (created by the apps stage via ARM) so rotating the key needs no redeploy
    $secretUri = $apps.vendorKeySecretUri
    if (-not $secretUri) { throw 'apps.json has no vendorKeySecretUri - re-run -Stage apps.' }
    $params = @{
      names              = $names
      apps               = $apps.apps
      apiAppIds          = @{
        research  = $ent.apis.research.appId
        wall      = $ent.apis.wall.appId
        actions   = $ent.apis.actions.appId
        vendorgw  = $ent.apis.vendorgw.appId
      }
      vendorKeySecretUri = $secretUri
      validateInternalTls = $(if ($null -ne $cfg.validateInternalTls) { [bool]$cfg.validateInternalTls } else { $false })
    }
    Invoke-Stage 'apis' (Join-Path $infra '05-apim-apis.bicep') $params 'apis.json' | Out-Null
  }

  'frontdoor' {
    $params = @{
      names                  = $names
      foundryProjectEndpoint = "https://$($names.foundry).services.ai.azure.com/api/projects/$($names.project)"
    }
    Invoke-Stage 'frontdoor' (Join-Path $infra '08-agent-frontdoor.bicep') $params 'frontdoor.json' | Out-Null
  }

  'budget' {
    $params = @{ names = $names }
    if ($cfg.PSObject.Properties['alertEmail'] -and $cfg.alertEmail) { $params.alertEmail = $cfg.alertEmail }
    Invoke-Stage 'budget' (Join-Path $infra '09-budget.bicep') $params 'budget.json' | Out-Null
  }

  'seed' {
    # In-VNet seeding: a Container Apps Job (own scoped identity) writes the synthetic corpus over the private endpoints.
    # No data plane is ever opened to the internet and no operator IP is needed.
    $plat = Read-Json (Join-Path $gen 'platform.json')
    $simg = Read-Json (Join-Path $gen 'images-seed.json')
    if (-not $plat) { throw 'Run -Stage platform first.' }
    if (-not $simg) { throw 'Run .\scripts\build-images.ps1 -Target seed first (writes infra\generated\images-seed.json).' }
    $params = @{
      location   = $cfg.location
      workload   = $cfg.workload
      regionCode = $cfg.regionCode
      instance   = $cfg.instance
      tags       = $cfg.tags
      platform   = $plat
      imageTag   = $simg.tag
    }
    $out = Invoke-Stage 'seed' (Join-Path $infra '04b-seed-job.bicep') $params 'seed.json'
    if ($WhatIf -or $NoWait) { break }
    $jobName = $out.seedJob.name
    Write-Step "starting seed job $jobName"
    & az containerapp job start -n $jobName -g $cfg.rgName --only-show-errors -o none
    if ($LASTEXITCODE -ne 0) { throw 'az containerapp job start failed' }
    $deadline = (Get-Date).AddMinutes(12); $status = ''
    do {
      Start-Sleep -Seconds 15
      $ex = (& az containerapp job execution list -n $jobName -g $cfg.rgName --only-show-errors -o json | ConvertFrom-Json) | Sort-Object { $_.properties.startTime } -Descending | Select-Object -First 1
      $status = $ex.properties.status
      Write-Host "    ..  execution $($ex.name): $status"
    } while ($status -in @('Running', 'Processing', 'Pending', '') -and (Get-Date) -lt $deadline)
    if ($status -ne 'Succeeded') { throw "seed job ended with status '$status' (see: az containerapp job logs show -n $jobName -g $($cfg.rgName) --container seed)" }
    Write-Ok "seed job succeeded ($($ex.name))"
  }

  'governance' {
    Build-ObservabilityArtifacts

    # 06a - custom policy definitions + the initiative (subscription scope; every name is abw-* and removed by teardown)
    $pol = Invoke-SubscriptionStage 'policy-defs' (Join-Path $infra '06a-policy-definitions.bicep') @{} 'policy.json'
    if ($WhatIf) { $pol = Read-Json (Join-Path $gen 'policy.json') }
    if (-not $pol) { throw 'No initiative yet - run -Stage governance once without -WhatIf (06a must exist before 06 can be assigned).' }

    # 06 - assignment, exemptions, guardrail policy, diagnostic settings (this is what flips the platform controls to Deny)
    Invoke-Stage 'governance' (Join-Path $infra '06-governance.bicep') @{ names = $names; initiativeId = $pol.initiativeId; legacyWaiverExpiry = ([datetime]::UtcNow.AddDays(90).ToString('s') + 'Z') } 'governance.json' | Out-Null

    Invoke-ObservabilityStage
  }

  'observability' {
    Build-ObservabilityArtifacts
    Invoke-ObservabilityStage
  }

  default {
    throw "Stage '$Stage' is not implemented yet."
  }
}
