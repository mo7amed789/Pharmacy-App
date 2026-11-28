# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise — Windows 11 Native Desktop App (PySide6 + PySide6-Fluent-Widgets + SQLite).
Arabic-first RTL UI, Mica backdrop, Fluent NavigationView, offline-first, EGP.
"""
from datetime import datetime
import os
import shutil
import sys
import threading

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QGuiApplication
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    PushButton,
    StrongBodyLabel,
)

from app_helpers import (
    BASE,
    EGP,
    _startup_log,
    money,
    qr_url_with_pin,
    safe_float,
    safe_int,
    strict_float,
    strict_int,
)
from database import DB
import ui_dialogs
import ui_dialogs as messagebox
from ui_login import LoginWindow, force_password_change_dialog
from ui_tabs_core import CoreTabsMixin
from ui_tabs_ops import OpsTabsMixin
from ui_tabs_system import SystemTabsMixin
import ui_theme

try:
    import printer as receipt_printer
except Exception:
    receipt_printer = None


class App(CoreTabsMixin, OpsTabsMixin, SystemTabsMixin, FluentWindow):
    """Main FluentWindow application shell combining all pharmacy tabs."""

    _ui_signal = Signal(object)
    EMPLOYEE_HIDDEN_TABS = (3, 5, 7, 8)

    def __init__(self, db, user):
        self.db = db
        self.user = user
        self.username = user["username"]
        self.role = user["role"]
        self.is_admin = self.role == "admin"

        super().__init__()
        self._ui_signal.connect(self._on_ui_dispatch, Qt.QueuedConnection)

        # Fix RTL for FluentWindow internals:
        # Keep titleBar buttons on the right (they're LTR by design — keep it)
        try:
            self.titleBar.setLayoutDirection(Qt.LeftToRight)
        except Exception:
            pass

        # Branch scope
        _b, _u = db.scope_for_user(self.username)
        db.set_scope(_b, _u)
        db.set_actor(self.username, "desktop")
        try:
            import updater as _upd
            db.app_version = (_upd.local_git_sha() or db.get_setting("update_applied_sha", ""))[:12]
        except Exception:
            pass
        db.syslog("info", "desktop", "app_start", "user=%s role=%s" % (self.username, self.role))
        self._install_error_logging()

        # Theme & customization settings
        self.theme_name = ui_theme.get_theme_name(db)
        self.ui_accent = db.get_setting("ui_accent", "teal") or "teal"
        if self.ui_accent not in ui_theme.ACCENTS:
            self.ui_accent = "teal"
        self.ui_font_size = db.get_setting("ui_font_size", "normal") or "normal"
        self.ui_font_delta = ui_theme.font_scale_for(self.ui_font_size)
        self.ui_alerts_top = (db.get_setting("ui_alerts_top", "1") or "1") != "0"
        self.ui_dash_cards = db.get_setting("ui_dash_cards", "") or ""

        # NOTE: never call setLayoutDirection() on the FluentWindow itself.
        # It reverses the window's *internal* HBoxLayout (nav panel + content
        # column) and shuffles the title bar, top bar and pages around.
        # RTL comes from QApplication (ui_theme.apply_qt_theme / main()) and
        # cascades to every content widget automatically.
        self.setWindowTitle(
            "Pharmacy Enterprise v6.30 — صيدلية المؤسسة | المستخدم: %s (%s)"
            % (self.username, "مدير" if self.is_admin else "موظف")
        )
        self.pal = ui_theme.apply_qt_theme(
            QApplication.instance(), self.theme_name, self.ui_accent, self.ui_font_delta
        )
        ui_dialogs.set_theme(self.theme_name, self.ui_accent)
        self.setStyleSheet(ui_theme.window_qss(self.theme_name, self.ui_accent))
        ui_theme.setup_main_window_geometry(self, db)
        ui_theme.install_screen_fit(self)
        ui_theme.apply_win11_window_style(self, self.theme_name, self.ui_accent)

        # NavigationView appearance — scale with the screen so the panel never
        # eats the content area on small panels, and collapse to the icon rail
        # automatically when the window gets narrow.
        try:
            self.navigationInterface.setExpandWidth(ui_theme.nav_expand_width(self))
            self.navigationInterface.setCollapsible(True)
            self.navigationInterface.setMinimumExpandWidth(1100)
        except Exception:
            pass

        # State
        self._debounce_timers = {}
        self.cart = []
        self.held = []
        self.purchase_lines = []
        self.current_shift = self.db.open_shift_for(self.username)
        self.mobile_server = None
        self._live_last_sale_id = 0
        self._live_last_pending = -1
        self._live_last_ok = False
        self._live_last_server_running = None
        self._qr_drawn_url = None
        self._qr_drawn_running = None
        self._pending_update = None
        self._update_check_busy = False
        self._update_installing = False
        self._update_restart_required = False
        self._update_notice = None

        # Top header bar + Status strip docked cleanly above stackedWidget
        self._build_topbar()

        # Register tabs in Fluent NavigationView (lazy build for tabs 1..9)
        self._tab_built = {}
        self._tab_builders = {}
        self._tab_widgets = {}
        tab_specs = [
            (0, FluentIcon.HOME, "🏠 الرئيسية", self.build_dashboard, NavigationItemPosition.TOP),
            (1, FluentIcon.SHOPPING_CART, "🛒 الكاشير (POS)", self.build_pos, NavigationItemPosition.TOP),
            (2, FluentIcon.MARKET, "📦 المخزون", self.build_inventory, NavigationItemPosition.TOP),
            (3, FluentIcon.DOCUMENT, "🧾 المشتريات والموردين", self.build_purchases, NavigationItemPosition.TOP),
            (4, FluentIcon.PEOPLE, "👥 العملاء", self.build_customers, NavigationItemPosition.TOP),
            (5, FluentIcon.PIE_SINGLE, "📊 التقارير", self.build_reports, NavigationItemPosition.TOP),
            (6, FluentIcon.DATE_TIME, "💰 الخزنة والورديات", self.build_cash, NavigationItemPosition.TOP),
            (8, FluentIcon.ROBOT, "🤖 التنبؤ الذكي", self.build_ai, NavigationItemPosition.TOP),
            (9, FluentIcon.PHONE, "📱 الموبايل والطباعة", self.build_mobile, NavigationItemPosition.TOP),
            (7, FluentIcon.SETTING, "⚙️ الإعدادات", self.build_settings, NavigationItemPosition.BOTTOM),
        ]
        hidden = set(self.hidden_tabs())
        for idx, icon, title, builder, pos in tab_specs:
            page = QWidget()
            page.setObjectName("tab_%d" % idx)
            self._tab_widgets[idx] = page
            self._tab_builders[idx] = builder
            if idx not in hidden:
                self.addSubInterface(page, icon, title, position=pos)

        # Build Dashboard immediately for crisp first paint
        self.build_dashboard(self._tab_widgets[0])
        self._tab_built[0] = True
        self.stackedWidget.currentChanged.connect(self._on_tab_changed)

        # The navigation panel reports its full stack height as a hard minimum,
        # which would push the window past short screens. It scrolls on its own,
        # so let it shrink instead.
        try:
            self.navigationInterface.setMinimumHeight(0)
        except Exception:
            pass

        # Shortcuts
        QShortcut(QKeySequence("F1"), self, activated=self.show_shortcuts)
        QShortcut(QKeySequence("F2"), self, activated=self.goto_pos)
        QShortcut(QKeySequence("F9"), self, activated=self._f9_complete_sale)

        # 3s live poll QTimer
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(3000)
        self._live_timer.timeout.connect(self._safe_live_tick)
        self._live_timer.start()

        self.update_topbar()
        self.refresh_dashboard()
        self.db.audit(self.username, "login", "role=%s" % self.role)

        # Background services
        self._update_qtimer = QTimer(self)
        self._update_qtimer.setSingleShot(True)
        self._update_qtimer.timeout.connect(self._startup_update_check)
        self._update_qtimer.start(3000)

        try:
            import cloud_sync
            self._cloud_orders_thread = cloud_sync.start_order_polling(self.db.path)
        except Exception:
            self._cloud_orders_thread = None

        import automation
        self._automation = automation.Automation(self.db.path)
        self._automation.start()

        try:
            import remote_monitor
            self._remote_monitor = remote_monitor.Monitor(
                self.db.path, version=getattr(self.db, "app_version", "")
            )
            self._remote_monitor.start()
        except Exception:
            self._remote_monitor = None

    # ---------- Topbar & Status Banner ----------
    def _build_topbar(self):
        self.topbar = CardWidget(self)
        lay = QHBoxLayout(self.topbar)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)
        # Keep topbar layout LTR: brand on left, action buttons on right.
        # The FluentWindow is RTL so we explicitly reset to LTR here to
        # prevent the double-reversal that would mirror the entire bar.
        self.topbar.setLayoutDirection(Qt.LeftToRight)

        brand = StrongBodyLabel("💊 Pharmacy Enterprise")
        brand.setStyleSheet(f"color: {self.pal['accent']};")
        self._lbl_brand = brand
        lay.addWidget(brand)

        self.lbl_top_pharmacy = StrongBodyLabel("")
        self.lbl_top_user = BodyLabel("")
        self.lbl_top_shift = StrongBodyLabel("")
        lay.addWidget(self.lbl_top_pharmacy)
        lay.addWidget(self.lbl_top_user)
        lay.addWidget(self.lbl_top_shift)
        lay.addStretch(1)

        if not self.is_admin:
            b_pw = PushButton("🔑 كلمتي")
            b_pw.clicked.connect(self.change_password_dialog)
            lay.addWidget(b_pw)

        b_att = PushButton("🕒 الحضور")
        b_att.clicked.connect(self.attendance_dialog)
        lay.addWidget(b_att)

        self._build_branch_selector(lay)

        self.btn_theme = PushButton("🌙 داكن" if self.theme_name == "light" else "☀️ فاتح")
        self.btn_theme.clicked.connect(self.toggle_theme)
        lay.addWidget(self.btn_theme)

        b_help = PushButton("❓ (F1)")
        b_help.clicked.connect(self.show_shortcuts)
        lay.addWidget(b_help)
        self.btn_help = b_help


        # Compact Fluent status strip right under the top bar
        self._banner_wrap = QWidget(self)
        bl = QHBoxLayout(self._banner_wrap)
        bl.setContentsMargins(16, 4, 16, 4)
        bl.setDirection(QHBoxLayout.RightToLeft)
        self.banner = QLabel("جاهز — اختر تبويباً أو ابدأ البيع من الكاشير.")
        self.banner.setFont(ui_theme.qfont(10, bold=True))
        self.banner.setWordWrap(True)
        self.banner.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bl.addWidget(self.banner, 1)

        # FluentWindow.widgetLayout is a *horizontal* layout that only holds
        # stackedWidget, so inserting rows into it lays them out side-by-side
        # as vertical strips (squashed content, top bar on the wrong edge).
        # Build a real vertical column instead: top bar, banner, pages.
        self.widgetLayout.removeWidget(self.stackedWidget)
        self.contentLayout = QVBoxLayout()
        self.contentLayout.setContentsMargins(0, 0, 0, 0)
        self.contentLayout.setSpacing(0)
        self.contentLayout.addWidget(self.topbar, 0)
        self.contentLayout.addWidget(self._banner_wrap, 0)
        self.contentLayout.addWidget(self.stackedWidget, 1)
        self.widgetLayout.addLayout(self.contentLayout, 1)

        self.show_banner("جاهز — اختر تبويباً أو ابدأ البيع من الكاشير.", "info")
        self._topbar_compact(self.width())

    def _topbar_compact(self, width):
        """Drop low-priority top-bar items on narrow windows so the bar never
        forces the window wider than the screen."""
        wide = width >= 1180
        mid = width >= 980
        for widget, visible in (
            (getattr(self, "_lbl_brand", None), wide),
            (getattr(self, "lbl_top_pharmacy", None), mid),
            (getattr(self, "lbl_top_user", None), mid),
            (getattr(self, "lbl_top_shift", None), wide),
            (getattr(self, "btn_help", None), mid),
        ):
            if widget is not None:
                widget.setVisible(visible)
        try:
            self.cb_branch.setMaximumWidth(200 if wide else 130)
        except Exception:
            pass

    def _build_branch_selector(self, lay):
        branches = self.db.list_branches(active_only=True)
        self._branch_by_label = {}
        if not branches:
            return
        if self.is_admin:
            labels = ["كل الفروع"] + [b["name"] for b in branches]
            for b in branches:
                self._branch_by_label[b["name"]] = b["id"]
            self.cb_branch = ComboBox()
            self.cb_branch.addItems(labels)
            self.cb_branch.currentIndexChanged.connect(self._on_branch_selected)
            lay.addWidget(self.cb_branch)
        else:
            name = next((b["name"] for b in branches if b["id"] == self.db.scope_branch), "بدون فرع")
            lay.addWidget(BodyLabel("🏬 " + name))

    def _on_branch_selected(self, _idx=0):
        label = self.cb_branch.currentText()
        bid = self._branch_by_label.get(label)
        self.db.set_scope(bid, None)
        for fn in ("refresh_dashboard", "cash_refresh", "inv_refresh", "refresh_pos_totals"):
            try:
                getattr(self, fn)()
            except Exception:
                pass
        self.show_banner("العرض الآن: " + label, "info")

    def show_banner(self, text, kind="info"):
        self._banner_kind = kind
        fg, bg = ui_theme.status_colors(kind, self.theme_name, self.ui_accent)
        if hasattr(self, "banner"):
            self.banner.setText(str(text))
            self.banner.setStyleSheet(f"color: {fg}; background: transparent;")
        if hasattr(self, "_banner_wrap"):
            self._banner_wrap.setStyleSheet(
                f"background-color: {bg}; border-bottom: 1px solid {ui_theme.palette(self.theme_name, self.ui_accent)['border']};"
            )
        if kind in ("success", "error"):
            try:
                fn = InfoBar.success if kind == "success" else InfoBar.error
                fn(
                    title="",
                    content=str(text),
                    isClosable=True,
                    duration=2500,
                    position=InfoBarPosition.TOP_RIGHT,
                    parent=self,
                )
            except Exception:
                pass

    def update_topbar(self):
        try:
            row = self.db.conn.execute("SELECT value FROM settings WHERE key='pharmacy_name'").fetchone()
            name = row["value"] if row else "صيدلية المؤسسة"
            self.lbl_top_pharmacy.setText("|  %s" % name)
            self.lbl_top_user.setText("👤 %s (%s)" % (self.username, "مدير" if self.is_admin else "موظف"))
            if getattr(self, "current_shift", None):
                self.lbl_top_shift.setText("🟢 وردية #%d مفتوحة" % self.current_shift["id"])
                self.lbl_top_shift.setStyleSheet(f"color: {self.pal['success']};")
            else:
                self.lbl_top_shift.setText("🔴 لا توجد وردية مفتوحة")
                self.lbl_top_shift.setStyleSheet(f"color: {self.pal['warning']};")
        except Exception:
            pass

    # ---------- Thread-safe Dispatcher & Debounce ----------
    def _ui_post(self, fn):
        try:
            self._ui_signal.emit(fn)
        except Exception:
            pass

    def _on_ui_dispatch(self, fn):
        try:
            fn()
        except Exception:
            pass

    def _debounce(self, key, ms, fn):
        prev = self._debounce_timers.get(key)
        if prev is not None:
            prev.stop()
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(fn)
        self._debounce_timers[key] = t
        t.start(ms)

    # ---------- Theme & Customization ----------
    def toggle_theme(self):
        self.apply_theme_now("dark" if self.theme_name == "light" else "light")

    def apply_theme_now(self, theme_name, accent=None, font_scale=None):
        self.theme_name = theme_name
        if accent is not None:
            self.ui_accent = accent if accent in ui_theme.ACCENTS else "teal"
            self.db.set_setting("ui_accent", self.ui_accent)
        if font_scale is not None:
            self.ui_font_delta = int(font_scale)
            self.ui_font_size = {0: "normal", 2: "large", 4: "xlarge"}.get(self.ui_font_delta, "normal")
            self.db.set_setting("ui_font_size", self.ui_font_size)
        ui_theme.set_theme_name(self.db, theme_name)
        self.pal = ui_theme.apply_qt_theme(
            QApplication.instance(), theme_name, self.ui_accent, self.ui_font_delta
        )
        ui_dialogs.set_theme(theme_name, self.ui_accent)
        self.setStyleSheet(ui_theme.window_qss(theme_name, self.ui_accent))
        ui_theme.apply_win11_window_style(self, theme_name, self.ui_accent)

        if hasattr(self, "btn_theme"):
            self.btn_theme.setText("🌙 داكن" if theme_name == "light" else "☀️ فاتح")
        if hasattr(self, "_lbl_brand"):
            self._lbl_brand.setStyleSheet(f"color: {self.pal['accent']};")
        for group in ("dash_cards", "rep_cards", "ai_cards"):
            for card in getattr(self, group, {}).values():
                card.recolor(theme_name, self.ui_accent)
        self.show_banner(self.banner.text(), getattr(self, "_banner_kind", "info"))
        self.refresh_dashboard()
        try:
            self.inv_refresh()
        except Exception:
            pass
        self.show_banner("تم تطبيق المظهر %s ✅" % ("الداكن" if theme_name == "dark" else "الفاتح"), "success")

    def apply_customization(self, accent, font_size_name, dash_cards, alerts_top):
        delta = ui_theme.font_scale_for(font_size_name)
        self.apply_theme_now(self.theme_name, accent=accent, font_scale=delta)
        self.ui_dash_cards = ",".join(dash_cards)
        self.db.set_setting("ui_dash_cards", self.ui_dash_cards)
        self.ui_alerts_top = bool(alerts_top)
        self.db.set_setting("ui_alerts_top", "1" if alerts_top else "0")
        self._apply_dash_cards_visibility()
        self._layout_dashboard_bottom()
        self.refresh_dashboard()
        self.show_banner("تم تطبيق التخصيص ✅ — اللون والخط والبطاقات", "success")

    # ---------- Navigation & Lazy Tabs ----------
    def hidden_tabs(self):
        return () if self.is_admin else self.EMPLOYEE_HIDDEN_TABS

    def _current_tab_index(self):
        cur = self.stackedWidget.currentWidget()
        for idx, w in self._tab_widgets.items():
            if w is cur:
                return idx
        return 0

    def _ensure_tab(self, idx):
        if self._tab_built.get(idx):
            return
        builder = self._tab_builders.get(idx)
        if builder is None:
            return
        self._tab_built[idx] = True
        page = self._tab_widgets[idx]
        builder(page)
        # Responsive + direction pass over everything the builder created.
        ui_theme.responsive_pass(page)
        adapt = getattr(self, "_adapt_page_layout", None)
        if callable(adapt):
            try:
                adapt(idx)
            except Exception:
                pass

    def goto_tab(self, index):
        if index in self.hidden_tabs():
            messagebox.showerror("صلاحيات", "هذه الصفحة للمدير فقط", parent=self)
            return
        page = self._tab_widgets.get(index)
        if page is None:
            return
        self._ensure_tab(index)
        self.switchTo(page)

    def goto_pos(self):
        self.goto_tab(1)
        QTimer.singleShot(80, lambda: hasattr(self, "e_barcode") and self.e_barcode.setFocus())

    def _on_tab_changed(self, _stack_idx):
        idx = self._current_tab_index()
        if idx in self.hidden_tabs():
            self.goto_tab(0)
            return
        self._ensure_tab(idx)
        # Newly built pages: Arabic right-to-left, English left-to-right.
        try:
            ui_theme.apply_auto_direction(self.stackedWidget.currentWidget())
        except Exception:
            pass
        if idx == 0:
            self.refresh_dashboard()
        elif idx == 9:
            self.mobile_refresh()
            self._qr_refresh()

    def show_shortcuts(self):
        txt = (
            "⌨️ اختصارات البرنامج\n\n"
            "F1  — عرض هذه النافذة\n"
            "F2  — الانتقال للكاشير والتركيز على الباركود\n"
            "F9  — إتمام البيع في الكاشير\n"
            "Enter في خانة الباركود — إضافة الدواء بالباركود\n"
            "ضغطتان على دواء في نتائج البحث — إضافته للفاتورة\n"
            "ضغطتان على دواء في المخزون — عرض تشغيلاته وصلاحياته\n\n"
            "💡 نصائح سريعة:\n"
            "• الباركود رقم تعريف فقط؛ لو غير معروف اربطه مرة واحدة.\n"
            "• البيع يأخذ دائماً من أقرب تشغيلة تنتهي أولاً (FEFO).\n"
            "• خذ نسخة احتياطية من الإعدادات قبل أي تحديث."
        )
        messagebox.TextViewerDialog(self, "اختصارات لوحة المفاتيح — F1", txt, width=520, height=400).exec()

    # ---------- 3s Live Poll ----------
    def _safe_live_tick(self):
        try:
            self._live_tick()
        except Exception:
            try:
                import traceback
                err = traceback.format_exc(limit=3)
                if getattr(self, "_live_last_error", "") != err:
                    self._live_last_error = err
                    with open(os.path.join(BASE, "error.log"), "a", encoding="utf-8") as f:
                        f.write("live_poll %s\n%s\n" % (datetime.now().isoformat(timespec="seconds"), err))
            except Exception:
                pass

    def _live_tick(self):
        try:
            row = self.db.conn.execute("SELECT MAX(id) AS m FROM sales").fetchone()
            last_id = row["m"] if row and row["m"] is not None else 0
            pend = self.db.conn.execute(
                "SELECT COUNT(*) AS c FROM sales WHERE source='mobile' "
                "AND status='completed' AND (printed_at IS NULL OR printed_at='')"
            ).fetchone()["c"]
            self._live_last_ok = True
        except Exception:
            self._live_last_ok = False
            self._live_update_status_label()
            return

        changed = (last_id != self._live_last_sale_id) or (pend != self._live_last_pending)
        self._live_last_sale_id = last_id
        self._live_last_pending = pend
        self._live_update_status_label()

        running = getattr(self, "mobile_server", None) is not None and self.mobile_server.running
        if running != self._live_last_server_running:
            self._live_last_server_running = running
            changed = True
        if hasattr(self, "qr_label"):
            self._qr_refresh()
        if not changed:
            return
        try:
            self.mobile_refresh()
        except Exception:
            pass
        try:
            self.refresh_dashboard()
        except Exception:
            pass
        try:
            if self._current_tab_index() == 1:
                self.pos_search_refresh()
        except Exception:
            pass
        try:
            if getattr(self, "_inv_win", None) is not None and self._inv_win.isVisible():
                self._inv_refresh()
        except Exception:
            pass

    def _live_update_status_label(self):
        if not hasattr(self, "lbl_live_update"):
            return
        now = datetime.now().strftime("%H:%M:%S")
        if self._live_last_ok:
            self.lbl_live_update.setText("🟢 متصل — آخر تحديث: %s (كل 3 ثوانٍ)" % now)
        else:
            self.lbl_live_update.setText("🔴 غير متصل — آخر محاولة: %s" % now)

    # ---------- Global Exception Handler ----------
    def _install_error_logging(self):
        import traceback as _tb
        from database import redact_text
        app = self
        app._in_error_dialog = False

        def handle_exception(exc, val, tb):
            raw_tb = "".join(_tb.format_exception(exc, val, tb))
            safe_tb = redact_text(raw_tb, 4000)
            err_msg = redact_text("%s: %s" % (exc.__name__, val), 400)
            try:
                app.db.syslog("error", "desktop", "ui_exception", err_msg, safe_tb[-3000:])
            except Exception:
                pass
            try:
                with open(os.path.join(BASE, "error.log"), "a", encoding="utf-8") as f:
                    f.write("\n[%s] %s\n%s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), err_msg, safe_tb))
            except Exception:
                pass
            _tb.print_exception(exc, val, tb)
            if getattr(app, "_in_error_dialog", False):
                return

            def show_box():
                if getattr(app, "_in_error_dialog", False):
                    return
                app._in_error_dialog = True
                try:
                    ui_dialogs.showerror(
                        "حدث خطأ غير متوقع",
                        "تعذّر إكمال العملية الحالية بسبب خطأ غير متوقع.\n\n"
                        "الخطأ: %s\n\n"
                        "تم حفظ التفاصيل في ملف error.log بجانب البرنامج.\n"
                        "يمكنك متابعة العمل أو إعادة المحاولة." % err_msg,
                        parent=app,
                    )
                except Exception:
                    pass
                finally:
                    app._in_error_dialog = False

            if threading.current_thread() is threading.main_thread():
                show_box()
            else:
                app._ui_post(show_box)

        sys.excepthook = handle_exception
        threading.excepthook = lambda args: handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

    # ---------- Window Lifecycle ----------
    def _adapt_page_layout(self, idx=None):
        """Flip wide/tall layouts to match the current window width."""
        width = self.width()
        # POS: search results beside the cart when wide, stacked when narrow.
        split = getattr(self, "_pos_split", None)
        if split is not None:
            want = Qt.Horizontal if width >= 1180 else Qt.Vertical
            if split.orientation() != want:
                split.setOrientation(want)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self._topbar_compact(self.width())
        except Exception:
            pass
        for idx in list(getattr(self, "_tab_built", {}).keys()):
            try:
                self._adapt_page_layout(idx)
            except Exception:
                pass

    def closeEvent(self, event):
        ui_theme.save_main_window_geometry(self, self.db)
        try:
            self._live_timer.stop()
        except Exception:
            pass
        try:
            if getattr(self, "mobile_server", None) is not None:
                self.mobile_server.stop()
        except Exception:
            pass
        super().closeEvent(event)


def _try_restore_latest_backup():
    db_path = os.path.join(BASE, "pharmacy.db")
    folder = os.path.join(BASE, "backups")
    try:
        cands = [os.path.join(folder, f) for f in os.listdir(folder) if f.startswith("pharmacy_") and f.endswith(".db")]
    except Exception:
        return False
    cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for cand in cands:
        try:
            if not DB.verify_backup(cand):
                continue
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            for suffix in ("", "-wal", "-shm"):
                p = db_path + suffix
                if os.path.exists(p):
                    os.rename(p, "%s.corrupt-%s%s" % (db_path, stamp, suffix))
            shutil.copyfile(cand, db_path)
            return True
        except Exception:
            continue
    return False


def _enable_dpi_awareness():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _show_fatal_error(title, summary, detail=""):
    try:
        from database import redact_text
        safe_detail = redact_text(detail, 1200) if detail else ""
    except Exception:
        safe_detail = str(detail or "")[:1200]
    msg = summary
    if safe_detail:
        msg += "\n\nالتفاصيل:\n" + safe_detail
    msg += "\n\nتم حفظ سجل الخطأ في:\n" + os.path.join(BASE, "error.log")
    try:
        if QApplication.instance() is None:
            _qapp = QApplication(sys.argv)
            _qapp.setLayoutDirection(Qt.RightToLeft)
            ui_theme.apply_qt_theme(_qapp, "dark", "teal", 0)
        ui_dialogs.showerror(title, msg, parent=None)
        return
    except Exception:
        pass
    try:
        print(title + ": " + msg)
    except Exception:
        pass


def main():
    _enable_dpi_awareness()
    # Fractional scaling (125% / 150% / 175%) must not round the UI up into a
    # size the screen cannot show; PassThrough keeps the logical size faithful.
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass
    qapp = QApplication.instance() or QApplication(sys.argv)
    # Arabic interface flows right-to-left; every text widget is then flipped
    # to left-to-right automatically when it holds English text.
    qapp.setLayoutDirection(Qt.RightToLeft)
    ui_theme.install_auto_direction(qapp)
    qapp.setApplicationName("Pharmacy Enterprise")

    try:
        db = DB()
    except Exception as exc:
        restored = _try_restore_latest_backup()
        db = None
        if restored:
            try:
                db = DB()
            except Exception:
                db = None
        if db is None:
            import traceback
            tb_txt = traceback.format_exc()
            try:
                with open(os.path.join(BASE, "error.log"), "w", encoding="utf-8") as f:
                    f.write(tb_txt)
            except Exception:
                pass
            _startup_log("database open FAILED (restored=%s)" % restored)
            _show_fatal_error(
                "خطأ في قاعدة البيانات",
                "تعذّر فتح قاعدة البيانات pharmacy.db"
                + (" (تمت استعادة نسخة احتياطية لكنها لم تعمل)." if restored else " ولا توجد نسخة احتياطية سليمة."),
                "%s: %s" % (type(exc).__name__, exc),
            )
            return

    _startup_log("app start: database ok")
    try:
        login = LoginWindow(db, log_fn=_startup_log)
        user = login.run()
        if not user:
            _startup_log("login closed without a user — clean exit")
            db.close()
            return
        _startup_log("login accepted: user=%s" % user["username"])

        def _startup_backup_async():
            try:
                folder = os.path.join(BASE, "backups")
                newest = 0.0
                if os.path.isdir(folder):
                    for f in os.listdir(folder):
                        if f.startswith("pharmacy_") and f.endswith(".db"):
                            newest = max(newest, os.path.getmtime(os.path.join(folder, f)))
                import time as _time
                if newest == 0.0 or _time.time() - newest > 24 * 3600:
                    bdb = DB(path=db.path, init=False)
                    try:
                        bdb.backup()
                    finally:
                        bdb.close()
            except Exception:
                pass

        threading.Thread(target=_startup_backup_async, daemon=True).start()
        try:
            if receipt_printer is not None:
                receipt_printer.prune_receipts(BASE)
        except Exception:
            pass

        win = App(db, user)
        win.show()
        win.raise_()
        win.activateWindow()
        _startup_log("main window shown")
        qapp.exec()
    except Exception as exc:
        import traceback
        tb_txt = traceback.format_exc()
        traceback.print_exc()
        _startup_log("FATAL exception — see error.log")
        try:
            with open(os.path.join(BASE, "error.log"), "w", encoding="utf-8") as f:
                f.write(tb_txt)
        except Exception:
            pass
        _show_fatal_error(
            "خطأ غير متوقع أثناء التشغيل",
            "توقف البرنامج بسبب خطأ غير متوقع.",
            "%s: %s" % (type(exc).__name__, exc),
        )
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
