"""Diagram 06 - identity and entitlements: personas, groups, app roles, data RBAC and the server identities."""
from __future__ import annotations

from excal import MUTED, Scene, th, wrap

LX, LW = 60, 1500             # left block
RX, RW = 1620, 720            # right block
HEAD_FILL = "#343a40"

PERSONAS = [
    ("Priya", "Research Analyst", "demo-all, research", "Research.Read, MarketData.Read"),
    ("Wes", "IB Associate", "demo-all, research, wall-falcon", "Research.Read, Wall.Falcon, MarketData.Read"),
    ("Tara", "Equity Trader", "demo-all, research, traders",
     "Research.Read, Trade.Execute, Positions.Read, MarketData.Read"),
    ("Carla", "Compliance Officer", "demo-all, research, wall-falcon, compliance",
     "Research.Read, Wall.Falcon, Trade.Read, Positions.Read, MarketData.Read"),
    ("Ian", "InfoSec Analyst", "demo-all, infosec", "none"),
]

OK = ("allowed", "compute")
NO1 = ("refused at Wall 1", "deny")
NO2 = ("refused at Wall 2", "deny")
T1_COLS = [("Persona", 150), ("research\nResearch.Read", 192), ("wall: Falcon\nWall.Falcon", 192),
           ("wall: Orion\nWall.Orion", 192), ("actions: read\nTrade.Read or Trade.Execute", 192),
           ("actions: place_order\nTrade.Execute", 192), ("private (direct)\nPositions.Read", 192),
           ("vendor\nMarketData.Read", 192)]
T1_ROWS = [
    ["Priya", OK, NO1, NO1, NO1, NO1, NO2, OK],
    ["Wes", OK, OK, NO2, NO1, NO1, NO2, OK],
    ["Tara", OK, NO1, NO1, OK, ("allowed + approval", "compute"), OK, OK],
    ["Carla", OK, OK, NO2, OK, NO2, OK, OK],
    ["Ian", NO1, NO1, NO1, NO1, NO1, NO2, NO1],
]
TOOLS_KEY = ("Tools. research: search_research, get_research_note. wall: list_my_wall_crossings, search_deal_documents, "
             "get_deal_document. actions: check_restricted_list and list_my_orders (Trade.Read or Trade.Execute), "
             "place_order (Trade.Execute and the Tools.Execute scope; the governed agent also asks a human to approve). "
             "private: get_firm_positions, get_credit_limit. vendor: get_market_quote, get_headlines. The private server "
             "is not behind the gateway, so it is Wall 2 that refuses.")

RD, WR, RW_ = ("read", "data"), ("read, write", "data"), "no role"
T2_COLS = [("Persona", 150), ("research-public blob and Search index\nsg-abw-research", 220),
           ("wall-falcon blob\nsg-abw-wall-falcon", 220), ("wall-orion blob\nno group", 190),
           ("Cosmos DB orders\nsg-abw-traders, sg-abw-compliance", 250),
           ("Cosmos DB positions\nsg-abw-traders, sg-abw-compliance", 250), ("Control plane\nsg-abw-infosec", 214)]
T2_ROWS = [
    ["Priya", RD, RW_, RW_, RW_, RW_, RW_],
    ["Wes", RD, RD, RW_, RW_, RW_, RW_],
    ["Tara", RD, RW_, RW_, WR, RD, RW_],
    ["Carla", RD, RD, RW_, RD, RD, RW_],
    ["Ian", RW_, RW_, RW_, RW_, RW_, ("read-only: RG, logs", "obs")],
]
NOTE2 = ("Cells follow the app roles and tool rules in the code and the group RBAC in the platform template. Priya, Ian "
         "and the operator were run live; Wes, Tara and Carla are designed behaviour until each has signed in once. "
         "The Search role covers the whole index: the public/wall split inside it is a server-side filter in the MCP "
         "server (Wall 2). sg-abw-demo-all holds Foundry Agent Consumer on the project, so every persona can talk to the "
         "agents. The operator holds no data-plane role: Owner is not data access.")

