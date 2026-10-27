"""excal.py - minimal Excalidraw scene builder, SVG preview renderer, PNG helper and layout lint.

Standard library only.  build_diagrams.py imports this module; the diagram modules (dg_*.py) draw with it.

Concepts
  Scene   one diagram = a list of Excalidraw elements plus a little metadata used by the layout lint.
  Shape   handle to a drawn element (position helpers, id) so arrows can bind to it.
  kinds   the one palette used on every diagram (see KINDS and the legend each scene draws).

Everything is deterministic: element ids, seeds and timestamps are derived from a counter, so regenerating
produces byte-identical files unless the drawing code changed.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import struct
import subprocess
import time
from pathlib import Path
from typing import Iterable, Sequence
from xml.sax.saxutils import escape as xml_escape

SOURCE = "https://excalidraw.com"
STAMP = 1735689600000
INK = "#1e1e1e"
MUTED = "#495057"
RED_TEXT = "#c92a2a"
WHITE = "#ffffff"
GAP = 4
LINE_H = 1.25
TOP = 64.5  # distance from a zone's top edge to its first child row (one-line title tab)

# kind -> colours.  zone = very light region tint, fill = box fill, stroke = outline, tab/tabtext = zone title tab
KINDS: dict[str, dict] = {
    "identity": dict(zone="#f3f0ff", fill="#e5dbff", stroke="#6741d9", tab="#6741d9", tabtext=WHITE, dashed=False, legend="Identity (Entra ID)"),
    "network": dict(zone="#e7f5ff", fill="#d0ebff", stroke="#1971c2", tab="#1971c2", tabtext=WHITE, dashed=False, legend="Network, API gateway (APIM)"),
    "compute": dict(zone="#ebfbee", fill="#d3f9d8", stroke="#2f9e44", tab="#2b8a3e", tabtext=WHITE, dashed=False, legend="Compute (agents, MCP servers)"),
    "data": dict(zone="#fff4e6", fill="#ffe8cc", stroke="#e8590c", tab="#d9480f", tabtext=WHITE, dashed=False, legend="Data stores"),
    "obs": dict(zone="#e3fafc", fill="#c5f6fa", stroke="#0b7285", tab="#0b7285", tabtext=WHITE, dashed=False, legend="Observability"),
    "deny": dict(zone="#fff5f5", fill="#ffe3e3", stroke="#e03131", tab="#c92a2a", tabtext=WHITE, dashed=False, legend="Deny, risk, kill switch"),
    "human": dict(zone="#f8f9fa", fill="#f1f3f5", stroke="#868e96", tab="#495057", tabtext=WHITE, dashed=True, legend="Human / optional (dashed)"),
    "policy": dict(zone="#fff9db", fill="#fff3bf", stroke="#f08c00", tab="#ffd43b", tabtext=INK, dashed=False, legend="Azure Policy, governance"),
    "actor": dict(zone=WHITE, fill=WHITE, stroke=INK, tab=INK, tabtext=WHITE, dashed=False, legend="People, client tools"),
}
ARROW_COLORS = {
    None: INK, "flow": INK, "deny": "#e03131", "human": "#868e96", "identity": "#6741d9", "network": "#1971c2",
    "compute": "#2f9e44", "data": "#e8590c", "obs": "#0b7285", "policy": "#f08c00",
}

_UP = [667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611]
_LO = [556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500]
_OTHER = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191, "(": 333, ")": 333, "*": 389, "+": 584,
    ",": 278, "-": 333, ".": 278, "/": 278, ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015,
    "[": 278, "\\": 278, "]": 278, "^": 469, "_": 556, "`": 333, "{": 334, "|": 260, "}": 334, "~": 584,
}
WIDTH: dict[str, int] = {}
for _i in range(26):
    WIDTH[chr(65 + _i)] = _UP[_i]
    WIDTH[chr(97 + _i)] = _LO[_i]
for _d in range(10):
    WIDTH[str(_d)] = 556
WIDTH.update(_OTHER)


class Overfull(ValueError):
    """Text does not fit the space it was given."""


def tw(text: str, size: float) -> float:
    """Width in px of one line of Helvetica/Arial text (Excalidraw font family 2)."""
    return sum(WIDTH.get(c, 556) for c in text) * size / 1000.0


def wrap(text: str, size: float, max_w: float) -> list[str]:
    """Greedy word wrap that respects explicit newlines; long tokens may break after / - _ ."""
    out: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            cand = word if not line else line + " " + word
            if tw(cand, size) <= max_w:
                line = cand
                continue
            if line:
                out.append(line)
                line = ""
            if tw(word, size) <= max_w:
                line = word
                continue
            cur = ""
            for part in re.findall(r"[^/\-_.]+[/\-_.]?|[/\-_.]", word):
                if tw(cur + part, size) <= max_w:
                    cur += part
                    continue
                if cur:
                    out.append(cur)
                if tw(part, size) > max_w:
                    raise Overfull(f"token {part!r} wider than {max_w:.0f}px at size {size}")
                cur = part
            line = cur
        out.append(line)
    return out


def r2(v: float) -> float:
    v = round(float(v), 2)
    return 0.0 if v == 0 else v


def th(lines: Sequence[str], size: float) -> float:
    return len(lines) * size * LINE_H


def block_w(lines: Sequence[str], size: float) -> float:
    return max((tw(x, size) for x in lines), default=0.0)


class Shape:
    """Handle to a drawn element."""

    def __init__(self, scene: "Scene", el: dict, role: str):
        self.scene, self.el, self.role = scene, el, role
        self.children: list[Shape] = []

    id = property(lambda s: s.el["id"])
    x = property(lambda s: s.el["x"])
    y = property(lambda s: s.el["y"])
    w = property(lambda s: s.el["width"])
    h = property(lambda s: s.el["height"])
    left = property(lambda s: s.el["x"])
    top = property(lambda s: s.el["y"])
    right = property(lambda s: s.el["x"] + s.el["width"])
    bottom = property(lambda s: s.el["y"] + s.el["height"])
    cx = property(lambda s: s.el["x"] + s.el["width"] / 2)
    cy = property(lambda s: s.el["y"] + s.el["height"] / 2)
    # first free spot inside a zone (below its title tab)
    inner_x = property(lambda s: s.el["x"] + 20)
    inner_y = property(lambda s: getattr(s, "content_y", s.el["y"] + 20))
    inner_w = property(lambda s: s.el["width"] - 40)


class Scene:
    def __init__(self, key: str, width: int, height: int, title: str, subtitle: str):
        self.key, self.num = key, int(key[:2])
        self.width, self.height = width, height
        self._items: list[tuple[float, int, dict]] = []
        self.meta: dict[str, dict] = {}
        self._n = 0
        self._g = 0
        self.errors: list[str] = []
        self.text(60, 34, title, size=36, color=INK, anchor="tl", role="title")
        self.text(60, 86, subtitle, size=20, color=MUTED, anchor="tl", role="title")
        self._foot = self.text(60, height - 34, f"Agents Behind the Wall - diagram {self.num:02d} of 13 - generated by docs/diagrams/build_diagrams.py",
                               size=16, color="#868e96", anchor="tl", role="title")
        self.legend()

    @staticmethod
    def top_for(title: str, w: float, size: float = 18) -> float:
        """Offset from a zone's top edge to its first content row, for a zone of width w with this title."""
        return 12 + th(wrap(title, size, w - 32 - 28), size) + 14 + 16

    @staticmethod
    def fill_to(shapes: Iterable[Shape], bottom: float) -> None:
        """Stretch boxes so their bottom edge is at `bottom`, keeping bound text centred."""
        for s in shapes:
            s.el["height"] = r2(bottom - s.y)
            for c in s.children:
                if c.el["type"] == "text" and c.el.get("containerId") == s.id:
                    c.el["y"] = r2(s.y + (s.h - c.h) / 2)

    def fit(self, bottom: float) -> None:
        """Set the canvas height from the lowest drawn y and move the footer line under it."""
        self.height = int(math.ceil((bottom + 70) / 10.0) * 10)
        self._foot.el["y"] = r2(self.height - 34)

    # ------------------------------------------------------------------ element plumbing
    def _id(self) -> str:
        self._n += 1
        return f"d{self.num:02d}_{self._n:04d}"

    def _el(self, typ: str, x: float, y: float, w: float, h: float, stroke: str, fill: str, *, sw: float = 2,
            style: str = "solid", roundness: dict | None = None, layer: float = 1.0, role: str = "box",
            group: str | None = None) -> Shape:
        eid = self._id()
        n = self._n
        el = {
            "id": eid, "type": typ, "x": r2(x), "y": r2(y), "width": r2(w), "height": r2(h), "angle": 0,
            "strokeColor": stroke, "backgroundColor": fill, "fillStyle": "solid", "strokeWidth": sw,
            "strokeStyle": style, "roughness": 0, "opacity": 100, "groupIds": [group] if group else [],
            "frameId": None, "roundness": roundness, "seed": (self.num * 100003 + n * 7919) % 2147483647,
            "version": 1, "versionNonce": (n * 104729 + self.num * 13) % 2147483647, "isDeleted": False,
            "boundElements": [], "updated": STAMP, "link": None, "locked": False,
        }
        self._items.append((layer, n, el))
        self.meta[eid] = {"role": role, "layer": layer}
        return Shape(self, el, role)

    def _group(self) -> str:
        self._g += 1
        return f"grp{self.num:02d}_{self._g:03d}"

    def _bind_text(self, box: Shape, lines: list[str], size: float, color: str, align: str, valign: str,
                   layer: float, role: str = "boundtext", inset: float = 5.0) -> Shape:
        tw_, th_ = block_w(lines, size), th(lines, size)
        if align == "center":
            tx = box.x + (box.w - tw_) / 2
        elif align == "left":
            tx = box.x + inset
        else:
            tx = box.right - tw_ - inset
        if valign == "middle":
            ty = box.y + (box.h - th_) / 2
        elif valign == "top":
            ty = box.y + inset
        else:
            ty = box.bottom - th_ - inset
        t = self._text_el(tx, ty, lines, size, color, align, valign, layer, role, container=box.id, group=None)
        box.el["boundElements"].append({"id": t.id, "type": "text"})
        box.children.append(t)
        return t

    def _text_el(self, x: float, y: float, lines: list[str], size: float, color: str, align: str, valign: str,
                 layer: float, role: str, container: str | None = None, group: str | None = None) -> Shape:
        text = "\n".join(lines)
        t = self._el("text", x, y, block_w(lines, size), th(lines, size), color, "transparent", layer=layer, role=role, group=group)
        t.el.update({"text": text, "fontSize": size, "fontFamily": 2, "textAlign": align, "verticalAlign": valign,
                     "containerId": container, "originalText": text, "autoResize": True, "lineHeight": LINE_H})
        t.el["strokeWidth"] = 1
        return t

    # ------------------------------------------------------------------ free text
    def text(self, x: float, y: float, text: str, *, size: float = 18, color: str = INK, align: str = "left",
             w: float | None = None, anchor: str = "tl", role: str = "text", layer: float = 4.0,
             group: str | None = None) -> Shape:
        lines = wrap(text, size, w) if w else text.split("\n")
        bw, bh = block_w(lines, size), th(lines, size)
        ax, ay = anchor[1], anchor[0]  # anchor = vertical letter + horizontal letter, e.g. "tl", "cc"
        px = x - (bw / 2 if ax == "c" else bw if ax == "r" else 0)
        py = y - (bh / 2 if ay == "c" else bh if ay == "b" else 0)
        return self._text_el(px, py, lines, size, color, align, "top", layer, role, group=group)

    # ------------------------------------------------------------------ boxes
    def box(self, x: float, y: float, w: float, text: str, *, h: float | None = None, kind: str = "compute",
            size: float = 18, align: str = "center", valign: str = "middle", dashed: bool | None = None,
            tone: str = "fill", sw: float = 2, color: str = INK, pad: float = 12, layer: float = 1.0,
            role: str = "box", fill: str | None = None, stroke: str | None = None, minh: float = 0,
            inset: float = 5.0) -> Shape:
        k = KINDS[kind]
        lines = wrap(text, size, w - 2 * pad) if text else []
        need = th(lines, size) + 2 * 10
        if h is None:
            h = max(minh, need)
        elif need > h + 0.01:
            raise Overfull(f"[{self.key}] box {text[:40]!r} needs {need:.0f}px height, has {h:.0f}")
        if dashed is None:
            dashed = k["dashed"]
        b = self._el("rectangle", x, y, w, h, stroke or k["stroke"], fill or k[tone], sw=sw,
                     style="dashed" if dashed else "solid", roundness={"type": 3}, layer=layer, role=role)
        if lines:
            self._bind_text(b, lines, size, color, align, valign, layer, inset=inset)
        return b

    def zone(self, x: float, y: float, w: float, h: float, title: str, *, kind: str = "compute", size: float = 18,
             dashed: bool | None = None, sw: float = 2) -> Shape:
        k = KINDS[kind]
        if dashed is None:
            dashed = k["dashed"]
        z = self._el("rectangle", x, y, w, h, k["stroke"], k["zone"], sw=sw, style="dashed" if dashed else "solid",
                     roundness={"type": 3}, layer=0.0, role="zone")
        tab_lines = wrap(title, size, w - 32 - 28)
        tab_h = th(tab_lines, size) + 14
        tab_w = block_w(tab_lines, size) + 28
        tab = self._el("rectangle", x + 16, y + 12, tab_w, tab_h, k["tab"], k["tab"], sw=1, roundness={"type": 3}, layer=0.5,
                       role="tab")
        self._bind_text(tab, tab_lines, size, k["tabtext"], "center", "middle", 0.5)
        z.content_y = y + 12 + tab_h + 16
        z.tab = tab
        return z

    def zone_around(self, shapes: Iterable[Shape], title: str, *, kind: str = "compute", pad: float = 20,
                    size: float = 18, min_w: float = 0) -> Shape:
        shapes = list(shapes)
        x0 = min(s.left for s in shapes) - pad
        y1 = min(s.top for s in shapes)
        x1 = max(s.right for s in shapes) + pad
        y2 = max(s.bottom for s in shapes) + pad
        tab_lines = wrap(title, size, max(x1 - x0, min_w) - 60)
        top = y1 - (12 + th(tab_lines, size) + 14 + 16)
        return self.zone(x0, top, max(x1 - x0, min_w), y2 - top, title, kind=kind, size=size)

    def panel(self, x: float, y: float, w: float, title: str, body: str = "", *, kind: str = "compute",
              h: float | None = None, size: float = 16, title_size: float = 20, pad: float = 14, dashed: bool | None = None,
              tone: str = "fill", align: str = "left", body_color: str = INK, role: str = "panel",
              fill: str | None = None, stroke: str | None = None, sw: float = 2) -> Shape:
        """Composite card: rectangle + title text + body text, grouped so it moves as one."""
        k = KINDS[kind]
        tl = wrap(title, title_size, w - 2 * pad) if title else []
        bl = wrap(body, size, w - 2 * pad) if body else []
        gap = 8 if (tl and bl) else 0
        need = pad + th(tl, title_size) + gap + th(bl, size) + pad
        if h is None:
            h = need
        elif need > h + 0.01:
            raise Overfull(f"[{self.key}] panel {title[:40]!r} needs {need:.0f}px height, has {h:.0f}")
        if dashed is None:
            dashed = k["dashed"]
        g = self._group()
        rect = self._el("rectangle", x, y, w, h, stroke or k["stroke"], fill or k[tone], sw=sw,
                        style="dashed" if dashed else "solid", roundness={"type": 3}, layer=1.0, role=role, group=g)
        cy = y + pad
        for lines, sz, col in ((tl, title_size, INK), (bl, size, body_color)):
            if not lines:
                continue
            bw = block_w(lines, sz)
            tx = x + pad if align == "left" else x + (w - bw) / 2
            t = self._text_el(tx, cy, lines, sz, col, align, "top", 4.0, "text", group=g)
            rect.children.append(t)
            cy += th(lines, sz) + gap
        return rect

    # ------------------------------------------------------------------ markers, labels, lines
    def marker(self, n: int | str, cx: float, cy: float, *, r: float = 18, kind: str | None = None,
               fill: str | None = None, stroke: str | None = None, text_color: str = WHITE, sw: float = 1) -> Shape:
        col = fill or (INK if kind is None else KINDS[kind]["tab"])
        m = self._el("ellipse", cx - r, cy - r, 2 * r, 2 * r, stroke or col, col, sw=sw, layer=5.0, role="marker")
        self._bind_text(m, [str(n)], 18, text_color, "center", "middle", 5.0)
        return m

    def label(self, text: str, x: float, y: float, *, size: float = 16, color: str = INK, w: float | None = 280,
              anchor: str = "cc", align: str = "center", plate: str = WHITE, layer: float = 4.5,
              role: str = "label", stroke: str = "transparent") -> Shape:
        """Text on a small plate (white by default) so lines never run through it."""
        lines = wrap(text, size, w) if w else text.split("\n")
        pw, ph = block_w(lines, size) + 18, th(lines, size) + 10
        ax, ay = anchor[1], anchor[0]
        px = x - (pw / 2 if ax == "c" else pw if ax == "r" else 0)
        py = y - (ph / 2 if ay == "c" else ph if ay == "b" else 0)
        p = self._el("rectangle", px, py, pw, ph, stroke, plate, sw=1, roundness={"type": 3}, layer=layer, role=role)
        self._bind_text(p, lines, size, color, align, "middle", layer)
        return p

    def line(self, points: Sequence[tuple[float, float]], *, kind: str | None = None, dashed: bool = False, sw: float = 2,
             color: str | None = None, role: str = "line", layer: float = 2.0) -> Shape:
        x0, y0 = points[0]
        rel = [[r2(px - x0), r2(py - y0)] for px, py in points]
        xs, ys = [p[0] for p in rel], [p[1] for p in rel]
        ln = self._el("line", x0, y0, max(xs) - min(xs), max(ys) - min(ys), color or ARROW_COLORS[kind], "transparent", sw=sw,
                      style="dashed" if dashed else "solid", layer=layer, role=role)
        ln.el.update({"points": rel, "lastCommittedPoint": None, "startBinding": None, "endBinding": None,
                      "startArrowhead": None, "endArrowhead": None})
        return ln

    # ------------------------------------------------------------------ arrows
    def lifeline(self, cx: float, y0: float, y1: float, *, kind: str = "compute", w: float = 8) -> Shape:
        """Thin tall rectangle used as a sequence-diagram lifeline (arrows bind to it, labels may cross it)."""
        k = KINDS[kind]
        return self._el("rectangle", cx - w / 2, y0, w, y1 - y0, k["stroke"], k["fill"], sw=1, layer=0.8, role="lifeline")

    @staticmethod
    def _side(sh: Shape, spec: str) -> tuple[tuple[float, float], str]:
        side, _, pos = spec.partition("@")
        if side not in ("l", "r", "t", "b"):
            raise ValueError(f"bad anchor {spec!r}")
        if side in ("l", "r"):
            yv = float(pos) if pos else sh.cy
            if not (sh.top + 3 <= yv <= sh.bottom - 3):
                raise ValueError(f"[{sh.scene.key}] anchor {spec} is outside {sh.id} (y {sh.top:.0f}..{sh.bottom:.0f})")
            return ((sh.left if side == "l" else sh.right), yv), side
        xv = float(pos) if pos else sh.cx
        if not (sh.left + 3 <= xv <= sh.right - 3):
            raise ValueError(f"[{sh.scene.key}] anchor {spec} is outside {sh.id} (x {sh.left:.0f}..{sh.right:.0f})")
        return (xv, (sh.top if side == "t" else sh.bottom)), side

    @staticmethod
    def _auto(a: Shape, b: Shape) -> tuple[str, str]:
        dx, dy = b.cx - a.cx, b.cy - a.cy
        if abs(dx) >= abs(dy):
            return ("r", "l") if dx > 0 else ("l", "r")
        return ("b", "t") if dy > 0 else ("t", "b")

    @staticmethod
    def _focus(sh: Shape, p_from: tuple[float, float], p_to: tuple[float, float]) -> float:
        dx, dy = p_to[0] - p_from[0], p_to[1] - p_from[1]
        ln = math.hypot(dx, dy)
        if ln < 1e-6:
            return 0.0
        d = (dx * (sh.cy - p_from[1]) - dy * (sh.cx - p_from[0])) / ln
        nx, ny = -dy / ln, dx / ln
        support = abs(nx) * sh.w / 2 + abs(ny) * sh.h / 2
        return r2(max(-1.0, min(1.0, d / support))) if support else 0.0

    def arrow(self, a: Shape | None, b: Shape | None, *, a_at: str | tuple[float, float] | None = None,
              b_at: str | tuple[float, float] | None = None, via: Sequence[tuple[float, float]] = (),
              kind: str | None = None, dashed: bool = False, sw: float = 2, label: str | None = None,
              step: int | str | None = None, label_side: str | None = None, label_dx: float = 0, label_dy: float = 0,
              label_w: float | None = 260, label_size: float = 16, both: bool = False, label_seg: int | None = None,
              label_at: float = 0.5, label_color: str | None = None, label_inline: bool = False,
              marker_at: float | None = None) -> Shape:
        col = ARROW_COLORS[kind]
        sides: list[str | None] = [None, None]
        pts: list[tuple[float, float]] = []

        def end_point(sh: Shape | None, at, which: int) -> tuple[float, float]:
            if sh is None:
                if not isinstance(at, tuple):
                    raise ValueError("free arrow end needs an (x, y) tuple")
                return at
            if isinstance(at, tuple):
                return at
            if at is None:
                if a is not None and b is not None and not via:
                    at = self._auto(a, b)[which]
                else:
                    raise ValueError(f"[{self.key}] arrow end needs an anchor ('r', 'l@300', ...)")
            (px, py), side = self._side(sh, at)
            sides[which] = side
            nx, ny = {"r": (1, 0), "l": (-1, 0), "t": (0, -1), "b": (0, 1)}[side]
            return (px + nx * GAP, py + ny * GAP)

        p0 = end_point(a, a_at, 0)
        p1 = end_point(b, b_at, 1)
        pts = [p0, *via, p1]
        x0, y0 = pts[0]
        rel = [[r2(px - x0), r2(py - y0)] for px, py in pts]
        xs, ys = [p[0] for p in rel], [p[1] for p in rel]
        ar = self._el("arrow", x0, y0, max(xs) - min(xs), max(ys) - min(ys), col, "transparent", sw=sw,
                      style="dashed" if dashed else "solid", layer=3.0, role="arrow")
        ar.el.update({"points": rel, "lastCommittedPoint": None, "startArrowhead": "arrow" if both else None,
                      "endArrowhead": "arrow", "elbowed": False, "startBinding": None, "endBinding": None})
        ends = set()
        for which, sh in ((0, a), (1, b)):
            if sh is None:
                continue
            ends.add(sh.id)
            p_from, p_to = (pts[0], pts[1]) if which == 0 else (pts[-2], pts[-1])
            ar.el["startBinding" if which == 0 else "endBinding"] = {"elementId": sh.id, "focus": self._focus(sh, p_from, p_to), "gap": GAP}
            sh.el["boundElements"].append({"id": ar.id, "type": "arrow"})
        ar.ends = ends
        self.meta[ar.id].update({"ends": ends, "own": set(), "points": pts})
        own = self.meta[ar.id]["own"]

        # label / marker go on the longest (or chosen) segment
        segs = list(zip(pts[:-1], pts[1:]))
        if label is not None or step is not None:
            idx = label_seg if label_seg is not None else max(range(len(segs)), key=lambda i: math.dist(*segs[i]))
            (sx, sy), (ex, ey) = segs[idx]
            mx, my = sx + (ex - sx) * label_at, sy + (ey - sy) * label_at
            horizontal = abs(ex - sx) >= abs(ey - sy)
            if step is not None:
                kx, ky = (mx, my) if marker_at is None else (sx + (ex - sx) * marker_at, sy + (ey - sy) * marker_at)
                mk = self.marker(step, kx, ky)
                own.add(mk.id)
                self.meta[mk.id]["arrow"] = ar.id
            if label is not None:
                side = label_side or ("above" if horizontal else "right")
                off = 24 if (step is not None and marker_at is None) else 8
                if label_inline:
                    pl = self.label(label, mx + label_dx, my + label_dy, size=label_size, w=label_w, anchor="cc",
                                    color=label_color or (RED_TEXT if kind == "deny" else INK))
                elif side == "above":
                    pl = self.label(label, mx + label_dx, my - off + label_dy, size=label_size, w=label_w, anchor="bc",
                                    color=label_color or (RED_TEXT if kind == "deny" else INK))
                elif side == "below":
                    pl = self.label(label, mx + label_dx, my + off + label_dy, size=label_size, w=label_w, anchor="tc",
                                    color=label_color or (RED_TEXT if kind == "deny" else INK))
                elif side == "left":
                    pl = self.label(label, mx - off + label_dx, my + label_dy, size=label_size, w=label_w, anchor="cr",
                                    color=label_color or (RED_TEXT if kind == "deny" else INK))
                else:
                    pl = self.label(label, mx + off + 8 + label_dx, my + label_dy, size=label_size, w=label_w, anchor="cl",
                                    color=label_color or (RED_TEXT if kind == "deny" else INK), align="left")
                own.add(pl.id)
                self.meta[pl.id]["arrow"] = ar.id
        return ar

    # ------------------------------------------------------------------ standard furniture
    def callout(self, x: float, y: float, w: float, bullets: Sequence[str], *, title: str = "What to notice",
                size: float = 18) -> Shape:
        pad = 16
        wrapped: list[str] = []
        for bl in bullets:
            ls = wrap(bl, size, w - 2 * pad - tw("- ", size))
            wrapped.append("- " + ls[0])
            wrapped.extend("  " + s for s in ls[1:])
        body = "\n".join(wrapped)
        g = self._group()
        tl = [title]
        h = pad + th(tl, 20) + 8 + th(wrapped, size) + pad
        rect = self._el("rectangle", x, y, w, h, "#343a40", "#f8f9fa", sw=2, roundness={"type": 3}, layer=1.0, role="panel", group=g)
        t1 = self._text_el(x + pad, y + pad, tl, 20, INK, "left", "top", 4.0, "text", group=g)
        t2 = self._text_el(x + pad, y + pad + th(tl, 20) + 8, wrapped, size, INK, "left", "top", 4.0, "text", group=g)
        rect.children += [t1, t2]
        return rect

    def legend(self, x: float | None = None, y: float = 22, *, cols: int = 4, col_w: float = 290, extra: bool = True) -> Shape:
        items: list[tuple[str, str]] = [(k, KINDS[k]["legend"]) for k in KINDS]
        if extra:
            items += [("arrow:flow", "Allowed flow"), ("arrow:deny", "Denied exit / risk path"), ("arrow:human", "Manual step (dashed)")]
        rows = math.ceil(len(items) / cols)
        pad = 14
        w = cols * col_w + 2 * pad - 20
        if x is None:
            x = self.width - 60 - w
        h = pad + 28 + rows * 30 + pad - 8
        g = self._group()
        frame = self._el("rectangle", x, y, w, h, "#adb5bd", WHITE, sw=1, roundness={"type": 3}, layer=1.0, role="panel", group=g)
        frame.children.append(self._text_el(x + pad, y + 10, ["Legend"], 18, INK, "left", "top", 4.0, "text", group=g))
        for i, (key, text) in enumerate(items):
            c, r = divmod(i, rows)
            ix, iy = x + pad + c * col_w, y + 10 + 28 + r * 30
            if key.startswith("arrow:"):
                kind = key.split(":")[1]
                ar = self._el("arrow", ix, iy + 12, 36, 0, ARROW_COLORS[None if kind == "flow" else kind], "transparent", sw=2,
                              style="dashed" if kind == "human" else "solid", layer=4.0, role="legend", group=g)
                ar.el.update({"points": [[0, 0], [36, 0]], "lastCommittedPoint": None, "startArrowhead": None,
                              "endArrowhead": "arrow", "elbowed": False, "startBinding": None, "endBinding": None})
                self.meta[ar.id].update({"ends": set(), "own": set(), "points": [(ix, iy + 12), (ix + 36, iy + 12)]})
                frame.children.append(ar)
            else:
                k = KINDS[key]
                sw_ = self._el("rectangle", ix, iy + 1, 36, 22, k["stroke"], k["fill"], sw=2, style="dashed" if k["dashed"] else "solid",
                               roundness={"type": 3}, layer=4.0, role="legend", group=g)
                frame.children.append(sw_)
            frame.children.append(self._text_el(ix + 46, iy + 1, [text], 16, INK, "left", "top", 4.0, "text", group=g))
        return frame

    def flow_key(self, x: float, y: float, w: float, steps: Sequence[str], *, title: str = "Numbered flow", size: float = 16,
                 cols: int = 1) -> Shape:
        pad, gutter = 16, 28
        colw = (w - 2 * pad - gutter * (cols - 1)) / cols
        entries: list[list[str]] = []
        for i, s in enumerate(steps, 1):
            prefix = f"{i}. "
            ind = " " * max(1, round(tw(prefix, size) / tw(" ", size)))
            ls = wrap(s, size, colw - tw(prefix, size))
            entries.append([prefix + ls[0]] + [ind + t for t in ls[1:]])
        total = sum(len(e) for e in entries)
        groups: list[list[str]] = [[] for _ in range(cols)]
        seen, gi = 0, 0
        for e in entries:
            if gi < cols - 1 and seen >= total * (gi + 1) / cols - len(e) / 2:
                gi += 1
            groups[gi].extend(e)
            seen += len(e)
        g = self._group()
        h = pad + 25 + 8 + th(max(groups, key=len), size) + pad
        rect = self._el("rectangle", x, y, w, h, "#343a40", "#f8f9fa", sw=2, roundness={"type": 3}, layer=1.0, role="panel", group=g)
        rect.children.append(self._text_el(x + pad, y + pad, [title], 20, INK, "left", "top", 4.0, "text", group=g))
        for ci, lines in enumerate(groups):
            if lines:
                rect.children.append(self._text_el(x + pad + ci * (colw + gutter), y + pad + 25 + 8, lines, size, INK, "left", "top",
                                                   4.0, "text", group=g))
        return rect

    def footer(self, y: float, bullets: Sequence[str], *, flow: Sequence[str] | None = None, callout_w: float = 900,
               flow_w: float | None = None, flow_title: str = "Numbered flow", flow_cols: int = 2) -> float:
        """What-to-notice callout (left) plus an optional numbered-flow key; returns the bottom y."""
        c = self.callout(60, y, callout_w, bullets)
        bottom = c.bottom
        if flow:
            fw = flow_w if flow_w is not None else self.width - 60 - (60 + callout_w + 30)
            f = self.flow_key(60 + callout_w + 30, y, fw, flow, title=flow_title, cols=flow_cols)
            bottom = max(bottom, f.bottom)
            self.fill_to([c, f], bottom)
        return bottom

    # ------------------------------------------------------------------ layout helpers
    @staticmethod
    def _spec(it, kind: str) -> tuple[str, str, dict]:
        if isinstance(it, str):
            return it, kind, {}
        return it[0], it[1], (dict(it[2]) if len(it) > 2 else {})

    def row(self, x: float, y: float, items: Sequence, *, w: float | None = None, widths: Sequence[float] | None = None,
            gap: float = 12, size: float = 18, kind: str = "compute", h: float | None = None, minh: float = 0,
            pad: float = 12) -> list[Shape]:
        """Equal-height row of boxes.  items: str | (str, kind) | (str, kind, {box kwargs})."""
        n = len(items)
        if widths is None:
            widths = [(w - gap * (n - 1)) / n] * n
        specs = [self._spec(it, kind) for it in items]
        need = max([minh] + [th(wrap(t, o.get("size", size), wd - 2 * o.get("pad", pad)), o.get("size", size)) + 20
                             for (t, k, o), wd in zip(specs, widths)])
        hh = h if h is not None else need
        out: list[Shape] = []
        cx = x
        for (t, k, o), wd in zip(specs, widths):
            kw = dict(kind=k, size=size, h=hh, pad=pad)
            kw.update(o)
            out.append(self.box(cx, y, wd, t, **kw))
            cx += wd + gap
        return out

    def stack(self, x: float, y: float, w: float, items: Sequence, *, gap: float = 10, size: float = 18, kind: str = "compute",
              pad: float = 12, minh: float = 0, h: float | None = None) -> list[Shape]:
        """Vertical stack of boxes (each as tall as its text, or all h)."""
        out: list[Shape] = []
        cy = y
        for it in items:
            t, k, o = self._spec(it, kind)
            kw = dict(kind=k, size=size, pad=pad, minh=minh)
            if h is not None:
                kw["h"] = h
            kw.update(o)
            sh = self.box(x, cy, w, t, **kw)
            out.append(sh)
            cy += sh.h + gap
        return out

    def table(self, x: float, y: float, cols: Sequence[tuple[str, float]], rows: Sequence[Sequence], *, size: float = 16,
              head_kind: str = "identity", pad: float = 10, min_row: float = 36, head_h: float = 40) -> dict:
        """Header cells are coloured boxes; body rows are tinted bands with left-aligned free text.
        A cell may be a plain string or (string, kind) for a coloured, centred cell."""
        cx = x
        total_w = sum(w for _, w in cols)
        hk = KINDS[head_kind]
        heads = []
        for title, w in cols:
            heads.append(self.box(cx, y, w, title, h=head_h, kind=head_kind, size=size, sw=1, role="cell", fill=hk["tab"],
                                  stroke=hk["tab"], color=hk["tabtext"]))
            cx += w
        cy = y + head_h
        row_shapes = []
        for ri, row in enumerate(rows):
            cells = []
            hmax = min_row
            for (title, w), cell in zip(cols, row):
                txt = cell[0] if isinstance(cell, tuple) else cell
                lines = wrap(txt, size, (w - 28) if isinstance(cell, tuple) else (w - 2 * pad))
                hmax = max(hmax, th(lines, size) + (30 if isinstance(cell, tuple) else 18))
                cells.append(lines)
            band = self._el("rectangle", x, cy, total_w, hmax, "#dee2e6", "#f8f9fa" if ri % 2 == 0 else WHITE, sw=1, layer=0.2, role="rowbg")
            cx = x
            for (title, w), cell, lines in zip(cols, row, cells):
                if isinstance(cell, tuple):
                    self.box(cx + 6, cy + 5, w - 12, cell[0], h=hmax - 10, kind=cell[1], size=size, sw=1, role="cell", pad=8)
                else:
                    self._text_el(cx + pad, cy + (hmax - th(lines, size)) / 2, lines, size, INK, "left", "top", 4.0, "text")
                cx += w
            row_shapes.append(band)
            cy += hmax
        return {"bottom": cy, "right": x + total_w, "rows": row_shapes, "heads": heads}

    # ------------------------------------------------------------------ output
    def document(self) -> dict:
        els = [e for _, _, e in sorted(self._items, key=lambda t: (t[0], t[1]))]
        return {"type": "excalidraw", "version": 2, "source": SOURCE, "elements": els,
                "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"}, "files": {}}

    def lint(self) -> list[str]:
        return lint_scene(self)


