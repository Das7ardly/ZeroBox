"""Synthetic dielines of different box styles for the solver tests."""
import math

from zerobox.dieline import Stroke


def rect(x0, y0, x1, y1):
    return Stroke([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], True)


def poly(*pts):
    return Stroke(list(pts), True)


def tube(n, w=60.0, h=120.0, glue=18.0, lids=False):
    """n wall panels in a row plus a tapered glue flap on the left (hexagon: n=6)."""
    x0, y0 = 100.0, 200.0
    out = [poly((x0 - glue, y0 + 8), (x0, y0), (x0, y0 + h), (x0 - glue, y0 + h - 8))]
    for i in range(n):
        out.append(rect(x0 + i * w, y0, x0 + (i + 1) * w, y0 + h))
    if lids:
        # a regular n-gon lid on the first wall and one on the bottom of the second wall
        r = w / (2 * math.sin(math.pi / n))
        a = w / (2 * math.tan(math.pi / n))          # apothem
        for k, (top, wall) in enumerate(((True, 0), (False, 1))):
            cx = x0 + wall * w + w / 2
            base_y = y0 if top else y0 + h
            cy = base_y - a if top else base_y + a
            pts = []
            for j in range(n):
                ang = (j + 0.5) * 2 * math.pi / n + (math.pi / 2 if top else -math.pi / 2)
                pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
            out.append(poly(*pts))
    return out


def sloped_tray(L=200.0, W=140.0, h=50.0, flare=15.0):
    """Base with four trapezoid walls leaning outwards (no corner flaps)."""
    x0, y0 = 150.0, 150.0
    x1, y1 = x0 + L, y0 + W
    return [
        rect(x0, y0, x1, y1),
        poly((x0, y0), (x1, y0), (x1 + flare, y0 - h), (x0 - flare, y0 - h)),
        poly((x0, y1), (x1, y1), (x1 + flare, y1 + h), (x0 - flare, y1 + h)),
        poly((x0, y0), (x0, y1), (x0 - h, y1 + flare), (x0 - h, y0 - flare)),
        poly((x1, y0), (x1, y1), (x1 + h, y1 + flare), (x1 + h, y0 - flare)),
    ]


def pyramid(n=4, side=120.0, h=150.0):
    """Square base with n triangular sides meeting at the top."""
    x0, y0 = 300.0, 300.0
    s = side
    out = [rect(x0, y0, x0 + s, y0 + s)]
    out.append(poly((x0, y0), (x0 + s, y0), (x0 + s / 2, y0 - h)))
    out.append(poly((x0, y0 + s), (x0 + s, y0 + s), (x0 + s / 2, y0 + s + h)))
    out.append(poly((x0, y0), (x0, y0 + s), (x0 - h, y0 + s / 2)))
    out.append(poly((x0 + s, y0), (x0 + s, y0 + s), (x0 + s + h, y0 + s / 2)))
    return out


def rsc_groups(L=200.0, W=120.0, H=150.0, glue=25.0, flap=None):
    """Shipping carton (FEFCO 0201) drawn the usual way: cut = outline + slot lines between
    the flaps, crease = the panel and flap creases. Returns (cut strokes, crease strokes)."""
    x0, y0 = 100.0, 100.0
    widths = [L, W, L, W]
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)
    f = W / 2 if flap is None else flap          # flap height: W / 2 = RSC, W = full overlap
    top, mid0, mid1, bot = y0, y0 + f, y0 + f + H, y0 + 2 * f + H
    if glue > 0:
        cut = [Stroke([(x0 - glue, mid0 + 10), (x0, mid0), (x0, top), (xs[-1], top), (xs[-1], bot),
                       (x0, bot), (x0, mid1), (x0 - glue, mid1 - 10)], False)]
        cut.append(Stroke([(x0 - glue, mid0 + 10), (x0 - glue, mid1 - 10)], False))
    else:                                   # no glue flap: the outline is a plain rectangle
        cut = [Stroke([(x0, top), (xs[-1], top), (xs[-1], bot), (x0, bot)], True)]
    for x in xs[1:-1]:                      # slots: one line from the edge to the crease
        cut.append(Stroke([(x, top), (x, mid0)], False))
        cut.append(Stroke([(x, mid1), (x, bot)], False))
    crease = [Stroke([(x0, mid0), (xs[-1], mid0)], False), Stroke([(x0, mid1), (xs[-1], mid1)], False)]
    for x in xs[:-1]:
        crease.append(Stroke([(x, mid0), (x, mid1)], False))
    return cut, crease
