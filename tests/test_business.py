"""Pharmacy Enterprise — business-logic + security unittest suite (v6.2).

Stdlib unittest only, zero new dependencies. Run from the app root:

    py -m unittest discover -s tests -p "test_business.py" -v
    (on this Linux VM:  python3 -m unittest discover -s tests -p "test_business.py" -v)

or run everything (this suite + the legacy check-scripts) with:

    python3 tests/run_all.py

Coverage: FEFO, unit conversion (box/strip/pill), shift/drawer math,
credit limits, partial payments, PIN header-only auth, PWA routes,
cert resolution (certs/ first, root fallback).

The legacy suites tests/test_v57.py (v5.7 review, 34 groups) and
tests/test_v58.py (v5.8 staged deletion) cover the same areas in
check() style and are kept as-is — this file is the unittest
counterpart, not a claim that no tests existed before.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..")
sys.path.insert(0, os.path.abspath(APP))

from database import (DB, allowed_units, unit_price, units_for_qty,
                      units_per_box)  # noqa: E402

TODAY = date.today().isoformat()
PAST = (date.today() - timedelta(days=30)).isoformat()
FUT = (date.today() + timedelta(days=365)).isoformat()
FUT2 = (date.today() + timedelta(days=730)).isoformat()


def fresh_db():
    d = tempfile.mkdtemp(prefix="pe_test_")
    return DB(path=os.path.join(d, "pharmacy.db")), d


def mkdrug(db, sell=100.0, buy=50.0, strips=2, tabs=10, name="TestDrug"):
    did = db.add_drug({"trade_en": name, "trade_ar": "x", "scientific": "T",
                       "company": "X", "form": "Tabs", "strength": "500",
                       "category": "T", "strips_per_box": strips,
                       "tablets_per_strip": tabs, "buy_price": buy,
                       "sell_price": sell, "min_stock": 5, "barcode": ""})
    return db.get_drug(did)


def add_batch(db, drug_id, qty, expiry, buy_unit=1.0, batch_no="B"):
    db.conn.execute(
        "INSERT INTO batches (drug_id, batch_no, expiry, qty_units, "
        "buy_price_unit, created_at) VALUES (?,?,?,?,?,?)",
        (drug_id, batch_no, expiry, qty, buy_unit, "2026-01-01"))
    db.conn.commit()


def stock(db, drug_id):
    return db.conn.execute(
        "SELECT COALESCE(SUM(qty_units),0) FROM batches WHERE drug_id=?",
        (drug_id,)).fetchone()[0]


def batch_qty(db, drug_id, batch_no):
    row = db.conn.execute(
        "SELECT qty_units FROM batches WHERE drug_id=? AND batch_no=?",
        (drug_id, batch_no)).fetchone()
    return row[0] if row else None


def sale_items(db, drug, qty, unit="box"):
    return [{"drug": drug, "pack_level": unit, "qty_display": qty}]


class TestFEFO(unittest.TestCase):
    def test_expired_batch_never_sold(self):
        db, d = fresh_db()
        drug = mkdrug(db)
        add_batch(db, drug["id"], 100, PAST, batch_no="OLD")
        add_batch(db, drug["id"], 100, FUT, batch_no="GOOD")
        db.create_sale("admin", sale_items(db, drug, 1))
        self.assertEqual(batch_qty(db, drug["id"], "OLD"), 100)
        self.assertEqual(batch_qty(db, drug["id"], "GOOD"), 80)
        shutil.rmtree(d, ignore_errors=True)

    def test_earliest_expiry_first(self):
        db, d = fresh_db()
        drug = mkdrug(db)
        add_batch(db, drug["id"], 20, FUT2, batch_no="LATE")
        add_batch(db, drug["id"], 20, FUT, batch_no="SOON")
        db.create_sale("admin", sale_items(db, drug, 1))
        self.assertEqual(batch_qty(db, drug["id"], "SOON"), 0)
        self.assertEqual(batch_qty(db, drug["id"], "LATE"), 20)
        shutil.rmtree(d, ignore_errors=True)

    def test_dateless_batch_sold_last(self):
        db, d = fresh_db()
        drug = mkdrug(db)
        add_batch(db, drug["id"], 20, "", batch_no="NODATE")
        add_batch(db, drug["id"], 20, FUT, batch_no="DATED")
        db.create_sale("admin", sale_items(db, drug, 1))
        self.assertEqual(batch_qty(db, drug["id"], "DATED"), 0)
        self.assertEqual(batch_qty(db, drug["id"], "NODATE"), 20)
        shutil.rmtree(d, ignore_errors=True)

    def test_expired_only_sale_refused(self):
        db, d = fresh_db()
        drug = mkdrug(db)
        add_batch(db, drug["id"], 100, PAST, batch_no="OLD")
        with self.assertRaises(ValueError):
            db.create_sale("admin", sale_items(db, drug, 1))
        shutil.rmtree(d, ignore_errors=True)

    def test_sale_detail_merges_batch_splits_for_mobile_editing(self):
        db, d = fresh_db()
        drug = mkdrug(db, strips=1, tabs=1, sell=25.0)
        add_batch(db, drug["id"], 1, FUT, batch_no="FIRST")
        add_batch(db, drug["id"], 1, FUT2, batch_no="SECOND")
        sale_id, _, total, _ = db.create_sale(
            "admin", sale_items(db, drug, 2))
        self.assertEqual(total, 50.0)
        self.assertEqual(len(db.get_sale_items(sale_id)), 2)
        detail = db.sale_detail(sale_id)
        self.assertEqual(len(detail["items"]), 1)
        self.assertEqual(detail["items"][0]["qty_display"], 2.0)
        self.assertEqual(detail["items"][0]["qty_units"], 2)
        self.assertEqual(detail["items"][0]["line_total"], 50.0)
        shutil.rmtree(d, ignore_errors=True)


class TestUnitConversion(unittest.TestCase):
    def test_allowed_units_follow_pharmaceutical_form(self):
        self.assertEqual(allowed_units({"form": "Tablets"}),
                         ["box", "strip", "pill"])
        self.assertEqual(allowed_units({"form": "Suppository"}),
                         ["box", "pill"])
        self.assertEqual(allowed_units({"form": "كريم جلدي"}), ["box"])
        self.assertEqual(allowed_units({"form": "Unclassified form"}),
                         ["box", "strip", "pill"])

    def test_units_per_box(self):
        drug = {"strips_per_box": 2, "tablets_per_strip": 10}
        self.assertEqual(units_per_box(drug), 20)

    def test_unit_prices(self):
        drug = {"sell_price": 100.0, "strips_per_box": 2,
                "tablets_per_strip": 10}
        self.assertEqual(unit_price(drug, "box"), 100.0)
        self.assertEqual(unit_price(drug, "strip"), 50.0)
        self.assertEqual(unit_price(drug, "pill"), 5.0)

    def test_units_for_qty(self):
        drug = {"strips_per_box": 2, "tablets_per_strip": 10}
        self.assertEqual(units_for_qty(drug, "box", 1), 20)
        self.assertEqual(units_for_qty(drug, "strip", 1), 10)
        self.assertEqual(units_for_qty(drug, "pill", 3), 3)

    def test_strip_sale_deducts_tablets(self):
        db, d = fresh_db()
        drug = mkdrug(db)  # 2 strips x 10 = 20 units per box
        add_batch(db, drug["id"], 100, FUT)
        db.create_sale("admin", sale_items(db, drug, 1, "strip"))
        self.assertEqual(stock(db, drug["id"]), 90)
        shutil.rmtree(d, ignore_errors=True)

    def test_pill_sale_deducts_single_units(self):
        db, d = fresh_db()
        drug = mkdrug(db)
        add_batch(db, drug["id"], 100, FUT)
        db.create_sale("admin", sale_items(db, drug, 3, "pill"))
        self.assertEqual(stock(db, drug["id"]), 97)
        shutil.rmtree(d, ignore_errors=True)

    def test_fractional_pill_rejected(self):
        db, d = fresh_db()
        drug = mkdrug(db)
        add_batch(db, drug["id"], 100, FUT)
        with self.assertRaises(ValueError):
            db.create_sale("admin", sale_items(db, drug, 1.5, "pill"))
        self.assertEqual(stock(db, drug["id"]), 100)
        shutil.rmtree(d, ignore_errors=True)

    def test_single_unit_form_rejects_strip_sales(self):
        db, d = fresh_db()
        did = db.add_drug({"trade_en": "Cream", "form": "Cream",
                           "strips_per_box": 4, "tablets_per_strip": 10,
                           "buy_price": 10, "sell_price": 20,
                           "min_stock": 1})
        drug = db.get_drug(did)
        add_batch(db, did, 100, FUT)
        with self.assertRaisesRegex(ValueError, "غير متاحة"):
            db.create_sale("admin", sale_items(db, drug, 1, "strip"))
        shutil.rmtree(d, ignore_errors=True)


class TestMobileQrLink(unittest.TestCase):
    def test_qr_link_contains_pin_only_in_fragment(self):
        from main import qr_url_with_pin

        self.assertEqual(
            qr_url_with_pin("https://192.168.1.5:8443", "123456"),
            "https://192.168.1.5:8443/#pin=123456")
        self.assertEqual(
            qr_url_with_pin("https://192.168.1.5:8443/#old", "123456"),
            "https://192.168.1.5:8443/#pin=123456")
        self.assertEqual(
            qr_url_with_pin("https://192.168.1.5:8443/?pin=old&view=scan", "123456"),
            "https://192.168.1.5:8443/?view=scan#pin=123456")
        self.assertNotIn("pin=", qr_url_with_pin("http://127.0.0.1:8080", "bad"))


class TestShiftDrawer(unittest.TestCase):
    def _shift_with_sale(self, tmp):
        db, d = fresh_db()
        drug = mkdrug(db, sell=100.0, buy=50.0, strips=1, tabs=1)
        add_batch(db, drug["id"], 100, FUT)
        sid = db.open_shift("admin", 50.0)
        return db, d, drug, sid

    def test_expected_cash_opening_plus_sales_minus_expenses(self):
        db, d, drug, sid = self._shift_with_sale(None)
        db.create_sale("admin", sale_items(db, drug, 1),
                       payment_method="cash", paid=100.0, shift_id=sid)
        db.add_expense("electricity", 20.0, user="admin", shift_id=sid)
        summ = db.shift_summary(sid)
        self.assertEqual(summ["expected_cash"], 130.0)  # 50+100-20
        shutil.rmtree(d, ignore_errors=True)

    def test_card_sales_never_touch_drawer(self):
        db, d, drug, sid = self._shift_with_sale(None)
        db.create_sale("admin", sale_items(db, drug, 1),
                       payment_method="card", paid=100.0, shift_id=sid)
        summ = db.shift_summary(sid)
        self.assertEqual(summ["expected_cash"], 50.0)
        self.assertEqual(summ["card_total"], 100.0)
        shutil.rmtree(d, ignore_errors=True)

    def test_other_cashier_sale_does_not_leak(self):
        db, d, drug, sid = self._shift_with_sale(None)
        db.create_sale("admin", sale_items(db, drug, 1),
                       payment_method="cash", paid=100.0, shift_id=sid)
        sid2 = db.open_shift("cashier", 0.0)
        db.create_sale("cashier", sale_items(db, drug, 1),
                       payment_method="cash", paid=100.0, shift_id=sid2)
        self.assertEqual(db.shift_summary(sid)["expected_cash"], 150.0)
        shutil.rmtree(d, ignore_errors=True)

    def test_cash_refund_subtracts_from_drawer(self):
        db, d, drug, sid = self._shift_with_sale(None)
        db.create_sale("admin", sale_items(db, drug, 1),
                       payment_method="cash", paid=100.0, shift_id=sid)
        sale_id = db.conn.execute(
            "SELECT id FROM sales WHERE shift_id=? ORDER BY id DESC LIMIT 1",
            (sid,)).fetchone()["id"]
        db.return_sale(sale_id, "admin")
        self.assertEqual(db.shift_summary(sid)["expected_cash"], 50.0)
        shutil.rmtree(d, ignore_errors=True)

    def test_close_records_counted_vs_expected(self):
        db, d, drug, sid = self._shift_with_sale(None)
        db.create_sale("admin", sale_items(db, drug, 1),
                       payment_method="cash", paid=100.0, shift_id=sid)
        closed = db.close_shift(sid, 145.0)
        self.assertEqual(closed["counted_cash"], 145.0)
        self.assertEqual(closed["difference"], -5.0)  # expected 150
        shutil.rmtree(d, ignore_errors=True)

    def test_cash_sale_with_change_counts_net(self):
        db, d, drug, sid = self._shift_with_sale(None)
        db.create_sale("admin", sale_items(db, drug, 1),
                       payment_method="cash", paid=150.0, shift_id=sid)
        # paid 150, change 50 -> drawer gains only the 100 total
        self.assertEqual(db.shift_summary(sid)["expected_cash"], 150.0)
        shutil.rmtree(d, ignore_errors=True)


class TestCreditLimits(unittest.TestCase):
    def _credit_setup(self, limit):
        db, d = fresh_db()
        drug = mkdrug(db, sell=100.0, buy=50.0, strips=1, tabs=1)
        add_batch(db, drug["id"], 100, FUT)
        cid = db.add_customer("Cust", "0100", credit_limit=limit)
        return db, d, drug, cid

    def test_credit_over_limit_refused(self):
        db, d, drug, cid = self._credit_setup(50.0)
        with self.assertRaises(ValueError):
            db.create_sale("admin", sale_items(db, drug, 1),
                           payment_method="credit", customer_id=cid, paid=0)
        shutil.rmtree(d, ignore_errors=True)

    def test_credit_at_limit_allowed(self):
        db, d, drug, cid = self._credit_setup(100.0)
        db.create_sale("admin", sale_items(db, drug, 1),
                       payment_method="credit", customer_id=cid, paid=0)
        bal = db.conn.execute(
            "SELECT balance FROM customers WHERE id=?", (cid,)).fetchone()["balance"]
        self.assertEqual(bal, 100.0)
        shutil.rmtree(d, ignore_errors=True)

    def test_credit_without_customer_refused(self):
        db, d, drug, cid = self._credit_setup(0)
        with self.assertRaises(ValueError):
            db.create_sale("admin", sale_items(db, drug, 1),
                           payment_method="credit", customer_id=None, paid=0)
        shutil.rmtree(d, ignore_errors=True)

    def test_credit_limit_uses_unpaid_remainder(self):
        # limit 60, sale 100 with 50 paid -> remainder 50 fits; a
        # second identical sale would push the balance to 100 > 60.
        db, d, drug, cid = self._credit_setup(60.0)
        db.create_sale("admin", sale_items(db, drug, 1),
                       payment_method="credit", customer_id=cid, paid=50.0)
        with self.assertRaises(ValueError):
            db.create_sale("admin", sale_items(db, drug, 1),
                           payment_method="credit", customer_id=cid, paid=50.0)
        shutil.rmtree(d, ignore_errors=True)


class TestPartialPayments(unittest.TestCase):
    def _setup(self):
        db, d = fresh_db()
        drug = mkdrug(db, sell=100.0, buy=50.0, strips=1, tabs=1)
        add_batch(db, drug["id"], 100, FUT)
        cid = db.add_customer("Cust", "0100", credit_limit=1000.0)
        return db, d, drug, cid

    def _balance(self, db, cid):
        return db.conn.execute(
            "SELECT balance FROM customers WHERE id=?", (cid,)).fetchone()["balance"]

    def test_partial_payment_balance_is_total_minus_paid(self):
        db, d, drug, cid = self._setup()
        db.create_sale("admin", sale_items(db, drug, 1),
                       payment_method="credit", customer_id=cid, paid=40.0)
        self.assertEqual(self._balance(db, cid), 60.0)
        shutil.rmtree(d, ignore_errors=True)

    def test_full_payment_leaves_zero_balance(self):
        db, d, drug, cid = self._setup()
        db.create_sale("admin", sale_items(db, drug, 1),
                       payment_method="credit", customer_id=cid, paid=100.0)
        self.assertEqual(self._balance(db, cid), 0.0)
        shutil.rmtree(d, ignore_errors=True)

    def test_credit_overpayment_refused(self):
        db, d, drug, cid = self._setup()
        with self.assertRaises(ValueError):
            db.create_sale("admin", sale_items(db, drug, 1),
                           payment_method="credit", customer_id=cid, paid=150.0)
        shutil.rmtree(d, ignore_errors=True)

    def test_cash_underpayment_refused(self):
        db, d, drug, cid = self._setup()
        with self.assertRaises(ValueError):
            db.create_sale("admin", sale_items(db, drug, 1),
                           payment_method="cash", paid=50.0)
        shutil.rmtree(d, ignore_errors=True)

    def test_return_reverses_only_unpaid_credit(self):
        db, d, drug, cid = self._setup()
        sid, _, _, _ = db.create_sale(
            "admin", sale_items(db, drug, 1),
            payment_method="credit", customer_id=cid, paid=20.0)
        self.assertEqual(self._balance(db, cid), 80.0)
        db.return_sale(sid, "admin")
        self.assertEqual(self._balance(db, cid), 0.0)
        shutil.rmtree(d, ignore_errors=True)


class TestCertResolution(unittest.TestCase):
    """v6.2: certs/ first, root pair as fallback for existing installs."""

    def test_prefers_certs_dir(self):
        import mobile_server
        base = tempfile.mkdtemp(prefix="pe_cert_")
        try:
            root_cert = os.path.join(APP, "cert.pem")
            root_key = os.path.join(APP, "key.pem")
            certs_dir = os.path.join(base, "certs")
            os.makedirs(certs_dir)
            shutil.copy(root_cert, os.path.join(certs_dir, "cert.pem"))
            shutil.copy(root_key, os.path.join(certs_dir, "key.pem"))
            # point the module at the scratch base
            old_base, old_dir = mobile_server.BASE, mobile_server.CERT_DIR
            old_cert, old_key = mobile_server.CERT_FILE, mobile_server.KEY_FILE
            mobile_server.BASE = base
            mobile_server.CERT_DIR = certs_dir
            mobile_server.CERT_FILE = os.path.join(base, "cert.pem")
            mobile_server.KEY_FILE = os.path.join(base, "key.pem")
            try:
                cert, key = mobile_server.resolve_cert_files()
                self.assertEqual(cert, os.path.join(certs_dir, "cert.pem"))
                self.assertEqual(key, os.path.join(certs_dir, "key.pem"))
                self.assertTrue(mobile_server.cert_files_exist())
            finally:
                mobile_server.BASE = old_base
                mobile_server.CERT_DIR = old_dir
                mobile_server.CERT_FILE = old_cert
                mobile_server.KEY_FILE = old_key
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_falls_back_to_root_pair(self):
        import mobile_server
        base = tempfile.mkdtemp(prefix="pe_cert_")
        try:
            shutil.copy(os.path.join(APP, "cert.pem"),
                        os.path.join(base, "cert.pem"))
            shutil.copy(os.path.join(APP, "key.pem"),
                        os.path.join(base, "key.pem"))
            old_base, old_dir = mobile_server.BASE, mobile_server.CERT_DIR
            old_cert, old_key = mobile_server.CERT_FILE, mobile_server.KEY_FILE
            mobile_server.BASE = base
            mobile_server.CERT_DIR = os.path.join(base, "certs")
            mobile_server.CERT_FILE = os.path.join(base, "cert.pem")
            mobile_server.KEY_FILE = os.path.join(base, "key.pem")
            try:
                cert, key = mobile_server.resolve_cert_files()
                self.assertEqual(cert, os.path.join(base, "cert.pem"))
                self.assertTrue(mobile_server.cert_files_exist())
            finally:
                mobile_server.BASE = old_base
                mobile_server.CERT_DIR = old_dir
                mobile_server.CERT_FILE = old_cert
                mobile_server.KEY_FILE = old_key
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_regenerate_writes_into_certs_dir(self):
        import mobile_server
        base = tempfile.mkdtemp(prefix="pe_cert_")
        try:
            ok, msg = mobile_server.regenerate_cert(
                ["127.0.0.1", "192.168.1.99"], base)
            self.assertTrue(ok, msg)
            self.assertTrue(os.path.isfile(
                os.path.join(base, "certs", "cert.pem")))
            self.assertTrue(os.path.isfile(
                os.path.join(base, "certs", "key.pem")))
            # no cert files leaked into the base root
            self.assertFalse(os.path.isfile(os.path.join(base, "cert.pem")))
            sans = mobile_server.cert_san_ips(
                os.path.join(base, "certs", "cert.pem"))
            self.assertIn("192.168.1.99", sans)
            self.assertIn("127.0.0.1", sans)
        finally:
            shutil.rmtree(base, ignore_errors=True)


class TestPinHeaderOnlyAndPWA(unittest.TestCase):
    """v6.2: PIN travels in X-Mobile-PIN only; PWA shell is served."""

    @classmethod
    def setUpClass(cls):
        # isolated server copy so cert regeneration can never touch
        # the app sources (same pattern as tests/test_server_v57.py).
        # Loaded as its own module ("srv_mobile_server") so its BASE
        # is the scratch dir even though the app-root mobile_server
        # may already be imported by another test class.
        import importlib.util
        cls.work = tempfile.mkdtemp(prefix="pe_srv_")
        for f in ("database.py", "mobile_server.py", "mobile.html",
                  "zxing.min.js", "manifest.json", "sw.js",
                  "icon-192.png", "icon-512.png", "cert.pem", "key.pem"):
            shutil.copy(os.path.join(APP, f), os.path.join(cls.work, f))
        spec = importlib.util.spec_from_file_location(
            "srv_mobile_server",
            os.path.join(cls.work, "mobile_server.py"))
        srvmod = importlib.util.module_from_spec(spec)
        sys.modules["srv_mobile_server"] = srvmod
        spec.loader.exec_module(srvmod)
        cls.srvmod = srvmod
        db_path = os.path.join(cls.work, "pharmacy.db")
        db = DB(path=db_path)
        cls.pin = db.ensure_mobile_pin()
        did = db.add_drug({"trade_en": "SrvDrug", "trade_ar": "x",
                           "scientific": "T", "company": "X",
                           "form": "Tabs", "strength": "500",
                           "category": "T", "strips_per_box": 1,
                           "tablets_per_strip": 1, "buy_price": 40.0,
                           "sell_price": 60.0, "min_stock": 5,
                           "barcode": ""})
        db.conn.execute(
            "INSERT INTO batches (drug_id, batch_no, expiry, qty_units,"
            " buy_price_unit, created_at) VALUES (?,?,?,?,?,?)",
            (did, "B1", "2030-01-01", 100, 40.0, "2026-01-01"))
        db.conn.commit()
        cls.drug_id = did
        db.close()
        cls.srv = srvmod.MobileServer(db_path=db_path,
                                      port=18082, https_port=18445)
        assert cls.srv.start(), cls.srv.start_error
        cls.base = "http://127.0.0.1:18082"
        cls.https_base = "https://127.0.0.1:18445"

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        sys.modules.pop("srv_mobile_server", None)
        shutil.rmtree(cls.work, ignore_errors=True)

    def _get(self, path, headers=None):
        req = urllib.request.Request(self.base + path,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read(), resp.headers.get_content_type()
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get_content_type()

    def test_query_string_pin_rejected(self):
        st, _, _ = self._get("/api/drugs?pin=%s" % self.pin)
        self.assertEqual(st, 401)

    def test_header_pin_accepted(self):
        st, body, _ = self._get("/api/drugs",
                                {"X-Mobile-PIN": self.pin})
        self.assertEqual(st, 200)
        self.assertIn("SrvDrug", body.decode("utf-8"))

    def test_live_endpoint_returns_only_requested_cart_drugs(self):
        st, body, _ = self._get(
            "/api/live?ids=%s" % self.drug_id,
            {"X-Mobile-PIN": self.pin})
        self.assertEqual(st, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual([d["id"] for d in data["drugs"]], [self.drug_id])

    def test_wrong_header_pin_rejected(self):
        st, _, _ = self._get("/api/drugs", {"X-Mobile-PIN": "000000"})
        self.assertEqual(st, 401)

    def test_no_pin_rejected(self):
        st, _, _ = self._get("/api/drugs")
        self.assertEqual(st, 401)

    def test_security_headers_are_present(self):
        req = urllib.request.Request(self.base + "/")
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(resp.headers.get("Referrer-Policy"), "no-referrer")
            self.assertEqual(resp.headers.get("Permissions-Policy"), "camera=(self)")
            self.assertIn("frame-ancestors 'none'", resp.headers.get("Content-Security-Policy", ""))

    def test_options_does_not_enable_wildcard_cors(self):
        req = urllib.request.Request(self.base + "/", method="OPTIONS")
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertIsNone(resp.headers.get("Access-Control-Allow-Origin"))

    def test_manifest_served(self):
        st, body, ctype = self._get("/manifest.json")
        self.assertEqual(st, 200)
        self.assertIn("manifest", ctype)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["display"], "standalone")
        self.assertTrue(any(i["sizes"] == "512x512"
                            for i in data["icons"]))

    def test_sw_served_and_never_caches_api(self):
        st, body, ctype = self._get("/sw.js")
        self.assertEqual(st, 200)
        self.assertIn("javascript", ctype)
        text = body.decode("utf-8")
        self.assertIn("/api/", text)  # the network-only guard
        self.assertIn("caches.open", text)

    def test_icons_served(self):
        for path in ("/icon-192.png", "/icon-512.png"):
            st, body, ctype = self._get(path)
            self.assertEqual(st, 200)
            self.assertIn("png", ctype)
            self.assertTrue(body.startswith(b"\x89PNG"))

    def test_https_up(self):
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(self.https_base + "/")
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            self.assertEqual(resp.status, 200)

    def test_mobile_html_links_manifest(self):
        with open(os.path.join(APP, "mobile.html"),
                  encoding="utf-8") as f:
            html = f.read()
        self.assertIn('rel="manifest" href="/manifest.json"', html)
        self.assertIn("serviceWorker", html)
        self.assertIn("openSecureScanner", html)
        self.assertIn("secureLinkBtn", html)
        self.assertIn("location.pathname+location.hash", html)
        self.assertIn("const SCAN_NATIVE_INTERVAL=80", html)
        self.assertIn("const SCAN_ZXING_INTERVAL=250", html)
        self.assertIn("const SCAN_COOLDOWN=350", html)
        self.assertIn("bdBusy", html)
        self.assertIn("inv.paid == null ? inv.total : inv.paid", html)
        self.assertNotIn("?pin=", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
