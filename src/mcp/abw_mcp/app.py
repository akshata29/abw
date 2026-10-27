"""ASGI app factory for Agents Behind the Wall MCP servers."""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any, Callable

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.util.http import parse_excluded_urls
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from azure.monitor.opentelemetry import configure_azure_monitor

from .audit import AuditService, build_default_audit_service
from .auth import BearerAuthMiddleware, Caller, RequestContextMiddleware, current_caller
from .config import Settings
from .data import DataPlaneClients
from .obo import OboBroker, OboError
from .registry import ToolError, ToolRegistry
from .runtime import RuntimeServices
from .servers import actions, legacy, private, research, vendor, wall
from .util import compact_json

logger = logging.getLogger(__name__)

SERVER_SCOPES = {
    "research": ["Tools.Read"],
    "wall": ["Tools.Read"],
    "actions": ["Tools.Read", "Tools.Execute"],
    "private": ["Tools.Read"],
    "vendor": ["Tools.Read"],
    "legacy": ["Tools.Read"],
}


def _build_registry(runtime: RuntimeServices) -> ToolRegistry:
    if runtime.settings.mcp_server == "research":
        return ToolRegistry(runtime, research.build_tools())
    if runtime.settings.mcp_server == "wall":
        return ToolRegistry(runtime, wall.build_tools())
    if runtime.settings.mcp_server == "actions":
        return ToolRegistry(runtime, actions.build_tools())
    if runtime.settings.mcp_server == "private":
        return ToolRegistry(runtime, private.build_tools())
    if runtime.settings.mcp_server == "vendor":
        return ToolRegistry(runtime, vendor.build_tools())
    return ToolRegistry(runtime, legacy.build_tools(), default_reason="no_user_context")


def _configure_observability(settings: Settings) -> None:
    if not settings.applicationinsights_connection_string:
        return
    configure_azure_monitor(
        connection_string=settings.applicationinsights_connection_string,
        logger_name="abw.audit",
        resource=Resource.create({ResourceAttributes.SERVICE_NAME: f"ca-abw-mcp-{settings.mcp_server}"}),
    )


def build_runtime(settings: Settings, overrides: dict[str, Any] | None = None) -> RuntimeServices:
    overrides = overrides or {}
    obo = overrides.get("obo")
    if obo is None and settings.mcp_server not in {"vendor", "legacy"}:
        obo = OboBroker(settings)
    runtime = RuntimeServices(
        settings=settings,
        audit=overrides.get("audit"),
        data=overrides.get("data"),
        obo=obo,
    )
    if runtime.data is None:
        runtime.data = DataPlaneClients(settings=settings, obo=runtime.obo)
    if runtime.audit is None:
        runtime.audit = build_default_audit_service(runtime)
    return runtime


def derive_public_base_url(request: Request, settings: Settings) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    forwarded_host = request.headers.get("x-forwarded-host")
    host = forwarded_host or request.headers.get("host") or request.url.netloc
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    prefix = request.headers.get("x-forwarded-prefix", "").rstrip("/")
    return f"{proto}://{host}{prefix}"


def _build_prm_payload(request: Request, settings: Settings) -> dict[str, Any]:
    resource = f"{derive_public_base_url(request, settings)}/mcp"
    return {
        "resource": resource,
        "authorization_servers": [f"{settings.issuer}"],
        "scopes_supported": (
            [f"api://{settings.mcp_app_client_id}/{scope}" for scope in SERVER_SCOPES[settings.mcp_server]]
            if settings.mcp_app_client_id
            else []
        ),
        "bearer_methods_supported": ["header"],
    }


class VendorKeyMiddleware:
    """Require the APIM-injected vendor key."""

    def __init__(self, app: ASGIApp, expected_key: str, runtime: RuntimeServices) -> None:
        self.app = app
        self.expected_key = expected_key
        self.runtime = runtime
        self.logger = logging.getLogger("abw.vendor")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/mcp":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        vendor_key = request.headers.get("x-vendor-key", "")
        log_event = {
            "event": "vendor_request",
            "tool": None,
            "saw_authorization_header": bool(request.headers.get("authorization")),
            "saw_vendor_key": bool(vendor_key),
            "client_ip": (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host if request.client else None),
        }
        self.logger.info(compact_json(log_event))
        if not hmac.compare_digest(vendor_key.encode("utf-8"), self.expected_key.encode("utf-8")):
            response = JSONResponse({"error": "invalid_vendor_key"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class AutoStartingSessionApp:
    """Ensure the MCP session manager is running before request handling."""

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self.session_manager = session_manager
        self._app = StreamableHTTPASGIApp(session_manager)
        self._lock = anyio.Lock()
        self._run_context = None
        self._started = False

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            self._run_context = self.session_manager.run()
            await self._run_context.__aenter__()
            self._started = True

    async def stop(self) -> None:
        async with self._lock:
            if not self._started or self._run_context is None:
                return
            await self._run_context.__aexit__(None, None, None)
            self._run_context = None
            self._started = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.start()
        await self._app(scope, receive, send)


class LazyApp:
    """Build the Starlette app on first use so env vars can be set at runtime."""

    def __init__(self) -> None:
        self._app: Starlette | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._app is None:
            self._app = create_app()
        await self._app(scope, receive, send)


def create_app(settings: Settings | None = None, runtime_overrides: dict[str, Any] | None = None) -> Starlette:
    settings = settings or Settings.from_env()
    _configure_observability(settings)
    runtime = runtime_overrides.get("runtime") if runtime_overrides else None
    if runtime is None:
        runtime = build_runtime(settings, runtime_overrides)
    registry = _build_registry(runtime)

    async def on_list_tools(ctx, params):
        return await registry.list_tools(current_caller.get())

    async def on_call_tool(ctx, params):
        return await registry.call_tool(current_caller.get(), params.name, params.arguments)

    server = Server(
        f"abw-{settings.mcp_server}",
        version="0.1.0",
        title=f"ABW {settings.mcp_server} MCP",
        description=f"Agents Behind the Wall {settings.mcp_server} server",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    streamable_app = AutoStartingSessionApp(session_manager)

    async def healthz(_: Request):
        return JSONResponse({"status": "ok", "server": settings.mcp_server})

    async def protected_resource_metadata(request: Request):
        return JSONResponse(_build_prm_payload(request, settings))

    routes = [
        Route("/mcp", endpoint=streamable_app, methods=["GET", "POST", "DELETE"]),
        Route("/healthz", endpoint=healthz, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", endpoint=protected_resource_metadata, methods=["GET"]),
    ]

    @asynccontextmanager
    async def lifespan(_: Starlette):
        runtime.audit.start()
        await streamable_app.start()
        yield
        await streamable_app.stop()
        runtime.audit.stop()

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.runtime = runtime
    app.state.registry = registry
    if settings.mcp_server == "vendor":
        app.add_middleware(VendorKeyMiddleware, expected_key=settings.vendor_api_key or "", runtime=runtime)
    elif settings.mcp_server not in {"legacy"}:
        app.add_middleware(
            BearerAuthMiddleware,
            settings=settings,
            prm_url_builder=lambda request: f"{derive_public_base_url(request, settings)}/.well-known/oauth-protected-resource",
            audit_service=runtime.audit,
        )
    # Starlette wraps in reverse order of registration: OpenTelemetry is outermost (spans cover auth failures),
    # then request-context (request id available to the auth audit events), then the auth middleware.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(OpenTelemetryMiddleware, excluded_urls=parse_excluded_urls("healthz"))
    return app


app = LazyApp()
