"""Diagram 10 - deployment pipeline: the orchestrator's 26 steps, the files that chain them, the human-only steps and teardown."""
from __future__ import annotations

from excal import KINDS, MUTED, RED_TEXT, Scene, th, wrap

X0, COL_W, COL_GAP = 85, 406, 50
COLS = [X0 + i * (COL_W + COL_GAP) for i in range(5)]
HEAD_H, BODY_GAP, ROW_GAP = 40, 4, 60
WHITE, GREY = "#ffffff", "#495057"
INFO_FILL, INFO_STROKE = "#f8f9fa", "#343a40"

ORCH = "scripts\\Deploy-AgentWall.ps1 - one command, resumable. Start with -CheckOnly (read-only)"

# Card = (label, chip title, kind, body, human markers, dashed body).  Info panel = (title, body).
# Step bodies: script, purpose, needs (files in infra\generated), writes, planning estimate.
PHASES = {
    "A": ("Check and plan", "actor",
          "Prerequisites, az sign-in, configuration and name checks, permissions, model capacity. Then the plan table "
          "(run, done or skip per step, with estimates) and what the run will change. -CheckOnly (alias -DryRun) stops "
          "here: strictly read-only, it also compiles the templates when Bicep is installed; exit 3 if blocked, else 0."),
    "B": ("Confirm", "actor",
          "Type the resource group name to start; anything else cancels. -Yes skips the prompt, and a non-interactive "
          "session needs it."),
    "C": ("Run the steps in order", "actor",
          "A plain loop over the plan, never parallel. A step starts only when its needed files exist (otherwise a "
          "required step stops the run and an optional one is skipped). Up to 3 attempts, only for transient errors, "
          "60 s apart (90 s for governance). Exit 0 with its file missing counts as failed. A failed required step "
          "(1-17) stops the run; a failed optional step (18-26) only warns."),
    "D": ("Verify (read-only)", "actor",
          "Resources in the group, Container Apps provisioned, API Management Succeeded, the Foundry model deployment, "
          "3 or more agents, the policy assignment, Sentinel rules, the KQL function pack, the workbook, and Entra "
          "counts (7 apps, 6 groups, 5 users). The result is saved in deploy-state.json."),
    "E": ("What still needs a human", "actor",
          "Printed at the end: persona sign-in and Foundry consents, the optional admin-portal switches, the optional "
          "proof run, the jump-box sign-in and teardown. They are the grey zone below."),
}

KEY_INFO = ("How to read the cards",
            "Chip = the step id that -From, -Only, -Until and -Skip take. Number = run order. Letters A-E = the "
            "orchestrator's own phases. est. = planning minutes, not a guarantee. Grey H = a human-only step (zone "
            "below). White chip = operator-side tooling. Dashed card = off by default. Default plan: steps 1-22.")
CHOOSE_INFO = ("Choose what runs",
               "By step id: -From, -Only, -Until, -Skip. Run again: -Force. Switches: -SkipJumpBox, -SkipConsole, "
               "-SkipFrontDoor, -SkipBudget, -SkipGuardrail; opt in with -WithExtras (23-24) and -RunProofs (25-26). "
               "-ResetState archives the local state and starts fresh; -AdoptExistingEntra lets step 2 update abw-* "
               "objects already in the tenant.")
STATE_INFO = ("State and logs",
              "infra\\generated\\deploy-state.json holds, per step, status, time, attempts and a note, plus the last 50 "
              "runs and the verify result. Written atomically, never by -CheckOnly.\n"
              "Log, one per run, in infra\\generated\\logs:\ndeploy-<yyyyMMdd-HHmmss>.log\n"
              "Each step's own result file sits beside the state file.")
EXIT_INFO = ("Exit codes",
             "0 = done\n1 = a required step failed, or a blocking problem\n2 = done, but an optional step failed\n"
             "3 = -CheckOnly found a blocker\n"
             "Rerun the same command: finished steps are skipped and the failed one is retried.")

