import os, tempfile, time, unittest
from database import DB
import search_util as S

AR = lambda *c: "".join(chr(x) for x in c)


class SearchSpacing(unittest.TestCase):
    def setUp(self):
        self.db = DB(path=os.path.join(tempfile.mkdtemp(), "t.db"))
        ins = lambda en, ar, sci="": self.db.conn.execute(
            "INSERT INTO drugs (trade_en,trade_ar,scientific,sell_price,active) VALUES (?,?,?,?,1)", (en, ar, sci, 10))
        ins("light vel cream 50 gm", "\u0644\u0627\u064a\u062a \u0641\u0644 \u0643\u0631\u064a\u0645 50 \u062c\u0645")
        ins("panadol advance 500 mg", "\u0628\u0627\u0646\u0627\u062f\u0648\u0644 \u0627\u062f\u0641\u0627\u0646\u0633")
        ins("amoxicillin 500mg caps", "\u0623\u0645\u0648\u0643\u0633\u064a\u0633\u064a\u0644\u064a\u0646", "amoxicillin")
        ins("panthenol cream", "\u0628\u0627\u0646\u062b\u064a\u0646\u0648\u0644 \u0643\u0631\u064a\u0645")
        ins("vitamin c 1000 mg", "\u0641\u064a\u062a\u0627\u0645\u064a\u0646 \u0633\u064a \u0629")
        self.db.conn.commit()

    def names(self, q):
        return [d["trade_en"] for d in self.db.search_drugs(q)]

    def test_spaces_ignored_both_ways(self):
        for q in ("light vel", "lightvel", "Lightvel Cream", "light  vel", "\u0644\u0627\u064a\u062a\u0641\u0644", "\u0644\u0627\u064a\u062a \u0641\u0644"):
            self.assertEqual(self.names(q)[:1], ["light vel cream 50 gm"], q)
        self.assertEqual(self.names("zzzzzz"), [])

    def test_typos_swap_missing_extra_letter(self):
        for q in ("lihgt vel", "panadool", "panadl", "panadoll", "amoxcillin", "amoxicilin 500"):
            self.assertTrue(self.names(q), q)
        self.assertEqual(self.names("panadoll")[0], "panadol advance 500 mg")
        self.assertEqual(self.names("amoxcillin")[0], "amoxicillin 500mg caps")

    def test_arabic_variants_and_tashkeel(self):
        self.assertEqual(S.normalize(AR(0x623, 0x645, 0x648)), S.normalize(AR(0x627, 0x645, 0x648)))        # alef hamza
        self.assertEqual(S.normalize(AR(0x6A9, 0x631)), S.normalize(AR(0x643, 0x631)))
        for q in (AR(0x627, 0x645, 0x648, 0x643, 0x633, 0x64a, 0x633, 0x64a, 0x644, 0x64a, 0x646),            # alef instead of hamza
                  AR(0x623, 0x645, 0x648, 0x643, 0x633, 0x650, 0x64a, 0x633, 0x650, 0x64a, 0x644, 0x650, 0x64a, 0x646),  # with tashkeel
                  AR(0x627, 0x645, 0x648, 0x643, 0x633, 0x64a, 0x633, 0x64a, 0x644, 0x649, 0x646)):           # misspelled letters
            self.assertEqual(self.names(q)[:1], ["amoxicillin 500mg caps"], q)
        self.assertEqual(self.names(AR(0x641, 0x64a, 0x62a, 0x627, 0x645, 0x64a, 0x646, 0x20, 0x633, 0x64a, 0x20, 0x647))[:1], ["vitamin c 1000 mg"])  # teh marbuta vs heh

    def test_ranking_exact_before_fuzzy(self):
        r = self.names("panadol")
        self.assertEqual(r[0], "panadol advance 500 mg")
        self.assertIn("panthenol cream", self.names("panthnol"))

    def test_short_words_not_fuzzy(self):
        self.assertEqual(self.names("xyz"), [])

    def test_index_refreshes_after_new_drug(self):
        self.assertEqual(self.names("brandnew"), [])
        self.db.conn.execute("INSERT INTO drugs (trade_en,trade_ar,sell_price,active) VALUES ('brandnew gel','',5,1)")
        self.db.conn.commit()
        self.assertEqual(self.names("brandnew"), ["brandnew gel"])

    def test_speed_on_large_table(self):
        self.db.conn.executemany("INSERT INTO drugs (trade_en,trade_ar,sell_price,active) VALUES (?,?,1,1)",
                                 [("drug%dx syrup %d ml" % (i, i % 7), "\u062f\u0648\u0627\u0621 %d" % i) for i in range(30000)])
        self.db.conn.commit()
        self.names("warmup")
        t = time.time(); self.names("panadl"); self.names("drug123"); self.names("lightvel")
        self.assertLess(time.time() - t, 3.0)


if __name__ == "__main__":
    unittest.main()
