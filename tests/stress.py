"""Stress run: many box styles x many ways of drawing them. Run  py tests/stress.py [filter]

Every case must fold without an exception, quickly, with no issues from the checker and
with the expected outer size. Prints one line per failing case and a summary."""
import math
import os
import random
import sys
import time
import traceback

from shapely.geometry import LineString, Polygon
from shapely.ops import linemerge, unary_union

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dies  # noqa: E402
from zerobox import fold3d, geometry  # noqa: E402
from zerobox.dieline import Stroke  # noqa: E402

R = dies.rect
P = dies.poly


# ------------------------------------------------------------------ box styles (closed panels)

def tuck_end(L=120.0, W=60.0, H=180.0, glue=18.0, tuck=14.0, reverse=False, dust=None, taper=6.0):
    """Folding carton: 4 walls + glue flap, lid with tuck flap top and bottom, dust flaps."""
    x0, y0 = 100.0, 200.0
    xs = [x0, x0 + L, x0 + L + W, x0 + 2 * L + W, x0 + 2 * L + 2 * W]
    d = W / 2 if dust is None else dust
    out = [P((x0 - glue, y0 + taper), (x0, y0), (x0, y0 + H), (x0 - glue, y0 + H - taper))]
    for i in range(4):
        out.append(R(xs[i], y0, xs[i + 1], y0 + H))
    for top, wall in ((True, 0), (False, 2 if reverse else 0)):
        a, b = xs[wall], xs[wall + 1]
        if top:
            out.append(R(a, y0 - W, b, y0))
            out.append(P((a, y0 - W), (b, y0 - W), (b - 3, y0 - W - tuck), (a + 3, y0 - W - tuck)))
        else:
            out.append(R(a, y0 + H, b, y0 + H + W))
            out.append(P((a, y0 + H + W), (b, y0 + H + W), (b - 3, y0 + H + W + tuck), (a + 3, y0 + H + W + tuck)))
    for wall in (1, 3):
        a, b = xs[wall], xs[wall + 1]
        out.append(P((a, y0), (b, y0), (b - taper, y0 - d), (a + taper, y0 - d)))
        out.append(P((a, y0 + H), (b, y0 + H), (b - taper, y0 + H + d), (a + taper, y0 + H + d)))
    return out, (L, W, H)


def sleeve(L=150.0, W=40.0, H=100.0, glue=14.0):
    x0, y0 = 100.0, 100.0
    xs = [x0, x0 + L, x0 + L + W, x0 + 2 * L + W, x0 + 2 * L + 2 * W]
    out = [R(x0 - glue, y0, x0, y0 + H)] if glue else []
    out += [R(xs[i], y0, xs[i + 1], y0 + H) for i in range(4)]
    return out, (L, W, H)


def tray(L=200.0, W=140.0, H=40.0, tabs=True, tab=30.0):
    """Base + 4 walls; corner glue tabs on the short walls."""
    x0, y0 = 150.0, 150.0
    x1, y1 = x0 + L, y0 + W
    out = [R(x0, y0, x1, y1), R(x0, y0 - H, x1, y0), R(x0, y1, x1, y1 + H),
           R(x0 - H, y0, x0, y1), R(x1, y0, x1 + H, y1)]
    if tabs:
        t = min(tab, H * 0.9)
        for x, sgn in ((x0 - H, 1), (x1, 1)):
            out.append(P((x, y0), (x + H, y0), (x + H - 3, y0 - t), (x + 3, y0 - t)))
            out.append(P((x, y1), (x + H, y1), (x + H - 3, y1 + t), (x + 3, y1 + t)))
    return out, (L, W, H)


def mailer(L=220.0, W=160.0, H=50.0, front=40.0, ears=True):
    """Tray whose back wall carries a lid with a front flap (pizza / mailer box)."""
    x0, y0 = 150.0, 400.0
    x1, y1 = x0 + L, y0 + W
    out = [R(x0, y0, x1, y1), R(x0, y1, x1, y1 + H), R(x0 - H, y0, x0, y1), R(x1, y0, x1 + H, y1),
           R(x0, y0 - H, x1, y0),                               # back wall
           R(x0, y0 - H - W, x1, y0 - H),                       # lid
           R(x0, y0 - H - W - front, x1, y0 - H - W)]           # lid front flap
    if ears:
        out.append(R(x0 - front, y0 - H - W, x0, y0 - H))
        out.append(R(x1, y0 - H - W, x1 + front, y0 - H))
    return out, (L, W, H)


