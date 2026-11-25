"""Owner activity log + system log: who / what / when / branch / shift / before-after,
no secrets, append-only, desktop + phone. Disposable DBs only."""
import inspect
import json
import os
import re
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from database import DB, redact_text
from mobile_server import _make_handler, _ReuseServer


def _drug(db, price=10):
    return db.add_drug(dict(trade_en="Panadol", trade_ar="", scientific="", company="", form="Tabs",
                            strength="", category="", strips_per_box=1, tablets_per_strip=1,
                            buy_price=5, sell_price=price, min_stock=0, barcode=""))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "t.db")
        self.db = DB(path=self.path)
        self.db.create_user("boss", "S3cretPass!", "admin")
        self.db.create_user("emp1", "S3cretPass!", "cashier", "Emp One")
        self.a = self.db.add_branch("boss", "Branch A")
        self.db.set_user_branch("boss", "emp1", self.a)
        self.did = _drug(self.db)
        self.db.conn.execute("INSERT INTO batches (drug_id,batch_no,expiry,qty_units,buy_price_unit,created_at,branch_id)"
                             " VALUES (?,?,?,?,?,?,?)", (self.did, "b", "2030-01-01", 100, 5, "x", self.a))
        self.db.conn.commit()

    def rows(self, action=None):
        q = "SELECT * FROM audit_log" + (" WHERE action=?" if action else "") + " ORDER BY id"
        return [dict(r) for r in self.db.conn.execute(q, (action,) if action else ()).fetchall()]



