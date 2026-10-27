"""Runaway-agent simulation: hammer the gateway with one user's token and watch it throttle.

This is proof P14 as a stand-alone, stage-friendly script (about 4 seconds).

    python demo\\burst.py                       # 400 calls, 48 workers, research MCP server
    python demo\\burst.py --calls 600 --server wall
    python demo\\burst.py --persona priya       # the same burst as Priya, using her cached sign-in (one device-code prompt if she has none)

The gateway limit is a token bucket per user (`rate-limit-by-key calls=120 renewal-period=60` keyed on the token's `oid`), so a
loop that outruns the refill gets HTTP 429 with a Retry-After header - the other users are unaffected, and Sentinel rule
ABW-009 records the burst.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcpclient as mc  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calls", type=int, default=400)
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--server", choices=["research", "wall", "actions", "private", "vendor"], default="research")
    ap.add_argument("--persona", choices=["priya", "wes", "tara", "carla", "ian"], help="burst as this persona instead of the signed-in operator")
    ns = ap.parse_args()

    token = mc.persona_token(ns.persona, ns.server) if ns.persona else mc.admin_token(ns.server)
    who = mc.summarize(token)
    url = mc.GATEWAY[ns.server]
    print(f"caller : {who.get('upn') or who.get('preferred_username') or who.get('oid')}  (oid {str(who.get('oid'))[:8]}...)")
    print(f"target : {ns.server} MCP server through the APIM gateway - {ns.calls} tools/list calls, {ns.workers} in flight")
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "Authorization": f"Bearer {token}"}

    def one(_: int) -> tuple[int, str]:
        try:
            resp = client.post(url, headers={**headers, "x-abw-request-id": str(uuid.uuid4())}, json=body)
            return resp.status_code, resp.headers.get("retry-after", "")
        except Exception as exc:  # noqa: BLE001
            return -1, type(exc).__name__

    started = time.time()
    done: list[tuple[int, str]] = []
    with httpx.Client(timeout=45, limits=httpx.Limits(max_connections=64, max_keepalive_connections=64)) as client:
        with cf.ThreadPoolExecutor(max_workers=ns.workers) as pool:
            futures = [pool.submit(one, i) for i in range(ns.calls)]
            for fut in cf.as_completed(futures):
                done.append(fut.result())
    elapsed = time.time() - started

    counts = collections.Counter(code for code, _ in done)
    first_429 = next((i + 1 for i, (code, _) in enumerate(done) if code == 429), None)
    retry = next((r for code, r in done if code == 429 and r), "")
    widest = max(counts.values()) if counts else 1
    print()
    for code, n in sorted(counts.items()):
        label = {200: "served", 429: "throttled", 401: "no token", 403: "refused"}.get(code, "error" if code < 0 else "")
        print(f"  HTTP {code:>3}  {'#' * max(1, round(40 * n / widest)):<40} {n:>4}  {label}")
    print(f"\n{ns.calls} calls in {elapsed:.1f}s - first 429 came back as response #{first_429}; Retry-After: {retry or 'n/a'}s")
    print("every call carried the same user's token; other users' budgets are untouched (the key is the token's oid).")
    return 0 if counts.get(429) else 1


if __name__ == "__main__":
    sys.exit(main())
