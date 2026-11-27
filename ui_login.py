# -*- coding: utf-8 -*-
"""
Fluent Design Login Window & Forced Default-Password Change Dialog (PySide6).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TitleLabel,
)

import ui_dialogs as messagebox
import ui_theme


def force_password_change_dialog(parent, db, user, old_password=None):
    """First login with a factory default password must change it before entering."""
    changed = {"ok": False}

    dlg = QDialog(parent)
    dlg.setWindowTitle("غيّر كلمة المرور الافتراضية")
    dlg.setLayoutDirection(Qt.RightToLeft)
    dlg.setStyleSheet(ui_theme.window_qss())
    dlg.setModal(True)

    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(24, 18, 24, 18)
    lay.setSpacing(10)

    title = SubtitleLabel("⚠️ كلمة مرور افتراضية")
    title.setAlignment(Qt.AlignCenter)
    lay.addWidget(title)

    info = BodyLabel(
        "أنت تدخل بكلمة المرور الافتراضية للبرنامج.\n"
        "لحماية بيانات الصيدلية، يجب تغييرها الآن قبل الاستخدام."
    )
    info.setWordWrap(True)
    info.setAlignment(Qt.AlignCenter)
    lay.addWidget(info)

    lay.addWidget(CaptionLabel("كلمة المرور الجديدة (8 أحرف على الأقل)"))
    e_new = PasswordLineEdit()
    lay.addWidget(e_new)

    lay.addWidget(CaptionLabel("تأكيد كلمة المرور الجديدة"))
    e_conf = PasswordLineEdit()
    lay.addWidget(e_conf)

    def save():
        from database import _verify_password
        if old_password is None:
            messagebox.showerror("خطأ", "تعذّر التحقق من كلمة المرور — سجّل الدخول مرة أخرى", parent=dlg)
            return
        row = db.conn.execute(
            "SELECT password_hash FROM users WHERE username=?",
            (user["username"],),
        ).fetchone()
        if not row or not _verify_password(old_password, row["password_hash"]):
            messagebox.showerror("خطأ", "تعذّر التحقق من كلمة المرور — سجّل الدخول مرة أخرى", parent=dlg)
            return
        new = e_new.text()
        if len(new) < 8:
            messagebox.showerror("خطأ", "كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل", parent=dlg)
            return
        if new != e_conf.text():
            messagebox.showerror("خطأ", "تأكيد كلمة المرور لا يطابق كلمة المرور الجديدة", parent=dlg)
            return
        if new in ("admin123", "cashier123"):
            messagebox.showerror(
                "خطأ",
                "كلمة المرور الجديدة لا يمكن أن تكون كلمة المرور الافتراضية — اختر كلمة مرور مختلفة",
                parent=dlg,
            )
            return
        db.change_password(user["username"], new)
        db.audit(user["username"], "change_password", "forced default change")
        changed["ok"] = True
        messagebox.showinfo("تم", "تم تغيير كلمة المرور — احتفظ بها في مكان آمن", parent=dlg)
        dlg.accept()

    btn_save = PrimaryPushButton("💾 تغيير كلمة المرور")
    btn_save.clicked.connect(save)
    e_conf.returnPressed.connect(save)
    lay.addWidget(btn_save)

    btn_cancel = PushButton("إلغاء — الرجوع لتسجيل الدخول")
    btn_cancel.clicked.connect(dlg.reject)
    lay.addWidget(btn_cancel)

    hint = CaptionLabel("إغلاق هذه النافذة يعيدك لتسجيل الدخول — لن تدخل البرنامج\nبكلمة المرور الافتراضية.")
    hint.setAlignment(Qt.AlignCenter)
    hint.setWordWrap(True)
    lay.addWidget(hint)

    ui_theme.fit_dialog_widget(dlg, 460, 360)
    e_new.setFocus()
    dlg.exec()
    return changed["ok"]


class LoginWindow(QDialog):
    def __init__(self, db, notice="", log_fn=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.user = None
        self.notice = notice
        self._log = log_fn or (lambda _m: None)

        self._theme = ui_theme.get_theme_name(db)
        self._accent = db.get_setting("ui_accent", "teal") or "teal"
        if self._accent not in ui_theme.ACCENTS:
            self._accent = "teal"
        self._pal = ui_theme.apply_qt_theme(None, self._theme, self._accent, 0)
        ui_dialogs_set(self._theme, self._accent)

        self.setWindowTitle("تسجيل الدخول — Pharmacy Enterprise")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(ui_theme.window_qss(self._theme, self._accent))
        self.setFixedSize(440, 470)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 18)
        root.setSpacing(0)

        strip = QFrame()
        strip.setFixedHeight(5)
        strip.setStyleSheet(f"background-color: {self._pal['accent']};")
        root.addWidget(strip)

        body = QVBoxLayout()
        body.setContentsMargins(28, 18, 28, 6)
        body.setSpacing(8)
        root.addLayout(body, 1)

        brand = TitleLabel("💊 Pharmacy Enterprise")
        brand.setAlignment(Qt.AlignCenter)
        body.addWidget(brand)

        try:
            _pn = db.conn.execute("SELECT value FROM settings WHERE key='pharmacy_name'").fetchone()
            _pname = _pn["value"] if _pn and _pn["value"] else "صيدلية المؤسسة"
        except Exception:
            _pname = "صيدلية المؤسسة"

        lbl_ph = SubtitleLabel(_pname)
        lbl_ph.setAlignment(Qt.AlignCenter)
        lbl_ph.setStyleSheet(f"color: {self._pal['accent']};")
        body.addWidget(lbl_ph)

        lbl_ver = BodyLabel("نظام إدارة الصيدلية — v6.30")
        lbl_ver.setAlignment(Qt.AlignCenter)
        body.addWidget(lbl_ver)

        lbl_sub = CaptionLabel("لوحة تحكم • كاشير سريع • تنبؤ ذكي")
        lbl_sub.setAlignment(Qt.AlignCenter)
        body.addWidget(lbl_sub)

        body.addSpacing(10)
        body.addWidget(CaptionLabel("اسم المستخدم"))
        self.e_user = LineEdit()
        self.e_user.setPlaceholderText("أدخل اسم المستخدم")
        self.e_user.setClearButtonEnabled(True)
        body.addWidget(self.e_user)

        body.addSpacing(4)
        body.addWidget(CaptionLabel("كلمة المرور"))
        self.e_pass = PasswordLineEdit()
        self.e_pass.setPlaceholderText("أدخل كلمة المرور")
        self.e_pass.returnPressed.connect(self.try_login)
        body.addWidget(self.e_pass)

        body.addSpacing(12)
        self.btn_login = PrimaryPushButton("دخول")
        self.btn_login.setFixedHeight(38)
        self.btn_login.clicked.connect(self.try_login)
        body.addWidget(self.btn_login)

        lbl_sec = CaptionLabel("أول دخول بكلمة مرور افتراضية يطلب تغييرها فوراً — لا تشارك كلمة مرورك مع أحد")
        lbl_sec.setWordWrap(True)
        lbl_sec.setAlignment(Qt.AlignCenter)
        body.addWidget(lbl_sec)

        self.lbl_notice = QLabel(self.notice or "")
        self.lbl_notice.setWordWrap(True)
        self.lbl_notice.setAlignment(Qt.AlignCenter)
        self.lbl_notice.setFont(ui_theme.qfont(9, bold=True))
        self.lbl_notice.setStyleSheet(f"color: {self._pal['danger']}; background: transparent;")
        if not self.notice:
            self.lbl_notice.hide()
        body.addWidget(self.lbl_notice)
        body.addStretch(1)

        ui_theme.fit_dialog_widget(self, 440, 470)
        self.e_user.setFocus()

    def _show_notice(self, text):
        self.lbl_notice.setText(text)
        self.lbl_notice.show()

    def try_login(self):
        username = self.e_user.text().strip()
        entered = self.e_pass.text()
        u = self.db.authenticate(username, entered)
        if u:
            self._log("login ok: user=%s role=%s" % (u["username"], u.get("role", "")))
            if self.db.is_default_password(u["username"]):
                self._log("forced password change dialog opening for %s" % u["username"])
                try:
                    ok = force_password_change_dialog(self, self.db, u, old_password=entered)
                except Exception as e:
                    self._log("forced password change dialog ERROR: %r" % (e,))
                    messagebox.showerror(
                        "خطأ",
                        "تعذّر فتح نافذة تغيير كلمة المرور (%s).\nأعد المحاولة." % e,
                        parent=self,
                    )
                    self.e_pass.clear()
                    self.e_pass.setFocus()
                    return
                self._log("forced password change dialog closed ok=%s" % ok)
                if not ok:
                    self._show_notice("لم يتم تغيير كلمة المرور الافتراضية —\nيجب تغييرها قبل الدخول.")
                    messagebox.showinfo(
                        "تنبيه",
                        "لم يتم تغيير كلمة المرور الافتراضية.\nسجّل الدخول مرة أخرى وغيّرها قبل الاستخدام.",
                        parent=self,
                    )
                    self.e_pass.clear()
                    self.e_pass.setFocus()
                    return
            self.user = u
            self.accept()
        else:
            try:
                self.db.audit(username or "?", "login_failed", "wrong password")
            except Exception:
                pass
            messagebox.showerror("خطأ", "اسم المستخدم أو كلمة المرور غير صحيحة", parent=self)

    def run(self):
        self.exec()
        return self.user


def ui_dialogs_set(theme_name, accent):
    messagebox.set_theme(theme_name, accent)
