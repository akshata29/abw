"""Diagram 01 - system architecture: every component, who talks to whom, the numbered main flow."""
from __future__ import annotations

from excal import Scene, TOP


def build() -> Scene:
    sc = Scene("01-system-architecture", 2400, 1900, "System architecture",
               "Five personas reach Foundry agents and MCP tools through one gateway; the data plane has the last word")

    # ---------------------------------------------------------------- Entra band
    ey = 185
    ent = sc.row(80, ey + TOP, [
        "App registrations: 5 MCP API apps (research, wall, actions, private, vendorgw) and 2 clients (abw-agent-client, abw-test-client)",
        "6 security groups: sg-abw-demo-all, -research, -wall-falcon, -traders, -compliance, -infosec",
        "5 persona users, abw.<persona>@<tenant-domain>, with app roles assigned to the user",
        "4 federated credentials (research, wall, actions, private): managed identity to API app, no secrets",
        "Token endpoint: sign-in with MFA, device code, and the on-behalf-of (OBO) exchange",
    ], w=2240, gap=16, size=16, kind="identity")
    ez = sc.zone(60, ey, 2280, TOP + ent[0].h + 20, "Microsoft Entra ID - identity and tokens", kind="identity")
    y0 = round(ez.bottom + 70)

    # ---------------------------------------------------------------- column A: people
    AX, AW = 60, 270
    pers = sc.stack(AX + 20, y0 + TOP, AW - 40, [
        "Priya - Research Analyst", "Wes - IB Associate", "Tara - Equity Trader", "Carla - Compliance Officer", "Ian - InfoSec Analyst",
    ], gap=10, size=16, kind="actor", minh=46)
    pz = sc.zone(AX, y0, AW, TOP + pers[-1].bottom - pers[0].top + 20, "Five demo personas", kind="actor")
    oy = pz.bottom + 30
    ops = sc.stack(AX + 20, oy + TOP, AW - 40, [
        ("Operator on a laptop: az CLI sign-in", "actor"),
        ("Demo Console on localhost:8787; personas sign in by device code", "compute"),
        ("Jump box + Bastion (optional): runs the console inside the VNet", "human"),
    ], gap=10, size=16)
    opz = sc.zone(AX, oy, AW, TOP + ops[-1].bottom - ops[0].top + 20, "Operator and console", kind="actor")

    # ---------------------------------------------------------------- column B: APIM + Foundry
    BX, BW = 440, 620
    ix, iw = BX + 20, BW - 40
    r1 = sc.row(ix, y0 + TOP, ["/agents front door: validate-jwt, per-user token budget, rate limit"], w=iw, size=16, kind="network")
    r2 = sc.row(ix, r1[0].bottom + 12, ["/research/mcp", "/wall/mcp", "/actions/mcp", "/vendor/mcp"], w=iw, gap=12, size=16,
                kind="network", minh=44)
    r3 = sc.row(ix, r2[0].bottom + 12, [("/legacy/mcp: shared subscription key, no token check", "deny"),
                                         "/.well-known/oauth-protected-resource: protected-resource metadata",
                                         "API Center (a separate resource): catalog of the APIs"],
                w=iw, gap=12, size=16, kind="network")
    r4 = sc.row(ix, r3[0].bottom + 12, ["Per-MCP policy: validate-jwt, then abw-deny (kill switch, client allow-list, scope, role), "
                                         "then 120 calls per minute per user"], w=iw, size=16, kind="network")
    az = sc.zone(BX, y0, BW, r4[0].bottom + 20 - y0, "API Management (APIM) - Wall 1", kind="network")

    fy = az.bottom + 90
    f1 = sc.row(ix, fy + TOP, ["Foundry account and project; agents run in snet-agent", "Model gpt-54-mini (GlobalStandard)"],
                w=iw, size=16, kind="compute")
    f2 = sc.row(ix, f1[0].bottom + 12, ["abw-poc-legacy", "abw-wall-desk", "abw-wall-desk-redteam",
                                         "abw-wall-desk-redteam-shielded (optional, --rai)"],
                widths=[110, 110, 140, 184], gap=12, size=16, kind="compute")
    f3 = sc.row(ix, f2[0].bottom + 12, [("Guardrail abw-agent-guardrails: Wall 0, detective, preview, probabilistic", "deny"),
                                         "6 connections: 5 OAuth (one per MCP server) and 1 key (legacy)"], w=iw, size=16)
    fz = sc.zone(BX, fy, BW, f3[0].bottom + 20 - fy, "Microsoft Foundry - agents and guardrail", kind="compute")

    # ---------------------------------------------------------------- column C: Container Apps
    CX, CW = 1210, 570
    cix, ciw = CX + 20, CW - 40
    t_int = "Internal environment cae-abw-priv (snet-mcp)"
    iy = y0 + TOP
    s1 = sc.row(cix + 20, iy + Scene.top_for(t_int, ciw), ["mcp-research via APIM /research", "mcp-wall via APIM /wall",
                                                           "mcp-actions via APIM /actions"], w=ciw - 40, gap=12, size=16, kind="compute")
    s2 = sc.row(cix + 20, s1[0].bottom + 12, [("mcp-private: reached directly from Foundry, NOT behind APIM", "compute"),
                                               ("mcp-legacy: shared key, no user token (deliberate)", "deny")],
                w=ciw - 40, gap=12, size=16)
    iz = sc.zone(cix, iy, ciw, s2[0].bottom + 20 - iy, t_int, kind="compute")

    t_pub = "Public environment cae-abw-pub (outside the VNet)"
    py = iz.bottom + 24
    v1 = sc.row(cix + 20, py + Scene.top_for(t_pub, ciw), ["mcp-vendor (vendor mock) via APIM /vendor: accepts only the key APIM injects"],
                w=ciw - 40, size=16, kind="compute")
    pubz = sc.zone(cix, py, ciw, v1[0].bottom + 20 - py, t_pub, kind="compute")

    u1 = sc.row(cix, pubz.bottom + 24, ["6 MCP user-assigned managed identities (one per server; the seed job has a 7th); 4 hold a federated credential in Entra"],
                w=ciw, size=16, kind="identity")
    u2 = sc.row(cix, u1[0].bottom + 12, ["One image, abw-mcp; MCP_SERVER picks the server; 0.5 vCPU, 1 GiB, 1 to 2 replicas"],
                w=ciw, size=16, kind="compute")

    bottom = max(fz.bottom, u2[0].bottom + 20)
    cz = sc.zone(CX, y0, CW, bottom - y0, "Azure Container Apps - MCP tool servers - Wall 2", kind="compute")
    fz.el["height"] = bottom - fz.y  # keep the Foundry column flush with the others
    sc.fill_to(f3, bottom - 20)
    sc.fill_to(u2, bottom - 20)

    # ---------------------------------------------------------------- column D: data
    DX, DW = 1880, 460
    gapd = 14
    hd = (bottom - y0 - TOP - 20 - 4 * gapd) / 5
    sc.stack(DX + 20, y0 + TOP, DW - 40, [
        "Storage: research-public, wall-falcon, wall-orion, worm-audit; shared key off. worm-audit is the audit log, 1-day immutability (unlocked demo setting)",
        "Cosmos DB (serverless, public access off): database abw with restricted, orders, positions",
        "AI Search (Basic): index deals-idx",
        "Key Vault (RBAC): vendor-api-key, the only secret stored here, read by APIM",
        "Container Registry (Standard, admin off): image abw-mcp",
    ], gap=gapd, size=16, kind="data", h=hd)
    dz = sc.zone(DX, y0, DW, bottom - y0, "Data stores - Wall 3 (data-plane roles)", kind="data")

    # ---------------------------------------------------------------- bottom band
    by = bottom + 70
    g1 = sc.row(80, by + TOP, ["Azure Policy initiative abw-agent-platform-controls: 5 control families - no keys, private networking, "
                                "approved tools and models, guardrails, hygiene"], w=480, size=16, kind="policy")
    g2 = sc.row(80, g1[0].bottom + 12, ["Budget USD 1,200 per month on the resource group: alerts at 50, 80 and 100 % actual and "
                                         "100 % forecast (an alert, not a cap)"], w=480, size=16, kind="policy")
    o1 = sc.row(640, by + TOP, ["Agent 365 gateway", "Defender XDR security for AI agents", "Purview DSPM for AI"],
                w=660, gap=12, size=16, kind="human")
    o2 = sc.row(640, o1[0].bottom + 12, ["Optional: a person switches these on in the Microsoft admin portals; nothing else depends on them"],
                w=660, size=16, kind="human")
    l1 = sc.row(1400, by + TOP, [
        "Log Analytics: gateway, container and storage logs; 10 KQL functions such as AbwFullChain",
        "Application Insights (private link): Foundry agent and tool spans",
        "Microsoft Sentinel: 9 analytics rules, ABW-001 to ABW-009",
    ], w=920, gap=12, size=16, kind="obs")
    l2 = sc.row(1400, l1[0].bottom + 12, [
        "Workbook Agent Wall - Cockpit, 8 tabs", "3 alert rules and an action group",
        "Entra sign-in export workspace: separate, read-only",
    ], w=920, gap=12, size=16, kind="obs")
    bandb = max(g2[0].bottom, o2[0].bottom, l2[0].bottom) + 20
    for last in (g2, o2, l2):
        sc.fill_to(last, bandb - 20)
    gz = sc.zone(60, by, 540, bandb - by, "Governance", kind="policy")
    oz2 = sc.zone(620, by, 700, bandb - by, "Optional admin-portal features", kind="human")
    obz = sc.zone(1380, by, 960, bandb - by, "Observability", kind="obs")

    # ---------------------------------------------------------------- numbered main flow
    sc.arrow(pz, ez, a_at="t@195", b_at="b@195", step=1, label="sign in + MFA", label_side="right")
    sc.arrow(pz, az, a_at=f"r@{y0 + 150}", b_at=f"l@{y0 + 150}", step=2)
    sc.arrow(az, fz, a_at="b@600", b_at="t@600", step=3, label="Responses API, T1 forwarded", label_side="left", label_w=190)
    sc.arrow(fz, az, a_at="t@900", b_at="b@900", step=4, label="tools/call with the user's token, T2", label_side="left", label_w=190)
    sc.arrow(az, cz, a_at=f"r@{y0 + 180}", b_at=f"l@{y0 + 180}", step=5)
    sc.arrow(cz, ez, a_at="t@1500", b_at="b@1500", step=6, label="OBO via managed identity", label_side="right")
    sc.arrow(cz, dz, a_at=f"r@{y0 + 150}", b_at=f"l@{y0 + 150}", step=7)
    sc.arrow(cz, obz, a_at="b@1500", b_at="t@1500", step=8, label="audit and logs", label_side="right", label_w=150)
    sc.arrow(fz, s2[0], a_at=f"r@{fz.top + 120}", b_at=f"l@{s2[0].cy}", via=[(1135, fz.top + 120), (1135, s2[0].cy)],
             kind="deny", dashed=True, label="direct, not via APIM", label_inline=True, label_w=110, label_color="#c92a2a")

    fb = sc.footer(bandb + 40, [
        "Four walls in order: Foundry guardrail (W0, detective), APIM gateway (W1), MCP server (W2), data plane (W3). Each one has its own deny.",
        "The private MCP server is reached directly from Foundry, so the APIM kill switch and rate limit do not cover it.",
        "Governed data paths carry the user's own identity end to end (T1, T2, then T4 by OBO); the vendor path ends at the "
        "gateway, and the legacy path (red) uses a shared key on purpose.",
    ], flow=[
        "A persona signs in to Entra ID with MFA (the console uses device code on abw-test-client).",
        "The user calls APIM /agents with an Entra token for Foundry (T1); APIM checks it and meters tokens.",
        "APIM forwards to the Foundry Responses API; the user's token is passed on unchanged.",
        "The agent calls a tool: Foundry sends the user's own OAuth token (T2, from a one-time consent) to APIM.",
        "APIM checks audience, role, client and rate, then forwards to the MCP server (Wall 1).",
        "The MCP server re-checks the token and swaps it for a data-plane token (OBO) using its managed identity (Wall 2).",
        "The MCP server calls Storage, Cosmos or Search as the user; the data plane's own roles allow or deny (Wall 3).",
        "Every hop logs: APIM, MCP and Foundry telemetry flow to Log Analytics; MCP also writes the audit blob.",
    ], callout_w=860, flow_title="Main flow (numbers on the arrows)")
    sc.fit(fb)
    return sc
