# -*- coding: utf-8 -*-
"""
Core tabs mixin (PySide6-Fluent-Widgets):
  - Tab 0: Dashboard
  - Tab 1: POS (الكاشير)
  - Tab 2: Inventory (المخزون)
  - Tab 3: Purchases & Suppliers (المشتريات والموردين)
  - Tab 4: Customers (العملاء)
"""
from datetime import date, datetime
import sqlite3
import time as _t

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    EditableComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    SearchLineEdit,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    TitleLabel,
)

from app_helpers import BASE, ar_date, money, safe_float, safe_int, strict_float, strict_int
from database import (
    DB,
    allowed_units,
    discount_label,
    drug_default_line_discount,
    ean13_png_bytes,
    unit_price,
    units_for_qty,
)
import ui_dialogs as messagebox
import ui_theme

try:
    import ai_forecast
except Exception:
    ai_forecast = None
try:
    import mobile_server
except Exception:
    mobile_server = None
try:
    import printer as receipt_printer
except Exception:
    receipt_printer = None


class CoreTabsMixin:
    """Dashboard, POS, Inventory, Purchases, Customers tabs & dialogs."""

    # Arabic-native dosage-form picker. Stored values may be Arabic or the
    # legacy English names; both are understood by database.allowed_units().
    FORM_AR = {
        "Tablets": "أقراص",
        "Capsules": "كبسولات",
        "Syrup": "شراب",
        "Suspension": "معلق",
        "Drops": "قطرة",
        "Cream": "كريم",
        "Ointment": "مرهم",
        "Gel": "جل",
        "Spray": "بخاخ",
        "Injection": "حقن",
        "Sachet": "أكياس",
        "Suppository": "تحاميل",
    }

    # =========================================================================
    # Dashboard (Tab 0)
    # =========================================================================
    def _dash_visible_cards(self):
        all_keys = ["sales", "profit", "cash", "invoices", "low", "expiry", "critical", "inv_value"]
        if not getattr(self, "ui_dash_cards", ""):
            vis = set(all_keys)
        else:
            vis = {k.strip() for k in self.ui_dash_cards.split(",") if k.strip()} or set(all_keys)
        if not self.is_admin:
            vis -= {"profit", "inv_value"}
        return vis

    def _apply_dash_cards_visibility(self):
        vis = self._dash_visible_cards()
        for key, card in getattr(self, "dash_cards", {}).items():
            card.setVisible(key in vis)

    def _layout_dashboard_bottom(self):
        if not hasattr(self, "_dash_bottom_box"):
            return
        while self._dash_bottom_box.count():
            self._dash_bottom_box.takeAt(0)
        first, second = (
            (self.dash_alerts_frame, self.dash_best_frame)
            if getattr(self, "ui_alerts_top", True)
            else (self.dash_best_frame, self.dash_alerts_frame)
        )
        self._dash_bottom_box.addWidget(first)
        self._dash_bottom_box.addWidget(second)

    def build_dashboard(self, outer=None):
        container = outer or self._tab_widgets[0]
        outer_lay = QVBoxLayout(container)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll, _inner, tab = ui_theme.make_scroll_page("dashInner")
        outer_lay.addWidget(scroll)

        tab.addWidget(TitleLabel("لوحة التحكم الرئيسية"))
        self.lbl_dash_date = CaptionLabel("")
        tab.addWidget(self.lbl_dash_date)

        # KPI Cards — auto-fit grid: 4 per row on wide screens, fewer on narrow
        self.dash_cards = {}
        self._dash_cards_grid = ui_theme.ResponsiveGrid(min_item_width=250, spacing=10)
        defs = [
            ("sales", "مبيعات اليوم", self.pal["accent"], lambda: self.goto_tab(5) if self.is_admin else self.goto_pos()),
            ("profit", "صافي ربح اليوم", self.pal["success"], lambda: self.goto_tab(5)),
            ("cash", "نقدي اليوم", self.pal["info"], lambda: self.goto_tab(6)),
            ("invoices", "فواتير اليوم", self.pal["muted"], lambda: self.goto_tab(5) if self.is_admin else self.goto_pos()),
            ("low", "أصناف ناقصة", self.pal["warning"], lambda: self.goto_tab(2)),
            ("expiry", "تشغيلات قريبة الانتهاء (30 يوم)", self.pal["danger"], lambda: self.goto_tab(2)),
            ("critical", "طلبات حرجة (التنبؤ)", self.pal["danger"], lambda: self.goto_tab(8) if self.is_admin else self.goto_tab(2)),
            ("inv_value", "قيمة المخزون (سعر البيع)", self.pal["accent"], lambda: self.goto_tab(2)),
        ]
        for key, title, acc, cb in defs:
            card = ui_theme.StatCard(title, "—", "", acc, click_cb=cb)
            self._dash_cards_grid.addWidget(card)
            self.dash_cards[key] = card
        tab.addWidget(self._dash_cards_grid)
        self._apply_dash_cards_visibility()

        # Quick actions bar — wraps onto extra lines instead of overflowing
        acts_card = CardWidget()
        acts_outer = QVBoxLayout(acts_card)
        acts_outer.setContentsMargins(14, 10, 14, 10)
        acts = ui_theme.FlowRow(spacing=8)
        acts.add(StrongBodyLabel("إجراءات سريعة:"))
        btn_pos = PrimaryPushButton("🛒 بيع جديد (F2)")
        btn_pos.clicked.connect(self.goto_pos)
        acts.add(btn_pos)
        if self.is_admin:
            btn_add = PushButton("➕ إضافة دواء")
            btn_add.clicked.connect(lambda: (self.goto_tab(2), self.drug_dialog()))
            acts.add(btn_add)
        btn_inv = PushButton("📦 المخزون")
        btn_inv.clicked.connect(lambda: self.goto_tab(2))
        acts.add(btn_inv)
        if self.is_admin:
            btn_ai = PushButton("🤖 التنبؤ الذكي")
            btn_ai.clicked.connect(lambda: self.goto_tab(8))
            acts.add(btn_ai)
            btn_bk = PushButton("💾 نسخة احتياطية")
            btn_bk.clicked.connect(self.do_backup)
            acts.add(btn_bk)
        btn_ref = PushButton("🔄 تحديث اللوحة")
        btn_ref.clicked.connect(self.refresh_dashboard)
        acts.add(btn_ref)
        acts_outer.addWidget(acts)
        tab.addWidget(acts_card)

        # Bottom stacked tables: Alerts + Best Sellers
        self._dash_bottom_box = QVBoxLayout()
        self._dash_bottom_box.setSpacing(10)
        tab.addLayout(self._dash_bottom_box)

        self.dash_alerts_frame = CardWidget()
        al_lay = QVBoxLayout(self.dash_alerts_frame)
        al_lay.setContentsMargins(14, 12, 14, 12)
        al_lay.addWidget(StrongBodyLabel("⚠️ تنبيهات تحتاج انتباهك — أولاً"))
        self.tree_dash_alerts = TableWidget()
        ui_theme.configure_table(self.tree_dash_alerts, ("النوع", "الصنف", "التفاصيل"), (150, 260, 400), stretch_cols=(2,), min_height=200)
        al_lay.addWidget(self.tree_dash_alerts)

        self.dash_best_frame = CardWidget()
        be_lay = QVBoxLayout(self.dash_best_frame)
        be_lay.setContentsMargins(14, 12, 14, 12)
        be_lay.addWidget(StrongBodyLabel("⚡ الأكثر مبيعاً اليوم"))
        self.tree_dash_best = TableWidget()
        ui_theme.configure_table(self.tree_dash_best, ("الدواء", "الكمية", "الإجمالي"), (320, 140, 180), stretch_cols=(0,), min_height=200)
        be_lay.addWidget(self.tree_dash_best)

        self._layout_dashboard_bottom()
        tab.addStretch(1)

    def refresh_dashboard(self):
        if not hasattr(self, "dash_cards"):
            return
        try:
            self.lbl_dash_date.setText("اليوم: %s  •  اضغط على أي بطاقة للانتقال لتبويبها" % ar_date(date.today()))
            r = self.db.report_daily()
            low = self.db.low_stock()
            exp30 = self.db.near_expiry(30)
            _rows, _tc, ts = self.db.report_inventory_value()
            self._kick_dash_ai()
            crit_text = str(getattr(self, "_dash_crit_count", "…"))
            vals = {
                "sales": money(r["total"]),
                "profit": money(r["net_profit"]),
                "cash": money(r["cash"]),
                "invoices": str(r["count"]),
                "low": str(len(low)),
                "expiry": str(len(exp30)),
                "critical": crit_text,
                "inv_value": money(ts),
            }
            subs = {
                "sales": "كارت: %s  •  آجل: %s" % (money(r["card"]), money(r["credit"])),
                "profit": "إجمالي الربح قبل المصروفات: %s  •  مصروفات اليوم: %s" % (money(r["profit"]), money(r["expenses"])),
                "cash": "رصيد أول المدة يظهر في الخزنة",
                "invoices": "فواتير مسجلة اليوم",
                "low": "أقل من الحد الأدنى — راجع المخزون",
                "expiry": "تنتهي خلال 30 يوم — راجع التشغيلات",
                "critical": "مخزون يكفي 3 أيام أو أقل",
                "inv_value": "عدد الأصناف: %d" % len(_rows),
            }
            for key, card in self.dash_cards.items():
                card.set_values(vals.get(key, "—"), subs.get(key, ""))

            best = self.db.report_best_sellers()
            if not best:
                ui_theme.set_table_rows(self.tree_dash_best, [("لا توجد مبيعات بعد", "—", "أنشئ أول فاتورة من الكاشير")])
            else:
                ui_theme.set_table_rows(
                    self.tree_dash_best,
                    [(b["trade_en"], b["units"], money(b["total"])) for b in best],
                )

            p = ui_theme.palette(self.theme_name, self.ui_accent)
            al_rows = []
            al_styles = []
            for d in low[:8]:
                al_rows.append(("نقص مخزون", d["trade_en"], "المخزون %.1f علبة — الحد الأدنى %s" % (d.get("stock_boxes", 0), d["min_stock"])))
                al_styles.append((p["danger"], p["danger_bg"]))
            for b in exp30[:8]:
                al_rows.append(("قرب انتهاء", b["trade_en"], "تشغيلة %s تنتهي %s" % (b["batch_no"], b["expiry"])))
                al_styles.append((p["warning"], p["warning_bg"]))
            if not al_rows:
                al_rows.append(("✅", "لا توجد تنبيهات", "كل شيء تحت السيطرة"))
                al_styles.append((p["success"], p["success_bg"]))
            ui_theme.set_table_rows(self.tree_dash_alerts, al_rows, al_styles)
            self.update_topbar()
        except Exception:
            pass

    def _kick_dash_ai(self):
        if ai_forecast is None:
            self._dash_crit_count = 0
            return
        now = _t.monotonic()
        if getattr(self, "_dash_ai_running", False):
            return
        if now - getattr(self, "_dash_ai_last", 0.0) < 600:
            return
        self._dash_ai_running = True
        import cloud_sync
        db_path = self.db.path

        def work():
            db = DB(path=db_path, init=False)
            try:
                rl = ai_forecast.generate_reorder_list(db, horizon_days=30, lead_time_days=3, safety_days=2)
                return len([x for x in rl if x.get("urgency") == "حرجة"])
            finally:
                db.close()

        def done(result, error):
            def ui():
                self._dash_ai_running = False
                self._dash_ai_last = _t.monotonic()
                if error is None and result is not None:
                    self._dash_crit_count = result
                    card = self.dash_cards.get("critical")
                    if card:
                        card.set_values(str(result))
            self._ui_post(ui)

        cloud_sync.run_in_background(work, done)

    # =========================================================================
    # Shared Drug Table & POS Helpers
    # =========================================================================
    def drug_label(self, d):
        _sf = " ".join(x for x in (d.get("strength", ""), d.get("form", "")) if x)
        return "%s — %s (%s) | %s | المخزون: %.1f علبة" % (
            d["trade_en"], d.get("trade_ar", ""), _sf, money(d["sell_price"]), d.get("stock_boxes", 0)
        )

    def make_drug_search_tree(self, min_height=220):
        return ui_theme.DrugSearchTableWidget(money, allowed_units, unit_price, min_height=min_height)

    def _line_disc_amount(self, drug, pack_level, qty, mode="auto", per_unit=None):
        try:
            q = float(qty or 0)
        except (TypeError, ValueError):
            return 0.0
        if q <= 0:
            return 0.0
        if mode == "manual" and per_unit is not None:
            return round(float(per_unit) * q + 1e-9, 2)
        return drug_default_line_discount(drug, unit_price(drug, pack_level), q)

    def refresh_pos_totals(self):
        if not hasattr(self, "lbl_subtotal"):
            return 0.0, 0.0
        sub = sum(
            unit_price(it["drug"], it["pack_level"]) * float(it["qty_display"]) - float(it.get("discount") or 0)
            for it in self.cart
            if not it.get("held")
        )
        disc = safe_float(self.e_discount.text())
        total = max(0.0, sub - disc)
        self.lbl_subtotal.setText("المجموع الفرعي: %s" % money(sub))
        self.lbl_total.setText("الإجمالي: %s" % money(total))
        if hasattr(self, "lbl_change"):
            paid_txt = self.e_paid.text().strip() if hasattr(self, "e_paid") else ""
            if paid_txt:
                change = safe_float(paid_txt, 0.0) - total
                self.lbl_change.setText(
                    "الباقي للعميل: %s" % money(change)
                    if change >= 0
                    else "⚠️ المدفوع أقل من الإجمالي بـ %s" % money(-change)
                )
            else:
                self.lbl_change.setText("الباقي للعميل: —")
        return sub, total

    def cart_tree_refresh(self):
        if not hasattr(self, "tree_cart"):
            return
        p = ui_theme.palette(self.theme_name, self.ui_accent)
        rows = []
        styles = []
        for it in self.cart:
            d = it["drug"]
            up = unit_price(d, it["pack_level"])
            held = bool(it.get("held"))
            _ld = float(it.get("discount") or 0)
            rows.append((
                ("⏳ محذوف مؤقتاً — " + d["trade_en"]) if held else d["trade_en"],
                d.get("trade_ar", ""),
                it["pack_level"],
                it["qty_display"],
                money(up),
                money(_ld),
                money(up * float(it["qty_display"]) - _ld),
                "%.1f" % d.get("stock_boxes", 0),
            ))
            styles.append((p["muted"], p["row_alt"]) if held else None)
        ui_theme.set_table_rows(self.tree_cart, rows, styles)
        self.refresh_pos_totals()

    # =========================================================================
    # POS (Tab 1)
    # =========================================================================
    def build_pos(self, outer=None):
        container = outer or self._tab_widgets[1]
        outer_lay = QVBoxLayout(container)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll, _inner, tab = ui_theme.make_scroll_page("posInner")
        outer_lay.addWidget(scroll)

        # Top barcode & search bar
        top_card = CardWidget()
        top = QHBoxLayout(top_card)
        top.setContentsMargins(12, 10, 12, 10)
        top.setSpacing(8)
        top.addWidget(StrongBodyLabel("🔎 باركود:"))
        self.e_barcode = LineEdit()
        self.e_barcode.setPlaceholderText("امسح الباركود ثم اضغط Enter")
        self.e_barcode.setMinimumWidth(150)
        self.e_barcode.setFont(ui_theme.qfont(13))
        self.e_barcode.returnPressed.connect(self.pos_scan)
        top.addWidget(self.e_barcode)

        btn_scan = PrimaryPushButton("إضافة بالباركود")
        btn_scan.clicked.connect(self.pos_scan)
        top.addWidget(btn_scan)

        top.addSpacing(10)
        top.addWidget(BodyLabel("بحث بالاسم / المادة الفعالة:"))
        self.e_search = SearchLineEdit()
        self.e_search.setPlaceholderText("اكتب اسم الدواء أو المادة الفعالة...")
        self.e_search.setMinimumWidth(150)
        self.e_search.textChanged.connect(lambda _t: self._debounce("pos_search", 120, self.pos_search_refresh))
        self.e_search.returnPressed.connect(self.pos_search_refresh)
        top.addWidget(self.e_search, 1)

        btn_s = PushButton("بحث")
        btn_s.clicked.connect(self.pos_search_refresh)
        top.addWidget(btn_s)
        tab.addWidget(top_card)

        tab.addWidget(CaptionLabel("F2 للانتقال للباركود  •  F9 لإتمام البيع  •  F1 للاختصارات  •  اضغط مرتين على الدواء لإضافته للفاتورة"))

        # Split middle area: search results + cart. A splitter so it can flip
        # to a stacked column on narrow windows (see _adapt_page_layout).
        self._pos_split = QSplitter(Qt.Horizontal)
        self._pos_split.setChildrenCollapsible(False)
        self._pos_split.setHandleWidth(8)
        mid = self._pos_split

        # Left side in code -> right in RTL (Search results + unit picker)
        left_card = CardWidget()
        left = QVBoxLayout(left_card)
        left.setContentsMargins(12, 12, 12, 12)
        left.setSpacing(8)
        left.addWidget(StrongBodyLabel("نتائج البحث (اضغط مرتين للإضافة):"))
        self.list_search = self.make_drug_search_tree(min_height=240)
        self.list_search.drugActivated.connect(lambda _d: self.pos_add_selected())
        left.addWidget(self.list_search, 1)

        unit_row = QHBoxLayout()
        unit_row.setSpacing(8)
        btn_add_sel = PrimaryPushButton("➕ إضافة المحدد للفاتورة")
        btn_add_sel.clicked.connect(self.pos_add_selected)
        unit_row.addWidget(btn_add_sel)
        unit_row.addSpacing(8)
        unit_row.addWidget(StrongBodyLabel("وحدة البيع:"))
        self._pos_unit = "box"
        self._pos_unit_group = QButtonGroup(self)
        for val, lbl_txt in (("box", "علبة (Box)"), ("strip", "شريط (Strip)"), ("pill", "حبة (Pill)")):
            rb = RadioButton(lbl_txt)
            if val == "box":
                rb.setChecked(True)
            rb.toggled.connect(lambda checked, v=val: self._set_pos_unit(v) if checked else None)
            self._pos_unit_group.addButton(rb)
            unit_row.addWidget(rb)
        unit_row.addWidget(StrongBodyLabel("الكمية:"))
        self.e_qty = LineEdit()
        self.e_qty.setText("1")
        self.e_qty.setFixedWidth(70)
        unit_row.addWidget(self.e_qty)
        unit_row.addStretch(1)
        left.addLayout(unit_row)

        self.lbl_alt = CaptionLabel("بدائل بنفس المادة الفعالة تظهر هنا عند اختيار دواء.")
        self.lbl_alt.setWordWrap(True)
        left.addWidget(self.lbl_alt)
        mid.addWidget(left_card)

        # Cart card
        right_card = CardWidget()
        right = QVBoxLayout(right_card)
        right.setContentsMargins(12, 12, 12, 12)
        right.setSpacing(8)
        right.addWidget(StrongBodyLabel("فاتورة البيع الحالية:"))
        self.tree_cart = TableWidget()
        ui_theme.configure_table(
            self.tree_cart,
            ("الدواء", "عربي", "الوحدة", "الكمية", "سعر الوحدة", "خصم السطر", "الإجمالي", "المخزون"),
            (150, 95, 65, 60, 85, 75, 95, 70),
            stretch_cols=(0,),
            min_height=240,
        )
        right.addWidget(self.tree_cart, 1)

        cbtns = QHBoxLayout()
        cbtns.setSpacing(6)
        for text, fn, p_color in [
            ("💸 خصم السطر", self.pos_line_discount_dialog, None),
            ("🗑 حذف مؤقت", self.pos_remove_line, self.pal["danger"]),
            ("↩ استرجاع", self.pos_restore_line, self.pal["success"]),
            ("مسح الفاتورة", self.pos_clear_cart, self.pal["warning"]),
            ("⏸ تعليق (Hold)", self.pos_hold, None),
            ("↩ استدعاء", self.pos_recall, None),
        ]:
            b = PushButton(text)
            if p_color:
                b.setStyleSheet(f"color: {p_color}; font-weight: bold;")
            b.clicked.connect(fn)
            cbtns.addWidget(b)
        cbtns.addStretch(1)
        right.addLayout(cbtns)
        mid.addWidget(right_card)
        tab.addWidget(self._pos_split, 1)

        # Bottom Totals & Checkout Card
        self.pos_panel = CardWidget()
        panel = QVBoxLayout(self.pos_panel)
        panel.setContentsMargins(16, 12, 16, 12)
        panel.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(StrongBodyLabel("العميل:"))
        self.cb_customer = ComboBox()
        self.cb_customer.setMinimumWidth(140)
        self._refresh_customer_combo()
        row1.addWidget(self.cb_customer)

        row1.addWidget(StrongBodyLabel("خصم (ج.م):"))
        self.e_discount = LineEdit()
        self.e_discount.setText("0")
        self.e_discount.setFixedWidth(90)
        self.e_discount.textChanged.connect(lambda _t: self.refresh_pos_totals())
        row1.addWidget(self.e_discount)

        row1.addWidget(StrongBodyLabel("طريقة الدفع:"))
        self._pos_pay = "cash"
        self._pos_pay_group = QButtonGroup(self)
        for val, lbl_txt in (("cash", "نقدي"), ("card", "فيزا / كارت"), ("credit", "آجل (عميل)")):
            rb = RadioButton(lbl_txt)
            if val == "cash":
                rb.setChecked(True)
            rb.toggled.connect(lambda checked, v=val: self._set_pos_pay(v) if checked else None)
            self._pos_pay_group.addButton(rb)
            row1.addWidget(rb)

        row1.addWidget(StrongBodyLabel("المدفوع:"))
        self.e_paid = LineEdit()
        self.e_paid.setPlaceholderText("اتركه فارغاً للتام")
        self.e_paid.setFixedWidth(120)
        self.e_paid.textChanged.connect(lambda _t: self.refresh_pos_totals())
        row1.addWidget(self.e_paid)
        row1.addStretch(1)
        panel.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(16)
        self.lbl_subtotal = BodyLabel("المجموع الفرعي: 0.00 ج.م")
        self.lbl_total = QLabel("الإجمالي: 0.00 ج.م")
        self.lbl_total.setFont(ui_theme.qfont(20, bold=True))
        self.lbl_total.setStyleSheet(f"color: {self.pal['success']}; background: transparent;")
        self.lbl_change = QLabel("الباقي للعميل: —")
        self.lbl_change.setFont(ui_theme.qfont(13, bold=True))
        self.lbl_change.setStyleSheet(f"color: {self.pal['info']}; background: transparent;")

        row2.addWidget(self.lbl_total)
        row2.addWidget(self.lbl_subtotal)
        row2.addWidget(self.lbl_change)
        row2.addStretch(1)

        btn_complete = PrimaryPushButton("✅ إتمام البيع (F9)")
        btn_complete.setMinimumHeight(40)
        btn_complete.setMinimumWidth(150)
        btn_complete.clicked.connect(self.pos_complete_sale)
        row2.addWidget(btn_complete)

        btn_rec = PushButton("🧾 عرض الإيصال")
        btn_rec.setMinimumHeight(40)
        btn_rec.clicked.connect(self.pos_show_receipt)
        row2.addWidget(btn_rec)
        panel.addLayout(row2)
        tab.addWidget(self.pos_panel)

        self.pos_search_refresh()
        self.e_barcode.setFocus()

    def _set_pos_unit(self, val):
        self._pos_unit = val

    def _set_pos_pay(self, val):
        self._pos_pay = val

    def _refresh_customer_combo(self):
        if not hasattr(self, "cb_customer"):
            return
        cur = self.cb_customer.currentText() if self.cb_customer.count() else "عميل نقدي"
        items = ["عميل نقدي"] + [c["name"] for c in self.db.customers()]
        self.cb_customer.clear()
        self.cb_customer.addItems(items)
        idx = self.cb_customer.findText(cur)
        self.cb_customer.setCurrentIndex(idx if idx >= 0 else 0)

    def _f9_complete_sale(self):
        if self._current_tab_index() != 1:
            return
        self.pos_complete_sale()

    def pos_search_refresh(self):
        if not hasattr(self, "list_search"):
            return
        q = self.e_search.text() if hasattr(self, "e_search") else ""
        self.search_results = self.db.search_drugs(q, limit=60)
        self.list_search.fill(self.search_results, empty_message="لا توجد نتائج مطابقة.")

    def pos_scan(self):
        code = self.e_barcode.text().strip()
        if not code:
            return
        drug, pack = self.db.lookup_barcode(code)
        self.e_barcode.clear()
        if not drug:
            self.unknown_barcode_dialog(code)
            return
        self.pos_add_drug(drug, pack or "box", 1)
        self.e_barcode.setFocus()

    def pos_add_selected(self):
        drug = self.list_search.selected_drug()
        if not drug:
            messagebox.showinfo("تنبيه", "اختر دواء من نتائج البحث أولاً", parent=self)
            return
        self.pos_add_drug(drug, self._pos_unit, safe_int(self.e_qty.text(), 1))
        self.e_barcode.setFocus()
        alts = self.db.alternatives(drug)
        if alts:
            txt = "بدائل بنفس المادة الفعالة (%s): " % drug["scientific"]
            txt += " | ".join("%s %s" % (a["trade_en"], money(a["sell_price"])) for a in alts[:5])
            self.lbl_alt.setText(txt)
        else:
            self.lbl_alt.setText("لا توجد بدائل مسجلة بنفس المادة الفعالة.")

    def pos_add_drug(self, drug, pack_level, qty):
        if pack_level not in allowed_units(drug):
            messagebox.showwarning(
                "وحدة غير متاحة",
                "الوحدة المختارة غير متاحة للشكل الصيدلاني: %s" % (drug.get("form") or "غير محدد"),
                parent=self,
            )
            return
        if qty is None or float(qty) <= 0:
            messagebox.showwarning("كمية غير صالحة", "الكمية يجب أن تكون أكبر من صفر", parent=self)
            return
        if pack_level in ("box", "strip") and float(qty) != int(float(qty)):
            messagebox.showwarning("كمية غير صالحة", "كمية العلبة / الشريط يجب أن تكون عدداً صحيحاً", parent=self)
            return
        if drug.get("stock_units", 0) < units_for_qty(drug, pack_level, qty):
            messagebox.showwarning("مخزون غير كافٍ", "المخزون المتاح من %s غير كافٍ لهذه الكمية." % drug["trade_en"], parent=self)
            return
        for it in self.cart:
            if it["drug"]["id"] == drug["id"] and it["pack_level"] == pack_level:
                it["held"] = False
                it["qty_display"] = float(it["qty_display"]) + float(qty)
                if it.get("disc_mode", "auto") == "auto":
                    it["discount"] = self._line_disc_amount(drug, pack_level, it["qty_display"], "auto")
                else:
                    it["discount"] = self._line_disc_amount(drug, pack_level, it["qty_display"], "manual", it.get("disc_per_unit"))
                break
        else:
            self.cart.append({
                "drug": drug,
                "pack_level": pack_level,
                "qty_display": float(qty),
                "held": False,
                "disc_mode": "auto",
                "discount": self._line_disc_amount(drug, pack_level, qty, "auto"),
            })
        self.cart_tree_refresh()
        try:
            self.e_qty.setText("1")
        except Exception:
            pass

    def pos_remove_line(self):
        idx = ui_theme.selected_row_index(self.tree_cart)
        if idx is None:
            messagebox.showinfo("تنبيه", "اختر سطراً من الفاتورة أولاً", parent=self)
            return
        it = self.cart[idx]
        if it.get("held"):
            messagebox.showinfo("تنبيه", "هذا السطر محذوف مؤقتاً بالفعل — استرجعه بزر «↩ استرجاع» أو أكمل البيع لاعتماد الحذف", parent=self)
            return
        it["held"] = True
        it["held_qty"] = float(it["qty_display"])
        self.cart_tree_refresh()

    def pos_restore_line(self):
        idx = ui_theme.selected_row_index(self.tree_cart)
        if idx is None:
            messagebox.showinfo("تنبيه", "اختر سطراً محذوفاً مؤقتاً من الفاتورة أولاً", parent=self)
            return
        it = self.cart[idx]
        if not it.get("held"):
            messagebox.showinfo("تنبيه", "هذا السطر ليس محذوفاً مؤقتاً", parent=self)
            return
        it["held"] = False
        self.cart_tree_refresh()

    def pos_line_discount_dialog(self):
        idx = ui_theme.selected_row_index(self.tree_cart)
        if idx is None:
            messagebox.showinfo("تنبيه", "اختر سطراً من الفاتورة أولاً", parent=self)
            return
        it = self.cart[idx]
        if it.get("held"):
            messagebox.showinfo("تنبيه", "هذا السطر محذوف مؤقتاً — استرجعه أولاً", parent=self)
            return
        d = it["drug"]
        up = unit_price(d, it["pack_level"])

        win = QDialog(self)
        win.setWindowTitle("خصم السطر — %s" % d["trade_en"])
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        lay = QVBoxLayout(win)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)

        lbl = StrongBodyLabel("%s — %s — سعر الوحدة: %s" % (d["trade_en"], it["pack_level"], money(up)))
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        lay.addWidget(CaptionLabel("خصم الدواء الافتراضي: %s" % (discount_label(d) or "بدون خصم")))
        lay.addWidget(BodyLabel("نوع الخصم لهذا السطر:"))

        state = {"kind": "none"}
        grp = QButtonGroup(win)
        for val, text in (("none", "بدون خصم"), ("percent", "نسبة % من سعر السطر"), ("amount", "مبلغ ثابت (ج.م) لكل وحدة")):
            rb = RadioButton(text)
            if val == "none":
                rb.setChecked(True)
            rb.toggled.connect(lambda chk, v=val: state.__setitem__("kind", v) if chk else None)
            grp.addButton(rb)
            lay.addWidget(rb)

        lay.addWidget(CaptionLabel("القيمة:"))
        e_val = LineEdit()
        e_val.setText("0")
        lay.addWidget(e_val)

        def apply_disc():
            kind = state["kind"]
            try:
                val = float(e_val.text() or 0)
            except ValueError:
                messagebox.showerror("خطأ", "قيمة الخصم غير صالحة", parent=win)
                return
            if kind == "none" or val <= 0:
                it["discount"] = 0.0
                it["disc_mode"] = "manual"
                it["disc_per_unit"] = 0.0
            elif kind == "percent":
                if val > 100:
                    messagebox.showerror("خطأ", "نسبة الخصم يجب أن تكون بين 0 و 100%", parent=win)
                    return
                it["disc_per_unit"] = round(up * val / 100.0 + 1e-9, 2)
                it["discount"] = self._line_disc_amount(d, it["pack_level"], it["qty_display"], "manual", it["disc_per_unit"])
                it["disc_mode"] = "manual"
            else:
                if val >= up:
                    messagebox.showerror("خطأ", "المبلغ الثابت يجب أن يكون أقل من سعر الوحدة", parent=win)
                    return
                it["disc_per_unit"] = val
                it["discount"] = self._line_disc_amount(d, it["pack_level"], it["qty_display"], "manual", val)
                it["disc_mode"] = "manual"
            win.accept()
            self.cart_tree_refresh()

        btn = PrimaryPushButton("✅ تطبيق خصم السطر")
        btn.clicked.connect(apply_disc)
        lay.addWidget(btn)
        ui_theme.fit_dialog_widget(win, 430, 330)
        win.exec()

    def pos_clear_cart(self):
        if not self.cart:
            messagebox.showinfo("تنبيه", "الفاتورة فارغة أصلاً", parent=self)
            return
        if not messagebox.askyesno("مسح الفاتورة", "هل تريد مسح كل أصناف الفاتورة الحالية؟", parent=self):
            return
        self.cart = []
        self.cart_tree_refresh()

    def pos_hold(self):
        if not self.cart:
            messagebox.showinfo("تنبيه", "الفاتورة فارغة — لا يوجد ما يتم تعليقه", parent=self)
            return
        self.held.append([dict(it) for it in self.cart])
        self.cart = []
        self.cart_tree_refresh()
        messagebox.showinfo("تم", "تم تعليق الفاتورة. عدد الفواتير المعلقة: %d" % len(self.held), parent=self)

    def pos_recall(self):
        if not self.held:
            messagebox.showinfo("تنبيه", "لا توجد فواتير معلقة", parent=self)
            return
        fresh = []
        for it in self.held.pop(0):
            try:
                d = self.db.get_drug(it["drug"]["id"])
            except Exception:
                d = None
            fresh.append({
                "drug": d or it["drug"],
                "pack_level": it["pack_level"],
                "qty_display": it["qty_display"],
                "held": bool(it.get("held")),
                "disc_mode": it.get("disc_mode", "auto"),
                "discount": float(it.get("discount") or 0),
                "disc_per_unit": it.get("disc_per_unit"),
            })
        self.cart = fresh
        self.cart_tree_refresh()

    def _customer_id(self):
        name = self.cb_customer.currentText().strip() if hasattr(self, "cb_customer") else ""
        if not name or name == "عميل نقدي":
            return None
        for c in self.db.customers():
            if c["name"] == name:
                return c["id"]
        return None

    def pos_complete_sale(self):
        active_cart = [it for it in self.cart if not it.get("held")]
        if not active_cart:
            if self.cart:
                messagebox.showinfo("تنبيه", "كل أصناف الفاتورة محذوفة مؤقتاً — استرجع ما تريده بزر «↩ استرجاع» أو أضف صنفاً جديداً", parent=self)
            else:
                messagebox.showinfo("تنبيه", "الفاتورة فارغة", parent=self)
            return
        _, total = self.refresh_pos_totals()
        pay = self._pos_pay
        cust_id = self._customer_id()
        try:
            disc = strict_float(self.e_discount.text(), "الخصم")
            disc = disc if disc is not None else 0.0
            paid_txt = self.e_paid.text().strip()
            paid_entered = strict_float(paid_txt, "المبلغ المدفوع") if paid_txt else None
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        if pay == "credit":
            if not cust_id:
                messagebox.showerror("خطأ", "البيع الآجل يحتاج عميل مسجل — اختر عميل من القائمة أو أضفه من تبويب العملاء", parent=self)
                return
            paid = paid_entered if paid_entered is not None else 0.0
            cust = [c for c in self.db.customers() if c["id"] == cust_id][0]
            if float(cust["credit_limit"] or 0) > 0 and float(cust["balance"]) + (total - disc - paid) > float(cust["credit_limit"]):
                messagebox.showerror("خطأ", "العميل وصل لحد الائتمان المسموح", parent=self)
                return
        else:
            paid = paid_entered if paid_entered is not None else total
            if pay == "cash" and paid < total:
                messagebox.showerror("خطأ", "المبلغ المدفوع أقل من الإجمالي", parent=self)
                return
        try:
            sale_id, inv, total2, change = self.db.create_sale(
                self.username, active_cart, discount=disc,
                payment_method=pay, customer_id=cust_id, paid=paid,
                shift_id=self.current_shift["id"] if self.current_shift else None,
            )
        except sqlite3.OperationalError:
            messagebox.showerror(
                "قاعدة البيانات مشغولة",
                "قاعدة البيانات مشغولة لحظياً (ربما الهاتف يحفظ فاتورة الآن) — أعد المحاولة بعد ثانية",
                parent=self,
            )
            return
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        msg = "تم البيع ✅\nفاتورة: %s\nالإجمالي: %s" % (inv, money(total2))
        if pay == "cash" and change:
            msg += "\nالباقي للعميل: %s" % money(change)
        messagebox.showinfo("تم البيع", msg, parent=self)
        self.show_banner("✅ " + msg.replace("\n", "  •  "), "success")
        self.last_receipt = (inv, list(active_cart), total2, change, pay)
        self.cart = []
        self.e_discount.setText("0")
        self.e_paid.clear()
        self.cb_customer.setCurrentIndex(0)
        self.cart_tree_refresh()
        self.pos_search_refresh()
        self.e_barcode.setFocus()

    def pos_show_receipt(self):
        if not getattr(self, "last_receipt", None):
            messagebox.showinfo("تنبيه", "لا يوجد إيصال بعد — أتمم بيع أولاً", parent=self)
            return
        inv, cart, total, change, pay = self.last_receipt
        _pharmacy_name = self.db.get_setting("pharmacy_name", "صيدلية المؤسسة") or "صيدلية المؤسسة"
        lines = [_pharmacy_name, "فاتورة: %s" % inv, "-" * 34]
        for it in cart:
            up = unit_price(it["drug"], it["pack_level"])
            lines.append("%s x%s @ %s = %s" % (it["drug"]["trade_en"], it["qty_display"], money(up), money(up * float(it["qty_display"]))))
        lines += ["-" * 34, "الإجمالي: %s" % money(total), "الباقي: %s" % money(change), "شكراً لزيارتك"]
        dlg = messagebox.TextViewerDialog(
            self, "إيصال %s" % inv, "\n".join(lines), width=520, height=470, monospace=True,
            extra_buttons=[("🖨️ طباعة", lambda d: self._pos_receipt_print(d, inv, lines, pay), True)],
        )
        dlg.exec()

    def unknown_barcode_dialog(self, code):
        win = QDialog(self)
        win.setWindowTitle("باركود غير معروف")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 620, 480)
        lay = QVBoxLayout(win)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        lbl1 = StrongBodyLabel("الباركود %s غير مسجل في قاعدة البيانات." % code)
        lbl1.setWordWrap(True)
        lay.addWidget(lbl1)
        lbl2 = CaptionLabel("الباركود رقم تعريف فقط — لا يحتوي على سعر. اربطه مرة واحدة بدواء موجود، أو أضف دواء جديد بسعره.")
        lbl2.setWordWrap(True)
        lay.addWidget(lbl2)

        e = SearchLineEdit()
        e.setPlaceholderText("ابحث عن الدواء للربط به...")
        lay.addWidget(e)

        lb = self.make_drug_search_tree(min_height=200)
        lay.addWidget(lb, 1)

        def refresh(_t=""):
            res = self.db.search_drugs(e.text(), limit=40)
            lb.fill(res)

        e.textChanged.connect(refresh)
        refresh()

        def link():
            drug = lb.selected_drug()
            if not drug:
                messagebox.showinfo("تنبيه", "اختر دواء أولاً", parent=win)
                return
            self.db.link_barcode(code, drug["id"])
            self.db.audit(self.username, "link_barcode", "%s -> drug %s" % (code, drug["id"]))
            messagebox.showinfo("تم", "تم ربط الباركود بالدواء", parent=win)
            win.accept()
            self.pos_add_drug(drug, "box", 1)
            self.e_barcode.setFocus()

        btns = QHBoxLayout()
        b_link = PrimaryPushButton("ربط الباركود بالدواء المحدد")
        b_link.clicked.connect(link)
        b_new = PushButton("إضافة دواء جديد بهذا الباركود")
        b_new.clicked.connect(lambda: (win.accept(), self.drug_dialog(prefill_barcode=code)))
        btns.addWidget(b_link)
        btns.addWidget(b_new)
        btns.addStretch(1)
        lay.addLayout(btns)
        win.exec()

    # =========================================================================
    # Inventory (Tab 2)
    # =========================================================================
    def build_inventory(self, outer=None):
        container = outer or self._tab_widgets[2]
        outer_lay = QVBoxLayout(container)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll, _inner, tab = ui_theme.make_scroll_page("invInner")
        outer_lay.addWidget(scroll)

        top_card = CardWidget()
        top = QHBoxLayout(top_card)
        top.setContentsMargins(12, 10, 12, 10)
        top.setSpacing(8)
        top.addWidget(StrongBodyLabel("بحث:"))
        self.e_inv_search = SearchLineEdit()
        self.e_inv_search.setPlaceholderText("ابحث بالاسم أو المادة الفعالة أو الباركود...")
        self.e_inv_search.setMinimumWidth(150)
        self.e_inv_search.textChanged.connect(lambda _t: self._debounce("inv_search", 130, self.inv_refresh))
        self.e_inv_search.returnPressed.connect(self.inv_refresh)
        top.addWidget(self.e_inv_search, 1)

        for label, cb, prim in [
            ("تحديث", self.inv_refresh, False),
            ("➕ إضافة دواء", lambda: self.drug_dialog(), True),
            ("✏️ تعديل المحدد", self.drug_edit_selected, False),
            ("📋 قائمة النواقص", self.show_shortages, False),
            ("⏰ قرب انتهاء الصلاحية", self.show_expiry, False),
            ("🏷️ ملصق باركود", self.barcode_label_dialog, False),
        ]:
            b = PrimaryPushButton(label) if prim else PushButton(label)
            b.clicked.connect(cb)
            top.addWidget(b)
        tab.addWidget(top_card)

        self.tree_inv = TableWidget()
        cols = ("#", "الدواء", "عربي", "المادة الفعالة", "التركيز", "الشكل", "خصم الدواء",
                "المخزون (علبة)", "الحد الأدنى", "سعر الشراء", "سعر البيع", "باركود")
        widths = (45, 160, 115, 120, 80, 80, 85, 95, 85, 95, 95, 115)
        ui_theme.configure_table(self.tree_inv, cols, widths, stretch_cols=(1,), min_height=360)
        if not self.is_admin:
            self.tree_inv.setColumnHidden(9, True)
        self.tree_inv.cellDoubleClicked.connect(lambda _r, _c: self.show_batches())
        tab.addWidget(self.tree_inv, 1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        for text, fn in [
            ("عرض التشغيلات / الصلاحية للدواء المحدد", self.show_batches),
            ("جرد / تعديل كمية (بموافقة المدير)", self.adjust_stock_dialog),
            ("تصدير الأدوية CSV", self.export_drugs),
        ]:
            b = PushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        tab.addLayout(btns)
        self.inv_refresh()

    def inv_refresh(self):
        if not hasattr(self, "tree_inv"):
            return
        q = self.e_inv_search.text() if hasattr(self, "e_inv_search") else ""
        self.inv_rows = self.db.search_drugs(q, limit=500)
        barcodes = {}
        try:
            inv_ids = [d["id"] for d in self.inv_rows]
            for start in range(0, len(inv_ids), 900):
                chunk = inv_ids[start:start + 900]
                marks = ",".join("?" * len(chunk))
                for r in self.db.conn.execute(
                    "SELECT drug_id, barcode FROM barcodes WHERE pack_level='box' AND drug_id IN (%s)" % marks,
                    chunk,
                ):
                    barcodes.setdefault(r["drug_id"], r["barcode"])
        except Exception:
            pass
        p = ui_theme.palette(self.theme_name, self.ui_accent)
        rows = []
        styles = []
        for d in self.inv_rows:
            bc = barcodes.get(d["id"], "")
            sb = d.get("stock_boxes", 0)
            rows.append((
                d["id"], d["trade_en"], d.get("trade_ar", ""), d.get("scientific", ""),
                d.get("strength", ""), d.get("form", ""), discount_label(d) or "—",
                "%.1f" % sb, d["min_stock"], money(d["buy_price"]), money(d["sell_price"]), bc,
            ))
            if sb <= d["min_stock"]:
                styles.append((p["danger"], p["danger_bg"]))
            elif sb <= d["min_stock"] * 1.5:
                styles.append((p["warning"], p["warning_bg"]))
            else:
                styles.append(None)
        ui_theme.set_table_rows(self.tree_inv, rows, styles)

    def _selected_inv_drug(self):
        idx = ui_theme.selected_row_index(self.tree_inv)
        if idx is None or idx >= len(self.inv_rows):
            messagebox.showinfo("تنبيه", "اختر دواء من القائمة أولاً", parent=self)
            return None
        return self.inv_rows[idx]

    def barcode_label_dialog(self):
        drug = self._selected_inv_drug()
        if drug:
            self.barcode_label_dialog_for(drug["id"])

    def barcode_label_dialog_for(self, drug_id):
        drug = self.db.get_drug(drug_id)
        if not drug:
            messagebox.showerror("خطأ", "الدواء غير موجود", parent=self)
            return
        was_auto = not self.db.drug_barcode(drug_id)
        try:
            bc = self.db.ensure_drug_barcode(drug_id)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        pharmacy = self.db.get_setting("pharmacy_name", "صيدلية المؤسسة") or "صيدلية المؤسسة"
        phone = self.db.get_setting("pharmacy_phone", "") or ""

        win = QDialog(self)
        win.setWindowTitle("ملصق باركود الصيدلية — %s" % drug["trade_en"])
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 480, 620)
        root_lay = QVBoxLayout(win)
        root_lay.setContentsMargins(14, 12, 14, 12)
        root_lay.setSpacing(8)

        scroll, _in, form = ui_theme.make_scroll_page("labelScroll")
        root_lay.addWidget(scroll, 1)

        form.addWidget(SubtitleLabel(drug["trade_en"]))
        if drug.get("trade_ar"):
            form.addWidget(BodyLabel(drug["trade_ar"]))
        form.addWidget(CaptionLabel("التركيز: %s   الشكل: %s" % (drug.get("strength", "") or "—", drug.get("form", "") or "—")))
        bc_lbl = BodyLabel("الباركود: %s%s" % (bc, "  (باركود داخلي مولَّد تلقائياً — ثابت لهذا الدواء)" if was_auto else ""))
        bc_lbl.setWordWrap(True)
        form.addWidget(bc_lbl)

        try:
            _png = ean13_png_bytes(bc, scale=3, height=56)
            pix = QPixmap()
            pix.loadFromData(_png, "PNG")
            img_lbl = QLabel()
            img_lbl.setPixmap(pix)
            img_lbl.setAlignment(Qt.AlignCenter)
            img_lbl.setStyleSheet("background-color: white; padding: 8px; border-radius: 6px;")
            form.addWidget(img_lbl)
            code_lbl = CaptionLabel(bc)
            code_lbl.setAlignment(Qt.AlignCenter)
            form.addWidget(code_lbl)
        except Exception:
            form.addWidget(CaptionLabel("(معاينة الأعمدة غير متاحة — رقم الباركود مطبوع كنص)"))

        form.addWidget(StrongBodyLabel("اختر ما يظهر على الملصق:"))
        vars_ = {}
        for _key, _lbl in (
            ("name", "اسم الدواء"), ("pharmacy", "اسم الصيدلية"),
            ("price", "السعر"), ("phone", "تليفون الصيدلية"),
            ("barcode", "الباركود (أعمدة + رقم)"),
        ):
            chk = CheckBox(_lbl)
            chk.setChecked(True)
            vars_[_key] = chk
            form.addWidget(chk)

        sel_row = QHBoxLayout()
        b_all = PushButton("✅ اختيار الكل")
        b_all.clicked.connect(lambda: [c.setChecked(True) for c in vars_.values()])
        b_none = PushButton("❌ إلغاء الكل")
        b_none.clicked.connect(lambda: [c.setChecked(False) for c in vars_.values()])
        sel_row.addWidget(b_all)
        sel_row.addWidget(b_none)
        sel_row.addStretch(1)
        form.addLayout(sel_row)

        form.addWidget(StrongBodyLabel("حجم الملصق:"))
        sz_state = {"size": "50x25"}
        sz_row = QHBoxLayout()
        grp_sz = QButtonGroup(win)
        for val, lbl_txt in (("50x25", "50 × 25 مم"), ("38x25", "38 × 25 مم")):
            rb = RadioButton(lbl_txt)
            if val == "50x25":
                rb.setChecked(True)
            rb.toggled.connect(lambda c, v=val: sz_state.__setitem__("size", v) if c else None)
            grp_sz.addButton(rb)
            sz_row.addWidget(rb)
        sz_row.addStretch(1)
        form.addLayout(sz_row)

        form.addWidget(BodyLabel("عدد النسخ:"))
        e_copies = LineEdit()
        e_copies.setText("1")
        e_copies.setFixedWidth(90)
        form.addWidget(e_copies)

        if not phone:
            hint = CaptionLabel("⚠️ لم يُسجَّل تليفون للصيدلية بعد — أضفه من الإعدادات ليظهر على الملصق.")
            hint.setWordWrap(True)
            form.addWidget(hint)

        def do_print_label():
            if not any(c.isChecked() for c in vars_.values()):
                messagebox.showerror("خطأ", "اختر عنصراً واحداً على الأقل للملصق", parent=win)
                return
            try:
                copies = int(e_copies.text() or "1")
            except ValueError:
                messagebox.showerror("خطأ", "عدد النسخ يجب أن يكون رقماً", parent=win)
                return
            copies = max(1, min(50, copies))
            name = drug["trade_en"] + ((" — " + drug["trade_ar"]) if drug.get("trade_ar") else "")
            price_txt = "السعر: %s" % money(drug["sell_price"])
            extra = []
            if vars_["pharmacy"].isChecked():
                extra.append(pharmacy)
            if vars_["phone"].isChecked() and phone:
                extra.append("تليفون: %s" % phone)
            lines = list(extra)
            if vars_["name"].isChecked():
                lines.append(name)
            if vars_["price"].isChecked():
                lines.append(price_txt)
            if vars_["barcode"].isChecked():
                lines.append("الباركود: %s" % bc)
            png_path = ""
            if vars_["barcode"].isChecked() and receipt_printer is not None:
                try:
                    png_path = receipt_printer.save_bytes(BASE, "label_%s.png" % bc, ean13_png_bytes(bc, scale=3, height=64))
                except Exception:
                    png_path = ""
            escpos_data = None
            if receipt_printer is not None:
                ps = self._printer_settings()
                escpos_data = receipt_printer.build_escpos_label(
                    name if vars_["name"].isChecked() else "",
                    price_txt if vars_["price"].isChecked() else "",
                    bc if vars_["barcode"].isChecked() else "",
                    size=sz_state["size"],
                    width_chars=receipt_printer.width_chars_for(ps["width"]),
                    cp864_page=ps["cp864"], cp1256_page=ps["cp1256"],
                    extra_lines=tuple(extra),
                    show_barcode=vars_["barcode"].isChecked(),
                )
            ok, msg, path = (True, "", "")
            for _i in range(copies):
                ok, msg, path = self._print_lines(lines, "label_%s.txt" % bc, is_cash=False, escpos_data=escpos_data)
                if not ok:
                    break
            if ok:
                self.show_banner("🏷️ طُبع ملصق %s ×%d — %s" % (drug["trade_en"], copies, msg), "success")
                if png_path:
                    self.show_banner("صورة الباركود (PNG): %s" % png_path, "info")
                win.accept()
            else:
                messagebox.showinfo("لم يُطبع بعد", "حُفظ في:\n%s\n%s" % (path, msg), parent=win)

        b_print = PrimaryPushButton("🏷️ طباعة الملصق")
        b_print.clicked.connect(do_print_label)
        root_lay.addWidget(b_print)
        win.exec()

    def drug_dialog(self, drug=None, prefill_barcode=""):
        if drug is None and not self.is_admin:
            messagebox.showerror("صلاحيات", "الكاشير لا يستطيع إضافة أدوية أو تغيير الأسعار — هذه صلاحية المدير فقط", parent=self)
            return
        if drug is not None and not self.is_admin:
            messagebox.showerror("صلاحيات", "تعديل الأسعار صلاحية المدير فقط", parent=self)
            return

        win = QDialog(self)
        win.setWindowTitle("تعديل دواء" if drug else "إضافة دواء جديد")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 520, 740)

        root_lay = QVBoxLayout(win)
        root_lay.setContentsMargins(14, 12, 14, 12)
        root_lay.setSpacing(8)
        scroll, _in, form = ui_theme.make_scroll_page("drugFormScroll")
        root_lay.addWidget(scroll, 1)

        fields = {}
        labels = [
            ("trade_en", "الاسم التجاري (إنجليزي) *"),
            ("trade_ar", "الاسم التجاري (عربي)"),
            ("scientific", "المادة الفعالة"),
            ("company", "الشركة"),
            ("form", "الشكل الصيدلاني (Tablets / Syrup / Cream...)"),
            ("strength", "التركيز (مثال: 250 أو 250mg)"),
            ("category", "الفئة"),
            ("strips_per_box", "عدد الشرائط في العلبة"),
            ("tablets_per_strip", "عدد الحبات في الشريط"),
            ("buy_price", "سعر الشراء (للعلبة)"),
            ("sell_price", "سعر البيع (للعلبة)"),
            ("min_stock", "الحد الأدنى للمخزون (علبة)"),
            ("barcode", "باركود العلبة (GTIN) — امسح بالماسح ثم Enter"),
        ]
        for key, lbl in labels:
            form.addWidget(CaptionLabel(lbl))
            val = ""
            if drug:
                val = str(drug.get(key, ""))
            elif key == "barcode":
                val = prefill_barcode
            elif key in ("strips_per_box", "tablets_per_strip"):
                val = "1"
            elif key == "min_stock":
                val = "5"

            if key == "form":
                cb = EditableComboBox()
                cb.addItems(list(self.FORM_AR.values()))
                cb.setText(self.FORM_AR.get(str(val).strip(), str(val)))
                form.addWidget(cb)
                fields[key] = cb
            elif key == "barcode":
                row = QHBoxLayout()
                ent = LineEdit()
                ent.setText(val)
                row.addWidget(ent, 1)
                b_cam = PrimaryPushButton("📷 مسح")
                b_cam.clicked.connect(lambda _c=False, e=ent: self._barcode_scan_dialog(e))
                row.addWidget(b_cam)
                form.addLayout(row)
                fields[key] = ent
            else:
                ent = LineEdit()
                ent.setText(val)
                form.addWidget(ent)
                fields[key] = ent

        form.addWidget(BodyLabel("خصم الدواء الافتراضي (يُطبق تلقائياً عند البيع):"))
        disc_state = {"type": "none"}
        if drug:
            _dt = drug.get("discount_type") or "none"
            disc_state["type"] = _dt if _dt in ("none", "percent", "amount") else "none"
        d_row = QHBoxLayout()
        d_grp = QButtonGroup(win)
        for val, lbl_txt in (("none", "بدون خصم"), ("percent", "نسبة %"), ("amount", "مبلغ ثابت (ج.م) لكل وحدة")):
            rb = RadioButton(lbl_txt)
            if val == disc_state["type"]:
                rb.setChecked(True)
            rb.toggled.connect(lambda chk, v=val: disc_state.__setitem__("type", v) if chk else None)
            d_grp.addButton(rb)
            d_row.addWidget(rb)
        d_row.addStretch(1)
        form.addLayout(d_row)

        form.addWidget(CaptionLabel("قيمة الخصم:"))
        e_disc_val = LineEdit()
        e_disc_val.setText(str(drug.get("discount_value") or 0) if drug else "0")
        form.addWidget(e_disc_val)

        def save():
            if not fields["trade_en"].text().strip():
                messagebox.showerror("خطأ", "الاسم التجاري مطلوب", parent=win)
                return
            data = {k: v.text().strip() for k, v in fields.items()}
            data["discount_type"] = disc_state["type"]
            data["discount_value"] = e_disc_val.text().strip() or "0"
            try:
                data["strips_per_box"] = strict_int(data["strips_per_box"], "عدد الشرائط في العلبة") or 1
                data["tablets_per_strip"] = strict_int(data["tablets_per_strip"], "عدد الحبات في الشريط") or 1
                data["buy_price"] = strict_float(data["buy_price"], "سعر الشراء") or 0.0
                data["sell_price"] = strict_float(data["sell_price"], "سعر البيع") or 0.0
                data["min_stock"] = strict_int(data["min_stock"], "الحد الأدنى للمخزون") or 5
                data["discount_value"] = strict_float(data["discount_value"], "قيمة الخصم") or 0.0
            except ValueError as e:
                messagebox.showerror("خطأ", str(e), parent=win)
                return
            try:
                if drug:
                    self.db.update_drug(drug["id"], data)
                    if data["barcode"]:
                        self.db.link_barcode(data["barcode"], drug["id"])
                    saved_id = drug["id"]
                else:
                    saved_id = self.db.add_drug(data)
            except ValueError as e:
                messagebox.showerror("خطأ", str(e), parent=win)
                return
            win.accept()
            self.inv_refresh()
            self.pos_search_refresh()
            if messagebox.askyesno("تم الحفظ", "تم الحفظ بنجاح.\nهل تريد طباعة ملصق باركود الصيدلية لهذا الدواء الآن؟", parent=self):
                self.barcode_label_dialog_for(saved_id)
            else:
                messagebox.showinfo("تم", "تم الحفظ بنجاح", parent=self)

        fields["barcode"].returnPressed.connect(save)
        b_save = PrimaryPushButton("💾 حفظ")
        b_save.clicked.connect(save)
        root_lay.addWidget(b_save)
        win.exec()

    def drug_edit_selected(self):
        d = self._selected_inv_drug()
        if d:
            self.drug_dialog(drug=d)

    def show_batches(self):
        d = self._selected_inv_drug()
        if not d:
            return
        win = QDialog(self)
        win.setWindowTitle("تشغيلات: %s" % d["trade_en"])
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 640, 380)
        lay = QVBoxLayout(win)
        lay.setContentsMargins(14, 12, 14, 12)
        tv = TableWidget()
        ui_theme.configure_table(tv, ("رقم التشغيلة", "تاريخ الصلاحية", "الكمية (حبة/وحدة)", "سعر شراء الوحدة"), (140, 140, 150, 140), stretch_cols=(0,), min_height=240)
        rows = [(b["batch_no"], b["expiry"], b["qty_units"], money(b["buy_price_unit"]) if self.is_admin else "—") for b in self.db.batches_for(d["id"])]
        ui_theme.set_table_rows(tv, rows)
        lay.addWidget(tv, 1)
        lay.addWidget(CaptionLabel("البيع يأخذ دائماً من أقرب تشغيلة تنتهي أولاً (FEFO)."))
        win.exec()

    def _barcode_scan_dialog(self, target):
        win = QDialog(self)
        win.setWindowTitle("📷 مسح باركود العلبة")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 520, 400)
        lay = QVBoxLayout(win)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        state = {"rid": None}
        timer = QTimer(win)
        timer.setInterval(1000)

        def _cleanup():
            timer.stop()
            if state["rid"] is not None and mobile_server:
                try:
                    mobile_server.scan_request_cancel(state["rid"])
                except Exception:
                    pass
                state["rid"] = None

        def _fill_and_close(code):
            code = (code or "").strip()
            if not code:
                return
            try:
                target.setText(code)
            except Exception:
                pass
            _cleanup()
            win.accept()
            self.show_banner("تم مسح الباركود: %s" % code, "success")

        lay.addWidget(StrongBodyLabel("١) ماسح الباركود (USB)"))
        lay.addWidget(CaptionLabel("الماسح يكتب مثل لوحة المفاتيح — المؤشر جاهز بالأسفل، امسح الآن."))
        usb_entry = LineEdit()
        usb_entry.returnPressed.connect(lambda: _fill_and_close(usb_entry.text()))
        lay.addWidget(usb_entry)
        lay.addWidget(ui_theme.make_separator())

        lay.addWidget(StrongBodyLabel("٢) كاميرا الموبايل"))
        status_lbl = CaptionLabel("اطلب المسح ثم امسح من صفحة الموبايل — سيظهر الكود هنا.")
        status_lbl.setWordWrap(True)
        lay.addWidget(status_lbl)

        def _poll_phone():
            rid = state["rid"]
            if rid is None:
                timer.stop()
                return
            try:
                res = mobile_server.scan_request_poll(rid) if mobile_server else None
            except Exception:
                res = None
            if not res:
                status_lbl.setText("تعذّر قراءة حالة الطلب — أعد المحاولة.")
                state["rid"] = None
                timer.stop()
                return
            if res.get("code"):
                _fill_and_close(res["code"])
                return
            if not res.get("pending"):
                status_lbl.setText("انتهت مهلة الطلب — اضغط الزر من جديد.")
                state["rid"] = None
                timer.stop()

        timer.timeout.connect(_poll_phone)

        def _request_phone_scan():
            srv = getattr(self, "mobile_server", None)
            if srv is None or not getattr(srv, "running", False):
                status_lbl.setText("سيرفر الموبايل متوقف — شغّله أولاً من تبويب «📱 موبايل».")
                return
            try:
                state["rid"] = mobile_server.scan_request_open()
            except Exception:
                status_lbl.setText("تعذّر فتح طلب المسح — أعد المحاولة.")
                return
            status_lbl.setText("افتح صفحة الموبايل — سيظهر تنبيه «الكمبيوتر يطلب مسح باركود»…")
            timer.start()

        btn_phone = PrimaryPushButton("📱 اطلب المسح من الموبايل")
        btn_phone.clicked.connect(_request_phone_scan)
        lay.addWidget(btn_phone)
        lay.addStretch(1)

        btn_cancel = PushButton("إلغاء")
        btn_cancel.clicked.connect(win.reject)
        lay.addWidget(btn_cancel)
        win.finished.connect(_cleanup)
        usb_entry.setFocus()
        win.exec()

    def adjust_stock_dialog(self):
        d = self._selected_inv_drug()
        if not d:
            return
        if not self.is_admin:
            messagebox.showerror("صلاحيات", "تعديل المخزون يحتاج موافقة المدير", parent=self)
            return
        qty = messagebox.askinteger("جرد / تعديل", "أدخل فرق الكمية بالحبة/وحدة (+ زيادة، - نقص) لدواء %s:" % d["trade_en"], parent=self)
        if qty is None or qty == 0:
            return
        reason = messagebox.askstring("سبب التعديل", "سبب التعديل (جرد / تالف / ...):", parent=self) or "جرد"
        try:
            self.db.adjust_stock(d["id"], qty, reason, self.username)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        messagebox.showinfo("تم", "تم تعديل المخزون", parent=self)
        self.inv_refresh()

    def show_shortages(self):
        rows = self.db.low_stock()
        lines = ["قائمة النواقص (%d صنف):\n" % len(rows)]
        for d in rows:
            lines.append("- %s %s — المخزون %.1f علبة، الحد الأدنى %s" % (d["trade_en"], d.get("strength", ""), d.get("stock_boxes", 0), d["min_stock"]))
        if not rows:
            lines.append("لا توجد نواقص حالياً ✅")
        messagebox.TextViewerDialog(self, "قائمة النواقص", "\n".join(lines)).exec()

    def show_expiry(self):
        rows = self.db.near_expiry(90)
        n_exp = sum(1 for b in rows if (b["expiry"] or "") < date.today().isoformat())
        lines = ["أصناف تقترب صلاحيتها خلال 90 يوم (%d تشغيلة، منها %d منتهية):\n" % (len(rows), n_exp)]
        for b in rows:
            expired = (b["expiry"] or "") < date.today().isoformat()
            lines.append("- %s — تشغيلة %s تنتهي %s، الكمية %s وحدة%s" % (
                b["trade_en"], b["batch_no"], b["expiry"], b["qty_units"],
                "  ⛔ منتهية — اعزلها ولا تبعها" if expired else "",
            ))
        if not rows:
            lines.append("لا توجد أصناف قريبة الانتهاء ✅")
        messagebox.TextViewerDialog(self, "قرب انتهاء الصلاحية (90 يوم)", "\n".join(lines), width=760).exec()

    def export_drugs(self):
        path = messagebox.get_save_filename(parent=self, initialfile="drugs_export.csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        n = self.db.export_drugs_csv(path)
        messagebox.showinfo("تم", "تم تصدير %d دواء إلى:\n%s" % (n, path), parent=self)

    # =========================================================================
    # Purchases & Suppliers (Tab 3)
    # =========================================================================
    def build_purchases(self, outer=None):
        container = outer or self._tab_widgets[3]
        outer_lay = QVBoxLayout(container)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll, _inner, tab = ui_theme.make_scroll_page("purInner")
        outer_lay.addWidget(scroll)

        top_card = CardWidget()
        top_v = QVBoxLayout(top_card)
        top_v.setContentsMargins(12, 10, 12, 10)
        top_v.setSpacing(8)

        r1 = QHBoxLayout()
        r1.setSpacing(6)
        r1.addWidget(StrongBodyLabel("المورد:"))
        self.cb_supplier = ComboBox()
        self.cb_supplier.setMinimumWidth(140)
        sups = [s["name"] for s in self.db.suppliers()]
        self.cb_supplier.addItems(sups)
        r1.addWidget(self.cb_supplier)

        r1.addWidget(BodyLabel("رقم المورد #:"))
        self.e_sup_id = LineEdit()
        self.e_sup_id.setFixedWidth(70)
        r1.addWidget(self.e_sup_id)
        b_sid = PushButton("🔎")
        b_sid.clicked.connect(self.supplier_id_search)
        r1.addWidget(b_sid)

        for lbl, fn in [
            ("➕ مورد جديد", self.add_supplier_dialog),
            ("💰 دفع للمورد", self.pay_supplier_dialog),
            ("↩️ مرتجع مشتريات", self.purchase_return_dialog),
        ]:
            b = PushButton(lbl)
            b.clicked.connect(fn)
            r1.addWidget(b)

        r1.addWidget(BodyLabel("رقم الفاتورة:"))
        self.e_pur_inv = LineEdit()
        self.e_pur_inv.setFixedWidth(120)
        r1.addWidget(self.e_pur_inv)

        r1.addWidget(BodyLabel("المدفوع:"))
        self.e_pur_paid = LineEdit()
        self.e_pur_paid.setText("0")
        self.e_pur_paid.setFixedWidth(95)
        r1.addWidget(self.e_pur_paid)
        r1.addStretch(1)
        top_v.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(10)
        self.btn_pur_save_top = PrimaryPushButton("💾 حفظ فاتورة الشراء وتحديث المخزون")
        self.btn_pur_save_top.clicked.connect(self.pur_save)
        r2.addWidget(self.btn_pur_save_top)
        b_photo = PushButton("📷 من صورة فاتورة")
        b_photo.clicked.connect(self.invoice_photo_intake)
        r2.addWidget(b_photo)
        self.lbl_pur_total_top = QLabel("إجمالي فاتورة الشراء: 0.00 ج.م")
        self.lbl_pur_total_top.setFont(ui_theme.qfont(14, bold=True))
        self.lbl_pur_total_top.setStyleSheet(f"color: {self.pal['success']}; background: transparent;")
        r2.addWidget(self.lbl_pur_total_top)
        r2.addStretch(1)
        top_v.addLayout(r2)
        tab.addWidget(top_card)

        mid_card = CardWidget()
        mid = QVBoxLayout(mid_card)
        mid.setContentsMargins(12, 12, 12, 12)
        mid.setSpacing(8)
        mid.addWidget(StrongBodyLabel("ابحث عن دواء لإضافته للفاتورة:"))

        srow = QHBoxLayout()
        self.e_pur_search = SearchLineEdit()
        self.e_pur_search.setPlaceholderText("بحث عن دواء...")
        self.e_pur_search.textChanged.connect(lambda _t: self._debounce("pur_search", 120, self.pur_search_refresh))
        self.e_pur_search.returnPressed.connect(self.pur_search_refresh)
        srow.addWidget(self.e_pur_search, 1)
        b_ps = PushButton("بحث")
        b_ps.clicked.connect(self.pur_search_refresh)
        srow.addWidget(b_ps)
        mid.addLayout(srow)

        self.list_pur = self.make_drug_search_tree(min_height=190)
        mid.addWidget(self.list_pur)

        frow1 = QHBoxLayout()
        frow1.setSpacing(8)
        for lbl, var, w in [("عدد العلب:", "qty", 90), ("سعر شراء العلبة:", "buy", 110), ("سعر بيع العلبة (اختياري):", "sell", 110)]:
            frow1.addWidget(BodyLabel(lbl))
            ent = LineEdit()
            ent.setFixedWidth(w)
            frow1.addWidget(ent)
            setattr(self, "e_pur_" + var, ent)
        for lbl, var, w in [("رقم التشغيلة:", "batch", 120), ("الصلاحية (YYYY-MM-DD):", "exp", 120)]:
            frow1.addWidget(BodyLabel(lbl))
            ent = LineEdit()
            ent.setFixedWidth(w)
            frow1.addWidget(ent)
            setattr(self, "e_pur_" + var, ent)
        frow1.addStretch(1)
        self.e_pur_qty.setText("1")
        self.e_pur_exp.setText("2027-12-31")
        mid.addLayout(frow1)

        b_add_ln = PrimaryPushButton("➕ إضافة السطر لفاتورة الشراء")
        b_add_ln.clicked.connect(self.pur_add_line)
        mid.addWidget(b_add_ln, 0, Qt.AlignLeft)

        self.tree_pur = TableWidget()
        ui_theme.configure_table(self.tree_pur, ("الدواء", "عدد العلب", "سعر الشراء", "الإجمالي"), (300, 110, 140, 150), stretch_cols=(0,), min_height=200)
        self.tree_pur.cellDoubleClicked.connect(lambda _r, _c: self.pur_edit_line())
        mid.addWidget(self.tree_pur, 1)

        pb_row = QHBoxLayout()
        self.btn_pur_edit_line = PushButton("✏️ تعديل السطر المحدد")
        self.btn_pur_edit_line.clicked.connect(self.pur_edit_line)
        pb_row.addWidget(self.btn_pur_edit_line)
        self.btn_pur_delete_line = PushButton("🗑 حذف السطر المحدد")
        self.btn_pur_delete_line.setStyleSheet(f"color: {self.pal['danger']}; font-weight: bold;")
        self.btn_pur_delete_line.clicked.connect(self.pur_delete_line)
        pb_row.addWidget(self.btn_pur_delete_line)
        pb_row.addStretch(1)
        self.lbl_pur_total = QLabel("إجمالي فاتورة الشراء: 0.00 ج.م")
        self.lbl_pur_total.setFont(ui_theme.qfont(14, bold=True))
        self.lbl_pur_total.setStyleSheet(f"color: {self.pal['success']}; background: transparent;")
        pb_row.addWidget(self.lbl_pur_total)
        b_save_bot = PrimaryPushButton("💾 حفظ فاتورة الشراء وتحديث المخزون")
        b_save_bot.clicked.connect(self.pur_save)
        pb_row.addWidget(b_save_bot)
        mid.addLayout(pb_row)
        tab.addWidget(mid_card, 1)

        self.pur_search_refresh()

    def invoice_photo_intake(self):
        import invoice_intake_ui
        invoice_intake_ui.open_invoice_intake(self)

    def pur_search_refresh(self):
        if not hasattr(self, "list_pur"):
            return
        q = self.e_pur_search.text() if hasattr(self, "e_pur_search") else ""
        self.pur_results = self.db.search_drugs(q, limit=40)
        self.list_pur.fill(self.pur_results)

    def pur_validate_line(self, qty_raw, buy_raw, sell_raw, expiry_raw):
        try:
            qty = strict_float(qty_raw, "عدد العلب")
        except ValueError as e:
            return None, None, None, None, str(e)
        if qty is None or qty <= 0 or qty != int(qty):
            return None, None, None, None, "عدد العلب يجب أن يكون عدداً صحيحاً أكبر من صفر"
        try:
            buy = strict_float(buy_raw, "سعر الشراء")
        except ValueError as e:
            return None, None, None, None, str(e)
        if buy is None or buy <= 0:
            return None, None, None, None, "أدخل سعر شراء أكبر من صفر"
        sell_txt = str(sell_raw or "").strip()
        sell = None
        if sell_txt:
            try:
                sell = strict_float(sell_txt, "سعر البيع")
            except ValueError as e:
                return None, None, None, None, str(e)
            if sell is None or sell < 0:
                return None, None, None, None, "سعر البيع غير صالح"
        expiry = str(expiry_raw or "").strip() or "2027-12-31"
        try:
            exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        except Exception:
            return None, None, None, None, "تاريخ الصلاحية غير صالح — استخدم الصيغة YYYY-MM-DD"
        if exp_date < date.today():
            return None, None, None, None, "تاريخ الصلاحية في الماضي — لا يمكن استلام تشغيلة منتهية"
        return int(qty), buy, sell, expiry, None

    def pur_refresh_table(self):
        if not hasattr(self, "tree_pur"):
            return
        rows = []
        total = 0.0
        for line in self.purchase_lines:
            rows.append((
                line["drug"]["trade_en"],
                line["qty_boxes"],
                money(line["buy_price"]),
                money(line["qty_boxes"] * line["buy_price"]),
            ))
            total += line["qty_boxes"] * line["buy_price"]
        ui_theme.set_table_rows(self.tree_pur, rows)
        txt = "إجمالي فاتورة الشراء: %s" % money(total)
        self.lbl_pur_total.setText(txt)
        if hasattr(self, "lbl_pur_total_top"):
            self.lbl_pur_total_top.setText(txt)

    def pur_selected_line_index(self):
        return ui_theme.selected_row_index(self.tree_pur)

    def pur_add_line(self):
        d = self.list_pur.selected_drug()
        if not d:
            messagebox.showinfo("تنبيه", "اختر دواء أولاً", parent=self)
            return
        qty, buy, sell, expiry, err = self.pur_validate_line(
            self.e_pur_qty.text(), self.e_pur_buy.text(), self.e_pur_sell.text(), self.e_pur_exp.text()
        )
        if err:
            messagebox.showerror("خطأ", err, parent=self)
            return
        batch = self.e_pur_batch.text().strip() or "B-%s" % date.today().isoformat()
        for line in self.purchase_lines:
            if (
                line["drug"]["id"] == d["id"]
                and line["batch_no"] == batch
                and line["expiry"] == expiry
                and line["buy_price"] == buy
                and line.get("sell_price") == sell
            ):
                line["qty_boxes"] += qty
                self.pur_refresh_table()
                messagebox.showinfo(
                    "تم الدمج",
                    "الدواء موجود بالفعل في الفاتورة بنفس التشغيلة والأسعار — تمت إضافة الكمية للسطر الموجود (أصبح %s علبة)."
                    % line["qty_boxes"],
                    parent=self,
                )
                return
        self.purchase_lines.append({
            "drug": d, "qty_boxes": qty, "buy_price": buy,
            "sell_price": sell, "batch_no": batch, "expiry": expiry,
        })
        self.pur_refresh_table()

    def pur_delete_line(self):
        idx = self.pur_selected_line_index()
        if idx is None:
            messagebox.showinfo("تنبيه", "اختر سطراً من جدول الفاتورة أولاً", parent=self)
            return
        del self.purchase_lines[idx]
        self.pur_refresh_table()

    def pur_edit_line(self):
        idx = self.pur_selected_line_index()
        if idx is None:
            messagebox.showinfo("تنبيه", "اختر سطراً من جدول الفاتورة أولاً", parent=self)
            return
        line = self.purchase_lines[idx]
        win = QDialog(self)
        win.setWindowTitle("تعديل سطر فاتورة الشراء — %s" % line["drug"]["trade_en"])
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        lay = QVBoxLayout(win)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        fields = {}
        for key, lbl, val in [
            ("qty", "عدد العلب:", str(int(line["qty_boxes"]))),
            ("buy", "سعر شراء العلبة:", str(line["buy_price"])),
            ("sell", "سعر بيع العلبة (اختياري):", "" if line.get("sell_price") is None else str(line["sell_price"])),
            ("batch", "رقم التشغيلة:", str(line["batch_no"])),
            ("exp", "تاريخ الصلاحية (YYYY-MM-DD):", str(line["expiry"])),
        ]:
            lay.addWidget(CaptionLabel(lbl))
            ent = LineEdit()
            ent.setText(val)
            lay.addWidget(ent)
            fields[key] = ent

        def save_edit():
            qty, buy, sell, expiry, err = self.pur_validate_line(
                fields["qty"].text(), fields["buy"].text(), fields["sell"].text(), fields["exp"].text()
            )
            if err:
                messagebox.showerror("خطأ", err, parent=win)
                return
            line["qty_boxes"] = qty
            line["buy_price"] = buy
            line["sell_price"] = sell
            line["batch_no"] = fields["batch"].text().strip() or line["batch_no"]
            line["expiry"] = expiry
            self.pur_refresh_table()
            win.accept()

        btns = QHBoxLayout()
        b_save = PrimaryPushButton("💾 حفظ التعديل")
        b_save.clicked.connect(save_edit)
        b_cancel = PushButton("إلغاء")
        b_cancel.clicked.connect(win.reject)
        btns.addWidget(b_save)
        btns.addWidget(b_cancel)
        lay.addLayout(btns)
        ui_theme.fit_dialog_widget(win, 420, 410)
        win.exec()

    def pur_save(self):
        if not self.purchase_lines:
            messagebox.showinfo("تنبيه", "لا توجد أسطر في فاتورة الشراء", parent=self)
            return
        name = self.cb_supplier.currentText().strip()
        sup = next((s for s in self.db.suppliers() if s["name"] == name), None)
        if not sup:
            messagebox.showerror("خطأ", "اختر مورد موجود أو أضف مورد جديد", parent=self)
            return
        inv_no = self.e_pur_inv.text().strip() or "PUR-%s" % date.today().isoformat()
        try:
            paid_amt = strict_float(self.e_pur_paid.text(), "المبلغ المدفوع للمورد")
            paid_amt = paid_amt if paid_amt is not None else 0.0
            pid, total = self.db.record_purchase(sup["id"], inv_no, self.purchase_lines, paid=paid_amt, user=self.username)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        messagebox.showinfo("تم", "تم حفظ فاتورة الشراء #%d\nالإجمالي: %s\nتم تحديث المخزون والأسعار" % (pid, money(total)), parent=self)
        self.purchase_lines = []
        self.pur_refresh_table()
        self.inv_refresh()
        self.pos_search_refresh()

    def supplier_id_search(self):
        raw = self.e_sup_id.text().strip().lstrip("#")
        if not raw:
            messagebox.showinfo("تنبيه", "اكتب رقم المورد أولاً (مثال: 12)", parent=self)
            return
        sup = self.db.get_supplier(raw)
        if not sup:
            messagebox.showinfo("المورد غير موجود", "لا يوجد مورد بالرقم #%s — راجع الرقم أو أضف مورد جديد" % raw, parent=self)
            return
        idx = self.cb_supplier.findText(sup["name"])
        if idx >= 0:
            self.cb_supplier.setCurrentIndex(idx)
        self.show_banner("المورد #%d: %s — دينه الحالي: %s" % (sup["id"], sup["name"], money(sup.get("balance") or 0)), "info")

    def add_supplier_dialog(self):
        name = messagebox.askstring("مورد جديد", "اسم المورد:", parent=self)
        if not name:
            return
        phone = messagebox.askstring("مورد جديد", "هاتف المورد (اختياري):", parent=self) or ""
        nid = self.db.add_supplier(name.strip(), phone)
        self.cb_supplier.clear()
        self.cb_supplier.addItems([s["name"] for s in self.db.suppliers()])
        idx = self.cb_supplier.findText(name.strip())
        if idx >= 0:
            self.cb_supplier.setCurrentIndex(idx)
        messagebox.showinfo("تم", "تمت إضافة المورد #%d" % nid, parent=self)

    def pay_supplier_dialog(self):
        name = self.cb_supplier.currentText().strip()
        sup = next((s for s in self.db.suppliers() if s["name"] == name), None)
        if not sup:
            messagebox.showinfo("تنبيه", "اختر مورد أولاً", parent=self)
            return
        amt = messagebox.askfloat(
            "دفع للمورد #%d" % sup["id"],
            "المبلغ المدفوع لـ %s (دينه الحالي: %s):" % (name, money(sup["balance"])),
            parent=self,
        )
        if amt is None or amt <= 0:
            return
        try:
            self.db.pay_supplier(sup["id"], amt, self.username)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        messagebox.showinfo("تم", "تم تسجيل الدفع", parent=self)

    def purchase_return_dialog(self):
        sups = self.db.suppliers()
        if not sups:
            messagebox.showinfo("تنبيه", "أضف مورد أولاً", parent=self)
            return
        win = QDialog(self)
        win.setWindowTitle("↩️ مرتجع مشتريات")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 640, 580)
        lay = QVBoxLayout(win)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        lay.addWidget(CaptionLabel("المورد:"))
        cb_sup = ComboBox()
        cb_sup.addItems([s["name"] for s in sups])
        cur = self.cb_supplier.currentText().strip() if hasattr(self, "cb_supplier") else ""
        if cur:
            idx = cb_sup.findText(cur)
            if idx >= 0:
                cb_sup.setCurrentIndex(idx)
        lay.addWidget(cb_sup)

        lay.addWidget(CaptionLabel("ابحث عن الدواء:"))
        e_search = SearchLineEdit()
        lay.addWidget(e_search)
        lst = self.make_drug_search_tree(min_height=180)
        lay.addWidget(lst, 1)

        lay.addWidget(CaptionLabel("التشغيلة (اتركها فارغة = الأقرب انتهاءً أولاً FEFO):"))
        cb_batch = ComboBox()
        cb_batch.addItem("— الأقرب انتهاءً أولاً —")
        lay.addWidget(cb_batch)

        row = QHBoxLayout()
        row.addWidget(BodyLabel("الكمية:"))
        e_qty = LineEdit()
        e_qty.setText("1")
        e_qty.setFixedWidth(90)
        row.addWidget(e_qty)
        row.addWidget(BodyLabel("الوحدة:"))
        cb_unit = ComboBox()
        cb_unit.addItems(["box", "strip", "pill"])
        row.addWidget(cb_unit)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(CaptionLabel("السبب (منتهي / قارب على الانتهاء / تالف):"))
        e_reason = LineEdit()
        e_reason.setText("منتهي الصلاحية")
        lay.addWidget(e_reason)

        state = {"batches": []}

        def refresh_drugs(_t=""):
            res = self.db.search_drugs(e_search.text(), limit=40)
            lst.fill(res)
            state["batches"] = []
            cb_batch.clear()
            cb_batch.addItem("— الأقرب انتهاءً أولاً —")

        def on_drug(*_):
            d = lst.selected_drug()
            if not d:
                return
            units = allowed_units(d)
            cb_unit.clear()
            cb_unit.addItems(units)
            if "box" in units:
                cb_unit.setCurrentText("box")
            state["batches"] = [b for b in self.db.batches_for(d["id"]) if b["qty_units"] > 0]
            vals = ["— الأقرب انتهاءً أولاً —"] + [
                "#%d | %s | انتهاء %s | %d وحدة | شراء %s/وحدة"
                % (b["id"], b["batch_no"] or "—", b["expiry"] or "بدون تاريخ", b["qty_units"], money(b["buy_price_unit"]))
                for b in state["batches"]
            ]
            cb_batch.clear()
            cb_batch.addItems(vals)

        e_search.textChanged.connect(refresh_drugs)
        lst.itemSelectionChanged.connect(on_drug)
        refresh_drugs()

        def do_save():
            d = lst.selected_drug()
            if not d:
                messagebox.showinfo("تنبيه", "اختر الدواء أولاً", parent=win)
                return
            name = cb_sup.currentText().strip()
            sup = next((s for s in sups if s["name"] == name), None)
            if not sup:
                messagebox.showerror("خطأ", "اختر مورد موجود", parent=win)
                return
            try:
                qty = float(e_qty.text())
            except ValueError:
                messagebox.showerror("خطأ", "كمية غير صالحة", parent=win)
                return
            if qty <= 0:
                messagebox.showerror("خطأ", "الكمية يجب أن تكون أكبر من صفر", parent=win)
                return
            unit = cb_unit.currentText()
            try:
                qty_units = units_for_qty(d, unit, qty)
            except Exception as ex:
                messagebox.showerror("خطأ", str(ex), parent=win)
                return
            batch_id = state["batches"][cb_batch.currentIndex() - 1]["id"] if cb_batch.currentIndex() > 0 else None
            reason = e_reason.text().strip()
            if not reason:
                messagebox.showerror("خطأ", "أدخل سبب المرتجع", parent=win)
                return
            try:
                rid, total = self.db.create_purchase_return(
                    sup["id"], d["id"], qty_units, unit=unit, reason=reason, cashier=self.username, batch_id=batch_id
                )
            except ValueError as e:
                messagebox.showerror("خطأ", str(e), parent=win)
                return
            sup_after = next(s for s in self.db.suppliers() if s["id"] == sup["id"])
            messagebox.showinfo(
                "تم",
                "تم تسجيل مرتجع المشتريات #%d\nالمبلغ: %s\nدين المورد الآن: %s" % (rid, money(total), money(sup_after["balance"])),
                parent=win,
            )
            win.accept()
            self.reports_refresh()

        btn = PrimaryPushButton("✅ اعتماد مرتجع المشتريات")
        btn.clicked.connect(do_save)
        lay.addWidget(btn)
        win.exec()

    # =========================================================================
    # Customers (Tab 4)
    # =========================================================================
    def build_customers(self, outer=None):
        container = outer or self._tab_widgets[4]
        outer_lay = QVBoxLayout(container)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll, _inner, tab = ui_theme.make_scroll_page("custInner")
        outer_lay.addWidget(scroll)

        top_card = CardWidget()
        top = QHBoxLayout(top_card)
        top.setContentsMargins(12, 10, 12, 10)
        top.setSpacing(8)
        top.addWidget(StrongBodyLabel("بحث:"))
        self.e_cust_search = SearchLineEdit()
        self.e_cust_search.setPlaceholderText("ابحث باسم العميل أو الهاتف...")
        self.e_cust_search.setMinimumWidth(150)
        self.e_cust_search.textChanged.connect(lambda _t: self._debounce("cust_search", 120, self.cust_refresh))
        self.e_cust_search.returnPressed.connect(self.cust_refresh)
        top.addWidget(self.e_cust_search, 1)

        b_add = PrimaryPushButton("➕ عميل جديد")
        b_add.clicked.connect(self.add_customer_dialog)
        b_pay = PushButton("💰 تسجيل دفعة على الحساب")
        b_pay.clicked.connect(self.customer_pay_dialog)
        b_hist = PushButton("📜 سجل مشتريات العميل")
        b_hist.clicked.connect(self.customer_history_dialog)
        top.addWidget(b_add)
        top.addWidget(b_pay)
        top.addWidget(b_hist)
        tab.addWidget(top_card)

        self.tree_cust = TableWidget()
        ui_theme.configure_table(self.tree_cust, ("#", "الاسم", "الهاتف", "حد الائتمان", "الدين الحالي (آجل)"), (60, 240, 160, 160, 180), stretch_cols=(1,), min_height=360)
        tab.addWidget(self.tree_cust, 1)
        self.cust_refresh()

    def cust_refresh(self):
        if not hasattr(self, "tree_cust"):
            return
        q = self.e_cust_search.text() if hasattr(self, "e_cust_search") else ""
        self.cust_rows = self.db.customers(q)
        ui_theme.set_table_rows(
            self.tree_cust,
            [(c["id"], c["name"], c["phone"], money(c["credit_limit"]), money(c["balance"])) for c in self.cust_rows],
        )

    def _selected_customer(self):
        idx = ui_theme.selected_row_index(self.tree_cust)
        if idx is None or idx >= len(self.cust_rows):
            messagebox.showinfo("تنبيه", "اختر عميل أولاً", parent=self)
            return None
        return self.cust_rows[idx]

    def add_customer_dialog(self):
        win = QDialog(self)
        win.setWindowTitle("عميل جديد")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        lay = QVBoxLayout(win)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)
        ents = {}
        for key, lbl in [("name", "الاسم *"), ("phone", "الهاتف"), ("limit", "حد الائتمان (ج.م)"), ("notes", "ملاحظات")]:
            lay.addWidget(CaptionLabel(lbl))
            e = LineEdit()
            lay.addWidget(e)
            ents[key] = e

        def save():
            if not ents["name"].text().strip():
                messagebox.showerror("خطأ", "الاسم مطلوب", parent=win)
                return
            self.db.add_customer(
                ents["name"].text().strip(),
                ents["phone"].text().strip(),
                safe_float(ents["limit"].text()),
                ents["notes"].text().strip(),
            )
            win.accept()
            self.cust_refresh()
            self._refresh_customer_combo()
            messagebox.showinfo("تم", "تمت إضافة العميل", parent=self)

        b = PrimaryPushButton("حفظ")
        b.clicked.connect(save)
        lay.addWidget(b)
        ui_theme.fit_dialog_widget(win, 400, 340)
        win.exec()

    def customer_pay_dialog(self):
        c = self._selected_customer()
        if not c:
            return
        amt = messagebox.askfloat("دفعة على الحساب", "المبلغ الذي دفعه %s (دينه: %s):" % (c["name"], money(c["balance"])), parent=self)
        if amt is None or amt <= 0:
            return
        try:
            self.db.customer_pay(c["id"], amt, self.username)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        self.cust_refresh()
        messagebox.showinfo("تم", "تم تسجيل الدفعة", parent=self)

    def customer_history_dialog(self):
        c = self._selected_customer()
        if not c:
            return
        rows = self.db.customer_history(c["id"])
        lines = ["سجل مشتريات %s (دين حالي: %s):\n" % (c["name"], money(c["balance"]))]
        for s in rows:
            lines.append("- %s | %s | %s | %s" % (s["invoice_no"], s["date"], money(s["total"]), s["status"]))
        if not rows:
            lines.append("لا توجد مشتريات مسجلة بعد.")
        messagebox.TextViewerDialog(self, "سجل مشتريات: %s" % c["name"], "\n".join(lines)).exec()
