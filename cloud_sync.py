# -*- coding: utf-8 -*-
"""مزامنة كتالوج الأصناف بين قاعدة SQLite المحلية وSupabase السحابية.

الاتجاهان:
- push: أي إضافة/تعديل صنف من شاشات البرنامج يُرفع للسحابة فوراً
  (أفضل جهد: لو النت مقطوع البرنامج لا يتعطل ويحفظ العملية محلياً كالعادة).
- pull: زر «سحب الكتالوج من السحابة» في الإعدادات يجلب كل المنتجات
  (أدوية + كوزمتكس) ويحدّث الأسعار محلياً بنفس منطق استيراد CSV —
  نفس الصنف يتحدث ولا يتكرر.

السحابة تحفظ بيانات الصنف والأسعار فقط؛ المخزون (التشغيلات/الباتشات)
والمبيعات والمستخدمون يبقون محليين — جدول products لا يحفظ مخزوناً.
"""

import threading

import supabase_client
from supabase_client import SupabaseClient, SupabaseError

# إعدادات تُحفظ في جدول settings لتظهر في شاشة الإعدادات
K_LAST_PULL = "cloud_last_pull"
K_LAST_PUSH = "cloud_last_push"
K_LAST_ERROR = "cloud_last_error"


def _client():
    """عميل جاهز أو None إن لم يُضبط الإعداد."""
    if not supabase_client.is_configured():
        return None
    return SupabaseClient()


def _set(db, key, value):
    try:
        db.set_setting(key, value)
    except Exception:
        pass


def status(db):
    """حالة المزامنة كما تعرضها شاشة الإعدادات."""
    if not supabase_client.is_configured():
        return {"configured": False}
    return {
        "configured": True,
        "last_pull": db.get_setting(K_LAST_PULL, ""),
        "last_push": db.get_setting(K_LAST_PUSH, ""),
        "last_error": db.get_setting(K_LAST_ERROR, ""),
    }


# ---------- التحويل بين الصيغتين ----------

def drug_to_product(db, drug_row, catalog="drug"):
    """صف من جدول drugs المحلي إلى صف products سحابي."""
    d = dict(drug_row)
    barcode = ""
    try:
        row = db.conn.execute(
            "SELECT barcode FROM barcodes WHERE drug_id=? AND pack_level='box' "
            "LIMIT 1", (d["id"],)).fetchone()
        barcode = row["barcode"] if row else ""
    except Exception:
        pass
    return {
        "catalog": catalog,
        "trade_en": d.get("trade_en") or "",
        "trade_ar": d.get("trade_ar") or "",
        "scientific": d.get("scientific") or "",
        "company": d.get("company") or "",
        "form": d.get("form") or "",
        "strength": d.get("strength") or "",
        "category": d.get("category") or "",
        "strips_per_box": int(d.get("strips_per_box") or 1),
        "tablets_per_strip": int(d.get("tablets_per_strip") or 1),
        "buy_price": float(d.get("buy_price") or 0),
        "sell_price": float(d.get("sell_price") or 0),
        "min_stock": int(d.get("min_stock") or 0),
        "barcode": barcode,
    }


def product_to_fields(row):
    """صف products سحابي إلى حقول add_drug/update_drug المحلية."""
    return {
        "trade_en": (row.get("trade_en") or "").strip(),
        "trade_ar": (row.get("trade_ar") or "").strip(),
        "scientific": (row.get("scientific") or "").strip(),
        "company": (row.get("company") or "").strip(),
        "form": (row.get("form") or "").strip(),
        "strength": (row.get("strength") or "").strip(),
        "category": (row.get("category") or "").strip(),
        "strips_per_box": int(row.get("strips_per_box") or 1),
        "tablets_per_strip": int(row.get("tablets_per_strip") or 1),
        "buy_price": float(row.get("buy_price") or 0),
        "sell_price": float(row.get("sell_price") or 0),
        "min_stock": int(row.get("min_stock") or 0),
        "barcode": (row.get("barcode") or "").strip(),
    }


# ---------- push: محلي → سحابة ----------

def push_drug(db, drug_id, catalog="drug"):
    """يرفع صنفاً واحداً للسحابة. يرفع SupabaseError عند الفشل."""
    client = _client()
    if client is None:
        return False
    row = db.conn.execute("SELECT * FROM drugs WHERE id=?", (drug_id,)).fetchone()
    if row is None:
        return False
    client.upsert_products([drug_to_product(db, row, catalog)])
    _set(db, K_LAST_PUSH, _now_str())
    _set(db, K_LAST_ERROR, "")
    return True


def push_drug_safe(db, drug_id):
    """نسخة «أفضل جهد»: لا ترفع أي استثناء أبداً حتى لا تتعطل شاشة البيع."""
    try:
        return push_drug(db, drug_id)
    except Exception as e:
        _set(db, K_LAST_ERROR, str(e))
        return False


