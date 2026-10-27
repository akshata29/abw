"""Diagram 08 - Scenarios, Acts 1-7: each act as a short flow, the point it proves and the wall(s) it exercises."""
from __future__ import annotations

from excal import KINDS, MUTED, RED_TEXT, Scene, r2, th, tw, wrap

PW, PG, IN = 740, 30, 16
XS = [60 + i * (PW + PG) for i in range(3)]
IW = PW - 2 * IN
GREY = "#f8f9fa"
CHIP_W, ARR_GAP, ROW_GAP = 48, 38, 14
BOX_W = [172, 188, 216]

# wall chips: label and palette kind
WALLS = {
    "W0": ("W0 Guardrail", "compute"),
    "W1": ("W1 Gateway", "network"),
    "W2": ("W2 MCP server", "compute"),
    "W3": ("W3 Data plane", "data"),
    "POL": ("Azure Policy", "policy"),
    "ENT": ("Entra ID", "identity"),
    "OBS": ("Observes all four walls", "obs"),
}

# (beat, trigger, control that decides, result, control kind, result kind)
ACTS = {
    1: dict(
        title="Same question, two answers",
        proves="The answer comes from the token, not the prompt. 1.2 is the model being polite; 1.4 is the enforced stop.",
        walls=["W1", "W2", "W3"],
        rows=[
            ("1.1", "Legacy agent: shared key via APIM /legacy", "Legacy server: no user context, broad identity",
             "Answered: LEAKED if confidential terms come back", "deny", "deny"),
            ("1.2", "Governed agent, same Orion question", "Roles read from the token: Falcon only",
             "Model declines Orion in its own words", "compute", "actor"),
            ("1.3", "Ask for the Falcon deal", "OBO: Storage checks the user's own token",
             "Allowed: Storage logs auth=OAuth", "data", "actor"),
            ("1.4", "Raw call for ORION-001, no model", "MCP server: Orion is not in the token's roles",
             "DENIED (HTTP 200), Storage never touched", "compute", "deny"),
        ],
    ),
    2: dict(
        title="No keys",
        proves="Keys are off everywhere, and the platform rejects or rewrites unsafe changes, shown with real requests.",
        walls=["POL", "W3"],
        rows=[
            ("2.1", "9 real Azure changes: keys on, public endpoint, unapproved tool", "Azure Policy initiative",
             "5 BLOCKED, 3 CORRECTED, 1 ALLOWED", "policy", "actor"),
            ("2.2", "KQL: AbwZeroKeys(30d)", "StorageBlobLogs, every request",
             "People, agents, apps: OAuth or TrustedAccess, none by key", "obs", "actor"),
            ("2.3", "Live read of Azure Resource Manager", "Foundry, its connections, the data stores",
             "Local keys off, 5 OAuth connections, stores Entra-only", "policy", "actor"),
        ],
        note=("2.1 takes 4-6 min and deletes its throw-away resources. CORRECTED means an organisation Modify policy "
              "rewrote the change to a safe value first.", MUTED),
    ),
    3: dict(
        title="Whose hands are on the data",
        proves="Private by design: data is reached as the user over private paths, and the vendor key never leaves the gateway.",
        walls=["W1", "W2", "W3"],
        rows=[
            ("3.1", "Positions and credit headroom", "Private MCP server (internal ingress) checks the token itself",
             "Cosmos DB read with the user's own token (OBO)", "compute", "data"),
            ("3.2", "DNS lookup from the laptop", "Private DNS zone, linked to the VNet only",
             "No public record: it cannot resolve", "network", "deny"),
            ("3.3", "Vendor quote request", "APIM checks the user, adds the vendor key from Key Vault",
             "Quote returned; the user and agent never see the key", "network", "actor"),
        ],
        note=("No gateway in front of the private server: the kill switch and rate limit do not cover it. "
              "W1 applies to the vendor path only.", RED_TEXT),
    ),
    4: dict(
        title="When it goes wrong",
        proves="Each control stops the call on its own, and the agent fails closed when one says no.",
        walls=["W0", "W1", "W2"],
        rows=[
            ("4.1", "400 calls in seconds", "APIM rate limit: 120 per 60 s per user",
             "About 125-133 served, the rest HTTP 429", "network", "deny"),
            ("4.2", "Agent asks to place an order", "Human approval gate in Foundry",
             "Approved, still refused: ZYNX is on the restricted list", "human", "deny"),
            ("4.3", "Vendor feed carries a poisoned notice", "Guardrail on some runs, the wall every time",
             "If the model obeys: Orion read and ZYNX order DENIED", "compute", "deny"),
            ("4.4", "Block the Azure CLI client, then call with its token", "APIM client allow-list (abw-allowed-azp)",
             "200, then 403 client_not_allowed. The agent is unaffected", "network", "deny"),
            ("4.5", "SOC puts the user on the kill switch", "APIM deny list (abw-deny-oids), checked first",
             "403 revoked at all four governed servers, the agent fails closed", "network", "deny"),
        ],
        note=("The kill switch and allow-list are APIM named values: they reach the four governed servers, not the "
              "private server (it checks the token itself) or the legacy server.", RED_TEXT),
    ),
    5: dict(
        title="What InfoSec sees",
        proves="One request id joins the agent, gateway, MCP server and data plane, with the user named at every hop.",
        walls=["OBS"],
        rows=[
            ("5.1", "Trace the Orion denial by request id", "AbwIdentityChain joins APIM, MCP audit and Storage",
             "Gateway allowed, MCP denied, no Storage row", "obs", "actor"),
            ("5.2", "Trace an allowed read", "Foundry agent, APIM, MCP server, Storage",
             "obo=True at the MCP server, auth=OAuth at Storage", "obs", "actor"),
        ],
        lines=[
            ("5.3", "AbwUsageByUser(7d): calls, allowed, denied and tools per user"),
            ("5.4", "AbwDenials(24h): denials by layer and reason"),
            ("5.5", "AbwAgentActivity(24h): the agent's tool calls, with obo and request id"),
            ("5.6", "AbwMcpAudit by jti: how long one token keeps serving calls"),
        ],
        note=("Governance tour: 12 cards that open the real portal blades. Logs reach Log Analytics 5-10 min after "
              "a call.", MUTED),
    ),
}

