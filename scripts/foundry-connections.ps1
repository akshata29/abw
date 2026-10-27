#requires -Version 7
<#
.SYNOPSIS
  Agents Behind the Wall - creates the Foundry project connections for every MCP server (keyless: OAuth identity passthrough).

.DESCRIPTION
  One *custom OAuth* connection per MCP server (Entra v2 tokens are single-resource, so one audience per connection):
    mcp-research-oauth  -> APIM /research/mcp   api://<research>/Tools.Read
    mcp-wall-oauth      -> APIM /wall/mcp       api://<wall>/Tools.Read
    mcp-actions-oauth   -> APIM /actions/mcp    api://<actions>/Tools.Read + Tools.Execute
    mcp-vendor-oauth    -> APIM /vendor/mcp     api://<vendorgw>/Tools.Read   (gateway swaps in the vendor key)
    mcp-private-oauth   -> private ACA /mcp     api://<private>/Tools.Read    (direct over the delegated agent subnet)
  plus the deliberately leaky baseline:
    mcp-legacy-key      -> APIM /legacy/mcp     shared APIM subscription key (custom-keys)  <- "what we found in the typical POC"

  The OAuth app is the abw-agent-client app registration; Foundry returns one redirect URL per connection, which is
  registered on the app (identity\Setup-Entra.ps1 -Phase 2 -AgentClientRedirectUris).
  Output: infra\generated\connections.json  { <name>: { target, authType, scopes, redirectUrl, connectionId } }

.EXAMPLE
  .\scripts\foundry-connections.ps1            # create the missing ones
  .\scripts\foundry-connections.ps1 -Force     # re-create all (redirect URLs may change)
  .\scripts\foundry-connections.ps1 -Only mcp-wall-oauth,mcp-vendor-oauth   # re-create just those
