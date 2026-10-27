"""Diagram 07 - token anatomy: one card per token or secret, plus a strip showing where T1-T4 travel."""
from __future__ import annotations

from excal import KINDS, Scene, th, wrap

CW, CG = 740, 30
XS = [60 + i * (CW + CG) for i in range(3)]
PAD, LABEL_W, ROW_GAP, HEAD_H = 16, 116, 10, 44
LABELS = ["Issuer", "Audience", "Key claims", "Lifetime", "Held by", "Validated by"]

CARDS = {
    "t1": ("T1  User token for Foundry and the front door", "identity", [
        "Entra ID, the tenant's endpoint. The front door accepts the v1 (sts.windows.net) and the v2.0 issuer.",
        "https://ai.azure.com, the Foundry data plane.",
        "tid, oid (the user), upn or preferred_username, exp. The kill switch, rate limit and token budget are keyed on oid.",
        "Entra default, typically 60-90 min.",
        "The caller: the operator's Azure CLI cache, or a persona's device-code cache. The front door forwards it "
        "unchanged.",
        "APIM /agents (signature, issuer, audience, tid, expiry), then Foundry (Entra only, local keys are off).",
    ]),
    "t2": ("T2  User token for one MCP API", "identity", [
        "Entra ID, the tenant's v2.0 endpoint.",
        "One MCP API app (api://<app-id>). A token for one server is refused by the others.",
        "ver 2.0, tid, oid, preferred_username, azp (an allowed client), scp Tools.Read (and Tools.Execute for "
        "actions), roles (the app roles), uti (logged as jti).",
        "Entra default, typically 60-90 min. Foundry reuses it until it expires, so a role change reaches the agent "
        "only then.",
        "Foundry, after the user's one-time consent for that connection.",
        "APIM (signature, audience, tenant, deny list, client, scope, role), then the MCP server again. The private "
        "server has no gateway in front.",
    ]),
    "t3": ("T3  Managed identity assertion (UAMI)", "identity", [
        "Entra ID, the tenant's v2.0 endpoint, for the server's managed identity.",
        "api://AzureADTokenExchange",
        "sub = the UAMI's principal id. It is not a token for any API: it is the client assertion that replaces a "
        "client secret.",
        "Set by the platform; the managed identity back end caches it about 24 h and it cannot be force-refreshed.",
        "The MCP server, from its managed identity endpoint. No secret is stored.",
        "Entra, against the federated credential on the API app: issuer, subject and audience must match. Exists for "
        "research, wall, actions and private only.",
    ]),
    "t4": ("T4  OBO data token (Storage, Cosmos DB, Search)", "identity", [
        "Entra ID, through the on-behalf-of (OBO) exchange of T2, authenticated by T3.",
        "One data service: Storage, Cosmos DB or Search (scope user_impersonation).",
        "oid = the user, azp = the MCP API app, scp user_impersonation. The data plane resolves the user's group role "
        "assignments.",
        "Entra default, typically 60-90 min. MSAL keeps it in the server's memory.",
        "The MCP server, in memory only. The audit event carries the request id, never the token.",
        "The data service: its own roles, on the user's own identity (Wall 3).",
    ]),
    "persona": ("Persona sign-in token (device code)", "identity", [
        "Entra ID, the tenant's v2.0 endpoint.",
        "One MCP API app, requested as api://<app-id>/Tools.Read.",
        "Same shape as T2, with azp = abw-test-client (a public client). Roles and groups come from the persona.",
        "Access token: Entra default. The refresh token sits in the cache file; the first token per persona, server "
        "and scope after a console start is forced fresh.",
        "The Demo Console's MSAL cache file (.secrets\\msal-test-<id>.json) on the machine that runs it.",
        "APIM and the MCP server, exactly like T2.",
    ]),
    "operator": ("Operator tokens (az login)", "identity", [
        "Entra ID, the tenant's endpoint.",
        "ARM, Microsoft Graph, Log Analytics and Foundry. For the MCP APIs, a delegated token for the operator.",
        "The operator's own oid and roles. azp = the well-known Azure CLI client (on the client allow-list).",
        "Entra default. The console and the CLI mint tokens silently from the cache when needed.",
        "The Azure CLI's encrypted MSAL cache on the machine that runs the console. The jump box has its own az login.",
        "ARM, Graph, Log Analytics and Foundry (their own RBAC). APIM and the MCP server for the gateway beats.",
    ]),
    "k1": ("C5  APIM subscription key on /legacy", "deny", [
        "API Management: the subscription sub-abw-legacy-poc.",
        "The /legacy API only, sent as the Ocp-Apim-Subscription-Key header.",
        "None. An opaque string: no user, no roles, no expiry.",
        "Static until someone rotates it.",
        "The Foundry connection mcp-legacy-key (custom keys), and anyone who copies it.",
        "APIM only, plus a rate limit of 120 calls a minute per subscription key (else per caller IP). The legacy server checks nothing "
        "(reason no_user_context).",
    ]),
    "k2": ("C6  Vendor API key (x-vendor-key)", "deny", [
        "The deployment creates it as the Key Vault secret vendor-api-key.",
        "The simulated market-data vendor, a third party outside the private network.",
        "None. An opaque string sent as the x-vendor-key header.",
        "Static until rotated.",
        "Key Vault (APIM reads it as a named value) plus a plain Container Apps secret copy on the vendor app. The "
        "user and the agent never see it.",
        "The vendor (401 invalid_vendor_key). APIM adds it only after validating the user's token, and removes the "
        "user's Authorization header.",
    ]),
    "k3": ("C3  Agent client secret (abw-agent-client)", "deny", [
        "Entra ID: a client secret on the confidential app registration abw-agent-client.",
        "Entra's token endpoint, when Foundry exchanges a user's consent code for T2.",
        "None. An opaque string.",
        "80 days. Setup-Entra.ps1 creates a new one when fewer than 10 days remain.",
        "The Foundry OAuth connections and the git-ignored .secrets folder.",
        "Entra, at the token endpoint.",
    ]),
}
ROWS = [["t1", "t2", "t3"], ["t4", "persona", "operator"], ["k1", "k2", "k3"]]


