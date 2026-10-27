"""Wall-crossed document server tools."""

from __future__ import annotations

from pydantic import Field
from typing_extensions import Literal

from ..data import DataAccessError
from ..registry import ArgsModel, ToolDefinition, ToolError, ToolOutcome, require_any_role
from ..runtime import RuntimeServices
from ..util import first_markdown_h1

PROJECT_TITLES = {
    "falcon": "Project Falcon",
    "orion": "Project Orion",
}


class SearchDealDocumentsArgs(ArgsModel):
    query: str = Field(min_length=1, max_length=200)
    project: Literal["falcon", "orion"] = Field(description="Deal code, lowercase: falcon (Project Falcon) or orion (Project Orion).")
    limit: int = Field(default=5, ge=1, le=10)


class GetDealDocumentArgs(ArgsModel):
    doc_id: str = Field(pattern=r"^(FALCON|ORION)-\d{3}$", description="Document id such as FALCON-001 or ORION-003.")


def caller_projects(caller) -> set[str]:
    projects = set()
    for role in getattr(caller, "roles", ()):
        if role == "Wall.Falcon":
            projects.add("falcon")
        if role == "Wall.Orion":
            projects.add("orion")
    return projects


def _require_project(caller, project: str) -> None:
    if project not in caller_projects(caller):
        raise ToolError(
            "FORBIDDEN",
            "Caller is not crossed on that project.",
            reason="project_not_in_token_roles",
            audit_event="wall_violation_attempt",
            downstream={"service": "search", "target": project, "status": 403},
        )


async def list_my_wall_crossings(caller, args: ArgsModel, runtime: RuntimeServices) -> ToolOutcome:
    crossings = [
        {
            "project": project,
            "codename": PROJECT_TITLES[project],
            "summary": f"{PROJECT_TITLES[project]} synthetic confidential M&A mandate.",
        }
        for project in sorted(caller_projects(caller))
    ]
    return ToolOutcome(payload={"crossings": crossings}, downstream={"service": "token", "target": "roles", "status": 200})


async def search_deal_documents(caller, args: SearchDealDocumentsArgs, runtime: RuntimeServices) -> ToolOutcome:
    _require_project(caller, args.project)
    rows = await runtime.data.search_documents(
        caller=caller,
        query=args.query,
        filter_text=f"classification eq 'wall' and project eq '{args.project}'",
        select=["id", "title", "summary", "updated"],
        top=args.limit,
    )
    return ToolOutcome(
        payload={
            "project": args.project,
            "results": [
                {
                    "doc_id": row.get("id"),
                    "title": row.get("title"),
                    "summary": row.get("summary"),
                    "updated": row.get("updated"),
                }
                for row in rows
            ],
        },
        downstream={"service": "search", "target": runtime.settings.search_index, "status": 200},
    )


async def get_deal_document(caller, args: GetDealDocumentArgs, runtime: RuntimeServices) -> ToolOutcome:
    project = args.doc_id.split("-", 1)[0].lower()
    _require_project(caller, project)
    container = f"wall-{project}"
    try:
        content = await runtime.data.read_blob_text(caller=caller, container=container, blob_name=f"{args.doc_id}.md")
    except DataAccessError as exc:
        audit_event = "wall_violation_attempt" if exc.reason == "storage_rbac_denied" else "tool_denied"
        raise ToolError(exc.code, exc.message, reason=exc.reason, audit_event=audit_event, downstream={"service": "storage", "target": container, "status": exc.status_code or 500}) from exc
    return ToolOutcome(
        payload={
            "doc_id": args.doc_id,
            "project": project,
            "title": first_markdown_h1(content, args.doc_id),
            "content": content[:8000],
        },
        downstream={"service": "storage", "target": container, "status": 200},
    )


class EmptyArgs(ArgsModel):
    pass


def build_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="list_my_wall_crossings",
            description="List the confidential deal projects (information barrier wall-crossings) the signed-in user is cleared for.",
            args_model=EmptyArgs,
            handler=list_my_wall_crossings,
            requirement=require_any_role("Wall.Falcon", "Wall.Orion"),
            data_class="wall",
        ),
        ToolDefinition(
            name="search_deal_documents",
            description="Search confidential (MNPI) deal-room documents for ONE project the user is wall-crossed on. project must be falcon or orion.",
            args_model=SearchDealDocumentsArgs,
            handler=search_deal_documents,
            requirement=require_any_role("Wall.Falcon", "Wall.Orion"),
            data_class="wall",
        ),
        ToolDefinition(
            name="get_deal_document",
            description="Fetch the full text of one confidential deal-room document (for example FALCON-001). Only for projects the user is wall-crossed on.",
            args_model=GetDealDocumentArgs,
            handler=get_deal_document,
            requirement=require_any_role("Wall.Falcon", "Wall.Orion"),
            data_class="wall",
        ),
    ]