LAYERS = [("Entra ID", "identity"), ("Guardrail", "compute"), ("Foundry agent", "compute"),
          ("Gateway (APIM)", "network"), ("MCP server", "compute"), ("Data plane", "data")]
STOPS = [["6.1"], ["6.6"], ["6.2"], ["6.2", "6.3"], ["6.4"], ["6.5"]]
BEATS6 = [
    ("6.1", "Wrong password: Entra refuses it (AADSTS50126)", "deny"),
    ("6.2", "Keys instead of Entra: 401 at the gateway and at Foundry", "deny"),
    ("6.3", "Valid token, no Wall role: 403 at the gateway", "deny"),
    ("6.4", "Right door, wrong deal: the MCP server refuses, Storage untouched", "deny"),
    ("6.5", "Storage RBAC denial: replayed from the logs", "deny"),
    ("6.6", "Jailbreak: the guardrail stops it before the model answers", "deny"),
    ("6.7", "Cleared user reads Falcon: allowed end to end (Conditional Access is report-only)", "compute"),
    ("6.8", "The same read through the agent: allowed end to end", "compute"),
]
PROVES6 = ("Each refusal stops at the first layer that can say no, and the layers behind it never see the request. "
           "The two allowed beats pass them all.")
PROVES7 = ("Different person, different answer, read from the token. The agent enters through the same gateway, "
           "and spend and a per-user token ceiling are visible and enforced.")


class Panel:
    def __init__(self, zone, x, w, proves, walls):
        self.zone, self.x, self.w, self.proves, self.walls = zone, x, w, proves, walls
        self.bottom = zone.content_y