# (number, step id, optional?, kind, script, purpose, needs, writes, estimate, switch note, human markers, off by default)
STEPS = [
    (1, "preflight", False, "actor", "scripts\\deploy.ps1 -Stage preflight",
     "Tagged resource group, resource providers registered, operator public IP noted (informational).",
     "nothing", "preflight.json", "1-3", "", [], False),
    (2, "entra1", False, "identity", "identity\\Setup-Entra.ps1 -Phase 1",
     "6 groups, 5 persona users, 5 MCP API apps (scopes, app roles), 2 client apps, admin consent including the OBO "
     "consent to Storage, Cosmos DB and AI Search.",
     "nothing", "entra.json; the agent-client secret goes to .secrets", "3-5", "", ["H1"], False),
    (3, "network", False, "network", "scripts\\deploy.ps1 -Stage network",
     "VNet, 4 subnets, NAT gateway, NSG on the APIM subnet, 14 private DNS zones (01-network.bicep).",
     "nothing", "network.json", "2-4", "", [], False),
    (4, "foundry", False, "compute", "scripts\\deploy.ps1 -Stage foundry",
     "Foundry account, project, model deployment, agent subnet injection, bring-your-own agent stores, AMPLS, Log "
     "Analytics, App Insights (vendored template).",
     "network.json", "foundry.json", "15-20", "", [], False),
    (5, "foundryrbac", False, "identity", "scripts\\deploy.ps1 -Stage foundryrbac",
     "Foundry User for the operator on the account; Foundry Agent Consumer for the persona group on the project "
     "(02-foundry-rbac.bicep).",
     "foundry.json, entra.json", "foundryrbac.json", "1-3", "", [], False),
    (6, "platform", False, "data", "scripts\\deploy.ps1 -Stage platform",
     "6 managed identities, Key Vault, ACR, Storage with WORM audit, Cosmos DB, AI Search, 2 Container Apps "
     "environments, RBAC, private endpoints (03-platform.bicep).",
     "network.json, entra.json", "platform.json", "10-15", "", [], False),
    (7, "images", False, "actor", "scripts\\build-images.ps1 -Target mcp",
     "ACR Tasks builds the abw-mcp image (az acr build, no local Docker).",
     "platform.json (the ACR)", "images.json", "5-8", "", [], False),
    (8, "apps", False, "compute", "scripts\\deploy.ps1 -Stage apps",
     "6 MCP servers as Container Apps from one image (04-apps.bicep); creates the vendor key secret.",
     "platform.json, entra.json, images.json", "apps.json", "5-8", "", [], False),
    (9, "entra2", False, "identity", "identity\\Setup-Entra.ps1 -Phase 2",
     "Federated credentials let 4 managed identities (research, wall, actions, private) act as their API apps: OBO "
     "without a secret.",
     "platform.json, entra.json", "no file of its own (recorded in deploy-state.json)", "1-2", "", [], False),
    (10, "apim", False, "network", "scripts\\deploy.ps1 -Stage apim",
     "API Management StandardV2 with outbound VNet integration and a private endpoint, named values, logger, API "
     "Center (05-apim.bicep). The long one.",
     "network.json, entra.json, foundry.json", "apim.json", "35-50", "", [], False),
    (11, "apis", False, "network", "scripts\\deploy.ps1 -Stage apis",
     "MCP APIs for research, wall, actions and vendor with the mcp-jwt policy, the /legacy API with a subscription "
     "key, protected-resource metadata (05-apim-apis.bicep).",
     "apps.json, entra.json, apim.json", "apis.json", "3-6", "", [], False),
    (12, "images-seed", False, "actor", "scripts\\build-images.ps1 -Target seed",
     "ACR Tasks builds the abw-seed image.",
     "platform.json", "images-seed.json", "3-6", "", [], False),
    (13, "seed", False, "data", "scripts\\deploy.ps1 -Stage seed",
     "An in-VNet Container Apps job loads the synthetic data over private endpoints; the stage polls it for up to 12 "
     "min (04b-seed-job.bicep).",
     "platform.json, images-seed.json", "seed.json", "5-12", "", [], False),
    (14, "baseline", False, "identity", "identity\\Use-AdminAsPersona.ps1 -As wes -Also tara",
     "Role baseline: the signed-in admin mirrors the roles and groups of wes and tara, so agent beats, which run as "
     "the operator, have them before the first consent.",
     "entra.json", "roles and groups in Entra, no file", "1-2", "", [], False),
    (15, "connections", False, "compute", "scripts\\foundry-connections.ps1",
     "6 Foundry connections (5 OAuth, 1 legacy key), then registers the Foundry redirect URLs on the agent client.",
     "entra.json, apis.json, apps.json, foundry.json and the agent-client secret", "connections.json", "5-10", "",
     ["H2"], False),
    (16, "agents", False, "compute", "src\\agent\\create_agents.py",
     "Publishes 3 agents: abw-poc-legacy, abw-wall-desk and abw-wall-desk-redteam (no guardrail yet).",
     "foundry.json, connections.json", "agents.json", "2-4", "", ["H2"], False),
    (17, "governance", False, "policy", "scripts\\deploy.ps1 -Stage governance",
     "Policy initiative and assignment, exemptions, the guardrail abw-agent-guardrails, diagnostics; then the "
     "observability pack: KQL function pack, 9 Sentinel rules, Cockpit workbook, 3 ops alerts (-Stage observability "
     "re-runs only the pack). Retries after 90 s if a role assignment has not propagated.",
     "foundry.json, platform.json", "governance.json, observability.json, policy.json", "8-12", "", [], False),
    (18, "guardrail", True, "compute", "src\\agent\\create_agents.py --rai abw-agent-guardrails",
     "Attaches the guardrail to abw-wall-desk and publishes a 4th agent, abw-wall-desk-redteam-shielded. Needs the "
     "guardrail that step 17 creates.",
     "agents.json, governance.json", "agents.json (adds the shielded agent)", "1-3", "off with -SkipGuardrail", [], False),
    (19, "frontdoor", True, "network", "scripts\\deploy.ps1 -Stage frontdoor",
     "The /agents API on APIM: JWT check, kill switch, rate limit and per-user token budget "
     "(08-agent-frontdoor.bicep).",
     "apim.json", "frontdoor.json", "5-10", "off with -SkipFrontDoor", [], False),
    (20, "budget", True, "policy", "scripts\\deploy.ps1 -Stage budget",
     "USD 1,200 a month on the resource group by default. Alerts at 50, 80 and 100 % actual and 100 % forecast. An "
     "alert, not a cap (09-budget.bicep).",
     "nothing", "budget.json", "1-2", "off with -SkipBudget", [], False),
    (21, "jumpbox", True, "compute", "scripts\\jumpbox.ps1",
     "snet-jump with its NSG, a Windows Server 2022 VM with no public IP, Bastion Developer, auto-shutdown.",
     "network.json", "jumpbox.json (deployedAt; no secrets)", "10-15", "off with -SkipJumpBox", [], False),
    (22, "console", True, "compute", "scripts\\jumpbox-console.ps1",
     "Installs the Demo Console on the VM: tools, package, venv, launcher, verify. Persona files only with "
     "-IncludePersonaFiles.",
     "jumpbox.json", "jumpbox.json (consoleOnVm)", "15-25",
     "off with -SkipJumpBox or -SkipConsole; skipped if demo\\evidence-scrubbed\\scoreboard.json is missing", ["H4"], False),
    (23, "extras-defender", True, "obs", "scripts\\extras-defender-sentinel.ps1",
     "Sentinel connector and incident rule for Defender for Cloud, then a read-back of alerts, Sentinel rows and "
     "Purview reachability. No paid Defender plan is enabled.",
     "platform.json", "trackb-defender.json", "2-5", "off by default: add -WithExtras", ["H3"], True),
    (24, "extras-identity", True, "identity", "scripts\\extras-agent-identity.ps1 -SkipConditionalAccess",
     "Records the Entra Agent ID and grants the Agent 365 gateway role on APIM. The script alone also creates ONE "
     "report-only Conditional Access policy; the orchestrator skips it.",
     "apim.json, entra.json", "trackb-identity.json", "1-3", "off by default: add -WithExtras", ["H3"], True),
    (25, "proofs", True, "actor", "demo\\prove.py",
     "The 18 proofs (P00-P17); they call the gateway.",
     "agents.json, governance.json", "demo\\evidence\\prove-<utc>.json; recorded in deploy-state.json", "30-40",
     "off by default: add -RunProofs", [], True),
    (26, "scoreboard", True, "actor", "demo\\scoreboard.py --check",
     "Prints the table, writes the scoreboard and exits 1 unless every proof P00-P17 has a latest PASS.",
     "nothing", "demo\\evidence\\SCOREBOARD.md and scoreboard.json", "1", "off by default: add -RunProofs", [], True),
]

