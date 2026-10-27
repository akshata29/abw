# Vendored template: Foundry Agent Service, standard setup + private networking

Upstream: `Azure-Samples/foundry-samples` → `infrastructure/infrastructure-setup-bicep/19-private-network-agent-tools`
(network-secured Agent Service, BYO Cosmos/Storage/Search, delegated agent subnet). Copied here so the demo is
reproducible and pinned. **Nothing below weakens the upstream security posture except where marked ⚠.**

## Why patched
The upstream sample creates its own VNet/subnets/DNS zones and derives resource names from a random suffix. The demo needs to
(a) re-use the VNet, subnets and private DNS zones created by `..\01-network.bicep`, (b) use CAF-style names, (c) keep the Foundry
front door reachable from the presenter's laptop/portal (Entra-only, keys disabled) while the agent runtime is still injected
into the delegated subnet, and (d) deploy Log Analytics / App Insights / AMPLS under predictable names for the governance stage.

## Patches

### `main.bicep`
- Banner + `uniqueSuffix` is now a 4-char parameter (`u4` from `infra\generated\config.json`).
- Name overrides: `accountNameOverride`, `projectNameOverride`, `cosmosDBNameOverride`, `aiSearchNameOverride`, `azureStorageNameOverride`.
- `modelDeploymentName` (so the agent code refers to a stable name, `gpt-54-mini`).
- ⚠ `foundryPublicNetworkAccess` (default `Enabled`; set `Disabled` for the "fully private" scene). Local/key auth stays **disabled** (`disableLocalAuth: true`),
  so a reachable front door still requires an Entra token + Azure RBAC.
- `logAnalyticsName`, `appInsightsName`, `amplsName`; ⚠ `amplsIngestionAccessMode` (default `Open`) and `disablePublicIngestion` (default `false`) so the
  Container Apps / APIM / the laptop can still send telemetry to App Insights during the demo.
- `searchSkuName` (default `basic`) and `searchDisableLocalAuth` (default `true`) for the agent-state Search service.
- ⚠ searchLocation (default empty = account region): the BYO Search service may live in a different region than the VNet. **Added on build day because East US 2 returned `InsufficientResourcesAvailable` for new Azure AI Search services (Basic and Standard)**; the Foundry docs explicitly allow Cosmos/Search/Storage in a different region from the VNet-bound account. The private endpoint stays in the VNet region (the PE module uses `resourceGroup().location`), so traffic remains private end-to-end.
- Extra outputs: account/project name, id, endpoint and principalId; model deployment name; BYO store names; App Insights / Log Analytics / AMPLS ids.

### `modules-network-secured/ai-account-identity.bicep`
- Params `modelDeploymentName` and `publicNetworkAccess`; `networkAcls.defaultAction` follows the public-access switch; deployment name uses `modelDeploymentName`; outputs `modelDeploymentName`.

### `modules-network-secured/standard-dependent-resources.bicep`
- Search: `searchSkuName`, `searchDisableLocalAuth` (when local auth is disabled the `authOptions` block is omitted), `searchLocation` (region override, see above).

### `modules-network-secured/monitor-private-link-scope.bicep`
- Params `amplsName`, `ingestionAccessMode`; private endpoint named `${amplsName}-pe`.

## Parameters the demo passes (see `scripts\deploy.ps1` → `foundry` stage)
Existing VNet/subnet ids + `existingDnsZones` (all in the demo resource group, so the template *references* instead of creating and does not touch VNet links),
`enableKeyVault=false`, `enableContainerRegistry=false`, model `gpt-5.4-mini` / `2026-03-17` / `GlobalStandard` / capacity 100.

## Updating
Diff against upstream before re-vendoring. Patches are small and localized; keep this file in sync.
