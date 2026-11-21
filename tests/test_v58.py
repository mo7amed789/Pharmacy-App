"""v5.8 staged-deletion verification: DB edit + server approval gate.
Run: python3 tests/test_v58.py  (exit 0 only if ALL pass)"""
import json, os, shutil, sys, tempfile, time, urllib.request, urllib.error
from datetime import date, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..')  # app root (was /tmp/v58/work in the v5.8 work)
sys.path.insert(0, SRC)
from database import DB

WORK = HERE  # scratch dbs/srv live under tests/ (was /tmp/v58/tests)
SCRATCH = os.path.join(WORK, "dbs")
os.makedirs(SCRATCH, exist_ok=True)
PASS = []
FAIL = []
def check(n,c,x=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+((" | "+str(x)) if x and not c else ""))
FUT=(date.today()+timedelta(days=365)).isoformat()
def fresh(name):
    # Unique paths make repeated runs safe even when a prior process was
    # interrupted while SQLite still had a file handle open.
    d=tempfile.mkdtemp(prefix=name+'-', dir=SCRATCH)
    return DB(path=os.path.join(d,'pharmacy.db'))
def mk(db,name,sell,strips=2,tabs=10):
    did=db.add_drug({"trade_en":name,"trade_ar":"x","scientific":"T","company":"X","form":"Tabs","strength":"500","category":"T","strips_per_box":strips,"tablets_per_strip":tabs,"buy_price":1.0,"sell_price":sell,"min_stock":5,"barcode":""})
    return db.get_drug(did)
def batch(db,did,qty):
    db.conn.execute("INSERT INTO batches (drug_id,batch_no,expiry,qty_units,buy_price_unit,created_at) VALUES (?,?,?,?,?,?)",(did,"B1",FUT,qty,1.0,"2026-01-01")); db.conn.commit()
def stock(db,did): return db.conn.execute("SELECT COALESCE(SUM(qty_units),0) FROM batches WHERE drug_id=?",(did,)).fetchone()[0]
def audit_n(db): return db.conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='edit_sale'").fetchone()[0]
def setup(name):
    db=fresh(name); a=mk(db,"DrugA",25.0); b=mk(db,"DrugB",50.0); c=mk(db,"DrugC",10.0)
    for d in (a,b,c): batch(db,d["id"],100)
    sid,inv,total,ch=db.create_sale("admin",[{"drug":a,"pack_level":"box","qty_display":1},{"drug":b,"pack_level":"box","qty_display":1},{"drug":c,"pack_level":"box","qty_display":1}])
    assert total==85.0, total
    return db,a,b,c,sid

# T1: approve deletion of ONE line (B) -> B stock restored, total 25+10=35, audit names B
db,a,b,c,sid=setup("t1")
res=db.edit_sale(sid,"admin",[{"drug":a,"pack_level":"box","qty_display":1},{"drug":c,"pack_level":"box","qty_display":1}])
check("T1 approved delete: total 35", res["new_total"]==35.0, res)
check("T1 approved delete: B stock restored 80->100", stock(db,b["id"])==100, stock(db,b["id"]))
check("T1 approved delete: A/C stock still deducted", stock(db,a["id"])==80 and stock(db,c["id"])==80)
row=db.conn.execute("SELECT details FROM audit_log WHERE action='edit_sale' ORDER BY id DESC LIMIT 1").fetchone()[0]
check("T1 audit names the deleted line", "حُذف نهائياً" in row and "DrugB" in row, row)

# T2: restore-then-approve (full cart) -> totals/stock unchanged, audit has NO deletion
db,a,b,c,sid=setup("t2")
before=(stock(db,a["id"]),stock(db,b["id"]),stock(db,c["id"]))
res=db.edit_sale(sid,"admin",[{"drug":a,"pack_level":"box","qty_display":1},{"drug":b,"pack_level":"box","qty_display":1},{"drug":c,"pack_level":"box","qty_display":1}])
check("T2 restore+approve: total still 85", res["new_total"]==85.0, res)
check("T2 restore+approve: stock unchanged", (stock(db,a["id"]),stock(db,b["id"]),stock(db,c["id"]))==before)
row=db.conn.execute("SELECT details FROM audit_log WHERE action='edit_sale' ORDER BY id DESC LIMIT 1").fetchone()[0]
check("T2 audit has no deletion entry", "حُذف نهائياً" not in row, row)

# T3: cancel = no edit_sale call at all -> DB byte-identical (sale, items, batches, audit)
db,a,b,c,sid=setup("t3")
def snap(d):
    return (d.conn.execute("SELECT * FROM sales").fetchall(), d.conn.execute("SELECT * FROM sale_items").fetchall(), d.conn.execute("SELECT * FROM batches").fetchall(), d.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0])
