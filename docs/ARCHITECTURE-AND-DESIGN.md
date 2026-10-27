# Agents Behind the Wall: technical architecture and design

> Status: generated from the repository as it stands. Every behavioural statement carries a source
> citation of the form `path:START-END#symbol`.
>
> This page is the index of the document. GitHub does not render a Markdown file larger than 512 KB, so the
> chapters are separate files in `docs/architecture/`; sections 0 and 1 follow on this page. Section numbers are
> unique across the whole document, so "section 7.4" always means the section numbered 7.4, whichever file holds it.
>
> Re-check every citation yourself and confirm that nothing deployment-specific leaked (from the repository root,
> in PowerShell):
> `python scripts\check_citations.py (Get-ChildItem docs\ARCHITECTURE-AND-DESIGN.md, docs\architecture\*.md).FullName --strict-diagrams`
> and `python scripts\share_check.py scan docs`.
> Diagrams live in `docs/diagrams/` (Excalidraw sources, SVG and PNG exports).

## Chapters

- Sections 0 and 1 (About this document, Executive summary): below, on this page
- [2. System overview](architecture/02-system-overview.md)
- [3. Infrastructure and network design](architecture/03-infrastructure-and-network.md)
- [4. Deployment architecture](architecture/04-deployment.md)
- [5. Identity objects and entitlement model](architecture/05-identity-objects.md)
- [6. Authentication: identities, tokens and trust](architecture/06-authentication.md)
- [7. Authorization: the four walls and policy-as-code](architecture/07-authorization.md)
- [8. MCP server internals](architecture/08-mcp-server-internals.md)
- [9. Scenarios, part 1: how to read a scenario and Acts 1 to 3 (9.1 to 9.4)](architecture/09a-scenarios-acts-1-3.md)
- [9. Scenarios, part 2: Act 4 (9.5)](architecture/09b-scenarios-act-4.md)
- [9. Scenarios, part 3: Act 5 (9.6)](architecture/09c-scenarios-act-5.md)
- [9. Scenarios, part 4: Act 6 (9.7)](architecture/09d-scenarios-act-6.md)
- [9. Scenarios, part 5: Act 7, the front door and the person tabs (9.8 to 9.8.9)](architecture/09e-scenarios-act-7a.md)
- [9. Scenarios, part 6: Act 7, the admin tab, cost and evidence (9.8.10 to 9.8.15)](architecture/09f-scenarios-act-7b.md)
- [9. Scenarios, part 7: proof coverage (9.9 to 9.10)](architecture/09g-proof-coverage.md)
- [10. Data flow and correlation](architecture/10-data-flow-and-correlation.md)
- [11. Observability, detection and response](architecture/11-observability-and-response.md)
- [12. Demo Console architecture](architecture/12-demo-console.md)
- [13. Operations, cost, limits and known gaps](architecture/13-operations-cost-and-limits.md)
- [Appendix A. Repository file index](architecture/appendix-a-file-index.md)
- [Appendix B. Findings register](architecture/appendix-b-findings-register.md)

## Contents

