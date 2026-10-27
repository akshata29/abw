# Agents Behind the Wall: Excalidraw diagrams

Thirteen editable diagrams of the architecture and design: the system, the network, the data flow, authentication,
authorization, identity, tokens, the seven scenarios, observability, deployment, the agent front door, the Demo Console,
and the trust boundaries. Each one is drawn from what the repository implements. The text carries placeholders such as
`<tenant-id>`, `<u4>` and `abw.<persona>@<tenant-domain>`, never real ids.

Every diagram is three files with the same name:

- `NN-name.excalidraw`: the editable drawing (JSON). This is the file to open and edit.
- `NN-name.svg`: a preview rendered by the generator's own small renderer, for quick viewing in a browser or the repo.
- `png\NN-name.png`: a picture of the SVG made by local, headless Microsoft Edge, ready for a slide.

## Index

The document is `docs/ARCHITECTURE-AND-DESIGN.md` (the index page) with its chapter files in `docs/architecture/`. Its own diagram index is section 0.4; the section numbers below are
the numbered headings of that document.

| File | What it shows | Sections it supports |
|---|---|---|
| `01-system-architecture` | Everything on one canvas: the five personas and the operator, Entra (apps, groups, federated credentials), Foundry (account, project, agents, model, guardrail), APIM (one API per MCP server, the /agents front door, /legacy), the six MCP servers on Container Apps (which sit behind APIM and which do not), the data stores, observability, governance, and the optional admin-portal features. Numbered main flow. | 1.2, 1.3, 2.2, 2.3, 2.5 |
| `02-network-topology` | The VNet and every subnet (CIDR, purpose, NSG, NAT, delegation), private endpoints and private DNS zones, APIM inbound and outbound networking, the two Container Apps environments, the Foundry agent subnet, the jump box with Bastion, and the egress paths. | 3.1 to 3.6, 3.9 |
| `03-request-data-flow` | One governed tools/call as swim lanes (user, Foundry agent, APIM, MCP server, Entra on-behalf-of, data plane): what data and which header or token travels on each hop, what each hop logs, and the denial exit at each wall. | 6.11, 8.2, 9.1, 10.1 |
| `04-authentication-flow` | A sequence diagram with numbered messages that name each token (issuer, audience, key claims): first-time consent, then the steady state. | 1.2, 6.3 to 6.8, 6.11 |
| `05-authorization-layers` | The four walls as stacked layers: what each checks, its decision inputs, its deny shape and where the denial is logged; a side column of the four controls that change the answer and a bottom bar for Azure Policy. | 1.2, 2.5, 7.1 to 7.5, 7.7 to 7.9, 9.8 |
| `06-identity-and-entitlements` | Groups, the five personas, app roles, the five MCP API apps, tools and data containers, showing who can reach what; the managed identities and their federated credentials. | 5.1 to 5.8, 7.6, 9.8 |
| `07-token-anatomy` | One card per token or secret: issuer, audience, key claims, lifetime, who holds it and who validates it. | 6.1, 6.2, 6.9, 6.10 |
| `08-scenarios-acts-1-7` | Seven panels, one per act, each a mini flow with the point it proves and the wall or walls it exercises. | 1.4, 9.1 to 9.9 |
| `09-observability-correlation` | Each layer's log source and join key flowing into the KQL functions (such as `AbwFullChain`), which the workbook, the Sentinel rules, the alerts and the Demo Console read; the exceptions (guardrail, Entra, the private server, Search and Cosmos DB) are marked. | 10.2 to 10.5, 11.1 to 11.5, 11.7 |
| `10-deployment-pipeline` | The 26-step plan of `scripts\Deploy-AgentWall.ps1` as one wrapper around the stages: what each step needs, writes and takes; the check, confirm and verify phases; state and exit codes; the human-only steps; teardown. | 4.1 to 4.11 |
| `11-agent-front-door` | The Act 7 path: user, APIM /agents (token validation, per-user token budget, rate limit), Foundry Responses, the agent, then its tools through APIM; the FinOps meters and where the budget alert sits. | 6.9, 7.3, 7.8, 9.8, 13.1 |
| `12-demo-console` | The Demo Console components, what each talks to (Foundry, APIM, Log Analytics, Azure Resource Manager, Graph, Entra device-code sign-in; scrubbed replay data is read locally), and how it is installed on the jump box. | 3.9, 4.8, 12.1 to 12.6 |
| `13-trust-boundaries-and-failure-modes` | The trust boundaries and the blast radius of each component, what fails closed and what is a soft spot, and a failure, symptom, where-to-look table. | 2.4, 7.9, 13.5, 13.6 |

To cite a diagram from the document, use `Diagram: docs/diagrams/NN-name.excalidraw`.

A suggested order for a talk: 01 (the picture), 03 (one request), 04 and 07 (who proves what), 05 (the four walls),
08 (the seven acts), 09 (proof from the logs), 13 (what can go wrong). The rest are reference material.

## How to open and edit

- **VS Code:** install the Excalidraw extension, then open the `.excalidraw` file.
- **Browser:** go to excalidraw.com, choose Open (or drag the file into the window). The file is read locally by your
  browser. Avoid Live collaboration and shareable links for these files unless you mean to share them.
