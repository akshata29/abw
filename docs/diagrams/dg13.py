"""Diagram 13 - Trust boundaries and failure modes: blast radius, what fails closed or soft, and the failure table."""
from __future__ import annotations

from excal import INK, KINDS, MUTED, RED_TEXT, Scene, th, wrap

WHITE = "#ffffff"

TITLE = "Trust boundaries and failure modes"
SUBTITLE = "What each boundary protects, what fails closed or soft, and where to look when it breaks"
KEY_CLOSED = "the request is refused"
KEY_SOFT = "the request can still pass, or the control is late or best-effort"
PATH_NOTE = "One governed request crosses these boundaries in order. Each wall decides again on its own."
HEAD_BAND = "Around the request path: the public edge, the operator, governance and logging"
HEAD_TABLE = "Failure, symptom and where to look"

# (zone title, kind, role, blast radius, closed, soft)
PATH = [
    ("Callers", "actor",
     "Role: five personas, the operator, the Demo Console and test clients. Each holds an Entra token: T1 for Foundry, "
     "T2a for an MCP API.",
     "Blast radius: a stolen token carries only that person's roles.",
     "Closed: a call with no valid token is refused at the gateway (401). /legacy takes a shared key instead, by design.",
     "Soft spot: a token stays valid until it expires (60-90 min)."),
    ("Entra ID", "identity",
     "Role: signs every token. App roles on users and group membership decide what each wall allows. Federated "
     "credentials let the research, wall, actions and private UAMIs ask for OBO tokens.",
     "Blast radius: a wrong role or group here is inherited by every wall below.",
     "Closed: a person with no app role (Ian) is refused on every tool call at the gateway and sees no tools. Nobody "
     "holds Wall.Orion.",
     "Soft spot: Conditional Access is report-only. A role change can take up to about 30 s to reach a new token."),
    ("Foundry (Wall 0)", "compute",
     "Role: agents call only the tools in allowed_tools. Foundry holds each user's OAuth token per connection. The "
     "governed agent asks a human to approve place_order. The guardrail screens prompts, completions and tool output.",
     "Blast radius: a prompt-injected agent acts only with the caller's own token and roles, inside allowed_tools.",
     "Closed: tools outside allowed_tools are not offered. place_order waits for a human approval.",
     "Soft spot: the guardrail is preview and best-effort. Foundry reuses a token until it expires, so a role change "
     "reaches the agent late."),
    ("APIM gateway (Wall 1)", "network",
     "Role: validates the token, then refuses a revoked user, a client not on the allow-list, a missing scope or a "
     "missing role. Rate limit: 120 calls per 60 s per user.",
     "Blast radius: if APIM is bypassed, research, wall, actions and private re-check the token themselves; vendor "
     "and legacy do not. /legacy has no token check.",
     "Closed: 401 (token), 403 (revoked, client, scope, role) or 429 (rate), all before any MCP server runs.",
     "Soft spot: the kill switch and allow-list take 45-90 s. The private MCP server is not behind APIM: no kill "
     "switch, no rate limit."),
    ("MCP servers (Wall 2)", "compute",
     "Role: internal Container Apps environment in the VNet. Re-verifies the token, filters tools by role, then swaps "
     "the token (OBO, with its T3 assertion) for the user's own T4a/b/c. One UAMI per server.",
     "Blast radius: its UAMI (audit append and image pull; actions also reads the restricted list; vendor reads one "
     "Key Vault secret) plus the user tokens it is handling. Legacy is deliberately broad.",
     "Closed: refuses a bad token (401) or a missing scope (403). A tool the caller has no role for, a project not in the "
     "token roles or an OBO failure gets a DENIED result (HTTP 200). All are logged.",
     "Soft spot: the audit blob write is asynchronous and best-effort. Search and Cosmos logs are matched by time."),
    ("Data plane (Wall 3)", "data",
     "Role: Storage, Cosmos and Search accept private traffic only, with no keys. The data plane's own roles are "
     "checked on the user's own T4a/b/c token.",
     "Blast radius: what that person's groups grant, and no more. Exception: actions reads the restricted list as "
     "the service.",
     "Closed: no data-plane role, no data. Storage answers 403 and the server reports storage_rbac_denied. Nobody holds a "
     "role on wall-orion.",
     "Soft spot: the Search role is index-wide; public and wall documents are split by a server-side filter."),
]