def need_h(values: list[str]) -> float:
    vw = CW - 2 * PAD - LABEL_W
    body = sum(th(wrap(v, 16, vw), 16) for v in values) + ROW_GAP * (len(values) - 1)
    return 10 + HEAD_H + 14 + body + PAD


def draw_card(sc: Scene, x: float, y: float, h: float, key: str) -> None:
    title, kind, values = CARDS[key]
    k = KINDS[kind]
    rect = sc.panel(x, y, CW, "", "", kind=kind, h=h, tone="zone")
    g = rect.el["groupIds"][0]
    bar = sc.box(x + 10, y + 10, CW - 20, title, h=HEAD_H, kind=kind, size=18, sw=1, role="bar", fill=k["tab"],
                 stroke=k["tab"], color=k["tabtext"])
    bar.el["groupIds"] = [g]
    for c in bar.children:
        c.el["groupIds"] = [g]
    vw = CW - 2 * PAD - LABEL_W
    cy = y + 10 + HEAD_H + 14
    for lab, val in zip(LABELS, values):
        rect.children.append(sc.text(x + PAD, cy, lab, size=16, color=k["tab"], group=g))
        rect.children.append(sc.text(x + PAD + LABEL_W, cy, val, size=16, w=vw, group=g))
        cy += th(wrap(val, 16, vw), 16) + ROW_GAP


def build() -> Scene:
    sc = Scene("07-token-anatomy", 2400, 1900, "Token anatomy: who issues it, who holds it, who checks it",
               "Four tokens on the governed path, two sign-in tokens and three static secrets (C3, C5, C6)")

    # ------------------------------------------------------------------ strip: where T1-T4 travel
    sc.text(60, 190, "Which token is on which hop of one governed call (sign-in, consent and the OBO exchange: diagram 04)",
            size=20)
    sy, sh = 232, 72
    nodes = [("User, Demo Console or CLI", "actor"), ("APIM /agents front door", "network"), ("Foundry agent", "compute"),
             ("APIM gateway /<server>/mcp", "network"), ("MCP server", "compute"),
             ("Data plane: Storage, Cosmos DB, Search", "data")]
    boxes = [sc.box(60 + i * 400, sy, 280, t, h=sh, kind=k, size=18) for i, (t, k) in enumerate(nodes)]
    entra = sc.box(boxes[4].x, sy + sh + 90, 280, "Entra ID token endpoint", h=56, kind="identity", size=18)
    sc.arrow(boxes[0], boxes[1], a_at="r", b_at="l", kind="identity", step=1, label="T1", label_w=80)
    sc.arrow(boxes[1], boxes[2], a_at="r", b_at="l", kind="identity", step=2, label="T1", label_w=80)
    sc.arrow(boxes[2], boxes[3], a_at="r", b_at="l", kind="identity", step=3, label="T2", label_w=80)
    sc.arrow(boxes[3], boxes[4], a_at="r", b_at="l", kind="identity", step=4, label="T2", label_w=80)
    sc.arrow(boxes[4], entra, a_at="b", b_at="t", kind="identity", step=5, both=True, label="T3 + T2 in, T4 out",
             label_side="right", label_w=240)
    sc.arrow(boxes[4], boxes[5], a_at="r", b_at="l", kind="identity", step=6, label="T4", label_w=80)
    sc.text(60, sy + sh + 66, "The front door forwards T1 unchanged. The private MCP server skips the gateway: Foundry "
                              "sends T2 to it directly, and only the server checks it.", size=16, color="#495057", w=1300)

    # ------------------------------------------------------------------ cards
    y = sy + sh + 90 + 56 + 44
    sc.text(60, y, "Entra-issued tokens: signed, short-lived, and only good for the audience they name", size=20)
    y += 36
    bottom = y
    for ri, keys in enumerate(ROWS):
        if ri == 2:
            y += 14
            sc.text(60, y, "Static secrets: long-lived, shared, and not tied to a user", size=20)
            y += 36
        h = max(need_h(CARDS[k][2]) for k in keys)
        for k, x in zip(keys, XS):
            draw_card(sc, x, y, h, k)
        y += h + 24
        bottom = y - 24

    bottom = sc.footer(bottom + 40, [
        "Four tokens do the work: T1 gets a person into Foundry, T2 carries the person through the gateway and the MCP "
        "server, T3 is the server's own identity, and T4 reaches data as that person.",
        "Every token names its audience. T2 for one server fails at the others, and T4 works only at the one data "
        "service it was issued for.",
        "The static secrets (C3, C5, C6) are long-lived, shared and carry no user. The four data-backed MCP servers "
        "hold none of them: they use managed identities.",
    ], callout_w=1500)
    sc.fit(bottom)
    return sc
