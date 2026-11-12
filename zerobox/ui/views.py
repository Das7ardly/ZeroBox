"""3D box view (orbit, pan, zoom) and the flat 2D die view."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .. import fold3d
from . import render
from .theme import C


class View3D(QWidget):
    viewChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(False)
        self.model = None
        self.tex = None
        self.t = 1.0
        self.cam = fold3d.Camera()
        self.roll = 0.0
        self.opts = render.RenderOptions()
        self._drag = None
        self._fast = False
        self._idle = QTimer(self, singleShot=True, interval=180, timeout=self._sharp)
        self._tween = QTimer(self, interval=16, timeout=self._tween_step)
        self._tween_from = self._tween_to = None
        self._tween_k = 0.0
        self.message = ""
        self.setCursor(Qt.OpenHandCursor)

    # ------------------------------------------------------------ painting
    def paintEvent(self, _):
        p = QPainter(self)
        opt = render.RenderOptions(**{**self.opts.__dict__, "fast": self._fast})
        if opt.background == "transparent":
            opt.background = "studio"
        render.render_scene(p, self.width(), self.height(), self.model, self.tex, self.t, self.cam, opt, self.roll)
        if self.model is None or self.message:
            p.setPen(QColor("#5a606c"))
            f = p.font()
            f.setPointSize(12)
            p.setFont(f)
            p.drawText(self.rect().adjusted(40, 40, -40, -40), Qt.AlignCenter | Qt.TextWordWrap,
                       self.message or "Отвори щанца (Ctrl+O), постави от Illustrator (Ctrl+V)\n"
                                       "или натисни „От Illustrator“ / „От Photoshop“.")
        p.end()

    def grab_image(self, w, h, opts: render.RenderOptions, tex=None, fill=False) -> QImage:
        """Render the current view at another size (export). fill = centre the box and fill the frame."""
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        if fill and self.model is not None:
            cam = render.fit_camera(self.model, self.t, self.cam, w, h, self.roll)
        else:
            # the view's framing scaled to fit inside the new frame
            cam = fold3d.Camera(**self.cam.__dict__)
            W, H = max(1, self.width()), max(1, self.height())
            s = min(w / W, h / H)
            cam.zoom *= min(W, H) * s / min(w, h)
            cam.pan_x *= s
            cam.pan_y *= s
        p = QPainter(img)
        render.render_scene(p, w, h, self.model, tex or self.tex, self.t, cam, opts, self.roll)
        p.end()
        return img

    def _sharp(self):
        self._fast = False
        self.update()

    def _rough(self):
        self._fast = True
        self._idle.start()

    # ------------------------------------------------------------ interaction
    def mousePressEvent(self, e):
        self._tween.stop()
        self._drag = (e.button(), e.position(), self.cam.yaw, self.cam.pitch, self.cam.pan_x, self.cam.pan_y)
        self.setCursor(Qt.ClosedHandCursor if e.button() == Qt.LeftButton else Qt.SizeAllCursor)

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        btn, start, yaw, pitch, px, py = self._drag
        d = e.position() - start
        if btn == Qt.LeftButton and not (e.modifiers() & Qt.ShiftModifier):
            self.cam.yaw = yaw + d.x() * 0.4
            self.cam.pitch = max(-89.0, min(89.0, pitch + d.y() * 0.4))
        else:
            self.cam.pan_x = px + d.x()
            self.cam.pan_y = py + d.y()
        self._rough()
        self.update()
        self.viewChanged.emit()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)
        self._sharp()

    def mouseDoubleClickEvent(self, e):
        self.set_view(-32, 18, reset=True)

    def wheelEvent(self, e):
        k = 1.12 ** (e.angleDelta().y() / 120)
        self.cam.zoom = max(0.15, min(8.0, self.cam.zoom * k))
        # zoom toward the cursor
        cx, cy = self.width() / 2 + self.cam.pan_x, self.height() / 2 + self.cam.pan_y
        pos = e.position()
        self.cam.pan_x += (pos.x() - cx) * (1 - k)
        self.cam.pan_y += (pos.y() - cy) * (1 - k)
        self._rough()
        self.update()
        self.viewChanged.emit()

    # ------------------------------------------------------------ camera presets
    def set_view(self, yaw, pitch, reset=False):
        self._tween_from = (self.cam.yaw, self.cam.pitch, self.cam.zoom, self.cam.pan_x, self.cam.pan_y)
        # take the short way round
        yaw0 = self.cam.yaw
        while yaw - yaw0 > 180:
            yaw -= 360
        while yaw - yaw0 < -180:
            yaw += 360
        z, px, py = (1.0, 0.0, 0.0) if reset else (self.cam.zoom, self.cam.pan_x, self.cam.pan_y)
        self._tween_to = (yaw, pitch, z, px, py)
        self._tween_k = 0.0
        self._tween.start()

    def _tween_step(self):
        self._tween_k = min(1.0, self._tween_k + 0.08)
        k = fold3d.ease(self._tween_k)
        a, b = self._tween_from, self._tween_to
        v = [x + (y - x) * k for x, y in zip(a, b)]
        self.cam.yaw, self.cam.pitch, self.cam.zoom, self.cam.pan_x, self.cam.pan_y = v
        self._fast = self._tween_k < 1.0
        self.update()
        if self._tween_k >= 1.0:
            self._tween.stop()
            self.viewChanged.emit()


class View2D(QWidget):
    """Flat die with the hand tools: pick the front panel, turn lines into folds or cuts,
    keep two panels flat together, leave a panel out."""
    foldClicked = Signal(int)
    rootRequested = Signal(str)       # face key
    edgeClicked = Signal(str, str)    # edge key, current state
    faceClicked = Signal(str)         # face key (exclude tool)
    shapesChanged = Signal()          # the hand-drawn panels changed

    TOOLS = ("select", "root", "toggle", "flat", "exclude", "rect", "poly", "edit")
    HINTS = {
        "rect": "Влачи, за да нарисуваш панел. Ръбовете се залепват за другите форми и за линиите. "
                "Панели с общ ръб се сгъват по него",
        "poly": "Кликни ъглите на формата (скосени капаци, лепенки); двоен клик или Enter = готово, Esc = откажи",
        "edit": "Влачи форма = премести · влачи ъгъл = промени размера · Delete или десен клик = изтрий",
        "select": "Клик върху сгъвка = избери я в таблицата · двоен клик върху панел = лицев панел",
        "root": "Кликни панела, който е лицето на кутията (той стои срещу камерата)",
        "toggle": "Кликни линия между два панела: сгъвка ↔ рязане. "
                  "Оранжев пунктир = панелите се допират, но не са сгънати един към друг",
        "flat": "Кликни сгъвка: двата панела остават плоски като едно цяло (клик пак = отмяна)",
        "exclude": "Кликни панел, който не е част от кутията, за да го махнеш (клик пак = върни)",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.model = None
        self.groups = []
        self.art = None
        self.art_rect = None
        self.selected_fold = -1
        self.excluded = set()
        self.issue_faces = set()          # panels the fold check complains about
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self._drag = None
        self.tool = "select"
        self.setMouseTracking(True)
        self._hover_fold = -1
        self._hover_edge = None
        self._hover_face = None
        self.shapes = []                # hand-drawn panels: [[(x, y), ...], ...] in die pt
        self.sel_shape = -1
        self._draft = None              # rect: [start, end]; poly: [points...]
        self._cursor_die = None
        self._edit = None               # (mode, index, start die pt, original points, vertex)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_tool(self, tool):
        self.tool = tool
        self._hover_edge = self._hover_face = None
        self._hover_fold = -1
        self._draft = None
        self._edit = None
        self.setCursor(Qt.CrossCursor if tool in ("rect", "poly") else Qt.ArrowCursor)
        self.update()

    # ------------------------------------------------------------ hand-drawn shapes
    def _snap_lists(self, skip=-1):
        xs, ys = [], []
        for i, sh in enumerate(self.shapes):
            if i == skip:
                continue
            for x, y in sh:
                xs.append(x)
                ys.append(y)
        for g in self.groups:
            if not g.selected:
                continue
            for st in g.strokes:
                if len(st.pts) <= 8:            # straight die lines and corners, not curves
                    for x, y in st.pts:
                        xs.append(x)
                        ys.append(y)
        if self.art_rect is not None:
            r = self.art_rect
            xs += [r.x(), r.right()]
            ys += [r.y(), r.bottom()]
        return xs, ys

    def _snap(self, pt, skip=-1, lists=None):
        """Pull a point onto the x / y of nearby corners (other shapes, die lines)."""
        s, _ = self._xf()
        tol = 9.0 / max(s, 1e-9)
        xs, ys = lists or self._snap_lists(skip)
        x, y = pt
        bx = min(xs, key=lambda v: abs(v - x), default=None)
        by = min(ys, key=lambda v: abs(v - y), default=None)
        if bx is not None and abs(bx - x) <= tol:
            x = bx
        if by is not None and abs(by - y) <= tol:
            y = by
        return (x, y)

    @staticmethod
    def _is_rect(pts):
        if len(pts) != 4:
            return False
        xs = sorted({round(p[0], 3) for p in pts})
        ys = sorted({round(p[1], 3) for p in pts})
        return len(xs) == 2 and len(ys) == 2

    def _shape_at(self, pos):
        from shapely.geometry import Point, Polygon
        pt = Point(*self.to_die(pos))
        hits = []
        for i, sh in enumerate(self.shapes):
            if len(sh) >= 3:
                poly = Polygon(sh)
                if poly.is_valid and poly.buffer(2).contains(pt):
                    hits.append((poly.area, i))
        return min(hits)[1] if hits else -1

    def _vertex_at(self, pos):
        s, off = self._xf()
        best, bd = None, 9.0
        for i, sh in enumerate(self.shapes):
            for k, (x, y) in enumerate(sh):
                d = math.hypot(x * s + off.x() - pos.x(), y * s + off.y() - pos.y())
                if d < bd:
                    best, bd = (i, k), d
        return best

    def _changed(self):
        self.update()
        self.shapesChanged.emit()

    def delete_selected_shape(self):
        if 0 <= self.sel_shape < len(self.shapes):
            del self.shapes[self.sel_shape]
            self.sel_shape = -1
            self._changed()

    def _finish_poly(self):
        pts = self._draft or []
        # drop a duplicated last point from the double click
        while len(pts) >= 2 and math.dist(pts[-1], pts[-2]) < 0.5:
            pts.pop()
        if len(pts) >= 3:
            self.shapes.append(list(pts))
            self.sel_shape = len(self.shapes) - 1
            self._draft = None
            self._changed()
        else:
            self._draft = None
            self.update()

    def _shape_press(self, e):
        pos = e.position()
        d = self.to_die(pos)
        if e.button() == Qt.RightButton:
            i = self._shape_at(pos)
            if i >= 0:
                self.sel_shape = i
                self.delete_selected_shape()
            return True
        if e.button() != Qt.LeftButton:
            return False
        if self.tool == "rect":
            p0 = self._snap(d)
            self._draft = [p0, p0]
            self.update()
            return True
        if self.tool == "poly":
            p = self._snap(d)
            if self._draft is None:
                self._draft = [p]
            elif len(self._draft) >= 3 and math.dist(p, self._draft[0]) < 9.0 / self._xf()[0]:
                self._finish_poly()            # clicked the first corner again
                return True
            else:
                self._draft.append(p)
            self.update()
            return True
        if self.tool == "edit":
            v = self._vertex_at(pos)
            if v is not None:
                i, k = v
                self.sel_shape = i
                self._edit = ("vertex", i, d, [tuple(q) for q in self.shapes[i]], k)
                self.update()
                return True
            i = self._shape_at(pos)
            self.sel_shape = i
            if i >= 0:
                self._edit = ("move", i, d, [tuple(q) for q in self.shapes[i]], -1)
                self.update()
                return True
            self.update()
        return False

    def _shape_move(self, e):
        d = self.to_die(e.position())
        self._cursor_die = d
        if self.tool == "rect" and self._draft:
            self._draft[1] = self._snap(d)
            self.update()
            return True
        if self.tool == "poly" and self._draft:
            self.update()
            return True
        if self.tool == "edit" and self._edit:
            mode, i, start, orig, k = self._edit
            lists = self._snap_lists(skip=i)
            if mode == "move":
                dx, dy = d[0] - start[0], d[1] - start[1]
                moved = [(x + dx, y + dy) for x, y in orig]
                # snap the whole shape by the corner that is closest to something
                best = (0.0, 0.0)
                bdx = bdy = None
                for q in moved:
                    sx, sy = self._snap(q, lists=lists)
                    if sx != q[0] and (bdx is None or abs(sx - q[0]) < abs(bdx)):
                        bdx = sx - q[0]
                    if sy != q[1] and (bdy is None or abs(sy - q[1]) < abs(bdy)):
                        bdy = sy - q[1]
                best = (bdx or 0.0, bdy or 0.0)
                self.shapes[i] = [(x + best[0], y + best[1]) for x, y in moved]
            else:
                p = self._snap(d, lists=lists)
                if self._is_rect(orig):
                    # keep a rectangle a rectangle: the opposite corner stays put
                    ox, oy = orig[(k + 2) % 4]
                    x0, x1 = sorted((ox, p[0]))
                    y0, y1 = sorted((oy, p[1]))
                    self.shapes[i] = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                else:
                    pts = list(orig)
                    pts[k] = p
                    self.shapes[i] = pts
            self.update()
            return True
        return False

    def _shape_release(self, e):
        if self.tool == "rect" and self._draft:
            (x0, y0), (x1, y1) = self._draft
            self._draft = None
            if abs(x1 - x0) > 3 and abs(y1 - y0) > 3:
                x0, x1 = sorted((x0, x1))
                y0, y1 = sorted((y0, y1))
                self.shapes.append([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
                self.sel_shape = len(self.shapes) - 1
                self._changed()
            else:
                self.update()
            return True
        if self.tool == "edit" and self._edit:
            self._edit = None
            self._changed()
            return True
        return False

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.tool in ("edit", "rect", "poly"):
            if self._draft and self.tool == "poly":
                self._draft.pop()
                if not self._draft:
                    self._draft = None
                self.update()
            else:
                self.delete_selected_shape()
            return
        if e.key() == Qt.Key_Escape:
            self._draft = None
            self._edit = None
            self.update()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.tool == "poly":
            self._finish_poly()
            return
        super().keyPressEvent(e)

    def _paint_shapes(self, p, s, off):
        MMK = 25.4 / 72
        acc = QColor(C["accent"])
        p.setBrush(Qt.NoBrush)              # outlines only; fills are done explicitly below
        for i, sh in enumerate(self.shapes):
            if len(sh) < 2:
                continue
            path = QPainterPath(QPointF(*sh[0]))
            for x, y in sh[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
            fill = QColor(acc)
            fill.setAlpha(70 if i == self.sel_shape else 38)
            p.fillPath(path, fill)
            pen = QPen(acc, 3.0 if i == self.sel_shape else 2.0)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawPath(path)
        # handles of the selected shape
        if 0 <= self.sel_shape < len(self.shapes) and self.tool == "edit":
            p.save()
            p.resetTransform()
            p.setPen(QPen(QColor(C["on_accent"]), 1.5))
            p.setBrush(acc)
            for x, y in self.shapes[self.sel_shape]:
                p.drawRect(QRectF(x * s + off.x() - 5, y * s + off.y() - 5, 10, 10))
            p.restore()
        # the shape being drawn
        label = None
        if self._draft and self.tool == "rect":
            (x0, y0), (x1, y1) = self._draft
            pen = QPen(QColor("#ffffff"), 1.6, Qt.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized())
            label = (f"{abs(x1 - x0) * MMK:.1f} × {abs(y1 - y0) * MMK:.1f} mm", x1, y1)
        elif self._draft and self.tool == "poly":
            pts = list(self._draft)
            if self._cursor_die is not None:
                pts.append(self._snap(self._cursor_die))
            pen = QPen(QColor("#ffffff"), 1.6, Qt.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            self._poly(p, pts, False)
            if len(pts) >= 2:
                a, b = pts[-2], pts[-1]
                label = (f"{math.dist(a, b) * MMK:.1f} mm", b[0], b[1])
        elif self.tool == "edit" and 0 <= self.sel_shape < len(self.shapes):
            sh = self.shapes[self.sel_shape]
            xs = [q[0] for q in sh]
            ys = [q[1] for q in sh]
            label = (f"{(max(xs) - min(xs)) * MMK:.1f} × {(max(ys) - min(ys)) * MMK:.1f} mm", max(xs), max(ys))
        if label:
            text, lx, ly = label
            p.save()
            p.resetTransform()
            f = QFont(self.font())
            f.setBold(True)
            p.setFont(f)
            r = QRectF(lx * s + off.x() + 10, ly * s + off.y() + 8, 150, 22)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(r, 5, 5)
            p.setPen(QColor("#ffffff"))
            p.drawText(r, Qt.AlignCenter, text)
            p.restore()

    def _bounds(self):
        if self.art_rect is not None:
            r = self.art_rect
            return (r.x(), r.y(), r.right(), r.bottom())
        if self.model is not None:
            pts = [c for _, poly in self.model.all_faces for c in poly.exterior.coords] or None
            if pts:
                return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
            return self.model.bbox
        pts = [p for g in self.groups for s in g.strokes for p in s.pts]
        if pts:
            return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        if self.art_rect is not None:
            r = self.art_rect
            return (r.x(), r.y(), r.right(), r.bottom())
        return None

    def _xf(self):
        b = self._bounds()
        if b is None:
            return 1.0, QPointF(0, 0)
        x0, y0, x1, y1 = b
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        s = min((self.width() - 60) / w, (self.height() - 60) / h) * self.zoom
        off = QPointF(self.width() / 2 - (x0 + w / 2) * s, self.height() / 2 - (y0 + h / 2) * s) + self.pan
        return s, off

    def to_die(self, pos):
        s, off = self._xf()
        return ((pos.x() - off.x()) / s, (pos.y() - off.y()) / s)

    @staticmethod
    def _poly_path(poly):
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        for ring in [poly.exterior, *poly.interiors]:
            pts = list(ring.coords)
            path.moveTo(*pts[0])
            for x, y in pts[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
        return path

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C["bg"]))
        p.setRenderHint(QPainter.Antialiasing)
        s, off = self._xf()
        p.translate(off)
        p.scale(s, s)
        m = self.model
        if self.art is not None and self.art_rect is not None:
            p.setOpacity(0.55)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            if m is not None and getattr(m, "pieces", 1) > 1:
                # a two-piece box was put together: each panel shows its own artwork
                for f in m.faces:
                    ox, oy = f.offset
                    p.save()
                    p.setClipPath(render.face_path(f))
                    p.translate(ox, oy)
                    p.drawImage(self.art_rect, self.art)
                    p.restore()
            else:
                p.drawImage(self.art_rect, self.art)
            p.setOpacity(1.0)
        pen = QPen(QColor(150, 150, 160, 90), 1)
        pen.setCosmetic(True)
        p.setPen(pen)
        for g in self.groups:
            if g.selected:
                continue
            for st in g.strokes:
                self._poly(p, st.pts, st.closed)
        if m is not None:
            in_box = {f.key for f in m.faces}
            # panels left out of the box: grey hatch
            for key, poly in m.all_faces:
                if key in in_box:
                    continue
                path = self._poly_path(poly)
                col = QColor(120, 120, 130, 150 if key in self.excluded else 70)
                p.fillPath(path, QBrush(col, Qt.BDiagPattern))
            root = m.faces[m.root]
            p.fillPath(render.face_path(root), QColor(242, 165, 65, 60))
            for fid in self.issue_faces:
                if 0 <= fid < len(m.faces):
                    bad = QColor(C["bad"])
                    bad.setAlpha(90)
                    p.fillPath(render.face_path(m.faces[fid]), bad)
            if self._hover_face is not None:
                for key, poly in m.all_faces:
                    if key == self._hover_face:
                        p.fillPath(self._poly_path(poly), QColor(76, 155, 232, 70))
            pen = QPen(QColor(C["cut"]), 1.6)
            pen.setCosmetic(True)
            p.setPen(pen)
            for line in m.cut_lines:
                self._poly(p, line, False)
            # touching panels that are not folded to each other
            if self.tool == "toggle":
                for ek, a, b, state in m.shared:
                    if state != "fold":
                        pen = QPen(QColor(C["accent"]), 2.2, Qt.DotLine)
                        pen.setCosmetic(True)
                        p.setPen(pen)
                        p.drawLine(QPointF(*a), QPointF(*b))
            for fd in m.folds:
                sel = fd.id == self.selected_fold
                hov = fd.id == self._hover_fold
                col = QColor(C["accent"] if sel else C["fold"])
                if fd.angle == 0:
                    col = QColor(150, 150, 160)
                pen = QPen(col, 3.2 if (sel or hov) else 1.8, Qt.DashLine)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.drawLine(QPointF(*fd.p0), QPointF(*fd.p1))
            if self._hover_edge is not None:
                for ek, a, b, state in m.shared:
                    if ek == self._hover_edge:
                        pen = QPen(QColor("#ffffff"), 4.5)
                        pen.setCosmetic(True)
                        p.setPen(pen)
                        p.drawLine(QPointF(*a), QPointF(*b))
            p.resetTransform()
            f = QFont(self.font())
            f.setPointSize(8)
            f.setBold(True)
            p.setFont(f)
            for fd in m.folds:
                if fd.angle == 0 and fd.id != self.selected_fold:
                    continue
                mx = (fd.p0[0] + fd.p1[0]) / 2 * s + off.x()
                my = (fd.p0[1] + fd.p1[1]) / 2 * s + off.y()
                r = QRectF(mx - 10, my - 8, 20, 16)
                sel = fd.id == self.selected_fold
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(C["accent"] if sel else C["fold"]))
                p.drawRoundedRect(r, 5, 5)
                p.setPen(QColor(C["on_accent"]) if sel else QColor("#ffffff"))
                p.drawText(r, Qt.AlignCenter, str(fd.id + 1))
            c = root.poly.representative_point()
            p.setPen(QColor(C["accent"]))
            f.setPointSize(9)
            p.setFont(f)
            p.drawText(QRectF(c.x * s + off.x() - 60, c.y * s + off.y() - 10, 120, 20), Qt.AlignCenter, "ЛИЦЕ")
        p.resetTransform()
        p.translate(off)
        p.scale(s, s)
        self._paint_shapes(p, s, off)
        p.resetTransform()
        p.setPen(QColor(C["muted"]))
        p.drawText(self.rect().adjusted(12, 8, -12, -8), Qt.AlignLeft | Qt.AlignBottom | Qt.TextWordWrap,
                   "червено = рязане · синьо = сгъване · сиво = плоско · " + self.HINTS[self.tool])
        p.end()

    @staticmethod
    def _poly(p, pts, closed):
        if len(pts) < 2:
            return
        path = QPainterPath(QPointF(*pts[0]))
        for x, y in pts[1:]:
            path.lineTo(x, y)
        if closed:
            path.closeSubpath()
        p.drawPath(path)

    def _dist(self, pos, a, b):
        s, off = self._xf()
        ax, ay = a[0] * s + off.x(), a[1] * s + off.y()
        bx, by = b[0] * s + off.x(), b[1] * s + off.y()
        vx, vy = bx - ax, by - ay
        L = vx * vx + vy * vy
        if L == 0:
            return 1e9
        t = max(0, min(1, ((pos.x() - ax) * vx + (pos.y() - ay) * vy) / L))
        return math.hypot(ax + t * vx - pos.x(), ay + t * vy - pos.y())

    def _fold_at(self, pos):
        if self.model is None:
            return -1
        best, bd = -1, 9.0
        for fd in self.model.folds:
            d = self._dist(pos, fd.p0, fd.p1)
            if d < bd:
                best, bd = fd.id, d
        return best

    def _edge_at(self, pos, folds_only=False):
        if self.model is None:
            return None
        best, bd = None, 9.0
        for ek, a, b, state in self.model.shared:
            if folds_only and state != "fold":
                continue
            d = self._dist(pos, a, b)
            if d < bd:
                best, bd = (ek, state), d
        return best

    def _face_at(self, pos):
        if self.model is None:
            return None
        from shapely.geometry import Point
        pt = Point(*self.to_die(pos))
        hits = [(poly.area, key) for key, poly in self.model.all_faces if poly.contains(pt)]
        return min(hits)[1] if hits else None

    def mousePressEvent(self, e):
        if self.tool in ("rect", "poly", "edit") and self._shape_press(e):
            return
        if e.button() == Qt.LeftButton and self.model is not None:
            if self.tool == "select":
                f = self._fold_at(e.position())
                if f >= 0:
                    self.selected_fold = f
                    self.foldClicked.emit(f)
                    self.update()
                    return
            elif self.tool in ("toggle", "flat"):
                hit = self._edge_at(e.position(), folds_only=self.tool == "flat")
                if hit:
                    self.edgeClicked.emit(*hit)
                    return
            elif self.tool == "root":
                key = self._face_at(e.position())
                if key:
                    self.rootRequested.emit(key)
                    return
            elif self.tool == "exclude":
                key = self._face_at(e.position())
                if key:
                    self.faceClicked.emit(key)
                    return
        self._drag = (e.position(), QPointF(self.pan))

    def mouseMoveEvent(self, e):
        if self.tool in ("rect", "poly", "edit") and not self._drag:
            if self._shape_move(e):
                return
            if self.tool == "edit":
                over = self._vertex_at(e.position()) is not None
                self.setCursor(Qt.SizeAllCursor if over else
                               (Qt.OpenHandCursor if self._shape_at(e.position()) >= 0 else Qt.ArrowCursor))
            return
        if self._drag:
            start, pan = self._drag
            self.pan = pan + (e.position() - start)
            self.update()
            return
        fold, edge, face = -1, None, None
        if self.tool == "select":
            fold = self._fold_at(e.position())
        elif self.tool in ("toggle", "flat"):
            hit = self._edge_at(e.position(), folds_only=self.tool == "flat")
            edge = hit[0] if hit else None
        else:
            face = self._face_at(e.position())
        if (fold, edge, face) != (self._hover_fold, self._hover_edge, self._hover_face):
            self._hover_fold, self._hover_edge, self._hover_face = fold, edge, face
            self.setCursor(Qt.PointingHandCursor if (fold >= 0 or edge or face) else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, e):
        if self.tool in ("rect", "edit") and self._shape_release(e):
            return
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        if self.tool == "poly" and self._draft:
            self._finish_poly()
            return
        if self.model is None or self.tool != "select":
            return
        key = self._face_at(e.position())
        if key:
            self.rootRequested.emit(key)

    def wheelEvent(self, e):
        k = 1.12 ** (e.angleDelta().y() / 120)
        old = self.zoom
        self.zoom = max(0.3, min(12.0, self.zoom * k))
        k = self.zoom / old
        c = QPointF(self.width() / 2, self.height() / 2) + self.pan
        self.pan += (e.position() - c) * (1 - k)
        self.update()

    def reset_view(self):
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.update()


class LightPad(QWidget):
    """Drag the dot on the sphere to where the light comes from; the sphere shows the result."""
    changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(132, 132)
        self.x, self.y = -0.25, 0.35
        self.strength = 0.12
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Влачи точката: откъдето идва светлината.\nЦентър = от камерата, горе = отгоре, ляво = отляво")

    def set_pos(self, x, y):
        self.x, self.y = x, y
        self.update()

    def _geom(self):
        r = min(self.width(), self.height()) / 2 - 8
        return QPointF(self.width() / 2, self.height() / 2), r

    def paintEvent(self, _):
        from PySide6.QtGui import QRadialGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c, r = self._geom()
        hl = QPointF(c.x() + self.x * r * 0.7, c.y() - self.y * r * 0.7)
        g = QRadialGradient(hl, r * 1.7)
        g.setColorAt(0, QColor("#ffffff"))
        dark = max(0, int(255 * (1 - min(0.9, self.strength * 1.6))))
        g.setColorAt(1, QColor(dark, dark, dark))
        p.setPen(QPen(QColor(C["border"]), 1))
        p.setBrush(g)
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor(C["muted"]), 1, Qt.DotLine))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        dot = QPointF(c.x() + self.x * r, c.y() - self.y * r)
        p.setPen(QPen(QColor(C["on_accent"]), 2))
        p.setBrush(QColor(C["accent"]))
        p.drawEllipse(dot, 7, 7)
        p.end()

    def _set_from(self, pos):
        c, r = self._geom()
        x = (pos.x() - c.x()) / r
        y = -(pos.y() - c.y()) / r
        d = math.hypot(x, y)
        if d > 0.99:
            x, y = x / d * 0.99, y / d * 0.99
        self.x, self.y = x, y
        self.update()
        self.changed.emit(x, y)

    def mousePressEvent(self, e):
        self._set_from(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._set_from(e.position())
