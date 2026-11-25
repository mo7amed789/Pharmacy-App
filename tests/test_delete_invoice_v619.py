"""v6.19 verification: direct حذف الفاتورة (full void) everywhere +
audit-logging of every void.

What v6.19 adds:
- Mobile: a 🗑️ حذف button per invoice in the سجل list and inside the
  open invoice — same confirm box and the same PIN-protected
  POST /api/invoices/<id>/return endpoint (v6.17) behind them.
- Desktop: 🗑️ حذف الفاتورة buttons in the invoices list window and the
  invoice detail window, sharing one _void_sale_row() helper with the
  reports-tab dialog.
- DB: return_sale() itself writes the audit_log row inside the same
  atomic transaction — before v6.19 only the PC dialog logged (mobile
  voids were never audited despite the endpoint docstring).

Run: python3 tests/test_delete_invoice_v619.py"""
import json
import re
import os
import shutil
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "srv619")
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
did = db.add_drug({"trade_en": "V619Drug", "trade_ar": "x", "scientific": "T", "company": "X",
                   "form": "Tabs", "strength": "500", "category": "T", "strips_per_box": 2,
                   "tablets_per_strip": 10, "buy_price": 40.0, "sell_price": 60.0,
                   "min_stock": 5, "barcode": ""})
drug = db.get_drug(did)
db.conn.execute("INSERT INTO batches (drug_id, batch_no, expiry, qty_units, buy_price_unit, created_at) "
                "VALUES (?,?,?,?,?,?)", (did, "B1", "2030-01-01", 200, 40.0, "2026-01-01"))
db.conn.commit()

sidA, invA, totA, _ = db.create_sale("admin", [{"drug": drug, "pack_level": "box", "qty_display": 1}],
                                     discount=0, paid=60.0, payment_method="cash", source="mobile")
db.close()

# ---------- 1) DB level: return_sale writes audit_log atomically ----------
db2 = DB(path=DB_PATH)
db2.return_sale(sidA, "mobile", reason="اختبار v6.19")
a = db2.conn.execute(
    "SELECT user, action, details FROM audit_log WHERE action='return_sale'").fetchall()
check("return_sale writes an audit_log row", len(a) == 1, "%s" % (a,))
check("audit row carries user + invoice number + reason",
      bool(a) and a[0][0] == "mobile" and invA in a[0][2] and "اختبار" in a[0][2],
      "%s" % (a,))
db2.close()

# ---------- 2) HTTP: the endpoint the delete buttons call ----------
db3 = DB(path=DB_PATH)
sidB, invB, totB, _ = db3.create_sale("admin", [{"drug": drug, "pack_level": "box", "qty_display": 1}],
                                      discount=0, paid=60.0, payment_method="cash", source="pc")
db3.close()

srv = MobileServer(db_path=DB_PATH, port=18084, https_port=18447)
assert srv.start(), srv.start_error
BASE = "http://127.0.0.1:18084"
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

s, d = req("POST", "/api/invoices/%d/return" % sidB, pin=None)
check("delete without PIN is 401", s == 401, "%s" % s)
s, d = req("POST", "/api/invoices/%d/return" % sidB)
check("delete via endpoint: 200", s == 200, "%s %s" % (s, d))
db4 = DB(path=DB_PATH)
a2 = db4.conn.execute(
    "SELECT COUNT(*) FROM audit_log WHERE action='return_sale'").fetchone()[0]
check("endpoint void is audit-logged too (2 rows total)", a2 == 2, "%s" % a2)
st = db4.conn.execute("SELECT status FROM sales WHERE id=?", (sidB,)).fetchone()[0]
check("invoice B status is 'returned'", st == "returned", st)
s, d = req("POST", "/api/invoices/%d/return" % sidB)
check("second delete refused 400", s == 400, "%s %s" % (s, d))
db4.close()
srv.stop()

# ---------- 3) structural: the phone page ----------
html = open(os.path.join(SRC, "mobile.html"), encoding="utf-8").read()
check("mobile.html has askVoidInvoice()", "function askVoidInvoice(id,no)" in html)
check("list rows wire the 🗑️ button to askVoidInvoice(i.id,i.invoice_no)",
      "askVoidInvoice(i.id,i.invoice_no)" in html)
check("delete button only rendered for completed invoices",
      "if(i.status==='completed')" in html)
check("returned rows get a «مُرجعة» marker instead of buttons",
      "مُرجعة ↩️" in html)
check("open invoice has a 🗑️ حذف الفاتورة button",
      'class="btn red" onclick="askVoidInvoice()"' in html)
# the confirm box must sit OUTSIDE the detail card, or the list-row
# delete could never show it (the card stays hidden until فتح).
det_open = html.find('<div id="histDetail"')
det_close = html.find('</div>\n    <!-- v6.19')
conf = html.find('id="histConfirm"')
check("histConfirm moved outside the hidden detail card",
      det_open != -1 and conf != -1 and conf > det_open and det_close != -1
      and det_open < det_close < conf,
      "detail=%s close=%s confirm=%s" % (det_open, det_close, conf))
check("list-flow errors go to the global message (detail may be closed)",
      "(fromList?showMsg:hMsg)" in html)
check("deleting from the list never discards another open invoice's edits",
      "if(!fromList||hId===vid)closeHistDetail(true)" in html)

# ---------- 4) structural: the desktop app ----------
main = open(os.path.join(SRC, "main.py"), encoding="utf-8").read()
check("desktop invoices list has the 🗑️ delete button",
      "🗑️ حذف الفاتورة المحددة (إرجاع كامل)" in main
      and "_inv_void_selected" in main)
check("desktop detail window has the 🗑️ delete button",
      "🗑️ حذف الفاتورة" in main and "_void_sale_row(s, parent=win)" in main)
check("one shared void path (_void_sale_row) behind every button",
      "def _void_sale_row(self, s, parent=None)" in main
      and main.count("_void_sale_row") >= 4)
check("delete buttons use the danger style",
      main.count('style="Danger.TButton"') >= 3)
check("detail window closes only when the void succeeded",
      "_void_sale_row(s, parent=win) and win.destroy()" in main)
check("reports dialog no longer double-logs (audit moved into DB)",
      "self.db.audit(self.username, \"return_sale\"" not in main)

# ---------- 5) structural: DB + service worker ----------
dbpy = open(os.path.join(SRC, "database.py"), encoding="utf-8").read()
check("return_sale itself writes audit_log (every caller logged)",
      '_audit_row(user, "return_sale"' in dbpy
      and '"return_sale"' in dbpy)
sw = open(os.path.join(SRC, "sw.js"), encoding="utf-8").read()
check("sw cache bumped so phones fetch the v6.19 page",
      re.search(r"pharmacy-mobile-v\d+", sw) and "pharmacy-mobile-v616" not in sw)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
