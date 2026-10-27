[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [13. Operations, cost, limits and known gaps](13-operations-cost-and-limits.md) | Next: [Appendix B. Findings register](appendix-b-findings-register.md)

## Appendix A. Repository file index

**Scope and conventions.** This appendix lists every folder and file group of the repository so a reader can find the code behind any statement in this reference; the lists that decide which folders are private live at `scripts/share_check.py:33-36#PRIVATE_DIRS`. Paths are repo-relative. Every purpose is **Implemented** (read from the file itself) unless a row says **Inferred**. The last column gives one or more citations per main file. Dotfiles, extension-less files (such as a Dockerfile) and binaries cannot carry a line citation, so those rows are described without line numbers and point at a citable neighbour instead. The private folders themselves are described in A.11 and never cited.

### A.1 Repository root

**What this section proves.** The root holds two top-level documents, one pinned dependency list and three Windows launchers, so each task has one starting file (`README.md:55#Quickstart`).

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `README.md` | Front page: the thesis, the six questions and where each is answered, what is deployed, prerequisites, quickstart, demo paths, a repo map, honest edges, teardown and the sharing warning. | `README.md:1#Agents`; `README.md:10#thesis`; `README.md:27#questions`; `README.md:42#deployed`; `README.md:46#Prerequisites`; `README.md:55#Quickstart`; `README.md:103#demo`; `README.md:121#Repo`; `README.md:138#Honest`; `README.md:152#Teardown`; `README.md:161#share` |
| `DESIGN.md` | Design contract as built: thesis, the four walls, naming, identities and roles, the four-hop token chain, MCP servers and tools, variables, Foundry objects, governance and observability, deploy stages, proof scenarios, learnings and honest edges. | `DESIGN.md:7#Thesis`; `DESIGN.md:26#walls`; `DESIGN.md:70#Identities`; `DESIGN.md:100#Token`; `DESIGN.md:114#MCP`; `DESIGN.md:158#Governance`; `DESIGN.md:178#Deploy`; `DESIGN.md:198#Proof`; `DESIGN.md:234#Honest` |
| `requirements.txt` | Python packages for the operator tooling, the proof harness, the deck builder and the Demo Console, each pinned to the versions the recorded 18/18 proof run used (Python 3.11). The MCP image (`src/mcp/pyproject.toml`) and the seed job (`src/seed/requirements.txt`) keep their own lists. | `requirements.txt:4#azure-identity`; `requirements.txt:5#azure-ai-projects`; `requirements.txt:8#msal`; `requirements.txt:11#PyJWT`; `requirements.txt:13#python-pptx`; `requirements.txt:15#starlette`; `requirements.txt:16#uvicorn` |
| `Start-Console.bat` | Launcher for the Demo Console: needs the project virtual env, prints one-time setup help when it is missing, then runs the console server with any arguments passed through. | `Start-Console.bat:18#server.py` |
| `Start-JumpBox.bat` | Launcher that starts the jump box VM if it is stopped, opens the portal and copies the VM password to the clipboard; needs PowerShell 7. | `Start-JumpBox.bat:17#jumpbox.ps1` |
| `Deploy-JumpBox-Console.bat` | Launcher that pushes the Demo Console and the proof evidence to the jump box, installing the tools it needs, then verifies there; safe to re-run. Switches are passed through to the script. | `Deploy-JumpBox-Console.bat:19#jumpbox-console.ps1` |
| `.gitignore` | Keeps the local secrets folder, the archive folder, per-deployment state and logs, local env and override files, the console's last-run file, the virtual env, caches, raw evidence and rendered deck output out of version control; exceptions keep an empty marker file in the two state folders. A dotfile, so it cannot be line-cited (it is 25 lines long). | not line-citable; the matching share-safety lists are `scripts/share_check.py:33-35#PRIVATE_DIRS` and `scripts/share_check.py:36#KEEP_EMPTY` |

### A.2 Documentation and the diagram toolchain (docs)

**What this section proves.** Each long-form guide serves one audience, and the diagram set is generated from code instead of being drawn by hand (`docs/diagrams/build_diagrams.py:39#build_scene`).

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `docs/ARCHITECTURE-AND-DESIGN.md` and `docs/architecture/` | This document: the index page (chapter list, contents, sections 0 and 1) and one file per other chapter, split because GitHub does not render a Markdown file larger than 512 KB. Every citation in it is machine-checked and the text is scanned for deployment identifiers. | the checks are `scripts/check_citations.py:1-14#Citation` and `scripts/share_check.py:1-17#Share-readiness` (section 0.5) |
| `docs/COST.md` | What the demo costs to run: the monthly estimate if left running, the levers in order of impact, where the money goes, how to see the real number, agent spend and the budget, and what to tell a customer. | `docs/COST.md:1#costs`; `docs/COST.md:9#Monthly`; `docs/COST.md:40#Levers`; `docs/COST.md:51#Where`; `docs/COST.md:63#real`; `docs/COST.md:70#Agent`; `docs/COST.md:77#customer` |
| `docs/CUSTOMER-GUIDE.md` | Guide for taking the platform to a Capital Markets customer: positioning, who to talk to, discovery questions, objections, regulatory themes, the two-week assessment offer, what is live, service status, what can be shared and pitfalls. | `docs/CUSTOMER-GUIDE.md:1#CUSTOMER`; `docs/CUSTOMER-GUIDE.md:95#offer` |
| `docs/DEMO-GUIDE.md` | Operator guide: Part A is the Demo Console path, Part B the terminal backup; it also covers the jump box and the fallbacks. | `docs/DEMO-GUIDE.md:1#DEMO`; `docs/DEMO-GUIDE.md:22#Demo`; `docs/DEMO-GUIDE.md:303#terminal` |
| `docs/PROOF-PLAYBOOK.md` | Tell it, show it, prove it: the act-by-act playbook behind the proof harness. | `docs/PROOF-PLAYBOOK.md:1#PROOF`; `docs/PROOF-PLAYBOOK.md:566#Act`; `docs/PROOF-PLAYBOOK.md:912#Act` |
| `docs/RUNBOOK.md` | Operations runbook: the 60-second version, the identity-path decision, one-time prep, the jump box, countdown, stage cheat sheet, fallbacks, troubleshooting and after-the-talk steps. | `docs/RUNBOOK.md:1#RUNBOOK`; `docs/RUNBOOK.md:23#Decide`; `docs/RUNBOOK.md:82#Jump`; `docs/RUNBOOK.md:180#Stage`; `docs/RUNBOOK.md:258#Fallbacks`; `docs/RUNBOOK.md:275#Troubleshooting` |
| `docs/SELF-DEPLOY.md` | Self-deployment guide for the one-command orchestrator: what you get, prerequisites, quick start, the readiness check, the step list, options, interrupted runs, the manual path, cost control and teardown, troubleshooting. | `docs/SELF-DEPLOY.md:1#Self-deployment`; `docs/SELF-DEPLOY.md:156#steps`; `docs/SELF-DEPLOY.md:259#Interrupted`; `docs/SELF-DEPLOY.md:346#Cost` |
| `docs/TALK-TRACK.md` | The 30-minute spoken script. | `docs/TALK-TRACK.md:1#TALK`; `docs/TALK-TRACK.md:28#Run`; `docs/TALK-TRACK.md:257#bank` |
| `docs/TALK-TRACK-PORTAL-TOUR.md` | A portal-driven talk track with click paths. | `docs/TALK-TRACK-PORTAL-TOUR.md:1#portal-tour`; `docs/TALK-TRACK-PORTAL-TOUR.md:861#click-path` |

**Diagram toolchain (docs/diagrams).** The builders are the source; the scene, SVG and PNG files are generated output. The `NAMES` list holds 13 diagrams, and each has a builder module `dgNN.py` with its scene, SVG and PNG files in the tree (`docs/diagrams/build_diagrams.py:28-33#NAMES`).

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `docs/diagrams/README.md` | Guide to the diagram set: the three files per diagram, an index of what each diagram shows and which sections of this document it supports, how to open, regenerate and self-check them, the colour legend, and the editing and content rules. | `docs/diagrams/README.md:1#Excalidraw`; `docs/diagrams/README.md:14#Index`; `docs/diagrams/README.md:40#How to open`; `docs/diagrams/README.md:53#How to regenerate`; `docs/diagrams/README.md:72#Self-check`; `docs/diagrams/README.md:88#Colour legend`; `docs/diagrams/README.md:134#Content rules` |
| `docs/diagrams/build_diagrams.py` | Generator and self-check for the whole set (standard library only): builds each scene, writes the scene file, the SVG and a PNG preview, then runs the layout lint and the validator; the exit code is non-zero on any failure. | `docs/diagrams/build_diagrams.py:28-33#NAMES`; `docs/diagrams/build_diagrams.py:39-46#KeyError`; `docs/diagrams/build_diagrams.py:64-66#CROPS`; `docs/diagrams/build_diagrams.py:69#main`; `docs/diagrams/build_diagrams.py:113-116#KeyError`; `docs/diagrams/build_diagrams.py:119-122#write_text` |
| `docs/diagrams/excal.py` | Small Excalidraw toolkit: the scene model, a text-fit and overlap lint, SVG export and the headless-Edge PNG step. | `docs/diagrams/excal.py:34#TOP`; `docs/diagrams/excal.py:37#KINDS`; `docs/diagrams/excal.py:146#Scene`; `docs/diagrams/excal.py:702#lint_scene`; `docs/diagrams/excal.py:827#to_svg`; `docs/diagrams/excal.py:889#svg_to_png` |
| `docs/diagrams/validate_excalidraw.py` | Standalone validator for the scene files: JSON shape, unique ids, bindings, ASCII only, no GUIDs and none of the strings the share rules forbid. | `docs/diagrams/validate_excalidraw.py:28#FORBIDDEN`; `docs/diagrams/validate_excalidraw.py:69#validate_data`; `docs/diagrams/validate_excalidraw.py:189#validate_file`; `docs/diagrams/validate_excalidraw.py:197#main` |
| `docs/diagrams/dg01.py` | Builder for diagram 01, system architecture. | `docs/diagrams/dg01.py:7#build` |
| `docs/diagrams/dg02.py` | Builder for diagram 02, network topology. | `docs/diagrams/dg02.py:195#build` |
| `docs/diagrams/dg03.py` | Builder for diagram 03, request data flow. | `docs/diagrams/dg03.py:7#build` |
| `docs/diagrams/dg04.py` | Builder for diagram 04, authentication flow. | `docs/diagrams/dg04.py:9#build` |
| `docs/diagrams/dg05.py` | Builder for diagram 05, authorization layers. | `docs/diagrams/dg05.py:85#build` |
| `docs/diagrams/dg06.py` | Builder for diagram 06, identity and entitlements. | `docs/diagrams/dg06.py:87#build` |
| `docs/diagrams/dg07.py` | Builder for diagram 07, token anatomy. | `docs/diagrams/dg07.py:123#build` |
| `docs/diagrams/dg08.py` | Builder for diagram 08, the scenarios of Acts 1 to 7. | `docs/diagrams/dg08.py:387#build` |
| `docs/diagrams/dg09.py` | Builder for diagram 09, observability and correlation. | `docs/diagrams/dg09.py:135#build` |
| `docs/diagrams/dg10.py` | Builder for diagram 10, the deployment pipeline. | `docs/diagrams/dg10.py:254#build` |
| `docs/diagrams/dg11.py` | Builder for diagram 11, the agent front door. | `docs/diagrams/dg11.py:108#build` |
| `docs/diagrams/dg12.py` | Builder for diagram 12, the Demo Console. | `docs/diagrams/dg12.py:129#build` |
| `docs/diagrams/dg13.py` | Builder for diagram 13, trust boundaries and failure modes. | `docs/diagrams/dg13.py:225#build` |
| `docs/diagrams/` scene files (NN-name pairs of scene and SVG) | The 13 generated scenes and their SVG renders, numbered 01 to 13; each name carries the diagram title. | written at `docs/diagrams/build_diagrams.py:119-122#write_text` |
| `docs/diagrams/png/` | PNG exports of the 13 scenes, rendered by a local headless Edge; the `_crops` subfolder holds scratch crops and is local-only (A.11). | `docs/diagrams/build_diagrams.py:124-125#PNG_DIR` |

### A.3 Identity (identity)

**What this section proves.** Every tenant-side object comes from one idempotent script, and a separate helper handles persona MFA seeds (`identity/Setup-Entra.ps1:104#Invoke-Phase1`).

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `identity/Setup-Entra.ps1` | Idempotent Entra setup in three modes. Phase 1 creates the six groups, the five persona users, the five API apps with their scopes and app roles, the client apps, the direct app-role assignments and the consent grants. Phase 2 adds the federated credentials from the managed identities once their principal ids exist. Teardown deletes every object tagged or named for this demo. | `identity/Setup-Entra.ps1:29#Apis`; `identity/Setup-Entra.ps1:46#OboResources`; `identity/Setup-Entra.ps1:48#Groups`; `identity/Setup-Entra.ps1:50#Users`; `identity/Setup-Entra.ps1:90#Get-OboTargets`; `identity/Setup-Entra.ps1:104#Invoke-Phase1`; `identity/Setup-Entra.ps1:258#Invoke-Phase2`; `identity/Setup-Entra.ps1:289#Invoke-Teardown` |
| `identity/Persona-Totp.py` | Stores each persona's TOTP seed in the local secrets store and prints or watches the current code, so a device-code sign-in during a demo is one paste; `login` also puts a persona password on the clipboard without printing it, and `selftest` runs the RFC 6238 vectors. | `identity/Persona-Totp.py:35#STORE`; `identity/Persona-Totp.py:36#PERSONAS`; `identity/Persona-Totp.py:44#totp`; `identity/Persona-Totp.py:73#cmd_set`; `identity/Persona-Totp.py:87#cmd_code`; `identity/Persona-Totp.py:97#cmd_watch`; `identity/Persona-Totp.py:113#cmd_login`; `identity/Persona-Totp.py:138#cmd_selftest` |
| `identity/Use-*AsPersona.ps1` | A dev and test helper that makes the signed-in operator mirror one persona's app roles and group memberships (`-As` a persona or none, `-Also` to add more), used when persona MFA is not enrolled yet. No citation is given because the file name trips the share-check word list. | none; the role and group sets it mirrors are at `identity/Setup-Entra.ps1:50#Users` |

### A.4 Infrastructure as code (infra)

**What this section proves.** Thirteen top-level templates, three shared modules, four gateway policies and one vendored Foundry template make up the whole infrastructure; the stages in section 4 deploy them (`scripts/deploy.ps1:79#Invoke-Stage`).

**Top-level templates.**

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `infra/01-network.bicep` | VNet with four subnets, the APIM NSG, the NAT public IP and gateway, 14 private DNS zones and their VNet links. | `infra/01-network.bicep:48-63#dnsZoneNames`; `infra/01-network.bicep:131#natGateway`; `infra/01-network.bicep:148#vnet`; `infra/01-network.bicep:223#zones`; `infra/01-network.bicep:229#zoneLinks` |
| `infra/02-foundry-rbac.bicep` | Foundry roles on the account and project (operator, all-users group) applied to resources the vendored template created. | `infra/02-foundry-rbac.bicep:17#account`; `infra/02-foundry-rbac.bicep:26#raOperatorAccount`; `infra/02-foundry-rbac.bicep:36#raConsumersProject` |
| `infra/03-platform.bicep` | Six UAMIs, Key Vault, ACR, Storage with four containers and a retention policy, Cosmos, AI Search, platform private endpoints, two Container Apps envs, diagnostics and RBAC. | `infra/03-platform.bicep:74#uamis`; `infra/03-platform.bicep:81#kv`; `infra/03-platform.bicep:108#acr`; `infra/03-platform.bicep:122#st`; `infra/03-platform.bicep:195#wormPolicy`; `infra/03-platform.bicep:205#cosmos`; `infra/03-platform.bicep:302#search`; `infra/03-platform.bicep:377#caePriv`; `infra/03-platform.bicep:399#caePub` |
| `infra/04-apps.bicep` | The vendor key secret and the six Container Apps, all from one module. | `infra/04-apps.bicep:43#vendorKeySecret`; `infra/04-apps.bicep:191#apps` |
| `infra/04b-seed-job.bicep` | The seed UAMI with its grants and the manual Container Apps job in the internal env that loads the synthetic data. | `infra/04b-seed-job.bicep:45#seedId`; `infra/04b-seed-job.bicep:101#seedJob` |
| `infra/05-apim.bicep` | The APIM service, its private endpoint, the App Insights logger, diagnostics, named values and API Center. | `infra/05-apim.bicep:43#apim`; `infra/05-apim.bicep:65#apimPe`; `infra/05-apim.bicep:79#logger`; `infra/05-apim.bicep:236#apic` |
| `infra/05-apim-apis.bicep` | One MCP API, backend and policy per server (research, wall, actions, vendor), the legacy API with one subscription, and the OAuth protected-resource discovery APIs. | `infra/05-apim-apis.bicep:28#servers`; `infra/05-apim-apis.bicep:123#mcpApis`; `infra/05-apim-apis.bicep:149#mcpPolicies`; `infra/05-apim-apis.bicep:204#legacySub`; `infra/05-apim-apis.bicep:238#prmPolicies` |
| `infra/06a-policy-definitions.bicep` | Subscription-scope custom policy definitions and the initiative. | `infra/06a-policy-definitions.bicep:19#targetScope`; `infra/06a-policy-definitions.bicep:50#noKeyedConnections`; `infra/06a-policy-definitions.bicep:96#approvedMcpTargets`; `infra/06a-policy-definitions.bicep:168#initiative` |
| `infra/06-governance.bicep` | The initiative assignment, exemptions, the Foundry guardrail policy and diagnostic settings. | `infra/06-governance.bicep:86#guardrails`; `infra/06-governance.bicep:102#diagFoundry`; `infra/06-governance.bicep:177#assignment`; `infra/06-governance.bicep:232#exLegacyAccount` |
| `infra/06b-observability.bicep` | The KQL functions as saved searches, Sentinel onboarding with nine analytics rules, an action group, three alert rules and the cockpit workbook. | `infra/06b-observability.bicep:29#pack`; `infra/06b-observability.bicep:43#functions`; `infra/06b-observability.bicep:60#sentinel`; `infra/06b-observability.bicep:67#analyticsRules`; `infra/06b-observability.bicep:153#opsAlertRules`; `infra/06b-observability.bicep:193#cockpit` |
| `infra/07-jumpbox.bicep` | The jump subnet and NSG, NIC, Windows VM, auto-shutdown schedule and Bastion Developer. | `infra/07-jumpbox.bicep:124#jumpSubnet`; `infra/07-jumpbox.bicep:153#vm`; `infra/07-jumpbox.bicep:211#autoShutdown`; `infra/07-jumpbox.bicep:230#bastion` |
| `infra/08-agent-frontdoor.bicep` | Additive APIM front door for the Foundry agent: two named values, the API, its operations and policy. | `infra/08-agent-frontdoor.bicep:27#nvQuota`; `infra/08-agent-frontdoor.bicep:38#nvRpm`; `infra/08-agent-frontdoor.bicep:49#api`; `infra/08-agent-frontdoor.bicep:76#policy` |
| `infra/09-budget.bicep` | One monthly cost budget with threshold notifications; an alert, not a cap. | `infra/09-budget.bicep:14#monthlyBudgetUsd`; `infra/09-budget.bicep:24#budget` |

**Shared modules and gateway policies.**

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `infra/modules/pe.bicep` | One private endpoint with its DNS zone group, reused for every platform endpoint. | `infra/modules/pe.bicep:19#pe`; `infra/modules/pe.bicep:41#zoneGroup` |
| `infra/modules/aca-dns.bicep` | The private DNS zone of the internal Container Apps env: wildcard and apex A records and a VNet link. | `infra/modules/aca-dns.bicep:18#zone`; `infra/modules/aca-dns.bicep:24#wildcard`; `infra/modules/aca-dns.bicep:37#apex`; `infra/modules/aca-dns.bicep:50#link` |
| `infra/modules/mcp-app.bicep` | One Container App: UAMI, ACR pull by identity, single revision, probes and scale. | `infra/modules/mcp-app.bicep:24#containerApps`; `infra/modules/mcp-app.bicep:45-48#registries` |
| `infra/apim/policies/mcp-jwt.policy.xml` | Gateway policy for the MCP APIs: token validation, the deny list, the allowed-client list, a trace record, a rate limit and the request id header. | `infra/apim/policies/mcp-jwt.policy.xml:17#validate-jwt`; `infra/apim/policies/mcp-jwt.policy.xml:37#abw-deny-oids`; `infra/apim/policies/mcp-jwt.policy.xml:38#abw-allowed-azp`; `infra/apim/policies/mcp-jwt.policy.xml:57#trace`; `infra/apim/policies/mcp-jwt.policy.xml:81#rate-limit-by-key`; `infra/apim/policies/mcp-jwt.policy.xml:82#x-abw-request-id` |
| `infra/apim/policies/mcp-legacy.policy.xml` | Policy for the legacy API, which authenticates with a subscription key; the rate limit is keyed by subscription or client IP. | `infra/apim/policies/mcp-legacy.policy.xml:8#rate-limit-by-key` |
| `infra/apim/policies/prm.policy.xml` | Returns the OAuth protected-resource discovery document with a cache header. | `infra/apim/policies/prm.policy.xml:7#return-response`; `infra/apim/policies/prm.policy.xml:12#Cache-Control`; `infra/apim/policies/prm.policy.xml:19#authorization_servers` |
| `infra/apim/policies/agent-frontdoor.policy.xml` | Policy for the agent front door: token validation, the deny list, a per-minute call limit, an hourly token quota and a throttle response. | `infra/apim/policies/agent-frontdoor.policy.xml:18#validate-jwt`; `infra/apim/policies/agent-frontdoor.policy.xml:53#abw-deny-oids`; `infra/apim/policies/agent-frontdoor.policy.xml:95#rate-limit-by-key`; `infra/apim/policies/agent-frontdoor.policy.xml:96#llm-token-limit`; `infra/apim/policies/agent-frontdoor.policy.xml:160#return-response` |

**Vendored Foundry template (infra/foundry).** A vendored, patched copy of an upstream private-network agent sample, so the demo is reproducible and pinned; it reuses the VNet from `infra/01-network.bicep:148#vnet`. The 24 modules under `modules-network-secured/` are listed one per row.

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `infra/foundry/PATCHES.md` | Explains the vendoring: why the sample is copied in and which patches were applied. | `infra/foundry/PATCHES.md:1#Vendored`; `infra/foundry/PATCHES.md:3#foundry-samples`; `infra/foundry/PATCHES.md:7#Why`; `infra/foundry/PATCHES.md:13#Patches` |
| `infra/foundry/main.bicep` | Entry template of the sample; 18 module declarations wire the account, project, state stores, private endpoints, monitoring and role assignments. | `infra/foundry/main.bicep:274#vnet`; `infra/foundry/main.bicep:309#aiAccount`; `infra/foundry/main.bicep:350#aiDependencies`; `infra/foundry/main.bicep:388#privateEndpointAndDNS`; `infra/foundry/main.bicep:455#monitorPrivateLink`; `infra/foundry/main.bicep:476#aiProject`; `infra/foundry/main.bicep:553#addProjectCapabilityHost` |
| `infra/foundry/modules-network-secured/ai-account-identity.bicep` | The Foundry account and the model deployment. | `infra/foundry/modules-network-secured/ai-account-identity.bicep:23#accounts`; `infra/foundry/modules-network-secured/ai-account-identity.bicep:57#deployments` |
| `infra/foundry/modules-network-secured/ai-project-identity.bicep` | The Foundry project. | `infra/foundry/modules-network-secured/ai-project-identity.bicep:37#projects` |
| `infra/foundry/modules-network-secured/ai-project-identity-unique.bicep` | A variant of the project module. **Inferred:** no template or script under `infra` or `scripts` references it. | `infra/foundry/modules-network-secured/ai-project-identity-unique.bicep:40#project` |
| `infra/foundry/modules-network-secured/add-project-capability-host.bicep` | The Agent Service capability host of the project. | `infra/foundry/modules-network-secured/add-project-capability-host.bicep:22#capabilityHosts` |
| `infra/foundry/modules-network-secured/format-project-workspace-id.bicep` | Formats the project workspace id as a GUID; declares no resource. | `infra/foundry/modules-network-secured/format-project-workspace-id.bicep:2#projectWorkspaceId`; `infra/foundry/modules-network-secured/format-project-workspace-id.bicep:12#projectWorkspaceIdGuid` |
| `infra/foundry/modules-network-secured/vnet.bicep` | The new-VNet path of the sample; not used here, because the foundry stage passes the existing VNet instead. | `infra/foundry/modules-network-secured/vnet.bicep:50#virtualNetwork`; `scripts/deploy.ps1:259#existingVnetResourceId` |
| `infra/foundry/modules-network-secured/existing-vnet.bicep` | The existing-VNet path this deployment uses: the agent, private-endpoint and MCP subnets. | `infra/foundry/modules-network-secured/existing-vnet.bicep:68#agentSubnet`; `infra/foundry/modules-network-secured/existing-vnet.bicep:88#peSubnet`; `infra/foundry/modules-network-secured/existing-vnet.bicep:104#mcpSubnet` |
| `infra/foundry/modules-network-secured/network-agent-vnet.bicep` | Chooses between the new and the existing VNet module. | `infra/foundry/modules-network-secured/network-agent-vnet.bicep:47#newVNet`; `infra/foundry/modules-network-secured/network-agent-vnet.bicep:63#existingVNet` |
| `infra/foundry/modules-network-secured/subnet.bicep` | Subnet helper used by the new-VNet path. | `infra/foundry/modules-network-secured/subnet.bicep:16#newSubnet` |
| `infra/foundry/modules-network-secured/private-dns-zone.bicep` | Private DNS zone helper. | `infra/foundry/modules-network-secured/private-dns-zone.bicep:31#newZone` |
| `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep` | Private endpoints and zone groups for the account and the three state stores. | `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:128#aiAccountPrivateEndpoint`; `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:150#aiSearchPrivateEndpoint`; `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:172#storagePrivateEndpoint`; `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:191#cosmosDBPrivateEndpoint`; `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:233#keyVaultPrivateEndpoint`; `infra/foundry/modules-network-secured/private-endpoint-and-dns.bicep:272#dnsZones` |
| `infra/foundry/modules-network-secured/standard-dependent-resources.bicep` | The agent-state Cosmos DB, AI Search and Storage, new or existing. | `infra/foundry/modules-network-secured/standard-dependent-resources.bicep:49#cosmosDB`; `infra/foundry/modules-network-secured/standard-dependent-resources.bicep:82#aiSearch`; `infra/foundry/modules-network-secured/standard-dependent-resources.bicep:122#storage` |
| `infra/foundry/modules-network-secured/key-vault.bicep` | Key Vault for the sample; switched off by the foundry stage. | `infra/foundry/modules-network-secured/key-vault.bicep:12#keyVault`; `scripts/deploy.ps1:265#enableKeyVault` |
| `infra/foundry/modules-network-secured/container-registry.bicep` | Container registry for the sample; switched off by the foundry stage. | `infra/foundry/modules-network-secured/container-registry.bicep:43#containerRegistry`; `scripts/deploy.ps1:266#enableContainerRegistry` |
| `infra/foundry/modules-network-secured/application-insights.bicep` | The Log Analytics workspace, a workspace-based App Insights component and the account connection to it. | `infra/foundry/modules-network-secured/application-insights.bicep:44#appInsights` |
| `infra/foundry/modules-network-secured/monitor-private-link-scope.bicep` | The Azure Monitor private link scope, its scoped resources and a private endpoint. | `infra/foundry/modules-network-secured/monitor-private-link-scope.bicep:59#ampls` |
| `infra/foundry/modules-network-secured/key-vault-role-assignment.bicep` | Key Vault secrets role for the project; skipped because the sample's vault is off. | `infra/foundry/modules-network-secured/key-vault-role-assignment.bicep:20#keyVaultSecretsUserRoleAssignment` |
| `infra/foundry/modules-network-secured/application-insights-role-assignment.bicep` | App Insights role for the project. | `infra/foundry/modules-network-secured/application-insights-role-assignment.bicep:25#appInsightsRoleAssignments` |
| `infra/foundry/modules-network-secured/ai-search-role-assignments.bicep` | Two AI Search roles for the project. | `infra/foundry/modules-network-secured/ai-search-role-assignments.bicep:20#searchIndexDataContributorAssignment`; `infra/foundry/modules-network-secured/ai-search-role-assignments.bicep:35#searchServiceContributorRoleAssignment` |
| `infra/foundry/modules-network-secured/cosmosdb-account-role-assignment.bicep` | Cosmos account-level role for the project. | `infra/foundry/modules-network-secured/cosmosdb-account-role-assignment.bicep:19#cosmosDBOperatorRoleAssignment` |
| `infra/foundry/modules-network-secured/cosmos-container-role-assignments.bicep` | Cosmos data-plane roles on the agent-state containers. | `infra/foundry/modules-network-secured/cosmos-container-role-assignments.bicep:24#containerRoleAssignmentUserContainer` |
| `infra/foundry/modules-network-secured/blob-storage-container-role-assignments.bicep` | Container-scoped Storage roles for the project. | `infra/foundry/modules-network-secured/blob-storage-container-role-assignments.bicep:26#storageBlobDataOwnerAssignment` |
| `infra/foundry/modules-network-secured/blob-storage-container-role-assignments-unique.bicep` | A variant of the container-role module. **Inferred:** not referenced by any template or script under `infra` or `scripts`. | `infra/foundry/modules-network-secured/blob-storage-container-role-assignments-unique.bicep:28#storageBlobDataOwnerAssignment` |
| `infra/foundry/modules-network-secured/azure-storage-account-role-assignment.bicep` | Account-level Storage role for the project. | `infra/foundry/modules-network-secured/azure-storage-account-role-assignment.bicep:16#storageBlobDataContributorRoleAssignmentProject` |

### A.5 Observability (observability)

**What this section proves.** Every query behind the cockpit, the alerts and the investigations is a plain file in the repo, and small generators turn those files into the JSON the Bicep loads (`infra/06b-observability.bicep:29#pack`).

**KQL function pack.** Each file starts with header comments (`@function`, `@params`, `@description`, `@fallback`); the pack generator reads them.

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `observability/kql/AbwAgentActivity.kql` | Which agent called which MCP tool for which user and what was decided, plus every agent run the guardrail stopped; joined on the request id. | `observability/kql/AbwAgentActivity.kql:1#AbwAgentActivity` |
| `observability/kql/AbwDenials.kql` | Every refusal across the four defence layers in one stream with the same columns. | `observability/kql/AbwDenials.kql:1#AbwDenials` |
| `observability/kql/AbwFullChain.kql` | The whole run for one id including the Entra sign-in and token rows read from the Entra sign-in export; with no export workspace it falls back to the core function. | `observability/kql/AbwFullChain.kql:1#AbwFullChain`; `observability/kql/pack.py:34#ENTRA_ENV` |
| `observability/kql/AbwFullChainCore.kql` | Everything one run touched in this workspace in time order, from any of its ids (request id, front-door id or trace id). | `observability/kql/AbwFullChainCore.kql:1#AbwFullChainCore` |
| `observability/kql/AbwGateway.kql` | The APIM gateway view of every MCP request and every agent front-door request, with decision and outcome. | `observability/kql/AbwGateway.kql:1#AbwGateway` |
| `observability/kql/AbwIdentityChain.kql` | The audit answer for one request id: the chain from agent through gateway and MCP server to the Storage data plane, with the identity each hop saw. | `observability/kql/AbwIdentityChain.kql:1#AbwIdentityChain` |
| `observability/kql/AbwMcpAudit.kql` | The MCP server audit trail, one row per tool listing, call or denial. | `observability/kql/AbwMcpAudit.kql:1#AbwMcpAudit` |
| `observability/kql/AbwTokenUsage.kql` | FinOps view: model tokens per user and agent per hour, measured at the agent front door. | `observability/kql/AbwTokenUsage.kql:1#AbwTokenUsage` |
| `observability/kql/AbwUsageByUser.kql` | Calls, denials, servers and tools per user; rows with no user are legacy-path calls. | `observability/kql/AbwUsageByUser.kql:1#AbwUsageByUser` |
| `observability/kql/AbwZeroKeys.kql` | Evidence that no Storage data-plane request is key-based, by authentication type. | `observability/kql/AbwZeroKeys.kql:1#AbwZeroKeys` |
| `observability/kql/pack.json` | Generated bundle of the ten functions that the observability template loads. | `observability/kql/pack.json:3#AbwGateway` |
| `observability/kql/pack.py` | The pack tool: `build` writes the bundle, `run` runs an ad-hoc query, `check` runs every function once. | `observability/kql/pack.py:30#PACK_JSON`; `observability/kql/pack.py:52#load_pack`; `observability/kql/pack.py:102#deploy_body`; `observability/kql/pack.py:125#cmd_build`; `observability/kql/pack.py:153#cmd_run`; `observability/kql/pack.py:160#cmd_check`; `observability/kql/pack.py:174#main` |

**Sentinel analytics rules.** Each rule file starts with header comments (`@id`, `@name`, `@severity`, `@tactics`, `@frequency`, `@period`, `@group`, `@entity`, `@details`, `@description`).

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `observability/sentinel/abw-001-wall-violation.kql` | ABW-001: an information-barrier violation attempt on the wall server (High). | `observability/sentinel/abw-001-wall-violation.kql:1-3#severity` |
| `observability/sentinel/abw-002-restricted-order.kql` | ABW-002: an order blocked on a restricted-list instrument (High). | `observability/sentinel/abw-002-restricted-order.kql:1-3#severity` |
| `observability/sentinel/abw-003-legacy-no-identity.kql` | ABW-003: a tool call on the legacy shared-key path with no user identity (Medium). | `observability/sentinel/abw-003-legacy-no-identity.kql:1-3#severity` |
| `observability/sentinel/abw-004-client-not-allowed.kql` | ABW-004: the gateway rejected a token from an unapproved client app (High). | `observability/sentinel/abw-004-client-not-allowed.kql:1-3#severity` |
| `observability/sentinel/abw-005-revoked-principal.kql` | ABW-005: a revoked principal is still calling the MCP APIs (High). | `observability/sentinel/abw-005-revoked-principal.kql:1-3#severity` |
| `observability/sentinel/abw-006-repeated-denials.kql` | ABW-006: repeated denials for one identity across layers (Medium). | `observability/sentinel/abw-006-repeated-denials.kql:1-3#severity` |
| `observability/sentinel/abw-007-entitlement-drift.kql` | ABW-007: entitlement drift, where the gateway and MCP allowed a call but storage RBAC denied the user (High). | `observability/sentinel/abw-007-entitlement-drift.kql:1-3#severity` |
| `observability/sentinel/abw-008-guardrail-intervention.kql` | ABW-008: the Foundry guardrail stopped an agent run, a prompt-injection indicator (High). | `observability/sentinel/abw-008-guardrail-intervention.kql:1-3#severity` |
| `observability/sentinel/abw-009-throttled-burst.kql` | ABW-009: a burst of throttled MCP calls from one identity (Low). | `observability/sentinel/abw-009-throttled-burst.kql:1-3#severity` |
| `observability/sentinel/rules.json` | Generated bundle of the nine rules that the observability template loads. | `observability/sentinel/rules.json:3#wall-violation` |
| `observability/sentinel/build_rules.py` | `build` writes the bundle from the rule files; `check` runs every rule query once. | `observability/sentinel/build_rules.py:30#RULES_JSON`; `observability/sentinel/build_rules.py:36#load_rules`; `observability/sentinel/build_rules.py:75#cmd_build`; `observability/sentinel/build_rules.py:82#cmd_check`; `observability/sentinel/build_rules.py:100#main` |

**Cockpit workbook.**

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `observability/workbook/build_workbook.py` | Generates the cockpit workbook as plain Azure Workbooks JSON; placeholders for the workspace, subscription and resource group are filled in by the Bicep at deploy time, and the tabs query the KQL function pack. | `observability/workbook/build_workbook.py:30#ASSIGNMENT`; `observability/workbook/build_workbook.py:127#tab_overview`; `observability/workbook/build_workbook.py:225#tab_identity`; `observability/workbook/build_workbook.py:291#tab_governance`; `observability/workbook/build_workbook.py:370#tab_threats`; `observability/workbook/build_workbook.py:439#tab_gateway`; `observability/workbook/build_workbook.py:494#tab_finops`; `observability/workbook/build_workbook.py:571#tab_keys`; `observability/workbook/build_workbook.py:619#tab_changes`; `observability/workbook/build_workbook.py:645#TABS`; `observability/workbook/build_workbook.py:657#build`; `observability/workbook/build_workbook.py:742#cmd_check` |
| `observability/workbook/cockpit.workbook.json` | The generated workbook template (a single line of JSON) that the observability template loads. | `observability/workbook/cockpit.workbook.json:1#Notebook` |

### A.6 Scripts (scripts)

**What this section proves.** Deployment, the kill switch, the allow-list, the jump box and teardown are re-runnable scripts built on one shared helper file (`scripts/common.ps1:29#Get-AbwConfig`).

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `scripts/common.ps1` | Helpers dot-sourced by the deploy, identity and operator scripts (for example `scripts/deploy.ps1:39#common.ps1`) but not by the scripts that run on the VM (`jumpbox-check.ps1`, `jumpbox-console-setup.ps1`, `jumpbox-console-start.ps1`) or by `demo/stage.ps1` and `deck/export.ps1`: step logging, JSON state read and write, the config loader, Graph token and call helpers with paging, retry, strong-password and deterministic-GUID helpers, the name table and the operator IP lookup. | `scripts/common.ps1:10#Write-Step`; `scripts/common.ps1:14#Save-Json`; `scripts/common.ps1:18#Read-Json`; `scripts/common.ps1:29#Get-AbwConfig`; `scripts/common.ps1:63#Get-GraphToken`; `scripts/common.ps1:71#Invoke-Graph`; `scripts/common.ps1:104#Get-GraphAll`; `scripts/common.ps1:115#Invoke-Retry`; `scripts/common.ps1:125#New-StrongPassword`; `scripts/common.ps1:137#New-DetGuid`; `scripts/common.ps1:147#Get-AbwNames`; `scripts/common.ps1:185#Get-OperatorIp`; `scripts/common.ps1:189#Get-AzJson` |
| `scripts/deploy.ps1` | The stage runner: parameter files, what-if, state capture and the stages preflight, network, foundry, foundryrbac, platform, apps, apim, apis, seed, governance, observability, frontdoor and budget (`scripts/deploy.ps1:32#preflight`). | `scripts/deploy.ps1:50#Write-ParamFile`; `scripts/deploy.ps1:63#New-ParamFile`; `scripts/deploy.ps1:73#Remove-SecretParamFile`; `scripts/deploy.ps1:79#Invoke-Stage`; `scripts/deploy.ps1:115#Invoke-SubscriptionStage`; `scripts/deploy.ps1:152#Build-ObservabilityArtifacts`; `scripts/deploy.ps1:162#Invoke-ObservabilityStage`; `scripts/deploy.ps1:178#Get-AllowedAzp`; `scripts/deploy.ps1:182#Get-VendorKey`; `scripts/deploy.ps1:187#Get-OperatorIpCached` |
| `scripts/Deploy-AgentWall.ps1` | The one-command orchestrator (section 4.9 describes it); it was still changing when this index was written. It resolves config, runs an Entra take-over guard, checks prerequisites, permissions, model capacity and a Bicep compile, runs the steps in order, verifies and prints next steps. | `scripts/Deploy-AgentWall.ps1:221#Get-RegionCode`; `scripts/Deploy-AgentWall.ps1:228#New-UniqueSuffix`; `scripts/Deploy-AgentWall.ps1:233#Test-AbwNameRules`; `scripts/Deploy-AgentWall.ps1:359#Get-StepTable`; `scripts/Deploy-AgentWall.ps1:448#Test-StepDone`; `scripts/Deploy-AgentWall.ps1:587#Invoke-Step`; `scripts/Deploy-AgentWall.ps1:683#Test-Prereqs`; `scripts/Deploy-AgentWall.ps1:877#Resolve-Config`; `scripts/Deploy-AgentWall.ps1:967#Test-EntraTakeoverGuard`; `scripts/Deploy-AgentWall.ps1:994#Test-Permissions`; `scripts/Deploy-AgentWall.ps1:1028#Test-ModelCapacity`; `scripts/Deploy-AgentWall.ps1:1070#Test-BicepCompile`; `scripts/Deploy-AgentWall.ps1:1147#Invoke-Verify`; `scripts/Deploy-AgentWall.ps1:1215#Show-NextSteps`; `scripts/Deploy-AgentWall.ps1:1270#Invoke-MainCore` |
| `scripts/Test-DeployOrchestrator.ps1` | Offline self-test of the orchestrator's logic. | `scripts/Test-DeployOrchestrator.ps1:37#Assert-That`; `scripts/Test-DeployOrchestrator.ps1:53#New-TestContext` |
| `scripts/build-images.ps1` | ACR Tasks builds with no local Docker: the default target builds the single `abw-mcp` image (six behaviours chosen by an env var at run time), `-Target seed` builds the seed image. | `scripts/build-images.ps1:7#abw-mcp`; `scripts/build-images.ps1:27#abw-seed`; `scripts/build-images.ps1:34#build` |
| `scripts/foundry-connections.ps1` | Creates one custom OAuth connection per MCP server plus the deliberately leaky legacy key connection. | `scripts/foundry-connections.ps1:55#Get-Scope`; `scripts/foundry-connections.ps1:71#Get-ConnectionArm` |
| `scripts/client-allowlist.ps1` | Edits the APIM allowed-client named value (the list of approved client app ids). | `scripts/client-allowlist.ps1:47#Resolve-Client`; `scripts/client-allowlist.ps1:53#Get-Label`; `scripts/client-allowlist.ps1:58#Get-List`; `scripts/client-allowlist.ps1:64#Set-List`; `scripts/client-allowlist.ps1:70#Write-List` |
| `scripts/kill-switch.ps1` | Edits the deny-list named value and can optionally revoke a user's sessions. | `scripts/kill-switch.ps1:43#nvId`; `scripts/kill-switch.ps1:45#Resolve-Oid`; `scripts/kill-switch.ps1:57#Get-Label`; `scripts/kill-switch.ps1:63#Get-DenyList`; `scripts/kill-switch.ps1:70#Set-DenyList`; `scripts/kill-switch.ps1:76#Write-List` |
| `scripts/teardown.ps1` | Ordered removal of the deployment, with `-WhatIf`, `-Yes`, `-KeepEntra`, `-SkipPurge` and `-CleanLocal`. | `scripts/teardown.ps1:57#policyInitiative`; `scripts/teardown.ps1:60#Invoke-AzJson`; `scripts/teardown.ps1:66#Invoke-AzRest`; `scripts/teardown.ps1:73#Test-RgExists` |
| `scripts/extras-agent-identity.ps1` | Optional extra (Track B): an Agent ID record, an Agent 365 RBAC pre-grant and a report-only Conditional Access policy. | `scripts/extras-agent-identity.ps1:47#Get-AzToken`; `scripts/extras-agent-identity.ps1:53#Invoke-Arm` |
| `scripts/extras-defender-sentinel.ps1` | Optional extra (Track B): Sentinel wiring, chat and jailbreak probes sent straight to the model deployment's chat completions endpoint (not through an agent or the gateway) and a Purview readiness read (audit-query API reachability, service plans and the operator's license). | `scripts/extras-defender-sentinel.ps1:255-255#chat/completions`; `scripts/extras-defender-sentinel.ps1:85#Get-Tok`; `scripts/extras-defender-sentinel.ps1:124#Invoke-Kql`; `scripts/extras-defender-sentinel.ps1:174#Ensure-SentinelWiring`; `scripts/extras-defender-sentinel.ps1:253#Invoke-ChatProbe`; `scripts/extras-defender-sentinel.ps1:275#Invoke-JailbreakProbes`; `scripts/extras-defender-sentinel.ps1:323#Get-PurviewState` |
| `scripts/jumpbox.ps1` | Deploys, verifies, starts, stops, shows status of and removes the jump box VM; can copy its password. | `scripts/jumpbox.ps1:79#Assert-AzContext`; `scripts/jumpbox.ps1:166#Invoke-JumpDeploy`; `scripts/jumpbox.ps1:235#Invoke-DeployAndVerify`; `scripts/jumpbox.ps1:307#Invoke-JumpVerify`; `scripts/jumpbox.ps1:389#Start-Jump`; `scripts/jumpbox.ps1:412#Stop-Jump`; `scripts/jumpbox.ps1:421#Show-Status`; `scripts/jumpbox.ps1:447#Copy-Password`; `scripts/jumpbox.ps1:468#Invoke-Remove` |
| `scripts/jumpbox-check.ps1` | Read-only reachability probe that runs inside the VM through run-command. | `scripts/jumpbox-check.ps1:12#Test-Tcp`; `scripts/jumpbox-check.ps1:21#Get-HttpStatus`; `scripts/jumpbox-check.ps1:31#Test-Endpoint` |
| `scripts/jumpbox-console.ps1` | Packages and pushes the Demo Console and the proof evidence to the VM, then checks, reports or removes it. | `scripts/jumpbox-console.ps1:241#Test-StageSafety`; `scripts/jumpbox-console.ps1:318#Build-Package`; `scripts/jumpbox-console.ps1:603#Invoke-DeployMode`; `scripts/jumpbox-console.ps1:727#Invoke-StatusMode`; `scripts/jumpbox-console.ps1:745#Invoke-VerifyMode`; `scripts/jumpbox-console.ps1:764#Invoke-RemoveConsole` |
| `scripts/jumpbox-console-setup.ps1` | The setup script that runs on the VM: probes, installs the tools, unpacks the package, builds the venv, writes the launcher, verifies and handles the persona files. | `scripts/jumpbox-console-setup.ps1:260#Invoke-Probe`; `scripts/jumpbox-console-setup.ps1:305#Invoke-Tools`; `scripts/jumpbox-console-setup.ps1:343#Invoke-Package`; `scripts/jumpbox-console-setup.ps1:389#Invoke-Venv`; `scripts/jumpbox-console-setup.ps1:424#Invoke-Launcher`; `scripts/jumpbox-console-setup.ps1:482#Invoke-Verify`; `scripts/jumpbox-console-setup.ps1:563#Invoke-Personas`; `scripts/jumpbox-console-setup.ps1:636#Invoke-Remove` |
| `scripts/jumpbox-console-start.ps1` | Starts the console on the VM and opens Edge on its local port (default 8787). | `scripts/jumpbox-console-start.ps1:20#Test-Console`; `scripts/jumpbox-console-start.ps1:27#Open-Edge` |
| `scripts/jumpbox_clip.py` | Private clipboard helper: reads the VM password from the local secrets store, copies it, and wipes the clipboard after a timeout. | `scripts/jumpbox_clip.py:30#read_password`; `scripts/jumpbox_clip.py:38#wipe`; `scripts/jumpbox_clip.py:49#copy`; `scripts/jumpbox_clip.py:72#main` |
| `scripts/check_citations.py` | Checks that every `path:START-END#symbol` citation in a document points at real lines containing the symbol, and flags private path prefixes, non-ASCII text, over-long spans and missing diagrams. | `scripts/check_citations.py:25#CITE`; `scripts/check_citations.py:26#HEADING`; `scripts/check_citations.py:27#DIAGRAM`; `scripts/check_citations.py:28#PRIVATE_PREFIXES`; `scripts/check_citations.py:51#check_doc`; `scripts/check_citations.py:103#main` |
| `scripts/share_check.py` | Learns this deployment's private values from local files, then scans or exports the shareable tree (`scan` and `export` subcommands). | `scripts/share_check.py:33#PRIVATE_DIRS`; `scripts/share_check.py:142#Sensitive`; `scripts/share_check.py:174#load_sensitive`; `scripts/share_check.py:240#is_private`; `scripts/share_check.py:254#iter_shareable`; `scripts/share_check.py:300#scan_tree`; `scripts/share_check.py:340#export_tree`; `scripts/share_check.py:360#main` |

