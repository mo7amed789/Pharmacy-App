# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise — Windows 11 Fluent Design Theme Module (PySide6 + PySide6-Fluent-Widgets).

Preserves palette/status/preference contracts stored in pharmacy.db while rendering
native Windows 11 Fluent UI (Mica backdrop, NavigationView, SmoothScrollArea,
CardWidget, TableWidget, InfoBar, crisp RTL typography).
"""
import os
import re

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QGridLayout, QLayout, QSizePolicy
from PySide6.QtGui import QColor, QCursor, QFont, QFontDatabase, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QAbstractItemView,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
import qfluentwidgets as qfw
from qfluentwidgets import (
    CardWidget,
    CaptionLabel,
    BodyLabel,
    StrongBodyLabel,
    SmoothScrollArea,
    TableWidget,
    Theme,
    setTheme,
    setThemeColor,
)

FONT_FAMILY = "Segoe UI"
# Arabic-first stack: purpose-built Arabic UI faces when installed, then the
# Windows Arabic-capable system UI fonts.
FONT_FAMILIES_PREFERRED = (
    "Cairo",
    "Tajawal",
    "Noto Sans Arabic",
    "Noto Kufi Arabic",
    "Dubai",
    "Segoe UI Variable Text",
    "Segoe UI Variable",
    "Segoe UI",
    "Tahoma",
    "DejaVu Sans",
)
_resolved_family = None

TYPE_SCALE = {
    "caption": 9,
    "body": 11,
    "subtitle": 13,
    "title": 18,
    "title_large": 22,
    "display": 28,
}

FONT_DELTA = 0
FONT_SCALES = {"normal": 0, "large": 2, "xlarge": 4}
FONT_SCALE_LABELS = {"normal": "عادي", "large": "كبير", "xlarge": "كبير جداً"}

ACCENTS = {
    "teal":   {"label": "سماوي (افتراضي)", "accent": "#0D9488", "hover": "#14B8A6", "header": "#0B3B39", "header2": "#082B2A"},
    "blue":   {"label": "أزرق كهربائي",    "accent": "#3B82F6", "hover": "#60A5FA", "header": "#1E3A8A", "header2": "#172554"},
    "green":  {"label": "زمردي",            "accent": "#10B981", "hover": "#34D399", "header": "#064E3B", "header2": "#022C22"},
    "violet": {"label": "بنفسجي",           "accent": "#8B5CF6", "hover": "#A78BFA", "header": "#4C1D95", "header2": "#2E1065"},
}

LIGHT = {
    "name": "light",
    "bg": "#F3F3F3",
    "card_bg": "#FFFFFF",
    "header_bg": "#0B3B39",
    "header_bg2": "#082B2A",
    "header_fg": "#FFFFFF",
    "text": "#1B1B1B",
    "muted": "#616161",
    "accent": "#0D9488",
    "accent_hover": "#14B8A6",
    "success": "#059669",
    "success_bg": "#D1FAE5",
    "warning": "#D97706",
    "warning_bg": "#FEF3C7",
    "danger": "#DC2626",
    "danger_bg": "#FEE2E2",
    "info": "#2563EB",
    "info_bg": "#DBEAFE",
    "input_bg": "#FFFFFF",
    "border": "#E0E0E0",
    "row_alt": "#F7F7F7",
    "row_bg": "#FFFFFF",
    "selected_bg": "#DCEAF7",
}

DARK = {
    "name": "dark",
    "bg": "#202020",
    "card_bg": "#2C2C2C",
    "header_bg": "#0B3B39",
    "header_bg2": "#082B2A",
    "header_fg": "#FFFFFF",
    "text": "#F2F2F2",
    "muted": "#A9A9A9",
    "accent": "#14B8A6",
    "accent_hover": "#2DD4BF",
    "success": "#34D399",
    "success_bg": "#052E22",
    "warning": "#FBBF24",
    "warning_bg": "#3B2A05",
    "danger": "#F87171",
    "danger_bg": "#3F0D0D",
    "info": "#60A5FA",
    "info_bg": "#0B1E3D",
    "input_bg": "#3A3A3A",
    "border": "#454545",
    "row_alt": "#323232",
    "row_bg": "#2C2C2C",
    "selected_bg": "#3B4C5E",
}

PALETTES = {"light": LIGHT, "dark": DARK}

STATUS_KINDS = ("success", "warning", "danger", "info", "muted")

STATUS_WORDS = {
    # invoices / payments
    "مدفوعة": "success", "مدفوع": "success", "نقدي": "success",
    "آجلة": "warning", "آجل": "warning", "جزئي": "warning",
    "متأخرة": "danger", "مُرجعة": "danger", "مرتجع": "danger",
    "ملغاة": "danger", "ملغية": "danger",
    # sync / background tasks (negative phrases first)
    "غير مفعّلة": "warning", "غير متاحة": "danger",
    "متزامنة": "success", "ناجحة": "success",
    "يعمل": "success", "مفعّلة": "success",
    "فشلت": "danger", "فشل": "danger", "خطأ": "danger",
    "متوقف": "danger",
    "قيد التنفيذ": "info", "معلّقة": "info", "جارٍ": "info",
    # stock / forecast urgency
    "حرجة": "danger", "حرج": "danger", "ناقصة": "warning",
    "عالية": "warning", "قريبة": "warning", "مستقرة": "success",
    # held / disabled lines
    "محذوف مؤقتاً": "muted", "معلَّق": "muted",
}

_LAST_THEME = "dark"
_LAST_ACCENT = "teal"
_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")


def resolve_font_family():
    """Pick the best installed Fluent font family."""
    global FONT_FAMILY, _resolved_family
    if _resolved_family:
        return _resolved_family
    fam = FONT_FAMILY
    try:
        available = set(QFontDatabase.families())
        for cand in FONT_FAMILIES_PREFERRED:
            if cand in available:
                fam = cand
                break
    except Exception:
        fam = FONT_FAMILY
    FONT_FAMILY = fam
    _resolved_family = fam
    return fam


def set_font_scale(delta):
    global FONT_DELTA
    try:
        FONT_DELTA = int(delta)
    except Exception:
        FONT_DELTA = 0


def font_scale_for(name):
    return FONT_SCALES.get(str(name or "normal"), 0)


def qfont(size=10, bold=False, family=None):
    """Return a configured QFont honoring current FONT_DELTA."""
    f = QFont(family or resolve_font_family(), max(8, int(size) + FONT_DELTA))
    if bold:
        f.setBold(True)
    return f


def palette(theme_name=None, accent=None):
    t = theme_name or _LAST_THEME
    a_key = accent or _LAST_ACCENT
    base = dict(PALETTES.get(t, LIGHT))
    a = ACCENTS.get(str(a_key or "teal"), ACCENTS["teal"])
    base["accent"] = a["accent"]
    base["accent_hover"] = a["hover"]
    base["header_bg"] = a["header"]
    base["header_bg2"] = a["header2"]
    return base


def status_colors(kind, theme_name="light", accent="teal"):
    p = palette(theme_name, accent)
    table = {
        "success": (p["success"], p["success_bg"]),
        "warning": (p["warning"], p["warning_bg"]),
        "danger":  (p["danger"],  p["danger_bg"]),
        "info":    (p["info"],    p["info_bg"]),
        "muted":   (p["muted"],   p["row_alt"]),
    }
    return table.get(str(kind or "info"), table["info"])


def status_kind_for(text):
    t = str(text or "")
    for word, kind in STATUS_WORDS.items():
        if word in t:
            return kind
    return "info"


def get_ui_pref(db, key, default=""):
    try:
        return db.get_setting(key, default)
    except Exception:
        return default


def set_ui_pref(db, key, value):
    try:
        db.set_setting(key, str(value))
    except Exception:
        pass


def get_theme_name(db):
    try:
        row = db.conn.execute("SELECT value FROM settings WHERE key='ui_theme'").fetchone()
        if row and row["value"] in PALETTES:
            return row["value"]
    except Exception:
        pass
    return "dark"


def set_theme_name(db, theme_name):
    try:
        db.conn.execute(
            "INSERT INTO settings (key, value) VALUES ('ui_theme', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (theme_name,),
        )
        db.conn.commit()
    except Exception:
        try:
            cur = db.conn.execute("SELECT 1 FROM settings WHERE key='ui_theme'")
            if cur.fetchone():
                db.conn.execute("UPDATE settings SET value=? WHERE key='ui_theme'", (theme_name,))
            else:
                db.conn.execute("INSERT INTO settings VALUES ('ui_theme', ?)", (theme_name,))
            db.conn.commit()
        except Exception:
            pass


def _hex_to_colorref(hex_color):
    h = str(hex_color or "#202020").lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def apply_win11_window_style(win, theme_name=None, accent=None):
    """Apply Windows 11 Mica / dark titlebar / rounded corners safely."""
    t = theme_name or _LAST_THEME
    a = accent or _LAST_ACCENT
    try:
        if hasattr(win, "setMicaEffectEnabled"):
            win.setMicaEffectEnabled(True)
    except Exception:
        pass
    if os.name != "nt":
        return
    try:
        import ctypes
        p = palette(t, a)
        hwnd = int(win.winId())
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        dark_val = ctypes.c_int(1 if t == "dark" else 0)
        for attr in (20, 19):
            try:
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(dark_val), ctypes.sizeof(dark_val))
            except Exception:
                pass
        try:
            corner = ctypes.c_int(2)
            dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
            border = ctypes.c_int(_hex_to_colorref(p["border"]))
            dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border), ctypes.sizeof(border))
        except Exception:
            pass
    except Exception:
        pass


def apply_qt_theme(app, theme_name="dark", accent="teal", font_scale=0):
    """Apply Fluent theme, accent color, RTL direction, and base typography."""
    global _LAST_THEME, _LAST_ACCENT
    _LAST_THEME = theme_name if theme_name in PALETTES else "dark"
    _LAST_ACCENT = accent if accent in ACCENTS else "teal"
    set_font_scale(font_scale)
    fam = resolve_font_family()
    p = palette(_LAST_THEME, _LAST_ACCENT)

    setTheme(Theme.DARK if _LAST_THEME == "dark" else Theme.LIGHT)
    setThemeColor(p["accent"])

    if app is not None:
        try:
            app.setLayoutDirection(Qt.RightToLeft)
            f = QFont(fam, 10 + FONT_DELTA)
            f.setStyleStrategy(QFont.PreferAntialias)
            app.setFont(f)
        except Exception:
            pass
    # Arabic text right-to-left, English text left-to-right, app wide.
    install_auto_direction(app)
    return p


def window_qss(theme_name=None, accent=None):
    """Subtle global polish stylesheet compatible with FluentWindow & QDialog."""
    p = palette(theme_name, accent)
    return f"""
    QDialog {{
        background-color: {p["bg"]};
        color: {p["text"]};
    }}
    QScrollArea, SmoothScrollArea {{
        background-color: transparent;
        border: none;
    }}
    QLabel[muted="true"] {{
        color: {p["muted"]};
    }}
    QFrame[separator="true"] {{
        background-color: {p["border"]};
        max-height: 1px;
        min-height: 1px;
    }}
    /* RTL: input fields follow the text language (line edits switch direction
       per content via ui_theme's bidi filter). */
    QLineEdit, LineEdit, SearchLineEdit, PasswordLineEdit {{
        padding-right: 4px;
    }}
    QTextEdit, TextEdit {{
        padding-right: 4px;
    }}
    /* Fluent-specific RTL button layout */
    QPushButton, PushButton, PrimaryPushButton {{
        text-align: center;
    }}
    """


def make_separator():
    sep = QFrame()
    sep.setFrameShape(QFrame.HLine)
    sep.setProperty("separator", "true")
    sep.setFixedHeight(1)
    return sep


def make_scroll_page(object_name="page"):
    """Return (scroll_area, container_widget, container_layout) for scrollable tabs.

    Pages scroll vertically only: horizontal scrolling is never needed because
    every row reflows inside the viewport width.
    """
    scroll = SmoothScrollArea()
    scroll.setObjectName(object_name)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setStyleSheet("background-color: transparent; border: none;")
    scroll.setLayoutDirection(Qt.RightToLeft)

    inner = QWidget()
    inner.setStyleSheet("background-color: transparent;")
    inner.setLayoutDirection(Qt.RightToLeft)
    inner.setMinimumWidth(0)
    inner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(16, 14, 16, 18)
    layout.setSpacing(12)
    scroll.setWidget(inner)
    return scroll, inner, layout


# ---------------------------------------------------------------------------
# Responsive containers (Qt equivalents of flex-wrap + CSS grid auto-fit)
# ---------------------------------------------------------------------------
class FlowRow(QWidget):
    """A wrapping row: widgets flow onto new lines instead of overflowing.

    Implemented on QGridLayout (no custom C++ layout callbacks) so Qt stays in
    control of geometry; children keep their natural size and the row reports
    the height it actually needs.
    """

    def __init__(self, spacing=8, margins=(0, 0, 0, 0), parent=None):
        super().__init__(parent)
        self._spacing = max(2, int(spacing))
        self._grid = QGridLayout(self)
        if isinstance(margins, (tuple, list)):
            self._grid.setContentsMargins(*margins)
        self._grid.setSpacing(self._spacing)
        self._items = []
        self._signature = None
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.setMinimumWidth(0)

    # -- API ---------------------------------------------------------------
    def add(self, widget):
        self._items.append(widget)
        widget.setParent(self)
        widget.setMinimumWidth(0)
        self._reflow(force=True)
        return widget

    def addWidget(self, widget, *args, **kwargs):
        return self.add(widget)

    def count(self):
        return len(self._items)

    def minimumSizeHint(self):
        """A wrapping row must not claim the width of all its items at once."""
        widest = 0
        for w in self._items:
            if not w.isHidden():
                widest = max(widest, w.minimumSizeHint().width(), w.sizeHint().width())
        if not widest:
            return super().minimumSizeHint()
        try:
            height = self._grid.minimumSize().height()
        except Exception:
            height = super().minimumSizeHint().height()
        return QSize(min(widest, 300), max(24, height))

    # -- reflow ------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _rows_for_width(self, width):
        rows = []
        row = []
        used = 0
        for w in self._items:
            if w.isHidden():
                continue
            need = max(w.sizeHint().width(), w.minimumWidth())
            cost = need + (self._spacing if row else 0)
            if row and used + cost > width:
                rows.append(row)
                row = []
                used = 0
                cost = need
            row.append(w)
            used += cost
        if row:
            rows.append(row)
        return rows

    def _reflow(self, force=False):
        width = self.width()
        if width <= 0 or not self._items:
            return
        rows = self._rows_for_width(width)
        signature = tuple(tuple(id(w) for w in r) for r in rows)
        if signature == self._signature and not force:
            return
        self._signature = signature
        for w in self._items:
            self._grid.removeWidget(w)
        cols = max((len(r) for r in rows), default=1)
        for r, row_widgets in enumerate(rows):
            for c, w in enumerate(row_widgets):
                self._grid.addWidget(w, r, c)
        for c in range(cols):
            self._grid.setColumnStretch(c, 0)
        self.updateGeometry()


class ResponsiveGrid(QWidget):
    """Auto-fit grid: reflows children and stretches them to fill each row."""

    def __init__(self, min_item_width=200, spacing=10, parent=None):
        super().__init__(parent)
        self._min_w = int(min_item_width)
        self._spacing = int(spacing)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)
        self._widgets = []
        self._cols = 0
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.setMinimumWidth(0)

    def addWidget(self, widget, *args, **kwargs):
        self._widgets.append(widget)
        widget.setParent(self)
        widget.setMinimumWidth(0)
        self._relayout(force=True)
        return widget

    def widgets(self):
        return list(self._widgets)

    def minimumSizeHint(self):
        """Never demand the full multi-column width from the page."""
        widest = 0
        for w in self._widgets:
            if not w.isHidden():
                widest = max(widest, w.minimumSizeHint().width())
        if not widest:
            return super().minimumSizeHint()
        try:
            height = self._grid.minimumSize().height()
        except Exception:
            height = super().minimumSizeHint().height()
        return QSize(min(widest, 300), max(60, height))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _columns_for_width(self, width):
        if width <= 0:
            return 1
        return max(1, min(4, (width + self._spacing) // (self._min_w + self._spacing)))

    def _relayout(self, force=False):
        cols = self._columns_for_width(self.width())
        if cols == self._cols and not force:
            return
        self._cols = cols
        for w in self._widgets:
            self._grid.removeWidget(w)
        for i, w in enumerate(self._widgets):
            self._grid.addWidget(w, i // cols, i % cols)
        for c in range(max(cols, self._grid.columnCount())):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
        self.updateGeometry()


def _collect_row_widgets(layout):
    """Return (widgets, convertible). Nested layouts make a row unsafe to convert."""
    out = []
    for j in range(layout.count()):
        item = layout.itemAt(j)
        if item is None:
            continue
        w = item.widget()
        if w is not None:
            out.append(w)
        elif item.layout() is not None:
            return [], False
    return out, True


def _orphan_layout(layout):
    """Not used any more: destroying a layout that still owns items can delete
    the widgets in PySide. Rows are converted by reparenting widgets first."""
    return None


def _flow_row_from_layout(parent_widget, layout, widgets, spacing, margins):
    """Move a row's widgets into a wrapping FlowRow, then empty the old layout."""
    row = FlowRow(
        spacing=spacing,
        margins=(margins.left(), margins.top(), margins.right(), margins.bottom()),
        parent=parent_widget,
    )
    for w in widgets:
        row.add(w)          # Qt detaches the widget from its previous layout
    while layout.count():   # drop leftover stretches/spacers
        layout.takeAt(0)
    return row


