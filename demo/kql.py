"""Run KQL against the ABW Log Analytics workspace using the signed-in Azure CLI identity.

    python demo\\kql.py "AppTraces | take 3"
    python demo\\kql.py -f observability\\kql\\02-wall-denials.kql --hours 6
    python demo\\kql.py --json "ApiManagementGatewayLogs | summarize count() by ResponseCode"

Also importable: ``from kql import query_rows``.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from datetime import timedelta
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEN = ROOT / "infra" / "generated"
sys.path.insert(0, str(ROOT / "src" / "agent"))

import netfix  # noqa: E402

netfix.install()

from azure.core.exceptions import HttpResponseError  # noqa: E402
from azure.identity import AzureCliCredential  # noqa: E402
from azure.monitor.query import LogsQueryClient, LogsQueryStatus  # noqa: E402


def workspace_customer_id() -> str:
    platform = json.loads((GEN / "platform.json").read_text(encoding="utf-8-sig"))
    return platform["observability"]["lawCustomerId"]


_client: LogsQueryClient | None = None


def _logs() -> LogsQueryClient:
    global _client
    if _client is None:
        _client = LogsQueryClient(AzureCliCredential(process_timeout=90))
    return _client


def _with_retry(fn: Any, attempts: int = 4) -> Any:
    """Token refreshes and TCP resets fail transiently; a bad query or a refused caller (HTTP 4xx) does not - only the former is retried."""
    for n in range(1, attempts + 1):
        try:
            return fn()
        except HttpResponseError as exc:
            client_error = exc.status_code is not None and 400 <= exc.status_code < 500 and exc.status_code != 429
            if n == attempts or client_error:
                raise
        except Exception:  # noqa: BLE001
            if n == attempts:
                raise
        time.sleep(3 * n)


def query_rows(kql: str, hours: float = 24.0) -> list[dict[str, Any]]:
    result = _with_retry(lambda: _logs().query_workspace(workspace_customer_id(), kql, timespan=timedelta(hours=hours)))
    if result.status == LogsQueryStatus.PARTIAL:
        tables = result.partial_data
        print(f"-- partial result: {result.partial_error}", file=sys.stderr)
    else:
        tables = result.tables
    rows: list[dict[str, Any]] = []
    for table in tables:
        cols = list(table.columns)
        for row in table.rows:
            rows.append({c: _plain(v) for c, v in zip(cols, row)})
    return rows


def _plain(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _print_table(rows: list[dict[str, Any]], width: int = 46) -> None:
    if not rows:
        print("(no rows)")
        return
    cols = list(rows[0].keys())
    cells = [[_cell(r.get(c), width) for c in cols] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(widths[i]) for i, c in enumerate(cols)))
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(v.ljust(widths[i]) for i, v in enumerate(row)))
    print(f"({len(rows)} rows)")


def _cell(value: Any, width: int) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else ("" if value is None else str(value))
    text = text.replace("\r", " ").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "~"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", help="KQL text")
    ap.add_argument("-f", "--file", help="read the query from a .kql file")
    ap.add_argument("--hours", type=float, default=24.0, help="time window (default 24h)")
    ap.add_argument("--json", action="store_true", help="print JSON lines instead of a table")
    ap.add_argument("--width", type=int, default=46, help="max cell width in table mode")
    args = ap.parse_args()
    text = pathlib.Path(args.file).read_text(encoding="utf-8") if args.file else args.query
    if not text:
        ap.error("provide a query or -f file")
    rows = query_rows(text, args.hours)
    if args.json:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
    else:
        _print_table(rows, args.width)
    return 0


if __name__ == "__main__":
    sys.exit(main())