### A.7 Application source (src)

**What this section proves.** One Python package becomes all six MCP servers, selected by an env var, and the agents, the tests and the seed data sit beside it (`src/mcp/README.md:3#MCP_SERVER`).

**Agents (src/agent).**

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `src/agent/abw_agents.py` | Definitions of the four prompt agents (the legacy POC agent, the wall desk, the red-team agent and its shielded variant), the guardrail policy name, the tool lists and the publish step. | `src/agent/abw_agents.py:35-39#POC_AGENT`; `src/agent/abw_agents.py:42#WALL_DESK_TOOLS`; `src/agent/abw_agents.py:49#APPROVAL_REQUIRED`; `src/agent/abw_agents.py:155#publish` |
| `src/agent/create_agents.py` | Entry point that publishes three agents (the legacy POC agent, the governed wall desk and the red-team agent); `--rai <policy>` also attaches the guardrail to the governed agent and publishes the fourth, shielded, red-team agent. | `src/agent/create_agents.py:28#main`; `src/agent/create_agents.py:30-30#--rai`; `src/agent/abw_agents.py:186-193#SHIELDED_AGENT` |
| `src/agent/ask.py` | Asks an agent a question as a persona or as the signed-in Azure CLI user. | `src/agent/ask.py:38#AZURE_CLI_CLIENT_ID`; `src/agent/ask.py:43#PersonaCredential`; `src/agent/ask.py:74#AzCliCacheCredential`; `src/agent/ask.py:109#build_credential`; `src/agent/ask.py:148#main` |
| `src/agent/netfix.py` | A retry shim for flaky local DNS resolvers. | `src/agent/netfix.py:18#_retrying_getaddrinfo`; `src/agent/netfix.py:31#install` |