HUMAN = [
    ("H1", "Persona MFA and TOTP secret",
     "priya, wes and tara each enrol an authenticator secret once: about 12 min each; the whole one-time manual prep "
     "is about 40 min. identity\\Persona-Totp.py stores the secret and produces the codes.\n"
     "Path B needs none of it: the admin mirrors a persona (identity\\Use-AdminAsPersona.ps1; step 14 does it for wes "
     "and tara).\nWhen: after step 2, once the users exist."),
    ("H2", "OAuth consent per persona",
     "Each persona consents once to each of the 5 OAuth connections: the first agent call returns a consent link, "
     "valid about 10 min. Foundry then keeps the token 60-90 min, so a role change reaches the agent only with the "
     "next token.\nApply the role baseline (step 14) first: a role-less first consent leaves the agent with empty "
     "tool lists long after the roles are fixed (the token lives 60-90 min, the tool list about 15-20 min).\n"
     "When: after steps 15 and 16."),
    ("H3", "Admin-portal switches (optional)",
     "Three admin-portal switches: the Agent 365 gateway (the tenant-level consent), Defender XDR 'Security for AI "
     "agents' and Purview 'DSPM for AI'. Click-paths: docs\\DEMO-GUIDE.md, section A6. Teardown does not reverse "
     "them.\nWhen: optional, no fixed place in the order."),
    ("H4", "VM sign-in (jump box)",
     "Start-JumpBox.bat starts the VM, opens its portal page and copies the admin password for 120 s. Then Connect > "
     "Bastion, start the 'ABW Demo Console' desktop shortcut and, on the first start, sign in once with a device code "
     "(az login) as the admin. Bastion Developer allows one session at a time.\n"
     "When: after the console (step 22) is installed on the VM."),
]
HUMAN_NOTE = ("Also by hand: each persona signs in once to the Demo Console with a device code (it opens a private "
              "browser window and copies the code) before the 'Acting as' beats.")

