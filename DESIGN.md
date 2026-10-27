# Agents Behind the Wall — design contract (as built)

Single source of truth for names, identities, contracts and flows. Code, Bicep, scripts and the demo agree with this file.
Everything is **synthetic**: fictional firm (Contoso Capital Markets), fictional tickers, fake deal data. Status: deployed and
proven — **18/18 proofs, 110/110 checks** (`demo\evidence\SCOREBOARD.md`).

## 1. Thesis (what the demo proves)

> Keys bypass Conditional Access. A missing user context bypasses data-level RBAC, Purview and every
> audit trail you own. Fix the *identity chain* (user → agent → gateway → tool → data) and every
> other control — policy, monitoring, records, infosec visibility — lights up on its own.

Customer pain points, each with the proof that closes it:

| # | FSI pain point | How it is closed here | Proof |
|---|---|---|---|
| 1 | "No keys." | Foundry, Storage, Cosmos, Search, ACR, Key Vault: Entra only (7 days of storage requests: 0 key-based). Azure Policy denies key auth and keyed Foundry connections. The one *external vendor* key lives in Key Vault → APIM and is never seen by an agent or a user. | P01, P07, P11 |
| 2 | On-behalf-of | Each MCP server exchanges the **user's** token (OBO, federated credential, no secret) for the data plane. Azure RBAC — not our code — decides. | P03, P04, P10 |
| 3 | User auth on internal / external / private MCP | internal = APIM + ACA (Entra JWT + OBO); external = vendor MCP behind APIM (key injected at the gateway); private = ACA internal ingress, reachable only from the VNet-injected agent runtime. | P02, P06, P07 |
| 4 | "How are people using agents?" | `AbwUsageByUser`, `AbwAgentActivity`, cockpit workbook: users, agents, tools, denials, latency. | P17 |
| 5 | InfoSec visibility into governance | Azure Policy compliance, 9 Sentinel analytics rules, one correlated trace per `request_id`, WORM audit blob. | P10, P11, P13, P17 |
| 6 | MNPI information barrier | Wall roles gate deal data at the gateway, at the MCP tool list/call and — independently — at Azure Storage. | P03, P08 (contrast) |
| 7 | Human in the loop for irreversible actions | `require_approval` on `place_order`; refusal blocks the order, approval places it as the user. | P05 |
| 8 | Containment when something goes wrong | Kill switch (≈ 1 min; the four governed servers behind APIM - the private server is outside it, §5), client allow-list (≈ 1 min), per-user rate limit, entitlement drift via group removal (seconds), prompt injection: the wall refuses what the poisoned text asks for every time, a preview guardrail stops the run when it fires. | P09, P12, P14, P15, P16 |

## 2. The four walls (defence in depth — each wall denies on its own)

| Layer | Where | What it enforces |
|---|---|---|
| 0 | Foundry guardrail (agent) | RAI policy `abw-agent-guardrails`: prompt shields + tool-response *Indirect Attack* control, attached to `abw-wall-desk` and `abw-wall-desk-redteam-shielded`. **Preview and probabilistic:** when it fires, the poisoned tool result never reaches the model and the run ends `incomplete`; it fired on only some identical requests in this build (§12), so it is a *detective* layer (it feeds Sentinel ABW-008), not the control. Layers 1-3 are the deterministic ones. |
| 1 | APIM gateway (governed: `/research`, `/wall`, `/actions`, `/vendor`; the keyed contrast: `/legacy`) | One template (`infra\apim\policies\mcp-jwt.policy.xml`) rendered per MCP API by `05-apim-apis.bicep` (own audience and roles) and attached at **API scope** - nothing at global, product or operation scope: `validate-jwt` (sig, iss, aud, exp, tid) → claim authz: scope, app role, **client allow-list (`azp`)**, **kill switch (`oid`)**, rate limit 120 calls/60 s per `oid`. Emits metric `abw-gateway-decisions` + trace `abw-gateway`; sets `x-abw-request-id`. `/legacy` carries a different policy (`mcp-legacy.policy.xml`): subscription key and a per-key rate limit, no token check. The Private MCP is not behind APIM (§5). |
| 2 | MCP server (ACA) | Re-validates the JWT (never trusts the hop); role-filtered `tools/list`; tool rules (restricted list, separation of duties); no tool takes a user/role parameter; one audit event per decision. |
| 3 | Data plane | OBO token → Storage / Cosmos / Search RBAC **evaluated per request** — withdrawing a group membership denies access even though the token still says yes. |

Cross-cutting: **Azure Policy** (platform rules, §9) and **observability** (KQL pack, Sentinel, workbook, alerts, §9).

## 3. Naming (CAF-style) — `workload=abw env=demo region=eus2 instance=001`, `u4` = random suffix in `infra\generated\config.json` (four characters, different in every deployment)

