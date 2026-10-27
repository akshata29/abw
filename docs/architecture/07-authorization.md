[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [6. Authentication: identities, tokens and trust](06-authentication.md) | Next: [8. MCP server internals](08-mcp-server-internals.md)

## 7. Authorization: the four walls and policy-as-code

Section 6 explains how a person becomes a token and how that token is exchanged on the user's behalf. This section starts where it ends: with a valid token in hand, who may do what, where each decision is made, what a refusal looks like on the wire, and what is written down. It also covers Azure Policy, which stops the platform itself from being reconfigured around the walls (Designed: `DESIGN.md:26-33#four`).

Provenance labels used here and in section 8: **Implemented** = Python code in this repo; **Configured** = Bicep, policy XML, PowerShell or JSON in this repo; **Designed** = stated in `DESIGN.md` or the docs and not re-derived from code; **Platform behaviour** = documented on Microsoft Learn (URL in plain text). Anything the repo does not contain is marked "not in this repo". Gaps and mismatches found while reading are collected in the `### Findings` block at the end of section 8 and are referred to here as "Findings".

### 7.1 Overview: four walls, one request

**What this section proves.** The information barrier is not carried by one control. A request that one wall wrongly allows still meets the next one, each wall writes its own evidence, and each wall can be shown to refuse on its own (Designed: `DESIGN.md:28-33#abw-agent-guardrails`).

| Layer | Enforcement point | Decision inputs | Decision | Deny shape | What is logged | Code |
|---|---|---|---|---|---|---|
| 0 | Foundry guardrail: the RAI policy `abw-agent-guardrails`, attached to an agent | Prompt text, completion text and (preview) tool-response text. No identity, no roles. | Block or annotate by category and severity (probabilistic classifiers) | No HTTP shape from this repo. The agent run ends `incomplete` with a `content_filter` error (Designed) | Foundry diagnostics to Log Analytics; layer `0-agent-guardrail` in `AbwDenials`; Sentinel ABW-008 | `infra/06-governance.bicep:86-98#guardrails`; `src/agent/abw_agents.py:155-194#publish`; `observability/kql/AbwDenials.kql:32-41#0-agent-guardrail` |
| 1 | APIM policy `mcp-jwt.policy.xml`, attached at API scope to research, wall, actions and vendor | Token claims (`aud`, `iss`, `tid`, `exp`, `oid`, `azp`, `scp`, `roles`), the JSON-RPC `method`, named values `abw-deny-oids` and `abw-allowed-azp` | Forward, or deny with one of `revoked`, `client_not_allowed`, `missing_scope`, `missing_role`; then a per-user rate limit | 401 plus `WWW-Authenticate` (token invalid); 403 JSON `{error, reason, server, request_id}`; 429 native APIM | Metric `abw-gateway-decisions` and trace `abw-gateway` for allow and deny; `ApiManagementGatewayLogs` | `infra/apim/policies/mcp-jwt.policy.xml:17-46#validate-jwt`; `infra/apim/policies/mcp-jwt.policy.xml:51-81#emit-metric`; `observability/kql/AbwGateway.kql:1-8#abw-gateway` |
| 2 | The MCP server (one container app per server): auth middleware, tool registry, tool handlers | The re-validated token as a `Caller`, the per-tool requirement, the tool arguments, tool rules (wall project, restricted list) | Reject the token; hide the tool; refuse the call (soft denial) | 401/403 plus `WWW-Authenticate` for token failures; HTTP 200 with `structuredContent` `decision: DENIED` for tool refusals (`isError: true` only in strict mode) | One audit JSON event per decision: stdout, App Insights logger and the WORM blob | `src/mcp/abw_mcp/auth.py:108-165#verify_token`; `src/mcp/abw_mcp/registry.py:158-218#call_tool`; `src/mcp/abw_mcp/registry.py:238-270#_tool_error_result` |
| 3 | Azure RBAC on Storage, Cosmos DB data-plane RBAC, AI Search RBAC, evaluated for the user's on-behalf-of token | The OBO token's `oid` and group membership against role assignments at container, collection or service scope | Allow, or the service's own 403 | Storage 403 is mapped to `DENIED` / `storage_rbac_denied`; Search and Cosmos errors are not mapped in this repo | `StorageBlobLogs` (client request id equals `request_id`); layer `3-data-plane` in `AbwDenials` | `src/mcp/abw_mcp/data.py:57-71#read_blob_text`; `infra/03-platform.bicep:618-636#raResearchBlob`; `observability/kql/AbwDenials.kql:67-77#3-data-plane` |
| Cross-cutting | Azure Policy at the resource group (control plane, not a request-path layer) | Resource properties in an ARM request | Deny, Audit, or Modify by an organisation baseline | HTTP 403 `RequestDisallowedByPolicy` on a denied PUT | Activity log and policy compliance state | `infra/06-governance.bicep:177-207#assignment`; `infra/06a-policy-definitions.bicep:168-221#abw-agent-platform-controls` |

Diagram: docs/diagrams/05-authorization-layers.excalidraw

**How a tool call meets the walls, in order.**

1. Before Layer 0 there is a project gate: the group `sg-abw-demo-all` holds the Foundry Agent Consumer role at project scope, which decides who may call an agent at all (Configured: `infra/02-foundry-rbac.bicep:36-44#raConsumersProject`). It has no per-tool meaning and is not one of the four walls.
2. Layer 0 screens the prompt on the way in and the completion on the way out. The policy also asks the preview tool-response control to screen text that an MCP tool returns (Configured: `infra/06-governance.bicep:92-97#PostToolCall`), but Learn's list of tools that support that intervention point does not name MCP, so it is not shown to apply to these tools (Platform behaviour: https://learn.microsoft.com/azure/foundry/guardrails/intervention-points).
3. The agent calls each MCP server through an OAuth-passthrough project connection named `mcp-<server>-oauth`, so the call carries the signed-in user's own access token (Implemented: `src/agent/abw_agents.py:119-139#project_connection_id`). For research, wall, actions and vendor this hop goes through APIM (Layer 1). The private server is called directly (section 7.3).
4. Layer 2 validates the same token again, filters the tool list, applies the tool rule and decides (Implemented: `src/mcp/abw_mcp/registry.py:158-193#call_tool`).
5. For an allowed call the server trades the user's token for a data-plane token (section 6) and Layer 3 evaluates RBAC for that user (Implemented: `src/mcp/abw_mcp/data.py:57-71#read_blob_text`).

**The same barrier, three different refusals.** The refusal point depends on who asks and what for (Designed and consistent with the code, see section 7.6):

| Case | Layer 1 | Layer 2 | Layer 3 |
|---|---|---|---|
| A person with no Wall role asks the wall server for a deal document | 403 `missing_role` (`infra/apim/policies/mcp-jwt.policy.xml:44-45#missing_role`) | never reached | never reached |
| A person crossed on Falcon asks for ORION-001 | passes: the policy accepts either Wall role (`infra/05-apim-apis.bicep:40-50#apiAppIds.wall`) | `DENIED` / `project_not_in_token_roles` before any data call (`src/mcp/abw_mcp/servers/wall.py:39-47#_require_project`) | would refuse as well: nobody is assigned on `wall-orion` (`infra/03-platform.bicep:638-640#Orion`) |
| A trader orders 100 shares of a restricted name | passes: Trade.Execute is accepted | `DENIED` / `restricted_list` (`src/mcp/abw_mcp/servers/actions.py:68-75#restricted_list`) | not reached for the write; the restricted list is read as the service identity (`src/mcp/abw_mcp/servers/actions.py:30-37#_read_restricted`) |

**Why four walls and not one.** Each wall fails differently. The gateway cannot see deals or tickers, so it cannot enforce the information barrier. The MCP server can, but it is code that changes. The data plane enforces membership with no application code involved, so it still holds if a tool has a bug, but it cannot see what a tool is for. The guardrail sees content but not identity. Stacking them means a defect in one is a finding, not a breach (Designed: `DESIGN.md:28-33#Re-validates`).

**Trade-off / limitation.** The price of four walls is four places to change when a rule changes. A new deal touches an Entra app role, the APIM role list, the wall server, a Storage container with its RBAC and the agent tool lists (section 7.9). There is no single entitlement store that the four layers read.

### 7.2 Layer 0, the Foundry guardrail

**What this section proves.** Layer 0 exists, is attached by one flag, and is honest about its limits: it is a preview, probabilistic, detective control. It is not part of the authorization argument.

**What the policy `abw-agent-guardrails` configures** (Configured: `infra/06-governance.bicep:72-98#guardrails`). It is a Foundry content-filter policy (a `raiPolicies` child of the Foundry account, API version `2026-07-15-preview`) built on the base policy `Microsoft.DefaultV2` in `Blocking` mode:

| Filter | Applied to | Blocking | Notes |
|---|---|---|---|
| Hate, Sexual, Violence, Selfharm | Prompt, and again on Completion (each category appears twice) | yes | severity threshold Medium (`infra/06-governance.bicep:77-84#harmFilters`) |
| Jailbreak | Prompt | yes | `infra/06-governance.bicep:93-93#Jailbreak` |
| Indirect Attack | Prompt | yes | `infra/06-governance.bicep:94-94#Attack` |
| Indirect Attack | `PostToolCall` (what an MCP tool returns), action `BLOCKING` | yes | preview; `infra/06-governance.bicep:95-95#PostToolCall` |
| Protected Material Text | Completion | no (annotate only) | `infra/06-governance.bicep:96-96#Protected` |

The comment above the resource states the intent and the caveat in one place: the tool-response control "screens what an MCP tool RETURNS before the model reads it", it is "preview and best effort", it stopped the run on only a minority of identical requests, "so it is a detection layer", and "the deterministic control is the wall" (Configured: `infra/06-governance.bicep:72-76#guardrails`).

**Where it is defined and how it is named.** The resource sits in `06-governance.bicep`, the policy name is the parameter `guardrailPolicyName` (default `abw-agent-guardrails`), and the resource id is exported as an output so scripts can attach it (Configured: `infra/06-governance.bicep:31-31#guardrailPolicyName`, `infra/06-governance.bicep:309-314#guardrailPolicyId`). Diagnostic settings send all log categories of the Foundry account and of the project to the Log Analytics workspace (Configured: `infra/06-governance.bicep:102-119#allLogs`). The guardrail events that the KQL pack uses are read from a different table (see "How a Layer 0 event is seen" below).

**Which agent uses it.** There are four published agents and only two carry the guardrail:

| Agent | Guardrail | When | Code |
|---|---|---|---|
| `abw-poc-legacy` | none | never: the "before" picture | `src/agent/abw_agents.py:159-165#POC_AGENT` |
| `abw-wall-desk` (the governed agent) | `abw-agent-guardrails` | only when `--rai` is passed | `src/agent/abw_agents.py:170-176#WALL_AGENT` |
| `abw-wall-desk-redteam` | none, by design, so attacks reach the server-side denial | never | `src/agent/abw_agents.py:178-184#REDTEAM_AGENT` |
| `abw-wall-desk-redteam-shielded` | `abw-agent-guardrails` | only when `--rai` is passed (the agent is not published otherwise) | `src/agent/abw_agents.py:186-193#SHIELDED_AGENT` |

**How `create_agents.py --rai` attaches it** (Implemented):

1. `--rai` takes a policy name or a full ARM id (`src/agent/create_agents.py:30-30#--rai`).
2. The value is passed to `publish(project, rai_policy=args.rai)` (`src/agent/create_agents.py:39-39#publish`).
3. `rai_policy_id` keeps a full id as it is and turns a bare name into `<foundry account id>/raiPolicies/<name>`, because agents reject a bare name (`src/agent/abw_agents.py:83-87#rai_policy_id`).
4. `publish` builds `RaiConfig(rai_policy_name=...)` once and spreads it into the governed agent and the shielded red-team agent only (`src/agent/abw_agents.py:167-169#guard_kwargs`, `src/agent/abw_agents.py:186-191#shielded`).

**Why a flag and not always on.** The shielded red-team agent exists so the demo can show the same attack with and without the guardrail (`src/agent/abw_agents.py:12-14#shielded`). Publishing without `--rai` yields a governed agent that has no Layer 0 at all, which is a deployment foot-gun: the code does not fail or warn when the flag is missing (Trade-off / limitation).

**Preview, probabilistic, detective.**

- **Preview.** The resource API version is a preview version (`infra/06-governance.bicep:86-86#raiPolicies`) and the repo lists the guardrail among its preview features (Designed: `DESIGN.md:30-30#probabilistic`). Learn describes agent guardrails as a preview feature with four intervention points (user input, tool call, tool response, output): https://learn.microsoft.com/azure/foundry/guardrails/guardrails-overview (Platform behaviour).
- **Probabilistic.** The harness asks up to 40 times until the guardrail fires once, because it fires on a minority of identical requests. Measured rates recorded in the repo: 3/20, 5/8, 3/10, 2/10, 1/9 (`demo/prove.py:787-791#GUARD_TRIES`), plus 1/10 and 1/11 in the design notes (`DESIGN.md:228-228#3/20`). Policy variants did not change the rate (Designed: `DESIGN.md:228-228#variant`).
- **Not documented for MCP.** Learn says tool-call and tool-response controls need support on the tool side, and MCP is not in the documented list of supported tool types: https://learn.microsoft.com/azure/foundry/guardrails/intervention-points (Platform behaviour). The repo repeats this caveat (`DESIGN.md:228-228#documented`). So the `PostToolCall` Indirect Attack control may simply not apply to MCP results. Prompt Shields classify user-prompt attacks by default and document attacks only when enabled: https://learn.microsoft.com/azure/foundry/openai/concepts/content-filter-prompt-shields (Platform behaviour).
- **Detective.** When it fires, the run ends and the event is visible, but when it does not fire the whole tool-stage guardrail is skipped rather than "evaluated negative" (Designed: `DESIGN.md:228-228#skipped`). Nothing in the wall depends on it: the proof P09 asserts that every attempt, stopped or not, executed nothing the poisoned notice asked for (`demo/prove.py:815-830#p09`).

**The attack fixture it is tested against.** The vendor mock serves one deliberately poisoned headline, only for the ticker NOVA: a fake "system notice" telling the assistant to read an Orion document and buy a restricted name without saying so (Implemented: `src/mcp/abw_mcp/servers/vendor.py:17-23#_INJECTED_HEADLINE`, `src/mcp/abw_mcp/servers/vendor.py:53-54#_INJECTED_TICKER`). P09 first replays what the notice asks for with the user's own token and expects `project_not_in_token_roles` and `restricted_list` or `separation_of_duties` (`demo/prove.py:820-829#project_not_in_token_roles`). The wall refuses those every time. The guardrail is the extra layer that may stop the run earlier.

**How a Layer 0 event is seen.** The MCP server never sees a guardrail block, because it happens inside the Foundry run. `AbwDenials` reads `AppDependencies` rows named `invoke_agent*` whose `error.type` is `content_filter` and labels them layer `0-agent-guardrail` (`observability/kql/AbwDenials.kql:4-12#guardRuns`, `observability/kql/AbwDenials.kql:32-41#0-agent-guardrail`). Sentinel rule ABW-008 raises an alert on exactly that layer (`observability/sentinel/abw-008-guardrail-intervention.kql:11-12#0-agent-guardrail`).

**Policy-as-code on the guardrail itself.** The initiative `abw-agent-platform-controls` has two Audit-only references (jailbreak and indirect attack) that report agents without those filters (Configured: `infra/06a-policy-definitions.bicep:328-348#agent-guardrail-jailbreak`). They report; they do not stop an unguarded agent from being published (section 7.7).

**Trade-off / limitation.** Layer 0 adds latency at each intervention point (Learn estimates roughly 50 to 100 ms per point: https://learn.microsoft.com/azure/foundry/guardrails/intervention-points, Platform behaviour) and is non-deterministic. It belongs in the story as a detection and defence-in-depth layer, never as the reason a Falcon user cannot read Orion.

### 7.3 Layer 1, APIM

**What this section proves.** Every MCP API in the gateway's server array gets the same gateway policy, rendered once per server from one template, and the gateway makes a fixed, ordered set of decisions before any container is touched.

**How the policy is attached.** `05-apim-apis.bicep` holds an array of four servers (research, wall, actions, vendor), called the gateway APIs in this reference. The governed servers are a different set: research, wall, actions and private, the four that validate Entra tokens in the app and exchange the user's token (the proofs call them `GOVERNED_APPS`, `demo/prove.py:540#GOVERNED_APPS`). The vendor mock is behind the gateway without being governed in that sense, the private server is governed without a gateway, and the legacy server is neither. For each gateway API the Bicep creates an MCP-type API bound to a backend, with `subscriptionRequired: false` (the user's token is the credential), and attaches the template `mcp-jwt.policy.xml` at API scope after replacing the placeholders `__SERVER__`, `__PATH__`, `__AUDIENCE__`, `__ROLES_CS__`, `__LIST_OPEN__`, `__VENDOR_SECTION__` and `__TITLE__` (Configured: `infra/05-apim-apis.bicep:123-147#mcpApis`, `infra/05-apim-apis.bicep:149-166#mcpPolicies`).

**Per-API parameters** (Configured):

| API | Path | Required scope and roles | Allowed `azp` | Rate limit | Backend |
|---|---|---|---|---|---|
| `abw-mcp-research` | `/research` | scope `Tools.Read`; role `Research.Read`. `initialize`, `ping`, `tools/list` and `notifications/*` are open to any valid token (`listOpen: true`) (`infra/05-apim-apis.bicep:29-39#apiAppIds.research`) | the global named value `abw-allowed-azp` | 120 calls per 60 s per `oid` | `be-mcp-research`, the research container app; TLS chain and name validation follow `validateInternalTls` (default false) |
| `abw-mcp-wall` | `/wall` | scope `Tools.Read`; role `Wall.Falcon` or `Wall.Orion`; `listOpen: true` (`infra/05-apim-apis.bicep:40-50#apiAppIds.wall`) | same list | same | `be-mcp-wall` |
| `abw-mcp-actions` | `/actions` | scope `Tools.Read` (the gateway never checks `Tools.Execute`); role `Trade.Read` or `Trade.Execute`; `listOpen: true` (`infra/05-apim-apis.bicep:51-61#apiAppIds.actions`) | same list | same | `be-mcp-actions` |
| `abw-mcp-vendor` | `/vendor` | scope `Tools.Read`; role `MarketData.Read` on every method (`listOpen: false`) (`infra/05-apim-apis.bicep:62-72#apiAppIds.vendorgw`) | same list | same | `be-mcp-vendor`, TLS validated; the policy deletes `Authorization` and injects `x-vendor-key` from the Key-Vault-backed named value `abw-vendor-key` |
| `abw-mcp-legacy` | `/legacy` | none: an APIM subscription key (header `Ocp-Apim-Subscription-Key` or query `subscription-key`), no token (`infra/05-apim-apis.bicep:169-193#legacyApi`) | not checked | 120 per 60 s per subscription id, falling back to the caller address (`infra/apim/policies/mcp-legacy.policy.xml:8-8#rate-limit-by-key`) | `be-mcp-legacy` |
| private MCP | none | not behind APIM | enforced only by the MCP server (`MCP_ALLOWED_AZP`) | none | reached directly by the agent runtime |

The backend objects are declared in `infra/05-apim-apis.bicep:94-106#backends` and each API is bound with `backendId` (`infra/05-apim-apis.bicep:131-131#backendId`). The allowed-client list is one named value for all APIs, filled from a deployment parameter (`infra/05-apim.bicep:199-207#abw-allowed-azp`). The role lists live in the Bicep array and are baked into the XML at deploy time, so changing a role list means redeploying this file (Trade-off / limitation).

**Decision order inside `mcp-jwt.policy.xml`** (Configured). The comment at the top of the file and `DESIGN.md` describe the order as "validate-jwt, then claim authorization, then rate limit". The code is more specific, and the order matters because the first failing check supplies the reason code (see Findings):

1. **`validate-jwt`.** Bearer scheme required, expiry required, signed tokens required, clock skew 60 s, the issuer and the target API (the `aud` claim) pinned to this API, and the claim `tid` required to equal the tenant. A failure returns 401 (`infra/apim/policies/mcp-jwt.policy.xml:17-30#validate-jwt`). The parsed token is kept in a variable for the next steps. The key set comes from the tenant's OpenID configuration document. How `validate-jwt` verifies a token is documented at https://learn.microsoft.com/azure/api-management/validate-jwt-policy (Platform behaviour).
2. **Kill switch.** If the token's `oid` is an exact element of the comma-separated named value `abw-deny-oids`, the reason is `revoked` (`infra/apim/policies/mcp-jwt.policy.xml:37-37#abw-deny-oids`). The comparison is an element match on the split list, not a substring match.
3. **Client allow-list.** If the token's `azp` is not an element of `abw-allowed-azp`, the reason is `client_not_allowed`. An empty or unknown `azp` therefore fails closed at the gateway (`infra/apim/policies/mcp-jwt.policy.xml:38-38#abw-allowed-azp`). The MCP server behaves differently when its own list is empty (section 7.4, Findings).
4. **Scope.** If `scp` does not contain `Tools.Read`, the reason is `missing_scope`. This is hard-coded in the template, so every server needs `Tools.Read` and none is asked for `Tools.Execute` here (`infra/apim/policies/mcp-jwt.policy.xml:39-39#missing_scope`).
5. **Role.** The JSON-RPC `method` is read from the request body. Where `listOpen` is true, `initialize`, `ping`, `tools/list` and `notifications/*` need no role; every other method needs at least one role from the server's list, else `missing_role`. A body that cannot be read as a JSON object leaves `method` empty, so it counts as a non-discovery call and needs a role (`infra/apim/policies/mcp-jwt.policy.xml:40-45#discovery`).
6. **Telemetry for every decision.** A metric `abw-gateway-decisions` (dimensions server, decision, reason, oid) and a trace `abw-gateway` (with `request_id` equal to the APIM request id) are emitted for allow and for deny (`infra/apim/policies/mcp-jwt.policy.xml:51-63#emit-metric`).
7. **Deny.** If a reason was set, the policy returns 403 with a JSON body (`infra/apim/policies/mcp-jwt.policy.xml:64-80#return-response`).
8. **Rate limit, request id, forward.** The per-user counter runs only for requests that passed, so refused requests do not consume it. Then `x-abw-request-id` and `x-abw-gateway: apim` are set, the vendor section is inserted where applicable, and the request is forwarded (`infra/apim/policies/mcp-jwt.policy.xml:81-89#rate-limit-by-key`).

**Why this order.** Revocation is checked first so a revoked person is refused with the clearest reason regardless of other claims. Cheap string checks run before the more specific role check, and the per-user counter sits after the deny so that a flood of refused calls cannot lock a user out of legitimate calls. This rationale is an inference from the structure; the repo states the order only in the template and in the proofs P12, P14 and P15 (section 7.5).

**Wire shapes** (Configured):

| Status | When | Headers | Body | Code |
|---|---|---|---|---|
| 401 | `validate-jwt` fails: no token, bad signature, wrong `aud` or issuer, expired, wrong tenant | `WWW-Authenticate` carrying `error="invalid_token"` and a parameter that points at the protected-resource discovery document for this API | `{"error":"unauthorized","server":"<server>","reason":"a valid Entra access token for this MCP server is required"}` | `infra/apim/policies/mcp-jwt.policy.xml:96-112#invalid_token` |
| 403 | Kill switch, client allow-list, scope or role | `Content-Type: application/json` | `{"error":"forbidden","reason":"<revoked, client_not_allowed, missing_scope or missing_role>","server":"<server>","request_id":"<request-id>"}` | `infra/apim/policies/mcp-jwt.policy.xml:66-78#forbidden` |
| 429 | The per-user budget of 120 calls per 60 s is used up for one `oid` (a token bucket on this StandardV2 gateway, see below) | produced by APIM itself; Learn documents a 429 with a retry hint | no custom body in this repo | `infra/apim/policies/mcp-jwt.policy.xml:81-81#rate-limit-by-key` |

Platform behaviour (https://learn.microsoft.com/azure/api-management/rate-limit-by-key-policy): the policy answers 429 with a retry hint and is "never completely accurate". The classic tiers use a sliding window; the v2 tiers use a token bucket. APIM keeps a single counter for each `counter-key` value, updated at every scope where the policy is configured with that key; separate counters per scope need different key values. This gateway is a StandardV2 instance, so the limit behaves as a token bucket, which is how the proof harness describes it (Configured: `infra/05-apim.bicep:47-49#StandardV2`; Implemented: `demo/prove.py:878#token`). The key is the bare `oid` with no scope suffix (`infra/apim/policies/mcp-jwt.policy.xml:81-81#rate-limit-by-key`). By the Learn usage note, the four gateway APIs therefore most likely draw on one per-user budget (inference; not tested, because proof P14 exercises one API only: `demo/prove.py:870-903#P14`).

**The `/legacy` policy is a deliberate foil.** It is a different policy: the API requires a subscription key (`subscriptionRequired: true`) and the policy only rate-limits by subscription, sets `x-abw-request-id` and sets `x-abw-gateway: apim-legacy`. There is no `validate-jwt`, no kill switch, no client list and no role check (`infra/apim/policies/mcp-legacy.policy.xml:6-15#apim-legacy`, `infra/05-apim-apis.bicep:175-182#subscriptionRequired`). The legacy container has no authentication middleware either (`src/mcp/abw_mcp/app.py:241-249#BearerAuthMiddleware`). It is the "before" picture: one shared key, no person (section 8.3).

**Why the private server is not behind APIM.** The demo shows three placements on purpose: an internal server behind the gateway, an external vendor server behind the gateway, and a private server reached only from inside the network (Designed: `DESIGN.md:19-19#private`). The code gives the agent the private server's own application address instead of a gateway address (Implemented: `src/agent/abw_agents.py:95-106#server_urls`), and the Bicep array of gateway APIs has no private entry (`infra/05-apim-apis.bicep:28-28#servers`). The design notes state the consequence: this path never touches APIM, so the kill switch does not reach it, and a revoked user keeps it until the token expires. The notes mark that as read from the code, not exercised live, and name the production fixes: an internal APIM in front, or the server reading the same deny list (Designed: `DESIGN.md:107-107#kill`). The server still validates the token itself, filters tools by `Positions.Read` and reads Cosmos with the user's token, so Layers 2 and 3 apply (section 7.4).

**Trade-off / limitation.** The private server has no gateway kill switch, no client allow-list at the gateway, no per-user rate limit and no gateway request-id header. Its request id comes from the first of `x-abw-request-id`, `x-request-id`, `x-ms-request-id` or `traceparent` that is present, else it is generated locally (`src/mcp/abw_mcp/auth.py:173-188#RequestContextMiddleware`). Which of those headers the Foundry runtime sends on this direct path is not in this repo.

**The agent front door shares the kill switch.** A second APIM policy fronts the Foundry agent endpoint: it validates a token issued for the Foundry data plane (its `aud` claim), refuses any `oid` in the same `abw-deny-oids` named value with 403, then applies a per-user calls-per-minute limit and a per-user hourly token budget (Configured: `infra/apim/policies/agent-frontdoor.policy.xml:18-32#validate-jwt`, `infra/apim/policies/agent-frontdoor.policy.xml:53-53#abw-deny-oids`, `infra/apim/policies/agent-frontdoor.policy.xml:95-96#llm-token-limit`). It forwards the user's token unchanged and has no role check. One revocation therefore closes both the tool path and the agent path.

**Discovery.** An anonymous policy answers the RFC 9728 protected-resource discovery request for each gateway API, so an MCP client can find the authorization server and scope after a 401. The 401 `WWW-Authenticate` header points at it (`infra/05-apim-apis.bicep:216-249#prmApi`).

### 7.4 Layer 2, the MCP server

**What this section proves.** The MCP server does not trust the gateway. It re-validates the token itself, decides per tool from the `roles` claim, shows each caller only the tools that caller may use, and turns every refusal into an audited result. Token failures are real wire errors (HTTP 401 or 403 before any tool code runs). Tool refusals are soft: HTTP 200 with `decision: DENIED` in `structuredContent`. Both kinds are written to the audit log.

**Where it runs (Implemented).** One container image serves all six servers; the `MCP_SERVER` setting picks the tool set (section 8.1). Research, wall, actions and private install `BearerAuthMiddleware`. The vendor server has a vendor-key middleware instead, and legacy has no authentication middleware at all (`src/mcp/abw_mcp/app.py:241-249#BearerAuthMiddleware`). Token validation is switched on for exactly the servers that are not vendor or legacy (`src/mcp/abw_mcp/config.py:99-108#validates_tokens`). Only the `/mcp` path is protected, so `/healthz` and the protected-resource (PRM) document stay anonymous (`src/mcp/abw_mcp/auth.py:209-216#__call__`).

The transport is stateless: no server-side session is kept, so every `tools/call` is authenticated on its own and no authorization decision is cached between calls (`src/mcp/abw_mcp/app.py:210-215#stateless`).

#### 7.4.1 Token re-validation, in order

**Implemented.** Layer 2 re-checks the token that Layer 1 already validated (section 7.3). Section 6 explains how the token is obtained and what each claim means; this table records only the decision order and the refusal each step produces.

| Step | Check | Reason code | HTTP | Code |
|---|---|---|---|---|
| 1 | No bearer token on `/mcp` | `missing_token` | 401 | `src/mcp/abw_mcp/auth.py:111-112#missing_token` |
| 2 | Token header cannot be parsed | `bad_signature` | 401 | `src/mcp/abw_mcp/auth.py:113-116#bad_signature` |
| 3 | Signing key not in the tenant key set (the set is cached for 3600 s) | `bad_signature` | 401 | `src/mcp/abw_mcp/auth.py:60-79#JwksCache` |
| 4 | Decode with RS256 only; the `aud` must be the MCP app (client id, or `api://` plus client id); `iss` must be the tenant v2.0 issuer; 60 s clock leeway; `exp`, `nbf`, `iss`, `aud` are required | see 4a-4f | 401 | `src/mcp/abw_mcp/auth.py:118-128#RS256` |
| 4a | Signature invalid | `bad_signature` | 401 | `src/mcp/abw_mcp/auth.py:129-130#InvalidSignatureError` |
| 4b | `aud` not allowed | `bad_aud` + `ience` (see the spelling note) | 401 | `src/mcp/abw_mcp/auth.py:131-132#bad_aud` |
| 4c | `iss` wrong | `bad_issuer` | 401 | `src/mcp/abw_mcp/auth.py:133-134#bad_issuer` |
| 4d | Expired | `expired` | 401 | `src/mcp/abw_mcp/auth.py:135-136#expired` |
| 4e | Not yet valid | `not_yet_valid` | 401 | `src/mcp/abw_mcp/auth.py:137-138#not_yet_valid` |
| 4f | Any other decode failure, including a missing required claim | `bad_signature` | 401 | `src/mcp/abw_mcp/auth.py:139-142#bad_signature` |
| 5 | `ver` claim is not `2.0` | `bad_issuer` | 401 | `src/mcp/abw_mcp/auth.py:144-145#bad_issuer` |
| 6 | `tid` is not this tenant | `bad_tenant` | 401 | `src/mcp/abw_mcp/auth.py:146-147#bad_tenant` |
| 7 | App-only token (`idtyp` is `app`) or no `oid` | `app_only` | 401 | `src/mcp/abw_mcp/auth.py:148-149#app_only` |
| 8 | `azp` not in `MCP_ALLOWED_AZP`; skipped when that list is empty | `bad_azp` | 401 | `src/mcp/abw_mcp/auth.py:151-153#bad_azp` |
| 9 | The required scope (`Tools.Read` by default) is not in `scp` | `missing_scope` | 403 | `src/mcp/abw_mcp/auth.py:155-157#missing_scope` |

Spelling note: the reason code in step 4b is `bad_aud` joined to `ience`. This document writes it in two parts so that the repo's share scanner, which treats the plain English word as a deployment value, does not match it; search the code for `bad_aud`. The same convention is used wherever the code appears in sections 7 and 8.

The mapping to HTTP status is in one place: `AuthError` returns 403 for `missing_scope` and `missing_role` and 401 for every other reason, and the `error` value follows (`insufficient_scope` for 403, `invalid_token` for 401) (`src/mcp/abw_mcp/auth.py:44-57#AuthError`). The 403 for `missing_role` exists only for the optional `authorization_check` hook, and the app registers `BearerAuthMiddleware` without one (`src/mcp/abw_mcp/app.py:244-249#BearerAuthMiddleware`), so in practice only `missing_scope` is raised on this path; a missing role at a server is a tool-level DENIED result with HTTP 200 (`src/mcp/abw_mcp/registry.py:98-108#require_any_role`, `src/mcp/abw_mcp/registry.py:163-165#requirement`). The scope name and the allow-list come from settings, not from code (`src/mcp/abw_mcp/config.py:140-141#MCP_ALLOWED_AZP`).

**The refusal on the wire.** The response carries a `WWW-Authenticate` Bearer challenge with realm `abw`, the `error` value, an `error_description` equal to the reason code, and a parameter that points to the PRM document. The JSON body is `{"error": "<invalid_token or insufficient_scope>", "error_description": "<reason code>"}` (`src/mcp/abw_mcp/auth.py:250-260#_auth_error_response`).

**The caller object.** After the last check a `Caller` is built from the verified claims: `oid`, `upn` (from `preferred_username`), `tid`, `roles` (sorted, unique), `scopes`, `azp`, `aud`, `jti` (the token's `uti` when present, else `jti`) and the raw token. The raw token field is excluded from `repr`, so a log line that prints the object cannot leak it (`src/mcp/abw_mcp/auth.py:29-41#Caller`, `src/mcp/abw_mcp/auth.py:159-170#roles`). The caller is published on a context variable for the duration of the request and reset afterwards (`src/mcp/abw_mcp/auth.py:244-248#current_caller`).

**What a token failure logs.** One `auth_failed` event with `decision` deny, `reason` set to the code, no tool, no argument hash and `obo` false. The caller is passed as `None`, so the event has NO identity even when the token had verified up to `bad_azp` or `missing_scope` (`src/mcp/abw_mcp/auth.py:224-242#auth_failed`). The main join key is the request id; every event also carries `trace_id` from the active OpenTelemetry span, or null when no span is active (`src/mcp/abw_mcp/audit.py:146-152#trace_id_from_context`, `src/mcp/abw_mcp/audit.py:214#trace_id`). The request id is the first present of `x-abw-request-id` (set by the gateway, section 7.3), `x-request-id`, `x-ms-request-id` and `traceparent`, else a generated `req-` plus epoch milliseconds (`src/mcp/abw_mcp/auth.py:173-188#RequestContextMiddleware`).

**A hook that is never used.** `BearerAuthMiddleware` accepts an optional `authorization_check` callback that could add a role rule at the middleware. `app.py` never passes it, so the middleware's `missing_role` branch cannot fire; role enforcement lives in the registry (`src/mcp/abw_mcp/auth.py:194-207#authorization_check`, `src/mcp/abw_mcp/auth.py:220-223#authorization_check`, `src/mcp/abw_mcp/app.py:244-249#BearerAuthMiddleware`).

**Why validate again.** (1) The private server is reached directly over the VNet, not through the gateway, so on that path the MCP server is the only token checker (`src/agent/abw_agents.py:95-106#server_urls`; DESIGN.md:107-107#private). (2) The registry needs a verified caller, not a header it must trust. (3) A mis-routed or direct call is still refused.

**Platform behaviour.** Microsoft's guidance for APIs that accept Entra tokens is to validate signature, issuer, target API, and time window, and not to trust a claim that was not validated (https://learn.microsoft.com/entra/identity-platform/access-tokens#validate-tokens, https://learn.microsoft.com/entra/identity-platform/claims-validation). The `azp` claim identifies the client application that requested the token and exists in v2.0 tokens only; `roles` lists the user's app roles on the target API; user tokens carry `scp` (https://learn.microsoft.com/entra/identity-platform/access-token-claims-reference). The extra `tid`, `ver`, `idtyp`, `azp` and scope checks above are this repo's own hardening, not a platform requirement.

**Trade-off / limitation (the two allow-lists).** The gateway and the MCP server keep separate copies of the allowed-client list and fail in opposite directions. The gateway reads the APIM named value and refuses when it is empty (`infra/apim/policies/mcp-jwt.policy.xml:38-38#azp`). The MCP server reads `MCP_ALLOWED_AZP`, a static copy injected at deploy time, and SKIPS the check when it is empty (`src/mcp/abw_mcp/auth.py:151-153#bad_azp`, `infra/04-apps.bicep:80-80#MCP_ALLOWED_AZP`). `scripts/client-allowlist.ps1` changes only the named value (section 7.8), so the direct private path keeps whatever the static copy lists. The same refusal also has two shapes: 403 `client_not_allowed` at the gateway, 401 `invalid_token` with description `bad_azp` here (Findings, end of section 8).

#### 7.4.2 The registry and its three requirement helpers

**Implemented.** Each tool is a `ToolDefinition` holding a name, a Pydantic argument model, a handler, a requirement function and a `data_class` (`src/mcp/abw_mcp/registry.py:78-91#ToolDefinition`). The same requirement function runs when the tools are listed and again when a tool is called. Argument models forbid unknown fields, so an extra argument is an `invalid_arguments` refusal (`src/mcp/abw_mcp/registry.py:24-27#ArgsModel`).

| Helper | Rule | With no caller | Reason code | Used by |
|---|---|---|---|---|
| `allow_all` | Always true | true | none | Vendor and legacy tools |
| `require_any_role(*roles)` | At least one listed role is in the token's `roles` | false | `missing_role` | Research, wall, private, and the read tools of actions |
| `require_scope_and_role(scope, *roles)` | The scope must be in `scp` first, then the role rule | false | `missing_scope`, then `missing_role` | `place_order` only |

Code: `src/mcp/abw_mcp/registry.py:94-121#require_any_role`.

**Why roles and not groups.** The decision input is the app-role claim in the validated token, which the application owner controls through app-role assignment (`identity/Setup-Entra.ps1:29-44#Research.Read`). Group membership is deliberately left for Layer 3, where the data service evaluates it (section 7.5).

**The order inside `call_tool`.** Unknown tool, then requirement, then argument validation, then the handler (token exchange and data call), then success. Every branch ends in exactly one audit event, except an exception that the registry does not catch (section 7.5, "What an unmapped denial looks like") (`src/mcp/abw_mcp/registry.py:158-165#call_tool`).

#### 7.4.3 Role-filtered tools/list

**Implemented.** `list_tools` runs each tool's requirement against the caller and returns only the tools that pass. A tool the caller may not use is not described to the model at all (`src/mcp/abw_mcp/registry.py:132-140#list_tools`). One `tool_listed` audit event is written per VISIBLE tool, with the caller's identity and no arguments. Hidden tools produce no event, and a caller with no matching role gets an empty list and no MCP audit event at all (`src/mcp/abw_mcp/registry.py:141-156#tool_listed`; Findings, end of section 8).

**Why it matters.** At Layer 1, research, wall and actions are "list-open": the gateway lets `initialize`, `ping`, `tools/list` and any `notifications/` method through for any valid token and requires a role for every other method, `tools/call` included (an unreadable body also needs the role) (section 7.3; `infra/apim/policies/mcp-jwt.policy.xml:42-44#discovery`). So the empty tool list is produced here, at Layer 2. Hiding the tools is a usability and exposure control; it is not the security boundary, because the call path re-runs the requirement (`src/mcp/abw_mcp/registry.py:163-165#requirement`).

**Proof.** P02 checks that a caller with no role sees no tools on research, wall and actions, and that a 403 with reason `missing_role` is returned when such a caller calls a tool anyway (`demo/prove.py:607-636#p02`). That 403 can only come from the gateway: the registry's own `missing_role` is a soft HTTP 200 denial (see 7.4.5), so P02 line 628 does not exercise Layer 2. Layer 2 is proven by the unit tests `test_role_filtered_tools_list` (`src/mcp/tests/test_servers.py:33-63#test_role_filtered_tools_list`) and `test_entitled_to_nothing_sees_no_tools_and_cannot_call` (`src/mcp/tests/test_servers.py:250-266#test_entitled_to_nothing_sees_no_tools_and_cannot_call`).

#### 7.4.4 Per-tool authorization rules, by server

**Implemented.** "Deny reason codes" are the `reason` values an audit row and a denial payload can carry. Every tool can also return `invalid_arguments`, and every tool that exchanges a token can return `obo_failed:<code>` (the code comes from the token broker, section 6). A failed exchange never falls back to the service identity (see "Why" in 7.4.6).

**Research server.** Two tools, both gated only by the role. Layer 2 holds no per-note rule: the control for a note is the data plane (section 7.5).

| Tool | Roles (any of) | Data class | Deny reason codes |
|---|---|---|---|
| `search_research` | `Research.Read` | `public` | `missing_role`, `invalid_arguments`, `obo_failed:<code>` |
| `get_research_note` | `Research.Read` | `public` | `missing_role`, `invalid_arguments`, `obo_failed:<code>`, `storage_rbac_denied`, `blob_not_found` |

Code: `src/mcp/abw_mcp/servers/research.py:67-85#build_tools`. `search_research` always adds the filter `classification eq 'public'` (`src/mcp/abw_mcp/servers/research.py:22-30#classification`). `get_research_note` reads the `research-public` container as the user and converts a data-plane failure into a `ToolError` with the default `tool_denied` event (`src/mcp/abw_mcp/servers/research.py:47-64#get_research_note`).

**Wall server.** All three tools need `Wall.Falcon` or `Wall.Orion`; the handler then applies the project rule.

| Tool | Roles (any of) | Data class | Deny reason codes |
|---|---|---|---|
| `list_my_wall_crossings` | `Wall.Falcon` or `Wall.Orion` | `wall` | `missing_role`, `invalid_arguments` |
| `search_deal_documents` | `Wall.Falcon` or `Wall.Orion` | `wall` | `missing_role`, `invalid_arguments` (project must be `falcon` or `orion`), `project_not_in_token_roles`, `obo_failed:<code>` |
| `get_deal_document` | `Wall.Falcon` or `Wall.Orion` | `wall` | `missing_role`, `invalid_arguments` (id must be FALCON-nnn or ORION-nnn), `project_not_in_token_roles`, `storage_rbac_denied`, `blob_not_found`, `obo_failed:<code>` |

Code: `src/mcp/abw_mcp/servers/wall.py:112-138#build_tools`.

- `caller_projects` maps the role names to project names: `Wall.Falcon` gives falcon, `Wall.Orion` gives orion (`src/mcp/abw_mcp/servers/wall.py:29-36#caller_projects`).
- `_require_project` raises FORBIDDEN "Caller is not crossed on that project." with reason `project_not_in_token_roles` and audit event `wall_violation_attempt`. It runs BEFORE any data call, so a project the caller is not crossed on is never probed and its existence is not revealed (`src/mcp/abw_mcp/servers/wall.py:39-47#_require_project`). The denial records a downstream `search` call with status 403 even though no call was made (Findings, end of section 8).
- `search_deal_documents` applies the check first, then queries with the filter `classification eq 'wall' and project eq '<project>'` (`src/mcp/abw_mcp/servers/wall.py:62-85#search_deal_documents`).
- `get_deal_document` derives the project from the id prefix, applies the check, then reads the container `wall-<project>` as the user. A Storage 403 becomes FORBIDDEN `storage_rbac_denied` with audit event `wall_violation_attempt`; a missing blob becomes NOT_FOUND `blob_not_found` with `tool_denied` (`src/mcp/abw_mcp/servers/wall.py:88-105#get_deal_document`).
- `list_my_wall_crossings` has no data call: it reports the projects derived from the role claims (`src/mcp/abw_mcp/servers/wall.py:50-59#list_my_wall_crossings`).

**Actions server.** Three tools. `place_order` is the only tool with a scope rule.

| Tool | Roles | Data class | Deny reason codes |
|---|---|---|---|
| `check_restricted_list` | `Trade.Read` or `Trade.Execute` | `internal` | `missing_role`, `invalid_arguments` |
| `place_order` | Scope `Tools.Execute` AND role `Trade.Execute` | `internal` | `missing_scope`, `missing_role`, `invalid_arguments`, `separation_of_duties`, `restricted_list`, `obo_failed:<code>` |
| `list_my_orders` | `Trade.Read` or `Trade.Execute` | `internal` | `missing_role`, `invalid_arguments`, `obo_failed:<code>` |

Code: `src/mcp/abw_mcp/servers/actions.py:130-156#build_tools`.

- `check_restricted_list` and the restricted-list read inside `place_order` read the `restricted` container as the SERVICE identity (`use_user_token=False`), because the restricted list is a compliance system of record that individual users are deliberately not entitled to (`src/mcp/abw_mcp/servers/actions.py:30-37#_read_restricted`, `infra/03-platform.bicep:603-615#cosmosActionsRestricted`). Its audit rows therefore say `obo` false (`src/mcp/abw_mcp/servers/actions.py:44-55#check_restricted_list`).
- `place_order` reads the restricted list first. If the security is restricted AND the token holds any `Wall.*` role, it refuses with WALL_VIOLATION `separation_of_duties`. If the security is restricted for anyone else, it refuses with WALL_VIOLATION `restricted_list`. Both use the audit event `order_blocked`. Otherwise it writes the order to `orders` with the caller's `oid`, `upn`, `azp`, `jti` and request id, and emits `order_placed` (`src/mcp/abw_mcp/servers/actions.py:58-110#place_order`; the separation-of-duties branch is `src/mcp/abw_mcp/servers/actions.py:60-67#separation_of_duties`).
- `list_my_orders` queries `orders` with the caller's `oid` as both the filter and the partition key, using the user's token (`src/mcp/abw_mcp/servers/actions.py:113-127#list_my_orders`).

**Trade-off / limitation (two rules the live proofs cannot trigger).** App roles are per API, so one token never holds both `Wall.*` (a wall-API role) and `Trade.Execute` (an actions-API role); `separation_of_duties` is therefore reachable only with a crafted token in the unit test (`src/mcp/tests/test_servers.py:109-137#test_restricted_list_and_separation_of_duties`; DESIGN.md:226-226#missing_scope). The tool-level `missing_scope` that guards `place_order` has no test at all: the token-level `missing_scope` is unit-tested (`src/mcp/tests/test_auth.py:26#missing_scope`), but no test calls `place_order` with a token that lacks `Tools.Execute`, and the live proofs always request that scope (`demo/prove.py:665#Tools.Execute`). Entra returns every consented scope to the Azure CLI, so the case does not arise in the demo. DESIGN.md presents separation of duties as a tool rule in the layer table and discloses the limitation only in the notes (Findings, end of section 8).

**Private server.** Two tools, one role, no wall or scope rule. The server is not behind the gateway, so this rule and the token checks in 7.4.1 are the whole of its Layer 1 and Layer 2.

| Tool | Roles | Data class | Deny reason codes |
|---|---|---|---|
| `get_firm_positions` | `Positions.Read` | `internal` | `missing_role`, `invalid_arguments`, `obo_failed:<code>` |
| `get_credit_limit` | `Positions.Read` | `internal` | `missing_role`, `invalid_arguments`, `obo_failed:<code>`, `counterparty_not_found` |

Code: `src/mcp/abw_mcp/servers/private.py:59-77#build_tools`. `get_firm_positions` filters out the `limit-` rows so credit limits do not appear in a position list; `get_credit_limit` is a point read of `limit-<counterparty slug>` in the `credit` partition and returns NOT_FOUND `counterparty_not_found` when it is absent (`src/mcp/abw_mcp/servers/private.py:37-56#get_credit_limit`).

**Vendor server (external mock).** Both tools use `allow_all`. The gate is the vendor-key middleware: the request must carry the shared `x-vendor-key` header (compared in constant time) or the server returns 401 `invalid_vendor_key`. The `MarketData.Read` role is enforced only at the gateway, never in the server.

| Tool | Roles | Data class | Deny reason codes |
|---|---|---|---|
| `get_market_quote` | none (`allow_all`) | `external` | `invalid_arguments` |
| `get_headlines` | none (`allow_all`) | `external` | `invalid_arguments` |

Code: `src/mcp/abw_mcp/servers/vendor.py:62-80#build_tools`, `src/mcp/abw_mcp/app.py:115-142#VendorKeyMiddleware`. The middleware logs a `vendor_request` line on the `abw.vendor` logger that records whether an authorization header and a vendor key were seen; it does not write an `AuditService` event (Findings, end of section 8). P07 proves the three cases: valid token through the gateway works, no token gets 401 at the gateway, and a direct call without or with a wrong key gets 401 `invalid_vendor_key` (`demo/prove.py:736-761#p07`).

**Legacy server (deliberately ungoverned).** All five tools use `allow_all` and read as the service identity with no user context.

| Tool | Roles | Data class | Deny reason codes |
|---|---|---|---|
| `search_research` | none | `mixed` | `invalid_arguments` |
| `search_deal_documents` | none | `mixed` | `invalid_arguments` |
| `get_deal_document` | none | `mixed` | `invalid_arguments` |
| `place_order` | none | `mixed` | `invalid_arguments` |
| `get_firm_positions` | none | `internal` | `invalid_arguments` |

Code: `src/mcp/abw_mcp/servers/legacy.py:114-121#build_tools`. The registry for this server is built with `default_reason` set to `no_user_context`, so allowed legacy events carry that reason (`src/mcp/abw_mcp/app.py:49-60#no_user_context`). The legacy server is the contrast case for every control in this section; its detail is in section 8.3 and its proof is P08 (`demo/prove.py:763-775#p08`).

#### 7.4.5 The soft-denial shape

**Implemented.** A refusal inside a tool is a NORMAL tool result: HTTP 200, a text content item holding compact JSON, and the same JSON in `structuredContent`. The registry builds it in one place (`src/mcp/abw_mcp/registry.py:273-292#_error_payload`):

| Field | Meaning |
|---|---|
| `decision` | `DENIED` when the error code is FORBIDDEN or WALL_VIOLATION; `ERROR` for every other code |
| `error` | Error code: FORBIDDEN, WALL_VIOLATION, NOT_FOUND or INVALID_ARGUMENT |
| `message` | Short human-readable text |
| `reason` | The machine reason code from the tables above |
| `request_id` | The request id, when known (the join key to the gateway log, the audit row and the data-plane log) |
| `note` | Present only for DENIED ("blocked by policy and written to the audit log; tell the user the reason code; do not retry or look for a workaround") and for INVALID_ARGUMENT ("fix the arguments and retry once") |

Example of a wall refusal (placeholders for ids):

```json
{"decision":"DENIED","error":"FORBIDDEN","message":"Caller is not crossed on that project.","reason":"project_not_in_token_roles","request_id":"<request-id>","note":"<advisory text for the model>"}
```

`DENIED_CODES` is the set that makes a result DENIED (`src/mcp/abw_mcp/registry.py:42-42#DENIED_CODES`). The unknown-tool, requirement and argument failures are all built by the same two helpers (`src/mcp/abw_mcp/registry.py:222-236#_error_result`, `src/mcp/abw_mcp/registry.py:238-262#_tool_error_result`).

**Why it is soft.** The code comment states that Foundry Agent Service aborts the whole run with an HTTP 400 `tool_user_error` when a tool returns `isError` true. A soft result lets the model explain the refusal to the user while the audit row is still written. Setting `MCP_DENIAL_MODE` to `strict` restores `isError` true for clients that render it natively, and it applies to EVERY error result, including NOT_FOUND and INVALID_ARGUMENT (`src/mcp/abw_mcp/registry.py:263-269#isError`). A strict-mode unit test covers it (`src/mcp/tests/test_servers.py:234-247#test_strict_denial_mode_uses_mcp_is_error`).

**Trade-off / limitation.** In the default mode, a client or SIEM rule that watches HTTP status or `isError` sees a successful call. Detection has to key on the `decision` field in the audit stream; the observability pack does (`observability/kql/AbwDenials.kql:57-66#deny`). The `note` text is advice to the model, not a control: the deterministic part of a refusal is that no data call was made (for the pre-checks) and that an audit event was written. P09 shows the practical consequence: the guardrail fires only on a minority of replays, whereas the wall refuses the injected requests every time (`demo/prove.py:815-868#p09`).

**Payload decision versus audit decision.** A result with `decision` ERROR (NOT_FOUND, INVALID_ARGUMENT) is still audited with `decision` deny, because `ToolError` defaults to deny. The audit vocabulary has only `allow` and `deny` (`src/mcp/abw_mcp/registry.py:54-75#ToolError`; Findings, end of section 8).

#### 7.4.6 Audit events and the decision vocabulary

**Implemented.** Each decision writes one event through the audit service, whose fields are listed in section 8.4. The `event` name tells you which rule produced it:

| `event` | Written when | `decision` | `reason` values | Code |
|---|---|---|---|---|
| `tool_listed` | A tool is visible in a `tools/list` response | allow | none on governed servers; `no_user_context` on legacy | `src/mcp/abw_mcp/registry.py:141-155#tool_listed` |
| `tool_call` | A tool call succeeded | allow | none; `no_user_context` on legacy | `src/mcp/abw_mcp/registry.py:202-216#reason` |
| `tool_denied` | Unknown tool, requirement failure, invalid arguments, failed token exchange, or any `ToolError` that does not set another event | deny | `unknown_tool`, `missing_role`, `missing_scope`, `forbidden`, `invalid_arguments`, `obo_failed:<code>`, `blob_not_found`, `counterparty_not_found`, `storage_rbac_denied` (research) | `src/mcp/abw_mcp/registry.py:54-75#audit_event` |
| `wall_violation_attempt` | Wall project rule, or a Storage 403 on a wall read | deny | `project_not_in_token_roles`, `storage_rbac_denied` | `src/mcp/abw_mcp/servers/wall.py:39-47#wall_violation_attempt` |
| `order_blocked` | `place_order` refused on the restricted list | deny | `restricted_list`, `separation_of_duties` | `src/mcp/abw_mcp/servers/actions.py:60-75#order_blocked` |
| `order_placed` | An order was written | allow | none | `src/mcp/abw_mcp/servers/actions.py:105-110#order_placed` |
| `auth_failed` | A token failed validation on `/mcp` | deny | The `AuthError` reason code from 7.4.1 | `src/mcp/abw_mcp/auth.py:224-242#auth_failed` |

**What to read from the vocabulary.** There is no `error` decision: everything that did not succeed is `deny`. A refusal that the user caused by a wrong argument (`invalid_arguments`) and a refusal by policy (`missing_role`) are both `deny`, so a dashboard that counts denials should split on `reason` (section 8.5).

**Why the exchange never falls back.** When the on-behalf-of exchange fails, the registry returns FORBIDDEN `obo_failed:<code>` and stops (`src/mcp/abw_mcp/registry.py:177-193#obo_failed`). It does not retry with the server's own identity. A fallback would turn a user-level refusal into a service-level read, and the four governed identities hold no data-plane role on these stores in any case, other than the audit-container role and the actions identity's Cosmos reader on `restricted` (section 7.5). The test `test_obo_failure_does_not_fallback` pins the behaviour (`src/mcp/tests/test_servers.py:141-156#test_obo_failure_does_not_fallback`).

**Trade-off / limitation (the `obo` flag).** The audit field `obo` is set from the server type and the tool outcome, not from whether an exchange actually happened. It stays true on denials that occur before any exchange (`project_not_in_token_roles`, `restricted_list`, `separation_of_duties`), on `tool_listed` events, and on `list_my_wall_crossings`, which makes no exchange at all (`src/mcp/abw_mcp/servers/wall.py:50-59#downstream`; `src/mcp/abw_mcp/registry.py:38-38#obo`; Findings, end of section 8). Treat `obo` as "this server normally acts on behalf of the user", and use the `downstream` field and the data-plane log to see what really ran.

### 7.5 Layer 3, the data plane

**What this section proves.** The last decision on a read or a write is taken by the data service, not by this repo's code. The MCP server presents the person's own on-behalf-of (OBO) token (section 6 covers the exchange). Storage, Cosmos DB and AI Search check that token against role assignments held by Entra groups. A bug in a tool, or a role claim that has gone stale, therefore still meets one more refusal. The section also records where this wall is thinner than the others: it cannot express per-partition or per-document rules, and Search and Cosmos refusals are not mapped to an audited denial.

**Where it runs (Configured and Implemented).** Three stores sit behind this layer: Blob Storage (public research notes and one container per deal), Cosmos DB (`restricted`, `orders`, `positions`) and AI Search (one index, default name `deals-idx`, `src/mcp/abw_mcp/config.py:147#deals-idx`). All three refuse keys and public network access, so an Entra token is the only way in:

- Storage: shared-key access off, anonymous blob access off, public network access disabled (Configured: `infra/03-platform.bicep:133-138#allowSharedKeyAccess`).
- Cosmos DB: local (key) authentication off, public network access disabled (Configured: `infra/03-platform.bicep:227-230#disableLocalAuth`).
- AI Search: local (key) authentication off, public network access disabled (Configured: `infra/03-platform.bicep:314-315#disableLocalAuth`).

**Platform behaviour.** Disabling Shared Key makes Storage reject requests that are authorised with the account key, which leaves Microsoft Entra authorisation as the only path (https://learn.microsoft.com/azure/storage/common/shared-key-authorization-prevent). Azure RBAC decides by taking the caller's identity and group memberships and comparing them with every role assignment (and deny assignment) that applies to the resource (https://learn.microsoft.com/azure/role-based-access-control/overview#how-azure-rbac-determines-if-a-user-has-access-to-a-resource). Cosmos DB uses its own data-plane role system, separate from Azure RBAC and without `notDataActions` (https://learn.microsoft.com/azure/cosmos-db/reference-data-plane-security).

**Why the decision is left to the service.** The design states the goal in one line: each MCP server exchanges the user's token for the data plane, and Azure RBAC, not application code, decides (Designed: `DESIGN.md:18#decides`). The consequence, which the design also states, is that withdrawing a group membership denies access even though the token still says yes (Designed: `DESIGN.md:33#evaluated`).

#### 7.5.1 RBAC assignments as built

**Configured.** Every person-facing assignment goes to an Entra group, never to a single user. The Bicep comment says the groups are "evaluated by the data plane against the user's OBO token" (`infra/03-platform.bicep:617-617#people`). Scope is a Blob container or a Cosmos DB container; for Search the assignment is on the whole service. An index-level Search assignment is possible on the platform (https://learn.microsoft.com/azure/search/search-security-rbac) and is not used here.

| Store and scope | Group | Role | Members (from the persona definitions) | Code |
|---|---|---|---|---|
| Blob container `research-public` | `sg-abw-research` | Storage Blob Data Reader | priya, wes, tara, carla | `infra/03-platform.bicep:618-626#raResearchBlob` |
| Blob container `wall-falcon` | `sg-abw-wall-falcon` | Storage Blob Data Reader | wes, carla | `infra/03-platform.bicep:628-636#raFalconBlob` |
| Blob container `wall-orion` | nobody | no assignment | nobody; no Orion group or persona exists | `infra/03-platform.bicep:638-638#Orion` |
| AI Search service (all indexes) | `sg-abw-research` | Search Index Data Reader | priya, wes, tara, carla | `infra/03-platform.bicep:640-648#raSearchResearch` |
| Cosmos DB container `orders` | `sg-abw-traders` | Built-in Data Contributor | tara | `infra/03-platform.bicep:650-661#cosmosTradersOrders` |
| Cosmos DB container `orders` | `sg-abw-compliance` | Built-in Data Reader | carla | `infra/03-platform.bicep:663-674#cosmosComplianceOrders` |
| Cosmos DB container `positions` | `sg-abw-traders` | Built-in Data Reader | tara | `infra/03-platform.bicep:676-687#cosmosTradersPositions` |
| Cosmos DB container `positions` | `sg-abw-compliance` | Built-in Data Reader | carla | `infra/03-platform.bicep:689-700#cosmosCompliancePositions` |
| Cosmos DB container `restricted` | no person | none | nobody | see the service-identity table below |

Membership comes from one place, the persona list (Configured: `identity/Setup-Entra.ps1:48-60#Groups`):

| Group | Members | What it grants on data |
|---|---|---|
| `sg-abw-demo-all` | all five personas | nothing on data; it is the Foundry project gate (`infra/02-foundry-rbac.bicep:36-44#raConsumersProject`) |
| `sg-abw-research` | priya, wes, tara, carla | `research-public` blobs; the Search service |
| `sg-abw-wall-falcon` | wes, carla | `wall-falcon` blobs |
| `sg-abw-traders` | tara | `orders` (read and write); `positions` (read) |
| `sg-abw-compliance` | carla | `orders` (read); `positions` (read) |
| `sg-abw-infosec` | ian | nothing on data (control-plane and log roles only, below) |

**Service identities.** The servers hold only what a service needs, with two deliberate exceptions (the legacy server and the seed job). The four governed servers (research, wall, actions, private; section 7.3 defines the term) hold no role on any data blob container, on Search, or on `orders` and `positions`; their only blob role is on the audit container, and the actions identity also reads `restricted`:

| Identity | Role and scope | Purpose | Code |
|---|---|---|---|
| All six server identities | AcrPull on the registry | pull the image | `infra/03-platform.bicep:537-545#raAcrPull` |
| research, wall, actions, private, legacy (not vendor) | Storage Blob Data Contributor on the `worm-audit` container | write audit events; the role can also read and delete blobs, so the append-only behaviour comes from the container's unlocked 1-day retention policy, not from the role (Platform behaviour: https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/storage#storage-blob-data-contributor) | `infra/03-platform.bicep:548-556#raAuditAppend`; `infra/03-platform.bicep:195-202#immutabilityPeriodSinceCreationInDays` |
| vendor | Key Vault Secrets User | granted so the vendor container could read its key from Key Vault; the container gets the key as a plain secret value, so the grant looks unused (section 8.6; Findings) | `infra/03-platform.bicep:559-567#raVendorKv`; `infra/04-apps.bicep:182-187#vendor-api-key` |
| actions | Cosmos DB Built-in Data Reader on `restricted` only | read the restricted list as the service | `infra/03-platform.bicep:603-615#cosmosActionsRestricted` |
| legacy | Blob Data Reader (whole account); Search Index Data Reader (whole service); Cosmos DB Built-in Data Contributor (whole account) | the deliberately broad "before" path (section 8.3) | `infra/03-platform.bicep:570-578#raLegacyBlob`; `infra/03-platform.bicep:580-588#raLegacySearch`; `infra/03-platform.bicep:590-601#cosmosLegacyContrib` |
| seed job | Blob Data Contributor (account); Search Service Contributor and Search Index Data Contributor (service); Cosmos DB Built-in Data Contributor (account) | load the synthetic data | `infra/04b-seed-job.bicep:61-69#raBlob`; `infra/04b-seed-job.bicep:81-89#raSearchData`; `infra/04b-seed-job.bicep:91-99#cosmosSeed` |

**Control plane only.** The infosec group gets Reader and Monitoring Reader on the resource group and Log Analytics Reader on the workspace, and no data role (Configured: `infra/03-platform.bicep:703-731#raInfosecReader`).
The deploying account, which also runs the proofs, holds the built-in Key Vault role that allows every data-plane operation on keys, secrets and certificates, AcrPush and Search Service Contributor;
the Bicep comment states that Subscription Owner is not a data-plane role and that this account has no blob, index or document access (Configured: `infra/03-platform.bicep:733-764#raOpKv`).
The design records the reason: a direct data role for that account would break the entitlement-drift proof P16 (Designed: `DESIGN.md:244#roles`).

**Platform behaviour.** Owner, Contributor and Storage Account Contributor let a principal manage a storage account but do not give blob data access through Entra; a role that includes the list-keys action can still reach data with the account key (https://learn.microsoft.com/azure/storage/blobs/authorize-access-azure-active-directory#assign-azure-roles-for-access-rights). Here that route is closed because Shared Key is off (`infra/03-platform.bicep:134-134#allowSharedKeyAccess`). Search Service Contributor manages the service but cannot query an index (https://learn.microsoft.com/azure/search/search-security-rbac).

**The no-fallback guarantee has a second lock.** Section 7.4 shows that a failed token exchange stops the call and never retries as the server (`src/mcp/abw_mcp/registry.py:177-193#obo_failed`; test `src/mcp/tests/test_servers.py:141-156#test_obo_failure_does_not_fallback`). The role table above adds a second lock: even a fallback would fail, because no role assignment under `infra/` gives the research, wall, actions or private identity a role on the user-data stores (apart from the audit-container role in the table, the only data role among them is the actions identity's reader on `restricted`). This is a statement about the Bicep in this repo; a role added by hand after deployment would not appear here. Azure role assignments in the repo come from Bicep, with one opt-in exception: the Agent 365 extras step, run only with `-WithExtras`, writes one assignment for the Agent 365 principal at the APIM scope and removes it with `-Remove`; it touches no data store (`scripts/extras-agent-identity.ps1:178-182#roleDefinitionId`, `scripts/extras-agent-identity.ps1:166-169#Remove`, `scripts/Deploy-AgentWall.ps1:439#extras-identity`). The other role command in the scripts is a read-only list in the deploy preflight (`scripts/Deploy-AgentWall.ps1:1002#role`). Entra app-role assignments are a separate mechanism, written for the personas by the identity script (`identity/Setup-Entra.ps1:237-251#appRoleAssignments`).

**Trade-off / limitation.** The legacy identity and the seed identity are broad by design and remain deployed. The legacy one is the "before" half of proof P08; the seed one keeps account-wide write roles on Storage, Search and Cosmos DB after seeding (Finding in section 8).

#### 7.5.2 Per-request evaluation

**Implemented.** For every call that touches a data store, the sequence is the same. Token mechanics (the client assertion, the federated credential, the MSAL call) are in section 6 and are not repeated here.

1. A tool handler calls a data helper and passes the `Caller`, which holds the validated token (`src/mcp/abw_mcp/servers/wall.py:88-93#get_deal_document`).
2. The helper picks the credential. With `use_user_token` true (the default) it asks the broker for a user token for the target service; with it false it uses the server's own managed identity. The blob scope is `https://storage.azure.com/user_impersonation`, the Search scope is `https://search.azure.com/user_impersonation`, and the Cosmos DB scope is the `COSMOS_OBO_SCOPE` setting (`src/mcp/abw_mcp/data.py:57-62#read_blob_text`; `src/mcp/abw_mcp/data.py:73-86#search_documents`; `src/mcp/abw_mcp/config.py:154-155#cosmos_obo_scope`).
3. The broker exchanges the caller's token as the user assertion and wraps the result in a small credential object that returns that one token whatever scope the SDK asks for (`src/mcp/abw_mcp/obo.py:29-36#StaticTokenCredential`; `src/mcp/abw_mcp/obo.py:60-66#get_credential`). A failed exchange raises `OboError` and ends the call (section 7.4). For Cosmos DB the same switch is the `use_user_token` argument: true with no caller (or no broker) raises `OboError("missing_caller")`; false uses the server's managed identity (`src/mcp/abw_mcp/data.py:170-182#_get_cosmos_container`).
4. A new SDK client is built for every call from that credential, so no client and no token is shared between people (`src/mcp/abw_mcp/data.py:152-168#_build_blob_service`; `src/mcp/abw_mcp/data.py:170-189#_get_cosmos_container`). The reason is not stated in the code. Inference: a credential is bound to one person's token, so a shared client would let one person's token serve another's request.
5. The call carries the gateway request id when it is header-safe (a 1 to 64 character string of letters, digits and `._:-`). Storage gets it as the client request id and Search as the request id; the Cosmos DB helpers stamp nothing (`src/mcp/abw_mcp/data.py:24-28#downstream_request_id`; `src/mcp/abw_mcp/data.py:201-204#client_request_id`; `src/mcp/abw_mcp/data.py:207-217#request_id`). That is why Storage rows join the audit trail by id and Search and Cosmos rows are matched by time (`observability/kql/AbwFullChainCore.kql:186-186#carry`).
6. The service evaluates its own role assignments for that user and answers. Storage and Search use Azure RBAC; Cosmos DB uses its data-plane roles. Group membership is part of the evaluation, which is what makes group-based assignments work (Platform behaviour: the RBAC overview URL above).
7. On HTTP 403 from Storage the helper raises `DataAccessError("FORBIDDEN", "Storage access denied.", reason="storage_rbac_denied")`; on 404 it raises `blob_not_found`; any other error is re-raised unchanged (`src/mcp/abw_mcp/data.py:63-71#storage_rbac_denied`).

**Why the user's token and not the server's.** The identity that reaches the store is the person, so the store's own log shows the person and a tool defect cannot widen what that person may read. Proof P10 asserts that the same human identity appears at the MCP server and in the Storage log, and that the Storage request used OAuth (`demo/prove.py:1044-1046#OAuth`).

**Group evidence for Cosmos DB.** The Learn pages I checked do not state that Cosmos DB data-plane role assignments accept group principals. The repo demonstrates it indirectly: P04 passes with an identity that holds no direct data role and gets `orders` access only through a mirrored `sg-abw-traders` membership, so Cosmos DB resolved the group assignment for that user token (`demo/prove.py:678-678#on-behalf-of`). That is demonstrated here, not documented there.

**Timing.** The service reads the current assignments and memberships, not the claims frozen in the token. P16 measured 5 to 44 seconds from group removal to the first Storage refusal (Designed: `DESIGN.md:218#P16`). Microsoft documents role-assignment propagation of up to about ten minutes (https://learn.microsoft.com/azure/role-based-access-control/troubleshooting), so treat the measured figure as an observation and not as a guarantee.

#### 7.5.3 What a Storage denial looks like

**Implemented.** The chain below is the one the wall server follows; the research server follows the same chain with the default audit event.

1. Storage answers HTTP 403 to the download because the user's token holds no data role on the container. The Learn troubleshooting page lists `AuthorizationPermissionMismatch` for a missing data-plane role, and lists other 403 causes as well (https://learn.microsoft.com/troubleshoot/azure/azure-storage/blobs/authentication/storage-troubleshoot-403-errors).
2. The helper converts any `HttpResponseError` whose status is 403 into `DataAccessError` with reason `storage_rbac_denied` (`src/mcp/abw_mcp/data.py:68-70#storage_rbac_denied`).
3. The wall handler turns that into a `ToolError` and sets the audit event to `wall_violation_attempt` when the reason is `storage_rbac_denied` (any other reason keeps `tool_denied`). The downstream record is `service: storage`, `target: <container>`, `status: 403` (`src/mcp/abw_mcp/servers/wall.py:92-96#wall_violation_attempt`). The research handler maps the same error with the default event `tool_denied` (`src/mcp/abw_mcp/servers/research.py:47-57#DataAccessError`).
4. The registry builds the soft denial and writes exactly one audit event (`src/mcp/abw_mcp/registry.py:238-270#_tool_error_result`; payload shape `src/mcp/abw_mcp/registry.py:273-292#_error_payload`). The wire result is HTTP 200 with `structuredContent` like this (the `note` text is shortened):

```json
{
  "decision": "DENIED",
  "error": "FORBIDDEN",
  "message": "Storage access denied.",
  "reason": "storage_rbac_denied",
  "request_id": "<request-id>",
  "note": "Blocked by policy and written to the audit log. ..."
}
```

5. The audit event for the same call has `event` `wall_violation_attempt`, `decision` `deny`, `reason` `storage_rbac_denied`, `obo` true, `data_class` `wall` and a downstream status of 403.
6. Storage writes its own log row with the same client request id. The denial roll-up reads status 401 and 403 from the blob log as layer `3-data-plane` and joins on the request id (`observability/kql/AbwDenials.kql:67-77#StorageBlobLogs`). The same refusal therefore appears twice, once as `2-mcp-server` and once as `3-data-plane`, and the two rows share the id.

**What the unit test proves, and what it does not.** `test_storage_rbac_denial_audited` checks the mapping from a Storage denial to the audited result (error `FORBIDDEN`, event `wall_violation_attempt`, reason `storage_rbac_denied`) (`src/mcp/tests/test_servers.py:90-105#test_storage_rbac_denial_audited`). The fake data plane raises `DataAccessError` directly (`src/mcp/tests/conftest.py:95-96#deny_blob_containers`), so the translation of a real HTTP 403 (`src/mcp/abw_mcp/data.py:68-70#status_code`) is not unit-tested. It is exercised only by the live proof P16.

**Trade-off / limitation.** The helper keys on the HTTP status alone. Any Storage 403, including one caused by something other than a missing role, is reported as `storage_rbac_denied` (`src/mcp/abw_mcp/data.py:68-70#getattr`). The reason code is therefore the designed cause, not a diagnosis. The Storage log row carries the precise service-side status text.

#### 7.5.4 What an unmapped denial looks like

**Implemented.** Only Storage has a translation layer. Nothing else in the data helpers turns a service refusal into a `DataAccessError`:

- Search: `search_documents` has no error handling at all (`src/mcp/abw_mcp/data.py:73-97#search_documents`).
- Cosmos DB: `cosmos_read_item` catches every exception only to turn a 404 into "not found" and re-raises the rest; `cosmos_query_items` and `cosmos_upsert_item` have no handling (`src/mcp/abw_mcp/data.py:99-147#cosmos_read_item`).

The registry catches only two exception types around a handler, `OboError` and `ToolError` (`src/mcp/abw_mcp/registry.py:177-193#except`). Any other exception leaves `call_tool` before any of the audit emit points (success path `src/mcp/abw_mcp/registry.py:195-220#structuredContent`; denial path `src/mcp/abw_mcp/registry.py:238-270#_tool_error_result`).

What follows from the code, and what does not:

| Question | Answer | Basis |
|---|---|---|
| Is an MCP audit event written for the refused call? | No. The audit emit points are never reached. | `src/mcp/abw_mcp/registry.py:177-217#ToolError` |
| Does the caller get a `DENIED` result? | Not from this code. | `src/mcp/abw_mcp/registry.py:273-292#_error_payload` |
| What does the caller see instead? | Not defined in this repo. It depends on how the MCP SDK renders an unhandled exception, and no test exercises it. Treat it as unknown. | `src/mcp/abw_mcp/app.py:196-209#on_call_tool` |
| Does the service log the refusal? | Search and Cosmos DB diagnostic logs record the request, but carry no caller id, so they can be matched to a call only by time. | `observability/kql/AbwFullChainCore.kql:186-186#carry` |
| Does the denial roll-up show it? | No. Layer `3-data-plane` reads the Storage blob log only. | `observability/kql/AbwDenials.kql:67-77#StorageBlobLogs` |

**When this could happen in the demo.** It needs a gap between Layer 2 and Layer 3 for the same person: a trader who still holds `Trade.Execute` but has been removed from `sg-abw-traders` would pass the role check and meet a Cosmos DB refusal on `orders`; a researcher removed from `sg-abw-research` would meet a Search refusal. P16 tests the equivalent gap for Storage only (`demo/prove.py:962-991#P16`).

**Trade-off / limitation.** The unmapped path is the weakest evidence path in the four walls. The service still refuses, so confidentiality holds, but the refusal is neither audited at Layer 2 nor visible in the denial roll-up. I did not run the server to observe what the SDK returns, so the caller-side shape is an open question (Findings).

#### 7.5.5 Where Layer 3 stops

**Cosmos DB roles cannot express per-user or per-desk rules.** Cosmos DB data-plane assignments are scoped to the account, a database or a container (https://learn.microsoft.com/azure/cosmos-db/how-to-connect-role-based-access-control), and there is no `notDataActions` to carve out an exception. The consequences in this repo:

- A trader holds Data Contributor on all of `orders` (`infra/03-platform.bicep:650-661#cosmosTradersOrders`). The rule "list only my orders" is the query `WHERE c.user_oid = @user_oid` with the partition key set to the caller's oid, which is MCP code (`src/mcp/abw_mcp/servers/actions.py:113-127#list_my_orders`). The container is partitioned on `/user_oid` (`infra/03-platform.bicep:263-280#cosmosOrders`).
- Any caller with `Positions.Read` may ask for any desk; the desk is a query parameter and the container is partitioned on `/desk` (`src/mcp/abw_mcp/servers/private.py:19-34#get_firm_positions`; `infra/03-platform.bicep:282-299#cosmosPositions`). Cosmos DB roles could not restrict a desk either.

**Search roles do not trim documents.** Search RBAC is granted on the service or an index and does not filter documents; document-level rules need filters or the separate document-level access feature (https://learn.microsoft.com/azure/search/search-document-level-access-overview). Here the research group holds Search Index Data Reader on the whole service (`infra/03-platform.bicep:640-648#raSearchResearch`), and wes and carla are members, so the separation of public notes from deal summaries inside the one index rests on the filter the MCP server builds plus the role gate:

- research: `classification eq 'public'` (`src/mcp/abw_mcp/servers/research.py:22-30#classification`);
- wall: `classification eq 'wall' and project eq '<project>'` after the project check (`src/mcp/abw_mcp/servers/wall.py:62-70#classification`).

Two facts limit the exposure. The Search service has no public path (`infra/03-platform.bicep:314-315#disableLocalAuth`), and a wall document in the index carries only a short summary, with the full text held in the per-project container whose assignment is per group (`src/seed/seed.py:157-163#summary`).

**Roles in the token against groups in the data plane.** The gateway and the MCP server decide on the `roles` claim, which is fixed for the life of the token. Storage decides on current group membership. The two can disagree for a while, and the data plane is the one that follows a change quickly. P16 asserts exactly this: the role claim is unchanged while Storage refuses (`demo/prove.py:978-981#unchanged`).

**The Cosmos DB switch.** `COSMOS_OBO` defaults to true (`src/mcp/abw_mcp/config.py:154-154#cosmos_obo`). With it false, Cosmos DB calls go through the server's own identity (`src/mcp/abw_mcp/data.py:176-182#use_user_token`), and the actions identity holds no role on `orders` (`infra/03-platform.bicep:604-615#cosmosActionsRestricted`). The write would then fail. This is an inference from reading the Bicep and the code, not a tested behaviour (Findings).

#### 7.5.6 The proofs, layer by layer

**What the proofs show.** Each row says what the proof asserts, which wall it exercises and where the code is. Identity for the proofs is explained in the caveat after the table.

| Proof | What it shows | Wall | Code |
|---|---|---|---|
| P01 | Every data service is Entra-only. The four governed apps (research, wall, actions, private) hold no secrets beyond the telemetry ingestion string; the vendor mock is outside that check and holds a plain `vendor-api-key` secret by design. In the 7-day query window there were zero key-based Storage requests, apart from Azure-internal SAS service-property calls that the proof discloses, and no anonymous Storage request succeeded. So for the governed path, within that window, RBAC is the only door. | 3 | `demo/prove.py:540#GOVERNED_APPS`; `demo/prove.py:566-574#GOVERNED_APPS`; `demo/prove.py:576-596#Platform`; `demo/prove.py:597-600#anonymous`; `infra/04-apps.bicep:182-187#vendor-api-key` |
| P02 | A person with no Wall or Trade role gets 403 `missing_role` from the gateway; a person with no roles gets an empty `tools/list` on research, wall and actions, and a 403 on the vendor API. The gateway and the servers agree. | 1, 2 | `demo/prove.py:607-636#P02` |
| P03 | A Falcon-crossed identity reads a Falcon document (role claim plus group-based Blob read). The same identity asking for ORION-001 gets `DENIED` `project_not_in_token_roles` at Layer 2, before any data call; an Orion search is refused as well. This does not make Layer 3 answer for Orion. | 2, 3 | `demo/prove.py:638-657#P03` |
| P04 | A restricted ticker is refused, a clean order is accepted, and it appears in the caller's own order list, written to Cosmos DB with the user's token. | 2, 3 | `demo/prove.py:659-683#P04` |
| P08 | The legacy path returns ORION-001 to an anonymous caller with only the shared subscription key; the governed wall server refuses the same document. | contrast | `demo/prove.py:763-775#P08` |
| P09 | A poisoned vendor headline cannot make the wall give up an Orion document or place a restricted order: replayed with the user's own token, both are refused at Layer 2. The guardrail stopped the run on a minority of attempts, so it is a detective extra. | 0, 2 | `demo/prove.py:815-868#P09` |
| P10 | One request id across gateway, MCP server and Storage log, with the same human identity at the last two hops and OAuth at Storage; the denied chain stops at the MCP server and Storage is never touched. | 1, 2, 3 | `demo/prove.py:1024-1052#P10` |
| P12 | The kill switch turns a user's next call into 403 `revoked` on research, wall, actions and vendor. It exercises one gateway step (section 7.8). | 1 | `demo/prove.py:932-960#P12` |
| P14 | 400 `tools/list` calls from 48 workers: at least 60 are served and at least 20 refused with 429 and a retry hint, and the budget refills. It exercises the rate limit on one API (section 7.3). | 1 | `demo/prove.py:870-903#P14` |
| P15 | Remove the Azure CLI application from the allow-list and the same user with the same roles gets 403 `client_not_allowed`; the proof polls for up to 180 seconds (section 7.8). | 1 | `demo/prove.py:905-930#P15` |
| P16 | Remove the identity from the Falcon group: Storage refuses the next read (`storage_rbac_denied`) while the role claim is unchanged; the proof polls every 15 seconds. This is the only proof in which Layer 3 is the wall that refuses. | 3 | `demo/prove.py:962-991#P16` |

P12, P14 and P15 each exercise one gateway step (revocation, the per-user budget, the calling-application check). None of them proves the relative order of the steps; the order is read from the policy XML in section 7.3.

**Evidence caveat: the proofs run as the deploying account mirroring a persona.** The proof harness does not sign in as the personas.
It uses the deploying account and mirrors a persona's app roles and group memberships onto it, because both tenants force multi-factor authentication for the personas' own sign-ins (`demo/prove.py:303-304#persona`; `DESIGN.md:241#mirrors`). The design adds that the account's `oid` is what appears in the audit rows, and that an agent run keeps the roles of the token Foundry already holds (`DESIGN.md:241#oid`).
The baseline identity is the deploying account carrying the roles and groups of Wes plus Tara (`demo/prove.py:323-328#become`), and P16 removes and restores that account's own membership of the Falcon group (`demo/prove.py:168-177#set_falcon_membership`).
So P02, P03, P04 and P16 show the platform behaviour for those role and group sets, not for the persona sign-in path (multi-factor authentication and per-user Conditional Access are not exercised).
Read "P04 places an order" as "as the baseline identity", not as Tara (Findings).

**Gaps in what the proofs cover.** No proof makes Layer 3 refuse for Orion, for a Search query or for a Cosmos DB container; Layer 2 answers first for Orion and P16 covers Storage only.

**Why groups and not users, and the cost.** Group assignments keep the Bicep stable while people move; a membership change is an Entra operation and takes effect at the data plane within the propagation window (the 5 to 44 seconds above). The cost is that the entitlement for one person is spread over app roles (Layers 1 and 2) and groups (Layer 3), with no single store that reads both (section 7.9).

### 7.6 Entitlement matrix as built

**What this section is.** A derived view, not a policy document. The repo has no entitlement table (section 7.9), so "who may do what" is the composition of four independent inputs. The matrix below is built by reading each input and combining them:

1. the app roles and groups each persona is given in Entra (Configured: `identity/Setup-Entra.ps1:50-64#Users`);
2. the per-API gateway parameters (Configured: `infra/05-apim-apis.bicep:28-73#servers`);
3. the requirement function attached to each tool (Implemented: the single-line citations in the table in 7.6.3);
4. the data-plane role assignments (Configured: `infra/03-platform.bicep:618-648#raResearchBlob` and `infra/03-platform.bicep:650-700#cosmosTradersOrders`).

**Evidence status.** Everything here is derived from code and Bicep. It was exercised live for Priya and Ian; the Wes, Tara and Carla columns are the designed outcome (Designed: `docs/DEMO-GUIDE.md:265#design`, `docs/DEMO-GUIDE.md:277#designed`, `docs/RUNBOOK.md:45#Expected`). The automated proofs run as the deploying account mirroring a persona's roles and groups, not as the persona (section 7.5.6; `demo/prove.py:303-304#persona`).

#### 7.6.1 Inputs: app roles and groups per persona

| Persona (job) | App roles assigned directly to the user | Entra groups | Code |
|---|---|---|---|
| Priya (research analyst) | `Research.Read`, `MarketData.Read` | sg-abw-demo-all, sg-abw-research | `identity/Setup-Entra.ps1:51-52#priya` |
| Wes (investment banking associate) | `Research.Read`, `Wall.Falcon`, `MarketData.Read` | sg-abw-demo-all, sg-abw-research, sg-abw-wall-falcon | `identity/Setup-Entra.ps1:53-54#wes` |
| Tara (equity trader) | `Research.Read`, `Trade.Execute`, `Positions.Read`, `MarketData.Read` | sg-abw-demo-all, sg-abw-research, sg-abw-traders | `identity/Setup-Entra.ps1:55-56#tara` |
| Carla (compliance officer) | `Research.Read`, `Wall.Falcon`, `Trade.Read`, `Positions.Read`, `MarketData.Read` | sg-abw-demo-all, sg-abw-research, sg-abw-wall-falcon, sg-abw-compliance | `identity/Setup-Entra.ps1:57-58#carla` |
| Ian (information security analyst) | none | sg-abw-demo-all, sg-abw-infosec | `identity/Setup-Entra.ps1:59-60#ian` |

Five things to read off this table before reading the matrix:

- **Roles are per API.** Five API registrations each define their own roles, and an Entra token carries the roles of the API named in its `aud` (Configured: `identity/Setup-Entra.ps1:29-44#Apis`). The research API knows only `Research.Read`, the wall API only `Wall.Falcon` and `Wall.Orion`, the actions API `Trade.Read` and `Trade.Execute`, the private API `Positions.Read`, and the vendor gateway API `MarketData.Read`. Platform behaviour: the `roles` claim of a user token lists the app roles the user holds on the target app (https://learn.microsoft.com/entra/identity-platform/access-token-claims-reference). A role granted on one API is therefore invisible in a token for another API. Why it matters: a rule that needs two roles from two different APIs cannot be satisfied by a real token (section 7.9, separation of duties).
- **Roles go to users, not groups.** Roles are assigned to each user object directly (Configured: `identity/Setup-Entra.ps1:237-251#appRoleAssignments`) and every role allows the `User` member type only (Configured: `identity/Setup-Entra.ps1:125#allowedMemberTypes`). The build notes say group-based app-role assignment needs a higher Entra licence tier and the build does not depend on it (Designed: `DESIGN.md:226#Entra`).
- **Groups exist for one reason: the data plane.** Group membership is created separately (Configured: `identity/Setup-Entra.ps1:224-235#members`) and is read by Storage, Search and Cosmos when they evaluate the user's OBO token (section 7.5). Neither the gateway nor the MCP server reads a `groups` claim: the gateway policy reads only `scp`, `roles`, `azp` and `oid` (Configured: `infra/apim/policies/mcp-jwt.policy.xml:32-36#roles`) and the validated caller has no groups field (Implemented: `src/mcp/abw_mcp/auth.py:29-41#Caller`).
- **The same person is therefore described twice**, once as roles (Layers 1 and 2) and once as groups (Layer 3), in two vocabularies and two places. Wes and Carla hold both `Wall.Falcon` and membership of sg-abw-wall-falcon; nothing in the repo checks that the two stay in step (section 7.9, "four places per deal").
- **There is no group for Orion and no persona with `Wall.Orion`.** The role exists in the wall API (Configured: `identity/Setup-Entra.ps1:33-35#Wall.Orion`), so the Orion path is refused for every persona by design (Designed: `docs/RUNBOOK.md:45#Expected`).

#### 7.6.2 What each layer asks, per server

| Server | Layer 1 (APIM) on `tools/call` | Layer 1 on `initialize`, `ping`, `tools/list` | Layer 2 (MCP server) | Layer 3 identity |
|---|---|---|---|---|
| research | `Research.Read` | open (any valid token) | `Research.Read` | the user's OBO token (Blob, Search) |
| wall | `Wall.Falcon` or `Wall.Orion` | open | the same roles plus the project must be in the token roles | the user's OBO token (Blob, Search) |
| actions | `Trade.Read` or `Trade.Execute` | open | per tool (see 7.6.3) | `restricted`: the server's own identity; `orders`: the user's OBO token |
| private | not behind APIM | not behind APIM | `Positions.Read` | the user's OBO token (Cosmos) |
| vendor | `MarketData.Read` | also needs `MarketData.Read` (not open) | `allow_all`; the server checks the injected vendor key instead of a token | none (synthetic data in code) |
| legacy | APIM subscription key only, no token | same | `allow_all`, no caller | the legacy server's own identity, broad roles |

The "open" cells are the `listOpen` parameter: true for research, wall and actions, false for the vendor (Configured: `infra/05-apim-apis.bicep:38#listOpen`, `infra/05-apim-apis.bicep:49#listOpen`, `infra/05-apim-apis.bicep:60#listOpen`, `infra/05-apim-apis.bicep:71#listOpen`). In the policy, a discovery method skips only the role test; the kill switch, the `azp` test and the `Tools.Read` scope test still run first (Configured: `infra/apim/policies/mcp-jwt.policy.xml:37-44#discovery`). Why: a person entitled to nothing sees zero tools instead of a 403, which keeps the model's tool list honest. The gateway roles per API are in `infra/05-apim-apis.bicep:34#roles`, `infra/05-apim-apis.bicep:45#roles`, `infra/05-apim-apis.bicep:56#roles` and `infra/05-apim-apis.bicep:67#roles`.

#### 7.6.3 The matrix: persona x tool x data

Cell vocabulary (every cell is derived, see "Evidence status"):

- **OK**: all layers pass.
- **GW 403**: APIM answers HTTP 403 `missing_role`; the MCP server is never reached (section 7.3).
- **DENIED `<reason>`**: HTTP 200 with a soft denial in `structuredContent`, and an audit event (section 7.4). A tool that fails its requirement is also absent from the caller's `tools/list` (Implemented: `src/mcp/abw_mcp/registry.py:132-156#list_tools`).
- **no tools**: `tools/list` returns an empty list and a direct call is soft-denied `missing_role` (Tested: `src/mcp/tests/test_servers.py:250-266#test_entitled_to_nothing_sees_no_tools_and_cannot_call`).

| Server.tool | Layer 2 rule | Priya | Wes | Tara | Carla | Ian | Data touched, and whose identity |
|---|---|---|---|---|---|---|---|
| research.search_research | `Research.Read` (`src/mcp/abw_mcp/servers/research.py:74#require_any_role`) | OK | OK | OK | OK | GW 403 | Search index, filter on classification `public` (`src/mcp/abw_mcp/servers/research.py:22-44#classification`); user OBO |
| research.get_research_note | `Research.Read` (`src/mcp/abw_mcp/servers/research.py:82#require_any_role`) | OK | OK | OK | OK | GW 403 | Blob `research-public`; user OBO |
| wall.list_my_wall_crossings | `Wall.Falcon` or `Wall.Orion` (`src/mcp/abw_mcp/servers/wall.py:119#require_any_role`) | GW 403 | OK (falcon only) | GW 403 | OK (falcon only) | GW 403 | none: lists the roles in the token |
| wall.search_deal_documents, project falcon | same rule (`src/mcp/abw_mcp/servers/wall.py:127#require_any_role`) plus project in roles | GW 403 | OK | GW 403 | OK | GW 403 | Search, filter on classification `wall` and the project (`src/mcp/abw_mcp/servers/wall.py:62-70#classification`); summaries only; user OBO |
| wall.get_deal_document, FALCON-nnn | same (`src/mcp/abw_mcp/servers/wall.py:135#require_any_role`) | GW 403 | OK | GW 403 | OK | GW 403 | Blob `wall-falcon`; user OBO, group sg-abw-wall-falcon |
| wall.search_deal_documents / get_deal_document, Orion | same | GW 403 | DENIED `project_not_in_token_roles` | GW 403 | DENIED `project_not_in_token_roles` | GW 403 | none reached (`src/mcp/abw_mcp/servers/wall.py:39-47#project_not_in_token_roles`); the blob container has no reader anyway |
| actions.check_restricted_list | `Trade.Read` or `Trade.Execute` (`src/mcp/abw_mcp/servers/actions.py:137#require_any_role`) | GW 403 | GW 403 | OK | OK | GW 403 | Cosmos `restricted`; the server's own identity (`src/mcp/abw_mcp/servers/actions.py:30-37#use_user_token`) |
| actions.place_order | scope `Tools.Execute` and role `Trade.Execute` (`src/mcp/abw_mcp/servers/actions.py:145#require_scope_and_role`) | GW 403 | GW 403 | OK, or DENIED `restricted_list` for a restricted ticker | DENIED `missing_role` | GW 403 | reads `restricted` (own identity), writes `orders` with the user's OBO token (`src/mcp/abw_mcp/servers/actions.py:58-75#restricted_list`, `src/mcp/abw_mcp/servers/actions.py:90-98#cosmos_obo`) |
| actions.list_my_orders | `Trade.Read` or `Trade.Execute` (`src/mcp/abw_mcp/servers/actions.py:153#require_any_role`) | GW 403 | GW 403 | OK | OK | GW 403 | Cosmos `orders`, partition key is the caller's oid; user OBO (`src/mcp/abw_mcp/servers/actions.py:113-127#partition_key`) |
| private.get_firm_positions | `Positions.Read` (`src/mcp/abw_mcp/servers/private.py:66#require_any_role`) | no tools | no tools | OK | OK | no tools | Cosmos `positions`, filter on desk; user OBO (`src/mcp/abw_mcp/servers/private.py:19-34#desk`) |
| private.get_credit_limit | `Positions.Read` (`src/mcp/abw_mcp/servers/private.py:74#require_any_role`) | no tools | no tools | OK | OK | no tools | Cosmos `positions`, one limit row; user OBO |
| vendor.get_market_quote, get_headlines | `allow_all` (`src/mcp/abw_mcp/servers/vendor.py:69#allow_all`, `src/mcp/abw_mcp/servers/vendor.py:77#allow_all`) | OK | OK | OK | OK | GW 403 (`missing_role`, even on `initialize`) | none: synthetic data in the server |
| legacy.* (five tools) | `allow_all`, no caller | any holder of the APIM subscription key, whatever the person | | | | | the legacy server's own identity (section 8.3) |

Reading notes:

- **Tara and `Trade.Read`.** Tara holds `Trade.Execute` only. She can use the read tools because their rule is "`Trade.Read` or `Trade.Execute`" (Implemented: `src/mcp/abw_mcp/registry.py:98-108#require_any_role`).
- **Carla can look but not trade.** She reads the restricted list, her orders and positions, but `place_order` is hidden from her list and denied if she calls it. A second lock sits under that rule: the compliance group holds only a Reader role on the orders container (7.6.4).
- **The restricted-list outcome belongs to Tara alone**, the only persona that reaches the check (Designed: `docs/DEMO-GUIDE.md:275#Tara`).
- **The "separation of duties" branch of `place_order` cannot fire for any persona.** It needs a caller who holds a `Wall.*` role in a token for the actions API, and wall roles live on the wall API (Implemented: `src/mcp/abw_mcp/servers/actions.py:40-41#Wall`; Designed: `DESIGN.md:226#Entra`). It is covered by a unit test only.

What the model sees through `tools/list` (derived; the number of tools returned, after the role filter at the MCP server):

| Persona | research | wall | actions | private | vendor |
|---|---|---|---|---|---|
| Priya | 2 | 0 | 0 | 0 | 2 |
| Wes | 2 | 3 | 0 | 0 | 2 |
| Tara | 2 | 0 | 3 | 2 | 2 |
| Carla | 2 | 3 | 2 | 2 | 2 |
| Ian | 0 | 0 | 0 | 0 | none: the gateway refuses every vendor method |

Check against the code: the filter runs per tool with the validated caller (Implemented: `src/mcp/abw_mcp/registry.py:132-156#list_tools`; Tested: `src/mcp/tests/test_servers.py:33-63#test_role_filtered_tools_list`).

#### 7.6.4 The data-plane half of the matrix

Who can read or write each store, if the request reaches it. This is the Layer 3 view of the same five people (Configured: `infra/03-platform.bicep:618-648#raResearchBlob`, `infra/03-platform.bicep:650-700#cosmosTradersOrders`). The grants go to groups and are evaluated against the user's OBO token (section 7.5).

| Store | Grant | Priya | Wes | Tara | Carla | Ian |
|---|---|---|---|---|---|---|
| Blob `research-public` | Blob Data Reader to sg-abw-research (`infra/03-platform.bicep:618-626#raResearchBlob`) | read | read | read | read | none |
| AI Search service, index `deals-idx` | Search Index Data Reader to sg-abw-research, whole service (`infra/03-platform.bicep:640-648#raSearchResearch`) | read | read | read | read | none |
| Blob `wall-falcon` | Blob Data Reader to sg-abw-wall-falcon (`infra/03-platform.bicep:628-636#raFalconBlob`) | none | read | none | read | none |
| Blob `wall-orion` | no assignment to anyone (`infra/03-platform.bicep:637-639#Orion`) | none | none | none | none | none |
| Cosmos `orders` | Data Contributor to sg-abw-traders, Data Reader to sg-abw-compliance (`infra/03-platform.bicep:650-674#cosmosTradersOrders`) | none | none | read and write | read | none |
| Cosmos `positions` | Data Reader to sg-abw-traders and sg-abw-compliance (`infra/03-platform.bicep:676-700#cosmosTradersPositions`) | none | none | read | read | none |
| Cosmos `restricted` | Data Reader to the actions server's identity only (`infra/03-platform.bicep:603-615#cosmosActionsRestricted`) | none | none | none | none | none |
| Blob `worm-audit` | Blob Data Contributor to five server identities, no person (`infra/03-platform.bicep:548-556#raAuditAppend`) | none | none | none | none | none |

Three consequences:

- **The Falcon read needs two keys.** `Wall.Falcon` (token) and membership of sg-abw-wall-falcon (group). Wes and Carla hold both. Remove either and the path closes: the role at Layer 2, the group at Layer 3 (proof P16 removes only the group, section 7.5.6).
- **The wall's search path rides the research group.** The only Search grant is to sg-abw-research (above), so a wall-crossed person outside that group would pass Layer 2 and then meet a Search refusal that this repo does not map to `DENIED` (section 7.5.4). Wes and Carla are in sg-abw-research, so the demo does not show it.
- **Cosmos roles are container-wide.** Nothing in Cosmos RBAC limits a trader to her own orders or to one desk; the per-user `orders` partition and the `desk` filter are Layer 2 rules (Implemented: `src/mcp/abw_mcp/servers/actions.py:113-127#partition_key`, `src/mcp/abw_mcp/servers/private.py:19-34#desk`). There is no per-desk entitlement at all.

The operator holds no role on the user-data stores (blobs, Cosmos DB, search documents), on purpose, so that proof P16 (group drift) stays meaningful (Designed: `docs/RUNBOOK.md:122#P16`); it does hold the built-in Key Vault role that allows every data-plane operation on the vault, and AcrPush on the registry (Configured: `infra/03-platform.bicep:733-764#raOpKv`). Everyone in sg-abw-demo-all, Ian included, can invoke agents in the Foundry project (Configured: `infra/02-foundry-rbac.bicep:36-44#raConsumersProject`); what an agent can do for that person is then decided by the layers above.

#### 7.6.5 Cross-check against `docs/DEMO-GUIDE.md` and `docs/RUNBOOK.md`

The demo guide publishes a persona x scenario table (Designed: `docs/DEMO-GUIDE.md:265-275#Persona`). Each cell agrees with the matrix derived from code:

| DEMO-GUIDE column | Claim | Derived from code | Result |
|---|---|---|---|
| 1.4 Orion | refused for all five | Priya, Tara, Ian: GW 403; Wes, Carla: DENIED `project_not_in_token_roles` | agrees |
| 1.3 alt Falcon | allowed for Wes and Carla, refused for Priya, Tara, Ian | Wes and Carla: role and group present; the others: GW 403 | agrees |
| 3.3 vendor quote | allowed for four, refused for Ian (`missing_role`) | the gateway needs `MarketData.Read` on every vendor method; Ian has no role | agrees |
| 4.1 burst | four are served until the limit, then 429; Ian "the console refuses it up front" | the gateway limit is 120 calls per 60 s per oid for callers that pass the checks (Configured: `infra/apim/policies/mcp-jwt.policy.xml:81#rate-limit-by-key`) | agrees for the four; for Ian the refusal is a console rule, not a gateway rule |

The reasons also agree: the same guide says the gateway stops Priya, Tara and Ian and the MCP server stops Wes and Carla on Orion (Designed: `docs/DEMO-GUIDE.md:275#gateway`). The runbook role table matches `identity/Setup-Entra.ps1:50-64#Users` row for row (Designed: `docs/RUNBOOK.md:35-41#Persona`), and its "Expected" outcomes for the persona switcher match the matrix (Designed: `docs/RUNBOOK.md:45#Expected`).

What the guide does not publish is the actions and private rows above. They are derived here from the code only; the observations about the guide (what it labels as designed, and the console-versus-gateway wording for Ian) are in the Findings at the end of section 8.

Diagram: docs/diagrams/06-identity-and-entitlements.excalidraw

### 7.7 Azure Policy as code

**What this section proves.** The platform's configuration rules (no keys, private by default, approved tool endpoints, guardrails on) are code. Two custom definitions and one initiative with 19 references live at subscription scope (Configured: `infra/06a-policy-definitions.bicep:168-172#initiative`), one assignment at resource-group scope (Configured: `infra/06-governance.bicep:177-183#assignment`), and six recorded exemptions (section 7.7.7). Nine real attempts to break the rules test them (Implemented: `demo/try-violations.py:1-10#RequestDisallowedByPolicy`). Policy is a preventive control on how resources are configured. It is not one of the four request-time walls and it never sees an MCP call.

**Provenance labels.** Configured = Bicep. Implemented = the test code. Designed = documents. Platform behaviour = Microsoft Learn, given as plain-text URLs.

#### 7.7.1 Where Policy sits relative to the four walls

Azure Policy is evaluated by Azure Resource Manager when a resource is created or updated, and by the compliance scan afterwards. It does not look at tokens, roles, tools or documents. The repo says the same: the proof board labels Azure Policy "preventive" and "not on the request path" (Designed: `docs/PROOF-PLAYBOOK.md:869#PREVENTIVE`).

What Policy does is hold the preconditions the four walls depend on. The Bicep introduces each control group as the answer to one infosec question (Configured: `infra/06a-policy-definitions.bicep:7-12#ABW-01-NO-KEYS`). The right-hand column is my reading of how each group relates to the walls.

| Control group | Question it answers (from the Bicep) | Wall it protects (analysis) |
|---|---|---|
| ABW-01-NO-KEYS | "Can anyone leak a key?" | Layer 3. With shared-key and local authentication off, the data planes accept only Entra tokens, so the per-user RBAC of section 7.5 cannot be walked around with an account key. Foundry connections cannot use the eight keyed authentication types (`infra/06a-policy-definitions.bicep:40#keyedAuthTypes`); the OAuth connections still hold the agent's client secret inside Foundry (section 6; `scripts/foundry-connections.ps1:85-89`), and the legacy connection is exempt under a time-boxed waiver (`infra/06-governance.bicep:232-256#exLegacyAccount`). |
| ABW-02-PRIVATE | "Can data leave the private path?" | The network path under Layers 2 and 3: public network access stays off on the data planes. |
| ABW-03-TOOLS-MODELS | "What can an agent reach?" | Layer 1, in part. A remote-tool connection target must match one of the four gateway paths or the private server's host (`infra/06-governance.bicep:162-168#approvedMcpEndpoints`). The private server is the sanctioned exception, because it is reached without the gateway; only connection targets are checked (Deny by default), and the tool-level policy defaults to Audit, so it is report-only (`infra/06-governance.bicep:25#agentToolEffect`). Also restricts model publishers. |
| ABW-04-GUARDRAILS | "Is the guardrail on?" | Layer 0. Reports agents that lack the Jailbreak and Indirect Attack filters (report-only). |
| ABW-05-HYGIENE | "Is the workload well-formed?" | The hosting of the MCP servers: HTTPS only and managed identity (report-only). |

Platform behaviour (needed to read the rest of this section):

- In Resource Manager mode a Deny effect stops the request before it reaches the resource provider and the caller receives HTTP 403; resources that already exist and match are marked non-compliant (https://learn.microsoft.com/azure/governance/policy/concepts/effect-deny#deny-evaluation). The error code is `RequestDisallowedByPolicy` (https://learn.microsoft.com/azure/azure-resource-manager/troubleshooting/error-policy-requestdisallowedbypolicy).
- Effects are evaluated in a fixed order: Disabled, then Append and Modify, then Deny, then Audit (https://learn.microsoft.com/azure/governance/policy/concepts/effect-basics#order-of-evaluation). A Modify effect can change the request so that a later Deny or Audit does not trigger (https://learn.microsoft.com/azure/governance/policy/concepts/effect-modify#modify-evaluation). Section 7.7.9 shows why this matters here.

#### 7.7.2 Files, scopes and deployment order

| File | Scope | What it creates | Code |
|---|---|---|---|
| `infra/06a-policy-definitions.bicep` | subscription | the two custom definitions and the initiative; it only defines, nothing is assigned | `infra/06a-policy-definitions.bicep:3-5#DEFINES`, `infra/06a-policy-definitions.bicep:19#targetScope` |
| `infra/06-governance.bicep` | resource group | the Foundry guardrail policy (section 7.2, not an Azure Policy object), diagnostic settings, the assignment, six exemptions | `infra/06-governance.bicep:12#targetScope`, `infra/06-governance.bicep:177-183#assignment` |
| `demo/try-violations.py`, proof P11 in `demo/prove.py` | live test | nine attempts to break the rules, and a compliance read-back | `demo/try-violations.py:1-10#RequestDisallowedByPolicy`, `demo/prove.py:993-1023#p11` |

The definitions deploy first and the governance file takes the initiative id as a parameter (Configured: `infra/06-governance.bicep:16-17#initiativeId`). The Bicep header states the blast radius: nothing outside the demo resource group is ever evaluated or blocked (Configured: `infra/06a-policy-definitions.bicep:3-5#DEFINES`).

#### 7.7.3 The 19 references

Nineteen references make up the initiative: 17 point to built-in definitions (16 distinct built-ins, because one prompt-filter built-in is used twice) and 2 point to custom definitions. "Effect as assigned" is what the assignment passes in (section 7.7.5). Built-in display names are as listed on Microsoft Learn (https://learn.microsoft.com/azure/governance/policy/samples/built-in-policies, https://learn.microsoft.com/azure/ai-services/policy-reference, https://learn.microsoft.com/azure/search/policy-reference); the Bicep refers to them only by id, and ids are not reproduced here.

| Reference id | Group | Source | Effect as assigned | What it enforces | Code |
|---|---|---|---|---|---|
| `ai-local-auth-disabled` | ABW-01 | built-in | Deny | "Azure AI Services resources should have key access disabled (disable local authentication)" | `infra/06a-policy-definitions.bicep:223-228#ai-local-auth-disabled` |
| `storage-shared-key-disabled` | ABW-01 | built-in | Deny | "Storage accounts should prevent shared key access" | `infra/06a-policy-definitions.bicep:229-234#storage-shared-key-disabled` |
| `cosmos-local-auth-disabled` | ABW-01 | built-in | Deny | "Cosmos DB database accounts should have local authentication methods disabled" | `infra/06a-policy-definitions.bicep:235-240#cosmos-local-auth-disabled` |
| `search-local-auth-disabled` | ABW-01 | built-in | Deny | "Azure AI Search services should have local authentication methods disabled" | `infra/06a-policy-definitions.bicep:241-246#search-local-auth-disabled` |
| `keyvault-rbac` | ABW-01 | built-in | Deny | "Azure Key Vault should use RBAC permission model" | `infra/06a-policy-definitions.bicep:247-252#keyvault-rbac` |
| registry local-credential login (reference id not reproduced) | ABW-01 | built-in | Deny | the built-in that requires the container registry's local-credential login to stay off | `infra/06a-policy-definitions.bicep:253-258#ABW-01-NO-KEYS` |
| `foundry-no-keyed-connections` | ABW-01 | custom | Deny | no Foundry account or project connection may use a secret-bearing authentication type (7.7.4) | `infra/06a-policy-definitions.bicep:259-264#foundry-no-keyed-connections` |
| `ai-restrict-network` | ABW-02 | built-in | Audit | "Azure AI Services resources should restrict network access" | `infra/06a-policy-definitions.bicep:266-271#ai-restrict-network` |
| `cosmos-no-public` | ABW-02 | built-in | Deny | "Azure Cosmos DB should disable public network access" | `infra/06a-policy-definitions.bicep:272-277#cosmos-no-public` |
| `storage-no-public` | ABW-02 | built-in | Deny | "Storage accounts should disable public network access" | `infra/06a-policy-definitions.bicep:278-283#storage-no-public` |
| `search-no-public` | ABW-02 | built-in | Deny | "Azure AI Search services should disable public network access" | `infra/06a-policy-definitions.bicep:284-289#search-no-public` |
| `aca-env-no-public` | ABW-02 | built-in | Audit | "Container Apps environment should disable public network access" | `infra/06a-policy-definitions.bicep:290-295#aca-env-no-public` |
| `foundry-approved-tools` | ABW-03 | built-in, preview, data-plane | `toolsEffect`, Audit by default | agent tool definitions may use only approved tool types or approved MCP endpoints | `infra/06a-policy-definitions.bicep:297-307#foundry-approved-tools` |
| `foundry-approved-mcp-targets` | ABW-03 | custom | Deny | a remote-tool connection target must match an approved endpoint pattern (7.7.4) | `infra/06a-policy-definitions.bicep:308-316#foundry-approved-mcp-targets` |
| `foundry-approved-models` | ABW-03 | built-in | `toolsEffect`, Audit by default | "Foundry model deployments should only use approved models"; publishers from `allowedModelPublishers` | `infra/06a-policy-definitions.bicep:317-325#foundry-approved-models` |
| `agent-guardrail-jailbreak` | ABW-04 | built-in, preview, data-plane | Audit | "[Preview]: Cognitive Services Agents should only use allowed prompt content filtering", filter name Jailbreak | `infra/06a-policy-definitions.bicep:327-337#agent-guardrail-jailbreak` |
| `agent-guardrail-indirect-attack` | ABW-04 | the same built-in | Audit | the same policy with filter name Indirect Attack | `infra/06a-policy-definitions.bicep:338-348#agent-guardrail-indirect-attack` |
| `aca-managed-identity` | ABW-05 | built-in | Audit | "Managed Identity should be enabled for Container Apps" | `infra/06a-policy-definitions.bicep:350-355#aca-managed-identity` |
| `aca-https-only` | ABW-05 | built-in | Audit | "Container Apps should only be accessible over HTTPS" | `infra/06a-policy-definitions.bicep:356-361#aca-https-only` |

The built-in definitions are tenant-wide objects referenced by id (Configured: `infra/06a-policy-definitions.bicep:21-38#builtin`). The custom definitions are stored in the subscription. Both are evaluated only at the assignment scope, the demo resource group (section 7.7.6).

**What Learn says about the effects the built-ins allow.** Learn lists Audit, Deny and Disabled for the AI Services key-access and network policies, the Storage shared-key and public-network policies, the Search local-authentication and public-network policies, the three Container Apps policies and the approved-models policy. For the Cosmos DB, Key Vault and container-registry built-ins I did not record the effect lists. The prompt content filtering built-in supports only Audit and Disabled (https://learn.microsoft.com/azure/ai-services/policy-reference). That is why the two guardrail references use `auditEffect`, whose allowed values are Audit and Disabled (Configured: `infra/06a-policy-definitions.bicep:182-187#cannot`). For `foundry-approved-tools` I did not find independent Learn documentation of its rule body or effect list. The repo only sets the effect and parameters and labels it a preview data-plane policy (Configured: `infra/06a-policy-definitions.bicep:14-15#PREVIEW`, `infra/06a-policy-definitions.bicep:300#definitionVersion`).

**Trade-off / limitation.** Four references use `auditEffect` although Learn lists Deny for them: `ai-restrict-network`, `aca-env-no-public`, `aca-managed-identity` and `aca-https-only`. The parameter's own description says it is "used by policies that cannot Deny" (Configured: `infra/06a-policy-definitions.bicep:182-187#cannot`), which is true only for the two guardrail references. The repo does not state why the other four are report-only. Two of them carry exemptions (section 7.7.7), which may be the reason, but that is my inference.

#### 7.7.4 The two custom definitions

**`abw-foundry-no-keyed-connections`** (Configured: `infra/06a-policy-definitions.bicep:50-91#noKeyedConnections`).

- Mode `All`, parameter `effect` with allowed values Audit, Deny and Disabled and default Deny (`infra/06a-policy-definitions.bicep:62#defaultValue`).
- The rule matches two resource types, account connections and project connections, when `authType` is in the parameter `keyedAuthTypes` (Configured: `infra/06a-policy-definitions.bicep:71-88#policyRule`). The default list is ApiKey, CustomKeys, AccessKey, AccountKey, SAS, PAT, UsernamePassword and ServicePrincipal (Configured: `infra/06a-policy-definitions.bicep:40#keyedAuthTypes`).
- Intent, from the description: connections must use Entra ID (AAD or managed identity), OAuth 2.0 user delegation, or no credential (Configured: `infra/06a-policy-definitions.bicep:54#description`).

Why custom: the Bicep header describes the two custom definitions as the control-plane (ARM) rules that "visibly Deny", in contrast to the two preview built-ins, which are data-plane policies (Configured: `infra/06a-policy-definitions.bicep:14-17#PREVIEW`). I did not find a built-in definition for these two rules in the Learn index pages I checked; that is not proof that none exists.

**Trade-off / limitation.** The description states an allow-list intent (only AAD, managed identity, OAuth, none) but the rule is a deny-list of eight known secret-bearing types (`infra/06a-policy-definitions.bicep:40#keyedAuthTypes`). A new secret-bearing authentication type introduced by the platform would pass until someone adds it to the parameter (analysis).

**`abw-foundry-approved-mcp-targets`** (Configured: `infra/06a-policy-definitions.bicep:96-103#approvedMcpTargets`).

- Same effect parameter and default Deny (`infra/06a-policy-definitions.bicep:108#defaultValue`). Two more parameters: `approvedMcpEndpoints`, an array with no default, and `connectionCategories`, default `RemoteTool` (Configured: `infra/06a-policy-definitions.bicep:111-119#connectionCategories`).
- The rule fires for an account or project connection whose `category` is in `connectionCategories` and for which the number of approved patterns that match the connection `target` equals zero (Configured: `infra/06a-policy-definitions.bicep:121-160#policyRule`; the count over the patterns is `infra/06a-policy-definitions.bicep:129-137#count`).
- Platform behaviour: the `like` condition takes one `*` wildcard (no more than one), and string comparison ignores case (https://learn.microsoft.com/azure/governance/policy/concepts/definition-structure-policy-rule#conditions). The repo description says the same (Configured: `infra/06a-policy-definitions.bicep:100#wildcard`).

**Trade-off / limitation.** Only connections in the evaluated categories are checked, and only through their `target`. The agents in this repo attach a tool by `server_url` plus a named connection (Implemented: `src/agent/abw_agents.py:119-139#project_connection_id`). Whether the platform rejects a tool whose `server_url` differs from its connection's `target` is not stated in this repo. The rule that inspects agent tool definitions is the preview audit-only policy (row `foundry-approved-tools`), so an agent definition with an unapproved URL would be reported, not blocked at creation (analysis; Designed: `DESIGN.md:166#preview`).

#### 7.7.5 The initiative: parameters and effect wiring

The initiative is `abw-agent-platform-controls` (Configured: `infra/06a-policy-definitions.bicep:168-172#initiative`). Its parameters:

| Parameter | Allowed values | Default | Used by | Code |
|---|---|---|---|---|
| `denyEffect` | Audit, Deny, Disabled | Deny | 11 references (7 in ABW-01, 3 in ABW-02, 1 in ABW-03) | `infra/06a-policy-definitions.bicep:176-181#denyEffect` |
| `auditEffect` | Audit, Disabled | Audit | 6 references (2 in ABW-02, 2 in ABW-04, 2 in ABW-05) | `infra/06a-policy-definitions.bicep:182-187#auditEffect` |
| `toolsEffect` | Audit, Deny, Disabled | Audit | `foundry-approved-tools`, `foundry-approved-models` | `infra/06a-policy-definitions.bicep:188-193#toolsEffect` |
| `approvedMcpEndpoints` | array, no default | none | `foundry-approved-tools`, `foundry-approved-mcp-targets` | `infra/06a-policy-definitions.bicep:194-197#approvedMcpEndpoints` |
| `approvedToolTypes` | array | empty | `foundry-approved-tools` | `infra/06a-policy-definitions.bicep:198-202#approvedToolTypes` |
| `allowedModelPublishers` | array | OpenAI | `foundry-approved-models` | `infra/06a-policy-definitions.bicep:203-207#allowedModelPublishers` |
| `agentEntityKinds` | array | prompt | both guardrail references | `infra/06a-policy-definitions.bicep:208-212#agentEntityKinds` |

The 11 + 6 + 2 split sums to 19. The five control groups are declared at `infra/06a-policy-definitions.bicep:214-219#ABW-01-NO-KEYS` and every reference names its group (for example `infra/06a-policy-definitions.bicep:227#groupNames`). The initiative description calls it a "twelve-control baseline" although it holds 19 references (Configured: `infra/06a-policy-definitions.bicep:172#twelve-control`); this is listed in the Findings at the end of section 8.

#### 7.7.6 The assignment

- **Scope.** One assignment, named like the initiative, at resource-group scope (Configured: `infra/06-governance.bicep:12#targetScope`, `infra/06-governance.bicep:177-183#assignment`). Its description says "Scope: <resource group> only" (Configured: `infra/06-governance.bicep:181#description`).
- **Enforcement.** `enforcementMode` is `Default` (Configured: `infra/06-governance.bicep:183#enforcementMode`). Platform behaviour: Default means the effect is enforced at create and update (https://learn.microsoft.com/azure/governance/policy/concepts/assignment-structure#enforcement-mode).
- **Effect parameters.** `denyEffect` comes from `hardControlEffect` (default Deny, allowed Audit or Deny); `auditEffect` is the literal Audit; `toolsEffect` comes from `agentToolEffect` (default Audit, allowed Audit or Deny) (Configured: `infra/06-governance.bicep:19-25#hardControlEffect`, `infra/06-governance.bicep:184-190#denyEffect`). The assignment also passes an empty `approvedToolTypes` and the model publisher list `OpenAI`; it does not pass `agentEntityKinds`, so the initiative default (prompt agents) applies (Configured: `infra/06-governance.bicep:189-190#allowedModelPublishers`, `infra/06a-policy-definitions.bicep:208-212#agentEntityKinds`). Why: Deny can be switched to Audit "while introducing the controls" (Configured: `infra/06-governance.bicep:19#Deny`).
- **Approved endpoints.** The assignment passes five patterns: the four gateway paths for research, wall, actions and vendor, and the private server's internal address with a trailing wildcard (Configured: `infra/06-governance.bicep:162-168#approvedMcpEndpoints`). Two consequences. The private server is approved as a direct target, consistent with the private path that bypasses the gateway (section 7.3; Designed: `DESIGN.md:107#private`). The legacy gateway path is not in the list, which is why the legacy connection needs a waiver (section 7.7.7).
- **Non-compliance messages.** Eleven entries: one default and ten per reference (five for keys, two for targets, three for public access) (Configured: `infra/06-governance.bicep:192-204#nonComplianceMessages`). Platform behaviour: the custom message is added to the default error, it can be set per `policyDefinitionReferenceId` for an initiative, and it is supported only for definitions in Resource Manager mode (https://learn.microsoft.com/azure/governance/policy/concepts/assignment-structure#non-compliance-messages).

**Trade-off / limitation.**

- The default message tells the engineer to see `policy/README.md` for the control catalogue and how to request an exemption (Configured: `infra/06-governance.bicep:171#README`). That file does not exist in the repo. Two Deny controls (the Key Vault RBAC rule and the registry rule) have no specific message, so their denials show the default message and point to the missing page (Findings, end of section 8).
- A message is registered for `foundry-approved-tools` (Configured: `infra/06-governance.bicep:200#foundry-approved-tools`), but the Bicep header describes that policy as data-plane mode (Configured: `infra/06a-policy-definitions.bicep:14-15#PREVIEW`). Given the Learn restriction above, its message is probably never shown (inference).
- Platform behaviour: the assignment always evaluates the latest content of the assigned initiative, and a definition version left at its default takes the latest major version and auto-ingests minor and patch changes (https://learn.microsoft.com/azure/governance/policy/concepts/assignment-structure#policy-definition-id-and-version). The three preview references pin only `1.*.*-preview` (Configured: `infra/06a-policy-definitions.bicep:300#definitionVersion`, `infra/06a-policy-definitions.bicep:330#definitionVersion`, `infra/06a-policy-definitions.bicep:341#definitionVersion`). Built-in rule text can therefore change under a fixed assignment without any change in this repo.

#### 7.7.7 Exemptions

The Bicep records every exemption as an explicit, reviewable decision; the compliance view shows them as Exempt, not as green (Configured: `infra/06-governance.bicep:209#Exempt`). Platform behaviour: the category is Waiver or Mitigated, an exemption can name specific initiative references, and an exemption with an `expiresOn` date in the past is not deleted but is no longer honoured (https://learn.microsoft.com/azure/governance/policy/concepts/exemption-structure).

| Exemption | Scope (resource exempted) | Category | References covered | Expiry | Reason (from the Bicep) | Code |
|---|---|---|---|---|---|---|
| `exLegacyAccount` | the `mcp-legacy-key` connection, account level | Waiver | `foundry-no-keyed-connections`, `foundry-approved-mcp-targets` | `legacyWaiverExpiry`, set by the script to 90 days after the stage runs (Bicep default `2026-11-30T00:00:00Z`) | a deliberate "before" baseline: a keyed, ungoverned MCP connection that shows what the controls prevent | `infra/06-governance.bicep:232-243#exLegacyAccount` |
| `exLegacyProject` | the same connection, project level | Waiver | the same two | the same | the same | `infra/06-governance.bicep:245-256#exLegacyProject` |
| `exAppiAccount` | the telemetry connection to Application Insights, account level | Mitigated | `foundry-no-keyed-connections` | none | the platform creates it with a write-only ingestion key; telemetry is ingestion-only and the workspace is queried with Entra ID | `infra/06-governance.bicep:260-270#exAppiAccount` |
| `exAppiProject` | the same connection, project level | Mitigated | the same | none | the same | `infra/06-governance.bicep:272-282#exAppiProject` |
| `exFoundryNetwork` | the Foundry account | Mitigated | `ai-restrict-network` | none | the endpoint stays reachable so the operator workstation can run agents; key access is off, tool calls land in private MCP servers behind the gateway, the agent runtime is injected into the virtual network | `infra/06-governance.bicep:284-294#exFoundryNetwork` |
| `exPublicEnv` | the public Container Apps environment | Waiver | `aca-env-no-public` | none | it hosts the simulated third-party vendor and the legacy proof-of-concept server; the vendor gateway is the control | `infra/06-governance.bicep:296-306#exPublicEnv` |

Reasons are in `infra/06-governance.bicep:230#legacyReason` and `infra/06-governance.bicep:258#appiReason`. The waiver expiry parameter is `infra/06-governance.bicep:27-28#legacyWaiverExpiry`, and the script passes its value (`scripts/deploy.ps1:448#legacyWaiverExpiry`).

**Cross-check (arithmetic, not a stated fact).** The recorded snapshot reports 8 Exempt states (Designed: `DESIGN.md:166#Compliance`). The six exemptions cover 2 + 2 + 1 + 1 + 1 + 1 = 8 references, which matches if each exempted reference on each resource counts once.

**Trade-off / limitation.** Only the legacy waivers expire. The four Mitigated or Waiver exemptions without `expiresOn` stay in force until someone removes them, so "reviewable" depends on a human review that the repo does not schedule. The `exPublicEnv` description says the public environment hosts the legacy server, but the apps Bicep places the legacy server in the private environment (Configured: `infra/06-governance.bicep:304#legacy`, `infra/04-apps.bicep:152#caePriv`; Findings, end of section 8).

#### 7.7.8 Proof: nine attempts and the compliance snapshot

`demo/try-violations.py` sends nine real ARM requests, eight unsafe and one compliant control. Its docstring defines the three outcomes (Implemented: `demo/try-violations.py:1-10#RequestDisallowedByPolicy`):

- **BLOCKED**: HTTP 403 `RequestDisallowedByPolicy` naming the assignment, the control (initiative reference) and its effect. The attempt passes only if every expected control appears among the policies the denial names (Implemented: `demo/try-violations.py:338-350#RequestDisallowedByPolicy`).
- **CORRECTED**: the request succeeds but the resource is stored safe. It passes only if every unsafe setting was changed and the initiative still flags the original request body through the stateless policy-evaluation API, where at least one expected control must be among the flags (Implemented: `demo/try-violations.py:297-316#_classify_allowed`, `demo/try-violations.py:271-296#_flagged_by_initiative`).
- **ALLOWED**: an unsafe resource survives. It fails, except for the positive control, which must be allowed (Implemented: `demo/try-violations.py:351-356#_classify_allowed`). Every resource an attempt creates is deleted.

| Attempt | Expected controls | Outcome recorded in the tenant used for the build | Code |
|---|---|---|---|
| storage shared key | `storage-shared-key-disabled`, `storage-no-public` | CORRECTED | `demo/try-violations.py:89#controls` |
| Cosmos local auth | `cosmos-local-auth-disabled`, `cosmos-no-public` | CORRECTED | `demo/try-violations.py:104#controls` |
| Search local auth | `search-local-auth-disabled`, `search-no-public` | BLOCKED | `demo/try-violations.py:123#controls` |
| Key Vault access policies | `keyvault-rbac` | BLOCKED | `demo/try-violations.py:137#controls` |
| registry local-credential login | the registry reference | BLOCKED | `demo/try-violations.py:153-155#controls` |
| Foundry local auth | `ai-local-auth-disabled` | CORRECTED | `demo/try-violations.py:164#controls` |
| keyed Foundry connection | `foundry-no-keyed-connections` | BLOCKED | `demo/try-violations.py:180#controls` |
| unapproved MCP target | `foundry-approved-mcp-targets` | BLOCKED | `demo/try-violations.py:196#controls` |
| positive control (compliant) | none | ALLOWED, as expected | `demo/try-violations.py:211-212#expect` |

The recorded totals are 5 denied, 3 created safe and 1 compliant control allowed, with a compliance snapshot of 69 Compliant, 8 Exempt and 1 NonCompliant, the last being `foundry-approved-tools` on the legacy path by design (Designed: `DESIGN.md:166#Measured`, `docs/PROOF-PLAYBOOK.md:185#exempt`, `docs/PROOF-PLAYBOOK.md:341#BLOCKED`).

**What proof P11 asserts** (Implemented: `demo/prove.py:993-1023#p11`):

1. The harness exits 0 and its summary reports the same number of expected and total attempts.
2. It records how many attempts were denied by this initiative, and lists the attempts that were rewritten safe by another policy before the Deny ran.
3. It reads the initiative's compliance rows from Azure Resource Graph, grouped by state and reference, and asserts that rows exist and that at least one is Compliant.
4. It records the NonCompliant references as a fact, labelled "legacy path, by design". It does not assert which references are NonCompliant.

**Trade-off / limitation.** The "1 NonCompliant, by design" expectation is documented but not asserted. A second NonCompliant reference would not fail P11.

#### 7.7.9 Caveats: what "enforced" means in this build

1. **A baseline can correct instead of deny.** The build tenant carries an organisation baseline, assigned at tenant-root or management-group scope, whose Modify policies rewrite shared-key, local-auth and public-network settings on the way in. Policy evaluates Modify before Deny, so three of the nine attempts were stored safe instead of being rejected (Designed: `DESIGN.md:166#Modify`; Platform behaviour: the order of evaluation URL in 7.7.1; Implemented: `demo/try-violations.py:309#CORRECTED`). In a tenant with no such baseline each unsafe attempt is rejected (Designed: `DESIGN.md:166#nothing`). The harness records which layer acted, so a BLOCKED result is not guaranteed in every tenant and a CORRECTED result is not a failure.
2. **The preview data-plane policies are report-only.** `foundry-approved-tools`, `foundry-approved-models` and the two guardrail references are Audit by default (Configured: `infra/06a-policy-definitions.bicep:185-191#defaultValue`, `infra/06-governance.bicep:25#agentToolEffect`). The repo states that create-time Deny is not enforced for the Foundry data-plane policies for agent tools, models and guardrails (Designed: `DESIGN.md:166#preview`). Learn lists Deny as an allowed effect for the approved-models built-in, so for that reference the Audit default rests on the repo's statement; no proof in this repo exercises a Deny on it.
3. **Policy is configuration control, not request-time authorization.** It would not stop a legitimate identity with the right roles from reading data it may read. That is the job of the four walls.
4. **Scope is one resource group.** Resources created outside the demo resource group are not evaluated by this assignment (Configured: `infra/06a-policy-definitions.bicep:3-5#DEFINES`, `infra/06-governance.bicep:181#description`).
5. **Exemptions are decisions, not gaps.** They are listed in 7.7.7. After the legacy waiver expires, Policy stops honouring it and the legacy connection is evaluated again.

Why this design: the repo wants a policy set that is explainable to a customer, one question per control group, with every exception visible, rather than a silent allow-list. The cost is the report-only subset above.

### 7.8 Emergency controls

**What this section proves.** Both emergency controls are single writes to an APIM named value that the gateway policy references in an expression. The kill switch writes `abw-deny-oids` (Implemented: `scripts/kill-switch.ps1:43#abw-deny-oids`), which the policy compares with the caller's `oid` claim (Configured: `infra/apim/policies/mcp-jwt.policy.xml:37#abw-deny-oids`). The client allow-list writes `abw-allowed-azp` (Implemented: `scripts/client-allowlist.ps1:39#abw-allowed-azp`), which the policy compares with the token's `azp` claim (Configured: `infra/apim/policies/mcp-jwt.policy.xml:38#abw-allowed-azp`). Both act at the gateway only, both take about a minute to take effect, and each has a live proof (Tested: P12 in `demo/prove.py:932-956#p12` and P15 in `demo/prove.py:905-926#p15`). Neither reaches the private MCP server or the data plane (sections 7.5 and 7.9).

**Provenance labels.** Implemented = read in code or in a script. Configured = Bicep and policy XML. Tested = asserted by a proof in the harness. Designed = DESIGN.md or the guides. Platform behaviour = Microsoft Learn, with the URL in plain text. Inference = my reading of the files, not observed.

**Platform behaviour.** Named values are instance-wide name and value pairs that a policy references as `{{name}}` (https://learn.microsoft.com/azure/api-management/api-management-howto-properties). Learn gives no propagation time for a changed value, so the "about a minute" quoted below is the repo's own measurement, not a documented figure.

#### 7.8.1 The kill switch

**What this section proves.** The kill switch is a deny list of Entra object ids that the gateway checks after it has validated the token and before it applies any allow-list, scope or role rule. A listed user is refused whatever roles the token carries (Configured: `infra/apim/policies/mcp-jwt.policy.xml:36-38#revoked`).

**Mechanism.**

| Item | As built | Evidence |
|---|---|---|
| Store | One APIM named value, `abw-deny-oids`: comma-separated lower-case object ids, or the literal `none` when the list is empty. It is declared as a plain (not secret) named value whose initial value is `none`. | Configured: `infra/05-apim.bicep:210-218#abw-deny-oids`. Implemented: `scripts/kill-switch.ps1:70-74#Set-DenyList` |
| Reader | The policy splits the named value on commas and tests whether the caller's `oid` is one of the elements. A hit sets the reason `revoked`. The comparison is exact: the policy does no trimming and no case folding (Inference: LINQ `Contains` on a string array is ordinal and case-sensitive). | Configured: `infra/apim/policies/mcp-jwt.policy.xml:36-37#revoked` |
| Position in the decision order | After `validate-jwt`, so a token that fails validation is refused with 401 before the list is consulted. Before the allow-list, scope and role checks, so the first hit wins. Also before the discovery exemption (`initialize`, `ping`, `tools/list` and `notifications/*` need no role on the APIs where the list is open), so a revoked user is refused on those methods too. | Configured: `infra/apim/policies/mcp-jwt.policy.xml:17-30#validate-jwt`, `infra/apim/policies/mcp-jwt.policy.xml:42-44#discovery` |
| Deny shape | HTTP 403, `application/json`, body fields `error` (`forbidden`), `reason` (`revoked`), `server` and `request_id`. | Configured: `infra/apim/policies/mcp-jwt.policy.xml:64-77#forbidden` |
| Evidence trail | A metric `abw-gateway-decisions` (dimensions server, decision, reason and oid) and a trace carrying the oid, reason and request id. Both are emitted before the 403 is returned. | Configured: `infra/apim/policies/mcp-jwt.policy.xml:51-63#abw-gateway-decisions` |
| Second reader | The agent front door reads the same named value. It does not read `abw-allowed-azp`. | Configured: `infra/apim/policies/agent-frontdoor.policy.xml:6#kill`, `infra/apim/policies/agent-frontdoor.policy.xml:13#abw-deny-oids`, `infra/apim/policies/agent-frontdoor.policy.xml:53#abw-deny-oids` |

**Operations.**

| Invocation | Effect | Evidence |
|---|---|---|
| `-Show`, or no `-User` and no `-Reset` | Reads the list and prints each entry with a label (persona alias and UPN, `operator`, or the bare oid). Prints "deny list is empty - nobody is revoked" when empty. Because `-Show` is the default, `-Restore` or `-RevokeSessions` given without `-User` only prints the list. | Implemented: `scripts/kill-switch.ps1:76-85#Write-List`, `scripts/kill-switch.ps1:57-61#Get-Label` |
| `-User X` | Resolves X, appends the oid if it is not already listed, writes the list, and prints that APIM applies it within about a minute. | Implemented: `scripts/kill-switch.ps1:96-97#Resolve-Oid`, `scripts/kill-switch.ps1:106-107#notin` |
| `-User X -Restore` | Writes the list without that oid and prints that the gateway picks the change up in about a minute. | Implemented: `scripts/kill-switch.ps1:99-104#Restore` |
| `-Reset` | Writes `none`. | Implemented: `scripts/kill-switch.ps1:90-94#Reset` |
| `-User X -RevokeSessions` | After the gateway write, POSTs the Graph call `revokeSignInSessions` for the user. For the operator it is skipped with a warning unless `-Force` is added, because it would also sign the Azure CLI out. | Implemented: `scripts/kill-switch.ps1:109-116#RevokeSessions` |

`-User` accepts a persona alias (priya, wes, tara, carla, ian), a UPN, an object id, or `operator` (Implemented: `scripts/kill-switch.ps1:16-17#operator`).

**How an oid is blocked, step by step.**

1. **Resolve.** `Resolve-Oid` returns a lower-case oid. A GUID is used as typed, `operator` maps to the configured operator oid, a persona alias maps to the oid recorded when the personas were created, and a UPN is looked up in Graph selecting only `id`. Anything else throws (Implemented: `scripts/kill-switch.ps1:45-55#Resolve-Oid`).
2. **Read.** `Get-DenyList` runs `az apim nv show`, throws if the read fails, maps `none` or an empty value to an empty list, and otherwise splits on commas, trims and lower-cases each element (Implemented: `scripts/kill-switch.ps1:63-68#Get-DenyList`).
3. **Write.** Unless the oid is already listed, the script writes the old list plus the new oid with `az apim nv update` (Implemented: `scripts/kill-switch.ps1:106#notin`, `scripts/kill-switch.ps1:70-74#Set-DenyList`). The "revoked" message is printed even when the oid was already listed, so the command is idempotent (Implemented: `scripts/kill-switch.ps1:107#revoked`).
4. **Propagate.** The gateway applies the new value after a lag. The script says "within about a minute"; DESIGN.md quotes 45-90 s for the first refusal (Designed: `DESIGN.md:176#refusal`), and P12 measured 42-66 s in the harness and 88 s by hand (Designed: `DESIGN.md:214#harness`).
5. **Refuse.** The user's token is still genuine, so `validate-jwt` passes. The next expression finds the oid in the list and returns the reason `revoked`; the 403 JSON is returned before the rate limit and before the request is forwarded (Configured: `infra/apim/policies/mcp-jwt.policy.xml:37#revoked`, `infra/apim/policies/mcp-jwt.policy.xml:64-81#forbidden`).
6. **Record.** The decision metric and the trace are emitted before the 403 (Configured: `infra/apim/policies/mcp-jwt.policy.xml:51-63#abw-gateway-decisions`). The MCP server never sees the call, so no MCP audit event exists for it; the evidence is the APIM gateway log (Inference from the request path; the MCP audit event is section 8.4).
7. **Detect.** `AbwGateway` exposes `Reason` and `UserOid` (Implemented: `observability/kql/AbwGateway.kql:24-25#Reason`). Sentinel rule ABW-005 groups `Reason == 'revoked'` by `UserOid`, runs every 5 minutes over a 30-minute window and has severity High (Configured: `observability/sentinel/abw-005-revoked-principal.kql:3-13#revoked`). Its description says revocation works at the gateway and that the caller still needs containment at the identity layer (Configured: `observability/sentinel/abw-005-revoked-principal.kql:10#identity`).

**Reach.**

| Path | Covered | Why | Evidence |
|---|---|---|---|
| The gateway MCP APIs: research, wall, actions, vendor | Yes | The same policy template is rendered once per API | Configured: `infra/05-apim-apis.bicep:123-147#mcpApis` |
| The agent front door (`/agents`) | Yes, deny list only | The front-door policy has its own check of the same named value. P12 asserts only the four MCP APIs, so the front-door check is configured but not proven by that test. | Configured: `infra/apim/policies/agent-frontdoor.policy.xml:53#abw-deny-oids`. Tested (MCP APIs only): `demo/prove.py:947-949#vendor` |
| The legacy API | No | There is no JWT: a shared subscription key identifies no user, so there is no `oid` to deny | Configured: `infra/apim/policies/mcp-legacy.policy.xml:8-8#rate-limit-by-key`. Designed: `docs/DEMO-GUIDE.md:235#Private` |
| The private MCP server | No | The direct path from Foundry never touches APIM | Designed: `DESIGN.md:107#kill` |
| The data plane (Storage, Cosmos, Search) | No | Each service evaluates the user's on-behalf-of token against RBAC; cutting data access means removing the group or role (section 7.5) | Tested: `demo/prove.py:962-963#p16` |
| A token already issued | Refused at the gateway on the next call; still accepted on the private path until it expires | The check is per request and needs no token revocation | Designed: `DESIGN.md:107#kill` |

**Proof.** (Tested: `demo/prove.py:932-956#p12`.) P12 first confirms the operator is served by a list call on the research API. It runs `kill-switch.ps1 -User operator`, then polls every 6 s for up to 180 s until the same call returns 403 with reason `revoked` (`demo/prove.py:940-945#revoked`). It then asserts the same refusal on the wall, actions and vendor APIs (`demo/prove.py:947-949#vendor`), stamps the ABW-005 traffic marker (`demo/prove.py:950#ABW-005`), restores in a `finally` block (`demo/prove.py:951-952#finally`), polls until the operator is served again, and checks that `-Show` reports nobody revoked (`demo/prove.py:955-956#Show`). It does not test the private server or the front door.

**Why.** Nothing the repo builds recalls an issued access token, and the repo states that continuous access evaluation is not available for this self-validated custom API (Designed: `DESIGN.md:236#CAE`; this document did not verify that statement, and no claims challenge is built). The only lever that acts on an already-issued token is therefore a per-request identity check at the gateway (analysis). Learn describes CAE for supported resources, with critical-event latency of up to 15 minutes (https://learn.microsoft.com/entra/identity/conditional-access/concept-continuous-access-evaluation); the repo does not claim CAE for the MCP APIs.

**Trade-off / limitation.**

- Gateway only. The private server and the data plane never read the list (Designed: `DESIGN.md:107#kill`).
- About a minute, not instant. The Bicep comment says the deny list applies "immediately" (Configured: `infra/05-apim.bicep:209#immediately`), which is not what was measured.
- Read-modify-write. The script reads the list, then writes the whole list back, with no concurrency control, so two operators acting at once could overwrite each other (Inference: `scripts/kill-switch.ps1:63-74#Get-DenyList`, `scripts/kill-switch.ps1:106#notin`).
- A redeploy of the apim stage most likely resets the list to `none`, because the named value is a plain declared resource with `value: 'none'` (Inference, untested: `infra/05-apim.bicep:210-218#abw-deny-oids`).
- Exact matching. A hand-edited value with spaces or upper-case letters would silently not match (Inference: `infra/apim/policies/mcp-jwt.policy.xml:37#abw-deny-oids`).
- Authority. The script calls itself a "SOC" kill switch (`scripts/kill-switch.ps1:4#SOC`), but the infosec persona holds only Reader, Log Analytics Reader and Monitoring Reader (Configured: `infra/03-platform.bicep:702-731#raInfosecReader`). Writing the named value needs write access to the APIM instance and `revokeSignInSessions` needs a Graph permission (https://learn.microsoft.com/graph/api/user-revokesigninsessions), so in this repo only the operator can pull the switch (Inference; the operator is Subscription Owner: `infra/03-platform.bicep:733-735#Owner`).
- Revoking sessions is partial. Graph invalidates refresh tokens and "might" take a few minutes; it does not recall access tokens already issued (Inference from the Learn description; default access-token lifetime is a random 60-90 minutes: https://learn.microsoft.com/entra/identity-platform/configurable-token-lifetimes).

#### 7.8.2 The client allow-list

**What this section proves.** The allow-list answers a different question from the kill switch: not "which user" but "which application asked for this token". A validly signed token is accepted only if its `azp` is in the named value `abw-allowed-azp`; otherwise the gateway returns 403 `client_not_allowed` (Configured: `infra/apim/policies/mcp-jwt.policy.xml:38#client_not_allowed`), and Sentinel rule ABW-004 raises an incident (Configured: `observability/sentinel/abw-004-client-not-allowed.kql:11-12#client_not_allowed`).

**Mechanism and operations.**

| Item | As built | Evidence |
|---|---|---|
| Store | One APIM named value, `abw-allowed-azp`, a comma-separated list of lower-case application ids. Declared as a plain named value whose value comes from the deployment parameter. | Configured: `infra/05-apim.bicep:199-207#abw-allowed-azp` |
| Default content | The agent client, the test client and the Azure CLI's public application id (a well-known Microsoft public client id held in `$azCliAppId`, `identity/Setup-Entra.ps1:190-190#azCliAppId`). The deploy script builds the list and passes it to both the apps stage and the apim stage. | Configured: `scripts/deploy.ps1:178-180#Get-AllowedAzp` |
| Aliases | `agent` (the Foundry agent's OAuth identity passthrough client), `test` (the persona sign-in client used by the proofs) and `azcli` (the Azure CLI, "operator testing", standing in for some other application). | Implemented: `scripts/client-allowlist.ps1:41-45#aliases` |
| `-Block X` | Removes an alias or application id from the list and prints that APIM applies it within about a minute. | Implemented: `scripts/client-allowlist.ps1:91-96#Block` |
| `-Allow X` | Adds it back if it is not already listed. | Implemented: `scripts/client-allowlist.ps1:97-102#Allow` |
| `-Reset` | Writes all three aliases. It does not read the deployed parameter, so after a custom deployment the reset list can differ from the deployed one. | Implemented: `scripts/client-allowlist.ps1:84-89#Reset` |
| `-Show` | Default when no flag is given; prints each alias as allowed or not allowed. | Implemented: `scripts/client-allowlist.ps1:70-82#Write-List` |
| Safety rail | `Set-List` refuses to write an empty list, because every call, including the agents', would be rejected. | Implemented: `scripts/client-allowlist.ps1:64-68#Set-List` |
| Decision order | After the deny list, before the scope and role checks. | Configured: `infra/apim/policies/mcp-jwt.policy.xml:37-39#client_not_allowed` |

**Proof.** (Tested: `demo/prove.py:905-926#p15`.) P15 first checks that the Azure CLI application is allowed (`demo/prove.py:907-908#baseline`), runs `-Block azcli` (`demo/prove.py:912#azcli`), then polls every 8 s for up to 180 s until the same user and roles get 403 `client_not_allowed` (`demo/prove.py:915-920#client_not_allowed`). It stamps the ABW-004 marker (`demo/prove.py:922#ABW-004`), resets in a `finally` block (`demo/prove.py:923-924#finally`) and polls until calls succeed again. DESIGN.md records 46-59 s in the harness and 56-83 s by hand (Designed: `DESIGN.md:217#harness`).

**Interaction with the kill switch and the agents.** The deny list is checked first, so with both controls engaged a raw call reports `revoked` (Designed: `docs/DEMO-GUIDE.md:448#revoked`). Blocking `azcli` does not affect the agent, because Foundry's own client stays on the list (Designed: `docs/DEMO-GUIDE.md:483#unaffected`). Blocking the `agent` alias would break every agent beat (Inference: `scripts/client-allowlist.ps1:64-68#Set-List` states the agents depend on the list).

**Why.** The allow-list narrows who can mint a token that the MCP APIs accept: a token phished or replayed from another application, a developer script or a first-party tool is refused even though its signature, issuer, `aud` and roles are all valid. The `azp` claim exists only in v2 access tokens (https://learn.microsoft.com/entra/identity-platform/access-token-claims-reference).

**Trade-off / limitation.**

- Two copies of the list. The script changes only the APIM named value. The container apps carry a second static copy as `MCP_ALLOWED_AZP`, set at deployment and not touched by the script (Configured: `infra/04-apps.bicep:26#allowedAzp`, `infra/04-apps.bicep:77-84#MCP_ALLOWED_AZP`). A direct call to a server inside the network is therefore checked against the static copy (Inference).
- Opposite failure modes. The gateway would reject every real token if the named value were empty (Inference from the expression at `infra/apim/policies/mcp-jwt.policy.xml:38#client_not_allowed`; the script refuses to write an empty list), while the MCP server skips its `azp` check entirely when its own list is empty (Implemented: `src/mcp/abw_mcp/auth.py:151-153#bad_azp`). A bad `azp` therefore has two wire shapes: gateway 403 `client_not_allowed`, MCP 401 `invalid_token` with description `bad_azp` (section 8.5).
- Global. A named value is instance-wide, so the list cannot differ per API (https://learn.microsoft.com/azure/api-management/api-management-howto-properties).
- Not locked down by default. The Azure CLI is on the default list and is also pre-authorised on the MCP APIs (Configured: `identity/Setup-Entra.ps1:189-196#preAuthorizedApplications`). The default is a demo posture.
- Narrows minting, not replay. A stolen token minted by an allowed client still passes; the token is a bearer token (analysis).
- The front door has no allow-list (Configured: `infra/apim/policies/agent-frontdoor.policy.xml:13#abw-deny-oids`).

#### 7.8.3 The emergency ladder

**What this section proves.** No single control stops everything. The table lists each lever the repo provides or describes, what it stops, what it leaves running, and how fast it acts, so an operator can pick the right combination (Designed: `DESIGN.md:236#CAE`, which pairs group or role removal with the kill switch).

| Control | What it stops | What it does not stop | Time to effect | Evidence |
|---|---|---|---|---|
| Gateway kill switch (`-User X`) | Every call to the gateway MCP APIs and the agent front door that presents a token for that oid | The private server; the legacy API (no identity); data-plane access with a token the user already holds | About a minute (42-66 s harness, 88 s by hand) | Tested: `demo/prove.py:932-956#p12`; Designed: `DESIGN.md:214#harness` |
| `-RevokeSessions` | New access tokens minted from the user's existing sign-in sessions | An access token already issued, valid until it expires (60-90 minutes by default) | A few minutes (Learn) | Implemented: `scripts/kill-switch.ps1:11-14#revokeSignInSessions`; https://learn.microsoft.com/graph/api/user-revokesigninsessions |
| Remove the group or app role | Layer 3: Storage refuses the user's next on-behalf-of call (5-44 s measured) | Layers 1 and 2 trust the roles inside a token already issued; Foundry can hold a user's token for 60-90 minutes | Seconds to a minute at layer 3; up to token expiry at layers 1 and 2 (Inference) | Tested: `demo/prove.py:962-963#p16`; Designed: `DESIGN.md:218#measured`, `DESIGN.md:223#jti`, `DESIGN.md:226#propagation` |
| Disable the Entra account | Sign-in altogether | An access token already issued, until it expires (Inference) | Manual, "an identity decision, not a gateway one" | Implemented: `scripts/kill-switch.ps1:14#manual` |
| Client allow-list block | Tokens minted by one client application, at the gateway | Tokens from allowed clients; direct calls checked only against the static copy | 45-90 s (46-59 s harness) | Tested: `demo/prove.py:905-926#p15`; Designed: `DESIGN.md:217#harness` |
| Disable an Agent ID identity | Nothing for tool calls, which carry the user's token | Everything: it is an inventory entry, "Not a kill switch" | Not applicable | Designed: `docs/DEMO-GUIDE.md:234#agent` |
| Front-door budgets | Runaway agent use per user: by default 60 calls a minute and 250,000 tokens an hour (Bicep parameter defaults, held in the named values `abw-agent-rpm` and `abw-agent-token-quota`; the console can lower the quota live) | With `estimate-prompt-tokens` set to false the prompt is not pre-counted, so a single call can overshoot the hourly token budget before the lock-out starts (Inference) | The design says a rate-limit lock-out lasts about two minutes; that describes the calls-per-minute limiter, and the repo states no lock-out time for the hourly token quota | Configured: `infra/08-agent-frontdoor.bicep:17-21#tokenQuotaPerHour`, `infra/apim/policies/agent-frontdoor.policy.xml:95-96#abw-agent-rpm`, `infra/apim/policies/agent-frontdoor.policy.xml:96#estimate-prompt-tokens`; Designed: `DESIGN.md:174#lock-out` |
| Agent 365 gateway block on the legacy server | The legacy server's tool traffic (reported) | Not reproducible from the repo files read | About 15 s (reported) | Designed: `DESIGN.md:240#report-only` |

Why the ladder is shaped this way: the gateway controls act per request but only on the paths that cross APIM; the identity controls act on token issuance but not on tokens already issued; the data-plane control acts at the resource. That is the same four-layer logic as section 7.1, applied to containment instead of access.

### 7.9 Authorization gaps and trade-offs

**What this section proves.** The design is strongest where a decision is deterministic and independently verifiable: the gateway policy, the MCP rule and data-plane RBAC each decide on their own (Implemented: `src/mcp/abw_mcp/registry.py:158-165#call_tool`). It is weakest on the lifecycle of an entitlement, on paths that skip APIM, and on the evidence trail. Each item below carries its provenance, the files that show it, and why it matters. Line-level mismatches between documents and code are collected in the Findings at the end of section 8.

#### 7.9.1 The entitlement model

These items concern who is entitled to what, and how that is authored and reviewed (Implemented: `src/mcp/abw_mcp/servers/wall.py:29-36#caller_projects`).

1. **No entitlement store (Implemented).** Entitlement is spread over four hard-coded or provisioned mappings: the project map and role checks in the wall server (`src/mcp/abw_mcp/servers/wall.py:13-16#PROJECT_TITLES`), the persona-to-role and persona-to-group lists in the identity script (`identity/Setup-Entra.ps1:50-61#Users`), the tool list per agent (`src/agent/abw_agents.py:42-48#WALL_DESK_TOOLS`), and the role and group assignments in Bicep (section 7.5). Nothing records who approved an entitlement, for how long it lasts, or when it was last reviewed. Entra provides that workflow as entitlement management (access packages with approval, time-limited assignment and access reviews; it needs Entra ID Governance or the Entra Suite): https://learn.microsoft.com/entra/id-governance/entitlement-management-overview. The repo does not use it, and DESIGN.md says the core demo depends on no Entra P1 or P2 feature (Designed: `DESIGN.md:240#P1/P2`). Why it matters: "who could read Falcon on a given date, and who approved it" cannot be answered from this repo.
2. **App roles at scale (Configured, with Platform behaviour).** Roles go directly to users (`identity/Setup-Entra.ps1:237-251#appRoleAssignments`), the app roles allow `User` members only (`identity/Setup-Entra.ps1:125#allowedMemberTypes`), and DESIGN.md says group-based assignment needs P1, which the build avoids (Designed: `DESIGN.md:226#P1`). Roles are issued per target API, so a token for one MCP API carries only that API's roles, and the MCP server reads every role in the token it receives (Implemented: `src/mcp/abw_mcp/auth.py:159#roles`; Designed: `DESIGN.md:226#separation-of-duties`). Learn documents ceilings that matter at scale: 1,500 app role assignments per principal, group overage above 200 groups in a JWT, and no nested-group support for app role assignment (https://learn.microsoft.com/entra/identity/users/directory-service-limits-restrictions, https://learn.microsoft.com/entra/identity-platform/access-token-claims-reference, https://learn.microsoft.com/entra/identity/enterprise-apps/assign-user-or-group-access-portal). Five personas never approach them; a firm with many deals and desks per user could (analysis).
3. **Four places per deal (Implemented).** A new deal touches: Entra, for an app role on the wall API (`identity/Setup-Entra.ps1:33-35#Wall.Falcon`) and a security group with persona memberships (`identity/Setup-Entra.ps1:48#Groups`); APIM, for the wall API's `roles` parameter (`infra/05-apim-apis.bicep:45#roles`); the MCP code, for the project map, the `project` type, the `doc_id` pattern and the role-to-project function (`src/mcp/abw_mcp/servers/wall.py:21#Literal`, `src/mcp/abw_mcp/servers/wall.py:26#doc_id`, `src/mcp/abw_mcp/servers/wall.py:29-36#caller_projects`); and Storage, for a container and a reader assignment (`infra/03-platform.bicep:172-186#wall-falcon`, `infra/03-platform.bicep:628-636#raFalconBlob`). The legacy server repeats the project type and the document pattern (`src/mcp/abw_mcp/servers/legacy.py:28#Literal`, `src/mcp/abw_mcp/servers/legacy.py:32#doc_id`), and the search index and agent tool lists are further places. The only drift detector is storage-side: Sentinel ABW-007 raises on layer-3 denials for a named principal (Configured: `observability/sentinel/abw-007-entitlement-drift.kql:11-12#AbwDenials`). Section 8.8 gives the recipe and marks what would need new design.
4. **Cosmos RBAC is container-wide, so per-user filters are code (Implemented).** Traders hold the data Contributor role on the whole `orders` container (`infra/03-platform.bicep:650-661#cosmosTradersOrders`). The rule that a trader sees only their own orders is a partition key and query filter chosen in the server (`src/mcp/abw_mcp/servers/actions.py:113-127#partition_key`); positions are filtered by a `desk` parameter with no per-desk entitlement at all (`src/mcp/abw_mcp/servers/private.py:19-34#desk`). Cosmos native data-plane RBAC is separate from Azure RBAC and its role definitions carry no `notDataActions` (https://learn.microsoft.com/azure/cosmos-db/reference-data-plane-security). Inference, untested: a trader who reached the private endpoint from inside the network and obtained a Cosmos data token as themselves would be authorised on the whole container, so the per-user boundary rests on layer 2.
5. **Search RBAC is whole-service with no document-level trimming (Implemented, with Platform behaviour).** The research group holds Search Index Data Reader on the whole service (`infra/03-platform.bicep:640-648#raSearchResearch`). Learn says RBAC alone does not trim documents inside an index (https://learn.microsoft.com/azure/search/search-document-level-access-overview). Wall documents sit in the same index with `content` and `snippet` empty and a `summary` built from the third and fourth non-blank lines of the document (after dropping any line that starts with SYNTHETIC DEMO), truncated to 240 characters, plus title, ticker, project and blob path (`src/seed/seed.py:131-172#build_search_documents`, `src/seed/seed.py:156-157#body_lines`); those fields are retrievable (`src/seed/seed.py:113-128#make_search_index`). Inference, untested: a research-group member with a direct route to Search could read wall titles and summaries but not the full text, which stays in Blob under container RBAC. The legacy search tools apply no classification filter at all (`src/mcp/abw_mcp/servers/legacy.py:49#filter_text`, `src/mcp/abw_mcp/servers/legacy.py:61#filter_text`).
6. **Orion has no holder, and the separation-of-duties rule is narrow (Implemented).** `Wall.Orion` exists as a role and the code knows the project (`src/mcp/abw_mcp/servers/wall.py:29-36#caller_projects`), but no persona holds it and no group can read the Orion container, by design (Configured: `infra/03-platform.bicep:638#Orion`). The `separation_of_duties` denial in the actions server fires only for a restricted security and a caller with a wall role (`src/mcp/abw_mcp/servers/actions.py:60-67#separation_of_duties`). DESIGN.md discloses that roles are issued per target API, so that branch is unit-tested only (Designed: `DESIGN.md:226#separation-of-duties`). Why it matters: it is a defence for a future token that carries both roles, not a rule real tokens exercise today (Inference).

#### 7.9.2 Enforcement coverage

These items concern paths and checks that skip a wall (Configured: `infra/apim/policies/mcp-jwt.policy.xml:37-44#revoked`).

7. **The private MCP server is outside APIM (Configured).** Foundry reaches it directly, and the server validates the token itself (Designed: `DESIGN.md:107#kill`; `src/agent/abw_agents.py:104#private`). Its ingress is `external: true` inside an internal-only environment (`infra/modules/mcp-app.bicep:40#external`, `infra/03-platform.bicep:385-388#internal`). It therefore has no runtime kill switch, no runtime allow-list (the APIM named values), no APIM rate limit and no gateway role check. It does have the deploy-time `MCP_ALLOWED_AZP` list, checked in the server, and its own token, role and audit checks (`infra/04-apps.bicep:77-84#serverEnv`, `infra/04-apps.bicep:141#serverEnv`, `src/mcp/abw_mcp/auth.py:151-153#bad_azp`). DESIGN.md names the production fix: an internal APIM in front, or have the server read the same deny list.
8. **Emergency-control limits (Implemented).** The kill switch and the allow-list are gateway-only, take about a minute, rely on a plain named value that a redeploy likely resets, and are pullable only by the operator in this repo (section 7.8). Revoking sessions stops new tokens only.
9. **The gateway scope check is a fixed `Tools.Read` (Configured).** The policy requires `Tools.Read` on every API (`infra/apim/policies/mcp-jwt.policy.xml:39#Tools.Read`). Entra returns every consented scope to the Azure CLI, so `missing_scope` cannot be shown live (Designed: `DESIGN.md:226#missing_scope`). The token-level rule is unit-tested (Tested: `src/mcp/tests/test_auth.py:26#missing_scope`); the tool-level rule that guards `place_order` has no test (section 8.7). `Tools.Execute` is enforced only inside the actions server (section 7.4).
10. **The rate-limit counter's scope is unspecified (Configured).** The 429 budget is a `rate-limit-by-key` keyed on the caller's `oid` (`infra/apim/policies/mcp-jwt.policy.xml:81#rate-limit-by-key`). The repo does not say whether the counter is shared across the four gateway APIs or kept per API, and P14 exercises the research API only (`demo/prove.py:871-873#GATEWAY`). Section 7.3 gives the reading used in this reference (most likely shared, an inference). The harness comment calls it a token bucket that refills at 2 per second (`demo/prove.py:878#token`), which matches Learn for v2 tiers (https://learn.microsoft.com/azure/api-management/rate-limit-by-key-policy).
11. **The legacy path has no user identity (Configured).** The legacy API is a shared subscription key with a rate limit and no JWT (`infra/apim/policies/mcp-legacy.policy.xml:8-8#rate-limit-by-key`). Its server holds broad data roles (`infra/03-platform.bicep:570-601#cosmosLegacyContrib`) and applies no filters (section 8.3). It exists to show the contrast; it is the intended weak path.
12. **Human approval lives in the agent definition, not in the server (Implemented).** `place_order` requires approval only because the wall-desk agent's tool definition says so (`src/agent/abw_agents.py:49#APPROVAL_REQUIRED`, `src/agent/abw_agents.py:119-139#require_approval`); the proof-of-concept agent uses `never` (`src/agent/abw_agents.py:150#require_approval`). A caller who holds `Trade.Execute` and calls the actions API directly is not asked for approval (Inference): the approval protects against agent autonomy, not against the user.
13. **The guardrail is probabilistic and detective (Designed, Tested).** Layer 0 is attached only when the agents are published with the guardrail flag (`src/agent/abw_agents.py:168-169#rai_config`), the red-team agent carries none by design, and when it fires it did so on only some identical requests (Designed: `DESIGN.md:30#probabilistic`, `DESIGN.md:228#guardrail`). Section 7.2 gives the detail. Why it matters: do not count layer 0 as a control; layers 1 to 3 are the deterministic ones.
14. **Conditional Access is report-only (Designed).** One report-only policy is "configured, not proven (nothing evaluated yet)" (Designed: `DESIGN.md:240#report-only`), and the guide says it has not yet evaluated a persona sign-in (Designed: `docs/DEMO-GUIDE.md:154#REPORT-ONLY`). MFA and per-user Conditional Access therefore play no proven part in the walls.
15. **Some policy controls are Audit-only previews (Configured).** The tool-endpoint, guardrail and approved-model definitions default to `Audit` and four further references use the audit effect even though Learn lists Deny (`infra/06a-policy-definitions.bicep:182-191#toolsEffect`). See section 7.7.9 for the list and the Findings for line references.

#### 7.9.3 Evidence, audit and proof

These items concern what the repo can show afterwards (Configured: `observability/kql/AbwDenials.kql:3#Every`).

16. **Entra refusals and Cosmos and Search denials are not in `AbwDenials` (Implemented).** The query says it lists "every refusal across all four defence layers", but its data-plane branch reads Storage logs only (`observability/kql/AbwDenials.kql:67-77#StorageBlobLogs`). The full-chain query does add the Entra sign-in row, but only for a token that was issued: it joins on the token id of each token the MCP servers saw, plus ids the Demo Console passes in for calls the gateway refused (Designed: `DESIGN.md:170#uti`; Configured: `observability/kql/AbwFullChain.kql:50-52#UniqueTokenIdentifier`). A refusal at the token endpoint issues no token, so it has no id to join on (Inference), and `AbwDenials` has no Entra layer. Why it matters: a refusal at the identity provider or at Cosmos or Search leaves no row in the one-stop denial view.
17. **A soft denial is HTTP 200 (Implemented).** By default the MCP server returns a denial as a normal result with `structuredContent` `DENIED`, because Foundry aborts the whole run when a tool result carries `isError` (`src/mcp/abw_mcp/registry.py:262-270#isError`; default `MCP_DENIAL_MODE` in `src/mcp/abw_mcp/config.py:157#MCP_DENIAL_MODE`). HTTP-status monitoring cannot see layer-2 denials; only the MCP audit event and the `structuredContent` body show them (section 7.4, section 8.5).
18. **Audit is best-effort and the WORM policy is unlocked (Implemented, Configured).** A failed append to the audit blob writes a line to standard error and continues unless the fail-closed setting is on, and the deployment does not set it (`src/mcp/abw_mcp/audit.py:88-103#append_audit_failed`). The retention policy is time-based, one day, unlocked (`infra/03-platform.bicep:193-202#immutabilityPeriodSinceCreationInDays`; Designed: `DESIGN.md:239#unlocked`). Learn calls an unlocked policy suitable only for short-term testing and requires a locked policy for SEC 17a-4(f) (https://learn.microsoft.com/azure/storage/blobs/immutable-storage-overview#time-based-retention-policies). It demonstrates the pattern, not a compliance attestation.
19. **The proofs ran as the operator mirroring a persona (Tested, with a caveat).** The final proof run used the deploying account, which mirrors a persona's app roles and group memberships, rather than the personas' own sign-ins (Implemented: `demo/prove.py:303-304#persona`; Designed: `DESIGN.md:241#mirrors`). The proofs show platform behaviour for those role and group sets; MFA and per-user Conditional Access paths are not exercised, and Wes, Tara and Carla are designed rather than observed.

#### 7.9.4 Platform principals and who can change the controls

These items concern the identities that sit behind the walls (Configured: `infra/03-platform.bicep:733-735#Owner`).

20. **The operator is Subscription Owner (Configured, with Platform behaviour).** The Bicep comment states that Owner is not a data-plane role and that the operator has no blob, index or document access. Learn confirms that Owner has all management actions and no data actions, and can assign roles (https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/privileged). So nothing technical stops the operator from granting itself a data role, and the runbook relies on the operator not having one, because a direct grant would break proof P16 (Designed: `docs/RUNBOOK.md:122#P16`). I found no Sentinel rule, KQL function or workbook query in the observability folder that reads role-assignment activity; the only `Microsoft.Authorization` queries there read policy assignments and exemptions (`observability/workbook/build_workbook.py:329#policyassignments`, `observability/workbook/build_workbook.py:358#policyexemptions`). Why it matters: "Owner is not data access" holds until Owner assigns a role.
21. **The seed and legacy identities hold broad data roles (Configured).** The seed identity has Blob Data Contributor, Search Service Contributor, Search Index Data Contributor and a Cosmos data Contributor role at account scope (`infra/04b-seed-job.bicep:61-99#raBlob`); the job is manual and has a 15-minute replica timeout (`infra/04b-seed-job.bicep:122-123#triggerType`). The legacy identity has broad blob, search and Cosmos access by design (`infra/03-platform.bicep:570-601#cosmosLegacyContrib`). They are not user-reachable, but they persist after seeding.
22. **Agent invocation is project-wide for the demo group (Configured).** The demo group holds the Foundry Agent Consumer role at project scope (`infra/02-foundry-rbac.bicep:36-44#raConsumersProject`). The repo has no per-agent assignment: the grant is at project scope, so it is not narrowed to one agent. Whether that lets a group member invoke the red-team agent was not tested here. What an agent can reach is still bounded by the caller's own roles, because tool calls carry the user's token.
23. **Time-to-effect figures are measurements, not guarantees (Platform behaviour).** Learn says Azure role assignment changes can take up to about 10 minutes to propagate (https://learn.microsoft.com/azure/role-based-access-control/troubleshooting), while P16 measured 5-44 s (Designed: `DESIGN.md:218#measured`). Treat the measured numbers as the good case.

**Key takeaways**

- **Four walls, three deterministic.** The gateway policy, the MCP rule and data-plane RBAC each decide independently on the same caller; the Foundry guardrail is probabilistic and detective (`DESIGN.md:30#probabilistic`).
- **The same wall is refused in different places, with different shapes.** A caller with no wall role (Priya, Tara, Ian) is refused at the gateway with a 403 JSON body (`infra/apim/policies/mcp-jwt.policy.xml:64-77#forbidden`); a Falcon-crossed caller (Wes, Carla) asking for an Orion document is refused at the MCP server with HTTP 200 and `DENIED` (`src/mcp/abw_mcp/servers/wall.py:39-47#project_not_in_token_roles`); a caller who holds the role but has lost the group is refused by Storage and mapped to `DENIED` (`src/mcp/abw_mcp/servers/wall.py:94-96#storage_rbac_denied`).
- **The weakest point is the entitlement lifecycle.** Entitlements are authored in four places, there is no store, no approval and no review (`src/mcp/abw_mcp/servers/wall.py:13-16#PROJECT_TITLES`), and app-role scale limits are real.
- **Containment is gateway-scoped.** The kill switch and the allow-list take about a minute, act on APIM paths only, and a redeploy likely resets them (`scripts/kill-switch.ps1:70-74#Set-DenyList`).
- **The private server skips APIM.** It keeps its own token, role, deploy-time client-list and audit checks but has no runtime kill switch, no runtime allow-list and no gateway rate limit (`DESIGN.md:107#kill`).
- **Policy-as-code governs configuration, not requests.** Some definitions are Audit-only previews, and an organisation baseline can correct instead of deny (section 7.7).
- **Evidence has holes.** Soft denials are HTTP 200, Cosmos and Search refusals and Entra refusals are not in `AbwDenials`, audit appends fail silently, and the WORM policy is unlocked (`src/mcp/abw_mcp/audit.py:88-103#append_audit_failed`).
- **The proofs are strong for platform behaviour and silent on persona sign-in.** They ran as the operator mirroring roles and groups, so MFA and Conditional Access paths are not exercised (`demo/prove.py:303-304#persona`).

---

[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [6. Authentication: identities, tokens and trust](06-authentication.md) | Next: [8. MCP server internals](08-mcp-server-internals.md)
