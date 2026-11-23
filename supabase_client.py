# -*- coding: utf-8 -*-
"""عميل Supabase (PostgREST) لمشروع صيدلية المؤسسة — مكتبة قياسية فقط.

يقرأ الإعداد من متغيرين في البيئة:
    SUPABASE_URL  مثل https://xxxx.supabase.co
    SUPABASE_KEY  مفتاح publishable (أو secret) من لوحة Supabase
أو من ملف supabase_config.json بجوار البرنامج:
    {"url": "https://xxxx.supabase.co", "key": "..."}

الملف supabase_config.json متجاهل في .gitignore — لا ترفع المفتاح الحقيقي
للمستودع أبداً. انسخ supabase_config.example.json وعدّل قيمتيه.

لا يُستخدم هذا الموديول إلا عبر cloud_sync.py؛ إن لم يكن الإعداد موجوداً
يبقى البرنامج يعمل محلياً كما كان تماماً.
"""

import json
import base64
import os
import urllib.error
import urllib.parse
import urllib.request

TABLE = "products"
PAGE = 1000

# الأعمدة المشتركة بين جدول drugs المحلي وجدول products السحابي
PRODUCT_COLUMNS = (
    "catalog", "trade_en", "trade_ar", "scientific", "company", "form",
    "strength", "category", "strips_per_box", "tablets_per_strip",
    "buy_price", "sell_price", "min_stock", "barcode",
)


class SupabaseError(Exception):
    """أي فشل في الاتصال أو في استجابة الـ API."""


def _normalize_url(raw):
    """يوحّد رابط Supabase: يضيف https:// تلقائياً إن نُسيت، ويحذف / الأخيرة.

    يرجع "" إن كان الرابط فارغاً أو غير صالح إطلاقاً (بلا host)، حتى لا
    يسقط urllib لاحقاً بخطأ غير مفهوم مثل "unknown url type".
    """
    url = (raw or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    url = url.rstrip("/")
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    if any(c.isspace() for c in url):
        return ""
    return url


def load_config(path=None):
    """يرجع (url, key) أو (None, None) إن لم يُضبط الإعداد بعد.

    الأولوية: متغيرات البيئة، ثم ملف supabase_config.json بجوار البرنامج.
    الرابط يُطبّع عبر _normalize_url: كتابة xxxx.supabase.co بدون https://
    تعمل كما هي، والرابط التالف يُعامل كأن الإعداد غير موجود بدل أن يُسقط
    المزامنة بخطأ غير واضح.
    """
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_KEY") or "").strip()
    if not (url and key):
        cfg_path = path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "supabase_config.json")
        try:
            with open(cfg_path, encoding="utf-8") as f:
                data = json.load(f)
            url = url or (data.get("url") or "").strip()
            key = key or (data.get("key") or "").strip()
        except (OSError, ValueError):
            pass
    url = _normalize_url(url)
    if url and key:
        return url, key
    return None, None


def browser_safe_key(key):
    """Only documented public key forms may leave the desktop for a phone.

    This is classification, not JWT verification or an authorization grant.
    Public keys remain dangerous when server policies permit public writes.
    """
    if not isinstance(key, str):
        return False
    if key.startswith('sb_publishable_'):
        return len(key) > len('sb_publishable_')
    try:
        parts = key.split('.')
        if len(parts) != 3:
            return False
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
        return payload.get('role') == 'anon'
    except (ValueError, TypeError, AttributeError, UnicodeError):
        return False


def is_configured(path=None):
    url, key = load_config(path)
    return bool(url and key)


