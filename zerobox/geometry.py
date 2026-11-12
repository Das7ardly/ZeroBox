"""Turn dieline strokes into panels (faces) and folds. Qt-free.

Every closed region formed by the die lines is a face. Two faces that share a piece of
boundary are joined by a fold (crease); everything else on the outline is a cut. Faces
form a tree rooted at the main panel, which is what the 3D folding walks."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import shapely
import shapely.ops
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import linemerge, polygonize, unary_union
from shapely.strtree import STRtree

SOLVE_BUDGET = 8.0       # seconds a build may spend on closing / checking the box
MAX_SOLVE_FACES = 100   # more panels than this is not a box (artwork taken for the die)
SMALL_FACE = 0.035      # faces below this share of the biggest panel stay flat (slots, tabs)
MIN_FOLD = 3.0          # pt of shared edge to count as a fold


@dataclass
class Face:
    id: int
    poly: Polygon
    area: float
    parent: int = -1
    fold: int = -1                  # fold joining this face to its parent
    children: list = field(default_factory=list)
    small: bool = False
    depth: int = 0
    key: str = ""
    offset: tuple = (0.0, 0.0)      # how far a panel of a second die piece was moved

    @property
    def centroid(self):
        c = self.poly.representative_point()
        return (c.x, c.y)


@dataclass
class Fold:
    id: int
    parent: int
    child: int
    p0: tuple
    p1: tuple
    length: float
    angle: float = 90.0             # degrees, positive folds away from the printed side
    phase: int = 1                  # 1 = walls, 2 = flaps
    start: float = 0.0              # animation window inside 0..1
    end: float = 1.0
    sign: float = 1.0               # rotation sign that moves the child behind the print
    key: str = ""                   # edge key (the two panels it joins)
    locked: bool = False            # kept flat by the user
    solved: float = 90.0            # the angle the solver found (the check returns to it)

    skew: float = 0.0               # degrees the die is drawn rotated by

    @property
    def horizontal(self) -> bool:
        """Along the die's x direction (the die may be drawn at any angle)."""
        dx, dy = self.p1[0] - self.p0[0], self.p1[1] - self.p0[1]
        if self.skew:
            c, sn = math.cos(math.radians(self.skew)), math.sin(math.radians(self.skew))
            dx, dy = dx * c + dy * sn, -dx * sn + dy * c
        return abs(dx) >= abs(dy)


@dataclass
class FoldModel:
    faces: list
    folds: list
    root: int
    bbox: tuple
    cut_lines: list                 # [[(x, y), ...], ...] outline pieces that are cuts
    up_rotation: float = 0.0        # degrees around Z so the walls stand upright
    walls: set = field(default_factory=set)
    tube_sides: int = 0
    floor: bool = False              # root lies flat as the bottom (no wall tube)
    solve_report: str = ""
    check_report: str = ""
    issues: list = field(default_factory=list)       # check.Issue after the final angles
    seam_pairs: list = field(default_factory=list)   # edges that meet when the box is closed
    shared: list = field(default_factory=list)      # (edge key, p0, p1, "fold" | "cut" | "free")
    all_faces: list = field(default_factory=list)   # (face key, polygon) incl. excluded panels
    source_bbox: tuple = None       # where the die is drawn in the file (artwork area)
    pieces: int = 1                 # 2 when a two-piece box was put together

    def subtree(self, fid):
        out, st = [], [fid]
        while st:
            f = st.pop()
            out.append(f)
            st.extend(self.faces[f].children)
        return out


def _clean(strokes):
    """Strokes without broken points (NaN / infinite coordinates from damaged files)
    and without repeated points; strokes left with fewer than two points are dropped."""
    from .dieline import Stroke
    out = []
    for s in strokes:
        pts = []
        for q in s.pts:
            try:
                x, y = float(q[0]), float(q[1])
            except (TypeError, ValueError, IndexError):
                continue
            if not (math.isfinite(x) and math.isfinite(y)) or abs(x) > 1e7 or abs(y) > 1e7:
                continue
            if not pts or pts[-1] != (x, y):
                pts.append((x, y))
        if len(pts) >= 2:
            out.append(s if pts == list(s.pts) else Stroke(pts, s.closed and len(pts) >= 3))
    return out


def _lines(strokes):
    out = []
    for s in _clean(strokes):
        pts = list(s.pts) + ([s.pts[0]] if s.closed else [])
        if len(pts) >= 2:
            ln = LineString(pts)
            if ln.length > 0:
                out.append(ln)
    return out


SNAP_TOL = 3.0          # pt: corners closer than this are the same corner
EXTEND_TOL = 12.0       # pt: a line that stops this short of another one is extended to it


