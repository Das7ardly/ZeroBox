"""Window fuzz: random clicks, drags, keys, tool changes, edits and exports on many sources.
Run  py tests/ui_fuzz.py [seed] [steps]   - any Python error in a handler is a failure.
Uses its own in-memory settings, never the user's."""
import os
import random
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox  # noqa: E402

import dies  # noqa: E402
import stress  # noqa: E402
from zerobox import dieline  # noqa: E402
from zerobox.settings import Settings  # noqa: E402

ERRORS = []


def hook(tp, val, tb):
    ERRORS.append("".join(traceback.format_exception(tp, val, tb))[-900:])


sys.excepthook = hook

# no modal dialog may block the run
for name in ("information", "warning", "critical", "question"):
    setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Yes))
QMessageBox.exec = lambda self: 0
QDialog.exec = lambda self: 0
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
Settings.save = lambda self: None


def png_bytes(w=300, h=200):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor("#3377aa"))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def source(name, strokes, crease=None):
    groups = [dieline.LineGroup("L|#ff0000|1.00|0", "Die", (1, 0, 0), 1.0, False, list(strokes), True, "auto")]
    if crease:
        groups[0].role = "cut"
        groups.append(dieline.LineGroup("L|#00ff00|1.00|1", "Die", (0, 1, 0), 1.0, True, list(crease), True, "crease"))
    xs = [p[0] for s in strokes for p in s.pts] or [0, 100]
    ys = [p[1] for s in strokes for p in s.pts] or [0, 100]
    return dieline.DieSource(name, max(xs) + 50, max(ys) + 50, groups)


def sources():
    out = []
    for sname in ("tuck_straight", "tray", "mailer", "prism6", "pyramid", "cube0", "window", "two_piece"):
        st, _ = stress.STYLES[sname]()
        out.append(source(sname, st))
    cut, crease = dies.rsc_groups()
    out.append(source("rsc_roles", cut, crease))
    out.append(dieline.DieSource("empty", 500, 400, []))
    out.append(source("one_rect", [dies.rect(0, 0, 100, 50)]))
    out.append(source("garbage", [dieline.Stroke([(0, 0), (float("nan"), 3), (50, 50)], False),
                                  dieline.Stroke([(5, 5)], False)]))
    # optional real dies: ZEROBOX_TEST_FILES = paths separated by ";"
    for fn in filter(None, os.environ.get("ZEROBOX_TEST_FILES", "").split(";")):
        if os.path.exists(fn):
            out.append(dieline.load_file(fn))
    try:
        out.append(dieline.image_only(png_bytes(), "picture.png"))
    except Exception:                                                   # noqa: BLE001
        ERRORS.append("image_only: " + traceback.format_exc()[-600:])
    return out


def idle(win, timeout=40):
    end = time.time() + timeout
    QApplication.processEvents()
    while time.time() < end and (win._loading > 0 or win._rebuild_timer.isActive()):
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    return win._loading == 0


def rnd_pos(w, rnd):
    return QPoint(rnd.randint(-20, w.width() + 20), rnd.randint(-20, w.height() + 20))