PLANES = [
    ("Public edge: reachable from the Internet", "network",
     "Role: the APIM gateway (a user token, or the subscription key on /legacy), the Foundry endpoint (keyless, Entra "
     "only), Container Registry (admin off, pull needs AcrPull), Key Vault (default-Deny; the NAT IP and trusted "
     "Azure services allowed) and the vendor mock (a public Container Apps environment).",
     "Blast radius: Storage, Cosmos and Search have no public path, and the five internal MCP servers are reachable "
     "only from the VNet. The vendor mock is public and protected by one static key.",
     "Closed: APIM refuses a call with no valid token or key. The vendor mock refuses a wrong key (401 "
     "invalid_vendor_key). Key Vault refuses other networks.",
     "Soft spot: the Foundry endpoint and the Container Registry stay public (Entra-only). The vendor key is a "
     "static secret."),
    ("Operator and control plane", "human",
     "Role: the operator holds control-plane roles and the same data app roles as Wes and Tara. The kill-switch and "
     "allow-list scripts write APIM named values; Reset demo also writes group membership and the operator's roles "
     "in Entra.",
     "Blast radius: the operator can change the kill switch, the allow-list, the front-door limits and their own "
     "roles. The Demo Console listens on 127.0.0.1 only; the jump box has no public IP.",
     "Closed: the Demo Console refuses cross-origin POSTs and other host names. No token, password or TOTP seed "
     "reaches the browser.",
     "Soft spot: each persona's refresh token is cached in .secrets on the operator's machine. The jump box gets "
     "one only with -IncludePersonaFiles."),
    ("Governance", "policy",
     "Role: Azure Policy initiative abw-agent-platform-controls (no keys, private networking, approved tools and "
     "models, guardrails, hygiene) and a budget with alerts at 50, 80 and 100 % actual and 100 % forecast.",
     "Blast radius: exemptions mark the deliberate gaps: six in all, and the legacy keyed connection has a "
     "time-boxed waiver.",
     "Closed: Deny stops a keyed Foundry connection, and an MCP target outside the four APIM paths and the private "
     "server, when it is created.",
     "Soft spot: the budget is an alert, not a cap. The Foundry data-plane policies are preview and report "
     "compliance only."),
    ("Observability and audit", "obs",
     "Role: container logs and App Insights feed Log Analytics (AbwMcpAudit, AbwGateway, AbwFullChain). Five MCP "
     "servers also append JSON lines to a WORM audit blob. Sentinel rules and a workbook sit on top.",
     "Blast radius: the logs hold user ids, tool names and a SHA-256 of the arguments, never the arguments "
     "themselves.",
     "Closed: nothing here refuses a call; logs and alerts only record and notify.",
     "Soft spot: logs arrive 2-18 min late. The audit blob is best-effort and unlocked (1-day immutability, a demo "
     "pattern). Sentinel receives no Entra sign-in data in this build."),
]

