"""Diagram 02 - Network topology: the VNet, its subnets, private endpoints, private DNS and egress."""
from __future__ import annotations

from excal import INK, KINDS, MUTED, Scene, th, wrap

TITLE = "Network topology: subnets, private endpoints, egress"
SUBTITLE = "Private-endpoint-only data planes, one NAT address, no internet path from the agent subnet"

# ---------------------------------------------------------------------------------------------------- top band (outside the VNet)
FOUNDRY_TOP = (
    "Foundry account aif-abw-demo-<region>-<u4>\n"
    "Public network access on (policy-exempt), local auth off. Its Agent Service runtime is injected into snet-agent.")
CALLERS = (
    "Callers outside the VNet\n"
    "A laptop, curl, the Foundry portal. Each reaches a public endpoint.")
APIM_TOP = (
    "API Management apim-abw-demo-<region>-<u4> (StandardV2)\n"
    "Public gateway: public network access on. Inbound: a private endpoint in snet-pe. "
    "Outbound: VNet integration into snet-apim.")
OPERATOR = (
    "Operator (manual)\n"
    "Azure portal, then the VM, Connect, Bastion. Sign in with the VM's local admin password.")
BASTION = (
    "Bastion Developer bas-abw-demo-<region>-001\n"
    "Attached to the VNet, not to a subnet. No public IP, free, one session at a time.")

# ---------------------------------------------------------------------------------------------------- subnets
SUBNETS = [
    ("snet-agent 10.42.0.0/24", "network"),
    ("snet-pe 10.42.1.0/24", "network"),
    ("snet-mcp 10.42.2.0/24", "network"),
    ("snet-apim 10.42.3.0/26", "network"),
    ("snet-jump 10.42.4.0/27", "human"),
]

A_RUNTIME = (
    "Foundry Agent Service runtime\n"
    "Network-injected into this subnet. The agents' tool calls to MCP servers start here.")
A_SETTINGS = "Delegated to Microsoft.App/environments. Default outbound access off. No NSG and no NAT gateway."
A_CHIP = "No path to the internet"
A_TOOLS = (
    "Tool calls leave this subnet two ways\n"
    "Through the APIM private endpoint in snet-pe (step 2), or straight to ca-abw-mcp-private (step 5).")

P_APIM = (
    "Private endpoint: APIM gateway\n"
    "How callers inside the VNet, such as the agent runtime and the jump box, reach the gateway privately. "
    "The public gateway stays on for everyone else.")
P_DATA = (
    "Private endpoints: app data stores\n"
    "Storage blob (data and WORM audit), Cosmos DB (SQL) and AI Search. Public access off and keys off: "
    "the only way in is a private endpoint with an on-behalf-of token.")
P_SMALL = [
    "Private endpoint: Foundry account",
    "Private endpoints: Agent Service stores (BYO Storage blob, Cosmos DB, AI Search)",
    "Private endpoint: Key Vault",
    "Private endpoint: Azure Monitor Private Link Scope (AMPLS)",
]
P_SETTINGS = "Private endpoints only. PE network policies off, default outbound access off. No NSG and no NAT gateway."

M_PRIVATE = (
    "ca-abw-mcp-private\n"
    "Called straight from the agent subnet at its internal name. Never behind APIM, so the APIM kill switch cannot stop it.")
M_APPS = (
    "ca-abw-mcp-research, -wall, -actions, -legacy\n"
    "Reached through APIM, which calls them from snet-apim.")
M_SEED = (
    "Seed job caj-abw-seed-<region>-001\n"
    "Loads the demo data from inside the VNet, because every data plane is private-endpoint-only.")
M_ENV = (
    "Container Apps environment cae-abw-priv-<region>-001\n"
    "Internal: VNet-only ingress. One image (abw-mcp); the MCP_SERVER setting picks the server. "
    "0.5 vCPU, 1 GiB, 1 to 2 replicas each.")
M_SETTINGS = "Delegated to Microsoft.App/environments. NAT gateway attached (Entra signing keys, on-behalf-of, telemetry). No NSG."