TEARDOWN = [
    "Report-only Conditional Access policy and Agent 365 role grant removed",
    "Foundry agent capability hosts (they hold the agent subnet)",
    "Log Analytics workspace force-deleted (else its name is held 14 days)",
    "Resource group deleted, everything in it: 20-40 min",
    "Soft-deleted Foundry account, Key Vault and APIM purged",
    "Subscription policy: the abw-agent-platform-controls initiative and its definitions",
    "Entra: demo users, sg-abw-* groups and abw-* apps",
    "Local secrets and generated state (only with -CleanLocal)",
]
TEARDOWN_NOTE = ("-WhatIf prints everything it would remove and deletes nothing. -Yes skips the type-the-resource-group-name "
                 "prompt. -KeepEntra skips 0 and 6, -SkipPurge skips 4, -CleanLocal adds 7. It only touches objects it can "
                 "prove belong to the demo.")
TEARDOWN_RED = "Not reversed: the 3 admin-portal switches (H3)."

BULLETS = [
    "Each step's result is a file in infra\\generated. A step starts only when the files it needs exist, a failed "
    "required step (1-17) stops the run, and rerunning the same command resumes where it stopped.",
    "The one command wraps the machine steps only. Persona MFA, OAuth consents, the admin-portal switches and the VM "
    "sign-in stay with people (grey H markers).",
    "Two ordering rules: create_agents.py runs twice, because the guardrail step (18) needs the guardrail that "
    "governance (17) creates; and the role baseline (14) must exist before the first OAuth consent (H2). "
    "API Management (est. 35-50 min) dominates the run time.",
]


