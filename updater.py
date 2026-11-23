# -*- coding: utf-8 -*-
"""تحديث تلقائي للبرنامج من GitHub — مكتبة قياسية فقط (v6.12).

الفكرة: أي كود جديد يترفع على فرع main في GitHub يقدر البرنامج ينزّله
ويثبّته بنفسه، من غير ما تلمس ملفاته المحلية (قاعدة البيانات، الإعدادات،
النسخ الاحتياطية، الشهادات).

الآلية:
- check_for_update: يقارن آخر commit على main بمراجعة Git المحلية أو
  آخر تثبيت مثبت. لا يفترض أن كود الإنترنت مثبت في أول تشغيل.
- فحص خلفي عند التشغيل وكل ساعة، وتنبيه بخياري التثبيت أو التأجيل 24 ساعة.
- apply_update: ينزّل zip للـ commit، يفك ضغطه في مجلد مؤقت، ينسخ الملفات
  فوق مجلد البرنامج مع نسخة رجوع لكل ملف مستبدل في backups/code_update_*.
  الملفات والمجلدات المحلية في PRESERVE_* لا تُلمس أبداً، والمحدّث لا
  يحذف أي ملف — التحديث إضافي فقط.
- أي فشل (نت، zip تالف، ملف مقفل) يظهر برسالة عربية واضحة بدل ترك نسخة
  نصف محدثة: النسخ يتم ملفاً ملفاً، ولو فشل ملف تُسترجع النسخ الاحتياطية.
"""

import io
import math
import json
import os
import shutil
import subprocess
import time
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime

REPO_OWNER = "mo7amed789"
REPO_NAME = "Pharmacy-App"
BRANCH = "main"

K_APPLIED_SHA = "update_applied_sha"
K_APPLIED_AT = "update_applied_at"
K_LAST_CHECK = "update_last_check"
K_LAST_ERROR = "update_last_error"
K_SNOOZE_SHA = "update_snooze_sha"
K_SNOOZE_UNTIL = "update_snooze_until"
CHECK_INTERVAL_MS = 60 * 60 * 1000
SNOOZE_SECONDS = 24 * 60 * 60


