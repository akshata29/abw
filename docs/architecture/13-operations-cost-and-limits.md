[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [12. Demo Console architecture](12-demo-console.md) | Next: [Appendix A. Repository file index](appendix-a-file-index.md)

## 13. Operations, cost, limits and known gaps

**What this section proves.** What the platform costs to run (about USD 37 a day while it is on, `docs/COST.md:3-3#Bottom`) and why; how much capacity it has; where the design stops scaling; what happens when a second deployment shares a tenant or a subscription; how much of the keyless claim holds and which secrets remain; how to recover from the failures the runbook records; and a numbered list of defects and documentation mismatches found while writing this reference. Each limit is cited to the repo or labelled Inferred.

Provenance labels used in this section: **Implemented** (code), **Configured** (Bicep, policy XML, JSON), **Designed** (the repo's own docs), **Platform behaviour** (Microsoft Learn; the URL is given as plain text) and **Inferred** (derived by reading, not tested). Anything the repo does not contain is marked "not in this repo".

### 13.1 Cost model

**What this section proves.** The platform costs about USD 37 a day while it is switched on, nine of the twelve cost lines are fixed whatever the traffic, and the only automatic brake on spend is the per-user token and rate limit at the agent front door. The cost budget alerts and never stops anything.

**Basis (Designed).** The cost document prices each resource from the Azure Retail Prices API (pulled 2026-10-13) at pay-as-you-go list price for 730 hours a month, with no discount. Cost Management held no usage rows when it was written, so the figure is a bottom-up estimate and not an invoice. The resource counts it quotes are 92 when written, 97 for the then-current deployment, 103 with the optional jump box and a later 104 that includes a Defender for Cloud extension on the jump box VM; it was not re-priced for the difference, apart from the jump-box paragraph (`docs/COST.md:6-7#bottom-up`). The headline is about USD 1,100 a month, about USD 37 a day, with API Management about 63 % of it (`docs/COST.md:3-3#Bottom`). A three-week window is about USD 780, and after teardown the burn is zero (`docs/COST.md:4-4#teardown`).

| # | Cost driver (as stated) | USD a month | Behaviour | Source (Designed) |
|---|---|---|---|---|
| 1 | API Management Standard v2 (hourly rate stated as USD 0.9589) | 700 | Fixed | `docs/COST.md:13-13#Management` |
| 2 | AI Search Basic, two services (deal data, and the Agent Service state store) | 147 | Fixed | `docs/COST.md:14-14#Search` |
| 3 | Private endpoints, ten | 73 | Fixed | `docs/COST.md:15-15#endpoints` |
| 4 | Container Apps, six at 0.5 vCPU and 1 GiB, minimum 1 replica, billed at idle rates | 71 | Fixed | `docs/COST.md:16-16#Container` |
| 5 | Cosmos DB agent store: five containers, autoscale to 1000 RU/s, a floor of 100 RU/s each | 44 | Fixed | `docs/COST.md:17-17#autoscale` |
| 6 | NAT gateway and its public IP | 37 | Fixed | `docs/COST.md:18-18#NAT` |
| 7 | Container Registry Standard | 20 | Fixed | `docs/COST.md:19-19#Registry` |
| 8 | Private DNS: 15 zones and 15 links | 9 | Fixed | `docs/COST.md:20-20#DNS` |
| 9 | Log alert rules, three | 5 | Fixed | `docs/COST.md:21-21#alert` |
| 10 | Log Analytics and Sentinel ingestion | 2 to 5 | Usage | `docs/COST.md:22-22#Sentinel` |
| 11 | Serverless Cosmos, two storage accounts, Key Vault, API Center (Free tier), App Insights | about 3 | Usage | `docs/COST.md:23-23#serverless` |
| 12 | Model tokens (`gpt-5.4-mini`, GlobalStandard) | 1 to 5 | Usage | `docs/COST.md:24-24#GlobalStandard` |
| | Total | about 1,110 | | `docs/COST.md:25-25#Total` |

Rows 1 to 9 are fixed and rows 10 to 12 move with usage (`docs/COST.md:38-38#fixed`). By share of the total: API Management 63 % (USD 700), Search 13 % (147), private endpoints 7 % (73), Container Apps 6 % (71), Cosmos 4 % (44), NAT gateway, public IP and registry 5 % (57), everything else 2 % (23) (`docs/COST.md:54-60#APIM`).

**Why this shape (Inferred from the table).** The bill is almost entirely the price of being switched on: private networking, a gateway tier chosen for network isolation, and two Search services. Traffic barely moves it, so the number of days the platform exists is the real lever.

**What is not in the total.**

| Item | What the cost document says | Source (Designed) |
|---|---|---|
| Jump box VM | Windows at about USD 0.183 an hour, about USD 4.4 a day, about USD 134 a month if left on; while deallocated only the OS disk bills, about USD 0.3 a day; Bastion Developer is free | `docs/COST.md:30-30#jump` |
| Defender for Cloud plans | Not estimated. The scripts enable no paid plan (the Defender and Sentinel extras script only reads them), but a subscription whose plans are already Standard bills the demo's resources, Cost Management had already shown a Defender line on the group, and teardown does not change the plan setting | `docs/COST.md:32-35#Defender` |
| Items that do not bill | Entra ID (the Conditional Access policy is report-only and relies on the tenant's existing P1 or P2 licence), Purview (licensing only), Azure Policy, workbooks, Sentinel rules (the charge is per-GB ingestion, row 10) and the Foundry account itself (the S0 tier has no hourly fee; only tokens bill) | `docs/COST.md:27-28#billed` |

**Levers.**

| Lever | Saving | Cost of using it | Source |
|---|---|---|---|
| Tear down the day after the talk | about USD 37 a day | A rebuild is a long afternoon (API Management alone takes 30 minutes or more); keep the repo and the local secrets folder if you want the same personas | **Designed**: `docs/COST.md:44-44#teardown` |
| Deploy later | USD 37 for each day not running; start about 10 days before the talk | Less rehearsal time | **Designed**: `docs/COST.md:45-45#Deploy` |
| Minimum replicas 0 on the six Container Apps between rehearsals | about USD 71 a month | The first call after idle cold-starts a replica (seconds); set it back to 1 a day before the talk | **Designed**: `docs/COST.md:46-46#replicas`; **Platform behaviour**: https://learn.microsoft.com/azure/container-apps/scale-app (a zero-replica app has no usage charge; an app with a minimum of 1 or more keeps an instance running) |
| Stop the jump box | about USD 4 a day (about USD 4.4 running against about USD 0.3 for the OS disk while deallocated) | `Start-JumpBox.bat` restarts it in about a minute; it also deallocates itself at 03:00 Central | **Designed**: `docs/COST.md:47-47#Stop`, `docs/RUNBOOK.md:307-307#03:00` |
| A smaller API Management tier | Not available: the cost document states that Basic v2 has no private-endpoint inbound and cannot reach VNet-isolated backends, and that Standard v2 is the cheapest tier that does both | None | **Designed**: `docs/COST.md:48-48#smaller`; **Platform behaviour**: https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview#networking-options |
| Delete Search and the private endpoints | about USD 220 a month | They belong to the platform stage and the Agent Service capability host depends on them, so a full teardown is the supported route | **Designed**: `docs/COST.md:49-49#Delete` |

**Inferred reconciliation.** The template default is already a minimum of 1 replica (`infra/modules/mcp-app.bicep:19-19#minReplicas`), so the slow first call after idle that the runbook attributes to a Container Apps cold start (`docs/RUNBOOK.md:293-293#cold`) can be a scale-from-zero event only after the minimum-replica lever above has been used to set it to 0; with the default it may instead be gateway, Foundry or token warm-up. The repo does not isolate the cause.

**Budget and brakes.** Two controls exist and they do different jobs.

| | Cost budget | Token and rate brake |
|---|---|---|
| Scope | The demo resource group; it is deleted with the group | Each user object id, at the agent front door |
| Thresholds | USD 1,200 a month; notices at 50 %, 80 % and 100 % of actual cost and at 100 % of forecast | 250,000 tokens an hour and 60 calls a minute (demo values, not a sizing) |
| Action | Mails the resource group Owners, plus an optional extra address | Refuses the call: 403 on the token quota, 429 on the rate limit |
| Stops spend | No. Nothing is stopped or scaled down | Only the model-token part of spend, and only per user |
| Timing | Cost data lags and the budget is evaluated every 24 hours (platform behaviour, below) | Tokens are counted after the response (`estimate-prompt-tokens` is false), so one call can overshoot |
| Source | **Configured**: `infra/09-budget.bicep:14-14#monthlyBudgetUsd`, `infra/09-budget.bicep:33-70#contactRoles`, `infra/09-budget.bicep:3-5#alert` | **Configured**: `infra/08-agent-frontdoor.bicep:18-21#tokenQuotaPerHour`, `infra/apim/policies/agent-frontdoor.policy.xml:95-96#llm-token-limit` |

Platform behaviour for the budget: notifications fire at the thresholds, resources are not affected and consumption is not stopped, and cost data is typically available within 8 to 24 hours and budgets are evaluated against it every 24 hours (https://learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets). Platform behaviour for the token limit: with `estimate-prompt-tokens` set to false the policy counts the usage the model reports after the response, a token-rate breach returns 429 and a quota breach returns 403 (https://learn.microsoft.com/azure/api-management/llm-token-limit-policy). The runbook records both codes (`docs/RUNBOOK.md:316-316#token_quota_exceeded`).

**Why.** The budget amount is the list-price run-rate of leaving the platform on around the clock, so the 80 % notice means the demo was forgotten, not that traffic spiked (`infra/09-budget.bicep:12-12#forgot`). The real brake on an agent that loops is the per-user token budget; the cost budget only tells you afterwards (`docs/COST.md:74-74#brake`, `docs/COST.md:79-80#afterwards`).

**Inferred headroom.** At about USD 37 a day a 31-day month is about USD 1,147, which is under the USD 1,200 budget. The 100 % actual notice therefore fires only if usage or unpriced lines (Defender plans, for example) add about USD 53 or more. The realistic notices are 50 % (USD 600, about day 17) and 80 % (USD 960, about day 26). The time grain is monthly (`infra/09-budget.bicep:29-29#timeGrain`), so a deployment that crosses a month end is measured in two parts.

**Tags and the reminder.** Resources carry `workload`, `env`, `owner`, `purpose`, `data` and `delete-after` (45 days after deployment) (`scripts/common.ps1:54-54#delete-after`); the orchestrator writes its own tag set into the config (`scripts/Deploy-AgentWall.ps1:820-820#delete-after`). The runbook calls the tag a reminder (`docs/RUNBOOK.md:325-325#reminder`), and nothing in the repo reads it to delete anything (Inferred from a search of the scripts and Bicep). Cost views can filter on the tags (`docs/COST.md:66-66#Tags`).

**How to see the real number (Designed).**

| Where | What it shows | Source |
|---|---|---|
| Cost Management, cost analysis on the resource group, grouped by service | Actual spend; usage posts up to a day late | `docs/COST.md:65-65#Cost` |
| Ingestion query run through `demo/kql.py` | Billable Log Analytics ingestion over a chosen window | `docs/COST.md:67-67#kql` |
| Console Act 7, beat 7.3 (FinOps board); the workbook tab "Cost & tokens"; `AbwTokenUsage(24h)` | Spend by service and tokens by user and agent | `docs/COST.md:68-68#FinOps` |

On 2026-10-23 the board showed USD 38.84 month to date, with API Management USD 23.97 (62 %) and 48,008 tokens in 24 hours, all from one user (`docs/COST.md:75-75#board`). The front door added no hourly line: it is one more API on the same API Management instance and the budget object is free (`docs/COST.md:72-72#hourly`).

**Trade-off / limitation.** Nothing in the repo caps spend. A forgotten deployment costs about USD 37 a day until someone acts on a mailed notice, and the notice itself arrives with the cost-data lag. The token quota limits only model tokens, which are the smallest line in the table (row 12). Safety here is human discipline plus an alert.

### 13.2 Capacity and quota

**What this section proves.** Capacity is fixed at demo scale: one API Management unit, at most two replicas per MCP server, one Search partition and replica, and a 100K tokens-per-minute model deployment. The repo records single-operator timings and gateway rate limits, and no throughput or load test, so no capacity claim beyond these numbers is established here.

| Resource | Configured capacity | What the repo shows about headroom | Provenance and source |
|---|---|---|---|
| Model deployment | `gpt-5.4-mini`, version `2026-03-17`, GlobalStandard, capacity 100 (described as 100K tokens per minute) | Quota is per subscription, per region, per model and per deployment type, counted in tokens per minute. The plain deploy script's preflight registers providers and records the operator IP and has no quota check; the orchestrator adds a soft check that only warns | **Configured**: `scripts/deploy.ps1:251-255#modelName`, `docs/SELF-DEPLOY.md:80-80#Model`. **Implemented**: `scripts/deploy.ps1:194-214#preflight`, `scripts/Deploy-AgentWall.ps1:1028-1068#Test-ModelCapacity`, `docs/SELF-DEPLOY.md:85-85#warning`. **Platform behaviour**: https://learn.microsoft.com/azure/foundry-classic/openai/how-to/quota |
| API Management | Standard v2, capacity 1, no autoscale declared | The gateway limits are 120 calls per 60 s per user on each MCP API, and 60 calls a minute plus 250,000 tokens an hour per user at the front door. The burst test sent 400 calls in 3 to 7 seconds and between 124 and 133 were allowed in the runs on record (124 in the shipped proof run, 126 in the runbook's final harness run, 129 and 133 hand-run) and the rest got HTTP 429 (the bucket holds 120 and refills 2 a second). No requests-per-second ceiling for the unit is recorded (Inferred from absence) | **Configured**: `infra/05-apim.bicep:47-50#capacity`, `infra/apim/policies/mcp-jwt.policy.xml:81-81#rate-limit-by-key`, `infra/08-agent-frontdoor.bicep:18-21#tokenQuotaPerHour`. **Designed**: `docs/RUNBOOK.md:338-338#Burst`. **Implemented**: `demo/evidence-scrubbed/SCOREBOARD.md:42-42#429` |
| Container Apps (six) | 0.5 vCPU, 1 GiB, minimum 1 and maximum 2 replicas, Consumption workload profile, a single active revision | Scale is set by minimum and maximum only; the module declares no scale rule, and the repo records no scale-out test. The transport is stateless JSON, so a request does not need replica affinity (Inferred) | **Configured**: `infra/modules/mcp-app.bicep:19-22#minReplicas`, `infra/modules/mcp-app.bicep:36-38#workloadProfileName`, `infra/modules/mcp-app.bicep:85-88#maxReplicas`. **Implemented**: `src/mcp/abw_mcp/app.py:210-215#stateless` |
| AI Search (deal data) | Basic, one partition, one replica, semantic search off | One index serves research notes and wall documents; no query-rate figure is recorded. A second Basic service holds the Agent Service state | **Configured**: `infra/03-platform.bicep:307-313#partitionCount`, `infra/foundry/PATCHES.md:23-23#searchSkuName` |
| AI Search region | The Search service may sit in a different region from the rest | Added because the primary region had no Search capacity on build day | **Configured**: `scripts/deploy.ps1:275-275#searchLocation`; **Designed**: `docs/SELF-DEPLOY.md:81-81#Search` |
| Cosmos DB | Platform account is serverless; the Foundry state account has five autoscale containers with a floor of 100 RU/s each | The floor is a fixed cost, so it appears in the fixed rows of 13.1 | **Configured**: `infra/03-platform.bicep:214-214#EnableServerless`; **Designed**: `docs/COST.md:17-17#autoscale` |
| Jump box VM | Standard_D2as_v7, with a fallback list of Standard_D2s_v7 and Standard_D2ads_v7 | A size can be unavailable to a subscription, so the script tries sizes in order | **Configured**: `infra/07-jumpbox.bicep:58-59#vmSize`; **Implemented**: `scripts/jumpbox.ps1:22-22#VmSize`, `scripts/jumpbox.ps1:64-64#sizeOrder` |

**Inferred arithmetic.** A deployment of 100,000 tokens a minute is 6 million tokens an hour, and the per-user front-door cap is 250,000 tokens an hour, so about 24 users at the cap, spread evenly, would use the whole deployment. The repo does not test this.

**Timings recorded in the repo (Designed; single-operator lab runs).**

| Event | Value | Source |
|---|---|---|
| Full deployment | 122 to 200 minutes (137 to 225 with the console) | `docs/SELF-DEPLOY.md:102-102#Time` |
| API Management create | 35 to 50 minutes | `docs/SELF-DEPLOY.md:4-4#Management` |
| Platform stage | 10 to 15 minutes | `docs/SELF-DEPLOY.md:167-167#platform` |
| Jump box and console steps in the orchestrator plan | 10 to 15 and 15 to 25 minutes | `scripts/Deploy-AgentWall.ps1:434-436#EtaMin` |
| One agent run | 12 to 30 seconds | `docs/RUNBOOK.md:343-343#Agent` |
| First call after idle | 10 to 20 seconds | `docs/RUNBOOK.md:293-293#cold` |
| Full proof run | 18 of 18 proofs; the runbook says 110 of 110 checks in about 29 minutes (109 when the preview guardrail does not fire), while the shipped board shows 109 checks and about 23 minutes (9.9.2) | `docs/RUNBOOK.md:334-334#Proofs` |
| Reset demo, and the baseline reset command | about 1.5 minutes, and 67 to 104 seconds | `docs/RUNBOOK.md:282-282#collide`, `docs/RUNBOOK.md:344-344#restore` |
| Kill switch to first refusal; allow-list flip; group removal to data-plane denial | 45 to 90 s; 45 to 85 s; under a minute | `docs/RUNBOOK.md:335-335#Kill`, `docs/RUNBOOK.md:336-336#Client`, `docs/RUNBOOK.md:337-337#Entitlement` |
| App-role change visible in a token | about 30 s | `docs/RUNBOOK.md:295-295#propagation` |
| Detection: event to Sentinel incident | up to about 8 minutes by the runbook (about 13 for the Storage-sourced rule); the proof playbook allows up to about 15 minutes (`docs/PROOF-PLAYBOOK.md:193#Allow`) and records one dry run that needed 22 (`docs/PROOF-PLAYBOOK.md:501#ABW-001`) | `docs/RUNBOOK.md:345-345#Detection` |

### 13.3 Scale limits and design trade-offs

**What this section proves.** The platform is built for two deals and five personas. The limits that bind are in the operating model (one role per deal, edits in four places, no entitlement store), not in Entra or Azure quotas, and several visibility gaps and demo-tuned defaults are deliberate or undocumented trade-offs a reviewer should know before reusing the pattern.

**A. Identity and entitlement scale.**

| Limit | What the repo shows | Consequence | Provenance and source |
|---|---|---|---|
| One app role per deal | The wall app defines `Wall.Falcon` and `Wall.Orion`; the gateway lists them; the server hard-codes the project names; Storage has one container and one role assignment per project | A new deal is a change in four places (section 5.7) and cannot be done as data | **Implemented/Configured**: `identity/Setup-Entra.ps1:33-35#Wall.Falcon`, `infra/05-apim-apis.bicep:45-45#Wall.Falcon`, `src/mcp/abw_mcp/servers/wall.py:13-16#PROJECT_TITLES`, `infra/03-platform.bicep:628-636#raFalconBlob` |
| No entitlement store (not in this repo) | The only data-driven entitlement is the restricted list in Cosmos, read at call time by the order tool; nothing records requests, approvals, expiry or recertification | Entitlement changes are made by hand in Entra, and nothing compares Entra, the gateway role lists and Azure role assignments | **Implemented**: `src/mcp/abw_mcp/servers/actions.py:58-75#_read_restricted` |
| Entra platform limits | 700 permission definitions per app (disabled roles still count); 1,500 role assignments per user, group or service principal; group-based assignment needs Entra P1 or P2 and does not support nested groups. This repo defines one or two scopes and one or two roles on each API app | Far from binding at demo scale | **Platform behaviour**: https://learn.microsoft.com/entra/identity-platform/howto-add-app-roles-in-apps#app-role-limits, https://learn.microsoft.com/entra/identity/users/directory-service-limits-restrictions, https://learn.microsoft.com/entra/identity/enterprise-apps/assign-user-or-group-access-portal. **Implemented**: `identity/Setup-Entra.ps1:29-45#Apis` |
| Token lifetime, no continuous evaluation | Access tokens live 60 to 90 minutes by default, and the repo builds no continuous access evaluation for its custom APIs (the README says they cannot get it, which this document did not verify). Revocation therefore relies on the gateway deny-list (about 45 to 90 s) and on data-plane group removal (under a minute) | A role removal does not invalidate an issued token by itself; pair it with the kill switch | **Designed**: `README.md:141-141#CAE`, `DESIGN.md:236-236#jti`. **Platform behaviour**: https://learn.microsoft.com/entra/identity-platform/configurable-token-lifetimes, https://learn.microsoft.com/entra/identity/conditional-access/concept-continuous-access-evaluation |
| Foundry holds the user's token | Foundry reuses a user's token until it expires and mints the next one at the first agent call after that (the same `jti` was seen for 39 to 51 minutes or more) | An agent can keep old roles for 60 to 90 minutes after a role change; the runbook says to use real personas rather than a flip account | **Designed**: `DESIGN.md:236-236#jti`, `docs/RUNBOOK.md:296-296#Foundry` |

**B. Coverage and visibility.**

| Limit | What the repo shows | Consequence | Provenance and source |
|---|---|---|---|
| Denial table covers four layers | `AbwDenials` unions the guardrail runs (layer 0), the gateway (1), the MCP server (2) and Storage data-plane refusals (3, status 401 or 403 from the blob log only) | Refusals made by Entra (sign-in, consent, Conditional Access), by Cosmos and by Search never appear in the table, and Sentinel gets no Entra sign-in data | **Implemented**: `observability/kql/AbwDenials.kql:3-3#Storage`, `observability/kql/AbwDenials.kql:67-78#dataplane`. **Designed**: `README.md:148-148#Conditional` |
| Private MCP server outside APIM | The private server is reached on a direct path from the agent subnet, not through the gateway | The APIM kill switch, the APIM client allow-list (a runtime named value) and the gateway metrics do not apply to it; the server still enforces its own deploy-time `azp` allow-list | **Designed**: `DESIGN.md:107-107#private`, `README.md:149-149#kill`. **Configured**: `infra/04-apps.bicep:141-141#serverEnv`. **Implemented**: `src/mcp/abw_mcp/auth.py:151-153#bad_azp` |
| Guardrail is a preview feature | Best effort: the runbook says it stopped the run on 1 of 11 attempts in the final run and on between 1 of 11 and 5 of 8 across runs, while the stored proof run shows 1 stopped in 2 attempts (`demo/evidence-scrubbed/SCOREBOARD.md:36#attempts`); the wall's own refusal is the deterministic part | Treat it as a detection layer, not a control | **Configured**: `infra/06-governance.bicep:72-76#deterministic`. **Designed**: `README.md:140-140#preview`, `docs/RUNBOOK.md:346-346#Prompt-injection` |
| Token quota counted after the response | The front door counts the tokens the model reports after each call | One large call can pass the quota before the next call is refused | **Configured**: `infra/apim/policies/agent-frontdoor.policy.xml:96-96#llm-token-limit`. **Designed**: `README.md:149-149#kill` |
| Observability lag | Log rows arrive 2 to 20 minutes after the event (Entra's sign-in log 10 to 20); Sentinel incidents appear within about 8 minutes by the runbook (about 13 for the Storage-sourced rule), the proof playbook allows up to about 15 (`docs/PROOF-PLAYBOOK.md:193#Allow`) and one dry run needed 22 (`docs/PROOF-PLAYBOOK.md:501#ABW-001`); the Act 6 board lives in console memory and needs a refresh from logs | A live beat cannot show a log-derived result at once | **Designed**: `README.md:148-148#Conditional`, `docs/RUNBOOK.md:345-345#Detection`, `docs/RUNBOOK.md:314-314#Refresh` |
| Observed versus designed | Nine of the eleven Act 6 scenarios ran live, 6.5 replays a real Storage denial and 6.3 was not run on its own board; Act 7 is mostly observed and the poisoned-feed beat was never run; only Priya and Ian had signed in through the console switcher when the README recorded it, so what Wes, Tara and Carla see is the designed result; Conditional Access is report-only | Claims for the unobserved beats rest on design, not on evidence | **Designed**: `README.md:147-149#Acting`, `DESIGN.md:246-246#Act` |

**C. Demo-tuned defaults.**

| Default | What the repo shows | Consequence | Provenance and source |
|---|---|---|---|
| Discovery without a role | For the research, wall and actions APIs, `initialize`, `ping`, `tools/list` and `notifications/*` need only a valid token from an allowed client with the `Tools.Read` scope; each server then filters its own tool list per caller, so a caller with no role sees no tools. The vendor API keeps discovery closed | Layer 2 carries the weight for discovery calls; every `tools/call` still needs a role at the gateway and in the server | **Configured**: `infra/apim/policies/mcp-jwt.policy.xml:42-44#discovery`, `infra/05-apim-apis.bicep:38-38#listOpen`, `infra/05-apim-apis.bicep:49-49#listOpen`, `infra/05-apim-apis.bicep:60-60#listOpen`, `infra/05-apim-apis.bicep:71-71#listOpen`. **Implemented**: `src/mcp/abw_mcp/registry.py:132-140#requirement` |
| Backend TLS validation off | The gateway does not validate the certificate chain or name of the internal servers by default; a config key can turn it on, and the vendor backend always validates. The repo says to flip it after verifying trust but does not say why it starts off | The gateway-to-server hop is private but its certificate is not checked | **Configured**: `infra/05-apim-apis.bicep:21-22#validateInternalTls`, `infra/05-apim-apis.bicep:101-104#validateCertificateChain`, `infra/05-apim-apis.bicep:69-69#validateTls`. **Implemented**: `scripts/deploy.ps1:387-387#validateInternalTls` |
| DNS-rebinding protection off | The MCP HTTP transport is created stateless with JSON responses and with DNS-rebinding protection disabled. The repo gives no reason and records no test of the effect | Not established here | **Implemented**: `src/mcp/abw_mcp/app.py:210-215#enable_dns_rebinding_protection` |
| Audit is best effort | `AUDIT_FAIL_CLOSED` defaults to false and no Bicep or script sets it. By default the append-blob sink queues lines and a write failure is only logged; with fail-closed no background thread starts, every write is synchronous and a failure is raised. Allowed calls emit their audit event with no error handling around it | Under the default, an audit write can be lost without stopping the tool call. With fail-closed the exception leaves the tool-call path (how the transport reports it was not traced) | **Implemented**: `src/mcp/abw_mcp/config.py:150-150#audit_fail_closed`, `src/mcp/abw_mcp/audit.py:72-76#audit_fail_closed`, `src/mcp/abw_mcp/audit.py:88-103#append_audit_failed`, `src/mcp/abw_mcp/audit.py:174-176#emit`, `src/mcp/abw_mcp/registry.py:202-215#emit` |
| Legacy path waived until a date | The approved-endpoint list omits the legacy server, and two exemptions waive the keyed-connection and approved-endpoint controls for it until the expiry the governance stage passes, 90 days after the stage runs (a direct Bicep deployment uses the default `2026-11-30T00:00:00Z`). After that moment the exemptions are no longer honoured | The waived controls would flag the legacy connection again and, with the Deny default, block re-creating it (Inferred from the effect default) | **Configured**: `infra/06-governance.bicep:162-168#approvedMcpEndpoints`, `scripts/deploy.ps1:448#legacyWaiverExpiry`, `infra/06-governance.bicep:28-28#legacyWaiverExpiry`, `infra/06-governance.bicep:232-256#abw-ex-legacy-key-account`, `infra/06-governance.bicep:20-21#hardControlEffect`. **Platform behaviour**: https://learn.microsoft.com/azure/governance/policy/concepts/exemption-structure (an expired exemption is kept but no longer honoured) |

**Why (Inferred).** The defaults in table C trade strictness for a demo that comes up in a fresh tenant on the first run. Each one is visible in the code as a parameter or a one-line setting, so each can be tightened without redesign.

**Trade-off / limitation.** Table A is the real scale limit. Hundreds of deals would need an external entitlement system that the tools consult at call time (not in this repo; section 5.7 lists what it would add), and tables B and C list the places where evidence is weaker than the design.

### 13.4 The multi-deployment hazard

**What this section proves.** A second deployment in the same Entra tenant or Azure subscription takes over objects the first one owns and can break it. The orchestrator carries a guard for this; running the stage scripts directly does not.

The Entra objects have fixed names and the policy initiative has a fixed name, so a second deployment does not create copies. It finds the existing objects by name and updates them (`scripts/Deploy-AgentWall.ps1:23-24#tenant`).

| Shared object | Fixed name | What a second deployment does | Source |
|---|---|---|---|
| API apps and the two client apps | `abw-*` display names | Phase 1 finds each by name and patches it in place | **Implemented**: `identity/Setup-Entra.ps1:64-69#Find-One`, `identity/Setup-Entra.ps1:131-132#PATCH` |
| Security groups | `sg-abw-*` | Phase 1 finds each group by its exact name; teardown deletes every group whose name starts with the prefix, including another party's, and the orchestrator's existing-objects probe also matches the prefix | **Implemented**: `identity/Setup-Entra.ps1:113-113#displayName eq`, `identity/Setup-Entra.ps1:299-300#startswith`, `scripts/Deploy-AgentWall.ps1:954-954#sg-abw-` |
| Persona users | `abw.<persona>@<tenant-domain>` | With adoption on, Phase 1 resets the password of an existing user that has no stored password and creates a new agent-client secret when none is stored locally | **Implemented**: `scripts/Deploy-AgentWall.ps1:976-976#AdoptExistingEntra`, `identity/Setup-Entra.ps1:212-218#password` |
| Federated credentials on the four API apps that have managed-identity servers | `uami-research`, `uami-wall`, `uami-actions`, `uami-private` | Phase 2 deletes and re-creates a credential whose subject differs, so the first deployment's servers can no longer exchange tokens. The guard's own warning says any other deployment that uses the objects will break | **Implemented**: `identity/Setup-Entra.ps1:270-274#uami-`, `scripts/Deploy-AgentWall.ps1:976-976#break` |
| Subscription-scope policy definitions and the initiative | `abw-foundry-*` and `abw-agent-platform-controls` | Redeployed with the same names; teardown tries to delete every custom initiative and definition whose name starts with `abw-` and only warns when one cannot be deleted because it is still assigned elsewhere, so tearing down one deployment can remove them from under the other (the last step is Inferred) | **Configured**: `infra/06a-policy-definitions.bicep:19-19#targetScope`. **Implemented**: `scripts/deploy.ps1:443-443#policy-defs`, `scripts/teardown.ps1:93-98#abw-*`, `scripts/teardown.ps1:205-214#set-definition` |
| Redirect URIs on the agent client | n/a | Merged with the existing list, so adding a deployment keeps the first one's URIs | **Implemented**: `identity/Setup-Entra.ps1:281-282#merged` |

**Guards (Implemented, orchestrator only).**

| Guard | Behaviour | Source |
|---|---|---|
| Read-only check | `-CheckOnly` reports without changing anything | `scripts/Deploy-AgentWall.ps1:17-18#CheckOnly` |
| Existing-objects probe | Looks for any app named `abw-*`, group named `sg-abw-*` or user named `abw.*`; returns true, false, or null when Graph cannot be read | `scripts/Deploy-AgentWall.ps1:950-964#Test-ExistingEntraDeployment` |
| Takeover guard | If objects exist, blocks the run unless `-AdoptExistingEntra` is given; with it, warns that Phase 1 will update them, create a new agent-client secret when none is stored locally, reset passwords of existing users that have no stored password, and break any other deployment that uses them. It is skipped, with a warning, when Graph is unreadable | `scripts/Deploy-AgentWall.ps1:967-986#Test-EntraTakeoverGuard` |
| Initiative probe | Warns only (it does not block) when the initiative already exists and governance will run for the first time | `scripts/Deploy-AgentWall.ps1:988-992#Test-ExistingInitiative`, `scripts/Deploy-AgentWall.ps1:1319-1323#governance` |
| When the Entra guard runs | Only when the first Entra step will run and either a fresh start is assumed or no Entra state file exists | `scripts/Deploy-AgentWall.ps1:1316-1318#entra1` |

**Inferred absence.** The guard exists only in the orchestrator: a search finds `AdoptExistingEntra` in `Deploy-AgentWall.ps1`, in its self-test and in the documents and diagram that describe it (`scripts/Test-DeployOrchestrator.ps1:658-658#AdoptExistingEntra`, `docs/SELF-DEPLOY.md:45-45#AdoptExistingEntra`, `docs/diagrams/dg10.py:45-45#AdoptExistingEntra`), and not in `deploy.ps1` or `Setup-Entra.ps1`, so running those directly applies no such check.

**Remedies.** Use a different tenant, which also means a different subscription (the guard's own advice, `scripts/Deploy-AgentWall.ps1:979-979#different tenant`); a different subscription in the same tenant still collides on the tenant-wide Entra objects (`scripts/Deploy-AgentWall.ps1:23-24#tenant-wide`); adopt the existing objects knowingly with `-AdoptExistingEntra` and accept that the other deployment breaks; or tear down with `-KeepEntra`, after which the federated credentials point at deleted identities until Phase 2 replaces them (section 5.8).

**Why.** The Entra objects are named, not parameterised, so the proofs, the console and the Foundry connections can refer to fixed names (`DESIGN.md:85-98#abw-`; section 2.7).

**Trade-off / limitation.** The price is a single-copy limit: one platform per tenant and per subscription, and a shared tenant is a risk for any other work that uses the `abw` prefix.

### 13.5 Security posture and residual risk

**What this section proves.** The data path is keyless and no server holds a key to a data store, but the platform is not secret-free: one OAuth client secret, a legacy subscription key, a vendor key, persona passwords and TOTP seeds, an ingestion connection string and a jump-box password remain, each with a known location and rotation story.

**What is keyless (Configured unless marked).**

| Surface | Setting | Source |
|---|---|---|
| Storage accounts | Shared-key access off, public blob access off, OAuth by default | `infra/03-platform.bicep:131-135#allowSharedKeyAccess` |
| Cosmos DB (platform account) | Local auth disabled, public network access disabled | `infra/03-platform.bicep:227-230#disableLocalAuth` |
| AI Search | Local (key) auth disabled, public network access disabled | `infra/03-platform.bicep:314-315#disableLocalAuth` |
| Key Vault | Azure RBAC authorisation; public endpoint on, default action Deny, trusted-service bypass, one IP rule for the NAT public address | `infra/03-platform.bicep:91-91#enableRbacAuthorization`, `infra/03-platform.bicep:94-102#natPublicIp` |
| Container Registry | The registry's built-in user is off; apps pull with their managed identities; images are built in the cloud with ACR Tasks, so no local Docker is needed | `infra/03-platform.bicep:112-118#publicNetworkAccess`, `infra/modules/mcp-app.bicep:45-50#uamiId`, `scripts/build-images.ps1:34-34#acr` |
| Foundry account | Local (key) auth disabled | `infra/foundry/modules-network-secured/ai-account-identity.bicep:52-52#disableLocalAuth` |
| MCP servers to data stores | No client secret: each server's managed identity is federated to its API app and presents a federated assertion in the on-behalf-of exchange (**Implemented** as well) | `identity/Setup-Entra.ps1:264-275#uami-`, `src/mcp/abw_mcp/obo.py:57-57#client_assertion`, `src/mcp/abw_mcp/obo.py:77-78#AzureADTokenExchange` |
| MCP APIs at the gateway | Token signature, issuer, expiry, tenant and the API's `aud` claim are validated before any role check | `infra/apim/policies/mcp-jwt.policy.xml:17-30#validate-jwt` |

The README reports a 7-day log check in which none of the platform's own users, agents or apps used a key or SAS; four SAS-signed storage requests came from Azure itself during Defender for Storage onboarding and are disclosed (`README.md:145-145#SAS`).

**What is still a secret.**

| Secret | Where it lives | Rotation | Source |
|---|---|---|---|
| Agent-client secret | The local, gitignored secrets folder (written by Phase 1), and a copy inside each of the five OAuth Foundry connections | Phase 1 re-creates it when fewer than 10 days remain (80-day life) and writes only the local file; the connections keep their copy until `foundry-connections.ps1` re-creates them; nothing removes an older secret | **Implemented**: `identity/Setup-Entra.ps1:158-169#secretPath`, `scripts/foundry-connections.ps1:79-90#client-secret` |
| Legacy APIM subscription key | Held in the Foundry key connection for the legacy server; fetched from ARM with `listSecrets`; the demo client reads it the same way | None in the repo; the legacy path is the deliberate anti-pattern | **Implemented**: `scripts/foundry-connections.ps1:65-65#mcp-legacy-key`, `scripts/foundry-connections.ps1:91-95#listSecrets`, `demo/mcpclient.py:157-161#listSecrets`, `infra/05-apim-apis.bicep:204-213#legacySub` |
| Persona passwords, TOTP seeds, MSAL token caches | The local secrets folder only. They reach the jump box only with `-IncludePersonaFiles`, as plain refresh-token caches plus demo passwords, locked to SYSTEM and the VM's local account but not encrypted | None; Phase 1 resets only an existing persona that has no stored password | **Implemented**: `identity/Setup-Entra.ps1:199-218#pwPath`, `console/personas.py:42-43#TOTP_STORE`, `identity/Persona-Totp.py:35-35#STORE`, `scripts/jumpbox-console.ps1:18-21#IncludePersonaFiles`. **Designed**: `README.md:147-147#Acting` |
| Jump-box local password | Generated on the first deploy and saved in the local secrets folder; never printed and never copied to the VM. Bastion Developer needs a password, so it sits outside the keyless story | None in the repo | **Implemented**: `scripts/jumpbox.ps1:24-26#password`, `scripts/jumpbox.ps1:254-263#secretFile` |
| Vendor API key | Three places: a local file, an inline Container App secret, and a Key Vault secret that API Management reads through a versionless reference | None in the repo | **Implemented**: `scripts/deploy.ps1:182-186#Get-VendorKey`, `infra/04-apps.bicep:182-187#vendor-api-key`, `scripts/deploy.ps1:375-375#secretUri` |
| App Insights connection string | An ingestion key in a Container App secret. The platform creates the Foundry telemetry connection with an ingestion key and a policy exemption covers it. Log Analytics ingestion keys are still enabled; Entra-authenticated ingestion is the named follow-up | None | **Configured**: `infra/04-apps.bicep:68-73#appiSecret`, `infra/06-governance.bicep:258-258#appiReason`. **Designed**: `DESIGN.md:238-238#ingestion` |

**Inferred note on the agent-client secret.** A holder of the secret cannot call a tool by itself. A client-credentials token carries no `scp` claim, so layer 1 refuses it with `missing_scope`, and the five API apps expose delegated scopes and user-only roles. The holder would still need a user sign-in. This is derived from the policy and the scope definitions and was not tested.

| Evidence for the inferred note | Source |
|---|---|
| The gateway refuses a token without the `Tools.Read` scope | `infra/apim/policies/mcp-jwt.policy.xml:39-39#missing_scope` |
| The API scopes are delegated and the roles are for users | `identity/Setup-Entra.ps1:29-45#Tools.Read` |

**Partial controls and residual risk.**

| Control | Gap | Source |
|---|---|---|
| WORM audit container | The time-based policy is left unlocked and the data is synthetic: a pattern, not a SEC 17a-4 attestation. An unlocked policy can be shortened, extended or deleted; a locked one cannot be deleted | **Designed**: `README.md:143-143#unlocked`, `DESIGN.md:239-239#WORM`. **Platform behaviour**: https://learn.microsoft.com/azure/storage/blobs/immutable-storage-overview |
| Public surfaces | The API Management gateway, the Foundry account's public access and the Container Registry stay public; each is documented and exempt | **Configured**: `infra/05-apim.bicep:61-61#publicNetworkAccess`, `scripts/deploy.ps1:267-267#foundryPublicNetworkAccess`, `infra/03-platform.bicep:112-118#publicNetworkAccess`. **Designed**: `README.md:146-146#ACR`, `DESIGN.md:243-243#exempt` |
| Policy ordering | An organisation baseline's Modify runs before the Deny, so a violating request can succeed and come back safe; 3 of 9 attempts were handled that way. Policy evaluates disabled, then modify, then deny, then audit | **Designed**: `docs/RUNBOOK.md:302-302#CORRECTED`, `docs/RUNBOOK.md:342-342#Policy`. **Platform behaviour**: https://learn.microsoft.com/azure/governance/policy/concepts/effect-basics#order-of-evaluation |
| Conditional Access | Report-only; it blocks nothing | **Designed**: `docs/COST.md:27-27#billed`, `README.md:148-148#Conditional` |
| Foundry-created agent identities | The identities and blueprints for the agents are not tagged, so teardown leaves them; check the Entra portal afterwards | **Designed**: `README.md:159-159#blueprints` |
| The model is not the control | The wall (identity and policy at the tool boundary) is deterministic; the model and the guardrail are not | **Designed**: `README.md:150-150#control` |

**Trade-off / limitation.** The residual-risk list is short because the data path is genuinely keyless, but the keyless claim has footnotes that a reviewer should read first: the OAuth client secret in Foundry, the vendor key's three homes, and the plain-file persona material on the jump box.

### 13.6 Failure modes and recovery

**What this section proves.** The runbook records 39 troubleshooting rows. Most are waits (token and log lag), resets (console and baseline) or sign-ins (consent and device code), and the recovery commands are short and scripted. Three preventive habits are recorded: `abw-preshow` at T-45, `abw-warm` at T-30 and the persona baseline before the first consent.

Diagram: docs/diagrams/13-trust-boundaries-and-failure-modes.excalidraw

**Console and local.**

| Symptom | Cause | Recovery | Source |
|---|---|---|---|
| The Python env is reported missing, or the window closes | The `.venv` was not created on this machine, or a dependency is missing | One-time setup: create the venv and install the requirements | `docs/RUNBOOK.md:279-279#venv` |
| The console asks you to sign in | The `az` cache is empty or expired; every token the console uses comes from it | Finish the browser sign-in as the demo operator, or run `az login` for the tenant first | `docs/RUNBOOK.md:280-280#cache` |
| The page is blank or does not open | The browser did not auto-open, or port 8787 was busy | Use the address the console prints; `/api/health` answers when it is up | `docs/RUNBOOK.md:281-281#8787` |
| "Can't start that right now" | A beat that would collide with a running job or a gateway change | Wait for the job chip, or use Reset demo (about 1.5 minutes) | `docs/RUNBOOK.md:282-282#collide` |
| A status light is red or amber | The live check behind it failed | Press Preflight to name it; Reset demo clears a leftover kill switch or allow-list change | `docs/RUNBOOK.md:283-283#Preflight` |
| "Azure CLI token unavailable" | The Azure CLI token cache is empty or expired, or `az` is slow to start | Refresh the token for the Foundry resource and retry, or sign in again | `docs/RUNBOOK.md:291-291#unavailable` |
| SSL EOF, DNS errors, connection reset | A flaky local network | The agent client retries name resolution automatically; reconnect Wi-Fi or VPN and rerun if it persists | `docs/RUNBOOK.md:294-294#netfix`, `src/agent/netfix.py:18-18#_retrying_getaddrinfo`, `src/agent/netfix.py:31-31#install` |
| The Acting as panel says the console predates the persona switcher | The console process started before the new backend files existed | Close the console window and start it again (this clears job history) | `docs/RUNBOOK.md:312-312#switcher` |

**Identity and consent.**

| Symptom | Cause | Recovery | Source |
|---|---|---|---|
| Consent link or "consent needed" | First run for that persona and connection, or Foundry dropped the token | Paste the link into that persona's InPrivate window and repeat | `docs/RUNBOOK.md:284-284#consent` |
| A device-code prompt appears mid-demo | The persona's refresh token is missing or expired, or the operator path was asked for a persona never signed in on this machine | Use the operator path, or generate a one-time code with the TOTP script and finish the device sign-in; avoid it by running `abw-warm` at T-30 | `docs/RUNBOOK.md:285-285#device-code` |
| `AADSTS50076` or `50079` | The persona is not MFA-enrolled | Enrol the persona (runbook section 3); the DESIGN notes the enrolment was not exercised in the second tenant | `docs/RUNBOOK.md:286-286#AADSTS50076`, `DESIGN.md:241-241#TOTP` |
| Redirect URI mismatch, or the consent page loops | The Foundry connection's redirect URLs changed | Run `foundry-connections.ps1 -Force` and redo the consents (the runbook says "re-creates"; the README says "overwrites in place", Finding 11) | `docs/RUNBOOK.md:287-287#redirect` |
| The consent link opens signed in as the wrong person, or has expired | The default browser holds another session; links live about 10 minutes | Point the `BROWSER` variable at a private browser window and rerun for a fresh link | `docs/RUNBOOK.md:303-303#BROWSER` |
| A one-time code is rejected | Clock skew; codes roll every 30 seconds | Resync the machine clock from an elevated shell and retry | `docs/RUNBOOK.md:305-305#TOTP` |
| A role change is not in the token | Entra role-claim propagation, about 30 s | Wait and request a new token | `docs/RUNBOOK.md:295-295#propagation` |
| The agent shows the old roles after a flip or a restore | Foundry holds the user's access token for its whole life (60 to 90 minutes) | Nothing to fix; it clears when the token expires. Use real personas, not a flip account | `docs/RUNBOOK.md:296-296#Foundry` |
| The agent shows `(none)` for wall, actions or private tools | The persona baseline was applied after the first consent, so Foundry kept the role-less token and the tool list it saw (about 15 to 20 minutes) | Apply the baseline before the first consent; otherwise wait or re-consent | `docs/RUNBOOK.md:299-299#baseline`, `docs/SELF-DEPLOY.md:175-175#baseline` |
| A persona "has not signed in yet" or its sign-in has expired | No cached gateway token for that persona, or it was revoked | Sign in through Acting as (the persona must be MFA-enrolled) or switch back to the operator | `docs/RUNBOOK.md:313-313#sign-in` |
| `foundry-connections.ps1` reports a tenant mismatch | `azd` is signed in to another tenant | Give azd its own config directory through `AZD_CONFIG_DIR` and set Azure CLI auth | `docs/RUNBOOK.md:300-300#AZD_CONFIG_DIR` |

**Gateway and policy.**

| Symptom | Cause | Recovery | Source |
|---|---|---|---|
| HTTP 401 right after a kill or allow-list change | The old token meets the new gateway state | Wait about 50 s, get a new token, and reset both switches if needed | `docs/RUNBOOK.md:288-288#401` |
| HTTP 429 after a burst | The 120 calls per 60 s per user limit | Wait 60 s | `docs/RUNBOOK.md:289-289#429` |
| An agent beat is refused with 403 `token_quota_exceeded` or 429 `rate_limited` | A lowered limit is still set, or the rate lock-out (about 2 minutes) is still running | Reset demo restores both settings and waits until the front door forwards | `docs/RUNBOOK.md:316-316#token_quota_exceeded` |
| `abw-ask` prints nothing for more than 45 s | Foundry is slow | Switch to Plan B or stop the command | `docs/RUNBOOK.md:304-304#abw-ask` |
| A proof left the tenant in an odd state | An aborted proof | `abw-restore`: it resets the kill switch and the allow-list, puts the operator back in the Falcon group and mirrors two personas (67 to 104 s) | `docs/RUNBOOK.md:297-297#abw-restore`, `docs/RUNBOOK.md:344-344#restore` |
| The guardrail never intervenes | It is a preview, best-effort control (about 9 to 63 % of identical requests) | Expected; the wall's refusal is the deterministic part | `docs/RUNBOOK.md:298-298#preview` |
| The policy proof reports CORRECTED where BLOCKED was expected | The organisation baseline's Modify ran before the Deny | Expected and still passing; do not bypass the baseline | `docs/RUNBOOK.md:302-302#CORRECTED` |
| The governance stage fails once in a new tenant | `CheckAccessPrincipalCreationConcurrencyError` on the first role check-access calls | Wait about 75 s and re-run the stage (the orchestrator retries after 90 s, Finding 18) | `docs/RUNBOOK.md:301-301#CheckAccessPrincipalCreationConcurrencyError`, `scripts/Deploy-AgentWall.ps1:426-426#RetryDelay` |
| The agent entry light says the agent is on the direct path | A console switch was pressed; it changes nothing in Azure | Press the switch back, or Reset demo | `docs/RUNBOOK.md:317-317#direct` |

**Observability.**

| Symptom | Cause | Recovery | Source |
|---|---|---|---|
| The `abw-chain` query returns 0 rows or only the gateway row | Ingestion lag of 5 to 10 minutes (the server row of a denial can take longer), or a wrong id | Wait | `docs/RUNBOOK.md:290-290#abw-chain` |
| Sentinel shows no incidents | Rules run every 5 minutes on top of about 5 minutes of ingestion | Run `abw-preshow` at T-45; incidents appear up to about 8 minutes after the event by the runbook (about 13 for the Storage-sourced rule), the proof playbook allows up to about 15 minutes (`docs/PROOF-PLAYBOOK.md:193#Allow`) and one dry run needed 22 (`docs/PROOF-PLAYBOOK.md:501#ABW-001`) | `docs/RUNBOOK.md:292-292#Sentinel` |
| An Act 6 board is no longer in memory, or a row says Waiting | Boards live in console memory only, or the log has not arrived | Run the scenario again; press Refresh from logs 15 to 20 minutes after the click | `docs/RUNBOOK.md:314-314#Refresh` |
| An Act 7 person tab says Not signed in | That person has not signed in through the console, or the sign-in expired | Press Sign in in the tab header (the person must be MFA-enrolled) | `docs/RUNBOOK.md:315-315#Sign` |

**Platform and jump box.**

| Symptom | Cause | Recovery | Source |
|---|---|---|---|
| First call after idle is slow (10 to 20 s) | Container Apps cold start | `abw-warm`; keep minimum replicas at 1 | `docs/RUNBOOK.md:293-293#cold` |
| A portal data page fails on the laptop | Those data planes are private-endpoint-only by design; the laptop resolves public names and is refused | Expected; show the page from the jump box | `docs/RUNBOOK.md:306-306#private-endpoint` |
| The jump box will not connect | The VM is deallocated (it stops itself at 03:00 Central), or another Bastion Developer session is open | `Start-JumpBox.bat` (about a minute), close the other session, retry | `docs/RUNBOOK.md:307-307#03:00` |
| `Start-JumpBox.bat` says it is not deployed | It was removed, or never deployed in this subscription | Run `jumpbox.ps1` (the runbook says about 2 minutes, Finding 21) | `docs/RUNBOOK.md:308-308#Start-JumpBox.bat` |
| The console shortcut on the VM says Python or `az` is missing | The package or an installer never finished | Re-run `jumpbox-console.ps1` from the laptop (safe to repeat), then verify | `docs/RUNBOOK.md:309-309#jumpbox-console.ps1` |
| Signed in is red on the VM, or the shortcut window asks for a sign-in | First start on the VM, or the Azure CLI sign-in expired | The window prints a device code and opens the code page; sign in as the demo operator (MFA), then press Preflight | `docs/RUNBOOK.md:310-310#Signed` |
| Acting as on the VM says a persona has not signed in | No cached sign-in for that persona on the VM | Sign in once with a device code, or redeploy the console with `-IncludePersonaFiles` for personas cached on the laptop | `docs/RUNBOOK.md:311-311#IncludePersonaFiles` |

**Recovery tools and preventive habits.**

| Tool or habit | What it does | Source |
|---|---|---|
| Reset demo (console) | Clears a leftover kill switch or allow-list change and waits until the front door forwards; about 1.5 minutes | **Designed**: `docs/RUNBOOK.md:282-282#collide`, `docs/RUNBOOK.md:316-316#token_quota_exceeded` |
| `kill-switch.ps1 -Reset` | Empties the deny-list | **Implemented**: `scripts/kill-switch.ps1:90-93#Reset` |
| `client-allowlist.ps1 -Reset` | Restores the allow-list to the agent, test and Azure CLI clients | **Implemented**: `scripts/client-allowlist.ps1:84-87#Reset` |
| `abw-restore` | Baseline reset after an aborted proof | **Designed**: `docs/RUNBOOK.md:297-297#abw-restore` |
| `abw-preshow` at T-45 and `abw-warm` at T-30 | The runbook names them as the remedy for the "no incidents" row (preshow) and for the device-code and cold-start rows (warm) | **Designed**: `docs/RUNBOOK.md:285-285#device-code`, `docs/RUNBOOK.md:292-293#Sentinel` |
| Persona baseline before the first consent | Avoids a role-less token and an empty tool list that Foundry holds for 60 to 90 minutes | **Designed**: `docs/SELF-DEPLOY.md:175-175#baseline`, `docs/RUNBOOK.md:299-299#baseline` |

**Trade-off / limitation.** Recovery is mostly waiting and resetting, and the lag figures (tokens 60 to 90 minutes, logs up to 20 minutes) set the pace of any live failure. There is no automated health check or alert for the platform itself beyond the three log alert rules priced in 13.1 and the console's Preflight.

**Key takeaways**

- **Cost is the calendar.** Nine of twelve lines are fixed, the platform costs about USD 37 a day while it exists and API Management is 63 % of it. The figures are a list-price estimate (`docs/COST.md:3-3#Bottom`, `docs/COST.md:38-38#fixed`).
- **Nothing caps spend.** The USD 1,200 budget mails the group Owners and stops nothing. The only automatic brake is the per-user token and rate limit at the front door, counted after the response (`infra/09-budget.bicep:3-5#alert`, `infra/apim/policies/agent-frontdoor.policy.xml:96-96#llm-token-limit`).
- **Capacity is demo scale and untested for load.** One API Management unit, at most two replicas per server, one Search replica and a 100K tokens-per-minute model (`infra/05-apim.bicep:47-50#capacity`, `infra/modules/mcp-app.bicep:19-22#minReplicas`).
- **The scale limit is the operating model.** One role per deal, four edit places and no entitlement store (not in this repo); the Entra caps are far away (13.3 table A).
- **Visibility has holes.** The denial table has four layers; Entra, Cosmos and Search refusals and the private MCP server sit outside it, the guardrail is a preview and logs lag by minutes (13.3 table B).
- **One deployment per tenant and per subscription.** Fixed `abw-*` Entra names, four federated credentials replaced by Phase 2 and a subscription-scope initiative; the guard lives only in the orchestrator (13.4).
- **Keyless is true of the data path, with footnotes.** The remaining secrets are the OAuth client secret, the legacy subscription key, the vendor key, persona passwords and TOTP seeds, the ingestion connection string and the jump-box password (13.5).
- **Several defaults are tuned for the demo.** Discovery without a role, backend TLS validation off, best-effort audit, an unlocked WORM policy, a public gateway and a legacy waiver that lapses 90 days after the governance stage runs (13.3 table C, 13.5).
- **Recovery is waiting and resetting.** Reset demo, the baseline reset, the two `-Reset` switches and a fresh token after any revocation cover almost every recorded failure (13.6).


### 13.7 Findings

The 22 findings raised while writing sections 2 to 5, 13 and Appendix A (documentation mismatches, defects and undocumented decisions) are collected in [Appendix B.2](appendix-b-findings-register.md#b2-raised-while-writing-sections-2-to-5-13-and-appendix-a). Where the text above says "Findings" or quotes a finding number, it means that list.

---

[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [12. Demo Console architecture](12-demo-console.md) | Next: [Appendix A. Repository file index](appendix-a-file-index.md)
