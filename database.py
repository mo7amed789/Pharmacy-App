# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise v1 — database layer (stdlib only: sqlite3, hashlib, csv, shutil).
Offline-first: pharmacy.db lives in the app folder next to main.py.
Money is stored as REAL rounded to 2 decimals (EGP).
Stock is stored in SMALLEST UNITS (tablet / capsule / piece).
  units_per_box = strips_per_box * tablets_per_strip
  (for syrups / creams / inhalers: strips=1, tablets=1, so 1 box = 1 unit)
Price math:
  box_price  = drug.sell_price
  strip_price = box_price / strips_per_box
  pill_price  = strip_price / tablets_per_strip
Barcode:
  A barcode (GTIN / EAN-13) is ONLY an identifier. It contains NO price.
  Lookup: barcode -> barcodes table -> drug -> price from drugs table.
  GS1 2D DataMatrix (Phase 3): a square code can also carry batch +
  expiry + serial for one box. v1 only reads the GTIN part; if a 2D
  code is scanned, the GTIN is extracted from it when possible.
FEFO: sales always take from the batch with the nearest expiry first.
"""
import csv
import functools
import hashlib
import hmac
import math
import os
import re
import secrets
import shutil
import sqlite3
import threading
from datetime import date, datetime, timedelta

DB_NAME = "pharmacy.db"
SCHEMA_VERSION = 1
# v6.0 FINAL — FULL EMPTY install: True = this build ships with NO sample data.
# On a fresh database it creates the schema + the two default users ONLY
# (admin / cashier) and skips seeding the 60 sample drugs, the opening
# stock batches, the default supplier and the walk-in customer.
# seed_data.py is NOT shipped in this zip, so seeding cannot run at all.
# On an EXISTING database this flag changes nothing (seed_if_empty only
# acts when the drugs table is empty, and a real DB is never empty).
EMPTY_INSTALL = True
# v5.0: PBKDF2-HMAC-SHA256, 600k iterations (stdlib only, no new deps).
_PBKDF2_ITERATIONS = 600000


def _hash(password):
    """v5.0 password hash: pbkdf2_sha256$iterations$salt_hex$hash_hex.
    Legacy rows are bare 64-hex SHA-256 strings — see _verify_password."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (_PBKDF2_ITERATIONS, salt.hex(), dk.hex())


def _is_legacy_hash(stored):
    return isinstance(stored, str) and len(stored) == 64 and all(
        ch in "0123456789abcdef" for ch in stored.lower())


def _verify_password(password, stored):
    """True if password matches stored hash (PBKDF2 or legacy SHA-256)."""
    if not stored:
        return False
    if _is_legacy_hash(stored):
        return hmac.compare_digest(
            stored.lower(), hashlib.sha256(password.encode("utf-8")).hexdigest())
    try:
        scheme, iters, salt_hex, hash_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def _atomic(fn):
    """Decorator: any exception inside a multi-statement write rolls
    the whole transaction back, so a failed sale/purchase/return can
    never leave a half-written record that a later commit would
    silently persist (v5.0 fix for the missing rollback)."""
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        try:
            return fn(self, *a, **kw)
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
            raise
    return wrapper


def _cash_refund(sale):
    """Cash actually handed back when a sale is returned: cash sales
    refund paid-minus-change, credit sales refund only the cash part
    already received, card sales refund nothing from the drawer.
    STEP2 (2B) — shared by return_sale() and the backfill so both
    compute the same number."""
    m = sale["payment_method"]
    if m == "cash":
        return _round(float(sale["paid"] or 0) - float(sale["change_amount"] or 0))
    if m == "credit":
        return _round(float(sale["paid"] or 0))
    return 0.0


def _today():
    return date.today().isoformat()


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _round(x):
    return round(float(x) + 1e-9, 2)


def _validate_day(day):
    """v5.7: a report/sales query with a bad date used to silently return
    empty zeros. Raise a clear Arabic error instead."""
    try:
        _d = date.fromisoformat(str(day).strip()[:10])
    except Exception:
        raise ValueError("تاريخ غير صالح — استخدم الصيغة YYYY-MM-DD")
    return str(day).strip()[:10]


def _parse_expiry(value):
    """v5.7: expiry must be '' (unknown) or a valid YYYY-MM-DD date.
    Garbage strings used to be stored verbatim and sorted oddly in FEFO."""
    v = (value or "").strip()
    if not v:
        return ""
    try:
        date.fromisoformat(v[:10])
    except Exception:
        raise ValueError("تاريخ صلاحية غير صالح — استخدم الصيغة YYYY-MM-DD")
    return v[:10]


def units_per_box(drug):
    """drug is a dict/row with strips_per_box and tablets_per_strip."""
    strips = int(drug["strips_per_box"] or 1)
    tabs = int(drug["tablets_per_strip"] or 1)
    return max(1, strips * tabs)


def unit_price(drug, pack_level):
    """Price of ONE unit of the given pack level (box/strip/pill)."""
    box = float(drug["sell_price"])
    strips = int(drug["strips_per_box"] or 1)
    tabs = int(drug["tablets_per_strip"] or 1)
    if pack_level == "box":
        return _round(box)
    if pack_level == "strip":
        return _round(box / strips)
    return _round(box / strips / tabs)  # pill / single unit


def allowed_units(drug):
    """Return the sale units allowed by a drug's pharmaceutical form.

    Blank or unclassified forms keep the legacy box/strip/pill behaviour.
    Single-piece forms use ``pill`` for one suppository or sachet because
    that is the existing unit key used by the sale and stock code.
    """
    try:
        form = str(drug["form"] or "").strip().lower()
    except (KeyError, TypeError, IndexError):
        form = ""
    if re.search(
        r"cream|ointment|gel|paste|lotion|syrup|suspension|solution|"
        r"drops?|spray|shampoo|injection|ampoule|vial|كريم|مرهم|جل|"
        r"معجون|لوشن|شراب|معلق|محلول|نقط|قطرة|بخاخ|شامبو|حقن|أمبول|فيال|"
        # personal-care single-piece forms (v6.26): sold whole, never by strip/pill
        r"hair mask|serum|oil|soap|toothpaste|mouthwash|wash|deodorant|razor|foam|powder|"
        r"wipes|diapers?|pads|cotton|jelly|sunscreen|conditioner|toothbrush|"
        r"floss|shower|tissues|intimate|زيت|صابون|بلسم|مزيل|شفرات|رغوة|"
        r"بودرة|مناديل|حفاض|فوط|قطن|فازلين|واقي|فرشاة|شاور",
        form,
    ):
        return ["box"]
    if re.search(r"suppositor|pessar|ovule|sachet|تحميلة|تحاميل|لبوس|لبوسة|ظرف", form):
        return ["box", "pill"]
    return ["box", "strip", "pill"]


def units_for_qty(drug, pack_level, qty):
    """Convert a displayed qty (boxes/strips/pills) to smallest units."""
    if pack_level == "box":
        return int(qty) * units_per_box(drug)
    if pack_level == "strip":
        return int(qty) * int(drug["tablets_per_strip"] or 1)
    return int(qty)


def extract_gtin(code):
    """If a GS1 2D string was scanned, try to pull the GTIN (AI 01, 14 digits).
    Otherwise return the code as typed/scanned, digits only."""
    code = (code or "").strip()
    if "(01)" in code:
        # v5.7: take the 13- or 14-digit GTIN after (01) — the old
        # [:14] kept a trailing '(' from the next AI, and a 13-digit
        # EAN fell through to a digits-only mash, so 2D scans never matched.
        m = re.search(r"\(01\)(\d{13,14})", code)
        if m:
            return m.group(1)
    # GS1 DataMatrix often starts with ]d2 and contains 01 + 14 digits
    digits = "".join(ch for ch in code if ch.isdigit())
    return digits


# ---------------------------------------------------------------- EAN-13
# v6.3: real EAN-13 barcode support (internal pharmacy barcodes +
# label printing). Standard GS1 tables — no invented patterns.
_EAN_L = ("0001101", "0011001", "0010011", "0111101", "0100011",
          "0110001", "0101111", "0111011", "0111001", "0001011")
_EAN_G = ("0100111", "0110011", "0011011", "0100001", "0011101",
          "0111001", "0000101", "0010001", "0001001", "0010111")
_EAN_R = ("1110010", "1100110", "1101100", "1000010", "1011100",
          "1001110", "1010000", "1000100", "1001000", "1110100")
_EAN_PARITY = ("LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
               "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL")


def ean13_check_digit(first12):
    """GS1 check digit for the first 12 digits of an EAN-13 code."""
    d = [int(ch) for ch in str(first12).strip() if ch.isdigit()]
    if len(d) != 12:
        raise ValueError("باركود EAN-13 يحتاج 12 رقماً قبل رقم التحقق")
    total = sum(x * (3 if i % 2 else 1) for i, x in enumerate(d))
    return (10 - (total % 10)) % 10


def ean13_complete(first12):
    return str(first12) + str(ean13_check_digit(first12))


def ean13_is_valid(code):
    """True only for a 13-digit code whose check digit is correct."""
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(digits) != 13:
        return False
    return ean13_check_digit(digits[:12]) == int(digits[12])


def ean13_pattern(code13):
    """95-module bit string for a valid EAN-13 code (start 101, six
    left digits, middle 01010, six right digits, end 101)."""
    digits = "".join(ch for ch in str(code13 or "") if ch.isdigit())
    if not ean13_is_valid(digits):
        raise ValueError("باركود EAN-13 غير صالح (رقم التحقق خاطئ)")
    first = int(digits[0])
    parity = _EAN_PARITY[first]
    bits = "101"
    for i, ch in enumerate(digits[1:7]):
        table = _EAN_L if parity[i] == "L" else _EAN_G
        bits += table[int(ch)]
    bits += "01010"
    for ch in digits[7:13]:
        bits += _EAN_R[int(ch)]
    bits += "101"
    assert len(bits) == 95, len(bits)
    return bits


def ean13_decode_pattern(bits):
    """Decode a 95-module EAN-13 bit string back to its 13 digits.
    Used by the tests to prove the encoder is real and scannable,
    not a hand-drawn pattern."""
    bits = "".join(ch for ch in str(bits or "") if ch in "01")
    if len(bits) != 95 or not bits.startswith("101") or not bits.endswith("101"):
        raise ValueError("نمط باركود غير صالح")
    if bits[45:50] != "01010":
        raise ValueError("نمط باركود غير صالح (الوسط)")
    left = bits[3:45]
    right = bits[50:92]
    rev_l = {v: str(i) for i, v in enumerate(_EAN_L)}
    rev_g = {v: str(i) for i, v in enumerate(_EAN_G)}
    rev_r = {v: str(i) for i, v in enumerate(_EAN_R)}
    digits = ""
    parity = ""
    for i in range(6):
        chunk = left[i * 7:(i + 1) * 7]
        if chunk in rev_l:
            digits += rev_l[chunk]
            parity += "L"
        elif chunk in rev_g:
            digits += rev_g[chunk]
            parity += "G"
        else:
            raise ValueError("رقم يسار غير معروف في الباركود")
    first = _EAN_PARITY.index(parity)
    out = str(first) + digits
    for i in range(6):
        chunk = right[i * 7:(i + 1) * 7]
        if chunk not in rev_r:
            raise ValueError("رقم يمين غير معروف في الباركود")
        out += rev_r[chunk]
    if not ean13_is_valid(out):
        raise ValueError("رقم التحقق لا يطابق بعد فك الباركود")
    return out


def ean13_png_bytes(code13, scale=3, height=60, quiet=10):
    """Render an EAN-13 code as PNG bytes (pure stdlib: zlib + struct).
    Bars are drawn from ean13_pattern(); the number is NOT drawn in
    the image — callers print it as text under the bars."""
    import struct
    import zlib
    bits = ean13_pattern(code13)
    w = (len(bits) + 2 * quiet) * scale
    h = height
    raw = b""
    for _y in range(h):
        row = bytearray(b"\x00")
        for x in range(len(bits) + 2 * quiet):
            dark = x >= quiet and x < quiet + len(bits) and bits[x - quiet] == "1"
            row.extend(b"\x00\x00\x00" if dark else b"\xff\xff\xff")
        raw += bytes(row)
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw))
    png += chunk(b"IEND", b"")
    return png


def drug_default_line_discount(drug, unit_price_value, qty):
    """v6.3: the drug's own default discount, as a TOTAL amount for
    this line. percent -> % of the line total; amount -> fixed EGP
    per unit (so it scales with qty). Returns 0.0 when the drug has
    no discount. Never more than the line total."""
    try:
        dtype = (drug.get("discount_type") or "none").strip().lower()
        val = float(drug.get("discount_value") or 0)
        up = float(unit_price_value or 0)
        q = float(qty or 0)
    except (TypeError, ValueError):
        return 0.0
    if val <= 0 or up <= 0 or q <= 0:
        return 0.0
    if dtype == "percent":
        return _round(up * q * min(val, 100.0) / 100.0)
    if dtype == "amount":
        return _round(min(val, up) * q)
    return 0.0


def discount_label(drug):
    """Arabic display of a drug's default discount, e.g. '10%' or
    '5.00 ج.م/وحدة' or '' when there is none."""
    dtype = (drug.get("discount_type") or "none").strip().lower()
    try:
        val = float(drug.get("discount_value") or 0)
    except (TypeError, ValueError):
        return ""
    if dtype == "percent" and val > 0:
        return "%g%%" % val
    if dtype == "amount" and val > 0:
        return "%s ج.م/وحدة" % _round(val)
    return ""