- **Slides:** in Excalidraw use Export image (PNG or SVG), or use the ready-made pictures in `png\`. To lift one part
  of a diagram, select the shapes and export "only selected".

Box labels are bound to their boxes and arrows are bound to the shapes they connect, so text moves with its box and
arrows follow when you drag a shape. Arrow labels are separate text next to the arrow. Text uses Excalidraw font family
2 ("Normal") at 16 px or larger, with roughness 0. The SVG and PNG previews use Helvetica or Arial; another font in your
Excalidraw build can wrap a few labels differently, and a slightly wider box fixes that.

## How to regenerate

From the repository root, with the repo's Python (the generator uses only the standard library):

```
python docs\diagrams\build_diagrams.py
```

| Option | Effect |
|---|---|
| `--only 01,05` | Build only those diagrams (numbers or full names). |
| `--no-png` | Skip the PNG previews. Use this when Microsoft Edge is not installed. |
| `--crop 03 0 0 1200 900 1` | Render one region of one diagram to `png\_crops\` at the given scale, for a close look. |
| `--clean` | Remove `png\_crops` and the temporary Edge profile. |

PNG previews come from a local, headless `msedge.exe` (found under Program Files); nothing is uploaded to any service.
The script exits with a non-zero code when any check below fails, and a full run also checks that exactly these 13
`.excalidraw` files exist.

## Self-check

Every run validates what it writes, and `python docs\diagrams\validate_excalidraw.py [file ...]` runs the same checks
on its own. Per file it checks that:

- the file is valid JSON with top-level type `excalidraw`, version 2, a source string, an `elements` array, an
  `appState` object and `files` equal to `{}`;
- element ids are unique and every element has the fields Excalidraw expects;
- all numbers are finite, no size is negative, text is 16 px or larger, roughness is 0 and the font family is 2;
- every bound text has an existing container (`containerId`) and the container lists it in `boundElements`;
- every arrow binding points at an existing element that lists the arrow;
- the text is ASCII only, has no GUIDs and none of the strings the share rules forbid.

The generator also runs a layout lint: text fits its box, text does not collide with text or a shape border, shapes do
not partly overlap, nothing sits off the canvas, and no arrow crosses text or a solid box.

## Colour legend

One palette in all 13 diagrams, with the same legend drawn in the top right of each.

| Colour | Meaning | Fill and stroke |
|---|---|---|
| Purple | Identity: Entra ID apps, groups, tokens, federated credentials | `#e5dbff`, `#6741d9` |
| Blue | Network and the API gateway (APIM) | `#d0ebff`, `#1971c2` |
| Green | Compute: agents, MCP servers, Container Apps | `#d3f9d8`, `#2f9e44` |
| Orange | Data stores: Storage, Cosmos DB, AI Search, Key Vault, ACR | `#ffe8cc`, `#e8590c` |
| Teal | Observability: Log Analytics, Application Insights, Sentinel, workbook | `#c5f6fa`, `#0b7285` |
| Red | Deny, risk and the kill switch | `#ffe3e3`, `#e03131` |
| Grey, dashed | Human and manual steps, and optional admin-portal features | `#f1f3f5`, `#868e96` |
| Yellow | Azure Policy and governance | `#fff3bf`, `#f08c00` |
| White with a black chip | People and client tools | `#ffffff`, `#343a40` |

Other conventions:

- A numbered black circle marks the order of a flow. In diagram 10 a white circle with an `H` on a step card marks a
  human-only step, explained in the grey zone below the steps.
- A solid black arrow is an allowed flow, a red arrow is a denied exit or a risk path, and a grey dashed arrow is a
  manual step. A dashed outline means optional, manual or off by default.
- A coloured strip on top of a card (a chip) names the card and carries its colour. In diagram 13 a solid red chip
  means the request is refused (fails closed) and a dashed red chip marks a soft spot.
- Every diagram has a title, a one-line subtitle, a legend and a "What to notice" call-out with three bullets.
- The four walls are Wall 0 (the Foundry guardrail), Wall 1 (APIM), Wall 2 (the MCP server) and Wall 3 (the data plane).
  The document calls them Layers 0 to 3.
- T1 to T4 are the four tokens on the governed path: T1 the user's token for Foundry and the front door, T2 the user's
  token for one MCP API, T3 the managed identity assertion and T4 the on-behalf-of data token. The document uses the same
  labels and adds a letter where a family has several members (T2a and T2b; T4a, T4b and T4c); see sections 6.2 and 6.11.1.

## Editing rule

Edit the generator for structural changes; hand edits in Excalidraw are fine for slides.

Regenerating overwrites the `.excalidraw`, `.svg` and `.png` files, so a hand-edited copy that you want to keep belongs
under another name or outside this folder. For a structural change (a new box, a changed flow, a corrected fact), edit
the matching module below, run the generator and read the PNG before you commit.

| File | Role |
|---|---|
| `build_diagrams.py` | Entry point: builds every diagram, runs the self-check and the layout lint, writes the previews. |
| `excal.py` | The small library: Excalidraw scene builder, SVG renderer, Edge PNG helper, layout lint. |
| `dg01.py` to `dg13.py` | One module per diagram; each exposes `build()` and holds that diagram's text and layout. |
| `validate_excalidraw.py` | The standalone self-check, also called by the generator. |

## Content rules

- Draw only what the repository implements. A detail that cannot be verified in code, templates or scripts is left out.
- ASCII only. No tenant, subscription or object ids, no GUIDs, no real names, domains or dates. Use placeholders such
  as `<tenant-id>`, `<u4>` and `abw.<persona>@<tenant-domain>`.
- Diagrams carry no citations; the document's text carries them.
