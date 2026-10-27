"""Seed synthetic Agents Behind the Wall demo data into Azure services."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import AzureCliCredential, ChainedTokenCredential, DefaultAzureCredential, ManagedIdentityCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SimpleField,
)
from azure.storage.blob import BlobServiceClient

try:
    from azure.cosmos import CosmosClient
except ImportError:  # pragma: no cover
    CosmosClient = None

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data"
PLATFORM_JSON = ROOT.parent.parent / "infra" / "generated" / "platform.json"


@dataclass(slots=True)
class SeedConfig:
    storage_name: str
    cosmos_endpoint: str
    search_endpoint: str
    search_index: str
    cosmos_database: str = "abw"

    @property
    def storage_account_url(self) -> str:
        return f"https://{self.storage_name}.blob.core.windows.net"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed ABW synthetic demo data.")
    parser.add_argument("--storage-name")
    parser.add_argument("--cosmos-endpoint")
    parser.add_argument("--search-endpoint")
    parser.add_argument("--search-index", default="deals-idx")
    parser.add_argument("--cosmos-database", default="abw")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_platform_defaults() -> dict[str, Any]:
    if not PLATFORM_JSON.exists():
        return {}
    with PLATFORM_JSON.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_config(args: argparse.Namespace) -> SeedConfig:
    # Precedence: CLI flag > environment (container job) > infra/generated/platform.json (local dry-run).
    platform = load_platform_defaults()
    storage_name = args.storage_name or os.environ.get("STORAGE_ACCOUNT") or platform.get("storage", {}).get("name")
    cosmos_endpoint = args.cosmos_endpoint or os.environ.get("COSMOS_ENDPOINT") or platform.get("cosmos", {}).get("endpoint")
    search_endpoint = args.search_endpoint or os.environ.get("SEARCH_ENDPOINT") or platform.get("search", {}).get("endpoint")
    missing = [name for name, value in {"storage.name": storage_name, "cosmos.endpoint": cosmos_endpoint, "search.endpoint": search_endpoint}.items() if not value]
    if missing:
        raise SystemExit(f"Missing required platform values: {', '.join(missing)}")
    return SeedConfig(
        storage_name=storage_name,
        cosmos_endpoint=cosmos_endpoint,
        search_endpoint=search_endpoint,
        search_index=args.search_index,
        cosmos_database=args.cosmos_database,
    )


def get_credential():
    # In the in-VNet seed job AZURE_CLIENT_ID selects the seed user-assigned identity (no secrets, no keys).
    if os.environ.get("AZURE_CLIENT_ID"):
        return ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"])
    return ChainedTokenCredential(
        AzureCliCredential(process_timeout=90),
        DefaultAzureCredential(exclude_interactive_browser_credential=True),
    )


def load_markdown_files() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for directory in ("research", "wall-falcon", "wall-orion"):
        folder = DATA_ROOT / directory
        files = {}
        for path in sorted(folder.glob("*.md")):
            files[path.name] = path.read_text(encoding="utf-8")
        result[directory] = files
    return result


def first_h1(content: str, fallback: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def make_search_index(index_name: str) -> SearchIndex:
    return SearchIndex(
        name=index_name,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True, sortable=True, filterable=True),
            SearchableField(name="title", type=SearchFieldDataType.String),
            SearchableField(name="content", type=SearchFieldDataType.String, retrievable=True),
            SearchableField(name="summary", type=SearchFieldDataType.String, retrievable=True),
            SearchableField(name="snippet", type=SearchFieldDataType.String, retrievable=True),
            SimpleField(name="ticker", type=SearchFieldDataType.String, filterable=True, sortable=True),
            SimpleField(name="classification", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="project", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="blob_path", type=SearchFieldDataType.String, retrievable=True),
            SearchField(name="updated", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
        ],
    )


def build_search_documents(markdown_sets: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    updated = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for filename, content in markdown_sets["research"].items():
        note_id = filename.removesuffix(".md")
        lines = [line for line in content.splitlines() if line.strip()]
        ticker_line = next((line for line in lines if line.startswith("Ticker: ")), "Ticker: UNKNOWN")
        snippet = content[:200]
        docs.append(
            {
                "id": note_id,
                "title": first_h1(content, note_id),
                "content": content,
                "summary": None,
                "snippet": snippet,
                "ticker": ticker_line.replace("Ticker: ", "").strip(),
                "classification": "public",
                "project": None,
                "blob_path": f"research-public/{filename}",
                "updated": updated,
            }
        )
    for directory, project in (("wall-falcon", "falcon"), ("wall-orion", "orion")):
        for filename, content in markdown_sets[directory].items():
            doc_id = filename.removesuffix(".md")
            body_lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("SYNTHETIC DEMO")]
            summary = " ".join(body_lines[2:4])[:240]
            docs.append(
                {
                    "id": doc_id,
                    "title": first_h1(content, doc_id),
                    "content": None,
                    "summary": summary,
                    "snippet": None,
                    "ticker": "ZYNX" if project == "falcon" else "VRDN",
                    "classification": "wall",
                    "project": project,
                    "blob_path": f"wall-{project}/{filename}",
                    "updated": updated,
                }
            )
    return docs


def upload_blobs(config: SeedConfig, credential: Any, markdown_sets: dict[str, dict[str, str]], dry_run: bool) -> int:
    if dry_run:
        return sum(len(files) for files in markdown_sets.values())
    service = BlobServiceClient(account_url=config.storage_account_url, credential=credential)
    uploads = 0
    for directory, container in (("research", "research-public"), ("wall-falcon", "wall-falcon"), ("wall-orion", "wall-orion")):
        container_client = service.get_container_client(container)
        for filename, content in markdown_sets[directory].items():
            container_client.upload_blob(name=filename, data=content.encode("utf-8"), overwrite=True)
            uploads += 1
    return uploads


def sync_search_index(config: SeedConfig, credential: Any, documents: list[dict[str, Any]], dry_run: bool) -> int:
    if dry_run:
        return len(documents)
    index_client = SearchIndexClient(endpoint=config.search_endpoint, credential=credential)
    index_client.create_or_update_index(make_search_index(config.search_index))
    search_client = SearchClient(endpoint=config.search_endpoint, index_name=config.search_index, credential=credential)
    batch_result = search_client.merge_or_upload_documents(documents)
    return sum(1 for result in batch_result if result.succeeded)


def ensure_container(database, name: str):
    container = database.get_container_client(name)
    try:
        container.read()
    except ResourceNotFoundError as exc:
        raise SystemExit(f"Cosmos container '{name}' is missing. Create it via Bicep before seeding.") from exc
    except HttpResponseError as exc:
        raise SystemExit(f"Failed to access Cosmos container '{name}': {exc}") from exc
    return container


def seed_cosmos(config: SeedConfig, credential: Any, dry_run: bool) -> dict[str, int]:
    restricted_items = [
        {"id": "ZYNX", "ticker": "ZYNX", "project": "falcon", "reason": "deal-restricted", "added": "2026-10-13T00:00:00Z"},
        {"id": "HLCN", "ticker": "HLCN", "project": "falcon", "reason": "deal-restricted", "added": "2026-10-13T00:00:00Z"},
        {"id": "VRDN", "ticker": "VRDN", "project": "orion", "reason": "deal-restricted", "added": "2026-10-13T00:00:00Z"},
        {"id": "ORBS", "ticker": "ORBS", "project": "orion", "reason": "deal-restricted", "added": "2026-10-13T00:00:00Z"},
    ]
    positions = [
        {"id": "rates-1", "desk": "rates", "ticker": "UST2", "quantity": 1250000, "market_value_usd": 1247500},
        {"id": "rates-2", "desk": "rates", "ticker": "UST10", "quantity": -840000, "market_value_usd": -835400},
        {"id": "rates-3", "desk": "rates", "ticker": "MBSA", "quantity": 420000, "market_value_usd": 417200},
        {"id": "rates-4", "desk": "rates", "ticker": "SOFR1", "quantity": 650000, "market_value_usd": 649100},
        {"id": "rates-5", "desk": "rates", "ticker": "TIPS5", "quantity": -210000, "market_value_usd": -208900},
        {"id": "rates-6", "desk": "rates", "ticker": "AGCY7", "quantity": 305000, "market_value_usd": 304250},
        {"id": "equities-1", "desk": "equities", "ticker": "ACME", "quantity": 150000, "market_value_usd": 6225000},
        {"id": "equities-2", "desk": "equities", "ticker": "GLBX", "quantity": -80000, "market_value_usd": -3520000},
        {"id": "equities-3", "desk": "equities", "ticker": "MRDN", "quantity": 95000, "market_value_usd": 2945000},
        {"id": "equities-4", "desk": "equities", "ticker": "NTRX", "quantity": 125000, "market_value_usd": 4687500},
        {"id": "equities-5", "desk": "equities", "ticker": "SPY", "quantity": -15000, "market_value_usd": -8212500},
        {"id": "equities-6", "desk": "equities", "ticker": "QQQ", "quantity": 11000, "market_value_usd": 5368000},
        {"id": "credit-1", "desk": "credit", "ticker": "HYETF", "quantity": 500000, "market_value_usd": 4980000},
        {"id": "credit-2", "desk": "credit", "ticker": "IGETF", "quantity": 625000, "market_value_usd": 6275000},
        {"id": "credit-3", "desk": "credit", "ticker": "CDXIG", "quantity": -350000, "market_value_usd": -3484000},
        {"id": "credit-4", "desk": "credit", "ticker": "CDXHY", "quantity": 180000, "market_value_usd": 1767000},
        {"id": "credit-5", "desk": "credit", "ticker": "BANKS", "quantity": 90000, "market_value_usd": 2730000},
        {"id": "credit-6", "desk": "credit", "ticker": "UTIL", "quantity": -70000, "market_value_usd": -1960000},
        {"id": "limit-northwind-capital", "desk": "credit", "counterparty": "Northwind Capital", "limit_usd": 15000000, "utilization_usd": 6200000},
        {"id": "limit-contoso-prime", "desk": "credit", "counterparty": "Contoso Prime", "limit_usd": 18500000, "utilization_usd": 9100000},
        {"id": "limit-fabrikam-clearing", "desk": "credit", "counterparty": "Fabrikam Clearing", "limit_usd": 12000000, "utilization_usd": 4150000},
        {"id": "limit-tailspin-securities", "desk": "credit", "counterparty": "Tailspin Securities", "limit_usd": 10000000, "utilization_usd": 3700000},
    ]
    if dry_run:
        return {"restricted": len(restricted_items), "positions": len(positions), "orders": 0}
    if CosmosClient is None:
        raise SystemExit("azure-cosmos is not installed in this environment.")
    client = CosmosClient(url=config.cosmos_endpoint, credential=credential)
    database = client.get_database_client(config.cosmos_database)
    restricted = ensure_container(database, "restricted")
    positions_container = ensure_container(database, "positions")
    ensure_container(database, "orders")
    for item in restricted_items:
        restricted.upsert_item(item)
    for item in positions:
        positions_container.upsert_item(item)
    return {"restricted": len(restricted_items), "positions": len(positions), "orders": 0}


def validate_shapes(markdown_sets: dict[str, dict[str, str]], documents: list[dict[str, Any]]) -> None:
    for directory, files in markdown_sets.items():
        if not files:
            raise SystemExit(f"No markdown files found in {directory}.")
        for name, content in files.items():
            if not content.startswith("SYNTHETIC DEMO DATA — NOT REAL"):
                raise SystemExit(f"{name} is missing the synthetic-data banner.")
            if directory != "research" and "MNPI — WALL-CROSSED ONLY" not in content:
                raise SystemExit(f"{name} is missing the MNPI banner.")
    if len(documents) != 24:
        raise SystemExit(f"Expected 24 indexed documents, found {len(documents)}.")


def main() -> None:
    args = parse_args()
    config = resolve_config(args)
    markdown_sets = load_markdown_files()
    documents = build_search_documents(markdown_sets)
    validate_shapes(markdown_sets, documents)
    if args.dry_run:
        credential = None
    else:
        credential = get_credential()
    blob_count = upload_blobs(config, credential, markdown_sets, args.dry_run)
    search_count = sync_search_index(config, credential, documents, args.dry_run)
    cosmos_counts = seed_cosmos(config, credential, args.dry_run)
    print(
        f"seed complete dry_run={args.dry_run} blobs={blob_count} search_docs={search_count} "
        f"restricted={cosmos_counts['restricted']} positions={cosmos_counts['positions']} orders={cosmos_counts['orders']}"
    )


if __name__ == "__main__":
    main()
