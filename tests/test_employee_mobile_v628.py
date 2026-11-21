"""v6.28 employee HTTP access and simultaneous sales, disposable DB only.
Run: python3 -m unittest tests.test_employee_mobile_v628 -v
"""
import hashlib
import json
import os
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from database import DB
from mobile_server import _make_handler, _ReuseServer


class EmployeeMobile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'test.db')
        db = DB(self.path)
        self.pin = db.ensure_mobile_pin()
        self.user_ids = {}
        for name, role in [('alice', 'cashier'), ('bob', 'cashier'), ('manager', 'admin')]:
            self.user_ids[name] = db.create_user(name, 'test-only-password', role, name.title())
        self.did = db.add_drug(dict(trade_en='Concurrent', trade_ar='', scientific='', company='', form='Tabs', strength='', category='', strips_per_box=1, tablets_per_strip=1, buy_price=1, sell_price=2, min_stock=0, barcode=''))
        db.conn.execute('INSERT INTO batches (drug_id,batch_no,expiry,qty_units,buy_price_unit,created_at) VALUES (?,?,?,?,?,?)', (self.did,'test','2030-01-01',100,1,'2026-11-21'))
        db.conn.commit()
        db.close()
        self.handler = _make_handler(self.path)
        self.server = _ReuseServer(('127.0.0.1', 0), self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:%d' % self.server.server_port
        self.tokens = {name: self.login(name)[1]['token'] for name in self.user_ids}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, data=None, token=None, legacy=False):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer '+token
        if legacy:
            headers['X-Mobile-PIN'] = self.pin
        r = urllib.request.Request(self.base+path, headers=headers, method=method,
            data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=20) as response:
                self.assertEqual(response.headers.get('Cache-Control'), 'no-store')
                return response.status, json.load(response)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def login(self, name, password='test-only-password'):
        return self.request('POST', '/api/login', dict(username=name,password=password))

    def sale(self, name, ref, **extra):
        body=dict(items=[dict(drug_id=self.did,unit='box',qty=1)], payment='cash',client_ref=ref)
        body.update(extra)
        return self.request('POST', '/api/invoices', body, self.tokens.get(name), name is None)

    def test_attribution_and_access(self):
        a=self.sale('alice','same',cashier='bob',username='bob',employee_id=self.user_ids['bob'])
        b=self.sale('bob','same')
        self.assertEqual((a[0],b[0]),(200,200))
        self.assertNotEqual(a[1]['sale_id'], b[1]['sale_id'])
        sid=b[1]['sale_id']
        for query in ['', '?history=1', '?status=pending_print']:
            rows=self.request('GET','/api/invoices'+query,token=self.tokens['alice'])[1]['invoices']
            self.assertEqual([r['cashier'] for r in rows], ['alice'])
        for method,path,data in [('GET','/api/invoice/%d'%sid,None),('POST','/api/invoices/%d/edit'%sid,{}),('POST','/api/invoices/%d/return'%sid,{})]:
            # Edit checks ownership after validating items, so supply valid items.
            if path.endswith('/edit'):
                data=dict(items=[dict(drug_id=self.did,unit='box',qty=1)])
            self.assertEqual(self.request(method,path,data,self.tokens['alice'])[0],403)
        self.assertEqual(self.request('GET','/api/invoice/%d'%sid,token=self.tokens['manager'])[0],200)
        self.assertEqual(self.request('GET','/api/invoice/%d'%sid,legacy=True)[0],403)
        self.assertEqual(self.request('GET','/api/invoices?history=1',legacy=True)[1]['invoices'],[])
        self.assertEqual(self.request('GET','/api/cloud-config',token=self.tokens['alice'])[1],dict(url='',key=''))
        db=DB(self.path,init=False)
        self.assertEqual(db.get_sale(a[1]['sale_id'])['cashier'],'alice')
        self.assertIsNone(db.get_sale(a[1]['sale_id'])['shift_id'])
        db.close()

    def test_retries_concurrency_stock(self):
        barrier=threading.Barrier(20)
        def save(i):
            barrier.wait()
            return self.sale('alice' if i%2 else 'bob','ref-%d'%i)
        with ThreadPoolExecutor(max_workers=20) as pool:
            results=list(pool.map(save, range(20)))
        self.assertTrue(all(s==200 for s,b in results),results)
        self.assertEqual(len({b['invoice_no'] for s,b in results}),20)
        db=DB(self.path,init=False)
        self.assertEqual(db.sellable_stock(self.did),80)
        rows=db.report_employee_sales('2020-01-01','2030-01-01')
        self.assertEqual({r['employee']:r['completed_count'] for r in rows},{'alice':10,'bob':10})
        db.conn.execute('UPDATE batches SET qty_units=1 WHERE drug_id=?',(self.did,));db.conn.commit();db.close()
        barrier=threading.Barrier(2)
        def last(name):
            barrier.wait()
            return self.sale(name,'last')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(last,['alice','bob']))
        self.assertEqual(sorted(s for s,b in results),[200,400])
        winner='alice' if results[0][0]==200 else 'bob'
        self.assertEqual(self.sale(winner,'last')[1]['sale_id'], next(b['sale_id'] for s,b in results if s==200))

    def test_sessions_and_legacy(self):
        self.assertEqual(self.login('alice','wrong')[0],401)
        self.assertEqual(self.request('GET','/api/invoices',token='invalid',legacy=True)[0],401)
        self.assertEqual(self.sale(None,'legacy')[0],200)
        db=DB(self.path,init=False)
        db.set_setting('mobile_shared_pin_enabled','0');db.close()
        self.assertEqual(self.request('GET','/api/invoices',legacy=True)[0],401)
        self.assertEqual(self.sale('alice','employee')[0],200)
        self.request('POST','/api/logout',token=self.tokens['alice'])
        self.assertEqual(self.request('GET','/api/invoices',token=self.tokens['alice'])[0],401)
        db=DB(self.path,init=False);db.change_password('bob','changed-test-password');db.close()
        self.assertEqual(self.request('GET','/api/invoices',token=self.tokens['bob'])[0],401)
        digest=hashlib.sha256(self.tokens['manager'].encode()).hexdigest()
        self.handler._SESSIONS[digest]['expires']=0
        self.assertEqual(self.request('GET','/api/invoices',token=self.tokens['manager'])[0],401)

    def test_legacy_hash_upgrade_and_default_password(self):
        db=DB(self.path,init=False)
        db.conn.execute("UPDATE users SET password_hash=? WHERE username='alice'", (hashlib.sha256(b'test-only-password').hexdigest(),))
        db.conn.commit();db.close()
        code,body=self.login('alice')
        self.assertEqual(code,200)
        self.assertEqual(self.request('GET','/api/invoices',token=body['token'])[0],200)
        self.assertEqual(self.login('admin','admin123')[0],403)

    def test_own_edit_and_reference_collision_guard(self):
        sale=self.sale('alice','original')[1]
        body=dict(items=[dict(drug_id=self.did,unit='box',qty=2)],payment='cash')
        self.assertEqual(self.request('POST','/api/invoices/%d/edit'%sale['sale_id'],body,self.tokens['alice'])[0],200)
        db=DB(self.path,init=False)
        self.assertEqual(db.get_sale(sale['sale_id'])['cashier'],'alice')
        ref=db.get_sale(sale['sale_id'])['client_ref']
        db.close()
        self.assertEqual(self.sale(None,ref)[0],403)
        self.assertEqual(self.request('GET','/api/invoice/%d'%sale['sale_id'],token=self.tokens['alice'])[0],200)

    def test_reports_and_return(self):
        a=self.sale('alice','returned')[1]
        self.sale('alice','completed')
        self.assertEqual(self.request('POST','/api/invoices/%d/return'%a['sale_id'],{},self.tokens['alice'])[0],200)
        db=DB(self.path,init=False)
        rows=db.report_employee_sales('2020-01-01','2030-01-01')
        self.assertEqual(len(rows),1)
        r=rows[0]
        self.assertEqual((r['completed_count'],r['returned_count'],r['completed_sales'],r['returned_sales']),(1,1,2,2))
        self.assertEqual(db.report_employee_sales('2020-01-01','2020-01-02'),[])
        with self.assertRaises(ValueError):db.report_employee_sales('bad','2030-01-01')
        with self.assertRaises(ValueError):db.report_employee_sales('2030-01-01','2020-01-01')
        with self.assertRaises(ValueError):db.create_user('mobile','test-password','cashier')
        db.close()

if __name__=='__main__':
    unittest.main()
