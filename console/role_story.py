"""Act 7 role tabs - the story: one tab per person plus the Administrator, each with a positive and a negative beat.

Pure data. The catalog imports this module (so it must not import catalog, e2e or role_tabs); role_tabs calls verify() once
the scenarios are registered, so a beat that points at a missing scenario, the wrong persona or the wrong kind of run is
logged at start-up instead of failing in front of an audience.

The beats are ordinary catalog beats plus three display keys: tab (which tab shows it), tone (pos / neg / warn) and tag
(the pill on the card). Every claim in the text is one the board itself shows, or a portal path marked as not seen.
"""
from __future__ import annotations

from typing import Any

MAX_BEAT_ID = 11  # the console shortens a beat id to 12 characters and Refresh from logs appends one more
TONES = ("pos", "neg", "warn")
SERVERS = ("research", "wall", "actions", "private", "vendor")
PRIVATE_BEAT = "7.2-adm-pri"


# ------------------------------------------------------------------------------------------------ helpers
def _p(scenario: str, who: str) -> dict[str, Any]:
    return {"kind": "e2e", "scenario": scenario, "persona": who}


def _e(scenario: str) -> dict[str, Any]:
    return {"kind": "e2e", "scenario": scenario}


def _a(scenario: str) -> dict[str, Any]:
    return {"kind": "e2e_agent", "scenario": scenario}


def _alt(label: str, eta: str, run: dict[str, Any]) -> dict[str, Any]:
    return {"label": label, "eta": eta, "run": run}


