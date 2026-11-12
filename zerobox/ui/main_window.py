from __future__ import annotations

import copy
import os
import traceback

from PySide6.QtCore import QObject, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QColorSpace, QGuiApplication, QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QScrollArea,
                               QSlider, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget, QColorDialog, QApplication)

from .. import APP_NAME, adobe, check, roles, dieline, fold3d, geometry
from ..settings import Settings
from . import brand, render
from .theme import C
from .views import LightPad, View2D, View3D

PREVIEW_PX = 2600
MM = 25.4 / 72


class _Bridge(QObject):
    done = Signal(object, object)
    failed = Signal(object, str)


def run_bg(fn, on_done, on_error):
    """Run fn() on the thread pool, deliver the result on the GUI thread."""
    br = _Bridge()
    br.done.connect(lambda _b, r: on_done(r))
    br.failed.connect(lambda _b, msg: on_error(msg))
    _keep.add(br)

    def job():
        try:
            r = fn()
        except Exception as e:                        # noqa: BLE001 - shown to the user
            traceback.print_exc()
            try:
                br.failed.emit(br, str(e) or e.__class__.__name__)
            except RuntimeError:
                pass                                  # the window closed meanwhile
            return
        try:
            br.done.emit(br, r)
        except RuntimeError:
            pass
        finally:
            QTimer.singleShot(0, lambda: _keep.discard(br))
    QThreadPool.globalInstance().start(job)


_keep: set = set()


def card(title=None):
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(8)
    if title:
        lb = QLabel(title)
        lb.setObjectName("h")
        lay.addWidget(lb)
    return f, lay


def swatch(color, dashed=False):
    img = QImage(28, 14, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    from PySide6.QtGui import QPainter, QPen
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor.fromRgbF(*color), 3, Qt.DashLine if dashed else Qt.SolidLine)
    p.setPen(pen)
    p.drawLine(2, 7, 26, 7)
    p.end()
    return QIcon(QPixmap.fromImage(img))


