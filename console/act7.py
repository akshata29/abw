"""Roles, cost and the agent front door for the Demo Console (scene 7, "Roles & cost").

Act 6 follows ONE request through every layer. Act 7 answers the three questions a bank asks next:
  7.1  Does the AGENT also enter through the APIM gateway, so the path is user -> APIM -> agent -> APIM -> MCP -> data?
  7.2  Does it work for every kind of user, not just the operator - one allowed and one refused request per persona, plus an administrator?
  7.3  What does it cost, who spends the tokens, and can a runaway agent be capped?  (7.4 proves the cap.)

Every cell of the role matrix carries an evidence tag so the presenter can tell what was observed from what was designed:
  live    this very request was just made and the cell is its real response
  rbac    a live read of the Azure role assignments (the grant itself, not a request)
  logs    read back from Log Analytics
  design  not run - the outcome the role model predicts, shown because that persona has not signed in yet

The only thing this module ever changes is the two APIM named values abw-agent-token-quota and abw-agent-rpm (Beat 7.4),
and it always puts them back (in `finally`, and again by Reset demo). Nothing here touches Entra, a role or another resource group.
Secrets (tokens, subscription keys, passwords) are never emitted or stored.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import logging
import re
import threading
import time
from typing import Any

import azure_probe as ap
import catalog
import jobs
import mcpclient
import personas

log = logging.getLogger(__name__)

KINDS = jobs.ACT7_KINDS
AI_AUDIENCE = "https://ai.azure.com"
PROBE_ID = "resp_" + "0" * 48  # a well-formed response id that does not exist: Foundry answers 404, so the request got past the front door without spending a token
POST_PROBE_ARGS = "POST /openai/v1/responses  (empty body - Foundry would answer 400, so no token is spent)"
NV_API = "2024-06-01-preview"
NV_QUOTA = "abw-agent-token-quota"
NV_RPM = "abw-agent-rpm"
FRONTDOOR_API = "abw-agent-frontdoor"
COST_API = "2023-11-01"
BUDGET_API = "2023-05-01"
COST_TTL = 600.0  # Cost Management throttles hard and lags by hours anyway
HONEST_PUBLIC = ("Foundry's own endpoint still answers a valid Entra token in this demo (public network access is on). "
                 "In production the account sits behind a private endpoint so APIM is the only way in - see DESIGN.md.")


# ------------------------------------------------------------------------------------------------------ small helpers
def _clip(text: Any, limit: int = 150) -> str:
    flat = re.sub(r"\s+", " ", str(text or "")).strip()
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def _safe(fn: Any, *args: Any) -> tuple[Any, str]:
    """(result, '') or (None, why): one unreadable source must not hide the others."""
    try:
        return fn(*args), ""
    except Exception as exc:  # noqa: BLE001
        log.warning("act7: %s failed: %s", getattr(fn, "__name__", "read"), exc)
        return None, jobs.friendly(exc)


def _emit_table(job: jobs.Job, title: str, rows: list[dict[str, Any]], query: str = "", lights: dict[str, str] | None = None) -> None:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    job.emit("table", title=title, columns=columns, rows=[[jobs._cell(r.get(c)) for c in columns] for r in rows[:40]], query=query, total=len(rows), lights=lights or {})


def _frontdoor() -> dict[str, Any]:
    return json.loads(jobs.FRONTDOOR_FILE.read_text(encoding="utf-8-sig"))


def _probe_url() -> str:
    return str(_frontdoor()["openAiBaseUrl"]).rstrip("/") + "/responses/" + PROBE_ID


def _probe_get(url: str, token: str | None) -> tuple[Any, float]:
    """One GET, no retries: a retry would hide the very 429 the beat is waiting for."""
    t0 = time.time()
    resp = ap._HTTP.get(url, headers={"Authorization": "Bearer " + token} if token else {})
    return resp, time.time() - t0


def _probe_post(token: str | None) -> tuple[Any, float]:
    """An empty POST to the agent route. Foundry would answer 400, so it spends no token - but it walks the same gateway route a real agent call does."""
    t0 = time.time()
    url = str(_frontdoor()["openAiBaseUrl"]).rstrip("/") + "/responses"
    resp = ap._HTTP.post(url, headers={"Authorization": "Bearer " + token} if token else {}, json={}, timeout=20)
    return resp, time.time() - t0


def _shaped(resp: Any) -> dict[str, Any]:
    """The front door's own error body {"error": {code, message, reason, retry_after_seconds, request_id}} - empty for anything else."""
    try:
        body = resp.json()
    except ValueError:
        return {}
    err = body.get("error") if isinstance(body, dict) else None
    return err if isinstance(err, dict) else {}


def _front_card(tool: str, args: str, resp: Any, seconds: float, *, verdict: str, title: str, plain: str, wall: int | None, reason: str, lights: dict[str, str]) -> dict[str, Any]:
    hl = {k.lower(): v for k, v in resp.headers.items()}
    return {
        "server": "agents", "tool": tool, "args": args, "status": resp.status_code, "seconds": round(seconds, 2), "decision": "", "reason": reason,
        "request_id": hl.get("x-abw-request-id") or _shaped(resp).get("request_id"), "excerpt": _clip(resp.text, 700), "leak": [], "attack": "",
        "verdict": verdict, "title": title, "plain": plain, "wall": wall, "lights": lights,
    }


# ------------------------------------------------------------------------------------------------ APIM named values
def _nv_url(name: str) -> str:
    return f"{ap.ARM}{ap.RG_ID}/providers/Microsoft.ApiManagement/service/{ap.APIM_NAME}/namedValues/{name}"


def _set_named_value(name: str, value: int) -> None:
    """PATCH one APIM named value (202, empty body). APIM applies it within seconds to about a minute."""
    resp = ap._retrying("PATCH", _nv_url(name), params={"api-version": NV_API},
                        headers={"Authorization": "Bearer " + ap.token(ap.ARM), "If-Match": "*"},
                        json={"properties": {"value": str(int(value))}})
    if resp.status_code >= 400:
        raise ap.ProbeError(f"APIM {resp.status_code} {ap._err_text(resp)}")


def restore_frontdoor() -> dict[str, int]:
    """Put the agent front door back to the demo baseline: default token budget and call rate, agent path = APIM. Used by Reset demo."""
    base = jobs.FRONT_DOOR_DEFAULTS
    for name, want in ((NV_QUOTA, base["quota"]), (NV_RPM, base["rpm"])):
        if str(ap._named_value(name)) != str(want):  # an identical PATCH would still make the gateway recompile its policy
            _set_named_value(name, want)
    jobs.save_state(agent_via="apim")
    return dict(base)


