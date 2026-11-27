"""Admin-only publisher setup/review window (Fluent Qt). No keys displayed or collected."""
import json
import os

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TableWidget,
)

from availability_bridge import inventory_preview, mapping_candidates
from availability_sync import KEY_ENV, Store, start_worker
import ui_dialogs as messagebox
import ui_theme


def open_settings(app):
    if not app.is_admin:
        return
    path = app.db.path + ".availability.sqlite3"
    store = Store(path)

    win = QDialog(app)
    win.setWindowTitle("مزامنة توفر الأدوية - إعداد ومراجعة")
    win.setLayoutDirection(Qt.RightToLeft)
    win.setStyleSheet(ui_theme.window_qss())
    ui_theme.fit_dialog_widget(win, 980, 680)
    win.setMinimumSize(900, 560)

    lay = QVBoxLayout(win)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)

    lay.addWidget(SubtitleLabel("مزامنة التوفر منفصلة عن الكتالوج والفواتير. مقفولة افتراضياً."))
    warn = BodyLabel("لا تفعّل قبل تجهيز الموقع والفروع والمصادقة ومراجعة الربط على الطرفين. لا توجد مفاتيح في هذه الشاشة.")
    warn.setWordWrap(True)
    lay.addWidget(warn)

    config = store.config()
    lay.addWidget(CaptionLabel("HTTPS receiver URL"))
    e_endpoint = LineEdit()
    e_endpoint.setText(config["endpoint"])
    lay.addWidget(e_endpoint)

    lay.addWidget(CaptionLabel("Branch ID (UUID)"))
    e_branch = LineEdit()
    e_branch.setText(config["branch"])
    lay.addWidget(e_branch)

    lay.addWidget(CaptionLabel("Installation ID: " + config["installation"]))
    lbl_status = BodyLabel("")
    lbl_status.setWordWrap(True)
    lay.addWidget(lbl_status)

    rows = TableWidget()
    ui_theme.configure_table(
        rows,
        ("Local ID", "Local product / strength", "Units/box", "Platform medicine", "Review state"),
        (75, 250, 90, 290, 140),
        stretch_cols=(3,),
        min_height=240,
    )
    lay.addWidget(rows, 1)

    catalog = []
    candidates = []

    def refresh():
        c = store.config()
        p = store.pending()
        lbl_status.setText(
            ("ENABLED" if c["enabled"] else "DISABLED")
            + " | "
            + c["status"]
            + " | Reviewed: "
            + str(len(store.bindings()))
            + " | Queued: "
            + str(bool(p))
        )

    def guard(fn):
        try:
            fn()
            refresh()
        except Exception as exc:
            messagebox.showerror("تعذر إكمال الإعداد", str(exc), parent=win)

    def render_candidates():
        from database import units_per_box
        trows = []
        for c in candidates:
            d = dict(app.db.conn.execute("SELECT * FROM drugs WHERE id=?", (c["externalProductId"],)).fetchone())
            trows.append((
                c["externalProductId"],
                c["name"] + " / " + str(c["strength"]),
                units_per_box(d),
                ", ".join(c["candidateMedicineIds"]),
                c["status"],
            ))
        ui_theme.set_table_rows(rows, trows)

    def load_catalog():
        nonlocal catalog, candidates
        source = ui_dialogs_get_open(win)
        if not source:
            return
        if os.path.getsize(source) > 20 * 1024 * 1024:
            raise ValueError("Catalog too large")
        with open(source, encoding="utf-8") as f:
            catalog = json.load(f)
        if not isinstance(catalog, list):
            raise ValueError("Use an exported array of platform medicine DTOs")
        candidates = mapping_candidates(app.db, catalog)
        render_candidates()

    def ui_dialogs_get_open(parent):
        return messagebox.get_open_filename(parent=parent, filetypes=[("Platform catalog JSON", "*.json")])

    def review():
        idx = ui_theme.selected_row_index(rows)
        if idx is None or idx >= len(candidates):
            return
        candidate = candidates[idx]
        if len(candidate["candidateMedicineIds"]) != 1:
            raise ValueError("Exact unique box GTIN required; do not guess")
        mid = candidate["candidateMedicineIds"][0]
        remote = next(m for m in catalog if m["id"] == mid)
        d = dict(app.db.conn.execute("SELECT * FROM drugs WHERE id=?", (candidate["externalProductId"],)).fetchone())
        from database import units_per_box
        text = (
            "Local: %s / %s / %s\nLocal units per box: %s\n"
            "Platform: %s / %s / %s\nGTIN: %s\n\n"
            "راجع الاسم والتركيز والشكل والعبوة بالضبط على الجانبين. هل التطابق مؤكد؟\n"
            "Server binding must also be provisioned by the operator."
            % (
                candidate["name"], candidate["strength"], candidate["dosageForm"], units_per_box(d),
                remote.get("brandName", ""), remote.get("strength", ""), remote.get("dosageForm", ""),
                ", ".join(candidate["boxGtins"]),
            )
        )
        if not messagebox.askyesno("مراجعة عبوة واحدة", text, parent=win):
            return
        store.review(app.db, catalog, candidate["externalProductId"], mid)
        candidate["status"] = "reviewed locally"
        render_candidates()

    def export():
        store.configure(e_endpoint.text().strip(), e_branch.text().strip(), False)
        target = messagebox.get_save_filename(
            parent=win, initialfile="binding_manifest.json", filetypes=[("Reviewed binding manifest", "*.json")]
        )
        if target:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(store.provision_manifest(), f, indent=2, ensure_ascii=False)

    def preview():
        p = inventory_preview(app.db, store.bindings())
        if p["held"]:
            raise ValueError("Held mappings: " + str(len(p["held"])) + ". Review changed identity or prices before enabling.")
        messagebox.showinfo(
            "معاينة محلية فقط",
            "Reviewed items: %s\nExplicit zero: %s\nNo stock transmitted."
            % (len(p["items"]), sum(i["availableQuantity"] == 0 for i in p["items"])),
            parent=win,
        )

    def disable():
        store.disable()
        event = getattr(app, "_availability_stop", None)
        if event:
            event.set()

    def enable():
        if not store.bindings():
            raise ValueError("Review mappings and provision them on the server first")
        if not messagebox.askyesno(
            "تشغيل لاحق فقط",
            "هل جهزت الفرع والمكان والمصادقة والربط المراجع على السيرفر؟\n"
            "سيتم إرسال المخزون والأسعار للمنتجات المراجعة كل دقيقة.\n"
            "مفتاح الناشر مطلوب في متغير البيئة " + KEY_ENV,
            parent=win,
        ):
            return
        store.configure(e_endpoint.text().strip(), e_branch.text().strip(), True)
        event = getattr(app, "_availability_stop", None)
        if event:
            event.set()

        def restart_when_released():
            if event and event.thread.is_alive():
                QTimer.singleShot(250, restart_when_released)
            else:
                app._availability_stop = start_worker(app.db.path, path)

        restart_when_released()

    btns = QHBoxLayout()
    btns.setSpacing(6)
    for text, fn, prim in [
        ("تحميل كتالوج الموقع JSON", load_catalog, True),
        ("مراجعة المحدد", review, False),
        ("معاينة فقط", preview, False),
        ("حفظ وتصدير الربط", export, False),
        ("إيقاف", disable, False),
        ("تفعيل بعد التجهيز", enable, True),
    ]:
        b = PrimaryPushButton(text) if prim else PushButton(text)
        b.clicked.connect(lambda _c=False, f=fn: guard(f))
        btns.addWidget(b)
    btns.addStretch(1)
    lay.addLayout(btns)

    def _on_close(_e=None):
        try:
            store.close()
        except Exception:
            pass

    win.finished.connect(_on_close)
    refresh()
    win.exec()
    return win
