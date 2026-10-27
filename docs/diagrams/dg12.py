"""Diagram 12 - Demo Console: components, what each talks to, and the jump-box installation."""
from __future__ import annotations

from excal import INK, Scene, th, wrap

Y0 = 200
C1X, C1W = 60, 360      # presenter's side
C2X, C2W = 580, 980     # the console process
C3X, C3W = 1920, 420    # what the console calls

TITLE = "Demo Console: components, targets and jump-box install"
SUBTITLE = "One local web app; tokens come from the operator's az login or a persona's own sign-in"

# ---------------------------------------------------------------------------------------------- column 1
PRESENTER = "Presenter or operator. Signs in once with their own az login, then presses the beat buttons."
BROWSER = ("Browser at http://127.0.0.1:<port>/ (the default browser on the laptop, Edge on the jump box). Plain JavaScript, "
           "no CDN. Pages: Start, Acts 1-5, Act 6 boards, Act 7 roles and cost, Control Room, Scoreboard. A strip lights "
           "up the layers a job touches.")
CREDS = ("Credentials, local only. The operator's az login cache gives silent tokens for ARM, Graph, Log Analytics, Foundry "
         "and the MCP APIs. .secrets\\msal-test-<id>.json holds one device-code sign-in per persona (an MSAL cache: the "
         "refresh token plus short-lived access tokens).")
EVIDENCE = ("Proof evidence for the Scoreboard and the replay rows. The laptop holds the raw files; the jump box gets only "
            "a scrubbed copy.")
PRIVATE = ("Private browser window for a persona's device-code sign-in. Human step: the person enters the code and "
           "completes MFA.")

# ---------------------------------------------------------------------------------------------- column 2
STARTS = ("Started by Start-Console.bat on the laptop, or by the ABW Demo Console desktop shortcut on the jump box. Either "
          "way the operator's az login is checked first and the browser opens on the console. Closing the window stops it.")
SERVER = ("server.py: Starlette and uvicorn on 127.0.0.1 only (the next free port if 8787 is busy). Serves the web UI and "
          "the /api routes. Sets security headers, accepts only localhost host names and refuses a POST that is not "
          "same-origin.")
JOBS = ("jobs.py (Manager): one button press is one job, in its own thread, with plain-English events the browser "
        "polls. Disruptive scenes never overlap each other or anything that calls the gateway (the allow-list scene may "
        "run beside an agent run); two agent runs never overlap; read-only jobs always run.")
CATALOG = ("catalog.py: the story. Scenes (Acts 1-7), beats, plain-English allow and deny reasons, architecture cards, "
           "portal links for 'Prove it's real' and the KQL pack.")
PERSONAS = ("personas.py: signs a persona in once with a device code against abw-test-client, then asks for tokens "
            "silently, so a job never prompts. Passwords stay in .secrets and reach only the clipboard; TOTP seeds never "
            "leave it (the page gets the 6-digit code).")
PROBE = ("azure_probe.py: read-only probes of Foundry, APIM, the MCP servers, data, Monitor, Sentinel, Policy, Defender, "
         "Entra and more. Each result is cached 120 s. Feeds the Control Room and 'Prove it's real'.")
AGENT = ("agent_run.py: one Foundry agent turn in a child process, one JSON event per line. Approval requests go to the "
         "browser. Enters at the APIM /agents front door once it is deployed, else direct; the legacy PoC agent always "
         "goes direct.")
E2E = ("e2e.py (Act 6): one request through twelve layers: Entra, Conditional Access, guardrails, agent, gateway, MCP "
       "server, data and five watchtowers. Boards live in memory only; every row carries an evidence tag.")
ACT7 = ("act7.py (Act 7): role matrix, FinOps, token budget, agent path and front door. Its only change is the two APIM "
        "named values for the front-door limits, always restored.")
ROLES = ("role_story.py and role_tabs.py: one tab per person plus the Administrator, each with a positive and a negative "
         "beat. A persona makes a real gateway call with their own token; the Administrator runs the agents through the "
         "front door.")
HELPERS = ("Helpers and child processes: demo\\mcpclient.py makes gateway calls in process. Child processes: "
           "scripts\\kill-switch.ps1, scripts\\client-allowlist.ps1, demo\\burst.py, demo\\try-violations.py and "
           "demo\\prove.py.")
