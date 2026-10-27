[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [Index, section 0 (About this document) and section 1 (Executive summary)](../ARCHITECTURE-AND-DESIGN.md) | Next: [3. Infrastructure and network design](03-infrastructure-and-network.md)

## 2. System overview

**What this section proves.** Agents Behind the Wall (workload code `abw`) is a self-contained Azure reference platform in which an AI agent calls tools on behalf of a signed-in user, and every hop between the user and the data is checked by something other than the model (**Designed**: `DESIGN.md:9-11#identity`). This section inventories the components, groups them into four planes, lists the trust boundaries and the four walls, and explains the naming and configuration conventions and the limits on where a copy of the platform can run. Network, deployment, identity and operations are covered in depth in sections 3, 4, 5 and 13.

Provenance labels used throughout this document: **Implemented** (application or script code), **Configured** (Bicep, policy XML or JSON), **Designed** (intent as written in DESIGN.md, README.md and docs/), and **Platform behaviour** (Azure or Entra behaviour confirmed on Microsoft Learn; the URL is written as plain text). Anything that is not in the repository is marked "not in this repo".

### 2.1 Purpose and design principles

**What this section proves.** The platform exists to show that agent tool use can be governed by identity and policy at the tool boundary instead of by prompts. The five principles below are the tests every component is held to.

The thesis in the design contract is that keys bypass Conditional Access, and that a missing user context bypasses data-level RBAC and every audit trail you own, so the identity chain (user, agent, gateway, tool, data) is what has to be fixed (**Designed**, `DESIGN.md:9-11#identity`). The whole estate is a fictional firm with fictional tickers and fake deal data (**Designed**, `DESIGN.md:4-5#synthetic`).

| # | Principle | What it means in this platform | Basis and evidence |
|---|---|---|---|
| 1 | Keyless | No account keys or SAS tokens on the platform's own services: Storage has shared-key access off, Cosmos DB, AI Search and Foundry have local (key) auth disabled, ACR has its built-in registry user off. Callers use Entra tokens and managed identities. The exceptions are listed in 13.5 (the external vendor key, the legacy POC subscription key, the OAuth client secret, the App Insights connection string). | **Configured**: `infra/03-platform.bicep:122-146#allowSharedKeyAccess`, `infra/03-platform.bicep:205-236#disableLocalAuth`, `infra/03-platform.bicep:302-322#disableLocalAuth`, `infra/03-platform.bicep:108-120#acr`, `infra/foundry/modules-network-secured/ai-account-identity.bicep:23-54#disableLocalAuth`. **Designed**: `DESIGN.md:17#Entra` |
| 2 | On-behalf-of | The data plane sees the user, not the server. The four token-validating MCP servers (research, wall, actions, private) validate the caller's token, then exchange it (OBO) for a Storage, Cosmos DB or Search token using a client assertion signed for their own managed identity - no client secret. Azure RBAC decides whether the user may reach each store; the server's own checks (app roles, the restricted list, query filters) narrow what it returns. | **Implemented**: `src/mcp/abw_mcp/obo.py:39-79#OboBroker`, `src/mcp/abw_mcp/auth.py:108-170#verify_token`, `src/mcp/abw_mcp/app.py:73-77#OboBroker`. **Designed**: `DESIGN.md:102-105#OBO` |
| 3 | Governance at the tool level | The unit of control is the MCP tool call, not the prompt. Gateway policy, server role checks, per-tool rules and data-plane RBAC decide; the model only helps the user phrase a request. | **Designed**: `DESIGN.md:28-33#abw-agent-guardrails`, `README.md:150#control` |
| 4 | Defence in depth | Four layers ("walls") deny on their own, so a failure or bypass of one does not open the data. Azure Policy and observability span all four. | **Designed**: `DESIGN.md:28-35#Cross-cutting` |
| 5 | Synthetic data only | Fictional firm, tickers, research notes and deal documents; the resource group and the network, platform, apps, API Management, seed, observability and jump box stages carry the tag `data = synthetic`, while the vendored Foundry stage passes no tags. | **Implemented**: `scripts/common.ps1:54#synthetic`, `scripts/deploy.ps1:222#tags`, `scripts/deploy.ps1:304#tags`. **Designed**: `DESIGN.md:4-5#synthetic` |

**Why.** A key or a service identity that is broader than the caller is exactly how a "typical POC" leaks data, so the repository deploys that anti-pattern deliberately (`abw-poc-legacy`, the `/legacy` API and a broad managed identity) next to the governed path, to make the contrast provable (**Configured**, `infra/03-platform.bicep:569-601#raLegacyBlob`; **Implemented**, `src/agent/abw_agents.py:142-152#poc_tools`).

**Trade-off / limitation.** On-behalf-of needs the user's token to stay alive across every hop. Foundry holds a user's token for its whole life, so a role change reaches the agent only when that token expires (**Designed**, `README.md:141#Foundry`). Access tokens live 60-90 minutes, and the README says that custom APIs get no continuous access evaluation, which this document has not verified (**Designed**, `README.md:141#CAE`).

### 2.2 Component inventory

**What this section proves.** Every runtime component, the Azure resource type behind it and the file that declares it. Unless a row says otherwise, the "Defined in" column is **Configured** (Bicep). Names use the placeholders explained in 2.6.

| Component | Role | Azure resource type | Defined in | Notes |
|---|---|---|---|---|
| Foundry account | Model host and Agent Service front door. Entra only (local auth disabled); the agent runtime is injected into the VNet. | `Microsoft.CognitiveServices/accounts` (kind AIServices, S0) | `infra/foundry/modules-network-secured/ai-account-identity.bicep:23-54#allowProjectManagement` | Vendored, patched upstream template (`infra/foundry/PATCHES.md:3#foundry-samples`). `aif-abw-demo-<region>-<u4>`. Public endpoint stays enabled for the presenter, see 3.4. |
| Foundry project | Holds the connections, agents and capability host. | `Microsoft.CognitiveServices/accounts/projects` | `infra/foundry/modules-network-secured/ai-project-identity.bicep:37-43#SystemAssigned` | `proj-abw-wall-<u4>`. Three bring-your-own connections (Cosmos DB, Storage, AI Search) use Entra auth: `infra/foundry/modules-network-secured/ai-project-identity.bicep:49-91#project_connection_cosmosdb_account`. |
| Model deployment | The chat model the agents run on (GlobalStandard, capacity 100). | `Microsoft.CognitiveServices/accounts/deployments` | `infra/foundry/modules-network-secured/ai-account-identity.bicep:57-71#deployments` | Model and capacity are passed by the foundry stage: `scripts/deploy.ps1:251-256#model`. |
| Agent capability host | Enables the Agents runtime for the project. | `Microsoft.CognitiveServices/accounts/projects/capabilityHosts` (kind Agents) | `infra/foundry/modules-network-secured/add-project-capability-host.bicep:22-30#capabilityHosts` | Deleted explicitly at teardown (`scripts/teardown.ps1:148-162#capability`). |
| Agent Service state stores (3) | Foundry's own thread, file and vector state, kept apart from the demo data. | Cosmos DB, Storage, AI Search | `infra/foundry/modules-network-secured/standard-dependent-resources.bicep:49-71#cosmos` | `cosmos-abw-asvc-<region>-<u4>`, `stabwasvc<u4>`, `srch-abw-asvc-<region>-<u4>` (`scripts/common.ps1:171-173#asvcStorage`). Search placement: `infra/foundry/modules-network-secured/standard-dependent-resources.bicep:82-107#search`. |
| Foundry agents (4) | `abw-poc-legacy` (v0 typical POC), `abw-wall-desk` (v1 governed), `abw-wall-desk-redteam`, `abw-wall-desk-redteam-shielded`. | Not ARM resources: agent versions in the project data plane | **Implemented**: `src/agent/abw_agents.py:35-39#SHIELDED_AGENT`, `src/agent/abw_agents.py:155-194#publish`, `src/agent/create_agents.py:34-40#AIProjectClient` | Detailed in the agent table below. |
| API Management | The enterprise gateway for four governed MCP servers, the keyed legacy contrast, discovery documents and the agent front door. | `Microsoft.ApiManagement/service` (StandardV2, capacity 1, system-assigned identity) | `infra/05-apim.bicep:43-63#StandardV2` | `apim-abw-demo-<region>-<u4>`. Outbound VNet integration plus an inbound private endpoint; the public gateway stays on (`infra/05-apim.bicep:57-61#virtualNetworkType`). |
| APIM APIs | Five MCP-type APIs (`research`, `wall`, `actions`, `vendor`, `legacy`), the discovery API and the agent front door. | `Microsoft.ApiManagement/service/apis` | `infra/05-apim-apis.bicep:123-147#mcpApis`, `infra/08-agent-frontdoor.bicep:49-64#api` | Policies rendered from `infra/apim/policies/*.policy.xml` (see 3.6). |
| API Center | Catalogue of the gateway's APIs (Free tier). | `Microsoft.ApiCenter/services` | `infra/05-apim.bicep:236-247#apic` | Imports from APIM (`infra/05-apim.bicep:277-290#apicSource`). |
| Container Apps env, internal | Hosts five MCP servers (research, wall, actions, private, legacy). No public endpoint. | `Microsoft.App/managedEnvironments` (workload profiles, internal) | `infra/03-platform.bicep:377-397#caePriv` | `cae-abw-priv-<region>-001`, infrastructure subnet `snet-mcp`. |
| Container Apps env, public | Hosts only the simulated external vendor MCP server. | `Microsoft.App/managedEnvironments` | `infra/03-platform.bicep:399-416#caePub` | `cae-abw-pub-<region>-001`; no VNet configuration. Policy exemption: `infra/06-governance.bicep:296-307#exPublicEnv`, whose text also names the legacy POC server as a tenant of this env although the legacy app is deployed in the internal env (`infra/06-governance.bicep:304#legacy`, `infra/04-apps.bicep:146-164#legacy`); the root README also lists all six servers under the internal env (`README.md:44#internal`). |
| MCP servers (6) | research, wall, actions, private (positions and credit limits), vendor (mock), legacy. One image, behaviour chosen by `MCP_SERVER`. | `Microsoft.App/containerApps` | `infra/04-apps.bicep:86-130#research`, `infra/04-apps.bicep:131-190#privateMcp`, `infra/modules/mcp-app.bicep:1-2#MCP_SERVER` | `ca-abw-mcp-<server>`; one user-assigned identity per server. Detailed in 3.5. |
| Seed job | Loads the synthetic documents, search index and Cosmos items from inside the VNet. | `Microsoft.App/jobs` (manual trigger) | `infra/04b-seed-job.bicep:101-156#seedJob` | Needed because the data planes are private-endpoint only (`infra/04b-seed-job.bicep:1-8#job`). |
| User-assigned identities (6 + seed) | One identity per MCP server, plus the seed job. | `Microsoft.ManagedIdentity/userAssignedIdentities` | `infra/03-platform.bicep:40-46#uamiKeys`, `infra/03-platform.bicep:74#uamis`, `infra/04b-seed-job.bicep:45#seedId` | Section 5.5. |
| Container Registry | Holds the single `abw-mcp` image (and the seed image); built with ACR Tasks. | `Microsoft.ContainerRegistry/registries` (Standard, built-in registry user off, public) | `infra/03-platform.bicep:108-120#acr` | Pulled by managed identity (`infra/03-platform.bicep:537-546#raAcrPull`). |
| Key Vault | Holds the one legacy static secret (the vendor API key) that the gateway reads as a named value. | `Microsoft.KeyVault/vaults` (RBAC mode, soft delete 7 days) | `infra/03-platform.bicep:81-105#kv`, `infra/04-apps.bicep:37-50#vendorKeySecret` | Firewall default Deny, NAT IP allowed, AzureServices bypass. Private endpoint `peKv`. |
| Storage | Research and wall documents, plus the immutable audit container. | `Microsoft.Storage/storageAccounts` (LRS, shared key off, public off) | `infra/03-platform.bicep:122-146#st`, `infra/03-platform.bicep:162-203#cWorm` | Containers `research-public`, `wall-falcon`, `wall-orion`, `worm-audit`. |
| Cosmos DB | Restricted list, orders and positions. | `Microsoft.DocumentDB/databaseAccounts` (serverless, local auth off, public off) | `infra/03-platform.bicep:205-236#cosmos`, `infra/03-platform.bicep:237-300#cosmosDb` | Database `abw`; containers `restricted`, `orders`, `positions`. |
| AI Search | Keyword index `deals-idx` over the research and deal documents. | `Microsoft.Search/searchServices` (Basic, local auth off, public off) | `infra/03-platform.bicep:302-322#search` | Region may differ from the VNet region (3.10). |
| Private endpoints | Private paths to Storage, Cosmos DB, Search, Key Vault, the APIM gateway, and the Foundry account and its dependencies. | `Microsoft.Network/privateEndpoints` | `infra/modules/pe.bicep:19#pe`, `infra/03-platform.bicep:324-376#peBlob`, `infra/05-apim.bicep:65-76#apimPe` | Section 3.2. |
| VNet, subnets, NSGs | Network boundary (10.42.0.0/16). | `Microsoft.Network/virtualNetworks`, `networkSecurityGroups` | `infra/01-network.bicep:148-221#vnet`, `infra/01-network.bicep:65-115#apimNsg` | Section 3.1. |
| NAT gateway | The only Internet egress for `snet-mcp`, `snet-apim` and `snet-jump`. | `Microsoft.Network/natGateways`, `publicIPAddresses` | `infra/01-network.bicep:117-146#natGateway` | Section 3.3. |
| Private DNS zones (14 plus one for the internal ACA env) | Name resolution to the private endpoints. | `Microsoft.Network/privateDnsZones` | `infra/01-network.bicep:48-63#dnsZoneNames`, `infra/modules/aca-dns.bicep:18-37#zone` | Section 3.2. |
| Log Analytics, App Insights | Workspace-based telemetry store for gateway, container, Foundry and audit data. | `Microsoft.OperationalInsights/workspaces`, `Microsoft.Insights/components` | `infra/foundry/modules-network-secured/application-insights.bicep:33-54#PerGB2018` | Declared by the vendored template; the platform references them as existing (`infra/03-platform.bicep:65-72#law`). |
| Azure Monitor Private Link Scope | Private path for Azure Monitor. | `Microsoft.Insights/privateLinkScopes` | `infra/foundry/modules-network-secured/monitor-private-link-scope.bicep:59-68#queryAccessMode` | Ingestion left open by patch (`infra/foundry/PATCHES.md:15-25#amplsIngestionAccessMode`). |
| Diagnostic settings | Send platform logs to Log Analytics. | `Microsoft.Insights/diagnosticSettings` | `infra/03-platform.bicep:428-463#diagCaePriv`, `infra/06-governance.bicep:102-159#diagFoundry`, `infra/05-apim.bicep:154-176#apimDiag` | Section 3.8. |
| Microsoft Sentinel | SIEM on the workspace: nine analytics rules ABW-001 to ABW-009. | `Microsoft.SecurityInsights/onboardingStates`, `alertRules` | `infra/06b-observability.bicep:60-64#sentinel`, `infra/06b-observability.bicep:67-106#analyticsRules` | Rules are built from `observability/sentinel/` by `build_rules.py`. |
| KQL function pack, alerts, workbook | Ten saved-search functions, three ops alert rules, the cockpit workbook. | `Microsoft.OperationalInsights/workspaces/savedSearches`, `scheduledQueryRules`, `Microsoft.Insights/workbooks` | `infra/06b-observability.bicep:43-57#functions`, `infra/06b-observability.bicep:126-151#opsAlerts`, `infra/06b-observability.bicep:193-205#cockpit` | Section 4.7. |
| Azure Policy initiative | A baseline of 19 policy references in five control families (the initiative's own description calls it a twelve-control baseline): no keys, private by default, approved tools and models, guardrails, hygiene. | `Microsoft.Authorization/policySetDefinitions`, `policyDefinitions` (2 custom), `policyAssignments`, `policyExemptions` | `infra/06a-policy-definitions.bicep:168-172#initiative`, `infra/06-governance.bicep:177-183#assignment` | Definitions and initiative are subscription-scope objects; the assignment is resource-group scope (2.7). |
| Foundry guardrail | RAI policy `abw-agent-guardrails`: jailbreak and indirect-attack shields, harm categories. Preview. | `Microsoft.CognitiveServices/accounts/raiPolicies` | `infra/06-governance.bicep:86-99#guardrails` | Layer 0 (2.5). |
| Agent front door | APIM API `/agents` that validates the user token, applies kill switch, per-user rate limit and token budget. | APIM API and named values | `infra/08-agent-frontdoor.bicep:15-64#tokenQuotaPerHour` | Additive (stage `frontdoor`). |
| Budget | Monthly cost budget with alerts at 50, 80, 100 percent actual and 100 percent forecast. An alert, not a cap. | `Microsoft.Consumption/budgets` | `infra/09-budget.bicep:24-31#budget`, `infra/09-budget.bicep:33-70#notifications` | USD 1,200 per month default (`infra/09-budget.bicep:14#monthlyBudgetUsd`). |
| Jump box | Windows Server 2022 VM inside the VNet from which the console and the portal data pages are shown over private endpoints. | `Microsoft.Compute/virtualMachines` | `infra/07-jumpbox.bicep:153-208#vm` | Optional. Subnet `snet-jump` (10.42.4.0/27). Section 3.9. |
| Azure Bastion | Browser RDP to the jump box without a public IP. | `Microsoft.Network/bastionHosts` (Developer SKU) | `infra/07-jumpbox.bicep:230-241#bastion` | Developer SKU is free and a shared pool (Platform behaviour: https://learn.microsoft.com/azure/bastion/bastion-overview#skus). |
| Demo Console | Presenter UI: scenes, proofs, scoreboard, evidence boards. Local app bound to 127.0.0.1, runs on the laptop or on the jump box; not an Azure resource. | Not in Azure (Python Starlette app) | **Implemented**: `console/server.py:418-434#main`, `scripts/jumpbox-console.ps1:7-10#127.0.0.1` | Uses the operator's own `az` sign-in tokens (`console/azure_probe.py:73-89#token`). |
| Entra objects | Six groups, five API apps, two client apps, five persona users. | Microsoft Entra (Graph, not ARM) | **Implemented**: `identity/Setup-Entra.ps1:29-61#$Apis` | Section 5. |

The four Foundry agents, the tools each may call and whether the guardrail is attached:

| Agent | Tools (servers) | Approval gate | Guardrail | Purpose | Source |
|---|---|---|---|---|---|
| `abw-poc-legacy` (v0) | `legacy` only, through connection `mcp-legacy-key`, no tool filter | none | no | The typical POC: one shared APIM subscription key | `src/agent/abw_agents.py:142-152#poc_tools`, `src/agent/abw_agents.py:159-165#POC_AGENT` |
| `abw-wall-desk` (v1) | 12 allow-listed tools on 5 servers: research (2), wall (3), actions (3), private (2), vendor (2), each through its own OAuth connection `mcp-<server>-oauth` | `place_order` always needs approval | yes, when `--rai` is passed | The governed agent | `src/agent/abw_agents.py:42-49#WALL_DESK_TOOLS`, `src/agent/abw_agents.py:119-139#wall_desk_tools`, `src/agent/abw_agents.py:170-176#WALL_AGENT` |
| `abw-wall-desk-redteam` | same tools and connections as v1 | same | no | Deliberately over-compliant prompt, to prove the walls hold when the model is the weak link | `src/agent/abw_agents.py:70-76#REDTEAM_INSTRUCTIONS`, `src/agent/abw_agents.py:178-184#REDTEAM_AGENT` |
| `abw-wall-desk-redteam-shielded` | same as red-team | same | yes; published only with `--rai` | Red-team prompt plus the guardrail | `src/agent/abw_agents.py:186-193#SHIELDED_AGENT` |

The agents are published by `src/agent/create_agents.py`, which signs in with the operator's Azure CLI credential and writes the ids to `agents.json` in the generated-state folder (**Implemented**, `src/agent/create_agents.py:34-44#AzureCliCredential`). A guardrail is attached by its fully qualified ARM id; the helper expands a bare guardrail name to the id under the Foundry account, because the service rejects a bare name (**Implemented**, `src/agent/abw_agents.py:83-87#rai_policy_id`).

### 2.3 The four planes

**What this section proves.** The platform is easier to audit when you separate what changes it (deployment), who may act (identity), where the data and the tool calls travel (data) and what proves what happened (observability). The repository uses "data plane" and "control plane" only in the Azure sense; the four-plane grouping is an organising device of this document, and each plane is built from the components in 2.2.

Diagram: docs/diagrams/01-system-architecture.excalidraw

| Plane | What flows | Principals and initiators | Components | Evidence |
|---|---|---|---|---|
| Deployment and control | Bicep deployments, container image builds, Foundry connection and agent creation, policy and observability artefacts, jump box setup. State is captured as JSON files under the generated-state folder. | The operator, from a Windows workstation with PowerShell 7, Azure CLI, Python and azd. Owner on the subscription plus the rights to create Entra apps (**Designed**, `README.md:48-52#Owner`). | `scripts/deploy.ps1` stages, `scripts/build-images.ps1`, `scripts/foundry-connections.ps1`, `src/agent/create_agents.py`, `scripts/jumpbox*.ps1` | **Implemented**: `scripts/deploy.ps1:79-113#Invoke-Stage`, `scripts/build-images.ps1:34#--platform`, `scripts/foundry-connections.ps1:85-89#azdArgs` |
| Identity | User sign-in tokens and their exchange: user token for Foundry, delegated per-connection token for an MCP API, on-behalf-of token for a data plane; federated credentials let a managed identity act as an Entra app without a secret. | The persona users, the client apps `abw-agent-client` and `abw-test-client`, five API apps, six managed identities. | Entra objects from `identity/Setup-Entra.ps1`; identities in `infra/03-platform.bicep` | **Implemented**: `identity/Setup-Entra.ps1:29-45#$Apis`, `identity/Setup-Entra.ps1:258-286#federated`. **Designed**: `DESIGN.md:102-105#OBO` |
| Data | The agent's tool calls (MCP over HTTPS) and the data they read or write. Everything between the Foundry agent runtime and the data stores is private-endpoint or VNet traffic. The deliberate Internet-bound hops are the gateway's call to the simulated vendor and the gateway's and MCP servers' calls to Entra and Azure Monitor, which leave through the NAT gateway on `snet-mcp` and `snet-apim`; `snet-agent` has no NAT. | The Foundry agent runtime (injected in `snet-agent`), APIM (VNet-integrated), the MCP servers in the internal ACA env, the seed job. | Storage, Cosmos DB, AI Search behind private endpoints (`infra/03-platform.bicep:324-376#peBlob`); the MCP servers (`infra/04-apps.bicep:53-66#commonEnv`) | **Configured**: `infra/03-platform.bicep:122-146#publicNetworkAccess`, `infra/03-platform.bicep:205-236#publicNetworkAccess`, `infra/03-platform.bicep:302-322#publicNetworkAccess`, `infra/01-network.bicep:98-111#allow-out-internet-443`, `infra/01-network.bicep:183-206#natGateway` |
| Observability | Gateway decision traces and metrics, container console logs with one JSON audit event per decision, an append-only audit blob, Foundry and Azure diagnostics, correlation by `request_id`. | The APIM logger, the MCP servers, Azure diagnostic settings, Sentinel. | Log Analytics, App Insights, ten KQL functions, nine Sentinel rules, three alerts, the cockpit workbook | **Configured**: `infra/05-apim.bicep:92-137#diagAppi`, `infra/06b-observability.bicep:43-57#functions`, `infra/06b-observability.bicep:67-106#analyticsRules`. **Implemented**: `src/mcp/abw_mcp/audit.py:54-130#AppendBlobAuditSink` |

The runtime token chain that crosses the identity and data planes has four hops (**Designed**, `DESIGN.md:102-105#OBO`):

1. The user signs in and gets a Foundry token (`aud` claim `https://ai.azure.com`).
2. Foundry's OAuth identity passthrough, after a one-time consent per connection, obtains a token for the target MCP API using the client app `abw-agent-client`.
3. APIM validates the JWT, applies claim authorization, kill switch, client allow-list and rate limit, then calls the MCP backend inside the VNet.
4. The token-validating MCP server (research, wall, actions or private) re-validates the JWT and then does the on-behalf-of exchange, using a client assertion that is the managed identity's token for `api://AzureADTokenExchange`, to reach Storage, Cosmos DB or Search as the user.

Two paths deliberately differ (**Designed**, `DESIGN.md:107-110#Direct`): the private MCP server is reached directly from the injected agent subnet and validates the token itself, never touching APIM; the vendor path goes through APIM, which swaps the user's token for the vendor key; the legacy path uses one shared subscription key.

**Why.** Separating the planes lets each be restricted separately: the control plane needs Owner and Entra rights only while deploying, the identity plane holds only the standing secrets listed in 13.5, the data stores (Storage, Cosmos DB, Search) have public network access disabled, and the observability plane is written to by the same components it audits but read by a separate InfoSec group (5.1).

**Trade-off / limitation.** The deployment plane is a laptop script chain, not a pipeline: state lives in local JSON files in a git-ignored folder (`.gitignore:5#generated`), so a second operator must copy that folder or rebuild it (4.2).

### 2.4 Trust boundaries

**What this section proves.** Each boundary below names who trusts whom and what the receiving side verifies. A bypass of one boundary is caught by the next because each receiving side re-checks instead of trusting the hop.

Diagram: docs/diagrams/13-trust-boundaries-and-failure-modes.excalidraw

| # | Boundary (caller -> callee) | What the callee verifies | Does not trust | Basis and evidence |
|---|---|---|---|---|
| B1 | Presenter or operator -> Foundry | Entra sign-in; Azure RBAC: the operator has Foundry User on the account, the all-users group has Agent Consumer on the project; keys are disabled. | Any caller without an Entra token | **Configured**: `infra/02-foundry-rbac.bicep:26-47#raOperatorAccount` |
| B2 | Foundry agent runtime -> gateway or private MCP | The agent carries the user's own delegated token, one `aud` value per connection (OAuth identity passthrough, client app `abw-agent-client`). | The agent or the model choosing an identity: a tool call runs as the signed-in user | **Implemented**: `scripts/foundry-connections.ps1:6-14#custom` ; `src/agent/abw_agents.py:129-137#project_connection_id` |
| B3 | APIM -> internal Container Apps env | JWT validation at the gateway: signature, issuer, `aud`, expiry, tenant; scope or app role; client allow-list (`azp`); kill switch by `oid`; per-`oid` rate limit. | Backend TLS validation is off for the internal ACA env by default. | **Configured**: `infra/apim/policies/mcp-jwt.policy.xml:17-46#validate-jwt`, `infra/05-apim-apis.bicep:22#validateInternalTls` |
| B4 | Gateway or agent -> MCP server | Each of the four token-validating servers (research, wall, actions, private) re-validates the token (RS256 signature from the tenant keys, audience, issuer, expiry, version 2.0, tenant, `azp` allow-list, required scope) and rejects app-only tokens. Roles are carried in the caller record but checked later, per tool (`src/mcp/abw_mcp/registry.py:98-121#require_any_role`). | The hop: a caller that bypasses APIM still needs a valid user token. | **Implemented**: `src/mcp/abw_mcp/auth.py:108-170#verify_token` |
| B5 | MCP server -> Entra (on-behalf-of) | Entra accepts the managed identity's token as the app's credential only if a federated credential matches issuer, subject (the identity's principal id) and `aud` `api://AzureADTokenExchange`. | A server impersonating another: each app trusts exactly one identity. | **Implemented**: `src/mcp/abw_mcp/obo.py:39-79#OboBroker`, `identity/Setup-Entra.ps1:262-276#AzureADTokenExchange`. **Platform behaviour**: https://learn.microsoft.com/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity |
| B6 | MCP server -> data plane (as the user) | Azure RBAC evaluated per request on the user's identity: container-level blob roles, Cosmos DB data-plane roles per container, a search index data role. | The server's own permissions: the research, wall and actions servers have no broad data roles. | **Configured**: `infra/03-platform.bicep:618-649#raResearchBlob`, `infra/03-platform.bicep:650-700#cosmosTradersOrders` |
| B7 | APIM -> vendor MCP server (public ACA env) | APIM validates the user token, deletes the Authorization header and injects the vendor key from a Key Vault named value; the vendor mock checks the key in constant time. | The vendor never sees a user token. | **Configured**: `infra/05-apim-apis.bicep:75-91#vendorSection`. **Implemented**: `src/mcp/abw_mcp/app.py:115-142#VendorKeyMiddleware` |
| B8 | Legacy path (contrast) | A shared APIM subscription key and nothing per user; the server runs with a broad identity. | n/a - this is the anti-pattern shown on purpose | **Configured**: `infra/05-apim-apis.bicep:169-210#legacyApi`, `infra/03-platform.bicep:569-601#raLegacyBlob` |
| B9 | Operator -> Azure control plane | ARM RBAC. The operator gets Key Vault Administrator, AcrPush and Search Service Contributor (the first two are data-plane roles on the vault and the registry themselves) but no role on the data in Storage, Cosmos DB or the search index. | Subscription Owner as a data role | **Configured**: `infra/03-platform.bicep:733-765#raOpKv` |
| B10 | Jump box -> VNet | Reached only through Bastion; the NSG allows RDP from the VNet and denies Internet inbound. | Direct RDP from the Internet | **Configured**: `infra/07-jumpbox.bicep:85-120#jumpNsg` |
| B11 | Presenter laptop -> Foundry and APIM public endpoints | Foundry public access is on but Entra-only; the APIM gateway stays public so the laptop and the proof scripts can call it; layer 1 protects it. A policy exemption records the Foundry exposure as Mitigated. | An unauthenticated caller | **Configured**: `infra/foundry/PATCHES.md:15-25#foundryPublicNetworkAccess`, `infra/05-apim.bicep:57-61#publicNetworkAccess`, `infra/06-governance.bicep:284-295#exFoundryNetwork` |
| B12 | MCP servers -> telemetry | The App Insights connection string is held as a Container App secret on all six apps; Azure Monitor ingestion is left open by patch. | n/a | **Configured**: `infra/04-apps.bicep:56#appi-conn`, `infra/04-apps.bicep:68-73#appiSecret` |

**Why.** The four token-validating servers (research, wall, actions, private) re-validate the token (B4) because the gateway is not the only way in: the private server has no gateway at all, and any future network mistake that exposes a backend must still meet a token check (**Designed**, `DESIGN.md:32#Re-validates`).

**Trade-off / limitation.** The private server (B2 direct path) sits outside APIM, so the gateway kill switch and gateway rate limit do not reach it (**Designed**, `DESIGN.md:107#private`, `README.md:149#kill`). Backend TLS from APIM to the internal ACA env is not validated unless `validateInternalTls` is set (`infra/05-apim-apis.bicep:22#validateInternalTls`).

### 2.5 The four walls at a glance

**What this section proves.** Three deterministic layers and one best-effort layer, each enforced in a different place and each able to refuse alone. The details, with the code paths and the proofs, are in section 7.

| Layer | Wall | Enforced where | What it checks | Nature | Source |
|---|---|---|---|---|---|
| 0 | Foundry guardrail | Foundry account, content-filter policy `abw-agent-guardrails` attached to the agent | Prompt shields (jailbreak, indirect attack in tool output), harm categories, protected material | Preview and probabilistic; a detective layer that feeds Sentinel rule ABW-008. Not the control. | **Configured**: `infra/06-governance.bicep:72-99#guardrails`. **Designed**: `DESIGN.md:30#Preview` |
| 1 | APIM gateway | One policy template (`mcp-jwt.policy.xml`) rendered per governed MCP API at API scope; the legacy API has its own policy file (`mcp-legacy.policy.xml`, rate limit only) | `validate-jwt` (signature, issuer, `aud`, expiry, tenant); client allow-list by `azp`; kill switch by `oid`; scope; an app role (waived only for discovery calls on the three servers whose `listOpen` is true); rate limit 120 calls per 60 s per user; sets `x-abw-request-id`; emits the decision metric and trace | Deterministic | **Configured**: `infra/apim/policies/mcp-jwt.policy.xml:17-46#validate-jwt`, `infra/apim/policies/mcp-jwt.policy.xml:42-44#discovery`, `infra/apim/policies/mcp-jwt.policy.xml:81#rate-limit-by-key`, `infra/apim/policies/mcp-legacy.policy.xml:8#rate-limit-by-key`, `infra/05-apim-apis.bicep:38#listOpen` |
| 2 | MCP server | The server process in a Container App | Re-validates the JWT; role-filtered `tools/list`; per-tool rules (restricted list, separation of duties, project crossing); one audit event per decision | Deterministic | **Implemented**: `src/mcp/abw_mcp/registry.py:98-108#require_any_role`, `src/mcp/abw_mcp/registry.py:132-156#list_tools`, `src/mcp/abw_mcp/servers/wall.py:29-47#caller_projects`, `src/mcp/abw_mcp/servers/actions.py:58-110#place_order` |
| 3 | Data plane | Azure Storage, Cosmos DB and AI Search RBAC on the on-behalf-of token | RBAC assignments for the user's groups, evaluated per request, so removing a group membership denies access even while the token still carries the old claim | Deterministic | **Configured**: `infra/03-platform.bicep:618-649#raResearchBlob`, `infra/03-platform.bicep:650-700#cosmosTradersOrders`. **Designed**: `DESIGN.md:33#evaluated` |
| Across | Azure Policy and observability | Subscription-scope definitions and initiative, resource-group assignment; KQL pack, Sentinel rules, workbook, alerts | Platform rules (no keys, private by default, approved MCP targets, models, guardrails, hygiene); detection and correlation of the four layers' decisions | Policy is mostly Deny; some controls Audit | **Configured**: `infra/06a-policy-definitions.bicep:168-172#initiative`, `infra/06b-observability.bicep:67-106#analyticsRules` |

**Why.** The model is not the control: the identity and policy checks at the tool boundary are deterministic, and the one model-adjacent layer is preview and best effort (**Designed**, `README.md:150#control`; **Configured**, `infra/06-governance.bicep:72-76#Preview`).

**Trade-off / limitation.** The guardrail fired on only some identical requests in the lab (1 in 11 to 5 in 8), so the proofs assert the wall's refusal and report the guardrail as a measured rate (**Designed**, `README.md:140#guardrail`).

### 2.6 Naming, tagging and configuration conventions

**What this section proves.** Most Azure resource names, plus the tags and the region choice, are derived from one configuration file by one function (`scripts/common.ps1:29-58#Get-AbwConfig`, `scripts/common.ps1:147-183#Get-AbwNames`), so scripts and Bicep agree and a second operator can reproduce the names. The exceptions are fixed in Bicep or in the Entra script (2.6.2).

#### 2.6.1 The configuration file

`Get-AbwConfig` reads `config.json` from the generated-state folder; if it does not exist it creates it from `az account show` and `az ad signed-in-user show`, then saves it (**Implemented**, `scripts/common.ps1:29-58#Get-AbwConfig`). The file is git-ignored (**Configured**, `.gitignore:5#generated`). Optional keys written by portable deployments override defaults through `Get-CfgValue` (**Implemented**, `scripts/common.ps1:23-27#Get-CfgValue`).

| Key | Meaning | Default or source |
|---|---|---|
| `tenantId`, `tenantDomain` | The Entra tenant and its domain, written as `<tenant-id>` and `<tenant-domain>` in this document | from `az account show` |
| `subscriptionId` | The deployment subscription, written `<subscription-id>` | from `az account show` |
| `location` | Region of the resource group and most resources | `eastus2` |
| `searchLocation` | Region of AI Search; may differ because Search capacity was unavailable in the primary region on build day, while the private endpoint stays in the VNet region | `eastus` (`scripts/common.ps1:45#searchLocation`) |
| `workload`, `env`, `instance` | Name parts | `abw`, `demo`, `001` |
| `regionCode` | Short region code used inside names, written `<region>` in this document | `eus2` for `eastus2` |
| `u4` | Four-character unique suffix for globally unique names, written `<u4>`. The orchestrator draws four random characters from a-z and 0-9 (or takes `-UniqueSuffix`), saves them in `config.json`, and draws a new suffix when a name is already taken; the `Get-AbwConfig` fallback, used when the stage scripts run without a config file, makes the letter `k` plus three random characters. Both draw from a cryptographic generator | `scripts/Deploy-AgentWall.ps1:228-231#New-UniqueSuffix`, `scripts/Deploy-AgentWall.ps1:802#UniqueSuffix`, `scripts/Deploy-AgentWall.ps1:932#New-UniqueSuffix`, `scripts/Deploy-AgentWall.ps1:1368#config.json`, `scripts/common.ps1:36-37#u4` |
| `rgName` | Resource group | `rg-abw-demo-<region>-001` |
| `operatorUpn`, `operatorOid` | The signed-in operator, written `<operator-upn>` and `<user-oid>` | from `az` |
| `tags` | Tags applied to the resource group and resources | see 2.6.3 |

#### 2.6.2 Name patterns

`Get-AbwNames` is the main source of names; its own comment calls it the "single source of truth" and says it "mirrors DESIGN.md section 2" (**Implemented**, `scripts/common.ps1:144-149#Get-AbwNames`). With `<region>` for the region code and `<u4>` for the suffix:

| Resource | Pattern | Why it carries the suffix |
|---|---|---|
| VNet, NAT gateway | `vnet-abw-demo-<region>-001`, `ng-abw-demo-<region>-001` | no |
| APIM NSG | `nsg-abw-apim-<region>-001` | no |
| Log Analytics, App Insights, private link scope | `log-abw-demo-<region>-001`, `appi-abw-demo-<region>-001`, `ampls-abw-demo-<region>-001` | no |
| Key Vault | `kv-abw-demo-<region>-<u4>` | global name |
| Container Registry | `crabwdemo<region><u4>` | global name |
| Storage account | `stabwdemo<region><u4>` | global name |
| Cosmos DB | `cosmos-abw-demo-<region>-<u4>` | global name |
| AI Search | `srch-abw-deals-<region>-<u4>` | global name |
| API Management, API Center | `apim-abw-demo-<region>-<u4>`, `apic-abw-demo-<region>-<u4>` | global name |
| Foundry account, project | `aif-abw-demo-<region>-<u4>`, `proj-abw-wall-<u4>` | global name |
| Agent Service stores | `stabwasvc<u4>`, `cosmos-abw-asvc-<region>-<u4>`, `srch-abw-asvc-<region>-<u4>` | global name |
| Container Apps envs | `cae-abw-priv-<region>-001`, `cae-abw-pub-<region>-001` | no |
| APIM private endpoint | `pe-apim-abw-demo-<region>-001` | no |
| Jump box | `nsg-abw-jump-<region>-001`, `vm-abw-jump-<region>-001`, `nic-abw-jump-<region>-001`, `osdisk-abw-jump-<region>-001`, `bas-abw-demo-<region>-001` | no |
| Budget | `budget-abw-demo-<region>-001` | no |
| Model deployment | `gpt-54-mini` unless `modelDeployment` is set | no |

These patterns are in `scripts/common.ps1:147-183#Get-AbwNames`. Names that are not produced by the function are fixed in Bicep: the user-assigned identities `id-abw-mcp-<server>-<region>-001` (`infra/03-platform.bicep:74#uamis`), the Container Apps `ca-abw-mcp-<server>` (`infra/04-apps.bicep:86-99#research`), the seed identity (`infra/04b-seed-job.bicep:45#seedId`) and the Entra objects, which carry fixed `abw-*` and `sg-abw-*` names (`identity/Setup-Entra.ps1:29-48#$Groups`). The fixed Entra names are what makes the one-deployment-per-tenant limit in 2.7.

Deterministic identifiers: `New-DetGuid` derives the ids of the OAuth scopes and app roles from a fixed string, so a re-run produces the same ids (**Implemented**, `scripts/common.ps1:137-141#New-DetGuid`; used at `identity/Setup-Entra.ps1:124-125#New-DetGuid`).

#### 2.6.3 Tags

The tags written at group creation are: `workload`, `env`, `owner` (derived from the signed-in user's alias), `purpose`, `data = synthetic`, and `delete-after` (today plus 45 days) (**Implemented**, `scripts/common.ps1:54#delete-after`). The preflight stage applies them when it creates the resource group (**Implemented**, `scripts/deploy.ps1:198-201#tagArgs`). Teardown never reads the group's tags. Its proof of ownership is the group named in `config.json`, custom policy objects whose name starts with `abw-`, and Entra objects tagged `abw-demo`, named `sg-abw-*` or carrying the demo company marker (**Implemented**, `scripts/teardown.ps1:18-20#abw-demo`). It refuses to run when `az` is signed in to a different subscription than the one in the config (`scripts/teardown.ps1:78-80#throw`) and asks for the group name to be typed unless `-Yes` is passed (`scripts/teardown.ps1:135-138#Confirmation`); see 4.10.

**Why.** Reading most names from one function removes drift between Bicep parameters, scripts and the console; the global-name suffix is generated once and persisted so re-runs and teardown address the same resources.

**Trade-off / limitation.** The suffix and the config live only in a git-ignored local file. Losing `config.json` while resources exist means the names can no longer be derived (the stage scripts would generate a new suffix), so back it up or recover it from the resource names.

### 2.7 Deployment-shape constraints

**What this section proves.** A copy of the platform has a fixed footprint in two shared namespaces - the Entra tenant and the Azure subscription - so only one deployment can exist in each.

| Constraint | Why | Consequence of a second deployment | Evidence |
|---|---|---|---|
| One deployment per Entra tenant | The Entra objects are tenant-wide with fixed names: five API apps, two client apps, six groups, five persona users. Setup finds them by display name and updates them in place. | The second run takes the first deployment's apps and groups over. Phase 2 replaces any federated credential whose subject differs, so the first deployment's managed identities would stop being accepted for on-behalf-of. | **Implemented**: `identity/Setup-Entra.ps1:112-118#displayName`, `identity/Setup-Entra.ps1:128-132#displayName`, `identity/Setup-Entra.ps1:265-276#subject`. **Designed**: `scripts/Deploy-AgentWall.ps1:23-24#tenant` |
| One deployment per Azure subscription | The custom policy definitions and the initiative are created at subscription scope with fixed names, including the initiative name that is also the assignment name. | The second run overwrites the definitions and the initiative that the first deployment's assignment points to. | **Configured**: `infra/06a-policy-definitions.bicep:19#targetScope`, `infra/06a-policy-definitions.bicep:168-170#abw-agent-platform-controls`, `infra/06-governance.bicep:177-183#assignment`; `scripts/deploy.ps1:439-451#policy-defs` |
| One Foundry/APIM/VNet in one region | APIM v2 outbound VNet integration and the inbound private endpoint need the VNet in the same region and subscription as the gateway. | The network, APIM and Container Apps envs are tied to one region. | **Platform behaviour**: https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview#networking-options |
| Windows operator workstation | The scripts require PowerShell 7 and are developed on Windows; there is no Docker dependency because images are built in ACR Tasks. | n/a | **Designed**: `README.md:48#Docker` |
| Human steps that cannot be scripted | Tenant-wide consent and the Foundry OAuth consent need the operator's browser; persona MFA enrolment is manual. | A fresh deployment is not unattended end to end. | **Designed**: `README.md:99#consent`, `README.md:92#Baseline` |

**Why.** The Entra objects are named, not parameterised, so that the proofs, the console and the Foundry connections can refer to fixed names (**Designed**, `DESIGN.md:85-98#abw-`). The cost of that choice is the single-copy limit; 13.4 treats it as a hazard.

**Trade-off / limitation.** Only the one-command orchestrator guards against a second copy. On a first Entra run (no `entra.json`, or `-ResetState`) it stops when `abw-*` apps, `sg-abw-*` groups or `abw.*` users already exist in the tenant, unless `-AdoptExistingEntra` is passed, and it only warns when the policy initiative already exists in the subscription (**Implemented**, `scripts/Deploy-AgentWall.ps1:950-965#Test-ExistingEntraDeployment`, `scripts/Deploy-AgentWall.ps1:967-986#Test-EntraTakeoverGuard`, `scripts/Deploy-AgentWall.ps1:988-992#Test-ExistingInitiative`, `scripts/Deploy-AgentWall.ps1:1316-1323#Test-EntraTakeoverGuard`). The stage scripts `identity\Setup-Entra.ps1` and `scripts\deploy.ps1` run no such check, so anyone who bypasses the orchestrator can still take over another deployment's objects (**Designed**, `scripts/Deploy-AgentWall.ps1:23-24#tenant`).

**Key takeaways**

- Five principles reduce to one: the tool call runs as the user, and every layer from the gateway to the data plane checks that identity again (`src/mcp/abw_mcp/auth.py:108-170#verify_token`, `infra/03-platform.bicep:618-649#raResearchBlob`).
- Three of the four walls are deterministic; the Foundry guardrail is preview and detective (`DESIGN.md:30#Preview`).
- Six MCP servers share one image `abw-mcp`; five run in an internal Container Apps env and only the vendor mock runs in the public one (`infra/04-apps.bicep:166-190#vendor`).
- The platform is one resource group of about 97 resources plus tenant-wide Entra objects and subscription-scope policy objects (`README.md:42#resources`, `infra/06a-policy-definitions.bicep:19#targetScope`).
- Most Azure resource names come from `Get-AbwNames` with a region code and a four-character suffix, which is why those placeholders appear in this document; the exceptions (managed identities, Container Apps, the seed identity and the Entra objects) are fixed in Bicep or the Entra script (`scripts/common.ps1:147-183#Get-AbwNames`).
- One deployment per Entra tenant and per subscription is a hard limit of the naming model (`identity/Setup-Entra.ps1:128-132#displayName`).

---

[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [Index, section 0 (About this document) and section 1 (Executive summary)](../ARCHITECTURE-AND-DESIGN.md) | Next: [3. Infrastructure and network design](03-infrastructure-and-network.md)
