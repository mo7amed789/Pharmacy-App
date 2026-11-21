"""v6.3 GUI smoke under Xvfb: Add Drug dialog (form dropdown +
discount fields), Inventory columns (strength/form/discount),
barcode label dialog with auto barcode + checkboxes, supplier
ID search, POS sale with per-drug discount.
Run: xvfb-run -a python3 tests/gui_v63.py"""
import os, shutil, sys, tkinter as tk
from tkinter import messagebox
from datetime import date, timedelta

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "gui63")
SRC = os.path.join(HERE, "..")
PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (" | " + str(extra) if extra and not cond else ""), flush=True)

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
for f in os.listdir(SRC):
    if f.endswith((".py", ".html", ".js", ".json")):
        shutil.copy(os.path.join(SRC, f), os.path.join(WORK, f))
sys.path.insert(0, WORK)
os.chdir(WORK)
import main as M
from database import DB, ean13_is_valid

calls = {"info": [], "error": [], "ask": []}
def _info(t, m, **kw): calls["info"].append((t, m)); return None
def _err(t, m, **kw): calls["error"].append((t, m)); return None
messagebox.showinfo = _info
messagebox.showerror = _err
M.messagebox.showinfo = _info
M.messagebox.showerror = _err
M.messagebox.askyesno = lambda *a, **k: True

db = DB(path=os.path.join(WORK, "pharmacy.db"))
FUT = (date.today() + timedelta(days=365)).isoformat()
# seed one supplier + one drug with stock, via the DB API
sup_id = db.add_supplier("Alpha Pharma", "01000000001")
did = db.add_drug({"trade_en": "Ivrrond", "trade_ar": "ايفيروند", "scientific": "Ivy",
                   "company": "Safe", "form": "Syrup", "strength": "250",
                   "category": "T", "strips_per_box": 1, "tablets_per_strip": 1,
                   "buy_price": 20.0, "sell_price": 30.0, "min_stock": 5,
                   "barcode": "", "discount_type": "percent", "discount_value": 10})
db.conn.execute("INSERT INTO batches (drug_id,batch_no,expiry,qty_units,buy_price_unit,created_at) VALUES (?,?,?,?,?,?)",
                (did, "B1", FUT, 100, 20.0, "2026-01-01"))
db.conn.commit()

root = tk.Tk()
root.geometry("1280x800")
app = M.App(root, db, {"username": "admin", "role": "admin"})
root.update_idletasks()
check("G1 main window viewable, 10 tabs", root.winfo_viewable() and len(app.notebook.tabs()) == 10, len(app.notebook.tabs()))

# --- Inventory columns include strength / form / discount ---
app.notebook.select(2)
root.update_idletasks()
cols = app.tree_inv["columns"]
check("G2 inventory has strength/form/disc columns", "strength" in cols and "form" in cols and "disc" in cols, cols)
app.inv_refresh()
root.update_idletasks()
vals = app.tree_inv.item(app.tree_inv.get_children()[0])["values"] if app.tree_inv.get_children() else []
check("G3 inventory row shows 250 / Syrup / 10%", len(vals) >= 8 and str(vals[4]) == "250" and vals[5] == "Syrup" and vals[6] == "10%", vals)

# --- POS search label includes strength + form ---
app.notebook.select(1)
root.update_idletasks()
lbl = app.drug_label(db.get_drug(did))
check("G4 POS search label shows 250 Syrup", "250" in lbl and "Syrup" in lbl, lbl)

# --- POS sale: 1 box of Ivrrond (30) with 10% drug discount -> total 27 ---
app.pos_search_refresh()
app.e_search.delete(0, "end"); app.e_search.insert(0, "Ivrrond")
app.pos_search_refresh()
root.update_idletasks()
assert app.search_results, "no search results"
app.list_search.selection_set(0)
app.pos_add_selected()
root.update_idletasks()
sub, total = app.refresh_pos_totals()
check("G5 POS total with drug discount is 27.00", abs(total - 27.0) < 0.01, (sub, total))
cart_disc = float(app.cart[0].get("discount") or 0)
check("G6 cart line discount is 3.00", abs(cart_disc - 3.0) < 0.01, cart_disc)

# --- Add Drug dialog: form combobox + discount fields present ---
app.drug_dialog()
root.update_idletasks()
dlg = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
texts = []
def walk(w):
    try: texts.append(str(w.cget("text")))
    except Exception: pass
    for ch in w.winfo_children(): walk(ch)
walk(dlg)
check("G7 drug dialog has form label + discount label",
      any("الشكل الصيدلاني" in t for t in texts) and any("خصم الدواء" in t for t in texts), texts)
combos = [w for w in dlg.winfo_children() if w.winfo_class() == "TCombobox"]
check("G8 drug dialog has a form combobox", len(combos) >= 1, len(combos))
dlg.destroy()

# --- Barcode label dialog: auto barcode + checkboxes + preview ---
app.tree_inv.selection_set(app.tree_inv.get_children()[0])
app.barcode_label_dialog()
root.update_idletasks()
dlg = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
texts = []
walk(dlg)
bc = db.drug_barcode(did)
check("G9 auto barcode generated and valid EAN-13", bool(bc) and ean13_is_valid(bc), bc)
check("G10 label dialog lists the barcode", any(bc in t for t in texts), texts)
check("G11 label dialog has choose-what checkboxes",
      any("اسم الصيدلية" in t for t in texts) and any("تليفون الصيدلية" in t for t in texts)
      and any("اختيار الكل" in t for t in texts), texts)
check("G12 label dialog has size + copies", any("50" in t and "25" in t for t in texts) and any("عدد النسخ" in t for t in texts), texts)
dlg.destroy()

# --- Supplier ID search: finds #id, unknown id shows message ---
app.notebook.select(3)
root.update_idletasks()
app.e_sup_id.delete(0, "end"); app.e_sup_id.insert(0, str(sup_id))
app.supplier_id_search()
root.update_idletasks()
check("G13 supplier ID search selects Alpha Pharma", app.cb_supplier.get() == "Alpha Pharma", app.cb_supplier.get())
calls["info"].clear()
app.e_sup_id.delete(0, "end"); app.e_sup_id.insert(0, "99999")
app.supplier_id_search()
check("G14 unknown supplier ID shows 'غير موجود'", any("غير موجود" in (t + m) for t, m in calls["info"]), calls["info"])

# --- Settings: pharmacy phone field present ---
app.notebook.select(9)
root.update_idletasks()
check("G15 settings has pharmacy phone entry", hasattr(app, "e_pharmacy_phone"))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", ", ".join(FAIL)); sys.exit(1)
print("ALL v6.3 GUI CHECKS PASSED")
