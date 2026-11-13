"""Read vector paths (dielines) and artwork from PDF/AI/SVG files, Illustrator clipboard
data (PDF or AICB) and Photoshop paths. Qt-free.

Coordinates are PDF points with y pointing down (PyMuPDF convention)."""
from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field

import pymupdf

BEZIER_STEPS = 12
# MuPDF is not thread-safe: every use of pymupdf goes through this lock
PDF_LOCK = threading.RLock()


@dataclass
class Stroke:
    pts: list            # [(x, y), ...]
    closed: bool = False

    def length(self) -> float:
        p = self.pts + ([self.pts[0]] if self.closed else [])
        return sum(math.dist(a, b) for a, b in zip(p, p[1:]))


@dataclass
class LineGroup:
    """All strokes that share layer, colour, width and dash style."""
    key: str
    layer: str
    color: tuple          # (r, g, b) 0..1
    width: float
    dashed: bool
    strokes: list = field(default_factory=list)
    selected: bool = False
    role: str = "ignore"          # auto | cut | crease | perf | ignore (see roles.py)

    @property
    def length(self) -> float:
        return sum(s.length() for s in self.strokes)

    def bbox(self):
        xs = [p[0] for s in self.strokes for p in s.pts]
        ys = [p[1] for s in self.strokes for p in s.pts]
        return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)

    def label(self) -> str:
        style = "пунктир" if self.dashed else "плътна"
        layer = f"{self.layer} · " if self.layer else ""
        return f"{layer}{style} {self.width:.2f}pt · {len(self.strokes)} линии"


@dataclass
class DieSource:
    name: str
    width: float                    # page size in pt
    height: float
    groups: list
    art_kind: str = "none"          # "pdf" | "image" | "none"
    art_data: bytes = b""           # pdf bytes or encoded image bytes
    art_page: int = 0
    art_rect: tuple = None          # where an image artwork sits (pt)
    filetype: str = "pdf"

    def selected_strokes(self):
        return [s for g in self.groups if g.selected for s in g.strokes]


# ---------------------------------------------------------------- helpers

def _bezier(p0, p1, p2, p3, steps=BEZIER_STEPS):
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def _close(a, b, tol=0.01):
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def _is_dashed(dashes) -> bool:
    if not dashes:
        return False
    nums = [float(x) for x in re.findall(r"[-\d.]+", dashes.split("]")[0])]
    # "[ 23 0 0 0 ]" draws a solid line; only real gaps count
    return len(nums) >= 2 and any(n > 0.01 for n in nums[1::2])


def _group_key(layer, color, width, dashed):
    c = "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in color)
    return f"{layer}|{c}|{width:.2f}|{int(dashed)}"


def _add_stroke(groups: dict, layer, color, width, dashed, stroke):
    if len(stroke.pts) < 2:
        return
    color = tuple(round(v, 3) for v in color)
    key = _group_key(layer, color, width, dashed)
    g = groups.get(key)
    if g is None:
        g = groups[key] = LineGroup(key, layer, color, round(width, 2), dashed)
    g.strokes.append(stroke)


# ---------------------------------------------------------------- PDF / AI / SVG

def _drawing_strokes(d):
    """Split one PyMuPDF drawing into polylines."""
    out, cur = [], []
    for it in d["items"]:
        op = it[0]
        if op == "re":
            r = it[1]
            out.append(Stroke([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)], True))
            continue
        if op == "qu":
            q = it[1]
            out.append(Stroke([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)], True))
            continue
        a = (it[1].x, it[1].y)
        if not cur or not _close(cur[-1], a):
            if len(cur) > 1:
                out.append(Stroke(cur))
            cur = [a]
        if op == "l":
            cur.append((it[2].x, it[2].y))
        elif op == "c":
            cur.extend(_bezier(a, (it[2].x, it[2].y), (it[3].x, it[3].y), (it[4].x, it[4].y)))
    if len(cur) > 1:
        closed = bool(d.get("closePath")) or _close(cur[0], cur[-1])
        if closed and _close(cur[0], cur[-1]) and len(cur) > 2:
            cur = cur[:-1]
        out.append(Stroke(cur, closed))
    return out


