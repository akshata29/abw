"""Agents Behind the Wall - Demo Console server.

A small local web app (Starlette, 127.0.0.1 only) that runs every demo beat against the real Azure tenant and lets the
presenter open each real service. It owns no state of its own: jobs live in `jobs.MANAGER`, live facts come from
`azure_probe`, story content comes from `catalog`.

    python console\\server.py            # opens http://127.0.0.1:8787  (or double-click Start-Console.bat)
    python console\\server.py --no-browser --port 8787

If the port is busy the next free one is used and the right address is printed and opened.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, AsyncIterator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "demo"))

import uvicorn  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import FileResponse, JSONResponse, Response  # noqa: E402
from starlette.routing import Route  # noqa: E402

import azure_probe as ap  # noqa: E402
import catalog  # noqa: E402
import jobs  # noqa: E402
import personas  # noqa: E402

log = logging.getLogger("console.server")
WEB = HERE / "web"
EVIDENCE = ROOT / "demo" / "evidence"
POLICIES = {
    "mcp-jwt": ROOT / "infra" / "apim" / "policies" / "mcp-jwt.policy.xml",
    "mcp-legacy": ROOT / "infra" / "apim" / "policies" / "mcp-legacy.policy.xml",
    "prm": ROOT / "infra" / "apim" / "policies" / "prm.policy.xml",
}
EVIDENCE_NAME = re.compile(r"^(prove|try-violations|burst)-[0-9T_-]+\.json$")
NO_STORE = {"Cache-Control": "no-store"}
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}


class Json(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")


def ok(data: Any, status: int = 200) -> Json:
    return Json(data, status_code=status, headers=NO_STORE)


def err(message: str, status: int = 400) -> Json:
    return Json({"error": message}, status_code=status, headers=NO_STORE)


async def body_of(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


# ----------------------------------------------------------------------------------------------------- static
async def index(request: Request) -> Response:
    return FileResponse(WEB / "index.html", media_type=MIME[".html"], headers=NO_STORE)


async def asset(request: Request) -> Response:
    name = request.path_params["name"]
    path = (WEB / name).resolve()
    if WEB.resolve() not in path.parents or not path.is_file():
        return err("Not found.", 404)
    return FileResponse(path, media_type=MIME.get(path.suffix.lower(), "application/octet-stream"), headers=NO_STORE)


# -------------------------------------------------------------------------------------------------- catalog
_CATALOG: dict[str, Any] = {}


async def api_catalog(request: Request) -> Response:
    if not _CATALOG:
        _CATALOG.update(
            tenant=ap.TENANT,
            tenantDomain=ap.CFG.get("tenantDomain", ""),
            operator=jobs.OPERATOR,
            resourceGroup=ap.RG,
            asks=catalog.ASKS,
            scenes=catalog.SCENES,
            nodes=catalog.NODES,
            strip=catalog.STRIP,
            walls=catalog.WALLS,
            kql={k: {"title": v["title"], "q": v["q"], "hours": v["hours"]} for k, v in catalog.KQL.items()},
            probes=list(ap.PROBES),
        )
    return ok(_CATALOG)


# ---------------------------------------------------------------------------------------------------- status
async def api_status(request: Request) -> Response:
    fresh = request.query_params.get("fresh") == "1"
    if fresh:
        jobs.invalidate_status()
    data = await run_in_threadpool(jobs.status_lights)
    active = [{"id": j.id, "kind": j.kind, "title": j.title, "beat": j.beat, "status": j.status} for j in jobs.MANAGER.active()]
    return ok({**data, "active": active, "busy": bool(active)})


# ------------------------------------------------------------------------------------------------------ jobs
async def api_jobs_start(request: Request) -> Response:
    data = await body_of(request)
    kind = str(data.get("kind") or "")
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    job, message = await run_in_threadpool(jobs.MANAGER.start, kind, params, str(data.get("title") or kind)[:120], str(data.get("beat") or "")[:12])
    if job is None:
        return err(message, 409)
    return ok({"id": job.id, "status": job.status})


async def api_jobs_list(request: Request) -> Response:
    rows = [{"id": j.id, "kind": j.kind, "title": j.title, "beat": j.beat, "status": j.status, "elapsed": round((j.ended or time.time()) - j.started, 1),
             "summary": j.result.get("summary", "")} for j in reversed(list(jobs.MANAGER.jobs.values()))]
    return ok(rows[:30])


async def api_job(request: Request) -> Response:
    job = jobs.MANAGER.get(request.path_params["job_id"])
    if job is None:
        return err("Unknown job (the console was restarted?).", 404)
    try:
        since = max(0, int(request.query_params.get("since", "0")))
    except ValueError:
        since = 0
    return ok(job.view(since))


async def api_job_approve(request: Request) -> Response:
    job = jobs.MANAGER.get(request.path_params["job_id"])
    if job is None:
        return err("Unknown job.", 404)
    data = await body_of(request)
    done, message = await run_in_threadpool(job.answer, str(data.get("id") or ""), bool(data.get("approve")))
    return ok({"ok": done, "message": message}) if done else err(message, 409)


async def api_job_cancel(request: Request) -> Response:
    job = jobs.MANAGER.get(request.path_params["job_id"])
    if job is None:
        return err("Unknown job.", 404)
    await run_in_threadpool(job.cancel)
    return ok({"ok": True})


# ---------------------------------------------------------------------------------------------------- probes
async def api_probe(request: Request) -> Response:
    pid = request.path_params["pid"]
    if pid not in ap.PROBES:
        return ok(ap._res(pid, "na", "No live probe for this component - use the portal link or the click-path."))
    return ok(await run_in_threadpool(ap.run_probe, pid, force=request.query_params.get("force") == "1"))


async def api_probes(request: Request) -> Response:
    ids = [i for i in request.query_params.get("ids", "").split(",") if i in ap.PROBES] or list(ap.PROBES)
    return ok(await run_in_threadpool(ap.run_many, ids, force=request.query_params.get("force") == "1"))


# ---------------------------------------------------------------------------------------------------- evidence
async def api_policy(request: Request) -> Response:
    path = POLICIES.get(request.path_params["name"])
    if path is None or not path.is_file():
        return err("Unknown policy.", 404)
    return Response(path.read_text(encoding="utf-8-sig"), media_type="text/plain; charset=utf-8", headers=NO_STORE)


async def api_gateway_policy(request: Request) -> Response:
    """The policy API Management is enforcing on one MCP server right now. Never answers from the repo template."""
    server = request.path_params["server"]
    if server not in ap.GATEWAY_SERVERS:
        return err("Unknown server.", 404)
    try:
        return ok(await run_in_threadpool(ap.gateway_policy, server))
    except ap.ProbeError as exc:
        return err(f"Could not read the live policy from API Management: {exc}", 502)


async def api_scoreboard(request: Request) -> Response:
    path = EVIDENCE / "scoreboard.json"
    if not path.is_file():
        return ok([])
    return ok(json.loads(path.read_text(encoding="utf-8-sig")))


async def api_evidence(request: Request) -> Response:
    name = request.path_params["name"]
    path = EVIDENCE / name
    if not EVIDENCE_NAME.match(name) or not path.is_file():
        return err("Unknown evidence file.", 404)
    return Response(path.read_text(encoding="utf-8-sig"), media_type="application/json; charset=utf-8", headers=NO_STORE)


async def api_health(request: Request) -> Response:
    return ok({"ok": True, "operator": jobs.OPERATOR, "jobs": len(jobs.MANAGER.jobs)})


# ------------------------------------------------------------------------------------------------- personas
async def persona_action(request: Request, action: Any, *extra: Any) -> Response:
    """Run one blocking persona helper off the event loop. Messages are for the presenter and never carry a password, code or key."""
    pid = str(request.path_params["pid"])
    if pid not in personas.IDS:
        return err("Unknown persona.", 404)
    try:
        return ok(await run_in_threadpool(action, pid, *extra))
    except personas.NeedsSignIn as exc:
        return err(str(exc), 409)
    except ValueError as exc:
        return err(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        log.warning("persona action failed: %s", type(exc).__name__)
        return err(jobs.friendly(exc), 502)


def _cancel_login(pid: str) -> dict[str, Any]:
    personas.cancel_login(pid)
    return {"login": personas.login_view(pid)}


def _save_totp(pid: str, secret: str) -> dict[str, Any]:
    personas.set_totp(pid, secret)
    return {"hasTotp": True, **personas.totp_now(pid)}


async def api_personas(request: Request) -> Response:
    return ok(await run_in_threadpool(personas.state))


async def api_persona_login(request: Request) -> Response:
    return await persona_action(request, personas.start_login)


async def api_persona_login_cancel(request: Request) -> Response:
    return await persona_action(request, _cancel_login)


async def api_persona_verify(request: Request) -> Response:
    return await persona_action(request, personas.verify)


async def api_persona_totp(request: Request) -> Response:
    data = await body_of(request)
    return await persona_action(request, _save_totp, str(data.get("secret") or "")[:600])


async def api_persona_code(request: Request) -> Response:
    return await persona_action(request, personas.totp_now)


async def api_persona_password(request: Request) -> Response:
    return await persona_action(request, personas.clip_password)


async def api_persona_open(request: Request) -> Response:
    return await persona_action(request, personas.open_private_window)


# ------------------------------------------------------------------------------------------------- the app
class SameOriginMiddleware:
    """A page on another origin must not be able to press the revoke button: POSTs need a same-origin Origin header."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            origin = headers.get("origin", "")
            host = headers.get("host", "")
            if not origin or origin.split("://", 1)[-1] != host:
                await Json({"error": "Cross-origin request refused."}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """The console is local, but it is shown on a shared screen next to live tenant data: no framing, no sniffing, no outside resources."""

    HEADERS = (
        (b"x-frame-options", b"DENY"),
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"no-referrer"),
        (
            b"content-security-policy",
            b"default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; "
            b"form-action 'none'; object-src 'none'; frame-ancestors 'none'",
        ),
    )

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        ours = {name for name, _ in self.HEADERS}

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in ours]
                message = {**message, "headers": kept + list(self.HEADERS)}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def warm_up() -> None:
    """Mint tokens and fill the status cache so the first page load is quick."""
    try:
        jobs.status_lights()
        ap.run_many(["foundry", "apim", "monitor"])
    except Exception as exc:  # noqa: BLE001 - the page shows the real error when you press a button
        log.warning("warm-up skipped: %s", exc)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    threading.Thread(target=warm_up, daemon=True, name="warm-up").start()
    yield


