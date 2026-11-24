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

# openFDA NDC rows
fda = {"results": [
    {"product_ndc": "1-1", "finished": True, "brand_name": "TestDrug", "labeler_name": "Lab", "marketing_category": "ANDA",
     "dosage_form": "TABLET", "active_ingredients": [{"name": "X", "strength": "5 mg"}],
     "openfda": {"upc": ["0123456789012"]},
     "packaging": [{"package_ndc": "1-1-1", "description": "30 TABLET in 1 BOTTLE"}, {"package_ndc": "1-1-2", "description": "90 TABLET in 1 BOTTLE"}]},
    {"product_ndc": "1-1", "finished": True, "brand_name": "TestDrug", "marketing_category": "ANDA",
     "packaging": [{"package_ndc": "1-1-1", "description": "dup package"}]},           # duplicate package_ndc
    {"product_ndc": "2-2", "finished": True, "generic_name": "Multi Upc", "marketing_category": "NDA",
     "openfda": {"upc": ["111111111111", "222222222222"]}, "packaging": [{"package_ndc": "2-2-1"}]},
    {"product_ndc": "3-3", "finished": True, "brand_name": "Bulk Stuff", "marketing_category": "BULK INGREDIENT",
     "packaging": [{"package_ndc": "3-3-1"}]},
    {"product_ndc": "4-4", "finished": False, "brand_name": "Unfinished", "packaging": [{"package_ndc": "4-4-1"}]},
]}
fp = os.path.join(tmp, "drug-ndc-0001-of-0001.json")
json.dump(fda, open(fp, "w"))
b.OUT = os.path.join(tmp, "ref2.sqlite3")
assert b.build([(b.FDA, fp)]) == 3
con = sqlite3.connect(b.OUT)
r = {x[0]: x for x in con.execute("SELECT source_id,barcode,id_type,pack FROM ref_products")}
assert r["1-1-1"][1] == "123456789012" or r["1-1-1"][1] == "0123456789012", r  # single UPC kept
assert r["2-2-1"][1] == "", r            # several UPCs -> no barcode guessed
assert all(v[2] == "NDC" for v in r.values())
assert "3-3-1" not in r and "4-4-1" not in r
assert r["1-1-1"][3].startswith("30 TABLET")  # first package row wins
print("reference catalog tests OK")