**MCP server package (src/mcp).**

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `src/mcp/pyproject.toml` | Package definition for the `abw-mcp` image: dependencies, test extras and the package list. | `src/mcp/pyproject.toml:6#abw-mcp`; `src/mcp/pyproject.toml:19#mcp`; `src/mcp/pyproject.toml:35#packages` |
| `src/mcp/README.md` | Short guide to the package and the env var that selects the server. | `src/mcp/README.md:1#ABW`; `src/mcp/README.md:3#MCP_SERVER` |
| `src/mcp/Dockerfile` and `src/mcp/.dockerignore` | Image recipe on a Python 3.12 slim base image running as a non-root user, and its ignore list. No extension or a dotfile, so neither can be line-cited; the consumer is the image build. | not line-citable; built by `scripts/build-images.ps1:34#build` |
| `src/mcp/abw_mcp/__init__.py` | Package marker with the export list and version. | `src/mcp/abw_mcp/__init__.py:5#__all__`; `src/mcp/abw_mcp/__init__.py:7#__version__` |
| `src/mcp/abw_mcp/app.py` | ASGI app factory: the scope table per server, runtime assembly, the vendor-key middleware and `create_app`. | `src/mcp/abw_mcp/app.py:39#SERVER_SCOPES`; `src/mcp/abw_mcp/app.py:73#build_runtime`; `src/mcp/abw_mcp/app.py:115#VendorKeyMiddleware`; `src/mcp/abw_mcp/app.py:188#create_app` |
| `src/mcp/abw_mcp/auth.py` | JWT validation and the auth middleware: the caller model, the JWKS cache, `verify_token` and the request-context and bearer middlewares. | `src/mcp/abw_mcp/auth.py:30#Caller`; `src/mcp/abw_mcp/auth.py:44#AuthError`; `src/mcp/abw_mcp/auth.py:60#JwksCache`; `src/mcp/abw_mcp/auth.py:108#verify_token`; `src/mcp/abw_mcp/auth.py:173#RequestContextMiddleware`; `src/mcp/abw_mcp/auth.py:191#BearerAuthMiddleware` |
| `src/mcp/abw_mcp/audit.py` | The audit service and the append-blob sink that writes the audit trail as JSON lines to the `worm-audit` container, which carries a one-day time-based retention policy that is deliberately left unlocked. | `src/mcp/abw_mcp/audit.py:19#LOGGER_NAME`; `src/mcp/abw_mcp/audit.py:54#AppendBlobAuditSink`; `src/mcp/abw_mcp/audit.py:156#AuditService`; `src/mcp/abw_mcp/config.py:149#worm-audit`; `infra/03-platform.bicep:194-200#UNLOCKED` |
| `src/mcp/abw_mcp/config.py` | Env-backed settings for every server. | `src/mcp/abw_mcp/config.py:36#Settings` |
| `src/mcp/abw_mcp/data.py` | Thin data-plane helpers and the data-access error type. | `src/mcp/abw_mcp/data.py:31#DataAccessError`; `src/mcp/abw_mcp/data.py:43#DataPlaneClients` |
| `src/mcp/abw_mcp/obo.py` | The on-behalf-of token broker. | `src/mcp/abw_mcp/obo.py:39#OboBroker` |
| `src/mcp/abw_mcp/registry.py` | The tool registry, the role and scope requirements and the MCP list and call handlers. | `src/mcp/abw_mcp/registry.py:42#DENIED_CODES`; `src/mcp/abw_mcp/registry.py:98#require_any_role`; `src/mcp/abw_mcp/registry.py:111#require_scope_and_role`; `src/mcp/abw_mcp/registry.py:124#ToolRegistry` |
| `src/mcp/abw_mcp/runtime.py` | The bundle of services handed to every tool. | `src/mcp/abw_mcp/runtime.py:12#RuntimeServices` |
| `src/mcp/abw_mcp/util.py` | Canonical JSON and hashing helpers. | `src/mcp/abw_mcp/util.py:14#canonical_json`; `src/mcp/abw_mcp/util.py:20#sha256_json` |
| `src/mcp/abw_mcp/servers/__init__.py` | The list of server builders. | `src/mcp/abw_mcp/servers/__init__.py:1#builders` |
| `src/mcp/abw_mcp/servers/research.py` | The research server: public research notes. | `src/mcp/abw_mcp/servers/research.py:22#search_research`; `src/mcp/abw_mcp/servers/research.py:47#get_research_note` |
| `src/mcp/abw_mcp/servers/wall.py` | The wall server: documents on the wall-crossed deals. | `src/mcp/abw_mcp/servers/wall.py:13#PROJECT_TITLES`; `src/mcp/abw_mcp/servers/wall.py:29#caller_projects`; `src/mcp/abw_mcp/servers/wall.py:50#list_my_wall_crossings`; `src/mcp/abw_mcp/servers/wall.py:62#search_deal_documents`; `src/mcp/abw_mcp/servers/wall.py:88#get_deal_document` |
| `src/mcp/abw_mcp/servers/actions.py` | The actions server: the restricted-list check and orders. | `src/mcp/abw_mcp/servers/actions.py:44#check_restricted_list`; `src/mcp/abw_mcp/servers/actions.py:58#place_order`; `src/mcp/abw_mcp/servers/actions.py:113#list_my_orders` |
| `src/mcp/abw_mcp/servers/private.py` | The private server: firm positions and credit limits. | `src/mcp/abw_mcp/servers/private.py:19#get_firm_positions`; `src/mcp/abw_mcp/servers/private.py:37#get_credit_limit` |
| `src/mcp/abw_mcp/servers/vendor.py` | The vendor server: a synthetic external market-data mock reached through the gateway. | `src/mcp/abw_mcp/servers/vendor.py:30#get_market_quote`; `src/mcp/abw_mcp/servers/vendor.py:46#get_headlines` |
| `src/mcp/abw_mcp/servers/legacy.py` | The legacy server: the intentionally insecure "before" foil used by the proof-of-concept agent. | `src/mcp/abw_mcp/servers/legacy.py:45#search_research`; `src/mcp/abw_mcp/servers/legacy.py:86#place_order`; `src/mcp/abw_mcp/servers/legacy.py:114#build_tools` |

