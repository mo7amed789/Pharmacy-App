# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise v5.4 — the REAL Windows Mobile Hotspot.

The phone joins the PC's OWN Windows Mobile Hotspot (the one in
Settings > Network & internet > Mobile hotspot), then opens the
mobile invoice server (mobile_server.py, ports 8080/8443).
No internet is needed at any point — the hotspot and the invoice
server are both local.

IMPORTANT (v5.4): the app does NOT invent its own hotspot network
and does NOT overwrite the Windows hotspot name/password. There is
no invented hotspot network any more. StartTetheringAsync() turns on
THE Windows hotspot with ITS existing name and password — the same
switch the user flips in Windows Settings. The SSID is read back
from Windows via GetCurrentAccessPointConfiguration() when Windows
exposes it; the password is NOT reliably exposed by Windows and is
therefore never displayed and never guessed — it is the password
already set in Windows Settings.

How it works on modern Windows 10/11 (read this before "fixing" it):
  * The legacy `netsh wlan set hostednetwork` command is DEAD on most
    modern adapters: `netsh wlan show drivers` usually reports
    "Hosted network supported: No". Do NOT use hostednetwork.
  * The supported programmatic way is the Windows Runtime (WinRT) API:
    NetworkOperatorTetheringManager.CreateFromConnectionProfile(...)
    then StartTetheringAsync() / StopTetheringAsync(). The PowerShell
    script hotspot.ps1 (shipped next to this file) does that work;
    this module only launches it, parses its output, and never raises
    to the UI — every function returns (ok, message) or a dict.
  * The hotspot auto-stops after ~5 minutes with no connected
    clients unless DisableNoConnectionsTimeout() is called — the
    script calls it (best effort, ignored if unavailable).
  * The SSID/password are the ones configured in Windows
    Settings > Network > Mobile hotspot. Windows does NOT let a
    script read the password freely on every build; the script tries
    GetCurrentAccessPointConfiguration() and, if that fails, this
    module says so honestly and tells the user where to see/change
    it in Settings. Since v5.4 the app NEVER calls
    ConfigureAccessPointAsync() — changing the name/password is
    done only by the user in Windows Settings, so the app can never
    replace the real PC hotspot with an invented one.
  * Starting the hotspot may need administrator rights. If the
    script fails with an access error, the UI tells the user to run
    run.bat as administrator (right-click > Run as administrator).

