# Pharmacy Enterprise — نظام إدارة صيدلية

Offline-first pharmacy management app for Windows, Arabic-first UI, in Egyptian pounds (EGP).
Built with Python standard library only (Tkinter + SQLite) — no pip packages, no venv.

**Version: v6.9.1**

## Features

- POS by barcode (box / strip / pill), FEFO stock deduction, alternatives
- Inventory with batches, expiry dates, low-stock and near-expiry alerts
- Purchases, suppliers and supplier debts; purchase returns
- Customers, credit sales and credit limits, loyalty
- Cash, shifts and expenses, shift reconciliation
- Reports (sales, profit, best sellers, stock value, shortages, expiry)
- Mobile companion page over local Wi-Fi / hotspot (phone creates invoices, PC prints them)
  - Camera barcode scan, auto flash, auto-PIN via QR scan, remember-this-device
  - HTTPS on port 8443 (self-signed cert, generated on first start)
- AI stock forecasting (local, offline, no API key)
- Invoice editing before printing and later, with staged deletion (approve to apply)
- Per-drug discount, pharmacy barcode labels (real EAN-13), supplier search by ID
- Users and permissions, backup and restore

## Install (Windows)

1. Install Python 3.11+ from python.org (check "Add python.exe to PATH" — or use the `py` launcher).
2. Download / clone this repository into a new folder, e.g. `C:\Users\mohamed\Desktop\pharmacy-enterprise`.
3. Run `run.bat` **as administrator** the first time.
4. Log in with `admin` / `admin123` (or `cashier` / `cashier123`) — you will be **forced to change the default password** on first login. Do this for both accounts.
5. Enter your real data in order: pharmacy name in Settings → drugs (or import CSV, see `drugs_template.csv`) → suppliers → credit customers → opening stock via a purchase invoice (batch + expiry + quantity) → test sale + print + backup + phone test.

This is an **empty install**: 0 drugs, 0 sales, 0 customers. No real pharmacy data is shipped.

## Security notes

- Never commit `pharmacy.db`, `backups/`, `certs/`, `*.pem`, `*.log` or `DEFAULT_LOGINS.txt` — they are in `.gitignore` for a reason. Your live database stays on your own PC only.
- The mobile PIN is stored in the local database and shown only to the admin on the PC. The QR code contains it — do not share a QR screenshot outside the pharmacy, and regenerate the PIN if it leaks.
- Change both default passwords on first login and delete `DEFAULT_LOGINS.txt` if you ever create one.

## Cloud sync (Supabase) — v6.11

The app can now sync its product catalog with a Supabase cloud database
(the same one the Egyptian drugs/cosmetics catalogs live in):

- **Automatic push:** any product added or edited in the app is upserted to
  the cloud in the background (best effort — offline just records the error
  in Settings and never blocks a sale). The cloud key is
  `(catalog, trade_en, strength)`, so re-syncing never duplicates rows.
- **Pull:** Settings → ☁️ المزامنة السحابية → «سحب الكتالوج من السحابة»
  downloads all cloud products and updates local prices without duplicates
  (same merge logic as CSV import). Stock, batches, sales and users stay
  local — the cloud stores catalog/price data only.
- **Push all:** «رفع كل الأصناف المحلية للسحابة» uploads every local
  product in batches, preserving each row's catalog (drug vs cosmetic).

### Setup (one time, per PC)

1. Copy `supabase_config.example.json` to `supabase_config.json` next to
   `main.py` and fill in your project URL and publishable API key
   (Supabase dashboard → Project Settings → API Keys).
   Environment variables `SUPABASE_URL` / `SUPABASE_KEY` work too and take
   priority. `supabase_config.json` is git-ignored — never commit the key.
2. Restart the app. The Settings → ☁️ section shows sync status and the
   last error if the PC was offline.

Files: `supabase_client.py` (stdlib-only PostgREST client),
`cloud_sync.py` (mapping + push/pull), `tests/test_cloud_sync.py`
(local tests plus a live API round-trip that runs when the env vars are set).

## Auto-update from GitHub — v6.12

The installed app can update itself when new code lands on `main`:

- On every startup it quietly checks the repo's latest commit (public repo,
  no key needed). A banner appears only when an update exists.
- Settings → 🔄 تحديثات البرنامج: "check now", "download & install", and a
  status line (installed version, last check, last error).
- Installs overlay code files only. The local database, `supabase_config.json`,
  backups, certs, receipts and logs are never touched; every replaced file is
  backed up under `backups/code_update_*/` and a mid-update failure rolls
  everything back and shows a clear Arabic error. Restart the app after
  installing.

Files: `updater.py`, Settings section in `main.py`, `tests/test_updater.py`.

## Full Arabic guide

See `README_AR.md` (and `README_AR_V6.9.md` for the latest changes).
