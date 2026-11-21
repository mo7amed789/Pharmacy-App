"""اختبارات v6.23 — زر «📷 مسح» بجانب خانة باركود العلبة في نافذة إضافة الدواء.

المساران:
1) ماسح USB: نافذة «مسح باركود العلبة» فيها خانة جاهزة بالتركيز — الماسح
   يكتب كلوحة مفاتيح وEnter يملأ خانة الباركود ويغلق النافذة.
2) كاميرا الموبايل: «اطلب المسح من الموبايل» يفتح طلب مسح عبر سيرفر
   الموبايل (mailbox في الذاكرة)؛ صفحة الموبايل تستطلع GET /api/scan-request
   وتعرض تنبيهاً، والمسح يرسل POST /api/scan-result فتُملأ الخانة.

Run: python3 tests/test_scan_button_v623.py"""
import json
import re
import os
import shutil
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "srv623")
SRC = os.path.join(HERE, "..")
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (" | " + str(extra) if extra and not cond else ""))

# ---------- 1) structural: desktop dialog ----------
main_src = open(os.path.join(SRC, "main.py"), encoding="utf-8").read()
check("window title at current version (v6.24)",
      "Pharmacy Enterprise v6.24" in main_src)
check("login label at current version (v6.24)",
      "نظام إدارة الصيدلية — v6.24" in main_src)
check("scan dialog method exists", "_barcode_scan_dialog" in main_src)
check("scan button beside the barcode field",
      'text="📷 مسح"' in main_src and "self._barcode_scan_dialog(e)" in main_src)
check("USB path: focused entry fills target on Enter",
      'usb_entry.bind("<Return>"' in main_src and "usb_entry.focus_set()" in main_src)
check("phone path: opens a scan request via mobile_server",
      "mobile_server.scan_request_open()" in main_src)
check("phone path: desktop polls the mailbox",
      "mobile_server.scan_request_poll(rid)" in main_src)
check("phone path: cancel cleans the request up",
      "mobile_server.scan_request_cancel(state[\"rid\"])" in main_src)
check("server-off guard message",
      "سيرفر الموبايل متوقف" in main_src)
check("dialog fits the screen (fit_dialog)",
      "ui_theme.fit_dialog(win, 520, 430)" in main_src)
check("barcode Enter binding kept (scanner then Enter saves)",
      'fields["barcode"].bind("<Return>"' in main_src)

# ---------- 2) structural: server routes + mailbox ----------
srv_py = open(os.path.join(SRC, "mobile_server.py"), encoding="utf-8").read()
check("server routes GET /api/scan-request",
      '"/api/scan-request"' in srv_py and "_api_scan_request" in srv_py)
check("server routes POST /api/scan-result",
      '"/api/scan-result"' in srv_py and "_api_scan_result" in srv_py)
check("mailbox functions exist",
      "def scan_request_open" in srv_py and "def scan_request_poll" in srv_py
      and "def scan_request_cancel" in srv_py)
check("MobileServer exposes mailbox wrappers",
      "def scan_request_open(self)" in srv_py)

# ---------- 3) structural: phone page ----------
html = open(os.path.join(SRC, "mobile.html"), encoding="utf-8").read()
check("phone page has the PC-scan banner", 'id="pcScanBanner"' in html)
check("phone polls /api/scan-request", "pollPcScan" in html and "/api/scan-request" in html)
check("poll started at login", "startPcScanPoll();" in html)
check("scan button for the PC request", "pcScanStart" in html)
check("onScanned delivers to the PC first",
      "if(pcScanId!=null){await pcScanDeliver(code);return}" in html)
check("phone posts to /api/scan-result", "/api/scan-result" in html)
sw = open(os.path.join(SRC, "sw.js"), encoding="utf-8").read()
check("service-worker cache name is versioned",
      re.search(r"pharmacy-mobile-v\d+", sw) is not None)

# ---------- 4) functional: mailbox round-trip over HTTP ----------
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
for f in ("database.py", "mobile_server.py", "mobile.html", "zxing.min.js", "seed_data.py",
          "manifest.json", "sw.js", "icon-192.png", "icon-512.png"):
    shutil.copy(os.path.join(SRC, f), os.path.join(WORK, f))
sys.path.insert(0, WORK)
from database import DB
from mobile_server import MobileServer, scan_request_open, scan_request_poll, scan_request_cancel

DB_PATH = os.path.join(WORK, "pharmacy.db")
db = DB(path=DB_PATH)
PIN = db.ensure_mobile_pin()
db.close()

srv = MobileServer(db_path=DB_PATH, port=18087, https_port=18450)
assert srv.start(), srv.start_error
BASE = "http://127.0.0.1:18087"
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

# 4.1 auth: no PIN -> 401 on both endpoints
s, _ = req("GET", "/api/scan-request", pin=None)
check("GET /api/scan-request without PIN is 401", s == 401, "%s" % s)
s, _ = req("POST", "/api/scan-result", pin=None, body={"id": 1, "code": "123"})
check("POST /api/scan-result without PIN is 401", s == 401, "%s" % s)

# 4.2 idle: nothing pending
s, d = req("GET", "/api/scan-request")
check("idle: no pending request", s == 200 and d.get("pending") is False, "%s %s" % (s, d))

# 4.3 desktop opens a request -> phone sees it
rid = scan_request_open()
check("mailbox: fresh request is pending with no code",
      scan_request_poll(rid) == {"pending": True, "code": None, "expired": False})
s, d = req("GET", "/api/scan-request")
check("phone sees the pending request with its id",
      s == 200 and d.get("pending") is True and d.get("id") == rid, "%s %s" % (s, d))

# 4.4 wrong/stale id is refused
s, d = req("POST", "/api/scan-result", body={"id": rid + 99, "code": "622"})
check("stale request id is 409", s == 409, "%s" % s)

# 4.5 phone delivers the barcode -> desktop poll picks it up
s, d = req("POST", "/api/scan-result", body={"id": rid, "code": "6223001234567"})
check("phone scan accepted", s == 200 and d.get("ok") is True, "%s %s" % (s, d))
res = scan_request_poll(rid)
check("desktop poll returns the scanned code",
      res.get("code") == "6223001234567" and res.get("pending") is False, "%s" % res)
s, d = req("GET", "/api/scan-request")
check("after delivery: no pending request", s == 200 and d.get("pending") is False)

# 4.6 empty / oversized codes refused
rid2 = scan_request_open()
s, _ = req("POST", "/api/scan-result", body={"id": rid2, "code": ""})
check("empty code is 409", s == 409, "%s" % s)
s, _ = req("POST", "/api/scan-result", body={"id": rid2, "code": "9" * 100})
check("oversized code is 409", s == 409, "%s" % s)

# 4.7 cancel: pending disappears for the phone
scan_request_cancel(rid2)
s, d = req("GET", "/api/scan-request")
check("cancelled request no longer pending", s == 200 and d.get("pending") is False)
check("cancelled request polls expired", scan_request_poll(rid2).get("expired") is True)

# 4.8 a second phone POST after delivery is refused
s, _ = req("POST", "/api/scan-result", body={"id": rid, "code": "111"})
check("duplicate delivery is 409", s == 409, "%s" % s)

srv.stop()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