On non-Windows (e.g. this Linux test VM) every function returns a
clear "Windows only" result instead of crashing.
"""
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import traceback
from datetime import datetime

BASE = (os.path.dirname(os.path.abspath(sys.executable))
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)))
PS1_PATH = os.path.join(getattr(sys, "_MEIPASS", BASE), "hotspot.ps1")
LOG_PATH = os.path.join(BASE, "hotspot.log")

def pc_hostname():
    """Real PC name, e.g. DESKTOP-BMF6PTK (v5.4).

    Windows names its Mobile Hotspot after the PC
    (e.g. "DESKTOP-BMF6PTK 3602"), so the PC name is the honest
    fallback hint when Windows does not expose the SSID to the
    script. It is a DISPLAY hint only — it is never written back
    as a hotspot name, and no password is ever invented here.
    Never raises; returns "" when it cannot be read.
    """
    try:
        return socket.gethostname() or ""
    except Exception:
        return ""


def is_windows():
    return os.name == "nt" or platform.system() == "Windows"


def _redact(message):
    """v5.0: never write a Wi-Fi password (or a PIN/password) to disk.
    Strips -Passphrase <value> and PASSWORD: <value> from any log line."""
    msg = re.sub(r"(-Passphrase\s+)\S+", r"\1***", str(message))
    msg = re.sub(r"(?i)(PASSWORD\s*:\s*)\S+", r"\1***", msg)
    return msg


def _rotate_log():
    """v5.0: cap the log at ~1 MB — keep the last 200 KB so logs can
    never grow forever on a pharmacy PC."""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 1024 * 1024:
            with open(LOG_PATH, "rb") as f:
                f.seek(-200 * 1024, os.SEEK_END)
                tail = f.read()
            with open(LOG_PATH, "wb") as f:
                f.write(b"... [log truncated, kept last 200KB] ...\n" + tail)
    except Exception:
        pass


def log(message):
    """Append one line to hotspot.log (best effort, never raises)."""
    try:
        _rotate_log()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (datetime.now().isoformat(timespec="seconds"),
                                  _redact(message)))
    except Exception:
        pass


def find_powershell():
    """Return the PowerShell executable path, or None."""
    for name in ("powershell", "pwsh"):
        path = shutil.which(name)
        if path:
            return path
    # Common fixed locations on Windows.
    for cand in (r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                 r"C:\Program Files\PowerShell\7\pwsh.exe"):
        if os.path.exists(cand):
            return cand
    return None


def _run_ps(action, extra_args=None, timeout=40):
    """Run hotspot.ps1 -Action <action>. Returns (ok, stdout, stderr).

    ok=False with a readable message on: non-Windows, PowerShell
    missing, script missing, timeout, or non-zero exit code.
    Never raises.
    """
    if not is_windows():
        return False, "", "يعمل على ويندوز فقط — هذه الميزة غير متاحة على هذا النظام."
    ps = find_powershell()
    if not ps:
        return False, "", "لم يتم العثور على PowerShell على هذا الجهاز."
    if not os.path.exists(PS1_PATH):
        return False, "", "ملف hotspot.ps1 غير موجود بجانب البرنامج — انسخ ملفات التحديث v5 كاملة."
    cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", PS1_PATH, "-Action", action]
    for a in (extra_args or []):
        cmd.append(a)
    log("run: %s" % " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                              text=True, encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        log("timeout after %ds: %s" % (timeout, action))
        return False, "", "انتهت المهلة أثناء تنفيذ أمر الهوت سبوت (أكثر من %d ثانية)." % timeout
    except Exception as e:
        log("subprocess error: %s" % e)
        return False, "", "تعذر تشغيل PowerShell: %s" % e
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    log("exit=%s out=%r err=%r" % (proc.returncode, out[:500], err[:500]))
    if proc.returncode != 0 and not out:
        return False, out, err or "فشل تنفيذ سكربت الهوت سبوت بدون تفاصيل."
    return True, out, err


def _parse_output(text):
    """Parse KEY:value lines printed by hotspot.ps1 into a dict."""
    data = {}
    for line in (text or "").splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            data[key.strip().upper()] = value.strip()
    return data


def _admin_hint(error_text):
    """Append the run-as-admin hint when the error smells like access."""
    low = (error_text or "").lower()
    if any(w in low for w in ("access", "denied", "unauthorized", "admin",
                              "privilege", "0x80070005", "e_accessdenied")):
        return (" — قد تحتاج صلاحيات مسؤول: أغلق البرنامج، ثم كليك يمين على "
                "run.bat واختر «Run as administrator»، ثم حاول مجدداً.")
    return ""


def check_hotspot_support():
    """Best-effort support check. Returns a dict, never raises.

    Keys: supported (True/False/None=unknown), windows (bool),
    powershell (bool), legacy_hosted (Yes/No/unknown),
    reason (Arabic, human-readable).
    NOTE: legacy hostednetwork is informational only — modern
    Windows hotspot uses the WinRT tethering API, so
    "Hosted network supported: No" does NOT mean the hotspot
    cannot work.
    """
    if not is_windows():
        return {"supported": None, "windows": False,
                "powershell": False, "legacy_hosted": "unknown",
                "reason": "هذه الميزة تعمل على ويندوز 10 / 11 فقط."}
    ps = find_powershell()
    legacy = "unknown"
    try:
        proc = subprocess.run(["netsh", "wlan", "show", "drivers"],
                              capture_output=True, timeout=15,
                              text=True, encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        m = re.search(r"Hosted network supported\s*:\s*(\w+)",
                      proc.stdout or "", re.IGNORECASE)
        if m:
            legacy = m.group(1)
    except Exception:
        pass
    reason = ("واي فاي الهوت سبوت في ويندوز 10/11 يعمل عبر واجهة WinRT "
              "(NetworkOperatorTetheringManager) وليس عبر netsh hostednetwork القديم، "
              "لذلك «Hosted network supported» لا يقرر وحده إن كان يعمل أم لا. "
              "جرّب زر التشغيل — إذا فشل، ستظهر رسالة الخطأ الحقيقية من ويندوز.")
    return {"supported": None, "windows": True, "powershell": bool(ps),
            "legacy_hosted": legacy, "reason": reason}


def get_hotspot_status():
    """Return dict: {state: On/Off/Unknown, ssid, password, clients,
    raw, error}. Never raises; on non-Windows state is Unknown
    with a clear error."""
    if not is_windows():
        return {"state": "Unknown", "ssid": "", "password": "",
                "clients": "unknown", "pc_name": pc_hostname(), "raw": "",
                "error": "يعمل على ويندوز فقط — هذه الميزة غير متاحة على هذا النظام."}
    ok, out, err = _run_ps("Status")
    if not ok:
        return {"state": "Unknown", "ssid": "", "password": "",
                "clients": "unknown", "pc_name": pc_hostname(), "raw": out,
                "error": (err or "تعذر قراءة حالة الهوت سبوت.") + _admin_hint(err)}
    data = _parse_output(out)
    if data.get("ERROR"):
        return {"state": "Unknown", "ssid": "", "password": "",
                "clients": "unknown", "pc_name": pc_hostname(), "raw": out,
                "error": data["ERROR"] + _admin_hint(data["ERROR"])}
    return {"state": data.get("STATUS", "Unknown"),
            "ssid": data.get("SSID", ""),
            "password": data.get("PASSWORD", ""),
            "clients": data.get("CLIENTS", "unknown"),
            "pc_name": pc_hostname(),
            "raw": out, "error": ""}


def get_hotspot_config():
    """Return (ssid, password) as configured in Windows, or ('', '')
    when Windows does not expose them. Never raises."""
    st = get_hotspot_status()
    return st.get("ssid", ""), st.get("password", "")


def start_hotspot():
    """Start the PC hotspot. Returns (ok, arabic_message)."""
    if not is_windows():
        return False, "تشغيل هوت سبوت ويندوز يعمل على ويندوز 10 / 11 فقط."
    ok, out, err = _run_ps("Start", timeout=60)
    if not ok:
        return False, (err or "تعذر تشغيل الهوت سبوت.") + _admin_hint(err)
    data = _parse_output(out)
    if data.get("ERROR"):
        return False, data["ERROR"] + _admin_hint(data["ERROR"])
    if data.get("STATUS", "").lower() == "on":
        # StartTetheringAsync turns on THE Windows hotspot with ITS
        # existing name/password — no invented network, no new password.
        ssid = (data.get("SSID") or "").strip()
        msg = ("تم تشغيل هوت سبوت ويندوز ✅\n"
               "من الموبايل: اتصل بشبكة الواي فاي، ثم افتح رابط "
               "الموبايل وأدخل رمز PIN. لا حاجة لأي إنترنت.")
        if ssid:
            msg = ("تم تشغيل هوت سبوت ويندوز ✅ — الشبكة: %s\n"
                   "من الموبايل: اتصل بهذه الشبكة، ثم افتح رابط "
                   "الموبايل وأدخل رمز PIN. لا حاجة لأي إنترنت.") % ssid
        return True, msg
    return False, "ويندوز لم يؤكد تشغيل الهوت سبوت. راجع ملف hotspot.log."


def stop_hotspot():
    """Stop the PC hotspot. Returns (ok, arabic_message)."""
    if not is_windows():
        return False, "إيقاف هوت سبوت ويندوز يعمل على ويندوز 10 / 11 فقط."
    ok, out, err = _run_ps("Stop", timeout=60)
    if not ok:
        return False, (err or "تعذر إيقاف الهوت سبوت.") + _admin_hint(err)
    data = _parse_output(out)
    if data.get("ERROR"):
        return False, data["ERROR"] + _admin_hint(data["ERROR"])
    return True, "تم إيقاف هوت سبوت ويندوز."


def set_hotspot_config(ssid, password):
    """v5.4 — REFUSES to change the hotspot name/password.

    The old implementation called ConfigureAccessPointAsync(),
    which would REPLACE the real Windows Mobile Hotspot name and
    password with whatever name the app invented.
    That is exactly what the user asked to stop: the name and
    password must be the real PC's, set by the user in Windows
    Settings > Network & internet > Mobile hotspot. So this
    function now always returns False with the Settings
    instructions, and never runs the Configure script action.
    Kept (same signature) so old callers fail loudly and safely
    instead of silently overwriting the real hotspot.
    """
    return False, ("اسم شبكة الهوت سبوت وكلمة المرور يُحدَّدان من "
                   "إعدادات ويندوز فقط، وليس من البرنامج — افتح "
                   "الإعدادات > الشبكة والإنترنت > Mobile hotspot "
                   "وغيّرهما من هناك.")
def open_hotspot_settings():
    """Open Windows Settings > Mobile hotspot. Returns True on Windows."""
    if not is_windows():
        return False
    try:
        os.startfile("ms-settings:network-mobilehotspot")  # noqa: S606 - local settings page
        return True
    except Exception as e:
        log("open settings failed: %s" % e)
        return False


def run_in_thread(fn, done=None):
    """Run fn() in a daemon thread; call done(ok, message) on the
    calling thread's behalf via the callback (the caller is
    responsible for marshalling back to the Tkinter thread, e.g.
    with root.after). fn must return (ok, message)."""
    def _run():
        try:
            ok, msg = fn()
        except Exception:
            log("thread error:\n%s" % traceback.format_exc())
            ok, msg = False, "حدث خطأ غير متوقع — راجع ملف hotspot.log."
        if done:
            try:
                done(ok, msg)
            except Exception:
                log("done-callback error:\n%s" % traceback.format_exc())
    threading.Thread(target=_run, daemon=True).start()


def main():
    """Standalone check: py hotspot.py [status|start|stop|support]"""
    import sys
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if action == "support":
        print(check_hotspot_support())
    elif action == "start":
        print(start_hotspot())
    elif action == "stop":
        print(stop_hotspot())
    elif action == "config":
        print(get_hotspot_config())
    else:
        print(get_hotspot_status())
    try:
        input("اضغط Enter للخروج...")
    except Exception:
        pass


if __name__ == "__main__":
    main()
