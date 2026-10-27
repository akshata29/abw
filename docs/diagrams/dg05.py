"""Diagram 05 - authorization layers: the four walls as stacked rows, with the controls that change their answer."""
from __future__ import annotations

from excal import Scene, th, wrap

WX, WW = 60, 230              # wall column
GX = 300                      # first grid column
WIDTHS = [420, 370, 430, 380]
GAP_C = 10
SX, SW = 1990, 350            # side column
ROW_GAP = 80
HEAD_FILL = "#343a40"


def need(text: str, w: float, size: float = 16, pad: float = 12) -> float:
    return th(wrap(text, size, w - 2 * pad), size) + 20


ROWS = [
    dict(
        name="Wall 0: Foundry guardrail (detective)", kind="compute",
        checks="The prompt, the model's output and the tool result, against content-safety classes: jailbreak, indirect "
               "attack (in the prompt and after a tool call), hate, sexual, violence and self-harm at Medium. Protected "
               "material is flagged, not blocked.",
        inputs="The text, and the guardrail's categories and severity thresholds. Not the user's token or roles.",
        deny="The run stops, and the Foundry span carries error.type = content_filter. A preview control that fires on "
             "only some attacks, so the walls below never rely on it.",
        logged="Application Insights spans (invoke_agent, chat). Sentinel ABW-008 when it stops a run. Join key: the "
               "trace id only, no request_id.",
        lever=("Tool allow-list. allowed_tools names the only tools the model may call on each server, and "
               "require_approval is always on for actions.place_order.", "compute"),
    ),
    dict(
        name="Wall 1: APIM gateway", kind="network",
        checks="A valid Entra token for this MCP server: signature, audience, tenant. Then who and what: kill switch, "
               "client allow-list, scope, role. Then volume: 120 calls a minute per user.",
        inputs="Token claims: aud, tid, oid, azp, scp, roles. The named values abw-deny-oids and abw-allowed-azp. A "
               "counter per oid; the JSON-RPC method.",
        deny="401 unauthorized with a fixed message. 403 forbidden with a reason (revoked, client_not_allowed, "
             "missing_scope or missing_role) plus the request_id. 429 when rate limited.",
        logged="ApiManagementGatewayLogs (RequestId), the abw-gateway trace and the abw-gateway-decisions metric. "
               "Sentinel ABW-004, ABW-005, ABW-009.",
        lever=("Kill switch. Put a user's oid in abw-deny-oids and the gateway refuses that person on every gateway API "
               "within 45-90 s. The private MCP server is outside the gateway, so outside the kill switch.", "deny"),
    ),
    dict(
        name="Wall 2: MCP server", kind="compute",
        checks="The token again, because the server does not rely on the gateway: signature, audience, issuer, tenant, "
               "azp, scope. Then the tool: tools/list is filtered by role, and tools/call needs the role and passes the "
               "tool's own rule.",
        inputs="Token claims (roles, scp, azp, oid), the tool arguments, and the rule: the project must be in the "
               "roles, the ticker must not be on the restricted list.",
        deny="401 or 403 with a reason code, or HTTP 200 with decision DENIED: a soft denial the agent reads as a "
             "result. Also NOT_FOUND, INVALID_ARGUMENT and obo_failed.",
        logged="An audit event (tool_denied, auth_failed, wall_violation_attempt, order_blocked): console JSON, "
               "Application Insights and the WORM audit blob. Sentinel ABW-001, ABW-002.",
        lever=("Client allow-list. abw-allowed-azp admits only the agent client, the test client and the Azure CLI "
               "client at the gateway, and the MCP server checks azp again.", "identity"),
    ),
    dict(
        name="Wall 3: data plane", kind="data",
        checks="The data plane's own roles, on the user's own token T4 rather than the server's identity: Azure RBAC "
               "for the blob container and the Search index, Cosmos DB's data-plane roles for the Cosmos DB container.",
        inputs="T4 (oid = the user) and the user's groups: sg-abw-wall-falcon, sg-abw-traders, sg-abw-compliance, "
               "sg-abw-research.",
        deny="403 from the data service. For Storage the MCP server reports storage_rbac_denied.",
        logged="StorageBlobLogs (ClientRequestId). Search and Cosmos DB logs are matched by time. Sentinel ABW-007: "
               "gateway and MCP allowed, storage denied.",
        lever=("Group membership. People get data access only through groups, and the operator holds no data role of "
               "its own. Leave the group and Wall 3 refuses, even while the token still carries the role (the drift "
               "ABW-007 watches).", "identity"),
    ),
]