X_SETTINGS = "Delegated to Microsoft.Web/serverFarms. NAT gateway attached."
X_INTEGRATION = (
    "APIM outbound VNet integration\n"
    "The gateway's calls to backends leave from this subnet: to the MCP apps inside the VNet, "
    "and to public hosts through the NAT gateway.")
X_NSG = (
    "NSG nsg-abw-apim-<region>-001 (outbound rules only)\n"
    "100 allow AzureKeyVault 443: an APIM v2 platform dependency\n"
    "110 allow VirtualNetwork 443: the MCP apps and the Foundry private endpoints\n"
    "120 allow Internet 443: the vendor mock, Entra and Monitor through the NAT\n"
    "Only these three custom rules; no custom inbound rules.")

J_VM = (
    "Jump VM vm-abw-jump-<region>-001 (optional)\n"
    "Windows Server 2022, Trusted Launch, no public IP. A local admin password, because Bastion Developer needs one. "
    "Auto-shutdown at 03:00 Central as a backstop.")
J_NSG = (
    "NSG nsg-abw-jump-<region>-001\n"
    "100 allow RDP 3389 from VirtualNetwork (Bastion)\n"
    "4000 deny all inbound from the Internet")
J_NAT = "NAT gateway attached, so the VM's browser reaches Entra and the portal. Default outbound access off."
J_WHY = (
    "Why it exists: every data plane is private-endpoint-only, so the portal's data pages fail from a laptop. "
    "From this VM the same names resolve to the private endpoints.")
J_RULE = "Never re-run the network stage while this subnet exists: run jumpbox.ps1 -Remove first."

# ---------------------------------------------------------------------------------------------------- bottom band
NAT_TEXT = (
    "NAT gateway ng-abw-demo-<region>-001 with public address pip-ng-abw-demo-<region>-001\n"
    "Standard SKU, one static IPv4 address, idle timeout 10 minutes. Attached to snet-mcp, snet-apim and snet-jump; "
    "not to snet-agent or snet-pe. This address is the only one allowed through the Key Vault firewall "
    "(public endpoint on, default action Deny, trusted Azure services bypass).")
I_ENTRA = (
    "Microsoft Entra ID\n"
    "On-behalf-of token exchange and signing keys for the MCP servers; token-validation metadata for APIM.")
I_MONITOR = (
    "Azure Monitor ingestion\n"
    "Telemetry from the MCP apps and APIM. The Monitor Private Link Scope runs in Open ingestion mode, "
    "so writers outside the VNet can still ingest.")
I_VENDOR = (
    "Public Container Apps environment cae-abw-pub-<region>-001\n"
    "Hosts ca-abw-mcp-vendor, the simulated third-party MCP server. No VNet configuration. "
    "APIM calls it on 443 through the NAT gateway.")
I_BROWSER = (
    "From the jump box\n"
    "Entra sign-in, Azure portal, ai.azure.com, Azure Resource Manager, Microsoft Graph and the container registry host. "
    "The one-time console installers (Python, Azure CLI, PowerShell 7) pass the same way.")
OBSERVED = (
    "Observed from inside the jump box (in-VM run command): 11 of 11 private names resolve to 10.42.1.x and answer on 443, "
    "6 of 6 outbound hosts answer, and the egress address is the NAT gateway's. "
    "Not observed: the Bastion browser session itself.")

DNS_TITLE = "Private DNS zones (linked to the VNet, registration off)"
DNS_HEAD1 = "13 network-stage zones the Foundry template references as existing (the 14th, APIM's, is below)"
DNS_FOUNDRY = [
    "privatelink.services.ai.azure.com",
    "privatelink.openai.azure.com",
    "privatelink.cognitiveservices.azure.com",
    "privatelink.search.windows.net",
    "privatelink.blob.core.windows.net",
    "privatelink.documents.azure.com",
    "privatelink.fabric.microsoft.com (unused)",
    "privatelink.azurecr.io (unused)",
    "privatelink.vaultcore.azure.net",
    "privatelink.monitor.azure.com",
    "privatelink.oms.opinsights.azure.com",
    "privatelink.ods.opinsights.azure.com",
    "privatelink.agentsvc.azure-automation.net",
]
DNS_HEAD2 = "Also in use: the APIM endpoint zone and the internal Container Apps zone"
DNS_APIM = "privatelink.azure-api.net (APIM gateway endpoint)"
DNS_ACA = "The internal environment's default domain, wildcard record to its internal address (platform stage)"

