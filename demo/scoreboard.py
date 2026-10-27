"""Merge every demo\\evidence\\prove-*.json into one scoreboard: the latest result per proof id.

    python demo\\scoreboard.py            print the table and write demo\\evidence\\SCOREBOARD.md + scoreboard.json
    python demo\\scoreboard.py --check    also exit 1 unless every proof P00-P17 has a latest PASS

The harness (demo\\prove.py) writes one evidence file per run, and a run may cover only some proofs. This script
answers "what is the current state of every claim?" without re-running anything.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVIDENCE = os.path.join(HERE, "evidence")
EXPECTED = [f"P{i:02d}" for i in range(18)]


def load_latest() -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for path in glob.glob(os.path.join(EVIDENCE, "prove-*.json")):
        with open(path, encoding="utf-8") as fh:
            run = json.load(fh)
        for res in run.get("results", []):
            prev = latest.get(res["id"])
            if prev is None or run["startedUtc"] > prev["startedUtc"]:
                checks = res.get("checks", [])
                latest[res["id"]] = {
                    "id": res["id"],
                    "title": res["title"],
                    "layer": res["layer"],
                    "passed": bool(res["passed"]),
                    "checks_ok": sum(1 for c in checks if c["ok"]),
                    "checks_total": len(checks),
                    "seconds": res.get("seconds"),
                    "startedUtc": run["startedUtc"],
                    "evidence": os.path.basename(path),
                    "facts": res.get("facts", {}),
                }
    return latest


def render(latest: dict[str, dict]) -> str:
    rows = [latest[p] for p in EXPECTED if p in latest]
    ok_checks = sum(r["checks_ok"] for r in rows)
    all_checks = sum(r["checks_total"] for r in rows)
    ok_proofs = sum(1 for r in rows if r["passed"])
    out = [
        "# Agents Behind the Wall - proof scoreboard",
        "",
        f"**{ok_proofs}/{len(EXPECTED)} proofs passing, {ok_checks}/{all_checks} checks** "
        "(latest run of each proof; every row links to an evidence file in `demo\\evidence`).",
        "",
        "| Proof | Layer | What it proves | Checks | Result | Run (UTC) |",
        "|---|---|---|---|---|---|",
    ]
    for pid in EXPECTED:
        r = latest.get(pid)
        if r is None:
            out.append(f"| {pid} | - | not run yet | - | **MISSING** | - |")
            continue
        out.append(
            f"| {pid} | {r['layer']} | {r['title']} | {r['checks_ok']}/{r['checks_total']} | "
            f"{'PASS' if r['passed'] else '**FAIL**'} | {r['startedUtc'][:19]}Z |"
        )
    numbers = [(r["id"], k, v) for r in rows for k, v in r["facts"].items() if k != "clock"]
    if numbers:
        out += ["", "## Numbers measured live", "", "| Proof | Measurement | Value |", "|---|---|---|"]
        for pid, key, val in numbers:
            text = val if isinstance(val, str) else json.dumps(val)
            out.append(f"| {pid} | {key} | {text[:140].replace('|', '/')} |")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 unless P00-P17 all have a latest PASS")
    args = ap.parse_args()

    latest = load_latest()
    text = render(latest)
    print(text)
    with open(os.path.join(EVIDENCE, "SCOREBOARD.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    with open(os.path.join(EVIDENCE, "scoreboard.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump([latest[p] for p in EXPECTED if p in latest], fh, indent=2)

    missing = [p for p in EXPECTED if p not in latest]
    failing = [p for p in EXPECTED if p in latest and not latest[p]["passed"]]
    if args.check and (missing or failing):
        print(f"missing: {missing}  failing: {failing}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
