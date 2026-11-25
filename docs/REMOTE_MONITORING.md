# Owner remote monitoring

Off by default. The pharmacy keeps working with no internet; the monitor just waits and retries.

Setup (once):
1. In your own Supabase project run `docs/supabase_owner_monitor.sql` (steps are at the top).
2. Copy `remote_monitor.example.json` to `remote_monitor.json` next to the program and fill in the project URL,
   the project's publishable (anon) key, and the DEVICE user's email and password. This file is ignored by git.
3. In the program: Settings > Remote monitoring > "show what will be sent" > "Enable". From then on it starts by itself every time.

What is sent (only rows created after you enable it, never old history):
- Summary level: time, user, role, action, source (desktop/mobile), branch name, shift number, entity and entity id (for example an invoice number); for system events: time, level, component, event, a short redacted message, app version.
- Full level adds details, before/after values and the redacted traceback. These can contain customer names and prices.
- Never sent: passwords, hashes, PINs, tokens, keys, the database file, the catalog key.
- A heartbeat every 5 minutes: app version, highest log id, log row count, unsent count. A drop in the id or count, or a gap in heartbeats, shows a restore, a reset or a PC that was off.
  The heartbeat is a hint, not proof. Someone with full control of the PC can stop the app or alter the local database, and the counters then look normal. It does not guarantee tamper detection or that every event arrived.

View: open `owner_monitor.html` (any browser, no server), enter the project URL, publishable key and the OWNER login.


## Consent, cursors and restores
- Consent (on/off), level and upload cursors are stored in a small file next to the database, `<database>.rmstate.json` (git-ignored, no secrets). Restoring an old database copy therefore does not turn monitoring off and does not rewind the cursors. If the file is lost, monitoring is off until enabled again.
- Each upload carries a `generation`. If the database has fewer log rows than already uploaded, or the row at the cursor no longer matches its fingerprint (ids reused after a restore), the app starts a new generation, moving forward only: events created after the last uploaded one are still sent, older restored history is not. A `generation_change` warning is written to the local system log and uploaded.
- Server rows are keyed by (device login, device id, generation, kind, source id), so retries never duplicate and reused ids in a new generation are not dropped.
- The owner id on each row is set by the server from the login (`auth.uid()`); a client cannot write rows as another account. The SQL was tested on a local Postgres with RLS (forged owner, anon, owner write, update, delete, oversized payload all rejected).


## Email reports (optional, can be used instead of Supabase)
- Add a `mail_report` block to `remote_monitor.json` (git-ignored): `host`, `port`, `mode` (`ssl` = implicit TLS, or `starttls`), `username`, `sender`, `to`. No password goes in this file. With only this block, nothing is ever sent to Supabase.
- Resend example (from its docs, not yet tested live): host `smtp.resend.com`, port 465 (ssl) or 587 (starttls), username `resend`, password = the API key. The sandbox sender `onboarding@resend.dev` can only send to the Resend account owner's own address.
- The key is entered in Settings > Remote monitoring > "مفتاح الإيميل" and stored encrypted with Windows DPAPI in `<database>.rmsecret` (git-ignored). Saving is refused on non-Windows. DPAPI has not been tested on a real Windows PC yet.
- One combined report every 6 hours, summary only (action, source, counts, system event names). No customer names, prices, before/after values or keys.
- Mail is sent only over verified TLS (certificate and host name checked), with no plaintext fallback. TLS protects the message in transit; it is not end-to-end encryption, so the provider and the mailbox can read it.
- Failures keep the cursors and retry later; they do not flood the log. Enable shows a preview with the destination first.
- HTTPS API mode (Resend): `"mail_report": {"mode": "api", "url": "https://api.resend.com/emails", "sender": "...", "to": "..."}`. The key goes in the same Settings box and is sent as a Bearer token over certificate-verified HTTPS; `http://` URLs are refused. Resend documents sending-only API keys for the API; it does not say whether such a key works over SMTP, so API mode is the safer choice. Tested only against a local fake HTTPS server, never against Resend.
