"""Azure Resource Graph query helper for the demo (the 'az graph' extension is not required).

    python demo\\arg.py "<ARG KQL>"            # table output
    python demo\\arg.py -f query.kql --json    # JSON rows

Scope: the demo subscription from infra\\generated\\config.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests
from azure.identity import AzureCliCredential

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))

ARG_URL = "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"


def subscription_id() -> str:
    return json.loads((ROOT / "infra" / "generated" / "config.json").read_text(encoding="utf-8"))["subscriptionId"]


def _arm_token() -> str:
    for n in range(1, 5):
        try:
            return AzureCliCredential(process_timeout=90).get_token("https://management.azure.com/.default").token
        except Exception:  # noqa: BLE001 - the az token refresh fails transiently (connection reset); retry, then raise
            if n == 4:
                raise
            time.sleep(3 * n)
    raise RuntimeError("unreachable")


def query_rows(kql: str) -> list[dict]:
    token = _arm_token()
    rows: list[dict] = []
    body: dict = {"subscriptions": [subscription_id()], "query": kql, "options": {"resultFormat": "objectArray", "$top": 1000}}
    while True:
        resp = requests.post(ARG_URL, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=120)
        if resp.status_code >= 400:
            raise SystemExit(f"ARG error {resp.status_code}: {resp.text[:800]}")
        data = resp.json()
        rows.extend(data.get("data", []))
        skip = data.get("$skipToken")
        if not skip:
            return rows
        body["options"]["$skipToken"] = skip


def render(rows: list[dict], width: int) -> None:
    if not rows:
        print("(0 rows)")
        return
    cols = list(rows[0].keys())
    cells = [[("" if r.get(c) is None else (json.dumps(r[c]) if isinstance(r[c], (dict, list)) else str(r[c]))) for c in cols] for r in rows]
    widths = [min(width, max(len(c), *(len(row[i]) for row in cells))) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(widths[i]) for i, c in enumerate(cols)))
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(row[i][: widths[i]].ljust(widths[i]) for i in range(len(cols))))
    print(f"({len(rows)} rows)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("-f", "--file")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--width", type=int, default=60)
    args = ap.parse_args()
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.query
    if not text:
        ap.error("query or -f required")
    rows = query_rows(text)
    if args.json:
        for row in rows:
            print(json.dumps(row))
    else:
        render(rows, args.width)
    return 0


if __name__ == "__main__":
    sys.exit(main())