def flowify_rows(root, min_items=4):
    """Turn wide horizontal rows anywhere in a page into wrapping rows.

    Rows of label+field (2-3 items) are left untouched, so forms keep their
    compact look; toolbars and action bars wrap instead of overflowing.
    """
    if root is None:
        return 0
    converted = 0
    targets = [root] + list(root.findChildren(QWidget))
    for widget in targets:
        try:
            layout = widget.layout()
        except Exception:
            continue
        if isinstance(layout, QHBoxLayout):
            widgets, ok = _collect_row_widgets(layout)
            if ok and len(widgets) >= min_items:
                margins = layout.contentsMargins()
                spacing = layout.spacing()
                spacing = spacing if spacing and spacing > 0 else 8
                try:
                    row = _flow_row_from_layout(widget, layout, widgets, spacing, margins)
                    layout.setContentsMargins(0, 0, 0, 0)
                    layout.setSpacing(0)
                    layout.addWidget(row)
                    converted += 1
                except Exception:
                    continue
        elif isinstance(layout, QVBoxLayout):
            converted += _convert_child_rows(widget, layout, min_items)
    return converted


def _convert_child_rows(parent_widget, vbox, min_items):
    converted = 0
    i = 0
    while i < vbox.count():
        item = vbox.itemAt(i)
        sub = item.layout() if item is not None else None
        if isinstance(sub, QHBoxLayout):
            widgets, ok = _collect_row_widgets(sub)
            if ok and len(widgets) >= min_items:
                margins = sub.contentsMargins()
                spacing = sub.spacing()
                spacing = spacing if spacing and spacing > 0 else 8
                try:
                    row = _flow_row_from_layout(parent_widget, sub, widgets, spacing, margins)
                    vbox.takeAt(i)
                    vbox.insertWidget(i, row)
                    converted += 1
                except Exception:
                    i += 1
                    continue
        i += 1
    return converted


