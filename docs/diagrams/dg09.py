"""Diagram 09 - observability and correlation: each layer's log source and join key, the KQL functions and their readers."""
from __future__ import annotations

from excal import KINDS, MUTED, RED_TEXT, Scene, th, wrap

X_STEP, W_STEP = 60, 100
X_LAYER, W_LAYER = 172, 210
X_SRC, W_SRC = 422, 350
X_KEY, W_KEY = 812, 380
X_BUS, W_BUS = 1262, 170
X_FN, W_FN = 1502, 440
X_CON, W_CON = 2000, 340
Y0, ROW_GAP = 190, 12
HEAD_FILL = "#343a40"

# (step chip, layer, layer kind, where it logs, join key, exception to the request-id join)
ROWS = [
    ("Step 0", "Entra ID: sign-in and token issue", "identity",
     "SigninLogs and AADNonInteractiveUserSignInLogs, in the tenant's existing Entra export workspace.",
     "Token id (uti, the same value as the MCP audit jti) and SessionId. A sign-in can be days older than the call.",
     True),
    ("Step 1", "APIM agent front door (/agents)", "network",
     "ApiManagementGatewayLogs (abw-agent-frontdoor) and App Insights AppRequests.",
     "RequestId = x-abw-request-id. AppRequests maps it to the W3C trace id.",
     False),
    ("Step 3", "Foundry guardrail", "compute",
     "AppDependencies, the invoke_agent span: content_filter.results (blocked, flagged categories).",
     "Trace id (OperationId) only. There is no request_id on this row.",
     True),
    ("Steps 4-5", "Foundry agent and model", "compute",
     "AppDependencies: invoke_agent (user.id) and chat spans (tokens in, out, cached).",
     "Trace id (OperationId).",
     False),
    ("Step 6", "Foundry tool call", "compute",
     "AppDependencies: execute_tool spans. The tool result carries the MCP request_id.",
     "Trace id, plus the request_id echoed in the tool result: the bridge from the trace to every request id.",
     False),
    ("Steps 7, 10", "APIM gateway (MCP APIs)", "network",
     "ApiManagementGatewayLogs, ApiManagementGatewayMCPLog (method, tool) and the abw-gateway decision trace.",
     "RequestId = x-abw-request-id = the MCP audit request_id. Policy errors (AppExceptions) join on the trace id.",
     False),
    ("Steps 2, 8", "MCP server (Container App)", "compute",
     "ContainerAppConsoleLogs (AbwMcpAudit) and App Insights abw.audit. Also an append blob in worm-audit, best-effort.",
     "request_id, jti (the token id) and trace_id.",
     False),
    ("Step 8", "Private MCP server (direct)", "compute",
     "The same audit trail: ContainerAppConsoleLogs and App Insights.",
     "request_id and trace_id from the audit event and the tool result. No APIM row: Foundry calls it direct.",
     True),
    ("Step 9", "Storage (blob)", "data",
     "StorageBlobLogs: caller (RequesterUpn, ObjectId), AuthenticationType, status.",
     "ClientRequestId = request_id, an exact join. The MCP server stamps x-ms-client-request-id.",
     False),
    ("Step 9", "AI Search and Cosmos DB", "data",
     "AzureDiagnostics (Search, Query.*) and CDBDataPlaneRequests (database abw).",
     "No request id and no caller in these logs: matched by time, from the APIM start to start plus total time.",
     True),
    ("Steps 11-12", "Microsoft Sentinel", "obs",
     "SecurityAlert and SecurityIncident, written by the analytics rules in the same workspace.",
     "Ids inside the alert's ExtendedProperties. Incidents join through AlertIds.",
     False),
]

CHAIN = [
    ("AbwFullChain(anyId, lookback, tokenIds)",
     "One id in, the whole run out, one row per hop (steps 0-12). The id can be a tool-call request_id, a front-door "
     "request id or the 32-hex trace id; it is expanded to every request id and trace id through three maps: APIM, "
     "the MCP audit and the tool-result echo. Optional tokenIds: the uti values a caller sent, for a call the "
     "gateway refused."),
    ("AbwFullChainCore(anyId, lookback)",
     "The same chain without the Entra rows. AbwFullChain is deployed as a copy of it when no Entra workspace is "
     "set, and the console falls back to it if the cross-workspace read fails."),
    ("AbwIdentityChain(requestId)",
     "The narrower chain for one request_id: agent, gateway, MCP server, Storage."),
]