class Tracking(Base):
    def test_sale_has_actor_role_branch_shift_source_and_after(self):
        self.db.set_actor("emp1", "desktop")
        b, u = self.db.scope_for_user("emp1")
        self.db.set_scope(b, u)
        sid = self.db.open_shift("emp1", 50)
        items = [dict(drug_id=self.did, unit="pill", qty=2)]
        self.db.create_sale_from_items("emp1", items, payment_method="cash", paid=20, source="mobile", shift_id=sid)
        r = self.rows("sale")[-1]
        self.assertEqual((r["user"], r["role"], r["branch_id"], r["shift_id"], r["source"]),
                         ("emp1", "cashier", self.a, sid, "desktop"))
        after = json.loads(r["after_json"])
        self.assertEqual(after["total"], 20.0)
        self.assertEqual(after["via"], "mobile")
        self.assertEqual(r["entity"], "sale")

    def test_before_after_for_price_stock_customer_shift(self):
        self.db.set_actor("boss", "desktop")
        d = self.db.get_drug(self.did)
        f = dict(d); f["sell_price"] = 12
        self.db.update_drug(self.did, f)
        r = self.rows("edit_drug")[-1]
        self.assertEqual(json.loads(r["before_json"]), {"sell_price": 10.0})
        self.assertEqual(json.loads(r["after_json"]), {"sell_price": 12.0})
        self.db.update_drug(self.did, f)                  # no change -> no row
        self.assertEqual(len(self.rows("edit_drug")), 1)
        self.db.set_scope(self.a)
        self.db.adjust_stock(self.did, -3, "damaged", "boss")
        self.assertEqual(json.loads(self.rows("adjust_stock")[-1]["after_json"])["delta_units"], -3)
        cid = self.db.add_customer("Ali", "1", 500)
        self.db.conn.execute("UPDATE customers SET balance=100 WHERE id=?", (cid,)); self.db.conn.commit()
        self.db.customer_pay(cid, 30, user="boss")
        r = self.rows("customer_payment")[-1]
        self.assertEqual(json.loads(r["before_json"])["balance"], 100.0)
        self.assertEqual(json.loads(r["after_json"])["balance"], 70.0)
        sid = self.db.open_shift("boss", 100)
        self.db.close_shift(sid, 95, actor="boss")
        r = self.rows("close_shift")[-1]
        a = json.loads(r["after_json"])
        self.assertEqual((a["expected_cash"], a["counted_cash"], a["difference"]), (100.0, 95.0, -5.0))
        self.assertEqual(r["shift_id"], sid)

    def test_return_and_edit_are_tracked_with_before_after(self):
        self.db.set_actor("boss", "desktop")
        self.db.set_scope(self.a)
        sale_id, inv, total, _ = self.db.create_sale_from_items("boss", [dict(drug_id=self.did, unit="pill", qty=1)])
        self.db.edit_sale_from_items(sale_id, "boss", [dict(drug_id=self.did, unit="pill", qty=3)])
        e = self.rows("edit_sale")[-1]
        self.assertEqual(json.loads(e["before_json"])["total"], 10.0)
        self.assertEqual(json.loads(e["after_json"])["total"], 30.0)
        self.db.return_sale(sale_id, "boss", reason="x")
        r = self.rows("return_sale")[-1]
        self.assertEqual(json.loads(r["after_json"])["status"], "returned")
        self.assertEqual(r["branch_id"], self.a)

    def test_no_secrets_in_activity_or_system_log(self):
        self.db.set_actor("boss", "desktop")
        self.db.change_password("emp1", "N3wSecretPass!")
        self.db.set_setting("pharmacy_phone", "0100")
        self.db.syslog("error", "desktop", "ui_exception", "password=hunter22 pin=123456 Bearer abc.def.ghi",
                       "key=sk-abcdefghijklmnopqrstuvwx\nAuthorization: Bearer zzzzzzzz\n" + "a" * 60)
        dump = json.dumps([dict(r) for r in self.db.conn.execute("SELECT * FROM audit_log").fetchall()]
                          + [dict(r) for r in self.db.conn.execute("SELECT * FROM system_log").fetchall()],
                          ensure_ascii=False)
        for bad in ("S3cretPass", "N3wSecretPass", "hunter22", "123456", "sk-abcdefgh", "zzzzzzzz", "pbkdf2", "a" * 50):
            self.assertNotIn(bad, dump)
        self.assertTrue(self.rows("password_changed"))
        self.assertEqual(redact_text("token=abc123 here"), "token=[redacted] here")

    def test_logs_are_append_only(self):
        self.db.audit("boss", "x", "y")
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.conn.execute("UPDATE audit_log SET user='someone else'")
        self.db.syslog("info", "t", "e", "m")
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.conn.execute("UPDATE system_log SET message='x'")

    def test_old_database_keeps_rows_and_gains_columns(self):
        db2 = DB(path=os.path.join(self.dir, "old.db"))
        db2.conn.execute("DROP TRIGGER trg_audit_log_no_update")
        db2.conn.executescript("""ALTER TABLE audit_log RENAME TO audit_new;
            CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT DEFAULT '',
              action TEXT DEFAULT '', details TEXT DEFAULT '', created_at TEXT DEFAULT '');
            INSERT INTO audit_log (user, action, details, created_at) VALUES ('old','sale','INV-1','2026-01-01T00:00:00');
            DROP TABLE audit_new;""")
        db2.close()
        db3 = DB(path=os.path.join(self.dir, "old.db"))
        cols = [r[1] for r in db3.conn.execute("PRAGMA table_info(audit_log)").fetchall()]
        for c in ("source", "role", "branch_id", "shift_id", "before_json", "after_json", "entity"):
            self.assertIn(c, cols)
        self.assertEqual(db3.conn.execute("SELECT details FROM audit_log WHERE user='old'").fetchone()[0], "INV-1")

    def test_every_mutating_db_method_is_tracked_or_listed_as_exempt(self):
        EXEMPT = {  # internal helpers (their public caller logs), migrations, seeding, print flag
            "_deduct_fefo": "called by sale/return/adjust which log",
            "_link_barcode_checked": "called by add_drug/link_barcode (UI logs link_barcode)",
            "_split_lines": "called by create_sale which logs",
            "mark_printed": "print status flag only",
            "seed_if_empty": "first-run demo seed",
            "authenticate": "login/failed login logged by the desktop login screen and phone server",
            "link_barcode": "logged by the desktop caller (link_barcode)",
        }
        tabs = ("drugs|batches|sales|sale_items|expenses|purchases|purchase_items|stock_movements|customers|"
                "customer_payments|suppliers|users|shifts|shift_members|attendance|branches|settings")
        missing = []
        for n, f in inspect.getmembers(DB, inspect.isfunction):
            if n.startswith("__") or n.startswith("_migrate") or n in EXEMPT:
                continue
            try:
                src = inspect.getsource(f)
            except OSError:
                continue
            if re.search(r"(INSERT INTO|UPDATE|DELETE FROM)\s+(%s)\b" % tabs, src, re.I):
                if "_audit_row" not in src and "self.audit(" not in src:
                    missing.append(n)
        self.assertEqual(missing, [])