def flowify_page_rows(inner, min_items=3):
    """Turn page-level horizontal rows (toolbars, filter bars) into wrapping rows.

    Only rows that are direct children of the page column are converted, so
    compact rows inside cards keep their exact design.
    """
    if inner is None:
        return 0
    layout = inner.layout()
    if not isinstance(layout, QVBoxLayout):
        return 0
    return _convert_child_rows(inner, layout, min_items)


def responsive_pass(page):
    """Apply wrapping rows + Arabic/Latin direction to a freshly built page."""
    if page is None:
        return
    try:
        scroll = page.findChild(SmoothScrollArea)
        inner = scroll.widget() if scroll is not None else page
        flowify_page_rows(inner)
        flowify_rows(inner, min_items=4)
        apply_auto_direction(page)
    except Exception:
        pass



class StatCard(CardWidget):
    """Windows 11 Fluent KPI Card with colored accent bar and optional click action."""
    clicked = Signal()

    def __init__(self, title, value="—", sub="", accent_color=None, click_cb=None, parent=None):
        super().__init__(parent)
        self._accent_color = accent_color or palette()["accent"]
        self._click_cb = click_cb
        if click_cb is not None:
            self.setCursor(Qt.PointingHandCursor)
            self.clicked.connect(click_cb)

        # Cards shrink with the window instead of forcing a wide page.
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._bar = QFrame()
        self._bar.setFixedWidth(5)
        self._bar.setStyleSheet(
            f"background-color: {self._accent_color}; border-top-left-radius: 6px; border-bottom-left-radius: 6px;"
            f" border-top-right-radius: 6px; border-bottom-right-radius: 6px;"
        )
        outer.addWidget(self._bar)

        body = QVBoxLayout()
        body.setContentsMargins(14, 12, 14, 12)
        body.setSpacing(4)

        self.lbl_title = CaptionLabel(title, self)
        self.lbl_title.setFont(qfont(10, bold=True))
        self.lbl_title.setWordWrap(True)
        self.lbl_value = QLabel(str(value), self)
        self.lbl_value.setFont(qfont(20, bold=True))
        self.lbl_sub = CaptionLabel(str(sub), self)
        self.lbl_sub.setWordWrap(True)

        body.addWidget(self.lbl_title)
        body.addWidget(self.lbl_value)
        body.addWidget(self.lbl_sub)
        outer.addLayout(body, 1)
        self.recolor()

    def set_values(self, value=None, sub=None):
        if value is not None:
            self.lbl_value.setText(str(value))
        if sub is not None:
            self.lbl_sub.setText(str(sub))
        self._align_text()

    def _align_text(self):
        """Arabic values (and currency/numbers) sit on the right, Latin on the left."""
        for lbl in (self.lbl_title, self.lbl_value, self.lbl_sub):
            try:
                if direction_for_text(lbl.text()) is None:
                    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    lbl.setLayoutDirection(Qt.RightToLeft)
                else:
                    apply_text_direction(lbl)
            except Exception:
                pass

    def recolor(self, theme_name=None, accent=None):
        p = palette(theme_name, accent)
        self.lbl_title.setStyleSheet(f"color: {p['muted']}; background: transparent;")
        self.lbl_value.setStyleSheet(f"color: {p['text']}; background: transparent;")
        self.lbl_sub.setStyleSheet(f"color: {p['muted']}; background: transparent;")
        self._align_text()

    def mousePressEvent(self, event):
        if self._click_cb is not None and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def configure_table(table: TableWidget, headers, widths=None, stretch_cols=None, min_height=220):
    """Configure a Fluent TableWidget consistently across the app.

    Column widths are treated as *preferred* widths: they shrink
    proportionally when the table is narrower than their sum, so a table never
    forces horizontal scrolling on the page. Long text is elided instead.
    """
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.setBorderVisible(True)
    table.setBorderRadius(8)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.ElideRight)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(34)
    table.setMinimumHeight(min_height)
    table.setAlternatingRowColors(True)

    hh = table.horizontalHeader()
    # AlignAbsolute keeps Arabic headers on the right even inside RTL layouts
    # (Qt mirrors relative AlignLeft/AlignRight otherwise).
    hh.setDefaultAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)
    hh.setStretchLastSection(False)
    hh.setSectionResizeMode(QHeaderView.Interactive)

    if widths:
        table._fit_widths = tuple(int(w or 0) for w in widths)
        table._fit_stretch = tuple(stretch_cols or ())
        for idx, w in enumerate(widths):
            if w is not None and idx < len(headers):
                table.setColumnWidth(idx, int(w))
        if not getattr(table, "_fit_filter", None):
            flt = _TableColumnFit(table)
            table._fit_filter = flt
            table.installEventFilter(flt)
            try:
                table.viewport().installEventFilter(flt)
            except Exception:
                pass
        QTimer.singleShot(0, lambda t=table: _fit_table_columns(t))


