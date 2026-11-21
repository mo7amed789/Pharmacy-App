# Egyptian Product Catalogs — 27,617 drugs + 27,623 cosmetics

Import-ready product catalogs for Pharmacy Enterprise: the public
Egyptian medicines dataset, plus a live-scraped Egyptian cosmetics
catalog.

## What's here

| File | What it is |
| --- | --- |
| `build_catalog.py` | Builds the import-ready drug catalog. Run it once — it downloads the latest dataset itself and writes `egyptian_drugs_catalog.csv` next to it. |
| `build_cosmetics_catalog.py` | Builds the import-ready cosmetics catalog from `egyptian_cosmetics_source.csv` and writes `egyptian_cosmetics_catalog.csv`. Runs the drug builder first if its output is missing, so barcode/key collisions with drugs are avoided. |
| `egyptian_cosmetics_source.csv` | Raw cosmetics snapshot: 27,623 products scraped live from 10 Egyptian online beauty stores on Nov 21, 2026 (sourcebeauty.com, eg.lolabeauty.com, blush2brush.com, 10point8.com, alzad-cosmetics.com, belamoon.com, miolora.com, skinpopeg.com, zohrashop.com, souqtaj.com). |
| `egyptian_drugs_catalog.csv` | (Generated — not committed.) 27,617 products in the exact format of Settings -> Import CSV (same columns as `drugs_template.csv`). |
| `egyptian_cosmetics_catalog.csv` | (Generated — not committed.) 27,623 cosmetics in the same import format. |

## How to use

1. Generate the drug catalog (downloads ~7 MB once, needs internet):

       py catalog/build_catalog.py

2. Generate the cosmetics catalog (offline, uses the committed snapshot):

       py catalog/build_cosmetics_catalog.py

3. Open the app, log in as admin.
4. Settings -> Import CSV -> choose `catalog/egyptian_drugs_catalog.csv`.
5. Settings -> Import CSV -> choose `catalog/egyptian_cosmetics_catalog.csv`.
6. Each file imports in one transaction: 27,617 drugs + 27,623
   cosmetics = 55,240 products, ~16,300 barcodes. Verified against the
   app's own importer (`import_drugs_csv`), including re-imports
   (second import = pure updates, no duplicates) and a drugs-first
   then cosmetics order (no cosmetic row overwrites a drug).

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
| `sell_price` | Current official price in EGP. |
| `buy_price` | 0. Source old prices are previous SELL prices, not purchase prices; real buy prices come from your supplier invoices. |
| `min_stock` | 5 (app default). |
| `barcode` | ~10,500 unique, digits-only barcodes. Duplicate or missing barcodes are dropped (the app rejects duplicates). |

## Cosmetics column mapping (source -> app)

Same columns as the drug catalog, with these source-specific choices:

| App column | Source |
| --- | --- |
| `trade_en` / `trade_ar` | Trade name. 2,047 products have no usable English name (Arabic-only stores); for those the Arabic name is used in BOTH columns so the product stays searchable. |
| `scientific` | Empty — cosmetics have no active ingredient. |
| `company` | Brand. |
| `form` | Parsed from the trade name, then the category (Cream, Lotion, Shampoo, ...). Best effort. |
| `strength` | Size/volume (e.g. `200 ml`) — the importer keys updates on (trade name, strength), and size is what tells two variants of the same product apart. Parsed from the name when the size field is empty; ~18,300 rows have no machine-readable size. |
| `category` | Store category (e.g. Hair Care, Skin Care). |
| `sell_price` | Current RETAIL e-shop price in EGP. |
| `buy_price` | 0. `old_price_egp` is a pre-discount SELL price, not a purchase price. |
| `barcode` | ~5,800 real EANs (only the WooCommerce stores publish barcodes; the Shopify stores don't). 172 barcodes that collided with the drug catalog were dropped — the app rejects duplicate barcodes and a shared code would point a scan at the wrong product. |

## Caveats

- Drug prices are official Egyptian prices as of the dataset's last refresh
  (late October 2026). They change with EDA repricing decisions; verify
  against the Egyptian Drug Authority (edaegypt.gov.eg) for official
  use. Re-run `build_catalog.py` to pull fresher data any time.
- Cosmetics prices are RETAIL consumer prices from online stores,
  scraped Nov 21, 2026 — a different thing from the drugs' official
  pricing, and they move with store promotions. Replace
  `egyptian_cosmetics_source.csv` with a fresher snapshot and re-run
  `build_cosmetics_catalog.py` to refresh.
- One product (Zolgensma, 34M EGP) exceeds the app's 10M EGP price
  ceiling; it is clamped to 10,000,000.
- Importing again later UPDATES existing products (matched on trade
  name + strength) instead of duplicating them, so re-imports are safe
  for price refreshes. Import drugs BEFORE cosmetics: the cosmetics
  builder disambiguates against the drug catalog, and that guarantee
  only holds if the drug catalog was built from the same source data.

## Sources

- github.com/mahmoudfalous/eg-drugs (drug names EN/AR, active ingredients,
  manufacturers, prices, barcodes, categories; refreshed Oct 30, 2026)
- Cosmetics: live scrape of 10 Egyptian online beauty stores, Nov 21,
  2026 (store list above; names EN/AR, brands, sizes, categories,
  prices, barcodes where published, stock status, product URLs).

## Personal-care supplement (v6.27)

`personal_care_cosmetics.csv` adds 77 source-checked listings to the existing
catalog. It covers shampoo, oils, soap, oral care, deodorants, shaving,
creams, gels, baby care and related items. `personal_care_sources.csv`
records the listing sources and check date. These are not all products
sold in Egypt. The existing catalogs already include many more products,
including eye/nasal/oral drops in the drug catalog.

- Import using Settings -> Import CSV, or pull the cloud catalog after its update.
- Arabic search labels include the product type and, where supplied, a
  transliterated brand. The original English product name stays visible.
- Prices are observed retailer listing prices, not official medicine tariffs
  or purchase costs. They can vary by branch, promotion and date. Review
  selling prices before use. No manufacturer, barcode or purchase price is
  invented. The company field contains the listed brand, not a verified
  manufacturer.
- Existing cloud rows are not overwritten by the supplement. Importing the
  CSV locally uses the app's usual matching by trade name and size.
- New products have no stock. Enter real quantities through purchase invoices.
- Whole-piece forms such as oils, soap, deodorant and toothpaste can only
  be sold as a whole pack, not a strip or pill. Tablet/capsule behavior stays
  unchanged.

## Open reference research (v6.30)

`open_reference_batch2_provenance.csv` contains two source-checked proposals, NOT an import file. Both remain `import_ready=False`; no live rows were inserted by this update. Preserve identifiers as text and keep this provenance with any later authorized data export.

Contains data from Open Beauty Facts and Open Products Facts, available under the Open Database License (ODbL 1.0). Individual contents: DbCL. No product images included. Source and license links, distribution obligations, and the boundary excluding private sales/customer/stock records are documented in [v6.30](../docs/changelog/README_AR_V6.30.md).