def validate(kind: str, p: dict[str, Any]) -> str:
    """Why this Act 7 request cannot run, in the presenter's words ('' when it can). Called by jobs.validate for these kinds."""
    deploy = "The APIM agent front door is not deployed in this environment - run scripts\\deploy.ps1 -Stage frontdoor first."
    if kind == "agentpath":
        via = str(p.get("via") or "")
        if via not in ("apim", "direct"):
            return "Unknown agent path."
        return deploy if via == "apim" and not jobs.frontdoor_ready() else ""
    if kind in ("frontdoor", "quota") and not jobs.frontdoor_ready():
        return deploy
    if kind == "quota":
        if str(p.get("mode") or "quota") not in ("quota", "rate"):
            return "Unknown budget mode."
        if jobs.agent_via() != "apim":
            return "The agent is switched to the direct path, which has no budget to cut. Switch the front door on first (Beat 7.1), then run this."
    return ""


# ===================================================================================== 7.1  the agent front door
def run_agentpath(job: jobs.Job) -> None:
    via = str(job.params.get("via") or "apim")
    jobs.save_state(agent_via=via)
    if via == "apim":
        job.say("Agent calls now enter at the APIM front door: user -> APIM -> Foundry agent -> (its tool calls come back through the same APIM) -> MCP -> data.")
        job.step("Agent path: APIM front door (token check, kill switch, per-user rate limit and token budget, token metering)", "ok")
        job.finish("done", "Agent calls enter through the APIM front door.", via=via)
        return
    job.say("Agent calls now go straight to the Foundry project endpoint - the way most PoCs ship. Use this only to show the difference.")
    job.step("Agent path: direct to Foundry. No per-user token budget, no token metering, no kill switch at the agent's entrance.", "info")
    job.finish("done", "Agent calls go direct to Foundry (front door bypassed).", via=via)


def run_frontdoor(job: jobs.Job) -> None:
    job.say("Act 6 sent the user straight to the agent. A bank puts one gateway in front of everything: the user calls APIM, APIM calls the agent, and the agent's own tool calls come back through the same APIM. Here is that front door refusing and admitting real requests.")
    api = ap.arm(f"{ap.RG_ID}/providers/Microsoft.ApiManagement/service/{ap.APIM_NAME}/apis/{FRONTDOOR_API}", NV_API)["properties"]
    target = str(api.get("serviceUrl") or "").rstrip("/")
    job.step(f"APIM API {FRONTDOOR_API} (path /{api.get('path')}) forwards to the Foundry project; a subscription key is {'required' if api.get('subscriptionRequired') else 'not required - Entra tokens only'}", "ok")
    url = _probe_url()
    shown = "GET /openai/v1/responses/" + PROBE_ID[:11] + "...  (an id that does not exist)"

    job.step("1. No token at all", "run")
    resp, secs = _probe_get(url, None)
    info = catalog.explain_failure({"via": "apim", "gateway_id": "probe", "code": "unauthorized"})
    ok = resp.status_code == 401 and _shaped(resp).get("code") == "unauthorized"
    job.emit("http", **_front_card("front door, no token", shown, resp, secs, verdict="denied" if ok else "failed", title=info["title"] if ok else "Unexpected answer",
                                    plain=info["plain"] if ok else f"Expected 401 unauthorized from the front door, got HTTP {resp.status_code}.", wall=1 if ok else None,
                                    reason="no_valid_token" if ok else "", lights={"apim": "deny"} if ok else {}))
    seen = {"none": ok}

    job.step("2. A real Entra token - for the wrong audience (Azure Resource Manager, not Foundry)", "run")
    resp, secs = _probe_get(url, ap.token(ap.ARM))
    ok = resp.status_code == 401 and _shaped(resp).get("code") == "unauthorized"
    job.emit("http", **_front_card("front door, wrong audience", shown, resp, secs, verdict="denied" if ok else "failed", title="Wrong audience - refused at the front door" if ok else "Unexpected answer",
                                    plain=("Right user, genuine Entra token, but minted for another resource. The front door accepts only the Foundry audience (" + AI_AUDIENCE + ") - a token stolen from another app is useless here.") if ok
                                    else f"Expected 401 from the front door, got HTTP {resp.status_code}.", wall=1 if ok else None, reason="no_valid_token" if ok else "",
                                    lights={"user": "ok", "apim": "deny"} if ok else {}))
    seen["audience"] = ok

    job.step("3. A valid Foundry-audience token (the operator's own)", "run")
    resp, secs = _probe_get(url, ap.token(AI_AUDIENCE))
    ok = resp.status_code in (400, 404) and _shaped(resp).get("code") not in ("unauthorized", "forbidden", "token_quota_exceeded", "rate_limited")
    job.emit("http", **_front_card("front door, valid token", shown, resp, secs, verdict="allowed" if ok else "failed", title="Let through to Foundry" if ok else "Unexpected answer",
                                    plain=(f"The front door accepted the token and forwarded the call: HTTP {resp.status_code} is Foundry's own answer (that response id does not exist) - "
                                           "a harmless way to show the request got past the gateway without spending a token. A real agent call is the next button.") if ok
                                    else f"Expected Foundry to answer 404, got HTTP {resp.status_code}.", wall=None, reason="",
                                    lights={"user": "ok", "entra": "ok", "apim": "ok", "foundry": "ok"} if ok else {}))
    seen["valid"] = ok

    job.step("4. Honest check: Foundry's own endpoint, bypassing APIM", "run")
    direct = target + "/openai/v1/responses/" + PROBE_ID
    bare, _ = _probe_get(direct, None)
    authed, _ = _probe_get(direct, ap.token(AI_AUDIENCE))
    job.step(f"Direct to Foundry without a token: HTTP {bare.status_code} (Foundry refuses the anonymous call itself). With a valid Entra token: HTTP {authed.status_code}.", "info")
    job.say(HONEST_PUBLIC)

    good = all(seen.values())
    job.finish("done" if good else "failed",
               "No token -> 401, wrong audience -> 401, valid token -> forwarded to Foundry" if good else "The front door did not answer as designed - see the cards above.", **seen)


