# -*- coding: utf-8 -*-
"""Owner email reports for remote monitoring (OFF until the owner enables monitoring). Standard library only.

One combined summary (employee activity + errors/warnings) every 6 hours, sent by the PC itself over TLS-verified SMTP.
- TLS is REQUIRED: implicit TLS (port 465) or STARTTLS (587) with certificate and hostname
  verification (ssl.create_default_context). There is no plaintext fallback.
- The SMTP password / API key is NOT stored in remote_monitor.json. It is kept encrypted with
  Windows DPAPI (current Windows user only) in <db>.rmsecret, or refused on other systems.
- Summary level only: no prices, customers or before/after values, whatever the level setting.
- Uses its own cursors (em_*) in the same sidecar file, forward only, so a restore cannot replay old rows.
"""
import base64
import json
import os
import smtplib
import urllib.error
import urllib.parse
import urllib.request
import ssl
import time
from datetime import datetime
from email.message import EmailMessage

import remote_monitor as RM

REPORT_GAP = 6 * 3600   # one combined activity + error report every 6 hours
MODES = ("ssl", "starttls", "api")


class EmailError(Exception):
    pass


# ---------- secret storage (Windows DPAPI via ctypes, current user only) ----------
def _secret_path(db):
    return str(db.path) + ".rmsecret"


def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    inb = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise EmailError("could not %s the secret" % ("protect" if protect else "unprotect"))
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


_PROTECT = lambda b: _dpapi(b, True)      # replaced in tests; on non-Windows there is no safe default
_UNPROTECT = lambda b: _dpapi(b, False)


def store_secret(db, secret):
    if os.name != "nt" and _PROTECT.__name__ == "<lambda>" and not getattr(_PROTECT, "testing", False):
        raise EmailError("secure secret storage needs Windows")
    blob = _PROTECT(secret.encode("utf-8"))
    tmp = _secret_path(db) + ".tmp"
    with open(tmp, "w", encoding="ascii") as f:
        f.write(base64.b64encode(blob).decode("ascii"))
    os.replace(tmp, _secret_path(db))


def load_secret(db):
    try:
        with open(_secret_path(db), encoding="ascii") as f:
            return _UNPROTECT(base64.b64decode(f.read().strip())).decode("utf-8")
    except (OSError, ValueError, EmailError):
        return None


# ---------- config (no secret in it) ----------
def load_email_cfg(path=None):
    try:
        with open(path or RM.config_path(), encoding="utf-8") as f:
            d = (json.load(f) or {}).get("mail_report") or {}
    except (OSError, ValueError):
        return None
    if d.get("mode") == "api":
        u = str(d.get("url") or "")
        if not (u.startswith("https://") and d.get("sender") and d.get("to")):
            return None      # HTTPS only; a plain http URL is refused
        return {"mode": "api", "url": u, "host": urllib.parse.urlparse(u).hostname or "", "port": 443,
                "username": "", "sender": d["sender"], "to": d["to"]}
    need = ("host", "port", "username", "sender", "to")
    if not all(d.get(k) for k in need) or d.get("mode", "ssl") not in MODES:
        return None
    return {"host": d["host"], "port": int(d["port"]), "mode": d.get("mode", "ssl"), "username": d["username"],
            "sender": d["sender"], "to": d["to"]}


def destination(cfg):
    if cfg and cfg["mode"] == "api":
        return "email to %s via HTTPS API %s (certificate checked)" % (cfg["to"], cfg["host"])
    return "email to %s via %s:%s (%s, certificate checked)" % (cfg["to"], cfg["host"], cfg["port"], cfg["mode"]) if cfg else ""


# ---------- sending ----------
def send_mail(cfg, password, subject, body, context=None):
    context = context or ssl.create_default_context()
    if cfg["mode"] == "api":     # Resend-style JSON API: POST {from,to,subject,text} with Bearer key
        req = urllib.request.Request(cfg["url"], data=json.dumps({"from": cfg["sender"], "to": [cfg["to"]], "subject": subject,
                                     "text": body}).encode("utf-8"), method="POST",
                                     headers={"Authorization": "Bearer " + password, "Content-Type": "application/json",
                                              "User-Agent": "pharmacy-app-report/1"})
        try:
            with urllib.request.urlopen(req, timeout=30, context=context) as r:
                if not 200 <= r.status < 300:
                    raise EmailError("HTTP %s" % r.status)
        except urllib.error.HTTPError as e:
            raise EmailError("HTTP %s" % e.code)
        except (urllib.error.URLError, ssl.SSLError, OSError) as e:
            raise EmailError("%s" % type(e).__name__)
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg["sender"], cfg["to"]
    msg.set_content(body)
    try:
        if cfg["mode"] == "ssl":
            s = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30, context=context)
        else:
            s = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
            s.ehlo()
            s.starttls(context=context)
            s.ehlo()
        with s:
            s.login(cfg["username"], password)
            s.send_message(msg)
    except (smtplib.SMTPException, ssl.SSLError, OSError) as e:
        raise EmailError("%s" % type(e).__name__)


