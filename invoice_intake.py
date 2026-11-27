# -*- coding: utf-8 -*-
"""Supplier invoice photo intake (draft only).

Flow: photo -> OCR text (local) -> candidate lines -> match to the drug
catalog -> REVIEW dialog -> purchase draft. This module never writes to
the database and never saves a purchase; the existing "save purchase"
button stays the only commit. Anything unclear is flagged, not guessed.

OCR providers (all LOCAL, nothing is uploaded):
  * "windows"   - the OCR built into Windows 10/11 (Windows.Media.Ocr),
                  called through PowerShell. Arabic needs the Arabic
                  language pack installed in Windows.
  * "tesseract" - used only if tesseract.exe is installed and on PATH.
A cloud OCR/vision provider is intentionally NOT included: it would send
invoice images (supplier names, prices) out of the PC and needs the
owner's explicit approval first.
"""
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬،", "0123456789.,,")
_NUM = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})*(?:\.\d+)?(?![\w])|(?<![\w.])\d+(?:\.\d+)?(?![\w])")
_EXP = re.compile(r"(?<!\d)(?:(\d{1,2})[/\-.](\d{4})|(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})|(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2}))(?!\d)")
_SKIP = re.compile(r"(total|subtotal|vat|tax|discount|balance|paid|الاجمالي|الإجمالي|اجمالي|المجموع|ضريبة|خصم|الصافي|المدفوع|رقم الفاتورة|invoice\s*(no|#)|tel|phone|ت:|هاتف)", re.I)
_LETTERS = re.compile(r"[A-Za-z\u0600-\u06FF]{2,}")


def norm_digits(text):
    return (text or "").translate(_AR_DIGITS)


def _num(tok):
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def _norm_name(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\u0600-\u06FF ]+", " ", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"\s+", " ", s).strip()


def _expiry(m):
    """-> (full_date_or_"", month_or_"", note). Never invents a day.
    Month/year stays month-only. d/m/y with both parts <= 12 is
    ambiguous (day-first or month-first), so no date is produced."""
    if m.group(1):
        mo, yr = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 2000 <= yr <= 2100:
            return "", "%04d-%02d" % (yr, mo), "الصلاحية شهر/سنة فقط — أدخل اليوم بنفسك"
        return "", "", ""
    if m.group(3):
        a, b, yr = int(m.group(3)), int(m.group(4)), int(m.group(5))
        if yr < 100:
            yr += 2000
        if a <= 12 and b <= 12 and a != b:
            return "", "", "تاريخ الصلاحية ملتبس (يوم/شهر أم شهر/يوم) — أدخله بنفسك"
        d, mo = a, b
        if mo > 12:
            d, mo = b, a
    else:
        yr, mo, d = int(m.group(6)), int(m.group(7)), int(m.group(8))
    try:
        return date(yr, mo, d).isoformat(), "", ""
    except ValueError:
        return "", "", "تاريخ صلاحية غير صالح"