def groups_from_page(page) -> list:
    groups: dict = {}
    for d in page.get_drawings():
        if "s" not in d["type"] or d.get("color") is None:
            continue
        col = tuple(d["color"])[:3]
        if len(col) == 1:
            col = col * 3
        for s in _drawing_strokes(d):
            _add_stroke(groups, d.get("layer") or "", col, d.get("width") or 0.0,
                        _is_dashed(d.get("dashes")), s)
    return list(groups.values())


def load_pdf_bytes(data: bytes, name="document", filetype="pdf", page_no=0) -> DieSource:
    with PDF_LOCK:
        src = _load_pdf(data, name, filetype, page_no)
    auto_select(src.groups, (src.width, src.height))
    return src


def _load_pdf(data, name, filetype, page_no):
    doc = pymupdf.open(stream=data, filetype=filetype)
    if filetype != "pdf":                      # SVG etc.: keep a PDF copy for rendering
        data = doc.convert_to_pdf()
        doc = pymupdf.open(stream=data, filetype="pdf")
    page = doc[page_no]
    return DieSource(name, page.rect.width, page.rect.height, groups_from_page(page), "pdf", data, page_no)


def load_file(path: str) -> DieSource:
    import os
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        data = f.read()
    name = os.path.basename(path)
    if ext in (".ai", ".pdf"):
        if not data.startswith(b"%PDF"):
            i = data.find(b"%PDF")
            if i < 0:
                raise ValueError("Файлът не е запазен с PDF съвместимост.\n"
                                 "В Illustrator: Save As → .ai → включи „Create PDF Compatible File“.")
            data = data[i:]
        return load_pdf_bytes(data, name, "pdf")
    if ext == ".svg":
        return load_pdf_bytes(data, name, "svg")
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".psd", ".webp"):
        return image_only(data, name)
    raise ValueError(f"Неподдържан формат: {ext}")


def image_only(data: bytes, name: str, size_pt=None) -> DieSource:
    """A raster image without vectors (e.g. Photoshop pixels): artwork only."""
    if size_pt is None:
        with PDF_LOCK:
            pix = pymupdf.Pixmap(data)
        size_pt = (pix.width * 72 / 150, pix.height * 72 / 150)
    w, h = size_pt
    return DieSource(name, w, h, [], "image", data, 0, (0, 0, w, h), "image")


# ---------------------------------------------------------------- AICB (Illustrator clipboard, Photoshop paths)

_NUM = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")


