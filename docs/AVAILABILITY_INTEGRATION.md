# Availability integration: offline foundation and next contract

## Purpose and boundaries

Pharmacy-App remains the offline billing and batch-stock authority. The separate
Pharmacy-Medicine-Availability-Platform is a public finder: which pharmacy has a
medicine and which branch is nearest. This is not a database merger.

This PR is intentionally inert. `availability_bridge.py` is not called at startup,
has no HTTP client, saves no mappings, and sends nothing. It provides tested mapping
suggestions and a read-only inventory preview for a later opt-in connector. It
changes no existing tables, Supabase policies, catalog rows or selling prices.
Merging this PR does not enable publication. No production URL or credentials are
included. Do not put generated previews or real stock exports in Git.

## Product identity and privacy

- Use stable local product IDs scoped to an installation and pharmacy. Never use
  local integer IDs as global medicine IDs. The platform uses GUIDs.
- Match checksum-valid global **box** GTINs, with zero-padding equivalence. Local
  restricted-circulation barcodes are not global identifiers. Do not match by fuzzy
  product name. A candidate is always `needs_review`, even with one barcode hit.
- Review exact name, pack, strength and form before confirming a mapping. Pin the
  reviewed identity fingerprint. A later identity change pauses that row.
- Ambiguous/unmatched items go to review, not silent medicine creation. Existing
  platform Medicine requires generic name, active ingredient, form and strength;
  catalog gaps and cosmetics must not be filled with invented clinical metadata.
  Catalog import needs a separate reviewed path and source/license attribution.
- Publish only product identity, whole-pack sellable quantity, selling price and
  freshness. Never upload sales, customers, prescriptions, supplier costs, debts,
  staff details or local database files.

## Units, zero stock and expiry

Local `batches.qty_units` counts the smallest sale unit. `sell_price` is per box.
The platform's current inventory quantity has no unit field. Phase 1 uses full
sellable boxes/packs: floor(non-expired sellable units / units_per_box). Partial
packs do not become a whole available box. The UI must label the unit and price.
Use decimal EGP with two places; invalid/nonpositive prices are held.

Preview includes **zero** for verified mapped products that sold out or became
inactive. Omission is never interpreted as zero: previews are partial, so an
unmatched row cannot accidentally erase remote inventory. Deleted/unlinked rows
need explicit tombstones or a separate reviewed mapping-retirement protocol.
The existing POS accepts stock with unknown expiry as sellable; the preview follows
that same rule. Expired batches are excluded. No branch-wide snapshot may be
labelled complete while rows are held.

## Receiver contract to implement next (not an existing endpoint)

Add a dedicated authenticated `POST /api/v1/integration/inventory-snapshots`,
separate from the disabled management/reservation features. Dedicated connector
credentials must be bound server-side to a single pharmacy, branch and installation;
never trust pharmacy IDs supplied by the client alone. Do not reuse the anonymous
Supabase key or expose a platform admin token in the public website.

Envelope: schemaVersion, installationId, branchId, snapshotId, monotonic sequence,
observedAtUtc, mode='partial', items, explicit tombstones. Each item: externalProductId,
medicineId, identityFingerprint, availableQuantity, price (decimal string),
currency='EGP', saleUnit='box', unitsPerPack. Receiver must validate active verified
mapping, pack identity and branch ownership before accepting an item.

- Save snapshot ID/sequence and inventory updates atomically. Same ID and payload
  retries return the saved receipt without applying twice. Same ID with different
  payload is a conflict. Reject out-of-order sequence numbers. Return per-row
  accepted/held outcomes and a durable receipt; never claim unaccepted rows synced.
- Preserve source observation time as well as server receive time. A delayed queue
  must not refresh old inventory into apparently fresh availability. Reject future
  observations outside a small explicit clock-skew allowance.
- No delta arithmetic for POS sync: repeated deltas after network failures would
  double-deduct stock. Current management quantity PATCH is not this protocol.
- Persist local pending snapshots/receipts in a separate connector queue, not in
  business transactions. Reconcile on launch, reconnect and periodically. Trigger
  reconciliation after completed sale, purchase, return, adjustment, product price
  or activation change; failed internet must never block billing. Expiry crossing
  midnight also needs reconciliation even with no sales.
- The platform currently has mapping/sync-log domain types and `UpdateFromSync`,
  but no end-to-end sync service/controller. Its branch inventory and public finder
  already have branch address, phone, coordinates and distance search.
- Keep online reservations off. With no local reservation acknowledgement protocol,
  cloud holds can disagree with the offline till. Enabling them needs a later design.
- Public availability must visibly show last observation and suppress unreliable
  stale offers rather than treating old positive stock as live. Reconnect needs a
  fresh local read, not just replay of an old queued payload.

## Nearest pharmacy setup and acceptance

No new GPS schema is needed in the platform. Before real activation, the operator
must confirm the branch identity, exact map pin/address, contact details and opening
hours. Do not substitute a developer's home/network location. Ordinary visitors
can consent to browser location or choose an area manually. Deployment/HTTPS,
platform branch activation and connector credentials are separate opt-in setup.

Next PRs: receiver/auth/idempotency and unit-labelled public responses first; then
opt-in desktop queue/settings and mapping review. Use synthetic fixtures in tests.
Required integration tests: retry/reorder, branch isolation, no internet at sale,
zero stock, expiry rollover, split packs, changed mapping, missing clinical fields,
inactive products, price units, stale offers and no private-data payload fields.

Baseline reviewed: Pharmacy-App e1504cc and availability platform 864cefd. No
production deployment, real stock transmission, policy change or reservation
activation is part of this foundation.
