"""v5.7 HTTP verification for mobile_server.py + mobile.html.
Copies the working-copy server files into tests/srv/ (isolated, so cert
regeneration can never touch the patch sources), starts the server on
test ports, and exercises the PIN lockout + strict validation fixes.
Run: python3 tests/test_server_v57.py"""
import json
import os
import shutil
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "srv")
SRC = os.path.join(HERE, "..")  # app root (was a separate src/ layout in the review work)
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
# test drug + customer
did = db.add_drug({"trade_en": "SrvDrug", "trade_ar": "x", "scientific": "T", "company": "X",
                   "form": "Tabs", "strength": "500", "category": "T", "strips_per_box": 1,
                   "tablets_per_strip": 1, "buy_price": 40.0, "sell_price": 60.0,
                   "min_stock": 5, "barcode": ""})
drug = db.get_drug(did)
db.conn.execute("INSERT INTO batches (drug_id, batch_no, expiry, qty_units, buy_price_unit, created_at) "
                "VALUES (?,?,?,?,?,?)", (did, "B1", "2030-01-01", 100, 40.0, "2026-01-01"))
db.conn.commit()
cid = db.add_customer("SrvCust", "0100", credit_limit=0)
db.close()

srv = MobileServer(db_path=DB_PATH, port=18080, https_port=18443)
assert srv.start(), srv.start_error
BASE = "http://127.0.0.1:18080"
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

# ---------- C9: empty probes do not lock ----------
for _ in range(5):
    st, _ = req("GET", "/api/drugs", pin=None)
    assert st == 401, st
st, _ = req("GET", "/api/drugs")
check("C9a 5 empty probes do NOT lock the IP (correct PIN still 200)", st == 200, st)

# ---------- C9: wrong PINs lock, correct PIN bypasses ----------
for _ in range(5):
    st, _ = req("GET", "/api/drugs", pin="000000")
    assert st == 401, st
st, body = req("GET", "/api/drugs", pin="000000")
check("C9b 6th wrong PIN is 429 locked", st == 429, (st, body))
st, _ = req("GET", "/api/drugs")
check("C9c correct PIN bypasses the lock (200)", st == 200, st)
st, _ = req("GET", "/api/drugs", pin="000000")
check("C9d after a correct PIN, the counter restarts (401 not 429)", st == 401, st)

# ---------- C5/C10: strict create validation ----------
items = [{"drug_id": did, "unit": "box", "qty": 1}]
st, body = req("POST", "/api/invoices", body={"items": items, "payment": "credit", "customer_id": "abc", "paid": 0})
check("C5 credit with garbage customer_id -> 400", st == 400, (st, body))
st, body = req("POST", "/api/invoices", body={"items": items, "payment": "weird", "paid": 60})
check("C10a unknown payment -> 400 (not silent cash)", st == 400, (st, body))
st, body = req("POST", "/api/invoices", body={"items": items, "payment": "cash", "discount": "abc", "paid": 60})
check("C10b garbage discount -> 400 (not silent 0)", st == 400, (st, body))
st, body = req("POST", "/api/invoices", body={"items": items, "payment": "cash", "paid": "abc"})
check("C10c garbage paid -> 400 (not silent full payment)", st == 400, (st, body))
st, body = req("POST", "/api/invoices", body={"items": {"drug_id": did}, "payment": "cash", "paid": 60})
check("C19a items as dict -> 400 (not 500)", st == 400, (st, body))
st, body = req("POST", "/api/invoices", body={"items": ["x"], "payment": "cash", "paid": 60})
check("C19b non-dict item -> 400 (not 500)", st == 400, (st, body))
st, body = req("POST", "/api/invoices", body={"items": [{"drug_id": did, "unit": "crate", "qty": 1}], "payment": "cash", "paid": 60})
check("F15 unknown unit -> 400 (not silent box)", st == 400, (st, body))
st, body = req("POST", "/api/invoices", body={"items": items, "payment": "cash", "discount": -1, "paid": 60})
check("V1 negative create discount -> 400", st == 400, (st, body))
st, body = req("GET", "/api/drugs?ids=%d" % did)
check("V2 targeted drug lookup returns only requested drug", st == 200 and [d.get("id") for d in body.get("drugs", [])] == [did], (st, body))

# ---------- happy path: credit sale paid 0 records the debt ----------
st, body = req("POST", "/api/invoices", body={"items": items, "payment": "credit", "customer_id": cid, "paid": 0})
check("H1 credit sale via API succeeds", st == 200 and body.get("total") == 60.0, (st, body))
db2 = DB(path=DB_PATH)
bal = db2.conn.execute("SELECT balance FROM customers WHERE id=?", (cid,)).fetchone()["balance"]
check("H2 credit balance after API sale is 60 (total - paid)", bal == 60.0, bal)
sale_id = body.get("sale_id")
db2.close()

# ---------- B5: edit a credit invoice without customer_id ----------
st, body = req("POST", "/api/invoices/%d/edit" % sale_id,
               body={"items": [{"drug_id": did, "unit": "box", "qty": 2}],
                     "discount": 0, "payment": "credit", "paid": 0})
check("B5 edit credit invoice without customer_id succeeds", st == 200, (st, body))
st, body = req("POST", "/api/invoices/%d/edit" % sale_id,
               body={"items": [{"drug_id": did, "unit": "box", "qty": 2}],
                     "discount": -1, "payment": "credit", "paid": 0})
check("V3 negative edit discount -> 400", st == 400, (st, body))
db3 = DB(path=DB_PATH)
bal = db3.conn.execute("SELECT balance FROM customers WHERE id=?", (cid,)).fetchone()["balance"]
check("B5b balance after edit is 120", bal == 120.0, bal)
db3.close()

# ---------- C4: XSS gone from the served page ----------
html = open(os.path.join(WORK, "mobile.html"), encoding="utf-8").read()
check("C4a no onclick=addToCart interpolation left", 'onclick="addToCart' not in html)
check("C4b no onclick=histAdd interpolation left", 'onclick="histAdd' not in html)
check("C4c buttons use addEventListener", "addEventListener('click'" in html)

srv.stop()
print("\n==== %d passed, %d failed ====" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
