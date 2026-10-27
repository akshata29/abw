"""Diagram 04 - authentication flow: a sequence diagram of the one-time consent and of every call after it."""
from __future__ import annotations

from excal import Scene, th, wrap

LABEL = 16


def build() -> Scene:
    sc = Scene("04-authentication-flow", 2400, 3000, "Authentication flow: who proves what, with which token",
               "First call: one-time consent. Every call after: user token, managed identity, OBO, data")

    X = [200 + i * 285 for i in range(8)]
    heads = [
        ("User", "persona in a browser, or the Demo Console", "actor"),
        ("Entra ID", "sign-in, MFA, authorization code", "identity"),
        ("Foundry agent", "Responses API, agent, OAuth connections", "compute"),
        ("APIM", "gateway: Wall 1", "network"),
        ("MCP server", "Container App: Wall 2", "compute"),
        ("Managed identity endpoint", "the server's user-assigned identity (UAMI)", "identity"),
        ("Entra token endpoint", "on-behalf-of (OBO) exchange", "identity"),
        ("Data plane", "Storage, Cosmos DB, AI Search: Wall 3", "data"),
    ]
    HW, hy = 250, 190
    hs = [sc.panel(x - HW / 2, hy, HW, t, b, kind=k, align="center") for x, (t, b, k) in zip(X, heads)]
    hh = max(h.h for h in hs)
    for h in hs:
        h.el["height"] = hh
    life_top = hy + hh
    lives = [sc.lifeline(x, life_top, life_top + 5000, kind=k) for x, (_, _, k) in zip(X, heads)]

    state = {"y": life_top + 24, "n": 0}

    def banner(text: str) -> None:
        b = sc.box(60, state["y"], 2280, text, kind="actor", size=18, h=44, role="bar")
        state["y"] = b.bottom + 24

    def msg(i: int, j: int, text: str, *, kind: str | None = None, dashed: bool = False) -> None:
        span = abs(X[j] - X[i])
        lw = min(max(span + 150, 330), 640)
        lh = th(wrap(text, LABEL, lw), LABEL) + 10
        y = state["y"] + lh + 20
        state["n"] += 1
        right = j > i
        sc.arrow(lives[i], lives[j], a_at=f"{'r' if right else 'l'}@{y}", b_at=f"{'l' if right else 'r'}@{y}",
                 label=text, label_w=lw, label_dy=-12, step=state["n"], marker_at=34 / (span - 16), kind=kind, dashed=dashed)
        state["y"] = y + 26

    def note(i: int, text: str, kind: str, w: float = 520) -> None:
        x = max(60, min(X[i] - w / 2, 2340 - w))
        b = sc.box(x, state["y"], w, text, kind=kind, size=LABEL)
        state["y"] = b.bottom + 24

    # ------------------------------------------------------------------ A. first call: consent
    banner("A. First call by a user on a connection: the one-time consent (grey dashed arrows are done by a person)")
    msg(0, 2, "Ask the agent something that needs the wall tool. Bearer T1: the user's Entra token for Foundry "
              "(audience https://ai.azure.com).")
    msg(2, 0, "Response holds oauth_consent_request: a sign-in link, valid about 10 minutes. No tool has run yet.")
    msg(0, 1, "Open the link as that persona and sign in: password and MFA. The MCP API scopes are already admin-consented.",
        kind="human", dashed=True)
    msg(1, 2, "Redirect to Foundry's redirect URI with an authorization code.")
    msg(2, 1, "Redeem the code as abw-agent-client; its client secret is held in the Foundry connection.")
    msg(1, 2, "T2 issued: audience = the wall API app, scp = Tools.Read, roles = the user's app roles, azp = abw-agent-client.")
    note(2, "Foundry keeps T2 for this user and connection and reuses it until it expires (Entra lifetimes are 60-90 min). "
            "A role change reaches the agent only when that token expires.", "compute", w=540)

    # ------------------------------------------------------------------ B. steady state
    banner("B. Every call after that: the steady state, until the token Foundry holds expires (60-90 minutes)")
    msg(0, 2, "Ask again. Bearer T1 (audience https://ai.azure.com, oid = the user). In Act 7 the call enters through "
              "APIM /agents, which forwards T1 unchanged (diagram 11).")
    msg(2, 3, "Foundry checks T1 (Foundry Agent Consumer on the project), runs the agent, then calls the tool: "
              "tools/call get_deal_document with Bearer T2.")
    note(3, "Wall 1: validate-jwt (audience = the wall API app, tenant, tid), then abw-deny (kill switch, azp allow-list, "
            "scope, role) and 120 calls per minute per user. Adds x-abw-request-id.", "network")
    msg(3, 4, "Forward the call: T2 unchanged, plus x-abw-request-id and x-abw-gateway: apim.")
    note(4, "Wall 2: verify T2 again (RS256 signature via JWKS, audience, v2.0 issuer, tid, azp allow-list, scp Tools.Read). "
            "Then the tool's own rule: the project (falcon) must be in the token's roles.", "compute")
    msg(4, 5, "Ask for a token as the server's UAMI, audience api://AzureADTokenExchange.")
    msg(5, 4, "T3: the UAMI assertion. sub = the UAMI principal, issued by the tenant's v2.0 endpoint.")
    msg(4, 6, "OBO request: assertion = T2, client_assertion = T3, scope https://storage.azure.com/user_impersonation "
              "(Cosmos and Search use their own scope).")
    note(6, "Checks T3 against the federated credential on the API app (issuer, subject, audience) and the pre-granted consent.",
         "identity", w=500)
    msg(6, 4, "T4: audience = Storage, oid = the user, azp = the wall API app. The data plane sees the person, not the server.")
    msg(4, 7, "GET FALCON-001.md with Bearer T4 and x-ms-client-request-id = request_id.")
    note(7, "Wall 3: Azure RBAC on the user's own identity. sg-abw-wall-falcon holds Storage Blob Data Reader on wall-falcon.",
         "data", w=296)
    msg(7, 4, "200 with the document, or 403 (the server reports storage_rbac_denied).")
    msg(4, 2, "Tool result with request_id, back through APIM. A denial is a result too: decision DENIED, a reason and the request_id.")
    msg(2, 0, "The answer. The execute_tool span records the tool result and its request_id.")

    y_end = state["y"]
    for lf in lives:
        lf.el["height"] = y_end - life_top

    # ------------------------------------------------------------------ footer: callout and the token key
    fy = y_end + 40
    c = sc.callout(60, fy, 760, [
        "Three tokens meet at the MCP server: T2 comes in from the user, T3 proves the server's own identity, and T4 goes out "
        "to the data as the user.",
        "No MCP server holds a client secret: T3 is a managed identity token, trusted through a federated credential. "
        "The only OAuth client secret, abw-agent-client's, sits in the five Foundry OAuth connections and the git-ignored "
        ".secrets folder.",
        "A role change reaches the gateway with the next token you request (up to about 30 s; one removal lagged longer), but the agent keeps the T2 "
        "Foundry already holds until it expires.",
    ])
    sc.text(850, fy, "Tokens in this diagram (T1-T4 mean the same in diagrams 01, 03, 07, 11 and 13; the document also writes T2a, T2b and T4a-c)", size=20)
    tb = sc.table(850, fy + 36, [("Token", 76), ("What it is", 290), ("Audience (aud)", 270), ("Key claims", 560), ("Checked by", 294)], [
        [("T1", "identity"), "User token for Foundry, sent with every agent call", "https://ai.azure.com",
         "oid, tid, upn or preferred_username; a delegated token, not app-only", "Foundry (and APIM /agents in Act 7)"],
        [("T2", "identity"), "User token for one MCP API; Foundry mints it after the consent and holds it",
         "the API app, for example abw-mcp-wall",
         "scp Tools.Read (Tools.Execute on actions); roles = the user's app roles; azp = abw-agent-client; oid, tid, uti",
         "APIM validate-jwt (Wall 1), then the MCP server (Wall 2)"],
        [("T3", "identity"), "Managed identity token of the MCP server", "api://AzureADTokenExchange",
         "sub = the UAMI principal; iss = the tenant's v2.0 endpoint", "Entra, against the federated credential on the API app"],
        [("T4", "identity"), "On-behalf-of token for one data plane",
         "https://storage.azure.com, https://cosmos.azure.com or https://search.azure.com",
         "oid = the user; azp = the MCP API app; scp user_impersonation", "The data plane: its own roles, as that user"],
    ])
    sc.fit(max(c.bottom, tb["bottom"]))
    return sc