GRID = [(CATALOG, PERSONAS), (PROBE, AGENT), (E2E, ACT7), (ROLES, HELPERS)]

# ---------------------------------------------------------------------------------------------- column 3
# (box text, box kind, arrow label)
TARGETS = [
    ("Foundry project: the agents and their Responses API (audience https://ai.azure.com)", "compute",
     "agent_run.py: one agent turn with the operator's token; via APIM /agents once deployed, else direct"),
    ("API Management gateway: /research, /wall, /actions, /vendor, /legacy and the /agents front door", "network",
     "gateway beats with the operator's or a persona's own token; /legacy with the key read through ARM"),
    ("Azure Resource Manager: resources, Azure Policy, APIM named values, Cost Management, Defender alerts", "policy",
     "read-only probes, Cost Management, Defender alerts; scripts and Act 7 write APIM named values"),
    ("Log Analytics query API: the audit, gateway and App Insights tables", "obs",
     "KQL pack, Refresh from logs and the token meter; rows land 2-18 min later"),
    ("Microsoft Graph: the directory and the sign-in log", "identity",
     "reads the sign-in log, Conditional Access, apps, groups, licences; Reset demo restores operator roles"),
    ("Entra ID sign-in: the device-code flow for each persona", "identity",
     "personas.py: one device-code sign-in per persona (abw-test-client); MFA is a human step"),
]
HUMAN_LANE = "human: the person enters the device code and completes MFA"

# ---------------------------------------------------------------------------------------------- install band
BAND_TITLE = "Putting the console on the jump box (Deploy-JumpBox-Console.bat, safe to re-run)"
BAND_NOTE = ("In the VM, each phase is one Azure run-command call (as SYSTEM, in Windows PowerShell 5.1) that returns one "
             "JSON line. The first failing phase stops the run, and every phase can be repeated.")
S1 = ("Stage (laptop): Deploy-JumpBox-Console.bat runs scripts\\jumpbox-console.ps1, which builds a whitelist package: the "
      "console, the agent and demo code, the policy XML, the KQL and Sentinel packs, the generated infra JSON (resource "
      "names and ids, no keys) and the scrubbed evidence. It scans the package for secrets before anything is sent.")
S2 = ("Start (laptop): starts the VM if it is stopped, then reads the state of C:\\abw on it with one Azure run-command "
      "probe. Safe to re-run.")
S3 = "Tools (in the VM): installs Python, Azure CLI and PowerShell 7 when missing. Each installer must carry a valid signature."
S4 = ("Package (in the VM): receives the zip in base64 chunks, rebuilds it, checks its SHA-256 and copies it to C:\\abw. "
      "Never overwrites demo\\evidence.")
S5 = ("Venv (in the VM): creates C:\\abw\\.venv and installs the requirements with the constraints file, only when either "
      "file changed.")
S6 = ("Launcher: desktop shortcuts for the console and the Azure and Foundry portals. C:\\abw\\.secrets is locked to SYSTEM "
      "and the local admin.")
S7 = ("Verify: a throw-away console on port 8799 (health, UI, catalog, scoreboard, policy, personas), private DNS, an "
      "unauthenticated APIM call and a silent sign-in check for each persona already on the VM.")
S8 = ("Show day: Start-JumpBox.bat starts the VM and copies its password. In the Azure portal: the VM, Connect, Bastion. "
      "The first run also needs a one-time az login with a device code as the operator.")
S9 = ("Run: the desktop shortcut starts scripts\\jumpbox-console-start.ps1, which starts the console and opens Edge at "
      "http://127.0.0.1:8787/. Closing the window stops it.")
NEVER = ("Never copied: .secrets by default, the legacy key, raw evidence, the deck, the docs. Persona files travel only "
         "with -IncludePersonaFiles.")

