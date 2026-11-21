# -*- coding: utf-8 -*-
"""اختبارات التحديث التلقائي من GitHub (v6.12).

كل الاختبارات تعمل بدون نت: الـ HTTP مُستبدل ببيانات وهمية في الذاكرة.
اختبار حي واحد (اختياري) يعمل عند RUN_LIVE_UPDATE_TEST=1 ويثبّت آخر
commit حقيقي في مجلد مؤقت ويتأكد أن الملفات المحلية تُحفظ.

التشغيل: py tests/test_updater.py
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater
from database import DB


def fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return DB(path=path), path


def make_zip(files, repo="Pharmacy-App", sha="abc123"):
    """zip في الذاكرة يحاكي أرشيف GitHub: جذر واحد <repo>-<sha>/."""
    buf = io.BytesIO()
    root = "%s-%s/" % (repo, sha)
    with zipfile.ZipFile(buf, "w") as zf:
        for rel, content in files.items():
            zf.writestr(root + rel, content)
    return buf.getvalue()


FAKE_LATEST = {"sha": "deadbeef1234567890", "date": "2026-11-21T08:00:00Z",
               "message": "test commit"}


class UpdaterTestBase(unittest.TestCase):
    def setUp(self):
        self.db, self.db_path = fresh_db()
        self.base = tempfile.mkdtemp(prefix="app_dir_")
        self.addCleanup(self._close)
        self.git_patch = patch.object(updater, "local_git_sha", return_value="a"*40)
        self.git_patch.start()
        self.addCleanup(self.git_patch.stop)
        # HTTP وهمي
        self._real_json, self._real_bytes = updater._http_json, updater._http_bytes
        updater._http_json = lambda url, timeout=20: FAKE_LATEST_COMMIT
        updater._http_bytes = lambda url, timeout=120: self.zip_bytes
        self.zip_bytes = b""
        self.addCleanup(self._restore_http)

    def _restore_http(self):
        updater._http_json, updater._http_bytes = self._real_json, self._real_bytes

    def _close(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.db_path + suffix)
            except OSError:
                pass
        shutil.rmtree(self.base, ignore_errors=True)

    def write_local(self, rel, content):
        path = os.path.join(self.base, *rel.split("/"))
        os.makedirs(os.path.dirname(path) or self.base, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def read_local(self, rel):
        with open(os.path.join(self.base, *rel.split("/")), encoding="utf-8") as f:
            return f.read()


# يُستخدم كرد وهمي لـ commits API: يحاكي بنية رد GitHub الحقيقية
FAKE_LATEST_COMMIT = {
    "sha": FAKE_LATEST["sha"],
    "commit": {"committer": {"date": FAKE_LATEST["date"]},
               "message": FAKE_LATEST["message"] + "\n"},
}


class TestCheckForUpdate(UpdaterTestBase):
    def test_first_run_uses_local_revision_not_remote(self):
        result = updater.check_for_update(self.db)
        self.assertEqual(result["status"], "update_available")
        self.assertEqual(self.db.get_setting(updater.K_APPLIED_SHA), "a"*40)

    def test_same_sha_is_up_to_date(self):
        self.db.set_setting(updater.K_APPLIED_SHA, FAKE_LATEST["sha"])
        result = updater.check_for_update(self.db)
        self.assertEqual(result["status"], "up_to_date")

    def test_matching_checkout_after_manual_pull(self):
        self.db.set_setting(updater.K_APPLIED_SHA, "older")
        with patch.object(updater, "local_git_sha", return_value=FAKE_LATEST["sha"]):
            self.assertEqual(updater.check_for_update(self.db)["status"], "up_to_date")

    def test_unknown_zip_revision_never_silently_baselines(self):
        with patch.object(updater, "local_git_sha", return_value=""):
            result = updater.check_for_update(self.db)
        self.assertEqual(result["status"], "update_available")
        self.assertTrue(result["unverified_install"])
        self.assertFalse(self.db.get_setting(updater.K_APPLIED_SHA, ""))

    def test_new_sha_is_update_available(self):
        updater.check_for_update(self.db)
        global FAKE_LATEST_COMMIT
        old = FAKE_LATEST_COMMIT
        FAKE_LATEST_COMMIT = {
            "sha": "newsha9999",
            "commit": {"committer": {"date": "2026-11-22T00:00:00Z"},
                       "message": "newer\n"},
        }
        updater._http_json = lambda url, timeout=20: FAKE_LATEST_COMMIT
        try:
            result = updater.check_for_update(self.db)
            self.assertEqual(result["status"], "update_available")
            self.assertEqual(result["latest"]["sha"], "newsha9999")
        finally:
            FAKE_LATEST_COMMIT = old
            updater._http_json = lambda url, timeout=20: old

    def test_network_error_never_raises(self):
        updater._http_json = lambda url, timeout=20: (_ for _ in ()).throw(
            updater.UpdateError("تعذر الاتصال بـ GitHub: no net"))
        result = updater.check_for_update(self.db)
        self.assertEqual(result["status"], "error")
        self.assertIn("GitHub", result["error"])
        self.assertEqual(self.db.get_setting(updater.K_LAST_ERROR),
                         result["error"])


class TestApplyUpdate(UpdaterTestBase):
    def test_apply_replaces_adds_and_preserves(self):
        # ملفات محلية يجب أن تبقى
        self.write_local("pharmacy.db", "SQLITE-DATA")
        self.write_local("supabase_config.json", '{"url": "real", "key": "real"}')
        self.write_local("certs/cert.pem", "CERT")
        self.write_local("backups/pharmacy_old.db", "BACKUP")
        self.write_local("receipts/r1.txt", "RECEIPT")
        self.write_local("startup.log", "LOG")
        self.write_local("invoice_counter.txt", "42")
        # ملف كود قديم سيُستبدل + ملف سيُحذف من الكود الجديد (لا يُحذف محلياً)
        self.write_local("main.py", "OLD CODE")
        self.write_local("old_removed.py", "REMOVED UPSTREAM")

        self.zip_bytes = make_zip({
            "main.py": "NEW CODE",
            "new_feature.py": "BRAND NEW",
            "pharmacy.db": "MALICIOUS-OVERWRITE-ATTEMPT",
            "supabase_config.json": '{"url": "evil"}',
        }, sha=FAKE_LATEST["sha"])
        updater.check_for_update(self.db)  # baseline
        updated, rollback = updater.apply_update(self.db, self.base,
                                                 FAKE_LATEST["sha"])
        self.assertGreaterEqual(updated, 2)
        self.assertEqual(self.read_local("main.py"), "NEW CODE")
        self.assertEqual(self.read_local("new_feature.py"), "BRAND NEW")
        # المحمية لم تُمس
        self.assertEqual(self.read_local("pharmacy.db"), "SQLITE-DATA")
        self.assertEqual(self.read_local("supabase_config.json"),
                         '{"url": "real", "key": "real"}')
        self.assertEqual(self.read_local("certs/cert.pem"), "CERT")
        self.assertEqual(self.read_local("backups/pharmacy_old.db"), "BACKUP")
        self.assertEqual(self.read_local("receipts/r1.txt"), "RECEIPT")
        self.assertEqual(self.read_local("startup.log"), "LOG")
        self.assertEqual(self.read_local("invoice_counter.txt"), "42")
        # المحدّث لا يحذف ملفات
        self.assertEqual(self.read_local("old_removed.py"), "REMOVED UPSTREAM")
        # نسخة الرجوع تحوي الكود القديم
        self.assertTrue(rollback and os.path.isdir(rollback))
        with open(os.path.join(rollback, "main.py"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "OLD CODE")
        # الإصدار المثبّت سُجّل
        self.assertEqual(self.db.get_setting(updater.K_APPLIED_SHA),
                         FAKE_LATEST["sha"])

    def test_bad_zip_fails_loudly(self):
        self.zip_bytes = b"this is not a zip"
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.apply_update(self.db, self.base, FAKE_LATEST["sha"])
        self.assertIn("تالف", str(ctx.exception))

    def test_zip_without_main_py_rejected(self):
        self.zip_bytes = make_zip({"random.txt": "x"}, sha=FAKE_LATEST["sha"])
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.apply_update(self.db, self.base, FAKE_LATEST["sha"])
        self.assertIn("أُلغي", str(ctx.exception))

    def test_failed_copy_rolls_back(self):
        self.write_local("main.py", "OLD CODE")
        if os.name == "nt":
            self.skipTest("read-only file semantics differ on Windows CI")
        os.chmod(os.path.join(self.base, "main.py"), 0o444)
        self.zip_bytes = make_zip({"main.py": "NEW CODE"}, sha=FAKE_LATEST["sha"])
        try:
            with self.assertRaises(updater.UpdateError) as ctx:
                updater.apply_update(self.db, self.base, FAKE_LATEST["sha"])
            self.assertIn("استُرجعت", str(ctx.exception))
        finally:
            os.chmod(os.path.join(self.base, "main.py"), 0o644)
        # الملف الأصلي كما هو
        self.assertEqual(self.read_local("main.py"), "OLD CODE")


@unittest.skipUnless(os.environ.get("RUN_LIVE_UPDATE_TEST") == "1",
                     "live GitHub test: set RUN_LIVE_UPDATE_TEST=1")
class TestLiveUpdate(UpdaterTestBase):
    """يثبّت آخر commit حقيقي من GitHub في مجلد مؤقت ويفحص الحفاظ على البيانات."""

    def test_apply_real_main(self):
        updater._http_json, updater._http_bytes = self._real_json, self._real_bytes
        latest = updater.latest_commit()
        self.assertTrue(latest["sha"])
        # ملفات محلية وهمية يجب أن تنجو
        self.write_local("pharmacy.db", "SQLITE-DATA")
        self.write_local("supabase_config.json", '{"url": "real"}')
        updated, _ = updater.apply_update(self.db, self.base, latest["sha"])
        self.assertGreater(updated, 10)
        self.assertTrue(os.path.exists(os.path.join(self.base, "main.py")))
        self.assertEqual(self.read_local("pharmacy.db"), "SQLITE-DATA")
        self.assertEqual(self.read_local("supabase_config.json"), '{"url": "real"}')


if __name__ == "__main__":
    unittest.main(verbosity=2)
