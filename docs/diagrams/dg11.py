"""Diagram 11 - agent front door: user -> APIM /agents -> Foundry Responses -> agent -> tools back through APIM, plus the FinOps meters."""
from __future__ import annotations

from excal import INK, KINDS, MUTED, Scene, th, wrap

WHITE = "#ffffff"
Y0 = 270
C1X, C1W = 60, 380      # caller and operator
C2X, C2W = 520, 700     # the /agents front door
C3X, C3W = 1300, 470    # Foundry project and agent
C4X, C4W = 1890, 450    # tool calls back through the same APIM

TITLE = "Agent front door: APIM in front of agent and tools"
SUBTITLE = "Act 7 path: every governed agent call is checked, metered and revocable per user"

# (marker letter, check, refusal chip, chip kind). The order is the order inside agent-frontdoor.policy.xml.
CHECKS = [
    ("a", "validate-jwt: audience https://ai.azure.com, issuer v1 or v2.0 of this tenant, tid required, 60 s skew",
     "401\nunauthorized", "deny"),
    ("b", "Kill switch: the caller's oid is in abw-deny-oids", "403\nrevoked", "deny"),
    ("c", "Call rate: abw-agent-rpm calls per minute per user (default 60)", "429\nrate_limited", "deny"),
    ("d", "Token budget: abw-agent-token-quota per user per hour (default 250000), counted after the response, "
          "so one call can overshoot", "403\ntoken_quota_exceeded", "deny"),
    ("e", "Token meter: tokens by user, upn and agent (namespace abw-agent)", "no refusal\nmetric only", "obs"),
]
FORWARD = ("Forward to the Foundry project endpoint (timeout 240 s). The user's token passes on UNCHANGED; "
           "APIM adds x-abw-request-id.")
NAMED = ("Named values the checks read. An operator changes them with no redeploy; APIM applies a change within seconds "
         "to about a minute.\n"
         "abw-tenant-id: the tenant for the issuer and tid checks\n"
         "abw-deny-oids: the users the kill switch refuses\n"
         "abw-agent-rpm: calls per minute per user, default 60\n"
         "abw-agent-token-quota: tokens per user per hour, default 250000")

CALLER = "Caller: a user's client, or the Demo Console running Act 7 as the operator"
T1 = "T1: the user's Entra token for Foundry (audience https://ai.azure.com), sent as a bearer token"
BEATS = ("Console agent beats enter here by default. Act 7.1 tests the door: no token, a wrong-audience token, a valid token. "
         "Act 7.4 shows the token-budget refusal.")
ANSWER = "Answer, plus the headers x-abw-tokens-consumed, x-abw-tokens-remaining, x-abw-request-id and x-abw-gateway"
OPERATOR = ("Operator in the Demo Console. 7.3 reads Cost Management, the budget and the token meter. 7.4 lowers "
            "abw-agent-token-quota or abw-agent-rpm for about a minute, then restores them (global: demo tenant only).")

RESP = ("Responses endpoint of the Foundry project: authorises the person (Foundry Agent Consumer on the project), "
        "then runs the agent")
AGENT = ("Agent abw-wall-desk (model gpt-54-mini): picks the tools and calls each with the user's own token, T2b. "
         "Approval is required only for place_order.")
GUARD = "Guardrail abw-agent-guardrails (Wall 0): detective, preview, probabilistic"
T2 = "T2b: the user's token for each MCP API, minted for Foundry after the one-time consent and reused until it expires (60-90 min)"
CONSENT = ("First use per person and tool connection: Foundry returns an oauth_consent_request with a link that lives "
           "about 10 min; a person opens it once (diagram 04).")
DIRECT = ("Direct calls skip the front door. The legacy PoC agent is called this way on purpose (the before picture: a "
          "shared key, no user). A valid Entra token also works here because public network access is on; in production "
          "a private endpoint makes APIM the only way in.")

POINTER = "Tool path in detail: diagram 03 (data flow) and diagram 05 (the four walls)."
APIS = ("API Management again: the MCP APIs /research, /wall, /actions and /vendor (Wall 1). validate-jwt, abw-deny, "
        "120 calls per minute per user.")
