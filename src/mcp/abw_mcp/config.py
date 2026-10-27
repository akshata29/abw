"""Environment-backed settings for ABW MCP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

ServerName = Literal["research", "wall", "actions", "private", "vendor", "legacy"]

_TRUTHY = {"1", "true", "yes", "on"}


def _parse_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUTHY


def _parse_denial_mode(value: str | None) -> str:
    """`soft` returns policy denials as normal tool results (the model can narrate them); `strict` uses MCP isError."""
    mode = (value or "soft").strip().lower()
    if mode not in {"soft", "strict"}:
        raise ValueError("MCP_DENIAL_MODE must be 'soft' or 'strict'.")
    return mode


def _parse_csv(name: str) -> tuple[str, ...]:
    value = os.getenv(name, "")
    items = [part.strip() for part in value.split(",") if part.strip()]
    return tuple(items)


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved application settings."""

    mcp_server: ServerName
    tenant_id: str
    mcp_app_client_id: str
    mcp_allowed_azp: tuple[str, ...]
    mcp_required_scope: str
    uami_client_id: str
    storage_account: str | None
    cosmos_endpoint: str | None
    cosmos_database: str
    search_endpoint: str | None
    search_index: str
    audit_storage_account: str
    audit_container: str
    audit_fail_closed: bool
    applicationinsights_connection_string: str | None
    log_level: str
    public_base_url: str | None
    cosmos_obo: bool
    cosmos_obo_scope: str
    vendor_api_key: str | None
    denial_mode: str = "soft"

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"

    @property
    def issuer(self) -> str:
        return f"{self.authority}/v2.0"

    @property
    def jwks_url(self) -> str:
        return f"{self.authority}/discovery/v2.0/keys"

    @property
    def audience_values(self) -> tuple[str, str]:
        return (self.mcp_app_client_id, f"api://{self.mcp_app_client_id}")

    @property
    def audit_account_url(self) -> str:
        return f"https://{self.audit_storage_account}.blob.core.windows.net"

    @property
    def storage_account_url(self) -> str | None:
        if not self.storage_account:
            return None
        return f"https://{self.storage_account}.blob.core.windows.net"

    @classmethod
    def from_env(cls) -> "Settings":
        mcp_server = (os.getenv("MCP_SERVER") or "").strip().lower()
        if not mcp_server:
            raise ValueError("MCP_SERVER is required.")
        if mcp_server not in {"research", "wall", "actions", "private", "vendor", "legacy"}:
            raise ValueError(f"Unsupported MCP_SERVER '{mcp_server}'.")

        tenant_id = (os.getenv("TENANT_ID") or "").strip()
        app_client_id = (os.getenv("MCP_APP_CLIENT_ID") or "").strip()
        uami_client_id = (os.getenv("UAMI_CLIENT_ID") or "").strip()
        audit_storage_account = (os.getenv("AUDIT_STORAGE_ACCOUNT") or "").strip()

        # vendor (shared-key) and legacy (the deliberately leaky POC) do not validate Entra tokens, so they have no audience app.
        validates_tokens = mcp_server not in {"vendor", "legacy"}
        missing = []
        for name, value in (
            ("TENANT_ID", tenant_id),
            ("MCP_APP_CLIENT_ID", app_client_id if validates_tokens else "n/a"),
            ("UAMI_CLIENT_ID", uami_client_id),
            ("AUDIT_STORAGE_ACCOUNT", audit_storage_account),
        ):
            if not value:
                missing.append(name)

        storage_account = (os.getenv("STORAGE_ACCOUNT") or "").strip() or None
        cosmos_endpoint = (os.getenv("COSMOS_ENDPOINT") or "").strip() or None
        search_endpoint = (os.getenv("SEARCH_ENDPOINT") or "").strip() or None
        vendor_api_key = os.getenv("VENDOR_API_KEY")

        server_requirements: dict[str, tuple[tuple[str, str | None], ...]] = {
            "research": (("STORAGE_ACCOUNT", storage_account), ("SEARCH_ENDPOINT", search_endpoint)),
            "wall": (("STORAGE_ACCOUNT", storage_account), ("SEARCH_ENDPOINT", search_endpoint)),
            "actions": (("COSMOS_ENDPOINT", cosmos_endpoint),),
            "private": (("COSMOS_ENDPOINT", cosmos_endpoint),),
            "vendor": (("VENDOR_API_KEY", vendor_api_key),),
            "legacy": (
                ("STORAGE_ACCOUNT", storage_account),
                ("COSMOS_ENDPOINT", cosmos_endpoint),
                ("SEARCH_ENDPOINT", search_endpoint),
            ),
        }
        for env_name, value in server_requirements[mcp_server]:
            if not value:
                missing.append(env_name)

        if missing:
            raise ValueError(f"Missing required environment variables for server '{mcp_server}': {', '.join(sorted(set(missing)))}")

        return cls(
            mcp_server=mcp_server,
            tenant_id=tenant_id,
            mcp_app_client_id=app_client_id,
            mcp_allowed_azp=_parse_csv("MCP_ALLOWED_AZP"),
            mcp_required_scope=(os.getenv("MCP_REQUIRED_SCOPE") or "Tools.Read").strip(),
            uami_client_id=uami_client_id,
            storage_account=storage_account,
            cosmos_endpoint=cosmos_endpoint,
            cosmos_database=(os.getenv("COSMOS_DATABASE") or "abw").strip(),
            search_endpoint=search_endpoint,
            search_index=(os.getenv("SEARCH_INDEX") or "deals-idx").strip(),
            audit_storage_account=audit_storage_account,
            audit_container=(os.getenv("AUDIT_CONTAINER") or "worm-audit").strip(),
            audit_fail_closed=_parse_bool("AUDIT_FAIL_CLOSED", False),
            applicationinsights_connection_string=(os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING") or "").strip() or None,
            log_level=(os.getenv("LOG_LEVEL") or "INFO").strip().upper(),
            public_base_url=(os.getenv("PUBLIC_BASE_URL") or "").strip() or None,
            cosmos_obo=_parse_bool("COSMOS_OBO", True),
            cosmos_obo_scope=(os.getenv("COSMOS_OBO_SCOPE") or "https://cosmos.azure.com/user_impersonation").strip(),
            vendor_api_key=vendor_api_key.strip() if vendor_api_key else None,
            denial_mode=_parse_denial_mode(os.getenv("MCP_DENIAL_MODE")),
        )

