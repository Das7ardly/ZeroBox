"""What each group of lines is: cut, crease, perforation, artwork. Qt-free.

The idea comes from ArtiosCAD's import tuning: line types are decided by rules on the
line's colour / width / dash / layer (or spot-colour name), not guessed from the shape
every time. ZeroBox proposes roles automatically, the user corrects them, and the
correction is remembered as a rule so files from the same studio work next time."""
from __future__ import annotations

import re

# role -> label shown in the UI
ROLES = {
    "auto": "Щанца (авто)",
    "cut": "Рязане",
    "crease": "Сгъване",
    "perf": "Перфорация",
    "ignore": "Не е щанца",
}
FOLDING = ("auto", "crease", "perf")       # lines a panel may hinge on

# names used for die layers / spot colours (Artios_Cut, CutContour, Crease, Rill, Биг ...)
_HINTS = [
    ("crease", re.compile(r"crease|rill|ril[l]?en|\bfold|bend|scor|nut|bieg|бигов|биг\b|сгъв|рил", re.I)),
    ("perf", re.compile(r"perf|перфор", re.I)),
    ("cut", re.compile(r"\bcut\b|cut[_ ]?line|cutcontour|kiss|knife|stanz|рязан|нож|контур", re.I)),
]


def hint_from_name(name: str) -> str | None:
    if not name:
        return None
    for role, rx in _HINTS:
        if rx.search(name):
            return role
    return None


def guess_roles(groups) -> None:
    """Propose a role for every group. Groups that are not part of the die stay 'ignore'.
    With one die group cut and crease can't be told apart by style: it stays 'auto' and
    the folds are found from the shape. With several, lines on the outline of the die
    (and around cut-outs) are cuts, lines running inside it are creases."""
    sel = [g for g in groups if g.selected]
    for g in groups:
        g.role = "auto" if g.selected else "ignore"
    hinted = set()
    for g in sel:
        r = hint_from_name(g.layer)
        if r:
            g.role = r
            hinted.add(g.key)
    rest = [g for g in sel if g.key not in hinted]
    if len(sel) < 2 or not rest:
        return
    from shapely.ops import unary_union

    from .geometry import _lines, faces_from_strokes
    polys = faces_from_strokes([s for g in sel for s in g.strokes])
    if not polys:
        return
    outline = unary_union(polys).boundary.buffer(1.5)
    stats = {}
    for g in rest:
        lines = _lines(g.strokes)
        total = sum(ln.length for ln in lines)
        if total <= 0:
            continue
        inside = sum(ln.difference(outline).length for ln in lines) / total
        closed = sum(1 for s in g.strokes if s.closed) / max(1, len(g.strokes))
        stats[g.key] = (inside, closed)
        if closed >= 0.5:
            # panels drawn as closed shapes: their edges are cuts and folds at once (auto);
            # a closed shape lying fully inside the die is a cut-out (window, slot)
            if inside >= 0.8:
                g.role = "cut"
        elif inside >= 0.8:
            g.role = "crease"                   # open lines running inside the die
    has_crease = any(g.role == "crease" for g in sel)
    for g in rest:
        inside, closed = stats.get(g.key, (0.5, 1.0))
        if has_crease and closed < 0.5 and g.role == "auto" and inside <= 0.5:
            g.role = "cut"                      # the outline (and slots) next to a crease group


# ---------------------------------------------------------------- remembered rules

def _hex(color) -> str:
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in color)


def rule_for(group) -> dict:
    return {"color": _hex(group.color), "width": round(group.width, 2), "dashed": bool(group.dashed),
            "layer": group.layer or "", "role": group.role}


def _matches(rule, group) -> bool:
    if rule.get("color") != _hex(group.color) or bool(rule.get("dashed")) != bool(group.dashed):
        return False
    w = float(rule.get("width", 0))
    if abs(w - group.width) > max(0.06, 0.12 * max(w, group.width)):
        return False
    layer = rule.get("layer", "")
    return layer in ("", "*") or layer == (group.layer or "")


def apply_rules(groups, rules) -> int:
    """Use remembered rules where they match. Returns how many groups they decided."""
    n = 0
    # a rule remembered from another file must not pull this file's artwork into the die:
    # a group the detection left out that has far more lines than the die is artwork here
    die = sum(len(g.strokes) for g in groups if g.selected)
    limit = max(300, 5 * die)
    for g in groups:
        g.rule_skipped = False
        for r in rules:
            if _matches(r, g):
                if r["role"] != "ignore" and not g.selected and len(g.strokes) > limit:
                    g.rule_skipped = True
                    break
                g.role = r["role"]
                g.selected = g.role != "ignore"
                n += 1
                break
    return n


def remember(rules: list, group) -> list:
    """Add or replace the rule for this group's style."""
    new = rule_for(group)
    out = [r for r in rules if not (r.get("color") == new["color"] and bool(r.get("dashed")) == new["dashed"]
                                    and abs(float(r.get("width", 0)) - new["width"]) < 0.01
                                    and r.get("layer", "") == new["layer"])]
    out.append(new)
    return out[-200:]


def fold_strokes(groups):
    """Strokes a panel may fold on, or None when no group says cut or crease explicitly
    (then every shared edge may be a fold, and the shape decides)."""
    sel = [g for g in groups if g.selected]
    if not any(g.role in ("cut", "crease") for g in sel):
        return None
    return [s for g in sel if g.role in FOLDING for s in g.strokes]
