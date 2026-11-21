"""v5.7 GUI smoke test under Xvfb: login (admin/admin123 -> forced
password change), main window with 10 tabs, POS sale through the UI,
reports reconcile with the DB, purchase, edit dialog opens, return,
shift open/close with reconciliation. Run: xvfb-run -a python3 tests/gui_smoke.py"""
import os
import shutil
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog
from datetime import date, timedelta

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "gui")
SRC = os.path.join(HERE, "..")
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (" | " + str(extra) if extra and not cond else ""), flush=True)

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
for f in os.listdir(SRC):
    if f.endswith((".py", ".html", ".js")):
        shutil.copy(os.path.join(SRC, f), os.path.join(WORK, f))
sys.path.insert(0, WORK)
os.chdir(WORK)

import main as M
from database import DB

# ---- patch dialogs: never block the test ----
calls = {"info": [], "error": []}
orig_info = messagebox.showinfo
orig_err = messagebox.showerror
def _info(title, msg, **kw):
    calls["info"].append((title, msg))
    return None
def _err(title, msg, **kw):
    calls["error"].append((title, msg))
    return None
messagebox.showinfo = _info
messagebox.showerror = _err
M.messagebox.showinfo = _info
M.messagebox.showerror = _err
M.messagebox.askyesno = lambda *a, **k: True
M.simpledialog.askfloat = lambda *a, **k: 125.0
M.simpledialog.askstring = lambda *a, **k: "INV-000001"

DB_PATH = os.path.join(WORK, "pharmacy.db")
db = DB(path=DB_PATH)
FUT = (date.today() + timedelta(days=365)).isoformat()

# ---------- 1. login + forced password change ----------
login = M.LoginWindow(db)
login.e_user.insert(0, "admin")
login.e_pass.insert(0, "admin123")
def fill_pw_dialog():
    for ch in login.root.winfo_children():
        if isinstance(ch, tk.Toplevel):
            entries = [w for w in ch.winfo_children() if w.winfo_class() == "TEntry"]
            if len(entries) >= 2:
                for e in entries:
                    e.delete(0, "end")
                    e.insert(0, "newpass123")
                for w in ch.winfo_children():
                    if w.winfo_class() == "TButton" and "تغيير كلمة المرور" in str(w.cget("text")):
                        w.invoke()
                        return
login.root.after(600, fill_pw_dialog)
login.try_login()
check("G1 login with admin/admin123 + forced change succeeds", login.user is not None and login.user["username"] == "admin")
check("G2 new password authenticates", db.authenticate("admin", "newpass123") is not None)
check("G3 old default password no longer works", db.authenticate("admin", "admin123") is None)

# ---------- 2. main window ----------
root = tk.Tk()
root.geometry("1280x800")
app = M.App(root, db, login.user)
root.update_idletasks()
root.update()
tabs = root.nametowidget(app.notebook).tabs() if hasattr(app, "notebook") else app.notebook.tabs()
check("G4 main window opens with 10 tabs", len(tabs) == 10, len(tabs))
check("G5 main window is viewable", bool(root.winfo_viewable()))

# ---------- 3. POS sale through the UI ----------
# STEP2 harness note: v6.x is an EMPTY install (0 drugs), but this
# v5.7-era suite expects seeded drug id=1. Seed one here (test copy
# only; product code untouched).
_did = db.add_drug({"trade_en": "SmokeDrug", "trade_ar": "x", "scientific": "T",
                    "company": "X", "form": "Tabs", "strength": "500",
                    "category": "T", "strips_per_box": 2, "tablets_per_strip": 10,
                    "buy_price": 20.0, "sell_price": 25.0, "min_stock": 0,
                    "barcode": ""})
db.conn.execute("INSERT INTO batches (drug_id, batch_no, expiry, qty_units, "
                "buy_price_unit, created_at) VALUES (?,?,?,?,?,?)",
                (_did, "B1", "2030-01-01", 1000, 1.0, "2026-01-01"))