EXAMPLES = [
    "Stops at Wall 1. Ian has no app roles: the gateway answers 403 missing_role to every tools/call behind it, and "
    "no tool runs.",
    "Stops at Wall 2. Wes asks for an Orion memo: the gateway lets Wall.Falcon through, the MCP server answers "
    "project_not_in_token_roles, and Storage is never touched.",
    "Stops at Wall 3. A user holds the Wall.Falcon role but is not in sg-abw-wall-falcon: the gateway and the MCP "
    "server allow it, Storage answers 403 (Sentinel ABW-007).",
]


def build() -> Scene:
    sc = Scene("05-authorization-layers", 2400, 1700, "Authorization layers: four walls, each with its own deny",
               "What each wall checks, what it decides on, what a denial looks like, where it is logged")
    xs = [GX]
    for w in WIDTHS[:-1]:
        xs.append(xs[-1] + w + GAP_C)
    grid_right = xs[-1] + WIDTHS[-1]

    req = sc.box(WX, 190, grid_right - WX,
                 "The request: the agent's tools/call with the user's own token (T2) and the tool arguments. "
                 "Every governed call meets the four walls in this order (the private MCP server has no Wall 1).",
                 kind="actor", size=18, h=56)

    hy = req.bottom + 16
    for title, x, w in list(zip(["What it checks", "Decision inputs", "Deny shape", "Where the denial is logged"], xs, WIDTHS)) \
            + [("Controls that change the answer", SX, SW)]:
        sc.box(x, hy, w, title, h=44, size=18, sw=1, role="cell", fill=HEAD_FILL, stroke=HEAD_FILL, color="#ffffff")

    y = hy + 44 + 16
    walls = []
    for r in ROWS:
        texts = [r["checks"], r["inputs"], r["deny"], r["logged"]]
        h = max([need(t, w) for t, w in zip(texts, WIDTHS)] + [need(r["lever"][0], SW), 100])
        items = [(texts[0], r["kind"], {"tone": "zone"}), (texts[1], r["kind"], {"tone": "zone"}),
                 (texts[2], "deny"), (texts[3], "obs")]
        cells = sc.row(GX, y, items, widths=WIDTHS, gap=GAP_C, size=16, h=h)
        walls.append(sc.box(WX, y, WW, r["name"], kind=r["kind"], size=20, h=h))
        lever = sc.box(SX, y, SW, r["lever"][0], kind=r["lever"][1], size=16, h=h)
        sc.line([(lever.left, lever.cy), (cells[-1].right, cells[-1].cy)])
        y += h + ROW_GAP

    sc.arrow(req, walls[0], a_at=f"b@{walls[0].cx}", b_at="t", step=1)
    for i in range(3):
        sc.arrow(walls[i], walls[i + 1], a_at="b", b_at="t", step=i + 2)

    data = sc.box(WX, walls[-1].bottom + ROW_GAP, WW, "Data: reached only when all four walls say yes", kind="data",
                  size=18, h=110)
    sc.arrow(walls[-1], data, a_at="b", b_at="t", step=5)
    ew = (2340 - GX - 2 * GAP_C) / 3
    sc.row(GX, data.top, [(t, "deny", {"tone": "zone"}) for t in EXAMPLES], widths=[ew] * 3, gap=GAP_C, size=16, h=110)

    pol = sc.box(WX, data.bottom + 30, 2340 - WX,
                 "Azure Policy (initiative abw-agent-platform-controls) is not a wall: it decides what may exist, not what "
                 "a request may do. Five control families: no keys, private data planes, approved tools and models, "
                 "guardrails attached, hygiene. A custom Deny refuses Foundry connections to MCP targets that are not "
                 "approved.", kind="policy", size=18)

    bottom = sc.footer(pol.bottom + 50, [
        "Each wall is a different system with its own deny, so getting past one still meets the next.",
        "Wall 2 checks the token again instead of trusting the gateway, and Wall 3 decides on the user's own token T4, "
        "never on the server's identity for user data (the restricted-list read and the audit append use it).",
        "Wall 0 is detective and best effort (a preview control). The three identity walls, 1, 2 and 3, make a call safe.",
    ], flow=[
        "Request reaches Wall 0: the Foundry guardrail screens the content.",
        "It passes to Wall 1: the gateway checks token, role, rate and kill switch.",
        "It passes to Wall 2: the MCP server re-checks the token and applies the tool's rule.",
        "It passes to Wall 3: the data plane's own roles answer for the user.",
        "Only when all four walls say yes does the call reach the data.",
    ], callout_w=1100, flow_title="Numbered flow", flow_cols=1)
    sc.fit(bottom)
    return sc