API_APPS = [
    ("abw-mcp-research", "Scope Tools.Read. Role Research.Read. OBO to Storage and Search."),
    ("abw-mcp-wall", "Scope Tools.Read. Roles Wall.Falcon, Wall.Orion. OBO to Storage and Search."),
    ("abw-mcp-actions", "Scopes Tools.Read, Tools.Execute. Roles Trade.Read, Trade.Execute. OBO to Cosmos DB."),
    ("abw-mcp-private", "Scope Tools.Read. Role Positions.Read. OBO to Cosmos DB."),
]
UAMIS = [
    ("research", "AcrPull. Blob Data Contributor on worm-audit (audit append)."),
    ("wall", "AcrPull. Blob Data Contributor on worm-audit (audit append)."),
    ("actions", "AcrPull. Audit append. Reads the restricted list as the service: Cosmos DB data reader on that one "
                "container."),
    ("private", "AcrPull. Blob Data Contributor on worm-audit (audit append)."),
]
VENDOR_API = ("abw-mcp-vendorgw", "Scope Tools.Read. Role MarketData.Read. No OBO: checked at the gateway only.")
VENDOR_UAMI = ("vendor", "AcrPull. Key Vault Secrets User, granted but not used: the vendor app holds its own copy of the "
                         "key as a Container Apps secret.")
LEGACY_UAMI = ("legacy", "Deliberately broad, the typical POC. Read on all of Storage and Search, Cosmos DB data "
                         "contributor on the account, plus audit append and AcrPull.")


def pneed(title: str, body: str, w: float, tsz: float = 18, sz: float = 16, pad: float = 14) -> float:
    tl, bl = wrap(title, tsz, w - 2 * pad), wrap(body, sz, w - 2 * pad)
    return pad + th(tl, tsz) + (8 if tl and bl else 0) + th(bl, sz) + pad


def head_h(cols, size: float = 16) -> float:
    return max(th(wrap(t, size, w - 24), size) for t, w in cols) + 20


