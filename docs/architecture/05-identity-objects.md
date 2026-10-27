[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [4. Deployment architecture](04-deployment.md) | Next: [6. Authentication: identities, tokens and trust](06-authentication.md)

## 5. Identity objects and entitlement model

**What this section proves.** Every identity object the platform depends on is declared in code and can be re-created: six Entra groups, five API app registrations, two client apps, five persona users, seven user-assigned managed identities and a fixed set of Azure role assignments. For the tools that read business data as the caller, an entitlement is held as two grants in two systems - an app role on the API and a group-based data-plane role - so on Storage blobs and Cosmos DB containers a mistake in one layer does not open data (Search is the exception: one service-wide group grant covers every document). The section also states how far this model scales and what it leaves out (`identity/Setup-Entra.ps1:29-61#Apis`, `infra/03-platform.bicep:5-8#ENTRA`, `infra/03-platform.bicep:40-47#uamiKeys`).

**Objects at a glance.**

| Object class | Count | Created by | Removed by |
|---|---|---|---|
| Entra security groups (`sg-abw-*`) | 6 | Phase 1 (`identity/Setup-Entra.ps1:48-48#Groups`, `identity/Setup-Entra.ps1:115-115#securityEnabled`) | Teardown, matched by the name prefix `sg-abw-` (`identity/Setup-Entra.ps1:299-300#startswith`) |
| API app registrations (`abw-mcp-<server>`) | 5 | Phase 1 (`identity/Setup-Entra.ps1:29-45#Apis`) | Teardown, matched by the tag `abw-demo` (`identity/Setup-Entra.ps1:291-293#deletedItems`) |
| Client app registrations | 2 (`abw-agent-client`, `abw-test-client`) | Phase 1 (`identity/Setup-Entra.ps1:150-156#abw-agent-client`, `identity/Setup-Entra.ps1:171-178#abw-test-client`) | Teardown, by the same tag |
| Persona users (`abw.<persona>@<tenant-domain>`) | 5 | Phase 1 (`identity/Setup-Entra.ps1:198-222#personas.json`) | Teardown, matched by the demo company marker (`identity/Setup-Entra.ps1:295-297#companyMarker`) |
| Direct app-role assignments | 14, counted from the user map (`identity/Setup-Entra.ps1:50-61#Users`) | Phase 1 (`identity/Setup-Entra.ps1:237-251#appRoleAssignments`) | Go with the users and apps |
| Group memberships | 14, counted from the user map | Phase 1 (`identity/Setup-Entra.ps1:224-235#members`) | Go with the groups |
| Tenant-wide delegated grants | The data-plane targets of each API app, and all five APIs' scopes for each client app | Phase 1 (`identity/Setup-Entra.ps1:79-88#AllPrincipals`) | Go with the apps |
| User-assigned managed identities | 7: six MCP identities and one seed identity | `infra/03-platform.bicep:74-78#regionCode`, `infra/04b-seed-job.bicep:45-49#seedId` | Resource group deletion |
| System-assigned identities | 5: Foundry account, Foundry project, API Management, API Center and the Foundry-owned AI Search service | `infra/foundry/modules-network-secured/ai-account-identity.bicep:30-32#SystemAssigned`, `infra/foundry/modules-network-secured/ai-project-identity.bicep:41-43#SystemAssigned`, `infra/05-apim.bicep:51-53#SystemAssigned`, `infra/05-apim.bicep:243-245#SystemAssigned`, `infra/foundry/modules-network-secured/standard-dependent-resources.bicep:82-87#SystemAssigned` | Go with their resources |
| Federated identity credentials | 4: research, wall, actions, private | Phase 2 (`identity/Setup-Entra.ps1:266-275#research`) | Go with the apps |
| Foundry-created agent identity and blueprint, one set per agent | Not defined in this repo | Foundry | Not removed by teardown, because they are untagged (`README.md:159-159#blueprints`) |

### 5.1 Entra groups

**What this section proves.** The six security groups are the unit of data-plane access. Each group maps to a small, fixed set of Azure role assignments, and persona membership is declared in one table in the Entra script (`identity/Setup-Entra.ps1:48-61#Groups`).

| Group | Purpose | Members (from the user map) | Where it is granted |
|---|---|---|---|
| `sg-abw-demo-all` | Everyone who may use the agents | priya, wes, tara, carla, ian (`identity/Setup-Entra.ps1:50-61#Users`) | Foundry Agent Consumer on the Foundry project (`infra/02-foundry-rbac.bicep:36-44#raConsumersProject`; group id supplied by `scripts/deploy.ps1:280-291#consumersGroupId`; `DESIGN.md:155-155#Consumer`). The platform stage receives the id too (`scripts/deploy.ps1:311-318#sg-abw-demo-all`) but its role assignments use the other five groups (`infra/03-platform.bicep:618-674#groupIds`, `infra/03-platform.bicep:676-731#groupIds`). Also the target of the optional report-only Conditional Access policy (`scripts/extras-agent-identity.ps1:17-19#sg-abw-demo-all`) |
| `sg-abw-research` | Read the public research notes | priya, wes, tara, carla | Storage Blob Data Reader on `research-public` (`infra/03-platform.bicep:618-626#raResearchBlob`); Search Index Data Reader on the whole Search service (`infra/03-platform.bicep:640-648#raSearchResearch`) |
| `sg-abw-wall-falcon` | Wall-crossed on Project Falcon | wes, carla; the operator joins through the baseline (`docs/RUNBOOK.md:43-43#baseline`) | Storage Blob Data Reader on `wall-falcon` (`infra/03-platform.bicep:628-636#raFalconBlob`). There is no Orion group, and nobody is granted `wall-orion` (`infra/03-platform.bicep:638-638#Orion`) |
| `sg-abw-traders` | Trading desk | tara | Cosmos Data Contributor on `orders` (`infra/03-platform.bicep:650-661#cosmosTradersOrders`); Data Reader on `positions` (`infra/03-platform.bicep:676-687#cosmosTradersPositions`) |
| `sg-abw-compliance` | Compliance review | carla | Cosmos Data Reader on `orders` and `positions` (`infra/03-platform.bicep:663-674#cosmosComplianceOrders`, `infra/03-platform.bicep:689-700#cosmosCompliancePositions`) |
| `sg-abw-infosec` | Security operations visibility | ian | Reader and Monitoring Reader on the resource group and Log Analytics Reader on the workspace (`infra/03-platform.bicep:703-731#raInfosecReader`) |

**Why groups carry data-plane access (Implemented).** Storage, Cosmos and Search roles go to groups, not to the servers, because each server reads data under the caller's own OBO token, so the data plane evaluates the person and not the server (`infra/03-platform.bicep:5-8#ENTRA`, `src/mcp/abw_mcp/data.py:57-71#read_blob_text`). The operator deliberately holds no direct role on the user-data stores (blobs, Cosmos DB, search documents): a direct grant would break the group-based proof P16, and Owner is not data access (`docs/RUNBOOK.md:122-122#operator`).

**Why app roles go to users, not groups (Implemented, Platform behaviour).** The Entra script assigns app roles directly to users because group-based assignment needs Entra P1 (`identity/Setup-Entra.ps1:7-7#P1`), and the deploy guide states that P1 or P2 is not needed for the core demo (`docs/SELF-DEPLOY.md:94-94#P1`). Learn confirms that group-based app-role assignment requires Entra ID P1 or P2 and that nested group memberships are not supported for it: https://learn.microsoft.com/entra/identity/enterprise-apps/assign-user-or-group-access-portal. A related platform fact: a service principal that is added to a group assigned an app role does not get a `roles` claim (https://learn.microsoft.com/entra/identity-platform/howto-add-app-roles-in-apps), which is not an issue here because only users hold roles.

**Trade-off / limitation.** Each entitlement is two grants in two systems: an app-role assignment on the API app, and a group membership that turns into an Azure role assignment. Nothing in this repo reconciles the two, so a user can hold one without the other. That is useful in the demo (a crossed user asking for Orion is refused by the tool and, independently, by Storage: `src/mcp/abw_mcp/servers/wall.py:39-47#_require_project`, `infra/03-platform.bicep:638-638#Orion`), and it is a drift risk in operation (section 5.7).

**Inferred observation (derived from the code, not tested): Search scope.** `sg-abw-research` holds Search Index Data Reader on the whole service (`infra/03-platform.bicep:640-648#raSearchResearch`), and wall documents are indexed in the same `deals-idx` index as the public notes, with a title and a summary but no body (`src/seed/seed.py:153-171#wall`). The project separation at the Search layer is only the server-side filter in the wall server (`src/mcp/abw_mcp/servers/wall.py:62-68#classification`). A research-group member who could reach the Search endpoint directly would not be stopped by Azure RBAC from reading wall titles and summaries. Reaching it needs network access, because the service is private-endpoint-only with local auth off (`scripts/deploy.ps1:274-274#searchDisableLocalAuth`). The wall document body stays protected by per-container Storage RBAC (`infra/03-platform.bicep:628-636#raFalconBlob`, `src/mcp/abw_mcp/servers/wall.py:88-105#get_deal_document`). See Findings in section 13.

### 5.2 The five API apps

**What this section proves.** The five API app registrations are the only resource identifiers an MCP token can be issued for. Each one declares delegated scopes and user-assignable app roles and carries the OBO consents its server needs (`identity/Setup-Entra.ps1:29-45#Apis`).

Diagram: docs/diagrams/06-identity-and-entitlements.excalidraw

| App | Identifier URI and `aud` claim | Delegated scopes | App roles (value; member types) | Assigned to | OBO grants |
|---|---|---|---|---|---|
| `abw-mcp-research` | `api://<client-id>`; the `aud` claim of a v2 token is the app's client-id GUID (`identity/Setup-Entra.ps1:133-133#identifierUris`, `DESIGN.md:97-97#client-ID`) | `Tools.Read` | `Research.Read`; User (`identity/Setup-Entra.ps1:29-32#Research.Read`) | priya, wes, tara, carla | Storage, Search |
| `abw-mcp-wall` | Same pattern | `Tools.Read` | `Wall.Falcon`, `Wall.Orion`; User (`identity/Setup-Entra.ps1:33-35#Wall.Falcon`) | Falcon: wes, carla. Orion: nobody | Storage, Search (not Cosmos) |
| `abw-mcp-actions` | Same pattern | `Tools.Read`, `Tools.Execute` | `Trade.Read`, `Trade.Execute`; User (`identity/Setup-Entra.ps1:36-38#Trade.Execute`) | Read: carla. Execute: tara | Cosmos |
| `abw-mcp-private` | Same pattern | `Tools.Read` | `Positions.Read`; User (`identity/Setup-Entra.ps1:39-41#Positions.Read`) | tara, carla | Cosmos |
| `abw-mcp-vendorgw` | Same pattern | `Tools.Read` | `MarketData.Read`; User (`identity/Setup-Entra.ps1:42-44#MarketData.Read`) | priya, wes, tara, carla | None: the vendor server never sees the user token (`DESIGN.md:93-93#vendor`) |

The "Assigned to" column is read from the user map (`identity/Setup-Entra.ps1:50-61#Users`). The data-plane targets are Azure Storage, Azure Cosmos DB and Azure AI Search, identified by their first-party resource URLs (`identity/Setup-Entra.ps1:46-46#OboResources`).

**How Phase 1 builds each app (Implemented).**

1. Scope and role ids are derived from a fixed seed string, so a re-run produces the same ids and existing assignments keep pointing at the same role (`identity/Setup-Entra.ps1:124-125#New-DetGuid`). Roles allow the member type User only (`identity/Setup-Entra.ps1:125-125#allowedMemberTypes`). The determinism is Implemented; the reason (stable ids across re-runs) is inferred.
2. The app declares the data-plane scopes it will exchange for (`identity/Setup-Entra.ps1:126-126#rra`) and issues version 2 tokens (`identity/Setup-Entra.ps1:130-130#requestedAccessTokenVersion`).
3. The app is created or patched in full (`identity/Setup-Entra.ps1:131-132#PATCH`), then gets the identifier URI `api://<client-id>` (`identity/Setup-Entra.ps1:133-133#identifierUris`) and a service principal (`identity/Setup-Entra.ps1:134-134#Ensure-ServicePrincipal`).
4. The delegated data-plane scope is consented for all users in advance (`identity/Setup-Entra.ps1:136-136#Ensure-Grant`), using a tenant-wide grant (`identity/Setup-Entra.ps1:79-88#AllPrincipals`).

**Platform behaviour (OBO).** Learn states that the on-behalf-of flow works only with delegated scopes, that roles stay attached to the user, that it works only for user principals, that the incoming token's `aud` claim must be the middle-tier app, and that consent for the downstream API has to be given up front because the middle tier has no user interaction: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow. This is why the apps carry `requiredResourceAccess` and why the grants are tenant-wide. Section 6 covers the token itself.

**One server has no Entra API app, and one has an app that only the gateway uses.** The vendor server has an API app (`abw-mcp-vendorgw`, role `MarketData.Read`, no OBO grants: `identity/Setup-Entra.ps1:42-42#vendorgw`) but is validated at the gateway only (`DESIGN.md:93-93#vendor`): the gateway checks the user's token against that app, applies the role check to every call because `listOpen` is false for it, deletes the `Authorization` header and injects the vendor key (`infra/05-apim-apis.bicep:62-72#vendorgw`, `infra/05-apim-apis.bicep:75-78#vendorSection`). The server builds no OBO broker for it (`src/mcp/abw_mcp/app.py:76-77#OboBroker`) and checks only the vendor key header that the gateway injects (`src/mcp/abw_mcp/app.py:115-142#VendorKeyMiddleware`). The legacy server has no app registration at all, runs without an auth middleware (`src/mcp/abw_mcp/app.py:241-249#BearerAuthMiddleware`) and relies on the APIM subscription key (`DESIGN.md:125-125#legacy`).

### 5.3 Client apps

**What this section proves.** Two client apps stand for the callers of the APIs: a confidential client that Foundry uses to obtain user tokens, and a public client that persona sign-in uses. Neither client holds data access; both only obtain tokens (`identity/Setup-Entra.ps1:146-148#clientRra`).

| Client | Type | Redirect URIs | Credential | Used by |
|---|---|---|---|---|
| `abw-agent-client` | Confidential web app (`identity/Setup-Entra.ps1:150-156#abw-agent-client`) | A placeholder (`identity/Setup-Entra.ps1:153-153#abw-placeholder`) that Phase 2 replaces with the redirect URL Foundry returns for each connection (`identity/Setup-Entra.ps1:278-284#merged`, `scripts/foundry-connections.ps1:16-17#redirect`) | A client secret named `foundry-connection`, 80 days (`identity/Setup-Entra.ps1:166-166#addPassword`). Kept in the git-ignored secrets folder (`identity/Setup-Entra.ps1:158-158#agent-client.json`) and in each Foundry OAuth connection. The value is never written to this document or to state files | The five OAuth connections for Foundry identity passthrough (`scripts/foundry-connections.ps1:8-14#mcp-research-oauth`) |
| `abw-test-client` | Public client (`identity/Setup-Entra.ps1:171-178#isFallbackPublicClient`) | `http://localhost` (`identity/Setup-Entra.ps1:175-175#publicClient`) | None | Device-code persona sign-in for the console and for `demo/mcpclient.py` with `--persona` (`demo/mcpclient.py:88-107#persona_token`); the proofs do not use it |
| Azure CLI (Microsoft first-party app; its well-known application id is the constant `$azCliAppId` at `identity/Setup-Entra.ps1:190-190#azCliAppId`) | Microsoft public client | Not applicable | None | Pre-authorised on all five API apps for their delegated scopes (`identity/Setup-Entra.ps1:189-196#preAuthorizedApplications`) |

**Secret handling (Implemented).** Phase 1 creates a new agent-client secret only when the local file is missing, the stored app id differs, the credential is gone from the app, or it expires within 10 days (`identity/Setup-Entra.ps1:160-165#AddDays(10)`). Phase 1 writes the new secret to the local file only (`identity/Setup-Entra.ps1:167-167#Save-Json`); each Foundry connection keeps the copy it was created with until `foundry-connections.ps1` re-creates it (`scripts/foundry-connections.ps1:79-89#client-secret`). The script passes the secret on the azd command line and replaces it with a placeholder in error output (`scripts/foundry-connections.ps1:99-100#Escape`). A search of `identity/` and `scripts/` finds no call that removes an older credential, so a superseded secret stays valid until its own expiry. Rotation is therefore manual and split across two places (see Findings in section 13).

**Allow-list for clients.** The gateway rejects a token whose `azp` is not in the named value `abw-allowed-azp` (`infra/apim/policies/mcp-jwt.policy.xml:38-38#client_not_allowed`), and the MCP server applies its own copy (`src/mcp/abw_mcp/auth.py:151-153#bad_azp`). The deploy script builds the list from the two clients and the Azure CLI app id (`scripts/deploy.ps1:178-180#Get-AllowedAzp`). The reason the Azure CLI is pre-authorised is stated in the script step label: dev and test tokens from `az account get-access-token` for an API scope (`identity/Setup-Entra.ps1:189-189#Pre-authorize`).

**Consent.** Both clients are given delegated access to all five APIs' scopes and receive a tenant-wide consent grant (`identity/Setup-Entra.ps1:180-185#Ensure-Grant`). That is separate from the per-user consent each real persona gives Foundry for each OAuth connection (five consents per persona: `DESIGN.md:155-155#Consumer`). Section 6.4 covers that flow.

### 5.4 Personas and the operator

**What this section proves.** Six identities - five personas and the operator - cover the positive and negative cases the demo needs. Each persona is defined by app roles and groups, and the console states what each one is meant to prove (`console/personas.py:52-58#STORY`).

| Identity | Job | App roles | Groups | What it proves |
|---|---|---|---|---|
| priya | Research Analyst | `Research.Read`, `MarketData.Read` | all, research | The negative control: no wall crossing, so the gateway refuses Falcon, Orion, trades and positions (`console/personas.py:52-58#STORY`) |
| wes | Investment Banking Associate | `Research.Read`, `Wall.Falcon`, `MarketData.Read` | all, research, wall-falcon | Wall-crossed on Falcon only: Falcon allowed, Orion refused by the tool, no trading, no firm positions |
| tara | Equity Trader | `Research.Read`, `Trade.Execute`, `Positions.Read`, `MarketData.Read` | all, research, traders | Can place orders (restricted names still refused) and read firm positions; Falcon is refused |
| carla | Compliance Officer | `Research.Read`, `Wall.Falcon`, `Trade.Read`, `Positions.Read`, `MarketData.Read` | all, research, wall-falcon, compliance | Wall-crossed on Falcon, reads trade history and firm positions, cannot trade; Orion is refused |
| ian | Information Security Analyst | None | all, infosec | Holds no tool role, so the gateway refuses every tool call even with a valid token; he reads the audit trail, not the data |
| Operator (the person who deployed) | The signed-in account | Mirrored from wes and tara by the baseline (`docs/RUNBOOK.md:186-186#mirrors`) | Member of `sg-abw-wall-falcon` through the baseline (`docs/RUNBOOK.md:43-43#baseline`) | Path B: the console's default acting identity (`console/personas.py:47-48#OPERATOR_STORY`) |

The role and group columns are read from the user map (`identity/Setup-Entra.ps1:50-61#Users`). A persona without an app role on a server is refused at the gateway on every tool call to it (`console/personas.py:101-104#can_use`). That function's docstring says "every call", which overstates it: on the three servers whose `listOpen` flag is true, the gateway lets initialize, ping, tool-list and notification calls through on a valid token with the `Tools.Read` scope, and the server's own filter then decides which tools the caller sees (`infra/apim/policies/mcp-jwt.policy.xml:42-44#discovery`, `infra/05-apim-apis.bicep:38#listOpen`, `src/mcp/abw_mcp/registry.py:132-156#list_tools`).

**Two identity paths.** Path A uses the real persona accounts: device-code sign-in plus a TOTP code, with each persona holding their own Foundry consents, and setup takes about 40 minutes once. Path B keeps the operator signed in and re-maps the operator's roles and groups to look like a persona, which is fast for gateway beats but cannot switch the agent (`docs/RUNBOOK.md:23-31#Decide`, `docs/RUNBOOK.md:47-47#Agent`).

**Why the baseline runs before the first consent.** Foundry stores the token it receives at consent and reuses it for its whole life, so a first consent without roles leaves the agent with no wall, actions or private tools for a long time (`README.md:92-92#Baseline`). The deploy plan therefore runs the baseline step before the first consent (`docs/SELF-DEPLOY.md:175-175#baseline`). In this document the helper is called "baseline (persona mirroring on the operator)"; its parameters select a persona to mirror (`-As`) and extra personas to add (`-Also`).

**The operator's grants.** The operator needs Owner on the subscription to deploy (`scripts/Deploy-AgentWall.ps1:20-20#Owner`), Foundry User on the Foundry account (`infra/02-foundry-rbac.bicep:26-34#raOperatorAccount`) and three roles on the platform stage: the Key Vault full-control role, AcrPush and Search Service Contributor. The first two are themselves data-plane roles on the vault and the registry; the Bicep comment calls the set control plane only because the operator gets no blob, index or document access, and seeding runs inside the VNet (`infra/03-platform.bicep:733-764#CONTROL`). The runbook's "no direct data-plane roles" therefore means the user-data stores (`docs/RUNBOOK.md:122-122#operator`).

**Credential handling (names and locations only).**

- Persona passwords are generated, set to never expire and written to `personas.json` in the git-ignored secrets folder (`identity/Setup-Entra.ps1:207-207#New-StrongPassword`, `identity/Setup-Entra.ps1:210-211#DisablePasswordExpiration`, `identity/Setup-Entra.ps1:199-199#personas.json`). An existing persona with no stored password gets a reset and a stored password (`identity/Setup-Entra.ps1:214-218#password`).
- TOTP seeds are stored per persona in the same folder by a helper that follows RFC 6238 (`identity/Persona-Totp.py:1-18#RFC`).
- The console never displays a persona password: it copies it to the clipboard and wipes it after 60 seconds (`console/personas.py:527-534#clip_password`, `console/web/personas.js:229#clipboard`). It does show the six-digit one-time code and the device code on screen, each with a Copy button (`console/personas.py:1-12#clipboard`, `console/personas.py:370-374#totp_now`, `console/web/personas.js:220#userCode`, `console/web/personas.js:241#pc-otp`). Test sign-in caches are per persona (`console/personas.py:108-109#msal-test-`).
- Enrolling real personas for MFA is a human step: the deploy script does not do it (`docs/SELF-DEPLOY.md:41-41#MFA`).

### 5.5 Managed identities

**What this section proves.** Each MCP server has its own user-assigned managed identity. The four token-validating servers (research, wall, actions and private) hold only what a service legitimately needs and are federated to their own Entra API app, so each can prove itself during OBO without a secret. The other two differ on purpose: the legacy identity is broad, as the "typical POC" contrast case, and the vendor identity holds a Key Vault role its app does not use; neither is federated (`infra/03-platform.bicep:5-8#over-privileged`, `infra/03-platform.bicep:49-77#regionCode`, `identity/Setup-Entra.ps1:266-266#private`).

| Identity (`id-abw-mcp-<key>-<region>-001`) | Container App | Azure roles | Federates to | Defined in |
|---|---|---|---|---|
| research | `ca-abw-mcp-research` | AcrPull; audit append on `worm-audit` | Credential `uami-research` on `abw-mcp-research` | `infra/04-apps.bicep:93-93#uamis.research`, `infra/03-platform.bicep:537-556#raAuditAppend` |
| wall | `ca-abw-mcp-wall` | AcrPull; audit append | Credential `uami-wall` on `abw-mcp-wall` | `infra/04-apps.bicep:108-108#uamis.wall` |
| actions | `ca-abw-mcp-actions` | AcrPull; audit append; Cosmos Data Reader on `restricted` | Credential `uami-actions` on `abw-mcp-actions` | `infra/04-apps.bicep:123-123#uamis.actions`, `infra/03-platform.bicep:604-615#cosmosActionsRestricted` |
| private | `ca-abw-mcp-private` | AcrPull; audit append | Credential `uami-private` on `abw-mcp-private` | `infra/04-apps.bicep:138-138#uamis.private` |
| legacy | `ca-abw-mcp-legacy` | AcrPull; audit append; deliberately broad: Blob Data Reader on the whole account, Search Index Data Reader, Cosmos Data Contributor on the account | None | `infra/04-apps.bicep:153-153#uamis.legacy`, `infra/03-platform.bicep:569-601#raLegacyBlob` |
| vendor | `ca-abw-mcp-vendor` | AcrPull; Key Vault Secrets User, which the app does not use | None | `infra/04-apps.bicep:173-173#uamis.vendor`, `infra/03-platform.bicep:559-567#raVendorKv` |

Other identities in the platform:

| Identity | Kind | What it does | Defined in |
|---|---|---|---|
| Seed job (`id-abw-seed-<region>-001`) | User-assigned | Loads the demo data from inside the VNet: AcrPull, Blob Data Contributor on the account, Search Service Contributor, Search Index Data Contributor, Cosmos Data Contributor | `infra/04b-seed-job.bicep:45-49#seedId`, `infra/04b-seed-job.bicep:51-99#raAcr` |
| Foundry account | System-assigned | Hosts the models and agents | `infra/foundry/modules-network-secured/ai-account-identity.bicep:30-32#SystemAssigned` |
| Foundry project | System-assigned | The principal for every role the Foundry template grants on its own state stores (section 5.6) | `infra/foundry/modules-network-secured/ai-project-identity.bicep:41-43#SystemAssigned` |
| Foundry-owned AI Search | System-assigned | Created by the vendored Foundry template because the deploy scripts pass no existing Search service; the template exposes no principal id for it and this repo assigns it no role | `infra/foundry/modules-network-secured/standard-dependent-resources.bicep:82-87#SystemAssigned`, `infra/foundry/modules-network-secured/standard-dependent-resources.bicep:140-143#aiSearchID` |
| API Management | System-assigned | Reads the vendor key from Key Vault | `infra/05-apim.bicep:51-53#SystemAssigned`, `infra/05-apim.bicep:225-233#raApimKv` |
| API Center | System-assigned | Reads the APIM instance for the API catalogue | `infra/05-apim.bicep:243-245#SystemAssigned`, `infra/05-apim.bicep:267-275#raApicApim` |
| Jump box | None | The VM resource declares no identity block; the local account password is a generated secret in the secrets folder | `infra/07-jumpbox.bicep:153-208#vm` |
| Image build | The signed-in operator | `az acr build` runs as the operator, who holds AcrPush; no separate build identity | `scripts/build-images.ps1:34-34#acr`, `infra/03-platform.bicep:746-754#raOpAcr` |
| Foundry agent identities | Created by Foundry | Each agent on the new Foundry agent model gets its own Entra agent identity and blueprint; this repo records them read-only | `scripts/extras-agent-identity.ps1:10-12#ALREADY` |

**Why the four token-validating servers' identities hold no user-data read (Implemented).** On those servers user data is read with the caller's OBO token (`src/mcp/abw_mcp/data.py:57-97#read_blob_text`), so the managed identity only proves the server to Entra: it signs a client assertion for `api://AzureADTokenExchange` (`src/mcp/abw_mcp/obo.py:52-57#ManagedIdentityCredential`, `src/mcp/abw_mcp/obo.py:77-79#AzureADTokenExchange`). Their identities hold audit append (a write to the WORM container) and image pull, plus the restricted-list read for the actions server, which reads the list as the service (`src/mcp/abw_mcp/servers/actions.py:30-37#_read_restricted`). The other two servers are the contrast: the legacy server reads data as its own identity (`src/mcp/abw_mcp/servers/legacy.py:52-64#use_user_token`), which is why that identity is broad, and the vendor identity holds image pull and an unused Key Vault role but no audit append (`infra/03-platform.bicep:548-548#vendor`, `infra/03-platform.bicep:559-567#raVendorKv`).

**How the federation is built (Implemented, Platform behaviour).** Phase 2 reads the UAMI principal ids from the platform stage output and, for the four federated servers, creates a credential named `uami-<key>` whose issuer is the Entra v2 issuer URL for the tenant, whose subject is the UAMI principal id and whose `aud` claim is `api://AzureADTokenExchange` (`identity/Setup-Entra.ps1:265-265#issuer`, `identity/Setup-Entra.ps1:270-274#AzureADTokenExchange`). A credential with a different subject is deleted and re-created (`identity/Setup-Entra.ps1:272-273#subject`). Learn describes this trust: https://learn.microsoft.com/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity. Phase 2 needs the platform stage first because the principal ids exist only after the UAMIs do (`identity/Setup-Entra.ps1:258-262#Invoke-Phase2`).

**The Foundry template's own role assignments.** The vendored Foundry template grants roles to the project identity on the Foundry-owned state stores, not on the platform's data accounts (section 5.6). The Key Vault role in that template is skipped because Key Vault is disabled in the Foundry stage (`infra/foundry/main.bicep:327-327#keyVaultRoleAssignment`, `scripts/deploy.ps1:265-267#enableKeyVault`).

### 5.6 Azure RBAC role assignments

**What this section proves.** The complete set of Azure role assignments is small enough to read in one table. Five principal kinds hold them: user-assigned identities, Entra groups, the operator, the Foundry, APIM and API Center system identities and, only when the optional identity extras are run, the first-party Agent 365 service principal (section 5.6.4). The platform stage's own comment states the rule for the servers: only what a service legitimately needs (`infra/03-platform.bicep:535-536#legitimately`). Cosmos roles `...0001` and `...0002` are Cosmos DB's own data-plane roles (Data Reader and Data Contributor), distinct from Azure RBAC: https://learn.microsoft.com/azure/cosmos-db/reference-data-plane-security.

#### 5.6.1 Platform stage (`infra/03-platform.bicep`)

| Principal | Role (id) | Scope | Defined in |
|---|---|---|---|
| All six MCP identities | AcrPull (`7f951dda-4ed3-4680-a7ca-43fe172d538d`) | The container registry | `infra/03-platform.bicep:537-545#raAcrPull` |
| Five MCP identities (all but vendor) | Storage Blob Data Contributor (`ba92f5b4-2d11-453d-a403-e96b0029c9fe`) | Container `worm-audit` | `infra/03-platform.bicep:548-556#raAuditAppend` |
| Vendor identity | Key Vault Secrets User (`4633458b-17de-408a-b874-0445c86b69e6`) | The Key Vault | `infra/03-platform.bicep:559-567#raVendorKv` |
| Legacy identity | Storage Blob Data Reader (`2a2b9908-6ea1-4ae2-8e65-a410df84e7d1`) | The whole storage account | `infra/03-platform.bicep:570-578#raLegacyBlob` |
| Legacy identity | Search Index Data Reader (`1407120a-92aa-4202-b7e9-c0e197c71c8f`) | The Search service | `infra/03-platform.bicep:580-588#raLegacySearch` |
| Legacy identity | Cosmos Data Contributor (`...0002`) | The Cosmos account | `infra/03-platform.bicep:590-601#cosmosLegacyContrib` |
| Actions identity | Cosmos Data Reader (`...0001`) | Container `restricted` | `infra/03-platform.bicep:604-615#cosmosActionsRestricted` |
| `sg-abw-research` | Storage Blob Data Reader | Container `research-public` | `infra/03-platform.bicep:618-626#raResearchBlob` |
| `sg-abw-wall-falcon` | Storage Blob Data Reader | Container `wall-falcon` | `infra/03-platform.bicep:628-636#raFalconBlob` |
| Nobody | None | Container `wall-orion` | `infra/03-platform.bicep:638-638#Orion` |
| `sg-abw-research` | Search Index Data Reader | The Search service | `infra/03-platform.bicep:640-648#raSearchResearch` |
| `sg-abw-traders` | Cosmos Data Contributor (`...0002`) | Container `orders` | `infra/03-platform.bicep:650-661#cosmosTradersOrders` |
| `sg-abw-compliance` | Cosmos Data Reader (`...0001`) | Container `orders` | `infra/03-platform.bicep:663-674#cosmosComplianceOrders` |
| `sg-abw-traders` | Cosmos Data Reader (`...0001`) | Container `positions` | `infra/03-platform.bicep:676-687#cosmosTradersPositions` |
| `sg-abw-compliance` | Cosmos Data Reader (`...0001`) | Container `positions` | `infra/03-platform.bicep:689-700#cosmosCompliancePositions` |
| `sg-abw-infosec` | Reader (`acdd72a7-3385-48ef-bd42-f606fba81ae7`) | The resource group | `infra/03-platform.bicep:703-711#raInfosecReader` |
| `sg-abw-infosec` | Log Analytics Reader (`73c42c96-874c-492b-b04d-ab87d138a893`) | The Log Analytics workspace | `infra/03-platform.bicep:713-721#raInfosecLaReader` |
| `sg-abw-infosec` | Monitoring Reader (`43d0d8ad-25c7-4714-9337-8ba259a9fe05`) | The resource group | `infra/03-platform.bicep:723-731#raInfosecMonitor` |
| Operator (user) | Key Vault full-control data role (`00482a5a-887f-4fb3-b363-3b7fe8e74483`) | The Key Vault | `infra/03-platform.bicep:736-744#raOpKv` |
| Operator (user) | AcrPush (`8311e382-0749-4cb8-b61a-304f252e45ec`) | The container registry | `infra/03-platform.bicep:746-754#raOpAcr` |
| Operator (user) | Search Service Contributor (`7ca78c08-252a-4471-8644-bb5ff32d4ba0`) | The Search service | `infra/03-platform.bicep:756-764#raOpSearchSvc` |

#### 5.6.2 Foundry RBAC, APIM and seed stages

| Principal | Role (id) | Scope | Defined in |
|---|---|---|---|
| Operator (user) | Foundry User (`53ca6127-db72-4b80-b1b0-d745d6d5456d`) | The Foundry account | `infra/02-foundry-rbac.bicep:12-13#53ca6127-db72-4b80-b1b0-d745d6d5456d`, `infra/02-foundry-rbac.bicep:26-34#raOperatorAccount` |
| `sg-abw-demo-all` (group) | Foundry Agent Consumer (`eed3b665-ab3a-47b6-8f48-c9382fb1dad6`) | The Foundry project | `infra/02-foundry-rbac.bicep:14-15#eed3b665-ab3a-47b6-8f48-c9382fb1dad6`, `infra/02-foundry-rbac.bicep:36-44#raConsumersProject` |
| API Management identity | Key Vault Secrets User | The Key Vault | `infra/05-apim.bicep:225-233#raApimKv` |
| API Center identity | API Management Service Reader (`71522526-b88f-4d52-b57f-d31fc3546d0d`) | The APIM instance | `infra/05-apim.bicep:41-41#71522526-b88f-4d52-b57f-d31fc3546d0d`, `infra/05-apim.bicep:267-275#raApicApim` |
| Seed identity | AcrPull | The container registry | `infra/04b-seed-job.bicep:51-59#raAcr` |
| Seed identity | Storage Blob Data Contributor | The whole storage account | `infra/04b-seed-job.bicep:61-69#raBlob` |
| Seed identity | Search Service Contributor | The Search service | `infra/04b-seed-job.bicep:71-79#raSearchSvc` |
| Seed identity | Search Index Data Contributor (`8ebe5a00-799e-43f5-93ac-243d3dce84a7`) | The Search service | `infra/04b-seed-job.bicep:81-89#raSearchData` |
| Seed identity | Cosmos Data Contributor (`...0002`) | The Cosmos account | `infra/04b-seed-job.bicep:91-99#cosmosSeed` |

#### 5.6.3 Vendored Foundry template (Foundry-owned state stores)

The principal in every row is the Foundry project's system identity (`infra/foundry/main.bicep:620-620#projectPrincipalId`). These roles are on the stores the template creates for the Agent Service, not on the platform's business data (`scripts/deploy.ps1:245-250#asvcCosmos`).

| Role (id) | Scope | Defined in |
|---|---|---|
| Storage Blob Data Contributor (`ba92f5b4-2d11-453d-a403-e96b0029c9fe`) | The Foundry-owned storage account | `infra/foundry/modules-network-secured/azure-storage-account-role-assignment.bicep:12-22#ba92f5b4-2d11-453d-a403-e96b0029c9fe`, invoked at `infra/foundry/main.bicep:514-514#storageAccountRoleAssignment` |
| Cosmos DB Operator (`230815da-be43-4aae-9cb4-875f7bd000aa`) | The Foundry-owned Cosmos account | `infra/foundry/modules-network-secured/cosmosdb-account-role-assignment.bicep:14-25#230815da-be43-4aae-9cb4-875f7bd000aa`, invoked at `infra/foundry/main.bicep:527-527#cosmosAccountRoleAssignments` |
| Search Index Data Contributor (`8ebe5a00-799e-43f5-93ac-243d3dce84a7`) and Search Service Contributor (`7ca78c08-252a-4471-8644-bb5ff32d4ba0`) | The Foundry-owned Search service | `infra/foundry/modules-network-secured/ai-search-role-assignments.bicep:15-28#8ebe5a00-799e-43f5-93ac-243d3dce84a7`, `infra/foundry/modules-network-secured/ai-search-role-assignments.bicep:30-43#7ca78c08-252a-4471-8644-bb5ff32d4ba0`, invoked at `infra/foundry/main.bicep:540-540#aiSearchRoleAssignments` |
| Storage Blob Data Owner (`b7e6dc6d-f1e8-4753-8033-0f276bb0955b`) with an attribute condition | The Foundry-owned storage account; the condition limits the blob-tag read, write and filter actions to containers whose name starts with the project workspace id and ends in `-azureml-agent` (other actions are not limited by it) | `infra/foundry/modules-network-secured/blob-storage-container-role-assignments.bicep:19-36#b7e6dc6d-f1e8-4753-8033-0f276bb0955b`, invoked at `infra/foundry/main.bicep:572-572#storageContainersRoleAssignment` |
| Cosmos Data Contributor (`...0002`) | The Foundry-owned Cosmos account (the module's account scope) | `infra/foundry/modules-network-secured/cosmos-container-role-assignments.bicep:16-32#accountScope`, invoked at `infra/foundry/main.bicep:587-587#cosmosContainerRoleAssignments` |
| Log Analytics Reader (`73c42c96-874c-492b-b04d-ab87d138a893`) and Privileged Monitoring Data Reader (`dbc9c667-e97f-4491-aee6-90b9cf960190`) | The Application Insights component | `infra/foundry/modules-network-secured/application-insights-role-assignment.bicep:15-33#dbc9c667-e97f-4491-aee6-90b9cf960190`, invoked at `infra/foundry/main.bicep:602-602#applicationInsightsRoleAssignment` |

#### 5.6.4 Optional extras

| Principal | Role | Scope | Defined in |
|---|---|---|---|
| The first-party Agent 365 service principal | The Azure role A365 Gateway Policy Operator | The APIM instance. This is the RBAC half only; the tenant-level step is a human action. `-WithExtras` runs the script without its Conditional Access part | `scripts/extras-agent-identity.ps1:13-16#A365`, `scripts/extras-agent-identity.ps1:134-182#roleDefinitions`, `docs/SELF-DEPLOY.md:42-42#WithExtras` |

The same script can create one Conditional Access policy in report-only state (never enforced) for members of `sg-abw-demo-all`, with the operator excluded, that requires MFA for the five MCP API apps (`scripts/extras-agent-identity.ps1:17-19#enabledForReportingButNotEnforced`, `scripts/extras-agent-identity.ps1:241-247#includeGroups`). It is not created by the orchestrator (`docs/SELF-DEPLOY.md:42-42#WithExtras`).

**Trade-off / limitation.** The legacy identity's grants are broad on purpose, as the contrast case (`infra/03-platform.bicep:569-569#broad`). The `raVendorKv` grant is not exercised by the vendor app, which keeps its own inline copy of the key (`infra/04-apps.bicep:180-187#VENDOR_API_KEY`, `infra/03-platform.bicep:558-558#vendor`); see Findings in section 13.

### 5.7 Entitlement model as built

**What this section proves.** An entitlement travels as claims in one user token through seven checks, and the last check is made by the Azure data plane against the person, not by repo code. The same model is expensive to extend, because a new deal touches four places, and it has no entitlement store (`infra/apim/policies/mcp-jwt.policy.xml:31-46#abw-deny`, `src/mcp/abw_mcp/auth.py:108-170#verify_token`).

**The path of one entitlement (Implemented).**

1. Entra issues a v2 access token for `api://<client-id>`: `scp` holds the delegated scopes and `roles` holds the user's directly assigned app roles (`DESIGN.md:97-97#client-ID`, `identity/Setup-Entra.ps1:130-130#requestedAccessTokenVersion`).
2. The gateway validates the token and evaluates, in order, the deny-list (`revoked`), the client allow-list (`client_not_allowed`), the scope (`missing_scope`) and, for non-discovery methods, the role (`missing_role`) (`infra/apim/policies/mcp-jwt.policy.xml:37-37#revoked`, `infra/apim/policies/mcp-jwt.policy.xml:38-38#client_not_allowed`, `infra/apim/policies/mcp-jwt.policy.xml:39-39#missing_scope`, `infra/apim/policies/mcp-jwt.policy.xml:43-44#missing_role`).
3. The MCP server validates the token again and builds the caller, including its roles (`src/mcp/abw_mcp/auth.py:144-149#ver`, `src/mcp/abw_mcp/auth.py:155-159#missing_scope`, `src/mcp/abw_mcp/auth.py:168-168#jti`).
4. The tool registry hides tools whose requirement the caller fails and refuses a direct call to them (`src/mcp/abw_mcp/registry.py:98-108#require_any_role`, `src/mcp/abw_mcp/registry.py:132-156#list_tools`, `src/mcp/abw_mcp/registry.py:163-165#FORBIDDEN`).
5. The tool applies deal-level rules: the project must be in the caller's roles, and a restricted ticker blocks an order (`src/mcp/abw_mcp/servers/wall.py:39-47#_require_project`, `src/mcp/abw_mcp/servers/actions.py:58-75#separation_of_duties`).
6. The server exchanges the caller's token for a data-plane token (`src/mcp/abw_mcp/obo.py:64-75#acquire_token_on_behalf_of`).
7. Storage, Cosmos or Search evaluates the caller against the group-based role assignments of section 5.6. A refusal comes back as `storage_rbac_denied` and is audited (`src/mcp/abw_mcp/servers/wall.py:95-95#storage_rbac_denied`).

Sections 6 and 7 describe the tokens and the layers in detail. Refusals that Entra makes before a request reaches the gateway are outside this path (see section 13).

**Where an entitlement is checked, by tool.** Each tool states its requirement once, in the server code.

| Server | Requirement | Cited at |
|---|---|---|
| research | `Research.Read` on both tools | `src/mcp/abw_mcp/servers/research.py:67-85#Research.Read` |
| wall | `Wall.Falcon` or `Wall.Orion` on all three tools, then the project check | `src/mcp/abw_mcp/servers/wall.py:112-138#build_tools` |
| actions | `Trade.Read` or `Trade.Execute` to check the list and read own orders; scope `Tools.Execute` plus `Trade.Execute` to place an order | `src/mcp/abw_mcp/servers/actions.py:137-137#require_any_role`, `src/mcp/abw_mcp/servers/actions.py:145-145#require_scope_and_role` |
| private | `Positions.Read` on both tools | `src/mcp/abw_mcp/servers/private.py:59-76#Positions.Read` |
| vendor | No user role; the gateway checks `MarketData.Read` | `src/mcp/abw_mcp/servers/vendor.py:69-77#allow_all`, `infra/05-apim-apis.bicep:67-67#MarketData.Read` |
| legacy | None: every tool allows all callers and uses the service identity | `src/mcp/abw_mcp/servers/legacy.py:116-120#allow_all` |

**The four places a new deal must be changed.** The repo has no add-a-deal procedure; this list is derived from reading the code.

| # | Place | Where | What changes |
|---|---|---|---|
| 1 | Entra app role and assignments | `identity/Setup-Entra.ps1:33-35#Wall.Falcon` | A new role value on the wall app, and an assignment for each entitled user |
| 2 | Gateway role list | `infra/05-apim-apis.bicep:45-45#Wall.Falcon` | The role must be in the API's role array, or the gateway answers `missing_role` (`infra/apim/policies/mcp-jwt.policy.xml:43-44#missing_role`) |
| 3 | Server code | `src/mcp/abw_mcp/servers/wall.py:13-16#PROJECT_TITLES`, `src/mcp/abw_mcp/servers/wall.py:21-21#Literal`, `src/mcp/abw_mcp/servers/wall.py:26-26#doc_id`, `src/mcp/abw_mcp/servers/wall.py:29-36#caller_projects` | The project names are hard-coded: the argument type, the document id pattern, the title map, the role-to-project map, and the role lists on the three tools (`src/mcp/abw_mcp/servers/wall.py:119-119#require_any_role`) |
| 4 | Storage container and RBAC | `infra/03-platform.bicep:170-186#cFalcon`, `infra/03-platform.bicep:628-636#raFalconBlob` | A container per project and a role assignment for the entitled group |

The seed data also changes: wall documents and restricted-list entries are generated per project (`src/seed/seed.py:153-171#wall`, `src/seed/seed.py:211-214#ZYNX`).

**Strengths.**

- The data plane decides on the person on the four token-validating servers. Storage, Cosmos and Search see the caller's own identity through OBO, so repo code cannot silently widen access there (`src/mcp/abw_mcp/data.py:57-97#read_blob_text`, `src/mcp/abw_mcp/obo.py:64-75#acquire_token_on_behalf_of`). Two qualifications. The Cosmos user token is a setting, `COSMOS_OBO`, which defaults to true; if it were set to false, the actions and private servers would call Cosmos as the server, and in this repo their identities hold no Cosmos role on the orders and positions containers, so the likely result is a refusal rather than a wider read (derived from the role table; not run) (`src/mcp/abw_mcp/config.py:154#COSMOS_OBO`, `src/mcp/abw_mcp/servers/private.py:26-27#cosmos_obo`, `infra/03-platform.bicep:604-614#cosmosActionsRestricted`). The legacy server is the contrast: it never uses a user token (`src/mcp/abw_mcp/servers/legacy.py:52-109#use_user_token`).
- Two independent grants per entitlement give defence in depth on Storage and Cosmos. The Orion case shows it: nobody is granted the container, and the tool refuses first (`infra/03-platform.bicep:638-638#Orion`, `src/mcp/abw_mcp/servers/wall.py:39-47#_require_project`). Search is the weaker case: `sg-abw-research` holds Search Index Data Reader on the whole service, so the data plane does not separate the documents in the index and the research tool's own filter, `classification eq 'public'`, does (`infra/03-platform.bicep:640-648#raSearchResearch`, `src/mcp/abw_mcp/servers/research.py:23-29#filter_text`).
- No server holds a key to a data store. The four token-validating servers each have a managed identity federated to their API app (`identity/Setup-Entra.ps1:266-266#private`, `identity/Setup-Entra.ps1:272-274#subject`); the legacy and vendor identities are not federated. The only secrets in the servers' own settings are the telemetry connection string and, on the vendor server alone, the vendor key (`infra/04-apps.bicep:180-186#vendor-api-key`; section 13.5).
- The identity surface is small and re-creatable: six groups, five API apps, five users, deterministic ids (`identity/Setup-Entra.ps1:124-125#New-DetGuid`).
- Revocation does not wait for token expiry at the gateway: the deny-list takes about 45 to 90 seconds, and group removal reaches the data plane in under a minute in the measured runs (`docs/RUNBOOK.md:335-335#Kill`, `docs/RUNBOOK.md:337-337#Entitlement`).
- One entitlement is already data-driven: the restricted list lives in Cosmos and is read at call time, not encoded in roles (`src/mcp/abw_mcp/servers/actions.py:58-75#restricted_list`, `src/seed/seed.py:211-214#ZYNX`).

**Scale limits (Platform behaviour, with this repo's position).**

| Limit | Value | Source | This repo today |
|---|---|---|---|
| Permission definitions per app (app roles plus exposed scopes) | 700 by default; disabled roles still count | https://learn.microsoft.com/entra/identity-platform/howto-add-app-roles-in-apps#app-role-limits | 2 to 4 per API app, counted from `identity/Setup-Entra.ps1:29-45#Apis` |
| App-role assignments per user, group or service principal | 1,500 | https://learn.microsoft.com/entra/identity/users/directory-service-limits-restrictions | At most 5 per persona |
| Group-based app-role assignment | Needs Entra ID P1 or P2; nested groups not supported | https://learn.microsoft.com/entra/identity/enterprise-apps/assign-user-or-group-access-portal | Not used (`identity/Setup-Entra.ps1:7-7#P1`) |

**Inferred judgement.** The Entra caps are far from binding at five personas. What binds is the operating model: one role per deal, assigned user by user, plus edits in four files. Learn advises using app roles for stable categories rather than one role per resource, and keeping fine-grained resource permissions in the application's own authorisation data (https://learn.microsoft.com/entra/identity-platform/howto-add-app-roles-in-apps#app-role-limits). The per-deal wall role is the opposite pattern, which is acceptable for two deals and does not scale to hundreds.

**What a real entitlement store would add (not in this repo).**

- A system of record for who is wall-crossed on which deal, who approved it, and for how long, owned by compliance. The tool would consult it at call time, the way `place_order` consults the restricted list, instead of reading role names.
- Request, approval and expiry. Learn describes access packages with multi-stage approval, time-limited assignments, access reviews and automatic assignment from identity properties, and Azure roles can be driven by putting a group into a package: https://learn.microsoft.com/entra/id-governance/entitlement-management-overview.
- Recertification and drift detection between the store, Entra group membership and Azure role assignments. Today nothing compares them.
- One decision point called by layers 1 to 3, so an entitlement change needs no Bicep or code change.
- Grant-level evidence: who changed what, and when.

Section 13 lists the related gaps: the private-server bypass of the kill switch and the Entra refusals that never reach the denial table.

### 5.8 Lifecycle

**What this section proves.** Every identity object has a create path, a rotation story and a removal path in the scripts, with three exceptions: a superseded agent-client secret is never removed, the Foundry-created agent identities are not tagged, so teardown leaves them, and the persona passwords and one-time-code seeds have no rotation procedure (`identity/Setup-Entra.ps1:166-166#addPassword`, `README.md:159-159#blueprints`, `identity/Setup-Entra.ps1:214-218#password`).

| Event | What happens | Where |
|---|---|---|
| Create, Phase 1 (before any Azure stage) | Groups, five API apps with scopes, roles and consent, two clients, the agent-client secret, Azure CLI pre-authorisation, persona users, memberships, direct role assignments | `identity/Setup-Entra.ps1:104-104#Invoke-Phase1`; in order: groups (`identity/Setup-Entra.ps1:111-111#Security`), API apps (`identity/Setup-Entra.ps1:121-121#API`), clients (`identity/Setup-Entra.ps1:145-145#Client`), Azure CLI pre-authorisation (`identity/Setup-Entra.ps1:189-189#Pre-authorize`), users (`identity/Setup-Entra.ps1:198-198#Persona`), memberships (`identity/Setup-Entra.ps1:224-224#Group`), role assignments (`identity/Setup-Entra.ps1:237-237#App-role`) |
| Create, Phase 2 (after the platform stage) | Four federated credentials, then the redirect URIs Foundry returned, merged with the existing list and without the placeholder | `identity/Setup-Entra.ps1:258-286#Invoke-Phase2`, `identity/Setup-Entra.ps1:281-282#merged` |
| Re-run Phase 1 | Finds objects by name, patches apps, skips memberships and assignments that exist, and creates a secret only when needed | `identity/Setup-Entra.ps1:131-132#PATCH`, `identity/Setup-Entra.ps1:160-165#AddDays(10)`, `identity/Setup-Entra.ps1:245-245#continue` |
| Re-run Phase 2 | Skips a credential whose subject already equals the UAMI principal id; deletes and re-creates one with another subject | `identity/Setup-Entra.ps1:272-273#subject` |
| Rotate the agent-client secret | Re-run Phase 1 inside the 10-day window, then re-create the connections so they pick up the new secret; the old credential is not removed | `identity/Setup-Entra.ps1:160-166#addPassword`, `scripts/foundry-connections.ps1:22-22#Force` |
| Rotate persona passwords or TOTP seeds | No rotation procedure in this repo; Phase 1 resets only an existing persona that has no stored password | `identity/Setup-Entra.ps1:214-218#password` |
| Revoke one user at the gateway | The kill switch adds the user to the named value `abw-deny-oids`; about 45 to 90 seconds; the session-revocation switch takes minutes; disabling the account is manual on purpose | `scripts/kill-switch.ps1:7-9#abw-deny-oids`, `scripts/kill-switch.ps1:11-14#revokeSignInSessions`, `docs/RUNBOOK.md:335-335#Kill` |
| Revoke an entitlement | Removing a group membership reaches the data plane in under a minute; an app-role change shows only in the next token | `docs/RUNBOOK.md:337-337#Entitlement`, `README.md:141-141#CAE` |
| Revoke the agent's copy | Foundry reuses a user's token for its whole life, so a role change reaches the agent only when that token expires | `README.md:141-141#CAE` |
| Private server | The direct path does not go through APIM, so the kill switch does not reach it | `DESIGN.md:107-107#private` |
| Teardown | Step 0 removes the report-only policy and the Agent 365 role grant; step 6 removes Entra apps (by tag, and purges them), users (by company marker) and groups (by prefix) | `scripts/teardown.ps1:9-16#Entra`, `scripts/teardown.ps1:141-146#extras-agent-identity`, `scripts/teardown.ps1:216-219#Phase` |
| Teardown, keep Entra | `-KeepEntra` leaves users, groups and apps for the next deployment; the federated credentials then point at deleted identities until Phase 2 replaces them (derived from the two code paths). It also skips step 0, so the report-only Conditional Access policy, which lives in Entra outside the resource group, stays in the tenant | `scripts/teardown.ps1:26-27#KeepEntra`, `scripts/teardown.ps1:9-10#skipped`, `scripts/teardown.ps1:142-142#KeepEntra`, `identity/Setup-Entra.ps1:272-273#subject` |
| Teardown, clean local | `-CleanLocal` deletes the files at the top of the secrets folder and the `*.json` files at the top of the generated-state folder, so persona passwords and the agent-client secret are gone; subfolders and other file types stay, although the script's own help says it deletes both folders | `scripts/teardown.ps1:30-31#CleanLocal`, `scripts/teardown.ps1:224-224#SecretsDir`, `scripts/teardown.ps1:225-225#Filter` |

**Trade-off / limitation.** Teardown matches groups by the name prefix `sg-abw-`, so it would also delete another party's groups that share the prefix (`identity/Setup-Entra.ps1:299-300#startswith`). That is one reason the platform allows one deployment per tenant (section 13.4). Section 4.5 and section 4.10 cover the stage order and the teardown steps.

**Key takeaways**

- The identity surface is small and fully scripted: 6 groups, 5 API apps, 2 clients, 5 users, 7 user-assigned identities and 4 federated credentials, all re-creatable (`identity/Setup-Entra.ps1:29-61#Apis`, `infra/03-platform.bicep:40-47#uamiKeys`).
- App roles go to users because group-based assignment needs Entra P1 (`identity/Setup-Entra.ps1:7-7#P1`); data-plane access goes to groups because the servers read data as the caller (`infra/03-platform.bicep:5-8#ENTRA`).
- An entitlement is two grants in two systems, and nothing reconciles them: that is the demo's defence in depth and an operating risk (`infra/03-platform.bicep:638-638#Orion`, `src/mcp/abw_mcp/servers/wall.py:39-47#_require_project`).
- The four token-validating servers are keyless: each has a managed identity federated to its API app, with roles limited to audit append, image pull and, for actions, the restricted list; the legacy identity is broad on purpose and the vendor identity is not federated (`identity/Setup-Entra.ps1:270-274#AzureADTokenExchange`, `infra/03-platform.bicep:569-601#raLegacyBlob`).
- A new deal touches four places and the seed data; there is no entitlement store, and Learn advises against one app role per resource at scale (`infra/05-apim-apis.bicep:45-45#Wall.Falcon`, `src/mcp/abw_mcp/servers/wall.py:21-21#Literal`).
- Revocation is fast at the gateway and the data plane but slow for the agent, and the private server is outside the kill switch (`docs/RUNBOOK.md:335-335#Kill`, `README.md:141-141#CAE`, `DESIGN.md:107-107#private`).
- The agent-client secret is the one long-lived secret in the identity design: it is copied into every Foundry connection, rotated by hand and never removed after rotation (`identity/Setup-Entra.ps1:166-166#addPassword`, `scripts/foundry-connections.ps1:88-88#client-secret`).

---

[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [4. Deployment architecture](04-deployment.md) | Next: [6. Authentication: identities, tokens and trust](06-authentication.md)
