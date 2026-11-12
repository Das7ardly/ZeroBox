"""Hidden self-test: ZEROBOX_SELFTEST=<dir> [ZEROBOX_SELFTEST_FILES=<file>].
Loads the file, visits every view, saves screenshots and an export, then exits."""
import os
import time

from PySide6.QtWidgets import QApplication

from . import dieline


def _wait(cond, timeout=60):
    end = time.time() + timeout
    while time.time() < end and not cond():
        QApplication.processEvents()
        time.sleep(0.02)


def run(win, out, files):
    os.makedirs(out, exist_ok=True)
    log = open(os.path.join(out, "selftest.log"), "w", encoding="utf-8")

    def shot(name):
        QApplication.processEvents()
        win.grab().save(os.path.join(out, name + ".png"))
        log.write(f"shot {name}\n")

    try:
        win.resize(1360, 860)
        shot("01_empty")
        if files:
            win.set_source(dieline.load_file(files))
            _wait(lambda: win.view3d.tex is not None and win._loading == 0)
            log.write(f"faces {len(win.model.faces) if win.model else 0} folds "
                      f"{len(win.model.folds) if win.model else 0}\n{win.dims.text()}\n")
            shot("02_box")
            win.view3d.cam.yaw, win.view3d.cam.pitch = 150, 25
            win.view3d._sharp()
            shot("05_back")
            log.write("roles " + ", ".join(f"{g.key}={g.role}" for g in win.src.groups if g.selected) + "\n")
            win.seg.button(1).click()
            win.folds.selectRow(2)
            shot("06_die2d")
            win.seg.button(0).click()
            from .ui import render
            win.view3d.cam.yaw, win.view3d.cam.pitch = -38, 12
            img = win._export_image(1600, win._light_into(render.RenderOptions(background="white")), 0.8, True)
            img.save(os.path.join(out, "07_export.jpg"), None, 92)
            win.pad.changed.emit(-0.7, 0.45)
            win.pad.set_pos(-0.7, 0.45)
            win.s_strength.setValue(45)
            img = win._export_image(1600, win._light_into(render.RenderOptions(background="white")), 0.8, True)
            img.save(os.path.join(out, "07b_manual_light.jpg"), None, 92)
            log.write(f"light {win.light.currentData()} {win.st.light_x:.2f} {win.st.light_y:.2f}\n")
            img = win._export_image(1600, render.RenderOptions(background="transparent"))
            img.save(os.path.join(out, "08_export.png"))
            win.resize(1024, 700)
            shot("09_small")
        log.write("ok\n")
    except Exception:
        import traceback
        log.write(traceback.format_exc())
    finally:
        log.close()
        # leave the normal way (window close + event loop end), like a user would
        win.close()
        QApplication.instance().quit()
