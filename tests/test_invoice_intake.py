# -*- coding: utf-8 -*-
"""Invoice intake parser/matcher. Run: py tests/test_invoice_intake.py"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import DB
import invoice_intake as ii

TEXT = """ABC Pharma Distribution
Invoice No: INV-2291
Panadol 500 mg  10  25.50  255.00  03/2028  Batch: A123
Augmentin 1g    5   110     550     2028-01-31 Lot B77
Nizapex  3  40  100  06/2027
Mystery drugx  2 10 20 05/2028
Total 925.00
"""


class T(unittest.TestCase):
    def setUp(self):
        self.db = DB(path=os.path.join(tempfile.mkdtemp(), "t.db"))
        for n in ("Panadol 500mg", "Augmentin 1g", "Nizapex", "Panadol Extra"):
            self.db.conn.execute("INSERT INTO drugs (trade_en,created_at) VALUES (?,?)", (n, ""))
        self.db.conn.commit()

    def lines(self, text):
        return ii.annotate(self.db, ii.parse_invoice_text(text))["lines"]

    def test_parse(self):
        p = ii.parse_invoice_text(TEXT)
        self.assertEqual(p["invoice_no"], "INV-2291")
        L = p["lines"]
        self.assertEqual(len(L), 4)
        self.assertEqual((L[0]["qty"], L[0]["price"], L[0]["total"]), (10, 25.5, 255.0))
        self.assertEqual(L[0]["batch"], "A123")
        self.assertEqual(L[1]["batch"], "B77")
        self.assertEqual(L[1]["expiry"], "2028-01-31")
        self.assertTrue(any("≠" in f for f in L[2]["flags"]))

    def test_month_year_never_gets_a_day(self):
        L = ii.parse_invoice_text("Panadol 500 mg 10 25.50 255.00 03/2028")["lines"]
        self.assertEqual(L[0]["expiry"], "")
        self.assertEqual(L[0]["expiry_month"], "2028-03")
        self.assertTrue(any("شهر/سنة" in f for f in L[0]["flags"]))

    def test_ambiguous_date(self):
        L = ii.parse_invoice_text("Panadol 500 mg 10 25.50 255.00 04/05/2028")["lines"]
        self.assertEqual(L[0]["expiry"], "")
        self.assertTrue(any("ملتبس" in f for f in L[0]["flags"]))
        L = ii.parse_invoice_text("Panadol 500 mg 10 25.50 255.00 25/05/2028")["lines"]
        self.assertEqual(L[0]["expiry"], "2028-05-25")
        L = ii.parse_invoice_text("Panadol 500 mg 10 25.50 255.00 31/02/2028")["lines"]
        self.assertEqual(L[0]["expiry"], "")

    def test_arabic_digits(self):
        L = ii.parse_invoice_text("بنادول ٥٠٠ مجم ١٠ ٢٥٫٥ ٢٥٥ ٢٠٢٨-٠٣-١٥")["lines"]
        self.assertEqual((L[0]["qty"], L[0]["price"], L[0]["expiry"]), (10, 25.5, "2028-03-15"))

    def test_fuzzy_never_auto_accepts(self):
        for l in self.lines(TEXT):
            self.assertIsNone(l["drug"])  # no barcode -> suggestion only
        L = self.lines(TEXT)
        self.assertEqual(L[1]["suggestion"]["trade_en"], "Augmentin 1g")
        ready, left = ii.to_purchase_lines(L)
        self.assertEqual(ready, [])

    def test_lookalike_strength_warned(self):
        self.db.conn.execute("INSERT INTO drugs (trade_en,created_at) VALUES ('Panadol 1000mg','')")
        self.db.conn.commit()
        L = self.lines("Panadol 1000 mg 2 30 60 01/01/2029")
        self.assertIsNotNone(L[0]["suggestion"])
        self.assertIsNone(L[0]["drug"])
        L = self.lines("Panadol 250 mg 2 30 60 01/01/2029")
        self.assertTrue(any("التركيز" in f for f in L[0]["flags"]))

    def test_barcode_exact_is_verified(self):
        did = self.db.conn.execute("SELECT id FROM drugs WHERE trade_en='Nizapex'").fetchone()["id"]
        self.db.conn.execute("INSERT INTO barcodes (barcode, drug_id, pack_level) VALUES ('6221234567890',?,'box')", (did,))
        self.db.conn.commit()
        L = self.lines("Nizapex 6221234567890 3 40 120 15/06/2029")
        self.assertTrue(L[0]["verified"])
        self.assertEqual(L[0]["drug"]["id"], did)
        self.assertEqual((L[0]["qty"], L[0]["price"]), (3, 40))

    def confirmed(self, text):
        L = self.lines(text)
        for l in L:
            l["drug"] = l["suggestion"] or l["drug"]  # what a user click does
        return L

    def test_ready_rules(self):
        L = self.confirmed("Augmentin 1g 5 110 550 31/01/2030\n"
                           "Nizapex 3 40 100 15/06/2029\n"       # total mismatch
                           "Nizapex 2.5 40 100 15/06/2029\n"     # fractional boxes
                           "Panadol 500 mg 1 10 10 01/2030\n"    # month-only
                           "Panadol 500 mg 1 10 10 15/06/2001\n")  # expired
        ready, left = ii.to_purchase_lines(L)
        self.assertEqual([r["drug"]["trade_en"] for r in ready], ["Augmentin 1g"])
        self.assertEqual(len(left), 4)
        L[1]["numbers_confirmed"] = True
        ready, _ = ii.to_purchase_lines(L)
        self.assertEqual(len(ready), 2)

    def test_repeat_import_not_doubled(self):
        L = self.confirmed("Augmentin 1g 5 110 550 31/01/2030 Batch X1")
        ready, _ = ii.to_purchase_lines(L)
        self.assertEqual(len(ready), 1)
        ready2, left2 = ii.to_purchase_lines(self.confirmed("Augmentin 1g 5 110 550 31/01/2030 Batch X1"), ready)
        self.assertEqual(ready2, [])
        self.assertEqual(len(left2), 1)

    def test_save_path_keeps_sell_price_and_units(self):
        self.db.conn.execute("UPDATE drugs SET sell_price=99, strips_per_box=3, tablets_per_strip=10 WHERE trade_en='Augmentin 1g'")
        self.db.conn.commit()
        L = self.confirmed("Augmentin 1g 5 110 550 31/01/2030 Batch X1")
        ready, _ = ii.to_purchase_lines(L)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) c FROM purchases").fetchone()["c"], 0)
        sid = self.db.add_supplier("Test Sup")
        self.db.record_purchase(sid, "INV-1", ready, user="t")
        d = self.db.conn.execute("SELECT * FROM drugs WHERE trade_en='Augmentin 1g'").fetchone()
        self.assertEqual(d["sell_price"], 99)       # untouched
        self.assertEqual(d["buy_price"], 110)       # cost updated per existing app rule
        b = self.db.conn.execute("SELECT * FROM batches WHERE batch_no='X1'").fetchone()
        self.assertEqual(b["qty_units"], 150)       # 5 boxes x 30
        self.assertEqual(b["expiry"], "2030-01-31")
        self.assertTrue(ii.known_invoice(self.db, "INV-1"))
        self.assertFalse(ii.known_invoice(self.db, "INV-2"))

    def test_ocr_unavailable_clean_error(self):
        with self.assertRaises(ii.OcrUnavailable):
            ii.ocr_image("/nonexistent.png")


if __name__ == "__main__":
    unittest.main()