# ---------------------------------------------------------------------- lint
def _bbox(el: dict) -> tuple[float, float, float, float]:
    return el["x"], el["y"], el["x"] + el["width"], el["y"] + el["height"]


def _inter(a, b, tol: float = 0.5) -> bool:
    return a[0] < b[2] - tol and b[0] < a[2] - tol and a[1] < b[3] - tol and b[1] < a[3] - tol


def _inside(inner, outer, tol: float = 1.0) -> bool:
    return inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol


def _seg_rect(p, q, box, m: float = 0.0) -> bool:
    x0, y0 = p
    dx, dy = q[0] - x0, q[1] - y0
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x0 - (box[0] - m)), (dx, (box[2] + m) - x0), (-dy, y0 - (box[1] - m)), (dy, (box[3] + m) - y0)):
        if abs(pp) < 1e-9:
            if qq < 0:
                return False
        else:
            t = qq / pp
            if pp < 0:
                if t > t1:
                    return False
                t0 = max(t0, t)
            else:
                if t < t0:
                    return False
                t1 = min(t1, t)
    return True


def _seg_seg(p1, p2, p3, p4) -> bool:
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2, d3, d4 = ccw(p3, p4, p1), ccw(p3, p4, p2), ccw(p1, p2, p3), ccw(p1, p2, p4)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