#>
[CmdletBinding()]
param(
  [switch]$Force,
  [string[]]$Only = @(),
  [switch]$SkipEntraRedirects
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"
$Only = @($Only | ForEach-Object { $_ -split ',' } | Where-Object { $_ })   # pwsh -File passes a,b as one string

$cfg   = Get-AbwConfig
$names = Get-AbwNames $cfg
$gen   = $script:GenDir
$ent   = Read-Json (Join-Path $gen 'entra.json')
$apis  = Read-Json (Join-Path $gen 'apis.json')
$apps  = Read-Json (Join-Path $gen 'apps.json')
$fnd   = Read-Json (Join-Path $gen 'foundry.json')
if (-not $ent -or -not $apis -or -not $apps -or -not $fnd) { throw 'Run the foundry, apps and apis stages (and Entra phase 1) first.' }

$projectEndpoint = $fnd.projectEndpoint
if (-not $projectEndpoint) { $projectEndpoint = "https://$($names.foundry).services.ai.azure.com/api/projects/$($names.project)" }
$secretFile = Join-Path $script:SecretsDir 'agent-client.json'
$agentSecret = (Get-Content $secretFile -Raw | ConvertFrom-Json).secret
$tenant = $cfg.tenantId
$authUrl  = "https://login.microsoftonline.com/$tenant/oauth2/v2.0/authorize"
$tokenUrl = "https://login.microsoftonline.com/$tenant/oauth2/v2.0/token"
$gw = @{}; foreach ($a in $apis.gatewayApis) { $gw[$a.key] = $a.url }

# @() keeps a single scope an array - otherwise '+' concatenates strings (...Tools.Readoffline_access, AADSTS650053)
function Get-Scope([string]$ApiKey, [string[]]$Scopes) {
  (@($Scopes | ForEach-Object { "api://$($ent.apis.$ApiKey.appId)/$_" }) + 'offline_access') -join ' '
}

$specs = @(
  @{ name = 'mcp-research-oauth'; target = $gw.research; auth = 'oauth2'; scope = (Get-Scope 'research' @('Tools.Read')) }
  @{ name = 'mcp-wall-oauth';     target = $gw.wall;     auth = 'oauth2'; scope = (Get-Scope 'wall' @('Tools.Read')) }
  @{ name = 'mcp-actions-oauth';  target = $gw.actions;  auth = 'oauth2'; scope = (Get-Scope 'actions' @('Tools.Read', 'Tools.Execute')) }
  @{ name = 'mcp-vendor-oauth';   target = $gw.vendor;   auth = 'oauth2'; scope = (Get-Scope 'vendorgw' @('Tools.Read')) }
  @{ name = 'mcp-private-oauth';  target = $apps.apps.private.url; auth = 'oauth2'; scope = (Get-Scope 'private' @('Tools.Read')) }
  @{ name = 'mcp-legacy-key';     target = $apis.legacyUrl; auth = 'custom-keys' }
)

$projArmBase = "https://management.azure.com/subscriptions/$($cfg.subscriptionId)/resourceGroups/$($cfg.rgName)/providers/Microsoft.CognitiveServices/accounts/$($names.foundry)/projects/$($names.project)/connections"
$apiVer = '2025-06-01'

function Get-ConnectionArm([string]$Name) {
  $raw = & az rest --method get --url "$projArmBase/$($Name)?api-version=$apiVer" -o json 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
  ($raw | Out-String) | ConvertFrom-Json
}

$legacyKey = $null
$result = [ordered]@{}
foreach ($s in $specs) {
  $existing = Get-ConnectionArm $s.name
  if ($existing -and -not ($Force -or $Only -contains $s.name)) {
    Write-Ok "$($s.name) exists - skipping (use -Force or -Only to re-create)"
  } else {
    Write-Step "creating connection $($s.name) -> $($s.target)"
    $azdArgs = @('ai', 'connection', 'create', $s.name, '--kind', 'remote-tool', '--target', $s.target, '--force',
                 '-p', $projectEndpoint, '--no-prompt', '-o', 'json')
    if ($s.auth -eq 'oauth2') {
      $azdArgs += @('--auth-type', 'oauth2', '--client-id', $ent.clients.agent.appId, '--client-secret', $agentSecret,
                    '--authorization-url', $authUrl, '--token-url', $tokenUrl, '--refresh-url', $tokenUrl, '--scopes', $s.scope)
    } else {
      if (-not $legacyKey) {
        $legacyKey = (& az rest --method post --url "https://management.azure.com/subscriptions/$($cfg.subscriptionId)/resourceGroups/$($cfg.rgName)/providers/Microsoft.ApiManagement/service/$($names.apim)/subscriptions/$($apis.legacySubscriptionName)/listSecrets?api-version=2024-06-01-preview" --query primaryKey -o tsv).Trim()
        if (-not $legacyKey) { throw 'could not read the legacy APIM subscription key' }
      }
      $azdArgs += @('--auth-type', 'custom-keys', '--custom-key', "Ocp-Apim-Subscription-Key=$legacyKey")
    }
    $out = & azd @azdArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
      $msg = ($out | Out-String) -replace [regex]::Escape($agentSecret), '<secret>'
      if ($legacyKey) { $msg = $msg -replace [regex]::Escape($legacyKey), '<key>' }
      throw "azd ai connection create $($s.name) failed: $msg"
    }
    $existing = Get-ConnectionArm $s.name
    Write-Ok "$($s.name) created"
  }
  if (-not $existing) { throw "connection $($s.name) not found after create" }
  $p = $existing.properties
  $result[$s.name] = [ordered]@{
    target       = $p.target
    authType     = $p.authType
    scopes       = $p.scopes
    redirectUrl  = $p.redirectUrl
    connectionId = $existing.id
  }
}
Save-Json (Join-Path $gen 'connections.json') $result
Write-Ok "connections.json written ($($result.Count) connections)"

$redirects = @($result.Values | Where-Object { $_.redirectUrl } | ForEach-Object { $_.redirectUrl } | Select-Object -Unique)
if ($redirects.Count -gt 0 -and -not $SkipEntraRedirects) {
  Write-Step "registering $($redirects.Count) Foundry consent redirect URL(s) on abw-agent-client"
  & "$script:RepoRoot\identity\Setup-Entra.ps1" -Phase 2 -AgentClientRedirectUris $redirects
}
