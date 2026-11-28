# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise — Fluent Design Dialogs (PySide6 + PySide6-Fluent-Widgets).

Provides a drop-in replacement for showinfo / showwarning / showerror / askyesno
plus RTL-aware Fluent helpers: askstring, askinteger, askfloat, TextViewerDialog,
get_open_filename, and get_save_filename.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    LineEdit,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TextEdit,
)

import ui_theme

_THEME_NAME = "dark"
_ACCENT = "teal"


def set_theme(theme_name, accent=None):
    global _THEME_NAME, _ACCENT
    if theme_name in ui_theme.PALETTES:
        _THEME_NAME = theme_name
    if accent in ui_theme.ACCENTS:
        _ACCENT = accent


_KIND_META = {
    "info":     ("ℹ️", "info"),
    "success":  ("✅", "success"),
    "warning":  ("⚠️", "warning"),
    "error":    ("⛔", "danger"),
    "question": ("❓", "warning"),
}


def _resolve_parent(parent):
    if parent is not None and hasattr(parent, "isVisible"):
        return parent
    win = QApplication.activeWindow()
    return win


def _run_fluent_message(title, message, kind, parent=None, yes_no=False):
    msg = str(message or "")
    p = ui_theme.palette(_THEME_NAME, _ACCENT)
    icon, col_kind = _KIND_META.get(kind, _KIND_META["info"])
    fg, _bg = ui_theme.status_colors(col_kind, _THEME_NAME, _ACCENT)
    host = _resolve_parent(parent)

    # Use Fluent MessageBox overlay when we have a visible host window and short message
    if host is not None and host.isVisible() and msg.count("\n") <= 12 and len(msg) <= 700:
        try:
            box = MessageBox(f"{icon}  {title}", msg, host)
            box.yesButton.setText("نعم" if yes_no else "حسناً")
            if yes_no:
                box.cancelButton.setText("لا")
            else:
                box.cancelButton.hide()
                box.buttonLayout.insertStretch(0, 1)
            return bool(box.exec())
        except Exception:
            pass

    # Standalone / long-text / pre-window themed dialog
    dlg = QDialog(host)
    dlg.setWindowTitle(str(title))
    dlg.setLayoutDirection(Qt.RightToLeft)
    dlg.setStyleSheet(ui_theme.window_qss(_THEME_NAME, _ACCENT))
    dlg.setModal(True)

    root = QVBoxLayout(dlg)
    root.setContentsMargins(0, 0, 0, 14)
    root.setSpacing(10)

    strip = QFrame()
    strip.setFixedHeight(5)
    strip.setStyleSheet(f"background-color: {fg};")
    root.addWidget(strip)

    head = QHBoxLayout()
    head.setContentsMargins(18, 6, 18, 0)
    head.setSpacing(10)
    lbl_ico = QLabel(icon)
    lbl_ico.setFont(ui_theme.qfont(18))
    lbl_ico.setStyleSheet(f"color: {fg}; background: transparent;")
    lbl_t = SubtitleLabel(str(title))
    lbl_t.setWordWrap(True)
    head.addWidget(lbl_ico)
    head.addWidget(lbl_t, 1)
    root.addLayout(head)

    is_long = msg.count("\n") > 10 or len(msg) > 650
    if is_long:
        te = TextEdit()
        te.setReadOnly(True)
        te.setPlainText(msg)
        te.setMinimumSize(460, 220)
        wrap = QVBoxLayout()
        wrap.setContentsMargins(18, 4, 18, 4)
        wrap.addWidget(te)
        root.addLayout(wrap, 1)
    else:
        lbl_m = BodyLabel(msg)
        lbl_m.setWordWrap(True)
        lbl_m.setMinimumWidth(360)
        lbl_m.setContentsMargins(18, 4, 18, 4)
        root.addWidget(lbl_m)

    btns = QHBoxLayout()
    btns.setContentsMargins(18, 4, 18, 0)
    btns.addStretch(1)
    result = {"val": False}

    def accept_choice():
        result["val"] = True
        dlg.accept()

    def reject_choice():
        result["val"] = False
        dlg.reject()

    btn_ok = PrimaryPushButton("نعم" if yes_no else "حسناً")
    btn_ok.setDefault(True)
    btn_ok.clicked.connect(accept_choice)
    btns.addWidget(btn_ok)

    if yes_no:
        btn_no = PushButton("لا")
        btn_no.clicked.connect(reject_choice)
        btns.addWidget(btn_no)

    root.addLayout(btns)
    ui_theme.fit_dialog_widget(dlg, 560 if is_long else 440, 380 if is_long else 210)
    dlg.adjustSize()
    ui_theme.apply_win11_window_style(dlg, _THEME_NAME, _ACCENT)
    dlg.exec()
    return result["val"]


def showinfo(title, message, parent=None, **_kw):
    _run_fluent_message(title, message, "info", parent=parent, yes_no=False)
    return "ok"


