"""v6.8: phone edit keeps explicit line discounts, and the payment rules the
page now enforces (cash/card paid >= total, card not overpaid) match the server.
Run: python3 tests/test_v68_harmony.py  (exit 0 only if ALL pass)"""
import json, os, shutil, sys, time, urllib.request, urllib.error
from datetime import date, timedelta
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(HERE, '..')
PASS, FAIL = [], []
def check(n, c, x=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ") + n + ((" | " + str(x)) if x and not c else ""))
FUT = (date.today() + timedelta(days=365)).isoformat()
SRV = os.path.join(HERE, 'srv68'); shutil.rmtree(SRV, ignore_errors=True); os.makedirs(SRV)
for f in ("database.py", "mobile_server.py", "mobile.html", "zxing.min.js", "cert.pem", "key.pem"):
    shutil.copy(os.path.join(SRC, f), os.path.join(SRV, f))
sys.path.insert(0, SRV)
import database as D
from mobile_server import MobileServer
DBP = os.path.join(SRV, "pharmacy.db"); db = D.DB(path=DBP); PIN = db.ensure_mobile_pin()
def mk(name, sell, disc=None):
    did = db.add_drug({"trade_en": name, "trade_ar": "x", "scientific": "T", "company": "X", "form": "Tabs", "strength": "1", "category": "T",
                       "strips_per_box": 2, "tablets_per_strip": 10, "buy_price": 1.0, "sell_price": sell, "min_stock": 5, "barcode": ""})
    if disc: db.conn.execute("UPDATE drugs SET discount_type='percent', discount_value=? WHERE id=?", (disc, did)); db.conn.commit()
    db.conn.execute("INSERT INTO batches (drug_id,batch_no,expiry,qty_units,buy_price_unit,created_at) VALUES (?,?,?,?,?,?)", (did, "B1", FUT, 1000, 1.0, "2026-01-01")); db.conn.commit()
    return db.get_drug(did)
X = mk("X68", 100.0, 10); Y = mk("Y68", 40.0); Z = mk("Z68", 50.0, 10)
# the cashier removed X's default discount (explicit 0) -> total 140, not 130
sid, inv, total, ch = db.create_sale("admin", [{"drug": X, "pack_level": "box", "qty_display": 1, "discount": 0}, {"drug": Y, "pack_level": "box", "qty_display": 1}])
check("setup: explicit zero discount honoured on create (140)", total == 140.0, total)
db.close()
srv = MobileServer(db_path=DBP, port=18082, https_port=18445); assert srv.start(), srv.start_error
BASE = "http://127.0.0.1:18082"; time.sleep(0.5)
def req(path, body):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"X-Mobile-PIN": PIN, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp: return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode())
        except Exception: return e.code, {}
it = lambda d, q, **k: dict({"drug_id": d["id"], "unit": "box", "qty": q}, **k)
E = f"/api/invoices/{sid}/edit"
st, b = req(E, {"items": [it(X, 1, discount=0), it(Y, 2)], "payment": "cash", "paid": None})
check("H1 edit keeps X's explicit 0 discount: total 180 (not 170), paid=null ok", st == 200 and b.get("new_total") == 180.0, (st, b))
st, b = req(E, {"items": [it(X, 1, discount=0), it(Y, 2), it(Z, 1)], "payment": "cash", "paid": None})
check("H2 new line sent WITHOUT discount gets the drug default (Z 50-10%=45): 225", st == 200 and b.get("new_total") == 225.0, (st, b))
st, b = req(E, {"items": [it(X, 1, discount=0), it(Y, 2), it(Z, 1)], "payment": "cash", "paid": 100})
check("H3 cash paid < new total refused (400)", st == 400, (st, b))
st, b = req(E, {"items": [it(X, 1, discount=0), it(Y, 2), it(Z, 1)], "payment": "card", "paid": 300})
check("H4 card overpaid refused (400)", st == 400, (st, b))
st, b = req(E, {"items": [it(X, 1, discount=0), it(Y, 2), it(Z, 1)], "payment": "card", "paid": None})
check("H5 card with paid=null accepted, total 225", st == 200 and b.get("new_total") == 225.0, (st, b))
srv.stop()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed: {FAIL}"); sys.exit(1 if FAIL else 0)