STREAMS = [
    ("AbwMcpAudit", "MCP audit trail, one row per event"),
    ("AbwGateway", "APIM decision and outcome per request"),
    ("AbwDenials", "every refusal across layers 0-3"),
    ("AbwAgentActivity", "which agent called which tool for whom"),
    ("AbwUsageByUser", "calls and denials per user"),
    ("AbwTokenUsage", "model tokens per user and hour"),
    ("AbwZeroKeys", "Storage requests by auth type"),
]

SENTINEL = (
    "ABW-001 Wall violation attempt (High)\n"
    "ABW-002 Restricted order (High)\n"
    "ABW-003 Legacy, no identity (Medium)\n"
    "ABW-004 Client not allowed (High)\n"
    "ABW-005 Revoked principal (High)\n"
    "ABW-006 Repeated denials (Medium)\n"
    "ABW-007 Entitlement drift (High)\n"
    "ABW-008 Guardrail intervention (High)\n"
    "ABW-009 Throttled burst (Low)\n"
    "\n"
    "They read AbwMcpAudit (001-003), AbwGateway (004, 005, 009) and AbwDenials (006-008). Alerts and incidents "
    "return to the workspace as SecurityAlert and SecurityIncident."
)

BULLETS = [
    "Any one id finds the whole run: a tool-call request_id, a front-door request id or the trace id. The request_id "
    "echoed in the Foundry tool result bridges the trace and the request ids.",
    "Four exceptions break the exact join: the guardrail (trace id only), Entra (token id, in its own workspace), "
    "the private server (no APIM row) and Search and Cosmos DB (matched by time).",
    "Sentinel cannot see Entra sign-ins in this build, so a failed sign-in is read from Entra's own log. In "
    "production, switch the Entra ID connector on.",
]

FLOW = [
    "Each layer logs to its own table and carries the join key it has.",
    "Everything lands in one Log Analytics workspace, except Entra's sign-in logs, which stay in their own.",
    "KQL functions join the tables on those keys and expose one chain.",
    "The workbook, Sentinel, the ops alerts and the Demo Console read the functions.",
]


def need(text: str, w: float, size: float = 16, pad: float = 12) -> float:
    return th(wrap(text, size, w - 2 * pad), size) + 20


def solid(kind: str) -> dict:
    k = KINDS[kind]
    return dict(fill=k["tab"], stroke=k["tab"], color=k["tabtext"])


def chip(sc: Scene, x: float, y: float, w: float, h: float, text: str, kind: str):
    """Solid one-line chip: boxes need 40 px, so create then shrink to h."""
    b = sc.box(x, y, w, text, kind=kind, size=16, pad=4, role="chip", **solid(kind))
    sc.fill_to([b], y + h)
    return b


