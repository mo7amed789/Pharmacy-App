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


if __name__ == "__main__":
    unittest.main()
