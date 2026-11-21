# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise v3 — Windows desktop app (stdlib only: Tkinter + SQLite).
Arabic-first UI, offline-first, EGP.
Run: double-click run.bat  (it tries `py` first, then `python`)
Login: first run uses the factory accounts — the app FORCES a password
change on first login. Never share the default password in writing.
       cashier role cannot change prices.
v1 ships with ~60 SAMPLE drugs + CSV import. The full 25,000-item
Egyptian catalog is a Phase 2 DATA task, not a code task — see README_AR.md.
v3 adds: big UI overhaul (ui_theme.py) — dashboard, modern theme, POS redesign.
v4 adds: mobile companion (mobile_server.py + mobile.html) — phone on the
same Wi-Fi creates invoices in the same DB; the PC prints them from the
Mobile tab. LAN-only, 6-digit PIN, no internet, no new packages.
v5 adds: PC local Wi-Fi hotspot (hotspot.py + hotspot.ps1) — the PC
creates its own Wi-Fi network, so the phone needs no
router and no internet at all. WinRT NetworkOperatorTetheringManager
API (NOT legacy netsh hostednetwork). See docs/changelog/README_AR_V5.md.
v4.1 (in v5.2): mobile-connection fix — list EVERY local IP
(hotspot 192.168.137.x AND home Wi-Fi 192.168.1.x), firewall rule
button for port 8080, and a connection-diagnostics panel, because
ERR_CONNECTION_TIMED_OUT means the phone never reached the PC.
See docs/changelog/README_AR_V4.1.md.
v4.2 (app v5.3): QR/barcode scan on the mobile page (BarcodeDetector,
camera, no CDN), a connect-QR on the PC Mobile tab (qrgen.py, pure
Python, stdlib only), live update every 3s on the PC / 5s on the phone
(no manual Refresh), RTL fixes on the mobile page + Mobile tab, and
a "كل الفواتير" view in Reports (filters, detail, CSV export).
See docs/changelog/README_AR_V4.2.md.
v4.3 (app v5.4): QR LIVE in the app — the connect-QR draws
automatically when the Mobile tab is opened and the server is
running, refreshes only when the URL or server state changes, and
shows a live status line; when the server is stopped it shows
"شغّل السيرفر أولاً لعرض الـ QR" instead of a stale QR. Plus a
"🌐 فتح الموقع على هذا الكمبيوتر" button that opens
http://127.0.0.1:8080 in the PC browser (localhost, no phone, no
firewall) — PC-only test path; phone access is unchanged.
See docs/changelog/README_AR_V4.3.md.
v4.4 (app v5.5): Mobile tab is SCROLLABLE — the tab was a plain
Frame with every section packed directly on it, so on a normal
window everything below the fold (QR, diagnostics, pending-print
list) was unreachable: no scrollbar existed at all. Now the whole
tab lives inside a Canvas + vertical Scrollbar + inner Frame, with
mouse-wheel scrolling (Windows <MouseWheel>, Linux Button-4/5),
plus a hint label at the top. Also ships qrgen.py itself (v4.3
did not include it, so skipping v4.2 meant no QR could draw).
v4.5 (app v5.6): firewall rule must cover PUBLIC profile too —
v4.1 created the 8080 rule with profile=private only, and the
Windows Mobile Hotspot network is PUBLIC, so the phone on the
hotspot was still blocked even though the rule "existed" and
every PC-side diagnostic passed. Confirmed on Mohamed's PC:
phone on hotspot (192.168.137.242) got "can't be reached" until
he added a public-profile rule manually. firewall.py now opens
8080 on private+public (one combined rule if netsh accepts it,
else two single-profile rules) and the diagnostics panel reports
private-only / public-only instead of a misleading "rule exists".
See docs/changelog/README_AR_V4.5.md. The combined profile=private,public
netsh syntax was NOT verified on real Windows in this VM.
See docs/changelog/README_AR_V4.4.md.
v4.11 (app v5.7): HTTPS for camera scanning — plain http://192.168.137.1:8080
is an INSECURE context in Chrome, so the browser itself removes
getUserMedia / BarcodeDetector and no permission prompt ever appears;
the chrome://flags workaround did not fix it on Mohamed's phone.
mobile_server.py now also listens on HTTPS 8443 with a local
self-signed cert (cert.pem / key.pem, stdlib ssl only, SANs:
192.168.137.1, 192.168.1.2, 127.0.0.1, localhost). The Mobile tab
shows the HTTPS URL as the recommended scan URL and the connect-QR
now encodes the HTTPS URL; HTTP 8080 still works for invoices
without scanning. The phone shows a cert warning the first time
(Advanced > Proceed). "إصلاح الاتصال" also opens port 8443 in the
firewall (private+public), because the old 8080-only rule would
still block HTTPS. NOT verified on a real phone / real Windows.
See docs/changelog/README_AR_V4.11.md.
v4.12 (app v5.8): firewall fix for 8443, done properly in the
ORIGINAL app code — the v4.11 helper in main.py (_ensure_8443_rule)
did NOT open 8443 on Mohamed's PC: the HTTPS link stayed blocked
until he ran the manual public-profile 8443 command himself.
Audit found: the helper tried the unverified combined
profile=private,public syntax first; its profile parser missed
the "Profiles:" line on localised Windows ("ملفات التعريف" does
not contain "ملف التعريف"); the fix button reported SUCCESS from
the 8080 result even when 8443 failed; and diagnostics never
checked 8443 at all. v4.12 centralises both ports in firewall.py:
8080 AND 8443, each on private AND public, with single-profile
rules ONLY (the exact syntax Mohamed proved manually), per-port
per-profile diagnostics, and a fix button that succeeds ONLY when
all four combinations are covered. See docs/changelog/README_AR_V4.12.md.
v5.10 (audit step 3): receipt printing + barcode labels — receipts go to
receipts/ (auto-pruned after 30 days), optional direct ESC/POS raw printing
(stdlib only, Windows winspool) with cash-drawer kick on cash sales only,
and a barcode-label utility in Inventory (name + price + barcode number as
text — no Code-128 encoder exists in the codebase, qrgen.py is QR-only).
Defaults keep the old Windows-default printing. NOT tested on real printer
hardware. See README_AR_V5.10.md.
v2 adds: local AI inventory forecasting (ai_forecast.py) — weighted
moving average + trend + weekly seasonality, reorder points, expiry
loss prediction, cheapest-supplier comparison. No API key, no internet.
"""
import os
import queue
import shutil
import sqlite3
import ssl
import subprocess
import sys
import webbrowser  # v4.3: open http://127.0.0.1:8080 on the PC only (stdlib)
import threading
import urllib.request
import urllib.error
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import date, datetime

from database import (DB, allowed_units, unit_price, units_for_qty,
                      units_per_box, extract_gtin, drug_default_line_discount,
                      discount_label, ean13_png_bytes)
import ui_theme
try:
    import ai_forecast
except Exception:  # pragma: no cover - patch missing ai_forecast.py
    ai_forecast = None
try:
    import mobile_server
except Exception:  # pragma: no cover - patch missing mobile_server.py
    mobile_server = None
try:
    import hotspot
except Exception:  # pragma: no cover - patch missing hotspot.py
    hotspot = None
try:
    import firewall
except Exception:  # pragma: no cover - patch missing firewall.py
    firewall = None
try:
    import qrgen  # v4.2: pure-Python QR encoder (stdlib only)
except Exception:  # pragma: no cover - patch missing qrgen.py
    qrgen = None
try:
    import printer as receipt_printer  # v5.10 (audit step 3): receipts/ + ESC/POS
except Exception:  # pragma: no cover - patch missing printer.py
    receipt_printer = None


def qr_url_with_pin(url, pin):
    """Build the phone QR URL without putting the PIN in the query string.

    The fragment is read locally by mobile.html and is never sent in an
    HTTP request, so it cannot leak through server request logs or referrers.
    Invalid PINs deliberately produce a plain URL rather than a misleading
    partially authenticated link.
    """
    base = str(url or "").strip().split("#", 1)[0]
    value = str(pin or "").strip()
    try:
        parts = urlsplit(base)
        # Drop legacy ?pin= values before creating the new fragment link.
        # Other query parameters are preserved, but authentication never is.
        query = urlencode([(key, val) for key, val in parse_qsl(
            parts.query, keep_blank_values=True) if key.lower() != "pin"])
        if parts.scheme and parts.netloc and not parts.path:
            base = urlunsplit((parts.scheme, parts.netloc, "/", query, ""))
        else:
            base = urlunsplit((parts.scheme, parts.netloc, parts.path,
                               query, ""))
    except ValueError:
        return ""
    if base and len(value) == 6 and value.isdigit():
        return base + "#pin=" + value
    return base

BASE = os.path.dirname(os.path.abspath(__file__))
EGP = "ج.م"


def _startup_log(msg):
    """v5.1: append one timestamped line to startup.log (never any
    password or PIN — usernames only). This is the first thing to
    read when the app seems to start and then show nothing: the log
    tells exactly which step it reached (login ok? password dialog?
    main window shown?)."""
    try:
        with open(os.path.join(BASE, "startup.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def money(x):
    """v5.9: thousands separators (1,234.56 ج.م) — display only, no logic change."""
    try:
        return "%s %s" % (format(float(x), ",.2f"), EGP)
    except Exception:
        return "0.00 %s" % EGP


def safe_float(v, default=0.0):
    try:
        return float(str(v).strip() or default)
    except Exception:
        return default


def safe_int(v, default=1):
    try:
        return int(float(str(v).strip() or default))
    except Exception:
        return default


def strict_float(v, label="القيمة"):
    """v5.7: like safe_float, but garbage raises a clear Arabic error
    instead of silently becoming 0 — safe_float("abc") used to mean
    a discount of 0 and a paid amount of 0 with no warning."""
    txt = str(v).strip()
    if not txt:
        return None
    try:
        val = float(txt)
    except Exception:
        raise ValueError("%s غير صالحة — أدخل رقماً صحيحاً" % label)
    if val != val or val in (float("inf"), float("-inf")):
        raise ValueError("%s غير صالحة — أدخل رقماً صحيحاً" % label)
    return val


def strict_int(v, label="القيمة"):
    """v5.7: whole numbers only — "2.5" used to be truncated to 2
    by safe_int() with no warning."""
    val = strict_float(v, label)
    if val is None:
        return None
    if val != int(val):
        raise ValueError("%s يجب أن تكون عدداً صحيحاً (بدون كسور)" % label)
    return int(val)


class LoginWindow:
    def __init__(self, db, notice=""):
        self.db = db
        self.user = None
        self.notice = notice
        self.root = tk.Tk()
        self.root.title("تسجيل الدخول — Pharmacy Enterprise")
        self.root.geometry("430x400")
        self.root.resizable(False, False)
        _style = ttk.Style()
        _lpal = ui_theme.apply_theme(
            self.root, _style, ui_theme.get_theme_name(db),
            db.get_setting("ui_accent", "teal"))
        ttk.Label(self.root, text="💊 Pharmacy Enterprise", font=("Segoe UI", 22, "bold")).pack(pady=(16, 2))
        try:
            _pn = db.conn.execute("SELECT value FROM settings WHERE key='pharmacy_name'").fetchone()
            _pname = _pn["value"] if _pn and _pn["value"] else "صيدلية المؤسسة"
        except Exception:
            _pname = "صيدلية المؤسسة"
        ttk.Label(self.root, text=_pname, font=("Segoe UI", 16, "bold"),
                  foreground=_lpal["accent"]).pack(pady=2)
        ttk.Label(self.root, text="نظام إدارة الصيدلية — v6.15", font=("Segoe UI", 12)).pack()
        ttk.Label(self.root, text="لوحة تحكم • كاشير سريع • تنبؤ ذكي",
                  font=("Segoe UI", 10), style="Muted.TLabel").pack(pady=(2, 8))
        ttk.Label(self.root, text="اسم المستخدم").pack(pady=(14, 2))
        self.e_user = ttk.Entry(self.root, width=30, font=("Segoe UI", 12))
        self.e_user.pack()
        ttk.Label(self.root, text="كلمة المرور").pack(pady=(10, 2))
        self.e_pass = ttk.Entry(self.root, width=30, show="*", font=("Segoe UI", 12))
        self.e_pass.pack()
        self.e_pass.bind("<Return>", lambda e: self.try_login())
        ttk.Button(self.root, text="دخول", command=self.try_login,
                   style="Accent.TButton").pack(pady=18)
        ttk.Label(self.root, text="أول دخول بكلمة مرور افتراضية يطلب تغييرها فوراً — لا تشارك كلمة مرورك مع أحد",
                  font=("Segoe UI", 9), style="Muted.TLabel", wraplength=360).pack()
        # v5.1: notice line (e.g. after cancelling the forced password
        # change) — shown in red so a return to the login screen is
        # never mistaken for a silent failure.
        self.lbl_notice = tk.Label(self.root, text=self.notice, fg="#b00020",
                                   font=("Segoe UI", 10, "bold"), wraplength=360,
                                   justify="center")
        if self.notice:
            self.lbl_notice.pack(pady=(10, 0))
        self.e_user.focus_set()

    def _show_notice(self, text):
        try:
            self.lbl_notice.config(text=text)
            self.lbl_notice.pack(pady=(10, 0))
        except Exception:
            pass

    def try_login(self):
        username = self.e_user.get().strip()
        entered = self.e_pass.get()
        u = self.db.authenticate(username, entered)
        if u:
            _startup_log("login ok: user=%s role=%s" % (u["username"], u.get("role", "")))
            # v5.1 ROOT-CAUSE FIX: the forced password change used to
            # run AFTER this window was destroyed, as a Toplevel of a
            # second, WITHDRAWN Tk() — that dialog never maps (measured
            # 1x1+0+0, not viewable, not mapped), its grab_set +
            # wait_window() then blocks the whole app forever with no
            # window on screen. The dialog now opens HERE, parented to
            # this VISIBLE login window, before it is destroyed.
            # Equivalence note: authentication just succeeded with the
            # password the user typed, so "typed password is a factory
            # default" is exactly "current password is a factory
            # default". The helper re-checks the stored hash (cheap
            # PBKDF2 verifies) so no literal default password appears
            # in the login flow.
            # v6.2: enforced for BOTH factory-default users (admin
            # AND cashier) — db.is_default_password() checks the
            # stored hash against both defaults. (Before: the literal
            # check `entered in ("admin123", "cashier123")` — same
            # effect, but the helper is the single source of truth.)
            if self.db.is_default_password(u["username"]):
                _startup_log("forced password change dialog opening for %s" % u["username"])
                # v5.3: the dialog gets the old password FROM THIS LOGIN
                # (the password just typed and just authenticated) — the
                # user is NOT asked to type it again. Only the new
                # password (twice) is asked for.
                try:
                    ok = force_password_change_dialog(self.root, self.db, u,
                                                      old_password=entered)
                except Exception as e:
                    _startup_log("forced password change dialog ERROR: %r" % (e,))
                    messagebox.showerror("خطأ", "تعذّر فتح نافذة تغيير كلمة المرور (%s).\nأعد المحاولة." % e,
                                         parent=self.root)
                    self.e_pass.delete(0, "end")
                    self.e_pass.focus_set()
                    return
                _startup_log("forced password change dialog closed ok=%s" % ok)
                if not ok:
                    # v5.1: NEVER leave a dead hidden process. Closing /
                    # cancelling returns to this visible login screen
                    # with a clear message — the user is not locked out
                    # of their own data and can change the password on
                    # the next attempt.
                    self._show_notice("لم يتم تغيير كلمة المرور الافتراضية —\n"
                                      "يجب تغييرها قبل الدخول.")
                    messagebox.showinfo("تنبيه", "لم يتم تغيير كلمة المرور الافتراضية.\n"
                                        "سجّل الدخول مرة أخرى وغيّرها قبل الاستخدام.",
                                        parent=self.root)
                    self.e_pass.delete(0, "end")
                    self.e_pass.focus_set()
                    return
            self.user = u
            self.root.destroy()
        else:
            # v5.0: failed logins are audited (was silent) — a wrong
            # password shows an Arabic error, never a crash.
            try:
                self.db.audit(self.e_user.get().strip() or "?",
                              "login_failed", "wrong password")
            except Exception:
                pass
            messagebox.showerror("خطأ", "اسم المستخدم أو كلمة المرور غير صحيحة")

    def run(self):
        self.root.mainloop()
        return self.user


def force_password_change_dialog(root, db, user, old_password=None):
    """v5.0/v5.1/v5.3: first login with a factory default password
    (admin123 / cashier123) must change it before using the app.
    Returns True only when the password was actually changed.
    Closing / cancelling means NOT entering — the caller returns to
    the visible login screen (never a hidden process).

    v5.3: the OLD password is NOT asked for here. It comes from the
    login itself: the caller passes the password the user JUST typed
    and JUST authenticated with (`old_password`), and it is verified
    internally against the stored hash. The dialog asks ONLY for the
    new password (twice). `old_password` is kept in memory only and
    is NEVER logged. Do NOT reuse this shortcut for the voluntary
    Settings change-password dialog — there the user must type the
    current password (see App.change_password_dialog).

    v5.1: `root` MUST be a visible window (the login window). In v5.0
    this dialog was a Toplevel of a second, withdrawn Tk() and never
    mapped on screen (1x1+0+0, not viewable) while grab_set +
    wait_window() blocked the app forever — that was the "app hidden,
    nothing appeared" bug. Do not call it with a withdrawn parent."""
    changed = {"ok": False}
    win = tk.Toplevel(root)
    win.title("غيّر كلمة المرور الافتراضية")
    win.geometry("460x330")
    win.resizable(False, False)
    try:
        win.transient(root)
    except Exception:
        pass
    try:
        win.grab_set()
    except Exception:
        pass
    ttk.Label(win, text="⚠️ كلمة مرور افتراضية", font=("Segoe UI", 14, "bold")).pack(pady=12)
    ttk.Label(win, text="أنت تدخل بكلمة المرور الافتراضية للبرنامج.\n"
                        "لحماية بيانات الصيدلية، يجب تغييرها الآن قبل الاستخدام.",
              wraplength=400, justify="center").pack(pady=4)
    ents = {}
    for key, lbl in [("new", "كلمة المرور الجديدة (8 أحرف على الأقل)"),
                     ("confirm", "تأكيد كلمة المرور الجديدة")]:
        ttk.Label(win, text=lbl).pack(anchor="w", padx=20, pady=(8, 0))
        e = ttk.Entry(win, width=36, show="*")
        e.pack(padx=20)
        ents[key] = e
    ents["new"].focus_set()

    def save():
        # v5.3: verify the old password INTERNALLY — it is the password
        # from the login that just succeeded, not a field the user
        # typed here. If it no longer matches (should not happen),
        # refuse and send the user back to log in again.
        from database import _verify_password
        if old_password is None:
            messagebox.showerror("خطأ", "تعذّر التحقق من كلمة المرور — سجّل الدخول مرة أخرى", parent=win)
            return
        row = db.conn.execute(
            "SELECT password_hash FROM users WHERE username=?",
            (user["username"],)).fetchone()
        if not row or not _verify_password(old_password, row["password_hash"]):
            messagebox.showerror("خطأ", "تعذّر التحقق من كلمة المرور — سجّل الدخول مرة أخرى", parent=win)
            return
        new = ents["new"].get()
        if len(new) < 8:
            messagebox.showerror("خطأ", "كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل", parent=win)
            return
        if new != ents["confirm"].get():
            messagebox.showerror("خطأ", "تأكيد كلمة المرور لا يطابق كلمة المرور الجديدة", parent=win)
            return
        # v6.2: the new password must not BE a factory default again
        # (admin123 / cashier123) — otherwise the next login would
        # force another change and the default would never really go.
        if new in ("admin123", "cashier123"):
            messagebox.showerror("خطأ", "كلمة المرور الجديدة لا يمكن أن تكون كلمة المرور الافتراضية — اختر كلمة مرور مختلفة", parent=win)
            return
        db.change_password(user["username"], new)
        db.audit(user["username"], "change_password", "forced default change")
        changed["ok"] = True
        messagebox.showinfo("تم", "تم تغيير كلمة المرور — احتفظ بها في مكان آمن", parent=win)
        win.destroy()

    ttk.Button(win, text="💾 تغيير كلمة المرور", command=save,
               style="Accent.TButton").pack(pady=(16, 4))
    # v5.1: a visible Cancel — closing the dialog is an explicit
    # choice that returns to the login screen, not a dead end.
    ttk.Button(win, text="إلغاء — الرجوع لتسجيل الدخول",
               command=win.destroy).pack(pady=4)
    ttk.Label(win, text="إغلاق هذه النافذة يعيدك لتسجيل الدخول — لن تدخل البرنامج\n"
                        "بكلمة المرور الافتراضية.",
              font=("Segoe UI", 9), style="Muted.TLabel",
              wraplength=400, justify="center").pack(pady=4)
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    # v5.1: centre on screen and force to the front — the dialog must
    # be impossible to miss. (In v5.0 it was never mapped at all.)
    try:
        win.update_idletasks()
        w, h = 460, 330
        x = max(0, (win.winfo_screenwidth() - w) // 2)
        y = max(0, (win.winfo_screenheight() - h) // 2)
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        win.deiconify()
        win.lift()
        win.focus_force()
    except Exception:
        pass
    try:
        win.wait_window()
    finally:
        try:
            win.grab_release()
        except Exception:
            pass
    return changed["ok"]


class App:
    def __init__(self, root, db, user):
        self.root = root
        self.db = db
        self.user = user
        self.username = user["username"]
        self.role = user["role"]
        self.is_admin = self.role == "admin"
        self.theme_name = ui_theme.get_theme_name(db)
        # v5.9 customization (safe defaults; missing keys fall back)
        self.ui_accent = db.get_setting("ui_accent", "teal") or "teal"
        if self.ui_accent not in ui_theme.ACCENTS: self.ui_accent = "teal"
        self.ui_font_size = db.get_setting("ui_font_size", "normal") or "normal"
        self.ui_font_delta = ui_theme.font_scale_for(self.ui_font_size)
        self.ui_alerts_top = (db.get_setting("ui_alerts_top", "1") or "1") != "0"
        self.ui_dash_cards = db.get_setting("ui_dash_cards", "") or ""
        root.title("Pharmacy Enterprise v6.15 — صيدلية المؤسسة | المستخدم: %s (%s)" %
                   (self.username, "مدير" if self.is_admin else "كاشير"))
        root.geometry("1280x800")
        root.minsize(1100, 650)
        try:
            root.state("zoomed")
        except Exception:
            pass
        style = ttk.Style()
        self.pal = ui_theme.apply_theme(root, style, self.theme_name, self.ui_accent, self.ui_font_delta)
        # ----- top bar (every screen) -----
        self.topbar = tk.Frame(root, bg=self.pal["header_bg"], height=52)
        self.topbar.pack(fill="x")
        self.topbar.pack_propagate(False)
        tk.Label(self.topbar, text="💊 Pharmacy Enterprise",
                 bg=self.pal["header_bg"], fg="#FFFFFF",
                 font=("Segoe UI", 14, "bold")).pack(side="left", padx=12)
        self.lbl_top_pharmacy = tk.Label(self.topbar, text="",
                                         bg=self.pal["header_bg"], fg="#CCFBF1",
                                         font=("Segoe UI", 11))
        self.lbl_top_pharmacy.pack(side="left", padx=6)
        self.lbl_top_user = tk.Label(self.topbar, text="",
                                     bg=self.pal["header_bg"], fg="#FFFFFF",
                                     font=("Segoe UI", 11, "bold"))
        self.lbl_top_user.pack(side="left", padx=12)
        self.lbl_top_shift = tk.Label(self.topbar, text="",
                                      bg=self.pal["header_bg"], fg="#FEF3C7",
                                      font=("Segoe UI", 11))
        self.lbl_top_shift.pack(side="left", padx=6)
        tk.Button(self.topbar, text="❓ اختصارات (F1)", bg=self.pal["header_bg2"],
                  fg="#FFFFFF", font=("Segoe UI", 10, "bold"), relief="flat",
                  command=self.show_shortcuts).pack(side="right", padx=6, pady=8)
        self.btn_theme = tk.Button(self.topbar, text="🌙 داكن" if self.theme_name == "light" else "☀️ فاتح",
                                   bg=self.pal["header_bg2"], fg="#FFFFFF",
                                   font=("Segoe UI", 10, "bold"), relief="flat",
                                   command=self.toggle_theme)
        self.btn_theme.pack(side="right", padx=6, pady=8)
        # ----- status banner (coloured success/error/info) -----
        self.banner = ui_theme.make_banner(root, "جاهز — اختر تبويباً أو ابدأ البيع من الكاشير.", "info", self.theme_name)
        self.banner.pack(fill="x")
        self.cart = []          # POS cart: dicts {drug, pack_level, qty_display}
        self.held = []          # held invoices: list of carts
        self.purchase_lines = []
        self.current_shift = self.db.open_shift_for(self.username)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)
        self.mobile_server = None
        # v6.14: lazy tabs — only the dashboard builds at startup; every
        # other tab is a placeholder frame until first opened, so the
        # app paints fast instead of building 10 tabs of widgets and
        # running their data loads before the window appears. Tab order
        # and indices are unchanged (goto_tab/_on_tab_changed rely on them).
        self._tab_built = {}
        self._tab_builders = {}
        self.build_dashboard()
        self._tab_built[0] = True
        _lazy = [
            ("🛒 الكاشير (POS)", self.build_pos),
            ("📦 المخزون", self.build_inventory),
            ("🧾 المشتريات والموردين", self.build_purchases),
            ("👥 العملاء", self.build_customers),
            ("📊 التقارير", self.build_reports),
            ("💰 الخزنة والورديات", self.build_cash),
            ("⚙️ الإعدادات", self.build_settings),
            ("🤖 التنبؤ الذكي", self.build_ai),
            ("📱 الموبايل والطباعة", self.build_mobile),
        ]
        for _idx, (_title, _builder) in enumerate(_lazy, start=1):
            self._tab_builders[_idx] = _builder
            self.notebook.add(ttk.Frame(self.notebook), text=_title)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        # Thread-safe UI queue: background threads (hotspot / server)
        # must NEVER call Tk methods directly — Python 3.12 raises
        # "main thread is not in main loop". They post callables here
        # and this poller runs them on the main thread every 250ms.
        self._ui_queue = queue.Queue()
        self._ui_poll()
        # v4.2 live update: poll the DB every 3s from the MAIN thread
        # (root.after — never from a background thread) and refresh
        # ONLY when something changed, so the UI never flickers.
        self._live_last_sale_id = 0
        self._live_last_pending = -1
        self._live_last_ok = False
        # v4.3: track mobile-server state so a start/stop refreshes the
        # live QR (and its status line) even with no new sale.
        self._live_last_server_running = None
        # v4.3: QR draw cache — what is currently on the canvas, so the
        # QR is re-encoded ONLY when the URL or server state changes.
        self._qr_drawn_url = None
        self._qr_drawn_running = None
        self._live_poll()
        self.root.bind("<F1>", lambda e: self.show_shortcuts())
        self.root.bind("<F2>", lambda e: self.goto_pos())
        self.update_topbar()
        self.refresh_dashboard()
        self.db.audit(self.username, "login", "role=%s" % self.role)
        # v6.12: فحص تحديثات البرنامج من GitHub في الخلفية عند التشغيل
        self._startup_update_check()
        # v6.13: المهام المجدولة — مزامنة ونسخ احتياطي تلقائي كل 24 ساعة
        import automation
        self._automation = automation.Automation(self.db.path)
        self._automation.start()

    # ---------- thread-safe UI queue ----------
    def _ui_post(self, fn):
        """Post a callable to run on the Tkinter main thread. Safe to
        call from any background thread."""
        self._ui_queue.put(fn)

    def _ui_poll(self):
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            self.root.after(250, self._ui_poll)
        except Exception:
            pass  # root destroyed — stop polling silently

    # ---------- v4.2 live update (3s poll, main thread only) ----------
    def _live_poll(self):
        """Check for new sales / pending phone invoices every 3s.
        Runs on the Tkinter main thread via root.after — it only
        READS the DB (fast) and refreshes the Mobile pending list,
        the Dashboard cards, the POS stock list and the open
        'كل الفواتير' window ONLY when the latest sale id or the
        pending count changed. Also updates the 'آخر تحديث' label
        and the متصل/غير متصل dot on the Mobile tab."""
        try:
            self._live_tick()
        except Exception:
            # v5.0: a failing live poll used to look like "not
            # connected" with no trace. Log each DISTINCT error once.
            try:
                import traceback
                err = traceback.format_exc(limit=3)
                if getattr(self, "_live_last_error", "") != err:
                    self._live_last_error = err
                    with open(os.path.join(BASE, "error.log"), "a", encoding="utf-8") as f:
                        f.write("live_poll %s\n%s\n" % (datetime.now().isoformat(timespec="seconds"), err))
            except Exception:
                pass
        try:
            self.root.after(3000, self._live_poll)
        except Exception:
            pass  # root destroyed — stop polling silently

    def _live_tick(self):
        try:
            row = self.db.conn.execute(
                "SELECT MAX(id) AS m FROM sales").fetchone()
            last_id = row["m"] if row and row["m"] is not None else 0
            pend = self.db.conn.execute(
                "SELECT COUNT(*) AS c FROM sales WHERE source='mobile' "
                "AND status='completed' AND (printed_at IS NULL OR printed_at='')"
            ).fetchone()["c"]
            self._live_last_ok = True
        except Exception:
            self._live_last_ok = False
            self._live_update_status_label()
            return
        changed = (last_id != self._live_last_sale_id
                   or pend != self._live_last_pending)
        self._live_last_sale_id = last_id
        self._live_last_pending = pend
        self._live_update_status_label()
        # v4.3: server start/stop is a change too — refresh the Mobile
        # tab (and the live QR + its status line) even with no new sale.
        # _qr_refresh() itself is cached: it only re-encodes the QR
        # when the URL or server state changed, so this cheap call
        # every 3s never redraws a QR that is already correct.
        try:
            running = (getattr(self, "mobile_server", None) is not None
                       and self.mobile_server.running)
            if running != self._live_last_server_running:
                self._live_last_server_running = running
                changed = True
            if hasattr(self, "qr_canvas"):
                self._qr_refresh()
        except Exception:
            pass
        if not changed:
            return
        # Mobile pending-print list (always refresh on change)
        try:
            self.mobile_refresh()
        except Exception:
            pass
        # Dashboard cards (cheap read, only on change)
        try:
            self.refresh_dashboard()
        except Exception:
            pass
        # POS stock display — only if the POS tab is visible, so a
        # refresh never steals the selection while the user is elsewhere
        try:
            if self.notebook.index("current") == 1:
                self.pos_search_refresh()
        except Exception:
            pass
        # Open "كل الفواتير" window, if any
        try:
            if getattr(self, "_inv_win", None) is not None and self._inv_win.winfo_exists():
                self._inv_refresh()
        except Exception:
            pass

    def _live_update_status_label(self):
        """'آخر تحديث: HH:MM:SS' + 🟢 متصل / 🔴 غير متصل on the Mobile tab."""
        try:
            if not hasattr(self, "lbl_live_update"):
                return
            from datetime import datetime as _dt
            now = _dt.now().strftime("%H:%M:%S")
            if self._live_last_ok:
                self.lbl_live_update.config(
                    text="🟢 متصل — آخر تحديث: %s (كل 3 ثوانٍ)" % now)
            else:
                self.lbl_live_update.config(
                    text="🔴 غير متصل — آخر محاولة: %s" % now)
        except Exception:
            pass

    # ---------- top bar / banner / theme ----------
    def show_banner(self, text, kind="info"):
        try:
            # v5.0: remember the kind so a theme switch doesn't reset
            # a success banner back to blue "info".
            self._banner_kind = kind
            ui_theme.set_banner(self.banner, text, kind, self.theme_name)
        except Exception:
            pass

    def update_topbar(self):
        try:
            row = self.db.conn.execute(
                "SELECT value FROM settings WHERE key='pharmacy_name'").fetchone()
            name = row["value"] if row else "صيدلية المؤسسة"
            self.lbl_top_pharmacy.config(text="|  %s" % name)
            self.lbl_top_user.config(text="👤 %s (%s)" % (
                self.username, "مدير" if self.is_admin else "كاشير"))
            if getattr(self, "current_shift", None):
                self.lbl_top_shift.config(text="🟢 وردية #%d مفتوحة" % self.current_shift["id"])
            else:
                self.lbl_top_shift.config(text="🔴 لا توجد وردية مفتوحة")
        except Exception:
            pass

    def toggle_theme(self):
        self.apply_theme_now("dark" if self.theme_name == "light" else "light")

    def apply_theme_now(self, theme_name, accent=None, font_scale=None):
        # v5.9: accent / font size are optional — old 1-arg calls still work.
        self.theme_name = theme_name
        if accent is not None:
            self.ui_accent = accent if accent in ui_theme.ACCENTS else "teal"
            self.db.set_setting("ui_accent", self.ui_accent)
        if font_scale is not None:
            self.ui_font_delta = int(font_scale)
            self.ui_font_size = {0: "normal", 2: "large", 4: "xlarge"}.get(self.ui_font_delta, "normal")
            self.db.set_setting("ui_font_size", self.ui_font_size)
        ui_theme.set_theme_name(self.db, theme_name)
        self.pal = ui_theme.apply_theme(self.root, ttk.Style(), theme_name, self.ui_accent, self.ui_font_delta)
        try:
            self.topbar.configure(bg=self.pal["header_bg"])
            for w in (self.lbl_top_pharmacy, self.lbl_top_user, self.lbl_top_shift):
                w.configure(bg=self.pal["header_bg"])
            self.btn_theme.configure(text="🌙 داكن" if theme_name == "light" else "☀️ فاتح",
                                     bg=self.pal["header_bg2"])
            ui_theme.set_banner(self.banner, self.banner.cget("text"),
                                getattr(self, "_banner_kind", "info"), theme_name)
            for fr, _v, _s in getattr(self, "dash_cards", {}).values():
                ui_theme.recolor_card(fr, theme_name)
            for fr, _v, _s in getattr(self, "rep_cards", {}).values():
                ui_theme.recolor_card(fr, theme_name)
            for fr, _v, _s in getattr(self, "ai_cards", {}).values():
                ui_theme.recolor_card(fr, theme_name)
            if hasattr(self, "pos_panel"):
                self.pos_panel.configure(bg=self.pal["card_bg"],
                                         highlightbackground=self.pal["border"])
        except Exception:
            pass
        self.refresh_dashboard()
        try:
            self.inv_refresh()
        except Exception:
            pass
        self.show_banner("تم تطبيق المظهر %s ✅" % ("الداكن" if theme_name == "dark" else "الفاتح"), "success")

    def apply_customization(self, accent, font_size_name, dash_cards, alerts_top):
        """v5.9: apply every customization choice from Settings at once."""
        delta = ui_theme.font_scale_for(font_size_name)
        self.apply_theme_now(self.theme_name, accent=accent, font_scale=delta)
        self.ui_dash_cards = ",".join(dash_cards)
        self.db.set_setting("ui_dash_cards", self.ui_dash_cards)
        self.ui_alerts_top = bool(alerts_top)
        self.db.set_setting("ui_alerts_top", "1" if alerts_top else "0")
        self._apply_dash_cards_visibility()
        self._layout_dashboard_bottom()
        self.refresh_dashboard()
        self.show_banner("تم تطبيق التخصيص ✅ — اللون والخط والبطاقات", "success")

    def _dash_visible_cards(self):
        all_keys = ["sales", "profit", "cash", "invoices", "low", "expiry", "critical", "inv_value"]
        if not getattr(self, "ui_dash_cards", ""):
            return set(all_keys)
        chosen = {k.strip() for k in self.ui_dash_cards.split(",") if k.strip()}
        return chosen if chosen else set(all_keys)

    def _apply_dash_cards_visibility(self):
        vis = self._dash_visible_cards()
        for key, (fr, _v, _s) in getattr(self, "dash_cards", {}).items():
            try:
                if key in vis: fr.pack(side="left", fill="both", expand=True, padx=4)
                else: fr.pack_forget()
            except Exception: pass

    def _layout_dashboard_bottom(self):
        """Alerts on top (default) or best-sellers on top, per setting."""
        try:
            for fr in (getattr(self, "dash_alerts_frame", None), getattr(self, "dash_best_frame", None)):
                if fr is not None: fr.pack_forget()
            first, second = (self.dash_alerts_frame, self.dash_best_frame) if self.ui_alerts_top else (self.dash_best_frame, self.dash_alerts_frame)
            first.pack(fill="both", expand=True, padx=10, pady=4)
            second.pack(fill="both", expand=True, padx=10, pady=4)
        except Exception: pass

    def goto_tab(self, index):
        try:
            self._ensure_tab(index)
            self.notebook.select(index)
        except Exception:
            pass

    def goto_pos(self):
        self.goto_tab(1)
        try:
            self.root.after(80, lambda: self.e_barcode.focus_set())
        except Exception:
            pass

    def show_shortcuts(self):
        win = tk.Toplevel(self.root)
        win.title("اختصارات لوحة المفاتيح — F1")
        win.geometry("480x380")
        txt = tk.Text(win, width=56, height=18, font=("Segoe UI", 12))
        txt.pack(fill="both", expand=True, padx=12, pady=12)
        txt.insert("1.0",
            "⌨️ اختصارات البرنامج\n\n"
            "F1  — عرض هذه النافذة\n"
            "F2  — الانتقال للكاشير والتركيز على الباركود\n"
            "F9  — إتمام البيع في الكاشير\n"
            "Enter في خانة الباركود — إضافة الدواء بالباركود\n"
            "ضغطتان على دواء في نتائج البحث — إضافته للفاتورة\n"
            "ضغطتان على دواء في المخزون — عرض تشغيلاته وصلاحياته\n\n"
            "💡 نصائح سريعة:\n"
            "• الباركود رقم تعريف فقط؛ لو غير معروف اربطه مرة واحدة.\n"
            "• البيع يأخذ دائماً من أقرب تشغيلة تنتهي أولاً (FEFO).\n"
            "• خذ نسخة احتياطية من الإعدادات قبل أي تحديث.")
        txt.config(state="disabled")

    def _ensure_tab(self, idx):
        """v6.14: build a tab's real content into its placeholder frame,
        once, the first time the tab is shown. Refresh methods called
        before that (from sales, live poll, other tabs) no-op on their
        hasattr guards; the first open always builds with fresh data."""
        if self._tab_built.get(idx):
            return
        builder = self._tab_builders.get(idx)
        if builder is None:
            return
        self._tab_built[idx] = True  # before building: no re-entry
        frame = self.notebook.nametowidget(self.notebook.tabs()[idx])
        builder(frame)

    def _on_tab_changed(self, event=None):
        try:
            idx = self.notebook.index("current")
            self._ensure_tab(idx)
            if idx == 0:
                self.refresh_dashboard()
            elif idx == 9:
                # v4.3: QR LIVE — draw/refresh the connect-QR as soon as
                # the Mobile tab is opened (mobile_refresh() also calls
                # it via _mobile_update_labels, this makes it explicit).
                self.mobile_refresh()
                self._qr_refresh()
        except Exception:
            pass

    # ---------- Dashboard (first tab) ----------
    def build_dashboard(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="🏠 الرئيسية")
        self.dash_tab = tab
        ttk.Label(tab, text="لوحة التحكم الرئيسية", style="Header.TLabel").pack(
            anchor="w", padx=12, pady=(10, 2))
        self.lbl_dash_date = ttk.Label(tab, text="", style="Muted.TLabel")
        self.lbl_dash_date.pack(anchor="w", padx=12)
        # cards row 1 + row 2
        self.dash_cards = {}
        for row_no, defs in enumerate([
            [("sales", "مبيعات اليوم", "#0F766E"), ("profit", "صافي ربح اليوم", "#15803D"),
             ("cash", "نقدي اليوم", "#1D4ED8"), ("invoices", "فواتير اليوم", "#6D28D9")],
            [("low", "أصناف ناقصة", "#B45309"), ("expiry", "تشغيلات قريبة الانتهاء (30 يوم)", "#B91C1C"),
             ("critical", "طلبات حرجة (التنبؤ)", "#B91C1C"), ("inv_value", "قيمة المخزون (سعر البيع)", "#0F766E")],
        ]):
            rowf = ttk.Frame(tab)
            rowf.pack(fill="x", padx=10, pady=4)
            for key, title, accent in defs:
                fr, val, sub = ui_theme.make_card(rowf, title, "—", "", accent, self.theme_name)
                fr.pack(side="left", fill="both", expand=True, padx=4)
                self.dash_cards[key] = (fr, val, sub)
        self._apply_dash_cards_visibility()
        # quick actions
        acts = ttk.Frame(tab)
        acts.pack(fill="x", padx=10, pady=8)
        ttk.Label(acts, text="إجراءات سريعة:", style="Section.TLabel").pack(side="left", padx=4)
        ttk.Button(acts, text="🛒 بيع جديد (F2)", command=self.goto_pos,
                   style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(acts, text="➕ إضافة دواء",
                   command=lambda: (self.goto_tab(2), self.drug_dialog())).pack(side="left", padx=4)
        ttk.Button(acts, text="📦 المخزون", command=lambda: self.goto_tab(2)).pack(side="left", padx=4)
        ttk.Button(acts, text="🤖 التنبؤ الذكي", command=lambda: self.goto_tab(8)).pack(side="left", padx=4)
        ttk.Button(acts, text="💾 نسخة احتياطية", command=self.do_backup).pack(side="left", padx=4)
        ttk.Button(acts, text="🔄 تحديث اللوحة", command=self.refresh_dashboard).pack(side="left", padx=4)
        # v5.9: bottom is STACKED, alerts FIRST (full width) so a low-stock
        # or near-expiry warning is never hidden beside the best sellers.
        self.dash_alerts_frame = ttk.Frame(tab)
        ttk.Label(self.dash_alerts_frame, text="⚠️ تنبيهات تحتاج انتباهك — أولاً", style="Section.TLabel").pack(anchor="w")
        cols2 = ("kind", "item", "detail")
        self.tree_dash_alerts = ttk.Treeview(self.dash_alerts_frame, columns=cols2, show="headings", height=5)
        for c, t in zip(cols2, ("النوع", "الصنف", "التفاصيل")):
            self.tree_dash_alerts.heading(c, text=t)
            self.tree_dash_alerts.column(c, width=160)
        self.tree_dash_alerts.pack(fill="both", expand=True)
        self.dash_best_frame = ttk.Frame(tab)
        ttk.Label(self.dash_best_frame, text="⚡ الأكثر مبيعاً اليوم", style="Section.TLabel").pack(anchor="w")
        cols = ("name", "units", "total")
        self.tree_dash_best = ttk.Treeview(self.dash_best_frame, columns=cols, show="headings", height=6)
        for c, t in zip(cols, ("الدواء", "الكمية", "الإجمالي")):
            self.tree_dash_best.heading(c, text=t)
            self.tree_dash_best.column(c, width=160)
        self.tree_dash_best.pack(fill="both", expand=True)
        self._layout_dashboard_bottom()
        ui_theme.style_treeview(self.tree_dash_best, self.theme_name)
        ui_theme.style_treeview(self.tree_dash_alerts, self.theme_name)

    def refresh_dashboard(self):
        if not hasattr(self, "dash_cards"):
            return
        try:
            self.lbl_dash_date.config(text="اليوم: %s  •  اضغط على أي بطاقة إجراء للانتقال لتبويبها" % date.today().isoformat())
            r = self.db.report_daily()
            low = self.db.low_stock()
            exp30 = self.db.near_expiry(30)
            _rows, _tc, ts = self.db.report_inventory_value()
            # v6.14: التنبؤ الذكي (طلبات حرجة) يكلف ~1-2 ثانية على كتالوج
            # كبير — لا يعمل أبداً على خيط الواجهة. يُحسب في الخلفية
            # ويُخزن 10 دقائق، والبطاقة تتحدث عند جاهزية النتيجة.
            self._kick_dash_ai()
            crit_text = str(getattr(self, "_dash_crit_count", "…"))
            vals = {
                "sales": money(r["total"]), "profit": money(r["net_profit"]),
                "cash": money(r["cash"]), "invoices": str(r["count"]),
                "low": str(len(low)), "expiry": str(len(exp30)),
                "critical": crit_text, "inv_value": money(ts),
            }
            subs = {
                "sales": "كارت: %s  •  آجل: %s" % (money(r["card"]), money(r["credit"])),
                "profit": "إجمالي الربح قبل المصروفات: %s  •  مصروفات اليوم: %s" % (money(r["profit"]), money(r["expenses"])),
                "cash": "رصيد أول المدة يظهر في الخزنة",
                "invoices": "فواتير مسجلة اليوم",
                "low": "أقل من الحد الأدنى — راجع المخزون",
                "expiry": "تنتهي خلال 30 يوم — راجع التشغيلات",
                "critical": "مخزون يكفي 3 أيام أو أقل",
                "inv_value": "عدد الأصناف: %d" % len(_rows),
            }
            for key, (fr, val, sub) in self.dash_cards.items():
                val.config(text=vals.get(key, "—"))
                sub.config(text=subs.get(key, ""))
            for i in self.tree_dash_best.get_children():
                self.tree_dash_best.delete(i)
            best = self.db.report_best_sellers()
            if not best:
                self.tree_dash_best.insert("", "end", values=(
                    "لا توجد مبيعات بعد", "—", "أنشئ أول فاتورة من الكاشير"))
            for b in best:
                self.tree_dash_best.insert("", "end", values=(b["trade_en"], b["units"], money(b["total"])))
            ui_theme.stripe_rows(self.tree_dash_best, self.theme_name)
            for i in self.tree_dash_alerts.get_children():
                self.tree_dash_alerts.delete(i)
            for d in low[:8]:
                self.tree_dash_alerts.insert("", "end", values=(
                    "نقص مخزون", d["trade_en"],
                    "المخزون %.1f علبة — الحد الأدنى %s" % (d.get("stock_boxes", 0), d["min_stock"])),
                    tags=("crit",))
            for b in exp30[:8]:
                self.tree_dash_alerts.insert("", "end", values=(
                    "قرب انتهاء", b["trade_en"],
                    "تشغيلة %s تنتهي %s" % (b["batch_no"], b["expiry"])),
                    tags=("warn",))
            if not low and not exp30:
                self.tree_dash_alerts.insert("", "end", values=("✅", "لا توجد تنبيهات", "كل شيء تحت السيطرة"), tags=("ok",))
            self.update_topbar()
        except Exception:
            pass

    def _kick_dash_ai(self):
        """v6.14: حساب «طلبات حرجة» في الخلفية — مرة كل 10 دقائق كحد
        أقصى، ولا يتزامن حسابان. النتيجة تصل للبطاقة عبر طابور الواجهة."""
        if ai_forecast is None:
            self._dash_crit_count = 0
            return
        import time as _t
        now = _t.monotonic()
        if getattr(self, "_dash_ai_running", False):
            return
        if now - getattr(self, "_dash_ai_last", 0.0) < 600:
            return
        self._dash_ai_running = True
        import cloud_sync
        db_path = self.db.path

        def work():
            db = DB(path=db_path, init=False)
            try:
                rl = ai_forecast.generate_reorder_list(
                    db, horizon_days=30, lead_time_days=3, safety_days=2)
                return len([x for x in rl if x.get("urgency") == "حرجة"])
            finally:
                db.close()

        def done(result, error):
            def ui():
                self._dash_ai_running = False
                self._dash_ai_last = _t.monotonic()
                if error is None and result is not None:
                    self._dash_crit_count = result
                    card = self.dash_cards.get("critical")
                    if card:
                        card[1].config(text=str(result))
            self._ui_post(ui)

        cloud_sync.run_in_background(work, done)

    # ---------- shared helpers ----------
    def _scrollable_tab(self, title, outer=None):
        """v5.0: one shared scrollable tab (same Canvas+Scrollbar pattern
        as the Mobile tab since v4.4). Returns the INNER frame — all
        existing pack() calls on `tab` keep working unchanged."""
        if outer is None:
            outer = ttk.Frame(self.notebook)
            self.notebook.add(outer, text=title)
        canvas = tk.Canvas(outer, highlightthickness=0)
        vbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_conf(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(inner_id, width=canvas.winfo_width())
        inner.bind("<Configure>", _on_conf)
        canvas.bind("<Configure>", _on_conf)

        def _is_inside(widget):
            w = widget
            while w is not None:
                if w is outer:
                    return True
                w = getattr(w, "master", None)
            return False

        def _on_wheel(e):
            # bind_all fires app-wide — scroll only when the pointer
            # is over this tab (same guard as the Mobile tab, v4.4).
            try:
                if not _is_inside(e.widget):
                    return
                if getattr(e, "delta", 0):
                    canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
                elif getattr(e, "num", None) == 4:
                    canvas.yview_scroll(-3, "units")
                elif getattr(e, "num", None) == 5:
                    canvas.yview_scroll(3, "units")
            except Exception:
                pass
        self.root.bind_all("<MouseWheel>", _on_wheel, add="+")
        self.root.bind_all("<Button-4>", _on_wheel, add="+")
        self.root.bind_all("<Button-5>", _on_wheel, add="+")
        return inner

    def drug_label(self, d):
        # v6.3: name + concentration + pharmaceutical form, so
        # "ivrrond 250 syrup" is distinguishable from other forms.
        # v6.4: kept for tests / single-line contexts only — the
        # search lists no longer show this mashed one-line format.
        _sf = " ".join(x for x in (d.get("strength", ""), d.get("form", "")) if x)
        return "%s — %s (%s) | %s | المخزون: %.1f علبة" % (
            d["trade_en"], d.get("trade_ar", ""), _sf,
            money(d["sell_price"]), d.get("stock_boxes", 0))

    # ---------- v6.4: Excel-style drug search tables ----------
    # The old POS / purchase search showed each drug as ONE mashed
    # text line ("Antinal — أنتينال (200 mg Capsules) | 45.00 علبة
    # 0.0 المخزون: ج.م") where Arabic/English, numbers and units ran
    # into each other. Search results are now a ttk.Treeview table —
    # one field per column, like Excel / the Inventory table — with
    # sortable headers, alternating rows and scrollbars.
    SEARCH_COLS = ("name", "ar", "strength", "form", "box", "strip", "pill", "stock")
    SEARCH_HEADS = {"name": "الدواء", "ar": "عربي", "strength": "التركيز",
                    "form": "الشكل", "box": "سعر العلبة", "strip": "سعر الشريط",
                    "pill": "سعر الحبة", "stock": "المخزون (علبة)"}
    SEARCH_WIDTHS = {"name": 150, "ar": 95, "strength": 75, "form": 75,
                     "box": 85, "strip": 85, "pill": 85, "stock": 90}

    def drug_search_values(self, d):
        """One value per column for a drug search row."""
        allowed = set(allowed_units(d))
        return (d["trade_en"], d.get("trade_ar", ""), d.get("strength", ""),
                d.get("form", ""), money(unit_price(d, "box")),
                money(unit_price(d, "strip")) if "strip" in allowed else "—",
                money(unit_price(d, "pill")) if "pill" in allowed else "—",
                "%.1f" % d.get("stock_boxes", 0))

    def make_drug_search_tree(self, parent, height=8):
        """Build a framed Treeview search table + scrollbars.
        Returns (frame, tree). Row iid is the row index, so the
        selected drug is _search_results[int(iid)]."""
        frame = ttk.Frame(parent)
        tree = ttk.Treeview(frame, columns=self.SEARCH_COLS, show="headings", height=height)
        for c in self.SEARCH_COLS:
            tree.heading(c, text=self.SEARCH_HEADS[c],
                         command=lambda col=c: self._sort_search_tree(tree, col))
            tree.column(c, width=self.SEARCH_WIDTHS[c],
                        anchor="e" if c in ("box", "strip", "pill", "stock") else "w")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        ui_theme.style_treeview(tree, self.theme_name)
        tree._search_results = []
        tree._sort_col = None
        tree._sort_rev = False
        return frame, tree

    def _render_search_tree(self, tree):
        for i in tree.get_children():
            tree.delete(i)
        for idx, d in enumerate(tree._search_results):
            tag = "crit" if d.get("stock_boxes", 0) <= 0 else ("even" if idx % 2 == 0 else "odd")
            tree.insert("", "end", iid=str(idx),
                        values=self.drug_search_values(d), tags=(tag,))
        ui_theme.style_treeview(tree, self.theme_name)

    def fill_drug_search_tree(self, tree, results):
        """Show `results` in the table (resets any column sorting)."""
        tree._search_results = list(results)
        tree._sort_col = None
        tree._sort_rev = False
        self._render_search_tree(tree)

    def selected_search_drug(self, tree):
        """The drug of the selected table row, or None."""
        sel = tree.selection()
        if not sel:
            return None
        try:
            return tree._search_results[int(sel[0])]
        except (IndexError, TypeError, ValueError):
            return None

    def _sort_search_tree(self, tree, col):
        rows = getattr(tree, "_search_results", None)
        if not rows:
            return
        rev = (not tree._sort_rev) if tree._sort_col == col else False
        if col == "name":
            key = lambda d: str(d["trade_en"]).lower()
        elif col == "ar":
            key = lambda d: str(d.get("trade_ar", ""))
        elif col == "strength":
            key = lambda d: str(d.get("strength", ""))
        elif col == "form":
            key = lambda d: str(d.get("form", ""))
        elif col in ("box", "strip", "pill"):
            key = lambda d, c=col: unit_price(d, c)
        elif col == "stock":
            key = lambda d: d.get("stock_boxes", 0)
        else:
            key = lambda d: str(d["trade_en"]).lower()
        rows.sort(key=key, reverse=rev)
        tree._sort_col = col
        tree._sort_rev = rev
        self._render_search_tree(tree)

    def _line_disc_amount(self, drug, pack_level, qty, mode="auto", per_unit=None):
        """v6.3: total line discount for one cart line. 'auto' = the
        drug's own default discount; 'manual' = a per-unit amount
        the cashier set for this line (scales with qty)."""
        try:
            q = float(qty or 0)
        except (TypeError, ValueError):
            return 0.0
        if q <= 0:
            return 0.0
        if mode == "manual" and per_unit is not None:
            return round(float(per_unit) * q + 1e-9, 2)
        return drug_default_line_discount(drug, unit_price(drug, pack_level), q)

    def refresh_pos_totals(self):
        # v5.8: held (pending-deletion) lines are NOT counted in the
        # totals until the sale is completed — they are only hidden
        # from the bill, not deleted, until then.
        # v6.3: subtotal is NET of per-line drug discounts; the
        # sale-level discount (e_discount) is applied on top.
        sub = sum(unit_price(it["drug"], it["pack_level"]) * float(it["qty_display"])
                  - float(it.get("discount") or 0)
                  for it in self.cart if not it.get("held"))
        disc = safe_float(self.e_discount.get())
        total = max(0.0, sub - disc)
        self.lbl_subtotal.config(text="المجموع الفرعي: %s" % money(sub))
        self.lbl_total.config(text="الإجمالي: %s" % money(total))
        if hasattr(self, "lbl_change"):
            paid_txt = self.e_paid.get().strip() if hasattr(self, "e_paid") else ""
            if paid_txt:
                change = safe_float(paid_txt, 0.0) - total
                self.lbl_change.config(text="الباقي للعميل: %s" % money(change) if change >= 0
                                       else "⚠️ المدفوع أقل من الإجمالي بـ %s" % money(-change))
            else:
                self.lbl_change.config(text="الباقي للعميل: —")
        return sub, total

    def cart_tree_refresh(self):
        for i in self.tree_cart.get_children():
            self.tree_cart.delete(i)
        for it in self.cart:
            d = it["drug"]
            up = unit_price(d, it["pack_level"])
            held = bool(it.get("held"))
            _ld = float(it.get("discount") or 0)
            self.tree_cart.insert("", "end", values=(
                ("⏳ محذوف مؤقتاً — " + d["trade_en"]) if held else d["trade_en"],
                d.get("trade_ar", ""), it["pack_level"],
                it["qty_display"], money(up), money(_ld),
                money(up * float(it["qty_display"]) - _ld),
                "%.1f" % d.get("stock_boxes", 0)),
                tags=("held",) if held else ())
        ui_theme.stripe_rows(self.tree_cart, self.theme_name)
        self.refresh_pos_totals()

    # ---------- POS ----------
    def build_pos(self, tab=None):
        if tab is None:
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text="🛒 الكاشير (POS)")
        # Big scan / search bar at the top
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(top, text="🔎 باركود / بحث:", font=("Segoe UI", 13, "bold")).pack(side="left")
        self.e_barcode = ttk.Entry(top, width=30, font=("Segoe UI", 16))
        self.e_barcode.pack(side="left", padx=6)
        self.e_barcode.bind("<Return>", lambda e: self.pos_scan())
        ttk.Button(top, text="إضافة بالباركود", command=self.pos_scan,
                   style="Accent.TButton").pack(side="left", padx=4)
        ttk.Label(top, text="بحث بالاسم / المادة الفعالة:").pack(side="left", padx=(14, 2))
        self.e_search = ttk.Entry(top, width=22, font=("Segoe UI", 12))
        self.e_search.pack(side="left")
        self.e_search.bind("<KeyRelease>", lambda e: self.pos_search_refresh())
        ttk.Button(top, text="بحث", command=self.pos_search_refresh).pack(side="left", padx=4)
        ttk.Label(tab, text="F2 للانتقال للباركود  •  F9 لإتمام البيع  •  F1 للاختصارات  •  اضغط مرتين على الدواء لإضافته للفاتورة",
                  style="Muted.TLabel").pack(anchor="w", padx=12)

        mid = ttk.Frame(tab)
        # v5.0: mid is packed AFTER the totals panel (see below) so the
        # panel always gets its full height and mid takes the rest —
        # packing mid first let it swallow the panel's second row.
        self._pos_mid = mid
        left = ttk.Frame(mid)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="نتائج البحث (اضغط مرتين للإضافة):",
                  style="Section.TLabel").pack(anchor="w")
        # v6.4: Excel-style table, not a mashed one-line Listbox.
        _sf, self.list_search = self.make_drug_search_tree(left, height=8)
        _sf.pack(fill="both", expand=True)
        self.list_search.bind("<Double-Button-1>", lambda e: self.pos_add_selected())
        self.list_search.bind("<Return>", lambda e: self.pos_add_selected())
        ttk.Button(left, text="➕ إضافة المحدد للفاتورة", command=self.pos_add_selected,
                   style="Accent.TButton").pack(pady=6, anchor="w")
        self.lbl_alt = ttk.Label(left, text="بدائل بنفس المادة الفعالة تظهر هنا عند اختيار دواء.",
                                 wraplength=460, style="Muted.TLabel", font=("Segoe UI", 11))
        self.lbl_alt.pack(anchor="w", pady=4)
        unit_row = ttk.Frame(left)
        unit_row.pack(fill="x", pady=6)
        ttk.Label(unit_row, text="وحدة البيع:", font=("Segoe UI", 11, "bold")).pack(side="left")
        self.var_unit = tk.StringVar(value="box")
        ttk.Radiobutton(unit_row, text="علبة (Box)", variable=self.var_unit, value="box").pack(side="left")
        ttk.Radiobutton(unit_row, text="شريط (Strip)", variable=self.var_unit, value="strip").pack(side="left")
        ttk.Radiobutton(unit_row, text="حبة (Pill)", variable=self.var_unit, value="pill").pack(side="left")
        ttk.Label(unit_row, text="الكمية:", font=("Segoe UI", 11, "bold")).pack(side="left", padx=(12, 2))
        self.e_qty = ttk.Entry(unit_row, width=6, font=("Segoe UI", 12))
        self.e_qty.pack(side="left")
        self.e_qty.insert(0, "1")

        right = ttk.Frame(mid)
        right.pack(side="right", fill="both", expand=True, padx=(12, 0))
        ttk.Label(right, text="فاتورة البيع الحالية:", style="Section.TLabel").pack(anchor="w")
        cols = ("name", "ar", "unit", "qty", "price", "disc", "total", "stock")
        self.tree_cart = ttk.Treeview(right, columns=cols, show="headings", height=9)
        for c, w in zip(cols, (150, 100, 60, 50, 80, 70, 90, 70)):
            self.tree_cart.heading(c, text={"name": "الدواء", "ar": "عربي", "unit": "الوحدة",
                                            "qty": "الكمية", "price": "سعر الوحدة",
                                            "disc": "خصم السطر", "total": "الإجمالي",
                                            "stock": "المخزون"}[c])
            self.tree_cart.column(c, width=w)
        self.tree_cart.pack(fill="both", expand=True)
        self.tree_cart.tag_configure("held", foreground="#9CA3AF")
        ui_theme.style_treeview(self.tree_cart, self.theme_name)
        btns = ttk.Frame(right)
        btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="💸 خصم السطر", command=self.pos_line_discount_dialog).pack(side="left", padx=2)
        ttk.Button(btns, text="🗑 حذف السطر المحدد", command=self.pos_remove_line).pack(side="left", padx=2)
        ttk.Button(btns, text="↩ استرجاع السطر المحذوف", command=self.pos_restore_line).pack(side="left", padx=2)
        ttk.Button(btns, text="مسح الفاتورة", command=self.pos_clear_cart).pack(side="left", padx=2)
        ttk.Button(btns, text="⏸ تعليق الفاتورة (Hold)", command=self.pos_hold).pack(side="left", padx=2)
        ttk.Button(btns, text="↩ استدعاء فاتورة معلقة", command=self.pos_recall).pack(side="left", padx=2)

        # Total panel — huge, always visible. v5.0: TWO rows — the old
        # single row was 1689px wide in a 1244px tab, so Tk squeezed
        # "إتمام البيع" and "عرض الإيصال" to 1px (invisible) at 1280x800.
        panel = tk.Frame(tab, bg=self.pal["card_bg"], highlightbackground=self.pal["border"],
                         highlightthickness=1, padx=12, pady=10)
        panel.pack(fill="x", padx=10, pady=(4, 10))
        self.pos_panel = panel
        row1 = ttk.Frame(panel, style="Card.TFrame")
        row1.pack(fill="x")
        ttk.Label(row1, text="العميل:", style="Card.TLabel").pack(side="left")
        self.var_customer = tk.StringVar(value="عميل نقدي")
        self.cb_customer = ttk.Combobox(row1, textvariable=self.var_customer, width=20,
                                        values=["عميل نقدي"] + [c["name"] for c in self.db.customers()])
        self.cb_customer.pack(side="left", padx=4)
        ttk.Label(row1, text="خصم (ج.م):", style="Card.TLabel").pack(side="left", padx=(10, 2))
        self.e_discount = ttk.Entry(row1, width=8, font=("Segoe UI", 12))
        self.e_discount.pack(side="left")
        self.e_discount.insert(0, "0")
        self.e_discount.bind("<KeyRelease>", lambda e: self.refresh_pos_totals())
        ttk.Label(row1, text="طريقة الدفع:", style="Card.TLabel").pack(side="left", padx=(10, 2))
        self.var_pay = tk.StringVar(value="cash")
        ttk.Radiobutton(row1, text="نقدي", variable=self.var_pay, value="cash", style="Card.TRadiobutton").pack(side="left")
        ttk.Radiobutton(row1, text="فيزا / كارت", variable=self.var_pay, value="card", style="Card.TRadiobutton").pack(side="left")
        ttk.Radiobutton(row1, text="آجل (عميل)", variable=self.var_pay, value="credit", style="Card.TRadiobutton").pack(side="left")
        ttk.Label(row1, text="المدفوع:", style="Card.TLabel").pack(side="left", padx=(10, 2))
        self.e_paid = ttk.Entry(row1, width=10, font=("Segoe UI", 12))
        self.e_paid.pack(side="left")
        self.e_paid.bind("<KeyRelease>", lambda e: self.refresh_pos_totals())
        totals = ttk.Frame(row1, style="Card.TFrame")
        totals.pack(side="left", padx=14)
        self.lbl_subtotal = ttk.Label(totals, text="المجموع الفرعي: 0.00 ج.م", style="CardMuted.TLabel")
        self.lbl_subtotal.pack(anchor="w")
        self.lbl_total = ttk.Label(totals, text="الإجمالي: 0.00 ج.م", style="CardHuge.TLabel")
        self.lbl_total.pack(anchor="w")
        self.lbl_change = ttk.Label(totals, text="الباقي للعميل: —", style="CardChange.TLabel")
        self.lbl_change.pack(anchor="w")
        row2 = ttk.Frame(panel, style="Card.TFrame")
        row2.pack(fill="x", pady=(8, 0))
        ttk.Button(row2, text="✅ إتمام البيع (F9)", command=self.pos_complete_sale,
                   style="Success.TButton").pack(side="left", padx=4)
        ttk.Button(row2, text="🧾 عرض الإيصال", command=self.pos_show_receipt).pack(side="left", padx=4)
        ttk.Label(row2, text="F9 لإتمام البيع  •  الباقي يظهر فوراً أثناء الكتابة",
                  style="CardMuted.TLabel").pack(side="left", padx=12)
        # v5.0: F9 only completes a sale when the POS tab is current —
        # before, it fired on every tab and popped "الفاتورة فارغة".
        self.root.bind("<F9>", lambda e: self._f9_complete_sale())
        # v5.0: pack the middle (expanding) area last — after the panel
        # — so the panel keeps its full two-row height at 1280x800.
        mid.pack(fill="both", expand=True, padx=10)
        self.pos_search_refresh()
        self.e_barcode.focus_set()

    def _f9_complete_sale(self):
        try:
            if self.notebook.index("current") != 1:
                return
        except Exception:
            pass
        self.pos_complete_sale()

    def pos_search_refresh(self):
        if not hasattr(self, "list_search"):
            return  # v6.14: الكاشير لم يُبن بعد
        q = self.e_search.get()
        self.search_results = self.db.search_drugs(q, limit=60)
        self.fill_drug_search_tree(self.list_search, self.search_results)
        if not self.search_results:
            # v6.4: the "no results" message is a row inside the
            # table itself (a label packed under the table was
            # squeezed to 1px by the pack layout). Its iid is not a
            # number, so selecting it returns None — a safe no-op.
            self.list_search.insert("", "end", iid="empty",
                                    values=("لا توجد نتائج مطابقة.", "", "", "",
                                            "", "", "", ""), tags=("odd",))

    def pos_scan(self):
        code = self.e_barcode.get().strip()
        if not code:
            return
        drug, pack = self.db.lookup_barcode(code)
        self.e_barcode.delete(0, "end")
        if not drug:
            self.unknown_barcode_dialog(code)
            return
        self.pos_add_drug(drug, pack or "box", 1)
        self.e_barcode.focus_set()

    def pos_add_selected(self):
        drug = self.selected_search_drug(self.list_search)
        if not drug:
            messagebox.showinfo("تنبيه", "اختر دواء من نتائج البحث أولاً")
            return
        self.pos_add_drug(drug, self.var_unit.get(), safe_int(self.e_qty.get(), 1))
        # v5.0: focus back to the barcode box so the next scan works
        self.e_barcode.focus_set()
        alts = self.db.alternatives(drug)
        if alts:
            txt = "بدائل بنفس المادة الفعالة (%s): " % drug["scientific"]
            txt += " | ".join("%s %s" % (a["trade_en"], money(a["sell_price"])) for a in alts[:5])
            self.lbl_alt.config(text=txt)
        else:
            self.lbl_alt.config(text="لا توجد بدائل مسجلة بنفس المادة الفعالة.")

    def pos_add_drug(self, drug, pack_level, qty):
        # v5.0: reject impossible quantities at the POS boundary
        if pack_level not in allowed_units(drug):
            messagebox.showwarning(
                "وحدة غير متاحة",
                "الوحدة المختارة غير متاحة للشكل الصيدلاني: %s" % (drug.get("form") or "غير محدد"))
            return
        if qty is None or float(qty) <= 0:
            messagebox.showwarning("كمية غير صالحة", "الكمية يجب أن تكون أكبر من صفر")
            return
        if pack_level in ("box", "strip") and float(qty) != int(float(qty)):
            messagebox.showwarning("كمية غير صالحة", "كمية العلبة / الشريط يجب أن تكون عدداً صحيحاً")
            return
        if drug.get("stock_units", 0) < units_for_qty(drug, pack_level, qty):
            messagebox.showwarning("مخزون غير كافٍ",
                                   "المخزون المتاح من %s غير كافٍ لهذه الكمية." % drug["trade_en"])
            return
        for it in self.cart:
            if it["drug"]["id"] == drug["id"] and it["pack_level"] == pack_level:
                # v5.8: adding the same drug back restores a held line.
                it["held"] = False
                it["qty_display"] = float(it["qty_display"]) + float(qty)
                # v6.3: recompute an AUTO discount for the new qty;
                # a cashier-set (manual) discount keeps its per-unit rate.
                if it.get("disc_mode", "auto") == "auto":
                    it["discount"] = self._line_disc_amount(
                        drug, pack_level, it["qty_display"], "auto")
                else:
                    it["discount"] = self._line_disc_amount(
                        drug, pack_level, it["qty_display"], "manual",
                        it.get("disc_per_unit"))
                break
        else:
            self.cart.append({"drug": drug, "pack_level": pack_level, "qty_display": float(qty),
                              "held": False, "disc_mode": "auto",
                              "discount": self._line_disc_amount(drug, pack_level, qty, "auto")})
        self.cart_tree_refresh()
        # v5.0: reset qty to 1 — the old value silently reused itself
        try:
            self.e_qty.delete(0, "end")
            self.e_qty.insert(0, "1")
        except Exception:
            pass

    def pos_remove_line(self):
        """v5.8: deleting a cart line does NOT remove it — it is HELD
        (greyed, struck through, excluded from the total) until the
        sale is completed (approve) or the line is restored. No stock
        moves in a POS cart anyway; the point is the line cannot be
        lost by one accidental tap."""
        sel = self.tree_cart.selection()
        if not sel:
            messagebox.showinfo("تنبيه", "اختر سطراً من الفاتورة أولاً")
            return
        idx = self.tree_cart.index(sel[0])
        it = self.cart[idx]
        if it.get("held"):
            messagebox.showinfo("تنبيه", "هذا السطر محذوف مؤقتاً بالفعل — استرجعه بزر «↩ استرجاع السطر المحذوف» أو أكمل البيع لاعتماد الحذف")
            return
        it["held"] = True
        it["held_qty"] = float(it["qty_display"])
        self.cart_tree_refresh()

    def pos_restore_line(self):
        """v5.8: undo a held (pending-deletion) cart line."""
        sel = self.tree_cart.selection()
        if not sel:
            messagebox.showinfo("تنبيه", "اختر سطراً محذوفاً مؤقتاً من الفاتورة أولاً")
            return
        idx = self.tree_cart.index(sel[0])
        it = self.cart[idx]
        if not it.get("held"):
            messagebox.showinfo("تنبيه", "هذا السطر ليس محذوفاً مؤقتاً")
            return
        it["held"] = False
        self.cart_tree_refresh()

    def pos_line_discount_dialog(self):
        """v6.3: change / remove the discount of ONE cart line. The
        drug's default discount is the starting point; the cashier
        may override it for this sale only (percent % or a fixed
        amount per unit), or remove it. The drug's saved default
        is never changed here."""
        sel = self.tree_cart.selection()
        if not sel:
            messagebox.showinfo("تنبيه", "اختر سطراً من الفاتورة أولاً")
            return
        idx = self.tree_cart.index(sel[0])
        it = self.cart[idx]
        if it.get("held"):
            messagebox.showinfo("تنبيه", "هذا السطر محذوف مؤقتاً — استرجعه أولاً")
            return
        d = it["drug"]
        up = unit_price(d, it["pack_level"])
        win = tk.Toplevel(self.root)
        win.title("خصم السطر — %s" % d["trade_en"])
        win.geometry("420x300")
        ttk.Label(win, text="%s — %s — سعر الوحدة: %s" % (
            d["trade_en"], it["pack_level"], money(up)),
            wraplength=380).pack(padx=12, pady=8)
        ttk.Label(win, text="خصم الدواء الافتراضي: %s" % (
            discount_label(d) or "بدون خصم")).pack(anchor="w", padx=12)
        ttk.Label(win, text="نوع الخصم لهذا السطر:").pack(anchor="w", padx=12, pady=(8, 0))
        var_kind = tk.StringVar(value="none")
        ttk.Radiobutton(win, text="بدون خصم", variable=var_kind, value="none").pack(anchor="w", padx=12)
        ttk.Radiobutton(win, text="نسبة % من سعر السطر", variable=var_kind, value="percent").pack(anchor="w", padx=12)
        ttk.Radiobutton(win, text="مبلغ ثابت (ج.م) لكل وحدة", variable=var_kind, value="amount").pack(anchor="w", padx=12)
        ttk.Label(win, text="القيمة:").pack(anchor="w", padx=12, pady=(6, 0))
        e_val = ttk.Entry(win, width=12)
        e_val.pack(anchor="w", padx=12)
        e_val.insert(0, "0")

        def apply_disc():
            kind = var_kind.get()
            try:
                val = float(e_val.get() or 0)
            except ValueError:
                messagebox.showerror("خطأ", "قيمة الخصم غير صالحة")
                return
            if kind == "none" or val <= 0:
                it["discount"] = 0.0
                it["disc_mode"] = "manual"
                it["disc_per_unit"] = 0.0
            elif kind == "percent":
                if val > 100:
                    messagebox.showerror("خطأ", "نسبة الخصم يجب أن تكون بين 0 و 100%")
                    return
                it["disc_per_unit"] = round(up * val / 100.0 + 1e-9, 2)
                it["discount"] = self._line_disc_amount(
                    d, it["pack_level"], it["qty_display"], "manual", it["disc_per_unit"])
                it["disc_mode"] = "manual"
            else:
                if val >= up:
                    messagebox.showerror("خطأ", "المبلغ الثابت يجب أن يكون أقل من سعر الوحدة")
                    return
                it["disc_per_unit"] = val
                it["discount"] = self._line_disc_amount(
                    d, it["pack_level"], it["qty_display"], "manual", val)
                it["disc_mode"] = "manual"
            win.destroy()
            self.cart_tree_refresh()
        ttk.Button(win, text="✅ تطبيق خصم السطر", style="Success.TButton",
                   command=apply_disc).pack(pady=12)

    def pos_clear_cart(self):
        if not self.cart:
            messagebox.showinfo("تنبيه", "الفاتورة فارغة أصلاً")
            return
        if not messagebox.askyesno("مسح الفاتورة", "هل تريد مسح كل أصناف الفاتورة الحالية؟"):
            return
        self.cart = []
        self.cart_tree_refresh()

    def pos_hold(self):
        if not self.cart:
            messagebox.showinfo("تنبيه", "الفاتورة فارغة — لا يوجد ما يتم تعليقه")
            return
        self.held.append([dict(it) for it in self.cart])
        self.cart = []
        self.cart_tree_refresh()
        messagebox.showinfo("تم", "تم تعليق الفاتورة. عدد الفواتير المعلقة: %d" % len(self.held))

    def pos_recall(self):
        if not self.held:
            messagebox.showinfo("تنبيه", "لا توجد فواتير معلقة")
            return
        # v5.7: re-resolve every drug from the DB — a held cart used
        # to keep the price from when it was held, even if the price
        # changed since (or the drug was edited).
        fresh = []
        for it in self.held.pop(0):
            d = None
            try:
                d = self.db.get_drug(it["drug"]["id"])
            except Exception:
                d = None
            fresh.append({"drug": d or it["drug"], "pack_level": it["pack_level"],
                          "qty_display": it["qty_display"], "held": bool(it.get("held"))})
        self.cart = fresh
        self.cart_tree_refresh()

    def _customer_id(self):
        name = self.var_customer.get().strip()
        if not name or name == "عميل نقدي":
            return None
        for c in self.db.customers():
            if c["name"] == name:
                return c["id"]
        return None

    def pos_complete_sale(self):
        # v5.8: held lines are excluded from the completed sale — this
        # is the approval point for their deletion. If every line is
        # held, there is nothing to sell.
        active_cart = [it for it in self.cart if not it.get("held")]
        if not active_cart:
            if self.cart:
                messagebox.showinfo("تنبيه", "كل أصناف الفاتورة محذوفة مؤقتاً — استرجع ما تريده بزر «↩ استرجاع السطر المحذوف» أو أضف صنفاً جديداً")
            else:
                messagebox.showinfo("تنبيه", "الفاتورة فارغة")
            return
        _, total = self.refresh_pos_totals()
        pay = self.var_pay.get()
        cust_id = self._customer_id()
        try:
            disc = strict_float(self.e_discount.get(), "الخصم")
            disc = disc if disc is not None else 0.0
            paid_txt = self.e_paid.get().strip()
            paid_entered = strict_float(paid_txt, "المبلغ المدفوع") if paid_txt else None
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        if pay == "credit":
            if not cust_id:
                messagebox.showerror("خطأ", "البيع الآجل يحتاج عميل مسجل — اختر عميل من القائمة أو أضفه من تبويب العملاء")
                return
            # v5.7: a credit sale records what the customer actually
            # hands over NOW (0 if nothing) — it used to record
            # paid=total while still adding the full total to the debt.
            paid = paid_entered if paid_entered is not None else 0.0
            cust = [c for c in self.db.customers() if c["id"] == cust_id][0]
            if float(cust["credit_limit"] or 0) > 0 and \
                    float(cust["balance"]) + (total - disc - paid) > float(cust["credit_limit"]):
                messagebox.showerror("خطأ", "العميل وصل لحد الائتمان المسموح")
                return
        else:
            paid = paid_entered if paid_entered is not None else total
            if pay == "cash" and paid < total:
                messagebox.showerror("خطأ", "المبلغ المدفوع أقل من الإجمالي")
                return
        try:
            sale_id, inv, total2, change = self.db.create_sale(
                self.username, active_cart, discount=disc,
                payment_method=pay, customer_id=cust_id, paid=paid,
                shift_id=self.current_shift["id"] if self.current_shift else None)
        except sqlite3.OperationalError:
            # v5.0: a locked DB (phone writing at the same moment) is a
            # retryable moment, not a crash.
            messagebox.showerror("قاعدة البيانات مشغولة",
                                 "قاعدة البيانات مشغولة لحظياً (ربما الهاتف يحفظ فاتورة الآن) — أعد المحاولة بعد ثانية")
            return
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        self.db.audit(self.username, "sale", "%s total %.2f pay=%s" % (inv, total2, pay))
        msg = "تم البيع ✅\nفاتورة: %s\nالإجمالي: %s" % (inv, money(total2))
        if pay == "cash" and change:
            msg += "\nالباقي للعميل: %s" % money(change)
        messagebox.showinfo("تم البيع", msg)
        self.show_banner("✅ " + msg.replace("\n", "  •  "), "success")
        self.last_receipt = (inv, list(active_cart), total2, change, pay)
        self.cart = []
        self.e_discount.delete(0, "end"); self.e_discount.insert(0, "0")
        self.e_paid.delete(0, "end")
        # v5.0: reset the customer — the previous customer used to stay
        # selected and the next walk-in sale could be recorded under them.
        self.var_customer.set("عميل نقدي")
        self.cart_tree_refresh()
        self.pos_search_refresh()
        self.e_barcode.focus_set()

    def pos_show_receipt(self):
        if not getattr(self, "last_receipt", None):
            messagebox.showinfo("تنبيه", "لا يوجد إيصال بعد — أتمم بيع أولاً")
            return
        inv, cart, total, change, pay = self.last_receipt
        lines = ["Pharmacy Enterprise", "فاتورة: %s" % inv, "-" * 34]
        for it in cart:
            up = unit_price(it["drug"], it["pack_level"])
            lines.append("%s x%s @ %s = %s" % (it["drug"]["trade_en"], it["qty_display"],
                                               money(up), money(up * float(it["qty_display"]))))
        lines += ["-" * 34, "الإجمالي: %s" % money(total),
                  "الباقي: %s" % money(change), "شكراً لزيارتك"]
        win = tk.Toplevel(self.root)
        win.title("إيصال %s" % inv)
        txt = tk.Text(win, width=52, height=22, font=("Consolas", 11))
        txt.pack(padx=10, pady=10)
        txt.insert("1.0", "\n".join(lines))
        txt.config(state="disabled")
        # v5.10 (audit step 3): the POS receipt window had NO print
        # button at all — only the mobile receipt window could print.
        ttk.Button(win, text="🖨️ طباعة", style="Success.TButton",
                   command=lambda: self._pos_receipt_print(win, inv, lines, pay)).pack(pady=(0, 10))

    def unknown_barcode_dialog(self, code):
        win = tk.Toplevel(self.root)
        win.title("باركود غير معروف")
        win.geometry("520x420")
        ttk.Label(win, text="الباركود %s غير مسجل في قاعدة البيانات." % code,
                  font=("Segoe UI", 11, "bold"), wraplength=480).pack(pady=10)
        ttk.Label(win, text="الباركود رقم تعريف فقط — لا يحتوي على سعر. اربطه مرة واحدة بدواء موجود، أو أضف دواء جديد بسعره، وبعدها أي سكان لنفس الباركود سيعمل تلقائياً.",
                  wraplength=480).pack(pady=4)
        ttk.Label(win, text="ابحث عن الدواء للربط به:").pack(anchor="w", padx=12)
        e = ttk.Entry(win, width=50)
        e.pack(padx=12, pady=4)
        _bf, lb = self.make_drug_search_tree(win, height=8)
        _bf.pack(fill="both", expand=True, padx=12)
        results = []
        def refresh(ev=None):
            nonlocal results
            results = self.db.search_drugs(e.get(), limit=40)
            self.fill_drug_search_tree(lb, results)
        e.bind("<KeyRelease>", refresh)
        refresh()
        def link():
            drug = self.selected_search_drug(lb)
            if not drug:
                messagebox.showinfo("تنبيه", "اختر دواء أولاً")
                return
            self.db.link_barcode(code, drug["id"])
            self.db.audit(self.username, "link_barcode", "%s -> drug %s" % (code, drug["id"]))
            messagebox.showinfo("تم", "تم ربط الباركود بالدواء")
            win.destroy()
            self.pos_add_drug(drug, "box", 1)
            self.e_barcode.focus_set()
        ttk.Button(win, text="ربط الباركود بالدواء المحدد", command=link).pack(pady=6)
        ttk.Button(win, text="إضافة دواء جديد بهذا الباركود", command=lambda: (win.destroy(), self.drug_dialog(prefill_barcode=code))).pack(pady=4)

    # ---------- Inventory ----------
    def build_inventory(self, tab=None):
        if tab is None:
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text="📦 المخزون")
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="بحث:").pack(side="left")
        self.e_inv_search = ttk.Entry(top, width=30)
        self.e_inv_search.pack(side="left", padx=4)
        self.e_inv_search.bind("<KeyRelease>", lambda e: self.inv_refresh())
        ttk.Button(top, text="تحديث", command=self.inv_refresh).pack(side="left", padx=4)
        ttk.Button(top, text="➕ إضافة دواء", command=lambda: self.drug_dialog()).pack(side="left", padx=4)
        ttk.Button(top, text="✏️ تعديل الدواء المحدد", command=self.drug_edit_selected).pack(side="left", padx=4)
        ttk.Button(top, text="📋 قائمة النواقص", command=self.show_shortages).pack(side="left", padx=4)
        ttk.Button(top, text="⏰ قرب انتهاء الصلاحية", command=self.show_expiry).pack(side="left", padx=4)
        ttk.Button(top, text="🏷️ طباعة ملصق باركود", command=self.barcode_label_dialog).pack(side="left", padx=4)
        # v6.3: concentration (التركيز) + pharmaceutical form (الشكل)
        # + per-drug discount are now visible columns — they were
        # saved in the DB all along but never shown in the list.
        cols = ("id", "name", "ar", "sci", "strength", "form", "disc", "stock", "min", "buy", "sell", "barcode")
        self.tree_inv = ttk.Treeview(tab, columns=cols, show="headings", height=20)
        heads = {"id": "#", "name": "الدواء", "ar": "عربي", "sci": "المادة الفعالة",
                 "strength": "التركيز", "form": "الشكل", "disc": "خصم الدواء",
                 "stock": "المخزون (علبة)", "min": "الحد الأدنى", "buy": "سعر الشراء",
                 "sell": "سعر البيع", "barcode": "باركود"}
        for c in cols:
            self.tree_inv.heading(c, text=heads[c])
            self.tree_inv.column(c, width=110 if c not in ("id", "strength", "form", "disc") else (40 if c == "id" else 80))
        self.tree_inv.pack(fill="both", expand=True, padx=8)
        self.tree_inv.bind("<Double-Button-1>", lambda e: self.show_batches())
        btns = ttk.Frame(tab)
        btns.pack(fill="x", padx=8, pady=6)
        ttk.Button(btns, text="عرض التشغيلات / الصلاحية للدواء المحدد", command=self.show_batches).pack(side="left", padx=4)
        ttk.Button(btns, text="جرد / تعديل كمية (بموافقة المدير)", command=self.adjust_stock_dialog).pack(side="left", padx=4)
        ttk.Button(btns, text="تصدير الأدوية CSV", command=self.export_drugs).pack(side="left", padx=4)
        self.inv_refresh()

    def inv_refresh(self):
        if not hasattr(self, "tree_inv"):
            return  # v6.14: التبويب لم يُبن بعد — يُبنى ببيانات حديثة عند أول فتح
        q = self.e_inv_search.get() if hasattr(self, "e_inv_search") else ""
        for i in self.tree_inv.get_children():
            self.tree_inv.delete(i)
        self.inv_rows = self.db.search_drugs(q, limit=500)
        # v5.0: the barcode column is actually filled now (was hardcoded
        # empty — the barcode lives in the drug_barcode table).
        barcodes = {}
        try:
            for r in self.db.conn.execute(
                    "SELECT drug_id, barcode FROM barcodes WHERE pack_level='box'"):
                barcodes.setdefault(r["drug_id"], r["barcode"])
        except Exception:
            pass
        for d in self.inv_rows:
            bc = barcodes.get(d["id"], "")
            _tag = "crit" if d.get("stock_boxes", 0) <= d["min_stock"] else (
                "warn" if d.get("stock_boxes", 0) <= d["min_stock"] * 1.5 else "odd")
            self.tree_inv.insert("", "end", values=(
                d["id"], d["trade_en"], d.get("trade_ar", ""), d.get("scientific", ""),
                d.get("strength", ""), d.get("form", ""), discount_label(d) or "—",
                "%.1f" % d.get("stock_boxes", 0), d["min_stock"],
                money(d["buy_price"]), money(d["sell_price"]), bc), tags=(_tag,))
        ui_theme.style_treeview(self.tree_inv, self.theme_name)

    def _selected_inv_drug(self):
        sel = self.tree_inv.selection()
        if not sel:
            messagebox.showinfo("تنبيه", "اختر دواء من القائمة أولاً")
            return None
        return self.inv_rows[self.tree_inv.index(sel[0])]

    def barcode_label_dialog(self):
        """v6.3: pharmacy barcode label for the selected drug
        (Inventory tab). Opens the chooser dialog."""
        drug = self._selected_inv_drug()
        if not drug:
            return
        self.barcode_label_dialog_for(drug["id"])

    def barcode_label_dialog_for(self, drug_id):
        """v6.3: print a pharmacy barcode label for one drug.
        The user CHOOSES what goes on the label (drug name,
        pharmacy name, price, pharmacy phone, barcode bars +
        number) — checkboxes + Select all / Clear all — plus
        label size (50x25 / 38x25mm) and number of copies.
        AUTO barcode: if the drug has no GTIN, a unique internal
        EAN-13 is generated (correct GS1 check digit) and SAVED to
        the drug, so it prints the same code next time and scans
        back to this drug. The bars are REAL EAN-13 (GS k on
        ESC/POS, PNG in receipts/ on the Windows path) and the
        number is always printed as text under them."""
        drug = self.db.get_drug(drug_id)
        if not drug:
            messagebox.showerror("خطأ", "الدواء غير موجود")
            return
        # was the barcode just auto-generated? (no barcode before)
        was_auto = not self.db.drug_barcode(drug_id)
        try:
            bc = self.db.ensure_drug_barcode(drug_id)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        pharmacy = self.db.get_setting("pharmacy_name", "صيدلية المؤسسة") or "صيدلية المؤسسة"
        phone = self.db.get_setting("pharmacy_phone", "") or ""
        win = tk.Toplevel(self.root)
        win.title("ملصق باركود الصيدلية — %s" % drug["trade_en"])
        win.geometry("460x640")
        ttk.Label(win, text=drug["trade_en"], font=("Segoe UI", 13, "bold"),
                  wraplength=420).pack(pady=6)
        if drug.get("trade_ar"):
            ttk.Label(win, text=drug["trade_ar"], font=("Segoe UI", 12),
                      wraplength=420).pack()
        _info = "التركيز: %s   الشكل: %s" % (drug.get("strength", "") or "—", drug.get("form", "") or "—")
        ttk.Label(win, text=_info, style="Muted.TLabel").pack(pady=2)
        ttk.Label(win, text="الباركود: %s%s" % (bc, "  (باركود داخلي مولَّد تلقائياً — احفظه، فهو ثابت لهذا الدواء)" if was_auto else ""),
                  font=("Consolas", 12), wraplength=420).pack(pady=4)
        # --- barcode preview: real EAN-13 bars as an image ---
        self._label_preview_img = None
        try:
            import base64 as _b64
            _png = ean13_png_bytes(bc, scale=3, height=56)
            self._label_preview_img = tk.PhotoImage(data=_b64.b64encode(_png).decode("ascii"))
            ttk.Label(win, image=self._label_preview_img, background="white").pack(pady=4)
            ttk.Label(win, text=bc, font=("Consolas", 13)).pack()
        except Exception:
            ttk.Label(win, text="(معاينة الأعمدة غير متاحة — رقم الباركود مطبوع كنص)",
                      style="Muted.TLabel").pack()
        ttk.Label(win, text="اختر ما يظهر على الملصق:", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=16, pady=(10, 2))
        vars_ = {}
        for _key, _lbl in (("name", "اسم الدواء"), ("pharmacy", "اسم الصيدلية"),
                           ("price", "السعر"), ("phone", "تليفون الصيدلية"),
                           ("barcode", "الباركود (أعمدة + رقم)")):
            _v = tk.BooleanVar(value=True)
            vars_[_key] = _v
            ttk.Checkbutton(win, text=_lbl, variable=_v).pack(anchor="w", padx=20)
        _sel_row = ttk.Frame(win)
        _sel_row.pack(fill="x", padx=16, pady=4)
        ttk.Button(_sel_row, text="✅ اختيار الكل",
                   command=lambda: [v.set(True) for v in vars_.values()]).pack(side="left", padx=2)
        ttk.Button(_sel_row, text="❌ إلغاء الكل",
                   command=lambda: [v.set(False) for v in vars_.values()]).pack(side="left", padx=2)
        ttk.Label(win, text="حجم الملصق:").pack(anchor="w", padx=16, pady=(6, 0))
        var_size = tk.StringVar(value="50x25")
        _sz = ttk.Frame(win)
        _sz.pack(anchor="w", padx=16)
        ttk.Radiobutton(_sz, text="50 × 25 مم", variable=var_size, value="50x25").pack(side="left")
        ttk.Radiobutton(_sz, text="38 × 25 مم", variable=var_size, value="38x25").pack(side="left")
        ttk.Label(win, text="عدد النسخ:").pack(anchor="w", padx=16, pady=(6, 0))
        e_copies = ttk.Entry(win, width=6)
        e_copies.pack(anchor="w", padx=16)
        e_copies.insert(0, "1")
        if not phone:
            ttk.Label(win, text="⚠️ لم يُسجَّل تليفون للصيدلية بعد — أضفه من الإعدادات ليظهر على الملصق.",
                      wraplength=420, style="Muted.TLabel").pack(padx=16, pady=4)

        def do_print_label():
            if not any(v.get() for v in vars_.values()):
                messagebox.showerror("خطأ", "اختر عنصراً واحداً على الأقل للملصق")
                return
            try:
                copies = int(e_copies.get() or "1")
            except ValueError:
                messagebox.showerror("خطأ", "عدد النسخ يجب أن يكون رقماً")
                return
            copies = max(1, min(50, copies))
            name = drug["trade_en"] + ((" — " + drug["trade_ar"]) if drug.get("trade_ar") else "")
            price_txt = "السعر: %s" % money(drug["sell_price"])
            extra = []
            if vars_["pharmacy"].get():
                extra.append(pharmacy)
            if vars_["phone"].get() and phone:
                extra.append("تليفون: %s" % phone)
            lines = []
            lines.extend(extra)
            if vars_["name"].get():
                lines.append(name)
            if vars_["price"].get():
                lines.append(price_txt)
            if vars_["barcode"].get():
                lines.append("الباركود: %s" % bc)
            # Save a PNG of the real bars next to the label file, so
            # the Windows path also carries a scannable image.
            png_path = ""
            if vars_["barcode"].get() and receipt_printer is not None:
                try:
                    png_path = receipt_printer.save_bytes(
                        BASE, "label_%s.png" % bc, ean13_png_bytes(bc, scale=3, height=64))
                except Exception:
                    png_path = ""
            escpos_data = None
            if receipt_printer is not None:
                ps = self._printer_settings()
                escpos_data = receipt_printer.build_escpos_label(
                    name if vars_["name"].get() else "",
                    price_txt if vars_["price"].get() else "",
                    bc if vars_["barcode"].get() else "",
                    size=var_size.get(),
                    width_chars=receipt_printer.width_chars_for(ps["width"]),
                    cp864_page=ps["cp864"], cp1256_page=ps["cp1256"],
                    extra_lines=tuple(extra),
                    show_barcode=vars_["barcode"].get())
            ok, msg, path = (True, "", "")
            for _i in range(copies):
                ok, msg, path = self._print_lines(
                    lines, "label_%s.txt" % bc, is_cash=False, escpos_data=escpos_data)
                if not ok:
                    break
            if ok:
                self.show_banner("🏷️ طُبع ملصق %s ×%d — %s" % (drug["trade_en"], copies, msg), "success")
                if png_path:
                    self.show_banner("صورة الباركود (PNG): %s" % png_path, "info")
                win.destroy()
            else:
                messagebox.showinfo("لم يُطبع بعد", "حُفظ في:\n%s\n%s" % (path, msg))
        ttk.Button(win, text="🏷️ طباعة الملصق", style="Success.TButton",
                   command=do_print_label).pack(pady=10)

    def drug_dialog(self, drug=None, prefill_barcode=""):
        if drug is None and not self.is_admin:
            messagebox.showerror("صلاحيات", "الكاشير لا يستطيع إضافة أدوية أو تغيير الأسعار — هذه صلاحية المدير فقط")
            return
        if drug is not None and not self.is_admin:
            messagebox.showerror("صلاحيات", "تعديل الأسعار صلاحية المدير فقط")
            return
        win = tk.Toplevel(self.root)
        win.title("تعديل دواء" if drug else "إضافة دواء جديد")
        # v6.3: taller dialog — discount fields + label button added.
        win.geometry("480x900")
        win.minsize(440, 600)
        fields = {}
        labels = [("trade_en", "الاسم التجاري (إنجليزي) *"), ("trade_ar", "الاسم التجاري (عربي)"),
                  ("scientific", "المادة الفعالة"), ("company", "الشركة"),
                  ("form", "الشكل الصيدلاني (Tablets / Syrup / Cream...)"), ("strength", "التركيز (مثال: 250 أو 250mg)"),
                  ("category", "الفئة"), ("strips_per_box", "عدد الشرائط في العلبة"),
                  ("tablets_per_strip", "عدد الحبات في الشريط"),
                  ("buy_price", "سعر الشراء (للعلبة)"), ("sell_price", "سعر البيع (للعلبة)"),
                  ("min_stock", "الحد الأدنى للمخزون (علبة)"), ("barcode", "باركود العلبة (GTIN) — امسح بالماسح ثم Enter")]
        for key, lbl in labels:
            ttk.Label(win, text=lbl).pack(anchor="w", padx=12, pady=(6, 0))
            val = ""
            if drug:
                val = str(drug.get(key, ""))
            elif key == "barcode":
                val = prefill_barcode
            elif key in ("strips_per_box", "tablets_per_strip"):
                val = "1"
            elif key == "min_stock":
                val = "5"
            if key == "form":
                # v6.3: dropdown of common pharmaceutical forms AND
                # free text — the user can type any other form.
                cb = ttk.Combobox(win, width=44, values=['Tablets', 'Capsules', 'Syrup', 'Suspension', 'Drops', 'Cream', 'Ointment', 'Gel', 'Spray', 'Injection', 'Sachet', 'Suppository'])
                cb.pack(padx=12)
                cb.set(val)
                fields[key] = cb
            else:
                ent = ttk.Entry(win, width=46)
                ent.pack(padx=12)
                ent.insert(0, val)
                fields[key] = ent
        # --- v6.3: per-drug discount (percent OR fixed amount per unit) ---
        ttk.Label(win, text="خصم الدواء الافتراضي (يُطبق تلقائياً عند البيع — ويمكن تغييره في الفاتورة):").pack(
            anchor="w", padx=12, pady=(10, 0))
        _disc_row = ttk.Frame(win)
        _disc_row.pack(fill="x", padx=12)
        var_disc_type = tk.StringVar(value="none")
        if drug:
            _dt = (drug.get("discount_type") or "none")
            var_disc_type.set(_dt if _dt in ("none", "percent", "amount") else "none")
        ttk.Radiobutton(_disc_row, text="بدون خصم", variable=var_disc_type, value="none").pack(side="left")
        ttk.Radiobutton(_disc_row, text="نسبة %", variable=var_disc_type, value="percent").pack(side="left")
        ttk.Radiobutton(_disc_row, text="مبلغ ثابت (ج.م) لكل وحدة", variable=var_disc_type, value="amount").pack(side="left")
        ttk.Label(win, text="قيمة الخصم:").pack(anchor="w", padx=12, pady=(4, 0))
        e_disc_val = ttk.Entry(win, width=46)
        e_disc_val.pack(padx=12)
        e_disc_val.insert(0, str(drug.get("discount_value") or 0) if drug else "0")
        # v6.3: a USB barcode scanner types the digits + Enter — Enter
        # in the GTIN field saves the drug, so a scan completes the
        # entry without touching the mouse.
        def save():
            if not fields["trade_en"].get().strip():
                messagebox.showerror("خطأ", "الاسم التجاري مطلوب")
                return
            data = {k: v.get().strip() for k, v in fields.items()}
            data["discount_type"] = var_disc_type.get()
            data["discount_value"] = e_disc_val.get().strip() or "0"
            try:
                data["strips_per_box"] = strict_int(data["strips_per_box"], "عدد الشرائط في العلبة") or 1
                data["tablets_per_strip"] = strict_int(data["tablets_per_strip"], "عدد الحبات في الشريط") or 1
                data["buy_price"] = strict_float(data["buy_price"], "سعر الشراء") or 0.0
                data["sell_price"] = strict_float(data["sell_price"], "سعر البيع") or 0.0
                data["min_stock"] = strict_int(data["min_stock"], "الحد الأدنى للمخزون") or 5
                data["discount_value"] = strict_float(data["discount_value"], "قيمة الخصم") or 0.0
            except ValueError as e:
                messagebox.showerror("خطأ", str(e))
                return
            try:
                if drug:
                    self.db.update_drug(drug["id"], data)
                    if data["barcode"]:
                        self.db.link_barcode(data["barcode"], drug["id"])
                    self.db.audit(self.username, "edit_drug", "drug %s price %.2f" % (drug["id"], data["sell_price"]))
                    saved_id = drug["id"]
                else:
                    saved_id = self.db.add_drug(data)
                    self.db.audit(self.username, "add_drug", "drug %s %s" % (saved_id, data["trade_en"]))
            except ValueError as e:
                messagebox.showerror("خطأ", str(e))
                return
            win.destroy()
            self.inv_refresh()
            self.pos_search_refresh()
            # v6.3: offer the pharmacy barcode label right after saving
            # a drug — the user asked for the label from this dialog.
            if messagebox.askyesno("تم الحفظ", "تم الحفظ بنجاح.\nهل تريد طباعة ملصق باركود الصيدلية لهذا الدواء الآن؟"):
                self.barcode_label_dialog_for(saved_id)
            else:
                messagebox.showinfo("تم", "تم الحفظ بنجاح")
        fields["barcode"].bind("<Return>", lambda e: save())
        ttk.Button(win, text="💾 حفظ", command=save).pack(pady=14)

    def drug_edit_selected(self):
        d = self._selected_inv_drug()
        if d:
            self.drug_dialog(drug=d)

    def show_batches(self):
        d = self._selected_inv_drug()
        if not d:
            return
        win = tk.Toplevel(self.root)
        win.title("تشغيلات: %s" % d["trade_en"])
        win.geometry("620x360")
        cols = ("batch", "expiry", "qty", "buy_unit")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for c, t in zip(cols, ("رقم التشغيلة", "تاريخ الصلاحية", "الكمية (حبة/وحدة)", "سعر شراء الوحدة")):
            tree.heading(c, text=t)
            tree.column(c, width=140)
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        for b in self.db.batches_for(d["id"]):
            tree.insert("", "end", values=(b["batch_no"], b["expiry"], b["qty_units"], money(b["buy_price_unit"])))
        ttk.Label(win, text="البيع يأخذ دائماً من أقرب تشغيلة تنتهي أولاً (FEFO).",
                  style="Muted.TLabel").pack(pady=4)

    def adjust_stock_dialog(self):
        d = self._selected_inv_drug()
        if not d:
            return
        if not self.is_admin:
            messagebox.showerror("صلاحيات", "تعديل المخزون يحتاج موافقة المدير")
            return
        qty = simpledialog.askinteger("جرد / تعديل", "أدخل فرق الكمية بالحبة/وحدة (+ زيادة، - نقص) لدواء %s:" % d["trade_en"])
        if qty is None or qty == 0:
            return
        reason = simpledialog.askstring("سبب التعديل", "سبب التعديل (جرد / تالف / ...):") or "جرد"
        try:
            self.db.adjust_stock(d["id"], qty, reason, self.username)
            self.db.audit(self.username, "adjust_stock", "drug %s delta %d (%s)" % (d["id"], qty, reason))
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        messagebox.showinfo("تم", "تم تعديل المخزون")
        self.inv_refresh()

    def show_shortages(self):
        rows = self.db.low_stock()
        win = tk.Toplevel(self.root)
        win.title("قائمة النواقص")
        txt = tk.Text(win, width=70, height=22, font=("Segoe UI", 11))
        txt.pack(padx=10, pady=10)
        txt.insert("1.0", "قائمة النواقص (%d صنف):\n\n" % len(rows))
        for d in rows:
            txt.insert("end", "- %s %s — المخزون %.1f علبة، الحد الأدنى %s\n" %
                       (d["trade_en"], d.get("strength", ""), d.get("stock_boxes", 0), d["min_stock"]))
        if not rows:
            txt.insert("end", "لا توجد نواقص حالياً ✅")
        txt.config(state="disabled")

    def show_expiry(self):
        rows = self.db.near_expiry(90)
        win = tk.Toplevel(self.root)
        win.title("قرب انتهاء الصلاحية (90 يوم)")
        txt = tk.Text(win, width=75, height=22, font=("Segoe UI", 11))
        txt.pack(padx=10, pady=10)
        # v5.7 (F14): expired batches are now labelled as expired —
        # they used to sit in the "near expiry" list with no distinction.
        n_exp = sum(1 for b in rows if (b["expiry"] or "") < date.today().isoformat())
        txt.insert("1.0", "أصناف تقترب صلاحيتها خلال 90 يوم (%d تشغيلة، منها %d منتهية):\n\n" % (len(rows), n_exp))
        for b in rows:
            expired = (b["expiry"] or "") < date.today().isoformat()
            txt.insert("end", "- %s — تشغيلة %s تنتهي %s، الكمية %s وحدة%s\n" %
                       (b["trade_en"], b["batch_no"], b["expiry"], b["qty_units"],
                        "  ⛔ منتهية — اعزلها ولا تبعها" if expired else ""))
        if not rows:
            txt.insert("end", "لا توجد أصناف قريبة الانتهاء ✅")
        txt.config(state="disabled")

    def export_drugs(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile="drugs_export.csv")
        if not path:
            return
        n = self.db.export_drugs_csv(path)
        messagebox.showinfo("تم", "تم تصدير %d دواء إلى:\n%s" % (n, path))

    # ---------- Purchases ----------
    def build_purchases(self, tab=None):
        if tab is None:
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text="🧾 المشتريات والموردين")
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="المورد:").pack(side="left")
        self.cb_supplier = ttk.Combobox(top, width=26, values=[s["name"] for s in self.db.suppliers()])
        self.cb_supplier.pack(side="left", padx=4)
        # v6.3: search a supplier by its ID number (#12) as well as
        # by name — type the ID and press the button.
        ttk.Label(top, text="بحث برقم المورد #:").pack(side="left", padx=(10, 2))
        self.e_sup_id = ttk.Entry(top, width=8)
        self.e_sup_id.pack(side="left")
        ttk.Button(top, text="🔎", command=self.supplier_id_search).pack(side="left", padx=2)
        if self.db.suppliers():
            self.cb_supplier.set(self.db.suppliers()[0]["name"])
        ttk.Button(top, text="➕ مورد جديد", command=self.add_supplier_dialog).pack(side="left", padx=4)
        ttk.Button(top, text="💰 دفع للمورد المحدد", command=self.pay_supplier_dialog).pack(side="left", padx=4)
        ttk.Button(top, text="↩️ مرتجع مشتريات", command=self.purchase_return_dialog).pack(side="left", padx=4)
        ttk.Label(top, text="رقم فاتورة المورد:").pack(side="left", padx=(12, 2))
        self.e_pur_inv = ttk.Entry(top, width=14)
        self.e_pur_inv.pack(side="left")
        ttk.Label(top, text="المدفوع:").pack(side="left", padx=(12, 2))
        self.e_pur_paid = ttk.Entry(top, width=10)
        self.e_pur_paid.pack(side="left")
        self.e_pur_paid.insert(0, "0")

        # v6.6: Save button + running total at the TOP. The old
        # bottom-only Save button sat below the lines table, below
        # the fold at normal window sizes — the user added lines
        # and could not find Save at all (screenshot image-77).
        top2 = ttk.Frame(tab)
        top2.pack(fill="x", padx=8, pady=(0, 4))
        self.btn_pur_save_top = ttk.Button(
            top2, text="💾 حفظ فاتورة الشراء وتحديث المخزون",
            command=self.pur_save)
        self.btn_pur_save_top.pack(side="left", padx=(0, 8))
        self.lbl_pur_total_top = ttk.Label(
            top2, text="إجمالي فاتورة الشراء: 0.00 ج.م", style="Total.TLabel")
        self.lbl_pur_total_top.pack(side="left")

        mid = ttk.Frame(tab)
        mid.pack(fill="both", expand=True, padx=8)
        ttk.Label(mid, text="ابحث عن دواء لإضافته للفاتورة:").pack(anchor="w")
        row = ttk.Frame(mid)
        row.pack(fill="x", pady=4)
        self.e_pur_search = ttk.Entry(row, width=34)
        self.e_pur_search.pack(side="left")
        self.e_pur_search.bind("<KeyRelease>", lambda e: self.pur_search_refresh())
        ttk.Button(row, text="بحث", command=self.pur_search_refresh).pack(side="left", padx=4)
        _pf, self.list_pur = self.make_drug_search_tree(mid, height=7)
        _pf.pack(fill="x")
        f = ttk.Frame(mid)
        f.pack(fill="x", pady=6)
        # v5.0: two rows — the old single row squeezed the expiry field
        # to 30px at 1280x800 (a YYYY-MM-DD date was barely editable).
        for lbl, var, w in [("عدد العلب:", "qty", 10), ("سعر شراء العلبة:", "buy", 10),
                            ("سعر بيع العلبة (اختياري):", "sell", 10)]:
            ttk.Label(f, text=lbl).pack(side="left", padx=(8, 2))
            ent = ttk.Entry(f, width=w)
            ent.pack(side="left")
            setattr(self, "e_pur_" + var, ent)
        f2 = ttk.Frame(mid)
        f2.pack(fill="x", pady=2)
        for lbl, var, w in [("رقم التشغيلة:", "batch", 14), ("تاريخ الصلاحية (YYYY-MM-DD):", "exp", 12)]:
            ttk.Label(f2, text=lbl).pack(side="left", padx=(8, 2))
            ent = ttk.Entry(f2, width=w)
            ent.pack(side="left")
            setattr(self, "e_pur_" + var, ent)
        self.e_pur_qty.insert(0, "1")
        self.e_pur_exp.insert(0, "2027-12-31")
        ttk.Button(mid, text="➕ إضافة السطر لفاتورة الشراء", command=self.pur_add_line).pack(anchor="w", pady=4)
        cols = ("name", "boxes", "buy", "total")
        self.tree_pur = ttk.Treeview(mid, columns=cols, show="headings", height=9)
        for c, t in zip(cols, ("الدواء", "عدد العلب", "سعر الشراء", "الإجمالي")):
            self.tree_pur.heading(c, text=t)
        self.tree_pur.pack(fill="both", expand=True)
        self.tree_pur.bind("<Double-Button-1>", lambda e: self.pur_edit_line())
        _pur_btns = ttk.Frame(mid)
        _pur_btns.pack(fill="x", pady=(6, 0))
        self.btn_pur_edit_line = ttk.Button(
            _pur_btns, text="✏️ تعديل السطر المحدد", command=self.pur_edit_line)
        self.btn_pur_edit_line.pack(side="left", padx=2)
        self.btn_pur_delete_line = ttk.Button(
            _pur_btns, text="🗑 حذف السطر المحدد", command=self.pur_delete_line)
        self.btn_pur_delete_line.pack(side="left", padx=2)
        ttk.Button(mid, text="💾 حفظ فاتورة الشراء وتحديث المخزون", command=self.pur_save).pack(pady=8)
        self.lbl_pur_total = ttk.Label(mid, text="إجمالي فاتورة الشراء: 0.00 ج.م", style="Total.TLabel")
        self.lbl_pur_total.pack()
        self.pur_search_refresh()

    def pur_search_refresh(self):
        if not hasattr(self, "list_pur"):
            return  # v6.14
        q = self.e_pur_search.get() if hasattr(self, "e_pur_search") else ""
        self.pur_results = self.db.search_drugs(q, limit=40)
        self.fill_drug_search_tree(self.list_pur, self.pur_results)

    def pur_validate_line(self, qty_raw, buy_raw, sell_raw, expiry_raw):
        """v6.6: one validation for add AND edit — same rules the DB
        enforces in record_purchase (whole boxes > 0, buy > 0,
        sell >= 0 if given, expiry YYYY-MM-DD and not in the past).
        Returns (qty, buy, sell_or_None, expiry, error_or_None)."""
        try:
            qty = strict_float(qty_raw, "عدد العلب")
        except ValueError as e:
            return None, None, None, None, str(e)
        if qty is None or qty <= 0 or qty != int(qty):
            return None, None, None, None, "عدد العلب يجب أن يكون عدداً صحيحاً أكبر من صفر"
        try:
            buy = strict_float(buy_raw, "سعر الشراء")
        except ValueError as e:
            return None, None, None, None, str(e)
        if buy is None or buy <= 0:
            return None, None, None, None, "أدخل سعر شراء أكبر من صفر"
        sell_txt = str(sell_raw or "").strip()
        sell = None
        if sell_txt:
            try:
                sell = strict_float(sell_txt, "سعر البيع")
            except ValueError as e:
                return None, None, None, None, str(e)
            if sell is None or sell < 0:
                return None, None, None, None, "سعر البيع غير صالح"
        expiry = str(expiry_raw or "").strip() or "2027-12-31"
        try:
            exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        except Exception:
            return None, None, None, None, "تاريخ الصلاحية غير صالح — استخدم الصيغة YYYY-MM-DD"
        if exp_date < date.today():
            return None, None, None, None, "تاريخ الصلاحية في الماضي — لا يمكن استلام تشغيلة منتهية"
        return int(qty), buy, sell, expiry, None

    def pur_refresh_table(self):
        """v6.6: rebuild the lines table from purchase_lines and
        update BOTH total labels (top bar + bottom)."""
        for i in self.tree_pur.get_children():
            self.tree_pur.delete(i)
        total = 0.0
        for line in self.purchase_lines:
            self.tree_pur.insert("", "end", values=(
                line["drug"]["trade_en"], line["qty_boxes"],
                money(line["buy_price"]),
                money(line["qty_boxes"] * line["buy_price"])))
            total += line["qty_boxes"] * line["buy_price"]
        txt = "إجمالي فاتورة الشراء: %s" % money(total)
        self.lbl_pur_total.config(text=txt)
        if hasattr(self, "lbl_pur_total_top"):
            self.lbl_pur_total_top.config(text=txt)

    def pur_selected_line_index(self):
        sel = self.tree_pur.selection()
        if not sel:
            return None
        return self.tree_pur.index(sel[0])

    def pur_add_line(self):
        d = self.selected_search_drug(self.list_pur)
        if not d:
            messagebox.showinfo("تنبيه", "اختر دواء أولاً")
            return
        qty, buy, sell, expiry, err = self.pur_validate_line(
            self.e_pur_qty.get(), self.e_pur_buy.get(),
            self.e_pur_sell.get(), self.e_pur_exp.get())
        if err:
            messagebox.showerror("خطأ", err)
            return
        batch = self.e_pur_batch.get().strip() or "B-%s" % date.today().isoformat()
        # v6.6: same drug + same batch + same expiry + same prices
        # = the same line, not a new one — merge the quantities.
        # (This is exactly the screenshot case: Nizapex added twice
        # with the same defaults became two identical lines.)
        for line in self.purchase_lines:
            if (line["drug"]["id"] == d["id"] and line["batch_no"] == batch
                    and line["expiry"] == expiry
                    and line["buy_price"] == buy
                    and line.get("sell_price") == sell):
                line["qty_boxes"] += qty
                self.pur_refresh_table()
                messagebox.showinfo(
                    "تم الدمج",
                    "الدواء موجود بالفعل في الفاتورة بنفس التشغيلة والأسعار — "
                    "تمت إضافة الكمية للسطر الموجود (أصبح %s علبة)." % line["qty_boxes"])
                return
        self.purchase_lines.append({
            "drug": d, "qty_boxes": qty, "buy_price": buy,
            "sell_price": sell, "batch_no": batch, "expiry": expiry})
        self.pur_refresh_table()

    def pur_delete_line(self):
        """v6.6: remove a draft line before saving — no DB change,
        the invoice is not saved yet."""
        idx = self.pur_selected_line_index()
        if idx is None:
            messagebox.showinfo("تنبيه", "اختر سطراً من جدول الفاتورة أولاً")
            return
        del self.purchase_lines[idx]
        self.pur_refresh_table()

    def pur_edit_line(self):
        """v6.6: double-click a line (or the edit button) to change
        qty / buy / sell / batch / expiry before saving. The edit
        only changes the in-memory draft line; nothing touches the
        DB until the whole invoice is saved."""
        idx = self.pur_selected_line_index()
        if idx is None:
            messagebox.showinfo("تنبيه", "اختر سطراً من جدول الفاتورة أولاً")
            return
        line = self.purchase_lines[idx]
        win = tk.Toplevel(self.root)
        win.title("تعديل سطر فاتورة الشراء — %s" % line["drug"]["trade_en"])
        win.geometry("420x380")
        fields = {}
        for key, lbl, val in [
                ("qty", "عدد العلب:", str(int(line["qty_boxes"]))),
                ("buy", "سعر شراء العلبة:", str(line["buy_price"])),
                ("sell", "سعر بيع العلبة (اختياري):",
                 "" if line.get("sell_price") is None else str(line["sell_price"])),
                ("batch", "رقم التشغيلة:", str(line["batch_no"])),
                ("exp", "تاريخ الصلاحية (YYYY-MM-DD):", str(line["expiry"]))]:
            ttk.Label(win, text=lbl).pack(anchor="w", padx=12, pady=(8, 0))
            ent = ttk.Entry(win, width=40)
            ent.pack(padx=12)
            ent.insert(0, val)
            fields[key] = ent

        def save_edit():
            qty, buy, sell, expiry, err = self.pur_validate_line(
                fields["qty"].get(), fields["buy"].get(),
                fields["sell"].get(), fields["exp"].get())
            if err:
                messagebox.showerror("خطأ", err)
                return
            line["qty_boxes"] = qty
            line["buy_price"] = buy
            line["sell_price"] = sell
            line["batch_no"] = fields["batch"].get().strip() or line["batch_no"]
            line["expiry"] = expiry
            self.pur_refresh_table()
            win.destroy()

        ttk.Button(win, text="💾 حفظ التعديل", command=save_edit).pack(pady=14)
        ttk.Button(win, text="إلغاء", command=win.destroy).pack()

    def pur_save(self):
        if not self.purchase_lines:
            messagebox.showinfo("تنبيه", "لا توجد أسطر في فاتورة الشراء")
            return
        name = self.cb_supplier.get().strip()
        sup = next((s for s in self.db.suppliers() if s["name"] == name), None)
        if not sup:
            messagebox.showerror("خطأ", "اختر مورد موجود أو أضف مورد جديد")
            return
        inv_no = self.e_pur_inv.get().strip() or "PUR-%s" % date.today().isoformat()
        try:
            paid_amt = strict_float(self.e_pur_paid.get(), "المبلغ المدفوع للمورد")
            paid_amt = paid_amt if paid_amt is not None else 0.0
            pid, total = self.db.record_purchase(
                sup["id"], inv_no,
                self.purchase_lines, paid=paid_amt, user=self.username)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        self.db.audit(self.username, "purchase", "purchase %s total %.2f supplier %s" % (pid, total, name))
        messagebox.showinfo("تم", "تم حفظ فاتورة الشراء #%d\nالإجمالي: %s\nتم تحديث المخزون والأسعار" % (pid, money(total)))
        self.purchase_lines = []
        self.pur_refresh_table()
        self.inv_refresh()
        self.pos_search_refresh()

    def supplier_id_search(self):
        """v6.3: find a supplier by ID (the # number next to the
        name). Unknown / non-numeric IDs show a clear message,
        never a crash."""
        raw = self.e_sup_id.get().strip().lstrip("#")
        if not raw:
            messagebox.showinfo("تنبيه", "اكتب رقم المورد أولاً (مثال: 12)")
            return
        sup = self.db.get_supplier(raw)
        if not sup:
            messagebox.showinfo("المورد غير موجود",
                                "لا يوجد مورد بالرقم #%s — راجع الرقم أو أضف مورد جديد" % raw)
            return
        self.cb_supplier.set(sup["name"])
        self.show_banner("المورد #%d: %s — دينه الحالي: %s" % (
            sup["id"], sup["name"], money(sup.get("balance") or 0)), "info")

    def add_supplier_dialog(self):
        name = simpledialog.askstring("مورد جديد", "اسم المورد:")
        if not name:
            return
        phone = simpledialog.askstring("مورد جديد", "هاتف المورد (اختياري):") or ""
        nid = self.db.add_supplier(name.strip(), phone)
        self.cb_supplier["values"] = [s["name"] for s in self.db.suppliers()]
        self.cb_supplier.set(name.strip())
        messagebox.showinfo("تم", "تمت إضافة المورد #%d" % nid)

    def pay_supplier_dialog(self):
        name = self.cb_supplier.get().strip()
        sup = next((s for s in self.db.suppliers() if s["name"] == name), None)
        if not sup:
            messagebox.showinfo("تنبيه", "اختر مورد أولاً")
            return
        amt = simpledialog.askfloat("دفع للمورد #%d" % sup["id"], "المبلغ المدفوع لـ %s (دينه الحالي: %s):" % (name, money(sup["balance"])))
        if amt is None or amt <= 0:
            return
        try:
            self.db.pay_supplier(sup["id"], amt, self.username)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        messagebox.showinfo("تم", "تم تسجيل الدفع")

    def purchase_return_dialog(self):
        """STEP2 (2C): return stock to a supplier — expired / near-expiry /
        damaged. Pick supplier, drug, batch (or leave blank for FEFO
        nearest-expiry first), qty + unit, reason."""
        sups = self.db.suppliers()
        if not sups:
            messagebox.showinfo("تنبيه", "أضف مورد أولاً")
            return
        win = tk.Toplevel(self.root)
        win.title("↩️ مرتجع مشتريات")
        win.geometry("560x520")
        ttk.Label(win, text="المورد:").pack(anchor="w", padx=10, pady=(8, 0))
        cb_sup = ttk.Combobox(win, width=40, state="readonly",
                              values=[s["name"] for s in sups])
        cb_sup.pack(anchor="w", padx=10)
        cur = self.cb_supplier.get().strip() if hasattr(self, "cb_supplier") else ""
        cb_sup.set(cur if cur in [s["name"] for s in sups] else sups[0]["name"])
        ttk.Label(win, text="ابحث عن الدواء:").pack(anchor="w", padx=10, pady=(8, 0))
        e_search = ttk.Entry(win, width=40)
        e_search.pack(anchor="w", padx=10)
        _rf, lst = self.make_drug_search_tree(win, height=6)
        _rf.pack(fill="x", padx=10, pady=4)
        ttk.Label(win, text="التشغيلة (اتركها فارغة = الأقرب انتهاءً أولاً FEFO):").pack(anchor="w", padx=10)
        cb_batch = ttk.Combobox(win, width=52, state="readonly", values=["— الأقرب انتهاءً أولاً —"])
        cb_batch.pack(anchor="w", padx=10)
        cb_batch.set("— الأقرب انتهاءً أولاً —")
        f = ttk.Frame(win)
        f.pack(fill="x", padx=10, pady=8)
        ttk.Label(f, text="الكمية:").pack(side="left")
        e_qty = ttk.Entry(f, width=10)
        e_qty.pack(side="left", padx=4)
        e_qty.insert(0, "1")
        ttk.Label(f, text="الوحدة:").pack(side="left", padx=(8, 2))
        cb_unit = ttk.Combobox(f, width=10, state="readonly",
                               values=["box", "strip", "pill"])
        cb_unit.pack(side="left")
        cb_unit.set("box")
        ttk.Label(win, text="السبب (منتهي / قارب على الانتهاء / تالف):").pack(anchor="w", padx=10)
        e_reason = ttk.Entry(win, width=52)
        e_reason.pack(anchor="w", padx=10)
        e_reason.insert(0, "منتهي الصلاحية")
        state = {"results": [], "batches": []}

        def refresh_drugs(_e=None):
            state["results"] = self.db.search_drugs(e_search.get(), limit=40)
            self.fill_drug_search_tree(lst, state["results"])
            state["batches"] = []
            cb_batch["values"] = ["— الأقرب انتهاءً أولاً —"]
            cb_batch.set("— الأقرب انتهاءً أولاً —")

        def on_drug(_e=None):
            d = self.selected_search_drug(lst)
            if not d:
                return
            units = allowed_units(d)
            cb_unit["values"] = units
            cb_unit.set("box" if "box" in units else units[0])
            state["batches"] = [b for b in self.db.batches_for(d["id"]) if b["qty_units"] > 0]
            vals = ["— الأقرب انتهاءً أولاً —"] + [
                "#%d | %s | انتهاء %s | %d وحدة | شراء %s/وحدة" % (
                    b["id"], b["batch_no"] or "—", b["expiry"] or "بدون تاريخ",
                    b["qty_units"], money(b["buy_price_unit"]))
                for b in state["batches"]]
            cb_batch["values"] = vals
            cb_batch.set(vals[0])

        e_search.bind("<KeyRelease>", refresh_drugs)
        lst.bind("<<TreeviewSelect>>", on_drug)
        refresh_drugs()

        def do_save():
            d = self.selected_search_drug(lst)
            if not d:
                messagebox.showinfo("تنبيه", "اختر الدواء أولاً")
                return
            name = cb_sup.get().strip()
            sup = next((s for s in sups if s["name"] == name), None)
            if not sup:
                messagebox.showerror("خطأ", "اختر مورد موجود")
                return
            try:
                qty = float(e_qty.get())
            except ValueError:
                messagebox.showerror("خطأ", "كمية غير صالحة")
                return
            if qty <= 0:
                messagebox.showerror("خطأ", "الكمية يجب أن تكون أكبر من صفر")
                return
            unit = cb_unit.get()
            try:
                qty_units = units_for_qty(d, unit, qty)
            except Exception as ex:
                messagebox.showerror("خطأ", str(ex))
                return
            batch_id = None
            if cb_batch.current() > 0:
                batch_id = state["batches"][cb_batch.current() - 1]["id"]
            reason = e_reason.get().strip()
            if not reason:
                messagebox.showerror("خطأ", "أدخل سبب المرتجع")
                return
            try:
                rid, total = self.db.create_purchase_return(
                    sup["id"], d["id"], qty_units, unit=unit,
                    reason=reason, cashier=self.username, batch_id=batch_id)
            except ValueError as e:
                messagebox.showerror("خطأ", str(e))
                return
            sup_after = next(s for s in self.db.suppliers() if s["id"] == sup["id"])
            messagebox.showinfo("تم", "تم تسجيل مرتجع المشتريات #%d\nالمبلغ: %s\nدين المورد الآن: %s" % (
                rid, money(total), money(sup_after["balance"])))
            win.destroy()
            self.reports_refresh()

        ttk.Button(win, text="✅ اعتماد مرتجع المشتريات", command=do_save,
                   style="Accent.TButton").pack(pady=12)

    # ---------- Customers ----------
    def build_customers(self, tab=None):
        if tab is None:
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text="👥 العملاء")
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="بحث:").pack(side="left")
        self.e_cust_search = ttk.Entry(top, width=28)
        self.e_cust_search.pack(side="left", padx=4)
        self.e_cust_search.bind("<KeyRelease>", lambda e: self.cust_refresh())
        ttk.Button(top, text="➕ عميل جديد", command=self.add_customer_dialog).pack(side="left", padx=4)
        ttk.Button(top, text="💰 تسجيل دفعة على الحساب", command=self.customer_pay_dialog).pack(side="left", padx=4)
        ttk.Button(top, text="📜 سجل مشتريات العميل", command=self.customer_history_dialog).pack(side="left", padx=4)
        cols = ("id", "name", "phone", "limit", "balance")
        self.tree_cust = ttk.Treeview(tab, columns=cols, show="headings", height=20)
        for c, t in zip(cols, ("#", "الاسم", "الهاتف", "حد الائتمان", "الدين الحالي (آجل)")):
            self.tree_cust.heading(c, text=t)
            self.tree_cust.column(c, width=150)
        self.tree_cust.pack(fill="both", expand=True, padx=8)
        self.cust_refresh()

    def cust_refresh(self):
        if not hasattr(self, "tree_cust"):
            return  # v6.14
        q = self.e_cust_search.get() if hasattr(self, "e_cust_search") else ""
        for i in self.tree_cust.get_children():
            self.tree_cust.delete(i)
        self.cust_rows = self.db.customers(q)
        for c in self.cust_rows:
            self.tree_cust.insert("", "end", values=(c["id"], c["name"], c["phone"],
                                                     money(c["credit_limit"]), money(c["balance"])))

    def _selected_customer(self):
        sel = self.tree_cust.selection()
        if not sel:
            messagebox.showinfo("تنبيه", "اختر عميل أولاً")
            return None
        return self.cust_rows[self.tree_cust.index(sel[0])]

    def add_customer_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("عميل جديد")
        win.geometry("380x300")
        ents = {}
        for key, lbl in [("name", "الاسم *"), ("phone", "الهاتف"),
                         ("limit", "حد الائتمان (ج.م)"), ("notes", "ملاحظات")]:
            ttk.Label(win, text=lbl).pack(anchor="w", padx=12, pady=(8, 0))
            e = ttk.Entry(win, width=40)
            e.pack(padx=12)
            ents[key] = e
        def save():
            if not ents["name"].get().strip():
                messagebox.showerror("خطأ", "الاسم مطلوب")
                return
            nid = self.db.add_customer(ents["name"].get().strip(), ents["phone"].get().strip(),
                                       safe_float(ents["limit"].get()), ents["notes"].get().strip())
            self.db.audit(self.username, "add_customer", "customer %s" % nid)
            win.destroy()
            self.cust_refresh()
            self.cb_customer["values"] = ["عميل نقدي"] + [c["name"] for c in self.db.customers()]
            messagebox.showinfo("تم", "تمت إضافة العميل")
        ttk.Button(win, text="حفظ", command=save).pack(pady=14)

    def customer_pay_dialog(self):
        c = self._selected_customer()
        if not c:
            return
        amt = simpledialog.askfloat("دفعة على الحساب", "المبلغ الذي دفعه %s (دينه: %s):" % (c["name"], money(c["balance"])))
        if amt is None or amt <= 0:
            return
        try:
            self.db.customer_pay(c["id"], amt, self.username)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        self.cust_refresh()
        messagebox.showinfo("تم", "تم تسجيل الدفعة")

    def customer_history_dialog(self):
        c = self._selected_customer()
        if not c:
            return
        rows = self.db.customer_history(c["id"])
        win = tk.Toplevel(self.root)
        win.title("سجل مشتريات: %s" % c["name"])
        txt = tk.Text(win, width=70, height=20, font=("Segoe UI", 11))
        txt.pack(padx=10, pady=10)
        txt.insert("1.0", "سجل مشتريات %s (دين حالي: %s):\n\n" % (c["name"], money(c["balance"])))
        for s in rows:
            txt.insert("end", "- %s | %s | %s | %s\n" % (s["invoice_no"], s["date"], money(s["total"]), s["status"]))
        if not rows:
            txt.insert("end", "لا توجد مشتريات مسجلة بعد.")
        txt.config(state="disabled")

    # ---------- Reports ----------
    def build_reports(self, tab=None):
        if tab is None:
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text="📊 التقارير")
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="التاريخ (YYYY-MM-DD):").pack(side="left")
        self.e_rep_date = ttk.Entry(top, width=14)
        self.e_rep_date.pack(side="left", padx=4)
        self.e_rep_date.insert(0, date.today().isoformat())
        ttk.Button(top, text="عرض تقرير اليوم", command=self.reports_refresh).pack(side="left", padx=4)
        ttk.Button(top, text="📋 كل الفواتير", command=self.show_all_invoices,
                   style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(top, text="إرجاع فاتورة (مرتجع)", command=self.return_sale_dialog).pack(side="left", padx=4)
        self.lbl_rep = ttk.Label(tab, text="", font=("Segoe UI", 12), wraplength=1000, justify="left")
        self.lbl_rep.pack(anchor="w", padx=10, pady=6)
        self.rep_cards_frame = ttk.Frame(tab)
        self.rep_cards_frame.pack(fill="x", padx=10, pady=4)
        self.rep_cards = {}
        for _key, _title, _acc in [("total", "مبيعات اليوم", "#0F766E"), ("profit", "ربح اليوم", "#15803D"),
                                   ("count", "عدد الفواتير", "#6D28D9"), ("net", "صافي الربح", "#1D4ED8")]:
            _fr, _val, _sub = ui_theme.make_card(self.rep_cards_frame, _title, "—", "", _acc, self.theme_name)
            _fr.pack(side="left", fill="both", expand=True, padx=4)
            self.rep_cards[_key] = (_fr, _val, _sub)
        ttk.Label(tab, text="أكثر الأصناف مبيعاً:", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10)
        cols = ("name", "units", "total")
        self.tree_best = ttk.Treeview(tab, columns=cols, show="headings", height=10)
        for c, t in zip(cols, ("الدواء", "الكمية المباعة (وحدة)", "الإجمالي")):
            self.tree_best.heading(c, text=t)
            self.tree_best.column(c, width=250)
        self.tree_best.pack(fill="both", expand=True, padx=10)
        btns = ttk.Frame(tab)
        btns.pack(fill="x", padx=10, pady=8)
        ttk.Button(btns, text="📥 تصدير تقرير اليوم CSV", command=self.export_daily_csv).pack(side="left", padx=4)
        ttk.Button(btns, text="📥 تصدير الأكثر مبيعاً CSV", command=self.export_best_csv).pack(side="left", padx=4)
        ttk.Button(btns, text="📥 تصدير قيمة المخزون CSV", command=self.export_inventory_csv).pack(side="left", padx=4)
        ttk.Button(btns, text="عرض قيمة المخزون", command=self.show_inventory_value).pack(side="left", padx=4)
        self.reports_refresh()

    def reports_refresh(self):
        if not hasattr(self, "tree_best"):
            return  # v6.14
        day = self.e_rep_date.get().strip() or date.today().isoformat()
        try:
            r = self.db.report_daily(day)
        except ValueError as e:
            self.lbl_rep.config(text="⚠️ %s" % e)
            return
        self.lbl_rep.config(text=(
            "تقرير يوم %s\nعدد الفواتير: %d | إجمالي المبيعات: %s | نقدي: %s | كارت: %s | آجل: %s\n"
            "الربح (بيع − تكلفة): %s | المصروفات: %s | صافي الربح: %s\n"
            "مرتجع مشتريات اليوم: %s (%d عملية)" % (
                r["date"], r["count"], money(r["total"]), money(r["cash"]), money(r["card"]),
                money(r["credit"]), money(r["profit"]), money(r["expenses"]), money(r["net_profit"]),
                money(r.get("purchase_returns_total", 0)), r.get("purchase_returns_count", 0))))
        try:
            self.rep_cards["total"][1].config(text=money(r["total"]))
            self.rep_cards["profit"][1].config(text=money(r["profit"]))
            self.rep_cards["count"][1].config(text=str(r["count"]))
            self.rep_cards["net"][1].config(text=money(r["net_profit"]))
            self.rep_cards["total"][2].config(text="نقدي %s • كارت %s • آجل %s" % (money(r["cash"]), money(r["card"]), money(r["credit"])))
            self.rep_cards["profit"][2].config(text="المصروفات: %s" % money(r["expenses"]))
        except Exception:
            pass
        for i in self.tree_best.get_children():
            self.tree_best.delete(i)
        best = self.db.report_best_sellers(day)
        if not best:
            self.tree_best.insert("", "end", values=(
                "لا توجد مبيعات في هذا اليوم بعد", "—", "—"))
        for b in best:
            self.tree_best.insert("", "end", values=(b["trade_en"], b["units"], money(b["total"])))
        ui_theme.stripe_rows(self.tree_best, self.theme_name)

    # ---------- v4.2: كل الفواتير ----------
    def show_all_invoices(self):
        """Full invoices list (newest first) with filters. Auto-refreshes
        with the 3s live poll while open. Double-click = detail window."""
        win = tk.Toplevel(self.root)
        win.title("📋 كل الفواتير")
        win.geometry("1100x600")
        self._inv_win = win
        self._inv_rows = []
        f = ttk.Frame(win)
        f.pack(fill="x", padx=10, pady=6)
        ttk.Label(f, text="من:").pack(side="left")
        self._inv_from = ttk.Entry(f, width=12)
        self._inv_from.pack(side="left", padx=2)
        self._inv_from.insert(0, date.today().isoformat())
        ttk.Label(f, text="إلى:").pack(side="left")
        self._inv_to = ttk.Entry(f, width=12)
        self._inv_to.pack(side="left", padx=2)
        self._inv_to.insert(0, date.today().isoformat())
        ttk.Label(f, text="المصدر:").pack(side="left", padx=(8, 0))
        self._inv_src = ttk.Combobox(f, width=10, state="readonly",
                                     values=["الكل", "كمبيوتر", "موبايل"])
        self._inv_src.pack(side="left", padx=2)
        self._inv_src.set("الكل")
        ttk.Label(f, text="الدفع:").pack(side="left", padx=(8, 0))
        self._inv_pay = ttk.Combobox(f, width=10, state="readonly",
                                     values=["الكل", "نقدي", "كارت", "آجل"])
        self._inv_pay.pack(side="left", padx=2)
        self._inv_pay.set("الكل")
        f2 = ttk.Frame(win)
        f2.pack(fill="x", padx=10, pady=2)
        ttk.Label(f2, text="العميل:").pack(side="left")
        self._inv_cust = ttk.Entry(f2, width=20)
        self._inv_cust.pack(side="left", padx=2)
        ttk.Label(f2, text="رقم الفاتورة:").pack(side="left", padx=(8, 0))
        self._inv_no = ttk.Entry(f2, width=16)
        self._inv_no.pack(side="left", padx=2)
        ttk.Button(f2, text="🔎 بحث", command=self._inv_refresh,
                   style="Accent.TButton").pack(side="left", padx=6)
        ttk.Button(f2, text="عرض الكل", command=self._inv_show_all).pack(side="left", padx=2)
        ttk.Button(f2, text="📥 تصدير CSV", command=self._inv_export_csv).pack(side="left", padx=2)
        self._inv_count = ttk.Label(win, text="", font=("Segoe UI", 11, "bold"))
        self._inv_count.pack(anchor="w", padx=10)
        cols = ("inv", "datetime", "customer", "source", "payment", "items", "total", "printed")
        self._inv_tree = ttk.Treeview(win, columns=cols, show="headings", height=18)
        for c, t, w in zip(cols, ("رقم الفاتورة", "التاريخ والوقت", "العميل", "المصدر",
                                  "طريقة الدفع", "عدد الأصناف", "الإجمالي", "حالة الطباعة"),
                           (130, 170, 180, 90, 90, 90, 110, 140)):
            self._inv_tree.heading(c, text=t)
            self._inv_tree.column(c, width=w)
        self._inv_tree.pack(fill="both", expand=True, padx=10, pady=4)
        self._inv_tree.bind("<Double-1>", lambda e: self._inv_open_detail())
        ui_theme.style_treeview(self._inv_tree, self.theme_name)
        ttk.Button(win, text="🧾 عرض تفاصيل الفاتورة المحددة",
                   command=self._inv_open_detail).pack(padx=10, pady=(6, 2))
        ttk.Button(win, text="✏️ تعديل الفاتورة المحددة",
                   command=self._inv_edit_selected,
                   style="Accent.TButton").pack(padx=10, pady=(0, 6))
        win.protocol("WM_DELETE_WINDOW", self._inv_close)
        self._inv_refresh()

    def _inv_close(self):
        try:
            self._inv_win.destroy()
        except Exception:
            pass
        self._inv_win = None

    def _inv_filters(self):
        src = {"الكل": None, "كمبيوتر": "pc", "موبايل": "mobile"}.get(self._inv_src.get())
        pay = {"الكل": None, "نقدي": "cash", "كارت": "card", "آجل": "credit"}.get(self._inv_pay.get())
        return dict(date_from=self._inv_from.get().strip() or None,
                    date_to=self._inv_to.get().strip() or None,
                    source=src, payment=pay,
                    customer=self._inv_cust.get().strip(),
                    invoice_no=self._inv_no.get().strip())

    def _inv_show_all(self):
        self._inv_from.delete(0, "end")
        self._inv_to.delete(0, "end")
        self._inv_src.set("الكل")
        self._inv_pay.set("الكل")
        self._inv_cust.delete(0, "end")
        self._inv_no.delete(0, "end")
        self._inv_refresh()

    def _inv_refresh(self):
        if getattr(self, "_inv_win", None) is None or not self._inv_win.winfo_exists():
            return
        try:
            self._inv_rows = self.db.get_all_sales(**self._inv_filters())
            for i in self._inv_tree.get_children():
                self._inv_tree.delete(i)
            for s in self._inv_rows:
                dt = (s.get("created_at") or s.get("date") or "").replace("T", " ")
                src = "موبايل 📱" if s.get("source") == "mobile" else "كمبيوتر 🖥️"
                pay = {"cash": "نقدي", "card": "كارت", "credit": "آجل"}.get(
                    s.get("payment_method"), s.get("payment_method") or "")
                printed = "🖨️ مطبوعة" if s.get("printed_at") else "⏳ بانتظار الطباعة"
                self._inv_tree.insert("", "end", values=(
                    s["invoice_no"], dt, s.get("customer_name") or "عميل نقدي",
                    src, pay, s.get("item_count", ""), money(s["total"]), printed))
            ui_theme.stripe_rows(self._inv_tree, self.theme_name)
            total = sum(s["total"] for s in self._inv_rows)
            self._inv_count.config(text="عدد الفواتير: %d — الإجمالي: %s" % (len(self._inv_rows), money(total)))
        except Exception:
            pass

    def _inv_export_csv(self):
        rows = [(s["invoice_no"], (s.get("created_at") or s.get("date") or ""),
                 s.get("customer_name") or "", s.get("source") or "",
                 s.get("payment_method") or "", s.get("item_count", ""),
                 s["total"], "مطبوعة" if s.get("printed_at") else "بانتظار الطباعة")
                for s in getattr(self, "_inv_rows", [])]
        self._export_csv("all_invoices.csv",
                         ["invoice", "datetime", "customer", "source", "payment",
                          "items", "total", "printed"], rows)

    def _inv_selected(self):
        sel = self._inv_tree.selection()
        if not sel:
            return None
        idx = self._inv_tree.index(sel[0])
        if 0 <= idx < len(self._inv_rows):
            return self._inv_rows[idx]
        return None

    def _inv_open_detail(self):
        s = self._inv_selected()
        if not s:
            messagebox.showinfo("تنبيه", "اختر فاتورة من القائمة أولاً (أو اضغط مرتين عليها)")
            return
        items = self.db.get_grouped_sale_items(s["id"])
        win = tk.Toplevel(self.root)
        win.title("فاتورة %s" % s["invoice_no"])
        win.geometry("750x550")
        info = ("رقم الفاتورة: %s\nالتاريخ والوقت: %s\nالعميل: %s\nالكاشير: %s\n"
                "المصدر: %s\nطريقة الدفع: %s\nالمدفوع: %s\nالحالة: %s" % (
                    s["invoice_no"], (s.get("created_at") or s.get("date") or "").replace("T", " "),
                    s.get("customer_name") or "عميل نقدي", s.get("cashier") or "",
                    "موبايل 📱" if s.get("source") == "mobile" else "كمبيوتر 🖥️",
                    {"cash": "نقدي", "card": "كارت", "credit": "آجل"}.get(
                        s.get("payment_method"), s.get("payment_method") or ""),
                    money(s.get("paid", s["total"])),
                    "🖨️ مطبوعة %s" % s["printed_at"] if s.get("printed_at") else "⏳ بانتظار الطباعة"))
        ttk.Label(win, text=info, font=("Segoe UI", 12), justify="left").pack(anchor="w", padx=12, pady=8)
        cols = ("drug", "unit", "qty", "price", "total")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=12)
        for c, t in zip(cols, ("الدواء", "الوحدة", "الكمية", "السعر", "الإجمالي")):
            tree.heading(c, text=t)
            tree.column(c, width=140)
        tree.pack(fill="both", expand=True, padx=10)
        for it in items:
            unit = {"box": "علبة", "strip": "شريط", "pill": "حبة"}.get(
                it.get("pack_level"), it.get("pack_level") or "")
            tree.insert("", "end", values=(
                "%s %s" % (it.get("trade_en") or "", it.get("trade_ar") or ""),
                unit, it.get("qty_display"), money(it.get("unit_price", 0)),
                money(it.get("line_total", 0))))
        ui_theme.style_treeview(tree, self.theme_name)
        ttk.Label(win, text="الإجمالي: %s" % money(s["total"]),
                  font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=12, pady=6)
        if s.get("edited_at"):
            ttk.Label(win, text="✏️ عُدّلت: %s بواسطة %s" % (
                s["edited_at"], s.get("edited_by") or "—"),
                font=("Segoe UI", 11, "bold"), foreground="#B45309").pack(
                    anchor="w", padx=12, pady=2)
        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=8)
        ttk.Button(btns, text="✏️ تعديل الفاتورة",
                   command=lambda: self.edit_invoice_dialog(s["id"]),
                   style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(btns, text="🖨️ طباعة الإيصال",
                   command=lambda: self._open_receipt_window(s),
                   style="Success.TButton").pack(side="left", padx=4)
        ttk.Button(btns, text="📥 تصدير أصناف الفاتورة CSV",
                   command=lambda: self._export_csv(
                       "invoice_%s_items.csv" % s["invoice_no"],
                       ["drug", "unit", "qty", "price", "total"],
                       [(it.get("trade_en") or "", it.get("pack_level") or "",
                         it.get("qty_display"), it.get("unit_price"),
                         it.get("line_total")) for it in items])).pack(side="left", padx=4)

    # ---------- v5.5: تعديل الفاتورة (قبل الطباعة أو بعدها) ----------
    def _inv_edit_selected(self):
        s = self._inv_selected()
        if not s:
            messagebox.showinfo("تنبيه", "اختر فاتورة من القائمة أولاً")
            return
        self.edit_invoice_dialog(s["id"])

    def mobile_edit_selected(self):
        sale = self._selected_mobile_sale()
        if not sale:
            return
        self.edit_invoice_dialog(sale["id"])

    def edit_invoice_dialog(self, sale_id):
        """Edit one invoice (PC + phone invoices alike): change qty,
        remove lines, add a new item, change discount / paid /
        payment / customer. Save goes through DB.edit_sale() — one
        atomic transaction, FEFO restock of the old lines then
        FEFO deduct of the new ones, audit logged. Invoice number
        and date never change; a printed invoice stays printable
        and can be re-printed with the new contents."""
        sale = self.db.get_sale(sale_id)
        if not sale:
            messagebox.showerror("خطأ", "الفاتورة غير موجودة")
            return
        if sale["status"] != "completed":
            messagebox.showinfo("لا يمكن التعديل",
                                "لا يمكن تعديل هذه الفاتورة — حالتها: %s.\n"
                                "الفاتورة المُرجعة لا تُعدَّل." % sale["status"])
            return
        items = self.db.get_grouped_sale_items(sale_id)
        # working cart: dicts {drug, pack_level, qty_display}
        # v5.8: staged deletion — a line deleted here is only HELD
        # (held=True) until the edit is approved. Nothing is removed
        # from `cart` on delete; held lines are excluded from the new
        # total and from the cart sent to DB.edit_sale() on approve.
        # Closing / cancelling discards them and the invoice is
        # untouched (no stock, credit or audit change).
        cart = []
        for it in items:
            d = self.db.get_drug(it["drug_id"])
            if d:
                # v6.3: keep the line's stored discount (orig) — it is
                # re-applied exactly, not recomputed from today's
                # drug default, unless the qty changes (then it
                # scales proportionally).
                cart.append({"drug": d, "pack_level": it["pack_level"] or "box",
                             "qty_display": float(it["qty_display"] or 0),
                             "held": False, "orig": True,
                             "discount": float(it.get("line_discount") or 0),
                             "disc_mode": "orig"})
        orig_snapshot = [dict(it) for it in cart]
        orig_disc = float(sale.get("discount") or 0)
        orig_paid = float(sale.get("paid") or sale["total"])
        orig_pay = sale.get("payment_method") or "cash"
        orig_cust_name = None
        if sale.get("customer_id"):
            for _c in self.db.customers(""):
                if _c["id"] == sale["customer_id"]:
                    orig_cust_name = _c["name"]
        win = tk.Toplevel(self.root)
        win.title("✏️ تعديل فاتورة %s" % sale["invoice_no"])
        win.geometry("900x650")
        old_total = float(sale["total"])
        ttk.Label(win, text="فاتورة: %s — التاريخ: %s — الإجمالي القديم: %s" % (
            sale["invoice_no"], sale["date"], money(old_total)),
            font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=8)
        if sale.get("printed_at"):
            ttk.Label(win, text="⚠️ هذه الفاتورة مطبوعة — بعد التعديل ستُطبع من جديد بالمحتوى الجديد.",
                      font=("Segoe UI", 11), foreground="#B45309").pack(anchor="w", padx=12)
        if sale.get("edited_at"):
            ttk.Label(win, text="✏️ عُدّلت من قبل: %s بواسطة %s" % (
                sale["edited_at"], sale.get("edited_by") or "—"),
                font=("Segoe UI", 11), foreground="#B45309").pack(anchor="w", padx=12)
        cols = ("drug", "unit", "qty", "price", "disc", "total")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=10)
        for c, t in zip(cols, ("الدواء", "الوحدة", "الكمية", "السعر", "الخصم", "الإجمالي")):
            tree.heading(c, text=t)
            tree.column(c, width=130)
        tree.pack(fill="both", expand=True, padx=10, pady=4)
        tree.tag_configure("held", foreground="#9CA3AF")
        ui_theme.style_treeview(tree, self.theme_name)

        def refresh_tree():
            for i in tree.get_children():
                tree.delete(i)
            for it in cart:
                up = unit_price(it["drug"], it["pack_level"])
                held = bool(it.get("held"))
                _ld = float(it.get("discount") or 0)
                tree.insert("", "end", values=(
                    ("⏳ محذوف مؤقتاً — %s %s" % (it["drug"]["trade_en"], it["drug"].get("trade_ar") or "")) if held
                    else "%s %s" % (it["drug"]["trade_en"], it["drug"].get("trade_ar") or ""),
                    {"box": "علبة", "strip": "شريط", "pill": "حبة"}.get(it["pack_level"], it["pack_level"]),
                    it["qty_display"], money(up), money(_ld),
                    money(up * float(it["qty_display"]) - _ld)),
                    tags=("held",) if held else ())
            ui_theme.stripe_rows(tree, self.theme_name)
            active = [it for it in cart if not it.get("held")]
            held_lines = [it for it in cart if it.get("held")]
            sub = sum(unit_price(it["drug"], it["pack_level"]) * float(it["qty_display"])
                      - float(it.get("discount") or 0) for it in active)
            held_sum = sum(unit_price(it["drug"], it["pack_level"]) * float(it["qty_display"])
                           - float(it.get("discount") or 0) for it in held_lines)
            disc = safe_float(e_disc.get())
            total = max(0.0, sub - disc)
            paid = safe_float(e_paid.get(), total)
            diff = total - old_total
            lbl_totals.config(
                text="الإجمالي المحفوظ: %s — الإجمالي الجديد بعد الاعتماد: %s (المجموع: %s — الخصم: %s)\n"
                     "الفرق عن القديم: %s (%s) — الباقي: %s%s" % (
                         money(old_total), money(total), money(sub), money(disc), money(diff),
                         "يُحصَّل من العميل" if diff > 0 else ("يُرد للعميل" if diff < 0 else "لا فرق"),
                         money(max(0.0, paid - total)) if paid >= total else "—",
                         (" — مبلغ الأصناف المحذوفة مؤقتاً (غير محسوب حتى الاعتماد): %s" % money(held_sum)) if held_lines else ""))

        def change_qty(delta):
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("تنبيه", "اختر صنفاً من القائمة أولاً")
                return
            it = cart[tree.index(sel[0])]
            if it.get("held"):
                messagebox.showinfo("تنبيه", "هذا الصنف محذوف مؤقتاً — استرجعه أولاً بزر «↩️ استرجاع المحذوف» قبل تغيير كميته")
                return
            _old_q = float(it["qty_display"])
            _old_disc = float(it.get("discount") or 0)
            it["qty_display"] = _old_q + delta
            # v6.3: a stored/manual line discount scales with qty;
            # an auto discount is recomputed from the drug default.
            if it.get("disc_mode", "auto") == "auto":
                it["discount"] = self._line_disc_amount(
                    it["drug"], it["pack_level"], it["qty_display"], "auto")
            elif _old_q > 0:
                it["discount"] = round(_old_disc * it["qty_display"] / _old_q + 1e-9, 2)
            if it["qty_display"] <= 0:
                # v5.8: reaching zero HOLDS the line instead of
                # deleting it — it stays visible until approved.
                # Keep the last real quantity so Restore brings it back.
                it["qty_display"] = _old_q
                it["held_qty"] = _old_q
                it["held"] = True
            refresh_tree()

        def remove_line():
            """v5.8: hold the line for approval instead of deleting it."""
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("تنبيه", "اختر صنفاً من القائمة أولاً")
                return
            it = cart[tree.index(sel[0])]
            if it.get("held"):
                messagebox.showinfo("تنبيه", "هذا الصنف محذوف مؤقتاً بالفعل — يبقى معلَّقاً حتى تعتمد التعديلات أو تسترجعه")
                return
            it["held_qty"] = float(it["qty_display"])
            it["held"] = True
            refresh_tree()

        def restore_line():
            """v5.8: undo a held (pending-deletion) line."""
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("تنبيه", "اختر صنفاً محذوفاً مؤقتاً أولاً")
                return
            it = cart[tree.index(sel[0])]
            if not it.get("held"):
                messagebox.showinfo("تنبيه", "هذا الصنف ليس محذوفاً مؤقتاً")
                return
            it["held"] = False
            refresh_tree()

        row = ttk.Frame(win)
        row.pack(fill="x", padx=10, pady=4)
        ttk.Button(row, text="＋ كمية", command=lambda: change_qty(1)).pack(side="left", padx=4)
        ttk.Button(row, text="− كمية", command=lambda: change_qty(-1)).pack(side="left", padx=4)
        ttk.Button(row, text="🗑️ حذف الصنف", command=remove_line).pack(side="left", padx=4)
        ttk.Button(row, text="↩️ استرجاع المحذوف", command=restore_line).pack(side="left", padx=4)
        # --- add a new item ---
        addf = ttk.Frame(win)
        addf.pack(fill="x", padx=10, pady=4)
        ttk.Label(addf, text="إضافة صنف: باركود / اسم:").pack(side="left")
        e_add = ttk.Entry(addf, width=28, font=("Segoe UI", 12))
        e_add.pack(side="left", padx=4)
        var_unit = tk.StringVar(value="box")
        for txt, val in (("علبة", "box"), ("شريط", "strip"), ("حبة", "pill")):
            ttk.Radiobutton(addf, text=txt, variable=var_unit, value=val).pack(side="left")
        e_qty = ttk.Entry(addf, width=6, font=("Segoe UI", 12))
        e_qty.pack(side="left", padx=4)
        e_qty.insert(0, "1")

        def add_item():
            code = e_add.get().strip()
            if not code:
                return
            drug = None
            try:
                drug, _pk = self.db.lookup_barcode(code)
            except Exception:
                drug = None
            if not drug:
                res = self.db.search_drugs(code, limit=1)
                drug = res[0] if res else None
            if not drug:
                messagebox.showerror("خطأ", "الدواء غير موجود — جرّب الباركود أو الاسم")
                return
            try:
                q = float(e_qty.get() or "1")
            except Exception:
                q = 1
            if q <= 0:
                messagebox.showerror("خطأ", "الكمية يجب أن تكون أكبر من صفر")
                return
            unit = var_unit.get()
            if unit not in allowed_units(drug):
                messagebox.showerror("خطأ", "هذه الوحدة غير متاحة لهذا الشكل الصيدلاني")
                return
            for it in cart:
                if it["drug"]["id"] == drug["id"] and it["pack_level"] == unit:
                    # v5.8: adding the same item back restores a held line.
                    it["held"] = False
                    it["qty_display"] = float(it["qty_display"]) + q
                    if it.get("disc_mode", "auto") == "auto":
                        it["discount"] = self._line_disc_amount(
                            drug, unit, it["qty_display"], "auto")
                    break
            else:
                cart.append({"drug": drug, "pack_level": unit, "qty_display": q,
                             "held": False, "orig": False, "disc_mode": "auto",
                             "discount": self._line_disc_amount(drug, unit, q, "auto")})
            e_add.delete(0, "end")
            refresh_tree()
        ttk.Button(addf, text="➕ إضافة", command=add_item,
                   style="Accent.TButton").pack(side="left", padx=4)
        e_add.bind("<Return>", lambda e: add_item())
        # --- discount / paid / payment / customer ---
        payf = ttk.Frame(win)
        payf.pack(fill="x", padx=10, pady=4)
        ttk.Label(payf, text="الخصم (ج.م):").pack(side="left")
        e_disc = ttk.Entry(payf, width=8, font=("Segoe UI", 12))
        e_disc.pack(side="left", padx=4)
        e_disc.insert(0, "%.2f" % float(sale.get("discount") or 0))
        e_disc.bind("<KeyRelease>", lambda e: refresh_tree())
        ttk.Label(payf, text="المدفوع:").pack(side="left", padx=(10, 0))
        e_paid = ttk.Entry(payf, width=10, font=("Segoe UI", 12))
        e_paid.pack(side="left", padx=4)
        e_paid.insert(0, "%.2f" % float(sale.get("paid") or sale["total"]))
        e_paid.bind("<KeyRelease>", lambda e: refresh_tree())
        ttk.Label(payf, text="الدفع:").pack(side="left", padx=(10, 0))
        var_pay = tk.StringVar(value=sale.get("payment_method") or "cash")
        cmb_pay = ttk.Combobox(payf, textvariable=var_pay, width=8, state="readonly",
                               values=["cash", "card", "credit"])
        cmb_pay.pack(side="left", padx=4)
        ttk.Label(payf, text="العميل:").pack(side="left", padx=(10, 0))
        customers = self.db.customers("")
        cust_names = ["عميل نقدي"] + [c["name"] for c in customers]
        var_cust = tk.StringVar()
        cmb_cust = ttk.Combobox(payf, textvariable=var_cust, width=22, state="readonly",
                                values=cust_names)
        cmb_cust.pack(side="left", padx=4)
        cur_cust = ""
        if sale.get("customer_id"):
            for c in customers:
                if c["id"] == sale["customer_id"]:
                    cur_cust = c["name"]
        cmb_cust.set(cur_cust or "عميل نقدي")
        lbl_totals = ttk.Label(win, text="", font=("Segoe UI", 12, "bold"))
        lbl_totals.pack(anchor="w", padx=12, pady=6)
        refresh_tree()

        def do_save():
            """v5.8: this is the APPROVAL point. Held lines are only
            now excluded from the saved invoice; until this button is
            pressed and confirmed, nothing has changed in the DB."""
            active = [it for it in cart if not it.get("held")]
            if not active:
                if cart:
                    messagebox.showerror("خطأ", "كل الأصناف محذوفة مؤقتاً — استرجع ما تريده بزر «↩️ استرجاع المحذوف» قبل الاعتماد")
                else:
                    messagebox.showerror("خطأ", "الفاتورة فارغة — لا يمكن حفظ فاتورة بلا أصناف")
                return
            cust_id = None
            cust_name = var_cust.get() or "عميل نقدي"
            if cust_name != "عميل نقدي":
                for c in customers:
                    if c["name"] == cust_name:
                        cust_id = c["id"]
            try:
                disc = strict_float(e_disc.get(), "الخصم")
                disc = disc if disc is not None else 0.0
                paid_v = strict_float(e_paid.get(), "المبلغ المدفوع") if e_paid.get().strip() else None
            except ValueError as e:
                messagebox.showerror("خطأ", str(e))
                return
            # --- build the full change summary for the approval box ---
            def _nm(it):
                return "%s %s" % (it["drug"]["trade_en"], it["drug"].get("trade_ar") or "")
            def _amt(it):
                return (unit_price(it["drug"], it["pack_level"]) * float(it["qty_display"])
                        - float(it.get("discount") or 0))
            held_lines = [it for it in cart if it.get("held")]
            orig_by_key = {(it["drug"]["id"], it["pack_level"]): it for it in orig_snapshot}
            summary = []
            for it in held_lines:
                summary.append("🗑️ حذف: %s — %s x%s = %s" % (
                    _nm(it), {"box": "علبة", "strip": "شريط", "pill": "حبة"}.get(it["pack_level"], it["pack_level"]),
                    it["qty_display"], money(_amt(it))))
            for it in active:
                key = (it["drug"]["id"], it["pack_level"])
                if key not in orig_by_key:
                    summary.append("➕ إضافة: %s — %s x%s = %s" % (
                        _nm(it), {"box": "علبة", "strip": "شريط", "pill": "حبة"}.get(it["pack_level"], it["pack_level"]),
                        it["qty_display"], money(_amt(it))))
                elif float(it["qty_display"]) != float(orig_by_key[key]["qty_display"]):
                    summary.append("🔢 تغيير كمية: %s — من x%s إلى x%s" % (
                        _nm(it), orig_by_key[key]["qty_display"], it["qty_display"]))
            if disc != orig_disc:
                summary.append("💸 الخصم: من %s إلى %s" % (money(orig_disc), money(disc)))
            if paid_v is not None and abs(float(paid_v) - orig_paid) > 0.005:
                summary.append("💵 المدفوع: من %s إلى %s" % (money(orig_paid), money(paid_v)))
            if var_pay.get() != orig_pay:
                summary.append("💳 طريقة الدفع: من %s إلى %s" % (orig_pay, var_pay.get()))
            if cust_name != (orig_cust_name or "عميل نقدي"):
                summary.append("👤 العميل: من %s إلى %s" % (orig_cust_name or "عميل نقدي", cust_name))
            if not summary:
                messagebox.showinfo("لا تغييرات", "لا توجد تغييرات لاعتمادها — الفاتورة كما هي.")
                return
            _sub = sum(_amt(it) for it in active)
            _new_total = max(0.0, _sub - disc)
            _diff = _new_total - old_total
            confirm_txt = ("اعتماد التعديلات على فاتورة %s؟\n\n%s\n\n"
                           "الإجمالي القديم: %s\nالإجمالي الجديد: %s\nالفرق: %s (%s)\n\n"
                           "بعد الاعتماد فقط يُحذف ما حُذف ويُعاد المخزون — قبل ذلك لم يتغيّر شيء." % (
                               sale["invoice_no"], "\n".join(summary), money(old_total),
                               money(_new_total), money(_diff),
                               "يُحصَّل من العميل" if _diff > 0 else ("يُرد للعميل" if _diff < 0 else "لا فرق")))
            if not messagebox.askyesno("✅ اعتماد التعديلات", confirm_txt):
                return
            try:
                res = self.db.edit_sale(
                    sale_id, self.username, active,
                    discount=disc,
                    payment_method=var_pay.get(),
                    customer_id=cust_id,
                    paid=paid_v)
            except ValueError as e:
                messagebox.showerror("خطأ", str(e))
                return
            diff = res["difference"]
            msg = ("تم تعديل الفاتورة %s\nالإجمالي القديم: %s\nالإجمالي الجديد: %s\n"
                   % (res["invoice_no"], money(res["old_total"]), money(res["new_total"])))
            msg += ("الفرق: %s يُحصَّل من العميل" % money(diff) if diff > 0 else
                    ("الفرق: %s يُرد للعميل" % money(-diff) if diff < 0 else "لا فرق في الإجمالي"))
            messagebox.showinfo("تم التعديل", msg)
            win.destroy()
            try:
                self._inv_refresh()
            except Exception:
                pass
            try:
                self.mobile_refresh()
            except Exception:
                pass
            try:
                self.reports_refresh()
                self.inv_refresh()
            except Exception:
                pass
        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=8)
        ttk.Button(btns, text="✅ اعتماد التعديلات", command=do_save,
                   style="Success.TButton").pack(side="left", padx=4)
        ttk.Button(btns, text="إلغاء (بدون اعتماد)", command=win.destroy).pack(side="left", padx=4)
        # v5.8: closing the window (X / Esc / Cancel) discards every
        # pending deletion — the invoice is only changed by Approve.
        win.protocol("WM_DELETE_WINDOW", win.destroy)

    def return_sale_dialog(self):
        inv = simpledialog.askstring("مرتجع", "أدخل رقم الفاتورة (مثال INV-000001):")
        if not inv:
            return
        row = self.db.conn.execute("SELECT * FROM sales WHERE invoice_no=?", (inv.strip(),)).fetchone()
        if not row:
            messagebox.showerror("خطأ", "الفاتورة غير موجودة")
            return
        if messagebox.askyesno("تأكيد المرتجع", "إرجاع كامل الفاتورة %s بمبلغ %s؟\nسيتم إعادة الكمية للمخزون." % (inv, money(row["total"]))):
            reason = simpledialog.askstring("سبب المرتجع", "سبب الإرجاع (اختياري):") or ""
            try:
                # STEP2 (2B): the refund is charged to the CURRENT shift
                # when one is open; the original shift keeps its history.
                self.db.return_sale(row["id"], self.username,
                                    return_shift_id=self.current_shift["id"] if self.current_shift else None,
                                    reason=reason.strip())
                self.db.audit(self.username, "return_sale", inv)
            except ValueError as e:
                messagebox.showerror("خطأ", str(e))
                return
            messagebox.showinfo("تم", "تم إرجاع الفاتورة")
            self.reports_refresh()
            self.inv_refresh()

    def _export_csv(self, filename, header, rows):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile=filename)
        if not path:
            return
        import csv as _csv
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        messagebox.showinfo("تم", "تم التصدير إلى:\n%s" % path)

    def export_daily_csv(self):
        day = self.e_rep_date.get().strip() or date.today().isoformat()
        try:
            self.db.sales_on(day)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        # v5.7: the on-screen report excludes returned invoices — the
        # export used to include them.
        rows = [(s["invoice_no"], s["date"], s["cashier"], s["total"], s["payment_method"], s["status"])
                for s in self.db.sales_on(day) if s["status"] == "completed"]
        self._export_csv("daily_sales_%s.csv" % day,
                         ["invoice", "date", "cashier", "total", "payment", "status"], rows)

    def export_best_csv(self):
        # v5.7: the screen shows the selected day — the export used
        # to be all-time.
        day = self.e_rep_date.get().strip() or date.today().isoformat()
        try:
            rows = [(b["trade_en"], b["units"], b["total"]) for b in self.db.report_best_sellers(day)]
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        self._export_csv("best_sellers.csv", ["drug", "units", "total"], rows)

    def export_inventory_csv(self):
        rows, tc, ts = self.db.report_inventory_value()
        self._export_csv("inventory_value.csv", ["drug", "units", "cost_value", "sell_value"],
                         [(r["trade_en"], r["units"], r["cost_value"], r["sell_value"]) for r in rows])

    def show_inventory_value(self):
        rows, tc, ts = self.db.report_inventory_value()
        win = tk.Toplevel(self.root)
        win.title("قيمة المخزون")
        txt = tk.Text(win, width=75, height=22, font=("Segoe UI", 11))
        txt.pack(padx=10, pady=10)
        txt.insert("1.0", "قيمة المخزون الإجمالية:\nبالتكلفة: %s\nبسعر البيع: %s\nعدد الأصناف: %d\n\n" % (money(tc), money(ts), len(rows)))
        for r in rows[:60]:
            txt.insert("end", "- %s: %s وحدة — تكلفة %s\n" % (r["trade_en"], r["units"], money(r["cost_value"] or 0)))
        txt.config(state="disabled")

    # ---------- Cash / Shifts ----------
    def build_cash(self, tab=None):
        if tab is None:
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text="💰 الخزنة والورديات")
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=8)
        self.lbl_shift = ttk.Label(top, text="", font=("Segoe UI", 12, "bold"))
        self.lbl_shift.pack(side="left")
        ttk.Button(top, text="فتح وردية جديدة", command=self.open_shift_dialog).pack(side="left", padx=8)
        ttk.Button(top, text="إغلاق الوردية الحالية", command=self.close_shift_dialog).pack(side="left", padx=4)
        ttk.Label(top, text="رصيد أول المدة:").pack(side="left", padx=(14, 2))
        self.e_float = ttk.Entry(top, width=10)
        self.e_float.pack(side="left")
        self.e_float.insert(0, "0")

        mid = ttk.Frame(tab)
        mid.pack(fill="both", expand=True, padx=8)
        ttk.Label(mid, text="إضافة مصروف:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        row = ttk.Frame(mid)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="النوع (إيجار / رواتب / كهرباء / أخرى):").pack(side="left")
        self.e_exp_kind = ttk.Entry(row, width=18)
        self.e_exp_kind.pack(side="left", padx=4)
        ttk.Label(row, text="المبلغ:").pack(side="left")
        self.e_exp_amt = ttk.Entry(row, width=10)
        self.e_exp_amt.pack(side="left", padx=4)
        ttk.Label(row, text="ملاحظات:").pack(side="left")
        self.e_exp_notes = ttk.Entry(row, width=26)
        self.e_exp_notes.pack(side="left", padx=4)
        ttk.Button(row, text="حفظ المصروف", command=self.add_expense).pack(side="left", padx=6)
        ttk.Label(mid, text="مصروفات اليوم:", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 2))
        cols = ("kind", "amount", "notes", "user")
        self.tree_exp = ttk.Treeview(mid, columns=cols, show="headings", height=12)
        for c, t in zip(cols, ("النوع", "المبلغ", "ملاحظات", "المستخدم")):
            self.tree_exp.heading(c, text=t)
            self.tree_exp.column(c, width=200)
        self.tree_exp.pack(fill="both", expand=True)
        ttk.Button(mid, text="تحديث", command=self.cash_refresh).pack(pady=6, anchor="w")
        self.cash_refresh()

    def cash_refresh(self):
        if not hasattr(self, "lbl_shift"):
            return  # v6.14
        if self.current_shift:
            self.lbl_shift.config(text="الوردية الحالية: #%d — فتحت %s — رصيد أول المدة %s" % (
                self.current_shift["id"], self.current_shift["opened_at"],
                money(self.current_shift["opening_float"])))
        else:
            self.lbl_shift.config(text="لا توجد وردية مفتوحة — افتح وردية قبل البيع")
        for i in self.tree_exp.get_children():
            self.tree_exp.delete(i)
        for e in self.db.expenses_on():
            self.tree_exp.insert("", "end", values=(e["kind"], money(e["amount"]), e["notes"], e["user"]))
        ui_theme.stripe_rows(self.tree_exp, self.theme_name)
        self.update_topbar()

    def open_shift_dialog(self):
        if self.current_shift:
            messagebox.showinfo("تنبيه", "توجد وردية مفتوحة بالفعل")
            return
        try:
            sid = self.db.open_shift(self.username, safe_float(self.e_float.get()))
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        self.current_shift = self.db.open_shift_for(self.username)
        self.db.audit(self.username, "open_shift", "shift %s" % sid)
        self.cash_refresh()
        messagebox.showinfo("تم", "تم فتح الوردية #%d" % sid)

    def close_shift_dialog(self):
        if not self.current_shift:
            messagebox.showinfo("تنبيه", "لا توجد وردية مفتوحة")
            return
        # v5.7: the drawer is reconciled from THIS shift's own sales
        # (opening + cash collected - expenses - cash refunds), not
        # from whole-day all-cashier totals. The cashier counts the
        # drawer and the app reports the difference.
        try:
            summ = self.db.shift_summary(self.current_shift["id"])
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        # STEP2 (2A): sales made with no shift open are NEVER invisible —
        # warn here (same day) so the cashier sees them before closing.
        no_shift_txt = ""
        if summ.get("no_shift_count"):
            no_shift_txt = ("\n⚠️ مبيعات بدون وردية (%s): %d فاتورة بإجمالي %s — "
                            "ليست محسوبة في هذه الوردية، راجعها قبل الإغلاق." % (
                                summ["no_shift_date"], summ["no_shift_count"],
                                money(summ["no_shift_total"])))
        counted = simpledialog.askfloat(
            "إغلاق الوردية",
            "رصيد البداية: %s\nنقدي محصَّل في هذه الوردية: %s\nمصروفات الوردية: %s\n"
            "المتوقع في الدرج: %s%s\n\nأدخل المبلغ الذي عدّدته في الدرج:" % (
                money(summ["opening_float"]), money(summ["cash_collected"]),
                money(summ["expenses"]), money(summ["expected_cash"]), no_shift_txt))
        if counted is None:
            return
        try:
            summ = self.db.close_shift(self.current_shift["id"], counted)
        except ValueError as e:
            messagebox.showerror("خطأ", str(e))
            return
        self.db.audit(self.username, "close_shift",
                      "shift %s expected %.2f counted %.2f diff %.2f" % (
                          self.current_shift["id"], summ["expected_cash"],
                          summ["counted_cash"], summ["difference"]))
        self.current_shift = None
        self.cash_refresh()
        diff = summ["difference"]
        done_txt = ("المتوقع في الدرج: %s\nالذي عدّدته: %s\nالفرق: %s %s" % (
            money(summ["expected_cash"]), money(summ["counted_cash"]),
            money(abs(diff)),
            "(زيادة)" if diff > 0 else ("(عجز)" if diff < 0 else "(مطابق ✅)")))
        if summ.get("no_shift_count"):
            done_txt += ("\n\n⚠️ تذكير: توجد %d فاتورة بدون وردية (%s) بإجمالي %s "
                         "لم تُحسب في هذه الوردية." % (
                             summ["no_shift_count"], summ["no_shift_date"],
                             money(summ["no_shift_total"])))
        messagebox.showinfo("تم إغلاق الوردية", done_txt)

    def add_expense(self):
        if not self.e_exp_kind.get().strip() or safe_float(self.e_exp_amt.get()) <= 0:
            messagebox.showerror("خطأ", "أدخل نوع المصروف والمبلغ")
            return
        self.db.add_expense(self.e_exp_kind.get().strip(), safe_float(self.e_exp_amt.get()),
                            self.e_exp_notes.get().strip(), self.username,
                            shift_id=self.current_shift["id"] if self.current_shift else None)
        self.db.audit(self.username, "expense", "%s %.2f" % (self.e_exp_kind.get(), safe_float(self.e_exp_amt.get())))
        self.e_exp_amt.delete(0, "end")
        self.e_exp_notes.delete(0, "end")
        self.cash_refresh()
        self.reports_refresh()

    # ---------- v2: AI forecasting ----------
    def build_ai(self, outer=None):
        # v5.0: scrollable tab (was cut off at 1280x800 — expiry table
        # and chart were invisible below the fold).
        tab = self._scrollable_tab("🤖 التنبؤ الذكي", outer)
        self.ai_reorder = []
        self.ai_expiry = []
        self.ai_forecasts = {}
        self.ai_selected_drug = None
        if ai_forecast is None:
            ttk.Label(tab, text="⚠️ ملف ai_forecast.py غير موجود — انسخ ملفات التحديث v2 كاملة.",
                      font=("Segoe UI", 12, "bold"), foreground="red").pack(pady=20)
            return
        # Top controls
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="أفق التنبؤ (يوم):").pack(side="left")
        self.e_ai_horizon = ttk.Entry(top, width=6)
        self.e_ai_horizon.pack(side="left", padx=4)
        self.e_ai_horizon.insert(0, "30")
        ttk.Label(top, text="مدة التوريد (يوم):").pack(side="left", padx=(10, 2))
        self.e_ai_lead = ttk.Entry(top, width=6)
        self.e_ai_lead.pack(side="left", padx=4)
        self.e_ai_lead.insert(0, "3")
        ttk.Button(top, text="🔄 تحديث التنبؤ", command=self.ai_refresh).pack(side="left", padx=8)
        ttk.Button(top, text="📋 إنشاء قائمة طلب", command=self.ai_create_order_list).pack(side="left", padx=4)
        ttk.Button(top, text="📥 تصدير قائمة الطلب CSV", command=self.ai_export_reorder_csv).pack(side="left", padx=4)
        # Summary + honesty note
        self.lbl_ai_summary = ttk.Label(tab, text="", font=("Segoe UI", 11, "bold"),
                                        wraplength=1100, justify="left")
        self.lbl_ai_summary.pack(anchor="w", padx=10, pady=4)
        self.lbl_ai_note = ttk.Label(
            tab, text="التنبؤ تقديري ويعتمد على مبيعاتك المسجلة فقط — كل ما تبيع أكتر، الدقة تزيد. "
                      "مع تاريخ قليل تظهر ثقة منخفضة، وهذا مقصود: لا نريد أن يطلب البرنامج كميات كبيرة من تخمين ضعيف.",
            wraplength=1100, style="Muted.TLabel")
        self.lbl_ai_note.pack(anchor="w", padx=10, pady=2)
        # Summary cards (same style as Dashboard)
        self.ai_cards_frame = ttk.Frame(tab)
        self.ai_cards_frame.pack(fill="x", padx=10, pady=4)
        self.ai_cards = {}
        for _key, _title, _acc in [("critical", "حرجة تحتاج طلب", "#B91C1C"),
                                   ("high", "عالية الأولوية", "#B45309"),
                                   ("loss", "خسارة صلاحية متوقعة", "#B91C1C")]:
            _fr, _val, _sub = ui_theme.make_card(self.ai_cards_frame, _title, "—", "", _acc, self.theme_name)
            _fr.pack(side="left", fill="both", expand=True, padx=4)
            self.ai_cards[_key] = (_fr, _val, _sub)
        # Reorder table
        ttk.Label(tab, text="قائمة إعادة الطلب المقترحة (مرتبة حسب الأولوية — اضغط على سطر لعرض التفاصيل):",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(6, 2))
        cols = ("drug", "stock", "daily", "forecast", "rop", "suggest", "supplier", "urgency", "conf")
        self.tree_ai = ttk.Treeview(tab, columns=cols, show="headings", height=9)
        heads = {"drug": "الدواء", "stock": "المخزون (علبة)", "daily": "مبيعات/يوم (وحدة)",
                 "forecast": "توقع 30 يوم (وحدة)", "rop": "نقطة إعادة الطلب",
                 "suggest": "الكمية المقترحة (علبة)", "supplier": "المورد الأرخص",
                 "urgency": "الأولوية", "conf": "الثقة %"}
        for c in cols:
            self.tree_ai.heading(c, text=heads[c])
            self.tree_ai.column(c, width=120)
        self.tree_ai.column("drug", width=200)
        self.tree_ai.pack(fill="x", padx=10)
        self.tree_ai.bind("<<TreeviewSelect>>", lambda e: self.ai_show_detail())
        # Detail + chart
        self.lbl_ai_detail = ttk.Label(tab, text="اختر دواء من القائمة أعلاه لعرض تفاصيل التنبؤ.",
                                       wraplength=1100, justify="left")
        self.lbl_ai_detail.pack(anchor="w", padx=10, pady=4)
        self.txt_ai_chart = tk.Text(tab, width=110, height=6, font=("Consolas", 10))
        self.txt_ai_chart.pack(fill="x", padx=10)
        # Expiry risk table
        ttk.Label(tab, text="خطر انتهاء الصلاحية — الخسارة المتوقعة خلال 90 يوم:",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        cols2 = ("drug", "batch", "expiry", "qty", "sellable", "loss", "suggest")
        self.tree_ai_exp = ttk.Treeview(tab, columns=cols2, show="headings", height=7)
        heads2 = {"drug": "الدواء", "batch": "التشغيلة", "expiry": "تاريخ الصلاحية",
                  "qty": "الكمية (وحدة)", "sellable": "المتوقع بيعه",
                  "loss": "الخسارة المتوقعة (ج.م)", "suggest": "الاقتراح"}
        for c in cols2:
            self.tree_ai_exp.heading(c, text=heads2[c])
            self.tree_ai_exp.column(c, width=130)
        self.tree_ai_exp.column("suggest", width=280)
        self.tree_ai_exp.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.ai_refresh()

    def ai_refresh(self):
        if ai_forecast is None:
            return
        try:
            horizon = safe_int(self.e_ai_horizon.get(), 30)
            lead = safe_int(self.e_ai_lead.get(), 3)
        except Exception:
            horizon, lead = 30, 3
        horizon = max(7, min(90, horizon))
        lead = max(1, min(14, lead))
        self.ai_horizon = horizon
        self.ai_lead = lead
        try:
            self.ai_reorder = ai_forecast.generate_reorder_list(
                self.db, horizon_days=horizon, lead_time_days=lead, safety_days=2)
        except Exception as e:
            messagebox.showerror("خطأ في التنبؤ", str(e))
            self.ai_reorder = []
        # Cache + keep per-drug forecasts for the detail pane
        self.ai_forecasts = {}
        for r in self.ai_reorder:
            self.ai_forecasts[r["drug_id"]] = r
            try:
                self.db.cache_forecast(r["drug_id"], horizon, r["daily_rate"],
                                       r["forecast_total"], r["confidence"])
            except Exception:
                pass
        # Reorder table: show only drugs that actually need attention
        for i in self.tree_ai.get_children():
            self.tree_ai.delete(i)
        self.ai_visible = [r for r in self.ai_reorder if r["urgency"] in ("حرجة", "عالية", "عادية")]
        if not self.ai_visible:
            self.tree_ai.insert("", "end", values=(
                "لا توجد أصناف تحتاج طلب حالياً ✅", "—", "—", "—", "—", "—", "—", "—", "—"))
        for r in self.ai_visible:
            self.tree_ai.insert("", "end", values=(
                r["drug_name"], "%.1f" % r["stock_boxes"], "%.2f" % r["daily_rate"],
                "%.0f" % r["forecast_total"], "%.0f" % r["reorder_point"],
                r["suggested_boxes"], r["supplier_name"], r["urgency"],
                "%d%%" % r["confidence"]))
        # Expiry risk
        try:
            self.ai_expiry, total_loss = ai_forecast.expiry_risk_for_all(
                self.db, horizon_days=horizon)
        except Exception:
            self.ai_expiry, total_loss = [], 0.0
        for i in self.tree_ai_exp.get_children():
            self.tree_ai_exp.delete(i)
        for row in self.ai_expiry:
            if row["unsold_units"] <= 0:
                continue
            _rtag = {"عالية": "crit", "متوسطة": "high"}.get(row["risk"], "ok")
            self.tree_ai_exp.insert("", "end", values=(
                row["drug"], row["batch_no"], row["expiry"], row["qty_units"],
                row["expected_sell"], "%.2f" % row["loss_egp"],
                "%s (%s)" % (row["suggestion"], row["risk"])), tags=(_rtag,))
        # Summary cards
        try:
            fastest, slowest = ai_forecast.get_movers(self.db, days=30, limit=5)
        except Exception:
            fastest, slowest = [], []
        critical = [r for r in self.ai_reorder if r["urgency"] == "حرجة"]
        high = [r for r in self.ai_reorder if r["urgency"] == "عالية"]
        total_sold_30d = sum(f["units"] for f in fastest)
        if total_sold_30d == 0:
            fast_txt = "لا توجد مبيعات بعد"
            slow_txt = "لا توجد مبيعات بعد — لا يمكن تحديد الراكد"
        else:
            fast_txt = ", ".join("%s (%d)" % (f["drug_name"], f["units"]) for f in fastest[:3]) or "لا توجد مبيعات بعد"
            slow_txt = ", ".join("%s (%d)" % (s["drug_name"], s["units"]) for s in slowest[:3]) or "—"
        low_conf = [r for r in self.ai_reorder if r["daily_rate"] > 0 and r["confidence"] < 40]
        self.lbl_ai_summary.config(text=(
            "🧾 أصناف تحتاج طلب الآن: %d حرجة + %d عالية  |  💸 خسارة صلاحية متوقعة هذا الشهر: %s\n"
            "⚡ الأسرع مبيعاً (30 يوم): %s\n🐢 الأبطأ (مخزون راكد): %s\n"
            "⚠️ %d صنف بتنبؤ ثقة منخفضة (<40%%) — اعتمد على خبرتك قبل الطلب بكميات كبيرة."
            % (len(critical), len(high), money(total_loss), fast_txt, slow_txt, len(low_conf))))
        try:
            self.ai_cards["critical"][1].config(text=str(len(critical)))
            self.ai_cards["high"][1].config(text=str(len(high)))
            self.ai_cards["loss"][1].config(text=money(total_loss))
            self.ai_cards["loss"][2].config(text="تشغيلات تنتهي خلال 90 يوم")
            if low_conf:
                self.lbl_ai_note.config(text="⚠️ %d صنف بتنبؤ ثقة منخفضة (<40%%) — اعتمد على خبرتك قبل الطلب بكميات كبيرة." % len(low_conf))
        except Exception:
            pass
        if not fastest or sum(f["units"] for f in fastest) == 0:
            self.lbl_ai_note.config(text="لا توجد مبيعات مسجلة بعد في قاعدة البيانات — التنبؤ الآن تقديري جداً. "
                                        "سجّل مبيعات ومشتريات لمدة أسبوعين على الأقل وستبدأ الثقة والدقة في الارتفاع. "
                                        "يمكنك تجربة ميزة التنبؤ فوراً بإدخال مبيعات تجريبية من تبويب الكاشير.")
        else:
            self.lbl_ai_note.config(text="التنبؤ تقديري ويعتمد على مبيعاتك المسجلة فقط — كل ما تبيع أكتر، الدقة تزيد.")

        ui_theme.stripe_rows(self.tree_ai, self.theme_name)
        ui_theme.stripe_rows(self.tree_ai_exp, self.theme_name)

    def ai_show_detail(self):
        sel = self.tree_ai.selection()
        if not sel:
            return
        idx = self.tree_ai.index(sel[0])
        if idx >= len(self.ai_visible):
            return
        row = self.ai_visible[idx]
        drug = self.db.get_drug(row["drug_id"])
        if not drug:
            return
        self.ai_selected_drug = drug
        try:
            daily = ai_forecast.get_daily_sales(self.db, drug["id"], days=90)
            fc = ai_forecast.forecast_demand(daily, horizon_days=getattr(self, "ai_horizon", 30))
        except Exception:
            fc = {"daily_rate": row["daily_rate"], "trend": row["trend"],
                  "trend_pct": row["trend_pct"], "confidence": row["confidence"],
                  "method": row["method"], "nonzero_days": 0}
        stock_days = ("%.1f يوم" % row["days_of_stock"]) if row["days_of_stock"] < 900 else "— (لا يوجد معدل بيع)"
        self.lbl_ai_detail.config(text=(
            "تفاصيل: %s — معدل البيع %.2f وحدة/يوم | الاتجاه: %s (%+.1f%%) | الثقة: %d%%\n"
            "المخزون الحالي يكفي %s | نقطة إعادة الطلب: %.0f وحدة | الكمية المقترحة: %d علبة (%d وحدة) | الطريقة: %s"
            % (row["drug_name"], row["daily_rate"], row["trend"], row["trend_pct"],
               row["confidence"], stock_days, row["reorder_point"],
               row["suggested_boxes"], row["suggested_units"], row["method"])))
        try:
            self.txt_ai_chart.delete("1.0", "end")
            self.txt_ai_chart.insert("1.0", "مبيعات آخر 14 يوم (وحدة/يوم):\n" +
                                     ai_forecast.text_chart(daily, days=14))
        except Exception:
            pass

    def ai_create_order_list(self):
        if not getattr(self, "ai_visible", None):
            messagebox.showinfo("تنبيه", "لا توجد أصناف تحتاج طلب حالياً — حدّث التنبؤ أولاً")
            return
        need = [r for r in self.ai_visible if r["suggested_boxes"] > 0]
        if not need:
            messagebox.showinfo("تنبيه", "لا توجد كميات مقترحة — المخزون يغطي توقع الـ %d يوم القادمة" % getattr(self, "ai_horizon", 30))
            return
        by_supplier = {}
        for r in need:
            by_supplier.setdefault(r["supplier_name"], []).append(r)
        win = tk.Toplevel(self.root)
        win.title("قائمة الطلب المقترحة — مسودة (لم تُحفظ بعد)")
        win.geometry("720x480")
        txt = tk.Text(win, width=88, height=20, font=("Segoe UI", 11))
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        total_est = 0.0
        txt.insert("1.0", "قائمة طلب مقترحة من التنبؤ الذكي — مسودة للمراجعة قبل الشراء:\n\n")
        for sup, items in by_supplier.items():
            txt.insert("end", "المورد: %s\n" % sup)
            for r in items:
                est = (r["supplier_price"] or 0) * r["suggested_boxes"]
                total_est += est
                txt.insert("end", "  - %s: %d علبة (أولوية %s، ثقة %d%%)%s\n" % (
                    r["drug_name"], r["suggested_boxes"], r["urgency"], r["confidence"],
                    " — تكلفة تقديرية %s" % money(est) if r["supplier_price"] else ""))
            txt.insert("end", "\n")
        txt.insert("end", "التكلفة التقديرية الإجمالية: %s\n\n" % money(total_est))
        txt.insert("end", "⚠️ هذه مسودة فقط — راجع الكميات مع المورد قبل تأكيد أي شراء. لا يتم إنشاء فاتورة شراء تلقائياً.")
        txt.config(state="disabled")

        def add_to_purchase_draft():
            added = 0
            for r in need:
                drug = self.db.get_drug(r["drug_id"])
                if not drug:
                    continue
                self.purchase_lines.append({
                    "drug": drug, "qty_boxes": float(r["suggested_boxes"]),
                    "buy_price": float(r["supplier_price"] or drug["buy_price"]),
                    "sell_price": float(drug["sell_price"]),
                    "batch_no": "AI-%s" % date.today().isoformat(),
                    "expiry": "2027-12-31"})
                added += 1
            # v6.6: refresh the purchase tab table + both totals.
            self.pur_refresh_table()
            # Pre-select the most common supplier in the draft
            sups = [s for s in self.db.suppliers() if s["name"] in by_supplier]
            if sups:
                self.cb_supplier.set(sups[0]["name"])
            self.db.audit(self.username, "ai_order_draft", "%d lines from AI forecast" % added)
            win.destroy()
            self.notebook.select(2)  # purchases tab
            messagebox.showinfo("تم", "تمت إضافة %d صنف كمسودة فاتورة شراء.\n"
                                "راجع الكميات والأسعار والتشغيلات والصلاحية ثم اضغط «حفظ فاتورة الشراء»." % added)
        ttk.Button(win, text="➕ إضافة القائمة كمسودة فاتورة شراء (للمراجعة)",
                   command=add_to_purchase_draft).pack(pady=6)
        ttk.Button(win, text="إغلاق", command=win.destroy).pack(pady=4)

    def ai_export_reorder_csv(self):
        if not getattr(self, "ai_visible", None):
            messagebox.showinfo("تنبيه", "حدّث التنبؤ أولاً")
            return
        rows = [(r["drug_name"], "%.1f" % r["stock_boxes"], "%.2f" % r["daily_rate"],
                 "%.0f" % r["forecast_total"], "%.0f" % r["reorder_point"],
                 r["suggested_boxes"], r["supplier_name"], r["urgency"],
                 "%d%%" % r["confidence"]) for r in self.ai_visible]
        self._export_csv("ai_reorder_%s.csv" % date.today().isoformat(),
                         ["drug", "stock_boxes", "daily_rate", "forecast_30d",
                          "reorder_point", "suggested_boxes", "cheapest_supplier",
                          "urgency", "confidence_pct"], rows)

    # ---------- v4: Mobile companion + print queue ----------
    def build_mobile(self, tab=None):
        if tab is None:
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text="📱 الموبايل والطباعة")
        self.mobile_tab = tab
        # ---------- v4.4: SCROLLABLE Mobile tab (root cause of "no QR") --
        # Before v4.4 every section was packed directly on `tab` (a plain
        # Frame) with NO scrollbar at all, so on a normal-size window
        # everything below the fold — QR, diagnostics, pending-print
        # list — was unreachable and looked "not there". Now the whole
        # tab lives in a Canvas + vertical Scrollbar + inner Frame.
        # `tab` is re-pointed at the inner frame below, so ALL existing
        # widgets below keep their exact order/labels/commands — only
        # their parent changes from the outer tab to the inner frame.
        self._mobile_canvas = tk.Canvas(tab, highlightthickness=0)
        self._mobile_vscroll = ttk.Scrollbar(
            tab, orient="vertical", command=self._mobile_canvas.yview)
        self._mobile_canvas.configure(yscrollcommand=self._mobile_vscroll.set)
        self._mobile_vscroll.pack(side="right", fill="y")
        self._mobile_canvas.pack(side="left", fill="both", expand=True)
        _inner = ttk.Frame(self._mobile_canvas)
        self._mobile_scroll_inner = _inner
        self._mobile_canvas_window = self._mobile_canvas.create_window(
            (0, 0), window=_inner, anchor="nw")
        _inner.bind("<Configure>", lambda e: self._mobile_canvas.configure(
            scrollregion=self._mobile_canvas.bbox("all")))
        self._mobile_canvas.bind("<Configure>", lambda e: self._mobile_canvas.itemconfig(
            self._mobile_canvas_window, width=e.width))

        def _is_inside_mobile(widget):
            w = widget
            while w is not None:
                if w is tab:
                    return True
                w = getattr(w, "master", None)
            return False

        def _mobile_wheel(event):
            # Only scroll when the pointer is over this tab — bind_all
            # fires for the whole app, so guard by widget ancestry.
            try:
                if not _is_inside_mobile(event.widget):
                    return
            except Exception:
                return
            try:
                if getattr(event, "delta", 0):
                    self._mobile_canvas.yview_scroll(
                        -1 * int(event.delta / 120), "units")
                elif getattr(event, "num", None) == 4:
                    self._mobile_canvas.yview_scroll(-3, "units")
                elif getattr(event, "num", None) == 5:
                    self._mobile_canvas.yview_scroll(3, "units")
            except Exception:
                pass

        # Windows: <MouseWheel> (delta). Linux/Xvfb: Button-4/5.
        self.root.bind_all("<MouseWheel>", _mobile_wheel, add="+")
        self.root.bind_all("<Button-4>", _mobile_wheel, add="+")
        self.root.bind_all("<Button-5>", _mobile_wheel, add="+")
        tab = _inner
        ttk.Label(tab, text="📱 الموبايل والطباعة",
                  style="Header.TLabel").pack(anchor="w", padx=12, pady=(10, 2))
        # v4.4 hint: there is more below the fold (QR, diagnostics, invoices).
        ttk.Label(tab, text="⬇️ انزل لتحت لرؤية QR والفواتير",
                  font=("Segoe UI", 11, "bold"), foreground="#0F766E").pack(
                      anchor="w", padx=12, pady=(0, 2))
        ttk.Label(tab, text="نفس الواي فاي — شبكة محلية فقط.",
                  style="Muted.TLabel", wraplength=1100).pack(anchor="w", padx=12)
        # ---------- v5.4: Windows hotspot only ----------
        # v5.4: the whole app-owned "local Wi-Fi" card was removed at
        # the user's request — no SSID field, no password field, no
        # show-password checkbox, no Save button. The app no longer
        # invents its own hotspot name and never
        # overwrites the real Windows hotspot name/password.
        # What is left is a status line for the REAL Windows Mobile
        # Hotspot (Settings > Network & internet > Mobile hotspot):
        # "تشغيل الهوت سبوت" only calls StartTetheringAsync, i.e. it
        # turns on THAT same Windows hotspot with ITS existing name
        # and password — it does not create a second network.
        # The password is never shown: Windows does not reliably
        # expose it to scripts, and it is the one set in Settings.
        hcard = ttk.Frame(tab)
        hcard.pack(fill="x", padx=10, pady=(8, 2))
        self.lbl_hotspot_status = ttk.Label(
            hcard, text="هوت سبوت ويندوز: —",
            font=("Segoe UI", 12, "bold"))
        self.lbl_hotspot_status.pack(anchor="w", pady=2)
        self.lbl_hotspot_info = ttk.Label(
            hcard, text="الاسم وكلمة المرور من إعدادات ويندوز.",
            style="Muted.TLabel", wraplength=1100)
        self.lbl_hotspot_info.pack(anchor="w", pady=2)
        hbtns = ttk.Frame(hcard)
        hbtns.pack(anchor="w", pady=4)
        self.btn_hotspot_start = ttk.Button(
            hbtns, text="📶 تشغيل الهوت سبوت",
            command=self.hotspot_start_async, style="Accent.TButton")
        self.btn_hotspot_start.pack(side="left", padx=4)
        self.btn_hotspot_stop = ttk.Button(
            hbtns, text="⏹ إيقاف الهوت سبوت", command=self.hotspot_stop_async)
        self.btn_hotspot_stop.pack(side="left", padx=4)
        ttk.Button(hbtns, text="⚙️ إعدادات الهوت سبوت",
                   command=self.hotspot_open_settings).pack(side="left", padx=4)
        ttk.Button(hbtns, text="🔄 تحديث الحالة",
                   command=self.hotspot_refresh_async).pack(side="left", padx=4)
        ttk.Label(hcard, text="1) شغّل الهوت سبوت  2) اتصل به من الموبايل  3) افتح الرابط  4) أدخل PIN.",
                  wraplength=1100, style="Muted.TLabel").pack(anchor="w", pady=2)
        ttk.Label(hcard, text="الرابط يتغير بعد التشغيل — حدّث القائمة.",
                  wraplength=1100, style="Muted.TLabel").pack(anchor="w", pady=2)
        # Server status card
        card = ttk.Frame(tab)
        card.pack(fill="x", padx=10, pady=8)
        self.lbl_mobile_status = ttk.Label(card, text="السيرفر: متوقف", font=("Segoe UI", 12, "bold"))
        self.lbl_mobile_status.pack(anchor="w", pady=2)
        self.lbl_mobile_url = ttk.Label(card, text="الرابط: — (شغّل السيرفر أولاً)",
                                        font=("Segoe UI", 14, "bold"))
        self.lbl_mobile_url.pack(anchor="w", pady=2)
        # v5.4: the PIN lives inside a visible bordered frame so
        # it stands out clearly (LabelFrame + large bold digits).
        self.pin_frame = ttk.LabelFrame(card, text="رمز الموبايل (PIN)",
                                        padding=10)
        self.pin_frame.pack(anchor="w", pady=4)
        self.lbl_mobile_pin = ttk.Label(self.pin_frame, text="—",
                                        font=("Segoe UI", 20, "bold"))
        self.lbl_mobile_pin.pack(anchor="w")
        # v4.2 live status: "آخر تحديث: HH:MM:SS" + 🟢 متصل / 🔴 غير متصل
        # (يحدّثها فحص الـ 3 ثوانٍ _live_poll — لا زر تحديث يدوي مطلوب)
        self.lbl_live_update = ttk.Label(card, text="🟢 متصل — آخر تحديث: —",
                                         font=("Segoe UI", 11))
        self.lbl_live_update.pack(anchor="w", pady=2)
        btns = ttk.Frame(card)
        btns.pack(anchor="w", pady=6)
        self.btn_mobile_start = ttk.Button(btns, text="▶️ تشغيل السيرفر",
                                           command=self.mobile_toggle_server,
                                           style="Accent.TButton")
        self.btn_mobile_start.pack(side="left", padx=4)
        # v4.3: PC-ONLY test path — open the mobile website on THIS PC
        # (http://127.0.0.1:8080, localhost). No phone, no Wi-Fi, no
        # firewall involved. If the server is stopped, this starts it
        # first and opens the browser ~1s later (see
        # open_mobile_site_on_pc / _open_local_site).
        ttk.Button(btns, text="🌐 فتح على الكمبيوتر",
                   command=self.open_mobile_site_on_pc,
                   style="Success.TButton").pack(side="left", padx=4)
        ttk.Button(btns, text="🔑 تغيير الرمز",
                   command=self.regenerate_mobile_pin_ui).pack(side="left", padx=4)
        ttk.Button(btns, text="🔄 تحديث",
                   command=self.mobile_refresh).pack(side="left", padx=4)
        ttk.Label(card,
                  text="للتجربة على الكمبيوتر فقط.",
                  style="Muted.TLabel", wraplength=1100).pack(anchor="w", pady=(2, 0))
        # ---------- v4.1: ALL candidate URLs + diagnostics ----------
        ttk.Label(tab, text="🔗 الروابط — جرّب رابط شبكة هاتفك:",
                  style="Section.TLabel").pack(anchor="w", padx=12, pady=(8, 2))
        ttk.Label(tab, text="الموبايل على نفس الشبكة المكتوبة.",
                  style="Muted.TLabel", wraplength=1100).pack(anchor="w", padx=12)
        self.frame_mobile_urls = ttk.Frame(tab)
        self.frame_mobile_urls.pack(fill="x", padx=12, pady=2)
        self.txt_mobile_urls = tk.Text(self.frame_mobile_urls, width=90, height=3,
                                       font=("Consolas", 12), wrap="none")
        self.txt_mobile_urls.pack(side="left", fill="x", expand=True)
        self.txt_mobile_urls.config(state="disabled")
        self.frame_url_btns = ttk.Frame(self.frame_mobile_urls)
        self.frame_url_btns.pack(side="left", padx=6)
        # ---------- v4.11: HTTPS للمسح بالكاميرا (8443) ----------
        # لماذا HTTPS؟ رابط http:// العادي سياق غير آمن في كروم،
        # فالمتصفح نفسه يلغي getUserMedia / BarcodeDetector ولا يظهر
        # سؤال الإذن أبداً — وعلامة chrome://flags لم تصلّحها عند
        # محمد. رابط https://<IP>:8443 سياق آمن، فتعود الكاميرا.
        # الشهادة موقعة ذاتياً، فتظهر رسالة تحذير أول مرة فقط.
        ttk.Label(tab, text="🔒 رابط آمن (HTTPS) للمسح:",
                  style="Section.TLabel").pack(anchor="w", padx=12, pady=(8, 2))
        self.lbl_https_url = ttk.Label(tab, text="الرابط الآمن: — (شغّل السيرفر أولاً)",
                                       font=("Consolas", 12, "bold"))
        self.lbl_https_url.pack(anchor="w", padx=12, pady=2)
        hbtns = ttk.Frame(tab)
        hbtns.pack(anchor="w", padx=12, pady=2)
        ttk.Button(hbtns, text="📋 نسخ الرابط الآمن",
                   command=lambda: self._copy_text(self._https_url())).pack(side="left", padx=4)
        ttk.Label(tab, text="أول مرة: «متقدم» ثم «المتابعة إلى الموقع».",
                  style="Muted.TLabel", wraplength=1100).pack(anchor="w", padx=12)
        # ---------- v4.2: QR للاتصال السريع ----------
        # عناوين عربية بمحاذاة يمين (anchor="e") — إصلاح RTL عملي؛
        # Tkinter لا يدعم RTL الحقيقي، والرابط/الأرقام تبقى LTR.
        ttk.Label(tab, text="📷 QR للاتصال السريع",
                  style="Section.TLabel").pack(anchor="e", padx=12, pady=(8, 2))
        qframe = ttk.Frame(tab)
        qframe.pack(fill="x", padx=12, pady=2)
        self.qr_canvas = tk.Canvas(qframe, width=260, height=260, bg="white",
                                   highlightthickness=1, highlightbackground="#0F766E")
        self.qr_canvas.pack(side="left", padx=4)
        qctl = ttk.Frame(qframe)
        qctl.pack(side="left", fill="both", expand=True, padx=8)
        ttk.Label(qctl, text="اختر رابط شبكة هاتفك:",
                  style="Muted.TLabel").pack(anchor="e", pady=2)
        self.var_qr_url = tk.StringVar()
        self.cmb_qr_url = ttk.Combobox(qctl, textvariable=self.var_qr_url,
                                       width=42, state="readonly")
        self.cmb_qr_url.pack(anchor="e", pady=2)
        self.cmb_qr_url.bind("<<ComboboxSelected>>", self._qr_refresh)
        self.lbl_qr_url = ttk.Label(qctl, text="—", font=("Consolas", 12, "bold"))
        self.lbl_qr_url.pack(anchor="w", pady=2)
        qbtns = ttk.Frame(qctl)
        qbtns.pack(anchor="e", pady=4)
        ttk.Button(qbtns, text="🔄 تحديث QR",
                   command=self._qr_refresh).pack(side="left", padx=4)
        ttk.Button(qbtns, text="📋 نسخ",
                   command=lambda: self._copy_text(self.var_qr_url.get())).pack(side="left", padx=4)
        self.lbl_qr_note = ttk.Label(
            qctl, text="", wraplength=650, style="Muted.TLabel")
        self.lbl_qr_note.pack(anchor="e", pady=2)
        # v4.3: live QR status line — server running/stopped + last update.
        self.lbl_qr_status = ttk.Label(
            qctl, text="حالة رمز QR: —", font=("Segoe UI", 11, "bold"),
            wraplength=650)
        self.lbl_qr_status.pack(anchor="e", pady=2)
        ttk.Label(tab, text="🔍 اختبار الاتصال",
                  style="Section.TLabel").pack(anchor="w", padx=12, pady=(8, 2))
        diag_btns = ttk.Frame(tab)
        diag_btns.pack(anchor="w", padx=12, pady=2)
        ttk.Button(diag_btns, text="🔍 اختبار الاتصال",
                   command=self.diag_run_async, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(diag_btns, text="🛡️ إصلاح الاتصال",
                   command=self.firewall_fix_async, style="Success.TButton").pack(side="left", padx=4)
        ttk.Button(diag_btns, text="📋 نسخ النتائج",
                   command=self.diag_copy_results).pack(side="left", padx=4)
        self.txt_diag = tk.Text(tab, width=100, height=9, font=("Segoe UI", 11))
        self.txt_diag.pack(fill="x", padx=12, pady=4)
        self.txt_diag.insert("1.0", "اضغط «اختبار الاتصال».")
        self.txt_diag.config(state="disabled")
        self.diag_text = ""
        # ---------- v5.6: سجل الطلبات — من يطلب ماذا؟ ----------
        # محمد أبلغ عن "طلبات كثيرة لم أقم بها". السيرفر كان لا
        # يسجّل أي طلب، فلم يكن بالإمكان معرفة مصدرها. هذا القسم
        # يعرض آخر الطلبات (الوقت، IP، المسار، الحالة، المتصفح)
        # وعدد الطلبات لكل IP — لتعرف بنفسك هل هي من هاتفك، أم من
        # تبويب متصفح مفتوح على الكمبيوتر، أم من جهاز آخر على
        # الهوت سبوت.
        ttk.Label(tab, text="📋 الطلبات الأخيرة — من يطلب ماذا؟",
                  style="Section.TLabel").pack(anchor="w", padx=12, pady=(8, 2))
        req_btns = ttk.Frame(tab)
        req_btns.pack(anchor="w", padx=12, pady=2)
        ttk.Button(req_btns, text="🔄 تحديث الطلبات",
                   command=self.refresh_requests_view).pack(side="left", padx=4)
        ttk.Button(req_btns, text="🗑 مسح السجل",
                   command=self.clear_requests_view).pack(side="left", padx=4)
        self.lbl_req_summary = ttk.Label(
            tab, text="لا توجد طلبات مسجلة بعد — شغّل السيرفر ثم اضغط «تحديث الطلبات».",
            font=("Segoe UI", 11, "bold"), wraplength=1100)
        self.lbl_req_summary.pack(anchor="w", padx=12, pady=2)
        self.txt_requests = tk.Text(tab, width=100, height=8,
                                    font=("Consolas", 10))
        self.txt_requests.pack(fill="x", padx=12, pady=4)
        self.txt_requests.insert("1.0", "—")
        self.txt_requests.config(state="disabled")
        ttk.Label(tab, text="1) شغّل السيرفر  2) افتح الرابط  3) أدخل الرمز  4) احفظ الفاتورة  5) اطبعها هنا.",
                  wraplength=1100, style="Muted.TLabel").pack(anchor="w", padx=12, pady=4)
        ttk.Label(tab, text="🧾 بانتظار الطباعة:",
                  style="Section.TLabel").pack(anchor="w", padx=12, pady=(8, 2))
        cols = ("inv", "date", "cashier", "customer", "total", "payment")
        self.tree_mobile = ttk.Treeview(tab, columns=cols, show="headings", height=10)
        for c, t in zip(cols, ("رقم الفاتورة", "التاريخ", "الكاشير", "العميل",
                               "الإجمالي", "الدفع")):
            self.tree_mobile.heading(c, text=t)
            self.tree_mobile.column(c, width=160)
        self.tree_mobile.pack(fill="both", expand=True, padx=10)
        ui_theme.style_treeview(self.tree_mobile, self.theme_name)
        row = ttk.Frame(tab)
        row.pack(fill="x", padx=10, pady=8)
        ttk.Button(row, text="🧾 عرض الإيصال", command=self.mobile_show_receipt,
                   style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(row, text="🖨️ طباعة",
                   command=self.mobile_print_selected,
                   style="Success.TButton").pack(side="left", padx=4)
        ttk.Button(row, text="✏️ تعديل",
                   command=self.mobile_edit_selected,
                   style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(row, text="📋 كل الفواتير",
                   command=self.mobile_show_all).pack(side="left", padx=4)
        self.mobile_rows = []
        self.mobile_refresh()

    def mobile_pin(self):
        try:
            return self.db.ensure_mobile_pin()
        except Exception:
            return "------"

    def mobile_refresh(self):
        if not hasattr(self, "tree_mobile"):
            return
        try:
            self.mobile_rows = self.db.pending_phone_invoices()
            for i in self.tree_mobile.get_children():
                self.tree_mobile.delete(i)
            if not self.mobile_rows:
                self.tree_mobile.insert("", "end", values=(
                    "لا توجد فواتير بانتظار الطباعة", "—", "—", "—", "—", "—"))
            for s in self.mobile_rows:
                self.tree_mobile.insert("", "end", values=(
                    s["invoice_no"], s["date"], s["cashier"],
                    s.get("customer_name", "") or "عميل نقدي",
                    money(s["total"]), s["payment_method"]))
            ui_theme.stripe_rows(self.tree_mobile, self.theme_name)
            self._mobile_update_labels()
        except Exception:
            pass

    def _mobile_update_labels(self):
        try:
            running = getattr(self, "mobile_server", None) is not None and self.mobile_server.running
            if running:
                self.lbl_mobile_status.config(text="السيرفر: 🟢 يعمل")
                self.lbl_mobile_url.config(text="الرابط: %s" % self.mobile_server.url)
                self.btn_mobile_start.config(text="⏹ إيقاف السيرفر")
            else:
                self.lbl_mobile_status.config(text="السيرفر: 🔴 متوقف")
                self.lbl_mobile_url.config(text="الرابط: —")
                self.btn_mobile_start.config(text="▶️ تشغيل السيرفر")
            pin = self.mobile_pin()
            # v5.0: the PIN is an admin-only secret — cashiers see it
            # masked and cannot regenerate it (was ungated).
            pin_shown = pin if self.is_admin else "••••••"
            self.lbl_mobile_pin.config(text="%s" % pin_shown)
            if hasattr(self, "lbl_settings_pin"):
                self.lbl_settings_pin.config(text="رمز الموبايل الحالي (PIN): %s" % pin_shown)
        except Exception:
            pass
        self._mobile_update_url_list()

    def _copy_text(self, text):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.show_banner("تم نسخ: %s" % text, "success")
        except Exception:
            pass

    def _mobile_update_url_list(self):
        """Show EVERY candidate URL (v4.1). One IP is not enough:
        a phone on the hotspot needs 192.168.137.1, a phone on home
        Wi-Fi needs 192.168.1.5 — showing only one caused the timeout."""
        try:
            if not hasattr(self, "txt_mobile_urls"):
                return
            urls = []
            if mobile_server is not None:
                try:
                    urls = mobile_server.mobile_urls(8080)
                except Exception:
                    urls = []
            if not urls:
                urls = [{"ip": "—", "label": "لا توجد شبكة", "adapter": "",
                         "url": "لا يوجد عنوان شبكة — تأكد من اتصال الكمبيوتر بالواي فاي"}]
            self.txt_mobile_urls.config(state="normal")
            self.txt_mobile_urls.delete("1.0", "end")
            for u in urls:
                self.txt_mobile_urls.insert(
                    "end", "%s  (%s)\n" % (u["url"], u["label"]))
            self.txt_mobile_urls.config(state="disabled")
            for w in self.frame_url_btns.winfo_children():
                w.destroy()
            for u in urls:
                if u["url"].startswith("http"):
                    ttk.Button(self.frame_url_btns, text="📋 نسخ",
                               command=lambda t=u["url"]: self._copy_text(t)).pack(pady=2)
            # v4.11: HTTPS URL label (first HTTPS candidate, or a
            # clear reason when HTTPS is not running).
            try:
                if hasattr(self, "lbl_https_url"):
                    hurl = self._https_url()
                    if hurl:
                        self.lbl_https_url.config(text="الرابط الآمن: %s" % hurl)
                    elif getattr(self, "mobile_server", None) is not None and getattr(
                            self.mobile_server, "https_error", ""):
                        self.lbl_https_url.config(
                            text="الرابط الآمن: — (%s)" % self.mobile_server.https_error)
                    else:
                        self.lbl_https_url.config(text="الرابط الآمن: — (شغّل السيرفر أولاً)")
            except Exception:
                pass
            self._qr_refresh()
        except Exception:
            pass

    # ---------- v4.11: HTTPS URL (first candidate) ----------
    def _https_url(self):
        """First HTTPS candidate URL (https://<IP>:8443), or "".
        Empty when the server is stopped or HTTPS is not running."""
        try:
            srv = getattr(self, "mobile_server", None)
            if srv is not None and getattr(srv, "https_running", False):
                urls = srv.https_url_list
                if urls:
                    return urls[0]["url"]
        except Exception:
            pass
        return ""

    # ---------- v4.2: QR للاتصال السريع (qrgen.py — stdlib فقط) ----------
    def _qr_url_choices(self):
        """Candidate mobile URLs for the QR.

        HTTPS is first whenever it is running because the browser camera
        APIs require a secure context. HTTP remains a fallback for invoice
        entry when certificate setup failed. Every QR URL carries the
        current PIN in its fragment, never in a query parameter.
        """
        urls = []
        try:
            srv = getattr(self, "mobile_server", None)
            if srv is not None and getattr(srv, "https_running", False):
                urls += [u["url"] for u in srv.https_url_list
                         if u["url"].startswith("https")]
            if mobile_server is not None:
                urls += [u["url"] for u in mobile_server.mobile_urls(8080)
                         if u["url"].startswith("http")]
        except Exception:
            pass
        try:
            pin = self.db.ensure_mobile_pin() if getattr(self, "mobile_server", None) else ""
        except Exception:
            pin = ""
        seen = set()
        out = []
        for url in urls:
            qr_url = qr_url_with_pin(url, pin)
            if qr_url and qr_url not in seen:
                seen.add(qr_url)
                out.append(qr_url)
        return out

    def _qr_status(self, running, url=""):
        """Live QR status line under the QR: running/stopped + time.
        Cheap — never re-encodes the QR."""
        try:
            if not hasattr(self, "lbl_qr_status"):
                return
            from datetime import datetime as _dt
            now = _dt.now().strftime("%H:%M:%S")
            if running:
                self.lbl_qr_status.config(
                    text="🟢 QR حي — %s" % now)
            else:
                self.lbl_qr_status.config(
                    text="🔴 QR متوقف — %s" % now)
        except Exception:
            pass

    def _qr_refresh(self, event=None):
        """v4.3 LIVE connect-QR. (Re)draws ONLY when the URL or the
        server state changed — the 3s live poll and every tab-open
        call this method, but the cached QR is left alone when
        nothing changed, so the canvas never flickers and qrgen is
        not re-run on every poll. Never crashes the tab: if qrgen
        is missing or encoding fails, the URL is shown in large
        text with a copy button instead — a fake QR image is never
        drawn. HTTPS URLs are preferred for live camera scanning and
        include the current PIN only in the URL fragment.
        When the server is STOPPED, no stale QR is left on screen:
        the canvas shows "شغّل السيرفر أولاً لعرض الـ QR" instead."""
        try:
            if not hasattr(self, "qr_canvas"):
                return
            running = (getattr(self, "mobile_server", None) is not None
                       and self.mobile_server.running)
            choices = self._qr_url_choices()
            if hasattr(self, "cmb_qr_url"):
                self.cmb_qr_url["values"] = choices
            url = self.var_qr_url.get().strip()
            if choices and url not in choices:
                url = choices[0]
                self.var_qr_url.set(url)
            # --- server stopped: clear any stale QR, show the message ---
            if not running:
                self.lbl_qr_url.config(text="— السيرفر متوقف —")
                if getattr(self, "_qr_drawn_running", None) is not False:
                    self.qr_canvas.delete("all")
                    w = int(self.qr_canvas.cget("width") or 260)
                    h = int(self.qr_canvas.cget("height") or 260)
                    self.qr_canvas.create_text(
                        w // 2, h // 2,
                        text="شغّل السيرفر أولاً\nلعرض رمز QR",
                        font=("Segoe UI", 14, "bold"), fill="#B91C1C",
                        justify="center")
                    self._qr_drawn_url = None
                    self._qr_drawn_running = False
                self.lbl_qr_note.config(
                    text="السيرفر متوقف — شغّله أولاً.")
                self._qr_status(False)
                return
            # --- server running: same URL as drawn? Just refresh status. ---
            self.lbl_qr_url.config(text=url or "— لا يوجد رابط —")
            if (url and url == getattr(self, "_qr_drawn_url", None)
                    and getattr(self, "_qr_drawn_running", None) is True):
                self._qr_status(True, url)
                return
            self.qr_canvas.delete("all")
            if qrgen is None:
                raise RuntimeError("ملف qrgen.py غير موجود")
            if not url or not url.startswith("http"):
                raise RuntimeError("لا يوجد رابط صالح")
            qr = qrgen.encode_qr(url)
            n = qr.size
            cell = 7
            border = 4  # quiet zone (4 modules) — required to scan
            px = (n + 2 * border) * cell
            self.qr_canvas.config(width=px, height=px)
            for y in range(n):
                for x in range(n):
                    if qr.modules[y][x]:
                        x0 = (x + border) * cell
                        y0 = (y + border) * cell
                        self.qr_canvas.create_rectangle(
                            x0, y0, x0 + cell, y0 + cell,
                            fill="black", outline="black")
            self._qr_drawn_url = url
            self._qr_drawn_running = True
            if url.startswith("https"):
                self.lbl_qr_note.config(
                    text="امسح الرمز للدخول والمسح بالكاميرا. أول مرة: «متقدم» ثم «المتابعة». الكود يحتوي PIN — لا تشارك صورته.")
            else:
                self.lbl_qr_note.config(
                    text="HTTPS غير متاح حالياً — الفواتير تعمل، لكن المسح الحي يحتاج الرابط الآمن.")
            self._qr_status(True, url)
        except Exception as e:
            try:
                self._qr_drawn_url = None
                self._qr_drawn_running = None
                self.qr_canvas.delete("all")
                url = self.var_qr_url.get().strip()
                if url:
                    self.qr_canvas.create_text(
                        130, 130, text=url, font=("Consolas", 14, "bold"),
                        width=240, justify="center")
                self.lbl_qr_note.config(
                    text="تعذّر رسم QR (%s) — انسخ الرابط بالزر." % e)
                self._qr_status(
                    getattr(self, "mobile_server", None) is not None
                    and self.mobile_server.running)
            except Exception:
                pass

    # ---------- v4.3: فتح الموقع على الكمبيوتر فقط (127.0.0.1) ----------
    def open_mobile_site_on_pc(self):
        """Open the mobile website on THIS PC only:
        http://127.0.0.1:8080 in the default browser. Localhost
        bypasses the Windows Firewall inbound rule, so this tests
        the website with NO phone and NO Wi-Fi involved. If the
        server is stopped, start it first, then open the browser
        ~1s later via root.after — never blocks the UI. Phone
        access is NOT changed by this: the phone still needs the
        same Wi-Fi + the port-8080 firewall rule."""
        if mobile_server is None:
            messagebox.showerror("خطأ", "ملف mobile_server.py غير موجود — انسخ ملفات التحديث v4 كاملة.")
            return
        running = (getattr(self, "mobile_server", None) is not None
                   and self.mobile_server.running)
        if not running:
            self.show_banner("جارٍ تشغيل السيرفر…",
                             "info")
            self.mobile_toggle_server()
            try:
                self.root.after(1000, self._open_local_site)
            except Exception:
                self._open_local_site()
        else:
            self._open_local_site()

    def _open_local_site(self):
        """Actually open http://127.0.0.1:8080 — only if the server
        is really running now (the delayed call after a start may
        find that the start failed, e.g. port busy)."""
        url = "http://127.0.0.1:8080/"
        running = (getattr(self, "mobile_server", None) is not None
                   and self.mobile_server.running)
        if not running:
            messagebox.showerror(
                "خطأ", "تعذّر تشغيل السيرفر على 8080 — تأكد أنه لا يعمل سيرفر آخر.")
            return
        try:
            webbrowser.open(url)
            self.show_banner(
                "تم الفتح (%s) — أدخل PIN." % url,
                "success")
        except Exception as e:
            messagebox.showerror("خطأ", "تعذّر فتح المتصفح: %s" % e)

    def diag_copy_results(self):
        if getattr(self, "diag_text", ""):
            self._copy_text(self.diag_text)
        else:
            messagebox.showinfo("تنبيه", "شغّل «اختبار الاتصال» أولاً")

    def _diag_http_get(self, url):
        """GET one URL, timeout 3s. Returns (ok, detail). Never raises."""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PharmacyDiag/1.0"})
            with urllib.request.urlopen(req, timeout=3) as r:
                r.read(200)
            return True, "رد السيرفر (HTTP %d)" % r.status
        except urllib.error.HTTPError as e:
            return True, "رد السيرفر (HTTP %d — السيرفر شغال)" % e.code
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if "timed out" in str(reason).lower() or "timeout" in str(reason).lower():
                return False, "انتهت المهلة (Timeout) — مثل خطأ الهاتف تماماً"
            return False, "تعذر الوصول: %s" % reason
        except Exception as e:
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                return False, "انتهت المهلة (Timeout) — مثل خطأ الهاتف تماماً"
            return False, "تعذر الوصول: %s" % e

    def _diag_https_get(self, url):
        """GET one HTTPS URL, timeout 3s, IGNORING the self-signed
        cert (v4.11: the local cert is never trusted by the OS, so
        a normal verified request would always fail — the phone
        bypasses the same warning with Advanced > Proceed).
        Returns (ok, detail). Never raises."""
        try:
            ctx = ssl._create_unverified_context()
            req = urllib.request.Request(url, headers={"User-Agent": "PharmacyDiag/1.0"})
            with urllib.request.urlopen(req, timeout=3, context=ctx) as r:
                r.read(200)
            return True, "رد السيرفر (HTTPS %d)" % r.status
        except urllib.error.HTTPError as e:
            return True, "رد السيرفر (HTTPS %d — السيرفر شغال)" % e.code
        except Exception as e:
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                return False, "انتهت المهلة (Timeout)"
            return False, "تعذر الوصول: %s" % e

    def _diag_run(self):
        """Diagnostics worker (runs in a thread; returns text only)."""
        lines = []
        # 1. Server running?
        running = getattr(self, "mobile_server", None) is not None and self.mobile_server.running
        lines.append(("✅ السيرفر يعمل" if running
                      else "❌ السيرفر متوقف — شغّله أولاً"))
        # 2. Localhost test — if this fails, the server itself is down.
        ok, detail = self._diag_http_get("http://127.0.0.1:8080/")
        lines.append(("✅ اختبار من الكمبيوتر نفسه (8080): %s" % detail) if ok
                     else ("❌ اختبار من الكمبيوتر نفسه (8080): %s" % detail))
        # 2b. HTTPS localhost test (v4.11) — the scan URL. A failure
        # here means the cert is missing or HTTPS did not start,
        # even though HTTP works fine.
        ok, detail = self._diag_https_get("https://127.0.0.1:8443/")
        if ok:
            lines.append("✅ اختبار HTTPS (8443): %s" % detail)
        else:
            lines.append("❌ اختبار HTTPS (8443): %s — تأكد من الشهادة (مجلد certs أو cert.pem و key.pem بجانب البرنامج)." % detail)
        # 2c. v5.6: does the cert cover the PC's CURRENT IPs? A cert
        # generated for an old Wi-Fi IP does not cover the new one,
        # and the phone's camera then fails even after Proceed.
        try:
            srv = getattr(self, "mobile_server", None)
            if srv is not None:
                if getattr(srv, "cert_regenerated", False):
                    lines.append("✅ الشهادة: تم توليد شهادة جديدة تغطي عناوين الكمبيوتر الحالية.")
                elif getattr(srv, "cert_covers_current_ip", None) is False:
                    lines.append("⚠️ الشهادة: لا تغطي عنوان الكمبيوتر الحالي — "
                                 "أعد تشغيل السيرفر لتوليد شهادة جديدة (يحتاج PowerShell 7 أو openssl)، "
                                 "أو افتح رابط https واقبل التحذير.")
                elif getattr(srv, "cert_covers_current_ip", None) is True:
                    lines.append("✅ الشهادة: تغطي عنوان الكمبيوتر الحالي.")
        except Exception:
            pass
        # 3. LAN test for every candidate URL.
        urls = []
        if mobile_server is not None:
            try:
                urls = mobile_server.mobile_urls(8080)
            except Exception:
                urls = []
        if not urls:
            lines.append("❌ لا يوجد عنوان شبكة — فعّل الواي فاي.")
        for u in urls:
            ok, detail = self._diag_http_get(u["url"] + "/")
            lines.append(("✅ رابط %s (%s): %s" % (u["url"], u["label"], detail)) if ok
                         else ("❌ رابط %s (%s): %s" % (u["url"], u["label"], detail)))
        # 4. Firewall rules? (v4.12: BOTH ports, BOTH profiles.
        #    A private-ONLY rule is NOT enough — the Windows hotspot
        #    is a PUBLIC network, so it must be reported as blocked,
        #    not as "rule exists". PC-side URL tests can pass even
        #    then, because the PC talking to its own addresses does
        #    not go through the inbound rule. v4.11's bug was that
        #    this panel never checked port 8443 at all, so it could
        #    print ✅ while the phone on HTTPS was still blocked.)
        if firewall is None:
            lines.append("❓ فحص الفايروول: ملف firewall.py غير موجود — انسخ ملفات التحديث v4.1 كاملة.")
        else:
            try:
                st = firewall.firewall_status()
                ports = st.get("ports") or {}
                if st.get("exists") is True:
                    lines.append("✅ الفايروول: 8080 و 8443 مفتوحان (خاص + عام).")
                elif ports:
                    for port in (8080, 8443):
                        info = ports.get(port) or {}
                        priv, pub = info.get("private"), info.get("public")
                        if priv and pub:
                            lines.append("✅ الفايروول: البورت %d مفتوح (خاص + عام)." % port)
                        elif priv and not pub:
                            lines.append("❌ الفايروول: البورت %d مفتوح للشبكات الخاصة فقط — "
                                         "الهوت سبوت عام، لن يصل — اضغط «إصلاح الاتصال»." % port)
                        elif pub and not priv:
                            lines.append("❌ الفايروول: البورت %d مفتوح للشبكات العامة فقط — "
                                         "واي فاي البيت لن يصل — اضغط «إصلاح الاتصال»." % port)
                        elif info.get("unknown"):
                            lines.append("❓ الفايروول: تعذّر فحص البورت %d." % port)
                        else:
                            lines.append("❌ الفايروول: لا توجد قاعدة للبورت %d — اضغط «إصلاح الاتصال»." % port)
                    lines.append("⚠️ اختبار الكمبيوتر قد ينجح حتى لو الفايروول يقفل الهاتف.")
                elif st.get("exists") is False:
                    lines.append("❌ جدار الحماية: %s" % st.get("message", "تعذر الفحص"))
                else:
                    lines.append("❓ جدار الحماية: %s" % st.get("message", "تعذر الفحص"))
                if not st.get("admin"):
                    lines.append("⚠️ البرنامج لا يعمل كمسؤول — شغّل run.bat كمسؤول.")
            except Exception as e:
                lines.append("❓ جدار الحماية: تعذر الفحص (%s)" % e)
        # 5. Hotspot?
        try:
            if hotspot is not None:
                st = hotspot.get_hotspot_status()
                if st.get("state") == "On":
                    lines.append("✅ هوت سبوت ويندوز يعمل — الشبكة: %s" % (st.get("ssid") or "؟"))
                elif st.get("state") == "Off":
                    lines.append("ℹ️ هوت سبوت ويندوز متوقف.")
                else:
                    lines.append("❓ حالة هوت سبوت ويندوز غير معروفة: %s" % (st.get("error") or ""))
            else:
                lines.append("ℹ️ ملف hotspot.py غير موجود — لا يمكن فحص الهوت سبوت.")
        except Exception as e:
            lines.append("❓ حالة هوت سبوت ويندوز: تعذر الفحص (%s)" % e)
        # 6. Plain-Arabic conclusion.
        local_ok = any("✅ اختبار من الكمبيوتر نفسه" in ln for ln in lines)
        lan_ok = any(ln.startswith("✅ رابط") for ln in lines)
        fw_blocked = any(("لا توجد قاعدة للبورت" in ln
                          or "للشبكات الخاصة فقط" in ln
                          or "للشبكات العامة فقط" in ln) for ln in lines)
        fw_private_only = any("للشبكات الخاصة فقط" in ln for ln in lines)
        fw_8443_blocked = any("البورت 8443" in ln and ln.startswith("❌")
                              for ln in lines)
        if not running:
            lines.append("الخلاصة: السيرفر متوقف — شغّله أولاً.")
        elif fw_8443_blocked:
            lines.append("الخلاصة: الفايروول قافل 8443 — اضغط «إصلاح الاتصال» (كمسؤول).")
        elif local_ok and not lan_ok and fw_blocked:
            lines.append("الخلاصة: الفايروول قافل 8080 — اضغط «إصلاح الاتصال» (كمسؤول).")
        elif fw_private_only:
            lines.append("الخلاصة: الفايروول خاص فقط — الهوت سبوت عام، لن يصل. اضغط «إصلاح الاتصال».")
        elif local_ok and not lan_ok:
            lines.append("الخلاصة: السيرفر شغال محلياً ولا يرد على الشبكة — جرّب كل رابط.")
        elif lan_ok:
            lines.append("الخلاصة: الاتصال سليم من الكمبيوتر — الهاتف على شبكة مختلفة غالباً.")
        else:
            lines.append("الخلاصة: السيرفر لا يرد — أعد تشغيله.")
        return "\n".join(lines)

    def diag_run_async(self):
        self.show_banner("جارٍ الاختبار…", "info")

        def _work():
            text = self._diag_run()
            self._ui_post(lambda: self._diag_show(text))

        threading.Thread(target=_work, daemon=True).start()

    # ---------- v5.6: عرض سجل الطلبات ----------
    def refresh_requests_view(self):
        try:
            srv = getattr(self, "mobile_server", None)
            if srv is None or not srv.running:
                self.lbl_req_summary.config(
                    text="السيرفر متوقف — شغّله أولاً لعرض الطلبات.")
                self._set_requests_text("—")
                return
            sm = srv.request_summary()
            total = sm.get("total", 0)
            by_ip = sm.get("by_ip") or []
            by_path = sm.get("by_path") or []
            by_status = sm.get("by_status") or []
            top_ip = by_ip[0] if by_ip else None
            summary = ("إجمالي الطلبات منذ تشغيل السيرفر: %d" % total)
            if top_ip:
                summary += (" — أكثر IP طلباً: %s (%d طلب)" % (top_ip[0], top_ip[1]))
            summary += " — كل طلب شرعي من هاتفك ≈ طلب واحد كل 8 ثوانٍ."
            self.lbl_req_summary.config(text=summary)
            lines = []
            if by_ip:
                lines.append("حسب الجهاز (IP): " + ", ".join(
                    "%s: %d" % (ip, n) for ip, n in by_ip))
            if by_path:
                lines.append("حسب المسار: " + ", ".join(
                    "%s: %d" % (pa, n) for pa, n in by_path[:6]))
            if by_status:
                lines.append("حسب النتيجة: " + ", ".join(
                    "%s: %d" % (st, n) for st, n in by_status))
            lines.append("")
            for r in sm.get("recent") or []:
                lines.append("%s  %-15s %-4s %-28s %s  %s" % (
                    r.get("t", ""), r.get("ip", ""), r.get("method", ""),
                    r.get("path", "")[:28], r.get("status", ""),
                    r.get("ua", "")))
            if not (sm.get("recent") or []):
                lines.append("لا توجد طلبات بعد — افتح صفحة الموبايل وستظهر هنا.")
            self._set_requests_text("\n".join(lines))
        except Exception as e:
            self.lbl_req_summary.config(text="تعذّر عرض الطلبات: %s" % e)

    def _set_requests_text(self, text):
        try:
            self.txt_requests.config(state="normal")
            self.txt_requests.delete("1.0", "end")
            self.txt_requests.insert("1.0", text)
            self.txt_requests.config(state="disabled")
        except Exception:
            pass

    def clear_requests_view(self):
        try:
            srv = getattr(self, "mobile_server", None)
            if srv is not None:
                srv.clear_request_log()
            self.refresh_requests_view()
        except Exception:
            pass

    def _diag_show(self, text):
        self.diag_text = text
        try:
            self.txt_diag.config(state="normal")
            self.txt_diag.delete("1.0", "end")
            self.txt_diag.insert("1.0", text)
            self.txt_diag.config(state="disabled")
        except Exception:
            pass
        self.show_banner("اكتمل الاختبار.", "info")

    # ---------- v4.12: firewall for BOTH ports lives in firewall.py ----------
    # v4.11 kept a second, separate 8443 implementation here
    # (_netsh_8443 / _rule8443_profiles / _ensure_8443_rule). It did
    # NOT open 8443 on Mohamed's real PC (see firewall.py docstring
    # for the audit), so it was REMOVED. firewall.add_rule() now
    # ensures 8080 AND 8443 on private AND public, with
    # single-profile rules only, and firewall_fix_async below calls
    # it alone — its ok now means all four combinations are covered.

    def firewall_fix_async(self):
        if firewall is None:
            messagebox.showerror("خطأ", "ملف firewall.py غير موجود — انسخ ملفات التحديث v4.1 كاملة.")
            return
        self.show_banner("جارٍ فتح البورتين…", "info")

        def _work():
            # v4.12: ONE call — firewall.add_rule() now covers both
            # ports and both profiles, and returns True ONLY when all
            # four combinations are covered (no separate 8443 helper).
            ok, msg = firewall.add_rule()
            self._ui_post(lambda: self._firewall_fix_done(ok, msg))

        threading.Thread(target=_work, daemon=True).start()

    def _firewall_fix_done(self, ok, msg):
        if ok:
            self.show_banner(msg, "success")
            messagebox.showinfo("جدار الحماية", msg)
        else:
            self.show_banner(msg, "error")
            messagebox.showerror("جدار الحماية", msg)
        self.diag_run_async()

    def mobile_toggle_server(self):
        if mobile_server is None:
            messagebox.showerror("خطأ", "ملف mobile_server.py غير موجود — انسخ ملفات التحديث v4 كاملة.")
            return
        if getattr(self, "mobile_server", None) is not None and self.mobile_server.running:
            try:
                self.mobile_server.stop()
            except Exception:
                pass
            self.mobile_server = None
            self.show_banner("تم إيقاف سيرفر الموبايل", "info")
        else:
            srv = mobile_server.MobileServer(db_path=self.db.path, port=8080)
            if not srv.start():
                # v5.0: show the real reason (busy port vs other) —
                # before, every failure showed the same generic text.
                detail = getattr(srv, "start_error", "") or (
                    "تعذر تشغيل السيرفر على المنفذ 8080.\n"
                    "تأكد أنه لا يعمل سيرفر آخر على نفس المنفذ، وأن جدار حماية "
                    "ويندوز سمح لـ Python على الشبكات الخاصة.")
                messagebox.showerror("خطأ", detail)
                return
            self.mobile_server = srv
            self.db.audit(self.username, "mobile_server_start", srv.url)
            # v4.11: say plainly whether HTTPS (camera scan) is up.
            if getattr(srv, "https_running", False):
                self.show_banner(
                    "🟢 سيرفر الموبايل يعمل — للفواتير: %s — للمسح بالكاميرا: %s"
                    % (srv.url, srv.https_url), "success")
            else:
                self.show_banner(
                    "🟢 سيرفر الموبايل يعمل على HTTP فقط — HTTPS متوقف (%s) — "
                    "الفواتير تعمل، لكن المسح بالكاميرا لن يعمل."
                    % (getattr(srv, "https_error", "") or "الشهادة غير موجودة"),
                    "info")
        self._mobile_update_labels()

    def regenerate_mobile_pin_ui(self):
        if not self.is_admin:
            messagebox.showerror("صلاحيات", "تغيير رمز الموبايل صلاحية المدير فقط")
            return
        pin = self.db.regenerate_mobile_pin()
        self.db.audit(self.username, "mobile_pin_regen", "")
        self._mobile_update_labels()
        messagebox.showinfo("رمز جديد", "رمز الموبايل الجديد (PIN): %s\nأدخله على الهاتف عند الطلب." % pin)

    # ---------- v5: PC local Wi-Fi hotspot ----------
    def _hotspot_available(self):
        if hotspot is None:
            messagebox.showerror(
                "خطأ", "ملف hotspot.py غير موجود — انسخ ملفات التحديث v5 كاملة.")
            return False
        return True

    def _hotspot_done(self, ok, msg, refresh=True):
        """Called on the Tkinter thread after a hotspot action finishes."""
        if ok:
            self.show_banner(msg, "success")
            try:
                self.db.audit(self.username, "hotspot_action", msg[:200])
            except Exception:
                pass
        else:
            self.show_banner(msg, "error")
            messagebox.showerror("هوت سبوت ويندوز", msg)
        if refresh:
            self.hotspot_refresh_async()
            # The LAN IP can change once the hotspot is up — re-read
            # the mobile server URL so the phone link stays correct.
            try:
                self._mobile_update_labels()
            except Exception:
                pass

    def _hotspot_run(self, fn, what):
        """Run a hotspot.py call in a background thread so the UI never
        freezes while PowerShell talks to Windows (up to 60s)."""
        if not self._hotspot_available():
            return
        self.show_banner("جارٍ %s — انتظر لحظات..." % what, "info")
        self.btn_hotspot_start.config(state="disabled")
        self.btn_hotspot_stop.config(state="disabled")

        def _done(ok, msg):
            try:
                self.btn_hotspot_start.config(state="normal")
                self.btn_hotspot_stop.config(state="normal")
            except Exception:
                pass
            self._hotspot_done(ok, msg)

        def _marshal(ok, msg):
            # hotspot.run_in_thread calls done() from the worker
            # thread; bounce back to the Tkinter thread via the
            # queue (never root.after from a worker thread).
            self._ui_post(lambda: _done(ok, msg))

        hotspot.run_in_thread(fn, done=_marshal)

    def hotspot_start_async(self):
        self._hotspot_run(hotspot.start_hotspot, "تشغيل هوت سبوت ويندوز")

    def hotspot_stop_async(self):
        self._hotspot_run(hotspot.stop_hotspot, "إيقاف هوت سبوت ويندوز")

    def hotspot_refresh_async(self):
        if not self._hotspot_available():
            return

        def _fetch():
            st = hotspot.get_hotspot_status()
            return True, st  # never an error to the banner; shown in labels

        def _apply(ok, st):
            # v5.4: show ONLY the real Windows hotspot name as read
            # from Windows. The password is never displayed (Windows
            # does not reliably expose it, and it is the one set in
            # Settings). If Windows gives no SSID, show the PC name
            # as a hint — Windows names its hotspot after the PC
            # (e.g. DESKTOP-XXXX 3602) — never invent a name.
            try:
                state = st.get("state", "Unknown")
                ssid = (st.get("ssid") or "").strip()
                pc_name = ""
                try:
                    pc_name = hotspot.pc_hostname()
                except Exception:
                    pc_name = ""
                if state == "On":
                    self.lbl_hotspot_status.config(
                        text="هوت سبوت ويندوز: 🟢 يعمل — الشبكة: %s" % (
                            ssid or "؟"))
                elif state == "Off":
                    self.lbl_hotspot_status.config(
                        text="هوت سبوت ويندوز: 🔴 متوقف")
                else:
                    self.lbl_hotspot_status.config(
                        text="هوت سبوت ويندوز: ❓ غير معروف — %s" % (
                            st.get("error", "") or "اضغط «تشغيل» للتجربة."))
                if ssid:
                    self.lbl_hotspot_info.config(
                        text="الشبكة: %s — كلمة المرور: من إعدادات ويندوز "
                             "(الإعدادات > الشبكة والإنترنت > Mobile hotspot)." % ssid)
                elif pc_name:
                    self.lbl_hotspot_info.config(
                        text="الاسم وكلمة المرور من إعدادات ويندوز — "
                             "اسم الكمبيوتر: %s (اسم الهوت سبوت مشتق منه)." % pc_name)
                else:
                    self.lbl_hotspot_info.config(
                        text="الاسم وكلمة المرور من إعدادات ويندوز — "
                             "شاهدهما وغيّرهما من الإعدادات > الشبكة والإنترنت > "
                             "Mobile hotspot (زر «إعدادات الهوت سبوت»).")
            except Exception:
                pass

        def _marshal(ok, st):
            # Runs in the worker thread — post to the main thread
            # via the queue (never root.after from a worker thread).
            self._ui_post(lambda: _apply(ok, st))

        threading.Thread(
            target=lambda: _marshal(*_fetch()), daemon=True).start()

    def hotspot_open_settings(self):
        if not self._hotspot_available():
            return
        if hotspot.open_hotspot_settings():
            self.show_banner("تم فتح إعدادات الهوت سبوت في ويندوز — "
                             "فعّل Mobile hotspot وانسخ الاسم وكلمة المرور.", "info")
        else:
            messagebox.showinfo(
                "الإعدادات",
                "افتح يدوياً: الإعدادات > الشبكة والإنترنت > Mobile hotspot")

    def _selected_mobile_sale(self):
        sel = self.tree_mobile.selection()
        if not sel:
            messagebox.showinfo("تنبيه", "اختر فاتورة من القائمة أولاً")
            return None
        return self.mobile_rows[self.tree_mobile.index(sel[0])]

    def receipt_lines_for_sale(self, sale):
        items = self.db.get_grouped_sale_items(sale["id"])
        lines = ["Pharmacy Enterprise",
                 self.db.get_setting("pharmacy_name", "صيدلية المؤسسة") or "صيدلية المؤسسة"]
        _phone = self.db.get_setting("pharmacy_phone", "")
        if _phone:
            lines.append("تليفون: %s" % _phone)
        lines += ["فاتورة: %s" % sale["invoice_no"],
                  "التاريخ: %s" % sale["date"],
                  "-" * 34]
        _line_disc_total = 0.0
        for it in items:
            _ld = float(it.get("line_discount") or 0)
            _line_disc_total += _ld
            _txt = "%s x%s @ %s = %s" % (
                it["trade_en"], it["qty_display"],
                money(it["unit_price"]), money(it["line_total"]))
            if _ld:
                _txt += "  (خصم: %s)" % money(_ld)
            lines.append(_txt)
        lines.append("-" * 34)
        _total_disc = _line_disc_total + float(sale.get("discount") or 0)
        if _total_disc:
            lines.append("المجموع قبل الخصم: %s" % money(float(sale["subtotal"] or 0) + _line_disc_total))
            lines.append("خصم الأصناف: %s" % money(_line_disc_total))
            lines.append("خصم الفاتورة: %s" % money(sale["discount"]))
            lines.append("إجمالي الخصم: %s" % money(_total_disc))
        lines += ["الإجمالي: %s" % money(sale["total"]),
                  "المدفوع: %s   الباقي: %s" % (money(sale["paid"]), money(sale["change_amount"])),
                  "شكراً لزيارتك"]
        return lines

    def mobile_show_receipt(self):
        sale = self._selected_mobile_sale()
        if not sale:
            return
        self._open_receipt_window(sale)

    # ---------- v5.10 (audit step 3): printing ----------
    def _printer_settings(self):
        """Printer settings from the DB. Every default keeps the OLD
        behaviour (Windows default printer, 80mm, no drawer kick), so
        existing installs print exactly as before until the user
        changes something in Settings."""
        defaults = {"type": "windows", "name": "", "width": "80mm",
                    "kick": False, "cp864": 37, "cp1256": 50}
        if receipt_printer is None:
            return defaults
        g = self.db.get_setting
        try:
            cp864 = int(g(receipt_printer.SETTING_CP864_PAGE, "37") or 37)
        except (TypeError, ValueError):
            cp864 = 37
        try:
            cp1256 = int(g(receipt_printer.SETTING_CP1256_PAGE, "50") or 50)
        except (TypeError, ValueError):
            cp1256 = 50
        ptype = g(receipt_printer.SETTING_PRINTER_TYPE, "windows") or "windows"
        return {"type": ptype if ptype in ("windows", "escpos") else "windows",
                "name": g(receipt_printer.SETTING_PRINTER_NAME, "") or "",
                "width": g(receipt_printer.SETTING_PRINTER_WIDTH, "80mm") or "80mm",
                "kick": (g(receipt_printer.SETTING_PRINTER_KICK, "0") or "0") == "1",
                "cp864": max(0, min(255, cp864)),
                "cp1256": max(0, min(255, cp1256))}

    def _print_lines(self, lines, filename, is_cash=False, escpos_data=None):
        """The ONE print path for receipts and labels. Saves the text
        file under receipts/ (old files pruned first), then prints:
        raw ESC/POS if that is configured, otherwise the old Windows
        default-printer path. A failed raw send falls back to the
        Windows path and says so — printing never silently dies.
        ``escpos_data``: prebuilt ESC/POS bytes (labels); None means
        build a receipt (drawer kick only when ``is_cash``).
        Returns (ok, message, path)."""
        if receipt_printer is None:
            # printer.py missing — old behaviour, app root (never crash
            # printing because a patch file is absent).
            path = os.path.join(BASE, filename)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except Exception as e:
                return False, "تعذر حفظ الإيصال: %s" % e, path
            if os.name == "nt":
                try:
                    os.startfile(path, "print")  # noqa: S606 - local file
                    return True, "طُبعت بطابعة ويندوز الافتراضية", path
                except Exception as e:
                    return False, "لم تُطبع: %s" % e, path
            return False, "حُفظ في:\n%s" % path, path
        try:
            receipt_printer.prune_receipts(BASE)
        except Exception:
            pass
        try:
            path = receipt_printer.save_text(BASE, filename, "\n".join(lines))
        except Exception as e:
            return False, "تعذر حفظ الإيصال: %s" % e, os.path.join(BASE, filename)
        ps = self._printer_settings()
        note = ""
        if ps["type"] == "escpos":
            if os.name != "nt":
                note = "الطباعة المباشرة ESC/POS متاحة على ويندوز فقط — "
            else:
                if escpos_data is None:
                    escpos_data = receipt_printer.build_escpos_receipt(
                        lines,
                        width_chars=receipt_printer.width_chars_for(ps["width"]),
                        kick=bool(ps["kick"] and is_cash),
                        cp864_page=ps["cp864"], cp1256_page=ps["cp1256"])
                ok, msg = receipt_printer.send_raw_windows(ps["name"], escpos_data)
                if ok:
                    return True, "طُبعت مباشرة على طابعة ESC/POS (%s)" % ps["name"], path
                note = "تعذّرت الطباعة المباشرة (%s) — " % msg
        if os.name == "nt":
            try:
                os.startfile(path, "print")  # noqa: S606 - local file, user printer
                return True, note + "طُبعت بطابعة ويندوز الافتراضية", path
            except Exception as e:
                return False, note + "لم تُطبع: %s" % e, path
        return False, note + "حُفظ في:\n%s\nاطبعه من الملف." % path, path

    def _pos_receipt_print(self, win, inv, lines, pay):
        """Print button on the POS receipt window. NOTE: this does NOT
        mark anything printed — the printed flag is only tracked for
        mobile-queue invoices (see _open_receipt_window)."""
        ok, msg, path = self._print_lines(
            lines, "receipt_%s.txt" % inv.replace("-", "_"),
            is_cash=(pay == "cash"))
        if ok:
            self.show_banner("🖨️ طُبعت الفاتورة %s — %s" % (inv, msg), "success")
            win.destroy()
        else:
            messagebox.showinfo("لم تُطبع بعد", "حُفظ في:\n%s\n%s" % (path, msg))

    def _open_receipt_window(self, sale):
        lines = self.receipt_lines_for_sale(sale)
        win = tk.Toplevel(self.root)
        win.title("إيصال %s" % sale["invoice_no"])
        txt = tk.Text(win, width=54, height=24, font=("Consolas", 11))
        txt.pack(padx=10, pady=10)
        txt.insert("1.0", "\n".join(lines))
        # v5.9: totals + change stand out in bold in the preview.
        txt.tag_configure("bold", font=("Consolas", 12, "bold"))
        for _i, _ln in enumerate(lines, start=1):
            if _ln.startswith(("الإجمالي:", "المدفوع:", "المجموع:", "الخصم:")):
                txt.tag_add("bold", "%d.0" % _i, "%d.end" % _i)
        txt.config(state="disabled")

        def do_print():
            # v5.10 (audit step 3): the receipt is saved under receipts/
            # and printed through the shared path (ESC/POS raw if
            # configured, else the old Windows-default print). The
            # drawer kicks ONLY on a cash sale with a raw ESC/POS
            # printer (see printer.py) — never to a normal printer.
            ok, msg, path = self._print_lines(
                lines, "receipt_%s.txt" % sale["invoice_no"].replace("-", "_"),
                is_cash=(sale.get("payment_method") == "cash"))
            if not ok:
                # v5.0: NOT printed — say so, and do NOT mark it printed.
                messagebox.showinfo("لم تُطبع بعد",
                                    "حُفظ في:\n%s\n%s — وستبقى في «بانتظار الطباعة»." % (path, msg))
                return
            try:
                self.db.mark_printed(sale["id"])
                self.db.audit(self.username, "mobile_print", sale["invoice_no"])
            except Exception:
                pass
            self.mobile_refresh()
            self.show_banner("🖨️ طُبعت الفاتورة %s — %s" % (sale["invoice_no"], msg), "success")
            win.destroy()
        ttk.Button(win, text="🖨️ طباعة", command=do_print,
                   style="Success.TButton").pack(pady=(0, 10))

    def mobile_print_selected(self):
        sale = self._selected_mobile_sale()
        if not sale:
            return
        self._open_receipt_window(sale)

    def mobile_show_all(self):
        rows = self.db.phone_invoices(limit=50)
        win = tk.Toplevel(self.root)
        win.title("كل فواتير الهاتف")
        txt = tk.Text(win, width=80, height=22, font=("Segoe UI", 11))
        txt.pack(padx=10, pady=10)
        txt.insert("1.0", "فواتير الهاتف (الأحدث أولاً — %d فاتورة):\n\n" % len(rows))
        for s in rows:
            done = "🖨️ مطبوعة %s" % s["printed_at"] if s.get("printed_at") else "⏳ بانتظار الطباعة"
            txt.insert("end", "- %s | %s | %s | %s | %s\n" % (
                s["invoice_no"], s["date"], money(s["total"]), s["payment_method"], done))
        if not rows:
            txt.insert("end", "لا توجد فواتير من الهاتف بعد.")
        txt.config(state="disabled")

    # ---------- Settings ----------
    def build_settings(self, outer=None):
        # v5.0: scrollable tab (backup/import/audit were invisible at
        # 1280x800 — content is ~1225px, the tab is 652px).
        tab = self._scrollable_tab("⚙️ الإعدادات", outer)
        f = ttk.Frame(tab)
        f.pack(fill="both", expand=True, padx=14, pady=12)
        ttk.Label(f, text="إعدادات النظام", style="Header.TLabel").pack(anchor="w", pady=6)
        ttk.Label(f, text="اسم الصيدلية:").pack(anchor="w")
        self.e_pharmacy = ttk.Entry(f, width=50)
        self.e_pharmacy.pack(anchor="w", pady=2)
        row = self.db.conn.execute("SELECT value FROM settings WHERE key='pharmacy_name'").fetchone()
        self.e_pharmacy.insert(0, row["value"] if row else "صيدلية المؤسسة")
        # v6.3: pharmacy phone — shown on receipts and barcode labels.
        ttk.Label(f, text="تليفون الصيدلية:").pack(anchor="w")
        self.e_pharmacy_phone = ttk.Entry(f, width=50)
        self.e_pharmacy_phone.pack(anchor="w", pady=2)
        _ph = self.db.get_setting("pharmacy_phone", "")
        self.e_pharmacy_phone.insert(0, _ph)
        ttk.Button(f, text="حفظ اسم وتليفون الصيدلية", command=self.save_pharmacy_name).pack(anchor="w", pady=4)
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(f, text="المظهر:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.var_theme = tk.StringVar(value=self.theme_name)
        _theme_row = ttk.Frame(f)
        _theme_row.pack(anchor="w", pady=4)
        ttk.Radiobutton(_theme_row, text="☀️ فاتح (افتراضي)", variable=self.var_theme, value="light").pack(side="left", padx=4)
        ttk.Radiobutton(_theme_row, text="🌙 داكن", variable=self.var_theme, value="dark").pack(side="left", padx=4)
        ttk.Button(_theme_row, text="تطبيق المظهر",
                   command=lambda: self.apply_theme_now(self.var_theme.get())).pack(side="left", padx=8)
        ttk.Label(f, text="يُحفظ اختيارك في قاعدة البيانات ويُطبق فوراً على معظم الشاشات.",
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)
        # ---------- v5.9: 🎨 التخصيص — every look choice in one place ----------
        ttk.Label(f, text="🎨 التخصيص:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(f, text="لون التمييز:").pack(anchor="w")
        self.var_accent = tk.StringVar(value=getattr(self, "ui_accent", "teal"))
        self.cb_accent = ttk.Combobox(f, textvariable=self.var_accent, width=30, state="readonly",
                                      values=list(ui_theme.ACCENTS.keys()))
        self.cb_accent.pack(anchor="w", pady=2)
        ttk.Label(f, text=" | ".join("%s = %s" % (v["label"], k)
                                      for k, v in ui_theme.ACCENTS.items())).pack(anchor="w")
        ttk.Label(f, text="حجم الخط:").pack(anchor="w", pady=(6, 0))
        self.var_fontsize = tk.StringVar(value=getattr(self, "ui_font_size", "normal"))
        self.cb_fontsize = ttk.Combobox(f, textvariable=self.var_fontsize, width=30, state="readonly",
                                        values=["normal", "large", "xlarge"])
        self.cb_fontsize.pack(anchor="w", pady=2)
        ttk.Label(f, text="بطاقات لوحة التحكم الظاهرة (ألغِ تحديد أي بطاقة لإخفائها):").pack(anchor="w", pady=(6, 0))
        self.dash_card_vars = {}
        _card_labels = [("sales", "مبيعات اليوم"), ("profit", "صافي ربح اليوم"), ("cash", "نقدي اليوم"),
                        ("invoices", "فواتير اليوم"), ("low", "أصناف ناقصة"), ("expiry", "قريبة الانتهاء"),
                        ("critical", "طلبات حرجة"), ("inv_value", "قيمة المخزون")]
        _vis = self._dash_visible_cards()
        _crow = ttk.Frame(f); _crow.pack(anchor="w", pady=2)
        for _k, _lbl in _card_labels:
            _v = tk.BooleanVar(value=_k in _vis)
            self.dash_card_vars[_k] = _v
            ttk.Checkbutton(_crow, text=_lbl, variable=_v).pack(side="left", padx=3)
        self.var_alerts_top = tk.BooleanVar(value=getattr(self, "ui_alerts_top", True))
        ttk.Checkbutton(f, text="التنبيهات في أعلى لوحة التحكم (قبل الأكثر مبيعاً)",
                        variable=self.var_alerts_top).pack(anchor="w", pady=4)
        ttk.Button(f, text="✅ تطبيق التخصيص", style="Accent.TButton",
                   command=lambda: self.apply_customization(
                       self.var_accent.get(), self.var_fontsize.get(),
                       [k for k, v in self.dash_card_vars.items() if v.get()],
                       self.var_alerts_top.get())).pack(anchor="w", pady=6)
        ttk.Label(f, text="يُحفظ كل اختيار في قاعدة البيانات ويبقى بعد إعادة التشغيل — ويمكنك تغييره في أي وقت من هنا.",
                  style="Muted.TLabel", wraplength=700).pack(anchor="w")
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(f, text="📱 الموبايل:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.lbl_settings_pin = ttk.Label(f, text="رمز الموبايل الحالي (PIN): —")
        self.lbl_settings_pin.pack(anchor="w")
        try:
            self.lbl_settings_pin.config(text="رمز الموبايل الحالي (PIN): %s" % self.db.ensure_mobile_pin())
        except Exception:
            pass
        ttk.Button(f, text="🔑 تغيير رمز الموبايل", command=self.regenerate_mobile_pin_ui).pack(anchor="w", pady=4)
        ttk.Label(f, text="من تبويب «الموبايل والطباعة» شغّل السيرفر، ثم افتح الرابط على الهاتف (نفس الواي فاي) وأدخل الرمز.",
                  style="Muted.TLabel", wraplength=700).pack(anchor="w")
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)
        # ---------- v5.10 (audit step 3): 🖨️ الطباعة ----------
        ttk.Label(f, text="🖨️ الطباعة:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        _ps = self._printer_settings()
        ttk.Label(f, text="نوع الطابعة:").pack(anchor="w")
        self.var_printer_type = tk.StringVar(value=_ps["type"])
        _prow = ttk.Frame(f)
        _prow.pack(anchor="w", pady=2)
        ttk.Radiobutton(_prow, text="طابعة ويندوز الافتراضية (الوضع القديم)",
                        variable=self.var_printer_type, value="windows").pack(side="left", padx=4)
        ttk.Radiobutton(_prow, text="طابعة حرارية ESC/POS مباشرة (خام)",
                        variable=self.var_printer_type, value="escpos").pack(side="left", padx=4)
        ttk.Label(f, text="اسم طابعة ESC/POS (أو منفذ مثل COM1):").pack(anchor="w", pady=(6, 0))
        _names = receipt_printer.list_windows_printers() if receipt_printer is not None else []
        self.var_printer_name = tk.StringVar(value=_ps["name"])
        self.cb_printer_name = ttk.Combobox(f, textvariable=self.var_printer_name,
                                            width=48, values=_names)
        self.cb_printer_name.pack(anchor="w", pady=2)
        ttk.Label(f, text="عرض الورق:").pack(anchor="w", pady=(6, 0))
        self.var_printer_width = tk.StringVar(value=_ps["width"])
        ttk.Combobox(f, textvariable=self.var_printer_width, width=12, state="readonly",
                     values=["80mm", "58mm"]).pack(anchor="w", pady=2)
        self.var_printer_kick = tk.BooleanVar(value=_ps["kick"])
        ttk.Checkbutton(f, text="فتح درج النقود عند البيع النقدي (ESC/POS فقط — لا يُرسل أبداً لطابعة ويندوز)",
                        variable=self.var_printer_kick).pack(anchor="w", pady=4)
        _cprow = ttk.Frame(f)
        _cprow.pack(anchor="w", pady=2)
        ttk.Label(_cprow, text="رقم صفحة CP864:").pack(side="left")
        self.e_cp864 = ttk.Entry(_cprow, width=6)
        self.e_cp864.pack(side="left", padx=4)
        self.e_cp864.insert(0, str(_ps["cp864"]))
        ttk.Label(_cprow, text="رقم صفحة Windows-1256:").pack(side="left", padx=(10, 0))
        self.e_cp1256 = ttk.Entry(_cprow, width=6)
        self.e_cp1256.pack(side="left", padx=4)
        self.e_cp1256.insert(0, str(_ps["cp1256"]))
        ttk.Label(f, text="تُحفظ الإيصالات في مجلد receipts/ داخل مجلد البرنامج، وتُحذف الملفات الأقدم من 30 يوماً تلقائياً عند التشغيل والطباعة.",
                  style="Muted.TLabel", wraplength=700).pack(anchor="w")
        ttk.Label(f, text="الوضع الافتراضي هو طابعة ويندوز — لا يتغير شيء في التثبيتات الحالية. اختر ESC/POS فقط إذا كانت طابعتك حرارية متصلة مباشرة بهذا الكمبيوتر، وإذا فشلت الطباعة المباشرة يعود البرنامج تلقائياً لطابعة ويندوز ويخبرك.",
                  style="Muted.TLabel", wraplength=700).pack(anchor="w")
        ttk.Label(f, text="العربية في ESC/POS: تُشكَّل الحروف وتُرمَّز CP864 (حروف متصلة) فإن تعذّر تُستخدم Windows-1256 (حروف غير متصلة غالباً). رقما الصفحتين من صفحة الاختبار الذاتي للطابعة (اضغط FEED أثناء التشغيل) — أرقام Epson الافتراضية 37 و 50 وتختلف من ماركة لأخرى. إن ظهرت العربية مفككة أو كعلامات ؟ فالمشكلة في الطابعة نفسها لا في البرنامج.",
                  style="Muted.TLabel", wraplength=700).pack(anchor="w")
        ttk.Button(f, text="💾 حفظ إعدادات الطباعة", command=self.save_printer_settings).pack(anchor="w", pady=4)
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(f, text="الأمان:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Button(f, text="تغيير كلمة المرور الخاصة بي", command=self.change_password_dialog).pack(anchor="w", pady=4)
        if self.is_admin:
            ttk.Button(f, text="➕ إضافة مستخدم جديد (مدير / كاشير)", command=self.add_user_dialog).pack(anchor="w", pady=4)
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(f, text="البيانات:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Button(f, text="💾 نسخة احتياطية الآن (Backup)", command=self.do_backup).pack(anchor="w", pady=4)
        ttk.Button(f, text="♻️ استعادة نسخة احتياطية (Restore)", command=self.do_restore).pack(anchor="w", pady=4)
        self.lbl_backup = ttk.Label(f, text="لم يتم عمل نسخة احتياطية بعد في هذه الجلسة.")
        self.lbl_backup.pack(anchor="w", pady=2)
        ttk.Button(f, text="📥 استيراد أدوية من CSV", command=self.import_drugs).pack(anchor="w", pady=4)
        ttk.Button(f, text="📤 تصدير الأدوية CSV", command=self.export_drugs).pack(anchor="w", pady=4)
        ttk.Label(f, text="ملف قالب الاستيراد: drugs_template.csv — انسخ منه الصفوف وعدّلها.",
                  style="Muted.TLabel").pack(anchor="w", pady=2)
        # ---------- v6.11: ☁️ المزامنة السحابية (Supabase) ----------
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(f, text="☁️ المزامنة السحابية:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.btn_cloud_pull = ttk.Button(f, text="⬇️ سحب الكتالوج من السحابة (تحديث الأسعار)",
                                         command=self.cloud_pull)
        self.btn_cloud_pull.pack(anchor="w", pady=4)
        self.btn_cloud_push = ttk.Button(f, text="⬆️ رفع كل الأصناف المحلية للسحابة",
                                         command=self.cloud_push_all)
        self.btn_cloud_push.pack(anchor="w", pady=4)
        self.lbl_cloud = ttk.Label(f, text=self._cloud_status_text(), style="Muted.TLabel",
                                   wraplength=700, justify="left")
        self.lbl_cloud.pack(anchor="w", pady=2)
        ttk.Button(f, text="🔄 تحديث حالة المزامنة",
                   command=lambda: self.lbl_cloud.config(text=self._cloud_status_text())).pack(anchor="w", pady=2)
        # ---------- v6.12: 🔄 تحديثات البرنامج ----------
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(f, text="🔄 تحديثات البرنامج:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.btn_update_check = ttk.Button(f, text="🔍 التحقق من التحديثات الآن",
                                           command=self.update_check_now)
        self.btn_update_check.pack(anchor="w", pady=4)
        self.btn_update_apply = ttk.Button(f, text="⬇️ تحميل وتثبيت التحديث",
                                           command=self.update_apply_now)
        self.btn_update_apply.pack(anchor="w", pady=4)
        self.btn_update_apply.config(state="disabled")
        self._pending_update = None
        self.lbl_update = ttk.Label(f, text=self._update_status_text(), style="Muted.TLabel",
                                    wraplength=700, justify="left")
        self.lbl_update.pack(anchor="w", pady=2)
        ttk.Label(f, text="البرنامج يفحص GitHub عند كل تشغيل، وعند وجود كود جديد يمكنك تثبيته من هنا. "
                          "بياناتك (قاعدة البيانات والإعدادات والنسخ الاحتياطية) لا تتأثر بالتحديث أبداً، "
                          "وبعد التثبيت أعد تشغيل البرنامج.",
                  style="Muted.TLabel", wraplength=700, justify="left").pack(anchor="w", pady=2)
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)
        # ---------- v6.13: 🤖 المهام التلقائية ----------
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(f, text="🤖 المهام التلقائية:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        import automation
        self.var_autosync = tk.BooleanVar(value=self.db.get_setting("autosync_enabled", "1") != "0")
        ttk.Checkbutton(f, text="مزامنة الكتالوج من السحابة تلقائياً كل 24 ساعة (تحديث الأسعار بصمت)",
                        variable=self.var_autosync, command=self._save_automation_flags).pack(anchor="w", pady=2)
        self.var_autobackup = tk.BooleanVar(value=self.db.get_setting("autobackup_enabled", "1") != "0")
        ttk.Checkbutton(f, text="نسخة احتياطية تلقائية من قاعدة البيانات كل 24 ساعة (يُحتفظ بأحدث 10 نسخ)",
                        variable=self.var_autobackup, command=self._save_automation_flags).pack(anchor="w", pady=2)
        self.lbl_automation = ttk.Label(f, text=automation.status_text(self.db), style="Muted.TLabel",
                                        wraplength=700, justify="left")
        self.lbl_automation.pack(anchor="w", pady=2)
        ttk.Button(f, text="🔄 تحديث حالة المهام التلقائية",
                   command=self._refresh_automation_status).pack(anchor="w", pady=2)
        # ---------- v6.13: سجل التدقيق بفلاتر بحث ----------
        ttk.Label(f, text="🧾 سجل التدقيق — كل ما يحدث في النظام:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        _af = ttk.Frame(f)
        _af.pack(anchor="w", fill="x", pady=2)
        ttk.Label(_af, text="بحث:").pack(side="left")
        self.e_audit_filter = ttk.Entry(_af, width=22)
        self.e_audit_filter.pack(side="left", padx=4)
        ttk.Label(_af, text="نوع الإجراء:").pack(side="left")
        self.cb_audit_action = ttk.Combobox(_af, width=20, state="readonly")
        self.cb_audit_action.pack(side="left", padx=4)
        ttk.Label(_af, text="المستخدم:").pack(side="left")
        self.cb_audit_user = ttk.Combobox(_af, width=12, state="readonly")
        self.cb_audit_user.pack(side="left", padx=4)
        ttk.Button(_af, text="🔍 عرض", command=self.audit_refresh).pack(side="left", padx=6)
        self.lbl_audit_count = ttk.Label(f, text="", style="Muted.TLabel")
        self.lbl_audit_count.pack(anchor="w")
        self.txt_audit = tk.Text(f, width=100, height=12, font=("Segoe UI", 10))
        self.txt_audit.pack(fill="both", expand=True, pady=4)
        ttk.Button(f, text="تحديث سجل التدقيق", command=self.audit_refresh).pack(anchor="w", pady=4)
        self.audit_refresh()

    def save_pharmacy_name(self):
        self.db.conn.execute("UPDATE settings SET value=? WHERE key='pharmacy_name'",
                             (self.e_pharmacy.get().strip(),))
        # v6.3: pharmacy phone is saved with the name.
        self.db.set_setting("pharmacy_phone", self.e_pharmacy_phone.get().strip())
        self.db.conn.commit()
        messagebox.showinfo("تم", "تم حفظ اسم وتليفون الصيدلية")

    def save_printer_settings(self):
        """v5.10 (audit step 3): persist the printer choices. Defaults
        keep the old behaviour — nothing changes unless the user saves
        something different here."""
        if receipt_printer is None:
            messagebox.showerror("خطأ", "ملف printer.py غير موجود — أعد نسخ ملفات التحديث")
            return
        try:
            cp864 = int(self.e_cp864.get().strip() or "37")
            cp1256 = int(self.e_cp1256.get().strip() or "50")
            if not (0 <= cp864 <= 255 and 0 <= cp1256 <= 255):
                raise ValueError
        except ValueError:
            messagebox.showerror("خطأ", "رقم صفحة الترميز يجب أن يكون عدداً بين 0 و 255")
            return
        self.db.set_setting(receipt_printer.SETTING_PRINTER_TYPE,
                            self.var_printer_type.get())
        self.db.set_setting(receipt_printer.SETTING_PRINTER_NAME,
                            self.var_printer_name.get().strip())
        self.db.set_setting(receipt_printer.SETTING_PRINTER_WIDTH,
                            self.var_printer_width.get())
        self.db.set_setting(receipt_printer.SETTING_PRINTER_KICK,
                            "1" if self.var_printer_kick.get() else "0")
        self.db.set_setting(receipt_printer.SETTING_CP864_PAGE, str(cp864))
        self.db.set_setting(receipt_printer.SETTING_CP1256_PAGE, str(cp1256))
        messagebox.showinfo("تم", "تم حفظ إعدادات الطباعة")

    def change_password_dialog(self):
        """v5.0: changing a password now requires the CURRENT password,
        a new password of at least 8 characters, and a matching
        confirmation (was: any 4-char password, no checks at all)."""
        win = tk.Toplevel(self.root)
        win.title("تغيير كلمة المرور")
        win.geometry("420x320")
        win.resizable(False, False)
        ents = {}
        for key, lbl in [("current", "كلمة المرور الحالية"),
                         ("new", "كلمة المرور الجديدة (8 أحرف على الأقل)"),
                         ("confirm", "تأكيد كلمة المرور الجديدة")]:
            ttk.Label(win, text=lbl).pack(anchor="w", padx=16, pady=(10, 0))
            e = ttk.Entry(win, width=36, show="*")
            e.pack(padx=16)
            ents[key] = e
        ents["current"].focus_set()

        def save():
            from database import _verify_password
            row = self.db.conn.execute(
                "SELECT password_hash FROM users WHERE username=?",
                (self.username,)).fetchone()
            if not row or not _verify_password(ents["current"].get(), row["password_hash"]):
                messagebox.showerror("خطأ", "كلمة المرور الحالية غير صحيحة", parent=win)
                return
            new = ents["new"].get()
            if len(new) < 8:
                messagebox.showerror("خطأ", "كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل", parent=win)
                return
            if new != ents["confirm"].get():
                messagebox.showerror("خطأ", "تأكيد كلمة المرور لا يطابق كلمة المرور الجديدة", parent=win)
                return
            self.db.change_password(self.username, new)
            self.db.audit(self.username, "change_password", "")
            win.destroy()
            messagebox.showinfo("تم", "تم تغيير كلمة المرور")
        ttk.Button(win, text="💾 تغيير كلمة المرور", command=save,
                   style="Accent.TButton").pack(pady=16)

    def add_user_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("مستخدم جديد")
        win.geometry("360x260")
        ents = {}
        for key, lbl in [("username", "اسم المستخدم"), ("password", "كلمة المرور"), ("full", "الاسم الكامل")]:
            ttk.Label(win, text=lbl).pack(anchor="w", padx=12, pady=(8, 0))
            e = ttk.Entry(win, width=36, show="*" if key == "password" else "")
            e.pack(padx=12)
            ents[key] = e
        ttk.Label(win, text="الدور:").pack(anchor="w", padx=12, pady=(8, 0))
        var = tk.StringVar(value="cashier")
        ttk.Radiobutton(win, text="كاشير", variable=var, value="cashier").pack(anchor="w", padx=12)
        ttk.Radiobutton(win, text="مدير", variable=var, value="admin").pack(anchor="w", padx=12)
        def save():
            if not ents["username"].get().strip() or len(ents["password"].get()) < 8:
                messagebox.showerror("خطأ", "أدخل اسم مستخدم وكلمة مرور 8 أحرف على الأقل")
                return
            try:
                # v5.0: PBKDF2 hash via DB.create_user (was raw SHA-256 here)
                self.db.create_user(ents["username"].get().strip(),
                                    ents["password"].get(), var.get(),
                                    ents["full"].get().strip())
            except Exception as e:
                messagebox.showerror("خطأ", "اسم المستخدم موجود بالفعل: %s" % e)
                return
            self.db.audit(self.username, "add_user", ents["username"].get())
            win.destroy()
            messagebox.showinfo("تم", "تمت إضافة المستخدم")
        ttk.Button(win, text="حفظ", command=save).pack(pady=12)

    def do_backup(self):
        try:
            dest = self.db.backup()
        except Exception as e:
            messagebox.showerror("خطأ في النسخ الاحتياطي",
                                 "تعذر حفظ النسخة الاحتياطية: %s" % e)
            return
        try:
            self.lbl_backup.config(text="آخر نسخة احتياطية: %s" % dest)
        except Exception:
            pass
        self.db.audit(self.username, "backup", dest)
        messagebox.showinfo("تم", "تم حفظ نسخة احتياطية (تم التحقق من سلامتها) في:\n%s" % dest)
        self.show_banner("💾 تم حفظ نسخة احتياطية: %s" % dest, "success")

    def do_restore(self):
        """v5.0: restore a backup — the file is integrity-checked FIRST,
        the current DB is kept aside (never deleted), then the app
        reopens the restored DB. Requires admin; the mobile server
        is stopped first so no phone write lands mid-swap."""
        if not self.is_admin:
            messagebox.showerror("صلاحيات", "استعادة نسخة احتياطية صلاحية المدير فقط")
            return
        path = filedialog.askopenfilename(
            title="اختر ملف النسخة الاحتياطية",
            filetypes=[("SQLite DB", "*.db"), ("كل الملفات", "*.*")])
        if not path:
            return
        if not DB.verify_backup(path):
            messagebox.showerror("خطأ", "هذا الملف ليس نسخة احتياطية صالحة (فشل فحص السلامة) — لم يتغير شيء")
            return
        if not messagebox.askyesno(
                "استعادة نسخة احتياطية",
                "سيتم استبدال قاعدة البيانات الحالية بهذه النسخة.\n"
                "النسخة الحالية ستُحفظ جانباً باسم pharmacy.db.before-restore.\n"
                "هل أنت متأكد؟"):
            return
        try:
            if getattr(self, "mobile_server", None) is not None:
                try:
                    self.mobile_server.stop()
                except Exception:
                    pass
                self.mobile_server = None
            self.db.close()
            db_path = self.db.path
            keep = os.path.join(BASE, "pharmacy.db.before-restore")
            for suffix in ("", "-wal", "-shm"):
                p = db_path + suffix
                if os.path.exists(p):
                    try:
                        os.rename(p, keep + suffix)
                    except Exception:
                        pass
            shutil.copyfile(path, db_path)
            self.db = DB(path=db_path)
            self.db.audit(self.username, "restore", "restored from %s" % path)
            messagebox.showinfo("تم", "تمت الاستعادة من:\n%s\nأعد تشغيل البرنامج لتحديث كل الشاشات." % path)
            self.show_banner("✅ تمت استعادة النسخة الاحتياطية — أعد تشغيل البرنامج", "success")
        except Exception as e:
            messagebox.showerror("خطأ", "فشلت الاستعادة: %s\nراجع ملف error.log" % e)
            return

    def import_drugs(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            added, updated = self.db.import_drugs_csv(path, self.username)
        except Exception as e:
            messagebox.showerror("خطأ في الاستيراد", str(e))
            return
        messagebox.showinfo("تم", "تم الاستيراد: %d جديد، %d محدّث" % (added, updated))
        self.inv_refresh()
        self.pos_search_refresh()

    # ---------- v6.11: المزامنة السحابية (Supabase) ----------
    def _cloud_status_text(self):
        try:
            import cloud_sync
            st = cloud_sync.status(self.db)
        except Exception as e:
            return "المزامنة السحابية غير متاحة: %s" % e
        if not st.get("configured"):
            return ("المزامنة غير مفعّلة بعد. للتفعيل: انسخ الملف supabase_config.example.json "
                    "إلى supabase_config.json بجوار البرنامج واكتب فيه رابط المشروع والمفتاح، "
                    "ثم أعد تشغيل البرنامج. بعدها أي صنف جديد أو معدّل يُرفع للسحابة تلقائياً.")
        parts = ["المزامنة مفعّلة — أي صنف جديد أو معدّل يُرفع للسحابة تلقائياً."]
        if st.get("last_pull"):
            parts.append("آخر سحب: " + st["last_pull"])
        if st.get("last_push"):
            parts.append("آخر رفع: " + st["last_push"])
        if st.get("last_error"):
            parts.append("آخر خطأ: " + st["last_error"])
        return "\n".join(parts)

    def cloud_pull(self):
        """سحب كل المنتجات من السحابة ودمجها محلياً (في خيط خلفي)."""
        import cloud_sync
        import supabase_client
        if not supabase_client.is_configured():
            messagebox.showerror("المزامنة السحابية",
                                 "إعداد Supabase غير موجود.\nانسخ supabase_config.example.json إلى "
                                 "supabase_config.json بجوار البرنامج واكتب فيه الرابط والمفتاح.")
            return
        if not messagebox.askyesno("سحب الكتالوج من السحابة",
                                   "سيُسحب كل المنتجات (أدوية + كوزمتكس) من السحابة وتحدّث بياناتها "
                                   "وأسعارها محلياً بدون تكرار.\nالمخزون والمبيعات لا تتأثر. متابعة؟"):
            return
        self.btn_cloud_pull.config(state="disabled")
        self.show_banner("⏳ جاري سحب الكتالوج من السحابة...", "info")
        db_path = self.db.path
        username = self.username

        def work():
            db = DB(path=db_path, init=False)
            try:
                return cloud_sync.pull_catalog(db, username)
            finally:
                db.close()

        def done(result, error):
            def ui():
                self.btn_cloud_pull.config(state="normal")
                self.lbl_cloud.config(text=self._cloud_status_text())
                if error is not None:
                    messagebox.showerror("خطأ في المزامنة", str(error))
                    return
                added, updated, skipped = result
                self.show_banner("✅ اكتمل السحب من السحابة", "success")
                messagebox.showinfo("تم", "اكتمل السحب: %d جديد، %d محدّث، %d متجاهَل"
                                    % (added, updated, skipped))
                self.inv_refresh()
                self.pos_search_refresh()
            self._ui_post(ui)
        cloud_sync.run_in_background(work, done)

    def cloud_push_all(self):
        """رفع كل الأصناف المحلية للسحابة على دفعات (في خيط خلفي)."""
        import cloud_sync
        import supabase_client
        if not supabase_client.is_configured():
            messagebox.showerror("المزامنة السحابية",
                                 "إعداد Supabase غير موجود.\nانسخ supabase_config.example.json إلى "
                                 "supabase_config.json بجوار البرنامج واكتب فيه الرابط والمفتاح.")
            return
        if not messagebox.askyesno("رفع الأصناف للسحابة",
                                   "سيُرفع كل الأصناف المحلية إلى السحابة وتحدّث أسعارها هناك "
                                   "(الصنف الموجود يتحدث ولا يتكرر). متابعة؟"):
            return
        self.btn_cloud_push.config(state="disabled")
        self.show_banner("⏳ جاري رفع الأصناف للسحابة...", "info")
        db_path = self.db.path

        def work():
            db = DB(path=db_path, init=False)
            try:
                return cloud_sync.push_all(db)
            finally:
                db.close()

        def done(result, error):
            def ui():
                self.btn_cloud_push.config(state="normal")
                self.lbl_cloud.config(text=self._cloud_status_text())
                if error is not None:
                    messagebox.showerror("خطأ في المزامنة", str(error))
                    return
                sent, failed = result
                self.show_banner("✅ اكتمل الرفع للسحابة", "success")
                messagebox.showinfo("تم", "اكتمل الرفع: %d صنف، فشل %d" % (sent, failed))
            self._ui_post(ui)
        cloud_sync.run_in_background(work, done)

    # ---------- v6.13: المهام التلقائية ----------
    def _save_automation_flags(self):
        self.db.set_setting("autosync_enabled", "1" if self.var_autosync.get() else "0")
        self.db.set_setting("autobackup_enabled", "1" if self.var_autobackup.get() else "0")
        self._refresh_automation_status()

    def _refresh_automation_status(self):
        import automation
        self.lbl_automation.config(text=automation.status_text(self.db))

    # ---------- v6.12: تحديثات البرنامج من GitHub ----------
    def _update_status_text(self):
        try:
            import updater
            return updater.status_text(self.db)
        except Exception as e:
            return "فحص التحديثات غير متاح: %s" % e

    def _refresh_update_ui(self, result=None):
        """تحديث سطر الحالة وزر التثبيت بعد أي فحص (خيط الواجهة فقط)."""
        try:
            self.lbl_update.config(text=self._update_status_text())
        except Exception:
            pass
        available = bool(result and result.get("status") == "update_available")
        if result and result.get("status") == "update_available":
            self._pending_update = result["latest"]
        try:
            self.btn_update_apply.config(state="normal" if available else "disabled")
        except Exception:
            pass

    def _startup_update_check(self):
        """فحص صامت عند التشغيل: لو فيه تحديث يظهر بانر فقط."""
        import cloud_sync
        import updater
        db_path = self.db.path

        def work():
            db = DB(path=db_path, init=False)
            try:
                return updater.check_for_update(db)
            finally:
                db.close()

        def done(result, error):
            def ui():
                self._refresh_update_ui(result)
                if result and result.get("status") == "update_available":
                    msg = result["latest"].get("message") or ""
                    self.show_banner("🔄 يوجد تحديث جديد للبرنامج%s — راجع الإعدادات ← تحديثات البرنامج"
                                     % ((": " + msg[:60]) if msg else ""), "info")
            self._ui_post(ui)
        cloud_sync.run_in_background(work, done)

    def update_check_now(self):
        """زر «التحقق الآن»: فحص في الخلفية مع رسالة نتيجة واضحة."""
        import cloud_sync
        import updater
        self.btn_update_check.config(state="disabled")
        db_path = self.db.path

        def work():
            db = DB(path=db_path, init=False)
            try:
                return updater.check_for_update(db)
            finally:
                db.close()

        def done(result, error):
            def ui():
                self.btn_update_check.config(state="normal")
                self._refresh_update_ui(result)
                if error is not None:
                    messagebox.showerror("خطأ في فحص التحديثات", str(error))
                elif result.get("status") == "error":
                    messagebox.showerror("خطأ في فحص التحديثات", result["error"])
                elif result.get("status") == "update_available":
                    messagebox.showinfo("تحديث متاح",
                                        "يوجد تحديث جديد: %s\nاضغط «تحميل وتثبيت التحديث»."
                                        % (result["latest"].get("message") or ""))
                else:
                    messagebox.showinfo("لا يوجد تحديث", "البرنامج على آخر إصدار ✅")
            self._ui_post(ui)
        cloud_sync.run_in_background(work, done)

    def update_apply_now(self):
        """زر «تحميل وتثبيت التحديث»: تنزيل وتثبيت مع نسخة رجوع."""
        import cloud_sync
        import updater
        if not self._pending_update:
            messagebox.showinfo("لا يوجد تحديث", "افحص التحديثات أولاً — لا يوجد تحديث معلّق.")
            return
        latest = self._pending_update
        if not messagebox.askyesno("تثبيت التحديث",
                                   "سيُنزَّل آخر كود من GitHub ويُثبَّت فوق مجلد البرنامج.\n"
                                   "قاعدة البيانات والإعدادات والنسخ الاحتياطية لن تتأثر،\n"
                                   "وستُحفظ نسخة رجوع من الملفات المستبدلة. متابعة؟"):
            return
        self.btn_update_apply.config(state="disabled")
        self.show_banner("⏳ جاري تنزيل التحديث وتثبيته...", "info")
        db_path = self.db.path
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sha = latest["sha"]

        def work():
            db = DB(path=db_path, init=False)
            try:
                return updater.apply_update(db, base_dir, sha)
            finally:
                db.close()

        def done(result, error):
            def ui():
                self._pending_update = None
                self._refresh_update_ui({"status": "up_to_date"} if error is None else None)
                if error is not None:
                    self.show_banner("❌ فشل تثبيت التحديث", "error")
                    messagebox.showerror("فشل التحديث", str(error))
                    return
                updated, rollback_dir = result
                self.show_banner("✅ تم تثبيت التحديث — أعد تشغيل البرنامج", "success")
                messagebox.showinfo("تم التحديث",
                                    "تم تثبيت التحديث (%d ملف).\nأغلق البرنامج وشغّله من جديد "
                                    "ليعمل بالإصدار الجديد." % updated)
            self._ui_post(ui)
        cloud_sync.run_in_background(work, done)

    def audit_refresh(self):
        """v6.13: السجل بفلاتر (بحث حر / نوع الإجراء / المستخدم).
        الحجم مضبوط: لا يُحتفظ إلا بأحدث 5,000 حدث (تنظيف تلقائي عند
        كل تشغيل) فلا يكبر حتى بعد سنوات."""
        if not hasattr(self, "txt_audit"):
            return  # v6.14: الإعدادات لم تُبن بعد
        try:
            actions = self.db.audit_actions()
            cur_a = self.cb_audit_action.get()
            self.cb_audit_action.config(values=[""] + actions)
            if cur_a and cur_a not in actions:
                self.cb_audit_action.set("")
            users = sorted({a["user"] for a in self.db.audit_list(5000) if a["user"]})
            cur_u = self.cb_audit_user.get()
            self.cb_audit_user.config(values=[""] + users)
            if cur_u and cur_u not in users:
                self.cb_audit_user.set("")
        except Exception:
            pass
        text = self.e_audit_filter.get().strip()
        action = self.cb_audit_action.get().strip()
        user = self.cb_audit_user.get().strip()
        rows = self.db.audit_query(text=text, action=action, user=user, limit=200)
        self.txt_audit.delete("1.0", "end")
        for a in rows:
            self.txt_audit.insert("end", "%s | %s | %s | %s\n" % (
                a["created_at"], a["user"], a["action"], a["details"]))
        total = self.db.audit_count()
        shown = len(rows)
        filters_on = bool(text or action or user)
        self.lbl_audit_count.config(
            text="يظهر %d%s من إجمالي %d حدث — يُحتفظ تلقائياً بأحدث 5,000 حدث فقط حتى لا يكبر الملف."
                 % (shown, " (مفلترة)" if filters_on else " (الأحدث)", total))


def _try_restore_latest_backup():
    """v5.0 startup recovery: if pharmacy.db is corrupt/locked and the
    app cannot open it, restore the newest VERIFIED backup instead of
    dying. The corrupt file is moved aside (never deleted) as
    pharmacy.db.corrupt-<stamp>. Returns True if a restore happened."""
    import shutil
    base = BASE
    db_path = os.path.join(base, "pharmacy.db")
    folder = os.path.join(base, "backups")
    try:
        cands = [os.path.join(folder, f) for f in os.listdir(folder)
                 if f.startswith("pharmacy_") and f.endswith(".db")]
    except Exception:
        return False
    cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for cand in cands:
        try:
            if not DB.verify_backup(cand):
                continue
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            for suffix in ("", "-wal", "-shm"):
                p = db_path + suffix
                if os.path.exists(p):
                    os.rename(p, "%s.corrupt-%s%s" % (db_path, stamp, suffix))
            shutil.copyfile(cand, db_path)
            return True
        except Exception:
            continue
    return False


def main():
    try:
        db = DB()
    except Exception:
        # v5.0: corrupt DB is no longer total loss — restore the newest
        # verified backup automatically and try again.
        restored = _try_restore_latest_backup()
        db = None
        if restored:
            try:
                db = DB()
            except Exception:
                db = None
        if db is None:
            # Entry-point safety: never close instantly with no message.
            try:
                import traceback
                with open(os.path.join(BASE, "error.log"), "w", encoding="utf-8") as f:
                    traceback.print_exc(file=f)
            except Exception:
                pass
            _startup_log("database open FAILED (restored=%s)" % restored)
            print("ERROR starting database: could not open pharmacy.db"
                  + (" (a backup was restored but still failed)" if restored
                     else " and no verified backup was available"))
            try:
                input("حدث خطأ أثناء تشغيل قاعدة البيانات. اضغط Enter للخروج...")
            except Exception:
                pass
            return
        else:
            print("NOTICE: pharmacy.db was corrupt — restored the newest verified backup.")
    _startup_log("app start: database ok")
    try:
        login = LoginWindow(db)
        user = login.run()
        if not user:
            _startup_log("login closed without a user — clean exit")
            db.close()
            return
        _startup_log("login accepted: user=%s" % user["username"])
        # v5.1: the forced default-password change now happens INSIDE
        # LoginWindow.try_login(), parented to the visible login window.
        # The old code here created a second, withdrawn Tk() and a
        # Toplevel on it that never mapped — that was the bug that left
        # the app hidden with nothing on screen. Do not re-add it.
        # v5.0: automatic daily backup on startup (silent, best effort).
        # v6.14: moved OFF the opening path — copying a large DB file
        # used to sit between login and the first paint. It now runs in
        # a daemon thread with its own DB connection (SQLite connections
        # are never shared across threads here).
        def _startup_backup_async():
            try:
                folder = os.path.join(BASE, "backups")
                newest = 0.0
                if os.path.isdir(folder):
                    for f in os.listdir(folder):
                        if f.startswith("pharmacy_") and f.endswith(".db"):
                            newest = max(newest, os.path.getmtime(os.path.join(folder, f)))
                import time as _time
                if newest == 0.0 or _time.time() - newest > 24 * 3600:
                    bdb = DB(path=db.path, init=False)
                    try:
                        bdb.backup()
                    finally:
                        bdb.close()
            except Exception:
                pass
        threading.Thread(target=_startup_backup_async, daemon=True).start()
        # v5.10 (audit step 3): prune old receipt/label files (>30 days)
        # from receipts/ on startup (also pruned on every print).
        try:
            if receipt_printer is not None:
                receipt_printer.prune_receipts(BASE)
        except Exception:
            pass
        root = tk.Tk()
        App(root, db, user)
        # v5.1 failsafe: the main window MUST be visible. Force it to
        # the front now, and check again after 1s — if it is somehow
        # not mapped, show it again instead of leaving a hidden app.
        def _ensure_main_visible():
            try:
                if not root.winfo_viewable():
                    _startup_log("FAILSAFE: main window not viewable — forcing deiconify")
                    root.deiconify()
                    root.lift()
                    root.focus_force()
                else:
                    _startup_log("main window visible: %s" % root.winfo_geometry())
            except Exception as e:
                _startup_log("FAILSAFE check error: %r" % (e,))
        try:
            root.update_idletasks()
            root.deiconify()
            root.lift()
            root.focus_force()
            _startup_log("main window created, viewable=%s" % root.winfo_viewable())
        except Exception as e:
            _startup_log("main window show error: %r" % (e,))
        root.after(1000, _ensure_main_visible)
        root.mainloop()
    except Exception:
        import traceback
        traceback.print_exc()
        _startup_log("FATAL exception — see error.log")
        try:
            with open(os.path.join(BASE, "error.log"), "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except Exception:
            pass
        try:
            input("حدث خطأ. راجع ملف error.log ثم اضغط Enter للخروج...")
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
