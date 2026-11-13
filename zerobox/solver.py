"""Find fold angles that close the box, for any die (not just 90-degree boxes). Qt-free.

auto_close tries the readings below and keeps the one the checker ranks best
(check.rank); plain 90-degree folds win ties.
1. Every crease at 90 degrees (what most boxes need).
2. Tube boxes (a chain of wall panels, any number of sides): one angle for every wall
   fold, searched so the last wall meets the glue flap / first wall. 90 for a normal
   box, 60 for a hexagon, 120 for a triangle...
3. If the box is still wrong (trays with sloped walls, pyramids): free cut edges of
   different panels that end up close to each other are paired, and the angles are
   nudged until paired edges meet."""
from __future__ import annotations

import math
import time

import numpy as np

from . import fold3d


# ---------------------------------------------------------------- helpers

def _segments(face, min_len=1.0):
    """Straight boundary segments of a face (collinear pieces merged), flat die coords."""
    pts = list(face.poly.exterior.coords)[:-1]
    n = len(pts)
    if n < 3:
        return []
    # start at a corner so a straight run is not split at the ring start
    def turn(i):
        a, b, c = np.array(pts[i - 1]), np.array(pts[i]), np.array(pts[(i + 1) % n])
        u, v = b - a, c - b
        nu, nv = np.linalg.norm(u), np.linalg.norm(v)
        if nu < 1e-9 or nv < 1e-9:
            return 0.0
        return abs(u[0] * v[1] - u[1] * v[0]) / (nu * nv)
    corners = [i for i in range(n) if turn(i) > 0.02]
    if len(corners) < 2:
        return []
    segs = []
    for k, i in enumerate(corners):
        j = corners[(k + 1) % len(corners)]
        a, b = np.array(pts[i]), np.array(pts[j])
        if np.linalg.norm(b - a) >= min_len:
            segs.append((a, b))
    return segs


def _on_line(p, a, b, tol=0.8):
    ab = b - a
    L = np.linalg.norm(ab)
    if L < 1e-9:
        return False
    t = float((p - a) @ ab) / (L * L)
    d = abs(ab[0] * (p - a)[1] - ab[1] * (p - a)[0]) / L
    return -0.02 <= t <= 1.02 and d < tol


def _free_segments(model, fid):
    """Boundary segments of a face that are cuts (not on any of its folds)."""
    face = model.faces[fid]
    hinges = []
    if face.fold >= 0:
        fd = model.folds[face.fold]
        hinges.append((np.array(fd.p0), np.array(fd.p1)))
    for c in face.children:
        fd = model.folds[model.faces[c].fold]
        hinges.append((np.array(fd.p0), np.array(fd.p1)))
    out = []
    for a, b in _segments(face):
        mid = (a + b) / 2
        if any(_on_line(mid, h0, h1) and _on_line(a, h0, h1, 2.0) for h0, h1 in hinges):
            continue
        out.append((a, b))
    return out


def _world(M, p):
    return (M @ np.array([p[0], -p[1], 0.0, 1.0]))[:3]


def _size(model):
    x0, y0, x1, y1 = model.bbox
    return max(x1 - x0, y1 - y0)


# ---------------------------------------------------------------- 1. tube closing

def _chain(model):
    """Wall faces in order along the tube, or [] when there is no tube."""
    walls = getattr(model, "walls", set())
    if len(walls) < 3:
        return []
    adj = {f: [] for f in walls}
    for f in walls:
        p = _wall_parent(model, f)
        if p in walls:
            adj[p].append(f)
            adj[f].append(p)
    ends = [f for f, n in adj.items() if len(n) == 1]
    if len(ends) != 2 or any(len(n) > 2 for n in adj.values()):
        return []
    order, prev, cur = [ends[0]], None, ends[0]
    while True:
        nxt = [n for n in adj[cur] if n != prev]
        if not nxt:
            break
        prev, cur = cur, nxt[0]
        order.append(cur)
    return order if len(order) == len(walls) else []


def _wall_parent(model, f):
    """The panel a wall hangs on, looking through slivers (the seam strip of a two-piece
    box sits between two walls). -1 for the root."""
    p = model.faces[f].parent
    while p >= 0 and model.faces[p].small and model.faces[p].parent >= 0:
        p = model.faces[p].parent
    return p


