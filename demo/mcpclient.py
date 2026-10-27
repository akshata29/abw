"""Minimal MCP client + token helpers for testing the gateway, the servers and the demo proofs.

Tokens
  * admin_token(): fresh delegated token for the signed-in operator (re-uses the Azure CLI's own MSAL cache with
    force_refresh, so app-role changes made by identity\\Use-AdminAsPersona.ps1 show up immediately).
  * persona_token(): real persona sign-in (device code, cached per persona) once MFA is enrolled.
Transport
  * rpc(): one JSON-RPC call to a stateless streamable-HTTP MCP endpoint (JSON or SSE reply).

Nothing here prints a raw token; claims() returns only the non-secret claims.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import msal
from msal_extensions import PersistedTokenCache, build_encrypted_persistence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "agent"))
import netfix  # noqa: E402

netfix.install()
GEN = ROOT / "infra" / "generated"
ENTRA = json.loads((GEN / "entra.json").read_text(encoding="utf-8-sig"))
CONFIG = json.loads((GEN / "config.json").read_text(encoding="utf-8-sig"))
APIS = json.loads((GEN / "apis.json").read_text(encoding="utf-8-sig"))
APPS = json.loads((GEN / "apps.json").read_text(encoding="utf-8-sig"))
TENANT = CONFIG["tenantId"]
AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"

GATEWAY = {a["key"]: a["url"] for a in APIS["gatewayApis"]}
GATEWAY["legacy"] = APIS["legacyUrl"]
DIRECT = {name: app["url"] for name, app in APPS["apps"].items()}
API_KEY_FOR_SERVER = {"research": "research", "wall": "wall", "actions": "actions", "private": "private", "vendor": "vendorgw"}


def scope_for(server: str, scope: str = "Tools.Read") -> str:
    return f"api://{ENTRA['apis'][API_KEY_FOR_SERVER[server]]['appId']}/{scope}"


def claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def summarize(token: str) -> dict[str, Any]:
    c = claims(token)
    return {k: c.get(k) for k in ("aud", "azp", "scp", "roles", "oid", "upn", "preferred_username", "exp") if k in c}


_az_app: msal.PublicClientApplication | None = None


def _az_cli_app() -> msal.PublicClientApplication:
    global _az_app
    if _az_app is None:
        persistence = build_encrypted_persistence(str(Path.home() / ".azure" / "msal_token_cache.bin"))
        cache = PersistedTokenCache(persistence)
        _az_app = msal.PublicClientApplication(
            AZURE_CLI_CLIENT_ID, authority=f"https://login.microsoftonline.com/{TENANT}", token_cache=cache
        )
    return _az_app


def admin_token(server: str, scope: str = "Tools.Read", *, force: bool = True) -> str:
    """Delegated token (azp = Azure CLI) for the operator signed in with `az login`."""
    app = _az_cli_app()
    accounts = app.get_accounts(username=CONFIG["operatorUpn"]) or app.get_accounts()
    if not accounts:
        raise RuntimeError("no az CLI account found in the MSAL cache - run `az login`")
    res = app.acquire_token_silent([scope_for(server, scope)], account=accounts[0], force_refresh=force)
    if not res or "access_token" not in res:
        raise RuntimeError(f"token for {server}/{scope} failed: {res}")
    return res["access_token"]


def persona_token(persona: str, server: str, scope: str = "Tools.Read") -> str:
    """Real persona token (public client = abw-test-client, device code, cached under .secrets)."""
    cache_path = ROOT / ".secrets" / f"msal-test-{persona}.json"
    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(
        ENTRA["clients"]["test"]["appId"], authority=f"https://login.microsoftonline.com/{TENANT}", token_cache=cache
    )
    upn = ENTRA["users"][persona]["upn"]
    accounts = app.get_accounts(username=upn)
    res = app.acquire_token_silent([scope_for(server, scope)], account=accounts[0]) if accounts else None
    if not res:
        flow = app.initiate_device_flow(scopes=[scope_for(server, scope)])
        print(f">> {flow['message']}", file=sys.stderr)
        res = app.acquire_token_by_device_flow(flow)
    if "access_token" not in res:
        raise RuntimeError(f"{persona}: {res.get('error')}: {res.get('error_description', '')[:200]}")
    cache_path.write_text(cache.serialize(), encoding="utf-8")
    return res["access_token"]


def _parse(resp: httpx.Response) -> Any:
    ctype = resp.headers.get("content-type", "")
    text = resp.text
    if "text/event-stream" in ctype:
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return None
    try:
        return resp.json()
    except ValueError:
        return text


def rpc(
    url: str,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    token: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> tuple[int, Any, httpx.Headers]:
    hdrs = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "x-abw-request-id": str(uuid.uuid4())}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    hdrs.update(headers or {})
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=hdrs, json=body)
    return resp.status_code, _parse(resp), resp.headers


def call_tool(url: str, tool: str, arguments: dict[str, Any], **kw: Any) -> tuple[int, Any, httpx.Headers]:
    return rpc(url, "tools/call", {"name": tool, "arguments": arguments}, **kw)


def legacy_key() -> str:
    """Primary key of the shared APIM subscription behind /legacy/mcp: the 'POC key' that carries no user.

    Read through ARM with the operator's Azure CLI credential; never printed.
    """
    from urllib.parse import urlparse

    from azure.identity import AzureCliCredential

    apim = urlparse(APIS["legacyUrl"]).hostname.split(".")[0]
    arm = AzureCliCredential(process_timeout=90).get_token("https://management.azure.com/.default").token
    url = (
        f"https://management.azure.com/subscriptions/{CONFIG['subscriptionId']}/resourceGroups/{CONFIG['rgName']}"
        f"/providers/Microsoft.ApiManagement/service/{apim}/subscriptions/{APIS['legacySubscriptionName']}"
        "/listSecrets?api-version=2024-06-01-preview"
    )
    resp = httpx.post(url, headers={"Authorization": f"Bearer {arm}"}, timeout=60)
    resp.raise_for_status()
    return resp.json()["primaryKey"]


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Call an MCP tool through the APIM gateway (or directly) with the operator's delegated token.")
    ap.add_argument("server", choices=["research", "wall", "actions", "private", "vendor", "legacy"])
    ap.add_argument("tool", help="tool name, or 'list' for tools/list")
    ap.add_argument("--args", default="{}", help="JSON arguments")
    ap.add_argument("--scope", default="Tools.Read")
    ap.add_argument("--direct", action="store_true", help="call the ACA ingress directly (only works from inside the VNet)")
    ap.add_argument("--no-token", action="store_true")
    ap.add_argument("--persona", choices=["priya", "wes", "tara", "carla", "ian"], help="real persona sign-in (device code, abw-test-client) instead of the operator's token")
    ap.add_argument("--key", help="APIM subscription key for the legacy API (default: read from ARM)")
    ap.add_argument("--claims", action="store_true", help="print the caller's token claims")
    ap.add_argument("--brief", action="store_true", help="print only the verdict line and the structured result (or the tool names for 'list')")
    ns = ap.parse_args()

    targets = DIRECT if ns.direct else GATEWAY
    if ns.server not in targets:
        print(f"'{ns.server}' is not published at the gateway: it is an internal-only Container App that only the VNet-injected agent can reach (prove it: abw-private).")
        return 2
    url = targets[ns.server]
    token = None
    headers: dict[str, str] = {}
    if ns.server == "legacy":
        headers["Ocp-Apim-Subscription-Key"] = ns.key or legacy_key()
        if ns.claims:
            print("claims: (none - a shared subscription key carries no user, no scope, no role)")
    elif not ns.no_token:
        token = persona_token(ns.persona, ns.server, ns.scope) if ns.persona else admin_token(ns.server, ns.scope)
        if ns.claims:
            print("claims:", json.dumps(summarize(token), default=str))
    started = time.time()
    if ns.tool == "list":
        status, body, hdrs = rpc(url, "tools/list", token=token, headers=headers)
    else:
        status, body, hdrs = call_tool(url, ns.tool, json.loads(ns.args), token=token, headers=headers)
    result = body.get("result") if isinstance(body, dict) and isinstance(body.get("result"), dict) else {}
    sc = result.get("structuredContent") if isinstance(result.get("structuredContent"), dict) else {}
    rid = sc.get("request_id") or (body.get("request_id") if isinstance(body, dict) else None) or hdrs.get("x-abw-request-id") or hdrs.get("request-id")
    decision = sc.get("decision") or ("BLOCKED" if status >= 400 else "")
    reason = sc.get("reason") or (body.get("reason") if isinstance(body, dict) else "") or ""
    verdict = f"  decision={decision}" if decision else ""
    verdict += f" reason={reason}" if reason else ""
    print(f"HTTP {status}  {time.time() - started:.2f}s  request-id={rid}{verdict}")
    if ns.brief:
        if ns.tool == "list":
            names = [t.get("name") for t in result.get("tools", []) if isinstance(t, dict)]
            print("tools:", ", ".join(n for n in names if n) or "(none)")
        else:
            print(json.dumps(sc or body, indent=2, default=str)[:2500])
    else:
        print(json.dumps(body, indent=2, default=str)[:4000])
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(_cli())