def need(text: str, w: float, size: float = 16, pad: float = 12) -> float:
    return th(wrap(text, size, w - 2 * pad), size) + 20


def info_need(title: str, body: str, w: float, size: float = 16, title_size: float = 20, pad: float = 14) -> float:
    return pad + th(wrap(title, title_size, w - 2 * pad), title_size) + 8 + th(wrap(body, size, w - 2 * pad), size) + pad


def solid(kind: str) -> dict:
    k = KINDS[kind]
    return dict(fill=k["tab"], stroke=k["tab"], color=k["tabtext"])


def human_marker(sc: Scene, tag: str, cx: float, cy: float):
    return sc.marker(tag, cx, cy, r=17, fill=WHITE, stroke=GREY, text_color=GREY, sw=2)


def card(sc: Scene, x: float, y: float, w: float, title: str, kind: str, body: str, h: float,
         num: int | str | None = None, humans: list[str] | None = None, pad: float = 12, body_dashed: bool = False):
    """Header chip (solid) over a body box; returns (head, body)."""
    head = sc.box(x, y, w, title, h=HEAD_H, kind=kind, size=16, pad=pad, role="chip", dashed=False, **solid(kind))
    bod = sc.box(x, y + HEAD_H + BODY_GAP, w, body, h=h, kind=kind, size=16, align="left", valign="top", tone="zone",
                 inset=10, dashed=body_dashed)
    if num is not None:
        sc.marker(num, x + 24, y + HEAD_H / 2, r=16)
    for tag in humans or []:
        human_marker(sc, tag, x + w - 26, y + HEAD_H / 2)
    return head, bod


def step_slot(s: tuple) -> tuple:
    n, sid, optional, kind, script, what, needs, writes, est, note, humans, off = s
    title = f"{sid} (optional)" if optional else sid
    body = f"{script}\n{what}\nneeds: {needs}\nwrites: {writes}\nest. {est} min"
    if note:
        body += f"\n{note}"
    return ("card", n, title, kind, body, humans, off)


def phase_slot(letter: str) -> tuple:
    title, kind, body = PHASES[letter]
    return ("card", letter, title, kind, body, [], False)


