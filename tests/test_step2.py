"""STEP2 audit-fix verification — Accounting, Shifts & Purchase Returns.

Covers 2A (mobile sales bound to the active shift; no-shift sales
visible), 2B (returns attributed to the RETURNING shift; original
shift unchanged; legacy backfill) and 2C (purchase returns).
Stdlib unittest only. Run:  python3 tests/test_step2.py
Exit 0 only if ALL tests pass. Uses throwaway DBs under tests/dbs/.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # the isolated step2 copy
sys.path.insert(0, ROOT)

from database import DB, _today  # noqa: E402

TODAY = date.today().isoformat()
PAST = (date.today() - timedelta(days=30)).isoformat()
FUT = (date.today() + timedelta(days=365)).isoformat()
FUT2 = (date.today() + timedelta(days=730)).isoformat()


def mkdrug(db, sell=100.0, buy=20.0, strips=2, tabs=10, name="Step2Drug"):
    did = db.add_drug({"trade_en": name, "trade_ar": "اختبار", "scientific": "T",
                       "company": "X", "form": "Tabs", "strength": "500",
                       "category": "Test", "strips_per_box": strips,
                       "tablets_per_strip": tabs, "buy_price": buy,
                       "sell_price": sell, "min_stock": 0, "barcode": ""})
    return db.get_drug(did)


def add_batch(db, drug_id, qty_units, expiry, buy_unit=1.0, batch_no="B",
              supplier_id=None):
    db.conn.execute(
        "INSERT INTO batches (drug_id, batch_no, expiry, qty_units, "
        "buy_price_unit, supplier_id, created_at) VALUES (?,?,?,?,?,?,?)",
        (drug_id, batch_no, expiry, qty_units, buy_unit, supplier_id, "2026-01-01"))
    db.conn.commit()
    return db.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def cash_sale(db, drug, qty=1, unit="box", shift_id=None, cashier="admin"):
    return db.create_sale(cashier, [{"drug": drug, "pack_level": unit,
                                     "qty_display": qty}],
                          payment_method="cash", shift_id=shift_id, source="pc")


class Step2Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="step2_")
        self.db = DB(path=os.path.join(self.tmp, "pharmacy.db"))

    def tearDown(self):
        try:
            self.db.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- 2A ----------
    def test_active_shift_id_none_when_no_shift_open(self):
        self.assertIsNone(self.db.active_shift_id())

    def test_active_shift_id_returns_open_shift(self):
        sid = self.db.open_shift("admin", 50.0)
        self.assertEqual(self.db.active_shift_id(), sid)
        self.db.close_shift(sid, 50.0)
        self.assertIsNone(self.db.active_shift_id())

    def test_mobile_style_sale_bound_to_active_shift(self):
        sid = self.db.open_shift("admin", 0.0)
        drug = mkdrug(self.db)
        add_batch(self.db, drug["id"], 100, FUT, buy_unit=1.0)
        # what the mobile server now does: shift_id=db.active_shift_id()
        sale_id, inv, total, _chg = self.db.create_sale_from_items(
            "mobile", [{"drug_id": drug["id"], "unit": "box", "qty": 1}],
            payment_method="cash", shift_id=self.db.active_shift_id(),
            source="mobile", client_ref="step2-a")
        sale = self.db.get_sale(sale_id)
        self.assertEqual(sale["shift_id"], sid)
        self.assertEqual(self.db.shift_summary(sid)["cash_collected"], 100.0)

    def test_no_open_shift_sale_shows_in_no_shift_line(self):
        drug = mkdrug(self.db)
        add_batch(self.db, drug["id"], 100, FUT, buy_unit=1.0)
        cash_sale(self.db, drug, shift_id=None)  # PC or mobile, no shift open
        self.assertEqual(len(self.db.sales_without_shift()), 1)
        sid = self.db.open_shift("admin", 0.0)
        summ = self.db.shift_summary(sid)
        self.assertEqual(summ["no_shift_count"], 1)
        self.assertEqual(summ["no_shift_total"], 100.0)
        # the no-shift sale is reported, NOT counted in this drawer
        self.assertEqual(summ["expected_cash"], 0.0)
        self.assertEqual(summ["cash_collected"], 0.0)

    def test_mobile_http_invoice_bound_to_active_shift(self):
        """End-to-end 2A through the real HTTP API (isolated server copy)."""
        import importlib.util
        work = os.path.join(self.tmp, "srv")
        os.makedirs(work)
        for f in ("database.py", "mobile_server.py", "mobile.html", "zxing.min.js"):
            shutil.copy(os.path.join(ROOT, f), os.path.join(work, f))
        # load the COPIED mobile_server so its BASE (cert files) is the
        # temp dir — cert regeneration can never touch the step2 copy.
        spec = importlib.util.spec_from_file_location(
            "step2_srv_mobile_server", os.path.join(work, "mobile_server.py"))
        srv_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(srv_mod)
        db_path = os.path.join(work, "pharmacy.db")
        sdb = DB(path=db_path)
        pin = sdb.ensure_mobile_pin()
        did = sdb.add_drug({"trade_en": "SrvDrug", "trade_ar": "x", "scientific": "T",
                            "company": "X", "form": "Tabs", "strength": "500",
                            "category": "T", "strips_per_box": 1,
                            "tablets_per_strip": 1, "buy_price": 40.0,
                            "sell_price": 60.0, "min_stock": 0, "barcode": ""})
        sdb.conn.execute(
            "INSERT INTO batches (drug_id, batch_no, expiry, qty_units, "
            "buy_price_unit, created_at) VALUES (?,?,?,?,?,?)",
            (did, "B1", "2030-01-01", 100, 40.0, "2026-01-01"))
        sdb.conn.commit()
        sid = sdb.open_shift("admin", 0.0)
        sdb.close()
        srv = srv_mod.MobileServer(db_path=db_path, port=18081, https_port=18444)
        self.assertTrue(srv.start(), srv.start_error)
        try:
            time.sleep(1.0)
            body = json.dumps({"items": [{"drug_id": did, "unit": "box", "qty": 1}],
                               "payment": "cash", "paid": 60}).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:18081/api/invoices", data=body,
                headers={"X-Mobile-PIN": pin, "Content-Type": "application/json"},
                method="POST")
            # retry briefly: a previous run's daemon threads can still
            # hold the test port for a moment after its process exits.
            payload = None
            last_err = None
            for _attempt in range(6):
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        payload = json.loads(resp.read().decode())
                        status = resp.status
                    break
                except urllib.error.URLError as e:
                    last_err = e
                    time.sleep(0.5)
            self.assertIsNotNone(payload, "server never answered: %r" % (last_err,))
            self.assertEqual(status, 200)
            check = DB(path=db_path)
            try:
                sale = check.get_sale(payload["sale_id"])
                self.assertEqual(sale["shift_id"], sid)
                self.assertEqual(sale["source"], "mobile")
            finally:
                check.close()
        finally:
            for httpd in (getattr(srv, "httpd", None),
                          getattr(srv, "https_httpd", None)):
                if httpd is not None:
                    try:
                        httpd.shutdown()
                        httpd.server_close()
                    except Exception:
                        pass

    # ---------- 2B ----------
    def test_return_in_different_shift_hits_returning_shift_only(self):
        drug = mkdrug(self.db)
        add_batch(self.db, drug["id"], 100, FUT, buy_unit=1.0)
        shift_a = self.db.open_shift("admin", 0.0)
        sale_id, _inv, _t, _c = cash_sale(self.db, drug, shift_id=shift_a)
        before_a = self.db.shift_summary(shift_a)
        self.assertEqual(before_a["cash_collected"], 100.0)
        self.db.close_shift(shift_a, before_a["expected_cash"])
        shift_b = self.db.open_shift("admin", 0.0)
        self.db.return_sale(sale_id, "admin", return_shift_id=shift_b,
                            reason="زبون غيّر رأيه")
        sale = self.db.get_sale(sale_id)
        self.assertEqual(sale["status"], "returned")
        self.assertEqual(sale["shift_id"], shift_a)  # original shift kept
        rows = self.db.sale_returns_for_shift(shift_b)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sale_id"], sale_id)
        self.assertEqual(rows[0]["total_refunded"], 100.0)
        self.assertEqual(rows[0]["reason"], "زبون غيّر رأيه")
        # original shift: history NOT retroactively changed
        after_a = self.db.shift_summary(shift_a)
        self.assertEqual(after_a["cash_collected"], before_a["cash_collected"])
        self.assertEqual(after_a["expected_cash"], before_a["expected_cash"])
        self.assertEqual(after_a["card_total"], before_a["card_total"])
        # returning shift: the refund comes out of ITS drawer
        summ_b = self.db.shift_summary(shift_b)
        self.assertEqual(summ_b["cash_collected"], -100.0)
        self.assertEqual(summ_b["expected_cash"], -100.0)

    def test_return_same_shift_nets_zero(self):
        drug = mkdrug(self.db)
        add_batch(self.db, drug["id"], 100, FUT, buy_unit=1.0)
        sid = self.db.open_shift("admin", 200.0)
        sale_id, _i, _t, _c = cash_sale(self.db, drug, shift_id=sid)
        self.db.return_sale(sale_id, "admin", return_shift_id=sid)
        summ = self.db.shift_summary(sid)
        self.assertEqual(summ["cash_collected"], 0.0)
        self.assertEqual(summ["expected_cash"], 200.0)

    def test_card_sale_returned_elsewhere_keeps_original_card_total(self):
        drug = mkdrug(self.db)
        add_batch(self.db, drug["id"], 100, FUT, buy_unit=1.0)
        shift_a = self.db.open_shift("admin", 0.0)
        sale_id, _i, _t, _c = self.db.create_sale(
            "admin", [{"drug": drug, "pack_level": "box", "qty_display": 1}],
            payment_method="card", shift_id=shift_a)
        self.db.close_shift(shift_a, 0.0)
        shift_b = self.db.open_shift("admin", 0.0)
        self.db.return_sale(sale_id, "admin", return_shift_id=shift_b)
        self.assertEqual(self.db.shift_summary(shift_a)["card_total"], 100.0)
        self.assertEqual(self.db.shift_summary(shift_b)["card_total"], 0.0)
        self.assertEqual(self.db.shift_summary(shift_b)["cash_collected"], 0.0)

    def test_return_flow_still_restocks_and_reverses_credit(self):
        drug = mkdrug(self.db)
        add_batch(self.db, drug["id"], 40, FUT, buy_unit=1.0)
        cid = self.db.add_customer("Cred", "0100", credit_limit=10000)
        sale_id, _i, _t, _c = self.db.create_sale(
            "admin", [{"drug": drug, "pack_level": "box", "qty_display": 1}],
            payment_method="credit", customer_id=cid, paid=0.0)
        cust = [c for c in self.db.customers() if c["id"] == cid][0]
        self.assertEqual(cust["balance"], 100.0)
        self.assertEqual(self.db.sellable_stock(drug["id"]), 20)
        self.db.return_sale(sale_id, "admin")
        cust = [c for c in self.db.customers() if c["id"] == cid][0]
        self.assertEqual(cust["balance"], 0.0)
        self.assertEqual(self.db.sellable_stock(drug["id"]), 40)

    def test_backfill_legacy_returned_sale(self):
        drug = mkdrug(self.db)
        add_batch(self.db, drug["id"], 100, FUT, buy_unit=1.0)
        sid = self.db.open_shift("admin", 0.0)
        sale_id, _i, _t, _c = cash_sale(self.db, drug, shift_id=sid)
        # simulate a pre-STEP2 return: status flipped, no sale_returns row
        self.db.conn.execute("UPDATE sales SET status='returned' WHERE id=?", (sale_id,))
        self.db.conn.execute("DELETE FROM sale_returns WHERE sale_id=?", (sale_id,))
        self.db.conn.execute("DELETE FROM settings WHERE key='step2_returns_backfilled'")
        self.db.conn.commit()
        self.db.close()
        reopened = DB(path=os.path.join(self.tmp, "pharmacy.db"))
        try:
            rows = reopened.sale_returns_for_shift(sid)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["sale_id"], sale_id)
            self.assertEqual(rows[0]["return_shift_id"], sid)
            self.assertEqual(rows[0]["total_refunded"], 100.0)
            # totals stay consistent: same-shift legacy return nets to zero
            self.assertEqual(reopened.shift_summary(sid)["cash_collected"], 0.0)
        finally:
            reopened.close()
        self.db = DB(path=os.path.join(self.tmp, "pharmacy.db"))

    def test_return_unknown_shift_rejected(self):
        drug = mkdrug(self.db)
        add_batch(self.db, drug["id"], 100, FUT, buy_unit=1.0)
        sale_id, _i, _t, _c = cash_sale(self.db, drug)
        with self.assertRaises(ValueError):
            self.db.return_sale(sale_id, "admin", return_shift_id=99999)
        self.assertEqual(self.db.get_sale(sale_id)["status"], "completed")

    # ---------- 2C ----------
    def _stocked_supplier(self):
        sup = self.db.add_supplier("Sup1", "0100")
        drug = mkdrug(self.db, sell=25.0, buy=20.0)
        self.db.record_purchase(sup, "PUR-1", [
            {"drug": drug, "qty_boxes": 10, "buy_price": 20.0,
             "sell_price": None, "batch_no": "PB1", "expiry": FUT}],
            paid=0.0, user="admin")
        return sup, drug

    def test_purchase_return_deducts_stock_and_credits_supplier(self):
        sup, drug = self._stocked_supplier()
        before = [s for s in self.db.suppliers() if s["id"] == sup][0]
        self.assertEqual(before["balance"], 200.0)  # 10 boxes x 20
        self.assertEqual(self.db.sellable_stock(drug["id"]), 200)  # 10 x 20 units
        rid, total = self.db.create_purchase_return(
            sup, drug["id"], 20, unit="box", reason="منتهي الصلاحية",
            cashier="admin")
        self.assertEqual(total, 20.0)  # 20 units x 1.0 buy/unit
        self.assertEqual(self.db.sellable_stock(drug["id"]), 180)
        after = [s for s in self.db.suppliers() if s["id"] == sup][0]
        self.assertEqual(after["balance"], 180.0)
        rows = self.db.purchase_returns()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], rid)
        self.assertEqual(rows[0]["qty_units"], 20)
        self.assertEqual(rows[0]["reason"], "منتهي الصلاحية")
        audit = [a for a in self.db.audit_list(50) if a["action"] == "purchase_return"]
        self.assertTrue(audit)

    def test_purchase_return_fefo_takes_expired_batch_first(self):
        sup = self.db.add_supplier("Sup1", "0100")
        drug = mkdrug(self.db, sell=25.0, buy=20.0)
        exp_id = add_batch(self.db, drug["id"], 30, PAST, buy_unit=2.0,
                           batch_no="EXP", supplier_id=sup)
        add_batch(self.db, drug["id"], 30, FUT2, buy_unit=1.0,
                  batch_no="FRESH", supplier_id=sup)
        rid, total = self.db.create_purchase_return(
            sup, drug["id"], 30, unit="pill", reason="منتهي", cashier="admin")
        self.assertEqual(total, 60.0)  # expired batch @ 2.0/unit
        batches = {b["id"]: b for b in self.db.batches_for(drug["id"])}
        self.assertEqual(batches[exp_id]["qty_units"], 0)
        fresh = [b for b in self.db.batches_for(drug["id"]) if b["batch_no"] == "FRESH"][0]
        self.assertEqual(fresh["qty_units"], 30)

    def test_purchase_return_specific_batch(self):
        sup, drug = self._stocked_supplier()
        add_batch(self.db, drug["id"], 40, FUT2, buy_unit=5.0,
                  batch_no="B2", supplier_id=sup)
        b2 = [b for b in self.db.batches_for(drug["id"]) if b["batch_no"] == "B2"][0]
        rid, total = self.db.create_purchase_return(
            sup, drug["id"], 10, unit="pill", reason="تالف", cashier="admin",
            batch_id=b2["id"])
        self.assertEqual(total, 50.0)
        batches = {b["id"]: b for b in self.db.batches_for(drug["id"])}
        self.assertEqual(batches[b2["id"]]["qty_units"], 30)
        self.assertEqual(self.db.sellable_stock(drug["id"]), 230)

    def test_purchase_return_refusals(self):
        sup, drug = self._stocked_supplier()
        with self.assertRaises(ValueError):
            self.db.create_purchase_return(sup, drug["id"], 0, reason="x")
        with self.assertRaises(ValueError):
            self.db.create_purchase_return(sup, drug["id"], -5, reason="x")
        with self.assertRaises(ValueError):  # over stock (200 units on hand)
            self.db.create_purchase_return(sup, drug["id"], 201, reason="x")
        with self.assertRaises(ValueError):  # unknown supplier
            self.db.create_purchase_return(99999, drug["id"], 5, reason="x")
        other = mkdrug(self.db, name="Other")
        b_other = add_batch(self.db, other["id"], 10, FUT, buy_unit=1.0)
        with self.assertRaises(ValueError):  # batch belongs to another drug
            self.db.create_purchase_return(sup, drug["id"], 5, reason="x",
                                           batch_id=b_other)
        # failed attempts changed nothing
        self.assertEqual(self.db.sellable_stock(drug["id"]), 200)
        self.assertEqual(
            [s for s in self.db.suppliers() if s["id"] == sup][0]["balance"], 200.0)
        self.assertEqual(self.db.purchase_returns(), [])

    def test_purchase_return_in_daily_report(self):
        sup, drug = self._stocked_supplier()
        self.db.create_purchase_return(sup, drug["id"], 20, unit="box",
                                       reason="منتهي", cashier="admin")
        self.db.create_purchase_return(sup, drug["id"], 20, unit="box",
                                       reason="تالف", cashier="admin")
        r = self.db.report_daily()
        self.assertEqual(r["purchase_returns_count"], 2)
        self.assertEqual(r["purchase_returns_total"], 40.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
