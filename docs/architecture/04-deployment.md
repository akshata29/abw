[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [3. Infrastructure and network design](03-infrastructure-and-network.md) | Next: [5. Identity objects and entitlement model](05-identity-objects.md)

## 4. Deployment architecture

**What this section proves.** The platform is built by a fixed sequence of idempotent stages. Each stage is a thin PowerShell wrapper around one Bicep deployment (or around a Microsoft Graph, ACR Tasks, azd or Foundry SDK call) and hands its outputs to later stages through a small JSON state file (`scripts/deploy.ps1:30-44#ValidateSet`). This section lists every stage, what it reads and writes, why the order is what it is, which steps are slow or fragile, and how everything is removed again. The one-command orchestrator (4.9) runs the same stages as the manual README path, with the differences listed in 4.1 (`docs/SELF-DEPLOY.md:158#README`). Labels (Configured, Implemented, Designed, Platform behaviour) are used as defined in section 2.

### 4.1 Stage graph

**What this section proves.** Every build step, in the order the orchestrator runs them, with the files it needs and the file it leaves behind. The order is the orchestrator's plan order (`docs/SELF-DEPLOY.md:160-187#guardrail`), which follows the README quickstart (`README.md:65-85#preflight`) with three differences. Preflight runs before Entra Phase 1 (`scripts/Deploy-AgentWall.ps1:392-395#entra1`). There is no separate observability step, because governance already runs it (`scripts/deploy.ps1:450#Invoke-ObservabilityStage`). And the orchestrator adds baseline, front door, budget, jump box, console and two extras steps that the README code block does not list. The minutes are planning figures printed by the orchestrator, not measurements (`docs/SELF-DEPLOY.md:189#planning`).

Diagram: docs/diagrams/10-deployment-pipeline.excalidraw

| Order | Step | Script / Bicep | Scope | Reads from earlier stages | Writes | Typical min | Notes |
|---|---|---|---|---|---|---|---|
| 1 | preflight | `scripts/deploy.ps1 -Stage preflight` (az CLI only, no Bicep) | subscription and RG | `config.json`, created from the az sign-in on first use (`scripts/common.ps1:29-58#Get-AbwConfig`) | the tagged RG, 17 resource providers registered, `preflight.json` | 1-3 | **Implemented** at `scripts/deploy.ps1:194-214#preflight`; provider loop at `scripts/deploy.ps1:202#Microsoft.Network`. It does not check quota (see Findings in section 13). |
| 2 | entra1 | `identity/Setup-Entra.ps1 -Phase 1` | Entra tenant (Graph) | `config.json` | `entra.json`, the agent-client secret in the secrets folder | 3-5 | `identity/Setup-Entra.ps1:104#Invoke-Phase1`. Needs no Azure resource (4.5). |
| 3 | network | `scripts/deploy.ps1 -Stage network` -> `infra/01-network.bicep` | RG | none | `network.json` | 2-4 | `scripts/deploy.ps1:216-225#network`. Never re-run once the jump box subnet exists (4.11). |
| 4 | foundry | `-Stage foundry` -> `infra/foundry/main.bicep` (vendored) | RG | `network.json` | `foundry.json` | 15-20 | `scripts/deploy.ps1:227-278#foundry`. Account, project, model, agent-state stores, capability host, AMPLS, App Insights (4.3). |
| 5 | foundryrbac | `-Stage foundryrbac` -> `infra/02-foundry-rbac.bicep` | RG | `foundry.json`, `entra.json` | `foundryrbac.json` | 1-3 | `scripts/deploy.ps1:280-291#foundryrbac`. Passes the operator object id and the all-users group id. |
| 6 | platform | `-Stage platform` -> `infra/03-platform.bicep` | RG | `network.json`, `entra.json` | `platform.json` | 10-15 | `scripts/deploy.ps1:293-321#platform`. Six UAMIs, data stores, two Container Apps envs, private endpoints, diagnostics, RBAC. |
| 7 | images | `scripts/build-images.ps1` (target mcp) | ACR Tasks | none (the registry name comes from naming) | `images.json` | 5-8 | `scripts/build-images.ps1:34#acr`. Needs the registry from step 6. |
| 8 | apps | `-Stage apps` -> `infra/04-apps.bicep` | RG | `platform.json`, `entra.json`, `images.json`, the vendor key file in the secrets folder | `apps.json` | 5-8 | `scripts/deploy.ps1:323-348#apps`. Six Container Apps and the vendor key secret. |
| 9 | entra2 | `identity/Setup-Entra.ps1 -Phase 2` | Entra tenant (Graph) | `entra.json`, `platform.json` | federated credentials on four API apps | 1-2 | `identity/Setup-Entra.ps1:258-286#Invoke-Phase2` (4.5). |
| 10 | apim | `-Stage apim` -> `infra/05-apim.bicep` | RG | `network.json`, `entra.json`; workspace and App Insights ids derived by `Get-ObservabilityIds` | `apim.json` | 35-50 | `scripts/deploy.ps1:350-368#apim`, `scripts/deploy.ps1:142-147#Get-ObservabilityIds`. The slowest stage. |
| 11 | apis | `-Stage apis` -> `infra/05-apim-apis.bicep` | RG | `apps.json` (including the versionless vendor key secret URI), `entra.json` | `apis.json` | 3-6 | `scripts/deploy.ps1:370-390#apis`. |
| 12 | images-seed | `scripts/build-images.ps1 -Target seed` | ACR Tasks | none | `images-seed.json` | 3-6 | `scripts/build-images.ps1:7-10#abw-seed`. |
| 13 | seed | `-Stage seed` -> `infra/04b-seed-job.bicep`, then `az containerapp job start` | RG | `platform.json`, `images-seed.json` | `seed.json` | 5-12 | `scripts/deploy.ps1:406-437#seed`. Polls every 15 s for up to 12 min (4.4). |
| 14 | baseline | persona mirroring on the operator (a helper in `identity/`) | Entra tenant (Graph) | the persona and group objects from step 2 | the operator's role and group membership | 1-2 | `docs/SELF-DEPLOY.md:175#baseline`. Must run before the consent clicks (`README.md:92#Baseline`). |
| 15 | connections | `scripts/foundry-connections.ps1` | Foundry project (azd) and Entra | `entra.json`, `apis.json`, `apps.json`, `foundry.json` | `connections.json`; Phase 2 re-run for redirect URIs | 5-10 | `scripts/foundry-connections.ps1:39-43#Read-Json` (4.6). |
| 16 | agents | `src/agent/create_agents.py` | Foundry project (SDK) | `foundry.json`, `apis.json`, `apps.json` | `agents.json` | 2-4 | `src/agent/abw_agents.py:79-106#load_state`. The first run publishes 3 agents, not 4 (4.6). |
| 17 | governance | `-Stage governance` -> `06a`, then `06`, then `06b` | subscription, then RG | the initiative id from its own subscription-scope deployment | `policy.json`, `governance.json`, `observability.json` | 8-12 | `scripts/deploy.ps1:439-451#governance` (4.7). |
| 18 | guardrail | `src/agent/create_agents.py --rai abw-agent-guardrails` | Foundry project (SDK) | the guardrail policy created in step 17 | `agents.json`, refreshed | 1-3 (optional) | `src/agent/create_agents.py:30#rai`. Attaches the guardrail and publishes the shielded agent (4.6). |
| 19 | frontdoor | `-Stage frontdoor` -> `infra/08-agent-frontdoor.bicep` | RG | the Foundry project endpoint | `frontdoor.json` | 5-10 (optional) | `scripts/deploy.ps1:392-398#frontdoor`. |
| 20 | budget | `-Stage budget` -> `infra/09-budget.bicep` | RG | none | `budget.json` | 1-2 (optional) | `scripts/deploy.ps1:400-404#budget`. An alert, not a cap (section 13.1). |
| 21 | jumpbox | `scripts/jumpbox.ps1` -> `infra/07-jumpbox.bicep` | RG | the existing VNet and NAT gateway (looked up in Azure) | `jumpbox.json`, plus the local password file in the secrets folder | 10-15 (optional) | `scripts/jumpbox.ps1:235-303#Invoke-DeployAndVerify` (4.8). |
| 22 | console | `scripts/jumpbox-console.ps1` | the VM, through run-command | the VM from step 21 and the scrubbed demo evidence | the console installed on the VM | 15-25 (optional) | `scripts/jumpbox-console.ps1:603#Invoke-DeployMode` (4.8). |
| - | observability (stand-alone) | `-Stage observability` -> `infra/06b-observability.bicep` | RG | the workspace | `observability.json` | inside step 17 | `scripts/deploy.ps1:453-456#observability`. Governance already runs it, so the separate README step is a repeat (see Findings in section 13). |

Four more steps exist in the orchestrator plan but are not part of the platform build: `extras-defender` (`scripts/extras-defender-sentinel.ps1`), `extras-identity` (`scripts/extras-agent-identity.ps1`), `proofs` (`demo/prove.py`) and `scoreboard` (`demo/scoreboard.py`), with planning figures of 2-5, 1-3, 30-40 and 1 minutes (`docs/SELF-DEPLOY.md:160-187#guardrail`). Steps 1-21 add up to 122-200 minutes and the console raises that to 137-225 (`docs/SELF-DEPLOY.md:102#Time`). APIM alone is quoted at about 30 minutes or more (`README.md:74#apim`).

**Why this order.** Each rule below is a data dependency, not a convention.

1. **network before foundry.** The Foundry template does not create the VNet; it is handed the existing VNet, subnet ids and pre-created private DNS zone names (`scripts/deploy.ps1:231-241#monZones`, `scripts/deploy.ps1:259-262#existingVnetResourceId`).
2. **Entra Phase 1 before foundryrbac, platform, apps, apim and apis.** They take group ids and app ids from `entra.json` (`scripts/deploy.ps1:280-291#entra`).
3. **platform before images, images before apps.** The registry is created in the platform stage and the apps pull the `abw-mcp` image from it (4.4).
4. **Phase 2 after platform.** A federated credential needs the managed identity's principal id, which only exists once the UAMIs are created (`identity/Setup-Entra.ps1:261-262#platform`).
5. **apim before apis, apis before connections.** The APIs are declared on the existing APIM service and the connections point at the gateway URLs (`scripts/foundry-connections.ps1:59-66#specs`).
6. **connections before agents.** Each agent tool names its connection (`src/agent/abw_agents.py:134#project_connection_id`).
7. **governance after the objects it governs.** The stage's own comment says it is what flips the platform controls to Deny (`scripts/deploy.ps1:447#Deny`), and the exemptions reference the connections as `existing` resources (`infra/06-governance.bicep:210-229#legacyConnAccount`). That the connections must therefore exist first is inferred from those references.
8. **guardrail after governance.** The `raiPolicies` resource is created by the governance template (`infra/06-governance.bicep:86-99#guardrails`).

**Trade-off / limitation.** The dependency graph is implicit. There is no solver in `deploy.ps1`; a stage whose input file is missing fails with a "run X first" message (`scripts/foundry-connections.ps1:43#Run`, `identity/Setup-Entra.ps1:262#03-platform`). The orchestrator adds a plan that refuses a selection whose inputs do not exist (`docs/SELF-DEPLOY.md:189#planning`).

### 4.2 How `Invoke-Stage` works

**What this section proves.** Every Bicep stage goes through one function, so parameters, what-if, error reporting and state capture behave the same way for all of them (`scripts/deploy.ps1:79-113#Invoke-Stage`).

1. `New-ParamFile` writes the parameters, in the `2019-04-01` deployment-parameters schema with every value wrapped as `{ value: ... }`, to `params.<name>.json` in the generated-state folder (`scripts/deploy.ps1:50-61#Write-ParamFile`, `scripts/deploy.ps1:63-71#New-ParamFile`). That file is an audit copy of what was sent. A parameter named in `$script:SecretParamKeys` (today only `vendorApiKey`, passed by the apps stage) shows `***` in it, and `az` is given a second file, `params.<name>.tmp.json`, under the git-ignored secrets folder. When no parameter is secret, `az` reads the audit copy itself (`scripts/deploy.ps1:46-48#SecretParamKeys`, `scripts/deploy.ps1:345#vendorApiKey`).
2. The deployment is named `abw-<stage>` (`scripts/deploy.ps1:81#deployName`), so a stage normally leaves one ARM deployment record in the RG. The governance stage is the exception and makes three deployments: `abw-policy-defs` at subscription scope (`scripts/deploy.ps1:443#policy-defs`, named the same way by `scripts/deploy.ps1:116#deployName`), `abw-governance` in the RG (`scripts/deploy.ps1:448#governance`) and `abw-observability` in the RG (`scripts/deploy.ps1:450#Invoke-ObservabilityStage`). The stand-alone observability stage reuses the name `abw-observability` (`scripts/deploy.ps1:455#Invoke-ObservabilityStage`).
3. With `-WhatIf` it runs `az deployment group what-if` with `--result-format ResourceIdOnly` and returns. Nothing is deployed and no state file is written (`scripts/deploy.ps1:83-88#what-if`).
4. With `-NoWait` it starts `az deployment group create --no-wait`, prints a command to poll the deployment, and returns. No state file is written (`scripts/deploy.ps1:90-94#no-wait`).
5. Otherwise it runs `az deployment group create -o json`. On failure it warns, prints the raw output, lists the failed operations and throws "stage failed" (`scripts/deploy.ps1:95-102#failed`).
6. On success it flattens the outputs, saves them to the stage's state file when one is named, prints the duration and returns the outputs (`scripts/deploy.ps1:103-110#Save-Json`).
7. Steps 3 to 6 all run inside a `try`, and its `finally` calls `Remove-SecretParamFile`. That function deletes a path only when it lies under the secrets folder, so the live secret file does not outlive the call on success, failure, `-WhatIf` or `-NoWait`, and the audit copy is never removed (`scripts/deploy.ps1:73-77#Remove-SecretParamFile`, `scripts/deploy.ps1:112#finally`).

`Invoke-SubscriptionStage` is the same pattern with `az deployment sub` and an explicit location, used only for the policy definitions. It has no `-NoWait` branch, writes a parameter file only when it is given parameters, and `policy-defs` passes none (`scripts/deploy.ps1:115-140#Invoke-SubscriptionStage`, `scripts/deploy.ps1:118#Params`, `scripts/deploy.ps1:443#policy-defs`). It has no `finally`, so a secret parameter given to it would leave its live file in the secrets folder (Inference: nothing passes one today).

**State files.** Names only; they live in `infra/generated`, which is git-ignored (`.gitignore:5#generated`). `Save-Json` writes UTF-8 without a byte-order mark (`scripts/common.ps1:14-17#Save-Json`). The folder and the secrets folder are created on first use (`scripts/common.ps1:5-8#GenDir`). Secrets never go into the state files, including the parameter files kept as audit copies; they go to the secrets folder (4.5, 4.6). An audit copy is written when its stage runs, so a `params.apps.json` left by an earlier version of the script, which sent the vendor key in it, is replaced by the masked copy only the next time the apps stage runs (`scripts/deploy.ps1:63-71#New-ParamFile`).

| State file | Written by | Verified readers |
|---|---|---|
| `config.json` | `Get-AbwConfig` on first use (`scripts/common.ps1:29-58#Get-AbwConfig`) | every script |
| `preflight.json` | preflight, operator IP and time (`scripts/deploy.ps1:213#preflight.json`) | informational |
| `network.json` | network stage | foundry, platform, apim |
| `foundry.json` | foundry stage | foundryrbac, connections, agents (also the guardrail policy id, `src/agent/abw_agents.py:83-87#rai_policy_id`), the Defender extra (`scripts/extras-defender-sentinel.ps1:59#foundry.json`) and the violation probes (`demo/try-violations.py:54#foundry.json`) |
| `entra.json` | Entra Phase 1 (`identity/Setup-Entra.ps1:253#entraStatePath`) | foundryrbac, platform, apps, apim, apis, connections, Phase 2, and the operator tools: the allow-list and kill-switch scripts (`scripts/client-allowlist.ps1:37#entra.json`, `scripts/kill-switch.ps1:41#entra.json`), the identity extra (`scripts/extras-agent-identity.ps1:36#entra.json`), the persona helper (`identity/Use-AdminAsPersona.ps1:23#entra.json`) and the demo clients (`demo/mcpclient.py:34#entra.json`, `demo/abw_tokens.py:16#entra.json`) |
| `platform.json` | platform stage | apps, seed, Entra Phase 2 |
| `images.json`, `images-seed.json` | `build-images.ps1` (`scripts/build-images.ps1:42#builtAt`) | apps, seed |
| `apps.json` | apps stage | apis, connections, agents, the live-demo helper commands (`demo/stage.ps1:122#apps.json`) and the demo client (`demo/mcpclient.py:37#apps.json`) |
| `apis.json` | apis stage | connections, agents and the demo client (`demo/mcpclient.py:36#apis.json`) |
| `policy.json` | `Invoke-SubscriptionStage 'policy-defs'` (`scripts/deploy.ps1:443#policy-defs`) | governance (initiative id, `scripts/deploy.ps1:444-445#policy`) |
| `connections.json` | `foundry-connections.ps1` (`scripts/foundry-connections.ps1:116#connections.json`) | the consent-reset procedure (`README.md:93#connections.json`) |
| `agents.json` | `create_agents.py` (`src/agent/create_agents.py:40#agents.json`) | the orchestrator only: its guardrail done probe and its final verify step (`scripts/Deploy-AgentWall.ps1:371#agents.json`, `scripts/Deploy-AgentWall.ps1:1177#agents.json`) |
| `jumpbox.json` | `Update-State` (`scripts/jumpbox.ps1:140#Update-State`) | `jumpbox.ps1` itself, including its verify and remove modes (`scripts/jumpbox.ps1:60#stateFile`), the console deploy script (`scripts/jumpbox-console.ps1:66#jumpbox.json`) and the orchestrator's done probes (`scripts/Deploy-AgentWall.ps1:374#jumpbox.json`, `scripts/Deploy-AgentWall.ps1:377#jumpbox.json`). A different file of the same name holds the jump box password in the secrets folder (`scripts/jumpbox.ps1:59#secretFile`, `scripts/jumpbox_clip.py:22#SECRET_FILE`) |
| `frontdoor.json` | frontdoor stage | the console, which uses it to decide whether agent beats enter through the APIM front door (`console/jobs.py:93#FRONTDOOR_FILE`, `console/jobs.py:98-102#frontdoor_ready`) |
| `governance.json`, `observability.json` | the governance stage writes the first; the second is written by the observability step that governance runs, or by the stand-alone observability stage | the violation probes read `governance.json` (`demo/try-violations.py:55#governance.json`); the orchestrator's final verify step reads both (`scripts/Deploy-AgentWall.ps1:1184#governance.json`, `scripts/Deploy-AgentWall.ps1:1190#observability.json`) |
| `foundryrbac.json`, `apim.json`, `budget.json`, `seed.json` | the matching stage | no reader of their content was found in the scripts, console, demo, identity or source folders; they are the audit record of each deployment, and the orchestrator only checks that they exist (`scripts/Deploy-AgentWall.ps1:474-484#Get-MissingOutputs`) |
| `trackb-defender.json`, `trackb-identity.json` | the two optional extras (`scripts/extras-defender-sentinel.ps1:60#trackb-defender.json`, `scripts/extras-agent-identity.ps1:37#trackb-identity.json`) | the console reads the agent blueprint app id from the identity file (`console/e2e.py:901#trackb-identity.json`) |
| `params.<name>.json` | `New-ParamFile` (`scripts/deploy.ps1:63-71#New-ParamFile`) | `az deployment` reads it for every stage without a secret parameter; for `apps` it is an audit copy with `***` for the vendor key, and `az` reads `.secrets/params.apps.tmp.json`, which is deleted after the call |
| `deploy-state.json` | the orchestrator (4.9) | the orchestrator |

**Why files on disk.** Stages are separate processes that may run days apart, and several of them (Entra, ACR Tasks, azd, the SDK) are not ARM at all, so ARM outputs alone could not carry the hand-off. This is an inference from the design; the repo does not state a rationale.

**Trade-off / limitation.** State is local to the operator's machine. There is no remote state, no lock and no drift detection beyond Bicep's own idempotency, and `teardown.ps1 -CleanLocal` deletes it (4.10).

### 4.3 Bicep module map

**What this section proves.** Which file declares which resources, so a reader can find the definition behind any component in section 2.2. All stages deploy at resource-group scope except the policy definitions, which deploy at subscription scope (`infra/06a-policy-definitions.bicep:19#targetScope`); the budget declares RG scope explicitly (`infra/09-budget.bicep:8#targetScope`).

| File | Resources declared | Key declarations |
|---|---|---|
| `infra/01-network.bicep` | 14 private DNS zone names, the APIM NSG, NAT public IP and NAT gateway, the VNet with four inline subnets (Container Apps delegations on the agent and MCP subnets, a web-farm delegation on the APIM subnet), zones and VNet links (section 3.1, 3.2) | `infra/01-network.bicep:48-63#dnsZoneNames`, `infra/01-network.bicep:65#apimNsg`, `infra/01-network.bicep:117#natPip`, `infra/01-network.bicep:131#natGateway`, `infra/01-network.bicep:148#vnet`, `infra/01-network.bicep:164-171#delegations`, `infra/01-network.bicep:209-216#delegations`, `infra/01-network.bicep:223#zones`, `infra/01-network.bicep:229#zoneLinks` |
| `infra/02-foundry-rbac.bicep` | Foundry account and project as `existing`; Foundry User for the operator (account scope); Foundry Agent Consumer for the all-users group (project scope) | `infra/02-foundry-rbac.bicep:17#account`, `infra/02-foundry-rbac.bicep:26#raOperatorAccount`, `infra/02-foundry-rbac.bicep:36#raConsumersProject` |
| `infra/03-platform.bicep` | six UAMIs, Key Vault, ACR, Storage with four containers and a retention policy, Cosmos with a database and three containers, AI Search, four private endpoints, two Container Apps envs, the ACA private DNS zone, seven diagnostic settings, RBAC (section 5.6) | `infra/03-platform.bicep:74#uamis`, `infra/03-platform.bicep:81#kv`, `infra/03-platform.bicep:108#acr`, `infra/03-platform.bicep:122#st`, `infra/03-platform.bicep:195#wormPolicy`, `infra/03-platform.bicep:205#cosmos`, `infra/03-platform.bicep:302#search`, `infra/03-platform.bicep:324#peBlob`, `infra/03-platform.bicep:377#caePriv`, `infra/03-platform.bicep:399#caePub`, `infra/03-platform.bicep:417#acaDns`, `infra/03-platform.bicep:428#diagCaePriv` |
| `infra/04-apps.bicep` | the vendor key secret in Key Vault (created through ARM because the vault data plane is firewalled), six Container Apps from one module, outputs | `infra/04-apps.bicep:43#vendorKeySecret`, `infra/04-apps.bicep:86#research`, `infra/04-apps.bicep:131#privateMcp`, `infra/04-apps.bicep:146#legacy`, `infra/04-apps.bicep:166#vendor`, `infra/04-apps.bicep:191#apps`, `infra/04-apps.bicep:200#vendorKeySecretUri` |
| `infra/04b-seed-job.bicep` | the seed UAMI and its five grants, the manual Container Apps job in the internal env | `infra/04b-seed-job.bicep:45#seedId`, `infra/04b-seed-job.bicep:101#seedJob`, `infra/04b-seed-job.bicep:119#caePriv` |
| `infra/05-apim.bicep` | the APIM service, its private endpoint, the App Insights logger, diagnostics, four named values, the Key Vault role for APIM's identity, API Center with a workspace, env and source | `infra/05-apim.bicep:43#apim`, `infra/05-apim.bicep:65#apimPe`, `infra/05-apim.bicep:79#logger`, `infra/05-apim.bicep:154#apimDiag`, `infra/05-apim.bicep:179#nvTenant`, `infra/05-apim.bicep:225#raApimKv`, `infra/05-apim.bicep:236#apic`, `infra/05-apim.bicep:277#apicSource` |
| `infra/05-apim-apis.bicep` | the `servers` list (research, wall, actions, vendor), the vendor key named value, backends, one MCP-type API per server with its policy, the legacy API with policy and one subscription, the OAuth protected-resource discovery APIs | `infra/05-apim-apis.bicep:28#servers`, `infra/05-apim-apis.bicep:81#nvVendorKey`, `infra/05-apim-apis.bicep:94#backends`, `infra/05-apim-apis.bicep:123#mcpApis`, `infra/05-apim-apis.bicep:149#mcpPolicies`, `infra/05-apim-apis.bicep:169#legacyApi`, `infra/05-apim-apis.bicep:195#legacyPolicy`, `infra/05-apim-apis.bicep:204#legacySub`, `infra/05-apim-apis.bicep:216#prmApi`, `infra/05-apim-apis.bicep:238#prmPolicies` |
| `infra/06a-policy-definitions.bicep` | two custom policy definitions and the initiative of 19 references (4.7) | `infra/06a-policy-definitions.bicep:50#noKeyedConnections`, `infra/06a-policy-definitions.bicep:96#approvedMcpTargets`, `infra/06a-policy-definitions.bicep:168#initiative` |
| `infra/06-governance.bicep` | the Foundry guardrail (`raiPolicies`), six diagnostic settings, the policy assignment, `existing` references to connections, six exemptions (4.7) | `infra/06-governance.bicep:86#guardrails`, `infra/06-governance.bicep:102#diagFoundry`, `infra/06-governance.bicep:177#assignment`, `infra/06-governance.bicep:210#legacyConnAccount`, `infra/06-governance.bicep:232#exLegacyAccount`, `infra/06-governance.bicep:296#exPublicEnv` |
| `infra/06b-observability.bicep` | KQL functions as saved searches, Sentinel onboarding, nine analytics rules, an action group, three alert rules, the cockpit workbook (4.7) | `infra/06b-observability.bicep:43#functions`, `infra/06b-observability.bicep:60#sentinel`, `infra/06b-observability.bicep:67#analyticsRules`, `infra/06b-observability.bicep:109#opsActionGroup`, `infra/06b-observability.bicep:153#opsAlertRules`, `infra/06b-observability.bicep:193#cockpit` |
| `infra/07-jumpbox.bicep` | VNet and NAT gateway as `existing`; the jump subnet, its NSG, the NIC, the Windows VM, the auto-shutdown schedule, Bastion Developer (4.8) | `infra/07-jumpbox.bicep:77#vnet`, `infra/07-jumpbox.bicep:85#jumpNsg`, `infra/07-jumpbox.bicep:124#jumpSubnet`, `infra/07-jumpbox.bicep:153#vm`, `infra/07-jumpbox.bicep:211#autoShutdown`, `infra/07-jumpbox.bicep:230#bastion` |
| `infra/08-agent-frontdoor.bicep` | two named values (token quota, calls per minute), the agent front-door API, its operations and policy, on the existing APIM | `infra/08-agent-frontdoor.bicep:23#apim`, `infra/08-agent-frontdoor.bicep:27#nvQuota`, `infra/08-agent-frontdoor.bicep:38#nvRpm`, `infra/08-agent-frontdoor.bicep:49#api`, `infra/08-agent-frontdoor.bicep:76#policy` |
| `infra/09-budget.bicep` | one RG-scope budget of USD 1,200 a month with threshold notifications | `infra/09-budget.bicep:14#monthlyBudgetUsd`, `infra/09-budget.bicep:24#budget` |
| `infra/modules/pe.bicep` | one private endpoint and its DNS zone group, reused for every platform private endpoint | `infra/modules/pe.bicep:19#pe`, `infra/modules/pe.bicep:41#zoneGroup` |
| `infra/modules/aca-dns.bicep` | the private DNS zone of the internal Container Apps env, a wildcard and an apex A record, a VNet link | `infra/modules/aca-dns.bicep:18#zone`, `infra/modules/aca-dns.bicep:24#wildcard`, `infra/modules/aca-dns.bicep:37#apex`, `infra/modules/aca-dns.bicep:50#link` |
| `infra/modules/mcp-app.bicep` | one Container App: UAMI, ACR pull by identity, single revision, probes, scale | `infra/modules/mcp-app.bicep:24#containerApps`, `infra/modules/mcp-app.bicep:45-48#registries` |
| `infra/apim/policies/` (four XML files) | gateway policies: the MCP JWT policy, the legacy key policy, the protected-resource discovery policy, the agent front-door policy; loaded by the APIM templates, content in sections 6 and 7 | `infra/05-apim-apis.bicep:149#mcpPolicies`, `infra/05-apim-apis.bicep:195#legacyPolicy`, `infra/05-apim-apis.bicep:238#prmPolicies`, `infra/08-agent-frontdoor.bicep:76#policy` |

**The vendored Foundry template.** `infra/foundry/main.bicep` is the Azure-Samples private-network agent template, copied in and patched (`infra/foundry/PATCHES.md:3#foundry-samples`). The patches are a 4-character unique-suffix parameter, name overrides, the model deployment name, a public-access switch that defaults to Enabled, Open ingestion mode for the monitor private link scope, a Basic Search SKU and a Search location parameter that was added on build day because the primary region returned `InsufficientResourcesAvailable` (`infra/foundry/PATCHES.md:16-25#searchLocation`). It declares 18 modules:

| Module declaration | File under `modules-network-secured/` | Resources it declares | In this deployment |
|---|---|---|---|
| `infra/foundry/main.bicep:274#vnet` | `network-agent-vnet.bicep`, which calls `vnet.bicep` or `existing-vnet.bicep` | virtual network or subnet children; the existing-VNet path wires the agent and MCP subnets with the Container Apps delegation and the PE subnet without one (`infra/foundry/modules-network-secured/existing-vnet.bicep:68#agentSubnet`) | existing-VNet path (`infra/foundry/main.bicep:279#useExistingVnet`) |
| `infra/foundry/main.bicep:297#keyVault` | `key-vault.bicep` | `Microsoft.KeyVault/vaults` (`infra/foundry/modules-network-secured/key-vault.bicep:12#vaults`) | switched off by the stage (`scripts/deploy.ps1:265#enableKeyVault`) |
| `infra/foundry/main.bicep:309#aiAccount` | `ai-account-identity.bicep` | the Foundry account and the model deployment (`infra/foundry/modules-network-secured/ai-account-identity.bicep:23#accounts`, `infra/foundry/modules-network-secured/ai-account-identity.bicep:57#deployments`) | used |
| `infra/foundry/main.bicep:327#keyVaultRoleAssignment` | `key-vault-role-assignment.bicep` | a Key Vault role assignment, only `if (enableKeyVault)` | skipped |
| `infra/foundry/main.bicep:350#aiDependencies` | `standard-dependent-resources.bicep` | the agent-state Cosmos DB, AI Search and Storage, new or existing (`infra/foundry/modules-network-secured/standard-dependent-resources.bicep:40#DocumentDB`) | used, with the stage's name overrides (`scripts/deploy.ps1:245-250#asvcCosmos`) |
| `infra/foundry/main.bicep:388#privateEndpointAndDNS` | `private-endpoint-and-dns.bicep` | private endpoints and zone groups for the account and the three state stores; calls `private-dns-zone.bicep` per zone (`infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:272#private-dns-zone`) | reuses the zones the network stage created |
| `infra/foundry/main.bicep:418#acr` | `container-registry.bicep` | a registry and its private endpoint (`infra/foundry/modules-network-secured/container-registry.bicep:43#registries`) | switched off (`scripts/deploy.ps1:266#enableContainerRegistry`) |
| `infra/foundry/main.bicep:441#applicationInsights` | `application-insights.bicep` | the Log Analytics workspace, a workspace-based App Insights component, and an account connection to it (`infra/foundry/modules-network-secured/application-insights.bicep:57#connection`) | used; the platform stage only references the workspace |
| `infra/foundry/main.bicep:455#monitorPrivateLink` | `monitor-private-link-scope.bicep` | the private link scope, scoped resources, monitor DNS zones and a private endpoint (`infra/foundry/modules-network-secured/monitor-private-link-scope.bicep:59#privateLinkScopes`) | used, Open mode (`scripts/deploy.ps1:271#amplsIngestionAccessMode`) |
| `infra/foundry/main.bicep:476#aiProject` | `ai-project-identity.bicep` | the Foundry project and three project connections to the agent-state stores (Cosmos DB, Storage and AI Search, each with `authType` AAD) (`infra/foundry/modules-network-secured/ai-project-identity.bicep:37#projects`, `infra/foundry/modules-network-secured/ai-project-identity.bicep:49-89#AzureStorageAccount`) | used |
| `infra/foundry/main.bicep:504#formatProjectWorkspaceId` | `format-project-workspace-id.bicep` | no resource; formats an id | used |
| `infra/foundry/main.bicep:514#storageAccountRoleAssignment` | `azure-storage-account-role-assignment.bicep` | a Storage role assignment (`infra/foundry/modules-network-secured/azure-storage-account-role-assignment.bicep:16#roleAssignments`) | used |
| `infra/foundry/main.bicep:527#cosmosAccountRoleAssignments` | `cosmosdb-account-role-assignment.bicep` | a Cosmos account role assignment (`infra/foundry/modules-network-secured/cosmosdb-account-role-assignment.bicep:19#roleAssignments`) | used |
| `infra/foundry/main.bicep:540#aiSearchRoleAssignments` | `ai-search-role-assignments.bicep` | two Search role assignments (`infra/foundry/modules-network-secured/ai-search-role-assignments.bicep:20#roleAssignments`) | used |
| `infra/foundry/main.bicep:553#addProjectCapabilityHost` | `add-project-capability-host.bicep` | the Agent Service capability host (`infra/foundry/modules-network-secured/add-project-capability-host.bicep:22#capabilityHosts`) | used; deleted first on teardown (4.10) |
| `infra/foundry/main.bicep:572#storageContainersRoleAssignment` | `blob-storage-container-role-assignments.bicep` | container-scoped Storage role assignments (`infra/foundry/modules-network-secured/blob-storage-container-role-assignments.bicep:26#roleAssignments`) | used |
| `infra/foundry/main.bicep:587#cosmosContainerRoleAssignments` | `cosmos-container-role-assignments.bicep` | Cosmos data-plane role assignments (`infra/foundry/modules-network-secured/cosmos-container-role-assignments.bicep:24#sqlRoleAssignments`) | used |
| `infra/foundry/main.bicep:602#applicationInsightsRoleAssignment` | `application-insights-role-assignment.bicep` | an App Insights role assignment (`infra/foundry/modules-network-secured/application-insights-role-assignment.bicep:25#roleAssignments`) | used |

The role assignments inside the vendored modules are not audited line by line here; section 5.6 covers the repo's own assignments. Two `-unique` variants (`ai-project-identity-unique.bicep`, `blob-storage-container-role-assignments-unique.bicep`) are present but not referenced by `main.bicep`.

**What the foundry stage passes.** The stage sets the existing VNet id, the three subnet ids, the nine non-monitor and four monitor zone names (`scripts/deploy.ps1:259#existingVnetResourceId`), disables the template's Key Vault and registry (`scripts/deploy.ps1:265-266#enableKeyVault`), passes the account's public network access as Enabled explicitly (`scripts/deploy.ps1:267#foundryPublicNetworkAccess`; the patched template's own default is also Enabled, `infra/foundry/main.bicep:93#foundryPublicNetworkAccess`), sets monitor ingestion to Open (`scripts/deploy.ps1:271-272#disablePublicIngestion`) and sets Search to the Basic SKU with local auth disabled and an explicit location (`scripts/deploy.ps1:273-275#searchSkuName`). The model defaults are `gpt-5.4-mini`, version `2026-03-17`, `GlobalStandard`, capacity 100 (`scripts/deploy.ps1:251-256#GlobalStandard`).

**Why this shape.** Reusing the sample template keeps the network-injected Agent Service wiring as published instead of re-deriving it; the cost is a patched fork that has to be re-diffed against upstream when the sample changes (`infra/foundry/PATCHES.md:16-25#searchLocation`). The upstream sample and its account module default public access to Disabled (`infra/foundry/modules-network-secured/ai-account-identity.bicep:17#publicNetworkAccess`); this repo's patch makes the main template default to Enabled and the stage passes Enabled as well, which is why the policy exemption for the Foundry public endpoint exists (4.7).

### 4.4 Image build with ACR Tasks and the seed job

**What this section proves.** No container image is built on the operator's machine, and the synthetic data is loaded from inside the VNet because the data planes are private-endpoint-only.

**Image build.**

- `build-images.ps1` builds in ACR Tasks, so no local Docker is needed (`scripts/build-images.ps1:4#Docker`). Each build runs `az acr build` for `linux/amd64` against the source folder (`scripts/build-images.ps1:34#acr`).
- There is one MCP image, `abw-mcp`: the `MCP_SERVER` setting selects the tool set and authorization posture at start-up, so six servers are six deployments of one image (`scripts/build-images.ps1:7-10#MCP_SERVER`). The seed loader is a second image, `abw-seed` (`scripts/build-images.ps1:7-10#abw-seed`).
- The tag defaults to a timestamp, so every build is a new tag (`scripts/build-images.ps1:16-21#yyyyMMdd-HHmmss`). The tag is saved to `images.json` or `images-seed.json` (`scripts/build-images.ps1:41-42#builtAt`) and passed to the apps stage as `imageTag`.
- A known Windows CLI crash while streaming pip progress is avoided by forcing UTF-8 and not streaming logs, and when the CLI still exits non-zero the script checks the latest ACR run instead of failing blindly (`scripts/build-images.ps1:32-33#PYTHONUTF8`, `scripts/build-images.ps1:35-39#list-runs`).
- The image is `python:3.12-slim`, runs as a non-root user, listens on 8080 and starts uvicorn (`src/mcp/Dockerfile:1#slim`, `src/mcp/Dockerfile:6-12#appuser`, `src/mcp/Dockerfile:13#EXPOSE`, `src/mcp/Dockerfile:15#uvicorn`).
- Apps pull by managed identity, not by registry credential: each Container App names its UAMI in `registries`, and each UAMI has the AcrPull role (`infra/modules/mcp-app.bicep:45-48#registries`, `infra/03-platform.bicep:537#raAcrPull`).

**Platform behaviour.** `az acr build` is an ACR quick task: it sends the build context to the registry and builds there, with no local Docker Engine (https://learn.microsoft.com/azure/container-registry/container-registry-tasks-overview#quick-tasks).

**Why this shape.** ACR Tasks makes the build reproducible from any Windows laptop with only the Azure CLI, which is the prerequisite list in the README (`README.md:48#Docker`). The registry stays public so a laptop can push to it (section 3.7).

**The seed job.** The data planes are private-endpoint-only and the laptop has no stable egress address, so the stage loads data from a Container Apps job inside the VNet (`DESIGN.md:189#PE-only`).

1. `04b-seed-job.bicep` creates a dedicated UAMI `id-abw-seed-<region>-001` with AcrPull, Storage Blob Data Contributor, Search Service Contributor, Search Index Data Contributor and a Cosmos data-plane role (`infra/04b-seed-job.bicep:45#seedId`, `infra/04b-seed-job.bicep:51#raAcr`, `infra/04b-seed-job.bicep:61#raBlob`, `infra/04b-seed-job.bicep:71#raSearchSvc`, `infra/04b-seed-job.bicep:81#raSearchData`, `infra/04b-seed-job.bicep:91#cosmosSeed`).
2. The job is a `Microsoft.App/jobs` resource in the internal Container Apps env, with a manual trigger, a 900 s replica timeout and one retry (`infra/04b-seed-job.bicep:101#seedJob`, `infra/04b-seed-job.bicep:119#caePriv`, `infra/04b-seed-job.bicep:122-124#replicaTimeout`).
3. The stage deploys the template, starts the job with `az containerapp job start`, polls the execution every 15 s for up to 12 minutes, and throws unless the status is Succeeded (`scripts/deploy.ps1:422-426#containerapp`, `scripts/deploy.ps1:428-435#deadline`).
4. The loader is re-runnable: blobs are uploaded with overwrite, search documents with merge-or-upload, Cosmos items with upsert (`src/seed/seed.py:183#overwrite`, `src/seed/seed.py:194#merge_or_upload_documents`, `src/seed/seed.py:250#upsert_item`). `main` validates the data shapes first, then uploads blobs, syncs the search index and seeds Cosmos, and `--dry-run` runs without a credential (`src/seed/seed.py:274-281#validate_shapes`).

**Platform behaviour.** A Container Apps job with the Manual trigger runs on demand and stops when finished (https://learn.microsoft.com/azure/container-apps/jobs).

**Trade-off / limitation.** The seed stage has a hard 12-minute deadline and a single container retry; a slow private-endpoint DNS warm-up would surface as a failed stage rather than a longer wait (`scripts/deploy.ps1:428#deadline`). Re-running the stage is safe because of the upserts above.

### 4.5 Entra provisioning in sequence

**What this section proves.** Entra objects are created in two phases because the second phase needs Azure objects (the UAMI principal ids) that the first cannot know (`identity/Setup-Entra.ps1:261-262#platform`).

| Aspect | Phase 1 | Phase 2 |
|---|---|---|
| When | before any Azure resource that needs a group id or app id (step 2) | after the platform stage (step 9); re-run by `foundry-connections.ps1` |
| Needs | the Entra tenant only (`config.json`) | `entra.json` from Phase 1 and `platform.json` for the UAMI principal ids (`identity/Setup-Entra.ps1:259-262#entraStatePath`) |
| Creates | six security groups; five API apps with scopes and app roles; `abw-agent-client` and `abw-test-client`; tenant-wide consent grants; the persona users; direct user-to-role assignments | one federated identity credential per UAMI on the research, wall, actions and private apps; redirect URIs on `abw-agent-client` |
| Idempotency | find-or-create for every object; deterministic ids for scopes and roles; app PATCH on re-run; a secret is re-created only when missing or close to expiry | skip when the existing subject matches; delete and re-create when it differs |
| Writes | `entra.json` and the agent-client secret in the secrets folder | Entra changes only |
| Source | `identity/Setup-Entra.ps1:104#Invoke-Phase1`, `identity/Setup-Entra.ps1:253-254#entraStatePath` | `identity/Setup-Entra.ps1:258-286#Invoke-Phase2` |

**Phase 1 in order.**

1. Resolve the first-party OBO targets (Storage, Cosmos DB, AI Search) and their `user_impersonation` scope ids (`identity/Setup-Entra.ps1:90-100#Get-OboTargets`).
2. Create the six security groups, find-or-create (`identity/Setup-Entra.ps1:111-119#groups`).
3. For each of the five API apps: build scope and role definitions with deterministic ids from `New-DetGuid`, then POST the app or PATCH it if it exists; set the access-token version to 2; set `api://<app id>` as its identifier URI; ensure the service principal; and grant OBO consent to the Storage, Cosmos or Search service principal that the app needs (`identity/Setup-Entra.ps1:121-143#oauth2PermissionScopes`, `scripts/common.ps1:137-141#New-DetGuid`). App roles are for users only (`identity/Setup-Entra.ps1:125#allowedMemberTypes`).
4. Create `abw-agent-client` with a placeholder redirect URI and a client secret with an 80-day lifetime, saved to the secrets folder; the secret is re-created only when missing or when the stored one has fewer than 10 days left (`identity/Setup-Entra.ps1:150-156#abw-agent-client`, `identity/Setup-Entra.ps1:160-169#needSecret`).
5. Grant both client apps tenant-wide consent to all five API scopes (`identity/Setup-Entra.ps1:180-185#Ensure-Grant`, `identity/Setup-Entra.ps1:79-88#Ensure-Grant`) and pre-authorise the Azure CLI first-party app (a Microsoft public client whose well-known application id is held in `$azCliAppId`) on the APIs (`identity/Setup-Entra.ps1:189-196#preAuthorizedApplications`, `identity/Setup-Entra.ps1:190-190#azCliAppId`).
6. Create the persona users, put them in their groups, and assign app roles directly to each user (`identity/Setup-Entra.ps1:198-222#DisablePasswordExpiration`). Roles go to users, not groups, because group-based app-role assignment needs Entra ID P1 (`identity/Setup-Entra.ps1:7#P1`).
7. Save `entra.json` (`identity/Setup-Entra.ps1:253#entraStatePath`).

**Phase 2 in order.**

1. Read `entra.json` and `platform.json`; stop with "run Phase 1 first" or "deploy the platform first" if either is missing (`identity/Setup-Entra.ps1:259-262#platform`).
2. For the four apps whose servers do OBO (research, wall, actions, private), take the matching UAMI principal id and create a credential named `uami-<key>` with the Entra v2 issuer URL of the tenant, the subject set to that principal id and the `api://AzureADTokenExchange` token-exchange value (`identity/Setup-Entra.ps1:264-275#AzureADTokenExchange`, `identity/Setup-Entra.ps1:266#research`). The legacy and vendor UAMIs are not federated.
3. If a credential for that name already exists with the same subject, leave it; if the subject differs, delete it and create the new one (`identity/Setup-Entra.ps1:272-273#subject`).
4. If redirect URIs were supplied, merge them into the agent client's web redirect list, dropping the placeholder (`identity/Setup-Entra.ps1:278-284#abw-placeholder`). `foundry-connections.ps1` supplies them after it creates the connections (`scripts/foundry-connections.ps1:119-123#AgentClientRedirectUris`).

**Platform behaviour.** A federated identity credential that trusts a managed identity has the tenant's Entra v2 URL as issuer, the managed identity's principal (object) id as subject, and `api://AzureADTokenExchange` as the `aud` value; a mismatch is rejected with AADSTS70021 (https://learn.microsoft.com/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity). This is what makes on-behalf-of keyless: the container presents a UAMI-signed assertion instead of a client secret.

**Why this shape.** Phase 1 has no Azure dependency, so it can run first and give the later templates their group and app ids. Phase 2 cannot, because the subject of the credential is the UAMI's principal id. Splitting them keeps each phase single-purpose and re-runnable (`identity/Setup-Entra.ps1:1-14#Phase`).

**Trade-off / limitation.** Phase 2 replaces any credential whose subject differs (`identity/Setup-Entra.ps1:272-273#subject`). Because the app names and credential names are fixed, a second deployment in the same tenant takes the credentials over and breaks the first (section 13.4).

### 4.6 Foundry connections and agent creation

**What this section proves.** The tools an agent can use are Foundry project connections, and an agent version is a published record that binds a model, instructions, tools and an optional guardrail. Connections are created by the azd extension; agents by the Foundry SDK (`scripts/foundry-connections.ps1:59-66#specs`, `src/agent/abw_agents.py:155-194#create_version`).

**Why azd.** The rationale is not stated in the repo. The observable facts are these. The deployment scripts create the MCP connections only through the azd extension `azure.ai.connections` (`README.md:52#azd`, `README.md:94-95#extension`, `DESIGN.md:231#ARM-DELETE`). The script uses ARM only to read a connection back (GET) (`scripts/foundry-connections.ps1:68-75#Get-ConnectionArm`). Deleting a connection so that a stored consent can be reset is a manual `az rest` call that the README documents (`README.md:93#Force`), and the violation probe uses ARM PUT to attempt two connections that policy is meant to deny (`demo/try-violations.py:181#abw-try-keyed`, `demo/try-violations.py:197#abw-try-unapproved-mcp`, `demo/try-violations.py:321#requests.put`). No Bicep declares an MCP connection. Bicep declares only the three agent-state project connections in the vendored project module (`infra/foundry/modules-network-secured/ai-project-identity.bicep:49-89#AzureStorageAccount`) and the App Insights one (`infra/foundry/modules-network-secured/application-insights.bicep:57#connection`), and `06-governance.bicep` only references connections as `existing` (`infra/06-governance.bicep:210-229#legacyConnAccount`).

**The six connections** (one `azd ai connection create` each, kind `remote-tool`, `scripts/foundry-connections.ps1:85-97#azd`):

| Connection | Target | Auth | Scope or key | Notes |
|---|---|---|---|---|
| `mcp-research-oauth` | APIM research API | OAuth, user identity passthrough | research `Tools.Read` | consent once per user |
| `mcp-wall-oauth` | APIM wall API | OAuth, user identity passthrough | wall `Tools.Read` | consent once per user |
| `mcp-actions-oauth` | APIM actions API | OAuth, user identity passthrough | actions `Tools.Read` and `Tools.Execute` | `place_order` needs the second scope |
| `mcp-vendor-oauth` | APIM vendor API | OAuth, user identity passthrough | `vendorgw` `Tools.Read` | the gateway adds the vendor key |
| `mcp-private-oauth` | the internal Container App address, direct | OAuth, user identity passthrough | private `Tools.Read` | bypasses APIM (section 3.4) |
| `mcp-legacy-key` | APIM legacy API | custom keys | the APIM subscription key, read from APIM `listSecrets` | the deliberate counter-example |

Source: `scripts/foundry-connections.ps1:59-66#specs`, key handling `scripts/foundry-connections.ps1:91-95#custom-key`. Scopes are passed as arrays; a scalar triggered a scope error that the script now avoids (`scripts/foundry-connections.ps1:54-57#AADSTS650053`).

**Flow.**

1. Read `entra.json`, `apis.json`, `apps.json` and `foundry.json`; stop with a "run the earlier stages first" message if any is missing (`scripts/foundry-connections.ps1:39-43#Read-Json`).
2. Read the agent-client secret from the secrets folder and never print it (`scripts/foundry-connections.ps1:47-48#agent-client.json`).
3. For each connection, skip it if it already exists unless `-Force` or `-Only` is given (`scripts/foundry-connections.ps1:81-82#Force`).
4. Create it through azd; on failure the message has the secret and key replaced by placeholders (`scripts/foundry-connections.ps1:98-101#LASTEXITCODE`).
5. Read the stored connection back and write `connections.json` (`scripts/foundry-connections.ps1:116#connections.json`).
6. Collect each OAuth connection's redirect URL and, unless `-SkipEntraRedirects` is given, run Entra Phase 2 to register them on `abw-agent-client` (`scripts/foundry-connections.ps1:119-123#AgentClientRedirectUris`).

**Consent and reset.** Each persona must consent once per OAuth connection, which is five consents (`DESIGN.md:155#consent`). `-Force` does not reset a stored consent: delete the connection with the manual `az rest` call in the README and re-run with `-Only <name>` (`README.md:93#Force`, `DESIGN.md:231#ARM-DELETE`). Consent needs the operator's browser (`README.md:99#BROWSER`). The persona baseline must be applied before consenting (`README.md:92#Baseline`). The orchestrator gives azd its own config folder under the secrets folder unless `AZD_CONFIG_DIR` is already set, so a sign-in to another tenant does not interfere (`docs/SELF-DEPLOY.md:176#azd`, `scripts/Deploy-AgentWall.ps1:387#AZD_CONFIG_DIR`); on the manual path the README tells the operator to do the same when azd is signed in elsewhere (`README.md:94-95#AZD_CONFIG_DIR`).

**Agents.** `create_agents.py` publishes agents through the project endpoint with an Azure CLI credential (`src/agent/create_agents.py:34#AzureCliCredential`, `src/agent/create_agents.py:40#agents.json`). Every call creates a new version of the named agent (`src/agent/abw_agents.py:155-194#create_version`).

| Agent | Published by | Tools | Guardrail | Purpose |
|---|---|---|---|---|
| `abw-poc-legacy` | `src/agent/abw_agents.py:159-165#poc` | the legacy server through `mcp-legacy-key`, no tool filter, no approvals (`src/agent/abw_agents.py:142-152#poc_tools`) | none | the typical POC with a shared key |
| `abw-wall-desk` | `src/agent/abw_agents.py:170-176#wall` | one `MCPTool` per server in `WALL_DESK_TOOLS` with `project_connection_id` `mcp-<server>-oauth`, an `allowed_tools` list, and approval required for `place_order` (`src/agent/abw_agents.py:42-49#WALL_DESK_TOOLS`, `src/agent/abw_agents.py:119-139#wall_desk_tools`) | attached only on the `--rai` run (`src/agent/abw_agents.py:167-169#guard_kwargs`) | the governed agent |
| `abw-wall-desk-redteam` | `src/agent/abw_agents.py:178-184#red` | same tools and passthrough, prompt safety removed | none | red-team baseline |
| `abw-wall-desk-redteam-shielded` | `src/agent/abw_agents.py:186-193#shielded`, only when a guardrail is supplied | same as the red-team build | the Foundry guardrail | red team plus guardrail |

The first run without `--rai` therefore publishes 3 agents; the `--rai abw-agent-guardrails` run after governance adds the guardrail to the governed agent and creates the shielded one, which makes 4 (`src/agent/create_agents.py:30#rai`). The README quickstart says "4 agents" for the first run (`README.md:79#agents`; see Findings in section 13).

**The guardrail step.** The guardrail is a `raiPolicies` resource created by the governance template (`infra/06-governance.bicep:86-99#guardrails`). The SDK needs its fully qualified id, so a bare name is rejected and the id is built from `foundry.json` (`src/agent/abw_agents.py:83-87#rai_policy_id`). It is a preview feature that the template itself calls best effort, with the deterministic control being the wall (`infra/06-governance.bicep:72-76#Preview`), and it fires intermittently (`README.md:98#guardrail`).

**Trade-off / limitation.** Connection creation is not declarative: it cannot be what-if'd, it depends on an azd extension install and sign-in, and a stored consent survives `-Force`. These are why the README lists two azd gotchas (`README.md:93-95#Force`).

### 4.7 Governance stage

**What this section proves.** The governance stage turns the platform's design rules into Azure Policy at resource-group scope, adds the Foundry guardrail, and then deploys the observability pack that makes denials and anomalies visible (`scripts/deploy.ps1:439-451#governance`).

**Sequence.**

1. Build the three observability artefacts (KQL function pack, Sentinel rules, workbook JSON) with the repo's Python builders (`scripts/deploy.ps1:152-158#Build-ObservabilityArtifacts`).
2. Deploy `06a-policy-definitions.bicep` at subscription scope and save `policy.json` (`scripts/deploy.ps1:443#policy-defs`).
3. Deploy `06-governance.bicep` at RG scope with the names, the initiative id and the legacy waiver expiry, computed as 90 days from the run (`scripts/deploy.ps1:448#governance`).
4. Deploy `06b-observability.bicep`. If it fails, wait 120 s and retry once, because Sentinel validates analytics rules against workspace functions that take minutes to become resolvable (`scripts/deploy.ps1:160-176#Invoke-ObservabilityStage`).

#### 4.7.1 Policy definitions and the initiative

Two custom definitions are combined with 16 distinct built-in definitions (`infra/06a-policy-definitions.bicep:21-38#builtin`). The prompt-filter built-in is referenced twice, so the initiative holds 17 built-in references and 2 custom ones (`infra/06a-policy-definitions.bicep:329#promptFilters`, `infra/06a-policy-definitions.bicep:340#promptFilters`).

| Custom definition | Rule | Effect |
|---|---|---|
| `abw-foundry-no-keyed-connections` | a Foundry account or project connection whose `authType` is one of ApiKey, CustomKeys, AccessKey, AccountKey, SAS, PAT, UsernamePassword, ServicePrincipal | parameter Audit, Deny or Disabled, default Deny (`infra/06a-policy-definitions.bicep:50-91#noKeyedConnections`, `infra/06a-policy-definitions.bicep:40#keyedAuthTypes`) |
| `abw-foundry-approved-mcp-targets` | a connection whose category is in `connectionCategories` (default `RemoteTool`) and whose `target` matches none of the approved URL patterns (`like`, one wildcard) | default Deny (`infra/06a-policy-definitions.bicep:96-163#approvedMcpTargets`) |

The initiative `abw-agent-platform-controls` groups 19 policy references into five control groups (`infra/06a-policy-definitions.bicep:168#initiative`, groups at `infra/06a-policy-definitions.bicep:214-220#ABW-01`). Its description says "twelve-control baseline" (`infra/06a-policy-definitions.bicep:172#twelve-control`); the references number 19 (see Findings in section 13).

| Group | References (policy reference ids) | Effect as assigned |
|---|---|---|
| ABW-01 no keys | `ai-local-auth-disabled`, `storage-shared-key-disabled`, `cosmos-local-auth-disabled`, `search-local-auth-disabled`, `keyvault-rbac`, the container-registry built-in-user-disabled reference, `foundry-no-keyed-connections` (custom) | Deny, 7 of 7 (`infra/06a-policy-definitions.bicep:224-262#ai-local-auth-disabled`) |
| ABW-02 network exposure | `ai-restrict-network` (Audit), `cosmos-no-public`, `storage-no-public`, `search-no-public` (Deny), `aca-env-no-public` (Audit) | 3 Deny, 2 Audit (`infra/06a-policy-definitions.bicep:267-297#ai-restrict-network`) |
| ABW-03 tools, targets, models | `foundry-approved-tools`, `foundry-approved-models` (Audit, preview), `foundry-approved-mcp-targets` (Deny, custom) | 1 Deny, 2 Audit (`infra/06a-policy-definitions.bicep:298-327#foundry-approved-tools`) |
| ABW-04 guardrails | `agent-guardrail-jailbreak`, `agent-guardrail-indirect-attack` | Audit, preview (`infra/06a-policy-definitions.bicep:328-350#agent-guardrail-jailbreak`) |
| ABW-05 hygiene | `aca-managed-identity`, `aca-https-only` | Audit (`infra/06a-policy-definitions.bicep:351-364#aca-managed-identity`) |

So 11 references deny and 8 audit. The Foundry data-plane policies are compliance-reporting only, because create-time Deny is not enforced for them, which is why the tools and models references are Audit (`DESIGN.md:230#Audit`, `infra/06-governance.bicep:25#agentToolEffect`).

#### 4.7.2 Assignment and exemptions

The assignment `abw-agent-platform-controls` is scoped to the resource group only, with `enforcementMode` Default (`infra/06-governance.bicep:177-206#assignment`, `infra/06-governance.bicep:183#enforcementMode`). Its parameters are `denyEffect` (Deny), `auditEffect` (Audit), `toolsEffect` (Audit), the approved MCP endpoint list, an empty approved tool-type list, and `allowedModelPublishers` limited to OpenAI (`infra/06-governance.bicep:185-190#allowedModelPublishers`). It carries 11 non-compliance messages (`infra/06-governance.bicep:192-204#nonComplianceMessages`). The approved endpoints are the four gateway paths for research, wall, actions and vendor plus the private app's address; `/legacy/*` is absent, so the legacy connection is covered by the waiver below instead (`infra/06-governance.bicep:162-168#approvedMcpEndpoints`).

| Exemption | Category | Exempts | Scope | Stated reason |
|---|---|---|---|---|
| `abw-ex-legacy-key-account`, `abw-ex-legacy-key-project` | Waiver | no-keyed-connections and approved-mcp-targets | the `mcp-legacy-key` connection | the POC counter-example; expires on `legacyWaiverExpiry`, which the script sets 90 days after the stage runs (`scripts/deploy.ps1:448#legacyWaiverExpiry`, `infra/06-governance.bicep:28#legacyWaiverExpiry`, `infra/06-governance.bicep:232-259#exLegacyAccount`) |
| `abw-ex-appinsights-ingestion-key-account`, `abw-ex-appinsights-ingestion-key-project` | Mitigated | no-keyed-connections | the Foundry App Insights connection | ingestion uses a connection string (`infra/06-governance.bicep:260-283#exAppiAccount`) |
| `abw-ex-foundry-public-endpoint` | Mitigated | ai-restrict-network | the Foundry account | operator laptop access (`infra/06-governance.bicep:284-295#exFoundryNetwork`) |
| `abw-ex-public-saas-simulator` | Waiver | aca-env-no-public | the public Container Apps env | the simulated third-party market-data vendor sits outside the private network by design (`infra/06-governance.bicep:296-307#exPublicEnv`) |

**Platform behaviour.** Policy effects evaluate in a fixed order: disabled, then append and modify, then deny, then audit (https://learn.microsoft.com/azure/governance/policy/concepts/effect-basics#order-of-evaluation). An organisation baseline at tenant-root management group that runs Modify effects can therefore change a request before this initiative's Deny sees it (`README.md:97#Modify`).

**Trade-off / limitation.** The legacy waiver is time-boxed: the governance stage passes an expiry 90 days after the stage runs, so each run restarts the clock, and once it lapses the legacy connection is evaluated against its Deny controls again (`scripts/deploy.ps1:448#legacyWaiverExpiry`, `infra/06-governance.bicep:28#legacyWaiverExpiry`). The Bicep default, `2026-11-30T00:00:00Z`, applies to a direct template deployment and to any deployment made by a version of the script that did not pass the value (Implemented). The exemption text says the public Container Apps env hosts the simulated vendor and the legacy POC server, but the legacy server is deployed in the internal env (`infra/06-governance.bicep:304#legacy`, `infra/04-apps.bicep:146-153#legacy`; see Findings in section 13).

#### 4.7.3 The Foundry guardrail resource

`06-governance.bicep` creates a `raiPolicies` resource (API version `2026-07-15-preview`) on the Foundry account: base policy `Microsoft.DefaultV2`, blocking mode, with 12 content filters (`infra/06-governance.bicep:77-99#harmFilters`). Eight are the four harm categories Hate, Sexual, Violence and Selfharm at the Medium threshold, each blocking, on both the prompt and the completion (`infra/06-governance.bicep:77-85#harmCategories`). The other four are Jailbreak and Indirect Attack on the prompt and Indirect Attack on the tool response (source `PostToolCall`), all blocking, and Protected Material Text on the completion, which does not block (`infra/06-governance.bicep:93-96#Jailbreak`). It is attached to agents by `create_agents.py --rai` (4.6).

#### 4.7.4 Observability artefacts

| Artefact | What is deployed | Source |
|---|---|---|
| KQL functions | 10 saved searches: AbwAgentActivity, AbwDenials, AbwFullChain, AbwFullChainCore, AbwGateway, AbwIdentityChain, AbwMcpAudit, AbwTokenUsage, AbwUsageByUser, AbwZeroKeys; deployed one at a time | `infra/06b-observability.bicep:42-57#savedSearches`, `observability/kql/pack.py:52#load_pack` |
| Sentinel | workspace onboarding plus 9 analytics rules (table below) | `infra/06b-observability.bicep:60-64#sentinel`, `infra/06b-observability.bicep:67-106#analyticsRules` |
| Alerts | an action group and three scheduled-query alerts: `mcp-server-errors` (severity 2), `gateway-backend-errors` (severity 2, threshold 2), `agent-run-failures` (severity 3). The first one counts audit events whose decision is `error`, but the tool servers record only allow or deny, so as built it cannot fire (section 8.5.6) | `infra/06b-observability.bicep:126-151#opsAlerts`, `infra/06b-observability.bicep:153-188#PT5M`, `infra/06b-observability.bicep:126-134#mcp-server-errors` |
| Cockpit workbook | one workbook of 8 tabs, generated by a builder | `observability/workbook/build_workbook.py:645#TABS`, `infra/06b-observability.bicep:193#cockpit` |
| Optional Entra link | a read-only reference to an Entra sign-in export workspace; that export is not in this repo | `infra/06b-observability.bicep:27#entraWorkspaceId` |

The `AbwDenials` function covers defence layers 0-3 only, so Entra-side refusals are not in it (section 13.3).

| Rule | Detects | Severity | Source |
|---|---|---|---|
| ABW-001 | information-barrier violation attempt on the Wall MCP | High | `observability/sentinel/rules.json:4-5#ABW-001` |
| ABW-002 | order blocked on a restricted-list instrument | High | `observability/sentinel/rules.json:39-40#ABW-002` |
| ABW-003 | tool call on the legacy shared-key path with no user identity | Medium | `observability/sentinel/rules.json:73-74#ABW-003` |
| ABW-004 | gateway rejected a token from an unapproved client app | High | `observability/sentinel/rules.json:103-104#ABW-004` |
| ABW-005 | revoked principal still calling the MCP APIs | High | `observability/sentinel/rules.json:141-142#ABW-005` |
| ABW-006 | repeated denials for one identity across defence layers | Medium | `observability/sentinel/rules.json:169-170#ABW-006` |
| ABW-007 | entitlement drift: gateway and MCP allowed, storage RBAC denied | High | `observability/sentinel/rules.json:199-200#ABW-007` |
| ABW-008 | Foundry guardrail stopped an agent run | High | `observability/sentinel/rules.json:229-230#ABW-008` |
| ABW-009 | burst of throttled MCP calls from one identity | Low | `observability/sentinel/rules.json:259-260#ABW-009` |

**Why this shape.** Governance and observability share one stage because the rules and alerts depend on the policy and diagnostics the governance template creates, and the retry exists because the workspace functions are not immediately resolvable (`scripts/deploy.ps1:160-161#Sentinel`).

### 4.8 Jump box and console deployment path

**What this section proves.** The jump box exists because every data plane is private-endpoint-only, so the portal's data pages cannot load from a laptop, and the demo console runs on that VM rather than as a hosted app (`scripts/jumpbox.ps1:7-10#private`, `scripts/jumpbox-console.ps1:7-10#127.0.0.1`). Section 3.9 covers what it is; this section covers how it is deployed.

**Jump box (`scripts/jumpbox.ps1`).**

1. It requires the VNet and NAT gateway from the network stage, otherwise it tells the operator to run that stage (`scripts/jumpbox.ps1:236-241#network`).
2. It registers `Microsoft.Compute` and `Microsoft.DevTestLab` (`scripts/jumpbox.ps1:242-243#DevTestLab`).
3. An existing VM is left alone without `-Force`: the script reports that the template is not re-applied, starts the VM if it is stopped and only runs the verification. With `-Force` it re-applies the template, and then, if the VM exists but its credential file is missing, it stops rather than guess the password (`scripts/jumpbox.ps1:247-256#Force`).
4. It generates a local password if none exists and keeps it in the secrets folder. The audit copy of the parameters in the generated folder has no password, and the temporary parameter file with the secret is deleted in a `finally` block (`scripts/jumpbox.ps1:258-263#New-JumpPassword`, `scripts/jumpbox.ps1:166-227#Invoke-JumpDeploy`).
5. It tries VM sizes in order, `Standard_D2as_v7`, `Standard_D2s_v7`, `Standard_D2ads_v7`. A size or quota error deletes the half-created VM and tries the next size; a Bastion-only failure redeploys without Bastion (`scripts/jumpbox.ps1:64#sizeOrder`, `scripts/jumpbox.ps1:221-222#sizeProblem`, `scripts/jumpbox.ps1:269-286#bastionOnly`).
6. It writes `jumpbox.json`, then runs a read-only verification inside the VM through run-command. The check confirms that the data-plane hosts resolve to private-endpoint addresses and answer on 443, that the portal, sign-in and registry hosts answer through the NAT gateway, that the VM's egress address matches the NAT gateway's public address, and that RDP is listening for Bastion. The result is saved to `jumpbox.json` without secrets (`scripts/jumpbox.ps1:67-75#privateHosts`, `scripts/jumpbox.ps1:289-302#passwordFile`, `scripts/jumpbox.ps1:307#Invoke-JumpVerify`, `scripts/jumpbox.ps1:361-366#Write-Check`, `scripts/jumpbox.ps1:382-383#Update-State`).
7. Day-to-day: `-Start`, `-Stop` and `-Remove` (`scripts/jumpbox.ps1:389#Start-Jump`, `scripts/jumpbox.ps1:412#Stop-Jump`, `scripts/jumpbox.ps1:468-498#Invoke-Remove`). `Start-JumpBox.bat` starts the VM, opens the portal and copies the password (`Start-JumpBox.bat:17#jumpbox.ps1`). Auto-shutdown at 03:00 Central is declared in the template (`infra/07-jumpbox.bicep:211#autoShutdown`).

**Console (`scripts/jumpbox-console.ps1`).** The console is a local app bound to 127.0.0.1 that uses the operator's `az` sign-in, so it runs on the VM; hosting it as a Container App would need a second identity model (`scripts/jumpbox-console.ps1:7-10#127.0.0.1`).

1. **Package.** It builds a package from a whitelist and never includes the secrets folder, the legacy key, raw evidence, the deck or the docs, then scans every file for secret patterns and for every secret value held in memory (`scripts/jumpbox-console.ps1:30-33#whitelist`, `scripts/jumpbox-console.ps1:241-269#Test-StageSafety`).
2. **Upload.** The package is base64-chunked at 140,000 characters per run-command call, under the run-command size limit (`scripts/jumpbox-console.ps1:70#chunkChars`). It is sent when `-Force` is given, when the VM records no content hash, when the recorded hash differs from the local one, or when the VM reports missing files (`scripts/jumpbox-console.ps1:643#needPackage`). Otherwise the script reports that the VM already has the exact package and skips the upload (`scripts/jumpbox-console.ps1:662-667#Force`).
3. **Setup on the VM.** `jumpbox-console-setup.ps1` runs inside the VM as SYSTEM, once per phase, and returns one JSON line; details go to a log file because run-command keeps only the last 4 KB (`scripts/jumpbox-console-setup.ps1:1-19#placeholders`). The phases are probe, tools, package, venv, launcher, verify, personas, personas-remove and remove, and each can be repeated (`scripts/jumpbox-console-setup.ps1:7-19#probe`).
4. **Tools.** Python, Azure CLI and PowerShell are installed from fixed versions and URLs with signature checks (`scripts/jumpbox-console.ps1:73-79#tools`).
5. **Launcher.** It creates the "ABW Demo Console" desktop shortcut, portal and Foundry shortcuts and a readme, and locks the VM's secrets folder to SYSTEM and the local account (`scripts/jumpbox-console-setup.ps1:424-452#Invoke-Launcher`).
6. **Personas.** Persona sign-in files are copied only with `-IncludePersonaFiles` and can be removed with `-RemovePersonaFiles` (`scripts/jumpbox-console.ps1:15-28#IncludePersonaFiles`).
7. **Not automated.** The Bastion browser session and the one-time Azure sign-in on the VM (device code) are done by the operator (`scripts/jumpbox-console.ps1:35-37#Bastion`).

Run-command calls make up to 8 attempts and wait 8 s times the attempt number after each failure, so the waits grow from 8 s to 56 s (`scripts/jumpbox-console.ps1:410#Invoke-Retry`, `scripts/common.ps1:120#Start-Sleep`); the jump box verification uses the same setting (`scripts/jumpbox.ps1:317#Invoke-Retry`). The setup script is refused if it contains non-ASCII text (`scripts/jumpbox-console.ps1:431-454#Send-Setup`). Other modes are `-Status`, `-Verify` and `-Remove` (`scripts/jumpbox-console.ps1:727#Invoke-StatusMode`, `scripts/jumpbox-console.ps1:745#Invoke-VerifyMode`, `scripts/jumpbox-console.ps1:764#Invoke-RemoveConsole`). `Deploy-JumpBox-Console.bat` is a launcher for it (`Deploy-JumpBox-Console.bat:19#jumpbox-console`).

**Trade-off / limitation.** The jump box has a local account with a generated password rather than a managed identity, and the header of the jump box template overstates how private the platform is (see Findings in section 13). Cost is about USD 4.4 a day while running (`docs/COST.md:30#jump`).

### 4.9 One-command deployment orchestrator

**What this section proves.** A colleague who has Owner on a subscription and Entra rights in a tenant can deploy the whole solution (Entra objects, network, Foundry, platform, six MCP Container Apps, API Management, Foundry connections and agents, the policy initiative, Sentinel rules, the KQL pack and workbook, Front Door, budget, jump box and the demo console) with one resumable command. `-CheckOnly` shows what would happen first and changes nothing. The decision logic (plan resolution, done-detection, configuration freeze, guards, retries, exit codes, verification) is covered by an offline test of 178 checks that mocks `az`, `azd` and Graph and runs the stage script `deploy.ps1` as a child process against a fake `az`. A live deployment into a second tenant has not been run; section 4.9.10 says exactly what the test does and does not prove.

Provenance: **Implemented**. The orchestrator is a single script, `scripts/Deploy-AgentWall.ps1:95-96#CmdletBinding` (1,463 lines), tested by `scripts/Test-DeployOrchestrator.ps1:37-53#Assert-That` (929 lines). The operator guide is `docs/SELF-DEPLOY.md`; this section is the design reference behind it.

Diagram: `docs/diagrams/10-deployment-pipeline.excalidraw`

#### 4.9.1 Contract: what one command does

| Claim | Value | Citation |
|---|---|---|
| Runtime | PowerShell 7 or later; Windows only (the guard in 4.9.3 blocks anything else) | `scripts/Deploy-AgentWall.ps1:1-3#requires` |
| Purpose | One-command, resumable deployment of the whole solution | `scripts/Deploy-AgentWall.ps1:3-9#SYNOPSIS` |
| Resume | Progress is remembered in `infra/generated/deploy-state.json`; a second run skips finished steps | `scripts/Deploy-AgentWall.ps1:6-9#deploy-state.json` |
| Default scope | Everything: Entra apps, groups and five persona users; network; Foundry; platform; six MCP Container Apps; APIM; Foundry connections and agents; the Azure Policy initiative; Sentinel rules, KQL pack and workbook; Front Door; budget; jump box and demo console | `scripts/Deploy-AgentWall.ps1:11-14#everything` |
| Read-only mode | `-CheckOnly` is strictly read-only; loading the shared helpers creates only the two empty git-ignored folders `infra/generated` and `.secrets` | `scripts/Deploy-AgentWall.ps1:17-18#CheckOnly` |
| Prerequisites | Windows, PowerShell 7, Azure CLI 2.61+, Python 3.11+, azd, Owner on the subscription, Entra rights (Global Administrator) | `scripts/Deploy-AgentWall.ps1:20-21#Owner` |
| Scope limit | One deployment per Entra tenant and per Azure subscription: the Entra objects are tenant-wide with fixed `abw-*` names and the policy initiative `abw-agent-platform-controls` is per subscription | `scripts/Deploy-AgentWall.ps1:23-24#abw-agent-platform-controls` |
| Exit codes | 0 done, 1 a required step failed or a blocking problem was found, 2 done but an optional step failed, 3 `-CheckOnly` found a blocking problem | `scripts/Deploy-AgentWall.ps1:26-27#Exit` |

Why one orchestrator on top of `scripts/deploy.ps1`: the stage script is a dispatcher with a `-Stage` switch and no memory of what already ran (`scripts/deploy.ps1:32#ValidateSet`). The orchestrator adds the plan, the state file, the guards, the retries and the verification, and calls the stage script once per step.

How the exit codes are produced:

| Code | When | Citation |
|---|---|---|
| 0 | Every planned step finished and no optional step failed; or nothing was left to run; or `-CheckOnly` found the environment ready. Failed verification checks only warn and do not change the code | `scripts/Deploy-AgentWall.ps1:1432-1447#ExitCode` |
| 1 | A required step failed; a blocker was found in a real run; the typed confirmation was not given; an unhandled error was caught (an `ERROR:` line, GUIDs masked) | `scripts/Deploy-AgentWall.ps1:1424-1430#ExitCode` |
| 2 | All required steps finished but at least one optional step failed or was skipped for a missing input | `scripts/Deploy-AgentWall.ps1:1435-1438#ExitCode` |
| 3 | `-CheckOnly` found a blocker (a real run exits 1 for the same blocker) | `scripts/Deploy-AgentWall.ps1:1245-1252#Complete-Blocked` |

The entry guard runs the main routine only when the file is executed, not when it is dot-sourced, which is what lets the offline test load every function without deploying anything: `scripts/Deploy-AgentWall.ps1:1449-1463#InvocationName`.

Shape of a run:

```
-CheckOnly                                         real run
----------                                         --------
prereqs -> sign-in -> config -> guards ---------+-- same checks, then:
plan + impact (read-only)                       |
   |                                            +-> typed confirmation -> run steps (sequential)
   v                                                   -> verify (read-only) -> next steps
result: exit 0 (ready) or 3 (blocked)               exit 0, 1 or 2
```

`-CheckOnly` against a finished deployment has one extra effect: when nothing is left to run it executes the verification checks of section 4.9.7 (up to 12), which makes it a read-only health check: `scripts/Deploy-AgentWall.ps1:1342-1348#CheckOnly`.

#### 4.9.2 Options, run context and configuration

**Options.** The script has 34 options in seven groups. Every option is a script parameter with a default, and every parameter is documented in the comment-based help (the offline test enforces both).

| Group | Options | Citation |
|---|---|---|
| Target (4) | `-SubscriptionId`, `-TenantId`, `-Location`, `-SearchLocation` | `scripts/Deploy-AgentWall.ps1:97-100#SubscriptionId` |
| Naming (5) | `-Workload`, `-EnvName`, `-Instance`, `-UniqueSuffix`, `-ResourceGroupName` | `scripts/Deploy-AgentWall.ps1:101-105#Workload` |
| Contacts and optional wiring (4) | `-AlertEmail`, `-PublisherEmail`, `-EntraWorkspaceId`, `-TenantDomain` | `scripts/Deploy-AgentWall.ps1:106-109#AlertEmail` |
| Model (4) | `-ModelName`, `-ModelVersion`, `-ModelSku`, `-ModelCapacity` | `scripts/Deploy-AgentWall.ps1:110-113#ModelName` |
| Scope switches (7) | `-SkipJumpBox`, `-SkipConsole`, `-SkipFrontDoor`, `-SkipBudget`, `-SkipGuardrail`, `-WithExtras`, `-RunProofs` | `scripts/Deploy-AgentWall.ps1:114-120#SkipJumpBox` |
| Run control (6) | `-CheckOnly` (alias `-DryRun`), `-Yes`, `-Force`, `-ResetState`, `-AdoptExistingEntra`, `-InstallPrereqs` | `scripts/Deploy-AgentWall.ps1:121-126#CheckOnly` |
| Step selection (4) | `-From`, `-Only`, `-Until`, `-Skip` (comma separated lists accepted) | `scripts/Deploy-AgentWall.ps1:127-130#Until` |

Options with a default or a validation rule:

| Option | Default | Validation | Citation |
|---|---|---|---|
| `-SubscriptionId` | the current `az` default subscription | none | `scripts/Deploy-AgentWall.ps1:29-83#SubscriptionId` |
| `-Location` | `eastus2` | none | `scripts/Deploy-AgentWall.ps1:99#Location` |
| `-Workload` | `abw` | pattern `^[a-z0-9]{3,5}$` | `scripts/Deploy-AgentWall.ps1:101#Workload` |
| `-EnvName` | `demo` | pattern of 2 to 5 characters | `scripts/Deploy-AgentWall.ps1:102#EnvName` |
| `-Instance` | `001` | pattern `^[0-9]{3}$` | `scripts/Deploy-AgentWall.ps1:103#Instance` |
| `-UniqueSuffix` | 4 random lowercase letters or digits | pattern `^[a-z0-9]{4}$` | `scripts/Deploy-AgentWall.ps1:104#UniqueSuffix` |
| `-ModelName` | `gpt-5.4-mini` | none | `scripts/Deploy-AgentWall.ps1:110#ModelName` |
| `-ModelVersion` | `2026-03-17` | none | `scripts/Deploy-AgentWall.ps1:111#ModelVersion` |
| `-ModelSku` | `GlobalStandard` | none | `scripts/Deploy-AgentWall.ps1:112#ModelSku` |
| `-ModelCapacity` | `100` (thousand tokens per minute) | range 1 to 100000 | `scripts/Deploy-AgentWall.ps1:113#ModelCapacity` |

**Run context.** `Get-DefaultOptions` supplies the defaults and `New-RunContext` turns the parameters into one context object: comma lists are flattened, the same `pwsh` that runs the orchestrator is reused for every child script, and the repo-local `.venv` Python is the interpreter for Python steps (`scripts/Deploy-AgentWall.ps1:184-194#Get-DefaultOptions`, `scripts/Deploy-AgentWall.ps1:196-219#New-RunContext`).

**Names.** The resource group default is `rg-<workload>-<env>-<region code>-<instance>`. The region code comes from a table of 18 regions (`eastus2` -> `eus2`, `westeurope` -> `weu`, and so on); an unknown region falls back to its first four letters. The unique suffix is four random characters from `a-z0-9` drawn from a cryptographic generator. Generated names are checked against the Azure naming rules and reported when too long or when they contain upper-case characters (`scripts/Deploy-AgentWall.ps1:139-144#RegionCodes`, `scripts/Deploy-AgentWall.ps1:221-226#Get-RegionCode`, `scripts/Deploy-AgentWall.ps1:228-231#New-UniqueSuffix`, `scripts/Deploy-AgentWall.ps1:233-259#Test-AbwNameRules`).

**Configuration object.** The first run writes `infra/generated/config.json`; every stage script reads it through `Get-AbwConfig` and derives all resource names from it through `Get-AbwNames` (`scripts/common.ps1:29-59#Get-AbwConfig`, `scripts/common.ps1:147-183#Get-AbwNames`).

| Key | Value and source | Citation |
|---|---|---|
| `tenantId`, `subscriptionId` | the signed-in context | `scripts/Deploy-AgentWall.ps1:794-832#New-ConfigObject` |
| `tenantDomain` | `-TenantDomain`; else the tenant's initial `*.onmicrosoft.com` domain read from Graph; else the sign-in domain (a note is printed) | `scripts/Deploy-AgentWall.ps1:785-792#Get-InitialDomain` |
| `location`, `searchLocation` | `-Location`; the Search region is `-SearchLocation`, else `eastus` when the location is `eastus2`, else the location | `scripts/Deploy-AgentWall.ps1:794-832#searchLocation` |
| `workload`, `env`, `regionCode`, `instance`, `u4` | options, region code, suffix | `scripts/Deploy-AgentWall.ps1:794-832#regionCode` |
| `rgName` | `-ResourceGroupName`, else the default pattern above | `scripts/Deploy-AgentWall.ps1:794-832#rgName` |
| `operatorUpn`, `operatorOid` | the signed-in user | `scripts/Deploy-AgentWall.ps1:794-832#operatorUpn` |
| `tags` | workload, env, owner (UPN local part, sanitised), purpose, data (`synthetic`), `delete-after` set 45 days ahead | `scripts/Deploy-AgentWall.ps1:820#delete-after` |
| `modelName`, `modelVersion`, `modelSku`, `modelCapacity`, `modelDeployment` | the model options; the deployment name is the model name without dots (`gpt-5.4-mini` becomes `gpt-54-mini`) | `scripts/common.ps1:180#modelDeploy` |
| `publisherEmail` | `-PublisherEmail`, else the sign-in name unless it contains `#` (a guest account) | `scripts/Deploy-AgentWall.ps1:794-832#publisherEmail` |
| `alertEmail`, `entraWorkspaceId` | written only when supplied | `scripts/Deploy-AgentWall.ps1:794-832#alertEmail` |

Where the options take effect downstream:

| Option | Effect | Citation |
|---|---|---|
| `-AlertEmail` | Sentinel and Monitor action group (observability stage), only when set | `scripts/deploy.ps1:162-167#alertEmail` |
| `-AlertEmail` | budget alert recipient, only when set | `scripts/deploy.ps1:402#alertEmail` |
| `-EntraWorkspaceId` | optional, read-only Entra sign-in export workspace; adds Entra rows to `AbwFullChain` | `scripts/deploy.ps1:162-167#entraWorkspaceId` |
| `-PublisherEmail` | APIM publisher e-mail, defaults to the operator | `scripts/deploy.ps1:364#publisherEmail` |
| `-Model*` | parameters of the Foundry deployment | `scripts/deploy.ps1:251-256#modelName` |
| `-SearchLocation` | AI Search region passed to the Foundry Bicep | `scripts/deploy.ps1:275#searchLocation` |

**Configuration resolution.** `Resolve-Config` decides whether this run reuses an existing configuration, starts a new one, or must stop. The configuration is frozen once written: names embed the unique suffix and are bound to Entra and ARM objects, so changing one mid-way would orphan resources. An option that was explicitly passed and differs from the stored configuration is reported as a conflict instead of being applied silently (`scripts/Deploy-AgentWall.ps1:834-853#Get-ConfigConflicts`).

| Situation | Result | Citation |
|---|---|---|
| `config.json` exists for the same tenant and subscription | reused; names frozen; an explicitly passed Location, SearchLocation, Workload, EnvName, Instance, UniqueSuffix, ResourceGroupName, TenantDomain or Model option that differs is a problem ("remove the option, or rerun with -ResetState") | `scripts/Deploy-AgentWall.ps1:877-908#Resolve-Config` |
| Local state belongs to another tenant or subscription; or the resource group is gone but stage outputs remain; or outputs exist without a `config.json` | problem, unless `-ResetState` is given | `scripts/Deploy-AgentWall.ps1:877-908#Resolve-Config` |
| `-ResetState` | archives `infra/generated` and `.secrets` into `_archive/state-<time>` and builds a new configuration; it never touches Azure or Entra | `scripts/Deploy-AgentWall.ps1:939-948#Reset-LocalState` |
| New configuration | names generated; global-name availability checked for two storage accounts, the container registry and APIM; up to six suffix attempts; a supplied `-UniqueSuffix` that is taken is reported at once | `scripts/Deploy-AgentWall.ps1:905-937#New-ConfigObject` |

The availability probe is `scripts/Deploy-AgentWall.ps1:855-869#Test-NameAvailability`; the "stage outputs already on disk" test is `scripts/Deploy-AgentWall.ps1:871-875#Get-PresentArtifacts`.

#### 4.9.3 Guards that run before anything changes

| Check | Blocks the run? | What it verifies | Citation |
|---|---|---|---|
| Operating system | yes | Windows | `scripts/Deploy-AgentWall.ps1:688-689#IsWindows` |
| Azure CLI | yes | `az` present and at least 2.61.0 | `scripts/Deploy-AgentWall.ps1:691-697#2.61.0` |
| Bicep | no | `az bicep version`; a missing Bicep only skips the template compile check | `scripts/Deploy-AgentWall.ps1:699-704#bicep` |
| Python | yes | 3.11 or later, found through `py -3.13/-3.12/-3.11`, `python`, `python3` | `scripts/Deploy-AgentWall.ps1:706-712#Find-Python` |
| azd | yes, only when `connections` will run | present on the PATH | `scripts/Deploy-AgentWall.ps1:714-718#azd` |
| Prerequisite install | opt-in | `-InstallPrereqs` installs Azure CLI, azd and Python 3.11 with winget and refreshes the PATH; ignored by `-CheckOnly` | `scripts/Deploy-AgentWall.ps1:665-681#Install-MissingPrereqs` |
| Python virtual environment | n/a | `.venv` is created and `requirements.txt` installed; the import test covers azure.identity, azure.ai.projects, azure.monitor.query, httpx, msal, jwt, requests, openai, starlette and uvicorn | `scripts/Deploy-AgentWall.ps1:722-737#Initialize-Venv` |
| Azure sign-in | yes | a user sign-in (service principals are refused); `-TenantId`, when given, must match the subscription's tenant; GUIDs are masked in output | `scripts/Deploy-AgentWall.ps1:751-783#Initialize-AzContext` |
| Name rules | yes | the generated names | `scripts/Deploy-AgentWall.ps1:233-259#Test-AbwNameRules` |
| Plan inputs | yes | every step that will run has its input files, or an earlier selected step produces them | `scripts/Deploy-AgentWall.ps1:529-543#Test-PlanNeeds` |
| Existing Entra footprint | yes, unless `-AdoptExistingEntra`; asked only when `entra1` will run and either `-ResetState` is set or `entra.json` is absent (step 8 below) | any app named `abw-*`, group named `sg-abw-*` or user named `abw.*` already in the tenant (the same three prefixes the verification counts); a Graph read failure is only a warning; `-CheckOnly` against a subscription that is not the `az` default skips the check and says so, because it cannot read that subscription's tenant | `scripts/Deploy-AgentWall.ps1:950-964#Test-ExistingEntraDeployment`, `scripts/Deploy-AgentWall.ps1:967-986#Test-EntraTakeoverGuard` |
| Existing policy initiative | no | `az policy set-definition show --name abw-agent-platform-controls`; asked only when `governance` will run and `governance.json` is absent | `scripts/Deploy-AgentWall.ps1:988-992#Test-ExistingInitiative` |
| Permissions | no | Owner, or Contributor plus User Access Administrator or Role Based Access Control Administrator; Entra Global Administrator (checked only when Graph is usable) | `scripts/Deploy-AgentWall.ps1:994-1026#Test-Permissions` |
| Model quota | no | the model is offered in the region and the remaining quota covers `-ModelCapacity` | `scripts/Deploy-AgentWall.ps1:1028-1068#Test-ModelCapacity` |
| Template compile | yes, `-CheckOnly` only | every `infra/*.bicep` builds with `az bicep build --stdout` (non-recursive) | `scripts/Deploy-AgentWall.ps1:1070-1085#Test-BicepCompile` |
| Typed confirmation | gate | the operator types the resource group name; `-Yes` skips it; a non-interactive session without `-Yes` stops with an error | `scripts/Deploy-AgentWall.ps1:1132-1138#Confirm-Run` |

The impact screens print the configuration without any tenant or subscription id, the plan with rough minutes, and a cost and undo summary: `scripts/Deploy-AgentWall.ps1:1090-1101#Show-Config`, `scripts/Deploy-AgentWall.ps1:1103-1121#Show-Plan`, `scripts/Deploy-AgentWall.ps1:1123-1130#Show-Impact`.

**Order of events in `Invoke-MainCore`.**

1. Force UTF-8 for the console and for Python children, print the banner: `scripts/Deploy-AgentWall.ps1:1273-1279#PYTHONUTF8`.
2. Build the step table, read the state file, make `-ResetState` mean "assume nothing is done", compute the first plan and whether `connections` will run (that decides whether azd is required). An unknown step id, a `-From` that comes after `-Until`, or an `-Only` step outside that range is thrown here, before any prerequisite check or sign-in (4.9.5): `scripts/Deploy-AgentWall.ps1:1281-1285#Get-StepTable`.
3. Install missing prerequisites (opt-in), then check them; blockers stop the run: `scripts/Deploy-AgentWall.ps1:1287-1291#Test-Prereqs`.
4. Sign in and select the subscription: `scripts/Deploy-AgentWall.ps1:1293#Initialize-AzContext`.
5. Resolve and print the configuration, then the name rules: `scripts/Deploy-AgentWall.ps1:1297-1304#Resolve-Config`.
6. For a new configuration, warn when the resource group already exists (the run would add to it): `scripts/Deploy-AgentWall.ps1:1305-1310#group`.
7. Compute the plan again with the real configuration, check plan inputs, warn about `-Force` without `-Only` or `-From`: `scripts/Deploy-AgentWall.ps1:1312-1314#Test-PlanNeeds`.
8. Entra footprint and policy initiative checks. The Entra guard runs only when `entra1` will run and either `-ResetState` is set or `entra.json` is absent, so a resumed deployment is never blocked by its own objects; what it returns is added to the blockers: `scripts/Deploy-AgentWall.ps1:1316-1318#Test-EntraTakeoverGuard`. The initiative check is a warning and runs when `governance` will run and `governance.json` is absent: `scripts/Deploy-AgentWall.ps1:1319-1323#Test-ExistingInitiative`.
9. Permission and quota checks (warnings), then the template compile in `-CheckOnly`: `scripts/Deploy-AgentWall.ps1:1325-1326#Test-ModelCapacity`, `scripts/Deploy-AgentWall.ps1:1327-1335#Test-BicepCompile`.
10. Show the plan and the impact; any blocker ends the run here: `scripts/Deploy-AgentWall.ps1:1337-1341#Show-Impact`.
11. `-CheckOnly` ends with "Ready. Nothing was created, changed or written", or runs the verification first when there is nothing left to run; a real run with nothing left to run verifies and exits: `scripts/Deploy-AgentWall.ps1:1342-1355#runCount`.
12. Typed confirmation; declining prints "Cancelled. Nothing was deployed." and exits 1: `scripts/Deploy-AgentWall.ps1:1357-1358#Confirm-Run`.
13. Archive stale local state when `-ResetState` or a changed scope requires it, then write `config.json` for a new configuration: `scripts/Deploy-AgentWall.ps1:1360-1370#Reset-LocalState`.
14. Open the log file `infra/generated/logs/deploy-<time>.log`, prepare the virtual environment, write down the steps that existing outputs show as done when no run is on record yet (`Save-InferredSteps`, 4.9.5), then record the run (the last 50 runs keep only step selection and switch names, never ids): `scripts/Deploy-AgentWall.ps1:1372-1390#LogWriter`, `scripts/Deploy-AgentWall.ps1:1388#Save-InferredSteps`.
15. Run the steps one at a time, then summarise, verify and print the next steps: `scripts/Deploy-AgentWall.ps1:1397-1417#Invoke-Step`.

Trade-off: because `az account set` runs while the sign-in context is prepared (before the confirmation), declining the confirmation can still leave the operator's `az` default subscription switched. The cancel message therefore says "Nothing was deployed" rather than "Nothing was changed" (`scripts/Deploy-AgentWall.ps1:772-781#CheckOnly`).

#### 4.9.4 The 26 steps

The step table is built by `Get-StepTable`. Steps are strictly ordered and each lists the files it needs (named below by their stage, for example `entra` means `entra.json` in `infra/generated`) and the artifact that proves it finished. Seventeen steps are required (a failure stops the run) and nine are optional (a failure only warns). The "Min" column is the rough estimate the orchestrator prints.

Required steps (fatal on failure):

| # | Step | Runs | Done when | Needs | Min | Citation |
|---|---|---|---|---|---|---|
| 1 | preflight | `scripts/deploy.ps1 -Stage preflight` | `preflight.json` | - | 1-3 | `scripts/Deploy-AgentWall.ps1:392-393#preflight` |
| 2 | entra1 | `identity/Setup-Entra.ps1 -Phase 1` | `entra.json` (also leaves `.secrets/agent-client.json`) | - | 3-5 | `scripts/Deploy-AgentWall.ps1:394-395#entra1` |
| 3 | network | `-Stage network` | `network.json` | - | 2-4 | `scripts/Deploy-AgentWall.ps1:396-397#network` |
| 4 | foundry | `-Stage foundry` | `foundry.json` | network | 15-20 | `scripts/Deploy-AgentWall.ps1:398-399#foundry` |
| 5 | foundryrbac | `-Stage foundryrbac` | `foundryrbac.json` | foundry, entra | 1-3 | `scripts/Deploy-AgentWall.ps1:400-401#foundryrbac` |
| 6 | platform | `-Stage platform` | `platform.json` | network, entra | 10-15 | `scripts/Deploy-AgentWall.ps1:402-403#platform` |
| 7 | images | `scripts/build-images.ps1 -Target mcp` | `images.json` | platform | 5-8 | `scripts/Deploy-AgentWall.ps1:404-405#images` |
| 8 | apps | `-Stage apps` | `apps.json` | platform, entra, images | 5-8 | `scripts/Deploy-AgentWall.ps1:406-407#apps` |
| 9 | entra2 | `identity/Setup-Entra.ps1 -Phase 2` | state entry only (inferred from `apis.json`, but only while no run is on record) | platform, entra | 1-2 | `scripts/Deploy-AgentWall.ps1:408-409#entra2` |
| 10 | apim | `-Stage apim` | `apim.json` | network, entra, foundry | 35-50 | `scripts/Deploy-AgentWall.ps1:410-411#apim` |
| 11 | apis | `-Stage apis` | `apis.json` | apps, entra, apim | 3-6 | `scripts/Deploy-AgentWall.ps1:412-413#apis` |
| 12 | images-seed | `scripts/build-images.ps1 -Target seed` | `images-seed.json` | platform | 3-6 | `scripts/Deploy-AgentWall.ps1:414-415#images-seed` |
| 13 | seed | `-Stage seed` | state entry only (inferred when `connections.json`, `agents.json` or `governance.json` exists, but only while no run is on record) | platform, images-seed | 5-12 | `scripts/Deploy-AgentWall.ps1:416-417#seed` |
| 14 | baseline | `identity/Use-AdminAsPersona.ps1 -As wes -Also tara` | state entry only (inferred from `connections.json`, but only while no run is on record) | entra | 1-2 | `scripts/Deploy-AgentWall.ps1:418-419#baseline` |
| 15 | connections | `scripts/foundry-connections.ps1` | `connections.json` | entra, apis, apps, foundry, `.secrets/agent-client.json` | 5-10 | `scripts/Deploy-AgentWall.ps1:420-421#connections` |
| 16 | agents | `src/agent/create_agents.py` | `agents.json` | foundry, connections | 2-4 | `scripts/Deploy-AgentWall.ps1:422-423#agents` |
| 17 | governance | `-Stage governance` | `governance.json` and `observability.json` | foundry, platform | 8-12 | `scripts/Deploy-AgentWall.ps1:424-426#governance` |

Optional steps (a failure warns and the run continues):

| # | Step | Runs | Done when | Needs | Min | Off when | Citation |
|---|---|---|---|---|---|---|---|
| 18 | guardrail | `src/agent/create_agents.py --rai abw-agent-guardrails` | `agents.json` lists the shielded agent `abw-wall-desk-redteam-shielded` | agents, governance | 1-3 | `-SkipGuardrail` | `scripts/Deploy-AgentWall.ps1:427-428#guardrail` |
| 19 | frontdoor | `-Stage frontdoor` | `frontdoor.json` | apim | 5-10 | `-SkipFrontDoor` | `scripts/Deploy-AgentWall.ps1:429-430#frontdoor` |
| 20 | budget | `-Stage budget` | `budget.json` | - | 1-2 | `-SkipBudget` | `scripts/Deploy-AgentWall.ps1:431-432#budget` |
| 21 | jumpbox | `scripts/jumpbox.ps1` | `jumpbox.json` contains `deployedAt` | network | 10-15 | `-SkipJumpBox` | `scripts/Deploy-AgentWall.ps1:433-434#jumpbox` |
| 22 | console | `scripts/jumpbox-console.ps1` | the jump box record contains `consoleOnVm` | jumpbox | 15-25 | `-SkipJumpBox`, `-SkipConsole`, or `demo/evidence-scrubbed/scoreboard.json` missing | `scripts/Deploy-AgentWall.ps1:435-436#console` |
| 23 | extras-defender | `scripts/extras-defender-sentinel.ps1` | `trackb-defender.json` | platform | 2-5 | off unless `-WithExtras` | `scripts/Deploy-AgentWall.ps1:437-438#extras-defender` |
| 24 | extras-identity | `scripts/extras-agent-identity.ps1 -SkipConditionalAccess` | `trackb-identity.json` | apim, entra | 1-3 | off unless `-WithExtras` | `scripts/Deploy-AgentWall.ps1:439-440#extras-identity` |
| 25 | proofs | `demo/prove.py` (the 18 proofs) | state entry only | agents, governance | 30-40 | off unless `-RunProofs` | `scripts/Deploy-AgentWall.ps1:441-442#proofs` |
| 26 | scoreboard | `demo/scoreboard.py --check` | state entry only | - | 1 | off unless `-RunProofs` | `scripts/Deploy-AgentWall.ps1:443-444#scoreboard` |

Default plan: steps 1-17 plus guardrail, frontdoor, budget, jumpbox and console, which is 22 steps, or 21 when the scrubbed scoreboard file is missing (the console is then skipped with the hint to run `python demo/scrub_evidence.py` first). Rough totals from the table: the 17 required steps take 105 to 170 minutes, the four optional infrastructure steps add 17 to 30, the console adds 15 to 25 (137 to 225 minutes in all), the two extras add 3 to 8 and the proofs add 31 to 41.

Probes that decide "done" for steps without a plain artifact are defined next to the switches: `scripts/Deploy-AgentWall.ps1:359-390#probeGuardrail`.

Why this order (read from the Needs column, not assumed):

- `entra1` runs early and has no input because nine later steps list `entra.json` in their Needs column (`foundryrbac`, `platform`, `apps`, `entra2`, `apim`, `apis`, `baseline`, `connections`, `extras-identity`), and `connections` also needs the agent client secret it leaves under `.secrets` (`scripts/Deploy-AgentWall.ps1:394-395#entra1`, `scripts/Deploy-AgentWall.ps1:420-421#agent-client.json`).
- `network` precedes `foundry`, `platform` and `jumpbox`: the Foundry stage consumes the VNet and subnet ids (`scripts/deploy.ps1:259-262#existingVnetResourceId`).
- `entra2` follows `platform` because Phase 2 reads `platform.json` and creates one federated identity credential on each of the four on-behalf-of MCP apps (research, wall, actions, private; the vendor app gets none). The subject of each credential is that server's own user-assigned managed identity, read from `platform.json`, and the on-behalf-of exchange later relies on it (`identity/Setup-Entra.ps1:10#platform.json`, `identity/Setup-Entra.ps1:266#research`, `identity/Setup-Entra.ps1:267#uamis`, `identity/Setup-Entra.ps1:274#federatedIdentityCredentials`).
- `baseline` sits before `connections`: Foundry stores the token it gets at the first consent for the token's whole life, so a role-less first consent leaves an agent without tools long after the roles are fixed (`README.md:92#Baseline`).
- APIM (35 to 50 minutes) dominates the wall-clock time. Steps are never run in parallel: the loop is a plain `foreach` over the plan and later steps read the files earlier steps wrote (`scripts/Deploy-AgentWall.ps1:1397-1417#foreach`).
- The connections step prepares azd first: its Before hook points `AZD_CONFIG_DIR` at `.secrets/azd` only when the variable is not already set, so the operator's own azd configuration is untouched unless the operator has already set that variable (the two azd changes below then land in the operator's folder). It then enables Azure CLI authentication and installs the `azure.ai.connections` extension if missing. `Invoke-Main` saves the variable before the run and restores it, or removes it, in a `finally` block, so a shell that started the script keeps its own value (`scripts/Deploy-AgentWall.ps1:386-389#AZD_CONFIG_DIR`, `scripts/Deploy-AgentWall.ps1:1259-1267#AZD_CONFIG_DIR`, `scripts/Deploy-AgentWall.ps1:420-421#connections`, `scripts/Deploy-AgentWall.ps1:350-357#Initialize-Azd`). The probe reads `azd extension list --installed -o json`; `azd ai connection --help` is deliberately not used because it installs the extension as a side effect (`scripts/Deploy-AgentWall.ps1:340-348#Test-AzdExtension`).

#### 4.9.5 Plan resolution and done-detection

`Get-PlanItems` turns the step table, the state and the options into one action per step: run, done, assumed, skip (`scripts/Deploy-AgentWall.ps1:486-527#Get-PlanItems`). Precedence, in order:

| Order | Rule | Action | Citation |
|---|---|---|---|
| 0a | a step id in `-From`, `-Until`, `-Only` or `-Skip` that does not exist | the run stops with "Unknown step ... Valid steps: ..." | `scripts/Deploy-AgentWall.ps1:489-491#Unknown step` |
| 0b | `-From` names a step after `-Until`, or an `-Only` step lies outside the `-From` to `-Until` range | the run stops with an error that names both steps and prints the step order, instead of planning nothing or quietly ignoring the step; like 0a it ends in the unhandled-error path, exit 1 | `scripts/Deploy-AgentWall.ps1:496#comes after`, `scripts/Deploy-AgentWall.ps1:497-501#is outside the range` |
| 1 | the step is disabled by a switch | skip, with the reason | `scripts/Deploy-AgentWall.ps1:507#Disabled` |
| 2 | the step is in `-Skip` | skip | `scripts/Deploy-AgentWall.ps1:508#Skip` |
| 3 | `-Only` is set and the step is not listed | skip | `scripts/Deploy-AgentWall.ps1:509#Only` |
| 4 | the step is before `-From` | assumed done | `scripts/Deploy-AgentWall.ps1:510#From` |
| 5 | the step is after `-Until` | skip | `scripts/Deploy-AgentWall.ps1:511#Until` |
| 6 | the step is done and `-Force` is not set | done (the note adds "add -Force to run it again" when `-Only` named it) | `scripts/Deploy-AgentWall.ps1:513-517#Force` |
| 7 | the step has a skip condition that holds | skip, with the reason | `scripts/Deploy-AgentWall.ps1:519-521#SkipIf` |
| 8 | otherwise | run | `scripts/Deploy-AgentWall.ps1:505#run` |

`Test-StepDone` decides "done":

- With `-ResetState` (assume fresh) nothing is done.
- A state entry of `failed` or `running` is never done, so an interrupted step is run again.
- For steps flagged state-only, a recorded `done` is trusted and any other recorded status is not done. With no entry, the step's inference probe is consulted only while no run is on record (`runs` is empty); once a run is on record, a step with no entry is not done.
- Otherwise every artifact must exist and the step's own probe (for example the `deployedAt` check on the jump box record) must pass.

(`scripts/Deploy-AgentWall.ps1:448-462#Test-StepDone`). `Save-InferredSteps` makes the inference permanent: when a run starts and none is on record yet (an environment built by hand or by the older scripts, or one whose state file was lost), it writes every state-only step whose probe holds into the state file as `done` with the note "inferred from existing outputs", before the run itself is recorded. It does nothing with `-ResetState` or once a run is on record; `-CheckOnly` never reaches it in a real flow, and if it were called there the result would stay in memory because `Save-State` writes nothing (`scripts/Deploy-AgentWall.ps1:465-472#Save-InferredSteps`, called at `scripts/Deploy-AgentWall.ps1:1388#Save-InferredSteps`). `Get-MissingOutputs` lists the artifacts a step should have left and is the check applied after every step (`scripts/Deploy-AgentWall.ps1:474-484#Get-MissingOutputs`). `Test-PlanNeeds` rejects a plan in which a step's input file is neither on disk nor produced by an earlier selected step, which is why `-Only foundry` on a fresh checkout reports the missing network output instead of failing deep inside Bicep (`scripts/Deploy-AgentWall.ps1:529-543#Test-PlanNeeds`).

Trade-off: state-only steps (`entra2`, `seed`, `baseline`, `proofs`, `scoreboard`) leave no artifact the orchestrator can inspect. Only the first three have an inference probe, and it is used in one situation: the first run against an environment that already has outputs but no recorded run. From then on only recorded results count, so a step that was skipped or never reached is not taken for done just because a later step left outputs behind. The heuristics can still be wrong in that first run, in either direction (`scripts/Deploy-AgentWall.ps1:379-381#inferEntra2`).

#### 4.9.6 Step execution, retries and state

**Execution.** Each step is a separate process started from the repo root: `pwsh -NoProfile -ExecutionPolicy Bypass -File <script> <arguments>` (the same `pwsh` that runs the orchestrator) or `.venv/Scripts/python.exe <script> <arguments>`. Standard error is merged into standard output, every line is echoed to the console and the log, the last 40 lines are kept for diagnostics, and a line that matches the step's transient pattern marks the failure as retryable. A null exit code and any exception both count as exit code 1 (`scripts/Deploy-AgentWall.ps1:548-585#Invoke-StepProcess`).

**Retries.** `Invoke-Step` makes up to three attempts. A step is retried only when its exit code is non-zero, its output matched the transient pattern, and attempts remain; the wait is 60 seconds by default and 90 seconds for `governance`. A failing Before hook fails the step at once. A step that exits 0 but leaves a declared artifact missing is marked failed ("finished but did not leave the expected result") and is not retried (`scripts/Deploy-AgentWall.ps1:587-631#Invoke-Step`, `scripts/Deploy-AgentWall.ps1:594-601#Before`, `scripts/Deploy-AgentWall.ps1:603#maxAttempts`, `scripts/Deploy-AgentWall.ps1:612-621#Get-MissingOutputs`, `scripts/Deploy-AgentWall.ps1:622-626#RetryDelay`).

Default transient pattern (`scripts/Deploy-AgentWall.ps1:138#TransientPattern`):

```
OperationInProgress | AnotherOperationInProgress | ConflictingOperationInProgress
RetryableError | ServiceUnavailable | GatewayTimeout | TooManyRequests | InternalServerError
```

The `governance` step has its own list because the first policy assignment in a tenant can hit Azure role-assignment propagation errors (`scripts/Deploy-AgentWall.ps1:424-426#CheckAccessPrincipalCreationConcurrencyError`):

```
CheckAccessPrincipalCreationConcurrencyError | CheckAccessPrincipalTokenInvalid | OperationInProgress
RetryableError | ServiceUnavailable | GatewayTimeout
```

**State file.** `infra/generated/deploy-state.json` is git-ignored. Its shape: `schema` (1), `createdAt`, `steps` (per step id: `status`, `updatedAt`, `seconds`, `attempts`, `note`), `runs` (the last 50: `startedAt`, `options`) and `verify` (`at`, `checks`). A missing file starts a fresh state. A file that is empty, not valid JSON or not a JSON object (for example `[1,2]`) is ignored with a warning, so the recorded step results are lost; unless `-CheckOnly` is set, a copy is kept first as `deploy-state.json.bad` (`scripts/Deploy-AgentWall.ps1:270-276#deploy-state.json.bad`). Writes are atomic: the state goes to `deploy-state.json.tmp` and is then moved over the real file, so a crash mid-write cannot leave a half-written state, and a stale `.tmp` from an earlier crash is simply overwritten (`scripts/Deploy-AgentWall.ps1:288-290#Move`). `-CheckOnly` keeps the state in memory only and never writes it (`scripts/Deploy-AgentWall.ps1:264-282#Read-State`, `scripts/Deploy-AgentWall.ps1:284-291#Save-State`, `scripts/Deploy-AgentWall.ps1:293-300#Set-StepState`).

| Status | Written when | Effect on the next run |
|---|---|---|
| `running` | each attempt starts | not done; run again |
| `done` | exit 0 and every expected output exists | skipped (or trusted, for state-only steps) |
| `failed` | attempts exhausted, a non-retryable failure, or missing outputs | not done; run again |
| (no entry) | never started, or skipped for a missing optional input | decided by artifacts and probes; for state-only steps, by an inference probe only while no run is on record, otherwise not done |

A step definition carries its defaults in one place: kind `ps` (or `py`), fatal by default, retry delay 60 seconds, estimate 0 (`scripts/Deploy-AgentWall.ps1:308-338#New-Step`).

**Step loop.** For each planned step the loop first checks its input files. A required step with a missing input fails the run; an optional one is skipped with a note and counted as a soft failure. A required step that fails prints the last 25 lines of its output and stops the loop; an optional failure warns and continues (`scripts/Deploy-AgentWall.ps1:1400-1409#missingNeeds`, `scripts/Deploy-AgentWall.ps1:1410-1416#Fatal`). After the loop the run summary lists every step as done, FAILED, not run, done earlier, assumed done or skipped (`scripts/Deploy-AgentWall.ps1:1228-1243#Show-RunSummary`).

#### 4.9.7 Verification

After a successful run, after a "nothing to run" run, and in `-CheckOnly` against a finished deployment, `Invoke-Verify` performs up to 12 read-only checks and stores them under `verify` in the state file. Four checks (1 to 4) read live Azure state with ARM GET calls through `az rest`; check 6 reads an assignment id from a local record and then asks ARM whether it resolves; four checks (5 and 7 to 9) read only local records; and the three Entra checks (10 to 12) use Graph GET calls and run only when Graph is usable. A missing `observability.json` produces one failed "Observability" check in place of checks 7 to 9, and a Graph error one failed "Entra objects" check in place of 10 to 12 (`scripts/Deploy-AgentWall.ps1:1197#Observability`, `scripts/Deploy-AgentWall.ps1:1207#Entra objects`). A failed check prints a warning ("some resources may still be provisioning") and never changes the exit code (`scripts/Deploy-AgentWall.ps1:1140-1145#Get-ArmJson`, `scripts/Deploy-AgentWall.ps1:1432-1433#failedChecks`).

| # | Check | Passes when | Source | Citation |
|---|---|---|---|---|
| 1 | Resources in the resource group | at least one resource is listed | live ARM list | `scripts/Deploy-AgentWall.ps1:1161-1162#Resources` |
| 2 | Container Apps | at least one app and all are `Succeeded` | live ARM list | `scripts/Deploy-AgentWall.ps1:1164-1169#containerApps` |
| 3 | API Management | provisioning state `Succeeded` | live ARM GET | `scripts/Deploy-AgentWall.ps1:1171-1172#ApiManagement` |
| 4 | Foundry model deployment | provisioning state `Succeeded` | live ARM GET | `scripts/Deploy-AgentWall.ps1:1174-1175#CognitiveServices` |
| 5 | Foundry agents | at least 3 published agents | local `agents.json` | `scripts/Deploy-AgentWall.ps1:1177-1182#agents.json` |
| 6 | Policy initiative assignment | the assignment id recorded in `governance.json` resolves | local record, live ARM GET | `scripts/Deploy-AgentWall.ps1:1184-1188#assignmentId` |
| 7 | Sentinel analytics rules | at least 1 rule recorded | local `observability.json` | `scripts/Deploy-AgentWall.ps1:1190-1197#sentinelRuleCount` |
| 8 | KQL function pack | at least 1 function recorded | local `observability.json` | `scripts/Deploy-AgentWall.ps1:1190-1197#functionNames` |
| 9 | Cockpit workbook | a workbook name recorded | local `observability.json` | `scripts/Deploy-AgentWall.ps1:1190-1197#workbookName` |
| 10 | Entra app registrations | exactly 7 whose name starts with `abw-` | live Graph | `scripts/Deploy-AgentWall.ps1:1199-1208#GraphOk` |
| 11 | Entra groups | exactly 6 whose name starts with `sg-abw-` | live Graph | `scripts/Deploy-AgentWall.ps1:1199-1208#groups` |
| 12 | Entra persona users | exactly 5 whose sign-in name starts with `abw.` | live Graph | `scripts/Deploy-AgentWall.ps1:1199-1208#users` |

Limitation: checks 5 and 7 to 9 confirm what a stage recorded, not what exists now. The Sentinel rule count, the function count and the workbook name come from `observability.json`, and the agent count from `agents.json`.

#### 4.9.8 Failure handling

| Situation | What the orchestrator does | Exit | Citation |
|---|---|---|---|
| An unknown step id, a `-From` after `-Until`, or an `-Only` step outside the range | an error that names the steps and prints the step order; thrown at the first plan, so nothing has been changed | 1 | `scripts/Deploy-AgentWall.ps1:1284#firstPlan` |
| A prerequisite is missing | blocker; nothing is changed | 1 (3 with `-CheckOnly`) | `scripts/Deploy-AgentWall.ps1:1287-1291#Complete-Blocked` |
| Not signed in, a service principal, or a tenant mismatch | blocker | 1 or 3 | `scripts/Deploy-AgentWall.ps1:1293-1295#blockers` |
| The configuration conflicts with the stored one, or local state is from another scope | problem list; fix the option or use `-ResetState` | 1 or 3 | `scripts/Deploy-AgentWall.ps1:1297-1303#Problems` |
| `abw-*` apps, `sg-abw-*` groups or `abw.*` users already exist in the tenant, and `entra1` will run with `-ResetState` set or `entra.json` absent | blocker unless `-AdoptExistingEntra`; with the switch it is a warning, and Phase 1 updates the objects, creates a new `abw-agent-client` secret when none is stored locally, and resets passwords of existing `abw.*` users that have no stored password | 1 or 3 | `scripts/Deploy-AgentWall.ps1:967-986#Test-EntraTakeoverGuard`, `scripts/Deploy-AgentWall.ps1:1316-1318#Test-EntraTakeoverGuard` |
| The resource group already exists | warning only; the run adds to it | n/a | `scripts/Deploy-AgentWall.ps1:1305-1310#Warn` |
| The initiative already exists, and `governance` will run with `governance.json` absent | warning only; the governance step would take it over | n/a | `scripts/Deploy-AgentWall.ps1:1319-1323#Warn` |
| A template does not compile (`-CheckOnly`) | blocker | 3 | `scripts/Deploy-AgentWall.ps1:1327-1335#bad` |
| The operator declines the confirmation | "Cancelled. Nothing was deployed." | 1 | `scripts/Deploy-AgentWall.ps1:1358#Cancelled` |
| A transient Azure error in a step | up to three attempts, waiting 60 s (90 s for governance) between them | continues | `scripts/Deploy-AgentWall.ps1:587-631#Invoke-Step` |
| A required step fails | last 25 lines printed; run stops; hint to rerun the same command, or `-Only <step> -Force` for one step | 1 | `scripts/Deploy-AgentWall.ps1:1424-1430#Stopped` |
| A step exits 0 but its output is missing | failed, not retried | 1 for a required step | `scripts/Deploy-AgentWall.ps1:612-621#Get-MissingOutputs` |
| An optional step fails | warning; the run continues; reported at the end | 2 | `scripts/Deploy-AgentWall.ps1:1435-1438#softFailed` |
| A step's input file is missing at run time | required step: run stops; optional step: skipped and counted as a soft failure | 1 or 2 | `scripts/Deploy-AgentWall.ps1:1400-1409#missingNeeds` |
| A verification check fails | warning; the exit code is unchanged | 0 | `scripts/Deploy-AgentWall.ps1:1432-1433#failedChecks` |
| The run is interrupted (window closed, Ctrl+C) | the step stays `running` in the state file, which counts as not done, so a rerun repeats it | n/a | `scripts/Deploy-AgentWall.ps1:448-462#Test-StepDone` |
| In the preflight stage `az account set`, `az group create` or `az provider register` returns an error | the stage throws a message that names the failed call and writes no `preflight.json`; the step fails and, being required, stops the run | 1 | `scripts/deploy.ps1:196-197#az account set`, `scripts/deploy.ps1:199-200#az group create`, `scripts/deploy.ps1:206-207#az provider register`, `scripts/deploy.ps1:213#preflight.json` |
| An unhandled exception | an `ERROR:` line with GUIDs masked | 1 | `scripts/Deploy-AgentWall.ps1:1449-1463#ERROR` |

There is no rollback. A failed step is retried, not undone, and cleanup is a separate, deliberate action (`scripts/teardown.ps1 -WhatIf`, then `-Yes`), which the orchestrator only mentions in its closing hints (`scripts/Deploy-AgentWall.ps1:1215-1226#Show-NextSteps`).

What the orchestrator does not automate: authenticator enrolment and sign-in for the real personas (Path A), the one Foundry OAuth consent per MCP connection (a browser step), the optional admin-portal switches (Agent 365 gateway, Defender XDR "Security for AI agents", Purview DSPM for AI), the proof run unless `-RunProofs` is given, and the jump box device-code sign-in. `Show-NextSteps` prints these (`scripts/Deploy-AgentWall.ps1:1215-1226#Show-NextSteps`).

#### 4.9.9 Security and data handling

| Concern | Behaviour | Citation |
|---|---|---|
| GUIDs in output | `Hide-Guid` keeps only the first group (`xxxxxxxx-****`) in the orchestrator's own messages | `scripts/Deploy-AgentWall.ps1:167-171#Hide-Guid` |
| Log file | every console line is also written to `infra/generated/logs/deploy-<time>.log` with ANSI colour codes stripped; the folder is git-ignored | `scripts/Deploy-AgentWall.ps1:149-155#Write-Log` |
| Secrets | the orchestrator prints none; child scripts write secrets under `.secrets/`, which is git-ignored | `scripts/Deploy-AgentWall.ps1:1215-1226#Show-NextSteps` |
| Secret deployment parameters | a parameter named in the stage script's secret list (today only the vendor API key of the `apps` stage) reaches `az` through a short-lived `.secrets/params.<stage>.tmp.json`; the copy kept in `infra/generated` shows `***` for it. The live file is deleted in a `finally` after the call, whether the deployment succeeds, fails, runs as `-WhatIf` or is started with `-NoWait` | `scripts/deploy.ps1:46-48#SecretParamKeys`, `scripts/deploy.ps1:63-71#New-ParamFile`, `scripts/deploy.ps1:73-77#Remove-SecretParamFile`, `scripts/deploy.ps1:112#finally` |
| azd configuration | isolated in `.secrets/azd` for the connections step unless the operator's session already sets `AZD_CONFIG_DIR`; the previous value is restored when the run ends | `scripts/Deploy-AgentWall.ps1:420-421#connections`, `scripts/Deploy-AgentWall.ps1:387#AZD_CONFIG_DIR`, `scripts/Deploy-AgentWall.ps1:1259-1267#AZD_CONFIG_DIR` |
| Sign-in type | user sign-ins only; service principals are refused | `scripts/Deploy-AgentWall.ps1:751-783#Initialize-AzContext` |
| Wrong tenant | `-TenantId` must match the subscription's tenant; local state from another tenant is refused | `scripts/Deploy-AgentWall.ps1:877-908#Resolve-Config` |
| Read-only mode | `-CheckOnly` never writes state, configuration or logs and never switches the default subscription; the one side effect is the two empty folders created when the shared helpers load (4.9.1) | `scripts/Deploy-AgentWall.ps1:284-291#Save-State`, `scripts/common.ps1:8#GenDir` |
| Tenant takeover | an existing `abw-*` app, `sg-abw-*` group or `abw.*` user blocks a first Entra run (`entra1` will run and `-ResetState` is set or `entra.json` is absent) unless `-AdoptExistingEntra` is given | `scripts/Deploy-AgentWall.ps1:950-964#Test-ExistingEntraDeployment`, `scripts/Deploy-AgentWall.ps1:967-986#Test-EntraTakeoverGuard` |
| Cost exposure | the confirmation requires typing the resource group name; the impact screen names the undo path | `scripts/Deploy-AgentWall.ps1:1132-1138#Confirm-Run` |

Not masked: the sign-in name is printed unmasked, the banner prints the absolute local repo path, and child-script output is relayed verbatim to the console and the log (see Findings): `scripts/Deploy-AgentWall.ps1:769#Signed`, `scripts/Deploy-AgentWall.ps1:1277-1279#Out-Line`, `scripts/Deploy-AgentWall.ps1:548-585#Invoke-StepProcess`.

#### 4.9.10 Testing

`scripts/Test-DeployOrchestrator.ps1` dot-sources the orchestrator (possible because of the entry guard in 4.9.1) and exercises its functions without deploying anything. It takes about 20 seconds, exits 0 when every check passes (1 when any fails) and prints "All 178 checks passed". It replaces `az`, `azd`, `Invoke-Graph` and `Get-GraphAll` with mocks, runs steps against a fake child process and, in its last section, starts nine child `pwsh` processes from a temp copy of `deploy.ps1` and `common.ps1`: the first only prints which `az` it finds, and the other eight run the real `scripts/deploy.ps1` (three preflight failures, four `apps` runs and one `network` run). In those children a fake `az.ps1` is first on the `PATH` and `AZURE_CONFIG_DIR` points at an empty folder; the first child proves that the fake is the `az` that gets found, so no real `az` call is made and no tenant is touched. Everything the test creates lives in temp folders that it removes at the end (`scripts/Test-DeployOrchestrator.ps1:758-782#ChildPwsh`, `scripts/Test-DeployOrchestrator.ps1:868-870#probe`).

Helpers: `scripts/Test-DeployOrchestrator.ps1:37-53#New-TestContext`; the Azure and Graph mocks: `scripts/Test-DeployOrchestrator.ps1:513-538#Get-GraphAll`; the fake `az.ps1`, the temp copy of the scripts and the child-process helpers: `scripts/Test-DeployOrchestrator.ps1:759-782#ShimText`, `scripts/Test-DeployOrchestrator.ps1:784-809#New-DeployRepo`, `scripts/Test-DeployOrchestrator.ps1:811-831#Invoke-ShimmedPwsh`.

| Section | Checks | What it pins down | Citation |
|---|---|---|---|
| Parameters and help | 4 | every parameter has a default and a help entry; the script is ASCII only | `scripts/Test-DeployOrchestrator.ps1:123#Parameters` |
| Step table | 6 | step ids and order; every step script exists; every artifact and input lives under `infra/generated`, apart from the one known secret `.secrets/agent-client.json`; every `-Stage`, `-Phase`, `-Target`, `-As` value is accepted by its script; with every option on all steps are planned; every step input is produced by an earlier step | `scripts/Test-DeployOrchestrator.ps1:137#Step`, `scripts/Test-DeployOrchestrator.ps1:144#agent-client.json` |
| Plan resolution | 22 | fresh state, extras and proofs off by default, console skipped without the scoreboard, `-Force`, `-From`, `-Until`, `-Only`, `-Skip`, unknown ids, a reversed `-From`/`-Until` range and an `-Only` step outside it refused, `-From` and `-Until` naming the same step, the Skip switches | `scripts/Test-DeployOrchestrator.ps1:171#Plan`, `scripts/Test-DeployOrchestrator.ps1:211-220#comes after` |
| Done detection | 20 | inference for `entra2`, failed beats inference, interrupted `running` is rerun, inference only while no run is on record, `Save-InferredSteps` writing the inferred steps with their reason, nothing inferred once a run is on record or with `-ResetState`, `-CheckOnly` keeping the inference in memory, guardrail, jump box and console probes | `scripts/Test-DeployOrchestrator.ps1:231#Done`, `scripts/Test-DeployOrchestrator.ps1:262-284#Save-InferredSteps` |
| Plan needs | 3 | missing inputs are reported and clear once the file exists | `scripts/Test-DeployOrchestrator.ps1:304#Plan` |
| Names, regions, suffix, formatting | 13 | region codes, suffix shape and variety, naming rules, `Hide-Guid`, durations, version comparison | `scripts/Test-DeployOrchestrator.ps1:316#Names` |
| Configuration object and conflicts | 12 | defaults, model deployment name, publisher and owner, optional keys, guest sign-ins, conflict rules | `scripts/Test-DeployOrchestrator.ps1:335#Configuration` |
| State file | 11 | round trip, an empty, corrupt or non-object file ignored with a warning and kept as `.bad`, `-CheckOnly` writes neither the state nor a `.bad` copy, a second save keeps the first entry, a stale `.tmp` does not stop a save, no `.tmp` is left behind | `scripts/Test-DeployOrchestrator.ps1:361#State`, `scripts/Test-DeployOrchestrator.ps1:372-373#.bad` |
| Local state archive | 2 | archive empties and keeps the moved files | `scripts/Test-DeployOrchestrator.ps1:397#Local` |
| Step runner (fake child process) | 11 | one attempt on success, missing output fails, retry and stop at three attempts, step-specific pattern, last 40 lines kept, missing executable, failing hook | `scripts/Test-DeployOrchestrator.ps1:407#Step` |
| Output of plan, configuration, blockers | 5 | plan text, no ids in the configuration summary, impact summary, exit codes 3 and 1, `-Yes` | `scripts/Test-DeployOrchestrator.ps1:461#Output` |
| azd extension probe (mock azd) | 7 | extension present or absent in each output form; install and failure of install | `scripts/Test-DeployOrchestrator.ps1:479#azd` |
| Azure sign-in, config resolution, guards | 32 | sign-in refusals, subscription switching, new and resumed configuration, every refusal and its `-ResetState` escape, the Entra probe over apps, groups and users (each alone is enough), the four outcomes of the takeover guard plus its `-CheckOnly` skip, initiative probes, Graph failure as "unknown" | `scripts/Test-DeployOrchestrator.ps1:513#Azure`, `scripts/Test-DeployOrchestrator.ps1:643-667#Test-EntraTakeoverGuard` |
| Permissions and model quota | 6 | Owner plus Global Administrator, missing rights, alternative roles, quota enough or short, model not offered | `scripts/Test-DeployOrchestrator.ps1:673#Permissions` |
| Verification (mock ARM and Graph) | 3 | a complete deployment passes with no failed check; results are recorded; a missing footprint fails the matching checks | `scripts/Test-DeployOrchestrator.ps1:720#Verification` |
| `deploy.ps1` against a fake `az` | 21 | the fake `az` is the one found; preflight stops at each failing `az` call (account set, group create, provider register) and writes no result; the apps stage gives `az` a file under `.secrets` that holds the real key, keeps a masked copy in `infra/generated`, and deletes the live file after success, failure, `-WhatIf` and `-NoWait`; a stage without secrets is unchanged | `scripts/Test-DeployOrchestrator.ps1:755#deploy.ps1`, `scripts/Test-DeployOrchestrator.ps1:873-884#cases`, `scripts/Test-DeployOrchestrator.ps1:886-906#vendor key`, `scripts/Test-DeployOrchestrator.ps1:908-914#WhatIf`, `scripts/Test-DeployOrchestrator.ps1:916-921#audit copy` |

What the test proves: the orchestrator's own logic, plus the preflight failure handling and the secret-parameter-file handling of `deploy.ps1` against a fake `az`. The fake only records its arguments and returns canned output, so it shows that the right files reach `az` and are cleaned up, not that Azure accepts the templates. What it does not prove: that every stage script succeeds in a tenant it has never seen. The stage scripts and Bicep were run in the demo tenant, and `-CheckOnly` has been run read-only against it. A deployment from an empty second tenant and subscription has not been run.

**Key takeaways**

- One command deploys the whole solution; the default plan is 22 steps (21 without the scrubbed scoreboard file) and the required 17 take roughly two to three hours, with APIM the longest single step.
- It is resumable: state is kept per step, an interrupted step is repeated, and a finished step is skipped unless `-Force` is given.
- Everything that can go wrong cheaply is checked first (prerequisites, sign-in, configuration conflicts, existing Entra objects, permissions, quota, template compile) and `-CheckOnly` runs all of it read-only.
- The configuration is frozen after the first run, so a rerun can never rename resources silently.
- Verification is read-only and informative: a failed check warns and does not change the exit code, and four of the 12 checks read only local records (a fifth reads a recorded id and then asks ARM).
- The 178-check offline test proves the orchestrator's logic and the stage script's secret handling; a live second-tenant deployment is still outstanding.


#### 4.9.11 Findings

The 10 findings raised while writing section 4.9 (documentation mismatches, defects and undocumented decisions) are collected in [Appendix B.3](appendix-b-findings-register.md#b3-raised-while-writing-section-49). Where the text above says "Findings" or quotes a finding number, it means that list.



### 4.10 Teardown, kill switch and re-deploy

**What this section proves.** One script removes everything the demo created, in the order that works, and touches only objects it can prove belong to the demo (`scripts/teardown.ps1:18-20#prove`). A separate pair of scripts revokes a user or a client app at the gateway without redeploying anything.

**Teardown (`scripts/teardown.ps1`).** Run `-WhatIf` first for a read-only plan, then `-Yes`. Without `-Yes` the operator must type the RG name, and a mismatch aborts before anything is deleted (`scripts/teardown.ps1:135-139#Read-Host`). Flags are `-KeepEntra`, `-SkipPurge` and `-CleanLocal` (`scripts/teardown.ps1:39-44#KeepEntra`, `README.md:159#KeepEntra`).

| Step | Removes | Why it is ordered here | Source |
|---|---|---|---|
| 0 | the report-only Conditional Access policy and the Agent 365 role grant on APIM; runs only without `-KeepEntra`, and a failure is a warning that tells the operator to delete the policy by hand | they live in Entra or on APIM and are outside the RG | `scripts/teardown.ps1:9-10#Track`, `scripts/teardown.ps1:141-146#extras-agent-identity`, `scripts/teardown.ps1:145#catch` |
| 1 | the Foundry capability hosts, the project-scope host first and then the account-scope host; for each host it polls for up to 20 min and then moves on without raising an error | the network-injected agent subnet is held by a service link until they are gone | `scripts/teardown.ps1:11#capability`, `scripts/teardown.ps1:148-162#capability`, `scripts/teardown.ps1:154#AddMinutes` |
| 2 | the Log Analytics workspace, force-deleted | otherwise the name stays reserved in soft-delete | `scripts/teardown.ps1:164-169#force` |
| 3 | the resource group and everything in it | up to three attempts; the script waits 300 s after each of the first two failures and throws after the third; the message warns it takes 20-40 minutes | `scripts/teardown.ps1:171-183#attempt` |
| 4 | soft-deleted Foundry account, Key Vault and API Management (skipped with `-SkipPurge`) | otherwise they keep their names for 7-90 days | `scripts/teardown.ps1:185-203#purge` |
| 5 | every custom policy initiative and definition in the subscription whose name starts with `abw-`; a failed delete is a warning, for example when an initiative is still assigned elsewhere | they are outside the RG | `scripts/teardown.ps1:92-98#abw-`, `scripts/teardown.ps1:205-214#policy` |
| 6 | demo users, `sg-abw-*` groups and `abw-*` apps (skipped with `-KeepEntra`) | tenant objects, removed by `Setup-Entra.ps1 -Phase Teardown` | `scripts/teardown.ps1:216-219#Entra`, `identity/Setup-Entra.ps1:289-302#Invoke-Teardown` |
| 7 | with `-CleanLocal`, the files at the top of the secrets folder and the `*.json` files at the top of the generated-state folder; sub-folders such as the azd config folder stay | `config.json` is then recreated with a new suffix | `scripts/teardown.ps1:221-227#CleanLocal`, `scripts/teardown.ps1:224#-File`, `scripts/teardown.ps1:225#-Filter` |

**Proof of ownership.** The script deletes only the RG named in `config.json`, custom policy objects whose name starts with `abw-`, and Entra objects tagged `abw-demo`, named `sg-abw-*` or carrying the demo company marker (`scripts/teardown.ps1:18-20#prove`, `scripts/teardown.ps1:92-98#abw-`). Entra teardown deletes apps tagged `abw-demo` and users carrying the company marker, removes both from the deleted-items bin, and deletes groups whose name starts with `sg-abw-` (`identity/Setup-Entra.ps1:289-302#Invoke-Teardown`). The `-WhatIf` plan line for step 5 names only the initiative and the two `abw-foundry-*` definitions, but the list printed just above the plan is the set that a real run deletes (`scripts/teardown.ps1:97-98#Subscription-scope`, `scripts/teardown.ps1:129#policyInitiative`).

**Platform behaviour.** A deleted Log Analytics workspace is kept in soft-delete for 14 days unless it is deleted permanently (https://learn.microsoft.com/azure/azure-monitor/logs/delete-workspace). A soft-deleted Key Vault is recoverable for 7 to 90 days and its name cannot be reused until the retention period ends (https://learn.microsoft.com/azure/key-vault/general/soft-delete-overview).

**Not removed.** The Entra agent identities and blueprints that Foundry creates for the four agents are not tagged, so teardown leaves them; they need a manual check (`README.md:159#blueprint`).

**Kill switch and client allow-list.** These two scripts write APIM named values and never redeploy.

| Script | Writes | Effect | Source |
|---|---|---|---|
| `scripts/kill-switch.ps1` | the named value `abw-deny-oids` | the gateway returns HTTP 403 with reason `revoked` for the listed users; `-User`, `-RevokeSessions`, `-Restore`, `-Reset`, `-Show`; the first refusal appears in about 45-90 s | `scripts/kill-switch.ps1:8#abw-deny-oids`, `scripts/kill-switch.ps1:43#nvId`, `scripts/kill-switch.ps1:63-74#Get-DenyList`, `scripts/kill-switch.ps1:109-116#RevokeSessions`, `DESIGN.md:176#kill-switch` |
| `scripts/client-allowlist.ps1` | the named value `abw-allowed-azp` | `-Block` removes a client app (alias or id) from the allow-list, `-Allow` adds it back, `-Reset` restores all three; an empty list is refused | `scripts/client-allowlist.ps1:8#abw-allowed-azp`, `scripts/client-allowlist.ps1:39#nvId`, `scripts/client-allowlist.ps1:64-66#Set-List` |

The kill switch does not reach the private MCP server because that path bypasses APIM (`DESIGN.md:107#kill`; section 13.3). More exactly, the named value `abw-deny-oids` is read in only two places, the MCP gateway policy and the agent front-door policy (`infra/apim/policies/mcp-jwt.policy.xml:37#abw-deny-oids`, `infra/apim/policies/agent-frontdoor.policy.xml:53#abw-deny-oids`). So it does not apply to the legacy keyed API either, which has no user token to test.

**Re-deploy.** After a teardown without `-CleanLocal`, `config.json` is kept, so names repeat; the purge step exists because soft-deleted names would block reuse. After `-CleanLocal`, the next `deploy.ps1` run writes a new `config.json` with a new 4-character suffix (`scripts/common.ps1:29-58#Get-AbwConfig`, `scripts/teardown.ps1:226#config.json`). A rebuild is described as a long afternoon with APIM alone taking 30 minutes or more (`docs/COST.md:44#teardown`).

### 4.11 Idempotency, resumability and known gotchas

**What this section proves.** Every stage can be re-run, most failures are transient and have a documented retry, and a short list of sharp edges is known and written down (`README.md:59#idempotent`).

**Idempotency by step.**

| Step | Re-run behaviour | Source |
|---|---|---|
| Bicep stages | declarative; the same template converges to the same state | `scripts/deploy.ps1:79-113#Invoke-Stage` |
| Entra Phase 1 | find-or-create; role and scope ids are deterministic; the secret is re-created only when missing or within 10 days of expiry | `identity/Setup-Entra.ps1:64-69#Find-One`, `identity/Setup-Entra.ps1:160-164#needSecret` |
| Entra Phase 2 | skip when the subject matches, replace when it differs | `identity/Setup-Entra.ps1:272-273#subject` |
| `build-images.ps1` | always builds a new timestamped tag | `scripts/build-images.ps1:20#yyyyMMdd-HHmmss` |
| seed job | upserts and overwrites | `src/seed/seed.py:183#overwrite` |
| `foundry-connections.ps1` | skips an existing connection unless `-Force` or `-Only`; `-Force` keeps a stored consent | `scripts/foundry-connections.ps1:81-82#Force`, `README.md:93#Force` |
| `create_agents.py` | publishes a new version every run | `src/agent/abw_agents.py:155-194#create_version` |
| `jumpbox.ps1` | leaves an existing VM alone unless `-Force`: it starts the VM if stopped and only verifies | `scripts/jumpbox.ps1:247-253#Force` |
| `jumpbox-console.ps1` | uploads the package when `-Force` is given, no hash is recorded, the hash differs or files are missing | `scripts/jumpbox-console.ps1:643#needPackage` |
| teardown | `-WhatIf` first; objects it cannot prove are never touched | `scripts/teardown.ps1:18-20#prove` |

**Retry mechanisms.** `Invoke-Retry` defaults to 8 attempts and waits 4 s times the attempt number after each failure, and a caller can change both numbers (`scripts/common.ps1:115-123#Invoke-Retry`). The observability stage retries once after 120 s (`scripts/deploy.ps1:173#Start-Sleep`). Run-command calls use `Invoke-Retry` with 8 attempts and 8 s times the attempt number (`scripts/jumpbox-console.ps1:410#Invoke-Retry`, `scripts/jumpbox.ps1:317#Invoke-Retry`). The agent scripts install a retrying DNS lookup (`src/agent/netfix.py:18#_retrying_getaddrinfo`). The orchestrator makes at most three attempts at a step, and retries only after a non-zero exit whose output matched a known transient error, waiting the step's retry delay (`scripts/Deploy-AgentWall.ps1:603#maxAttempts`, `scripts/Deploy-AgentWall.ps1:622-625#Transient`, `docs/SELF-DEPLOY.md:191#Retries`).

**Known gotchas.**

| Gotcha | What happens | What to do | Source |
|---|---|---|---|
| APIM is slow | 35-50 min planned, "30+ min" in the README | use `-NoWait` and poll, then re-run the stage normally because `-NoWait` writes no state file | `README.md:74#apim`, `scripts/deploy.ps1:90-94#no-wait` |
| First `governance` in a new tenant fails once | `CheckAccessPrincipalCreationConcurrencyError` | wait about 75 s and re-run (the orchestrator waits 90 s and retries) | `README.md:96#CheckAccessPrincipalCreationConcurrencyError`, `docs/RUNBOOK.md:301#CheckAccessPrincipalCreationConcurrencyError`, `docs/SELF-DEPLOY.md:178#governance` |
| Observability rules fail validation | the workspace functions are not yet resolvable | the stage waits 120 s and retries once | `scripts/deploy.ps1:160-176#Invoke-ObservabilityStage` |
| Resource group delete is slow | the message says 20-40 min; up to three attempts with a 300 s wait after each of the first two | wait; do not interrupt | `scripts/teardown.ps1:171-183#attempt` |
| Network stage after the jump box exists | the template declares four inline subnets, so a re-apply can conflict with the fifth, in-use jump subnet (inferred) | never re-run `deploy.ps1 -Stage network` while `snet-jump` exists | `docs/RUNBOOK.md:121#snet-jump`, `infra/01-network.bicep:148#vnet` |
| `-Force` does not reset consent | the stored token stays | delete the connection with the manual `az rest` call in the README, then re-run with `-Only <name>` | `README.md:93#Force`, `DESIGN.md:231#ARM-DELETE` |
| azd signs in to the wrong tenant | connection creation fails | azd has its own config folder; set `AZD_CONFIG_DIR` and use CLI auth | `README.md:94-95#AZD_CONFIG_DIR`, `docs/SELF-DEPLOY.md:176#azd` |
| Persona baseline after consent | roles are not in the consented token | apply the baseline before consenting | `README.md:92#Baseline` |
| Organisation baseline runs Modify before Deny | a Deny may be pre-empted | check the effective effect in the tenant | `README.md:97#Modify` |
| Guardrail fires intermittently | the preview guardrail does not stop every run | rely on the wall, not the guardrail | `README.md:98#guardrail`, `infra/06-governance.bicep:72-76#Preview` |
| Consent opens the wrong browser profile | `ask.py --open-consent` opens the default browser, which may be signed in as someone else | point Python at a private window of the right browser through `BROWSER` | `README.md:99#BROWSER` |
| Consent page loops or reports a redirect URI mismatch | the Foundry connection redirect URLs changed | run `foundry-connections.ps1 -Force` and redo the consents; the runbook says this re-creates the connections, the README says it overwrites in place (see Findings in section 13) | `docs/RUNBOOK.md:287#redirect`, `README.md:93#Force` |
| AI Search capacity | the primary region returned no capacity on build day | the Search location is a separate setting | `scripts/common.ps1:45#searchLocation`, `infra/foundry/PATCHES.md:16-25#searchLocation` |
| VM size not available | several VM families were not available to the subscription | the script falls back through three sizes | `scripts/jumpbox.ps1:64#sizeOrder`, `infra/07-jumpbox.bicep:56-60#NotAvailableForSubscription` |
| `apis` needs a versionless vendor key URI | rotating the key would otherwise need a redeploy | the URI comes from the apps stage output | `scripts/deploy.ps1:373-376#vendorKeySecretUri` |
| Seed job slow | the stage fails after 12 min if the job is not Succeeded | read the job logs and re-run the stage | `scripts/deploy.ps1:428-435#deadline` |

**Documentation mismatches** that affect a rebuild (each is listed with a line reference in section 13 Findings): the governance retry wait is 90 s in the orchestrator guide and about 75 s in the README and runbook; the README says the first agent run publishes 4 agents, but it publishes 3; the separate `observability` step in the README repeats work governance already did; the runbook quotes about 2 minutes for a jump box deploy where the orchestrator plan says 10-15 (`docs/RUNBOOK.md:308#Start-JumpBox`, `docs/SELF-DEPLOY.md:160-187#guardrail`); DESIGN.md says preflight does quota checks, but the code does not; and `deploy.ps1` points to DESIGN.md section 8 for the stage table, which is in section 10.

**Key takeaways**

- The build is a 22-step pipeline whose order is set by data dependencies: network, then Foundry, then the platform, then images and apps, then the gateway, then connections and agents, then governance, then the optional jump box and console (`docs/SELF-DEPLOY.md:160-187#guardrail`).
- Every Bicep stage goes through one function that writes a state file; `-WhatIf` and `-NoWait` write none, the vendor key reaches `az` through a short-lived file in the secrets folder, and state is local to the operator's machine (`scripts/deploy.ps1:79-113#Invoke-Stage`, `scripts/deploy.ps1:90-94#no-wait`, `scripts/deploy.ps1:112#finally`).
- Entra is built in two phases because a federated credential's subject is the UAMI principal id, which only exists after the platform stage (`identity/Setup-Entra.ps1:261-262#platform`, `identity/Setup-Entra.ps1:272-273#subject`).
- Images are built in ACR Tasks and pulled by managed identity; data is seeded by an in-VNet job because the data planes are private (`scripts/build-images.ps1:34#acr`, `infra/modules/mcp-app.bicep:45-48#registries`, `DESIGN.md:189#PE-only`).
- Foundry connections are created through an azd extension, not Bicep, and a stored consent survives `-Force`; the reason for azd is not stated in the repo (`README.md:93#Force`, `scripts/foundry-connections.ps1:85-97#azd`).
- Governance flips 11 platform controls to Deny and audits 8, and the legacy waiver expires 90 days after the stage runs (`infra/06a-policy-definitions.bicep:224-262#ai-local-auth-disabled`, `infra/06a-policy-definitions.bicep:267-297#ai-restrict-network`, `scripts/deploy.ps1:448#legacyWaiverExpiry`, `infra/06-governance.bicep:28#legacyWaiverExpiry`).
- Teardown deletes only what it can prove is the demo's, in an order that releases the agent subnet first and purges soft-deleted names last (`scripts/teardown.ps1:7-16#Order`, `scripts/teardown.ps1:18-20#prove`).
- The slow or fragile points are APIM, the first-tenant RBAC race, consent, and soft-deleted names; each has a documented retry or workaround (`README.md:96#CheckAccessPrincipalCreationConcurrencyError`, `scripts/teardown.ps1:171-183#attempt`).

---

[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [3. Infrastructure and network design](03-infrastructure-and-network.md) | Next: [5. Identity objects and entitlement model](05-identity-objects.md)