SOLID = {"box", "panel", "label", "tab", "cell", "bar", "chip"}


def lint_scene(sc: Scene) -> list[str]:
    """Layout problems a human would see: text/shape collisions, partial overlaps, arrows through boxes, off-canvas items."""
    doc = sc.document()
    els = doc["elements"]
    by_id = {e["id"]: e for e in els}
    meta = sc.meta
    out: list[str] = []
    W, H = sc.width, sc.height

    def nm(e):
        t = e.get("text") if e["type"] == "text" else None
        return f"{e['id']}({(t or meta[e['id']]['role'])[:30]!r})".replace("\n", " ")

    texts = [e for e in els if e["type"] == "text"]
    rects = [e for e in els if e["type"] in ("rectangle", "ellipse")]
    for e in els:
        if e["type"] in ("arrow", "line"):
            xs = [e["x"] + p[0] for p in e["points"]]
            ys = [e["y"] + p[1] for p in e["points"]]
            lo, hi = (min(xs), min(ys)), (max(xs), max(ys))
        else:
            b = _bbox(e)
            lo, hi = (b[0], b[1]), (b[2], b[3])
        if lo[0] < 4 or lo[1] < 4 or hi[0] > W - 4 or hi[1] > H - 4:
            out.append(f"off-canvas: {nm(e)} spans {lo[0]:.0f},{lo[1]:.0f}..{hi[0]:.0f},{hi[1]:.0f} on a {W}x{H} canvas")

    # bound text must sit inside its container
    for t in texts:
        cid = t.get("containerId")
        if cid:
            box = by_id[cid]
            if not _inside(_bbox(t), _bbox(box), 0.5):
                out.append(f"bound text outside its container: {nm(t)} in {cid}")

    # text vs text
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            if _inter(_bbox(a), _bbox(b), 1.0):
                out.append(f"text overlaps text: {nm(a)} <-> {nm(b)}")

    # text vs rect: must be fully inside (container, zone, panel) or fully outside
    for t in texts:
        tb = _bbox(t)
        for r in rects:
            if r["id"] == t.get("containerId") or r["type"] == "ellipse" or meta[r["id"]]["role"] == "lifeline":
                continue
            rb = _bbox(r)
            if _inter(tb, rb, 1.0) and not _inside(tb, rb, 1.0):
                out.append(f"text crosses a shape border: {nm(t)} <-> {nm(r)}")

    # rect vs rect: nested or disjoint only
    box_rects = [r for r in rects if meta[r["id"]]["role"] not in ("marker", "legend", "rowbg", "lifeline") and r["type"] == "rectangle"]
    for i, a in enumerate(box_rects):
        ab = _bbox(a)
        for b in box_rects[i + 1:]:
            bb = _bbox(b)
            if _inter(ab, bb, 1.0) and not _inside(ab, bb) and not _inside(bb, ab):
                out.append(f"shapes partly overlap: {nm(a)} <-> {nm(b)}")

    # markers must not hide text
    for m in [r for r in rects if meta[r["id"]]["role"] == "marker"]:
        mb = _bbox(m)
        for t in texts:
            if t.get("containerId") == m["id"]:
                continue
            if _inter(mb, _bbox(t), 1.0):
                out.append(f"marker covers text: {nm(m)} <-> {nm(t)}")

    # arrows: no length-less arrows, no crossing text or solid boxes (other than their own ends/labels)
    arrows = [e for e in els if e["type"] == "arrow" and meta[e["id"]]["role"] != "legend"]
    for ar in arrows:
        info = meta[ar["id"]]
        pts = info["points"]
        total = sum(math.dist(p, q) for p, q in zip(pts[:-1], pts[1:]))
        if total < 28:
            out.append(f"arrow too short to read: {nm(ar)} ({total:.0f}px)")
        own = info["own"] | info["ends"]
        for p, q in zip(pts[:-1], pts[1:]):
            for t in texts:
                cid = t.get("containerId")
                if cid in own or t["id"] in own or (cid and cid in info["own"]):
                    continue
                if _seg_rect(p, q, _bbox(t), 1.0):
                    out.append(f"arrow crosses text: {ar['id']} -> {nm(t)}")
            for r in rects:
                rid = r["id"]
                if rid in own or meta[rid]["role"] not in SOLID:
                    continue
                if _seg_rect(p, q, _bbox(r), 0.0):
                    out.append(f"arrow passes through a box: {ar['id']} -> {nm(r)}")
    # arrow crossings are reported by the builder as information only
    sc.crossings = 0
    for i, a in enumerate(arrows):
        pa = meta[a["id"]]["points"]
        for b in arrows[i + 1:]:
            pb = meta[b["id"]]["points"]
            if any(_seg_seg(p, q, r, s) for p, q in zip(pa[:-1], pa[1:]) for r, s in zip(pb[:-1], pb[1:])):
                sc.crossings += 1
    return out