def parse_aicb(text: str) -> list:
    """Parse the Adobe Illustrator clipboard format ("Adobe AI3"), a PostScript dialect."""
    groups: dict = {}
    stack: list = []
    path: list = []
    cur: list = []
    color, width, dashed, layer = (0, 0, 0), 1.0, False, ""
    page_h = None

    def flush_sub():
        nonlocal cur
        if len(cur) > 1:
            path.append(cur)
        cur = []

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("%%BoundingBox:") or line.startswith("%%HiResBoundingBox:"):
            nums = [float(x) for x in line.split(":")[1].split()]
            if len(nums) == 4:
                page_h = nums[3]
            continue
        if line.startswith("%") or not line:
            continue
        m = re.match(r"^\((.*)\)\s+Ln$", line)
        if m:
            layer = m.group(1)
            continue
        for tok in re.findall(r"\(.*?\)|\[.*?\]|\S+", line):
            if _NUM.match(tok):
                stack.append(float(tok))
                continue
            if tok.startswith("(") or tok.startswith("["):
                stack.append(tok)
                continue
            op = tok
            if op == "m":
                flush_sub()
                cur = [(stack[-2], stack[-1])]
            elif op in ("l", "L") and cur:
                cur.append((stack[-2], stack[-1]))
            elif op in ("c", "C") and cur and len(stack) >= 6:
                x1, y1, x2, y2, x3, y3 = stack[-6:]
                cur.extend(_bezier(cur[-1], (x1, y1), (x2, y2), (x3, y3)))
            elif op in ("v", "V") and cur and len(stack) >= 4:
                x2, y2, x3, y3 = stack[-4:]
                cur.extend(_bezier(cur[-1], cur[-1], (x2, y2), (x3, y3)))
            elif op in ("y", "Y") and cur and len(stack) >= 4:
                x1, y1, x3, y3 = stack[-4:]
                cur.extend(_bezier(cur[-1], (x1, y1), (x3, y3), (x3, y3)))
            elif op == "K" and len(stack) >= 4:
                c, mm, yy, k = stack[-4:]
                color = ((1 - c) * (1 - k), (1 - mm) * (1 - k), (1 - yy) * (1 - k))
            elif op == "XA" and len(stack) >= 3:
                color = tuple(stack[-3:])
            elif op == "G" and stack:
                color = (stack[-1],) * 3
            elif op == "X" and len(stack) >= 6:        # custom (spot) stroke colour
                c, mm, yy, k = [v for v in stack[-6:-2]]
                color = ((1 - c) * (1 - k), (1 - mm) * (1 - k), (1 - yy) * (1 - k))
            elif op == "w" and stack:
                width = stack[-1]
            elif op == "d" and len(stack) >= 2:
                dashed = _is_dashed(str(stack[-2]))
            elif op in ("S", "s", "B", "b"):
                flush_sub()
                for sub in path:
                    closed = op in ("s", "b") or _close(sub[0], sub[-1])
                    _add_stroke(groups, layer, color, width, dashed, Stroke(sub, closed))
                path = []
            elif op in ("F", "f", "N", "n", "H", "h"):
                flush_sub()
                path = []
            stack = []
    # AI coordinates are y-up
    ys = [p[1] for g in groups.values() for s in g.strokes for p in s.pts]
    top = page_h if page_h is not None else (max(ys) if ys else 0)
    for g in groups.values():
        for s in g.strokes:
            s.pts = [(x, top - y) for x, y in s.pts]
    return list(groups.values())


def normalize(src: DieSource, margin=20.0) -> DieSource:
    """Shift vector-only sources so the paths start at (margin, margin)."""
    pts = [p for g in src.groups for s in g.strokes for p in s.pts]
    if not pts:
        return src
    x0 = min(p[0] for p in pts)
    y0 = min(p[1] for p in pts)
    dx, dy = margin - x0, margin - y0
    for g in src.groups:
        for s in g.strokes:
            s.pts = [(x + dx, y + dy) for x, y in s.pts]
    src.width = max(p[0] for p in pts) + dx + margin
    src.height = max(p[1] for p in pts) + dy + margin
    return src


# ---------------------------------------------------------------- automatic die detection