- [0. About this document](#0-about-this-document)
  - [0.1 Purpose, audience and scope](#01-purpose-audience-and-scope)
  - [0.2 Document map](#02-document-map)
  - [0.3 Conventions](#03-conventions)
  - [0.4 Diagram index](#04-diagram-index)
  - [0.5 Verifying this document](#05-verifying-this-document)
  - [0.6 What this document is not](#06-what-this-document-is-not)
- [1. Executive summary](#1-executive-summary)
  - [1.1 The business problem](#11-the-business-problem)
  - [1.2 The solution on one page](#12-the-solution-on-one-page)
  - [1.3 What was built](#13-what-was-built)
  - [1.4 The seven acts](#14-the-seven-acts)
  - [1.5 What is proven](#15-what-is-proven)
  - [1.6 Honest limits](#16-honest-limits)
  - [1.7 Reading paths and next steps](#17-reading-paths-and-next-steps)
  - [1.8 Findings](#18-findings)
- [2. System overview](architecture/02-system-overview.md#2-system-overview)
  - [2.1 Purpose and design principles](architecture/02-system-overview.md#21-purpose-and-design-principles)
  - [2.2 Component inventory](architecture/02-system-overview.md#22-component-inventory)
  - [2.3 The four planes](architecture/02-system-overview.md#23-the-four-planes)
  - [2.4 Trust boundaries](architecture/02-system-overview.md#24-trust-boundaries)
  - [2.5 The four walls at a glance](architecture/02-system-overview.md#25-the-four-walls-at-a-glance)
  - [2.6 Naming, tagging and configuration conventions](architecture/02-system-overview.md#26-naming-tagging-and-configuration-conventions)
  - [2.7 Deployment-shape constraints](architecture/02-system-overview.md#27-deployment-shape-constraints)
- [3. Infrastructure and network design](architecture/03-infrastructure-and-network.md#3-infrastructure-and-network-design)
  - [3.1 VNet and subnets](architecture/03-infrastructure-and-network.md#31-vnet-and-subnets)
  - [3.2 Private endpoints and private DNS zones](architecture/03-infrastructure-and-network.md#32-private-endpoints-and-private-dns-zones)
  - [3.3 Egress](architecture/03-infrastructure-and-network.md#33-egress)
  - [3.4 Foundry account and project networking](architecture/03-infrastructure-and-network.md#34-foundry-account-and-project-networking)
  - [3.5 Container Apps envs and the six apps](architecture/03-infrastructure-and-network.md#35-container-apps-envs-and-the-six-apps)
  - [3.6 API Management](architecture/03-infrastructure-and-network.md#36-api-management)
  - [3.7 Data stores](architecture/03-infrastructure-and-network.md#37-data-stores)
  - [3.8 Monitoring plumbing](architecture/03-infrastructure-and-network.md#38-monitoring-plumbing)
  - [3.9 Jump box and Bastion](architecture/03-infrastructure-and-network.md#39-jump-box-and-bastion)
  - [3.10 Region, SKU and capacity decisions](architecture/03-infrastructure-and-network.md#310-region-sku-and-capacity-decisions)
- [4. Deployment architecture](architecture/04-deployment.md#4-deployment-architecture)
  - [4.1 Stage graph](architecture/04-deployment.md#41-stage-graph)
  - [4.2 How `Invoke-Stage` works](architecture/04-deployment.md#42-how-invoke-stage-works)
  - [4.3 Bicep module map](architecture/04-deployment.md#43-bicep-module-map)
  - [4.4 Image build with ACR Tasks and the seed job](architecture/04-deployment.md#44-image-build-with-acr-tasks-and-the-seed-job)
  - [4.5 Entra provisioning in sequence](architecture/04-deployment.md#45-entra-provisioning-in-sequence)
  - [4.6 Foundry connections and agent creation](architecture/04-deployment.md#46-foundry-connections-and-agent-creation)
  - [4.7 Governance stage](architecture/04-deployment.md#47-governance-stage)
  - [4.8 Jump box and console deployment path](architecture/04-deployment.md#48-jump-box-and-console-deployment-path)
  - [4.9 One-command deployment orchestrator](architecture/04-deployment.md#49-one-command-deployment-orchestrator)
  - [4.10 Teardown, kill switch and re-deploy](architecture/04-deployment.md#410-teardown-kill-switch-and-re-deploy)
  - [4.11 Idempotency, resumability and known gotchas](architecture/04-deployment.md#411-idempotency-resumability-and-known-gotchas)
- [5. Identity objects and entitlement model](architecture/05-identity-objects.md#5-identity-objects-and-entitlement-model)
  - [5.1 Entra groups](architecture/05-identity-objects.md#51-entra-groups)
  - [5.2 The five API apps](architecture/05-identity-objects.md#52-the-five-api-apps)
  - [5.3 Client apps](architecture/05-identity-objects.md#53-client-apps)
  - [5.4 Personas and the operator](architecture/05-identity-objects.md#54-personas-and-the-operator)
  - [5.5 Managed identities](architecture/05-identity-objects.md#55-managed-identities)
  - [5.6 Azure RBAC role assignments](architecture/05-identity-objects.md#56-azure-rbac-role-assignments)
  - [5.7 Entitlement model as built](architecture/05-identity-objects.md#57-entitlement-model-as-built)
  - [5.8 Lifecycle](architecture/05-identity-objects.md#58-lifecycle)
- [6. Authentication: identities, tokens and trust](architecture/06-authentication.md#6-authentication-identities-tokens-and-trust)
  - [6.1 Principals and credentials inventory](architecture/06-authentication.md#61-principals-and-credentials-inventory)
  - [6.2 Token inventory](architecture/06-authentication.md#62-token-inventory)
  - [6.3 User sign-in](architecture/06-authentication.md#63-user-sign-in)
  - [6.4 Foundry OAuth identity passthrough](architecture/06-authentication.md#64-foundry-oauth-identity-passthrough)
  - [6.5 APIM inbound authentication](architecture/06-authentication.md#65-apim-inbound-authentication)
  - [6.6 MCP server authentication](architecture/06-authentication.md#66-mcp-server-authentication)
  - [6.7 On-behalf-of with a federated managed identity](architecture/06-authentication.md#67-on-behalf-of-with-a-federated-managed-identity)
  - [6.8 Data-plane authentication](architecture/06-authentication.md#68-data-plane-authentication)
  - [6.9 Service-to-service and platform identities](architecture/06-authentication.md#69-service-to-service-and-platform-identities)
  - [6.10 Lifetimes, refresh, revocation and replay](architecture/06-authentication.md#610-lifetimes-refresh-revocation-and-replay)
  - [6.11 One governed tools/call, token by token](architecture/06-authentication.md#611-one-governed-toolscall-token-by-token)
  - [6.12 Findings](architecture/06-authentication.md#612-findings)
- [7. Authorization: the four walls and policy-as-code](architecture/07-authorization.md#7-authorization-the-four-walls-and-policy-as-code)
  - [7.1 Overview: four walls, one request](architecture/07-authorization.md#71-overview-four-walls-one-request)
  - [7.2 Layer 0, the Foundry guardrail](architecture/07-authorization.md#72-layer-0-the-foundry-guardrail)
  - [7.3 Layer 1, APIM](architecture/07-authorization.md#73-layer-1-apim)
  - [7.4 Layer 2, the MCP server](architecture/07-authorization.md#74-layer-2-the-mcp-server)
  - [7.5 Layer 3, the data plane](architecture/07-authorization.md#75-layer-3-the-data-plane)
  - [7.6 Entitlement matrix as built](architecture/07-authorization.md#76-entitlement-matrix-as-built)
  - [7.7 Azure Policy as code](architecture/07-authorization.md#77-azure-policy-as-code)
  - [7.8 Emergency controls](architecture/07-authorization.md#78-emergency-controls)
  - [7.9 Authorization gaps and trade-offs](architecture/07-authorization.md#79-authorization-gaps-and-trade-offs)
- [8. MCP server internals](architecture/08-mcp-server-internals.md#8-mcp-server-internals)
  - [8.1 Process and image](architecture/08-mcp-server-internals.md#81-process-and-image)
  - [8.2 Request lifecycle for tools/call](architecture/08-mcp-server-internals.md#82-request-lifecycle-for-toolscall)
  - [8.3 Server catalogue](architecture/08-mcp-server-internals.md#83-server-catalogue)
  - [8.4 The audit event](architecture/08-mcp-server-internals.md#84-the-audit-event)
  - [8.5 Error and denial taxonomy](architecture/08-mcp-server-internals.md#85-error-and-denial-taxonomy)
  - [8.6 Configuration surface](architecture/08-mcp-server-internals.md#86-configuration-surface)
  - [8.7 Tests under src/mcp/tests](architecture/08-mcp-server-internals.md#87-tests-under-srcmcptests)
  - [8.8 Extension guide](architecture/08-mcp-server-internals.md#88-extension-guide)
  - [8.9 Findings](architecture/08-mcp-server-internals.md#89-findings)
- [9. Scenarios: Acts 1 to 7 end to end](architecture/09a-scenarios-acts-1-3.md#9-scenarios-acts-1-to-7-end-to-end)
  - [9.1 How to read a scenario](architecture/09a-scenarios-acts-1-3.md#91-how-to-read-a-scenario)
  - [9.2 Act 1: Same question, two answers](architecture/09a-scenarios-acts-1-3.md#92-act-1-same-question-two-answers)
  - [9.3 Act 2: No keys](architecture/09a-scenarios-acts-1-3.md#93-act-2-no-keys)
  - [9.4 Act 3: Whose hands are on the data](architecture/09a-scenarios-acts-1-3.md#94-act-3-whose-hands-are-on-the-data)
  - [9.5 Act 4: When it goes wrong](architecture/09b-scenarios-act-4.md#95-act-4-when-it-goes-wrong)
  - [9.6 Act 5: What InfoSec sees](architecture/09c-scenarios-act-5.md#96-act-5-what-infosec-sees)
  - [9.7 Act 6: One request, every layer](architecture/09d-scenarios-act-6.md#97-act-6-one-request-every-layer)
  - [9.8 Act 7: Every role, the agent's front door, and the bill](architecture/09e-scenarios-act-7a.md#98-act-7-every-role-the-agents-front-door-and-the-bill)
  - [9.9 Proof coverage](architecture/09g-proof-coverage.md#99-proof-coverage)
  - [9.10 Findings](architecture/09g-proof-coverage.md#910-findings)
- [10. Data flow and correlation](architecture/10-data-flow-and-correlation.md#10-data-flow-and-correlation)
  - [10.1 Data flow of a governed tool call](architecture/10-data-flow-and-correlation.md#101-data-flow-of-a-governed-tool-call)
  - [10.2 Correlation keys](architecture/10-data-flow-and-correlation.md#102-correlation-keys)
  - [10.3 How `AbwFullChain` stitches the chain](architecture/10-data-flow-and-correlation.md#103-how-abwfullchain-stitches-the-chain)
  - [10.4 Ingestion latency and why the console polls and retries](architecture/10-data-flow-and-correlation.md#104-ingestion-latency-and-why-the-console-polls-and-retries)
  - [10.5 The exceptions: guardrail trace id, Entra token and session id, and the private server](architecture/10-data-flow-and-correlation.md#105-the-exceptions-guardrail-trace-id-entra-token-and-session-id-and-the-private-server)
  - [10.6 Classification and retention](architecture/10-data-flow-and-correlation.md#106-classification-and-retention)
- [11. Observability, detection and response](architecture/11-observability-and-response.md#11-observability-detection-and-response)
  - [11.1 Telemetry sources and tables](architecture/11-observability-and-response.md#111-telemetry-sources-and-tables)
  - [11.2 The ten KQL functions](architecture/11-observability-and-response.md#112-the-ten-kql-functions)
  - [11.3 The nine Sentinel analytics rules ABW-001 to ABW-009](architecture/11-observability-and-response.md#113-the-nine-sentinel-analytics-rules-abw-001-to-abw-009)
  - [11.4 The cockpit workbook](architecture/11-observability-and-response.md#114-the-cockpit-workbook)
  - [11.5 The three operational alert rules](architecture/11-observability-and-response.md#115-the-three-operational-alert-rules)
  - [11.6 Optional tenant-level portal features](architecture/11-observability-and-response.md#116-optional-tenant-level-portal-features)
  - [11.7 Proving a decision with only logs](architecture/11-observability-and-response.md#117-proving-a-decision-with-only-logs)
- [12. Demo Console architecture](architecture/12-demo-console.md#12-demo-console-architecture)
  - [12.1 Process model](architecture/12-demo-console.md#121-process-model)
  - [12.2 How personas sign in](architecture/12-demo-console.md#122-how-personas-sign-in)
  - [12.3 The modules](architecture/12-demo-console.md#123-the-modules)
  - [12.4 Evidence tags and replay](architecture/12-demo-console.md#124-evidence-tags-and-replay)
  - [12.5 Safety rails](architecture/12-demo-console.md#125-safety-rails)
  - [12.6 Jump-box installation of the console](architecture/12-demo-console.md#126-jump-box-installation-of-the-console)
  - [12.7 Findings](architecture/12-demo-console.md#127-findings)
- [13. Operations, cost, limits and known gaps](architecture/13-operations-cost-and-limits.md#13-operations-cost-limits-and-known-gaps)
  - [13.1 Cost model](architecture/13-operations-cost-and-limits.md#131-cost-model)
  - [13.2 Capacity and quota](architecture/13-operations-cost-and-limits.md#132-capacity-and-quota)
  - [13.3 Scale limits and design trade-offs](architecture/13-operations-cost-and-limits.md#133-scale-limits-and-design-trade-offs)
  - [13.4 The multi-deployment hazard](architecture/13-operations-cost-and-limits.md#134-the-multi-deployment-hazard)
  - [13.5 Security posture and residual risk](architecture/13-operations-cost-and-limits.md#135-security-posture-and-residual-risk)
  - [13.6 Failure modes and recovery](architecture/13-operations-cost-and-limits.md#136-failure-modes-and-recovery)
  - [13.7 Findings](architecture/13-operations-cost-and-limits.md#137-findings)
- [Appendix A. Repository file index](architecture/appendix-a-file-index.md#appendix-a-repository-file-index)
  - [A.1 Repository root](architecture/appendix-a-file-index.md#a1-repository-root)
  - [A.2 Documentation and the diagram toolchain (docs)](architecture/appendix-a-file-index.md#a2-documentation-and-the-diagram-toolchain-docs)
  - [A.3 Identity (identity)](architecture/appendix-a-file-index.md#a3-identity-identity)
  - [A.4 Infrastructure as code (infra)](architecture/appendix-a-file-index.md#a4-infrastructure-as-code-infra)
  - [A.5 Observability (observability)](architecture/appendix-a-file-index.md#a5-observability-observability)
  - [A.6 Scripts (scripts)](architecture/appendix-a-file-index.md#a6-scripts-scripts)
  - [A.7 Application source (src)](architecture/appendix-a-file-index.md#a7-application-source-src)
  - [A.8 Demo Console (console)](architecture/appendix-a-file-index.md#a8-demo-console-console)
  - [A.9 Demo, proof harness and scrubbed evidence (demo)](architecture/appendix-a-file-index.md#a9-demo-proof-harness-and-scrubbed-evidence-demo)
  - [A.10 Slide deck (deck)](architecture/appendix-a-file-index.md#a10-slide-deck-deck)
  - [A.11 Local-only and non-shareable folders](architecture/appendix-a-file-index.md#a11-local-only-and-non-shareable-folders)
  - [A.12 Find it fast](architecture/appendix-a-file-index.md#a12-find-it-fast)
- [Appendix B. Findings register](architecture/appendix-b-findings-register.md#appendix-b-findings-register)
  - [B.1 Raised while writing sections 0 and 1](architecture/appendix-b-findings-register.md#b1-raised-while-writing-sections-0-and-1)
  - [B.2 Raised while writing sections 2 to 5, 13 and Appendix A](architecture/appendix-b-findings-register.md#b2-raised-while-writing-sections-2-to-5-13-and-appendix-a)
  - [B.3 Raised while writing section 4.9](architecture/appendix-b-findings-register.md#b3-raised-while-writing-section-49)
  - [B.4 Raised while writing section 6](architecture/appendix-b-findings-register.md#b4-raised-while-writing-section-6)
  - [B.5 Raised while writing sections 7 and 8](architecture/appendix-b-findings-register.md#b5-raised-while-writing-sections-7-and-8)
  - [B.6 Raised while writing section 9](architecture/appendix-b-findings-register.md#b6-raised-while-writing-section-9)
  - [B.7 Raised while writing sections 10 to 12](architecture/appendix-b-findings-register.md#b7-raised-while-writing-sections-10-to-12)

---

## 0. About this document

**What this section covers.** The purpose, audience and scope of this document, where each topic lives, how to read a citation and the provenance labels, the diagrams that accompany the text, how to re-check every citation yourself, and what the document deliberately does not claim.

### 0.1 Purpose, audience and scope

**What this section proves.** The document is a map of the repository, not a second source of truth: every behavioural statement points back to the code, template or contract that makes it true.

This is the technical architecture and design record of **Agents Behind the Wall** (workload code `abw`), an Azure reference platform in which an AI agent calls tools on behalf of a signed-in user and every hop between the user and the data is checked by something other than the model (**Designed**, `DESIGN.md:9-11#identity`). It explains how the platform is built, how a request travels through it, how each caller is authenticated and authorised, which token is exchanged at which hop, and what each of the seven demonstration acts shows. The platform is a lab reference, not a product, and it is not a compliance attestation (**Designed**, `README.md:8#attestation`). All data in it is fictional (**Designed**, `DESIGN.md:4-5#synthetic`).

**Who reads what.**

| Reader | Start with | Then | What they get |
|---|---|---|---|
| Sales, account team, executive sponsor | Section 1 and diagrams 01, 05 and 08 (0.4) | Section 9, one act at a time | The customer story and the evidence behind it, without the code |
| Solution engineer or architect presenting or reusing the story | Sections 1 and 2 | Sections 9 and 13 | The design in one pass, and what not to over-claim |
| Security architect or reviewer | Sections 6 and 7 | Sections 11 and 13 | Token claims, the four walls, detection and the disclosed exceptions |
| Platform or DevOps engineer deploying a copy | Sections 3 and 4, and `docs/SELF-DEPLOY.md` | Section 4.9 | Network design, the stage graph and the one-command orchestrator |
| SecOps, audit and risk | Sections 10 and 11 | Section 7 | How the request id, the trace id and a time window join the agent, gateway, tool-server and data-plane rows |

**Scope.** In scope is everything in the repository that builds, deploys, runs, proves or observes the platform: the Bicep templates in `infra/`, the Entra provisioning in `identity/`, the tool servers in `src/mcp/`, the agent definitions in `src/agent/`, the proof harness in `demo/`, the Demo Console in `console/`, the observability pack in `observability/` and the deployment scripts in `scripts/`. Out of scope are Microsoft product internals (except where they decide how the platform behaves; those statements are labelled **Platform behaviour**), controls a customer adds in their own tenant, and production sizing.

**Companion documents.** This document does not repeat them; it cites them.

| Document | Use it for |
|---|---|
| `README.md` | Entry point, quickstart, the table of eight pain points (the README heads it "six questions", see Findings) and the honest edges (`README.md:27#questions`, `README.md:138#Honest`) |
| `DESIGN.md` | The design contract: names, identities, the token chain, MCP servers, Foundry objects and the honest edges |
| `docs/SELF-DEPLOY.md` | Deploying your own copy: prerequisites, the orchestrator, verification and teardown |
| `docs/RUNBOOK.md` | Operating the deployment |
| `docs/DEMO-GUIDE.md` | Running the demo from the console and testing it yourself |
| `docs/PROOF-PLAYBOOK.md` | Beat by beat: tell it, show it, prove it |
| `docs/TALK-TRACK.md` and `docs/TALK-TRACK-PORTAL-TOUR.md` | The 30-minute talk and the portal tour |
| `docs/CUSTOMER-GUIDE.md` | Taking the story to a Capital Markets customer |
| `docs/COST.md` | What the platform costs and how to stop paying |

When this document writes **DESIGN.md section N** it means the numbered section of the design contract. A plain **section N** or **N.N** means this document, whichever file holds that section (0.2 lists the files).

### 0.2 Document map

**What this section proves.** Every topic has one home, so a question about tokens, networks or logs has an obvious place to start. A very large Markdown file may not render on GitHub (the display limit is about 512 KB; that is platform behaviour this repository does not control), so the document is split: this page (`docs/ARCHITECTURE-AND-DESIGN.md`) holds the chapter list, the contents and sections 0 and 1, and every other chapter is a file in `docs/architecture/`, named in the File column below. Section numbers are unique across all the files, and each file has a Previous / Next line at the top and bottom.

| # | Section | File | Read it to learn |
|---|---|---|---|
| 1 | Executive summary | `ARCHITECTURE-AND-DESIGN.md` (this page) | The problem, the solution, what was built, what is proven and what is not |
| 2 | System overview | `02-system-overview.md` | Components, planes, trust boundaries, the four walls at a glance, naming and configuration, deployment-shape limits |
| 3 | Infrastructure and network design | `03-infrastructure-and-network.md` | The resource group, VNet, subnets, private endpoints and DNS, the two Container Apps environments |
| 4 | Deployment architecture | `04-deployment.md` | The stage graph, Bicep modules, image build, Entra provisioning order, governance, the jump box, the one-command orchestrator (4.9), teardown and idempotency |
| 5 | Identity objects and entitlement model | `05-identity-objects.md` | The Entra groups, API and client apps, personas and operator, managed identities, Azure role assignments, the entitlement model as built and the identity lifecycle |
| 6 | Authentication: identities, tokens and trust | `06-authentication.md` | Who each caller is, the four-hop token chain, what is in every token and how each hop validates it |
| 7 | Authorization: the four walls and policy-as-code | `07-authorization.md` | The gateway policy, the tool-server checks, on-behalf-of RBAC, the authorization matrix and Azure Policy |
| 8 | MCP server internals | `08-mcp-server-internals.md` | The one image behind six servers, the tool registry, audit events and denial modes |
| 9 | Scenarios: Acts 1 to 7 end to end | Seven files: `09a-scenarios-acts-1-3.md` (9.1 to 9.4), `09b-scenarios-act-4.md` (9.5), `09c-scenarios-act-5.md` (9.6), `09d-scenarios-act-6.md` (9.7), `09e-scenarios-act-7a.md` (9.8 to 9.8.9), `09f-scenarios-act-7b.md` (9.8.10 to 9.8.15), `09g-proof-coverage.md` (9.9 to 9.10) | Every beat: what runs, what each layer decides and what is logged |
| 10 | Data flow and correlation | `10-data-flow-and-correlation.md` | The path of one governed call, the correlation keys, how `AbwFullChain` joins the layers, latency, exceptions and retention |
| 11 | Observability, detection and response | `11-observability-and-response.md` | The KQL pack, Sentinel rules, workbook, alerts, the front door and FinOps, operator controls |
| 12 | Demo Console architecture | `12-demo-console.md` | The process model, how personas sign in, the modules and how a scenario is registered and run |
| 13 | Operations, cost, limits and known gaps | `13-operations-cost-and-limits.md` | The cost model, capacity and quota, scale limits, the multi-deployment hazard, security posture and residual risk, failure modes and recovery, and a Findings subsection that points to the register in Appendix B |
| A | Appendix A: repository file index | `appendix-a-file-index.md` | Every folder and file group of the repository with its purpose and one or more cited symbols, the local-only folders that never leave the operator machine, and a "find it fast" table from a question to the file that answers it |
| B | Appendix B: findings register | `appendix-b-findings-register.md` | Every finding raised while writing this document, in one list; the section that raised each group ends with a Findings subsection that points to it |

### 0.3 Conventions

**What this section proves.** A reader can tell, for every sentence, where it comes from and how strongly the repository backs it.

#### 0.3.1 Citations

A citation is an inline-code reference of the form `path:START-END#symbol`. The path is relative to the repository root and uses forward slashes. START-END is a line or a range of lines. The symbol is a literal piece of text, usually one identifier and sometimes a short phrase, that must appear inside those lines exactly as written (the match is case-sensitive), so a citation that drifts after a code change fails the check (0.5) instead of silently pointing at the wrong line (**Implemented**, `scripts/check_citations.py:1-14#Citation`). Ranges are kept short (the checker's default limit is 80 lines) so a reader lands on the code that supports the claim. Example: `src/mcp/abw_mcp/auth.py:144-157#app_only` points at the lines where the tool server refuses an application-only token.

#### 0.3.2 Provenance labels

| Label | Means | Typical source |
|---|---|---|
| **Implemented** | Behaviour you can read in application or script code | `src/`, `console/`, `demo/`, `scripts/` |
| **Configured** | Behaviour set by a template or policy file | Bicep, policy XML, KQL, rules JSON |
| **Designed** | Intent stated in the contract, the README or `docs/`; not necessarily exercised | `DESIGN.md`, `README.md`, `docs/` |
| **Platform behaviour** | What Azure or Entra does, taken from Microsoft documentation; the URL is written as plain text | Microsoft Learn |
| **Tested** | A test or a live proof in the repository asserts the behaviour; this document did not run it | `src/mcp/tests/`, `demo/prove.py` |
| **Inference** | The author's reading of the files, neither run nor observed; section 13 writes it as Inferred | The cited code or text, with the reasoning stated |
| not in this repo | A control a customer would add in their own environment | none |

For example, the gateway's token validation is **Configured** (`infra/apim/policies/mcp-jwt.policy.xml:17-30#validate-jwt`), the tool server's second validation is **Implemented** (`src/mcp/abw_mcp/auth.py:108-142#verify_token`) and the statement that keys bypass Conditional Access is **Designed** (`DESIGN.md:9-11#identity`).

#### 0.3.3 Placeholders and names

Real identifiers of the build tenant never appear in this document. Placeholders stand in for them: `<tenant-id>`, `<subscription-id>`, `<region>` (the short region code used in names), `<u4>` (a four-character suffix: the stage scripts make the letter `k` plus three random characters from a-z and 0-9, `scripts/common.ps1:36-37#u4`; the orchestrator makes four random characters or takes `-UniqueSuffix`, `scripts/Deploy-AgentWall.ps1:228-231#New-UniqueSuffix`, `scripts/Deploy-AgentWall.ps1:802#UniqueSuffix`), `<user-oid>`, `<client-id>`, `<operator-upn>` and `<tenant-domain>`. Resource names follow patterns such as `apim-abw-demo-<region>-<u4>`, `aif-abw-demo-<region>-<u4>`, `proj-abw-wall-<u4>` and `stabwdemo<region><u4>`; persona sign-in names are `abw.<persona>@<tenant-domain>`. The full pattern table is in 2.6.2.

#### 0.3.4 Terms

| Term | Meaning in this document | Basis |
|---|---|---|
| Agent | A Foundry prompt agent that calls tools through MCP; four are published | `src/agent/abw_agents.py:3-14#abw-poc-legacy` |
| MCP server | A tool server speaking the Model Context Protocol; six exist, built from one image | `DESIGN.md:120-125#legacy` |
| Wall | A layer that can refuse a call on its own: 1 gateway, 2 tool server and 3 data plane deterministically, 0 guardrail only on a best-effort basis | `DESIGN.md:28-33#abw-agent-guardrails` |
| Persona | One of five demo people: Priya, Wes, Tara, Carla and Ian | `identity/Setup-Entra.ps1:50-61#Users` |
| Operator | The administrator who deploys the platform and runs the console; the sixth identity | `console/catalog.py:743#administrator` |
| App role | An Entra application role carried in the token's `roles` claim and used as the entitlement | `identity/Setup-Entra.ps1:29-45#Wall.Falcon` |
| Scope | A delegated permission in the token's `scp` claim, for example `Tools.Read` | `src/mcp/abw_mcp/auth.py:155-157#scopes` |
| OBO | The on-behalf-of flow: a server swaps the caller's token for a data-plane token as that caller | `src/mcp/abw_mcp/obo.py:39-79#OboBroker` |
| Request id | The id the gateway stamps on each request it forwards (`x-abw-request-id`); the gateway log and the tool server's audit row repeat it, and a tool server called directly makes its own | `infra/apim/policies/mcp-jwt.policy.xml:62#request_id`, `infra/apim/policies/mcp-jwt.policy.xml:82#x-abw-request-id`, `src/mcp/abw_mcp/auth.py:180-184#x-abw-request-id` |
| Act and beat | One of seven demonstration chapters, and one numbered step in it (beat 6.4 is the fourth beat of Act 6) | `console/catalog.py:238-243#SCENES` |
| Proof | One automated check group in the harness, numbered P00 to P17 | `demo/prove.py:545#P01` |

"Six identities" is a presentation count: five Entra users plus the administrator. Entra holds five persona users, not six.

### 0.4 Diagram index

**What this section proves.** Thirteen diagrams cover the architecture, the data flow, authentication, authorization, the scenarios and the design decisions; each is referenced from the section that explains it.

| # | File | Shows | Main sections |
|---|---|---|---|
| 01 | `docs/diagrams/01-system-architecture.excalidraw` | Components, planes and the four walls | 2 |
| 02 | `docs/diagrams/02-network-topology.excalidraw` | VNet, subnets, private endpoints, DNS and the two Container Apps environments | 3 |
| 03 | `docs/diagrams/03-request-data-flow.excalidraw` | The path of one governed tool call, hop by hop | 10, 6 |
| 04 | `docs/diagrams/04-authentication-flow.excalidraw` | Sign-in and the four-hop token chain | 6 |
| 05 | `docs/diagrams/05-authorization-layers.excalidraw` | What each wall checks and which claim it uses | 7 |
| 06 | `docs/diagrams/06-identity-and-entitlements.excalidraw` | The identities, groups and app roles | 5, 7 |
| 07 | `docs/diagrams/07-token-anatomy.excalidraw` | The claims of each token in the chain | 6 |
| 08 | `docs/diagrams/08-scenarios-acts-1-7.excalidraw` | The seven acts and the layer that answers each | 9 |
| 09 | `docs/diagrams/09-observability-correlation.excalidraw` | Log sources and the keys that join them | 10, 11 |
| 10 | `docs/diagrams/10-deployment-pipeline.excalidraw` | The 26-step plan (`scripts/Deploy-AgentWall.ps1:359-370#Get-StepTable`), the verify phase and the read-only check mode | 4 |
| 11 | `docs/diagrams/11-agent-front-door.excalidraw` | The Act 7 path: user, APIM, agent, APIM, MCP server, data | 6, 9 |
| 12 | `docs/diagrams/12-demo-console.excalidraw` | Console components and their data sources | 12 |
| 13 | `docs/diagrams/13-trust-boundaries-and-failure-modes.excalidraw` | Where trust changes and what each failure does | 13 |

Each diagram is an Excalidraw file (JSON). Open it at excalidraw.com or with the Excalidraw extension for VS Code to view or edit it; an `.svg` rendering sits beside each file and a `.png` copy in `docs/diagrams/png/`.

### 0.5 Verifying this document

**What this section proves.** The citations are machine-checked, so a reader does not have to trust the author.

Run these checks from the repository root. They cover this page and every chapter file in one run:

```powershell
python scripts\check_citations.py (Get-ChildItem docs\ARCHITECTURE-AND-DESIGN.md, docs\architecture\*.md).FullName --strict-diagrams
python scripts\share_check.py scan docs
```

The first command prints one summary line per file and proves that every cited file exists inside the repository, that every line range lies inside the file, that every `#symbol` appears literally inside the cited lines, that the text is ASCII only and mentions no private path, and (with `--strict-diagrams`) that every referenced diagram exists (**Implemented**, `scripts/check_citations.py:1-14#Citation`); add `--stats` to see which repository files each chapter cites most. The second command scans the whole `docs` folder for the identifiers and secrets of the deployment you run it in, and never prints them (**Implemented**, `scripts/share_check.py:1-17#Share-readiness`). Both exit with code 0 when nothing is wrong.

**Trade-off / limitation.** A citation can go stale without the claim being wrong: when code is edited, line numbers move and the checker reports the citation, not the claim. Re-run it after any change to cited code, then read the cited lines before correcting the text. The checker proves that a symbol is on the cited lines; it cannot prove that the sentence next to it is true.

### 0.6 What this document is not

- **Not product documentation.** Azure AI Foundry, API Management, Entra, Sentinel and Defender are described only as far as they decide how this platform behaves; those statements are labelled **Platform behaviour**.
- **Not a compliance attestation.** The repository says so itself (`README.md:8#attestation`), and the write-once audit container is unlocked in this build (`README.md:143#WORM`).
- **Not a production blueprint.** It is a lab build that costs about $37 a day while it exists and is meant to be torn down after the presentation (`docs/COST.md:3#Bottom`).
- **Not a sizing guide.** The throttle and token-budget numbers are demonstration defaults (`DESIGN.md:246#defaults`).
- **Not real data.** Every firm, ticker, deal and document is synthetic (`DESIGN.md:4-5#synthetic`).

**Key takeaways.**

- Every behavioural claim carries a `path:lines#symbol` citation, and a checker proves each one.
- Provenance labels (Implemented, Configured, Designed, Platform behaviour and, where a section needs them, Tested and Inference) say how strongly the repository backs a statement.
- Section 1 stands alone; sections 2 to 13 go deep; Appendix B collects every finding.
- Real tenant identifiers never appear; placeholders do.

## 1. Executive summary

**What this section covers.** The business problem, the solution on one page, what was built, the seven acts, what is proven and what is not, and where to read next. It is written to be read alone by a sales or architecture audience; every number points to the part of the repository that holds it.

**In one paragraph.** Regulated firms stall AI agent pilots on identity questions, not on model quality. This platform shows, on Azure and without keys, that an agent can act as the signed-in person at every hop: Entra authenticates the person, Foundry passes that identity to each tool, an API gateway and the tool server each verify it independently, the tool server exchanges it for a data-plane token as that person, and Azure RBAC decides. Every call the gateway forwards carries a request id, and one saved query joins the agent, gateway, tool-server and data-plane rows for it by that id, the run's trace id and a time window; Azure Policy governs the demo resource group, and Sentinel watches the gateway, tool-server, data-plane and agent logs. The claims are backed by 18 automated proofs against a live deployment, and the platform's known limits are listed rather than hidden (**Designed**, `DESIGN.md:9-11#identity`, `README.md:6#proofs`, `README.md:138#Honest`; **Implemented**, `observability/kql/AbwFullChainCore.kql:3#W3C`).

### 1.1 The business problem

**What this section proves.** The pilot that every team builds first has a structural problem that no prompt can fix, and the problem decomposes into eight questions a bank can ask and a platform can answer with evidence.

The pilot gives the agent one shared key. A key proves nothing about who is asking, so Conditional Access never sees the call, data-level RBAC has no user to evaluate, and the audit trail names a service instead of a person. The design contract states it as the thesis: keys bypass Conditional Access, a missing user context bypasses data-level RBAC, Purview and every audit trail you own, and fixing the identity chain (user, agent, gateway, tool, data) lights up every other control (**Designed**, `DESIGN.md:9-11#identity`). The platform deploys that anti-pattern on purpose, as a legacy agent beside the governed one, so the contrast can be shown rather than argued (**Configured**, `infra/03-platform.bicep:569-601#raLegacyBlob`; **Implemented**, `src/agent/abw_agents.py:142-152#poc_tools`).

The thesis breaks down into eight questions that regulated-industry pilots stall on. The table states each in the bank's words, what closes it here, the proofs that demonstrate it and where the repository states it (the README groups them under the heading "six questions", see Findings).

| # | What the bank asks | What closes it here | Proofs | Basis |
|---|---|---|---|---|
| 1 | Can anyone leak a key? | Foundry, Storage, Cosmos DB, AI Search, the registry and Key Vault accept Entra only; Azure Policy either denies key authentication or, where the organisation's own baseline runs first, rewrites it off (in the proof, 5 of 9 attempts were denied, 3 were corrected and 1 compliant request was allowed). The one external vendor key lives in Key Vault and the gateway and is never seen by an agent or a user | P01, P07, P11 | `DESIGN.md:17#Entra`, `demo/prove.py:1002-1006#Modify`, `demo/evidence-scrubbed/SCOREBOARD.md:37-38#Modify` |
| 2 | Does the data plane see the user or the server? | Each tool server swaps the user's token for a data-plane token as that user (on-behalf-of); Azure RBAC decides, not application code | P03, P04, P10 | `DESIGN.md:18#OBO` |
| 3 | Is every tool path authenticated: internal, external and private? | Internal tools sit behind the gateway and verify the token again themselves; the external vendor tool is reached through the gateway that holds its key; the private tool is reachable only from inside the VNet, which includes the agent runtime and the optional jump box (3.9) | P02, P06, P07 | `DESIGN.md:19#APIM` |
| 4 | How are people using agents? | Saved queries and a workbook show users, agents, tools, denials and latency | P17 | `DESIGN.md:20#AbwUsageByUser` |
| 5 | Can InfoSec see governance? | Policy compliance, nine Sentinel analytics rules, one correlated trace per request (joined by id and time window) and a WORM-mode audit blob (unlocked in this build, see 1.6) | P10, P11, P13, P17 | `DESIGN.md:21#WORM` |
| 6 | Does the MNPI information barrier hold? | Wall roles gate deal data at the gateway, at the tool list and call, and, independently, at Azure Storage | P03, P08 | `DESIGN.md:22#MNPI` |
| 7 | Is a human in the loop for irreversible actions? | The order tool requires approval: a refusal blocks the order, an approval places it as the user | P05 | `DESIGN.md:23#require_approval` |
| 8 | What contains an incident? | Kill switch, client allow-list, per-user rate limit, entitlement drift and a prompt-injection guardrail | P09, P12, P14, P15, P16 | `DESIGN.md:24#Kill` |

Each question is closed by trying to break the control, not by describing it (**Designed**, `README.md:4#break`).

**Key takeaways (1.1).** The structural problem is the missing user context, not the model. Eight bank questions follow from it, and each has a named proof.

### 1.2 The solution on one page

**What this section proves.** One idea, carried through every layer: the person's own token travels from sign-in to the data, and something other than the model checks it at each stop.

**Five design principles.** The platform is held to five tests: keyless (no account keys or SAS tokens on its own services), on-behalf-of (the data plane sees the user, not the server), governance at the tool level (the unit of control is the tool call, not the prompt), defence in depth (three deterministic layers that each deny on their own, behind a best-effort preview guardrail) and synthetic data only. Section 2.1 states each with its evidence.

**The token chain.** Four hops carry the person's identity from sign-in to the data (**Designed**, `DESIGN.md:102-105#OBO`):

1. The user signs in and receives a Foundry token (`DESIGN.md:102#Foundry`).
2. Foundry's OAuth identity passthrough, after a one-time consent per connection, obtains a token for the target MCP API (`DESIGN.md:103#passthrough`).
3. The APIM gateway validates the token and authorises the call: signature, issuer, audience, expiry and tenant, then the kill switch, the client allow-list, the scope and the app role in that order, and last the rate limit (`DESIGN.md:104#validate-jwt`, `infra/apim/policies/mcp-jwt.policy.xml:37-44#missing_role`).
4. The MCP server validates the token again and exchanges it, using a client assertion signed for its own managed identity, for a Storage, Cosmos DB or Search token as the user (`DESIGN.md:105#OBO`).

Three other paths differ. The private server is called directly from the agent subnet and never touches APIM (`DESIGN.md:107#private`). The external vendor tool is reached through APIM, which validates the user token and injects the vendor key (`DESIGN.md:108#vendor`). The legacy contrast path uses one shared APIM subscription key and a broad shared identity (`DESIGN.md:109#shared`).

**The four walls.** Layers 1 to 3 each deny deterministically and on their own, so a failure or bypass of one does not open the data; layer 0 is a best-effort preview layer in front of them (**Designed**, `DESIGN.md:28-33#abw-agent-guardrails`):

| Layer | Where | What it decides | Basis |
|---|---|---|---|
| 0 | Foundry guardrail on the agent | Prompt shields and a tool-response indirect-attack control; preview and probabilistic, so a detective layer and not the control | `DESIGN.md:30#abw-agent-guardrails` |
| 1 | API Management gateway | Validates the token, then checks the kill switch, the client allow-list, the scope and the app role in that order, and applies a per-user rate limit | `infra/apim/policies/mcp-jwt.policy.xml:17-46#validate-jwt`, `infra/apim/policies/mcp-jwt.policy.xml:81-87#rate-limit-by-key` |
| 2 | MCP server | Validates the token again, refuses application-only tokens and filters the tool list by role | `src/mcp/abw_mcp/auth.py:108-142#verify_token`, `src/mcp/abw_mcp/auth.py:144-157#app_only`, `src/mcp/abw_mcp/registry.py:132-156#list_tools` |
| 3 | Data plane | Receives the user's own on-behalf-of token, and Azure RBAC is evaluated for that user on every request | `src/mcp/abw_mcp/obo.py:39-79#OboBroker`, `DESIGN.md:33#RBAC` |

Azure Policy (one initiative of 19 policy references in five families) and the observability pack span all four layers (**Configured**, `infra/06a-policy-definitions.bicep:168-172#abw-agent-platform-controls`, `infra/06a-policy-definitions.bicep:214-219#ABW-05-HYGIENE`).

**One request in six steps.** A governed tool call by a signed-in person:

1. The agent decides to call a tool. Foundry attaches the person's token for that tool's API.
2. The gateway validates the token. A call that passes gets a request id stamped on it (`x-abw-request-id`); a refusal is either a 403 whose body carries a reason and the same id, or a 401 whose body carries a reason and no id (`infra/apim/policies/mcp-jwt.policy.xml:76#request_id`, `infra/apim/policies/mcp-jwt.policy.xml:82#x-abw-request-id`, `infra/apim/policies/mcp-jwt.policy.xml:108#unauthorized`).
3. The MCP server validates the token again and lists only the tools the person's roles allow (`src/mcp/abw_mcp/registry.py:132-156#list_tools`).
4. The server exchanges the token for a data-plane token as that person (`src/mcp/abw_mcp/obo.py:39-79#OboBroker`).
5. Azure RBAC on Storage, Cosmos DB or Search answers for that person; a refusal is a normal result, not an outage (`DESIGN.md:33#RBAC`).
6. Each layer logs its decision. The gateway and the tool server log the request id, the agent and model rows carry the run's trace id, and the Search and Cosmos rows are matched by time; Section 10 shows how one query joins them (**Implemented**, `observability/kql/AbwFullChainCore.kql:3#W3C`).

`Diagram: docs/diagrams/01-system-architecture.excalidraw`

`Diagram: docs/diagrams/04-authentication-flow.excalidraw`

`Diagram: docs/diagrams/05-authorization-layers.excalidraw`

**Why.** A model can be talked into anything, so the control has to sit where a decision can be enforced without trusting the model: at the token, the gateway, the tool and the data. The demonstration shows this by removing the model from the picture: the red-team agent is deliberately over-compliant and the wall still says no (**Implemented**, `src/agent/abw_agents.py:3-14#abw-wall-desk-redteam-shielded`).

**Trade-off / limitation.** The chain needs the person's token alive across every hop. Foundry holds a user's token for its whole life, so a role change reaches the agent only when that token expires, and the private server sits outside the gateway (1.6).

**Key takeaways (1.2).** One token, four hops, four walls. The model proposes; identity, policy and RBAC decide. Every call the gateway forwards carries a request id.

### 1.3 What was built

**What this section proves.** The platform is a complete, deployable estate and not a diagram: a counted inventory with a pointer to where each part is defined.

| Area | What exists | Basis |
|---|---|---|
| Azure footprint | About 97 resources in one resource group (103 with the optional jump box; the reference deployment counts 104 because Defender for Cloud added an extension to the jump box VM) | `README.md:42#resources`, `docs/SELF-DEPLOY.md:33#MDE.Windows`, `docs/COST.md:7#MDE.Windows` |
| Gateway | API Management Standard v2: a public gateway plus a private endpoint, with outbound VNet integration | `infra/05-apim.bicep:43-63#StandardV2` |
| Tool servers | Six MCP servers built from one container image whose behaviour is selected by an environment variable: research, wall, actions, private, vendor mock and legacy. Five run in an internal Container Apps environment and the vendor mock in a public one | `DESIGN.md:120-125#legacy`, `infra/modules/mcp-app.bicep:1-2#MCP_SERVER`, `infra/03-platform.bicep:377-397#caePriv`, `infra/03-platform.bicep:399-416#caePub` |
| Agents | Four Foundry prompt agents (a shared-key PoC agent, the governed wall-desk agent, a red-team variant and the same variant behind the guardrail), one guardrail policy, six MCP tool connections; twelve tools reach the governed agent across five servers, and the order tool needs human approval | `src/agent/abw_agents.py:35-49#APPROVAL_REQUIRED`, `DESIGN.md:152#mcp-legacy-key` |
| Identity | Seven Entra app registrations (five MCP API apps with scopes and app roles, the agent client and the test client), six security groups, five personas with different role sets, and federated credentials on the four servers that do on-behalf-of (the vendor mock has none) so that each of those servers' managed identities can exchange a token without a secret | `identity/Setup-Entra.ps1:29-61#Users`, `identity/Setup-Entra.ps1:150#abw-agent-client`, `identity/Setup-Entra.ps1:171#abw-test-client`, `identity/Setup-Entra.ps1:266#research`, `identity/Setup-Entra.ps1:274#AzureADTokenExchange` |
| Data | Storage, Cosmos DB and AI Search, private-endpoint only with key authentication off, holding fictional data | `DESIGN.md:50-52#serverless` |
| Platform governance | One Azure Policy initiative with 19 policy references in five families (no keys, private, tools and models, guardrails, hygiene); definitions at subscription scope, assignment on the resource group | `infra/06a-policy-definitions.bicep:214-219#ABW-01-NO-KEYS`, `infra/06-governance.bicep:177-183#assignment` |
| Observability | Ten saved KQL functions, nine Sentinel analytics rules, a cockpit workbook and three alert rules | `observability/kql/pack.json:3#AbwGateway`, `observability/kql/pack.json:66#AbwFullChain`, `observability/sentinel/rules.json:4#ABW-001`, `observability/sentinel/rules.json:259#ABW-009`, `infra/06b-observability.bicep:126-151#opsAlerts`, `infra/06b-observability.bicep:193-205#cockpit` |
| Front door and cost | An APIM API at `/agents` that the console's agent runs enter through by default (the legacy agent stays outside it on purpose, and Foundry's own endpoint still answers a valid token while its public access is on), with a per-user rate limit and a per-user token budget; a resource-group budget that alerts and does not cap | `DESIGN.md:174#abw-agent-rpm`, `DESIGN.md:174#public network access`, `console/jobs.py:106#front door`, `console/role_story.py:381#abw-poc-legacy`, `infra/08-agent-frontdoor.bicep:15-64#tokenQuotaPerHour`, `docs/COST.md:73#budget` |
| Demo Console | A local web application that runs the seven acts against the live deployment and reads the evidence back from the logs | `console/server.py:418-434#main` |
| Deployment | A stage-based deployment plus a 26-step orchestrator with a read-only check mode, an offline self-test, and a self-deployment guide | `scripts/Deploy-AgentWall.ps1:359-370#Get-StepTable`, `scripts/Test-DeployOrchestrator.ps1:4-20#Offline` |
| Cost | About $37 a day while it runs, about 63 percent of it API Management Standard v2 | `docs/COST.md:3#Bottom`, `docs/COST.md:54#APIM` |

**Key takeaways (1.3).** One resource group, six tool servers from one image, four agents, one Azure Policy initiative, one observability pack, one console and one orchestrator.

### 1.4 The seven acts

**What this section proves.** The story is told as seven acts, each answering a different bank question by running a real call and reading the result back from the logs. Section 9 walks every beat.

| Act | Title | What the audience sees | Proofs behind it | Basis |
|---|---|---|---|---|
| 1 | Same question, two answers | A user who is not cleared for a deal asks the shared-key agent and gets it; the governed agent is told who the user is by the token, and the wall refuses | P03, P08 | `console/catalog.py:249#Act` |
| 2 | No keys | Every data service is Entra-only, and Azure Policy either refuses or switches off anyone's attempt to bring a key back | P01, P11 | `console/catalog.py:319#Act` |
| 3 | Whose hands are on the data | Internal, private and external tools pass through the same wall; the private server is not reachable from the internet; the vendor key never leaves the gateway | P06, P07 | `console/catalog.py:372#Act` |
| 4 | When it goes wrong | A runaway loop is throttled, a human approves an order, a poisoned tool result is refused, a stolen token is turned away and a user is cut off | P14, P04, P05, P09, P15, P12 | `console/catalog.py:416#Act` |
| 5 | What InfoSec sees | One query follows a request from the agent through the gateway and the tool server to the data plane, with the user named in each row that records one (the console's story says "one request id", see Findings) | P10, P13, P17 | `console/catalog.py:499#Act` |
| 6 | One request, every layer | One request through twelve layers (seven on the path, five watching) in eight beats that run eleven scenarios: nine refusals and two successes | none dedicated | `console/catalog.py:598#Act`, `console/e2e.py:1209-1220#SCENARIOS` |
| 7 | Every role, the agent's front door, and the bill | Five people and the administrator, each with one allowed and one refused request; the agent front door; the FinOps board; a token budget that stops a runaway agent | none of the 18 | `console/catalog.py:742#Act` |

Act 6 follows a request through twelve layers: Entra sign-in, Conditional Access, the guardrail, the agent, the gateway, the tool server and the data on the path, with five watchtowers recording it (Azure Monitor, Sentinel, Defender, Azure Policy and Agent 365) (**Implemented**, `console/e2e.py:44#PATH`, `console/e2e.py:45#WATCH`).

Three proofs are not tied to one act in the table: P00 (the baseline preflight), P02 (least privilege) and P16 (entitlement drift). Section 1.5 groups all 18.

`Diagram: docs/diagrams/08-scenarios-acts-1-7.excalidraw`

**Key takeaways (1.4).** Acts 1 to 5 each demonstrate a group of controls; Act 6 follows one request through every layer; Act 7 repeats the wall for each role and adds the front door and the bill.

### 1.5 What is proven

**What this section proves.** The claims in 1.1 are backed by an automated harness that runs against the live deployment, and the boundary between proven, observed and merely designed is stated.

The harness has 18 proofs (P00 to P17). The shipped board shows all 18 passing with 109 checks, and its per-proof times add up to about 23 minutes. The README and other documents quote 110 checks and between 25 and 30 minutes from a later run (the README dates it nearly four hours after the shipped board's run) whose raw board is not shipped, and they say 109 appears when the preview guardrail does not fire in P09. Counts vary by run and cannot be reconciled from the shipped files (9.9.2, Findings F9-13 and F9-14), so quote the proof count (**Implemented**, `demo/prove.py:508#P00`, `demo/evidence-scrubbed/SCOREBOARD.md:3-3#109/109`; **Designed**, `README.md:6-6#110/110`).

| What is proven | Proofs | Basis |
|---|---|---|
| The identity chain: no keys, least privilege, the information barrier, trading controls | P01, P02, P03, P04 | `demo/prove.py:545#P01`, `demo/prove.py:607#P02`, `demo/prove.py:638#P03`, `demo/prove.py:659#P04` |
| Three tool paths: private, external and the legacy contrast | P06, P07, P08 | `demo/prove.py:711#P06`, `demo/prove.py:736#P07`, `demo/prove.py:763#P08` |
| A human in the loop, and prompt injection | P05, P09 | `demo/prove.py:688#P05`, `demo/prove.py:815#P09` |
| Containment: throttle, stolen token, kill switch, entitlement drift | P14, P15, P12, P16 | `demo/prove.py:870#P14`, `demo/prove.py:905#P15`, `demo/prove.py:932#P12`, `demo/prove.py:962#P16` |
| Audit and detection: one request id joins the gateway, tool-server and storage rows, a healthy observability pack, Sentinel incidents | P10, P17, P13 | `demo/prove.py:1024#P10`, `demo/prove.py:1054#P17`, `demo/prove.py:1065#P13` |
| Platform controls: policy as code, and a baseline preflight | P11, P00 | `demo/prove.py:993#P11`, `demo/prove.py:508#P00` |

**Three levels of evidence.**

- **Proven.** The 18 proofs, run against the live deployment (109 checks in the shipped run). Even the "zero keys" claim carries a disclosed footnote: four SAS-signed storage requests in the seven-day log coincide with Defender for Storage onboarding (`README.md:145#SAS`).
- **Observed, outside the 18.** Acts 6 and 7 were run live through the console and sit outside the 18 proofs; only Act 7 is documented as added after the final proof run. Observed live: nine of Act 6's eleven scenarios, the Priya and Ian tabs of Act 7, and ten of the Admin tab's eleven scenarios (`README.md:148#observed`, `README.md:149#observed`, `DESIGN.md:246#proofs`).
- **Designed, not exercised.** For example, that the kill switch does not reach the private server is read from the code, not exercised live (`DESIGN.md:107#exercised`), and the Wes, Tara and Carla tabs of Act 7 show the designed result until each person has signed in once (`README.md:149#designed`).

**Not in this repo.** Identity Protection, sign-in-log export and Temporary Access Pass are not configured: they are the layer a customer adds (`README.md:144#TAP`).

**Key takeaways (1.5).** Eighteen proofs back the platform controls (109 checks in the shipped run); the 1.4 table maps fifteen of them to Acts 1 to 5. Acts 6 and 7 are observed, mostly, and sit outside the proofs; the rest is designed and labelled as such.

### 1.6 Honest limits

**What this section proves.** A reference platform is only as useful as the limits it states. These are the ones a customer, a reviewer or an auditor will find first; each is detailed in the section named in the third column and again in section 13.

| Limit | What it means in practice | Detailed in | Basis |
|---|---|---|---|
| The guardrail is not the control | Layer 0 is a preview, probabilistic layer. In tests it stopped a poisoned tool result on only some identical requests (1 in 11 to 5 in 8), so the proofs assert the wall's refusal and report the guardrail's interventions as a rate | 7, 13 | `README.md:140#guardrail` |
| The private tool server sits outside the gateway | The agent subnet calls it directly, so the kill switch and the rate limit do not reach it; a revoked user keeps it until the token expires | 7, 10, 13 | `DESIGN.md:107#private`, `README.md:149#kill` |
| A role change reaches the agent late | Access tokens live 60 to 90 minutes, the README says that custom APIs get no continuous access evaluation (not verified here), and Foundry holds a user's token for its whole life | 6, 7 | `README.md:141#CAE` |
| "Keyless" has disclosed exceptions | A client secret for the OAuth client sits in a Foundry connection, Application Insights ingestion still uses a connection string, the vendor key lives in Key Vault and the gateway by design, and four SAS-signed storage requests coincide with Defender for Storage onboarding | 13 | `README.md:142#secret`, `README.md:145#SAS`, `DESIGN.md:17#Entra` |
| The audit container is not a records attestation | The write-once container is unlocked on synthetic data: a pattern, not an SEC 17a-4 attestation | 11, 13 | `README.md:143#WORM` |
| Entitlements are hard-coded per deal | Each deal is an app role named in four places (the gateway role list, the server code, the Entra provisioning and the platform template); that works for a demonstration and does not scale to thousands of deals or users without an entitlement store | 5, 7, 13 | `infra/05-apim-apis.bicep:45#roles`, `src/mcp/abw_mcp/servers/wall.py:32-35#Wall.Falcon`, `identity/Setup-Entra.ps1:35#Wall.Falcon`, `infra/03-platform.bicep:172-181#wall-falcon` |
| Entra refusals are not in the gateway-layer denials | The denials function covers layers 0 to 3; a failed sign-in is read from Entra's own log through Microsoft Graph, and this demo's Sentinel receives no Entra sign-in data | 10, 11 | `README.md:148#Graph` |
| Backend TLS chain validation is off by default | The gateway does not validate the certificate chain of the internal Container Apps backends unless a parameter is set | 3, 7 | `infra/05-apim-apis.bicep:21-22#validateInternalTls` |
| Some admin-portal controls are only partly evidenced | Conditional Access is report-only; Agent 365 is proven; Defender XDR and Purview were on in audit mode and had shown nothing when last recorded | 11, 13 | `README.md:144#Defender`, `README.md:44#report-only` |
| One copy per Entra tenant and per subscription | Application and group display names and the policy initiative name are fixed, so a second copy in the same tenant or subscription collides | 2, 4 | `identity/Setup-Entra.ps1:112-118#displayName`, `infra/06a-policy-definitions.bicep:168-170#abw-agent-platform-controls` |
| A deliberately insecure contrast path exists | The legacy agent, the `/legacy` API and a broad managed identity are deployed on purpose and must not be copied | 2, 9 | `infra/03-platform.bicep:569-601#raLegacyBlob` |
| The orchestrator is validated offline and read-only | Its logic is covered by 178 offline checks and its read-only check mode, not yet by a live deployment into a second tenant | 4 | `scripts/Test-DeployOrchestrator.ps1:4-20#Offline`, `docs/SELF-DEPLOY.md:428#178 checks` |

**Why.** Each limit is a design decision or a consequence of a preview feature, not an oversight: the guardrail is a preview API, the private path trades a kill switch for network isolation, and the app-role entitlement model trades scale for the simplicity of showing a token's `roles` claim on a slide.

**Key takeaways (1.6).** The wall is deterministic; the guardrail is not. The weakest points are the private server outside the gateway, the token-lifetime lag, the hard-coded entitlements and the disclosed "keyless" exceptions.

### 1.7 Reading paths and next steps

**What this section proves.** Whatever the reader needs next, the way to it is short.

- **Ten minutes.** This section and diagrams 01, 05 and 08.
- **One hour.** Add sections 2, 6, 7 and 9.
- **Review the security design.** Sections 6, 7, 11 and 13, then Appendix B.
- **Deploy a copy.** `docs/SELF-DEPLOY.md`, then section 4.9. Run the orchestrator's read-only check mode first; it changes nothing (**Implemented**, `scripts/Deploy-AgentWall.ps1:3-9#SYNOPSIS`). Expect about $37 a day while it runs, and tear it down the day after you present (`scripts/Deploy-AgentWall.ps1:1123-1130#Show-Impact`).
- **Check the citations.** Section 0.5.

**Key takeaways (1.7).** Section 1 stands alone; deploy with the self-deployment guide; verify the citations with the checker.

**Key takeaways (section 1).**

- Agent pilots stall on identity questions, not on model quality; the platform answers eight of them with evidence.
- The control is the identity chain: the person's token at every hop, on-behalf-of to the data and three deterministic walls that each deny on their own, behind a best-effort guardrail.
- It is a counted, deployable estate: one resource group, six tool servers from one image, four agents, one policy initiative, one observability pack, one console and one orchestrator.
- Eighteen proofs back the platform controls (109 checks in the shipped run); Acts 6 and 7 are observed, mostly, and sit outside them.
- The limits are listed: the preview guardrail, the private server outside the gateway, the token-lifetime lag, the per-deal entitlement model and the disclosed "keyless" exceptions.


### 1.8 Findings

The 4 findings raised while writing sections 0 and 1 (documentation mismatches, defects and undocumented decisions) are collected in [Appendix B.1](architecture/appendix-b-findings-register.md#b1-raised-while-writing-sections-0-and-1). Where the text above says "Findings" or quotes a finding number, it means that list.

---

Next: [2. System overview](architecture/02-system-overview.md)