# ---------------------------------------------------------------------- SVG preview
def _dash(el: dict) -> str:
    sw = el["strokeWidth"]
    if el["strokeStyle"] == "dashed":
        return ' stroke-dasharray="10 7"'
    if el["strokeStyle"] == "dotted":
        return f' stroke-dasharray="1 {sw * 3 + 2:g}" stroke-linecap="round"'
    return ""


def _fill(c: str) -> str:
    return "none" if c in ("transparent", "", None) else c


def _head(out: list[str], p_from, p_to, color: str, sw: float) -> None:
    ang = math.atan2(p_to[1] - p_from[1], p_to[0] - p_from[0])
    pts = []
    for s in (1, -1):
        a = ang + math.pi + s * math.radians(27)
        pts.append((p_to[0] + 15 * math.cos(a), p_to[1] + 15 * math.sin(a)))
    out.append(f'<path d="M {pts[0][0]:.2f} {pts[0][1]:.2f} L {p_to[0]:.2f} {p_to[1]:.2f} L {pts[1][0]:.2f} {pts[1][1]:.2f}" '
               f'fill="none" stroke="{color}" stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round"/>')


def to_svg(doc: dict, width: int, height: int, view: tuple[float, float, float, float] | None = None, scale: float = 1.0) -> str:
    vx, vy, vw, vh = view or (0, 0, width, height)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{vw * scale:g}" height="{vh * scale:g}" viewBox="{vx:g} {vy:g} {vw:g} {vh:g}" '
           f'font-family="Helvetica, Arial, sans-serif">',
           f'<rect x="{vx:g}" y="{vy:g}" width="{vw:g}" height="{vh:g}" fill="#ffffff"/>']
    for el in doc["elements"]:
        t = el["type"]
        stroke = _fill(el["strokeColor"])
        if t == "rectangle":
            rad = ""
            if el.get("roundness"):
                m = min(el["width"], el["height"])
                rr = m * 0.25 if m <= 128 else 32
                rad = f' rx="{rr:g}" ry="{rr:g}"'
            out.append(f'<rect x="{el["x"]:g}" y="{el["y"]:g}" width="{el["width"]:g}" height="{el["height"]:g}"{rad} '
                       f'fill="{_fill(el["backgroundColor"])}" stroke="{stroke}" stroke-width="{el["strokeWidth"]}"{_dash(el)}/>')
        elif t == "ellipse":
            out.append(f'<ellipse cx="{el["x"] + el["width"] / 2:g}" cy="{el["y"] + el["height"] / 2:g}" rx="{el["width"] / 2:g}" '
                       f'ry="{el["height"] / 2:g}" fill="{_fill(el["backgroundColor"])}" stroke="{stroke}" stroke-width="{el["strokeWidth"]}"{_dash(el)}/>')
        elif t in ("arrow", "line"):
            pts = [(el["x"] + p[0], el["y"] + p[1]) for p in el["points"]]
            d = "M " + " L ".join(f"{px:.2f} {py:.2f}" for px, py in pts)
            out.append(f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{el["strokeWidth"]}" stroke-linejoin="round" '
                       f'stroke-linecap="round"{_dash(el)}/>')
            if t == "arrow":
                if el.get("endArrowhead"):
                    _head(out, pts[-2], pts[-1], stroke, el["strokeWidth"])
                if el.get("startArrowhead"):
                    _head(out, pts[1], pts[0], stroke, el["strokeWidth"])
        elif t == "text":
            size, al = el["fontSize"], el["textAlign"]
            anchor = {"left": "start", "center": "middle", "right": "end"}[al]
            tx = el["x"] if al == "left" else el["x"] + el["width"] / 2 if al == "center" else el["x"] + el["width"]
            for i, line in enumerate(el["text"].split("\n")):
                if not line.strip():
                    continue
                yy = el["y"] + (i + 0.5) * size * LINE_H
                out.append(f'<text x="{tx:.2f}" y="{yy:.2f}" font-size="{size:g}" fill="{stroke}" text-anchor="{anchor}" '
                           f'dominant-baseline="central" xml:space="preserve">{xml_escape(line)}</text>')
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------------- PNG via Microsoft Edge (headless, local only)
def find_edge() -> Path | None:
    for cand in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(cand).exists():
            return Path(cand)
    found = shutil.which("msedge")
    return Path(found) if found else None