**MCP tests (src/mcp/tests).**

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `src/mcp/tests/__init__.py` | Package marker. | `src/mcp/tests/__init__.py:1#Test` |
| `src/mcp/tests/conftest.py` | Fixtures: a signing key, a patched JWKS, settings, a token factory and an app client. | `src/mcp/tests/conftest.py:143#signing_key`; `src/mcp/tests/conftest.py:148#patched_jwks`; `src/mcp/tests/conftest.py:156#settings_factory`; `src/mcp/tests/conftest.py:185#token_factory`; `src/mcp/tests/conftest.py:210#build_runtime`; `src/mcp/tests/conftest.py:221#app_client_factory`; `src/mcp/tests/conftest.py:236#auth_headers`; `src/mcp/tests/conftest.py:249#mcp_initialize` |
| `src/mcp/tests/smoke_local.py` | A manual local smoke run with a fake JWKS and minted tokens. | `src/mcp/tests/smoke_local.py:29#make_settings`; `src/mcp/tests/smoke_local.py:54#install_fake_jwks`; `src/mcp/tests/smoke_local.py:60#mint_token`; `src/mcp/tests/smoke_local.py:80#main` |
| `src/mcp/tests/test_auth.py` | Token verification tests: valid, a matrix of bad tokens and garbage. | `src/mcp/tests/test_auth.py:10#test_verify_token_valid`; `src/mcp/tests/test_auth.py:31#test_verify_token_matrix`; `src/mcp/tests/test_auth.py:39#test_verify_token_garbage` |
| `src/mcp/tests/test_config.py` | Settings tests: which servers need the validating app and which do not. | `src/mcp/tests/test_config.py:23#test_vendor_and_legacy`; `src/mcp/tests/test_config.py:38#test_token_validating_servers` |
| `src/mcp/tests/test_downstream.py` | Downstream-call tests: a header-safe request id, the blob read stamp and vendor-fixture isolation. | `src/mcp/tests/test_downstream.py:23#test_downstream_request_id_is_header_safe`; `src/mcp/tests/test_downstream.py:54#test_blob_read_stamps_gateway_request_id`; `src/mcp/tests/test_downstream.py:71#test_vendor_injection_fixture_is_isolated_to_nova` |
| `src/mcp/tests/test_servers.py` | Server behaviour tests: header semantics, role-filtered tool lists, wall isolation, storage RBAC denial, separation of duties, no fallback after an OBO failure, audit redaction, vendor key, discovery document, argument validation and strict denial mode. | `src/mcp/tests/test_servers.py:16#test_auth_header_semantics`; `src/mcp/tests/test_servers.py:33#test_role_filtered_tools_list`; `src/mcp/tests/test_servers.py:67#test_wall_isolation_and_audit`; `src/mcp/tests/test_servers.py:90#test_storage_rbac_denial_audited`; `src/mcp/tests/test_servers.py:109#test_restricted_list_and_separation_of_duties`; `src/mcp/tests/test_servers.py:141#test_obo_failure_does_not_fallback`; `src/mcp/tests/test_servers.py:160#test_audit_redacts_arguments_and_content`; `src/mcp/tests/test_servers.py:179#test_vendor_key_enforcement`; `src/mcp/tests/test_servers.py:195#test_prm_endpoint`; `src/mcp/tests/test_servers.py:208#test_argument_validation`; `src/mcp/tests/test_servers.py:234#test_strict_denial_mode_uses_mcp_is_error`; `src/mcp/tests/test_servers.py:252#test_entitled_to_nothing_sees_no_tools_and_cannot_call` |