class PhoneTracking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "t.db")
        db = DB(self.path)
        self.pin = db.ensure_mobile_pin()
        db.create_user("manager", "S3cretPass!", "admin")
        db.create_user("alice", "S3cretPass!", "cashier")
        a = db.add_branch("manager", "A")
        db.set_user_branch("manager", "alice", a)
        self.did = _drug(db)
        db.conn.execute("INSERT INTO batches (drug_id,batch_no,expiry,qty_units,buy_price_unit,created_at,branch_id)"
                        " VALUES (?,?,?,?,?,?,?)", (self.did, "b", "2030-01-01", 100, 5, "x", a))
        db.conn.commit(); db.close()
        self.server = _ReuseServer(("127.0.0.1", 0), _make_handler(self.path))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.server.server_port

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.tmp.cleanup()

    def req(self, method, path, data=None, token=None):
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = "Bearer " + token
        r = urllib.request.Request(self.base + path, headers=h, method=method,
                                   data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_phone_sale_login_and_failed_login_are_logged_without_password(self):
        bad = self.req("POST", "/api/login", dict(username="alice", password="WrongPass999!"))
        self.assertEqual(bad[0], 401)
        tok = self.req("POST", "/api/login", dict(username="alice", password="S3cretPass!"))[1]["token"]
        s = self.req("POST", "/api/invoices", dict(items=[dict(drug_id=self.did, unit="box", qty=1)],
                                                   payment="cash", client_ref="r1"), tok)
        self.assertEqual(s[0], 200)
        db = DB(self.path, init=False)
        rows = {r["action"]: dict(r) for r in db.conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()}
        self.assertEqual((rows["sale"]["user"], rows["sale"]["source"], rows["sale"]["role"]),
                         ("alice", "mobile", "cashier"))
        self.assertIsNotNone(rows["sale"]["branch_id"])
        self.assertIn("mobile_login", rows)
        self.assertIn("mobile_login_failed", rows)
        dump = json.dumps([dict(r) for r in db.conn.execute("SELECT * FROM audit_log").fetchall()])
        self.assertNotIn("WrongPass999", dump)
        self.assertNotIn("S3cretPass", dump)
        db.close()


class Integrity(Base):
    """Logs cannot be deleted by staff / app SQL before retention, and a business
    write is never saved without its activity row."""

    def test_recent_rows_cannot_be_deleted_or_updated(self):
        self.db.syslog("error", "t", "boom", "x")
        self.db.audit("boss", "login", "")
        for sql in ("DELETE FROM audit_log", "DELETE FROM system_log",
                    "DELETE FROM audit_log WHERE id>0", "UPDATE audit_log SET user='x'",
                    "UPDATE system_log SET message='x'"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                self.db.conn.execute(sql)
            self.db.conn.rollback()
        self.assertGreater(self.db.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0], 0)
        self.assertGreater(self.db.conn.execute("SELECT COUNT(*) FROM system_log").fetchone()[0], 0)

    def test_only_aged_out_rows_are_pruned(self):
        old_a = "2000-01-01T00:00:00"
        self.db.conn.execute("INSERT INTO audit_log (user,action,details,created_at) VALUES ('x','old','',?)", (old_a,))
        self.db.conn.execute("INSERT INTO system_log (created_at,level,component,event) VALUES (?,?,?,?)",
                             (old_a, "info", "t", "old"))
        # 400 days: past the 365-day system retention, inside the 730-day activity retention
        from datetime import datetime, timedelta
        mid = (datetime.now() - timedelta(days=400)).isoformat(timespec="seconds")
        self.db.conn.execute("INSERT INTO audit_log (user,action,details,created_at) VALUES ('x','mid','',?)", (mid,))
        self.db.conn.execute("INSERT INTO system_log (created_at,level,component,event) VALUES (?,?,?,?)",
                             (mid, "info", "t", "mid"))
        self.db.conn.commit()
        self.db._prune_audit_log()
        acts = {r[0] for r in self.db.conn.execute("SELECT action FROM audit_log")}
        evs = {r[0] for r in self.db.conn.execute("SELECT event FROM system_log")}
        self.assertNotIn("old", acts); self.assertIn("mid", acts)
        self.assertNotIn("old", evs); self.assertNotIn("mid", evs)
        # a row with a blank date can never be deleted
        self.db.conn.execute("INSERT INTO audit_log (user,action,details,created_at) VALUES ('x','blank','','')")
        self.db.conn.commit()
        self.db._prune_audit_log()
        self.assertIn("blank", {r[0] for r in self.db.conn.execute("SELECT action FROM audit_log")})

    def test_app_code_never_deletes_logs_except_prune(self):
        import database
        src = inspect.getsource(database)
        self.assertEqual(len(re.findall(r"DELETE FROM (audit_log|system_log)", src)), 2)
        for f in ("main.py", "mobile_server.py", "cloud_sync.py", "updater.py", "automation.py"):
            with open(os.path.join(os.path.dirname(__file__), "..", f), encoding="utf-8") as fh:
                self.assertNotRegex(fh.read(), r"DELETE FROM (audit_log|system_log)|DROP TABLE (audit_log|system_log)")

    def _break_audit_inserts(self):
        self.db.conn.execute("""CREATE TRIGGER t_break BEFORE INSERT ON audit_log
            BEGIN SELECT RAISE(ABORT, 'disk full simulated'); END""")
        self.db.conn.commit()

    def _count(self, t):
        return self.db.conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]

    def test_audit_failure_rolls_back_sale_stock_and_shift(self):
        self.db.set_actor("emp1", "desktop")
        b, u = self.db.scope_for_user("emp1"); self.db.set_scope(b, u)
        sid = self.db.open_shift("emp1", 50)
        stock0 = self.db.conn.execute("SELECT SUM(qty_units) FROM batches").fetchone()[0]
        sales0 = self._count("sales")
        self._break_audit_inserts()
        with self.assertRaises(RuntimeError):
            self.db.create_sale_from_items("emp1", [dict(drug_id=self.did, unit="pill", qty=2)],
                                           payment_method="cash", paid=20, shift_id=sid)
        self.assertEqual(self._count("sales"), sales0)
        self.assertEqual(self.db.conn.execute("SELECT SUM(qty_units) FROM batches").fetchone()[0], stock0)
        # a later unrelated commit must not resurrect the half-done sale
        self.db.conn.execute("DROP TRIGGER t_break"); self.db.conn.commit()
        self.assertEqual(self._count("sales"), sales0)
        self.assertEqual(self.db.conn.execute("SELECT SUM(qty_units) FROM batches").fetchone()[0], stock0)

    def test_audit_failure_blocks_every_other_business_write(self):
        self.db.set_actor("boss", "desktop")
        self._break_audit_inserts()
        n_drugs, n_exp = self._count("drugs"), self._count("expenses")
        n_cust, n_move = self._count("customers"), self._count("stock_movements")
        with self.assertRaises(RuntimeError):
            _drug(self.db, 11)
        with self.assertRaises(RuntimeError):
            self.db.add_expense("rent", 10, "", user="boss")
        with self.assertRaises(RuntimeError):
            self.db.adjust_stock(self.did, 5, "t", "boss")
        with self.assertRaises(RuntimeError):
            self.db.add_customer("Zed", "01000000000")
        self.assertEqual(self._count("drugs"), n_drugs)
        self.assertEqual(self._count("expenses"), n_exp)
        self.assertEqual(self._count("customers"), n_cust)
        self.assertEqual(self._count("stock_movements"), n_move)
        self.assertGreaterEqual(self._count("system_log"), 1)  # the failure itself is recorded

    def test_informational_event_failure_is_recorded_in_system_log(self):
        self._break_audit_inserts()
        self.db.audit("boss", "login", "role=admin")  # must not raise
        r = self.db.conn.execute("SELECT * FROM system_log WHERE event='audit_write_failed'").fetchone()
        self.assertIsNotNone(r)


