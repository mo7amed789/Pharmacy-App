"""Email reports against a LOCAL fake SMTP server (127.0.0.1, self-made certificate). No real mail."""
import base64
import json
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest

import email_report as ER
import remote_monitor as RM
from database import DB


class FakeSMTP:
    def __init__(self, certfile, keyfile, tls=True, starttls=False):
        self.mails, self.logins, self.plain_seen = [], [], False
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(certfile, keyfile)
        self.tls, self.starttls = tls, starttls
        self.sock = socket.socket(); self.sock.bind(("127.0.0.1", 0)); self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.alive = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.alive:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        try:
            if self.tls and not self.starttls:
                c = self.ctx.wrap_socket(c, server_side=True)
            f = c.makefile("rwb", buffering=0)
            w = lambda s: f.write((s + "\r\n").encode())
            w("220 fake")
            data, body = False, []
            while True:
                line = f.readline()
                if not line:
                    return
                t = line.decode(errors="replace").rstrip("\r\n")
                if data:
                    if t == ".":
                        self.mails.append("\n".join(body)); data = False; w("250 ok")
                    else:
                        body.append(t)
                    continue
                u = t.upper()
                if u.startswith("EHLO"):
                    w("250-fake"); w("250-AUTH PLAIN" if (not self.starttls or isinstance(c, ssl.SSLSocket) or not self.tls) else "250-STARTTLS"); w("250 8BITMIME") if False else w("250 OK")
                elif u == "STARTTLS" and self.starttls and self.tls:
                    w("220 go"); c = self.ctx.wrap_socket(c, server_side=True); f = c.makefile("rwb", buffering=0)
                    w = lambda s: f.write((s + "\r\n").encode())
                elif u.startswith("AUTH PLAIN"):
                    self.logins.append(base64.b64decode(t.split()[2]).split(b"\0")[1:]); w("235 ok")
                elif u.startswith(("MAIL", "RCPT")):
                    w("250 ok")
                elif u == "DATA":
                    data = True; body = []; w("354 go")
                elif u == "QUIT":
                    w("221 bye"); return
                else:
                    w("250 ok")
        except Exception:
            pass

    def close(self):
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class EmailReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.cert, cls.key = os.path.join(cls.dir, "c.pem"), os.path.join(cls.dir, "k.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", cls.key, "-out", cls.cert,
                        "-days", "2", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                       check=True, capture_output=True)
        cls.ctx = ssl.create_default_context(cafile=cls.cert)   # the test trusts ONLY its own cert

    def setUp(self):
        d = tempfile.mkdtemp()
        self.db = DB(path=os.path.join(d, "t.db"))
        self.db.create_user("boss", "S3cretPass!", "admin"); self.db.set_actor("boss", "desktop")
        self.srv = FakeSMTP(self.cert, self.key)
        self.cfgfile = os.path.join(d, "remote_monitor.json")
        self.write_cfg("ssl", self.srv.port)
        self._o = RM.config_path; RM.config_path = lambda: self.cfgfile
        self._p, self._u = ER._PROTECT, ER._UNPROTECT
        ER._PROTECT = lambda b: b"ENC:" + base64.b64encode(b[::-1]); ER._PROTECT.testing = True
        ER._UNPROTECT = lambda b: base64.b64decode(b[4:])[::-1]
        ER.store_secret(self.db, "SMTP-SECRET-KEY-123")
        RM.enable(self.db)

    def write_cfg(self, mode, port):
        json.dump({"url": "https://x.supabase.co", "anon_key": "k", "email": "e@x", "password": "p",
                   "mail_report": {"host": "localhost", "port": port, "mode": mode, "username": "resend",
                             "sender": "onboarding@resend.dev", "to": "owner@example.com"}}, open(self.cfgfile, "w"))

    def tearDown(self):
        RM.config_path = self._o; ER._PROTECT, ER._UNPROTECT = self._p, self._u; self.srv.close()

    def test_secret_is_not_in_config_db_or_state_in_clear(self):
        blob = open(ER._secret_path(self.db)).read()
        self.assertNotIn("SMTP-SECRET-KEY-123", blob)
        self.assertNotIn("SMTP-SECRET", open(self.cfgfile).read())
        self.assertNotIn("SMTP-SECRET", open(RM._state_path(self.db)).read())
        self.assertEqual(ER.load_secret(self.db), "SMTP-SECRET-KEY-123")

    def test_daily_sends_over_verified_tls_with_summary_only_content(self):
        self.db.audit("boss", "edit_drug", "price password=Hunter2", before={"sell_price": 10, "customer": "Ahmed"}, after={"sell_price": 12})
        self.db.syslog("error", "mobile", "http_500", "POST /x token=ABCSECRET")
        sent = ER.tick(self.db, now=__import__("time").time() + 7 * 3600, context=self.ctx)
        self.assertEqual(len(sent), 1)
        text = "\n".join(self.srv.mails)
        self.assertIn("edit_drug", text); self.assertIn("http_500", text)
        for banned in ("Hunter2", "Ahmed", "ABCSECRET", "sell_price", "SMTP-SECRET"):
            self.assertNotIn(banned, text)
        self.assertEqual(self.srv.logins[0][1], b"SMTP-SECRET-KEY-123")

    def test_untrusted_certificate_is_rejected_no_mail(self):
        sent = ER.tick(self.db, now=__import__("time").time() + 7 * 3600)  # default trust store: self-made cert not trusted
        self.assertEqual(sent, []); self.assertEqual(self.srv.mails, [])
        self.assertTrue(RM.load_state(self.db).get("em_last_err"))

    def test_no_plaintext_fallback(self):
        plain = FakeSMTP(self.cert, self.key, tls=False)
        self.write_cfg("ssl", plain.port)
        sent = ER.tick(self.db, now=__import__("time").time() + 7 * 3600, context=self.ctx)
        self.assertEqual(sent, []); self.assertEqual(plain.mails, []); self.assertEqual(plain.logins, [])
        self.write_cfg("starttls", plain.port)   # server offers no STARTTLS: must refuse, not log in in clear
        sent = ER.tick(self.db, now=__import__("time").time() + 7 * 3600, context=self.ctx)
        self.assertEqual(plain.logins, []); plain.close()

    def test_starttls_mode_works(self):
        st = FakeSMTP(self.cert, self.key, tls=True, starttls=True)
        self.write_cfg("starttls", st.port)
        ER.send_mail(ER.load_email_cfg(), "SMTP-SECRET-KEY-123", "s", "b", self.ctx)
        self.assertEqual(len(st.mails), 1); st.close()

    def test_one_combined_report_every_6_hours_no_separate_alerts(self):
        import time
        t0 = time.time()
        self.db.syslog("error", "mobile", "e1", "a")
        self.assertEqual(ER.tick(self.db, now=t0 + 3600, context=self.ctx), [])         # before 6h: nothing, even with an error
        self.assertEqual(len(ER.tick(self.db, now=t0 + 6 * 3600 + 5, context=self.ctx)), 1)
        self.assertEqual(ER.tick(self.db, now=t0 + 6 * 3600 + 600, context=self.ctx), [])  # not repeated
        self.db.audit("boss", "sale", "x")
        self.assertEqual(ER.tick(self.db, now=t0 + 11 * 3600, context=self.ctx), [])
        self.assertEqual(len(ER.tick(self.db, now=t0 + 12 * 3600 + 10, context=self.ctx)), 1)
        self.assertEqual(len(self.srv.mails), 2)
        self.assertIn("e1", self.srv.mails[0]); self.assertNotIn("e1", self.srv.mails[1]); self.assertIn("sale", self.srv.mails[1])

    def test_offline_keeps_cursors_then_sends_missed_events(self):
        import time
        self.srv.close()
        self.db.audit("boss", "sale", "x")
        t = time.time() + 7 * 3600
        self.assertEqual(ER.tick(self.db, now=t, context=self.ctx), [])
        self.srv = FakeSMTP(self.cert, self.key); self.write_cfg("ssl", self.srv.port)
        self.assertEqual(len(ER.tick(self.db, now=t + 60, context=self.ctx)), 1)
        self.assertIn("sale", "\n".join(self.srv.mails))

    def test_off_when_monitoring_not_enabled_or_no_secret(self):
        import time
        os.remove(ER._secret_path(self.db))
        self.assertEqual(ER.tick(self.db, now=time.time() + 7 * 3600, context=self.ctx), [])
        ER.store_secret(self.db, "x"); RM.disable(self.db)
        self.assertEqual(ER.tick(self.db, now=time.time() + 7 * 3600, context=self.ctx), [])
        self.assertEqual(self.srv.mails, [])

    def test_no_recursive_log_growth_on_repeated_failures(self):
        import time
        self.srv.close()
        for i in range(20):
            ER.tick(self.db, now=time.time() + 7 * 3600 + i, context=self.ctx)
        n = [r for r in self.db.system_log_query(component="cloud_sync") if r["event"] == "email_report_failed"]
        self.assertEqual(len(n), 1)

    def test_restore_does_not_lose_new_events(self):
        import time
        for i in range(4):
            self.db.audit("boss", "old%d" % i, "x")
        t = time.time() + 7 * 3600
        ER.tick(self.db, now=t, context=self.ctx)
        self.db.conn.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_delete")
        self.db.conn.execute("DELETE FROM audit_log"); self.db.conn.execute("DELETE FROM sqlite_sequence WHERE name='audit_log'")
        ts = RM.load_state(self.db)["em_a_ts"]
        self.db.conn.execute("INSERT INTO audit_log (created_at,user,action,details) VALUES (?,?,?,?)", (ts, "boss", "after_restore", ""))
        self.db.conn.commit()
        ER.tick(self.db, now=t + 7 * 3600, context=self.ctx)
        self.assertIn("after_restore", "\n".join(self.srv.mails))


if __name__ == "__main__":
    unittest.main()