**Seed job (src/seed).**

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `src/seed/seed.py` | The seed job: loads the markdown files, creates the Search index, uploads blobs, syncs the index and seeds Cosmos. | `src/seed/seed.py:32#DATA_ROOT`; `src/seed/seed.py:33#PLATFORM_JSON`; `src/seed/seed.py:37#SeedConfig`; `src/seed/seed.py:95#load_markdown_files`; `src/seed/seed.py:113#make_search_index`; `src/seed/seed.py:175#upload_blobs`; `src/seed/seed.py:188#sync_search_index`; `src/seed/seed.py:209#seed_cosmos`; `src/seed/seed.py:269#main` |
| `src/seed/requirements.txt` | The seed job's own dependency list. | `src/seed/requirements.txt:1#azure-identity`; `src/seed/requirements.txt:2#azure-storage-blob`; `src/seed/requirements.txt:3#azure-search-documents`; `src/seed/requirements.txt:4#azure-cosmos` |
| `src/seed/Dockerfile` and `src/seed/.dockerignore` | Image recipe and ignore list for the seed image; not line-citable. | not line-citable; built by `scripts/build-images.ps1:27#abw-seed` |
| `src/seed/data/research/` | Twelve synthetic public research notes (RN-001 to RN-012). | `src/seed/data/research/RN-001.md:3#ACME`; `src/seed/data/research/RN-012.md:3#Cross-sector` |
| `src/seed/data/wall-falcon/` | Six synthetic documents for the Falcon deal (FALCON-001 to FALCON-006). | `src/seed/data/wall-falcon/FALCON-001.md:4#FALCON-001` |
| `src/seed/data/wall-orion/` | Six synthetic documents for the Orion deal (ORION-001 to ORION-006). | `src/seed/data/wall-orion/ORION-001.md:4#ORION-001` |