class SupabaseClient:
    """غلاف صغير حول PostgREST: بحث، جلب، إدراج/تحديث (upsert)، حذف."""

    def __init__(self, url=None, key=None, timeout=30):
        cfg_url, cfg_key = load_config()
        raw_url = url if url is not None else (cfg_url or "")
        self.url = _normalize_url(raw_url)
        self.key = (key or cfg_key or "").strip()
        if raw_url and not self.url:
            raise SupabaseError(
                "رابط Supabase في الإعداد غير صالح — اكتبه كاملاً مثل "
                "https://xxxx.supabase.co (راجع supabase_config.json)")
        if not (self.url and self.key):
            raise SupabaseError(
                "إعداد Supabase غير موجود — اضبط SUPABASE_URL/SUPABASE_KEY "
                "أو ملف supabase_config.json")
        self.timeout = timeout

    # ---------- أساسيات HTTP ----------
    def _request(self, method, path, params=None, body=None, extra_headers=None):
        query = ("?" + urllib.parse.urlencode(params)) if params else ""
        req = urllib.request.Request(self.url + path + query, method=method)
        req.add_header("apikey", self.key)
        req.add_header("Authorization", "Bearer " + self.key)
        req.add_header("Accept", "application/json")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        for k, v in (extra_headers or {}).items():
            req.add_header(k, v)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        try:
            with urllib.request.urlopen(req, data=data, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                headers = dict(resp.headers.items())
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8")[:300]
            except Exception:
                detail = ""
            raise SupabaseError("HTTP %d من Supabase: %s" % (e.code, detail))
        except (urllib.error.URLError, OSError) as e:
            raise SupabaseError("تعذر الاتصال بـ Supabase: %s" % e)
        return (json.loads(raw) if raw.strip() else None), headers

    # ---------- قراءة ----------
    def search(self, query="", catalog=None, limit=50):
        """بحث نصي في الاسم التجاري (إنجليزي أو عربي) أو المادة الفعالة."""
        params = {"select": "*", "limit": int(limit), "order": "trade_en.asc"}
        q = (query or "").strip()
        if q:
            # أقواس وفواصل ونقاط في النص تكسر صيغة or= في PostgREST
            q = "".join(ch for ch in q if ch.isalnum() or ch in " -_@")
        if q:
            like = "*%s*" % q.replace("*", "")
            params["or"] = ("(trade_en.ilike.%s,trade_ar.ilike.%s,"
                            "scientific.ilike.%s)" % (like, like, like))
        if catalog:
            params["catalog"] = "eq." + catalog
        rows, _ = self._request("GET", "/rest/v1/" + TABLE, params)
        return rows

    def get_by_barcode(self, barcode):
        params = {"select": "*", "barcode": "eq." + (barcode or ""), "limit": 1}
        rows, _ = self._request("GET", "/rest/v1/" + TABLE, params)
        return rows[0] if rows else None

    def count(self):
        _, headers = self._request(
            "GET", "/rest/v1/" + TABLE,
            {"select": "id"},
            extra_headers={"Prefer": "count=exact", "Range": "0-0"})
        content_range = headers.get("Content-Range") or headers.get("content-range") or ""
        try:
            return int(content_range.split("/")[-1])
        except (ValueError, IndexError):
            raise SupabaseError("تعذر قراءة عدد الصفوف من Supabase")

    def fetch_page(self, offset, updated_since=None, columns="*"):
        """صفحة واحدة من المنتجات مرتبة بالمعرف — تستخدم للمزامنة الكاملة."""
        params = {
            "select": columns, "order": "id.asc",
            "offset": int(offset), "limit": PAGE,
        }
        if updated_since:
            params["updated_at"] = "gt." + updated_since
        rows, _ = self._request("GET", "/rest/v1/" + TABLE, params)
        return rows

    def fetch_catalog_keys(self):
        """(trade_en, strength) -> catalog لكل الصفوف — يميّز الأدوية عن
        الكوزمتكس عند رفع الكتالوج المحلي حتى لا تتكرر الصفوف."""
        keys = {}
        offset = 0
        while True:
            rows = self.fetch_page(offset, columns="trade_en,strength,catalog")
            for r in rows:
                keys[(r.get("trade_en") or "", r.get("strength") or "")] = \
                    r.get("catalog") or "drug"
            if len(rows) < PAGE:
                break
            offset += PAGE
        return keys

    # ---------- كتابة ----------
    def upsert_products(self, rows):
        """إدراج أو تحديث حسب (catalog, trade_en, strength) — آمن للتكرار."""
        if not rows:
            return 0
        clean = [{k: v for k, v in r.items() if k in PRODUCT_COLUMNS} for r in rows]
        self._request(
            "POST", "/rest/v1/" + TABLE,
            params={"on_conflict": "catalog,trade_en,strength"},
            body=clean,
            extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
        return len(clean)

    # ---------- طابور فواتير الموبايل (v6.26 — الوضع السحابي) ----------
    # جدول mobile_orders: الهاتف يدرج طلب بيع عندما يتعذر الوصول للكمبيوتر،
    # والبرنامج يسحب الطلبات المعلقة ويطبقها بنفس منطق البيع المحلي ثم
    # يحدّث الحالة ليقرأها الهاتف. الإعداد والصلاحيات في
    # docs/supabase_mobile_orders.sql.
    def fetch_pending_orders(self, limit=10):
        """طلبات البيع المعلقة من الهاتف، الأقدم أولاً."""
        rows, _ = self._request(
            "GET", "/rest/v1/mobile_orders",
            {"select": "id,created_at,payload", "status": "eq.pending",
             "order": "created_at.asc", "limit": int(limit)})
        return rows or []

    def update_order(self, order_id, status, result=None):
        """يحدّث حالة الطلب (done/failed) مع النتيجة ليقرأها الهاتف."""
        from datetime import datetime, timezone
        body = {"status": status,
                "processed_at": datetime.now(timezone.utc).isoformat()}
        if result is not None:
            body["result"] = result
        self._request(
            "PATCH", "/rest/v1/mobile_orders",
            {"id": "eq.%d" % int(order_id)}, body=body,
            extra_headers={"Prefer": "return=minimal"})

    def delete_product(self, product_id):
        self._request("DELETE", "/rest/v1/" + TABLE,
                      {"id": "eq.%d" % int(product_id)},
                      extra_headers={"Prefer": "return=minimal"})

    def ping(self):
        """فحص سريع أن الاتصال والمفتاح يعملان."""
        return self.count()