def push_all(db, batch=500, progress=None):
    """يرفع كل الأصناف المحلية للسحابة على دفعات.

    يميّز الأدوية عن الكوزمتكس بمطابقة (trade_en, strength) مع المفاتيح
    الموجودة في السحابة أولاً، حتى لا تنشأ صفوف مكررة بكتالوج خاطئ.
    يرجع (عدد المرفوع, عدد الفاشل)."""
    client = _client()
    if client is None:
        raise SupabaseError("إعداد Supabase غير موجود")
    cloud_keys = client.fetch_catalog_keys()
    rows = db.conn.execute(
        "SELECT * FROM drugs WHERE active=1 ORDER BY id").fetchall()
    sent, failed = 0, 0
    pending = []
    for r in rows:
        d = dict(r)
        catalog = cloud_keys.get(
            (d.get("trade_en") or "", d.get("strength") or ""), "drug")
        pending.append(drug_to_product(db, r, catalog))
        if len(pending) >= batch:
            try:
                client.upsert_products(pending)
                sent += len(pending)
            except SupabaseError:
                failed += len(pending)
            pending = []
            if progress:
                progress(sent, failed)
    if pending:
        try:
            client.upsert_products(pending)
            sent += len(pending)
        except SupabaseError:
            failed += len(pending)
    _set(db, K_LAST_PUSH, _now_str())
    db.audit("", "cloud_push", "pushed %d failed %d" % (sent, failed))
    return sent, failed


# ---------- pull: سحابة → محلي ----------

def pull_catalog(db, user="", progress=None):
    """يسحب كل المنتجات من السحابة ويدمجها محلياً (تحديث بلا تكرار).

    نفس دلالة استيراد CSV: المطابقة على (trade_en, strength)، والصف
    الموجود يتحدث والجديد يُضاف. الباركود المتعارض مع صنف آخر أو غير
    الصالح يُسقط من الصف بدل إيقاف المزامنة (مثل بناء ملفات الكتالوج).
    أثناء السحب تُكتم مزامنة الرفع حتى لا يُعاد رفع كل صف للسحابة.
    يرجع (جديد, محدّث, متجاهَل)."""
    import database as database_module
    client = _client()
    if client is None:
        raise SupabaseError("إعداد Supabase غير موجود")
    added, updated, skipped = 0, 0, 0
    offset = 0
    db._cloud_mute = True
    try:
        while True:
            rows = client.fetch_page(offset)
            if not rows:
                break
            for row in rows:
                try:
                    fields = product_to_fields(row)
                    if not fields["trade_en"]:
                        skipped += 1
                        continue
                    db._validate_drug_fields(fields)
                except (ValueError, TypeError):
                    skipped += 1
                    continue
                # باركود غير صالح يُسقط من الصف
                if fields["barcode"] and not database_module.extract_gtin(fields["barcode"]):
                    fields["barcode"] = ""
                existing = db.conn.execute(
                    "SELECT id FROM drugs WHERE trade_en=? AND strength=?",
                    (fields["trade_en"], fields["strength"])).fetchone()
                # باركود مسجل لصنف آخر يُسقط أيضاً (مثل بناء الكتالوج)
                if fields["barcode"]:
                    code = database_module.extract_gtin(fields["barcode"])
                    owner = db.conn.execute(
                        "SELECT drug_id FROM barcodes WHERE barcode=?",
                        (code,)).fetchone()
                    if owner and (not existing or
                                  int(owner["drug_id"]) != int(existing["id"])):
                        fields["barcode"] = ""
                try:
                    if existing:
                        db.update_drug(existing["id"], fields, _commit=False)
                        if fields["barcode"]:
                            db._link_barcode_checked(
                                db.conn, fields["barcode"], existing["id"])
                        updated += 1
                    else:
                        db.add_drug(fields, _commit=False)
                        added += 1
                except ValueError:
                    skipped += 1
            db.conn.commit()
            if progress:
                progress(added, updated, skipped)
            if len(rows) < supabase_client.PAGE:
                break
            offset += supabase_client.PAGE
    finally:
        db._cloud_mute = False
    _set(db, K_LAST_PULL, _now_str())
    _set(db, K_LAST_ERROR, "")
    db.audit(user, "cloud_pull",
             "added %d updated %d skipped %d" % (added, updated, skipped))
    return added, updated, skipped


# ---------- تشغيل في الخلفية من الواجهة ----------

def run_in_background(fn, on_done):
    """يشغّل دالة مزامنة بعيداً عن خيط الواجهة ويستدعي on_done(result, error)."""
    def worker():
        try:
            on_done(fn(), None)
        except Exception as e:
            on_done(None, e)
    threading.Thread(target=worker, daemon=True).start()


def _now_str():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