### A.8 Demo Console (console)

**What this section proves.** The console is a local web app on the loopback interface with a job engine behind it and a plain-JavaScript front end that needs no bundler (`console/server.py:359#build_app`).

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `console/server.py` | The local Starlette web app, loopback only; it owns no state (jobs live in the job manager) and adds same-origin and security-header middleware. | `console/server.py:50#EVIDENCE`; `console/server.py:284#SameOriginMiddleware`; `console/server.py:301#SecurityHeadersMiddleware`; `console/server.py:359#build_app`; `console/server.py:394#ensure_az_login`; `console/server.py:418#main` |
| `console/catalog.py` | The story content: asks, scenes, beats, plain-English allow and deny reasons, architecture nodes and portal links. | `console/catalog.py:33#PROMPTS`; `console/catalog.py:46#REASONS`; `console/catalog.py:110#WALLS`; `console/catalog.py:118#explain`; `console/catalog.py:128#FRONT_DOOR_REFUSALS`; `console/catalog.py:192#ASKS`; `console/catalog.py:238#SCENES`; `console/catalog.py:888#NODES`; `console/catalog.py:1215#STRIP` |
| `console/jobs.py` | The job engine: one job is one button press, run in its own thread and polled by the browser; it keeps a small local state file and the table of runners. | `console/jobs.py:43#STATE_FILE`; `console/jobs.py:47#ALLOWED_AGENTS`; `console/jobs.py:48#ALLOWED_TOOLS`; `console/jobs.py:52#SERVERS`; `console/jobs.py:59#POISON`; `console/jobs.py:74#load_state`; `console/jobs.py:81#save_state`; `console/jobs.py:1276#run_allowlist`; `console/jobs.py:1304#run_kill`; `console/jobs.py:1401#RUNNERS` |
| `console/e2e.py` | Scene 6, "One request, every layer": the twelve layers, the log chain and the probes. | `console/e2e.py:44#PATH`; `console/e2e.py:45#WATCH`; `console/e2e.py:46#PROBE_IDS`; `console/e2e.py:49#LAYER_INFO`; `console/e2e.py:83#Q_CHAIN`; `console/e2e.py:1858#run_logs` |
| `console/act7.py` | Scene 7, "Roles and cost": the agent front door, the token quota and FinOps. | `console/act7.py:42#NV_QUOTA`; `console/act7.py:43#NV_RPM`; `console/act7.py:44#FRONTDOOR_API`; `console/act7.py:47#COST_TTL`; `console/act7.py:464#_month_cost`; `console/act7.py:547#run_finops`; `console/act7.py:711#run_quota` |
| `console/role_story.py` | Pure data for the Act 7 role tabs, with a coverage check and a verifier. | `console/role_story.py:14#MAX_BEAT_ID`; `console/role_story.py:63#TABS`; `console/role_story.py:136#BEATS`; `console/role_story.py:557#coverage`; `console/role_story.py:702#verify` |
| `console/role_tabs.py` | The positive and negative trace boards for each persona. | `console/role_tabs.py:27#WALL_WORD`; `console/role_tabs.py:33#DENIALS_BY_LAYER`; `console/role_tabs.py:552#SCENARIO_IDS` |
| `console/azure_probe.py` | Read-only probes behind the Control Room and "Prove it is real" drawers. | `console/azure_probe.py:31#GRAPH`; `console/azure_probe.py:32#LOGS`; `console/azure_probe.py:806#PROBES`; `console/azure_probe.py:833#run_probe` |
| `console/agent_run.py` | Runs one Foundry agent turn and prints one JSON event per line. | `console/agent_run.py:33#emit`; `console/agent_run.py:73#main` |
| `console/personas.py` | The persona switcher: device-code sign-in against the test client, TOTP codes and password copy. | `console/personas.py:42#TOTP_STORE`; `console/personas.py:43#PASSWORD_STORE`; `console/personas.py:52#STORY`; `console/personas.py:61#NeedsSignIn` |
| `console/smoke.py` | Runs one console job in-process without a browser. | `console/smoke.py:54#main` |
| `console/web/index.html` | The single page shell; the scripts load in the order util, render, strip, personas, pages, app. | `console/web/index.html:23#strip`; `console/web/index.html:29#util.js`; `console/web/index.html:34#app.js` |
| `console/web/util.js` | Shared browser helpers: the namespace, the API wrapper, tracking and job start. | `console/web/util.js:3#ABW`; `console/web/util.js:29#api`; `console/web/util.js:113#track`; `console/web/util.js:160#startJob` |
| `console/web/render.js` | Card renderers for verdicts, the full chain and traces. | `console/web/render.js:19#verdictCard`; `console/web/render.js:143#fullChainCard`; `console/web/render.js:331#traceCard` |
| `console/web/strip.js` | The architecture strip and the policy viewer. | `console/web/strip.js:91#TEMPLATE_OF`; `console/web/strip.js:115#policyViewer` |
| `console/web/personas.js` | The persona switcher UI and token verification. | `console/web/personas.js:114#act`; `console/web/personas.js:155#verifyToken`; `console/web/personas.js:365#init` |
| `console/web/pages.js` | The pages: start, scene, Control Room and scoreboard. | `console/web/pages.js:43#startPage`; `console/web/pages.js:437#scenePage`; `console/web/pages.js:466#controlRoom`; `console/web/pages.js:503#scoreboard` |
| `console/web/app.js` | Application bootstrap: the scene rail, running an operation and boot. | `console/web/app.js:58#buildRail`; `console/web/app.js:125#runOp`; `console/web/app.js:141#boot` |
| `console/web/style.css` | The stylesheet: root variables, wall colours and the top bar. | `console/web/style.css:2#root`; `console/web/style.css:6#--w1`; `console/web/style.css:22#topbar` |

