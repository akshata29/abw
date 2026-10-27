"""Private positions server tools."""

from __future__ import annotations

from pydantic import Field

from ..registry import ArgsModel, ToolDefinition, ToolError, ToolOutcome, require_any_role
from ..runtime import RuntimeServices


class PositionsArgs(ArgsModel):
    desk: str = Field(pattern=r"^[a-z0-9_-]{1,32}$", description="Desk name in lowercase: rates, equities or credit.")


class CreditLimitArgs(ArgsModel):
    counterparty: str = Field(min_length=1, max_length=64, description="Counterparty name, for example Northgate Capital.")


async def get_firm_positions(caller, args: PositionsArgs, runtime: RuntimeServices) -> ToolOutcome:
    rows = await runtime.data.cosmos_query_items(
        caller=caller,
        container="positions",
        query="SELECT c.id, c.ticker, c.quantity, c.market_value_usd FROM c WHERE c.desk = @desk",
        parameters=[{"name": "@desk", "value": args.desk}],
        partition_key=args.desk,
        use_user_token=runtime.settings.cosmos_obo,
        user_scope=runtime.settings.cosmos_obo_scope,
    )
    positions = [
        {"ticker": row["ticker"], "quantity": row["quantity"], "market_value_usd": row["market_value_usd"]}
        for row in rows
        if row.get("ticker") and not str(row.get("id", "")).startswith("limit-")
    ]
    return ToolOutcome(payload={"desk": args.desk, "positions": positions}, obo=runtime.settings.cosmos_obo, downstream={"service": "cosmos", "target": "positions", "status": 200})


async def get_credit_limit(caller, args: CreditLimitArgs, runtime: RuntimeServices) -> ToolOutcome:
    item = await runtime.data.cosmos_read_item(
        caller=caller,
        container="positions",
        item_id=runtime.data.credit_limit_id(args.counterparty),
        partition_key="credit",
        use_user_token=runtime.settings.cosmos_obo,
        user_scope=runtime.settings.cosmos_obo_scope,
    )
    if item is None:
        raise ToolError("NOT_FOUND", "Credit limit not found.", reason="counterparty_not_found")
    return ToolOutcome(
        payload={
            "counterparty": item["counterparty"],
            "limit_usd": item["limit_usd"],
            "utilization_usd": item["utilization_usd"],
        },
        obo=runtime.settings.cosmos_obo,
        downstream={"service": "cosmos", "target": "positions", "status": 200},
    )


def build_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="get_firm_positions",
            description="Get the firm's internal (private-network) positions for one trading desk: ticker, quantity and market value.",
            args_model=PositionsArgs,
            handler=get_firm_positions,
            requirement=require_any_role("Positions.Read"),
            data_class="internal",
        ),
        ToolDefinition(
            name="get_credit_limit",
            description="Get the internal credit limit and current utilisation for one counterparty.",
            args_model=CreditLimitArgs,
            handler=get_credit_limit,
            requirement=require_any_role("Positions.Read"),
            data_class="internal",
        ),
    ]
