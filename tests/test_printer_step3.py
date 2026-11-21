# -*- coding: utf-8 -*-
"""Step 3 (audit fix) offline tests for printer.py — stdlib only, no GUI,
no real printer. Run:  python3 test_printer_step3.py
NOT a real-hardware test: the ESC/POS byte stream is asserted here, but
no thermal printer was available in this VM."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import printer

PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, "FAIL: %s %s" % (name, extra)
    PASS += 1
    print("ok %d - %s" % (PASS, name))


# --- receipts folder + save + prune -------------------------------------
tmp = tempfile.mkdtemp(prefix="step3_printer_")
check("receipts dir auto-created", os.path.isdir(printer.receipts_dir(tmp)))
p = printer.save_text(tmp, "receipt_2026_1.txt", "line1\nline2")
check("receipt saved under receipts/",
      p == os.path.join(tmp, "receipts", "receipt_2026_1.txt")
      and open(p, encoding="utf-8").read() == "line1\nline2")
check("no receipt file in app root",
      not os.path.exists(os.path.join(tmp, "receipt_2026_1.txt")))
old = printer.save_text(tmp, "receipt_old.txt", "old")
os.utime(old, (time.time() - 31 * 86400, time.time() - 31 * 86400))
new = printer.save_text(tmp, "receipt_new.txt", "new")
other = os.path.join(tmp, "receipts", "keep_me.txt")
open(other, "w").write("x")
os.utime(other, (time.time() - 99 * 86400, time.time() - 99 * 86400))
check("prune removes only old receipt/label files",
      printer.prune_receipts(tmp) == 1
      and not os.path.exists(old)
      and os.path.exists(new) and os.path.exists(other))
check("prune on missing folder is 0", printer.prune_receipts(
    os.path.join(tmp, "nope")) == 0)

# --- Arabic shaping -------------------------------------------------------
shaped = printer.shape_arabic("السلام")
check("shaping produces presentation forms",
      all("\uFB50" <= ch <= "\uFEFF" for ch in shaped if ch.strip()),
      repr(shaped))
check("every arabic letter encodes in cp864 via shaping",
      all(printer._to_cp864(printer.shape_arabic("م" + ch + "م")) is not None
          for ch in "ابتثجحخدرزسشصضطظعغفقكلمنهويءآأؤإئةى"))
check("lam-alef variants all encode",
      all(printer._to_cp864(printer.shape_arabic(w)) is not None
          for w in ("لا", "لأ", "لإ", "لآ", "سلام", "إلى")))
check("alef alone is isolated form",
      printer.shape_arabic("ا") == "\uFE8D")
check("beh medial/initial forms differ",
      printer.shape_arabic("بب") == "\uFE91\uFE90", repr(printer.shape_arabic("بب")))
check("diacritics dropped", printer.shape_arabic("مُحَمَّد") ==
      printer.shape_arabic("محمد"))
check("latin passes through", printer.shape_arabic("Panadol 500") == "Panadol 500")
check("shaped arabic encodes in cp864 (closest-form fallback)",
      printer._encode_line("صيدلية المؤسسة", 37, 50)[0] == 37)
check("medial form falls back to initial in cp864",
      printer._CP864_CLOSEST.get("\uFEE4") == "\uFEE3"  # م medial -> initial
      and printer._CP864_CLOSEST.get("\uFE94") == "\uFE93")  # ة final -> isolated
try:
    "صيدلية".encode("cp864")
    check("unshaped arabic does NOT encode in cp864", False)
except UnicodeEncodeError:
    check("unshaped arabic does NOT encode in cp864", True)

# --- encoding selection ---------------------------------------------------
page, data = printer._encode_line("الإجمالي: 100.00 ج.م", 37, 50)
check("arabic line uses CP864 page", page == 37 and data)
page2, data2 = printer._encode_line("Pharmacy Enterprise", 37, 50)
check("latin line uses CP864 page too", page2 == 37 and b"Pharmacy" in data2)
# A character with no CP864 form (e.g. €) falls back to cp1256 path.
page3, data3 = printer._encode_line("السعر €100", 37, 50)
check("unencodable char falls back (no crash)", isinstance(data3, bytes))

# --- ESC/POS receipt bytes -------------------------------------------------
lines = ["Pharmacy Enterprise", "فاتورة: INV-1",
         "Panadol x2 @ 10.00 = 20.00", "-" * 34,
         "الإجمالي: 20.00 ج.م", "المدفوع: 20.00   الباقي: 0.00", "شكراً لزيارتك"]
raw = printer.build_escpos_receipt(lines, width_chars=48, kick=False)
check("receipt starts with ESC @ init", raw.startswith(b"\x1b\x40"))
check("receipt ends with full cut", raw.endswith(b"\x1d\x56\x00"))
check("receipt contains latin text", b"Pharmacy" in raw)
check("receipt contains shaped arabic bytes",
      printer._to_cp864(printer.visual_order(
          printer.shape_arabic("شكراً"))) in raw)
check("no drawer kick without kick=True", printer.DRAWER_KICK not in raw)
raw_kick = printer.build_escpos_receipt(lines, kick=True)
check("kick bytes present only when asked",
      raw_kick.endswith(printer.DRAWER_KICK)
      and printer.DRAWER_KICK == b"\x1b\x70\x00\x19\xfa")
check("kick comes after cut",
      raw_kick.index(b"\x1d\x56\x00") < raw_kick.index(printer.DRAWER_KICK))
raw58 = printer.build_escpos_receipt(lines, width_chars=32)
check("58mm build works", raw58.startswith(b"\x1b\x40") and b"\x1d\x56\x00" in raw58)
check("code-page select emitted", b"\x1b\x74\x25" in raw)  # ESC t 37 (CP864)
check("width helper", printer.width_chars_for("80mm") == 48
      and printer.width_chars_for("58mm") == 32)

# --- ESC/POS label bytes ----------------------------------------------------
lab = printer.build_escpos_label("Panadol Extra", "السعر: 25.00 ج.م",
                                 "6220000100000", size="50x25")
check("label starts with ESC @", lab.startswith(b"\x1b\x40"))
check("label is centred", b"\x1b\x61\x01" in lab)
check("label contains barcode number as text", b"6220000100000" in lab)
check("label ends with cut", lab.rstrip().endswith(b"\x1d\x56\x00"))
check("label has no drawer kick", printer.DRAWER_KICK not in lab)
lab38 = printer.build_escpos_label("Panadol Extra", "السعر: 25.00 ج.م",
                                   "6220000100000", size="38x25")
check("38x25 label builds", lab38.startswith(b"\x1b\x40")
      and b"6220000100000" in lab38)

# --- raw send guards (no Windows here) --------------------------------------
ok, msg = printer.send_raw_windows("Any Printer", b"test")
check("raw send on non-Windows fails gracefully, no raise",
      ok is False and msg)
ok, msg = printer.send_raw_windows("", b"test")
check("raw send with no printer name fails gracefully", ok is False)
check("list printers on non-Windows is []",
      printer.list_windows_printers() == [])

print("\n%d checks passed (offline only — NOT tested on real hardware)" % PASS)
