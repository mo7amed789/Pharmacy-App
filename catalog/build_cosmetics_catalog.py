#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a Pharmacy-Enterprise-import-ready COSMETICS catalog from the
scraped Egyptian beauty-store snapshot (27K+ products, 10 stores).

Usage:
    py catalog/build_cosmetics_catalog.py
        Converts catalog/egyptian_cosmetics_source.csv and writes
        catalog/egyptian_cosmetics_catalog.csv next to it.
    py catalog/build_cosmetics_catalog.py SOURCE.csv [OUT.csv]
        Convert a different snapshot instead.

Run catalog/build_catalog.py first (or let this script run it): the
drug catalog's barcodes and (trade name, strength) keys are loaded so
a cosmetic product can never steal a drug's barcode or silently
overwrite a drug row on import.

Output: same EXACT columns as the drug catalog / drugs_template.csv
        (see database.py import_drugs_csv).

Decisions (documented in catalog/README.md):
- sell_price  = current retail price (price_egp). These are retail
  e-shop prices, NOT official prices like the drug catalog.
- buy_price   = 0. old_price_egp is a pre-discount SELL price, not a
  purchase price; real buy prices come from purchase invoices.
- strength    = size/volume (e.g. "200 ml"), because the importer
  keys updates on (trade_en, strength): size is what tells two
  variants of the same product apart. Parsed from the trade name
  when the size field is empty.
- form        = parsed from the trade name, then the category
  (Cream, Lotion, Shampoo, ...). Best effort.
- trade_en    = English trade name. 780 alzad-cosmetics.com products
  have an Arabic name only; for those the Arabic name is used in
  BOTH trade_en and trade_ar so the product stays searchable.
- barcode     = real EANs from the WooCommerce stores. A barcode that
  collides with the drug catalog (or an earlier cosmetic row) is
  dropped, because the app rejects duplicate barcodes.
"""
import csv, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_catalog  # reuse parse_form / parse_strength / clean_barcode

SIZE_NORM_RE = re.compile(r"(\d)\s*(ml|gm|g|l|kg|oz|pcs|pieces?)\b", re.IGNORECASE)
LETTERS_RE = re.compile(r"[A-Za-z\u0600-\u06FF]")

def has_letters(s):
    return bool(LETTERS_RE.search(s or ""))

def norm_size(raw):
    s = re.sub(r"\s+", " ", (raw or "").strip())
    s = SIZE_NORM_RE.sub(lambda m: m.group(1) + " " + m.group(2).lower(), s)
    return s

def ensure_drugs_catalog(here):
    """Make sure the drug catalog exists; build it if missing."""
    drugs_out = os.path.join(here, "egyptian_drugs_catalog.csv")
    if not os.path.exists(drugs_out):
        src = os.path.join(here, "eg_drugs_source.csv")
        if not os.path.exists(src):
            print("Downloading latest drug dataset ...")
            import urllib.request
            urllib.request.urlretrieve(build_catalog.SOURCE_URL, src)
            print("saved:", src)
        build_catalog.main(src, drugs_out)
    return drugs_out

def load_drug_keys_and_barcodes(drugs_out):
    keys, barcodes = set(), set()
    with open(drugs_out, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            keys.add(((r["trade_en"] or "").lower(), (r["strength"] or "").lower()))
            bc = (r["barcode"] or "").strip()
            if bc:
                barcodes.add(bc)
    return keys, barcodes

def main(src, dst):
    here = os.path.dirname(os.path.abspath(__file__))
    drug_keys, drug_barcodes = load_drug_keys_and_barcodes(ensure_drugs_catalog(here))

    with open(src, newline="", encoding="utf-8-sig") as f:
        raw_rows = list(csv.DictReader(f))

    out, seen_keys, seen_barcodes = [], set(), set()
    stats = {"rows_in": len(raw_rows), "no_name": 0, "arabic_only_name": 0,
             "no_price": 0, "no_barcode": 0, "dup_barcode": 0,
             "drug_barcode_collision": 0, "key_collisions": 0,
             "drug_key_collision": 0, "no_size": 0}
    for r in raw_rows:
        name_en = (r.get("trade_name_en") or "").strip()
        name_ar = (r.get("trade_name_ar") or "").strip()
        if not has_letters(name_en):
            # 780 alzad rows have no English name and 1,215 more have a
            # mangled one ("( ) 100"); all carry a proper Arabic name.
            if not has_letters(name_ar):
                stats["no_name"] += 1
                continue
            name_en = name_ar  # Arabic-only product: searchable under its AR name
            stats["arabic_only_name"] += 1

        strength = norm_size(r.get("size_volume")) or build_catalog.parse_strength(name_en)
        if not strength:
            stats["no_size"] += 1
        form = build_catalog.parse_form(name_en) or build_catalog.parse_form(r.get("category"))

        # Import updates on (trade_en, strength): disambiguate so no row
        # silently overwrites another cosmetic OR a drug.
        key = (name_en.lower(), strength.lower())
        if key in seen_keys or key in drug_keys:
            stats["key_collisions"] += 1
            if key in drug_keys:
                stats["drug_key_collision"] += 1
            for extra in (form, (r.get("brand") or "").strip(), "cosmetic"):
                if not extra:
                    continue
                strength = ("%s | %s" % (strength, extra)).strip(" |")
                key = (name_en.lower(), strength.lower())
                if key not in seen_keys and key not in drug_keys:
                    break
            n = 2
            while key in seen_keys or key in drug_keys:
                strength = re.sub(r"( \| \d+)?$", " | %d" % n, strength)
                key = (name_en.lower(), strength.lower())
                n += 1
        seen_keys.add(key)

        try:
            sell = round(float(r.get("price_egp") or 0), 2)
        except ValueError:
            sell = 0.0
        if not sell:
            stats["no_price"] += 1

        bc = build_catalog.clean_barcode(r.get("barcode"))
        if bc:
            if bc in drug_barcodes:
                stats["drug_barcode_collision"] += 1
                bc = ""
            elif bc in seen_barcodes:
                stats["dup_barcode"] += 1
                bc = ""
            else:
                seen_barcodes.add(bc)
        else:
            stats["no_barcode"] += 1

        out.append({
            "trade_en": name_en,
            "trade_ar": name_ar,
            "scientific": "",
            "company": (r.get("brand") or "").strip(),
            "form": form,
            "strength": strength,
            "category": (r.get("category") or "").strip(),
            "strips_per_box": 1,
            "tablets_per_strip": 1,
            "buy_price": 0,
            "sell_price": sell,
            "min_stock": 5,
            "barcode": bc,
        })

    cols = ["trade_en", "trade_ar", "scientific", "company", "form",
            "strength", "category", "strips_per_box", "tablets_per_strip",
            "buy_price", "sell_price", "min_stock", "barcode"]
    with open(dst, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    stats["rows_out"] = len(out)
    for k, v in stats.items():
        print("%s: %s" % (k, v))

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    if len(sys.argv) >= 2:
        src_path = sys.argv[1]
        dst_path = sys.argv[2] if len(sys.argv) >= 3 else os.path.join(
            here, "egyptian_cosmetics_catalog.csv")
    else:
        src_path = os.path.join(here, "egyptian_cosmetics_source.csv")
        dst_path = os.path.join(here, "egyptian_cosmetics_catalog.csv")
    main(src_path, dst_path)
    print("wrote:", dst_path)
