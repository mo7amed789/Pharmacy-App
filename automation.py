# -*- coding: utf-8 -*-
"""مهام مجدولة داخل البرنامج (v6.13) — مكتبة قياسية فقط.

خيط خلفي واحد يوقظ كل 15 دقيقة وينفّذ عند الاستحقاق:
- مزامنة الكتالوج من السحابة كل 24 ساعة (تحديث الأسعار بصمت، بلا أي
  نوافذ أو إزعاج؛ النتيجة أو الخطأ يتسجلا ويظهران في الإعدادات).
- نسخة احتياطية تلقائية من قاعدة البيانات كل 24 ساعة (نفس دالة النسخ
  اليدوي: نسخة سليمة مُتحقق منها، والاحتفاظ بأحدث 10 نسخ فقط).

كل مهمة تعمل باتصال SQLite خاص (الاتصالات لا تُشارك بين الخيوط) وأي فشل
يُسجَّل في settings وفي سجل التدقيق ولا يوقف البرنامج أبداً. عند فشل
المزامنة تُعاد المحاولة بعد ساعة بدل انتظار 24 ساعة كاملة.
"""

import threading
from datetime import datetime

TICK_SECONDS = 15 * 60
STARTUP_DELAY_SECONDS = 60
SYNC_INTERVAL_HOURS = 24
BACKUP_INTERVAL_HOURS = 24
SYNC_RETRY_HOURS = 1

K_SYNC_ENABLED = "autosync_enabled"        # "1" افتراضياً، "0" تعطيل
K_BACKUP_ENABLED = "autobackup_enabled"
K_SYNC_LAST = "autosync_last"
K_SYNC_ATTEMPT = "autosync_last_attempt"
K_SYNC_RESULT = "autosync_last_result"
K_SYNC_ERROR = "autosync_last_error"
K_BACKUP_LAST = "autobackup_last"
K_BACKUP_ERROR = "autobackup_last_error"


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hours_since(ts):
    try:
        return (datetime.now() - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                ).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return 1e9  # لا قيمة مسجلة = مستحق فوراً


def sync_due(db):
    attempt = db.get_setting(K_SYNC_ATTEMPT, "")
    if db.get_setting(K_SYNC_ERROR, ""):
        # آخر محاولة فشلت: أعد المحاولة بعد ساعة فقط
        return _hours_since(attempt) >= SYNC_RETRY_HOURS
    return _hours_since(db.get_setting(K_SYNC_LAST, "")) >= SYNC_INTERVAL_HOURS


def backup_due(db):
    return _hours_since(db.get_setting(K_BACKUP_LAST, "")) >= BACKUP_INTERVAL_HOURS


def run_sync_now(db):
    """مزامنة واحدة (تُستدعى من الخيط الخلفي أو من الاختبارات)."""
    import cloud_sync
    db.set_setting(K_SYNC_ATTEMPT, _now_str())
    added, updated, skipped = cloud_sync.pull_catalog(db, "auto")
    db.set_setting(K_SYNC_LAST, _now_str())
    db.set_setting(K_SYNC_RESULT,
                   "جديد %d، محدّث %d، متجاهَل %d" % (added, updated, skipped))
    db.set_setting(K_SYNC_ERROR, "")
    return added, updated, skipped


def run_backup_now(db):
    """نسخة احتياطية واحدة (تُستدعى من الخيط الخلفي أو من الاختبارات)."""
    dest = db.backup(suffix="_auto")
    db.set_setting(K_BACKUP_LAST, _now_str())
    db.set_setting(K_BACKUP_ERROR, "")
    db.audit("", "auto_backup", dest)
    return dest


def tick(db_path):
    """دورة واحدة: نفّذ ما استحق. تُعيد قائمة بما حدث (للاختبارات)."""
    import supabase_client
    from database import DB
    done = []
    db = DB(path=db_path, init=False)
    try:
        if db.get_setting(K_BACKUP_ENABLED, "1") != "0" and backup_due(db):
            try:
                run_backup_now(db)
                done.append("backup")
            except Exception as e:
                db.set_setting(K_BACKUP_ERROR, str(e))
                db.audit("", "auto_backup_failed", str(e)[:300])
                db.syslog("error", "automation", "auto_backup_failed", str(e)[:300])
        if (db.get_setting(K_SYNC_ENABLED, "1") != "0"
                and supabase_client.is_configured() and sync_due(db)):
            try:
                run_sync_now(db)
                done.append("sync")
            except Exception as e:
                db.set_setting(K_SYNC_ERROR, str(e))
                db.audit("", "auto_sync_failed", str(e)[:300])
                import cloud_sync
                cloud_sync.log_sync_error(db, "auto_sync_failed", str(e)[:300])
    finally:
        db.close()
    return done


class Automation(threading.Thread):
    """خيط خلفي واحد: ينتظر دقيقة بعد التشغيل ثم يوقظ كل 15 دقيقة."""

    def __init__(self, db_path):
        super().__init__(daemon=True, name="pharmacy-automation")
        self.db_path = db_path
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        if self._stop_event.wait(STARTUP_DELAY_SECONDS):
            return
        while not self._stop_event.is_set():
            try:
                tick(self.db_path)
            except Exception:
                pass  # لا مهمة مجدولة توقف البرنامج أبداً
            if self._stop_event.wait(TICK_SECONDS):
                break


def status_text(db):
    """حالة الأتمتة كما تظهر في شاشة الإعدادات."""
    import supabase_client
    lines = []
    if db.get_setting(K_SYNC_ENABLED, "1") == "0":
        lines.append("المزامنة التلقائية: معطّلة")
    elif not supabase_client.is_configured():
        lines.append("المزامنة التلقائية: بانتظار إعداد Supabase")
    else:
        last = db.get_setting(K_SYNC_LAST, "")
        res = db.get_setting(K_SYNC_RESULT, "")
        if last:
            lines.append("آخر مزامنة تلقائية: %s%s" % (
                last, (" — " + res) if res else ""))
            due_in = SYNC_INTERVAL_HOURS - _hours_since(last)
            if due_in > 0:
                lines.append("المزامنة القادمة بعد حوالي %d ساعة" % max(1, int(due_in)))
        else:
            lines.append("المزامنة التلقائية: ستعمل عند أول استحقاق")
        err = db.get_setting(K_SYNC_ERROR, "")
        if err:
            lines.append("آخر خطأ مزامنة: " + err)
    if db.get_setting(K_BACKUP_ENABLED, "1") == "0":
        lines.append("النسخ الاحتياطي التلقائي: معطّل")
    else:
        last_b = db.get_setting(K_BACKUP_LAST, "")
        lines.append("آخر نسخة تلقائية: " + (last_b or "ستؤخذ عند أول استحقاق")
                     + " (يُحتفظ بأحدث 10 نسخ)")
        err_b = db.get_setting(K_BACKUP_ERROR, "")
        if err_b:
            lines.append("آخر خطأ نسخ: " + err_b)
    return "\n".join(lines)