def small(sc: Scene, x: float, y: float, w: float, h: float, text: str, kind: str, *, solid: bool = False, **kw):
    """A compact chip: boxes need 40 px for one line, so create then shrink (or grow) to h."""
    k = KINDS[kind]
    if solid:
        kw = {"fill": k["tab"], "stroke": k["tab"], "color": k["tabtext"], **kw}
    b = sc.box(x, y, w, text, kind=kind, size=16, pad=4, sw=1 if solid else 2, role="chip", **kw)
    sc.fill_to([b], y + h)
    return b


def chip_w(text: str) -> float:
    return tw(text, 16) + 24


def flow_row(sc: Scene, x: float, y: float, bid: str, trig: str, ctrl: str, res: str, ck: str, rk: str) -> float:
    texts = (trig, ctrl, res)
    h = max([60.0] + [th(wrap(t, 16, w - 16), 16) + 20 for t, w in zip(texts, BOX_W)])
    small(sc, x, y, CHIP_W, h, bid, "actor", solid=True)
    cx = x + CHIP_W + 8
    boxes = []
    for t, w, k in zip(texts, BOX_W, ("actor", ck, rk)):
        boxes.append(sc.box(cx, y, w, t, h=h, kind=k, size=16, pad=8))
        cx += w + ARR_GAP
    sc.arrow(boxes[0], boxes[1], a_at="r", b_at="l")
    sc.arrow(boxes[1], boxes[2], a_at="r", b_at="l", kind="deny" if rk == "deny" else None)
    return h


def line_row(sc: Scene, x: float, y: float, bid: str, text: str, kind: str, w: float = IW) -> float:
    cw = 56
    lines = wrap(text, 16, w - cw - 12)
    h = max(30.0, th(lines, 16) + 10)
    small(sc, x, y, cw, h, bid, kind, solid=True)
    sc.text(x + cw + 12, y + (h - th(lines, 16)) / 2, text, size=16, w=w - cw - 12)
    return h


def block_h(p: Panel) -> float:
    pl = wrap(p.proves, 16, p.w - 2 * IN - 84)
    return max(30.0, th(pl, 16) + 10) + 12 + 30


def finish(sc: Scene, p: Panel, bottom: float) -> None:
    """Stretch the panel to `bottom` and place its Proves / Walls block at the foot."""
    p.zone.el["height"] = r2(bottom - p.zone.y)
    x, y = p.x + IN, bottom - IN - block_h(p)
    pw = p.w - 2 * IN - 84
    ph = max(30.0, th(wrap(p.proves, 16, pw), 16) + 10)
    small(sc, x, y, 72, 30, "Proves", "actor", solid=True)
    sc.text(x + 84, y + 5, p.proves, size=16, w=pw)
    y += ph + 12
    small(sc, x, y, 72, 30, "Walls", "actor", solid=True)
    cx = x + 84
    for key in p.walls:
        label, kind = WALLS[key]
        w = chip_w(label)
        small(sc, cx, y, w, 30, label, kind)
        cx += w + 8


def new_panel(sc: Scene, x: float, y: float, w: float, title: str, proves: str, walls: list[str]) -> Panel:
    z = sc.zone(x, y, w, 300, title, kind="actor")
    z.el["backgroundColor"] = GREY
    return Panel(z, x, w, proves, walls)


def make_flow_panel(sc: Scene, x: float, y: float, n: int) -> Panel:
    spec = ACTS[n]
    p = new_panel(sc, x, y, PW, f"Act {n}: {spec['title']}", spec["proves"], spec["walls"])
    cx, cy = x + IN, p.zone.content_y
    for r in spec["rows"]:
        cy += flow_row(sc, cx, cy, *r) + ROW_GAP
    for bid, text in spec.get("lines", ()):
        cy += line_row(sc, cx, cy, bid, text, "obs") + 10
    if "note" in spec:
        text, col = spec["note"]
        sc.text(cx, cy, text, size=16, color=col, w=IW)
        cy += th(wrap(text, 16, IW), 16) + ROW_GAP
    p.bottom = cy - 10
    return p