def _hinge_between(model, a, b):
    """The fold that turns one of two neighbouring walls against the other."""
    for child, parent in ((a, b), (b, a)):
        if model.faces[child].fold >= 0 and _wall_parent(model, child) == parent:
            return model.folds[model.faces[child].fold]
    return None


def _outer_edge(model, fid, hinge):
    """The cut edge of an end panel that lies across from (parallel to) its hinge."""
    h0, h1 = np.array(hinge.p0), np.array(hinge.p1)
    u = (h1 - h0) / max(1e-9, np.linalg.norm(h1 - h0))
    best, bd = None, -1
    for a, b in _free_segments(model, fid):
        v = b - a
        L = np.linalg.norm(v)
        if L < 0.4 * np.linalg.norm(h1 - h0) or abs(float(u @ v) / L) < 0.97:
            continue
        mid = (a + b) / 2
        d = abs(u[0] * (mid - h0)[1] - u[1] * (mid - h0)[0])
        if d > bd:
            best, bd = (a, b), d
    return best, bd


def _seg_gap(A, B):
    (a0, a1), (b0, b1) = A, B
    return min(np.linalg.norm(a0 - b0) + np.linalg.norm(a1 - b1),
               np.linalg.norm(a0 - b1) + np.linalg.norm(a1 - b0)) / 2


def _looks_like_glue(edge, hinge, width, wall_w):
    """Glue flaps are clearly narrower than the walls, often tapered."""
    if width < 0.6 * wall_w:
        return True
    hl = np.linalg.norm(np.array(hinge.p1) - np.array(hinge.p0))
    el = np.linalg.norm(edge[1] - edge[0])
    return width < 0.8 * wall_w and el < 0.95 * hl


def solve_tube(model) -> bool:
    """Set one common angle on all wall folds so the tube closes. True if changed/solved."""
    order = _chain(model)
    if len(order) < 3:
        return False
    hinges = [_hinge_between(model, a, b) for a, b in zip(order, order[1:])]
    if any(h is None or h.locked for h in hinges):
        return False
    first, last = order[0], order[-1]
    e1, w1 = _outer_edge(model, first, hinges[0])
    e2, w2 = _outer_edge(model, last, hinges[-1])
    if e1 is None or e2 is None:
        return False
    widths = []
    for i in range(1, len(order) - 1):
        u = np.array(hinges[i].p1) - np.array(hinges[i].p0)
        v = np.array(hinges[i - 1].p0) - np.array(hinges[i].p0)
        widths.append(abs(u[0] * v[1] - u[1] * v[0]) / max(1e-9, np.linalg.norm(u)))
    # a glue flap is narrower than every real wall - including the narrow side panels
    # (a carton without a glue flap often ends on a narrow side panel)
    g1 = _looks_like_glue(e1, hinges[0], w1, min(widths + [w2]))
    g2 = _looks_like_glue(e2, hinges[-1], w2, min(widths + [w1]))
    sides = len(order) - (1 if (g1 or g2) else 0)
    # a narrow end panel is the glue flap: it lies inside the other end wall, so the
    # other end's free edge has to reach the glue flap's hinge
    if g1 and (w1 <= w2 or not g2):
        owner_a, target_a = order[1], (np.array(hinges[0].p0), np.array(hinges[0].p1))
        owner_b, target_b = last, e2
    elif g2:
        owner_a, target_a = order[-2], (np.array(hinges[-1].p0), np.array(hinges[-1].p1))
        owner_b, target_b = first, e1
    else:
        owner_a, target_a = first, e1
        owner_b, target_b = last, e2
    saved = {h.id: h.angle for h in hinges}

    def gap(theta):
        for h in hinges:
            h.angle = theta
        Ms = fold3d.face_transforms(model, 1.0)
        A = (_world(Ms[owner_a], target_a[0]), _world(Ms[owner_a], target_a[1]))
        B = (_world(Ms[owner_b], target_b[0]), _world(Ms[owner_b], target_b[1]))
        return _seg_gap(A, B)

    # one turn around the tube: n sides -> 360/n (90 box, 60 hexagon, 120 triangle);
    # search near it so the walls never wrap round twice
    base = 360.0 / sides
    grid = np.arange(max(5.0, base - 30), min(175.0, base + 30) + 0.01, 0.5)
    vals = [gap(t) for t in grid]
    t = float(grid[int(np.argmin(vals))])
    lo, hi = t - 1, t + 1
    for _ in range(40):                               # golden-section refine
        m1, m2 = lo + (hi - lo) * 0.382, lo + (hi - lo) * 0.618
        if gap(m1) < gap(m2):
            hi = m2
        else:
            lo = m1
    t = round((lo + hi) / 2, 1)
    # the exact turn (90 for four sides) wins when the tube closes there as well: a glue
    # flap drawn a little narrow or tapered must not tilt every wall by a degree
    if abs(t - base) < 8.0 and gap(base) <= max(gap(t) + 0.2, 0.015 * _size(model)):
        t = base
    g = gap(t)
    if g > 0.03 * _size(model):
        for h in hinges:
            h.angle = saved[h.id]
        return False
    model.tube_sides = sides
    # remembered so the check can tell later whether the tube still closes
    model.tube_seam = (owner_a, tuple(map(tuple, target_a)), owner_b, tuple(map(tuple, target_b)),
                       tuple(order))
    return True