def _heal(geoms):
    """Close the small gaps real dielines have: crease lines stopped short of the cut
    line, panels drawn as separate rectangles a point apart, corners that miss."""
    from shapely.geometry import Point
    # corners of closed outlines that almost meet become one corner (panels drawn as
    # separate rectangles a point apart). Open lines are never moved, only extended
    # below. Links only between different outlines, so a curve never collapses.
    owner, pts = [], []
    for i, g in enumerate(geoms):
        cs = list(g.coords)
        closed = len(cs) > 2 and cs[0] == cs[-1]
        for c in cs:
            owner.append(i if closed else -1 - i)
            pts.append(c)
    parent = list(range(len(pts)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    box = {k: (c[0], c[1], c[0], c[1]) for k, c in enumerate(pts)}   # cluster extent
    ptree = STRtree([Point(c) for c in pts])
    for k, c in enumerate(pts):
        for j in ptree.query(Point(c).buffer(SNAP_TOL)):
            j = int(j)
            if owner[j] == owner[k] or owner[j] < 0 or owner[k] < 0 or math.dist(c, pts[j]) > SNAP_TOL:
                continue
            ra, rb = find(j), find(k)
            if ra == rb:
                continue
            a, b = box[ra], box[rb]
            merged = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
            if merged[2] - merged[0] > SNAP_TOL or merged[3] - merged[1] > SNAP_TOL:
                continue                      # never chain distinct corners together
            parent[ra] = rb
            box[rb] = merged
    groups = {}
    for k in range(len(pts)):
        groups.setdefault(find(k), []).append(k)
    rep = {}
    for members in groups.values():
        x = sum(pts[m][0] for m in members) / len(members)
        y = sum(pts[m][1] for m in members) / len(members)
        for m in members:
            rep[m] = (x, y)
    snapped, k = [], 0
    for g in geoms:
        n = len(g.coords)
        cs = [rep[k + t] for t in range(n)]
        k += n
        if len(cs) >= 2:
            snapped.append(LineString(cs))
    geoms = [g for g in snapped if not g.is_empty and g.length > 0]
    if len(geoms) < 2:
        return geoms
    tree = STRtree(geoms)
    extra = []
    for i, g in enumerate(geoms):
        cs = list(g.coords)
        if len(cs) < 2 or cs[0] == cs[-1]:
            continue                                  # closed outline: no loose ends
        for end, prev in ((cs[0], cs[1]), (cs[-1], cs[-2])):
            p = Point(end)
            near = [int(j) for j in tree.query(p.buffer(EXTEND_TOL)) if int(j) != i]
            if not near or min(geoms[j].distance(p) for j in near) < 1e-6:
                continue                              # nothing near, or exactly touching
            dx, dy = end[0] - prev[0], end[1] - prev[1]
            n1 = math.hypot(dx, dy)
            target = None
            jn = min(near, key=lambda j: geoms[j].distance(p))
            hair = geoms[jn].distance(p) <= 1.0
            if hair:
                # 0. a corner drawn a hair open: close it there - carrying the line on
                #    could reach some other line further away and cut a sliver off
                q = shapely.ops.nearest_points(geoms[jn], p)[0]
                ex, ey = q.x - end[0], q.y - end[1]
                n2 = math.hypot(ex, ey) or 1.0
                target = (q.x + ex / n2 * 0.6, q.y + ey / n2 * 0.6)
            if n1 > 0 and target is None:
                # 1. carry the line straight on until it meets another line
                ux, uy = dx / n1, dy / n1
                ray = LineString([end, (end[0] + ux * EXTEND_TOL, end[1] + uy * EXTEND_TOL)])
                best = EXTEND_TOL
                for j in near:
                    hit = ray.intersection(geoms[j])
                    if hit.is_empty:
                        continue
                    d = hit.distance(p)
                    if 1e-6 < d < best:
                        best = d
                if best < EXTEND_TOL:
                    target = (end[0] + ux * (best + 0.6), end[1] + uy * (best + 0.6))
            if target is None:
                # 2. a corner that misses sideways by a hair: join it to the nearest line
                j = min(near, key=lambda j: geoms[j].distance(p))
                if geoms[j].distance(p) <= SNAP_TOL:
                    q = shapely.ops.nearest_points(geoms[j], p)[0]
                    ex, ey = q.x - end[0], q.y - end[1]
                    n2 = math.hypot(ex, ey) or 1.0
                    target = (q.x + ex / n2 * 0.6, q.y + ey / n2 * 0.6)
            if target is not None:
                # the new piece overshoots a little so it really crosses the line it meets
                extra.append(LineString([end, target]))
    # a curve that only grazes another line (a relief arc whose top "touches" a crease)
    # leaves a hair-thin gap; join every such near touch
    near_tol = 0.6
    for i, g in enumerate(geoms):
        for c in g.coords:
            p = Point(c)
            for j in tree.query(p.buffer(near_tol)):
                j = int(j)
                if j == i:
                    continue
                d = geoms[j].distance(p)
                if 0.02 < d <= near_tol:
                    q = shapely.ops.nearest_points(geoms[j], p)[0]
                    ex, ey = q.x - c[0], q.y - c[1]
                    n2 = math.hypot(ex, ey) or 1.0
                    extra.append(LineString([c, (q.x + ex / n2 * 0.3, q.y + ey / n2 * 0.3)]))
    return geoms + extra


def _noded(strokes, grid=0.1, heal=False, skew=0.0):
    geoms = _lines(strokes)
    if not geoms:
        return None
    if skew:
        from shapely import affinity
        geoms = [affinity.rotate(g, -skew, origin=(0, 0)) for g in geoms]
    if heal:
        geoms = _heal(geoms)
    # snap-rounding: a line that ends on another line is split there even when the
    # coordinates miss by a rounding error (dies drawn at an angle)
    snapped = shapely.set_precision(MultiLineString(geoms), grid)
    try:
        return shapely.union_all(snapped, grid_size=grid)
    except shapely.errors.GEOSException:
        return unary_union(snapped)                # degenerate pieces: plain noding


def _polys(noded):
    if noded is None or noded.is_empty:
        return []
    return [p for p in polygonize(getattr(noded, "geoms", [noded])) if p.area > 1.0]


def _quality(polys, noded):
    """(share of the area in the biggest connected group of panels, share of line
    length left dangling outside any panel). A clean die scores (1, ~0)."""
    if not polys or noded is None:
        return 0.0, 1.0
    tree = STRtree(polys)
    parent = list(range(len(polys)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, p in enumerate(polys):
        for j in tree.query(p.buffer(0.05)):
            j = int(j)
            if j > i and p.boundary.intersection(polys[j].boundary).length >= MIN_FOLD:
                parent[find(i)] = find(j)
    area = {}
    for i, p in enumerate(polys):
        area[find(i)] = area.get(find(i), 0.0) + p.area
    share = max(area.values()) / max(1e-9, sum(area.values()))
    # the noded lines are split at every crossing, so a piece is either a panel edge or
    # dangling; its middle tells which (buffering the whole outline is far too slow on
    # dense artwork)
    parts = [g for g in getattr(noded, "geoms", [noded]) if g.length > 0]
    if not parts:
        return share, 1.0
    mids = shapely.line_interpolate_point(parts, 0.5, normalized=True)
    hit = STRtree([p.boundary for p in polys]).query(mids, predicate="dwithin", distance=0.2)
    covered = set(int(i) for i in hit[0])
    total = sum(g.length for g in parts)
    dangle = sum(g.length for i, g in enumerate(parts) if i not in covered) / max(1e-9, total)
    return share, dangle


def faces_from_strokes(strokes, grid=0.1, heal=True):
    """Panels of the die. Clean files are used as drawn; only when that leaves the die in
    pieces or with loose lines are the small gaps closed (and kept if that helps).
    heal=False: as drawn only (quick look, e.g. scoring artwork groups)."""
    # a die drawn at an angle is worked on upright (lines stay on the rounding grid,
    # so lines that end on each other still meet) and the panels are turned back
    strokes = _clean(strokes)
    skew = _skew_lines(strokes)

    def back(polys):
        if not skew:
            return polys
        from shapely import affinity
        return [affinity.rotate(p, skew, origin=(0, 0)) for p in polys]
    noded = _noded(strokes, grid, skew=skew)
    polys = _polys(noded)
    if not heal:
        return back(polys)
    share, dangle = _quality(polys, noded)
    if share >= 0.97 and dangle <= 0.03:
        return back(polys)
    noded2 = _noded(strokes, grid, heal=True, skew=skew)
    polys2 = _polys(noded2)
    share2, dangle2 = _quality(polys2, noded2)
    if (share2 - dangle2) > (share - dangle) + 0.01:
        return back(polys2)
    return back(polys)


def _shared(a: Polygon, b: Polygon):
    inter = a.boundary.intersection(b.boundary)
    if inter.is_empty:
        return None, 0.0
    lines = [g for g in getattr(inter, "geoms", [inter]) if g.geom_type in ("LineString", "MultiLineString")]
    if not lines:
        return None, 0.0
    merged = linemerge(unary_union(lines)) if len(lines) > 1 else lines[0]
    return merged, merged.length


def _chord(geom):
    pts = []
    for g in getattr(geom, "geoms", [geom]):
        pts.extend(g.coords)
    best, pair = -1, (pts[0], pts[-1])
    # extreme points along the principal direction are enough for straight folds
    for i in (0, len(pts) - 1):
        for p in pts:
            d = math.dist(pts[i], p)
            if d > best:
                best, pair = d, (pts[i], p)
    a, b = pair
    for p in pts:
        if math.dist(a, p) > best:
            best, pair = math.dist(a, p), (a, p)
    return tuple(pair[0]), tuple(pair[1])


def _components(polys):
    tree = STRtree(polys)
    parent = list(range(len(polys)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, p in enumerate(polys):
        for j in tree.query(p.buffer(0.05)):
            j = int(j)
            if j > i and p.boundary.intersection(polys[j].boundary).length >= MIN_FOLD:
                parent[find(i)] = find(j)
    comps = {}
    for i in range(len(polys)):
        comps.setdefault(find(i), []).append(i)
    return sorted(comps.values(), key=lambda c: -sum(polys[k].area for k in c))


def _wall_row(polys, comp):
    """Panels of one piece that form its row of walls, left to right, plus the axis
    (0 = walls side by side along x, 1 = stacked along y)."""
    big = max(comp, key=lambda k: polys[k].area)
    best = None
    for axis in (0, 1):
        o = 1 - axis                                   # the other axis: walls share its span
        b0, b1 = polys[big].bounds[o], polys[big].bounds[o + 2]
        row = []
        for k in comp:
            a0, a1 = polys[k].bounds[o], polys[k].bounds[o + 2]
            overlap = min(a1, b1) - max(a0, b0)
            if overlap > 0.8 * (b1 - b0) and (a1 - a0) < 1.25 * (b1 - b0):
                row.append(k)
        row.sort(key=lambda k: polys[k].bounds[axis])
        if best is None or len(row) > len(best[0]):
            best = (row, axis)
    return best


def _join_pieces(polys):
    """Boxes printed as two pieces (each with its own glue flap) are put back together:
    the second piece is moved so that its glue-flap crease sits on the free edge of the
    first piece, and its glue flap (hidden inside the box) is dropped.
    Returns (polys, offsets): offsets[i] = how far panel i was moved."""
    offsets = [(0.0, 0.0)] * len(polys)
    if len(polys) < 4:
        return polys, offsets
    comps = _components(polys)
    if len(comps) < 2:
        return polys, offsets
    area = [sum(polys[k].area for k in c) for c in comps]
    if area[1] < 0.3 * area[0] or len(comps[1]) < 3:
        return polys, offsets
    A, B = comps[0], comps[1]
    ra, axis_a = _wall_row(polys, A)
    rb, axis_b = _wall_row(polys, B)
    if axis_a != axis_b or len(ra) < 2 or len(rb) < 2:
        return polys, offsets
    ax = axis_a
    o = 1 - ax

    def width(k):
        b = polys[k].bounds
        return b[ax + 2] - b[ax]

    def glue_end(row):
        widths = sorted(width(k) for k in row)
        typical = widths[len(widths) // 2]
        first, last = width(row[0]), width(row[-1])
        if first < 0.6 * typical and first <= last:
            return "start"
        if last < 0.6 * typical:
            return "end"
        return None
    ga, gb = glue_end(ra), glue_end(rb)
    if gb is None:
        return polys, offsets
    a_lo = min(polys[k].bounds[ax] for k in ra)
    a_hi = max(polys[k].bounds[ax + 2] for k in ra)
    if gb == "start" and ga != "end":
        glue = rb[0]
        hinge = polys[glue].bounds[ax + 2]             # where piece B's glue flap folds
        shift_ax = a_hi - hinge                        # B continues after A's free end
    elif gb == "end" and ga != "start":
        glue = rb[-1]
        hinge = polys[glue].bounds[ax]
        shift_ax = a_lo - hinge                        # B comes before A's free start
    else:
        return polys, offsets
    big_a = max(ra, key=lambda k: polys[k].area)
    big_b = max(rb, key=lambda k: polys[k].area)
    shift_o = polys[big_a].bounds[o] - polys[big_b].bounds[o]
    d = (shift_ax, shift_o) if ax == 0 else (shift_o, shift_ax)
    from shapely import affinity
    moved, offs = [], []
    for i, p in enumerate(polys):
        if i in B:
            if i == glue:
                continue
            moved.append(affinity.translate(p, d[0], d[1]))
            offs.append(d)
        elif i in A:
            moved.append(p)
            offs.append((0.0, 0.0))
    # stitch the seam: the two pieces' edges are a fraction of a point apart, so their
    # outlines are re-noded together (closed-outline corners snap) into one die
    rings = [LineString(p.exterior.coords) for p in moved]
    rings += [LineString(r.coords) for p in moved for r in p.interiors]
    noded = unary_union(shapely.set_precision(MultiLineString(_heal(rings)), 0.1))
    out, out_offs = [], []
    grown = [p.buffer(0.5) for p in moved]
    gtree = STRtree(grown)
    for q in _polys(noded):
        c = q.representative_point()
        owner = min((int(k) for k in gtree.query(c) if grown[int(k)].contains(c)), default=None)
        if owner is None:
            continue                                   # a hole or a sliver outside both pieces
        out.append(q)
        out_offs.append(offs[owner])
    return out, out_offs


def _skew_lines(strokes) -> float:
    return _skew_of([list(s.pts) + ([s.pts[0]] if s.closed else []) for s in strokes if len(s.pts) >= 2])


def _skew(polys) -> float:
    return _skew_of([list(p.exterior.coords) for p in polys])


def _skew_of(rings) -> float:
    """Degrees the die is drawn rotated by: the direction most of its lines run in,
    in (-45, 45]. 0 for the usual upright drawing."""
    acc = []
    for cs in rings:
        for (ax, ay), (bx, by) in zip(cs, cs[1:]):
            L = math.hypot(bx - ax, by - ay)
            if L >= 2.0:
                acc.append((math.degrees(math.atan2(by - ay, bx - ax)) % 90.0, L))
    if not acc:
        return 0.0
    bins = {}
    for a, L in acc:
        k = int(round(a)) % 90
        bins[k] = bins.get(k, 0.0) + L
    k = max(bins, key=lambda b: bins[b] + 0.5 * (bins.get((b - 1) % 90, 0.0) + bins.get((b + 1) % 90, 0.0)))
    num = den = 0.0
    for a, L in acc:
        d = (a - k + 45.0) % 90.0 - 45.0
        if abs(d) <= 1.5:
            num += d * L
            den += L
    ang = k + (num / den if den else 0.0)
    if ang > 45.0:
        ang -= 90.0
    return 0.0 if abs(ang) < 0.25 else ang


def face_key(poly) -> str:
    """Stable id of a panel across rebuilds (a point inside it, rounded)."""
    c = poly.representative_point()
    return "%d,%d" % (round(c.x), round(c.y))


def edge_key(ka: str, kb: str) -> str:
    return "|".join(sorted((ka, kb)))


@dataclass
class Manual:
    """What the user marked by hand in the 2D die view."""
    root: str = ""                                  # face key of the front panel
    cuts: set = field(default_factory=set)          # shared edges that are cuts, not folds
    folds: set = field(default_factory=set)         # shared edges that must be the hinge
    flat: set = field(default_factory=set)          # folds kept flat (panels act as one)
    excluded: set = field(default_factory=set)      # panels that are not part of the box

    def empty(self) -> bool:
        return not (self.root or self.cuts or self.folds or self.flat or self.excluded)


def build(strokes, root: int | None = None, angles: dict | None = None, solve=True,
          manual: Manual | None = None, fold_lines=None) -> FoldModel | None:
    """fold_lines: strokes panels may hinge on (crease lines). When given, two panels
    touching along a cut line (a slot, flaps side by side) are never folded together."""
    manual = manual or Manual()
    deadline = time.monotonic() + SOLVE_BUDGET
    polys = faces_from_strokes(strokes)
    if not polys:
        return None
    source_bbox = unary_union(polys).bounds
    skew = _skew(polys)
    if skew:
        # two-piece dies are matched along x / y: do it in the die's own frame
        from shapely import affinity
        turned, offsets = _join_pieces([affinity.rotate(p, -skew, origin=(0, 0)) for p in polys])
        polys = [affinity.rotate(p, skew, origin=(0, 0)) for p in turned]
        c, sn = math.cos(math.radians(skew)), math.sin(math.radians(skew))
        offsets = [(dx * c - dy * sn, dx * sn + dy * c) for dx, dy in offsets]
    else:
        polys, offsets = _join_pieces(polys)
    keys = [face_key(p) for p in polys]
    tree = STRtree(polys)
    adj = {i: {} for i in range(len(polys))}
    shared_all = []                                  # every pair of touching panels
    hinge_zone = None
    if fold_lines is not None:
        fl = _lines(fold_lines)
        from shapely import affinity
        for d in {o for o in offsets if o != (0.0, 0.0)}:
            # a joined second piece: its creases moved with it (its glue crease is the seam)
            fl += [affinity.translate(ln, d[0], d[1]) for ln in _lines(fold_lines)]
        hinge_zone = unary_union(fl).buffer(1.5) if fl else Polygon()
    for i, p in enumerate(polys):
        for j in tree.query(p.buffer(0.05)):
            j = int(j)
            if j <= i:
                continue
            geom, length = _shared(p, polys[j])
            if length < MIN_FOLD:
                continue
            ek = edge_key(keys[i], keys[j])
            shared_all.append((i, j, geom, ek))
            if ek in manual.cuts or keys[i] in manual.excluded or keys[j] in manual.excluded:
                continue
            if (hinge_zone is not None and ek not in manual.folds
                    and geom.intersection(hinge_zone).length < 0.5 * length):
                continue                            # they only touch along a cut line
            adj[i][j] = adj[j][i] = geom

    # keep the biggest connected group of panels (the box); the rest are holes
    seen, comps = set(), []
    for i in range(len(polys)):
        if i in seen or keys[i] in manual.excluded:
            continue
        comp, st = [], [i]
        seen.add(i)
        while st:
            k = st.pop()
            comp.append(k)
            for n in adj[k]:
                if n not in seen:
                    seen.add(n)
                    st.append(n)
        comps.append(comp)
    if not comps:
        return None
    wanted = [c for c in comps if any(keys[k] == manual.root for k in c)]
    comp = wanted[0] if wanted else max(comps, key=lambda c: sum(polys[k].area for k in c))
    remap = {old: new for new, old in enumerate(sorted(comp, key=lambda k: -polys[k].area))}
    faces = [None] * len(remap)
    for old, new in remap.items():
        faces[new] = Face(new, polys[old], polys[old].area)
        faces[new].key = keys[old]
        faces[new].offset = offsets[old]
    big = faces[0].area
    for f in faces:
        f.small = f.area < big * SMALL_FACE
    # small pieces on the outer edge of the die that are not hair-thin are real tabs
    # (tuck/lock tabs) and fold; small pieces inside a panel or thin strips stay flat
    outer = unary_union([f.poly for f in faces])
    rim = unary_union([Polygon(g.exterior) for g in getattr(outer, "geoms", [outer])]).boundary.buffer(1.0)
    ob = outer.bounds
    unit = min(1.0, max(ob[2] - ob[0], ob[3] - ob[1]) / 880.0)   # dies drawn small / to scale
    for f in faces:
        f.tab = False
        if f.small:
            mrr = f.poly.minimum_rotated_rectangle
            cs = list(mrr.exterior.coords) if mrr.geom_type == "Polygon" else []
            a, b = sorted((math.dist(cs[0], cs[1]), math.dist(cs[1], cs[2]))) if len(cs) > 2 else (0.0, 0.0)
            # a sliver beside a slit is long and narrow; a small glue tab is not
            thin = a < 15.0 * unit and (a < 6.0 * unit or b > 3.0 * a)
            on_rim = f.poly.boundary.intersection(rim).length > 0.3 * f.poly.length
            f.tab = on_rim and not thin

    by_key = {f.key: f.id for f in faces}
    fixed_root = by_key.get(manual.root)
    if fixed_root is None and root is not None and 0 <= root < len(faces):
        fixed_root = root

    # every pair of panels that may hinge, longest shared edge first
    order_edges = []
    seen_e = set()
    inv = {n: o for o, n in remap.items()}
    for f in range(len(faces)):
        for o, geom in adj[inv[f]].items():
            if o not in remap:
                continue
            n = remap[o]
            e = (min(f, n), max(f, n))
            if e not in seen_e:
                seen_e.add(e)
                order_edges.append((e[0], e[1], geom))
    order_edges.sort(key=lambda t: -t[2].length)
    proto = faces

    def assemble(row, root_id, prefer, flat=manual.flat):
        """One reading of the die: a spanning tree over the panels - hinges the user
        forced first, then the hinges of `row` (the panels taken as the walls), then the
        longest shared edges (a flap hangs on its long crease, not on the short slot
        line that separates it from the next flap) - folded and closed."""
        faces = []
        for f in proto:
            g = Face(f.id, f.poly, f.area)
            g.small, g.tab, g.key, g.offset = f.small, f.tab, f.key, f.offset
            faces.append(g)
        forced = [e for e in order_edges if edge_key(faces[e[0]].key, faces[e[1]].key) in manual.folds]
        first = [e for e in order_edges if (e[0], e[1]) in row and e not in forced]
        rest = [e for e in order_edges if e not in forced and e not in first]
        parent_of = list(range(len(faces)))

        def find(x):
            while parent_of[x] != x:
                parent_of[x] = parent_of[parent_of[x]]
                x = parent_of[x]
            return x
        tree_edges = {}
        for a, b, geom in forced + first + rest:
            ra, rb = find(a), find(b)
            if ra == rb:
                continue
            parent_of[ra] = rb
            tree_edges.setdefault(a, []).append((b, geom))
            tree_edges.setdefault(b, []).append((a, geom))

        folds = []
        faces[root_id].parent = -1
        visited = {root_id}
        queue = [root_id]
        while queue:
            nxt = []
            for f in queue:
                for n, geom in sorted(tree_edges.get(f, []), key=lambda t: -t[1].length):
                    if n in visited:
                        continue
                    visited.add(n)
                    p0, p1 = _chord(geom)
                    fold = Fold(len(folds), f, n, p0, p1, geom.length)
                    fold.skew = skew
                    fold.key = edge_key(faces[f].key, faces[n].key)
                    fold.locked = fold.key in flat
                    fold.angle = 0.0 if ((faces[n].small and not faces[n].tab) or fold.locked) else 90.0
                    folds.append(fold)
                    faces[n].parent = f
                    faces[n].fold = fold.id
                    faces[n].depth = faces[f].depth + 1
                    faces[f].children.append(n)
                    nxt.append(n)
            queue = nxt
        for fold in folds:
            fold.sign = _fold_sign(fold, faces[fold.child])
        model = FoldModel(faces, folds, root_id, unary_union([f.poly for f in faces]).bounds, [])
        model.skew = skew
        model.deadline = deadline
        _schedule(model, prefer)
        _follow_collinear(model)
        if solve and len(faces) > MAX_SOLVE_FACES:
            model.solve_report = (f"{len(faces)} панела са твърде много за автоматично затваряне — "
                                  "всички сгъвки са на 90°. Провери кои линии са щанца.")
        elif solve:
            # angles that close the box (hexagons, trays with sloped walls, pyramids...)
            from . import solver
            try:
                model.solve_report = solver.auto_close(model)
            except Exception as e:                     # never block loading on the solver
                model.solve_report = f"автоматичното затваряне не успя: {e}"
            for fd in folds:
                if fd.locked:
                    fd.angle = 0.0
            _follow_collinear(model)
        return model

    # the plain reading first; when panels touch in loops (slots drawn like creases) the
    # die can be read in other ways too - each row of panels may be the walls. The
    # reading that closes best is kept, the plain one wins ties.
    from . import check
    # panels the user keeps flat do not take part in choosing the reading (a lid held
    # open would count against the right one); they are applied to the chosen reading
    chosen = (set(), fixed_root if fixed_root is not None else _pick_root(faces, adj, remap), None)
    model = assemble(*chosen, flat=())
    loops = len(order_edges) > len(faces) - 1
    solve = solve and len(faces) <= MAX_SOLVE_FACES
    if solve:
        best = getattr(model, "close_rank", None) or check.rank(model)
        rows = _rows(proto, order_edges, skew)
        size = max(model.bbox[2] - model.bbox[0], model.bbox[3] - model.bbox[1])
        if not loops or (best[0] == 0 and best[1] < 0.02 * size):
            # one tree only, or already a perfectly closed box: only make sure the
            # front panel is one of the walls when the die has a clear row of walls
            rows = rows[:1] if (fixed_root is None and rows and model.root not in rows[0][2]) else []
        for row, prefer, members in rows[:6]:
            if time.monotonic() > deadline:
                break
            r_id = fixed_root if fixed_root is not None else _pick_root(faces, adj, remap, members)
            other = assemble(row, r_id, prefer, flat=())
            rank = getattr(other, "close_rank", None) or check.rank(other)
            if check.better(rank, best, other) or (not check.better(best, rank, other)
                                                   and other.tube_sides > model.tube_sides):
                model, best, chosen = other, rank, (row, r_id, prefer)
    if manual.flat:
        model = assemble(*chosen)
    faces, folds, root = model.faces, model.folds, model.root
    model.source_bbox = source_bbox
    model.pieces = 2 if any(o != (0.0, 0.0) for o in offsets) else 1
    # every touching pair, for the 2D tools (hinge in the tree or not)
    tree_keys = {fd.key for fd in folds}
    for i, j, geom, ek in shared_all:
        p0, p1 = _chord(geom)
        state = "fold" if ek in tree_keys else ("cut" if ek in manual.cuts else "free")
        model.shared.append((ek, p0, p1, state))
    model.all_faces = [(keys[i], polys[i]) for i in range(len(polys))]
    big_children = [c for c in faces[root].children if not faces[c].small and folds[faces[c].fold].angle]
    model.floor = model.tube_sides == 0 and len(big_children) >= 3
    from . import check
    if solve:
        # remember the closed state: which edges meet, and the angles that got there
        from . import solver
        from .fold3d import face_transforms
        x0, y0, x1, y1 = model.bbox
        try:
            model.seam_pairs = solver._pairs(model, face_transforms(model, 1.0), 0.18 * max(x1 - x0, y1 - y0))
        except Exception:
            model.seam_pairs = []
        for fd in folds:
            fd.solved = fd.angle
        # then look for anything a real box can't do and repair it
        protected = {fd.key for fd in folds if angles and fold_key(fd) in angles}
        try:
            model.check_report = check.repair(model, protected)
        except Exception as e:                     # never block loading on the check
            model.check_report = f"проверката не успя: {e}"
        _follow_collinear(model)
    if angles:
        for fold in folds:
            key = fold_key(fold)
            if key in angles:
                fold.angle = angles[key]
        _follow_collinear(model)
    try:
        model.issues = check.analyze(model) if len(faces) <= MAX_SOLVE_FACES else []
    except Exception:
        model.issues = []
    model.cut_lines = _cut_lines(faces, folds)
    return model


def fold_key(fold: Fold) -> str:
    """Stable id for a fold across rebuilds (midpoint, rounded)."""
    return "%d,%d" % (round((fold.p0[0] + fold.p1[0]) / 2), round((fold.p0[1] + fold.p1[1]) / 2))


def _rows(faces, edges, skew):
    """Rows of three or more panels hinged side by side on parallel creases - each could
    be the walls of the box. [(set of hinge pairs, hinges run along x?, panels)], the
    row with the most panels (then panel area) first."""
    c, sn = math.cos(math.radians(skew)), math.sin(math.radians(skew))
    out = []
    for horizontal in (False, True):
        parent = {f.id: f.id for f in faces if not f.small}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        used = []
        for a, b, geom in edges:
            if a not in parent or b not in parent:
                continue
            p0, p1 = _chord(geom)
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            dx, dy = dx * c + dy * sn, -dx * sn + dy * c
            L = math.hypot(dx, dy)
            if L < 1e-9 or abs(dx if horizontal else dy) / L < 0.98:
                continue
            parent[find(a)] = find(b)
            used.append((a, b))
        groups = {}
        for f in parent:
            groups.setdefault(find(f), set()).add(f)
        for members in groups.values():
            if len(members) >= 3:
                row = {(a, b) for a, b in used if a in members}
                out.append((row, horizontal, members))
    out.sort(key=lambda r: (-len(r[2]), -sum(faces[f].area for f in r[2])))
    return out


def _pick_root(faces, adj, remap, among=None):
    """A big panel with the most panels around it (front wall, tray base); then the
    biggest, then the leftmost. A lid hanging off one wall is never chosen."""
    inv = {n: o for o, n in remap.items()}
    pool = [f for f in faces if among is None or f.id in among]
    best = max(f.area for f in pool)
    cands = [f for f in pool if f.area >= best * 0.5]

    def degree(f):
        return sum(1 for o in adj[inv[f.id]] if o in remap and not faces[remap[o]].small)
    return min(cands, key=lambda f: (-degree(f), -round(f.area / best, 2), f.poly.bounds[0])).id


def _fold_sign(fold: Fold, child: Face) -> float:
    """+1/-1 so a positive angle swings the child away from the viewer (behind the print).

    Flat die: x right, y down in the file; world = (x, -y, 0), print faces +Z."""
    ux, uy = fold.p1[0] - fold.p0[0], -(fold.p1[1] - fold.p0[1])
    cx, cy = child.centroid
    rx, ry = cx - fold.p0[0], -(cy - fold.p0[1])
    cross_z = ux * ry - uy * rx
    # rotating r around u by +phi gives z = sin(phi) * (u x r)_z / |u|; we want z < 0
    return -1.0 if cross_z > 0 else 1.0


def _schedule(model: FoldModel, prefer=None):
    """Walls first, then flaps from smallest to biggest (dust flaps before lids)."""
    faces, folds = model.faces, model.folds
    root = model.root
    if not folds:
        return

    def chain(horizontal):
        out, st, seen = {root}, [root], {root}
        while st:
            f = st.pop()
            for c in faces[f].children:
                if c in seen:
                    continue
                fd = folds[faces[c].fold]
                if faces[c].small:
                    # a sliver (e.g. the seam of a two-piece box): look through it
                    seen.add(c)
                    st.append(c)
                elif fd.horizontal == horizontal:
                    seen.add(c)
                    out.add(c)
                    st.append(c)
        return out

    hv = chain(True)
    vv = chain(False)
    walls_horizontal = (len(hv), sum(faces[f].area for f in hv)) > (len(vv), sum(faces[f].area for f in vv))
    if prefer is not None and len(hv if prefer else vv) >= 3:
        walls_horizontal = prefer
    walls = hv if walls_horizontal else vv
    model.up_rotation = (90.0 if walls_horizontal else 0.0) + getattr(model, "skew", 0.0)
    model.walls = walls

    flaps = []
    for fd in folds:
        if fd.child in walls:
            fd.phase, fd.start, fd.end = 1, 0.0, 0.45
        elif fd.parent in walls:
            flaps.append(fd)
    flaps.sort(key=lambda fd: sum(faces[f].area for f in model.subtree(fd.child)))
    n = len(flaps)
    span = 0.3
    for i, fd in enumerate(flaps):
        s = 0.45 + (1 - 0.45 - span) * (i / max(1, n - 1))
        fd.phase, fd.start, fd.end = 2, s, s + span
    # nested folds (tuck tabs) move together with the flap they hang on
    for fd in folds:
        if fd.phase == 2 and fd in flaps:
            for f in model.subtree(fd.child)[1:]:
                sub = folds[faces[f].fold]
                sub.phase, sub.start, sub.end = 2, fd.start, fd.end
    for fd in folds:
        if fd.child not in walls and fd.parent not in walls and fd.start == 0.0 and fd.end == 1.0:
            fd.phase, fd.start, fd.end = 2, 0.45, 1.0


def _follow_collinear(model: FoldModel):
    """Small pieces (strips next to slits) whose hinge continues a real fold move with it."""
    folds, faces = model.folds, model.faces

    def base(fid):
        # walk up through pieces that stay flat with their parent
        while faces[fid].parent >= 0 and faces[fid].small and folds[faces[fid].fold].angle == 0:
            fid = faces[fid].parent
        return fid

    for fd in folds:                         # breadth-first, parents are settled first
        if not faces[fd.child].small:
            continue
        b = base(fd.parent)
        below = set(model.subtree(fd.child))
        for big in folds:
            if faces[big.child].small or base(big.parent) != b:
                continue
            if big.parent in below:
                continue                     # a fold hanging off this strip itself, not beside it
            ux, uy = big.p1[0] - big.p0[0], big.p1[1] - big.p0[1]
            L = math.hypot(ux, uy)
            if L == 0:
                continue

            def off(p):
                return abs((p[0] - big.p0[0]) * uy - (p[1] - big.p0[1]) * ux) / L
            if off(fd.p0) < 1.0 and off(fd.p1) < 1.0:
                fd.angle, fd.start, fd.end, fd.phase = big.angle, big.start, big.end, big.phase
                break


def _cut_lines(faces, folds):
    """Outline pieces that are not folds (for drawing the die in 2D)."""
    fold_geoms = [LineString([fd.p0, fd.p1]).buffer(0.3) for fd in folds]
    folds_u = unary_union(fold_geoms) if fold_geoms else None
    outline = unary_union([f.poly.boundary for f in faces])
    if folds_u is not None:
        outline = outline.difference(folds_u)
    out = []
    for g in getattr(outline, "geoms", [outline]):
        if g.geom_type == "LineString" and len(g.coords) > 1:
            out.append(list(g.coords))
    return out