def build() -> Scene:
    sc = Scene("09-observability-correlation", 2400, 1700, "Observability: one request joined across every layer",
               "Each layer logs to its own table; join keys stitch the tables into one chain")

    # ---------------------------------------------------------------- 1: layers, log sources, join keys
    heads = [("Layer (AbwFullChain step)", X_STEP, X_LAYER + W_LAYER - X_STEP), ("Where it logs", X_SRC, W_SRC),
             ("Join key", X_KEY, W_KEY)]
    for title, x, w in heads:
        sc.box(x, Y0, w, title, h=44, size=18, sw=1, role="cell", fill=HEAD_FILL, stroke=HEAD_FILL, color="#ffffff")
    sc.marker(1, X_STEP + 26, Y0 + 22)

    ws_text = "Entra sign-in workspace (read-only)"
    rows = []
    y = Y0 + 44 + 14
    for i, (step, layer, lkind, src, key, exc) in enumerate(ROWS):
        h = max([70.0, need(layer, W_LAYER, pad=10), need(src, W_SRC), need(key, W_KEY)] + ([need(ws_text, W_BUS)] if i == 0 else []))
        stepb = sc.box(X_STEP, y, W_STEP, step, h=h, kind="actor", size=16, pad=4, role="chip", **solid("actor"))
        lay = sc.box(X_LAYER, y, W_LAYER, layer, h=h, kind=lkind, size=16, pad=10)
        sk = "deny" if exc else "obs"
        srcb = sc.box(X_SRC, y, W_SRC, src, h=h, kind=sk, size=16, tone="zone")
        keyb = sc.box(X_KEY, y, W_KEY, key, h=h, kind=sk, size=16)
        sc.arrow(lay, srcb, a_at="r", b_at="l")
        sc.arrow(srcb, keyb, a_at="r", b_at="l")
        rows.append((stepb, lay, srcb, keyb))
        y += h + ROW_GAP
    rows_bottom = y - ROW_GAP

    # ---------------------------------------------------------------- 2: one workspace, Entra stays in its own
    ws = sc.box(X_BUS, rows[0][0].top, W_BUS, ws_text, h=rows[0][0].h, kind="deny", size=16)
    bus_top = rows[1][0].top
    bus_text = ("Log Analytics\nworkspace\nlog-abw-demo-\n<region>-001\n\nApp Insights\ndata lands\nin it too")
    bus = sc.box(X_BUS, bus_top, W_BUS, bus_text, h=rows_bottom - bus_top, kind="obs", size=16, **solid("obs"))
    sc.marker(2, bus.cx, bus_top + 30)
    sc.arrow(rows[0][3], ws, a_at="r", b_at="l", kind="deny", dashed=True)
    for _, _, _, keyb in rows[1:]:
        sc.arrow(keyb, bus, a_at="r", b_at=f"l@{keyb.cy}")

    # ---------------------------------------------------------------- 3: the KQL functions
    fz = sc.zone(X_FN, Y0, W_FN, 100, "KQL functions (ABW Agent Wall)", kind="obs")
    sc.marker(3, X_FN - 35, Y0 + 24)
    cx, cw = X_FN + 16, W_FN - 32
    cy = fz.content_y
    chain_heads = []
    for sig, body in CHAIN:
        head = chip(sc, cx, cy, cw, 34, sig, "obs")
        bh = need(body, cw)
        sc.box(cx, cy + 38, cw, body, h=bh, kind="obs", size=16, tone="zone")
        chain_heads.append(head)
        cy += 38 + bh + 12
    cy += 4
    sc.text(cx, cy, "Single-purpose functions", size=16, color=MUTED)
    cy += 26
    for name, desc in STREAMS:
        lines = wrap(desc, 16, cw - 184)
        rh = max(34.0, th(lines, 16) + 8)
        chip(sc, cx, cy, 176, rh, name, "obs")
        sc.text(cx + 184, cy + (rh - th(lines, 16)) / 2, desc, size=16, w=cw - 184)
        cy += rh + 6
    fz_bottom = cy - 6 + 16

    # ---------------------------------------------------------------- 4: who reads them
    cz = sc.zone(X_CON, Y0, W_CON, 100, "Who reads them", kind="obs")
    sc.marker(4, X_CON - 29, Y0 + 24)
    px, pw = X_CON + 16, W_CON - 32
    py = cz.content_y
    panels = [
        ("Cockpit workbook",
         "Agent Wall - Cockpit, 8 tabs: Overview, Identity chain, Governance, Threats & layers, Gateway & MCP, "
         "Cost & tokens, Zero keys, Changes. The Identity chain tab calls AbwFullChain.", "obs"),
        ("Sentinel rules, every 5 min", SENTINEL, "obs"),
        ("Ops alert rules",
         "3 rules, every 5 min over 15 min: MCP server errors, gateway or backend 5xx, agent run failures. They notify "
         "the action group ag-abw-ops-<region>-001.", "obs"),
        ("Demo Console",
         "The Act 5 KQL pack and the Act 6 boards (Refresh from logs) query this workspace.", "obs"),
        ("Ingestion lag",
         "Log Analytics: 2-18 min after the event.\nSentinel alerts: 5-15 min.\nEntra's own sign-in log: 10-20 min.", "actor"),
    ]
    for title, body, kind in panels:
        p = sc.panel(px, py, pw, title, body, kind=kind, size=16, title_size=18, tone="zone" if kind == "obs" else "fill")
        py = p.bottom + 12
    cz_bottom = py - 12 + 16

    bottom = max(rows_bottom, fz_bottom, cz_bottom)
    for z in (fz, cz):
        z.el["height"] = bottom - z.y
    sc.arrow(bus, fz, a_at=f"r@{(bus_top + rows_bottom) / 2}", b_at=f"l@{(bus_top + rows_bottom) / 2}")
    sc.arrow(ws, chain_heads[0], a_at=f"r@{chain_heads[0].cy}", b_at="l", kind="deny", dashed=True)
    mid = (Y0 + bottom) / 2
    sc.arrow(fz, cz, a_at=f"r@{mid}", b_at=f"l@{mid}")

    sc.text(X_LAYER, rows_bottom + 12, "Red boxes mark the exceptions to the request-id join.", size=16, color=RED_TEXT)

    fy = max(bottom, rows_bottom + 40) + 40
    fb = sc.footer(fy, BULLETS, flow=FLOW, callout_w=1180, flow_w=1070, flow_title="How to read it", flow_cols=1)
    sc.fit(fb)
    return sc
