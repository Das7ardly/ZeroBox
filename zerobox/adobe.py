"""Pull the die and artwork straight from a running Illustrator or Photoshop (COM)."""
from __future__ import annotations

import os
import tempfile

from . import dieline

PS_PIXELS = 1


class AdobeError(Exception):
    pass


def _active(progids):
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        raise AdobeError("Връзката с Adobe работи само под Windows.")
    pythoncom.CoInitialize()
    for pid in progids:
        try:
            return win32com.client.GetActiveObject(pid)
        except Exception:
            continue
    return None


# ---------------------------------------------------------------- Illustrator

ILLUSTRATOR_IDS = ["Illustrator.Application"] + [f"Illustrator.Application.{v}" for v in range(30, 22, -1)]


def illustrator_document():
    """(app, doc) of the front Illustrator document, or raise AdobeError."""
    app = _active(ILLUSTRATOR_IDS)
    if app is None:
        raise AdobeError("Illustrator не е отворен (или не е регистриран за автоматизация).\n"
                         "Отвори документа в Illustrator и опитай пак, или копирай щанцата (Ctrl+C) "
                         "и я постави тук с Ctrl+V.")
    try:
        if app.Documents.Count == 0:
            raise AdobeError("В Illustrator няма отворен документ.")
        return app, app.ActiveDocument
    except AdobeError:
        raise
    except Exception as e:
        raise AdobeError(f"Illustrator не отговаря: {e}")


def illustrator_state(doc):
    """(path or '', has_unsaved_changes)"""
    try:
        path = str(doc.FullName or "")
    except Exception:
        path = ""
    try:
        saved = bool(doc.Saved)
    except Exception:
        saved = False
    if path and not os.path.exists(path):
        path = ""
    return path, not saved


def illustrator_save(doc):
    try:
        doc.Save()
    except Exception as e:
        raise AdobeError(f"Illustrator не можа да запази документа: {e}")


def illustrator_copy_all(app):
    """Select everything and copy it to the clipboard (Illustrator puts PDF data there)."""
    try:
        app.ExecuteMenuCommand("selectall")
        app.ExecuteMenuCommand("copy")
    except Exception as e:
        raise AdobeError(f"Копирането от Illustrator не успя: {e}")


# ---------------------------------------------------------------- Photoshop

def _xy(v):
    return float(v[0]), float(v[1])


def from_photoshop() -> dieline.DieSource:
    app = _active(["Photoshop.Application"])
    if app is None:
        raise AdobeError("Photoshop не е отворен. Отвори документа в Photoshop и опитай пак.")
    try:
        if app.Documents.Count == 0:
            raise AdobeError("В Photoshop няма отворен документ.")
        doc = app.ActiveDocument
    except AdobeError:
        raise
    except Exception as e:
        raise AdobeError(f"Photoshop не отговаря: {e}")

    old_units = app.Preferences.RulerUnits
    app.Preferences.RulerUnits = PS_PIXELS
    try:
        w_px, h_px = float(doc.Width), float(doc.Height)
        res = float(doc.Resolution) or 72.0
        k = 72.0 / res
        groups = []
        for item in doc.PathItems:
            g = dieline.LineGroup(f"path|{item.Name}", str(item.Name), (0.9, 0.1, 0.1), 1.0, False)
            for sub in item.SubPathItems:
                pts = list(sub.PathPoints)
                if not pts:
                    continue
                anchors = [_xy(p.Anchor) for p in pts]
                outs = [_xy(p.RightDirection) for p in pts]
                ins = [_xy(p.LeftDirection) for p in pts]
                poly = [anchors[0]]
                closed = bool(sub.Closed)
                n = len(pts)
                for i in range(n if closed else n - 1):
                    j = (i + 1) % n
                    if outs[i] == anchors[i] and ins[j] == anchors[j]:
                        poly.append(anchors[j])
                    else:
                        poly.extend(dieline._bezier(anchors[i], outs[i], ins[j], anchors[j]))
                if closed and len(poly) > 2:
                    poly = poly[:-1]
                g.strokes.append(dieline.Stroke([(x * k, y * k) for x, y in poly], closed))
            if g.strokes:
                g.selected = True
                groups.append(g)
        fd, png = tempfile.mkstemp(suffix=".png", prefix="zerobox_ps_")
        os.close(fd)
        try:
            import win32com.client
            opts = win32com.client.Dispatch("Photoshop.PNGSaveOptions")
            doc.SaveAs(png, opts, True)
            with open(png, "rb") as f:
                art = f.read()
        finally:
            try:
                os.remove(png)
            except OSError:
                pass
    except AdobeError:
        raise
    except Exception as e:
        raise AdobeError(f"Четенето от Photoshop не успя: {e}")
    finally:
        try:
            app.Preferences.RulerUnits = old_units
        except Exception:
            pass

    w, h = w_px * k, h_px * k
    name = str(doc.Name)
    src = dieline.DieSource(name, w, h, groups, "image", art, 0, (0, 0, w, h), "photoshop")
    if len(groups) > 1:
        dieline.auto_select(src.groups)
        if not any(g.selected for g in src.groups):
            for g in src.groups:
                g.selected = True
    return src
