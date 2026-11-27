# -*- coding: utf-8 -*-
"""
Operations tabs mixin (PySide6-Fluent-Widgets):
  - Tab 5: Reports, All Invoices, Edit/Void Invoice, Attendance, Branches, Employee Sales
  - Tab 6: Cash & Shifts (الخزنة والورديات)
  - Tab 8: AI Inventory Forecasting (التنبؤ الذكي)
"""
import csv as _csv
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    TextEdit,
)

from app_helpers import money, safe_float, safe_int, strict_float
from database import allowed_units, unit_price
import ui_dialogs as messagebox
import ui_theme

try:
    import ai_forecast
except Exception:
    ai_forecast = None


class OpsTabsMixin:
    """Reports, Cash/Shifts, and AI Forecasting tabs & dialogs."""

    # =========================================================================
    # Reports (Tab 5)
    # =========================================================================
    def build_reports(self, outer=None):
        container = outer or self._tab_widgets[5]
        outer_lay = QVBoxLayout(container)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll, _inner, tab = ui_theme.make_scroll_page("repInner")
        outer_lay.addWidget(scroll)

        top_card = CardWidget()
        top = QHBoxLayout(top_card)
        top.setContentsMargins(12, 10, 12, 10)
        top.setSpacing(8)
        top.addWidget(StrongBodyLabel("التاريخ (YYYY-MM-DD):"))
        self.e_rep_date = LineEdit()
        self.e_rep_date.setText(date.today().isoformat())
        self.e_rep_date.setFixedWidth(130)
        top.addWidget(self.e_rep_date)

        b_show = PrimaryPushButton("عرض تقرير اليوم")
        b_show.clicked.connect(self.reports_refresh)
        b_all = PushButton("📋 كل الفواتير")
        b_all.clicked.connect(self.show_all_invoices)
        b_ret = PushButton("إرجاع فاتورة (مرتجع)")
        b_ret.setStyleSheet(f"color: {self.pal['danger']}; font-weight: bold;")
        b_ret.clicked.connect(self.return_sale_dialog)
        top.addWidget(b_show)
        top.addWidget(b_all)
        top.addWidget(b_ret)
        top.addStretch(1)
        tab.addWidget(top_card)

        self.lbl_rep = BodyLabel("")
        self.lbl_rep.setWordWrap(True)
        tab.addWidget(self.lbl_rep)

        cards_grid = QGridLayout()
        cards_grid.setSpacing(10)
        self.rep_cards = {}
        for idx, (_key, _title, _acc) in enumerate([
            ("total", "مبيعات اليوم", self.pal["accent"]),
            ("profit", "ربح اليوم", self.pal["success"]),
            ("count", "عدد الفواتير", self.pal["info"]),
            ("net", "صافي الربح", self.pal["success"]),
        ]):
            card = ui_theme.StatCard(_title, "—", "", _acc)
            cards_grid.addWidget(card, 0, idx)
            self.rep_cards[_key] = card
        tab.addLayout(cards_grid)

        best_card = CardWidget()
        bl = QVBoxLayout(best_card)
        bl.setContentsMargins(12, 12, 12, 12)
        bl.addWidget(StrongBodyLabel("أكثر الأصناف مبيعاً:"))
        self.tree_best = TableWidget()
        ui_theme.configure_table(self.tree_best, ("الدواء", "الكمية المباعة (وحدة)", "الإجمالي"), (320, 160, 180), stretch_cols=(0,), min_height=240)
        bl.addWidget(self.tree_best)
        tab.addWidget(best_card, 1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        for text, fn in [
            ("📥 تصدير تقرير اليوم CSV", self.export_daily_csv),
            ("📥 تصدير الأكثر مبيعاً CSV", self.export_best_csv),
            ("📥 تصدير قيمة المخزون CSV", self.export_inventory_csv),
            ("عرض قيمة المخزون", self.show_inventory_value),
        ]:
            b = PushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        if self.is_admin:
            b_emp = PrimaryPushButton("👥 تقرير مبيعات الموظفين")
            b_emp.clicked.connect(self.employee_sales_dialog)
            btns.addWidget(b_emp)
        btns.addStretch(1)
        tab.addLayout(btns)

        self.reports_refresh()

    def reports_refresh(self):
        if not hasattr(self, "tree_best"):
            return
        day = self.e_rep_date.text().strip() or date.today().isoformat()
        try:
            r = self.db.report_daily(day)
        except ValueError as e:
            self.lbl_rep.setText("⚠️ %s" % e)
            return
        self.lbl_rep.setText(
            "تقرير يوم %s\nعدد الفواتير: %d | إجمالي المبيعات: %s | نقدي: %s | كارت: %s | آجل: %s\n"
            "الربح (بيع − تكلفة): %s | المصروفات: %s | صافي الربح: %s\n"
            "مرتجع مشتريات اليوم: %s (%d عملية)"
            % (
                r["date"], r["count"], money(r["total"]), money(r["cash"]), money(r["card"]),
                money(r["credit"]), money(r["profit"]), money(r["expenses"]), money(r["net_profit"]),
                money(r.get("purchase_returns_total", 0)), r.get("purchase_returns_count", 0),
            )
        )
        try:
            self.rep_cards["total"].set_values(money(r["total"]), "نقدي %s • كارت %s • آجل %s" % (money(r["cash"]), money(r["card"]), money(r["credit"])))
            self.rep_cards["profit"].set_values(money(r["profit"]), "المصروفات: %s" % money(r["expenses"]))
            self.rep_cards["count"].set_values(str(r["count"]), "فواتير مكتملة")
            self.rep_cards["net"].set_values(money(r["net_profit"]), "بعد خصم المصروفات")
        except Exception:
            pass
        best = self.db.report_best_sellers(day)
        if not best:
            ui_theme.set_table_rows(self.tree_best, [("لا توجد مبيعات في هذا اليوم بعد", "—", "—")])
        else:
            ui_theme.set_table_rows(self.tree_best, [(b["trade_en"], b["units"], money(b["total"])) for b in best])

    # ---------- Attendance / Branches / Employee Sales ----------
    def attendance_dialog(self):
        win = QDialog(self)
        win.setWindowTitle("الحضور والانصراف")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 900, 560)
        lay = QVBoxLayout(win)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        top = QHBoxLayout()
        lbl = StrongBodyLabel("")
        top.addWidget(lbl)
        top.addStretch(1)

        filt = {}
        today = date.today().isoformat()
        tree = TableWidget()
        ui_theme.configure_table(tree, ("الموظف", "الفرع", "الحضور", "الانصراف", "الساعات", "ملاحظة"), (110, 120, 165, 165, 80, 180), stretch_cols=(5,), min_height=280)

        def refresh():
            op = self.db.attendance_open_for(self.username)
            lbl.setText(("🟢 حاضر منذ %s" % op["check_in"].replace("T", " ")) if op else "⚪ لم يتم تسجيل حضور")
            d1 = filt["from"].text().strip() if filt else (date.today() - timedelta(days=30)).isoformat()
            d2 = filt["to"].text().strip() if filt else today
            try:
                rows = self.db.attendance_report(
                    self.username, d1, d2, (filt["user"].text().strip() or None) if filt else None
                )
            except ValueError as e:
                messagebox.showerror("خطأ", str(e), parent=win)
                return
            ui_theme.set_table_rows(
                tree,
                [
                    (
                        r["username"], r.get("branch_name") or "—",
                        r["check_in"].replace("T", " "), r["check_out"].replace("T", " ") or "—",
                        "—" if r["hours"] is None else r["hours"], r["note"],
                    )
                    for r in rows
                ],
            )

        def do_in():
            try:
                self.db.check_in(self.username)
            except ValueError as e:
                messagebox.showerror("الحضور", str(e), parent=win)
            refresh()

        def do_out():
            try:
                self.db.check_out(self.username)
            except ValueError as e:
                messagebox.showerror("الحضور", str(e), parent=win)
            refresh()

        b_in = PrimaryPushButton("✅ تسجيل حضور")
        b_in.clicked.connect(do_in)
        b_out = PushButton("🚪 تسجيل انصراف")
        b_out.clicked.connect(do_out)
        top.addWidget(b_in)
        top.addWidget(b_out)

        if self.is_admin:
            def add_manual():
                dlg = QDialog(win)
                dlg.setWindowTitle("تسجيل وردية لموظف")
                dlg.setLayoutDirection(Qt.RightToLeft)
                dlg.setStyleSheet(ui_theme.window_qss())
                dl = QVBoxLayout(dlg)
                dl.setContentsMargins(16, 14, 16, 14)
                dl.setSpacing(8)
                ents = {}
                for key, lab, init in (
                    ("u", "اسم المستخدم", ""), ("a", "الحضور (2026-11-25 09:00)", today + " 09:00"),
                    ("b", "الانصراف (اختياري)", ""), ("n", "ملاحظة", ""),
                ):
                    dl.addWidget(CaptionLabel(lab))
                    e = LineEdit()
                    e.setText(init)
                    dl.addWidget(e)
                    ents[key] = e

                def save():
                    try:
                        self.db.attendance_add_manual(
                            self.username, ents["u"].text().strip(),
                            ents["a"].text(), ents["b"].text(), ents["n"].text(),
                        )
                    except (ValueError, PermissionError) as e:
                        messagebox.showerror("خطأ", str(e), parent=dlg)
                        return
                    dlg.accept()
                    refresh()

                b_sv = PrimaryPushButton("حفظ")
                b_sv.clicked.connect(save)
                dl.addWidget(b_sv)
                ui_theme.fit_dialog_widget(dlg, 400, 340)
                dlg.exec()

            b_man = PushButton("➕ تسجيل وردية لموظف")
            b_man.clicked.connect(add_manual)
            top.addWidget(b_man)

        lay.addLayout(top)
        if self.is_admin:
            fr = QHBoxLayout()
            fr.addWidget(BodyLabel("الموظف (فارغ = الكل):"))
            filt["user"] = LineEdit()
            filt["user"].setFixedWidth(130)
            fr.addWidget(filt["user"])
            for k, lab in (("from", "من"), ("to", "إلى")):
                fr.addWidget(BodyLabel(lab))
                filt[k] = LineEdit()
                filt[k].setText(today)
                filt[k].setFixedWidth(120)
                fr.addWidget(filt[k])
            b_f = PushButton("عرض")
            b_f.clicked.connect(refresh)
            fr.addWidget(b_f)
            fr.addStretch(1)
            lay.addLayout(fr)

        lay.addWidget(tree, 1)
        refresh()
        win.exec()

    def branches_dialog(self):
        if not self.is_admin:
            messagebox.showerror("صلاحيات", "إدارة الفروع للمدير فقط", parent=self)
            return
        win = QDialog(self)
        win.setWindowTitle("الفروع")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 740, 640)
        lay = QVBoxLayout(win)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        tree = TableWidget()
        ui_theme.configure_table(tree, ("الفرع", "العنوان", "الحالة"), (200, 280, 120), stretch_cols=(1,), min_height=160)
        lay.addWidget(tree)

        form = QHBoxLayout()
        e_name = LineEdit()
        e_addr = LineEdit()
        form.addWidget(BodyLabel("اسم الفرع:"))
        form.addWidget(e_name)
        form.addWidget(BodyLabel("العنوان:"))
        form.addWidget(e_addr, 1)
        b_add = PrimaryPushButton("➕ إضافة فرع")
        b_tog = PushButton("إيقاف / تفعيل الفرع المحدد")
        form.addWidget(b_add)
        form.addWidget(b_tog)
        lay.addLayout(form)

        lay.addWidget(StrongBodyLabel("تعيين موظف لفرع:"))
        users_tree = TableWidget()
        ui_theme.configure_table(users_tree, ("المستخدم", "الاسم", "الدور", "الفرع"), (150, 200, 110, 170), stretch_cols=(1,), min_height=200)
        lay.addWidget(users_tree, 1)

        arow = QHBoxLayout()
        cb = ComboBox()
        cb.setMinimumWidth(220)
        b_assign = PrimaryPushButton("تعيين")
        arow.addWidget(cb)
        arow.addWidget(b_assign)
        arow.addStretch(1)
        lay.addLayout(arow)

        state = {"branches": [], "users": []}

        def refresh():
            state["branches"] = self.db.list_branches()
            ui_theme.set_table_rows(
                tree,
                [(b["name"], b["address"], "نشط" if b["active"] else "موقوف") for b in state["branches"]],
            )
            cb.clear()
            cb.addItems([b["name"] for b in state["branches"] if b["active"]])
            names = {b["id"]: b["name"] for b in state["branches"]}
            state["users"] = self.db.list_users(self.username)
            ui_theme.set_table_rows(
                users_tree,
                [(u["username"], u["full_name"], "مدير" if u["role"] == "admin" else "موظف", names.get(u["branch_id"], "—")) for u in state["users"]],
            )

        def add():
            try:
                self.db.add_branch(self.username, e_name.text(), e_addr.text())
            except (ValueError, PermissionError) as e:
                messagebox.showerror("خطأ", str(e), parent=win)
                return
            e_name.clear()
            e_addr.clear()
            refresh()

        def toggle():
            idx = ui_theme.selected_row_index(tree)
            if idx is None or idx >= len(state["branches"]):
                return
            b = state["branches"][idx]
            self.db.set_branch_active(self.username, b["id"], not b["active"])
            refresh()

        def assign():
            uidx = ui_theme.selected_row_index(users_tree)
            bname = cb.currentText()
            if uidx is None or uidx >= len(state["users"]) or not bname:
                messagebox.showinfo("الفروع", "اختر مستخدماً وفرعاً", parent=win)
                return
            u = state["users"][uidx]
            b = next(x for x in state["branches"] if x["name"] == bname)
            self.db.set_user_branch(self.username, u["username"], b["id"])
            refresh()

        b_add.clicked.connect(add)
        b_tog.clicked.connect(toggle)
        b_assign.clicked.connect(assign)
        refresh()
        win.exec()

    def employee_sales_dialog(self):
        if not self.is_admin:
            return
        win = QDialog(self)
        win.setWindowTitle("مبيعات الموظفين، أساس مراجعة البونص")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 1020, 600)
        lay = QVBoxLayout(win)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        controls = QHBoxLayout()
        fields = []
        for label in ("من YYYY-MM-DD", "إلى YYYY-MM-DD"):
            controls.addWidget(BodyLabel(label))
            ent = LineEdit()
            ent.setText(date.today().isoformat())
            ent.setFixedWidth(130)
            controls.addWidget(ent)
            fields.append(ent)

        keys = ("employee", "full_name", "completed_count", "completed_sales", "returned_count", "returned_sales", "mobile_sales")
        headers = ("المستخدم", "الاسم", "عدد المكتمل", "مبيعات مكتملة", "عدد المرتجع", "قيمة المرتجع", "موبايل مكتمل")
        tree = TableWidget()
        ui_theme.configure_table(tree, headers, (130, 180, 115, 135, 115, 135, 135), stretch_cols=(1,), min_height=280)

        rows_cache = []

        def refresh():
            try:
                data = self.db.report_employee_sales(fields[0].text().strip(), fields[1].text().strip())
            except ValueError as e:
                messagebox.showerror("خطأ", str(e), parent=win)
                return False
            rows_cache[:] = [[r[k] for k in keys] for r in data]
            ui_theme.set_table_rows(
                tree,
                [[("%.2f" % val) if k.endswith("sales") else val for k, val in zip(keys, row)] for row in rows_cache],
            )
            return True

        def export():
            if not refresh():
                return
            values = [[fields[0].text().strip(), fields[1].text().strip()] + row for row in rows_cache]
            safe = [[("'" + v) if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for v in row] for row in values]
            self._export_csv("employee_sales.csv", ("date_from", "date_to") + headers, safe)

        b_show = PrimaryPushButton("عرض")
        b_show.clicked.connect(refresh)
        b_exp = PushButton("تصدير CSV")
        b_exp.clicked.connect(export)
        controls.addWidget(b_show)
        controls.addWidget(b_exp)
        controls.addStretch(1)
        lay.addLayout(controls)
        lay.addWidget(tree, 1)

        notes = CaptionLabel(
            "حسب تاريخ الفاتورة الأصلي، كل طرق الدفع والمصادر. المبيعات المكتملة بعد الخصم وتستبعد المرتجع بالكامل.\n"
            "ليست تحصيلات نقدية. التعديلات والمرتجعات اللاحقة تغيّر النتائج، وليست دفتر صرف بونص ثابتاً.\n"
            "mobile = دخول مشترك بلا موظف. لا توجد معادلة بونص مفترضة."
        )
        notes.setWordWrap(True)
        lay.addWidget(notes)
        refresh()
        win.exec()

    # ---------- All Invoices Window (live-refreshed) ----------
    def show_all_invoices(self):
        if getattr(self, "_inv_win", None) is not None and self._inv_win.isVisible():
            self._inv_win.raise_()
            self._inv_win.activateWindow()
            self._inv_refresh()
            return
        win = QDialog(self)
        win.setWindowTitle("📋 كل الفواتير")
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 1120, 640)
        self._inv_win = win
        self._inv_rows = []
        lay = QVBoxLayout(win)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        f1 = QHBoxLayout()
        f1.addWidget(BodyLabel("من:"))
        self._inv_from = LineEdit()
        self._inv_from.setText(date.today().isoformat())
        self._inv_from.setFixedWidth(120)
        f1.addWidget(self._inv_from)
        f1.addWidget(BodyLabel("إلى:"))
        self._inv_to = LineEdit()
        self._inv_to.setText(date.today().isoformat())
        self._inv_to.setFixedWidth(120)
        f1.addWidget(self._inv_to)
        f1.addWidget(BodyLabel("المصدر:"))
        self._inv_src = ComboBox()
        self._inv_src.addItems(["الكل", "كمبيوتر", "موبايل"])
        f1.addWidget(self._inv_src)
        f1.addWidget(BodyLabel("الدفع:"))
        self._inv_pay = ComboBox()
        self._inv_pay.addItems(["الكل", "نقدي", "كارت", "آجل"])
        f1.addWidget(self._inv_pay)
        f1.addStretch(1)
        lay.addLayout(f1)

        f2 = QHBoxLayout()
        f2.addWidget(BodyLabel("العميل:"))
        self._inv_cust = LineEdit()
        self._inv_cust.setFixedWidth(180)
        f2.addWidget(self._inv_cust)
        f2.addWidget(BodyLabel("رقم الفاتورة:"))
        self._inv_no = LineEdit()
        self._inv_no.setFixedWidth(150)
        f2.addWidget(self._inv_no)
        b_find = PrimaryPushButton("🔎 بحث")
        b_find.clicked.connect(self._inv_refresh)
        b_all = PushButton("عرض الكل")
        b_all.clicked.connect(self._inv_show_all)
        b_csv = PushButton("📥 تصدير CSV")
        b_csv.clicked.connect(self._inv_export_csv)
        f2.addWidget(b_find)
        f2.addWidget(b_all)
        f2.addWidget(b_csv)
        f2.addStretch(1)
        lay.addLayout(f2)

        self._inv_count = StrongBodyLabel("")
        lay.addWidget(self._inv_count)

        self._inv_tree = TableWidget()
        ui_theme.configure_table(
            self._inv_tree,
            ("رقم الفاتورة", "التاريخ والوقت", "العميل", "المصدر", "طريقة الدفع", "عدد الأصناف", "الإجمالي", "حالة الطباعة"),
            (130, 165, 180, 95, 95, 90, 115, 145),
            stretch_cols=(2,),
            min_height=320,
        )
        self._inv_tree.cellDoubleClicked.connect(lambda _r, _c: self._inv_open_detail())
        lay.addWidget(self._inv_tree, 1)

        acts = QHBoxLayout()
        b_det = PushButton("🧾 عرض تفاصيل الفاتورة المحددة")
        b_det.clicked.connect(self._inv_open_detail)
        acts.addWidget(b_det)
        b_edit = PrimaryPushButton("✏️ تعديل الفاتورة المحددة")
        b_edit.clicked.connect(self._inv_edit_selected)
        acts.addWidget(b_edit)
        if self.is_admin:
            b_del = PushButton("🗑️ حذف الفاتورة المحددة (إرجاع كامل)")
            b_del.setStyleSheet(f"color: {self.pal['danger']}; font-weight: bold;")
            b_del.clicked.connect(self._inv_void_selected)
            acts.addWidget(b_del)
        acts.addStretch(1)
        lay.addLayout(acts)

        win.finished.connect(lambda _r=0: setattr(self, "_inv_win", None))
        self._inv_refresh()
        win.show()

    def _inv_filters(self):
        src = {"الكل": None, "كمبيوتر": "pc", "موبايل": "mobile"}.get(self._inv_src.currentText())
        pay = {"الكل": None, "نقدي": "cash", "كارت": "card", "آجل": "credit"}.get(self._inv_pay.currentText())
        return dict(
            date_from=self._inv_from.text().strip() or None,
            date_to=self._inv_to.text().strip() or None,
            source=src,
            payment=pay,
            customer=self._inv_cust.text().strip(),
            invoice_no=self._inv_no.text().strip(),
        )

    def _inv_show_all(self):
        self._inv_from.clear()
        self._inv_to.clear()
        self._inv_src.setCurrentIndex(0)
        self._inv_pay.setCurrentIndex(0)
        self._inv_cust.clear()
        self._inv_no.clear()
        self._inv_refresh()

    def _inv_refresh(self):
        if getattr(self, "_inv_win", None) is None or not self._inv_win.isVisible():
            return
        try:
            self._inv_rows = self.db.get_all_sales(**self._inv_filters())
            rows = []
            for s in self._inv_rows:
                dt = (s.get("created_at") or s.get("date") or "").replace("T", " ")
                src = "موبايل 📱" if s.get("source") == "mobile" else "كمبيوتر 🖥️"
                pay = {"cash": "نقدي", "card": "كارت", "credit": "آجل"}.get(s.get("payment_method"), s.get("payment_method") or "")
                printed = "🖨️ مطبوعة" if s.get("printed_at") else "⏳ بانتظار الطباعة"
                rows.append((s["invoice_no"], dt, s.get("customer_name") or "عميل نقدي", src, pay, s.get("item_count", ""), money(s["total"]), printed))
            ui_theme.set_table_rows(self._inv_tree, rows)
            total = sum(s["total"] for s in self._inv_rows)
            self._inv_count.setText("عدد الفواتير: %d — الإجمالي: %s" % (len(self._inv_rows), money(total)))
        except Exception:
            pass

    def _inv_export_csv(self):
        rows = [
            (
                s["invoice_no"], (s.get("created_at") or s.get("date") or ""),
                s.get("customer_name") or "", s.get("source") or "",
                s.get("payment_method") or "", s.get("item_count", ""),
                s["total"], "مطبوعة" if s.get("printed_at") else "بانتظار الطباعة",
            )
            for s in getattr(self, "_inv_rows", [])
        ]
        self._export_csv("all_invoices.csv", ["invoice", "datetime", "customer", "source", "payment", "items", "total", "printed"], rows)

    def _inv_selected(self):
        idx = ui_theme.selected_row_index(self._inv_tree)
        if idx is None or idx >= len(self._inv_rows):
            return None
        return self._inv_rows[idx]

    def _inv_open_detail(self):
        s = self._inv_selected()
        if not s:
            messagebox.showinfo("تنبيه", "اختر فاتورة من القائمة أولاً (أو اضغط مرتين عليها)", parent=self._inv_win or self)
            return
        items = self.db.get_grouped_sale_items(s["id"])
        win = QDialog(self._inv_win or self)
        win.setWindowTitle("فاتورة %s" % s["invoice_no"])
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 760, 560)
        lay = QVBoxLayout(win)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        info = (
            "رقم الفاتورة: %s  |  التاريخ والوقت: %s\nالعميل: %s  |  الكاشير: %s\n"
            "المصدر: %s  |  طريقة الدفع: %s  |  المدفوع: %s  |  الحالة: %s"
            % (
                s["invoice_no"], (s.get("created_at") or s.get("date") or "").replace("T", " "),
                s.get("customer_name") or "عميل نقدي", s.get("cashier") or "",
                "موبايل 📱" if s.get("source") == "mobile" else "كمبيوتر 🖥️",
                {"cash": "نقدي", "card": "كارت", "credit": "آجل"}.get(s.get("payment_method"), s.get("payment_method") or ""),
                money(s.get("paid", s["total"])),
                "🖨️ مطبوعة %s" % s["printed_at"] if s.get("printed_at") else "⏳ بانتظار الطباعة",
            )
        )
        lbl_i = BodyLabel(info)
        lbl_i.setWordWrap(True)
        lay.addWidget(lbl_i)

        tree = TableWidget()
        ui_theme.configure_table(tree, ("الدواء", "الوحدة", "الكمية", "السعر", "الإجمالي"), (230, 90, 90, 120, 130), stretch_cols=(0,), min_height=220)
        ui_theme.set_table_rows(
            tree,
            [
                (
                    "%s %s" % (it.get("trade_en") or "", it.get("trade_ar") or ""),
                    {"box": "علبة", "strip": "شريط", "pill": "حبة"}.get(it.get("pack_level"), it.get("pack_level") or ""),
                    it.get("qty_display"), money(it.get("unit_price", 0)), money(it.get("line_total", 0)),
                )
                for it in items
            ],
        )
        lay.addWidget(tree, 1)

        lay.addWidget(SubtitleLabel("الإجمالي: %s" % money(s["total"])))
        if s.get("edited_at"):
            ed = StrongBodyLabel("✏️ عُدّلت: %s بواسطة %s" % (s["edited_at"], s.get("edited_by") or "—"))
            ed.setStyleSheet(f"color: {self.pal['warning']};")
            lay.addWidget(ed)

        btns = QHBoxLayout()
        if self.is_admin:
            b_ed = PrimaryPushButton("✏️ تعديل الفاتورة")
            b_ed.clicked.connect(lambda: self.edit_invoice_dialog(s["id"]))
            btns.addWidget(b_ed)
        b_pr = PushButton("🖨️ طباعة الإيصال")
        b_pr.clicked.connect(lambda: self._open_receipt_window(s))
        btns.addWidget(b_pr)
        b_ex = PushButton("📥 تصدير أصناف الفاتورة CSV")
        b_ex.clicked.connect(
            lambda: self._export_csv(
                "invoice_%s_items.csv" % s["invoice_no"],
                ["drug", "unit", "qty", "price", "total"],
                [(it.get("trade_en") or "", it.get("pack_level") or "", it.get("qty_display"), it.get("unit_price"), it.get("line_total")) for it in items],
            )
        )
        btns.addWidget(b_ex)
        if self.is_admin:
            b_del = PushButton("🗑️ حذف الفاتورة")
            b_del.setStyleSheet(f"color: {self.pal['danger']}; font-weight: bold;")
            b_del.clicked.connect(lambda: self._void_sale_row(s, parent=win) and win.accept())
            btns.addWidget(b_del)
        btns.addStretch(1)
        lay.addLayout(btns)
        win.exec()

    def _inv_edit_selected(self):
        s = self._inv_selected()
        if not s:
            messagebox.showinfo("تنبيه", "اختر فاتورة من القائمة أولاً", parent=self._inv_win or self)
            return
        self.edit_invoice_dialog(s["id"])

    def _inv_void_selected(self):
        s = self._inv_selected()
        if not s:
            messagebox.showinfo("تنبيه", "اختر فاتورة من القائمة أولاً", parent=self._inv_win or self)
            return
        self._void_sale_row(s, parent=self._inv_win)

    def mobile_edit_selected(self):
        sale = self._selected_mobile_sale()
        if sale:
            self.edit_invoice_dialog(sale["id"])

    def _admin_only_invoice(self):
        if not self.is_admin:
            messagebox.showwarning("غير مسموح", "إلغاء أو تعديل الفاتورة للمدير فقط", parent=self)
            return False
        return True

    def edit_invoice_dialog(self, sale_id):
        if not self._admin_only_invoice():
            return
        sale = self.db.get_sale(sale_id)
        if not sale:
            messagebox.showerror("خطأ", "الفاتورة غير موجودة", parent=self)
            return
        if sale["status"] != "completed":
            messagebox.showinfo(
                "لا يمكن التعديل",
                "لا يمكن تعديل هذه الفاتورة — حالتها: %s.\nالفاتورة المُرجعة لا تُعدَّل." % sale["status"],
                parent=self,
            )
            return
        items = self.db.get_grouped_sale_items(sale_id)
        cart = []
        for it in items:
            d = self.db.get_drug(it["drug_id"])
            if d:
                cart.append({
                    "drug": d, "pack_level": it["pack_level"] or "box",
                    "qty_display": float(it["qty_display"] or 0),
                    "held": False, "orig": True,
                    "discount": float(it.get("line_discount") or 0),
                    "disc_mode": "orig",
                })
        orig_snapshot = [dict(it) for it in cart]
        orig_disc = float(sale.get("discount") or 0)
        orig_paid = float(sale.get("paid") or sale["total"])
        orig_pay = sale.get("payment_method") or "cash"
        orig_cust_name = None
        if sale.get("customer_id"):
            for _c in self.db.customers(""):
                if _c["id"] == sale["customer_id"]:
                    orig_cust_name = _c["name"]

        win = QDialog(self)
        win.setWindowTitle("✏️ تعديل فاتورة %s" % sale["invoice_no"])
        win.setLayoutDirection(Qt.RightToLeft)
        win.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(win, 920, 680)
        lay = QVBoxLayout(win)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        old_total = float(sale["total"])
        lay.addWidget(StrongBodyLabel("فاتورة: %s — التاريخ: %s — الإجمالي القديم: %s" % (sale["invoice_no"], sale["date"], money(old_total))))
        if sale.get("printed_at"):
            lw = CaptionLabel("⚠️ هذه الفاتورة مطبوعة — بعد التعديل ستُطبع من جديد بالمحتوى الجديد.")
            lw.setStyleSheet(f"color: {self.pal['warning']};")
            lay.addWidget(lw)
        if sale.get("edited_at"):
            le = CaptionLabel("✏️ عُدّلت من قبل: %s بواسطة %s" % (sale["edited_at"], sale.get("edited_by") or "—"))
            le.setStyleSheet(f"color: {self.pal['warning']};")
            lay.addWidget(le)

        tree = TableWidget()
        ui_theme.configure_table(tree, ("الدواء", "الوحدة", "الكمية", "السعر", "الخصم", "الإجمالي"), (260, 80, 85, 115, 100, 125), stretch_cols=(0,), min_height=220)
        lay.addWidget(tree, 1)

        row_btns = QHBoxLayout()
        b_plus = PushButton("＋ كمية")
        b_minus = PushButton("− كمية")
        b_rem = PushButton("🗑️ حذف الصنف")
        b_res = PushButton("↩️ استرجاع المحذوف")
        for b in (b_plus, b_minus, b_rem, b_res):
            row_btns.addWidget(b)
        row_btns.addStretch(1)
        lay.addLayout(row_btns)

        addf = QHBoxLayout()
        addf.addWidget(BodyLabel("إضافة صنف: باركود / اسم:"))
        e_add = LineEdit()
        e_add.setMinimumWidth(200)
        addf.addWidget(e_add)
        unit_state = {"unit": "box"}
        ugrp = QButtonGroup(win)
        for txt, val in (("علبة", "box"), ("شريط", "strip"), ("حبة", "pill")):
            rb = RadioButton(txt)
            if val == "box":
                rb.setChecked(True)
            rb.toggled.connect(lambda c, v=val: unit_state.__setitem__("unit", v) if c else None)
            ugrp.addButton(rb)
            addf.addWidget(rb)
        e_qty = LineEdit()
        e_qty.setText("1")
        e_qty.setFixedWidth(70)
        addf.addWidget(e_qty)
        b_add_it = PrimaryPushButton("➕ إضافة")
        addf.addWidget(b_add_it)
        addf.addStretch(1)
        lay.addLayout(addf)

        payf = QHBoxLayout()
        payf.addWidget(BodyLabel("الخصم (ج.م):"))
        e_disc = LineEdit()
        e_disc.setText("%.2f" % float(sale.get("discount") or 0))
        e_disc.setFixedWidth(95)
        payf.addWidget(e_disc)
        payf.addWidget(BodyLabel("المدفوع:"))
        e_paid = LineEdit()
        e_paid.setText("%.2f" % float(sale.get("paid") or sale["total"]))
        e_paid.setFixedWidth(105)
        payf.addWidget(e_paid)
        payf.addWidget(BodyLabel("الدفع:"))
        cmb_pay = ComboBox()
        cmb_pay.addItems(["cash", "card", "credit"])
        cmb_pay.setCurrentText(sale.get("payment_method") or "cash")
        payf.addWidget(cmb_pay)
        payf.addWidget(BodyLabel("العميل:"))
        customers = self.db.customers("")
        cmb_cust = ComboBox()
        cmb_cust.addItems(["عميل نقدي"] + [c["name"] for c in customers])
        if orig_cust_name:
            cmb_cust.setCurrentText(orig_cust_name)
        payf.addWidget(cmb_cust)
        payf.addStretch(1)
        lay.addLayout(payf)

        lbl_totals = StrongBodyLabel("")
        lbl_totals.setWordWrap(True)
        lay.addWidget(lbl_totals)

        p = ui_theme.palette(self.theme_name, self.ui_accent)

        def refresh_tree():
            trows = []
            tstyles = []
            for it in cart:
                up = unit_price(it["drug"], it["pack_level"])
                held = bool(it.get("held"))
                _ld = float(it.get("discount") or 0)
                trows.append((
                    ("⏳ محذوف مؤقتاً — %s %s" % (it["drug"]["trade_en"], it["drug"].get("trade_ar") or "")) if held
                    else "%s %s" % (it["drug"]["trade_en"], it["drug"].get("trade_ar") or ""),
                    {"box": "علبة", "strip": "شريط", "pill": "حبة"}.get(it["pack_level"], it["pack_level"]),
                    it["qty_display"], money(up), money(_ld), money(up * float(it["qty_display"]) - _ld),
                ))
                tstyles.append((p["muted"], p["row_alt"]) if held else None)
            ui_theme.set_table_rows(tree, trows, tstyles)
            active = [it for it in cart if not it.get("held")]
            held_lines = [it for it in cart if it.get("held")]
            sub = sum(unit_price(it["drug"], it["pack_level"]) * float(it["qty_display"]) - float(it.get("discount") or 0) for it in active)
            held_sum = sum(unit_price(it["drug"], it["pack_level"]) * float(it["qty_display"]) - float(it.get("discount") or 0) for it in held_lines)
            disc = safe_float(e_disc.text())
            total = max(0.0, sub - disc)
            paid = safe_float(e_paid.text(), total)
            diff = total - old_total
            lbl_totals.setText(
                "الإجمالي المحفوظ: %s — الإجمالي الجديد بعد الاعتماد: %s (المجموع: %s — الخصم: %s)\n"
                "الفرق عن القديم: %s (%s) — الباقي: %s%s"
                % (
                    money(old_total), money(total), money(sub), money(disc), money(diff),
                    "يُحصَّل من العميل" if diff > 0 else ("يُرد للعميل" if diff < 0 else "لا فرق"),
                    money(max(0.0, paid - total)) if paid >= total else "—",
                    (" — مبلغ الأصناف المحذوفة مؤقتاً (غير محسوب حتى الاعتماد): %s" % money(held_sum)) if held_lines else "",
                )
            )

        def change_qty(delta):
            idx = ui_theme.selected_row_index(tree)
            if idx is None or idx >= len(cart):
                messagebox.showinfo("تنبيه", "اختر صنفاً من القائمة أولاً", parent=win)
                return
            it = cart[idx]
            if it.get("held"):
                messagebox.showinfo("تنبيه", "هذا الصنف محذوف مؤقتاً — استرجعه أولاً بزر «↩️ استرجاع المحذوف»", parent=win)
                return
            _old_q = float(it["qty_display"])
            _old_disc = float(it.get("discount") or 0)
            it["qty_display"] = _old_q + delta
            if it.get("disc_mode", "auto") == "auto":
                it["discount"] = self._line_disc_amount(it["drug"], it["pack_level"], it["qty_display"], "auto")
            elif _old_q > 0:
                it["discount"] = round(_old_disc * it["qty_display"] / _old_q + 1e-9, 2)
            if it["qty_display"] <= 0:
                it["qty_display"] = _old_q
                it["held_qty"] = _old_q
                it["held"] = True
            refresh_tree()

        def remove_line():
            idx = ui_theme.selected_row_index(tree)
            if idx is None or idx >= len(cart):
                messagebox.showinfo("تنبيه", "اختر صنفاً من القائمة أولاً", parent=win)
                return
            it = cart[idx]
            if it.get("held"):
                messagebox.showinfo("تنبيه", "هذا الصنف محذوف مؤقتاً بالفعل — يبقى معلَّقاً حتى تعتمد التعديلات أو تسترجعه", parent=win)
                return
            it["held_qty"] = float(it["qty_display"])
            it["held"] = True
            refresh_tree()

        def restore_line():
            idx = ui_theme.selected_row_index(tree)
            if idx is None or idx >= len(cart):
                messagebox.showinfo("تنبيه", "اختر صنفاً محذوفاً مؤقتاً أولاً", parent=win)
                return
            it = cart[idx]
            if not it.get("held"):
                messagebox.showinfo("تنبيه", "هذا الصنف ليس محذوفاً مؤقتاً", parent=win)
                return
            it["held"] = False
            refresh_tree()

        def add_item():
            code = e_add.text().strip()
            if not code:
                return
            drug = None
            try:
                drug, _pk = self.db.lookup_barcode(code)
            except Exception:
                drug = None
            if not drug:
                res = self.db.search_drugs(code, limit=1)
                drug = res[0] if res else None
            if not drug:
                messagebox.showerror("خطأ", "الدواء غير موجود — جرّب الباركود أو الاسم", parent=win)
                return
            try:
                q = float(e_qty.text() or "1")
            except Exception:
                q = 1
            if q <= 0:
                messagebox.showerror("خطأ", "الكمية يجب أن تكون أكبر من صفر", parent=win)
                return
            unit = unit_state["unit"]
            if unit not in allowed_units(drug):
                messagebox.showerror("خطأ", "هذه الوحدة غير متاحة لهذا الشكل الصيدلاني", parent=win)
                return
            for it in cart:
                if it["drug"]["id"] == drug["id"] and it["pack_level"] == unit:
                    it["held"] = False
                    it["qty_display"] = float(it["qty_display"]) + q
                    if it.get("disc_mode", "auto") == "auto":
                        it["discount"] = self._line_disc_amount(drug, unit, it["qty_display"], "auto")
                    break
            else:
                cart.append({
                    "drug": drug, "pack_level": unit, "qty_display": q,
                    "held": False, "orig": False, "disc_mode": "auto",
                    "discount": self._line_disc_amount(drug, unit, q, "auto"),
                })
            e_add.clear()
            refresh_tree()

        b_plus.clicked.connect(lambda: change_qty(1))
        b_minus.clicked.connect(lambda: change_qty(-1))
        b_rem.clicked.connect(remove_line)
        b_res.clicked.connect(restore_line)
        b_add_it.clicked.connect(add_item)
        e_add.returnPressed.connect(add_item)
        e_disc.textChanged.connect(lambda _t: refresh_tree())
        e_paid.textChanged.connect(lambda _t: refresh_tree())

        def do_save():
            active = [it for it in cart if not it.get("held")]
            if not active:
                messagebox.showerror(
                    "خطأ",
                    "كل الأصناف محذوفة مؤقتاً — استرجع ما تريده بزر «↩️ استرجاع المحذوف» قبل الاعتماد"
                    if cart else "الفاتورة فارغة — لا يمكن حفظ فاتورة بلا أصناف",
                    parent=win,
                )
                return
            cust_id = None
            cust_name = cmb_cust.currentText() or "عميل نقدي"
            if cust_name != "عميل نقدي":
                for c in customers:
                    if c["name"] == cust_name:
                        cust_id = c["id"]
            try:
                disc = strict_float(e_disc.text(), "الخصم")
                disc = disc if disc is not None else 0.0
                paid_v = strict_float(e_paid.text(), "المبلغ المدفوع") if e_paid.text().strip() else None
            except ValueError as e:
                messagebox.showerror("خطأ", str(e), parent=win)
                return

            def _nm(it):
                return "%s %s" % (it["drug"]["trade_en"], it["drug"].get("trade_ar") or "")

            def _amt(it):
                return unit_price(it["drug"], it["pack_level"]) * float(it["qty_display"]) - float(it.get("discount") or 0)

            held_lines = [it for it in cart if it.get("held")]
            orig_by_key = {(it["drug"]["id"], it["pack_level"]): it for it in orig_snapshot}
            summary = []
            for it in held_lines:
                summary.append("🗑️ حذف: %s — %s x%s = %s" % (_nm(it), {"box": "علبة", "strip": "شريط", "pill": "حبة"}.get(it["pack_level"], it["pack_level"]), it["qty_display"], money(_amt(it))))
            for it in active:
                key = (it["drug"]["id"], it["pack_level"])
                if key not in orig_by_key:
                    summary.append("➕ إضافة: %s — %s x%s = %s" % (_nm(it), {"box": "علبة", "strip": "شريط", "pill": "حبة"}.get(it["pack_level"], it["pack_level"]), it["qty_display"], money(_amt(it))))
                elif float(it["qty_display"]) != float(orig_by_key[key]["qty_display"]):
                    summary.append("🔢 تغيير كمية: %s — من x%s إلى x%s" % (_nm(it), orig_by_key[key]["qty_display"], it["qty_display"]))
            if disc != orig_disc:
                summary.append("💸 الخصم: من %s إلى %s" % (money(orig_disc), money(disc)))
            if paid_v is not None and abs(float(paid_v) - orig_paid) > 0.005:
                summary.append("💵 المدفوع: من %s إلى %s" % (money(orig_paid), money(paid_v)))
            pay_val = cmb_pay.currentText()
            if pay_val != orig_pay:
                summary.append("💳 طريقة الدفع: من %s إلى %s" % (orig_pay, pay_val))
            if cust_name != (orig_cust_name or "عميل نقدي"):
                summary.append("👤 العميل: من %s إلى %s" % (orig_cust_name or "عميل نقدي", cust_name))
            if not summary:
                messagebox.showinfo("لا تغييرات", "لا توجد تغييرات لاعتمادها — الفاتورة كما هي.", parent=win)
                return
            _sub = sum(_amt(it) for it in active)
            _new_total = max(0.0, _sub - disc)
            _diff = _new_total - old_total
            confirm_txt = (
                "اعتماد التعديلات على فاتورة %s؟\n\n%s\n\n"
                "الإجمالي القديم: %s\nالإجمالي الجديد: %s\nالفرق: %s (%s)\n\n"
                "بعد الاعتماد فقط يُحذف ما حُذف ويُعاد المخزون — قبل ذلك لم يتغيّر شيء."
                % (
                    sale["invoice_no"], "\n".join(summary), money(old_total), money(_new_total), money(_diff),
                    "يُحصَّل من العميل" if _diff > 0 else ("يُرد للعميل" if _diff < 0 else "لا فرق"),
                )
            )
            if not messagebox.askyesno("✅ اعتماد التعديلات", confirm_txt, parent=win):
                return
            try:
                res = self.db.edit_sale(
                    sale_id, self.username, active, discount=disc, payment_method=pay_val, customer_id=cust_id, paid=paid_v
                )
            except ValueError as e:
                messagebox.showerror("خطأ", str(e), parent=win)
                return
            diff = res["difference"]
            msg = "تم تعديل الفاتورة %s\nالإجمالي القديم: %s\nالإجمالي الجديد: %s\n" % (
                res["invoice_no"], money(res["old_total"]), money(res["new_total"])
            )
            msg += (
                "الفرق: %s يُحصَّل من العميل" % money(diff) if diff > 0
                else ("الفرق: %s يُرد للعميل" % money(-diff) if diff < 0 else "لا فرق في الإجمالي")
            )
            messagebox.showinfo("تم التعديل", msg, parent=win)
            win.accept()
            for fn in (self._inv_refresh, self.mobile_refresh, self.reports_refresh, self.inv_refresh):
                try:
                    fn()
                except Exception:
                    pass

        btns = QHBoxLayout()
        b_sv = PrimaryPushButton("✅ اعتماد التعديلات")
        b_sv.clicked.connect(do_save)
        b_cn = PushButton("إلغاء (بدون اعتماد)")
        b_cn.clicked.connect(win.reject)
        btns.addWidget(b_sv)
        btns.addWidget(b_cn)
        btns.addStretch(1)
        lay.addLayout(btns)
        refresh_tree()
        win.exec()

    def return_sale_dialog(self):
        inv = messagebox.askstring("مرتجع", "أدخل رقم الفاتورة (مثال INV-000001):", parent=self)
        if not inv:
            return
        row = self.db.conn.execute("SELECT * FROM sales WHERE invoice_no=?", (inv.strip(),)).fetchone()
        if not row:
            messagebox.showerror("خطأ", "الفاتورة غير موجودة", parent=self)
            return
        self._void_sale_row(dict(row), parent=self)

    def _void_sale_row(self, s, parent=None):
        if not s or not self._admin_only_invoice():
            return False
        if s.get("status") != "completed":
            messagebox.showinfo("لا يمكن الحذف", "هذه الفاتورة مُرجعة بالفعل — لا يمكن حذفها مرة أخرى.", parent=parent or self)
            return False
        if not messagebox.askyesno(
            "تأكيد حذف الفاتورة",
            "حذف الفاتورة %s بمبلغ %s؟\n\n"
            "كل الكميات ترجع للمخزون، وأي دين آجل على الفاتورة يُلغى، "
            "وحالتها تصبح «مُرجعة».\nلا يمكن التراجع عن الحذف." % (s["invoice_no"], money(s["total"])),
            parent=parent or self,
        ):
            return False
        reason = messagebox.askstring("سبب الحذف", "سبب الحذف (اختياري):", parent=parent or self) or ""
        try:
            self.db.return_sale(
                s["id"], self.username,
                return_shift_id=self.current_shift["id"] if self.current_shift else None,
                reason=reason.strip(),
            )
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=parent or self)
            return False
        messagebox.showinfo("تم", "حُذفت الفاتورة %s (إرجاع كامل) — رجعت الكميات للمخزون." % s["invoice_no"], parent=parent or self)
        self.reports_refresh()
        self.inv_refresh()
        self._inv_refresh()
        return True

    def _export_csv(self, filename, header, rows):
        path = messagebox.get_save_filename(parent=self, initialfile=filename, filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        messagebox.showinfo("تم", "تم التصدير إلى:\n%s" % path, parent=self)

    def export_daily_csv(self):
        day = self.e_rep_date.text().strip() or date.today().isoformat()
        try:
            sales = self.db.sales_on(day)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        rows = [(s["invoice_no"], s["date"], s["cashier"], s["total"], s["payment_method"], s["status"]) for s in sales if s["status"] == "completed"]
        self._export_csv("daily_sales_%s.csv" % day, ["invoice", "date", "cashier", "total", "payment", "status"], rows)

    def export_best_csv(self):
        day = self.e_rep_date.text().strip() or date.today().isoformat()
        try:
            rows = [(b["trade_en"], b["units"], b["total"]) for b in self.db.report_best_sellers(day)]
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        self._export_csv("best_sellers.csv", ["drug", "units", "total"], rows)

    def export_inventory_csv(self):
        rows, _tc, _ts = self.db.report_inventory_value()
        self._export_csv("inventory_value.csv", ["drug", "units", "cost_value", "sell_value"], [(r["trade_en"], r["units"], r["cost_value"], r["sell_value"]) for r in rows])

    def show_inventory_value(self):
        rows, tc, ts = self.db.report_inventory_value()
        lines = ["قيمة المخزون الإجمالية:\nبالتكلفة: %s\nبسعر البيع: %s\nعدد الأصناف: %d\n" % (money(tc), money(ts), len(rows))]
        for r in rows[:60]:
            lines.append("- %s: %s وحدة — تكلفة %s" % (r["trade_en"], r["units"], money(r["cost_value"] or 0)))
        messagebox.TextViewerDialog(self, "قيمة المخزون", "\n".join(lines), width=740).exec()

    # =========================================================================
    # Cash / Shifts (Tab 6)
    # =========================================================================
    def build_cash(self, outer=None):
        container = outer or self._tab_widgets[6]
        outer_lay = QVBoxLayout(container)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll, _inner, tab = ui_theme.make_scroll_page("cashInner")
        outer_lay.addWidget(scroll)

        shift_card = CardWidget()
        sc_lay = QVBoxLayout(shift_card)
        sc_lay.setContentsMargins(14, 12, 14, 12)
        sc_lay.setSpacing(8)
        self.lbl_shift = StrongBodyLabel("")
        self.lbl_shift.setWordWrap(True)
        sc_lay.addWidget(self.lbl_shift)

        srow = QHBoxLayout()
        srow.setSpacing(8)
        b_open = PrimaryPushButton("فتح وردية جديدة")
        b_open.clicked.connect(self.open_shift_dialog)
        b_join = PushButton("انضمام للوردية")
        b_join.clicked.connect(self.join_shift_dialog)
        b_close = PushButton("إغلاق الوردية الحالية")
        b_close.clicked.connect(self.close_shift_dialog)
        b_leave = PushButton("مغادرة الوردية")
        b_leave.clicked.connect(self.leave_shift_dialog)
        srow.addWidget(b_open)
        srow.addWidget(b_join)
        srow.addWidget(b_close)
        srow.addWidget(b_leave)
        srow.addWidget(BodyLabel("رصيد أول المدة:"))
        self.e_float = LineEdit()
        self.e_float.setText("0")
        self.e_float.setFixedWidth(100)
        srow.addWidget(self.e_float)
        srow.addStretch(1)
        sc_lay.addLayout(srow)
        tab.addWidget(shift_card)

        exp_card = CardWidget()
        ec_lay = QVBoxLayout(exp_card)
        ec_lay.setContentsMargins(14, 12, 14, 12)
        ec_lay.setSpacing(8)
        ec_lay.addWidget(StrongBodyLabel("إضافة مصروف:"))
        erow = QHBoxLayout()
        erow.addWidget(BodyLabel("النوع (إيجار / رواتب / كهرباء / أخرى):"))
        self.e_exp_kind = LineEdit()
        self.e_exp_kind.setFixedWidth(160)
        erow.addWidget(self.e_exp_kind)
        erow.addWidget(BodyLabel("المبلغ:"))
        self.e_exp_amt = LineEdit()
        self.e_exp_amt.setFixedWidth(100)
        erow.addWidget(self.e_exp_amt)
        erow.addWidget(BodyLabel("ملاحظات:"))
        self.e_exp_notes = LineEdit()
        erow.addWidget(self.e_exp_notes, 1)
        b_exp = PrimaryPushButton("حفظ المصروف")
        b_exp.clicked.connect(self.add_expense)
        erow.addWidget(b_exp)
        ec_lay.addLayout(erow)

        ec_lay.addWidget(StrongBodyLabel("مصروفات اليوم:"))
        self.tree_exp = TableWidget()
        ui_theme.configure_table(self.tree_exp, ("النوع", "المبلغ", "ملاحظات", "المستخدم"), (180, 140, 280, 140), stretch_cols=(2,), min_height=240)
        ec_lay.addWidget(self.tree_exp, 1)
        b_ref = PushButton("تحديث")
        b_ref.clicked.connect(self.cash_refresh)
        ec_lay.addWidget(b_ref, 0, Qt.AlignLeft)
        tab.addWidget(exp_card, 1)

        self.cash_refresh()

    def cash_refresh(self):
        if not hasattr(self, "lbl_shift"):
            return
        if self.current_shift:
            members = "، ".join(m["username"] for m in self.db.shift_members(self.current_shift["id"]))
            flt = (" — رصيد أول المدة %s" % money(self.current_shift["opening_float"])) if self.is_admin else ""
            self.lbl_shift.setText("الوردية الحالية: #%d — فتحت %s%s — الموظفون: %s" % (self.current_shift["id"], self.current_shift["opened_at"], flt, members))
        else:
            self.lbl_shift.setText("لا توجد وردية مفتوحة — افتح وردية قبل البيع")
        ui_theme.set_table_rows(
            self.tree_exp,
            [(e["kind"], money(e["amount"]), e["notes"], e["user"]) for e in self.db.expenses_on()],
        )
        self.update_topbar()

    def open_shift_dialog(self):
        if self.current_shift:
            messagebox.showinfo("تنبيه", "توجد وردية مفتوحة بالفعل", parent=self)
            return
        try:
            sid = self.db.open_shift(self.username, safe_float(self.e_float.text()))
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        self.current_shift = self.db.open_shift_for(self.username)
        self.cash_refresh()
        messagebox.showinfo("تم", "تم فتح الوردية #%d" % sid, parent=self)

    def join_shift_dialog(self):
        try:
            sid = self.db.join_shift(self.username)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        self.current_shift = self.db.open_shift_for(self.username)
        self.cash_refresh()
        messagebox.showinfo("تم", "انضممت للوردية #%d" % sid, parent=self)

    def leave_shift_dialog(self):
        if not self.current_shift:
            messagebox.showinfo("تنبيه", "لا توجد وردية مفتوحة", parent=self)
            return
        if not messagebox.askyesno("مغادرة الوردية", "ستغادر الوردية وتسجل انصرافك. الوردية تظل مفتوحة لباقي الزملاء. متأكد؟", parent=self):
            return
        try:
            self.db.leave_shift(self.username)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        self.current_shift = None
        self.cash_refresh()

    def close_shift_dialog(self):
        if not self.current_shift:
            messagebox.showinfo("تنبيه", "لا توجد وردية مفتوحة", parent=self)
            return
        if not self.db.can_close_shift(self.current_shift["id"], self.username):
            messagebox.showwarning("غير مسموح", "إغلاق الوردية للمدير أو للموظف الذي فتحها فقط. يمكنك مغادرتها وتسجيل انصرافك.", parent=self)
            return
        try:
            summ = self.db.shift_summary(self.current_shift["id"])
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        no_shift_txt = ""
        if summ.get("no_shift_count"):
            no_shift_txt = "\n⚠️ مبيعات بدون وردية (%s): %d فاتورة بإجمالي %s — ليست محسوبة في هذه الوردية، راجعها قبل الإغلاق." % (
                summ["no_shift_date"], summ["no_shift_count"], money(summ["no_shift_total"])
            )
        counted = messagebox.askfloat(
            "إغلاق الوردية",
            "عدّ النقدية في الدرج وأدخل المبلغ.\nالمتوقع والفرق يظهران بعد تأكيد العدّ.%s\n\nأدخل المبلغ الذي عدّدته في الدرج:" % no_shift_txt,
            parent=self,
        )
        if counted is None:
            return
        if not messagebox.askyesno("تأكيد العدّ", "المبلغ الذي عدّدته: %s\nبعد التأكيد يُغلق الدرج ويظهر المتوقع والفرق. تأكيد؟" % money(counted), parent=self):
            return
        try:
            summ = self.db.close_shift(self.current_shift["id"], counted, actor=self.username)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e), parent=self)
            return
        self.current_shift = None
        self.cash_refresh()
        diff = summ["difference"]
        done_txt = "المتوقع في الدرج: %s\nالذي عدّدته: %s\nالفرق: %s %s" % (
            money(summ["expected_cash"]), money(summ["counted_cash"]), money(abs(diff)),
            "(زيادة)" if diff > 0 else ("(عجز)" if diff < 0 else "(مطابق ✅)"),
        )
        if summ.get("no_shift_count"):
            done_txt += "\n\n⚠️ تذكير: توجد %d فاتورة بدون وردية (%s) بإجمالي %s لم تُحسب في هذه الوردية." % (
                summ["no_shift_count"], summ["no_shift_date"], money(summ["no_shift_total"])
            )
        messagebox.showinfo("تم إغلاق الوردية", done_txt, parent=self)

    def add_expense(self):
        if not self.e_exp_kind.text().strip() or safe_float(self.e_exp_amt.text()) <= 0:
            messagebox.showerror("خطأ", "أدخل نوع المصروف والمبلغ", parent=self)
            return
        self.db.add_expense(
            self.e_exp_kind.text().strip(), safe_float(self.e_exp_amt.text()),
            self.e_exp_notes.text().strip(), self.username,
            shift_id=self.current_shift["id"] if self.current_shift else None,
        )
        self.e_exp_amt.clear()
        self.e_exp_notes.clear()
        self.cash_refresh()
        self.reports_refresh()

    # =========================================================================
    # AI Forecasting (Tab 8)
    # =========================================================================
    def build_ai(self, outer=None):
        container = outer or self._tab_widgets[8]
        outer_lay = QVBoxLayout(container)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll, _inner, tab = ui_theme.make_scroll_page("aiInner")
        outer_lay.addWidget(scroll)

        self.ai_reorder = []
        self.ai_expiry = []
        self.ai_forecasts = {}
        self.ai_selected_drug = None
        if ai_forecast is None:
            err = SubtitleLabel("⚠️ ملف ai_forecast.py غير موجود — انسخ ملفات التحديث v2 كاملة.")
            err.setStyleSheet(f"color: {self.pal['danger']};")
            tab.addWidget(err)
            return

        top_card = CardWidget()
        top = QHBoxLayout(top_card)
        top.setContentsMargins(12, 10, 12, 10)
        top.setSpacing(8)
        top.addWidget(BodyLabel("أفق التنبؤ (يوم):"))
        self.e_ai_horizon = LineEdit()
        self.e_ai_horizon.setText("30")
        self.e_ai_horizon.setFixedWidth(75)
        top.addWidget(self.e_ai_horizon)
        top.addWidget(BodyLabel("مدة التوريد (يوم):"))
        self.e_ai_lead = LineEdit()
        self.e_ai_lead.setText("3")
        self.e_ai_lead.setFixedWidth(75)
        top.addWidget(self.e_ai_lead)

        b_ref = PrimaryPushButton("🔄 تحديث التنبؤ")
        b_ref.clicked.connect(self.ai_refresh)
        b_ord = PushButton("📋 إنشاء قائمة طلب")
        b_ord.clicked.connect(self.ai_create_order_list)
        b_exp = PushButton("📥 تصدير قائمة الطلب CSV")
        b_exp.clicked.connect(self.ai_export_reorder_csv)
        top.addWidget(b_ref)
        top.addWidget(b_ord)
        top.addWidget(b_exp)
        top.addStretch(1)
        tab.addWidget(top_card)

        self.lbl_ai_summary = StrongBodyLabel("")
        self.lbl_ai_summary.setWordWrap(True)
        tab.addWidget(self.lbl_ai_summary)

        self.lbl_ai_note = CaptionLabel(
            "التنبؤ تقديري ويعتمد على مبيعاتك المسجلة فقط — كل ما تبيع أكتر، الدقة تزيد. "
            "مع تاريخ قليل تظهر ثقة منخفضة، وهذا مقصود: لا نريد أن يطلب البرنامج كميات كبيرة من تخمين ضعيف."
        )
        self.lbl_ai_note.setWordWrap(True)
        tab.addWidget(self.lbl_ai_note)

        ai_grid = QGridLayout()
        ai_grid.setSpacing(10)
        self.ai_cards = {}
        for idx, (_key, _title, _acc) in enumerate([
            ("critical", "حرجة تحتاج طلب", self.pal["danger"]),
            ("high", "عالية الأولوية", self.pal["warning"]),
            ("loss", "خسارة صلاحية متوقعة", self.pal["danger"]),
        ]):
            card = ui_theme.StatCard(_title, "—", "", _acc)
            ai_grid.addWidget(card, 0, idx)
            self.ai_cards[_key] = card
        tab.addLayout(ai_grid)

        tab.addWidget(StrongBodyLabel("قائمة إعادة الطلب المقترحة (اضغط على سطر لعرض التفاصيل):"))
        self.tree_ai = TableWidget()
        ui_theme.configure_table(
            self.tree_ai,
            ("الدواء", "المخزون (علبة)", "مبيعات/يوم (وحدة)", "توقع 30 يوم (وحدة)", "نقطة إعادة الطلب", "الكمية المقترحة (علبة)", "المورد الأرخص", "الأولوية", "الثقة %"),
            (200, 105, 115, 115, 110, 125, 140, 85, 75),
            stretch_cols=(0,),
            min_height=220,
        )
        self.tree_ai.itemSelectionChanged.connect(self.ai_show_detail)
        tab.addWidget(self.tree_ai)

        self.lbl_ai_detail = BodyLabel("اختر دواء من القائمة أعلاه لعرض تفاصيل التنبؤ.")
        self.lbl_ai_detail.setWordWrap(True)
        tab.addWidget(self.lbl_ai_detail)

        self.txt_ai_chart = TextEdit()
        self.txt_ai_chart.setReadOnly(True)
        self.txt_ai_chart.setFont(ui_theme.qfont(10, family="Consolas"))
        self.txt_ai_chart.setFixedHeight(140)
        tab.addWidget(self.txt_ai_chart)

        tab.addWidget(StrongBodyLabel("خطر انتهاء الصلاحية — الخسارة المتوقعة خلال 90 يوم:"))
        self.tree_ai_exp = TableWidget()
        ui_theme.configure_table(
            self.tree_ai_exp,
            ("الدواء", "التشغيلة", "تاريخ الصلاحية", "الكمية (وحدة)", "المتوقع بيعه", "الخسارة المتوقعة (ج.م)", "الاقتراح"),
            (180, 110, 115, 105, 105, 130, 260),
            stretch_cols=(6,),
            min_height=200,
        )
        tab.addWidget(self.tree_ai_exp)
        self.ai_refresh()

    def ai_refresh(self):
        if ai_forecast is None:
            return
        horizon = max(7, min(90, safe_int(self.e_ai_horizon.text(), 30)))
        lead = max(1, min(14, safe_int(self.e_ai_lead.text(), 3)))
        self.ai_horizon = horizon
        self.ai_lead = lead
        try:
            self.ai_reorder = ai_forecast.generate_reorder_list(self.db, horizon_days=horizon, lead_time_days=lead, safety_days=2)
        except Exception as e:
            messagebox.showerror("خطأ في التنبؤ", str(e), parent=self)
            self.ai_reorder = []
        self.ai_forecasts = {}
        for r in self.ai_reorder:
            self.ai_forecasts[r["drug_id"]] = r
            try:
                self.db.cache_forecast(r["drug_id"], horizon, r["daily_rate"], r["forecast_total"], r["confidence"])
            except Exception:
                pass
        self.ai_visible = [r for r in self.ai_reorder if r["urgency"] in ("حرجة", "عالية", "عادية")]
        if not self.ai_visible:
            ui_theme.set_table_rows(self.tree_ai, [("لا توجد أصناف تحتاج طلب حالياً ✅", "—", "—", "—", "—", "—", "—", "—", "—")])
        else:
            p = ui_theme.palette(self.theme_name, self.ui_accent)
            rows = [
                (
                    r["drug_name"], "%.1f" % r["stock_boxes"], "%.2f" % r["daily_rate"],
                    "%.0f" % r["forecast_total"], "%.0f" % r["reorder_point"],
                    r["suggested_boxes"], r["supplier_name"], r["urgency"], "%d%%" % r["confidence"],
                )
                for r in self.ai_visible
            ]
            styles = [
                (p["danger"], p["danger_bg"]) if r["urgency"] == "حرجة"
                else ((p["warning"], p["warning_bg"]) if r["urgency"] == "عالية" else None)
                for r in self.ai_visible
            ]
            ui_theme.set_table_rows(self.tree_ai, rows, styles)

        try:
            self.ai_expiry, total_loss = ai_forecast.expiry_risk_for_all(self.db, horizon_days=horizon)
        except Exception:
            self.ai_expiry, total_loss = [], 0.0
        p = ui_theme.palette(self.theme_name, self.ui_accent)
        exp_rows = []
        exp_styles = []
        for row in self.ai_expiry:
            if row["unsold_units"] <= 0:
                continue
            exp_rows.append((row["drug"], row["batch_no"], row["expiry"], row["qty_units"], row["expected_sell"], "%.2f" % row["loss_egp"], "%s (%s)" % (row["suggestion"], row["risk"])))
            exp_styles.append(
                (p["danger"], p["danger_bg"]) if row["risk"] == "عالية"
                else ((p["warning"], p["warning_bg"]) if row["risk"] == "متوسطة" else (p["success"], p["success_bg"]))
            )
        ui_theme.set_table_rows(self.tree_ai_exp, exp_rows, exp_styles)

        try:
            fastest, slowest = ai_forecast.get_movers(self.db, days=30, limit=5)
        except Exception:
            fastest, slowest = [], []
        critical = [r for r in self.ai_reorder if r["urgency"] == "حرجة"]
        high = [r for r in self.ai_reorder if r["urgency"] == "عالية"]
        total_sold_30d = sum(f["units"] for f in fastest)
        if total_sold_30d == 0:
            fast_txt = "لا توجد مبيعات بعد"
            slow_txt = "لا توجد مبيعات بعد — لا يمكن تحديد الراكد"
        else:
            fast_txt = ", ".join("%s (%d)" % (f["drug_name"], f["units"]) for f in fastest[:3]) or "لا توجد مبيعات بعد"
            slow_txt = ", ".join("%s (%d)" % (s["drug_name"], s["units"]) for s in slowest[:3]) or "—"
        low_conf = [r for r in self.ai_reorder if r["daily_rate"] > 0 and r["confidence"] < 40]
        self.lbl_ai_summary.setText(
            "🧾 أصناف تحتاج طلب الآن: %d حرجة + %d عالية  |  💸 خسارة صلاحية متوقعة هذا الشهر: %s\n"
            "⚡ الأسرع مبيعاً (30 يوم): %s\n🐢 الأبطأ (مخزون راكد): %s\n"
            "⚠️ %d صنف بتنبؤ ثقة منخفضة (<40%%) — اعتمد على خبرتك قبل الطلب بكميات كبيرة."
            % (len(critical), len(high), money(total_loss), fast_txt, slow_txt, len(low_conf))
        )
        try:
            self.ai_cards["critical"].set_values(str(len(critical)))
            self.ai_cards["high"].set_values(str(len(high)))
            self.ai_cards["loss"].set_values(money(total_loss), "تشغيلات تنتهي خلال 90 يوم")
        except Exception:
            pass
        if not fastest or sum(f["units"] for f in fastest) == 0:
            self.lbl_ai_note.setText(
                "لا توجد مبيعات مسجلة بعد في قاعدة البيانات — التنبؤ الآن تقديري جداً. "
                "سجّل مبيعات ومشتريات لمدة أسبوعين على الأقل وستبدأ الثقة والدقة في الارتفاع."
            )
        elif low_conf:
            self.lbl_ai_note.setText("⚠️ %d صنف بتنبؤ ثقة منخفضة (<40%%) — اعتمد على خبرتك قبل الطلب بكميات كبيرة." % len(low_conf))
        else:
            self.lbl_ai_note.setText("التنبؤ تقديري ويعتمد على مبيعاتك المسجلة فقط — كل ما تبيع أكتر، الدقة تزيد.")

    def ai_show_detail(self):
        idx = ui_theme.selected_row_index(self.tree_ai)
        if idx is None or idx >= len(getattr(self, "ai_visible", [])):
            return
        row = self.ai_visible[idx]
        drug = self.db.get_drug(row["drug_id"])
        if not drug:
            return
        self.ai_selected_drug = drug
        try:
            daily = ai_forecast.get_daily_sales(self.db, drug["id"], days=90)
        except Exception:
            daily = []
        stock_days = ("%.1f يوم" % row["days_of_stock"]) if row["days_of_stock"] < 900 else "— (لا يوجد معدل بيع)"
        self.lbl_ai_detail.setText(
            "تفاصيل: %s — معدل البيع %.2f وحدة/يوم | الاتجاه: %s (%+.1f%%) | الثقة: %d%%\n"
            "المخزون الحالي يكفي %s | نقطة إعادة الطلب: %.0f وحدة | الكمية المقترحة: %d علبة (%d وحدة) | الطريقة: %s"
            % (
                row["drug_name"], row["daily_rate"], row["trend"], row["trend_pct"],
                row["confidence"], stock_days, row["reorder_point"],
                row["suggested_boxes"], row["suggested_units"], row["method"],
            )
        )
        try:
            self.txt_ai_chart.setPlainText("مبيعات آخر 14 يوم (وحدة/يوم):\n" + ai_forecast.text_chart(daily, days=14))
        except Exception:
            pass

    def ai_create_order_list(self):
        if not getattr(self, "ai_visible", None):
            messagebox.showinfo("تنبيه", "لا توجد أصناف تحتاج طلب حالياً — حدّث التنبؤ أولاً", parent=self)
            return
        need = [r for r in self.ai_visible if r["suggested_boxes"] > 0]
        if not need:
            messagebox.showinfo("تنبيه", "لا توجد كميات مقترحة — المخزون يغطي توقع الـ %d يوم القادمة" % getattr(self, "ai_horizon", 30), parent=self)
            return
        by_supplier = {}
        for r in need:
            by_supplier.setdefault(r["supplier_name"], []).append(r)

        total_est = 0.0
        lines = ["قائمة طلب مقترحة من التنبؤ الذكي — مسودة للمراجعة قبل الشراء:\n"]
        for sup, items in by_supplier.items():
            lines.append("المورد: %s" % sup)
            for r in items:
                est = (r["supplier_price"] or 0) * r["suggested_boxes"]
                total_est += est
                lines.append(
                    "  - %s: %d علبة (أولوية %s، ثقة %d%%)%s"
                    % (r["drug_name"], r["suggested_boxes"], r["urgency"], r["confidence"],
                       " — تكلفة تقديرية %s" % money(est) if r["supplier_price"] else "")
                )
            lines.append("")
        lines.append("التكلفة التقديرية الإجمالية: %s\n" % money(total_est))
        lines.append("⚠️ هذه مسودة فقط — راجع الكميات مع المورد قبل تأكيد أي شراء. لا يتم إنشاء فاتورة شراء تلقائياً.")

        def add_to_purchase_draft(dlg):
            self.goto_tab(3)  # build purchases tab if lazy
            added = 0
            for r in need:
                drug = self.db.get_drug(r["drug_id"])
                if not drug:
                    continue
                self.purchase_lines.append({
                    "drug": drug, "qty_boxes": float(r["suggested_boxes"]),
                    "buy_price": float(r["supplier_price"] or drug["buy_price"]),
                    "sell_price": float(drug["sell_price"]),
                    "batch_no": "AI-%s" % date.today().isoformat(),
                    "expiry": "2027-12-31",
                })
                added += 1
            self.pur_refresh_table()
            sups = [s for s in self.db.suppliers() if s["name"] in by_supplier]
            if sups and hasattr(self, "cb_supplier"):
                idx = self.cb_supplier.findText(sups[0]["name"])
                if idx >= 0:
                    self.cb_supplier.setCurrentIndex(idx)
            self.db.audit(self.username, "ai_order_draft", "%d lines from AI forecast" % added)
            dlg.accept()
            messagebox.showinfo(
                "تم",
                "تمت إضافة %d صنف كمسودة فاتورة شراء.\nراجع الكميات والأسعار والتشغيلات والصلاحية ثم اضغط «حفظ فاتورة الشراء»." % added,
                parent=self,
            )

        messagebox.TextViewerDialog(
            self, "قائمة الطلب المقترحة — مسودة (لم تُحفظ بعد)", "\n".join(lines),
            width=740, height=500,
            extra_buttons=[("➕ إضافة القائمة كمسودة فاتورة شراء (للمراجعة)", add_to_purchase_draft, True)],
        ).exec()

    def ai_export_reorder_csv(self):
        if not getattr(self, "ai_visible", None):
            messagebox.showinfo("تنبيه", "حدّث التنبؤ أولاً", parent=self)
            return
        rows = [
            (
                r["drug_name"], "%.1f" % r["stock_boxes"], "%.2f" % r["daily_rate"],
                "%.0f" % r["forecast_total"], "%.0f" % r["reorder_point"],
                r["suggested_boxes"], r["supplier_name"], r["urgency"], "%d%%" % r["confidence"],
            )
            for r in self.ai_visible
        ]
        self._export_csv(
            "ai_reorder_%s.csv" % date.today().isoformat(),
            ["drug", "stock_boxes", "daily_rate", "forecast_30d", "reorder_point", "suggested_boxes", "cheapest_supplier", "urgency", "confidence_pct"],
            rows,
        )
