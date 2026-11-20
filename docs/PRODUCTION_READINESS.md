# Pharmacy Enterprise — production readiness

## Verified in this checkout

- The mobile companion serves both HTTP `8080` and HTTPS `8443` when the
  local certificate is available.
- QR links prefer HTTPS and carry the mobile PIN only in the URL fragment
  (`#pin=...`). The PIN is not sent in requests or written to request logs.
- The live scanner uses the phone's rear camera over HTTPS, with local ZXing
  fallback, torch handling, camera cleanup, and photo capture fallback.
- Pharmaceutical-form unit rules are enforced by the database and reflected
  by the desktop and mobile interfaces.
- Security headers are enabled; wildcard CORS is not enabled; API calls still
  require `X-Mobile-PIN`.

## Run the verification suite

From this folder:

```bat
py tests\run_all.py
```

The suite must finish with `ALL SUITES PASSED`.

## Live scan on a phone

1. Start the desktop app with `run.bat`.
2. Start the mobile server from the Mobile tab and use the HTTPS URL shown by
   the app, ending in `:8443`.
3. On the phone's first visit, choose **Advanced → Proceed** for the local
   self-signed certificate.
4. Scan the QR shown by the desktop app, or open the HTTPS URL and enter the
   six-digit PIN.
5. Tap **مسح الباركود** and allow camera access. If the browser cannot grant
   live camera access, use **صوّر الباركود** as the supported fallback.

HTTP remains available for invoices, but browsers intentionally block live
camera APIs in an insecure context. The page offers a button to open the same
host's HTTPS scanner and preserves the PIN fragment.

## Before external deployment

This application is designed for a trusted pharmacy LAN, not public internet
exposure. Before a real rollout:

- change the default desktop passwords and remove `DEFAULT_LOGINS.txt`;
- keep `pharmacy.db`, `key.pem`, `cert.pem`, logs, backups, and `certs/` out of
  source archives and version control;
- replace the local self-signed certificate with a certificate trusted by the
  managed devices if the network policy requires it;
- verify Windows Firewall rules, database backup/restore, printer output, and
  a real Android/iPhone camera on the target Wi-Fi;
- never forward ports `8080` or `8443` to the public internet.
