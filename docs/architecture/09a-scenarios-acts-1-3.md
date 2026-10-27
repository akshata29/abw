[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [8. MCP server internals](08-mcp-server-internals.md) | Next: [9. Scenarios, part 2: Act 4 (9.5)](09b-scenarios-act-4.md)

> Section 9 (Scenarios: Acts 1 to 7 end to end) is split across seven files. This one holds 9.1 to 9.4.

## 9. Scenarios: Acts 1 to 7 end to end

This section follows every scripted scenario (an "act") of the Demo Console from the first click to the last log row. The acts are data, not UI code: each one is a dictionary with an `id`, a navigation label, a `title`, a `story` and a list of `beats` (`console/catalog.py:238-251#SCENES`), and the seven titles read "Act 1 - ..." to "Act 7 - ..." (`console/catalog.py:249#Act`). One list therefore drives the narration, the buttons, the plain-English verdicts and the lights on the architecture strip.

Three things cooperate, and every scenario names all three:

- **The console** (`console/`) runs a beat and shows what happened just now.
- **`demo/prove.py`** proves the same behaviour headlessly, with assertions, and writes a scoreboard of 18 proofs (`README.md:6#proofs`).
- **The logs** (Log Analytics, Sentinel, the Storage log, Entra's sign-in log) keep the evidence after the console is closed.

The mechanisms these scenarios exercise are specified elsewhere and are referred to by number, not repeated: authentication (which token, which `aud` value, which claims) is section 6, authorization (gateway rules, tool rules, RBAC) is section 7, MCP server internals are section 8, and data flow, observability and the Demo Console itself are sections 10 to 12 (data flow, observability, Demo Console). Here each sequence step cites the code that performs it and names the section that holds the detail.

**Why the scenarios are data.** A beat carries its own expected result, technical note, sales line and the architecture nodes to light (`console/catalog.py:253-270#expect`), so the talk track, the UI and the checks cannot drift apart silently; changing a scene is a data edit. **Trade-off / limitation:** the expected-result prose is a claim written by a person. It is checked only where a proof covers it (section 9.9); the card the console draws from the real response, not the prose, is the evidence.

### 9.1 How to read a scenario

**What this section proves.** It defines the template, the labels, the evidence vocabulary and the shared request path that every act in 9.2 to 9.8 reuses, so that each act can be read as a delta against the shared path instead of being re-explained. Walls are numbered 0 to 3 as in `DESIGN.md:30-33#abw-agent-guardrails`: wall 0 is the Foundry guardrail, wall 1 the APIM gateway, wall 2 the MCP server, wall 3 the data plane.

#### 9.1.1 The scenario template

Every act is written in the same ten parts. Parts 1 to 3 are stated once per act in an "Act overview" subsection; parts 4 to 10 are repeated for every beat, as bold lead-ins under the beat heading; each act closes with an act summary that gathers the evidence, the proofs, the Sentinel incident and the presenter notes.

| # | Part | The question it answers | Level |
|---|------|-------------------------|-------|
| 1 | Purpose | What is demonstrated, and which wall or control it shows | act |
| 2 | Actors and tokens | Which identity acts, which token is on the wire, with a pointer to section 6 | act |
| 3 | Preconditions | What must be deployed, consented or quiet before the beat is meaningful | act |
| 4 | Sequence | Numbered hops, component to component, with the token or header on the wire, the policy or rule evaluated, and a citation per step | beat |
| 5 | Success outcome | The exact shape of a good result, with placeholders | beat |
| 6 | Failure or denial outcomes | The exact shapes of refusals and which wall produced each | beat |
| 7 | Evidence produced | Where the evidence lands (table.column, blob, Foundry output) and how to retrieve it | beat |
| 8 | How the console runs it | The catalog entry, the job kind, the runner and the event types | beat |
| 9 | How demo/prove.py proves it | The proof id, its assertions and what it writes | beat |
| 10 | Failure modes and what the presenter should say | What can go wrong live and the wording to use | beat |

#### 9.1.2 Provenance labels

Every substantial statement carries one of these labels, so a reader can tell code from intent from platform behaviour.

| Label | Meaning | How to check it |
|-------|---------|-----------------|
| **Implemented** | Behaviour performed by code in this repo | Follow the citation to the function |
| **Configured** | Behaviour that exists because of Bicep, policy XML or JSON in this repo | Follow the citation to the template or policy |
| **Designed** | A claim in `DESIGN.md` or the docs that no single code line proves | Read the cited document line |
| **Platform behaviour** | Behaviour of Azure, Entra, Foundry or APIM itself | Stated here and not re-verified in this section; sections 6 and 7 carry the verified statements |
| **Not in this repo** | Something that exists only in the tenant or the portal, for example a response body that APIM generates itself | Nothing to cite |

#### 9.1.3 Evidence tags

An evidence tag says how a piece of evidence was obtained. The console shows the tag next to every row of a board, so a viewer can tell "I just did this" from "the platform says so" from "this was predicted".

| Tag | Console wording | Meaning | Source | Typical lag |
|-----|-----------------|---------|--------|-------------|
| `live` | seen live | The console made the request itself and read the response | The console's own HTTP call or agent run (`console/jobs.py:452-463#call_gateway`) | none |
| `probe` | read live from Azure | A read-only configuration probe of the deployed resource | `console/azure_probe.py` probes through ARM and Resource Graph, for example `probe_foundry`, `probe_data`, `probe_policy` | none (state now) |
| `logs` | from the logs | A Log Analytics query for this request id or this click's marker | `la_query` (`console/azure_probe.py:165-180#la_query`) over the `Abw*` functions | 2 to 18 minutes |
| `graph` | from Entra's sign-in log | A sign-in log row read back through Microsoft Graph | Entra sign-in logs (non-interactive and interactive) | 10 to 20 minutes |
| `arm` | read from Azure (ARM) | An alert read through the Azure Resource Manager API | The subscription's Defender for Cloud alert list, read twice and merged by `_defender_alerts` (`console/e2e.py:1789-1794#_defender_alerts`); the tag is set on the Defender row (`console/e2e.py:1821#arm`). Sentinel alerts are read from Log Analytics and carry the `logs` tag instead | minutes; not guaranteed |
| `replay` | replay of an earlier run | A saved result of an earlier run, shown again without re-running | The evidence files on disk, for example the policy-violation run (`console/e2e.py:726#replay`) | not applicable |
| `portal` | portal step - not read here | Something only the portal shows; the console gives the click path | Azure portal or the Agent 365 management surfaces (`console/e2e.py:947#portal`) | not applicable |

The console words come from `console/web/render.js:287-298#TR_EVIDENCE`; combined tags read "seen live + read from Azure", "seen live, confirmed in logs" and "seen live + Entra's sign-in log". The default tag of a board row is `live` (`console/e2e.py:193#evidence`).

A row also has a state: `pass` (Passed), `block` (Stopped here), `skip` (Never reached), `na` (Not used), `info` (Note), `due` (Waiting), `quiet` (Quiet), `seen` (Seen) or `portal` (Portal step) (`console/web/render.js:286#TR_STATE`). A row that is `due` says what it is waiting for: the default is "expected - not seen yet", `logs` is "waiting for the logs", `graph` is "waiting for Entra's log", `arm` is "waiting for an alert" (`console/web/render.js:299#TR_DUE`). The console's own lag statement is: logs reach Log Analytics 2 to 18 minutes after a call, Sentinel alerts 5 to 15 minutes, Entra's own sign-in log 10 to 20 minutes, and a row changes only when the service really shows this request (`console/web/render.js:300#TR_LAG`).

The Act 7 role matrix uses a different, four-word vocabulary for the same idea: `live` is "request just made", `rbac` is "Azure role assignment, read live", `logs` is "read from Log Analytics" and `design` is "predicted by the role model - not run" (`console/web/render.js:206-212#MX_EVIDENCE`). It is explained in 9.8.2.

**Why.** A board that painted every layer green because the request succeeded would be a claim, not evidence. Each row is allowed to turn green only when the named source shows this request (`console/e2e.py:193#evidence`). **Trade-off / limitation:** the log-based rows lag the click by minutes, so a full-chain board is "waiting" first and is completed by a Refresh; Entra's own log is the slowest source.

#### 9.1.4 Anatomy of a beat

A beat is one dictionary in `console/catalog.py`. The first beat of Act 1 shows every field (`console/catalog.py:253-270#expect`).

| Field | Meaning | Example (beat 1.1) |
|-------|---------|--------------------|
| `id`, `title` | The beat number and its heading | `1.1`, "The PoC everyone builds" |
| `say` | One sentence for the presenter to read aloud | "One shared key, no identity. A user who is NOT cleared for Project Orion asks for it." |
| `button`, `eta` | The button label and the expected duration | "Run the legacy agent", "~25 s" |
| `run` | The job the button starts: `{"kind": ..., ...}` | `{"kind":"agent","agent":"abw-poc-legacy","prompt":"orion","approve":"yes"}` |
| `alt` | An optional deterministic or quick alternative job | "Deterministic: raw legacy call" (kind `gateway`, tool `get_deal_document`) |
| `expect` | What a correct run shows | "Every call ... answered, and none of them checked who was asking" |
| `tech` | The technical note behind the card | The legacy path is an APIM subscription key behind `/legacy/mcp` |
| `sales` | The one-line sales framing | "This is the demo every customer has already built." |
| `prove` | Architecture node ids the strip lights and the "open the real service" chips link to | `["foundry","apim","policy"]` |
| `faq` | Optional answers to questions the room may ask | Present on beat 2.2 and several Act 6 and Act 7 beats |

`prove` lists nodes of the architecture strip, not proof ids of `demo/prove.py`: the page turns each entry into a chip that opens the real Azure resource (`console/web/pages.js:114#nodeChip`), and the strip maps nodes to walls (`console/web/strip.js:14#WALL_OF`). The proof ids that cover a beat are listed in 9.1.9 and 9.9.

#### 9.1.5 What happens when you click a beat

Every beat runs the same way. **Implemented:**

1. The page posts `POST /api/jobs` with `{kind, params, title, beat}`; the handler calls `MANAGER.start(kind, params, title[:120], beat[:12])` and answers `{"id", "status"}` or an error with HTTP 409 (`console/server.py:128-135#api_jobs_start`; route table `console/server.py:366-372#api_jobs_start`). The page sends the beat's whole `run` dictionary as `params`, so `params` repeats `kind`; for the gateway-level kinds (`gateway` except the legacy server, `xpia`, `burst`) it also adds the persona the presenter picked in the "Acting as" drawer. The request bodies printed in the act sections list only the keys that matter and leave out `title` and the repeated `kind` (`console/web/util.js:160-162#startJob`, `console/web/personas.js:29-31#withPersona`).
2. `Manager.start` refuses an unknown kind, runs `validate` (for an agent job: the agent must be in `ALLOWED_AGENTS`, the prompt a catalog key or 3 to 500 characters, `approve` one of ask, yes, no; for a gateway job: server and tool from allow-lists and never the private server), refuses kinds in `NEEDS_OPEN_GATEWAY`, and the `kill` kind, while the kill switch is engaged ("Reset demo" first), refuses an `allowlist` job while the allow-list is off its baseline, refuses a job that conflicts with a running one (two disruptive jobs; a disruptive job against a gateway or agent job, except an allow-list change against an agent job; two agent jobs; two `violations` jobs; read-only kinds never conflict), keeps at most 60 jobs and starts a daemon thread (`console/jobs.py:503-533#start`, `console/jobs.py:563-593#validate`, `console/jobs.py:495#NEEDS_OPEN_GATEWAY`, `console/jobs.py:473-492#conflicts`).
3. `_run` looks the runner up in `RUNNERS`, turns a cancel into a "Stopped." step, turns an exception into an `error` event worded by `friendly`, and always invalidates the cached status lights (`console/jobs.py:535-548#_run`, `console/jobs.py:1401-1424#RUNNERS`, `console/jobs.py:163-173#friendly`).
4. The runner emits events through `Job.emit`, each `{"i": <index>, "t": <seconds>, "type": <type>, ...}` (`console/jobs.py:276-280#emit`); `say` and `step` are the two text events (`console/jobs.py:282-286#say`).
5. The page polls `GET /api/jobs/<job-id>?since=<n>`; `Job.view` returns the events from `n` on and the next index (`console/server.py:144-152#api_job`, `console/jobs.py:288-294#view`).
6. An agent beat started with `approve = ask` parks the job in `waiting` and emits an `approval` event; the page answers with `POST /api/jobs/<job-id>/approve` and `{id, approve}`, and `Job.answer` writes `{"approve": true|false}` as one line to the agent process's standard input (`console/server.py:155-162#api_job_approve`, `console/jobs.py:317-343#need_approval`).
7. The runner ends with `Job.finish(status, summary, **result)`, which emits a `done` event and is ignored if the job already finished (`console/jobs.py:296-304#finish`).

A finished gateway job (beat 1.4) looks like this when polled; `<job-id>` and `<request-id>` are placeholders.

```json
{
  "id": "<job-id>",
  "kind": "gateway",
  "title": "<title sent by the page>",
  "beat": "1.4",
  "status": "done",
  "elapsed": 3.2,
  "events": [
    {"i": 0, "t": 0.0, "type": "say", "text": "Calling wall.get_deal_document through the APIM gateway with the signed-in user's Entra token. No key anywhere."},
    {"i": 1, "t": 3.1, "type": "http", "server": "wall", "tool": "get_deal_document", "status": 200,
     "decision": "DENIED", "reason": "project_not_in_token_roles", "request_id": "<request-id>",
     "verdict": "denied", "wall": 2, "title": "The MCP server said no"},
    {"i": 2, "t": 3.1, "type": "say", "text": "Request id <request-id> remembered for Act 5."}
  ],
  "next": 3,
  "result": {"summary": "Refused: HTTP 200 DENIED project_not_in_token_roles", "verdict": "denied", "request_id": "<request-id>"},
  "pending": []
}
```

The `say` texts and the finish label come from `run_gateway` (`console/jobs.py:843-860#run_gateway`); the `http` event is built by `http_result` (`console/jobs.py:229-253#http_result`). The gateway runner takes the operator's delegated token (the Azure CLI public client, see `demo/mcpclient.py:39#AZURE_CLI_CLIENT_ID`) or, for a persona, that persona's own token; for the legacy server it sends the APIM subscription key instead (`console/jobs.py:428-438#token_for`, `console/jobs.py:452-463#call_gateway`; token mechanics in section 6).

**Agent beats** start the Foundry agent in a child process, `console/agent_run.py`, and translate its JSON lines into console events (`console/jobs.py:717-796#agent_once`, `console/jobs.py:358#stream_process`). The child builds the operator's credential, creates a project client and calls the Responses API with an `agent_reference` for the named agent (`console/agent_run.py:83-87#agent_reference`, `src/agent/ask.py:109-118#build_credential`).

| Child line (`agent_run.py`) | Console event | What the console adds |
|-----------------------------|---------------|-----------------------|
| `who` | `who` | The note that the operator mirrors Wes and Tara (`console/jobs.py:60-61#WHO_NOTE`) or, for the legacy agent, that the sign-in is ignored |
| `tools` | `tools` (batched) | Per server, the tool names the agent was given |
| `call` | `call` | `server`, `tool`, `args`, `request_id`, `decision`, `reason`, an excerpt, `leak` terms and the verdict from `judge` |
| `consent` | `failure` with code `consent_required` | "One-time consent needed" and the consent link |
| `approval`, `approval_answer` | `approval` (or a waiting job) and `approval_answer` | The tool, server and arguments awaiting a human |
| `failure` | `failure` | Title, plain text, wall, front-door flag from `explain_failure` |
| `final` | `answer`, or `stop` when the guardrail ended the run | Answer text, seconds, token counts, gateway ids |

The `call` line carries `{"type":"call","server","tool","args","ok","guardrail","body","decision","reason","request_id"}`, where `decision`, `reason` and `request_id` are lifted from the tool result text by three regular expressions (`console/agent_run.py:28-30#DECISION`, `console/agent_run.py:42-70#show_items`).

#### 9.1.6 Verdicts and the denial vocabulary

The console does not take the model's word for what happened. `judge` derives a verdict from the tool result: a guardrail hit is a denial at wall 0; a 401 without a reason becomes `no_valid_token`; a decision of DENIED or BLOCKED, or HTTP 401, 403 or 429, is a denial worded by `explain`; a 2xx result that is not ERROR is "Allowed - every layer in the path agreed"; anything else is a failure (`console/jobs.py:176-198#judge`). Two views refine "allowed":

- `legacy_outcome`: the shared-key path carries no identity, so a call that worked is never plain "allowed". It is `leak` ("It answered - to anyone") when `leak_terms` finds confidential markers (deal ids, projects, amounts, party names; at most six) and `unchecked` ("It answered - nobody checked who asked") otherwise (`console/jobs.py:204-215#legacy_outcome`, `console/jobs.py:146-153#leak_terms`).
- `crossings_view`: a successful `list_my_wall_crossings` is titled "The wall's answer, read from the token: cleared on ..." with the projects found in the result, so a bare "Allowed" is not misread as clearance for everything (`console/jobs.py:218-226#crossings_view`).

Denials are worded from a table keyed by the reason code (`console/catalog.py:46-77#REASONS`, `console/catalog.py:101-108#content_filter`, `console/catalog.py:118-125#explain`); the wall labels are `console/catalog.py:110-115#WALLS`.

| Reason code | Wall | Card title | Raised by |
|-------------|------|------------|-----------|
| `content_filter` | 0 | Foundry guardrail | The Foundry guardrail (platform behaviour; the console infers it from the run, see 9.5) |
| `missing_role`, `revoked`, `client_not_allowed`, `no_valid_token`, `rate_limit`, `token_quota_exceeded` | 1 | The gateway said no / Kill switch / Wrong application / No valid token / Rate limit / Token budget used up | APIM policy (9.1.8, G2 to G4; the front door in 9.8.3) |
| `project_not_in_token_roles`, `restricted_list`, `separation_of_duties` | 2 | The MCP server said no / Trading control said no / Separation of duties | The tool's own rule (9.1.8, G7 to G8) |
| `storage_rbac_denied`, `AuthorizationPermissionMismatch` | 3 | The data plane said no | Azure RBAC on the user's own token |

A call that was refused is lit on the strip at the wall that said no, and the nodes before it are lit green (`console/catalog.py:173-190#lights_for_call`). A 429 with no reason is mapped to `rate_limit` (`console/catalog.py:118-125#explain`). **Why:** the viewer sees which wall decided, not just that something failed. **Trade-off / limitation:** a reason code that is not in the table falls back to the generic card "Refused - a control refused this call" with no wall.

#### 9.1.7 Outcome shapes

Every act below refers to these shapes by name. Bodies are shown with placeholders; where a body is generated by the platform and not by this repo it is marked as such.

| Shape | HTTP | Body | Produced by |
|-------|------|------|-------------|
| Gateway 401 | 401 | `{"error":"unauthorized","server":"<server>","reason":"a valid Entra access token for this MCP server is required"}` plus a `WWW-Authenticate` challenge that points at the protected-resource document (value not reproduced here) | APIM `on-error` for a failed `validate-jwt` (`infra/apim/policies/mcp-jwt.policy.xml:96-112#on-error`) |
| Gateway 403 | 403 | `{"error":"forbidden","reason":"<revoked, client_not_allowed, missing_scope or missing_role>","server":"<server>","request_id":"<request-id>"}` | APIM `abw-deny` (`infra/apim/policies/mcp-jwt.policy.xml:64-80#return-response`) |
| Gateway 429 | 429 | The body is APIM's own and is not defined in this repo; the `Retry-After` header carries the wait | APIM `rate-limit-by-key`, 120 calls per 60 s per `oid` (`infra/apim/policies/mcp-jwt.policy.xml:81#rate-limit-by-key`) |
| Missing key (legacy path) | 401 | APIM's own subscription-key error; not defined in this repo | `/legacy` API with `subscriptionRequired: true` (`infra/05-apim-apis.bicep:169-182#subscriptionRequired`) |
| MCP-level 401 or 403 | 401 or 403 | `{"error":"invalid_token" or "insufficient_scope","error_description":"<reason code>"}` plus a `WWW-Authenticate` challenge | The MCP server's bearer middleware, reason codes such as `missing_token`, `bad_signature`, `bad_issuer`, `expired`, `bad_tenant`, `app_only`, `bad_azp`, `missing_scope` and the wrong-target code for a token minted for another application; the 403 form is used only for `missing_scope`, because the middleware is registered without a role check, so a missing role is a soft denial instead (`src/mcp/abw_mcp/auth.py:250-260#_auth_error_response`, `src/mcp/abw_mcp/app.py:244-249#BearerAuthMiddleware`) |
| Soft denial | 200 | A JSON-RPC result whose `structuredContent` is `{"decision":"DENIED","error":"FORBIDDEN","message":"...","reason":"<reason>","request_id":"<request-id>","note":"Blocked by policy and written to the audit log. ..."}` and `isError` false | The tool registry in the default `MCP_DENIAL_MODE=soft` (`src/mcp/abw_mcp/registry.py:273-292#_error_payload`, `src/mcp/abw_mcp/registry.py:238-270#_tool_error_result`) |
| Strict denial | 200 | The same payload with `isError` true, which makes Foundry abort the run with HTTP 400 `tool_user_error` | `MCP_DENIAL_MODE=strict` (`src/mcp/abw_mcp/registry.py:263-265#isError`) |
| Data-plane denial | 200 (soft) | A soft denial with `error` `FORBIDDEN`, message "Storage access denied.", reason `storage_rbac_denied` | Storage answered 403 to the on-behalf-of token (`src/mcp/abw_mcp/data.py:57-71#read_blob_text`) |
| Guardrail stop | 200 (response incomplete) | The Foundry response ends `incomplete` with a content-filter reason; the tool result is withheld ("returned no result") | The Foundry guardrail (platform behaviour; wording in `console/jobs.py:788-803#content_filter`) |
| Front-door error | 401, 403, 429 | `{"error":{"code","message","reason","retry_after_seconds","request_id"}}` | The agent front door (9.8.3) |

A denial by a tool is HTTP 200 on purpose: the model receives the structured reason and can explain the block honestly (`DESIGN.md:132#Soft`). A denial by the gateway is a real 401 or 403 because no tool ran.

#### 9.1.8 The shared governed call path (G1 to G9)

Acts 1, 4, 5, 6 and 7 all ride the same nine hops; each act below names only the hops it adds or changes. Provenance is **Implemented** or **Configured** unless noted.

`Diagram: docs/diagrams/03-request-data-flow.excalidraw`

| Hop | Component to component | On the wire and rule evaluated | Citation |
|-----|------------------------|--------------------------------|----------|
| G1 | Caller -> APIM | `POST <apim-gateway-url>/<server>/mcp`, headers `Content-Type: application/json` and `Accept: application/json, text/event-stream`, an `Authorization` header carrying the Bearer-scheme access token for that MCP server, and a JSON-RPC body `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"<tool>","arguments":{}}}`. For agent beats the caller is the Foundry Agent Service tool runtime using the token it stored for the signed-in user (section 6). The four published APIs need no subscription key. | `demo/mcpclient.py:124-141#rpc`, `infra/05-apim-apis.bicep:123-135#subscriptionRequired`, `scripts/foundry-connections.ps1:59-65#specs` |
| G2 | APIM `validate-jwt` | Header `Authorization`, Bearer scheme, expiry required, signed tokens required, clock skew 60 s, failure -> 401; the `aud` claim must be the server's own application, the issuer is the tenant's v2.0 issuer, and the claim `tid` must match | `infra/apim/policies/mcp-jwt.policy.xml:17-30#validate-jwt` |
| G3 | APIM `abw-deny` | Evaluated in this order: `oid` in the revoked list (`revoked`), `azp` not in the client allow-list (`client_not_allowed`), `scp` without `Tools.Read` (`missing_scope`), no required app role (`missing_role`). The JSON-RPC `method` is read from the body; where the server's discovery is open (`listOpen`), the methods `initialize`, `ping`, `tools/list` and notifications skip the role check. | `infra/apim/policies/mcp-jwt.policy.xml:31-46#abw-deny` |
| G4 | APIM decision | Emits metric `abw-gateway-decisions` (dimensions server, decision, reason, `oid`) and a trace `abw-gateway`; a denial returns the 403 body of 9.1.7; an allow applies `rate-limit-by-key` (120 per 60 s per `oid`), sets `x-abw-request-id` from the APIM request id (overriding any client value) and `x-abw-gateway: apim` | `infra/apim/policies/mcp-jwt.policy.xml:51-56#abw-gateway-decisions`, `infra/apim/policies/mcp-jwt.policy.xml:57-63#abw-gateway`, `infra/apim/policies/mcp-jwt.policy.xml:81-87#rate-limit-by-key` |
| G5 | APIM -> MCP Container App | Forward to the server's backend `https://<fqdn>` (internal ingress); the Bearer token is passed through unchanged on the research, wall and actions servers only: the vendor API deletes it, the legacy API takes a subscription key instead, and the vendor app's ingress is external, not internal (next paragraph and 9.4) | `infra/05-apim-apis.bicep:94-106#backends`, `infra/05-apim-apis.bicep:75-79#vendorSection` |
| G6 | MCP middlewares | `RequestContextMiddleware` takes the request id from `x-abw-request-id` first, then `x-request-id`, `x-ms-request-id` and `traceparent`, and makes one up if none is present; `BearerAuthMiddleware` calls `verify_token`: RS256 signature from the tenant's keys, the `aud` claim, v2.0 issuer, `tid`, not app-only, `azp` allow-list, required scope; a failure emits an `auth_failed` audit event and returns the MCP-level 401, or 403 for `missing_scope` only; a missing role is decided later, by the tool layer | `src/mcp/abw_mcp/app.py:241-254#BearerAuthMiddleware`, `src/mcp/abw_mcp/auth.py:108-142#verify_token`, `src/mcp/abw_mcp/auth.py:144-170#Caller`, `src/mcp/abw_mcp/auth.py:173-189#RequestContextMiddleware`, `src/mcp/abw_mcp/auth.py:191-248#BearerAuthMiddleware` |
| G7 | Registry | `tools/list` returns only tools whose requirement the caller meets; `tools/call` re-checks the requirement, validates the arguments, then runs the handler | `src/mcp/abw_mcp/registry.py:132-156#list_tools`, `src/mcp/abw_mcp/registry.py:158-175#call_tool`, `src/mcp/abw_mcp/registry.py:98-121#require_any_role` |
| G8 | Handler -> data plane | The handler applies its own rule (for the wall: `_require_project`) and reads the data with a token it obtained on behalf of the caller: a client assertion from the server's user-assigned managed identity for `api://AzureADTokenExchange` plus the caller's token as the user assertion (section 6) | `src/mcp/abw_mcp/servers/wall.py:88-105#get_deal_document`, `src/mcp/abw_mcp/data.py:57-71#read_blob_text`, `src/mcp/abw_mcp/obo.py:39-79#OboBroker` |
| G9 | Result and audit | The request id is added to the payload, one audit event is written, and the result is a `CallToolResult` with compact JSON text plus `structuredContent` | `src/mcp/abw_mcp/registry.py:195-220#setdefault`, `src/mcp/abw_mcp/audit.py:178-216#build_event`, `src/mcp/abw_mcp/audit.py:54-102#AppendBlobAuditSink` |

What each hop leaves behind, and how to read it back:

| Hop | Evidence row | Where it lands | Retrieval |
|-----|--------------|----------------|-----------|
| Token issue and OBO exchange | Entra sign-in row (non-interactive for the exchange) | Entra sign-in logs | Graph read (`graph` tag, Act 6) |
| G2 to G4 | Gateway log row with `CorrelationId`, trace record `abw-gateway`, metric `abw-gateway-decisions` | `ApiManagementGatewayLogs` | `AbwGateway` (`observability/kql/AbwGateway.kql:1-12#AbwGateway`) |
| G6 to G9 | One JSON audit line per decision | Container Apps console log and the append blob in container `worm-audit` | `AbwMcpAudit` (`observability/kql/AbwMcpAudit.kql:1-8#ContainerAppConsoleLogs`) |
| G8 | Storage log row whose `ClientRequestId` equals the request id | `StorageBlobLogs` | `AbwIdentityChain` (`observability/kql/AbwIdentityChain.kql:39#StorageBlobLogs`) |
| Agent run | Output items `mcp_list_tools`, `mcp_call`, `mcp_approval_request`, `message` | The Foundry response | `demo/evidence-scrubbed/` shows the shape; the console prints the items |

Three paths differ from G1 to G9. The **legacy path** replaces G2 to G4 with a subscription key and a per-key rate limit and has no authentication middleware at G6 (`infra/apim/policies/mcp-legacy.policy.xml:6-15#rate-limit-by-key`, `src/mcp/abw_mcp/app.py:241-248#legacy`). The **private path** skips G1 to G5: the Foundry agent subnet calls the private server directly (`DESIGN.md:107#private`). The **vendor path** adds a gateway step that deletes the user's `Authorization` header and injects the vendor key (`infra/05-apim-apis.bicep:75-80#vendorSection`). **Why:** on the research, wall and actions servers the same JWT checks run at two independent hops (G2 and G6), so a request that bypasses the gateway still meets a server that verifies the token itself; the private server has only the G6 check, and the vendor and legacy paths have none at G6, the vendor server checking only the injected vendor key (`src/mcp/abw_mcp/app.py:115-142#VendorKeyMiddleware`, `src/mcp/abw_mcp/app.py:241-249#BearerAuthMiddleware`); **Trade-off / limitation:** the private server therefore has no kill switch and no rate limit (9.4, Findings).

#### 9.1.9 Summary of all acts

| Act | Title | Persona(s) | Walls exercised | Proof ids | Console location |
|-----|-------|-----------|-----------------|-----------|------------------|
| 1 (`console/catalog.py:249#Act`) | Same question, two answers | The operator, who mirrors Wes and Tara, for agent beats; beat 1.4 can run as a signed-in persona; Priya in the "Path A" script | Legacy path: none, by design. Governed path: walls 1, 2 and 3 | P03, P08 (P02 for the no-role case) | Act 1 page, beats 1.1 to 1.4 |
| 2 (`console/catalog.py:319#Act`) | No keys | The operator (ARM and Log Analytics reads) | Azure Policy platform controls; wall 3 is Entra-only | P01, P11 | Act 2 page, beats 2.1 to 2.3 |
| 3 (`console/catalog.py:372#Act`) | Whose hands are on the data | The operator | Private path: walls 2 and 3, APIM not in the path. Vendor path: wall 1 plus the gateway-held vendor key | P06, P07 | Act 3 page, beats 3.1 to 3.3 |
| 4 (`console/catalog.py:416#Act`) | When it goes wrong | The operator; the gateway-level beats can run as a persona | Walls 0, 1 (rate limit, allow-list, kill switch) and 2 (restricted list), plus the human approval gate | P14, P04, P05, P09, P15, P12 (P16 is replayed in 6.5) | Act 4 page, beats 4.1 to 4.5 |
| 5 (`console/catalog.py:499#Act`) | What InfoSec sees | The operator in the console; the human reader is Ian (Log Analytics Reader) | Observability across all walls | P10, P13, P17 | Act 5 page, beats 5.1 to 5.6, and the Scoreboard page |
| 6 (`console/catalog.py:598#Act`) | One request, every layer | The operator; Priya in 6.3 | Twelve layers: seven on the request path (`console/e2e.py:44#PATH`) and five watching layers (`console/e2e.py:45#WATCH`) | None dedicated (nearest P10, P13, P16) | Act 6 page, beats 6.1 to 6.8 |
| 7 (`console/catalog.py:742#Act`) | Every role, the agent's front door, and the bill | Priya, Wes, Tara, Carla and Ian, plus the operator tab | The front door plus walls 1 to 3 per role; cost controls | None of the 18 proofs | Act 7 page: 7.1 to 7.4 and the per-persona tabs |

Agent beats always run as the operator. The gateway-level job kinds (`gateway`, `xpia`, `burst`) can run as another user (`console/jobs.py:420#PERSONA_KINDS`), and so can the Act 6 traces that use no agent: 6.3 is pinned to Priya and the `follow` traces take the "Acting as" persona (`console/e2e.py:1230-1240#persona_for`). The operator mirrors Wes (Falcon only) and Tara (trader) (`console/jobs.py:60-61#WHO_NOTE`); the helper that does the mirroring is a script in the `identity` folder that copies a persona's roles onto the signed-in operator (`README.md:88#mirrors`).

`Diagram: docs/diagrams/08-scenarios-acts-1-7.excalidraw`

### 9.2 Act 1: Same question, two answers

**What this section proves.** One question about a confidential deal, asked by a user who is not cleared for it, gets two opposite answers from the same Foundry runtime and the same model. The only variable is how the tool call is authenticated. On the legacy path a shared subscription key carries no user, so nothing in the path can say no and the deal comes back. On the governed path every call carries the signed-in user's Entra token, so three independent layers can decide on that user: the gateway (wall 1), the tool server (wall 2) and Azure Storage (wall 3). The two agents are defined side by side in code: a legacy agent with one keyed tool and a governed agent with five per-user tools (`console/catalog.py:249#Act`, `src/agent/abw_agents.py:142-152#poc_tools`, `src/agent/abw_agents.py:119-139#wall_desk_tools`).

#### 9.2.1 Act overview

**Purpose.** Show with real calls what an agent does when its tools identify the user and when they do not, and show where the proof of "who read what" lives. The act has four beats: 1.1 the legacy agent leaks, 1.2 the governed agent is told the truth by the token, 1.3 the same person reads the deal they are cleared for, 1.4 the model is removed and the wall still refuses.

**Actors and tokens** (section 6 owns the token mechanics; this table only says which credential rides each hop in this act):

| Beat | Console action | Credential used to reach Foundry | What the tool call carries to APIM | What the MCP server sees | What Storage sees |
|------|----------------|----------------------------------|------------------------------------|--------------------------|-------------------|
| 1.1 legacy agent | `agent_run.py --agent abw-poc-legacy --via direct` | The operator's own Azure CLI sign-in, read from the CLI's token cache (`src/agent/ask.py:74-105#AzCliCacheCredential`). It authenticates the operator to Foundry only. | Header `Ocp-Apim-Subscription-Key` with the shared key stored in the custom-keys connection `mcp-legacy-key`. No Entra token, no `Authorization` header. | Nothing about a user: no authentication middleware, no caller, audit reason `no_user_context` | The legacy server's user-assigned managed identity, a service principal, not a person |
| 1.2 and 1.3 governed agent | `agent_run.py --agent abw-wall-desk` | The same operator sign-in | The per-user OAuth access token that Foundry stored for the operator when consent was given to connection `mcp-wall-oauth`: delegated, scope `Tools.Read`, `aud` claim = the wall API, `roles` claim from the operator's app-role assignments (`scripts/foundry-connections.ps1:59-66#specs`) | The verified claims as a `Caller`: `oid`, `upn` (from `preferred_username`), `tid`, `roles`, `scopes` (from `scp`), `azp`, `aud` and `jti` (from `uti` or `jti`) (`src/mcp/abw_mcp/auth.py:30-41#Caller`, `src/mcp/abw_mcp/auth.py:159-170#Caller`) | A token the wall server obtained on behalf of the user (OBO) for the Storage scope `user_impersonation`, so Storage names the person |
| 1.4 raw gateway call | `run_gateway`, no model | The console's own token for the wall API: for the operator a delegated token minted through the Azure CLI public client, for a persona the `abw-test-client` public client with a device-code sign-in (`demo/mcpclient.py:76-86#acquire_token_silent`, `demo/mcpclient.py:88-107#persona_token`, `console/jobs.py:428-438#token_for`) | Same as 1.2 | Same as 1.2 | Nothing: the tool refuses before any Storage call |

**Preconditions.**

1. The platform is deployed, the two agents are published and the six project connections exist: five OAuth identity-passthrough tools plus the keyed legacy tool (`scripts/foundry-connections.ps1:59-66#specs`, `scripts/foundry-connections.ps1:87-89#oauth2`, `scripts/foundry-connections.ps1:91-95#Ocp-Apim-Subscription-Key`).
2. The operator has run `az login`; the console reads that sign-in and maps a missing sign-in to a plain "not signed in" message (`console/jobs.py:163-173#friendly`, `console/agent_run.py:155-157#credential_unavailable`).
3. The operator mirrors Wes (Falcon only) and Tara (trader) roles (`README.md:88#mirrors`). Apply that role baseline before the first consent: Foundry keeps the token it is handed at consent for its whole life (Entra lifetimes are 60 to 90 minutes), so a role-less token leaves the agent with empty tool lists until it expires (`DESIGN.md:226#Consent`, `DESIGN.md:223#Foundry`).
4. Consent has been given once per connection. If not, `agent_run.py` emits a `consent` line and exits with code 3, and the console shows "One-time consent needed" with the link (`console/agent_run.py:126-131#oauth_consent_request`, `console/jobs.py:760-767#consent_required`).
5. The kill switch is released and the client allow-list is at baseline: the job manager refuses gateway and agent jobs while the kill switch is engaged, and refuses to run two disruptive jobs at once (`console/jobs.py:503-533#killEngaged`, `console/jobs.py:480-493#conflicts`).

#### 9.2.2 Beat 1.1: The PoC everyone builds

**Purpose.** Show the "before" picture: an agent whose only tool authenticates with one shared key. A user who is not cleared for Project Orion asks about Orion and gets it. Nothing fails, nothing is blocked, and no layer even records who asked. Provenance: Implemented (agent, server, policy), Configured (the keyed connection and the broad storage role).

**Sequence.**

1. Browser -> console: the "Run the legacy agent" button posts `{"kind":"agent","params":{"agent":"abw-poc-legacy","prompt":"orion","approve":"yes"},"beat":"1.1"}` to `POST /api/jobs` (`console/server.py:128-135#api_jobs_start`, beat definition `console/catalog.py:253-270#abw-poc-legacy`). The job manager validates the parameters and starts a worker thread (`console/jobs.py:563-593#validate`, `console/jobs.py:503-533#start`).
2. `run_agent` expands the prompt key `orion` through the prompt table to the sentence "Summarize the key terms in the Project Orion deal documents." (`console/catalog.py:33-42#PROMPTS`, `console/jobs.py:830-841#PROMPTS`).
3. `agent_once` forces the direct path for the legacy agent, because the legacy PoC is the "before" picture and must not pass any front door, and spawns the child process `agent_run.py --agent abw-poc-legacy --approve yes --via direct "<prompt>"` (`console/jobs.py:719-721#legacy`).
4. Child -> Foundry: `agent_run.py` builds the operator credential, creates an `AIProjectClient` and calls `responses.create` with `extra_body={"agent_reference": {"name": "abw-poc-legacy", "type": "agent_reference"}}`. The token on this hop is the operator's Entra token for the Foundry project endpoint, nothing else (`console/agent_run.py:83-87#build_credential`, `console/agent_run.py:107-119#with_raw_response`).
5. Foundry loads the stored agent definition: instructions `POC_INSTRUCTIONS` and exactly one MCP tool, `legacy`, bound to connection `mcp-legacy-key`, `require_approval="never"`, with no `allowed_tools` filter, so every tool the server lists is callable (`src/agent/abw_agents.py:142-152#poc_tools`, `src/agent/abw_agents.py:51-54#POC_INSTRUCTIONS`). Provenance: Implemented.
6. Foundry tool runtime -> APIM: JSON-RPC `initialize`, `tools/list` and `tools/call` to `<apim-gateway-url>/legacy/mcp` with header `Ocp-Apim-Subscription-Key: <shared-key>` copied from the custom-keys connection. There is no `Authorization` header and therefore no user (`scripts/foundry-connections.ps1:91-95#Ocp-Apim-Subscription-Key`). Provenance: Platform behaviour for the tool runtime.
7. APIM legacy API: `subscriptionRequired: true` with key header `Ocp-Apim-Subscription-Key`, path `legacy`, backend `be-mcp-legacy`. The platform checks the key against the subscription `sub-abw-legacy-poc` before any policy runs (`infra/05-apim-apis.bicep:169-193#subscriptionRequired`, `infra/05-apim-apis.bicep:204-213#legacySub`).
8. APIM legacy policy: `rate-limit-by-key` allows 120 calls per 60 s counted per subscription id (caller IP if there is no subscription), then sets `x-abw-request-id` from the APIM request id and `x-abw-gateway: apim-legacy`. There is no `validate-jwt`, no `abw-deny` and no decision trace (`infra/apim/policies/mcp-legacy.policy.xml:6-15#rate-limit-by-key`).
9. APIM -> legacy Container App over the internal backend (`infra/05-apim-apis.bicep:108-118#beLegacy`).
10. Legacy MCP server middleware: the branch that installs `BearerAuthMiddleware` is skipped for the legacy server, so the context variable `current_caller` keeps its default of None; only `RequestContextMiddleware` runs and takes the request id from `x-abw-request-id` first, then `x-request-id`, `x-ms-request-id` and `traceparent`, and makes one up if none is present (`src/mcp/abw_mcp/app.py:241-253#legacy`, `src/mcp/abw_mcp/auth.py:25#current_caller`, `src/mcp/abw_mcp/auth.py:173-189#RequestContextMiddleware`).
11. Registry: the legacy registry is built with `default_reason="no_user_context"` and all five tools use `allow_all`, so `tools/list` returns everything and `tools/call` cannot be refused for lack of a role (`src/mcp/abw_mcp/app.py:60#default_reason`, `src/mcp/abw_mcp/servers/legacy.py:114-120#build_tools`, `src/mcp/abw_mcp/registry.py:94-96#allow_all`).
12. Handler -> Storage: `get_deal_document` maps `ORION-001` to container `wall-orion` (research notes `RN-...` go to `research-public`) and reads it with `use_user_token=False`, which selects the server's own `ManagedIdentityCredential` instead of an OBO credential (`src/mcp/abw_mcp/servers/legacy.py:69-83#use_user_token`, `src/mcp/abw_mcp/data.py:57-71#managed_identity_credential`). The blob request carries `x-ms-client-request-id` equal to the request id (`src/mcp/abw_mcp/data.py:24-28#downstream_request_id`).
13. Storage RBAC: the legacy identity holds Storage Blob Data Reader on the whole storage account, described in a template comment as the "typical POC" legacy identity, broad on purpose, so the read succeeds on every container, including `wall-orion` (`infra/03-platform.bicep:569-578#raLegacyBlob`). Wall 3 never gets a person to judge.
14. Result and audit: the payload receives `request_id`, and one audit event `tool_call` is written with `decision` allow, `reason` `no_user_context`, `obo` false, empty user fields, empty roles and downstream storage status 200, to the Container Apps console log and to the append blob in container `worm-audit` (`src/mcp/abw_mcp/registry.py:195-220#setdefault`, `src/mcp/abw_mcp/audit.py:178-216#build_event`, `src/mcp/abw_mcp/audit.py:54-102#AppendBlobAuditSink`).
15. Foundry -> child process -> console: each `mcp_call` output item becomes a `call` line with `decision`, `reason` and `request_id` lifted from the tool text by regular expression; `agent_once` judges it and `legacy_outcome` re-labels a successful call as `leak` or `unchecked`, so it can never show as plain "allowed" (`console/agent_run.py:42-70#show_items`, `console/jobs.py:743-759#legacy_outcome`, `console/jobs.py:204-215#legacy_outcome`).

**Success outcome.** The tool result the model receives (shape from `src/mcp/abw_mcp/servers/legacy.py:78-83#doc_id`):

```json
{
  "doc_id": "ORION-001",
  "title": "<first markdown heading of the document>",
  "content": "<first 8000 characters of the document>",
  "request_id": "<request-id>"
}
```

The console event for that call (keys from `console/jobs.py:757-759#excerpt`; `decision` is null because a successful tool result has no `decision` key, and the verdict block comes from `legacy_outcome`):

```json
{
  "type": "call", "server": "legacy", "tool": "get_deal_document",
  "args": "{\"doc_id\": \"ORION-001\"}", "request_id": "<request-id>",
  "decision": null, "reason": "", "excerpt": "<result, cut for display>",
  "leak": ["<deal id>", "<amount>", "<party>"], "attack": "",
  "verdict": "leak", "wall": null, "title": "It answered - to anyone",
  "plain": "No user, no role, no check: the shared key handed confidential material to whoever asked. ...",
  "lights": {"foundry": "warn", "apim": "warn", "m-legacy": "warn", "data": "warn"}
}
```

The card shows the pill "Shared key, no user" (`console/jobs.py:735-741#LEGACY_WHO_NOTE`), one badge per tool call (red LEAKED, or amber NO CHECK when `leak_terms` finds nothing to highlight) and never a green one. The scrubbed agent-run evidence has this shape: `{"ts","agent":"abw-poc-legacy","as":"az-cli (signed-in operator)","prompt","turns":[{"id":"resp_<id>","items":["mcp_list_tools","mcp_call","mcp_call","mcp_call","mcp_call","message"]}],"answer","response_id":"<response-id>","status":"completed","failure":null,"seconds":<n>}`. The alternative button "Deterministic: raw legacy call" skips Foundry: `run_gateway` reads the shared key from APIM through ARM and calls `get_deal_document` for `ORION-001` over HTTP in about one second (`console/jobs.py:452-463#legacy_key`, `console/azure_probe.py:222-232#legacy_key`, `demo/mcpclient.py:147-165#legacy_key`).

**Failure or denial outcomes.** There is no denial on this path by design. The failures that can occur are: a missing or wrong subscription key gives APIM's own 401 (shape "Missing key" in 9.1.7), which the console cannot trigger because the key comes from the connection; more than 120 calls in 60 s per key gives a 429 from `rate-limit-by-key`; an unknown document id gives a soft `ERROR` result `NOT_FOUND` with reason `blob_not_found` (`src/mcp/abw_mcp/data.py:57-71#blob_not_found`); and an operator who is not signed in to Azure gets exit code 5 and the "Not signed in to Azure" message. If the model declines to call any tool the card shows no call badge at all.

**Evidence produced.**

| Evidence | Where it lands | How to retrieve it |
|----------|----------------|--------------------|
| Gateway row: `ResponseCode` 200, `ApimSubscription` set, no `UserOid`, `Outcome` `other` because the legacy policy emits no decision trace | `ApiManagementGatewayLogs`; `AuthenticationMethod` `subscription-key` in `ApiManagementGatewayMCPLog` | `AbwGateway(24h) \| where RequestId == '<request-id>'` (`observability/kql/AbwGateway.kql:1-12#AbwGateway`, `docs/PROOF-PLAYBOOK.md:166#ApiManagementGatewayMCPLog`) |
| MCP audit row: `Server` legacy, `Event` `tool_call`, `Decision` allow, `Reason` `no_user_context`, empty `UserUpn`, `OnBehalfOf` false, `Roles` empty, `DataClass` mixed | Container Apps console log and blob in `worm-audit` | `AbwMcpAudit(24h) \| where RequestId == '<request-id>'` (`observability/kql/AbwMcpAudit.kql:1-8#ContainerAppConsoleLogs`) |
| Storage row: `GetBlob` on `wall-orion`, `RequesterUpn` empty, `RequesterObjectId` = the legacy managed identity, `ClientRequestId` = request id | `StorageBlobLogs` | Step 4 of `AbwIdentityChain('<request-id>')` (`observability/kql/AbwIdentityChain.kql:39#StorageBlobLogs`) |
| Foundry row: agent name `abw-poc-legacy`, tool result returned to the model | `AppGenAIContent` | Step 1 of the same chain |
| Sentinel incident ABW-003 "Tool call on the legacy shared-key path (no user identity)", Medium, fires on `Server == 'legacy'` with empty user fields; allow up to about 15 minutes | `SecurityIncident` | `observability/sentinel/abw-003-legacy-no-identity.kql:12#legacy` and `docs/PROOF-PLAYBOOK.md:404#ABW-003` |

`AbwIdentityChain('<request-id>')` for this beat returns four rows whose Actor column reads: the agent name, blank, blank, and the legacy managed identity's object id. **Why:** that column is the whole point of the act; nobody was asked, and a robot with a read role on every container read Orion.

**How the console runs it.** Beat definition `console/catalog.py:253-270#abw-poc-legacy`, runner `agent` -> `run_agent` -> `agent_once` (`console/jobs.py:830-841#PROMPTS`, `console/jobs.py:717-760#agent_once`). The alternative button runs `run_gateway` with `server: legacy`, which says "Calling legacy.get_deal_document with the shared POC key: no Entra token, no user, no role - the way most PoCs ship." and finishes with "Leaked" or "Answered, unchecked" plus `HTTP <status>` (`console/jobs.py:843-860#run_gateway`).

**How demo/prove.py proves it.** Proof P08 calls the legacy API with the key and no token for `ORION-001`, expects HTTP 200 with Orion markers and records the request id as `legacy_leak`; it then asks the governed wall server for the same document and expects DENIED, and runs both agents, expecting the legacy agent to summarise Orion and the governed agent to refuse and leak nothing (`demo/prove.py:763-779#legacy_leak`).

**Failure modes and what the presenter should say.** Amber NO CHECK on a call is normal, because the console highlights only deal ids, parties and amounts; it is amber, never green, because nothing checked. The agent's wording changes from run to run; the tool lines and badges do not. The raw alternative shows fewer hops because no model is involved. Say: "Nothing failed and nothing was blocked, because nothing in this path decides. The system did exactly what it was built to do" (`docs/TALK-TRACK.md:140-152#v0`).

#### 9.2.3 Beat 1.2: The governed agent, same question

**Purpose.** Same runtime, same model, same question as 1.1; only the tools differ. The tool call now carries the user's own token, so the wall server can read the user's wall roles from it. The first call the agent makes is not a data read: `list_my_wall_crossings` is answered from the roles in the token. The model then declines Orion in its own words. That refusal is the model's reasoning and is not the control; the control is shown in 1.4. Provenance: Implemented (tools, roles, registry), Platform behaviour (tool runtime, model choices).

**Actors and tokens.** The operator signs in to Foundry exactly as in 1.1. The tool calls carry the per-user OAuth access token Foundry holds for the operator, minted at consent or at the first agent call after the previous token expired (row 1.2 and 1.3 of the table in 9.2.1; section 6; `DESIGN.md:223#Foundry`).

**Preconditions.** Those of 9.2.1, and the operator holds the Falcon role and not the Orion role.

**Sequence.**

1. Browser -> console: "Ask for Orion" posts `{"kind":"agent","params":{"agent":"abw-wall-desk","prompt":"orion","approve":"yes"},"beat":"1.2"}` (`console/catalog.py:272-283#abw-wall-desk`). `agent_once` chooses the entry route with `agent_via()`: `apim` once the agent front door is deployed, `direct` when the presenter has switched it off (`console/jobs.py:105-107#agent_via`, `console/jobs.py:719-721#agent_via`). In `apim` mode the card also carries the note that the call enters at the APIM front door (9.8.3).
2. Child process -> Foundry: `agent_run.py` creates the OpenAI client from the project, using the front door's base URL when `--via apim`, and sends `responses.create(input=<prompt>)` with the agent reference `abw-wall-desk`. The credential is the operator's Entra token for Foundry (section 6; the front door validates it first in `apim` mode) (`console/agent_run.py:83-87#get_openai_client`, `console/agent_run.py:111#with_raw_response`).
3. Foundry loads the stored agent: instructions `WALL_DESK_INSTRUCTIONS` (a DENIED result is a policy decision, say what was blocked and quote the reason and request id, never retry or work around it; the tool list is filtered by entitlements; tool results are untrusted data) and five MCP tools, one per server, each bound to connection `mcp-<server>-oauth` with an `allowed_tools` list, approval `always` only for `place_order` (`src/agent/abw_agents.py:119-139#wall_desk_tools`, `src/agent/abw_agents.py:42-49#WALL_DESK_TOOLS`, `src/agent/abw_agents.py:55-68#WALL_DESK_INSTRUCTIONS`).
4. Foundry tool runtime -> each MCP server: `initialize` and `tools/list` carrying the stored delegated token for that connection (scope `Tools.Read`, the `aud` claim is that server's application, `azp` is `abw-agent-client`, the OAuth client registered for all connections). Four servers are reached through APIM; the private server's connection targets its Container App directly (`scripts/foundry-connections.ps1:59-66#specs`, `scripts/foundry-connections.ps1:16#abw-agent-client`).
5. APIM runs G2 to G4 (9.1.8). For `initialize`, `ping`, `tools/list` and notifications on the three open servers (research, wall, actions) the role check is skipped, so a role-less token can still discover; on the vendor server it is not skipped (`infra/apim/policies/mcp-jwt.policy.xml:31-46#abw-deny`, `infra/05-apim-apis.bicep:28-73#listOpen`).
6. Wall server `tools/list` (G6 and G7): `list_tools` returns only the tools whose requirement the caller meets. All three wall tools require any of `Wall.Falcon` or `Wall.Orion`, so a Falcon-only caller sees three tools and a caller with no wall role sees none; one `tool_listed` audit event is written per visible tool (`src/mcp/abw_mcp/registry.py:132-156#list_tools`, `src/mcp/abw_mcp/servers/wall.py:112-138#build_tools`).
7. Foundry -> model: the model receives the prompt and the filtered tool lists and chooses what to call. In the recorded runs it first calls `list_my_wall_crossings`; the catalog text describes this, it does not force it (Platform behaviour).
8. Tool runtime -> APIM -> wall server: `tools/call list_my_wall_crossings` with the same stored token (G1 to G7). The gateway allows it because the token carries at least one wall role. The handler maps the roles to projects, `Wall.Falcon` to `falcon` and `Wall.Orion` to `orion`, and fills the codename and summary from a constant table; nothing is read from Storage or Search (`src/mcp/abw_mcp/servers/wall.py:29-36#caller_projects`, `src/mcp/abw_mcp/servers/wall.py:50-59#list_my_wall_crossings`).
9. Registry result and audit (G9): `request_id` is added to the payload and one `tool_call` audit event is written with `decision` allow, empty `reason`, the user's `user_upn` and `user_oid`, `roles` `["Wall.Falcon"]`, `data_class` wall, downstream `{"service":"token","target":"roles","status":200}` and `obo` true (the `ToolOutcome` default; see Findings) (`src/mcp/abw_mcp/registry.py:195-220#setdefault`, `src/mcp/abw_mcp/registry.py:31-38#ToolOutcome`).
10. Model -> answer: the model sees Falcon only and says the user is not crossed on Orion, bounded by the instruction not to work around a denial. If it tries `search_deal_documents` or `get_deal_document` for Orion anyway, step 8 runs against a tool that refuses at `_require_project`; the exact denial is in 9.2.5.
11. Child process -> console: each `mcp_call` item becomes a `call` event. For `list_my_wall_crossings` the console re-titles the green card "The wall's answer, read from the token: cleared on Project Falcon" and opens it by default; the final `answer` event carries the model text, seconds, token counts, `via`, rounds and the front door's request ids (`console/agent_run.py:42-70#show_items`, `console/jobs.py:743-759#crossings_view`, `console/jobs.py:218-226#crossings_view`, `console/jobs.py:792-801#gateway_ids`).

**Success outcome.** Tool result (shape from `src/mcp/abw_mcp/servers/wall.py:50-59#list_my_wall_crossings`):

```json
{
  "crossings": [
    {"project": "falcon", "codename": "Project Falcon", "summary": "Project Falcon synthetic confidential M&A mandate."}
  ],
  "request_id": "<request-id>"
}
```

Console `call` event: `server` wall, `tool` `list_my_wall_crossings`, `verdict` allowed, `title` "The wall's answer, read from the token: cleared on Project Falcon", `open` true, lights `user`, `entra`, `foundry`, `apim`, `m-wall` and `data` all `ok` (`data` is lit because lights are per server, although this tool reads no data) (`console/catalog.py:173-190#lights_for_call`). The final event is `{"type":"answer","text":"<model text>","seconds":<n>,"tokens_in":<n>,"tokens_out":<n>,"status":"completed","via":"apim","rounds":<n>,"gateway_ids":["<request-id>"]}` (the `tokens_remaining` field is present when the front door reports it).

**Failure or denial outcomes.**

| Situation | What happens | Shape and wall |
|-----------|--------------|----------------|
| The model calls an Orion tool anyway | The wall tool refuses at `_require_project` | Soft denial, reason `project_not_in_token_roles`, red DENIED, wall 2, audit `wall_violation_attempt` (9.2.5) |
| The operator token has no wall role (baseline applied after consent) | `tools/list` for wall is empty, the model says the user's permissions do not include it; if it calls the tool anyway the gateway refuses | Gateway 403 `missing_role`, wall 1; Foundry aborts the run and the console shows "The agent failed closed", a card written for a revoked user, so explain the missing role in your own words (`console/catalog.py:141-170#explain_failure`; the same card function as 9.5 beat 4.5). Provenance: Inferred, with no recorded agent run for a role-less operator in this repo |
| Consent not given | `agent_run.py` exits with code 3 | "One-time consent needed" card with the link (`console/jobs.py:760-767#consent_required`) |
| Stored token expired or roles changed | Foundry keeps the old token for its whole life (Entra lifetimes are 60 to 90 minutes), so a role change reaches the agent late | `DESIGN.md:223#Foundry` |

**Evidence produced.** Gateway rows for `initialize`, `tools/list` and `tools/call` on the wall API and `tools/list` rows for the other servers; MCP audit events `tool_listed` (three for the wall) and one `tool_call` for `list_my_wall_crossings` with `UserUpn`, `Roles` and `OnBehalfOf`; a Foundry row for agent `abw-wall-desk`. There is no Storage row, because nothing was read, and no new Entra sign-in, because Foundry reuses the token it already holds, which it minted at consent or at the first agent call after the previous token expired (`DESIGN.md:223#Foundry`). Retrieve with `AbwIdentityChain('<request-id>')` or `AbwMcpAudit(24h) | where Server == 'wall'` (`observability/kql/AbwMcpAudit.kql:1-8#ContainerAppConsoleLogs`).

**How the console runs it.** Beat definition `console/catalog.py:272-283#abw-wall-desk`; runner `agent` -> `run_agent` -> `agent_once`; `explain`, `judge` and `crossings_view` produce the card (9.1.6).

**How demo/prove.py proves it.** P03 checks that `list_my_wall_crossings` answers and shows Falcon (`demo/prove.py:638-653#list_my_wall_crossings`). P02 proves the mechanism behind the role-filtered tool list: a caller with no roles sees zero tools on the wall, actions and research servers, and a call anyway gets 403 `missing_role` (`demo/prove.py:607-632#missing_role`). P08 asks this agent the Orion question and requires that its answer leaks nothing (`demo/prove.py:763-779#safe`).

**Failure modes and what the presenter should say.** The title says the call is allowed "from the token"; green means the lookup worked, not that the user is cleared for Orion. The refusal wording changes from run to run. Say: "The model is not the control. The token is" (`console/catalog.py:280#sales`). If the card is red or empty for a person who should be cleared, suspect the baseline order or an expired stored token (`DESIGN.md:226#Consent`). The catalog and the playbook call this lookup "open to every signed-in user"; the code requires a wall role (Findings F1).

#### 9.2.4 Beat 1.3: Same person, the deal they ARE cleared for

**Purpose.** Same user, same agent, different deal. The wall server now reads the document, and it reads it with a token that names the user, so Azure Storage decides too. The answer depends on who is asking, not on how well the prompt was written. Provenance: Implemented (handlers, OBO), Configured (the group role on one container), Platform behaviour (Storage RBAC).

**Actors and tokens.** As 1.2 up to the wall server. Inside the wall server a second token is obtained: the server exchanges the caller's access token for a token for Azure Storage with the scope `user_impersonation`, so Storage sees the user and the application `abw-mcp-wall`, not a service identity (section 6).

**Preconditions.** Those of 9.2.1; the operator is a member of the Falcon group, which holds Storage Blob Data Reader on container `wall-falcon` only.

**Sequence.**

1. Browser -> console: "Ask for Falcon" posts the agent job with `prompt` `falcon`, expanded to "Summarize the key terms in the Project Falcon deal documents." (`console/catalog.py:284-302#falcon`, `console/catalog.py:33-42#PROMPTS`). Steps 1 to 6 of 9.2.3 run unchanged.
2. Model -> tools: the model typically calls `search_deal_documents` with `project` `falcon` and then `get_deal_document` with `doc_id` `FALCON-001`; the instructions tell it that codes are lowercase and exact (`src/agent/abw_agents.py:55-68#WALL_DESK_INSTRUCTIONS`).
3. Tool runtime -> APIM -> wall server with the stored token: G1 to G7 as in 9.2.3 step 8; the second verification of the token is at G6.
4. `search_deal_documents`: `_require_project` passes, then the handler searches the index with the filter `classification eq 'wall' and project eq 'falcon'`, selecting id, title, summary and updated, using an on-behalf-of token for the Search scope `user_impersonation`; the payload is `{"project","results":[{"doc_id","title","summary","updated"}]}` (`src/mcp/abw_mcp/servers/wall.py:62-85#search_deal_documents`, `src/mcp/abw_mcp/data.py:73-97#search_documents`).
5. `get_deal_document`: the project is the lowercase prefix of the document id, `_require_project` passes, the container is `wall-falcon` and the blob is `FALCON-001.md` (`src/mcp/abw_mcp/servers/wall.py:88-109#get_deal_document`).
6. On-behalf-of exchange (G8): `read_blob_text` asks the broker for a credential for the Storage scope `https://storage.azure.com/user_impersonation`. The broker's confidential client authenticates with a client assertion, which is a token the server's user-assigned managed identity obtains for `api://AzureADTokenExchange/.default`, and presents the caller's access token as the user assertion (`src/mcp/abw_mcp/data.py:57-71#user_impersonation`, `src/mcp/abw_mcp/data.py:191-195#_obo_credential`, `src/mcp/abw_mcp/obo.py:57#client_assertion`, `src/mcp/abw_mcp/obo.py:64-65#acquire_token_on_behalf_of`, `src/mcp/abw_mcp/obo.py:77-78#_get_client_assertion`). Entra returns a token for Storage that names the user; a failed exchange becomes the error reason `obo_failed:<code>` (`src/mcp/abw_mcp/registry.py:176-190#obo_failed`).
7. MCP server -> Storage: `GetBlob` on `wall-falcon/FALCON-001.md` with the user's token and the option `client_request_id` set to the request id, which is sent as `x-ms-client-request-id` and recorded by Storage (`src/mcp/abw_mcp/data.py:201-205#client_request_id`).
8. Storage authorizes with Azure RBAC on the user's identity: the Falcon group holds Storage Blob Data Reader on that one container; nobody holds a role on `wall-orion` except service identities (`infra/03-platform.bicep:628-636#raFalconBlob`). The read succeeds.
9. Result and audit (G9): the payload is `{"doc_id","project":"falcon","title":<first heading>,"content":<first 8000 characters>}` plus `request_id`; the audit event has `decision` allow, `obo` true, downstream `{"service":"storage","target":"wall-falcon","status":200}`.
10. Model -> console: the model summarises the document; the card shows two green calls with "Allowed - every layer in the path agreed" and the answer. The on-behalf-of proof is not on the card; it is in the logs (Act 5.2, 9.6).

**Success outcome.**

```json
{
  "doc_id": "FALCON-001",
  "project": "falcon",
  "title": "<first markdown heading of the document>",
  "content": "<first 8000 characters of the document>",
  "request_id": "<request-id>"
}
```

The console `call` events show `verdict` allowed with lights `user`, `entra`, `foundry`, `apim`, `m-wall` and `data` all `ok`. The alternative button "Quick: raw read of FALCON-001" runs the same call without a model through `run_gateway` in about two seconds and returns the same payload in an `http` event.

**Failure or denial outcomes.**

| Situation | Shape | Wall |
|-----------|-------|------|
| Entitlement drift: the user left the Falcon group after the token was issued; the role claim still says yes | Soft denial `FORBIDDEN`, message "Storage access denied.", reason `storage_rbac_denied`, audit event `wall_violation_attempt`, downstream storage 403 (`src/mcp/abw_mcp/servers/wall.py:93-97#storage_rbac_denied`) | 3: "The data plane said no" |
| The document does not exist | `ERROR` `NOT_FOUND`, reason `blob_not_found`, downstream storage 404 | none |
| The exchange for the Storage token fails | Soft denial `FORBIDDEN` (decision DENIED), message "Unable to acquire downstream user token.", reason `obo_failed:<code>`, audit event `tool_denied`, no Storage call (`src/mcp/abw_mcp/registry.py:179-190#obo_failed`) | none: the console titles the card "Refused" and names no wall |
| The model cannot find the document | The answer says so; no denial | none |

**Evidence produced.** Storage log row `GetBlob` on `wall-falcon` whose `RequesterUpn` is the user, `AuthenticationType` is OAuth, `RequesterAppId` is the wall API's application and `ClientRequestId` equals the request id (`docs/PROOF-PLAYBOOK.md:276#StorageBlobLogs`); Entra non-interactive sign-in rows for the application `abw-mcp-wall` against Azure Storage and Azure AI Search, which are the exchanges themselves; MCP audit rows with `OnBehalfOf` true and downstream status 200; gateway rows with `UserOid`; the container's access-control list showing the Falcon group and service identities only. `AbwIdentityChain('<request-id>')` returns four rows whose Actor column names the user at the MCP and Storage steps (`observability/kql/AbwIdentityChain.kql:39#StorageBlobLogs`).

**How the console runs it.** `console/catalog.py:284-302#falcon`; `agent_once` for the agent button, `run_gateway` for the alternative (`console/jobs.py:843-860#run_gateway`).

**How demo/prove.py proves it.** P03 searches Falcon, reads `FALCON-001` and records the request id as `falcon_ok` (`demo/prove.py:638-653#falcon_ok`). P16 is the sharpest test of the third wall: it removes the user from the Falcon group, polls until the same call returns `storage_rbac_denied` while the Entra role claim is unchanged, then restores the group (`demo/prove.py:962-992#storage_rbac_denied`).

**Failure modes and what the presenter should say.** If the first call is slow, the OBO exchange and the cold model are the cost; the beat is the slowest agent beat of Act 1 (about 40 to 60 seconds). If the agent says it cannot see Falcon tools the baseline was applied after consent (`DESIGN.md:226#Consent`). Say: "The answer depends on who is asking, not on how well the prompt was written. Storage checked the user, not the server" (`console/catalog.py:299#sales`).

#### 9.2.5 Beat 1.4: Take the model out of the loop

**Purpose.** Remove the model and make one raw call to the gateway for the Orion document with the user's token. This is the control itself, independent of any model behaviour. Provenance: Implemented.

**Actors and tokens.** The console's own delegated token for the wall API, scope `Tools.Read`: for the operator, minted through the Azure CLI public client with a silent refresh from its token cache; for a persona selected with "Acting as", the persona's token from the public client `abw-test-client` (device-code sign-in, cached per persona) (row 1.4 of 9.2.1; section 6).

**Preconditions.** The operator holds the Falcon role and not the Orion role; no job conflicts (`console/jobs.py:480-493#conflicts`).

**Sequence.**

1. Browser -> console: "Call the gateway directly" posts `{"kind":"gateway","params":{"server":"wall","tool":"get_deal_document","args":{"doc_id":"ORION-001"},"tag":"orion"},"beat":"1.4"}` (`console/catalog.py:303-314#orion`).
2. `run_gateway` says "Calling wall.get_deal_document through the APIM gateway with the signed-in user's Entra token. No key anywhere." (or "as <persona label>") and calls `call_gateway` (`console/jobs.py:843-852#run_gateway`).
3. `call_gateway` -> `token_for` -> `mcpclient.call_tool`: the token is acquired for the wall API with scope `Tools.Read` and a JSON-RPC `tools/call` is posted to `<apim-gateway-url>/wall/mcp` (`console/jobs.py:452-463#call_gateway`, `console/jobs.py:428-438#token_for`, `demo/mcpclient.py:76-86#acquire_token_silent`, `demo/mcpclient.py:88-107#persona_token`, `demo/mcpclient.py:124-141#rpc`).
4. APIM G2 to G4: `validate-jwt` passes; `abw-deny` finds the `oid` not revoked, the `azp` on the allow-list, `Tools.Read` in `scp`, and the role `Wall.Falcon`, which satisfies "any wall role"; decision allow, reason ok. The gateway cannot tell which project the document belongs to, so wall 1 lets this call through by design (`infra/apim/policies/mcp-jwt.policy.xml:31-46#abw-deny`).
5. MCP G6 and G7: the token is verified again, the requirement `require_any_role` passes and the arguments are validated against `^(FALCON|ORION)-\d{3}$` (`src/mcp/abw_mcp/registry.py:158-175#call_tool`, `src/mcp/abw_mcp/servers/wall.py:25-26#GetDealDocumentArgs`).
6. Handler: the project is `orion`; `_require_project` finds it absent from `caller_projects` and raises `FORBIDDEN` "Caller is not crossed on that project." with reason `project_not_in_token_roles` and audit event `wall_violation_attempt`. No on-behalf-of exchange and no Storage call happen (`src/mcp/abw_mcp/servers/wall.py:39-47#_require_project`).
7. Registry: `_tool_error_result` builds the soft denial of 9.1.7 and writes the audit event with `decision` deny, `roles` `["Wall.Falcon"]` and `obo` true (the default; no exchange was made, see Findings) (`src/mcp/abw_mcp/registry.py:238-270#_tool_error_result`, `src/mcp/abw_mcp/registry.py:273-292#_error_payload`).
8. Console: `http_result` reads the request id from the structured content, the decision and the reason; `judge` returns verdict denied, wall 2, title "The MCP server said no", and the lights `user` ok, `entra` ok, `apim` ok, `m-wall` deny (Foundry is not drawn for a direct call) (`console/jobs.py:229-253#http_result`, `console/catalog.py:47-51#project_not_in_token_roles`).
9. `run_gateway` stores the request id under the tag `orion` for Act 5, says "Request id <request-id> remembered for Act 5." and finishes with "Refused: HTTP 200 DENIED project_not_in_token_roles" (`console/jobs.py:854-859#tags`).

**Success outcome** (the expected result of this beat is the denial). HTTP 200 with the JSON-RPC result below, and the console event derived from it:

```json
{
  "jsonrpc": "2.0", "id": 1,
  "result": {
    "isError": false,
    "structuredContent": {
      "decision": "DENIED", "error": "FORBIDDEN",
      "message": "Caller is not crossed on that project.",
      "reason": "project_not_in_token_roles", "request_id": "<request-id>",
      "note": "Blocked by policy and written to the audit log. Tell the user what was blocked and the reason code; do not retry, rephrase or look for a workaround."
    }
  }
}
```

```json
{
  "type": "http", "server": "wall", "tool": "get_deal_document", "args": "{\"doc_id\": \"ORION-001\"}",
  "status": 200, "seconds": 2.0, "decision": "DENIED", "reason": "project_not_in_token_roles",
  "request_id": "<request-id>", "verdict": "denied", "wall": 2, "title": "The MCP server said no",
  "lights": {"user": "ok", "entra": "ok", "apim": "ok", "m-wall": "deny"}
}
```

**Failure or denial outcomes.** A persona with no wall role (Priya, Tara or Ian chosen with "Acting as"; `console/personas.py:53-57#tara`) is refused earlier: Gateway 403 with reason `missing_role`, wall 1, title "The gateway said no", and no MCP row. A token minted for an application that is not on the allow-list gets Gateway 403 `client_not_allowed` (9.5, beat 4.4). A missing or expired token gets Gateway 401 (9.7, beat 6.1). A Falcon document id returns the document (beat 1.3). Shapes: 9.1.7.

**Evidence produced.** `AbwIdentityChain('<request-id>')` returns two rows: the gateway (`POST wall`, HTTP 200 allowed) and the MCP server (`wall.get_deal_document [wall_violation_attempt]`, `deny (project_not_in_token_roles)`, `roles=["Wall.Falcon"]`); there is no Foundry row and no Storage row (`docs/PROOF-PLAYBOOK.md:315#ABW-001`). Sentinel incident ABW-001 "Information-barrier violation attempt (Wall MCP)" (High) fires on the `wall_violation_attempt` event and carries the request id in the alert details (`docs/PROOF-PLAYBOOK.md:404#ABW-001`). Entra: nobody holds the `Wall.Orion` role on the wall application. The remembered request id feeds beat 5.1 (9.6).

**How the console runs it.** `console/catalog.py:303-314#orion` -> `run_gateway` -> `call_gateway` -> `http_result` (steps 1 to 9).

**How demo/prove.py proves it.** P03 asks for `ORION-001` and requires `decision == DENIED` with reason `project_not_in_token_roles` and a request id, records it as `orion_denied`, marks Sentinel traffic for ABW-001, and requires that an Orion search is denied too, so the existence of the project does not leak (`demo/prove.py:638-653#orion_denied`). P08 repeats the Orion read against the governed wall server and requires DENIED (`demo/prove.py:763-779#gov`).

**Failure modes and what the presenter should say.** The card reads "Refused: HTTP 200 DENIED". HTTP 200 is the gateway letting a valid token through; DENIED is the tool refusing before it touched Storage. If it shows 403 the operator's role baseline is missing. Say: "It is a control, not a suggestion to the model" (`console/catalog.py:311#sales`).

#### 9.2.6 Act 1 evidence, proofs and presenter summary

| Beat | Layers that decided | Evidence rows | Sentinel | Proof ids |
|------|---------------------|---------------|----------|-----------|
| 1.1 legacy agent leaks | None: nothing could say no | Gateway row (subscription key), MCP row with empty user, Storage row as the legacy identity | ABW-003 (Medium) | P08 |
| 1.2 governed agent, Orion | The model's reasoning; the controls are 1.4 | Gateway rows, MCP `tool_listed` and `tool_call`, no Storage row | none | P02, P03, P08 |
| 1.3 governed agent, Falcon | Gateway, tool server and Storage all say yes | Gateway, MCP with `OnBehalfOf`, Storage row naming the user, Entra exchange rows | none | P03, P16 |
| 1.4 raw call, Orion | Tool server (wall 2) | Gateway row (allowed), MCP deny row, no Storage row | ABW-001 (High) | P03, P08 |

**The side-by-side exhibit.** Run `AbwIdentityChain('<request-id-1.1>')` and `AbwIdentityChain('<request-id-1.3>')`: the first shows the Actor column as the agent, blank, blank and a service identity; the second shows the agent, the user's object id, the user and the user. Then the closing query, which summarises every wall-container read by who did it (`docs/PROOF-PLAYBOOK.md:326#StorageBlobLogs`):

```kusto
StorageBlobLogs
| where TimeGenerated > ago(24h)
| where OperationName == 'GetBlob' and Uri has '/wall-'
| extend Container = extract(@'/(wall-[a-z]+)/', 1, Uri)
| summarize Reads = count(), Last = max(TimeGenerated)
    by Container, Actor = coalesce(RequesterUpn, RequesterObjectId), AuthenticationType, RequesterAppId
| order by Container asc, Reads desc
```

The expected result: `wall-falcon` read by a person with `AuthenticationType` OAuth and `RequesterAppId` equal to the wall API's application; `wall-orion` read only by the legacy service identity. **Why:** the wall server's own managed identity holds no read role on the wall containers, so its reads succeed only as the user; this is the property that makes wall 3 real.

**Why and trade-offs.** The legacy path is the one deliberate non-compliant row on the Azure Policy board and the only path with a broad storage role (`infra/03-platform.bicep:570-578#raLegacyBlob`). The model's refusal in 1.2 is not a control, and 1.4 shows what is. Wall 1 cannot see which project a document belongs to, so it checks only that the caller holds some wall role; the project check is wall 2's job. Entitlement drift is caught only at wall 3 until the stored token expires (`DESIGN.md:223#Foundry`).

**Presenter path** (`docs/TALK-TRACK.md:140-152#v0`): start beat 2.1 first, because its nine requests run in the background for four to six minutes; run 1.1, then 1.2, then 1.3 (the slowest agent beat of Act 1, about a minute) while the Act 2 job runs, then 1.4. Land it: "The wall is not in the prompt. It is a role in Entra, enforced three times: at the gateway, at the tool server, and again by Azure Storage." If asked why the model said that: "A soft denial is HTTP 200 with the decision, the reason and a request id, so the model can explain it honestly."

### 9.3 Act 2: No keys

**What this section proves.** Act 2 turns "there are no keys" from a claim into three things the room can watch. First, Azure Policy answers real attempts to put a key or a public endpoint back: five attempts are refused outright, three are rewritten safe by the tenant's own organisation baseline before this repository's policy even runs, and one compliant request is allowed on purpose (beat 2.1). Second, the Storage request log states how every request authenticated, and no person, agent or app used a key (beat 2.2). Third, the live configuration of Foundry, the data stores and the policy initiative is read back from Azure Resource Manager (ARM) and Resource Graph (beat 2.3). All three beats use the operator's own Azure CLI sign-in; none uses a persona token or the gateway (`console/catalog.py:316-321#act2`, `demo/try-violations.py:65#_cred`, `console/azure_probe.py:73-89#token`).

#### 9.3.1 Act overview

**Purpose.** Show that "no keys" is both enforced and observable. Enforced: Azure Policy at the demo resource group refuses or neutralises every attempt to create a data service with a key or a public endpoint, and every attempt to add a Foundry connection that stores a secret or points at an unapproved MCP server. Observable: a log query and live configuration reads show the same fact from the other side. The act has three beats: 2.1 nine live attacks, 2.2 how every storage request authenticated, 2.3 the live read of the configuration. Beat 2.1 is started first, before Act 1, because it runs four to six minutes in the background and is read when the room arrives at Act 2 or Act 3 (`console/catalog.py:322-334#violations`, `docs/TALK-TRACK.md:142#Start`).

**Actors and tokens** (section 6 owns the mechanics; this table only says which credential each beat uses):

| Beat | Console action | Identity | Token on the wire | Answered by |
|------|----------------|----------|-------------------|-------------|
| 2.1 live | `{"kind":"violations"}` | The operator, signed in with `az login` | A fresh ARM access token for scope `https://management.azure.com/.default`, asked from the Azure CLI by `AzureCliCredential(process_timeout=90)` before every request and sent in an Authorization header carrying the Bearer-scheme access token on every PUT, GET, POST and DELETE (`demo/try-violations.py:65-69#_headers`). The credential does not cache tokens (https://learn.microsoft.com/python/api/azure-identity/azure.identity.azureclicredential?view=azure-python). | ARM (can the operator write here at all), then Azure Policy: the tenant organisation baseline (Modify effects, not in this repository) and the initiative `abw-agent-platform-controls` assigned to the demo resource group (`infra/06-governance.bicep:177-205#assignment`) |
| 2.1 last run | `{"kind":"violations_last"}` | None | None | The console reads the newest result file from the script's evidence folder (`console/jobs.py:1033-1053#run_violations_last`) |
| 2.2 | `{"kind":"kql","params":{"query":"nokeys"}}` | The operator, from the Azure CLI sign-in | A Log Analytics access token for resource `https://api.loganalytics.io`, minted silently from the Azure CLI's token cache with scope `<resource>/.default` and kept by the console until 300 s before expiry (`console/azure_probe.py:73-89#token`, `console/azure_probe.py:165-180#la_query`) | Log Analytics workspace access control; the query runs on the table `StorageBlobLogs` |
| 2.3 | `{"kind":"probes","params":{"ids":["foundry","data","policy"]}}` | The operator, from the Azure CLI sign-in | ARM access tokens by the same silent path; Resource Graph is an ARM endpoint, so it uses the ARM token (`console/azure_probe.py:529-531#resource_graph`); the console mints the ARM, Graph and Logs tokens one after another and then runs up to six probes in parallel (`console/azure_probe.py:853-857#run_many`) | ARM read access; Resource Graph |

The silent path reads the Azure CLI's own encrypted token cache in the user's profile and asks the Azure CLI public client for a token, so the operator never signs in again and no secret is stored by the console (`demo/mcpclient.py:65-74#_az_cli_app`, `demo/mcpclient.py:76-86#acquire_token_silent`).

**Preconditions.**

1. The operator has run `az login`. Without it `try-violations.py` stops before the first request, no card is produced and the console job finishes `failed` with the summary `0/0 as expected` (`console/jobs.py:1024-1030#finish`); the probes report "no az CLI account in the MSAL cache - run `az login`" (`console/azure_probe.py:73-89#token`).
2. The deployment's generated configuration files exist. The script reads three of them at start-up: the subscription, resource group, location and tags; the Foundry account and project; and the assignment name (`demo/try-violations.py:49-65#_load`).
3. The operator's own rights let the PUT reach Azure Policy. A refusal by ARM itself (for example an authorization failure) is not a policy decision: it is classified ERROR and fails the card (`demo/try-violations.py:352-360#ERROR`).
4. The initiative is assigned at the resource group with enforcement mode Default, and its Deny effect is the parameter `hardControlEffect` (`infra/06-governance.bicep:21#hardControlEffect`, `infra/06-governance.bicep:177-205#assignment`). Provenance: Configured.
5. For beat 2.2, the blob service of the data storage account sends all logs to the Log Analytics workspace (`infra/03-platform.bicep:464-476#diagBlob`). Logs arrive 2 to 18 minutes after the request (see section 11 for the lag table).
6. The job manager lets beat 2.1 run beside everything else: the kind `violations` is not in the kill-switch precheck list and conflicts only with another `violations` job, which is why it can run during Act 1 (`console/jobs.py:495#NEEDS_OPEN_GATEWAY`, `console/jobs.py:480-493#conflicts`).

#### 9.3.2 Beat 2.1: Try to break the platform rules

**Purpose.** Make nine real requests to ARM, as the operator, that try to bring a key or a public endpoint back, plus one compliant control, and show that Azure Policy answers in one of three honest ways: refused (BLOCKED), made safe first (CORRECTED) or allowed (ALLOWED). The point for the room: "A policy that never says yes is not a policy - one of the nine is allowed on purpose" (`console/catalog.py:322-334#sales`). Provenance: Implemented (script and console parser), Configured (the initiative, its assignment and exemptions), Platform behaviour (policy evaluation order), Not in this repository (the tenant organisation baseline).

**Actors and tokens.** The operator's Azure CLI identity and a fresh ARM access token per request (table in 9.3.1). The judges are ARM and Azure Policy. There is no Foundry, APIM, MCP server or model in this beat.

**Preconditions.** Those of 9.3.1, and patience: the catalog allows 4 to 6 minutes (`console/catalog.py:327#eta`). In the scrubbed run the nine requests started within about a minute (`demo/evidence-scrubbed/`); the rest is the clean up in the final block, which retries each delete every 15 seconds while it is refused with HTTP 409 or 412, as a new Cosmos DB account can take minutes to become deletable (`demo/try-violations.py:362-372#_delete`), followed by a wait of up to 180 seconds for the Activity Log to show which policy rewrote each corrected request (`demo/try-violations.py:388-419#_modified_by`).

**Sequence.**

1. Browser -> console: the button "Run the nine attacks (live)" posts `{"kind":"violations","beat":"2.1"}` to `POST /api/jobs`; the alternative button "Show the last run" posts `{"kind":"violations_last","beat":"2.1"}`. The browser then polls the job with `?since=<n>` until it ends (`console/catalog.py:322-334#violations`, `console/server.py:128-135#api_jobs_start`, `console/server.py:144-152#api_job`).
2. Console job manager: look up the runner, validate, check conflicts, create the `Job` and start a daemon thread (`console/jobs.py:503-533#start`, `console/jobs.py:1401-1415#RUNNERS`). Events are numbered dictionaries `{"i","t","type",...}` (`console/jobs.py:276-304#emit`).
3. `run_violations` says "Sending nine real requests to Azure Resource Manager that try to break the platform rules. Each takes about 30 seconds; throw-away resources are deleted afterwards.", then fetches the human titles once by running `try-violations.py --list` with a 60 s timeout and caching the result (`console/jobs.py:994-1031#run_violations`, `console/jobs.py:975-987#violation_titles`).
4. Console -> child process: `stream_process` starts `python demo/try-violations.py` with `PYTHONIOENCODING`, `PYTHONUNBUFFERED` and `NO_COLOR` set, a 900 s ceiling and one callback per output line (`console/jobs.py:358-398#stream_process`, `console/jobs.py:1024#try-violations`).
5. Script start-up: load the three configuration files and create one `AzureCliCredential(process_timeout=90)` (`demo/try-violations.py:49-65#_cred`). Build the nine specs with a random six-hex-digit suffix so names never collide, for example `stabwtry<r>` and `cosmos-abw-try-<r>` (`demo/try-violations.py:72-84#_rand`).
6. Script -> ARM, once per spec and strictly in order: `PUT https://management.azure.com<resource id>?api-version=<api>` with the spec body, a 300 s timeout, and an Authorization header carrying the Bearer-scheme access token from step 5's credential (`demo/try-violations.py:318-322#run_attempt`).
7. ARM -> Azure Policy, before any resource provider is asked to create anything: the order of evaluation is disabled, then append and modify, then deny, then audit, and a change made by Modify can prevent a later audit or deny from triggering. Two sources of policy apply to the resource group: the tenant organisation baseline (its Modify effects) and the initiative `abw-agent-platform-controls` (its Deny effects). Provenance: Platform behaviour (https://learn.microsoft.com/azure/governance/policy/concepts/effect-basics#order-of-evaluation and https://learn.microsoft.com/azure/governance/policy/concepts/effect-modify#modify-evaluation).
8. Branch A, refusal: ARM answers HTTP 403 with error code `RequestDisallowedByPolicy`. The script collects each `PolicyViolation` item into `{reference, definition, effect, assignment, initiative}`, strips the long "Policy identifiers" tail from the message, records outcome BLOCKED and marks PASS only if the attempt expected a block and every expected control is among the hit references (`demo/try-violations.py:338-352#RequestDisallowedByPolicy`, `demo/try-violations.py:232-252#_policy_hits`).
9. Branch B, success (HTTP below 300): the positive control is marked ALLOWED/PASS. For every other attempt `_classify_allowed` reads the resource back (up to 12 GETs, 5 s apart), compares each unsafe property that was sent with what is stored, and if every one of them changed, records CORRECTED. It then asks ARM which controls of this initiative would have flagged the original body, with a stateless `checkPolicyRestrictions` call at the resource group (`includeAuditEffect` false, nothing is created) and marks PASS if at least one expected control is flagged. If not every unsafe property reads back changed, the outcome is ALLOWED/FAIL, a real hole only when the stored values are as sent, because a read back that never succeeds (12 tries, then nothing) or a property missing from the stored resource lands in the same outcome (`demo/try-violations.py:297-316#_classify_allowed`, `demo/try-violations.py:261-269#_read_back`, `demo/try-violations.py:271-295#_flagged_by_initiative`). Provenance: Platform behaviour for the restriction check (https://learn.microsoft.com/dotnet/api/azure.resourcemanager.policyinsights.mocking.mockablepolicyinsightsresourcegroupresource.checkpolicyrestrictions?view=azure-dotnet).
10. Branch C, anything else: outcome ERROR, status FAIL, with the error code and the message from ARM, without any trailing policy identifiers; when ARM sends no message, the first 300 characters of the response body stand in. The script prints the message line only for a FAIL card and cuts it at 300 characters, and the console reads that line (`demo/try-violations.py:358#message`, `demo/try-violations.py:250-252#_clean_message`, `demo/try-violations.py:460#message`).
11. After the last attempt, in a `finally` block: delete every resource that was created, retrying up to 60 times at 15 s intervals on HTTP 409 or 412 while it is still provisioning, and purge the soft-deleted Foundry account so no tombstone is left (`demo/try-violations.py:362-386#_delete`, `demo/try-violations.py:463-468#cleanup`).
12. Script -> ARM Activity Log: for the CORRECTED resources, poll every 20 s for up to 180 s for events whose operation name starts with `microsoft.authorization/policies/modify` and record `{assignment, scope, control}` as `correctedBy` (`demo/try-violations.py:388-419#_modified_by`).
13. Script -> disk: write `try-violations-<stamp>.json` with `{"runUtc","assignment","results"}` into its evidence folder, print the summary line, and exit 1 unless every attempt is PASS (`demo/try-violations.py:470-491#EVIDENCE`).
14. Console parse: every output line becomes a `raw` event. A line shaped `PASS|FAIL <outcome> HTTP <code> <id> <rest>` starts a card (the previous card is emitted at that moment, so cards appear one attempt late); lines indented by nine spaces are appended to the current card's note; the final `N/M as expected ... -> <path>` line emits the last card and remembers the evidence path (`console/jobs.py:966-971#_VIOL_OUTCOME`, `console/jobs.py:1001-1022#on_line`).
15. Console end: remember the evidence path in the console state, say "<passed> of <total> behaved exactly as the policy intends.", and finish `done` only if the exit code is 0 and every card passed; otherwise `failed` with the summary "<passed>/<total> as expected" (`console/jobs.py:1024-1030#save_state`).

**The nine attempts.** Each row is one spec in `attempts()`; the outcome column is the shape observed in the scrubbed evidence of a live run. Names and settings are the code's, the outcome is what this tenant did on that run, and your tenant's organisation baseline decides which rows are CORRECTED rather than BLOCKED.

| # | Attempt id (spec) | What is attempted | Unsafe settings sent | Controls expected | Outcome in the scrubbed run |
|---|-------------------|-------------------|----------------------|-------------------|-----------------------------|
| 1 | `storage-shared-key` (`demo/try-violations.py:87-99#controls`) | Create a storage account with shared-key access and public network access | `allowSharedKeyAccess` true, `publicNetworkAccess` Enabled | `storage-shared-key-disabled`, `storage-no-public` | CORRECTED, HTTP 202: both settings rewritten; the initiative flags both controls |
| 2 | `cosmos-local-auth` (`demo/try-violations.py:102-119#controls`) | Create a Cosmos DB account with key authentication and a public endpoint | `disableLocalAuth` false, `publicNetworkAccess` Enabled | `cosmos-local-auth-disabled`, `cosmos-no-public` | CORRECTED, HTTP 200: both rewritten; the stateless check flags `cosmos-no-public` only, which is enough |
| 3 | `search-local-auth` (`demo/try-violations.py:121-133#controls`) | Create an AI Search service with API keys and a public endpoint | `disableLocalAuth` false, `publicNetworkAccess` enabled | `search-local-auth-disabled`, `search-no-public` | BLOCKED, HTTP 403: three Deny hits (`ai-local-auth-disabled`, `search-local-auth-disabled`, `search-no-public`) |
| 4 | `keyvault-access-policies` (`demo/try-violations.py:135-151#controls`) | Create a Key Vault with legacy access policies instead of Azure RBAC | `enableRbacAuthorization` false | `keyvault-rbac` | BLOCKED, HTTP 403 |
| 5 | `<registry-attempt-id>` (`demo/try-violations.py:153-160#controls`) | Create a container registry with the built-in shared user switched on | the shared-user setting on | the `acr-*` registry control | BLOCKED, HTTP 403 |
| 6 | `foundry-local-auth` (`demo/try-violations.py:162-176#controls`) | Create a Foundry (AI Services) account with API keys switched on | `disableLocalAuth` false | `ai-local-auth-disabled` | CORRECTED, HTTP 201; the account is purged after deletion |
| 7 | `foundry-keyed-connection` (`demo/try-violations.py:178-192#controls`) | Add a Foundry project connection that stores an API key | `authType` ApiKey with a dummy key; the target is the first approved endpoint, so only the key is wrong | `foundry-no-keyed-connections` | BLOCKED, HTTP 403 |
| 8 | `foundry-unapproved-mcp` (`demo/try-violations.py:194-207#controls`) | Add a Foundry remote-tool (MCP) connection that points at an unapproved server | `authType` None; target `https://mcp.shadow-vendor.example.com/mcp` | `foundry-approved-mcp-targets` | BLOCKED, HTTP 403 |
| 9 | `positive-control` (`demo/try-violations.py:209-230#controls`) | Positive control: a compliant storage account | shared key off, public access Disabled, TLS 1.2 | none; the spec sets `expect` to allowed | ALLOWED, HTTP 202 |

The first approved endpoint is the research API on the gateway (`infra/06-governance.bicep:162-168#approvedMcpEndpoints`, `demo/try-violations.py:63#APPROVED_TARGET`). Attempt 3 shows that one request can hit several controls at once; attempt 2 shows that the stateless re-check can report fewer controls than a real request, so one expected control is enough (`demo/try-violations.py:297-316#_classify_allowed`).

**Success outcome.** All nine attempts are PASS: the script exits 0, the job finishes `done` with the summary `9/9 as expected` and the result fields `passed` and `total` (`console/jobs.py:1024-1030#finish`). The script's last line reads, with the tally computed from the PASS rows only:

```
  9/9 as expected (5 denied, 3 corrected by another policy, 1 compliant request allowed)  ->  <relative evidence path>
```

The three result shapes written to the evidence file (placeholders instead of ids; fields are the code's, in `run_attempt` and `_classify_allowed`):

```json
{
  "id": "keyvault-access-policies",
  "title": "Create a Key Vault with legacy access policies instead of Azure RBAC",
  "resource": "kv-abw-try-<r>",
  "expected": "blocked",
  "expectedControls": ["keyvault-rbac"],
  "httpStatus": 403,
  "utc": "<utc-time>",
  "outcome": "BLOCKED",
  "errorCode": "RequestDisallowedByPolicy",
  "policy": [
    {"reference": "keyvault-rbac", "definition": "<definition display name>", "effect": "Deny",
     "assignment": "abw-agent-platform-controls", "initiative": "abw-agent-platform-controls"}
  ],
  "message": "Resource 'kv-abw-try-<r>' was disallowed by policy. Reasons: '<policy message>'. See error details for policy resource IDs.",
  "status": "PASS"
}
```

```json
{
  "id": "storage-shared-key",
  "resource": "stabwtry<r>",
  "expected": "blocked",
  "expectedControls": ["storage-shared-key-disabled", "storage-no-public"],
  "httpStatus": 202,
  "outcome": "CORRECTED",
  "rewritten": {
    "properties.allowSharedKeyAccess": {"sent": true, "stored": false, "changed": true},
    "properties.publicNetworkAccess": {"sent": "Enabled", "stored": "Disabled", "changed": true}
  },
  "initiativeFlags": ["storage-no-public", "storage-shared-key-disabled"],
  "status": "PASS",
  "cleanup": "deleted (HTTP 200)",
  "correctedBy": [{"assignment": "<baseline-assignment>", "scope": "<management-group-scope>", "control": "<modify-control>"}]
}
```

```json
{"id": "positive-control", "resource": "stabwok<r>", "expected": "allowed", "expectedControls": [],
 "httpStatus": 202, "outcome": "ALLOWED", "status": "PASS", "cleanup": "deleted (HTTP 200)"}
```

The terminal view of the same run, one line per attempt (`demo/try-violations.py:425-432#_describe`, `demo/try-violations.py:455-462#print`):

```
  PASS CORRECTED HTTP 202  storage-shared-key         rewritten before the Deny ran: allowSharedKeyAccess true->false, publicNetworkAccess Enabled->Disabled; initiative flags: storage-no-public, storage-shared-key-disabled
  PASS BLOCKED   HTTP 403  keyvault-access-policies   keyvault-rbac
  PASS ALLOWED   HTTP 202  positive-control           -
         cleanup stabwok<r>: deleted (HTTP 200)
         storage-shared-key corrected by: <baseline-assignment> @ <management-group-scope>
```

The console shows the same run as a job transcript. The `t` values are illustrative; the shapes are the code's (`console/jobs.py:989-992#_viol_event`):

```json
[
  {"i": 0, "t": 0.0, "type": "say", "text": "Sending nine real requests to Azure Resource Manager that try to break the platform rules. Each takes about 30 seconds; throw-away resources are deleted afterwards."},
  {"i": 1, "t": 38.0, "type": "raw", "text": "  PASS CORRECTED HTTP 202  storage-shared-key         rewritten before the Deny ran: ..."},
  {"i": 2, "t": 52.0, "type": "raw", "text": "  PASS CORRECTED HTTP 200  cosmos-local-auth          rewritten before the Deny ran: ..."},
  {"i": 3, "t": 52.0, "type": "violation", "id": "storage-shared-key", "title": "Create a storage account with shared-key access and public network access",
   "outcome": "CORRECTED", "status": "202", "pass": true,
   "plain": "The organisation baseline rewrote the unsafe setting to a safe one first - same outcome, earlier layer.",
   "note": ["rewritten before the Deny ran: ..."], "lights": {"policy": "deny"}},
  {"i": 40, "t": 300.0, "type": "say", "text": "9 of 9 behaved exactly as the policy intends."},
  {"i": 41, "t": 300.0, "type": "done", "status": "done", "summary": "9/9 as expected"}
]
```

In the card, `status` is the HTTP code as text and `pass` is the PASS flag. The policy node on the console board lights red-ish "deny" for BLOCKED and CORRECTED and "ok" for ALLOWED, and the plain sentence is the text table for the three outcomes (`console/jobs.py:966-971#_VIOL_OUTCOME`).

**Classification rules.** These are the rules that decide PASS or FAIL for each card; none of them is decided by the console.

| Condition | Outcome | Status |
|-----------|---------|--------|
| ARM error code `RequestDisallowedByPolicy` | BLOCKED | PASS if the spec expects a block and every expected control is among the hit references; otherwise FAIL with the note "expected control(s) not reported: [...]" |
| HTTP below 300 and the spec expects allowed (the positive control only) | ALLOWED | PASS |
| HTTP below 300, block expected, every unsafe property read back differs from what was sent | CORRECTED | PASS if at least one expected control is in the initiative flags; otherwise FAIL with the note "the request was rewritten by another policy, but this initiative did not flag it" |
| HTTP below 300, block expected, not every unsafe property read back differs from what was sent | ALLOWED | FAIL: a real hole only when the stored values are as sent; a read back that never succeeds, or a property missing from the stored resource, ends here too |
| Any other HTTP status | ERROR | FAIL, with the error code and the message from ARM (the first 300 characters of the response body when ARM sends none; the printed line is cut at 300 characters) |

(`demo/try-violations.py:297-316#_classify_allowed`, `demo/try-violations.py:318-360#run_attempt`.)

**The initiative that answers.** The Deny answers come from the policy set `abw-agent-platform-controls` (19 policy references: 11 Deny and 8 Audit with the default effect parameters, in five control groups), assigned to the demo resource group only, with enforcement mode Default. The Deny effects follow `hardControlEffect` (default Deny), the tools and models references follow `agentToolEffect` (default Audit) and the other Audit references are fixed to Audit (`infra/06-governance.bicep:21#hardControlEffect`, `infra/06-governance.bicep:25#agentToolEffect`, `infra/06-governance.bicep:185-187#auditEffect`). The group names and references are the code's (`infra/06a-policy-definitions.bicep:168#initiative`, `infra/06a-policy-definitions.bicep:222-294#policyDefinitionReferenceId`, `infra/06a-policy-definitions.bicep:296-360#policyDefinitionReferenceId`, `infra/06-governance.bicep:177-205#assignment`):

| Group | References (effect) | Where defined |
|-------|---------------------|---------------|
| ABW-01-NO-KEYS | `ai-local-auth-disabled`, `storage-shared-key-disabled`, `cosmos-local-auth-disabled`, `search-local-auth-disabled`, `keyvault-rbac`, the `acr-*` registry control, `foundry-no-keyed-connections` (all Deny by default) | `infra/06a-policy-definitions.bicep:222-263#policyDefinitionReferenceId` |
| ABW-02-PRIVATE | `ai-restrict-network` (Audit), `cosmos-no-public`, `storage-no-public`, `search-no-public` (Deny), `aca-env-no-public` (Audit) | `infra/06a-policy-definitions.bicep:265-294#policyDefinitionReferenceId` |
| ABW-03-TOOLS-MODELS | `foundry-approved-tools` and `foundry-approved-models` (effect is the parameter `toolsEffect`, default Audit), `foundry-approved-mcp-targets` (Deny) | `infra/06a-policy-definitions.bicep:296-324#policyDefinitionReferenceId` |
| ABW-04-GUARDRAILS | `agent-guardrail-jailbreak`, `agent-guardrail-indirect-attack` (both Audit) | `infra/06a-policy-definitions.bicep:326-347#policyDefinitionReferenceId` |
| ABW-05-HYGIENE | `aca-managed-identity`, `aca-https-only` (both Audit) | `infra/06a-policy-definitions.bicep:349-360#policyDefinitionReferenceId` |

Two of the references are custom definitions written for this repository: one denies any Foundry connection whose auth type is a key, SAS token, PAT, password or similar, and one denies a remote-tool connection whose target is not on the approved list (`infra/06a-policy-definitions.bicep:40#keyedAuthTypes`, `infra/06a-policy-definitions.bicep:50-94#noKeyedConnections`, `infra/06a-policy-definitions.bicep:96-166#approvedMcpTargets`). The approved list is the three internal APIs, the vendor API on the gateway and the private server's own address (`infra/06-governance.bicep:162-168#approvedMcpEndpoints`). The messages the caller sees are fixed per reference: a default sentence naming the initiative, a "no shared secrets" sentence for the key controls, a "not on the approved MCP list" sentence for the targets control and a "private endpoints only" sentence for the public-access controls (`infra/06-governance.bicep:170-175#messages`).

**Exemptions that keep the board honest.** Some references are deliberately not enforced for named resources, each with a category; only the two legacy waivers carry an expiry. They show as Exempt in compliance, not green (`infra/06-governance.bicep:232-306#policyExemptions`):

| Exemption | Category | References | Why it exists |
|-----------|----------|------------|---------------|
| `exLegacyAccount`, `exLegacyProject` (`infra/06-governance.bicep:232-256#exLegacyAccount`) | Waiver, time-boxed | `foundry-no-keyed-connections`, `foundry-approved-mcp-targets` | The deliberate keyed `mcp-legacy-key` connection that Act 1 needs as the "before" picture |
| `exAppiAccount`, `exAppiProject` (`infra/06-governance.bicep:260-282#exAppiAccount`) | Mitigated | `foundry-no-keyed-connections` | The Foundry telemetry connection to Application Insights is created with an ingestion key (write-only) |
| `exFoundryNetwork` (`infra/06-governance.bicep:284-291#exFoundryNetwork`) | Mitigated | `ai-restrict-network` | The Foundry account keeps its public endpoint for operator access |
| `exPublicEnv` (`infra/06-governance.bicep:296-306#exPublicEnv`) | Waiver | `aca-env-no-public` | The public Container Apps environment hosts the simulated external vendor and the legacy POC server, on purpose |

**Failure or denial outcomes.** Beat 2.1 is a producer of denials, so its own failures are different shapes. A card is FAIL when a block was expected but the request was allowed unchanged (ALLOWED/FAIL, a hole in policy), when a CORRECTED request was not flagged by this initiative, when an expected control is missing from the BLOCKED hits, or when ARM returned a different error (ERROR). The job is `failed` when the exit code is not 0 or any card failed, when no card was produced, or when the 900 s ceiling is hit (`console/jobs.py:1024-1030#finish`). A ceiling hit raises `TimeoutError("try-violations.py took longer than 900s and was stopped")` (`console/jobs.py:400-407#TimeoutError`).

**Evidence produced.**

| Evidence | Where it lands | How to retrieve it |
|----------|----------------|--------------------|
| All nine results with HTTP status, controls, hits, rewrites, cleanup and `correctedBy` | The script's evidence folder as `try-violations-<stamp>.json` (tag: replay of an ARM call, shape in `demo/evidence-scrubbed/`) | Open the file; or run `python demo\try-violations.py --json` for the same list on the terminal (`demo/try-violations.py:434-441#add_argument`) |
| Cards for the room | Console job events of type `violation` | `GET /api/jobs/<job-id>?since=<n>` (`console/server.py:144-152#api_job`) |
| Where the last run's file is | Console state key `violations` with `path` and `at` | `console/jobs.py:1024-1030#save_state` |
| Which policy performed the Modify | `correctedBy` in each CORRECTED result, read from the ARM Activity Log | `demo/try-violations.py:388-419#_modified_by` |
| Compliance after the run | Policy states for the initiative, queried through Resource Graph | Beat 2.3 and proof P11 (below) |

**How the console runs it.** Beat definition and buttons: `console/catalog.py:322-334#violations`; runner: `console/jobs.py:994-1031#run_violations`; the `violations_last` runner is `console/jobs.py:1033-1053#run_violations_last`. The CLI equivalent is `python demo\try-violations.py` (all nine), `--only <id substrings>` for a subset and `--list` for the ids and titles (`demo/try-violations.py:434-441#add_argument`).

**"Show the last run".** The alternative button needs no credential and no Azure call. It takes the newest `try-violations-*.json` file from the script's evidence folder, says which run it is showing, and emits one card per result with the pass flag set true for every row, whatever its real status (Findings F5). Its notes print the first three `policy` hits and `correctedBy` entries as raw Python dictionaries (Findings F5b). With no earlier file it emits an error "No earlier run found" and finishes `failed` (`console/jobs.py:1033-1053#run_violations_last`).

**How demo/prove.py proves it.** Proof P11 runs the same script as a child process with a 1500 s ceiling, requires exit code 0 and an `N/N as expected` line, records the number of BLOCKED attempts and the names of the CORRECTED attempts, then reads the initiative's policy states from Resource Graph and requires at least one Compliant row (`demo/prove.py:993-1018#p11`). In the scrubbed run: "9/9 as expected (5 denied, 3 corrected by another policy, 1 compliant request allowed)", and the Resource Graph read returned 23 rows, one per state and policy reference pair, carrying 69 Compliant, 8 Exempt and 1 NonCompliant policy state records. The one NonCompliant reference is `foundry-approved-tools`, an Audit control; the proof prints it under the label "legacy path, by design" (`demo/prove.py:1015-1018#NonCompliant`), which is a fixed label, not a measurement (Findings F29).

**Failure modes and what the presenter should say.**

- The result bar still reads "Running" when you arrive: say "I launched nine attempts to break the platform rules; I will read the result in a moment" (`docs/TALK-TRACK.md:142#Start`).
- "Why not nine refusals?" The organisation baseline runs Modify before Deny, so three requests came back safe instead of refused: say "I did not bypass it to look stricter" (`docs/TALK-TRACK.md:169#Modify`).
- A card is red: do not explain it away. ALLOWED/FAIL means a control is missing; ERROR means ARM itself said no, usually the operator's own rights.
- The corrected-by lines and clean-up lines are printed after the last attempt, so the console appends them to the last card's note (the positive control), where the baseline assignment name is visible in the browser; do not read that note aloud (Findings F24).
- Stop or the 900 s ceiling kills the child process tree, so its `finally` clean-up never runs and throw-away resources can be left in the resource group; list the resource group afterwards (Findings F26; `console/jobs.py:351-355#_kill_tree`).

#### 9.3.3 Beat 2.2: Evidence that no key is in use

**Purpose.** Answer "how do you know?" with the platform's own log instead of a promise. Azure Storage writes one row per data-plane request into the workspace table `StorageBlobLogs`, and each row records how the caller authenticated. The saved function `AbwZeroKeys` counts the requests by account and authentication type and flags the key-signed types. The console then runs a second, classifying query that separates Azure-internal calls that carry no identity from anything a person, an agent or an app did. The line for the room is "Not 'we promise no keys' - here is the log" (`console/catalog.py:335-354#nokeys`). Provenance: Implemented (the function, the runner and the classifier), Configured (the diagnostic settings that feed the table and the deployment of the function), Platform behaviour (the meaning of the log fields, https://learn.microsoft.com/azure/azure-monitor/reference/tables/storagebloglogs).

**Actors and tokens.** The operator and one Log Analytics access token: resource `https://api.loganalytics.io`, scope `<resource>/.default`, minted silently from the Azure CLI's token cache and kept by the console until 300 s before it expires (table in 9.3.1; section 6 owns the mechanics). No persona token, no gateway and no MCP server is involved. The judge is Log Analytics access control on the workspace. The console stores no secret.

**Preconditions.**

1. `az login` as the operator (9.3.1, item 1). Without it the job ends `failed` with the sign-in text shown under the failure outcomes.
2. The workspace customer id is part of the deployment's generated platform state, which the console loads when it starts (`console/azure_probe.py:57-59#LAW_CUSTOMER`).
3. The operator's own account can query the workspace. This repository grants Log Analytics Reader to the infosec group, not to the operator. The operator's own assignments are a Foundry role on the Foundry account, a Key Vault role, a registry push role and a search-service management role, with no role on the user-data stores (blob, Cosmos DB, search documents), so the right to query the workspace is a property of the operator's own account, not something this repository grants (`infra/03-platform.bicep:713-720#raInfosecLaReader`, `infra/03-platform.bicep:733-764#raOpKv`, `infra/02-foundry-rbac.bicep:26-34#raOperatorAccount`; Findings F51). If it is missing, the job fails with `ProbeError: Log Analytics 403 <code>: <message>`.
4. The blob service of the data storage account and of the Foundry agent-service dependency storage account both send all logs to the workspace. Without these two diagnostic settings the table has no rows (`infra/03-platform.bicep:464-476#diagBlob`, `infra/06-governance.bicep:122-129#diagAsvcBlob`). Provenance: Configured.
5. The function `AbwZeroKeys` is deployed as a saved search with a function alias by the observability template, one function at a time because the workspace validates each query (`infra/06b-observability.bicep:42-54#savedSearches`).
6. Logs reach the workspace 2 to 18 minutes after a request (section 11 holds the lag table). A 30-day window makes the lag irrelevant for the headline and relevant only for the last few minutes.

**Sequence.**

1. Browser -> console: the button "Show authentication method" posts `{"kind":"kql","params":{"query":"nokeys"},"beat":"2.2"}` to `POST /api/jobs` (`console/catalog.py:335-354#nokeys`, `console/server.py:128-135#api_jobs_start`).
2. Job manager: `validate` accepts a `kql` job only when the query name is in the console's query table; anything else is answered "Unknown query.". The kind `kql` is in the READONLY set, so it never conflicts with another job, and it is not in the kill-switch list, so it also runs while the gateway is shut (`console/jobs.py:563-593#validate`, `console/jobs.py:476#READONLY`, `console/jobs.py:495#NEEDS_OPEN_GATEWAY`).
3. `run_kql` says "Querying Log Analytics: How every storage request authenticated (last 30 days)." (`console/jobs.py:1184-1188#Querying`).
4. Console -> Log Analytics: `la_query` calls `token(LOGS)` and POSTs `https://api.loganalytics.io/v1/workspaces/<workspace-customer-id>/query` with an Authorization header carrying the Bearer-scheme access token and the body `{"query":"AbwZeroKeys(30d)","timespan":"P30D"}`. The span is `PT<h>H` below 48 hours and `P<d>D` from 48 hours up, so 720 hours becomes `P30D`. A 429, 502, 503 or 504 answer is retried, three tries in all (`console/azure_probe.py:165-180#la_query`, `console/azure_probe.py:103-117#_retrying`).
5. Log Analytics evaluates the saved function over `StorageBlobLogs`: keep the lookback window, summarise by account and authentication type, count the rows whose status is 401 or 403 as `Denied`, and set `KeyBased` for the five key-signed types `AccountKey`, `SAS`, `AccountSas`, `ServiceSas` and `DelegationSas` (`observability/kql/AbwZeroKeys.kql:5-8#KeyBased`).
6. Log Analytics -> console: the first table comes back as column names and rows; `la_query` zips each row into a dictionary (`console/azure_probe.py:165-180#la_query`).
7. Console -> browser: `_kql_table` emits one `table` event with the columns in first-seen order, the first 40 rows with every cell turned into text, the query text, the total row count and the lights (`console/jobs.py:1150-1157#_kql_table`).
8. Because the query name is `nokeys`, the console runs the second query, the `detail` text of the same table entry, with the same token. It lists every key-signed request by account, authentication type and operation, and sets `Platform` to true when the operation is `GetBlobServiceProperties` or `SetBlobServiceProperties`, the caller address starts with `10.`, and the requester's object id, user principal name and app id are all empty (`console/catalog.py:1239-1251#nokeys`, `console/jobs.py:1220-1223#detail`).
9. The console chooses one of four outcomes and says it: no storage rows at all; at least one key-signed request that is not `Platform` (a red step); only `Platform` rows (a sentence with the count and the operations); or nothing key-signed (`console/jobs.py:1224-1234#platform`).
10. `finish` closes the job with `{"type":"done","status":"done","summary":"<n> rows"}`; the red step does not fail the job (Findings F30) (`console/jobs.py:1239#finish`).
11. Browser: `tableCard` draws the table, or, with no rows, the callout "No rows in this window yet - logs reach Log Analytics 5-10 minutes after a call.", and a "Show the query" panel with "Copy query" and "Open Log Analytics" (`console/web/render.js:91-106#tableCard`). The callout understates the lag: the console's own lag statement is 2 to 18 minutes (`console/web/render.js:300#TR_LAG`).

**Success outcome.** A table whose `KeyBased` column reads `False` on every row except any Azure-internal SAS rows (in the recorded tenant, one per storage account with two requests each and no identity, `docs/TALK-TRACK.md:157#SAS`), followed by one sentence. The columns are the function's output (`Account`, `AuthType`, `Requests`, `Denied`, `LastSeen`, `KeyBased`); the values are placeholders because they come from your tenant's logs. The scrubbed proof run saw one account and authentication type in its 7-day window (OAuth); your 30-day window may also show a `TrustedAccess` row, the second storage account and the Azure-internal SAS rows described below.

```json
{"i": 2, "t": 4.1, "type": "table", "title": "How every storage request authenticated (last 30 days)",
 "columns": ["Account", "AuthType", "Requests", "Denied", "LastSeen", "KeyBased"],
 "rows": [
   ["stabwdemo<region><u4>", "OAuth", "<n>", "<n>", "<utc-time>", "False"],
   ["stabwdemo<region><u4>", "TrustedAccess", "<n>", "0", "<utc-time>", "False"],
   ["stabwdemo<region><u4>", "SAS", "2", "0", "<utc-time>", "True"],
   ["<asvc-storage-account>", "OAuth", "<n>", "<n>", "<utc-time>", "False"],
   ["<asvc-storage-account>", "SAS", "2", "0", "<utc-time>", "True"]
 ],
 "query": "AbwZeroKeys(30d)", "total": 5, "lights": {"monitor": "ok"}}
```

```json
[
  {"i": 3, "t": 8.7, "type": "say", "text": "Every request from a person, an agent or an app used an Entra token. The only SAS rows are <n> Azure-internal service-property calls (<ops>) with no identity and no blob read or written - in this tenant they coincide with Defender for Storage onboarding the accounts (see the note under this step)."},
  {"i": 4, "t": 8.7, "type": "done", "status": "done", "summary": "5 rows"}
]
```

When there is no key-signed row at all, the sentence is "No key-signed request in the window: every storage call used an Entra token." (`console/jobs.py:1229-1234#platform`). In the example, the two SAS rows have `KeyBased` True and the console still says every person, agent and app used a token: that is the `Platform` rule at work, and it is the reason the presenter names those rows first (see the presenter notes below).

**Failure or denial outcomes.**

| Condition | What the browser shows | Job | Produced by |
|-----------|------------------------|-----|-------------|
| Not signed in to the Azure CLI | An `error` event: "Not signed in to Azure. Run `az login` as the demo operator, then press the button again." | `failed`, same text as the summary | `token`, then `friendly` (`console/azure_probe.py:73-89#token`, `console/jobs.py:163-173#friendly`) |
| The workspace refuses the caller or the query is rejected | An `error` event: `ProbeError: Log Analytics <status> <code>: <message>`, cut at 400 characters | `failed` | `la_query`, then `friendly` |
| DNS failure or timeout | An `error` event: "A network call to Azure did not complete (DNS or timeout). Press the button again - transient blips are common on hotel and home Wi-Fi." | `failed` | `_retrying`, then `friendly` |
| No rows in the window | The table card with the empty callout, then the line "No storage requests in the window yet." | `done`, summary "0 rows" | `run_kql` |
| A key-signed request with an identity | A red step: "<n> key-signed request(s) from a person, agent or app - investigate: <Account> <AuthType> <Operation>; ..." (first three groups) | `done` (Findings F30) | `run_kql` |

An `Anonymous` authentication type is not in the key-signed list, so it never turns `KeyBased` on and the console does not flag it; the `Denied` column counts only status 401 and 403, so a probe refused with 409 shows in `Requests` but not in `Denied` (`observability/kql/AbwZeroKeys.kql:6-7#Denied`). The presenter note explains an `Anonymous` row as probes from a public address that were refused with 403 or 409 (`docs/TALK-TRACK.md:157#Anonymous`).

**Evidence produced.**

| Evidence | Where it lands | How to retrieve it |
|----------|----------------|--------------------|
| The table and the closing sentence (tag `logs`) | Console job events `table`, `say` or `step`, and `done` | `GET /api/jobs/<job-id>?since=<n>` (`console/server.py:144-152#api_job`) |
| The log rows behind the table | Workspace table `StorageBlobLogs`: `AccountName`, `AuthenticationType`, `OperationName`, `CallerIpAddress`, `RequesterObjectId`, `RequesterUpn`, `RequesterAppId`, `StatusCode`, `TimeGenerated` | "Show the query", then "Copy query" or "Open Log Analytics"; or the terminal command `abw-nokeys`, which runs `AbwZeroKeys(30d)` through `demo/kql.py` with a 720-hour window (`demo/stage.ps1:197-200#abw-nokeys`, `demo/kql.py:63-76#query_rows`) |
| The saved function | Workspace function `AbwZeroKeys`, category "ABW Agent Wall" | Logs, then Functions; the workbook uses it twice, for the "Key / SAS storage requests" tile and for the Zero keys tab (`observability/workbook/build_workbook.py:144#AbwZeroKeys`, `observability/workbook/build_workbook.py:583#AbwZeroKeys`; section 12) |
| The proof result | `prove-<stamp>.json` in the evidence folder | `python demo\prove.py --only P01` |

**How the console runs it.** Beat definition: `console/catalog.py:335-354#nokeys`. The two query texts: `console/catalog.py:1239-1251#nokeys`. Runner: `console/jobs.py:1184-1239#run_kql`. The terminal backup named in the beat map is `abw-nokeys` (`docs/TALK-TRACK.md:127#abw-nokeys`).

**How demo/prove.py proves it.** Proof P01 is the strict version of this beat, in two halves (`demo/prove.py:545-571#p01`, `demo/prove.py:576-601#AbwZeroKeys`):

- *Configuration half.* One Resource Graph query reads six service types in the resource group: storage shared key, Cosmos local auth, Search local auth, Foundry local auth, the registry's built-in shared user and Key Vault RBAC. There is one check per resource, plus a check that all six types exist so the proof cannot pass on an empty result. For each of the four governed Container Apps, the only secret allowed is the Application Insights connection string, and no `env` value whose name looks sensitive may be a literal instead of a secret reference (`demo/prove.py:532-542#KEY_RULES`).
- *Behaviour half.* `AbwZeroKeys(7d)` must return rows (a log with no rows proves nothing); an inline copy of the classifier over 7 days must find no key-signed request that carries an identity; one fact lists the Azure-internal SAS calls; a further query requires that no `Anonymous` request succeeded (status 200 to 299) in the last 7 days (`demo/prove.py:598#Anonymous`); a last fact lists `<account>/<AuthType>` with its request count.

The differences from the console are: 7 days instead of 30, rows required, anonymous successes asserted at zero, and a different token path. The proof's log client is `LogsQueryClient(AzureCliCredential(process_timeout=90))`, where the SDK chooses the token scope (Platform behaviour), and its Resource Graph call uses an ARM token from the same Azure CLI sign-in (`demo/kql.py:41-45#_logs`, `demo/arg.py:29-37#_arm_token`). The console instead mints a token for `https://api.loganalytics.io` itself and calls the REST endpoint. In the scrubbed run every P01 check passed: four governed apps with only the Application Insights connection string as a secret and no literal sensitive setting, one account and authentication-type row (OAuth), zero key-based requests, and no anonymous success.

**Failure modes and what the presenter should say.**

- The table is empty: say "Logs reach the workspace a few minutes after a call; I will come back to this" and move on. Never say "zero" from an empty table; say "no rows yet".
- The two SAS rows: name them before anyone else does. They are four Azure-internal calls to read and write service properties, from a 10.x address, with no user or app identity and no blob read or written, at the time Defender for Storage onboarded the accounts. Read the time from your own table's `LastSeen` column, not from memory (`docs/TALK-TRACK.md:157#SAS`). The console's closing sentence says the same thing as a fixed string and does not check Defender (Findings F31).
- An `Anonymous` row: probes from a public address, refused with 403 or 409, not key-based (`docs/TALK-TRACK.md:157#Anonymous`).
- A red "investigate" step: do not explain it away. Open "Show the query" and read the rows; the job still says `done` (Findings F30).
- "Is there really no key anywhere?" Say: "The one key that does exist, the market-data vendor's, lives in Key Vault and is injected by the gateway. Neither the agent nor the user ever sees it" (`docs/TALK-TRACK.md:158#injected`), then use the honest list in 9.3.5.
- Land it: "'No keys' is not a policy document. It is a query, `AbwZeroKeys`, and a policy that refuses the attempt, which you will see in a minute" (`docs/TALK-TRACK.md:157-162#AbwZeroKeys`).

**Why and trade-offs.**

- A log proves what happened in a window, not what is possible. That is why 2.2 sits between 2.1 (what cannot be created) and 2.3 (what is switched off): three kinds of evidence for one claim.
- Storage only. Cosmos, Search, Key Vault and the registry also send all logs to the workspace, but no function in this repository classifies their authentication, so for those services the claim rests on configuration (beat 2.3, proof P01) and policy (beat 2.1) (`infra/03-platform.bicep:478-491#diagCosmos`, `infra/03-platform.bicep:493-505#diagSearch`).
- The `Platform` rule is a heuristic: an operation pair, a 10.x caller and empty identity fields. The console shows the rows so the presenter can show them too.
- `DelegationSas` is counted as key-based although a user delegation SAS is signed with a key obtained through Microsoft Entra credentials (https://learn.microsoft.com/rest/api/storageservices/create-user-delegation-sas); the code errs on the side of flagging. Provenance: Platform behaviour.

#### 9.3.4 Beat 2.3: Where the keys went

**Purpose.** Show the same fact as configuration, read live from Azure a few seconds ago: the Foundry account has local (API-key) authentication off, the Foundry project holds user-OAuth tool connections next to one deliberate keyed connection, every data store is Entra-only, and the policy initiative reports its compliance counts. The beat is optional (about 3 seconds) and is the "open it in the portal, the values are the same" backstop for beat 2.2 (`console/catalog.py:355-367#probes`, `docs/TALK-TRACK.md:160#Optional`). Provenance: Implemented (the three probes and the job), Configured (the settings being read), Platform behaviour (how a disabled-key setting takes effect, below).

**Actors and tokens.** The operator and ARM access tokens (scope `https://management.azure.com/.default`), minted silently as in 9.3.1. Resource Graph is an ARM endpoint, so the policy probe uses the same ARM token. The console always mints three tokens (ARM, Graph and Logs) one after the other before the first probe, even though these three probes need only the ARM one (`console/azure_probe.py:853-857#run_many`). No persona token, no gateway and no MCP server is involved. No secret is fetched: every call is a GET, or the Resource Graph POST that only reads.

**Preconditions.**

1. `az login` as the operator (9.3.1, item 1), and a Graph token the Azure CLI sign-in can mint, because `run_many` asks for one first (see the failure outcomes).
2. The deployment's generated state files hold the Foundry account and project names, the ids of the four data services and the policy assignment name; the probes read them when the console starts (`console/azure_probe.py:39-59#PLAT`).
3. The operator can read the resource group through ARM. The repository describes the operator as a subscription Owner and its Bicep comment calls that control plane only (`infra/03-platform.bicep:733-735#CONTROL`); the operator also holds Key Vault Administrator (a data-plane role), AcrPush, Search Service Contributor and a Foundry role on the Foundry account, but no role on the user-data stores (`infra/03-platform.bicep:736-764#raOpKv`, `infra/02-foundry-rbac.bicep:26-34#raOperatorAccount`; Findings F51, F5-35).
4. For the policy probe, Azure Policy has evaluated the resource group at least once; with no Compliant row the probe reports `warn`.

**Sequence.**

1. Browser -> console: the button "Read it live" posts `{"kind":"probes","params":{"ids":["foundry","data","policy"]},"beat":"2.3"}` (`console/catalog.py:355-367#probes`).
2. Job manager: `validate` rejects any id that is not in the probe table with "Unknown probe."; the kind is READONLY and not in the kill-switch list (`console/jobs.py:563-593#validate`, `console/jobs.py:476#READONLY`).
3. `run_probes` says "Reading the live configuration straight from Azure (read-only; no secrets are fetched)." and calls `run_many(ids, force=True)` (`console/jobs.py:1139-1146#run_probes`).
4. `run_many` mints the ARM, Graph and Logs tokens one after the other, then runs the probes on up to six worker threads. `force=True` skips the 120 s result cache; a probe that raises is turned into a `fail` card with "probe failed: <first 200 characters>" (`console/azure_probe.py:853-857#run_many`, `console/azure_probe.py:833-850#run_probe`).
5. `probe_foundry` -> ARM, API version `2025-04-01-preview`: GET the account, its deployments and the project's connections; count the connections by `authType`; read `disableLocalAuth` and `publicNetworkAccess` from the account (`console/azure_probe.py:251-281#probe_foundry`).
6. `probe_data` -> ARM: GET the storage account (`2023-05-01`), the Cosmos account (`2024-11-15`), the Search service (`2025-05-01`) and the Key Vault (`2023-07-01`) by the ids in the generated state; read `allowSharedKeyAccess`, `disableLocalAuth` twice, `enableRbacAuthorization` and each `publicNetworkAccess` (`console/azure_probe.py:449-461#probe_data`).
7. `probe_policy` -> Resource Graph: POST `/providers/Microsoft.ResourceGraph/resources` (API `2022-10-01`) with a query on the table `policyresources`, counting policy-state records by compliance state and policy reference for this assignment in this resource group. Provenance: Platform behaviour (https://learn.microsoft.com/azure/governance/resource-graph/reference/supported-tables-resources#policyresources) (`console/azure_probe.py:529-531#resource_graph`, `console/azure_probe.py:534-558#probe_policy`).
8. Console -> browser: one `probe` event per id in request order, then `finish`: `failed` if any status is `fail`, otherwise `done`, with the summary "<ok>/<total> probes OK", where only status `ok` is counted (`console/jobs.py:1139-1146#run_probes`).
9. Browser: `probeCard` draws a card per probe: a pill ("Live" for `ok`, "Check" for `warn`, "Problem" for `fail`, "Portal step" for `na`), "read at <HH:MM:SS>" with the milliseconds, the headline and a facts table (`console/web/render.js:74-81#probeCard`).

**Success outcome.** Three `probe` events and a `done` event. The shape is `_res` plus the `ms` that `run_probe` adds; the values are the code's formats with placeholders for names (`console/azure_probe.py:236-244#_res`).

```json
{"i": 1, "t": 2.9, "type": "probe", "probe": {
  "id": "foundry", "status": "ok",
  "headline": "6 project connections: 5 user-OAuth MCP tools, 1 shared-key (the legacy contrast); account keys OFF",
  "facts": [
    {"k": "Account", "v": "aif-abw-demo-<region>-<u4> (AIServices, <region>)"},
    {"k": "Project", "v": "proj-abw-wall-<u4>"},
    {"k": "Model deployment", "v": "<deployment> (<model>)"},
    {"k": "Local keys (API-key auth)", "v": "OFF - Entra only"},
    {"k": "Public network access", "v": "Enabled"},
    {"k": "Project connections", "v": "1 x CustomKeys, 5 x OAuth2"},
    {"k": "Agents", "v": "abw-wall-desk v<n>, <agent> v<n>"}
  ],
  "asOf": "<HH:MM:SS>", "ms": 1200}}
```

```json
{"i": 2, "t": 2.9, "type": "probe", "probe": {
  "id": "data", "status": "ok", "headline": "every data store is Entra-only - no account keys",
  "facts": [
    {"k": "Storage stabwdemo<region><u4>", "v": "shared key OFF, public Disabled"},
    {"k": "Cosmos <cosmos-account>", "v": "local (key) auth OFF, public Disabled"},
    {"k": "Search <search-service>", "v": "api-key auth OFF, public disabled"},
    {"k": "Key Vault <key-vault>", "v": "RBAC on, public Enabled"}
  ],
  "asOf": "<HH:MM:SS>", "ms": 900}}
```

```json
{"i": 3, "t": 2.9, "type": "probe", "probe": {
  "id": "policy", "status": "ok", "headline": "<n> compliant / <n> exempt / <n> non-compliant (by design)",
  "facts": [
    {"k": "Initiative", "v": "abw-agent-platform-controls"},
    {"k": "Compliant", "v": "<n>"},
    {"k": "Exempt (documented, with expiry)", "v": "<n>"},
    {"k": "Non-compliant", "v": "<n> - <reference list or none> (the legacy keyed path, by design)"},
    {"k": "Custom definitions", "v": "abw-foundry-no-keyed-connections, abw-foundry-approved-mcp-targets"},
    {"k": "Plus built-ins", "v": "<one sentence listing the built-in controls>"}
  ],
  "asOf": "<HH:MM:SS>", "ms": 1500}}
```

The closing line is `{"i": 4, "t": 3.0, "type": "done", "status": "done", "summary": "3/3 probes OK"}`. The connection counts follow what `scripts/foundry-connections.ps1` creates: five OAuth2 connections (research, wall, actions, vendor, private) and one custom-keys connection for the legacy path (`scripts/foundry-connections.ps1:59-66#specs`). The platform's own telemetry connection to Application Insights can add a row of another authentication type, which is why the total can be higher than six; that connection is the subject of the `exAppiAccount` and `exAppiProject` exemptions (`infra/06-governance.bicep:260-282#exAppiAccount`). The Key Vault row reads "public Enabled" because the vault keeps a public endpoint behind a firewall whose default action is Deny (`infra/03-platform.bicep:91-98#defaultAction`).

**Failure or denial outcomes.**

| Condition | Result | Job |
|-----------|--------|-----|
| Local keys are on, or fewer than five OAuth2 connections | `foundry` status `warn` (pill "Check") | `done`; the summary counts only `ok` (Findings F28) |
| Storage shared key, Cosmos local auth or Search local auth is not off | `data` status `warn`; the headline text does not change (Findings F32) | `done` |
| No Compliant rows for the assignment | `policy` status `warn` | `done` |
| An ARM call fails | That probe is `fail` with the headline "probe failed: <first 200 characters>", for example `ProbeError: ARM 403 <code>: <message>` | `failed` |
| A token cannot be minted (ARM, Graph or Logs) | No probe runs; an `error` event with the friendly text, or `ProbeError: could not get a token for <resource>: ...` | `failed` |
| An id that is not a probe, through the job API | Rejected by `validate` with "Unknown probe." | not started |
| An unknown id through `GET /api/probe/<id>` | A card with status `na` and the text that says to use the portal link or the click path | not a job |

(`console/azure_probe.py:73-89#token`, `console/azure_probe.py:833-850#run_probe`, `console/server.py:173-177#api_probe`.)

**Evidence produced.**

| Evidence | Where it lands | How to retrieve it |
|----------|----------------|--------------------|
| The three cards (tag `probe`) | Console job events of type `probe` | `GET /api/jobs/<job-id>?since=<n>` |
| A single card, fresh | The probe result, cached for 120 s unless forced | `GET /api/probe/<id>?force=1`, or all with `GET /api/probes?ids=foundry,data,policy&force=1` (`console/server.py:173-182#api_probes`) |
| The same values in the portal | Azure portal, resource properties and the policy compliance blade | The beat's `sales` line: "Open any of these in the portal - the same values are there." (`console/catalog.py:355-367#portal`) |
| The strict version of the data checks | `prove-<stamp>.json`, proof P01 | `python demo\prove.py --only P01` |
| The compliance counts | `prove-<stamp>.json`, proof P11 | `python demo\prove.py --only P11` |

**How the console runs it.** Beat definition: `console/catalog.py:355-367#probes`. Job runner: `console/jobs.py:1139-1146#run_probes`. Probe engine: `console/azure_probe.py:833-857#run_many`.

**How demo/prove.py proves it.** Beat 2.3 has no proof of its own; two proofs cover parts of it. P01 covers the data stores and is stricter than `probe_data`: it checks six service types, one pass-or-fail check per resource, including Foundry local auth, the registry's built-in shared user and Key Vault RBAC (`demo/prove.py:532-559#KEY_RULES`). P11 covers the policy counts: after the nine attempts of beat 2.1 it reads the same Resource Graph table, requires at least one row and at least one Compliant row, and prints the NonCompliant references (`demo/prove.py:1007-1018#policyresources`). Nothing in `demo/prove.py` counts the five OAuth2 connections, and the Foundry probe's threshold of five is hard-coded (Findings F32).

**Failure modes and what the presenter should say.**

- The cards show "Check" instead of "Live": read what the facts say. Do not say "all green"; a `warn` job still ends `done` (Findings F28).
- "Public network access: Enabled" on the Foundry account is real and intended; the platform keeps it for operator access and carries a documented exemption (`infra/06-governance.bicep:284-291#exFoundryNetwork`). Act 2 is about keys, not about endpoints (9.3.5).
- "Is the key really dead the moment the switch flips?" For Azure AI services, the setting changes at once in the control plane, but the data plane can keep accepting an old key for a while until its cache refreshes (from minutes up to hours); the way to confirm is to send a data-plane request with the old key and expect HTTP 401 (https://learn.microsoft.com/azure/ai-services/disable-local-auth). Provenance: Platform behaviour. This is why 2.3 reads configuration and 2.2 reads behaviour.
- One of the three tokens cannot be minted: the whole beat fails before any probe runs. Press the button again after `az login`; the network text is the friendly one in 9.3.3.
- Policy counts are policy-state records per resource and reference, not the 19 controls; do not say "19 controls compliant". The Exempt label says "documented, with expiry", but only the two legacy waivers carry an expiry (Findings F33). The NonCompliant label "the legacy keyed path, by design" is fixed text and in the scrubbed run the reference was an Audit control (Findings F29).

**Why and trade-offs.** The probes read configuration, not behaviour, and they are read-only by design: no secret is ever fetched. `probe_data` leaves Key Vault out of its `keys_off` test and shows it as a fact only; the Foundry probe fixes the threshold of five connections in code (Findings F32). The `data` headline is a constant, so it keeps saying "Entra-only" even when the status is `warn`; the status pill and the facts are the signal, not the headline.

#### 9.3.5 Act 2 evidence, proofs and presenter summary

| Beat | Layers that decided | Evidence tag | Sentinel | Proof ids |
|------|---------------------|--------------|----------|-----------|
| 2.1 nine attempts to break the rules | policy: the initiative's Deny effects and, in a tenant that has one, the organisation baseline's Modify effects | `live`, or `replay` through "Show the last run" | none | P11 |
| 2.2 evidence that no key is in use | data and monitor: the storage service's own log, read from the workspace | `logs` | none | P01 |
| 2.3 where the keys went | policy and data, read from ARM and Resource Graph | `probe` | none | P01 (data stores), P11 (policy counts) |

No Sentinel rule watches key use: the nine rules in `observability/sentinel/` are about walls, restricted orders, the legacy path, applications, revoked principals, repeated denials, drift, the guardrail and bursts (section 11.3 lists them). Act 2 is the one act whose evidence is the absence of an event.

**Three ways to know one claim.** For each service the claim "no key" can be read as configuration (what the template sets), behaviour (what the log or a live read shows) and refusal (what Azure Policy did when an attempt tried to bring a key back).

| Service | Configured as | Behaviour evidence | Refusal in beat 2.1 (outcome in the scrubbed run) |
|---------|---------------|--------------------|---------------------------------------------------|
| Storage account | shared key off, public access off (`infra/03-platform.bicep:122-138#allowSharedKeyAccess`) | `AbwZeroKeys` by authentication type (2.2); P01 | `storage-shared-key`, CORRECTED |
| Cosmos DB account | local (key) auth off, public access off (`infra/03-platform.bicep:205-230#disableLocalAuth`) | read by `probe_data` (2.3) and P01; no query classifies its log | `cosmos-local-auth`, CORRECTED |
| AI Search service | API keys off, public access off (`infra/03-platform.bicep:302-315#disableLocalAuth`) | read by `probe_data` and P01 | `search-local-auth`, BLOCKED |
| Key Vault | Azure RBAC instead of access policies (`infra/03-platform.bicep:81-96#enableRbacAuthorization`) | a fact on the data card, outside its status test (Findings F32); P01 | `keyvault-access-policies`, BLOCKED |
| Container registry | the built-in shared user off (`infra/03-platform.bicep:108-117#acr`) | P01 | `<registry-attempt-id>`, BLOCKED |
| Foundry account | local (API-key) auth off, network-injected agent runtime (`infra/foundry/modules-network-secured/ai-account-identity.bicep:52#disableLocalAuth`) | `probe_foundry` (2.3); P01 | `foundry-local-auth`, CORRECTED |
| Foundry project connections | five user-OAuth connections and one custom-keys connection for the legacy path (`scripts/foundry-connections.ps1:59-66#specs`) | `probe_foundry` counts them by authentication type (2.3) | `foundry-keyed-connection` and `foundry-unapproved-mcp`, BLOCKED |

**The keys that still exist.** "No keys" is a claim about the user path and the data stores. These secrets are real, and the presenter should be able to list them:

| Secret | Where it lives | What reaches it | Control around it |
|--------|----------------|-----------------|-------------------|
| The market-data vendor's API key | A Key Vault secret, surfaced in the gateway as the secret named value `abw-vendor-key` (`infra/05-apim-apis.bicep:81-92#nvVendorKey`) | The gateway resolves the named value when it evaluates the vendor policy (Platform behaviour: https://learn.microsoft.com/azure/api-management/api-management-howto-properties). The vendor mock holds its own copy: `DESIGN.md:147#VENDOR_API_KEY` describes a Key Vault reference, but the template stores an inline Container Apps secret (`infra/04-apps.bicep:180-190#vendor-api-key`; Findings F34) | The policy deletes the user's Authorization header and sets `x-vendor-key` from the named value, so neither agent nor user sees it (`infra/05-apim-apis.bicep:75-80#vendorSection`); beat 3.3 |
| The agent application's OAuth client secret | Inside each of the five OAuth2 Foundry connections; the connection script reads it from a local secrets file and passes it to the command that creates the connection (`scripts/foundry-connections.ps1:48#agentSecret`, `scripts/foundry-connections.ps1:86-90#client-secret`) | The Foundry connection store, when Foundry exchanges a user's stored delegated token at the identity provider (section 6) | It identifies the client application, not a person; the user's delegated token carries the identity. The script blanks it in its error output (`scripts/foundry-connections.ps1:99#secret`) |
| The legacy APIM subscription key | The custom-keys connection `mcp-legacy-key`; the script reads the primary key with an ARM `listSecrets` call and stores it as a header value (`scripts/foundry-connections.ps1:92-95#custom-keys`) | Anything that holds the connection, as a shared identity for the subscription and not a person | It is the deliberate Act 1 contrast, carried by two documented waivers that have an expiry date (`infra/06-governance.bicep:232-256#exLegacyAccount`) |
| The Application Insights connection string | The container-app secret `appi-conn` (`demo/prove.py:541#TELEMETRY_SECRET`), plus the Foundry telemetry connection | The app's runtime, for telemetry ingestion | Exempt as Mitigated (`infra/06-governance.bicep:260-282#exAppiAccount`); keyless ingestion with Entra authentication is the documented follow-up (`DESIGN.md:238#ingestion`). Provenance: Designed |
| The workspace ingestion keys | Still enabled on the Log Analytics workspace | The senders of logs | Documented as open, with the same follow-up (`DESIGN.md:238#ingestion`). Provenance: Not in this repo (no template switches them off) |

**Why and trade-offs.**

- Act 2 proves no keys, not no public endpoints. Key Vault and the registry keep public endpoints (the vault behind a firewall whose default action is Deny), and the Foundry account's public endpoint is open at the network level because its access-list default follows the public-access switch, which defaults to Enabled (`infra/03-platform.bicep:91-98#defaultAction`, `infra/03-platform.bicep:117#publicNetworkAccess`, `infra/foundry/modules-network-secured/ai-account-identity.bicep:37#defaultAction`, `infra/foundry/main.bicep:93#foundryPublicNetworkAccess`). The Foundry endpoint carries a Mitigated exemption whose stated reason is operator-laptop access (`infra/06-governance.bicep:284-291#exFoundryNetwork`; Findings F9). `probe_data` shows public access for Storage, Cosmos, Search and Key Vault as facts only; its status tests keys on Storage, Cosmos and Search and tests neither public access, Key Vault nor the registry (`console/azure_probe.py:449-461#probe_data`).
- Modify runs before Deny, so three of the nine attempts show CORRECTED, not BLOCKED (9.3.2). Do not say "nine refusals".
- Exempt is not green. The probe prints the Exempt count on its own line and the non-compliant references on another (`console/azure_probe.py:534-558#probe_policy`; Findings F33 and F29).
- `foundry-approved-tools` and `foundry-approved-models` are Audit-only by default, so they report and do not block (`infra/06-governance.bicep:25#agentToolEffect`, `infra/06a-policy-definitions.bicep:188-193#toolsEffect`; Findings F23).
- The initiative's description says "twelve-control baseline" (`infra/06a-policy-definitions.bicep:168-172#initiative`), but the set has 19 references, 11 Deny and 8 Audit at the default effect parameters (`infra/06a-policy-definitions.bicep:222-294#policyDefinitionReferenceId`, `infra/06a-policy-definitions.bicep:296-360#policyDefinitionReferenceId`; Findings F22).
- The keyed authentication types in the custom definition include `CustomKeys` and `ApiKey` but not `OAuth2`, which is why the five user-OAuth connections pass while the legacy connection needs the waiver (`infra/06a-policy-definitions.bicep:40#keyedAuthTypes`).
- Log lag is the enemy of this act: a fresh storage request is visible in the workspace after 2 to 18 minutes (section 11).

**Presenter path** (`docs/TALK-TRACK.md:156-162#AbwZeroKeys`): beat 2.1 has been running since before Act 1. Press 2.2 (about 10 s), name the two SAS rows before anyone else does, then the vendor-key sentence; optionally press 2.3 (3 s); then land it with "'No keys' is not a policy document. It is a query, `AbwZeroKeys`, and a policy that refuses the attempt." Read the result of 2.1 when the job chip shows it, at the glance in Act 3 or at the end of Act 4 if it is still running (`docs/TALK-TRACK.md:169#Glance`).

### 9.4 Act 3: Whose hands are on the data

**What this section proves.** Act 3 answers the customer question "Does internal data stay internal, and what do third-party tools get?" (`docs/PROOF-PLAYBOOK.md:376-378#Customer`). It shows three kinds of MCP server kept under one rule, a person or no key. The private server reads the firm's positions from Cosmos DB with the signed-in user's own token and cannot be found from the internet (`console/catalog.py:369-374#act3`, `src/mcp/abw_mcp/servers/private.py:19-34#get_firm_positions`). The external vendor server is meant to be reached through the gateway, which authenticates the user and swaps in the vendor's key, so the key never reaches the user or the agent (`infra/05-apim-apis.bicep:75-79#vendorSection`); the vendor app also has a public address of its own and refuses any `/mcp` call that does not carry its key (`infra/04-apps.bicep:166-173#caePub`, `demo/prove.py:742-747#gateway=False`). The act is also where the platform's largest design gap is named: the private path bypasses APIM, so the kill switch and the rate limit do not reach it (`DESIGN.md:107#kill`, Findings F10). Each beat states its provenance (Implemented, Configured, Designed, Platform behaviour, Not in this repo).

#### 9.4.1 Act overview

**Purpose.** Acts 1 and 2 asked who may call a tool and whether any key is in use. Act 3 asks what each kind of tool server can see and how it is attached. There are three beats: 3.1 internal data through the private server (an agent run, about 20 s), 3.2 a two-place DNS test of the private server's host name (about 1 s), 3.3 a quote from the external vendor through the gateway (about 3 s) (`console/catalog.py:369-410#act3`). All three are `live`; 3.1 and 3.3 also leave `logs` evidence that arrives later (section 11 has the lag table).

**The three kinds of MCP server.**

| Kind | Servers | Where the app runs and how it is reached | Where the user's token is checked | How data is reached | Kill switch, rate limit, gateway telemetry |
|------|---------|------------------------------------------|-----------------------------------|---------------------|---------------------------------------------|
| Internal | `research`, `wall`, `actions` | Container Apps on the internal-ingress host, reached through APIM backends (`infra/04-apps.bicep:86-100#research`, `infra/05-apim-apis.bicep:94-106#validateCertificateChain`) | At APIM (G2 to G4) and again in the server (G6) (9.1.8) | The server exchanges the user's token on behalf of the user for the data store's token (G8) | All three apply |
| Private | `private` | The same internal-ingress host, but the Foundry connection points straight at the app, and the app is not an APIM API (`infra/04-apps.bicep:131-141#privateMcp`, `src/agent/abw_agents.py:95-106#server_urls`, `demo/mcpclient.py:41-44#DIRECT`) | Only in the server (G6) | On-behalf-of exchange for Cosmos DB (G8) | None of them (`DESIGN.md:107#kill`; Findings F10) |
| External | `vendor` | A mock vendor app on the public host (`infra/04-apps.bicep:166-181#vendor`); the gateway is the route the deployment registers for it, but the app also has a public address of its own and refuses `/mcp` calls without its key (`infra/modules/mcp-app.bicep:39-44#externalIngress`) | At APIM only; the vendor app checks a shared key and never sees the user's token (`DESIGN.md:93#MarketData.Read`) | No user token: the app returns synthetic data and sets `obo` false (`src/mcp/abw_mcp/servers/vendor.py:30-43#get_market_quote`) | Gateway rules apply; the vendor's own audit has no user (Findings F4) |

Two things follow from the table. First, "private" is a routing and approval choice, not a separate network: the private app lives on the same internal host as the research, wall, actions and legacy apps (`infra/04-apps.bicep:86-141#caePriv`, `infra/04-apps.bicep:146-152#caePriv`), and what stops a Foundry connection from pointing at any other host directly is the approved-target Azure Policy control (9.3.2, `infra/06-governance.bicep:162-168#approvedMcpEndpoints`). Second, every app module takes the default `external: true` ingress setting (`infra/modules/mcp-app.bicep:15#externalIngress`, `infra/modules/mcp-app.bicep:40#external`); on the internal host that means reachable inside the virtual network, on the public host it means the internet (Platform behaviour: https://learn.microsoft.com/azure/container-apps/private-endpoints-with-dns#ingress-for-the-virtual-network-scope).

**Actors and tokens.**

| Beat | Console action | Identity | Token on the wire | Answered by |
|------|----------------|----------|-------------------|-------------|
| 3.1 | "Ask about positions", an `agent` job (`console/catalog.py:375-381#abw-wall-desk`) | The operator, through the Foundry agent `abw-wall-desk`; mirrors Wes and Tara (`console/jobs.py:60-61#WHO_NOTE`) | The delegated token Foundry stored for connection `mcp-private-oauth` (the `aud` claim is the private application, scope `Tools.Read`, `azp` the agent's OAuth client); the server then exchanges it on behalf of the user for a Cosmos DB token (`scripts/foundry-connections.ps1:59-66#specs`, `src/mcp/abw_mcp/obo.py:64-74#acquire_token_on_behalf_of`; section 6) | The private server (token and role) and Cosmos DB's own data-plane roles |
| 3.2 | "Check DNS", a `private` job (`console/catalog.py:387-393#private`) | None | None: two DNS lookups | A public resolver and the console host's own resolver |
| 3.3 | "Get a vendor quote", a `gateway` job (`console/catalog.py:399-405#get_market_quote`) | The operator | The operator's delegated token for the vendor gateway application (scope `api://<vendor-gateway-app>/Tools.Read`), sent in an Authorization header carrying the Bearer-scheme access token; APIM removes it before the vendor sees the request (`demo/mcpclient.py:47-48#scope_for`, `demo/mcpclient.py:76-86#acquire_token_silent`, `infra/05-apim-apis.bicep:75-79#vendorSection`) | APIM (token, role, key swap), then the vendor app (key only) |

Each Foundry connection has its own scope and its own target application, so the tokens in rows 1.2 to 3.1 are not "the same user token" even though the user and the OAuth client are the same (`scripts/foundry-connections.ps1:59-66#specs`; Findings F25).

**Preconditions.**

1. The role baseline of 9.2.1 is applied to the operator before the first consent: `Positions.Read` (Tara and Carla hold it) for the private server and `MarketData.Read` (four of the five personas hold it, all but Ian) for the vendor (`DESIGN.md:76-80#MarketData.Read`, `console/jobs.py:60-61#WHO_NOTE`). Foundry keeps the stored token for its whole life (Entra lifetimes are 60 to 90 minutes: `DESIGN.md:223#Foundry`), so a baseline applied later reaches the agent late.
2. For 3.1 the operator is a member of an Entra group that holds a Cosmos DB data role on the `positions` container: the traders group (built-in data reader) or the compliance group (`infra/03-platform.bicep:676-700#cosmosTradersPositions`). The helper that mirrors the roles also mirrors group memberships (`README.md:88#mirrors`; the group part is stated in the helper's own header in the `identity` folder).
3. For 3.1 the private server's `COSMOS_OBO` setting is true, which is the default (`infra/04-apps.bicep:30#cosmosObo`, `src/mcp/abw_mcp/config.py:154-155#cosmos_obo`). With it false the server would read with its own identity, which holds no Cosmos role (9.4.2).
4. For 3.2 the private DNS zone is linked to the virtual network and the deployment outputs hold the private app's host name (`infra/modules/aca-dns.bicep:50-60#link`, `demo/mcpclient.py:37#APPS`).
5. For 3.3 the vendor secret exists in Key Vault, APIM's system identity can read it, and the named value `abw-vendor-key` resolves it (`infra/04-apps.bicep:43-50#vendorKeySecret`, `infra/05-apim.bicep:225-231#raApimKv`, `infra/05-apim-apis.bicep:81-92#nvVendorKey`).
6. The kill switch is released, so the job manager does not refuse gateway or agent jobs (`console/jobs.py:495#NEEDS_OPEN_GATEWAY`).

**Why and trade-offs.** The three kinds map to three customer situations: systems of record that should not sit on a shared gateway, internal tools that benefit from central policy, and third-party tools that need their own credential. The private kind gives up the central kill switch (`DESIGN.md:107#kill`) and, because the path never touches APIM, the rate limit and the gateway telemetry as well (Findings F10); the stated reason for the choice is that some systems of record should never sit behind a public gateway (`docs/PROOF-PLAYBOOK.md:1447#AbwGateway`). The external kind gives up user identity at the vendor in exchange for never handing the vendor the user's token (Findings F4). Neither choice is free, and the presenter should say so.

#### 9.4.2 Beat 3.1: Internal data through the private MCP

**Purpose.** The agent reads one desk's positions and one counterparty's credit limit from Cosmos DB through the private server. The server is attached to the agent directly and verifies the user's token itself. It then exchanges that token for a Cosmos DB token that still names the user, so the database decides, request by request, whether this person may read the `positions` container. The server's own identity holds no Cosmos role at all. The take-away for the room: internal systems of record stay off the internet and off the shared gateway, and the agent holds no standing credential to them (`console/catalog.py:375-386#abw-wall-desk`). The prompt asks for the positions of one desk and the credit-limit headroom of one counterparty, so the model is expected to call two tools, and the scrubbed run shows exactly two calls (`console/catalog.py:39#positions`, `demo/evidence-scrubbed/20261022-123053-abw-wall-desk-operator.json:15-16`). Provenance: Implemented (server, handlers, on-behalf-of exchange), Configured (network, role assignments), Designed (withdrawal through group membership), Platform behaviour (Cosmos DB's own data-plane roles).

**Actors and tokens.** The operator signs in to Foundry exactly as in 9.2.3. Two tokens matter on the private path (section 6 gives the full token chain):

| Token | Issued for | Key claims | Carried by | Checked by |
|-------|-----------|------------|------------|------------|
| Stored delegated token for connection `mcp-private-oauth` | The operator, to the agent's OAuth client, at consent; requested scope `api://<private-app>/Tools.Read` plus `offline_access` (`scripts/foundry-connections.ps1:55-57#Get-Scope`, `scripts/foundry-connections.ps1:59-66#specs`) | `aud` is the private application, `scp` is `Tools.Read`, `azp` is the agent's OAuth client, `ver` is 2.0, `roles` must include `Positions.Read` | An Authorization header carrying the Bearer-scheme access token, from the Foundry tool runtime to `https://<private-host>/mcp` | `BearerAuthMiddleware` and the tool registry in the private server (`src/mcp/abw_mcp/auth.py:108-170#verify_token`) |
| On-behalf-of Cosmos DB token | The same user, minted inside the private server during the call; the incoming token is the user assertion and a managed-identity token for `api://AzureADTokenExchange/.default` is the client assertion; requested scope `https://cosmos.azure.com/user_impersonation` (`src/mcp/abw_mcp/obo.py:39-58#OboBroker`, `src/mcp/abw_mcp/obo.py:64-74#acquire_token_on_behalf_of`, `src/mcp/abw_mcp/obo.py:77-79#_get_client_assertion`, `src/mcp/abw_mcp/config.py:154-155#cosmos_obo_scope`) | `aud` is Cosmos DB; the subject is still the user | Handed to a new Cosmos DB client as a static token credential (`src/mcp/abw_mcp/obo.py:29-33#StaticTokenCredential`) | Cosmos DB's own data-plane roles (the group role assignments of step 9) |

The server's own managed identity appears only as the client assertion that lets the server redeem the user's token (`DESIGN.md:105#OBO`). It is never the identity that reads the data. Provenance: Implemented.

**Preconditions.** Those of 9.4.1, items 1 to 3, and also: the `positions` container is seeded with six position documents per desk and four credit-limit documents that share the container (`src/seed/seed.py:209-253#seed_cosmos`); the operator has consented to the `mcp-private-oauth` connection, and the role baseline was applied before that consent (`DESIGN.md:226#Consent`).

**Sequence.**

1. Browser -> console: "Ask about positions" posts `{"kind":"agent","params":{"agent":"abw-wall-desk","prompt":"positions","approve":"yes"},"beat":"3.1"}`. Steps 1 to 3 of 9.2.3 apply unchanged: `agent_once` picks the entry route, `agent_run.py` sends the prompt to the stored agent through the Responses API, and Foundry loads the agent with five MCP tools, one per server (`console/catalog.py:375-381#abw-wall-desk`, `console/jobs.py:719-721#agent_via`, `src/agent/abw_agents.py:119-139#wall_desk_tools`).
2. Foundry tool runtime -> private server: `initialize`, then `tools/list`, to `https://<private-host>/mcp`. Four of the five tool entries take their URL from the gateway list of the deployment outputs; the private entry takes the Container Apps address of the private app itself. The call leaves the Foundry agent runtime, which is injected into the delegated agent subnet `snet-agent`, and reaches the internal host over the virtual network. The private app's advertised base URL is its own address, where the other servers advertise the gateway's (`src/agent/abw_agents.py:95-106#server_urls`, `scripts/foundry-connections.ps1:59-66#specs`, `infra/01-network.bicep:160-165#snet-agent`, `infra/03-platform.bicep:385-388#internal`, `infra/04-apps.bicep:75#privateFqdn`). Provenance: Configured. The runtime injection and the private-MCP pattern (internal-only ingress on a dedicated subnet delegated to the Container Apps service) are Platform behaviour (https://learn.microsoft.com/azure/foundry/agents/how-to/virtual-networks, https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol#public-and-private-mcp-server-endpoints). Designed: `DESIGN.md:107#kill`.
3. APIM is not on this path. The private app is not an APIM API, so there is no `validate-jwt`, no `abw-deny` check, no kill switch, no limit of 120 calls per 60 seconds per user, no `x-abw-request-id` header and no gateway decision metric or trace for this call (`infra/apim/policies/mcp-jwt.policy.xml:81-87#rate-limit-by-key`, `demo/mcpclient.py:41-44#DIRECT`). Hops G1 to G5 of 9.1.8 do not happen.
4. Request id: the server's request-context middleware takes the first of the headers `x-abw-request-id`, `x-request-id`, `x-ms-request-id` and `traceparent`; when none is present it mints `req-<epoch ms>`. No code in this repository sets one for the call from Foundry to the private server. The scrubbed record of this beat in `demo/evidence-scrubbed/` shows the agent's answer quoting two different GUID-shaped request ids, one per private tool call, so in that run the tool runtime did forward a header with a GUID value; which header it was is not established (`src/mcp/abw_mcp/auth.py:173-189#RequestContextMiddleware`; Findings F38).
5. G6, the private server verifies the token itself. `BearerAuthMiddleware` guards only the path `/mcp`; `verify_token` loads the signing keys from a cached key set, checks the RS256 signature, `exp`, `nbf` (60 seconds of leeway) and the issuer; the token must be addressed to this server's own application; `ver` must be 2.0; the tenant must be ours; an app-only token, or a token without `oid`, is refused as `app_only`; when `MCP_ALLOWED_AZP` is set, as the deployment does, `azp` must be on the allow-list; `scp` must contain `Tools.Read`; roles come from the `roles` claim. A failure returns 401, or 403 for `missing_scope`, with an `auth_failed` audit event that has no user identity. `AuthError` would map `missing_role` to 403 too, but the middleware raises it only when it is given an `authorization_check`, and `app.py` registers it without one (`src/mcp/abw_mcp/app.py:244-249#BearerAuthMiddleware`); a missing role is therefore not refused here but by the tool layer, as a DENIED result with HTTP 200 (`src/mcp/abw_mcp/registry.py:98-108#require_any_role`; see Failure or denial outcomes below). Section 6 lists the checks in order (`src/mcp/abw_mcp/auth.py:191-248#BearerAuthMiddleware`, `src/mcp/abw_mcp/auth.py:108-170#verify_token`, `src/mcp/abw_mcp/auth.py:151-153#bad_azp`, `src/mcp/abw_mcp/auth.py:44-57#AuthError`, `infra/04-apps.bicep:77-84#serverEnv`).
6. G6 and G7, `tools/list`: `list_tools` returns only the tools whose requirement the caller meets. Both private tools require any of `Positions.Read`, so a caller without that role sees an empty list. One `tool_listed` audit event is written per visible tool (`src/mcp/abw_mcp/registry.py:132-156#list_tools`, `src/mcp/abw_mcp/servers/private.py:59-77#build_tools`, `src/mcp/abw_mcp/registry.py:98-106#require_any_role`).
7. Foundry -> model -> tool runtime: the model chooses its calls. For `tools/call get_firm_positions` the registry re-evaluates the requirement, so a call to a tool that was not listed is still refused, and then validates the arguments against `PositionsArgs` (`desk` must match `^[a-z0-9_-]{1,32}$`). No approval prompt appears: only `place_order` requires approval (`src/mcp/abw_mcp/registry.py:158-220#call_tool`, `src/mcp/abw_mcp/servers/private.py:11-12#PositionsArgs`, `src/agent/abw_agents.py:49#APPROVAL_REQUIRED`).
8. G8, the on-behalf-of exchange. `get_firm_positions` calls `cosmos_query_items` with `use_user_token` taken from the `COSMOS_OBO` setting (default true) and the scope `https://cosmos.azure.com/user_impersonation`. `_get_cosmos_container` creates a new Cosmos client for every call. When the caller or the broker is missing it raises `OboError("missing_caller")`; otherwise `OboBroker.get_credential` runs the exchange in the MSAL confidential client and wraps the result in a static token credential. The query is `SELECT c.id, c.ticker, c.quantity, c.market_value_usd FROM c WHERE c.desk = @desk`, run inside the partition whose key is the desk; the handler keeps rows that have a ticker and whose id does not start with `limit-`, which removes the credit-limit documents (`src/mcp/abw_mcp/servers/private.py:19-34#get_firm_positions`, `src/mcp/abw_mcp/data.py:118-135#cosmos_query_items`, `src/mcp/abw_mcp/data.py:170-189#_get_cosmos_container`, `src/mcp/abw_mcp/obo.py:60-62#get_credential`, `infra/04-apps.bicep:30#cosmosObo`).
9. Cosmos DB data plane. The account has key authentication disabled, public network access disabled and a private endpoint (`infra/03-platform.bicep:225-231#disableLocalAuth`, `infra/03-platform.bicep:337-347#peCosmos`). Cosmos DB evaluates the data-plane role assignments for the token's principal. On `positions` there are exactly two: the built-in Data Reader role (its id ends in `...0001`) for the traders group and for the compliance group, at the scope of that one container. The private server's identity has no assignment, and the seeding job has its own (`infra/03-platform.bicep:676-700#cosmosTradersPositions`, `infra/04b-seed-job.bicep:91-98#cosmosSeed`). Because the OBO token carries the user, the evaluation is made against the user (or the user's group); the playbook's data-plane query shows the user's object id as the principal (`docs/PROOF-PLAYBOOK.md:383-387#AadPrincipalId`). The Data Reader role includes item read, query and change-feed reads, and role assignments can be scoped to a single container (Platform behaviour: https://learn.microsoft.com/azure/cosmos-db/reference-data-plane-security#built-in-roles, https://learn.microsoft.com/azure/cosmos-db/how-to-connect-role-based-access-control#grant-data-plane-role-based-access). Designed: that removing the user from both groups denies the read while the token still verifies (`DESIGN.md:33#OBO`). No proof removes a group membership for Cosmos DB; P16 does it for Storage only (9.2.5), and the repository does not show Cosmos DB's handling of group principals, so treat the Cosmos case as designed, not demonstrated.
10. G9, audit. `call_tool` adds `request_id` to the payload and writes one `tool_call` event: decision allow, the user's `user_oid` and `user_upn`, `tid`, `roles`, `scp`, `azp`, `aud`, `jti`, `obo` true, downstream `{"service":"cosmos","target":"positions","status":200}`, `data_class` internal, `args_sha256`, `result_bytes`. The event goes to three places: standard output (collected into `ContainerAppConsoleLogs`), the `abw.audit` logger that is bound to Azure Monitor, and an append blob named `private/<yyyy>/<mm>/<dd>/private.jsonl` in the `worm-audit` container, written with the server's managed identity (`src/mcp/abw_mcp/registry.py:197-218#setdefault`, `src/mcp/abw_mcp/audit.py:178-217#build_event`, `src/mcp/abw_mcp/audit.py:40-51#StdoutLoggerAuditSink`, `src/mcp/abw_mcp/audit.py:125-135#jsonl`, `src/mcp/abw_mcp/audit.py:219-223#build_default_audit_service`, `src/mcp/abw_mcp/app.py:63-70#logger_name`). No gateway row exists for the call.
11. `get_credit_limit`: the same chain. The handler reads one document by id `limit-<slug of the counterparty>` with partition key `credit` from the same container, again with the user's OBO token. A missing document raises `NOT_FOUND` with reason `counterparty_not_found`; a Cosmos 404 is turned into `None` and any other Cosmos error is re-raised (`src/mcp/abw_mcp/servers/private.py:37-56#get_credit_limit`, `src/mcp/abw_mcp/data.py:99-116#cosmos_read_item`, `src/mcp/abw_mcp/data.py:149-150#credit_limit_id`).
12. Model -> answer, then child process -> console. Each `mcp_call` item becomes a `call` event with server `private`. `judge` turns the decision, status and reason into a verdict. `lights_for_call` lights `user`, `entra`, `foundry`, `apim`, `m-private` and `data` for an allowed call; `apim` is lit although this call never touched APIM (Findings F37), and `data` is lit for any successful call (Findings F21). The card's request id is taken by a regular expression that accepts only hex digits and dashes, so a GUID shows and a minted `req-<epoch ms>` id would leave the card without one (`console/jobs.py:745-760#verdict`, `console/jobs.py:176-195#judge`, `console/catalog.py:173-190#lights_for_call`, `console/agent_run.py:30#REQUEST_ID`; Findings F38).

**Success outcome.** Each tool result is one text item holding compact JSON in insertion order, plus the same object as `structuredContent`; `isError` is not set. The server appends `request_id` last, and only when the request context holds one (`src/mcp/abw_mcp/registry.py:195-220#payload_text`, `src/mcp/abw_mcp/util.py:27-30#compact_json`). `get_firm_positions` returns one object per position, six for each seeded desk (`src/mcp/abw_mcp/servers/private.py:19-34#get_firm_positions`, `src/seed/seed.py:209-253#seed_cosmos`):

```json
{"desk":"<desk>","positions":[{"ticker":"<ticker>","quantity":<quantity>,"market_value_usd":<market-value>}],"request_id":"<request-id>"}
```

`get_credit_limit` returns (`src/mcp/abw_mcp/servers/private.py:37-56#get_credit_limit`):

```json
{"counterparty":"<counterparty>","limit_usd":<limit>,"utilization_usd":<utilization>,"request_id":"<request-id>"}
```

An unknown desk is not an error: the query matches no document, `positions` is an empty list, and the call is audited as allowed. The audit event of an allowed call (a `tool_call`) is written as one compact line with sorted keys on standard output; the block below only adds line breaks (`src/mcp/abw_mcp/audit.py:178-217#build_event`, `src/mcp/abw_mcp/audit.py:40-51#StdoutLoggerAuditSink`, `src/mcp/abw_mcp/util.py:14-17#canonical_json`):

```json
{
  "args_sha256": "<sha256>",
  "aud": "<private-app-id>",
  "azp": "<client-id>",
  "data_class": "internal",
  "decision": "allow",
  "downstream": {"service": "cosmos", "status": 200, "target": "positions"},
  "event": "tool_call",
  "jti": "<token-id>",
  "obo": true,
  "reason": null,
  "request_id": "<request-id>",
  "result_bytes": <n>,
  "roles": ["Positions.Read"],
  "scp": "Tools.Read",
  "server": "private",
  "tid": "<tenant-id>",
  "tool": "get_firm_positions",
  "trace_id": "<trace-id>",
  "ts": "<utc-time>",
  "user_oid": "<user-oid>",
  "user_upn": "<operator-upn>"
}
```

Field notes. `user_upn` is the `preferred_username` claim, `roles` is the sorted `roles` claim, `scp` is the scope string, and `jti` holds the `uti` claim when the token carries one (`src/mcp/abw_mcp/auth.py:108-170#uti`). `reason` is null because the private registry is built without a default reason; only the legacy server has one (`src/mcp/abw_mcp/app.py:49-60#_build_registry`). `downstream.status` is a literal 200 written by the handler, not a response code measured from Cosmos DB (`src/mcp/abw_mcp/servers/private.py:34#downstream`). `args_sha256` is the SHA-256 of the canonical JSON of the arguments, so the line proves which arguments were used without storing them. `trace_id` is the 32-hex trace id of the active span, or null (`src/mcp/abw_mcp/audit.py:146-153#trace_id_from_context`). The same shape is written once per visible tool when the tool list is requested, with `event` `tool_listed`, `args_sha256` null, `result_bytes` 0 and an empty `downstream`; the number of those events in a run therefore shows whether the caller was entitled to the private tools (`src/mcp/abw_mcp/registry.py:132-156#list_tools`).

The console shows the run as a stream of events. The `tools` event carries one entry per attached server, and only the private entry is shown here; the `call` event is one per tool call (keys from `console/jobs.py:757-759#excerpt`, verdict block from `console/jobs.py:176-198#judge`, lights from `console/catalog.py:173-190#lights_for_call`, the tools event from `console/jobs.py:724-728#flush_tools`):

```json
{"type": "tools", "servers": {"private": ["get_firm_positions", "get_credit_limit"]}, "lights": {"foundry": "ok"}}
{
  "type": "call", "server": "private", "tool": "get_firm_positions",
  "args": "{\"desk\": \"<desk>\"}", "request_id": "<request-id>",
  "decision": null, "reason": "", "excerpt": "<result, cut for display>",
  "leak": [], "attack": "",
  "verdict": "allowed", "wall": null, "title": "Allowed",
  "plain": "Every layer in the path agreed.",
  "lights": {"user": "ok", "entra": "ok", "foundry": "ok", "apim": "ok", "m-private": "ok", "data": "ok"}
}
```

`decision` is null because a successful result has no `decision` key; `reason` is the empty string because the verdict block overrides it; `request_id` is null when the id is not hex digits and dashes (Findings F38); the `apim` light is green although APIM is not on this path (Findings F37). The run then ends with `{"type":"answer","text":"<model text>","seconds":<n>,"tokens_in":<n>,"tokens_out":<n>,"status":"completed","via":"apim","rounds":<n>,"gateway_ids":["<request-id>"]}`. Its `gateway_ids` are the ids of the front door's model rounds, read from the `x-abw-request-id` response header of each round, and are not the id of the private tool call, which never passed APIM (`console/jobs.py:799-801#gateway_ids`, `console/agent_run.py:88-98#gateway_ids`). The closing event is `{"type":"done","status":"done","summary":"2 tool calls, 2 allowed"}` (`console/jobs.py:808-827#agent_summary`, `console/jobs.py:296-304#finish`). The scrubbed response record of this beat in `demo/evidence-scrubbed/` has one turn with eight items, five `mcp_list_tools` (one per attached server), two `mcp_call` and one `message`, status `completed`, about 18 s; the scrubbed proof run lists both private tools as ok.

**Failure or denial outcomes.** The wall that decides is the MCP server (wall 2) or Cosmos DB (wall 3); there is no gateway wall on this path. In every row the payload is the exact compact JSON the registry builds; `<policy note>` stands for the fixed sentence "Blocked by policy and written to the audit log. Tell the user what was blocked and the reason code; do not retry, rephrase or look for a workaround." (`src/mcp/abw_mcp/registry.py:273-292#_error_payload`).

| Situation | What happens | Shape and wall |
|-----------|--------------|----------------|
| The user lacks `Positions.Read` (the designed outcome for Priya, Wes and Ian; Tara and Carla hold the role) | `tools/list` shows no private tool and writes no `tool_listed` event, so the console `tools` event shows an empty list for `private` and the model has nothing to call. A call that arrives anyway meets the same requirement check in `call_tool` (`console/role_story.py:528-535#DESIGNED`, `src/mcp/abw_mcp/registry.py:98-108#require_any_role`, `src/mcp/abw_mcp/registry.py:163-165#FORBIDDEN`) | Soft denial, HTTP 200, `isError` unset: `{"decision":"DENIED","error":"FORBIDDEN","message":"Tool unavailable for this caller.","reason":"missing_role","request_id":"<request-id>","note":"<policy note>"}`. Audit event `tool_denied`, decision deny, `args_sha256` of `{}` (the arguments are not read), the user's identity filled in, `obo` true (Findings F2). Decided by the MCP registry, wall 2. The console words it as wall 1 "The gateway said no" and lights `apim` red (Findings F39). Test: `src/mcp/tests/test_servers.py:251-266#missing_role` |
| An unknown counterparty | The handler raises `NOT_FOUND` after the point read returns nothing (`src/mcp/abw_mcp/servers/private.py:37-56#counterparty_not_found`) | `{"decision":"ERROR","error":"NOT_FOUND","message":"Credit limit not found.","reason":"counterparty_not_found","request_id":"<request-id>"}`, no note. The audit event is still `tool_denied` with decision deny, because `ToolError` defaults to a denial (Findings F36). The console verdict is "failed", title "The agent run failed", with lights `user` and `entra` only (Findings F42) |
| A bad or extra argument (a desk outside the pattern, an unknown key) | `ArgsModel` forbids extra keys; validation fails before the handler runs (`src/mcp/abw_mcp/registry.py:24-27#ArgsModel`, `src/mcp/abw_mcp/registry.py:167-175#invalid_arguments`) | `{"decision":"ERROR","error":"INVALID_ARGUMENT","message":"<field>: <validation message>","reason":"invalid_arguments","request_id":"<request-id>","note":"Fix the arguments to match the tool schema and retry once."}`. Audit `tool_denied`, deny, `obo` false, `args_sha256` of the arguments as offered. Console: "The agent run failed" (Findings F42) |
| The on-behalf-of exchange fails (`missing_caller`, an Entra error code, `unknown_error`) | The handler raises `OboError`. The registry refuses the call and does not fall back to the server's own identity (`src/mcp/abw_mcp/registry.py:179-190#obo_failed`, `src/mcp/tests/test_servers.py:141-156#obo_failed`, `src/mcp/abw_mcp/obo.py:20-25#OboError`) | `{"decision":"DENIED","error":"FORBIDDEN","message":"Unable to acquire downstream user token.","reason":"obo_failed:<code>","request_id":"<request-id>","note":"<policy note>"}`. Audit `tool_denied`, deny, `obo` still true (Findings F2), `downstream` empty. The reason is not in the console's reason table, so the verdict is denied with title "Refused", plain text "A control refused this call.", no wall, and `foundry`, `apim` and `m-private` all lit green with nothing red (`console/catalog.py:118-126#explain`) |
| Cosmos DB refuses the user (in neither group, a group removed, or `COSMOS_OBO` false so the server's own identity, which holds no role, is used) | Cosmos DB answers 403. The data helpers map only a 404; the 403 is neither an `OboError` nor a `ToolError`, so `call_tool` writes no audit event for the call, and what the MCP library puts on the wire is not established by this repository (`src/mcp/abw_mcp/data.py:99-135#cosmos_read_item`, `src/mcp/abw_mcp/registry.py:179-193#OboError`; Findings F3) | Designed, not demonstrated. Wall 3. Expected evidence: a `CDBDataPlaneRequests` row with `StatusCode` 403 for the user's principal, and no `tool_call` row in the MCP audit. Findings F43 notes that the exchange blocks the event loop |
| The server rejects the token (expired, wrong application, `azp` not on the allow-list, no `Tools.Read`) | `BearerAuthMiddleware` answers before any MCP handling (`src/mcp/abw_mcp/auth.py:191-248#BearerAuthMiddleware`, `src/mcp/abw_mcp/auth.py:44-57#AuthError`) | HTTP 401 `{"error":"invalid_token","error_description":"<reason code>"}`, or 403 `{"error":"insufficient_scope",...}` for `missing_scope` only, plus a `WWW-Authenticate` header (`src/mcp/abw_mcp/auth.py:250-260#_auth_error_response`). `AuthError` also maps `missing_role` to 403, but nothing raises it on this path because the middleware has no `authorization_check` (`src/mcp/abw_mcp/app.py:244-249#BearerAuthMiddleware`); a missing role is the soft denial of the first row. Audit `auth_failed`, deny, no user fields, `obo` false. What Foundry shows for it is not established. G6 |
| The user is revoked at the gateway (the kill switch of 9.5, beat 4.5) | No effect: the private path never touches APIM (`DESIGN.md:107#kill`) | The call still succeeds until the stored token expires or the group role is withdrawn (Findings F10) |
| `MCP_DENIAL_MODE` is `strict` | Denials and errors carry `isError` true; the code comment says Foundry then aborts the whole run with HTTP 400 `tool_user_error`, which is the repository's statement, not a verified platform fact (`src/mcp/abw_mcp/registry.py:263-270#isError`) | Not set in this deployment, so the default `soft` applies (`src/mcp/abw_mcp/config.py:59#denial_mode`, `src/mcp/abw_mcp/config.py:157#MCP_DENIAL_MODE`, `infra/04-apps.bicep:53-68#commonEnv`, `DESIGN.md:132#MCP_DENIAL_MODE`) |

**Evidence produced.** Beat 3.1 leaves evidence in six places. Only the first is immediate; the rest are read afterwards, and the log-based ones lag the click (the console's own lag statement is 2 to 18 minutes for Log Analytics, `console/web/render.js:300#TR_LAG`; section 11 holds the lag table).

| Evidence | Where it lands | How to retrieve it |
|----------|----------------|--------------------|
| Console events `tools`, `call`, `answer`, `done` | The job's event list in the console process; each event is numbered and timed when it is emitted and the browser reads the list through the job view (`console/jobs.py:276-280#emit`, `console/jobs.py:288-294#view`) | Immediate: it is the job card of the beat (`<job-id>`) |
| The Foundry response record | A JSON file written by the command-line client when it is run with `--save`, in the repository's `demo/evidence` folder; the client prints `saved <path>`. The console run does not write it, the proof script does (`src/agent/ask.py:270-277#saved`, `demo/prove.py:384-402#ask_agent`) | `demo/evidence-scrubbed/` holds a scrubbed copy of one run: `ts`, `agent`, `as`, `prompt`, `turns`, `answer`, `response_id`, `status`, `failure`, `seconds`, with the `mcp_list_tools` and `mcp_call` items inside the turn |
| MCP audit events: `tool_listed` per visible tool, `tool_call` per call | Three sinks: standard output, which the platform collects into workspace table `ContainerAppConsoleLogs`, column `Log`; the `abw.audit` logger, bound to Application Insights only when a connection string is present; and the append blob `private/<yyyy>/<mm>/<dd>/private.jsonl` in container `worm-audit` (`src/mcp/abw_mcp/audit.py:219-223#build_default_audit_service`, `src/mcp/abw_mcp/app.py:63-70#logger_name`, `infra/04-apps.bicep:53-68#appi-conn`, `src/mcp/abw_mcp/audit.py:125-135#jsonl`) | The first KQL block below, through the saved function (`observability/kql/AbwMcpAudit.kql:1-34#ContainerAppConsoleLogs`). No saved function in the repository reads the Application Insights copy. The blob is read with a Storage data-plane read; its one-day retention is not locked (`infra/03-platform.bicep:195-202#wormPolicy`) |
| Cosmos DB data-plane log | Workspace table `CDBDataPlaneRequests`, fed by a diagnostic setting that sends all logs to the workspace in dedicated tables (`infra/03-platform.bicep:478-491#diagCosmos`). Provenance: Platform behaviour (https://learn.microsoft.com/azure/azure-monitor/reference/tables/cdbdataplanerequests) | The second and third KQL blocks below |
| The joined chain | `AbwFullChainCore('<request-id>')` | The MCP row of this call carries the label "direct VNet path, no APIM" (`observability/kql/AbwFullChainCore.kql:149-160#mcpRows`); its Cosmos rows are matched by time only (Findings F40); the request-id join needs a GUID-shaped id (Findings F38) |
| No gateway row, no alert | `ApiManagementGatewayLogs` has no row for this call, because no gateway is on the path (`DESIGN.md:107#kill`; Designed. The playbook records a live run, tagged seen, in which `AbwGateway(1d) \| where Server == 'private' \| summarize n = count()` returned 0: `docs/PROOF-PLAYBOOK.md:1447#AbwGateway`, tag meaning at `docs/PROOF-PLAYBOOK.md:31#seen`. No scrubbed run record holds it). No Sentinel rule fires on an allowed call; rule ABW-006 counts private-server denials (`observability/sentinel/abw-006-repeated-denials.kql:11-15#AbwDenials`, Findings F36) | `AbwGateway(24h) \| where RequestId == '<request-id>'` returns nothing for this call (`observability/kql/AbwGateway.kql:1-12#AbwGateway`) |

```kusto
AbwMcpAudit(24h)
| where Server == 'private'
| project TimeGenerated, Event, Tool, Decision, Reason, UserUpn, OnBehalfOf, DataClass, DownstreamService, DownstreamStatus, RequestId, TraceId
| order by TimeGenerated desc
```

The two playbook queries read the Cosmos DB log (`docs/PROOF-PLAYBOOK.md:383-393#AadPrincipalId`):

```kusto
CDBDataPlaneRequests | where TimeGenerated > ago(24h) and DatabaseName == 'abw' | summarize Requests=count(), Last=max(TimeGenerated) by CollectionName, OperationName, AuthTokenType, AadPrincipalId | order by Last desc
```

```kusto
CDBDataPlaneRequests | where TimeGenerated > ago(24h) | summarize Requests=count() by AuthTokenType, KeyType
```

What the playbook records as seen: every row of the first query is an Entra token (`AadToken`); the positions reads and the order writes carry the operator's own object id, the person and not the server; the reads of the `restricted` reference container carry the actions server's own managed identity, which the presenter is told to disclose because it is firm reference data and not user data; and the second query returns one row with `AadToken` in both columns, so no request used a key. The land line is: "Internal systems of record, no new network exposure, and Cosmos names the person." (`docs/PROOF-PLAYBOOK.md:394#LAND`). Two properties make the evidence strong: the principal that Cosmos DB logs is the one whose token it checked, and the audit line carries the same token id (`TokenId`, the `jti`) for every run during the life of the stored token (Entra lifetimes are 60 to 90 minutes: `DESIGN.md:223#Foundry`, `demo/prove.py:405-410#settle_agent`).

**How the console runs it.**

1. The beat is the catalog entry of 3.1: kind `agent`, agent `abw-wall-desk`, the prompt key `positions` (a fixed prompt that asks for one desk's positions and one counterparty's credit headroom), approval `yes`, "about 20 s", and the nodes `m-private` and `data` as the things to point at (`console/catalog.py:375-386#abw-wall-desk`, `console/catalog.py:33-39#PROMPTS`).
2. The runner table sends kind `agent` to `run_agent`, which calls `agent_once` once; the shared route through the front door and the agent runtime is steps 1 to 3 of 9.2.3 (`console/jobs.py:1401-1403#run_agent`, `console/jobs.py:830-841#run_agent`, `console/jobs.py:717-760#agent_once`).
3. The operator tab runs the same agent with both private tools in one run and builds a board for it: a gateway row that says "NOT BEHIND APIM", an `mcp` row that passes (label ALLOWED, role `Positions.Read`) or blocks with the label of the refusal reason (`403 NO ROLE` for `missing_role`, and `TOOL REFUSED` only when the reason has no label: `console/e2e.py:400-404#_LABEL`), and a `data` row that says "COSMOS AS USER" or "NEVER TOUCHED" (`console/role_tabs.py:332-349#_private_rows`, `console/role_tabs.py:405-409#get_credit_limit`; the tab itself is 9.8.1).
4. The role matrix cannot run a person against the private server, because only the agent's subnet reaches it; it carries a "Designed, not run" statement per persona: Priya, Wes and Ian refused, Tara and Carla allowed, and says that the Admin column (the operator) runs it live through the agent (`console/role_story.py:528-535#DESIGNED`, 9.8.2). The gateway board of Act 7 says that the private server is not on it (`console/act7.py:442#private`).
5. There is no private-server board in the end-to-end flow and no private-server scenario in Act 7; beat 3.1 and the operator tab are the only live runs of this path.

**How demo/prove.py proves it.** Proof P06 combines beats 3.1 and 3.2. It resolves the private host through public DNS and requires that no internet-routable address comes back, requires that this machine cannot resolve the host either, calls `settle_agent` (it asks one cheap question every 60 s, up to 15 minutes, until the agent shows the baseline roles, because Foundry holds a token minted at the first call after the previous one expired), then runs `abw-wall-desk` with the positions prompt and requires `get_firm_positions` to have status `ok` and `get_credit_limit` to have status `ok` (`demo/prove.py:711-730#p06`, `demo/prove.py:384-402#ask_agent`, `demo/prove.py:405-410#settle_agent`). The scrubbed proof run records both checks as passed. P06 proves reachability from inside the VNet and tool success. It does not read the Cosmos DB log, so it does not prove who the principal was, and no proof removes a group to watch Cosmos DB refuse a person; the Storage equivalent is the data-plane drill of 9.7, beat 6.5, and the Cosmos DB version is Designed only.

**Failure modes and what the presenter should say.**

- Fewer than two calls: the healthy summary is "2 tool calls, 2 allowed" (`console/jobs.py:808-827#agent_summary`). The model chooses its tools, so if one is missing run the beat again; the proof script checks each tool on its own (`demo/prove.py:728-729#get_firm_positions`).
- The first run after a quiet period behaves differently: Foundry mints the user's token at the first agent call after the previous one expired and keeps it for its whole life (Entra lifetimes are 60 to 90 minutes: `DESIGN.md:223#Foundry`), so a token minted while roles were different keeps those roles until it expires (`demo/prove.py:405-410#settle_agent`). Run the beat once before the room, and say "the same token for the whole hour" only after the audit shows one `jti`.
- A card titled "One-time consent needed": Foundry needs the user to approve once that this agent may call the private server as them; the card carries a link. Open it, approve, run the step again (`console/jobs.py:761-767#consent_required`).
- The `tools` event shows an empty list for `private`: the signed-in user holds no `Positions.Read`, the registry filtered the listing, and the model has nothing to call (`src/mcp/abw_mcp/registry.py:132-156#list_tools`). This is the designed refusal, not a fault.
- The strip lights `apim` green and `data` green on any success (Findings F37 and F21); the call did not pass through APIM, and the light for `data` says only that the server answered. Show the audit row and the Cosmos DB query instead of the lights.
- No request id on the card (Findings F38): find the call by time, user and `Server == 'private'` in the first KQL block.
- Both tools fail and the audit shows no `tool_call` row: a Cosmos DB refusal is not audited by the server (Findings F3); look for `StatusCode` 403 in `CDBDataPlaneRequests`. Designed, not demonstrated.
- The run takes about 20 s; the scrubbed record shows about 18 s (`console/catalog.py:375-386#abw-wall-desk`).

Say: "Internal systems of record, no new network exposure." (`console/catalog.py:384#sales`), and add "and Cosmos names the person" only after the Cosmos DB query has been shown (`docs/PROOF-PLAYBOOK.md:394#LAND`).

**Why and trade-offs.** Why the private server reads Cosmos DB as the user: the database, and not the server's code, decides which rows a person can read, so a mistake in a query cannot widen access beyond the person's role, and the log names the person (`DESIGN.md:33#OBO`, `console/role_tabs.py:343#COSMOS`). The roles that decide are on two groups, a reader role on the `positions` container for traders and for compliance (`infra/03-platform.bicep:676-700#cosmosTradersPositions`). No Cosmos DB role is assigned to the private server's own identity; the other assignments are the traders group's contributor role and the compliance group's reader role on the `orders` container (`infra/03-platform.bicep:650-674#cosmosTradersOrders`), the legacy server's account-wide contributor role, the actions server's reader role on the `restricted` container (`infra/03-platform.bicep:590-614#cosmosLegacyContrib`) and the seed job's role (`infra/04b-seed-job.bicep:91-98#cosmosSeed`), so with `COSMOS_OBO` false the server would be refused. Provenance: Configured (the assignments), Designed (per-request evaluation of group membership: no recorded run removes a group for Cosmos DB). Why the server is not behind APIM: the agent runtime reaches it directly through a subnet delegated to the Container Apps service, which keeps the data on a path with no new public exposure (`DESIGN.md:107#kill`). **Trade-off / limitation:** the same choice removes the kill switch, the rate limit and the gateway telemetry from this path (Findings F10), so a revoked user keeps access until the stored token expires; a production design would need an internal gateway in front of the server or a server-side deny list, and neither is built here (not in this repo). The audit is best effort: the blob append runs on a background thread, and unless `AUDIT_FAIL_CLOSED` is set a failed append prints `append_audit_failed` and the call is still served (`src/mcp/abw_mcp/audit.py:88-103#append_audit_failed`, `src/mcp/abw_mcp/config.py:150#AUDIT_FAIL_CLOSED`, Findings F12). A denial returns a normal result, not an error, so the model reads the reason; strict mode would end the run instead (`src/mcp/abw_mcp/registry.py:263-270#isError`).

#### 9.4.3 Beat 3.2: Prove the server is private

**Purpose.** Show, with two DNS lookups and nothing else, that the private server is not on the internet. The console asks a public resolver for the server's address, asks this laptop's own resolver the same question, and expects "no record" from the first and "cannot resolve" from the second. The record exists, but only in a private DNS zone that is linked to the VNet, so only a machine that uses the VNet's resolver can find it. The take-away for the room: a firewall rule protects a door that exists, and this server has no door on the internet (`console/catalog.py:387-398#private`). The beat takes about one second. Provenance: Implemented (the check), Configured (the host, the zone and the link), Platform behaviour (a private zone answers only to linked virtual networks: https://learn.microsoft.com/azure/dns/private-dns-overview; an internal Container Apps host has no public endpoint: https://learn.microsoft.com/azure/container-apps/networking#accessibility-level).

**Actors and tokens.** There is no identity and no token in this beat; it is the only beat of Act 3 without one. Three parties take part: the console process on the presenter's laptop, a public DNS-over-HTTPS service (`dns.google`) and the laptop's own resolver. The console sends one anonymous HTTPS GET with the host name and the record type `A` as query parameters and an `accept` header of `application/dns-json`, and makes one local name lookup (`console/jobs.py:1112#resolve`, `console/jobs.py:1121-1126#_ORIGINAL`). Nothing goes to Entra, APIM, the private server, Foundry or Cosmos DB. The persona selector has no effect: `persona_error` ignores kinds outside `PERSONA_KINDS`, the page adds a persona only for the kinds in `AS_KINDS`, and `run_private` never reads one (`console/jobs.py:420#PERSONA_KINDS`, `console/jobs.py:595-612#persona_error`, `console/web/personas.js:11#AS_KINDS`, `console/web/personas.js:22#applies`). Section 6 has nothing to add for this beat. The only credential that comes near it is the operator's Azure sign-in, and only for the optional live-state drawer described under Evidence produced (`console/azure_probe.py:73-90#acquire_token_silent`).

**Preconditions.**

1. The deployment of 9.4.1. The private app runs on the internal Container Apps host, which is a different host from the public one that carries only the vendor server. The research, deal-room, actions and legacy servers share the internal host with the private one (`infra/03-platform.bicep:385-388#internal`, `infra/03-platform.bicep:399-415#caePub`, `infra/04-apps.bicep:86-130#caePriv`, `infra/04-apps.bicep:131-144#privateMcp`, `infra/04-apps.bicep:146-155#caePriv`, `infra/04-apps.bicep:166-173#caePub`).
2. The internal host sits on a subnet of its own, `snet-mcp`, that is delegated to the Container Apps service. A host in your own VNet needs such a dedicated subnet, and an internal host restricts inbound requests to the VNet (`infra/01-network.bicep:182-198#snet-mcp`; Platform behaviour: https://learn.microsoft.com/azure/container-apps/custom-virtual-networks).
3. The app's own ingress flag does not make it public. The module's flag `externalIngress` defaults to true and its comment says what it means: reachable from outside the host, which is the VNet for the internal host and the internet for the public one. The private app passes no value, so the host's `internal` setting is the only thing that keeps it off the internet (`infra/modules/mcp-app.bicep:14-15#externalIngress`, `infra/modules/mcp-app.bicep:39-44#externalIngress`, `infra/04-apps.bicep:131-144#privateMcp`).
4. The private DNS zone. Its name is the host's default domain. It holds a wildcard A record and an apex A record, both pointing at the host's internal load-balancer address, and one link to the VNet with auto-registration off. It is a separate module because the default domain is known only after the host exists. A virtual network resolves a private zone's records only when it is linked to the zone (`infra/modules/aca-dns.bicep:1-3#aca-dns`, `infra/modules/aca-dns.bicep:18-22#zone`, `infra/modules/aca-dns.bicep:24-35#wildcard`, `infra/modules/aca-dns.bicep:37-48#apex`, `infra/modules/aca-dns.bicep:50-61#link`, `infra/03-platform.bicep:417-426#acaDns`; Platform behaviour: https://learn.microsoft.com/azure/dns/private-dns-overview).
5. The host name the console resolves is `<private-host>`: the app name plus the host's default domain. The demo helpers load it from the deployment outputs when they start. If the entry is missing, the job ends with an error card instead of a table (`infra/04-apps.bicep:75#privateFqdn`, `demo/mcpclient.py:37#APPS`, `console/jobs.py:1107#fqdn`, `console/jobs.py:535-548#_run`).
6. The laptop can reach the public DNS-over-HTTPS service (timeout 15 s) and has no route to the VNet's resolver: no VPN or peering that forwards the private zone, and it is not a machine inside the VNet. Otherwise the second row changes (`console/jobs.py:1112#resolve`; failure table below).

**Sequence.**

1. Browser -> console. "Check DNS" posts `{"kind":"private","params":{"kind":"private"},"title":"Prove the server is private","beat":"3.2"}`; the title is the beat's title. The run dictionary, sent as `params`, has no keys beyond `kind`, and no persona is added (`console/catalog.py:387-398#private`, `console/web/util.js:160-162#startJob`, `console/web/pages.js:98#beat.title`, `console/web/personas.js:29-31#withPersona`, `console/server.py:128-135#api_jobs_start`).
2. Console admission. `Manager.start` finds the runner and calls `validate`, which has no branch for this kind and ends in `persona_error`, which returns an empty string. The kind is not in `NEEDS_OPEN_GATEWAY`, so the start does not read the gateway state and an engaged kill switch does not stop the beat. The kind is in `READONLY`, so `conflicts` is false against every other job. A daemon thread runs `run_private` (`console/jobs.py:503-533#start`, `console/jobs.py:563-593#validate`, `console/jobs.py:595-612#persona_error`, `console/jobs.py:495#NEEDS_OPEN_GATEWAY`, `console/jobs.py:476#READONLY`, `console/jobs.py:480-491#conflicts`).
3. Console -> browser: one `say` event names the host: "Resolving <private-host> - the private MCP server's hostname - from two places." (`console/jobs.py:1107-1108#fqdn`).
4. Console -> public resolver: `GET https://dns.google/resolve?name=<private-host>&type=A`, header `accept: application/dns-json`, no credentials, 15 s timeout. The reply is JSON with a `Status` and, when records exist, an `Answer` list. The code maps only status 3 to the words "NXDOMAIN - no such host". An empty answer list gives the row's meaning "no public record" and makes `public_ok` true; any record gives "RECORD FOUND - unexpected" (`console/jobs.py:1112-1118#answers`, `console/jobs.py:1115#NXDOMAIN`, `console/jobs.py:1118#public_ok`). The repository does not say which name servers hold the host's default domain, and the meaning of the status number belongs to the resolver; the code only turns the number into words. The scrubbed proof run records this check as status 3 with an empty answer list (`demo/evidence-scrubbed/`).
5. Console -> operating system: `getaddrinfo(<private-host>, 443)` through the saved original function. The console imports the demo client module, and that module installs a retry shim over `socket.getaddrinfo` (up to nine attempts, sleeping 0.3 s and growing by a factor of 1.6 to a cap of 3 s, about 13.7 s in all) so that a transient resolver fault does not break other demo calls. This runner bypasses the shim, so a genuine failure returns at once (`console/jobs.py:33#mcpclient`, `demo/mcpclient.py:29-32#install`, `src/agent/netfix.py:14#_ORIGINAL`, `src/agent/netfix.py:18-28#_retrying_getaddrinfo`, `src/agent/netfix.py:31-35#install`, `console/jobs.py:1121-1126#_ORIGINAL`).
6. The local result. On a laptop outside the VNet the lookup raises `socket.gaierror`: the row reads "cannot resolve" with the meaning "private DNS zone is linked to the VNet only", and `local_ok` is true. If the lookup returns addresses, the row lists them with the meaning "resolves - this network can see the private zone" and `local_ok` is false (`console/jobs.py:1124-1129#gaierror`).
7. Console -> browser: one `table` event with the two rows, an empty `query` and the fixed `lights` `{"m-private":"ok","apim":"ok"}`. The browser draws the table card and lights both nodes. The lights do not depend on the answers, and `apim` is lit although the path never touches APIM (Findings F37). The card has no "Show the query" block because `query` is empty, and no cell is coloured, because the colouring applies only to a cell that starts with a refusal word (deny, denied, blocked, refused, revoked) or is exactly an allow word (allow, allowed, ok) (`console/jobs.py:1133#columns`, `console/web/render.js:91-104#tableCard`, `console/web/render.js:92#query`, `console/web/render.js:84-90#cell`, `console/web/render.js:554-556#lights`, `console/web/strip.js:42-49#apply`).
8. Console -> browser: when both lookups passed, a closing `say`; then the `done` event. The finish status follows the public row only (`console/jobs.py:1134-1136#local_ok`; Findings F41).

Why the agent can reach the server and the laptop cannot (the only difference is which resolver answers):

```text
presenter laptop (the console)
  |-- HTTPS GET dns.google/resolve?name=<private-host>&type=A --> public resolver --> no record (status 3)
  |-- getaddrinfo(<private-host>, 443) --> laptop resolver ------> private zone not visible --> gaierror
inside the VNet only
  agent runtime (snet-agent) --> VNet resolver --> private zone (wildcard A record)
                             --> internal load-balancer address --> private app on the internal host
```

The zone is linked to the VNet that holds the agent subnet and the internal host, which is why beat 3.1 resolves the same name that this beat cannot (`infra/modules/aca-dns.bicep:24-35#wildcard`, `infra/modules/aca-dns.bicep:50-61#link`, `infra/01-network.bicep:160-165#snet-agent`). Provenance: Configured; the resolver behaviour is Platform behaviour (https://learn.microsoft.com/azure/dns/private-dns-overview).

**Success outcome.** The console stream for a healthy run is four events (the console adds an event index `i` and the elapsed seconds `t` to every event, omitted below, `console/jobs.py:276-280#emit`; `<private-host>` is a placeholder):

```json
{"type": "say", "text": "Resolving <private-host> - the private MCP server's hostname - from two places."}
{
  "type": "table",
  "title": "Who can find the private MCP server?",
  "columns": ["Where we asked", "Answer", "Meaning"],
  "rows": [
    ["Google public DNS (the internet)", "NXDOMAIN - no such host", "no public record"],
    ["This laptop", "cannot resolve", "private DNS zone is linked to the VNet only"]
  ],
  "query": "",
  "lights": {"m-private": "ok", "apim": "ok"}
}
{"type": "say", "text": "It is not 'protected by a firewall rule' - it is simply not on the internet. Only the VNet-injected agent runtime can reach it."}
{"type": "done", "status": "done", "summary": "Not resolvable from the internet."}
```

(`console/jobs.py:1108#Resolving`, `console/jobs.py:1133#columns`, `console/jobs.py:1134-1136#local_ok`, `console/jobs.py:296-304#finish`.) The first row's answer is "NXDOMAIN - no such host" only for status 3; any other status with no answer is printed as "status <n>" and still counts as "no public record" (Findings F41).

**Failure or denial outcomes.** This beat has no denial in the access-control sense; a "failure" is a different DNS answer. The strip maps the private node to wall 2 (`console/web/strip.js:14#WALL_OF`), but nothing in this beat is decided by a policy.

| Situation | What happens | Shape and where it is decided |
|-----------|--------------|-------------------------------|
| The public resolver returns a record | The row shows the comma-joined answer data with the meaning "RECORD FOUND - unexpected"; `public_ok` stays false; no closing sentence (`console/jobs.py:1114-1118#answers`) | `{"type":"done","status":"failed","summary":"The private host resolved publicly - investigate."}`. The strip lights stay `ok` because they are fixed in the event (Findings F37). A real finding: the host or the zone is not as designed |
| The public lookup itself fails (no internet, the service blocked, 15 s timeout) | The exception is caught; the row reads "lookup failed: <ExceptionName>" with the meaning "could not check"; `public_ok` stays false (`console/jobs.py:1119-1120#__name__`) | The job still ends `failed` with the sentence "The private host resolved publicly - investigate.", which is wrong for a lookup that never completed (Findings F41) |
| The resolver answers with a status other than 3 and no records (for example a server failure) | The row reads "status <n>" with the meaning "no public record"; `public_ok` is true (`console/jobs.py:1114-1118#answers`) | The job ends `done` as if privacy were proven; only status 3 is worded as NXDOMAIN (Findings F41) |
| The laptop resolves the name (VPN, jump box, a resolver that forwards the zone) | The row lists the addresses with the meaning "resolves - this network can see the private zone"; `local_ok` is false; no closing sentence (`console/jobs.py:1124-1126#resolves`) | The job still ends `done` when the public row passed, because the final status ignores `local_ok` (Findings F41) |
| The laptop lookup fails with something other than a name-resolution error | The row reads "lookup failed: <ExceptionName>" with the meaning "could not check"; `local_ok` is false (`console/jobs.py:1130-1132#local_ok`) | No closing sentence; status follows the public row |
| The deployment outputs have no private entry | `run_private` raises; `_run` turns it into an `error` event and finishes the job `failed` (`console/jobs.py:535-548#_run`, `console/jobs.py:163-173#friendly`) | An error card, no table |
| The kill switch is engaged, or another job is running | No effect: the kind is outside `NEEDS_OPEN_GATEWAY` and inside `READONLY` (`console/jobs.py:495#NEEDS_OPEN_GATEWAY`, `console/jobs.py:480-491#conflicts`) | The beat runs |
| A raw gateway call to `private` is attempted | The `gateway` kind refuses the server: "Unsupported gateway call." (`console/jobs.py:573-574#Unsupported`; Findings F27). The command-line client says that the server is not published at the gateway and points to the DNS helper (`demo/mcpclient.py:184#published`) | Start refusal (HTTP 409 from `api_jobs_start`), not a gateway result |

**Evidence produced.** The DNS answers themselves are shown once and not stored; the evidence that lasts is the state of the infrastructure that causes them.

| Evidence | Where it lands | How to retrieve it |
|----------|----------------|--------------------|
| The table card and the `done` line (tag `live`) | The job's event list in the console (`console/jobs.py:276-280#emit`, `console/web/render.js:599#tableCard`) | Immediate: it is the card of the beat |
| The DNS answers in the proof run | The run record of proof P06, which holds the public-lookup status and its answers; `demo/evidence-scrubbed/` shows the scrubbed copy (status 3, empty answer list) | Run `python demo\prove.py --only P06` (it needs the agent for its second half) or read the scrubbed run |
| The live state of the cause (tag `probe`) | Clicking the "Private MCP server" node of the strip opens a drawer that fetches `GET /api/probe/mcp`; the probe `probe_mcp` reads every Container App in the resource group and, for both hosts, the `vnetConfiguration.internal` flag from Azure Resource Manager with the operator's delegated token, and caches the answer for 120 s (the Refresh button forces a new read) (`console/catalog.py:987-997#m-private`, `console/web/strip.js:193-208#probe`, `console/server.py:173-178#api_probe`, `console/azure_probe.py:426-446#probe_mcp`, `console/azure_probe.py:833-850#run_probe`, `console/azure_probe.py:828-830#TTL`, `console/azure_probe.py:73-90#acquire_token_silent`) | The drawer. Its head line reads "<n> MCP servers on Container Apps: <k> reachable only inside the VNet, <m> public (the vendor)", with one fact row per app. For the six servers this repository deploys the Bicep puts five on the internal host and the vendor on the public one, so a healthy head line has one public app; that is derived from the Bicep, not from a recorded run (`infra/04-apps.bicep:166-173#caePub`). The probe status is `ok` whenever at least one app exists (`console/azure_probe.py:443#warn`; Findings F46) |
| The portal screens (tag `portal`) | The Container Apps host (internal, no public IP) and the Private DNS zone's virtual network links (linked to the VNet only) | The playbook gives the click path and marks both as path steps: the presenter navigates and reads, and the console does not verify them (`docs/PROOF-PLAYBOOK.md:396#Check`) |
| The terminal helper | The helper `abw-private` does the same two lookups in PowerShell and prints "Status=<n> answers=<n>" for the public one; `abw-gw` with the private server calls it (`demo/stage.ps1:121-134#abw-private`, `demo/stage.ps1:103#abw-private`) | Run `abw-private` |
| The absence of a gateway row (tag `logs`) | No row: the server is not behind the gateway (`demo/mcpclient.py:184#published`) | The query below. It returns 0, which shows that the gateway never saw the server; it cannot tell "unreachable" from "reached directly" (`docs/TALK-TRACK-PORTAL-TOUR.md:351#AbwGateway`, `observability/kql/AbwGateway.kql:1-12#AbwGateway`) |

```kusto
AbwGateway(1d) | where Server == 'private' | summarize n = count()
```

The probe result the drawer draws has the shape below; `<app name>` and the wording of `v` are placeholders because the wording is built from the host's flag (`console/azure_probe.py:236-244#asOf`):

```json
{"id": "mcp", "status": "ok",
 "headline": "<n> MCP servers on Container Apps: <k> reachable only inside the VNet, <m> public (the vendor)",
 "facts": [{"k": "<app name>", "v": "<VNet-only or public wording>; <running status>"}],
 "asOf": "<hh:mm:ss>", "ms": <n>}
```

The drawer also carries three "what to point at" lines for the node: the host is internal with no public IP and DNS resolves only inside the VNet; the server is not behind APIM, so the gateway policy and the kill switch do not apply and the server validates the same Entra token itself; and the honest edge, that a revoked user keeps access here until the token expires, with the suggestion to front the server with an internal APIM or have it read the same deny list (`console/catalog.py:992-996#Honest`). No log in this repository records the DNS lookups themselves.

**How the console runs it.**

1. The beat is the catalog entry 3.2: kind `private`, button "Check DNS", about one second, the node `m-private` as the thing to point at (`console/catalog.py:387-398#private`).
2. The runner table sends kind `private` to `run_private` (`console/jobs.py:1401-1424#RUNNERS`, `console/jobs.py:1411#private`, `console/jobs.py:1106-1136#run_private`).
3. Clicking the node on the strip opens the drawer with the live infrastructure state (`console/web/strip.js:193-208#probe`).
4. The gateway board of Act 7 says that the private server is not on it (`console/act7.py:442#private`; 9.8.1). Act 7 has no DNS scenario.

**How demo/prove.py proves it.** Proof P06 does the two lookups before its agent step. The public check asks the same resolver for the host's A records and passes when no address that is not private-range comes back; the laptop check calls the original resolver function, as the console does, and requires a name-resolution failure (`demo/prove.py:706-708#public_dns`, `demo/prove.py:715-718#public_ips`, `demo/prove.py:719-724#_ORIGINAL`). It therefore differs from the console in two ways: P06 fails when the laptop resolves the name, where the console only reports it (Findings F41), and P06 ignores answers in private ranges, where the console treats any answer as a failure. The scrubbed run records both checks as passed. The rest of P06 is the agent step of beat 3.1 (9.4.2).

**Failure modes and what the presenter should say.**

- The second row reads "resolves": the laptop sees the private zone (VPN, a jump box, a resolver that forwards the zone). Say so plainly, because the table says it; the job still shows done (Findings F41). Run the beat from a network outside the VNet, or show only the public row.
- The first row reads "lookup failed" and the job is marked failed with the "resolved publicly" sentence: the laptop could not reach the resolver. Say "we could not reach the resolver", not "it resolved publicly" (Findings F41). Retry, or use the terminal helper, which prints the failure text.
- The first row reads "RECORD FOUND - unexpected": treat it as a finding. Open the drawer to see which host the app is on, then the host's page in the portal.
- Do not use this beat to claim that the server is covered by the kill switch or the rate limit: it is not. The portal tour's own wording is to say so before someone finds it (`docs/TALK-TRACK-PORTAL-TOUR.md:354#Honest`, `docs/TALK-TRACK.md:128#abw-private`).
- The talk track presses "Check DNS" right after the positions result of 3.1 and says: public DNS has no record for it, and this laptop cannot resolve it (`docs/TALK-TRACK.md:167#Check`).
- A run that takes longer than about 15 s usually means the public lookup timed out; a slow local lookup, which has no timeout of its own, is the other cause (`console/jobs.py:1112#resolve`, `console/jobs.py:1121-1126#_ORIGINAL`).

Say: "It is not 'protected by a firewall rule' - it is not on the internet." (`console/catalog.py:396#sales`). The proof that the agent still reaches it is beat 3.1.

**Why and trade-offs.** Why DNS: it is the one network fact a presenter can show in a second from the room's own laptop, with no credential. Why a public resolver and not only the laptop: it gives the internet's view, which a local resolver that forwards the private zone would not; the code does not state this, it is the effect of the design. What the check proves: that the name cannot be found from the internet or from this laptop. What it does not prove: (1) that the app is unreachable at the network level; the cause is the host's internal setting, which the drawer and the portal show, and the drawer's status does not assert it (Findings F46); (2) authorization: a name that does not resolve is not a control on who may call, and the server still checks the token (9.4.2, step 5); (3) segmentation inside the VNet: the wildcard record points every name under the host's default domain at one internal address, so the research, deal-room, actions and legacy servers are as hidden from the internet as the private one, and what sets the private server apart is only that no gateway API fronts it (`infra/modules/aca-dns.bicep:24-35#wildcard`, `console/act7.py:442#private`, `DESIGN.md:107#kill`). **Trade-off / limitation:** the network file attaches a network security group only to the APIM subnet; the subnet of the internal host has none (`infra/01-network.bicep:182-198#snet-mcp`, `infra/01-network.bicep:200-210#networkSecurityGroup`). The isolation this repository configures is therefore the internal host, the private zone and the VNet boundary, and whatever can route to the internal address is stopped by the server's own token check; any filtering the platform adds on its own is not shown here (Findings F47). The check also sends the private host's name to a third-party public resolver; the name is derived from the workload name and the host's default domain, it is not a secret, but it is a disclosure that a locked-down tenant may not want (`console/jobs.py:1112#resolve`). Last, the status logic mis-words some outcomes (Findings F41).

#### 9.4.4 Beat 3.3: The vendor key never leaves the gateway

**Purpose.** Show the third kind of server, the one the firm does not run: an external SaaS MCP that insists on its own static API key. The signed-in user is authenticated at the gateway with an Entra token and checked for a role; the gateway then deletes that token, attaches the vendor's key as a header and forwards the call. The key never reaches the user or the agent, and the vendor never sees the user's token. The button is "Get a vendor quote" (about 3 s) and the opening line is "An external SaaS MCP that needs its own API key. The user authenticates; the gateway attaches the vendor key." (`console/catalog.py:399-410#get_market_quote`). Unlike beat 3.1 this is not an agent run: the console speaks MCP to the gateway itself with one `tools/call`, as the signed-in operator or, when a persona is chosen, with that person's own token. The beat is optional in the talk track: 20 s, the second thing cut when the show runs late and the first thing added when it runs early (`docs/TALK-TRACK.md:172#Optional`, `docs/TALK-TRACK.md:300#vendor`, `docs/TALK-TRACK.md:301#vendor`). Provenance: Implemented (the console call and the vendor server), Configured (the vendor API, its policy section, the named value, APIM's role on the vault, the backend and the vault firewall), Platform behaviour (named values of type Key Vault and the `set-header` policy: https://learn.microsoft.com/azure/api-management/api-management-howto-properties, https://learn.microsoft.com/azure/api-management/set-header-policy).

**Actors and tokens.** Four things move in this beat and only the first is a token that a user holds. The actors are the presenter's browser, the console server on the laptop, APIM, the vendor app on the public Container Apps host and, indirectly, Key Vault. The vendor app receives no user token, validates none and has no on-behalf-of broker: the broker is built for every server except `vendor` and `legacy`, and the token-validation flag is false for both (`src/mcp/abw_mcp/app.py:73-77#build_runtime`, `src/mcp/abw_mcp/config.py:101#validates_tokens`).

| Token or secret | Issued for | Key claims or content | Carried by | Checked or used by |
|-----------------|------------|-----------------------|------------|--------------------|
| The caller's delegated access token: the operator's, or the chosen persona's own | The vendor gateway application `<vendor-gateway-app>`, scope `api://<vendor-gateway-app>/Tools.Read` (`demo/mcpclient.py:44#API_KEY_FOR_SERVER`, `demo/mcpclient.py:47-48#scope_for`) | `aud` the vendor gateway application, `scp` `Tools.Read`, `roles` `MarketData.Read`, `azp` the Azure command-line client for the operator or the gateway test client for a persona (`console/personas.py:3-6#abw-test-client`, `console/personas.py:126-128#PublicClientApplication`; both are on the gateway's allow-list, the named value `abw-allowed-azp`: `infra/05-apim.bicep:199-206#abw-allowed-azp`, `infra/apim/policies/mcp-jwt.policy.xml:38#abw-allowed-azp`), `oid` (the key of the kill switch and of the rate limit) | The Authorization header carrying the Bearer-scheme access token, console to APIM only (`demo/mcpclient.py:124-141#rpc`) | APIM `validate-jwt` and `abw-deny` (hops G2 and G3 in 9.1.8); deleted before the vendor hop (`infra/05-apim-apis.bicep:75-78#vendorSection`) |
| The vendor key `<vendor-key>` | The vendor mock; a 40-character generated password (`scripts/deploy.ps1:182-186#New-StrongPassword`) | The key and nothing else | A Key Vault secret, an APIM named value `abw-vendor-key`, then the header `x-vendor-key` on the APIM-to-vendor hop only; the vendor app also holds its own copy (Findings F34) | APIM injects it; the vendor's `VendorKeyMiddleware` compares it (`src/mcp/abw_mcp/app.py:115-142#VendorKeyMiddleware`) |
| APIM's own access token for Key Vault | The vault's data plane | Key Vault Secrets User at vault scope, the one role APIM holds there | Not on the request path: APIM resolves the named value itself | Key Vault (`infra/05-apim.bicep:220-231#raApimKv`) |
| `x-abw-request-id` | One call | A fresh GUID from the caller, replaced by APIM with its own request id | Request header, then the audit event and the response | APIM override and the server's request-context middleware (`infra/apim/policies/mcp-jwt.policy.xml:82-84#x-abw-request-id`, `src/mcp/abw_mcp/auth.py:173-189#RequestContextMiddleware`) |

A chosen persona runs the same job with that person's own token instead of the operator's; the first operator token per server after a start or reset is forced fresh so that its role claims are current (`console/jobs.py:420#PERSONA_KINDS`, `console/web/personas.js:11#AS_KINDS`, `console/jobs.py:428-436#token_for`). Section 6 explains how the first token is issued and why the allow-list matters; section 8 covers the middleware chain of a server. Provenance: Implemented.

**Preconditions.**

1. The kill switch is released and no disruptive job (burst, allow-list, kill, restore, quota) is running: the `gateway` kind needs an open gateway and the job manager refuses a start that conflicts (`console/jobs.py:495#NEEDS_OPEN_GATEWAY`, `console/jobs.py:480-491#conflicts`, `console/jobs.py:503-533#start`).
2. The caller holds the `MarketData.Read` role on the vendor gateway application. The proof matrix expects it for the baseline operator and for Priya, and not for Ian; the persona table gives it to Priya, Wes, Tara and Carla and gives Ian no app role at all (`demo/prove.py:75-79#EXPECT`, `demo/prove.py:629-630#vendor`, `DESIGN.md:76-79#MarketData`, `infra/05-apim-apis.bicep:62-72#roles`).
3. The vendor app runs on the public Container Apps host, which has no VNet configuration, and its module leaves ingress external. It refuses to start without its key (`infra/03-platform.bicep:399-415#caePub`, `infra/modules/mcp-app.bicep:39-44#externalIngress`, `infra/04-apps.bicep:166-187#vendor`, `src/mcp/abw_mcp/config.py:117-134#server_requirements`).
4. The key's journey. The deploy script creates it on first use as a 40-character password in a local file of the deployment's secrets folder and passes it as a secure parameter; the audit copy of the parameters shows asterisks in its place and the live parameter file is removed when the call returns. The apps stage writes it into Key Vault through Azure Resource Manager (the vault's data plane is firewalled), gives the vendor app an inline copy, and returns the secret's version-less address, which the apis stage hands to the named value (`scripts/deploy.ps1:182-186#Get-VendorKey`, `scripts/deploy.ps1:329-346#vendorApiKey`, `scripts/deploy.ps1:46-48#SecretParamKeys`, `scripts/deploy.ps1:63-71#New-ParamFile`, `scripts/deploy.ps1:73-77#Remove-SecretParamFile`, `infra/04-apps.bicep:34-38#vendorApiKey`, `infra/04-apps.bicep:43-50#vendorKeySecret`, `infra/04-apps.bicep:180-186#vendor-api-key`, `infra/04-apps.bicep:200#vendorKeySecretUri`, `scripts/deploy.ps1:374-387#vendorKeySecretUri`).
5. The named value `abw-vendor-key` is marked secret and backed by Key Vault; APIM's system identity holds Key Vault Secrets User on the vault; the vault's firewall denies by default but lets trusted Microsoft services through (`infra/05-apim-apis.bicep:81-91#nvVendorKey`, `infra/05-apim.bicep:220-231#raApimKv`, `infra/03-platform.bicep:95-101#networkAcls`). Platform behaviour: a Key Vault named value needs a managed identity with that role, and with a firewalled vault the system-assigned identity plus the trusted-services exception (https://learn.microsoft.com/azure/api-management/api-management-howto-properties).
6. APIM can reach the public host: the APIM subnet's network security group allows outbound 443 to the Internet, and the subnet egresses through the NAT gateway (`infra/01-network.bicep:99-112#allow-out-internet-443`, `infra/01-network.bicep:200-208#natGateway`).

**Sequence.**

1. Browser -> console server -> job. "Get a vendor quote" posts `{"kind":"gateway","params":{"server":"vendor","tool":"get_market_quote","args":{"ticker":"<ticker>"}},"beat":"3.3"}` to `POST /api/jobs`, with a `persona` key added to `params` when one is chosen (9.1.5 explains the abbreviation). The server answers with a job id or a start refusal; `validate` accepts the `gateway` kind only for the listed servers and tools (`console/web/util.js:160-162#startJob`, `console/web/personas.js:29-31#withPersona`, `console/server.py:128-135#api_jobs_start`, `console/jobs.py:503-533#start`, `console/jobs.py:563-593#validate`).
2. Console -> APIM (hop G1 of 9.1.8). `run_gateway` says the opening line, `call_gateway` gets the token (`token_for`) and `rpc` posts to `<apim-gateway-url>/vendor/mcp` with Content-Type, Accept, `x-abw-request-id` (a fresh uuid4 that APIM will override) and the Authorization header carrying the Bearer-scheme access token. The body is `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_market_quote","arguments":{"ticker":"<ticker>"}}}`. The API requires no subscription key (`console/jobs.py:843-859#run_gateway`, `console/jobs.py:452-462#call_gateway`, `console/jobs.py:428-436#token_for`, `demo/mcpclient.py:76-86#acquire_token_silent`, `demo/mcpclient.py:124-141#rpc`, `demo/mcpclient.py:143-144#call_tool`, `infra/05-apim-apis.bicep:123-147#subscriptionRequired`).
3. APIM inbound, hops G2 to G4 of 9.1.8. `validate-jwt` checks the signature, the issuer, the expiry, the tenant claim and that the token was minted for the vendor gateway application; `abw-deny` returns the first of `revoked`, `client_not_allowed`, `missing_scope`, `missing_role`; because the vendor API sets `listOpen` false, even `tools/list` needs the role. The decision is counted and traced, a non-empty reason becomes a 403, then the rate limit applies (120 calls per 60 s per `oid`) and APIM overrides `x-abw-request-id` with its own request id (`infra/apim/policies/mcp-jwt.policy.xml:17-30#validate-jwt`, `infra/apim/policies/mcp-jwt.policy.xml:31-46#abw-deny`, `infra/apim/policies/mcp-jwt.policy.xml:42-44#__LIST_OPEN__`, `infra/apim/policies/mcp-jwt.policy.xml:51-63#abw-gateway`, `infra/apim/policies/mcp-jwt.policy.xml:64-80#return-response`, `infra/apim/policies/mcp-jwt.policy.xml:81#rate-limit-by-key`, `infra/apim/policies/mcp-jwt.policy.xml:82-84#x-abw-request-id`, `infra/05-apim-apis.bicep:62-72#listOpen`).
4. APIM swaps the credential, which is the point of the beat. `__VENDOR_SECTION__` is the last statement of the inbound section and the Bicep fills it only for the vendor API. It deletes the `Authorization` header and then sets `x-vendor-key` with the override action to the value of `{{abw-vendor-key}}`. Platform behaviour: in the inbound section `set-header` changes the request that goes to the target service, `delete` removes the header and `override` replaces its value (https://learn.microsoft.com/azure/api-management/set-header-policy); APIM resolves the named value with its system identity and refreshes a Key Vault value within four hours of a change in the vault (https://learn.microsoft.com/azure/api-management/api-management-howto-properties). Provenance: Configured (`infra/apim/policies/mcp-jwt.policy.xml:88#__VENDOR_SECTION__`, `infra/05-apim-apis.bicep:75-78#vendorSection`, `infra/05-apim-apis.bicep:149-166#mcpPolicies`).
5. APIM -> vendor app (hop G5). The backend URL is the vendor app's public HTTPS address, and certificate chain and name validation are on for it (`validateTls` true), unlike the other published servers, which follow the deployment's `validateInternalTls` switch (default false). The call leaves the APIM subnet through the NAT gateway and enters the public ingress. The request carries `x-vendor-key`, `x-abw-request-id` and `x-abw-gateway`, and no Authorization header (`infra/05-apim-apis.bicep:94-106#backends`, `infra/05-apim-apis.bicep:62-72#validateTls`, `infra/01-network.bicep:99-112#allow-out-internet-443`, `infra/modules/mcp-app.bicep:39-44#externalIngress`, `infra/apim/policies/mcp-jwt.policy.xml:85-87#x-abw-gateway`).
6. Vendor app, hop G6. The middleware order is OpenTelemetry, request context, then `VendorKeyMiddleware`; no token middleware is registered for this server. `VendorKeyMiddleware` acts only on the `/mcp` path: it logs a `vendor_request` record with `saw_authorization_header`, `saw_vendor_key` and the client address on logger `abw.vendor`, then compares the header with the expected key by `hmac.compare_digest` on UTF-8 bytes. A mismatch or a missing header returns 401 `{"error":"invalid_vendor_key"}`. The request-context middleware takes the request id from `x-abw-request-id` first (`src/mcp/abw_mcp/app.py:241-254#VendorKeyMiddleware`, `src/mcp/abw_mcp/app.py:115-142#VendorKeyMiddleware`, `src/mcp/abw_mcp/auth.py:173-189#RequestContextMiddleware`).
7. Registry, handler and audit (hops G7 to G9; there is no G8 because the server has no data plane). `call_tool` applies the `allow_all` requirement, validates the arguments (one to six capital letters), runs `get_market_quote`, which derives a synthetic price and change from a seed of the ticker and calls nothing downstream (`obo` false), adds the request id to the payload and emits the audit event. The event carries no user (Findings F4). The sinks are standard output and, in code, an append blob that the vendor identity has no role for (Findings F48). The result is a `CallToolResult` with a text item and `structuredContent` (`src/mcp/abw_mcp/registry.py:158-220#call_tool`, `src/mcp/abw_mcp/registry.py:94-96#allow_all`, `src/mcp/abw_mcp/servers/vendor.py:13-14#TickerArgs`, `src/mcp/abw_mcp/servers/vendor.py:30-43#get_market_quote`, `src/mcp/abw_mcp/servers/vendor.py:62-79#build_tools`, `src/mcp/abw_mcp/audit.py:178-216#build_event`, `src/mcp/abw_mcp/audit.py:219-223#build_default_audit_service`).
8. Vendor -> APIM -> console -> browser. The outbound and backend sections are the base policy only, so the response is not rewritten. The console reads the request id from the payload, decides `ok` (status 200 and no DENIED, BLOCKED or ERROR decision), asks `judge` for the verdict, replaces the plain sentence for a successful vendor call and drops the Foundry light. The browser draws the card and lights the strip (`infra/apim/policies/mcp-jwt.policy.xml:90-95#backend`, `console/jobs.py:229-253#http_result`, `console/jobs.py:176-198#judge`, `console/jobs.py:244-245#vendor`, `console/web/render.js:554-557#lights`, `console/web/render.js:577#verdictCard`, `console/web/render.js:19-40#verdictCard`).

The credential swap in one picture:

```text
console --- Authorization header (user access token, aud = vendor gateway app) ---> APIM  /vendor/mcp
APIM inbound: validate-jwt -> abw-deny -> 403 if denied -> rate limit -> request id
              -> delete Authorization -> set x-vendor-key = {{abw-vendor-key}} (Key Vault secret)
APIM --- x-vendor-key: <vendor-key>, no Authorization header ---> vendor app (public host, via NAT)
vendor app: VendorKeyMiddleware (constant-time compare) -> registry -> get_market_quote
```

**Success outcome.** The console stream for a healthy run is three events (the console adds an event index `i` and the elapsed seconds `t` to every event, omitted below, `console/jobs.py:276-280#emit`; the `say` line is the operator variant). With a persona chosen the opening line names that person and says the token is that person's own, and the `http` event also carries `persona`, `as_user` and `roles`; no `tag` is set for this beat, so the "remembered for Act 5" line is not added (`console/jobs.py:445-449#_as_persona`, `console/jobs.py:855-857#tag`):

```json
{"type": "say", "text": "Calling vendor.get_market_quote through the APIM gateway with the signed-in user's Entra token. No key anywhere."}
{
  "type": "http",
  "server": "vendor",
  "tool": "get_market_quote",
  "args": "{\"ticker\": \"<ticker>\"}",
  "status": 200,
  "seconds": <n>,
  "decision": "",
  "reason": "",
  "request_id": "<request-id>",
  "excerpt": "<the quote payload below, pretty-printed, at most 1100 characters>",
  "leak": [],
  "attack": "",
  "verdict": "allowed",
  "wall": null,
  "title": "Allowed",
  "plain": "The user was authenticated at the gateway; the vendor's API key was attached by the gateway and never reached the agent or the user.",
  "lights": {"user": "ok", "entra": "ok", "apim": "ok", "m-vendor": "ok"}
}
{"type": "done", "status": "done", "summary": "Allowed: HTTP 200"}
```

(`console/jobs.py:843-859#run_gateway`, `console/jobs.py:229-253#http_result`, `console/jobs.py:129-143#excerpt`, `console/jobs.py:244-245#vendor`.) The payload the vendor returns, and the audit event it writes, are:

```json
{"ticker": "<ticker>", "price": <price>, "change_pct": <pct>, "source": "vendor-mock (synthetic)", "request_id": "<request-id>"}
```

```json
{
  "args_sha256": "<sha256>",
  "aud": null,
  "azp": null,
  "data_class": "external",
  "decision": "allow",
  "downstream": {"service": "vendor-mock", "status": 200, "target": "quote"},
  "event": "tool_call",
  "jti": null,
  "obo": false,
  "reason": null,
  "request_id": "<request-id>",
  "result_bytes": <n>,
  "roles": [],
  "scp": "",
  "server": "vendor",
  "tid": null,
  "tool": "get_market_quote",
  "trace_id": "<trace-id>",
  "ts": "<utc-time>",
  "user_oid": null,
  "user_upn": null
}
```

(`src/mcp/abw_mcp/servers/vendor.py:30-43#get_market_quote`, `src/mcp/abw_mcp/registry.py:195-217#request_id`, `src/mcp/abw_mcp/audit.py:178-216#build_event`.) Field notes. The payload has no `decision` key, so the console's `decision` and `reason` are empty strings; `request_id` is APIM's own id (GUID-shaped), which is why the quote, the gateway row and the audit row join. Price and change are deterministic functions of the ticker and `source` says so. In the audit event every caller field is empty, because the vendor app does not read a token and APIM deleted it (Findings F4); `downstream.status` is a literal 200 written by the handler, not a measured vendor response; `obo` is false and `data_class` is `external`. A call refused at the gateway leaves no vendor row at all.

**Failure or denial outcomes.** A refusal at the gateway never reaches the vendor, so the key is never attached. Shapes and wall labels are in 9.1.6 and 9.1.7.

| Situation | What happens | Shape and where it is decided |
|-----------|--------------|-------------------------------|
| The token is missing, expired, wrongly signed or minted for another application | `validate-jwt` fails and the policy's `on-error` returns 401 with a `WWW-Authenticate` challenge that points at the gateway's protected-resource document (`infra/apim/policies/mcp-jwt.policy.xml:96-112#on-error`) | Gateway 401: `{"error":"unauthorized","server":"vendor","reason":"a valid Entra access token for this MCP server is required"}`. The console card reads the generic "Refused" with no wall and the strip lights the APIM and vendor nodes green, because that long `reason` is not a code in its table (`console/jobs.py:176-198#judge`, `console/catalog.py:118-125#explain`, Findings F50) |
| A valid token without `MarketData.Read` (Ian's case) | `abw-deny` returns `missing_role`; the 403 runs before the rate limit and before the vendor section, so no key is attached. Because `listOpen` is false, `tools/list` is refused as well (`infra/apim/policies/mcp-jwt.policy.xml:42-44#missing_role`, `demo/prove.py:629-630#vendor`) | Gateway 403: `{"error":"forbidden","reason":"missing_role","server":"vendor","request_id":"<request-id>"}`. Card "The gateway said no", wall 1; lights `{"user":"ok","entra":"ok","apim":"deny"}`; summary "Refused: HTTP 403 BLOCKED missing_role" (`infra/apim/policies/mcp-jwt.policy.xml:64-80#return-response`, `console/catalog.py:62-66#missing_role`) |
| The token is revoked, or minted for an application that is not allow-listed | The same 403 path with reason `revoked` or `client_not_allowed` | Gateway 403; cards "Kill switch" and "Wrong application", wall 1 (`console/catalog.py:67-76#revoked`) |
| The token lacks the `Tools.Read` scope | The same 403 path with reason `missing_scope` | Gateway 403; the console has no entry for this code, so it reads the generic "Refused" (`infra/apim/policies/mcp-jwt.policy.xml:39#missing_scope`, Findings F50) |
| More than 120 calls in 60 s from one user | `rate-limit-by-key` answers 429 | Gateway 429; card "Rate limit", wall 1 (`infra/apim/policies/mcp-jwt.policy.xml:81#rate-limit-by-key`, `console/catalog.py:82-86#rate_limit`) |
| The vendor app refuses the key: a direct call, a guessed key, or a rotation that reached one copy and not the other (the last is an inference) | `VendorKeyMiddleware` returns 401 | 401 `{"error":"invalid_vendor_key"}` from the app (`src/mcp/abw_mcp/app.py:115-142#invalid_vendor_key`). Through the gateway the console relabels a 401 that has no `reason` as "No valid token" (wall 1) and so blames the user's token; by code reading, not observed (Findings F34, F50) |
| The ticker is not one to six capital letters (the button's ticker is fixed, so only a hand-made call) | The registry returns a soft result | HTTP 200, decision `ERROR`, reason `invalid_arguments`; the payload says ERROR, but the audit event is `tool_denied` with decision deny (Findings F36). The console reads it as a failed call with a generic card (`src/mcp/abw_mcp/servers/vendor.py:13-14#TickerArgs`, `src/mcp/abw_mcp/registry.py:158-220#call_tool`, Findings F42) |
| A persona is chosen but has not signed in | The start is refused before any call | HTTP 409 from `api_jobs_start` with a message (`console/server.py:128-135#api_jobs_start`, `console/jobs.py:595-612#persona_error`) |
| The kill switch is engaged, or a disruptive job is running | The start is refused before any call | HTTP 409 with a message (`console/jobs.py:495#NEEDS_OPEN_GATEWAY`, `console/jobs.py:480-491#conflicts`, `console/jobs.py:503-533#start`) |
| The operator is not signed in to Azure, or the token request fails | `_run` turns the exception into an `error` event | The job ends `failed` with "Not signed in to Azure. Run `az login` as the demo operator, then press the button again." (`console/jobs.py:535-548#_run`, `console/jobs.py:163-173#friendly`) |
| Any gateway refusal above | The job finishes `done` | The status never separates refused from worked; the card and the summary text do (`console/jobs.py:858-859#label`, Findings F44) |

**Evidence produced.**

| Evidence | Where it lands | How to retrieve it |
|----------|----------------|--------------------|
| The card and the `done` line (tag `live`) | The job's event list in the console (`console/jobs.py:276-280#emit`) | Immediate: status, request id, verdict, the quote |
| The gateway row (tag `logs`) | One row per call in the APIM gateway logs, with the user's `oid`, which `AbwGateway` reads from the policy's trace record (`observability/kql/AbwGateway.kql:7#TraceRecords`, `observability/kql/AbwGateway.kql:25#UserOid`). The vendor's own audit row below has no user, so this row is how the person is tied to the call; the decision metric and the trace listed below carry the same `oid` | The first query below, by `RequestId` (`observability/kql/AbwGateway.kql:1-12#AbwGateway`; lag in section 11) |
| The vendor's audit row (tag `logs`) | Standard output of the vendor app, collected into the console logs of the public host; no user columns (Findings F4); the blob copy cannot land by code reading (Findings F48) | The second query below (`observability/kql/AbwMcpAudit.kql:1-34#ContainerAppConsoleLogs`, `infra/03-platform.bicep:446-461#diagCaePub`); the playbook records the same for Priya's rows and for the agent-driven vendor call of Act 7 ("the vendor server's own audit row has no name", `docs/PROOF-PLAYBOOK.md:1138#vendor`, `docs/PROOF-PLAYBOOK.md:1449#vendor`) |
| The key swap itself (tag `logs`, not verified) | The `vendor_request` record on logger `abw.vendor`, with `saw_authorization_header` and `saw_vendor_key`. No saved query returns it and the repository does not show that it is emitted (Findings F35, F49); if it is, the public environment that hosts the vendor app sends the `ContainerAppConsoleLogs` category to the workspace (`infra/03-platform.bicep:446-461#diagCaePub`), the table that the saved audit query reads (`observability/kql/AbwMcpAudit.kql:4#ContainerAppConsoleLogs`) but filters this record out of, because it has no `request_id` | Not retrievable by a saved query; the evidence is the policy text and the portal |
| The live policy (tag `probe`) | The APIM node's drawer reads the vendor API's live policy through Azure Resource Manager with the operator's delegated token, strips comments and reports the token check, the rate limit, the roles, whether discovery is open and whether the text contains `x-vendor-key` (`console/azure_probe.py:336-372#gateway_policy`) | Click the APIM node and choose the Vendor tab (`console/web/strip.js:146-182#show`, `console/server.py:193-201#api_gateway_policy`). The "Vendor key" row proves only that a header of that name appears in the policy; it never reads the named value (`console/azure_probe.py:370#vendorKey`, `console/web/strip.js:169#vendorKey`, Findings F45) |
| The named value (tag `portal`) | APIM -> Named values -> `abw-vendor-key`: type Key Vault, secret, value hidden | The playbook and the portal tour give the path; the presenter reads it and does not reveal the value (`docs/PROOF-PLAYBOOK.md:398#vendor`, `docs/TALK-TRACK-PORTAL-TOUR.md:266#abw-vendor-key`, `docs/TALK-TRACK-PORTAL-TOUR.md:321#abw-vendor-key`) |
| The decision metric and trace (tag `logs`) | One `abw-gateway-decisions` metric (dimensions server, decision, reason, oid) and one trace per call (`infra/apim/policies/mcp-jwt.policy.xml:51-63#abw-gateway`); the trace is also where the gateway row gets its `oid`. Platform behaviour: Learn says a trace whose severity is at or above the diagnostic's verbosity also becomes a Trace record in Application Insights, with the metadata as properties (https://learn.microsoft.com/azure/api-management/trace-policy). Here both are `information` (`infra/apim/policies/mcp-jwt.policy.xml:57#severity`, `infra/05-apim.bicep:102#verbosity`), so `AppTraces` should hold the `oid` too; no saved query reads that copy and no proof run recorded it (not verified) | Sections 10 to 12 |
| The terminal helper | `abw-gw` with the vendor server and the quote tool makes the same call from PowerShell and prints the request id (`demo/stage.ps1:90-120#abw-gw`) | Run it; the ticker is a parameter |

```kusto
AbwGateway(24h)
| where Server == 'vendor'
| project TimeGenerated, RequestId, ResponseCode, Decision, Reason, UserOid, Outcome
| order by TimeGenerated desc
```

```kusto
AbwMcpAudit(24h)
| where Server == 'vendor'
| project TimeGenerated, RequestId, Tool, Decision, DownstreamService, DownstreamStatus, UserOid, OnBehalfOf, DataClass
```

The rows for a healthy call have this shape. The gateway row names the user and the vendor row does not; a refused call has only the first row, with `Decision` "deny", the reason in `Reason` and `Outcome` "denied" (403) or "unauthenticated" (401, no trace record):

```json
{"TimeGenerated": "<utc-time>", "RequestId": "<request-id>", "ResponseCode": 200, "Decision": "allow", "Reason": "ok", "UserOid": "<user-oid>", "Outcome": "allowed"}
{"TimeGenerated": "<utc-time>", "RequestId": "<request-id>", "Tool": "get_market_quote", "Decision": "allow", "DownstreamService": "vendor-mock", "DownstreamStatus": 200, "UserOid": "", "OnBehalfOf": false, "DataClass": "external"}
```

The contrast is used again in Act 5: the "Usage by user" table groups this server and the legacy server in one "(no user context)" row (`docs/TALK-TRACK.md:189#vendor`, `docs/PROOF-PLAYBOOK.md:451#vendor`; 9.6).

**How the console runs it.**

1. The catalog entry 3.3 gives the kind `gateway`, server `vendor`, tool `get_market_quote` and the fixed ticker (`console/catalog.py:399-410#get_market_quote`).
2. The page posts it, adding the chosen persona for the kinds that allow one (`console/web/util.js:160-162#startJob`, `console/web/personas.js:11#AS_KINDS`, `console/jobs.py:420#PERSONA_KINDS`).
3. `run_gateway` calls `call_gateway`, which gets the token and posts through the demo client; `http_result` and `judge` build the card (`console/jobs.py:843-859#run_gateway`, `console/jobs.py:452-462#call_gateway`, `console/jobs.py:229-253#http_result`).
4. Clicking the vendor node opens the `mcp` drawer; clicking the APIM node opens the live policy viewer with a Vendor tab (`console/catalog.py:998-1004#m-vendor`, `console/catalog.py:963#policyServers`).
5. Act 7 runs the same call per person and as the operator: the vendor scenarios of 9.8.1 and the role matrix of 9.8.2 (`console/role_tabs.py:95-97#get_market_quote`, `console/role_tabs.py:145-146#vendor`, `console/role_tabs.py:412-416#get_market_quote`).

**How demo/prove.py proves it.** Proof P07 makes four calls: a quote with a user token must come back; a call with no token must get 401 at the gateway; a direct call to the vendor app without its key must get 401; and a direct call with a guessed key in `x-vendor-key` must get 401. The direct calls reach the public host from the laptop. The label of the third check names `invalid_vendor_key`, but the test asserts only the 401 status. Proof P02 adds the role: Priya gets a quote through the gateway and Ian gets 403 `missing_role` on a `tools/list` call (`demo/prove.py:620-621#get_market_quote`, `demo/prove.py:629-630#vendor`, `demo/prove.py:75-79#EXPECT`). Taken together, the P07 checks show that the gateway call succeeds where a call without the key is refused, so the gateway supplies a valid key; nothing shows that the user's token is removed or that the key comes from Key Vault (`demo/prove.py:736-747#p07`, Findings F35, F49). `python demo\prove.py --only P06,P07` runs the P00 preflight first and then both proofs (`demo/prove.py:7#preflight`); the scrubbed run records P07 as passed with its four checks ok (`demo/evidence-scrubbed/`).

**Failure modes and what the presenter should say.**

- The card reads "The gateway said no" with 403 `missing_role`: the operator's token carries no `MarketData.Read`. That is the role check working; the command-line client prints a token's claims with `--claims` (`demo/mcpclient.py:178#claims`). Say so, then continue with the next beat.
- The card reads "Refused" with the gateway's 401 sentence and green lights: the token is missing, expired or for another application; the lights are wrong for this case (Findings F50). Press the button again; sign in to Azure again if the operator is not signed in.
- The card reads "No valid token" although the user's token is fine: the 401 may have come from the vendor app after a key rotation reached only one copy (Findings F34, F50; inferred, not observed).
- The start is refused with HTTP 409: release the kill switch (beat 4.5, in 9.5) or wait for the disruptive job to end.
- Someone asks "is the key really in Key Vault?": open the named value in the portal and show that it is a secret and a Key Vault reference; do not reveal it. The drawer's sentence is asserted, not read (Findings F45).
- Someone asks "who can read the key?": the person who deploys can (Findings F51). The promise is about the request path: the user, the agent and the vendor's view of the call.

Say: "Third-party tools get the same user check - and you never hand them a key to pass around." (`console/catalog.py:408#sales`). The talk track's earlier line is the Act 2 version: the one key that exists lives in Key Vault and is injected by APIM (`docs/TALK-TRACK.md:158#vendor`).

**Why and trade-offs.** Why the gateway holds the key: the vendor understands only a static key, and a key that a user or an agent carries can be copied, logged or leaked, while a key shared by every user says nothing about who called. At the gateway the call is tied to the user's `oid` in one row per call, and the vendor sees only a key (`DESIGN.md:108#External`, `DESIGN.md:124#x-vendor-key`). Why a Key Vault named value: the policy text holds no secret, the value is hidden in the portal, and the address is version-less so a new version needs no redeploy (`scripts/deploy.ps1:374#versionless`; Platform behaviour: https://learn.microsoft.com/azure/api-management/api-management-howto-properties). **Trade-off / limitation:** (1) The key lives in two places, the vault for APIM and an inline secret of the vendor app (`infra/04-apps.bicep:180-186#vendor-api-key`; the parameter's own description says the vendor keeps its own copy), so a rotation reaches APIM within four hours but not the vendor app; the platform comment and `DESIGN.md:147` describe a vault read by the vendor identity that the code does not do (Findings F34). (2) The vendor app is on the public host with only the key between it and the internet: anyone who holds the key can call it without the gateway and without a user check, which is what P07's direct calls test from the other side; the repository sets no IP restriction for it (`infra/modules/mcp-app.bicep:39-44#externalIngress`). (3) The vendor's audit event has no user (Findings F4) and its blob copy fails by code reading (Findings F48). (4) The evidence of the swap is thin: the vendor's own record may never be emitted (Findings F35, F49) and the drawer's Key Vault sentence is asserted (Findings F45). (5) The console mislabels the two likely 401s and finishes refusals as `done` (Findings F50, F44). (6) "The user never sees the key" is a statement about the request path. The person who deploys, who is also the console's signed-in operator, holds a Key Vault role that can read secrets (Platform behaviour: https://learn.microsoft.com/azure/key-vault/general/rbac-guide), and the deploy script keeps the generated key in a local file; the comment at `infra/04-apps.bicep:37-38` says only the gateway and the vendor mock ever hold it (`infra/03-platform.bicep:733-764#raOpKv`, `infra/04-apps.bicep:37-38#legacy`, Findings F51).

#### 9.4.5 Act 3 evidence, proofs and presenter summary

| Beat | Layers that decided | Evidence tag | Sentinel | Proof ids |
|------|---------------------|--------------|----------|-----------|
| 3.1 internal data through the private server | The private server's token and role check (wall 2), then Cosmos DB's own data-plane roles on the user's own token (wall 3). No gateway (wall 1): the path never touches APIM | `live`, then `logs` (the MCP audit row and the Cosmos DB data-plane log) | none for an allowed call | P06 |
| 3.2 prove the server is private | None: no call is decided. The cause is the internal-ingress host setting and the private DNS zone (Configured) | `live`; the node drawer is `probe`; the portal steps are `portal` | none | P06 |
| 3.3 vendor quote | The gateway's token check, role check and key swap (wall 1), then the vendor app's key check. No wall 2, because the vendor's tools allow every caller (`src/mcp/abw_mcp/servers/vendor.py:62-71#allow_all`), and no wall 3, because the vendor holds no firm data | `live`, then `logs` (the gateway row); the live policy viewer is `probe`; the named value is `portal` | the generic gateway rules only | P07 (the role check: P02) |

**Sentinel.** No Sentinel rule is aimed at Act 3, and the private server is the kind that the fewest rules can see. These are the rules that read rows this act produces:

| Rule | Reads | What it does for Act 3 |
|------|-------|------------------------|
| ABW-004 client not allowed (High) | `AbwGateway` rows with reason `client_not_allowed` (`observability/sentinel/abw-004-client-not-allowed.kql:11-13#client_not_allowed`) | Fires for the vendor path when a token minted for another application reaches the gateway (9.5, beat 4.4). It has no row to read for the private server |
| ABW-005 revoked principal (High) | `AbwGateway` rows with reason `revoked` (`observability/sentinel/abw-005-revoked-principal.kql:11-13#revoked`) | Fires for the vendor path after the kill switch (9.5, beat 4.5). The private server never reads the deny list (Findings F10) |
| ABW-009 throttled burst (Low) | `AbwGateway` rows with outcome `rate_limited`, five or more in 30 minutes (`observability/sentinel/abw-009-throttled-burst.kql:11-14#rate_limited`) | Applies to the vendor path, where the policy allows 120 calls per minute per user (`infra/apim/policies/mcp-jwt.policy.xml:81#rate-limit-by-key`). Nothing throttles the private server |
| ABW-006 repeated denials (Medium) | `AbwDenials` for 30 minutes: three or more refusals for one principal from any layer (`observability/sentinel/abw-006-repeated-denials.kql:11-15#AbwDenials`) | In `AbwDenials` the MCP layer is every audit row whose decision is `deny`, so the private server's refusals count when they carry a user (`observability/kql/AbwDenials.kql:57-66#Decision`). The rule skips rows with no principal. Business errors count too (Findings F36) |
| ABW-007 entitlement drift (High) | `AbwDenials` rows of the data-plane layer, which reads only Storage's log (`observability/sentinel/abw-007-entitlement-drift.kql:11-12#3-data-plane`, `observability/kql/AbwDenials.kql:67-78#StorageBlobLogs`) | It does not see a Cosmos DB refusal (Findings F52) |

The other four rules do not read this act's rows. ABW-003 filters on the legacy server, so the vendor's user-less audit rows do not fire it (`observability/sentinel/abw-003-legacy-no-identity.kql:11-12#legacy`). A token refused by the private server leaves an `auth_failed` row with no user, which no rule reads (Findings F53). Section 11.3 lists all nine rules.

**The side-by-side exhibit: where the person's name is recorded.** The three kinds of server leave the user's name in different places. Provenance: Implemented (read from the code); the playbook records the same split from a real run (`docs/PROOF-PLAYBOOK.md:1447#OnBehalfOf`, `docs/PROOF-PLAYBOOK.md:1449#vendor`).

| Record | Internal (the wall server of Act 1) | Private | External (the vendor) |
|--------|--------------------------------------|---------|-----------------------|
| Gateway log, `AbwGateway` | A row per call with `UserOid` (`observability/sentinel/abw-004-client-not-allowed.kql:11-13#UserOid`) | None: the app is not an APIM API (`DESIGN.md:107#kill`); the playbook records 0 rows (`docs/PROOF-PLAYBOOK.md:1447#AbwGateway`; the portal tour says the same at `docs/TALK-TRACK-PORTAL-TOUR.md:351#AbwGateway`) | A row per call with `UserOid`; the vendor's own audit row (next row) names no user, so this row is where the person is named for this kind |
| MCP audit, `AbwMcpAudit` | `UserUpn` and `UserOid` set, `OnBehalfOf` true (`src/mcp/abw_mcp/audit.py:201-209#user_upn`) | The same fields; `OnBehalfOf` follows the `COSMOS_OBO` setting, true by default (`src/mcp/abw_mcp/servers/private.py:34#cosmos_obo`) | `UserUpn` and `UserOid` empty, `OnBehalfOf` false, `DataClass` external (`src/mcp/abw_mcp/servers/vendor.py:34-43#obo`, `src/mcp/abw_mcp/servers/vendor.py:62-71#data_class`; Findings F4) |
| The data store's own log | Storage: `RequesterUpn` is the user (`docs/PROOF-PLAYBOOK.md:276#StorageBlobLogs`) | Cosmos DB: `AadPrincipalId` is the user's object id (`docs/PROOF-PLAYBOOK.md:383-393#AadPrincipalId`) | None: no firm data store is touched |

Two queries show the split on a live workspace. The first counts the people behind the gateway rows per server:

```kusto
AbwGateway(1d)
| summarize Calls = count(), Users = dcountif(UserOid, isnotempty(UserOid)) by Server
| order by Server asc
```

Expected: rows for the governed servers that were called, for `vendor`, for `legacy` and for the front door (`agents`); no row for `private`. `Users` is above 0 for the governed rows and 0 for `legacy`, whose API carries only a subscription key (`infra/05-apim-apis.bicep:168-182#legacyApi`). The second counts the audit rows that name a user:

```kusto
AbwMcpAudit(1d)
| where Event == 'tool_call'
| summarize Calls = count(), WithUser = countif(isnotempty(UserUpn)), OnBehalf = countif(OnBehalfOf) by Server
| order by Server asc
```

Expected: `tool_call` is the event of an allowed call; a refusal is written as `tool_denied` (`src/mcp/abw_mcp/registry.py:31-39#tool_call`, `src/mcp/abw_mcp/registry.py:57-66#tool_denied`). For `private`, `WithUser` and `OnBehalf` both equal `Calls`; for `vendor` and `legacy` both are 0. The same function returns the private server's `tool_denied` rows with `Decision` "deny" when you drop the event filter.

**Why:** the person's name appears at the gateway for the kinds behind it and at the data store for the kinds that read on the person's behalf, and the vendor's own record names nobody. A request id joins the three records of an internal call. For a private call there is no gateway row, the audit and data rows need a request id that the Foundry runtime must forward (Findings F38), and the chain query labels the Cosmos DB row with the wrong actor (Findings F40).

**Why and trade-offs.**

- The private path is outside the gateway. The kill switch, the per-user rate limit, the runtime client allow-list and the gateway's telemetry do not reach it (`DESIGN.md:107#kill`, `console/catalog.py:987-997#Honest`; Findings F10). A revoked user keeps access for the life of the stored token (Entra lifetimes are 60 to 90 minutes: `DESIGN.md:223#Foundry`), and the design note says this was read from the code and not exercised live. The server's own client allow-list is a deploy-time setting (`infra/04-apps.bicep:77-80#MCP_ALLOWED_AZP`), not the runtime named value that the allow-list scene of beat 4.4 changes (Findings F53). The production fix, an internal gateway in front of the server or a deny list that the server reads itself, is Not in this repo.
- The evidence for the private and external kinds is thinner than for the internal kind. The private call has no gateway row; a Cosmos DB refusal of a person is neither audited nor alerted (Findings F3, F52). The vendor's audit names nobody (Findings F4), its blob copy fails by code reading (Findings F48) and its key-check log record may never be emitted (Findings F35, F49).
- The proofs check reachability and refusals, not identity. P06 reads no log, and P07 shows that the gateway supplies a valid key but not that the user's token is removed; the Cosmos DB refusal of a person is Designed only, and the Storage version of that drill is 9.7, beat 6.5.
- Who can run what: the vendor beat is the only Act 3 beat that a persona can run, through the `gateway` kind; the private server can be exercised only through the agent (3.1) and DNS (3.2), because the gateway job kind rejects it (`console/jobs.py:420#PERSONA_KINDS`, `console/jobs.py:573#SERVERS`; Findings F27).
- The console's strip lights the gateway node for a private call although no gateway is involved (Findings F37).
- "The same user token goes through all three" is loose wording: each connection has its own scope and target application (Findings F25).

**Presenter path** (`docs/TALK-TRACK.md:164-172#Whose`, 2.5 minutes; Provenance: Designed): press **Ask about positions** (3.1) and fill the 20 seconds with the private-server sentence: internal ingress only, not published at the gateway, only the agent runtime inside the virtual network reaches it, and it reads Cosmos DB with the person's own token. Read the result card and say that the database, not the code, decided who may read. Press **Check DNS** (3.2, 1 s): public DNS has no record and this laptop cannot resolve the name. Glance at the Act 2 job chip (`docs/TALK-TRACK.md:169#Glance`). Land with the three kinds (`docs/TALK-TRACK.md:171#Customers`): internal is the gateway plus Container Apps, external is a vendor behind the gateway with its key kept there, and private has no public path at all. Replace the talk track's last sentence with this one: the user's identity reaches the internal and private servers on a token scoped to each, and reaches the vendor not at all (Findings F25). The optional 20-second vendor press (3.3) is the first beat to add when ahead and the second to cut when behind (`docs/TALK-TRACK.md:300#vendor`, `docs/TALK-TRACK.md:301#vendor`). Say the private server's gap before someone finds it: it is outside the gateway and outside the kill switch (`docs/TALK-TRACK-PORTAL-TOUR.md:354#Honest`; Findings F10).

---

[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [8. MCP server internals](08-mcp-server-internals.md) | Next: [9. Scenarios, part 2: Act 4 (9.5)](09b-scenarios-act-4.md)
