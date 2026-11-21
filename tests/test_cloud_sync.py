# -*- coding: utf-8 -*-
"""اختبارات المزامنة السحابية (v6.11).

الوحدة الأولى (TestCloudSyncLocal) تعمل بدون نت: تتحقق من التحويل بين
الصيغتين، ومن عدم تعطل البرنامج بدون إعداد، ومن كتم الرفع أثناء السحب.
الوحدة الثانية (TestCloudSyncLive) تعمل على الـ API الحقيقي فقط عندما
تتوفر SUPABASE_URL وSUPABASE_KEY في البيئة، وتستخدم صفاً اختبارياً
واضح الاسم يُحذف بعد الانتهاء.

التشغيل: py tests/test_cloud_sync.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cloud_sync
import supabase_client
from database import DB


def fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return DB(path=path), path


DRUG = {
    "trade_en": "Cloud Sync Test Drug", "trade_ar": "اختبار",
    "scientific": "Testinol", "company": "Test Pharma", "form": "Tablet",
    "strength": "500mg", "category": "Test", "strips_per_box": 2,
    "tablets_per_strip": 10, "buy_price": 10.0, "sell_price": 15.0,
    "min_stock": 5, "barcode": "",
}


class FakeClient:
    """عميل وهمي يحاكي السحابة في الذاكرة."""

    def __init__(self, rows=()):
        self.rows = [dict(r) for r in rows]
        self.upserted = []

    def upsert_products(self, rows):
        self.upserted.extend(rows)
        return len(rows)

    def fetch_page(self, offset, updated_since=None, columns="*"):
        return self.rows[offset:offset + supabase_client.PAGE]

    def fetch_catalog_keys(self):
        return {(r.get("trade_en") or "", r.get("strength") or ""):
                r.get("catalog") or "drug" for r in self.rows}


class TestCloudSyncLocal(unittest.TestCase):
    def setUp(self):
        # اعزل الاختبارات عن أي إعداد حقيقي في البيئة
        self._env = {k: os.environ.pop(k, None)
                     for k in ("SUPABASE_URL", "SUPABASE_KEY")}
        self.db, self.path = fresh_db()
        self.addCleanup(self._close)

    def _close(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except OSError:
                pass
        for k, v in self._env.items():
            if v is not None:
                os.environ[k] = v

    def test_unconfigured_is_silent_noop(self):
        # بدون إعداد: لا إضافة صنف تتعطل، ولا push/pull يعمل
        self.assertFalse(supabase_client.is_configured())
        drug_id = self.db.add_drug(dict(DRUG))
        self.assertTrue(drug_id)
        self.assertFalse(cloud_sync.push_drug_safe(self.db, drug_id))
        with self.assertRaises(supabase_client.SupabaseError):
            cloud_sync.pull_catalog(self.db)

    def test_drug_to_product_mapping(self):
        drug_id = self.db.add_drug(dict(DRUG))
        row = self.db.conn.execute(
            "SELECT * FROM drugs WHERE id=?", (drug_id,)).fetchone()
        product = cloud_sync.drug_to_product(self.db, row)
        for key in ("trade_en", "trade_ar", "scientific", "company", "form",
                    "strength", "category", "strips_per_box",
                    "tablets_per_strip", "buy_price", "sell_price", "min_stock"):
            self.assertEqual(product[key], DRUG[key], key)
        self.assertEqual(product["catalog"], "drug")
        self.assertEqual(product["barcode"], "")

    def test_pull_inserts_then_updates_without_duplicates(self):
        cloud_rows = [cloud_sync.product_to_fields(DRUG)]
        fake = FakeClient(cloud_rows)
        # حقن العميل الوهمي
        orig = cloud_sync._client
        cloud_sync._client = lambda: fake
        try:
            added, updated, skipped = cloud_sync.pull_catalog(self.db)
            self.assertEqual((added, updated, skipped), (1, 0, 0))
            # سحب ثانٍ: تحديث لنفس الصف، لا تكرار
            fake.rows[0]["sell_price"] = 99.0
            added, updated, skipped = cloud_sync.pull_catalog(self.db)
            self.assertEqual((added, updated, skipped), (0, 1, 0))
            rows = self.db.conn.execute(
                "SELECT * FROM drugs WHERE trade_en=?",
                (DRUG["trade_en"],)).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["sell_price"], 99.0)
            # السحب لم يرفع شيئاً للسحابة (كتم الرفع)
            self.assertEqual(fake.upserted, [])
        finally:
            cloud_sync._client = orig

    def test_pull_drops_conflicting_barcode(self):
        # صنف محلي مختلف يملك الباركود مسبقاً
        other = dict(DRUG, trade_en="Other Local Drug", barcode="6221234567890")
        self.db.add_drug(other)
        row = cloud_sync.product_to_fields(
            dict(DRUG, barcode="6221234567890"))
        fake = FakeClient([row])
        orig = cloud_sync._client
        cloud_sync._client = lambda: fake
        try:
            added, updated, skipped = cloud_sync.pull_catalog(self.db)
            self.assertEqual(added, 1)
            # الصنف الجديد أُضيف بدون الباركود المتعارض
            new_id = self.db.conn.execute(
                "SELECT id FROM drugs WHERE trade_en=?",
                (DRUG["trade_en"],)).fetchone()["id"]
            self.assertIn(self.db.drug_barcode(new_id), (None, ""))
            # والباركود ما زال مع صاحبه الأصلي
            drug, _pack = self.db.lookup_barcode("6221234567890")
            self.assertEqual(drug["trade_en"], "Other Local Drug")
        finally:
            cloud_sync._client = orig

    def test_push_all_uses_cloud_catalog(self):
        self.db.add_drug(dict(DRUG))
        self.db.add_drug(dict(DRUG, trade_en="Cloud Sync Test Cream",
                              strength="200 ml", scientific=""))
        fake = FakeClient([
            {"trade_en": "Cloud Sync Test Cream", "strength": "200 ml",
             "catalog": "cosmetic"},
        ])
        orig = cloud_sync._client
        cloud_sync._client = lambda: fake
        try:
            sent, failed = cloud_sync.push_all(self.db)
            self.assertEqual(failed, 0)
            self.assertEqual(sent, 2)
            catalogs = {r["trade_en"]: r["catalog"] for r in fake.upserted}
            self.assertEqual(catalogs["Cloud Sync Test Drug"], "drug")
            self.assertEqual(catalogs["Cloud Sync Test Cream"], "cosmetic")
        finally:
            cloud_sync._client = orig


@unittest.skipUnless(
    os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"),
    "live test needs SUPABASE_URL/SUPABASE_KEY in the environment")
class TestCloudSyncLive(unittest.TestCase):
    """رحلة حقيقية: upsert صف اختبار، قراءته، ثم حذفه."""

    TEST_NAME = "ZZ CLOUD SYNC SELFTEST ROW"

    def setUp(self):
        self.client = supabase_client.SupabaseClient()

    def tearDown(self):
        try:
            found = self.client.search(self.TEST_NAME, limit=5)
            for row in found:
                if row["trade_en"] == self.TEST_NAME:
                    self.client.delete_product(row["id"])
        except Exception:
            pass

    def test_roundtrip(self):
        payload = {
            "catalog": "drug", "trade_en": self.TEST_NAME,
            "trade_ar": "", "scientific": "", "company": "Instinct self-test",
            "form": "Tablet", "strength": "1mg", "category": "test",
            "strips_per_box": 1, "tablets_per_strip": 1,
            "buy_price": 1.0, "sell_price": 2.0, "min_stock": 0, "barcode": "",
        }
        self.client.upsert_products([payload])
        found = [r for r in self.client.search(self.TEST_NAME, limit=5)
                 if r["trade_en"] == self.TEST_NAME]
        self.assertEqual(len(found), 1)
        # upsert ثانٍ: لا تكرار (نفس مفتاح catalog/trade_en/strength)
        payload["sell_price"] = 3.0
        self.client.upsert_products([payload])
        found = [r for r in self.client.search(self.TEST_NAME, limit=5)
                 if r["trade_en"] == self.TEST_NAME]
        self.assertEqual(len(found), 1)
        self.assertEqual(float(found[0]["sell_price"]), 3.0)
        self.client.delete_product(found[0]["id"])
        found = [r for r in self.client.search(self.TEST_NAME, limit=5)
                 if r["trade_en"] == self.TEST_NAME]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