class ExportDialog(QDialog):
    def __init__(self, st: Settings, aspect: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Експорт на изображение")
        self.st = st
        self.aspect = aspect
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.fmt = QComboBox()
        for name, ext in (("JPEG", "jpg"), ("PNG", "png"), ("TIFF", "tif"), ("WebP", "webp"), ("BMP", "bmp")):
            self.fmt.addItem(name, ext)
        self.fmt.setCurrentIndex(max(0, self.fmt.findText(st.export_format)))
        form.addRow("Формат", self.fmt)
        self.width_ = QComboBox()
        for w in (1200, 2000, 3000, 4000, 6000, 8000):
            self.width_.addItem(f"{w} px", w)
        i = self.width_.findData(st.export_width)
        self.width_.setCurrentIndex(i if i >= 0 else 2)
        form.addRow("Ширина", self.width_)
        self.aspect_cb = QComboBox()
        for label, key in (("4:5 (продуктова снимка)", "4:5"), ("1:1 (квадрат)", "1:1"), ("3:2", "3:2"),
                           ("16:9", "16:9"), ("Като изгледа", "view")):
            self.aspect_cb.addItem(label, key)
        self.aspect_cb.setCurrentIndex(max(0, self.aspect_cb.findData(st.export_aspect)))
        form.addRow("Пропорции", self.aspect_cb)
        self.size_lbl = QLabel()
        self.size_lbl.setObjectName("muted")
        form.addRow("", self.size_lbl)
        self.fill = QCheckBox("Центрирай кутията и запълни кадъра")
        self.fill.setChecked(st.export_fill)
        form.addRow("", self.fill)
        self.bg = QComboBox()
        for label, key in (("Бял", "white"), ("Прозрачен (PNG, TIFF, WebP)", "transparent"),
                           ("Студио (сив градиент)", "studio"), ("Цвят…", "color")):
            self.bg.addItem(label, key)
        self.bg.setCurrentIndex(max(0, self.bg.findData(st.export_background)))
        form.addRow("Фон", self.bg)
        self.color = st.export_color
        self.shadow = QCheckBox("Сянка под кутията")
        self.shadow.setChecked(st.shadow)
        form.addRow("", self.shadow)
        self.quality = QComboBox()
        for q in (80, 90, 95, 100):
            self.quality.addItem(str(q), q)
        self.quality.setCurrentIndex(max(0, self.quality.findData(st.export_quality)))
        form.addRow("JPEG качество", self.quality)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Запази…")
        bb.button(QDialogButtonBox.Ok).setObjectName("primary")
        bb.button(QDialogButtonBox.Cancel).setText("Отказ")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.width_.currentIndexChanged.connect(self._upd)
        self.aspect_cb.currentIndexChanged.connect(self._upd)
        self.fmt.currentIndexChanged.connect(self._upd)
        self.bg.activated.connect(self._bg_pick)
        self._upd()

    def _bg_pick(self):
        if self.bg.currentData() == "color":
            c = QColorDialog.getColor(QColor(self.color), self, "Цвят на фона")
            if c.isValid():
                self.color = c.name()

    def ratio(self):
        key = self.aspect_cb.currentData()
        if key == "view":
            return self.aspect
        a, b = key.split(":")
        return float(a) / float(b)

    def _upd(self):
        w = self.width_.currentData()
        self.size_lbl.setText(f"{w} × {int(w / self.ratio())} px")
        self.quality.setEnabled(self.fmt.currentText() in ("JPEG", "WebP"))

    def values(self):
        st = self.st
        st.export_format = self.fmt.currentText()
        st.export_width = self.width_.currentData()
        st.export_background = self.bg.currentData()
        st.export_color = self.color
        st.export_quality = self.quality.currentData()
        st.shadow = self.shadow.isChecked()
        st.export_aspect = self.aspect_cb.currentData()
        st.export_fill = self.fill.isChecked()
        return st


class MainWindow(QMainWindow):
    def __init__(self, st: Settings):
        super().__init__()
        self.st = st
        self.src = None
        self.model = None
        self.root = None
        self.angle_overrides = {}
        self.art = None
        self.art_rect = None
        self._art_key = None
        self.manual = geometry.Manual()
        self.shapes = []                    # hand-drawn panels (die pt), shared with the 2D view
        self._loading = 0
        self._build_gen = 0
        self.setWindowTitle(f"{APP_NAME} — щанца в 3D кутия")
        self.setWindowIcon(brand.app_icon())
        self.resize(1360, 860)
        self._build()
        self._shortcuts()
        self._rebuild_timer = QTimer(self, singleShot=True, interval=250, timeout=self._rebuild)
        if st.geometry:
            from PySide6.QtCore import QByteArray
            self.restoreGeometry(QByteArray.fromBase64(st.geometry.encode()))

    # ------------------------------------------------------------ layout
    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(12)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 14, 0)
        sl.setSpacing(10)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(brand.logo_pixmap(34))
        head.addWidget(logo)
        tl = QVBoxLayout()
        tl.setSpacing(0)
        t = QLabel(APP_NAME)
        t.setObjectName("title")
        tl.addWidget(t)
        sub = QLabel("щанца → 3D кутия")
        sub.setObjectName("muted")
        tl.addWidget(sub)
        head.addLayout(tl)
        head.addStretch()
        sl.addLayout(head)

        c, lay = card("Източник")
        g = QGridLayout()
        g.setSpacing(6)
        self.b_open = QPushButton(brand.line_icon("open"), " Отвори файл")
        self.b_paste = QPushButton(brand.line_icon("paste"), " Постави")
        self.b_ai = QPushButton(brand.line_icon("ai"), " От Illustrator")
        self.b_ps = QPushButton(brand.line_icon("ps"), " От Photoshop")
        self.b_open.setToolTip("Отвори .ai, .pdf или .svg (Ctrl+O)")
        self.b_paste.setToolTip("Постави щанца, копирана от Illustrator (Ctrl+V).\n"
                                "Ако в клипборда има картинка, тя става дизайн върху текущата щанца.")
        self.b_ai.setToolTip("Взима активния документ от отворения Illustrator")
        self.b_ps.setToolTip("Взима активния документ от отворения Photoshop:\n"
                             "пътищата (Paths) са щанцата, изображението е дизайнът")
        for i, b in enumerate((self.b_open, self.b_paste, self.b_ai, self.b_ps)):
            g.addWidget(b, i // 2, i % 2)
        lay.addLayout(g)
        self.src_lbl = QLabel("Няма зареден файл")
        self.src_lbl.setObjectName("muted")
        self.src_lbl.setWordWrap(True)
        lay.addWidget(self.src_lbl)
        self.b_art = QPushButton("Смени дизайна с изображение…")
        self.b_art.setToolTip("Постави PNG/JPG/TIFF (напр. експорт от Photoshop) върху\n"
                              "цялата площ на щанцата")
        lay.addWidget(self.b_art)
        sl.addWidget(c)

        c, lay = card("Линии на щанцата")
        hint = QLabel("Какво е всяка група линии. Предложено автоматично — поправи, ако трябва. "
                      "Поправките се запомнят за следващите файлове със същите цветове.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.groups_table = QTableWidget(0, 2)
        self.groups_table.setHorizontalHeaderLabels(["Линии", "Роля"])
        self.groups_table.verticalHeader().setVisible(False)
        self.groups_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.groups_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.groups_table.setColumnWidth(1, 150)
        self.groups_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.groups_table.setMinimumHeight(150)
        lay.addWidget(self.groups_table)
        self.rules_lbl = QLabel("")
        self.rules_lbl.setObjectName("muted")
        self.rules_lbl.setWordWrap(True)
        lay.addWidget(self.rules_lbl)
        row = QHBoxLayout()
        self.b_redetect = QPushButton("Разпознай отново")
        self.b_redetect.setToolTip("Предложи ролите наново, без запомнените правила")
        self.b_forget = QPushButton("Забрави правилата")
        self.b_forget.setToolTip("Изтрий всички запомнени правила за цветовете на линиите")
        row.addWidget(self.b_redetect)
        row.addWidget(self.b_forget)
        lay.addLayout(row)
        sl.addWidget(c)

        c, lay = card("Сгъвки")
        self.folds = QTableWidget(0, 3)
        self.folds.setHorizontalHeaderLabels(["№", "Дължина", "Ъгъл °"])
        self.folds.verticalHeader().setVisible(False)
        self.folds.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.folds.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.folds.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.folds.setSelectionMode(QAbstractItemView.SingleSelection)
        self.folds.setMinimumHeight(180)
        self.folds.setToolTip("Двоен клик върху ъгъла, за да го промениш.\n"
                              "90 = нормално сгъване, 0 = остава плоско, отрицателен = на другата страна")
        lay.addWidget(self.folds)
        self.b_auto = QPushButton("Автоматично затваряне")
        self.b_auto.setObjectName("primary")
        self.b_auto.setToolTip("Намира ъглите, при които кутията се затваря — и за шестоъгълни,\n"
                               "триъгълни, тави с наклонени стени, пирамиди и др.\n"
                               "Изчиства ръчно въведените ъгли.")
        lay.addWidget(self.b_auto)
        row = QHBoxLayout()
        self.b_all90 = QPushButton("Всички 90°")
        self.b_flip = QPushButton("Обърни избраната")
        row.addWidget(self.b_all90)
        row.addWidget(self.b_flip)
        lay.addLayout(row)
        self.solve_lbl = QLabel("")
        self.solve_lbl.setObjectName("muted")
        self.solve_lbl.setWordWrap(True)
        lay.addWidget(self.solve_lbl)
        self.issues_lbl = QLabel("")
        self.issues_lbl.setWordWrap(True)
        self.issues_lbl.setTextFormat(Qt.RichText)
        self.issues_lbl.setToolTip("След всяко сгъване програмата проверява за панели, които стърчат,\n"
                                   "минават един през друг или оставят кутията отворена, и опитва\n"
                                   "сама да поправи ъглите. Каквото остане, е изброено тук и е червено в 2D.")
        lay.addWidget(self.issues_lbl)
        tip = QLabel("Двоен клик върху панел в „Щанца 2D“ го прави лицев.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        sl.addWidget(c)

        c, lay = card("Снимка")
        row = QHBoxLayout()
        lbl = QLabel("Обектив")
        lbl.setObjectName("muted")
        row.addWidget(lbl)
        self.lens = QComboBox()
        for label, mm in fold3d.LENSES:
            self.lens.addItem(label, mm)
        self.lens.setToolTip("Перспектива като с този обектив на full-frame фотоапарат.\n"
                             "85 и 105 mm дават естествени, неизкривени пропорции на кутията.")
        i = self.lens.findData(self.st.lens)
        self.lens.setCurrentIndex(i if i >= 0 else 2)
        row.addWidget(self.lens, 1)
        lay.addLayout(row)
        self.cb_straight = QCheckBox("Прави вертикали (shift)")
        self.cb_straight.setToolTip("Вертикалните ръбове остават успоредни, както при продуктова снимка\n"
                                    "с shift обектив — кутията е точно по гайдовете")
        self.cb_straight.setChecked(self.st.straight)
        lay.addWidget(self.cb_straight)
        self.cb_lines = QCheckBox("Без линии на щанцата")
        self.cb_lines.setToolTip("Изтрива щанцовите линии от дизайна и тъмния контур по ръбовете")
        self.cb_lines.setChecked(self.st.hide_lines)
        lay.addWidget(self.cb_lines)
        self.cb_shadow = QCheckBox("Сянка под кутията")
        self.cb_shadow.setChecked(self.st.shadow)
        lay.addWidget(self.cb_shadow)
        sl.addWidget(c)

        c, lay = card("Светлина")
        self.light = QComboBox()
        for label, key in (("Оригинални цветове", "original"), ("Мека", "soft"), ("Контрастна", "contrast"),
                           ("Ръчна", "manual")):
            self.light.addItem(label, key)
        self.light.setCurrentIndex(max(0, self.light.findData(self.st.light)))
        lay.addWidget(self.light)
        row = QHBoxLayout()
        self.pad = LightPad()
        row.addWidget(self.pad)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.s_strength, self.l_strength = self._slider(col, "Сенки", 0, 90, self.st.light_strength, "%")
        self.s_exposure, self.l_exposure = self._slider(col, "Яркост", 80, 120, self.st.light_exposure, "%")
        col.addStretch()
        row.addLayout(col, 1)
        lay.addLayout(row)
        sl.addWidget(c)
        sl.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setFixedWidth(356)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        # ---- right side
        right = QVBoxLayout()
        right.setSpacing(8)
        top = QHBoxLayout()
        self.seg = QButtonGroup(self)
        for i, name in enumerate(("3D кутия", "Щанца 2D")):
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.seg.addButton(b, i)
            top.addWidget(b)
        top.setSpacing(0)
        top.addStretch()
        self.b_copy = QPushButton(brand.line_icon("copy"), " Копирай")
        self.b_copy.setToolTip("Копира изображението в клипборда (за имейл, Slack, Photoshop…)")
        self.b_export = QPushButton(brand.line_icon("export", color=C["on_accent"]), " Експорт…")
        self.b_export.setObjectName("primary")
        self.b_export.setToolTip("Запази като JPEG, PNG, TIFF… (Ctrl+E)")
        top.addWidget(self.b_copy)
        top.addSpacing(6)
        top.addWidget(self.b_export)
        right.addLayout(top)

        self.stack = QStackedWidget()
        self.view3d = View3D()
        self.view2d = View2D()
        self.stack.addWidget(self.view3d)
        page2d = QWidget()
        l2 = QVBoxLayout(page2d)
        l2.setContentsMargins(8, 8, 8, 0)
        l2.setSpacing(6)
        shapes_row = QHBoxLayout()
        shapes_row.setSpacing(0)
        lbl = QLabel("Ръчни форми:  ")
        lbl.setObjectName("muted")
        shapes_row.addWidget(lbl)
        self.tool_group = QButtonGroup(self)
        for i, (name, tip) in ((5, ("Панел", "Влачи, за да нарисуваш правоъгълен панел")),
                               (6, ("Многоъгълник", "Кликни ъглите; двоен клик = готово")),
                               (7, ("Редактирай", "Премести, промени размера или изтрий форма"))):
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setToolTip(tip)
            self.tool_group.addButton(b, i)
            shapes_row.addWidget(b)
        shapes_row.addSpacing(10)
        self.b_clear_shapes = QPushButton("Изчисти формите")
        self.b_clear_shapes.setToolTip("Махни всички нарисувани форми и се върни към разпознатата щанца")
        shapes_row.addWidget(self.b_clear_shapes)
        shapes_row.addStretch()
        self.shapes_lbl = QLabel("")
        self.shapes_lbl.setObjectName("muted")
        shapes_row.addWidget(self.shapes_lbl)
        l2.addLayout(shapes_row)
        tools = QHBoxLayout()
        tools.setSpacing(0)
        for i, (name, tip) in enumerate((
                ("Избор", "Клик върху сгъвка = избери я; двоен клик върху панел = лицев"),
                ("Лице", "Клик върху панел = това е лицето на кутията"),
                ("Сгъвка ↔ Рязане", "Клик върху линия между два панела сменя сгъвка и рязане"),
                ("Слей", "Клик върху сгъвка: двата панела остават плоски като едно цяло"),
                ("Изключи панел", "Клик върху панел: не е част от кутията (клик пак = върни)"))):
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setToolTip(tip)
            self.tool_group.addButton(b, i)
            tools.addWidget(b)
        tools.addSpacing(10)
        self.b_reset_manual = QPushButton("Нулирай ръчните")
        self.b_reset_manual.setToolTip("Махни всички ръчни отметки и разпознай щанцата автоматично")
        tools.addWidget(self.b_reset_manual)
        tools.addStretch()
        self.manual_lbl = QLabel("")
        self.manual_lbl.setObjectName("muted")
        tools.addWidget(self.manual_lbl)
        l2.addLayout(tools)
        l2.addWidget(self.view2d, 1)
        self.stack.addWidget(page2d)
        vf = QFrame()
        vf.setObjectName("card")
        vl = QVBoxLayout(vf)
        vl.setContentsMargins(1, 1, 1, 1)
        vl.addWidget(self.stack)
        right.addWidget(vf, 1)

        bar = QHBoxLayout()
        lbl = QLabel("Изглед")
        lbl.setObjectName("muted")
        bar.addWidget(lbl)
        bar.addStretch()
        bar.addSpacing(10)
        self.view_buttons = []
        for name, yaw, pitch in (("Отпред", 0, 0), ("3/4", -32, 18), ("Отстрани", -90, 0),
                                 ("Отзад", 180, 12), ("Отгоре", -20, 70), ("Отдолу", -20, -60)):
            b = QPushButton(name)
            b.setObjectName("tool")
            b.clicked.connect(lambda _=False, y=yaw, p=pitch: self.view3d.set_view(y, p))
            bar.addWidget(b)
            self.view_buttons.append(b)
        self.b_roll = QPushButton(brand.line_icon("rotate"), "")
        self.b_roll.setObjectName("tool")
        self.b_roll.setToolTip("Завърти кутията на 90° (ако щанцата е легнала)")
        bar.addWidget(self.b_roll)
        right.addLayout(bar)
        self.bottom_bar = bar
        root.addLayout(right, 1)

        self.status = self.statusBar()
        self.dims = QLabel("")
        self.status.addPermanentWidget(self.dims)
        self.status.showMessage("Влачи с мишката = въртене · Shift/десен бутон = местене · колелце = мащаб · двоен клик = нулиране")

        self.view3d.opts.board = self.st.board_color
        self.view3d.opts.shadow = self.st.shadow
        self.view3d.opts.outline = not self.st.hide_lines
        self.view3d.cam.fov = fold3d.lens_fov(self.lens.currentData())
        self.view3d.cam.shift = self.st.straight
        self.pad.set_pos(self.st.light_x, self.st.light_y)
        self._apply_light()

        # signals
        self.b_open.clicked.connect(self.open_file)
        self.b_paste.clicked.connect(self.paste)
        self.b_ai.clicked.connect(self.from_illustrator)
        self.b_ps.clicked.connect(self.from_photoshop)
        self.b_art.clicked.connect(self.replace_art)
        self.b_redetect.clicked.connect(self.redetect)
        self.b_forget.clicked.connect(self._forget_rules)
        self.folds.itemChanged.connect(self._angle_edited)
        self.folds.itemSelectionChanged.connect(self._fold_selected)
        self.b_all90.clicked.connect(self.all90)
        self.b_auto.clicked.connect(self.auto_close)
        self.b_flip.clicked.connect(self.flip_fold)
        self.seg.idClicked.connect(self._tab)
        self.b_roll.clicked.connect(self.roll)
        self.cb_shadow.toggled.connect(self._shadow)
        self.cb_lines.toggled.connect(self._lines)
        self.lens.currentIndexChanged.connect(self._lens)
        self.light.currentIndexChanged.connect(self._light_preset)
        self.pad.changed.connect(self._light_manual)
        self.s_strength.valueChanged.connect(self._light_manual)
        self.s_exposure.valueChanged.connect(self._light_manual)

        self.cb_straight.toggled.connect(self._straight)
        self.b_export.clicked.connect(self.export)
        self.b_copy.clicked.connect(self.copy_image)
        self.view2d.foldClicked.connect(self._select_fold_row)
        self.view2d.rootRequested.connect(self.set_root)
        self.view2d.edgeClicked.connect(self._edge_clicked)
        self.view2d.faceClicked.connect(self._face_clicked)
        self.tool_group.idClicked.connect(lambda i: self.view2d.set_tool(View2D.TOOLS[i]))
        self.b_reset_manual.clicked.connect(self._reset_manual)
        self.b_clear_shapes.clicked.connect(self._clear_shapes)
        self.view2d.shapes = self.shapes
        self.view2d.shapesChanged.connect(self._shapes_changed)
        self.setAcceptDrops(True)
        self._enable()

    def _slider(self, lay, name, lo, hi, val, unit, div=1):
        head = QHBoxLayout()
        lb = QLabel(name)
        lb.setObjectName("muted")
        head.addWidget(lb)
        head.addStretch()
        value = QLabel()
        head.addWidget(value)
        lay.addLayout(head)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(int(val))

        def show(v):
            value.setText(f"{v / div:g}{unit}" if div != 1 else f"{v}{unit}")
        show(sl.value())
        sl.valueChanged.connect(show)
        lay.addWidget(sl)
        return sl, value

    def _shortcuts(self):
        QShortcut(QKeySequence.Open, self, self.open_file)
        QShortcut(QKeySequence.Paste, self, self.paste)
        QShortcut(QKeySequence("Ctrl+E"), self, self.export)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self.copy_image)

    def _enable(self):
        has = self.model is not None
        for w in (self.b_export, self.b_copy, self.b_all90, self.b_flip, self.b_auto,
                  self.b_roll, self.b_redetect, *self.view_buttons):
            w.setEnabled(has)
        self.b_art.setEnabled(self.src is not None and bool(self.src.groups))

    # ------------------------------------------------------------ loading
    def _busy(self, msg):
        self._loading += 1
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.status.showMessage(msg)
        self.view3d.message = msg if self.model is None else ""
        self.view3d.update()

    def _unbusy(self, msg=""):
        self._loading = max(0, self._loading - 1)
        QApplication.restoreOverrideCursor()
        self.view3d.message = ""
        self.view3d.update()
        if msg:
            self.status.showMessage(msg, 8000)

    def _error(self, title, msg):
        self._unbusy()
        QMessageBox.warning(self, title, msg)

    def open_file(self):
        fn, _ = QFileDialog.getOpenFileName(
            self, "Отвори щанца", self.st.last_dir,
            "Щанци и дизайни (*.ai *.pdf *.svg);;Изображения (*.png *.jpg *.jpeg *.tif *.tiff);;Всички файлове (*.*)")
        if fn:
            self.st.last_dir = os.path.dirname(fn)
            self.load_path(fn)

    def load_path(self, fn):
        ext = os.path.splitext(fn)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp") and self.src and self.src.groups:
            with open(fn, "rb") as f:
                self._set_art_image(f.read(), os.path.basename(fn))
            return
        self._busy(f"Зареждане на {os.path.basename(fn)}…")
        run_bg(lambda: dieline.load_file(fn), self._source_loaded,
               lambda m: self._error("Файлът не може да се отвори", m))

    def _source_loaded(self, src):
        self._unbusy()
        self.set_source(src)

    def set_source(self, src):
        self.src = src
        self.root = None
        self.manual = geometry.Manual()
        self.angle_overrides = {}
        self.shapes.clear()
        self.view2d.sel_shape = -1
        self.art = None
        self._art_key = None
        self.src_lbl.setText(src.name)
        self._rules_used = roles.apply_rules(src.groups, self.st.line_rules)
        self._fill_groups()
        skipped = [g for g in src.groups if getattr(g, "rule_skipped", False)]
        if skipped:
            self.status.showMessage(
                f"Запомнено правило не е приложено за {len(skipped)} група линии — тук те са графика "
                f"({', '.join(str(len(g.strokes)) for g in skipped)} линии). Ако са щанца, избери ролята ръчно.",
                15000)
        if not src.groups:
            QMessageBox.information(self, APP_NAME, "В този източник няма векторни линии (щанца).\n"
                                    "Отвори .ai/.pdf с щанцата, а после „Смени дизайна с изображение…“.")
        self._rebuild()
        self._enable()

    def _fill_groups(self):
        t = self.groups_table
        t.setRowCount(0)
        groups = sorted(self.src.groups, key=lambda g: (not g.selected, -g.length))
        for g in groups:
            r = t.rowCount()
            t.insertRow(r)
            style = "пунктир" if g.dashed else "плътна"
            it = QTableWidgetItem(swatch(g.color, g.dashed), f"{g.width:.2f}pt · {len(g.strokes)}")
            it.setData(Qt.UserRole + 1, style)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            x0, y0, x1, y1 = g.bbox()
            it.setToolTip(f"{g.label()}\nОбща дължина: {g.length * MM:.0f} mm\n"
                          f"Обхват: {(x1 - x0) * MM:.0f} × {(y1 - y0) * MM:.0f} mm")
            t.setItem(r, 0, it)
            cb = QComboBox()
            for key, label in roles.ROLES.items():
                cb.addItem(label, key)
            cb.setCurrentIndex(max(0, cb.findData(g.role if g.selected else "ignore")))
            cb.setMinimumContentsLength(11)
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setToolTip("Рязане: контур и прорези · Сгъване: бигове · Перфорация: сгъва се като биг\n"
                          "Щанца (авто): рязане и сгъване в една група — сгъвките се намират по формата\n"
                          "Не е щанца: графика, текст, рамки")
            cb.currentIndexChanged.connect(lambda _i, grp=g, box=cb: self._role_changed(grp, box.currentData()))
            t.setCellWidget(r, 1, cb)
        t.resizeRowsToContents()
        n = len(self.st.line_rules)
        used = getattr(self, "_rules_used", 0)
        self.rules_lbl.setText((f"Запомнени правила: {n}" + (f" · приложени тук: {used}" if used else ""))
                               if n else "")
        self.b_forget.setEnabled(n > 0)

    def _role_changed(self, group, role):
        group.role = role
        group.selected = role != "ignore"
        self.st.line_rules = roles.remember(self.st.line_rules, group)
        try:
            self.st.save()
        except OSError:
            pass
        n = len(self.st.line_rules)
        self.rules_lbl.setText(f"Запомнени правила: {n} · тази промяна ще важи и за следващите файлове")
        self.b_forget.setEnabled(True)
        self._rebuild_timer.start()

    def _forget_rules(self):
        if QMessageBox.question(self, APP_NAME, "Да изтрия ли всички запомнени правила за линиите?") \
                != QMessageBox.Yes:
            return
        self.st.line_rules = []
        self.st.save()
        self._rules_used = 0
        self._fill_groups()
        self.status.showMessage("Правилата са изтрити. „Разпознай отново“ ще предложи ролите наново.", 8000)

    def redetect(self):
        if self.src:
            dieline.auto_select(self.src.groups, (self.src.width, self.src.height))
            self._rules_used = 0
            self._fill_groups()
            self.root = None
            self.manual = geometry.Manual()
            self._rebuild()

    def _rebuild(self, then=None):
        """Fold the die again. The work runs off the GUI thread so a heavy file never
        freezes the window; only the newest request is shown."""
        if self.src is None:
            return
        if self.shapes:
            # the user drew the panels: fold along the edges they share
            strokes = [dieline.Stroke([tuple(q) for q in sh], True) for sh in self.shapes if len(sh) >= 3]
            fold_lines = None
        else:
            strokes = self.src.selected_strokes()
            fold_lines = roles.fold_strokes(self.src.groups)
        overrides, manual = dict(self.angle_overrides), copy.deepcopy(self.manual)
        self._build_gen += 1
        gen = self._build_gen
        self._busy("Сгъвам кутията…")

        def job():
            return (geometry.build(strokes, None, overrides, manual=manual, fold_lines=fold_lines)
                    if strokes else None)

        def done(model):
            self._unbusy()
            if gen == self._build_gen:
                self._model_built(model, strokes)
                if then is not None:
                    then()

        def failed(msg):
            self._unbusy()
            if gen == self._build_gen:
                self.status.showMessage(f"Щанцата не може да се разчете: {msg}", 8000)
                self._model_built(None, strokes)
        run_bg(job, done, failed)

    def _model_built(self, model, strokes):
        if model is not None and len(model.faces) < 2:
            model = None
        self.model = model
        if model is None and strokes:
            self.status.showMessage("Не намирам затворени панели — провери ролите в „Линии на щанцата“.", 10000)
        self.root = model.root if model else None
        self._fill_folds()
        report = ""
        if model and model.solve_report:
            report = "Затваряне: " + model.solve_report
        if model and model.check_report:
            report += ("; " if report else "") + model.check_report
        self.solve_lbl.setText(report)
        self._show_issues()
        self.view2d.model = model
        self.view2d.excluded = self.manual.excluded
        self.view2d.groups = self.src.groups
        m = self.manual
        n = (1 if m.root else 0) + len(m.cuts) + len(m.folds) + len(m.flat) + len(m.excluded)
        self.manual_lbl.setText(f"ръчни промени: {n}" if n else "")
        self.view3d.model = model
        self._update_dims()
        self._enable()
        self._ensure_art()
        self.view2d.update()
        self.view3d.update()

    def _ensure_art(self):
        if self.src is None or self.src.art_kind == "none":
            self.view3d.tex = render.Textures(self.model, None, None) if self.model else None
            return
        bbox = self._art_bbox() if self.model else (0, 0, self.src.width, self.src.height)
        erase = self.st.hide_lines and self.model is not None
        sel = tuple(g.key for g in self.src.groups if g.selected) if erase else ()
        key = (id(self.src), self.src.art_kind, len(self.src.art_data), tuple(round(v) for v in bbox), erase, sel)
        if key == self._art_key and self.art is not None:
            self._apply_art()
            return
        self._art_key = key
        if self.art is not None:
            # until the new render arrives, map the current artwork onto the new panels
            self._apply_art()
        elif self.model is not None:
            self.view3d.tex = render.Textures(self.model, None, None)
        src = self.src
        self._busy("Подготвям дизайна…")

        def done(r):
            self._unbusy("Готово")
            if key != self._art_key:
                return
            self.art, self.art_rect = r
            self._apply_art()
        run_bg(lambda: self._art_job(src, bbox, PREVIEW_PX, erase), done,
               lambda m: self._error("Дизайнът не може да се изобрази", m))

    def _art_bbox(self):
        m = self.model
        if self.shapes and self.src is not None:
            # drawing by hand: keep the whole die / page visible underneath
            pts = [p for g in self.src.groups if g.selected for s in g.strokes for p in s.pts]
            pts += [q for sh in self.shapes for q in sh]
            if not pts:
                return (0, 0, self.src.width, self.src.height)
            return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        return (m.source_bbox or m.bbox) if m is not None else None

    @staticmethod
    def _art_job(src, bbox, px, erase):
        img, rect = render.render_art(src, bbox, px)
        if img is not None and erase:
            img = render.erase_lines(img, rect, src.groups)
        return img, rect

    def _apply_art(self):
        self.view2d.art, self.view2d.art_rect = self.art, self.art_rect
        if self.model is not None:
            self.view3d.tex = render.Textures(self.model, self.art, self.art_rect)
        self.view2d.update()
        self.view3d.update()

    def _set_art_image(self, data: bytes, name: str):
        if not self.src or not self.model:
            return
        x0, y0, x1, y1 = self._art_bbox()
        self.src.art_kind = "image"
        self.src.art_data = data
        self.src.art_rect = (x0, y0, x1, y1)
        self.src_lbl.setText(f"{self.src.name}\nдизайн: {name}")
        self._art_key = None
        self._ensure_art()

    def replace_art(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Изображение за дизайн", self.st.last_dir,
                                            "Изображения (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)")
        if fn:
            with open(fn, "rb") as f:
                self._set_art_image(f.read(), os.path.basename(fn))

    # ------------------------------------------------------------ clipboard & Adobe
    def paste(self):
        md = QGuiApplication.clipboard().mimeData()
        if md is None:
            return
        src = None
        for fmt in md.formats():
            data = bytes(md.data(fmt))
            if not data:
                continue
            i = data.find(b"%PDF", 0, 2048)
            if i >= 0:
                try:
                    src = dieline.load_pdf_bytes(data[i:], "Клипборд (Illustrator)")
                    break
                except Exception:
                    continue
        if src is None:
            for fmt in md.formats():
                if "AI" in fmt.upper() or "POSTSCRIPT" in fmt.upper() or "EPS" in fmt.upper():
                    text = bytes(md.data(fmt)).decode("latin-1", "replace")
                    if "%!PS" in text[:200] or "%%Creator" in text[:2000]:
                        groups = dieline.parse_aicb(text)
                        if groups:
                            src = dieline.normalize(dieline.DieSource("Клипборд (вектори)", 0, 0, groups))
                            dieline.auto_select(src.groups, (src.width, src.height))
                            break
        if src is not None:
            self.set_source(src)
            return
        if md.hasImage():
            img = QImage(md.imageData())
            from PySide6.QtCore import QBuffer, QIODevice
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            if self.model is not None:
                self._set_art_image(bytes(buf.data()), "картинка от клипборда")
                self.status.showMessage("Картинката от клипборда е сложена като дизайн върху щанцата.", 8000)
            else:
                QMessageBox.information(self, APP_NAME, "В клипборда има само картинка.\n"
                                        "Първо зареди щанцата, после постави картинката като дизайн.")
            return
        QMessageBox.information(self, APP_NAME,
                                "В клипборда няма щанца.\nВ Illustrator: избери щанцата и дизайна (Ctrl+A), "
                                "Ctrl+C, после тук Ctrl+V.")

    def from_illustrator(self):
        try:
            app, doc = adobe.illustrator_document()
            path, dirty = adobe.illustrator_state(doc)
            if path and not dirty and os.path.splitext(path)[1].lower() in (".ai", ".pdf"):
                self.load_path(path)
                return
            box = QMessageBox(self)
            box.setWindowTitle("Illustrator")
            if path:
                box.setText("Документът в Illustrator има незапазени промени.")
                b_save = box.addButton("Запази в Illustrator и вземи", QMessageBox.AcceptRole)
            else:
                box.setText("Документът в Illustrator още не е запазван като файл.")
                b_save = None
            b_copy = box.addButton("Копирай всичко през клипборда", QMessageBox.ActionRole)
            box.addButton("Отказ", QMessageBox.RejectRole)
            box.exec()
            if b_save is not None and box.clickedButton() is b_save:
                adobe.illustrator_save(doc)
                self.load_path(path)
            elif box.clickedButton() is b_copy:
                adobe.illustrator_copy_all(app)
                QTimer.singleShot(400, self.paste)
        except adobe.AdobeError as e:
            QMessageBox.information(self, "Illustrator", str(e))

    def from_photoshop(self):
        self._busy("Чета от Photoshop…")
        QApplication.processEvents()
        try:
            src = adobe.from_photoshop()
        except adobe.AdobeError as e:
            self._unbusy()
            QMessageBox.information(self, "Photoshop", str(e))
            return
        self._unbusy()
        self.set_source(src)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.load_path(urls[0])

    # ------------------------------------------------------------ folds
    def _fill_folds(self):
        self.folds.blockSignals(True)
        self.folds.setRowCount(0)
        if self.model:
            for fd in self.model.folds:
                r = self.folds.rowCount()
                self.folds.insertRow(r)
                it = QTableWidgetItem(str(fd.id + 1))
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.folds.setItem(r, 0, it)
                it = QTableWidgetItem(f"{fd.length * MM:.0f} mm")
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.folds.setItem(r, 1, it)
                it = QTableWidgetItem(f"{fd.angle:g}")
                self.folds.setItem(r, 2, it)
        self.folds.blockSignals(False)

    def _angle_edited(self, it):
        if it.column() != 2 or self.model is None:
            return
        fd = self.model.folds[it.row()]
        try:
            v = float(it.text().replace(",", ".").replace("°", ""))
        except ValueError:
            self.folds.blockSignals(True)
            it.setText(f"{fd.angle:g}")
            self.folds.blockSignals(False)
            return
        v = max(-180.0, min(180.0, v))
        fd.angle = v
        self.angle_overrides[geometry.fold_key(fd)] = v
        self._after_fold_edit()

    def _show_issues(self):
        m = self.model
        if m is None:
            self.issues_lbl.setText("")
            self.view2d.issue_faces = set()
            return
        issues = m.issues
        self.view2d.issue_faces = {f for i in issues for f in i.faces}
        if not issues:
            self.issues_lbl.setText(f"<span style='color:{C['ok']}'>✓ Проверка: без нередности</span>")
            return
        rows = "".join(f"<br>• {i.text}" for i in issues[:6])
        more = f"<br>… и още {len(issues) - 6}" if len(issues) > 6 else ""
        self.issues_lbl.setText(f"<span style='color:{C['bad']}'><b>Проверка: {len(issues)} "
                                f"нередност{'' if len(issues) == 1 else 'и'}</b>{rows}{more}</span>"
                                f"<br><span style='color:{C['muted']}'>Опитай „Автоматично затваряне“, "
                                "смени ъгъла в таблицата или нарисувай панелите в „Щанца 2D“.</span>")

    def _after_fold_edit(self):
        if self.model is not None:
            self.model.issues = check.analyze(self.model)
            self._show_issues()
        self._update_dims()
        self.view3d.update()
        self.view2d.update()

    def _fold_selected(self):
        rows = self.folds.selectionModel().selectedRows()
        self.view2d.selected_fold = rows[0].row() if rows else -1
        self.view2d.update()

    def _select_fold_row(self, i):
        self.folds.selectRow(i)

    def auto_close(self):
        if not self.model:
            return
        self.angle_overrides = {}
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._rebuild(lambda: self.model is not None and self.status.showMessage(
                "Автоматично затваряне: " + self.model.solve_report, 12000))
        finally:
            QApplication.restoreOverrideCursor()

    def all90(self):
        if not self.model:
            return
        for fd in self.model.folds:
            if not self.model.faces[fd.child].small:
                fd.angle = 90.0
                self.angle_overrides[geometry.fold_key(fd)] = 90.0
        self._fill_folds()
        self._after_fold_edit()

    def flip_fold(self):
        rows = self.folds.selectionModel().selectedRows()
        if not rows or not self.model:
            QMessageBox.information(self, APP_NAME, "Избери сгъвка в таблицата или я кликни в „Щанца 2D“.")
            return
        fd = self.model.folds[rows[0].row()]
        fd.angle = -fd.angle if fd.angle else 90.0
        self.angle_overrides[geometry.fold_key(fd)] = fd.angle
        r = rows[0].row()
        self._fill_folds()
        self.folds.selectRow(r)
        self._after_fold_edit()

    def set_root(self, key):
        if self.model is None:
            return
        self.manual.root = key
        self.manual.excluded.discard(key)
        self._rebuild(lambda: self.view3d.set_view(0, 0))
        self.status.showMessage("Лицевият панел е сменен.", 5000)

    def _shapes_changed(self):
        n = len(self.shapes)
        self.shapes_lbl.setText(f"сгъване по твоите {n} форми" if n else "")
        self.manual = geometry.Manual()        # panel ids change with the shapes
        self.angle_overrides = {}
        self._rebuild_timer.start()

    def _clear_shapes(self):
        if not self.shapes:
            return
        self.shapes.clear()
        self.view2d.sel_shape = -1
        self._shapes_changed()
        self.status.showMessage("Формите са махнати — сгъването е пак по разпознатата щанца.", 6000)

    def _keep_front(self):
        """Hand edits must not move the front panel: pin the current one."""
        if not self.manual.root and self.model is not None:
            self.manual.root = self.model.faces[self.model.root].key

    def _edge_clicked(self, ek, state):
        self._keep_front()
        m = self.manual
        if self.view2d.tool == "flat":
            if ek in m.flat:
                m.flat.discard(ek)
                msg = "Сгъвката пак се сгъва."
            else:
                m.flat.add(ek)
                msg = "Двата панела остават плоски като едно цяло."
        elif state == "fold":
            m.folds.discard(ek)
            m.cuts.add(ek)
            msg = "Линията е рязане — панелите вече не са сгънати един към друг."
        else:
            m.cuts.discard(ek)
            m.folds.add(ek)
            msg = "Линията е сгъвка — панелът се сгъва по нея."
        self._rebuild()
        self.status.showMessage(msg, 6000)

    def _face_clicked(self, key):
        self._keep_front()
        m = self.manual
        if key in m.excluded:
            m.excluded.discard(key)
            msg = "Панелът е върнат в кутията."
        else:
            if self.model and key == self.model.faces[self.model.root].key:
                self.status.showMessage("Лицевият панел не може да се изключи — първо избери друго лице.", 6000)
                return
            m.excluded.add(key)
            msg = "Панелът е изключен от кутията."
        self._rebuild()
        self.status.showMessage(msg, 6000)

    def _reset_manual(self):
        self.manual = geometry.Manual()
        self.angle_overrides = {}
        self._rebuild()
        self.status.showMessage("Ръчните промени са махнати.", 5000)

    def _update_dims(self):
        if not self.model:
            self.dims.setText("")
            return
        lo, hi = fold3d.bounds3d(self.model, fold3d.face_transforms(self.model, 1.0, self.view3d.roll))
        w, h, d = (hi - lo) * MM
        self.dims.setText(f"Кутия: {w:.0f} × {d:.0f} × {h:.0f} mm (Ш × Д × В)")

    # ------------------------------------------------------------ view controls
    def _tab(self, i):
        self.stack.setCurrentIndex(i)
        for i_ in range(self.bottom_bar.count()):
            w = self.bottom_bar.itemAt(i_).widget()
            if w is not None:
                w.setVisible(i == 0)

    def roll(self):
        self.view3d.roll = (self.view3d.roll + 90) % 360
        self._update_dims()
        self.view3d.update()

    def _lines(self, on):
        self.st.hide_lines = on
        self.view3d.opts.outline = not on
        self._ensure_art()

    def _lens(self):
        mm = self.lens.currentData()
        self.st.lens = mm
        self.view3d.cam.fov = fold3d.lens_fov(mm)
        self.view3d.update()

    def _light_preset(self):
        key = self.light.currentData()
        self.st.light = key
        if key in fold3d.LIGHTS:
            x, y, strength, exposure = fold3d.LIGHTS[key]
            self._setting_preset = True
            self.pad.set_pos(x, y)
            self.s_strength.setValue(strength)
            self.s_exposure.setValue(exposure)
            self._setting_preset = False
        self._apply_light()

    def _light_manual(self, *_):
        if getattr(self, "_setting_preset", False):
            return
        if self.light.currentData() != "manual":
            self.light.blockSignals(True)
            self.light.setCurrentIndex(self.light.findData("manual"))
            self.light.blockSignals(False)
            self.st.light = "manual"
        self._apply_light()

    def _apply_light(self, *_):
        st = self.st
        st.light_x, st.light_y = self.pad.x, self.pad.y
        st.light_strength = self.s_strength.value()
        st.light_exposure = self.s_exposure.value()
        self.pad.strength = st.light_strength / 100
        self.pad.update()
        self._light_into(self.view3d.opts)
        self.view3d.update()

    def _light_into(self, opts):
        st = self.st
        opts.light = (st.light_x, st.light_y)
        opts.strength = st.light_strength / 100
        opts.exposure = st.light_exposure / 100
        return opts

    def _straight(self, on):
        self.st.straight = on
        self.view3d.cam.shift = on
        self.view3d.update()

    def _shadow(self, on):
        self.view3d.opts.shadow = on
        self.st.shadow = on
        self.view3d.update()

    # ------------------------------------------------------------ export
    def _export_image(self, width, opts, ratio=None, fill=False):
        ratio = ratio or self.view3d.width() / max(1, self.view3d.height())
        h = int(width / ratio)
        tex = self.view3d.tex
        need = int(min(9000, max(width, h) * 2.4))
        if self.src and self.src.art_kind != "none" and need > PREVIEW_PX * 1.1:
            img, rect = self._art_job(self.src, self._art_bbox(), need, self.st.hide_lines)
            if img is not None:
                tex = render.Textures(self.model, img, rect)
        opts.outline = not self.st.hide_lines
        return self.view3d.grab_image(width, h, opts, tex, fill)

    def export(self):
        if self.model is None:
            return
        aspect = self.view3d.width() / max(1, self.view3d.height())
        dlg = ExportDialog(self.st, aspect, self)
        if dlg.exec() != QDialog.Accepted:
            return
        st = dlg.values()
        ext = {"JPEG": "jpg", "PNG": "png", "TIFF": "tif", "WebP": "webp", "BMP": "bmp"}[st.export_format]
        base = os.path.splitext(self.src.name)[0] if self.src else "box"
        start = os.path.join(st.export_dir or st.last_dir or os.path.expanduser("~"), f"{base}_3d.{ext}")
        fn, _ = QFileDialog.getSaveFileName(self, "Запази изображението", start, f"{st.export_format} (*.{ext})")
        if not fn:
            return
        st.export_dir = os.path.dirname(fn)
        bg = st.export_background
        if bg == "transparent" and ext in ("jpg", "bmp"):
            bg = "white"
        opts = self._light_into(render.RenderOptions(background=bg, color=st.export_color, board=st.board_color,
                                                     shadow=st.shadow))
        self._busy("Експорт…")
        QApplication.processEvents()
        try:
            img = self._export_image(st.export_width, opts, dlg.ratio(), st.export_fill)
            if ext in ("jpg", "bmp"):
                img = img.convertToFormat(QImage.Format_RGB32)
            # tag as sRGB so Photoshop / Illustrator show the same colours as here
            img.setColorSpace(QColorSpace(QColorSpace.SRgb))
            q = st.export_quality if ext in ("jpg", "webp") else -1
            ok = img.save(fn, None, q)
        except Exception as e:                                  # noqa: BLE001
            self._error("Експортът не успя", str(e))
            return
        self._unbusy()
        st.save()
        if ok:
            self.status.showMessage(f"Запазено: {fn}", 10000)
        else:
            QMessageBox.warning(self, APP_NAME, f"Файлът не можа да се запише:\n{fn}")

    def copy_image(self):
        if self.model is None:
            return
        self._busy("Копиране…")
        QApplication.processEvents()
        img = self._export_image(2000, self._light_into(render.RenderOptions(
            background="white", board=self.st.board_color, shadow=self.st.shadow)))
        QGuiApplication.clipboard().setImage(img.convertToFormat(QImage.Format_RGB32))
        self._unbusy("Изображението е копирано в клипборда.")

    def closeEvent(self, e):
        self.st.geometry = bytes(self.saveGeometry().toBase64()).decode()
        try:
            self.st.save()
        except OSError:
            pass
        super().closeEvent(e)


