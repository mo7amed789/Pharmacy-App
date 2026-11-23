"""Offline availability foundation. No live services or credentials required."""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import DB
from availability_bridge import canonical_gtin, mapping_candidates, inventory_preview


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = DB(path=os.path.join(self.temp.name, 'test.db'))
        self.addCleanup(self.db.conn.close)
        self.did = self.db.add_drug({
            'trade_en': 'Synthetic test product', 'trade_ar': '',
            'scientific': 'Test', 'company': 'Test', 'form': 'Tablet',
            'strength': '10mg', 'category': 'Test', 'strips_per_box': 2,
            'tablets_per_strip': 10, 'buy_price': 10, 'sell_price': 40,
            'min_stock': 0, 'barcode': '4006381333931'})
        self.mid = str(uuid4())
        self.medicines = [{'id': self.mid, 'isActive': True,
                           'barcodes': [{'barcode': '04006381333931'}]}]

    def binding(self):
        c = mapping_candidates(self.db, self.medicines)[0]
        return {'externalProductId': str(self.did), 'medicineId': self.mid,
                'status': 'verified', 'identityFingerprint': c['identityFingerprint']}

    def batch(self, units, expiry):
        self.db.conn.execute(
            'INSERT INTO batches(drug_id,expiry,qty_units) VALUES(?,?,?)',
            (self.did, expiry, units))
        self.db.conn.commit()

    def test_gtin_strict_and_padding(self):
        self.assertEqual(canonical_gtin('4006381333931'), '04006381333931')
        for bad in ['', '4006381333932', 'text4006381333931', '0000000000000',
                    '(01)04006381333931', '123', '４００６３８１３３３９３１']:
            self.assertIsNone(canonical_gtin(bad))

    def test_matches_need_review_and_no_fuzzy_name_match(self):
        c = mapping_candidates(self.db, self.medicines)[0]
        self.assertEqual(c['status'], 'needs_review')
        self.assertEqual(c['candidateMedicineIds'], [self.mid])
        self.assertEqual(mapping_candidates(self.db, [
            {'id': self.mid, 'brandName': 'Synthetic test product'}])[0]['status'], 'unmatched')

    def test_conflicting_and_inactive_remote_candidates(self):
        other = {'id': str(uuid4()), 'barcodes': [{'barcode': '4006381333931'}]}
        self.assertEqual(mapping_candidates(self.db, self.medicines + [other])[0]['status'], 'ambiguous')
        other['isActive'] = False
        self.assertEqual(mapping_candidates(self.db, self.medicines + [other])[0]['status'], 'needs_review')

    def test_sellable_whole_packs_and_expired_exclusion(self):
        self.batch(45, (date.today() + timedelta(days=1)).isoformat())
        self.batch(200, (date.today() - timedelta(days=1)).isoformat())
        before = self.db.conn.total_changes
        result = inventory_preview(self.db, [self.binding()])
        self.assertEqual(result['items'][0]['availableQuantity'], 2)
        self.assertEqual(result['items'][0]['price'], '40.00')
        self.assertEqual(result['items'][0]['unitsPerPack'], 20)
        self.assertFalse(result['networkEnabled'])
        self.assertEqual(self.db.conn.total_changes, before)
        self.assertFalse(self.db.conn.in_transaction)

    def test_zero_and_inactive_are_sent_not_omitted(self):
        self.assertEqual(inventory_preview(self.db, [self.binding()])['items'][0]['availableQuantity'], 0)
        self.batch(100, '')
        self.db.conn.execute('UPDATE drugs SET active=0 WHERE id=?', (self.did,))
        self.db.conn.commit()
        self.assertEqual(inventory_preview(self.db, [self.binding()])['items'][0]['availableQuantity'], 0)

    def test_unreviewed_and_changed_identity_held(self):
        b = self.binding()
        b['status'] = 'needs_review'
        self.assertFalse(inventory_preview(self.db, [b])['items'])
        b['status'] = 'verified'
        self.db.conn.execute("UPDATE drugs SET strength='20mg' WHERE id=?", (self.did,))
        self.db.conn.commit()
        self.assertIn('identity changed', inventory_preview(self.db, [b])['held'][0]['reason'])

    def test_duplicate_binding_invalidates_preview(self):
        b = self.binding()
        result = inventory_preview(self.db, [b, b])
        self.assertFalse(result['items'])
        self.assertIn('duplicate', result['held'][0]['reason'])

    def test_invalid_price_held(self):
        self.db.conn.execute('UPDATE drugs SET sell_price=0 WHERE id=?', (self.did,))
        self.db.conn.commit()
        self.assertFalse(inventory_preview(self.db, [self.binding()])['items'])

    def test_no_nested_transaction_or_partial_sale_commit(self):
        self.db.conn.execute('UPDATE drugs SET sell_price=50 WHERE id=?', (self.did,))
        with self.assertRaises(ValueError):
            inventory_preview(self.db, [])
        self.assertTrue(self.db.conn.in_transaction)
        self.db.conn.rollback()
        self.assertEqual(self.db.get_drug(self.did)['sell_price'], 40)


if __name__ == '__main__':
    unittest.main()
