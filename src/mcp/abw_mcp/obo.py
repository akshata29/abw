"""On-behalf-of token broker for ABW MCP."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import msal
from azure.core.credentials import AccessToken, TokenCredential
from azure.identity import ManagedIdentityCredential

from .auth import Caller
from .config import Settings

logger = logging.getLogger(__name__)


class OboError(Exception):
    """Raised when OBO acquisition fails."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class StaticTokenCredential(TokenCredential):
    """Static Azure credential backed by an access token."""

    token: str
    expires_on: int

    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return AccessToken(self.token, self.expires_on)


class OboBroker:
    """Acquire downstream user tokens via OBO."""

    def __init__(
        self,
        settings: Settings,
        *,
        cache: msal.SerializableTokenCache | None = None,
        mi_credential: ManagedIdentityCredential | None = None,
        app: msal.ConfidentialClientApplication | None = None,
    ) -> None:
        self.settings = settings
        self._cache = cache or msal.SerializableTokenCache()
        self._mi_credential = mi_credential or ManagedIdentityCredential(client_id=settings.uami_client_id)
        self._app = app or msal.ConfidentialClientApplication(
            settings.mcp_app_client_id,
            authority=settings.authority,
            token_cache=self._cache,
            client_credential={"client_assertion": self._get_client_assertion},
        )

    def get_credential(self, caller: Caller, scope: str) -> StaticTokenCredential:
        token = self.acquire_token_on_behalf_of(caller, [scope])
        return StaticTokenCredential(token=token["access_token"], expires_on=token["expires_on"])

    def acquire_token_on_behalf_of(self, caller: Caller, scopes: list[str]) -> dict[str, Any]:
        result = self._app.acquire_token_on_behalf_of(user_assertion=caller.token, scopes=scopes)
        if "access_token" not in result:
            code = str(result.get("error") or "unknown_error")
            raise OboError(code)
        expires_in = int(result.get("expires_in") or 3600)
        return {
            "access_token": result["access_token"],
            "expires_in": expires_in,
            "ext_expires_in": int(result.get("ext_expires_in") or expires_in),
            "expires_on": int(time.time()) + expires_in,
        }

    def _get_client_assertion(self, *args: Any, **kwargs: Any) -> str:
        token = self._mi_credential.get_token("api://AzureADTokenExchange/.default")
        return token.token