| Thing | Name |
|---|---|
| Resource group | `rg-abw-demo-eus2-001` (eastus2) |
| VNet | `vnet-abw-demo-eus2-001` `10.42.0.0/16` |
| Subnets | `snet-agent` 10.42.0.0/24 (deleg. `Microsoft.App/environments`, Foundry agent injection) · `snet-pe` 10.42.1.0/24 · `snet-mcp` 10.42.2.0/24 (deleg. `Microsoft.App/environments`, ACA internal) · `snet-apim` 10.42.3.0/26 (deleg. `Microsoft.Web/serverFarms`, NSG, NAT) · `snet-jump` 10.42.4.0/27 (optional jump box, added by `07-jumpbox.bicep`; NSG, NAT) |
| NSG / NAT | `nsg-abw-apim-eus2-001` (snet-apim) · `nsg-abw-jump-eus2-001` (snet-jump: RDP only from inside the VNet, which is Bastion, and no inbound from the Internet) · `ng-abw-demo-eus2-001` + `pip-ng-abw-demo-eus2-001` on **snet-mcp and snet-apim** (they must reach Entra JWKS/OBO, Azure Monitor and the public vendor mock) and, when the jump box exists, on `snet-jump` (its browser must reach Entra and the portal). `snet-agent` and `snet-pe` have **no** NAT and no default outbound access: the Foundry agent runtime has no path to the internet. |
| Private DNS | 14 `privatelink.*` zones linked to the VNet (services.ai, openai, cognitiveservices, search, blob, documents, fabric, azurecr, vaultcore, monitor, oms, ods, agentsvc, azure-api) + ACA environment zone |
| Log Analytics / App Insights | `log-abw-demo-eus2-001` (30-day retention) · `appi-abw-demo-eus2-001` (workspace-based) · AMPLS `ampls-abw-demo-eus2-001` |
| Key Vault | `kv-abw-demo-eus2-<u4>` (RBAC, purge protection off for easy teardown) |
| UAMIs | `id-abw-mcp-{research,wall,actions,private,legacy,vendor}-eus2-001` |
| ACR | `crabwdemoeus2<u4>` (Standard, admin disabled, Entra RBAC) |
| Storage (demo data) | `stabwdemoeus2<u4>` (LRS, shared key off, PE-only) — containers `research-public`, `wall-falcon`, `wall-orion`, `worm-audit` |
| Cosmos | `cosmos-abw-demo-eus2-<u4>` serverless, local auth off, db `abw`, containers `restricted` (/ticker), `orders` (/user_oid), `positions` (/desk) |
| Search (demo data) | `srch-abw-deals-eus2-<u4>` Basic (**eastus** — eastus2 had no capacity on build day; PE stays in the VNet region), index `deals-idx` |
| ACA envs | `cae-abw-priv-eus2-001` (internal, `snet-mcp`) · `cae-abw-pub-eus2-001` (vendor mock, public) |
| Container apps | `ca-abw-mcp-{research,wall,actions,private,legacy,vendor}` (0.5 vCPU / 1 GiB, min 1 / max 2) · seed job `caj-abw-seed-eus2-001` (in-VNet) |
| APIM | `apim-abw-demo-eus2-<u4>` **StandardV2** ×1 (public gateway + PE `pe-apim-abw-demo-eus2-001`; outbound VNet integration) · logger `appi` |
| Agent front door (Act 7, additive) | API `abw-agent-frontdoor` at path `/agents` on the same APIM (`08-agent-frontdoor.bicep`, policy `infra\apim\policies\agent-frontdoor.policy.xml`) forwarding to the Foundry project Responses endpoint · named values `abw-agent-token-quota` (default 250,000 tokens per user per hour) and `abw-agent-rpm` (default 60 calls per user per minute) |
| Budget (Act 7, additive) | `budget-abw-demo-eus2-001` on the resource group, USD 1,200 a month, e-mail alerts at 50 / 80 / 100 % actual and 100 % forecast (`09-budget.bicep`) - an alert, not a cap |
| API Center | `apic-abw-demo-eus2-<u4>` (Free; MCP registry) |
| Foundry account / project | `aif-abw-demo-eus2-<u4>` (S0) / `proj-abw-wall-<u4>` · deployment `gpt-54-mini` (GlobalStandard, 100K TPM) |
| Agent-service BYO stores | `stabwasvc<u4>` (ZRS) · `cosmos-abw-asvc-eus2-<u4>` · `srch-abw-asvc-eus2-<u4>` (**separate** from demo data so the shared project identity can never read wall data) |
| Foundry connections | `mcp-research-oauth`, `mcp-wall-oauth`, `mcp-actions-oauth`, `mcp-vendor-oauth`, `mcp-private-oauth` (OAuth2 passthrough, client `abw-agent-client`) · `mcp-legacy-key` (custom-keys, the anti-pattern) |
| Agents | `abw-wall-desk` (v1 governed) · `abw-poc-legacy` (v0 typical POC) · `abw-wall-desk-redteam` · `abw-wall-desk-redteam-shielded` |
| Policy objects (subscription scope) | custom definitions `abw-foundry-no-keyed-connections`, `abw-foundry-approved-mcp-targets` · initiative `abw-agent-platform-controls` · RG assignment + exemptions `abw-ex-*` |
| Observability | KQL functions `Abw*` · Sentinel rules `ABW - …` · workbook `Agent Wall - Cockpit` · action group `ag-abw-ops-eus2-001` · alerts `alrt-abw-{agent-run-failures,mcp-server-errors,gateway-backend-errors}-eus2-001` |
| Jump box (optional) | VM `vm-abw-jump-eus2-001` (Standard_D2as_v7, Windows Server 2022 Datacenter Azure Edition, Trusted Launch, no public IP) · NIC `nic-abw-jump-eus2-001` · disk `osdisk-abw-jump-eus2-001` · Azure Bastion **Developer** `bas-abw-demo-eus2-001` (free, one session at a time) · auto-shutdown `shutdown-computevm-vm-abw-jump-eus2-001` (03:00 Central, never auto-starts). Local admin `abwadmin`; the password exists only in `.secrets\jumpbox.json`. It can also host the Demo Console (`C:\abw`, the desktop shortcut **ABW Demo Console**; `scripts\jumpbox-console.ps1`, section 10). |
| Entra objects | prefix `abw-`; users `abw.priya|wes|tara|carla|ian@<tenant domain>`; groups `sg-abw-*`; tagged `abw-demo` |

Tags on every resource: `workload=abw`, `env=demo`, `owner=<signed-in alias>`, `purpose=se-weekly-showcase`, `data=synthetic`, `delete-after=<date>` (derived by `Get-AbwConfig`).

## 4. Identities & roles (app roles are assigned to **users**, not groups - group-based assignment needs Entra P1, and the build is meant to run on a plain tenant)

Personas (Member users, random strong passwords → `.secrets\personas.json`, never in code):

| UPN prefix | Who | Research | Wall (Falcon) | Trade | Positions | MarketData |
|---|---|---|---|---|---|---|
| `abw.priya` | Public-side research analyst | `Research.Read` | – | – | – | `MarketData.Read` |
| `abw.wes`   | IB associate, wall-crossed on Project Falcon | `Research.Read` | `Wall.Falcon` | – | – | `MarketData.Read` |
| `abw.tara`  | Equity trader | `Research.Read` | – | `Trade.Execute` | `Positions.Read` | `MarketData.Read` |
| `abw.carla` | Compliance officer | `Research.Read` | `Wall.Falcon` (oversight) | `Trade.Read` | `Positions.Read` | `MarketData.Read` |
| `abw.ian`   | Infosec analyst (no agent use; workbook / Sentinel only) | – | – | – | – | – |

