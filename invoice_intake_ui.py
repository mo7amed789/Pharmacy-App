# -*- coding: utf-8 -*-
"""Tk review dialog for supplier-invoice photo intake. Draft only."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import invoice_intake as ii
import ui_theme


def open_invoice_intake(app):
    if not getattr(app, "is_admin", False):
        messagebox.showerror("صلاحيات", "هذه الصفحة للمدير فقط", parent=app.root)
        return
    """app = the main window object (needs .root, .db, .purchase_lines,
    .pur_refresh_table, .e_pur_inv, .username). Nothing is saved here."""
    path = filedialog.askopenfilename(
        parent=app.root, title="اختر صورة فاتورة المورد",
        filetypes=[("صور", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"), ("كل الملفات", "*.*")])
    if not path:
        return
    try:
        app.root.config(cursor="watch")
        app.root.update_idletasks()
        text = ii.ocr_image(path)
    except ii.OcrUnavailable as e:
        messagebox.showerror("قراءة الفاتورة", str(e), parent=app.root)
        return
    finally:
        app.root.config(cursor="")
    parsed = ii.annotate(app.db, ii.parse_invoice_text(text))
    if ii.known_invoice(app.db, parsed.get("invoice_no")):
        if not messagebox.askyesno(
                "فاتورة مكررة؟", "رقم الفاتورة %s مسجل من قبل في المشتريات. قد تكون نفس الفاتورة. هل تكمل؟" % parsed["invoice_no"],
                parent=app.root):
            return
    if not parsed["lines"]:
        messagebox.showinfo("قراءة الفاتورة",
                            "لم أتعرف على أي سطور. جرّب صورة أوضح ومستقيمة وبإضاءة جيدة.",
                            parent=app.root)
        return
    _review(app, parsed)


def _review(app, parsed):
    win = tk.Toplevel(app.root)
    win.title("مراجعة فاتورة المورد (لن يتم حفظ شيء قبل ضغطك على حفظ)")
    ui_theme.fit_dialog(win, 1100, 520)
    ttk.Label(win, text="راجع كل سطر. الصنف المقترح لا يُعتمد إلا بعد تأكيدك (زر تأكيد الصنف). الصلاحية لازم تاريخ كامل. لا يتم تخمين أي رقم.",
              wraplength=900).pack(anchor="w", padx=10, pady=6)
    cols = ("status", "name", "drug", "qty", "price", "exp", "batch")
    tv = ttk.Treeview(win, columns=cols, show="headings", height=14)
    for c, t, w in zip(cols, ("الحالة", "كما في الفاتورة", "الصنف في البرنامج", "علب", "سعر العلبة (يُؤكَّد)", "الصلاحية", "التشغيلة"),
                       (340, 200, 200, 50, 80, 90, 80)):
        tv.heading(c, text=t)
        tv.column(c, width=w)
    tv.tag_configure("bad", foreground="#b00020")
    tv.tag_configure("ok", foreground="#1b5e20")
    lines = parsed["lines"]

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
        tv.delete(*tv.get_children())
        for i, ln in enumerate(lines):
            miss = status(ln)
            warn = [f for f in ln["flags"] if f not in ("التشغيلة غير مقروءة",) and "اقتراح" not in f or "تحذير" in f]
            st = ("ناقص: " + "، ".join(miss)) if miss else ("✔ جاهز" + (" (راجع: %s)" % warn[0] if warn else ""))
            tv.insert("", "end", iid=str(i), tags=("bad" if miss or warn else "ok",), values=(
                st, ln["name"], ln["drug"]["trade_en"] if ln.get("drug") else ("؟ " + ln["suggestion"]["trade_en"] if ln.get("suggestion") else "—"),
                "" if ln.get("qty") is None else int(ln["qty"]) if ln["qty"] == int(ln["qty"]) else ln["qty"],
                "" if ln.get("price") is None else ln["price"], ln.get("expiry") or "", ln.get("batch") or ""))

    def sel():
        s = tv.selection()
        return lines[int(s[0])] if s else None

    def confirm_suggestion():
        ln = sel()
        if not ln or not ln.get("suggestion"):
            messagebox.showinfo("تأكيد", "لا يوجد اقتراح لهذا السطر. استخدم اختيار الصنف.", parent=win)
            return
        sg = ln["suggestion"]
        if messagebox.askyesno("تأكيد الصنف", "في الفاتورة:\n%s\n\nفي البرنامج:\n%s  %s\n\nهل هما نفس الدواء والتركيز والعبوة؟" % (
                ln["name"], sg["trade_en"], sg["strength"] or ""), parent=win):
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
        if messagebox.askyesno("الصلاحية", "الفاتورة تحمل %s فقط. هل تعتمد آخر يوم في الشهر (%s)؟" % (ln["expiry_month"], last), parent=win):
            ln["expiry"] = last
            refresh()

    def pick_drug():
        ln = sel()
        if not ln:
            return
        d = tk.Toplevel(win)
        d.title("اختر الصنف")
        ui_theme.fit_dialog(d, 520, 420)
        e = ttk.Entry(d, width=40)
        e.pack(padx=8, pady=6)
        e.insert(0, ln["name"])
        lb = tk.Listbox(d, height=14)
        lb.pack(fill="both", expand=True, padx=8)
        res = []

        def search(*_):
            res[:] = app.db.search_drugs(e.get(), limit=40)
            lb.delete(0, "end")
            for r in res:
                lb.insert("end", "%s  %s" % (r["trade_en"], r["strength"] or ""))

        def choose(*_):
            if lb.curselection():
                ln["drug"] = res[lb.curselection()[0]]  # explicit user pick
                d.destroy()
                refresh()
        e.bind("<KeyRelease>", search)
        lb.bind("<Double-Button-1>", choose)
        ttk.Button(d, text="اختيار", command=choose).pack(pady=6)
        search()

    def edit():
        ln = sel()
        if not ln:
            return
        for key, label, conv in (("qty", "عدد العلب", float), ("price", "سعر شراء العلبة", float),
                                 ("expiry", "الصلاحية YYYY-MM-DD", str), ("batch", "رقم التشغيلة", str)):
            v = simpledialog.askstring("تعديل", label, initialvalue="" if ln.get(key) is None else str(ln[key]), parent=win)
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
            ln["numbers_confirmed"] = True  # user went through every number
        refresh()

    def drop():
        ln = sel()
        if ln:
            lines.remove(ln)
            refresh()

    basis = tk.BooleanVar(value=False)

    def add_ready():
        if not basis.get():
            messagebox.showwarning(
                "أساس السعر", "أكّد أولا أن السعر في الفاتورة هو سعر شراء العلبة الواحدة الذي تريد تسجيله كتكلفة "
                "(بعد الخصم وبالضريبة كما تحاسب بها). حدد خانة التأكيد أسفل الجدول.", parent=win)
            return
        ready, left = ii.to_purchase_lines(lines, app.purchase_lines)
        if not ready:
            messagebox.showinfo("مراجعة", "لا يوجد سطر جاهز بعد.", parent=win)
            return
        if left and not messagebox.askyesno(
                "أسطر ناقصة", "يوجد %d سطر ناقص لن يُضاف. أضيف %d سطر الجاهز فقط كمسودة؟" % (len(left), len(ready)), parent=win):
            return
        app.purchase_lines.extend(ready)
        if parsed.get("invoice_no") and hasattr(app, "e_pur_inv") and not app.e_pur_inv.get().strip():
            app.e_pur_inv.insert(0, parsed["invoice_no"])
        app.pur_refresh_table()
        try:
            app.db.audit(app.username, "invoice_photo_draft", "%d lines drafted from invoice photo" % len(ready))
        except Exception:
            pass
        win.destroy()
        messagebox.showinfo("تم", "أُضيف %d سطر كمسودة. راجع المورد والمدفوع ثم اضغط «حفظ فاتورة الشراء»." % len(ready),
                            parent=app.root)

    tk.Checkbutton(win, variable=basis, justify="right", anchor="w", text="أؤكد: السعر = سعر شراء العلبة الواحدة (وليس القطعة/الشريط ولا الإجمالي)، "
                    "بعد الخصم وبنفس طريقة الضريبة التي أسجل بها التكلفة. سيتحدث سعر تكلفة الصنف بهذا الرقم.",
                    wraplength=1000).pack(side="bottom", anchor="w", padx=10, pady=(6, 0))
    bar = ttk.Frame(win)
    bar.pack(side="bottom", fill="x", padx=8, pady=8)
    ttk.Button(bar, text="تأكيد الصنف المقترح", command=confirm_suggestion).pack(side="left", padx=3)
    ttk.Button(bar, text="آخر يوم في الشهر", command=month_end).pack(side="left", padx=3)
    ttk.Button(bar, text="اختيار الصنف", command=pick_drug).pack(side="left", padx=3)
    ttk.Button(bar, text="تعديل الأرقام", command=edit).pack(side="left", padx=3)
    ttk.Button(bar, text="حذف السطر", command=drop).pack(side="left", padx=3)
    ttk.Button(bar, text="➕ إضافة الجاهز كمسودة شراء", command=add_ready).pack(side="right", padx=3)
    ttk.Button(bar, text="إلغاء", command=win.destroy).pack(side="right", padx=3)
    tv.pack(fill="both", expand=True, padx=8)
    refresh()