def build() -> Scene:
    sc = Scene("06-identity-and-entitlements", 2400, 1700, "Identity and entitlements: who can reach what",
               "Personas, groups and app roles, the five MCP API apps, data RBAC and the server identities")

    # ------------------------------------------------------------------ left block: personas and the two matrices
    sc.text(LX, 190, "Five personas (abw.<persona>@<tenant-domain>): app roles sit on the user, groups carry the data access",
            size=20)
    cw, cg = 288, 15
    cards = []
    for i, (name, job, groups, roles) in enumerate(PERSONAS):
        cards.append(sc.panel(LX + i * (cw + cg), 226, cw, name,
                              f"{job}\nGroups (sg-abw-*): {groups}\nApp roles: {roles}", kind="actor", title_size=20))
    ch = max(c.h for c in cards)
    for c in cards:
        c.el["height"] = ch

    y = 226 + ch + 36
    sc.text(LX, y, "Walls 1 and 2: the app roles in the token decide which tools a person may call", size=20)
    t1 = sc.table(LX, y + 34, T1_COLS, T1_ROWS, size=16, head_kind="identity", head_h=head_h(T1_COLS))
    sc.text(LX, t1["bottom"] + 12, TOOLS_KEY, size=16, color=MUTED, w=LW)
    key_h = th(wrap(TOOLS_KEY, 16, LW), 16)

    y = t1["bottom"] + 12 + key_h + 36
    sc.text(LX, y, "Wall 3: group membership decides what the user's own token can read", size=20)
    t2 = sc.table(LX, y + 34, T2_COLS, T2_ROWS, size=16, head_kind="data", head_h=head_h(T2_COLS))
    sc.text(LX, t2["bottom"] + 12, NOTE2, size=16, color=MUTED, w=LW)
    left_bottom = t2["bottom"] + 12 + th(wrap(NOTE2, 16, LW), 16)

    # ------------------------------------------------------------------ right block: API apps and managed identities
    sc.text(RX, 190, "Server identities: the five API apps and the six managed identities", size=20)
    ax, aw = RX + 20, 320
    ux, uw = RX + RW - 20 - 280, 280
    for title, x, w in (("Entra API app (audience of T2)", ax, aw), ("Server identity (UAMI)", ux, uw)):
        sc.box(x, 226, w, title, h=44, size=18, sw=1, role="cell", fill=HEAD_FILL, stroke=HEAD_FILL, color="#ffffff")

    z1y = 290
    row_h = [max(pneed(a[0], a[1], aw), pneed(f"id-abw-mcp-{u[0]}", u[1], uw)) for a, u in zip(API_APPS, UAMIS)]
    z1h = 64.5 + sum(row_h) + 14 * (len(row_h) - 1) + 20
    z1 = sc.zone(RX, z1y, RW, z1h, "With a federated credential: the server acts for the user (OBO)", kind="identity")
    ry = z1.content_y
    for (an, ab), (un, ub), h in zip(API_APPS, UAMIS, row_h):
        api = sc.panel(ax, ry, aw, an, ab, kind="identity", h=h, title_size=18)
        uami = sc.panel(ux, ry, uw, f"id-abw-mcp-{un}", ub, kind="identity", tone="zone", h=h, title_size=18)
        sc.arrow(uami, api, a_at="l", b_at="r", kind="identity", label="FIC", label_w=60)
        ry += h + 14

    z2y = z1.bottom + 20
    vh = max(pneed(VENDOR_API[0], VENDOR_API[1], aw), pneed(f"id-abw-mcp-{VENDOR_UAMI[0]}", VENDOR_UAMI[1], uw))
    lh = pneed(f"id-abw-mcp-{LEGACY_UAMI[0]}", LEGACY_UAMI[1], uw)
    z2h = 64.5 + vh + 14 + lh + 20
    z2 = sc.zone(RX, z2y, RW, z2h, "No federated credential: nothing in the server acts as the user", kind="human")
    ry = z2.content_y
    sc.panel(ax, ry, aw, VENDOR_API[0], VENDOR_API[1], kind="identity", h=vh, title_size=18)
    sc.panel(ux, ry, uw, f"id-abw-mcp-{VENDOR_UAMI[0]}", VENDOR_UAMI[1], kind="identity", tone="zone", h=vh, title_size=18)
    ry += vh + 14
    sc.text(ax, ry + 4, "The gateway checks the user's token for vendor and injects the vendor key. Legacy is the "
                        "before picture: one broad identity and no user context.", size=16, color=MUTED, w=aw)
    sc.panel(ux, ry, uw, f"id-abw-mcp-{LEGACY_UAMI[0]}", LEGACY_UAMI[1], kind="deny", h=lh, title_size=18)

    fic = sc.box(RX, z2.bottom + 20, RW,
                 "FIC = federated identity credential on the API app. It trusts the UAMI's token (issuer: the tenant's v2.0 "
                 "endpoint, subject: the UAMI's principal, audience api://AzureADTokenExchange), so the server proves "
                 "itself for OBO with no client secret. Names: id-abw-mcp-<server>-<region>-001.",
                 kind="identity", tone="zone", size=16)

    bottom = sc.footer(max(left_bottom, fic.bottom) + 50, [
        "App roles on the user open the gateway and the MCP server (Walls 1 and 2). Group membership opens the data "
        "plane (Wall 3). A person needs both to reach data.",
        "Orion is open to nobody: no persona holds Wall.Orion and no group has a role on wall-orion. Ian has no app role, "
        "so the gateway refuses every tool call he makes.",
        "Each server has its own managed identity and no Entra client secret. Four have a federated credential for OBO; "
        "the legacy identity is broad on purpose.",
    ], callout_w=1500)
    sc.fit(bottom)
    return sc
