# Optional public-availability publisher

This is separate from Supabase catalog sync and from invoices. It starts disabled.
Merging code does not deploy the public platform or send stock. The sales database
is read through its own connection; a separate `.availability.sqlite3` sidecar holds
reviewed bindings, configuration, monotonic sequence, one durable pending snapshot
and status. Include that sidecar in a coordinated backup/restore plan. Do not clone
an installation across branches. A stale/restored sequence fails closed and needs
operator review, never automatic resets or guessed branch changes.

Admin Settings opens the availability setup/review window. Use a trusted exported
array of platform medicine DTOs (id, brandName, strength, dosageForm, barcodes,
isActive). Load it, inspect exact local/platform product, strength, dosage form,
box GTIN and pack size, then review each unique candidate explicitly. There are
no fuzzy approvals. Review disables publishing and clears the pending snapshot.
Exported manifest contains only the installation/branch and reviewed product
bindings; it never includes a credential. The platform operator must provision
those bindings independently before activation. No public binding-write API.
Changed identity/price and held mappings stop publishing rather than silently
omitting products. Old offers eventually become unknown, not zero. Explicit
retirement and more-than-500-binding chunking are not implemented: keep disabled
for those cases. Do not treat this limit as a full pharmacy rollout.

Before any future activation: deploy and validate the disabled receiver, repair
known dependency security warnings, back up and review migrations, confirm branch
address/map pin, operator review of both-side identities/packs, and a synthetic
end-to-end acceptance run. Reservations and manual stock writes must be disabled
for connector-owned branches. This repository contains no live endpoint/grants.
The separate `PHARMACY_AVAILABILITY_PUBLISHER_KEY` process environment variable
must be provisioned securely by the operator with a high-entropy branch key. Never
put a real key in a repository, SQLite, JSON export, screenshot, command history,
public browser code or support logs. This UI does not collect or display secrets.

Only after all gates and a separate owner activation decision, enter the exact
HTTPS `/api/v1/integration/inventory-snapshots` endpoint and Branch UUID. Review the
manifest and provision server bindings for its Installation UUID. Explicit enable
requires the credential and confirmation. Disable stops new publishing. A request
already in flight can still complete; allow its 10-second timeout, then remove the
server grant for definitive revocation. Redirects never forward the credential.
TLS verification remains on and resolved private/loopback addresses are rejected.

A single-worker OS lock prevents two local processes from publishing this sidecar.
The worker checks every minute off the UI thread. No invoice hooks. Whole boxes,
nonexpired stock, explicit zero and positive two-decimal EGP prices only. One pending
snapshot keeps its ID, sequence, payload and observation time across retries/restarts.
A lost acknowledgement is safe to replay; a wrong acknowledgement never clears it.
After 14 minutes an old pending observation is replaced with a newly observed
higher-sequence snapshot. No timestamp refresh on old stock. HTTP rejection stops
for review; network/temporary failures back off up to 5 minutes. Public stock older
than 15 minutes is unknown. No customers, sales, staff, credentials or purchase
costs are sent. No automatic catalog downloads, product creation or deployment.

Tests: `python -m unittest discover -s tests -p 'test_availability*.py'`.
Native Windows billing and end-to-end live activation remain separate acceptance
checks; local synthetic tests and a Linux Tk render do not prove those.