def _beat(bid: str, tab: str, tone: str, tag: str, title: str, say: str, button: str, eta: str, run: dict[str, Any], *, expect: str, tech: str,
          sales: str, prove: list[str], alt: list[dict[str, Any]] | None = None, faq: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    beat: dict[str, Any] = {"id": bid, "tab": tab, "tone": tone, "tag": tag, "title": title, "say": say, "button": button, "eta": eta, "run": run}
    if alt:
        beat["alt"] = alt
    beat.update(expect=expect, tech=tech, sales=sales, prove=prove)
    if faq:
        beat["faq"] = [{"q": q, "a": a} for q, a in faq]
    return beat


def _groups(allowed: list[str], refused: list[str]) -> list[dict[str, Any]]:
    return [{"title": "Allowed - what the role is for", "beats": allowed}, {"title": "Refused - what the role must never do", "beats": refused}]


def _how(name: str) -> str:
    return (f"Each beat here makes one real call with {name}'s own Entra token and reads the answer from every layer. There is no agent and no model in it, so the "
            f"answer is the same every time. Sign in as {name} once (Acting as, key P) before the first run. Conditional Access reads REPORT-ONLY on every board: "
            "it records what it would require and blocks nothing in this demo. The agents run on the Admin tab.")


HOW_ADMIN = ("Every agent beat signs in as the operator, who holds the same data roles as Wes and Tara and no Orion role - the console signs in as one person at a time. "
             "The request enters at the APIM front door and the agent calls each MCP server back through APIM (the private server excepted). The agent chooses its own tools, "
             "so tool order and wording vary between runs and the board follows the tool call each beat is about. Beats that attack the model depend on the model and say so.")

# ------------------------------------------------------------------------------------------------ tabs
TABS: list[dict[str, Any]] = [
    {
        "id": "overview", "label": "Overview", "sub": "Everyone at once", "who": None, "coverage": True,
        "title": "Every person in one run - and what the tabs cover",
        "intro": ("Beat 7.2 makes one allowed and one refused request for every person at once, each with that person's own token. The table below shows which deployed MCP "
                  "server, agent, gateway and log each tab exercises, so nothing built here is left out. Open a tab for the full trace of one person, one beat at a time - "
                  "the same twelve-row board and flow strip as Act 6."),
        "groups": [{"title": "", "beats": ["7.2"]}],
    },
    {
        "id": "priya", "label": "Priya", "sub": "Research analyst", "who": "priya",
        "title": "Priya reads the library - never the deal room, never the trading desk",
        "intro": ("A research analyst. Her token carries Research.Read and MarketData.Read, so the research library and the market-data feed open for her. Nothing else does: "
                  "the gateway refuses the deal room and the trading server before either is asked."),
        "how": _how("Priya"),
        "reach": {"ok": ["m-research", "m-vendor"], "no": ["m-wall", "m-actions", "m-private"], "scope": {}, "design": ["m-private"]},
        "groups": _groups(["7.2-pri-ok"], ["7.2-pri-no"]),
    },
    {
        "id": "wes", "label": "Wes", "sub": "Investment banking", "who": "wes",
        "title": "Wes crosses the wall for Falcon only",
        "intro": ("An investment-banking associate staffed on Project Falcon. Wall.Falcon opens the Falcon deal room and, through his group, Storage accepts his own token on the "
                  "Falcon container. The same role is no key to Orion - the wall server compares each document's deal with the roles in his token - and nothing in his token "
                  "reaches the trading server."),
        "how": _how("Wes"),
        "reach": {"ok": ["m-research", "m-wall", "m-vendor"], "no": ["m-actions", "m-private"], "scope": {"m-wall": "Falcon only"}, "design": ["m-private"]},
        "groups": _groups(["7.2-wes-ok"], ["7.2-wes-no"]),
    },
    {
        "id": "tara", "label": "Tara", "sub": "Equity trader", "who": "tara",
        "title": "Tara trades - except what the restricted list forbids",
        "intro": ("An equity trader. Trade.Execute lets her place orders and Positions.Read lets her read firm positions. She holds no deal-room role, so the wall between the "
                  "trading desk and the deal team holds - and even for her the trading server still refuses a restricted name, after the gateway has let her in."),
        "how": _how("Tara"),
        "reach": {"ok": ["m-research", "m-actions", "m-private", "m-vendor"], "no": ["m-wall"], "scope": {}, "design": ["m-private"]},
        "groups": _groups(["7.2-tar-ok"], ["7.2-tar-no"]),
    },
    {
        "id": "carla", "label": "Carla", "sub": "Compliance", "who": "carla",
        "title": "Carla sees more than she can do",
        "intro": ("A compliance officer. Wall.Falcon, Trade.Read and Positions.Read give her a wide view - the Falcon deal, the restricted list, orders and positions - but she "
                  "holds no Trade.Execute: compliance can look at trading and cannot trade."),
        "how": _how("Carla"),
        "reach": {"ok": ["m-research", "m-wall", "m-actions", "m-private", "m-vendor"], "no": [], "scope": {"m-wall": "Falcon only", "m-actions": "read only"}, "design": ["m-private"]},
        "groups": _groups(["7.2-car-ok"], ["7.2-car-no"]),
    },
    {
        "id": "ian", "label": "Ian", "sub": "Security analyst", "who": "ian",
        "title": "Ian's power is the audit trail, not the data",
        "intro": ("An information-security analyst. He holds no application role on any MCP server, so the gateway refuses every tool call even with a valid token. What he does "
                  "hold is an Azure reader role on the workspace that records every refusal: the power to see what happened, not to do it."),
        "how": _how("Ian"),
        "reach": {"ok": [], "no": ["m-research", "m-wall", "m-actions", "m-private", "m-vendor"], "scope": {}, "design": ["m-private"]},
        "groups": _groups(["7.2-ian-ok"], ["7.2-ian-no"]),
    },
    {
        "id": "admin", "label": "Admin", "sub": "Operator and agents", "who": "operator",
        "title": "The administrator runs every agent, one MCP server at a time",
        "intro": ("The signed-in operator holds the same data roles as Wes and Tara - and no Orion role. All four agents and every MCP server are exercised here, because agent runs "
                  "sign in as the operator: the request enters at the APIM front door, the agent calls each MCP server back through APIM (the private server excepted) and each "
                  "server reads its data as that user. Administrator power is control-plane and audit power; it is no way through the wall."),
        "how": HOW_ADMIN,
        "reach": {"ok": ["m-research", "m-wall", "m-actions", "m-private", "m-vendor"], "no": [], "scope": {"m-wall": "Falcon only"}, "design": [],
                  "gap": ["Orion deal room - nobody holds Wall.Orion"]},
        "groups": [
            {"title": "The governed desk agent, one MCP server at a time", "beats": ["7.2-adm-res", "7.2-adm-wal", "7.2-adm-act", "7.2-adm-pri", "7.2-adm-ven"]},
            {"title": "The other agents: before and under attack", "beats": ["7.2-adm-leg", "7.2-adm-jbk", "7.2-adm-xpi", "7.2-adm-red"]},
            {"title": "Operator extras: audit power, not data power", "beats": ["7.2-adm-aud", "7.2-adm-ori"]},
        ],
    },
]

# ------------------------------------------------------------------------------------------------ beats
BEATS: list[dict[str, Any]] = [
    # ---------------------------------------------------------------------------------------------- Priya
    _beat(
        "7.2-pri-ok", "priya", "pos", "ALLOWED", "Priya researches ACME",
        "Priya, a research analyst, is preparing for a client call and looks up what the firm's research says about ACME. One real request to the research server, made with her own token.",
        "Search the research library", "~5 s", _p("role_priya_ok", "priya"),
        alt=[_alt("Get an ACME quote from the vendor feed", "~5 s", _p("role_priya_ok_quote", "priya"))],
        expect=("Headline ALLOWED END TO END. Entra issues a token that carries Research.Read; the gateway row reads FORWARDED, the MCP row ALLOWED and the data row AI SEARCH AS USER - "
                "Azure AI Search answered under her own identity, limited to public research notes. The guardrail and agent rows read NO MODEL and DIRECT CALL: there is no model in this "
                "request. Refresh from logs joins the gateway and the MCP audit under one request id, and Sentinel stays quiet - silence is the healthy answer. The vendor variation ends "
                "the same way: APIM attaches the vendor's own key from Key Vault and the quote is synthetic, so its data row reads NO AZURE DATA."),
        tech=("The token is Priya's, issued for the research API. APIM validates the signature, the audience and her Research.Read role and forwards the call; the research server takes the "
              "same token on-behalf-of to query Azure AI Search as her. Show it in Azure: Entra admin center -> Enterprise applications -> abw-mcp-research -> Users and groups lists her "
              "Research.Read assignment [path from docs, not seen - the Entra row shows the same roles, read live from the token]; Container Apps -> ca-abw-mcp-research -> Log stream, or the "
              "AbwMcpAudit table in Log Analytics [seen]; the gateway row's Query toggle shows the APIM log line for this request id [seen]."),
        sales="The analyst gets exactly what the job needs, and for every request the platform can show who asked, which layer said yes and what answered.",
        prove=["entra", "apim", "m-research", "data", "monitor"],
    ),
    _beat(
        "7.2-pri-no", "priya", "neg", "REFUSED", "Priya tries the Falcon deal room",
        "The same analyst is curious about a pending deal and asks the deal-room server for the Falcon term sheet. Her role covers research and market data - not the wall.",
        "Ask for the Falcon term sheet", "~5 s", _p("role_priya_no", "priya"),
        alt=[_alt("Try to place an order", "~5 s", _p("role_priya_no_order", "priya"))],
        expect=("Headline STOPPED AT: AI Gateway. Entra still issues a token - Priya is a valid employee - but it carries no role for the wall API, so APIM answers HTTP 403 (403 NO ROLE). "
                "The MCP row reads NOT REACHED and the data row NEVER TOUCHED: the wall server and Storage were never asked, so neither has a log line for this request. Sentinel reads "
                "BELOW THRESHOLD: one refusal is not an incident (rule ABW-006 groups three in 30 minutes for one identity - written, not yet seen firing). The order variation stops at "
                "the gateway for the same reason and writes no order."),
        tech=("A valid token is not a permission. The wall API's policy checks the role claim before anything is forwarded; it is the same policy every governed server uses (audience, role, "
              "client allow-list, kill switch). Show it in Azure: Entra admin center -> Enterprise applications -> abw-mcp-wall -> Users and groups: Priya is not listed [path from docs, "
              "not seen]; APIM -> Monitoring -> Logs, or the gateway row's Query toggle: the 403 with reason missing_role [seen]; Container Apps -> ca-abw-mcp-wall -> Log stream: nothing "
              "for this request id [seen path]."),
        sales="The deal room is closed to her at the front gate - not by a page that asks her to behave - and the refusal is logged with her name.",
        prove=["entra", "apim", "m-wall", "data", "sentinel"],
    ),
    # ---------------------------------------------------------------------------------------------- Wes
    _beat(
        "7.2-wes-ok", "wes", "pos", "ALLOWED", "Wes reads the Falcon term sheet",
        "Wes, an investment-banking associate staffed on Project Falcon, opens the Falcon deal document. His wall crossing is in his token.",
        "Read the Falcon term sheet", "~5 s", _p("role_wes_ok", "wes"),
        alt=[_alt("Search the Falcon documents", "~5 s", _p("role_wes_ok_search", "wes"))],
        expect=("Headline ALLOWED END TO END. His token carries Wall.Falcon: the gateway row reads FORWARDED, the MCP row ALLOWED - the wall server compared the document's deal with the roles "
                "in his token and found Falcon - and the data row RBAC ALLOWED: Azure Storage accepted Wes's own token on the Falcon container. Refresh from logs adds the Storage row with "
                "auth=OAuth: a token, not a key. Sentinel stays quiet. The search variation queries Azure AI Search with his token for Falcon documents only (a search for another project "
                "would be refused). Sign Wes in once (Acting as, key P) before this runs as him."),
        tech=("The wall server swaps Wes's token for a Storage token (on-behalf-of), so Storage sees Wes, not a service principal. Two separate things let him in: his Wall.Falcon app role "
              "opens the wall server, and his membership of the group sg-abw-wall-falcon - which holds Storage Blob Data Reader on the wall-falcon container only - opens Storage. Each "
              "layer decides on its own. Show it in Azure: Storage account -> Containers -> wall-falcon -> Access Control (IAM) -> Check access -> Wes [seen path]; the wall-orion container "
              "has no person or group assignment, only service identities [seen]; Storage -> Monitoring -> Logs (StorageBlobLogs) shows the read as auth=OAuth after Refresh from logs [seen]."),
        sales="He is cleared for one deal, and the platform proves it in three places - the token, the tool and the storage account - each deciding for itself.",
        prove=["entra", "apim", "m-wall", "data", "monitor"],
        faq=[("How do I prove Storage saw Wes and not the server?",
              "Click Refresh from logs: the Storage row shows auth=OAuth and the same request id as the gateway and MCP rows. In the portal, Storage -> Containers -> wall-falcon -> Access "
              "Control (IAM) -> Check access -> Wes lists the Reader role he gets through sg-abw-wall-falcon. A key would show auth=SharedKey - and this account has key access disabled.")],
    ),
    _beat(
        "7.2-wes-no", "wes", "neg", "REFUSED", "Wes asks for Orion",
        "The same associate asks for a document from Project Orion, a deal he is not staffed on. His Falcon crossing does not cover it.",
        "Ask for an Orion document", "~5 s", _p("role_wes_no", "wes"),
        alt=[_alt("Ask the trading server about ZYNX", "~5 s", _p("role_wes_no_trade", "wes"))],
        expect=("Headline STOPPED AT: MCP server. Unlike Priya, Wes gets past the gateway (FORWARDED): Wall.Falcon is a valid role on the wall API. The MCP row then reads WALL: NOT CROSSED - "
                "the wall server compares the deal in the document id with the roles in his token and finds none for Orion - and the data row reads NEVER TOUCHED: Storage was not asked. "
                "Sentinel rule ABW-001 (information-barrier violation attempt, High) should raise an incident in about 5-15 minutes; Refresh from logs looks for it, and it was seen live for "
                "the same refusal made by the operator. The trading variation is refused at the gateway - he holds no trading role - and writes nothing."),
        tech=("The refusal is deterministic code in the wall server, run before any Storage call: project_not_in_token_roles. It reads only the claims in the token, so it needs no lookup and "
              "cannot be talked around. A second control stands behind it: no person or group holds a role on the wall-orion container, so Storage would refuse Wes too. Show it in Azure: "
              "Container Apps -> ca-abw-mcp-wall -> Log stream, or AbwMcpAudit: Decision deny, Reason project_not_in_token_roles, UserUpn Wes [seen]; Defender portal -> Incidents -> "
              "'Information-barrier violation attempt (Wall MCP)' [seen]."),
        sales="Being cleared for one deal is not being cleared for the building: the check is at the tool, per deal, from the token.",
        prove=["m-wall", "data", "sentinel", "monitor"],
    ),
    # ---------------------------------------------------------------------------------------------- Tara
    _beat(
        "7.2-tar-ok", "tara", "pos", "ALLOWED", "Tara places an order",
        "Tara, an equity trader, places a one-share order for ACME, a name that is not on the restricted list. One real call to the trading server with her own token.",
        "Place a 1-share ACME order", "~6 s", _p("role_tara_ok", "tara"),
        alt=[_alt("Only check the restricted list (writes nothing)", "~5 s", _p("role_tara_ok_check", "tara"))],
        expect=("Headline ALLOWED END TO END. Her token carries Trade.Execute: the gateway row reads FORWARDED, the MCP row ALLOWED and the data row COSMOS AS USER - the order was written to "
                "Cosmos DB with Tara's own token, so it carries her identity, and the outcome names the order id. Each click creates one synthetic order (1 share of ACME) in the demo database. "
                "The check variation answers the read-only question 'is ACME restricted?' and writes nothing; its data row reads SERVER IDENTITY because the restricted list is firm-wide "
                "reference data read with the server's own identity. Sentinel stays quiet. Sign Tara in once (Acting as, key P) before this runs as her."),
        tech=("Two checks in order. APIM requires a valid role on the actions API; the actions server then requires Trade.Execute for place_order and looks the ticker up on the restricted list "
              "before it writes. The write to Cosmos DB is made on-behalf-of Tara, so the stored order and Cosmos RBAC both name her. Show it in Azure: Entra admin center -> Enterprise "
              "applications -> abw-mcp-actions -> Users and groups: Trade.Execute assigned to Tara [path from docs, not seen]; Container Apps -> ca-abw-mcp-actions -> AbwMcpAudit [seen]; "
              "Cosmos DB account -> Data Explorer -> the orders container: the new order [path from docs, not seen]."),
        sales="A trade carries the trader's identity from the first click to the database row, so 'who placed this?' has exactly one answer.",
        prove=["entra", "apim", "m-actions", "data", "monitor"],
    ),
    _beat(
        "7.2-tar-no", "tara", "neg", "REFUSED", "Tara tries a restricted name",
        "The same trader tries to buy 100 shares of ZYNX, a name the firm has put on its restricted list. She may trade - not this name.",
        "Buy 100 shares of ZYNX", "~6 s", _p("role_tara_no", "tara"),
        alt=[_alt("Ask the deal room for Falcon", "~5 s", _p("role_tara_no_wall", "tara"))],
        expect=("Headline STOPPED AT: MCP server. The gateway lets her in (FORWARDED: she holds Trade.Execute); the MCP row reads RESTRICTED LIST - the actions server looked ZYNX up and refused "
                "before writing - and the data row reads NO ORDER WRITTEN: the orders container was never touched, so no order exists. Sentinel reads BELOW THRESHOLD (one refusal). The "
                "deal-room variation shows the other wall: a trader holds no deal-room role, so APIM refuses at the gateway and the wall server and Storage are never asked."),
        tech=("The restricted list is enforced inside the actions server, after the gateway and after any human approval - a compliance control no approval can override. The list sits in Cosmos DB "
              "and is read with the server's own identity; the order write that did not happen would have used Tara's. Show it in Azure: Container Apps -> ca-abw-mcp-actions -> AbwMcpAudit: "
              "Decision deny, Reason restricted_list [seen]; Cosmos DB -> Data Explorer -> orders: no ZYNX order exists [path from docs, not seen]."),
        sales="The firm's own rule outranks a trader's wish, and the refusal is evidence: who tried, when, on which name.",
        prove=["m-actions", "data", "sentinel", "monitor"],
    ),
    # ---------------------------------------------------------------------------------------------- Carla
    _beat(
        "7.2-car-ok", "carla", "pos", "ALLOWED", "Carla checks the restricted list",
        "Carla, a compliance officer, asks whether ZYNX is on the restricted list - exactly what her job needs, and nothing that changes anything.",
        "Check ZYNX on the restricted list", "~5 s", _p("role_carla_ok", "carla"),
        alt=[_alt("Review the Falcon deal", "~5 s", _p("role_carla_ok_wall", "carla"))],
        expect=("Headline ALLOWED END TO END. Trade.Read is enough for the actions API and for this read-only tool: FORWARDED, ALLOWED, and the data row reads SERVER IDENTITY - the restricted list "
                "is firm-wide reference data, read with the server's own identity. The outcome says whether ZYNX is on the list. The Falcon variation shows her Wall.Falcon crossing at work: "
                "the wall server allows the document and Storage accepts her own token (RBAC ALLOWED). Sign Carla in once (Acting as, key P) before this runs as her."),
        tech=("Her token carries Trade.Read, which gets her through the actions API; check_restricted_list is a read tool, so the server asks for nothing more. Her Falcon access works like Wes's: "
              "the Wall.Falcon app role opens the wall server and her membership of sg-abw-wall-falcon opens the Falcon container in Storage. Show it in Azure: Entra admin center -> Enterprise "
              "applications -> abw-mcp-actions -> Users and groups: Trade.Read assigned to Carla [path from docs, not seen]; Container Apps -> ca-abw-mcp-actions -> AbwMcpAudit [seen]."),
        sales="Compliance gets a wide, read-oriented view built from roles - no shared admin account and no spreadsheet of screenshots.",
        prove=["entra", "apim", "m-actions", "data", "monitor"],
    ),
    _beat(
        "7.2-car-no", "carla", "neg", "REFUSED", "Carla tries to place an order",
        "The same compliance officer tries to place an order. Compliance can look at trading; it may not trade.",
        "Try to place an order", "~6 s", _p("role_carla_no", "carla"),
        alt=[_alt("Ask for an Orion document", "~5 s", _p("role_carla_no_orion", "carla"))],
        expect=("Headline STOPPED AT: MCP server. The gateway lets her in (FORWARDED: Trade.Read is a valid role on the actions API); the actions server then refuses place_order - the MCP row reads "
                "NO ROLE FOR THIS TOOL because her token has no Trade.Execute - and the data row reads NEVER TOUCHED: nothing was written. It is the same reason code the gateway gives Priya, one "
                "layer deeper: the tool checks the role itself. The Orion variation is refused by the wall server (WALL: NOT CROSSED): she is crossed on Falcon only, and nobody in the demo "
                "holds Orion. Sentinel reads BELOW THRESHOLD for the order refusal; the Orion refusal is the ABW-001 pattern."),
        tech=("Two layers can each say no on one role model. APIM checks that the token holds some role on the API; the actions server checks the role the tool needs (Trade.Execute for place_order) "
              "from the same token. Show it in Azure: Container Apps -> ca-abw-mcp-actions -> AbwMcpAudit: Decision deny, Reason missing_role, with her roles listed [from the server's code and its unit test; this reason has not appeared in the live log - Carla has not signed in]; Entra admin center -> "
              "Enterprise applications -> abw-mcp-actions -> Users and groups: she holds Trade.Read, not Trade.Execute [path from docs, not seen]."),
        sales="Separation of duties by role: the person who watches the trading desk cannot be the person who trades.",
        prove=["entra", "apim", "m-actions", "data", "sentinel"],
    ),
    # ---------------------------------------------------------------------------------------------- Ian
    _beat(
        "7.2-ian-ok", "ian", "pos", "AUDIT", "Ian reads the audit trail",
        "Ian, an information-security analyst, answers a regulator's question: what did the platform refuse in the last day, and for whom? His access is to the evidence, not to the data.",
        "Read the audit trail", "~10 s", _p("role_ian_audit", "ian"),
        expect=("Headline AUDIT TRAIL READABLE - NO DATA ROLE. The Entra row shows Ian's token with no app role on any MCP API; the agent, gateway and MCP rows read n/a (the audit trail is not behind "
                "the AI gateway and is not an MCP tool); the monitor row reads REFUSALS IN THE LOG with the count by layer for the last 24 hours; and the data row reads LOG ANALYTICS RBAC - the "
                "Azure roles on his group, read live, none of them a data role. A table lists the latest refusals with the request id that joins every layer. Sentinel stays quiet: reading the "
                "trail is an allowed action."),
        tech=("Reading logs is an Azure role on the workspace (Log Analytics Reader), a different permission from an MCP role - which is why Ian can read the trail and cannot read a single deal. "
              "The console runs the query with the operator's sign-in; the proof of Ian's own access is his role assignments, read live from Azure RBAC. Show it in Azure: sign in to the portal as "
              "Ian, open the Log Analytics workspace log-abw-demo-eus2-001 -> Logs and run AbwDenials(24h) [portal step - the query was seen, Ian's own portal sign-in was not]; the role assignments "
              "of the group sg-abw-infosec under Access control (IAM) [read live by the console; the portal path was not seen]."),
        sales="The security team can see everything the platform refused, by whom and at which layer - and cannot use that power to read one deal document.",
        prove=["monitor", "entra", "data", "sentinel"],
        faq=[("Why does the console run the query with the operator's sign-in?",
              "It cannot open a browser session as Ian, so it runs the same KQL with the operator's Azure sign-in and shows Ian's real role assignments, read live, as the proof of what he may do. "
              "The portal step is yours: sign in as Ian, open the workspace's Logs and run AbwDenials(24h).")],
    ),
    _beat(
        "7.2-ian-no", "ian", "neg", "REFUSED", "Ian tries the research data",
        "The same analyst - valid token, security badge - asks the research server for data. His role is the audit trail, not the data.",
        "Ask for research data", "~5 s", _p("role_ian_no", "ian"),
        alt=[_alt("Ask for a vendor quote", "~5 s", _p("role_ian_no_vendor", "ian")), _alt("Ask for a Falcon document", "~5 s", _p("role_ian_no_wall", "ian"))],
        expect=("Headline STOPPED AT: AI Gateway. Entra issues a valid token, but it carries no app role on any MCP API, so APIM answers HTTP 403 (403 NO ROLE); the MCP row reads NOT REACHED and the "
                "data row NEVER TOUCHED. The vendor variation shows the vendor's key is never even attached; the wall variation shows the deal room closed in the same way. Sentinel reads BELOW "
                "THRESHOLD for a single refusal (rule ABW-006 groups three in 30 minutes for one identity - written, not yet seen firing)."),
        tech=("A token without a role is a visitor's badge: it proves who he is and nothing else, and APIM checks the role claim before anything is forwarded. Show it in Azure: Entra admin center -> "
              "Enterprise applications -> abw-mcp-research -> Users and groups: Ian is not listed [path from docs, not seen]; APIM -> Monitoring -> Logs, or the gateway row's Query toggle: the 403 "
              "with reason missing_role [seen]."),
        sales="Security staff see the evidence, not the data: separation of duties between the people who watch the system and the people who use it.",
        prove=["entra", "apim", "m-research", "sentinel"],
    ),
    # ---------------------------------------------------------------------------------------------- Admin: the governed desk agent
    _beat(
        "7.2-adm-res", "admin", "pos", "ALLOWED", "The agent researches ACME",
        "The administrator asks the governed desk agent, abw-wall-desk, what the firm's research says about ACME. The request enters at the APIM front door; the agent calls the research server back through APIM.",
        "Ask the agent about ACME research", "15-60 s", _a("role_admin_research"),
        expect=("Headline ALLOWED END TO END. Entra shows the operator's sign-in; the guardrail row reads SCREENED; the agent row reads AGENT RAN, names the tool calls the agent made and says the run "
                "entered through the APIM agent front door; the gateway row reads FORWARDED, the MCP row ALLOWED and the data row AI SEARCH AS USER - the gateway, the server and Azure AI Search "
                "each saw the user, not the agent. The Agent 365 row is a portal step. Refresh from logs adds the agent's spans from Application Insights; Sentinel and Defender stay quiet. "
                "The agent chooses its own tools, so the exact calls vary between runs."),
        tech=("The user's token goes through the front door unchanged: APIM validates it, counts tokens against the user's hourly budget and forwards it to Foundry. The agent's tool connection uses OAuth "
              "identity passthrough, so each tool call carries the same user's token back to APIM, and the research server uses it on-behalf-of for Azure AI Search. Show it in Azure: Foundry portal "
              "-> your project -> Build -> Agents -> abw-wall-desk [Agents page seen; Traces tab from docs]; APIM -> Monitoring -> Logs: the front door's rows have Server 'agents' [seen]; Container "
              "Apps -> ca-abw-mcp-research -> AbwMcpAudit [seen]."),
        sales="The agent is one more identity on the same wall: the gateway, the tool and the data all decide from the user's token - the model is never the authority.",
        prove=["apim", "foundry", "guardrail", "m-research", "data", "monitor"],
    ),
    _beat(
        "7.2-adm-wal", "admin", "pos", "ALLOWED", "The agent reads the Falcon deal",
        "The administrator asks the agent for the Project Falcon terms. The agent lists its wall crossings, searches the deal documents and reads the document - each call through APIM, each decided again from the user's token.",
        "Ask the agent for Falcon", "25-60 s", _a("role_admin_wall"),
        expect=("Headline ALLOWED END TO END - the same run as Act 6 beat 6.8, here as the wall's allowed case. The agent row lists the tool calls it made (the wall crossings, a search and the document "
                "read among them); the board follows the document read, so after Refresh from logs the Storage data-plane row reads auth=OAuth: Storage saw the user's own identity, not the agent's. "
                "The Orion deal room stays closed for this run - the operator holds no Wall.Orion role."),
        tech=("The wall server reads Storage on-behalf-of the user, so Azure RBAC decides on the person, not on the agent. The agent has its own Entra identity (the agent row says so), but the data plane "
              "never sees it - Storage's logs name the user. Show it in Azure: Storage account -> Containers -> wall-falcon -> Access Control (IAM) -> Check access -> the operator shows Storage Blob Data "
              "Reader through sg-abw-wall-falcon [seen path]; Storage -> Monitoring -> Logs shows the read as auth=OAuth [seen]; the registry view of the agent is the Microsoft 365 admin center step on the "
              "Agent 365 row [not seen]."),
        sales="The agent can only open what the person asking could open - the same wall whether a human or an agent is the one reading.",
        prove=["foundry", "agentid", "apim", "m-wall", "data", "monitor"],
    ),
    _beat(
        "7.2-adm-act", "admin", "pos", "ALLOWED", "The agent places an order (with approval)",
        "The administrator asks the agent to check whether ACME is restricted and, if it is not, buy 25 shares. Foundry holds the run for an approval on place_order; the console approves it.",
        "Ask the agent to place an order", "30-90 s", _a("role_admin_actions"),
        expect=("Headline ALLOWED END TO END. The agent row names the restricted-list check and place_order; the console approved the Foundry approval request, as a desk supervisor would. Gateway "
                "FORWARDED, MCP ALLOWED, data COSMOS AS USER - the order is in Cosmos DB under the administrator's identity. Each run writes one synthetic order (25 shares of ACME). The approval is "
                "separate from the restricted list: even an approved order for a restricted name is refused by the server (Tara's refused beat shows it)."),
        tech=("Foundry marks place_order as needing approval, so the run pauses until someone approves it. The approval is not the control that matters: the actions server still looks the ticker up on the "
              "restricted list and checks Trade.Execute from the user's token before it writes, on-behalf-of the user. Show it in Azure: Foundry portal -> Build -> Agents -> abw-wall-desk -> Traces: the "
              "approval request [path from docs, not seen]; Cosmos DB account -> Data Explorer -> the orders container: the new order [path from docs, not seen]; Container Apps -> ca-abw-mcp-actions -> "
              "AbwMcpAudit [seen]."),
        sales="Two controls on one action: a human approval for the act, and a compliance rule that no approval can override.",
        prove=["foundry", "apim", "m-actions", "data", "monitor"],
    ),
    _beat(
        PRIVATE_BEAT, "admin", "pos", "ALLOWED", "The agent reads firm positions (private server)",
        "The administrator asks the agent for the rates desk's firm positions and a counterparty's credit headroom - data that must never leave the internal network.",
        "Ask the agent for positions", "15-60 s", _a("role_admin_private"),
        expect=("Headline ALLOWED END TO END, with the gateway row reading NOT BEHIND APIM - on purpose. The private server has no public endpoint: the agent's subnet calls it directly and the server "
                "validates the user's token itself (it checks the Positions.Read role). The data row reads COSMOS AS USER: the positions were read with the user's own token. After Refresh from logs the "
                "monitor row shows one request id across the Foundry agent and the MCP server only - APIM is not on this path."),
        tech=("The honest edge of this design, and the reason the person tabs show the private server as designed, not run: a laptop cannot reach it, only the agent runtime inside the virtual network can. "
              "APIM's kill switch does not apply here because the server validates the token itself, so a revoked user keeps access until the token expires; the production fix is an internal APIM in "
              "front of it or a server-side deny list. Show it in Azure: Container Apps environment (internal) and ca-abw-mcp-private [seen]; AbwMcpAudit [seen]."),
        sales="Some systems of record should never sit behind a public gateway at all. The model works there too: the server checks the user itself.",
        prove=["foundry", "m-private", "data", "monitor"],
        faq=[("Why do the person tabs show the private server as designed, not run?",
              "It is reachable only from inside the virtual network. The agent's subnet is on it; a laptop or the console is not, so a person cannot call it directly. Only an agent run reaches it, "
              "and agent runs use the operator's sign-in. The role model says Tara and Carla (Positions.Read) would be allowed and the others refused; this beat proves the mechanism live.")],
    ),
    _beat(
        "7.2-adm-ven", "admin", "pos", "ALLOWED", "The agent quotes ACME from the vendor feed",
        "The administrator asks the agent for the latest ACME quote from the external market-data vendor. The vendor's API key sits in Key Vault; neither the person nor the agent ever holds it.",
        "Ask the agent for a quote", "15-60 s", _a("role_admin_vendor"),
        expect=("Headline ALLOWED END TO END. The gateway validated the user's token and attached the vendor's key; the MCP row reads ALLOWED and the data row NO AZURE DATA - the answer is a synthetic "
                "quote, not Azure data. The vendor server runs in the public Container Apps environment on purpose, as a stand-in for a third-party SaaS."),
        tech=("APIM validates the user's token and role (MarketData.Read), removes the user's Authorization header and adds the vendor's key from a Key Vault-backed named value before forwarding - so the "
              "third party never sees the user's token and the user and the agent never see the key. Show it in Azure: APIM -> Named values -> abw-vendor-key (a Key Vault reference; the value stays "
              "hidden) [path from docs, not seen]; Container Apps -> ca-abw-mcp-vendor -> Log stream [seen]; the gateway row's Query toggle for Server 'vendor' [seen]."),
        sales="A third-party tool gets a key the user never sees and never gets the user's token: the gateway holds the secret, and the user's role decides who may ask.",
        prove=["apim", "m-vendor", "foundry", "monitor"],
    ),
    # ---------------------------------------------------------------------------------------------- Admin: the other agents
    _beat(
        "7.2-adm-leg", "admin", "warn", "BEFORE", "The before picture: the legacy PoC agent",
        "The same question about Project Orion, asked of the first proof-of-concept agent - the one built with a shared key. Nothing in its path knows who is asking.",
        "Run the legacy agent", "20-40 s", _a("role_admin_legacy"),
        expect=("Headline NOTHING CHECKED WHO WAS ASKING. The Entra row reads IDENTITY DROPPED: the user signed in, but this agent reaches its tool with a shared key. The gateway row reads KEY ONLY (APIM "
                "checks the key and nothing else), the MCP row NO USER CHECK and the data row SERVICE PRINCIPAL - Storage saw the legacy server's own managed identity, which can read every container. "
                "Sentinel rule ABW-003 is written for exactly this and should raise an incident in about 5-15 minutes; Refresh from logs looks for it. Every governed board above is measured against "
                "this picture."),
        tech=("The legacy agent (abw-poc-legacy) is left outside the front door on purpose. It uses the Foundry connection mcp-legacy-key, which sends an APIM subscription key (sub-abw-legacy-poc) to the "
              "legacy MCP API. A key identifies an application, not a person, so there is no user to check, rate-limit or revoke. Show it in Azure: APIM -> Subscriptions: besides the built-in master, the "
              "only key is sub-abw-legacy-poc [path from docs, not seen]; APIM -> APIs -> MCP Servers -> abw-mcp-legacy [path from docs, not seen]; Foundry portal -> Build -> Agents -> abw-poc-legacy "
              "[Agents page seen]."),
        sales="This is what most proofs of concept look like on day one: it works, and nobody can say who did what. The rest of the tab is the fix.",
        prove=["m-legacy", "apim", "data", "foundry", "sentinel"],
        faq=[("Why is the legacy agent not behind the front door?",
              "On purpose: it is the before picture - a shared key, no user, direct. Every governed agent beat enters at the front door; this one shows what that replaces.")],
    ),
    _beat(
        "7.2-adm-jbk", "admin", "warn", "ATTACK", "A jailbreak stopped by the guardrail",
        "A standard DAN-style prompt tells the governed agent to ignore its rules, reveal its system prompt and skip the wall checks.",
        "Send the jailbreak", "~10 s", _a("role_admin_jailbreak"),
        expect=("Headline STOPPED AT: Guardrails - the same run as Act 6 beat 6.6. Prompt Shields refuses the prompt before the model produces a word: the agent row says no tool was called, and the gateway, "
                "the MCP server and the data read as not reached. Sentinel rule ABW-008 reads the failed run from the logs, and Defender for Cloud raised a real alert for an earlier jailbreak test in this "
                "tenant (alerts are slower than logs and not guaranteed). If the guardrail does not fire, the headline says GUARDRAIL DID NOT FIRE and shows what caught the request instead."),
        tech=("The guardrail abw-agent-guardrails is attached to the agent. It is a classifier: it has stopped this prompt every time it was tried in this tenant, so say that and not 'always'. Show it in "
              "Azure: Foundry portal -> Operate -> Compliance -> Guardrails -> abw-agent-guardrails [path from docs, not seen]; Defender for Cloud -> Security alerts [path from docs, not seen - one real "
              "alert for an earlier jailbreak test was read through the API]."),
        sales="The first wall catches the obvious attack before the model sees it - and when it does not, the next three layers still decide.",
        prove=["guardrail", "foundry", "defender", "sentinel"],
    ),
    _beat(
        "7.2-adm-xpi", "admin", "warn", "ATTACK", "A poisoned tool result (indirect injection)",
        "The vendor feed carries a planted desk notice telling the agent to pull an Orion document and place a restricted order. The shielded agent reads it as data - or acts on it, and the wall refuses.",
        "Poison the feed", "30-90 s", _a("role_admin_xpia"),
        expect=("One of four outcomes, each labelled honestly. TOOL OUTPUT SHIELD: the guardrail caught the injected instruction in the tool result and ended the run. THE WALL HELD: the model tried the "
                "injected calls and the gateway, the MCP server or the data refused every one for the signed-in user. GUARDRAIL DID NOT FIRE: the model never acted on the notice, so nothing was attacked - "
                "run it again. AN INJECTED ACTION WAS NOT REFUSED: a failure - stop and investigate. The tool-output shield is a preview control that fires on only some identical runs; the wall behind it "
                "holds either way. The console tries up to four times."),
        tech=("The shielded red-team agent (abw-wall-desk-redteam-shielded) has Prompt Shields with the indirect-attack shield; the vendor MCP server's headline feed carries the planted notice (Act 4.3). "
              "The injected actions - an Orion document and an order for ZYNX - are refused for the signed-in user: no Orion role, and a restricted name. Show it in Azure: Foundry portal -> Guardrails "
              "-> abw-agent-guardrails (Indirect attack on) [path from docs, not seen]; AbwMcpAudit rows for the injected calls [seen]."),
        sales="An attacker can write text into a data feed. Only the controls outside the model decide what the agent may do.",
        prove=["guardrail", "foundry", "apim", "m-wall", "m-actions", "sentinel"],
        faq=[("What if the model ignores the planted notice?",
              "Then nothing was attacked, and the board says so - it never reports an attack that did not happen. Run it again: models are not deterministic. The wall's refusals do not depend on the model.")],
    ),
    _beat(
        "7.2-adm-red", "admin", "warn", "ATTACK", "No guardrail at all: the wall alone",
        "The same poisoned feed, read by an agent with no guardrail attached. Nothing screens the model - the wall behind it is the only control.",
        "Run the unshielded agent", "30-90 s", _a("role_admin_redteam"),
        expect=("THE WALL HELD: with no guardrail at all, the model followed the planted notice and tried the injected calls - and the wall refused every one (the board shows the refusal and the layer that "
                "made it). Or MODEL IGNORED THE NOTICE: the model read the poisoned headlines and never acted on them, so there was nothing to refuse - run it again, models are not deterministic. Or AN "
                "INJECTED ACTION WAS NOT REFUSED: stop and investigate the wall."),
        tech=("The agent abw-wall-desk-redteam has no guardrail attached, by design. The injected calls ask for an Orion document and an order for ZYNX; the signed-in user holds no Orion role and may not trade "
              "a restricted name, so the wall server and the actions server refuse them. Up to three attempts per click. Show it in Azure: Foundry portal -> Build -> Agents -> abw-wall-desk-redteam: no "
              "guardrail attached [Agents page seen]; AbwMcpAudit [seen]."),
        sales="Assume the model will be fooled. The design question is what stands behind it.",
        prove=["foundry", "guardrail", "apim", "m-wall", "m-actions", "sentinel"],
    ),
    # ---------------------------------------------------------------------------------------------- Admin: operator extras
    _beat(
        "7.2-adm-aud", "admin", "pos", "AUDIT", "The administrator reads the audit trail",
        "The administrator has the same question as Ian - what did the platform refuse in the last day - and answers it in one place. Administrator power is audit power.",
        "Read the audit trail", "~10 s", _e("role_admin_audit"),
        expect=("Headline AUDIT POWER, NOT DATA POWER. The Entra row lists the roles in the operator's token for every MCP API, read live - the same data roles as Wes and Tara, and no Wall.Orion; the monitor "
                "row counts the platform's refusals by layer; the data row reads AUDIT POWER ONLY: the administrator can read the evidence, and the roles in the token are still the only way to the data."),
        tech=("A real Log Analytics query with the operator's Azure sign-in (AbwDenials, last 24 hours). Everything the other tabs prove appears here in one table - every refusal by layer, principal and request "
              "id. Show it in Azure: Log Analytics workspace log-abw-demo-eus2-001 -> Logs [seen]; the workbook 'Agent Wall - Cockpit' [seen]."),
        sales="One pane for the evidence - and the administrator's rights end at the evidence.",
        prove=["monitor", "sentinel", "entra"],
    ),
    _beat(
        "7.2-adm-ori", "admin", "neg", "REFUSED", "The administrator asks for Orion",
        "The platform administrator - who can see everything in the Azure portal - asks the deal-room server for an Orion document.",
        "Ask for an Orion document", "~5 s", _e("role_admin_orion"),
        expect=("Headline STOPPED AT: MCP server. The gateway accepts the token (FORWARDED) and the wall server refuses: WALL: NOT CROSSED - nobody in the demo, the administrator included, holds Wall.Orion. "
                "The data row reads NEVER TOUCHED. Sentinel rule ABW-001 (information-barrier violation attempt, High) was seen live for this exact refusal when the beat was tested: Refresh from logs finds "
                "the incident."),
        tech=("A direct call with the operator's own token: the same deterministic check as Wes's refused beat. Administrator rights in Azure are control-plane and audit rights; they do not grant an Entra app "
              "role, so the token carries no Orion crossing and the wall server refuses before Storage. Show it in Azure: Container Apps -> ca-abw-mcp-wall -> AbwMcpAudit [seen]; Defender portal -> "
              "Incidents -> 'Information-barrier violation attempt (Wall MCP)' [seen]."),
        sales="An administrator is not a master key. The people who run the platform cannot read the deal room either - which is exactly what a regulator asks.",
        prove=["m-wall", "data", "sentinel", "entra", "monitor"],
    ),
]

# ------------------------------------------------------------------------------------------------ coverage
LEGEND = [
    {"state": "allowed", "label": "Allowed", "text": "a real request ended end to end"},
    {"state": "refused", "label": "Refused", "text": "a real request was stopped by a control"},
    {"state": "both", "label": "Both", "text": "an allowed beat and a refused beat"},
    {"state": "before", "label": "Before", "text": "the legacy contrast: nothing checks who is asking"},
    {"state": "design", "label": "Designed, not run", "text": "the role model predicts it; a person cannot reach this server directly"},
]

_GW = "at the gateway (no role)"
_WALL = "at the wall server (no Orion role)"


def _governed(server: str) -> tuple[tuple[str, str, str], ...]:
    return (("frontdoor", "allowed", ""), (server, "allowed", ""), ("agent:abw-wall-desk", "allowed", ""))


# scenario -> what it exercises: (artifact id, allowed | refused | before, where it stopped)
SCENARIO_COVERS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "role_priya_ok": (("research", "allowed", ""),),
    "role_priya_ok_quote": (("vendor", "allowed", ""),),
    "role_priya_no": (("wall", "refused", _GW),),
    "role_priya_no_order": (("actions", "refused", _GW),),
    "role_wes_ok": (("wall", "allowed", ""),),
    "role_wes_ok_search": (("wall", "allowed", ""),),
    "role_wes_no": (("wall", "refused", _WALL),),
    "role_wes_no_trade": (("actions", "refused", _GW),),
    "role_tara_ok": (("actions", "allowed", ""),),
    "role_tara_ok_check": (("actions", "allowed", ""),),
    "role_tara_no": (("actions", "refused", "at the actions server (restricted list)"),),
    "role_tara_no_wall": (("wall", "refused", _GW),),
    "role_carla_ok": (("actions", "allowed", ""),),
    "role_carla_ok_wall": (("wall", "allowed", ""),),
    "role_carla_no": (("actions", "refused", "at the actions server (no Trade.Execute)"),),
    "role_carla_no_orion": (("wall", "refused", _WALL),),
    "role_ian_audit": (("audit", "allowed", ""),),
    "role_ian_no": (("research", "refused", _GW),),
    "role_ian_no_vendor": (("vendor", "refused", _GW),),
    "role_ian_no_wall": (("wall", "refused", _GW),),
    "role_admin_research": _governed("research"),
    "role_admin_wall": _governed("wall"),
    "role_admin_actions": _governed("actions"),
    "role_admin_private": _governed("private"),
    "role_admin_vendor": _governed("vendor"),
    "role_admin_legacy": (("legacy", "before", ""), ("agent:abw-poc-legacy", "before", "")),
    "role_admin_jailbreak": (("agent:abw-wall-desk", "refused", "by Prompt Shields"),),
    "role_admin_xpia": (("agent:abw-wall-desk-redteam-shielded", "refused", "by the guardrail or the wall"),),
    "role_admin_redteam": (("agent:abw-wall-desk-redteam", "refused", "by the wall"),),
    "role_admin_audit": (("audit", "allowed", ""),),
    "role_admin_orion": (("wall", "refused", _WALL),),
}

