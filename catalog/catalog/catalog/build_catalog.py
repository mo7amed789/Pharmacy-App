#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a Pharmacy-Enterprise-import-ready drug catalog from the
27,617-item Egyptian pharmacy database.

Input : Egypt_Pharmacy_Database CSV (columns: id, trade_name_en,
        trade_name_ar, active_ingredients, manufacturer, price_egp,
        old_price_egp, barcode, category, route, units_in_pack, uses_ar)
Output: CSV with EXACTLY the columns Pharmacy Enterprise's
        Settings -> Import CSV expects (see drugs_template.csv /
        database.py import_drugs_csv):
        trade_en, trade_ar, scientific, company, form, strength,
        category, strips_per_box, tablets_per_strip, buy_price,
        sell_price, min_stock, barcode

Decisions (documented in catalog/README.md):
- sell_price  = current official price (price_egp).
- buy_price   = 0. Old prices are previous SELL prices, not purchase
  prices; real buy prices come from the pharmacy's purchase invoices.
- form/strength are parsed from the trade name on a best-effort
  basis; the full original name is always kept in trade_en.
- Pack structure defaults to 1 strip x 1 tablet (selling unit = pack);
  the owner edits pack structure per drug when entering stock.
- Only unique, digits-only barcodes (>= 8 digits) are kept; first
  occurrence wins, because the app rejects duplicate barcodes.
"""
import csv, re, sys

STRENGTH_RE = re.compile(
    r"(\d+(?:\.\d+)?(?:\s*[+/]\s*\d+(?:\.\d+)?)*)\s*"
    r"(mg/ml|mg/5\s?ml|mcg/ml|g/100\s?ml|mg/g|mcg|mg|gm|ml|g|iu|i\.u\.|%|units?|mmol|meq)\b",
    re.IGNORECASE)

FORMS = [
    (r"\bf\.?\s?c\.?\s*tabs?\b|\bfilm\s*coated\b|\btabs?\b|\btablets?\b", "Tablets"),
    (r"\bcaps?\b|\bcapsules?\b", "Capsules"),
    (r"\bsyrup\b", "Syrup"),
    (r"\bsusp(?:ension)?\b", "Suspension"),
    (r"\bcream\b", "Cream"),
    (r"\boint(?:ment)?\b", "Ointment"),
    (r"\bgel\b|\bjel\b", "Gel"),
    (r"\blotion\b", "Lotion"),
    (r"\bdrops?\b", "Drops"),
    (r"\bspray\b", "Spray"),
    (r"\binhaler\b", "Inhaler"),
    (r"\bamps?\b|\bampoules?\b", "Ampoules"),
    (r"\bvial\b", "Vial"),
    (r"\bsupp(?:ositories|ository)?\b", "Suppositories"),
    (r"\bsachets?\b", "Sachets"),
    (r"\bpatch\b", "Patch"),
    (r"\bshampoo\b", "Shampoo"),
    (r"\blozenges?\b", "Lozenges"),
    (r"\binj(?:ection)?\b", "Injection"),
    (r"\binfusion\b", "Infusion"),
    (r"\bpowder\b", "Powder"),
    (r"\bmouth\s?wash\b", "Mouthwash"),
    (r"\bfoam\b", "Foam"),
    (r"\bemulsion\b", "Emulsion"),
    (r"\bso?ln?\b|\bsolution\b", "Solution"),
    (r"\beff(?:ervescent)?\b", "Effervescent"),
]
FORM_RES = [(re.compile(p, re.IGNORECASE), label) for p, label in FORMS]

def parse_strength(name):
    m = STRENGTH_RE.search(name or "")
    if not m:
        return ""
    return ("%s %s" % (m.group(1).strip(), m.group(2).lower())).replace("gm", "g")

def parse_form(name):
    best_pos, best_label = None, ""
    for rx, label in FORM_RES:
        m = rx.search(name or "")
        if m and (best_pos is None or m.start() < best_pos):
            best_pos, best_label = m.start(), label
    return best_label

def clean_barcode(raw):
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return digits if len(digits) >= 8 else ""

def main(src, dst):
    with open(src, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out, seen_keys, seen_barcodes = [], set(), set()
    stats = {"rows_in": len(rows), "no_price": 0, "no_barcode": 0,
             "dup_barcode": 0, "key_collisions": 0, "no_strength": 0, "clamped_price": 0}
    for r in rows:
        name = (r.get("trade_name_en") or "").strip()
        if not name:
            continue
        form = parse_form(name)
        strength = parse_strength(name)
        if not strength:
            stats["no_strength"] += 1
        key = (name.lower(), strength.lower())
        if key in seen_keys:
            # Import updates on (trade_en, strength): disambiguate so no
            # row silently overwrites another.
            stats["key_collisions"] += 1
            strength = ("%s | %s" % (strength, form)).strip(" |")
            key = (name.lower(), strength.lower())
            if key in seen_keys:
                strength = ("%s | %s" % (strength, (r.get("manufacturer") or "").strip())).strip(" |")
                key = (name.lower(), strength.lower())
        seen_keys.add(key)
        try:
            sell = round(float(r.get("price_egp") or 0), 2)
        except ValueError:
            sell = 0.0
        if sell > 1e7:
            # App validation ceiling (database.py _validate_drug_fields).
            # Only Zolgensma (34M EGP) hits this; see catalog/README.md.
            sell = 10000000.0
            stats["clamped_price"] += 1
        if not sell:
            stats["no_price"] += 1
        bc = clean_barcode(r.get("barcode"))
        if bc:
            if bc in seen_barcodes:
                stats["dup_barcode"] += 1
                bc = ""
            else:
                seen_barcodes.add(bc)
        else:
            stats["no_barcode"] += 1
        out.append({
            "trade_en": name,
            "trade_ar": (r.get("trade_name_ar") or "").strip(),
            "scientific": (r.get("active_ingredients") or "").strip(),
            "company": (r.get("manufacturer") or "").strip(),
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
    main(sys.argv[1], sys.argv[2])
