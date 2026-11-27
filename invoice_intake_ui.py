# -*- coding: utf-8 -*-
"""Fluent Qt review dialog for supplier-invoice photo intake. Draft only."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QListWidget, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    TableWidget,
)

import invoice_intake as ii
import ui_dialogs as messagebox
import ui_theme


def open_invoice_intake(app):
    if not getattr(app, "is_admin", False):
        messagebox.showerror("صلاحيات", "هذه الصفحة للمدير فقط", parent=app)
        return
    path = messagebox.get_open_filename(
        parent=app,
        title="اختر صورة فاتورة المورد",
        filetypes=[("صور", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"), ("كل الملفات", "*.*")],
    )
    if not path:
        return
    try:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        text = ii.ocr_image(path)
    except ii.OcrUnavailable as e:
        messagebox.showerror("قراءة الفاتورة", str(e), parent=app)
        return
    finally:
        QApplication.restoreOverrideCursor()

    parsed = ii.annotate(app.db, ii.parse_invoice_text(text))
    if ii.known_invoice(app.db, parsed.get("invoice_no")):
        if not messagebox.askyesno(
            "فاتورة مكررة؟",
            "رقم الفاتورة %s مسجل من قبل في المشتريات. قد تكون نفس الفاتورة. هل تكمل؟" % parsed["invoice_no"],
            parent=app,
        ):
            return
    if not parsed["lines"]:
        messagebox.showinfo(
            "قراءة الفاتورة",
            "لم أتعرف على أي سطور. جرّب صورة أوضح ومستقيمة وبإضاءة جيدة.",
            parent=app,
        )
        return
    _review(app, parsed)


def _review(app, parsed):
    win = QDialog(app)
    win.setWindowTitle("مراجعة فاتورة المورد (لن يتم حفظ شيء قبل ضغطك على حفظ)")
    win.setLayoutDirection(Qt.RightToLeft)
    win.setStyleSheet(ui_theme.window_qss())
    ui_theme.fit_dialog_widget(win, 1100, 560)

    lay = QVBoxLayout(win)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)

    note = BodyLabel(
        "راجع كل سطر. الصنف المقترح لا يُعتمد إلا بعد تأكيدك (زر تأكيد الصنف). "
        "الصلاحية لازم تاريخ كامل. لا يتم تخمين أي رقم."
    )
    note.setWordWrap(True)
    lay.addWidget(note)

    tv = TableWidget()
    ui_theme.configure_table(
        tv,
        ("الحالة", "كما في الفاتورة", "الصنف في البرنامج", "علب", "سعر العلبة (يُؤكَّد)", "الصلاحية", "التشغيلة"),
        (290, 195, 195, 60, 110, 110, 90),
        stretch_cols=(0,),
        min_height=260,
    )
    lay.addWidget(tv, 1)

    lines = parsed["lines"]
    p = ui_theme.palette()

    def status(ln):
        miss = []
        if not ln.get("drug"):
            miss.append("أكّد الصنف" if ln.get("suggestion") else "اختر الصنف")
        if not ln.get("qty") or ln["qty"] <= 0 or ln["qty"] != int(ln["qty"]):
            miss.append("الكمية")
        if not ln.get("price") or ln["price"] <= 0:
            miss.append("السعر")
        if not ln.get("expiry"):
            miss.append("الصلاحية (تاريخ كامل)")
        if any("≠" in f for f in ln["flags"]) and not ln.get("numbers_confirmed"):
            miss.append("راجع الأرقام")
        return miss

    def refresh():
        rows = []
        styles = []
        for ln in lines:
            miss = status(ln)
            warn = [f for f in ln["flags"] if f not in ("التشغيلة غير مقروءة",) and "اقتراح" not in f or "تحذير" in f]
            st = ("ناقص: " + "، ".join(miss)) if miss else ("✔ جاهز" + (" (راجع: %s)" % warn[0] if warn else ""))
            drug_col = (
                ln["drug"]["trade_en"]
                if ln.get("drug")
                else ("؟ " + ln["suggestion"]["trade_en"] if ln.get("suggestion") else "—")
            )
            qty_col = "" if ln.get("qty") is None else (int(ln["qty"]) if ln["qty"] == int(ln["qty"]) else ln["qty"])
            rows.append((
                st,
                ln["name"],
                drug_col,
                qty_col,
                "" if ln.get("price") is None else ln["price"],
                ln.get("expiry") or "",
                ln.get("batch") or "",
            ))
            styles.append((p["danger"], p["danger_bg"]) if (miss or warn) else (p["success"], p["success_bg"]))
        ui_theme.set_table_rows(tv, rows, styles)

    def sel():
        idx = ui_theme.selected_row_index(tv)
        return lines[idx] if idx is not None and 0 <= idx < len(lines) else None

    def confirm_suggestion():
        ln = sel()
        if not ln or not ln.get("suggestion"):
            messagebox.showinfo("تأكيد", "لا يوجد اقتراح لهذا السطر. استخدم اختيار الصنف.", parent=win)
            return
        sg = ln["suggestion"]
        if messagebox.askyesno(
            "تأكيد الصنف",
            "في الفاتورة:\n%s\n\nفي البرنامج:\n%s  %s\n\nهل هما نفس الدواء والتركيز والعبوة؟"
            % (ln["name"], sg["trade_en"], sg["strength"] or ""),
            parent=win,
        ):
            ln["drug"] = sg
            refresh()

    def month_end():
        ln = sel()
        if not ln or not ln.get("expiry_month"):
            messagebox.showinfo("الصلاحية", "السطر ليس شهر/سنة فقط. استخدم تعديل الأرقام.", parent=win)
            return
        import calendar
        y, m = [int(x) for x in ln["expiry_month"].split("-")]
        last = "%04d-%02d-%02d" % (y, m, calendar.monthrange(y, m)[1])
        if messagebox.askyesno(
            "الصلاحية",
            "الفاتورة تحمل %s فقط. هل تعتمد آخر يوم في الشهر (%s)؟" % (ln["expiry_month"], last),
            parent=win,
        ):
            ln["expiry"] = last
            refresh()

    def pick_drug():
        ln = sel()
        if not ln:
            return
        d = QDialog(win)
        d.setWindowTitle("اختر الصنف")
        d.setLayoutDirection(Qt.RightToLeft)
        d.setStyleSheet(ui_theme.window_qss())
        ui_theme.fit_dialog_widget(d, 520, 420)
        dl = QVBoxLayout(d)
        dl.setContentsMargins(14, 12, 14, 12)
        dl.setSpacing(8)
        e = SearchLineEdit()
        e.setText(ln["name"])
        dl.addWidget(e)
        lb = QListWidget()
        dl.addWidget(lb, 1)
        res = []

        def search(_txt=""):
            res[:] = app.db.search_drugs(e.text(), limit=40)
            lb.clear()
            for r in res:
                lb.addItem("%s  %s" % (r["trade_en"], r["strength"] or ""))

        def choose(*_):
            row = lb.currentRow()
            if 0 <= row < len(res):
                ln["drug"] = res[row]
                d.accept()
                refresh()

        e.textChanged.connect(search)
        lb.itemDoubleClicked.connect(choose)
        btn = PrimaryPushButton("اختيار")
        btn.clicked.connect(choose)
        dl.addWidget(btn)
        search()
        d.exec()

    def edit():
        ln = sel()
        if not ln:
            return
        for key, label, conv in (
            ("qty", "عدد العلب", float),
            ("price", "سعر شراء العلبة", float),
            ("expiry", "الصلاحية YYYY-MM-DD", str),
            ("batch", "رقم التشغيلة", str),
        ):
            v = messagebox.askstring(
                "تعديل", label,
                initialvalue="" if ln.get(key) is None else str(ln[key]),
                parent=win,
            )
            if v is None:
                refresh()
                return
            v = ii.norm_digits(v).strip()
            try:
                ln[key] = conv(v) if v else (None if conv is float else "")
            except ValueError:
                messagebox.showerror("خطأ", "قيمة غير صالحة: " + label, parent=win)
                break
        else:
            ln["numbers_confirmed"] = True
        refresh()

    def drop():
        ln = sel()
        if ln:
            lines.remove(ln)
            refresh()

    basis = CheckBox(
        "أؤكد: السعر = سعر شراء العلبة الواحدة (وليس القطعة/الشريط ولا الإجمالي)، "
        "بعد الخصم وبنفس طريقة الضريبة التي أسجل بها التكلفة. سيتحدث سعر تكلفة الصنف بهذا الرقم."
    )
    lay.addWidget(basis)

    def add_ready():
        if not basis.isChecked():
            messagebox.showwarning(
                "أساس السعر",
                "أكّد أولا أن السعر في الفاتورة هو سعر شراء العلبة الواحدة الذي تريد تسجيله كتكلفة "
                "(بعد الخصم وبالضريبة كما تحاسب بها). حدد خانة التأكيد أسفل الجدول.",
                parent=win,
            )
            return
        ready, left = ii.to_purchase_lines(lines, app.purchase_lines)
        if not ready:
            messagebox.showinfo("مراجعة", "لا يوجد سطر جاهز بعد.", parent=win)
            return
        if left and not messagebox.askyesno(
            "أسطر ناقصة",
            "يوجد %d سطر ناقص لن يُضاف. أضيف %d سطر الجاهز فقط كمسودة؟" % (len(left), len(ready)),
            parent=win,
        ):
            return
        app.purchase_lines.extend(ready)
        if parsed.get("invoice_no") and hasattr(app, "e_pur_inv") and not app.e_pur_inv.text().strip():
            app.e_pur_inv.setText(parsed["invoice_no"])
        app.pur_refresh_table()
        try:
            app.db.audit(app.username, "invoice_photo_draft", "%d lines drafted from invoice photo" % len(ready))
        except Exception:
            pass
        win.accept()
        messagebox.showinfo(
            "تم",
            "أُضيف %d سطر كمسودة. راجع المورد والمدفوع ثم اضغط «حفظ فاتورة الشراء»." % len(ready),
            parent=app,
        )

    bar = QHBoxLayout()
    bar.setSpacing(6)
    for label, fn in (
        ("تأكيد الصنف المقترح", confirm_suggestion),
        ("آخر يوم في الشهر", month_end),
        ("اختيار الصنف", pick_drug),
        ("تعديل الأرقام", edit),
        ("حذف السطر", drop),
    ):
        b = PushButton(label)
        b.clicked.connect(fn)
        bar.addWidget(b)
    bar.addStretch(1)
    b_add = PrimaryPushButton("➕ إضافة الجاهز كمسودة شراء")
    b_add.clicked.connect(add_ready)
    b_cancel = PushButton("إلغاء")
    b_cancel.clicked.connect(win.reject)
    bar.addWidget(b_add)
    bar.addWidget(b_cancel)
    lay.addLayout(bar)

    refresh()
    win.exec()
