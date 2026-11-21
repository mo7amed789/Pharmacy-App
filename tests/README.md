# Tests — الاختبارات

Stdlib only — no new packages to install. Run from the app root.

## Run everything

```bat
py tests\run_all.py
```

```bash
python3 tests/run_all.py
```

Exit 0 only if ALL suites pass.

## Suites

| File | What it covers | Style |
|---|---|---|
| `test_business.py` | FEFO, unit conversion (box/strip/pill), shift/drawer math, credit limits, partial payments, PIN header-only auth, PWA routes, cert resolution (certs/ first, root fallback) | stdlib `unittest` |
| `test_v57.py` | v5.7 business-logic review verification (34 groups: expired stock, credit balance = total − paid, shift reconciliation, profit, CSV strictness, …) | legacy check-style script |
| `test_v58.py` | v5.8 staged-deletion verification (DB edit + server approval gate) | legacy check-style script |
| `test_server_v57.py` | Mobile server HTTP checks (PIN lockout, strict validation, XSS gone from served page) | legacy check-style script |

The v5.7 and v5.8 suites existed before this step — they were written
during the review work and are copied in here (paths adapted from the
old `src/` / `/tmp/v58` layouts to the app root), not rewritten.
The audit claim "no tests shipped with the app" was about the shipped
folder, not about tests never having existed.

## Run one suite

```bat
py -m unittest discover -s tests -p "test_business.py" -v
py tests\test_v57.py
py tests\test_v58.py
py tests\test_server_v57.py
```

## Notes

- Every suite uses throwaway databases (temp dirs, or `tests/dbs/`
  and `tests/srv/` under this folder) — never the real `pharmacy.db`.
- `tests/dbs/` and `tests/srv/` are scratch output, ignored by
  `.gitignore`; safe to delete at any time.
- The server suites start the real mobile server on test ports
  (18080–18082 / 18443–18445) and stop it again.
