"""build_diagrams.py - generate the "Agents Behind the Wall" Excalidraw diagram set (standard library only).

    python docs\\diagrams\\build_diagrams.py                 build all 13 diagrams, self-check, write previews
    python docs\\diagrams\\build_diagrams.py --only 01,05    build a subset
    python docs\\diagrams\\build_diagrams.py --no-png        skip the Microsoft Edge PNG step
    python docs\\diagrams\\build_diagrams.py --crop 03 0 0 1200 900 1   write png\\_crops\\_crop_03.png (zoomed look at one region)
    python docs\\diagrams\\build_diagrams.py --clean         remove crops and the temporary Edge profile

For every diagram it writes  NN-name.excalidraw  and  NN-name.svg  next to this script and  png\\NN-name.png  (rendered by a
local headless Microsoft Edge; nothing is uploaded anywhere).  Self-check: validate_excalidraw.py rules (valid JSON, ids,
bindings, ASCII, no GUIDs ...) plus a layout lint (text fits, no overlaps, arrows do not cross text or boxes).
The exit code is non-zero when any check fails.
"""
from __future__ import annotations

import argparse
import importlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import excal  # noqa: E402
import validate_excalidraw  # noqa: E402

NAMES = [
    "01-system-architecture", "02-network-topology", "03-request-data-flow", "04-authentication-flow",
    "05-authorization-layers", "06-identity-and-entitlements", "07-token-anatomy", "08-scenarios-acts-1-7",
    "09-observability-correlation", "10-deployment-pipeline", "11-agent-front-door", "12-demo-console",
    "13-trust-boundaries-and-failure-modes",
]
PNG_DIR = HERE / "png"
CROPS = PNG_DIR / "_crops"
PROFILE = HERE / ".edge-profile"


def build_scene(key: str) -> excal.Scene:
    """Each diagram lives in its own module dgNN.py, which exposes build() -> excal.Scene."""
    try:
        mod = importlib.import_module(f"dg{key[:2]}")
    except ModuleNotFoundError as exc:
        if exc.name == f"dg{key[:2]}":
            raise KeyError(f"no builder module dg{key[:2]}.py for {key}") from exc
        raise
    importlib.reload(mod)
    sc = mod.build()
    if sc.key != key:
        raise ValueError(f"dg{key[:2]}.build() produced scene {sc.key!r}, expected {key!r}")
    return sc


def pick(only: str | None) -> list[str]:
    if not only:
        return list(NAMES)
    wanted = [x.strip() for x in only.split(",") if x.strip()]
    out = [n for n in NAMES if any(n.startswith(w) or n == w for w in wanted)]
    if not out:
        raise SystemExit(f"--only {only!r} matches nothing")
    return out


def clean() -> None:
    shutil.rmtree(CROPS, ignore_errors=True)
    shutil.rmtree(PROFILE, ignore_errors=True)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated diagram numbers or names, e.g. 01,05")
    ap.add_argument("--no-png", action="store_true", help="skip the Edge PNG previews")
    ap.add_argument("--crop", nargs="+", metavar="V", help="NN x y w h [scale]  render one region of a diagram to png\\_crops")
    ap.add_argument("--clean", action="store_true", help="remove png\\_crops and the temporary Edge profile, then exit")
    args = ap.parse_args(argv)

    if args.clean:
        clean()
        print("cleaned crops and temporary Edge profile")
        return 0

    edge = excal.find_edge()
    if args.crop:
        key = pick(args.crop[0])[0]
        x, y, w, h = (float(v) for v in args.crop[1:5])
        scale = float(args.crop[5]) if len(args.crop) > 5 else 1.0
        sc = build_scene(key)
        svg = excal.to_svg(sc.document(), sc.width, sc.height, view=(x, y, w, h), scale=scale)
        CROPS.mkdir(parents=True, exist_ok=True)
        svg_path = CROPS / f"_crop_{key[:2]}.svg"
        svg_path.write_text(svg, encoding="utf-8")
        if edge is None:
            print("Microsoft Edge not found")
            return 1
        err = excal.svg_to_png(edge, svg_path, CROPS / f"_crop_{key[:2]}.png", int(w * scale), int(h * scale), PROFILE)
        shutil.rmtree(PROFILE, ignore_errors=True)
        print(err or f"wrote {CROPS / ('_crop_' + key[:2] + '.png')}")
        return 1 if err else 0

    names = pick(args.only)
    problems: list[str] = []
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    if not args.no_png and edge is None:
        problems.append("Microsoft Edge (msedge.exe) not found under Program Files; use --no-png to skip previews")

    for key in names:
        try:
            sc = build_scene(key)
        except excal.Overfull as exc:
            problems.append(f"{key}: {exc}")
            print(f"FAIL {key}: {exc}")
            continue
        except (KeyError, ValueError) as exc:
            problems.append(f"{key}: {exc}")
            print(f"FAIL {key}: {exc}")
            continue
        doc = sc.document()
        raw = excal.dump(doc)
        path = HERE / f"{key}.excalidraw"
        path.write_text(raw, encoding="utf-8", newline="\n")
        found = sc.lint() + validate_excalidraw.validate_text(raw, path.name)
        (HERE / f"{key}.svg").write_text(excal.to_svg(doc, sc.width, sc.height), encoding="utf-8", newline="\n")
        png_note = "skipped"
        if not args.no_png and edge is not None:
            png = PNG_DIR / f"{key}.png"
            err = excal.svg_to_png(edge, HERE / f"{key}.svg", png, sc.width, sc.height, PROFILE)
            if err:
                found.append(f"{key}: {err}")
                png_note = "FAILED"
            else:
                size = excal.png_size(png)
                png_note = f"{size[0]}x{size[1]}" if size else "unreadable"
                if size is None or size[0] < sc.width or size[1] < sc.height:
                    found.append(f"{key}: PNG is {png_note}, expected at least {sc.width}x{sc.height}")
        status = "ok  " if not found else "FAIL"
        print(f"{status} {key:40s} elements={len(doc['elements']):4d} canvas={sc.width}x{sc.height} png={png_note} "
              f"arrow-crossings={getattr(sc, 'crossings', 0)}")
        for line in found[:40]:
            print("      ", line)
        if len(found) > 40:
            print(f"       ... and {len(found) - 40} more")
        problems += [f"{key}: {p}" for p in found]

    if not args.only:
        missing = [n for n in NAMES if not (HERE / f"{n}.excalidraw").exists()]
        extra = [p.name for p in HERE.glob("*.excalidraw") if p.stem not in NAMES]
        if missing or extra:
            problems.append(f"file set mismatch: missing={missing} unexpected={extra}")
        # second, independent pass over what is on disk
        for f in sorted(HERE.glob("*.excalidraw")):
            problems += validate_excalidraw.validate_file(f)

    shutil.rmtree(PROFILE, ignore_errors=True)
    if problems:
        print(f"\nSELF-CHECK FAILED: {len(problems)} problem(s)")
        return 1
    print(f"\nall checks passed for {len(names)} diagram(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