BULLETS = [
    "No token, password or TOTP seed is printed or sent to the browser. Every token comes from the operator's az login or a "
    "persona's own device-code sign-in. The server listens on 127.0.0.1 only and refuses cross-origin POSTs.",
    "Every board row carries an evidence tag, so observed facts are never mixed up with replayed or portal-only ones. The "
    "jump box holds only the scrubbed copy of the evidence.",
    "The Act 6 and Act 7 boards change nothing in Entra except 6.1's real failed sign-ins for one demo user (at most five "
    "in ten minutes). Act 7 changes only the two front-door named values and restores them; Reset demo restores the "
    "baseline: kill switch, allow-list, limits and the operator's roles.",
]
FLOW = [
    "The presenter presses a beat button in the browser.",
    "The browser sends POST /api/jobs to 127.0.0.1. The server refuses it unless it is same-origin.",
    "jobs.py starts the job in its own thread. Scripts and agent turns run as child processes.",
    "The job runs the beat through a module: catalog, probe, e2e, act7, agent_run or a helper.",
    "The module takes a token silently from the operator's az login, or from a persona's own cache, and calls the target.",
    "The job emits plain-English events. The browser polls GET /api/jobs/{id}, draws the cards and lights the strip. Each "
    "row carries an evidence tag: live, probe, logs, graph, arm, replay or portal (Act 7 adds rbac and design).",
]


def need(text: str, w: float, size: float = 16, pad: float = 12) -> float:
    return th(wrap(text, size, w - 2 * pad), size) + 20


def card(sc: Scene, x: float, y: float, w: float, text: str, kind: str, h: float | None = None, **kw):
    return sc.box(x, y, w, text, h=need(text, w) if h is None else h, kind=kind, size=16, align="left", inset=10, **kw)