# ======================================================================================== 7.2  the role matrix
LANES: list[dict[str, Any]] = [
    {"id": "priya", "persona": "priya", "cells": [
        {"kind": "allow", "label": "Search the research library", "server": "research", "tool": "search_research", "args": {"query": "ACME", "limit": 3},
         "expect": "Allowed - Priya holds Research.Read.", "want": {"verdict": "allowed"}},
        {"kind": "refuse", "label": "Open a deal document on the wall server", "server": "wall", "tool": "get_deal_document", "args": {"doc_id": "FALCON-001"},
         "expect": "Refused at the gateway - no role on the wall server.", "want": {"verdict": "denied", "wall": 1, "reason": "missing_role"}},
    ]},
    {"id": "wes", "persona": "wes", "cells": [
        {"kind": "allow", "label": "Read the Falcon deal document", "server": "wall", "tool": "get_deal_document", "args": {"doc_id": "FALCON-001"},
         "expect": "Allowed - wall-crossed on Falcon, and Storage lets his own identity read the Falcon container.", "want": {"verdict": "allowed"}},
        {"kind": "refuse", "label": "Read the Orion deal document", "server": "wall", "tool": "get_deal_document", "args": {"doc_id": "ORION-001"},
         "expect": "Refused by the MCP server - not wall-crossed on Orion.", "want": {"verdict": "denied", "wall": 2, "reason": "project_not_in_token_roles"}},
    ]},
    {"id": "tara", "persona": "tara", "cells": [
        {"kind": "allow", "label": "Check whether ACME is restricted", "server": "actions", "tool": "check_restricted_list", "args": {"ticker": "ACME"},
         "expect": "Allowed - Tara holds Trade.Execute.", "want": {"verdict": "allowed"}},
        {"kind": "refuse", "label": "Place an order for ZYNX (a restricted name)", "server": "actions", "tool": "place_order", "args": {"ticker": "ZYNX", "side": "BUY", "quantity": 100},
         "scope": "Tools.Execute", "expect": "Refused by the MCP server - ZYNX is on the restricted list, whoever asks.", "want": {"verdict": "denied", "wall": 2, "reason": "restricted_list"}},
    ]},
    {"id": "carla", "persona": "carla", "cells": [
        {"kind": "allow", "label": "Check whether ZYNX is restricted", "server": "actions", "tool": "check_restricted_list", "args": {"ticker": "ZYNX"},
         "expect": "Allowed - compliance holds Trade.Read (and the answer is: restricted).", "want": {"verdict": "allowed"}},
        {"kind": "refuse", "label": "Place an order for ACME", "server": "actions", "tool": "place_order", "args": {"ticker": "ACME", "side": "BUY", "quantity": 1},
         "scope": "Tools.Execute", "expect": "Refused by the MCP server - compliance can read trades but not place them.", "want": {"verdict": "denied", "wall": 2, "reason": "missing_role"}},
    ]},
    {"id": "ian", "persona": "ian", "cells": [
        {"kind": "allow", "label": "Read the audit trail (Log Analytics)", "special": "rbac",
         "expect": "Allowed - his group holds Log Analytics Reader, so he reads the audit trail but no data.", "want": {"verdict": "allowed"}},
        {"kind": "refuse", "label": "Search the research library", "server": "research", "tool": "search_research", "args": {"query": "ACME", "limit": 3},
         "expect": "Refused at the gateway - no data role at all.", "want": {"verdict": "denied", "wall": 1, "reason": "missing_role"}},
    ]},
    {"id": "admin", "persona": None, "cells": [
        {"kind": "allow", "label": "Read the Falcon deal document", "server": "wall", "tool": "get_deal_document", "args": {"doc_id": "FALCON-001"},
         "expect": "Allowed - the administrator mirrors Wes: wall-crossed on Falcon.", "want": {"verdict": "allowed"}},
        {"kind": "allow", "label": "Read the audit trail (Log Analytics)", "special": "audit",
         "expect": "Allowed - the administrator reads every refusal the platform recorded.", "want": {"verdict": "allowed"}},
        {"kind": "refuse", "label": "Read the Orion deal document", "server": "wall", "tool": "get_deal_document", "args": {"doc_id": "ORION-001"},
         "expect": "Refused by the MCP server - full control-plane power, but nobody is wall-crossed on Orion, the administrator included.",
         "want": {"verdict": "denied", "wall": 2, "reason": "project_not_in_token_roles"}},
    ]},
]
ADMIN_STORY = ("The signed-in platform administrator. Owns the demo resource group and reads every log, but holds the same data roles as Wes and Tara: "
               "Falcon yes, Orion no. Administrator power is control-plane and audit power - it does not buy a way through the wall.")
DATA_PLANE_REASONS = ("storage_rbac_denied", "AuthorizationPermissionMismatch")
_ROLE_NAMES: dict[str, str] = {}


def _wall_of(res: dict[str, Any]) -> int | None:
    """Which wall refused, from the shape of the response: HTTP 401/403/429 is the gateway; HTTP 200 carrying DENIED is the MCP server (or the data plane when Storage said no)."""
    if res.get("verdict") != "denied":
        return None
    decision = str(res.get("decision") or "").upper()
    if int(res.get("status") or 0) == 200 and decision in ("DENIED", "BLOCKED"):
        return 3 if str(res.get("reason") or "") in DATA_PLANE_REASONS else 2
    return res.get("wall")


def _words(reason: str, wall: int | None, status: int | None, title: str, plain: str) -> tuple[str, str]:
    """Plain English for one cell. A tool-level missing_role shares its reason code with the gateway's - say which layer it really was."""
    if wall == 2 and reason == "missing_role" and status in (None, 200):
        return ("The MCP server said no",
                "The gateway let this person in - the token holds a role on this server - but this tool needs a stronger one, and the server checks the roles in the token itself. "
                "Same reason code as a gateway refusal, one layer deeper. Nothing was changed.")
    if wall == 2 and reason == "missing_scope" and status in (None, 200):
        return ("The MCP server said no", "The token was not granted the permission this tool needs (its scope), so the server refused the call.")
    return title, plain


def _cell(spec: dict[str, Any], **over: Any) -> dict[str, Any]:
    want = spec["want"]
    base = {
        "kind": spec["kind"], "label": spec["label"], "expect": spec["expect"],
        "tool": f"{spec['server']}.{spec['tool']}" if spec.get("server") else "", "args": json.dumps(spec.get("args") or {}, ensure_ascii=False) if spec.get("args") else "",
        "verdict": want["verdict"], "wall": want.get("wall"), "reason": want.get("reason", ""), "title": "", "plain": "",
        "status": None, "seconds": None, "request_id": None, "as_expected": None, "evidence": "design", "roles": [], "excerpt": "",
    }
    base.update(over)
    return base