db.conn.commit()
db.add_supplier("SmokeSup", "0100")  # STEP2 harness note: same empty-install gap as above
drug = db.get_drug(_did)
stock_before = drug["stock_units"]
upb = drug["strips_per_box"] * drug["tablets_per_strip"]
app.pos_add_drug(drug, "box", 1)
check("G6 cart has 1 line after pos_add_drug", len(app.cart) == 1, len(app.cart))
app.pos_complete_sale()
root.update()
sales = db.conn.execute("SELECT * FROM sales WHERE status='completed'").fetchall()
check("G7 POS sale saved (1 completed invoice)", len(sales) == 1, len(sales))
sale = dict(sales[0])
check("G8 sale total equals box price", abs(sale["total"] - float(drug["sell_price"])) < 0.01, sale["total"])
stock_after = db.get_drug(1)["stock_units"]
check("G9 stock deducted by exactly one box", stock_after == stock_before - upb, (stock_before, stock_after))
check("G10 no error dialogs during POS sale", len(calls["error"]) == 0, calls["error"])

# ---------- 4. reports reconcile ----------
app.reports_refresh()
root.update()
r = db.report_daily()
check("G11 report total matches DB", abs(r["total"] - sale["total"]) < 0.01, r)
check("G12 report label shows the sale total", ("%.2f" % sale["total"]) in app.lbl_rep.cget("text"), app.lbl_rep.cget("text")[:80])
best = db.report_best_sellers()
check("G13 best sellers lists the sold drug", len(best) == 1 and best[0]["trade_en"] == drug["trade_en"], best)

# ---------- 5. purchase through the UI ----------
app.purchase_lines = [{"drug": drug, "qty_boxes": 1, "buy_price": 10.0, "sell_price": 25.0,
                       "batch_no": "T1", "expiry": FUT}]
sup_name = db.suppliers()[0]["name"]
app.cb_supplier.set(sup_name)
app.e_pur_paid.delete(0, "end")
app.e_pur_paid.insert(0, "10")
stock_pre_pur = db.get_drug(1)["stock_units"]
app.pur_save()
root.update()
check("G14 purchase saved, stock increased by one box",
      db.get_drug(1)["stock_units"] == stock_pre_pur + upb,
      (stock_pre_pur, db.get_drug(1)["stock_units"]))

# ---------- 6. edit dialog opens ----------
app.edit_invoice_dialog(sale["id"])
root.update()
tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
check("G15 edit dialog opens", len(tops) >= 1, [t.title() for t in tops])
for t in tops:
    t.destroy()
root.update()

# ---------- 7. return through the UI ----------
app.return_sale_dialog()
root.update()
row = db.conn.execute("SELECT status FROM sales WHERE id=?", (sale["id"],)).fetchone()
check("G16 return dialog marks invoice returned", row["status"] == "returned", row["status"])
check("G17 returned stock is back", db.get_drug(1)["stock_units"] == stock_before + upb,
      db.get_drug(1)["stock_units"])

# ---------- 8. shift open/close with reconciliation ----------
app.e_float.delete(0, "end")
app.e_float.insert(0, "100")
app.open_shift_dialog()
root.update()
check("G18 shift opens", app.current_shift is not None)
sh = db.conn.execute("SELECT * FROM shifts WHERE cashier='admin' AND status='open'").fetchone()
check("G19 shift row is open in DB", sh is not None)
app.close_shift_dialog()
root.update()
sh = db.conn.execute("SELECT * FROM shifts WHERE id=?", (sh["id"],)).fetchone()
check("G20 shift closes with counted/expected/difference stored",
      sh["status"] == "closed" and sh["counted_cash"] == 125.0 and sh["expected_cash"] == 100.0
      and sh["difference"] == 25.0, dict(sh))
check("G21 no error dialogs during shift flow", len(calls["error"]) == 0, calls["error"])

# ---------- 9. mobile tab refresh does not crash ----------
try:
    app.mobile_refresh()
    root.update()
    check("G22 mobile tab refresh runs", True)
except Exception as e:
    check("G22 mobile tab refresh runs", False, repr(e))

root.destroy()
print("\n==== %d passed, %d failed ====" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