def cube_net(kind=0, s=100.0):
    nets = [
        [(1, 0), (0, 1), (1, 1), (2, 1), (3, 1), (1, 2)],          # cross
        [(0, 0), (0, 1), (1, 1), (2, 1), (3, 1), (3, 2)],          # Z-like
        [(0, 0), (1, 0), (1, 1), (2, 1), (2, 2), (3, 2)],          # stairs
        [(0, 0), (1, 0), (2, 0), (2, 1), (3, 1), (4, 1)],          # 3 + 3
        [(0, 1), (1, 1), (2, 1), (3, 1), (0, 0), (0, 2)],          # T ends
        [(1, 0), (0, 1), (1, 1), (2, 1), (3, 1), (2, 2)],
    ]
    out = [R(50 + cx * s, 50 + cy * s, 50 + cx * s + s, 50 + cy * s + s) for cx, cy in nets[kind]]
    return out, (s, s, s)


def prism_caps(n=3, w=90.0, h=160.0, glue=16.0):
    out = dies.tube(n, w=w, h=h, glue=glue, lids=True)
    r = w / (2 * math.sin(math.pi / n))
    a = w / (2 * math.tan(math.pi / n))
    if n % 2 == 0:
        dims = (2 * a if n % 4 == 0 else 2 * r, 2 * a, h) if n == 4 else None
    else:
        dims = None
    return out, dims


def frustum(n=4, bottom=120.0, top=80.0, h=140.0, base=True):
    """Base polygon with n trapezoid walls leaning inwards (truncated pyramid, open top)."""
    return dies.sloped_tray(L=bottom, W=bottom, h=h, flare=-(bottom - top) / 2), None


def two_piece(L=180.0, W=120.0, H=35.0):
    """Telescope box: a base tray and a slightly larger lid tray in one file."""
    a, _ = tray(L, W, H, tabs=False)
    b, _ = tray(L + 4, W + 4, H - 5, tabs=False)
    dx = L + 2 * H + 80
    b = [Stroke([(x + dx, y) for x, y in s.pts], True) for s in b]
    return a + b, None


def window_box(L=120.0, W=60.0, H=180.0):
    out, dims = tuck_end(L, W, H)
    x0, y0 = 100.0, 200.0
    out.append(R(x0 + 25, y0 + 40, x0 + L - 25, y0 + H - 60))          # window in the front
    return out, dims


def hang_tab_box(L=100.0, W=40.0, H=150.0):
    """Tuck box whose back wall continues up into a hang tab with a euro hole."""
    out, dims = tuck_end(L, W, H, reverse=True)
    x0, y0 = 100.0, 200.0
    a = x0 + L + W
    out.append(R(a, y0 - 50, a + L, y0))
    cx = a + L / 2
    out.append(P(*[(cx + 6 * math.cos(t / 12 * 2 * math.pi), y0 - 30 + 6 * math.sin(t / 12 * 2 * math.pi))
                   for t in range(12)]))
    return out, None


