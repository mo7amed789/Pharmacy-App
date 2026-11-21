"""اختبارات v6.24 — واجهة انتربرايز لصفحة الموبايل (mobile.html).

إعادة تصميم شكلية بالكامل (CSS فقط) بأسلوب Windows 11 Fluent الموحّد مع
برنامج الكمبيوتر: هيدر بتدرّج لوني، بطاقات بظلال، أزرار وحالات ألوان
موحّدة، شريط تنقّل مقسّم، حقول بحلقات تركيز. كل الـ IDs والـ classes
التي يعتمد عليها JavaScript يجب أن تبقى موجودة — لا كسر للسلوك.

Run: python3 tests/test_enterprise_web_v624.py"""
import os
import re
import sys

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "..")
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (" | " + str(extra) if extra and not cond else ""))

html = open(os.path.join(SRC, "mobile.html"), encoding="utf-8").read()
css = html[html.index("<style>"):html.index("</style>")]
js = html[html.index("<script>"):]
main_src = open(os.path.join(SRC, "main.py"), encoding="utf-8").read()

# ---------- 1) version + cache ----------
check("window title at v6.24", "Pharmacy Enterprise v6.24" in main_src)
check("login label at v6.24", "نظام إدارة الصيدلية — v6.24" in main_src)
sw = open(os.path.join(SRC, "sw.js"), encoding="utf-8").read()
check("service-worker cache bumped for the new page",
      "pharmacy-mobile-v624" in sw)

# ---------- 2) every id the JS uses still exists in the markup ----------
ids_used = sorted(set(re.findall(r"\$\('([A-Za-z0-9_]+)'\)", js)))
ids_def = set(re.findall(r'id="([A-Za-z0-9_]+)"', html))
missing = [i for i in ids_used if i not in ids_def]
check("all %d JS-referenced ids present in HTML" % len(ids_used), not missing, ",".join(missing))

# ---------- 3) every class family the JS/HTML uses still has CSS ----------
need_selectors = [".hidden", ".ltr", "header", ".top", ".logo", ".conn",
                  ".dot", "nav button", "nav button.on", "main", ".card",
                  ".muted", "input", "label.f", ".btn", ".btn.sec",
                  ".btn.gray", ".btn.red", ".btn.blue", ".row", ".search",
                  ".msg", ".msg.err", ".msg.ok", ".toast", ".warnl",
                  ".box", ".box.err", ".box.warn", ".drug", ".stock",
                  ".stock.low", ".units button", ".line", ".line.held",
                  ".qty button", ".pay button", ".pay button.sel", "#bar",
                  "#scanArea", "#scanVideo", ".frame", ".inv", ".ok-s",
                  ".steps i", ".steps i.on"]
miss = [n for n in need_selectors if n not in css]
check("all %d functional selectors styled" % len(need_selectors), not miss, ",".join(miss))

# ---------- 4) the enterprise theme is actually there ----------
check("desktop-matched palette: deep teal header gradient",
      "#0B3B39" in css and "linear-gradient" in css)
check("desktop-matched accent teal #0D9488", "#0D9488" in css)
check("Fluent font stack (Segoe UI Variable)", "Segoe UI Variable" in css)
check("cards are layered (box-shadow)", re.search(r"\.card\{[^}]*box-shadow", css) is not None)
check("consistent status colors (success/warning/danger/info)",
      all(c in css for c in ("#059669", "#D97706", "#DC2626", "#2563EB")))
check("focus ring on inputs", ":focus" in css and "0 0 0 3px rgba(13,148,136" in css)
check("focus-visible on buttons", "focus-visible" in css)
check("nav is a segmented control (active pill)", re.search(r"nav button\.on\{[^}]*background:#fff", css) is not None)
check("sticky blurred bottom bar", "backdrop-filter" in css)
check("buttons have press feedback", ".btn:active" in css and "scale(" in css)
check("tabular numbers for prices", "tabular-nums" in css)
check("reduced-motion respected", "prefers-reduced-motion" in css)
check("theme-color matches the header",
      '<meta name="theme-color" content="#0B3B39">' in html)

# ---------- 5) functional wiring untouched ----------
check("PIN flow intact", "savePin" in js and "X-Mobile-PIN" in js)
check("scan stack intact (live + photo)",
      "startScan" in js and "onPhotoPicked" in js and "BarcodeDetector" in js)
check("v6.23 PC scan-request flow intact",
      "pollPcScan" in js and "pcScanStart" in js and "/api/scan-result" in js)
check("invoice save intact", "saveInvoice" in js and "/api/invoices" in js)
check("history edit/void intact", "saveHistoryEdit" in js and "askVoidInvoice" in js)
check("service worker registration intact", "serviceWorker" in js and "/sw.js" in js)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