TABLE_COLS = [("Failure", 300), ("What you see", 560), ("Where to look", 600), ("Fix or wait", 820)]
TABLE_ROWS = [
    (("Stale OAuth consent: a role-less token held by Foundry", "identity"),
     "The agent shows (none) for the wall, actions or private tools (or 403 on vendor) long after the roles were "
     "fixed. Foundry keeps the token 60-90 min and the tool list about 15-20 min.",
     "The tool list the agent run reports ([tools/list] wall: (none)). A consent link lives about 10 min and must be "
     "opened signed in as that persona.",
     "Apply the persona role baseline first. Then delete the connection through ARM, run foundry-connections.ps1 "
     "-Only <name>, consent again and republish with create_agents.py --rai abw-agent-guardrails. A redirect-URI "
     "mismatch needs foundry-connections.ps1 -Force."),
    (("APIM 401", "network"),
     "401 with {error: unauthorized, server, reason} and a WWW-Authenticate resource_metadata header.",
     "The reason in the response body. KQL AbwGateway lists the call as Outcome unauthenticated: a 401 never "
     "reaches the policy trace.",
     "Right after abw-kill or abw-allow the old token no longer matches the gateway: wait about 50 s, request a new "
     "token (abw-gw does), then run abw-kill -Reset and abw-allow -Reset."),
    (("MCP cold start", "compute"),
     "The first call after idle takes 10-20 s.",
     "The Container Apps replica count: it should stay at the minimum of 1.",
     "Run abw-warm before the demo (30-60 s; it warms the gateway, every MCP replica and Foundry). Keep minimum "
     "replicas at 1."),
    (("OBO failure", "identity"),
     "The tool answers FORBIDDEN obo_failed:<code>.",
     "KQL AbwMcpAudit (event tool_denied, reason obo_failed:<code>). The UAMI and its federated credential on the "
     "API app.",
     "Fix what the code names. Federated credentials come from Setup-Entra.ps1 phase 2; consent to the data "
     "resources comes from phase 1."),
    (("Guardrail false negative", "deny"),
     "The red-team run just completes: the guardrail did not intervene.",
     "Expected: the guardrail is a preview, best-effort control. When it does fire, KQL AbwDenials shows Layer "
     "0-agent-guardrail and Sentinel raises ABW-008.",
     "Ask again, or show the stored blocked trace and the ABW-008 incident. Never present it as deterministic; "
     "the wall is the control."),
    (("Stale console data", "compute"),
     "An Act 6 board says it is no longer in memory, or a watchtower row says Waiting.",
     "Boards live in the console's memory only: a restart, or newer runs, push them out. Or the log has not arrived "
     "yet. The probe cache lasts 120 s.",
     "Run the scenario again. Press Refresh from logs 15-20 min after the click (Entra's own sign-in log can take "
     "that long)."),
    (("429 after a burst", "network"),
     "HTTP 429 right after the burst beat.",
     "The limit is 120 calls per 60 s per user. KQL AbwGateway lists the call as Outcome rate_limited.",
     "Wait 60 s."),
    (("Front-door limit hit", "network"),
     "An agent beat is refused with 403 token_quota_exceeded or 429 rate_limited.",
     "The Agent entry light says not the baseline. A limit lowered by Act 7 beat 7.4 is still in force, or the rate "
     "limiter's lock-out (about 2 min) is still counting down.",
     "Reset demo puts both settings back (APIM named values abw-agent-token-quota and abw-agent-rpm) and waits "
     "until the front door forwards."),
    (("Chain query is empty or late", "obs"),
     "abw-chain returns 0 rows or only the gateway row. A Sentinel incident has not appeared.",
     "Ingestion lag of 5-10 min (the MCP-server row of a denial can take longer), or the wrong request id. Sentinel "
     "incidents appear up to about 8 min after the event (about 13 for ABW-007).",
     "Wait, then run it again. For abw-chain -Allowed, first run abw-ask op falcon and wait about 10 min."),
    (("Jump box will not connect", "human"),
     "Connect > Bastion in the portal will not connect.",
     "The VM stops itself at 03:00 Central, so it may be deallocated. Or another Bastion Developer session is open "
     "(one at a time).",
     "Run Start-JumpBox.bat (about 1 min), close the other session and retry. jumpbox.ps1 -Status shows the "
     "state."),
]

BULLETS = [
    "A failure at one wall does not open the next: each wall decides again on its own. The data plane checks the "
    "user's own token, so a compromised server reaches no more than the person could, apart from what its UAMI holds.",
    "The soft spots are time and preview effects: the guardrail, the 45-90 s kill switch, token lifetime, log lag and "
    "the unlocked audit store. The private MCP server sits outside the gateway kill switch and rate limit.",
    "Read the table from the symptom. Every row names the log or the portal page that explains it.",
]
FLOW = [
    "Callers hold Entra tokens: T1 for Foundry, T2a for an MCP API.",
    "Entra signs them and decides the roles inside.",
    "Foundry (Wall 0) offers only allowed_tools, holds the user's T2b and screens the turn.",
    "APIM (Wall 1) validates T2a or T2b, the role, the client and the rate.",
    "The MCP server (Wall 2) re-verifies it and swaps it (OBO, with its T3 assertion) for the user's T4a/b/c.",
    "The data plane (Wall 3) checks its own roles on T4a/b/c.",
]