def showwarning(title, message, parent=None, **_kw):
    _run_fluent_message(title, message, "warning", parent=parent, yes_no=False)
    return "ok"


def showerror(title, message, parent=None, **_kw):
    _run_fluent_message(title, message, "error", parent=parent, yes_no=False)
    return "ok"


def askyesno(title, message, parent=None, **_kw):
    return bool(_run_fluent_message(title, message, "question", parent=parent, yes_no=True))


def _ask_input(title, prompt, initialvalue="", mode="str", parent=None):
    host = _resolve_parent(parent)
    dlg = QDialog(host)
    dlg.setWindowTitle(str(title))
    dlg.setLayoutDirection(Qt.RightToLeft)
    dlg.setStyleSheet(ui_theme.window_qss(_THEME_NAME, _ACCENT))
    dlg.setModal(True)

    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(10)

    lbl = BodyLabel(str(prompt))
    lbl.setWordWrap(True)
    lay.addWidget(lbl)

    edt = LineEdit()
    edt.setClearButtonEnabled(True)
    edt.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if initialvalue is not None and str(initialvalue) != "":
        edt.setText(str(initialvalue))
        edt.selectAll()
    lay.addWidget(edt)

    err_lbl = CaptionLabel = QLabel("")
    err_lbl.setStyleSheet(f"color: {ui_theme.palette(_THEME_NAME, _ACCENT)['danger']};")
    err_lbl.hide()
    lay.addWidget(err_lbl)

    btns = QHBoxLayout()
    btns.addStretch(1)
    out = {"value": None}

    def on_ok():
        raw = edt.text()
        if mode == "str":
            out["value"] = raw
            dlg.accept()
            return
        txt = raw.strip()
        if not txt:
            err_lbl.setText("أدخل رقماً صحيحاً")
            err_lbl.show()
            return
        try:
            out["value"] = int(txt) if mode == "int" else float(txt)
            dlg.accept()
        except ValueError:
            err_lbl.setText("القيمة المدخلة غير صالحة")
            err_lbl.show()

    btn_ok = PrimaryPushButton("موافق")
    btn_cancel = PushButton("إلغاء")
    btn_ok.setDefault(True)
    btn_ok.clicked.connect(on_ok)
    btn_cancel.clicked.connect(dlg.reject)
    edt.returnPressed.connect(on_ok)
    btns.addWidget(btn_ok)
    btns.addWidget(btn_cancel)
    lay.addLayout(btns)

    ui_theme.fit_dialog_widget(dlg, 430, 190)
    dlg.adjustSize()
    edt.setFocus()
    dlg.exec()
    return out["value"]


def askstring(title, prompt, initialvalue="", parent=None):
    return _ask_input(title, prompt, initialvalue=initialvalue, mode="str", parent=parent)


def askinteger(title, prompt, initialvalue="", parent=None):
    return _ask_input(title, prompt, initialvalue=initialvalue, mode="int", parent=parent)


def askfloat(title, prompt, initialvalue="", parent=None):
    return _ask_input(title, prompt, initialvalue=initialvalue, mode="float", parent=parent)


def get_open_filename(parent=None, title="اختر ملفاً", filetypes=None):
    flt = _convert_filetypes(filetypes)
    path, _ = QFileDialog.getOpenFileName(_resolve_parent(parent), title, "", flt)
    return path or ""


def get_save_filename(parent=None, title="حفظ الملف", initialfile="", filetypes=None):
    flt = _convert_filetypes(filetypes)
    path, _ = QFileDialog.getSaveFileName(_resolve_parent(parent), title, initialfile or "", flt)
    return path or ""


def _convert_filetypes(filetypes):
    if not filetypes:
        return "كل الملفات (*.*)"
    parts = []
    for label, pattern in filetypes:
        pat = " ".join(pattern.split())
        parts.append(f"{label} ({pat})")
    return ";;".join(parts)


class TextViewerDialog(QDialog):
    """Clean Fluent read-only text preview dialog with optional action buttons."""

    def __init__(self, parent, title, text, width=680, height=480, monospace=False, extra_buttons=None):
        super().__init__(_resolve_parent(parent))
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(ui_theme.window_qss(_THEME_NAME, _ACCENT))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        self.editor = TextEdit()
        self.editor.setReadOnly(True)
        if monospace:
            self.editor.setFont(ui_theme.qfont(10, family="Consolas"))
        self.editor.setPlainText(text)
        lay.addWidget(self.editor, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        if extra_buttons:
            for label, cb, is_primary in extra_buttons:
                btn = PrimaryPushButton(label) if is_primary else PushButton(label)
                btn.clicked.connect(lambda _c=False, fn=cb: fn(self))
                btns.addWidget(btn)
        btn_close = PushButton("إغلاق")
        btn_close.clicked.connect(self.close)
        btns.addWidget(btn_close)
        lay.addLayout(btns)

        ui_theme.fit_dialog_widget(self, width, height)