def build() -> Scene:
    sc = Scene("10-deployment-pipeline", 2400, 3300, "Deployment pipeline: 26 steps, state files, human steps",
               "One command wraps the machine steps and resumes after a failure; people do the consents, MFA and sign-ins")

    slots = [step_slot(s) for s in STEPS]
    rows_spec = [
        [phase_slot("A"), phase_slot("B"), phase_slot("C"), ("info", *KEY_INFO), ("info", *CHOOSE_INFO)],
        slots[0:5], slots[5:10], slots[10:15], slots[15:20], slots[20:25],
        [slots[25], phase_slot("D"), phase_slot("E"), ("info", *STATE_INFO), ("info", *EXIT_INFO)],
    ]

    # ---------------------------------------------------------------- the wrapper: the one-command orchestrator
    wz = sc.zone(60, 190, 2280, 100, ORCH, kind="actor")
    wz.el["backgroundColor"] = "#f8f9fa"

    y = wz.content_y
    rows: list[list[tuple]] = []
    for spec in rows_spec:
        heights = []
        for s in spec:
            if s[0] == "card":
                heights.append(HEAD_H + BODY_GAP + need(s[4], COL_W))
            else:
                heights.append(info_need(s[1], s[2], COL_W))
        row_h = max([HEAD_H + BODY_GAP + 110] + heights)
        drawn = []
        for c, s in enumerate(spec):
            x = COLS[c]
            if s[0] == "card":
                _, label, title, kind, body, humans, off = s
                drawn.append(card(sc, x, y, COL_W, title, kind, body, row_h - HEAD_H - BODY_GAP, num=label,
                                  humans=humans, pad=44, body_dashed=off))
            else:
                _, title, body = s
                drawn.append((sc.panel(x, y, COL_W, title, body, kind="actor", h=row_h, size=16, title_size=20,
                                       fill=INFO_FILL, stroke=INFO_STROKE),))
        rows.append(drawn)
        y += row_h + ROW_GAP
    rows_bottom = y - ROW_GAP

    # ---------------------------------------------------------------- flow: left to right inside a row, serpentine between rows
    chain_end = [2, 4, 4, 4, 4, 4, 2]
    for r, drawn in enumerate(rows):
        for c in range(chain_end[r]):
            sc.arrow(drawn[c][1], drawn[c + 1][1], a_at="r", b_at="l")
    for r in range(len(rows) - 1):
        last, first = rows[r][chain_end[r]][1], rows[r + 1][0][0]
        ymid = (last.bottom + first.top) / 2
        sc.arrow(last, first, a_at=f"b@{last.cx}", b_at=f"t@{first.cx}", via=[(last.cx, ymid), (first.cx, ymid)])

    wz.el["height"] = rows_bottom + 24 - wz.y

    # ---------------------------------------------------------------- human-only steps (left) and teardown (right)
    zy = wz.bottom + 40
    hz = sc.zone(60, zy, 1370, 100, "Human-only steps (outside the one command)", kind="human")
    hw, hgap = 645, 30
    hy = hz.content_y
    for r in range(2):
        pair = HUMAN[r * 2:(r + 1) * 2]
        h = max(100.0, max(need(p[2], hw) for p in pair))
        for c, (tag, title, body) in enumerate(pair):
            x = 85 + c * (hw + hgap)
            card(sc, x, hy, hw, title, "human", body, h, body_dashed=True, pad=44)
            human_marker(sc, tag, x + 26, hy + HEAD_H / 2)
        hy += HEAD_H + BODY_GAP + h + 24
    hn = sc.text(X0, hy - 8, HUMAN_NOTE, size=16, color=MUTED, w=1300)
    hz_bottom = hn.bottom + 16

    tz = sc.zone(1470, zy, 870, 100, "Teardown: scripts\\teardown.ps1 (not part of the one command)", kind="deny")
    ty = tz.content_y
    for i, text in enumerate(TEARDOWN):
        sc.marker(i, 1506, ty + 20, r=16, kind="deny")
        sc.box(1534, ty, 786, text, h=40, kind="deny", size=16, align="left", inset=12)
        ty += 48
    ty += 4
    n1 = sc.text(1490, ty, TEARDOWN_NOTE, size=16, color=MUTED, w=830)
    ty = n1.bottom + 8
    n2 = sc.text(1490, ty, TEARDOWN_RED, size=16, color=RED_TEXT, w=830)
    tz_bottom = n2.bottom + 16

    bottom = max(hz_bottom, tz_bottom)
    for z in (hz, tz):
        z.el["height"] = bottom - z.y

    fb = sc.footer(bottom + 40, BULLETS, flow=None, callout_w=1560)
    sc.fit(fb)
    return sc
