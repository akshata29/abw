"""Read-only probes against the real Azure / Entra / Defender services behind the demo.

The Demo Console's Control Room and "Prove it's real" drawers call these to show - live, from the control
plane - that every component exists and is configured the way the story says. Nothing in this module changes
the tenant: only GET requests (plus the POST-style read APIs for Policy compliance, Log Analytics and the
APIM key listing). Tokens come from the operator's `az login` MSAL cache; no secret is stored or printed.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "infra" / "generated"
sys.path.insert(0, str(ROOT / "demo"))
import mcpclient  # noqa: E402  (installs the DNS retry shim, owns the az-cache MSAL app)

log = logging.getLogger(__name__)

ARM = "https://management.azure.com"
GRAPH = "https://graph.microsoft.com"
LOGS = "https://api.loganalytics.io"


def _load(name: str) -> dict[str, Any]:
    return json.loads((GEN / f"{name}.json").read_text(encoding="utf-8-sig"))


CFG = _load("config")
PLAT = _load("platform")
FOUNDRY = _load("foundry")
APIM = _load("apim")
OBS = _load("observability")
GOV = _load("governance")
ENTRA = _load("entra")
AGENTS = _load("agents")
CONNS = _load("connections")

SUB = CFG["subscriptionId"]
RG = CFG["rgName"]
TENANT = CFG["tenantId"]
RG_ID = f"/subscriptions/{SUB}/resourceGroups/{RG}"
APIM_NAME = APIM["apim"]["name"]
APIC_NAME = APIM["apic"]["name"]
ACCOUNT = FOUNDRY["accountName"]
PROJECT = FOUNDRY["projectName"]
LAW_NAME = PLAT["observability"]["lawName"]
LAW_ID = PLAT["observability"]["lawId"]
LAW_CUSTOMER = PLAT["observability"]["lawCustomerId"]
APPI_NAME = PLAT["observability"]["appiName"]


class ProbeError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------------- tokens + http
_TOKENS: dict[str, tuple[str, float]] = {}
_TOK_LOCK = threading.Lock()
_HTTP = httpx.Client(timeout=45, follow_redirects=True)


def token(resource: str) -> str:
    """Delegated token for `resource`, minted silently from the az CLI's MSAL cache (refresh token, FOCI)."""
    scope = resource.rstrip("/") + "/.default"
    with _TOK_LOCK:
        hit = _TOKENS.get(scope)
        if hit and hit[1] - time.time() > 300:
            return hit[0]
        app = mcpclient._az_cli_app()
        accounts = app.get_accounts(username=CFG["operatorUpn"]) or app.get_accounts()
        if not accounts:
            raise ProbeError("no az CLI account in the MSAL cache - run `az login`")
        res = app.acquire_token_silent([scope], account=accounts[0])
        if not res or "access_token" not in res:
            msg = (res or {}).get("error_description", "") or str(res)
            raise ProbeError(f"could not get a token for {resource}: {msg.splitlines()[0][:200]}")
        _TOKENS[scope] = (res["access_token"], time.time() + int(res.get("expires_in", 3000)))
        return res["access_token"]


def _err_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        err = body.get("error", body)
        if isinstance(err, dict):
            return f"{err.get('code', '')}: {str(err.get('message', ''))[:260]}"
        return str(err)[:260]
    except ValueError:
        return resp.text[:260]


def _retrying(method: str, url: str, **kw: Any) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(3):
        try:
            resp = _HTTP.request(method, url, **kw)
        except httpx.HTTPError as exc:  # transient DNS / TLS blips on flaky networks
            last = exc
            time.sleep(0.6 * (attempt + 1))
            continue
        if resp.status_code in (429, 502, 503, 504) and attempt < 2:
            time.sleep(1.0 + attempt)
            continue
        return resp
    raise ProbeError(f"network error: {type(last).__name__}")


def arm(path: str, api: str, *, method: str = "GET", body: Any = None, **params: Any) -> Any:
    resp = _retrying(
        method,
        f"{ARM}{path}",
        params={"api-version": api, **params},
        headers={"Authorization": f"Bearer {token(ARM)}"},
        json=body,
    )
    if resp.status_code >= 400:
        raise ProbeError(f"ARM {resp.status_code} {_err_text(resp)}")
    ctype = resp.headers.get("content-type", "")
    return resp.json() if "json" in ctype else resp.text


def graph(path: str, *, beta: bool = False, **params: Any) -> Any:
    version = "beta" if beta else "v1.0"
    resp = _retrying(
        "GET",
        f"{GRAPH}/{version}{path}",
        params=params,
        headers={"Authorization": f"Bearer {token(GRAPH)}", "ConsistencyLevel": "eventual"},
    )
    if resp.status_code >= 400:
        raise ProbeError(f"Graph {resp.status_code} {_err_text(resp)}")
    return resp.json()


FOUNDRY_API = "2025-11-15-preview"


def foundry_agents_get(path: str = "", **params: Any) -> Any:
    """Read-only GET on the Foundry agent service (the same data the Control Plane's Assets tab shows)."""
    resp = _retrying(
        "GET",
        f"https://{ACCOUNT}.services.ai.azure.com/api/projects/{PROJECT}/agents{path}",
        params={"api-version": FOUNDRY_API, **params},
        headers={"Authorization": "Bearer " + token("https://ai.azure.com"), "Foundry-Features": "AgentEndpoints=V1Preview"},
    )
    if resp.status_code >= 400:
        raise ProbeError(f"Foundry agents {resp.status_code} {_err_text(resp)}")
    return resp.json()


_RID = re.compile(r"^[0-9A-Fa-f-]{8,64}$")


def la_query(kql: str, hours: float = 24.0) -> list[dict[str, Any]]:
    """Run KQL against the demo workspace (read-only) and return rows as dicts."""
    span = f"PT{int(hours)}H" if hours < 48 else f"P{int(hours // 24)}D"
    resp = _retrying(
        "POST",
        f"{LOGS}/v1/workspaces/{LAW_CUSTOMER}/query",
        headers={"Authorization": f"Bearer {token(LOGS)}", "Content-Type": "application/json"},
        json={"query": kql, "timespan": span},
    )
    if resp.status_code >= 400:
        raise ProbeError(f"Log Analytics {resp.status_code} {_err_text(resp)}")
    tables = resp.json().get("tables", [])
    if not tables:
        return []
    cols = [c["name"] for c in tables[0]["columns"]]
    return [dict(zip(cols, row)) for row in tables[0]["rows"]]