SERVERS = ("MCP servers on Container Apps (Wall 2): check the token again and the per-tool role rules, then swap T2b for a "
           "data token with the managed identity (OBO).")
DATA = "Data planes (Wall 3): Storage, Cosmos DB and AI Search. Each service's own roles decide on the user's own data token, T4a/b/c."
PRIV = ("mcp-private: reached directly from Foundry over the agent subnet, outside APIM, so outside this kill switch "
        "and rate limit.")

COST = ("Azure Cost Management: ActualCost, month to date, by service, for the resource group. Data arrives hours late; "
        "no dollars in the workbook.")
BUDGET = ("Budget budget-abw-demo-<region>-001: USD 1,200 a month by default. Mails the resource group Owners at 50, 80 "
          "and 100 % actual and 100 % forecast. An alert, not a cap.")
METERS = ("Two meters in the front-door policy.\n"
          "Token meter (llm-emit-token-metric, namespace abw-agent): tokens by user oid, upn and agent.\n"
          "Decision meter and trace (emit-metric abw-gateway-decisions, trace abw-gateway): allow or deny, reason, "
          "user oid, request_id.")
LOGS = ("Log Analytics workspace log-abw-demo-<region>-001. AppMetrics holds the token metric (through Application "
        "Insights); ApiManagementGatewayLogs holds the abw-gateway trace.")
KQL = ("KQL functions. AbwTokenUsage: runs, input, output and total tokens per hour, user and agent. AbwDenials: "
       "refusals, including Control llm-token-limit. AbwGateway: the gateway decisions.")
WORKBOOK = ("Workbook Agent Wall - Cockpit, tab 'Cost & tokens': tokens per user and hour, tokens per agent, refusals at "
            "the front door. Dollars per service live in Cost Management.")

BULLETS = [
    "The caller's own token goes through unchanged: the front door adds control and attribution, it never swaps who is "
    "calling. Foundry still authorises the person and the tools still get the user's identity.",
    "The limits are APIM named values, so an operator can change them in seconds. The token budget counts after the "
    "response, so one call can overshoot it.",
    "The Azure budget is an alert, not a cap. The per-user token budget (check d) is the control that stops a runaway "
    "agent; the private MCP server sits outside this gateway.",
]
FLOW = [
    "The caller sends a Responses API request to APIM /agents with T1.",
    "APIM runs checks a to e in order. The first failure returns the red refusal on its row (a JSON body with a "
    "request_id) and is logged. If all pass, APIM forwards to the Foundry project endpoint with the token unchanged.",
    "Foundry authorises the person, runs the agent and, for a tool, sends the user's own token T2b to the MCP API on the "
    "same APIM.",
    "The tool call crosses Wall 1 (APIM), Wall 2 (MCP server) and Wall 3 (data plane), as in diagrams 03 and 05.",
    "The answer returns through Foundry and APIM; the front door adds the token headers.",
    "The meters flow to Application Insights and Log Analytics; the KQL functions and the workbook tab read them.",
]


def need(text: str, w: float, size: float = 16, pad: float = 12) -> float:
    return th(wrap(text, size, w - 2 * pad), size) + 20


def solid(kind: str) -> dict:
    k = KINDS[kind]
    return dict(fill=k["tab"], stroke=k["tab"], color=k["tabtext"])


