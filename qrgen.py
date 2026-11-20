# -*- coding: utf-8 -*-
"""
qrgen.py — self-contained QR Code encoder (stdlib only, no dependencies).

Pharmacy Enterprise v4.2: draws the "connect QR" on the PC (Mobile tab)
so a phone camera can open the mobile invoice page without typing the
URL. The QR encodes ONLY the URL (http://<PC-IP>:8080) — never the PIN;
the PIN is typed on the phone after the page opens.

What this module is (and is not):
  * Byte-mode QR codes, error-correction level M, versions 1-6.
    That covers up to 106 bytes of text — far more than any LAN URL
    (e.g. "http://192.168.137.1:8080" is 24 bytes, version 2).
  * Written for this project from the public ISO/IEC 18004 structure
    (function patterns, format information, Reed-Solomon over GF(256),
    the 8 mask patterns and the 4 penalty rules). No code was copied
    from another QR library, and no pip package is needed.
  * It is NOT a general-purpose QR library: no alphanumeric/kanji
    modes, no ECC levels L/Q/H, no versions above 6, no logo embedding.
    If the text is longer than version 6-M can hold, encode() raises
    ValueError and the caller must fall back to showing the URL as
    large text (see main.py _qr_refresh).

If you change anything in this file, re-run the checks in
/tmp/test_qr.py (format bits, Reed-Solomon remainder == 0, and the
data-bit read-back) — a QR that "looks right" but has a wrong ECC or
format word will NOT scan.
"""

# ---------------------------------------------------------------------------
# Tables (versions 1-6, ECC level M) — from the QR Code specification.
# ---------------------------------------------------------------------------
_TOTAL_CODEWORDS = [None, 26, 44, 70, 100, 134, 172]
_ECC_PER_BLOCK = [None, 10, 16, 26, 18, 24, 16]   # level M
_NUM_BLOCKS = [None, 1, 1, 1, 2, 2, 4]            # level M
_ALIGN_POS = [[], [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34]]
# ^ index = version. Version 1 has NO alignment pattern, so index 1
# is empty — forgetting that shifts every version's positions by one
# and draws alignment patterns on top of the finder patterns.
_MAX_VERSION = 6
_ECC_LEVEL_BITS = 0b00  # M = 00 in the 15-bit format word

# Known-good format word for (M, mask 0), from the QR specification's
# format-information table — used as a self-check in the tests.
_FORMAT_M_MASK0 = 0b101010000010010


def _data_codewords(version):
    return (_TOTAL_CODEWORDS[version]
            - _ECC_PER_BLOCK[version] * _NUM_BLOCKS[version])


# ---------------------------------------------------------------------------
# GF(256) arithmetic (primitive polynomial 0x11D) and Reed-Solomon.
# ---------------------------------------------------------------------------
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree):
    """Generator polynomial g(x) = prod_{i=0}^{degree-1} (x - a^i),
    coefficients in descending order, g[0] == 1."""
    poly = [1]
    for i in range(degree):
        # Multiply poly by (x + a^i).
        new = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            new[j] ^= c                # * x
            new[j + 1] ^= _gf_mul(c, _EXP[i])  # * a^i
        poly = new
    return poly


def _rs_remainder(data, degree):
    """ECC bytes for `data` (list of ints) with `degree` check bytes.
    Synthetic division by the generator polynomial; the returned
    bytes make (data + ecc) divisible by the generator."""
    gen = _rs_generator(degree)
    res = list(data) + [0] * degree
    for i in range(len(data)):
        coef = res[i]
        if coef:
            for j in range(1, len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data):]


