"""اختبارات v6.26 — الوضع السحابي: اتصال الهاتف بالبرنامج بدون واي فاي.

عندما لا يصل الهاتف لسيرفر الكمبيوتر (لا شبكة مشتركة) يعمل «وضع السحابة»:
- mobile.html يبحث في كتالوج Supabase مباشرة ويدرج الفاتورة في جدول
  mobile_orders، ويستعلم عن حالتها حتى تُسجَّل.
- cloud_sync.start_order_polling يسحب الطلبات المعلقة كل 15 ثانية
  ويطبقها بنفس DB.create_sale_from_items التي يستخدمها سيرفر الموبايل.
- الهاتف يرسل بصمة SHA-256 للرمز (PIN) لا الرمز نفسه؛ البرنامج يقارنها
  برمزه الحالي قبل أي بيع.
- mobile_server يقدّم /api/cloud-config (محمي بالرمز) ليهيّئ الهاتف.
- sw.js لا يعترض أي طلب خارج أصل الصفحة (حركة Supabase تبقى حرة).

بدون إنترنت حقيقي هنا: الاختبارات الوظيفية تستخدم عميل سحابة مزيفاً.

Run: python3 tests/test_cloud_mode_v626.py"""
import hashlib
import os
import re
import shutil
import sys

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "cloud626")
SRC = os.path.join(HERE, "..")
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (" | " + str(extra) if extra and not cond else ""))

main_src = open(os.path.join(SRC, "main.py"), encoding="utf-8").read()
html = open(os.path.join(SRC, "mobile.html"), encoding="utf-8").read()
sw = open(os.path.join(SRC, "sw.js"), encoding="utf-8").read()
srv_src = open(os.path.join(SRC, "mobile_server.py"), encoding="utf-8").read()
sync_src = open(os.path.join(SRC, "cloud_sync.py"), encoding="utf-8").read()
client_src = open(os.path.join(SRC, "supabase_client.py"), encoding="utf-8").read()

# ---------- 1) الإصدار والكاش ----------
check("window title at v6.27", "Pharmacy Enterprise v6.29" in main_src)
check("login label at v6.27", "نظام إدارة الصيدلية — v6.29" in main_src)
check("sw cache bumped to v627", "pharmacy-mobile-v629" in sw)

# ---------- 2) sw لا يعترض حركة السحابة ----------
check("sw ignores cross-origin (Supabase) traffic",
      "url.origin !== self.location.origin" in sw)

# ---------- 3) بنية mobile.html للوضع السحابي ----------
ids_used = sorted(set(re.findall(r"\$\('([A-Za-z0-9_]+)'\)", html)))
ids_def = set(re.findall(r'id="([A-Za-z0-9_]+)"', html))
missing = [i for i in ids_used if i not in ids_def]
check("all %d JS-referenced ids present" % len(ids_used), not missing, ",".join(missing))
for marker in ("cloudBanner", "enterCloudMode", "exitCloudMode", "cloudSave",
               "pollCloudOrder", "startLanProbe", "sha256Hex", "pin_hash",
               "/mobile_orders", "pe_sb_url", "/api/cloud-config",
               "cloudDrugJson", "cloudSearch", "cloudBarcode"):
    check("mobile.html has %s" % marker, marker in html)
check("no Supabase key literal embedded in mobile.html",
      "sb_publishable" not in html and "apikey" in html)

# ---------- 4) سيرفر الموبايل: نقطة cloud-config ----------
check("server routes /api/cloud-config", '"/api/cloud-config"' in srv_src)
check("cloud-config handler reads supabase config",
      "_api_cloud_config" in srv_src and "load_config" in srv_src)

# ---------- 5) العميل والمزامنة: دوال الطابور ----------
check("client fetch_pending_orders", "def fetch_pending_orders" in client_src)
check("client update_order", "def update_order" in client_src)
check("sync apply_cloud_order", "def apply_cloud_order" in sync_src)
check("sync apply_mobile_orders", "def apply_mobile_orders" in sync_src)
check("sync start_order_polling", "def start_order_polling" in sync_src)
check("main.py starts order polling", "start_order_polling" in main_src)

# ---------- 6) وظيفي: تطبيق الطلبات على قاعدة حقيقية ----------
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
for f in ("database.py", "cloud_sync.py", "supabase_client.py", "seed_data.py"):
    shutil.copy(os.path.join(SRC, f), os.path.join(WORK, f))
sys.path.insert(0, WORK)
from database import DB  # noqa: E402
import cloud_sync  # noqa: E402

DB_PATH = os.path.join(WORK, "pharmacy.db")
db = DB(path=DB_PATH)
PIN = db.ensure_mobile_pin()
PIN_HASH = hashlib.sha256(PIN.encode("utf-8")).hexdigest()
did = db.add_drug({"trade_en": "CloudDrug", "trade_ar": "سحابي", "scientific": "T",
                   "company": "X", "form": "Tabs", "strength": "500", "category": "T",
                   "strips_per_box": 2, "tablets_per_strip": 10, "buy_price": 40.0,
                   "sell_price": 60.0, "min_stock": 5, "barcode": "62210001"})
