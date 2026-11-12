"""Harder inputs: details real dies have, junk, degenerate shapes, random manual edits.
Run  py tests/stress2.py   - prints failures and a summary."""
import math
import os
import random
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dies  # noqa: E402
import stress  # noqa: E402
from zerobox import fold3d, geometry  # noqa: E402
from zerobox.dieline import Stroke  # noqa: E402

R, P = dies.rect, dies.poly


def arc(cx, cy, r, a0, a1, n=8):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * k / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * k / n))) for k in range(n + 1)]


def rounded_tuck(L=140.0, W=70.0, H=200.0, glue=18.0, tuck=18.0, r=10.0):
    """Tuck box whose tuck flaps and dust flaps have rounded corners."""
    x0, y0 = 100.0, 250.0
    xs = [x0, x0 + L, x0 + L + W, x0 + 2 * L + W, x0 + 2 * L + 2 * W]
    out = [P((x0 - glue, y0 + 8), (x0, y0), (x0, y0 + H), (x0 - glue, y0 + H - 8))]
    out += [R(xs[i], y0, xs[i + 1], y0 + H) for i in range(4)]
    for sgn, base in ((-1, y0), (1, y0 + H)):
        a, b = xs[0], xs[1]
        lid_y = base + sgn * W
        out.append(R(a, min(base, lid_y), b, max(base, lid_y)))
        ty = lid_y + sgn * tuck
        if sgn < 0:
            pts = [(a, lid_y)] + arc(a + r, ty + r, r, 180, 270) + arc(b - r, ty + r, r, 270, 360) + [(b, lid_y)]
        else:
            pts = [(a, lid_y)] + arc(a + r, ty - r, r, 180, 90) + arc(b - r, ty - r, r, 90, 0) + [(b, lid_y)]
        out.append(P(*pts))
        for wall in (1, 3):
            a, b = xs[wall], xs[wall + 1]
            d = W / 2
            ey = base + sgn * d
            if sgn < 0:
                pts = [(a, base)] + arc(a + r, ey + r, r, 180, 270) + arc(b - r, ey + r, r, 270, 360) + [(b, base)]
            else:
                pts = [(a, base)] + arc(a + r, ey - r, r, 180, 90) + arc(b - r, ey - r, r, 90, 0) + [(b, base)]
            out.append(P(*pts))
    return out, (L, W, H)


def thumb_notch_box():
    """Sleeve-like tuck box with a semicircular thumb notch cut into the front's top edge."""
    out, dims = stress.tuck_end(L=140, W=60, H=200)
    x0, y0 = 100.0, 200.0
    # front wall is out[1]: replace by a wall with a notch into its bottom edge
    L, H = 140.0, 200.0
    cx = x0 + L / 2
    notch = arc(cx, y0 + H, 14, 0, -180, 10)
    out[1] = P((x0, y0), (x0 + L, y0), (x0 + L, y0 + H), *notch, (x0, y0 + H))
    # the bottom lid hangs on that edge; give it the matching bulge-free straight edge
    return out, None


def double_wall_tray(L=220.0, W=160.0, H=40.0):
    """Tray whose long walls roll over: wall + inner wall folded back 180 degrees."""
    x0, y0 = 200.0, 200.0
    x1, y1 = x0 + L, y0 + W
    out = [R(x0, y0, x1, y1), R(x0, y0 - H, x1, y0), R(x0, y1, x1, y1 + H),
           R(x0 - H, y0, x0, y1), R(x1, y0, x1 + H, y1),
           R(x0, y0 - 2 * H + 2, x1, y0 - H), R(x0, y1 + H, x1, y1 + 2 * H - 2)]
    return out, None