def _fit_table_columns(table):
    """Scale preferred column widths to the space the table actually has."""
    if getattr(table, "_fit_busy", False):
        return
    widths = getattr(table, "_fit_widths", None)
    if not widths or table.columnCount() < 1:
        return
    try:
        avail = table.viewport().width()
    except Exception:
        avail = table.width()
    if avail <= 40:
        return

    n = table.columnCount()
    ws = [int(widths[i]) if i < len(widths) and widths[i] else 0 for i in range(n)]
    if not any(ws):
        return
    total = sum(w for w in ws if w > 0)
    target = avail - 2
    stretch = tuple(c for c in getattr(table, "_fit_stretch", ()) if 0 <= c < n)

    if total <= target:
        extra = target - total
        if stretch:
            share = extra // len(stretch)
            for c in stretch:
                ws[c] += share
        else:
            ws[-1] += extra
    else:
        factor = float(target) / float(total)
        for i, w in enumerate(ws):
            if w > 0:
                ws[i] = max(52, int(w * factor))
        guard = 0
        while sum(ws) > target and guard < 200:
            guard += 1
            widest = ws.index(max(ws))
            if ws[widest] <= 52:
                break
            ws[widest] -= 4

    table._fit_busy = True
    try:
        for c, w in enumerate(ws):
            if w > 0 and table.columnWidth(c) != w:
                table.setColumnWidth(c, w)
    finally:
        table._fit_busy = False


