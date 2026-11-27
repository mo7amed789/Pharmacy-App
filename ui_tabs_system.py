# -*- coding: utf-8 -*-
"""
System & Companion tabs mixin (PySide6-Fluent-Widgets):
  - Tab 9: Mobile Companion, Windows Hotspot, Firewall Diagnostics, Connect-QR, Receipts & Printing
  - Tab 7: Settings, Theme & Customization, Printer Settings, Users/Security, Backup/Restore/CSV,
           Cloud Sync (Supabase), GitHub Auto-Updater, Automation, Audit & System Logs, Remote Monitor
"""
from datetime import datetime
import json as _json
import os
import shutil
import ssl
import threading
import urllib.error
import urllib.request
import webbrowser

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    EditableComboBox,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    TextEdit,
    TitleLabel,
)

from app_helpers import BASE, money, qr_url_with_pin
from database import DB
import ui_dialogs as messagebox
import ui_theme

try:
    import mobile_server
except Exception:
    mobile_server = None
try:
    import hotspot
except Exception:
    hotspot = None
try:
    import firewall
except Exception:
    firewall = None
try:
    import qrgen
except Exception:
    qrgen = None
try:
    import printer as receipt_printer
except Exception:
    receipt_printer = None


class SystemTabsMixin:
    """Mobile/Printing and Settings/Logs tabs & dialogs."""

    # =========================================================================
    # Mobile Companion & Printing (Tab 9)
    # =========================================================================
    def build_mobile(self, outer=None):
        container = outer or self._tab_widgets[9]
        outer_lay = QVBoxLayout(container)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll, _inner, tab = ui_theme.make_scroll_page("mobInner")
        outer_lay.addWidget(scroll)

        tab.addWidget(TitleLabel("📱 الموبايل والطباعة"))
        tab.addWidget(CaptionLabel("نفس الواي فاي — شبكة محلية فقط."))

        # Windows Hotspot Card
        hcard = CardWidget()
        hl = QVBoxLayout(hcard)
        hl.setContentsMargins(14, 12, 14, 12)
        hl.setSpacing(6)
        self.lbl_hotspot_status = StrongBodyLabel("هوت سبوت ويندوز: —")
        hl.addWidget(self.lbl_hotspot_status)
        self.lbl_hotspot_info = CaptionLabel("الاسم وكلمة المرور من إعدادات ويندوز.")
        self.lbl_hotspot_info.setWordWrap(True)
        hl.addWidget(self.lbl_hotspot_info)

        hbtns = QHBoxLayout()
        self.btn_hotspot_start = PrimaryPushButton("📶 تشغيل الهوت سبوت")
        self.btn_hotspot_start.clicked.connect(self.hotspot_start_async)
        self.btn_hotspot_stop = PushButton("⏹ إيقاف الهوت سبوت")
        self.btn_hotspot_stop.clicked.connect(self.hotspot_stop_async)
        b_hs_set = PushButton("⚙️ إعدادات الهوت سبوت")
        b_hs_set.clicked.connect(self.hotspot_open_settings)
        b_hs_ref = PushButton("🔄 تحديث الحالة")
        b_hs_ref.clicked.connect(self.hotspot_refresh_async)
        for b in (self.btn_hotspot_start, self.btn_hotspot_stop, b_hs_set, b_hs_ref):
            hbtns.addWidget(b)
        hbtns.addStretch(1)
        hl.addLayout(hbtns)
        hl.addWidget(CaptionLabel("1) شغّل الهوت سبوت  2) اتصل به من الموبايل  3) افتح الرابط  4) أدخل PIN."))
        tab.addWidget(hcard)

        # Server Status & PIN Card
        scard = CardWidget()
        sl = QVBoxLayout(scard)
        sl.setContentsMargins(14, 12, 14, 12)
        sl.setSpacing(8)
        self.lbl_mobile_status = StrongBodyLabel("السيرفر: متوقف")
        self.lbl_mobile_url = SubtitleLabel("الرابط: — (شغّل السيرفر أولاً)")
        sl.addWidget(self.lbl_mobile_status)
        sl.addWidget(self.lbl_mobile_url)

        pin_box = CardWidget()
        pl = QHBoxLayout(pin_box)
        pl.setContentsMargins(12, 8, 12, 8)
        pl.addWidget(StrongBodyLabel("رمز الموبايل (PIN):"))
        self.lbl_mobile_pin = QLabel("—")
        self.lbl_mobile_pin.setFont(ui_theme.qfont(20, bold=True))
        self.lbl_mobile_pin.setStyleSheet(f"color: {self.pal['accent']}; background: transparent;")
        pl.addWidget(self.lbl_mobile_pin)
        pl.addStretch(1)
        sl.addWidget(pin_box)

        self.lbl_live_update = CaptionLabel("🟢 متصل — آخر تحديث: —")
        sl.addWidget(self.lbl_live_update)

        sbtns = QHBoxLayout()
        self.btn_mobile_start = PrimaryPushButton("▶️ تشغيل السيرفر")
        self.btn_mobile_start.clicked.connect(self.mobile_toggle_server)
        b_pc = PushButton("🌐 فتح على الكمبيوتر")
        b_pc.clicked.connect(self.open_mobile_site_on_pc)
        b_pin = PushButton("🔑 تغيير الرمز")
        b_pin.clicked.connect(self.regenerate_mobile_pin_ui)
        b_mref = PushButton("🔄 تحديث")
        b_mref.clicked.connect(self.mobile_refresh)
        for b in (self.btn_mobile_start, b_pc, b_pin, b_mref):
            sbtns.addWidget(b)
        sbtns.addStretch(1)
        sl.addLayout(sbtns)
        sl.addWidget(CaptionLabel("للتجربة على الكمبيوتر فقط (127.0.0.1)."))
        tab.addWidget(scard)

        # URLs & HTTPS Card
        ucard = CardWidget()
        ul = QVBoxLayout(ucard)
        ul.setContentsMargins(14, 12, 14, 12)
        ul.setSpacing(6)
        ul.addWidget(StrongBodyLabel("🔗 الروابط — جرّب رابط شبكة هاتفك:"))
        urow = QHBoxLayout()
        self.txt_mobile_urls = TextEdit()
        self.txt_mobile_urls.setReadOnly(True)
        self.txt_mobile_urls.setFont(ui_theme.qfont(11, family="Consolas"))
        self.txt_mobile_urls.setFixedHeight(85)
        urow.addWidget(self.txt_mobile_urls, 1)
        self._url_btns_layout = QVBoxLayout()
        urow.addLayout(self._url_btns_layout)
        ul.addLayout(urow)

        ul.addWidget(StrongBodyLabel("🔒 رابط آمن (HTTPS) للمسح بالكاميرا:"))
        self.lbl_https_url = StrongBodyLabel("الرابط الآمن: — (شغّل السيرفر أولاً)")
        ul.addWidget(self.lbl_https_url)
        b_copy_https = PushButton("📋 نسخ الرابط الآمن")
        b_copy_https.clicked.connect(lambda: self._copy_text(self._https_url()))
        ul.addWidget(b_copy_https, 0, Qt.AlignLeft)
        ul.addWidget(CaptionLabel("أول مرة: «متقدم» ثم «المتابعة إلى الموقع»."))
        tab.addWidget(ucard)

        # Connect-QR Card
        qcard = CardWidget()
        ql_top = QVBoxLayout(qcard)
        ql_top.setContentsMargins(14, 12, 14, 12)
        ql_top.addWidget(StrongBodyLabel("📷 QR للاتصال السريع"))
        qrow = QHBoxLayout()
        qrow.setSpacing(16)

        self.qr_label = QLabel("شغّل السيرفر أولاً\nلعرض رمز QR")
        self.qr_label.setFixedSize(260, 260)
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setStyleSheet(
            f"background-color: white; color: {self.pal['danger']}; border: 2px solid {self.pal['accent']}; border-radius: 8px; font-weight: bold;"
        )
        qrow.addWidget(self.qr_label)

        qctl = QVBoxLayout()
        qctl.addWidget(CaptionLabel("اختر رابط شبكة هاتفك:"))
        self.cmb_qr_url = ComboBox()
        self.cmb_qr_url.setMinimumWidth(340)
        self.cmb_qr_url.currentIndexChanged.connect(lambda _i: self._qr_refresh())
        qctl.addWidget(self.cmb_qr_url)

        self.lbl_qr_url = StrongBodyLabel("—")
        qctl.addWidget(self.lbl_qr_url)

        qbtns = QHBoxLayout()
        b_qref = PushButton("🔄 تحديث QR")
        b_qref.clicked.connect(self._qr_refresh)
        b_qcopy = PushButton("📋 نسخ")
        b_qcopy.clicked.connect(lambda: self._copy_text(self.cmb_qr_url.currentText()))
        qbtns.addWidget(b_qref)
        qbtns.addWidget(b_qcopy)
        qbtns.addStretch(1)
        qctl.addLayout(qbtns)

        self.lbl_qr_note = CaptionLabel("")
        self.lbl_qr_note.setWordWrap(True)
        qctl.addWidget(self.lbl_qr_note)
        self.lbl_qr_status = StrongBodyLabel("حالة رمز QR: —")
        qctl.addWidget(self.lbl_qr_status)
        qctl.addStretch(1)
        qrow.addLayout(qctl, 1)
        ql_top.addLayout(qrow)
        tab.addWidget(qcard)

        # Diagnostics & Firewall Card
        dcard = CardWidget()
        dl = QVBoxLayout(dcard)
        dl.setContentsMargins(14, 12, 14, 12)
        dl.setSpacing(8)
        dl.addWidget(StrongBodyLabel("🔍 اختبار الاتصال وجدار الحماية"))
        db_row = QHBoxLayout()
        b_diag = PrimaryPushButton("🔍 اختبار الاتصال")
        b_diag.clicked.connect(self.diag_run_async)
        b_fw = PushButton("🛡️ إصلاح الاتصال")
        b_fw.clicked.connect(self.firewall_fix_async)
        b_dcopy = PushButton("📋 نسخ النتائج")
        b_dcopy.clicked.connect(self.diag_copy_results)
        for b in (b_diag, b_fw, b_dcopy):
            db_row.addWidget(b)
        db_row.addStretch(1)
        dl.addLayout(db_row)

        if self.is_admin:
            self.chk_shared_pin = CheckBox("السماح بـ PIN المشترك القديم (بلا اسم موظف). أوقفه بعد تجهيز حسابات الموظفين")
            self.chk_shared_pin.setChecked(self.db.get_setting("mobile_shared_pin_enabled", "1") == "1")

            def set_shared_mobile():
                val = self.chk_shared_pin.isChecked()
                if not val and not messagebox.askyesno(
                    "دخول الموظفين فقط",
                    "إيقاف PIN المشترك؟ تأكد من إنشاء حسابات الموظفين أولاً. الهواتف القديمة ستحتاج الدخول باسم مستخدم وكلمة مرور.",
                    parent=self,
                ):
                    self.chk_shared_pin.blockSignals(True)
                    self.chk_shared_pin.setChecked(True)
                    self.chk_shared_pin.blockSignals(False)
                    return
                self.db.set_setting("mobile_shared_pin_enabled", "1" if val else "0")
                self.db.audit(self.username, "mobile_shared_access", "enabled=%s" % val)

            self.chk_shared_pin.stateChanged.connect(lambda _s: set_shared_mobile())
            dl.addWidget(self.chk_shared_pin)

        self.txt_diag = TextEdit()
        self.txt_diag.setReadOnly(True)
        self.txt_diag.setPlainText("اضغط «اختبار الاتصال».")
        self.txt_diag.setFixedHeight(170)
        dl.addWidget(self.txt_diag)
        self.diag_text = ""
        tab.addWidget(dcard)

        # Request Log Card
        rcard = CardWidget()
        rl = QVBoxLayout(rcard)
        rl.setContentsMargins(14, 12, 14, 12)
        rl.setSpacing(6)
        rl.addWidget(StrongBodyLabel("📋 الطلبات الأخيرة — من يطلب ماذا؟"))
        rbtns = QHBoxLayout()
        b_rref = PushButton("🔄 تحديث الطلبات")
        b_rref.clicked.connect(self.refresh_requests_view)
        b_rclr = PushButton("🗑 مسح السجل")
        b_rclr.clicked.connect(self.clear_requests_view)
        rbtns.addWidget(b_rref)
        rbtns.addWidget(b_rclr)
        rbtns.addStretch(1)
        rl.addLayout(rbtns)

        self.lbl_req_summary = StrongBodyLabel("لا توجد طلبات مسجلة بعد — شغّل السيرفر ثم اضغط «تحديث الطلبات».")
        self.lbl_req_summary.setWordWrap(True)
        rl.addWidget(self.lbl_req_summary)

        self.txt_requests = TextEdit()
        self.txt_requests.setReadOnly(True)
        self.txt_requests.setFont(ui_theme.qfont(10, family="Consolas"))
        self.txt_requests.setPlainText("—")
        self.txt_requests.setFixedHeight(140)
        rl.addWidget(self.txt_requests)
        tab.addWidget(rcard)

        # Pending Print Queue Card
        pcard = CardWidget()
        pl_q = QVBoxLayout(pcard)
        pl_q.setContentsMargins(14, 12, 14, 12)
        pl_q.setSpacing(8)
        pl_q.addWidget(CaptionLabel("1) شغّل السيرفر  2) افتح الرابط  3) أدخل الرمز  4) احفظ الفاتورة  5) اطبعها هنا."))
        pl_q.addWidget(StrongBodyLabel("🧾 بانتظار الطباعة:"))
        self.tree_mobile = TableWidget()
        ui_theme.configure_table(self.tree_mobile, ("رقم الفاتورة", "التاريخ", "الكاشير", "العميل", "الإجمالي", "الدفع"), (140, 140, 130, 180, 130, 100), stretch_cols=(3,), min_height=220)
        pl_q.addWidget(self.tree_mobile, 1)

        mbtns = QHBoxLayout()
        b_show_r = PrimaryPushButton("🧾 عرض الإيصال")
        b_show_r.clicked.connect(self.mobile_show_receipt)
        b_prt = PushButton("🖨️ طباعة")
        b_prt.clicked.connect(self.mobile_print_selected)
        mbtns.addWidget(b_show_r)
        mbtns.addWidget(b_prt)
        if self.is_admin:
            b_med = PushButton("✏️ تعديل")
            b_med.clicked.connect(self.mobile_edit_selected)
            mbtns.addWidget(b_med)
        b_mall = PushButton("📋 كل الفواتير")
        b_mall.clicked.connect(self.mobile_show_all)
        mbtns.addWidget(b_mall)
        mbtns.addStretch(1)
        pl_q.addLayout(mbtns)
        tab.addWidget(pcard)

        self.mobile_rows = []
        self.mobile_refresh()

    def mobile_pin(self):
        try:
            return self.db.ensure_mobile_pin()
        except Exception:
            return "------"

    def mobile_refresh(self):
        if not hasattr(self, "tree_mobile"):
            return
        try:
            self.mobile_rows = self.db.pending_phone_invoices()
            if not self.mobile_rows:
                ui_theme.set_table_rows(self.tree_mobile, [("لا توجد فواتير بانتظار الطباعة", "—", "—", "—", "—", "—")])
            else:
                ui_theme.set_table_rows(
                    self.tree_mobile,
                    [
                        (s["invoice_no"], s["date"], s["cashier"], s.get("customer_name", "") or "عميل نقدي", money(s["total"]), s["payment_method"])
                        for s in self.mobile_rows
                    ],
                )
            self._mobile_update_labels()
        except Exception:
            pass

    def _mobile_update_labels(self):
        try:
            running = getattr(self, "mobile_server", None) is not None and self.mobile_server.running
            if running:
                self.lbl_mobile_status.setText("السيرفر: 🟢 يعمل")
                self.lbl_mobile_status.setStyleSheet(f"color: {self.pal['success']};")
                self.lbl_mobile_url.setText("الرابط: %s" % self.mobile_server.url)
                self.btn_mobile_start.setText("⏹ إيقاف السيرفر")
            else:
                self.lbl_mobile_status.setText("السيرفر: 🔴 متوقف")
                self.lbl_mobile_status.setStyleSheet(f"color: {self.pal['danger']};")
                self.lbl_mobile_url.setText("الرابط: —")
                self.btn_mobile_start.setText("▶️ تشغيل السيرفر")
            pin = self.mobile_pin()
            pin_shown = pin if self.is_admin else "••••••"
            self.lbl_mobile_pin.setText(pin_shown)
            if hasattr(self, "lbl_settings_pin"):
                self.lbl_settings_pin.setText("رمز الموبايل الحالي (PIN): %s" % pin_shown)
        except Exception:
            pass
        self._mobile_update_url_list()

    def _copy_text(self, text):
        try:
            QApplication.clipboard().setText(str(text or ""))
            self.show_banner("تم نسخ: %s" % text, "success")
        except Exception:
            pass

    def _mobile_update_url_list(self):
        try:
            if not hasattr(self, "txt_mobile_urls"):
                return
            urls = []
            if mobile_server is not None:
                try:
                    urls = mobile_server.mobile_urls(8080)
                except Exception:
                    urls = []
            if not urls:
                urls = [{"ip": "—", "label": "لا توجد شبكة", "adapter": "", "url": "لا يوجد عنوان شبكة — تأكد من اتصال الكمبيوتر بالواي فاي"}]
            self.txt_mobile_urls.setPlainText("\n".join("%s  (%s)" % (u["url"], u["label"]) for u in urls))
            while self._url_btns_layout.count():
                item = self._url_btns_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            for u in urls:
                if u["url"].startswith("http"):
                    b = PushButton("📋 نسخ %s" % u["ip"])
                    b.clicked.connect(lambda _c=False, t=u["url"]: self._copy_text(t))
                    self._url_btns_layout.addWidget(b)
            self._url_btns_layout.addStretch(1)

            try:
                hurl = self._https_url()
                if hurl:
                    self.lbl_https_url.setText("الرابط الآمن: %s" % hurl)
                elif getattr(self, "mobile_server", None) is not None and getattr(self.mobile_server, "https_error", ""):
                    self.lbl_https_url.setText("الرابط الآمن: — (%s)" % self.mobile_server.https_error)
                else:
                    self.lbl_https_url.setText("الرابط الآمن: — (شغّل السيرفر أولاً)")
            except Exception:
                pass
            self._qr_refresh()
        except Exception:
            pass

    def _https_url(self):
        try:
            srv = getattr(self, "mobile_server", None)
            if srv is not None and getattr(srv, "https_running", False):
                urls = srv.https_url_list
                if urls:
                    return urls[0]["url"]
        except Exception:
            pass
        return ""

    def _qr_url_choices(self):
        urls = []
        try:
            srv = getattr(self, "mobile_server", None)
            if srv is not None and getattr(srv, "https_running", False):
                urls += [u["url"] for u in srv.https_url_list if u["url"].startswith("https")]
            if mobile_server is not None:
                urls += [u["url"] for u in mobile_server.mobile_urls(8080) if u["url"].startswith("http")]
        except Exception:
            pass
        try:
            pin = self.db.ensure_mobile_pin() if getattr(self, "mobile_server", None) else ""
        except Exception:
            pin = ""
        seen = set()
        out = []
        for url in urls:
            qr_url = qr_url_with_pin(url, pin)
            if qr_url and qr_url not in seen:
                seen.add(qr_url)
                out.append(qr_url)
        return out

    def _qr_status(self, running, url=""):
        try:
            if not hasattr(self, "lbl_qr_status"):
                return
            now = datetime.now().strftime("%H:%M:%S")
            self.lbl_qr_status.setText(("🟢 QR حي — %s" if running else "🔴 QR متوقف — %s") % now)
        except Exception:
            pass

    def _qr_refresh(self, *_args):
        try:
            if not hasattr(self, "qr_label"):
                return
            running = getattr(self, "mobile_server", None) is not None and self.mobile_server.running
            choices = self._qr_url_choices()
            cur = self.cmb_qr_url.currentText().strip()
            existing_items = [self.cmb_qr_url.itemText(i) for i in range(self.cmb_qr_url.count())]
            if existing_items != choices:
                self.cmb_qr_url.blockSignals(True)
                self.cmb_qr_url.clear()
                self.cmb_qr_url.addItems(choices)
                if cur in choices:
                    self.cmb_qr_url.setCurrentText(cur)
                self.cmb_qr_url.blockSignals(False)
            url = self.cmb_qr_url.currentText().strip()
            if not running:
                self.lbl_qr_url.setText("— السيرفر متوقف —")
                if getattr(self, "_qr_drawn_running", None) is not False:
                    self.qr_label.clear()
                    self.qr_label.setText("شغّل السيرفر أولاً\nلعرض رمز QR")
                    self._qr_drawn_url = None
                    self._qr_drawn_running = False
                self.lbl_qr_note.setText("السيرفر متوقف — شغّله أولاً.")
                self._qr_status(False)
                return

            self.lbl_qr_url.setText(url or "— لا يوجد رابط —")
            if url and url == getattr(self, "_qr_drawn_url", None) and getattr(self, "_qr_drawn_running", None) is True:
                self._qr_status(True, url)
                return

            if qrgen is None:
                raise RuntimeError("ملف qrgen.py غير موجود")
            if not url or not url.startswith("http"):
                raise RuntimeError("لا يوجد رابط صالح")
            qr = qrgen.encode_qr(url)
            n = qr.size
            border = 4
            total = n + 2 * border
            cell = max(4, min(8, 260 // max(total, 1)))
            px = total * cell
            img = QImage(px, px, QImage.Format_RGB32)
            img.fill(QColor("white"))
            painter = QPainter(img)
            black = QColor("black")
            for y in range(n):
                for x in range(n):
                    if qr.modules[y][x]:
                        painter.fillRect((x + border) * cell, (y + border) * cell, cell, cell, black)
            painter.end()
            self.qr_label.setFixedSize(max(220, px), max(220, px))
            self.qr_label.setPixmap(QPixmap.fromImage(img))
            self._qr_drawn_url = url
            self._qr_drawn_running = True
            if url.startswith("https"):
                self.lbl_qr_note.setText("امسح الرمز للدخول والمسح بالكاميرا. أول مرة: «متقدم» ثم «المتابعة». الكود يحتوي PIN — لا تشارك صورته.")
            else:
                self.lbl_qr_note.setText("HTTPS غير متاح حالياً — الفواتير تعمل، لكن المسح الحي يحتاج الرابط الآمن.")
            self._qr_status(True, url)
        except Exception as e:
            self._qr_drawn_url = None
            self._qr_drawn_running = None
            self.qr_label.clear()
            self.qr_label.setText(self.cmb_qr_url.currentText().strip() or "—")
            self.lbl_qr_note.setText("تعذّر رسم QR (%s) — انسخ الرابط بالزر." % e)
            self._qr_status(getattr(self, "mobile_server", None) is not None and self.mobile_server.running)

    def open_mobile_site_on_pc(self):
        if mobile_server is None:
            messagebox.showerror("خطأ", "ملف mobile_server.py غير موجود", parent=self)
            return
        running = getattr(self, "mobile_server", None) is not None and self.mobile_server.running
        if not running:
            self.show_banner("جارٍ تشغيل السيرفر…", "info")
            self.mobile_toggle_server()
            QTimer.singleShot(1000, self._open_local_site)
        else:
            self._open_local_site()

    def _open_local_site(self):
        url = "http://127.0.0.1:8080/"
        running = getattr(self, "mobile_server", None) is not None and self.mobile_server.running
        if not running:
            messagebox.showerror("خطأ", "تعذّر تشغيل السيرفر على 8080 — تأكد أنه لا يعمل سيرفر آخر.", parent=self)
            return
        try:
            webbrowser.open(url)
            self.show_banner("تم الفتح (%s) — أدخل PIN." % url, "success")
        except Exception as e:
            messagebox.showerror("خطأ", "تعذّر فتح المتصفح: %s" % e, parent=self)

    def diag_copy_results(self):
        if getattr(self, "diag_text", ""):
            self._copy_text(self.diag_text)
        else:
            messagebox.showinfo("تنبيه", "شغّل «اختبار الاتصال» أولاً", parent=self)

    def _diag_http_get(self, url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PharmacyDiag/1.0"})
            with urllib.request.urlopen(req, timeout=3) as r:
                r.read(200)
            return True, "رد السيرفر (HTTP %d)" % r.status
        except urllib.error.HTTPError as e:
            return True, "رد السيرفر (HTTP %d — السيرفر شغال)" % e.code
        except Exception as e:
            reason = str(getattr(e, "reason", e))
            if "timed out" in reason.lower() or "timeout" in reason.lower():
                return False, "انتهت المهلة (Timeout) — مثل خطأ الهاتف تماماً"
            return False, "تعذر الوصول: %s" % reason

    def _diag_https_get(self, url):
        try:
            ctx = ssl._create_unverified_context()
            req = urllib.request.Request(url, headers={"User-Agent": "PharmacyDiag/1.0"})
            with urllib.request.urlopen(req, timeout=3, context=ctx) as r:
                r.read(200)
            return True, "رد السيرفر (HTTPS %d)" % r.status
        except urllib.error.HTTPError as e:
            return True, "رد السيرفر (HTTPS %d — السيرفر شغال)" % e.code
        except Exception as e:
            if "timeout" in str(e).lower():
                return False, "انتهت المهلة (Timeout)"
            return False, "تعذر الوصول: %s" % e

    def _diag_run(self):
        lines = []
        running = getattr(self, "mobile_server", None) is not None and self.mobile_server.running
        lines.append("✅ السيرفر يعمل" if running else "❌ السيرفر متوقف — شغّله أولاً")
        ok, detail = self._diag_http_get("http://127.0.0.1:8080/")
        lines.append(("✅ اختبار من الكمبيوتر نفسه (8080): %s" if ok else "❌ اختبار من الكمبيوتر نفسه (8080): %s") % detail)
        ok, detail = self._diag_https_get("https://127.0.0.1:8443/")
        if ok:
            lines.append("✅ اختبار HTTPS (8443): %s" % detail)
        else:
            lines.append("❌ اختبار HTTPS (8443): %s — تأكد من الشهادة." % detail)
        try:
            srv = getattr(self, "mobile_server", None)
            if srv is not None:
                if getattr(srv, "cert_regenerated", False):
                    lines.append("✅ الشهادة: تم توليد شهادة جديدة تغطي عناوين الكمبيوتر الحالية.")
                elif getattr(srv, "cert_covers_current_ip", None) is False:
                    lines.append("⚠️ الشهادة: لا تغطي عنوان الكمبيوتر الحالي — أعد تشغيل السيرفر.")
                elif getattr(srv, "cert_covers_current_ip", None) is True:
                    lines.append("✅ الشهادة: تغطي عنوان الكمبيوتر الحالي.")
        except Exception:
            pass
        urls = []
        if mobile_server is not None:
            try:
                urls = mobile_server.mobile_urls(8080)
            except Exception:
                urls = []
        if not urls:
            lines.append("❌ لا يوجد عنوان شبكة — فعّل الواي فاي.")
        for u in urls:
            ok, detail = self._diag_http_get(u["url"] + "/")
            lines.append(("✅" if ok else "❌") + " رابط %s (%s): %s" % (u["url"], u["label"], detail))
        if firewall is None:
            lines.append("❓ فحص الفايروول: ملف firewall.py غير موجود.")
        else:
            try:
                st = firewall.firewall_status()
                ports = st.get("ports") or {}
                if st.get("exists") is True:
                    lines.append("✅ الفايروول: 8080 و 8443 مفتوحان (خاص + عام).")
                elif ports:
                    for port in (8080, 8443):
                        info = ports.get(port) or {}
                        priv, pub = info.get("private"), info.get("public")
                        if priv and pub:
                            lines.append("✅ الفايروول: البورت %d مفتوح (خاص + عام)." % port)
                        elif priv and not pub:
                            lines.append("❌ الفايروول: البورت %d مفتوح للشبكات الخاصة فقط — اضغط «إصلاح الاتصال»." % port)
                        elif pub and not priv:
                            lines.append("❌ الفايروول: البورت %d مفتوح للشبكات العامة فقط — اضغط «إصلاح الاتصال»." % port)
                        else:
                            lines.append("❌ الفايروول: لا توجد قاعدة للبورت %d — اضغط «إصلاح الاتصال»." % port)
                else:
                    lines.append("❓ جدار الحماية: %s" % st.get("message", "تعذر الفحص"))
                if not st.get("admin"):
                    lines.append("⚠️ البرنامج لا يعمل كمسؤول.")
            except Exception as e:
                lines.append("❓ جدار الحماية: تعذر الفحص (%s)" % e)
        try:
            if hotspot is not None:
                st = hotspot.get_hotspot_status()
                if st.get("state") == "On":
                    lines.append("✅ هوت سبوت ويندوز يعمل — الشبكة: %s" % (st.get("ssid") or "؟"))
                elif st.get("state") == "Off":
                    lines.append("ℹ️ هوت سبوت ويندوز متوقف.")
                else:
                    lines.append("❓ حالة هوت سبوت ويندوز: %s" % (st.get("error") or ""))
        except Exception as e:
            lines.append("❓ حالة هوت سبوت ويندوز: تعذر الفحص (%s)" % e)
        return "\n".join(lines)

    def diag_run_async(self):
        self.show_banner("جارٍ الاختبار…", "info")
        threading.Thread(target=lambda: self._ui_post(lambda txt=self._diag_run(): self._diag_show(txt)), daemon=True).start()

    def _diag_show(self, text):
        self.diag_text = text
        if hasattr(self, "txt_diag"):
            self.txt_diag.setPlainText(text)
        self.show_banner("اكتمل الاختبار.", "info")

    def refresh_requests_view(self):
        try:
            srv = getattr(self, "mobile_server", None)
            if srv is None or not srv.running:
                self.lbl_req_summary.setText("السيرفر متوقف — شغّله أولاً لعرض الطلبات.")
                self._set_requests_text("—")
                return
            sm = srv.request_summary()
            total = sm.get("total", 0)
            by_ip = sm.get("by_ip") or []
            by_path = sm.get("by_path") or []
            by_status = sm.get("by_status") or []
            top_ip = by_ip[0] if by_ip else None
            summary = "إجمالي الطلبات منذ تشغيل السيرفر: %d" % total
            if top_ip:
                summary += " — أكثر IP طلباً: %s (%d طلب)" % (top_ip[0], top_ip[1])
            self.lbl_req_summary.setText(summary)
            lines = []
            if by_ip:
                lines.append("حسب الجهاز (IP): " + ", ".join("%s: %d" % (ip, n) for ip, n in by_ip))
            if by_path:
                lines.append("حسب المسار: " + ", ".join("%s: %d" % (pa, n) for pa, n in by_path[:6]))
            if by_status:
                lines.append("حسب النتيجة: " + ", ".join("%s: %d" % (st, n) for st, n in by_status))
            lines.append("")
            for r in sm.get("recent") or []:
                lines.append("%s  %-15s %-4s %-28s %s  %s" % (r.get("t", ""), r.get("ip", ""), r.get("method", ""), r.get("path", "")[:28], r.get("status", ""), r.get("ua", "")))
            if not (sm.get("recent") or []):
                lines.append("لا توجد طلبات بعد — افتح صفحة الموبايل وستظهر هنا.")
            self._set_requests_text("\n".join(lines))
        except Exception as e:
            self.lbl_req_summary.setText("تعذّر عرض الطلبات: %s" % e)

    def _set_requests_text(self, text):
        if hasattr(self, "txt_requests"):
            self.txt_requests.setPlainText(text)

    def clear_requests_view(self):
        srv = getattr(self, "mobile_server", None)
        if srv is not None:
            srv.clear_request_log()
        self.refresh_requests_view()

    def firewall_fix_async(self):
        if firewall is None:
            messagebox.showerror("خطأ", "ملف firewall.py غير موجود", parent=self)
            return
        self.show_banner("جارٍ فتح البورتين…", "info")

        def _work():
            ok, msg = firewall.add_rule()
            self._ui_post(lambda: self._firewall_fix_done(ok, msg))

        threading.Thread(target=_work, daemon=True).start()

    def _firewall_fix_done(self, ok, msg):
        if ok:
            self.show_banner(msg, "success")
            messagebox.showinfo("جدار الحماية", msg, parent=self)
        else:
            self.show_banner(msg, "error")
            messagebox.showerror("جدار الحماية", msg, parent=self)
        self.diag_run_async()

    def mobile_toggle_server(self):
        if mobile_server is None:
            messagebox.showerror("خطأ", "ملف mobile_server.py غير موجود", parent=self)
            return
        if getattr(self, "mobile_server", None) is not None and self.mobile_server.running:
            try:
                self.mobile_server.stop()
            except Exception:
                pass
            self.mobile_server = None
            self.show_banner("تم إيقاف سيرفر الموبايل", "info")
        else:
            srv = mobile_server.MobileServer(db_path=self.db.path, port=8080)
            if not srv.start():
                detail = getattr(srv, "start_error", "") or "تعذر تشغيل السيرفر على المنفذ 8080."
                messagebox.showerror("خطأ", detail, parent=self)
                return
            self.mobile_server = srv
            self.db.audit(self.username, "mobile_server_start", srv.url)
            if getattr(srv, "https_running", False):
                self.show_banner("🟢 سيرفر الموبايل يعمل — %s — HTTPS: %s" % (srv.url, srv.https_url), "success")
            else:
                self.show_banner("🟢 سيرفر الموبايل يعمل على HTTP فقط (%s)" % (getattr(srv, "https_error", "") or ""), "info")
        self._mobile_update_labels()

    def regenerate_mobile_pin_ui(self):
        if not self.is_admin:
            messagebox.showerror("صلاحيات", "تغيير رمز الموبايل صلاحية المدير فقط", parent=self)
            return
        pin = self.db.regenerate_mobile_pin()
        self.db.audit(self.username, "mobile_pin_regen", "")
        self._mobile_update_labels()
        messagebox.showinfo("رمز جديد", "رمز الموبايل الجديد (PIN): %s\nأدخله على الهاتف عند الطلب." % pin, parent=self)

    def _hotspot_available(self):
        if hotspot is None:
            messagebox.showerror("خطأ", "ملف hotspot.py غير موجود", parent=self)
            return False
        return True

    def _hotspot_done(self, ok, msg, refresh=True):
        if ok:
            self.show_banner(msg, "success")
            try:
                self.db.audit(self.username, "hotspot_action", msg[:200])
            except Exception:
                pass
        else:
            self.show_banner(msg, "error")
            messagebox.showerror("هوت سبوت ويندوز", msg, parent=self)
        if refresh:
            self.hotspot_refresh_async()
            self._mobile_update_labels()

    def _hotspot_run(self, fn, what):
        if not self._hotspot_available():
            return
        self.show_banner("جارٍ %s — انتظر لحظات..." % what, "info")
        self.btn_hotspot_start.setEnabled(False)
        self.btn_hotspot_stop.setEnabled(False)

        def _done(ok, msg):
            self.btn_hotspot_start.setEnabled(True)
            self.btn_hotspot_stop.setEnabled(True)
            self._hotspot_done(ok, msg)

        hotspot.run_in_thread(fn, done=lambda ok, msg: self._ui_post(lambda: _done(ok, msg)))

    def hotspot_start_async(self):
        self._hotspot_run(hotspot.start_hotspot, "تشغيل هوت سبوت ويندوز")

    def hotspot_stop_async(self):
        self._hotspot_run(hotspot.stop_hotspot, "إيقاف هوت سبوت ويندوز")

    def hotspot_refresh_async(self):
        if not self._hotspot_available():
            return

        def _apply(st):
            state = st.get("state", "Unknown")
            ssid = (st.get("ssid") or "").strip()
            pc_name = ""
            try:
                pc_name = hotspot.pc_hostname()
            except Exception:
                pass
            if state == "On":
                self.lbl_hotspot_status.setText("هوت سبوت ويندوز: 🟢 يعمل — الشبكة: %s" % (ssid or "؟"))
                self.lbl_hotspot_status.setStyleSheet(f"color: {self.pal['success']};")
            elif state == "Off":
                self.lbl_hotspot_status.setText("هوت سبوت ويندوز: 🔴 متوقف")
                self.lbl_hotspot_status.setStyleSheet(f"color: {self.pal['danger']};")
            else:
                self.lbl_hotspot_status.setText("هوت سبوت ويندوز: ❓ غير معروف — %s" % (st.get("error", "") or "اضغط «تشغيل»"))
                self.lbl_hotspot_status.setStyleSheet(f"color: {self.pal['warning']};")
            if ssid:
                self.lbl_hotspot_info.setText("الشبكة: %s — كلمة المرور من إعدادات ويندوز." % ssid)
            elif pc_name:
                self.lbl_hotspot_info.setText("اسم الكمبيوتر: %s — الاسم وكلمة المرور من إعدادات ويندوز." % pc_name)

        threading.Thread(target=lambda: self._ui_post(lambda st=hotspot.get_hotspot_status(): _apply(st)), daemon=True).start()

    def hotspot_open_settings(self):
        if not self._hotspot_available():
            return
        if hotspot.open_hotspot_settings():
            self.show_banner("تم فتح إعدادات الهوت سبوت في ويندوز.", "info")
        else:
            messagebox.showinfo("الإعدادات", "افتح يدوياً: الإعدادات > الشبكة والإنترنت > Mobile hotspot", parent=self)

    def _selected_mobile_sale(self):
        idx = ui_theme.selected_row_index(self.tree_mobile)
        if idx is None or idx >= len(self.mobile_rows):
            messagebox.showinfo("تنبيه", "اختر فاتورة من القائمة أولاً", parent=self)
            return None
        return self.mobile_rows[idx]

    def receipt_lines_for_sale(self, sale):
        items = self.db.get_grouped_sale_items(sale["id"])
        lines = ["Pharmacy Enterprise", self.db.get_setting("pharmacy_name", "صيدلية المؤسسة") or "صيدلية المؤسسة"]
        _phone = self.db.get_setting("pharmacy_phone", "")
        if _phone:
            lines.append("تليفون: %s" % _phone)
        lines += ["فاتورة: %s" % sale["invoice_no"], "التاريخ: %s" % sale["date"], "-" * 34]
        _line_disc_total = 0.0
        for it in items:
            _ld = float(it.get("line_discount") or 0)
            _line_disc_total += _ld
            _txt = "%s x%s @ %s = %s" % (it["trade_en"], it["qty_display"], money(it["unit_price"]), money(it["line_total"]))
            if _ld:
                _txt += "  (خصم: %s)" % money(_ld)
            lines.append(_txt)
        lines.append("-" * 34)
        _total_disc = _line_disc_total + float(sale.get("discount") or 0)
        if _total_disc:
            lines.append("المجموع قبل الخصم: %s" % money(float(sale["subtotal"] or 0) + _line_disc_total))
            lines.append("خصم الأصناف: %s" % money(_line_disc_total))
            lines.append("خصم الفاتورة: %s" % money(sale["discount"]))
            lines.append("إجمالي الخصم: %s" % money(_total_disc))
        lines += ["الإجمالي: %s" % money(sale["total"]), "المدفوع: %s   الباقي: %s" % (money(sale["paid"]), money(sale["change_amount"])), "شكراً لزيارتك"]
        return lines

    def mobile_show_receipt(self):
        sale = self._selected_mobile_sale()
        if sale:
            self._open_receipt_window(sale)

    def _printer_settings(self):
        defaults = {"type": "windows", "name": "", "width": "80mm", "kick": False, "cp864": 37, "cp1256": 50}
        if receipt_printer is None:
            return defaults
        g = self.db.get_setting
        try:
            cp864 = int(g(receipt_printer.SETTING_CP864_PAGE, "37") or 37)
        except (TypeError, ValueError):
            cp864 = 37
        try:
            cp1256 = int(g(receipt_printer.SETTING_CP1256_PAGE, "50") or 50)
        except (TypeError, ValueError):
            cp1256 = 50
        ptype = g(receipt_printer.SETTING_PRINTER_TYPE, "windows") or "windows"
        return {
            "type": ptype if ptype in ("windows", "escpos") else "windows",
            "name": g(receipt_printer.SETTING_PRINTER_NAME, "") or "",
            "width": g(receipt_printer.SETTING_PRINTER_WIDTH, "80mm") or "80mm",
            "kick": (g(receipt_printer.SETTING_PRINTER_KICK, "0") or "0") == "1",
            "cp864": max(0, min(255, cp864)),
            "cp1256": max(0, min(255, cp1256)),
        }

    def _print_lines(self, lines, filename, is_cash=False, escpos_data=None):
        if receipt_printer is None:
            path = os.path.join(BASE, filename)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except Exception as e:
                return False, "تعذر حفظ الإيصال: %s" % e, path
            if os.name == "nt":
                try:
                    os.startfile(path, "print")
                    return True, "طُبعت بطابعة ويندوز الافتراضية", path
                except Exception as e:
                    return False, "لم تُطبع: %s" % e, path
            return False, "حُفظ في:\n%s" % path, path
        try:
            receipt_printer.prune_receipts(BASE)
        except Exception:
            pass
        try:
            path = receipt_printer.save_text(BASE, filename, "\n".join(lines))
        except Exception as e:
            return False, "تعذر حفظ الإيصال: %s" % e, os.path.join(BASE, filename)
        ps = self._printer_settings()
        note = ""
        if ps["type"] == "escpos":
            if os.name != "nt":
                note = "الطباعة المباشرة ESC/POS متاحة على ويندوز فقط — "
            else:
                if escpos_data is None:
                    escpos_data = receipt_printer.build_escpos_receipt(
                        lines, width_chars=receipt_printer.width_chars_for(ps["width"]),
                        kick=bool(ps["kick"] and is_cash), cp864_page=ps["cp864"], cp1256_page=ps["cp1256"],
                    )
                ok, msg = receipt_printer.send_raw_windows(ps["name"], escpos_data)
                if ok:
                    return True, "طُبعت مباشرة على طابعة ESC/POS (%s)" % ps["name"], path
                note = "تعذّرت الطباعة المباشرة (%s) — " % msg
        if os.name == "nt":
            try:
                os.startfile(path, "print")
                return True, note + "طُبعت بطابعة ويندوز الافتراضية", path
            except Exception as e:
                return False, note + "لم تُطبع: %s" % e, path
        return False, note + "حُفظ في:\n%s" % path, path

    def _pos_receipt_print(self, win, inv, lines, pay):
        ok, msg, path = self._print_lines(lines, "receipt_%s.txt" % inv.replace("-", "_"), is_cash=(pay == "cash"))
        if ok:
            self.show_banner("🖨️ طُبعت الفاتورة %s — %s" % (inv, msg), "success")
            win.accept()
        else:
            messagebox.showinfo("لم تُطبع بعد", "حُفظ في:\n%s\n%s" % (path, msg), parent=win)

    def _open_receipt_window(self, sale):
        lines = self.receipt_lines_for_sale(sale)

        def do_print(dlg):
            ok, msg, path = self._print_lines(
                lines, "receipt_%s.txt" % sale["invoice_no"].replace("-", "_"),
                is_cash=(sale.get("payment_method") == "cash"),
            )
            if not ok:
                messagebox.showinfo("لم تُطبع بعد", "حُفظ في:\n%s\n%s — وستبقى في «بانتظار الطباعة»." % (path, msg), parent=dlg)
                return
            try:
                self.db.mark_printed(sale["id"])
                self.db.audit(self.username, "mobile_print", sale["invoice_no"])
            except Exception:
                pass
            self.mobile_refresh()
            self.show_banner("🖨️ طُبعت الفاتورة %s — %s" % (sale["invoice_no"], msg), "success")
            dlg.accept()

        messagebox.TextViewerDialog(
            self, "إيصال %s" % sale["invoice_no"], "\n".join(lines), width=540, height=500, monospace=True,
            extra_buttons=[("🖨️ طباعة", do_print, True)],
        ).exec()

    def mobile_print_selected(self):
        sale = self._selected_mobile_sale()
        if sale:
            self._open_receipt_window(sale)

    def mobile_show_all(self):
        rows = self.db.phone_invoices(limit=50)
        lines = ["فواتير الهاتف (الأحدث أولاً — %d فاتورة):\n" % len(rows)]
        for s in rows:
            done = "🖨️ مطبوعة %s" % s["printed_at"] if s.get("printed_at") else "⏳ بانتظار الطباعة"
            lines.append("- %s | %s | %s | %s | %s" % (s["invoice_no"], s["date"], money(s["total"]), s["payment_method"], done))
        if not rows:
            lines.append("لا توجد فواتير من الهاتف بعد.")
        messagebox.TextViewerDialog(self, "كل فواتير الهاتف", "\n".join(lines), width=760).exec()

    # =========================================================================
    # Settings & Logs (Tab 7)
    # =========================================================================
    def build_settings(self, outer=None):
        container = outer or self._tab_widgets[7]
        outer_lay = QVBoxLayout(container)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll, _inner, f = ui_theme.make_scroll_page("settingsInner")
        outer_lay.addWidget(scroll)
        self._settings_layout = f

        f.addWidget(TitleLabel("إعدادات النظام"))

        # Pharmacy Identity
        c_ph = CardWidget()
        l_ph = QVBoxLayout(c_ph)
        l_ph.setContentsMargins(14, 12, 14, 12)
        l_ph.setSpacing(6)
        l_ph.addWidget(StrongBodyLabel("🏥 بيانات الصيدلية"))
        l_ph.addWidget(CaptionLabel("اسم الصيدلية:"))
        self.e_pharmacy = LineEdit()
        row = self.db.conn.execute("SELECT value FROM settings WHERE key='pharmacy_name'").fetchone()
        self.e_pharmacy.setText(row["value"] if row else "صيدلية المؤسسة")
        l_ph.addWidget(self.e_pharmacy)
        l_ph.addWidget(CaptionLabel("تليفون الصيدلية:"))
        self.e_pharmacy_phone = LineEdit()
        self.e_pharmacy_phone.setText(self.db.get_setting("pharmacy_phone", ""))
        l_ph.addWidget(self.e_pharmacy_phone)
        b_ph = PrimaryPushButton("حفظ اسم وتليفون الصيدلية")
        b_ph.clicked.connect(self.save_pharmacy_name)
        l_ph.addWidget(b_ph, 0, Qt.AlignLeft)
        f.addWidget(c_ph)

        # Theme & Customization
        c_th = CardWidget()
        l_th = QVBoxLayout(c_th)
        l_th.setContentsMargins(14, 12, 14, 12)
        l_th.setSpacing(8)
        l_th.addWidget(StrongBodyLabel("🎨 المظهر والتخصيص"))

        trow = QHBoxLayout()
        self._set_theme_val = self.theme_name
        tgrp = QButtonGroup(self)
        for val, lbl_txt in (("light", "☀️ فاتح"), ("dark", "🌙 داكن")):
            rb = RadioButton(lbl_txt)
            if val == self.theme_name:
                rb.setChecked(True)
            rb.toggled.connect(lambda c, v=val: setattr(self, "_set_theme_val", v) if c else None)
            tgrp.addButton(rb)
            trow.addWidget(rb)
        b_th = PrimaryPushButton("تطبيق المظهر")
        b_th.clicked.connect(lambda: self.apply_theme_now(self._set_theme_val))
        trow.addWidget(b_th)
        trow.addStretch(1)
        l_th.addLayout(trow)

        crow = QHBoxLayout()
        crow.addWidget(BodyLabel("لون التمييز:"))
        self.cb_accent = ComboBox()
        self.cb_accent.addItems(list(ui_theme.ACCENTS.keys()))
        self.cb_accent.setCurrentText(getattr(self, "ui_accent", "teal"))
        crow.addWidget(self.cb_accent)
        crow.addWidget(BodyLabel("حجم الخط:"))
        self.cb_fontsize = ComboBox()
        self.cb_fontsize.addItems(["normal", "large", "xlarge"])
        self.cb_fontsize.setCurrentText(getattr(self, "ui_font_size", "normal"))
        crow.addWidget(self.cb_fontsize)
        crow.addStretch(1)
        l_th.addLayout(crow)

        l_th.addWidget(CaptionLabel("بطاقات لوحة التحكم الظاهرة:"))
        self.dash_card_vars = {}
        _vis = self._dash_visible_cards()
        drow = QHBoxLayout()
        for _k, _lbl in [
            ("sales", "مبيعات اليوم"), ("profit", "صافي ربح اليوم"), ("cash", "نقدي اليوم"),
            ("invoices", "فواتير اليوم"), ("low", "أصناف ناقصة"), ("expiry", "قريبة الانتهاء"),
            ("critical", "طلبات حرجة"), ("inv_value", "قيمة المخزون"),
        ]:
            chk = CheckBox(_lbl)
            chk.setChecked(_k in _vis)
            self.dash_card_vars[_k] = chk
            drow.addWidget(chk)
        drow.addStretch(1)
        l_th.addLayout(drow)

        self.chk_alerts_top = CheckBox("التنبيهات في أعلى لوحة التحكم (قبل الأكثر مبيعاً)")
        self.chk_alerts_top.setChecked(getattr(self, "ui_alerts_top", True))
        l_th.addWidget(self.chk_alerts_top)

        b_cust = PrimaryPushButton("✅ تطبيق التخصيص")
        b_cust.clicked.connect(
            lambda: self.apply_customization(
                self.cb_accent.currentText(),
                self.cb_fontsize.currentText(),
                [k for k, v in self.dash_card_vars.items() if v.isChecked()],
                self.chk_alerts_top.isChecked(),
            )
        )
        l_th.addWidget(b_cust, 0, Qt.AlignLeft)
        f.addWidget(c_th)

        # Mobile PIN Card
        c_pin = CardWidget()
        l_pin = QVBoxLayout(c_pin)
        l_pin.setContentsMargins(14, 12, 14, 12)
        l_pin.addWidget(StrongBodyLabel("📱 الموبايل"))
        self.lbl_settings_pin = BodyLabel("رمز الموبايل الحالي (PIN): %s" % self.mobile_pin())
        l_pin.addWidget(self.lbl_settings_pin)
        b_pin = PushButton("🔑 تغيير رمز الموبايل")
        b_pin.clicked.connect(self.regenerate_mobile_pin_ui)
        l_pin.addWidget(b_pin, 0, Qt.AlignLeft)
        f.addWidget(c_pin)

        # Printer Card
        c_pr = CardWidget()
        l_pr = QVBoxLayout(c_pr)
        l_pr.setContentsMargins(14, 12, 14, 12)
        l_pr.setSpacing(6)
        l_pr.addWidget(StrongBodyLabel("🖨️ الطباعة"))
        _ps = self._printer_settings()
        self._pr_type = _ps["type"]
        pr_row = QHBoxLayout()
        pgrp = QButtonGroup(self)
        for val, txt in (("windows", "طابعة ويندوز الافتراضية"), ("escpos", "طابعة حرارية ESC/POS مباشرة (خام)")):
            rb = RadioButton(txt)
            if val == _ps["type"]:
                rb.setChecked(True)
            rb.toggled.connect(lambda c, v=val: setattr(self, "_pr_type", v) if c else None)
            pgrp.addButton(rb)
            pr_row.addWidget(rb)
        pr_row.addStretch(1)
        l_pr.addLayout(pr_row)

        l_pr.addWidget(CaptionLabel("اسم طابعة ESC/POS (أو منفذ مثل COM1):"))
        _names = receipt_printer.list_windows_printers() if receipt_printer is not None else []
        self.cb_printer_name = EditableComboBox()
        self.cb_printer_name.addItems(_names)
        self.cb_printer_name.setText(_ps["name"])
        l_pr.addWidget(self.cb_printer_name)

        prow2 = QHBoxLayout()
        prow2.addWidget(BodyLabel("عرض الورق:"))
        self.cb_printer_width = ComboBox()
        self.cb_printer_width.addItems(["80mm", "58mm"])
        self.cb_printer_width.setCurrentText(_ps["width"])
        prow2.addWidget(self.cb_printer_width)
        prow2.addWidget(BodyLabel("CP864:"))
        self.e_cp864 = LineEdit()
        self.e_cp864.setText(str(_ps["cp864"]))
        self.e_cp864.setFixedWidth(70)
        prow2.addWidget(self.e_cp864)
        prow2.addWidget(BodyLabel("Windows-1256:"))
        self.e_cp1256 = LineEdit()
        self.e_cp1256.setText(str(_ps["cp1256"]))
        self.e_cp1256.setFixedWidth(70)
        prow2.addWidget(self.e_cp1256)
        prow2.addStretch(1)
        l_pr.addLayout(prow2)

        self.chk_printer_kick = CheckBox("فتح درج النقود عند البيع النقدي (ESC/POS فقط)")
        self.chk_printer_kick.setChecked(_ps["kick"])
        l_pr.addWidget(self.chk_printer_kick)
        b_pr_save = PrimaryPushButton("💾 حفظ إعدادات الطباعة")
        b_pr_save.clicked.connect(self.save_printer_settings)
        l_pr.addWidget(b_pr_save, 0, Qt.AlignLeft)
        f.addWidget(c_pr)

        # Security & Data Card
        c_sec = CardWidget()
        l_sec = QVBoxLayout(c_sec)
        l_sec.setContentsMargins(14, 12, 14, 12)
        l_sec.setSpacing(8)
        l_sec.addWidget(StrongBodyLabel("🔐 الأمان والبيانات"))
        sbtns = QHBoxLayout()
        b_pw = PushButton("تغيير كلمة المرور")
        b_pw.clicked.connect(self.change_password_dialog)
        sbtns.addWidget(b_pw)
        if self.is_admin:
            b_u = PushButton("➕ مستخدم جديد")
            b_u.clicked.connect(self.add_user_dialog)
            b_br = PushButton("🏬 الفروع")
            b_br.clicked.connect(self.branches_dialog)
            sbtns.addWidget(b_u)
            sbtns.addWidget(b_br)
        b_bk = PrimaryPushButton("💾 نسخة احتياطية")
        b_bk.clicked.connect(self.do_backup)
        b_rs = PushButton("♻️ استعادة نسخة")
        b_rs.clicked.connect(self.do_restore)
        b_imp = PushButton("📥 استيراد CSV")
        b_imp.clicked.connect(self.import_drugs)
        b_exp = PushButton("📤 تصدير CSV")
        b_exp.clicked.connect(self.export_drugs)
        for b in (b_bk, b_rs, b_imp, b_exp):
            sbtns.addWidget(b)
        sbtns.addStretch(1)
        l_sec.addLayout(sbtns)
        self.lbl_backup = CaptionLabel("لم يتم عمل نسخة احتياطية بعد في هذه الجلسة.")
        l_sec.addWidget(self.lbl_backup)
        f.addWidget(c_sec)

        # Catalog Sources & Cloud Sync Card
        import catalog_sources
        catalog_sources.build_notice(f)

        c_cl = CardWidget()
        l_cl = QVBoxLayout(c_cl)
        l_cl.setContentsMargins(14, 12, 14, 12)
        l_cl.setSpacing(8)
        l_cl.addWidget(StrongBodyLabel("☁️ المزامنة السحابية (Supabase)"))
        cbtns = QHBoxLayout()
        self.btn_cloud_pull = PrimaryPushButton("⬇️ سحب الكتالوج من السحابة")
        self.btn_cloud_pull.clicked.connect(self.cloud_pull)
        self.btn_cloud_push = PushButton("⬆️ رفع كل الأصناف للسحابة")
        self.btn_cloud_push.clicked.connect(self.cloud_push_all)
        b_cref = PushButton("🔄 تحديث الحالة")
        b_cref.clicked.connect(self._cloud_refresh_label)
        cbtns.addWidget(self.btn_cloud_pull)
        cbtns.addWidget(self.btn_cloud_push)
        cbtns.addWidget(b_cref)
        cbtns.addStretch(1)
        l_cl.addLayout(cbtns)
        self.lbl_cloud = BodyLabel("")
        self.lbl_cloud.setWordWrap(True)
        l_cl.addWidget(self.lbl_cloud)
        f.addWidget(c_cl)
        self._cloud_refresh_label()

        # Updater & Automation Card
        c_up = CardWidget()
        l_up = QVBoxLayout(c_up)
        l_up.setContentsMargins(14, 12, 14, 12)
        l_up.setSpacing(8)
        l_up.addWidget(StrongBodyLabel("🔄 التحديثات والمهام التلقائية"))
        ubtns = QHBoxLayout()
        self.btn_update_check = PushButton("🔍 التحقق من التحديثات الآن")
        self.btn_update_check.clicked.connect(self.update_check_now)
        self.btn_update_apply = PrimaryPushButton("⬇️ تحميل وتثبيت التحديث")
        self.btn_update_apply.clicked.connect(self.update_apply_now)
        self.btn_update_apply.setEnabled(False)
        ubtns.addWidget(self.btn_update_check)
        ubtns.addWidget(self.btn_update_apply)
        ubtns.addStretch(1)
        l_up.addLayout(ubtns)
        self.lbl_update = CaptionLabel(self._update_status_text())
        self.lbl_update.setWordWrap(True)
        l_up.addWidget(self.lbl_update)
        self._refresh_update_ui()

        import automation
        self.chk_autosync = CheckBox("مزامنة الكتالوج من السحابة تلقائياً كل 24 ساعة")
        self.chk_autosync.setChecked(self.db.get_setting("autosync_enabled", "1") != "0")
        self.chk_autosync.stateChanged.connect(lambda _s: self._save_automation_flags())
        self.chk_autobackup = CheckBox("نسخة احتياطية تلقائية من قاعدة البيانات كل 24 ساعة")
        self.chk_autobackup.setChecked(self.db.get_setting("autobackup_enabled", "1") != "0")
        self.chk_autobackup.stateChanged.connect(lambda _s: self._save_automation_flags())
        l_up.addWidget(self.chk_autosync)
        l_up.addWidget(self.chk_autobackup)
        self.lbl_automation = CaptionLabel(automation.status_text(self.db))
        l_up.addWidget(self.lbl_automation)
        f.addWidget(c_up)

        # Audit Log Card
        c_au = CardWidget()
        l_au = QVBoxLayout(c_au)
        l_au.setContentsMargins(14, 12, 14, 12)
        l_au.setSpacing(6)
        l_au.addWidget(StrongBodyLabel("🧾 سجل التدقيق — كل ما يحدث في النظام"))
        af = QHBoxLayout()
        af.addWidget(BodyLabel("بحث:"))
        self.e_audit_filter = LineEdit()
        self.e_audit_filter.setFixedWidth(180)
        af.addWidget(self.e_audit_filter)
        af.addWidget(BodyLabel("الإجراء:"))
        self.cb_audit_action = ComboBox()
        self.cb_audit_action.setMinimumWidth(160)
        af.addWidget(self.cb_audit_action)
        af.addWidget(BodyLabel("المستخدم:"))
        self.cb_audit_user = ComboBox()
        self.cb_audit_user.setMinimumWidth(120)
        af.addWidget(self.cb_audit_user)
        b_au = PrimaryPushButton("🔍 عرض")
        b_au.clicked.connect(self.audit_refresh)
        b_au_csv = PushButton("⬇️ تصدير سجل النشاط CSV")
        b_au_csv.clicked.connect(lambda: self.export_log_csv("activity"))
        af.addWidget(b_au)
        af.addWidget(b_au_csv)
        af.addStretch(1)
        l_au.addLayout(af)
        self.lbl_audit_count = CaptionLabel("")
        l_au.addWidget(self.lbl_audit_count)
        self.txt_audit, self.txt_audit_detail = self._make_log_view(l_au, "audit")
        f.addWidget(c_au)
        self.audit_refresh()

        # System Log Card
        c_sy = CardWidget()
        l_sy = QVBoxLayout(c_sy)
        l_sy.setContentsMargins(14, 12, 14, 12)
        l_sy.setSpacing(6)
        l_sy.addWidget(StrongBodyLabel("🛠️ سجل النظام — الأخطاء والتحديثات والتشغيل"))
        sf = QHBoxLayout()
        sf.addWidget(BodyLabel("المستوى:"))
        self.cb_sys_level = ComboBox()
        self.cb_sys_level.addItems(["", "error", "warning", "info"])
        sf.addWidget(self.cb_sys_level)
        b_sy = PrimaryPushButton("🔍 عرض")
        b_sy.clicked.connect(self.system_log_refresh)
        b_sy_csv = PushButton("⬇️ تصدير سجل النظام CSV")
        b_sy_csv.clicked.connect(lambda: self.export_log_csv("system"))
        sf.addWidget(b_sy)
        sf.addWidget(b_sy_csv)
        sf.addStretch(1)
        l_sy.addLayout(sf)
        self.txt_syslog, self.txt_syslog_detail = self._make_log_view(l_sy, "sys")
        f.addWidget(c_sy)
        self.system_log_refresh()

        # Remote Monitoring Card (Owner)
        if self.is_admin:
            c_rm = CardWidget()
            l_rm = QVBoxLayout(c_rm)
            l_rm.setContentsMargins(14, 12, 14, 12)
            l_rm.setSpacing(8)
            l_rm.addWidget(StrongBodyLabel("📡 المتابعة عن بعد (للمالك فقط)"))
            self.lbl_remote = BodyLabel("")
            self.lbl_remote.setWordWrap(True)
            l_rm.addWidget(self.lbl_remote)
            rf = QHBoxLayout()
            rf.addWidget(BodyLabel("مستوى التفاصيل:"))
            self.cb_remote_level = ComboBox()
            self.cb_remote_level.addItems(["summary", "full"])
            rf.addWidget(self.cb_remote_level)
            b_rp = PushButton("👁️ اعرض ما سيُرسل ووجهته")
            b_rp.clicked.connect(self.remote_preview)
            b_re = PrimaryPushButton("✅ تفعيل")
            b_re.clicked.connect(self.remote_enable)
            b_rd = PushButton("⛔ إيقاف")
            b_rd.clicked.connect(self.remote_disable)
            for b in (b_rp, b_re, b_rd):
                rf.addWidget(b)
            rf.addStretch(1)
            l_rm.addLayout(rf)
            f.addWidget(c_rm)
            self.remote_refresh()

    def save_pharmacy_name(self):
        self.db.set_setting("pharmacy_name", self.e_pharmacy.text().strip())
        self.db.set_setting("pharmacy_phone", self.e_pharmacy_phone.text().strip())
        self.db.conn.commit()
        self.update_topbar()
        messagebox.showinfo("تم", "تم حفظ اسم وتليفون الصيدلية", parent=self)

    def save_printer_settings(self):
        if receipt_printer is None:
            messagebox.showerror("خطأ", "ملف printer.py غير موجود", parent=self)
            return
        try:
            cp864 = int(self.e_cp864.text().strip() or "37")
            cp1256 = int(self.e_cp1256.text().strip() or "50")
            if not (0 <= cp864 <= 255 and 0 <= cp1256 <= 255):
                raise ValueError
        except ValueError:
            messagebox.showerror("خطأ", "رقم صفحة الترميز يجب أن يكون عدداً بين 0 و 255", parent=self)
            return
        self.db.set_setting(receipt_printer.SETTING_PRINTER_TYPE, self._pr_type)
        self.db.set_setting(receipt_printer.SETTING_PRINTER_NAME, self.cb_printer_name.text().strip())
        self.db.set_setting(receipt_printer.SETTING_PRINTER_WIDTH, self.cb_printer_width.currentText())
        self.db.set_setting(receipt_printer.SETTING_PRINTER_KICK, "1" if self.chk_printer_kick.isChecked() else "0")
        self.db.set_setting(receipt_printer.SETTING_CP864_PAGE, str(cp864))
        self.db.set_setting(receipt_printer.SETTING_CP1256_PAGE, str(cp1256))
        messagebox.showinfo("تم", "تم حفظ إعدادات الطباعة", parent=self)

    def change_password_dialog(self):
        win = QDialog(self)
        win.setWindowTitle("تغيير كلمة المرور")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        lay = QVBoxLayout(win)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)
        ents = {}
        for key, lbl in [
            ("current", "كلمة المرور الحالية"),
            ("new", "كلمة المرور الجديدة (8 أحرف على الأقل)"),
            ("confirm", "تأكيد كلمة المرور الجديدة"),
        ]:
            lay.addWidget(CaptionLabel(lbl))
            e = PasswordLineEdit()
            lay.addWidget(e)
            ents[key] = e

        def save():
            from database import _verify_password
            row = self.db.conn.execute("SELECT password_hash FROM users WHERE username=?", (self.username,)).fetchone()
            if not row or not _verify_password(ents["current"].text(), row["password_hash"]):
                messagebox.showerror("خطأ", "كلمة المرور الحالية غير صحيحة", parent=win)
                return
            new = ents["new"].text()
            if len(new) < 8:
                messagebox.showerror("خطأ", "كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل", parent=win)
                return
            if new != ents["confirm"].text():
                messagebox.showerror("خطأ", "تأكيد كلمة المرور لا يطابق كلمة المرور الجديدة", parent=win)
                return
            self.db.change_password(self.username, new)
            self.db.audit(self.username, "change_password", "")
            win.accept()
            messagebox.showinfo("تم", "تم تغيير كلمة المرور", parent=self)

        b = PrimaryPushButton("💾 تغيير كلمة المرور")
        b.clicked.connect(save)
        lay.addWidget(b)
        ui_theme.fit_dialog_widget(win, 420, 320)
        win.exec()

    def add_user_dialog(self):
        win = QDialog(self)
        win.setWindowTitle("مستخدم جديد")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        lay = QVBoxLayout(win)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)
        ents = {}
        for key, lbl in [("username", "اسم المستخدم"), ("password", "كلمة المرور"), ("full", "الاسم الكامل")]:
            lay.addWidget(CaptionLabel(lbl))
            e = PasswordLineEdit() if key == "password" else LineEdit()
            lay.addWidget(e)
            ents[key] = e

        lay.addWidget(CaptionLabel("الدور:"))
        role_state = {"role": "cashier"}
        rgrp = QButtonGroup(win)
        rrow = QHBoxLayout()
        for val, lbl_txt in (("cashier", "موظف"), ("admin", "مدير")):
            rb = RadioButton(lbl_txt)
            if val == "cashier":
                rb.setChecked(True)
            rb.toggled.connect(lambda c, v=val: role_state.__setitem__("role", v) if c else None)
            rgrp.addButton(rb)
            rrow.addWidget(rb)
        rrow.addStretch(1)
        lay.addLayout(rrow)

        lay.addWidget(CaptionLabel("الفرع:"))
        _branches = self.db.list_branches(active_only=True)
        cb_branch = ComboBox()
        cb_branch.addItems(["— بدون فرع —"] + [b["name"] for b in _branches])
        lay.addWidget(cb_branch)

        def save():
            if not ents["username"].text().strip() or len(ents["password"].text()) < 8:
                messagebox.showerror("خطأ", "أدخل اسم مستخدم وكلمة مرور 8 أحرف على الأقل", parent=win)
                return
            try:
                bid = _branches[cb_branch.currentIndex() - 1]["id"] if cb_branch.currentIndex() > 0 else None
                self.db.create_user(ents["username"].text().strip(), ents["password"].text(), role_state["role"], ents["full"].text().strip(), bid)
            except Exception as e:
                messagebox.showerror("خطأ", "اسم المستخدم موجود بالفعل: %s" % e, parent=win)
                return
            win.accept()
            messagebox.showinfo("تم", "تمت إضافة المستخدم", parent=self)

        b = PrimaryPushButton("حفظ")
        b.clicked.connect(save)
        lay.addWidget(b)
        ui_theme.fit_dialog_widget(win, 400, 380)
        win.exec()

    def do_backup(self):
        if not self.is_admin:
            messagebox.showerror("صلاحيات", "النسخ الاحتياطي للمدير فقط", parent=self)
            return
        try:
            dest = self.db.backup()
        except Exception as e:
            messagebox.showerror("خطأ في النسخ الاحتياطية", "تعذر حفظ النسخة الاحتياطية: %s" % e, parent=self)
            return
        if hasattr(self, "lbl_backup"):
            self.lbl_backup.setText("آخر نسخة احتياطية: %s" % dest)
        self.db.audit(self.username, "backup", dest)
        self.db.syslog("info", "desktop", "backup_ok", os.path.basename(dest))
        messagebox.showinfo("تم", "تم حفظ نسخة احتياطية (تم التحقق من سلامتها) في:\n%s" % dest, parent=self)
        self.show_banner("💾 تم حفظ نسخة احتياطية: %s" % dest, "success")

    def do_restore(self):
        if not self.is_admin:
            messagebox.showerror("صلاحيات", "استعادة نسخة احتياطية صلاحية المدير فقط", parent=self)
            return
        path = messagebox.get_open_filename(parent=self, title="اختر ملف النسخة الاحتياطية", filetypes=[("SQLite DB", "*.db"), ("كل الملفات", "*.*")])
        if not path:
            return
        if not DB.verify_backup(path):
            messagebox.showerror("خطأ", "هذا الملف ليس نسخة احتياطية صالحة — لم يتغير شيء", parent=self)
            return
        if not messagebox.askyesno(
            "استعادة نسخة احتياطية",
            "سيتم استبدال قاعدة البيانات الحالية بهذه النسخة.\n"
            "النسخة الحالية ستُحفظ جانباً باسم pharmacy.db.before-restore.\nهل أنت متأكد؟",
            parent=self,
        ):
            return
        try:
            if getattr(self, "mobile_server", None) is not None:
                try:
                    self.mobile_server.stop()
                except Exception:
                    pass
                self.mobile_server = None
            self.db.close()
            db_path = self.db.path
            keep = os.path.join(BASE, "pharmacy.db.before-restore")
            for suffix in ("", "-wal", "-shm"):
                p = db_path + suffix
                if os.path.exists(p):
                    try:
                        os.rename(p, keep + suffix)
                    except Exception:
                        pass
            shutil.copyfile(path, db_path)
            self.db = DB(path=db_path)
            self.db.set_actor(self.username, "desktop")
            _rb, _ru = self.db.scope_for_user(self.username)
            self.db.set_scope(_rb, _ru)
            self.db.audit(self.username, "restore", "restored from %s" % path)
            self.db.syslog("warning", "desktop", "restore_done", "database replaced from %s" % os.path.basename(path))
            messagebox.showinfo("تم", "تمت الاستعادة من:\n%s\nأعد تشغيل البرنامج لتحديث كل الشاشات." % path, parent=self)
            self.show_banner("✅ تمت استعادة النسخة الاحتياطية — أعد تشغيل البرنامج", "success")
        except Exception as e:
            messagebox.showerror("خطأ", "فشلت الاستعادة: %s\nراجع ملف error.log" % e, parent=self)

    def import_drugs(self):
        path = messagebox.get_open_filename(parent=self, filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            added, updated = self.db.import_drugs_csv(path, self.username)
        except Exception as e:
            messagebox.showerror("خطأ في الاستيراد", str(e), parent=self)
            return
        messagebox.showinfo("تم", "تم الاستيراد: %d صنف جديد، %d موجود بالفعل." % (added, updated), parent=self)
        self.inv_refresh()
        self.pos_search_refresh()

    def _cloud_status_text(self):
        try:
            import cloud_sync
            st = cloud_sync.status(self.db)
        except Exception as e:
            return "المزامنة السحابية غير متاحة: %s" % e
        if not st.get("configured"):
            return (
                "المزامنة غير مفعّلة بعد. للتفعيل: انسخ الملف supabase_config.example.json "
                "إلى supabase_config.json بجوار البرنامج واكتب فيه رابط المشروع والمفتاح."
            )
        parts = ["المزامنة مفعّلة — أي صنف جديد أو معدّل يُرفع للسحابة تلقائياً."]
        parts.append("فواتير الهاتف السحابية: تُسحب وتُسجَّل تلقائياً كل 15 ثانية عند توفر الإنترنت.")
        for key, label in (
            ("orders_last", "آخر فاتورة سحابية: "),
            ("orders_error", "آخر خطأ في الفواتير السحابية: "),
            ("last_pull", "آخر سحب: "),
            ("last_push", "آخر رفع: "),
            ("last_error", "آخر خطأ: "),
        ):
            if st.get(key):
                parts.append(label + str(st[key]))
        return "\n".join(parts)

    def _cloud_refresh_label(self):
        if not hasattr(self, "lbl_cloud"):
            return
        txt = self._cloud_status_text()
        if "آخر خطأ" in txt or "غير متاحة" in txt:
            colour = self.pal["danger"]
        elif "غير مفعّلة" in txt:
            colour = self.pal["warning"]
        elif "المزامنة مفعّلة" in txt:
            colour = self.pal["success"]
        else:
            colour = self.pal["muted"]
        self.lbl_cloud.setText(txt)
        self.lbl_cloud.setStyleSheet(f"color: {colour};")

    def cloud_pull(self):
        import cloud_sync
        import supabase_client
        if not supabase_client.is_configured():
            messagebox.showerror("المزامنة السحابية", "إعداد Supabase غير موجود.", parent=self)
            return
        if not messagebox.askyesno("سحب الكتالوج من السحابة", "سيُسحب كل المنتجات من السحابة وتحدّث بياناتها وأسعارها محلياً. متابعة؟", parent=self):
            return
        self.btn_cloud_pull.setEnabled(False)
        self.show_banner("⏳ جاري سحب الكتالوج من السحابة...", "info")
        db_path = self.db.path
        username = self.username

        def work():
            db = DB(path=db_path, init=False)
            try:
                return cloud_sync.pull_catalog(db, username)
            finally:
                db.close()

        def done(result, error):
            def ui():
                self.btn_cloud_pull.setEnabled(True)
                self._cloud_refresh_label()
                if error is not None:
                    self.db.syslog("error", "cloud_sync", "pull_failed", str(error)[:300])
                    messagebox.showerror("خطأ في المزامنة", str(error), parent=self)
                    return
                added, updated, skipped = result
                self.show_banner("✅ اكتمل السحب من السحابة", "success")
                messagebox.showinfo("تم", "اكتمل السحب: %d جديد، %d محدّث، %d متجاهَل" % (added, updated, skipped), parent=self)
                self.inv_refresh()
                self.pos_search_refresh()
            self._ui_post(ui)

        cloud_sync.run_in_background(work, done)

    def cloud_push_all(self):
        import cloud_sync
        import supabase_client
        if not supabase_client.is_configured():
            messagebox.showerror("المزامنة السحابية", "إعداد Supabase غير موجود.", parent=self)
            return
        if not messagebox.askyesno("رفع الأصناف للسحابة", "سيُرفع كل الأصناف المحلية إلى السحابة وتحدّث أسعارها هناك. متابعة؟", parent=self):
            return
        self.btn_cloud_push.setEnabled(False)
        self.show_banner("⏳ جاري رفع الأصناف للسحابة...", "info")
        db_path = self.db.path

        def work():
            db = DB(path=db_path, init=False)
            try:
                return cloud_sync.push_all(db)
            finally:
                db.close()

        def done(result, error):
            def ui():
                self.btn_cloud_push.setEnabled(True)
                self._cloud_refresh_label()
                if error is not None:
                    self.db.syslog("error", "cloud_sync", "push_failed", str(error)[:300])
                    messagebox.showerror("خطأ في المزامنة", str(error), parent=self)
                    return
                sent, failed = result
                self.show_banner("✅ اكتمل الرفع للسحابة", "success")
                messagebox.showinfo("تم", "اكتمل الرفع: %d صنف، فشل %d" % (sent, failed), parent=self)
            self._ui_post(ui)

        cloud_sync.run_in_background(work, done)

    def _save_automation_flags(self):
        self.db.set_setting("autosync_enabled", "1" if self.chk_autosync.isChecked() else "0")
        self.db.set_setting("autobackup_enabled", "1" if self.chk_autobackup.isChecked() else "0")
        self._refresh_automation_status()

    def _refresh_automation_status(self):
        import automation
        if hasattr(self, "lbl_automation"):
            self.lbl_automation.setText(automation.status_text(self.db))

    def _update_status_text(self):
        try:
            import updater
            return updater.status_text(self.db)
        except Exception as e:
            return "فحص التحديثات غير متاح: %s" % e

    def _refresh_update_ui(self, result=None):
        if hasattr(self, "lbl_update"):
            self.lbl_update.setText(self._update_status_text())
        if result and result.get("status") == "update_available":
            self._pending_update = dict(result["latest"])
            self._pending_update["unverified_install"] = result.get("unverified_install", False)
        elif result and result.get("status") == "up_to_date":
            self._pending_update = None
        available = bool(getattr(self, "_pending_update", None)) and not getattr(self, "_update_installing", False) and not getattr(self, "_update_restart_required", False)
        if hasattr(self, "btn_update_apply"):
            self.btn_update_apply.setEnabled(available)

    def _startup_update_check(self):
        import updater
        if hasattr(self, "_update_qtimer"):
            self._update_qtimer.start(updater.CHECK_INTERVAL_MS)
        self._run_update_check(manual=False)

    def update_check_now(self):
        self._run_update_check(manual=True)

    def _run_update_check(self, manual=False):
        import cloud_sync
        import updater
        if getattr(self, "_update_check_busy", False) or getattr(self, "_update_installing", False) or getattr(self, "_update_restart_required", False):
            return
        self._update_check_busy = True
        if hasattr(self, "btn_update_check"):
            self.btn_update_check.setEnabled(False)
        db_path = self.db.path

        def work():
            db = DB(path=db_path, init=False)
            try:
                return updater.check_for_update(db)
            finally:
                db.close()

        def done(result, error):
            def ui():
                self._update_check_busy = False
                if hasattr(self, "btn_update_check"):
                    self.btn_update_check.setEnabled(True)
                self._refresh_update_ui(result)
                if error is not None or not result or result.get("status") == "error":
                    if manual:
                        messagebox.showerror("فحص التحديثات", str(error or (result or {}).get("error", "تعذر الفحص")), parent=self)
                    return
                if result.get("status") == "update_available":
                    if manual or updater.notification_due(self.db, result):
                        self._show_update_notice(result)
                elif manual:
                    messagebox.showinfo("التحديثات", "النسخة المسجلة تطابق آخر كود على main", parent=self)
            self._ui_post(ui)

        cloud_sync.run_in_background(work, done)

    def _show_update_notice(self, result):
        import updater
        existing = getattr(self, "_update_notice", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            return
        latest = dict(result["latest"])
        latest["unverified_install"] = result.get("unverified_install", False)
        self._pending_update = latest

        win = QDialog(self)
        self._update_notice = win
        win.setWindowTitle("تحديث البرنامج")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 540, 290)
        lay = QVBoxLayout(win)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        title = "تحديث متاح للبرنامج" if not latest["unverified_install"] else "تحقق من نسخة البرنامج"
        lay.addWidget(SubtitleLabel(title))
        lines = (
            ["لا يمكن تحديد نسخة التثبيت الحالية.", "يمكنك تنزيل آخر كود من main باختيارك."]
            if latest["unverified_install"]
            else ["يوجد كود أحدث على فرع main جاهز للتنزيل."]
        )
        lines += ["لن يثبت أي تحديث دون موافقتك.", "احفظ الشغل وأوقف سيرفر الموبايل قبل التثبيت.", "لاحقاً = تذكير بعد 24 ساعة لهذا التحديث."]
        lbl = BodyLabel("\n".join(lines))
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        lay.addWidget(CaptionLabel(latest["sha"][:12]))
        lay.addStretch(1)

        btns = QHBoxLayout()
        def dismiss():
            updater.snooze_update(self.db, latest["sha"])
            win.reject()
            self._update_notice = None

        def install():
            self._pending_update = latest
            win.accept()
            self._update_notice = None
            self.update_apply_now()

        b_inst = PrimaryPushButton("تحميل وتثبيت الآن")
        b_inst.clicked.connect(install)
        b_lat = PushButton("لاحقاً: 24 ساعة")
        b_lat.clicked.connect(dismiss)
        btns.addWidget(b_inst)
        btns.addWidget(b_lat)
        btns.addStretch(1)
        lay.addLayout(btns)
        win.show()

    def update_apply_now(self):
        import cloud_sync
        import updater
        if getattr(self, "_update_installing", False) or getattr(self, "_update_restart_required", False):
            return
        if not getattr(self, "_pending_update", None):
            messagebox.showinfo("لا يوجد تحديث", "افحص التحديثات أولاً — لا يوجد تحديث معلّق.", parent=self)
            return
        latest = dict(self._pending_update)
        if getattr(self, "cart", []) or getattr(self, "purchase_lines", []):
            messagebox.showinfo("احفظ العمل أولاً", "احفظ أو امسح سلة البيع ومسودة المشتريات قبل التثبيت", parent=self)
            return
        server = getattr(self, "mobile_server", None)
        if server is not None and server.running:
            messagebox.showinfo("أوقف سيرفر الموبايل", "أكمل فواتير الهواتف وأوقف سيرفر الموبايل قبل التثبيت", parent=self)
            return
        if not self.is_admin:
            messagebox.showinfo("تحديث البرنامج", "اطلب من المدير تثبيت التحديث من حسابه", parent=self)
            return
        if not messagebox.askyesno(
            "تثبيت التحديث",
            "سيُنزَّل آخر كود من GitHub ويُثبَّت فوق مجلد البرنامج.\n"
            "قاعدة البيانات والإعدادات والنسخ الاحتياطية لن تتأثر. متابعة؟",
            parent=self,
        ):
            return
        self._update_installing = True
        if hasattr(self, "btn_update_apply"):
            self.btn_update_apply.setEnabled(False)
        self.show_banner("⏳ جاري تنزيل التحديث وتثبيته...", "info")
        db_path = self.db.path
        base_dir = BASE
        sha = latest["sha"]

        def work():
            db = DB(path=db_path, init=False)
            try:
                return updater.apply_update(db, base_dir, sha)
            finally:
                db.close()

        def done(result, error):
            def ui():
                self._update_installing = False
                if error is None:
                    self._pending_update = None
                    self._update_restart_required = True
                self._refresh_update_ui({"status": "up_to_date"} if error is None else None)
                if error is not None:
                    self.db.syslog("error", "updater", "update_failed", str(error))
                    self.show_banner("❌ فشل تثبيت التحديث", "error")
                    messagebox.showerror("فشل التحديث", str(error), parent=self)
                    return
                updated, _rollback = result
                self.show_banner("✅ تم تثبيت التحديث — أعد تشغيل البرنامج", "success")
                messagebox.showinfo("تم التحديث", "تم تثبيت التحديث (%d ملف).\nأغلق البرنامج وشغّله من جديد." % updated, parent=self)
            self._ui_post(ui)

        cloud_sync.run_in_background(work, done)

    def _make_log_view(self, parent_lay, kind):
        lst = QListWidget()
        lst.setWordWrap(True)
        lst.setMinimumHeight(200)
        parent_lay.addWidget(lst)
        parent_lay.addWidget(CaptionLabel("تفاصيل السطر المحدد (اضغط على أي سطر):"))
        det = TextEdit()
        det.setReadOnly(True)
        det.setFont(ui_theme.qfont(10, family="Consolas"))
        det.setFixedHeight(150)
        parent_lay.addWidget(det)
        lst.currentRowChanged.connect(lambda idx, k=kind: self._log_line_click(k, idx))
        return lst, det

    def _log_line_click(self, kind, idx):
        rows = getattr(self, "_audit_rows" if kind == "audit" else "_sys_rows", [])
        det = self.txt_audit_detail if kind == "audit" else self.txt_syslog_detail
        if idx < 0 or idx >= len(rows):
            return
        row = rows[idx]
        _bn = {b["id"]: b["name"] for b in self.db.list_branches()}
        lines = []
        for k, v in row.items():
            if v in (None, ""):
                continue
            if k == "branch_id":
                v = "%s (%s)" % (_bn.get(v, v), v)
            lines.append("%s: %s" % (k, v))
        det.setPlainText("\n".join(lines))

    def remote_refresh(self):
        try:
            import remote_monitor
            self.lbl_remote.setText(remote_monitor.status_text(self.db))
            if remote_monitor.is_enabled(self.db):
                self.cb_remote_level.setCurrentText(remote_monitor.level(self.db))
        except Exception:
            pass

    def _remote_preview_text(self):
        import remote_monitor
        lvl = self.cb_remote_level.currentText() or "summary"
        pv = remote_monitor.preview(self.db, lvl)
        head = "الوجهة: %s\nالمستوى: %s\nلن يُرسل أي سجل قديم، فقط ما يُسجَّل بعد التفعيل.\n" % (pv["destination"] or "غير مُعدّة", lvl)
        if lvl == "summary":
            head += "ملخص: المستخدم والدور والإجراء والفرع والوقت، بدون تفاصيل الأسعار أو العملاء أو قبل/بعد.\n"
        else:
            head += "كامل: يشمل التفاصيل وقبل/بعد. لا كلمات سر ولا مفاتيح أبداً.\n"
        return pv, head + "\nأمثلة مما سيُرسل:\n" + _json.dumps(pv["sample"], ensure_ascii=False, indent=1)[:1800]

    def remote_preview(self):
        try:
            pv, txt = self._remote_preview_text()
        except Exception as e:
            messagebox.showerror("المتابعة عن بعد", str(e), parent=self)
            return
        if not pv["configured"]:
            txt = "لم يتم إعداد remote_monitor.json بعد، فلن يُرسل شيء.\n\n" + txt
        messagebox.showinfo("ما الذي سيُرسل", txt, parent=self)

    def remote_enable(self):
        import remote_monitor
        if remote_monitor.load_config() is None:
            messagebox.showerror("المتابعة عن بعد", "ملف remote_monitor.json غير موجود أو ناقص.", parent=self)
            return
        _pv, txt = self._remote_preview_text()
        if not messagebox.askyesno("تفعيل المتابعة عن بعد", txt + "\n\nتفعيل الإرسال التلقائي من الآن؟", parent=self):
            return
        remote_monitor.enable(self.db, self.cb_remote_level.currentText() or "summary")
        self.remote_refresh()

    def remote_disable(self):
        import remote_monitor
        remote_monitor.disable(self.db)
        self.remote_refresh()

    def system_log_refresh(self):
        if not hasattr(self, "txt_syslog"):
            return
        rows = self.db.system_log_query(level=self.cb_sys_level.currentText().strip(), limit=200)
        self._sys_rows = rows
        self.txt_syslog.clear()
        for r in rows:
            txt = "%s | %s | %s/%s | %s%s" % (
                r["created_at"], r["level"], r["component"], r["event"], r["message"],
                (" | " + r["detail"].strip().splitlines()[-1][:200]) if r["detail"].strip() else "",
            )
            self.txt_syslog.addItem(QListWidgetItem(txt))
        if not rows:
            self.txt_syslog.addItem(QListWidgetItem("لا توجد أحداث نظام بعد."))

    def export_log_csv(self, kind):
        if not self.is_admin:
            messagebox.showerror("صلاحيات", "تصدير السجلات للمدير فقط", parent=self)
            return
        path = messagebox.get_save_filename(
            parent=self, initialfile="system_log.csv" if kind == "system" else "activity_log.csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        try:
            n = self.db.export_logs_csv(path, kind)
        except Exception as e:
            messagebox.showerror("خطأ", "تعذر التصدير: %s" % e, parent=self)
            return
        self.db.audit(self.username, "export_log", "%s: %d rows" % (kind, n), entity="log")
        messagebox.showinfo("تم", "تم تصدير %d سطر" % n, parent=self)

    def audit_refresh(self):
        if not hasattr(self, "txt_audit"):
            return
        try:
            actions = self.db.audit_actions()
            cur_a = self.cb_audit_action.currentText()
            self.cb_audit_action.clear()
            self.cb_audit_action.addItems([""] + actions)
            if cur_a in actions:
                self.cb_audit_action.setCurrentText(cur_a)
            users = sorted({a["user"] for a in self.db.audit_list(5000) if a["user"]})
            cur_u = self.cb_audit_user.currentText()
            self.cb_audit_user.clear()
            self.cb_audit_user.addItems([""] + users)
            if cur_u in users:
                self.cb_audit_user.setCurrentText(cur_u)
        except Exception:
            pass
        text = self.e_audit_filter.text().strip()
        action = self.cb_audit_action.currentText().strip()
        user = self.cb_audit_user.currentText().strip()
        rows = self.db.audit_query(text=text, action=action, user=user, limit=200)
        _bn = {b["id"]: b["name"] for b in self.db.list_branches()}
        self._audit_rows = rows
        self.txt_audit.clear()
        for a in rows:
            line = "%s | %s%s | %s | %s | %s" % (
                a["created_at"], a["user"], (" (%s)" % a["role"]) if a.get("role") else "",
                a.get("source") or "-", a["action"], a["details"],
            )
            if a.get("branch_id") is not None:
                line += " | فرع: %s" % _bn.get(a["branch_id"], a["branch_id"])
            if a.get("shift_id") is not None:
                line += " | وردية #%s" % a["shift_id"]
            if a.get("before_json") or a.get("after_json"):
                line += " | قبل: %s → بعد: %s" % (a.get("before_json") or "-", a.get("after_json") or "-")
            self.txt_audit.addItem(QListWidgetItem(line))
        total = self.db.audit_count()
        filters_on = bool(text or action or user)
        self.lbl_audit_count.setText(
            "يظهر %d%s من إجمالي %d حدث — يُحتفظ بالسجل سنتين." % (len(rows), " (مفلترة)" if filters_on else " (الأحدث)", total)
        )
