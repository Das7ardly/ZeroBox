"""Core checks: run with  py -m pytest tests  (or  py tests/test_core.py)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zerobox import dieline, fold3d, geometry  # noqa: E402

# optional real die: set ZEROBOX_TEST_DIE to a .ai / .pdf file (tests that need it are skipped without it)
ST = os.environ.get("ZEROBOX_TEST_DIE", os.path.join(os.path.expanduser("~"), "Desktop", "ST.ai"))


def cube_cross(s=100.0):
    """A cube net drawn the usual way: outline as cut, inner edges as separate crease lines."""
    x0, y0 = 50, 50
    sq = [(1, 0), (0, 1), (1, 1), (2, 1), (3, 1), (1, 2)]
    strokes = []
    for cx, cy in sq:
        a, b = x0 + cx * s, y0 + cy * s
        strokes.append(dieline.Stroke([(a, b), (a + s, b), (a + s, b + s), (a, b + s)], True))
    return strokes


def folded_size(model):
    lo, hi = fold3d.bounds3d(model, fold3d.face_transforms(model, 1.0))
    return np.round(hi - lo, 1)


def test_cube_closes():
    m = geometry.build(cube_cross())
    assert len(m.faces) == 6 and len(m.folds) == 5
    assert list(folded_size(m)) == [100.0, 100.0, 100.0]


def test_flat_at_zero():
    m = geometry.build(cube_cross())
    lo, hi = fold3d.bounds3d(m, fold3d.face_transforms(m, 0.0))
    assert round(float(hi[2] - lo[2]), 3) == 0.0


AICB = """%!PS-Adobe-3.0
%%Creator: Adobe Illustrator(R) 24.0
%%BoundingBox: 0 0 500 400
%%EndComments
(Die) Ln
0 0 0 1 K
0.5 w
[] 0 d
50 300 m
150 300 l
150 200 l
50 200 l
50 300 l
S
150 300 m
250 300 l
250 200 l
150 200 L
S
150 300 m
150 330 150 360 180 380 c
220 380 l
250 300 l
s
"""


def test_aicb_parser():
    groups = dieline.parse_aicb(AICB)
    assert len(groups) == 1
    g = groups[0]
    assert len(g.strokes) == 3 and g.layer == "Die"
    # y is flipped to y-down: the top edge (AI y=300) becomes 100
    assert any(abs(p[1] - 100) < 1e-6 for p in g.strokes[0].pts)
    m = geometry.build(g.strokes)
    assert m is not None and len(m.faces) == 3


def test_dash_detection():
    assert not dieline._is_dashed("[] 0")
    assert not dieline._is_dashed("[ 23 0 0 0 0 0 ] 0")
    assert dieline._is_dashed("[ 3 2 ] 0")


def test_st_box():
    if not os.path.exists(ST):
        return
    src = dieline.load_file(ST)
    m = geometry.build(src.selected_strokes())
    size = folded_size(m)
    # 180 x 142 x 110 mm box
    assert abs(size[0] - 510.2) < 2 and abs(size[1] - 402.5) < 2 and abs(size[2] - 311.8) < 2
    big = [f for f in m.faces if not f.small]
    assert len(big) == 14




# ---------------------------------------------------------------- other box styles (solver)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dies  # noqa: E402


def _angles(m):
    return sorted({fd.angle for fd in m.folds if not m.faces[fd.child].small})


def test_polygon_tubes():
    for n, want in ((3, 120.0), (4, 90.0), (6, 60.0), (8, 45.0)):
        m = geometry.build(dies.tube(n, w=240 / n))
        assert _angles(m) == [want], (n, _angles(m))
        assert m.tube_sides == n


def test_hexagon_with_lids_closes():
    from zerobox import solver
    m = geometry.build(dies.tube(6, lids=True))
    assert _angles(m) == [60.0, 90.0]
    assert solver.gaps(m)[1] < 1.0


def test_sloped_tray_and_pyramid_close():
    from zerobox import solver
    for strokes in (dies.sloped_tray(), dies.pyramid()):
        m = geometry.build(strokes)
        assert solver.gaps(m)[1] < 1.0          # paired edges meet within 1 pt
        assert all(fd.angle < 90 or fd.angle > 90 for fd in m.folds)


def test_st_stays_square():
    if not os.path.exists(ST):
        return
    src = dieline.load_file(ST)
    m = geometry.build(src.selected_strokes())
    assert _angles(m) == [90.0]


# ---------------------------------------------------------------- hand marking in the 2D view

def _st():
    if not os.path.exists(ST):
        return None
    return dieline.load_file(ST).selected_strokes()


def test_manual_front_panel():
    strokes = _st()
    if strokes is None:
        return
    m = geometry.build(strokes)
    big = m.faces[m.root].area
    back = next(f for f in m.faces if f.id != m.root and f.area > 0.9 * big)   # the other big panel
    m2 = geometry.build(strokes, manual=geometry.Manual(root=back.key))
    assert m2.faces[m2.root].key == back.key
    a, b = folded_size(m), folded_size(m2)
    assert sorted(a) == sorted(b)                                     # same box, seen from the back


def test_manual_cut_exclude_flat():
    strokes = _st()
    if strokes is None:
        return
    m = geometry.build(strokes)
    lid = next(fd for fd in m.folds if fd.parent == m.root and fd.horizontal and fd.length > 500)
    # cut: the lid (and its tuck) leave the box
    m2 = geometry.build(strokes, manual=geometry.Manual(cuts={lid.key}))
    assert len(m2.faces) == len(m.faces) - 2
    # flat: the lid stays in the plane of the front panel, so the box gets taller
    m3 = geometry.build(strokes, manual=geometry.Manual(flat={lid.key}, root=m.faces[m.root].key))
    f3 = next(fd for fd in m3.folds if fd.key == lid.key)
    assert f3.angle == 0 and folded_size(m3)[1] > folded_size(m)[1] + 100
    # exclude the glue flap
    glue = min((m.faces[fd.child] for fd in m.folds if fd.parent == m.root and not fd.horizontal),
               key=lambda f: f.area)
    m4 = geometry.build(strokes, manual=geometry.Manual(excluded={glue.key}))
    assert len(m4.faces) == len(m.faces) - 1 and glue.key not in {f.key for f in m4.faces}


def test_manual_forced_fold_changes_tree():
    from tests_dies_grid import grid2x2
    m = geometry.build(grid2x2(), solve=False)
    free = [ek for ek, a, b, st in m.shared if st == "free"]
    assert len(free) == 1                       # 4 panels in a ring: one edge is not a hinge
    m2 = geometry.build(grid2x2(), solve=False, manual=geometry.Manual(folds={free[0]}))
    assert free[0] in {fd.key for fd in m2.folds}


# ---------------------------------------------------------------- line roles (cut / crease)

def test_slots_are_never_hinges():
    cut, crease = dies.rsc_groups()
    loose = geometry.build(cut + crease, solve=False)
    m = geometry.build(cut + crease, solve=False, fold_lines=crease)
    walls = {f.id for f in m.faces if f.area > 0.3 * m.faces[0].area}
    for f in m.faces:
        if f.id in walls or f.parent < 0:
            continue
        # every flap hangs on a wall (its crease), never on the next flap through a slot
        assert f.parent in walls, ("flap on flap", f.id, f.parent)
    assert len(m.faces) == len(loose.faces) == 13
    lo, hi = fold3d.bounds3d(m, fold3d.face_transforms(m, 1.0))
    assert sorted(np.round(hi - lo)) == [120.0, 150.0, 200.0]          # 200 x 120 x 150 carton


def test_roles_guess_and_rules():
    from zerobox import roles
    from zerobox.dieline import LineGroup
    cut, crease = dies.rsc_groups()
    a = LineGroup("k|#000000|1.00|0", "Die", (0, 0, 0), 1.0, False, cut, True)
    b = LineGroup("k|#ff0000|1.00|0", "", (1, 0, 0), 1.0, False, crease, True)
    art = LineGroup("k|#00ff00|0.50|0", "", (0, 1, 0), 0.5, False, [cut[0]], False)
    roles.guess_roles([a, b, art])
    assert (a.role, b.role, art.role) == ("cut", "crease", "ignore")
    assert roles.hint_from_name("Crease") == "crease" and roles.hint_from_name("CutContour") == "cut"
    b.role = "perf"
    rules = roles.remember([], b)
    b2 = LineGroup("x|#ff0000|1.05|0", "", (1, 0, 0), 1.05, False, crease, True, "auto")
    assert roles.apply_rules([b2], rules) == 1 and b2.role == "perf"


# ---------------------------------------------------------------- fold check and repair

def test_check_finds_no_problems_in_good_boxes():
    cut, crease = dies.rsc_groups()
    for strokes, fl in ((dies.tube(6, lids=True), None), (dies.sloped_tray(), None), (dies.pyramid(), None),
                        (cut + crease, crease), (cube_cross(), None)):
        m = geometry.build(strokes, fold_lines=fl)
        assert m.issues == [], [i.text for i in m.issues]


def test_check_repairs_scrambled_folds():
    import random
    from zerobox import check
    cut, crease = dies.rsc_groups()
    random.seed(3)
    for strokes, fl in ((dies.tube(6, lids=True), None), (dies.sloped_tray(), None), (cut + crease, crease)):
        m = geometry.build(strokes, fold_lines=fl)
        good = {fd.id: fd.angle for fd in m.folds}
        size0 = folded_size(m)
        cand = [fd for fd in m.folds if not m.faces[fd.child].small]
        for _ in range(5):
            for fd in m.folds:
                fd.angle = good[fd.id]
            for fd in random.sample(cand, 2):
                fd.angle = random.choice([45.0, -90.0, 180.0, 135.0, 0.0])
            check.repair(m)
            assert check.analyze(m) == [] and list(folded_size(m)) == list(size0)


def test_check_reports_a_roof_lid():
    from zerobox import check
    strokes = _st()
    if strokes is None:
        return
    m = geometry.build(strokes)
    lid = next(fd for fd in m.folds if fd.parent == m.root and fd.horizontal and fd.length > 500
               and m.faces[fd.child].poly.bounds[1] < 600)
    lid.angle = 45.0
    kinds = {i.kind for i in check.analyze(m)}
    assert "sticks_out" in kinds
    check.repair(m)
    assert lid.angle == 90.0 and check.analyze(m) == []


def test_carton_with_narrow_sides_and_no_glue_flap():
    # wide front/back, narrow sides, no glue flap: the narrow end panel is a wall, not glue
    for glue in (0.0, 30.0):
        cut, crease = dies.rsc_groups(L=320, W=123, H=350, glue=glue)
        for fl in (crease, None):
            m = geometry.build(cut + crease, fold_lines=fl)
            assert m.tube_sides == 4 and m.issues == []
            assert sorted(folded_size(m)) == [123.0, 320.0, 350.0]
            assert all(fd.angle == 90.0 for fd in m.folds if not m.faces[fd.child].small)


def test_front_lid_is_on_top_when_lids_overlap_fully():
    cut, crease = dies.rsc_groups(L=320, W=123, H=350, glue=0, flap=123)
    m = geometry.build(cut + crease, fold_lines=crease)
    assert m.issues == []
    lids = [f for f in m.faces if f.poly.bounds[3] <= 223.5 and f.area > 0.9 * 320 * 123]
    front_lid = next(f for f in lids if f.parent == m.root)
    for yaw, pitch in ((-35, 30), (35, 50), (150, 40), (0, 80)):
        order = [d.id for d in fold3d.project(m, 1.0, fold3d.Camera(yaw=yaw, pitch=pitch), 800, 600).faces]
        assert max(lids, key=lambda f: order.index(f.id)).id == front_lid.id


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