def _endpoints(g: LineGroup):
    out = []
    for s in g.strokes:
        out.append(s.pts[0])
        out.append(s.pts[-1])
        if s.closed:
            out.extend(s.pts[::max(1, len(s.pts) // 4)])
    return out


def _is_page_frame(g: LineGroup, faces, page) -> bool:
    """A plain rectangle around the whole page (artboard / trim frame) is not a die."""
    if not page or len(faces) != 1:
        return False
    x0, y0, x1, y1 = faces[0].bounds
    pw, ph = page
    if (x1 - x0) < 0.85 * pw or (y1 - y0) < 0.85 * ph:
        return False
    return faces[0].area > 0.97 * (x1 - x0) * (y1 - y0)       # fills its box: a rectangle


def _face_score(g: LineGroup, page=None) -> float:
    """Total area of sizeable closed regions formed by this group alone."""
    from .geometry import faces_from_strokes
    try:
        faces = faces_from_strokes(g.strokes, heal=False)   # a quick look is enough here
    except Exception:
        return 0.0
    if not faces:
        return 0.0
    if _is_page_frame(g, faces, page):
        return 0.0
    areas = sorted((f.area for f in faces), reverse=True)
    big = areas[0]
    return sum(a for a in areas if a > big * 0.02)


def auto_select(groups: list, page=None) -> None:
    """Pick the die groups, then propose cut / crease roles for them."""
    _select_die(groups, page)
    from .roles import guess_roles
    guess_roles(groups)


def _select_die(groups: list, page=None) -> None:
    """Guess which line groups form the dieline.

    The seed is the group whose lines enclose the most area as panels; groups whose
    lines connect to the seed network are added (cut and crease lines are often
    different colours or layers)."""
    for g in groups:
        g.selected = False
    cands = [g for g in groups if g.strokes]
    if not cands:
        return
    # cheap prefilter: groups with many tiny strokes are usually artwork
    scored = sorted(cands, key=lambda g: g.length, reverse=True)[:12]
    scores = {g.key: _face_score(g, page) for g in scored}
    seed = max(scored, key=lambda g: scores[g.key])
    if scores[seed.key] <= 0:
        return
    seed.selected = True
    try:
        from shapely.geometry import LineString, Point
        from shapely.strtree import STRtree
    except ImportError:
        return
    sx0, sy0, sx1, sy1 = seed.bbox()
    span = max(sx1 - sx0, sy1 - sy0)
    tol = max(0.5, span * 0.002)
    # crease lines are often drawn a little short of the cut lines (another colour, so
    # another group): such a group still belongs to the die when it is made of plain
    # lines that end near the die's lines - within what the panel finder can close
    reach = max(tol, min(12.0, span * 0.03))
    seed_n = len(seed.strokes)

    def lines_of(g):
        return [LineString(s.pts + ([s.pts[0]] if s.closed else [])) for s in g.strokes]

    def line_like(g):
        """Open lines made of a few straight pieces (creases, perforations) - not closed
        outlines and not curves."""
        total = plain = 0.0
        for st in g.strokes:
            L = st.length()
            total += L
            if not st.closed and len(st.pts) <= 8:
                plain += L
        return total > 0 and plain >= 0.8 * total

    changed = True
    while changed:
        changed = False
        net = [ln for gg in groups if gg.selected for ln in lines_of(gg)]
        tree = STRtree(net)
        x0 = min(gg.bbox()[0] for gg in groups if gg.selected)
        y0 = min(gg.bbox()[1] for gg in groups if gg.selected)
        x1 = max(gg.bbox()[2] for gg in groups if gg.selected)
        y1 = max(gg.bbox()[3] for gg in groups if gg.selected)
        for g in cands:
            if g.selected:
                continue
            bx0, by0, bx1, by1 = g.bbox()
            m = span * 0.4
            if bx0 < x0 - m or by0 < y0 - m or bx1 > x1 + m or by1 > y1 + m:
                continue
            # a die group consists of strokes that start/end on the network
            # (closed shapes: share at least two points with it)
            touching = near = 0
            own = lines_of(g)
            own_tree = STRtree(own)
            loose = (len(g.strokes) <= 5 * seed_n + 50 and line_like(g)
                     and bx0 >= x0 - reach and by0 >= y0 - reach and bx1 <= x1 + reach and by1 <= y1 + reach)
            for k, s in enumerate(g.strokes):
                ends = s.pts if s.closed else [s.pts[0], s.pts[-1]]
                hit = close = 0
                for e in ends:
                    p = Point(e)
                    idx = tree.query(p.buffer(tol))
                    if any(net[i].distance(p) <= tol for i in idx):
                        hit += 1
                        close += 1
                    elif loose:
                        # near a die line, or on another line of this same group
                        # (creases end on creases)
                        if any(net[i].distance(p) <= reach for i in tree.query(p.buffer(reach))) or \
                                any(int(i) != k and own[int(i)].distance(p) <= tol
                                    for i in own_tree.query(p.buffer(tol))):
                            close += 1
                if hit >= 2:
                    touching += 1
                if close >= 2:
                    near += 1
            if touching >= max(1, 0.6 * len(g.strokes)) or (loose and near >= max(1, 0.7 * len(g.strokes))):
                g.selected = True
                changed = True
