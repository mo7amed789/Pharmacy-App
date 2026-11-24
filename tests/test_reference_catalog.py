# -*- coding: utf-8 -*-
"""Reference catalog is lookup-only: no price column, junk names skipped,
no-barcode products kept, and the phone page/API never offer it for sale."""
import gzip, json, os, sqlite3, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "catalog"))
import build_reference_catalog as b

tmp = tempfile.mkdtemp()
src = os.path.join(tmp, "openbeautyfacts-products.jsonl.gz")
rows = [
    {"code": "4006000137674", "product_name": "Nivea Cream", "brands": "Nivea", "countries_tags": ["en:germany"]},
    {"code": "123", "product_name": "0"},                      # junk name
    {"code": "999", "product_name": ""},                       # no name
    {"_id": "nocode-1", "code": "", "product_name": "Plain Soap"},  # no barcode kept
]
with gzip.open(src, "wt", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")
b.OUT = os.path.join(tmp, "reference_catalog.sqlite3")
n = b.build([("Open Beauty Facts", src)])
assert n == 2, n
con = sqlite3.connect(b.OUT)
cols = [r[1] for r in con.execute("PRAGMA table_info(ref_products)")]
assert not any("price" in c for c in cols), cols
assert con.execute("SELECT barcode FROM ref_products WHERE name='Plain Soap'").fetchone()[0] == ""
html = open(os.path.join(ROOT, "mobile.html"), encoding="utf-8").read()
assert 'id="refResults"' in html and "غير متاح للبيع" in html
srv = open(os.path.join(ROOT, "mobile_server.py"), encoding="utf-8").read()
assert '"for_sale": False' in srv and "mode=ro" in srv
print("reference catalog tests OK")
