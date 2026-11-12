# -*- mode: python -*-
from PyInstaller.utils.hooks import collect_dynamic_libs

excl_mods = ["PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtSql",
             "PySide6.QtSvg", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtMultimedia",
             "PySide6.QtWebEngineCore", "PySide6.QtDBus", "PySide6.QtTest", "PySide6.QtXml",
             "tkinter", "unittest", "pydoc", "matplotlib", "PIL", "pytest", "onnxruntime", "sympy",
             "ssl", "_ssl", "pandas", "scipy", "IPython", "pymupdf.layout", "pymupdf4llm"]

a = Analysis(["main.py"], pathex=["."], binaries=collect_dynamic_libs("shapely"),
             datas=[("assets/zerobox.ico", "assets")],
             hiddenimports=["win32com.client", "pythoncom", "pywintypes", "shapely.geometry"],
             excludes=excl_mods, noarchive=False)

drop = ("opengl32sw", "qt6pdf", "qt6quick", "qt6qml", "qt6network", "qt6virtualkeyboard", "qt6svg",
        "qt6opengl", "d3dcompiler", "qt6dbus")
a.binaries = [b for b in a.binaries if not any(d in b[0].lower() for d in drop)]
a.datas = [d for d in a.datas if "translations" not in d[0].lower()
           and not any(p in d[0].replace("\\", "/") for p in ("plugins/tls", "plugins/networkinformation",
                                                               "plugins/generic", "plugins/qmltooling"))]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ZeroBox", console=False,
          icon="assets/zerobox.ico", version="version_info.txt", upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="ZeroBox", upx=False)