def _design_cell(spec: dict[str, Any]) -> dict[str, Any]:
    """The outcome the role model predicts, shown (and labelled as such) for a persona who has not signed in yet."""
    want = spec["want"]
    reason = want.get("reason", "")
    info = catalog.REASONS.get(reason, {})
    title, plain = _words(reason, want.get("wall"), None, info.get("title") or ("Allowed" if want["verdict"] == "allowed" else "Refused"), info.get("plain") or spec["expect"])
    return _cell(spec, title=title, plain=plain, evidence="design")


def _as_expected(want: dict[str, Any], verdict: str, wall: int | None, reason: str) -> bool:
    if verdict != want["verdict"]:
        return False
    if want.get("wall") is not None and wall != want["wall"]:
        return False
    return not want.get("reason") or reason == want["reason"]


def _gateway_cell(spec: dict[str, Any], persona: str | None) -> dict[str, Any]:
    res = jobs.call_gateway(spec["server"], spec["tool"], spec["args"], scope=spec.get("scope", "Tools.Read"), persona=persona)
    wall = _wall_of(res)
    reason = str(res.get("reason") or "")
    title, plain = _words(reason, wall, res.get("status"), str(res.get("title") or ""), str(res.get("plain") or ""))
    roles = res.get("roles")
    if roles is None and persona is None:
        try:
            roles = mcpclient.summarize(jobs.token_for(spec["server"], spec.get("scope", "Tools.Read"))).get("roles") or []
        except Exception:  # noqa: BLE001 - the roles line is a bonus
            roles = []
    return _cell(spec, verdict=res["verdict"], wall=wall, reason=reason, title=title, plain=plain, status=res.get("status"), seconds=res.get("seconds"),
                 request_id=res.get("request_id"), as_expected=_as_expected(spec["want"], res["verdict"], wall, reason), evidence="live", roles=list(roles or []),
                 excerpt=_clip(res.get("excerpt"), 500))


def _role_name(definition_id: str) -> str:
    if definition_id not in _ROLE_NAMES:
        _ROLE_NAMES[definition_id] = str(ap.arm(definition_id, "2022-04-01")["properties"]["roleName"])
    return _ROLE_NAMES[definition_id]


def _infosec_grants() -> list[str]:
    """What Ian's group may do in Azure, read live from Azure RBAC at the resource group and at the workspace."""
    gid = ap.ENTRA["groups"]["sg-abw-infosec"]
    seen: dict[str, str] = {}
    for scope in (ap.RG_ID, ap.PLAT["observability"]["lawId"]):
        data = ap.arm(f"{scope}/providers/Microsoft.Authorization/roleAssignments", "2022-04-01", **{"$filter": f"principalId eq '{gid}'"})
        for ra in data.get("value") or []:
            where = str(ra["properties"].get("scope") or scope).rstrip("/").rsplit("/", 1)[-1]
            seen[ra["name"]] = f"{_role_name(ra['properties']['roleDefinitionId'])} on {where}"
    return sorted(seen.values())


def _rbac_cell(spec: dict[str, Any]) -> dict[str, Any]:
    grants = _infosec_grants()
    ok = any(g.startswith("Log Analytics Reader") for g in grants)
    plain = ("Read live from Azure RBAC: " + "; ".join(grants) + ". These are held through the group sg-abw-infosec, so Ian can query the audit trail but has no data role on any MCP server. "
             "His own query is a portal step: sign in as Ian, open Logs on the workspace, run AbwDenials(24h).") if grants else "No role assignment found for the infosec group."
    return _cell(spec, title="Allowed - read-only access to the audit trail" if ok else "No audit access found", plain=plain, as_expected=ok, evidence="rbac",
                 excerpt=_clip("; ".join(grants), 500))


def _audit_cell(spec: dict[str, Any]) -> dict[str, Any]:
    t0 = time.time()
    rows = ap.la_query("AbwDenials(24h) | summarize Refusals = count() by Layer | order by Layer asc", 24)
    summary = ", ".join(f"{r.get('Layer')}: {r.get('Refusals')}" for r in rows) or "no refusal recorded in the last 24 hours"
    total = sum(int(r.get("Refusals") or 0) for r in rows)
    return _cell(spec, title="Allowed - the audit trail is readable", plain=f"Log Analytics answered with the platform's own record of refusals (last 24 h): {summary}. Total {total}.",
                 seconds=round(time.time() - t0, 2), as_expected=True, evidence="logs", excerpt=_clip(summary, 500))


def _lane(lane: dict[str, Any]) -> dict[str, Any]:
    pid = lane["persona"]
    if pid:
        name, job = personas.name(pid), str((mcpclient.ENTRA.get("users", {}).get(pid) or {}).get("job") or "")
        story, roles = personas.STORY[pid], [f"{s}: {r}" for s, r in personas.role_pairs(pid)]
    else:
        name, job, story = "Administrator", "Platform admin (the signed-in operator)", ADMIN_STORY
        roles = []
        for srv in ("research", "wall", "actions"):
            try:
                roles += [f"{srv}: {r}" for r in mcpclient.summarize(jobs.token_for(srv)).get("roles") or []]
            except Exception:  # noqa: BLE001
                log.debug("operator roles for %s unreadable", srv, exc_info=True)
    out: dict[str, Any] = {"id": lane["id"], "name": name, "job": job, "story": story, "roles": roles, "state": "ran", "note": "", "cells": []}
    if pid and not personas.signed_in(pid):
        out.update(state="signin", note=f"{name} has not signed in yet, so these are the outcomes the role model predicts, not requests. Open Acting as (top of the left rail, or press P), sign in as {name} once, then run this beat again.")
        out["cells"] = [_design_cell(s) for s in lane["cells"]]
        return out
    for spec in lane["cells"]:
        try:
            if spec.get("special") == "rbac":
                out["cells"].append(_rbac_cell(spec))
            elif spec.get("special") == "audit":
                out["cells"].append(_audit_cell(spec))
            else:
                out["cells"].append(_gateway_cell(spec, pid))
        except personas.NeedsSignIn as exc:
            out.update(state="signin", note=str(exc))
            out["cells"].append(_design_cell(spec))
        except jobs.Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad cell must not blank the board
            log.warning("act7 matrix %s/%s failed: %s", lane["id"], spec["label"], exc)
            out["state"] = "error" if out["state"] == "ran" else out["state"]
            out["cells"].append(_cell(spec, verdict="failed", title="Could not run this check", plain=jobs.friendly(exc), as_expected=False, evidence="live"))
    return out


