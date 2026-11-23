# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise v4.12 — Windows Firewall helper for the mobile server.

Why this file exists: the most common reason a phone shows
ERR_CONNECTION_TIMED_OUT on http://<PC-IP>:8080 (or cannot open
https://<PC-IP>:8443) is that the PC itself answers fine on
127.0.0.1 but Windows Firewall blocks INBOUND TCP from the LAN.
The server binds 0.0.0.0, so the fix is inbound firewall rules —
no router change, no internet, no new packages.

Ports that must be open, each on BOTH profiles (private AND
public — the Windows Mobile Hotspot network is a PUBLIC profile):
    8080  HTTP  (invoices without scanning)
    8443  HTTPS (camera scanning — secure context)
So FOUR combinations must be covered:
    8080-private, 8080-public, 8443-private, 8443-public.

v4.12 audit — why v4.11's 8443 fix did NOT work on Mohamed's
real PC (found by reading the v4.11 code, not by guessing):
  1. The 8443 fix lived in main.py (_ensure_8443_rule), NOT in
     firewall.py, with its own second netsh implementation and
     different rule names ("Pharmacy Mobile 8443" vs firewall.py's
     "Pharmacy Enterprise Mobile 8080"). Two implementations that
     can disagree.
  2. Both v4.5 (8080) and v4.11 (8443) tried the COMBINED
     profile=private,public netsh syntax FIRST. That syntax was
     never verified on real Windows netsh in this VM. If netsh
     rejects it, the add fails — and the fallback then tries to
     add a rule with the SAME name, which netsh can reject as
     "already exists" if the combined add had in fact created it.
  3. main.py's _rule8443_profiles() only read lines containing
     "profile" or the exact Arabic string "ملف التعريف". netsh
     prints "Profiles:" (plural) in English, and on Arabic
     Windows "ملفات التعريف" — which does NOT contain
     "ملف التعريف" (extra alif) — so the profile line was missed
     and a rule that existed was reported as covering nothing.
     It also never added "private" by rule name (only "public"
     for the Public-named rule), so a private rule whose profile
     line was missed was invisible to the checker.
  4. The fix button reported SUCCESS from the 8080 result only:
     _firewall_fix_done(ok, ...) used ok from firewall.add_rule()
     (8080) and showed a success dialog even when the 8443 helper
     had returned False — the 8443 failure was buried inside a
     concatenated message in a success dialog.
  5. The diagnostics panel ("اختبار الاتصال") only checked
     firewall_status() for port 8080 — it NEVER checked 8443 at
     all. So it could print ✅ firewall while the phone on HTTPS
     was still blocked.
  All five are fixed here: one implementation, single-profile
  rules ONLY (the exact syntax Mohamed ran manually and proved
  works for both 8080-public and 8443-public), per-port
  per-profile coverage, and a fix/diagnostics path that reports
  success ONLY when all four combinations are covered.

Rule names (canonical — used when ADDING a rule):
    8080 private: "Pharmacy Enterprise Mobile 8080"
    8080 public:  "Pharmacy Mobile 8080 Public"
    8443 private: "Pharmacy Enterprise Mobile 8443"
    8443 public:  "Pharmacy Mobile 8443 Public"
When CHECKING, the legacy v4.11 private name for 8443
("Pharmacy Mobile 8443") is also accepted, as is a combined
private,public rule under any of those names — so a rule Mohamed
already created manually is detected and never duplicated.

