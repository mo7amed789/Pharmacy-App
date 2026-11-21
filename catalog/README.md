# Egyptian Drug Catalog — 27,617 products

Import-ready drug catalog for Pharmacy Enterprise, built from public
Egyptian market data (refreshed late October 2026).

## What's here

| File | What it is |
| --- | --- |
| `egyptian_drugs_catalog.csv` | 27,617 products in the exact format of Settings -> Import CSV (same columns as `drugs_template.csv`). |
| `build_catalog.py` | The script that produced the CSV from the source database, so the catalog can be regenerated when prices change. |

## How to use

1. Open the app, log in as admin.
2. Settings -> Import CSV -> choose `egyptian_drugs_catalog.csv`.
3. The whole file imports in one transaction: 27,617 drugs, 10,435
   barcodes. Verified against the app's own importer.

Every product starts with zero stock. Enter real stock through a
purchase invoice (batch + expiry + quantity) as usual.

## Column mapping (source -> app)

| App column | Source |
| --- | --- |
| `trade_en` / `trade_ar` | Full trade name (kept as-is, including pack size text). |
| `scientific` | Active ingredient(s). |
| `company` | Manufacturer. |
| `form` | Parsed from the trade name (Tablets, Syrup, ...). Best effort. |
| `strength` | Parsed from the trade name (e.g. `500 mg`). Best effort; ~5,800 rows have no machine-readable strength. |
| `category` | Source category (e.g. cold products). |
| `strips_per_box` / `tablets_per_strip` | Default 1 x 1 (selling unit = pack). Edit per drug when entering stock. |
| `sell_price` | Current official price in EGP (Oct 2026). |
| `buy_price` | 0. Source old prices are previous SELL prices, not purchase prices; real buy prices come from your supplier invoices. |
| `min_stock` | 5 (app default). |
| `barcode` | 10,435 unique, digits-only barcodes. Duplicate or missing barcodes were dropped (the app rejects duplicates). |

## Caveats

- Prices are official Egyptian prices as of late October 2026. They
  change with EDA repricing decisions; verify against the Egyptian Drug
  Authority (edaegypt.gov.eg) for official use.
- One product (Zolgensma, 34M EGP) exceeds the app's 10M EGP price
  ceiling; it is clamped to 10,000,000.
- Importing again later UPDATES existing products (matched on trade
  name + strength) instead of duplicating them, so re-imports are safe
  for price refreshes.

## Sources

- github.com/mahmoudfalous/eg-drugs (names, prices, barcodes; refreshed Oct 30, 2026)
- github.com/karem505/egyptian-drug-database (CC0; route / therapeutic class; refreshed Oct 24, 2026)