class DB:
    # v6.2: per-process record of DB files whose one-time init
    # (schema + migrations + seed) already ran. A second process
    # (PC app vs standalone mobile server) has its own set and
    # inits once at ITS startup — that is correct and harmless,
    # because every migration below is idempotent.
    _INIT_LOCK = threading.Lock()
    _INIT_DONE = set()

    def __init__(self, path=None, init=True):
        """init=True (default): full one-time setup — schema,
        migrations, audit prune, seed — exactly as before, so every
        existing caller is unaffected. init=False: lightweight
        connection only (PRAGMAs, no schema/migration/seed work);
        use ONLY after DB.ensure_initialized(path) has run once in
        this process, e.g. the mobile server's per-request _db()."""
        base = os.path.dirname(os.path.abspath(__file__))
        self.path = path or os.path.join(base, DB_NAME)
        # v5.0: 15s busy timeout + WAL so the PC app and the mobile
        # server (different connections) stop raising "database is locked"
        # on concurrent writes; they wait briefly instead.
        self.conn = sqlite3.connect(self.path, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 15000")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        if not init:
            return
        self.init_schema()
        self._migrate_v5()
        self._migrate_v5_5()
        self._migrate_v5_7()
        self._migrate_v6_2()
        self._migrate_step2()
        self._migrate_v6_3()
        self._migrate_roles_branches()
        self._prune_audit_log()
        self.seed_if_empty()
        with DB._INIT_LOCK:
            DB._INIT_DONE.add(os.path.abspath(self.path))

    @classmethod
    def ensure_initialized(cls, path=None):
        """Run the one-time schema init / migrations / seed for a DB
        file, at most once per process. Later calls are a lock +
        set lookup (~microseconds). Raises if the init itself fails,
        so a broken DB fails loudly at startup instead of serving
        half-initialised requests."""
        base = os.path.dirname(os.path.abspath(__file__))
        resolved = os.path.abspath(path or os.path.join(base, DB_NAME))
        with cls._INIT_LOCK:
            if resolved in cls._INIT_DONE:
                return
        db = cls(path=resolved)  # full init; records the path on success
        db.close()

    # ---------- schema ----------
    def init_schema(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS drugs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_en TEXT NOT NULL, trade_ar TEXT DEFAULT '',
            scientific TEXT DEFAULT '', company TEXT DEFAULT '',
            form TEXT DEFAULT '', strength TEXT DEFAULT '',
            category TEXT DEFAULT '', strips_per_box INTEGER DEFAULT 1,
            tablets_per_strip INTEGER DEFAULT 1,
            buy_price REAL DEFAULT 0, sell_price REAL DEFAULT 0,
            min_stock INTEGER DEFAULT 5, active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS barcodes (
            barcode TEXT PRIMARY KEY, drug_id INTEGER NOT NULL,
            pack_level TEXT DEFAULT 'box',
            FOREIGN KEY(drug_id) REFERENCES drugs(id)
        );
        CREATE TABLE IF NOT EXISTS batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drug_id INTEGER NOT NULL, batch_no TEXT DEFAULT '',
            expiry TEXT DEFAULT '', qty_units INTEGER DEFAULT 0,
            buy_price_unit REAL DEFAULT 0, supplier_id INTEGER,
            created_at TEXT DEFAULT '',
            FOREIGN KEY(drug_id) REFERENCES drugs(id)
        );
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drug_id INTEGER NOT NULL, batch_id INTEGER, qty_units INTEGER NOT NULL,
            kind TEXT DEFAULT '', ref TEXT DEFAULT '', user TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, phone TEXT DEFAULT '', address TEXT DEFAULT '',
            balance REAL DEFAULT 0, created_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER, invoice_no TEXT DEFAULT '',
            date TEXT DEFAULT '', total REAL DEFAULT 0, paid REAL DEFAULT 0,
            user TEXT DEFAULT '', created_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS purchase_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_id INTEGER NOT NULL, drug_id INTEGER NOT NULL,
            batch_id INTEGER, qty_boxes REAL DEFAULT 0, qty_units INTEGER DEFAULT 0,
            buy_price REAL DEFAULT 0, line_total REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, phone TEXT DEFAULT '', address TEXT DEFAULT '',
            credit_limit REAL DEFAULT 0, balance REAL DEFAULT 0,
            notes TEXT DEFAULT '', created_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT DEFAULT '', date TEXT DEFAULT '',
            cashier TEXT DEFAULT '', customer_id INTEGER,
            subtotal REAL DEFAULT 0, discount REAL DEFAULT 0,
            total REAL DEFAULT 0, paid REAL DEFAULT 0, change_amount REAL DEFAULT 0,
            payment_method TEXT DEFAULT 'cash', status TEXT DEFAULT 'completed',
            shift_id INTEGER, created_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL, drug_id INTEGER NOT NULL,
            batch_id INTEGER, pack_level TEXT DEFAULT 'box',
            qty_display REAL DEFAULT 0, qty_units INTEGER DEFAULT 0,
            unit_price REAL DEFAULT 0, buy_price_unit REAL DEFAULT 0,
            line_total REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'cashier', full_name TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cashier TEXT DEFAULT '', opened_at TEXT DEFAULT '',
            closed_at TEXT DEFAULT '', opening_float REAL DEFAULT 0,
            cash_total REAL DEFAULT 0, card_total REAL DEFAULT 0,
            credit_total REAL DEFAULT 0, status TEXT DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT DEFAULT '', kind TEXT DEFAULT '', amount REAL DEFAULT 0,
            notes TEXT DEFAULT '', user TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT DEFAULT '', action TEXT DEFAULT '',
            details TEXT DEFAULT '', created_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT DEFAULT ''
        );
        -- v5.7: a real payments ledger. Customer payments used to
        -- live only as free text in audit_log, so customer history
        -- showed sales but never the money the customer actually paid.
        CREATE TABLE IF NOT EXISTS customer_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL, amount REAL DEFAULT 0,
            user TEXT DEFAULT '', created_at TEXT DEFAULT '',
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        );
        -- STEP2 (2B): one row per sale return — which shift took the
        -- goods back and paid the refund. The sale keeps its ORIGINAL
        -- shift_id; the refund is attributed to the RETURNING shift.
        CREATE TABLE IF NOT EXISTS sale_returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL, invoice_no TEXT DEFAULT '',
            return_shift_id INTEGER, cashier TEXT DEFAULT '',
            returned_at TEXT DEFAULT '', refund_method TEXT DEFAULT '',
            total_refunded REAL DEFAULT 0, reason TEXT DEFAULT ''
        );
        -- STEP2 (2C): stock returned to a supplier (expired / damaged /
        -- near-expiry). batch_id is NULL when FEFO took units from
        -- several batches; unit is the unit the qty was entered in.
        CREATE TABLE IF NOT EXISTS purchase_returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL, drug_id INTEGER NOT NULL,
            batch_id INTEGER, qty_units INTEGER NOT NULL,
            unit TEXT DEFAULT 'pill', buy_price REAL DEFAULT 0,
            total REAL DEFAULT 0, reason TEXT DEFAULT '',
            returned_at TEXT DEFAULT '', cashier TEXT DEFAULT ''
        );
        -- v2: optional forecast cache. Recompute-on-demand is the source of
        -- truth; this table only avoids recomputing for 60 drugs on every
        -- tab switch. Safe to delete at any time — it is rebuilt on demand.
        CREATE TABLE IF NOT EXISTS forecast_cache (
            drug_id INTEGER PRIMARY KEY,
            horizon_days INTEGER DEFAULT 30,
            predicted_daily REAL DEFAULT 0,
            predicted_total REAL DEFAULT 0,
            confidence INTEGER DEFAULT 0,
            computed_at TEXT DEFAULT '',
            FOREIGN KEY(drug_id) REFERENCES drugs(id)
        );
        """)
        self.conn.commit()
        # v4 migration: phone invoices + print queue. Safe on old DBs —
        # PRAGMA check first so re-running never errors or loses data.
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(sales)").fetchall()]
        if "source" not in cols:
            self.conn.execute("ALTER TABLE sales ADD COLUMN source TEXT DEFAULT 'pc'")
        if "printed_at" not in cols:
            self.conn.execute("ALTER TABLE sales ADD COLUMN printed_at TEXT DEFAULT ''")
        self.conn.commit()

    def _migrate_v5(self):
        """v5.0 production migration — additive only, safe on an existing
        pharmacy.db. Runs once; re-running is a no-op (checks first).
        1) Dated backup of the DB BEFORE any structural change.
        2) sales.client_ref (mobile idempotency key) + partial unique index.
        3) Unique invoice numbers: de-duplicate any existing duplicates
           (later copies renamed INV-…-DUP<id>), then a UNIQUE index so
           two sales can never share a number again."""
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(sales)").fetchall()]
        idx = [r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='sales'").fetchall()]
        needs = ("client_ref" not in cols
                 or "idx_sales_invoice_no" not in idx
                 or "idx_sales_client_ref" not in idx)
        if not needs:
            return
        # 1) backup first — sqlite3 backup API, verified copy.
        try:
            self.backup(suffix="_pre_migration_v5")
        except Exception:
            pass
        # 2) client_ref column (idempotency key for mobile retries).
        if "client_ref" not in cols:
            self.conn.execute("ALTER TABLE sales ADD COLUMN client_ref TEXT DEFAULT ''")
        # 3) de-duplicate invoice_no values before the unique index.
        dupes = self.conn.execute(
            "SELECT invoice_no FROM sales GROUP BY invoice_no HAVING COUNT(*)>1"
        ).fetchall()
        for (inv,) in dupes:
            rows = self.conn.execute(
                "SELECT id FROM sales WHERE invoice_no=? ORDER BY id", (inv,)).fetchall()
            for r in rows[1:]:
                self.conn.execute(
                    "UPDATE sales SET invoice_no=? WHERE id=?",
                    ("%s-DUP%d" % (inv, r["id"]), r["id"]))
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_invoice_no ON sales(invoice_no)")
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_client_ref "
            "ON sales(client_ref) WHERE client_ref <> ''")
        self.conn.commit()

    def _migrate_v5_5(self):
        """v5.5 invoice editing — additive only, safe on an existing
        pharmacy.db. Adds edited_at / edited_by to sales so an edited
        invoice keeps its number/date but shows it was changed, by
        whom and when. Re-running is a no-op."""
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(sales)").fetchall()]
        if "edited_at" not in cols:
            self.conn.execute("ALTER TABLE sales ADD COLUMN edited_at TEXT DEFAULT ''")
        if "edited_by" not in cols:
            self.conn.execute("ALTER TABLE sales ADD COLUMN edited_by TEXT DEFAULT ''")
        self.conn.commit()

    def _migrate_v5_7(self):
        """v5.7 review migration — additive only, safe on an existing
        pharmacy.db. Runs once (guarded by the v57_credit_fixed
        setting for the one-time data correction).
        1) shifts: expected_cash / counted_cash / difference columns
           for drawer reconciliation.
        2) expenses: shift_id column (expenses belong to a shift now).
        3) Credit-balance correction: before v5.7, create/edit added
           the FULL total to the customer balance even when part was
           already paid, and recorded paid=total on credit sales.
           For every still-completed credit sale with paid>0, subtract
           the recorded paid from the customer's balance (clamped at
           0) — the balance then equals total - paid, as it should.
           Returned sales are skipped: their reversal already removed
           the full total. Runs once, guarded by a settings flag."""
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(shifts)").fetchall()]
        for col in ("expected_cash", "counted_cash", "difference"):
            if col not in cols:
                self.conn.execute("ALTER TABLE shifts ADD COLUMN %s REAL DEFAULT 0" % col)
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(expenses)").fetchall()]
        if "shift_id" not in cols:
            self.conn.execute("ALTER TABLE expenses ADD COLUMN shift_id INTEGER")
        self.conn.commit()
        if self.get_setting("v57_credit_fixed") != "1":
            try:
                rows = self.conn.execute(
                    """SELECT customer_id, paid FROM sales
                    WHERE payment_method='credit' AND status='completed'
                    AND customer_id IS NOT NULL AND paid>0""").fetchall()
                for r in rows:
                    self.conn.execute(
                        """UPDATE customers SET balance=
                        MAX(0, balance-?) WHERE id=?""",
                        (float(r["paid"] or 0), r["customer_id"]))
                self.set_setting("v57_credit_fixed", "1")
            except Exception:
                pass
        # Initialise the invoice high-water file from the DB max so a
        # restore of an old backup cannot re-issue numbers.
        try:
            if not os.path.exists(self._invoice_counter_path()):
                row = self.conn.execute(
                    "SELECT MAX(CAST(SUBSTR(invoice_no,5) AS INTEGER)) m "
                    "FROM sales WHERE invoice_no LIKE 'INV-%'").fetchone()
                if row and row["m"]:
                    self._invoice_bump(int(row["m"]))
        except Exception:
            pass

    def _migrate_v6_2(self):
        """v6.2 audit fix (1B) — ADDITIVE index migration, safe on an
        existing pharmacy.db. CREATE INDEX IF NOT EXISTS is itself a
        no-op on re-run, so no guard flag is needed; every statement
        only adds an index, never changes data or schema. Tables are
        checked first so a damaged DB missing a table cannot break
        startup. Indexes:
          batches(drug_id, expiry, qty_units) — FEFO stock lookups
            and _drug_with_stock / low_stock / near_expiry scans.
          sales(date, status) — daily reports, sales_on(), history.
          sales(shift_id) — shift close / reconciliation.
          sale_items(sale_id) — invoice detail lines.
          drugs(trade_en, trade_ar, scientific) — name ordering and
            prefix search (note: LIKE '%...%' with a leading wildcard
            still cannot use an index; this helps ORDER BY trade_en
            and prefix matches).
          barcodes(drug_id) — reverse lookup drug -> barcodes.
          stock_movements(drug_id, created_at) — per-drug history."""
        tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        have = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        wanted = [
            ("batches", "idx_batches_drug_expiry",
             "CREATE INDEX IF NOT EXISTS idx_batches_drug_expiry "
             "ON batches(drug_id, expiry, qty_units)"),
            ("sales", "idx_sales_date",
             "CREATE INDEX IF NOT EXISTS idx_sales_date "
             "ON sales(date, status)"),
            ("sales", "idx_sales_shift",
             "CREATE INDEX IF NOT EXISTS idx_sales_shift "
             "ON sales(shift_id)"),
            ("sale_items", "idx_sale_items_sale",
             "CREATE INDEX IF NOT EXISTS idx_sale_items_sale "
             "ON sale_items(sale_id)"),
            ("drugs", "idx_drugs_names",
             "CREATE INDEX IF NOT EXISTS idx_drugs_names "
             "ON drugs(trade_en, trade_ar, scientific)"),
            ("barcodes", "idx_barcodes_drug",
             "CREATE INDEX IF NOT EXISTS idx_barcodes_drug "
             "ON barcodes(drug_id)"),
            ("stock_movements", "idx_stock_movements_drug",
             "CREATE INDEX IF NOT EXISTS idx_stock_movements_drug "
             "ON stock_movements(drug_id, created_at)"),
        ]
        for table, name, sql in wanted:
            # Skip work already done: a repeat full DB() open must
            # stay as cheap as before this migration.
            if table in tables and name not in have:
                self.conn.execute(sql)
        self.conn.commit()

    def _migrate_roles_branches(self):
        """Additive only: branches, attendance, users.branch_id, shifts.branch_id.
        Existing rows keep branch_id NULL (= no branch)."""
        self.conn.execute("""CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL, address TEXT DEFAULT '',
            active INTEGER DEFAULT 1, created_at TEXT DEFAULT '')""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL, branch_id INTEGER,
            check_in TEXT NOT NULL, check_out TEXT DEFAULT '',
            note TEXT DEFAULT '', created_by TEXT DEFAULT '')""")
        for table in ("users", "shifts"):
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info(%s)" % table).fetchall()]
            if "branch_id" not in cols:
                self.conn.execute("ALTER TABLE %s ADD COLUMN branch_id INTEGER" % table)
        self.conn.commit()

    # ---------- roles / branches / attendance ----------
    def user_role(self, username):
        r = self.conn.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
        return r["role"] if r else None

    def _require_admin(self, actor):
        if self.user_role(actor) != "admin":
            raise PermissionError("هذه العملية للمدير فقط")

    def list_users(self, actor):
        self._require_admin(actor)
        return [dict(r) for r in self.conn.execute(
            "SELECT id, username, role, full_name, branch_id FROM users ORDER BY username").fetchall()]

    def list_branches(self, active_only=False):
        q = "SELECT * FROM branches" + (" WHERE active=1" if active_only else "") + " ORDER BY name"
        return [dict(r) for r in self.conn.execute(q).fetchall()]

    def add_branch(self, actor, name, address=""):
        self._require_admin(actor)
        name = (name or "").strip()
        if not name:
            raise ValueError("اسم الفرع مطلوب")
        try:
            c = self.conn.execute("INSERT INTO branches (name, address, active, created_at) VALUES (?,?,1,?)",
                                  (name, (address or "").strip(), _now()))
        except sqlite3.IntegrityError:
            raise ValueError("يوجد فرع بنفس الاسم")
        self.conn.commit()
        return c.lastrowid

    def set_branch_active(self, actor, branch_id, active):
        self._require_admin(actor)
        self.conn.execute("UPDATE branches SET active=? WHERE id=?", (1 if active else 0, branch_id))
        self.conn.commit()

    def set_user_branch(self, actor, username, branch_id):
        self._require_admin(actor)
        if branch_id is not None and not self.conn.execute(
                "SELECT 1 FROM branches WHERE id=?", (branch_id,)).fetchone():
            raise ValueError("الفرع غير موجود")
        self.conn.execute("UPDATE users SET branch_id=? WHERE username=?", (branch_id, username))
        self.conn.commit()

    def user_branch_id(self, username):
        r = self.conn.execute("SELECT branch_id FROM users WHERE username=?", (username,)).fetchone()
        return r["branch_id"] if r else None

    def attendance_open_for(self, username):
        r = self.conn.execute(
            "SELECT * FROM attendance WHERE username=? AND check_out='' ORDER BY id DESC LIMIT 1",
            (username,)).fetchone()
        return dict(r) if r else None

    def check_in(self, username):
        """An employee records their own attendance. One open record at a time."""
        if self.user_role(username) is None:
            raise ValueError("المستخدم غير موجود")
        if self.attendance_open_for(username):
            raise ValueError("تم تسجيل الحضور بالفعل، سجّل الانصراف أولاً")
        c = self.conn.execute(
            "INSERT INTO attendance (username, branch_id, check_in, created_by) VALUES (?,?,?,?)",
            (username, self.user_branch_id(username), _now(), username))
        self.conn.commit()
        return c.lastrowid

    def check_out(self, username):
        row = self.attendance_open_for(username)
        if not row:
            raise ValueError("لا يوجد حضور مفتوح لتسجيل الانصراف")
        self.conn.execute("UPDATE attendance SET check_out=? WHERE id=?", (_now(), row["id"]))
        self.conn.commit()
        return row["id"]

    @staticmethod
    def _parse_dt(value, label):
        value = (value or "").strip().replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
        raise ValueError("%s: اكتب التاريخ والوقت بالشكل 2026-11-25 09:00" % label)

    def attendance_add_manual(self, actor, username, check_in, check_out, note=""):
        """Admin records a shift/attendance for an employee."""
        self._require_admin(actor)
        if self.user_role(username) is None:
            raise ValueError("المستخدم غير موجود")
        a = self._parse_dt(check_in, "وقت الحضور")
        b = self._parse_dt(check_out, "وقت الانصراف") if (check_out or "").strip() else None
        if b is not None and b <= a:
            raise ValueError("وقت الانصراف يجب أن يكون بعد الحضور")
        c = self.conn.execute(
            "INSERT INTO attendance (username, branch_id, check_in, check_out, note, created_by) VALUES (?,?,?,?,?,?)",
            (username, self.user_branch_id(username), a.isoformat(timespec="seconds"),
             b.isoformat(timespec="seconds") if b else "", (note or "").strip(), actor))
        self.conn.commit()
        return c.lastrowid

    def attendance_report(self, actor, date_from, date_to, username=None):
        """Admin: anyone (or all). Anyone else: only their own rows."""
        if self.user_role(actor) != "admin":
            username = actor
        d1 = self._parse_dt(date_from + " 00:00", "من")
        d2 = self._parse_dt(date_to + " 23:59", "إلى")
        q = ("SELECT a.*, b.name AS branch_name FROM attendance a LEFT JOIN branches b ON b.id=a.branch_id "
             "WHERE a.check_in>=? AND a.check_in<=?")
        args = [d1.isoformat(timespec="seconds"), d2.isoformat(timespec="seconds")]
        if username:
            q += " AND a.username=?"
            args.append(username)
        rows = []
        for r in self.conn.execute(q + " ORDER BY a.check_in DESC", args).fetchall():
            d = dict(r)
            try:
                end = datetime.fromisoformat(d["check_out"]) if d["check_out"] else None
                d["hours"] = round((end - datetime.fromisoformat(d["check_in"])).total_seconds() / 3600, 2) if end else None
            except ValueError:
                d["hours"] = None
            rows.append(d)
        return rows

    def _migrate_v6_3(self):
        """v6.3 — additive only, safe on an existing pharmacy.db:
        drugs.discount_type ('none'|'percent'|'amount') +
        drugs.discount_value, and sale_items.line_discount (the
        per-line discount actually applied, so receipts, edits and
        profit all see it). Old rows get 'none'/0 — no sale changes."""
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(drugs)").fetchall()]
        if "discount_type" not in cols:
            self.conn.execute("ALTER TABLE drugs ADD COLUMN discount_type TEXT DEFAULT 'none'")
        if "discount_value" not in cols:
            self.conn.execute("ALTER TABLE drugs ADD COLUMN discount_value REAL DEFAULT 0")
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(sale_items)").fetchall()]
        if "line_discount" not in cols:
            self.conn.execute("ALTER TABLE sale_items ADD COLUMN line_discount REAL DEFAULT 0")
        self.conn.commit()

    def _migrate_step2(self):
        """STEP2 (2B) backfill — additive only, safe on an existing
        pharmacy.db. Runs once (guarded by the step2_returns_backfilled
        setting). Sales already marked 'returned' before sale_returns
        existed get one row each, with return_shift_id = the sale's
        ORIGINAL shift_id (best available attribution) so shift totals
        stay exactly as they were. Tables are created by init_schema;
        this only backfills the data."""
        if self.get_setting("step2_returns_backfilled") == "1":
            return
        try:
            rows = self.conn.execute(
                """SELECT s.* FROM sales s WHERE s.status='returned'
                AND NOT EXISTS (SELECT 1 FROM sale_returns sr
                                WHERE sr.sale_id=s.id)""").fetchall()
            for s in rows:
                self.conn.execute(
                    """INSERT INTO sale_returns (sale_id, invoice_no,
                    return_shift_id, cashier, returned_at, refund_method,
                    total_refunded, reason) VALUES (?,?,?,?,?,?,?,?)""",
                    (s["id"], s["invoice_no"], s["shift_id"], s["cashier"],
                     s["created_at"] or _now(), s["payment_method"],
                     _cash_refund(s), "إرجاع سابق (قبل سجل المرتجعات)"))
            self.set_setting("step2_returns_backfilled", "1")
            self.conn.commit()
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass

    def _prune_audit_log(self):
        """Keep the audit log from growing forever: newest 5,000 rows."""
        try:
            self.conn.execute(
                "DELETE FROM audit_log WHERE id NOT IN "
                "(SELECT id FROM audit_log ORDER BY id DESC LIMIT 5000)")
            self.conn.commit()
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass

    @_atomic
    def seed_if_empty(self):
        c = self.conn.cursor()
        n = c.execute("SELECT COUNT(*) FROM drugs").fetchone()[0]
        # EMPTY INSTALL: never seed sample drugs / stock / supplier /
        # customer. The pharmacy starts at zero and the owner enters
        # real data (Inventory tab, or CSV import in Settings).
        if n == 0 and not EMPTY_INSTALL:
            from seed_data import SAMPLE_DRUGS, sample_barcode
            for i, d in enumerate(SAMPLE_DRUGS):
                (en, ar, sci, comp, form, strength, cat,
                 strips, tabs, buy, sell, mins) = d
                c.execute(
                    """INSERT INTO drugs (trade_en, trade_ar, scientific, company,
                    form, strength, category, strips_per_box, tablets_per_strip,
                    buy_price, sell_price, min_stock, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (en, ar, sci, comp, form, strength, cat, strips, tabs,
                     buy, sell, mins, _now()))
                drug_id = c.lastrowid
                c.execute("INSERT OR IGNORE INTO barcodes VALUES (?,?,?)",
                          (sample_barcode(i), drug_id, "box"))
                # v5.7: opening stock sits ABOVE the alert threshold
                # (min_stock + 2 boxes) — 2 boxes with min_stock 3-10
                # flagged ALL 60 seeded drugs as "low stock" on a fresh
                # install. low_stock() still alerts at <= min_stock,
                # which is the correct meaning of a minimum.
                upb = max(1, strips * tabs)
                c.execute(
                    """INSERT INTO batches (drug_id, batch_no, expiry, qty_units,
                    buy_price_unit, created_at) VALUES (?,?,?,?,?,?)""",
                    (drug_id, "SEED-%03d" % (i + 1), "2027-12-31",
                     (max(2, mins) + 2) * upb, _round(buy / upb), _now()))
            # default supplier + walk-in customer
            c.execute("INSERT INTO suppliers (name, phone, created_at) VALUES (?,?,?)",
                      ("مورد عام (نقدي)", "", _now()))
            c.execute("INSERT INTO customers (name, phone, credit_limit, created_at) VALUES (?,?,?,?)",
                      ("عميل نقدي", "", 0, _now()))
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            c.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?,?,?,?)",
                      ("admin", _hash("admin123"), "admin", "المدير"))
            c.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?,?,?,?)",
                      ("cashier", _hash("cashier123"), "cashier", "الكاشير"))
        c.execute("INSERT OR IGNORE INTO settings VALUES (?,?)",
                  ("pharmacy_name", "صيدلية المؤسسة — Pharmacy Enterprise"))
        self.conn.commit()

    # ---------- settings / mobile PIN (v4) ----------
    def get_setting(self, key, default=""):
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))
        self.conn.commit()

    def ensure_mobile_pin(self):
        """Return the 6-digit LAN PIN, generating it once if missing.
        Stored in the settings table — never in code, never in a zip."""
        pin = self.get_setting("mobile_pin")
        if pin and len(pin) == 6 and pin.isdigit():
            return pin
        pin = "%06d" % (secrets.randbelow(900000) + 100000)
        self.set_setting("mobile_pin", pin)
        return pin

    def regenerate_mobile_pin(self):
        pin = "%06d" % (secrets.randbelow(900000) + 100000)
        self.set_setting("mobile_pin", pin)
        return pin

    # ---------- audit ----------
    def audit(self, user, action, details=""):
        self.conn.execute(
            "INSERT INTO audit_log (user, action, details, created_at) VALUES (?,?,?,?)",
            (user or "", action, details or "", _now()))
        self.conn.commit()

    def authenticate(self, username, password):
        row = self.conn.execute(
            "SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
        if row and _verify_password(password, row["password_hash"]):
            # Lazy upgrade: a legacy SHA-256 hash is re-hashed to PBKDF2
            # on the first successful login — no manual migration needed.
            if _is_legacy_hash(row["password_hash"]):
                try:
                    self.conn.execute(
                        "UPDATE users SET password_hash=? WHERE username=?",
                        (_hash(password), username.strip()))
                    self.conn.commit()
                except Exception:
                    pass
            return dict(row)
        return None

    def is_default_password(self, username):
        """True if the user still logs in with a factory default
        password (admin123 / cashier123) — the app forces a change."""
        row = self.conn.execute(
            "SELECT password_hash FROM users WHERE username=?", (username.strip(),)).fetchone()
        if not row:
            return False
        return (_verify_password("admin123", row["password_hash"])
                or _verify_password("cashier123", row["password_hash"]))

    def change_password(self, username, new_password):
        # v5.7: the DB layer had no password rules at all (empty or
        # 3-char passwords were accepted).
        if not new_password or len(new_password) < 8:
            raise ValueError("كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل")
        self.conn.execute("UPDATE users SET password_hash=? WHERE username=?",
                          (_hash(new_password), username))
        self.conn.commit()

    def create_user(self, username, password, role, full_name="", branch_id=None):
        """Create a user with a PBKDF2 hash (v5.0). Raises on duplicate."""
        if not (username or "").strip():
            raise ValueError("اسم المستخدم مطلوب")
        if username.strip().lower() == "mobile":
            raise ValueError("الاسم mobile محجوز للدخول المشترك")
        if not password or len(password) < 8:
            raise ValueError("كلمة المرور يجب أن تكون 8 أحرف على الأقل")
        if role not in ("admin", "cashier"):
            raise ValueError("الصلاحية يجب أن تكون admin أو cashier")
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO users (username, password_hash, role, full_name, branch_id) VALUES (?,?,?,?,?)",
            (username.strip(), _hash(password), role, full_name.strip(), branch_id))
        self.conn.commit()
        return c.lastrowid

    # ---------- drugs / barcode ----------
    def search_drugs(self, query="", limit=100):
        q = "%" + (query or "").strip() + "%"
        if not query.strip():
            rows = self.conn.execute(
                "SELECT * FROM drugs WHERE active=1 ORDER BY trade_en LIMIT ?", (limit,)).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM drugs WHERE active=1 AND
                (trade_en LIKE ? OR trade_ar LIKE ? OR scientific LIKE ? OR company LIKE ?)
                ORDER BY trade_en LIMIT ?""", (q, q, q, q, limit)).fetchall()
        return self._drugs_with_stock(rows)

    def drugs_by_ids(self, drug_ids):
        """Active drugs requested by the mobile cart, preserving its order."""
        ids = []
        seen = set()
        for value in drug_ids or []:
            try:
                drug_id = int(value)
            except (TypeError, ValueError):
                continue
            if drug_id > 0 and drug_id not in seen:
                seen.add(drug_id)
                ids.append(drug_id)
        if not ids:
            return []
        rows = []
        for start in range(0, len(ids), 900):
            chunk = ids[start:start + 900]
            marks = ",".join("?" * len(chunk))
            rows.extend(self.conn.execute(
                "SELECT * FROM drugs WHERE active=1 AND id IN (%s)" % marks,
                chunk).fetchall())
        by_id = {drug["id"]: drug for drug in self._drugs_with_stock(rows)}
        return [by_id[drug_id] for drug_id in ids if drug_id in by_id]

    def get_drug(self, drug_id):
        row = self.conn.execute("SELECT * FROM drugs WHERE id=?", (drug_id,)).fetchone()
        return self._drug_with_stock(dict(row)) if row else None

    def _drugs_with_stock(self, rows):
        """Batch version of _drug_with_stock (v6.2 audit fix 1A):
        ONE query for the stock of every drug in `rows` instead of
        one query per drug (the N+1 in search_drugs). Same definition
        of stock: SUM(qty_units) over batches with qty_units>0 — a
        drug with no such batch gets 0 — and the identical
        stock_units / stock_boxes math as _drug_with_stock, so
        results, prices and FEFO behaviour are unchanged. Ids are
        chunked (900 per query) to stay under SQLite's variable
        limit on every bundled SQLite version."""
        dicts = [dict(r) for r in rows]
        if not dicts:
            return []
        stock = {}
        for i in range(0, len(dicts), 900):
            chunk = dicts[i:i + 900]
            ids = [d["id"] for d in chunk]
            qmarks = ",".join("?" * len(ids))
            for r in self.conn.execute(
                    "SELECT drug_id, COALESCE(SUM(qty_units),0) s FROM batches "
                    "WHERE drug_id IN (%s) AND qty_units>0 GROUP BY drug_id"
                    % qmarks, ids).fetchall():
                stock[r["drug_id"]] = int(r["s"])
        for d in dicts:
            d["stock_units"] = stock.get(d["id"], 0)
            d["stock_boxes"] = round(d["stock_units"] / units_per_box(d), 2)
        return dicts

    def _drug_with_stock(self, d):
        row = self.conn.execute(
            "SELECT COALESCE(SUM(qty_units),0) s FROM batches WHERE drug_id=? AND qty_units>0",
            (d["id"],)).fetchone()
        d["stock_units"] = int(row["s"])
        d["stock_boxes"] = round(d["stock_units"] / units_per_box(d), 2)
        return d

    def lookup_barcode(self, code):
        """Returns (drug_dict, pack_level) or (None, None) if unknown."""
        gtin = extract_gtin(code)
        row = self.conn.execute(
            "SELECT * FROM barcodes WHERE barcode=?", (gtin,)).fetchone()
        if not row:
            return None, None
        drug = self.get_drug(row["drug_id"])
        return drug, row["pack_level"]

    def drug_barcode(self, drug_id):
        """The drug's box barcode, or '' when none is registered."""
        row = self.conn.execute(
            "SELECT barcode FROM barcodes WHERE drug_id=? AND pack_level='box' LIMIT 1",
            (drug_id,)).fetchone()
        return row["barcode"] if row else ""

    def ensure_drug_barcode(self, drug_id):
        """v6.3: return the drug's barcode, auto-generating a unique
        internal EAN-13 when it has none (prefix 2 + zero-padded drug
        id + a CORRECT GS1 check digit) and saving it, so the same
        code prints next time and scans back to this drug. Raises
        ValueError if the drug does not exist."""
        bc = self.drug_barcode(drug_id)
        if bc:
            return bc
        if not self.conn.execute("SELECT id FROM drugs WHERE id=?", (drug_id,)).fetchone():
            raise ValueError("الدواء غير موجود")
        base = 0
        while True:
            first12 = "2" + str(int(drug_id) + base * 100000).zfill(11)
            code = ean13_complete(first12[:12])
            row = self.conn.execute("SELECT drug_id FROM barcodes WHERE barcode=?", (code,)).fetchone()
            if not row:
                break
            base += 1
            if base > 1000:
                raise ValueError("تعذر توليد باركود فريد")
        self._link_barcode_checked(self.conn.cursor(), code, drug_id)
        self.conn.commit()
        return code

    def link_barcode(self, barcode, drug_id, pack_level="box"):
        c = self.conn.cursor()
        self._link_barcode_checked(c, barcode, drug_id)
        self.conn.commit()

    @staticmethod
    def _validate_drug_fields(fields):
        """Reject impossible drug data at the DB boundary (v5.0 + v5.7):
        strips/tablets are whole numbers >= 1, prices are finite and
        >= 0 (NaN/inf used to be stored as NULL/inf and later crashed
        unit_price()), min_stock >= 0, trade name required."""
        try:
            strips_f = float(fields.get("strips_per_box", 1))
            tabs_f = float(fields.get("tablets_per_strip", 1))
            buy = float(fields.get("buy_price", 0) or 0)
            sell = float(fields.get("sell_price", 0) or 0)
            mins_f = float(fields.get("min_stock", 5) or 0)
        except (TypeError, ValueError):
            raise ValueError("قيم رقمية غير صالحة لبيانات الدواء")
        if strips_f != int(strips_f) or tabs_f != int(tabs_f) or mins_f != int(mins_f):
            raise ValueError("عدد الشرائط والحبات والحد الأدنى يجب أن تكون أعداداً صحيحة")
        strips, tabs, mins = int(strips_f), int(tabs_f), int(mins_f)
        if strips < 1 or tabs < 1:
            raise ValueError("عدد الشرائط والحبات يجب أن يكون 1 على الأقل")
        if not math.isfinite(buy) or not math.isfinite(sell):
            raise ValueError("سعر الشراء وسعر البيع يجب أن يكونا رقمين حقيقيين")
        if buy < 0 or sell < 0:
            raise ValueError("سعر الشراء وسعر البيع لا يمكن أن يكونا سالبين")
        if buy > 1e7 or sell > 1e7:
            raise ValueError("السعر كبير جداً — راجع القيمة المدخلة")
        if mins < 0:
            raise ValueError("الحد الأدنى للمخزون لا يمكن أن يكون سالباً")
        if not (fields.get("trade_en") or "").strip():
            raise ValueError("الاسم التجاري مطلوب")
        dtype = (fields.get("discount_type") or "none").strip().lower()
        if dtype not in ("none", "percent", "amount"):
            raise ValueError("نوع الخصم غير صالح — اختر: بدون خصم / نسبة % / مبلغ ثابت")
        try:
            dval = float(fields.get("discount_value") or 0)
        except (TypeError, ValueError):
            raise ValueError("قيمة الخصم غير صالحة")
        if not math.isfinite(dval) or dval < 0:
            raise ValueError("قيمة الخصم لا يمكن أن تكون سالبة")
        if dtype == "percent" and dval > 100:
            raise ValueError("نسبة الخصم يجب أن تكون بين 0 و 100%")
        if dtype == "amount" and sell > 0 and dval >= sell:
            raise ValueError("المبلغ الثابت للخصم يجب أن يكون أقل من سعر البيع")
        if dtype == "none":
            fields["discount_value"] = 0

    def _link_barcode_checked(self, c, barcode, drug_id):
        """v5.7: link a barcode, but never silently steal it from
        another drug (INSERT OR REPLACE used to) and never store an
        empty GTIN (all garbage scans collapsed to '')."""
        code = extract_gtin(barcode)
        if not code:
            raise ValueError("باركود غير صالح — أدخل رقماً صحيحاً")
        row = c.execute("SELECT drug_id FROM barcodes WHERE barcode=?", (code,)).fetchone()
        if row:
            if int(row["drug_id"]) == int(drug_id):
                return
            raise ValueError("هذا الباركود مسجل لدواء آخر بالفعل")
        c.execute("INSERT INTO barcodes VALUES (?,?,?)", (code, drug_id, "box"))

    def alternatives(self, drug):
        # Same active ingredient: exact scientific match first, then any
        # drug whose scientific name contains the base ingredient
        # (text before '+', e.g. "Paracetamol" in "Paracetamol + Caffeine").
        base = (drug.get("scientific") or "").split("+")[0].strip()
        if not base:
            return []
        rows = self.conn.execute(
            """SELECT * FROM drugs WHERE active=1 AND id<>?
            AND (scientific=? OR scientific LIKE ?) ORDER BY sell_price""",
            (drug["id"], drug["scientific"], "%" + base + "%")).fetchall()
        return [self._drug_with_stock(dict(r)) for r in rows]

    @_atomic
    def add_drug(self, fields, _commit=True):
        self._validate_drug_fields(fields)
        c = self.conn.cursor()
        c.execute(
            """INSERT INTO drugs (trade_en, trade_ar, scientific, company, form,
            strength, category, strips_per_box, tablets_per_strip, buy_price,
            sell_price, min_stock, discount_type, discount_value, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fields["trade_en"], fields.get("trade_ar", ""), fields.get("scientific", ""),
             fields.get("company", ""), fields.get("form", ""), fields.get("strength", ""),
             fields.get("category", ""), int(fields.get("strips_per_box", 1)),
             int(fields.get("tablets_per_strip", 1)), float(fields.get("buy_price", 0)),
             float(fields.get("sell_price", 0)), int(fields.get("min_stock", 5)),
             (fields.get("discount_type") or "none"),
             float(fields.get("discount_value") or 0), _now()))
        drug_id = c.lastrowid
        if fields.get("barcode"):
            self._link_barcode_checked(c, fields["barcode"], drug_id)
        if _commit:
            self.conn.commit()
            self._cloud_push_async(drug_id)
        return drug_id

    @_atomic
    def update_drug(self, drug_id, fields, _commit=True):
        self._validate_drug_fields(fields)
        self.conn.execute(
            """UPDATE drugs SET trade_en=?, trade_ar=?, scientific=?, company=?,
            form=?, strength=?, category=?, strips_per_box=?, tablets_per_strip=?,
            buy_price=?, sell_price=?, min_stock=?, discount_type=?, discount_value=? WHERE id=?""",
            (fields["trade_en"], fields.get("trade_ar", ""), fields.get("scientific", ""),
             fields.get("company", ""), fields.get("form", ""), fields.get("strength", ""),
             fields.get("category", ""), int(fields.get("strips_per_box", 1)),
             int(fields.get("tablets_per_strip", 1)), float(fields.get("buy_price", 0)),
             float(fields.get("sell_price", 0)), int(fields.get("min_stock", 5)),
             (fields.get("discount_type") or "none"),
             float(fields.get("discount_value") or 0), drug_id))
        if _commit:
            self.conn.commit()
            self._cloud_push_async(drug_id)

    # ---------- cloud sync (v6.11) ----------
    def _cloud_push_async(self, drug_id):
        """رفع الصنف للسحابة بعد أي إضافة/تعديل — أفضل جهد ولا يوقف
        البرنامج إطلاقاً: يعمل في خيط منفصل باتصال خاص (اتصالات SQLite
        لا تُشارك بين الخيوط)، ولا يفعل شيئاً إن لم يُضبط إعداد Supabase
        أو أثناء السحب من السحابة (_cloud_mute). أي فشل يُسجَّل في
        إعداد cloud_last_error ويظهر في شاشة الإعدادات."""
        if getattr(self, "_cloud_mute", False):
            return
        try:
            import cloud_sync
            import supabase_client
        except Exception:
            return
        if not supabase_client.is_configured():
            return
        path = self.path

        def worker():
            try:
                db = DB(path=path, init=False)
                try:
                    cloud_sync.push_drug_safe(db, drug_id)
                finally:
                    db.close()
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    # ---------- stock / batches / FEFO ----------
    def batches_for(self, drug_id):
        rows = self.conn.execute(
            """SELECT b.*, COALESCE(s.name,'') AS supplier_name FROM batches b
            LEFT JOIN suppliers s ON s.id=b.supplier_id
            WHERE b.drug_id=? ORDER BY b.expiry ASC, b.id ASC""", (drug_id,)).fetchall()
        return [dict(r) for r in rows]

    def _deduct_fefo(self, c, drug_id, qty_units, user, ref):
        """Deduct qty_units from nearest-expiry batches first. Returns
        list of (batch_id, taken_units, buy_price_unit). Raises ValueError
        if stock is not enough. Caller owns the transaction.
        v5.7 (CRITICAL): batches whose expiry is in the past are NEVER
        sold — FEFO used to prefer them because they were earliest.
        Batches with no expiry date are sold LAST, not first."""
        remaining = int(qty_units)
        out = []
        today = _today()
        rows = c.execute(
            """SELECT * FROM batches WHERE drug_id=? AND qty_units>0
            AND (expiry='' OR expiry IS NULL OR expiry>=?)
            ORDER BY (expiry='' OR expiry IS NULL) ASC, expiry ASC, id ASC""",
            (drug_id, today)).fetchall()
        for b in rows:
            if remaining <= 0:
                break
            take = min(int(b["qty_units"]), remaining)
            c.execute("UPDATE batches SET qty_units=qty_units-? WHERE id=?", (take, b["id"]))
            c.execute(
                """INSERT INTO stock_movements (drug_id, batch_id, qty_units, kind, ref, user, created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (drug_id, b["id"], -take, "sale", ref, user, _now()))
            out.append((b["id"], take, float(b["buy_price_unit"] or 0)))
            remaining -= take
        if remaining > 0:
            expired = c.execute(
                """SELECT COALESCE(SUM(qty_units),0) FROM batches
                WHERE drug_id=? AND qty_units>0 AND expiry<>'' AND expiry<?""",
                (drug_id, today)).fetchone()[0]
            if expired:
                raise ValueError("المخزون المتاح منتهي الصلاحية — اعزله أولاً قبل البيع")
            raise ValueError("المخزون غير كافٍ")
        return out

    def sellable_stock(self, drug_id):
        """v5.7: units that may actually be sold (not expired). The POS
        pre-check used to count expired stock as available."""
        row = self.conn.execute(
            """SELECT COALESCE(SUM(qty_units),0) FROM batches
            WHERE drug_id=? AND qty_units>0
            AND (expiry='' OR expiry IS NULL OR expiry>=?)""",
            (drug_id, _today())).fetchone()
        return int(row[0])

    @_atomic
    def adjust_stock(self, drug_id, qty_units_delta, reason, user, batch_no="", expiry=""):
        c = self.conn.cursor()
        if qty_units_delta > 0:
            # v5.7: a positive adjustment no longer invents expiry
            # 2027-12-31 and zero cost — the batch is dateless (sold
            # last by FEFO) and valued at the drug's current buy price.
            exp = _parse_expiry(expiry) if expiry else ""
            if exp and exp < _today():
                raise ValueError("تاريخ الصلاحية في الماضي — لا يمكن إضافة تشغيلة منتهية")
            drug = self.get_drug(drug_id)
            buy_unit = 0.0
            if drug:
                buy_unit = _round(float(drug.get("buy_price") or 0) / units_per_box(drug))
            c.execute(
                """INSERT INTO batches (drug_id, batch_no, expiry, qty_units,
                buy_price_unit, created_at) VALUES (?,?,?,?,?,?)""",
                (drug_id, batch_no or "ADJ", exp,
                 qty_units_delta, buy_unit, _now()))
            batch_id = c.lastrowid
        else:
            batch_id = None
            self._deduct_fefo(c, drug_id, -qty_units_delta, user, "adjust")
        c.execute(
            """INSERT INTO stock_movements (drug_id, batch_id, qty_units, kind, ref, user, created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (drug_id, batch_id, qty_units_delta, "adjust", reason, user, _now()))
        self.conn.commit()

    def low_stock(self):
        out = []
        for d in self.search_drugs("", limit=10000):
            # v5.7: min_stock 0 means "never alert" (0<=0 used to flag it).
            if int(d["min_stock"]) > 0 and d["stock_units"] <= int(d["min_stock"]) * units_per_box(d):
                out.append(d)
        return out

    def near_expiry(self, days=90):
        limit = (date.today() + timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            """SELECT b.*, d.trade_en, d.trade_ar FROM batches b
            JOIN drugs d ON d.id=b.drug_id
            WHERE b.qty_units>0 AND b.expiry<>'' AND b.expiry<=?
            ORDER BY b.expiry ASC""", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- sales ----------
    def _invoice_counter_path(self):
        """v5.7: high-water mark for invoice numbers, stored in a small
        file NEXT TO the DB. A restore copies an old DB file over the
        live one, so a counter kept inside the DB would roll back and
        re-issue numbers already given to customers on paper."""
        return os.path.join(os.path.dirname(os.path.abspath(self.path)),
                            "invoice_counter.txt")

    def _invoice_highwater(self):
        try:
            with open(self._invoice_counter_path(), encoding="utf-8") as f:
                return int((f.read() or "0").strip() or 0)
        except Exception:
            return 0

    def _invoice_bump(self, n):
        try:
            if int(n) > self._invoice_highwater():
                with open(self._invoice_counter_path(), "w", encoding="utf-8") as f:
                    f.write(str(int(n)))
        except Exception:
            pass

    def next_invoice_no(self):
        # v5.0: MAX+1, not COUNT+1 — deleted/returned sales no longer
        # recycle a number, and the UNIQUE index (migration) enforces it.
        row = self.conn.execute(
            "SELECT MAX(CAST(SUBSTR(invoice_no,5) AS INTEGER)) m "
            "FROM sales WHERE invoice_no LIKE 'INV-%'").fetchone()
        n = max(int(row["m"] or 0), self._invoice_highwater())
        return "INV-%06d" % (n + 1)

    def _validate_sale_lines(self, items):
        """v5.7: one validation for every sale/edit path (PC, mobile,
        edit). Returns (lines, subtotal) where lines are
        (drug, pack_level, qty_disp, qty_units, unit_price, line_total).
        Rejects: fractional qty at ANY pack level (a 0.5 pill used to
        be charged but 0 units deducted), negative/non-finite prices.
        Lines with qty<=0 are skipped; an all-skipped list is an
        empty invoice."""
        subtotal = 0.0
        lines = []
        for it in items:
            drug = it["drug"]
            try:
                qty_disp = float(it["qty_display"])
            except (TypeError, ValueError):
                raise ValueError("كمية غير صالحة في الفاتورة")
            if qty_disp <= 0:
                continue
            if qty_disp != int(qty_disp):
                raise ValueError("الكمية يجب أن تكون عدداً صحيحاً (بدون كسور) — حتى للحبة الواحدة")
            if it["pack_level"] not in allowed_units(drug):
                raise ValueError("الوحدة %s غير متاحة لهذا الشكل الصيدلاني" % it["pack_level"])
            # v6.16: an explicit "unit_price" on the line is the price
            # the cashier SAW for that line (the phone invoice-edit
            # flow prices existing lines at what they were sold at —
            # see edit_sale_from_items). Without it the edit silently
            # re-priced old lines at TODAY'S catalog price after any
            # price update: the phone showed one total, the server
            # saved another, and cash approvals could be rejected with
            # "المدفوع أقل من الإجمالي". No create path sends this key,
            # so selling prices stay catalog-driven.
            if it.get("unit_price") is not None:
                try:
                    up = float(it["unit_price"])
                except (TypeError, ValueError):
                    raise ValueError("سعر بيع غير صالح للدواء %s" % drug.get("trade_en", ""))
            else:
                up = unit_price(drug, it["pack_level"])
            if up < 0 or not math.isfinite(up):
                raise ValueError("سعر بيع غير صالح للدواء %s" % drug.get("trade_en", ""))
            qty_units = units_for_qty(drug, it["pack_level"], qty_disp)
            # v6.3: per-line discount. An explicit "discount" on the
            # item is the TOTAL for the line (PC cart / phone edit,
            # where the cashier may have changed or removed it).
            # Without one, the drug's own default discount applies
            # automatically. line_total is NET of the line discount,
            # so subtotal (and profit, which uses line_total) already
            # counts it — the sale-level discount stays separate.
            if "discount" in it and it["discount"] is not None:
                try:
                    line_disc = _round(float(it["discount"]))
                except (TypeError, ValueError):
                    raise ValueError("خصم سطر غير صالح")
                if line_disc < 0 or line_disc > _round(up * qty_disp):
                    raise ValueError("خصم السطر يجب أن يكون بين صفر وإجمالي السطر")
            else:
                line_disc = drug_default_line_discount(drug, up, qty_disp)
            line_total = _round(up * qty_disp - line_disc)
            if line_total < 0:
                raise ValueError("إجمالي سطر غير صالح")
            subtotal += line_total
            lines.append((drug, it["pack_level"], qty_disp, qty_units, up, line_total, line_disc))
        if not lines:
            raise ValueError("الفاتورة فارغة")
        return lines, subtotal

    def _check_credit(self, customer_id, new_unpaid, old_unpaid=0.0, old_customer_id=None):
        """v5.7: credit rules in one place, enforced for PC, mobile and
        edit alike (they used to live only in the PC POS dialog):
        a customer must exist, and balance + new unpaid must stay
        within the credit limit (limit 0 = unlimited, as before)."""
        if not customer_id:
            raise ValueError("البيع الآجل يحتاج عميل مسجل")
        row = self.conn.execute("SELECT id, balance, credit_limit FROM customers WHERE id=?",
                                (customer_id,)).fetchone()
        if not row:
            raise ValueError("العميل غير موجود")
        limit = float(row["credit_limit"] or 0)
        if limit > 0:
            base = float(row["balance"] or 0)
            if old_customer_id == customer_id:
                base -= float(old_unpaid or 0)
            if base + float(new_unpaid or 0) > limit:
                raise ValueError("العميل وصل لحد الائتمان المسموح (%.2f ج.م)" % limit)
        return row

    def _split_lines(self, c, sale_id, invoice_no, lines, cashier):
        """v5.7: deduct FEFO and write sale_items. The LAST split row
        takes the remainder, so split rows can no longer sum to 0.01
        more than the invoice total (each row used to be rounded alone)."""
        for drug, pack_level, qty_disp, qty_units, up, line_total, line_disc in lines:
            allocs = self._deduct_fefo(c, drug["id"], qty_units, cashier, invoice_no)
            qd_done = 0.0
            lt_done = 0.0
            ld_done = 0.0
            for k, (batch_id, taken, buy_unit) in enumerate(allocs):
                if k == len(allocs) - 1:
                    qd = _round(qty_disp - qd_done)
                    lt = _round(line_total - lt_done)
                    ld = _round(line_disc - ld_done)
                else:
                    frac = taken / qty_units
                    qd = _round(qty_disp * frac)
                    lt = _round(line_total * frac)
                    ld = _round(line_disc * frac)
                    qd_done += qd
                    lt_done += lt
                    ld_done += ld
                c.execute(
                    """INSERT INTO sale_items (sale_id, drug_id, batch_id, pack_level,
                    qty_display, qty_units, unit_price, buy_price_unit, line_total, line_discount)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (sale_id, drug["id"], batch_id, pack_level,
                     qd, taken, up, buy_unit, lt, ld))

    @_atomic
    def create_sale(self, cashier, items, discount=0.0, payment_method="cash",
                    customer_id=None, paid=None, shift_id=None, source="pc",
                    client_ref=""):
        """items: list of dicts {drug, pack_level, qty_display}.
        Returns (sale_id, invoice_no, total, change). Raises ValueError
        on insufficient stock / invalid amounts. All writes are in one
        transaction — any failure rolls everything back (v5.0).
        client_ref: optional mobile idempotency key — a retry with the
        same key returns the ORIGINAL sale instead of selling twice.
        v5.7: payment_method is whitelisted; credit needs a real
        customer and honours the credit limit; the customer balance
        grows by (total - paid), not by the full total; card/credit
        cannot be overpaid; a credit sale with no payment records
        paid=0 (it used to record paid=total while still adding the
        full debt)."""
        if payment_method not in ("cash", "card", "credit"):
            raise ValueError("طريقة دفع غير صالحة")
        if client_ref:
            row = self.conn.execute(
                "SELECT * FROM sales WHERE client_ref=?", (client_ref,)).fetchone()
            if row:
                return row["id"], row["invoice_no"], float(row["total"]), float(row["change_amount"])
        c = self.conn.cursor()
        lines, subtotal = self._validate_sale_lines(items)
        try:
            discount = float(discount or 0)
        except (TypeError, ValueError):
            raise ValueError("خصم غير صالح")
        if discount < 0 or discount > subtotal:
            raise ValueError("الخصم يجب أن يكون بين صفر والمجموع الفرعي")
        total = _round(max(0.0, subtotal - discount))
        if paid is None:
            paid = 0.0 if payment_method == "credit" else total
        try:
            paid = float(paid)
        except (TypeError, ValueError):
            raise ValueError("مبلغ مدفوع غير صالح")
        if paid < 0:
            raise ValueError("المبلغ المدفوع لا يمكن أن يكون سالباً")
        if payment_method in ("card", "credit") and paid > total:
            raise ValueError("المبلغ المدفوع أكبر من الإجمالي")
        if payment_method in ("cash", "card") and paid < total:
            raise ValueError("المبلغ المدفوع أقل من الإجمالي")
        if payment_method == "credit":
            self._check_credit(customer_id, total - paid)
        change = _round(max(0.0, paid - total)) if payment_method == "cash" else 0.0
        # Insert with retry: PC POS and the mobile server use different
        # connections and can both compute the same next number — the
        # UNIQUE index rejects the loser, we retry with a fresh number.
        sale_id = None
        invoice_no = None
        for _attempt in range(5):
            invoice_no = self.next_invoice_no()
            try:
                c.execute(
                    """INSERT INTO sales (invoice_no, date, cashier, customer_id, subtotal,
                    discount, total, paid, change_amount, payment_method, status, shift_id, created_at,
                    source, printed_at, client_ref)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (invoice_no, _today(), cashier, customer_id, _round(subtotal),
                     _round(discount), total, _round(paid), change,
                     payment_method, "completed", shift_id, _now(),
                     source or "pc", "", client_ref or ""))
                sale_id = c.lastrowid
                break
            except sqlite3.IntegrityError:
                if _attempt == 4:
                    raise ValueError("تعذر إنشاء رقم فاتورة فريد — أعد المحاولة")
                continue
        self._split_lines(c, sale_id, invoice_no, lines, cashier)
        if payment_method == "credit" and customer_id:
            c.execute("UPDATE customers SET balance=balance+? WHERE id=?",
                      (_round(total - paid), customer_id))
        self.conn.commit()
        try:
            self._invoice_bump(int(invoice_no[4:]))
        except Exception:
            pass
        return sale_id, invoice_no, total, change

    def create_sale_from_items(self, cashier, items_spec, discount=0.0,
                               payment_method="cash", customer_id=None,
                               paid=None, shift_id=None, source="mobile",
                               client_ref=""):
        """Shared by PC POS and the mobile server: items_spec is a list
        of {drug_id, unit, qty} (unit = box/strip/pill). Drugs are
        resolved here, then the SAME create_sale() runs — same FEFO
        deduction, same stock checks, same profit math. No second
        copy of the sale formula exists."""
        if not isinstance(items_spec, list):
            raise ValueError("بيانات أصناف غير صالحة")
        items = []
        for spec in items_spec:
            if not isinstance(spec, dict):
                raise ValueError("بيانات صنف غير صالحة")
            try:
                drug_id = int(spec.get("drug_id"))
            except (TypeError, ValueError):
                raise ValueError("رقم دواء غير صالح")
            drug = self.get_drug(drug_id)
            if not drug:
                raise ValueError("دواء غير موجود (id=%s)" % drug_id)
            unit = (spec.get("unit") or "box")
            unit = str(unit).strip()
            if unit not in ("box", "strip", "pill"):
                # v5.7: an unknown unit used to silently default to the
                # most expensive pack (box) — fail loudly instead.
                raise ValueError("وحدة غير صالحة: %s" % unit)
            try:
                qty = float(spec.get("qty") or 0)
            except (TypeError, ValueError):
                raise ValueError("كمية غير صالحة")
            if qty <= 0:
                continue
            spec_item = {"drug": drug, "pack_level": unit,
                         "qty_display": qty}
            if "discount" in spec and spec.get("discount") is not None:
                spec_item["discount"] = spec.get("discount")
            items.append(spec_item)
        if not items:
            raise ValueError("الفاتورة فارغة")
        return self.create_sale(cashier, items, discount=discount,
                                payment_method=payment_method,
                                customer_id=customer_id, paid=paid,
                                shift_id=shift_id, source=source,
                                client_ref=client_ref)

    def pending_phone_invoices(self):
        """Phone invoices saved from the phone, not printed yet."""
        rows = self.conn.execute(
            """SELECT s.*, COALESCE(cu.name,'') AS customer_name FROM sales s
            LEFT JOIN customers cu ON cu.id=s.customer_id
            WHERE s.source='mobile' AND s.status='completed'
            AND (s.printed_at IS NULL OR s.printed_at='')
            ORDER BY s.id DESC""").fetchall()
        return [dict(r) for r in rows]

    def phone_invoices(self, limit=50):
        rows = self.conn.execute(
            """SELECT s.*, COALESCE(cu.name,'') AS customer_name FROM sales s
            LEFT JOIN customers cu ON cu.id=s.customer_id
            WHERE s.source='mobile' ORDER BY s.id DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_all_sales(self, date_from=None, date_to=None, source=None,
                      payment=None, customer="", invoice_no="", limit=500):
        """v4.2 — كل الفواتير (الأحدث أولاً) مع فلاتر اختيارية.
        date_from/date_to بصيغة YYYY-MM-DD (شامل). source: 'pc' أو
        'mobile' أو None للكل. payment: 'cash'/'card'/'credit' أو None.
        customer/invoice_no: بحث جزئي بالنص. item_count = عدد الأصناف."""
        if date_from:
            date_from = _validate_day(date_from)
        if date_to:
            date_to = _validate_day(date_to)
        sql = """SELECT s.*, COALESCE(cu.name,'') AS customer_name,
                 (SELECT COUNT(*) FROM sale_items si WHERE si.sale_id=s.id) AS item_count
                 FROM sales s LEFT JOIN customers cu ON cu.id=s.customer_id
                 WHERE 1=1"""
        params = []
        if date_from:
            sql += " AND s.date>=?"
            params.append(date_from)
        if date_to:
            sql += " AND s.date<=?"
            params.append(date_to)
        if source:
            sql += " AND s.source=?"
            params.append(source)
        if payment:
            sql += " AND s.payment_method=?"
            params.append(payment)
        if customer:
            sql += " AND cu.name LIKE ?"
            params.append("%" + customer + "%")
        if invoice_no:
            sql += " AND s.invoice_no LIKE ?"
            params.append("%" + invoice_no + "%")
        sql += " ORDER BY s.id DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def mark_printed(self, sale_id):
        # v5.7: was a silent no-op on unknown or returned sales.
        cur = self.conn.execute(
            "UPDATE sales SET printed_at=? WHERE id=? AND status='completed'",
            (_now(), sale_id))
        if cur.rowcount == 0:
            raise ValueError("لا يمكن طباعة هذه الفاتورة — غير موجودة أو مُرجعة")
        self.conn.commit()
        return True

    def get_sale(self, sale_id):
        row = self.conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        return dict(row) if row else None

    def get_sale_items(self, sale_id):
        rows = self.conn.execute(
            """SELECT si.*, d.trade_en, d.trade_ar FROM sale_items si
            JOIN drugs d ON d.id=si.drug_id WHERE si.sale_id=?
            ORDER BY si.id""", (sale_id,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def group_sale_items(items):
        """v6.10: group split FEFO rows into ONE display line per
        (drug_id, pack_level, unit_price).

        create_sale writes one sale_items row per batch allocation, so
        a drug sold from 2 batches has 2 rows for the same drug+unit.
        The raw rows stay in the DB (FEFO/restock accounting must not
        change); only the DISPLAY/EDIT view is grouped. Sums:
        qty_display, qty_units, line_total, line_discount. unit_price
        is the same on every split row; buy_price_unit is the
        qty-weighted average across the split rows, so profit shown
        for the grouped line is correct. batch_id is None: a grouped
        line is not one batch.
        """
        grouped = {}
        order = []
        for item in items:
            key = (item.get("drug_id"), item.get("pack_level"),
                   float(item.get("unit_price") or 0))
            cur = grouped.get(key)
            if cur is None:
                cur = dict(item)
                cur["batch_id"] = None
                cur["_w_buy"] = float(cur.get("buy_price_unit") or 0) * int(
                    cur.get("qty_units") or 0)
                grouped[key] = cur
                order.append(cur)
                continue
            qty = int(item.get("qty_units") or 0)
            cur["_w_buy"] += float(item.get("buy_price_unit") or 0) * qty
            cur["qty_display"] = _round(
                float(cur.get("qty_display") or 0) +
                float(item.get("qty_display") or 0))
            cur["qty_units"] = int(cur.get("qty_units") or 0) + qty
            cur["line_total"] = _round(
                float(cur.get("line_total") or 0) +
                float(item.get("line_total") or 0))
            cur["line_discount"] = _round(
                float(cur.get("line_discount") or 0) +
                float(item.get("line_discount") or 0))
        for cur in order:
            units = int(cur.get("qty_units") or 0)
            cur["buy_price_unit"] = _round(cur.pop("_w_buy") / units) if units else 0.0
        return order

    def get_grouped_sale_items(self, sale_id):
        """v6.10: the invoice lines as the user sees/edits them — one
        line per drug+unit, split FEFO rows merged (see group_sale_items).
        Use this for invoice detail, invoice editing and receipts.
        get_sale_items() keeps returning the raw split rows for
        restock/return accounting."""
        return self.group_sale_items(self.get_sale_items(sale_id))

    @_atomic
    def return_sale(self, sale_id, user, return_shift_id=None,
                    refund_method=None, reason=""):
        """Full return of a completed sale: restock batches, reverse credit.
        STEP2 (2B): the sale keeps its ORIGINAL shift_id — the return is
        recorded in sale_returns with return_shift_id, so the RETURNING
        shift's drawer records the refund and the original shift's
        history is never retroactively changed. return_shift_id=None
        means "same shift as the sale" (old callers, backfill-compatible).
        Raises ValueError on an unknown sale / already-returned sale /
        unknown returning shift. Writes sale_returns + audit_log in the
        same atomic transaction (v6.19 — every void is logged, from the
        PC dialog, the invoices list, or the mobile delete button)."""
        c = self.conn.cursor()
        sale = c.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not sale or sale["status"] != "completed":
            raise ValueError("لا يمكن إرجاع هذه الفاتورة")
        if return_shift_id is None:
            return_shift_id = sale["shift_id"]
        elif c.execute("SELECT id FROM shifts WHERE id=?",
                       (return_shift_id,)).fetchone() is None:
            raise ValueError("الوردية المُرجعة غير موجودة")
        items = c.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)).fetchall()
        for it in items:
            # v5.0: never restore stock blindly — if the original batch
            # is gone (deleted/NULL), recreate a return batch so the
            # refunded units are actually back in stock.
            cur = c.execute("UPDATE batches SET qty_units=qty_units+? WHERE id=?",
                            (it["qty_units"], it["batch_id"]))
            if cur.rowcount == 0:
                c.execute(
                    """INSERT INTO batches (drug_id, batch_no, expiry, qty_units,
                    buy_price_unit, created_at) VALUES (?,?,?,?,?,?)""",
                    (it["drug_id"], "RETURN-%s" % sale["invoice_no"], "",
                     it["qty_units"], it["buy_price_unit"], _now()))
                batch_id = c.lastrowid
            else:
                batch_id = it["batch_id"]
            c.execute(
                """INSERT INTO stock_movements (drug_id, batch_id, qty_units, kind, ref, user, created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (it["drug_id"], batch_id, it["qty_units"], "return",
                 sale["invoice_no"], user, _now()))
        if sale["payment_method"] == "credit" and sale["customer_id"]:
            # v5.7: reverse only the unpaid part (total - paid), matching
            # what create_sale adds. Pre-v5.7 credit sales had their
            # recorded paid corrected by the v5.7 migration.
            c.execute("UPDATE customers SET balance=balance-? WHERE id=?",
                      (_round(float(sale["total"]) - float(sale["paid"] or 0)),
                       sale["customer_id"]))
        c.execute("UPDATE sales SET status='returned' WHERE id=?", (sale_id,))
        # STEP2 (2B): the refund belongs to the RETURNING shift.
        c.execute(
            """INSERT INTO sale_returns (sale_id, invoice_no, return_shift_id,
            cashier, returned_at, refund_method, total_refunded, reason)
            VALUES (?,?,?,?,?,?,?,?)""",
            (sale_id, sale["invoice_no"], return_shift_id, user, _now(),
             refund_method or sale["payment_method"],
             _cash_refund(sale), reason or ""))
        # v6.19: every void is audit-logged inside the SAME transaction
        # (PC dialog, invoices list, mobile delete button — all callers).
        c.execute(
            "INSERT INTO audit_log (user, action, details, created_at) VALUES (?,?,?,?)",
            (user or "", "return_sale",
             sale["invoice_no"] + ((" — " + reason) if reason else ""), _now()))
        self.conn.commit()

    def sale_returns_for_shift(self, shift_id):
        """STEP2 (2B): returns whose refund was paid out of this shift."""
        rows = self.conn.execute(
            "SELECT * FROM sale_returns WHERE return_shift_id=? ORDER BY id",
            (shift_id,)).fetchall()
        return [dict(r) for r in rows]

    @_atomic
    def edit_sale(self, sale_id, user, items, discount=0.0, payment_method=None,
                  customer_id=None, paid=None):
        """Edit a COMPLETED invoice in ONE atomic transaction.

        items: list of dicts {drug, pack_level, qty_display} (same
        shape as create_sale). Returns dict with old/new totals,
        difference (new-old) and change.
        Stock logic: restock ALL old lines first (same batch-restore
        as return_sale — if the original batch is gone, a RETURN
        batch is recreated so the units really come back), then
        deduct the NEW lines with the SAME _deduct_fefo() the PC
        POS and the mobile server use. No parallel stock logic.
        Any failure (e.g. not enough stock for the new lines) rolls
        the whole edit back — the old invoice and its stock stay
        exactly as they were. Returned/cancelled invoices are
        refused. Invoice number and date never change; edited_at /
        edited_by are stamped, and the edit is written to audit_log.
        v5.7: payment_method=None keeps the sale's existing method
        (the old default "cash" silently converted a credit sale to
        cash); credit falls back to the sale's existing customer when
        the caller passes none (mobile edits of credit invoices used
        to always fail); the credit limit is checked against the
        post-edit balance; credit moves by (total - paid), not the
        full total; a printed invoice has printed_at cleared so it
        re-queues for reprint instead of keeping a stale print
        timestamp."""
        c = self.conn.cursor()
        sale = c.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not sale:
            raise ValueError("الفاتورة غير موجودة")
        if sale["status"] != "completed":
            raise ValueError("لا يمكن تعديل هذه الفاتورة — حالتها: %s (المُرجعة لا تُعدَّل)" % sale["status"])
        method = payment_method or sale["payment_method"]
        if method not in ("cash", "card", "credit"):
            raise ValueError("طريقة دفع غير صالحة")
        if customer_id is None and method == "credit":
            customer_id = sale["customer_id"]
        old_total = float(sale["total"])
        old_paid = float(sale["paid"] or 0)
        old_lines = c.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)).fetchall()
        # --- validate the NEW lines first (same rules as create_sale) ---
        lines, subtotal = self._validate_sale_lines(items)
        try:
            discount = float(discount or 0)
        except (TypeError, ValueError):
            raise ValueError("خصم غير صالح")
        if discount < 0 or discount > subtotal:
            raise ValueError("الخصم يجب أن يكون بين صفر والمجموع الفرعي")
        total = _round(max(0.0, subtotal - discount))
        if paid is None:
            paid = 0.0 if method == "credit" else total
        try:
            paid = float(paid)
        except (TypeError, ValueError):
            raise ValueError("مبلغ مدفوع غير صالح")
        if paid < 0:
            raise ValueError("المبلغ المدفوع لا يمكن أن يكون سالباً")
        if method in ("card", "credit") and paid > total:
            raise ValueError("المبلغ المدفوع أكبر من الإجمالي")
        if method in ("cash", "card") and paid < total:
            raise ValueError("المبلغ المدفوع أقل من الإجمالي")
        if method == "credit":
            self._check_credit(customer_id, total - paid,
                               old_unpaid=old_total - old_paid,
                               old_customer_id=sale["customer_id"])
        change = _round(max(0.0, paid - total)) if method == "cash" else 0.0
        # --- restock the OLD lines ---
        for it in old_lines:
            cur = c.execute("UPDATE batches SET qty_units=qty_units+? WHERE id=?",
                            (it["qty_units"], it["batch_id"]))
            if cur.rowcount == 0:
                c.execute(
                    """INSERT INTO batches (drug_id, batch_no, expiry, qty_units,
                    buy_price_unit, created_at) VALUES (?,?,?,?,?,?)""",
                    (it["drug_id"], "RETURN-%s" % sale["invoice_no"], "",
                     it["qty_units"], it["buy_price_unit"], _now()))
                batch_id = c.lastrowid
            else:
                batch_id = it["batch_id"]
            c.execute(
                """INSERT INTO stock_movements (drug_id, batch_id, qty_units, kind, ref, user, created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (it["drug_id"], batch_id, it["qty_units"], "edit_return",
                 sale["invoice_no"], user, _now()))
        # reverse old credit balance (unpaid part only)
        if sale["payment_method"] == "credit" and sale["customer_id"]:
            c.execute("UPDATE customers SET balance=balance-? WHERE id=?",
                      (_round(old_total - old_paid), sale["customer_id"]))
        c.execute("DELETE FROM sale_items WHERE sale_id=?", (sale_id,))
        # --- deduct the NEW lines (same FEFO as a new sale) ---
        self._split_lines(c, sale_id, sale["invoice_no"], lines, user)
        if method == "credit" and customer_id:
            c.execute("UPDATE customers SET balance=balance+? WHERE id=?",
                      (_round(total - paid), customer_id))
        c.execute(
            """UPDATE sales SET subtotal=?, discount=?, total=?, paid=?,
            change_amount=?, payment_method=?, customer_id=?,
            edited_at=?, edited_by=?, printed_at='' WHERE id=?""",
            (_round(subtotal), _round(discount), total, _round(paid), change,
             method, customer_id, _now(), user or "", sale_id))
        # v5.8: name the lines that were fully deleted / had their
        # quantity reduced, so the audit trail says exactly what the
        # approval removed (a pending deletion that was cancelled or
        # restored never reaches this code — no audit row for it).
        _old_g = {}
        for _it in old_lines:
            _k = (_it["drug_id"], _it["pack_level"])
            _old_g[_k] = _old_g.get(_k, 0.0) + float(_it["qty_display"] or 0)
        _new_g = {}
        for _d, _pl, _qd, _u, _pr, _t, _ld in lines:
            _k = (_d["id"], _pl)
            _new_g[_k] = _new_g.get(_k, 0.0) + float(_qd)
        _removed, _reduced = [], []
        for _k, _q in _old_g.items():
            _row = c.execute("SELECT trade_en FROM drugs WHERE id=?", (_k[0],)).fetchone()
            _nm = _row["trade_en"] if _row else ("دواء %s" % _k[0])
            if _k not in _new_g:
                _removed.append("%s x%s" % (_nm, _q))
            elif _new_g[_k] < _q - 1e-9:
                _reduced.append("%s: من x%s إلى x%s" % (_nm, _q, _new_g[_k]))
        # audit inside the same transaction (no commit here)
        old_desc = "; ".join("%s x%s" % (it["drug_id"], it["qty_display"]) for it in old_lines)
        new_desc = "; ".join("%s(%s) x%s" % (d["trade_en"], pl, qd) for d, pl, qd, _u, _p, _t, _ld in lines)
        c.execute(
            "INSERT INTO audit_log (user, action, details, created_at) VALUES (?,?,?,?)",
            (user or "", "edit_sale",
             "%s: %s -> %s | فرق: %s | قديم: %s | جديد: %s%s%s" % (
                 sale["invoice_no"], _round(old_total), total,
                 _round(total - old_total), old_desc, new_desc,
                 (" | حُذف نهائياً: " + "; ".join(_removed)) if _removed else "",
                 (" | قُلّلت كميته: " + "; ".join(_reduced)) if _reduced else ""), _now()))
        self.conn.commit()
        return {"sale_id": sale_id, "invoice_no": sale["invoice_no"],
                "old_total": old_total, "new_total": total,
                "difference": _round(total - old_total), "change": change}

    def edit_sale_from_items(self, sale_id, user, items_spec, discount=0.0,
                             payment_method=None, customer_id=None, paid=None):
        """Shared by PC and mobile edit: items_spec is a list of
        {drug_id, unit, qty} (unit = box/strip/pill). Resolves drugs
        here, then the SAME edit_sale() runs — same FEFO, same stock
        restock/deduct, same audit. No second copy of the logic.
        v5.7: payment_method=None keeps the existing method; an
        unknown unit raises instead of silently becoming a box."""
        if not isinstance(items_spec, list):
            raise ValueError("بيانات أصناف غير صالحة")
        # v6.16: prices of lines ALREADY on the invoice, so an edit
        # keeps what the phone screen shows (the invoice's saved
        # prices) instead of silently re-pricing at today's catalog.
        # Split FEFO rows of one line share one price; last wins is
        # fine. A missing invoice yields an empty map and edit_sale()
        # itself raises "الفاتورة غير موجودة".
        saved_price = {}
        try:
            for _r in self.get_sale_items(sale_id):
                saved_price[(int(_r["drug_id"]),
                             str(_r["pack_level"] or "box"))] = float(_r["unit_price"] or 0)
        except Exception:
            saved_price = {}
        items = []
        for spec in items_spec:
            if not isinstance(spec, dict):
                raise ValueError("بيانات صنف غير صالحة")
            try:
                drug_id = int(spec.get("drug_id"))
            except (TypeError, ValueError):
                raise ValueError("رقم دواء غير صالح")
            drug = self.get_drug(drug_id)
            if not drug:
                raise ValueError("دواء غير موجود (id=%s)" % drug_id)
            unit = (spec.get("unit") or spec.get("pack_level") or "box")
            unit = str(unit).strip()
            if unit not in ("box", "strip", "pill"):
                raise ValueError("وحدة غير صالحة: %s" % unit)
            try:
                qty = float(spec.get("qty") or spec.get("qty_display") or 0)
            except (TypeError, ValueError):
                raise ValueError("كمية غير صالحة")
            if qty <= 0:
                continue
            spec_item = {"drug": drug, "pack_level": unit, "qty_display": qty}
            # v6.16: a line that was already on the invoice keeps the
            # price it was sold at; only genuinely NEW lines get
            # today's catalog price.
            _saved = saved_price.get((drug_id, unit))
            if _saved is not None:
                spec_item["unit_price"] = _saved
            # v6.8: honour the explicit per-line discount (TOTAL for the
            # line) exactly like create_sale_from_items() does. It used
            # to be dropped here, so every phone edit silently re-priced
            # the old lines with the drug's CURRENT default discount and
            # the new total no longer matched what the phone showed
            # (-> "paid < total" rejections on approve). A line sent
            # without "discount" still gets the drug default.
            if "discount" in spec and spec.get("discount") is not None:
                spec_item["discount"] = spec.get("discount")
            items.append(spec_item)
        if not items:
            raise ValueError("الفاتورة فارغة — لا يمكن حفظ فاتورة بلا أصناف")
        return self.edit_sale(sale_id, user, items, discount=discount,
                              payment_method=payment_method,
                              customer_id=customer_id, paid=paid)

    def sale_detail(self, sale_id):
        """One invoice + its lines + customer name (PC + mobile)."""
        sale = self.get_sale(sale_id)
        if not sale:
            return None
        display_items = self.get_grouped_sale_items(sale_id)
        cust = ""
        if sale.get("customer_id"):
            row = self.conn.execute("SELECT name FROM customers WHERE id=?",
                                    (sale["customer_id"],)).fetchone()
            cust = row["name"] if row else ""
        sale["customer_name"] = cust
        sale["items"] = display_items
        return sale

    def sales_on(self, day=None):
        day = _validate_day(day) if day else _today()
        rows = self.conn.execute(
            """SELECT s.*, COALESCE(cu.name,'') AS customer_name FROM sales s
            LEFT JOIN customers cu ON cu.id=s.customer_id
            WHERE s.date=? ORDER BY s.id DESC""", (day,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- purchases / suppliers ----------
    def add_supplier(self, name, phone="", address=""):
        if not (name or "").strip():
            raise ValueError("اسم المورد مطلوب")
        c = self.conn.cursor()
        c.execute("INSERT INTO suppliers (name, phone, address, created_at) VALUES (?,?,?,?)",
                  (name.strip(), phone, address, _now()))
        self.conn.commit()
        return c.lastrowid

    def suppliers(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM suppliers ORDER BY name").fetchall()]

    def get_supplier(self, supplier_id):
        """Exact lookup by supplier ID (the number the user sees as
        #12 next to the name). Returns None when it does not exist."""
        try:
            sid = int(supplier_id)
        except (TypeError, ValueError):
            return None
        row = self.conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone()
        return dict(row) if row else None

    def search_suppliers(self, query=""):
        """v6.3: search suppliers by ID (exact, digits only) or by
        name / phone (partial). An unknown ID returns [] — the UI
        shows 'المورد غير موجود' instead of crashing."""
        q = (query or "").strip()
        if not q:
            return self.suppliers()
        if q.lstrip("#").isdigit():
            row = self.get_supplier(q.lstrip("#"))
            return [row] if row else []
        like = "%" + q + "%"
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM suppliers WHERE name LIKE ? OR phone LIKE ? ORDER BY name",
            (like, like)).fetchall()]

    @_atomic
    def record_purchase(self, supplier_id, invoice_no, items, paid=0.0, user=""):
        """items: list of {drug, qty_boxes, buy_price(box), sell_price(box or None),
        batch_no, expiry}. Creates batches and updates stock + prices.
        v5.7: the supplier must exist; qty is a whole number of boxes
        (fractional boxes used to be charged per box but stocked
        truncated); prices must be finite; expiry must be a valid
        date and not in the past; paid must be 0..total (a negative
        paid used to INCREASE the supplier debt)."""
        sup = self.conn.execute("SELECT id FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
        if not sup:
            raise ValueError("المورد غير موجود")
        for it in items:
            try:
                qty_f = float(it.get("qty_boxes") or 0)
                buy = float(it.get("buy_price") or 0)
                sell = float(it.get("sell_price") or 0) if it.get("sell_price") else 0.0
            except (TypeError, ValueError):
                raise ValueError("قيم رقمية غير صالحة في فاتورة الشراء")
            if qty_f <= 0 or qty_f != int(qty_f):
                raise ValueError("كمية الشراء يجب أن تكون عدداً صحيحاً من العلب أكبر من صفر")
            if not math.isfinite(buy) or buy < 0:
                raise ValueError("سعر الشراء غير صالح")
            if it.get("sell_price") and (not math.isfinite(sell) or sell < 0):
                raise ValueError("سعر البيع غير صالح")
            exp = _parse_expiry(it.get("expiry", ""))
            if exp and exp < _today():
                raise ValueError("تاريخ الصلاحية في الماضي — لا يمكن استلام تشغيلة منتهية")
            it["_expiry"] = exp
        try:
            paid = float(paid)
        except (TypeError, ValueError):
            raise ValueError("المبلغ المدفوع للمورد غير صالح")
        c = self.conn.cursor()
        total = 0.0
        for it in items:
            total += _round(float(it["qty_boxes"]) * float(it["buy_price"]))
        if paid < 0 or paid > total:
            raise ValueError("المبلغ المدفوع للمورد يجب أن يكون بين صفر وإجمالي الفاتورة")
        c.execute(
            """INSERT INTO purchases (supplier_id, invoice_no, date, total, paid, user, created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (supplier_id, invoice_no, _today(), _round(total), _round(paid), user, _now()))
        purchase_id = c.lastrowid
        for it in items:
            drug = it["drug"]
            qty_boxes = float(it["qty_boxes"])
            qty_units = int(qty_boxes * units_per_box(drug))
            buy_unit = _round(float(it["buy_price"]) / units_per_box(drug))
            c.execute(
                """INSERT INTO batches (drug_id, batch_no, expiry, qty_units,
                buy_price_unit, supplier_id, created_at) VALUES (?,?,?,?,?,?,?)""",
                (drug["id"], it.get("batch_no", ""), it.get("_expiry", ""),
                 qty_units, buy_unit, supplier_id, _now()))
            batch_id = c.lastrowid
            c.execute(
                """INSERT INTO purchase_items (purchase_id, drug_id, batch_id, qty_boxes,
                qty_units, buy_price, line_total) VALUES (?,?,?,?,?,?,?)""",
                (purchase_id, drug["id"], batch_id, qty_boxes, qty_units,
                 float(it["buy_price"]), _round(qty_boxes * float(it["buy_price"]))))
            c.execute(
                """INSERT INTO stock_movements (drug_id, batch_id, qty_units, kind, ref, user, created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (drug["id"], batch_id, qty_units, "purchase", invoice_no, user, _now()))
            # update prices from the invoice (cost always, sell only if given)
            if it.get("sell_price"):
                c.execute("UPDATE drugs SET buy_price=?, sell_price=? WHERE id=?",
                          (float(it["buy_price"]), float(it["sell_price"]), drug["id"]))
            else:
                c.execute("UPDATE drugs SET buy_price=? WHERE id=?",
                          (float(it["buy_price"]), drug["id"]))
        if paid < total:
            c.execute("UPDATE suppliers SET balance=balance+? WHERE id=?",
                      (_round(total - paid), supplier_id))
        self.conn.commit()
        return purchase_id, _round(total)

    @_atomic
    def pay_supplier(self, supplier_id, amount, user=""):
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise ValueError("مبلغ غير صالح")
        if amount <= 0:
            raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
        row = self.conn.execute("SELECT balance FROM suppliers WHERE id=?",
                                (supplier_id,)).fetchone()
        if not row:
            raise ValueError("المورد غير موجود")
        # v5.7: paying more than the debt used to drive the balance
        # negative (a false credit) — and a payment to a ghost id
        # used to write a false audit row.
        if amount > float(row["balance"] or 0):
            raise ValueError("المبلغ أكبر من الدين المستحق (%.2f ج.م)" % float(row["balance"] or 0))
        # v5.0: money move + audit in ONE transaction (was two).
        self.conn.execute("UPDATE suppliers SET balance=balance-? WHERE id=?",
                          (amount, supplier_id))
        self.conn.execute(
            "INSERT INTO audit_log (user, action, details, created_at) VALUES (?,?,?,?)",
            (user or "", "supplier_payment",
             "supplier %s paid %.2f" % (supplier_id, amount), _now()))
        self.conn.commit()

    @_atomic
    def create_purchase_return(self, supplier_id, drug_id, qty_units,
                               unit="pill", reason="", cashier="", batch_id=None):
        """STEP2 (2C): return stock to a supplier (expired / near-expiry /
        damaged). qty_units is in base units (pills); unit records the
        unit the qty was entered in (box/strip/pill). Deducts FEFO —
        nearest expiry first, INCLUDING expired batches (that is the
        point: expired stock goes back), dateless batches last — or
        from one chosen batch when batch_id is given. Never below zero.
        Total comes from the batches' own buy prices; the supplier
        balance is credited (balance -= total, may go negative: the
        supplier then owes the pharmacy). Audit-logged, atomic.
        Returns (return_id, total). Raises ValueError on qty<=0,
        unknown supplier/drug, a batch that is not this drug's, or
        insufficient stock."""
        try:
            qty_units = int(qty_units)
        except (TypeError, ValueError):
            raise ValueError("كمية المرتجع غير صالحة")
        if qty_units <= 0:
            raise ValueError("كمية المرتجع يجب أن تكون أكبر من صفر")
        if (unit or "pill") not in ("box", "strip", "pill"):
            raise ValueError("وحدة غير صالحة: %s" % unit)
        sup = self.conn.execute("SELECT id FROM suppliers WHERE id=?",
                                (supplier_id,)).fetchone()
        if not sup:
            raise ValueError("المورد غير موجود")
        drug = self.get_drug(drug_id)
        if not drug:
            raise ValueError("الدواء غير موجود")
        c = self.conn.cursor()
        if batch_id is not None:
            b = c.execute("SELECT * FROM batches WHERE id=?",
                          (batch_id,)).fetchone()
            if not b or int(b["drug_id"]) != int(drug_id):
                raise ValueError("التشغيلة المختارة ليست لهذا الدواء")
            if int(b["qty_units"]) < qty_units:
                raise ValueError("الكمية المطلوبة أكبر من مخزون التشغيلة (%d وحدة)"
                                 % int(b["qty_units"]))
            allocs = [(int(b["id"]), qty_units, float(b["buy_price_unit"] or 0))]
        else:
            # FEFO including expired batches (unlike _deduct_fefo,
            # which never sells expired stock): nearest expiry first,
            # dateless last.
            rows = c.execute(
                """SELECT * FROM batches WHERE drug_id=? AND qty_units>0
                ORDER BY (expiry='' OR expiry IS NULL) ASC, expiry ASC, id ASC""",
                (drug_id,)).fetchall()
            remaining = qty_units
            allocs = []
            for b in rows:
                if remaining <= 0:
                    break
                take = min(int(b["qty_units"]), remaining)
                allocs.append((int(b["id"]), take, float(b["buy_price_unit"] or 0)))
                remaining -= take
            if remaining > 0:
                raise ValueError("المخزون غير كافٍ لمرتجع المشتريات")
        total = _round(sum(take * buy for _, take, buy in allocs))
        c.execute(
            """INSERT INTO purchase_returns (supplier_id, drug_id, batch_id,
            qty_units, unit, buy_price, total, reason, returned_at, cashier)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (supplier_id, drug_id,
             batch_id if batch_id is not None else None,
             qty_units, unit or "pill",
             _round(total / qty_units) if qty_units else 0.0, total,
             (reason or "").strip(), _now(), cashier or ""))
        rid = c.lastrowid
        for b_id, take, _buy in allocs:
            c.execute("UPDATE batches SET qty_units=qty_units-? WHERE id=?",
                      (take, b_id))
            c.execute(
                """INSERT INTO stock_movements (drug_id, batch_id, qty_units,
                kind, ref, user, created_at) VALUES (?,?,?,?,?,?,?)""",
                (drug_id, b_id, -take, "purchase_return", "PR-%d" % rid,
                 cashier or "", _now()))
        c.execute("UPDATE suppliers SET balance=balance-? WHERE id=?",
                  (total, supplier_id))
        self.conn.commit()
        self.audit(cashier or "", "purchase_return",
                   "supplier %s drug %s qty_units %d total %.2f (%s)"
                   % (supplier_id, drug_id, qty_units, total, (reason or "").strip()))
        return rid, total

    def purchase_returns(self, day=None):
        """STEP2 (2C): purchase returns on a day (today by default),
        newest first, with supplier/drug names."""
        day = _validate_day(day) if day else _today()
        rows = self.conn.execute(
            """SELECT pr.*, COALESCE(s.name,'') AS supplier_name,
            COALESCE(d.trade_en,'') AS drug_name FROM purchase_returns pr
            LEFT JOIN suppliers s ON s.id=pr.supplier_id
            LEFT JOIN drugs d ON d.id=pr.drug_id
            WHERE date(pr.returned_at)=? ORDER BY pr.id DESC""",
            (day,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- customers ----------
    def add_customer(self, name, phone="", credit_limit=0.0, notes=""):
        if not (name or "").strip():
            raise ValueError("اسم العميل مطلوب")
        try:
            credit_limit = float(credit_limit or 0)
        except (TypeError, ValueError):
            raise ValueError("حد الائتمان غير صالح")
        if credit_limit < 0:
            raise ValueError("حد الائتمان لا يمكن أن يكون سالباً")
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO customers (name, phone, credit_limit, notes, created_at) VALUES (?,?,?,?,?)",
            (name.strip(), phone, float(credit_limit), notes, _now()))
        self.conn.commit()
        return c.lastrowid

    def customers(self, query=""):
        if query.strip():
            q = "%" + query.strip() + "%"
            rows = self.conn.execute(
                "SELECT * FROM customers WHERE name LIKE ? OR phone LIKE ? ORDER BY name",
                (q, q)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    @_atomic
    def customer_pay(self, customer_id, amount, user=""):
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise ValueError("مبلغ غير صالح")
        if amount <= 0:
            raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
        row = self.conn.execute("SELECT balance FROM customers WHERE id=?",
                                (customer_id,)).fetchone()
        if not row:
            raise ValueError("العميل غير موجود")
        if amount > float(row["balance"] or 0):
            raise ValueError("المبلغ أكبر من الدين المستحق (%.2f ج.م)" % float(row["balance"] or 0))
        # v5.0: money move + audit in ONE transaction (was two).
        self.conn.execute("UPDATE customers SET balance=balance-? WHERE id=?",
                          (amount, customer_id))
        # v5.7: also write the payments ledger row so the payment
        # shows up in the customer's history.
        self.conn.execute(
            "INSERT INTO customer_payments (customer_id, amount, user, created_at) VALUES (?,?,?,?)",
            (customer_id, amount, user, _now()))
        self.conn.execute(
            "INSERT INTO audit_log (user, action, details, created_at) VALUES (?,?,?,?)",
            (user or "", "customer_payment",
             "customer %s paid %.2f" % (customer_id, amount), _now()))
        self.conn.commit()

    def customer_history(self, customer_id):
        # v5.7: sales AND payments in one history (payments used to
        # be invisible — only in audit_log free text).
        rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM sales WHERE customer_id=? ORDER BY id DESC LIMIT 50",
            (customer_id,)).fetchall()]
        pays = self.conn.execute(
            "SELECT amount, created_at FROM customer_payments WHERE customer_id=? ORDER BY id DESC",
            (customer_id,)).fetchall()
        for p in pays:
            rows.append({"invoice_no": "💰 سداد", "date": (p["created_at"] or "")[:10],
                         "total": float(p["amount"] or 0), "status": "payment",
                         "payment_method": "payment", "paid": float(p["amount"] or 0)})
        rows.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
        return rows[:50]

    # ---------- shifts / expenses ----------
    def open_shift(self, cashier, opening_float=0.0):
        # v5.7: a cashier can no longer open a second shift while one
        # is open, and a negative opening float is rejected.
        try:
            opening_float = float(opening_float)
        except (TypeError, ValueError):
            raise ValueError("رصيد بداية الوردية غير صالح")
        if opening_float < 0:
            raise ValueError("رصيد بداية الوردية لا يمكن أن يكون سالباً")
        row = self.conn.execute(
            "SELECT id FROM shifts WHERE cashier=? AND status='open'",
            (cashier,)).fetchone()
        if row:
            raise ValueError("توجد وردية مفتوحة بالفعل لهذا الكاشير")
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO shifts (cashier, opened_at, opening_float, status, branch_id) VALUES (?,?,?,?,?)",
            (cashier, _now(), opening_float, "open", self.user_branch_id(cashier)))
        self.conn.commit()
        return c.lastrowid

    def active_shift_id(self):
        """STEP2 (2A): id of the currently open shift, if any — the
        most recently opened one, whatever cashier opened it (the
        phone has no cashier of its own). None when no shift is open.
        Never invents or closes a shift."""
        row = self.conn.execute(
            "SELECT id FROM shifts WHERE status='open' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None

    def sales_without_shift(self, day=None):
        """STEP2 (2A): completed sales with shift_id NULL on a day
        (today by default) — sales that no drawer reconciliation
        would otherwise see. PC sales with no open shift and mobile
        sales made while no shift was open land here."""
        day = _validate_day(day) if day else _today()
        rows = self.conn.execute(
            """SELECT s.*, COALESCE(cu.name,'') AS customer_name FROM sales s
            LEFT JOIN customers cu ON cu.id=s.customer_id
            WHERE s.shift_id IS NULL AND s.date=? AND s.status='completed'
            ORDER BY s.id""", (day,)).fetchall()
        return [dict(r) for r in rows]

    def shift_summary(self, shift_id):
        """v5.7: what the drawer SHOULD contain for one shift, computed
        from the shift's own sales (not the whole day, all cashiers).
        Cash sales count net of change; credit sales count only the
        cash actually received; card sales never touch the drawer;
        returned sales' cash is subtracted; this shift's expenses
        are subtracted.
        STEP2 (2B): refunds now come from sale_returns by
        return_shift_id — a sale returned in a LATER shift no longer
        rewrites this shift's history. A returned sale still counts
        in this shift's card total / credit-unpaid when the return
        happened in a DIFFERENT shift (the money was taken here).
        STEP2 (2A): no-shift sales are reported, never counted — the
        "مبيعات بدون وردية" line (same calendar day as the shift
        opened) so they are visible at close time."""
        row = self.conn.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
        if not row:
            raise ValueError("الوردية غير موجودة")
        c = self.conn.cursor()
        # Cash received counts EVERY sale of the shift (a returned
        # sale's cash was received at sale time AND refunded later —
        # counting only completed sales would lose the receipt and
        # understate the drawer by the full sale amount). Card totals
        # and unpaid credit count completed sales only — plus returned
        # sales whose refund was paid by a DIFFERENT shift.
        sales = c.execute(
            """SELECT s.payment_method, s.total, s.paid, s.change_amount, s.status,
            sr.return_shift_id AS ret_shift FROM sales s
            LEFT JOIN sale_returns sr ON sr.sale_id=s.id
            WHERE s.shift_id=? AND s.status IN ('completed','returned')""",
            (shift_id,)).fetchall()
        cash_collected = 0.0
        card_total = 0.0
        credit_unpaid = 0.0
        for s_ in sales:
            m = s_["payment_method"]
            returned_elsewhere = (
                s_["status"] == "returned" and s_["ret_shift"] is not None
                and int(s_["ret_shift"]) != int(shift_id))
            if m == "cash":
                cash_collected += float(s_["paid"] or 0) - float(s_["change_amount"] or 0)
            elif m == "card":
                if s_["status"] == "completed" or returned_elsewhere:
                    card_total += float(s_["total"] or 0)
            elif m == "credit":
                cash_collected += float(s_["paid"] or 0)
                if s_["status"] == "completed" or returned_elsewhere:
                    credit_unpaid += float(s_["total"] or 0) - float(s_["paid"] or 0)
        # STEP2 (2B): refunds are subtracted from the shift that PAID
        # them, not from the shift that made the original sale.
        refunds = c.execute(
            "SELECT COALESCE(SUM(total_refunded),0) r FROM sale_returns "
            "WHERE return_shift_id=?", (shift_id,)).fetchone()["r"]
        cash_collected -= float(refunds or 0)
        expenses = c.execute(
            "SELECT COALESCE(SUM(amount),0) e FROM expenses WHERE shift_id=?",
            (shift_id,)).fetchone()["e"]
        expected = _round(float(row["opening_float"] or 0) + cash_collected - float(expenses or 0))
        # STEP2 (2A): sales with no shift at all, same day the shift opened.
        opened_day = (row["opened_at"] or "")[:10] or _today()
        no_shift = c.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM sales "
            "WHERE shift_id IS NULL AND date=? AND status='completed'",
            (opened_day,)).fetchone()
        return {"shift_id": shift_id, "cashier": row["cashier"],
                "opening_float": _round(float(row["opening_float"] or 0)),
                "cash_collected": _round(cash_collected),
                "card_total": _round(card_total),
                "credit_unpaid": _round(credit_unpaid),
                "expenses": _round(float(expenses or 0)),
                "expected_cash": expected,
                "no_shift_date": opened_day,
                "no_shift_count": int(no_shift["n"] or 0),
                "no_shift_total": _round(float(no_shift["t"] or 0))}

    def open_shift_for(self, cashier):
        row = self.conn.execute(
            "SELECT * FROM shifts WHERE cashier=? AND status='open' ORDER BY id DESC LIMIT 1",
            (cashier,)).fetchone()
        return dict(row) if row else None

    def close_shift(self, shift_id, counted_cash=None):
        """v5.7: closes only an open shift (double-close and closing
        a ghost shift used to be silent no-ops). counted_cash is the
        cash the cashier actually counted; expected/difference are
        computed from shift_summary() and stored for the audit trail.
        Returns the summary dict."""
        if counted_cash is None:
            raise ValueError("أدخل المبلغ الذي عدّدته في الدرج")
        try:
            counted_cash = float(counted_cash)
        except (TypeError, ValueError):
            raise ValueError("مبلغ الدرج غير صالح")
        if counted_cash < 0:
            raise ValueError("مبلغ الدرج لا يمكن أن يكون سالباً")
        summ = self.shift_summary(shift_id)
        cur = self.conn.execute(
            """UPDATE shifts SET closed_at=?, cash_total=?, card_total=?,
            credit_total=?, expected_cash=?, counted_cash=?, difference=?,
            status='closed' WHERE id=? AND status='open'""",
            (_now(), counted_cash, summ["card_total"], summ["credit_unpaid"],
             summ["expected_cash"], counted_cash,
             _round(counted_cash - summ["expected_cash"]), shift_id))
        if cur.rowcount == 0:
            raise ValueError("الوردية غير موجودة أو مغلقة بالفعل")
        self.conn.commit()
        summ["counted_cash"] = _round(counted_cash)
        summ["difference"] = _round(counted_cash - summ["expected_cash"])
        return summ

    def add_expense(self, kind, amount, notes="", user="", shift_id=None):
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise ValueError("مبلغ المصروف غير صالح")
        if amount <= 0:
            raise ValueError("مبلغ المصروف يجب أن يكون أكبر من صفر")
        if not (kind or "").strip():
            raise ValueError("نوع المصروف مطلوب")
        self.conn.execute(
            "INSERT INTO expenses (date, kind, amount, notes, user, shift_id) VALUES (?,?,?,?,?,?)",
            (_today(), kind.strip(), amount, notes, user, shift_id))
        self.conn.commit()

    def expenses_on(self, day=None):
        rows = self.conn.execute(
            "SELECT * FROM expenses WHERE date=? ORDER BY id DESC", (day or _today(),)).fetchall()
        return [dict(r) for r in rows]

    # ---------- reports ----------
    def report_employee_sales(self, date_from, date_to):
        """Current invoice-cohort report, by original sale date/cashier.
        Returned invoices are excluded from eligible completed sales.
        Not a historical payout ledger: edits/returns can change totals.
        """
        date_from, date_to = _validate_day(date_from), _validate_day(date_to)
        if date_from > date_to:
            raise ValueError("تاريخ البداية بعد النهاية")
        rows = self.conn.execute("""
            SELECT s.cashier AS employee, COALESCE(u.full_name,'') AS full_name,
              COUNT(*) AS invoice_count,
              SUM(CASE WHEN s.status='completed' THEN 1 ELSE 0 END) AS completed_count,
              SUM(CASE WHEN s.status='returned' THEN 1 ELSE 0 END) AS returned_count,
              ROUND(SUM(CASE WHEN s.status='completed' THEN s.total ELSE 0 END),2) AS completed_sales,
              ROUND(SUM(CASE WHEN s.status='returned' THEN s.total ELSE 0 END),2) AS returned_sales,
              ROUND(SUM(CASE WHEN s.status='completed' AND s.source='mobile' THEN s.total ELSE 0 END),2) AS mobile_sales,
              SUM(CASE WHEN s.source='mobile' THEN 1 ELSE 0 END) AS mobile_count
            FROM sales s LEFT JOIN users u ON u.username=s.cashier
            WHERE s.date>=? AND s.date<=?
            GROUP BY s.cashier ORDER BY s.cashier
        """, (date_from, date_to)).fetchall()
        return [dict(r) for r in rows]

    def report_daily(self, day=None):
        day = _validate_day(day) if day else _today()
        sales = self.conn.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(total),0) total,
            COALESCE(SUM(CASE WHEN payment_method='cash' THEN total ELSE 0 END),0) cash,
            COALESCE(SUM(CASE WHEN payment_method='card' THEN total ELSE 0 END),0) card,
            COALESCE(SUM(CASE WHEN payment_method='credit' THEN total ELSE 0 END),0) credit
            FROM sales WHERE date=? AND status='completed'""", (day,)).fetchone()
        # v5.7: profit used to ignore discounts — a 10 EGP discount
        # overstated profit by exactly 10 EGP.
        profit = self.conn.execute(
            """SELECT COALESCE(SUM(line_total - qty_units*buy_price_unit),0) p
            FROM sale_items si JOIN sales s ON s.id=si.sale_id
            WHERE s.date=? AND s.status='completed'""", (day,)).fetchone()
        disc = self.conn.execute(
            "SELECT COALESCE(SUM(discount),0) d FROM sales WHERE date=? AND status='completed'",
            (day,)).fetchone()
        profit_p = _round(float(profit["p"] or 0) - float(disc["d"] or 0))
        exp = self.conn.execute(
            "SELECT COALESCE(SUM(amount),0) e FROM expenses WHERE date=?", (day,)).fetchone()
        # STEP2 (2C): purchase returns for the day (stock sent back to suppliers).
        pr = self.conn.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM purchase_returns
            WHERE date(returned_at)=?""", (day,)).fetchone()
        return {"date": day, "count": sales["n"], "total": _round(sales["total"]),
                "cash": _round(sales["cash"]), "card": _round(sales["card"]),
                "credit": _round(sales["credit"]), "profit": profit_p,
                "expenses": _round(exp["e"]),
                "net_profit": _round(profit_p - exp["e"]),
                "purchase_returns_count": int(pr["n"] or 0),
                "purchase_returns_total": _round(float(pr["t"] or 0))}

    def report_best_sellers(self, day=None, limit=20):
        # v5.0: the day argument is honoured now (was ignored — the
        # "أكثر مبيعاً اليوم" cards showed all-time totals).
        if day:
            day = _validate_day(day)
        sql = """SELECT d.trade_en, d.trade_ar, SUM(si.qty_units) units,
            SUM(si.line_total) total FROM sale_items si
            JOIN sales s ON s.id=si.sale_id JOIN drugs d ON d.id=si.drug_id
            WHERE s.status='completed'"""
        params = []
        if day:
            sql += " AND s.date=?"
            params.append(day)
        sql += " GROUP BY si.drug_id ORDER BY total DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def report_inventory_value(self):
        rows = self.conn.execute(
            """SELECT d.trade_en, d.trade_ar, SUM(b.qty_units) units,
            SUM(b.qty_units*b.buy_price_unit) cost_value,
            SUM(b.qty_units * d.sell_price / (d.strips_per_box*d.tablets_per_strip)) sell_value
            FROM batches b JOIN drugs d ON d.id=b.drug_id
            WHERE b.qty_units>0 GROUP BY b.drug_id ORDER BY cost_value DESC""").fetchall()
        out = [dict(r) for r in rows]
        total_cost = _round(sum(r["cost_value"] or 0 for r in out))
        total_sell = _round(sum(r["sell_value"] or 0 for r in out))
        return out, total_cost, total_sell

    def audit_list(self, limit=200):
        rows = self.conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def audit_query(self, text="", action="", user="", limit=200):
        """v6.13: سجل التدقيق بفلاتر — نص حر (في التفاصيل أو المستخدم)،
        نوع الإجراء، المستخدم، وحد أقصى للصفوف (الأحدث أولاً)."""
        sql = "SELECT * FROM audit_log WHERE 1=1"
        args = []
        if text:
            sql += " AND (details LIKE ? OR user LIKE ?)"
            args += ["%" + text + "%", "%" + text + "%"]
        if action:
            sql += " AND action=?"
            args.append(action)
        if user:
            sql += " AND user=?"
            args.append(user)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def audit_actions(self):
        """أنواع الإجراءات الموجودة فعلاً في السجل (لقائمة الفلتر)."""
        rows = self.conn.execute(
            "SELECT DISTINCT action FROM audit_log ORDER BY action").fetchall()
        return [r[0] for r in rows]

    def audit_count(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    # ---------- CSV import / export / backup ----------
    def export_drugs_csv(self, path):
        rows = self.conn.execute("SELECT * FROM drugs WHERE active=1 ORDER BY trade_en").fetchall()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["trade_en", "trade_ar", "scientific", "company", "form", "strength",
                        "category", "strips_per_box", "tablets_per_strip",
                        "buy_price", "sell_price", "min_stock", "barcode",
                        "discount_type", "discount_value", "stock_units"])
            for r in rows:
                bc = self.conn.execute(
                    "SELECT barcode FROM barcodes WHERE drug_id=? AND pack_level='box' LIMIT 1",
                    (r["id"],)).fetchone()
                stock = self.conn.execute(
                    "SELECT COALESCE(SUM(qty_units),0) s FROM batches WHERE drug_id=? AND qty_units>0",
                    (r["id"],)).fetchone()["s"]
                w.writerow([r["trade_en"], r["trade_ar"], r["scientific"], r["company"],
                            r["form"], r["strength"], r["category"], r["strips_per_box"],
                            r["tablets_per_strip"], r["buy_price"], r["sell_price"],
                            r["min_stock"], bc["barcode"] if bc else "",
                            r["discount_type"] if "discount_type" in r.keys() else "none",
                            r["discount_value"] if "discount_value" in r.keys() else 0,
                            int(stock or 0)])
        return len(rows)

    @_atomic
    def import_drugs_csv(self, path, user=""):
        """v5.0: the WHOLE file is validated first (bad row = nothing
        imported, with the row number in the error), then all rows are
        written in ONE transaction — a bad file can no longer leave a
        half-imported catalogue behind."""
        parsed = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for lineno, row in enumerate(reader, start=2):
                name = (row.get("trade_en") or "").strip()
                if not name:
                    # v5.7: skip only a fully blank row; a row with
                    # data but no name used to vanish silently.
                    if not any((v or "").strip() for v in row.values() if v is not None):
                        continue
                    raise ValueError("خطأ في السطر %d: الاسم التجاري مفقود" % lineno)
                try:
                    def _int_field(raw, default):
                        f = float(raw or default)
                        if f != int(f):
                            raise ValueError("يجب أن يكون عدداً صحيحاً")
                        return int(f)
                    fields = {
                        "trade_en": name, "trade_ar": (row.get("trade_ar") or "").strip(),
                        "scientific": (row.get("scientific") or "").strip(),
                        "company": (row.get("company") or "").strip(),
                        "form": (row.get("form") or "").strip(),
                        "strength": (row.get("strength") or "").strip(),
                        "category": (row.get("category") or "").strip(),
                        "strips_per_box": _int_field(row.get("strips_per_box"), 1),
                        "tablets_per_strip": _int_field(row.get("tablets_per_strip"), 1),
                        "buy_price": float(row.get("buy_price") or 0),
                        "sell_price": float(row.get("sell_price") or 0),
                        "min_stock": _int_field(row.get("min_stock"), 5),
                        "barcode": (row.get("barcode") or "").strip(),
                        "discount_type": (row.get("discount_type") or "none").strip().lower(),
                        "discount_value": row.get("discount_value") or 0,
                    }
                    self._validate_drug_fields(fields)
                except ValueError as e:
                    raise ValueError("خطأ في السطر %d (%s): %s" % (lineno, name, e))
                except Exception:
                    raise ValueError("خطأ في السطر %d (%s): قيمة رقمية غير صالحة" % (lineno, name))
                parsed.append(fields)
        added, updated = 0, 0
        for fields in parsed:
            existing = self.conn.execute(
                "SELECT id FROM drugs WHERE trade_en=? AND strength=?",
                (fields["trade_en"], fields["strength"])).fetchone()
            if existing:
                self.update_drug(existing["id"], fields, _commit=False)
                if fields["barcode"]:
                    # v5.7: a barcode that belongs to another drug is
                    # now an error, not a silently dropped row.
                    self._link_barcode_checked(self.conn, fields["barcode"], existing["id"])
                updated += 1
            else:
                self.add_drug(fields, _commit=False)
                added += 1
        self.conn.execute(
            "INSERT INTO audit_log (user, action, details, created_at) VALUES (?,?,?,?)",
            (user or "", "import_drugs",
             "added %d updated %d from %s" % (added, updated, path), _now()))
        self.conn.commit()
        return added, updated

    @staticmethod
    def verify_backup(path):
        """Return True only if path is a readable SQLite DB that passes
        integrity_check. Used before any restore."""
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
            try:
                row = conn.execute("PRAGMA integrity_check").fetchone()
                conn.execute("SELECT COUNT(*) FROM drugs").fetchone()
                return bool(row and row[0] == "ok")
            finally:
                conn.close()
        except Exception:
            return False

    def backup(self, suffix=""):
        """v5.0: atomic backup via the sqlite3 backup API (no torn copy
        of a live DB), integrity-checked, and pruned to the newest 10
        backups (pre-migration backups are always kept). Backups live
        next to the database file itself."""
        base = os.path.dirname(os.path.abspath(self.path))
        folder = os.path.join(base, "backups")
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(folder, "pharmacy_%s%s.db" % (stamp, suffix))
        self.conn.commit()
        dest_conn = sqlite3.connect(dest)
        try:
            self.conn.backup(dest_conn)
            row = dest_conn.execute("PRAGMA integrity_check").fetchone()
            if not row or row[0] != "ok":
                raise IOError("فشل التحقق من سلامة النسخة الاحتياطية")
        finally:
            dest_conn.close()
        # prune: keep newest 10 regular backups, always keep pre-migration
        try:
            files = [os.path.join(folder, f) for f in os.listdir(folder)
                     if f.startswith("pharmacy_") and f.endswith(".db")
                     and "pre_migration" not in f]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for old in files[10:]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass
        return dest

    # ---------- v2: forecast cache (optional, rebuildable) ----------
    def cache_forecast(self, drug_id, horizon_days, predicted_daily,
                       predicted_total, confidence):
        self.conn.execute(
            """INSERT OR REPLACE INTO forecast_cache
            (drug_id, horizon_days, predicted_daily, predicted_total,
            confidence, computed_at) VALUES (?,?,?,?,?,?)""",
            (int(drug_id), int(horizon_days), float(predicted_daily),
             float(predicted_total), int(confidence), _now()))
        self.conn.commit()

    def cached_forecast(self, drug_id):
        row = self.conn.execute(
            "SELECT * FROM forecast_cache WHERE drug_id=?", (int(drug_id),)).fetchone()
        return dict(row) if row else None

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    db = DB()
    print("drugs:", len(db.search_drugs("", limit=10000)))
    print("low stock:", len(db.low_stock()))
    print("near expiry 90d:", len(db.near_expiry(90)))
    db.close()
