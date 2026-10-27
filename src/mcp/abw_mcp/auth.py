"""JWT validation and auth middleware for ABW MCP."""

from __future__ import annotations

import contextvars
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import jwt
import requests
from jwt import InvalidAudienceError, InvalidIssuerError, InvalidSignatureError
from jwt.algorithms import RSAAlgorithm
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings

logger = logging.getLogger(__name__)

current_caller: contextvars.ContextVar["Caller | None"] = contextvars.ContextVar("abw_current_caller", default=None)
current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("abw_request_id", default=None)


@dataclass(frozen=True, slots=True)
class Caller:
    """Validated caller identity."""

    oid: str
    upn: str | None
    tid: str
    roles: tuple[str, ...]
    scopes: tuple[str, ...]
    azp: str | None
    aud: str | None
    jti: str | None
    token: str = field(repr=False)


class AuthError(Exception):
    """Typed auth failure."""

    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code

    @property
    def status_code(self) -> int:
        return 403 if self.reason_code in {"missing_scope", "missing_role"} else 401

    @property
    def www_auth_error(self) -> str:
        return "insufficient_scope" if self.status_code == 403 else "invalid_token"


class JwksCache:
    """Simple JWKS cache with TTL and forced refresh on unknown kid."""

    def __init__(self, fetcher: Callable[[str], dict[str, Any]] | None = None, ttl_seconds: int = 3600) -> None:
        self._fetcher = fetcher or self._default_fetcher
        self._ttl_seconds = ttl_seconds
        self._expires_at = 0.0
        self._jwks: dict[str, Any] = {"keys": []}

    def get_key(self, jwks_url: str, kid: str | None) -> Any:
        if not kid:
            raise AuthError("bad_signature")
        keys = self._get_keys(jwks_url)
        key = self._find_key(keys, kid)
        if key is None:
            keys = self._refresh(jwks_url)
            key = self._find_key(keys, kid)
        if key is None:
            raise AuthError("bad_signature")
        return key

    def _get_keys(self, jwks_url: str) -> list[dict[str, Any]]:
        if time.time() >= self._expires_at:
            return self._refresh(jwks_url)
        return list(self._jwks.get("keys", []))

    def _refresh(self, jwks_url: str) -> list[dict[str, Any]]:
        self._jwks = self._fetcher(jwks_url)
        self._expires_at = time.time() + self._ttl_seconds
        return list(self._jwks.get("keys", []))

    @staticmethod
    def _find_key(keys: list[dict[str, Any]], kid: str) -> Any:
        for candidate in keys:
            if candidate.get("kid") == kid:
                return RSAAlgorithm.from_jwk(json.dumps(candidate))
        return None

    @staticmethod
    def _default_fetcher(jwks_url: str) -> dict[str, Any]:
        response = requests.get(jwks_url, timeout=10)
        response.raise_for_status()
        return response.json()


jwks_cache = JwksCache()


def verify_token(token: str, settings: Settings) -> Caller:
    """Validate an Entra JWT and return the caller."""

    if not token:
        raise AuthError("missing_token")
    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise AuthError("bad_signature") from exc

    try:
        public_key = jwks_cache.get_key(settings.jwks_url, header.get("kid"))
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=list(settings.audience_values),
            issuer=settings.issuer,
            leeway=60,
            options={"require": ["exp", "nbf", "iss", "aud"]},
        )
    except InvalidSignatureError as exc:
        raise AuthError("bad_signature") from exc
    except InvalidAudienceError as exc:
        raise AuthError("bad_audience") from exc
    except InvalidIssuerError as exc:
        raise AuthError("bad_issuer") from exc
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("expired") from exc
    except jwt.ImmatureSignatureError as exc:
        raise AuthError("not_yet_valid") from exc
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError("bad_signature") from exc

    if claims.get("ver") != "2.0":
        raise AuthError("bad_issuer")
    if claims.get("tid") != settings.tenant_id:
        raise AuthError("bad_tenant")
    if claims.get("idtyp") == "app" or not claims.get("oid"):
        raise AuthError("app_only")

    azp = claims.get("azp")
    if settings.mcp_allowed_azp and azp not in settings.mcp_allowed_azp:
        raise AuthError("bad_azp")

    scopes = tuple(scope for scope in str(claims.get("scp", "")).split(" ") if scope)
    if settings.mcp_required_scope not in scopes:
        raise AuthError("missing_scope")

    roles = tuple(sorted({str(role) for role in claims.get("roles", [])}))
    return Caller(
        oid=str(claims["oid"]),
        upn=claims.get("preferred_username"),
        tid=str(claims["tid"]),
        roles=roles,
        scopes=scopes,
        azp=azp,
        aud=str(claims.get("aud")) if claims.get("aud") is not None else None,
        jti=str(claims.get("uti") or claims.get("jti") or ""),
        token=token,
    )


class RequestContextMiddleware:
    """Populate request-scoped contextvars."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_id = None
        if scope["type"] == "http":
            headers = Headers(scope=scope)
            request_id = headers.get("x-abw-request-id") or headers.get("x-request-id") or headers.get("x-ms-request-id") or headers.get("traceparent")
        token = current_request_id.set(request_id or f"req-{int(time.time() * 1000)}")
        try:
            await self.app(scope, receive, send)
        finally:
            current_request_id.reset(token)


class BearerAuthMiddleware:
    """Protect the MCP endpoint with JWT validation."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        prm_url_builder: Callable[[Request], str],
        audit_service: Any,
        authorization_check: Callable[[Caller], tuple[bool, str | None]] | None = None,
    ) -> None:
        self.app = app
        self.settings = settings
        self.prm_url_builder = prm_url_builder
        self.audit_service = audit_service
        self.authorization_check = authorization_check

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/mcp":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        auth_header = request.headers.get("authorization", "")
        token = auth_header[7:] if auth_header.lower().startswith("bearer ") else ""

        try:
            caller = verify_token(token, self.settings)
            if self.authorization_check is not None:
                ok, reason = self.authorization_check(caller)
                if not ok:
                    raise AuthError(reason or "missing_role")
        except AuthError as exc:
            self.audit_service.emit(
                self.audit_service.build_event(
                    event="auth_failed",
                    tool=None,
                    decision="deny",
                    reason=exc.reason_code,
                    caller=None,
                    data_class=None,
                    args=None,
                    result_bytes=0,
                    obo=False,
                    downstream={},
                    request_id=current_request_id.get(),
                )
            )
            response = self._auth_error_response(request, exc)
            await response(scope, receive, send)
            return

        token_var = current_caller.set(caller)
        try:
            await self.app(scope, receive, send)
        finally:
            current_caller.reset(token_var)

    def _auth_error_response(self, request: Request, exc: AuthError) -> Response:
        prm_url = self.prm_url_builder(request)
        www_auth = (
            f'Bearer realm="abw", error="{exc.www_auth_error}", '
            f'error_description="{exc.reason_code}", resource_metadata="{prm_url}"'
        )
        return JSONResponse(
            {"error": exc.www_auth_error, "error_description": exc.reason_code},
            status_code=exc.status_code,
            headers={"WWW-Authenticate": www_auth},
        )
