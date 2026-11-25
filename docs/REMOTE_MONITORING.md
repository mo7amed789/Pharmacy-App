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

View: open `owner_monitor.html` (any browser, no server), enter the project URL, publishable key and the OWNER login.
