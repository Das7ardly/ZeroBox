"""App icon and small line icons drawn in code (colours from the theme)."""
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from .theme import C


def draw_logo(p: QPainter, s: float):
    """Amber rounded tile with an open box drawn in lines (Zero family style). Simplified below 24 px."""
    p.setRenderHint(QPainter.Antialiasing)
    r = s * 0.22
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C["accent"]))
    p.drawRoundedRect(QRectF(0, 0, s, s), r, r)
    ink = QColor(C["on_accent"])
    w = max(1.4, s * (0.07 if s >= 24 else 0.09))
    p.setPen(QPen(ink, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    u = s / 24.0

    def P(x, y):
        return QPointF(x * u, y * u)
    # box body: front-left and front-right faces, seen from above
    p.drawPolygon(QPolygonF([P(4.5, 10), P(12, 13.2), P(19.5, 10), P(19.5, 17), P(12, 20.5), P(4.5, 17)]))
    p.drawLine(P(12, 13.2), P(12, 20.5))
    if s >= 24:
        # two lid flaps opening outwards
        p.drawPolyline([P(4.5, 10), P(2.8, 6.4), P(10.2, 3.6), P(12, 6.8)])
        p.drawPolyline([P(19.5, 10), P(21.2, 6.4), P(13.8, 3.6), P(12, 6.8)])
        p.drawLine(P(4.5, 10), P(12, 6.8))
        p.drawLine(P(12, 6.8), P(19.5, 10))
    else:
        p.drawPolyline([P(4.5, 10), P(12, 5.5), P(19.5, 10)])


def logo_pixmap(size=256) -> QPixmap:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    draw_logo(p, size)
    p.end()
    return QPixmap.fromImage(img)


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(logo_pixmap(s))
    return ic


def check_images(folder: str):
    """check.png for QSS checkbox ticks."""
    path = os.path.join(folder, "check.png")
    img = QImage(32, 32, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(C["on_accent"]), 4.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    path_ = QPainterPath(QPointF(7, 17))
    path_.lineTo(13, 23)
    path_.lineTo(25, 9)
    p.drawPath(path_)
    p.end()
    img.save(path)
    return path.replace("\\", "/")


def line_icon(kind: str, size=18, color=None) -> QIcon:
    col = QColor(color or C["text"])
    img = QImage(size * 2, size * 2, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2, 2)
    pen = QPen(col, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    s = size
    if kind == "play":
        p.setBrush(col)
        p.drawPolygon(QPolygonF([QPointF(s * .3, s * .2), QPointF(s * .8, s * .5), QPointF(s * .3, s * .8)]))
    elif kind == "pause":
        p.setBrush(col)
        p.drawRect(int(s * .28), int(s * .22), int(s * .14), int(s * .56))
        p.drawRect(int(s * .58), int(s * .22), int(s * .14), int(s * .56))
    elif kind == "open":
        path = QPainterPath(QPointF(s * .12, s * .3))
        path.lineTo(s * .4, s * .3)
        path.lineTo(s * .48, s * .4)
        path.lineTo(s * .88, s * .4)
        path.lineTo(s * .88, s * .8)
        path.lineTo(s * .12, s * .8)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "paste":
        p.drawRoundedRect(int(s * .22), int(s * .2), int(s * .56), int(s * .66), 2, 2)
        p.drawLine(QPointF(s * .38, s * .2), QPointF(s * .38, s * .12))
        p.drawLine(QPointF(s * .38, s * .12), QPointF(s * .62, s * .12))
        p.drawLine(QPointF(s * .62, s * .12), QPointF(s * .62, s * .2))
    elif kind == "export":
        p.drawLine(QPointF(s * .5, s * .15), QPointF(s * .5, s * .62))
        p.drawLine(QPointF(s * .32, s * .33), QPointF(s * .5, s * .15))
        p.drawLine(QPointF(s * .68, s * .33), QPointF(s * .5, s * .15))
        p.drawLine(QPointF(s * .18, s * .62), QPointF(s * .18, s * .85))
        p.drawLine(QPointF(s * .18, s * .85), QPointF(s * .82, s * .85))
        p.drawLine(QPointF(s * .82, s * .85), QPointF(s * .82, s * .62))
    elif kind == "copy":
        p.drawRoundedRect(int(s * .3), int(s * .3), int(s * .5), int(s * .52), 2, 2)
        p.drawLine(QPointF(s * .2, s * .68), QPointF(s * .2, s * .18))
        p.drawLine(QPointF(s * .2, s * .18), QPointF(s * .62, s * .18))
    elif kind == "rotate":
        path = QPainterPath()
        path.arcMoveTo(s * .18, s * .18, s * .64, s * .64, 60)
        path.arcTo(s * .18, s * .18, s * .64, s * .64, 60, 270)
        p.drawPath(path)
        p.drawLine(QPointF(s * .66, s * .2), QPointF(s * .70, s * .36))
        p.drawLine(QPointF(s * .66, s * .2), QPointF(s * .52, s * .26))
    elif kind in ("ai", "ps"):
        p.drawRoundedRect(int(s * .1), int(s * .15), int(s * .8), int(s * .7), 3, 3)
        f = p.font()
        f.setPixelSize(int(s * .42))
        f.setBold(True)
        p.setFont(f)
        p.drawText(0, 0, s, s, Qt.AlignCenter, "Ai" if kind == "ai" else "Ps")
    p.end()
    return QIcon(QPixmap.fromImage(img))
