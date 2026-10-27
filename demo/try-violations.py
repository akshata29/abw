"""Try to break the platform controls: attempt non-compliant changes in the demo resource group and record what Azure Policy says.

Every attempt is a real ARM ``PUT`` against ``rg-abw-demo-eus2-001`` using throw-away resource names. The expected answer is
HTTP 403 ``RequestDisallowedByPolicy`` naming the assignment, the control (initiative reference) and its effect (BLOCKED).

Some tenants carry an organisation baseline (another assignment, usually at a management group) whose *Modify* policies rewrite
unsafe settings - shared keys, local auth, public network access - on the way in. Azure Policy evaluates Modify before Deny, so the
request succeeds but the resource is created safe. That is recorded as CORRECTED and passes only when (1) the stored resource no
longer carries the unsafe settings that were sent and (2) this initiative still flags the original request body (policy evaluation
API, nothing created). An unsafe resource that survives is ALLOWED and fails. Every resource an attempt creates is deleted.
A compliant control attempt proves the policy is not a blanket deny.

    python demo\\try-violations.py                    # run every attempt
    python demo\\try-violations.py --only keys,mcp    # run a subset (id substrings)
    python demo\\try-violations.py --list
    python demo\\try-violations.py --json             # machine readable result on stdout

Evidence is written to demo\\evidence\\try-violations-<utc stamp>.json.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import secrets
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEN = ROOT / "infra" / "generated"
EVIDENCE = ROOT / "demo" / "evidence"
sys.path.insert(0, str(ROOT / "src" / "agent"))

import netfix  # noqa: E402

netfix.install()

import requests  # noqa: E402
from azure.identity import AzureCliCredential  # noqa: E402

ARM = "https://management.azure.com"


def _load(name: str) -> dict[str, Any]:
    return json.loads((GEN / name).read_text(encoding="utf-8-sig"))


CFG = _load("config.json")
FOUNDRY = _load("foundry.json")
GOV = _load("governance.json")
SUB = CFG["subscriptionId"]
RG = CFG["rgName"]
LOC = CFG["location"]
SEARCH_LOC = CFG["searchLocation"]
TAGS = CFG["tags"]
RG_BASE = f"/subscriptions/{SUB}/resourceGroups/{RG}"
PROJECT = f"{FOUNDRY['accountId']}/projects/{FOUNDRY['projectName']}"
APPROVED_TARGET = GOV["approvedMcpEndpoints"][0].replace("/*", "/mcp")

_cred = AzureCliCredential(process_timeout=90)


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + _cred.get_token(ARM + "/.default").token}


def _rand() -> str:
    return secrets.token_hex(3)


def attempts() -> list[dict[str, Any]]:
    """Every attempt: id, human title, the control it should trip, the ARM resource id, api-version and body."""
    r = _rand()
    storage = f"stabwtry{r}"
    cosmos = f"cosmos-abw-try-{r}"
    search = f"srch-abw-try-{r}"
    vault = f"kv-abw-try-{r}"
    registry = f"crabwtry{r}"
    ai = f"aif-abw-try-{r}"
    return [
        {
            "id": "storage-shared-key",
            "title": "Create a storage account with shared-key access and public network access",
            "controls": ["storage-shared-key-disabled", "storage-no-public"],
            "unsafe": {"properties.allowSharedKeyAccess": True, "properties.publicNetworkAccess": "Enabled"},
            "resource": f"{RG_BASE}/providers/Microsoft.Storage/storageAccounts/{storage}",
            "api": "2023-05-01",
            "body": {
                "location": LOC,
                "kind": "StorageV2",
                "sku": {"name": "Standard_LRS"},
                "tags": TAGS,
                "properties": {"allowSharedKeyAccess": True, "publicNetworkAccess": "Enabled"},
            },
        },
        {
            "id": "cosmos-local-auth",
            "title": "Create a Cosmos DB account with key authentication and a public endpoint",
            "controls": ["cosmos-local-auth-disabled", "cosmos-no-public"],
            "unsafe": {"properties.disableLocalAuth": False, "properties.publicNetworkAccess": "Enabled"},
            "resource": f"{RG_BASE}/providers/Microsoft.DocumentDB/databaseAccounts/{cosmos}",
            "api": "2024-05-15",
            "body": {
                "location": LOC,
                "kind": "GlobalDocumentDB",
                "tags": TAGS,
                "properties": {
                    "databaseAccountOfferType": "Standard",
                    "disableLocalAuth": False,
                    "publicNetworkAccess": "Enabled",
                    "locations": [{"locationName": "East US 2", "failoverPriority": 0}],
                },
            },
        },
        {
            "id": "search-local-auth",
            "title": "Create an AI Search service with API keys and a public endpoint",
            "controls": ["search-local-auth-disabled", "search-no-public"],
            "unsafe": {"properties.disableLocalAuth": False, "properties.publicNetworkAccess": "enabled"},
            "resource": f"{RG_BASE}/providers/Microsoft.Search/searchServices/{search}",
            "api": "2023-11-01",
            "body": {
                "location": SEARCH_LOC,
                "sku": {"name": "basic"},
                "tags": TAGS,
                "properties": {"disableLocalAuth": False, "publicNetworkAccess": "enabled"},
            },
        },
        {
            "id": "keyvault-access-policies",
            "title": "Create a Key Vault with legacy access policies instead of Azure RBAC",
            "controls": ["keyvault-rbac"],
            "unsafe": {"properties.enableRbacAuthorization": False},
            "resource": f"{RG_BASE}/providers/Microsoft.KeyVault/vaults/{vault}",
            "api": "2023-07-01",
            "body": {
                "location": LOC,
                "tags": TAGS,
                "properties": {
                    "tenantId": CFG["tenantId"],
                    "sku": {"family": "A", "name": "standard"},
                    "enableRbacAuthorization": False,
                    "accessPolicies": [],
                },
            },
        },
        {
            "id": "acr-admin-user",
            "title": "Create a container registry with the shared admin user enabled",
            "controls": ["acr-admin-disabled"],
            "unsafe": {"properties.adminUserEnabled": True},
            "resource": f"{RG_BASE}/providers/Microsoft.ContainerRegistry/registries/{registry}",
            "api": "2023-07-01",
            "body": {"location": LOC, "sku": {"name": "Basic"}, "tags": TAGS, "properties": {"adminUserEnabled": True}},
        },
        {
            "id": "foundry-local-auth",
            "title": "Create a Foundry (AI Services) account with API keys switched on",
            "controls": ["ai-local-auth-disabled"],
            "unsafe": {"properties.disableLocalAuth": False},
            "resource": f"{RG_BASE}/providers/Microsoft.CognitiveServices/accounts/{ai}",
            "api": "2025-06-01",
            "body": {
                "location": LOC,
                "kind": "AIServices",
                "sku": {"name": "S0"},
                "identity": {"type": "SystemAssigned"},
                "tags": TAGS,
                "properties": {"customSubDomainName": ai, "disableLocalAuth": False, "publicNetworkAccess": "Enabled"},
            },
        },
        {
            "id": "foundry-keyed-connection",
            "title": "Add a Foundry project connection that stores an API key",
            "controls": ["foundry-no-keyed-connections"],
            "resource": f"{PROJECT}/connections/abw-try-keyed",
            "api": "2025-06-01",
            "body": {
                "properties": {
                    "category": "RemoteTool",
                    "target": APPROVED_TARGET,
                    "authType": "ApiKey",
                    "credentials": {"key": "not-a-real-key"},
                    "isSharedToAll": False,
                }
            },
        },
        {
            "id": "foundry-unapproved-mcp",
            "title": "Add a Foundry remote-tool (MCP) connection that points at an unapproved server",
            "controls": ["foundry-approved-mcp-targets"],
            "resource": f"{PROJECT}/connections/abw-try-unapproved-mcp",
            "api": "2025-06-01",
            "body": {
                "properties": {
                    "category": "RemoteTool",
                    "target": "https://mcp.shadow-vendor.example.com/mcp",
                    "authType": "None",
                    "isSharedToAll": False,
                }
            },
        },
        {
            "id": "positive-control",
            "title": "Positive control: a compliant storage account (no shared key, no public access) is allowed",
            "controls": [],
            "expect": "allowed",
            "resource": f"{RG_BASE}/providers/Microsoft.Storage/storageAccounts/stabwok{r}",
            "api": "2023-05-01",
            "body": {
                "location": LOC,
                "kind": "StorageV2",
                "sku": {"name": "Standard_LRS"},
                "tags": TAGS,
                "properties": {
                    "allowSharedKeyAccess": False,
                    "publicNetworkAccess": "Disabled",
                    "allowBlobPublicAccess": False,
                    "minimumTlsVersion": "TLS1_2",
                    "supportsHttpsTrafficOnly": True,
                },
            },
        },
    ]


def _policy_hits(err: dict[str, Any]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for item in err.get("additionalInfo") or []:
        info = item.get("info") or {}
        if item.get("type") != "PolicyViolation":
            continue
        hits.append(
            {
                "reference": info.get("policyDefinitionReferenceId", ""),
                "definition": info.get("policyDefinitionDisplayName", info.get("policyDefinitionName", "")),
                "effect": info.get("policyDefinitionEffect", ""),
                "assignment": info.get("policyAssignmentName", ""),
                "initiative": info.get("policySetDefinitionName", ""),
            }
        )
    return hits


def _clean_message(message: str) -> str:
    """Keep the human sentence, drop the long 'Policy identifiers: [...]' JSON tail."""
    return message.split(" Policy identifiers:")[0].strip()


def _dig(obj: Any, path: str) -> Any:
    for part in path.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def _read_back(url: str) -> dict[str, Any] | None:
    """GET the resource that was just created; ARM can need a few seconds before the read is consistent."""
    for _ in range(12):
        response = requests.get(url, headers=_headers(), timeout=60)
        if response.status_code == 200:
            return response.json()
        time.sleep(5)
    return None


def _flagged_by_initiative(spec: dict[str, Any]) -> list[str] | None:
    """Controls of this initiative that evaluate NonCompliant on the original request body (stateless evaluation, nothing is created)."""
    name = spec["resource"].rsplit("/", 1)[-1]
    rtype = spec["resource"].split("/providers/", 1)[1].rsplit("/", 1)[0]
    request = {
        "resourceDetails": {"resourceContent": {"type": rtype, "name": name, **spec["body"]}, "apiVersion": spec["api"], "scope": RG_BASE},
        "pendingFields": [{"field": "name", "values": [name]}],
        "includeAuditEffect": False,
    }
    url = f"{ARM}{RG_BASE}/providers/Microsoft.PolicyInsights/checkPolicyRestrictions?api-version=2023-03-01"
    for _ in range(3):
        response = requests.post(url, headers=_headers(), json=request, timeout=120)
        if response.status_code == 200:
            evaluations = (response.json().get("contentEvaluationResult") or {}).get("policyEvaluations") or []
            return sorted(
                {
                    (e.get("policyInfo") or {}).get("policyDefinitionReferenceId", "")
                    for e in evaluations
                    if e.get("evaluationResult") == "NonCompliant"
                    and str((e.get("policyInfo") or {}).get("policyAssignmentId", "")).lower().endswith("/" + GOV["assignmentName"].lower())
                }
            )
        time.sleep(5)
    return None


def _classify_allowed(spec: dict[str, Any], url: str, result: dict[str, Any]) -> None:
    """An unsafe request that succeeded: either another policy rewrote it to a safe shape first (CORRECTED) or it is a real hole (ALLOWED)."""
    unsafe = spec.get("unsafe") or {}
    stored = _read_back(url) if unsafe else None
    rewritten: dict[str, Any] = {}
    for path, sent in unsafe.items():
        now = _dig(stored, path) if stored else None
        rewritten[path] = {"sent": sent, "stored": now, "changed": now is not None and str(now).lower() != str(sent).lower()}
    if rewritten and all(v["changed"] for v in rewritten.values()):
        flagged = _flagged_by_initiative(spec)
        # one expected control is enough: the stateless evaluation can report fewer controls than a real request (cosmos capabilities[*] alias)
        covered = [c for c in spec["controls"] if c in (flagged or [])]
        result.update(outcome="CORRECTED", rewritten=rewritten, initiativeFlags=flagged, status="PASS" if covered else "FAIL")
        if not covered:
            result["note"] = "the request was rewritten by another policy, but this initiative did not flag it"
    else:
        result.update(outcome="ALLOWED", status="FAIL")
        if rewritten:
            result["rewritten"] = rewritten


def run_attempt(spec: dict[str, Any], cleanup: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    url = f"{ARM}{spec['resource']}?api-version={spec['api']}"
    started = datetime.now(timezone.utc)
    response = requests.put(url, headers=_headers(), json=spec["body"], timeout=300)
    body: dict[str, Any] = {}
    try:
        body = response.json()
    except ValueError:
        pass
    err = body.get("error") or {}
    expect = spec.get("expect", "blocked")
    result: dict[str, Any] = {
        "id": spec["id"],
        "title": spec["title"],
        "resource": spec["resource"].rsplit("/", 1)[-1],
        "expected": expect,
        "expectedControls": spec["controls"],
        "httpStatus": response.status_code,
        "utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if err.get("code") == "RequestDisallowedByPolicy":
        hits = _policy_hits(err)
        result.update(
            outcome="BLOCKED",
            errorCode=err["code"],
            policy=hits,
            message=_clean_message(err.get("message", "")),
        )
        hit_refs = {h["reference"] for h in hits}
        missing = [c for c in spec["controls"] if c not in hit_refs]
        result["status"] = "PASS" if expect == "blocked" and not missing else "FAIL"
        if missing:
            result["note"] = f"expected control(s) not reported: {missing}"
    elif response.status_code < 300:
        if expect == "allowed":
            result.update(outcome="ALLOWED", status="PASS")
        else:
            _classify_allowed(spec, url, result)
        cleanup.append((url, spec, result))
    else:
        result.update(outcome="ERROR", status="FAIL", errorCode=err.get("code", ""), message=_clean_message(err.get("message", response.text[:300])))
    return result


def _delete(put_url: str, spec: dict[str, Any]) -> str:
    for _ in range(60):
        response = requests.delete(put_url, headers=_headers(), timeout=300)
        if response.status_code in (200, 202, 204):
            return f"deleted (HTTP {response.status_code}){_purge(spec)}"
        if response.status_code in (409, 412):
            time.sleep(15)  # still provisioning (a Cosmos DB account takes minutes before it can be deleted)
            continue
        return f"delete returned HTTP {response.status_code}"
    return "delete did not complete - remove the resource manually"


def _purge(spec: dict[str, Any]) -> str:
    """Foundry (AI Services) accounts are soft-deleted; purge the throw-away account so no tombstone is left behind."""
    if "/Microsoft.CognitiveServices/accounts/" not in spec["resource"] or "/projects/" in spec["resource"]:
        return ""
    name = spec["resource"].rsplit("/", 1)[-1]
    url = f"{ARM}/subscriptions/{SUB}/providers/Microsoft.CognitiveServices/locations/{LOC}/resourceGroups/{RG}/deletedAccounts/{name}?api-version=2025-06-01"
    for _ in range(6):
        response = requests.delete(url, headers=_headers(), timeout=120)
        if response.status_code in (200, 202, 204):
            return ", purged"
        time.sleep(5)
    return ", purge pending"


def _modified_by(names: set[str], since: datetime, wait_s: int = 180) -> dict[str, list[dict[str, str]]]:
    """Which policy assignment performed the Modify. Best effort: the activity log lags by a few minutes, so poll briefly."""
    stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    flt = f"eventTimestamp ge '{stamp}' and resourceGroupName eq '{RG}'"
    deadline = time.time() + wait_s
    found: dict[str, list[dict[str, str]]] = {}
    while True:
        url: str | None = f"{ARM}/subscriptions/{SUB}/providers/Microsoft.Insights/eventtypes/management/values?api-version=2015-04-01&$filter={quote(flt)}"
        seen: dict[str, set[tuple[str, str, str]]] = {}
        while url:
            response = requests.get(url, headers=_headers(), timeout=120)
            if response.status_code != 200:
                break
            page = response.json()
            for event in page.get("value", []):
                if not str((event.get("operationName") or {}).get("value", "")).lower().startswith("microsoft.authorization/policies/modify"):
                    continue
                name = str(event.get("resourceId", "")).rsplit("/", 1)[-1]
                if name not in names:
                    continue
                try:
                    policies = json.loads((event.get("properties") or {}).get("policies") or "[]")
                except ValueError:
                    policies = []
                for pol in policies:
                    seen.setdefault(name, set()).add((pol.get("policyAssignmentName", ""), pol.get("policyAssignmentScope", ""), pol.get("policyDefinitionReferenceId", "")))
            url = page.get("nextLink")
        found = {n: [{"assignment": a, "scope": s, "control": c} for a, s, c in sorted(items)] for n, items in seen.items()}
        if set(found) >= names or time.time() > deadline:
            return found
        time.sleep(20)


def _show(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _describe(res: dict[str, Any]) -> str:
    if res["outcome"] == "BLOCKED":
        return ", ".join(h["reference"] for h in res.get("policy", [])) or "-"
    if res["outcome"] == "CORRECTED":
        changes = ", ".join(f"{path.rsplit('.', 1)[-1]} {_show(v['sent'])}->{_show(v['stored'])}" for path, v in res["rewritten"].items())
        return f"rewritten before the Deny ran: {changes}; initiative flags: {', '.join(res.get('initiativeFlags') or []) or '-'}"
    return "-"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default="", help="comma separated id substrings")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args()

    specs = attempts()
    if args.only:
        wanted = [w.strip() for w in args.only.split(",") if w.strip()]
        specs = [s for s in specs if any(w in s["id"] for w in wanted)]
    if args.list:
        for s in specs:
            print(f"  {s['id']:<26} {s['title']}")
        return

    results: list[dict[str, Any]] = []
    cleanup: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    began = datetime.now(timezone.utc)
    try:
        for spec in specs:
            res = run_attempt(spec, cleanup)
            results.append(res)
            if not args.json:
                print(f"  {res['status']:<4} {res['outcome']:<9} HTTP {res['httpStatus']}  {res['id']:<26} {_describe(res)}")
                if res.get("message") and res["status"] == "FAIL":
                    print(f"         {res['message'][:300]}")
                if res.get("note"):
                    print(f"         {res['note']}")
    finally:
        # deleted after the last attempt so a slow Cosmos DB provisioning overlaps with the remaining attempts
        for url, spec, res in cleanup:
            res["cleanup"] = _delete(url, spec)
            if not args.json:
                print(f"         cleanup {res['resource']}: {res['cleanup']}")

    corrected = {r["resource"]: r for r in results if r["outcome"] == "CORRECTED"}
    if corrected:
        by = _modified_by(set(corrected), began)
        for name, res in corrected.items():
            res["correctedBy"] = by.get(name, [])
            if not args.json:
                who = sorted({f"{b['assignment']} @ {b['scope'].replace('/providers/Microsoft.Management/', '')}" for b in res["correctedBy"]})
                print(f"         {res['id']} corrected by: {'; '.join(who) or 'not in the activity log yet'}")

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = EVIDENCE / f"try-violations-{stamp}.json"
    path.write_text(json.dumps({"runUtc": stamp, "assignment": GOV["assignmentName"], "results": results}, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        failed = [r for r in results if r["status"] != "PASS"]
        tally = collections.Counter(r["outcome"] for r in results if r["status"] == "PASS")
        labels = (("denied", "BLOCKED"), ("corrected by another policy", "CORRECTED"), ("compliant request allowed", "ALLOWED"))
        parts = ", ".join(f"{tally[key]} {label}" for label, key in labels if tally[key])
        print(f"\n  {len(results) - len(failed)}/{len(results)} as expected ({parts})  ->  {path.relative_to(ROOT)}")
    raise SystemExit(1 if any(r["status"] != "PASS" for r in results) else 0)


if __name__ == "__main__":
    main()
