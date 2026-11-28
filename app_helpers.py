# -*- coding: utf-8 -*-
"""Shared pure-Python formatting, validation, path, and URL helpers."""
from datetime import date, datetime
import os
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BASE = (
    os.path.dirname(os.path.abspath(sys.executable))
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)
EGP = "ج.م"


def ar_date(value):
    """User-facing date as يوم/شهر/سنة (dd/mm/yyyy).

    Data storage, CSV exports and IDs keep ISO (YYYY-MM-DD); only what a human
    reads on screen or paper is localized.
    """
    try:
        if isinstance(value, datetime):
            d = value.date()
        elif isinstance(value, date):
            d = value
        else:
            s = str(value or "").strip()
            if not s:
                return ""
            d = datetime.strptime(s[:10], "%Y-%m-%d").date()
        return "%02d/%02d/%04d" % (d.day, d.month, d.year)
    except Exception:
        return str(value or "")


def _startup_log(msg):
    """Append one timestamped line to startup.log (never passwords/PINs)."""
    try:
        with open(os.path.join(BASE, "startup.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def money(x):
    """Format monetary amount with thousands separators + EGP."""
    try:
        return "%s %s" % (format(float(x), ",.2f"), EGP)
    except Exception:
        return "0.00 %s" % EGP


def safe_float(v, default=0.0):
    try:
        return float(str(v).strip() or default)
    except Exception:
        return default


def safe_int(v, default=1):
    try:
        return int(float(str(v).strip() or default))
    except Exception:
        return default


def strict_float(v, label="القيمة"):
    """Parse float strictly; invalid text raises clear Arabic ValueError."""
    txt = str(v).strip()
    if not txt:
        return None
    try:
        val = float(txt)
    except Exception:
        raise ValueError("%s غير صالحة — أدخل رقماً صحيحاً" % label)
    if val != val or val in (float("inf"), float("-inf")):
        raise ValueError("%s غير صالحة — أدخل رقماً صحيحاً" % label)
    return val


def strict_int(v, label="القيمة"):
    """Parse whole integer strictly."""
    val = strict_float(v, label)
    if val is None:
        return None
    if val != int(val):
        raise ValueError("%s يجب أن تكون عدداً صحيحاً (بدون كسور)" % label)
    return int(val)


def qr_url_with_pin(url, pin):
    """Build phone QR URL carrying the 6-digit PIN in the fragment (#pin=...)."""
    base = str(url or "").strip().split("#", 1)[0]
    value = str(pin or "").strip()
    try:
        parts = urlsplit(base)
        query = urlencode(
            [
                (key, val)
                for key, val in parse_qsl(parts.query, keep_blank_values=True)
                if key.lower() != "pin"
            ]
        )
        if parts.scheme and parts.netloc and not parts.path:
            base = urlunsplit((parts.scheme, parts.netloc, "/", query, ""))
        else:
            base = urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    except ValueError:
        return ""
    if base and len(value) == 6 and value.isdigit():
        return base + "#pin=" + value
    return base
