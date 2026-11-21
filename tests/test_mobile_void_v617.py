"""v6.17 HTTP verification: full-cancel (return) of an invoice from the
phone, and the all-lines-held approve flow that drives it.

The phone edit screen can never save an EMPTY invoice; deleting every
line and approving now offers an explicit full-cancel instead:
POST /api/invoices/<id>/return -> DB.return_sale (same atomic path as
the PC): restock every batch, reverse (total - paid) credit, status ->
returned, sale_returns row. A returned invoice is refused.

Run: python3 tests/test_mobile_void_v617.py"""
import json
import os
import shutil
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "srv617")
SRC = os.path.join(HERE, "..")
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (" | " + str(extra) if extra and not cond else ""))

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
for f in ("database.py", "mobile_server.py", "mobile.html", "zxing.min.js", "seed_data.py",
          "manifest.json", "sw.js", "icon-192.png", "icon-512.png"):
    shutil.copy(os.path.join(SRC, f), os.path.join(WORK, f))
sys.path.insert(0, WORK)
from database import DB
from mobile_server import MobileServer

DB_PATH = os.path.join(WORK, "pharmacy.db")
db = DB(path=DB_PATH)
PIN = db.ensure_mobile_pin()
did = db.add_drug({"trade_en": "V617Drug", "trade_ar": "x", "scientific": "T", "company": "X",
                   "form": "Tabs", "strength": "500", "category": "T", "strips_per_box": 2,
                   "tablets_per_strip": 10, "buy_price": 40.0, "sell_price": 60.0,
                   "min_stock": 5, "barcode": ""})
drug = db.get_drug(did)
db.conn.execute("INSERT INTO batches (drug_id, batch_no, expiry, qty_units, buy_price_unit, created_at) "
                "VALUES (?,?,?,?,?,?)", (did, "B1", "2030-01-01", 200, 40.0, "2026-01-01"))
db.conn.commit()
cid = db.add_customer("V617Cust", "0100", credit_limit=0)

# cash sale: 2 boxes @60 = 120, paid exact
sidCASH, _, totCASH, _ = db.create_sale("admin", [{"drug": drug, "pack_level": "box", "qty_display": 2}],
                                        discount=0, paid=120.0, payment_method="cash", source="mobile")
# credit sale: 1 box @60, paid 20 -> unpaid 40 on the customer
sidCR, _, totCR, _ = db.create_sale("admin", [{"drug": drug, "pack_level": "box", "qty_display": 1}],
                                    discount=0, paid=20.0, payment_method="credit",
                                    customer_id=cid, source="pc")
bal0 = db.conn.execute("SELECT balance FROM customers WHERE id=?", (cid,)).fetchone()[0]
stock0 = db.conn.execute("SELECT SUM(qty_units) FROM batches WHERE drug_id=?", (did,)).fetchone()[0]
db.close()
check("setup: credit balance is 40 (60-20)", bal0 == 40.0, "bal=%s" % bal0)

srv = MobileServer(db_path=DB_PATH, port=18083, https_port=18446)
assert srv.start(), srv.start_error
BASE = "http://127.0.0.1:18083"
time.sleep(0.5)

def req(method, path, pin="USE", body=None):
    h = {}
    if pin == "USE":
        h["X-Mobile-PIN"] = PIN
    elif pin:
        h["X-Mobile-PIN"] = pin
    data = json.dumps(body).encode() if body is not None else None
    if data:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}

# 1) no PIN -> 401
s, d = req("POST", "/api/invoices/%d/return" % sidCASH, pin=None)
check("return without PIN is 401", s == 401, "%s" % s)

# 2) cash invoice full-cancel
s, d = req("POST", "/api/invoices/%d/return" % sidCASH)
check("return cash invoice: 200", s == 200, "%s %s" % (s, d))
db2 = DB(path=DB_PATH)
row = db2.conn.execute("SELECT status FROM sales WHERE id=?", (sidCASH,)).fetchone()
check("cash invoice status is 'returned'", row and row[0] == "returned", "%s" % (row,))
stock1 = db2.conn.execute("SELECT SUM(qty_units) FROM batches WHERE drug_id=?", (did,)).fetchone()[0]
check("cash invoice restocked (+40 units)", stock1 == stock0 + 40, "%s -> %s" % (stock0, stock1))
rr = db2.conn.execute("SELECT total_refunded, cashier FROM sale_returns WHERE sale_id=?",
                      (sidCASH,)).fetchone()
check("sale_returns row written (mobile cashier)", rr and rr[1] == "mobile", "%s" % (rr,))

# 3) double return refused (no double restock)
s, d = req("POST", "/api/invoices/%d/return" % sidCASH)
check("second return refused 400", s == 400, "%s %s" % (s, d))
stock2 = db2.conn.execute("SELECT SUM(qty_units) FROM batches WHERE drug_id=?", (did,)).fetchone()[0]
check("no double restock", stock2 == stock1, "%s vs %s" % (stock2, stock1))

# 4) credit invoice: reversal is (total - paid) only
s, d = req("POST", "/api/invoices/%d/return" % sidCR)
check("return credit invoice: 200", s == 200, "%s %s" % (s, d))
bal1 = db2.conn.execute("SELECT balance FROM customers WHERE id=?", (cid,)).fetchone()[0]
check("customer balance back to 0 (only the unpaid 40 reversed)",
      bal1 == 0.0, "bal=%s" % bal1)

# 5) unknown invoice -> 400 not crash
s, d = req("POST", "/api/invoices/99999/return")
check("unknown invoice refused 400", s == 400, "%s %s" % (s, d))
db2.close()

# 6) structural: phone page wires the all-held approve to the new flow
html = open(os.path.join(SRC, "mobile.html"), encoding="utf-8").read()
check("mobile.html has the explicit full-cancel confirm (voidAll)",
      "voidAll" in html and "تأكيد إلغاء الفاتورة" in html)
check("mobile.html calls the /return endpoint for voidAll",
      "(voidAll?'/return':'/edit')" in html)
srv_py = open(os.path.join(SRC, "mobile_server.py"), encoding="utf-8").read()
check("server routes /api/invoices/<id>/return",
      'path.endswith("/return")' in srv_py and "_api_return_invoice" in srv_py)
check("server return uses return_sale (same PC logic)",
      "db.return_sale(sid" in srv_py)

srv.stop()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
