"""v6.16 HTTP verification: mobile invoice edit keeps the prices the
phone SHOWS (the invoice's saved prices) instead of silently re-pricing
at today's catalog, and the PWA service worker can no longer pin phones
to a stale page.

Copies the working-copy server files into tests/srv616/ (isolated),
starts the server on its own test ports, and exercises the exact phone
edit protocol (items/discount/paid/approved/deleted_items — no
unit_price is ever sent by the client; the server takes saved prices
from the invoice itself).

Run: python3 tests/test_mobile_edit_v616.py"""
import json
import os
import shutil
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "srv616")
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
did = db.add_drug({"trade_en": "V616Drug", "trade_ar": "x", "scientific": "T", "company": "X",
                   "form": "Tabs", "strength": "500", "category": "T", "strips_per_box": 2,
                   "tablets_per_strip": 10, "buy_price": 40.0, "sell_price": 60.0,
                   "min_stock": 5, "barcode": ""})
drug = db.get_drug(did)
db.conn.execute("INSERT INTO batches (drug_id, batch_no, expiry, qty_units, buy_price_unit, created_at) "
                "VALUES (?,?,?,?,?,?)", (did, "B1", "2030-01-01", 500, 40.0, "2026-01-01"))
db.conn.commit()

# --- sale A: 1 box @60, cash, customer overpaid 100 ---
sidA, _, totA, _ = db.create_sale("admin", [{"drug": drug, "pack_level": "box", "qty_display": 1}],
                                  discount=0, paid=100.0, payment_method="cash", source="mobile")
# price update AFTER the sale (catalog reprice)
db.conn.execute("UPDATE drugs SET sell_price=90.0 WHERE id=?", (did,))
db.conn.commit()

# --- sale B: 1 box @90, cash, paid 95 (overpaid 5) ---
drug = db.get_drug(did)
sidB, _, totB, _ = db.create_sale("admin", [{"drug": drug, "pack_level": "box", "qty_display": 1}],
                                  discount=0, paid=95.0, payment_method="cash", source="pc")
# price doubles after sale B
db.conn.execute("UPDATE drugs SET sell_price=200.0 WHERE id=?", (did,))
db.conn.commit()

# --- sale C: 1 box @200 cash paid exact; will add a NEW strip line in edit ---
drug = db.get_drug(did)
sidC, _, totC, _ = db.create_sale("admin", [{"drug": drug, "pack_level": "box", "qty_display": 1}],
                                  discount=0, paid=200.0, payment_method="cash", source="pc")
# price doubles again after sale C
db.conn.execute("UPDATE drugs SET sell_price=400.0 WHERE id=?", (did,))
db.conn.commit()

# --- sale D: FEFO split across two batches (5 strips = 50 units: 30 from B0 + 20 from B1) ---
db.conn.execute("INSERT INTO batches (drug_id, batch_no, expiry, qty_units, buy_price_unit, created_at) "
                "VALUES (?,?,?,?,?,?)", (did, "B0", "2028-01-01", 30, 40.0, "2026-01-01"))
db.conn.commit()
drug = db.get_drug(did)
sidD, _, totD, _ = db.create_sale(
    "admin", [{"drug": drug, "pack_level": "strip", "qty_display": 5},
              {"drug": drug, "pack_level": "box", "qty_display": 1}],
    discount=0, paid=2000.0, payment_method="cash", source="mobile")
rawD = db.get_sale_items(sidD)
check("sale D really split across 2 batches (FEFO)",
      len([r for r in rawD if r["pack_level"] == "strip"]) == 2,
      "rows=%s" % [(r["pack_level"], r["qty_display"]) for r in rawD])
stock_before = db.conn.execute("SELECT SUM(qty_units) FROM batches WHERE drug_id=?", (did,)).fetchone()[0]
db.close()

srv = MobileServer(db_path=DB_PATH, port=18082, https_port=18445)
assert srv.start(), srv.start_error
BASE = "http://127.0.0.1:18082"
time.sleep(0.5)

def req(method, path, body=None):
    h = {"X-Mobile-PIN": PIN}
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

# ---- Test 1: price rose 60->90 after sale A; phone edits discount 5 ----
s, d = req("GET", "/api/invoice/%d" % sidA)
check("detail A shows the SAVED price 60 (not today's 90)",
      s == 200 and d["invoice"]["items"][0]["unit_price"] == 60.0,
      "%s %s" % (s, d))
