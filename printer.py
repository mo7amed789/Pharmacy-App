# -*- coding: utf-8 -*-
"""
printer.py — v5.10 (audit step 3): receipt + barcode-label printing.

Stdlib only. No new packages.

What it does
------------
1. Receipts/labels are saved as text files under ``receipts/`` inside the
   app folder (auto-created) instead of loose ``receipt_*.txt`` files in
   the app root. Files older than 30 days are pruned on startup and on
   every print (``prune_receipts``).
2. Two print paths, chosen in Settings (defaults keep the OLD behaviour):
   - "windows" (default): the saved text file is sent to the Windows
     default printer with ``os.startfile(path, "print")`` — exactly what
     the app did before.
   - "escpos": raw ESC/POS bytes are sent straight to a thermal printer
     on Windows via winspool (``OpenPrinterW`` / ``WritePrinter``) or,
     for a raw port name such as ``COM1`` / ``LPT1``, via ``CreateFileW``.
     If the raw send fails for any reason the caller falls back to the
     Windows-default path and says so — printing never silently dies.
3. Cash-drawer kick (``ESC p 0 0x19 0xFA``) is appended ONLY when the
   caller says the sale was cash AND the drawer-kick setting is on AND
   the raw ESC/POS path is used. It is NEVER sent to a normal Windows
   printer.

Arabic on ESC/POS — read this before expecting pretty output
------------------------------------------------------------
Thermal printers do not understand Unicode and do not shape Arabic:
* CP864 holds Arabic letters ONLY in their presentation forms
  (isolated / initial / medial / final), so the text MUST be shaped
  first — that is what ``shape_arabic`` does (joining forms + lam-alef
  ligatures). Python's ``cp864`` codec cannot encode plain base
  letters (U+0627 etc.) at all, which is why unshaped Arabic fails.
  CP864 is also missing most medial/final forms, so those are replaced
  with the closest form the page has (medial -> initial, final ->
  isolated) — the established practice for Arabic ESC/POS.
* Windows-1256 holds the plain base letters but NOT the presentation
  forms, so on most printers it prints UNJOINED (disconnected) letters.
  It is used here only as a fallback when a line cannot be encoded
  in CP864 (e.g. a character with no presentation form).
* The ``ESC t n`` code-page NUMBER is not standard across brands.
  Epson numbers are CP864 = 37 and WPC1256 = 50 (the defaults here);
  other printers use e.g. 22 / 46 / 41. Print the printer's self-test
  page (hold FEED while powering on) and put YOUR printer's numbers
  in Settings if Arabic comes out wrong.
* Line direction is a simplified bidi pass (``visual_order``): Arabic
  runs are reversed, Latin/digit runs keep their order. Mixed lines
  (Arabic + numbers) are best-effort — check the first receipt on
  the real printer.
* Bottom line: Latin text, digits and prices print fine on any
  ESC/POS printer. Arabic prints JOINED via CP864 on printers whose
  firmware supports it; on printers without Arabic firmware the
  letters may come out disconnected or as ``?`` — that is a printer
  limitation, not a bug in these bytes. The Windows-default path
  (Notepad) always renders Arabic correctly.

Barcode labels
--------------
The codebase has NO Code-128 barcode encoder (``qrgen.py`` is QR-only),
so a label prints the drug name + price + barcode NUMBER as text.
Graphical barcode bars need a real encoder — deliberately NOT faked
with a hand-drawn bar pattern.

NOT tested on real printer hardware: the byte stream is unit-tested
offline (init + text + cut present, kick only when asked), but no
thermal printer was available in this VM. The first real print is
the real test.
"""

import os
import re
import time

# ---------------------------------------------------------------- settings
SETTING_PRINTER_TYPE = "printer_type"    # "windows" (default) | "escpos"
SETTING_PRINTER_NAME = "printer_name"    # Windows printer name or COM/LPT port
SETTING_PRINTER_WIDTH = "printer_width"  # "80mm" (default) | "58mm"
SETTING_PRINTER_KICK = "printer_drawer_kick"  # "1" | "0" (default "0")
SETTING_CP864_PAGE = "printer_cp864_page"    # ESC t number, Epson default "37"
SETTING_CP1256_PAGE = "printer_cp1256_page"  # ESC t number, Epson default "50"

RECEIPTS_RETENTION_DAYS = 30
RECEIPT_PREFIXES = ("receipt_", "label_")

