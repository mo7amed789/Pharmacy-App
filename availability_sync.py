"""Opt-in public availability publisher. Separate from catalog and billing sync.

No network work happens on import. Settings start disabled. Credentials come only
from the process environment, never SQLite/config files, exports or logs.
"""
import json
import os
import ipaddress
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from uuid import UUID, uuid4

from availability_bridge import inventory_preview, mapping_candidates

KEY_ENV = 'PHARMACY_AVAILABILITY_PUBLISHER_KEY'


def _now():
    return datetime.now(timezone.utc)


def _stamp():
    return _now().isoformat().replace('+00:00', 'Z')


def _endpoint(value):
    p = urllib.parse.urlsplit(value)
    if (p.scheme != 'https' or not p.hostname or p.username or p.password or
            p.query or p.fragment or p.path != '/api/v1/integration/inventory-snapshots'):
        raise ValueError('Use the exact HTTPS inventory-snapshots endpoint, without credentials or query')
    return value


class Store:
    """Dedicated local sidecar; never commits or changes the sales database."""
    def __init__(self, path):
        self.conn = sqlite3.connect(path, timeout=2)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY CHECK(id=1),
          endpoint TEXT NOT NULL DEFAULT '', branch TEXT NOT NULL DEFAULT '',
          installation TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, sequence INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'Disabled');
        CREATE TABLE IF NOT EXISTS bindings (product TEXT PRIMARY KEY, medicine TEXT UNIQUE NOT NULL,
          fingerprint TEXT NOT NULL, units INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL,
          created REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0);
        ''')
        self.conn.execute('INSERT OR IGNORE INTO config(id,installation) VALUES(1,?)',(str(uuid4()),))
        self.conn.commit()

    def close(self):
        self.conn.close()

    def config(self):
        return dict(self.conn.execute('SELECT * FROM config WHERE id=1').fetchone())

    def configure(self, endpoint, branch, enabled=False):
        endpoint = _endpoint(endpoint)
        branch = str(UUID(branch))
        old = self.config()
        if old['branch'] and (old['branch'] != branch or old['endpoint'] != endpoint):
            raise ValueError('Changing an existing branch/destination needs a new reviewed installation')
        if enabled and len(os.environ.get(KEY_ENV, '')) < 32:
            raise ValueError('Publisher credential is missing from the process environment')
        with self.conn:
            self.conn.execute('UPDATE config SET endpoint=?,branch=?,enabled=?,status=? WHERE id=1',
                              (endpoint,branch,int(enabled),'Waiting' if enabled else 'Disabled'))

    def disable(self, status='Disabled'):
        with self.conn:
            self.conn.execute('UPDATE config SET enabled=0,status=? WHERE id=1',(status,))

    def review(self, db, catalog, product, medicine):
        """One explicit review action. No name-only or ambiguous auto-approval."""
        candidate = next((c for c in mapping_candidates(db,catalog) if c['externalProductId']==str(product)),None)
        if not candidate or candidate['candidateMedicineIds'] != [str(UUID(medicine))]:
            raise ValueError('Exact unique box GTIN candidate required')
        row = dict(db.conn.execute('SELECT * FROM drugs WHERE id=?',(str(product),)).fetchone())
        from database import units_per_box
        with self.conn:
            self.conn.execute('UPDATE config SET enabled=0,status=? WHERE id=1',('Mapping reviewed; re-enable after server provisioning',))
            self.conn.execute('DELETE FROM outbox')
            self.conn.execute('INSERT INTO bindings VALUES(?,?,?,?) ON CONFLICT(product) DO UPDATE SET medicine=excluded.medicine,fingerprint=excluded.fingerprint,units=excluded.units',
                (str(product),medicine,candidate['identityFingerprint'],units_per_box(row)))
        return candidate

    def bindings(self):
        return [{'externalProductId':r['product'],'medicineId':r['medicine'],
                 'identityFingerprint':r['fingerprint'],'unitsPerPack':r['units'],'status':'verified'}
                for r in self.conn.execute('SELECT * FROM bindings ORDER BY product')]

    def provision_manifest(self):
        c=self.config()
        return {'branchId':c['branch'],'installationId':c['installation'],'bindings':self.bindings()}

    def pending(self):
        r=self.conn.execute('SELECT * FROM outbox WHERE id=1').fetchone()
        return dict(r) if r else None

    def stage(self, db):
        if not self.config()['enabled']:
            return None
        preview=inventory_preview(db,self.bindings())
        # Do not silently omit a held mapping: stop until reviewed, avoiding old offers.
        if preview['held']:
            self.disable('Mapping or price changed; review required')
            return None
        if not preview['items']:
            return None
        old=self.pending()
        if old and time.time()-old['created'] < 14*60:
            return json.loads(old['payload'])
        if len(preview['items'])>500:
            self.disable('More than 500 bindings; split protocol required')
            return None
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            c=self.config()
            if not c['enabled']:
                return None
            sequence=c['sequence']+1
            payload={'schemaVersion':1,'installationId':c['installation'],'branchId':c['branch'],
                     'snapshotId':str(uuid4()),'sequence':sequence,'observedAtUtc':_stamp(),
                     'mode':'partial','items':preview['items']}
            self.conn.execute('UPDATE config SET sequence=?,status=? WHERE id=1',(sequence,'Queued'))
            self.conn.execute('INSERT OR REPLACE INTO outbox(id,payload,created) VALUES(1,?,?)',
                              (json.dumps(payload,separators=(',',':')),time.time()))
        return payload

    def send_once(self, transport=None):
        c=self.config();pending=self.pending()
        if not c['enabled'] or not pending or pending['next_attempt']>time.time():
            return False
        if time.time()-pending['created']>=14*60:
            return False # Re-observe in stage(); never refresh an old payload timestamp.
        key=os.environ.get(KEY_ENV,'')
        if len(key)<32:
            self.disable('Publisher credential missing');return False
        transport=transport or post_snapshot
        payload=json.loads(pending['payload'])
        try:
            status,ack=transport(_endpoint(c['endpoint']),key,payload)
        except Exception:
            status,ack=0,{}
        with self.conn:
            if status==200 and str(ack.get('snapshotId','')).lower()==payload['snapshotId'] and ack.get('sequence')==payload['sequence'] and ack.get('accepted')==len(payload['items']):
                self.conn.execute('DELETE FROM outbox WHERE id=1 AND payload=?',(pending['payload'],))
                self.conn.execute('UPDATE config SET status=? WHERE id=1',('Last acknowledgement: '+_stamp(),))
                return True
            if status in (400,401,403,404,409,410,413,422):
                self.conn.execute('UPDATE config SET enabled=0,status=? WHERE id=1',('Publisher rejected; operator review required (HTTP %s)'%status,))
            else:
                attempts=pending['attempts']+1
                delay=min(300,5*2**min(attempts,6))
                self.conn.execute('UPDATE outbox SET attempts=?,next_attempt=? WHERE id=1',(attempts,time.time()+delay))
                self.conn.execute('UPDATE config SET status=? WHERE id=1',('Waiting for acknowledged delivery',))
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_snapshot(endpoint,key,payload):
    """TLS verification stays enabled; redirects never forward publisher credentials."""
    host=urllib.parse.urlsplit(_endpoint(endpoint)).hostname
    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Public HTTPS destination required')
    request=urllib.request.Request(endpoint,data=json.dumps(payload).encode(),method='POST',
        headers={'Content-Type':'application/json','X-Inventory-Publisher-Key':key})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request,timeout=10) as response:
            return response.status,json.loads(response.read(65536))
    except urllib.error.HTTPError as error:
        return error.code,{}


def start_worker(db_path, store_path):
    """Separate connections, daemon thread, no sales hooks and no UI blocking."""
    stop=threading.Event()
    def run():
        from database import DB
        store=None;db=None;lock=None
        try:
            lock=open(store_path+'.lock','a+b')
            lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:
                return
            store=Store(store_path)
            if not store.config()['enabled']:
                return
            db=DB(path=db_path,init=False)
            while not stop.is_set():
                try:
                    if not store.config()['enabled']:break
                    store.stage(db);store.send_once()
                except Exception:
                    pass # Never expose payload/key details or interrupt billing.
                stop.wait(60)
        finally:
            if db:db.close()
            if store:store.close()
            if lock:lock.close()
    thread=threading.Thread(target=run,name='availability-publisher',daemon=True)
    stop.thread=thread
    thread.start()
    return stop
