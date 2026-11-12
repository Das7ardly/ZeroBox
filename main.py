import os
import sys


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QStyleFactory

    from zerobox import APP_NAME
    from zerobox.paths import data_dir
    from zerobox.settings import Settings
    from zerobox.ui import brand, theme
    from zerobox.ui.main_window import MainWindow

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ZeroBox.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.qss(brand.check_images(data_dir())))
    app.setWindowIcon(brand.app_icon())

    st = Settings.load()
    win = MainWindow(st)
    win.show()

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args and os.path.exists(args[0]):
        QTimer.singleShot(0, lambda: win.load_path(args[0]))

    selftest = os.environ.get("ZEROBOX_SELFTEST")
    if selftest:
        from zerobox.selftest import run
        QTimer.singleShot(0, lambda: run(win, selftest, os.environ.get("ZEROBOX_SELFTEST_FILES", "")))
    code = app.exec()
    # let background renders finish before the DLLs unload
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone(10000)
    sys.exit(code)


if __name__ == "__main__":
    main()