Groups (security, used for Azure RBAC — evaluated by the data plane, not by our code):
`sg-abw-research` (all but ian) · `sg-abw-wall-falcon` (wes, carla) · `sg-abw-traders` (tara) · `sg-abw-compliance` (carla) · `sg-abw-infosec` (ian) · `sg-abw-demo-all`.

### App registrations (one per MCP server; `requestedAccessTokenVersion=2`; Application ID URI `api://<appId>`)

| App | Scope(s) | App roles | Used by |
|---|---|---|---|
| `abw-mcp-research` | `Tools.Read` | `Research.Read` | research MCP |
| `abw-mcp-wall` | `Tools.Read` | `Wall.Falcon`, `Wall.Orion` | wall MCP |
| `abw-mcp-actions` | `Tools.Read`, `Tools.Execute` | `Trade.Read`, `Trade.Execute` | actions MCP |
| `abw-mcp-private` | `Tools.Read` | `Positions.Read` | private MCP |
| `abw-mcp-vendorgw` | `Tools.Read` | `MarketData.Read` | validated at APIM only (the vendor never sees the user token) |
| `abw-agent-client` | – (confidential web app) | – | Foundry OAuth passthrough client; delegated permissions to all five APIs; redirect URIs registered by `foundry-connections.ps1` |
| `abw-test-client` | – (public client) | – | `prove.py` persona sign-in (MSAL) |

For v2 tokens `aud` = the API app's **client-ID GUID**; `scp` carries delegated scopes; `roles` carries the user's assigned app roles.
Each MCP app has a **federated identity credential**: issuer `https://login.microsoftonline.com/<tenant>/v2.0`, subject = the server's **UAMI principalId**, audience `api://AzureADTokenExchange` ⇒ the server proves itself during OBO with no secret.

## 5. Token chain (the 4 hops) and the correlation id

1. User signs in (Foundry portal / SDK) → Foundry token (`aud=https://ai.azure.com`).
2. Foundry OAuth identity passthrough: the user consents once per connection → token for `aud=<abw-mcp-*>` (client = `abw-agent-client`).
3. APIM gateway: `validate-jwt` + claim authz + kill switch + allow-list + rate limit → MCP backend (ACA, VNet).
4. MCP server re-validates the JWT, then **OBO** (`client_assertion` = UAMI token for `api://AzureADTokenExchange`) → Storage / Cosmos / Search **as the user**.

