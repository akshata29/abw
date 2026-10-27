"""Trading actions server tools."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import Field
from typing_extensions import Literal

from ..auth import current_request_id
from ..registry import ArgsModel, ToolDefinition, ToolError, ToolOutcome, require_any_role, require_scope_and_role
from ..runtime import RuntimeServices


class CheckRestrictedArgs(ArgsModel):
    ticker: str = Field(pattern=r"^[A-Z]{1,6}$")


class PlaceOrderArgs(ArgsModel):
    ticker: str = Field(pattern=r"^[A-Z]{1,6}$", description="Uppercase ticker symbol, for example ACME.")
    side: Literal["BUY", "SELL"] = Field(description="Order side, uppercase: BUY or SELL.")
    quantity: int = Field(ge=1, le=1_000_000)


class ListOrdersArgs(ArgsModel):
    limit: int = Field(default=10, ge=1, le=100)


async def _read_restricted(runtime: RuntimeServices, ticker: str) -> dict | None:
    return await runtime.data.cosmos_read_item(
        caller=None,
        container="restricted",
        item_id=ticker,
        partition_key=ticker,
        use_user_token=False,
    )


def _has_wall_role(caller) -> bool:
    return any(role.startswith("Wall.") for role in caller.roles)


async def check_restricted_list(caller, args: CheckRestrictedArgs, runtime: RuntimeServices) -> ToolOutcome:
    item = await _read_restricted(runtime, args.ticker)
    restricted = item is not None
    return ToolOutcome(
        payload={
            "ticker": args.ticker,
            "restricted": restricted,
            "reason": "On the firm restricted list — do not trade" if restricted else None,
        },
        obo=False,
        downstream={"service": "cosmos", "target": "restricted", "status": 200},
    )


async def place_order(caller, args: PlaceOrderArgs, runtime: RuntimeServices) -> ToolOutcome:
    restricted = await _read_restricted(runtime, args.ticker)
    if restricted and _has_wall_role(caller):
        raise ToolError(
            "WALL_VIOLATION",
            "Trade blocked: security is on the firm restricted list.",
            reason="separation_of_duties",
            audit_event="order_blocked",
            downstream={"service": "cosmos", "target": "restricted", "status": 200},
        )
    if restricted:
        raise ToolError(
            "WALL_VIOLATION",
            "Trade blocked: security is on the firm restricted list.",
            reason="restricted_list",
            audit_event="order_blocked",
            downstream={"service": "cosmos", "target": "restricted", "status": 200},
        )

    item = {
        "id": str(uuid4()),
        "user_oid": caller.oid,
        "user_upn": caller.upn,
        "ticker": args.ticker,
        "side": args.side,
        "quantity": args.quantity,
        "status": "ACCEPTED",
        "source": "mcp-actions",
        "azp": caller.azp,
        "jti": caller.jti,
        "request_id": current_request_id.get(),
        "created": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    use_user_token = runtime.settings.cosmos_obo
    await runtime.data.cosmos_upsert_item(
        caller=caller,
        container="orders",
        item=item,
        use_user_token=use_user_token,
        user_scope=runtime.settings.cosmos_obo_scope,
    )
    return ToolOutcome(
        payload={
            "order_id": item["id"],
            "status": item["status"],
            "ticker": item["ticker"],
            "side": item["side"],
            "quantity": item["quantity"],
        },
        audit_event="order_placed",
        obo=use_user_token,
        downstream={"service": "cosmos", "target": "orders", "status": 200},
    )


async def list_my_orders(caller, args: ListOrdersArgs, runtime: RuntimeServices) -> ToolOutcome:
    use_user_token = runtime.settings.cosmos_obo
    rows = await runtime.data.cosmos_query_items(
        caller=caller,
        container="orders",
        query="SELECT TOP @limit c.id, c.user_oid, c.user_upn, c.ticker, c.side, c.quantity, c.status, c.source, c.created FROM c WHERE c.user_oid = @user_oid ORDER BY c.created DESC",
        parameters=[
            {"name": "@limit", "value": args.limit},
            {"name": "@user_oid", "value": caller.oid},
        ],
        partition_key=caller.oid,
        use_user_token=use_user_token,
        user_scope=runtime.settings.cosmos_obo_scope,
    )
    return ToolOutcome(payload={"orders": rows}, obo=use_user_token, downstream={"service": "cosmos", "target": "orders", "status": 200})


def build_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="check_restricted_list",
            description="Check whether a ticker is on the firm restricted (do-not-trade) list. Always call this before place_order.",
            args_model=CheckRestrictedArgs,
            handler=check_restricted_list,
            requirement=require_any_role("Trade.Read", "Trade.Execute"),
            data_class="internal",
        ),
        ToolDefinition(
            name="place_order",
            description="Place a synthetic equity order as the signed-in user. Requires the Trade.Execute role and human approval; blocked for restricted-list securities.",
            args_model=PlaceOrderArgs,
            handler=place_order,
            requirement=require_scope_and_role("Tools.Execute", "Trade.Execute"),
            data_class="internal",
        ),
        ToolDefinition(
            name="list_my_orders",
            description="List the signed-in user's own recent orders.",
            args_model=ListOrdersArgs,
            handler=list_my_orders,
            requirement=require_any_role("Trade.Read", "Trade.Execute"),
            data_class="internal",
        ),
    ]