def build() -> Scene:
    sc = Scene("12-demo-console", 2400, 2000, TITLE, SUBTITLE)

    z1 = sc.zone(C1X, Y0, C1W, 100, "Presenter's side", kind="actor")
    z2 = sc.zone(C2X, Y0, C2W, 100, "Demo Console process: python console\\server.py", kind="compute")
    top = z2.content_y
    off = top - Y0
    ux, uw = C1X + 20, C1W - 40
    ix, iw = C2X + 20, C2W - 40
    sw = (iw - 80) / 2
    gw = (iw - 40 - 20) / 2

    # ------------------------------------------------------------------ heights first, so all columns share one bottom
    row0_h = max(need(STARTS, iw), need(PRESENTER, uw))
    h1 = max(140.0, need(SERVER, sw), need(JOBS, sw))
    row1_y = top + row0_h + 70
    mz_y = row1_y + h1 + 80
    rows = [max(need(a, gw), need(b, gw)) for a, b in GRID]
    mz_bottom = mz_y + off + sum(rows) + 20 * (len(rows) - 1) + 20
    c2_bottom = mz_bottom + 20

    browser_h = need(BROWSER, uw)
    creds_h, evid_h, priv_h = need(CREDS, uw), need(EVIDENCE, uw), need(PRIVATE, uw)
    c1_bottom = row1_y + browser_h + 40 + creds_h + 40 + evid_h + 40 + priv_h + 20
    t_h = max(80.0, *(need(t[0], C3W) for t in TARGETS))
    c3_bottom = top + len(TARGETS) * t_h + (len(TARGETS) - 1) * 60 + 20
    row_bottom = max(c2_bottom, c1_bottom, c3_bottom)
    for z in (z1, z2):
        z.el["height"] = row_bottom - Y0

    # ------------------------------------------------------------------ column 2: the console process
    starts = card(sc, ix, top, iw, STARTS, "compute", h=row0_h, tone="zone")
    server = card(sc, ix, row1_y, sw, SERVER, "compute", h=h1)
    jobs = card(sc, ix + sw + 80, row1_y, sw, JOBS, "compute", h=h1)
    mz = sc.zone(ix, mz_y, iw, mz_bottom - mz_y, "Modules and helpers a job calls", kind="compute")
    assert abs(mz.content_y - (mz_y + off)) < 0.5
    y = mz.content_y
    for (left, right), rh in zip(GRID, rows):
        card(sc, ix + 20, y, gw, left, "compute", h=rh)
        card(sc, ix + 20 + gw + 20, y, gw, right, "compute", h=rh)
        y += rh + 20

    # ------------------------------------------------------------------ column 1: presenter's side
    presenter = card(sc, ux, top, uw, PRESENTER, "actor", h=row0_h)
    browser = card(sc, ux, row1_y, uw, BROWSER, "compute", h=browser_h)
    priv_y = row_bottom - 20 - priv_h
    gap = (priv_y - (row1_y + browser_h) - creds_h - evid_h) / 3
    creds = card(sc, ux, row1_y + browser_h + gap, uw, CREDS, "identity", h=creds_h)
    evidence = card(sc, ux, creds.bottom + gap, uw, EVIDENCE, "data", h=evid_h)
    private = card(sc, ux, priv_y, uw, PRIVATE, "human", h=priv_h)

    # ------------------------------------------------------------------ column 3: targets
    sc.text(C3X, Y0 + 12, "What the console calls", size=20, color=INK)
    gap3 = (row_bottom - 20 - top - len(TARGETS) * t_h) / (len(TARGETS) - 1)
    tboxes = [card(sc, C3X, top + i * (t_h + gap3), C3W, text, kind, h=t_h) for i, (text, kind, _) in enumerate(TARGETS)]

    # ------------------------------------------------------------------ the numbered flow
    sc.arrow(presenter, browser, a_at="b", b_at="t", step=1, label="press a beat", label_side="right", label_w=130)
    y_post, y_poll = row1_y + 45, row1_y + 110
    sc.arrow(browser, server, a_at=f"r@{y_post}", b_at=f"l@{y_post}", step=2, label="POST /api/jobs", label_side="above",
             label_w=130)
    sc.arrow(server, browser, a_at=f"l@{y_poll}", b_at=f"r@{y_poll}", step=6, label="poll GET /api/jobs/{id}: events back",
             label_side="below", label_w=150)
    sc.arrow(server, jobs, a_at="r", b_at="l", step=3)
    sc.arrow(jobs, mz, a_at="b", b_at=f"t@{jobs.cx}", step=4, label="runs the beat", label_side="right", label_w=150)
    for tb, (_, kind, label) in zip(tboxes, TARGETS):
        sc.arrow(z2, tb, a_at=f"r@{tb.cy}", b_at="l", kind=kind, step=5, label=label, label_side="above", label_w=320)

    # credentials and evidence feed the process (no label: described in the boxes)
    sc.arrow(creds, z2, a_at="r", b_at=f"l@{creds.cy}", kind="identity")
    sc.arrow(evidence, z2, a_at="r", b_at=f"l@{evidence.cy}", kind="data")

    # the human step of a persona sign-in, routed through the empty lane under the three columns
    lane_y = row_bottom + 50
    t6 = tboxes[-1]
    sc.arrow(private, t6, a_at=f"b@{private.cx}", b_at=f"b@{t6.cx}", kind="human", dashed=True,
             via=[(private.cx, lane_y), (t6.cx, lane_y)], label=HUMAN_LANE, label_side="above", label_w=520)

    # ------------------------------------------------------------------ install band
    bx, bw_total = 60, 2280
    band_y = row_bottom + 100
    bz = sc.zone(bx, band_y, bw_total, 100, BAND_TITLE, kind="compute")
    sc.text(bx + 840, band_y + 14, BAND_NOTE, size=16, color="#495057", w=1400)
    cw = 392
    cgap = (bw_total - 40 - 5 * cw) / 4
    colx = [bx + 20 + i * (cw + cgap) for i in range(5)]
    row1_items = [(S1, "actor"), (S2, "actor"), (S3, "compute"), (S4, "compute"), (S5, "compute")]
    row2_items = [(S6, "compute"), (S7, "compute"), (S8, "human"), (S9, "compute"), (NEVER, "deny")]
    r1h = max(need(t, cw) for t, _ in row1_items)
    r2h = max(need(t, cw) for t, _ in row2_items)
    r1y = bz.content_y
    r2y = r1y + r1h + 80
    r1 = [card(sc, colx[i], r1y, cw, t, k, h=r1h) for i, (t, k) in enumerate(row1_items)]
    # row 2 runs right to left; the last item is the standing note in the leftmost slot
    r2 = [card(sc, colx[4 - i], r2y, cw, t, k, h=r2h) for i, (t, k) in enumerate(row2_items)]
    for a, b in zip(r1, r1[1:]):
        sc.arrow(a, b, a_at="r", b_at="l")
    sc.arrow(r1[-1], r2[0], a_at="b", b_at="t")
    sc.arrow(r2[0], r2[1], a_at="l", b_at="r")
    sc.arrow(r2[1], r2[2], a_at="l", b_at="r", kind="human", dashed=True)
    sc.arrow(r2[2], r2[3], a_at="l", b_at="r", kind="human", dashed=True)
    band_bottom = r2y + r2h + 20
    bz.el["height"] = band_bottom - band_y

    fb = sc.footer(band_bottom + 40, BULLETS, flow=FLOW, callout_w=860, flow_title="Main flow (numbers on the arrows)")
    sc.fit(fb)
    return sc