def actions(win, rnd, png):
    v2, v3 = win.view2d, win.view3d
    from zerobox.ui import render

    def mouse(view):
        btn = rnd.choice([Qt.LeftButton, Qt.LeftButton, Qt.LeftButton, Qt.RightButton, Qt.MiddleButton])
        mod = rnd.choice([Qt.NoModifier, Qt.NoModifier, Qt.ShiftModifier, Qt.ControlModifier, Qt.AltModifier])
        a = rnd_pos(view, rnd)
        QTest.mousePress(view, btn, mod, a)
        for _ in range(rnd.randint(0, 4)):
            QTest.mouseMove(view, rnd_pos(view, rnd))
        QTest.mouseRelease(view, btn, mod, rnd_pos(view, rnd) if rnd.random() < 0.7 else a)

    def wheel(view):
        p = QPointF(rnd_pos(view, rnd))
        e = QWheelEvent(p, view.mapToGlobal(p), QPoint(0, 0), QPoint(0, rnd.choice([-1200, -120, 120, 2400])),
                        Qt.NoButton, rnd.choice([Qt.NoModifier, Qt.ControlModifier]), Qt.NoScrollPhase, False)
        QApplication.sendEvent(view, e)

    def key(view):
        QTest.keyClick(view, rnd.choice([Qt.Key_Delete, Qt.Key_Escape, Qt.Key_Return, Qt.Key_Backspace,
                                         Qt.Key_Enter, Qt.Key_Z, Qt.Key_Space]),
                       rnd.choice([Qt.NoModifier, Qt.ControlModifier]))

    def angle():
        t = win.folds
        if t.rowCount():
            it = t.item(rnd.randrange(t.rowCount()), t.columnCount() - 1)
            if it is not None:
                it.setText(rnd.choice(["45", "-90", "abc", "", "9999", "1e9", "90,5", "180", "0", " 30 ", "nan", "-0"]))

    def role():
        t = win.groups_table
        if t.rowCount():
            cb = t.cellWidget(rnd.randrange(t.rowCount()), 1)
            if cb is not None:
                cb.setCurrentIndex(rnd.randrange(cb.count()))

    def export():
        if win.model is None:
            return
        opts = win._light_into(render.RenderOptions(background=rnd.choice(["white", "transparent", "studio", "color"])))
        img = win._export_image(rnd.choice([64, 300, 1200]), opts, rnd.choice([None, 0.8, 1.0, 1.7778, 0.01, 50.0]),
                                rnd.random() < 0.5)
        if img is None or img.isNull():
            ERRORS.append("export returned an empty image")

    def combo(cb):
        return lambda: cb.setCurrentIndex(rnd.randrange(cb.count())) if cb.count() else None

    def check(cb):
        return lambda: cb.setChecked(not cb.isChecked())

    acts = [
        (6, lambda: mouse(v2)), (4, lambda: mouse(v3)), (2, lambda: wheel(v2)), (2, lambda: wheel(v3)),
        (2, lambda: key(v2)), (1, lambda: key(v3)),
        (4, lambda: v2.set_tool(rnd.choice(["select", "root", "toggle", "flat", "exclude", "rect", "poly", "edit"]))),
        (1, lambda: QTest.mouseDClick(v2, Qt.LeftButton, Qt.NoModifier, rnd_pos(v2, rnd))),
        (1, lambda: QTest.mouseDClick(v3, Qt.LeftButton, Qt.NoModifier, rnd_pos(v3, rnd))),
        (2, lambda: win.seg.button(rnd.choice([0, 1])).click()),
        (1, win.all90), (1, win.auto_close), (1, win.flip_fold), (1, win.redetect), (1, win.roll),
        (1, win._reset_manual), (1, win._clear_shapes), (1, win.copy_image), (2, export),
        (2, angle), (2, role),
        (1, lambda: win.folds.selectRow(rnd.randrange(win.folds.rowCount())) if win.folds.rowCount() else None),
        (1, combo(win.lens)), (1, combo(win.light)), (1, check(win.cb_straight)), (1, check(win.cb_lines)),
        (1, check(win.cb_shadow)),
        (1, lambda: win.pad.changed.emit(rnd.uniform(-1.5, 1.5), rnd.uniform(-1.5, 1.5))),
        (1, lambda: win.resize(rnd.choice([320, 700, 1360, 2400]), rnd.choice([240, 600, 860, 1500]))),
        (1, lambda: rnd.choice(win.view_buttons).click() if win.view_buttons else None),
        (1, lambda: win._set_art_image(rnd.choice([png, b"not an image", b""]), "art.png")),
        (1, lambda: v2.reset_view()),
        (1, lambda: v2.delete_selected_shape()),
    ]
    bag = [fn for w, fn in acts for _ in range(w)]
    return bag


def run(seed=1, steps=120):
    app = QApplication.instance() or QApplication([])
    from zerobox.ui import theme
    from zerobox.ui.main_window import MainWindow
    try:
        theme.apply(app)
    except Exception:                                                   # noqa: BLE001
        pass
    win = MainWindow(Settings())
    win.resize(1360, 860)
    win.show()
    QApplication.processEvents()
    png = png_bytes()
    rnd = random.Random(seed)
    report = []
    # every action on an empty window first
    for fn in actions(win, rnd, png):
        try:
            fn()
        except Exception:                                               # noqa: BLE001
            ERRORS.append(traceback.format_exc()[-900:])
    idle(win)
    if ERRORS:
        report.append(("<no file>", len(ERRORS), ERRORS[0]))
        ERRORS.clear()
    for src in sources():
        t = time.time()
        win.set_source(src)
        if not idle(win):
            ERRORS.append("did not become idle after loading")
        bag = actions(win, rnd, png)
        for i in range(steps):
            try:
                rnd.choice(bag)()
            except Exception:                                           # noqa: BLE001
                ERRORS.append(traceback.format_exc()[-900:])
            if i % 6 == 0:
                idle(win, 20)
            else:
                QApplication.processEvents()
        if not idle(win, 60):
            ERRORS.append("still busy 60 s after the last action")
        # the window must still be able to draw and export
        win.view3d.repaint()
        win.view2d.repaint()
        QApplication.processEvents()
        if ERRORS:
            seen = list(dict.fromkeys(e.strip().splitlines()[-1] + " @ " + (e.strip().splitlines()[-3].strip()
                                      if len(e.strip().splitlines()) > 2 else "") for e in ERRORS))
            report.append((src.name, len(ERRORS), seen))
            ERRORS.clear()
        print(f"{src.name}: {time.time() - t:.0f}s", flush=True)
    win.close()
    QApplication.processEvents()
    for name, n, seen in report:
        print("FAIL", name, n, "errors")
        for s in (seen if isinstance(seen, list) else [seen])[:12]:
            print("   ", s[:400])
    print("UI fuzz:", "clean" if not report else f"{len(report)} sources with errors")
    return report


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 1, int(sys.argv[2]) if len(sys.argv) > 2 else 120)
