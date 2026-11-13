"""Die in two colours (cut + crease) with crease lines that stop short of the cut lines,
plus artwork groups. Which groups does the detection take?"""
import math
import os
import random
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dies, stress
from zerobox import dieline, geometry, roles
from zerobox.dieline import LineGroup, Stroke


def shorten(s, gap):
    (ax, ay), (bx, by) = s.pts[0], s.pts[-1]
    d = math.hypot(bx - ax, by - ay)
    if d < 4 * gap or len(s.pts) != 2:
        return s
    k = gap / d
    return Stroke([(ax + (bx - ax) * k, ay + (by - ay) * k), (bx - (bx - ax) * k, by - (by - ay) * k)], False)


def art_groups(bbox, rnd):
    x0, y0, x1, y1 = bbox
    text = []
    for _ in range(60):                               # letter-like closed outlines
        cx, cy = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
        text.append(Stroke([(cx + 6 * math.cos(a), cy + 9 * math.sin(a)) for a in [k * math.pi / 5 for k in range(10)]], True))
    frames = [dies.rect(x0 + 30, y0 + 30, x0 + 130, y0 + 90), dies.rect(x1 - 150, y1 - 100, x1 - 40, y1 - 30)]
    rules_ = [Stroke([(rnd.uniform(x0, x1), y), (rnd.uniform(x0, x1), y)], False) for y in [rnd.uniform(y0, y1) for _ in range(8)]]
    return text, frames, rules_


def case(name, cut, crease, gap, cut_col, crease_col, same_style_art=False):
    rnd = random.Random(1)
    crease = [shorten(s, gap) for s in crease]
    xs = [p[0] for s in cut for p in s.pts]; ys = [p[1] for s in cut for p in s.pts]
    text, frames, rules_ = art_groups((min(xs), min(ys), max(xs), max(ys)), rnd)
    groups = [LineGroup("L|cut", "L", cut_col, 1.0, False, list(cut)),
              LineGroup("L|crease", "L", crease_col, 1.0, False, list(crease)),
              LineGroup("L|text", "L", (0.1, 0.1, 0.1), 0.25, False, text),
              LineGroup("L|frames", "L", (0.5, 0.5, 0.5), 0.5, False, frames),
              LineGroup("L|rules", "L", (0.2, 0.6, 0.2), 0.75, False, rules_)]
    if same_style_art:                                 # artwork in the die's own colour and width
        from shapely.geometry import LineString
        from shapely.ops import unary_union
        net = unary_union([LineString(s.pts + ([s.pts[0]] if s.closed else [])) for s in cut + crease])
        inside = [s for s in text + frames if LineString(s.pts).distance(net) > 12]
        groups[0].strokes += inside
        del groups[2:4]
    dieline.auto_select(groups, (max(xs) + 100, max(ys) + 100))
    sel = [f"{g.key.split('|')[1]}={g.role}" for g in groups if g.selected]
    st = [s for g in groups if g.selected for s in g.strokes]
    m = geometry.build(st, fold_lines=roles.fold_strokes(groups)) if st else None
    ok = m is not None and not m.issues and len(m.faces) >= 9
    print(f"{'ok  ' if ok and 'crease=crease' in sel or (ok and gap == 0) else 'FAIL'} {name:34} gap={gap:4} sel={sel} faces={len(m.faces) if m else 0} issues={len(m.issues) if m else '-'}")


RED, BLUE, BLACK = (0.93, 0.12, 0.14), (0.03, 0.3, 0.64), (0.14, 0.12, 0.13)
for gap in (0, 0.4, 1.5, 4, 8):
    cut, crease = dies.rsc_groups()
    case("rsc red cut / blue crease", cut, crease, gap, RED, BLUE)
    case("rsc black cut / red crease", cut, crease, gap, BLACK, RED)
    cc = stress._classify(stress.tuck_end()[0])
    case("tuck red cut / black crease", cc[0], cc[1], gap, RED, BLACK)
    cc = stress._classify(stress.tray()[0])
    case("tray blue cut / red crease", cc[0], cc[1], gap, BLUE, RED)
cut, crease = dies.rsc_groups()
case("rsc + art in the die's own style", cut, crease, 0, BLACK, BLUE, True)
cc = stress._classify(stress.tuck_end()[0])
case("tuck + art in the die's own style", cc[0], cc[1], 0, BLACK, BLUE, True)
