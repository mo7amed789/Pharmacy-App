# -*- coding: utf-8 -*-
"""اختبارات المهام التلقائية وسجل التدقيق (v6.13) — كلها بدون نت.

التشغيل: py tests/test_automation.py
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import automation
import cloud_sync
from database import DB


def fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return DB(path=path), path


def hours_ago(h):
    return (datetime.now() - timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")


DRUG = {
    "trade_en": "Automation Test Drug", "trade_ar": "", "scientific": "",
    "company": "", "form": "Tablet", "strength": "10mg", "category": "",
    "strips_per_box": 1, "tablets_per_strip": 10, "buy_price": 1.0,
    "sell_price": 2.0, "min_stock": 5, "barcode": "",
}


class FakeClient:
    def __init__(self, rows=()):
        self.rows = [dict(r) for r in rows]

    def upsert_products(self, rows):
        return len(rows)

    def fetch_page(self, offset, updated_since=None, columns="*"):
        return self.rows[offset:offset + 1000]

    def fetch_catalog_keys(self):
        return {}


class AutomationTestBase(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.pop(k, None)
                     for k in ("SUPABASE_URL", "SUPABASE_KEY")}
        self.db, self.db_path = fresh_db()
        self.addCleanup(self._close)

    def _close(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.db_path + suffix)
            except OSError:
                pass
        for k, v in self._env.items():
            if v is not None:
                os.environ[k] = v
        # نظّف النسخ الاحتياطية التي صنعتها الاختبارات بجوار القاعدة المؤقتة
        bdir = os.path.join(os.path.dirname(self.db_path), "backups")
        shutil.rmtree(bdir, ignore_errors=True)


class TestDueLogic(AutomationTestBase):
    def test_first_run_is_due(self):
        self.assertTrue(automation.sync_due(self.db))
        self.assertTrue(automation.backup_due(self.db))

    def test_not_due_after_success(self):
        self.db.set_setting(automation.K_SYNC_LAST, hours_ago(2))
        self.assertFalse(automation.sync_due(self.db))
        self.db.set_setting(automation.K_BACKUP_LAST, hours_ago(2))
        self.assertFalse(automation.backup_due(self.db))

    def test_due_after_24h(self):
        self.db.set_setting(automation.K_SYNC_LAST, hours_ago(25))
        self.assertTrue(automation.sync_due(self.db))
        self.db.set_setting(automation.K_BACKUP_LAST, hours_ago(25))
        self.assertTrue(automation.backup_due(self.db))

    def test_failed_sync_retries_after_one_hour(self):
        self.db.set_setting(automation.K_SYNC_ERROR, "some error")
        self.db.set_setting(automation.K_SYNC_ATTEMPT, hours_ago(0.5))
        self.assertFalse(automation.sync_due(self.db))   # مبكر على إعادة المحاولة
        self.db.set_setting(automation.K_SYNC_ATTEMPT, hours_ago(2))
        self.assertTrue(automation.sync_due(self.db))


class TestAutoBackup(AutomationTestBase):
    def test_backup_created_verified_and_audited(self):
        dest = automation.run_backup_now(self.db)
        self.assertTrue(os.path.exists(dest))
        self.assertIn("_auto", os.path.basename(dest))
        self.assertTrue(DB.verify_backup(dest))
        self.assertEqual(self.db.get_setting(automation.K_BACKUP_ERROR), "")
        self.assertTrue(self.db.get_setting(automation.K_BACKUP_LAST))
        rows = self.db.audit_query(action="auto_backup")
        self.assertEqual(len(rows), 1)


class TestTick(AutomationTestBase):
    def test_tick_disabled_does_nothing(self):
        self.db.set_setting(automation.K_SYNC_ENABLED, "0")
        self.db.set_setting(automation.K_BACKUP_ENABLED, "0")
        self.assertEqual(automation.tick(self.db_path), [])
        self.assertEqual(self.db.get_setting(automation.K_SYNC_LAST), "")
        self.assertEqual(self.db.get_setting(automation.K_BACKUP_LAST), "")

    def test_tick_without_supabase_config_syncs_nothing(self):
        done = automation.tick(self.db_path)
        self.assertIn("backup", done)
        self.assertNotIn("sync", done)
        self.assertEqual(self.db.get_setting(automation.K_SYNC_ERROR), "")

    def test_tick_pulls_when_configured(self):
        fake = FakeClient([cloud_sync.product_to_fields(DRUG)])
        orig = cloud_sync._client
        cloud_sync._client = lambda: fake
        # أجبر is_configured على True بدون ملف إعداد حقيقي
        import supabase_client
        orig_conf = supabase_client.is_configured
        supabase_client.is_configured = lambda path=None: True
        try:
            done = automation.tick(self.db_path)
            self.assertIn("sync", done)
            self.assertTrue(self.db.get_setting(automation.K_SYNC_LAST))
            self.assertIn("جديد 1", self.db.get_setting(automation.K_SYNC_RESULT))
            self.assertEqual(self.db.get_setting(automation.K_SYNC_ERROR), "")
            # الصنف وصل محلياً
            rows = self.db.search_drugs("Automation Test Drug")
            self.assertEqual(len(rows), 1)
            # tick ثانٍ فوراً: لا شيء مستحق
            self.assertEqual(automation.tick(self.db_path), [])
        finally:
            cloud_sync._client = orig
            supabase_client.is_configured = orig_conf

    def test_tick_records_sync_failure_and_retries_later(self):
        class BadClient:
            def fetch_page(self, offset, updated_since=None, columns="*"):
                raise cloud_sync.SupabaseError("لا يوجد اتصال")
        orig = cloud_sync._client
        cloud_sync._client = lambda: BadClient()
        import supabase_client
        orig_conf = supabase_client.is_configured
        supabase_client.is_configured = lambda path=None: True
        try:
            automation.tick(self.db_path)
            err = self.db.get_setting(automation.K_SYNC_ERROR)
            self.assertIn("لا يوجد اتصال", err)
            rows = self.db.audit_query(action="auto_sync_failed")
            self.assertEqual(len(rows), 1)
            # الفشل لا يعني إعادة المحاولة فوراً
            self.assertNotIn("sync", automation.tick(self.db_path))
        finally:
            cloud_sync._client = orig
            supabase_client.is_configured = orig_conf


class TestAuditQuery(AutomationTestBase):
    def setUp(self):
        super().setUp()
        self.db.audit("admin", "sale", "INV-1 total 100.0")
        self.db.audit("admin", "add_drug", "drug 5 Panadol")
        self.db.audit("cashier", "sale", "INV-2 total 55.0")
        self.db.audit("", "auto_sync_failed", "لا يوجد اتصال")

    def test_filter_by_action(self):
        rows = self.db.audit_query(action="sale")
        self.assertEqual(len(rows), 2)

    def test_filter_by_user(self):
        rows = self.db.audit_query(user="cashier")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["details"], "INV-2 total 55.0")

    def test_filter_by_free_text(self):
        rows = self.db.audit_query(text="Panadol")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "add_drug")

    def test_actions_list_and_count(self):
        self.assertEqual(self.db.audit_count(), 4)
        self.assertEqual(self.db.audit_actions(),
                         ["add_drug", "auto_sync_failed", "sale"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