STYLES = {
    "tuck_straight": lambda: tuck_end(),
    "tuck_reverse": lambda: tuck_end(reverse=True),
    "tuck_flat": lambda: tuck_end(L=200, W=30, H=120),
    "tuck_tall": lambda: tuck_end(L=50, W=50, H=260),
    "tuck_wide": lambda: tuck_end(L=260, W=180, H=60, tuck=20),
    "tuck_big_dust": lambda: tuck_end(dust=58.0),
    "sleeve": lambda: sleeve(),
    "sleeve_noglue": lambda: sleeve(glue=0),
    "sleeve_square": lambda: sleeve(L=80, W=80, H=200),
    "tray": lambda: tray(),
    "tray_notabs": lambda: tray(tabs=False),
    "tray_deep": lambda: tray(L=120, W=100, H=110),
    "tray_shallow": lambda: tray(L=300, W=200, H=14, tab=12),
    "mailer": lambda: mailer(),
    "mailer_noears": lambda: mailer(ears=False),
    "rsc": lambda: (sum(dies.rsc_groups(), []), (200, 120, 150)),
    "rsc_noglue": lambda: (sum(dies.rsc_groups(glue=0), []), (200, 120, 150)),
    "rsc_full_overlap": lambda: (sum(dies.rsc_groups(L=320, W=123, H=350, flap=123), []), (320, 123, 350)),
    "rsc_cube": lambda: (sum(dies.rsc_groups(L=150, W=150, H=150), []), (150, 150, 150)),
    "rsc_flat": lambda: (sum(dies.rsc_groups(L=400, W=300, H=40), []), (400, 300, 40)),
    "cube0": lambda: cube_net(0), "cube1": lambda: cube_net(1), "cube2": lambda: cube_net(2),
    "cube3": lambda: cube_net(3), "cube4": lambda: cube_net(4), "cube5": lambda: cube_net(5),
    "tube3": lambda: (dies.tube(3, w=90), None), "tube5": lambda: (dies.tube(5), None),
    "tube6": lambda: (dies.tube(6), None), "tube8": lambda: (dies.tube(8, w=40), None),
    "prism3": lambda: prism_caps(3), "prism4": lambda: prism_caps(4), "prism5": lambda: prism_caps(5),
    "prism6": lambda: prism_caps(6), "prism8": lambda: prism_caps(8, w=45),
    "pyramid": lambda: (dies.pyramid(), None),
    "pyramid_low": lambda: (dies.pyramid(h=75), None),
    "sloped_tray": lambda: (dies.sloped_tray(), None),
    "frustum": lambda: frustum(),
    "two_piece": lambda: two_piece(),
    "window": lambda: window_box(),
    "hang_tab": lambda: hang_tab_box(),
}


# ------------------------------------------------------------------ ways of drawing

def _classify(strokes):
    """(cut lines, crease lines) as merged polylines, from closed panels."""
    polys = [Polygon(s.pts) for s in strokes if s.closed and len(s.pts) >= 3]
    opens = [LineString(s.pts) for s in strokes if not s.closed]
    if opens:                               # already drawn as lines (rsc): keep as is
        return None
    noded = unary_union([p.exterior for p in polys])
    cut, crease = [], []
    for seg in getattr(noded, "geoms", [noded]):
        mid = seg.interpolate(0.5, normalized=True)
        n = sum(1 for p in polys if p.exterior.distance(mid) < 1e-6)
        (crease if n >= 2 else cut).append(seg)

    def merged(segs):
        if not segs:
            return []
        m = linemerge(segs)
        return [Stroke([(x, y) for x, y in g.coords], False) for g in getattr(m, "geoms", [m])]
    return merged(cut), merged(crease)


def as_closed(strokes, rnd):
    return strokes, None


def as_cut_crease(strokes, rnd):
    cc = _classify(strokes)
    if cc is None:
        return strokes, None
    return cc[0] + cc[1], cc[1]


def as_one_colour(strokes, rnd):
    cc = _classify(strokes)
    if cc is None:
        return strokes, None
    return cc[0] + cc[1], None


def as_segments(strokes, rnd):
    """Every edge its own 2-point line, in random order and direction."""
    cc = _classify(strokes)
    lines = (cc[0] + cc[1]) if cc else strokes
    out = []
    for s in lines:
        pts = s.pts + ([s.pts[0]] if s.closed else [])
        for a, b in zip(pts, pts[1:]):
            out.append(Stroke([a, b] if rnd.random() < 0.5 else [b, a], False))
    rnd.shuffle(out)
    return out, None


