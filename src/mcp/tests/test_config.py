"""Environment validation per MCP server flavour."""

from __future__ import annotations

import pytest

from abw_mcp.config import Settings

BASE = {
    "TENANT_ID": "00000000-0000-0000-0000-000000000000",
    "UAMI_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
    "AUDIT_STORAGE_ACCOUNT": "stabwaudit",
}


def _apply(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key in ("MCP_SERVER", "MCP_APP_CLIENT_ID", "STORAGE_ACCOUNT", "COSMOS_ENDPOINT", "SEARCH_ENDPOINT", "VENDOR_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {**BASE, **env}.items():
        monkeypatch.setenv(key, value)


def test_vendor_and_legacy_do_not_need_an_audience_app(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, MCP_SERVER="vendor", VENDOR_API_KEY="k")
    assert Settings.from_env().mcp_server == "vendor"

    _apply(
        monkeypatch,
        MCP_SERVER="legacy",
        STORAGE_ACCOUNT="st",
        COSMOS_ENDPOINT="https://c.documents.azure.com:443/",
        SEARCH_ENDPOINT="https://s.search.windows.net",
    )
    assert Settings.from_env().mcp_server == "legacy"


@pytest.mark.parametrize("server", ["research", "wall", "actions", "private"])
def test_token_validating_servers_require_the_audience_app(monkeypatch: pytest.MonkeyPatch, server: str) -> None:
    _apply(
        monkeypatch,
        MCP_SERVER=server,
        STORAGE_ACCOUNT="st",
        COSMOS_ENDPOINT="https://c.documents.azure.com:443/",
        SEARCH_ENDPOINT="https://s.search.windows.net",
    )
    with pytest.raises(ValueError, match="MCP_APP_CLIENT_ID"):
        Settings.from_env()