# Every deployed artifact the tabs are meant to cover (id, kind, label, sub, architecture node)
ARTIFACTS: list[dict[str, Any]] = [
    {"id": "frontdoor", "kind": "APIM API", "label": "Agent front door", "sub": "abw-agent-frontdoor", "node": "apim",
     "also": "Beat 7.1 tests its refusals (no token, wrong audience); beat 7.4 its token budget and rate limit."},
    {"id": "research", "kind": "MCP server", "label": "Research", "sub": "AI Search - public notes", "node": "m-research"},
    {"id": "wall", "kind": "MCP server", "label": "Wall (deal rooms)", "sub": "Blob Storage - Falcon and Orion", "node": "m-wall"},
    {"id": "actions", "kind": "MCP server", "label": "Trading actions", "sub": "Cosmos DB - orders", "node": "m-actions"},
    {"id": "private", "kind": "MCP server", "label": "Private", "sub": "Cosmos DB - positions; VNet-only, not behind APIM", "node": "m-private"},
    {"id": "vendor", "kind": "MCP server", "label": "Vendor (external)", "sub": "third-party feed; key held by APIM", "node": "m-vendor"},
    {"id": "legacy", "kind": "MCP server", "label": "Legacy PoC", "sub": "shared key - the before picture", "node": "m-legacy"},
    {"id": "agent:abw-wall-desk", "kind": "Agent", "label": "abw-wall-desk", "sub": "the governed desk agent", "node": "foundry"},
    {"id": "agent:abw-wall-desk-redteam-shielded", "kind": "Agent", "label": "abw-wall-desk-redteam-shielded", "sub": "red team, guardrail on", "node": "foundry"},
    {"id": "agent:abw-wall-desk-redteam", "kind": "Agent", "label": "abw-wall-desk-redteam", "sub": "red team, no guardrail", "node": "foundry"},
    {"id": "agent:abw-poc-legacy", "kind": "Agent", "label": "abw-poc-legacy", "sub": "the legacy PoC agent", "node": "foundry"},
    {"id": "audit", "kind": "Logs", "label": "Audit trail", "sub": "Log Analytics - AbwDenials", "node": "monitor"},
]

