"""Research server tools."""

from __future__ import annotations

from pydantic import Field, constr

from ..data import DataAccessError
from ..registry import ArgsModel, ToolDefinition, ToolError, ToolOutcome, require_any_role
from ..runtime import RuntimeServices
from ..util import first_markdown_h1


class SearchResearchArgs(ArgsModel):
    query: constr(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=10)


class GetResearchNoteArgs(ArgsModel):
    note_id: constr(pattern=r"^[A-Za-z0-9._-]{1,64}$")


async def search_research(caller, args: SearchResearchArgs, runtime: RuntimeServices) -> ToolOutcome:
    rows = await runtime.data.search_documents(
        caller=caller,
        query=args.query,
        filter_text="classification eq 'public'",
        select=["id", "title", "ticker", "snippet", "updated"],
        top=args.limit,
    )
    return ToolOutcome(
        payload={
            "results": [
                {
                    "note_id": row.get("id"),
                    "title": row.get("title"),
                    "ticker": row.get("ticker"),
                    "snippet": row.get("snippet"),
                    "updated": row.get("updated"),
                }
                for row in rows
            ]
        },
        downstream={"service": "search", "target": runtime.settings.search_index, "status": 200},
    )


async def get_research_note(caller, args: GetResearchNoteArgs, runtime: RuntimeServices) -> ToolOutcome:
    try:
        content = await runtime.data.read_blob_text(
            caller=caller,
            container="research-public",
            blob_name=f"{args.note_id}.md",
        )
    except DataAccessError as exc:
        raise ToolError(exc.code, exc.message, reason=exc.reason, downstream={"service": "storage", "target": "research-public", "status": exc.status_code or 500}) from exc
    title = first_markdown_h1(content, args.note_id)
    return ToolOutcome(
        payload={
            "note_id": args.note_id,
            "title": title,
            "content": content[:8000],
        },
        downstream={"service": "storage", "target": "research-public", "status": 200},
    )


def build_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="search_research",
            description="Search the firm's PUBLIC equity research notes (no deal or MNPI content). Returns note ids, titles, tickers and snippets.",
            args_model=SearchResearchArgs,
            handler=search_research,
            requirement=require_any_role("Research.Read"),
            data_class="public",
        ),
        ToolDefinition(
            name="get_research_note",
            description="Fetch the full text of one public research note by its id (for example RN-001).",
            args_model=GetResearchNoteArgs,
            handler=get_research_note,
            requirement=require_any_role("Research.Read"),
            data_class="public",
        ),
    ]