### A.9 Demo, proof harness and scrubbed evidence (demo)

**What this section proves.** Every claim in the demo is executed against the live platform by `demo/prove.py:443#PROOFS`, and only a scrubbed copy of the results is shareable (`demo/scrub_evidence.py:54#Scrubber`).

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `demo/prove.py` | The proof harness: every claim is executed against the live platform (proofs P00 to P17) and each run writes an evidence JSON. | `demo/prove.py:43#EVIDENCE`; `demo/prove.py:75#EXPECT`; `demo/prove.py:87#now_utc`; `demo/prove.py:106#poll`; `demo/prove.py:116#with_retry`; `demo/prove.py:323#become`; `demo/prove.py:384#ask_agent`; `demo/prove.py:443#PROOFS`; `demo/prove.py:1132#ORDER`; `demo/prove.py:1135#run_proofs`; `demo/prove.py:1163#main` |
| `demo/scoreboard.py` | Merges the latest result of each proof into a scoreboard. | `demo/scoreboard.py:19#EXPECTED`; `demo/scoreboard.py:22#load_latest`; `demo/scoreboard.py:46#render` |
| `demo/scrub_evidence.py` | Makes the shareable copy: GUIDs become stable pseudonyms and the deployment suffix becomes xxxx. | `demo/scrub_evidence.py:36#GUID`; `demo/scrub_evidence.py:39#PUBLIC_IDS`; `demo/scrub_evidence.py:54#Scrubber`; `demo/scrub_evidence.py:108#main` |
| `demo/abw_tokens.py` | Standalone persona sign-in helper (MSAL password sign-in against the public test client). It reads the persona file at import, nothing imports it, and the jump-box package leaves it out. | `demo/abw_tokens.py:24#scope_for`; `demo/abw_tokens.py:28#get_token`; `demo/abw_tokens.py:37#claims`; `scripts/jumpbox-console.ps1:148-149#abw_tokens.py` |
| `demo/mcpclient.py` | A minimal MCP client and token helpers for talking to a server directly. | `demo/mcpclient.py:47#scope_for`; `demo/mcpclient.py:51#claims`; `demo/mcpclient.py:88#persona_token`; `demo/mcpclient.py:124#rpc`; `demo/mcpclient.py:143#call_tool` |
| `demo/arg.py` | An Azure Resource Graph query helper. | `demo/arg.py:40#query_rows` |
| `demo/kql.py` | Runs KQL against the platform workspace. | `demo/kql.py:33#workspace_customer_id`; `demo/kql.py:63#query_rows` |
| `demo/burst.py` | The runaway-agent simulation: proof P14 stand-alone, about four seconds. | `demo/burst.py:30#main` |
| `demo/try-violations.py` | Makes the ARM writes that Azure Policy should refuse, the source of the policy proof. | `demo/try-violations.py:76#attempts`; `demo/try-violations.py:318#run_attempt`; `demo/try-violations.py:434#main` |
| `demo/stage.ps1` | Dot-sourced presenter helpers, one `abw-` function per demo move. | `demo/stage.ps1:42#abw-help`; `demo/stage.ps1:71#abw-ask`; `demo/stage.ps1:145#abw-kill`; `demo/stage.ps1:155#abw-allow`; `demo/stage.ps1:166#abw-burst`; `demo/stage.ps1:177#abw-kql`; `demo/stage.ps1:202#abw-chain`; `demo/stage.ps1:226#abw-warm` |
| `demo/evidence-scrubbed/README.md` | Explains the scrubbed evidence folder. | `demo/evidence-scrubbed/README.md:1#Scrubbed` |
| `demo/evidence-scrubbed/SCOREBOARD.md` | The rendered scoreboard: 18 of 18 proofs and 109 of 109 checks passing. | `demo/evidence-scrubbed/SCOREBOARD.md:1#proof`; `demo/evidence-scrubbed/SCOREBOARD.md:3#proofs` |
| `demo/evidence-scrubbed/scoreboard.json` | The scoreboard as data, one object per proof. | `demo/evidence-scrubbed/scoreboard.json:3#P00` |
| `demo/evidence-scrubbed/prove-*.json` | One scrubbed proof run (a single file). | `demo/evidence-scrubbed/prove-20261022-172919.json:7#P00` |
| `demo/evidence-scrubbed/try-violations-*.json` | One scrubbed policy-violation run (a single file). | `demo/evidence-scrubbed/try-violations-20261022-174305.json:3#assignment` |
| `demo/evidence-scrubbed/` agent-run files | Eight scrubbed agent runs, named by time and agent. | `demo/evidence-scrubbed/20261022-123053-abw-wall-desk-operator.json:3#agent` |