def png_size(path: Path) -> tuple[int, int] | None:
    try:
        head = path.read_bytes()[:24]
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", head[16:24])
    except OSError:
        return None


def svg_to_png(edge: Path, svg: Path, png: Path, w: int, h: int, profile: Path, timeout: int = 120) -> str | None:
    """Return None on success, else a message.

    Edge headless sometimes keeps running after it has written the screenshot, so the file is polled and the
    process tree (by PID) is ended once the PNG is complete and stable.
    """
    png = png.resolve()
    png.parent.mkdir(parents=True, exist_ok=True)
    if png.exists():
        png.unlink()
    cmd = [str(edge), "--headless", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
           f"--user-data-dir={profile.resolve()}", f"--screenshot={png}", f"--window-size={w},{h}",
           "file:///" + svg.resolve().as_posix()]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return f"edge failed: {exc}"
    deadline = time.time() + timeout
    last_size, stable_since = -1, 0.0
    try:
        while time.time() < deadline:
            time.sleep(0.5)
            size = png.stat().st_size if png.exists() else -1
            if size > 1000 and size == last_size:
                if stable_since and time.time() - stable_since >= 1.5:
                    break
                stable_since = stable_since or time.time()
            else:
                stable_since = 0.0
            last_size = size
            if proc.poll() is not None and size > 1000:
                break
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    if not png.exists() or png.stat().st_size < 1000:
        return "edge produced no screenshot"
    return None


def dump(doc: dict) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