def safe_request_id(value: str) -> str:
    if not _RID.match(value or ""):
        raise ProbeError("request id must be a GUID")
    return value


# ------------------------------------------------------------------------------------------- live gateway state
def _named_value(name: str) -> str:
    data = arm(f"{RG_ID}/providers/Microsoft.ApiManagement/service/{APIM_NAME}/namedValues/{name}", "2024-06-01-preview")
    return str(data.get("properties", {}).get("value", ""))


_ALLOW_ALIASES = {
    mcpclient.ENTRA["clients"]["agent"]["appId"]: "agent",
    mcpclient.ENTRA["clients"]["test"]["appId"]: "test",
    mcpclient.AZURE_CLI_CLIENT_ID: "azcli",
}
BASELINE_ALLOW = {"agent", "test", "azcli"}


def gateway_state() -> dict[str, Any]:
    """Kill switch + client allow-list as APIM holds them right now."""
    deny_raw = _named_value("abw-deny-oids").strip()
    deny = [] if deny_raw.lower() in ("", "none") else [x for x in re.split(r"[,; ]+", deny_raw) if x]
    allow_raw = _named_value("abw-allowed-azp").strip()
    allow_ids = [x for x in re.split(r"[,; ]+", allow_raw) if x]
    allow = sorted({_ALLOW_ALIASES.get(x, x[:8]) for x in allow_ids})
    return {
        "denyList": deny,
        "killEngaged": bool(deny),
        "allowList": allow,
        "allowIsBaseline": set(allow) == BASELINE_ALLOW,
        "operatorRevoked": CFG["operatorOid"] in deny,
    }


_LEGACY: dict[str, str] = {}


def legacy_key() -> str:
    """The shared 'POC key' behind /legacy/mcp, read through ARM (fast path; never printed or logged)."""
    if "k" not in _LEGACY:
        data = arm(
            f"{RG_ID}/providers/Microsoft.ApiManagement/service/{APIM_NAME}/subscriptions/"
            f"{mcpclient.APIS['legacySubscriptionName']}/listSecrets",
            "2024-06-01-preview",
            method="POST",
        )
        _LEGACY["k"] = data["primaryKey"]
    return _LEGACY["k"]