### A.10 Slide deck (deck)

**What this section proves.** The deck is built from code with native shapes and no template, so it can be regenerated and exported (`deck/build_deck.py:24#OUT`).

| Path | Purpose | Key symbols (cited) |
|---|---|---|
| `deck/build_deck.py` | Builds the SE weekly deck with python-pptx from native shapes; console screenshots are read from a local folder. | `deck/build_deck.py:24#OUT`; `deck/build_deck.py:25#SCREENS`; `deck/build_deck.py:145#table`; `deck/build_deck.py:195#Deck`; `deck/build_deck.py:237#build` |
| `deck/contact_sheet.py` | Builds contact sheets for visual QA of the rendered slides. | `deck/contact_sheet.py:14#num`; `deck/contact_sheet.py:18#main` |
| `deck/export.ps1` | Exports one PNG per slide and optionally a PDF, using the local PowerPoint. | `deck/export.ps1:19#PowerPoint`; `deck/export.ps1:22#Export`; `deck/export.ps1:23#SaveAs` |
| `deck/ABW-SE-Weekly.pptx` | The generated deck; a binary, so it cannot be line-cited. | built at `deck/build_deck.py:24#OUT` |
| `deck/ABW.pptx` | A second deck file; a binary. **Inferred:** no script or document in the repo references it, so its purpose is not stated. | not line-citable |

### A.11 Local-only and non-shareable folders

**What this section proves.** Which folders exist only on the operator machine and must never be copied into a shared export; the exclusion lists are code, not convention (`scripts/share_check.py:33-36#PRIVATE_DIRS`). These folders are described here and never cited.

| Path | What it holds | Produced by | Handling |
|---|---|---|---|
| `infra/generated/` | Per-deployment state JSON (one file per stage), logs and the generated config; values that identify one deployment. | the stage runner (`scripts/deploy.ps1:79#Invoke-Stage`) through the JSON writer (`scripts/common.ps1:14#Save-Json`) | Never share; excluded by the share-check list and by the ignore file. |
| the local, gitignored secrets folder | Persona sign-in material, the agent-client secret, TOTP seeds, the VM password and tool caches. | the identity script (`identity/Setup-Entra.ps1:104#Invoke-Phase1`), the TOTP helper (`identity/Persona-Totp.py:35#STORE`) and the clipboard helper (`scripts/jumpbox_clip.py:30#read_password`) | Never share; excluded by the share-check list. |
| local env files and local JSON overrides | Settings and secrets for one machine. | the operator | Excluded by name patterns (`scripts/share_check.py:35#PRIVATE_FILE_GLOBS`). |
| `.venv/` | The project virtual env built from the pinned requirements. | the one-time setup that `Start-Console.bat` prints when the env is missing | Never share; excluded by the share-check list. |
| `_archive/` | An archive of older local build output. **Inferred** from the folder name and the share-check list. | the operator | Never share; excluded by the share-check list. |
| `demo/evidence/` (raw) | One JSON per proof run, agent run and policy-violation run, with real ids. | the proof harness (`demo/prove.py:43#EVIDENCE`) | Never share; use the scrubbed copy made by `demo/scrub_evidence.py:54#Scrubber` (folder `demo/evidence-scrubbed/`). |
| `deck/png/`, `deck/*.pdf` and `deck/screens/` | Rendered slide images, the PDF export and console screenshots read by the deck builder. | `deck/export.ps1:22#Export` and `deck/build_deck.py:25#SCREENS` | Excluded by the share-check list and the ignore file. |
| `docs/diagrams/png/_crops/` and the temporary Edge profile folder next to the diagram builders | Scratch crops of single diagram regions, and the throwaway headless-browser profile used for the PNG step. | the `--crop` option and the PNG step, both removed by `docs/diagrams/build_diagrams.py:64-66#CROPS` (the profile path is `docs/diagrams/build_diagrams.py:36#PROFILE`) | Local scratch; the clean option removes both. |
| `__pycache__/`, `.pytest_cache/`, `node_modules/` | Tool caches and compiled bytecode. | Python, pytest and npm | Excluded by the share-check list (`scripts/share_check.py:33#PRIVATE_DIRS`). |
| `console/.state.json` | The console's last-run state: the agent route, the last cost reading, request-id tags and a violations path. | `console/jobs.py:43#STATE_FILE`, written by `console/jobs.py:81-90#save_state` | Never share; excluded by the share-check list (`scripts/share_check.py:35#PRIVATE_FILE_GLOBS`) and by the ignore file (Finding 22 in section 13, closed). It holds request ids and a month-to-date spend reading, no credential. |

### A.12 Find it fast

**What this section proves.** The shortest path from a question to the file that answers it, using only symbols verified above (`src/mcp/abw_mcp/auth.py:108#verify_token`).

| Question | Where to look | Key symbols (cited) |
|---|---|---|
| Where is a token validated at the gateway? | the MCP gateway policy | `infra/apim/policies/mcp-jwt.policy.xml:17#validate-jwt` |
| Where is a token validated inside a server? | the MCP package, auth module | `src/mcp/abw_mcp/auth.py:108#verify_token` |
| Where does a tool check the caller's app role? | the registry | `src/mcp/abw_mcp/registry.py:98#require_any_role` |
| Where is the on-behalf-of exchange? | the OBO broker | `src/mcp/abw_mcp/obo.py:39#OboBroker` |
| Where is an audit record written? | the audit sink | `src/mcp/abw_mcp/audit.py:54#AppendBlobAuditSink` |
| Which Entra apps, scopes and roles exist? | the identity script | `identity/Setup-Entra.ps1:29#Apis` |
| How are resource names derived? | the shared helpers | `scripts/common.ps1:147#Get-AbwNames` |
| How does one stage deploy? | the stage runner | `scripts/deploy.ps1:79#Invoke-Stage` |
| How does the one-command deployment choose its steps? | the orchestrator step table | `scripts/Deploy-AgentWall.ps1:359#Get-StepTable` |
| Which policy definitions and initiative are deployed? | the policy definitions template | `infra/06a-policy-definitions.bicep:168#initiative` |
| Where are the four agents defined? | the agent definitions | `src/agent/abw_agents.py:35-38#POC_AGENT` |
| How does a test obtain a persona token? | the demo MCP client | `demo/mcpclient.py:88#persona_token` |
| Where is each proof defined? | the proof harness | `demo/prove.py:443#PROOFS` |
| Where is the kill switch implemented? | the kill-switch script | `scripts/kill-switch.ps1:43#nvId` |
| How is the cockpit workbook generated? | the workbook builder | `observability/workbook/build_workbook.py:657#build` |
| How is the KQL function pack built? | the pack tool | `observability/kql/pack.py:125#cmd_build` |
| Where does the console start a job? | the runner table | `console/jobs.py:1401#RUNNERS` |
| Which paths does a share check refuse? | the share-check lists | `scripts/share_check.py:240#is_private` |

**Key takeaways**

- Four kinds of file stay off every shared copy: per-deployment state under `infra/generated/`, the local secrets folder, local env files and raw evidence; the lists are code at `scripts/share_check.py:33-36#PRIVATE_DIRS`, and the console's own last-run file `console/.state.json` is on them too (A.11, Finding 22 in section 13).
- Each layer has one entry point: the stage runner `scripts/deploy.ps1:79#Invoke-Stage` and the orchestrator `scripts/Deploy-AgentWall.ps1:1270#Invoke-MainCore`, identity `identity/Setup-Entra.ps1:104#Invoke-Phase1`, the server `src/mcp/abw_mcp/app.py:188#create_app`, the agents `src/agent/create_agents.py:28#main`, the console `console/server.py:418#main` and the proofs `demo/prove.py:1163#main`.
- One image serves six servers: the package in `src/mcp/abw_mcp/` is built once by `scripts/build-images.ps1:34#build`, and an env var picks the behaviour, so there is one place to read every tool.
- Observability is source files first: the ten KQL functions, nine Sentinel rules and the workbook are plain files that generators bundle for `infra/06b-observability.bicep:29#pack`.
- Known gaps in the tree: `deck/ABW.pptx` and the two `-unique` Bicep variants are unreferenced (**Inferred**); dotfiles and binaries cannot be line-cited, so their rows are verified by name only.

---

[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [13. Operations, cost, limits and known gaps](13-operations-cost-and-limits.md) | Next: [Appendix B. Findings register](appendix-b-findings-register.md)