# ---------- content ----------
def _rows(db, a_cur, s_cur):
    a = db.conn.execute("SELECT a.* FROM audit_log a WHERE a.id>? ORDER BY a.id LIMIT 5000", (a_cur,)).fetchall()
    s = db.conn.execute("SELECT * FROM system_log WHERE id>? ORDER BY id LIMIT 5000", (s_cur,)).fetchall()
    return a, s


def _syslines(rows, only_bad=True):
    out = []
    for r in rows:
        if only_bad and r["level"] not in ("error", "warning"):
            continue
        out.append("  %s | %s | %s/%s | %s" % (r["created_at"], r["level"], r["component"], r["event"],
                                                RM._redact(r["message"], 200)))
    return out


def report(db, st, version=""):
    a, s = _rows(db, int(st.get("em_a_cur", 0)), int(st.get("em_s_cur", 0)))
    from collections import Counter
    acts = Counter((r["user"], r["action"]) for r in a)
    bad = _syslines(s)
    nerr = sum(1 for r in s if r["level"] == "error")
    nwarn = sum(1 for r in s if r["level"] == "warning")
    amax, smax = RM._max_ids(db)
    lines = ["[Pharmacy App] Report %s (%d error, %d warning)" % (datetime.now().strftime("%Y-%m-%d %H:%M"), nerr, nwarn), "",
             "App v%s | last log id %s" % (version or getattr(db, "app_version", "") or "?", amax),
             "", "Activity (summary level, no prices or customers):"]
    lines += ["  %s  %s x%d" % (u, act, n) for (u, act), n in sorted(acts.items())] or ["  none"]
    lines += ["", "Errors and warnings:"] + (bad or ["  none"])
    subject, body = lines[0], "\n".join(lines[1:])
    return subject, body, (a[-1]["id"] if a else None), (s[-1]["id"] if s else None)


# ---------- cursors / restore handling ----------
def _init_cursors(db, st):
    a, s = RM._max_ids(db)
    st.update(em_a_cur=a, em_s_cur=s, em_a_ts=RM._ts(db, "audit_log", a), em_s_ts=RM._ts(db, "system_log", s),
              em_last_report=time.time())


def _check_restore(db, st):
    a, s = RM._max_ids(db)
    changed = False
    for key, tbl, mx in (("a", "audit_log", a), ("s", "system_log", s)):
        cur = int(st.get("em_%s_cur" % key, 0))
        if cur > mx:
            new = RM._cursor_after(db, tbl, st.get("em_%s_ts" % key, ""), mx)
            st["em_%s_cur" % key] = new
            changed = True
    return changed


def tick(db, version="", now=None, context=None):
    """One pass. Returns list of subjects sent. Never raises; failures keep the cursors and are logged once."""
    sent = []
    try:
        st = RM.load_state(db)
        if st.get("enabled") != 1:
            return sent
        cfg = load_email_cfg()
        if cfg is None:
            return sent
        pw = load_secret(db)
        if not pw:
            return sent
        now = now if now is not None else time.time()
        if "em_a_cur" not in st:
            _init_cursors(db, st)
            RM.save_state(db, st)
        if _check_restore(db, st):
            RM.save_state(db, st)
        if now - float(st.get("em_last_report", 0)) >= REPORT_GAP:
            subj, body, amax, smax = report(db, st, version)
            send_mail(cfg, pw, subj, body, context)
            st = RM.load_state(db)
            if amax is not None:
                st["em_a_cur"], st["em_a_ts"] = amax, RM._ts(db, "audit_log", amax)
            if smax is not None:
                st["em_s_cur"], st["em_s_ts"] = smax, RM._ts(db, "system_log", smax)
            st.update(em_last_report=now, em_last_ok=datetime.now().isoformat(timespec="seconds"), em_last_err="")
            RM.save_state(db, st)
            sent.append(subj)
    except Exception as e:
        try:
            st = RM.load_state(db)
            st["em_last_err"] = str(e)[:200]
            RM.save_state(db, st)
            import cloud_sync
            cloud_sync.log_sync_error(db, "email_report_failed", str(e)[:200])
        except Exception:
            pass
    return sent
