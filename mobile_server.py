# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise v4 — Mobile Companion server (stdlib only).

v4.1: get_all_lan_ips() lists EVERY local IPv4 (hotspot 192.168.137.x
AND home Wi-Fi 192.168.1.x) instead of picking one via 8.8.8.8;
server sets allow_reuse_address and Connection: close per request.

PC is the server. The phone is only a browser: it opens
http://<PC-LAN-IP>:8080 on the SAME Wi-Fi, enters the 6-digit PIN
shown in the PC app, creates an invoice, and the PC saves it in the
SAME pharmacy.db — then the PC prints it.

Architecture (LAN-only, no internet, no cloud, no new packages):
  * ThreadingHTTPServer on 0.0.0.0:8080 (LAN only; never expose it to
    the internet and never forward the port on the router).
  * Every /api/* call needs the PIN in the X-Mobile-PIN header
    ONLY (v6.2: the old ?pin=XXXXXX query-string fallback was
    removed — URLs get logged / shared / kept in browser history,
    so a PIN must never be in one). Wrong PIN -> 401. The landing
    page (GET /) only
    asks for the PIN; it never returns data without one.
  * The server opens a FRESH DB connection per request (sqlite3
    connections are not shared across threads). Writes are serialised
    with a lock. Sales are created through DB.create_sale_from_items()
    — the SAME FEFO / stock / profit logic the PC POS uses. There is
    no second copy of the sale formula anywhere.
  * Runs in a background daemon thread from the desktop app, or
    standalone:  py mobile_server.py   (prints the URL + PIN, waits).

Security, stated honestly: this is a simple LAN PIN, not bank-grade
auth. It is fine for a trusted home/shop Wi-Fi. Do NOT use it on a
public Wi-Fi, and do NOT forward port 8080 on the router.

v4.11: HTTPS on port 8443 with a LOCAL self-signed certificate
(certs/cert.pem + certs/key.pem, stdlib ssl only; an older
cert.pem/key.pem pair in the app root is still accepted as a
fallback for existing installs, and a missing cert is generated
at server start — v6.2: PowerShell New-SelfSignedCertificate
first, openssl fallback). Plain http://192.168.137.1:8080
is an INSECURE context in Chrome, so the browser itself removes
getUserMedia / BarcodeDetector and no permission prompt ever appears
— the Chrome flag workaround did not fix it on Mohamed's phone.
Serving the same page over https://<PC-IP>:8443 makes the browser
treat it as a secure context, so the camera APIs come back and live
scan can ask for permission. The cert is self-signed, so the phone
shows a "Your connection is not private" warning the first time:
tap Advanced > Proceed to the site. The cert covers only local
addresses (SANs: 192.168.137.1, 192.168.1.2, 127.0.0.1, localhost)
and must never be used on the public internet. HTTP 8080 keeps
working exactly as before for invoices without scanning; if the
cert files are missing, the server serves HTTP only and never
crashes.
"""
import collections
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

from database import DB, unit_price, units_per_box, allowed_units

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 8080
HTTPS_PORT = 8443
# v6.2 (audit step 4A): certs live in certs/ now. CERT_FILE/KEY_FILE
# below are the ROOT fallback only — an existing install that
# already has cert.pem/key.pem next to mobile_server.py keeps
# working exactly as before (resolve_cert_files() prefers certs/,
# falls back to the root pair). New certs are GENERATED at runtime
# into certs/ on first server start, so a future full zip must NOT
# ship key.pem (see regenerate_cert()).
CERT_DIR = os.path.join(BASE, "certs")
CERT_FILE = os.path.join(BASE, "cert.pem")
KEY_FILE = os.path.join(BASE, "key.pem")
WRITE_LOCK = threading.Lock()


def resolve_cert_files():
    """(cert_path, key_path) actually in use: prefer the certs/
    pair, fall back to the root pair (existing installs), and if
    neither exists return the certs/ pair as the generation target."""
    certs_pair = (os.path.join(CERT_DIR, "cert.pem"),
                  os.path.join(CERT_DIR, "key.pem"))
    root_pair = (CERT_FILE, KEY_FILE)
    try:
        if os.path.isfile(certs_pair[0]) and os.path.isfile(certs_pair[1]):
            return certs_pair
        if os.path.isfile(root_pair[0]) and os.path.isfile(root_pair[1]):
            return root_pair
    except Exception:
        pass
    return certs_pair


def cert_files_exist():
    """True when the local self-signed cert + key are present
    (certs/ first, root pair as fallback for existing installs)."""
    try:
        cert_file, key_file = resolve_cert_files()
        return os.path.isfile(cert_file) and os.path.isfile(key_file)
    except Exception:
        return False


def _label_for(ip, adapter=""):
    """Arabic label for one local IP. The PC hotspot gateway is
    192.168.137.1 on Windows, so a phone on the hotspot must use
    THAT address, not the home-Wi-Fi address (e.g. 192.168.1.5)."""
    low = (adapter or "").lower()
    if ip.startswith("192.168.137."):
        return "هوت سبوت الكمبيوتر"
    if "wi-fi direct" in low or "virtual adapter" in low:
        return "هوت سبوت الكمبيوتر"
    if "wi-fi" in low or "wifi" in low or "wireless" in low or "wlan" in low:
        return "واي فاي"
    if "ethernet" in low or "eth" in low:
        return "إيثرنت (كابل)"
    return "شبكة محلية"


def _valid_ip(ip):
    if not ip or ip.startswith("127.") or ip.startswith("169.254."):
        return False
    parts = ip.split(".")
    return len(parts) == 4 and all(x.isdigit() and 0 <= int(x) <= 255 for x in parts)


def _parse_ipconfig_windows():
    """Parse `ipconfig` output: (adapter name, IPv4) pairs. Windows only;
    returns [] anywhere else. Never raises."""
    out = []
    try:
        proc = subprocess.run(["ipconfig"], capture_output=True, timeout=10,
                              text=True, encoding="utf-8", errors="replace")
        adapter = ""
        for line in (proc.stdout or "").splitlines():
            m = re.match(r"\s*(.+?) adapter (.+):\s*$", line, re.IGNORECASE)
            if m:
                adapter = m.group(2).strip()
                continue
            m2 = re.search(r"IPv4 Address[^:]*:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", line)
            if m2:
                out.append((adapter, m2.group(1)))
    except Exception:
        pass
    return out


def get_all_lan_ips():
    """ALL local IPv4 addresses as a list of dicts
    {ip, label, adapter}. Never raises; may be [] on a machine with
    no network. Deduplicated, loopback and APIPA excluded.

    Why a list, not one IP: the old get_lan_ip() picked ONE address
    via a UDP connect to 8.8.8.8. That is wrong when there is no
    internet (route fails), the PC has Ethernet + Wi-Fi, or the PC
    hotspot is on (hotspot = 192.168.137.1, home Wi-Fi = 192.168.1.5
    — a phone on the hotspot can NEVER reach 192.168.1.5, hence
    ERR_CONNECTION_TIMED_OUT). The UI must show every candidate.
    """
    found = {}  # ip -> {ip, label, adapter}
    # (a) hostname / getaddrinfo — works on Windows and Linux.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _valid_ip(ip) and ip not in found:
                found[ip] = {"ip": ip, "label": _label_for(ip), "adapter": ""}
    except Exception:
        pass
    # (b) UDP trick — the old method, kept as ONE candidate, not the only one.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if _valid_ip(ip) and ip not in found:
            found[ip] = {"ip": ip, "label": _label_for(ip), "adapter": ""}
    except Exception:
        pass
    # (c) Windows ipconfig — gives adapter names (Wi-Fi / hotspot /
    # Ethernet), which (a)/(b) cannot tell apart.
    for adapter, ip in _parse_ipconfig_windows():
        if not _valid_ip(ip):
            continue
        if ip in found:
            found[ip]["adapter"] = adapter
            found[ip]["label"] = _label_for(ip, adapter)
        else:
            found[ip] = {"ip": ip, "label": _label_for(ip, adapter), "adapter": adapter}
    # Hotspot first (a phone on the hotspot must use it), then Wi-Fi,
    # then the rest — so the first URL is usually the right one.
    order = {"هوت سبوت الكمبيوتر": 0, "واي فاي": 1, "إيثرنت (كابل)": 2}
    items = sorted(found.values(), key=lambda d: (order.get(d["label"], 3), d["ip"]))
    return items


def get_lan_ip():
    """Backward-compatible single IP: first non-hotspot address if
    there is one, else the first address, else 127.0.0.1. Prefer
    get_all_lan_ips() in new code — one IP is not enough."""
    items = get_all_lan_ips()
    if not items:
        return "127.0.0.1"
    for it in items:
        if it["label"] != "هوت سبوت الكمبيوتر":
            return it["ip"]
    return items[0]["ip"]


def mobile_url(port=DEFAULT_PORT, scheme="http"):
    return "%s://%s:%d" % (scheme, get_lan_ip(), port)


def mobile_urls(port=DEFAULT_PORT, scheme="http"):
    """All candidate URLs, one per local IP. scheme is "http" (8080)
    or "https" (8443, v4.11 — the secure-context URL the phone
    needs for camera scanning)."""
    return [{"ip": it["ip"], "label": it["label"], "adapter": it["adapter"],
             "url": "%s://%s:%d" % (scheme, it["ip"], port)}
            for it in get_all_lan_ips()]


def mobile_https_url(port=HTTPS_PORT):
    return "https://%s:%d" % (get_lan_ip(), port)


def mobile_https_urls(port=HTTPS_PORT):
    """All candidate HTTPS URLs, one per local IP (v4.11)."""
    return mobile_urls(port, "https")


# ---------- v5.6: request log (who is asking for what?) ----------
# Mohamed reported "a lot of requests I did not do". The server used
# to log NOTHING (log_message was silenced), so nobody could tell
# whether the requests came from his phone, his PC browser, or
# another device on the hotspot. Every request is now recorded
# (in-memory ring, last 300, + a capped file mobile_requests.log).
# The query string is NEVER logged. (v6.2: the PIN is header-only
# now, so a PIN can never appear in a logged URL at all.)
class RequestLog:
    def __init__(self, maxlen=300, path=None):
        self._lock = threading.Lock()
        self._rows = collections.deque(maxlen=maxlen)
        self._total = 0
        self._path = path
        self._file_bytes = 0

    def record(self, ip, method, path, status, ua=""):
        row = {"t": time.strftime("%H:%M:%S"), "ip": ip or "?",
               "method": method, "path": path, "status": status,
               "ua": (ua or "")[:60]}
        with self._lock:
            self._rows.append(row)
            self._total += 1
        if self._path:
            try:
                line = ("%(t)s %(ip)s %(method)s %(path)s %(status)s %(ua)s\n" % row)
                if self._file_bytes > 512 * 1024:
                    with open(self._path, "w", encoding="utf-8") as f:
                        f.write("")
                    self._file_bytes = 0
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line)
                self._file_bytes += len(line.encode("utf-8"))
            except Exception:
                pass

    def recent(self, n=50):
        with self._lock:
            return list(self._rows)[-n:]

    def summary(self):
        with self._lock:
            rows = list(self._rows)
            total = self._total
        by_ip = collections.Counter(r["ip"] for r in rows)
        by_path = collections.Counter(r["path"] for r in rows)
        by_status = collections.Counter(str(r["status"]) for r in rows)
        return {"total": total, "shown": len(rows),
                "by_ip": by_ip.most_common(10),
                "by_path": by_path.most_common(10),
                "by_status": by_status.most_common(10),
                "recent": rows[-50:]}


def cert_san_ips(cert_path):
    """IP + DNS names in a cert's SubjectAltName, stdlib only.
    Uses ssl._ssl._test_decode_cert when available, else a small
    DER scan for the SAN extension (OID 2.5.29.17, IP tag 0x87).
    Never raises; returns set() when it cannot be read."""
    try:
        dec = ssl._ssl._test_decode_cert(cert_path)  # CPython private API
        out = set()
        for kind, value in (dec.get("subjectAltName") or ()):
            if kind in ("IP Address", "DNS"):
                out.add(str(value))
        return out
    except Exception:
        pass
    try:
        import base64 as _b64
        text = open(cert_path, "r", encoding="utf-8", errors="ignore").read()
        body = "".join(l.strip() for l in text.splitlines()
                       if l.strip() and "---" not in l)
        der = _b64.b64decode(body)
        out = set()
        oid = bytes([0x06, 0x03, 0x55, 0x1D, 0x11])
        i = der.find(oid)
        if i < 0:
            return out
        # IP GeneralNames are tagged 0x87 followed by a 4- or 16-byte value.
        j = i
        while True:
            j = der.find(b"\x87", j + 1)
            if j < 0 or j > i + 400:
                break
            ln = der[j + 1]
            raw = der[j + 2:j + 2 + ln]
            if len(raw) == 4:
                out.add(".".join(str(b) for b in raw))
            elif len(raw) == 16:
                out.add(socket.inet_ntop(socket.AF_INET6, raw))
        return out
    except Exception:
        return set()


# v6.2 (audit step 4A): PowerShell cert generation.
# New-SelfSignedCertificate is built into Windows — it is the FIRST
# choice for generating the self-signed cert. The private key is
# exported to PEM with .NET's ExportPkcs8PrivateKey(), which exists
# in PowerShell 7 (pwsh, .NET Core) but NOT in Windows PowerShell
# 5.1 (.NET Framework has no such method, and pure-Python cert
# generation is not in the stdlib — no crypto library is invented
# here). So: pwsh is tried first, then powershell 5.1 (which will
# fail at the key export and fall through), then openssl. Whatever
# method produces the files, the caller sanity-checks the SANs
# (cert_san_ips) before accepting the cert.
_PS_GEN_SCRIPT = r'''
param([string]$Ips, [string]$CertOut, [string]$KeyOut)
$ErrorActionPreference = 'Stop'
$cert = $null
try {
    $ipList = $Ips -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $dnsNames = @($ipList) + @('localhost')
    $cert = New-SelfSignedCertificate -DnsName $dnsNames `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256 `
        -KeyExportPolicy Exportable -NotAfter (Get-Date).AddYears(10) `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.1')
    $b64 = [Convert]::ToBase64String($cert.GetRawCertData(), 'InsertLineBreaks')
    [System.IO.File]::WriteAllText($CertOut,
        "-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----`n")
    $rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)
    $kb64 = [Convert]::ToBase64String($rsa.ExportPkcs8PrivateKey(), 'InsertLineBreaks')
    [System.IO.File]::WriteAllText($KeyOut,
        "-----BEGIN PRIVATE KEY-----`n$kb64`n-----END PRIVATE KEY-----`n")
    Write-Output "OK"
} catch {
    Write-Error $_.Exception.Message
    exit 1
} finally {
    if ($cert) {
        Remove-Item ("Cert:\CurrentUser\My\" + $cert.Thumbprint) `
            -ErrorAction SilentlyContinue
    }
}
'''


def _generate_cert_powershell(ips, cert_path, key_path):
    """Generate cert+key with Windows New-SelfSignedCertificate.
    Returns (ok, message). Never raises. Returns False (not an
    error) when no usable PowerShell is present — e.g. on Linux —
    so the caller can fall back to openssl."""
    for exe in ("pwsh", "powershell"):
        ps = shutil.which(exe)
        if not ps:
            continue
        script_path = cert_path + ".gen.ps1"
        try:
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(_PS_GEN_SCRIPT)
            r = subprocess.run(
                [ps, "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", script_path,
                 "-Ips", ",".join(ips),
                 "-CertOut", cert_path, "-KeyOut", key_path],
                capture_output=True, timeout=120, text=True)
            if (r.returncode == 0 and os.path.isfile(cert_path)
                    and os.path.isfile(key_path)):
                return True, "PowerShell (%s)" % exe
        except Exception:
            pass
        finally:
            for tmp in (script_path,):
                try:
                    if os.path.isfile(tmp):
                        os.remove(tmp)
                except Exception:
                    pass
            # a failed attempt must not leave half a pair behind
            for tmp in (cert_path, key_path):
                try:
                    if os.path.isfile(tmp) and not (
                            os.path.isfile(cert_path)
                            and os.path.isfile(key_path)):
                        os.remove(tmp)
                except Exception:
                    pass
    return False, "PowerShell غير متاح أو لا يستطيع تصدير المفتاح (يحتاج PowerShell 7)"


def regenerate_cert(ips, base_dir):
    """Generate a NEW self-signed cert covering the given IPs.
    v6.2: FIRST choice is Windows New-SelfSignedCertificate via
    PowerShell (built into Windows, no openssl needed); FALLBACK
    is the openssl CLI (present on this Linux VM and on many
    Windows PCs via Git). New files go into certs/ (created if
    needed) — the root cert.pem/key.pem pair of an existing install
    is left untouched and keeps working as a fallback. Old files
    in the target dir are backed up to *.bak, then the new pair
    replaces them atomically.
    Returns (ok, message). Never raises. If no generator works,
    returns False and the OLD cert stays in place — the server
    must never break because regeneration was impossible."""
    ips = sorted({ip for ip in ips if ip and ip != "127.0.0.1"})
    ips = ["127.0.0.1"] + ips
    target_dir = os.path.join(base_dir, "certs")
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as e:
        return False, "تعذر إنشاء مجلد certs: %s" % e
    cert_tmp = os.path.join(target_dir, "cert.pem.tmp")
    key_tmp = os.path.join(target_dir, "key.pem.tmp")
    method = ""
    try:
        # --- first choice: PowerShell (writes straight to the tmp pair)
        ok, msg = _generate_cert_powershell(ips, cert_tmp, key_tmp)
        if ok:
            method = "PowerShell"
        else:
            # --- fallback: openssl
            openssl = shutil.which("openssl")
            if not openssl:
                return False, ("لا يمكن توليد شهادة جديدة تلقائياً — "
                               "%s، وopenssl غير موجود" % msg)
            cn = ips[1] if len(ips) > 1 else "127.0.0.1"
            san = ",".join(["IP:%s" % ip for ip in ips] + ["DNS:localhost"])
            r = subprocess.run(
                [openssl, "req", "-x509", "-newkey", "rsa:2048",
                 "-keyout", key_tmp, "-out", cert_tmp, "-days", "3650",
                 "-nodes", "-subj", "/CN=%s" % cn,
                 "-addext", "subjectAltName=%s" % san],
                capture_output=True, timeout=60, text=True)
            if r.returncode != 0 or not (os.path.isfile(cert_tmp) and os.path.isfile(key_tmp)):
                return False, "فشل توليد الشهادة: %s" % (r.stderr or "")[:200]
            method = "openssl"
        # sanity: the new cert really covers the IPs we asked for
        if not set(ips).issubset(cert_san_ips(cert_tmp)):
            return False, "الشهادة الجديدة لا تغطي العناوين المطلوبة"
        for name in ("cert.pem", "key.pem"):
            old = os.path.join(target_dir, name)
            if os.path.isfile(old):
                try:
                    shutil.copyfile(old, old + ".bak")
                except Exception:
                    pass
        os.replace(cert_tmp, os.path.join(target_dir, "cert.pem"))
        os.replace(key_tmp, os.path.join(target_dir, "key.pem"))
        return True, "تم توليد شهادة جديدة (%s) تغطي: %s" % (method, ", ".join(ips))
    except Exception as e:
        for tmp in (cert_tmp, key_tmp):
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except Exception:
                pass
        return False, "فشل توليد الشهادة: %s" % e


class _ReuseServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64  # Burst of phone polls/saves must not overflow the default backlog.


# ---------------------------------------------------------------------------
# v6.23: desktop <-> phone scan-request mailbox (in-memory, per process).
#
# The desktop add-drug dialog can ask the phone page to scan a barcode with
# its camera and send the result back. The phone polls GET /api/scan-request;
# the desktop dialog polls scan_request_poll() directly (same process), so no
# DB writes and no extra HTTP are involved on the PC side. One request at a
# time; it expires after SCAN_REQUEST_TTL seconds.
# ---------------------------------------------------------------------------
SCAN_REQUEST_TTL = 180.0
_SCAN_LOCK = threading.Lock()
_SCAN_STATE = {"id": 0, "at": 0.0, "code": None}


def scan_request_open():
    """Desktop: open one pending barcode request; returns its id."""
    with _SCAN_LOCK:
        _SCAN_STATE["id"] += 1
        _SCAN_STATE["at"] = time.time()
        _SCAN_STATE["code"] = None
        return _SCAN_STATE["id"]


def scan_request_poll(rid):
    """Desktop: poll a request id -> {"pending", "code", "expired"}."""
    with _SCAN_LOCK:
        if not rid or rid != _SCAN_STATE["id"] or _SCAN_STATE["at"] == 0.0:
            return {"pending": False, "code": None, "expired": True}
        if _SCAN_STATE["code"]:
            return {"pending": False, "code": _SCAN_STATE["code"], "expired": False}
        if time.time() - _SCAN_STATE["at"] > SCAN_REQUEST_TTL:
            return {"pending": False, "code": None, "expired": True}
        return {"pending": True, "code": None, "expired": False}


def scan_request_cancel(rid):
    """Desktop: give up on a request (dialog closed)."""
    with _SCAN_LOCK:
        if rid and rid == _SCAN_STATE["id"]:
            _SCAN_STATE["at"] = 0.0
            _SCAN_STATE["code"] = None


def _scan_phone_view():
    """Phone GET: is a scan request pending right now, and which id?"""
    with _SCAN_LOCK:
        pending = (_SCAN_STATE["at"] > 0.0 and not _SCAN_STATE["code"]
                   and time.time() - _SCAN_STATE["at"] <= SCAN_REQUEST_TTL)
        return {"pending": pending, "id": _SCAN_STATE["id"] if pending else 0}


def _scan_phone_submit(rid, code):
    """Phone POST: deliver one scanned barcode. True when accepted."""
    code = (code or "").strip()
    if not code or len(code) > 64:
        return False
    with _SCAN_LOCK:
        if rid != _SCAN_STATE["id"] or _SCAN_STATE["at"] == 0.0:
            return False
        if time.time() - _SCAN_STATE["at"] > SCAN_REQUEST_TTL:
            return False
        _SCAN_STATE["code"] = code
        return True


class MobileServer:
    """Start/stop wrapper so the desktop app can run the server in a
    background daemon thread. Safe to call start() twice.

    v4.11: start() brings up BOTH listeners on the same handler:
    HTTP on `port` (8080, as before) AND HTTPS on `https_port`
    (8443) when the cert files exist (certs/ first, root pair as
    fallback). HTTPS failing (missing or
    bad cert, port busy) never stops HTTP: self.https_error holds
    the reason and self.https_running is False. `running` still
    means the HTTP server is up, as the desktop app expects."""

    def __init__(self, db_path=None, port=DEFAULT_PORT, https_port=HTTPS_PORT):
        self.db_path = db_path or os.path.join(BASE, "pharmacy.db")
        self.port = int(port)
        self.https_port = int(https_port)
        self.httpd = None
        self.thread = None
        self.https_httpd = None
        self.https_thread = None
        self.https_error = ""
        self.start_error = ""
        # v5.6: request log + cert coverage state (read by the PC app)
        self.req_log = RequestLog(path=os.path.join(BASE, "mobile_requests.log"))
        self.cert_sans = set()
        self.cert_covers_current_ip = None
        self.cert_regenerated = False
        self.cert_message = ""

    @property
    def running(self):
        return self.httpd is not None

    @property
    def https_running(self):
        return self.https_httpd is not None

    @property
    def url(self):
        return mobile_url(self.port)

    @property
    def url_list(self):
        return mobile_urls(self.port)

    # v6.23: the desktop scan dialog talks to the mailbox through the
    # server object it already holds.
    def scan_request_open(self):
        return scan_request_open()

    def scan_request_poll(self, rid):
        return scan_request_poll(rid)

    def scan_request_cancel(self, rid):
        scan_request_cancel(rid)

    @property
    def https_url(self):
        return mobile_https_url(self.https_port)

    @property
    def https_url_list(self):
        return mobile_https_urls(self.https_port)

    def start(self):
        if self.httpd is not None:
            return True
        self.start_error = ""
        # v6.2 audit fix (1C): one-time schema init / migrations /
        # seed NOW, at startup — not on the first (or every) HTTP
        # request. A failure here fails startup loudly instead of
        # serving half-initialised requests.
        try:
            DB.ensure_initialized(self.db_path)
        except Exception as e:
            self.start_error = ("تعذر فتح قاعدة البيانات: %s" % e)
            return False
        try:
            handler = _make_handler(self.db_path, self.req_log)
            self.httpd = _ReuseServer(("0.0.0.0", self.port), handler)
            self.thread = threading.Thread(target=self.httpd.serve_forever,
                                           daemon=True)
            self.thread.start()
        except Exception as e:
            self.httpd = None
            self.thread = None
            # v5.0: keep the real reason (busy port vs other) so the UI
            # can tell the user what to do instead of a silent failure.
            err = str(e)
            if "10048" in err or "Address already in use" in err:
                self.start_error = ("المنفذ %d مشغول — سيرفر آخر يعمل عليه بالفعل. "
                                    "أوقف نسخة البرنامج الأخرى أو أعد تشغيل الكمبيوتر، ثم حاول مجدداً."
                                    % self.port)
            else:
                self.start_error = "تعذر تشغيل السيرفر على المنفذ %d: %s" % (self.port, err)
            return False
        # v5.6: CERT COVERAGE CHECK — the v4.11 cert only covers
        # 192.168.137.1 / 192.168.1.2 / 127.0.0.1. If the PC's IP
        # changed (home Wi-Fi gives a new address every time), the
        # cert does NOT cover the URL the phone actually opens, so
        # Chrome distrusts it and the camera may still fail even
        # after Advanced > Proceed. Regenerate a cert covering the
        # CURRENT LAN IPs before starting HTTPS (v6.2: PowerShell
        # first, openssl fallback; new cert goes into certs/).
        # If generation is impossible the old cert stays and a
        # clear warning is shown instead of silently serving a
        # stale cert.
        _cert_file, _key_file = resolve_cert_files()
        self.cert_sans = cert_san_ips(_cert_file) if cert_files_exist() else set()
        try:
            current_ips = [it["ip"] for it in get_all_lan_ips()]
        except Exception:
            current_ips = []
        lan_ips = [ip for ip in current_ips if ip and not ip.startswith("127.")]
        self.cert_covers_current_ip = (
            bool(lan_ips) and any(ip in self.cert_sans for ip in lan_ips))
        if not cert_files_exist() or not self.cert_covers_current_ip:
            # Always include the Windows hotspot gateway 192.168.137.1
            # even when the hotspot is OFF right now — otherwise a
            # cert generated on home Wi-Fi would not cover the hotspot
            # URL the phone opens a minute later.
            regen_ips = list(dict.fromkeys(current_ips + ["192.168.137.1"]))
            ok, msg = regenerate_cert(regen_ips, BASE)
            self.cert_message = msg
            if ok:
                self.cert_regenerated = True
                _cert_file, _key_file = resolve_cert_files()
                self.cert_sans = cert_san_ips(_cert_file)
                self.cert_covers_current_ip = True
        # HTTPS (v4.11): best-effort — a failure here must never
        # take down the HTTP server that already started.
        self.https_error = ""
        try:
            if not cert_files_exist():
                self.https_error = ("ملف الشهادة غير موجود (certs/cert.pem و certs/key.pem) — "
                                    "السيرفر يعمل على HTTP فقط، والمسح بالكاميرا لن يعمل.")
            else:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(_cert_file, _key_file)
                handler = _make_handler(self.db_path, self.req_log)
                self.https_httpd = _ReuseServer(("0.0.0.0", self.https_port), handler)
                self.https_httpd.socket = ctx.wrap_socket(
                    self.https_httpd.socket, server_side=True)
                self.https_thread = threading.Thread(
                    target=self.https_httpd.serve_forever, daemon=True)
                self.https_thread.start()
        except Exception as e:
            self.https_error = "تعذر تشغيل HTTPS على المنفذ %d: %s" % (self.https_port, e)
            self.https_httpd = None
            self.https_thread = None
        return True

    def request_summary(self):
        """v5.6: request log summary for the PC Mobile tab."""
        try:
            return self.req_log.summary()
        except Exception:
            return {"total": 0, "shown": 0, "by_ip": [], "by_path": [],
                    "by_status": [], "recent": []}

    def clear_request_log(self):
        try:
            with self.req_log._lock:
                self.req_log._rows.clear()
        except Exception:
            pass

    def stop(self):
        for attr in ("httpd", "https_httpd"):
            srv = getattr(self, attr, None)
            if srv is not None:
                try:
                    srv.shutdown()
                    srv.server_close()
                except Exception:
                    pass
            setattr(self, attr, None)
        self.thread = None
        self.https_thread = None
        self.https_error = ""


def _make_handler(db_path, req_log=None):
    """Build a handler class bound to one database file. A fresh DB
    connection is opened per request (never shared across threads)."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "PharmacyEnterpriseMobile/5.0"

        # v5.0 PIN rate limiting: per-IP failure counter. After 5 wrong
        # PINs an IP is locked out for 60 seconds (429, Arabic message).
        # The lock lives in memory only and never blocks the PC app.
        _PIN_FAILS = {}
        _PIN_FAILS_LOCK = threading.Lock()
        _PIN_MAX_FAILS = 5
        _PIN_LOCK_SECONDS = 60
        _MAX_BODY_BYTES = 65536

        # v5.6: generic per-IP rate limit for EVERY request (the PIN
        # lock above only counts failed PINs — a hammering client
        # hitting / or /api/* with no PIN at all was never limited).
        # Legitimate use is ~8 requests/min per phone (one 8s poll);
        # 120/min per IP is generous and never touches a real phone.
        # 127.0.0.1 (the PC's own diagnostics) is exempt.
        _RATE = {}
        _RATE_LOCK = threading.Lock()
        _RATE_MAX_PER_MIN = 120
        _RATE_WINDOW = 60

        def _rate_limited(self):
            ip = self._client_ip()
            if ip in ("127.0.0.1", "::1"):
                return False
            now = time.time()
            with Handler._RATE_LOCK:
                q = Handler._RATE.setdefault(ip, collections.deque())
                while q and q[0] < now - Handler._RATE_WINDOW:
                    q.popleft()
                if len(q) >= Handler._RATE_MAX_PER_MIN:
                    return True
                q.append(now)
                return False

        def send_response(self, code, message=None):
            # v5.6: record every request (status known here) exactly
            # once — the phone's poller, the PC diagnostics, a
            # hammering client, all of it. Query string never logged.
            try:
                if not getattr(self, "_req_logged", False):
                    self._req_logged = True
                    if req_log is not None:
                        req_log.record(
                            self._client_ip(), self.command,
                            urlparse(self.path).path,
                            code, self.headers.get("User-Agent", ""))
            except Exception:
                pass
            return super().send_response(code, message)

        def end_headers(self):
            """Apply browser security policy to every response.

            The mobile page is same-origin and does not need cross-origin
            access.  Keeping this policy in the response boundary also
            covers error responses and the stdlib server's less common
            routes, not only the happy-path JSON helpers.
            """
            if urlparse(self.path).path.startswith("/api/"):
                self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(self)")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "media-src 'self'; connect-src 'self'; worker-src 'self'; "
                "base-uri 'none'; frame-ancestors 'none'",
            )
            return super().end_headers()

        # ---- helpers ----
        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        def _client_ip(self):
            return (self.client_address or ("?",))[0]

        def _pin_locked(self):
            with Handler._PIN_FAILS_LOCK:
                rec = Handler._PIN_FAILS.get(self._client_ip())
                if rec and rec.get("locked_until", 0) > time.time():
                    return True
            return False

        def _pin_failed(self):
            with Handler._PIN_FAILS_LOCK:
                rec = Handler._PIN_FAILS.setdefault(
                    self._client_ip(), {"count": 0, "locked_until": 0})
                rec["count"] += 1
                if rec["count"] >= Handler._PIN_MAX_FAILS:
                    rec["locked_until"] = time.time() + Handler._PIN_LOCK_SECONDS
                    rec["count"] = 0

        def _pin_succeeded(self):
            with Handler._PIN_FAILS_LOCK:
                Handler._PIN_FAILS.pop(self._client_ip(), None)

        def _db(self):
            # v6.2 audit fix (1C): lightweight per-request connection.
            # Schema init, migrations, audit prune and seeding run
            # ONCE at server startup (DB.ensure_initialized, guarded
            # per process — see MobileServer.start()), never on every
            # request. ensure_initialized() is a lock + set lookup
            # when init already ran; if this process never started
            # the server (handler used directly), it inits now so
            # behaviour stays correct. Each request still gets its
            # own connection (sqlite3 connections are not shared
            # across threads); WRITE_LOCK, WAL and the PRAGMAs in
            # DB.__init__ are unchanged.
            DB.ensure_initialized(db_path)
            return DB(path=db_path, init=False)

        def _pin_from_request(self):
            # v6.2: header ONLY. The old ?pin= query-string fallback
            # was removed: a PIN in the URL ends up in logs, browser
            # history and shared links. A client that still sends
            # ?pin= gets a 401 and must switch to X-Mobile-PIN.
            return (self.headers.get("X-Mobile-PIN", "") or "").strip()

        def _pin_ok(self):
            try:
                db = self._db()
                try:
                    want = db.ensure_mobile_pin()
                finally:
                    db.close()
                # constant-time comparison — no early-exit timing leak
                return hmac.compare_digest(self._pin_from_request(), want)
            except Exception:
                return False

        def _send_json(self, status, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, status, body_bytes):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body_bytes)

        _SESSIONS = {}
        _SESSIONS_LOCK = threading.Lock()

        def _session_user(self):
            token = self.headers.get("Authorization", "")
            if not isinstance(self.connection, ssl.SSLSocket) and self._client_ip() not in ("127.0.0.1", "::1"):
                return None
            if not token.startswith("Bearer "):
                return None
            digest = hashlib.sha256(token[7:].encode()).hexdigest()
            with Handler._SESSIONS_LOCK:
                rec = Handler._SESSIONS.get(digest)
            if not rec or rec["expires"] <= time.time():
                return None
            db = self._db()
            try:
                row = db.conn.execute("SELECT * FROM users WHERE id=?", (rec["id"],)).fetchone()
                if not row or row["password_hash"] != rec["password_hash"]:
                    return None
                return dict(row)
            finally:
                db.close()

        def _can_access_sale(self, db, sid):
            sale = db.get_sale(sid)
            if not sale:
                self._send_json(404, {"error": "الفاتورة غير موجودة"})
                return False
            user = getattr(self, "employee", None)
            # Legacy PIN may only access old shared-mobile / desktop rows.
            # It must never bypass the privacy boundary for employee sales.
            allowed = (user and (user["role"] == "admin" or sale["cashier"] == user["username"]))
            if not user:
                allowed = sale["cashier"] == "mobile" or sale.get("source") != "mobile"
            if not allowed:
                self._send_json(403, {"error": "هذه الفاتورة تخص موظفاً آخر"})
                return False
            return True

        def _api_login(self):
            if not isinstance(self.connection, ssl.SSLSocket) and self._client_ip() not in ("127.0.0.1", "::1"):
                self._send_json(403, {"error": "دخول الموظفين يحتاج رابط HTTPS على بورت 8443"})
                return
            if self._pin_locked():
                self._send_json(429, {"error": "انتظر دقيقة قبل إعادة الدخول"})
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= 4096:
                    raise ValueError()
                data = json.loads(self.rfile.read(n).decode())
                username, password = data.get("username"), data.get("password")
                if not isinstance(username, str) or not isinstance(password, str):
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                self._send_json(400, {"error": "بيانات الدخول غير صالحة"})
                return
            db = self._db()
            try:
                user = db.authenticate(username, password)
                if user:
                    user = dict(db.conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())
                if user and db.is_default_password(user["username"]):
                    self._send_json(403, {"error": "غيّر كلمة المرور الافتراضية من الكمبيوتر أولاً"})
                    return
            finally:
                db.close()
            if user and user["username"].lower() == "mobile":
                self._send_json(403, {"error": "الاسم mobile محجوز للدخول المشترك، أنشئ حساباً آخر"})
                return
            if not user:
                self._pin_failed()
                self._send_json(401, {"error": "اسم المستخدم أو كلمة المرور غير صحيحة"})
                return
            self._pin_succeeded()
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            with Handler._SESSIONS_LOCK:
                now = time.time()
                Handler._SESSIONS = {k:v for k,v in Handler._SESSIONS.items() if v["expires"] > now}
                Handler._SESSIONS[digest] = {"id": user["id"], "password_hash": user["password_hash"], "expires": now + 12*3600}
            self._send_json(200, {"token": token, "username": user["username"], "full_name": user["full_name"], "expires_in": 43200})

        def _api_logout(self):
            token = self.headers.get("Authorization", "")
            if token.startswith("Bearer "):
                with Handler._SESSIONS_LOCK:
                    Handler._SESSIONS.pop(hashlib.sha256(token[7:].encode()).hexdigest(), None)
            self._send_json(200, {"ok": True})

        def _require_pin(self):
            self.employee = self._session_user()
            if self.employee:
                return True
            if self.headers.get("Authorization"):
                self._send_json(401, {"error": "انتهت الجلسة، سجل الدخول مجدداً"})
                return False
            db = self._db()
            try:
                legacy_enabled = db.get_setting("mobile_shared_pin_enabled", "1") == "1"
            finally:
                db.close()
            if not legacy_enabled:
                self._send_json(401, {"error": "الدخول المشترك مغلق، استخدم حساب الموظف"})
                return False
            # v5.7 (C9): the lock used to count EVERY unauthenticated
            # hit — 5 probes with no PIN at all locked the IP, and the
            # CORRECT pin was then rejected for 60s. Now: (a) a correct
            # PIN always unlocks immediately — the lock only stops
            # guessing; (b) a request with NO pin supplied at all is
            # not a "wrong PIN attempt" and does not count.
            pin = self._pin_from_request()
            if self._pin_locked():
                if pin and self._pin_ok():
                    self._pin_succeeded()
                    return True
                self._send_json(429, {"error":
                    "محاولات خاطئة كثيرة — انتظر دقيقة واحدة ثم أعد المحاولة"})
                return False
            if not self._pin_ok():
                if pin:
                    self._pin_failed()
                self._send_json(401, {"error": "رمز الموبايل (PIN) غير صحيح"})
                return False
            self._pin_succeeded()
            return True

        # ---- routing ----
        def do_GET(self):
            self._req_logged = False
            if self._rate_limited():
                try:
                    self._send_json(429, {"error": "طلبات كثيرة جداً من هذا الجهاز — انتظر دقيقة"})
                except Exception:
                    pass
                return
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            try:
                if path == "/favicon.ico":
                    # v5.6: browsers request this on every page load;
                    # answer 204 instead of a 404 JSON so it does not
                    # pollute the request log.
                    self.send_response(204)
                    self.send_header("Content-Length", "0")
                    self.send_header("Connection", "close")
                    self.end_headers()
                elif path == "/":
                    self._serve_landing()
                elif path == "/zxing.min.js":
                    # v4.9: serve ONLY the vendored ZXing decoder bundle,
                    # locally, so the phone needs no internet and no CDN.
                    # No directory listing, no other files are served.
                    self._serve_zxing()
                elif path == "/manifest.json":
                    # v6.2 PWA: the install manifest.
                    self._serve_static("manifest.json",
                                       "application/manifest+json; charset=utf-8")
                elif path == "/sw.js":
                    # v6.2 PWA: the service worker (root scope).
                    # Served no-cache so an app update is picked up.
                    self._serve_static("sw.js",
                                       "application/javascript; charset=utf-8",
                                       max_age=0)
                elif path in ("/icon-192.png", "/icon-512.png"):
                    # v6.2 PWA: home-screen icons.
                    self._serve_static(path[1:], "image/png")
                elif path == "/api/drugs":
                    self._api_drugs(parsed)
                elif path == "/api/ref-search":
                    self._api_ref_search(parsed)
                elif path == "/api/live":
                    self._api_live(parsed)
                elif path == "/api/scan-request":
                    # v6.23: the phone asks if the PC wants a barcode scanned.
                    self._api_scan_request()
                elif path == "/api/drug":
                    # v6.10: single-drug lookup by id (?id=123) — the
                    # lightweight cart refresh for ONE drug, without
                    # re-fetching the whole drug list.
                    self._api_drug_by_id(parsed)
                elif path.startswith("/api/drug/"):
                    self._api_drug(unquote(path[len("/api/drug/"):]))
                elif path == "/api/diag":
                    self._api_diag()
                elif path == "/api/customers":
                    self._api_customers(parsed)
                elif path == "/api/cloud-config":
                    # v6.26: Supabase url+key for the phone's cloud mode.
                    self._api_cloud_config()
                elif path == "/api/invoices":
                    self._api_invoices_list(parsed)
                elif path.startswith("/api/invoice/"):
                    self._api_invoice_detail(unquote(path[len("/api/invoice/"):]))
                else:
                    self._send_json(404, {"error": "غير موجود"})
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                # A browser closing a TLS connection while the response is
                # being written is normal (reload, navigation, or cert
                # interstitial). Do not turn it into a server traceback.
                pass
            except Exception as e:
                traceback.print_exc()
                try:
                    # v5.0: generic message — never leak internals to the phone
                    self._send_json(500, {"error": "خطأ داخلي في السيرفر"})
                except Exception:
                    pass

        def do_POST(self):
            self._req_logged = False
            if self._rate_limited():
                try:
                    self._send_json(429, {"error": "طلبات كثيرة جداً من هذا الجهاز — انتظر دقيقة"})
                except Exception:
                    pass
                return
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            try:
                if path == "/api/login":
                    self._api_login()
                elif path == "/api/logout":
                    self._api_logout()
                elif path == "/api/invoices":
                    self._api_create_invoice()
                elif path == "/api/drugs":
                    self._api_create_drug()
                elif path == "/api/scan-result":
                    # v6.23: the phone delivers one scanned barcode.
                    self._api_scan_result()
                elif path.startswith("/api/invoices/") and path.endswith("/edit"):
                    self._api_edit_invoice(path)
                elif path.startswith("/api/invoices/") and path.endswith("/return"):
                    self._api_return_invoice(path)
                else:
                    self._send_json(404, {"error": "غير موجود"})
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                # Same client-disconnect case for POST responses.
                pass
            except Exception as e:
                traceback.print_exc()
                try:
                    self._send_json(500, {"error": "خطأ داخلي في السيرفر"})
                except Exception:
                    pass

        def do_OPTIONS(self):  # phone browsers may preflight
            self.send_response(204)
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, X-Mobile-PIN")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()

        # ---- handlers ----
        def _serve_zxing(self):
            """Serve the vendored ZXing JS bundle (v4.9) — one exact
            file only, application/javascript. The phone loads it
            from the PC server, never from a CDN."""
            js_path = os.path.join(BASE, "zxing.min.js")
            try:
                with open(js_path, "rb") as f:
                    body = f.read()
            except Exception:
                self._send_json(404, {"error": "zxing.min.js غير موجود — انسخ ملف التحديث v4.9"})
                return
            # v5.6: cache it for a day — the phone used to re-download
            # this 329 KB bundle on EVERY page load (no cache headers).
            etag = '"zx-%d-%d"' % (len(body), int(os.path.getmtime(js_path)))
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Connection", "close")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("ETag", etag)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _serve_static(self, filename, content_type, max_age=86400):
            """Serve one exact PWA shell file from the app root
            (v6.2: manifest.json, sw.js, icon-192/512.png). The
            filename is allow-listed — no path traversal, no
            directory listing, no other files are served. API
            responses are never served here and never cached."""
            allowed = {"manifest.json", "sw.js",
                       "icon-192.png", "icon-512.png"}
            if filename not in allowed:
                self._send_json(404, {"error": "غير موجود"})
                return
            fpath = os.path.join(BASE, filename)
            try:
                with open(fpath, "rb") as f:
                    body = f.read()
            except Exception:
                self._send_json(404, {"error": "%s غير موجود" % filename})
                return
            etag = '"st-%s-%d-%d"' % (filename, len(body),
                                     int(os.path.getmtime(fpath)))
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Connection", "close")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            if max_age:
                self.send_header("Cache-Control",
                                 "public, max-age=%d" % max_age)
            else:
                self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", etag)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _serve_landing(self):
            html_path = os.path.join(BASE, "mobile.html")
            try:
                with open(html_path, "rb") as f:
                    body = f.read()
            except Exception:
                body = ("<html><body><h1>mobile.html غير موجود</h1>"
                        "<p>انسخ ملف mobile.html بجانب mobile_server.py</p>"
                        "</body></html>").encode("utf-8")
            # v5.6: ETag + revalidate — the browser asks "changed?"
            # and gets a 304 with no body instead of re-downloading
            # the whole page on every load.
            etag = '"pg-%d-%d"' % (len(body),
                                   int(os.path.getmtime(html_path))) if os.path.isfile(html_path) else '"pg-0"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Connection", "close")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", etag)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _api_cloud_config(self):
            """v6.26: GET /api/cloud-config -> {"url":..., "key":...}.
            PIN-protected like every /api/* call. The phone stores the
            pair in localStorage so its cached PWA can reach Supabase
            directly (cloud mode) when this PC is unreachable. Empty
            strings when sync is not configured — cloud mode then stays
            off on the phone."""
            if not self._require_pin():
                return
            try:
                import supabase_client
                if self.employee:
                    self._send_json(200, {"url": "", "key": ""})
                    return
                url, key = supabase_client.load_config()
                if not supabase_client.browser_safe_key(key):
                    url, key = None, None
            except Exception:
                url, key = None, None
            self._send_json(200, {"url": url or "", "key": key or ""})

        def _api_drugs(self, parsed):
            if not self._require_pin():
                return
            q = (parse_qs(parsed.query).get("q", [""])[0] or "")
            db = self._db()
            try:
                out = [_drug_json(d) for d in db.search_drugs(q, limit=60)]
            finally:
                db.close()
            self._send_json(200, {"drugs": out})

        def _api_ref_search(self, parsed):
            """Worldwide NON-SALE reference catalog (lookup only): no price,
            never part of an invoice. Missing file -> empty list."""
            if not self._require_pin():
                return
            q = (parse_qs(parsed.query).get("q", [""])[0] or "").strip()[:80]
            rows = []
            path = os.path.join(BASE, "reference_catalog.sqlite3")
            if len(q) >= 3 and os.path.isfile(path):
                import sqlite3
                con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
                try:
                    like = "%" + q.replace("%", " ").replace("_", " ") + "%"
                    digits = "".join(c for c in q if c.isdigit())
                    if len(digits) < 6:
                        digits = "-"
                    cur = con.execute(
                        "SELECT source,barcode,name,brand,category,quantity,countries,url,ingredients,form,pack,id_type,source_id "
                        "FROM ref_products WHERE name LIKE ? OR brand LIKE ? OR ingredients LIKE ? OR barcode=? "
                        "ORDER BY (barcode<>'') DESC, name LIMIT 30",
                        (like, like, like, digits))
                    keys = ("source", "barcode", "name", "brand", "category",
                            "quantity", "countries", "url", "ingredients", "form",
                            "pack", "id_type", "source_id")
                    rows = [dict(zip(keys, r)) for r in cur.fetchall()]
                finally:
                    con.close()
            # Rows whose barcode already exists in THIS pharmacy's own catalogue
            # carry that existing Egyptian price (read-only lookup, nothing copied
            # or changed). Everything else stays price-free.
            codes = [r["barcode"] for r in rows if r.get("barcode")]
            if codes:
                db = self._db()
                try:
                    for r in rows:
                        r["in_catalog"] = None
                        if not r.get("barcode"):
                            continue
                        try:
                            d, _pack = db.lookup_barcode(r["barcode"])  # GTIN-normalised
                        except Exception:
                            d = None
                        if d:
                            r["in_catalog"] = {"id": d["id"], "name": d["trade_en"],
                                               "price": d["sell_price"]}
                finally:
                    db.close()
            self._send_json(200, {"ref": rows, "for_sale": False})

        def _api_live(self, parsed):
            """Minimal stock/price refresh for the drugs currently in the cart."""
            if not self._require_pin():
                return
            raw_ids = (parse_qs(parsed.query).get("ids", [""])[0] or "")
            db = self._db()
            try:
                out = [_drug_json(d) for d in db.drugs_by_ids(raw_ids.split(",")[:60])]
            finally:
                db.close()
            self._send_json(200, {"drugs": out})

        def _api_scan_request(self):
            """v6.23: GET /api/scan-request -> {"pending": bool, "id": int}.
            The phone page polls this every few seconds; when the desktop
            scan dialog opened a request, the page offers to start the
            camera. PIN required, same as every API."""
            if not self._require_pin():
                return
            self._send_json(200, _scan_phone_view())

        def _api_scan_result(self):
            """v6.23: POST /api/scan-result {"id": int, "code": str}.
            Accepts the barcode only while its request is still open and
            fresh; anything else is a 409 so the phone can say so."""
            if not self._require_pin():
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except Exception:
                length = 0
            if length > Handler._MAX_BODY_BYTES:
                self._send_json(413, {"error": "الطلب أكبر من المسموح"})
                return
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._send_json(400, {"error": "بيانات غير صالحة (JSON)"})
                return
            if not isinstance(data, dict):
                self._send_json(400, {"error": "بيانات غير صالحة"})
                return
            try:
                rid = int(data.get("id") or 0)
            except Exception:
                rid = 0
            if _scan_phone_submit(rid, str(data.get("code") or "")):
                self._send_json(200, {"ok": True})
            else:
                self._send_json(409, {"error": "انتهت مهلة طلب المسح — اطلب من جديد من الكمبيوتر"})

        def _api_drug(self, barcode):
            if not self._require_pin():
                return
            db = self._db()
            try:
                drug, _pack = db.lookup_barcode(barcode)
            finally:
                db.close()
            if not drug:
                self._send_json(404, {"error": "الباركود غير مسجل"})
                return
            self._send_json(200, {"drug": _drug_json(drug)})

        def _api_drug_by_id(self, parsed):
            """v6.10: GET /api/drug?id=<id> — one drug by id (same
            _drug_json shape as /api/drug/<barcode>). PIN required;
            non-numeric or unknown id is 404, never a crash."""
            if not self._require_pin():
                return
            try:
                did = int((parse_qs(parsed.query).get("id", [""])[0] or ""))
            except Exception:
                self._send_json(404, {"error": "غير موجود"})
                return
            db = self._db()
            try:
                drug = db.get_drug(did)
            finally:
                db.close()
            if not drug:
                self._send_json(404, {"error": "غير موجود"})
                return
            self._send_json(200, {"drug": _drug_json(drug)})

        def _api_create_drug(self):
            """v6.5: POST /api/drugs (PIN required) — add a drug from
            the phone when a scanned barcode is not in the DB. Reuses
            the PC Add-Drug validation in DB.add_drug() — no second
            set of rules. A barcode already linked to another drug
            is a clear 400, never a silent steal
            (DB._link_barcode_checked)."""
            if not self._require_pin():
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except Exception:
                length = 0
            if length > Handler._MAX_BODY_BYTES:
                self._send_json(413, {"error": "بيانات الدواء أكبر من المسموح"})
                return
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._send_json(400, {"error": "بيانات غير صالحة (JSON)"})
                return
            if not isinstance(data, dict):
                self._send_json(400, {"error": "بيانات غير صالحة"})
                return
            fields = {
                "trade_en": str(data.get("trade_en") or "").strip(),
                "trade_ar": str(data.get("trade_ar") or "").strip(),
                "scientific": str(data.get("scientific") or "").strip(),
                "company": str(data.get("company") or "").strip(),
                "form": str(data.get("form") or "").strip(),
                "strength": str(data.get("strength") or "").strip(),
                "category": str(data.get("category") or "").strip(),
                "barcode": str(data.get("barcode") or "").strip(),
                "discount_type": str(data.get("discount_type") or "none").strip().lower(),
            }
            for key, default in (("strips_per_box", 1),
                                 ("tablets_per_strip", 1),
                                 ("min_stock", 5)):
                try:
                    v = data.get(key)
                    fields[key] = int(v) if v not in (None, "") else default
                except Exception:
                    self._send_json(400, {"error": "قيمة عددية غير صالحة"})
                    return
            for key in ("buy_price", "sell_price", "discount_value"):
                try:
                    fields[key] = float(data.get(key) or 0)
                except Exception:
                    self._send_json(400, {"error": "قيمة سعر غير صالحة"})
                    return
            with WRITE_LOCK:
                db = self._db()
                try:
                    drug_id = db.add_drug(fields)
                    db.audit("mobile", "mobile_add_drug",
                             "%s (barcode %s)" % (fields["trade_en"],
                                                  fields["barcode"] or "-"))
                    drug = db.get_drug(drug_id)
                except ValueError as e:
                    self._send_json(400, {"error": str(e)})
                    return
                finally:
                    db.close()
            self._send_json(200, {"ok": True, "drug": _drug_json(drug),
                                  "message": "تمت إضافة الدواء"})

        def _api_customers(self, parsed):
            if not self._require_pin():
                return
            q = (parse_qs(parsed.query).get("q", [""])[0] or "")
            db = self._db()
            try:
                rows = db.customers(q)
            finally:
                db.close()
            self._send_json(200, {"customers": [
                {"id": c["id"], "name": c["name"], "phone": c["phone"],
                 "balance": c["balance"], "credit_limit": c["credit_limit"]}
                for c in rows]})

        def _api_diag(self):
            """v5.6: GET /api/diag (PIN required) — what the phone
            page needs to explain a camera failure: the PC's current
            IPs, the cert's SANs, and whether the cert covers the
            address the phone actually opened."""
            if not self._require_pin():
                return
            try:
                ips = [it["ip"] for it in get_all_lan_ips()]
            except Exception:
                ips = []
            self._send_json(200, {
                "ips": ips,
                "cert_sans": sorted(cert_san_ips(CERT_FILE)) if cert_files_exist() else [],
                "cert_covers_current": bool(
                    ips and any(ip in cert_san_ips(CERT_FILE) for ip in ips
                                if not ip.startswith("127."))),
                "https_running": True,
            })

        def _api_invoices_list(self, parsed):
            if not self._require_pin():
                return
            qs = parse_qs(parsed.query)
            status = (qs.get("status", [""])[0] or "")
            db = self._db()
            try:
                user = getattr(self, "employee", None)
                if user and user["role"] != "admin":
                    rows = [dict(r) for r in db.conn.execute(
                        "SELECT * FROM sales WHERE cashier=? ORDER BY id DESC", (user["username"],)).fetchall()]
                    df = qs.get("date_from", [""])[0]
                    dt = qs.get("date_to", [""])[0]
                    q = qs.get("q", [""])[0].strip().lower()
                    rows = [r for r in rows if (not df or r["date"] >= df) and (not dt or r["date"] <= dt)
                            and (not q or q in r["invoice_no"].lower())]
                    if status == "pending_print":
                        rows = [r for r in rows if r["source"] == "mobile" and r["status"] == "completed" and not r["printed_at"]]
                    rows = rows[:200]
                elif status == "pending_print":
                    rows = db.pending_phone_invoices()
                elif qs.get("history", [""])[0] == "1":
                    # v5.5: full invoice history — PC + phone, newest
                    # first, filterable by number / date / customer.
                    # q matches EITHER invoice number OR customer, so
                    # fetch both ways and merge (get_all_sales ANDs
                    # its filters, which would match almost nothing).
                    q = (qs.get("q", [""])[0] or "").strip()
                    df = qs.get("date_from", [""])[0] or None
                    dt = qs.get("date_to", [""])[0] or None
                    if q:
                        seen, rows = set(), []
                        for r in (db.get_all_sales(date_from=df, date_to=dt,
                                                   customer=q, limit=200)
                                  + db.get_all_sales(date_from=df, date_to=dt,
                                                     invoice_no=q, limit=200)):
                            if r["id"] not in seen:
                                seen.add(r["id"])
                                rows.append(r)
                        rows.sort(key=lambda r: r["id"], reverse=True)
                    else:
                        rows = db.get_all_sales(date_from=df, date_to=dt, limit=200)
                else:
                    rows = db.sales_on()
            finally:
                db.close()
            if not getattr(self, "employee", None):
                rows = [r for r in rows if r["cashier"] == "mobile" or r.get("source") != "mobile"]
            self._send_json(200, {"invoices": rows})

        def _api_invoice_detail(self, sale_id):
            """v5.5: GET /api/invoice/<id> — one invoice + lines."""
            if not self._require_pin():
                return
            try:
                sid = int(sale_id)
            except Exception:
                self._send_json(400, {"error": "رقم فاتورة غير صحيح"})
                return
            db = self._db()
            try:
                if not self._can_access_sale(db, sid):
                    return
                detail = db.sale_detail(sid)
            finally:
                db.close()
            if not detail:
                self._send_json(404, {"error": "الفاتورة غير موجودة"})
                return
            self._send_json(200, {"invoice": detail})

        def _api_return_invoice(self, path):
            """v6.17: POST /api/invoices/<id>/return — FULL return (void)
            of a completed invoice from the phone: same return_sale()
            the PC uses — every batch restocked, credit reversed,
            status -> returned, sale_returns + audit written, one
            atomic transaction. An empty invoice can never be SAVED by
            the edit flow, so when the phone user deletes every line
            and approves, the client offers this explicit full-cancel
            instead of a dead-end message. A returned invoice is
            refused (no double restock)."""
            if not self._require_pin():
                return
            try:
                sid = int(path.split("/")[3])
            except Exception:
                self._send_json(400, {"error": "رقم فاتورة غير صحيح"})
                return
            with WRITE_LOCK:
                db = self._db()
                try:
                    if not self._can_access_sale(db, sid):
                        return
                    db.return_sale(sid, self.employee["username"] if self.employee else "mobile",
                                   reason="إلغاء كامل من الموبايل")
                except ValueError as e:
                    self._send_json(400, {"error": str(e)})
                    return
                finally:
                    db.close()
            self._send_json(200, {"ok": True, "sale_id": sid,
                                  "message": "أُلغيت الفاتورة (إرجاع كامل) — رجعت الكميات للمخزون"})

        def _api_edit_invoice(self, path):
            """v5.5: POST /api/invoices/<id>/edit — same edit_sale()
            the PC uses (one atomic transaction, FEFO restock +
            deduct, audit). PIN + rate limiting via _require_pin."""
            if not self._require_pin():
                return
            try:
                sid = int(path.split("/")[3])
            except Exception:
                self._send_json(400, {"error": "رقم فاتورة غير صحيح"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except Exception:
                length = 0
            if length > Handler._MAX_BODY_BYTES:
                self._send_json(413, {"error": "بيانات الفاتورة أكبر من المسموح"})
                return
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._send_json(400, {"error": "بيانات غير صالحة (JSON)"})
                return
            items = data.get("items")
            if not isinstance(items, list) or not items:
                self._send_json(400, {"error": "بيانات أصناف غير صالحة"})
                return
            # v5.8: staged deletion — a line missing from `items`
            # that WAS on the saved invoice is a deletion, and it is
            # applied ONLY with an explicit approval: approved=true
            # AND deleted_items listing every omitted line. A payload
            # without that approval is refused and changes nothing
            # (no stock, credit or audit change). Qty changes and
            # added lines do not need the deletion approval.
            _db0 = self._db()
            try:
                if not self._can_access_sale(_db0, sid):
                    return
                _detail = _db0.sale_detail(sid)
            finally:
                _db0.close()
            if not _detail:
                self._send_json(404, {"error": "الفاتورة غير موجودة"})
                return
            _orig_keys = {(it.get("drug_id"), it.get("pack_level") or "box")
                          for it in (_detail.get("items") or [])}
            _new_keys = set()
            for _sp in items:
                try:
                    _new_keys.add((int(_sp.get("drug_id")),
                                   str(_sp.get("unit") or _sp.get("pack_level") or "box").strip()))
                except Exception:
                    pass
            _omitted = _orig_keys - _new_keys
            if _omitted:
                _deleted_keys = set()
                for _d in (data.get("deleted_items") or []):
                    try:
                        _deleted_keys.add((int(_d.get("drug_id")),
                                           str(_d.get("unit") or _d.get("pack_level") or "box").strip()))
                    except Exception:
                        pass
                if data.get("approved") is not True or not _omitted.issubset(_deleted_keys):
                    self._send_json(400, {"error": "الحذف يحتاج اعتماداً صريحاً — أعد إرسال التعديل مع approved=true وقائمة الأصناف المحذوفة المعتمدة (deleted_items)"})
                    return
            # v5.7 (C10): unknown payment / garbage discount / garbage
            # paid used to be silently coerced (to cash / 0 / full
            # payment). Now they are a clear 400.
            payment = str(data.get("payment") or "cash").strip()
            if payment not in ("cash", "card", "credit"):
                self._send_json(400, {"error": "طريقة دفع غير صالحة"})
                return
            customer_id = data.get("customer_id")
            try:
                customer_id = int(customer_id) if customer_id not in (None, "") else None
            except Exception:
                self._send_json(400, {"error": "رقم عميل غير صالح"})
                return
            # v5.7 (B5): no pre-check here — edit_sale() falls back
            # to the invoice's existing customer when none is sent
            # (the phone edit screen never sends one), and raises
            # itself if the invoice truly has no customer.
            try:
                discount = float(data.get("discount") or 0)
            except Exception:
                self._send_json(400, {"error": "خصم غير صالح"})
                return
            paid = data.get("paid")
            try:
                paid = float(paid) if paid is not None else None
            except Exception:
                self._send_json(400, {"error": "مبلغ مدفوع غير صالح"})
                return
            with WRITE_LOCK:
                db = self._db()
                try:
                    if not self._can_access_sale(db, sid):
                        return
                    res = db.edit_sale_from_items(
                        sid, self.employee["username"] if self.employee else "mobile", items, discount=discount,
                        payment_method=payment, customer_id=customer_id,
                        paid=paid)
                except ValueError as e:
                    self._send_json(400, {"error": str(e)})
                    return
                finally:
                    db.close()
            self._send_json(200, {"ok": True, **res,
                                  "message": "تم تعديل الفاتورة — الإجمالي الجديد: %.2f ج.م" % res["new_total"]})

        def _api_create_invoice(self):
            if not self._require_pin():
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except Exception:
                length = 0
            # v5.0: refuse oversized bodies (was unbounded)
            if length > Handler._MAX_BODY_BYTES:
                self._send_json(413, {"error": "بيانات الفاتورة أكبر من المسموح"})
                return
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._send_json(400, {"error": "بيانات غير صالحة (JSON)"})
                return
            items = data.get("items")
            if not isinstance(items, list) or not items:
                self._send_json(400, {"error": "بيانات أصناف غير صالحة"})
                return
            # v5.7 (C5/C10): convert customer_id FIRST — the old code
            # checked "credit needs a customer" on the raw value, so
            # customer_id:"abc" passed the check, became None, and a
            # credit sale was saved with no customer at all. Unknown
            # payment / garbage discount / garbage paid are now a
            # clear 400 instead of silent coercion.
            payment = str(data.get("payment") or "cash").strip()
            if payment not in ("cash", "card", "credit"):
                self._send_json(400, {"error": "طريقة دفع غير صالحة"})
                return
            customer_id = data.get("customer_id")
            try:
                customer_id = int(customer_id) if customer_id not in (None, "") else None
            except Exception:
                self._send_json(400, {"error": "رقم عميل غير صالح"})
                return
            if payment == "credit" and not customer_id:
                self._send_json(400, {"error": "البيع الآجل يحتاج عميل مسجل"})
                return
            try:
                discount = float(data.get("discount") or 0)
            except Exception:
                self._send_json(400, {"error": "خصم غير صالح"})
                return
            paid = data.get("paid")
            try:
                paid = float(paid) if paid is not None else None
            except Exception:
                self._send_json(400, {"error": "مبلغ مدفوع غير صالح"})
                return
            note = str(data.get("note") or "").strip()
            # v5.0: idempotency — the phone sends client_ref once per
            # invoice; if the phone retries after a disconnect, the
            # SAME sale is returned instead of selling twice.
            client_ref = str(data.get("client_ref") or "")[:64]
            if self.employee and client_ref:
                client_ref = "u%d:%s" % (self.employee["id"], hashlib.sha256(client_ref.encode()).hexdigest()[:48])
            # Serialise writes: two phones must never sell the same
            # last box twice.
            with WRITE_LOCK:
                db = self._db()
                try:
                    # STEP2 (2A): bind the mobile sale to the current
                    # employee's own open shift, or the legacy shared
                    # active shift for shared-PIN phones. When no
                    # shift is open the sale keeps shift_id=None and
                    # shows up in the "مبيعات بدون وردية" line of the
                    # next shift reconciliation instead of vanishing.
                    cashier = self.employee["username"] if self.employee else "mobile"
                    existing = db.conn.execute("SELECT cashier FROM sales WHERE client_ref=?", (client_ref,)).fetchone() if client_ref else None
                    if existing and existing["cashier"] != cashier:
                        self._send_json(403, {"error": "مرجع الفاتورة يخص موظفاً آخر"})
                        return
                    sale_id, invoice_no, total, change = db.create_sale_from_items(
                        cashier=self.employee["username"] if self.employee else "mobile", items_spec=items,
                        discount=discount,
                        payment_method=payment, customer_id=customer_id,
                        paid=paid, shift_id=(db.open_shift_for(self.employee["username"]) or {}).get("id") if self.employee else db.active_shift_id(),
                        source="mobile", client_ref=client_ref)
                    if note:
                        db.audit(self.employee["username"] if self.employee else "mobile", "mobile_invoice_note",
                                 "%s: %s" % (invoice_no, note[:200]))
                except ValueError as e:
                    self._send_json(400, {"error": str(e)})
                    return
                finally:
                    db.close()
            self._send_json(200, {"ok": True, "sale_id": sale_id,
                                  "invoice_no": invoice_no,
                                  "total": total, "change": change,
                                  "message": "تم الحفظ — جاهزة للطباعة من الكمبيوتر"})

    return Handler


def _drug_json(d):
    return {
        "id": d["id"],
        "trade_en": d["trade_en"],
        "trade_ar": d.get("trade_ar", ""),
        "scientific": d.get("scientific", ""),
        "strength": d.get("strength", ""),
        "form": d.get("form", ""),
        "discount_type": d.get("discount_type", "none") or "none",
        "discount_value": float(d.get("discount_value") or 0),
        "company": d.get("company", ""),
        "sell_price": d["sell_price"],
        "price_box": unit_price(d, "box"),
        "price_strip": unit_price(d, "strip"),
        "price_pill": unit_price(d, "pill"),
        # v6.8: form-based units — the phone only renders buttons
        # for these (a cream gets box only, no strip/pill).
        "allowed_units": allowed_units(d),
        "strips_per_box": int(d["strips_per_box"] or 1),
        "tablets_per_strip": int(d["tablets_per_strip"] or 1),
        "units_per_box": units_per_box(d),
        "stock_units": d.get("stock_units", 0),
        "stock_boxes": d.get("stock_boxes", 0),
    }


def main():
    import sys
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except Exception:
            pass
    try:
        db = DB()
        pin = db.ensure_mobile_pin()
        db.close()
    except Exception as e:
        print("ERROR opening database: %s" % e)
        try:
            input("حدث خطأ. اضغط Enter للخروج...")
        except Exception:
            pass
        return
    srv = MobileServer(port=port)
    if not srv.start():
        print("ERROR: could not start server on port %d — is it already running?" % port)
        print("If Windows Firewall asks, choose 'Allow' for private networks.")
        try:
            input("اضغط Enter للخروج...")
        except Exception:
            pass
        return
    print("Pharmacy Enterprise — Mobile server running")
    print("Open on the phone (same network as the URL you use):")
    for u in srv.url_list:
        print("  %s  (%s)" % (u["url"], u["label"]))
    if not srv.url_list:
        print("  No LAN IP found — check the PC network, then use: %s" % srv.url)
    if srv.https_running:
        print("Secure (HTTPS) — use this URL for CAMERA SCANNING:")
        for u in srv.https_url_list:
            print("  %s  (%s)" % (u["url"], u["label"]))
        print("First time on the phone: Advanced > Proceed (self-signed cert).")
    else:
        print("HTTPS NOT running: %s" % (srv.https_error or "unknown reason"))
        print("Camera scanning needs HTTPS — the server generates certs/cert.pem + certs/key.pem on start (PowerShell 7 or openssl).")
    print("Mobile PIN: shown in the PC app (Mobile tab) — never printed here.")
    print("Press Ctrl+C to stop.")
    try:
        import time
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()


if __name__ == "__main__":
    main()