class CloudSyncErrors(Base):
    def test_failed_syncs_reach_the_system_log_once_per_window(self):
        import cloud_sync, supabase_client

        class Boom:
            def upsert_products(self, rows):
                raise supabase_client.SupabaseError("HTTP 503 apikey=SUPERSECRETKEY123")
        orig = (cloud_sync._client, supabase_client.is_configured)
        cloud_sync._client = lambda: Boom()
        supabase_client.is_configured = lambda: True
        try:
            self.assertFalse(cloud_sync.push_drug_safe(self.db, self.did))
            self.assertFalse(cloud_sync.push_drug_safe(self.db, self.did))
        finally:
            cloud_sync._client, supabase_client.is_configured = orig
        rows = self.db.system_log_query(component="cloud_sync")
        self.assertEqual(len(rows), 1)  # same error inside 30 min is logged once
        self.assertEqual(rows[0]["event"], "push_failed")
        self.assertEqual(rows[0]["level"], "error")
        self.assertNotIn("SUPERSECRETKEY123", json.dumps(rows))
        self.assertTrue(self.db.get_setting("cloud_last_error"))

    def test_partial_push_and_failed_order_are_logged(self):
        import cloud_sync, supabase_client

        class Half:
            def fetch_catalog_keys(self): return {}
            def upsert_products(self, rows): raise supabase_client.SupabaseError("HTTP 500")
        orig = cloud_sync._client
        cloud_sync._client = lambda: Half()
        try:
            sent, failed = cloud_sync.push_all(self.db)
        finally:
            cloud_sync._client = orig
        self.assertEqual(sent, 0); self.assertGreaterEqual(failed, 1)
        ev = {r["event"] for r in self.db.system_log_query(component="cloud_sync")}
        self.assertIn("push_all_partial", ev)
        self.assertTrue(self.db.get_setting("cloud_last_error"))


if __name__ == "__main__":
    unittest.main()