class _TableColumnFit(QObject):
    """Re-fit table columns whenever the table (or its viewport) resizes."""

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            try:
                _fit_table_columns(obj if hasattr(obj, "columnCount") else obj.parent())
            except Exception:
                pass
        return False


def set_table_rows(table: TableWidget, rows_values, row_styles=None):
    """Fast batch populate TableWidget without intermediate repaints."""
    table.setUpdatesEnabled(False)
    try:
        table.setRowCount(len(rows_values))
        for r_idx, vals in enumerate(rows_values):
            fg_bg = row_styles[r_idx] if row_styles and r_idx < len(row_styles) else None
            for c_idx, val in enumerate(vals):
                cell_text = str(val if val is not None else "")
                item = QTableWidgetItem(cell_text)
                item.setTextAlignment(cell_alignment(cell_text))
                if fg_bg:
                    fg, bg = fg_bg
                    if fg:
                        item.setForeground(QBrush(QColor(fg)))
                    if bg:
                        item.setBackground(QBrush(QColor(bg)))
                table.setItem(r_idx, c_idx, item)
    finally:
        table.setUpdatesEnabled(True)


def selected_row_index(table: TableWidget):
    rows = table.selectionModel().selectedRows() if table.selectionModel() else []
    if not rows:
        row = table.currentRow()
        return row if row >= 0 else None
    return rows[0].row()


