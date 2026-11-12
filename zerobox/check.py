"""Check a folded box for things a real box can't do, and repair fold angles. Qt-free.

Issues found at full fold:
* a panel sticking out of the box body (a lid tilted like a roof, a flap folded outwards)
* two panels passing through each other
* a seam that should close but stays open
The repair tries simple alternatives (all folds square, then 90 / -90 / 180 / 0 on each
offending fold) and keeps whatever leaves the fewest problems."""
from __future__ import annotations

import time

from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import MultiPoint, Point

from . import fold3d

MM = 25.4 / 72


@dataclass
class Issue:
    kind: str                       # "sticks_out" | "crosses" | "open_seam"
    faces: list = field(default_factory=list)
    fold: int = -1                  # fold to look at (the offending panel's hinge)
    amount: float = 0.0             # pt
    text: str = ""


def _size(model):
    x0, y0, x1, y1 = model.bbox
    return max(x1 - x0, y1 - y0)


def _world_pts(Ms, face):
    return fold3d.world_points(Ms[face.id], fold3d.face_points(face))


def _body(model, Ms):
    """Prism spanned by the walls: (axis, cross-section polygon, (h0, h1)) or None."""
    walls = [model.faces[f] for f in getattr(model, "walls", ()) if not model.faces[f].small]
    if len(walls) < 3 or getattr(model, "floor", False):
        return None
    hinge = None
    for f in walls:
        if f.fold >= 0 and model.folds[f.fold].parent in model.walls:
            hinge = model.folds[f.fold]
            break
    if hinge is None:
        return None
    M = Ms[hinge.parent]
    a = (M @ np.array([hinge.p0[0], -hinge.p0[1], 0.0, 1.0]))[:3]
    b = (M @ np.array([hinge.p1[0], -hinge.p1[1], 0.0, 1.0]))[:3]
    u = (b - a) / max(1e-9, np.linalg.norm(b - a))
    # two axes across the tube
    t = np.array([1.0, 0, 0]) if abs(u[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(u, t)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(u, e1)
    pts = np.vstack([_world_pts(Ms, f) for f in walls])
    hull = MultiPoint([(float(p @ e1), float(p @ e2)) for p in pts]).convex_hull
    hs = pts @ u
    return u, e1, e2, hull, (float(hs.min()), float(hs.max()))


def _sticking_out(model, Ms, body, tol):
    u, e1, e2, hull, (h0, h1) = body
    if hull.geom_type != "Polygon" or hull.area <= 0:
        return []
    out = []
    walls = set(model.walls)
    for f in model.faces:
        if f.id in walls or (f.small and not getattr(f, "tab", False)):
            continue
        pts = _world_pts(Ms, f)
        worst = 0.0
        for p in pts:
            q = Point(float(p @ e1), float(p @ e2))
            d = 0.0 if hull.covers(q) else hull.exterior.distance(q)
            h = float(p @ u)
            d = max(d, h0 - h, h - h1)
            worst = max(worst, d)
        if worst > tol:
            out.append(Issue("sticks_out", [f.id], f.fold, worst,
                             f"Панел {f.id + 1} стърчи извън кутията с {worst * MM:.0f} mm"))
    return out


def _crossing(model, Ms, tol):
    """Pairs of panels where an edge of one passes through the inside of the other."""
    big = [f for f in model.faces if not f.small or getattr(f, "tab", False)]
    near = {}
    for ek, a, b, state in getattr(model, "shared", []):
        ka, kb = ek.split("|")
        near.setdefault(ka, set()).add(kb)
        near.setdefault(kb, set()).add(ka)
    import shapely
    inv = {f.id: np.linalg.inv(Ms[f.id]) for f in big}
    world = {f.id: _world_pts(Ms, f) for f in big}
    shrunk = {f.id: f.poly.buffer(-tol) for f in big}
    centre = {f.id: world[f.id].mean(axis=0) for f in big}
    radius = {f.id: float(np.linalg.norm(world[f.id] - centre[f.id], axis=1).max()) for f in big}
    out, seen = [], set()
    for A in big:
        for B in big:
            if A.id == B.id or (min(A.id, B.id), max(A.id, B.id)) in seen:
                continue
            if B.key in near.get(A.key, ()) or A.parent == B.id or B.parent == A.id:
                continue
            if np.linalg.norm(centre[A.id] - centre[B.id]) > radius[A.id] + radius[B.id]:
                continue
            Minv = inv[B.id]
            n = Ms[B.id][:3, :3] @ np.array([0, 0, 1.0])
            o = Ms[B.id][:3, 3]
            pts = world[A.id]
            d = (pts - o) @ n
            if not ((d > tol).any() and (d < -tol).any()):
                continue
            hit = False
            k = len(pts)
            for i in range(k):
                j = (i + 1) % k
                if (d[i] > tol and d[j] < -tol) or (d[i] < -tol and d[j] > tol):
                    t = d[i] / (d[i] - d[j])
                    x = pts[i] + t * (pts[j] - pts[i])
                    loc = Minv @ np.array([x[0], x[1], x[2], 1.0])
                    if shapely.contains_xy(shrunk[B.id], loc[0], -loc[1]):
                        hit = True
                        break
            if hit:
                seen.add((min(A.id, B.id), max(A.id, B.id)))
                child = A if A.depth >= B.depth else B
                out.append(Issue("crosses", [A.id, B.id], child.fold, 0.0,
                                 f"Панели {A.id + 1} и {B.id + 1} минават един през друг"))
    return out


def _open_seams(model, Ms, tol):
    """Edges that met when the box was solved and are now apart (a wall left open)."""
    from . import solver
    out = []
    for (fa, a, b, _), (fc, c, d, _) in getattr(model, "seam_pairs", None) or []:
        g = solver._seg_gap((solver._world(Ms[fa], a), solver._world(Ms[fa], b)),
                            (solver._world(Ms[fc], c), solver._world(Ms[fc], d)))
        if g > tol * 2:
            out.append(Issue("open_seam", [fa, fc], -1, g,
                             f"Ръбът между панели {fa + 1} и {fc + 1} остава отворен с {g * MM:.0f} mm"))
    return out


def _dangling(model, Ms, tol):
    """A panel whose free edges touch nothing: it only hangs on its hinge (a wall left
    open like a book, a lid standing up). Works without knowing how the box should close."""
    import shapely
    from . import solver
    big = [f for f in model.faces if not f.small]
    pts, owner = [], []
    for f in big:
        if f.parent < 0:
            continue
        segs = list(solver._free_segments(model, f.id))
        # an edge that carries another panel or a glue tab counts too: the panel is
        # held there if that edge lies against something
        for c in f.children:
            cf = model.folds[model.faces[c].fold]
            segs.append((np.array(cf.p0), np.array(cf.p1)))
        for a, b in segs:
            for t in (0.4, 0.5, 0.6):          # middle of the edge: corners always touch
                pts.append(solver._world(Ms[f.id], a + (b - a) * t))
                owner.append(f.id)
    if not pts:
        return []
    P = np.c_[np.array(pts), np.ones(len(pts))]
    owner = np.array(owner)
    held = set()
    for g in big:
        loc = (np.linalg.inv(Ms[g.id]) @ P.T).T
        x0, y0, x1, y1 = g.poly.bounds
        cand = ((owner != g.id) & (np.abs(loc[:, 2]) <= tol)
                & (loc[:, 0] >= x0 - tol) & (loc[:, 0] <= x1 + tol)
                & (-loc[:, 1] >= y0 - tol) & (-loc[:, 1] <= y1 + tol))
        idx = np.nonzero(cand)[0]
        if not len(idx):
            continue
        d_in = shapely.distance(g.poly, shapely.points(loc[idx, 0], -loc[idx, 1]))
        ok = np.hypot(loc[idx, 2], d_in) <= tol
        held.update(int(o) for o in owner[idx[ok]])
    out = []
    for fid in dict.fromkeys(int(o) for o in owner):
        if fid not in held:
            f = model.faces[fid]
            out.append(Issue("dangling", [f.id], f.fold, 0.0,
                             f"Панел {f.id + 1} виси свободно — не опира в друг панел"))
    return out


def _open_tube(model, Ms, tol):
    """The walls of a tube box must come round to the glue flap / first wall."""
    seam = getattr(model, "tube_seam", None)
    if not seam:
        return []
    from . import solver
    oa, (a0, a1), ob, (b0, b1), order = seam
    g = solver._seg_gap((solver._world(Ms[oa], np.array(a0)), solver._world(Ms[oa], np.array(a1))),
                        (solver._world(Ms[ob], np.array(b0)), solver._world(Ms[ob], np.array(b1))))
    if g > tol * 2:
        return [Issue("open_seam", list(order), -1, g, f"Стените не се затварят в кутия (разлика {g * MM:.0f} mm)")]
    return []


def _flat_overlap(Ms, a, b, tol):
    """Area two panels share when they lie in one plane, else 0."""
    na = Ms[a.id][:3, :3] @ np.array([0.0, 0.0, 1.0])
    nb = Ms[b.id][:3, :3] @ np.array([0.0, 0.0, 1.0])
    if abs(float(na @ nb)) < 0.999 or abs(float(na @ (Ms[b.id][:3, 3] - Ms[a.id][:3, 3]))) > tol:
        return 0.0
    from shapely.geometry import Polygon
    T = np.linalg.inv(Ms[a.id]) @ Ms[b.id]              # b's outline in a's flat coordinates
    cs = np.array(b.poly.exterior.coords)
    h = (T @ np.c_[cs[:, 0], -cs[:, 1], np.zeros(len(cs)), np.ones(len(cs))].T).T
    try:
        q = Polygon(np.c_[h[:, 0], -h[:, 1]])
        if not q.is_valid:
            q = q.buffer(0)
        return a.poly.intersection(q).area
    except Exception:                                   # noqa: BLE001 - a degenerate panel
        return 0.0


def _wound(model, Ms, tol):
    """Two walls of about the same size lying on each other: the tube goes round more
    than once (a hexagon folded with square corners). The two end panels of the row may
    overlap (glue flap, the front flap of a mailer lid over the front wall)."""
    from . import solver
    order = solver._chain(model)
    if len(order) < 4:
        return []
    ends = {order[0], order[-1]}
    walls = [model.faces[f] for f in order if not model.faces[f].small]
    out = []
    for i, a in enumerate(walls):
        for b in walls[i + 1:]:
            if a.id in ends and b.id in ends:
                continue                    # the two ends meet: that is how a tube closes
            small, large = (a, b) if a.area <= b.area else (b, a)
            if small.area < 0.6 * large.area:
                continue
            if _flat_overlap(Ms, a, b, tol) > 0.6 * small.area:
                out.append(Issue("wound", [a.id, b.id], small.fold, 0.0,
                                 f"Стени {a.id + 1} и {b.id + 1} лягат една върху друга — кутията се навива"))
    return out


def analyze(model) -> list:
    if model is None or not model.faces:
        return []
    Ms = fold3d.face_transforms(model, 1.0)
    size = _size(model)
    tol = max(2.0, 0.012 * size)
    issues = []
    body = _body(model, Ms)
    if body is not None:
        issues += _sticking_out(model, Ms, body, tol)
    issues += _crossing(model, Ms, max(1.0, 0.004 * size))
    issues += _open_seams(model, Ms, tol)
    issues += _dangling(model, Ms, max(3.0, 0.012 * size))
    issues += _open_tube(model, Ms, tol)
    issues += _wound(model, Ms, tol)
    return issues


def score(issues) -> float:
    s = 0.0
    for i in issues:
        if i.kind == "crosses":
            s += 1000.0
        elif i.kind in ("dangling", "wound"):
            s += 500.0
        elif i.kind == "sticks_out":
            s += 300.0 + i.amount
        else:
            s += 100.0 + i.amount
    return s


def repair(model, protected=()) -> str:
    """Change fold angles until the box has as few issues as possible. Folds whose key is
    in `protected` (set by hand) are never touched. Returns a short report."""
    issues = analyze(model)
    if not issues:
        return ""
    best = score(issues)
    start = {fd.id: fd.angle for fd in model.folds}
    free = {fd.id for fd in model.folds
            if not fd.locked and fd.key not in protected and fold3d_angle_ok(model, fd)}

    def snapshot():
        return {fd.id: fd.angle for fd in model.folds}

    def restore(snap):
        for fd in model.folds:
            fd.angle = snap[fd.id]

    # 1. whole-box alternatives: the solver's angles, then every real fold square
    #    (tube walls keep their solved angle)
    tube_hinges = set()
    if getattr(model, "tube_sides", 0):
        tube_hinges = {fd.id for fd in model.folds if fd.child in model.walls and fd.parent in model.walls}
    deadline = getattr(model, "deadline", None)

    def late():
        return deadline is not None and time.monotonic() > deadline
    for variant in ("solved", "square"):
        if late():
            break
        snap = snapshot()
        for fid in free:
            fd = model.folds[fid]
            if variant == "solved":
                fd.angle = fd.solved
            elif fid not in tube_hinges and not model.faces[fd.child].small:
                fd.angle = 90.0
        s = score(analyze(model))
        if s < best - 1e-6:
            best = s
        else:
            restore(snap)
    # 2. try the usual alternatives on the hinge of each offending panel (or the nearest
    #    hinge above it that may be changed)
    for _ in range(3):
        issues = analyze(model)
        if not issues:
            break
        improved = False
        targets = []
        for i in issues:
            for fid in i.faces:
                # the panel's own hinge and up to three hinges above it
                f = model.faces[fid]
                found = 0
                while f.fold >= 0 and found < 4:
                    if f.fold in free and f.fold not in targets:
                        targets.append(f.fold)
                        found += 1
                    f = model.faces[model.folds[f.fold].parent]
        for fid in targets:
            fd = model.folds[fid]
            keep = fd.angle
            for a in dict.fromkeys((fd.solved, 90.0, -90.0, 180.0, 0.0, 135.0, 45.0)):
                if a == keep or late():
                    continue
                fd.angle = a
                s = score(analyze(model))
                if s < best - 1e-6:
                    best, keep, improved = s, a, True
            fd.angle = keep
        if not improved:
            break
    changed = [fd for fd in model.folds if abs(fd.angle - start[fd.id]) > 0.01]
    left = analyze(model)
    if not changed:
        return ""
    msg = f"проверката поправи {len(changed)} сгъвк" + ("а" if len(changed) == 1 else "и")
    if left:
        msg += f", остават {len(left)} нередности"
    return msg


def fold3d_angle_ok(model, fd) -> bool:
    """Folds of hair-thin strips are not worth changing."""
    f = model.faces[fd.child]
    return not (f.small and not getattr(f, "tab", False))


# ---------------------------------------------------------------- how well the box closes

def open_length(model, Ms=None) -> float:
    """How much of the panels' cut edges (pt) touches no other panel in the folded box:
    a closed box has none, a tray only its rim. Used to choose between different ways
    of reading the same die."""
    import shapely
    from . import solver
    if Ms is None:
        Ms = fold3d.face_transforms(model, 1.0)
    size = _size(model)
    tol = max(0.3, 0.008 * size)
    step = max(1.0, size / 80.0)
    big = [f for f in model.faces if not f.small or getattr(f, "tab", False)]
    pts, owner, weight = [], [], []
    for f in big:
        if f.small:
            continue
        for a, b in solver._free_segments(model, f.id):
            L = float(np.linalg.norm(b - a))
            n = max(3, int(L / step))
            for k in range(n):
                q = a + (b - a) * ((k + 0.5) / n)
                pts.append(solver._world(Ms[f.id], q))
                owner.append(f.id)
                weight.append(L / n)
    open_len = 0.0
    if pts:
        P = np.c_[np.array(pts), np.ones(len(pts))]
        owner = np.array(owner)
        touched = np.zeros(len(pts), dtype=bool)
        for g in big:
            loc = (np.linalg.inv(Ms[g.id]) @ P.T).T
            x0, y0, x1, y1 = g.poly.bounds
            cand = ((owner != g.id) & ~touched & (np.abs(loc[:, 2]) <= tol)
                    & (loc[:, 0] >= x0 - tol) & (loc[:, 0] <= x1 + tol)
                    & (-loc[:, 1] >= y0 - tol) & (-loc[:, 1] <= y1 + tol))
            idx = np.nonzero(cand)[0]
            if len(idx):
                d = shapely.distance(g.poly, shapely.points(loc[idx, 0], -loc[idx, 1]))
                touched[idx[d <= tol]] = True
        open_len = float(np.array(weight)[~touched].sum())
    return open_len


def rank(model):
    """(issue score, open length) - smaller is a better box."""
    return score(analyze(model)), open_length(model)


def better(a, b, model) -> bool:
    """Is rank a clearly better than rank b? Small differences don't count, so the
    plain reading of a die wins ties."""
    size = _size(model)
    if abs(a[0] - b[0]) > 0.5:
        return a[0] < b[0]
    if abs(a[1] - b[1]) > max(0.04 * size, 0.15 * max(a[1], b[1])):
        return a[1] < b[1]
    return False
