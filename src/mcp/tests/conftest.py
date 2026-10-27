"""Shared pytest fixtures for ABW MCP."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from abw_mcp.app import create_app
from abw_mcp.audit import AuditService, InMemoryAuditSink
from abw_mcp.auth import JwksCache
from abw_mcp.config import Settings
from abw_mcp.data import DataAccessError
from abw_mcp.obo import OboError
from abw_mcp.runtime import RuntimeServices

import abw_mcp.auth as auth_module

PROTOCOL_VERSION = "2025-03-26"


@dataclass(slots=True)
class FakeObo:
    """Simple fake OBO broker."""

    error_code: str | None = None
    calls: list[tuple[str, str]] | None = None

    def get_credential(self, caller, scope: str):
        if self.calls is not None:
            self.calls.append((caller.oid, scope))
        if self.error_code:
            raise OboError(self.error_code)
        return object()


class FakeDataPlane:
    """Pure-Python fake data plane for offline tests."""

    def __init__(self) -> None:
        self.blob_calls: list[tuple[str, str, bool]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.order_writes: list[dict[str, Any]] = []
        self.deny_blob_containers: set[str] = set()
        self.blobs = {
            ("research-public", "RN-001.md"): "SYNTHETIC DEMO DATA — NOT REAL\n\n# Public ACME Note\n\ncontent canary-doc",
            ("wall-falcon", "FALCON-001.md"): "SYNTHETIC DEMO DATA — NOT REAL\nMNPI — WALL-CROSSED ONLY\n\n# Falcon Memo\n\nfalcon content",
            ("wall-orion", "ORION-001.md"): "SYNTHETIC DEMO DATA — NOT REAL\nMNPI — WALL-CROSSED ONLY\n\n# Orion Memo\n\norion content",
        }
        self.search_rows = [
            {"id": "RN-001", "title": "Public ACME Note", "ticker": "ACME", "snippet": "public snippet", "updated": "2026-10-13T00:00:00Z"},
        ]
        self.wall_rows = {
            "falcon": [{"id": "FALCON-001", "title": "Falcon Memo", "summary": "falcon summary", "updated": "2026-10-13T00:00:00Z"}],
            "orion": [{"id": "ORION-001", "title": "Orion Memo", "summary": "orion summary", "updated": "2026-10-13T00:00:00Z"}],
        }
        self.restricted = {
            "ZYNX": {"id": "ZYNX", "ticker": "ZYNX", "project": "falcon", "reason": "deal-restricted"},
            "VRDN": {"id": "VRDN", "ticker": "VRDN", "project": "orion", "reason": "deal-restricted"},
        }
        self.orders_by_user = {
            "oid-carla": [
                {"id": "ord-1", "user_oid": "oid-carla", "user_upn": "abw.carla@example.com", "ticker": "ACME", "side": "BUY", "quantity": 100, "status": "ACCEPTED", "source": "mcp-actions", "created": "2026-10-13T00:00:00Z"}
            ]
        }
        self.positions = {
            "rates": [{"id": "rates-1", "ticker": "UST2", "quantity": 1, "market_value_usd": 2}],
            "credit": [
                {"id": "credit-1", "ticker": "IGETF", "quantity": 5, "market_value_usd": 10},
                {"id": "limit-northwind-capital", "counterparty": "Northwind Capital", "limit_usd": 1000, "utilization_usd": 600},
            ],
        }
        self.obo: FakeObo | None = None

    def _maybe_obo(self, caller, use_user_token: bool, scope: str) -> None:
        if use_user_token and self.obo is not None:
            self.obo.get_credential(caller, scope)

    async def read_blob_text(self, *, caller, container: str, blob_name: str, use_user_token: bool = True) -> str:
        self.blob_calls.append((container, blob_name, use_user_token))
        self._maybe_obo(caller, use_user_token, "https://storage.azure.com/user_impersonation")
        if container in self.deny_blob_containers:
            raise DataAccessError("FORBIDDEN", "Storage access denied.", reason="storage_rbac_denied", status_code=403)
        return self.blobs[(container, blob_name)]

    async def search_documents(self, *, caller, query: str, filter_text: str | None, select: list[str], top: int, use_user_token: bool = True) -> list[dict[str, Any]]:
        self.search_calls.append({"query": query, "filter": filter_text, "top": top, "use_user_token": use_user_token})
        self._maybe_obo(caller, use_user_token, "https://search.azure.com/user_impersonation")
        if filter_text == "classification eq 'public'":
            return self.search_rows[:top]
        if "project eq 'falcon'" in str(filter_text):
            return self.wall_rows["falcon"][:top]
        if "project eq 'orion'" in str(filter_text):
            return self.wall_rows["orion"][:top]
        return (self.search_rows + self.wall_rows["falcon"] + self.wall_rows["orion"])[:top]

    async def cosmos_read_item(self, *, caller, container: str, item_id: str, partition_key: str, use_user_token: bool, user_scope: str | None = None):
        if container == "restricted":
            return self.restricted.get(item_id)
        if container == "positions" and partition_key == "credit":
            for item in self.positions["credit"]:
                if item["id"] == item_id:
                    return item
            return None
        return None

    async def cosmos_query_items(self, *, caller, container: str, query: str, parameters: list[dict[str, Any]], partition_key: str | None, use_user_token: bool, user_scope: str | None = None):
        if use_user_token and self.obo is not None:
            self.obo.get_credential(caller, user_scope or "https://cosmos.azure.com/user_impersonation")
        if container == "orders":
            oid = next(item["value"] for item in parameters if item["name"] == "@user_oid")
            limit = next(item["value"] for item in parameters if item["name"] == "@limit")
            return self.orders_by_user.get(oid, [])[:limit]
        if container == "positions":
            return self.positions.get(partition_key or "", [])
        return []

    async def cosmos_upsert_item(self, *, caller, container: str, item: dict[str, Any], use_user_token: bool, user_scope: str | None = None):
        if use_user_token and self.obo is not None:
            self.obo.get_credential(caller, user_scope or "https://cosmos.azure.com/user_impersonation")
        self.order_writes.append(item)
        self.orders_by_user.setdefault(item["user_oid"], []).insert(0, item)
        return item

    def credit_limit_id(self, counterparty: str) -> str:
        return "limit-" + counterparty.strip().lower().replace(" ", "-")


@pytest.fixture(scope="session")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def patched_jwks(monkeypatch, signing_key):
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    public_jwk["kid"] = "kid-1"
    monkeypatch.setattr(auth_module, "jwks_cache", JwksCache(fetcher=lambda _: {"keys": [public_jwk]}))
    return public_jwk


@pytest.fixture()
def settings_factory():
    def _factory(server: str, required_scope: str = "Tools.Read") -> Settings:
        return Settings(
            mcp_server=server,
            tenant_id="tenant-123",
            mcp_app_client_id=f"{server}-client-guid",
            mcp_allowed_azp=("trusted-client",),
            mcp_required_scope=required_scope,
            uami_client_id="uami-guid",
            storage_account="storacct",
            cosmos_endpoint="https://cosmos.example.test:443/",
            cosmos_database="abw",
            search_endpoint="https://search.example.test",
            search_index="deals-idx",
            audit_storage_account="auditacct",
            audit_container="worm-audit",
            audit_fail_closed=False,
            applicationinsights_connection_string=None,
            log_level="INFO",
            public_base_url="https://public.example.test",
            cosmos_obo=True,
            cosmos_obo_scope="https://cosmos.azure.com/user_impersonation",
            vendor_api_key="vendor-secret",
        )

    return _factory


@pytest.fixture()
def token_factory(signing_key):
    def _factory(settings: Settings, *, scopes: str = "Tools.Read", roles: list[str] | None = None, oid: str = "oid-user", upn: str = "user@example.com", azp: str = "trusted-client", aud: str | None = None, tid: str | None = None, iss: str | None = None, exp_delta: int = 3600, nbf_delta: int = -60, extra: dict[str, Any] | None = None) -> str:
        now = int(time.time())
        claims = {
            "iss": iss or settings.issuer,
            "aud": aud or settings.mcp_app_client_id,
            "tid": tid or settings.tenant_id,
            "ver": "2.0",
            "scp": scopes,
            "roles": roles or [],
            "oid": oid,
            "preferred_username": upn,
            "azp": azp,
            "uti": f"uti-{oid}",
            "exp": now + exp_delta,
            "nbf": now + nbf_delta,
            "iat": now,
        }
        if extra:
            claims.update(extra)
        return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "kid-1"})

    return _factory


def build_runtime(settings: Settings, *, data: FakeDataPlane | None = None, obo: FakeObo | None = None):
    data = data or FakeDataPlane()
    obo = obo or FakeObo(calls=[])
    data.obo = obo
    runtime = RuntimeServices(settings=settings, audit=None, data=data, obo=obo)
    sink = InMemoryAuditSink()
    runtime.audit = AuditService(runtime=runtime, sinks=[sink])
    return runtime, data, sink


@pytest_asyncio.fixture()
async def app_client_factory():
    clients: list[AsyncClient] = []

    async def _factory(settings: Settings, *, runtime: RuntimeServices):
        app = create_app(settings=settings, runtime_overrides={"runtime": runtime})
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        clients.append(client)
        return client

    yield _factory

    for client in clients:
        await client.aclose()


def auth_headers(token: str | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra:
        headers.update(extra)
    return headers


async def mcp_initialize(client: AsyncClient, headers: dict[str, str]) -> None:
    init = {
        "jsonrpc": "2.0",
        "id": "init-1",
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    }
    response = await client.post("/mcp", headers=headers, json=init)
    assert response.status_code == 200, response.text
    notify = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    notify_response = await client.post("/mcp", headers=headers, json=notify)
    assert notify_response.status_code in {200, 202}, notify_response.text