def run_matrix(job: jobs.Job) -> None:
    job.say("Does it work for every kind of user? One allowed and one refused request for each persona, plus the administrator - each made with that person's own token, "
            "through the gateway and on to the MCP server and the data. No agent and no model is involved, so the answers are deterministic.")
    job.step("Running six lanes in parallel: Priya, Wes, Tara, Carla, Ian and the administrator", "run")
    order = [lane["id"] for lane in LANES]
    done: dict[str, dict[str, Any]] = {}
    with cf.ThreadPoolExecutor(len(LANES)) as pool:
        futures = {pool.submit(_lane, lane): lane for lane in LANES}
        try:
            for fut in cf.as_completed(futures):
                lane = futures[fut]
                result = fut.result()
                done[lane["id"]] = result
                live = [c for c in result["cells"] if c["evidence"] != "design"]
                bad = [c for c in live if c["as_expected"] is False]
                if result["state"] == "signin":
                    job.step(f"{result['name']}: not signed in - shown as designed", "info")
                else:
                    job.step(f"{result['name']}: {len(live) - len(bad)} of {len(live)} behaved as the role model predicts", "fail" if bad else "ok")
                job.check_cancel()
        except BaseException:
            for fut in futures:
                fut.cancel()
            raise
    lanes = [done[i] for i in order]
    cells = [c for lane in lanes for c in lane["cells"]]
    live = [c for c in cells if c["evidence"] != "design"]
    bad = [c for c in live if c["as_expected"] is False]
    designed = [lane["name"] for lane in lanes if lane["state"] == "signin"]
    notes = [
        "Each request here goes to the gateway with that person's own Entra token. There is no agent and no model in the loop, so this tests Walls 1 to 3; Wall 0 (the Foundry guardrail) is Beat 4 and Act 6.",
        "Evidence: live = a request just made; rbac = the Azure role assignment read live; logs = read from Log Analytics; design = not run, because that person has not signed in yet.",
        "The private Positions server lives inside the VNet and is not behind the gateway, so it is not on this board.",
    ]
    job.emit("matrix", lanes=lanes, notes=notes)
    summary = f"{len(live) - len(bad)} of {len(live)} live checks behaved as the role model predicts"
    if designed:
        summary += f"; {', '.join(designed)} not signed in (shown as designed)"
    job.finish("failed" if bad else "done", summary, live=len(live), unexpected=len(bad), designed=designed)