# ---------------------------------------------------------------- 2. pairing optimiser

def _normal(Ms, fid):
    return Ms[fid][:3, :3] @ np.array([0.0, 0.0, 1.0])


def _pairs(model, Ms, max_d):
    """Free edges of different panels that should meet: same length, nearly parallel,
    already fairly close, and on panels that are not lying flat on each other."""
    segs = []
    for f in model.faces:
        if f.small:
            continue
        for a, b in _free_segments(model, f.id):
            segs.append((f.id, a, b, np.linalg.norm(b - a)))
    cand = []
    for i in range(len(segs)):
        fi, a, b, la = segs[i]
        A = (_world(Ms[fi], a), _world(Ms[fi], b))
        for j in range(i + 1, len(segs)):
            fj, c, d, lc = segs[j]
            if fj == fi or not (0.8 <= la / lc <= 1.25):
                continue
            pi, pj = model.faces[fi].parent, model.faces[fj].parent
            if pi == fj or pj == fi:
                continue
            if abs(float(_normal(Ms, fi) @ _normal(Ms, fj))) > 0.985:
                continue                              # stacked flaps overlap, they don't meet
            B = (_world(Ms[fj], c), _world(Ms[fj], d))
            ua, ub = A[1] - A[0], B[1] - B[0]
            cosang = abs(float(ua @ ub)) / max(1e-9, np.linalg.norm(ua) * np.linalg.norm(ub))
            if cosang < math.cos(math.radians(50)):
                continue
            g = _seg_gap(A, B)
            if g < min(max_d, 0.35 * min(la, lc)):
                cand.append((g, i, j))
    cand.sort()
    used, pairs = set(), []
    for g, i, j in cand:
        if i in used or j in used:
            continue
        used.update((i, j))
        pairs.append((segs[i], segs[j]))
    return pairs


def solve_pairs(model, iterations=6, fixed=()) -> int:
    """Nudge fold angles so free edges that should meet do meet. Returns pairs used."""
    size = _size(model)
    Ms = fold3d.face_transforms(model, 1.0)
    pairs = _pairs(model, Ms, 0.18 * size)
    if not pairs:
        return 0
    fixed = set(fixed)
    vars_ = [fd for fd in model.folds
             if not model.faces[fd.child].small and fd.id not in fixed and not fd.locked]
    init = {fd.id: fd.angle for fd in vars_}

    def energy():
        Ms = fold3d.face_transforms(model, 1.0)
        e = 0.0
        for (fa, a, b, _), (fc, c, d, _) in pairs:
            g = _seg_gap((_world(Ms[fa], a), _world(Ms[fa], b)), (_world(Ms[fc], c), _world(Ms[fc], d)))
            e += (g / size) ** 2
        reg = sum(((fd.angle - init[fd.id]) / 90.0) ** 2 for fd in vars_)
        return e + 2e-3 * reg

    e0 = best = energy()
    if e0 < 1e-6 * len(pairs):                        # already closed
        return len(pairs)
    deadline = getattr(model, "deadline", None)

    def late():
        return deadline is not None and time.monotonic() > deadline
    for step in (16, 8, 4, 2, 1, 0.5, 0.25)[:iterations + 1]:
        improved = True
        while improved and not late():
            improved = False
            for fd in vars_:
                if late():
                    break
                for s in (step, -step):
                    old = fd.angle
                    fd.angle = max(-179.0, min(179.0, old + s))
                    e = energy()
                    if e < best - 1e-12:
                        best, improved = e, True
                    else:
                        fd.angle = old
    for fd in vars_:
        fd.angle = round(fd.angle, 1)
    if best > e0 * 0.98:                              # nothing worth changing
        for fd in vars_:
            fd.angle = init[fd.id]
    return len(pairs)