class DrugSearchTableWidget(TableWidget):
    """Reusable Excel-style sortable Fluent drug table shared across screens."""

    COLS = ("name", "ar", "strength", "form", "box", "strip", "pill", "stock")
    HEADS = ("الدواء", "عربي", "التركيز", "الشكل", "سعر العلبة", "سعر الشريط", "سعر الحبة", "المخزون (علبة)")
    WIDTHS = (165, 115, 85, 85, 90, 90, 90, 95)

    drugActivated = Signal(dict)

    def __init__(self, money_fn, allowed_units_fn, unit_price_fn, min_height=220, parent=None):
        super().__init__(parent)
        self._money = money_fn
        self._allowed = allowed_units_fn
        self._unit_price = unit_price_fn
        self._results = []
        self._sort_col = None
        self._sort_rev = False

        configure_table(self, self.HEADS, self.WIDTHS, stretch_cols=(0,), min_height=min_height)
        self.horizontalHeader().sectionClicked.connect(self._on_header_click)
        self.cellDoubleClicked.connect(self._on_double_click)

    def fill(self, results, empty_message=None):
        self._results = list(results or [])
        self._sort_col = None
        self._sort_rev = False
        self._render(empty_message=empty_message)

    def _row_values(self, d):
        allowed = set(self._allowed(d))
        return (
            d["trade_en"],
            d.get("trade_ar", ""),
            d.get("strength", ""),
            d.get("form", ""),
            self._money(self._unit_price(d, "box")),
            self._money(self._unit_price(d, "strip")) if "strip" in allowed else "—",
            self._money(self._unit_price(d, "pill")) if "pill" in allowed else "—",
            "%.1f" % d.get("stock_boxes", 0),
        )

    def _render(self, empty_message=None):
        if not self._results and empty_message:
            set_table_rows(self, [(empty_message, "", "", "", "", "", "", "")])
            return
        p = palette()
        rows = [self._row_values(d) for d in self._results]
        styles = [
            (p["danger"], p["danger_bg"]) if d.get("stock_boxes", 0) <= 0 else None
            for d in self._results
        ]
        set_table_rows(self, rows, styles)

    def selected_drug(self):
        idx = selected_row_index(self)
        if idx is None or idx < 0 or idx >= len(self._results):
            return None
        return self._results[idx]

    def _on_header_click(self, col_idx):
        if not self._results or col_idx >= len(self.COLS):
            return
        col = self.COLS[col_idx]
        rev = (not self._sort_rev) if self._sort_col == col else False
        if col == "name":
            key = lambda d: str(d["trade_en"]).lower()
        elif col == "ar":
            key = lambda d: str(d.get("trade_ar", ""))
        elif col == "strength":
            key = lambda d: str(d.get("strength", ""))
        elif col == "form":
            key = lambda d: str(d.get("form", ""))
        elif col in ("box", "strip", "pill"):
            key = lambda d, c=col: self._unit_price(d, c)
        elif col == "stock":
            key = lambda d: d.get("stock_boxes", 0)
        else:
            key = lambda d: str(d["trade_en"]).lower()
        self._results.sort(key=key, reverse=rev)
        self._sort_col = col
        self._sort_rev = rev
        self._render()

    def _on_double_click(self, row, _col):
        if 0 <= row < len(self._results):
            self.drugActivated.emit(self._results[row])


