"""Diagram 03 - request data flow: one governed tools/call across six swim lanes, with denial exits and log fan-out."""
from __future__ import annotations

from excal import Scene


def build() -> Scene:
    sc = Scene("03-request-data-flow", 2400, 2200, "Request data flow: one governed tool call",
               "Wes asks for a Falcon deal memo; what travels on each hop, which wall can stop it, what gets logged")

    LW, LG = 350, 36                      # lane (zone) width and gap
    LX = [60 + i * (LW + LG) for i in range(6)]
    CW = LW - 40                          # card width
    CX = [x + 20 for x in LX]
    top0 = 190

    lanes = [("User", "actor"), ("Foundry agent - Wall 0", "compute"), ("APIM gateway - Wall 1", "network"),
             ("MCP server - Wall 2", "compute"), ("Entra ID (OBO)", "identity"), ("Data plane - Wall 3", "data")]

    # ------------------------------------------------------------------ forward cards (staircase)
    STEP = 150
    s1y = top0 + 80
    S1 = sc.panel(CX[0], s1y, CW, "Ask", "Wes (IB Associate) asks the agent for the Falcon deal memo FALCON-001.", kind="actor")
    S2 = sc.panel(CX[1], s1y + STEP, CW, "Pick the tool",
                  "Wall 0: the guardrail screens the prompt (detective, preview, probabilistic). The model picks wall.get_deal_document; "
                  "the agent's allowed_tools list permits it.", kind="compute")
    S3 = sc.panel(CX[2], s1y + 2 * STEP, CW, "Check the call",
                  "validate-jwt: audience, tenant. abw-deny: kill switch, client allow-list, scope, role. "
                  "Rate limit: 120 calls per minute per user. Adds x-abw-request-id.", kind="network")
    S4 = sc.panel(CX[3], s1y + 3 * STEP, CW, "Re-check, then act",
                  "Verifies the token again: signature (JWKS), audience, issuer, tenant, allowed client, scope Tools.Read. "
                  "The role must allow the tool and the project (falcon) must be in the token's roles. "
                  "Swaps T2 for a Storage token (hop 4), then reads the blob (hop 5).", kind="compute")
    S5 = sc.panel(CX[4], S4.top, CW, "Exchange the token",
                  "Checks the managed identity's federated credential and the pre-granted consent, then issues T4 for Wes: "
                  "oid = Wes, audience Storage.", kind="identity")

    # hop 5 leaves the lower part of S4; the data card sits level with it
    hop5_y = round(S4.bottom + 40)
    S4.el["height"] = hop5_y + 40 - S4.top
    S6 = sc.panel(CX[5], hop5_y - 40, CW, "Check Azure RBAC",
                  "Evaluates Wes himself: sg-abw-wall-falcon holds Storage Blob Data Reader on wall-falcon. "
                  "No other identity is involved.", kind="data")

    # ------------------------------------------------------------------ denial exits (above each card)
    def deny_above(card, text, gap=46):
        probe = sc.box(card.left, 0, card.w, text, kind="deny", size=16)
        need = probe.h
        probe.el["y"] = card.top - gap - need
        for c in probe.children:
            c.el["y"] = probe.el["y"] + (need - c.h) / 2
        return probe

    D1 = deny_above(S2, "Denied at Wall 0: the guardrail stops the run. The span carries error.type = content_filter (Sentinel ABW-008).")
    D2 = deny_above(S3, "Denied at Wall 1: 401 unauthorized (a fixed message, no reason code); 403 forbidden (revoked, client_not_allowed, missing_scope, "
                        "missing_role); 429 rate limited. Sentinel ABW-004, 005, 009.")
    D3 = deny_above(S4, "Denied at Wall 2: 401 (bad token) or 403 (missing scope); or HTTP 200 with decision DENIED "
                        "(missing_role, project_not_in_token_roles). Logged as auth_failed, tool_denied or wall_violation_attempt; "
                        "Sentinel ABW-001 fires on the last.")
    D4 = deny_above(S5, "OBO refused: the MCP server answers FORBIDDEN obo_failed:<code>.")
    D5 = deny_above(S6, "Denied at Wall 3: Storage answers 403; the MCP server reports storage_rbac_denied. Sentinel ABW-007.")

    # ------------------------------------------------------------------ left-lane context cards
    who = sc.panel(CX[0], S1.bottom + 40, CW, "Who is calling",
                   "Wes, persona abw.wes@<tenant-domain>. App roles: Research.Read, Wall.Falcon, MarketData.Read. "
                   "Groups: sg-abw-demo-all, sg-abw-research, sg-abw-wall-falcon.", kind="actor")
    toks = sc.panel(CX[0], who.bottom + 30, CW, "Tokens in this flow",
                    "T1: Entra token for Foundry (audience https://ai.azure.com).\n"
                    "T2: Entra token for the wall MCP API (audience = the API app, scope Tools.Read, app roles).\n"
                    "T3: managed identity token (audience api://AzureADTokenExchange).\n"
                    "T4: Entra token for Storage (audience https://storage.azure.com, oid = Wes).", kind="identity")

    # ------------------------------------------------------------------ return row
    yr = round(max(S6.bottom, toks.bottom) + 70)
    R2 = sc.panel(CX[2], yr, CW, "Relay", "Passes the result back and logs status and latency.", kind="network")
    R1 = sc.panel(CX[1], yr, CW, "Record and answer",
                  "The execute_tool span stores the result and the request_id; the model writes the reply.", kind="compute")
    R0 = sc.panel(CX[0], yr, CW, "Read", "Wes reads the summary of FALCON-001.", kind="actor")
    rh = max(R0.h, R1.h, R2.h)
    for r in (R0, R1, R2):
        r.el["height"] = rh
    AUD = sc.box(CX[5], yr, CW, "Storage worm-audit: append blob, one JSON line per event, written by the MCP server's managed identity "
                 "(async, best effort)", kind="data", size=16, h=rh + 40)
    ret_bottom = max(AUD.bottom, R2.bottom)

    # ------------------------------------------------------------------ log row
    ly = round(ret_bottom + 60)
    logs = [
        (0, "Entra SigninLogs: Wes's interactive sign-in (MFA, Conditional Access). Join key: session id. Separate export workspace.", "obs", True),
        (1, "Application Insights spans: invoke_agent, execute_tool, chat. Join key: trace id.", "obs", False),
        (2, "ApiManagementGatewayLogs plus the abw-gateway trace. Join key: RequestId = x-abw-request-id.", "obs", False),
        (3, "Console stdout JSON (AbwMcpAudit): request_id, jti, trace_id, decision, downstream.", "obs", False),
        (4, "Entra non-interactive sign-in log: the row that issued T2 (join key: token id = the MCP jti). Separate workspace.", "obs", True),
        (5, "StorageBlobLogs. Join key: ClientRequestId = request_id. Search and Cosmos are matched by time.", "obs", False),
    ]
    chips = []
    for i, text, k, sep in logs:
        chips.append(sc.box(CX[i], ly, CW, text, kind=k, size=16, dashed=sep))
    ch = max(c.h for c in chips)
    sc.fill_to(chips, ly + ch)

    lane_bottom = ly + ch + 20
    zones = []
    for (title, kind), x in zip(lanes, LX):
        zones.append(sc.zone(x, top0, LW, lane_bottom - top0, title, kind=kind))

    la = sc.box(60, lane_bottom + 70, 2280, "Log Analytics workspace: the KQL function AbwFullChain(<any id>) joins these rows into one chain. "
                "The Entra sign-in tables (dashed) sit in a separate export workspace and are read cross-workspace.",
                kind="obs", size=18, h=70)
    for i, c in enumerate(chips):
        sc.arrow(c, la, a_at=f"b@{c.cx}", b_at=f"t@{c.cx}", kind="obs", dashed=logs[i][3])

    # ------------------------------------------------------------------ forward arrows
    def zhop(a, b, step, ay, by, **kw):
        xm = (a.right + b.left) / 2
        return sc.arrow(a, b, a_at=f"r@{ay}", b_at=f"l@{by}", via=[(xm, ay), (xm, by)], step=step, **kw)

    zhop(S1, S2, 1, S1.top + 40, S2.top + 40)
    zhop(S2, S3, 2, S2.top + 40, S3.top + 40)
    zhop(S3, S4, 3, S3.top + 40, S4.top + 40)
    sc.arrow(S4, S5, a_at=f"r@{S4.top + 70}", b_at=f"l@{S5.top + 70}", step=4, both=True)
    sc.arrow(S4, S6, a_at=f"r@{hop5_y}", b_at=f"l@{hop5_y}", step=5, both=True)
    # return path: MCP -> APIM -> Foundry -> user
    xm = (S3.right + S4.left) / 2
    sc.arrow(S4, R2, a_at=f"l@{S4.bottom - 20}", b_at=f"r@{R2.cy}", via=[(xm, S4.bottom - 20), (xm, R2.cy)], step=6)
    sc.arrow(R2, R1, a_at="l", b_at="r", step=7)
    sc.arrow(R1, R0, a_at="l", b_at="r", step=8)
    # audit line to the immutable blob
    sc.arrow(S4, AUD, a_at=f"b@{S4.cx + 60}", b_at=f"l@{AUD.cy}", via=[(S4.cx + 60, AUD.cy)], dashed=True, kind="data",
             label="audit line, async", label_side="above", label_w=170, label_seg=1, label_at=0.5)
    # denial exits (red, upward)
    for card, d in ((S2, D1), (S3, D2), (S4, D3), (S5, D4), (S6, D5)):
        sc.arrow(card, d, a_at=f"t@{card.cx}", b_at=f"b@{card.cx}", kind="deny")

    fb = sc.footer(la.bottom + 50, [
        "Each wall is a different system with its own deny (red boxes); a denial stops the call and leaves a log row.",
        "The user's own identity reaches the data plane: T2 goes in, T4 comes out, so Azure RBAC decides on Wes, not on the server.",
        "One request id (x-abw-request-id) ties the APIM, MCP and Storage rows; Entra and the guardrail use other ids (diagram 09).",
    ], flow=[
        "Prompt plus Wes's token T1 when sent through the APIM /agents front door (it validates T1; diagram 11).",
        "tools/call get_deal_document {doc_id: FALCON-001} with Authorization: Bearer T2, the user's own token that Foundry holds from the one-time consent.",
        "The same call and T2, unchanged, plus x-abw-request-id and x-abw-gateway: apim.",
        "Request to Entra: grant jwt-bearer, assertion T2, client_assertion T3, scope https://storage.azure.com/user_impersonation. Response: T4.",
        "GET FALCON-001.md in wall-falcon with Authorization: Bearer T4 and x-ms-client-request-id = request_id. Response: the document, or 403.",
        "Tool result with request_id added (a denial is a result too: decision DENIED, reason, request_id).",
        "The result, relayed by APIM, which logs status and latency.",
        "The model's answer to Wes.",
    ], callout_w=860, flow_title="Hops (numbers on the arrows)")
    sc.fit(fb)
    return sc