ESC_INIT = b"\x1b\x40"          # ESC @ — initialise printer
ESC_CUT = b"\x1d\x56\x00"       # GS V 0 — full cut
DRAWER_KICK = b"\x1b\x70\x00\x19\xfa"  # ESC p m=0 t1=0x19 t2=0xFA (pin 2)

DEFAULT_CP864_PAGE = 37   # Epson number for PC864 (Arabic)
DEFAULT_CP1256_PAGE = 50  # Epson number for WPC1256 (Arabic)


def width_chars_for(paper_width):
    """Printable characters per line (font A): 80mm -> 48, 58mm -> 32."""
    return 32 if (paper_width or "80mm") == "58mm" else 48


# ------------------------------------------------------------ receipts dir
def receipts_dir(base):
    """The receipts/ folder under the app folder; created on demand."""
    folder = os.path.join(base, "receipts")
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        pass
    return folder


def save_text(base, filename, text):
    """Save a receipt/label text file under receipts/. Returns the path."""
    folder = receipts_dir(base)
    path = os.path.join(folder, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def prune_receipts(base, days=RECEIPTS_RETENTION_DAYS):
    """Delete receipt_*.txt / label_*.txt older than ``days`` in receipts/.
    Returns how many files were removed. Never raises."""
    removed = 0
    try:
        folder = os.path.join(base, "receipts")
        if not os.path.isdir(folder):
            return 0
        cutoff = time.time() - days * 24 * 3600
        for name in os.listdir(folder):
            if not (name.startswith(RECEIPT_PREFIXES) and name.endswith(".txt")):
                continue
            path = os.path.join(folder, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except Exception:
                continue
    except Exception:
        pass
    return removed


# ------------------------------------------------------- Arabic shaping
# char -> (isolated, final, initial, medial); right-joining-only letters
# have just (isolated, final); non-joining letters just (isolated,).
_FORMS = {
    "\u0621": ("\uFE80",),                                  # ء hamza
    "\u0622": ("\uFE81", "\uFE82"),                         # آ
    "\u0623": ("\uFE83", "\uFE84"),                         # أ
    "\u0624": ("\uFE85", "\uFE86"),                         # ؤ
    "\u0625": ("\uFE87", "\uFE88"),                         # إ
    "\u0626": ("\uFE89", "\uFE8A", "\uFE8B", "\uFE8C"),     # ئ
    "\u0627": ("\uFE8D", "\uFE8E"),                         # ا
    "\u0628": ("\uFE8F", "\uFE90", "\uFE91", "\uFE92"),     # ب
    "\u0629": ("\uFE93", "\uFE94"),                         # ة
    "\u062A": ("\uFE95", "\uFE96", "\uFE97", "\uFE98"),     # ت
    "\u062B": ("\uFE99", "\uFE9A", "\uFE9B", "\uFE9C"),     # ث
    "\u062C": ("\uFE9D", "\uFE9E", "\uFE9F", "\uFEA0"),     # ج
    "\u062D": ("\uFEA1", "\uFEA2", "\uFEA3", "\uFEA4"),     # ح
    "\u062E": ("\uFEA5", "\uFEA6", "\uFEA7", "\uFEA8"),     # خ
    "\u062F": ("\uFEA9", "\uFEAA"),                         # د
    "\u0630": ("\uFEAB", "\uFEAC"),                         # ذ
    "\u0631": ("\uFEAD", "\uFEAE"),                         # ر
    "\u0632": ("\uFEAF", "\uFEB0"),                         # ز
    "\u0633": ("\uFEB1", "\uFEB2", "\uFEB3", "\uFEB4"),     # س
    "\u0634": ("\uFEB5", "\uFEB6", "\uFEB7", "\uFEB8"),     # ش
    "\u0635": ("\uFEB9", "\uFEBA", "\uFEBB", "\uFEBC"),     # ص
    "\u0636": ("\uFEBD", "\uFEBE", "\uFEBF", "\uFEC0"),     # ض
    "\u0637": ("\uFEC1", "\uFEC2", "\uFEC3", "\uFEC4"),     # ط
    "\u0638": ("\uFEC5", "\uFEC6", "\uFEC7", "\uFEC8"),     # ظ
    "\u0639": ("\uFEC9", "\uFECA", "\uFECB", "\uFECC"),     # ع
    "\u063A": ("\uFECD", "\uFECE", "\uFECF", "\uFED0"),     # غ
    "\u0641": ("\uFED1", "\uFED2", "\uFED3", "\uFED4"),     # ف
    "\u0642": ("\uFED5", "\uFED6", "\uFED7", "\uFED8"),     # ق
    "\u0643": ("\uFED9", "\uFEDA", "\uFEDB", "\uFEDC"),     # ك
    "\u0644": ("\uFEDD", "\uFEDE", "\uFEDF", "\uFEE0"),     # ل
    "\u0645": ("\uFEE1", "\uFEE2", "\uFEE3", "\uFEE4"),     # م
    "\u0646": ("\uFEE5", "\uFEE6", "\uFEE7", "\uFEE8"),     # ن
    "\u0647": ("\uFEE9", "\uFEEA", "\uFEEB", "\uFEEC"),     # ه
    "\u0648": ("\uFEED", "\uFEEE"),                         # و
    "\u0649": ("\uFEEF", "\uFEF0"),                         # ى
    "\u064A": ("\uFEF1", "\uFEF2", "\uFEF3", "\uFEF4"),     # ي
}
# lam + alef ligatures: (isolated, final)
_LAM_ALEF = {
    "\u0627": ("\uFEFB", "\uFEFC"),  # لا
    "\u0623": ("\uFEF7", "\uFEF8"),  # لأ
    "\u0625": ("\uFEF9", "\uFEFA"),  # لإ
    "\u0622": ("\uFEF5", "\uFEF6"),  # لآ
}
_DIACRITICS = re.compile("[\u064B-\u0652\u0670\u0640]")  # harakaat + tatweel


def _build_cp864_closest():
    """CP864 does NOT contain every presentation form (e.g. most medial
    and final forms are missing). The established practice is to use the
    closest form that IS in the page: medial -> initial, final ->
    isolated (and isolated -> initial when even the isolated form is
    missing, as for ئ). This is computed from the codec itself, so it
    stays correct even if the codec table changes."""
    closest = {}
    for _forms in list(_FORMS.values()) + [v for v in _LAM_ALEF.values()]:
        n = len(_forms)
        # preference order per form index: medial(3)->initial(2)->isolated(0)
        # final(1)->isolated(0)->initial(2); initial(2)->isolated(0);
        # isolated(0)->initial(2)->final(1)
        _prefs = {0: (2, 1), 1: (0, 2), 2: (0,), 3: (2, 0)}
        for idx, ch in enumerate(_forms):
            try:
                ch.encode("cp864")
                continue
            except UnicodeEncodeError:
                pass
            for alt in _prefs.get(idx, (0,)):
                if alt < n:
                    try:
                        _forms[alt].encode("cp864")
                        closest[ch] = _forms[alt]
                        break
                    except UnicodeEncodeError:
                        continue
    return closest


_CP864_CLOSEST = _build_cp864_closest()


# إ (alef with hamza below) has NO form at all in CP864 — neither
# isolated nor final. The standard degradation is plain alef
# (the hamza below is simply lost, as documented by ESC/POS Arabic
# implementations). Applied only when no same-letter form exists.
_CP864_BASE_FALLBACK = {
    "\uFE87": "\uFE8D",  # إ isolated -> ا isolated
    "\uFE88": "\uFE8E",  # إ final    -> ا final
}
# The لإ ligature has NO form at all in CP864 (neither FEF9 nor FEFA
# is in the page), so it is expanded back into ل + إ before encoding.
# (The other three lam-alef ligatures — لا لأ لآ — are in CP864.)
_LIGATURE_EXPAND = {
    "\uFEF9": "\uFEDD\uFE87",  # لإ isolated -> ل isolated + إ isolated
    "\uFEFA": "\uFEDF\uFE87",  # لإ final    -> ل initial  + إ isolated
}


def _to_cp864(shaped):
    """Encode shaped text to CP864, substituting the closest available
    presentation form where the exact form is missing from the page.
    Returns bytes, or None if a character still cannot be encoded."""
    expanded = "".join(_LIGATURE_EXPAND.get(ch, ch) for ch in shaped)
    try:
        return expanded.encode("cp864")
    except UnicodeEncodeError:
        pass
    out = []
    for ch in expanded:
        try:
            out.append(ch.encode("cp864"))
        except UnicodeEncodeError:
            alt = _CP864_CLOSEST.get(ch) or _CP864_BASE_FALLBACK.get(ch)
            if alt is None:
                return None
            try:
                out.append(alt.encode("cp864"))
            except UnicodeEncodeError:
                return None
    return b"".join(out)


def _is_arabic_letter(ch):
    return ch in _FORMS


def _joins_forward(ch):
    """Can this letter extend a join to the NEXT letter? Only dual-joining."""
    return ch in _FORMS and len(_FORMS[ch]) == 4


def _accepts_join(ch):
    """Can this letter accept a join FROM the previous letter?"""
    return ch in _FORMS and len(_FORMS[ch]) >= 2


def shape_arabic(text):
    """Shape Arabic letters into presentation forms (with lam-alef
    ligatures). Diacritics are dropped — thermal printers cannot render
    them. Non-Arabic characters pass through untouched."""
    text = _DIACRITICS.sub("", text or "")
    # Merge lam + alef into one ligature unit first.
    units = []  # each unit: ("char", ch) or ("lamalef", alef)
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\u0644" and i + 1 < len(text) and text[i + 1] in _LAM_ALEF:
            units.append(("lamalef", text[i + 1]))
            i += 2
        else:
            units.append(("char", ch))
            i += 1
    out = []
    for idx, (kind, ch) in enumerate(units):
        if kind == "lamalef":
            prev = units[idx - 1][1] if idx > 0 else None
            joins_left = prev is not None and _joins_forward(prev)
            forms = _LAM_ALEF[ch]
            out.append(forms[1] if joins_left else forms[0])
            continue
        if not _is_arabic_letter(ch):
            out.append(ch)
            continue
        prev = units[idx - 1][1] if idx > 0 else None
        nxt = units[idx + 1][1] if idx + 1 < len(units) else None
        # A lam-alef ligature before us joins forward like a dual letter.
        if idx > 0 and units[idx - 1][0] == "lamalef":
            joins_left = False  # ligature ends the word (lam-alef never joins on)
            # (lam-alef is final/isolated only, so nothing joins after it)
        else:
            joins_left = prev is not None and _joins_forward(prev)
        next_is_ligature = idx + 1 < len(units) and units[idx + 1][0] == "lamalef"
        if next_is_ligature:
            joins_right = False  # ligature cannot accept a join from the left
        else:
            joins_right = nxt is not None and _accepts_join(nxt)
        forms = _FORMS[ch]
        if len(forms) == 4:
            if joins_left and joins_right:
                out.append(forms[3])  # medial
            elif joins_left:
                out.append(forms[1])  # final
            elif joins_right:
                out.append(forms[2])  # initial
            else:
                out.append(forms[0])  # isolated
        elif len(forms) == 2:
            out.append(forms[1] if joins_left else forms[0])
        else:
            out.append(forms[0])
    return "".join(out)


def _is_shaped_arabic(ch):
    return "\uFB50" <= ch <= "\uFEFF"


def visual_order(line):
    """Simplified bidi: reverse each Arabic run and reverse the order of
    runs, so a right-to-left line prints in visual order. Latin/digit
    runs keep their internal order. Best-effort for mixed lines."""
    if not line:
        return line
    runs = []  # (is_arabic, text)
    cur_ar = _is_arabic_letter(line[0]) or _is_shaped_arabic(line[0])
    cur = [line[0]]
    for ch in line[1:]:
        ar = _is_arabic_letter(ch) or _is_shaped_arabic(ch)
        if ar == cur_ar:
            cur.append(ch)
        else:
            runs.append((cur_ar, "".join(cur)))
            cur_ar, cur = ar, [ch]
    runs.append((cur_ar, "".join(cur)))
    if not any(ar for ar, _ in runs):
        return line
    out = []
    for ar, text in reversed(runs):
        out.append(text[::-1] if ar else text)
    return "".join(out)


def _encode_line(line, cp864_page, cp1256_page):
    """Encode one receipt line for ESC/POS.
    Returns (code_page_number, bytes). Prefers shaped CP864 (joined
    letters); falls back to unshaped Windows-1256 (usually unjoined);
    last resort replaces unencodable characters with '?'."""
    shaped = visual_order(shape_arabic(line))
    data = _to_cp864(shaped)
    if data is not None:
        return cp864_page, data
    plain = visual_order(_DIACRITICS.sub("", line))
    try:
        return cp1256_page, plain.encode("cp1256")
    except UnicodeEncodeError:
        pass
    return cp864_page, plain.encode("cp864", errors="replace")


def _wrap_logical(line, width):
    """Word-wrap a logical (unshaped) line to ``width`` chars. Never
    splits a word in the middle (that would break Arabic joining);
    a single over-long word is truncated."""
    if len(line) <= width:
        return [line]
    out, cur = [], ""
    for word in line.split(" "):
        if len(word) > width:
            word = word[:width]
        if cur and len(cur) + 1 + len(word) > width:
            out.append(cur)
            cur = word
        else:
            cur = (cur + " " + word) if cur else word
    if cur:
        out.append(cur)
    return out or [""]


_BOLD_PREFIXES = ("الإجمالي:", "المدفوع:", "المجموع:", "الخصم:", "الباقي:")


def build_escpos_receipt(lines, width_chars=48, kick=False,
                         cp864_page=DEFAULT_CP864_PAGE,
                         cp1256_page=DEFAULT_CP1256_PAGE):
    """Build the raw ESC/POS byte stream for a receipt.
    Contains: ESC @ init, the text, feed + GS V full cut, and — only
    when ``kick`` is True — the drawer-kick command after the cut."""
    out = bytearray(ESC_INIT)
    current_page = None
    for raw in lines:
        bold = raw.startswith(_BOLD_PREFIXES)
        for wline in _wrap_logical(raw, width_chars):
            page, data = _encode_line(wline, cp864_page, cp1256_page)
            if page != current_page:
                out += b"\x1b\x74" + bytes([page & 0xFF])
                current_page = page
            if bold:
                out += b"\x1b\x45\x01"
            out += data + b"\n"
            if bold:
                out += b"\x1b\x45\x00"
    out += b"\n\n" + ESC_CUT
    if kick:
        out += DRAWER_KICK
    return bytes(out)


def build_escpos_label(name, price_text, barcode, size="50x25",
                       width_chars=48,
                       cp864_page=DEFAULT_CP864_PAGE,
                       cp1256_page=DEFAULT_CP1256_PAGE):
    """Build the raw ESC/POS byte stream for a barcode label.
    Name (double-height on the 50x25 size) + price + barcode NUMBER
    as text, centred, then cut. No graphical barcode bars: the
    codebase has no Code-128 encoder (qrgen.py is QR-only)."""
    out = bytearray(ESC_INIT)
    out += b"\x1b\x61\x01"  # centre align
    current_page = None

    def _emit(text, double=False):
        nonlocal current_page
        for wline in _wrap_logical(text, width_chars // 2 if double else width_chars):
            page, data = _encode_line(wline, cp864_page, cp1256_page)
            if page != current_page:
                out.extend(b"\x1b\x74" + bytes([page & 0xFF]))
                current_page = page
            if double:
                out.extend(b"\x1d\x21\x11")  # double width + double height
            out.extend(data + b"\n")
            if double:
                out.extend(b"\x1d\x21\x00")

    _emit(name, double=(size == "50x25"))
    _emit(price_text)
    _emit(barcode)
    out += b"\n" + ESC_CUT
    return bytes(out)


# ------------------------------------------------------- Windows raw send
def send_raw_windows(printer_name, data):
    """Send raw bytes to a Windows printer. Returns (ok, message).
    Non-Windows always returns (False, ...) — the caller falls back to
    the Windows-default print path. Never raises."""
    if os.name != "nt":
        return False, "الطباعة المباشرة ESC/POS متاحة على ويندوز فقط"
    if not printer_name or not str(printer_name).strip():
        return False, "لم يتم تحديد اسم طابعة ESC/POS في الإعدادات"
    printer_name = str(printer_name).strip()
    if re.match(r"^(COM|LPT)\d+$", printer_name, re.I) or \
            printer_name.startswith("\\\\.\\"):
        return _send_raw_port(printer_name, data)
    return _send_raw_winspool(printer_name, data)


def _send_raw_port(port_name, data):
    """Write raw bytes straight to a COM/LPT port (e.g. COM1)."""
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        handle = kernel32.CreateFileW(port_name, GENERIC_WRITE, 0, None,
                                      OPEN_EXISTING, 0, None)
        if not handle or handle == ctypes.c_void_p(-1).value:
            return False, "تعذّر فتح المنفذ %s" % port_name
        try:
            written = ctypes.c_ulong(0)
            ok = kernel32.WriteFile(handle, data, len(data),
                                    ctypes.byref(written), None)
            if not ok or written.value != len(data):
                return False, "تعذّرت الكتابة على المنفذ %s" % port_name
        finally:
            kernel32.CloseHandle(handle)
        return True, "أُرسلت إلى %s" % port_name
    except Exception as e:
        return False, "خطأ في المنفذ %s: %s" % (port_name, e)


def _send_raw_winspool(printer_name, data):
    """Send raw bytes via winspool (OpenPrinterW + WritePrinter, RAW)."""
    try:
        import ctypes
        from ctypes import wintypes
        winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)

        class DOC_INFO_1W(ctypes.Structure):
            _fields_ = [("pDocName", wintypes.LPWSTR),
                        ("pOutputFile", wintypes.LPWSTR),
                        ("pDatatype", wintypes.LPWSTR)]

        winspool.OpenPrinterW.argtypes = [wintypes.LPWSTR,
                                          ctypes.POINTER(wintypes.HANDLE),
                                          ctypes.c_void_p]
        winspool.OpenPrinterW.restype = wintypes.BOOL
        winspool.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                              ctypes.POINTER(DOC_INFO_1W)]
        winspool.StartDocPrinterW.restype = wintypes.DWORD
        winspool.StartPagePrinter.argtypes = [wintypes.HANDLE]
        winspool.StartPagePrinter.restype = wintypes.BOOL
        winspool.WritePrinter.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                          wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD)]
        winspool.WritePrinter.restype = wintypes.BOOL
        winspool.EndPagePrinter.argtypes = [wintypes.HANDLE]
        winspool.EndPagePrinter.restype = wintypes.BOOL
        winspool.EndDocPrinter.argtypes = [wintypes.HANDLE]
        winspool.EndDocPrinter.restype = wintypes.BOOL
        winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
        winspool.ClosePrinter.restype = wintypes.BOOL

        handle = wintypes.HANDLE()
        if not winspool.OpenPrinterW(printer_name, ctypes.byref(handle), None):
            return False, "تعذّر فتح الطابعة «%s» — تأكد من الاسم" % printer_name
        try:
            doc = DOC_INFO_1W("Pharmacy Receipt", None, "RAW")
            if not winspool.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
                return False, "تعذّر بدء مهمة الطباعة على «%s»" % printer_name
            try:
                if not winspool.StartPagePrinter(handle):
                    return False, "تعذّر بدء الصفحة على «%s»" % printer_name
                written = wintypes.DWORD(0)
                buf = ctypes.create_string_buffer(data, len(data))
                if not winspool.WritePrinter(handle, buf, len(data),
                                             ctypes.byref(written)) \
                        or written.value != len(data):
                    return False, "تعذّرت الكتابة إلى «%s»" % printer_name
                winspool.EndPagePrinter(handle)
            finally:
                winspool.EndDocPrinter(handle)
        finally:
            winspool.ClosePrinter(handle)
        return True, "أُرسلت إلى «%s»" % printer_name
    except Exception as e:
        return False, "خطأ في الطباعة المباشرة: %s" % e


