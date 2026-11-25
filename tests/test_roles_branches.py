# -*- coding: utf-8 -*-
"""Role-based access, branches and attendance (DB layer). Run: py tests/test_roles_branches.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import DB


class RolesBranches(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = DB(path=os.path.join(self.dir, "t.db"))
        self.db.create_user("boss", "password123", "admin")
        self.db.create_user("emp1", "password123", "cashier", "Emp One")
        self.db.create_user("emp2", "password123", "cashier", "Emp Two")

    def test_only_admin_manages_branches(self):
        bid = self.db.add_branch("boss", "Main", "Cairo")
        self.assertEqual([b["name"] for b in self.db.list_branches()], ["Main"])
        with self.assertRaises(PermissionError):
            self.db.add_branch("emp1", "Evil")
        with self.assertRaises(PermissionError):
            self.db.set_user_branch("emp1", "emp1", bid)
        with self.assertRaises(PermissionError):
            self.db.set_branch_active("emp1", bid, False)
        with self.assertRaises(PermissionError):
            self.db.list_users("emp1")
        with self.assertRaises(ValueError):
            self.db.add_branch("boss", "Main")
        self.db.set_user_branch("boss", "emp1", bid)
        self.assertEqual(self.db.user_branch_id("emp1"), bid)
        self.db.set_branch_active("boss", bid, False)
        self.assertEqual(self.db.list_branches(active_only=True), [])

    def test_attendance_flow(self):
        bid = self.db.add_branch("boss", "Main")
        self.db.set_user_branch("boss", "emp1", bid)
        self.db.check_in("emp1")
        with self.assertRaises(ValueError):
            self.db.check_in("emp1")
        self.assertIsNotNone(self.db.attendance_open_for("emp1"))
        self.db.check_out("emp1")
        with self.assertRaises(ValueError):
            self.db.check_out("emp1")
        rows = self.db.attendance_report("emp1", "2000-01-01", "2100-01-01")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["branch_name"], "Main")

    def test_employee_sees_only_own_attendance(self):
        self.db.check_in("emp1")
        self.db.check_in("emp2")
        mine = self.db.attendance_report("emp1", "2000-01-01", "2100-01-01", username="emp2")
        self.assertEqual({r["username"] for r in mine}, {"emp1"})
        allrows = self.db.attendance_report("boss", "2000-01-01", "2100-01-01")
        self.assertEqual({r["username"] for r in allrows}, {"emp1", "emp2"})

    def test_manual_shift_admin_only_and_validated(self):
        with self.assertRaises(PermissionError):
            self.db.attendance_add_manual("emp1", "emp1", "2026-11-25 09:00", "2026-11-25 17:00")
        with self.assertRaises(ValueError):
            self.db.attendance_add_manual("boss", "emp1", "2026-11-25 17:00", "2026-11-25 09:00")
        with self.assertRaises(ValueError):
            self.db.attendance_add_manual("boss", "emp1", "garbage", "")
        with self.assertRaises(ValueError):
            self.db.attendance_add_manual("boss", "nobody", "2026-11-25 09:00", "")
        self.db.attendance_add_manual("boss", "emp1", "2026-11-25 09:00", "2026-11-25 17:30", "morning")
        rows = self.db.attendance_report("boss", "2026-11-25", "2026-11-25", "emp1")
        self.assertEqual(rows[0]["hours"], 8.5)

    def test_shift_gets_user_branch(self):
        bid = self.db.add_branch("boss", "Main")
        self.db.set_user_branch("boss", "emp1", bid)
        sid = self.db.open_shift("emp1", 100)
        row = self.db.conn.execute("SELECT branch_id FROM shifts WHERE id=?", (sid,)).fetchone()
        self.assertEqual(row["branch_id"], bid)

    def test_existing_db_migrates(self):
        # re-open the same file: migration is idempotent
        path = os.path.join(self.dir, "t.db")
        DB(path=path)
        DB(path=path)


    def test_shared_shift_many_employees(self):
        bid = self.db.add_branch("boss", "Main")
        for u in ("emp1", "emp2"):
            self.db.set_user_branch("boss", u, bid)
        sid = self.db.open_shift("emp1", 100)
        with self.assertRaises(ValueError):
            self.db.open_shift("emp2", 0)  # one shared drawer per branch
        self.assertEqual(self.db.join_shift("emp2"), sid)
        self.assertEqual(self.db.open_shift_for("emp2")["id"], sid)
        self.assertEqual([m["username"] for m in self.db.shift_members(sid)], ["emp1", "emp2"])
        # attendance stays individual
        self.db.check_in("emp1")
        self.assertIsNone(self.db.attendance_open_for("emp2"))
        self.assertIsNotNone(self.db.attendance_open_for("emp1"))
        summ = self.db.shift_summary(sid)
        self.assertEqual(summ["members"], ["emp1", "emp2"])

    def test_employee_cannot_void_or_edit_invoice(self):
        with self.assertRaises(PermissionError):
            self.db.return_sale(1, "emp1")
        with self.assertRaises(PermissionError):
            self.db.edit_sale(1, "emp1", [])

    def _drug(self, name="D1"):
        did = self.db.add_drug({"trade_en": name, "trade_ar": "ت", "scientific": "x", "company": "x",
                                "form": "Tabs", "strength": "1", "category": "t", "strips_per_box": 1,
                                "tablets_per_strip": 10, "buy_price": 5, "sell_price": 10,
                                "min_stock": 1, "barcode": ""})
        return self.db.get_drug(did)

    def _stock(self, drug_id, qty, branch):
        self.db.conn.execute(
            "INSERT INTO batches (drug_id, batch_no, expiry, qty_units, buy_price_unit, created_at, branch_id) "
            "VALUES (?,?,?,?,?,?,?)", (drug_id, "B", "2099-01-01", qty, 0.5, "2026-01-01", branch))
        self.db.conn.commit()

    def _items(self, d, q=1):
        return [{"drug": d, "pack_level": "box", "qty_display": q}]

    def test_branch_stock_sales_reports_are_separate(self):
        d = self._drug()
        self._stock(d["id"], 20, None)               # legacy stock, no branch yet
        a = self.db.add_branch("boss", "A")          # first branch adopts legacy stock
        b = self.db.add_branch("boss", "B")
        self.assertEqual(self.db.conn.execute("SELECT branch_id FROM batches").fetchone()[0], a)
        self._stock(d["id"], 10, b)
        self.db.set_scope(a)
        self.assertEqual(self.db.get_drug(d["id"]).get("stock_units"), 20)
        self.db.set_scope(b)
        self.assertEqual(self.db.sellable_stock(d["id"]), 10)
        self.db.create_sale("boss", self._items(d, 1), payment_method="cash", paid=10)   # 10 units from B
        self.assertEqual(self.db.sellable_stock(d["id"]), 0)
        with self.assertRaises(ValueError):
            self.db.create_sale("boss", self._items(d, 1))   # B is empty; A's stock must not be used
        self.db.set_scope(a)
        self.assertEqual(self.db.sellable_stock(d["id"]), 20)
        self.assertEqual(self.db.report_daily()["count"], 0)
        self.db.set_scope(b)
        self.assertEqual(self.db.report_daily()["count"], 1)
        self.db.set_scope(None)                       # admin sees all
        self.assertEqual(self.db.report_daily()["count"], 1)
        self.assertEqual(self.db.sellable_stock(d["id"]), 20)
        with self.assertRaises(ValueError):           # two branches: admin must choose one to write
            self.db.add_expense("x", 5, user="boss")
        # return restocks the sale's own branch
        sid = self.db.conn.execute("SELECT id FROM sales").fetchone()[0]
        self.db.return_sale(sid, "boss")
        self.db.set_scope(b)
        self.assertEqual(self.db.sellable_stock(d["id"]), 10)

    def test_employee_sees_only_own_sales(self):
        d = self._drug()
        a = self.db.add_branch("boss", "A")
        self._stock(d["id"], 50, a)
        self.db.set_scope(a)
        self.db.create_sale("emp1", self._items(d, 1), payment_method="cash", paid=10)
        self.db.create_sale("emp2", self._items(d, 2), payment_method="cash", paid=20)
        self.db.set_scope(a, user="emp1")
        self.assertEqual(self.db.report_daily()["total"], 10)
        self.assertEqual([x["cashier"] for x in self.db.sales_on()], ["emp1"])
        self.db.set_scope(a)
        self.assertEqual(self.db.report_daily()["total"], 30)

    def test_customer_history_scoped(self):
        d = self._drug()
        a = self.db.add_branch("boss", "A")
        b = self.db.add_branch("boss", "B")
        self._stock(d["id"], 100, a)
        self._stock(d["id"], 100, b)
        cid = self.db.conn.execute("SELECT id FROM customers LIMIT 1").fetchone()
        if cid is None:
            self.db.conn.execute("INSERT INTO customers (name, phone, credit_limit, created_at) VALUES ('c','',1000,'x')")
            self.db.conn.commit()
            cid = self.db.conn.execute("SELECT id FROM customers LIMIT 1").fetchone()
        cid = cid[0]
        self.db.set_scope(a)
        self.db.create_sale("emp1", self._items(d, 1), customer_id=cid, payment_method="credit", paid=0)
        self.db.create_sale("emp2", self._items(d, 1), customer_id=cid, payment_method="credit", paid=0)
        self.db.set_scope(b)
        self.db.create_sale("boss", self._items(d, 1), customer_id=cid, payment_method="credit", paid=0)
        self.db.set_scope(a, user="emp1")
        hist = [r for r in self.db.customer_history(cid) if r.get("status") != "payment"]
        self.assertEqual([r["cashier"] for r in hist], ["emp1"])
        self.db.set_scope(None)
        self.assertEqual(len(self.db.customer_history(cid)), 3)

    def test_premigration_backup_is_made(self):
        import sqlite3
        path = os.path.join(self.dir, "old.db")
        db = DB(path=path)
        db.add_drug({"trade_en": "Z", "trade_ar": "ز", "scientific": "x", "company": "x", "form": "Tabs",
                     "strength": "1", "category": "t", "strips_per_box": 1, "tablets_per_strip": 1,
                     "buy_price": 1, "sell_price": 2, "min_stock": 1, "barcode": ""})
        db.close()
        # simulate a database from before branches existed
        c = sqlite3.connect(path)
        c.execute("DROP TRIGGER IF EXISTS trg_stock_mov_branch")
        for t in ("batches", "sales", "expenses", "purchases", "stock_movements", "customer_payments"):
            c.execute("ALTER TABLE %s DROP COLUMN branch_id" % t)
        c.commit(); c.close()
        db = DB(path=path)
        folder = os.path.join(self.dir, "backups")
        self.assertTrue(any("pre_migration_branches" in f for f in os.listdir(folder)), os.listdir(folder))
        self.assertTrue(DB.verify_backup(os.path.join(folder, [f for f in os.listdir(folder) if "pre_migration_branches" in f][0])))

    def test_shared_shift_close_and_leave_rules(self):
        bid = self.db.add_branch("boss", "Main")
        for u in ("emp1", "emp2"):
            self.db.set_user_branch("boss", u, bid)
        sid = self.db.open_shift("emp1", 0)
        self.db.join_shift("emp2")
        with self.assertRaises(PermissionError):
            self.db.close_shift(sid, 0, actor="emp2")      # a member who did not open it
        self.db.check_in("emp2")
        self.db.leave_shift("emp2")                          # leaves, shift stays open, departure recorded
        self.assertIsNone(self.db.open_shift_for("emp2"))
        self.assertIsNotNone(self.db.open_shift_for("emp1"))
        self.assertIsNone(self.db.attendance_open_for("emp2"))
        with self.assertRaises(ValueError):
            self.db.leave_shift("emp1")                      # last member must close instead
        self.db.close_shift(sid, 0, actor="emp1")            # opener may close
        sid2 = self.db.open_shift("emp2", 0)
        self.db.close_shift(sid2, 0, actor="boss")           # admin may close any shift

if __name__ == "__main__":
    unittest.main()