# ---------------------------------------------------------------------------
# Bidirectional text — Arabic flows right to left, English flows left to right
# ---------------------------------------------------------------------------
_RTL_RE = re.compile(
    "[\u0590-\u05FF\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB1D-\uFDFD\uFE70-\uFEFC]"
)
_LTR_RE = re.compile("[A-Za-z\u00C0-\u024F]")


def has_rtl_text(text):
    """True when the string contains Arabic/Hebrew characters."""
    return bool(_RTL_RE.search(str(text if text is not None else "")))


def has_ltr_text(text):
    """True when the string contains Latin letters."""
    return bool(_LTR_RE.search(str(text if text is not None else "")))


def direction_for_text(text):
    """RTL for Arabic, LTR for Latin-only text, None when undecided."""
    s = str(text if text is not None else "")
    if not s.strip():
        return None
    if has_rtl_text(s):
        return Qt.RightToLeft
    if has_ltr_text(s):
        return Qt.LeftToRight
    return None


def alignment_for_text(text, vertical_center=True):
    """Absolute alignment: Arabic starts on the right, English on the left."""
    flags = Qt.AlignRight if has_rtl_text(text) else Qt.AlignLeft
    if vertical_center:
        flags |= Qt.AlignVCenter
    return flags


def cell_alignment(text):
    """Table-cell alignment that survives RTL mirroring."""
    return alignment_for_text(text) | Qt.AlignAbsolute


def _text_of(widget):
    if isinstance(widget, QLabel):
        return widget.text()
    if isinstance(widget, QLineEdit):
        return widget.text() or widget.placeholderText()
    if isinstance(widget, (QPlainTextEdit, QTextEdit)):
        return widget.toPlainText() or widget.placeholderText()
    return ""


def apply_text_direction(widget, text=None):
    """Make one text widget flow Arabic->right, English->left."""
    if not isinstance(widget, (QLabel, QLineEdit, QPlainTextEdit, QTextEdit)):
        return None
    s = _text_of(widget) if text is None else str(text)
    direction = direction_for_text(s)
    if direction is None:
        return None
    if widget.layoutDirection() != direction:
        widget.setLayoutDirection(direction)
    # Only labels still on the default left alignment are flipped, so labels
    # that were deliberately centred keep their design.
    if isinstance(widget, QLabel):
        cur = widget.alignment()
        if not (cur & (Qt.AlignRight | Qt.AlignHCenter | Qt.AlignJustify)):
            widget.setAlignment(alignment_for_text(s))
    return direction


def apply_auto_direction(root):
    """Apply Arabic/English auto-direction to a whole widget tree."""
    if root is None:
        return
    try:
        apply_text_direction(root)
        for child in root.findChildren(QWidget):
            apply_text_direction(child)
    except Exception:
        pass


class _BidiFilter(QObject):
    """Keeps late-built widgets correctly directed (labels, inputs, pages)."""

    _TRIGGERS = (QEvent.Show, QEvent.Polish, QEvent.ChildPolished)

    def __init__(self):
        super().__init__()
        self._watched = set()

    def eventFilter(self, obj, event):
        if event.type() in self._TRIGGERS:
            target = obj
            if event.type() == QEvent.ChildPolished:
                target = event.child()
            try:
                apply_text_direction(target)
                if isinstance(target, QLineEdit):
                    self._watch(target)
            except Exception:
                pass
        return False

    def _watch(self, line_edit):
        key = id(line_edit)
        if key in self._watched:
            return
        self._watched.add(key)
        try:
            line_edit.textChanged.connect(
                lambda _t, w=line_edit: apply_text_direction(w)
            )
        except Exception:
            pass


_BIDI_FILTER = None


def install_auto_direction(app=None):
    """Install the app-wide Arabic-RTL / English-LTR direction filter (once)."""
    global _BIDI_FILTER
    if _BIDI_FILTER is not None:
        return _BIDI_FILTER
    app = app if app is not None else QApplication.instance()
    if app is None:
        return None
    try:
        _BIDI_FILTER = _BidiFilter()
        app.installEventFilter(_BIDI_FILTER)
    except Exception:
        _BIDI_FILTER = None
    return _BIDI_FILTER


