# -*- coding: utf-8 -*-
"""Offline product search helpers: Arabic/English normalization and typo tolerance.
Pure functions, no database access. Used by database.search_drugs."""
import re
import unicodedata

_AR_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه",
    "ک": "ك", "ی": "ي",
})
_TASHKEEL = re.compile("[\u064b-\u065f\u0670\u0640]")     # harakat, dagger alef, tatweel
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SPLIT = re.compile(r"[^0-9a-z\u0600-\u06ff]+")


def normalize(text):
    """Lowercase, strip accents/tashkeel/tatweel, unify alef/yeh/teh-marbuta forms, Arabic digits to ASCII."""
    t = unicodedata.normalize("NFKD", str(text or "")).lower()
    t = "".join(ch for ch in t if not (unicodedata.combining(ch) and ord(ch) < 0x300 + 0x70))
    t = _TASHKEEL.sub("", t).translate(_AR_MAP).translate(_AR_DIGITS)
    return t


def words(text):
    return [w for w in _SPLIT.split(normalize(text)) if w]


def compact(text):
    return "".join(words(text))


def max_typos(n):
    """Allowed edit distance for a word of length n: none for very short words (avoids noise)."""
    return 0 if n <= 3 else (1 if n <= 6 else 2)


def edit_distance(a, b, limit):
    """Damerau-Levenshtein (adjacent swap = 1) bounded by limit; returns limit+1 when exceeded."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > limit:
        return limit + 1
    prev2, prev = None, list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        best = cur[0]
        for j in range(1, lb + 1):
            c = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + c)
            if prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
            if v < best:
                best = v
        if best > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[lb] if prev[lb] <= limit else limit + 1


class Index:
    """In-memory index of normalized names. Build once, query many times."""

    def __init__(self, rows):
        # rows: iterable of (id, trade_en, trade_ar, scientific, company)
        self.ids, self.names, self.compacts, self.full = [], [], [], []
        self.vocab = {}          # word -> set(row index), from trade names only
        for i, (rid, en, ar, sci, comp) in enumerate(rows):
            nm = normalize(en) + " | " + normalize(ar)
            self.ids.append(rid)
            self.names.append(nm)
            self.compacts.append(compact(nm))
            self.full.append(compact(nm + " " + str(sci or "") + " " + str(comp or "")))
            for w in set(words(en) + words(ar)):
                self.vocab.setdefault(w, set()).add(i)
        self._near = {}

    def _near_words(self, tok):
        """Vocabulary words within the typo limit of tok (cached per token)."""
        hit = self._near.get(tok)
        if hit is not None:
            return hit
        lim = max_typos(len(tok))
        out = []
        for w in self.vocab:
            if abs(len(w) - len(tok)) <= lim and (w[0] == tok[0] or lim >= 2 or w[-1] == tok[-1]):
                d = edit_distance(tok, w, lim)
                if d <= lim:
                    out.append((w, d))
        if len(self._near) > 500:
            self._near.clear()
        self._near[tok] = out
        return out

    def search(self, query, limit=100):
        """Return row ids, best first: exact/prefix, then contains, then all words, then typo-tolerant."""
        qn = normalize(query).strip()
        toks = words(query)
        if not toks:
            return []
        qc = "".join(toks)
        scored = {}

        def put(i, tier, d=0):
            cur = scored.get(i)
            if cur is None or (tier, d) < cur:
                scored[i] = (tier, d)

        for i, nm in enumerate(self.names):
            c = self.compacts[i]
            if nm.startswith(qn) or c.startswith(qc):
                put(i, 0)
            elif qc in c:
                put(i, 1)
            elif qc in self.full[i]:
                put(i, 2)
        if len(toks) > 1:    # every word present as a substring, any order
            for i, c in enumerate(self.full):
                if i not in scored and all(t in c for t in toks):
                    put(i, 2)
        if len(scored) < limit:
            # typo tolerance: every query word must match a name word within the allowed distance
            cands = None
            dist = {}
            for t in toks:
                m = {}
                for w, d in self._near_words(t):
                    for i in self.vocab[w]:
                        if i not in m or d < m[i]:
                            m[i] = d
                # also a query word glued to or split from neighbours: handled by compact matching above
                if cands is None:
                    cands = set(m)
                else:
                    cands &= set(m)
                for i, d in m.items():
                    dist[i] = dist.get(i, 0) + d
                if not cands:
                    break
            if not cands and len(toks) > 1:
                # words run together or split differently ("lightvel" vs "light vel"): typo-compare the compact form
                lim = max_typos(len(qc))
                if lim:
                    for i, c in enumerate(self.compacts):
                        if abs(len(c) - len(qc)) > 20:
                            continue
                        head = c[:len(qc) + lim]
                        if edit_distance(qc, head, lim) <= lim:
                            put(i, 3, 1)
            for i in cands or ():
                if i not in scored:
                    put(i, 3, dist[i])
            if not scored and len(toks) == 1 and len(qc) > 3:
                lim = max_typos(len(qc))
                for i, c in enumerate(self.compacts):
                    head = c[:len(qc) + lim]
                    if edit_distance(qc, head, lim) <= lim:
                        put(i, 3, 1)
        order = sorted(scored, key=lambda i: (scored[i][0], scored[i][1], self.names[i]))
        return [self.ids[i] for i in order[:limit]]
