"""Artwork textures and the QPainter scene renderer shared by the 3D view and export."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pymupdf
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF,
                           QRadialGradient, QTransform)

from .. import fold3d


def render_art(src, rect, max_px: int):
    """Artwork of the die area as (QImage, QRectF in pt). rect = (x0, y0, x1, y1) in pt."""
    x0, y0, x1, y1 = rect
    x0, y0, x1, y1 = x0 - 2, y0 - 2, x1 + 2, y1 + 2
    if src.art_kind == "pdf":
        from ..dieline import PDF_LOCK
        with PDF_LOCK:
            return _render_pdf(src, x0, y0, x1, y1, max_px)
    if src.art_kind == "image":
        img = QImage.fromData(src.art_data)
        if img.isNull():
            return None, None
        ax0, ay0, ax1, ay1 = src.art_rect
        if max(img.width(), img.height()) > max_px * 1.5:
            img = img.scaled(int(max_px * 1.5), int(max_px * 1.5), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return img.convertToFormat(QImage.Format_ARGB32_Premultiplied), QRectF(ax0, ay0, ax1 - ax0, ay1 - ay0)
    return None, None


def _render_pdf(src, x0, y0, x1, y1, max_px):
    # colour-managed CMYK -> sRGB, like Illustrator / Photoshop show it
    pymupdf.TOOLS.set_icc(True)
    doc = pymupdf.open(stream=src.art_data, filetype="pdf")
    page = doc[src.art_page]
    clip = pymupdf.Rect(x0, y0, x1, y1) & page.rect
    zoom = max_px / max(clip.width, clip.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
    return img, QRectF(clip.x0, clip.y0, clip.width, clip.height)


def erase_lines(img: QImage, rect: QRectF, groups) -> QImage:
    """Remove the die lines printed in the artwork: paint a mask of the selected die strokes
    and fill those pixels from their surroundings (grows inwards from both sides)."""
    from PySide6.QtGui import QPainterPath as _P
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    sx, sy = w / rect.width(), h / rect.height()
    mask = QImage(w, h, QImage.Format_Grayscale8)
    mask.fill(0)
    p = QPainter(mask)
    p.translate(-rect.x() * sx, -rect.y() * sy)
    p.scale(sx, sy)
    for g in groups:
        if not g.selected:
            continue
        pen = QPen(QColor(255, 255, 255), max(g.width, 0.25) + 3.0 / sx, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        for st in g.strokes:
            path = _P(QPointF(*st.pts[0]))
            for x, y in st.pts[1:]:
                path.lineTo(x, y)
            if st.closed:
                path.closeSubpath()
            p.drawPath(path)
    p.end()
    m = np.array(mask.constBits(), dtype=np.uint8).reshape(h, mask.bytesPerLine())[:, :w] > 0
    a = np.array(img.constBits(), dtype=np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w].astype(np.float32)
    known = ~m
    ys, xs = np.nonzero(m)
    offs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    for _ in range(400):
        if len(ys) == 0:
            break
        acc = np.zeros((len(ys), 4), np.float32)
        cnt = np.zeros(len(ys), np.float32)
        for dy, dx in offs:
            ny = np.clip(ys + dy, 0, h - 1)
            nx = np.clip(xs + dx, 0, w - 1)
            k = known[ny, nx]
            acc[k] += a[ny[k], nx[k]]
            cnt[k] += 1
        fill = cnt > 0
        if not fill.any():
            break
        a[ys[fill], xs[fill]] = acc[fill] / cnt[fill, None]
        known[ys[fill], xs[fill]] = True
        ys, xs = ys[~fill], xs[~fill]
    out = np.ascontiguousarray(np.clip(a + 0.5, 0, 255).astype(np.uint8))
    return QImage(out.data, w, h, w * 4, QImage.Format_ARGB32).copy()


def fit_camera(model, t, cam, w, h, roll=0.0, fill=0.84):
    """Camera that centres the box and makes it fill the frame (product shot)."""
    c = fold3d.Camera(**cam.__dict__)
    c.zoom, c.pan_x, c.pan_y = 1.0, 0.0, 0.0
    scene = fold3d.project(model, t, c, w, h, roll)
    pts = []
    for d in scene.faces:
        P = fold3d.face_points(model.faces[d.id])
        hom = (d.H @ np.c_[P, np.ones(len(P))].T).T
        pts.append(hom[:, :2] / hom[:, 2:3])
    if not pts:
        return c
    allp = np.vstack(pts)
    (x0, y0), (x1, y1) = allp.min(axis=0), allp.max(axis=0)
    k = fill * min(w / max(1e-6, x1 - x0), h / max(1e-6, y1 - y0))
    c.zoom = k
    c.pan_x = -((x0 + x1) / 2 - w / 2) * k
    c.pan_y = -((y0 + y1) / 2 - h / 2) * k
    return c


def face_path(face) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    for ring in [face.poly.exterior, *face.poly.interiors]:
        pts = list(ring.coords)
        path.moveTo(*pts[0])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
    return path


@dataclass
class FaceTex:
    path: QPainterPath
    brush: QBrush | None


class Textures:
    def __init__(self, model, art: QImage | None, art_rect: QRectF | None):
        self.faces = {}
        for f in model.faces:
            brush = None
            if art is not None and not art.isNull():
                ox, oy = getattr(f, "offset", (0.0, 0.0))
                bx0, by0, bx1, by1 = f.poly.bounds
                bx0, by0, bx1, by1 = bx0 - ox, by0 - oy, bx1 - ox, by1 - oy   # where its art is
                sx = art.width() / art_rect.width()
                sy = art.height() / art_rect.height()
                ix0 = max(0, int((bx0 - art_rect.x()) * sx) - 2)
                iy0 = max(0, int((by0 - art_rect.y()) * sy) - 2)
                ix1 = min(art.width(), int((bx1 - art_rect.x()) * sx) + 3)
                iy1 = min(art.height(), int((by1 - art_rect.y()) * sy) + 3)
                if ix1 > ix0 and iy1 > iy0:
                    sub = art.copy(ix0, iy0, ix1 - ix0, iy1 - iy0)
                    brush = QBrush(sub)
                    tr = QTransform()
                    tr.translate(art_rect.x() + ix0 / sx + ox, art_rect.y() + iy0 / sy + oy)
                    tr.scale(1 / sx, 1 / sy)
                    brush.setTransform(tr)
            self.faces[f.id] = FaceTex(face_path(f), brush)


@dataclass
class RenderOptions:
    background: str = "studio"        # studio | white | transparent | color
    color: str = "#ffffff"
    board: str = "#ece6da"
    shadow: bool = True
    outline: bool = True
    fast: bool = False
    light: tuple = (-0.25, 0.35)      # light pad position
    strength: float = 0.12            # how dark faces turned away from the light get
    exposure: float = 1.0


def paint_background(p: QPainter, w, h, opt: RenderOptions):
    if opt.background == "transparent":
        return
    if opt.background == "white":
        p.fillRect(0, 0, w, h, QColor("#ffffff"))
    elif opt.background == "color":
        p.fillRect(0, 0, w, h, QColor(opt.color))
    else:
        g = QRadialGradient(QPointF(w * 0.5, h * 0.42), max(w, h) * 0.75)
        g.setColorAt(0, QColor("#f4f5f7"))
        g.setColorAt(1, QColor("#b9bec8"))
        p.fillRect(0, 0, w, h, QBrush(g))


def paint_shadow(p: QPainter, w, h, scene, strength=0.32):
    if not scene.shadows:
        return
    k = 6                                            # blur by drawing small and scaling up
    sw, sh = max(1, w // k), max(1, h // k)
    img = QImage(sw, sh, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    q = QPainter(img)
    q.setRenderHint(QPainter.Antialiasing)
    q.setPen(Qt.NoPen)
    q.setBrush(QColor(0, 0, 0, 255))
    for poly in scene.shadows:
        q.drawPolygon(QPolygonF([QPointF(x / k, y / k) for x, y in poly]))
    q.end()
    # two smoothing passes give a soft edge
    for _ in range(2):
        img = img.scaled(max(1, sw // 3), max(1, sh // 3), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        img = img.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    p.save()
    p.setOpacity(strength)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.drawImage(QRectF(0, 0, w, h), img)
    p.restore()


def render_scene(p: QPainter, w: int, h: int, model, tex: Textures | None, t: float,
                 cam: fold3d.Camera, opt: RenderOptions, roll: float = 0.0):
    paint_background(p, w, h, opt)
    if model is None:
        return None
    scene = fold3d.project(model, t, cam, w, h, roll, fold3d.light_vector(*opt.light), opt.strength,
                           opt.exposure)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, not opt.fast)
    if opt.shadow and t > 0.3:
        paint_shadow(p, w, h, scene, 0.32 * min(1.0, (t - 0.3) / 0.4))
    board = QColor(opt.board)
    for d in scene.faces:
        ft = tex.faces.get(d.id) if tex else None
        if ft is None:
            path = face_path(model.faces[d.id])
            brush = None
        else:
            path, brush = ft.path, ft.brush
        H = d.H
        tr = QTransform(H[0, 0], H[1, 0], H[2, 0], H[0, 1], H[1, 1], H[2, 1], H[0, 2], H[1, 2], H[2, 2])
        p.save()
        p.setTransform(tr)
        p.setPen(Qt.NoPen)
        if d.front:
            p.fillPath(path, brush if brush is not None else QBrush(QColor("#ffffff")))
        else:
            p.fillPath(path, board)
        if d.shade < 1:
            p.fillPath(path, QColor(0, 0, 0, min(255, int(round((1 - d.shade) * 255)))))
        elif d.shade > 1:
            p.fillPath(path, QColor(255, 255, 255, min(255, int(round((d.shade - 1) * 255)))))
        if opt.outline and not model.faces[d.id].small:
            pen = QPen(QColor(0, 0, 0, 40 if d.front else 60), 0.8)
            pen.setCosmetic(True)
            p.strokePath(path, pen)
        p.restore()
    return scene