def free_port(start: int) -> int:
    for port in range(start, start + 25):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit(f"No free port between {start} and {start + 24}. Close other local servers and try again.")


def build_app() -> Starlette:
    routes = [
        Route("/", index),
        Route("/web/{name:path}", asset),
        Route("/api/health", api_health),
        Route("/api/catalog", api_catalog),
        Route("/api/status", api_status),
        Route("/api/jobs", api_jobs_start, methods=["POST"]),
        Route("/api/jobs", api_jobs_list, methods=["GET"]),
        Route("/api/jobs/{job_id}", api_job),
        Route("/api/jobs/{job_id}/approve", api_job_approve, methods=["POST"]),
        Route("/api/jobs/{job_id}/cancel", api_job_cancel, methods=["POST"]),
        Route("/api/probe/{pid}", api_probe),
        Route("/api/probes", api_probes),
        Route("/api/policy/{name}", api_policy),
        Route("/api/gateway-policy/{server}", api_gateway_policy),
        Route("/api/scoreboard", api_scoreboard),
        Route("/api/evidence/{name}", api_evidence),
        Route("/api/personas", api_personas),
        Route("/api/personas/{pid}/login", api_persona_login, methods=["POST"]),
        Route("/api/personas/{pid}/login/cancel", api_persona_login_cancel, methods=["POST"]),
        Route("/api/personas/{pid}/verify", api_persona_verify, methods=["POST"]),
        Route("/api/personas/{pid}/totp", api_persona_totp, methods=["POST"]),
        Route("/api/personas/{pid}/code", api_persona_code, methods=["POST"]),
        Route("/api/personas/{pid}/password", api_persona_password, methods=["POST"]),
        Route("/api/personas/{pid}/open", api_persona_open, methods=["POST"]),
    ]
    middleware = [
        Middleware(SecurityHeadersMiddleware),
        Middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"]),
        Middleware(SameOriginMiddleware),
    ]
    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


