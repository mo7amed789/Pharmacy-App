"""Owner remote monitoring against a LOCAL fake Supabase (127.0.0.1). No real network."""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import remote_monitor as RM
from database import DB


class Fake:
    def __init__(self):
        self.reqs, self.rows, self.fail, self.logins = [], [], False, 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"null")
                outer.reqs.append((self.path, dict(self.headers), body))
                if self.path.startswith("/auth/v1/token"):
                    outer.logins += 1
                    return self._send(200, {"access_token": "devtoken"})
                if outer.fail:
                    return self._send(503, {})
                if self.headers.get("Authorization") != "Bearer devtoken":
                    return self._send(401, {})
                for e in body:
                    if not any((r["device_id"], r.get("generation"), r["kind"], r["src_id"]) == (e["device_id"], e.get("generation"), e["kind"], e["src_id"]) for r in outer.rows):
                        outer.rows.append(e)
                self._send(201, None)

            def _send(self, code, obj):
                data = json.dumps(obj).encode() if obj is not None else b""
                self.send_response(code); self.send_header("Content-Length", str(len(data))); self.end_headers()
                self.wfile.write(data)
        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_port
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


class RemoteMonitor(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = DB(path=os.path.join(self.dir, "t.db"))
        self.db.create_user("boss", "S3cretPass!", "admin")
        self.db.set_actor("boss", "desktop")
        self.fake = Fake()
        self.cfgfile = os.path.join(self.dir, "remote_monitor.json")
        with open(self.cfgfile, "w") as f:
            json.dump({"url": self.fake.url, "anon_key": "pk", "email": "dev@x.io", "password": "DevPassw0rd!"}, f)
        self._orig = RM.config_path
        RM.config_path = lambda: self.cfgfile

    def tearDown(self):
        RM.config_path = self._orig
        self.fake.close()

    def test_off_by_default_sends_nothing_even_with_config(self):
        self.db.audit("boss", "login", "x")
        self.assertIsNone(RM.sync_once(self.db))
        self.assertEqual(self.fake.reqs, [])

    def test_not_configured_sends_nothing(self):
        os.remove(self.cfgfile)
        RM.enable(self.db)
        self.assertIsNone(RM.sync_once(self.db))
        self.assertEqual(self.fake.reqs, [])

    def test_forward_only_and_summary_has_no_details_or_secrets(self):
        self.db.audit("boss", "old_event", "BEFORE ENABLE")
        RM.enable(self.db, "summary")
        self.db.audit("boss", "edit_drug", "drug 1 price password=Hunter2 note",
                      before={"sell_price": 10, "customer": "Ahmed"}, after={"sell_price": 12}, entity="drug", entity_id=1)
        self.db.syslog("error", "mobile", "http_500", "POST /api/x token=ABCSECRET", "Traceback ... apikey=ZZSECRET")
        n = RM.sync_once(self.db, version="6.30")
        self.assertGreaterEqual(n, 2)
        dump = json.dumps(self.fake.rows)
        self.assertNotIn("old_event", dump)
        self.assertNotIn("BEFORE ENABLE", dump)
        self.assertIn("edit_drug", dump)
        for banned in ("Hunter2", "Ahmed", "ABCSECRET", "ZZSECRET", "DevPassw0rd", "price"):
            self.assertNotIn(banned, dump)
        kinds = {r["kind"] for r in self.fake.rows}
        self.assertEqual(kinds, {"activity", "system", "heartbeat"})
        # the device password was only ever sent to the sign-in call
        for path, _h, body in self.fake.reqs:
            if not path.startswith("/auth/v1/token"):
                self.assertNotIn("DevPassw0rd", json.dumps(body))

    def test_full_level_adds_details_but_still_redacts(self):
        RM.enable(self.db, "full")
        self.db.audit("boss", "edit_drug", "pw=1 password=Hunter2", before={"a": 1}, after={"a": 2}, entity="drug", entity_id=1)
        RM.sync_once(self.db)
        dump = json.dumps(self.fake.rows)
        self.assertIn('"before"', dump)
        self.assertNotIn("Hunter2", dump)

    def test_failure_keeps_cursor_logs_once_and_retries_without_duplicates(self):
        RM.enable(self.db)
        self.db.audit("boss", "sale", "INV-1", entity="sale", entity_id=1)
        self.fake.fail = True
        self.assertIsNone(RM.sync_once(self.db))
        self.assertIsNone(RM.sync_once(self.db))
        self.assertEqual(len([r for r in self.fake.rows if r["kind"] == "activity"]), 0)
        logs = self.db.system_log_query(component="cloud_sync")
        self.assertEqual(len([r for r in logs if r["event"] == "remote_monitor_failed"]), 1)
        self.assertTrue(RM.load_state(self.db).get("last_err"))
        self.fake.fail = False
        self.assertGreaterEqual(RM.sync_once(self.db), 1)
        self.assertEqual(len([r for r in self.fake.rows if r["kind"] == "activity" and r["payload"]["action"] == "sale"]), 1)
        before = len(self.fake.rows)
        RM.sync_once(self.db)  # nothing new except a heartbeat
        self.assertEqual(len([r for r in self.fake.rows if r["kind"] != "heartbeat"]), before - len([r for r in self.fake.rows if r["kind"] == "heartbeat"]))

    def test_offline_never_raises(self):
        RM.enable(self.db)
        self.fake.close()
        self.db.audit("boss", "sale", "x")
        self.assertIsNone(RM.sync_once(self.db))  # connection refused
        self.fake = Fake()  # for tearDown

    def test_preview_sends_nothing_and_shows_destination_and_sample(self):
        self.db.audit("boss", "sale", "INV-1", entity="sale", entity_id=1)
        pv = RM.preview(self.db, "summary")
        self.assertIn("127.0.0.1", pv["destination"])
        self.assertTrue(pv["sample"])
        self.assertFalse(pv["history_sent"])
        self.assertEqual(self.fake.reqs, [])
        self.assertFalse(RM.is_enabled(self.db))

    def test_heartbeat_exposes_log_counters_for_gap_detection(self):
        RM.enable(self.db)
        RM.sync_once(self.db, version="v")
        hb = [r for r in self.fake.rows if r["kind"] == "heartbeat"][0]["payload"]
        for k in ("audit_max_id", "audit_count", "unsent_activity", "app_version"):
            self.assertIn(k, hb)

    def test_enable_and_disable_are_themselves_logged(self):
        RM.enable(self.db); RM.disable(self.db)
        acts = [r[0] for r in self.db.conn.execute("SELECT action FROM audit_log")]
        self.assertIn("remote_monitor_on", acts); self.assertIn("remote_monitor_off", acts)
        self.assertFalse(RM.is_enabled(self.db))

    # ---- restore / reset handling ----
    def _acts(self):
        return [r["payload"]["action"] for r in self.fake.rows if r["kind"] == "activity"]

    def test_restore_of_older_db_uploads_new_events_under_new_generation(self):
        RM.enable(self.db)
        for i in range(5):
            self.db.audit("boss", "sale_%d" % i, "x")
        RM.sync_once(self.db)
        g1 = RM.load_state(self.db)["generation"]
        # simulate restore: wipe log rows so ids restart lower than the cursor
        self.db.conn.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_delete")
        self.db.conn.execute("DELETE FROM audit_log"); self.db.conn.execute("DELETE FROM sqlite_sequence WHERE name='audit_log'")
        self.db.conn.commit()
        import time; time.sleep(1.2)
        self.db.audit("boss", "after_restore", "x")
        RM.sync_once(self.db)
        st = RM.load_state(self.db)
        self.assertNotEqual(st["generation"], g1)
        self.assertIn("after_restore", self._acts())
        self.assertEqual(st["enabled"], 1)  # restore does not turn monitoring off
        self.assertTrue([r for r in self.db.system_log_query(component="remote_monitor") if r["event"] == "generation_change"])

    def test_restore_event_in_same_second_as_last_upload_is_not_lost(self):
        RM.enable(self.db)
        for i in range(3):
            self.db.audit("boss", "old_%d" % i, "x")
        RM.sync_once(self.db)
        self.db.conn.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_delete")
        self.db.conn.execute("DELETE FROM audit_log"); self.db.conn.execute("DELETE FROM sqlite_sequence WHERE name='audit_log'")
        # same created_at second as the last uploaded event, lower id than the cursor
        self.db.conn.commit()
        ts = RM.load_state(self.db)["a_ts"]
        self.db.conn.execute("INSERT INTO audit_log (created_at,user,action,details) VALUES (?,?,?,?)", (ts, "boss", "same_second", ""))
        self.db.conn.commit()
        RM.sync_once(self.db)
        self.assertIn("same_second", self._acts())

    def test_reused_ids_with_same_max_id_detected_by_fingerprint(self):
        RM.enable(self.db)
        self.db.audit("boss", "orig", "x")
        RM.sync_once(self.db)
        g1 = RM.load_state(self.db)["generation"]
        self.db.conn.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update")
        self.db.conn.execute("UPDATE audit_log SET action='other_history', user='someone' WHERE action='orig'")
        self.db.conn.commit()
        RM.sync_once(self.db)
        self.assertNotEqual(RM.load_state(self.db)["generation"], g1)

    def test_normal_use_keeps_one_generation(self):
        RM.enable(self.db)
        g1 = RM.load_state(self.db)["generation"]
        for i in range(3):
            self.db.audit("boss", "a%d" % i, "x"); RM.sync_once(self.db)
        self.assertEqual(RM.load_state(self.db)["generation"], g1)
        self.assertEqual(len(self.fake.rows and [r for r in self.fake.rows if r["kind"] == "activity" and r["payload"]["action"].startswith("a")]), 3)

    def test_lost_sidecar_means_off_and_sends_nothing(self):
        RM.enable(self.db)
        os.remove(RM._state_path(self.db))
        self.db.audit("boss", "x", "y")
        self.assertIsNone(RM.sync_once(self.db))
        self.assertFalse(RM.is_enabled(self.db))

    def test_events_carry_generation_and_no_client_owner_field(self):
        RM.enable(self.db)
        self.db.audit("boss", "sale", "x")
        RM.sync_once(self.db)
        for r in self.fake.rows:
            self.assertTrue(r["generation"])
            self.assertNotIn("device_uid", r)
            self.assertNotIn("user_id", r)

    def test_no_recursive_log_growth(self):
        RM.enable(self.db)
        self.db.audit("boss", "sale", "x")
        self.fake.fail = True
        for _ in range(20):
            RM.sync_once(self.db)
        n_fail = len([r for r in self.db.system_log_query(component="cloud_sync") if r["event"] == "remote_monitor_failed"])
        self.assertEqual(n_fail, 1)
        self.fake.fail = False
        RM.sync_once(self.db)
        c1 = self.db.conn.execute("SELECT COUNT(*) FROM system_log").fetchone()[0]
        for _ in range(5):
            RM.sync_once(self.db)
        c2 = self.db.conn.execute("SELECT COUNT(*) FROM system_log").fetchone()[0]
        self.assertEqual(c1, c2)

    def test_secrets_not_in_database_or_payloads(self):
        RM.enable(self.db)
        self.db.audit("boss", "sale", "x")
        RM.sync_once(self.db)
        dump = "\n".join(str(tuple(r)) for t in ("audit_log", "system_log", "settings")
                         for r in self.db.conn.execute("SELECT * FROM %s" % t))
        for secret in ("DevPassw0rd", "anon_key", "pk\x27"):
            self.assertNotIn(secret, dump)
        self.assertNotIn("DevPassw0rd", json.dumps(self.fake.rows))
        self.assertNotIn("DevPassw0rd", open(RM._state_path(self.db)).read())


if __name__ == "__main__":
    unittest.main()