def crash_lock(L=120.0, W=80.0, H=160.0, glue=16.0):
    """Tuck top, crash-lock (auto) bottom: bottom flaps with diagonal creases."""
    x0, y0 = 100.0, 200.0
    xs = [x0, x0 + L, x0 + L + W, x0 + 2 * L + W, x0 + 2 * L + 2 * W]
    out = [R(x0 - glue, y0, x0, y0 + H)]
    out += [R(xs[i], y0, xs[i + 1], y0 + H) for i in range(4)]
    out.append(R(xs[0], y0 - W, xs[1], y0))
    out.append(P((xs[0], y0 - W), (xs[1], y0 - W), (xs[1] - 4, y0 - W - 14), (xs[0] + 4, y0 - W - 14)))
    b = y0 + H
    d = W * 0.6
    for i in (0, 2):                      # big bottom flaps split by a diagonal crease
        a, c = xs[i], xs[i + 1]
        out.append(P((a, b), (c, b), (c - d, b + d), (a, b + d)))
        out.append(P((c, b), (c, b + d), (c - d, b + d)))
    for i in (1, 3):
        a, c = xs[i], xs[i + 1]
        out.append(P((a, b), (c, b), (c - 6, b + d * 0.8), (a + 6, b + d * 0.8)))
    return out, None


def with_junk(strokes, rnd):
    """The die plus things people leave in the same colour: a frame around it, dimension
    lines with arrow ticks, a text box, registration crosses."""
    xs = [p[0] for s in strokes for p in s.pts]
    ys = [p[1] for s in strokes for p in s.pts]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    out = list(strokes)
    out.append(Stroke([(x0, y1 + 30), (x1, y1 + 30)], False))                       # dimension line
    out.append(Stroke([(x0, y1 + 24), (x0, y1 + 36)], False))
    out.append(Stroke([(x1, y1 + 24), (x1, y1 + 36)], False))
    out.append(R(x1 + 40, y0, x1 + 140, y0 + 40))                                   # text box
    for cx, cy in ((x0 - 30, y0 - 30), (x1 + 30, y1 + 60)):                         # register marks
        out.append(Stroke([(cx - 8, cy), (cx + 8, cy)], False))
        out.append(Stroke([(cx, cy - 8), (cx, cy + 8)], False))
    return out


CASES = {
    "rounded_tuck": (rounded_tuck, True),
    "thumb_notch": (thumb_notch_box, True),
    "double_wall_tray": (double_wall_tray, True),
    "crash_lock": (crash_lock, False),          # needs no exception and a sane box, not perfection
}


def size_ok(m, dims, scale=1.0):
    lo, hi = fold3d.bounds3d(m, fold3d.face_transforms(m, 1.0))
    got, want = sorted(hi - lo), sorted(d * scale for d in dims)
    return all(abs(g - w) <= 0.03 * w + 1.5 * scale for g, w in zip(got, want)), got


