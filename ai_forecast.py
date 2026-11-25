# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise v2 — AI / smart forecasting (LOCAL, OFFLINE, stdlib only).
No API key, no internet, no new packages: sqlite3, math, statistics,
datetime, collections only.

Idea in one line:
  barcode -> drug -> price is a lookup (v1). Forecasting is the same
  idea one step further: past sales -> daily rate -> future demand.

How it works (honest, no magic):
  * Weighted moving average: recent days count more than old days.
  * Trend: last 14 days vs the 14 days before them (rising / falling).
  * Weekly seasonality: only when >= 28 days of history exist — e.g.
    Friday/Saturday sell more in Egypt — weekday averages vs overall.
  * Confidence 0-100: from how many days we actually observed and how
    stable sales are (low variance = high confidence). With little or
    no history the forecast says so clearly instead of pretending.
  * Reorder point = daily rate * (lead time + safety days).
  * Expiry loss = for each batch, how many units will NOT sell before
    its expiry date at the forecast daily rate, valued at sell price.

All functions are pure / read-only except simulate_sales() and the
optional forecast_cache helpers, which are for TEST databases only
(simulate_sales) or a cache table (database.py).
"""
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

# Defaults a pharmacist can reason about — shown in the UI, not hidden.
DEFAULT_HORIZON_DAYS = 30
DEFAULT_LEAD_TIME_DAYS = 3    # supplier usually delivers in ~3 days
DEFAULT_SAFETY_DAYS = 2       # extra buffer so the shelf never empties
MIN_TREND_NONZERO_DAYS = 7    # fewer observations cannot support a trend claim


def _coerce_units(value):
    """Return a safe non-negative integer for an external sales value."""
    try:
        number = float(value or 0)
        if not math.isfinite(number):
            return 0
        return max(0, int(number))
    except (TypeError, ValueError, OverflowError):
        return 0


def _parse_date(value):
    """Accept 'YYYY-MM-DD' or an ISO datetime string, return a date or None."""
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def _to_series(daily_sales):
    """Normalise input to a sorted list of (date, units).
    Accepts a dict {date-str: units} or a list of (date, units) tuples."""
    items = []
    if isinstance(daily_sales, dict):
        for k, v in daily_sales.items():
            d = _parse_date(k)
            if d is not None:
                items.append((d, _coerce_units(v)))
    else:
        for item in daily_sales or []:
            d = _parse_date(item[0])
            if d is not None:
                items.append((d, _coerce_units(item[1])))
    items.sort(key=lambda x: x[0])
    return items


def get_daily_sales(db, drug_id, days=90):
    """Units sold per day for one drug over the last `days` days.

    Reads completed sales only (sale_items JOIN sales, status='completed').
    Returns a dict {ISO date: units} with EVERY day in the window present
    (missing days = 0 sold — that matters: a zero day is real data, not
    a missing record). Returns {} only if the drug id is invalid.
    """
    try:
        drug_id = int(drug_id)
    except Exception:
        return {}
    end = date.today()
    start = end - timedelta(days=days - 1)
    result = {}
    d = start
    while d <= end:
        result[d.isoformat()] = 0
        d += timedelta(days=1)
    try:
        rows = db.conn.execute(
            """SELECT s.date AS day, COALESCE(SUM(si.qty_units), 0) AS units
            FROM sale_items si JOIN sales s ON s.id = si.sale_id
            WHERE si.drug_id = ? AND s.status = 'completed'
            AND s.date >= ? AND s.date <= ?
            GROUP BY s.date""",
            (drug_id, start.isoformat(), end.isoformat())).fetchall()
    except Exception:
        return result
    for row in rows:
        day = _parse_date(row["day"])
        if day is not None and day.isoformat() in result:
            result[day.isoformat()] = int(row["units"] or 0)
    return result


def get_sales_summary(db, drug_id, days=30):
    """Small helper for the UI: total units + total revenue in a window."""
    end = date.today()
    start = end - timedelta(days=days - 1)
    try:
        row = db.conn.execute(
            """SELECT COALESCE(SUM(si.qty_units), 0) AS units,
            COALESCE(SUM(si.line_total), 0) AS revenue
            FROM sale_items si JOIN sales s ON s.id = si.sale_id
            WHERE si.drug_id = ? AND s.status = 'completed'
            AND s.date >= ? AND s.date <= ?""",
            (drug_id, start.isoformat(), end.isoformat())).fetchone()
        return {"units": int(row["units"] or 0), "revenue": round(float(row["revenue"] or 0), 2)}
    except Exception:
        return {"units": 0, "revenue": 0.0}


def forecast_demand(daily_sales, horizon_days=30):
    """Forecast future demand from a daily sales series.

    Returns a dict:
      daily_rate, horizon_total, confidence (0-100),
      trend ('صاعد'/'هابط'/'مستقر'), trend_pct,
      method (Arabic label), days_observed, nonzero_days
    """
    series = _to_series(daily_sales)
    horizon_days = max(1, int(horizon_days or DEFAULT_HORIZON_DAYS))
    if not series:
        return {"daily_rate": 0.0, "horizon_total": 0.0, "confidence": 0,
                "trend": "لا توجد بيانات", "trend_pct": 0.0,
                "method": "لا توجد مبيعات مسجلة", "days_observed": 0,
                "nonzero_days": 0}
    values = [units for _, units in series]
    days_observed = len(values)
    nonzero_days = sum(1 for v in values if v > 0)
    total = sum(values)

    if total <= 0:
        return {"daily_rate": 0.0, "horizon_total": 0.0, "confidence": 0,
                "trend": "لا توجد بيانات", "trend_pct": 0.0,
                "method": "لا توجد مبيعات مسجلة — التنبؤ غير ممكن",
                "days_observed": days_observed, "nonzero_days": 0}

    # --- weighted moving average over the last 28 days (recent = heavier) ---
    window = values[-28:]
    weights = [i + 1 for i in range(len(window))]  # 1..28, newest heaviest
    wma = sum(v * w for v, w in zip(window, weights)) / sum(weights)
    simple_mean = total / days_observed

    # --- trend: last 14 days vs previous 14 days ---
    # A single sale in a long zero-filled window is not evidence of a trend.
    # Keep the rate useful, but explicitly refuse to manufacture direction.
    sparse_sales = nonzero_days < MIN_TREND_NONZERO_DAYS
    if sparse_sales:
        trend_pct = 0.0
        trend = "بيانات غير كافية للاتجاه"
    else:
        recent = values[-14:]
        previous = values[-28:-14] if len(values) >= 28 else values[:-14]
        recent_mean = sum(recent) / len(recent) if recent else 0.0
        prev_mean = sum(previous) / len(previous) if previous else 0.0
        if prev_mean > 0:
            trend_pct = (recent_mean - prev_mean) / prev_mean * 100.0
        elif recent_mean > 0:
            trend_pct = 100.0
        else:
            trend_pct = 0.0
        trend_pct = max(-80.0, min(120.0, trend_pct))
        if trend_pct > 10:
            trend = "صاعد"
        elif trend_pct < -10:
            trend = "هابط"
        else:
            trend = "مستقر"
    # Apply only half the trend — a 2-week swing should nudge, not explode,
    # the forecast.
    adjusted = wma * (1.0 + (trend_pct / 100.0) * 0.5)

    # --- weekly seasonality, only with >= 28 days of history ---
    method = "متوسط مرجح (آخر 28 يوم) + اتجاه"
    if days_observed >= 28 and simple_mean > 0 and not sparse_sales:
        weekday_sums = defaultdict(float)
        weekday_counts = defaultdict(int)
        for d, v in series:
            weekday_sums[d.weekday()] += v
            weekday_counts[d.weekday()] += 1
        factors = []
        for wd in range(7):
            if weekday_counts[wd]:
                factors.append((weekday_sums[wd] / weekday_counts[wd]) / simple_mean)
        if factors:
            # Average factor over the next 7 days (a full week) — neutral
            # when sales are flat across weekdays, >1 when weekends spike.
            season_factor = sum(factors) / len(factors)
            season_factor = max(0.7, min(1.3, season_factor))
            adjusted = adjusted * season_factor
            method = "متوسط مرجح + اتجاه + موسمية أسبوعية"
    elif sparse_sales or days_observed < 14:
        method = "متوسط بسيط — بيانات قليلة (مبيعات فعلية أقل من %d أيام)" % MIN_TREND_NONZERO_DAYS

    daily_rate = max(0.0, round(float(adjusted), 2))

    # --- confidence 0-100: coverage + stability ---
    # Coverage: 30 selling days is a solid sample; fewer days = less sure.
    coverage = min(1.0, nonzero_days / 30.0)
    # Stability: coefficient of variation of the last 28 days.
    if len(window) >= 7 and statistics.mean(window) > 0:
        cv = statistics.pstdev(window) / statistics.mean(window)
        stability = max(0.0, 1.0 - min(1.0, cv / 1.5))
    else:
        stability = 0.3
    confidence = int(round((coverage * 0.6 + stability * 0.4) * 100))
    if nonzero_days == 0:
        confidence = 0
    confidence = max(0, min(100, confidence))

    return {"daily_rate": daily_rate,
            "horizon_total": round(daily_rate * horizon_days, 1),
            "confidence": confidence, "trend": trend,
            "trend_pct": round(trend_pct, 1), "method": method,
            "days_observed": days_observed, "nonzero_days": nonzero_days}


def reorder_point(daily_rate, lead_time_days=3, safety_days=2):
    """Stock level (in smallest units) at which you must order now."""
    return max(0.0, round(float(daily_rate or 0) * (lead_time_days + safety_days), 1))


def suggested_order_qty(stock_units, forecast_total, daily_rate,
                        lead_time_days=3, safety_days=2):
    """Units to order so stock covers the horizon + safety buffer.

    Never negative, rounded UP to whole units (you cannot order 0.4 box).
    """
    safety = float(daily_rate or 0) * safety_days
    need = float(forecast_total or 0) - float(stock_units or 0) + safety
    return int(math.ceil(need)) if need > 0 else 0


def _unit_sell_price(batch):
    """Sell price of ONE smallest unit for a batch dict."""
    if batch.get("unit_sell_price"):
        return float(batch["unit_sell_price"])
    if batch.get("sell_price"):
        upb = 1
        try:
            upb = max(1, int(batch.get("strips_per_box") or 1) * int(batch.get("tablets_per_strip") or 1))
        except Exception:
            upb = 1
        return float(batch["sell_price"]) / upb
    return 0.0


def expiry_loss_prediction(batches, forecast_daily):
    """For each batch expiring in the next 90 days, estimate what will
    NOT sell before expiry at the forecast daily rate.

    batches: list of dicts with qty_units, expiry (YYYY-MM-DD), trade_en,
      batch_no, and sell_price or unit_sell_price.
    Returns (rows, total_loss_egp). Each row: drug, batch_no, expiry,
      days_left, qty_units, expected_sell, unsold_units, loss_egp,
      risk ('عالية'/'متوسطة'/'منخفضة'), suggestion (Arabic).
    """
    today = date.today()
    rows = []
    total_loss = 0.0
    daily = max(0.0, float(forecast_daily or 0))
    for b in batches or []:
        expiry = _parse_date(b.get("expiry"))
        qty = int(b.get("qty_units") or 0)
        if expiry is None or qty <= 0:
            continue
        days_left = (expiry - today).days
        if days_left > 90:
            continue
        if days_left < 0:
            # Already expired: everything unsold is a loss.
            unsold = qty
            expected_sell = 0
        else:
            expected_sell = int(min(qty, math.floor(daily * days_left))) if daily > 0 else 0
            unsold = max(0, qty - expected_sell)
        unit_price = _unit_sell_price(b)
        loss = round(unsold * unit_price, 2)
        total_loss += loss
        if unsold <= 0:
            risk = "منخفضة"
            suggestion = "سيُباع قبل الانتهاء — لا إجراء"
        else:
            ratio = unsold / qty if qty else 0
            if days_left < 0 or ratio >= 0.5 or days_left <= 14:
                risk = "عالية"
            elif ratio >= 0.2:
                risk = "متوسطة"
            else:
                risk = "منخفضة"
            if days_left < 0:
                suggestion = "منتهي — اعزله ولا تبعه، وراجعه مع المورد"
            elif days_left <= 14:
                suggestion = "خصم سريع أو إرجاع للمورد فوراً"
            elif ratio >= 0.5:
                suggestion = "خصم / عرض، أو تحويل لفرع يبيع أكثر"
            else:
                suggestion = "تابع بيعه أولاً (FEFO) وقلل الطلب الجديد"
        rows.append({
            "drug": b.get("trade_en") or b.get("trade_ar") or b.get("drug_name") or "",
            "drug_id": b.get("drug_id"),
            "batch_no": b.get("batch_no", ""),
            "expiry": expiry.isoformat(),
            "days_left": days_left,
            "qty_units": qty,
            "expected_sell": expected_sell,
            "unsold_units": unsold,
            "loss_egp": loss,
            "risk": risk,
            "suggestion": suggestion,
        })
    rows.sort(key=lambda r: r["loss_egp"], reverse=True)
    return rows, round(total_loss, 2)


def supplier_best_price(db, drug_id):
    """Cheapest supplier for one drug, from real purchase history.

    Compares each supplier's LOWEST buy price per box for this drug.
    Returns None if the drug was never purchased, else:
      {supplier_id, supplier_name, buy_price, saving_vs_current, current_buy_price}
    saving = current drug buy_price - cheapest price (per box, EGP).
    """
    try:
        drug = db.get_drug(int(drug_id))
    except Exception:
        return None
    if not drug:
        return None
    try:
        rows = db.conn.execute(
            """SELECT s.id AS supplier_id, s.name AS supplier_name,
            MIN(pi.buy_price) AS best_price, MAX(p.date) AS last_date
            FROM purchase_items pi
            JOIN purchases p ON p.id = pi.purchase_id
            JOIN suppliers s ON s.id = p.supplier_id
            WHERE pi.drug_id = ? GROUP BY s.id, s.name
            ORDER BY best_price ASC""", (int(drug_id),)).fetchall()
    except Exception:
        return None
    if not rows:
        return None
    best = rows[0]
    current = float(drug.get("buy_price") or 0)
    return {"supplier_id": best["supplier_id"],
            "supplier_name": best["supplier_name"],
            "buy_price": round(float(best["best_price"] or 0), 2),
            "last_date": best["last_date"],
            "current_buy_price": round(current, 2),
            "saving_vs_current": round(current - float(best["best_price"] or 0), 2)}


def _full_window(by_day, days=90):
    """Same shape get_daily_sales returns: every day present, missing = 0."""
    end = date.today()
    d = end - timedelta(days=days - 1)
    result = {}
    while d <= end:
        result[d.isoformat()] = 0
        d += timedelta(days=1)
    for k, v in by_day.items():
        if k in result:
            result[k] = v
    return result


def _bulk_sales_and_purchases(db, days=90):
    """({drug_id: {ISO day: units}} for completed sales in the window,
    set of drug ids that have purchase history or None if it cannot be read)."""
    end = date.today()
    start = end - timedelta(days=days - 1)
    sales = {}
    try:
        rows = db.conn.execute(
            """SELECT si.drug_id AS drug_id, s.date AS day,
            COALESCE(SUM(si.qty_units), 0) AS units
            FROM sale_items si JOIN sales s ON s.id = si.sale_id
            WHERE s.status = 'completed' AND s.date >= ? AND s.date <= ?
            GROUP BY si.drug_id, s.date""",
            (start.isoformat(), end.isoformat())).fetchall()
        for row in rows:
            day = _parse_date(row["day"])
            if day is None:
                continue
            m = sales.setdefault(row["drug_id"], {})
            m[day.isoformat()] = m.get(day.isoformat(), 0) + int(row["units"] or 0)
    except Exception:
        sales = {}
    try:
        purchased = {r[0] for r in db.conn.execute(
            "SELECT DISTINCT drug_id FROM purchase_items").fetchall()}
    except Exception:
        purchased = None
    return sales, purchased


def generate_reorder_list(db, horizon_days=30, lead_time_days=3, safety_days=2):
    """One row per drug, sorted by urgency (critical first).

    Row: drug_id, drug_name, scientific, stock_units, stock_boxes,
      daily_rate, forecast_total, reorder_point, suggested_units,
      suggested_boxes, urgency ('حرجة'/'عالية'/'عادية'/'مستقرة'),
      days_of_stock, confidence, supplier_name, supplier_price, method, trend
    Urgency is driven by days of stock left, not by gut feeling.
    """
    horizon_days = max(1, int(horizon_days or DEFAULT_HORIZON_DAYS))
    rows = []
    try:
        drugs = db.search_drugs("", limit=10000)
    except Exception:
        return []
    # v6.31: two bulk queries instead of two per drug. Drugs with no sales in the
    # window share one precomputed "no sales" forecast; drugs never purchased skip
    # the supplier lookup. Results are identical to the per-drug path.
    sales_by_drug, purchased = _bulk_sales_and_purchases(db, days=90)
    zero_fc = None
    for drug in drugs:
        sold = sales_by_drug.get(drug["id"])
        if sold is None:
            if zero_fc is None:
                zero_fc = forecast_demand(get_daily_sales(db, 0, days=90), horizon_days=horizon_days)
            fc = dict(zero_fc)
        else:
            fc = forecast_demand(_full_window(sold, days=90), horizon_days=horizon_days)
        rate = fc["daily_rate"]
        stock = int(drug.get("stock_units") or 0)
        rop = reorder_point(rate, lead_time_days, safety_days)
        suggested = suggested_order_qty(stock, fc["horizon_total"], rate,
                                        lead_time_days, safety_days)
        if rate > 0:
            days_left = stock / rate
        else:
            days_left = 999.0
        if rate > 0 and days_left <= 3:
            urgency = "حرجة"
        elif rate > 0 and days_left <= 7:
            urgency = "عالية"
        elif suggested > 0 or stock <= rop:
            urgency = "عادية"
        else:
            urgency = "مستقرة"
        best = supplier_best_price(db, drug["id"]) if (purchased is None or drug["id"] in purchased) else None
        try:
            from database import units_per_box
            upb = units_per_box(drug)
        except Exception:
            upb = 1
        rows.append({
            "drug_id": drug["id"],
            "drug_name": "%s %s" % (drug.get("trade_en", ""), drug.get("strength", "")),
            "scientific": drug.get("scientific", ""),
            "stock_units": stock,
            "stock_boxes": round(stock / upb, 1) if upb else 0,
            "daily_rate": rate,
            "forecast_total": fc["horizon_total"],
            "reorder_point": rop,
            "suggested_units": suggested,
            "suggested_boxes": math.ceil(suggested / upb) if suggested > 0 and upb else 0,
            "urgency": urgency,
            "days_of_stock": round(days_left, 1) if days_left < 900 else 999,
            "confidence": fc["confidence"],
            "supplier_name": best["supplier_name"] if best else "—",
            "supplier_price": best["buy_price"] if best else None,
            "method": fc["method"],
            "trend": fc["trend"],
            "trend_pct": fc["trend_pct"],
        })
    order = {"حرجة": 0, "عالية": 1, "عادية": 2, "مستقرة": 3}
    rows.sort(key=lambda r: (order.get(r["urgency"], 9), -r["daily_rate"]))
    return rows


def get_movers(db, days=30, limit=5):
    """Top fastest-moving and slowest-moving drugs in the last `days` days.

    Returns (fastest, slowest): each a list of dicts
    {drug_id, drug_name, units, revenue}. Slow = drugs with stock but
    zero sales in the window (dead stock candidates), then lowest sellers.
    """
    end = date.today()
    start = end - timedelta(days=days - 1)
    try:
        rows = db.conn.execute(
            """SELECT d.id AS drug_id, d.trade_en AS drug_name,
            COALESCE(SUM(si.qty_units), 0) AS units,
            COALESCE(SUM(si.line_total), 0) AS revenue
            FROM drugs d LEFT JOIN sale_items si ON si.drug_id = d.id
            LEFT JOIN sales s ON s.id = si.sale_id AND s.status = 'completed'
                AND s.date >= ? AND s.date <= ?
            WHERE d.active = 1 GROUP BY d.id""",
            (start.isoformat(), end.isoformat())).fetchall()
    except Exception:
        return [], []
    all_rows = [{"drug_id": r["drug_id"], "drug_name": r["drug_name"],
                 "units": int(r["units"] or 0),
                 "revenue": round(float(r["revenue"] or 0), 2)} for r in rows]
    fastest = sorted(all_rows, key=lambda r: -r["units"])[:limit]
    # Slowest: zero sellers first (only if they actually have stock —
    # a drug with no stock cannot sell, that is a shortage, not dead stock).
    try:
        stocked = {d["id"] for d in db.search_drugs("", limit=10000)
                   if int(d.get("stock_units") or 0) > 0}
    except Exception:
        stocked = set()
    slowest = [r for r in sorted(all_rows, key=lambda r: r["units"])
               if r["drug_id"] in stocked][:limit]
    return fastest, slowest


def expiry_risk_for_all(db, horizon_days=30):
    """Expiry loss for every batch expiring in the next 90 days.

    Uses each drug's own forecast rate (not one global rate).
    Returns (rows, total_loss_egp).
    """
    try:
        batches = db.near_expiry(90)
    except Exception:
        return [], 0.0
    # Group batches by drug so each drug's forecast is computed once.
    by_drug = defaultdict(list)
    for b in batches:
        by_drug[b["drug_id"]].append(b)
    all_rows = []
    total = 0.0
    for drug_id, blist in by_drug.items():
        drug = db.get_drug(drug_id)
        if not drug:
            continue
        fc = forecast_demand(get_daily_sales(db, drug_id, days=90),
                             horizon_days=horizon_days)
        enriched = []
        for b in blist:
            nb = dict(b)
            nb["sell_price"] = drug.get("sell_price")
            nb["strips_per_box"] = drug.get("strips_per_box")
            nb["tablets_per_strip"] = drug.get("tablets_per_strip")
            enriched.append(nb)
        rows, loss = expiry_loss_prediction(enriched, fc["daily_rate"])
        all_rows.extend(rows)
        total += loss
    all_rows.sort(key=lambda r: r["loss_egp"], reverse=True)
    return all_rows, round(total, 2)


def text_chart(daily_sales, days=14, width=20):
    """Simple text bar chart of the last `days` days, for the detail pane.
    One line per day: 'MM-DD | █████ 12'. No plotting library needed."""
    series = _to_series(daily_sales)[-days:]
    if not series:
        return "لا توجد بيانات مبيعات."
    peak = max((v for _, v in series), default=0)
    lines = []
    for d, v in series:
        bar_len = int(round(v / peak * width)) if peak > 0 else 0
        lines.append("%s | %s %d" % (d.strftime("%m-%d"), "█" * bar_len, v))
    return "\n".join(lines)


def simulate_sales(db, drug_id, daily_rate, days=60, start_days_ago=60):
    """TEST ONLY: insert synthetic past sales into a TEST database.

    Never call this on the real pharmacy.db — it invents sales history.
    Deterministic pattern (no randomness): weekend days (Fri/Sat in
    Egypt) sell ~30% more, weekdays ~10% less, every 3rd day +1 unit,
    so the average stays close to `daily_rate` and a forecast can be
    checked against it. Uses direct inserts (no stock deduction) so a
    test DB does not need stock for the drug.
    Returns the number of sale rows inserted.
    """
    from database import _round as _r  # reuse the app's rounding
    drug = db.get_drug(int(drug_id))
    if not drug:
        raise ValueError("drug not found: %s" % drug_id)
    today = date.today()
    inserted = 0
    c = db.conn.cursor()
    for i in range(int(days)):
        day = today - timedelta(days=int(start_days_ago) - i)
        # weekday(): Mon=0 .. Sun=6; Fri=4, Sat=5 are the Egyptian weekend.
        factor = 1.3 if day.weekday() in (4, 5) else 0.9
        if i % 3 == 0:
            factor += 0.15
        qty_units = max(0, int(round(float(daily_rate) * factor)))
        if qty_units <= 0:
            continue
        unit_sell = float(drug["sell_price"]) / max(1, int(drug.get("strips_per_box") or 1) * int(drug.get("tablets_per_strip") or 1))
        line_total = _r(unit_sell * qty_units)
        inv = "SIM-%s-%03d" % (day.isoformat(), int(drug_id))
        # The deterministic invoice number makes this helper safely
        # re-runnable: an interrupted or repeated test must not duplicate
        # synthetic revenue or hit the sales.invoice_no UNIQUE constraint.
        if c.execute("SELECT 1 FROM sales WHERE invoice_no=?", (inv,)).fetchone():
            continue
        c.execute(
            """INSERT INTO sales (invoice_no, date, cashier, customer_id,
            subtotal, discount, total, paid, change_amount, payment_method,
            status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (inv, day.isoformat(), "test", None, line_total, 0, line_total,
             line_total, 0, "cash", "completed", day.isoformat() + "T12:00:00"))
        sale_id = c.lastrowid
        c.execute(
            """INSERT INTO sale_items (sale_id, drug_id, pack_level,
            qty_display, qty_units, unit_price, buy_price_unit, line_total)
            VALUES (?,?,?,?,?,?,?,?)""",
            (sale_id, int(drug_id), "pill", qty_units, qty_units,
             _r(unit_sell), 0, line_total))
        inserted += 1
    db.conn.commit()
    return inserted


if __name__ == "__main__":
    # Quick self-check without a database: pure functions only.
    series = { (date.today() - timedelta(days=i)).isoformat(): 10 for i in range(60) }
    print(forecast_demand(series, 30))
    print("reorder_point(10/day):", reorder_point(10))
    print("suggested (stock 50, forecast 300):", suggested_order_qty(50, 300, 10))
    batches = [{"trade_en": "Panadol", "batch_no": "B1", "expiry": (date.today() + timedelta(days=10)).isoformat(),
                "qty_units": 100, "sell_price": 25.0, "strips_per_box": 2, "tablets_per_strip": 12}]
    print(expiry_loss_prediction(batches, 2.0))