def gaps(model):
    """Mean and worst gap (pt) between paired edges at full fold — a closing check."""
    Ms = fold3d.face_transforms(model, 1.0)
    pairs = _pairs(model, Ms, 0.18 * _size(model))
    if not pairs:
        return 0.0, 0.0
    gs = [_seg_gap((_world(Ms[fa], a), _world(Ms[fa], b)), (_world(Ms[fc], c), _world(Ms[fc], d)))
          for (fa, a, b, _), (fc, c, d, _) in pairs]
    return float(np.mean(gs)), float(np.max(gs))


def _set_floor(model):
    """Trays, pyramids and cube nets lie on their base (no tube of walls)."""
    root = model.faces[model.root]
    big_children = [c for c in root.children if not model.faces[c].small]
    model.floor = model.tube_sides == 0 and len(big_children) >= 3


def auto_close(model) -> str:
    """Fold like ArtiosCAD's "fold all": every crease 90 degrees. Other readings of the
    die (a polygon tube at 360/n, free edges nudged until they meet) are tried as well
    and the one that gives the best box wins; 90 degrees wins ties. Returns a report."""
    from . import check

    def state():
        return ({fd.id: fd.angle for fd in model.folds}, model.tube_sides,
                getattr(model, "tube_seam", None))

    def restore(st):
        for fd in model.folds:
            fd.angle = st[0][fd.id]
        model.tube_sides, model.tube_seam = st[1], st[2]
        _set_floor(model)

    model.tube_sides, model.tube_seam = 0, None
    _set_floor(model)
    square = state()
    tube = solve_tube(model)
    order = _chain(model) if tube else []
    hinges = [h for h in (_hinge_between(model, a, b) for a, b in zip(order, order[1:])) if h]
    cands = []                                   # (rank, label, state, fixed hinges)
    if tube and all(abs(h.angle - 90.0) < 0.05 for h in hinges):
        # an ordinary box: the tube closes with square folds
        _set_floor(model)
        cands.append((check.rank(model), f"тръба с {model.tube_sides} стени, ъгъл 90°; всички сгъвки на 90°",
                      state(), [h.id for h in hinges]))
    else:
        tubed = state() if tube else None
        restore(square)
        cands.append((check.rank(model), "всички сгъвки на 90°", square, []))
        if tubed is not None:
            restore(tubed)
            cands.append((check.rank(model), f"тръба с {model.tube_sides} стени, ъгъл {hinges[0].angle:g}°",
                          tubed, [h.id for h in hinges]))

    def best():
        b = cands[0]
        for c in cands[1:]:
            if check.better(c[0], b[0], model):
                b = c
        return b

    deadline = getattr(model, "deadline", None)
    if best()[0][0] > 0 and not (deadline is not None and time.monotonic() > deadline):
        # still wrong: bring free edges together, from each starting point
        for rank, label, st, fixed in list(cands):
            restore(st)
            n = solve_pairs(model, fixed=fixed)
            if not n:
                continue
            r = check.rank(model)
            if r[0] < rank[0] - 0.5:
                _, worst = gaps(model)
                head = label.split(";")[0] + "; " if fixed else ""
                cands.append((r, f"{head}{n} срещащи се ръба, разлика до {worst * 25.4 / 72:.1f} mm",
                              state(), fixed))
    rank, label, st, fixed = best()
    restore(st)
    model.close_rank = rank
    return label
