"""Blind drawer count at shift close: runs the real close_shift_dialog with
stubbed dialogs (needs tkinter; skipped without it). Run under xvfb if no display."""
import os
import tempfile
import types
import unittest

try:
    import main as M
except Exception as e:  # tkinter / display missing
    M = None
    _why = str(e)
from database import DB


@unittest.skipIf(M is None, "main/tkinter unavailable")
class BlindClose(unittest.TestCase):
    def setUp(self):
        self.db = DB(path=os.path.join(tempfile.mkdtemp(), "t.db"))
        self.db.create_user("boss", "password123", "admin")
        self.db.create_user("emp", "password123", "cashier")
        self.sid = self.db.open_shift("boss", 100)
        self.sh = dict(self.db.conn.execute("SELECT * FROM shifts WHERE id=?", (self.sid,)).fetchone())
        self.infos, self.prompts, self.confirms = [], [], []
        self.orig = (M.messagebox.showinfo, M.messagebox.showerror, M.simpledialog.askfloat, M.messagebox.askyesno)
        M.messagebox.showinfo = lambda t, m, **k: self.infos.append(m)
        M.messagebox.showerror = lambda t, m, **k: self.infos.append("ERR " + m)
        M.simpledialog.askfloat = lambda t, p, **k: (self.prompts.append(p), 95.0)[1]
        self.answer = True
        M.messagebox.askyesno = lambda t, m, **k: (self.confirms.append(m), self.answer)[1]
        self.app = types.SimpleNamespace(db=self.db, current_shift=dict(self.sh), username="boss",
                                         cash_refresh=lambda: None)

    def tearDown(self):
        (M.messagebox.showinfo, M.messagebox.showerror, M.simpledialog.askfloat, M.messagebox.askyesno) = self.orig

    def status(self):
        return self.db.conn.execute("SELECT status FROM shifts WHERE id=?", (self.sid,)).fetchone()[0]

    def test_prompt_is_blind_and_result_shown_after_confirm(self):
        M.App.close_shift_dialog(self.app)
        p = self.prompts[0]
        self.assertNotIn("100", p)
        self.assertNotIn("المتوقع في الدرج:", p)
        self.assertNotIn("رصيد البداية", p)
        self.assertNotIn("95", self.prompts[0])
        self.assertIn("95.00", self.confirms[0])
        self.assertEqual(self.status(), "closed")
        self.assertIn("المتوقع في الدرج: 100.00", self.infos[-1])
        self.assertIn("(عجز)", self.infos[-1])

    def test_declined_confirmation_keeps_shift_open(self):
        self.answer = False
        M.App.close_shift_dialog(self.app)
        self.assertEqual(self.status(), "open")
        self.assertEqual(self.infos, [])

    def test_opening_float_hidden_from_employee_label(self):
        class Lbl:
            text = ""
            def config(self, text=""): self.text = text
        for is_admin, expect in ((False, False), (True, True)):
            lbl = Lbl()
            st = types.SimpleNamespace(db=self.db, current_shift=dict(self.sh), lbl_shift=lbl, is_admin=is_admin,
                                       tree_exp=types.SimpleNamespace(get_children=lambda: [], delete=lambda i: None),
                                       theme_name="", update_topbar=lambda: None)
            orig = M.ui_theme.stripe_rows
            M.ui_theme.stripe_rows = lambda *a, **k: None
            try:
                M.App.cash_refresh(st)
            finally:
                M.ui_theme.stripe_rows = orig
            self.assertEqual("رصيد أول المدة" in lbl.text, expect, lbl.text)


if __name__ == "__main__":
    unittest.main()