def need(text: str, w: float, size: float = 16, pad: float = 12) -> float:
    return th(wrap(text, size, w - 2 * pad), size) + 20


def solid(kind: str) -> dict:
    k = KINDS[kind]
    return dict(fill=k["tab"], stroke=k["tab"], color=k["tabtext"])


def card(sc: Scene, x: float, y: float, w: float, text: str, kind: str, h: float, **kw):
    return sc.box(x, y, w, text, h=h, kind=kind, size=16, align="left", inset=10, **kw)


def closed_chip(sc: Scene, x: float, y: float, w: float, text: str, h: float):
    return sc.box(x, y, w, text, h=h, kind="deny", size=16, align="left", inset=10, role="chip", dashed=False, **solid("deny"))


def soft_chip(sc: Scene, x: float, y: float, w: float, text: str, h: float):
    return sc.box(x, y, w, text, h=h, kind="deny", size=16, align="left", inset=10, role="chip", dashed=True,
                  fill=WHITE, stroke=KINDS["deny"]["stroke"], color=RED_TEXT)


def columns(sc: Scene, y0: float, items: list, w: float, gap: float, x0: float = 60):
    """One zone per boundary; every zone gets the same four rows so the grid lines up across columns."""
    cw = w - 30
    hs = [max(need(it[2 + k], cw) for it in items) for k in range(4)]
    zs = [sc.zone(x0 + i * (w + gap), y0, w, 100, it[0], kind=it[1]) for i, it in enumerate(items)]
    ys = [zs[0].content_y]
    for h in hs[:-1]:
        ys.append(ys[-1] + h + 12)
    bottom = ys[-1] + hs[-1] + 16
    for z in zs:
        z.el["height"] = bottom - y0
    for z, it in zip(zs, items):
        x = z.x + 15
        card(sc, x, ys[0], cw, it[2], it[1], hs[0])
        card(sc, x, ys[1], cw, it[3], it[1], hs[1], tone="zone")
        closed_chip(sc, x, ys[2], cw, it[4], hs[2])
        soft_chip(sc, x, ys[3], cw, it[5], hs[3])
    return zs, bottom


def build() -> Scene:
    sc = Scene("13-trust-boundaries-and-failure-modes", 2400, 2800, TITLE, SUBTITLE)

    # key for the two chip styles
    sc.box(60, 122, 104, "Closed", h=40, kind="deny", size=16, pad=4, role="chip", dashed=False, **solid("deny"))
    sc.text(178, 132, KEY_CLOSED, size=16, color=MUTED)
    sc.box(400, 122, 124, "Soft spot", h=40, kind="deny", size=16, pad=4, role="chip", dashed=True, fill=WHITE,
           stroke=KINDS["deny"]["stroke"], color=RED_TEXT)
    sc.text(538, 132, KEY_SOFT, size=16, color=MUTED)

    # the request path, with one station per boundary
    sc.text(60, 176, PATH_NOTE, size=16, color=INK)
    path_y = 232
    zs, bottom = columns(sc, 268, PATH, 330, 60)
    ms = [sc.marker(i + 1, z.cx, path_y, r=15) for i, z in enumerate(zs)]
    sc.arrow(None, ms[0], a_at=(60, path_y), b_at="l")
    for a, b in zip(ms, ms[1:]):
        sc.arrow(a, b, a_at="r", b_at="l")
    sc.arrow(ms[-1], None, a_at="r", b_at=(2340, path_y))

    # the planes around the path
    sc.text(60, bottom + 24, HEAD_BAND, size=20, color=INK)
    _, band_bottom = columns(sc, bottom + 64, PLANES, 547, (2280 - 4 * 547) / 3)

    # failure -> symptom -> where to look
    sc.text(60, band_bottom + 24, HEAD_TABLE, size=20, color=INK)
    tb = sc.table(60, band_bottom + 64, TABLE_COLS, TABLE_ROWS, size=16, head_kind="actor")

    fb = sc.footer(tb["bottom"] + 40, BULLETS, flow=FLOW, callout_w=860, flow_title="The boundaries, in order (numbers on the path)")
    sc.fit(fb)
    return sc