BULLETS = [
    "snet-agent has no NAT gateway and no default outbound access: the agent runtime has no internet path. It reaches "
    "APIM through a private endpoint and the private MCP at its internal name.",
    "Storage, Cosmos DB and AI Search accept no public traffic and no keys. The only way to data is a private endpoint, "
    "with an on-behalf-of token.",
    "All VNet egress leaves through one NAT address, the only address on the Key Vault firewall. The APIM NSG allows "
    "three outbound destinations on 443; the jump-box NSG admits only Bastion and denies the internet.",
]
FLOW = [
    "A client calls the APIM public gateway with a bearer token. Wall 1 (APIM) judges every call there.",
    "The agent runtime has no internet path, so it reaches the same gateway through the APIM private endpoint in snet-pe.",
    "APIM's backend calls leave through its outbound VNet integration in snet-apim.",
    "They stay inside the VNet to the MCP apps in the internal Container Apps environment (NSG rule 110).",
    "The private MCP is called straight from the agent subnet at its internal name. It is never behind APIM, so Wall 1 "
    "and the kill switch do not apply to it.",
    "After the on-behalf-of exchange, the MCP servers reach Storage, Cosmos DB and AI Search through private "
    "endpoints. Private DNS answers with 10.42.1.x addresses.",
    "Public hosts (Entra, Azure Monitor, the vendor mock) are reached through the NAT gateway's one static address, "
    "from snet-mcp, snet-apim and snet-jump only.",
    "The operator opens the VM in the Azure portal and connects through Bastion Developer.",
    "Bastion reaches the VM on RDP 3389, the only inbound NSG rule. From the VM the private names resolve to the "
    "private endpoints.",
]

X0 = 80
ZW = 384
ZG = 80
COLX = [X0 + i * (ZW + ZG) for i in range(5)]
CW = ZW - 40
GAPV = 14
BAND_Y = 200


def need(text: str, w: float, size: float = 16, pad: float = 12) -> float:
    return th(wrap(text, size, w - 2 * pad), size) + 20


def card(sc: Scene, x: float, y: float, w: float, text: str, kind: str, h: float | None = None, **kw):
    return sc.box(x, y, w, text, h=need(text, w) if h is None else h, kind=kind, size=16, align="left", inset=10, **kw)


def solid(kind: str) -> dict:
    k = KINDS[kind]
    return dict(fill=k["tab"], stroke=k["tab"], color=k["tabtext"])


