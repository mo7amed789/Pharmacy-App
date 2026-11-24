# -*- coding: utf-8 -*-
"""Build the NON-SALE worldwide reference catalog (stdlib only).

Reads Open Beauty Facts / Open Products Facts JSONL dumps (ODbL 1.0) and writes
reference_catalog.sqlite3 next to mobile_server.py. This file is a lookup aid
only: it is never imported into the sale database (drugs), has no price column
and nothing in it can be added to an invoice.

    py catalog/build_reference_catalog.py            # downloads the dumps
    py catalog/build_reference_catalog.py a.jsonl.gz # use local dump(s)

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
PAGE = {"Open Beauty Facts": "https://world.openbeautyfacts.org/product/",
        "Open Products Facts": "https://world.openproductsfacts.org/product/"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS ref_products(
  source TEXT NOT NULL, source_id TEXT NOT NULL, barcode TEXT DEFAULT '',
  name TEXT NOT NULL, brand TEXT DEFAULT '', category TEXT DEFAULT '',
  quantity TEXT DEFAULT '', countries TEXT DEFAULT '', url TEXT DEFAULT '',
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
                   _s(p.get("quantity"), 40), countries, PAGE[source] + sid)


def build(paths):
    tmp = OUT + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    total = 0
    for source, path in paths:
        con.executemany("INSERT OR IGNORE INTO ref_products VALUES (?,?,?,?,?,?,?,?,?)",
                        rows_from(path, source))
        con.commit()
    total = con.execute("SELECT COUNT(*) FROM ref_products").fetchone()[0]
    con.close()
    os.replace(tmp, OUT)
    return total


def main(argv):
    if argv:
        paths = [("Open Products Facts" if "products" in os.path.basename(a) and "openproducts" in os.path.basename(a)
                  else "Open Beauty Facts", a) for a in argv]
    else:
        paths = []
        for source, url in DUMPS.items():
            dest = os.path.join(BASE, "catalog", os.path.basename(url))
            print("downloading", url)
            urllib.request.urlretrieve(url, dest)
            paths.append((source, dest))
    print("reference rows:", build(paths), "->", OUT)


if __name__ == "__main__":
    main(sys.argv[1:])
