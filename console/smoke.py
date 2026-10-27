"""Run one Demo Console job in-process and print its events - the same engine the web UI drives, without a browser.

    python console\\smoke.py kql '{"query": "denials"}'
    python console\\smoke.py gateway '{"server": "wall", "tool": "get_deal_document", "args": {"doc_id": "ORION-001"}, "tag": "orion"}'
    python console\\smoke.py agent '{"agent": "abw-wall-desk", "prompt": "crossings"}' --approve yes

Exit code 0 when the job finished "done", 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "demo"))

import jobs  # noqa: E402


def _fmt(ev: dict) -> str:
    kind = ev["type"]
    body = {k: v for k, v in ev.items() if k not in ("i", "t", "type")}
    if kind in ("http", "call"):
        head = f"{body.get('verdict', '?'):7} wall={body.get('wall')} {body.get('server')}.{body.get('tool')} HTTP {body.get('status', '-')} {body.get('decision', '')} {body.get('reason', '')}"
        extra = f" rid={body.get('request_id')}" if body.get("request_id") else ""
        leak = f" LEAK={body.get('leak')}" if body.get("leak") else ""
        attack = " ATTACK-PRESENT" if body.get("attack") else ""
        return f"{head}{extra}{leak}{attack}\n          -> {body.get('title')}: {str(body.get('plain'))[:150]}\n          lights={body.get('lights')}"
    if kind == "table":
        cols = body.get("columns", [])
        lines = [f"table '{body.get('title')}' ({body.get('total', len(body.get('rows', [])))} rows) cols={cols}"]
        lines += ["          " + " | ".join(str(c)[:28] for c in row) for row in body.get("rows", [])[:4]]
        return "\n".join(lines)
    if kind == "chain":
        lines = [f"chain rid={body.get('rid')} rows={len(body.get('rows', []))}  note={body.get('note')}"]
        lines += [f"          {r.get('step', r.get('n'))} {r['layer']:20} {str(r['actor'])[:30]:30} {str(r.get('action'))[:46]:46} {str(r['detail'])[:60]}" for r in body.get("rows", [])]
        return "\n".join(lines)
    if kind == "probe":
        p = body["probe"]
        return f"probe {p['id']:10} {p['status']:4} {p['headline'][:90]}"
    if kind in ("say", "step"):
        return f"{kind:5} [{body.get('state', '')}] {body.get('text')}"
    if kind == "answer":
        return f"answer ({body.get('seconds')}s): {str(body.get('text'))[:300]}"
    if kind == "raw":
        return f"raw   {body.get('text')}"
    return f"{kind} {json.dumps(body, default=str)[:300]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind")
    ap.add_argument("params", nargs="?", default="{}")
    ap.add_argument("--approve", choices=["ask", "yes", "no"], help="agent approval mode override")
    ap.add_argument("--raw", action="store_true", help="also print raw subprocess lines")
    args = ap.parse_args()

    params = json.loads(args.params)
    if args.approve:
        params["approve"] = args.approve
    job, err = jobs.MANAGER.start(args.kind, params, title=args.kind)
    if job is None:
        print(f"REFUSED: {err}")
        return 1
    seen = 0
    while True:
        view = job.view(seen)
        for ev in view["events"]:
            if ev["type"] == "raw" and not args.raw:
                continue
            print(f"{ev['t']:6.1f}s  {_fmt(ev)}")
        seen = view["next"]
        if view["status"] in ("done", "failed", "cancelled"):
            break
        if view["pending"]:
            print(f"        (approval {view['pending'][0]} pending - auto-approving in the harness)")
            job.answer(view["pending"][0], True)
        time.sleep(0.3)
    print(f"\n== {view['status'].upper()} in {view['elapsed']}s: {view['result'].get('summary')}")
    return 0 if view["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
