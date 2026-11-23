"""Offline-only availability bridge primitives. No HTTP, hooks or background jobs.

Candidate matches always require review. Preview output must not be uploaded until
an authenticated, retry-safe receiver and explicit branch activation exist.
"""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

from database import units_per_box


def canonical_gtin(value):
    """Accept plain checked GTINs only, never guess digits out of arbitrary text."""
    value = str(value or "").strip()
    if not re.fullmatch(r"[0-9]{8}|[0-9]{12,14}", value):
        return None
    total = sum(int(c) * (3 if i % 2 == 0 else 1)
                for i, c in enumerate(reversed(value[:-1])))
    if (total + int(value[-1])) % 10:
        return None
    padded = value.zfill(14)
    # Restricted-circulation EANs can be pharmacy-local, not global identities.
    if padded[0] == "0" and 20 <= int(padded[1:3]) <= 29:
        return None
    if set(value) == {"0"}:
        return None
    return padded


def _box_codes(db, drug_id):
    return sorted({c for row in db.conn.execute(
        "SELECT barcode FROM barcodes WHERE drug_id=? AND pack_level='box'",
        (drug_id,)) if (c := canonical_gtin(row[0]))})


def identity_fingerprint(drug, codes):
    fields = {k: drug.get(k) for k in (
        "id", "trade_en", "strength", "form", "strips_per_box", "tablets_per_strip")}
    fields["box_gtins"] = sorted(codes)
    raw = json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def mapping_candidates(db, medicines):
    """Suggest by global box GTIN. No name-only matches or silent approval.

    medicines is an already-fetched platform catalog list, using camelCase DTO
    fields. This function neither fetches it nor creates missing medicines.
    """
    index = {}
    for medicine in medicines:
        mid = str(UUID(str(medicine["id"])))
        if not medicine.get("isActive", True):
            continue
        for entry in medicine.get("barcodes", []):
            code = canonical_gtin(entry.get("barcode"))
            if code:
                index.setdefault(code, set()).add(mid)
    result = []
    for row in db.conn.execute("SELECT * FROM drugs ORDER BY id"):
        drug = dict(row)
        codes = _box_codes(db, drug["id"])
        matches = sorted(set().union(*(index.get(c, set()) for c in codes)))
        result.append({
            "externalProductId": str(drug["id"]), "name": drug["trade_en"],
            "strength": drug["strength"], "dosageForm": drug["form"],
            "boxGtins": codes, "candidateMedicineIds": matches,
            "status": "needs_review" if len(matches) == 1 else
                      "ambiguous" if matches else "unmatched",
            "identityFingerprint": identity_fingerprint(drug, codes),
        })
    return result


def inventory_preview(db, bindings):
    """Build a read-only, whole-pack, partial snapshot from reviewed bindings.

    Each binding needs externalProductId, medicineId, status='verified', and the
    reviewed identityFingerprint. Unmatched products are never invented. Missing
    rows/mapping changes are reported as holds, not implicit remote deletions.
    Zero quantities ARE included for mapped products to clear sold-out stock.
    """
    items, held = [], []
    seen_local, seen_remote = set(), set()
    # A stable SQLite read transaction prevents stock/catalog tearing mid-preview.
    # Do not commit or roll back a caller's active business transaction.
    if db.conn.in_transaction:
        raise ValueError("Preview requires an idle database connection")
    db.conn.execute("BEGIN")
    try:
        for binding in bindings:
            local = str(binding.get("externalProductId", ""))
            try:
                mid = str(UUID(str(binding.get("medicineId", ""))))
                if local in seen_local or mid in seen_remote:
                    raise ValueError("duplicate product or medicine binding")
                seen_local.add(local)
                seen_remote.add(mid)
                if binding.get("status") != "verified":
                    raise ValueError("mapping not verified")
                row = db.conn.execute("SELECT * FROM drugs WHERE id=?", (local,)).fetchone()
                if row is None:
                    raise ValueError("local product missing")
                drug = dict(row)
                codes = _box_codes(db, drug["id"])
                if not codes or identity_fingerprint(drug, codes) != binding.get("identityFingerprint"):
                    raise ValueError("product identity changed or no global box GTIN")
                price = Decimal(str(drug["sell_price"]))
                if not price.is_finite() or price <= 0 or price != price.quantize(Decimal("0.01")):
                    raise ValueError("invalid positive two-decimal sale price")
                units = db.sellable_stock(drug["id"]) if drug["active"] else 0
                items.append({"externalProductId": local, "medicineId": mid,
                              "availableQuantity": max(0, units) // units_per_box(drug),
                              "price": format(price, ".2f"), "currency": "EGP",
                              "saleUnit": "box", "unitsPerPack": units_per_box(drug),
                              "identityFingerprint": binding["identityFingerprint"]})
            except (ValueError, TypeError, InvalidOperation) as exc:
                held.append({"externalProductId": local, "reason": str(exc)})
        # A duplicate target invalidates the entire preview: never publish one side.
        if any(h["reason"] == "duplicate product or medicine binding" for h in held):
            items = []
        return {"schemaVersion": 1, "mode": "partial", "items": items,
                "held": held, "networkEnabled": False}
    finally:
        db.conn.rollback()