_PRIVATE_NOTE = ("Designed, not run: the private server is reachable only from the agent's subnet, so a person cannot call it directly. "
                 "The Admin column runs it live through the agent - click to open that beat.")
DESIGNED: dict[tuple[str, str], tuple[str, str]] = {
    ("private", "priya"): ("refused", "Priya holds no Positions.Read role, so the private server would refuse her. " + _PRIVATE_NOTE),
    ("private", "wes"): ("refused", "Wes holds no Positions.Read role, so the private server would refuse him. " + _PRIVATE_NOTE),
    ("private", "tara"): ("allowed", "Tara holds Positions.Read, so the private server would allow her. " + _PRIVATE_NOTE),
    ("private", "carla"): ("allowed", "Carla holds Positions.Read, so the private server would allow her. " + _PRIVATE_NOTE),
    ("private", "ian"): ("refused", "Ian holds no application role, so the private server would refuse him. " + _PRIVATE_NOTE),
}


def _phrase(result: str, where: str) -> str:
    if result == "allowed":
        return "Allowed"
    if result == "refused":
        return f"Refused {where}".strip()
    return "The before picture"


def _state(results: list[str]) -> str:
    if "allowed" in results and "refused" in results:
        return "both"
    if "refused" in results:
        return "refused"
    if "before" in results:
        return "before"
    return "allowed"


