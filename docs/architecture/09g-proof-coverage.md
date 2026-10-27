[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [9. Scenarios, part 6: Act 7, the admin tab, cost and evidence (9.8.10 to 9.8.15)](09f-scenarios-act-7b.md) | Next: [10. Data flow and correlation](10-data-flow-and-correlation.md)

> This file ends section 9 (Scenarios: Acts 1 to 7 end to end), which is split across seven files. This one holds 9.9 to 9.10.

### 9.9 Proof coverage

**What this section proves.** The claims in the talk that have a proof are executable; 9.9.3 and 9.9.4 list the beats that have none, or only a related one. `demo/prove.py` is a harness of about 1,200 lines that runs 18 proofs, P00 to P17, against the live platform and records every check it makes (`demo/prove.py:3-3#executed`). This section explains how the harness works (9.9.1), what each proof asserts and what state it changes (9.9.2), which beats of Acts 1 to 7 a proof actually backs (9.9.3) and what no proof covers (9.9.4). It refines the act-level table in 9.1.9: that table says which proofs an act exercises, this section says which beat each proof stands behind and how closely.

**Why.** A demo shows a result once, to the people in the room. A proof can be run again by anyone with access to the tenant, and it fails when the platform drifts. Three choices make that practical on a live platform: a proof that flips a control puts it back in a `finally` block, though the demo orders that P04 and P05 add stay (`demo/prove.py:15-15#finally`; Findings F9-15); every run writes an evidence file and a state file (`demo/prove.py:16-16#prove-`); and the whole set runs from one command, documented as about 30 minutes (`README.md:84-84#prove.py`).

**Trade-off / limitation.** The operator makes every call. Where a persona is needed, the operator mirrors the persona's app roles instead of signing in as that person (`demo/prove.py:303-303#persona`), so a proof shows how the platform answers a token that carries those roles, not a real persona sign-in (Findings F9-8). The result is also a point in time: the scoreboard keeps the latest result of each proof across all runs, so a green board can mix runs (`demo/scoreboard.py:22-43#load_latest`, `demo/scoreboard.py:28-29#startedUtc`; Findings F9-9).

#### 9.9.1 How the harness works

**Model.** A proof is a function registered by the `proof` decorator in the `PROOFS` registry. It receives a `Ctx` that records checks, facts, request ids and Sentinel traffic stamps (`demo/prove.py:435-452#PROOFS`, `demo/prove.py:455-486#Ctx`). A check is a labelled boolean with a detail string that is cut to 400 characters (`demo/prove.py:470-475#check`).

**Pass rule.** A proof passes only when it recorded at least one check and every check is true. An unexpected exception becomes a failed check, "proof ran without an unexpected error", with the traceback kept in the notes, so a proof cannot pass by crashing early (`demo/prove.py:1146-1150#bool(ctx.checks)`). If P00 fails, the run stops unless `--force` is given (`demo/prove.py:1157-1159#stop_on_preflight`).

**Order.** The runner does not follow the numbers. The proofs that read what the earlier proofs created (P10 and P13) go last, with P17 between them; P17 runs the pack's own `check` commands and does not depend on what the earlier proofs created. The comment above the list gives the reason for the rest: P02 flips the operator's roles, Foundry mints the user's token at its first agent call, and so the agent proofs go before P02 (`demo/prove.py:1127-1132#ORDER`). The order is P00, P01, P03, P04, P07, P06, P05, P08, P09, P02, P14, P15, P12, P16, P11, P10, P17, P13.

**Flags.**

| Flag | Effect |
|---|---|
| `--list` | Prints the proofs and exits |
| `--only P03,P12` | Runs the named proofs |
| `--skip` | Leaves the named proofs out |
| `--group` | Runs one group: core, agent, ops, policy or verify |
| `--verify` | Shortcut for the verification proofs P10, P17 and P13 |
| `--restore` | The panic button: puts the kill switch, the client allow-list, the operator's wall-group membership and the persona baseline back, then exits |
| `--force` | Keeps going when P00 fails |
| `--timeout` | Minutes the verification proofs wait for logs, alerts and incidents; the default is 25 |
| `--drift-timeout` | Seconds P16 waits for Storage to deny after the group change; the default is 600 |

The flags are declared in `demo/prove.py:1164-1173#--drift-timeout`; `--restore` is dispatched at `demo/prove.py:1182-1183#restore_all` and `--verify` at `demo/prove.py:1186-1187#P17`. Three selection rules matter. P00 is added to the front of every selection unless every selected proof is a verification proof (`demo/prove.py:1201-1202#P00`). A full run, with no `--only`, `--group` or `--verify`, clears the stored traffic stamps first (`demo/prove.py:1206-1207#traffic`). An interrupt runs the same restore as `--restore` (`demo/prove.py:1210-1215#restore_all`).

**Restore.** `restore_all` runs four independent steps and prints "restored:" or "RESTORE FAILED" for each: the kill switch reset, the client allow-list reset, the operator back in the Falcon wall group, and the persona baseline (`demo/prove.py:339-355#restore_all`). Because the steps are independent, one failure does not stop the others. P02 (`demo/prove.py:631-631#finally`), P15 (`demo/prove.py:923-923#finally`), P12 (`demo/prove.py:951-951#finally`) and P16 (`demo/prove.py:984-984#finally`) also restore the control they flip, each in a `finally` block; P04 and P05 add demo orders that nothing removes (Findings F9-15).

**State, request ids and stamps.** The harness keeps a state file next to the evidence (`demo/prove.py:44-44#STATE_FILE`) and saves it after every proof (`demo/prove.py:488-503#save_state`). A proof that wants to be found later records a request id under `<proof id>.<key>` (`demo/prove.py:477-480#rid`); P10 needs `P03.falcon_ok` and `P03.orion_denied` to find the allowed and the denied read that P03 made (`demo/prove.py:1024-1030#P03.falcon_ok`). A proof that expects Sentinel to react stamps a traffic entry with the rule id and the time the attacking proof started, not the time the check ran (`demo/prove.py:482-485#isoformat`). P13 later waits for an alert and an incident whose event time is at or after that stamp, because the rules re-run every five minutes over a look-back window (`demo/prove.py:1085-1086#look-back`).

**Acting as people.** The gateway sees whichever roles the operator's token carries. `become` runs the persona-mirroring script in the `identity` folder to copy a persona's app roles onto the operator, with three attempts and a pause that grows. `await_roles` then waits until the role claim is stable for two polls, up to 150 seconds. `_operator_token` fetches a fresh token and re-fetches up to ten times, three seconds apart, until the presence or absence of a role claim matches what the active persona should have on that server (`demo/prove.py:323-337#become`, `demo/prove.py:309-320#await_roles`, `demo/prove.py:260-276#_operator_token`). The baseline the proofs return to is the roles of Wes and Tara together (`demo/prove.py:73-73#BASELINE`).

**Agents.** `ask_agent` runs `src/agent/ask.py` with flags for approval, for not waiting and for saving the run (`demo/prove.py:384-399#ask_agent`). After a role change the agent keeps using the OAuth token Foundry already holds for the user; the code comment gives 60 to 90 minutes. `settle_agent` therefore probes the desk agent every 60 seconds, for up to 15 minutes, until a read-only call succeeds (`demo/prove.py:405-430#settle_agent`).

**Answers and retries.** `Resp` wraps one HTTP answer. `denied` is true for a DENIED or BLOCKED decision or for status 401, 403 or 429; `ok` is true for a 200 with a result that is not denied and not an ERROR decision (`demo/prove.py:241-247#denied`). `with_retry` retries any exception raised by the wrapped call (token fetches, for example), four attempts with a pause of 3, 6 and 9 seconds; gateway tool calls are not wrapped, so a refusal is never retried into a pass (`demo/prove.py:116-126#with_retry`). A transport exception in a tool call becomes a `Resp` with status -1 (`demo/prove.py:297-298#Resp`).

**Evidence and scoreboard.** At the end the runner writes `prove-<utc>.json` with `startedUtc`, the operator, the resource group and the result of each proof (`demo/prove.py:1224-1230#startedUtc`). `demo/scoreboard.py` reads every evidence file, keeps the latest result of each proof id, writes `SCOREBOARD.md` and `scoreboard.json`, and with `--check` exits 1 unless P00 to P17 all have a passing latest result (`demo/scoreboard.py:19-19#EXPECTED`, `demo/scoreboard.py:22-43#load_latest`, `demo/scoreboard.py:78-96#main`). The Demo Console serves the same board (`console/server.py:204-208#api_scoreboard`).

**Time budget.** The docstring says about 30 minutes, the last 5 or so waiting for Sentinel (`demo/prove.py:6-6#Sentinel`). In the shipped run the per-proof times add up to about 23 minutes (a derived sum of 1,376 seconds). Four proofs take more than 90 seconds: P13 at 436 seconds (`demo/evidence-scrubbed/scoreboard.json:197-197#seconds`), P11 at 224 (`demo/evidence-scrubbed/scoreboard.json:156-156#seconds`), P17 at 104 (`demo/evidence-scrubbed/scoreboard.json:255-255#seconds`) and P12 at 96 (`demo/evidence-scrubbed/scoreboard.json:183-183#seconds`). The documents quote four different totals (Findings F9-14), and the README's own 29-minute figure belongs to a later run than the shipped board's (Findings F9-13).

#### 9.9.2 The 18 proofs

The proofs are grouped as the harness groups them and listed in run order. `Checks` is the count in the shipped run: 109 in total, all 18 rows carrying one run time, so the shipped board does not mix runs (`demo/evidence-scrubbed/SCOREBOARD.md:3-3#109/109`, `demo/evidence-scrubbed/SCOREBOARD.md:7-24#PASS`). `State it changes` says what a proof leaves behind in the tenant when it ends. Documents elsewhere quote 110 checks from a later run whose raw board does not ship (Findings F9-13).

**Core group (47 checks).**

| Proof and layer | What it asserts | Checks | State it changes | Code |
|---|---|---|---|---|
| P00, platform | The baseline preflight. The operator is signed in; the baseline roles `Wall.Falcon`, `Trade.Execute` and `Research.Read` are present; the kill switch is not engaged; the client allow-list holds exactly three apps, one of them the Azure CLI; the research server lists at least two tools. | 5 | None | `demo/prove.py:508-529#abw-allowed-azp` |
| P01, platform | No keys. All six data-service types exist in the resource group and each resource found passes its rule in `KEY_RULES` (Storage shared-key access off, Cosmos DB, AI Search and Foundry key authentication off, the registry's built-in user off, Key Vault on RBAC). Each of the four governed apps holds no secret beyond the telemetry connection string and no literal key-like app setting. The `AbwZeroKeys` query returns rows, so the evidence is not empty. Seven days of `StorageBlobLogs` show no account-key or SAS request, apart from Azure-internal blob-service property calls from a `10.` address that carry no identity, which are recorded as a fact. No anonymous request succeeded. | 17 | None | `demo/prove.py:532-601#KEY_RULES`, `demo/prove.py:576-601#GetBlobServiceProperties` |
| P03, MCP server and data plane | The information barrier. `list_my_wall_crossings` shows Falcon; a Falcon search and a read of `FALCON-001` succeed (request id `falcon_ok`); a read of `ORION-001` is DENIED with `project_not_in_token_roles` (request id `orion_denied`) and the denial carries a request id; an Orion search is also DENIED, so the existence of the deal does not leak. Stamps ABW-001. | 6 | None | `demo/prove.py:638-657#project_not_in_token_roles` |
| P04, MCP server | Trading controls. ZYNX is on the restricted list and ACME is not. A BUY of 100 ZYNX is DENIED with `restricted_list` or `separation_of_duties` (request id `order_blocked`); a BUY of 10 ACME is accepted with an order id (`order_ok`); `list_my_orders` then contains it, read from Cosmos DB as the user. Stamps ABW-002 and ABW-006. | 5 | Adds one demo order record; nothing removes it (Findings F9-15) | `demo/prove.py:659-682#restricted_list` |
| P07, gateway | The external vendor server. A quote with the user's token succeeds; a call with no token is refused 401 at the gateway; a call straight to the vendor app without the vendor key is refused 401 (the check tests the status; the label names `invalid_vendor_key`); a guessed `x-vendor-key` is refused 401. | 4 | None | `demo/prove.py:736-752#invalid_vendor_key` |
| P02, gateway and MCP servers | Least privilege. As Priya: research lists at least two tools and `search_research` succeeds, a wall `get_deal_document` for `FALCON-001` is refused 403 `missing_role`, `place_order` on the actions server is refused 403 `missing_role`, and a vendor quote succeeds. As Ian: wall, actions and research `tools/list` all return an empty list, a wall call is refused 403 `missing_role`, and a vendor list is refused 403 `missing_role`. | 10 | Flips the operator's roles; `become(BASELINE)` in a `finally` block puts them back | `demo/prove.py:607-632#missing_role` |

P01 is the proof whose check count follows the resources found in the tenant: it adds one check for each resource found, 17 checks in the shipped run, so the total changes when a resource is added or removed. P13's count follows the recorded traffic stamps, and P16's depends on whether the denial appears (Findings F9-7, F9-11, F9-13).

**Agent group (20 checks).**

| Proof and layer | What it asserts | Checks | State it changes | Code |
|---|---|---|---|---|
| P06, network and Foundry agent | The private MCP server. A public DNS lookup (through dns.google) returns no internet-routable address for it; the laptop's original resolver cannot resolve it; the VNet-injected agent `abw-wall-desk` reads `get_firm_positions` and `get_credit_limit` through it. | 4 | None | `demo/prove.py:706-733#public_dns` |
| P05, Foundry agent | The human approval gate. A run that is refused approval asks for it for `place_order` and never executes the call; a run that is approved executes it. | 4 | When approved, adds one demo order record (Findings F9-15) | `demo/prove.py:685-704#ORDER_PROMPT` |
| P08, gateway and Foundry agent | The legacy path. The shared subscription key, read through Azure Resource Manager, returns `ORION-001` with no user token (request id `legacy_leak`); the governed wall DENIES the same document; the legacy agent `abw-poc-legacy` summarises Orion; `abw-wall-desk` refuses and leaks nothing. Stamps ABW-003. | 4 | None | `demo/prove.py:754-779#legacy_leak` |
| P09, wall and Foundry guardrail | Indirect prompt injection. The vendor feed carries an injected notice. Replaying the Orion read and a BUY of 5000 ZYNX that the notice asks for are each DENIED (`injected_read`, `injected_order`). With no guardrail, the poisoned result reaches the model and nothing executes or leaks. With the guardrail, the shielded red-team agent is tried up to 40 times until a run is stopped; a guardrail that never fires fails the proof; when it fires, no further `get_deal_document` or `place_order` follows; across all attempts nothing executes or leaks. Stamps ABW-008 only when the guardrail fires. | 8 | None in the tenant; it deletes the local run files of the middle shielded attempts and keeps the first and last | `demo/prove.py:787-792#GUARD_TRIES`, `demo/prove.py:838-862#stopped_runs` |

The guardrail is a preview control that fired on a minority of identical requests in the measurements the code comment records, from 1 of 9 up to 5 of 8 (`demo/prove.py:787-792#GUARD_TRIES`). The comment's own conclusion is that the deterministic control is the wall; the shipped board shows one stop in two attempts (`demo/evidence-scrubbed/SCOREBOARD.md:35-36#attempts`; Findings F9-6).

**Ops group (20 checks).**

| Proof and layer | What it asserts | Checks | State it changes | Code |
|---|---|---|---|---|
| P14, gateway | Abuse control. One operator token fires 400 calls at the research gateway from 48 workers. At least 60 are served and at least 20 are answered 429; the 429 carries a retry-after; the budget refills within 120 seconds. Stamps ABW-009. | 4 | None | `demo/prove.py:870-903#ThreadPoolExecutor` |
| P15, gateway | Stolen-token defence. The Azure CLI app is allowed at baseline; `scripts/client-allowlist.ps1 -Block azcli` removes it; within 180 seconds the gateway answers 403 `client_not_allowed`; the proof records how many seconds that took; after `-Reset` the call is served again. Stamps ABW-004. | 4 | Removes the Azure CLI app from the allow-list; reset in `finally` | `demo/prove.py:905-931#client_not_allowed` |
| P12, gateway | The kill switch. `scripts/kill-switch.ps1` revokes the operator; within 180 seconds the research API answers 403 `revoked`; the wall, actions and vendor APIs are then called once each and also answer 403 `revoked`; after `-Restore` the call is served again and `-Show` reports that nobody is revoked. Stamps ABW-005. | 8 | Puts the operator on the deny list; restored in `finally` | `demo/prove.py:932-961#revoked` |
| P16, data plane | Entitlement drift. `FALCON-001` is readable; the operator is removed from the Falcon wall group; within `--drift-timeout` seconds the read is DENIED `storage_rbac_denied` while the role claim in the token has not changed; the denial's request id is kept as `drift_denied`. Stamps ABW-007. | 4 | Removes the operator from the Falcon wall group; restored in `finally`, and the read works again | `demo/prove.py:962-992#storage_rbac_denied` |

P14 uses one token (Findings F9-12), and P12 asserts four gateway APIs only (`demo/prove.py:74-74#ROLE_APIS`, `demo/prove.py:946-949#revoked`; Findings F9-10).

**Policy group (3 checks).**

| Proof and layer | What it asserts | Checks | State it changes | Code |
|---|---|---|---|---|
| P11, Azure Policy | Policy as code. `demo/try-violations.py` attempts to break the platform rules and the proof requires every attempt to end as expected. It records which attempts were blocked and which were corrected (an organisation-level Modify policy rewrote three to a safe value in the shipped run), then reads compliance from Resource Graph for the `abw-agent-platform-controls` assignment and records the non-compliant references as a fact labelled legacy path, by design; no check asserts which item it is. | 3 | Makes the attempts; what they leave behind is in that script, not covered here | `demo/prove.py:993-1021#try-violations.py` |

**Verification group (19 checks).**

| Proof and layer | What it asserts | Checks | State it changes | Code |
|---|---|---|---|---|
| P10, observability | One request id answers the auditor. It needs the ids that P03 recorded, queries `AbwIdentityChain` for each over the last 7 days (24 * 7 hours), and polls every 30 seconds for up to `--timeout` minutes until the allowed chain has steps 2, 3 and 4 and the denied chain has steps 2 and 3. It checks that the allowed chain spans gateway, MCP server and Storage; that the operator identity appears in the MCP-server row or the Storage row (one combined check); that Storage authenticated with OAuth; that the MCP row shows `obo`; and that the denied chain has rows, has no Storage step and carries `project_not_in_token_roles` in its detail. | 7 | None | `demo/prove.py:1024-1051#AbwIdentityChain` |
| P17, observability | The observability pack runs. It runs three `check` commands, for the KQL function pack, the nine Sentinel rule queries and the workbook queries, and passes when every query runs without an error. It does not assert deployment: when a workspace function does not resolve, the scripts fall back to local copies of the functions, and no check needs a row, so a probe that returns nothing still passes (Findings F9-5). | 3 | None | `demo/prove.py:1054-1061#build_rules`, `observability/kql/pack.py:134-150#_run` |
| P13, Sentinel | Detection. From the stamps of the earlier proofs, for each rule that has recorded traffic it waits, polling every 45 seconds, until a `SecurityAlert` and a `SecurityIncident` exist whose event time is at or after the attacking proof's start. A rule with no recorded traffic is noted and never failed; with no traffic at all the proof fails. | 9 | None | `demo/prove.py:1065-1123#SecurityAlert` |

P13 judges event time, not alert time, and only the rules that have traffic (Findings F9-11).

**Detections the proofs stamp.** Each proof that expects Sentinel to react calls `ctx.traffic` with a rule id; P13 later checks the nine rules below.

| Rule | Name and severity | Stamped by | Code (rule, stamp) |
|---|---|---|---|
| ABW-001 | Information-barrier violation attempt (Wall MCP); High | P03 | `observability/sentinel/rules.json:4-5#ABW-001`, `demo/prove.py:651-651#ABW-001` |
| ABW-002 | Order blocked: restricted-list instrument; High | P04 | `observability/sentinel/rules.json:39-40#ABW-002`, `demo/prove.py:672-672#ABW-002` |
| ABW-003 | Tool call on the legacy shared-key path (no user identity); Medium | P08 | `observability/sentinel/rules.json:73-74#ABW-003`, `demo/prove.py:769-769#ABW-003` |
| ABW-004 | Gateway rejected a token from an unapproved client application; High | P15 | `observability/sentinel/rules.json:103-104#ABW-004`, `demo/prove.py:922-922#ABW-004` |
| ABW-005 | Revoked principal still calling MCP APIs; High | P12 | `observability/sentinel/rules.json:141-142#ABW-005`, `demo/prove.py:950-950#ABW-005` |
| ABW-006 | Repeated denials for one identity across defence layers; Medium | P04 | `observability/sentinel/rules.json:169-170#ABW-006`, `demo/prove.py:679-679#ABW-006` |
| ABW-007 | Entitlement drift: gateway and MCP allowed, storage RBAC denied the user; High | P16 | `observability/sentinel/rules.json:199-200#ABW-007`, `demo/prove.py:983-983#ABW-007` |
| ABW-008 | Foundry guardrail stopped an agent run (prompt-injection indicator); High | P09, only when it fires | `observability/sentinel/rules.json:229-230#ABW-008`, `demo/prove.py:844-844#ABW-008` |
| ABW-009 | Burst of throttled MCP calls from one identity; Low | P14 | `observability/sentinel/rules.json:259-260#ABW-009`, `demo/prove.py:897-897#ABW-009` |

ABW-006 needs three or more refusals for the same principal within 30 minutes, from any layer, and runs every five minutes (`observability/sentinel/abw-006-repeated-denials.kql:5-15#AbwDenials`). P04 stamps it after a single blocked order, so in a full run the rule depends on the two Orion refusals that P03 made just before; later refusals in the same run can also satisfy the P13 check (Findings F9-16).

#### 9.9.3 Which beats the proofs cover

The console defines the acts and beats; the proofs were written against the platform, not against the console. The catalog's `prove` field lists the architecture nodes a beat lights up, not proof ids (`console/catalog.py:269-269#prove`), so the console cannot say which proof backs a beat and this table is the only such map. Beats are named as in the catalog, with the section of this document that describes them and the catalog line range.

Diagram: docs/diagrams/08-scenarios-acts-1-7.excalidraw

The kind of coverage is one of four. **Asserted**: a proof makes the same call as the beat and checks the outcome. **Related**: a proof asserts the same control or a neighbouring one through another call, through mirrored roles, or only checks that the supporting queries run. **Replay**: the beat replays evidence that a proof produced. **None**: no proof touches the beat. A proof that covers only an alternative run of a beat makes it Related, not Asserted. 9.1.9 lists only the nearest proofs for Act 6; this table lists the nearest proofs for each beat, and its Proof column reads None only when the Kind is None.

| Beat | Section | Proof | Kind | What is and is not asserted |
|---|---|---|---|---|
| 1.1 The PoC everyone builds (`console/catalog.py:253-270`) | 9.2.2 | P08 | Asserted | The shared key with no token returns `ORION-001`, and the legacy agent summarises it. ABW-003. |
| 1.2 The governed agent, same question (`console/catalog.py:272-282`) | 9.2.3 | P02, P03, P08 | Asserted | P08 runs the same agent with the same Orion prompt and asserts that it refuses and leaks nothing; P03 asserts the wall denies Orion and P02 the no-role case. The agent's crossings lookup is not checked. A model's refusal is not the control; the denial is. A rule (ABW-001) fires only if the model tries an Orion tool. |
| 1.3 Same person, the deal they ARE cleared for (`console/catalog.py:284-301`) | 9.2.4 | P03, P16 | Related | The raw `FALCON-001` read (the quick alternative) is asserted by P03 and, before the drift, by P16; the agent run that is the headline is not (Findings F9-4). |
| 1.4 Take the model out of the loop (`console/catalog.py:303-313`) | 9.2.5 | P03, P08 | Asserted | The direct call to the wall is denied (ABW-001, High); P08 also shows the same document readable through the legacy path (beat 1.1, ABW-003). |
| 2.1 Try to break the platform rules (`console/catalog.py:323-334`) | 9.3.2 | P11 | Asserted | The same attempts script; five refused, three rewritten safe and one compliant control allowed in the shipped run. |
| 2.2 Evidence that no key is in use (`console/catalog.py:336-354`) | 9.3.3 | P01 | Asserted | Seven days of the Storage request log and the per-resource rules. |
| 2.3 Where the keys went (`console/catalog.py:356-366`) | 9.3.4 | P01, P11 | Related | Live configuration and the policy initiative are asserted through their own checks; no Sentinel rule watches key use. |
| 3.1 Internal data through the private MCP (`console/catalog.py:376-386`) | 9.4.2 | P06 | Asserted | `get_firm_positions` and `get_credit_limit` succeed for `abw-wall-desk` over the private server. |
| 3.2 Prove the server is private (`console/catalog.py:388-398`) | section 9.4 | P06 | Asserted | No internet-routable address in public DNS; the laptop cannot resolve it. |
| 3.3 The vendor key never leaves the gateway (`console/catalog.py:400-410`) | section 9.4 | P07 | Asserted | A token is required, a direct call without the key is 401 (status only), a guessed key is 401. |
| 4.1 Runaway loop -> rate limit (`console/catalog.py:421-431`) | section 9.5 | P14 | Asserted | At least 60 served, at least 20 refused with 429 and a retry-after, refill within 120 seconds. ABW-009 (Low). |
| 4.2 A human in the loop (`console/catalog.py:433-450`) | section 9.5 | P05, P04 | Asserted | P05: approval is requested, a refusal never executes, a yes does. P04 asserts the restricted-list refusal on a direct call. |
| 4.3 A poisoned tool result (indirect prompt injection) (`console/catalog.py:452-469`) | section 9.5 | P09 | Asserted | The replayed Orion read and the BUY of 5000 ZYNX are denied. The beat allows up to six guardrail attempts (`console/catalog.py:460-462#tries`), the harness forty (`demo/prove.py:790-790#GUARD_TRIES`). ABW-008 only when it fires. |
| 4.4 Stolen token from the wrong application (`console/catalog.py:471-481`) | section 9.5 | P15 | Asserted | 403 `client_not_allowed` within 180 seconds. ABW-004 (High). |
| 4.5 The SOC kill switch (`console/catalog.py:483-493`) | section 9.5 | P12 | Asserted | 403 `revoked` on research, wall, actions and vendor. The agent's own behaviour and the private server are not asserted (Findings F9-10). ABW-005 (High). |
| 5.1 One request id, four hops - the Orion denial (`console/catalog.py:504-514`) | section 9.6 | P10, P13 | Asserted | P10: gateway and MCP rows, no Storage row, `project_not_in_token_roles`; P13: the ABW-001 alert and incident. |
| 5.2 One request id, four hops - an allowed read (`console/catalog.py:516-526`) | section 9.6 | P10 | Asserted | Gateway, MCP server and Storage rows; the operator identity in the MCP-server or Storage row (one combined check); OAuth at Storage. |
| 5.3 How people are using agents (`console/catalog.py:528-538`) | section 9.6 | P17 | Related | P17 asserts that the pack's queries run; the numbers the beat shows are not asserted (Findings F9-5). |
| 5.4 What was refused, and by which wall (`console/catalog.py:540-550`) | section 9.6 | P13, P17 | Related | P13 asserts alerts from rules built on `AbwDenials`, the function behind this beat, and P17 that the functions run; the per-wall counts the beat shows are not asserted. |
| 5.5 The agent's own tool calls (`console/catalog.py:552-562`) | section 9.6 | P17 | Related | As 5.3. |
| 5.6 How long does one token keep serving calls? (`console/catalog.py:564-574`) | section 9.6 | P13, P17 | Related | P13 asserts alerts from rules built on `AbwMcpAudit`, the function behind this beat, and P17 that the functions run; the token-lifetime numbers the beat shows are not asserted. |
| Governance tour (`console/catalog.py:576-593`) | section 9.6 | P13, P11, P17 | Related | P13 asserts the alerts and incidents behind the Sentinel card, not the card itself or its count of enabled rules, and P11 backs the Policy card (the attempts are asserted; which row is non-compliant is recorded, not asserted); P17 runs the queries of the KQL pack, the workbook and the nine Sentinel rules (`demo/prove.py:1054-1061#build_rules`), not the Monitor card's own probe queries. The other cards are not asserted. |
| 6.1 Sign-in fails: a wrong password (`console/catalog.py:604-628#SigninLogs`) | section 9.7 | P07 | Related | P07 asserts the no-token alternative (401 at the gateway); the Entra password failure that is the headline is not asserted, and Sentinel does not receive the tenant's sign-in logs (Findings F9-2). |
| 6.2 Keys instead of Entra (`console/catalog.py:630-646#keys_not_entra`) | section 9.7 | P07, P01, P11 | Related | P07 asserts the no-token 401, P01 that account keys are off, P11 that policy refuses switching them on. No proof sends the shared key to the governed Wall API. |
| 6.3 Signed in, but no access to this server (`console/catalog.py:648-667#no_mcp_access`) | section 9.7 | P02 | Related | P02 asserts the same 403 `missing_role` for Priya and Ian with mirrored roles. The beat uses a persona sign-in and its own text says it had not been run with Priya signed in (`console/catalog.py:648-667#dry-run`; Findings F9-1). |
| 6.4 Right door, wrong deal (`console/catalog.py:669-679`) | section 9.7 | P03, P13 | Asserted | P03 asserts the same Orion denial with `project_not_in_token_roles` as the operator; P13 the ABW-001 alert. Unless a person is chosen in the Acting-as switcher the beat makes that call as the operator; a chosen person's own sign-in is not exercised by any proof. |
| 6.5 The last layer says no: Storage RBAC (`console/catalog.py:681-691`) | section 9.7 | P16 | Replay | The beat replays the newest `storage_rbac_denied` row in the MCP audit (last 14 days), the kind P16 produces; `python demo\prove.py --only P16` makes a fresh one. |
| 6.6 Attack the model: a jailbreak (`console/catalog.py:693-712#jailbreak`) | section 9.7 | P09 | Related | P09 asserts the poisoned-feed variation of the beat (the same attack as beat 4.3); the hostile user prompt that is the headline is not asserted (Findings F9-3). |
| 6.7 The same request, allowed: a cleared user (`console/catalog.py:714-724`) | section 9.7 | P03, P10 | Asserted | P03 asserts the Falcon read succeeds and P10 the allowed chain. Unless a person is chosen in the Acting-as switcher the beat makes that call as the operator; a chosen person's own sign-in is not exercised by any proof. |
| 6.8 The same request through the agent: allowed (`console/catalog.py:726-736#agent`) | section 9.7 | P06, P08 | Related | Other agent paths are asserted (the private server, the refusal of Orion); the agent's allowed wall read is not (Findings F9-4). |
| 7.1 to 7.4, the four headline beats of Act 7 (`console/catalog.py:756-756#frontdoor`, `console/catalog.py:789-789#matrix`, `console/catalog.py:817-817#finops`, `console/catalog.py:845-845#quota`) | 9.8.3, 9.8.4, 9.8.13 and 9.8.14 | None | None | Act 7 was added after the final proof run and is not one of the 18 proofs (`DESIGN.md:246-246#Act`, `docs/RUNBOOK.md:155-155#back-pocket`; Findings F9-1). The 21 role-tab beats of the act (ids 7.2-pri-ok to 7.2-adm-ori) are not separate rows here: 9.8.15 lists all 25 beats with the nearest proof for each, graded Same call, Related or None, and none of those grades says that the beat as the console runs it was proved. |

Counting the four headline Act 7 beats (7.1 to 7.4) and the governance tour as one entry each, and leaving out the 21 role-tab beats that 9.8.15 lists, the table has 34 entries in 31 rows (7.1 to 7.4 share one row): 17 are asserted by a proof, 12 are related, 1 is a replay and 4 have no proof. Acts 1 to 4 and the chain beats of Act 5 carry most of the assertions, and the direct-call beats 6.4 and 6.7 borrow P03 and P10; Act 6 has no dedicated proof, and Act 7 has none of the 18.

#### 9.9.4 What the proofs do not prove

| Not covered | Why it matters | Where it is exercised instead |
|---|---|---|
| Act 7 as a whole: the agent's front door, each person's view, the cost board, the runaway-agent budget | It is shown live but nothing re-proves it, and Wes, Tara and Carla have not signed in (Findings F9-1) | The Demo Console, by hand (`DESIGN.md:241-246#Carla`) |
| An Entra sign-in failure (beat 6.1) | The first layer of the path has neither a proof nor a detection (Findings F9-2) | Entra's own sign-in log read through Graph, 10 to 20 minutes later (`console/catalog.py:604-628#SigninLogs`) |
| A hostile user prompt (beat 6.6) | The catalog says the user-prompt guardrail has stopped this prompt every time in this tenant, but a classifier is not a guarantee (`console/catalog.py:702-703#classifier`); the preview control is the tool-output shield, which P09 covers (Findings F9-3) | The beat itself; re-run it before the talk for a fresh guardrail row |
| The agent's allowed read through the wall (beat 6.8) | The allowed half of the agent contrast is shown, not asserted (Findings F9-4) | The beat itself |
| What the Act 5 views display (beats 5.3 to 5.6) | P17 checks that the functions run and P13 asserts alerts built on `AbwDenials` and `AbwMcpAudit` (behind 5.4 and 5.6), but no proof checks the numbers the views show (Findings F9-5) | The beats, read against the logs |
| That the guardrail fires every time | It fires on only some runs; P09 passes on the first stop within up to 40 attempts and fails only if all of them miss, so reliability is not measured (Findings F9-6) | The wall, which is the deterministic control |
| Real persona sign-in, including one-time MFA enrolment | The operator mirrors roles instead (`demo/prove.py:303-303#persona`; Findings F9-8); the sign-in code lives in `demo/abw_tokens.py`, `demo/mcpclient.py` and `demo/burst.py`, and no proof calls it | The Acting-as switcher, once each person has signed in |
| The kill switch on the agent and the private server | P12 asserts four gateway APIs (`demo/prove.py:74-74#ROLE_APIS`; Findings F9-10) | Beat 4.5 and the design note in 9.4 |
| Independent rate-limit budgets per user | P14 uses one token (Findings F9-12) | Not exercised; the policy keys the counter on the user's `oid` (configuration, `infra/apim/policies/mcp-jwt.policy.xml:81-81#rate-limit-by-key`), and `demo/burst.py --persona` is a manual way to try it (`demo/burst.py:35-38#persona_token`) |
| Entitlement drift other than the Falcon group | P16 changes one group (`demo/prove.py:962-992#storage_rbac_denied`) | Not exercised elsewhere |
| How fast Sentinel alerts | P13 waits up to `--timeout` minutes and judges event time (Findings F9-11) | Not measured; the rules run every five minutes over a 30-minute look-back (one hour for ABW-007), which is configuration (`observability/sentinel/abw-006-repeated-denials.kql:5-6#PT5M`, `observability/sentinel/abw-007-entitlement-drift.kql:5-6#PT1H`) |
| That one board is one run | The scoreboard keeps the latest result of each proof (Findings F9-9) | The evidence files, one per run |

**Key takeaways**

- **The catalog is the script.** Acts, beats and the refusal-explainer cards come from one file, `console/catalog.py`, so every beat in 9.2 to 9.8 can be found by its line range (`console/catalog.py:46-108#REASONS`, `console/catalog.py:249-249#Act`).
- **Acts 1 to 4 and the chain beats of Act 5 mostly stand on proofs.** 17 of the 34 entries in 9.9.3 are asserted, and a proof cannot pass on nothing: it needs at least one check and every check true, and a crash is a failed check (`demo/prove.py:1146-1150#bool(ctx.checks)`).
- **Act 6 has no dedicated proof and Act 7 has none of the 18.** Act 6 runs `e2e` scenarios; the nearest proofs assert the same refusals through mirrored roles, the direct-call beats 6.4 and 6.7 borrow the operator's calls in P03 and P10, and one beat (6.5) replays a proof's evidence (`console/catalog.py:681-691#data_plane`).
- **One request id joins the chain.** P10 reads each request as rows of one id: the allowed read across the gateway, the MCP server and Storage, the denied one across the gateway and the MCP server (`demo/prove.py:1024-1051#AbwIdentityChain`).
- **The proofs act as the operator and put the controls back.** They mirror a persona's roles instead of signing in; the proofs that flip a control put it back in a `finally` block or `--restore` does, but the demo orders that P04 and P05 add are never removed (`demo/prove.py:303-303#persona`, `demo/prove.py:339-355#restore_all`; Findings F9-15).
- **Say what is designed, not run.** Four entries in 9.9.3 have no proof and 12 more are only related, and Wes, Tara and Carla have not signed in; the console and the talk should call the unproved results designed and name the nearest proof for the related ones (`DESIGN.md:241-246#Carla`).


### 9.10 Findings

The 235 findings raised while writing section 9 (documentation mismatches, defects and undocumented decisions) are collected in [Appendix B.6](appendix-b-findings-register.md#b6-raised-while-writing-section-9). Where the text above says "Findings" or quotes a finding number, it means that list.

---

[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [9. Scenarios, part 6: Act 7, the admin tab, cost and evidence (9.8.10 to 9.8.15)](09f-scenarios-act-7b.md) | Next: [10. Data flow and correlation](10-data-flow-and-correlation.md)