def make_e2e_panel(sc: Scene, x: float, y: float) -> Panel:
    p = new_panel(sc, x, y, PW, "Act 6: One request, every layer", PROVES6, ["ENT", "W0", "W1", "W2", "W3"])
    cx, cy = x + IN, p.zone.content_y
    cap = ("The layers on the path, in order (Conditional Access, report-only, sits beside Entra ID). The console board has "
           "12 rows: seven path layers and five watchtowers. A red tag marks where that beat stops.")
    sc.text(cx, cy, cap, size=16, color=MUTED, w=IW)
    cy += th(wrap(cap, 16, IW), 16) + 10
    bw, bh = 84, 60
    gap = (IW - 6 * bw) / 5
    boxes = [sc.box(cx + i * (bw + gap), cy, bw, t, h=bh, kind=k, size=16, pad=6) for i, (t, k) in enumerate(LAYERS)]
    for a, b in zip(boxes, boxes[1:]):
        sc.arrow(a, b, a_at="r", b_at="l")
    ty = cy + bh + 12
    for b, tags in zip(boxes, STOPS):
        total = len(tags) * 38 + (len(tags) - 1) * 6
        tx = b.cx - total / 2
        for t in tags:
            small(sc, tx, ty, 38, 30, t, "deny", solid=True)
            tx += 44
    cy = ty + 30 + 10
    small(sc, cx, cy, IW, 30, "6.7 and 6.8 pass every path layer: allowed end to end", "compute")
    cy += 30 + 16
    for bid, text, kind in BEATS6:
        cy += line_row(sc, cx, cy, bid, text, kind) + 10
    p.bottom = cy - 10
    return p


# ---------------------------------------------------------------------- Act 7
def step_row(sc: Scene, x: float, y: float, w: float, n: int, text: str, kind: str):
    bw = w - 44
    h = max(60.0, th(wrap(text, 16, bw - 16), 16) + 20)
    small(sc, x, y, 36, h, str(n), "actor", solid=True)
    return sc.box(x + 44, y, bw, text, h=h, kind=kind, size=16, pad=8), h


def act71(sc: Scene, z) -> float:
    x, y, w = z.x + IN, z.content_y, z.w - 2 * IN
    steps = [
        ("No token: HTTP 401, from the front door itself", "deny"),
        ("A genuine token for ARM, not Foundry: HTTP 401. Only the Foundry audience is accepted", "deny"),
        ("A valid Foundry token is forwarded. A 404 from Foundry for a made-up response id proves it passed, "
         "and no model token was spent", "actor"),
        ("Honest check: Foundry's own endpoint still answers a valid token, because public network access is on "
         "in this demo", "deny"),
    ]
    for i, (t, k) in enumerate(steps, 1):
        _, h = step_row(sc, x, y, w, i, t, k)
        y += h + 12
    for note in ("Behind the door, in order: validate the token, kill switch, per-user rate limit, per-user token "
                 "budget, token metric.",
                 "Agent beats enter here by default. The legacy PoC agent stays direct, as the before picture."):
        sc.text(x, y + 2, note, size=16, color=MUTED, w=w)
        y += 2 + th(wrap(note, 16, w), 16) + 10
    return y - 10