def list_windows_printers():
    """Names of installed Windows printers (for the Settings dropdown).
    Returns [] on non-Windows or on any error — never raises."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes
        winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)

        class PRINTER_INFO_1W(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD),
                        ("pDescription", wintypes.LPWSTR),
                        ("pName", wintypes.LPWSTR),
                        ("pComment", wintypes.LPWSTR)]

        PRINTER_ENUM_LOCAL = 0x00000002
        PRINTER_ENUM_CONNECTIONS = 0x00000004
        winspool.EnumPrintersW.argtypes = [wintypes.DWORD, wintypes.LPWSTR,
                                           wintypes.DWORD, ctypes.c_void_p,
                                           wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD),
                                           ctypes.POINTER(wintypes.DWORD)]
        winspool.EnumPrintersW.restype = wintypes.BOOL
        needed = wintypes.DWORD(0)
        returned = wintypes.DWORD(0)
        winspool.EnumPrintersW(PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS,
                               None, 1, None, 0,
                               ctypes.byref(needed), ctypes.byref(returned))
        if needed.value == 0:
            return []
        buf = ctypes.create_string_buffer(needed.value)
        if not winspool.EnumPrintersW(PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS,
                                      None, 1, buf, needed,
                                      ctypes.byref(needed),
                                      ctypes.byref(returned)):
            return []
        names = []
        addr = ctypes.addressof(buf)
        for _ in range(returned.value):
            info = PRINTER_INFO_1W.from_address(addr)
            if info.pName:
                names.append(info.pName)
            addr += ctypes.sizeof(PRINTER_INFO_1W)
        return names
    except Exception:
        return []
