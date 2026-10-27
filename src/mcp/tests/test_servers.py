"""In-process MCP server tests."""

from __future__ import annotations

import dataclasses
import json

import pytest

from abw_mcp.util import canonical_json

from .conftest import FakeObo, auth_headers, build_runtime, mcp_initialize


@pytest.mark.asyncio
async def test_auth_header_semantics(settings_factory, token_factory, patched_jwks, app_client_factory):
    settings = settings_factory("research")
    runtime, _, sink = build_runtime(settings)
    client = await app_client_factory(settings, runtime=runtime)

    response = await client.post("/mcp", headers=auth_headers(), json={"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}})
    assert response.status_code == 401
    assert 'resource_metadata="https://public.example.test/.well-known/oauth-protected-resource"' in response.headers["WWW-Authenticate"]

    wrong_scope = token_factory(settings, scopes="Wrong.Scope", roles=["Research.Read"])
    response = await client.post("/mcp", headers=auth_headers(wrong_scope), json={"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}})
    assert response.status_code == 403
    assert 'error="insufficient_scope"' in response.headers["WWW-Authenticate"]
    assert sink.events[-1]["event"] == "auth_failed"


@pytest.mark.asyncio
async def test_role_filtered_tools_list(settings_factory, token_factory, patched_jwks, app_client_factory):
    research_settings = settings_factory("research")
    research_runtime, _, _ = build_runtime(research_settings)
    research_client = await app_client_factory(research_settings, runtime=research_runtime)
    priya = token_factory(research_settings, roles=["Research.Read"], oid="oid-priya", upn="abw.priya@example.com")
    await mcp_initialize(research_client, auth_headers(priya))
    result = (await research_client.post("/mcp", headers=auth_headers(priya), json={"jsonrpc": "2.0", "id": "2", "method": "tools/list", "params": {}})).json()
    assert {tool["name"] for tool in result["result"]["tools"]} == {"search_research", "get_research_note"}

    wall_settings = settings_factory("wall")
    wall_runtime, _, _ = build_runtime(wall_settings)
    wall_client = await app_client_factory(wall_settings, runtime=wall_runtime)
    wes = token_factory(wall_settings, roles=["Wall.Falcon"], oid="oid-wes", upn="abw.wes@example.com")
    await mcp_initialize(wall_client, auth_headers(wes))
    wall_result = (await wall_client.post("/mcp", headers=auth_headers(wes), json={"jsonrpc": "2.0", "id": "3", "method": "tools/list", "params": {}})).json()
    assert {tool["name"] for tool in wall_result["result"]["tools"]} == {"list_my_wall_crossings", "search_deal_documents", "get_deal_document"}

    actions_settings = settings_factory("actions")
    tara_runtime, _, _ = build_runtime(actions_settings)
    tara_client = await app_client_factory(actions_settings, runtime=tara_runtime)
    tara = token_factory(actions_settings, scopes="Tools.Read Tools.Execute", roles=["Trade.Execute"], oid="oid-tara", upn="abw.tara@example.com")
    await mcp_initialize(tara_client, auth_headers(tara))
    tara_result = (await tara_client.post("/mcp", headers=auth_headers(tara), json={"jsonrpc": "2.0", "id": "4", "method": "tools/list", "params": {}})).json()
    assert {tool["name"] for tool in tara_result["result"]["tools"]} == {"check_restricted_list", "place_order", "list_my_orders"}

    carla_runtime, _, _ = build_runtime(actions_settings)
    carla_client = await app_client_factory(actions_settings, runtime=carla_runtime)
    carla = token_factory(actions_settings, roles=["Trade.Read"], oid="oid-carla", upn="abw.carla@example.com")
    await mcp_initialize(carla_client, auth_headers(carla))
    carla_result = (await carla_client.post("/mcp", headers=auth_headers(carla), json={"jsonrpc": "2.0", "id": "5", "method": "tools/list", "params": {}})).json()
    assert {tool["name"] for tool in carla_result["result"]["tools"]} == {"check_restricted_list", "list_my_orders"}


@pytest.mark.asyncio
async def test_wall_isolation_and_audit(settings_factory, token_factory, patched_jwks, app_client_factory):
    settings = settings_factory("wall")
    runtime, data, sink = build_runtime(settings)
    client = await app_client_factory(settings, runtime=runtime)
    wes = token_factory(settings, roles=["Wall.Falcon"], oid="oid-wes", upn="abw.wes@example.com")
    await mcp_initialize(client, auth_headers(wes))
    response = await client.post(
        "/mcp",
        headers=auth_headers(wes),
        json={"jsonrpc": "2.0", "id": "6", "method": "tools/call", "params": {"name": "get_deal_document", "arguments": {"doc_id": "ORION-001"}}},
    )
    payload = response.json()["result"]
    assert payload["isError"] is False  # soft denial: Foundry would abort the run on isError, the model must be able to narrate
    assert payload["structuredContent"]["decision"] == "DENIED"
    assert payload["structuredContent"]["error"] == "FORBIDDEN"
    assert payload["structuredContent"]["reason"] == "project_not_in_token_roles"
    assert "do not retry" in payload["structuredContent"]["note"]
    assert data.blob_calls == []
    assert sink.events[-1]["event"] == "wall_violation_attempt"
    assert sink.events[-1]["reason"] == "project_not_in_token_roles"


@pytest.mark.asyncio
async def test_storage_rbac_denial_audited(settings_factory, token_factory, patched_jwks, app_client_factory):
    settings = settings_factory("wall")
    runtime, data, sink = build_runtime(settings)
    data.deny_blob_containers.add("wall-falcon")
    client = await app_client_factory(settings, runtime=runtime)
    wes = token_factory(settings, roles=["Wall.Falcon"], oid="oid-wes", upn="abw.wes@example.com")
    await mcp_initialize(client, auth_headers(wes))
    response = await client.post(
        "/mcp",
        headers=auth_headers(wes),
        json={"jsonrpc": "2.0", "id": "7", "method": "tools/call", "params": {"name": "get_deal_document", "arguments": {"doc_id": "FALCON-001"}}},
    )
    payload = response.json()["result"]["structuredContent"]
    assert payload["error"] == "FORBIDDEN"
    assert sink.events[-1]["event"] == "wall_violation_attempt"
    assert sink.events[-1]["reason"] == "storage_rbac_denied"


@pytest.mark.asyncio
async def test_restricted_list_and_separation_of_duties(settings_factory, token_factory, patched_jwks, app_client_factory):
    settings = settings_factory("actions")
    tara_runtime, tara_data, tara_sink = build_runtime(settings)
    tara_client = await app_client_factory(settings, runtime=tara_runtime)
    tara = token_factory(settings, scopes="Tools.Read Tools.Execute", roles=["Trade.Execute"], oid="oid-tara", upn="abw.tara@example.com")
    await mcp_initialize(tara_client, auth_headers(tara))
    tara_resp = await tara_client.post(
        "/mcp",
        headers=auth_headers(tara),
        json={"jsonrpc": "2.0", "id": "8", "method": "tools/call", "params": {"name": "place_order", "arguments": {"ticker": "ZYNX", "side": "BUY", "quantity": 10}}},
    )
    tara_payload = tara_resp.json()["result"]["structuredContent"]
    assert tara_payload["error"] == "WALL_VIOLATION"
    assert tara_sink.events[-1]["reason"] == "restricted_list"
    assert tara_data.order_writes == []

    wes_runtime, wes_data, wes_sink = build_runtime(settings)
    wes_client = await app_client_factory(settings, runtime=wes_runtime)
    wes = token_factory(settings, scopes="Tools.Read Tools.Execute", roles=["Wall.Falcon", "Trade.Execute"], oid="oid-wes", upn="abw.wes@example.com")
    await mcp_initialize(wes_client, auth_headers(wes))
    wes_resp = await wes_client.post(
        "/mcp",
        headers=auth_headers(wes),
        json={"jsonrpc": "2.0", "id": "9", "method": "tools/call", "params": {"name": "place_order", "arguments": {"ticker": "ZYNX", "side": "BUY", "quantity": 10}}},
    )
    wes_payload = wes_resp.json()["result"]["structuredContent"]
    assert wes_payload["error"] == "WALL_VIOLATION"
    assert wes_sink.events[-1]["reason"] == "separation_of_duties"
    assert wes_data.order_writes == []


@pytest.mark.asyncio
async def test_obo_failure_does_not_fallback(settings_factory, token_factory, patched_jwks, app_client_factory):
    settings = settings_factory("research")
    obo = FakeObo(error_code="invalid_grant", calls=[])
    runtime, data, sink = build_runtime(settings, obo=obo)
    client = await app_client_factory(settings, runtime=runtime)
    priya = token_factory(settings, roles=["Research.Read"], oid="oid-priya", upn="abw.priya@example.com")
    await mcp_initialize(client, auth_headers(priya))
    response = await client.post(
        "/mcp",
        headers=auth_headers(priya),
        json={"jsonrpc": "2.0", "id": "10", "method": "tools/call", "params": {"name": "search_research", "arguments": {"query": "ACME"}}},
    )
    payload = response.json()["result"]["structuredContent"]
    assert payload["error"] == "FORBIDDEN"
    assert payload["reason"] == "obo_failed:invalid_grant"
    assert any(event["reason"] == "obo_failed:invalid_grant" for event in sink.events)


@pytest.mark.asyncio
async def test_audit_redacts_arguments_and_content(settings_factory, token_factory, patched_jwks, app_client_factory):
    settings = settings_factory("research")
    runtime, _, sink = build_runtime(settings)
    client = await app_client_factory(settings, runtime=runtime)
    priya = token_factory(settings, roles=["Research.Read"], oid="oid-priya", upn="abw.priya@example.com")
    await mcp_initialize(client, auth_headers(priya))
    canary = "CANARY-SECRET-STRING"
    response = await client.post(
        "/mcp",
        headers=auth_headers(priya),
        json={"jsonrpc": "2.0", "id": "11", "method": "tools/call", "params": {"name": "search_research", "arguments": {"query": canary, "limit": 1}}},
    )
    assert response.status_code == 200
    serialized = canonical_json(sink.events[-1])
    assert canary not in serialized
    assert sink.events[-1]["args_sha256"]


@pytest.mark.asyncio
async def test_vendor_key_enforcement(settings_factory, app_client_factory):
    settings = settings_factory("vendor")
    runtime, _, _ = build_runtime(settings)
    client = await app_client_factory(settings, runtime=runtime)

    no_key = await client.post("/mcp", headers=auth_headers(), json={"jsonrpc": "2.0", "id": "12", "method": "tools/list", "params": {}})
    assert no_key.status_code == 401

    bad_key = await client.post("/mcp", headers=auth_headers(extra={"x-vendor-key": "wrong"}), json={"jsonrpc": "2.0", "id": "13", "method": "tools/list", "params": {}})
    assert bad_key.status_code == 401

    ok = await client.post("/mcp", headers=auth_headers(extra={"x-vendor-key": "vendor-secret"}), json={"jsonrpc": "2.0", "id": "14", "method": "tools/list", "params": {}})
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_prm_endpoint(settings_factory, app_client_factory):
    settings = settings_factory("actions")
    runtime, _, _ = build_runtime(settings)
    client = await app_client_factory(settings, runtime=runtime)
    response = await client.get("/.well-known/oauth-protected-resource")
    payload = response.json()
    assert payload["resource"] == "https://public.example.test/mcp"
    assert payload["authorization_servers"] == ["https://login.microsoftonline.com/tenant-123/v2.0"]
    assert payload["bearer_methods_supported"] == ["header"]
    assert "api://actions-client-guid/Tools.Execute" in payload["scopes_supported"]


@pytest.mark.asyncio
async def test_argument_validation(settings_factory, token_factory, patched_jwks, app_client_factory):
    wall_settings = settings_factory("wall")
    wall_runtime, _, _ = build_runtime(wall_settings)
    wall_client = await app_client_factory(wall_settings, runtime=wall_runtime)
    wes = token_factory(wall_settings, roles=["Wall.Falcon"], oid="oid-wes", upn="abw.wes@example.com")
    await mcp_initialize(wall_client, auth_headers(wes))
    bad_doc = await wall_client.post(
        "/mcp",
        headers=auth_headers(wes),
        json={"jsonrpc": "2.0", "id": "15", "method": "tools/call", "params": {"name": "get_deal_document", "arguments": {"doc_id": "../x"}}},
    )
    assert bad_doc.json()["result"]["structuredContent"]["error"] == "INVALID_ARGUMENT"

    actions_settings = settings_factory("actions")
    actions_runtime, _, _ = build_runtime(actions_settings)
    actions_client = await app_client_factory(actions_settings, runtime=actions_runtime)
    tara = token_factory(actions_settings, scopes="Tools.Read Tools.Execute", roles=["Trade.Execute"], oid="oid-tara", upn="abw.tara@example.com")
    await mcp_initialize(actions_client, auth_headers(tara))
    bad_ticker = await actions_client.post(
        "/mcp",
        headers=auth_headers(tara),
        json={"jsonrpc": "2.0", "id": "16", "method": "tools/call", "params": {"name": "place_order", "arguments": {"ticker": "bad!", "side": "BUY", "quantity": 1}}},
    )
    assert bad_ticker.json()["result"]["structuredContent"]["error"] == "INVALID_ARGUMENT"

@pytest.mark.asyncio
async def test_strict_denial_mode_uses_mcp_is_error(settings_factory, token_factory, patched_jwks, app_client_factory):
    settings = dataclasses.replace(settings_factory("wall"), denial_mode="strict")
    runtime, _, _ = build_runtime(settings)
    client = await app_client_factory(settings, runtime=runtime)
    wes = token_factory(settings, roles=["Wall.Falcon"], oid="oid-wes", upn="abw.wes@example.com")
    await mcp_initialize(client, auth_headers(wes))
    response = await client.post(
        "/mcp",
        headers=auth_headers(wes),
        json={"jsonrpc": "2.0", "id": "20", "method": "tools/call", "params": {"name": "get_deal_document", "arguments": {"doc_id": "ORION-001"}}},
    )
    payload = response.json()["result"]
    assert payload["isError"] is True
    assert payload["structuredContent"]["decision"] == "DENIED"


@pytest.mark.asyncio
@pytest.mark.parametrize("server,expected_hidden", [("research", {"search_research", "get_research_note"}), ("wall", {"list_my_wall_crossings", "search_deal_documents", "get_deal_document"}), ("actions", {"check_restricted_list", "place_order", "list_my_orders"}), ("private", {"get_firm_positions", "get_credit_limit"})])
async def test_entitled_to_nothing_sees_no_tools_and_cannot_call(settings_factory, token_factory, patched_jwks, app_client_factory, server, expected_hidden):
    """Discovery is open at the gateway for any valid token; the server decides what is visible and callable."""
    settings = settings_factory(server)
    runtime, data, sink = build_runtime(settings)
    client = await app_client_factory(settings, runtime=runtime)
    ian = token_factory(settings, scopes="Tools.Read Tools.Execute", roles=[], oid="oid-ian", upn="abw.ian@example.com")
    await mcp_initialize(client, auth_headers(ian))
    listed = (await client.post("/mcp", headers=auth_headers(ian), json={"jsonrpc": "2.0", "id": "21", "method": "tools/list", "params": {}})).json()
    assert listed["result"]["tools"] == []
    name = sorted(expected_hidden)[0]
    called = (await client.post("/mcp", headers=auth_headers(ian), json={"jsonrpc": "2.0", "id": "22", "method": "tools/call", "params": {"name": name, "arguments": {}}})).json()
    assert called["result"]["structuredContent"]["decision"] == "DENIED"
    assert called["result"]["structuredContent"]["reason"] == "missing_role"
    assert sink.events[-1]["event"] == "tool_denied"
    assert data.blob_calls == [] and data.order_writes == []
