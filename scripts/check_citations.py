"""Citation checker for the architecture and design documents of Agents Behind the Wall.

Every behavioural claim in docs/ARCHITECTURE-AND-DESIGN.md and the chapter files in docs/architecture/ points at source with an inline-code citation:

    `src/mcp/abw_mcp/auth.py:120-168#validate_token`      range of lines, optional symbol
    `infra/05-apim-apis.bicep:45#roles`                   single line, optional symbol

This tool proves each citation: the file exists inside the repository, the lines are in range, and the symbol (a literal substring) appears
inside the cited lines. It also lints the text (ASCII only, no private paths) and reports sections that cite nothing.

    python scripts/check_citations.py docs/ARCHITECTURE-AND-DESIGN.md
    python scripts/check_citations.py path/to/part-A.md path/to/part-B.md --root . --stats

Exit code 0 = every citation verified and no lint failures; 1 = at least one failure. Standard library only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CITE = re.compile(r"`((?:[A-Za-z0-9_.\-/\\]+\.[A-Za-z0-9]{1,8}|[A-Za-z0-9_.\-/\\]*(?:Dockerfile|\.gitignore))):(\d+)(?:-(\d+))?(?:#([^`]+))?`")
HEADING = re.compile(r"^(#{2,4})\s+(.*\S)\s*$")
DIAGRAM = re.compile(r"docs/diagrams/([A-Za-z0-9_\-]+)\.excalidraw")
PRIVATE_PREFIXES = (".secrets/", "infra/generated/", "demo/evidence/", "_archive/", ".venv/", ".env")

_line_cache: dict[Path, list[str]] = {}


def read_lines(path: Path) -> list[str]:
    if path not in _line_cache:
        raw = path.read_bytes().decode("utf-8-sig", errors="replace")
        lines = raw.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        _line_cache[path] = [ln.rstrip("\r") for ln in lines]
    return _line_cache[path]


def nearest(lines: list[str], symbol: str, around: int) -> str:
    hits = [i + 1 for i, ln in enumerate(lines) if symbol in ln]
    if not hits:
        return "symbol not found anywhere in the file"
    hits.sort(key=lambda n: abs(n - around))
    return "symbol appears at line(s) " + ", ".join(str(n) for n in hits[:5])


def check_doc(doc: Path, root: Path, max_span: int, diagrams_dir: Path, strict_diagrams: bool) -> dict:
    text = doc.read_text(encoding="utf-8-sig", errors="replace")
    res = {"cites": 0, "files": {}, "fail": [], "warn": [], "sections": []}
    section = None
    sec_count = 0

    def close_section():
        if section is not None:
            res["sections"].append((section, sec_count))

    for lineno, line in enumerate(text.split("\n"), 1):
        line = line.rstrip("\r")
        for col, ch in enumerate(line, 1):
            if ord(ch) > 127:
                res["fail"].append(f"{doc.name}:{lineno}:{col}: non-ASCII character U+{ord(ch):04X} (documents are ASCII only; no em/en dashes)")
                break
        m = HEADING.match(line)
        if m:
            close_section()
            section, sec_count = m.group(2), 0
        for d in DIAGRAM.finditer(line):
            if not (diagrams_dir / f"{d.group(1)}.excalidraw").exists():
                (res["fail"] if strict_diagrams else res["warn"]).append(f"{doc.name}:{lineno}: diagram {d.group(1)}.excalidraw does not exist yet")
        for c in CITE.finditer(line):
            rel = c.group(1).replace("\\", "/")
            rel = rel[2:] if rel.startswith("./") else rel
            a, b, sym = int(c.group(2)), c.group(3), c.group(4)
            start, end = a, int(b) if b else a
            res["cites"] += 1
            sec_count += 1
            where = f"{doc.name}:{lineno}: `{c.group(0).strip('`')}`"
            if rel.startswith(PRIVATE_PREFIXES):
                res["fail"].append(f"{where}: cites a private path (state, secrets or raw evidence); cite source instead")
                continue
            f = (root / rel).resolve()
            if root.resolve() not in f.parents or not f.is_file():
                res["fail"].append(f"{where}: file not found in the repository")
                continue
            lines = read_lines(f)
            if start < 1 or end < start or end > len(lines):
                res["fail"].append(f"{where}: line range outside the file (file has {len(lines)} lines)")
                continue
            if end - start + 1 > max_span:
                res["warn"].append(f"{where}: span of {end - start + 1} lines is broad; narrow it (max {max_span})")
            if sym and not any(sym in ln for ln in lines[start - 1:end]):
                res["fail"].append(f"{where}: symbol not inside the cited lines; {nearest(lines, sym, start)}")
                continue
            res["files"][rel] = res["files"].get(rel, 0) + 1
    close_section()
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docs", nargs="+", help="markdown file(s) to check")
    ap.add_argument("--root", default=str(ROOT), help="repository root that citations are relative to (default: this repository)")
    ap.add_argument("--max-span", type=int, default=80, help="warn when a cited range is longer than this many lines")
    ap.add_argument("--diagrams-dir", default=None, help="folder holding the .excalidraw files (default: <root>/docs/diagrams)")
    ap.add_argument("--strict-diagrams", action="store_true", help="fail (not warn) when a referenced diagram does not exist")
    ap.add_argument("--stats", action="store_true", help="print cited-files table and sections without citations")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    diagrams = Path(args.diagrams_dir).resolve() if args.diagrams_dir else root / "docs" / "diagrams"
    total_fail = 0
    for d in args.docs:
        doc = Path(d).resolve()
        if not doc.is_file():
            print(f"{d}: not found")
            total_fail += 1
            continue
        r = check_doc(doc, root, args.max_span, diagrams, args.strict_diagrams)
        for w in r["warn"]:
            print("WARN  " + w)
        for f in r["fail"]:
            print("FAIL  " + f)
        bare = [s for s, n in r["sections"] if n == 0]
        print(f"{doc.name}: {r['cites']} citations, {len(r['files'])} distinct files, {len(r['fail'])} failure(s), {len(r['warn'])} warning(s), "
              f"{len(bare)} of {len(r['sections'])} sections without a citation")
        if args.stats:
            for rel, n in sorted(r["files"].items(), key=lambda kv: -kv[1]):
                print(f"   {n:4d}  {rel}")
            for s in bare:
                print(f"   no citation in section: {s}")
        total_fail += len(r["fail"])
    print("OK" if total_fail == 0 else f"FAILED ({total_fail})")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