def local_git_sha(base_dir=None):
    """Identify an actual checkout, never pretend a remote SHA is installed."""
    base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(os.path.join(base_dir, ".git")):
        return ""
    try:
        out = subprocess.run(["git", "-C", base_dir, "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and len(sha) == 40 and all(c in "0123456789abcdef" for c in sha) else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def snooze_update(db, sha, now=None):
    until = (time.time() if now is None else now) + SNOOZE_SECONDS
    db.set_setting(K_SNOOZE_SHA, sha)
    db.set_setting(K_SNOOZE_UNTIL, str(until))


def notification_due(db, result, now=None):
    if not result or result.get("status") != "update_available":
        return False
    sha = result.get("latest", {}).get("sha")
    if not sha:
        return False
    if db.get_setting(K_SNOOZE_SHA, "") != sha:
        return True
    try:
        until = float(db.get_setting(K_SNOOZE_UNTIL, "0"))
    except (TypeError, ValueError):
        return True
    return not math.isfinite(until) or (time.time() if now is None else now) >= until


# لا تُستبدل ولا تُحذف أبداً أثناء التحديث — بيانات المستخدم وإعداداته
PRESERVE_FILES = {
    "pharmacy.db", "pharmacy.db-wal", "pharmacy.db-shm",
    "supabase_config.json", "invoice_counter.txt", "DEFAULT_LOGINS.txt",
    "key.pem", "cert.pem", "startup.log", "mobile_requests.log",
    "error.log", "applied_update.json",
}
PRESERVE_DIRS = {"backups", "certs", "receipts", ".git", "__pycache__"}
PRESERVE_PREFIXES = ("pharmacy_",)   # ملفات النسخ الاحتياطية بجانب القاعدة
PRESERVE_SUFFIXES = (".db", ".db-wal", ".db-shm", ".log", ".pem", ".bak",
                     ".availability.sqlite3", ".availability.sqlite3-wal",
                     ".availability.sqlite3-shm", ".availability.sqlite3.lock")

MAX_CODE_BACKUPS = 3

UA = "Pharmacy-App-Updater/1.0 (+https://github.com/%s/%s)" % (REPO_OWNER, REPO_NAME)


class UpdateError(Exception):
    """فشل واضح في فحص أو تثبيت التحديث."""


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise UpdateError("GitHub رد بخطأ HTTP %d" % e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError("تعذر الاتصال بـ GitHub: %s" % e)


def _http_bytes(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise UpdateError("فشل تنزيل التحديث: HTTP %d" % e.code)
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError("فشل تنزيل التحديث: %s" % e)


def latest_commit():
    """آخر commit على فرع main: {sha, date, message}."""
    data = _http_json("https://api.github.com/repos/%s/%s/commits/%s"
                      % (REPO_OWNER, REPO_NAME, BRANCH))
    try:
        return {
            "sha": data["sha"],
            "date": data["commit"]["committer"]["date"],
            "message": (data["commit"]["message"] or "").splitlines()[0],
        }
    except (KeyError, IndexError, TypeError):
        raise UpdateError("رد غير متوقع من GitHub API")


def installed_info(db):
    """معلومات آخر تحديث مثبّت كما تُعرض في الإعدادات."""
    sha = db.get_setting(K_APPLIED_SHA, "")
    at = db.get_setting(K_APPLIED_AT, "")
    return {"sha": sha, "at": at}


def check_for_update(db):
    """يفحص وجود تحديث. يرجع dict بمفتاح status:
    update_available / up_to_date / error — ولا يرفع استثناءً أبداً."""
    try:
        latest = latest_commit()
    except UpdateError as e:
        _set(db, K_LAST_ERROR, str(e))
        return {"status": "error", "error": str(e)}
    _set(db, K_LAST_CHECK, _now_str())
    _set(db, K_LAST_ERROR, "")
    applied = db.get_setting(K_APPLIED_SHA, "")
    local = local_git_sha()
    if local == latest["sha"]:
        return {"status": "up_to_date", "latest": latest}
    if not applied:
        if local:
            _set(db, K_APPLIED_SHA, local)
            applied = local
        else:
            # A ZIP install has no trusted revision stamp on first run.
            # Offer an explicit user-approved sync, never silently mark
            # the remote as installed or claim this is a newer version.
            return {"status": "update_available", "latest": latest,
                    "applied": "", "unverified_install": True}
    if applied == latest["sha"]:
        return {"status": "up_to_date", "latest": latest}
    return {"status": "update_available", "latest": latest, "applied": applied}


def _preserved(rel):
    """هل المسار النسبي (بفواصل /) محمي من الاستبدال؟"""
    parts = rel.replace("\\", "/").split("/")
    name = parts[-1]
    if any(p in PRESERVE_DIRS for p in parts[:-1]):
        return True
    if name in PRESERVE_FILES or name == "__init__.pyc":
        return True
    if name.startswith(PRESERVE_PREFIXES) and name.endswith((".db", ".db-wal", ".db-shm")):
        return True
    if name.endswith(PRESERVE_SUFFIXES):
        return True
    return False


def apply_update(db, base_dir, sha, progress=None):
    """ينزّل commit بعينه ويثبّته فوق مجلد البرنامج.

    يرجع (عدد الملفات المحدّثة, مجلد نسخة الرجوع). يرفع UpdateError
    برسالة عربية واضحة عند أي فشل، مع استرجاع الملفات المستبدلة."""
    blob = _http_bytes("https://codeload.github.com/%s/%s/zip/%s"
                       % (REPO_OWNER, REPO_NAME, sha))
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise UpdateError("الملف المنزّل تالف — حاول مرة أخرى")
    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not any(n.endswith("/main.py") for n in names):
        raise UpdateError("التحديث المنزّل لا يشبه مجلد البرنامج — أُلغي الأمر")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rollback_dir = os.path.join(base_dir, "backups", "code_update_" + stamp)
    staging = tempfile.mkdtemp(prefix="pharmacy_update_")
    replaced = []
    try:
        zf.extractall(staging)
        roots = [d for d in os.listdir(staging) if d.startswith(REPO_NAME + "-")]
        if len(roots) != 1:
            raise UpdateError("بنية التحديث المنزّل غير متوقعة — أُلغي الأمر")
        root = os.path.join(staging, roots[0])

        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in PRESERVE_DIRS]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                if _preserved(rel):
                    continue
                files.append((full, rel))

        # نسخة رجوع لكل ملف موجود سيُستبدل، ثم الاستبدال ملفاً ملفاً
        for full, rel in files:
            dest = os.path.join(base_dir, *rel.split("/"))
            if os.path.exists(dest):
                bak = os.path.join(rollback_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(bak), exist_ok=True)
                shutil.copy2(dest, bak)
                replaced.append(rel)
        updated = 0
        for full, rel in files:
            dest = os.path.join(base_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(dest) or base_dir, exist_ok=True)
            try:
                shutil.copy2(full, dest)
            except OSError as e:
                _rollback(base_dir, rollback_dir, replaced)
                raise UpdateError("تعذر استبدال %s (%s) — استُرجعت النسخة القديمة "
                                  "كاملة. أغلق البرنامج وحاول مجدداً" % (rel, e))
            updated += 1
            if progress:
                progress(updated, len(files))
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    _prune_code_backups(base_dir)
    _set(db, K_APPLIED_SHA, sha)
    _set(db, K_APPLIED_AT, _now_str())
    _set(db, K_LAST_ERROR, "")
    db.audit("", "app_update", "applied %s (%d files)" % (sha[:8], len(files)))
    return updated, (rollback_dir if replaced else None)


def _rollback(base_dir, rollback_dir, replaced):
    """استرجاع كل الملفات المستبدلة عند فشل منتصف التحديث."""
    for rel in replaced:
        bak = os.path.join(rollback_dir, *rel.split("/"))
        dest = os.path.join(base_dir, *rel.split("/"))
        try:
            shutil.copy2(bak, dest)
        except OSError:
            pass


def _prune_code_backups(base_dir):
    folder = os.path.join(base_dir, "backups")
    try:
        olds = sorted(
            (os.path.join(folder, d) for d in os.listdir(folder)
             if d.startswith("code_update_")),
            key=os.path.getmtime, reverse=True)
        for old in olds[MAX_CODE_BACKUPS:]:
            shutil.rmtree(old, ignore_errors=True)
    except OSError:
        pass


def status_text(db):
    """سطر الحالة المعروض في شاشة الإعدادات."""
    info = installed_info(db)
    parts = []
    if info["sha"]:
        parts.append("الإصدار المثبّت: %s%s" % (
            info["sha"][:8], (" — " + info["at"]) if info["at"] else ""))
    else:
        parts.append("نسخة التثبيت غير مسجلة؛ لن يُفترض أن آخر كود على الإنترنت مثبت محلياً.")
    last = db.get_setting(K_LAST_CHECK, "")
    if last:
        parts.append("آخر فحص: " + last)
    err = db.get_setting(K_LAST_ERROR, "")
    if err:
        parts.append("آخر خطأ: " + err)
    return "\n".join(parts)


def _set(db, key, value):
    try:
        db.set_setting(key, value)
    except Exception:
        pass
