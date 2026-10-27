"""Build, run and check the ABW Log Analytics function pack (observability/kql/*.kql).

Every ``*.kql`` file is one workspace function. The first comment lines carry the metadata:

    // @function AbwDenials
    // @params lookback:timespan = 24h
    // @description ...
    // @fallback <query>        (optional: what the function deploys as when no Entra workspace is configured)

    python observability\\kql\\pack.py build                     # writes observability\\kql\\pack.json (consumed by infra\\06b-observability.bicep)
    python observability\\kql\\pack.py run "AbwDenials(24h) | take 20"
    python observability\\kql\\pack.py check                     # run every function once, report rows / errors

AbwFullChain reads the Entra sign-in tables, which usually live in the tenant's Entra export workspace. Its ``let entra... = <table>;`` lines are
rewritten to ``workspace('<id>').<table>`` at deploy time (infra\\06b-observability.bicep, parameter ``entraWorkspaceId``). ``--local`` runs do the
same with the ``ABW_ENTRA_WORKSPACE_ID`` environment variable; without it AbwFullChain is its ``@fallback``, AbwFullChainCore.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACK_JSON = HERE / "pack.json"

_META = re.compile(r"^//\s*@(function|params|description|fallback)\s+(.*)$")

ENTRA_ENV = "ABW_ENTRA_WORKSPACE_ID"
_ENTRA_TABLES = ("AADNonInteractiveUserSignInLogs", "SigninLogs")

#  default probe call per function for `check`
_CHECK_CALLS = {
    "AbwMcpAudit": "AbwMcpAudit(24h) | take 5",
    "AbwGateway": "AbwGateway(24h) | take 5",
    "AbwDenials": "AbwDenials(24h) | take 5",
    "AbwAgentActivity": "AbwAgentActivity(24h) | take 5",
    "AbwUsageByUser": "AbwUsageByUser(7d) | take 5",
    "AbwTokenUsage": "AbwTokenUsage(24h) | take 5",
    "AbwZeroKeys": "AbwZeroKeys(30d) | take 5",
    "AbwIdentityChain": "AbwIdentityChain('00000000-0000-0000-0000-000000000000') | take 5",
    "AbwFullChainCore": "AbwFullChainCore('00000000-0000-0000-0000-000000000000') | take 5",
    "AbwFullChain": "AbwFullChain('00000000-0000-0000-0000-000000000000') | take 5",
}


def load_pack() -> list[dict[str, str]]:
    functions: list[dict[str, str]] = []
    for path in sorted(HERE.glob("*.kql")):
        meta: dict[str, str] = {}
        body: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _META.match(line.strip())
            if m and not body:
                meta[m.group(1)] = m.group(2).strip()
            else:
                body.append(line)
        if "function" not in meta:
            raise SystemExit(f"{path.name}: missing '// @function <Name>' header")
        functions.append(
            {
                "name": meta["function"],
                "params": meta.get("params", ""),
                "description": meta.get("description", ""),
                "fallback": meta.get("fallback", ""),
                "body": "\n".join(body).strip(),
                "file": path.name,
            }
        )
    return _dependency_order(functions)


def _dependency_order(functions: list[dict[str, str]]) -> list[dict[str, str]]:
    names = {f["name"] for f in functions}
    ordered: list[dict[str, str]] = []
    placed: set[str] = set()
    pending = list(functions)
    while pending:
        progressed = False
        for fn in list(pending):
            deps = {n for n in names if n != fn["name"] and re.search(rf"\b{n}\s*\(", fn["body"])}
            if deps <= placed:
                ordered.append(fn)
                placed.add(fn["name"])
                pending.remove(fn)
                progressed = True
        if not progressed:
            raise SystemExit(f"circular function dependency among: {[f['name'] for f in pending]}")
    return ordered


def _localize(text: str, names: list[str]) -> str:
    """Point every call of a pack function at its local ``_L`` copy so it cannot collide with the deployed function."""
    return re.sub(rf"\b({'|'.join(re.escape(n) for n in names)})\b(?=\s*\()", r"\1_L", text)


def deploy_body(fn: dict[str, str], entra_ws: str = "") -> str:
    """The query text a function is deployed with. Mirrors infra\\06b-observability.bicep.

    With no Entra workspace a function that declares ``// @fallback`` deploys that; otherwise its Entra table lines read from the workspace.
    """
    if not entra_ws and fn.get("fallback"):
        return fn["fallback"]
    prefix = f"workspace('{entra_ws}')." if entra_ws else ""
    body = fn["body"]
    for table in _ENTRA_TABLES:
        body = body.replace(f"= {table};", f"= {prefix}{table};")
    return body


def let_prelude(functions: list[dict[str, str]]) -> str:
    names = [fn["name"] for fn in functions]
    entra_ws = os.environ.get(ENTRA_ENV, "").strip()
    parts = []
    for fn in functions:
        parts.append(f"let {fn['name']}_L = ({fn['params']}) {{\n{_localize(deploy_body(fn, entra_ws), names)}\n}};")
    return "\n".join(parts)


def cmd_build(_: argparse.Namespace) -> None:
    functions = load_pack()
    payload = [
        {k: fn[k] for k in ("name", "params", "description", "fallback", "body")} for fn in functions
    ]
    PACK_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {PACK_JSON.relative_to(ROOT)}  ({len(payload)} functions: {', '.join(f['name'] for f in payload)})")


def _run(expr: str, hours: float, local: bool = False) -> list[dict]:
    """Run ``expr`` against the workspace.

    Uses the deployed workspace functions when they exist; falls back to the local ``let`` prelude when they are
    not resolvable yet (before 06b is deployed) or when ``local`` is set (to test edited .kql files before redeploy).
    """
    sys.path.insert(0, str(ROOT / "demo"))
    from kql import query_rows  # noqa: E402

    if not local:
        try:
            return query_rows(expr, hours=hours)
        except Exception as exc:  # noqa: BLE001
            if "Failed to resolve" not in str(exc) and "SEM0100" not in str(exc):
                raise
    functions = load_pack()
    return query_rows(let_prelude(functions) + "\n" + _localize(expr, [fn["name"] for fn in functions]), hours=hours)


def cmd_run(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(ROOT / "demo"))
    from kql import _print_table  # noqa: E402

    _print_table(_run(args.expr, args.hours, args.local), width=args.width)


def cmd_check(args: argparse.Namespace) -> None:
    failed = 0
    for fn in load_pack():
        call = _CHECK_CALLS.get(fn["name"], f"{fn['name']}() | take 5")
        try:
            rows = _run(call, args.hours, args.local)
            print(f"  ok   {fn['name']:<18} {len(rows)} row(s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            text = str(exc).replace("\n", " ")
            print(f"  FAIL {fn['name']:<18} {text[:240]}")
    raise SystemExit(1 if failed else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    p_run = sub.add_parser("run")
    p_run.add_argument("expr")
    p_run.add_argument("--hours", type=float, default=168.0)
    p_run.add_argument("--width", type=int, default=46)
    p_run.add_argument("--local", action="store_true", help="use the local .kql files instead of the deployed functions")
    p_run.set_defaults(fn=cmd_run)
    p_check = sub.add_parser("check")
    p_check.add_argument("--hours", type=float, default=720.0)
    p_check.add_argument("--local", action="store_true", help="use the local .kql files instead of the deployed functions")
    p_check.set_defaults(fn=cmd_check)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
