# -*- coding: utf-8 -*-
"""Build the NON-SALE worldwide reference catalog (stdlib only).

Reads Open Beauty Facts / Open Products Facts JSONL dumps (ODbL 1.0) and the
US openFDA NDC drug listing (CC0, public domain) and writes
reference_catalog.sqlite3 next to mobile_server.py. This file is a lookup aid
only: it is never imported into the sale database (drugs), has no price column
and nothing in it can be added to an invoice.

    py catalog/build_reference_catalog.py            # downloads the dumps
    py catalog/build_reference_catalog.py a.jsonl.gz # use local dump(s); a file with 'ndc' in its name is read as openFDA NDC

Rows without a usable product name (under 3 characters or no letters) are skipped. A product with no barcode is kept
(barcode = '') and identified by its source + source_id.
"""
import gzip
import json
import os
import sqlite3
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "reference_catalog.sqlite3")
DUMPS = {
    "Open Beauty Facts": "https://static.openbeautyfacts.org/data/openbeautyfacts-products.jsonl.gz",
    "Open Products Facts": "https://static.openproductsfacts.org/data/openproductsfacts-products.jsonl.gz",
}
FDA_URL = "https://download.open.fda.gov/drug/ndc/drug-ndc-0001-of-0001.json.zip"
FDA = "openFDA NDC"
PAGE = {"Open Beauty Facts": "https://world.openbeautyfacts.org/product/",
        "Open Products Facts": "https://world.openproductsfacts.org/product/"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS ref_products(
  source TEXT NOT NULL, source_id TEXT NOT NULL, barcode TEXT DEFAULT '',
  name TEXT NOT NULL, brand TEXT DEFAULT '', category TEXT DEFAULT '',
  quantity TEXT DEFAULT '', countries TEXT DEFAULT '', url TEXT DEFAULT '',
  ingredients TEXT DEFAULT '', form TEXT DEFAULT '', pack TEXT DEFAULT '',
  id_type TEXT DEFAULT 'barcode',
  PRIMARY KEY(source, source_id));
CREATE INDEX IF NOT EXISTS ref_barcode ON ref_products(barcode);
CREATE INDEX IF NOT EXISTS ref_name ON ref_products(name COLLATE NOCASE);
"""


def _s(v, n=200):
    return str(v or "").strip().replace("\n", " ")[:n]


def rows_from(path, source):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                p = json.loads(line)
            except ValueError:
                continue
            name = _s(p.get("product_name") or p.get("product_name_en") or p.get("generic_name"))
            code = "".join(c for c in str(p.get("code") or "") if c.isdigit())
            sid = code or _s(p.get("_id"))
            if len(name) < 3 or not any(c.isalpha() for c in name) or not sid:
                continue
            cats = _s(p.get("categories"), 160)
            countries = ", ".join((p.get("countries_tags") or [])[:4]).replace("en:", "")
            yield (source, sid, code, name, _s(p.get("brands"), 80), cats,
                   _s(p.get("quantity"), 40), countries, PAGE[source] + sid,
                   "", "", "", "barcode")


def rows_from_fda(path, source=FDA):
    """openFDA NDC (CC0). One row per package_ndc (the official package ID, which
    is NOT a retail barcode and stays in source_id). barcode is filled only when
    the record carries exactly one UPC; several UPCs -> blank, never a guess.
    Bulk ingredients and 'further processing' listings are skipped."""
    import zipfile
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = [n for n in z.namelist() if n.endswith(".json")][0]
            data = json.loads(z.read(name).decode("utf-8"))
    else:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    for x in data.get("results", []):
        if not x.get("finished") or x.get("marketing_category") in (
                "BULK INGREDIENT", "DRUG FOR FURTHER PROCESSING"):
            continue
        name = _s(x.get("brand_name") or x.get("generic_name"))
        if len(name) < 3 or not any(c.isalpha() for c in name):
            continue
        upcs = [u for u in ((x.get("openfda") or {}).get("upc") or [])]
        upc = "".join(c for c in upcs[0] if c.isdigit()) if len(upcs) == 1 else ""
        ing = "; ".join(("%s %s" % (a.get("name", ""), a.get("strength", ""))).strip()
                        for a in (x.get("active_ingredients") or [])[:8])
        for pk in x.get("packaging") or []:
            pid = _s(pk.get("package_ndc"), 40)
            if not pid:
                continue
            yield (source, pid, upc, name, _s(x.get("labeler_name"), 80),
                   _s(x.get("marketing_category"), 60), "", "us",
                   "https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query=" + pid,
                   _s(ing, 240), _s(x.get("dosage_form"), 60), _s(pk.get("description"), 160), "NDC")


def build(paths):
    tmp = OUT + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    total = 0
    for source, path in paths:
        gen = rows_from_fda(path, source) if source == FDA else rows_from(path, source)
        con.executemany("INSERT OR IGNORE INTO ref_products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", gen)
        con.commit()
    total = con.execute("SELECT COUNT(*) FROM ref_products").fetchone()[0]
    con.close()
    os.replace(tmp, OUT)
    return total


def main(argv):
    if argv:
        def kind(a):
            b = os.path.basename(a)
            if "ndc" in b:
                return FDA
            return "Open Products Facts" if "openproducts" in b else "Open Beauty Facts"
        paths = [(kind(a), a) for a in argv]
    else:
        paths = []
        for source, url in list(DUMPS.items()) + [(FDA, FDA_URL)]:
            dest = os.path.join(BASE, "catalog", os.path.basename(url))
            print("downloading", url)
            urllib.request.urlretrieve(url, dest)
            paths.append((source, dest))
    print("reference rows:", build(paths), "->", OUT)


if __name__ == "__main__":
    main(sys.argv[1:])