# --------------------------------------------------------------------------------------------------- probes
def _res(pid: str, status: str, headline: str, facts: list[tuple[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "id": pid,
        "status": status,  # ok | warn | fail | na
        "headline": headline,
        "facts": [{"k": k, "v": "" if v is None else str(v)} for k, v in (facts or [])],
        "asOf": time.strftime("%H:%M:%S"),
        **extra,
    }


def _flag(value: Any, want: Any) -> str:
    return "ok" if value == want else "warn"


def probe_foundry() -> dict[str, Any]:
    base = f"{RG_ID}/providers/Microsoft.CognitiveServices/accounts/{ACCOUNT}"
    api = "2025-04-01-preview"
    acct = arm(base, api)
    props = acct.get("properties", {})
    deployments = arm(f"{base}/deployments", api).get("value", [])
    conns = arm(f"{base}/projects/{PROJECT}/connections", api).get("value", [])
    by_auth: dict[str, int] = {}
    for c in conns:
        kind = c.get("properties", {}).get("authType", "?")
        by_auth[kind] = by_auth.get(kind, 0) + 1
    models = ", ".join(f"{d['name']} ({d.get('properties', {}).get('model', {}).get('name', '?')})" for d in deployments)
    agents = ", ".join(f"{k} v{v['version']}" for k, v in AGENTS.items() if isinstance(v, dict) and "version" in v)
    keys_off = props.get("disableLocalAuth") is True
    facts = [
        ("Account", f"{ACCOUNT} ({acct.get('kind')}, {acct.get('location')})"),
        ("Project", PROJECT),
        ("Model deployment", models or "-"),
        ("Local keys (API-key auth)", "OFF - Entra only" if keys_off else "ON"),
        ("Public network access", props.get("publicNetworkAccess", "?")),
        ("Project connections", ", ".join(f"{n} x {k}" for k, n in sorted(by_auth.items())) or "none"),
        ("Agents", agents),
    ]
    status = "ok" if keys_off and by_auth.get("OAuth2", 0) >= 5 else "warn"
    return _res(
        "foundry",
        status,
        f"{len(conns)} project connections: {by_auth.get('OAuth2', 0)} user-OAuth MCP tools, {by_auth.get('CustomKeys', 0)} shared-key (the legacy contrast); account keys {'OFF' if keys_off else 'ON'}",
        facts,
    )


def probe_guardrail() -> dict[str, Any]:
    acct = f"{RG_ID}/providers/Microsoft.CognitiveServices/accounts/{ACCOUNT}"
    data = arm(f"{acct}/raiPolicies/{GOV['guardrailPolicyName']}", "2026-07-15-preview")
    props = data.get("properties", {})
    filters = props.get("contentFilters", []) or []
    rows = []
    for f in filters:
        if f.get("enabled"):
            rows.append(f"{f.get('name')} on {f.get('source')}{' (blocking)' if f.get('blocking') else ''}")
    attached: list[str] = []
    try:
        for a in foundry_agents_get(limit="50").get("data", []):
            d = ((a.get("versions") or {}).get("latest") or {}).get("definition") or {}
            if str((d.get("rai_config") or {}).get("rai_policy_name", "")).endswith(f"/raiPolicies/{data.get('name')}"):
                attached.append(a.get("name", "?"))
    except ProbeError as exc:
        log.info("guardrail attachment: %s", exc)
    baseline = ""
    try:
        deployments = arm(f"{acct}/deployments", "2024-10-01").get("value", [])
        baseline = ", ".join(f"{d['name']}: {d.get('properties', {}).get('raiPolicyName')}" for d in deployments)
    except ProbeError as exc:
        log.info("guardrail deployments: %s", exc)
    facts = [
        ("Guardrail policy", data.get("name")),
        ("Mode", props.get("mode", "?")),
        ("Base policy", props.get("basePolicyName", "?")),
        ("Attached (agent level) to", ", ".join(sorted(attached)) or "no agent"),
        ("Model deployment keeps its own filter", baseline or "?"),
        ("Enabled filters", len(rows)),
    ] + [("  filter", r) for r in rows[:14]]
    shield = any("indirect" in r.lower() for r in rows)
    jail = any("jailbreak" in r.lower() for r in rows)
    return _res(
        "guardrail",
        "ok" if shield and jail and attached else "warn",
        f"{len(rows)} filters on; Jailbreak shield {'on' if jail else 'OFF'}, Indirect-attack (tool output) {'on' if shield else 'OFF'}; attached to {len(attached)} agent(s)",
        facts,
    )


# The MCP servers API Management fronts, keyed by the short name the console uses. The Private MCP server is
# deliberately not here: it is VNet-only and is not published at the gateway.
GATEWAY_SERVERS: dict[str, tuple[str, str]] = {
    "wall": ("abw-mcp-wall", "Wall MCP"),
    "research": ("abw-mcp-research", "Research MCP"),
    "actions": ("abw-mcp-actions", "Trading Actions MCP"),
    "vendor": ("abw-mcp-vendor", "Market Data Vendor MCP"),
    "legacy": ("abw-mcp-legacy", "Legacy POC MCP"),
}
_XML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def gateway_policy(server: str, props: dict[str, Any] | None = None) -> dict[str, Any]:
    """The policy API Management is enforcing on one MCP server right now, read through ARM (API scope).

    There is deliberately no fallback to the repo template: when APIM cannot be read the caller has to say so.
    """
    if server not in GATEWAY_SERVERS:
        raise ProbeError(f"unknown server {server!r}")
    api_name, title = GATEWAY_SERVERS[server]
    base = f"{RG_ID}/providers/Microsoft.ApiManagement/service/{APIM_NAME}/apis/{api_name}"
    if props is None:
        props = arm(base, "2024-06-01-preview").get("properties", {})
    xml = str(arm(f"{base}/policies/policy", "2024-06-01-preview", format="rawxml")).lstrip("\ufeff")
    if "<policies" not in xml:
        raise ProbeError("API Management returned no policy document")
    live = _XML_COMMENT.sub("", xml)  # comments in the stored policy are documentation, not behaviour
    audience = re.search(r"<audience>([^<]+)</audience>", live)
    roles = re.search(r"new string\[\] \{ (.*?) \}", live)
    rate = re.search(r'<rate-limit-by-key calls="(\d+)" renewal-period="(\d+)" counter-key="([^"]*)"', live)
    discovery = re.search(r"var discovery = (true|false)", live)
    return {
        "server": server,
        "title": props.get("displayName") or title,
        "apiName": api_name,
        "path": props.get("path"),
        "subscriptionRequired": bool(props.get("subscriptionRequired")),
        "asOf": time.strftime("%H:%M:%S"),
        "lines": xml.count("\n") + 1,
        "xml": xml,
        "hasJwt": bool(re.search(r"<validate-jwt\b", live)),
        "hasRate": rate is not None,
        "rate": f"{rate.group(1)} calls / {rate.group(2)} s per {'user token' if 'abw-oid' in rate.group(3) else 'shared subscription key'}" if rate else "",
        "audience": audience.group(1) if audience else "",
        "roles": re.findall(r'"([^"]+)"', roles.group(1)) if roles else [],
        "discoveryOpen": (discovery.group(1) == "true") if discovery else None,
        "vendorKey": "x-vendor-key" in live,
        "unrendered": sorted(set(re.findall(r"__[A-Z][A-Z_]+__", xml))),
    }


def probe_apim() -> dict[str, Any]:
    base = f"{RG_ID}/providers/Microsoft.ApiManagement/service/{APIM_NAME}"
    svc = arm(base, "2024-06-01-preview")
    apis = arm(f"{base}/apis", "2024-06-01-preview").get("value", [])
    by_name = {a["name"]: a.get("properties", {}) for a in apis}
    mcp_apis = [a for a in apis if a.get("properties", {}).get("type") == "mcp" and a["name"] != "abw-mcp-legacy"]
    legacy = [a for a in apis if a["name"] == "abw-mcp-legacy"]
    keyless = [a for a in mcp_apis if not a.get("properties", {}).get("subscriptionRequired", True)]
    state = gateway_state()
    governed = [k for k in GATEWAY_SERVERS if k != "legacy"]

    def read(key: str) -> dict[str, Any] | str:
        try:
            return gateway_policy(key, by_name.get(GATEWAY_SERVERS[key][0], {}))
        except ProbeError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=len(governed)) as pool:
        policies = dict(zip(governed, pool.map(read, governed)))
    facts = [
        ("Service", f"{APIM_NAME} ({svc.get('sku', {}).get('name')})"),
        ("Gateway", APIM["apim"]["gatewayUrl"]),
        ("Governed MCP APIs", ", ".join(a["name"] for a in mcp_apis)),
        ("Subscription key required", f"no, on {len(keyless)} of {len(mcp_apis)} governed MCP APIs (Entra token only)"),
        ("Legacy POC API (the contrast)", f"{legacy[0]['name']} - key required, no user identity" if legacy else "not deployed"),
    ]
    sound = 0
    for key in governed:
        pol = policies[key]
        name = GATEWAY_SERVERS[key][0]
        if isinstance(pol, str):
            facts.append((f"Policy on {name}", f"UNREADABLE - {pol[:160]}"))
            continue
        problems = [m for m, bad in (("validate-jwt MISSING", not pol["hasJwt"]), ("rate limit MISSING", not pol["hasRate"]), ("unrendered template tokens", bool(pol["unrendered"]))) if bad]
        sound += not problems
        facts.append((f"Policy on {name}", f"{'; '.join(problems)}" if problems else f"validate-jwt + {pol['rate']}; audience {pol['audience']}; roles {', '.join(pol['roles']) or '-'}"))
    facts += [
        ("Kill switch (deny list)", "ENGAGED" if state["killEngaged"] else "off - nobody revoked"),
        ("Client allow-list", ", ".join(state["allowList"])),
        ("Not behind this gateway", "the Private MCP server (VNet-only): it validates the same Entra token itself and does not read the kill switch"),
    ]
    ok = sound == len(governed) and len(keyless) == len(mcp_apis) and not state["killEngaged"]
    unreadable = [k for k in governed if isinstance(policies[k], str)]
    head = (
        f"could not read the policy on {len(unreadable)} of {len(governed)} servers - nothing is assumed; try Refresh"
        if unreadable
        else f"{len(mcp_apis)} governed MCP APIs: each policy read live - validate-jwt + rate limit on, zero keys; kill switch {'ENGAGED' if state['killEngaged'] else 'off'}"
    )
    return _res("apim", "ok" if ok else "warn", head, facts)


def probe_mcp() -> dict[str, Any]:
    apps = arm(f"{RG_ID}/providers/Microsoft.App/containerApps", "2025-01-01").get("value", [])
    envs = {
        e["name"]: bool((arm(e["id"], "2025-01-01").get("properties", {}).get("vnetConfiguration") or {}).get("internal"))
        for e in (PLAT["caePriv"], PLAT["caePub"])
    }
    rows = []
    vnet_only = 0
    for a in sorted(apps, key=lambda x: x["name"]):
        props = a.get("properties", {})
        env = props.get("environmentId", "").rsplit("/", 1)[-1]
        internal = envs.get(env, False)
        vnet_only += internal
        where = "VNet-only (internal environment, no public IP)" if internal else "public internet (external vendor stand-in)"
        rows.append((a["name"], f"{where}; {props.get('runningStatus', props.get('provisioningState', '?'))}"))
    return _res(
        "mcp",
        "ok" if apps else "warn",
        f"{len(apps)} MCP servers on Container Apps: {vnet_only} reachable only inside the VNet, {len(apps) - vnet_only} public (the vendor)",
        rows,
    )


def probe_data() -> dict[str, Any]:
    st = arm(PLAT["storage"]["id"], "2023-05-01").get("properties", {})
    cs = arm(PLAT["cosmos"]["id"], "2024-11-15").get("properties", {})
    se = arm(PLAT["search"]["id"], "2025-05-01").get("properties", {})
    kv = arm(PLAT["kv"]["id"], "2023-07-01").get("properties", {})
    facts = [
        (f"Storage {PLAT['storage']['name']}", f"shared key {'OFF' if st.get('allowSharedKeyAccess') is False else 'ON'}, public {st.get('publicNetworkAccess')}"),
        (f"Cosmos {PLAT['cosmos']['name']}", f"local (key) auth {'OFF' if cs.get('disableLocalAuth') else 'ON'}, public {cs.get('publicNetworkAccess')}"),
        (f"Search {PLAT['search']['name']}", f"api-key auth {'OFF' if se.get('disableLocalAuth') else 'ON'}, public {se.get('publicNetworkAccess')}"),
        (f"Key Vault {PLAT['kv']['name']}", f"RBAC {'on' if kv.get('enableRbacAuthorization') else 'OFF'}, public {kv.get('publicNetworkAccess')}"),
    ]
    keys_off = st.get("allowSharedKeyAccess") is False and cs.get("disableLocalAuth") is True and se.get("disableLocalAuth") is True
    return _res("data", "ok" if keys_off else "warn", "every data store is Entra-only - no account keys", facts)


def probe_worm() -> dict[str, Any]:
    data = arm(f"{PLAT['storage']['id']}/blobServices/default/containers/worm-audit", "2023-05-01").get("properties", {})
    pol = (data.get("immutabilityPolicy") or {}).get("properties", {})
    state = pol.get("state", "none")
    facts = [
        ("Container", "worm-audit"),
        ("Time-based retention", f"{pol.get('immutabilityPeriodSinceCreationInDays', '?')} day(s)"),
        ("Policy state", state),
        ("Protected append writes", pol.get("allowProtectedAppendWrites")),
        ("Has immutability policy", data.get("hasImmutabilityPolicy")),
        ("Legal hold", data.get("hasLegalHold")),
        ("Honest edge", "Unlocked on purpose so the demo can be torn down; Locked is the SEC 17a-4(f)-style setting"),
    ]
    return _res(
        "worm",
        "ok" if data.get("hasImmutabilityPolicy") else "warn",
        f"append-only audit container with a time-based immutability policy ({state}) - a pattern, not a 17a-4 attestation",
        facts,
    )


def probe_monitor() -> dict[str, Any]:
    ws = arm(LAW_ID, "2023-09-01").get("properties", {})
    rows = la_query("Usage | where TimeGenerated > ago(1d) | summarize MB=round(sum(Quantity),1) by DataType | top 8 by MB desc", 24)
    facts = [
        ("Workspace", f"{LAW_NAME} (retention {ws.get('retentionInDays')} d)"),
        ("App Insights", APPI_NAME),
        ("Workbook", "Agent Wall - Cockpit"),
        ("KQL function pack", ", ".join(OBS.get("functionNames", []))),
    ] + [(f"ingested 24h: {r['DataType']}", f"{r['MB']} MB") for r in rows]
    return _res("monitor", "ok" if rows else "warn", f"{len(rows)} tables received data in the last 24 h; {len(OBS.get('functionNames', []))} KQL functions + Cockpit workbook", facts)


def probe_sentinel() -> dict[str, Any]:
    base = f"{LAW_ID}/providers/Microsoft.SecurityInsights"
    rules = arm(f"{base}/alertRules", "2023-02-01").get("value", [])
    abw = [r for r in rules if "ABW-0" in str(r.get("properties", {}).get("displayName", ""))]
    enabled = [r for r in abw if r.get("properties", {}).get("enabled")]
    incident_rule = next((r for r in rules if r.get("kind") == "MicrosoftSecurityIncidentCreation" and r.get("properties", {}).get("enabled")), None)
    incidents = arm(f"{base}/incidents", "2023-02-01", **{"$top": "50", "$orderby": "properties/createdTimeUtc desc"}).get("value", [])
    facts: list[tuple[str, Any]] = [("Analytics rules ABW-*", f"{len(abw)} ({len(enabled)} enabled)")]
    connector = "unknown"
    try:
        conns = arm(f"{base}/dataConnectors", "2023-02-01").get("value", [])
        asc = next((c for c in conns if c.get("kind") == "AzureSecurityCenter"), None)
        connector = ((asc or {}).get("properties", {}).get("dataTypes", {}).get("alerts", {}).get("state") or "not connected").lower()
    except ProbeError as exc:
        log.info("sentinel connectors: %s", exc)
    facts.append(("Defender for Cloud connector", connector))
    facts.append(("Rule: open incidents from Defender alerts", "enabled" if incident_rule else "not found"))
    received = "unknown"
    try:
        row = (la_query("SecurityAlert | where ProductName != 'Azure Sentinel' | summarize n=count(), lastSeen=max(TimeGenerated)", hours=168) or [{}])[0]
        received = f"{row.get('n', 0)}" + (f", latest {str(row.get('lastSeen'))[:16]}Z" if row.get("n") else " so far - the connector can take a while to deliver the first alert; the alert itself is already in Defender for Cloud")
    except ProbeError as exc:
        log.info("sentinel alert count: %s", exc)
    facts.append(("Defender alerts that reached Sentinel (7 d)", received))
    for i in incidents[:8]:
        p = i.get("properties", {})
        facts.append((f"incident #{p.get('incidentNumber')}", f"{p.get('title')} - {p.get('severity')} / {p.get('status')} ({p.get('additionalData', {}).get('alertsCount', '?')} alerts)"))
    ok = len(enabled) >= 9 and connector == "enabled"
    n_inc = f"{len(incidents)}+" if len(incidents) >= 50 else str(len(incidents))
    return _res("sentinel", "ok" if ok else "warn", f"{len(enabled)} analytics rules enabled; Defender for Cloud connector {connector}; {n_inc} incidents (latest 8 listed)", facts)


def resource_graph(query: str) -> list[dict[str, Any]]:
    out = arm("/providers/Microsoft.ResourceGraph/resources", "2022-10-01", method="POST", body={"subscriptions": [SUB], "query": query, "options": {"resultFormat": "objectArray"}})
    return out.get("data", [])


def probe_policy() -> dict[str, Any]:
    name = GOV["assignmentName"]
    rows = resource_graph(
        "policyresources | where type =~ 'microsoft.policyinsights/policystates' "
        f"| where tostring(properties.policyAssignmentName) =~ '{name}' and tostring(properties.resourceGroup) =~ '{RG}' "
        "| summarize n = count() by state = tostring(properties.complianceState), ref = tostring(properties.policyDefinitionReferenceId)"
    )
    totals: dict[str, int] = {}
    for r in rows:
        totals[r["state"]] = totals.get(r["state"], 0) + int(r["n"])
    bad = sorted({r["ref"] for r in rows if r["state"] == "NonCompliant"})
    facts = [
        ("Initiative", name),
        ("Compliant", totals.get("Compliant", 0)),
        ("Exempt (documented, with expiry)", totals.get("Exempt", 0)),
        ("Non-compliant", f"{totals.get('NonCompliant', 0)} - {', '.join(bad) or 'none'} (the legacy keyed path, by design)"),
        ("Custom definitions", "abw-foundry-no-keyed-connections, abw-foundry-approved-mcp-targets"),
        ("Plus built-ins", "no shared-key / local auth on Storage, Cosmos, Search and Foundry; no public network on Storage, Cosmos, Search; approved tool list; Container Apps env not public"),
    ]
    return _res(
        "policy",
        "ok" if totals.get("Compliant", 0) else "warn",
        f"{totals.get('Compliant', 0)} compliant / {totals.get('Exempt', 0)} exempt / {totals.get('NonCompliant', 0)} non-compliant (by design)",
        facts,
    )


def probe_defender() -> dict[str, Any]:
    plan = arm(f"/subscriptions/{SUB}/providers/Microsoft.Security/pricings/AI", "2024-01-01").get("properties", {})
    ext = {e["name"]: e.get("isEnabled") for e in plan.get("extensions", []) or []}
    alerts: dict[str, dict[str, Any]] = {}
    try:  # the alert list is eventually consistent, so merge two reads and key on the alert id
        for _ in range(2):
            for a in arm(f"/subscriptions/{SUB}/providers/Microsoft.Security/alerts", "2022-01-01").get("value", []):
                alerts[a.get("name", "")] = a
    except ProbeError as exc:
        log.info("defender alerts: %s", exc)
    sample = [a for a in alerts.values() if str(a.get("properties", {}).get("alertDisplayName", "")).startswith("[SAMPLE ALERT]")]
    real = sorted((a for a in alerts.values() if a not in sample), key=lambda a: str(a.get("properties", {}).get("timeGeneratedUtc", "")), reverse=True)
    facts: list[tuple[str, Any]] = [
        ("Defender for AI services plan", plan.get("pricingTier", "?")),
        ("Prompt evidence in alerts", ext.get("AIPromptEvidence")),
        ("Model scanner", ext.get("AIModelScanner")),
        ("Prompts shared with Purview", ext.get("AIPromptSharingWithPurview")),
        ("Real alerts (not samples)", len(real)),
    ]
    for a in real[:4]:
        p = a.get("properties", {})
        facts.append((f"real alert {str(p.get('timeGeneratedUtc', ''))[:16]}Z", f"{p.get('alertDisplayName')} [{p.get('severity')}] on {str(p.get('compromisedEntity') or 'the AI resource').rsplit('/', 1)[-1]}"))
    facts.append(("Sample alerts (portal 'Sample alerts' button)", len(sample)))
    ok = plan.get("pricingTier") == "Standard"
    return _res("defender", "ok" if ok else "warn", f"Defender for AI services: {plan.get('pricingTier')}; {len(real)} real alert(s), {len(sample)} sample alert(s)", facts, alertCount=len(alerts))


def probe_purview() -> dict[str, Any]:
    """Purview: licensing and the Defender-for-AI sharing flag are readable; switching it on and reading it are portal steps."""
    lic = probe_licenses()
    plans = [f for f in lic["facts"] if f["k"].startswith("Purview")]
    ready = sum(1 for f in plans if f["v"] == "Success")
    plan = arm(f"/subscriptions/{SUB}/providers/Microsoft.Security/pricings/AI", "2024-01-01").get("properties", {})
    share = {e["name"]: e.get("isEnabled") for e in plan.get("extensions", []) or []}.get("AIPromptSharingWithPurview")
    facts: list[tuple[str, Any]] = [(f["k"], f["v"]) for f in plans]
    facts.append(("Defender for AI shares prompts with Purview", share))
    facts += [
        ("Turn it on (once)", "Foundry portal -> Operate -> Compliance -> Data security and governance -> your subscription -> 'Powered by Microsoft Purview' (needs the Account Owner role)"),
        ("Where it shows up", "purview.microsoft.com -> Data Security Posture Management -> Discover -> Activity explorer; the older tile is called 'DSPM for AI (classic)' (allow hours to a day for the first data)"),
        ("Audit search", "purview.microsoft.com -> Audit. No API read from here: the audit API needs its own app registration, so this stays a portal view"),
    ]
    return _res("purview", "na", f"Licensed and ready ({ready} of {len(plans)} Purview agent plans provisioned); switching it on and reading it are portal steps", facts)


def probe_licenses() -> dict[str, Any]:
    skus = graph("/subscribedSkus", **{"$select": "skuPartNumber,servicePlans,consumedUnits,prepaidUnits"}).get("value", [])
    want = {
        "AGENT_365": "Agent 365 (registry, governance, MCP gateway)",
        "DEFENDER_FOR_AI": "Defender for AI",
        "ENTRA_ID_PROTECTION_FOR_AGENTS": "Entra ID Protection for agents",
        "ENTRA_CONDITIONAL_ACCESS_FOR_AGENTS": "Conditional Access for agents",
        "AUDIT_FOR_AGENTS": "Purview Audit for agents",
        "DATA_LOSS_PREVENTION_FOR_AGENTS": "Purview DLP for agents",
        "INFORMATION_PROTECTION_FOR_AGENTS": "Purview Information Protection for agents",
        "EDISCOVERY_FOR_AGENTS": "Purview eDiscovery for agents",
        "COMMUNICATION_COMPLIANCE_FOR_AGENTS": "Purview Communication Compliance for agents",
        "INSIDER_RISK_MANAGEMENT_FOR_AGENTS": "Purview Insider Risk for agents",
        "DATA_LIFECYCLE_MANAGEMENT_FOR_AGENTS": "Purview Data Lifecycle (retention) for agents",
    }
    found: dict[str, str] = {}
    sku_names = []
    for s in skus:
        sku_names.append(f"{s['skuPartNumber']} ({s.get('consumedUnits')}/{s.get('prepaidUnits', {}).get('enabled')})")
        for sp in s.get("servicePlans", []):
            if sp["servicePlanName"] in want:
                found[sp["servicePlanName"]] = sp.get("provisioningStatus", "?")
    facts = [("Tenant licence", ", ".join(sku_names))]
    facts += [(label, found.get(key, "not licensed")) for key, label in want.items()]
    ok = found.get("AGENT_365") == "Success" and found.get("DEFENDER_FOR_AI") == "Success"
    return _res("licenses", "ok" if ok else "warn", f"{sum(1 for v in found.values() if v == 'Success')} of {len(want)} agent-security service plans provisioned", facts, plans=found)


def probe_entra() -> dict[str, Any]:
    apps = graph("/applications", **{"$filter": "startswith(displayName,'abw-')", "$select": "id,appId,displayName", "$top": "50"}).get("value", [])
    groups = graph("/groups", **{"$filter": "startswith(displayName,'sg-abw')", "$select": "id,displayName", "$top": "50"}).get("value", [])
    facts = [
        ("Tenant", f"{CFG['tenantDomain']} ({TENANT})"),
        ("Operator (plays Wes + Tara)", CFG["operatorUpn"]),
        ("App registrations", ", ".join(sorted(a["displayName"] for a in apps))),
        ("Security groups", ", ".join(sorted(g["displayName"] for g in groups))),
    ]
    for key, api in ENTRA["apis"].items():
        facts.append((f"api {key}", f"scopes {', '.join(api.get('scopes', []))}; app roles {', '.join(api.get('roles', []))}"))
    return _res("entra", "ok" if len(apps) >= 7 else "warn", f"{len(apps)} app registrations (one per MCP server + agent clients), {len(groups)} wall groups", facts)


def probe_conditional_access() -> dict[str, Any]:
    pols = graph("/identity/conditionalAccess/policies").get("value", [])
    def is_mine(p: dict[str, Any]) -> bool:
        return str(p.get("displayName", "")).upper().startswith("ABW")

    mine = [p for p in pols if is_mine(p)]
    report_only = [p for p in mine if p.get("state") == "enabledForReportingButNotEnforced"]
    facts: list[tuple[str, Any]] = []
    for p in mine:
        cond = p.get("conditions") or {}
        users = cond.get("users") or {}
        who = ["all users"] if "All" in (users.get("includeUsers") or []) else []
        for gid in users.get("includeGroups") or []:
            try:
                who.append("group " + str(graph(f"/groups/{gid}", **{"$select": "displayName"}).get("displayName", gid)))
            except ProbeError:
                who.append(f"group {gid}")
        grant = (p.get("grantControls") or {}).get("builtInControls") or []
        facts += [
            (p["displayName"], p.get("state")),
            ("  applies to", ", ".join(who) or "no users"),
            ("  cloud apps", f"{len((cond.get('applications') or {}).get('includeApplications') or [])} app registrations"),
            ("  excludes", f"{len(users.get('excludeUsers') or [])} user(s) (the operator), {len(users.get('excludeRoles') or [])} admin directory roles, {len(users.get('excludeGroups') or [])} groups" + ("" if users.get("excludeGroups") else " - no break-glass group yet")),
            ("  requires", ", ".join(grant) or "-"),
        ]
    facts += [(p["displayName"], p.get("state")) for p in pols if not is_mine(p)][:8]
    tail = " - REPORT-ONLY: it records what it would require and blocks nothing" if report_only else ""
    return _res("ca", "ok" if mine else "warn", f"{len(pols)} Conditional Access policies in the tenant; {len(mine)} created for this demo{tail}", facts or [("policies", "none")])


def _agent_name(sp: dict[str, Any]) -> str:
    for tag in sp.get("tags") or []:
        if str(tag).startswith("agentName:"):
            return str(tag).split(":", 1)[1]
    return "(the project itself)"


def probe_agent_identity() -> dict[str, Any]:
    """Entra Agent ID: every Foundry agent has its own identity object, separate from the user's token."""
    rows = graph("/servicePrincipals/microsoft.graph.agentIdentity", **{"$select": "id,displayName,accountEnabled,tags", "$top": "100"}).get("value", [])
    prefix = f"{ACCOUNT}-{PROJECT}"
    mine = sorted((r for r in rows if str(r.get("displayName", "")).startswith(prefix)), key=_agent_name)
    facts: list[tuple[str, Any]] = [("Agent identities in the tenant", len(rows)), ("Created for this Foundry project", f"{len(mine)} (one per agent + the project)")]
    facts += [(_agent_name(r), "enabled" if r.get("accountEnabled") else "DISABLED") for r in mine]
    desk = next((r for r in mine if _agent_name(r) == "abw-wall-desk"), None)
    if desk:
        try:
            sponsors = graph(f"/servicePrincipals/{desk['id']}/microsoft.graph.agentIdentity/sponsors").get("value", [])
            facts.append(("abw-wall-desk sponsor (the accountable human)", ", ".join(s.get("userPrincipalName") or s.get("displayName", "?") for s in sponsors) or "none"))
        except ProbeError as exc:
            facts.append(("abw-wall-desk sponsor", f"could not read ({str(exc)[:80]})"))
    try:
        body = foundry_agents_get("/abw-wall-desk")
        facts.append(("Foundry says the agent's identity is", (body.get("instance_identity") or {}).get("principal_id", "?")))
        facts.append(("Published to Microsoft 365 / Teams?", (body.get("agent_endpoint") or {}).get("publish_approval_status", "?")))
    except (ProbeError, ValueError) as exc:
        log.info("foundry agent read: %s", exc)
    ok = desk is not None and desk.get("accountEnabled") is True
    return _res("agentid", "ok" if ok else "warn", f"{len(mine)} Entra agent identities for this project - each agent is its own principal, separate from the user it acts for", facts)


def probe_control_plane() -> dict[str, Any]:
    """Foundry Control Plane (Assets): what each agent can reach, read from the agent definitions themselves."""
    agents = foundry_agents_get(limit="50").get("data", [])
    gateway_host = f"{APIM_NAME}.azure-api.net"
    facts: list[tuple[str, Any]] = []
    for a in sorted(agents, key=lambda a: a.get("name", "")):
        latest = (a.get("versions") or {}).get("latest") or {}
        facts.append((a.get("name", "?"), f"version {latest.get('version', '?')}, model {(latest.get('definition') or {}).get('model', '?')}"))
    desk = next((a for a in agents if a.get("name") == "abw-wall-desk"), None)
    tools = (((desk or {}).get("versions") or {}).get("latest") or {}).get("definition", {}).get("tools") or []
    mcp = [t for t in tools if t.get("type") == "mcp"]
    via_gateway = [t for t in mcp if urlparse(t.get("server_url") or "").hostname == gateway_host]
    direct = [t.get("server_label", "?") for t in mcp if t not in via_gateway]
    approvals: list[str] = []
    for t in mcp:
        req = t.get("require_approval")
        if isinstance(req, dict):
            approvals += [f"{t.get('server_label')}.{n}" for n in (req.get("always") or {}).get("tool_names", [])]
    if mcp:
        facts.append(("abw-wall-desk reaches", f"{len(mcp)} MCP servers: {len(via_gateway)} through the APIM gateway" + (f", {', '.join(direct)} direct (VNet-only)" if direct else "")))
        facts.append(("Human approval required for", ", ".join(approvals) or "nothing"))
        facts.append(("Keys or headers inside a tool definition", "none - each tool uses a project connection" if not any("headers" in t for t in mcp) else "FOUND - review"))
    head = f"{len(agents)} agents in the project" + (f"; abw-wall-desk's {len(via_gateway)} of {len(mcp)} tools go through the gateway" if mcp else "")
    return _res("controlplane", "ok" if agents else "warn", head, facts or [("agents", "none")])


def probe_legacy() -> dict[str, Any]:
    """The shared-key contrast, read live: one keyed API, one keyed connection, an agent tool with no allow-list."""
    apim = f"{RG_ID}/providers/Microsoft.ApiManagement/service/{APIM_NAME}"
    api = arm(f"{apim}/apis/abw-mcp-legacy", "2024-06-01-preview").get("properties", {})
    conns = arm(f"{RG_ID}/providers/Microsoft.CognitiveServices/accounts/{ACCOUNT}/projects/{PROJECT}/connections", "2025-04-01-preview").get("value", [])
    keyed = [c["name"] for c in conns if c.get("properties", {}).get("authType") == "CustomKeys"]
    facts: list[tuple[str, Any]] = [
        ("APIM MCP server abw-mcp-legacy", f"subscription key required = {bool(api.get('subscriptionRequired', True))}, path /{api.get('path', '?')}/mcp"),
        ("Foundry connection (shared key)", ", ".join(keyed) or "none"),
    ]
    sub_name = mcpclient.APIS["legacySubscriptionName"]
    try:
        sub = arm(f"{apim}/subscriptions/{sub_name}", "2024-06-01-preview").get("properties", {})
        scope = "scoped to this one API" if str(sub.get("scope", "")).lower().endswith("/apis/abw-mcp-legacy") else "scope: " + str(sub.get("scope", "?"))
        facts.insert(1, ("APIM subscription (the shared key)", f"{sub_name} - {sub.get('state', '?')}, {scope}"))
    except ProbeError as exc:
        log.info("legacy subscription read: %s", exc)
    tool: dict[str, Any] = {}
    try:
        body = foundry_agents_get("/abw-poc-legacy")
        tools = (((body.get("versions") or {}).get("latest") or {}).get("definition") or {}).get("tools") or []
        tool = next((t for t in tools if t.get("type") == "mcp"), {})
    except (ProbeError, ValueError) as exc:
        log.info("legacy agent read: %s", exc)
    if tool:
        facts += [
            ("abw-poc-legacy tool", f"{tool.get('server_label')} via connection {tool.get('project_connection_id', '?')}"),
            ("Human approval", tool.get("require_approval", "?")),
            ("Tool allow-list", "none - the agent may call every tool the server offers" if not tool.get("allowed_tools") else ", ".join(tool["allowed_tools"])),
        ]
    facts.append(("Who is calling?", "nobody: the key is shared, so the audit row has no user and no role"))
    asdesigned = bool(api.get("subscriptionRequired", False)) and bool(keyed)
    return _res("legacy", "ok" if asdesigned else "warn", "the contrast is in place: one shared key, no user identity, no approval, no tool allow-list" if asdesigned else "the legacy contrast is not deployed as designed", facts)


A365_STEPS = [
    ("Where the inventory lives", "Microsoft 365 admin center -> Agents -> All agents (registry) and Agents -> Tools (gateway tools)"),
    ("Switch that connects the gateway", "Agents -> Settings -> Gateways -> 'Azure API Management service and AI Gateway' (tenant admin, one-time) - no API reads this setting"),
]


def probe_agent365() -> dict[str, Any]:
    """Agent 365: the one part that is readable from here is the role that lets it manage the APIM gateway."""
    sp = graph("/servicePrincipals", **{"$filter": "displayName eq 'Agent 365'", "$select": "id,appId,displayName"}).get("value", [])
    scope = f"{RG_ID}/providers/Microsoft.ApiManagement/service/{APIM_NAME}"
    facts: list[tuple[str, Any]] = [("Agent 365 service principal in this tenant", f"present ({sp[0]['appId']})" if sp else "not found")]
    granted: list[str] = []
    if sp:
        found = arm(f"{scope}/providers/Microsoft.Authorization/roleAssignments", "2022-04-01", **{"$filter": f"principalId eq '{sp[0]['id']}'"}).get("value", [])
        for ra in found:
            role = arm(ra["properties"]["roleDefinitionId"], "2022-04-01")
            granted.append(role.get("properties", {}).get("roleName", "?"))
    facts.append(("Role on the APIM gateway", ", ".join(granted) if granted else "not assigned"))
    facts += A365_STEPS
    facts.append(("Tier note", "APIM Standard v2 = inventory + block/unblock a server; per-tool block and threat protection need the AI Gateway tier (preview)"))
    head = "Gateway role for Agent 365 is granted (verified live); the registry and Tools views are a Microsoft 365 admin center step" if granted else "Agent 365 lives in the Microsoft 365 admin center - portal step"
    return _res("agent365", "na", head, facts)


def probe_apic() -> dict[str, Any]:
    base = f"{RG_ID}/providers/Microsoft.ApiCenter/services/{APIC_NAME}/workspaces/default"
    apis = arm(f"{base}/apis", "2024-03-01").get("value", [])
    facts: list[tuple[str, Any]] = []
    for a in apis[:14]:
        p = a.get("properties", {})
        facts.append((p.get("title") or a["name"], f"{p.get('kind', '?')} - {p.get('lifecycleStage', '?')}"))
    mcp = [a for a in apis if a.get("properties", {}).get("kind") == "mcp"]
    if apis:
        facts.append(("Read this as", "an inventory synced from API Management - it also lists the legacy keyed server and the default Petstore sample. What is approved is enforced by Azure Policy, not by this list"))
    return _res("apic", "ok" if apis else "warn", f"{len(apis)} APIs in the catalog ({len(mcp)} of them MCP servers), synced from API Management", facts or [("apis", "none")])


PROBES: dict[str, Callable[[], dict[str, Any]]] = {
    "foundry": probe_foundry,
    "guardrail": probe_guardrail,
    "apim": probe_apim,
    "mcp": probe_mcp,
    "data": probe_data,
    "worm": probe_worm,
    "monitor": probe_monitor,
    "sentinel": probe_sentinel,
    "policy": probe_policy,
    "defender": probe_defender,
    "licenses": probe_licenses,
    "entra": probe_entra,
    "ca": probe_conditional_access,
    "apic": probe_apic,
    "agentid": probe_agent_identity,
    "agent365": probe_agent365,
    "controlplane": probe_control_plane,
    "purview": probe_purview,
    "legacy": probe_legacy,
}

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
TTL = 120.0


def run_probe(pid: str, *, force: bool = False) -> dict[str, Any]:
    fn = PROBES.get(pid)
    if fn is None:
        return _res(pid, "na", "no live probe for this component - use the portal link")
    with _CACHE_LOCK:
        hit = _CACHE.get(pid)
        if hit and not force and time.time() - hit[0] < TTL:
            return hit[1]
    started = time.time()
    try:
        out = fn()
    except Exception as exc:  # never let one probe take the page down
        log.warning("probe %s failed: %s", pid, exc)
        out = _res(pid, "fail", f"probe failed: {str(exc)[:200]}")
    out["ms"] = int((time.time() - started) * 1000)
    with _CACHE_LOCK:
        _CACHE[pid] = (time.time(), out)
    return out


def run_many(ids: list[str] | None = None, *, force: bool = False) -> dict[str, dict[str, Any]]:
    ids = ids or list(PROBES)
    token(ARM), token(GRAPH), token(LOGS)  # mint serially once, then fan out
    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(zip(ids, pool.map(lambda i: run_probe(i, force=force), ids)))
