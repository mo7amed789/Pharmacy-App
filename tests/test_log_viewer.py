"""Owner log viewer: long lines wrap (nothing clipped), the list scrolls, and
clicking a line shows the full record (no CSV needed). Needs tkinter + a display."""
import os
import tempfile
import types
import unittest

try:
    import tkinter as tk
    from tkinter import ttk
    import main as M
    _root = tk.Tk()
    _root.withdraw()
except Exception:
    M = None
from database import DB


@unittest.skipIf(M is None, "tkinter/display unavailable")
class LogViewer(unittest.TestCase):
    def setUp(self):
        self.db = DB(path=os.path.join(tempfile.mkdtemp(), "t.db"))
        self.app = types.SimpleNamespace(db=self.db)
        for n in ("_make_log_view", "_log_line_click"):
            setattr(self.app, n, types.MethodType(getattr(M.App, n), self.app))
        self.win = tk.Toplevel(_root)
        self.win.geometry("700x500")
        self.txt, self.det = self.app._make_log_view(self.win, 6, "sys")
        self.app.txt_syslog, self.app.txt_syslog_detail = self.txt, self.det
        self.win.update()

    def tearDown(self):
        self.win.destroy()

    def test_wraps_scrolls_and_detail_shows_full_record(self):
        self.assertEqual(str(self.txt.cget("wrap")), "word")
        kinds = [type(w).__name__ for w in self.txt.master.winfo_children()]
        self.assertIn("Scrollbar", kinds)
        long_tail = "ValueError: " + "x" * 400 + " END-OF-TRACE"
        self.db.syslog("error", "mobile", "http_500", "POST /api/invoices", "Traceback\n" + long_tail)
        self.db.syslog("info", "updater", "update_applied", "applied abc")
        rows = self.db.system_log_query()
        self.app._sys_rows = rows
        for r in rows:
            self.txt.insert("end", "%s | %s | %s\n" % (r["created_at"], r["level"], r["event"]))
        self.win.update()
        # click the second display line (= older row: http_500)
        bbox = self.txt.bbox("2.0")
        ev = types.SimpleNamespace(x=bbox[0] + 3, y=bbox[1] + 3)
        self.app._log_line_click(self.txt, "sys", ev)
        shown = self.det.get("1.0", "end")
        self.assertIn("END-OF-TRACE", shown)       # full detail, not truncated to 200 chars
        self.assertIn("http_500", shown)
        self.assertIn("component: mobile", shown)


if __name__ == "__main__":
    unittest.main()