Every function returns (ok, arabic_message) or a dict and never
raises to the UI. On non-Windows (e.g. this Linux test VM) every
function returns a clear "Windows only" result instead of crashing.
"""
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE, "firewall.log")

# Canonical rule names used when ADDING a rule, per port/profile.
PORT_RULES = {
    8080: {"private": "Pharmacy Enterprise Mobile 8080",
           "public": "Pharmacy Mobile 8080 Public"},
    8443: {"private": "Pharmacy Enterprise Mobile 8443",
           "public": "Pharmacy Mobile 8443 Public"},
}
PORTS = (8080, 8443)
PROFILES = ("private", "public")
# Legacy names accepted when CHECKING (never added under these):
# v4.11's helper used "Pharmacy Mobile 8443" as its private name.
LEGACY_NAMES = {
    8443: {"private": ["Pharmacy Mobile 8443"], "public": []},
    8080: {"private": [], "public": []},
}


def is_windows():
    return os.name == "nt" or platform.system() == "Windows"


def log(message):
    # v5.0: cap the log at ~1 MB (keep last 200 KB) so it never
    # grows forever on a pharmacy PC.
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 1024 * 1024:
            with open(LOG_PATH, "rb") as f:
                f.seek(-200 * 1024, os.SEEK_END)
                tail = f.read()
            with open(LOG_PATH, "wb") as f:
                f.write(b"... [log truncated, kept last 200KB] ...\n" + tail)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (datetime.now().isoformat(timespec="seconds"), message))
    except Exception:
        pass


def is_admin():
    """True if the process runs elevated. False on non-Windows."""
    if not is_windows():
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_netsh(args, timeout=20):
    """Run one netsh command. Returns (ok, stdout, stderr). Never raises."""
    if not is_windows():
        return False, "", "يعمل على ويندوز فقط."
    netsh = shutil.which("netsh") or r"C:\Windows\System32\netsh.exe"
    cmd = [netsh] + args
    log("run: %s" % " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                              text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        log("netsh timeout: %s" % " ".join(args))
        return False, "", "انتهت المهلة أثناء تنفيذ أمر جدار الحماية."
    except Exception as e:
        log("netsh error: %s" % e)
        return False, "", "تعذر تشغيل netsh: %s" % e
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    log("exit=%s out=%r err=%r" % (proc.returncode, out[:400], err[:400]))
    return proc.returncode == 0, out, err


def _parse_profiles(text):
    """Profiles a netsh `show rule` output claims.

    Reads the PROFILE line(s) specifically — English "Profile:"
    / "Profiles:" and Arabic "ملف التعريف" / "ملفات التعريف"
    (matched via the substring "تعريف", which covers both Arabic
    forms — the v4.11 bug was matching the exact singular form
    only). Falls back to scanning the whole block when no profile
    line is found. Returns a set of {'private', 'public',
    'domain', 'all'}. "all" expands to all three in callers.
    Never raises.
    """
    try:
        text = text or ""
        low = text.lower()
        found = set()
        profile_lines = []
        for line in text.splitlines():
            ll = line.lower()
            if "profile" in ll or "تعريف" in ll:
                profile_lines.append(ll)
        hay = "\n".join(profile_lines) if profile_lines else low
        for word in ("private", "public", "domain"):
            if word in hay:
                found.add(word)
        if re.search(r"profile\s*:\s*all\b", hay) or "all" in hay and profile_lines:
            # "Profile: All" — only from a profile line, never a stray word.
            if re.search(r"profile\s*:\s*all\b", hay):
                found.add("all")
        if "all" in found:
            found.update(("private", "public", "domain"))
        return found
    except Exception:
        return set()


def _rule_info(name, port):
    """(found, profiles) for one rule name.

    found is True / False / None (unknown — netsh failed for a
    reason other than "no such rule"). profiles is the set from
    _parse_profiles, empty when the rule does not exist.
    A rule only counts when its output mentions the port (LocalPort)
    or the exact rule name, so a prefix match returning another
    rule cannot pollute the result. Never raises.
    On non-Windows returns (None, set()).
    """
    if not is_windows():
        return None, set()
    ok, out, err = _run_netsh(
        ["advfirewall", "firewall", "show", "rule", "name=%s" % name])
    text = (out + "\n" + err)
    low = text.lower()
    if ("no rules match" in low or "لا توجد قواعد" in low
            or "no rule" in low or "there are no rules" in low):
        return False, set()
    if str(port) not in text and name.lower() not in low:
        return False, set()
    profiles = _parse_profiles(text)
    if profiles:
        return True, profiles
    if not ok:
        return None, set()
    # A matching rule was printed (name/port appear) even if the
    # profile words were not recognised — count it as found with
    # unknown profiles, not as missing.
    return True, set()


def _coverage_for_port(port):
    """(private, public, unknown) for one port.

    Union over the canonical rule names for that port plus any
    legacy names accepted for it. unknown is True when netsh could
    not be checked at all for a rule that would matter.
    Never raises. On non-Windows returns (False, False, True).
    """
    if not is_windows():
        return False, False, True
    all_profiles = set()
    unknown = False
    names = {}
    for profile in PROFILES:
        names[profile] = [PORT_RULES[port][profile]]
        names[profile] += LEGACY_NAMES.get(port, {}).get(profile, [])
    for profile in PROFILES:
        for name in names[profile]:
            found, profs = _rule_info(name, port)
            if found is None:
                unknown = True
            elif found:
                all_profiles |= profs
                # A rule found under this name but with no readable
                # profiles still counts as covering the profile its
                # NAME promises (v4.11 lesson: never report a rule
                # that exists as covering nothing).
                if not profs:
                    all_profiles.add(profile)
    if "all" in all_profiles:
        return True, True, False
    return ("private" in all_profiles,
            "public" in all_profiles,
            unknown and not ("private" in all_profiles
                             and "public" in all_profiles))


def coverage_all():
    """{port: {"private": bool, "public": bool, "unknown": bool}}.

    Never raises. On non-Windows every port is unknown.
    """
    return {port: {"private": p, "public": q, "unknown": u}
            for port, (p, q, u) in
            ((port, _coverage_for_port(port)) for port in PORTS)}


def _missing_combos(coverage=None):
    """List of (port, profile) not covered, e.g. [(8443, "public")]."""
    cov = coverage or coverage_all()
    missing = []
    for port in PORTS:
        for profile in PROFILES:
            if not cov[port][profile]:
                missing.append((port, profile))
    return missing


def _combo_label(port, profile):
    return "البورت %d (%s)" % (port, "خاصة" if profile == "private" else "عامة")


def rule_exists():
    """(both_8080_covered, arabic_message) — port 8080 only.

    Kept for backward compatibility. True ONLY when port 8080 is
    allowed on BOTH private and public profiles. Use
    rule_exists_all() / firewall_status() for the full picture.
    Never raises. On non-Windows returns (None, windows-only msg).
    """
    if not is_windows():
        return None, "فحص جدار الحماية يعمل على ويندوز فقط."
    cov = coverage_all()
    private, public = cov[8080]["private"], cov[8080]["public"]
    if cov[8080]["unknown"] and not (private and public):
        return None, "تعذر فحص جدار الحماية."
    if private and public:
        return True, ("قاعدة جدار الحماية موجودة وتسمح بالبورت 8080 "
                      "على الشبكات الخاصة والعامة.")
    if private and not public:
        return False, ("القاعدة موجودة للشبكات الخاصة فقط — الهوت سبوت "
                       "شبكة عامة (Public)، فالهاتف على الهوت سبوت لن يصل — "
                       "اضغط «إصلاح الاتصال».")
    if public and not private:
        return False, ("القاعدة موجودة للشبكات العامة فقط — واي فاي البيت "
                       "(شبكة خاصة) لن يصل — اضغط «إصلاح الاتصال».")
    return False, "لا توجد قاعدة تسمح بالبورت 8080 — اضغط «إصلاح الاتصال»."


def rule_exists_all():
    """(all_four_covered, arabic_message).

    True ONLY when BOTH ports (8080 and 8443) are allowed on BOTH
    profiles. A missing 8443-public rule — the v4.11 bug — is
    reported as a failure, never as "rule exists".
    Never raises. On non-Windows returns (None, windows-only msg).
    """
    if not is_windows():
        return None, "فحص جدار الحماية يعمل على ويندوز فقط."
    cov = coverage_all()
    missing = _missing_combos(cov)
    if not missing:
        return True, ("قواعد جدار الحماية موجودة وتسمح بالبورتين 8080 و 8443 "
                      "على الشبكات الخاصة والعامة.")
    if any(cov[p]["unknown"] for p in PORTS) and not missing:
        return None, "تعذر فحص جدار الحماية."
    labels = "، ".join(_combo_label(p, pr) for p, pr in missing)
    return False, ("جدار الحماية ناقص: %s — اضغط «إصلاح الاتصال»." % labels)


def _add_single_rule(name, port, profile):
    """Add ONE single-profile rule. Returns (ok, output_text).

    Single-profile syntax ONLY — this is the exact syntax Mohamed
    ran manually on his PC and proved works, for both
    8080-public and 8443-public. The combined
    profile=private,public syntax is deliberately NOT used anywhere
    in v4.12. A netsh "already exists" answer is treated as ok:
    the rule is there, coverage is re-checked by the caller.
    Never raises (on non-Windows returns (False, windows-only)).
    """
    ok, out, err = _run_netsh([
        "advfirewall", "firewall", "add", "rule",
        "name=%s" % name,
        "dir=in", "action=allow", "protocol=TCP",
        "localport=%d" % port, "profile=%s" % profile, "remoteip=localsubnet",
    ])
    text = (out + " " + err).strip()
    low = text.lower()
    if ok or "ok." in low or "already exists" in low or "موجود" in low:
        return True, text
    return False, text


def _denied(text):
    low = (text or "").lower()
    return any(w in low for w in ("access is denied", "denied", "administrator",
                                  "elevation", "0x80070005", "requires elevation"))


def restrict_existing_rules():
    """Narrow only known application rules. Called by the explicit repair action."""
    if not is_windows():
        return False, "Windows only"
    for port in PORTS:
        names = set(PORT_RULES[port].values())
        for profile in PROFILES:
            names.update(LEGACY_NAMES.get(port, {}).get(profile, []))
        for name in sorted(names):
            found, _profiles = _rule_info(name, port)
            if found is None:
                return False, "Could not inspect existing firewall rules."
            if not found:
                continue
            ok, _out, _err = _run_netsh([
                "advfirewall", "firewall", "set", "rule", "name=%s" % name,
                "new", "remoteip=localsubnet"])
            if not ok:
                return False, "Could not restrict existing firewall rule; run repair as administrator."
    return True, "Known app rules restricted to the local subnet."


def add_rule():
    """Open inbound TCP 8080 AND 8443 on BOTH private and public profiles.

    Ensures all FOUR combinations, one single-profile rule at a
    time, re-checking coverage after the adds. Returns
    (ok, arabic_message). ok is True ONLY when all four are
    covered. Needs administrator: if the process is not elevated,
    netsh fails with access denied and the message says so plainly
    instead of pretending it worked. If all four are already
    covered — e.g. the user already ran the manual public-profile
    commands — returns True immediately and says no action was
    needed, creating no duplicates.
    """
    if not is_windows():
        return False, "إصلاح جدار الحماية يعمل على ويندوز 10 / 11 فقط."
    narrowed, detail = restrict_existing_rules()
    if not narrowed:
        return False, detail
    cov = coverage_all()
    missing = _missing_combos(cov)
    if not missing:
        return True, ("قواعد جدار الحماية موجودة بالفعل للبورتين 8080 و 8443 "
                      "على الشبكات الخاصة والعامة — لا حاجة لأي إجراء إضافي.\n"
                      "جرّب فتح الرابط من الهاتف مرة أخرى.")
    last_err = ""
    for port, profile in missing:
        name = PORT_RULES[port][profile]
        ok, text = _add_single_rule(name, port, profile)
        if not ok:
            last_err = text
    cov = coverage_all()
    missing = _missing_combos(cov)
    if not missing:
        return True, ("تم فتح البورتين 8080 و 8443 في جدار حماية ويندوز "
                      "للشبكات الخاصة والعامة ✅\n"
                      "جرّب الآن فتح الرابط من الهاتف مرة أخرى.")
    if _denied(last_err):
        return False, ("تعذر فتح البورت: يلزم تشغيل البرنامج كمسؤول.\n"
                       "أغلق البرنامج، ثم كليك يمين على run.bat واختر "
                       "«Run as administrator»، ثم اضغط «إصلاح الاتصال» مجدداً.")
    labels = "، ".join(_combo_label(p, pr) for p, pr in missing)
    return False, ("تعذر فتح جدار الحماية لـ: %s\n%s\n"
                   "أعد تشغيل البرنامج كمسؤول وحاول مجدداً، أو نفّذ يدوياً "
                   "من PowerShell كمسؤول:\n"
                   "netsh advfirewall firewall add rule "
                   "name=\"Pharmacy Mobile %d Public\" dir=in action=allow "
                   "protocol=TCP localport=%d profile=public remoteip=localsubnet"
                   % (labels, last_err or "خطأ غير معروف من netsh.",
                      missing[0][0], missing[0][0]))


def firewall_status():
    """One dict for the diagnostics panel. Never raises.

    Keys: exists (True only when ALL FOUR combinations are
    covered), ports {8080: {private, public, unknown},
    8443: {...}}, private (True only when both ports cover
    private), public (True only when both ports cover public),
    admin, message.
    """
    if not is_windows():
        return {"exists": None, "ports": {},
                "private": None, "public": None,
                "admin": False,
                "message": "فحص جدار الحماية يعمل على ويندوز فقط."}
    cov = coverage_all()
    missing = _missing_combos(cov)
    _both, msg = rule_exists_all()
    return {"exists": bool(not missing),
            "ports": cov,
            "private": bool(cov[8080]["private"] and cov[8443]["private"]),
            "public": bool(cov[8080]["public"] and cov[8443]["public"]),
            "admin": is_admin(),
            "message": msg}


def main():
    import sys
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if action == "add":
        print(add_rule())
    elif action == "admin":
        print("admin:", is_admin())
    elif action == "coverage":
        print(firewall_status())
    else:
        print(firewall_status())
    try:
        input("اضغط Enter للخروج...")
    except Exception:
        pass


if __name__ == "__main__":
    main()