s1=snap(db)
# simulate: user deletes B (held in memory only), then cancels -> nothing is called
s2=snap(db)
check("T3 cancelled deletion: DB identical, no audit row", s1==s2 and audit_n(db)==0)

# T4: delete 2 lines, approve 1 / restore 1 (edit keeps A+B, drops C)
db,a,b,c,sid=setup("t4")
res=db.edit_sale(sid,"admin",[{"drug":a,"pack_level":"box","qty_display":1},{"drug":b,"pack_level":"box","qty_display":1}])
check("T4 approve-1/restore-1: total 75, C restored", res["new_total"]==75.0 and stock(db,c["id"])==100, (res,stock(db,c["id"])))
check("T4 B kept (stock still deducted)", stock(db,b["id"])==80)

# ---------- server approval gate ----------
SRV=tempfile.mkdtemp(prefix='srv-', dir=SCRATCH)
for f in ("database.py","mobile_server.py","mobile.html","zxing.min.js","cert.pem","key.pem"):
    shutil.copy(os.path.join(SRC,f), os.path.join(SRV,f))
sys.path.insert(0, SRV)
import importlib
# fresh server DB via the srv copy's DB class
import database as srvdb; importlib.reload(srvdb)
from mobile_server import MobileServer
DBP=os.path.join(SRV,"pharmacy.db"); sdb=srvdb.DB(path=DBP); PIN=sdb.ensure_mobile_pin()
da=sdb.get_drug(mk(sdb,"SrvA",25.0)["id"]); db_=sdb.get_drug(mk(sdb,"SrvB",50.0)["id"])
for d in (da,db_): batch(sdb,d["id"],100)
sid,inv,total,ch=sdb.create_sale("admin",[{"drug":da,"pack_level":"box","qty_display":1},{"drug":db_,"pack_level":"box","qty_display":1}])
sdb.close()
srv=MobileServer(db_path=DBP, port=18081, https_port=18444)
assert srv.start(), srv.start_error
BASE="http://127.0.0.1:18081"; time.sleep(0.5)
def req(method,path,pin="USE",body=None):
    h={}
    if pin=="USE": h["X-Mobile-PIN"]=PIN
    elif pin: h["X-Mobile-PIN"]=pin
    data=json.dumps(body).encode() if body is not None else None
    if data: h["Content-Type"]="application/json"
    r=urllib.request.Request(BASE+path,data=data,headers=h,method=method)
    try:
        with urllib.request.urlopen(r,timeout=10) as resp: return resp.status,json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try: return e.code,json.loads(e.read().decode())
        except Exception: return e.code,{}
def stk(did):
    d=srvdb.DB(path=DBP); v=d.conn.execute("SELECT COALESCE(SUM(qty_units),0) FROM batches WHERE drug_id=?",(did,)).fetchone()[0]; d.close(); return v

# S1: omission WITHOUT approval -> 400, invoice + stock unchanged
st,body=req("POST",f"/api/invoices/{sid}/edit",body={"items":[{"drug_id":da["id"],"unit":"box","qty":1}],"payment":"cash","paid":25.0})
check("S1 unapproved deletion refused (400)", st==400, (st,body))
check("S1 invoice unchanged after refusal", stk(db_["id"])==80)
# S2: omission with approved=true but NO deleted_items -> 400
st,body=req("POST",f"/api/invoices/{sid}/edit",body={"items":[{"drug_id":da["id"],"unit":"box","qty":1}],"payment":"cash","paid":25.0,"approved":True})
check("S2 approved flag without deleted_items refused (400)", st==400, (st,body))
# S3: wrong PIN -> 401
st,body=req("POST",f"/api/invoices/{sid}/edit",pin="000000",body={"items":[{"drug_id":da["id"],"unit":"box","qty":1}],"payment":"cash","paid":25.0,"approved":True,"deleted_items":[{"drug_id":db_["id"],"unit":"box","qty":1}]})
check("S3 wrong PIN still 401", st==401, (st,body))
# S4: approved + deleted_items -> 200, B gone, stock restored
st,body=req("POST",f"/api/invoices/{sid}/edit",body={"items":[{"drug_id":da["id"],"unit":"box","qty":1}],"payment":"cash","paid":25.0,"approved":True,"deleted_items":[{"drug_id":db_["id"],"unit":"box","qty":1}]})
check("S4 approved deletion applied (200, total 25)", st==200 and body.get("new_total")==25.0, (st,body))
check("S4 B stock restored via server", stk(db_["id"])==100, stk(db_["id"]))
srv.stop()
print(f"\n{PASS.__len__()} passed, {len(FAIL)} failed: {FAIL}")
sys.exit(1 if FAIL else 0)
