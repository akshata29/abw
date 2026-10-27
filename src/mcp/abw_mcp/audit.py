"""Audit event construction and sinks for ABW MCP."""

from __future__ import annotations

import json
import logging
import queue
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from opentelemetry import trace

from .runtime import RuntimeServices
from .util import canonical_json, sha256_json

LOGGER_NAME = "abw.audit"
logger = logging.getLogger(LOGGER_NAME)


class AuditSink(Protocol):
    """Audit sink protocol."""

    def emit(self, event: dict[str, Any]) -> None:
        """Persist or forward an audit event."""


class InMemoryAuditSink:
    """Testing sink that stores events in memory."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class StdoutLoggerAuditSink:
    """Sink that logs to stdout and the dedicated audit logger."""

    def emit(self, event: dict[str, Any]) -> None:
        extra: dict[str, Any] = {}
        for key, value in event.items():
            if value is None:
                continue
            extra[key] = json.dumps(value, sort_keys=True, separators=(",", ":")) if isinstance(value, dict) else value
        logger.info("abw.audit", extra=extra)
        sys.stdout.write(canonical_json(event) + "\n")
        sys.stdout.flush()


class AppendBlobAuditSink:
    """Sink that appends JSONL events to Azure Blob Storage."""

    def __init__(
        self,
        runtime: RuntimeServices,
        blob_client_factory: Any | None = None,
    ) -> None:
        self._runtime = runtime
        self._blob_client_factory = blob_client_factory
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._closed = threading.Event()
        self._credential: Any | None = None
        self._clients: dict[str, Any] = {}
        self._created: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._runtime.settings.audit_fail_closed or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="abw-audit-blob", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._runtime.settings.audit_fail_closed:
            return
        if self._thread is None:
            return
        self._queue.put(None)
        self._thread.join(timeout=5)
        self._thread = None
        self._closed.set()

    def emit(self, event: dict[str, Any]) -> None:
        if self._runtime.settings.audit_fail_closed:
            self._append_line(event)
            return
        self._queue.put(event)

    def _run(self) -> None:
        while not self._closed.is_set():
            item = self._queue.get()
            if item is None:
                break
            try:
                self._append_line(item)
            except Exception:
                print("append_audit_failed", file=sys.stderr)
                logging.getLogger(__name__).exception("append_audit_failed")

    def _append_line(self, event: dict[str, Any]) -> None:
        with self._lock:
            client = self._get_append_blob_client(event)
            key = getattr(client, "blob_name", None) or id(client)
            if key not in self._created:
                try:
                    client.get_blob_properties()
                except Exception:
                    try:
                        client.create_append_blob()
                    except Exception:
                        client.get_blob_properties()
                self._created.add(key)
            client.append_block((canonical_json(event) + "\n").encode("utf-8"))

    def _get_append_blob_client(self, event: dict[str, Any]) -> Any:
        if self._blob_client_factory is not None:
            return self._blob_client_factory(event)

        from azure.identity import ManagedIdentityCredential
        from azure.storage.blob import AppendBlobClient

        settings = self._runtime.settings
        if self._credential is None:
            self._credential = ManagedIdentityCredential(client_id=settings.uami_client_id)
        now = datetime.fromisoformat(event["ts"].replace("Z", "+00:00"))
        blob_name = (
            f"{settings.mcp_server}/{now:%Y}/{now:%m}/{now:%d}/{settings.mcp_server}.jsonl"
        )
        client = self._clients.get(blob_name)
        if client is None:
            client = AppendBlobClient(
                account_url=settings.audit_account_url,
                container_name=settings.audit_container,
                blob_name=blob_name,
                credential=self._credential,
            )
            self._clients[blob_name] = client
        return client


def trace_id_from_context() -> str | None:
    """Get the active OpenTelemetry trace ID."""

    context = trace.get_current_span().get_span_context()
    if not context or not context.is_valid:
        return None
    return f"{context.trace_id:032x}"


@dataclass(slots=True)
class AuditService:
    """Coordinates audit sinks and event construction."""

    runtime: RuntimeServices
    sinks: list[AuditSink]

    def start(self) -> None:
        for sink in self.sinks:
            start = getattr(sink, "start", None)
            if callable(start):
                start()

    def stop(self) -> None:
        for sink in self.sinks:
            stop = getattr(sink, "stop", None)
            if callable(stop):
                stop()

    def emit(self, event: dict[str, Any]) -> None:
        for sink in self.sinks:
            sink.emit(event)

    def build_event(
        self,
        *,
        event: str,
        tool: str | None,
        decision: str,
        reason: str | None,
        caller: Any | None,
        data_class: str | None,
        args: Any | None,
        result_bytes: int,
        obo: bool,
        downstream: dict[str, Any] | None,
        request_id: str | None,
    ) -> dict[str, Any]:
        token_hash = sha256_json(args) if args is not None else None
        return {
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "event": event,
            "server": self.runtime.settings.mcp_server,
            "tool": tool,
            "decision": decision,
            "reason": reason,
            "user_oid": getattr(caller, "oid", None),
            "user_upn": getattr(caller, "upn", None),
            "tid": getattr(caller, "tid", None),
            "roles": list(getattr(caller, "roles", ()) or ()),
            "scp": " ".join(getattr(caller, "scopes", ()) or ()),
            "azp": getattr(caller, "azp", None),
            "aud": getattr(caller, "aud", None),
            "jti": getattr(caller, "jti", None),
            "obo": obo,
            "downstream": downstream or {},
            "data_class": data_class,
            "args_sha256": token_hash,
            "result_bytes": result_bytes,
            "trace_id": trace_id_from_context(),
            "request_id": request_id,
        }


def build_default_audit_service(runtime: RuntimeServices) -> AuditService:
    """Create the production audit service."""

    sinks: list[AuditSink] = [StdoutLoggerAuditSink(), AppendBlobAuditSink(runtime)]
    return AuditService(runtime=runtime, sinks=sinks)
