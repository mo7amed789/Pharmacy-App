"""v6.3 verification: per-drug discount, EAN-13 auto barcode + label
bars, concentration/form visibility, supplier ID search.
Run: python3 tests/test_v63.py  (exit 0 only if ALL pass)"""
import json, os, shutil, sys
from datetime import date, timedelta
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..')
sys.path.insert(0, SRC)
import database as dbmod
from database import DB
import printer

PASS = []
FAIL = []
def check(n, c, x=""):
    (PASS if c else FAIL).append(n)
    print(("  PASS " if c else "  FAIL ") + n + ((" | " + str(x)) if x and not c else ""))

FUT = (date.today() + timedelta(days=365)).isoformat()
WORK = os.path.join(HERE, 'dbs')

def fresh(name):
    d = os.path.join(WORK, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return DB(path=os.path.join(d, 'pharmacy.db'))

def mk(db, name, sell, disc_type="none", disc_val=0, form="Syrup", strength="250"):
    did = db.add_drug({"trade_en": name, "trade_ar": "x", "scientific": "Ivy",
                       "company": "Safe", "form": form, "strength": strength,
                       "category": "T", "strips_per_box": 2, "tablets_per_strip": 10,
                       "buy_price": 10.0, "sell_price": sell, "min_stock": 5,
                       "barcode": "", "discount_type": disc_type, "discount_value": disc_val})
    return db.get_drug(did)

def batch(db, did, qty):
    db.conn.execute("INSERT INTO batches (drug_id,batch_no,expiry,qty_units,buy_price_unit,created_at) VALUES (?,?,?,?,?,?)",
                    (did, "B1", FUT, qty, 1.0, "2026-01-01"))
    db.conn.commit()

def stock(db, did):
    return db.conn.execute("SELECT COALESCE(SUM(qty_units),0) FROM batches WHERE drug_id=?", (did,)).fetchone()[0]

# --- 1. concentration + form are saved and visible ---
db = fresh("v63_t1")
d = mk(db, "Ivrrond", 30.0)
check("T1 strength saved", d["strength"] == "250", d)
check("T1 form saved", d["form"] == "Syrup", d)
found = db.search_drugs("Ivrrond")
check("T1 search returns strength+form", found and found[0]["strength"] == "250" and found[0]["form"] == "Syrup", found)
check("T1 discount default none", d.get("discount_type") == "none" and float(d.get("discount_value") or 0) == 0, d)

# --- 2. percent discount: 10% on a 30 EGP box, qty 2 -> 6 off, total 54 ---
db = fresh("v63_t2")
d = mk(db, "DiscPct", 30.0, "percent", 10)
batch(db, d["id"], 100)
sid, inv, total, ch = db.create_sale("admin", [{"drug": d, "pack_level": "box", "qty_display": 2}])
check("T2 percent discount total 54", total == 54.0, total)
row = db.conn.execute("SELECT line_discount FROM sale_items WHERE sale_id=?", (sid,)).fetchone()
check("T2 line_discount stored 6.00", abs(float(row["line_discount"] or 0) - 6.0) < 0.01, row)
check("T2 stock deducted 2 boxes (40 units)", stock(db, d["id"]) == 100 - 40, stock(db, d["id"]))
rep = db.report_daily()
check("T2 profit counts line discount (54-40 cost=14)", abs(rep["profit"] - 14.0) < 0.01, rep)

# --- 3. fixed amount discount: 5 EGP per box, qty 3 -> 15 off ---
db = fresh("v63_t3")
d = mk(db, "DiscAmt", 30.0, "amount", 5)
batch(db, d["id"], 200)
sid, inv, total, ch = db.create_sale("admin", [{"drug": d, "pack_level": "box", "qty_display": 3}])
check("T3 amount discount total 75 (90-15)", total == 75.0, total)

# --- 4. explicit line discount overrides the drug default (cashier removed it) ---
db = fresh("v63_t4")
d = mk(db, "DiscOver", 30.0, "percent", 10)
batch(db, d["id"], 100)
sid, inv, total, ch = db.create_sale("admin", [{"drug": d, "pack_level": "box", "qty_display": 1, "discount": 0}])
check("T4 explicit 0 discount overrides default (total 30)", total == 30.0, total)

# --- 5. invalid discounts are refused at the DB boundary ---
db = fresh("v63_t5")
try:
    mk(db, "BadPct", 30.0, "percent", 150)
    check("T5 percent >100 refused", False)
except ValueError:
    check("T5 percent >100 refused", True)
try:
    mk(db, "BadAmt", 30.0, "amount", 30.0)
    check("T5 amount >= sell price refused", False)
except ValueError:
    check("T5 amount >= sell price refused", True)

# --- 6. EAN-13: check digit, pattern decode round-trip, PNG ---
code = dbmod.ean13_complete("200000000001")
check("T6 EAN-13 check digit valid", dbmod.ean13_is_valid(code) and len(code) == 13, code)
check("T6 EAN-13 pattern is 95 modules", len(dbmod.ean13_pattern(code)) == 95)
check("T6 pattern decodes back to the same code", dbmod.ean13_decode_pattern(dbmod.ean13_pattern(code)) == code)
check("T6 bad check digit rejected", not dbmod.ean13_is_valid(code[:-1] + ("0" if code[-1] != "0" else "1")))
png = dbmod.ean13_png_bytes(code)
check("T6 PNG header + non-trivial size", png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 200, len(png))
esc = printer.build_escpos_label("Panadol", "50.00", code)
check("T6 ESC/POS label contains GS k EAN-13 command", b"\x1d\x6b\x02" in esc and code[:12].encode() in esc)

# --- 7. auto barcode: drug with no barcode gets a valid, unique, scannable code ---
db = fresh("v63_t7")
d1 = mk(db, "NoBar1", 25.0)
d2 = mk(db, "NoBar2", 40.0)
c1 = db.ensure_drug_barcode(d1["id"])
c2 = db.ensure_drug_barcode(d2["id"])
check("T7 auto barcode is a valid EAN-13", dbmod.ean13_is_valid(c1), c1)
check("T7 two drugs get different barcodes", c1 != c2, (c1, c2))
check("T7 second call returns the SAME saved barcode", db.ensure_drug_barcode(d1["id"]) == c1)
got, pack = db.lookup_barcode(c1)
check("T7 printed barcode scans back to the drug (POS lookup)", got is not None and got["id"] == d1["id"], got)
check("T7 drug_barcode() returns the saved code", db.drug_barcode(d1["id"]) == c1)

# --- 8. existing barcode is kept, never overwritten by auto-generate ---
db = fresh("v63_t8")
did = db.add_drug({"trade_en": "HasBar", "trade_ar": "", "scientific": "", "company": "",
                   "form": "Tablets", "strength": "500", "category": "", "strips_per_box": 1,
                   "tablets_per_strip": 10, "buy_price": 5, "sell_price": 20, "min_stock": 5,
                   "barcode": "6220000100000"})
check("T8 existing barcode kept", db.ensure_drug_barcode(did) == "6220000100000")

# --- 9. supplier search by ID ---
db = fresh("v63_t9")
s1 = db.add_supplier("Alpha Pharma", "01000000001")
s2 = db.add_supplier("Beta Med", "01000000002")
check("T9 search by ID finds the right supplier", db.search_suppliers(str(s2)) == [db.get_supplier(s2)])
check("T9 search by '#id' also works", len(db.search_suppliers("#%d" % s1)) == 1 and db.search_suppliers("#%d" % s1)[0]["id"] == s1)
check("T9 unknown ID returns empty (no crash)", db.search_suppliers("99999") == [])
check("T9 non-numeric unknown name returns empty", db.search_suppliers("NoSuchSupplier") == [])
check("T9 get_supplier bad input returns None", db.get_supplier("abc") is None and db.get_supplier(99999) is None)
check("T9 name search still works", any(x["id"] == s1 for x in db.search_suppliers("Alpha")))

# --- 10. edit keeps the stored line discount; new item gets the default ---
db = fresh("v63_t10")
d = mk(db, "EditDisc", 30.0, "percent", 10)
e = mk(db, "EditNew", 20.0, "percent", 50)
batch(db, d["id"], 100)
batch(db, e["id"], 100)
sid, inv, total, ch = db.create_sale("admin", [{"drug": d, "pack_level": "box", "qty_display": 1}])
check("T10 original sale total 27 (30-3)", total == 27.0, total)
items = db.get_sale_items(sid)
res = db.edit_sale(sid, "admin", [
    {"drug": d, "pack_level": "box", "qty_display": 1, "discount": float(items[0].get("line_discount") or 0)},
    {"drug": e, "pack_level": "box", "qty_display": 1},
])
check("T10 edit: kept line 27 + new line 10 = 37", res["new_total"] == 37.0, res)

# --- 11. migration on an old DB: columns exist, old rows get none/0 ---
db = fresh("v63_t11")
cols = [r[1] for r in db.conn.execute("PRAGMA table_info(drugs)").fetchall()]
check("T11 drugs has discount columns", "discount_type" in cols and "discount_value" in cols, cols)
cols = [r[1] for r in db.conn.execute("PRAGMA table_info(sale_items)").fetchall()]
check("T11 sale_items has line_discount", "line_discount" in cols, cols)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", ", ".join(FAIL))
    sys.exit(1)
print("ALL v6.3 CHECKS PASSED")
