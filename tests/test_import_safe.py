import csv, glob, os, tempfile, unittest
from database import DB


class ImportSafe(unittest.TestCase):
    def test_reimport_keeps_prices_and_backs_up(self):
        d = tempfile.mkdtemp()
        db = DB(path=os.path.join(d, "t.db"))
        csvp = os.path.join(d, "c.csv")
        def write(rows):
            with open(csvp, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=["trade_en", "trade_ar", "scientific", "company", "form", "strength", "category",
                                                  "strips_per_box", "tablets_per_strip", "buy_price", "sell_price", "min_stock", "barcode"])
                w.writeheader(); w.writerows(rows)
        row = dict(trade_en="light vel cream 50 gm", trade_ar="x", scientific="", company="co", form="Cream", strength="50 g", category="",
                   strips_per_box=1, tablets_per_strip=1, buy_price=0, sell_price=149, min_stock=5, barcode="")
        write([row])
        self.assertEqual(db.import_drugs_csv(csvp), (1, 0))
        did = db.conn.execute("SELECT id FROM drugs").fetchone()["id"]
        db.conn.execute("UPDATE drugs SET buy_price=88, sell_price=120, min_stock=9, strips_per_box=3 WHERE id=?", (did,))
        db.conn.commit()
        write([dict(row, sell_price=149, trade_ar="new arabic")])
        self.assertEqual(db.import_drugs_csv(csvp), (0, 1))
        r = db.conn.execute("SELECT * FROM drugs WHERE id=?", (did,)).fetchone()
        self.assertEqual((r["buy_price"], r["sell_price"], r["min_stock"], r["strips_per_box"]), (88, 120, 9, 3))
        self.assertEqual(r["trade_ar"], "new arabic")                      # descriptive text still refreshed
        self.assertTrue(glob.glob(os.path.join(d, "backups", "*_pre_import.db")))
        db.conn.execute("UPDATE drugs SET sell_price=0 WHERE id=?", (did,)); db.conn.commit()
        db.import_drugs_csv(csvp)
        self.assertEqual(db.conn.execute("SELECT sell_price FROM drugs WHERE id=?", (did,)).fetchone()[0], 149)  # missing price filled
        self.assertEqual(len(db.conn.execute("SELECT 1 FROM drugs").fetchall()), 1)

    def test_bad_file_imports_nothing(self):
        d = tempfile.mkdtemp(); db = DB(path=os.path.join(d, "t.db")); p = os.path.join(d, "b.csv")
        open(p, "w", encoding="utf-8").write("trade_en,sell_price\nok,5\n,7\n")
        with self.assertRaises(ValueError):
            db.import_drugs_csv(p)
        self.assertEqual(db.conn.execute("SELECT count(*) FROM drugs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
