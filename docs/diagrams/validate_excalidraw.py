"""Self-check for the Excalidraw files in this folder (standard library only).

Run on its own:   python docs\\diagrams\\validate_excalidraw.py [file ...]      (default: every *.excalidraw next to this script)
It is also called by build_diagrams.py after every build; a failure makes that script exit non-zero.

Checks, per file:
  * valid JSON; top level type "excalidraw", version 2, a source string, an elements array, an appState object, files {}
  * unique element ids; every element has the full set of fields Excalidraw expects
  * numbers are finite, sizes are not negative, text is at least 16 px, roughness 0, font family 2
  * every bound text has an existing container (containerId) and the container lists it in boundElements
  * every boundElements entry points at an element that points back (text -> containerId, arrow -> a binding)
  * every arrow binding references an existing element that lists the arrow
  * ASCII only, no GUIDs, none of the strings the share rules forbid
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# Strings that must never appear in a diagram. Built from fragments so this file does not contain them either.
FORBIDDEN = [
    re.compile("kb" + "1a", re.I),
    re.compile("kv" + "gt", re.I),
    re.compile("Cal" + "dova", re.I),
    re.compile(r"\bMC" + "APS" + r"\b"),
    re.compile(r"\bE" + "CC" + r"\b"),
    re.compile("onmicro" + "soft", re.I),
    re.compile(r"@micro" + r"soft\.com", re.I),
]
TYPES = {"rectangle", "ellipse", "diamond", "text", "arrow", "line"}
COMMON = (
    "id type x y width height angle strokeColor backgroundColor fillStyle strokeWidth strokeStyle roughness opacity "
    "groupIds frameId roundness seed version versionNonce isDeleted boundElements updated link locked"
).split()
TEXT_KEYS = "text fontSize fontFamily textAlign verticalAlign containerId originalText autoResize lineHeight".split()
ARROW_KEYS = "points startBinding endBinding startArrowhead endArrowhead".split()
NUMBERS = ("x", "y", "width", "height", "angle", "strokeWidth", "opacity", "seed", "version", "versionNonce", "updated")


def _no_constants(name: str) -> Any:
    raise ValueError(f"non-finite number literal {name}")


def validate_text(raw: str, label: str = "file") -> list[str]:
    errors: list[str] = []
    bad = sorted({c for c in raw if ord(c) > 127})
    if bad:
        errors.append(f"{label}: non-ASCII characters present: {[hex(ord(c)) for c in bad][:8]}")
    for m in GUID.finditer(raw):
        errors.append(f"{label}: GUID-shaped string at offset {m.start()}")
    for pattern in FORBIDDEN:
        hit = pattern.search(raw)
        if hit:
            errors.append(f"{label}: forbidden string present at offset {hit.start()}")
    try:
        data = json.loads(raw, parse_constant=_no_constants)
    except (ValueError, json.JSONDecodeError) as exc:
        return errors + [f"{label}: not valid JSON ({exc})"]
    return errors + validate_data(data, label)


def validate_data(data: Any, label: str = "file") -> list[str]:
    errs: list[str] = []

    def err(msg: str) -> None:
        errs.append(f"{label}: {msg}")

    if not isinstance(data, dict):
        return [f"{label}: top level is not an object"]
    if data.get("type") != "excalidraw":
        err('top-level "type" must be "excalidraw"')
    if data.get("version") != 2:
        err('top-level "version" must be 2')
    if not isinstance(data.get("source"), str) or not data.get("source"):
        err('top-level "source" must be a non-empty string')
    if not isinstance(data.get("appState"), dict):
        err('top-level "appState" must be an object')
    if data.get("files") != {}:
        err('top-level "files" must be {}')
    els = data.get("elements")
    if not isinstance(els, list) or not els:
        return errs + [f"{label}: elements must be a non-empty array"]

    by_id: dict[str, dict[str, Any]] = {}
    for el in els:
        if not isinstance(el, dict) or not isinstance(el.get("id"), str):
            err("an element has no string id")
            continue
        if el["id"] in by_id:
            err(f"duplicate element id {el['id']}")
        by_id[el["id"]] = el

    for el in els:
        if not isinstance(el, dict):
            continue
        eid = el.get("id", "?")
        if el.get("type") not in TYPES:
            err(f"{eid}: unknown type {el.get('type')!r}")
            continue
        for key in COMMON:
            if key not in el:
                err(f"{eid}: missing field {key}")
        for key in NUMBERS:
            val = el.get(key)
            if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(val):
                err(f"{eid}: {key} is not a finite number")
        if isinstance(el.get("width"), (int, float)) and el["width"] < 0:
            err(f"{eid}: negative width")
        if isinstance(el.get("height"), (int, float)) and el["height"] < 0:
            err(f"{eid}: negative height")
        if el.get("roughness") != 0:
            err(f"{eid}: roughness must be 0")
        if el.get("opacity") != 100:
            err(f"{eid}: opacity must be 100")
        if el.get("isDeleted") is not False or el.get("locked") is not False:
            err(f"{eid}: isDeleted/locked must be false")
        if not isinstance(el.get("boundElements"), list) or not isinstance(el.get("groupIds"), list):
            err(f"{eid}: boundElements and groupIds must be arrays")
            continue

        if el["type"] == "text":
            for key in TEXT_KEYS:
                if key not in el:
                    err(f"{eid}: text is missing {key}")
            if el.get("fontFamily") != 2:
                err(f"{eid}: fontFamily must be 2")
            if not isinstance(el.get("fontSize"), (int, float)) or el["fontSize"] < 16:
                err(f"{eid}: fontSize must be >= 16")
            if el.get("text") != el.get("originalText"):
                err(f"{eid}: originalText must equal text")
            if el.get("lineHeight") != 1.25 or el.get("autoResize") is not True:
                err(f"{eid}: lineHeight must be 1.25 and autoResize true")
            cid = el.get("containerId")
            if cid is not None:
                box = by_id.get(cid)
                if box is None:
                    err(f"{eid}: containerId {cid} does not exist")
                elif {"id": eid, "type": "text"} not in box.get("boundElements", []):
                    err(f"{eid}: container {cid} does not list it in boundElements")

        if el["type"] == "arrow":
            for key in ARROW_KEYS:
                if key not in el:
                    err(f"{eid}: arrow is missing {key}")
            pts = el.get("points")
            if not isinstance(pts, list) or len(pts) < 2 or not all(
                isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in p) for p in pts
            ):
                err(f"{eid}: points must be a list of at least two finite [x, y] pairs")
            if el.get("endArrowhead") != "arrow":
                err(f'{eid}: endArrowhead must be "arrow"')
            for side in ("startBinding", "endBinding"):
                bind = el.get(side)
                if bind is None:
                    continue
                target = by_id.get(bind.get("elementId")) if isinstance(bind, dict) else None
                if target is None:
                    err(f"{eid}: {side} references a missing element")
                    continue
                if not isinstance(bind.get("focus"), (int, float)) or abs(bind["focus"]) > 1:
                    err(f"{eid}: {side}.focus must be within [-1, 1]")
                if not isinstance(bind.get("gap"), (int, float)) or bind["gap"] < 0:
                    err(f"{eid}: {side}.gap must be >= 0")
                if {"id": eid, "type": "arrow"} not in target.get("boundElements", []):
                    err(f"{eid}: {side} target {bind.get('elementId')} does not list the arrow in boundElements")

        for entry in el["boundElements"]:
            tid = entry.get("id") if isinstance(entry, dict) else None
            target = by_id.get(tid)
            if target is None:
                err(f"{eid}: boundElements references missing element {tid}")
                continue
            if entry.get("type") == "text" and target.get("containerId") != eid:
                err(f"{eid}: bound text {tid} does not point back (containerId)")
            if entry.get("type") == "arrow":
                ends = [(target.get("startBinding") or {}).get("elementId"), (target.get("endBinding") or {}).get("elementId")]
                if eid not in ends:
                    err(f"{eid}: bound arrow {tid} has no binding to it")
    return errs


def validate_file(path: Path) -> list[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path.name}: cannot read ({exc})"]
    return validate_text(raw, path.name)


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or sorted(HERE.glob("*.excalidraw"))
    if not paths:
        print("no .excalidraw files found")
        return 1
    bad = 0
    for path in paths:
        problems = validate_file(path)
        if problems:
            bad += 1
            print(f"FAIL {path.name}")
            for line in problems[:25]:
                print("   ", line)
            if len(problems) > 25:
                print(f"    ... and {len(problems) - 25} more")
        else:
            print(f"ok   {path.name}")
    print(f"{len(paths) - bad} of {len(paths)} files valid")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
