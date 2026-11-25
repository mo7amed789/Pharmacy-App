# -*- coding: utf-8 -*-
"""Owner remote monitoring (OFF by default). Standard library only.

The pharmacy keeps working fully offline. When the owner turns this on, new
rows of the owner activity log and the system log are copied (forward only,
never old history) to the OWNER's own Supabase project, into one table that
only a dedicated device account can write and only the owner account can read
(see docs/supabase_owner_monitor.sql). Nothing is sent unless ALL of these hold:
  1. remote_monitor.json exists next to the program (url, anon_key, email, password),
  2. the owner turned it on in Settings after seeing the destination and a sample,
  3. the rows were created after it was turned on.
The catalog key in supabase_config.json is never used here, and the device
password is never written to any log or sent anywhere except the sign-in call.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

K_ENABLED = "remote_monitor_enabled"
K_LEVEL = "remote_monitor_level"
K_AUDIT_CUR = "rm_audit_cursor"
K_SYS_CUR = "rm_sys_cursor"
K_LAST_OK = "rm_last_ok"
K_LAST_ERR = "rm_last_error"
K_DEVICE = "rm_device_id"
TABLE = "monitor_events"
BATCH = 200

LEVELS = ("summary", "full")


class MonitorError(Exception):
    pass


def config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "remote_monitor.json")


def load_config(path=None):
    """(cfg dict) or None. Needs url, anon_key, email, password."""
    try:
        with open(path or config_path(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    url = (d.get("url") or "").strip().rstrip("/")
    if "://" not in url and url:
        url = "https://" + url
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("https", "http") or not p.netloc:
        return None
    if not all((d.get("anon_key"), d.get("email"), d.get("password"))):
        return None
    return {"url": url, "anon_key": d["anon_key"].strip(), "email": d["email"].strip(),
            "password": d["password"], "host": p.netloc}


def destination(cfg):
    return "%s (table %s)" % (cfg["host"], TABLE) if cfg else ""


def is_enabled(db):
    return db.get_setting(K_ENABLED, "0") == "1"


def level(db):
    v = db.get_setting(K_LEVEL, "summary")
    return v if v in LEVELS else "summary"


def device_id(db):
    d = db.get_setting(K_DEVICE, "")
    if not d:
        import uuid
        d = "pc-" + uuid.uuid4().hex[:12]
        db.conn.execute("INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (K_DEVICE, d))
        db.conn.commit()
    return d


def _raw_set(db, key, value):
    db.conn.execute("INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value)))
    db.conn.commit()


def _max_ids(db):
    a = db.conn.execute("SELECT COALESCE(MAX(id),0) FROM audit_log").fetchone()[0]
    s = db.conn.execute("SELECT COALESCE(MAX(id),0) FROM system_log").fetchone()[0]
    return a, s


def enable(db, lvl="summary"):
    """Turn on, forward only: nothing logged before this moment is ever sent."""
    if lvl not in LEVELS:
        raise ValueError("level")
    a, s = _max_ids(db)
    _raw_set(db, K_AUDIT_CUR, a)
    _raw_set(db, K_SYS_CUR, s)
    _raw_set(db, K_LEVEL, lvl)
    _raw_set(db, K_LAST_ERR, "")
    _raw_set(db, K_ENABLED, "1")
    db.audit(db.actor or "", "remote_monitor_on", "level=" + lvl, entity="setting", entity_id=K_ENABLED)


def disable(db):
    _raw_set(db, K_ENABLED, "0")
    db.audit(db.actor or "", "remote_monitor_off", "", entity="setting", entity_id=K_ENABLED)


# ---------- what leaves the device ----------
def _redact(text, limit):
    from database import redact_text
    return redact_text(text, limit)


def audit_payload(r, lvl):
    p = {"time": r["created_at"], "user": r["user"], "role": r["role"] or "", "action": r["action"],
         "source": r["source"] or "", "branch": r["branch_name"] or "", "shift_id": r["shift_id"],
         "entity": r["entity"] or "", "entity_id": r["entity_id"] or ""}
    if lvl == "full":
        p["details"] = _redact(r["details"], 500)
        p["before"] = _redact(r["before_json"], 1500)
        p["after"] = _redact(r["after_json"], 1500)
    return p


def system_payload(r, lvl):
    p = {"time": r["created_at"], "level": r["level"], "component": r["component"],
         "event": r["event"], "message": _redact(r["message"], 200), "app_version": r["app_version"] or ""}
    if lvl == "full":
        p["detail"] = _redact(r["detail"], 3000)
    return p


def _pending(db, limit=BATCH):
    ac = int(db.get_setting(K_AUDIT_CUR, "0") or 0)
    sc = int(db.get_setting(K_SYS_CUR, "0") or 0)
    arows = db.conn.execute(
        "SELECT a.*, b.name AS branch_name FROM audit_log a LEFT JOIN branches b ON b.id=a.branch_id "
        "WHERE a.id>? ORDER BY a.id LIMIT ?", (ac, limit)).fetchall()
    srows = db.conn.execute("SELECT * FROM system_log WHERE id>? ORDER BY id LIMIT ?", (sc, limit)).fetchall()
    return arows, srows


def build_events(db, lvl=None, limit=BATCH):
    """Exactly the rows that would be uploaded next: (events, audit_max, sys_max)."""
    lvl = lvl or level(db)
    dev = device_id(db)
    arows, srows = _pending(db, limit)
    ev = []
    for r in arows:
        ev.append({"device_id": dev, "kind": "activity", "src_id": r["id"], "payload": audit_payload(r, lvl)})
    for r in srows:
        ev.append({"device_id": dev, "kind": "system", "src_id": r["id"], "payload": system_payload(r, lvl)})
    return ev, (arows[-1]["id"] if arows else None), (srows[-1]["id"] if srows else None)


def heartbeat(db, version=""):
    a, s = _max_ids(db)
    n = db.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    ac = int(db.get_setting(K_AUDIT_CUR, "0") or 0)
    return {"device_id": device_id(db), "kind": "heartbeat", "src_id": int(time.time()),
            "payload": {"time": datetime.now().isoformat(timespec="seconds"), "app_version": version or db.app_version or "",
                        "audit_max_id": a, "audit_count": n, "system_max_id": s, "unsent_activity": max(0, a - ac),
                        "level": level(db)}}


def preview(db, lvl=None):
    """What the owner is shown BEFORE enabling: destination, level, sample rows. Sends nothing."""
    cfg = load_config()
    lvl = lvl if lvl in LEVELS else level(db)
    # sample = latest rows as they would look (the real cursor is not touched)
    dev = device_id(db)
    arows = db.conn.execute("SELECT a.*, b.name AS branch_name FROM audit_log a LEFT JOIN branches b ON b.id=a.branch_id "
                            "ORDER BY a.id DESC LIMIT 3").fetchall()
    srows = db.conn.execute("SELECT * FROM system_log ORDER BY id DESC LIMIT 2").fetchall()
    sample = [{"kind": "activity", "payload": audit_payload(r, lvl)} for r in arows] + \
             [{"kind": "system", "payload": system_payload(r, lvl)} for r in srows]
    return {"configured": cfg is not None, "destination": destination(cfg), "level": lvl, "device_id": dev,
            "sample": sample, "history_sent": False}


# ---------- network ----------
class Client:
    def __init__(self, cfg, timeout=20):
        self.cfg, self.timeout, self.token = cfg, timeout, None

    def _req(self, method, path, body=None, headers=None):
        h = {"apikey": self.cfg["anon_key"], "Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request(self.cfg["url"] + path, method=method, headers=h,
                                     data=json.dumps(body).encode("utf-8") if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise MonitorError("HTTP %s" % e.code)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise MonitorError("network: %s" % type(e).__name__)

    def login(self):
        d = self._req("POST", "/auth/v1/token?grant_type=password",
                      {"email": self.cfg["email"], "password": self.cfg["password"]})
        self.token = (d or {}).get("access_token")
        if not self.token:
            raise MonitorError("sign-in failed")

    def insert(self, events):
        if not self.token:
            self.login()
        try:
            self._req("POST", "/rest/v1/%s?on_conflict=device_id,kind,src_id" % TABLE, events,
                      {"Authorization": "Bearer " + self.token,
                       "Prefer": "resolution=ignore-duplicates,return=minimal"})
        except MonitorError as e:
            if "HTTP 401" in str(e):
                self.token = None
                self.login()
                self._req("POST", "/rest/v1/%s?on_conflict=device_id,kind,src_id" % TABLE, events,
                          {"Authorization": "Bearer " + self.token,
                           "Prefer": "resolution=ignore-duplicates,return=minimal"})
            else:
                raise


def sync_once(db, client=None, version="", heartbeat_due=True):
    """One upload round. Returns number of rows sent, or None when off / not configured.
    Never raises: a failure keeps the cursor, is logged once per 30 min, and is retried later."""
    try:
        if not is_enabled(db):
            return None
        cfg = load_config()
        if cfg is None:
            return None
        client = client or Client(cfg)
        sent = 0
        while True:
            ev, amax, smax = build_events(db)
            if not ev:
                break
            client.insert(ev)
            if amax is not None:
                _raw_set(db, K_AUDIT_CUR, amax)
            if smax is not None:
                _raw_set(db, K_SYS_CUR, smax)
            sent += len(ev)
            if len(ev) < BATCH:
                break
        if heartbeat_due:
            client.insert([heartbeat(db, version)])
        _raw_set(db, K_LAST_OK, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        _raw_set(db, K_LAST_ERR, "")
        return sent
    except Exception as e:
        msg = str(e)[:200]
        try:
            _raw_set(db, K_LAST_ERR, msg)
            import cloud_sync
            cloud_sync.log_sync_error(db, "remote_monitor_failed", msg)
        except Exception:
            pass
        return None


def status_text(db):
    cfg = load_config()
    if cfg is None:
        return "المتابعة عن بعد غير مُعدّة (لا يوجد ملف remote_monitor.json). البرنامج يعمل محلياً كالمعتاد."
    if not is_enabled(db):
        return "المتابعة عن بعد متوقفة. الوجهة عند التفعيل: %s" % destination(cfg)
    a, s = _max_ids(db)
    pend = max(0, a - int(db.get_setting(K_AUDIT_CUR, "0") or 0)) + max(0, s - int(db.get_setting(K_SYS_CUR, "0") or 0))
    t = "المتابعة عن بعد مفعّلة (%s) إلى %s. آخر إرسال ناجح: %s. بانتظار الإرسال: %d" % (
        level(db), destination(cfg), db.get_setting(K_LAST_OK, "-") or "-", pend)
    err = db.get_setting(K_LAST_ERR, "")
    return t + ("\nآخر خطأ: " + err if err else "")


class Monitor(threading.Thread):
    """Background loop: every `interval` seconds; offline simply waits and retries."""

    def __init__(self, db_path, interval=60, version=""):
        super().__init__(daemon=True, name="pharmacy-remote-monitor")
        self.db_path, self.interval, self.version = db_path, interval, version
        self._stop = threading.Event()
        self._last_hb = 0

    def stop(self):
        self._stop.set()

    def run(self):
        from database import DB
        while not self._stop.wait(self.interval):
            try:
                db = DB(path=self.db_path, init=False)
                try:
                    if is_enabled(db):
                        hb = time.time() - self._last_hb > 300
                        r = sync_once(db, version=self.version, heartbeat_due=hb)
                        if r is not None and hb:
                            self._last_hb = time.time()
                finally:
                    db.close()
            except Exception:
                pass
