"""Thin Azure data-plane helpers for ABW MCP."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import ManagedIdentityCredential

from .auth import Caller, current_request_id
from .config import Settings
from .obo import OboBroker, OboError
from .util import slugify

logger = logging.getLogger(__name__)

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def downstream_request_id() -> str | None:
    """Gateway request id to stamp on downstream calls (x-ms-client-request-id) so data-plane logs join the audit trail."""

    value = current_request_id.get()
    return value if value and _SAFE_REQUEST_ID.match(value) else None


class DataAccessError(Exception):
    """Maps downstream errors into tool-safe failures."""

    def __init__(self, code: str, message: str, *, reason: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.reason = reason
        self.status_code = status_code


@dataclass(slots=True)
class DataPlaneClients:
    """Azure data-plane wrapper that is easy to replace in tests."""

    settings: Settings
    obo: OboBroker | None
    blob_service_factory: Callable[..., Any] | None = None
    search_client_factory: Callable[..., Any] | None = None
    cosmos_client_factory: Callable[..., Any] | None = None
    managed_identity_credential: ManagedIdentityCredential | None = None

    def __post_init__(self) -> None:
        if self.managed_identity_credential is None:
            self.managed_identity_credential = ManagedIdentityCredential(client_id=self.settings.uami_client_id)

    async def read_blob_text(self, *, caller: Caller | None, container: str, blob_name: str, use_user_token: bool = True) -> str:
        credential = (
            self._obo_credential(caller, "https://storage.azure.com/user_impersonation")
            if use_user_token
            else self.managed_identity_credential
        )
        client = self._build_blob_service(credential)
        try:
            return await asyncio.to_thread(self._download_blob_text, client, container, blob_name, downstream_request_id())
        except ResourceNotFoundError as exc:
            raise DataAccessError("NOT_FOUND", "Blob not found.", reason="blob_not_found", status_code=404) from exc
        except HttpResponseError as exc:
            if getattr(exc, "status_code", None) == 403:
                raise DataAccessError("FORBIDDEN", "Storage access denied.", reason="storage_rbac_denied", status_code=403) from exc
            raise

    async def search_documents(
        self,
        *,
        caller: Caller | None,
        query: str,
        filter_text: str | None,
        select: list[str],
        top: int,
        use_user_token: bool = True,
    ) -> list[dict[str, Any]]:
        credential = (
            self._obo_credential(caller, "https://search.azure.com/user_impersonation")
            if use_user_token
            else self.managed_identity_credential
        )
        client = self._build_search_client(credential)
        return await asyncio.to_thread(
            self._search_documents_sync,
            client,
            query,
            filter_text,
            select,
            top,
            downstream_request_id(),
        )

    async def cosmos_read_item(
        self,
        *,
        caller: Caller | None,
        container: str,
        item_id: str,
        partition_key: str,
        use_user_token: bool,
        user_scope: str | None = None,
    ) -> dict[str, Any] | None:
        container_client = self._get_cosmos_container(caller, container, use_user_token, user_scope)
        try:
            return await asyncio.to_thread(container_client.read_item, item=item_id, partition_key=partition_key)
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code == 404:
                return None
            raise

    async def cosmos_query_items(
        self,
        *,
        caller: Caller | None,
        container: str,
        query: str,
        parameters: list[dict[str, Any]],
        partition_key: str | None,
        use_user_token: bool,
        user_scope: str | None = None,
    ) -> list[dict[str, Any]]:
        container_client = self._get_cosmos_container(caller, container, use_user_token, user_scope)
        kwargs: dict[str, Any] = {"query": query, "parameters": parameters}
        if partition_key is not None:
            kwargs["partition_key"] = partition_key
        else:
            kwargs["enable_cross_partition_query"] = True
        return await asyncio.to_thread(self._query_items_sync, container_client, kwargs)

    async def cosmos_upsert_item(
        self,
        *,
        caller: Caller | None,
        container: str,
        item: dict[str, Any],
        use_user_token: bool,
        user_scope: str | None = None,
    ) -> dict[str, Any]:
        container_client = self._get_cosmos_container(caller, container, use_user_token, user_scope)
        return await asyncio.to_thread(container_client.upsert_item, item)

    def credit_limit_id(self, counterparty: str) -> str:
        return f"limit-{slugify(counterparty)}"

    def _build_blob_service(self, credential: Any) -> Any:
        if self.blob_service_factory is not None:
            return self.blob_service_factory(account_url=self.settings.storage_account_url, credential=credential)
        from azure.storage.blob import BlobServiceClient

        return BlobServiceClient(account_url=self.settings.storage_account_url, credential=credential)

    def _build_search_client(self, credential: Any) -> Any:
        if self.search_client_factory is not None:
            return self.search_client_factory(
                endpoint=self.settings.search_endpoint,
                index_name=self.settings.search_index,
                credential=credential,
            )
        from azure.search.documents import SearchClient

        return SearchClient(endpoint=self.settings.search_endpoint, index_name=self.settings.search_index, credential=credential)

    def _get_cosmos_container(
        self,
        caller: Caller | None,
        container: str,
        use_user_token: bool,
        user_scope: str | None,
    ) -> Any:
        if use_user_token:
            if caller is None or self.obo is None:
                raise OboError("missing_caller")
            credential = self.obo.get_credential(caller, user_scope or self.settings.cosmos_obo_scope)
        else:
            credential = self.managed_identity_credential
        if self.cosmos_client_factory is not None:
            client = self.cosmos_client_factory(url=self.settings.cosmos_endpoint, credential=credential)
        else:
            from azure.cosmos import CosmosClient

            client = CosmosClient(url=self.settings.cosmos_endpoint, credential=credential)
        return client.get_database_client(self.settings.cosmos_database).get_container_client(container)

    def _obo_credential(self, caller: Caller, scope: str) -> Any:
        if self.obo is None:
            raise OboError("not_configured")
        return self.obo.get_credential(caller, scope)

    @staticmethod
    def _query_items_sync(container_client: Any, kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        return list(container_client.query_items(**kwargs))

    @staticmethod
    def _download_blob_text(client: Any, container: str, blob_name: str, request_id: str | None = None) -> str:
        options = {"client_request_id": request_id} if request_id else {}
        downloader = client.get_blob_client(container=container, blob=blob_name).download_blob(**options)
        return downloader.readall().decode("utf-8")

    @staticmethod
    def _search_documents_sync(
        client: Any,
        query: str,
        filter_text: str | None,
        select: list[str],
        top: int,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        options = {"request_id": request_id} if request_id else {}
        pager = client.search(search_text=query, filter=filter_text, select=select, top=top, **options)
        return [dict(item) for item in pager]