def coverage() -> dict[str, Any]:
    """The tab x artifact table, built from the beats themselves so it cannot drift from what the tabs run."""
    cols = [{"id": t["id"], "label": t["label"], "who": t["who"]} for t in TABS if t.get("who")]
    live: dict[tuple[str, str], dict[str, list[str]]] = {}
    for beat in BEATS:
        for run in [beat["run"]] + [a["run"] for a in beat.get("alt", [])]:
            for artifact, result, where in SCENARIO_COVERS.get(run["scenario"], ()):
                cell = live.setdefault((artifact, beat["tab"]), {"results": [], "beats": [], "phrases": []})
                for key, value in (("results", result), ("beats", beat["id"]), ("phrases", _phrase(result, where))):
                    if value not in cell[key]:
                        cell[key].append(value)
    rows: list[dict[str, Any]] = []
    for art in ARTIFACTS:
        cells: dict[str, dict[str, Any]] = {}
        for col in cols:
            key = (art["id"], col["id"])
            if key in live:
                cell = live[key]
                cells[col["id"]] = {"state": _state(cell["results"]), "beats": cell["beats"], "note": "; ".join(cell["phrases"])}
            elif key in DESIGNED:
                expect, note = DESIGNED[key]
                cells[col["id"]] = {"state": "design", "expect": expect, "beats": [PRIVATE_BEAT], "note": note}
        rows.append(dict(art, cells=cells))
    return {"cols": cols, "rows": rows, "legend": LEGEND}