def parse_invoice_text(text):
    """Return {"invoice_no", "lines": [...]}. Each line has name, qty,
    price, total, expiry, batch, raw and a list of `flags` (reasons the
    reviewer must look). Never invents a value: a missing one is None."""
    text = norm_digits(text or "")
    inv_no = ""
    m = re.search(r"(?:invoice\s*(?:no|number|#)?|رقم\s*الفاتورة|فاتورة\s*رقم)\s*[:#]?\s*([A-Za-z0-9\-/]{3,})", text, re.I)
    if m:
        inv_no = m.group(1)
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if len(s) < 4 or _SKIP.search(s) or not _LETTERS.search(s):
            continue
        exp, exp_month, exp_note = "", "", ""
        em = _EXP.search(s)
        body = s
        if em:
            exp, exp_month, exp_note = _expiry(em)
            body = s[:em.start()] + " " + s[em.end():]
        bc = ""
        bcm = re.search(r"(?<!\d)(\d{8}|\d{12,14})(?!\d)", body)
        if bcm:
            bc = bcm.group(1)
            body = body[:bcm.start()] + " " + body[bcm.end():]
        bm = re.search(r"(?:batch|lot|b\.?no|تشغيلة|باتش)\s*[:#]?\s*([A-Za-z0-9\-]{2,})", body, re.I)
        batch = bm.group(1) if bm else ""
        if bm:
            body = body[:bm.start()] + " " + body[bm.end():]
        first_num = _NUM.search(body)
        if not first_num:
            continue
        name = re.sub(r"\s+", " ", body[:first_num.start()]).strip(" -:|.،")
        # strengths like "500 mg" belong to the name, not the numbers
        tail = body[first_num.start():]
        sm = re.match(r"\s*(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|iu|%|مجم|مج|جم|جرام|مل)\b", tail, re.I)
        while sm:
            name = (name + " " + sm.group(0).strip()).strip()
            tail = tail[sm.end():]
            sm = re.match(r"\s*(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|iu|%|مجم|مج|جم|جرام|مل)\b", tail, re.I)
        nums = [_num(t) for t in _NUM.findall(tail)]
        nums = [n for n in nums if n is not None]
        if len(name) < 3 or not nums:
            continue
        flags = []
        qty = price = total = None
        if len(nums) >= 3:
            a, b, c = nums[0], nums[1], nums[2]
            if abs(a * b - c) <= max(0.05, 0.01 * c):
                qty, price, total = a, b, c
            elif abs(a * c - b) <= max(0.05, 0.01 * b):
                qty, price, total = a, c, b
            else:
                qty, price, total = a, b, c
                flags.append("الكمية × السعر ≠ الإجمالي")
        elif len(nums) == 2:
            qty, price = nums
            flags.append("لا يوجد إجمالي للسطر للتحقق")
        else:
            qty = nums[0]
            flags.append("السعر غير مقروء")
        if qty is not None and (qty <= 0 or qty != int(qty)):
            flags.append("الكمية غير صحيحة")
        if price is not None and price <= 0:
            flags.append("السعر غير صالح")
        if exp_note:
            flags.append(exp_note)
        elif not exp:
            flags.append("الصلاحية غير مقروءة")
        if not batch:
            flags.append("التشغيلة غير مقروءة")
        lines.append({"raw": s, "name": name, "qty": qty, "price": price,
                      "total": total, "expiry": exp, "expiry_month": exp_month,
                      "batch": batch, "barcode": bc, "flags": flags})
    return {"invoice_no": inv_no, "lines": lines}


def match_drug(db, name, limit=3):
    """Candidates [(score, drug)] best first. A match is only `confident`
    (see annotate) when clearly ahead of the runner-up."""
    key = _norm_name(name)
    if not key:
        return []
    words = [w for w in key.split() if len(w) >= 3] or key.split()
    seen, pool = {}, []
    for w in words[:3]:
        for d in db.search_drugs(w, limit=60):
            if d["id"] not in seen:
                seen[d["id"]] = d
                pool.append(d)
    scored = []
    for d in pool:
        best = 0.0
        for cand in (d["trade_en"], d["trade_ar"], "%s %s" % (d["trade_en"], d["strength"] or "")):
            c = _norm_name(cand)
            if c:
                best = max(best, difflib.SequenceMatcher(None, key, c).ratio())
        scored.append((round(best, 3), d))
    scored.sort(key=lambda x: -x[0])
    return scored[:limit]


_STRENGTH = re.compile(r"\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu|%|مجم|مج|جم|جرام|مل)", re.I)


def _strengths(text):
    return {re.sub(r"\s+", "", x.lower()) for x in _STRENGTH.findall(norm_digits(text or ""))}


def annotate(db, parsed):
    """Medicine identity is NEVER accepted from a fuzzy score.
    * exact barcode match in our catalog -> `drug` set, verified=True
    * otherwise the best name match is only a `suggestion`; `drug` stays
      None until the user explicitly confirms it in the review dialog.
    A suggestion whose strength differs from the invoice text is flagged."""
    for ln in parsed["lines"]:
        ln["drug"] = None
        ln["verified"] = False
        ln["suggestion"] = None
        ln["candidates"] = match_drug(db, ln["name"])
        if ln.get("barcode"):
            try:
                d, _lvl = db.lookup_barcode(ln["barcode"])
            except Exception:
                d = None
            if d:
                ln["drug"], ln["verified"] = d, True
                continue
        if not ln["candidates"]:
            ln["flags"].append("الصنف غير موجود في الكتالوج")
            continue
        sug = ln["candidates"][0][1]
        ln["suggestion"] = sug
        ln["flags"].append("اقتراح فقط — يجب تأكيد الصنف يدويا")
        inv_s = _strengths(ln["name"])
        cat_s = _strengths("%s %s" % (sug["trade_en"], sug["strength"] or ""))
        if inv_s and cat_s and inv_s != cat_s:
            ln["flags"].append("تحذير: التركيز يختلف عن الصنف المقترح")
        elif inv_s and not cat_s:
            ln["flags"].append("تحذير: لا يمكن التحقق من التركيز في الكتالوج")
        if len(ln["candidates"]) > 1 and ln["candidates"][1][0] >= ln["candidates"][0][0] - 0.08:
            ln["flags"].append("تحذير: أصناف متشابهة — انتبه للتركيز والعبوة")
    return parsed


