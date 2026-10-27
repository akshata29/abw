"""Build and check the ABW Sentinel analytics rules (observability/sentinel/*.kql).

Each ``*.kql`` file is one scheduled analytics rule. The leading ``// @key value`` lines carry the metadata:

    // @id wall-violation                          stable key (used for the rule GUID)
    // @name ABW-001 ...                            display name
    // @severity High|Medium|Low|Informational
    // @tactics Collection InitialAccess            MITRE ATT&CK tactic names (space separated)
    // @frequency PT5M   // @period PT30M            query frequency / look-back (ISO-8601)
    // @group Account|AnyAlert                      incident grouping: per Account entity, or one incident per rule
    // @entity Account.FullName=UserUpn IP.Address=CallerIp   entity mappings  <Type>.<identifier>=<column>
    // @details Server=Server Tool=Tool             custom details  <label>=<column>
    // @description ...

    python observability\\sentinel\\build_rules.py build          # writes observability\\sentinel\\rules.json (consumed by infra\\06b-observability.bicep)
    python observability\\sentinel\\build_rules.py check          # run every rule query (as written) and report errors
    python observability\\sentinel\\build_rules.py check --wide   # same, but widen the look-back to 30 days to show sample hits
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RULES_JSON = HERE / "rules.json"

_META = re.compile(r"^//\s*@(\w+)\s+(.*)$")
_REQUIRED = ("id", "name", "severity", "tactics", "frequency", "period", "description")


def load_rules() -> list[dict]:
    rules: list[dict] = []
    for path in sorted(HERE.glob("*.kql")):
        meta: dict[str, str] = {}
        body: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _META.match(line.strip())
            if m and not body:
                meta[m.group(1)] = m.group(2).strip()
            else:
                body.append(line)
        missing = [k for k in _REQUIRED if k not in meta]
        if missing:
            raise SystemExit(f"{path.name}: missing metadata {missing}")
        entities: dict[str, list[dict[str, str]]] = {}
        for token in meta.get("entity", "").split():
            target, column = token.split("=", 1)
            entity_type, identifier = target.split(".", 1)
            entities.setdefault(entity_type, []).append({"identifier": identifier, "columnName": column})
        details = dict(token.split("=", 1) for token in meta.get("details", "").split())
        rules.append(
            {
                "id": meta["id"],
                "name": meta["name"],
                "severity": meta["severity"],
                "tactics": meta["tactics"].split(),
                "frequency": meta["frequency"],
                "period": meta["period"],
                "group": meta.get("group", "AnyAlert"),
                "entities": [{"entityType": t, "fieldMappings": maps} for t, maps in entities.items()],
                "details": details,
                "description": meta["description"],
                "query": "\n".join(body).strip(),
                "file": path.name,
            }
        )
    return rules


def cmd_build(_: argparse.Namespace) -> None:
    rules = load_rules()
    payload = [{k: v for k, v in r.items() if k != "file"} for r in rules]
    RULES_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {RULES_JSON.relative_to(ROOT)}  ({len(payload)} rules)")


def cmd_check(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(ROOT / "observability" / "kql"))
    import pack  # noqa: E402

    failed = 0
    for rule in load_rules():
        query = rule["query"]
        if args.wide:
            query = re.sub(r"\((\d+)(m|h)\)", "(30d)", query)
        try:
            rows = pack._run(query, 720.0 if args.wide else 24.0)
            print(f"  ok   {rule['id']:<24} {rule['severity']:<7} {len(rows)} row(s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {rule['id']:<24} {str(exc).replace(chr(10), ' ')[:240]}")
    raise SystemExit(1 if failed else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    p_check = sub.add_parser("check")
    p_check.add_argument("--wide", action="store_true")
    p_check.set_defaults(fn=cmd_check)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