# ---------------------------------------------------------------------------
# Format information (15 bits, BCH + mask 0x5412).
# ---------------------------------------------------------------------------
def _format_bits(mask):
    """15-bit format word for ECC level M and the given mask (0-7)."""
    data = (_ECC_LEVEL_BITS << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


# ---------------------------------------------------------------------------
# Mask patterns and penalty scoring (choice of mask only affects
# readability, never validity — any mask 0-7 with matching format
# bits is a legal QR code).
# ---------------------------------------------------------------------------
def _mask_bit(mask, r, c):
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask == 5:
        return (r * c) % 2 + (r * c) % 3 == 0
    if mask == 6:
        return ((r * c) % 2 + (r * c) % 3) % 2 == 0
    return ((r + c) % 2 + (r * c) % 3) % 2 == 0  # mask 7


def _penalty(modules):
    size = len(modules)
    score = 0
    # Rule 1: runs of 5+ same-colour modules in a row / column.
    for is_row in (True, False):
        for i in range(size):
            run_color = None
            run_len = 0
            for j in range(size):
                color = modules[i][j] if is_row else modules[j][i]
                if color == run_color:
                    run_len += 1
                else:
                    if run_len >= 5:
                        score += 3 + (run_len - 5)
                    run_color = color
                    run_len = 1
            if run_len >= 5:
                score += 3 + (run_len - 5)
    # Rule 2: 2x2 blocks of one colour.
    for r in range(size - 1):
        for c in range(size - 1):
            v = modules[r][c]
            if v == modules[r][c + 1] == modules[r + 1][c] == modules[r + 1][c + 1]:
                score += 3
    # Rule 3: finder-like pattern 1011101 with 4 light modules
    # immediately before or after it.
    for is_row in (True, False):
        for i in range(size):
            line = "".join("1" if (modules[i][j] if is_row else modules[j][i])
                           else "0" for j in range(size))
            for k in range(len(line) - 10):
                if line[k:k + 11] in ("00001011101", "10111010000"):
                    score += 40
    # Rule 4: proportion of dark modules.
    dark = sum(sum(1 for v in row if v) for row in modules)
    total = size * size
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    score += k * 10
    return score


# ---------------------------------------------------------------------------
# QR Code object.
# ---------------------------------------------------------------------------
class QrCode(object):
    def __init__(self, version, size, modules, mask):
        self.version = version
        self.size = size
        self.modules = modules  # rows of bool, True = dark
        self.mask = mask

    def dark_count(self):
        return sum(sum(1 for v in row if v) for row in self.modules)

    def to_ascii(self, dark="██", light="  "):
        out = []
        for row in self.modules:
            out.append("".join(dark if v else light for v in row))
        return "\n".join(out)


def _choose_version(data_len):
    """Smallest version 1-6 (ECC M, byte mode) that holds data_len bytes.
    Byte-mode capacity in bytes is data_codewords - 2 (mode + count
    indicators and the terminator)."""
    for ver in range(1, _MAX_VERSION + 1):
        if data_len <= _data_codewords(ver) - 2:
            return ver
    raise ValueError(
        "Text is too long for a version %d-M QR code (%d bytes max)."
        % (_MAX_VERSION, _data_codewords(_MAX_VERSION) - 2))


def _build_data_bits(data, version):
    """Byte-mode bit stream, padded to exactly data_codewords*8 bits."""
    bits = []

    def append_bits(value, length):
        for i in reversed(range(length)):
            bits.append((value >> i) & 1)

    append_bits(0b0100, 4)          # byte mode indicator
    append_bits(len(data), 8)       # character count (versions 1-9)
    for b in data:
        append_bits(b, 8)
    capacity = _data_codewords(version) * 8
    append_bits(0, min(4, capacity - len(bits)))  # terminator
    while len(bits) % 8 != 0:
        bits.append(0)              # pad to a byte boundary
    pad = 0xEC
    while len(bits) < capacity:
        append_bits(pad, 8)
        pad = 0x11 if pad == 0xEC else 0xEC
    return bits


def _interleave(data_bits, version):
    """Split data codewords into blocks, add ECC per block, interleave
    data bytes then ECC bytes (all blocks are equal-length for M, v1-6)."""
    data_bytes = []
    for i in range(0, len(data_bits), 8):
        byte = 0
        for bit in data_bits[i:i + 8]:
            byte = (byte << 1) | bit
        data_bytes.append(byte)
    nblocks = _NUM_BLOCKS[version]
    ecc_len = _ECC_PER_BLOCK[version]
    block_len = len(data_bytes) // nblocks
    blocks = [data_bytes[i * block_len:(i + 1) * block_len]
              for i in range(nblocks)]
    eccs = [_rs_remainder(b, ecc_len) for b in blocks]
    out = []
    for i in range(block_len):
        for b in blocks:
            out.append(b[i])
    for i in range(ecc_len):
        for e in eccs:
            out.append(e[i])
    result = []
    for byte in out:
        for i in reversed(range(8)):
            result.append((byte >> i) & 1)
    return result


class _Builder(object):
    def __init__(self, version):
        self.version = version
        self.size = version * 4 + 17
        self.modules = [[False] * self.size for _ in range(self.size)]
        self.is_function = [[False] * self.size for _ in range(self.size)]

    def set_function(self, x, y, dark):
        if 0 <= x < self.size and 0 <= y < self.size:
            self.modules[y][x] = bool(dark)
            self.is_function[y][x] = True

    def draw_finder(self, cx, cy):
        # Range -4..+4 INCLUSIVE on both sides: the +4 ring is the
        # white separator around the finder. range(-4, 4) would drop
        # it and leave data modules inside the separator zone.
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                dist = max(abs(dx), abs(dy))
                self.set_function(cx + dx, cy + dy, dist != 2 and dist != 4)

    def draw_function_modules(self):
        size = self.size
        # Timing FIRST: its row/column 6 passes through the finder
        # corners, where the finder pattern (all-dark edge) must win.
        # Drawing the finders after the timing overwrites the overlap
        # with the correct finder values.
        for i in range(size):
            self.set_function(i, 6, i % 2 == 0)
            self.set_function(6, i, i % 2 == 0)
        self.draw_finder(3, 3)
        self.draw_finder(size - 4, 3)
        self.draw_finder(3, size - 4)
        for ax in _ALIGN_POS[self.version]:
            for ay in _ALIGN_POS[self.version]:
                if (ax, ay) in ((6, 6), (6, size - 7), (size - 7, 6)):
                    continue  # overlaps a finder pattern
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_function(ax + dx, ay + dy,
                                          max(abs(dx), abs(dy)) != 1)
        # Reserve the format-information cells NOW (dummy mask 0):
        # data placement runs next and must skip them, or the real
        # format bits drawn later would overwrite data bits.
        self.draw_format_bits(0)

    def draw_format_bits(self, mask):
        bits = _format_bits(mask)
        size = self.size

        def bit(i):
            return (bits >> i) & 1 == 1

        for i in range(6):
            self.set_function(8, i, bit(i))
        self.set_function(8, 7, bit(6))
        self.set_function(8, 8, bit(7))
        self.set_function(7, 8, bit(8))
        for i in range(9, 15):
            self.set_function(14 - i, 8, bit(i))
        for i in range(8):
            self.set_function(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_function(8, size - 15 + i, bit(i))
        # Dark module: ALWAYS at (x=8, y=size-8) -- column 8, one row
        # above the vertical second copy of the format bits, at the
        # corner of the bottom-left finder's separator row. NOT at
        # (size-8, 8): that cell is format bit 7 of the horizontal
        # second copy, and putting the dark module there adds no new
        # function cell (it hides a format bit) -- the bug that left
        # one extra data cell (360 instead of 359 modules for V2).
        self.set_function(8, size - 8, True)  # always-dark module

    def place_data(self, bits):
        size = self.size
        i = 0
        for right in range(size - 1, 0, -2):
            if right <= 6:
                right -= 1
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = (size - 1 - vert) if upward else vert
                    if not self.is_function[y][x] and i < len(bits):
                        self.modules[y][x] = bool(bits[i])
                        i += 1
        if i != len(bits):
            raise ValueError("Data placement mismatch: placed %d of %d bits."
                             % (i, len(bits)))

    def apply_mask(self, mask):
        for y in range(self.size):
            for x in range(self.size):
                if not self.is_function[y][x] and _mask_bit(mask, y, x):
                    self.modules[y][x] = not self.modules[y][x]


def encode_qr(text):
    """Encode `text` (str, UTF-8) as a QrCode. Raises ValueError if the
    text is too long for version 6-M."""
    data = text.encode("utf-8")
    version = _choose_version(len(data))
    data_bits = _build_data_bits(data, version)
    final_bits = _interleave(data_bits, version)

    best = None
    for mask in range(8):
        b = _Builder(version)
        b.draw_function_modules()
        b.place_data(final_bits)
        b.apply_mask(mask)
        score = _penalty(b.modules)
        if best is None or score < best[0]:
            best = (score, mask, b)
    _, mask, builder = best
    builder.draw_format_bits(mask)
    return QrCode(version, builder.size, builder.modules, mask)


def encode_qr_matrix(text):
    """Convenience: return the module matrix (rows of bool) for `text`."""
    return encode_qr(text).modules


if __name__ == "__main__":
    import sys
    text = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.137.1:8080"
    qr = encode_qr(text)
    print("QR version %d, size %dx%d, mask %d, dark modules %d"
          % (qr.version, qr.size, qr.size, qr.mask, qr.dark_count()))
    print(qr.to_ascii())