# =========================================================================================== 7.3  the FinOps board
COST_BODY = {"type": "ActualCost", "timeframe": "MonthToDate",
             "dataset": {"granularity": "None", "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}}, "grouping": [{"type": "Dimension", "name": "ServiceName"}]}}
USAGE_WORDS = ("foundry", "openai", "model", "storage", "monitor", "log analytics", "insight", "bandwidth", "key vault", "event", "service bus")
_COST_LOCK = threading.Lock()
_COST: dict[str, Any] = {"at": 0.0, "data": None}


def _kind_of(service: str) -> str:
    low = service.lower()
    return "usage-based" if any(w in low for w in USAGE_WORDS) else "always-on platform"


def _month_cost() -> dict[str, Any]:
    """Month-to-date ACTUAL cost of the demo resource group by service, from Cost Management. Cached 10 minutes; a throttled call falls back to the last reading, flagged stale."""
    with _COST_LOCK:
        if _COST["data"] and time.time() - _COST["at"] < COST_TTL:
            return _COST["data"]
    try:
        raw = ap.arm(f"{ap.RG_ID}/providers/Microsoft.CostManagement/query", COST_API, method="POST", body=COST_BODY)
    except ap.ProbeError as exc:
        saved = jobs.load_state().get("cost")
        if saved:
            return {**saved, "stale": True, "why": _clip(exc, 120)}
        raise
    cols = [str(c.get("name")) for c in raw["properties"]["columns"]]
    ci, si = cols.index("Cost"), cols.index("ServiceName")
    cur = cols.index("Currency") if "Currency" in cols else None
    rows = raw["properties"].get("rows") or []
    services = sorted(({"service": str(r[si]), "cost": float(r[ci])} for r in rows), key=lambda x: -x["cost"])
    data = {"at": time.time(), "total": round(sum(s["cost"] for s in services), 2), "currency": str(rows[0][cur]) if rows and cur is not None else "USD", "services": services,
            "month": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m"), "stale": False}
    with _COST_LOCK:
        _COST.update(at=time.time(), data=data)
    jobs.save_state(cost=data)
    return data


def _budget() -> dict[str, Any] | None:
    data = ap.arm(f"{ap.RG_ID}/providers/Microsoft.Consumption/budgets", BUDGET_API)
    items = data.get("value") or []
    if not items:
        return None
    props = items[0].get("properties") or {}
    notes = [n for n in (props.get("notifications") or {}).values() if isinstance(n, dict) and n.get("threshold") is not None]
    actual = sorted(int(float(n["threshold"])) for n in notes if str(n.get("thresholdType")).lower() != "forecasted")
    forecast = sorted(int(float(n["threshold"])) for n in notes if str(n.get("thresholdType")).lower() == "forecasted")
    return {"name": items[0].get("name"), "amount": props.get("amount"), "grain": props.get("timeGrain"),
            "spent": (props.get("currentSpend") or {}).get("amount"), "actual": actual, "forecast": forecast}


def _age(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes} min" if minutes < 90 else f"{minutes // 60} h"


def _per_user(rows: list[dict[str, Any]], quota: int | None) -> list[dict[str, Any]]:
    """Hourly token rows -> one row per user and agent: tokens in the window, and how much of the hourly budget this hour has used."""
    prefix = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H")
    acc: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key = (str(r.get("User") or ""), str(r.get("Agent") or ""))
        row = acc.setdefault(key, {"User": key[0] or "(unknown user)", "Agent": key[1], "Runs": 0, "Input": 0, "Output": 0, "Total": 0, "ThisHour": 0, "Last": ""})
        row["Runs"] += int(float(r.get("Runs") or 0))
        row["Input"] += int(float(r.get("InputTokens") or 0))
        row["Output"] += int(float(r.get("OutputTokens") or 0))
        row["Total"] += int(float(r.get("TotalTokens") or 0))
        if str(r.get("Hour") or "").startswith(prefix):
            row["ThisHour"] += int(float(r.get("TotalTokens") or 0))
        row["Last"] = max(row["Last"], str(r.get("LastSeen") or ""))
    out = []
    for row in sorted(acc.values(), key=lambda x: -x["Total"]):
        used = f"{row['ThisHour']:,}" + (f" ({100.0 * row['ThisHour'] / quota:.1f}% of {quota:,})" if quota else "")
        out.append({"User": row["User"], "Agent": row["Agent"], "Agent calls": f"{row['Runs']:,}", "Input tokens": f"{row['Input']:,}", "Output tokens": f"{row['Output']:,}", "Total tokens": f"{row['Total']:,}",
                    "Used this hour": used, "Last seen": row["Last"][:19].replace("T", " ") + (" UTC" if row["Last"] else "")})
    return out


def _usage_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """AbwUsageByUser rows -> readable table: server list as words, timestamps trimmed, deny rate as a percentage."""
    out = []
    for r in rows:
        servers = r.get("Servers")
        if isinstance(servers, str):
            try:
                servers = json.loads(servers)
            except ValueError:
                servers = [servers]
        last = str(r.get("LastSeen") or "")
        out.append({"User": str(r.get("User") or "(no user context)"), "Calls": f"{int(float(r.get('Calls') or 0)):,}", "Allowed": f"{int(float(r.get('Allowed') or 0)):,}",
                    "Denied": f"{int(float(r.get('Denied') or 0)):,}", "Deny rate": f"{float(r.get('DenyRatePct') or 0):.1f}%",
                    "Tools tried": str(r.get("DistinctTools") if r.get("DistinctTools") is not None else ""), "Servers": ", ".join(str(s) for s in (servers or [])),
                    "Last seen": last[:19].replace("T", " ") + (" UTC" if last else "")})
    return out


def run_finops(job: jobs.Job) -> None:
    job.say("What does this cost, who is spending the tokens, and where does the budget stop a runaway agent? Real numbers only: Azure Cost Management for the money, the front door's own meter for the tokens.")
    job.step("Reading Cost Management, the budget, the token meter in Log Analytics and the front door's limits", "run")
    ready = jobs.frontdoor_ready()
    work: dict[str, Any] = {
        "cost": (_month_cost,), "budget": (_budget,),
        "tokens": (ap.la_query, "AbwTokenUsage(24h)", 24), "usage": (ap.la_query, "AbwUsageByUser(7d)", 24 * 7),
    }
    if ready:
        work["limits"] = (jobs.frontdoor_limits,)
    got: dict[str, Any] = {}
    why: dict[str, str] = {}
    with cf.ThreadPoolExecutor(len(work)) as pool:
        futures = {key: pool.submit(_safe, spec[0], *spec[1:]) for key, spec in work.items()}
        for key, fut in futures.items():
            got[key], why[key] = fut.result()
    job.check_cancel()

    cost, budget, limits = got.get("cost"), got.get("budget"), got.get("limits")
    tiles: list[dict[str, str]] = []
    notes: list[str] = []
    if cost:
        services = [{**s, "kind": _kind_of(s["service"])} for s in cost["services"]]
        platform = sum(s["cost"] for s in services if s["kind"] == "always-on platform")
        usage = sum(s["cost"] for s in services if s["kind"] == "usage-based")
        total = cost["total"] or 0.0
        stale = f" (last reading {_age(time.time() - float(cost['at']))} ago - Cost Management is throttling)" if cost.get("stale") else ""
        tiles.append({"label": "Spend this month", "value": f"${total:,.2f}", "sub": f"{cost['month']} to date, this resource group only{stale}", "tone": "warn" if cost.get("stale") else ""})
        tiles.append({"label": "Always-on platform", "value": f"${platform:,.2f}", "sub": f"{100.0 * platform / total:.0f}% - gateway, search, network, VMs; paid whether or not anyone calls" if total else "", "tone": ""})
        tiles.append({"label": "Usage-based", "value": f"${usage:,.2f}", "sub": "model calls, storage, monitoring - grows with use", "tone": ""})
        job.step(f"Cost Management: ${total:,.2f} month to date across {len(services)} services", "ok")
        notes.append("Azure bills this data hours late, so the figure is what has been billed so far - not a forecast, and not up to the minute.")
        top = services[0] if services else None
        if top and total and top["cost"] / total > 0.4:
            notes.append(f"{top['service']} is the largest line (${top['cost']:,.2f}, {100.0 * top['cost'] / total:.0f}%). It is a fixed platform cost - the price of having one governed front door - not a per-call cost. Token spend appears under the model line.")
    else:
        tiles.append({"label": "Spend this month", "value": "not available", "sub": why.get("cost") or "Cost Management returned no data", "tone": "warn"})
        job.step(f"Cost Management could not be read: {why.get('cost')}", "fail")
    if budget:
        spent, amount = budget.get("spent"), budget.get("amount")
        pct = f"{100.0 * float(spent) / float(amount):.0f}% used" if spent is not None and amount else ""
        marks = ", ".join(f"{t}%" for t in budget["actual"]) + (" of actual spend" if budget["actual"] else "")
        marks += (" and " if marks and budget["forecast"] else "") + ", ".join(f"{t}%" for t in budget["forecast"]) + (" forecast" if budget["forecast"] else "")
        tiles.append({"label": "Budget alert", "value": f"${float(amount):,.0f} / {str(budget.get('grain') or 'month').lower()}",
                      "sub": (pct + " - " if pct else "") + "mails the resource-group Owners at " + (marks or "no threshold"), "tone": "ok"})
    elif why.get("budget"):
        tiles.append({"label": "Budget alert", "value": "not readable", "sub": why["budget"], "tone": "warn"})
    else:
        tiles.append({"label": "Budget alert", "value": "none set", "sub": "run scripts\\deploy.ps1 -Stage budget", "tone": "warn"})
    tokens = got.get("tokens")
    if tokens is not None:
        total_tokens = sum(int(float(r.get("TotalTokens") or 0)) for r in tokens)
        users = {str(r.get("User")) for r in tokens if r.get("User")}
        tiles.append({"label": "Tokens metered (24 h)", "value": f"{total_tokens:,}", "sub": f"by {len(users)} user{'s' if len(users) != 1 else ''}, counted at the front door", "tone": ""})
        job.step(f"Token meter: {total_tokens:,} tokens in the last 24 hours", "ok")
    else:
        tiles.append({"label": "Tokens metered (24 h)", "value": "not readable", "sub": why.get("tokens") or "", "tone": "warn"})
        job.step(f"The token meter could not be read: {why.get('tokens')}", "fail")
    if limits:
        base = limits == jobs.FRONT_DOOR_DEFAULTS
        tiles.append({"label": "Per-user cap", "value": f"{limits['quota']:,} tokens / hour", "sub": f"{limits['rpm']} agent calls / minute" + ("" if base else " - not the baseline, click Reset demo"), "tone": "ok" if base else "warn"})
    elif ready:
        tiles.append({"label": "Per-user cap", "value": "not readable", "sub": why.get("limits") or "", "tone": "warn"})
    else:
        tiles.append({"label": "Per-user cap", "value": "no front door", "sub": "the agent front door is not deployed", "tone": "warn"})
    notes.append("Tokens are metered per user and per agent at the front door. This console does not invent a price per token: multiply by your negotiated model rate, or read it from the model line above.")
    notes.append("The cap is per user per hour at the front door, so one runaway agent stops at its own user's budget instead of becoming everybody's outage. Beat 7.4 proves it.")
    job.emit("finops", tiles=tiles, notes=notes)

    if cost:
        total = cost["total"] or 0.0
        rows = [{"Service": s["service"], "Month to date": f"${s['cost']:,.2f}", "Share": f"{100.0 * s['cost'] / total:.0f}%" if total else "", "Kind": s["kind"]} for s in services if s["cost"] >= 0.005]
        _emit_table(job, f"Where this month's spend went ({cost['currency']}, resource group, {'last reading' if cost.get('stale') else 'Azure Cost Management'})", rows,
                    query="Cost Management query: ActualCost, MonthToDate, grouped by ServiceName", lights={})
    if tokens is not None:
        rows = _per_user(tokens, limits["quota"] if limits else None)
        _emit_table(job, "LLM tokens per user and agent (last 24 hours, counted at the APIM front door)", rows or [{"Note": "No metered agent calls in the last 24 hours - run Beat 7.1 or any agent beat through the front door, wait a few minutes for the log, and refresh."}],
                    query="AbwTokenUsage(24h)", lights={"apim": "ok", "monitor": "ok"})
    usage_rows = got.get("usage")
    if usage_rows is not None:
        _emit_table(job, "Calls per user (last 7 days, as the MCP servers logged them - a call the gateway refuses never reaches a server)", _usage_rows(usage_rows), query="AbwUsageByUser(7d)", lights={"monitor": "ok"})
    elif why.get("usage"):
        job.step(f"Calls per user could not be read: {why['usage']}", "fail")
    job.finish("done", (f"${cost['total']:,.2f} month to date" if cost else "cost not available") + (f", {sum(int(float(r.get('TotalTokens') or 0)) for r in tokens):,} tokens metered in 24 h" if tokens is not None else ""))


# ======================================================================================= 7.4  the token budget guard
def _poll(job: jobs.Job, label: str, accept: Any, *, tries: int = 14, wait: float = 4.0, ignore_cancel: bool = False) -> Any:
    """Ask the front door (a cheap GET that spends no token) until `accept(resp)` is true. APIM applies a named-value change within seconds to about a minute."""
    token = ap.token(AI_AUDIENCE)
    url = _probe_url()
    for i in range(1, tries + 1):
        try:
            resp, secs = _probe_get(url, token)
        except Exception as exc:  # noqa: BLE001
            job.step(f"{label}: attempt {i} - {jobs.friendly(exc)}", "info")
            job.sleep(wait, ignore_cancel)
            continue
        code = str(_shaped(resp).get("code") or "")
        got = f"HTTP {resp.status_code}" + (f" {code}" if code else "")
        if accept(resp, code):
            job.step(f"{label}: {got}", "ok")
            return resp, secs
        job.step(f"{label}: attempt {i} - {got} (the change is still reaching the gateway)", "run")
        job.sleep(wait, ignore_cancel)
    return None


def _retry_after(resp: Any) -> int:
    try:
        return max(0, int(float(resp.headers.get("retry-after") or 0)))
    except (TypeError, ValueError):
        return 0


def _settle(job: jobs.Job, label: str, accept: Any, *, need: int = 3, tries: int = 24, wait: float = 2.0, ignore_cancel: bool = False) -> Any:
    """Probe the GET route AND the POST route (the one agent calls use), spending no token, until `need` rounds in a row answer as `accept(resp, code)` wants.
    Measured on this gateway: a changed named value reached the GET route about 5 s before the POST route (or the other way round), so one probe is not proof that the agent route has changed.
    A tripped rate limiter also keeps refusing for its Retry-After even after its limit is raised again - the loop says so instead of pretending the change is still travelling."""
    token = ap.token(AI_AUDIENCE)
    url = _probe_url()
    streak = 0
    shown: tuple[Any, float] = (None, 0.0)
    for i in range(1, tries + 1):
        try:
            got_get, secs_get = _probe_get(url, token)
            got_post, secs_post = _probe_post(token)
        except Exception as exc:  # noqa: BLE001
            streak = 0
            job.step(f"{label}: attempt {i} - {jobs.friendly(exc)}", "info")
            job.sleep(wait, ignore_cancel)
            continue
        said = [(r, str(_shaped(r).get("code") or "")) for r in (got_get, got_post)]
        if all(accept(r, c) for r, c in said):
            streak += 1
            if streak >= need:
                job.step(f"{label}: both routes agree - GET HTTP {got_get.status_code}, POST HTTP {got_post.status_code}, {need} rounds in a row", "ok")
                return (got_get, secs_get), (got_post, secs_post)
        else:
            streak = 0
            key = (got_get.status_code, got_post.status_code)
            if key != shown[0] or time.time() - shown[1] >= 10:
                shown = (key, time.time())
                locked = max((_retry_after(r) for r, c in said if c == "rate_limited"), default=0)
                why = f"the rate limiter is locked out for about {locked} more seconds (Retry-After)" if locked else "the change is still reaching the gateway"
                job.step(f"{label}: GET HTTP {key[0]}, POST HTTP {key[1]} - {why}", "run")
        job.sleep(wait, ignore_cancel)
    return None


def wait_open(job: jobs.Job, label: str = "Front door") -> bool:
    """Used by Reset demo: wait, even through a cancel, until both agent routes forward again (a tripped rate limiter has to run out its lock-out first)."""
    return bool(_settle(job, label, lambda r, c: r.status_code in (400, 404), need=2, tries=60, wait=3.0, ignore_cancel=True))


def _clear_of_the_hour(job: jobs.Job) -> None:
    """The token counter is per calendar hour: do not start a budget demo seconds before it resets."""
    now = dt.datetime.now(dt.timezone.utc)
    left = 3600 - (now.minute * 60 + now.second)
    if left < 150:
        job.step(f"The hourly token counter resets in {left} seconds - waiting for it so the reset cannot hide the budget cut", "info")
        job.sleep(left + 3)


def run_quota(job: jobs.Job) -> None:
    rate = str(job.params.get("mode") or "quota") == "rate"
    base = jobs.FRONT_DOOR_DEFAULTS
    if rate:
        job.say("A runaway loop must hit a ceiling. The front door allows each user a number of agent calls per minute; we drop that to one, fire a few calls, and watch the limiter lock the user out - "
                "then we put the limit back and wait out the lock-out.")
    else:
        job.say("An agent in a loop can burn a month of model budget in an afternoon. The front door counts LLM tokens per user per hour. We make one real call, "
                "cut this user's hourly budget to a single token, and watch the next call stop at the gateway - before the model is ever reached.")
    changed = False
    restored = True
    lock_s = 0
    seen = {"refused": False, "agent": False}
    try:
        if rate:
            ok = _poll(job, "Baseline", lambda r, c: r.status_code == 404)
            if not ok:
                raise RuntimeError("The front door is not forwarding calls right now (throttled or revoked). Wait a minute or click Reset demo, then try again.")
            job.step("Lowering this user's rate limit to 1 agent call per minute (APIM named value abw-agent-rpm)", "run")
            _set_named_value(NV_RPM, 1)
            changed = True
            hit = _settle(job, "Quick calls", lambda r, c: r.status_code == 429 and c == "rate_limited", need=2, tries=16, wait=3.0)
            if hit:
                seen["refused"] = True
                resp, secs = hit[1]
                lock_s = _retry_after(resp)
                info = catalog.REASONS["rate_limit"]
                job.emit("http", **_front_card("front door, calls beyond the limit", POST_PROBE_ARGS, resp, secs, verdict="denied", title="Rate limit - refused at the front door",
                                                plain=info["plain"] + " The answer carries Retry-After: " + str(resp.headers.get("retry-after") or "?") + " seconds.", wall=1, reason="rate_limit",
                                                lights={"user": "ok", "entra": "ok", "apim": "deny"}))
                job.say(f"Read Retry-After: the limiter does not only count, it locks this caller out for about {lock_s} seconds, so a looping agent cannot hammer its way back in. "
                        "Raising the limit again does not cut an armed lock-out short - the next step waits for it to run out.")
            else:
                job.step("The lower limit had not reached the gateway after about a minute - restoring.", "fail")
        else:
            _clear_of_the_hour(job)
            job.step("Baseline: one real agent call through the front door - the model spends tokens and APIM meters them", "run")
            first = jobs.agent_once(job, "abw-wall-desk", catalog.PROMPTS["crossings"], "yes", job.emit)
            if first["failure"] or not first["final"] or not first["final"].get("answer"):
                raise RuntimeError("The baseline agent call did not complete - see above. Fix that (or click Reset demo) and try again.")
            fin = first["final"]
            counted = fin.get("gateway_tokens")
            left = fin.get("tokens_remaining")
            job.step("The front door counted " + (f"{int(counted):,} tokens" if counted else "the tokens") + " for that call" + (f"; budget left this hour: {int(left):,} of {base['quota']:,}" if left is not None else ""), "ok")
            job.step("Cutting this user's hourly token budget to 1 token (APIM named value abw-agent-token-quota)", "run")
            _set_named_value(NV_QUOTA, 1)
            changed = True
            hit = _settle(job, "Probe both routes", lambda r, c: r.status_code == 403 and c == "token_quota_exceeded")
            if hit:
                seen["refused"] = True
                resp, secs = hit[1]
                info = catalog.REASONS["token_quota_exceeded"]
                job.emit("http", **_front_card("front door, budget used up", POST_PROBE_ARGS, resp, secs, verdict="denied", title="Token budget used up - refused at the front door",
                                                plain=info["plain"] + " Retry-After: " + str(resp.headers.get("retry-after") or "?") + " seconds.", wall=1, reason="token_quota_exceeded",
                                                lights={"user": "ok", "entra": "ok", "apim": "deny"}))
                job.say("Same user, same valid token. Now the real agent, which is what the budget is for:")
                for attempt in (1, 2):
                    second = jobs.agent_once(job, "abw-wall-desk", catalog.PROMPTS["crossings"], "yes", job.emit)
                    fail = second["failure"] or {}
                    if catalog.front_door_refusal(fail) and str(fail.get("code")) == "token_quota_exceeded":
                        seen["agent"] = True
                        rounds = (second["final"] or {}).get("rounds")
                        job.step("The agent run was refused at the front door" + (f" after {rounds} model rounds" if rounds else " - 0 model rounds, 0 tokens spent") + ": the model was never called.", "ok")
                        break
                    spent = (second["final"] or {}).get("gateway_tokens")
                    job.step("The agent call was admitted" + (f" and spent {int(spent):,} tokens" if spent else "") + " - the budget change had not reached the agent route yet." + (" Trying once more." if attempt == 1 else ""),
                             "info" if attempt == 1 else "fail")
            else:
                job.step("The lower budget had not reached the gateway after about a minute - restoring.", "fail")
    finally:
        if changed:
            job.step("Restoring the baseline budget and rate (always, even if a step above failed)", "run")
            try:
                _set_named_value(NV_QUOTA, base["quota"])
                _set_named_value(NV_RPM, base["rpm"])
                if rate and seen["refused"]:
                    job.step("Limit put back to " + str(base["rpm"]) + " calls per minute. Now waiting for the lock-out to run out (it is not lifted by the new limit)", "info")
                back = _settle(job, "After restore", lambda r, c: r.status_code in (400, 404), need=2, tries=60 if rate else 24, wait=3.0 if rate else 2.0, ignore_cancel=True)
                restored = bool(back)
                if not back:
                    job.step("The front door is not forwarding again yet - wait a minute, then click Reset demo.", "fail")
            except Exception as exc:  # noqa: BLE001
                restored = False
                job.step(f"Could not restore the front-door limits ({jobs.friendly(exc)}) - click Reset demo.", "fail")
    ok = seen["refused"] and (rate or seen["agent"]) and restored
    if rate:
        text = f"baseline OK -> 1 call per minute -> calls beyond it refused (429 rate_limited, Retry-After {lock_s} s) -> limit restored, lock-out waited out"
    else:
        text = "real call answered -> budget cut to 1 token -> next call refused at the front door (403 token_quota_exceeded, model never called) -> restored"
    if ok:
        msg = text
    elif seen["refused"] and not restored:
        msg = "The refusal was observed, but the front door has not confirmed it forwards again - click Reset demo."
    else:
        msg = "The refusal was not observed - see the steps above."
    job.finish("done" if ok else "failed", msg, **seen)