def as_gappy(strokes, rnd):
    """Lines that stop a fraction of a point short of each other (sloppy drawing)."""
    lines, fl = as_segments(strokes, rnd)
    out = []
    for s in lines:
        (ax, ay), (bx, by) = s.pts
        d = math.hypot(bx - ax, by - ay)
        if d < 8:
            out.append(s)
            continue
        k0, k1 = rnd.uniform(0, 0.4) / d, rnd.uniform(0, 0.4) / d
        out.append(Stroke([(ax + (bx - ax) * k0, ay + (by - ay) * k0),
                           (bx - (bx - ax) * k1, by - (by - ay) * k1)], False))
    return out, None


def as_doubled(strokes, rnd):
    """Shared edges drawn twice (each panel a closed shape) plus a duplicate of everything."""
    return strokes + [Stroke(list(reversed(s.pts)), s.closed) for s in strokes], None


DRAWINGS = {"closed": as_closed, "cut_crease": as_cut_crease, "one_colour": as_one_colour,
            "segments": as_segments, "gappy": as_gappy, "doubled": as_doubled}


def transform(strokes, rot=0.0, scale=1.0, mirror=False):
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    out = []
    for st in strokes:
        pts = []
        for x, y in st.pts:
            if mirror:
                x = -x
            pts.append(((x * c - y * s) * scale + 3000, (x * s + y * c) * scale + 3000))
        out.append(Stroke(pts, st.closed))
    return out


TRANSFORMS = {"plain": {}, "rot90": {"rot": 90}, "rot180": {"rot": 180}, "rot33": {"rot": 33},
              "mirror": {"mirror": True}, "small": {"scale": 0.25}, "big": {"scale": 6.0},
              "rot270_mirror": {"rot": 270, "mirror": True}}


def run(filt=""):
    bad, n, slow = [], 0, []
    t_all = time.time()
    for sname, make in STYLES.items():
        for dname, draw in DRAWINGS.items():
            for tname, tf in TRANSFORMS.items():
                name = f"{sname}/{dname}/{tname}"
                if filt and filt not in name:
                    continue
                # the full grid is large: every style x drawing plain, every style x transform closed
                if not filt and dname != "closed" and tname not in ("plain", "rot33"):
                    continue
                n += 1
                rnd = random.Random(hash(name) & 0xffff)
                strokes, dims = make()
                strokes, fl = draw(strokes, rnd)
                ids = {id(s) for s in fl} if fl else set()
                idx = [i for i, s in enumerate(strokes) if id(s) in ids]
                strokes = transform(strokes, **tf)
                fl = [strokes[i] for i in idx] if fl else None
                scale = tf.get("scale", 1.0)
                t = time.time()
                try:
                    m = geometry.build(strokes, fold_lines=fl)
                except Exception as e:                                  # noqa: BLE001
                    bad.append((name, "EXC " + repr(e) + " @ " + traceback.format_exc().strip().splitlines()[-3].strip()))
                    continue
                dt = time.time() - t
                if dt > 3:
                    slow.append((name, round(dt, 1)))
                if m is None or len(m.faces) < 2:
                    bad.append((name, "NO MODEL"))
                    continue
                why = []
                if m.issues:
                    why.append("ISSUES " + "; ".join(sorted({i.kind for i in m.issues})) + f" x{len(m.issues)}")
                if dims is not None:
                    lo, hi = fold3d.bounds3d(m, fold3d.face_transforms(m, 1.0))
                    got = sorted(hi - lo)
                    want = sorted(d * scale for d in dims)
                    if any(abs(g - w) > 0.03 * w + 1.5 * scale for g, w in zip(got, want)):
                        why.append("SIZE got " + "x".join(f"{g / scale:.0f}" for g in got)
                                   + " want " + "x".join(f"{w / scale:.0f}" for w in want))
                if why:
                    bad.append((name, " | ".join(why) + f"  [{len(m.faces)} faces; {m.solve_report}; {m.check_report}]"))
    for name, why in bad:
        print("FAIL", name, "->", why)
    for name, dt in slow:
        print("SLOW", name, dt, "s")
    print(f"{n - len(bad)}/{n} ok, {len(bad)} failed, {len(slow)} slow, {time.time() - t_all:.0f}s")
    return bad


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "")