# ---------------------------------------------------------------------------
# Screen fitting — the window adapts to whatever display it runs on
# ---------------------------------------------------------------------------
def _screen_available(win=None):
    """Available geometry of the screen the window is (or would be) on."""
    screen = None
    if win is not None:
        try:
            screen = win.screen()
        except Exception:
            screen = None
    if screen is None:
        try:
            screen = QApplication.screenAt(QCursor.pos())
        except Exception:
            screen = None
    if screen is None:
        screen = QApplication.primaryScreen()
    if screen is None:
        return None
    try:
        return screen.availableGeometry()
    except Exception:
        return None


def fitted_sizes(win=None):
    """(min_w, min_h, default_w, default_h) that always fit the screen."""
    avail = _screen_available(win)
    sw = avail.width() if avail else 1280
    sh = avail.height() if avail else 800
    min_w = max(480, min(1024, sw - 60))
    min_h = max(360, min(660, sh - 90))
    def_w = max(min_w, min(int(sw * 0.92), 1440, sw - 20))
    def_h = max(min_h, min(int(sh * 0.90), 920, sh - 40))
    return min_w, min_h, def_w, def_h


def nav_expand_width(win=None):
    """Navigation panel width that scales with the screen it runs on."""
    avail = _screen_available(win)
    base = avail.width() if avail else (win.width() if win is not None else 1280)
    return max(160, min(228, int(base * 0.15)))


def setup_main_window_geometry(win, db):
    """Restore/save the main window size, always fitted to the current screen."""
    avail = _screen_available(win)
    sw = avail.width() if avail else 1280
    sh = avail.height() if avail else 800
    min_w, min_h, def_w, def_h = fitted_sizes(win)

    win.setMinimumSize(min_w, min_h)

    saved = get_ui_pref(db, "ui_geometry", "")
    maximized = get_ui_pref(db, "ui_maximized", "") == "1"

    placed = False
    m = _GEOMETRY_RE.match(str(saved or ""))
    if m:
        w, h, x, y = (int(v) for v in m.groups())
        # Accept a saved geometry only if it still fits this screen, then clamp
        # it so a window saved on a big monitor never overflows a laptop panel.
        if 480 <= w <= sw and 360 <= h <= sh:
            w = max(min_w, min(w, sw))
            h = max(min_h, min(h, sh))
            if avail:
                x = min(max(x, avail.x()), avail.x() + max(0, sw - min_w))
                y = min(max(y, avail.y()), avail.y() + max(0, sh - min_h))
                win.resize(w, h)
                win.move(x, y)
                placed = True
    if not placed:
        win.resize(def_w, def_h)
        if avail:
            win.move(
                avail.x() + max(0, (sw - def_w) // 2),
                avail.y() + max(0, (sh - def_h) // 2),
            )
    if maximized or not saved:
        win.showMaximized()


def install_screen_fit(win):
    """Keep the window inside the display when it is dragged to another screen."""
    if win is None:
        return

    def _refit(*_args):
        try:
            avail = _screen_available(win)
            if avail is None:
                return
            min_w, min_h, def_w, def_h = fitted_sizes(win)
            win.setMinimumSize(min_w, min_h)
            if win.isMaximized() or win.isFullScreen():
                return
            g = win.geometry()
            w = max(min_w, min(g.width(), avail.width()))
            h = max(min_h, min(g.height(), avail.height()))
            x = min(max(g.x(), avail.x()), avail.x() + max(0, avail.width() - min_w))
            y = min(max(g.y(), avail.y()), avail.y() + max(0, avail.height() - min_h))
            if (x, y, w, h) != (g.x(), g.y(), g.width(), g.height()):
                win.setGeometry(x, y, w, h)
        except Exception:
            pass

    handle = None
    try:
        handle = win.windowHandle()
    except Exception:
        handle = None
    if handle is not None:
        handle.screenChanged.connect(_refit)
        return

    state = {"tries": 0}

    def _attach():
        try:
            handle = win.windowHandle()
        except Exception:
            handle = None
        if handle is not None:
            handle.screenChanged.connect(_refit)
        elif state["tries"] < 40:
            state["tries"] += 1
            QTimer.singleShot(100, _attach)

    QTimer.singleShot(100, _attach)



def save_main_window_geometry(win, db):
    try:
        is_max = win.isMaximized()
        set_ui_pref(db, "ui_maximized", "1" if is_max else "0")
        if not is_max:
            g = win.geometry()
            set_ui_pref(db, "ui_geometry", "%dx%d+%d+%d" % (g.width(), g.height(), g.x(), g.y()))
    except Exception:
        pass


def fit_dialog_widget(dlg, w, h):
    """Size and center a Qt dialog cleanly within the available screen."""
    avail = _screen_available(dlg)
    sw = avail.width() if avail else 1280
    sh = avail.height() if avail else 800
    w = min(int(w), max(sw - 60, 360))
    h = min(int(h), max(sh - 90, 280))
    dlg.resize(w, h)
    if avail:
        dlg.move(avail.x() + max(0, (sw - w) // 2), avail.y() + max(0, (sh - h) // 2))
    apply_win11_window_style(dlg)
