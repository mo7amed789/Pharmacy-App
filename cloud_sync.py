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

import hashlib
import threading
import time

import supabase_client
from supabase_client import SupabaseClient, SupabaseError

# إعدادات تُحفظ في جدول settings لتظهر في شاشة الإعدادات
K_LAST_PULL = "cloud_last_pull"
K_LAST_PUSH = "cloud_last_push"
K_LAST_ERROR = "cloud_last_error"
K_LAST_ORDERS = "cloud_orders_last"
K_LAST_ORDERS_ERROR = "cloud_orders_last_error"


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
        "orders_last": db.get_setting(K_LAST_ORDERS, ""),
        "orders_error": db.get_setting(K_LAST_ORDERS_ERROR, ""),
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


# ---------- طابور فواتير الموبايل (v6.26 — الوضع السحابي) ----------
# عندما لا يصل الهاتف للكمبيوتر (لا واي فاي مشترك) يدرج طلب البيع في
# جدول mobile_orders بالسحابة، والبرنامج هنا يسحبه ويطبقه بنفس
# create_sale_from_items التي يستخدمها سيرفر الموبايل — لا نسخة ثانية
# من منطق البيع. الهاتف يرسل بصمة SHA-256 للرمز (PIN) لا الرمز نفسه،
# والبرنامج يقارنها برمزه الحالي قبل أي بيع: من يملك مفتاح السحابة وحده
# لا يستطيع حقن فواتير.

def _pin_hash(pin):
    return hashlib.sha256((pin or "").encode("utf-8")).hexdigest()


def _resolve_drug_id(db, item):
    """يربط صنف الطلب السحابي بدواء محلي: بالباركود أولاً ثم بمطابقة
    (trade_en, strength) — نفس مطابقة pull_catalog."""
    import database as database_module
    barcode = (item.get("barcode") or "").strip()
    if barcode:
        code = database_module.extract_gtin(barcode)
        if code:
            row = db.conn.execute(
                "SELECT drug_id FROM barcodes WHERE barcode=?",
                (code,)).fetchone()
            if row:
                return int(row["drug_id"])
    name = (item.get("trade_en") or "").strip()
    strength = (item.get("strength") or "").strip()
    if name:
        row = db.conn.execute(
            "SELECT id FROM drugs WHERE trade_en=? AND strength=? AND active=1",
            (name, strength)).fetchone()
        if row:
            return int(row["id"])
    return None


def apply_cloud_order(db, order):
    """يطبق طلب بيع واحداً من السحابة. يرجع (result, error): عند النجاح
    result قاموس الفاتورة وerror=None، وعند الفشل result=None وerror نص
    يظهر للهاتف."""
    payload = order.get("payload")
    if not isinstance(payload, dict):
        return None, "بيانات الطلب غير صالحة"
    if str(payload.get("pin_hash") or "") != _pin_hash(db.ensure_mobile_pin()):
        return None, "رمز الموبايل (PIN) غير صحيح — أدخل الرمز الحالي من تبويب الموبايل"
    payment = str(payload.get("payment") or "cash").strip()
    if payment not in ("cash", "card"):
        return None, "البيع الآجل يحتاج اتصالاً مباشراً بالكمبيوتر"
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None, "بيانات أصناف غير صالحة"
    items_spec = []
    for it in items:
        if not isinstance(it, dict):
            return None, "بيانات صنف غير صالحة"
        did = _resolve_drug_id(db, it)
        if did is None:
            label = (it.get("trade_en") or it.get("barcode") or "?")
            return None, "صنف غير موجود محلياً: %s" % label
        items_spec.append({"drug_id": did, "unit": it.get("unit"),
                           "qty": it.get("qty")})
    client_ref = str(payload.get("client_ref") or "")[:64]
    paid = payload.get("paid")
    try:
        paid = float(paid) if paid is not None else None
    except (TypeError, ValueError):
        return None, "مبلغ مدفوع غير صالح"
    try:
        discount = float(payload.get("discount") or 0)
    except (TypeError, ValueError):
        return None, "خصم غير صالح"
    try:
        sale_id, invoice_no, total, change = db.create_sale_from_items(
            cashier="mobile", items_spec=items_spec, discount=discount,
            payment_method=payment, customer_id=None, paid=paid,
            shift_id=db.active_shift_id(), source="mobile",
            client_ref=client_ref)
    except ValueError as e:
        return None, str(e)
    note = str(payload.get("note") or "").strip()
    if note:
        db.audit("mobile", "cloud_invoice_note",
                 "%s: %s" % (invoice_no, note[:200]))
    db.audit("mobile", "cloud_invoice", "%s (order %s)" % (invoice_no, order.get("id")))
    return {"sale_id": sale_id, "invoice_no": invoice_no,
            "total": float(total), "change": float(change)}, None


def apply_mobile_orders(db, client=None, limit=10):
    """يسحب الطلبات المعلقة ويطبقها. يرجع (عدد الناجح, عدد الفاشل).
    client_ref في قاعدة البيانات يمنع التكرار لو أُعيدت المعالجة."""
    client = client or _client()
    if client is None:
        return 0, 0
    done = failed = 0
    for order in client.fetch_pending_orders(limit):
        result, err = apply_cloud_order(db, order)
        try:
            if err is None:
                client.update_order(order["id"], "done", result)
                done += 1
            else:
                client.update_order(order["id"], "failed", {"error": err})
                failed += 1
        except (SupabaseError, KeyError, TypeError):
            break  # تعذر تحديث السحابة — يُعاد الطلب في الدورة القادمة
    return done, failed


def start_order_polling(db_path, interval=15):
    """خيط خلفي يسحب فواتير الهاتف من السحابة كل `interval` ثانية طالما
    المزامنة مفعّلة. أفضل جهد بالكامل: لا إنترنت = انتظار فقط، ولا يؤثر
    على عمل البرنامج محلياً. يفتح اتصال قاعدة بيانات خاصاً به في كل
    دورة (لا تُشارك الاتصالات بين الخيوط)."""
    def loop():
        failures = 0
        while True:
            wait = interval
            try:
                if supabase_client.is_configured():
                    import database as database_module
                    db = database_module.DB(path=db_path, init=False)
                    try:
                        d, f = apply_mobile_orders(db)
                        if d or f:
                            _set(db, K_LAST_ORDERS, _now_str())
                            db.audit("", "cloud_orders",
                                     "done %d failed %d" % (d, f))
                        _set(db, K_LAST_ORDERS_ERROR, "")
                    finally:
                        db.close()
                    failures = 0
            except Exception as e:
                failures += 1
                wait = min(300, interval * (2 ** min(failures, 4)))
                try:
                    import database as database_module
                    db = database_module.DB(path=db_path, init=False)
                    _set(db, K_LAST_ORDERS_ERROR, str(e)[:200])
                    db.close()
                except Exception:
                    pass
            time.sleep(wait)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


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
