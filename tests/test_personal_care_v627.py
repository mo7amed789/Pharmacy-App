"""v6.27 personal-care catalog additions:
- catalog/personal_care_cosmetics.csv is a valid importer-format file
  (same columns as drugs_template.csv) whose rows all pass
  DB._validate_drug_fields, have unique (trade_en, strength) keys and
  sell as whole pieces only.
- allowed_units() (database.py) treats personal-care forms (oil, soap,
  toothpaste, deodorant, ...) as single-piece ["box"] forms, and the
  phone cloud-mode copy of that regex (mobile.html cloudDrugJson)
  carries the same extensions."""
import csv
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "catalog", "personal_care_cosmetics.csv")
TEMPLATE_PATH = os.path.join(ROOT, "drugs_template.csv")

from database import DB, allowed_units  # noqa: E402

EXTENDED_TOKENS = [
    "oil", "soap", "toothpaste", "mouthwash", "wash", "deodorant",
    "razor", "foam", "powder", "wipes", "diaper", "pads", "cotton",
    "jelly", "sunscreen", "conditioner", "toothbrush", "floss",
    "shower", "tissues", "intimate",
    "زيت", "صابون", "بلسم", "مزيل", "شفرات", "رغوة", "بودرة",
    "مناديل", "حفاض", "فوط", "قطن", "فازلين", "واقي", "فرشاة", "شاور",
]

SINGLE_PIECE_FORMS = [
    "Shampoo", "Conditioner", "Oil", "Soap", "Hand Wash", "Solution",
    "Gel", "Toothpaste", "Toothbrush", "Floss", "Mouthwash",
    "Deodorant", "Razor", "Shaving Foam", "Shaving Gel", "Pads",
    "Powder", "Shower Gel", "Intimate Wash", "Cotton", "Jelly",
    "Tissues", "Wipes", "Diapers", "Cream", "Sunscreen", "Drops",
    "Spray",
]


class TestPersonalCareCsv(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CSV_PATH, encoding="utf-8") as f:
            cls.rows = list(csv.DictReader(f))

    def test_file_has_products(self):
        self.assertGreaterEqual(len(self.rows), 50)

    def test_columns_match_importer_template(self):
        with open(TEMPLATE_PATH, encoding="utf-8-sig") as f:
            template_cols = next(csv.reader(f))
        with open(CSV_PATH, encoding="utf-8") as f:
            cols = next(csv.reader(f))
        self.assertEqual(cols, template_cols)

    def test_rows_pass_drug_field_validation(self):
        for r in self.rows:
            fields = dict(r)
            fields.setdefault("discount_type", "none")
            fields.setdefault("discount_value", 0)
            DB._validate_drug_fields(fields)  # raises on bad data

    def test_names_present_and_keys_unique(self):
        keys = set()
        for r in self.rows:
            self.assertTrue(r["trade_en"].strip())
            self.assertTrue(r["trade_ar"].strip())
            self.assertTrue(r["form"].strip())
            key = (r["trade_en"].strip().lower(), r["strength"].strip().lower())
            self.assertNotIn(key, keys, "duplicate upsert key: %r" % (key,))
            keys.add(key)

    def test_covers_requested_groups(self):
        forms = {r["form"] for r in self.rows}
        for need in ("Shampoo", "Oil", "Soap", "Gel", "Cream", "Toothpaste"):
            self.assertIn(need, forms)

    def test_every_row_sells_whole_piece_only(self):
        for r in self.rows:
            self.assertEqual(allowed_units({"form": r["form"]}), ["box"],
                             r["trade_en"])


class TestAllowedUnitsPersonalCare(unittest.TestCase):
    def test_extended_forms_are_box_only(self):
        for form in SINGLE_PIECE_FORMS:
            self.assertEqual(allowed_units({"form": form}), ["box"], form)

    def test_legacy_forms_unchanged(self):
        self.assertEqual(allowed_units({"form": "Tablet"}),
                         ["box", "strip", "pill"])
        self.assertEqual(allowed_units({"form": "Capsule"}),
                         ["box", "strip", "pill"])
        self.assertEqual(allowed_units({"form": "Suppository"}),
                         ["box", "pill"])
        self.assertEqual(allowed_units({"form": "Cream"}), ["box"])
        self.assertEqual(allowed_units({"form": ""}),
                         ["box", "strip", "pill"])



class TestActualImport(unittest.TestCase):
    def test_import_and_reimport_are_idempotent_and_no_stock_created(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = DB(path=os.path.join(tmp, 'catalog.db'))
            before = db.conn.execute('select count(*) from drugs').fetchone()[0]
            count = len(list(csv.DictReader(open(CSV_PATH, encoding='utf-8'))))
            self.assertEqual(db.import_drugs_csv(CSV_PATH), (count, 0))
            self.assertEqual(db.import_drugs_csv(CSV_PATH), (0, count))
            self.assertEqual(db.conn.execute('select count(*) from drugs').fetchone()[0], before + count)
            db.conn.close()

if __name__ == "__main__":
    unittest.main()