def build() -> Scene:
    sc = Scene("11-agent-front-door", 2400, 2000, TITLE, SUBTITLE)

    z1 = sc.zone(C1X, Y0, C1W, 100, "Caller and operator", kind="actor")
    z2 = sc.zone(C2X, Y0, C2W, 100, "API Management: the /agents front door", kind="network")
    z3 = sc.zone(C3X, Y0, C3W, 100, "Foundry project and agent", kind="compute")
    z4 = sc.zone(C4X, Y0, C4W, 100, "Tool calls: same APIM, then MCP and data", kind="compute")
    top = z2.content_y

    # ---------------------------------------------------------------- C2: the five checks, forward, named values
    ix = C2X + 20
    mx, mw = ix + 44, 402
    chx, chw = mx + mw + 12, 202
    sc.text(mx, top, "Check, in order", size=16, color=MUTED)
    sc.text(chx, top, "If it fails", size=16, color=MUTED)
    y = top + 28
    mains = []
    for letter, text, chip_text, chip_kind in CHECKS:
        h = max(60.0, need(text, mw))
        mains.append(sc.box(mx, y, mw, text, h=h, kind="network", size=16, align="left", inset=10))
        sc.box(chx, y, chw, chip_text, h=h, kind=chip_kind, size=16, pad=4, role="chip", dashed=False, **solid(chip_kind))
        sc.marker(letter, ix + 16, y + h / 2, r=15, fill=WHITE, stroke=INK, text_color=INK, sw=2)
        y += h + 40
    for a, b in zip(mains, mains[1:]):
        sc.arrow(a, b, a_at="b", b_at="t")
    fwd_w = chx + chw - mx
    fwd = sc.box(mx, y, fwd_w, FORWARD, h=need(FORWARD, fwd_w), kind="network", size=16, align="left", inset=10)
    sc.arrow(mains[-1], fwd, a_at="b", b_at=f"t@{mains[-1].cx}")

    # ---------------------------------------------------------------- C1: caller, T1, beats, answer, operator
    ux, uw = C1X + 20, C1W - 40
    caller = sc.box(ux, top, uw, CALLER, h=max(60.0, need(CALLER, uw)), kind="actor", size=16, align="left", inset=10)
    t1 = sc.box(ux, caller.bottom + 12, uw, T1, h=need(T1, uw), kind="identity", size=16, align="left", inset=10)
    beats = sc.box(ux, t1.bottom + 40, uw, BEATS, h=need(BEATS, uw), kind="actor", size=16, align="left", inset=10)
    ans_h = need(ANSWER, uw)
    ans = sc.box(ux, fwd.cy - ans_h / 2, uw, ANSWER, h=ans_h, kind="actor", size=16, align="left", inset=10)

    nv_w = C2X + C2W - 20 - ix
    nv_top = fwd.bottom + 40
    bh = max(need(NAMED, nv_w), need(OPERATOR, uw))
    nv = sc.box(ix, nv_top, nv_w, NAMED, h=bh, kind="network", tone="zone", size=16, align="left", inset=10)
    op = sc.box(ux, nv_top, uw, OPERATOR, h=bh, kind="human", size=16, align="left", inset=10)
    assert ans.bottom + 12 <= op.top, "answer box collides with the operator box"
    c2_bottom = nv.bottom + 20

    # ---------------------------------------------------------------- C3: Foundry
    px, pw = C3X + 20, C3W - 40
    resp = sc.box(px, top, pw, RESP, h=need(RESP, pw), kind="compute", size=16, align="left", inset=10)
    agent_h = max(100.0, need(AGENT, pw))
    agent = sc.box(px, resp.bottom + 40, pw, AGENT, h=agent_h, kind="compute", size=16, align="left", inset=10)
    sc.arrow(resp, agent, a_at="b", b_at="t")
    guard = sc.box(px, agent.bottom + 12, pw, GUARD, h=need(GUARD, pw), kind="deny", size=16, align="left", inset=10)
    t2 = sc.box(px, guard.bottom + 12, pw, T2, h=need(T2, pw), kind="identity", size=16, align="left", inset=10)
    consent = sc.box(px, t2.bottom + 40, pw, CONSENT, h=need(CONSENT, pw), kind="human", size=16, align="left", inset=10)
    direct_h = need(DIRECT, pw)

    # ---------------------------------------------------------------- C4: the governed chain and the private server
    qx, qw = C4X + 20, C4W - 40
    sc.text(qx, top, POINTER, size=16, color=MUTED, w=qw)
    apis_h = max(100.0, need(APIS, qw))
    apis = sc.box(qx, agent.cy - apis_h / 2, qw, APIS, h=apis_h, kind="network", size=16, align="left", inset=10)
    servers = sc.box(qx, apis.bottom + 80, qw, SERVERS, h=need(SERVERS, qw), kind="compute", size=16, align="left", inset=10)
    data = sc.box(qx, servers.bottom + 80, qw, DATA, h=need(DATA, qw), kind="data", size=16, align="left", inset=10)
    priv_h = need(PRIV, qw)

    row1_bottom = max(c2_bottom, consent.bottom + 40 + direct_h + 20, data.bottom + 40 + priv_h + 20)
    direct = sc.box(px, row1_bottom - 20 - direct_h, pw, DIRECT, h=direct_h, kind="deny", tone="zone", size=16, align="left",
                    inset=10, dashed=False)
    priv = sc.box(qx, row1_bottom - 20 - priv_h, qw, PRIV, h=priv_h, kind="compute", size=16, align="left", inset=10)
    for z in (z1, z2, z3, z4):
        z.el["height"] = row1_bottom - Y0

    # ---------------------------------------------------------------- the numbered flow
    sc.arrow(caller, z2, a_at="r", b_at=f"l@{caller.cy}", step=1, label="T1", label_side="below")
    via2 = [(C2X + C2W + 40, fwd.cy), (C2X + C2W + 40, resp.cy)]
    sc.arrow(fwd, resp, a_at="r", b_at="l", via=via2, step=2)
    assert abs(apis.cy - agent.cy) < 0.01
    sc.arrow(agent, apis, a_at="r", b_at="l", step=3, label="T2b", label_side="above")
    sc.arrow(apis, servers, a_at="b", b_at="t", step=4, marker_at=0.3, label="T2b: the user's token", label_side="right",
             label_dx=10, label_w=200)
    sc.arrow(servers, data, a_at="b", b_at="t", label="T4a/b/c: OBO data token", label_side="right", label_w=240)
    sc.arrow(z2, ans, a_at=f"l@{ans.cy}", b_at="r", step=5)
    sc.arrow(op, nv, a_at="r", b_at="l", kind="human", dashed=True)

    # the two ways around the gateway (red dashed)
    chan = (C3X + C3W + C4X) / 2
    sc.arrow(agent, priv, a_at=f"r@{agent.bottom - 18}", b_at="l", kind="deny", dashed=True,
             via=[(chan, agent.bottom - 18), (chan, priv.cy)], label="direct, not via APIM", label_inline=True,
             label_w=100)
    land = px + pw - 60
    sc.arrow(z1, resp, a_at="t@400", b_at=f"t@{land}", kind="deny", dashed=True, via=[(400, 222), (land, 222)],
             label="Direct to Foundry, around the front door", label_side="above", label_w=460)

    # ---------------------------------------------------------------- band 2: money (left) and tokens (right)
    band_y = row1_bottom + 80
    mz = sc.zone(C1X, band_y, 440, 100, "Money: Azure cost and budget", kind="policy")
    tz = sc.zone(540, band_y, 1800, 100, "Tokens: from meter to workbook", kind="obs")

    bx, bw = C1X + 20, 400
    cost = sc.box(bx, mz.content_y, bw, COST, h=need(COST, bw), kind="policy", size=16, align="left", inset=10)
    budget = sc.box(bx, cost.bottom + 12, bw, BUDGET, h=need(BUDGET, bw), kind="policy", size=16, align="left", inset=10)

    stages = [(METERS, 440, "obs"), (LOGS, 360, "obs"), (KQL, 440, "obs"), (WORKBOOK, 360, "obs")]
    px0, pend = 560, 2320
    pgap = (pend - px0 - sum(s[1] for s in stages)) / (len(stages) - 1)
    ph = max(need(t, w) for t, w, _ in stages)
    pipe = []
    cx = px0
    for text, w, kind in stages:
        pipe.append(sc.box(cx, tz.content_y, w, text, h=ph, kind=kind, size=16, align="left", inset=10))
        cx += w + pgap
    for a, b in zip(pipe, pipe[1:]):
        sc.arrow(a, b, a_at="r", b_at="l")

    band_bottom = max(budget.bottom, pipe[0].bottom) + 20
    sc.fill_to(pipe, band_bottom - 20)
    sc.fill_to([budget], band_bottom - 20)
    for z in (mz, tz):
        z.el["height"] = band_bottom - band_y

    sc.arrow(z2, pipe[0], a_at=f"b@{pipe[0].left + 390}", b_at=f"t@{pipe[0].left + 390}", step=6, marker_at=0.3)
    sc.arrow(op, cost, a_at="b@400", b_at="t@400", kind="human", dashed=True)

    fb = sc.footer(band_bottom + 40, BULLETS, flow=FLOW, callout_w=860, flow_title="Main flow (numbers on the arrows)")
    sc.fit(fb)
    return sc