def known_invoice(db, invoice_no):
    """True when a purchase with this supplier invoice number exists
    (possible repeat import of the same photo)."""
    if not invoice_no:
        return False
    return bool(db.conn.execute(
        "SELECT 1 FROM purchases WHERE invoice_no=? LIMIT 1", (invoice_no,)).fetchone())


def to_purchase_lines(parsed_lines, existing=None):
    """Convert REVIEWED lines into the app's purchase-draft dicts.
    A line is ready only when: the drug is confirmed (barcode match or
    the user pressed confirm), qty is a whole number > 0, price > 0, a
    FULL valid future expiry date is present (month-only or ambiguous
    dates must be completed by the user), and a qty x price != total
    mismatch was acknowledged by an edit. sell_price stays None so the
    existing selling price is untouched. Lines identical to one already
    in `existing` (repeat import) are skipped, not doubled."""
    ready, left = [], []
    today = date.today().isoformat()
    for ln in parsed_lines:
        ok = (ln.get("drug") and ln.get("qty") and ln.get("price")
              and ln["qty"] > 0 and ln["qty"] == int(ln["qty"]) and ln["price"] > 0)
        exp = ln.get("expiry") or ""
        try:
            date.fromisoformat(exp)
        except ValueError:
            exp = ""
        if not ok or not exp or exp < today:
            left.append(ln)
            continue
        if any("≠" in f for f in ln["flags"]) and not ln.get("numbers_confirmed"):
            left.append(ln)
            continue
        batch = ln.get("batch") or "INV-%s" % today
        item = {"drug": ln["drug"], "qty_boxes": int(ln["qty"]),
                "buy_price": float(ln["price"]), "sell_price": None,
                "batch_no": batch, "expiry": exp}
        dup = any(e["drug"]["id"] == item["drug"]["id"] and e.get("batch_no") == batch
                  and e.get("expiry") == exp for e in (existing or []) + ready)
        if dup:
            ln["flags"].append("مكرر في المسودة — تم تخطيه")
            left.append(ln)
            continue
        ready.append(item)
    return ready, left


# ---------------- local OCR providers ----------------
_PS = r'''
param([string]$Path, [string]$Lang)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics,ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
  $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$eng = $null
if ($Lang) { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Lang)) }
if (-not $eng) { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $eng) { Write-Error "no OCR language installed"; exit 2 }
$res = Await ($eng.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
foreach ($l in $res.Lines) { Write-Output $l.Text }
'''


class OcrUnavailable(RuntimeError):
    pass


def available_providers():
    out = []
    if sys.platform == "win32" and shutil.which("powershell"):
        out.append("windows")
    if shutil.which("tesseract"):
        out.append("tesseract")
    return out


def ocr_image(path, provider=None, lang="en-US"):
    """Local OCR of one image file -> text. Raises OcrUnavailable."""
    if not os.path.isfile(path):
        raise OcrUnavailable("الملف غير موجود")
    provs = available_providers()
    provider = provider or (provs[0] if provs else None)
    if provider not in provs:
        raise OcrUnavailable("لا يوجد محرك قراءة صور محلي (Windows OCR أو Tesseract)")
    if provider == "windows":
        fd, ps1 = tempfile.mkstemp(suffix=".ps1")
        try:
            with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
                f.write(_PS)
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1,
                 "-Path", os.path.abspath(path), "-Lang", lang],
                capture_output=True, text=True, timeout=90, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        finally:
            try:
                os.remove(ps1)
            except OSError:
                pass
        if r.returncode != 0:
            raise OcrUnavailable("فشل Windows OCR: " + (r.stderr or "").strip()[:200])
        return r.stdout
    r = subprocess.run(["tesseract", os.path.abspath(path), "stdout", "--psm", "6"],
                       capture_output=True, text=True, timeout=90, encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise OcrUnavailable("فشل Tesseract: " + (r.stderr or "").strip()[:200])
    return r.stdout