def build() -> Scene:
    sc = Scene("02-network-topology", 2400, 2400, TITLE, SUBTITLE)

    # ------------------------------------------------------------------ top band: what sits outside the VNet
    hb = max(need(t, ZW) for t in (FOUNDRY_TOP, CALLERS, APIM_TOP, OPERATOR))
    callers_x = COLX[0] + ZW + (COLX[3] - COLX[0] - ZW - ZW) / 2
    foundry = card(sc, COLX[0], BAND_Y, ZW, FOUNDRY_TOP, "compute", h=hb)
    callers = card(sc, callers_x, BAND_Y, ZW, CALLERS, "actor", h=hb)
    apim_top = card(sc, COLX[3], BAND_Y, ZW, APIM_TOP, "network", h=hb)
    operator = card(sc, COLX[4], BAND_Y, ZW, OPERATOR, "human", h=hb)
    band_bottom = BAND_Y + hb

    # ------------------------------------------------------------------ the VNet and its five subnets
    yv = band_bottom + 90
    bast_h = need(BASTION, ZW)
    ys = yv + 30 + bast_h + 84
    lane_y = yv + 76
    vnet = sc.zone(60, yv, 2280, 100, "VNet vnet-abw-demo-<region>-001", kind="network")
    sc.text(84, yv + 58, "Address space 10.42.0.0/16\nFive subnets, the fifth optional", size=16, color=MUTED)
    bast = card(sc, COLX[4], yv + 30, ZW, BASTION, "network", h=bast_h)

    zs = [sc.zone(COLX[i], ys, ZW, 100, t, kind=k) for i, (t, k) in enumerate(SUBNETS)]
    top = zs[0].content_y
    assert all(abs(z.content_y - top) < 0.5 for z in zs), "subnet tab titles must stay on one line"
    ix = [x + 20 for x in COLX]

    # row 1 and row 2 are shared by the four columns that the numbered arrows run across
    h1 = max(need(t, CW) for t in (A_RUNTIME, P_APIM, M_PRIVATE, X_SETTINGS))
    h2 = max(need(t, CW) for t in (A_SETTINGS, P_DATA, M_APPS, X_INTEGRATION))
    y1 = top
    y2 = y1 + h1 + GAPV
    y3 = y2 + h2 + GAPV

    runtime = card(sc, ix[0], y1, CW, A_RUNTIME, "compute", h=h1)
    pe_apim = card(sc, ix[1], y1, CW, P_APIM, "network", h=h1)
    priv = card(sc, ix[2], y1, CW, M_PRIVATE, "compute", h=h1)
    card(sc, ix[3], y1, CW, X_SETTINGS, "network", h=h1)
    vm = card(sc, ix[4], y1, CW, J_VM, "compute")

    card(sc, ix[0], y2, CW, A_SETTINGS, "network", h=h2)
    pe_data = card(sc, ix[1], y2, CW, P_DATA, "network", h=h2)
    apps = card(sc, ix[2], y2, CW, M_APPS, "compute", h=h2)
    integ = card(sc, ix[3], y2, CW, X_INTEGRATION, "network", h=h2)

    # remaining cards stack freely under rows 1 and 2
    chip = sc.box(ix[0], y3, CW, A_CHIP, h=40, kind="deny", size=16, pad=4, role="chip", dashed=False, **solid("deny"))
    bottoms = [card(sc, ix[0], chip.bottom + GAPV, CW, A_TOOLS, "network").bottom]

    y = y3
    for t in P_SMALL:
        y = card(sc, ix[1], y, CW, t, "network").bottom + GAPV
    bottoms.append(card(sc, ix[1], y, CW, P_SETTINGS, "network").bottom)

    y = y3
    for t in (M_SEED, M_ENV):
        y = card(sc, ix[2], y, CW, t, "compute").bottom + GAPV
    bottoms.append(card(sc, ix[2], y, CW, M_SETTINGS, "network").bottom)

    bottoms.append(card(sc, ix[3], y3, CW, X_NSG, "network").bottom)

    y = card(sc, ix[4], vm.bottom + GAPV, CW, J_NSG, "network").bottom + GAPV
    y = card(sc, ix[4], y, CW, J_NAT, "network").bottom + GAPV
    y = card(sc, ix[4], y, CW, J_WHY, "human").bottom + GAPV
    bottoms.append(card(sc, ix[4], y, CW, J_RULE, "deny").bottom)

    zone_bottom = max(bottoms) + 20
    for z in zs:
        z.el["height"] = zone_bottom - ys
    vnet_bottom = zone_bottom + 24
    vnet.el["height"] = vnet_bottom - yv

    # ------------------------------------------------------------------ bottom band, right: NAT gateway and the public side
    nat_y = vnet_bottom + 60
    band_w = COLX[4] + ZW - COLX[2]
    nat = card(sc, COLX[2], nat_y, band_w, NAT_TEXT, "network")
    inet_y = nat.bottom + 80
    inet = sc.zone(COLX[2], inet_y, band_w, 100, "Public endpoints reached through the NAT address", kind="network")
    iw = (band_w - 40 - 20) / 2
    r1h = max(need(I_ENTRA, iw), need(I_MONITOR, iw))
    r2h = max(need(I_VENDOR, iw), need(I_BROWSER, iw))
    r1y = inet.content_y
    r2y = r1y + r1h + GAPV
    card(sc, COLX[2] + 20, r1y, iw, I_ENTRA, "identity", h=r1h)
    card(sc, COLX[2] + 20 + iw + 20, r1y, iw, I_MONITOR, "obs", h=r1h)
    card(sc, COLX[2] + 20, r2y, iw, I_VENDOR, "compute", h=r2h)
    card(sc, COLX[2] + 20 + iw + 20, r2y, iw, I_BROWSER, "human", h=r2h)
    inet.el["height"] = r2y + r2h + 20 - inet_y
    obs = card(sc, COLX[2], inet.bottom + 30, band_w, OBSERVED, "obs")

    # ------------------------------------------------------------------ bottom band, left: private DNS
    dns_w = COLX[2] - 60 - 60
    dns = sc.zone(60, nat_y, dns_w, 100, DNS_TITLE, kind="network")
    cx0 = 60 + 20
    chip_w = (dns_w - 40 - 16) / 2
    y = dns.content_y
    sc.text(cx0, y, DNS_HEAD1, size=16, color=MUTED)
    y += 28
    for i in range(0, len(DNS_FOUNDRY), 2):
        pair = DNS_FOUNDRY[i:i + 2]
        sc.row(cx0, y, pair, widths=[chip_w] * len(pair), gap=16, size=16, kind="network", h=40)
        y += 50
    y += 4
    sc.text(cx0, y, DNS_HEAD2, size=16, color=MUTED)
    y += 28
    sc.row(cx0, y, [DNS_APIM, DNS_ACA], widths=[chip_w, chip_w], gap=16, size=16, kind="network", h=60)
    bottom = max(y + 60 + 20, obs.bottom)
    dns.el["height"] = bottom - nat_y
    sc.fill_to([obs], bottom)

    # ------------------------------------------------------------------ arrows (zone heights are final now)
    sc.arrow(callers, apim_top, a_at="r", b_at="l", kind="network", step=1, label="HTTPS with a bearer token",
             label_side="above", label_w=260)
    sc.arrow(callers, foundry, a_at="l", b_at="r", kind="network", label="public endpoint (portal, laptop)",
             label_side="above", label_w=270)
    fx = foundry.right - 24
    sc.arrow(foundry, zs[0], a_at=f"b@{fx}", b_at=f"t@{fx}", kind="network", label="network injection",
             label_side="left", label_at=0.8, label_w=200)
    ax = apim_top.right - 60
    sc.arrow(apim_top, zs[3], a_at=f"b@{ax}", b_at=f"t@{ax}", kind="network", step=3, label="outbound integration",
             label_side="left", label_w=200)

    sc.arrow(runtime, pe_apim, a_at="r", b_at="l", kind="network", step=2)
    px = priv.right - 40
    sc.arrow(runtime, priv, a_at=f"r@{y1 + 14}", b_at=f"t@{px}", kind="deny", step=5,
             via=[(480, y1 + 14), (480, lane_y), (px, lane_y)],
             label="Direct to the private MCP's internal name: never behind APIM", label_side="above", label_w=540)
    sc.arrow(integ, apps, a_at="l", b_at="r", kind="network", step=4)
    sc.arrow(apps, pe_data, a_at="l", b_at="r", kind="network", step=6)
    sc.arrow(zs[1], dns, a_at=f"b@{zs[1].cx}", b_at=f"t@{zs[1].cx}", kind="network", label="DNS zone group per endpoint",
             label_side="right", label_at=0.65, label_w=260)

    for z in (zs[2], zs[3], zs[4]):
        sc.arrow(z, nat, a_at=f"b@{z.cx}", b_at=f"t@{z.cx}", kind="network")
    sc.arrow(nat, inet, a_at=f"b@{zs[3].cx}", b_at=f"t@{zs[3].cx}", kind="network", step=7)

    bx = 2260
    sc.arrow(operator, bast, a_at=f"b@{bx}", b_at=f"t@{bx}", kind="human", dashed=True, step=8)
    y_s, y_e = bast.bottom + 4, vm.top - 4
    sc.arrow(bast, vm, a_at=f"b@{bx}", b_at=f"t@{bx}", kind="network", step=9, label_at=(ys - 52 - y_s) / (y_e - y_s))

    fb = sc.footer(bottom + 50, BULLETS, flow=FLOW, callout_w=860, flow_title="Numbered flow", flow_cols=2)
    sc.fit(fb)
    return sc
