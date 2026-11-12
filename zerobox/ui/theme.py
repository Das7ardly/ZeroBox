from PySide6.QtGui import QColor, QPalette

# same neutral base as ZeroPDF / ZeroGuard; each Zero app has its own accent
C = {
    "bg": "#121418",
    "surface": "#1a1d23",
    "surface2": "#22262e",
    "surface3": "#2b3039",
    "border": "#333945",
    "text": "#e7e9ee",
    "muted": "#8d94a3",
    "accent": "#f2a541",      # cardboard amber
    "accent_hi": "#ffbe66",
    "ok": "#3ecf8e",
    "warn": "#f5b942",
    "bad": "#ff5d6c",
    "on_accent": "#ffffff",
    "cut": "#ff5d6c",
    "fold": "#4c9be8",
    "root": "#f2a541",
}


def _lum(hex_):
    c = QColor(hex_)
    out = []
    for v in (c.redF(), c.greenF(), c.blueF()):
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# white on amber is < 4.5:1, so buttons and selections use dark text
if contrast(C["on_accent"], C["accent"]) < 4.5:
    C["on_accent"] = "#1a1206"
assert contrast(C["on_accent"], C["accent"]) >= 4.5
assert contrast(C["text"], C["bg"]) >= 7


def palette():
    p = QPalette()
    p.setColor(QPalette.Window, QColor(C["bg"]))
    p.setColor(QPalette.WindowText, QColor(C["text"]))
    p.setColor(QPalette.Base, QColor(C["surface"]))
    p.setColor(QPalette.AlternateBase, QColor(C["surface2"]))
    p.setColor(QPalette.Text, QColor(C["text"]))
    p.setColor(QPalette.Button, QColor(C["surface2"]))
    p.setColor(QPalette.ButtonText, QColor(C["text"]))
    p.setColor(QPalette.Highlight, QColor(C["accent"]))
    p.setColor(QPalette.HighlightedText, QColor(C["on_accent"]))
    p.setColor(QPalette.ToolTipBase, QColor(C["surface3"]))
    p.setColor(QPalette.ToolTipText, QColor(C["text"]))
    p.setColor(QPalette.PlaceholderText, QColor(C["muted"]))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(C["muted"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(C["muted"]))
    return p


def qss(check_png="", dash_png=""):
    c = C
    return f"""
* {{ font-size: 10pt; }}
QWidget {{ color: {c['text']}; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QFrame#card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QLabel#h {{ font-size: 11pt; font-weight: 600; }}
QLabel#muted {{ color: {c['muted']}; }}
QLabel#title {{ font-size: 14pt; font-weight: 700; }}
QLineEdit, QComboBox {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 6px 9px;
  selection-background-color: {c['accent']}; selection-color: {c['on_accent']}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['surface2']}; border: 1px solid {c['border']};
  selection-background-color: {c['accent']}; selection-color: {c['on_accent']}; outline: 0; }}
QPushButton {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ background: {c['surface3']}; }}
QPushButton:pressed {{ background: {c['border']}; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['surface']}; }}
QPushButton#primary {{ background: {c['accent']}; color: {c['on_accent']}; border: 1px solid {c['accent']}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {c['accent_hi']}; border-color: {c['accent_hi']}; }}
QPushButton#primary:disabled {{ background: {c['surface3']}; color: {c['muted']}; border-color: {c['border']}; }}
QPushButton#seg {{ border-radius: 0; padding: 6px 14px; }}
QPushButton#seg:checked {{ background: {c['accent']}; color: {c['on_accent']}; border-color: {c['accent']}; }}
QPushButton#tool {{ padding: 5px 10px; }}
QListWidget, QTableWidget {{ background: {c['surface']}; alternate-background-color: {c['surface2']};
  border: 1px solid {c['border']}; border-radius: 10px; gridline-color: transparent;
  selection-background-color: {c['surface3']}; selection-color: {c['text']}; outline: 0; }}
QListWidget::item, QTableWidget::item {{ padding: 4px 6px; border: none; }}
QListWidget::item:selected, QTableWidget::item:selected {{ background: {c['surface3']}; color: {c['text']}; }}
QHeaderView::section {{ background: {c['surface']}; color: {c['muted']}; border: none;
  border-bottom: 1px solid {c['border']}; padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {c['surface']}; border: none; }}
QSlider::groove:horizontal {{ height: 6px; background: {c['surface3']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {c['text']}; width: 16px; margin: -6px 0; border-radius: 8px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QListWidget::indicator {{ width: 16px; height: 16px; border-radius: 4px;
  border: 1px solid {c['muted']}; background: {c['surface2']}; }}
QCheckBox::indicator:checked, QListWidget::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']};
  image: url({check_png}); }}
QMenu {{ background: {c['surface2']}; border: 1px solid {c['border']}; padding: 4px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['accent']}; color: {c['on_accent']}; }}
QToolTip {{ background: {c['surface3']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['surface3']}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['surface3']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QStatusBar {{ background: {c['surface']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
QScrollArea {{ background: transparent; }}
"""
