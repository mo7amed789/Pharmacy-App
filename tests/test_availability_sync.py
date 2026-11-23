"""Synthetic sidecar tests. No HTTP or real publisher credentials."""
import os
import tempfile
import unittest
from datetime import date,timedelta
from unittest.mock import patch
from uuid import uuid4
from pathlib import Path
from database import DB
from availability_sync import Store,KEY_ENV,_endpoint,post_snapshot

class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=DB(path=str(Path(self.tmp.name)/'sales.db'));self.addCleanup(self.db.close)
        self.store=Store(str(Path(self.tmp.name)/'sidecar.db'));self.addCleanup(self.store.close)
        self.drug=self.db.add_drug({'trade_en':'Synthetic','form':'Tablet','strength':'10mg','strips_per_box':2,'tablets_per_strip':10,'sell_price':40,'barcode':'4006381333931'})
        self.mid=str(uuid4());self.branch=str(uuid4())
        self.catalog=[{'id':self.mid,'barcodes':[{'barcode':'04006381333931'}]}]
        self.store.review(self.db,self.catalog,self.drug,self.mid)
        self.env=patch.dict(os.environ,{KEY_ENV:'k'*40});self.env.start();self.addCleanup(self.env.stop)
    def enable(self):self.store.configure('https://example.invalid/api/v1/integration/inventory-snapshots',self.branch,True)
    def test_starts_disabled_no_network(self):
        self.assertFalse(self.store.config()['enabled']);self.assertIsNone(self.store.stage(self.db))
        self.assertFalse(self.store.send_once(lambda *a:self.fail('network while disabled')))
    def test_retry_and_reopen_keep_identical_snapshot(self):
        self.enable();p=self.store.stage(self.db);self.assertFalse(self.store.send_once(lambda *a:(503,{})))
        self.assertEqual(p,self.store.stage(self.db))
        second=Store(str(Path(self.tmp.name)/'sidecar.db'))
        try:self.assertEqual(p['snapshotId'],__import__('json').loads(second.pending()['payload'])['snapshotId'])
        finally:second.close()
    def test_pending_snapshot_does_not_bypass_501_limit(self):
        self.enable();queued=self.store.stage(self.db)
        with patch('availability_sync.inventory_preview',return_value={'items':[{}]*501,'held':[]}):
            self.assertIsNone(self.store.stage(self.db))
        self.assertFalse(self.store.config()['enabled'])
        self.assertIsNotNone(self.store.pending())
        self.assertFalse(self.store.send_once(lambda *a:self.fail('501 bindings sent')))

    def test_verified_ack_only_clears_queue(self):
        self.enable();p=self.store.stage(self.db)
        self.assertFalse(self.store.send_once(lambda *a:(200,{})));self.assertIsNotNone(self.store.pending())
        self.store.conn.execute('UPDATE outbox SET next_attempt=0');self.store.conn.commit()
        self.assertTrue(self.store.send_once(lambda *a:(200,{'snapshotId':p['snapshotId'],'sequence':p['sequence'],'accepted':len(p['items'])})))
        self.assertIsNone(self.store.pending())
    def test_expired_snapshot_reobserved_not_redated(self):
        self.enable();old=self.store.stage(self.db)
        self.store.conn.execute('UPDATE outbox SET created=0');self.store.conn.commit()
        self.assertFalse(self.store.send_once(lambda *a:self.fail('stale send')))
        new=self.store.stage(self.db);self.assertNotEqual(old['snapshotId'],new['snapshotId']);self.assertGreater(new['sequence'],old['sequence'])
    def test_identity_change_stops_instead_of_omitting(self):
        self.enable();self.db.conn.execute('UPDATE drugs SET strength=? WHERE id=?',('20mg',self.drug));self.db.conn.commit()
        self.assertIsNone(self.store.stage(self.db));self.assertFalse(self.store.config()['enabled'])
    def test_pending_identity_change_stops_before_retry(self):
        self.enable();self.store.stage(self.db)
        self.db.conn.execute('UPDATE drugs SET strength=? WHERE id=?',('changed',self.drug));self.db.conn.commit()
        self.assertIsNone(self.store.stage(self.db));self.assertFalse(self.store.config()['enabled'])
        self.assertFalse(self.store.send_once(lambda *a:self.fail('changed identity sent')))
    def test_mapping_review_disables_and_clears_pending(self):
        self.enable();self.store.stage(self.db)
        self.store.review(self.db,self.catalog,self.drug,self.mid)
        self.assertFalse(self.store.config()['enabled']);self.assertIsNone(self.store.pending())
    def test_network_rejects_local_destinations(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError):post_snapshot('https://example.invalid/api/v1/integration/inventory-snapshots','k'*40,{})
    def test_ambiguous_ack_does_not_clear(self):
        self.enable();p=self.store.stage(self.db)
        self.assertFalse(self.store.send_once(lambda *a:(200,{'snapshotId':p['snapshotId'],'sequence':p['sequence']+1,'accepted':1})))
        self.assertIsNotNone(self.store.pending())
    def test_updater_preserves_sidecar_and_lock(self):
        import updater
        for suffix in ['', '-wal', '-shm', '.lock']:
            self.assertTrue(updater._preserved('pharmacy.db.availability.sqlite3'+suffix))
    def test_credentials_not_saved_and_rejection_disables(self):
        self.enable();self.store.stage(self.db);self.store.send_once(lambda *a:(403,{}))
        self.assertFalse(self.store.config()['enabled'])
        self.assertNotIn('k'*40,repr(list(self.store.conn.iterdump())))
    def test_no_redirect_http_or_destination_change(self):
        for url in ['http://example.com/api/v1/integration/inventory-snapshots','https://user:pass@example.com/api/v1/integration/inventory-snapshots','https://example.com/x','https://example.com/api/v1/integration/inventory-snapshots?q=x']:
            with self.assertRaises(ValueError):_endpoint(url)
        self.enable()
        with self.assertRaises(ValueError):self.store.configure('https://other.invalid/api/v1/integration/inventory-snapshots',self.branch)
    def test_mapping_review_must_be_exact_and_unique(self):
        with self.assertRaises(ValueError):self.store.review(self.db,[],self.drug,self.mid)
        with self.assertRaises(ValueError):self.store.review(self.db,self.catalog+[{'id':str(uuid4()),'barcodes':[{'barcode':'4006381333931'}]}],self.drug,self.mid)
    def test_business_transaction_never_committed(self):
        self.enable();self.db.conn.execute('UPDATE drugs SET sell_price=99 WHERE id=?',(self.drug,))
        with self.assertRaises(ValueError):self.store.stage(self.db)
        self.assertTrue(self.db.conn.in_transaction);self.db.conn.rollback();self.assertEqual(40,self.db.get_drug(self.drug)['sell_price'])
    def test_fresh_zero_sent_and_no_private_sales_fields(self):
        self.enable();p=self.store.stage(self.db);self.assertEqual(0,p['items'][0]['availableQuantity'])
        self.assertEqual(set(p['items'][0]),{'externalProductId','medicineId','availableQuantity','price','currency','saleUnit','unitsPerPack','identityFingerprint'})
    def test_duplicate_remote_mapping_not_silently_replaced(self):
        another=self.db.add_drug({'trade_en':'Another','sell_price':50,'barcode':'5901234123457'})
        catalog=[{'id':self.mid,'barcodes':[{'barcode':'5901234123457'}]}]
        with self.assertRaises(Exception):self.store.review(self.db,catalog,another,self.mid)
        self.assertEqual(str(self.drug),self.store.bindings()[0]['externalProductId'])

if __name__=='__main__':unittest.main()