def act72(sc: Scene, z) -> float:
    x, y, w = z.x + IN, z.content_y, z.w - 2 * IN
    cx = x
    for name in ("Overview", "Priya", "Wes", "Tara", "Carla", "Ian", "Admin"):
        cw = chip_w(name) + 4
        small(sc, cx, y, cw, 30, name, "actor", solid=(name == "Overview"))
        cx += cw + 8
    y += 40
    cap = "Overview runs all six lanes at once. Each person's own tab replays their beats one at a time."
    sc.text(x, y, cap, size=16, color=MUTED, w=w)
    y += th(wrap(cap, 16, w), 16) + 12
    rows = [
        ("Priya\nResearch analyst", ("Research library opens", "actor"), ("Wall server: refused at the gateway", "deny")),
        ("Wes\nInvestment banking", ("Falcon opens", "actor"), ("Orion: refused by the MCP server", "deny")),
        ("Tara\nEquity trader", ("Restricted-list check opens", "actor"), ("ZYNX order: refused by the MCP server", "deny")),
        ("Carla\nCompliance", ("Reads the restricted list", "actor"), ("Order: refused by the MCP server, no Trade.Execute", "deny")),
        ("Ian\nSecurity analyst", ("Reads the audit trail", "actor"), ("Research data: refused at the gateway", "deny")),
        ("Admin\nOperator and agents", ("Falcon and the audit trail", "actor"), ("Orion: refused, no deal role", "deny")),
    ]
    tb = sc.table(x, y, [("Person", 160), ("Allowed", 250), ("Refused", w - 410)], rows, head_kind="actor")
    y = tb["bottom"] + 12
    note = ("Each cell carries an evidence chip: live (a request just made), rbac (role assignment read live), "
            "logs (read back from Log Analytics) or design (not run). A person who has not signed in once "
            "(key P) shows design.")
    sc.text(x, y, note, size=16, color=MUTED, w=w)
    return y + th(wrap(note, 16, w), 16)


