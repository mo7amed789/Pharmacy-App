"""اختبارات v6.27 — تقسيم أدكن لصفحة الموبايل بناءً على ملاحظة المستخدم:
«مش كل حاجة ساحة على بعضها» — حقول جنب بعضها، بطاقات أضيق، وشبكة
عمودين على العرض الأوسع، دون المساس بأي id أو وظيفة.

Run: python3 tests/test_web_layout_v625.py"""
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

# ---------- version + cache ----------
check("window title at v6.27", "Pharmacy Enterprise v6.28" in main_src)
check("login label at v6.27", "نظام إدارة الصيدلية — v6.28" in main_src)
sw = open(os.path.join(SRC, "sw.js"), encoding="utf-8").read()
check("service-worker cache bumped to current", "pharmacy-mobile-v628" in sw)

# ---------- layout structure ----------
check("grid2 two-column field utility exists",
      re.search(r"\.grid2\{display:grid;grid-template-columns:1fr 1fr", css) is not None)
check("wide-screen two-column section grid (cols2)",
      "@media (min-width:640px)" in css and ".cols2{" in css)
check("cart and payment cards grouped in cols2",
      '<div class="cols2">' in html and html.index('<div class="cols2">') < html.index('id="cart"') < html.index('id="customerSelect"'))
check("customer + payment method side by side",
      html.index('id="customerSelect"') < html.index('id="payMethod"') and
      'grid2' in html[html.index('id="customerSelect"') - 400:html.index('id="customerSelect"')])
check("add-drug step1 pairs the trade names",
      'grid2' in html[html.index('id="adStep1"'):html.index('id="adStep2"')])
check("add-drug step2 pairs scientific/company/form/strength",
      'grid2' in html[html.index('id="adStep2"'):html.index('id="adStep3"')])
check("history search + date side by side",
      'grid2' in html[html.index('id="histSearch"') - 100:html.index('id="histSearch"') + 400])
check("tighter card rhythm (13px padding, 10px gap)",
      "padding:13px 14px;margin-bottom:10px" in css)

# ---------- no functional regression ----------
ids_used = sorted(set(re.findall(r"\$\('([A-Za-z0-9_]+)'\)", js)))
ids_def = set(re.findall(r'id="([A-Za-z0-9_]+)"', html))
missing = [i for i in ids_used if i not in ids_def]
check("all %d JS-referenced ids present" % len(ids_used), not missing, ",".join(missing))
check("datalist moved but still linked to adForm",
      'list="adFormList"' in html and 'id="adFormList"' in html)
check("PIN flow intact", "savePin" in js and "X-Mobile-PIN" in js)
check("scan + PC scan-request intact", "startScan" in js and "pollPcScan" in js)
check("invoice save intact", "saveInvoice" in js)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