Direct path (private MCP): Foundry (injected `snet-agent`) → `ca-abw-mcp-private` internal FQDN; the token is validated by the server itself. This path never touches APIM, so the kill switch does not reach it: a revoked user keeps it until the token expires (read from the code, not exercised live). Production fix: an internal APIM in front, or have the server read the same deny list.
External path: Foundry → APIM `/vendor/mcp` → APIM validates the user JWT, injects the vendor key from a Key Vault named value → vendor mock (public ACA).
Legacy path (v0 "typical POC"): Foundry → APIM `/legacy/mcp` with a shared APIM subscription key → server runs with a broad shared identity.
Agent front door (Act 7, additive): user -> APIM `/agents` (validates the user's Entra token, kill switch, per-user rate limit and token budget, one token metric per user and agent) -> Foundry project Responses endpoint, with the user's own token forwarded unchanged; the agent's tool calls then return through APIM as above (the private server excepted).

**`request_id`** — APIM mints/forwards `x-abw-request-id`; the gateway decision trace, the MCP audit event (`request_id` field), soft-denial payload and data-plane log row all carry it, so `AbwIdentityChain('<request_id>')` returns user → agent → gateway → server → data plane for one call (P10), and `AbwFullChain('<any id>')` widens that to the whole run - Entra sign-in and token, front door, guardrail, agent, model, each tool call, gateway, MCP audit, data plane, Sentinel alert and incident - from a tool-call request id, the front-door id or the trace id.

## 6. MCP servers & tools (Python, official `mcp` SDK, streamable HTTP, `stateless_http=True`, `json_response=True`, path `/mcp`, port 8080)

One image `abw-mcp` (all servers), selected by `MCP_SERVER`. Shared package `abw_mcp` (JWT verify via JWKS, role-filtered `tools/list`, OBO, audit). Details: `src\mcp\README.md`.

| Server | Required (all calls) | Tools | Data plane (as the user via OBO unless noted) |
|---|---|---|---|
| research | scp `Tools.Read` + role `Research.Read` | `search_research`, `get_research_note` | Blob `research-public` + Search filter `classification eq 'public'` |
| wall | scp `Tools.Read` + role `Wall.Falcon` or `Wall.Orion` | `list_my_wall_crossings`, `search_deal_documents(project)`, `get_deal_document` | Blob `wall-<project>` (Storage RBAC decides) + Search filter built from **token roles**, never from the prompt |
| actions | scp `Tools.Read`; `place_order` needs `Tools.Execute` + role `Trade.Execute` | `check_restricted_list`, `place_order`, `list_my_orders` | Cosmos `restricted` (server identity), `orders` (user OBO) |
| private | scp `Tools.Read` + role `Positions.Read` | `get_firm_positions`, `get_credit_limit` | Cosmos `positions` |
| vendor (mock, external) | header `x-vendor-key` | `get_market_quote`, `get_headlines` | none (synthetic; headline text is the prompt-injection carrier for P09) |
| legacy | APIM subscription key only (no user context) | all of the above, unfiltered | server's broad UAMI (`Storage Blob Data Reader` on **all** containers) |

Rules in code (defence in depth, each independently denies):
- `tools/list` is filtered by the caller's roles (the model cannot call what it cannot see; a role-less user gets an empty list and `403 missing_role` on `tools/call`).
- `place_order`: (a) restricted-list hit → `WALL_VIOLATION` block; (b) any caller holding a `Wall.*` role is barred from trading restricted names (separation of duties — unit-tested; see §11 edges); (c) Foundry `require_approval` makes a human approve first.
- Wall docs: never return content for a project the token's roles don't include; Storage denial is surfaced and logged as `wall_violation_attempt`.
- No tool accepts a user/role/group parameter — identity comes only from the validated token.
- **Soft denials** (`MCP_DENIAL_MODE=soft`, default): a policy denial returns HTTP 200 with `structuredContent {decision:"DENIED", error, message, request_id}` so the model can *explain* the block (e.g. `project_not_in_token_roles`, `restricted_list`). `strict` returns MCP `isError`. Gateway-level denials stay HTTP 401/403 JSON `{error, reason, server, request_id}`.

### Audit event (one JSON per decision; log message `abw.audit` in App Insights `AppTraces` + append blob in `worm-audit`)
```
ts, event(tool_listed|tool_call|tool_denied|auth_failed|wall_violation_attempt|order_blocked|order_placed),
server, tool, decision(allow|deny), reason, user_oid, user_upn, tid, roles[], scp, azp, aud, jti,
obo(bool), downstream{service,target,status}, data_class(public|wall:falcon|wall:orion|internal), args_sha256,
result_bytes, trace_id, request_id
```
Never log tool arguments or document content — only hash + size.

## 7. Environment variables (every server)

`MCP_SERVER`, `TENANT_ID`, `MCP_APP_CLIENT_ID`, `MCP_ALLOWED_AZP` (comma list), `MCP_REQUIRED_SCOPE`, `UAMI_CLIENT_ID`, `STORAGE_ACCOUNT`, `COSMOS_ENDPOINT`,
`SEARCH_ENDPOINT`, `SEARCH_INDEX`, `COSMOS_DATABASE`, `COSMOS_OBO`, `AUDIT_STORAGE_ACCOUNT`, `AUDIT_CONTAINER=worm-audit`, `MCP_DENIAL_MODE`,
`APPLICATIONINSIGHTS_CONNECTION_STRING`, `LOG_LEVEL`, `PUBLIC_BASE_URL`. Vendor mock only: `VENDOR_API_KEY` (ACA secret → Key Vault reference via UAMI).

## 8. Foundry objects

- Account `aif-abw-…` (local auth/keys disabled; public network access ON for the portal and operator laptop — policy-exempt, documented; network-injected agent subnet; BYO Cosmos/Search/Storage for Agent Service), project `proj-abw-wall-<u4>`, deployment `gpt-54-mini` (GlobalStandard, 100K TPM).
- Connections: five OAuth2-passthrough remote-tool connections (`mcp-{research,wall,actions,vendor,private}-oauth`; targets = APIM `/<server>/mcp`, private = ACA internal FQDN `/mcp`) + `mcp-legacy-key` (custom-keys header `Ocp-Apim-Subscription-Key`).
- Agents (all `PromptAgentDefinition`, `MCPTool` per server with `project_connection_id`, `allowed_tools`, `require_approval` — `always` for `place_order`):
  `abw-wall-desk` (v1 governed + guardrail) · `abw-poc-legacy` (v0: one tool, shared key, `require_approval=never`) · `abw-wall-desk-redteam` (over-compliant instructions, no guardrail — lets the *server-side* denials be seen) · `abw-wall-desk-redteam-shielded` (same + guardrail — P09).
- Personas get **Foundry Agent Consumer** (runtime-only, the least-privilege end-user role) on the project through group `sg-abw-demo-all`; the operator holds **Foundry User** on the account. Each persona must consent once per OAuth connection (5 consents).
- Guardrail: `raiPolicies/abw-agent-guardrails` on the account; agents reference it by **fully qualified ARM id** (a bare name is rejected).

## 9. Governance & observability (as deployed)

**Azure Policy — initiative `abw-agent-platform-controls`** (5 families, assigned at the RG with exemptions `abw-ex-*` for the documented edges):
`ABW-01-NO-KEYS` (AI-services/Storage/Cosmos/Search local-auth disabled, Key Vault RBAC, ACR admin off, **no keyed Foundry connections** — custom) ·
`ABW-02-PRIVATE` (Cosmos/Storage/Search public access, AI network restriction, ACA env) ·
`ABW-03-TOOLS-MODELS` (**approved MCP targets** — custom; preview data-plane policies for approved tools/models) ·
`ABW-04-GUARDRAILS` (jailbreak + indirect-attack filters on agents) ·
`ABW-05-HYGIENE` (ACA HTTPS-only, managed identity).
`demo\try-violations.py` makes **9 real ARM attempts**: storage shared key, Cosmos local auth, Search local auth, Key Vault access policies, ACR admin user, Foundry local auth, keyed Foundry connection, unapproved MCP target + a compliant positive control. In a tenant with nothing else assigned, each unsafe attempt is rejected (HTTP 403 `RequestDisallowedByPolicy` naming the assignment and control) and the control is accepted (202). **Policy layers.** The tenant this build runs in carries an organisation baseline (a governance initiative assigned at the tenant-root management group) whose *Modify* policies rewrite shared-key, local-auth and public-network settings on the way in, and Azure Policy evaluates Modify before Deny. Measured here: **5 denied** (Search, Key Vault, ACR admin, keyed Foundry connection, unapproved MCP target), **3 created safe** (storage, Cosmos, Foundry local auth - the stored resource no longer carries the unsafe setting, and the initiative still flags the original request body), 1 compliant control allowed. Nothing unsafe survives either way; the harness records which layer acted (`CORRECTED` vs `BLOCKED`). Compliance snapshot at last run: 69 Compliant / 8 Exempt / 1 NonCompliant (`foundry-approved-tools` - the legacy path, by design). Foundry data-plane (agent tool / model / guardrail) policies are **preview, compliance-reporting only** — create-time Deny is not enforced for them, so they ship as Audit.

**Observability pack** (`observability\`, deployed by `-Stage observability`):
- 10 workspace KQL functions: `AbwGateway`, `AbwMcpAudit`, `AbwUsageByUser`, `AbwZeroKeys`, `AbwAgentActivity`, `AbwDenials` (layers 0 guardrail / 1 gateway / 2 MCP / 3 data plane), `AbwIdentityChain(request_id)`, `AbwFullChain(any id [, lookback [, tokenIds]])` (the whole run for one request id, tool-call id or trace id: Entra sign-in → APIM front door → Entra token issued → tool discovery → Foundry guardrail, agent, model and tool calls → APIM gateway → MCP audit → Storage, Search and Cosmos → APIM policy → Sentinel alert and incident; Search and Cosmos rows are matched by time because those logs carry no caller; sources land in stages, the last about 9-13 minutes after the event), `AbwFullChainCore` (the same without the two Entra row types; `AbwFullChain` is built on it), `AbwTokenUsage` (Act 7: model tokens per user and agent per hour, from the front door's token metric).
- **Entra rows in the full chain.** Identity logs live in the tenant's security workspace and application logs in this one; one claim joins them: the token id (`uti`), which the MCP audit row records and Entra logs as `UniqueTokenIdentifier`. `AbwFullChain` reads the tenant's existing Entra sign-in export (`SigninLogs`, `AADNonInteractiveUserSignInLogs`) across workspaces by resource id (`entraWorkspaceId` in `infra\generated\config.json`; **read only**: nothing is written there and no Entra diagnostic setting was added) and adds the sign-in that started the session (password, MFA) and the token issued for each MCP server, with the Conditional Access verdicts (the report-only policy included) and the city and country, never the IP. The optional third argument `tokenIds` (comma-separated `uti` values) exists because a call the gateway refuses never reaches an MCP server, so no audit row carries its token id: the Demo Console passes the id of each token it sent, and those runs show "Entra issued the token, the gateway refused it". Edges: Entra exports a token row about 4-8 minutes after it is issued (non-interactive sign-ins can lag longer); a token is reused until it expires, so the sign-in can be days older than the call (set the portal time range to Last 30 days); agent runs refused at the front door, and calls made outside the console, carry no known token id. Without `entraWorkspaceId` the pack deploys `AbwFullChain` as a copy of `AbwFullChainCore` (the Bicep fallback), and the console falls back to `AbwFullChainCore` when the cross-workspace read fails.
- 9 Sentinel analytics rules (`ABW-001…009`): wall-violation (High/Collection) · restricted-order (High/Impact) · legacy-no-identity (Medium/Credential Access) · client-not-allowed (High/Initial Access) · revoked-principal (High/Impact) · repeated-denials (Medium/Discovery) · entitlement-drift (High/Privilege Escalation) · guardrail-intervention (High/Execution) · throttled-burst (Low/Impact). Rules run every 5 min; plus ~5 min ingestion lag.
- Cockpit workbook `Agent Wall - Cockpit` (usage, identity chain, governance posture, threats, gateway, cost & tokens, zero-keys, change log) · 3 scheduled-query alerts → action group `ag-abw-ops-eus2-001` (email only if `alertEmail` is set).

**Agent front door and FinOps (Act 7; added after the final proof run, additive).** `08-agent-frontdoor.bicep` publishes `/agents` on the same APIM. It validates the caller's Entra token, checks the kill switch, rate-limits per user (`abw-agent-rpm`, 60 calls a minute), enforces a per-user hourly token budget (`llm-token-limit`, `abw-agent-token-quota`, 250,000) and emits a token metric per user and agent (`llm-emit-token-metric`), then forwards the user's own token unchanged to the Foundry project's Responses endpoint - so Foundry still authorises the person and OAuth passthrough still reaches every MCP server as that person. `09-budget.bicep` adds a monthly budget on the resource group: an **alert** (mail to the Owners at 50 / 80 / 100 % actual and 100 % forecast), **not a cap**; what stops runaway use is the per-user token budget. Edges: Foundry's own endpoint still answers a valid token while its public network access is on (a private endpoint would make the front door the only way in); the token budget is counted after the response, so one call can overshoot it; a rate-limit lock-out lasts about two minutes; Azure cost data arrives hours late. Deploy with `deploy.ps1 -Stage frontdoor` (after `apim`) and `-Stage budget`.

**Operator controls:** `scripts\kill-switch.ps1` (`-User wes [-RevokeSessions]`, `-Restore`, `-Reset`, `-Show`; writes APIM named value `abw-deny-oids`; first refusal 45-90 s) · `scripts\client-allowlist.ps1` (`-Block azcli`, `-Reset`, `-Show`; writes `abw-allowed-azp`; 45-90 s) · `identity\Use-AdminAsPersona.ps1` (test helper).

## 10. Deploy stages (`scripts\deploy.ps1 -Stage <n>`, each idempotent; `-WhatIf`, `-NoWait`)

| Order | Stage | Artifact |
|---|---|---|
| 0 | `identity\Setup-Entra.ps1 -Phase 1` | users, groups, apps, roles, grants |
| 1 | `preflight` → `network` | providers/quota checks · `01-network.bicep` (VNet, subnets, NSG, NAT, private DNS zones + links) |
| 2 | `foundry` → `foundryrbac` | vendored Foundry network-secured template `infra\foundry\main.bicep` (see `PATCHES.md`) · `02-foundry-rbac.bicep` |
| 3 | `platform` | `03-platform.bicep` — UAMIs, KV, ACR, Storage(+WORM), Cosmos, Search, ACA envs (+DNS), diagnostics, RBAC, private endpoints |
| 4 | `scripts\build-images.ps1` (`az acr build`) → `apps` | `04-apps.bicep` (container apps) |
| 5 | `identity\Setup-Entra.ps1 -Phase 2` | federated identity credentials (UAMI principals) |
| 6 | `apim` → `apis` | `05-apim.bicep` (service, PE, named values, logger, API Center) · `05-apim-apis.bicep` (MCP APIs, policy `mcp-jwt.policy.xml`, PRM, legacy) |
| 7 | `build-images.ps1 -Target seed` → `seed` | `04b-seed-job.bicep` — in-VNet ACA job loads synthetic Blob/Search/Cosmos data (data planes are PE-only; the laptop has no stable egress IP) |
| 8 | `scripts\foundry-connections.ps1` → `src\agent\create_agents.py --rai abw-agent-guardrails` | 6 connections + redirect URIs, 4 agents |
| 9 | `governance` (06a → 06 → 06b) / `observability` | policy definitions → assignment, exemptions, guardrail, diagnostics → KQL pack, Sentinel rules, workbook, alerts |
| 10 | `python demo\prove.py` · `python demo\scoreboard.py --check` | evidence in `demo\evidence\`, `SCOREBOARD.md` |
| + | `frontdoor` → `budget` (optional, additive; `frontdoor` runs after `apim`) | `08-agent-frontdoor.bicep` (API `abw-agent-frontdoor` at `/agents`, named values `abw-agent-token-quota` and `abw-agent-rpm`) · `09-budget.bicep` (monthly budget on the resource group). Remove the front door with `az apim api delete --api-id abw-agent-frontdoor`. |
| + | `scripts\jumpbox.ps1` (optional; needs the VNet and NAT gateway from `network`, and the private endpoints from `platform` for its check to mean anything) | `07-jumpbox.bicep` - `snet-jump`, its NSG, the VM, Azure Bastion Developer and the auto-shutdown schedule; then `jumpbox-check.ps1` runs inside the VM (private DNS resolves, outbound works). `-Stop` / `-Start` / `-Status` / `-Remove`. **Do not re-run `deploy.ps1 -Stage network` while it exists** (`01-network.bicep` declares the subnets inline): run `jumpbox.ps1 -Remove` first. |
| + | `scripts\jumpbox-console.ps1` or `Deploy-JumpBox-Console.bat` (optional; after the jump box) | installs the Demo Console on the jump box, nothing else in Azure: starts the VM if it is off, then `jumpbox-console-setup.ps1` runs inside it as SYSTEM in phases (tools: Python 3.11, Azure CLI and PowerShell 7, each installer's signature checked; package: a whitelisted, secret-scanned zip sent as base64 chunks through Azure run commands and checked by SHA-256; venv; launcher: the desktop shortcut **ABW Demo Console** that runs `jumpbox-console-start.ps1`; verify). `-IncludePersonaFiles` also copies `personas.json`, `totp.json` and `msal-test-*.json` into `C:\abw\.secrets` (locked to SYSTEM and `abwadmin`); `-RemovePersonaFiles`, `-Remove`, `-Status`, `-Verify`, `-WhatIf`, `-Force`. |
| ⌫ | `scripts\teardown.ps1 [-WhatIf]` | report-only CA policy + Agent 365 grant → capability hosts → Log Analytics → RG → soft-delete purge → policy objects → Entra |

## 11. Proof scenarios (`python demo\prove.py [--list|--only P05|--group core|agent|ops|policy|verify]`, each writes an evidence JSON)

| Proof | Layer | Headline | Checks |
|---|---|---|---|
| P00 | platform | Baseline preflight (identity, roles, gateway, kill switch, allow-list) | 5 |
| P01 | platform | **No keys** — every data service Entra-only; 0 key-based storage requests | 17 |
| P02 | gateway + servers | **Least privilege** — no role, no tools (empty `tools/list`, 403 `missing_role`) | 10 |
| P03 | server + data plane | **Information barrier** — Falcon yes, Orion no, decided on the user's token | 6 |
| P04 | server | **Trading controls** — restricted list blocks; clean order carries the user's identity | 5 |
| P05 | Foundry agent | **Human approval gate** — refuse → blocked, approve → order placed | 4 |
| P06 | network + agent | **Private MCP** — unreachable from the internet/laptop, reachable by the injected agent | 4 |
| P07 | gateway | **External vendor MCP** — gateway authenticates the user, holds the key | 4 |
| P08 | gateway + agent | **The legacy path** — one shared key, Orion leaks: same question, two answers | 4 |
| P09 | wall + guardrail | **Indirect prompt injection** — the wall refuses what a poisoned headline asks for (replayed, deterministic); the preview guardrail stops the run when it fires (asked until it fires once) | 8 |
| P10 | observability | **One request id answers the auditor** — agent → gateway → server → data plane | 7 |
| P11 | Azure Policy | **Policy as code** — 9 attempts, none leaves an unsafe resource (5 denied · 3 created safe by the org baseline · 1 compliant allowed) | 3 |
| P12 | gateway | **Kill switch** — ≈ 1 min (42-66 s in the harness, 88 s hand-run) | 8 |
| P13 | Sentinel | **Detection** — every attack became an incident (judged on the *event* time inside the alert and incident, so a re-alert of an older run's events cannot pass) | 9 |
| P14 | gateway | **Abuse control** — 400 calls in a few seconds → ≈ 125-133 × 200 / ≈ 267-275 × 429 (120/min budget, refilling 2/s) | 4 |
| P15 | gateway | **Stolen-token defence** — client allow-list, ≈ 1 min (46-59 s in the harness, 56-83 s hand-run) | 4 |
| P16 | data plane | **Entitlement drift** — group removal → Storage RBAC denial in under a minute (5-44 s measured) | 4 |
| P17 | observability | **The pack is healthy** — functions, rules, workbook | 3 |

## 12. Learnings / as-built gotchas (so the next build is faster)

- **Foundry:** connection names are `mcp-*-oauth`/`mcp-legacy-key`; guardrail references need the full ARM id; the OAuth redirect URIs are only known after the connections exist (`foundry-connections.ps1` registers them on `abw-agent-client`); the first agent call per persona returns a consent link per connection; a vendored network-secured template lives in `infra\foundry` with local patches in `PATCHES.md`. Foundry holds each user's OAuth access token for its whole life: it mints it at the first agent call after the previous one expired and reuses it (measured from the MCP audit `jti`: two sets of tokens were each used for 39–51 min, and a third set minted at 22:43:52Z expired at ≈ 73 min (wall, private) and ≈ 90 min (actions); Entra lifetimes are 60–90 min), so a role change reaches the *agent* only when that token expires — pair removal with the kill switch (gateway) and group removal (data plane). The same fact is why `identity\Use-AdminAsPersona.ps1` flips gateway beats instantly but cannot switch the persona of an agent beat (see RUNBOOK §2), and why the proof harness runs the agent proofs before it flips any role.
- **Networking:** every data plane is PE-only and the laptop has no stable egress → data is seeded from an **in-VNet ACA job**; Search lives in `eastus` (PE in `eastus2`); flaky local DNS is handled by `src\agent\netfix.py`.
- **APIM:** MCP API type needs the `2025-09-01-preview` API; policy gotchas — RFC 9728 PRM (`prm.policy.xml`), discovery methods (`initialize/ping/tools/list/notifications`) allowed without a role only when the server's `__LIST_OPEN__` flag is set; `rate-limit-by-key` per `oid`.
- **Entra:** app roles go to **users** (group-based assignment needs P1; the build does not depend on it); AAD returns **all consented scopes** to Azure CLI (so `missing_scope` is unit-tested, not a live demo); roles are **per API audience**, so the Wall/Trade separation-of-duties branch is unit-tested only; role-claim propagation lags up to ~30 s (vendorgw removal lags longer) — always request a new token. **Consent order matters:** apply the persona role baseline *before* the first agent consent - Foundry stores the token it gets then (60-90 min) and a role-less one leaves agents with empty tool lists (≥ 14-20 min after the roles are fixed; republish with `create_agents.py --rai abw-agent-guardrails`).
- **Soft denial** (HTTP 200 + `decision:"DENIED"`) is what lets the model *explain* a block and cite `request_id`; the red-team agent exists because a polite model self-checks under safe prompts and never reaches the server-side denial.
- **Prompt injection:** gpt-5.4-mini resists even a crude injection with over-compliant instructions (both the unguarded and the shielded agent answered "I did not carry out the embedded notice"), so an A/B of "the unguarded agent gets hijacked" does not materialise and the model is not the control either way. The proof therefore (a) replays what the poisoned headline asks for - read Orion, buy 5,000 ZYNX - against the live wall, which refuses it every time (a denial prints as status `ok` with `"decision":"DENIED"` in the body, so the invariant is content-based); (b) asserts that in every run nothing the notice asked for executed or leaked; and (c) treats the Foundry guardrail as **best effort**. It is a preview control that stops the run (`incomplete`, "returned no result", `content_filter`) on only some identical requests - measured 3/20, 5/8, 3/10, 2/10, 1/9, 1/10, 1/11 in this tenant (3/3 in the earlier one), varying over time, and unchanged by policy variant (full policy, without the auto-added DefenderForAI entries, only the post-tool Indirect Attack filter). When it does not fire the whole tool-stage guardrail is skipped, not "evaluated negative". Tool-call/response intervention points are documented as needing tool-side support and MCP is not in the documented list. The harness asks up to 40 times until it fires once, and the blocked trace plus the ABW-008 alert are the stage evidence. A deterministic Layer-0 alternative - Prompt Shields on the tool result at the gateway or in the server, keyless via managed identity - is the follow-up (note the APIM warning that reading the response body of an MCP API breaks streaming).
- **KQL:** `last` is reserved; `has` is term-based (use `contains 'ABW-0'`); ABW-005 needs `Reason == 'revoked'`; the MCP SDK emits extra `tool_listed` rows (filtered in the functions).
- **Azure Policy:** Foundry data-plane policies are compliance-reporting only (create-time Deny not enforced → Audit); legacy keyed connection is **non-compliant/exempt by design**. **Layering:** an org baseline assigned higher up (management group / tenant root) can run `Modify` effects *before* this initiative's `Deny`, so a "break the rule" attempt can succeed and come back safe (storage, Cosmos and AI-services local auth / public network here). Test for the stored state, not just the HTTP code, and never bypass the baseline to make a demo look stricter. **Defender for AI:** when the Defender for Cloud *AI services* plan is on, Foundry adds `DefenderForAI` entries to every guardrail policy; they do not change whether the Indirect Attack filter fires.
- **azd:** `foundry-connections.ps1` needs the azd extension `azure.ai.connections`; if azd is signed in to another tenant give it its own config dir (`$env:AZD_CONFIG_DIR`, `azd config set auth.useAzCliAuth true`). To reset a stored consent, ARM-DELETE the connection id (api `2025-06-01`) and re-run the script with `-Only <name>`; `-Force` alone keeps the stored token. The first `governance` deploy in a brand-new tenant can fail once with `CheckAccessPrincipalCreationConcurrencyError` - wait ~75 s and re-run.
- **Windows tooling:** the `az` shim breaks on `)` and unquoted special characters inside `--query` → keep queries trivial and filter in PowerShell; Graph `$filter` on `companyName` needs `$count=true`; use Python `AzureCliCredential(process_timeout=90)` for ARM.

## 13. Honest edges (say them on stage)

- Entra access tokens live 60–90 min (and Foundry reuses one for its whole life — it was the same `jti` for 39–51+ min in our audit); CAE isn't available for custom APIs → pair **group/role removal** (durable, under a minute at the data plane) with the **APIM deny-list kill switch** (≈ 1 min).
- Foundry OAuth passthrough for a custom MCP uses a confidential client (`abw-agent-client`) whose secret is stored in the Foundry connection (rotate; never in code).
- App Insights ingestion uses a connection string (a secret in the container-app config; policy-exempt) and Log Analytics ingestion keys are still enabled — keyless telemetry (Entra-auth ingestion + `Monitoring Metrics Publisher`) is the follow-up.
- WORM container uses an **unlocked** time-based policy and synthetic data: demonstrates the pattern, not a compliance attestation (SEC 17a-4 / CFTC need a locked policy + your counsel).
- The core demo depends on no Entra P1/P2 feature. The governance extras were added in the M365 E7-licensed tenant used for the final proof, and each one carries an honest status (README, the console, CUSTOMER-GUIDE section 7). **Live:** Agent 365's gateway integration (on since 2026-10-25: it lists the five MCP servers and the four agents, and a block on the legacy server was enforced by APIM within about 15 seconds, then reverted), Entra Agent ID identities (an inventory: tool calls carry the user's token), Defender for AI (Standard) with one real alert, the Sentinel connector and nine rules, the Foundry Control Plane, API Center. **Configured, not proven:** one report-only Conditional Access policy (nothing evaluated yet); the Defender-alert-to-Sentinel hop (not observed about 90 min after the alert); Defender XDR Security for AI agents and Purview DSPM for AI (both switched on 2026-10-25 in audit mode, no evidence yet). Identity Protection, sign-in-log export and Temporary Access Pass are not configured. Never claim the unproven ones as built.
- Both tenants this was built in force MFA for every user (the second through Microsoft-managed Conditional Access) and block, or make impractical, authenticator registration for the demo personas. Persona sign-in therefore needs a one-time TOTP enrolment from an allowed network or device (store the secret with `identity\Persona-Totp.py`) - **not exercised in the second tenant**. Until then `identity\Use-AdminAsPersona.ps1` mirrors a persona's roles/groups onto the signed-in admin so every server, gateway and data-plane rule can be exercised with real Entra tokens (`oid` in audit rows = the admin) — at the gateway; an agent beat keeps the roles of the token Foundry already holds (60–90 min), so agent beats stay on the baseline roles. Only the admin has consented to the agent connections. The console's **Acting as** switcher (gateway beats only) reuses the same per-persona sign-ins; it was built and checked after the final proof run. Priya and Ian have since signed in through it once (2026-10-23) and Act 7 ran their tabs live as them; Wes, Tara and Carla have not, so what they see on a gateway beat is the designed result, not an observed one.
- Preview features in use: APIM MCP API type (`2025-09-01-preview`), Foundry accounts/projects/connections (`2025-04-01-preview`), guardrail `raiPolicies` (`2026-07-15-preview`, tool-response Indirect Attack - **best effort, fires on only some requests**), Foundry data-plane policies, API Center/Search management previews. GA-versus-preview status of Entra Agent ID, Conditional Access for agents, Defender for AI services, the Foundry Control Plane and network-injected Agent Service was not re-verified for this build. As read on Learn: Agent 365 core is GA, Defender XDR's AI agent detection and the APIM AI Gateway tier are preview, and Purview's classic DSPM for AI retires on 2026-11-30 (the Foundry compliance setting is the path used here).
- Public surfaces that remain (documented, exempt): APIM public gateway (the entry point — protected by layer 1), Foundry account public access (portal/laptop), ACR public network.
- **Jump box (optional, added after the final proof run).** A VM inside the VNet reached through Azure Bastion Developer, so the private data-plane pages can be opened in the portal. Bastion Developer needs a password, so the VM has a **local admin account** (`abwadmin`, password only in `.secrets\jumpbox.json`): demo plumbing outside the keyless story. It has no public IP, and its NSG allows RDP only from inside the VNet. The operator holds **no direct data-plane roles** by design (data access is by group, on behalf of the user, and a direct role would break P16, entitlement drift), so the Storage, Cosmos and Search data explorers may show partial or denied results. Verified from inside the VM: private DNS, outbound through the NAT gateway, RDP listening. **Not observed:** the Bastion browser session, the portal sign-in from the VM, and what each page shows. Never re-run the `network` stage while `snet-jump` exists.
- **The Demo Console on the jump box (optional, added 2026-10-24).** The console runs on the VM, not in a Container App, on purpose: it is a local app on `127.0.0.1` that uses the operator's own `az` sign-in, and hosting it would need a second identity model (a managed identity or a stored secret) in a demo about the first one. From the VM every call and every portal data page travels the private endpoints. The package is a whitelist (code, policy XML, KQL and Sentinel packs, generated infra JSON, scrubbed evidence) scanned for secret patterns and for every value held in `.secrets` before it is sent; it carries no key, token, persona password or one-time-code seed. The operator signs in once on the VM with a device code, and the Azure CLI keeps that token in the VM admin's own cache. **Persona sign-in files are an opt-in widening of where secrets live** (`-IncludePersonaFiles`; `personas.json` holds the demo passwords, `msal-test-*.json` are plain refresh-token caches, `totp.json` seeds if any): the folder is locked to SYSTEM and the VM's local admin but not encrypted, so a local administrator can always take ownership of it; the VM and laptop copies diverge once either refreshes; Azure's run-command agent keeps an admin-only encrypted copy of each script it ran, and the plain-text upload script is emptied by the setup (a search of the agent's folder after the real run found none); PowerShell script-block logging on the VM was not checked. `-RemovePersonaFiles` or `-Remove` wipes them. **Observed from inside the VM:** the tools, 99 package files identical to the checkout, a throw-away console on port 8799 serving every page (scoreboard: 18 proofs), 11 of 11 private names resolving to 10.42.1.x, APIM answering 401 with the resource-metadata challenge when called with no token from its private address, and a silent sign-in from the VM's NAT address for Priya and Ian. **Not observed:** the Bastion browser session, the device-code sign-in on the VM, the console signed in end to end there, and Wes, Tara and Carla on the VM (they have no cached sign-in).
- **Act 7 (roles, the agent's front door, cost) was added after the final proof run and is not part of the 18 proofs.** It runs through the console and is documented scenario by scenario in PROOF-PLAYBOOK section 11. Live: the front door (401s, the forwarded Foundry-audience token, token counting and the 403 when the budget is cut), the FinOps board, Priya, Ian and the Admin tab (ten of its eleven scenarios). **Designed, not run:** Wes, Tara and Carla until each signs in once; the poisoned-feed scenario; the private MCP server for the five people (it is outside APIM and only the Admin tab's agent run reaches it). The 250,000-token and 60-call limits are demo defaults, not a sizing.
- Rate limit is 120 calls / 60 s **per user** at the gateway; Sentinel needs a few minutes of ingestion + ≤ 5 min rule cadence (alerts appeared within ~8 min of the traffic; ~13 min for the Storage-sourced ABW-007).
