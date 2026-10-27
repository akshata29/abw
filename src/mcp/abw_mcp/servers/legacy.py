"""Intentionally insecure legacy demo server.

This module exists only as the "before" foil. It deliberately skips user auth,
role filtering, restricted-list checks, and OBO attribution so the demo can show
why the governed servers matter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import Field
from typing_extensions import Literal

from ..data import DataAccessError
from ..registry import ArgsModel, ToolDefinition, ToolError, ToolOutcome, allow_all
from ..runtime import RuntimeServices
from ..util import first_markdown_h1


class SearchArgs(ArgsModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=10)


class SearchDealArgs(SearchArgs):
    project: Literal["falcon", "orion"] = Field(description="Deal code, lowercase: falcon or orion.")


class GetDocArgs(ArgsModel):
    doc_id: str = Field(pattern=r"^(RN-\d{3}|FALCON-\d{3}|ORION-\d{3})$")


class PlaceOrderArgs(ArgsModel):
    ticker: str = Field(pattern=r"^[A-Z]{1,6}$", description="Uppercase ticker symbol.")
    side: Literal["BUY", "SELL"] = Field(description="Order side, uppercase: BUY or SELL.")
    quantity: int = Field(ge=1, le=1_000_000)


class PositionsArgs(ArgsModel):
    desk: str = Field(pattern=r"^[a-z0-9_-]{1,32}$", description="Desk name in lowercase: rates, equities or credit.")


async def search_research(caller, args: SearchArgs, runtime: RuntimeServices) -> ToolOutcome:
    rows = await runtime.data.search_documents(
        caller=caller,
        query=args.query,
        filter_text=None,
        select=["id", "title", "ticker", "summary", "snippet", "updated"],
        top=args.limit,
        use_user_token=False,
    )
    return ToolOutcome(payload={"results": rows}, obo=False, reason="no_user_context", downstream={"service": "search", "target": runtime.settings.search_index, "status": 200})


async def search_deal_documents(caller, args: SearchDealArgs, runtime: RuntimeServices) -> ToolOutcome:
    rows = await runtime.data.search_documents(
        caller=caller,
        query=args.query,
        filter_text=None,
        select=["id", "title", "ticker", "summary", "snippet", "updated", "project"],
        top=args.limit,
        use_user_token=False,
    )
    return ToolOutcome(payload={"project": args.project, "results": rows}, obo=False, reason="no_user_context", downstream={"service": "search", "target": runtime.settings.search_index, "status": 200})


async def get_deal_document(caller, args: GetDocArgs, runtime: RuntimeServices) -> ToolOutcome:
    if args.doc_id.startswith("RN-"):
        container = "research-public"
    else:
        container = f"wall-{args.doc_id.split('-', 1)[0].lower()}"
    try:
        content = await runtime.data.read_blob_text(caller=caller, container=container, blob_name=f"{args.doc_id}.md", use_user_token=False)
    except DataAccessError as exc:
        raise ToolError(exc.code, exc.message, reason=exc.reason, obo=False, downstream={"service": "storage", "target": container, "status": exc.status_code or 500}) from exc
    return ToolOutcome(
        payload={"doc_id": args.doc_id, "title": first_markdown_h1(content, args.doc_id), "content": content[:8000]},
        obo=False,
        reason="no_user_context",
        downstream={"service": "storage", "target": container, "status": 200},
    )


async def place_order(caller, args: PlaceOrderArgs, runtime: RuntimeServices) -> ToolOutcome:
    item = {
        "id": str(uuid4()),
        "user_oid": "unknown-service",
        "user_upn": None,
        "ticker": args.ticker,
        "side": args.side,
        "quantity": args.quantity,
        "status": "ACCEPTED",
        "source": "mcp-legacy",
        "created": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    await runtime.data.cosmos_upsert_item(caller=None, container="orders", item=item, use_user_token=False)
    return ToolOutcome(payload={"order_id": item["id"], "status": item["status"], "ticker": item["ticker"], "side": item["side"], "quantity": item["quantity"]}, obo=False, reason="no_user_context", downstream={"service": "cosmos", "target": "orders", "status": 200})


async def get_firm_positions(caller, args: PositionsArgs, runtime: RuntimeServices) -> ToolOutcome:
    rows = await runtime.data.cosmos_query_items(
        caller=None,
        container="positions",
        query="SELECT c.id, c.ticker, c.quantity, c.market_value_usd FROM c WHERE c.desk = @desk",
        parameters=[{"name": "@desk", "value": args.desk}],
        partition_key=args.desk,
        use_user_token=False,
    )
    return ToolOutcome(payload={"desk": args.desk, "positions": rows}, obo=False, reason="no_user_context", downstream={"service": "cosmos", "target": "positions", "status": 200})


def build_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition("search_research", "Search the firm's research notes and deal-room documents.", SearchArgs, search_research, allow_all, "mixed"),
        ToolDefinition("search_deal_documents", "Search deal-room documents for one project (falcon or orion).", SearchDealArgs, search_deal_documents, allow_all, "mixed"),
        ToolDefinition("get_deal_document", "Read a document by id: RN-001 style research notes, FALCON-001 / ORION-001 style deal-room documents.", GetDocArgs, get_deal_document, allow_all, "mixed"),
        ToolDefinition("place_order", "Place an equity order (ticker, BUY or SELL, quantity).", PlaceOrderArgs, place_order, allow_all, "mixed"),
        ToolDefinition("get_firm_positions", "Read firm positions for a trading desk (rates, equities or credit).", PositionsArgs, get_firm_positions, allow_all, "internal"),
    ]