db.conn.execute("INSERT INTO batches (drug_id, batch_no, expiry, qty_units, buy_price_unit, created_at) "
                "VALUES (?,?,?,?,?,?)", (did, "B1", "2030-01-01", 100, 40.0, "2026-01-01"))
db.conn.commit()

class FakeClient:
    """عميل سحابة مزيف: طلبات جاهزة ويسجل تحديثات الحالة."""
    def __init__(self, orders):
        self.orders = orders
        self.updates = []
    def fetch_pending_orders(self, limit=10):
        return self.orders[:limit]
    def update_order(self, order_id, status, result=None):
        self.updates.append((order_id, status, result))

def order(oid, **kw):
    payload = {"pin_hash": PIN_HASH, "payment": "cash", "paid": None,
               "note": "", "discount": 0, "client_ref": "ref-%d" % oid,
               "items": [{"trade_en": "CloudDrug", "strength": "500",
                          "barcode": "62210001", "unit": "box", "qty": 1}]}
    payload.update(kw)
    return {"id": oid, "created_at": "2026-11-21T00:00:00Z", "payload": payload}

# 6أ) طلب صحيح -> فاتورة محلية + حالة done
c = FakeClient([order(1)])
d, f = cloud_sync.apply_mobile_orders(db, client=c)
check("valid order applied (done=1 failed=0)", (d, f) == (1, 0), "%d/%d" % (d, f))
check("status updated done with invoice",
      c.updates and c.updates[0][1] == "done" and
      bool(c.updates[0][2]) and "invoice_no" in c.updates[0][2])
sale = db.conn.execute("SELECT * FROM sales WHERE client_ref='ref-1'").fetchone()
check("sale created locally with source=mobile",
      sale is not None and sale["source"] == "mobile")

# 6ب) نفس client_ref -> لا فاتورة مكررة
c = FakeClient([order(2, client_ref="ref-1")])
d, f = cloud_sync.apply_mobile_orders(db, client=c)
count = db.conn.execute("SELECT COUNT(*) n FROM sales WHERE client_ref='ref-1'").fetchone()["n"]
check("client_ref idempotent (no duplicate sale)", d == 1 and count == 1)

# 6ج) رمز خاطئ -> فشل بدون بيع
c = FakeClient([order(3, pin_hash="0" * 64)])
d, f = cloud_sync.apply_mobile_orders(db, client=c)
check("wrong PIN rejected", (d, f) == (0, 1) and c.updates[0][1] == "failed")
check("PIN error mentions الرمز", "PIN" in (c.updates[0][2] or {}).get("error", ""))

# 6د) صنف غير موجود -> فشل
c = FakeClient([order(4, items=[{"trade_en": "NoSuchDrug", "strength": "1",
                                 "barcode": "", "unit": "box", "qty": 1}])])
d, f = cloud_sync.apply_mobile_orders(db, client=c)
check("unknown drug rejected", (d, f) == (0, 1))

# 6هـ) آجل مرفوض في الوضع السحابي
c = FakeClient([order(5, payment="credit")])
d, f = cloud_sync.apply_mobile_orders(db, client=c)
check("credit rejected in cloud mode", (d, f) == (0, 1))

# 6و) مخزون غير كافٍ -> فشل برسالة الخطأ نفسها من منطق البيع
c = FakeClient([order(6, items=[{"trade_en": "CloudDrug", "strength": "500",
                                 "barcode": "", "unit": "box", "qty": 9999}])])
d, f = cloud_sync.apply_mobile_orders(db, client=c)
check("insufficient stock rejected", (d, f) == (0, 1))

# 6ز) الحل بالباركود وبالاسم كلاهما يعمل
row = db.conn.execute("SELECT id FROM drugs WHERE trade_en='CloudDrug'").fetchone()
check("resolve by barcode", cloud_sync._resolve_drug_id(db, {"barcode": "62210001"}) == row["id"])
check("resolve by name+strength",
      cloud_sync._resolve_drug_id(db, {"trade_en": "CloudDrug", "strength": "500", "barcode": ""}) == row["id"])
db.close()

# ---------- 7) ملف SQL للإعداد موجود ----------
sql_path = os.path.join(SRC, "docs", "supabase_mobile_orders.sql")
check("docs/supabase_mobile_orders.sql exists", os.path.isfile(sql_path))
if os.path.isfile(sql_path):
    sql = open(sql_path, encoding="utf-8").read()
    # الملف الحالي إيقاف نشر مقصود حتى يُشحن التصميم المصادَق
    # (حساب مخصص + RLS بلا أي صلاحية للمفتاح العلني).
    check("sql is the deliberate deployment stop", "RAISE EXCEPTION" in sql)
    check("sql grants nothing to the anon key",
          not any("grant" in ln.lower() and "anon" in ln.lower()
                  for ln in sql.splitlines()))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
