import os, tempfile, unittest
from database import DB


class SearchSpacing(unittest.TestCase):
    def test_spaces_ignored_both_ways(self):
        db = DB(path=os.path.join(tempfile.mkdtemp(), "t.db"))
        db.conn.execute("INSERT INTO drugs (trade_en,trade_ar,sell_price,active) VALUES (?,?,?,1)",
                        ("light vel cream 50 gm", "\u0644\u0627\u064a\u062a \u0641\u0644 \u0643\u0631\u064a\u0645 50 \u062c\u0645", 149))
        db.conn.commit()
        for q in ("light vel", "lightvel", "Lightvel Cream", "light  vel", "\u0644\u0627\u064a\u062a\u0641\u0644", "\u0644\u0627\u064a\u062a \u0641\u0644"):
            self.assertEqual(len(db.search_drugs(q)), 1, q)
        self.assertEqual(len(db.search_drugs("zzz")), 0)


if __name__ == "__main__":
    unittest.main()