def run():
    bad, n = [], 0
    t_all = time.time()

    def case(name, fn):
        nonlocal n
        n += 1
        t = time.time()
        try:
            why = fn()
        except Exception as e:                                          # noqa: BLE001
            why = "EXC " + repr(e) + " @ " + " <- ".join(
                ln.strip() for ln in traceback.format_exc().strip().splitlines()[-4:-1:2])
        dt = time.time() - t
        if not why and dt > (25 if name.startswith("manual") else 10 if name.startswith("degenerate") else 6):
            why = f"SLOW {dt:.1f}s"
        if why:
            bad.append((name, why))

    # 1. details of real dies, drawn several ways
    for cname, (make, strict) in CASES.items():
        for dname in ("closed", "one_colour", "cut_crease", "segments", "gappy"):
            for tname in ("plain", "rot33", "rot90"):
                def fn(make=make, dname=dname, tname=tname, strict=strict, cname=cname):
                    rnd = random.Random(7)
                    st, dims = make()
                    st, fl = stress.DRAWINGS[dname](st, rnd)
                    ids = {id(s) for s in fl} if fl else set()
                    idx = [i for i, s in enumerate(st) if id(s) in ids]
                    st = stress.transform(st, **stress.TRANSFORMS[tname])
                    fl = [st[i] for i in idx] if fl else None
                    m = geometry.build(st, fold_lines=fl)
                    if m is None:
                        return "NO MODEL"
                    out = []
                    if strict and m.issues:
                        out.append("ISSUES " + "; ".join(sorted({i.kind for i in m.issues})))
                    if dims:
                        ok, got = size_ok(m, dims)
                        if not ok:
                            out.append("SIZE " + "x".join(f"{g:.0f}" for g in got))
                    return (" | ".join(out) + f" [{len(m.faces)} faces; {m.solve_report}; {m.check_report}]") if out else ""
                case(f"{cname}/{dname}/{tname}", fn)

    # 2. junk in the same colour as the die must not change the box
    for sname in ("tuck_straight", "rsc", "tray", "mailer", "cube0", "prism6", "sleeve"):
        for dname in ("closed", "one_colour", "segments"):
            def fn(sname=sname, dname=dname):
                rnd = random.Random(11)
                st, dims = stress.STYLES[sname]()
                st, fl = stress.DRAWINGS[dname](st, rnd)
                m0 = geometry.build(st)
                m = geometry.build(with_junk(st, rnd))
                if m is None:
                    return "NO MODEL"
                a = sorted(np.round(fold3d.bounds3d(m0, fold3d.face_transforms(m0, 1.0))[1]
                                    - fold3d.bounds3d(m0, fold3d.face_transforms(m0, 1.0))[0]))
                b = sorted(np.round(fold3d.bounds3d(m, fold3d.face_transforms(m, 1.0))[1]
                                    - fold3d.bounds3d(m, fold3d.face_transforms(m, 1.0))[0]))
                if len(m.faces) != len(m0.faces) or a != b or m.issues:
                    return f"junk changed the box: faces {len(m0.faces)}->{len(m.faces)} size {a}->{b} issues {len(m.issues)}"
                return ""
            case(f"junk/{sname}/{dname}", fn)

    # 3. degenerate input: no exception, no hang
    rnd = random.Random(5)
    degenerate = {
        "empty": [],
        "one_point": [Stroke([(10, 10)], False)],
        "zero_length": [Stroke([(10, 10), (10, 10)], False), Stroke([(10, 10), (10, 10), (10, 10)], True)],
        "one_line": [Stroke([(0, 0), (100, 0)], False)],
        "one_rect": [R(0, 0, 100, 50)],
        "two_rects_apart": [R(0, 0, 100, 50), R(300, 0, 400, 50)],
        "two_rects_joined": [R(0, 0, 100, 50), R(100, 0, 200, 50)],
        "two_rects_corner": [R(0, 0, 100, 50), R(100, 50, 200, 100)],
        "circle": [P(*arc(100, 100, 80, 0, 360, 48)[:-1])],
        "bow_tie": [P((0, 0), (100, 100), (100, 0), (0, 100))],
        "nested": [R(0, 0, 300, 300), R(50, 50, 250, 250), R(100, 100, 200, 200)],
        "grid10": [R(i * 50, j * 50, i * 50 + 50, j * 50 + 50) for i in range(10) for j in range(10)],
        "strip40": [R(i * 30, 0, i * 30 + 30, 100) for i in range(40)],
        "collinear_pts": [Stroke([(0, 0), (50, 0), (100, 0), (100, 0), (100, 80), (0, 80)], True),
                          Stroke([(100, 0), (200, 0), (200, 80), (100, 80)], True)],
        "huge_coords": [R(1e6, 1e6, 1e6 + 300, 1e6 + 200), R(1e6 + 300, 1e6, 1e6 + 500, 1e6 + 200),
                        R(1e6 + 500, 1e6, 1e6 + 800, 1e6 + 200)],
        "tiny": [R(0, 0, 3, 2), R(3, 0, 5, 2), R(5, 0, 8, 2)],
        "negative": [R(-500, -300, -200, -100), R(-200, -300, -50, -100), R(-50, -300, 250, -100)],
        "nan": [Stroke([(0, 0), (float("nan"), 5), (100, 100)], True), R(0, 0, 100, 50), R(100, 0, 200, 50)],
        "inf": [Stroke([(0, 0), (float("inf"), 5)], False), R(0, 0, 100, 50), R(100, 0, 200, 50)],
        "random_lines": [Stroke([(rnd.uniform(0, 800), rnd.uniform(0, 600)),
                                 (rnd.uniform(0, 800), rnd.uniform(0, 600))], False) for _ in range(150)],
        "random_rects": [R(x, y, x + rnd.uniform(20, 200), y + rnd.uniform(20, 200))
                         for x, y in [(rnd.uniform(0, 800), rnd.uniform(0, 600)) for _ in range(40)]],
        "spiral": [Stroke([(400 + t * 2 * math.cos(t / 5), 400 + t * 2 * math.sin(t / 5)) for t in range(300)], False)],
        "star": [P(*[(300 + (150 if k % 2 == 0 else 60) * math.cos(k * math.pi / 5),
                      300 + (150 if k % 2 == 0 else 60) * math.sin(k * math.pi / 5)) for k in range(10)])],
        "fan": [P((300, 300), (300 + 200 * math.cos(a), 300 + 200 * math.sin(a)),
                  (300 + 200 * math.cos(a + 0.5), 300 + 200 * math.sin(a + 0.5))) for a in np.arange(0, 6.0, 0.5)],
    }
    for name, st in degenerate.items():
        def fn(st=st):
            m = geometry.build(st)
            if m is not None:
                Ms = fold3d.face_transforms(m, 1.0)
                for M in Ms.values():
                    if not np.isfinite(M).all():
                        return "non-finite transform"
                sc = fold3d.project(m, 1.0, fold3d.Camera(), 800, 600)
                for d in sc.faces:
                    if not np.isfinite(d.H).all():
                        return "non-finite projection"
            return ""
        case(f"degenerate/{name}", fn)

    # 4. random manual edits and angle overrides: never an exception, always a model
    for sname in ("tuck_straight", "rsc", "tray", "mailer", "cube0", "prism6", "pyramid", "window"):
        def fn(sname=sname):
            rnd = random.Random(3)
            st, _ = stress.STYLES[sname]()
            m = geometry.build(st)
            for step in range(12):
                man = geometry.Manual()
                keys = [f.key for f in m.faces]
                eks = [e[0] for e in m.shared]
                if rnd.random() < 0.5:
                    man.root = rnd.choice(keys)
                for _ in range(rnd.randint(0, 3)):
                    getattr(man, rnd.choice(["cuts", "folds", "flat"])).add(rnd.choice(eks))
                for _ in range(rnd.randint(0, 2)):
                    k = rnd.choice(keys)
                    if k != man.root:
                        man.excluded.add(k)
                angles = {geometry.fold_key(fd): rnd.choice([0, 45, 90, -90, 135, 180, -180, 270, 1e9])
                          for fd in rnd.sample(m.folds, min(3, len(m.folds)))}
                m2 = geometry.build(st, None, angles, manual=man)
                if m2 is not None:
                    for cam in (fold3d.Camera(), fold3d.Camera(yaw=170, pitch=89, zoom=8, shift=False),
                                fold3d.Camera(yaw=-400, pitch=-89, zoom=0.05)):
                        sc = fold3d.project(m2, 1.0, cam, 640, 480)
                        for d in sc.faces:
                            if not np.isfinite(d.H).all():
                                return f"non-finite projection at step {step}"
            return ""
        case(f"manual/{sname}", fn)

    for name, why in bad:
        print("FAIL", name, "->", why[:330])
    print(f"{n - len(bad)}/{n} ok, {len(bad)} failed, {time.time() - t_all:.0f}s")
    return bad


if __name__ == "__main__":
    run()
