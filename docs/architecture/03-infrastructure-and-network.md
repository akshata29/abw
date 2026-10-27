[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [2. System overview](02-system-overview.md) | Next: [4. Deployment architecture](04-deployment.md)

## 3. Infrastructure and network design

**What this section proves.** The estate is one VNet in one region with five purpose-built subnets. Storage, Cosmos DB and AI Search accept traffic only through private endpoints (PE); Key Vault has a PE and a firewall that admits one NAT address; ACR, the APIM gateway, the Foundry front door and the vendor Container Apps env are the documented public surfaces. The provenance labels (**Implemented**, **Configured**, **Designed**, **Platform behaviour**) are defined at the top of section 2 and names use the placeholders explained in 2.6. The address plan is a single 10.42.0.0/16 space (**Configured**, `infra/01-network.bicep:36-43#addressPrefix`).

### 3.1 VNet and subnets

**What this section proves.** One VNet carries five subnets, and each one is shaped by what the Azure service inside it demands (delegation, NAT, NSG). The network stage declares four of them inline; the jump-box stage adds the fifth later.

Diagram: docs/diagrams/02-network-topology.excalidraw

| Subnet | CIDR | Purpose | Delegation | NSG rules | NAT | What lives there |
|---|---|---|---|---|---|---|
| `snet-agent` | 10.42.0.0/24 | Foundry Agent Service network injection | The Container Apps hosting service (`infra/01-network.bicep:164-171#delegations`) | None attached | None; `defaultOutboundAccess` is false (`infra/01-network.bicep:160-173#snet-agent`) | The injected Foundry agent runtime. The repo deploys nothing else here. |
| `snet-pe` | 10.42.1.0/24 | Every private endpoint | None | None attached | None; `defaultOutboundAccess` is false and PE network policies are `Disabled` (`infra/01-network.bicep:175-181#privateEndpointNetworkPolicies`) | The 10 PEs listed in 3.2 |
| `snet-mcp` | 10.42.2.0/24 | Infrastructure subnet of the internal Container Apps env | The Container Apps delegation (`infra/01-network.bicep:189-196#delegations`) | None attached | The shared NAT gateway (`infra/01-network.bicep:186-188#natGateway`) | `cae-abw-priv-<region>-001` and its five apps; the env's internal load-balancer address (3.5) |
| `snet-apim` | 10.42.3.0/26 | APIM Standard v2 outbound VNet integration | `Microsoft.Web/serverFarms` (`infra/01-network.bicep:209-216#delegations`) | `nsg-abw-apim-<region>-001`: three outbound allow rules and no custom inbound rule (table below) | The shared NAT gateway (`infra/01-network.bicep:203-205#natGateway`) | The gateway's outbound traffic leaves through this subnet |
| `snet-jump` | 10.42.4.0/27 | Operator jump box (optional, added by the jump stage) | None | `nsg-abw-jump-<region>-001`: allow RDP from VirtualNetwork, deny all inbound from Internet (table below) | The shared NAT gateway (`infra/07-jumpbox.bicep:124-133#jumpSubnet`) | The VM's NIC. Bastion Developer attaches to the VNet, not to a subnet (`infra/07-jumpbox.bicep:230-241#bastion`). |

The CIDRs are parameters of the network template (`infra/01-network.bicep:36-41#apimSubnetPrefix`) and the jump subnet's CIDR is a parameter of its own template (`infra/07-jumpbox.bicep:34#jumpSubnetPrefix`). The VNet resource declares only an address space and the subnets (`infra/01-network.bicep:148-157#addressSpace`): there is no custom DNS server setting, and a search of `infra/` finds no VNet peering, so the linked private DNS zones (3.2) are the whole name-resolution design.

**NSG on `snet-apim`** (**Configured**, `infra/01-network.bicep:65-115#apimNsg`). All three rules are outbound; the platform's default rules cover everything else.

| Priority | Rule | Source -> destination | Port | Reason in the Bicep |
|---|---|---|---|---|
| 100 | `allow-out-keyvault-443` | VirtualNetwork -> AzureKeyVault | 443 | APIM v2 VNet integration treats Key Vault as a platform dependency (`infra/01-network.bicep:72-84#allow-out-keyvault-443`) |
| 110 | `allow-out-vnet-443` | VirtualNetwork -> VirtualNetwork | 443 | Gateway to the private MCP apps and the Foundry PEs (`infra/01-network.bicep:85-98#allow-out-vnet-443`) |
| 120 | `allow-out-internet-443` | VirtualNetwork -> Internet | 443 | The public vendor mock and Entra and Monitor endpoints, through the NAT gateway (`infra/01-network.bicep:99-112#allow-out-internet-443`) |

**NSG on `snet-jump`** (**Configured**, `infra/07-jumpbox.bicep:85-120#jumpNsg`).

| Priority | Rule | Direction | Source -> destination | Port | Effect |
|---|---|---|---|---|---|
| 100 | `allow-in-rdp-3389-bastion` | Inbound | VirtualNetwork -> any | 3389 | Bastion Developer reaches the VM from a platform address that the VirtualNetwork tag covers (`infra/07-jumpbox.bicep:91-104#allow-in-rdp-3389-bastion`) |
| 4000 | `deny-in-internet-all` | Inbound | Internet -> any | any | Nothing from the Internet can open a session (`infra/07-jumpbox.bicep:105-117#deny-in-internet-all`) |

**Why this shape.** Three services each insist on a subnet of their own: the Foundry agent runtime (injection), the internal Container Apps env, and the APIM v2 integration. Private endpoints get a fourth so that their address range is predictable (the 10.42.1.x addresses the jump box is meant to resolve to, `infra/07-jumpbox.bicep:1-10#10.42.1.x`). The jump box gets a fifth so that it can have its own NSG without touching the others.

**Platform behaviour.**
- Foundry Agent Service network injection needs a subnet delegated to the Container Apps hosting service, /27 or larger, in private (RFC 1918) address space, and the private endpoints to Search, Storage and Cosmos DB are not created for you: https://learn.microsoft.com/azure/foundry/agents/how-to/virtual-networks
- A workload-profiles Container Apps env needs its subnet delegated, whereas a consumption-only env must not be delegated: https://learn.microsoft.com/azure/container-apps/vnet-custom (the repo's envs use a `Consumption` profile in a workload-profiles env, `infra/03-platform.bicep:389-394#workloadProfiles`).
- Azure's default security rules carry the lowest priority, so custom rules are evaluated first (custom priority range 100-4096): https://learn.microsoft.com/azure/virtual-network/network-security-groups-overview#security-rules
- A subnet with `defaultOutboundAccess` set to false needs an explicit outbound method (NAT gateway, load-balancer outbound rule or public IP) to reach public endpoints: https://learn.microsoft.com/azure/virtual-network/ip-services/default-outbound-access

**Trade-off / limitation.** `snet-agent`, `snet-pe` and `snet-mcp` carry no NSG in the Bicep; the reason is not stated in the repo. The jump-box template records that an organisation baseline policy attaches an empty NSG to bare subnets (`infra/07-jumpbox.bicep:122-123#baseline`), which would apply to these three in a subscription governed by such a baseline; that policy is not in this repo. The subnets are also declared inline in the network template, so re-running the network stage after the jump box exists tries to remove `snet-jump` and fails (`infra/07-jumpbox.bicep:14-15#INLINE`, `docs/RUNBOOK.md:121#Never`, `scripts/jumpbox.ps1:28-29#network`).

### 3.2 Private endpoints and private DNS zones

**What this section proves.** Ten PEs, all in `snet-pe`, put the data planes on private addresses, and fifteen private DNS zones linked to the VNet make the normal public host names resolve to those addresses from inside the VNet. The count matches the cost model (`docs/COST.md:15#Private`, `docs/COST.md:20#Private`).

**Platform behaviour.** Azure publishes a CNAME from the service's public name to a `privatelink` name; a private DNS zone linked to a VNet overrides that name with the PE's private address, and DNS resolution and access control are independent, because a service with public network access disabled refuses the connection whatever DNS returns: https://learn.microsoft.com/azure/private-link/private-endpoint-dns

**The ten private endpoints** (all in `snet-pe`; each has one DNS zone group, `infra/modules/pe.bicep:19-54#zoneGroup`).

| # | PE | Target | Group id | Private DNS zone(s) | Defined in |
|---|---|---|---|---|---|
| 1 | `pe-<account>-blob` | Platform Storage account | `blob` | `privatelink.blob.core.windows.net` | `infra/03-platform.bicep:324-336#peBlob` |
| 2 | `pe-<account>-sql` | Platform Cosmos DB account | `Sql` | `privatelink.documents.azure.com` | `infra/03-platform.bicep:337-349#peCosmos` |
| 3 | `pe-<account>-search` | Platform AI Search service | `searchService` | `privatelink.search.windows.net` | `infra/03-platform.bicep:350-362#peSearch` |
| 4 | `pe-<account>-vault` | Key Vault | `vault` | `privatelink.vaultcore.azure.net` | `infra/03-platform.bicep:363-375#peKv` |
| 5 | `<foundry>-private-endpoint` | Foundry account | `account` | `privatelink.services.ai.azure.com`, `privatelink.openai.azure.com`, `privatelink.cognitiveservices.azure.com` | `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:128-140#aiAccountPrivateEndpoint`, DNS group `:297-308#aiServicesDnsGroup` |
| 6 | Agent-state Search PE | `asvcSearch` | `searchService` | `privatelink.search.windows.net` | `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:150-162#aiSearchPrivateEndpoint` |
| 7 | Agent-state Storage PE | `asvcStorage` | `blob` | `privatelink.blob.core.windows.net` | `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:172-184#storagePrivateEndpoint` |
| 8 | Agent-state Cosmos PE | `asvcCosmos` | `Sql` | `privatelink.documents.azure.com` | `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:191-203#cosmosDBPrivateEndpoint` |
| 9 | `<ampls>-pe` | Azure Monitor private link scope | `azuremonitor` | The four monitor zones below | `infra/foundry/modules-network-secured/monitor-private-link-scope.bicep:114-137#amplsPrivateEndpoint` |
| 10 | `pe-apim-abw-demo-<region>-001` | API Management | `Gateway` | `privatelink.azure-api.net` | `infra/05-apim.bicep:65-76#apimPe` |

Two further PEs exist in the Foundry template but are not deployed: the Key Vault PE (the foundry stage turns the template's Key Vault off, `scripts/deploy.ps1:265#enableKeyVault`) and the Fabric PE (conditional and unused, `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:214-226#Fabric`).

**The fifteen private DNS zones.** Fourteen are created and linked in the network stage (`infra/01-network.bicep:48-63#dnsZoneNames`, `infra/01-network.bicep:223-240#zoneLinks`); the fifteenth is created later, by the platform stage, from the internal Container Apps env's default domain (`infra/03-platform.bicep:417-425#acaDns`, `infra/modules/aca-dns.bicep:18-22#zone`). Every link has `registrationEnabled` false (`infra/01-network.bicep:229-240#registrationEnabled`).

| Zone | What resolves through it | PE(s) that use it |
|---|---|---|
| `privatelink.services.ai.azure.com` | `<foundry>.services.ai.azure.com`, which carries the project endpoint (`scripts/foundry-connections.ps1:45-46#projectEndpoint`) | #5 |
| `privatelink.openai.azure.com` | The Foundry account's OpenAI-compatible host | #5 |
| `privatelink.cognitiveservices.azure.com` | The Foundry account's Cognitive Services host | #5 |
| `privatelink.search.windows.net` | Both AI Search services (deal data and agent state) | #3, #6 |
| `privatelink.blob.core.windows.net` | Both Storage accounts' blob endpoints | #1, #7 |
| `privatelink.documents.azure.com` | Both Cosmos DB accounts | #2, #8 |
| `privatelink.fabric.microsoft.com` | Nothing in this deployment | None (declared, unused) |
| `privatelink.azurecr.io` | Nothing in this deployment | None (declared and linked, but ACR has no PE: `scripts/deploy.ps1:266#enableContainerRegistry`, `infra/03-platform.bicep:117#publicNetworkAccess`) |
| `privatelink.vaultcore.azure.net` | The Key Vault host | #4 |
| `privatelink.monitor.azure.com`, `privatelink.oms.opinsights.azure.com`, `privatelink.ods.opinsights.azure.com`, `privatelink.agentsvc.azure-automation.net` | Azure Monitor, Log Analytics and App Insights endpoints (`infra/foundry/modules-network-secured/monitor-private-link-scope.bicep:48-53#monitorDnsZoneNames`) | #9 |
| `privatelink.azure-api.net` | The APIM gateway host | #10 |
| The env's default domain (name set at deploy time) | Every Container Apps FQDN in the internal env: a wildcard A record and an apex A record, both pointing at the env's internal load-balancer address, TTL 300 (`infra/modules/aca-dns.bicep:24-48#wildcard`); linked to the VNet as `link-vnet-abw` (`infra/modules/aca-dns.bicep:50-61#link`) | Not a PE; a plain A-record zone |

**Evidence that it resolves.** The jump-box verifier checks eleven private host names from inside the VM: the Foundry account's three hosts, both Cosmos accounts, both Search services, both Storage accounts, Key Vault and APIM (`scripts/jumpbox.ps1:67-73#privateHosts`). The RUNBOOK records that 11 of 11 resolved to private addresses when the check was run from inside the VM; this is a recorded observation, not a design statement (`docs/RUNBOOK.md:126#Verified`). The Container Apps zone and the Monitor zones are not in that list.

**Why two sets of data stores.** The platform stage creates the business-data stores (deal documents, orders, positions, the `deals-idx` index); the vendored Foundry template creates its own agent-state stores under separate names (`scripts/deploy.ps1:245-250#asvcCosmos`) and wires them to the project as bring-your-own connections (3.4). Each set has its own PEs, and both sets share the one zone per service type.

**Trade-off / limitation.** The Foundry template is told to reference the existing zones instead of creating them (`scripts/deploy.ps1:231-241#monZones`, `scripts/deploy.ps1:263-264#existingDnsZones`, `infra/foundry/PATCHES.md:36-38#existingDnsZones`), so the network stage must run first. Two of the fifteen zones (Fabric and ACR) cost money and resolve nothing.

### 3.3 Egress

**What this section proves.** Three subnets leave through one NAT gateway and one public address; two subnets have no declared outbound method; and a short, explicit list of surfaces stays public on purpose.

| Subnet | Outbound path | Evidence | Note |
|---|---|---|---|
| `snet-agent` | No NAT gateway, no NSG, `defaultOutboundAccess` false | `infra/01-network.bicep:160-173#snet-agent` | It reaches the PEs inside the VNet. Whether the Foundry Agent Service runtime has other egress paths is not verified here. |
| `snet-pe` | None (PEs only) | `infra/01-network.bicep:175-181#snet-pe` | |
| `snet-mcp` | Shared NAT gateway | `infra/01-network.bicep:183-198#snet-mcp` | The Bicep does not say why. Inference: the servers that validate tokens fetch Entra signing keys (`src/mcp/abw_mcp/auth.py:60-102#JwksCache`) and four of them exchange tokens on behalf of the user (`src/mcp/abw_mcp/obo.py:39-75#OboBroker`), and both need Entra. |
| `snet-apim` | Shared NAT gateway plus the three outbound rules | `infra/01-network.bicep:99-112#allow-out-internet-443` | Public vendor mock and Entra and Monitor endpoints |
| `snet-jump` | Shared NAT gateway | `infra/07-jumpbox.bicep:124-133#jumpSubnet` | The portal and Entra sign-in need outbound 443; six outbound hosts are checked (`scripts/jumpbox.ps1:75#outboundHosts`) |

The NAT gateway is Standard SKU with a 10-minute idle timeout and a single static, regional, IPv4 Standard public IP (`infra/01-network.bicep:117-146#natGateway`). That one address is also the only IP that Key Vault's firewall admits (`infra/03-platform.bicep:94-100#natPublicIp`). The Bicep does not state the purpose of that rule; the likely consumer is APIM, whose outbound traffic leaves through the NAT gateway and which reads the Key Vault-backed named value (`infra/05-apim-apis.bicep:81-91#nvVendorKey`). The address itself is not written in this reference.

**What stays public, and what compensates.** The repository states these as honest edges (**Designed**, `DESIGN.md:243#public`).

| Surface | Setting | Why it is public | Compensating control | Defined in |
|---|---|---|---|---|
| APIM gateway | `publicNetworkAccess` Enabled | The presenter's laptop and the proof scripts call it; the Bicep header calls it the honest edge | JWT validation on every governed API; a private path through PE #10 exists as well | `infra/05-apim.bicep:57-61#publicNetworkAccess`, `infra/05-apim.bicep:1-10#honest` |
| Foundry account | `publicNetworkAccess` Enabled (the upstream account module defaults to Disabled) | The portal and the laptop reach the front door while the runtime stays injected | Local auth is disabled, so an Entra token plus Azure RBAC is still required; the policy exemption is recorded as Mitigated | `scripts/deploy.ps1:267#foundryPublicNetworkAccess`, `infra/foundry/PATCHES.md:19-20#foundryPublicNetworkAccess`, `infra/06-governance.bicep:284-295#exFoundryNetwork` |
| ACR | `publicNetworkAccess` Enabled, Standard SKU, no PE | ACR Tasks builds and image pulls; the jump box reaches it through the NAT gateway | The built-in registry user is off; callers use Entra RBAC (AcrPull, AcrPush) | `infra/03-platform.bicep:108-120#acr`, `docs/RUNBOOK.md:123#ACR` |
| Key Vault | `publicNetworkAccess` Enabled, firewall default Deny, NAT address allowed, PE present | See above | RBAC authorization, no access policies | `infra/03-platform.bicep:81-105#enableRbacAuthorization` |
| Vendor Container Apps env | No VNet configuration | It simulates an external SaaS MCP server | The gateway injects the vendor key; the vendor server checks it | `infra/03-platform.bicep:399-415#caePub`, `infra/04-apps.bicep:1-7#PUBLIC`, `src/mcp/abw_mcp/app.py:115-142#VendorKeyMiddleware` |
| App Insights | Ingestion and query both public | Container Apps, APIM and the laptop send telemetry during the demo | The scope is in Open mode, not Private Only | `infra/foundry/modules-network-secured/application-insights.bicep:44-54#publicNetworkAccessForIngestion`, `infra/foundry/PATCHES.md:21-22#amplsIngestionAccessMode` |

The data planes that are not on that list are closed to the Internet: Storage, Cosmos DB and AI Search have public network access disabled (`infra/03-platform.bicep:136-142#publicNetworkAccess`, `infra/03-platform.bicep:227-233#publicNetworkAccess`, `infra/03-platform.bicep:313-317#publicNetworkAccess`). The operator's public IP is read and cached in the preflight state (`scripts/deploy.ps1:187-190#Get-OperatorIpCached`), but no firewall in this repo uses it; the platform Storage account has no IP allow-list, so data is loaded by an in-VNet job instead (`infra/03-platform.bicep:136-137#PE-only`).

**Platform behaviour.** Without an explicit outbound method a subnet's VMs use a Microsoft-owned default outbound IP, which is why the private subnets set `defaultOutboundAccess` to false: https://learn.microsoft.com/azure/virtual-network/ip-services/default-outbound-access

### 3.4 Foundry account and project networking

**What this section proves.** The Foundry account is Entra-only and its front door is deliberately reachable, while the agent runtime is injected into `snet-agent`; the agent's state lives in separate stores behind their own PEs; and every MCP server is reached by one of four named paths.

The Foundry account, project, model, capability host and PEs come from a vendored upstream sample that was patched for this platform (**Configured**, `infra/foundry/PATCHES.md:3#foundry-samples`). The patches reuse the VNet, subnets and zones from the network stage, use predictable names, keep the front door reachable from the presenter's laptop, and place Log Analytics, App Insights and the private link scope under predictable names (`infra/foundry/PATCHES.md:7-11#front`).

| Setting | Value | Defined in |
|---|---|---|
| Account kind and SKU | `AIServices`, S0, system-assigned identity, project management on | `infra/foundry/modules-network-secured/ai-account-identity.bicep:23-54#allowProjectManagement` |
| Key authentication | `disableLocalAuth` true: Entra tokens only | `infra/foundry/modules-network-secured/ai-account-identity.bicep:52#disableLocalAuth` |
| Public network access | The upstream sample and its account module default to Disabled; the patched `main.bicep` defaults to Enabled and the foundry stage also passes Enabled. A template comment calls the result a hybrid setup in which the data proxy routes tool calls to private resources. | `infra/foundry/modules-network-secured/ai-account-identity.bicep:13-20#Hybrid`, `infra/foundry/main.bicep:93#foundryPublicNetworkAccess`, `scripts/deploy.ps1:267#foundryPublicNetworkAccess` |
| Network ACL | `defaultAction` is Allow when public access is Enabled, Deny otherwise; `bypass` is AzureServices | `infra/foundry/modules-network-secured/ai-account-identity.bicep:36-41#networkAcls` |
| Network injection | Scenario `agent`, subnet `snet-agent`, `useMicrosoftManagedNetwork` false | `infra/foundry/modules-network-secured/ai-account-identity.bicep:43-51#networkInjections` |
| Project | System-assigned identity; three bring-your-own connections to Cosmos DB, Storage and AI Search, all `AAD` auth | `infra/foundry/modules-network-secured/ai-project-identity.bicep:37-47#project`, `infra/foundry/modules-network-secured/ai-project-identity.bicep:49-89#project_connection_cosmosdb_account` |
| Capability host | Kind `Agents`; vector stores -> the Search connection, files -> the Storage connection, threads -> the Cosmos connection | `infra/foundry/modules-network-secured/add-project-capability-host.bicep:22-32#capabilityHostKind` |
| Agent-state stores | Separate Cosmos DB, AI Search and Storage accounts (`asvc*`), each behind a PE (rows 6-8 in 3.2) | `scripts/deploy.ps1:245-250#asvcCosmos` |
| Policy exemption | The account's public access is exempted from the network-restriction policy as Mitigated | `infra/06-governance.bicep:284-295#exFoundryNetwork` |

**Why public access is left on.** The portal and the laptop must be able to open the account while the model and agent runtime remain private-by-injection; the upstream sample's own default is the opposite and this repo's patch and stage flip it on purpose (`infra/foundry/PATCHES.md:19-20#foundryPublicNetworkAccess`). Setting it back to Disabled is the "fully private" scene the patch notes mention.

**Platform behaviour.** Network injection needs the delegated subnet described in 3.1, and PEs to the agent-state stores are not created automatically: https://learn.microsoft.com/azure/foundry/agents/how-to/virtual-networks

**How an agent reaches each MCP server.** The connection target for each server is fixed when the connections are created (`scripts/foundry-connections.ps1:59-66#specs`, `src/agent/abw_agents.py:95-106#server_urls`). Identity passthrough on the OAuth connections is described in section 6.4.

| # | Server | Connection target | Network path | Identity check at the hop | Kill switch reaches it? |
|---|---|---|---|---|---|
| 1 | research, wall, actions | The APIM gateway URL for the API | The runtime in `snet-agent` resolves the APIM host through `privatelink.azure-api.net` to PE #10, then the gateway reaches the backend through the `snet-apim` integration, resolving the Container Apps zone to the internal load-balancer address in `snet-mcp` (**Designed**, `infra/05-apim.bicep:3-4#inbound`) | APIM validates the user's JWT, then the server validates it again | Yes: the deny list is an APIM named value |
| 2 | private | The app's own internal FQDN (`https://ca-abw-mcp-private.<default-domain>`) | `snet-agent` -> the Container Apps zone -> the internal load-balancer address in `snet-mcp`; APIM is not on the path (`infra/04-apps.bicep:75#privateFqdn`) | The server alone | No (**Designed**, `DESIGN.md:107#kill`) |
| 3 | vendor | The APIM `/vendor` API | As row 1 up to the gateway; then out through the NAT gateway to the public env's FQDN | APIM validates the JWT, removes the `Authorization` header and sets `x-vendor-key` (`infra/05-apim-apis.bicep:75-78#vendorSection`) | Yes, at APIM |
| 4 | legacy | The APIM `/legacy` API | As row 1 | A subscription key only; no user identity (`infra/05-apim-apis.bicep:169-193#legacyApi`) | Not applicable: there is no identity to deny |

**Trade-off / limitation.** Row 2 bypasses the gateway, so revoking a user at APIM does not stop that path until the user's token expires. The README states the same (**Designed**, `README.md:149#private`). The production fix named in the design is an internal APIM in front of it, or having the server read the same deny list (`DESIGN.md:107#Production`).

### 3.5 Container Apps envs and the six apps

**What this section proves.** Six apps run one image in two envs; five of them are reachable only from inside the VNet. All six pull their image with a managed identity, and the four servers that exchange user tokens sign the exchange with a managed-identity assertion, so no registry password or client secret exists in their configuration. Two secrets do exist in app config and are named below.

| Env | Type | Subnet | Reach | Apps | Logs |
|---|---|---|---|---|---|
| `cae-abw-priv-<region>-001` | Internal (`internal` true), workload-profiles with a `Consumption` profile, not zone-redundant | `snet-mcp` | VNet only, through an internal load balancer | research, wall, actions, private, legacy | `azure-monitor` destination, plus a diagnostic setting to Log Analytics |
| `cae-abw-pub-<region>-001` | Same profile, no VNet configuration | None | Public | vendor | Same |

Defined in `infra/03-platform.bicep:377-397#caePriv` (the VNet settings are at `infra/03-platform.bicep:386-387#infrastructureSubnetId`) and `infra/03-platform.bicep:399-415#caePub`.

**Platform behaviour.** An internal Container Apps env has no public endpoint and is fronted by an internal load balancer: https://learn.microsoft.com/azure/container-apps/networking#accessibility-level. An app with external ingress inside an internal env is therefore reachable only from the VNet: https://learn.microsoft.com/azure/container-apps/ingress-overview#external-and-internal-ingress

**The six apps.** All six use `infra/modules/mcp-app.bicep:24-52#containerApps`. The module's header states the pattern: same image, behaviour chosen by `MCP_SERVER`, image pulled with the app's own identity, probes on `/healthz` (`infra/modules/mcp-app.bicep:1-2#MCP_SERVER`). The apps are declared in `infra/04-apps.bicep` (header: `infra/04-apps.bicep:1-7#PUBLIC`).

| App (`ca-abw-mcp-<server>`) | Env | Identity (`id-abw-mcp-<key>-<region>-001`) | `PUBLIC_BASE_URL` | How it is reached | Defined in |
|---|---|---|---|---|---|
| research | private | `research` UAMI | `<apim>/research` | APIM, path `/research/mcp` | `infra/04-apps.bicep:86-99#research` |
| wall | private | `wall` UAMI | `<apim>/wall` | APIM | `infra/04-apps.bicep:101-114#wall` |
| actions | private | `actions` UAMI | `<apim>/actions` | APIM | `infra/04-apps.bicep:116-129#actions` |
| private | private | `private` UAMI | Its own internal FQDN | Directly from the Foundry agent subnet | `infra/04-apps.bicep:131-144#privateMcp` |
| legacy | private | `legacy` UAMI | `<apim>/legacy` | APIM, subscription key | `infra/04-apps.bicep:146-164#legacy` |
| vendor | public | `vendor` UAMI | Not set | APIM, which calls its public FQDN | `infra/04-apps.bicep:166-189#vendor` |

The six identities are created by the platform stage (`infra/03-platform.bicep:40-46#uamiKeys`, `infra/03-platform.bicep:74-80#uamis`); their roles are tabulated in 5.6.

**Per-app settings from the module** (identical for all six unless stated):

| Setting | Value | Defined in |
|---|---|---|
| Ingress | `external` true (default), target port 8080, transport `auto`, `allowInsecure` false | `infra/modules/mcp-app.bicep:14-15#externalIngress`, `infra/modules/mcp-app.bicep:39-44#allowInsecure` |
| Revisions | `Single` | `infra/modules/mcp-app.bicep:38#activeRevisionsMode` |
| Profile | `Consumption` | `infra/modules/mcp-app.bicep:36#workloadProfileName` |
| Size | 0.5 vCPU and 1 GiB | `infra/modules/mcp-app.bicep:19-22#cpu` |
| Scale | Minimum 1, maximum 2 replicas; no scale rule is declared | `infra/modules/mcp-app.bicep:85-88#minReplicas` |
| Liveness probe | `/healthz`, initial delay 10 s, period 20 s | `infra/modules/mcp-app.bicep:63-72#Liveness` |
| Readiness probe | `/healthz`, initial delay 5 s, period 10 s | `infra/modules/mcp-app.bicep:73-82#Readiness` |
| Registry | The app's own identity; no registry credentials | `infra/modules/mcp-app.bicep:45-50#registries` |

**Platform behaviour (scale).** Per revision, a Container Apps app defaults to a minimum of 0 and a maximum of 10 replicas (configurable up to 1,000); the HTTP rule `concurrentRequests` defaults to 10; with several rules the revision scales when any one is met; and a minimum of 1 or more keeps an instance always running: https://learn.microsoft.com/azure/container-apps/scale-app. The repo declares no rule, so the minimum of 1 is what keeps each app warm; the implicit behaviour when no rule is declared is not verified here. Setting the minimum to 0 would save about $71 a month but adds a cold start of 10-20 seconds on the first call (**Designed**, `docs/COST.md:46#Container`, `docs/RUNBOOK.md:293#cold`).

**Variables.** Every app gets the common set; each server adds a small per-server set.

| Variable | Source | Meaning |
|---|---|---|
| `TENANT_ID`, `LOG_LEVEL` | Parameters | Tenant for token validation; log verbosity |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Secret reference `appi-conn` | Telemetry target |
| `AUDIT_STORAGE_ACCOUNT`, `AUDIT_CONTAINER` | Platform output; the container name is the literal `worm-audit` (`infra/04-apps.bicep:58#AUDIT_CONTAINER`) | The audit sink (3.7) |
| `STORAGE_ACCOUNT` | Platform output | Blob account holding deal documents |
| `COSMOS_ENDPOINT`, `COSMOS_DATABASE` | Platform output for the endpoint; the database name is the literal `abw` (`infra/04-apps.bicep:61#COSMOS_DATABASE`) | Cosmos DB account and database |
| `SEARCH_ENDPOINT`, `SEARCH_INDEX` | Platform output for the endpoint; the index name is the literal `deals-idx` (`infra/04-apps.bicep:63#SEARCH_INDEX`) | AI Search service and index |
| `MCP_REQUIRED_SCOPE` (`Tools.Read`) | Constant | Default scope required on the caller's token |
| `COSMOS_OBO` | Parameter `cosmosObo` | Whether Cosmos access uses the user's exchanged token; the code default is true (`src/mcp/abw_mcp/config.py:154#COSMOS_OBO`) |
| `MCP_SERVER` | Per server | Selects the behaviour of the single image |
| `MCP_APP_CLIENT_ID`, `MCP_ALLOWED_AZP` | Per server (not set on legacy or vendor) | The server's own Entra API app and the callers' `azp` allow-list |
| `UAMI_CLIENT_ID` | Per server | The app's managed identity, used to sign the OBO client assertion |
| `PUBLIC_BASE_URL` | Per server (not set on vendor) | The URL clients use to reach it |
| `OTEL_SERVICE_NAME` | Per server | `ca-abw-mcp-<server>` |
| `VENDOR_API_KEY` | Vendor only, secret reference `vendor-api-key` | The key the vendor mock expects in `x-vendor-key` |

Defined in `infra/04-apps.bicep:53-66#commonEnv`, `infra/04-apps.bicep:77-84#serverEnv` and `infra/04-apps.bicep:176-181#VENDOR_API_KEY`.

**Secrets and keylessness.**

| Credential | Where it lives | Keyless? | Evidence |
|---|---|---|---|
| Registry pull | No credential; each identity holds `AcrPull` | Yes | `infra/03-platform.bicep:537-547#raAcrPull` |
| On-behalf-of exchange | A client assertion signed by the app's managed identity and federated to its Entra API app; no client secret | Yes | `src/mcp/abw_mcp/obo.py:52-58#ManagedIdentityCredential`, `src/mcp/abw_mcp/obo.py:77-79#_get_client_assertion` |
| Data-plane keys | None exist: shared-key, local-auth and key-based access are disabled on Storage, Cosmos DB and AI Search (3.7) | Yes | `infra/03-platform.bicep:134#allowSharedKeyAccess` |
| `appi-conn` | A Container App secret on all six apps; its value is the App Insights connection string, written inline from the observability output | No | `infra/04-apps.bicep:68-73#appi-conn`, `DESIGN.md:238#connection` |
| `vendor-api-key` | A Container App secret on the vendor app (inline `value`), and a Key Vault secret that the gateway reads as a named value | No | `infra/04-apps.bicep:43-50#vendorKeySecret`, `infra/04-apps.bicep:182-187#vendor-api-key` |

**Image.** One container image serves all six apps: Python 3.12 slim, a non-root user, port 8080, started with `uvicorn` behind proxy headers (`src/mcp/Dockerfile:1-15#appuser`). The image reference is `<acr>/abw-mcp:<tag>` (`infra/04-apps.bicep:51#image`); how it is built is in 3.7 and 4.4.

**Trade-off / limitation.** The vendor mock's key is an inline Container App secret, not a Key Vault reference, even though the platform stage grants the vendor identity `Key Vault Secrets User` (`infra/03-platform.bicep:559-568#raVendorKv`); see Findings in section 13.

### 3.6 API Management

**What this section proves.** APIM Standard v2 is the single front door for five of the six MCP servers. It is reachable privately (inbound PE) and publicly, it reaches the private backends through outbound VNet integration, and its policies are files in the repo that are loaded at deploy time. Policy logic is in sections 6 and 7.3; this section covers the networking, named values, APIs and telemetry.

| Setting | Value | Defined in |
|---|---|---|
| Resource and API version | `Microsoft.ApiManagement/service`, preview API version | `infra/05-apim.bicep:43-63#2025-09-01-preview` |
| SKU | `StandardV2`, capacity 1 | `infra/05-apim.bicep:47-50#StandardV2` |
| Identity | System-assigned; it is used only to read the vendor key from Key Vault (API Center has its own identity, see below) | `infra/05-apim.bicep:51-53#SystemAssigned`, `infra/05-apim.bicep:225-233#raApimKv` |
| Outbound | VNet integration into `snet-apim` | `infra/05-apim.bicep:57-60#subnetResourceId` |
| Inbound | A PE (group `Gateway`, zone `privatelink.azure-api.net`) while the public gateway stays on | `infra/05-apim.bicep:65-76#apimPe`, `infra/05-apim.bicep:61#publicNetworkAccess` |
| Products and subscriptions | No product is declared; one subscription exists, `sub-abw-legacy-poc`, scoped to the legacy API with tracing off | `infra/05-apim-apis.bicep:204-213#legacySub` |

**Why Standard v2.** The design needs both an inbound PE (so the Foundry agent subnet reaches the gateway privately) and outbound VNet integration (so the gateway reaches the internal env). The cost model states that Basic v2 has no private-endpoint inbound and that Standard v2 is the cheapest tier with both (**Designed**, `docs/COST.md:48#Basic`; not independently verified here). APIM is also the largest cost line, $700 of about $1,100 a month (`docs/COST.md:13#API`).

**Platform behaviour.** Standard v2 and Premium v2 support outbound VNet integration and inbound private endpoints, and the gateway, management plane and developer portal stay publicly reachable unless you change that; the VNet must be in the same region and subscription: https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview#networking-options, https://learn.microsoft.com/azure/api-management/integrate-vnet-outbound, https://learn.microsoft.com/azure/api-management/private-endpoint

**Named values** (**Configured**; names are the `abw-*` display names):

| Named value | Secret? | Used by | Updated by | Defined in |
|---|---|---|---|---|
| `abw-tenant-id` | No | The JWT discovery URL, the issuers and a required-claim value (`infra/apim/policies/mcp-jwt.policy.xml:17-30#validate-jwt`); the protected-resource document's authorization server (`infra/apim/policies/prm.policy.xml:19#authorization_servers`) | Deploy | `infra/05-apim.bicep:179-188#nvTenant` |
| `abw-gateway-url` | No | The protected-resource document's `resource` (`infra/apim/policies/prm.policy.xml:17#resource`) | Deploy | `infra/05-apim.bicep:189-198#nvGateway` |
| `abw-allowed-azp` | No | The `azp` allow-list check (`infra/apim/policies/mcp-jwt.policy.xml:31-46#abw-deny`) | `scripts/client-allowlist.ps1` | `infra/05-apim.bicep:199-208#nvAzp` |
| `abw-deny-oids` | No; the value is `none` at deploy | The kill-switch deny list (`infra/apim/policies/mcp-jwt.policy.xml:31-46#abw-deny`, `infra/apim/policies/agent-frontdoor.policy.xml:51-55#abw-deny`) | `scripts/kill-switch.ps1`, `demo/prove.py` | `infra/05-apim.bicep:209-218#nvDeny` |
| `abw-vendor-key` | Yes, Key Vault-backed | The vendor API's `x-vendor-key` header | Rotated in Key Vault | `infra/05-apim-apis.bicep:81-91#nvVendorKey` |
| `abw-agent-token-quota`, `abw-agent-rpm` | No | The front door's token and request limits (`infra/apim/policies/agent-frontdoor.policy.xml:95-101#abw-agent-rpm`) | Deploy | `infra/08-agent-frontdoor.bicep:27-47#nvQuota` |

**APIs.** Five APIs have the MCP API type, one is anonymous discovery, and one is a plain HTTP front door to Foundry.

| API | Path | Type | Auth at APIM | Backend | Policy file |
|---|---|---|---|---|---|
| `abw-mcp-research` | `research` | `mcp` | User JWT and a role from the server list | `be-mcp-research` | `infra/apim/policies/mcp-jwt.policy.xml` |
| `abw-mcp-wall` | `wall` | `mcp` | JWT; either wall role | `be-mcp-wall` | same |
| `abw-mcp-actions` | `actions` | `mcp` | JWT; a trade role | `be-mcp-actions` | same |
| `abw-mcp-vendor` | `vendor` | `mcp` | JWT; the vendor gateway app's role and `aud` value; vendor key injected | `be-mcp-vendor` (certificate chain validated) | same, with the vendor section |
| `abw-mcp-legacy` | `legacy` | `mcp` | Subscription key only (`Ocp-Apim-Subscription-Key` header or `subscription-key` query) | `be-mcp-legacy` | `infra/apim/policies/mcp-legacy.policy.xml` |
| `abw-mcp-prm-discovery` | `.well-known/oauth-protected-resource` | HTTP | Anonymous | None | `infra/apim/policies/prm.policy.xml` |
| `abw-agent-frontdoor` | `agents` | HTTP | User JWT for the Foundry platform | The Foundry project endpoint | `infra/apim/policies/agent-frontdoor.policy.xml` |

Defined in `infra/05-apim-apis.bicep:28-73#servers` (per-server roles and flags), `infra/05-apim-apis.bicep:123-147#mcpApis`, `infra/05-apim-apis.bicep:169-193#legacyApi`, `infra/05-apim-apis.bicep:216-226#prmApi` and `infra/08-agent-frontdoor.bicep:49-62#abw-agent-frontdoor`. The MCP endpoint of each API is `/mcp` under its path (`infra/05-apim-apis.bicep:134-140#uriTemplate`); the governed APIs do not require a subscription (`infra/05-apim-apis.bicep:130#subscriptionRequired`).

**Where the policies live.** The XML files are in `infra/apim/policies/` and are inserted into the APIs with `loadTextContent`, after replacing placeholders for the server name, path, `aud` value, role list, list-open flag, vendor section and title (`infra/05-apim-apis.bicep:149-166#mcpPolicies`, `infra/05-apim-apis.bicep:195-202#legacyPolicy`, `infra/05-apim-apis.bicep:238-249#prmPolicies`, `infra/08-agent-frontdoor.bicep:76-87#policy`).

**Backends and TLS.** Each MCP server has a backend named `be-mcp-<key>` pointing at the app's FQDN (`infra/05-apim-apis.bicep:94-106#backends`). Certificate-chain and name validation follow a per-server flag: on for the public vendor server, and tied to the `validateInternalTls` parameter, default false, for the internal ones (`infra/05-apim-apis.bicep:21-22#validateInternalTls`, `infra/05-apim-apis.bicep:108-120#beLegacy`). **Trade-off / limitation:** until the internal certificate trust is verified and the flag is flipped, the gateway-to-app hop inside the VNet is encrypted but its certificate chain is not checked.

**Telemetry** (**Configured**).
- An App Insights logger named `appi` (`infra/05-apim.bicep:79-90#logger`) and a diagnostic with W3C correlation, 100 percent sampling, `alwaysLog` for errors, the client IP, the `x-ms-client-request-id` request header, and no body bytes (`infra/05-apim.bicep:92-137#diagAppi`).
- An Azure Monitor logger with 100 percent sampling (`infra/05-apim.bicep:139-152#diagAzMon`).
- A diagnostic setting to Log Analytics (`to-law`, dedicated tables, all logs and all metrics) (`infra/05-apim.bicep:154-176#apimDiag`).

**API Center.** A Free-tier API Center holds a governed catalogue of the MCP servers; it syncs from APIM, and its own system identity is given the API Management Service Reader role on the APIM instance so that it can import the APIs (`infra/05-apim.bicep:236-246#apic`, `infra/05-apim.bicep:267-276#raApicApim`, `infra/05-apim.bicep:277-292#apicSource`).

### 3.7 Data stores

**What this section proves.** Every store is keyless and closed to the Internet except where 3.3 says otherwise, and access is granted by Azure RBAC to groups and identities, not by keys (**Configured**: `infra/03-platform.bicep:134#allowSharedKeyAccess`, `infra/03-platform.bicep:227#disableLocalAuth`, `infra/03-platform.bicep:314#disableLocalAuth`, `infra/03-platform.bicep:91#enableRbacAuthorization`).

#### 3.7.1 Storage (platform account `stabwdemo<region><u4>`)

| Setting | Value | Defined in |
|---|---|---|
| Account | StorageV2, Standard_LRS, TLS 1.2 minimum | `infra/03-platform.bicep:122-145#minimumTlsVersion` |
| Keys | `allowSharedKeyAccess` false; OAuth is the default; blob public access off | `infra/03-platform.bicep:133-135#allowSharedKeyAccess` |
| Network | `publicNetworkAccess` Disabled, firewall Deny, bypass None, no IP rules, one PE | `infra/03-platform.bicep:138-142#publicNetworkAccess` |
| Blob service | 7-day soft delete for blobs and containers | `infra/03-platform.bicep:147-160#blobSvc` |
| Containers | `research-public`, `wall-falcon`, `wall-orion`, `worm-audit`; all with public access None | `infra/03-platform.bicep:162-169#cResearch`, `infra/03-platform.bicep:170-177#cFalcon`, `infra/03-platform.bicep:178-185#cOrion`, `infra/03-platform.bicep:186-194#cWorm` |
| WORM | A time-based immutability policy on `worm-audit`: 1 day, protected append writes allowed, deliberately unlocked | `infra/03-platform.bicep:195-202#wormPolicy` |

**WORM trade-off.** The audit container uses a time-based retention policy with `allowProtectedAppendWrites`, so the audit sink can keep appending blocks to its blobs (`src/mcp/abw_mcp/audit.py:54-130#AppendBlobAuditSink`). The policy is unlocked on purpose, because the data is synthetic; the design notes that a regulated record (SEC 17a-4, CFTC) needs a locked policy (**Designed**, `DESIGN.md:239#WORM`). **Platform behaviour:** an unlocked time-based policy can be changed or deleted, and `allowProtectedAppendWrites` can be changed only while it is unlocked; with it, only new blocks can be appended: https://learn.microsoft.com/azure/storage/blobs/immutable-container-level-worm-policies#allow-protected-append-blobs-writes and https://learn.microsoft.com/azure/storage/blobs/immutable-policy-configure-container-scope#modify-an-unlocked-retention-policy

**Who can read which container** (all data-plane Azure RBAC, **Configured**):

| Data | Principal | Role | Scope | Defined in |
|---|---|---|---|---|
| `research-public` | `sg-abw-research` | Storage Blob Data Reader | The container | `infra/03-platform.bicep:618-627#raResearchBlob` |
| `wall-falcon` | `sg-abw-wall-falcon` | Storage Blob Data Reader | The container | `infra/03-platform.bicep:628-639#raFalconBlob` |
| `wall-orion` | No person or group | None granted; only the `legacy` identity can read it, through its account-wide role (last row) | - | `infra/03-platform.bicep:638#Orion`, `infra/03-platform.bicep:570-578#raLegacyBlob` |
| `worm-audit` | Every server identity except `vendor` | Storage Blob Data Contributor | The container | `infra/03-platform.bicep:548-558#raAuditAppend` |
| Whole account | The `legacy` identity | Storage Blob Data Reader | The account | `infra/03-platform.bicep:570-579#raLegacyBlob` |

The README's "zero keys" footnote records four SAS-signed storage requests in a seven-day log that coincide with Defender for Storage onboarding and carry no caller identity (a recorded observation, `README.md:145#SAS`).

#### 3.7.2 Cosmos DB (platform account `cosmos-abw-demo-<region>-<u4>`)

| Setting | Value | Defined in |
|---|---|---|
| Account | `GlobalDocumentDB`, serverless, Session consistency, one location, not zone-redundant | `infra/03-platform.bicep:205-235#EnableServerless` |
| Keys and network | `disableLocalAuth` true, key-based management writes off, TLS 1.2, `publicNetworkAccess` Disabled, one PE | `infra/03-platform.bicep:227-233#disableLocalAuth` |
| Database | `abw` | `infra/03-platform.bicep:237-246#cosmosDb` |
| Containers | `restricted` (partition key `/ticker`), `orders` (`/user_oid`), `positions` (`/desk`) | `infra/03-platform.bicep:247-262#cosmosRestricted`, `infra/03-platform.bicep:263-281#cosmosOrders`, `infra/03-platform.bicep:282-300#cosmosPositions` |

**Platform behaviour.** Cosmos DB data-plane roles are separate from Azure RBAC roles: the built-in role `00000000-0000-0000-0000-000000000001` is Cosmos DB Built-in Data Reader and `00000000-0000-0000-0000-000000000002` is Built-in Data Contributor: https://learn.microsoft.com/azure/cosmos-db/reference-data-plane-security

| Assignment | Principal | Data-plane role | Scope | Defined in |
|---|---|---|---|---|
| `cosmosActionsRestricted` | The `actions` identity | Data Reader | `restricted` container | `infra/03-platform.bicep:604-617#cosmosActionsRestricted` |
| `cosmosTradersOrders` | `sg-abw-traders` | Data Contributor | `orders` | `infra/03-platform.bicep:650-662#cosmosTradersOrders` |
| `cosmosComplianceOrders` | `sg-abw-compliance` | Data Reader | `orders` | `infra/03-platform.bicep:663-675#cosmosComplianceOrders` |
| `cosmosTradersPositions` | `sg-abw-traders` | Data Reader | `positions` | `infra/03-platform.bicep:676-688#cosmosTradersPositions` |
| `cosmosCompliancePositions` | `sg-abw-compliance` | Data Reader | `positions` | `infra/03-platform.bicep:689-702#cosmosCompliancePositions` |
| `cosmosLegacyContrib` | The `legacy` identity | Data Contributor | The whole account (broad on purpose) | `infra/03-platform.bicep:569-601#cosmosLegacyContrib` |

The `actions` server reads the restricted-ticker list with its own identity and then checks it per order, so the user needs no access to that container (`src/mcp/abw_mcp/servers/actions.py:68-75#restricted`).

#### 3.7.3 AI Search (platform service `srch-abw-deals-<region>-<u4>`)

| Setting | Value | Defined in |
|---|---|---|
| Service | Basic SKU, one partition, one replica, semantic search disabled | `infra/03-platform.bicep:302-322#semanticSearch` |
| Keys and network | `disableLocalAuth` true, `publicNetworkAccess` disabled, bypass None, one PE | `infra/03-platform.bicep:313-317#disableLocalAuth` |
| Region | `searchLocation` when set, otherwise the resource group's region | `infra/03-platform.bicep:302-306#searchLocation` |
| Index | `deals-idx`, created by the seed job, not by Bicep | `src/seed/seed.py:113-126#make_search_index` |
| Index fields | `id` (key), `title`, `content`, `summary`, `snippet`, `ticker`, `classification`, `project`, `blob_path`, `updated`; `ticker`, `classification` and `project` are filterable | `src/seed/seed.py:113-126#classification` |
| Roles | `sg-abw-research` and the `legacy` identity hold Search Index Data Reader on the whole service, so the Azure role alone does not limit which documents a holder can read | `infra/03-platform.bicep:640-649#raSearchResearch`, `infra/03-platform.bicep:580-589#raLegacySearch` |

The research and wall servers query it with the user's exchanged token for the Search resource (`identity/Setup-Entra.ps1:46#OboResources`), so the user must belong to a group that holds the role; because the role is service-wide, which documents come back is decided by the server's own role check and query filter (section 7).

#### 3.7.4 Key Vault (`kv-abw-demo-<region>-<u4>`)

| Setting | Value | Defined in |
|---|---|---|
| SKU and authorization | Standard; Azure RBAC authorization (no access policies) | `infra/03-platform.bicep:81-105#enableRbacAuthorization` |
| Protection | Soft delete on, 7-day retention; no purge protection is set | `infra/03-platform.bicep:92-93#softDeleteRetentionInDays` |
| Network | Public access Enabled, firewall default Deny, AzureServices bypass, the NAT address allowed, and a PE | `infra/03-platform.bicep:94-100#natPublicIp` |
| What it holds | One secret, `vendor-api-key`. It is created through ARM because the Key Vault data plane is firewalled. | `infra/04-apps.bicep:37-50#vendorKeySecret` |
| Who reads it | APIM's system identity (Key Vault Secrets User) and the vendor identity (same role) | `infra/05-apim.bicep:225-233#raApimKv`, `infra/03-platform.bicep:559-568#raVendorKv` |
| Operator | The Key Vault full-control data role, scoped to the vault (control-plane use) | `infra/03-platform.bicep:736-745#raOpKv` |

#### 3.7.5 Container Registry (`crabwdemo<region><u4>`)

| Setting | Value | Defined in |
|---|---|---|
| SKU and access | Standard; the built-in registry user is off; public network access Enabled; no PE | `infra/03-platform.bicep:108-120#acr` |
| Builds | `az acr build` (ACR Tasks) for `linux/amd64`; no local Docker | `scripts/build-images.ps1:27-39#acr`, `README.md:48#Docker` |
| Repositories | `abw-mcp` (one image for six apps) and `abw-seed` | `scripts/build-images.ps1:7-10#abw-mcp` |
| Pulls | Each app identity holds `AcrPull`; the operator holds `AcrPush` | `infra/03-platform.bicep:537-547#raAcrPull`, `infra/03-platform.bicep:746-755#raOpAcr` |

The seed job is an in-VNet Container Apps job that loads the Storage, Cosmos DB and Search data over the private endpoints: it runs in the internal env, with a manual trigger, under its own identity (`infra/04b-seed-job.bicep:101-120#seedJob`, `infra/04b-seed-job.bicep:119#caePriv`, `infra/03-platform.bicep:136-137#PE-only`).

### 3.8 Monitoring plumbing

**What this section proves.** One Log Analytics workspace and one workspace-based App Insights component receive the platform's logs and telemetry; both are reached privately through an Azure Monitor private link scope that is set to Open mode; there are no data collection rules; and only 14 diagnostic settings exist, none of them on the VNet, NAT gateway, NSGs, Bastion or VM.

| Component | Settings | Defined in |
|---|---|---|
| Log Analytics `log-abw-demo-<region>-001` | `PerGB2018`, 30-day retention; created by the Foundry template and referenced as `existing` by the platform stage | `infra/foundry/modules-network-secured/application-insights.bicep:33-42#PerGB2018`, `infra/03-platform.bicep:65-72#law` |
| App Insights `appi-abw-demo-<region>-001` | Workspace-based, kind `web`; ingestion public only when `disablePublicIngestion` is false (it is, `infra/foundry/PATCHES.md:21-22#disablePublicIngestion`); query public | `infra/foundry/modules-network-secured/application-insights.bicep:44-54#WorkspaceResourceId` |
| Private link scope `ampls-abw-demo-<region>-001` | Ingestion mode passed in (Open), query mode Open; scopes the workspace and the App Insights component | `infra/foundry/modules-network-secured/monitor-private-link-scope.bicep:59-68#queryAccessMode`, `infra/foundry/modules-network-secured/monitor-private-link-scope.bicep:71-87#amplsAppInsights` |
| Scope PE and DNS | PE #9 and the four monitor zones | `infra/foundry/modules-network-secured/monitor-private-link-scope.bicep:114-153#amplsDnsZoneGroup` |
| Data collection rules | None are declared in `infra/` | A search of the Bicep for data collection resources finds nothing |

**Diagnostic settings** (all named `to-law`; resource logs go to Log Analytics).

| Resource | Categories | Defined in |
|---|---|---|
| Internal and public Container Apps envs | `ContainerAppConsoleLogs`, `ContainerAppSystemLogs` (logs only) | `infra/03-platform.bicep:428-444#diagCaePriv`, `infra/03-platform.bicep:446-462#diagCaePub` |
| Platform Storage (blob), Search, Key Vault, ACR | All logs | `infra/03-platform.bicep:464-476#diagBlob`, `infra/03-platform.bicep:493-505#diagSearch`, `infra/03-platform.bicep:507-519#diagKv`, `infra/03-platform.bicep:521-533#diagAcr` |
| Platform Cosmos DB | All logs, dedicated tables | `infra/03-platform.bicep:478-491#diagCosmos` |
| APIM | All logs and all metrics, dedicated tables | `infra/05-apim.bicep:154-176#apimDiag` |
| Foundry account and project; agent-state Cosmos, Search and Storage; the workspace itself | Added by the governance stage (see 4.7); the workspace's own query log makes the SOC's activity auditable | `infra/06-governance.bicep:102-121#diagFoundry`, `infra/06-governance.bicep:122-149#diagAsvcBlob`, `infra/06-governance.bicep:150-160#diagWorkspace` |

**Application telemetry.** Each app exports to App Insights through the connection string in its secret `appi-conn` and names itself with `OTEL_SERVICE_NAME` (3.5). **Trade-off / limitation:** the connection string is a secret in container config, and Log Analytics ingestion keys are still enabled; keyless telemetry is listed as the follow-up (**Designed**, `DESIGN.md:238#connection`).

**Not in this repo.** The workspace that receives the tenant's Entra sign-in logs is only read here (`infra/06b-observability.bicep:27#entraWorkspaceId`); the export that fills it is configured outside the repository.

### 3.9 Jump box and Bastion

**What this section proves.** A small Windows VM inside the VNet, reached through Bastion Developer, exists so the presenter can open the private-only portal data pages and run the Demo Console against private endpoints. It is optional, additive, and outside the keyless story.

**Why it exists.** From a laptop, the portal's data pages (Foundry Knowledge, AI Search explorer, Cosmos DB Data Explorer, Storage browser) fail because the data planes are reachable only through PEs. The VM resolves the private zones, so the same pages open (**Configured**, `infra/07-jumpbox.bicep:1-10#private-endpoint-only`; **Designed**, `docs/RUNBOOK.md:306#private-endpoint`).

**Trade-off / limitation.** The header comment lists Foundry, Search, Cosmos DB, Storage, Key Vault, ACR and APIM as private-endpoint-only, but the Foundry account (public access Enabled), ACR and the APIM gateway are public and Key Vault is public behind a firewall (3.3); see Findings in section 13.

| Aspect | Value | Defined in |
|---|---|---|
| Network | `snet-jump` 10.42.4.0/27 with its own NSG and the shared NAT gateway; no public IP on the VM or on Bastion Developer, and outbound traffic leaves from the NAT gateway's single address | `infra/07-jumpbox.bicep:124-133#jumpSubnet`, `infra/07-jumpbox.bicep:9-11#snet-jump`, `infra/01-network.bicep:117-130#natPip` |
| VM | Windows Server 2022 Datacenter Azure Edition, Trusted Launch, Standard SSD; default size `Standard_D2as_v7` with fallbacks `Standard_D2s_v7` and `Standard_D2ads_v7` | `infra/07-jumpbox.bicep:153-210#TrustedLaunch`, `scripts/jumpbox.ps1:64#sizeOrder` |
| Size choice | The template comment says several VM families are not available to the subscription in this tenant and the v7 sizes are open | `infra/07-jumpbox.bicep:56-60#vmSize` |
| Schedule | Auto-shutdown at 03:00 Central; a stopped VM costs only its disk | `infra/07-jumpbox.bicep:211-221#autoShutdown`, `infra/07-jumpbox.bicep:69-72#shutdownTime` |
| Bastion | Developer SKU, `bas-abw-demo-<region>-001`, created after the VM; needs only the VNet | `infra/07-jumpbox.bicep:230-241#bastion` |
| Sign-in | A local account whose name is a template parameter; the password is generated on first deploy, kept in the secrets folder and never printed; Bastion Developer is password-only | `scripts/jumpbox.ps1:22-29#Standard_D2as_v7`, `docs/RUNBOOK.md:125#Bastion` |
| Verification | 11 private hosts must resolve to private addresses, 6 outbound hosts must answer, and the egress address must be the NAT gateway's | `scripts/jumpbox.ps1:67-75#privateHosts`, `docs/RUNBOOK.md:126#Verified` |

**Platform behaviour.** Bastion Developer is free, uses a shared pool, supports one VM and one session at a time in select regions: https://learn.microsoft.com/azure/bastion/bastion-overview#skus. It is not for production and does not support VNet peering: https://learn.microsoft.com/azure/bastion/bastion-sku-comparison#decision-framework. It is not a dedicated resource: https://learn.microsoft.com/azure/bastion/design-architecture#deployment---bastion-developer

**What is installed and how the console runs there.**
1. `scripts/jumpbox-console.ps1` builds a package of the console and its support files (a whitelist, with a secret scan of the staged files) and sends it to the VM through run-command in parts (`scripts/jumpbox-console.ps1:30-33#whitelist`, `scripts/jumpbox-console.ps1:318-330#Build-Package`).
2. A setup script runs inside the VM as SYSTEM in phases (probe, tools, package, venv, launcher, verify, optional persona files, remove). It installs Python 3.11.9, Azure CLI 2.91.0 and PowerShell 7.6.8 if missing, each installer signature-checked (`scripts/jumpbox-console-setup.ps1:1-19#probe`, `scripts/jumpbox-console-setup.ps1:305-341#Invoke-Tools`, `scripts/jumpbox-console.ps1:73-77#tools`).
3. The `verify` phase first checks from inside the VNet that the APIM host resolves to a 10.x address and that a call with no token is refused, then starts a throw-away console on port 8799 and checks its pages (`scripts/jumpbox-console-setup.ps1:482-545#Invoke-Verify`).
4. At run time the launcher signs the operator in with a device code only when the Azure CLI on the VM is not already signed in to the tenant, then starts the console bound to 127.0.0.1, with the browser launch and the local `az` check switched off (`scripts/jumpbox-console-start.ps1:66-76#device-code`, `scripts/jumpbox-console-start.ps1:85#no-browser`, `scripts/jumpbox-console.ps1:9-10#127.0.0.1`). The README records that the device-code sign-in on the VM has not been observed (`README.md:147#device-code`).

**Honest edges** (**Designed**, `docs/RUNBOOK.md:121-127#Never`):
- Never re-run the network stage once `snet-jump` exists (3.1).
- The operator deliberately has no direct role on the user-data stores (Storage, Cosmos DB, search documents); data access is by group and on-behalf-of, so some portal data pages can fail for the operator even on the VM (`docs/RUNBOOK.md:122#operator`).
- If persona sign-in files are copied to the VM they are real secrets (refresh-token caches and demo passwords): the folder is locked, not encrypted (`docs/RUNBOOK.md:127#secrets`).

### 3.10 Region, SKU and capacity decisions

**What this section proves.** Each sizing choice below is either stated in the repo with a reason, or marked as having none stated.

| Decision | Value | Why (stated in the repo) | Defined in |
|---|---|---|---|
| Region | `eastus2`, region code in names | Default of the configuration | `scripts/common.ps1:44#eastus2` |
| AI Search region | `eastus` for both Search services | `eastus2` returned `InsufficientResourcesAvailable` for a new Search service on build day, so the template takes a separate location | `scripts/common.ps1:45#searchLocation`, `infra/foundry/PATCHES.md:24#searchLocation`, `README.md:50#eastus` |
| Model | `gpt-5.4-mini`, version `2026-03-17`, `GlobalStandard`, capacity 100 (the README says 100K TPM); the deployment is named `gpt-54-mini` | A stable name for the agent code to refer to | `scripts/deploy.ps1:251-256#model`, `scripts/common.ps1:180#modelDeploy`, `infra/foundry/PATCHES.md:18#gpt-54-mini` |
| APIM | `StandardV2`, capacity 1 | Needs inbound PE and outbound VNet integration (3.6) | `infra/05-apim.bicep:47-50#StandardV2` |
| AI Search | Basic, one partition, one replica, two services | Deal data plus agent state | `infra/03-platform.bicep:307-312#partitionCount`, `docs/COST.md:14#Search` |
| Cosmos DB | Serverless for the platform account; autoscale, five containers, for the agent-state account | Cost: the agent-state store has an idle floor of 100 RU/s per container | `infra/03-platform.bicep:214#EnableServerless`, `docs/COST.md:17#Cosmos` |
| Container Apps | `Consumption` profile; min 1, max 2; 0.5 vCPU and 1 GiB | Warm apps (no cold start) at about $71 a month | `infra/modules/mcp-app.bicep:19-22#minReplicas`, `docs/COST.md:16#Container` |
| ACR | Standard, public, no PE | The repo records "Standard SKU, no private endpoint" and public by design, and prices Standard at about $20 a month; the platform reason a PE is not possible on Standard is given below | `infra/03-platform.bicep:112-114#sku`, `scripts/jumpbox.ps1:74#public`, `docs/COST.md:19#Container` |
| Storage and Cosmos redundancy | Platform Storage `Standard_LRS`; the vendored template's agent-state Storage account defaults to `Standard_ZRS` (`Standard_GRS` in two regions) and nothing in this repo overrides it; both Cosmos DB accounts have one location and no zone redundancy; Container Apps envs not zone-redundant | A demo build: production shares APIM, Search, Foundry and the PE fabric | `infra/03-platform.bicep:128#Standard_LRS`, `infra/foundry/modules-network-secured/standard-dependent-resources.bicep:117-118#Standard_ZRS`, `infra/03-platform.bicep:224#isZoneRedundant`, `infra/foundry/modules-network-secured/standard-dependent-resources.bicep:66#isZoneRedundant`, `docs/COST.md:79#demo` |
| Log Analytics | `PerGB2018`, 30 days as the workspace default (Learn gives the Application Insights tables 90 days by default, 10.6.1) | Not stated | `infra/foundry/modules-network-secured/application-insights.bicep:38#PerGB2018` |
| Budget | USD 1,200 a month on the resource group; an alert, not a cap | See section 13.1 | `infra/09-budget.bicep:14#monthlyBudgetUsd` |
| Tags | `delete-after` is today plus 45 days | A reminder to tear down | `scripts/common.ps1:54#delete-after` |

**Platform behaviour (model deployment type).** Global deployment types may process inference in any Azure region while keeping data at rest in the designated geography; Data Zone types process within the zone and Standard (geography) types within the geography; `GlobalStandard` is pay-per-token with the highest quota: https://learn.microsoft.com/azure/foundry/foundry-models/concepts/deployment-types. A firm with processing-location requirements would need a different deployment type; that choice is not made in this repo.

**Platform behaviour (ACR).** Private endpoints for a container registry are available only in the Premium tier (up to 200 per registry): https://learn.microsoft.com/azure/container-registry/container-registry-private-endpoints. That means a Standard registry cannot have a PE, which is consistent with the registry being public here and with the `privatelink.azurecr.io` zone created in 3.2 having no PE behind it.

**Trade-off / limitation.** The repo states that ACR is public by design and points to DESIGN.md (`scripts/jumpbox.ps1:74#public`, `DESIGN.md:243#ACR`), but DESIGN.md gives no separate rationale for choosing Standard over Premium; the Premium-tier requirement above is the platform fact, and the cost saving is the repo's stated pricing, not a stated reason.

**Key takeaways**
- One 10.42.0.0/16 VNet holds five subnets, and three of them (`snet-agent`, `snet-mcp`, `snet-apim`) exist because Foundry injection, the internal Container Apps env and APIM v2 integration each require a delegated subnet of their own (`infra/01-network.bicep:160-216#delegations`).
- Ten PEs and fifteen private DNS zones make Storage, Cosmos DB, AI Search, the Foundry account, Key Vault, Monitor and the APIM gateway resolve privately; the Fabric and ACR zones exist but nothing uses them (`infra/01-network.bicep:48-63#dnsZoneNames`, `infra/modules/pe.bicep:19-54#zoneGroup`).
- Three subnets leave through one NAT gateway and one public address, which is also the only address Key Vault's firewall admits (`infra/01-network.bicep:117-146#natGateway`, `infra/03-platform.bicep:94-100#natPublicIp`).
- The public surfaces are few and named: the APIM gateway, the Foundry front door, ACR, the vendor env, Key Vault's NAT-gated endpoint and App Insights ingestion (`DESIGN.md:243#public`).
- The Foundry account is Entra-only and injected into `snet-agent`; its agent state lives in separate stores behind their own PEs (`infra/foundry/modules-network-secured/ai-account-identity.bicep:43-52#networkInjections`).
- Four paths reach MCP servers: through APIM over PE #10, directly to the private server (which the kill switch does not reach), through APIM to the public vendor env, and through APIM with a key for the legacy POC (`scripts/foundry-connections.ps1:59-66#specs`).
- Six apps run one image with 1-2 replicas and pull with managed identities; the four that exchange user tokens do so with a managed-identity-signed assertion; only `appi-conn` and `vendor-api-key` are secrets in app config (`infra/modules/mcp-app.bicep:45-50#registries`, `infra/04-apps.bicep:43-50#vendorKeySecret`).
- APIM Standard v2 is the single biggest cost and the governance chokepoint for every MCP server except the private one (the legacy API has only a rate limit); no product exists, and the only subscription is the legacy POC key (`infra/05-apim-apis.bicep:204-213#legacySub`).
- Storage, Cosmos DB and AI Search are keyless and PE-only; the WORM policy is deliberately unlocked (`infra/03-platform.bicep:195-202#wormPolicy`).
- The jump box and Bastion Developer have no public IP of their own (outbound leaves through the shared NAT gateway address), and the network stage hazard is permanent: do not re-run the network stage once `snet-jump` exists (`infra/07-jumpbox.bicep:14-15#INLINE`).

---

[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [2. System overview](02-system-overview.md) | Next: [4. Deployment architecture](04-deployment.md)