# ------------------------------------------------------------------------------------------------ verification
def _structure(tabs: dict[str, dict[str, Any]], nodes: dict[str, Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for beat in BEATS:
        bid = beat["id"]
        if bid in seen:
            out.append(f"beat id {bid} is used twice")
        seen.add(bid)
        if len(bid) > MAX_BEAT_ID:
            out.append(f"beat id {bid} is longer than {MAX_BEAT_ID} characters (the console shortens job ids to 12 and Refresh from logs adds one)")
        if beat["tone"] not in TONES or not beat["tag"]:
            out.append(f"beat {bid} needs a tone ({', '.join(TONES)}) and a tag")
        if beat["tab"] not in tabs:
            out.append(f"beat {bid} names an unknown tab {beat['tab']}")
        for key in ("title", "say", "button", "eta", "expect", "tech", "sales"):
            if not str(beat.get(key) or "").strip():
                out.append(f"beat {bid} has no {key}")
        if nodes is not None:
            out.extend(f"beat {bid} proves an unknown node {n}" for n in beat["prove"] if n not in nodes)
    grouped: set[str] = set()
    for tab in tabs.values():
        for group in tab["groups"]:
            for bid in group["beats"]:
                grouped.add(bid)
                beat = next((b for b in BEATS if b["id"] == bid), None)
                if beat is None and not (tab["id"] == "overview" and bid == "7.2"):
                    out.append(f"tab {tab['id']} lists beat {bid}, which does not exist")
                elif beat is not None and beat["tab"] != tab["id"]:
                    out.append(f"tab {tab['id']} lists beat {bid}, which belongs to tab {beat['tab']}")
    out.extend(f"beat {b['id']} is in no tab group" for b in BEATS if b["id"] not in grouped)
    if nodes is not None:
        for tab in tabs.values():
            reach = tab.get("reach") or {}
            names = reach.get("ok", []) + reach.get("no", []) + reach.get("design", [])
            out.extend(f"tab {tab['id']} reach names an unknown node {n}" for n in names if n not in nodes)
        out.extend(f"artifact {a['id']} names an unknown node {a['node']}" for a in ARTIFACTS if a["node"] not in nodes)
    return out


def _scenarios(tabs: dict[str, dict[str, Any]], scenarios: dict[str, dict[str, Any]]) -> tuple[list[str], dict[str, set[str]]]:
    out: list[str] = []
    by_tab: dict[str, set[str]] = {}
    for beat in BEATS:
        tab = tabs.get(beat["tab"]) or {}
        for run in [beat["run"]] + [a["run"] for a in beat.get("alt", [])]:
            sid = str(run.get("scenario") or "")
            by_tab.setdefault(beat["tab"], set()).add(sid)
            spec = scenarios.get(sid)
            if spec is None:
                out.append(f"beat {beat['id']} runs scenario {sid}, which is not registered")
                continue
            if run.get("kind") not in ("e2e", "e2e_agent") or bool(spec.get("agent")) != (run.get("kind") == "e2e_agent"):
                out.append(f"beat {beat['id']}: scenario {sid} cannot run as kind {run.get('kind')}")
            polarity, tone = spec.get("polarity"), beat["tone"]
            if (polarity == "positive") != (tone == "pos"):
                out.append(f"beat {beat['id']}: scenario {sid} is {polarity} but the beat is tone {tone}")
            if tab.get("who") == "operator":
                if not spec.get("actor"):
                    out.append(f"beat {beat['id']}: Admin scenario {sid} does not name its actor")
            elif tab.get("who"):
                if spec.get("persona") != "fixed" or spec.get("who") != tab["who"] or run.get("persona") != tab["who"]:
                    out.append(f"beat {beat['id']}: scenario {sid} is not pinned to {tab['who']}")
    used = set().union(*by_tab.values()) if by_tab else set()
    out.extend(f"scenario {s} is registered but no beat runs it" for s in sorted(scenarios) if s.startswith("role_") and s not in used)
    out.extend(f"scenario {s} has no coverage entry" for s in sorted(used) if s not in SCENARIO_COVERS)
    out.extend(f"coverage names scenario {s}, which is not registered" for s in SCENARIO_COVERS if s not in scenarios)
    known = {a["id"] for a in ARTIFACTS}
    out.extend(f"coverage for {s} names unknown artifact {c[0]}" for s, covers in SCENARIO_COVERS.items() for c in covers if c[0] not in known)
    return out, by_tab


def _roles(tabs: dict[str, dict[str, Any]], by_tab: dict[str, set[str]], cases: list[dict[str, Any]], personas_mod: Any) -> list[str]:
    out: list[str] = []

    def can(who: str, server: str) -> bool | None:
        try:
            return bool(personas_mod.can_use(who, server))
        except Exception:  # noqa: BLE001 - a role file that cannot be read must not hide every other problem
            return None

    for tab in tabs.values():
        who, reach = tab.get("who"), tab.get("reach") or {}
        if not who or who == "operator":
            continue
        for server in SERVERS:
            node = f"m-{server}"
            listed_ok, listed_no = node in reach.get("ok", []), node in reach.get("no", [])
            if listed_ok == listed_no:
                out.append(f"tab {tab['id']} must list {node} as exactly one of ok / no")
            held = can(who, server)
            if held is not None and held != listed_ok:
                out.append(f"tab {tab['id']}: {node} is listed {'ok' if listed_ok else 'no'} but {who} {'holds a role' if held else 'holds no role'} on it")
        if ("m-private" in reach.get("design", [])) != (("private", tab["id"]) in DESIGNED):
            out.append(f"tab {tab['id']}: the designed-not-run marker for the private server disagrees with the coverage table")
        designed = DESIGNED.get(("private", tab["id"]))
        held = can(who, "private")
        if designed and held is not None and (designed[0] == "allowed") != held:
            out.append(f"tab {tab['id']}: the private server is designed as {designed[0]} but {who} {'holds' if held else 'holds no'} Positions.Read")
    for case in cases:
        who = case.get("who")
        if not who:
            continue
        sid, want = case["id"], case["want"]
        tab_id = next((t["id"] for t in tabs.values() if t.get("who") == who), None)
        if tab_id is None or sid not in by_tab.get(tab_id, set()):
            out.append(f"case {sid} is not run by a beat on {who}'s tab")
        result = "allowed" if want["verdict"] == "allowed" else "refused"
        if not any(c[0] == case["server"] and c[1] == result for c in SCENARIO_COVERS.get(sid, ())):
            out.append(f"case {sid} is {result} on {case['server']} but the coverage entry says otherwise")
        held = can(who, case["server"])
        if held is None:
            continue
        at_gateway = want["verdict"] == "denied" and want.get("wall") == 1
        if (result == "allowed" or not at_gateway) != held:
            out.append(f"case {sid} expects {'a role on' if held is False else 'no role on'} {case['server']}, which disagrees with {who}'s roles")
    return out


def verify(scenarios: dict[str, dict[str, Any]], cases: list[dict[str, Any]], personas_mod: Any, nodes: dict[str, Any] | None = None) -> list[str]:
    """Everything the role tabs promise, checked against the registered scenarios and the persona roles. Returns the problems (empty = consistent); never raises."""
    try:
        tabs = {t["id"]: t for t in TABS}
        out: list[str] = [] if len(tabs) == len(TABS) else ["tab ids are not unique"]
        out += _structure(tabs, nodes)
        found, by_tab = _scenarios(tabs, scenarios)
        out += found
        out += _roles(tabs, by_tab, cases, personas_mod)
        table = coverage()
        for row in table["rows"]:
            if not any(c["state"] != "design" for c in row["cells"].values()):
                out.append(f"artifact {row['id']} is not exercised live by any tab")
            for col, cell in row["cells"].items():
                out.extend(f"coverage cell {row['id']}/{col} points at unknown beat {b}" for b in cell["beats"] if all(b != x["id"] for x in BEATS))
        return out
    except Exception as exc:  # noqa: BLE001 - verification is advisory: it must never stop the console from starting
        return [f"role story verification failed: {exc}"]
