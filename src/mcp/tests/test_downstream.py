"""Downstream correlation (x-ms-client-request-id) and the vendor red-team fixture."""

from __future__ import annotations

import pytest

from abw_mcp.auth import current_request_id
from abw_mcp.data import DataPlaneClients, downstream_request_id
from abw_mcp.servers import vendor


@pytest.mark.parametrize(
    "value,expected",
    [
        ("ea59b224-776b-40a2-8c79-82dc3740a3d4", "ea59b224-776b-40a2-8c79-82dc3740a3d4"),
        ("req-1760000000000", "req-1760000000000"),
        ("bad\r\nx-injected: 1", None),
        ("a" * 65, None),
        ("", None),
        (None, None),
    ],
)
def test_downstream_request_id_is_header_safe(value, expected):
    token = current_request_id.set(value)
    try:
        assert downstream_request_id() == expected
    finally:
        current_request_id.reset(token)


class _Downloader:
    def readall(self) -> bytes:
        return b"synthetic"


class _BlobClient:
    def __init__(self, seen: list[dict]):
        self._seen = seen

    def download_blob(self, **kwargs):
        self._seen.append(kwargs)
        return _Downloader()


class _BlobService:
    def __init__(self, seen: list[dict]):
        self._seen = seen

    def get_blob_client(self, container: str, blob: str):
        return _BlobClient(self._seen)


@pytest.mark.asyncio
async def test_blob_read_stamps_gateway_request_id(settings_factory):
    seen: list[dict] = []
    clients = DataPlaneClients(
        settings=settings_factory("wall"),
        obo=None,
        blob_service_factory=lambda **_: _BlobService(seen),
    )
    token = current_request_id.set("ea59b224-776b-40a2-8c79-82dc3740a3d4")
    try:
        text = await clients.read_blob_text(caller=None, container="wall-falcon", blob_name="FALCON-001.md", use_user_token=False)
    finally:
        current_request_id.reset(token)
    assert text == "synthetic"
    assert seen == [{"client_request_id": "ea59b224-776b-40a2-8c79-82dc3740a3d4"}]


@pytest.mark.asyncio
async def test_vendor_injection_fixture_is_isolated_to_nova():
    nova = await vendor.get_headlines(None, vendor.TickerArgs(ticker="NOVA"), None)
    acme = await vendor.get_headlines(None, vendor.TickerArgs(ticker="ACME"), None)
    assert any("SYSTEM NOTICE TO AI ASSISTANT" in h for h in nova.payload["headlines"])
    assert not any("SYSTEM NOTICE" in h for h in acme.payload["headlines"])