body = {"items": [{"drug_id": did, "unit": "box", "qty": 1, "discount": 0}],
        "discount": 5, "payment": "cash", "customer_id": None, "paid": 100.0,
        "approved": True, "deleted_items": []}
s, d = req("POST", "/api/invoices/%d/edit" % sidA, body)
check("edit A approved (200)", s == 200, "%s %s" % (s, d))
check("edit A saves the phone's total 55 (60-5), not today's 85",
      s == 200 and d.get("new_total") == 55.0, "%s %s" % (s, d))

# ---- Test 2: price doubled 90->200 after sale B; paid 95 used to be
# rejected "المدفوع أقل من الإجمالي" (server computed 200-5=195) ----
body = {"items": [{"drug_id": did, "unit": "box", "qty": 1, "discount": 0}],
        "discount": 5, "payment": "cash", "customer_id": None, "paid": 95.0,
        "approved": True, "deleted_items": []}
s, d = req("POST", "/api/invoices/%d/edit" % sidB, body)
check("edit B approved where it used to be rejected (paid<total)", s == 200, "%s %s" % (s, d))
check("edit B saves the phone's total 85 (90-5)", s == 200 and d.get("new_total") == 85.0,
      "%s %s" % (s, d))

# ---- Test 3: existing line keeps saved price, NEW line gets today's ----
# sale C box was sold at 200; strip now costs 400/2=200 (price is 400/box)
body = {"items": [{"drug_id": did, "unit": "box", "qty": 1, "discount": 0},
                  {"drug_id": did, "unit": "strip", "qty": 1, "discount": 0}],
        "discount": 0, "payment": "cash", "customer_id": None, "paid": None,
        "approved": True, "deleted_items": []}
s, d = req("POST", "/api/invoices/%d/edit" % sidC, body)
check("edit C approved (200)", s == 200, "%s %s" % (s, d))
check("edit C total = saved box 200 + today's strip 200 = 400",
      s == 200 and d.get("new_total") == 400.0, "%s %s" % (s, d))

# ---- Test 4: delete a FEFO-grouped line with explicit approval ----
s, d = req("GET", "/api/invoice/%d" % sidD)
itemsD = d["invoice"]["items"]
check("detail D groups the FEFO split into ONE strip line (qty 5)",
      s == 200 and len([i for i in itemsD if i["pack_level"] == "strip"]) == 1
      and [i for i in itemsD if i["pack_level"] == "strip"][0]["qty_display"] == 5.0,
      "%s %s" % (s, [(i["pack_level"], i["qty_display"]) for i in itemsD]))
box = [i for i in itemsD if i["pack_level"] == "box"][0]
body = {"items": [{"drug_id": did, "unit": "box", "qty": box["qty_display"],
                   "discount": box.get("line_discount") or 0}],
        "discount": 0, "payment": "cash", "customer_id": None, "paid": None,
        "approved": True,
        "deleted_items": [{"drug_id": did, "unit": "strip", "qty": 5}]}
s, d = req("POST", "/api/invoices/%d/edit" % sidD, body)
check("edit D (delete grouped FEFO line) approved", s == 200, "%s %s" % (s, d))
db2 = DB(path=DB_PATH)
stock_after = db2.conn.execute("SELECT SUM(qty_units) FROM batches WHERE drug_id=?", (did,)).fetchone()[0]
db2.close()
# stock_before was captured before edits A-D; edit C added 1 strip
# (-10 units), edit D restocks 70 and re-deducts 20 (+50 units).
check("deleted grouped line restocked BOTH batches (+50 net of edit C's -10)",
      stock_after == stock_before + 40, "before=%s after=%s" % (stock_before, stock_after))

# ---- Test 5: service worker can no longer pin a stale page ----
sw = open(os.path.join(SRC, "sw.js"), encoding="utf-8").read()
check("sw.js cache name carries the app version (not the fixed v1)",
      "pharmacy-mobile-v1'" not in sw
      and __import__("re").search(r"pharmacy-mobile-v\d+", sw) is not None)
fetch_pos = sw.find("fetch(e.request)")
cache_pos = sw.find("caches.match(e.request")
check("sw.js fetch handler is network-first (fetch before caches.match)",
      0 < fetch_pos < cache_pos, "fetch=%d cache=%d" % (fetch_pos, cache_pos))

srv.stop()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
