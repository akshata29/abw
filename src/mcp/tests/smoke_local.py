"""Manual smoke script for local MCP protocol inspection."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
import sys

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import abw_mcp.auth as auth_module
from abw_mcp.app import create_app
from abw_mcp.audit import AuditService, InMemoryAuditSink
from abw_mcp.auth import JwksCache
from abw_mcp.config import Settings
from abw_mcp.runtime import RuntimeServices

from tests.conftest import FakeDataPlane, FakeObo, auth_headers, mcp_initialize


def make_settings() -> Settings:
    return Settings(
        mcp_server="research",
        tenant_id="tenant-123",
        mcp_app_client_id="research-client-guid",
        mcp_allowed_azp=("trusted-client",),
        mcp_required_scope="Tools.Read",
        uami_client_id="uami-guid",
        storage_account="storacct",
        cosmos_endpoint="https://cosmos.example.test",
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


def install_fake_jwks(signing_key) -> None:
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    public_jwk["kid"] = "kid-1"
    auth_module.jwks_cache = JwksCache(fetcher=lambda _: {"keys": [public_jwk]})


def mint_token(settings: Settings, signing_key) -> str:
    now = int(time.time())
    claims = {
        "iss": settings.issuer,
        "aud": settings.mcp_app_client_id,
        "tid": settings.tenant_id,
        "ver": "2.0",
        "scp": "Tools.Read",
        "roles": ["Research.Read"],
        "oid": "oid-priya",
        "preferred_username": "abw.priya@example.com",
        "azp": "trusted-client",
        "uti": "uti-priya",
        "exp": now + 3600,
        "nbf": now - 60,
        "iat": now,
    }
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "kid-1"})


async def main() -> None:
    settings = make_settings()
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    install_fake_jwks(signing_key)
    runtime = RuntimeServices(settings=settings, audit=None, data=FakeDataPlane(), obo=FakeObo(calls=[]))
    runtime.data.obo = runtime.obo
    sink = InMemoryAuditSink()
    runtime.audit = AuditService(runtime=runtime, sinks=[sink])
    app = create_app(settings=settings, runtime_overrides={"runtime": runtime})
    token = mint_token(settings, signing_key)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        headers = auth_headers(token)
        await mcp_initialize(client, headers)
        tools = await client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": "2", "method": "tools/list", "params": {}})
        call = await client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": "3", "method": "tools/call", "params": {"name": "search_research", "arguments": {"query": "ACME", "limit": 1}}},
        )
        print("tools/list:")
        print(json.dumps(tools.json(), indent=2))
        print("\ntools/call:")
        print(json.dumps(call.json(), indent=2))
        print("\naudit rows:")
        print(json.dumps(sink.events, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