def act73(sc: Scene, z) -> float:
    x, y, w = z.x + IN, z.content_y, z.w - 2 * IN
    tw_ = (w - 12) / 2
    tiles = [
        ("Spend this month\nCost Management", "policy"), ("Always-on platform\nfixed price", "policy"),
        ("Usage-based\ngrows with use", "policy"), ("Budget alert\nan alert, not a cap", "policy"),
        ("Tokens, last 24 h\nfrom the front door", "obs"), ("Per-user cap\ntokens/hour, calls/min", "network"),
    ]
    for i, (t, k) in enumerate(tiles):
        sc.box(x + (i % 2) * (tw_ + 12), y + (i // 2) * 72, tw_, t, h=60, kind=k, size=16, pad=8)
    y += 3 * 72 + 2
    tables = [
        ("Spend by service. API Management is the biggest line: a fixed price, not a per-call cost.", "policy"),
        ("LLM tokens per user and agent, with the share of this hour's budget used (AbwTokenUsage).", "obs"),
        ("Calls per user for 7 days, as the MCP servers logged them (AbwUsageByUser).", "obs"),
    ]
    for t, k in tables:
        b = sc.box(x, y, w, t, kind=k, size=16, pad=8)
        y += b.h + 10
    note = ("The budget mails the resource-group Owners at 50, 80 and 100 % of actual spend and at 100 % forecast. "
            "Azure bills hours late. No price per token is shown.")
    sc.text(x, y + 2, note, size=16, color=MUTED, w=w)
    return y + 2 + th(wrap(note, 16, w), 16)


def act74(sc: Scene, z) -> float:
    x, y, w = z.x + IN, z.content_y, z.w - 2 * IN
    steps = [
        ("One real agent call through the front door; its tokens are counted", "actor"),
        ("abw-agent-token-quota is cut to 1 token (an APIM named value)", "network"),
        ("The next call: HTTP 403 token_quota_exceeded, 0 model rounds, 0 tokens spent", "deny"),
        ("The value is restored: a finally block, and again by Reset demo", "actor"),
    ]
    prev = None
    for i, (t, k) in enumerate(steps, 1):
        b, h = step_row(sc, x, y, w, i, t, k)
        if prev is not None:
            sc.arrow(prev, b, a_at="b", b_at="t", kind="deny" if k == "deny" else None)
        prev = b
        y += h + 40
    y -= 40
    note = ("Alternate: abw-agent-rpm set to 1 gives HTTP 429 rate_limited with Retry-After of about 100 s. "
            "Both are global settings: use a demo tenant only.")
    sc.text(x, y + 14, note, size=16, color=MUTED, w=w)
    return y + 14 + th(wrap(note, 16, w), 16)


def make_act7(sc: Scene, y: float) -> Panel:
    p = new_panel(sc, 60, y, 2280, "Act 7: Every role, the agent's front door, and the bill", PROVES7,
                  ["W1", "W2", "W3"])
    widths = [520, 760, 440, 468]
    titles = ["7.1 Agent front door: four steps", "7.2 Every kind of user: one yes and one no each",
              "7.3 Cost and tokens: the FinOps board", "7.4 Runaway agent: cut the token budget"]
    subs, sx = [], 76
    for w, t in zip(widths, titles):
        subs.append(sc.zone(sx, p.zone.content_y, w, 300, t, kind="actor"))
        sx += w + 20
    bottom = max(f(sc, z) for f, z in zip((act71, act72, act73, act74), subs)) + 16
    for z in subs:
        z.el["height"] = r2(bottom - z.y)
    p.bottom = bottom
    return p


def chip_key(sc: Scene, x: float, y: float, w: float) -> float:
    rows = [("W0", "Foundry guardrail: preview, best effort"), ("W1", "APIM gateway: token, role, client, rate, kill switch"),
            ("W2", "MCP server: per-tool rules, on-behalf-of"), ("W3", "Data plane: its own roles, on the user's own token"),
            ("POL", "Azure Policy: rules on the Azure resources")]
    h = 16 + 25 + 10 + (len(rows) + 1) * 36 + 12
    sc.box(x, y, w, "", h=h, kind="actor", role="panel", fill=GREY, stroke="#343a40")
    sc.text(x + 16, y + 14, "Chip key", size=20)
    ry = y + 14 + 25 + 10
    for key, desc in rows:
        label, kind = WALLS[key]
        small(sc, x + 16, ry, 150, 30, label, kind)
        sc.text(x + 16 + 150 + 12, ry + 5, desc, size=16, w=w - 16 - 150 - 12 - 16)
        ry += 36
    small(sc, x + 16, ry, 74, 30, "Refused", "deny")
    small(sc, x + 16 + 82, ry, 74, 30, "Allowed", "actor")
    sc.text(x + 16 + 150 + 12, ry + 5, "Result colour: red = refused or leaked, white = allowed",
            size=16, w=w - 16 - 150 - 12 - 16)
    return y + h


def build() -> Scene:
    sc = Scene("08-scenarios-acts-1-7", 2400, 2400, "Scenarios: Acts 1-7 and the wall each one proves",
               "Seven acts, each a short flow: what it proves and which walls it exercises")
    y = 190
    for row in ((1, 2, 3), (4, 5, 6)):
        panels = [make_flow_panel(sc, XS[i], y, n) if n != 6 else make_e2e_panel(sc, XS[i], y)
                  for i, n in enumerate(row)]
        bottom = max(p.bottom + 16 + block_h(p) + IN for p in panels)
        for p in panels:
            finish(sc, p, bottom)
        y = bottom + 24
    p7 = make_act7(sc, y)
    bottom = p7.bottom + 16 + block_h(p7) + IN
    finish(sc, p7, bottom)

    top = bottom + 40
    c = sc.callout(60, top, 1500, [
        "Each act reads left to right: what is tried, the control that decides, and the result. Red results are "
        "refusals (or the legacy leak); the chips under each panel name the walls it exercises.",
        "Different acts stop the request at different walls: the gateway (W1), the MCP server (W2), the data plane "
        "(W3) and the guardrail (W0). Act 2 proves keys are off, and Act 5 shows how the evidence joins up.",
        "Act 7 runs as real people: a different answer per persona, the agent's front door, the bill and a live "
        "token budget. A persona that has not signed in once shows design, a predicted result and not a run.",
    ])
    key_bottom = chip_key(sc, 1620, top, 720)
    c.el["height"] = r2(max(c.bottom, key_bottom) - top)
    sc.fit(max(c.bottom, key_bottom))
    return sc