def ensure_az_login() -> None:
    """Every token the console uses comes from the operator's `az login` cache - make sure it exists before the page opens."""
    az = shutil.which("az")
    if not az:
        raise SystemExit("\n  The Azure CLI (az) was not found. Install it from https://aka.ms/installazurecliwindows and start the console again.\n")
    want_user = str(ap.CFG.get("operatorUpn", "")).lower()

    def signed_in() -> tuple[str, str]:
        res = subprocess.run([az, "account", "show", "-o", "json"], capture_output=True, text=True, timeout=90)
        if res.returncode != 0:
            return "", ""
        info = json.loads(res.stdout or "{}")
        return str(info.get("tenantId", "")).lower(), str((info.get("user") or {}).get("name", "")).lower()

    tenant, user = signed_in()
    if tenant == ap.TENANT.lower():
        if want_user and user != want_user:
            print(f"  Note: az is signed in as {user}; the demo was set up as {want_user}.")
        return
    print(f"\n  Azure sign-in needed: sign in as {want_user} ({ap.CFG.get('tenantDomain', ap.TENANT)}). A browser window will open.\n")
    if subprocess.run([az, "login", "--tenant", ap.TENANT]).returncode != 0:
        raise SystemExit("\n  The Azure sign-in did not complete. Start the console again when you are ready.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Agents Behind the Wall - Demo Console")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-az-check", action="store_true", help="do not verify the az CLI sign-in before starting")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not args.skip_az_check:
        ensure_az_login()
    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    if not args.no_browser:
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    print(f"\n  Agents Behind the Wall - Demo Console\n  {url}\n  (leave this window open; close it to stop the console)\n")
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
