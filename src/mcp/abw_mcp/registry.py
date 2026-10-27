"""Tool registry and MCP list/call handlers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from mcp import types
from pydantic import BaseModel, ConfigDict, ValidationError

from .auth import Caller, current_request_id
from .obo import OboError
from .runtime import RuntimeServices
from .util import compact_json

logger = logging.getLogger(__name__)

Requirement = Callable[[Caller | None], tuple[bool, str | None]]
Handler = Callable[[Caller | None, BaseModel, RuntimeServices], Awaitable["ToolOutcome"]]


class ArgsModel(BaseModel):
    """Common configuration for tool argument models."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """Tool result payload and audit metadata."""

    payload: dict[str, Any]
    audit_event: str = "tool_call"
    decision: str = "allow"
    reason: str | None = None
    obo: bool = True
    downstream: dict[str, Any] | None = None


DENIED_CODES = frozenset({"FORBIDDEN", "WALL_VIOLATION"})


def validation_message(exc: ValidationError) -> str:
    """Compact, model-readable summary of a pydantic validation failure."""
    parts = []
    for item in exc.errors():
        location = ".".join(str(part) for part in item.get("loc", ())) or "arguments"
        parts.append(f"{location}: {item.get('msg', 'invalid')}")
    return "; ".join(parts) or "invalid arguments"


class ToolError(Exception):
    """Tool failure surface."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        reason: str,
        audit_event: str = "tool_denied",
        decision: str = "deny",
        obo: bool = True,
        downstream: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.reason = reason
        self.audit_event = audit_event
        self.decision = decision
        self.obo = obo
        self.downstream = downstream or {}


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Registered tool metadata."""

    name: str
    description: str
    args_model: type[ArgsModel]
    handler: Handler
    requirement: Requirement
    data_class: str | None = None

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()


def allow_all(_: Caller | None) -> tuple[bool, str | None]:
    return True, None


def require_any_role(*roles: str) -> Requirement:
    role_set = set(roles)

    def _predicate(caller: Caller | None) -> tuple[bool, str | None]:
        if caller is None:
            return False, "missing_role"
        if any(role in role_set for role in caller.roles):
            return True, None
        return False, "missing_role"

    return _predicate


def require_scope_and_role(scope: str, *roles: str) -> Requirement:
    role_requirement = require_any_role(*roles)

    def _predicate(caller: Caller | None) -> tuple[bool, str | None]:
        if caller is None:
            return False, "missing_scope"
        if scope not in caller.scopes:
            return False, "missing_scope"
        return role_requirement(caller)

    return _predicate


class ToolRegistry:
    """Per-server tool registry."""

    def __init__(self, runtime: RuntimeServices, tools: list[ToolDefinition], *, default_reason: str | None = None) -> None:
        self.runtime = runtime
        self._tools = {tool.name: tool for tool in tools}
        self.default_reason = default_reason

    async def list_tools(self, caller: Caller | None) -> types.ListToolsResult:
        visible: list[types.Tool] = []
        for tool in self._tools.values():
            ok, _ = tool.requirement(caller)
            if not ok:
                continue
            visible.append(
                types.Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema)
            )
            self.runtime.audit.emit(
                self.runtime.audit.build_event(
                    event="tool_listed",
                    tool=tool.name,
                    decision="allow",
                    reason=self.default_reason,
                    caller=caller,
                    data_class=tool.data_class,
                    args=None,
                    result_bytes=0,
                    obo=self.runtime.settings.mcp_server not in {"legacy", "vendor"},
                    downstream={},
                    request_id=current_request_id.get(),
                )
            )
        return types.ListToolsResult(tools=visible)

    async def call_tool(self, caller: Caller | None, name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return self._error_result("NOT_FOUND", f"Unknown tool '{name}'.", reason="unknown_tool")

        ok, reason = tool.requirement(caller)
        if not ok:
            return self._error_result("FORBIDDEN", "Tool unavailable for this caller.", reason=reason or "forbidden", caller=caller, tool=tool)

        try:
            parsed = tool.args_model.model_validate(arguments or {})
        except ValidationError as exc:
            return self._tool_error_result(
                ToolError("INVALID_ARGUMENT", validation_message(exc), reason="invalid_arguments", decision="deny", obo=False),
                caller=caller,
                tool=tool,
                arguments=arguments,
            )

        try:
            outcome = await tool.handler(caller, parsed, self.runtime)
        except OboError as exc:
            return self._tool_error_result(
                ToolError(
                    "FORBIDDEN",
                    "Unable to acquire downstream user token.",
                    reason=f"obo_failed:{exc.code}",
                    decision="deny",
                    audit_event="tool_denied",
                ),
                caller=caller,
                tool=tool,
                arguments=arguments,
            )
        except ToolError as exc:
            return self._tool_error_result(exc, caller=caller, tool=tool, arguments=arguments)

        payload = dict(outcome.payload)
        request_id = current_request_id.get()
        if request_id:
            # Same id as the APIM CorrelationId and the Storage/Search client request id, so a Foundry trace can be
            # joined to the gateway, the audit record and the downstream data-plane log for ALLOWED calls too.
            payload.setdefault("request_id", request_id)
        payload_text = compact_json(payload)
        self.runtime.audit.emit(
            self.runtime.audit.build_event(
                event=outcome.audit_event,
                tool=tool.name,
                decision=outcome.decision,
                reason=outcome.reason or self.default_reason,
                caller=caller,
                data_class=tool.data_class,
                args=arguments or {},
                result_bytes=len(payload_text.encode("utf-8")),
                obo=outcome.obo,
                downstream=outcome.downstream,
                request_id=current_request_id.get(),
            )
        )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=payload_text)],
            structuredContent=payload,
        )

    def _error_result(
        self,
        code: str,
        message: str,
        *,
        reason: str,
        caller: Caller | None = None,
        tool: ToolDefinition | None = None,
    ) -> types.CallToolResult:
        return self._tool_error_result(
            ToolError(code, message, reason=reason, decision="deny", obo=self.runtime.settings.mcp_server not in {"legacy", "vendor"}),
            caller=caller,
            tool=tool,
            arguments={},
        )

    def _tool_error_result(
        self,
        error: ToolError,
        *,
        caller: Caller | None,
        tool: ToolDefinition | None,
        arguments: dict[str, Any] | None,
    ) -> types.CallToolResult:
        payload = self._error_payload(error)
        text = compact_json(payload)
        self.runtime.audit.emit(
            self.runtime.audit.build_event(
                event=error.audit_event,
                tool=tool.name if tool else None,
                decision=error.decision,
                reason=error.reason,
                caller=caller,
                data_class=tool.data_class if tool else None,
                args=arguments or {},
                result_bytes=len(text.encode("utf-8")),
                obo=error.obo,
                downstream=error.downstream,
                request_id=current_request_id.get(),
            )
        )
        # Foundry Agent Service aborts the whole run (HTTP 400 tool_user_error) when a tool returns isError=true, so by
        # default a policy denial is a NORMAL result carrying decision=DENIED: the model can explain it to the user, and
        # the denial is still audited above. `strict` restores the MCP-spec isError for clients that render it natively.
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            structuredContent=payload,
            isError=self.runtime.settings.denial_mode == "strict",
        )

    @staticmethod
    def _error_payload(error: ToolError) -> dict[str, Any]:
        denied = error.code in DENIED_CODES
        payload: dict[str, Any] = {
            "decision": "DENIED" if denied else "ERROR",
            "error": error.code,
            "message": error.message,
        }
        if error.reason:
            payload["reason"] = error.reason
        request_id = current_request_id.get()
        if request_id:
            payload["request_id"] = request_id
        if denied:
            payload["note"] = (
                "Blocked by policy and written to the audit log. Tell the user what was blocked and the reason code; "
                "do not retry, rephrase or look for a workaround."
            )
        elif error.code == "INVALID_ARGUMENT":
            payload["note"] = "Fix the arguments to match the tool schema and retry once."
        return payload
