# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise v6.20 — UI theme module (stdlib only: Tkinter/ttk).

One place for the whole look: colours, fonts, card/banner helpers and
Treeview striping.  Business logic, database and forecasting are NOT
here — this file only changes how things look.

v6.15 «futuristic» refresh: a deeper night-drive dark palette (the new
default), a cleaner modern light palette, cyan/violet accent family,
flatter buttons, roomier tabs and table rows, themed scrollbars, and
themed tk Text/Listbox defaults so every surface matches the palette.

v6.18 polish: a single button hierarchy (primary/success/danger/warning/
secondary) with hover and pressed states on every variant, one status
colour language (success/warning/danger/info/muted) with a pill label
helper and Treeview status tags, and helpers so no screen hardcodes its
own hex colours anymore.

Windows fonts first (Segoe UI Variable on Windows 11, then Segoe UI),
with Tahoma / DejaVu Sans as fallbacks so the same file also renders on
Linux during smoke tests.
"""
import tkinter as tk
from tkinter import ttk

FONT_FAMILY = "Segoe UI"
# v6.20: Windows 11 ships "Segoe UI Variable" — a modernised cut of the
# same face.  resolve_font_family() picks the best installed option at
# startup and keeps the module-level default as the safe fallback.
FONT_FAMILIES_PREFERRED = ("Segoe UI Variable Text", "Segoe UI",
                           "Tahoma", "DejaVu Sans")
_resolved_family = None

# v6.20: one Fluent-style type scale — every label size comes from here
# so the hierarchy (caption/body/subtitle/title/display) stays coherent.
TYPE_SCALE = {
    "caption": 9,
    "body": 11,
    "subtitle": 13,
    "title": 18,
    "title_large": 22,
    "display": 28,
}


def resolve_font_family(root=None):
    """Pick the best installed family from FONT_FAMILIES_PREFERRED.

    Safe everywhere: any failure keeps the plain Segoe UI default.
    """
    global FONT_FAMILY, _resolved_family
    if _resolved_family:
        return _resolved_family
    fam = FONT_FAMILY
    try:
        from tkinter import font as tkfont
        available = set(tkfont.families(root))
        for cand in FONT_FAMILIES_PREFERRED:
            if cand in available:
                fam = cand
                break
    except Exception:
        fam = FONT_FAMILY
    FONT_FAMILY = fam
    _resolved_family = fam
    return fam
# v5.9: font-size scale (0=normal, 2=large, 4=extra large) added to every font().
FONT_DELTA = 0
FONT_SCALES = {"normal": 0, "large": 2, "xlarge": 4}
FONT_SCALE_LABELS = {"normal": "عادي", "large": "كبير", "xlarge": "كبير جداً"}
ACCENTS = {
    "teal":   {"label": "سماوي (افتراضي)", "accent": "#0D9488", "hover": "#14B8A6", "header": "#0B3B39", "header2": "#082B2A"},
    "blue":   {"label": "أزرق كهربائي", "accent": "#3B82F6", "hover": "#60A5FA", "header": "#1E3A8A", "header2": "#172554"},
    "green":  {"label": "زمردي", "accent": "#10B981", "hover": "#34D399", "header": "#064E3B", "header2": "#022C22"},
    "violet": {"label": "بنفسجي", "accent": "#8B5CF6", "hover": "#A78BFA", "header": "#4C1D95", "header2": "#2E1065"},
}
def set_font_scale(delta):
    global FONT_DELTA
    try: FONT_DELTA = int(delta)
    except Exception: FONT_DELTA = 0
def font_scale_for(name):
    return FONT_SCALES.get(str(name or "normal"), 0)


def font(size=11, bold=False, family=None):
    """Return a font tuple.  ``family`` falls back gracefully on Linux."""
    return (family or FONT_FAMILY, size + FONT_DELTA, "bold" if bold else "normal")


# v6.20 palettes move to the Windows 11 Fluent neutrals: a light mica
# grey (#F3F3F3) and the Win11 dark charcoal (#202020) with layered
# card surfaces and subtle 1px borders.  Status colours are unchanged —
# the v6.18 colour language stays exactly as users learned it.
LIGHT = {
    "name": "light",
    "bg": "#F3F3F3",
    "card_bg": "#FFFFFF",
    "header_bg": "#0B3B39",
    "header_bg2": "#082B2A",
    "header_fg": "#FFFFFF",
    "text": "#1B1B1B",
    "muted": "#616161",
    "accent": "#0D9488",
    "accent_hover": "#14B8A6",
    "success": "#059669",
    "success_bg": "#D1FAE5",
    "warning": "#D97706",
    "warning_bg": "#FEF3C7",
    "danger": "#DC2626",
    "danger_bg": "#FEE2E2",
    "info": "#2563EB",
    "info_bg": "#DBEAFE",
    "input_bg": "#FFFFFF",
    "border": "#E0E0E0",
    "row_alt": "#F7F7F7",
    "row_bg": "#FFFFFF",
    "selected_bg": "#DCEAF7",
}

DARK = {
    "name": "dark",
    "bg": "#202020",
    "card_bg": "#2C2C2C",
    "header_bg": "#0B3B39",
    "header_bg2": "#082B2A",
    "header_fg": "#FFFFFF",
    "text": "#F2F2F2",
    "muted": "#A9A9A9",
    "accent": "#14B8A6",
    "accent_hover": "#2DD4BF",
    "success": "#34D399",
    "success_bg": "#052E22",
    "warning": "#FBBF24",
    "warning_bg": "#3B2A05",
    "danger": "#F87171",
    "danger_bg": "#3F0D0D",
    "info": "#60A5FA",
    "info_bg": "#0B1E3D",
    "input_bg": "#3A3A3A",
    "border": "#454545",
    "row_alt": "#323232",
    "row_bg": "#2C2C2C",
    "selected_bg": "#3B4C5E",
}

PALETTES = {"light": LIGHT, "dark": DARK}


def _shade(hex_color, factor):
    """Lighten (factor > 1) or darken (0 < factor < 1) a #RRGGBB colour."""
    try:
        h = str(hex_color).lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        if factor >= 1:
            f = min(factor - 1.0, 1.0)
            r = int(r + (255 - r) * f)
            g = int(g + (255 - g) * f)
            b = int(b + (255 - b) * f)
        else:
            r = int(r * factor)
            g = int(g * factor)
            b = int(b * factor)
        return "#%02X%02X%02X" % (max(0, min(255, r)),
                                  max(0, min(255, g)),
                                  max(0, min(255, b)))
    except Exception:
        return hex_color


# ---------------------------------------------------------------- status language
# v6.18: one coherent colour language for every state the app shows —
# success (paid/synced/done), warning (due soon/partial), danger (failed/
# void/critical), info (running/pending), muted (held/disabled).
STATUS_KINDS = ("success", "warning", "danger", "info", "muted")

# Arabic/domain status word → kind.  status_kind_for() matches the first
# word found inside any status text, so every screen paints the same
# state in the same colour.
STATUS_WORDS = {
    # invoices / payments
    "مدفوعة": "success", "مدفوع": "success", "نقدي": "success",
    "آجلة": "warning", "آجل": "warning", "جزئي": "warning",
    "متأخرة": "danger", "مُرجعة": "danger", "مرتجع": "danger",
    "ملغاة": "danger", "ملغية": "danger",
    # sync / background tasks  (negative phrases first — they contain
    # the positive words as substrings, and the first match wins)
    "غير مفعّلة": "warning", "غير متاحة": "danger",
    "متزامنة": "success", "ناجحة": "success",
    "يعمل": "success", "مفعّلة": "success",
    "فشلت": "danger", "فشل": "danger", "خطأ": "danger",
    "متوقف": "danger",
    "قيد التنفيذ": "info", "معلّقة": "info", "جارٍ": "info",
    # stock / forecast urgency
    "حرجة": "danger", "حرج": "danger", "ناقصة": "warning",
    "عالية": "warning", "قريبة": "warning", "مستقرة": "success",
    # held / disabled lines
    "محذوف مؤقتاً": "muted", "معلَّق": "muted",
}


def status_colors(kind, theme_name="light", accent="teal"):
    """(foreground, background) pair for a status kind."""
    p = palette(theme_name, accent)
    table = {
        "success": (p["success"], p["success_bg"]),
        "warning": (p["warning"], p["warning_bg"]),
        "danger": (p["danger"], p["danger_bg"]),
        "info": (p["info"], p["info_bg"]),
        "muted": (p["muted"], p["row_alt"]),
    }
    return table.get(str(kind or "info"), table["info"])


def status_kind_for(text):
    """Best status kind for an Arabic status text (info when unknown)."""
    t = str(text or "")
    for word, kind in STATUS_WORDS.items():
        if word in t:
            return kind
    return "info"


# ---------------------------------------------------------------- buttons
# v6.18 hierarchy, one meaning per colour everywhere:
#   primary/Accent  → الخطوة الرئيسية (دخول، اعتماد، تشغيل)
#   success         → تأكيد وحفظ وإتمام (حفظ، إتمام البيع)
#   danger          → تدميري (حذف، إلغاء فاتورة)
#   warning         → حذر (مسح، إيقاف)
#   secondary       → كل الأزرار المحايدة
BUTTON_KINDS = {
    "primary": "Accent.TButton", "accent": "Accent.TButton",
    "success": "Success.TButton",
    "danger": "Danger.TButton",
    "warning": "Warning.TButton",
    "info": "Info.TButton",
    "secondary": "TButton", "neutral": "TButton",
}


def button_style_for(kind):
    """ttk style name for a semantic button kind."""
    return BUTTON_KINDS.get(str(kind or "secondary"), "TButton")


def styled_button(parent, text, command, kind="secondary"):
    """A ttk.Button in the v6.18 hierarchy. kind: primary/success/danger/
    warning/info/secondary."""
    return ttk.Button(parent, text=text, command=command,
                      style=button_style_for(kind))


def palette(theme_name, accent="teal"):
    base = dict(PALETTES.get(theme_name, LIGHT))
    a = ACCENTS.get(str(accent or "teal"), ACCENTS["teal"])
    base["accent"] = a["accent"]; base["accent_hover"] = a["hover"]
    base["header_bg"] = a["header"]; base["header_bg2"] = a["header2"]
    return base
def get_ui_pref(db, key, default=""):
    try: return db.get_setting(key, default)
    except Exception: return default
def set_ui_pref(db, key, value):
    try: db.set_setting(key, str(value))
    except Exception: pass


# ---------------------------------------------------------------- settings
def get_theme_name(db):
    """Theme persisted in the settings table; v6.15 default is dark."""
    try:
        row = db.conn.execute(
            "SELECT value FROM settings WHERE key='ui_theme'").fetchone()
        if row and row["value"] in PALETTES:
            return row["value"]
    except Exception:
        pass
    return "dark"


def set_theme_name(db, theme_name):
    try:
        db.conn.execute(
            "INSERT INTO settings (key, value) VALUES ('ui_theme', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (theme_name,))
        db.conn.commit()
    except Exception:
        # Older SQLite without UPSERT: fall back to update/insert.
        try:
            cur = db.conn.execute(
                "SELECT 1 FROM settings WHERE key='ui_theme'")
            if cur.fetchone():
                db.conn.execute(
                    "UPDATE settings SET value=? WHERE key='ui_theme'",
                    (theme_name,))
            else:
                db.conn.execute(
                    "INSERT INTO settings VALUES ('ui_theme', ?)",
                    (theme_name,))
            db.conn.commit()
        except Exception:
            pass


# ---------------------------------------------------------------- styling
def apply_theme(root, style, theme_name="light", accent="teal", font_scale=0):
    """Configure every ttk style for the palette. Safe to call twice."""
    set_font_scale(font_scale)
    resolve_font_family(root)
    p = palette(theme_name, accent)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    try:
        root.configure(bg=p["bg"])
    except Exception:
        pass
    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"],
                    font=font(11))
    style.configure("Header.TLabel", font=font(TYPE_SCALE["title"], bold=True),
                    foreground=p["text"])
    style.configure("Section.TLabel", font=font(TYPE_SCALE["subtitle"], bold=True),
                    foreground=p["accent"])
    style.configure("Muted.TLabel", font=font(TYPE_SCALE["caption"]), foreground=p["muted"])
    style.configure("Total.TLabel", font=font(TYPE_SCALE["title"], bold=True),
                    foreground=p["success"])
    style.configure("Huge.TLabel", font=font(TYPE_SCALE["display"], bold=True),
                    foreground=p["success"])
    style.configure("CardTitle.TLabel", font=font(TYPE_SCALE["body"], bold=True),
                    foreground=p["muted"], background=p["card_bg"])
    style.configure("CardValue.TLabel", font=font(24, bold=True),
                    foreground=p["text"], background=p["card_bg"])
    style.configure("CardSub.TLabel", font=font(TYPE_SCALE["caption"]),
                    foreground=p["muted"], background=p["card_bg"])
    style.configure("Card.TFrame", background=p["card_bg"])
    style.configure("Card.TLabel", background=p["card_bg"],
                    foreground=p["text"], font=font(11))
    style.configure("CardMuted.TLabel", background=p["card_bg"],
                    foreground=p["muted"], font=font(10))
    style.configure("CardTotal.TLabel", background=p["card_bg"],
                    foreground=p["success"], font=font(18, bold=True))
    style.configure("CardHuge.TLabel", background=p["card_bg"],
                    foreground=p["success"], font=font(28, bold=True))
    style.configure("CardChange.TLabel", background=p["card_bg"],
                    foreground=p["info"], font=font(12, bold=True))
    style.configure("Card.TRadiobutton", background=p["card_bg"],
                    foreground=p["text"], font=font(11))
    # v6.18 button hierarchy: one meaning per colour, and every variant
    # has visible hover (lighter) and pressed (darker) states.
    style.configure("TButton", padding=(14, 9), font=font(11, bold=True),
                    background=p["card_bg"], foreground=p["text"],
                    bordercolor=p["border"], lightcolor=p["card_bg"],
                    darkcolor=p["card_bg"], focusthickness=0)
    style.map("TButton",
              background=[("pressed", p["border"]), ("active", p["row_alt"])],
              foreground=[("disabled", p["muted"])],
              bordercolor=[("focus", p["accent"]), ("active", p["accent"])])

    def _solid_button(name, base, size=11, pad=(16, 10)):
        """One solid-colour button style with hover/pressed shades."""
        style.configure(name, background=base, foreground="#FFFFFF",
                        font=font(size, bold=True), padding=pad,
                        bordercolor=base, lightcolor=base, darkcolor=base,
                        focusthickness=0)
        style.map(name,
                  background=[("pressed", _shade(base, 0.72)),
                              ("active", _shade(base, 1.18))],
                  foreground=[("disabled", p["muted"])])

    _solid_button("Accent.TButton", p["accent"], size=12)
    _solid_button("Success.TButton", p["success"], size=12)
    _solid_button("Danger.TButton", p["danger"])
    _solid_button("Warning.TButton", p["warning"])
    _solid_button("Info.TButton", p["info"])
    style.configure("Big.TButton", padding=(18, 13), font=font(14, bold=True))
    style.configure("TEntry", font=font(12), fieldbackground=p["input_bg"],
                    foreground=p["text"], insertcolor=p["text"],
                    bordercolor=p["border"], lightcolor=p["border"],
                    darkcolor=p["border"], padding=(6, 5))
    style.configure("TCombobox", font=font(11), padding=(6, 5),
                    fieldbackground=p["input_bg"], foreground=p["text"],
                    background=p["card_bg"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"],
                    insertcolor=p["text"])
    style.map("TCombobox",
              fieldbackground=[("readonly", p["input_bg"])],
              foreground=[("readonly", p["text"])])
    style.configure("TRadiobutton", background=p["bg"],
                    foreground=p["text"], font=font(11))
    style.configure("TCheckbutton", background=p["bg"],
                    foreground=p["text"], font=font(11))
    style.map("TRadiobutton", background=[("active", p["bg"])])
    style.map("TCheckbutton", background=[("active", p["bg"])])
    style.configure("TNotebook", background=p["bg"], tabposition="n",
                    borderwidth=0)
    style.configure("TNotebook.Tab", padding=(18, 10), font=font(11, bold=True))
    style.map("TNotebook.Tab",
              background=[("selected", p["card_bg"]), ("!selected", p["bg"])],
              foreground=[("selected", p["accent"]), ("!selected", p["text"])],
              expand=[("selected", (1, 1, 1, 0))])
    # v6.20: Fluent tables — a quiet header row (muted text on the
    # surface colour with a hairline border) instead of a heavy
    # coloured bar; the data is the loud part, not the chrome.
    style.configure("Treeview", font=font(11), rowheight=36,
                    background=p["row_bg"], fieldbackground=p["row_bg"],
                    foreground=p["text"], bordercolor=p["border"],
                    borderwidth=0)
    style.configure("Treeview.Heading", font=font(10, bold=True),
                    background=p["row_alt"], foreground=p["muted"],
                    relief="flat", padding=(8, 7),
                    bordercolor=p["border"])
    style.map("Treeview", background=[("selected", p["selected_bg"])],
              foreground=[("selected", p["text"])])
    style.configure("TSeparator", background=p["border"])
    style.configure("TLabelframe", background=p["bg"], foreground=p["text"])
    style.configure("TLabelframe.Label", font=font(12, bold=True),
                    foreground=p["accent"], background=p["bg"])
    style.configure("Vertical.TScrollbar", background=p["card_bg"],
                    troughcolor=p["bg"], bordercolor=p["bg"],
                    lightcolor=p["card_bg"], darkcolor=p["card_bg"],
                    arrowcolor=p["muted"], borderwidth=0, arrowsize=13)
    style.map("Vertical.TScrollbar",
              background=[("active", p["border"])])
    style.configure("Horizontal.TScrollbar", background=p["card_bg"],
                    troughcolor=p["bg"], bordercolor=p["bg"],
                    lightcolor=p["card_bg"], darkcolor=p["card_bg"],
                    arrowcolor=p["muted"], borderwidth=0, arrowsize=13)
    style.map("Horizontal.TScrollbar",
              background=[("active", p["border"])])
    # v6.15: plain-tk widgets (Text / Listbox / Canvas) follow the palette
    # too — option_add covers every current and future instance.
    try:
        root.option_add("*Text.Background", p["card_bg"])
        root.option_add("*Text.Foreground", p["text"])
        root.option_add("*Text.InsertBackground", p["text"])
        root.option_add("*Text.SelectBackground", p["selected_bg"])
        root.option_add("*Text.SelectForeground", p["text"])
        root.option_add("*Text.highlightColor", p["accent"])
        root.option_add("*Listbox.Background", p["card_bg"])
        root.option_add("*Listbox.Foreground", p["text"])
        root.option_add("*Listbox.SelectBackground", p["selected_bg"])
        root.option_add("*Listbox.SelectForeground", p["text"])
        root.option_add("*TCombobox*Listbox.Background", p["input_bg"])
        root.option_add("*TCombobox*Listbox.Foreground", p["text"])
        root.option_add("*TCombobox*Listbox.SelectBackground", p["selected_bg"])
    except Exception:
        pass
    return p


def style_treeview(tree, theme_name="light"):
    """Striping + status tags for one Treeview. Call after each refresh.

    v6.18 status tags (same language as status_colors): paid/synced/ok
    are success, due/warn/high are warning, failed/voided/crit are
    danger, held is muted grey.
    """
    p = palette(theme_name)
    try:
        tree.tag_configure("even", background=p["row_bg"],
                           foreground=p["text"])
        tree.tag_configure("odd", background=p["row_alt"],
                           foreground=p["text"])
        tree.tag_configure("crit", background=p["danger_bg"],
                           foreground=p["danger"], font=font(11, bold=True))
        tree.tag_configure("high", background=p["warning_bg"],
                           foreground=p["warning"], font=font(11, bold=True))
        tree.tag_configure("ok", background=p["success_bg"],
                           foreground=p["success"])
        tree.tag_configure("warn", background=p["warning_bg"],
                           foreground=p["warning"])
        tree.tag_configure("danger_text", foreground=p["danger"],
                           font=font(11, bold=True))
        tree.tag_configure("warn_text", foreground=p["warning"],
                           font=font(11, bold=True))
        # v6.18: held (محذوف مؤقتاً) and named status rows.
        tree.tag_configure("held", foreground=p["muted"])
        tree.tag_configure("paid", background=p["success_bg"],
                           foreground=p["success"])
        tree.tag_configure("due", background=p["warning_bg"],
                           foreground=p["warning"])
        tree.tag_configure("failed", background=p["danger_bg"],
                           foreground=p["danger"], font=font(11, bold=True))
        tree.tag_configure("synced", background=p["info_bg"],
                           foreground=p["info"])
    except Exception:
        pass


# Tags stripe_rows must never overwrite with even/odd striping.
STATUS_TAGS = ("crit", "high", "ok", "warn", "danger_text", "warn_text",
               "held", "paid", "due", "failed", "synced")


def stripe_rows(tree, theme_name="light"):
    """Re-apply even/odd tags, preserving any status tag already set."""
    style_treeview(tree, theme_name)
    try:
        for idx, iid in enumerate(tree.get_children()):
            tags = [t for t in tree.item(iid, "tags")
                    if t in STATUS_TAGS]
            if not tags:
                tags = ["even" if idx % 2 == 0 else "odd"]
            tree.item(iid, tags=tuple(tags))
    except Exception:
        pass


def status_tag_for_urgency(urgency):
    return {"حرجة": "crit", "عالية": "high", "عادية": "ok",
            "مستقرة": "ok"}.get(str(urgency), "odd")


# ---------------------------------------------------------------- widgets
# v6.20: Fluent cards have rounded corners and a hairline border.
# Tkinter has no native rounded frames, so the card is a Canvas that
# draws a rounded rectangle (plus a small accent pill) and holds the
# labels in an inner frame — and any failure falls back to the plain
# v6.15 frame card, so a theme glitch can never lose dashboard content.
CARD_RADIUS = 10


def _round_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Polygon approximating a rounded rectangle on a canvas."""
    r = max(0, min(int(r), (x2 - x1) // 2, (y2 - y1) // 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r,
           x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
           x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def make_card(parent, title, value, subtitle="", accent="#0F766E",
              theme_name="light"):
    """A summary card.  Returns (frame, value_label, subtitle_label) so
the caller can update the numbers later without rebuilding the card."""
    p = palette(theme_name)
    try:
        return _make_rounded_card(parent, title, value, subtitle,
                                  accent, theme_name, p)
    except Exception:
        return _make_flat_card(parent, title, value, subtitle, accent, p)


def _card_labels(body, title, value, subtitle):
    """The three labels every card variant shows."""
    ttk.Label(body, text=title, style="CardTitle.TLabel").pack(anchor="w")
    val = ttk.Label(body, text=value, style="CardValue.TLabel")
    val.pack(anchor="w", pady=(2, 0))
    sub = ttk.Label(body, text=subtitle, style="CardSub.TLabel")
    sub.pack(anchor="w")
    return val, sub


def _make_rounded_card(parent, title, value, subtitle, accent,
                       theme_name, p):
    """Fluent rounded card: rounded rect + accent pill on a canvas."""
    cv = tk.Canvas(parent, bg=p["bg"], highlightthickness=0, bd=0)
    cv._card_theme = theme_name
    inner = tk.Frame(cv, bg=p["card_bg"], padx=12, pady=10)
    win_id = cv.create_window(0, 0, window=inner, anchor="nw")
    val, sub = _card_labels(inner, title, value, subtitle)

    def _redraw(_event=None):
        try:
            pal = palette(getattr(cv, "_card_theme", "light"))
            w = max(cv.winfo_width(), 40)
            h = max(cv.winfo_height(), 24)
            cv.delete("cardshape")
            _round_rect(cv, 1, 1, w - 2, h - 2, CARD_RADIUS,
                        fill=pal["card_bg"], outline=pal["border"],
                        width=1, tags="cardshape")
            cy = h // 2
            _round_rect(cv, 7, cy - 9, 11, cy + 9, 2,
                        fill=accent, outline="", tags="cardshape")
            cv.coords(win_id, 19, 4)
            cv.itemconfigure(win_id, width=max(w - 25, 1),
                             height=max(h - 8, 1))
        except Exception:
            pass

    cv.bind("<Configure>", _redraw)
    # A canvas does not count window items in its requested size, so
    # without this the card would collapse to a strip; ask for the
    # labels' natural size (the row still stretches it with expand).
    try:
        inner.update_idletasks()
        cv.configure(width=max(inner.winfo_reqwidth() + 25, 160),
                     height=max(inner.winfo_reqheight() + 8, 70))
    except Exception:
        cv.configure(width=200, height=90)
    cv._card_body = inner
    cv._card_value = val
    cv._card_sub = sub
    return cv, val, sub


def _make_flat_card(parent, title, value, subtitle, accent, p):
    """The pre-v6.20 plain frame card — kept as the safe fallback."""
    frame = tk.Frame(parent, bg=p["card_bg"], highlightbackground=p["border"],
                     highlightthickness=1, padx=16, pady=12)
    accent_bar = tk.Frame(frame, bg=accent, width=4)
    accent_bar.pack(side="left", fill="y", padx=(0, 10))
    body = tk.Frame(frame, bg=p["card_bg"])
    body.pack(side="left", fill="both", expand=True)
    val, sub = _card_labels(body, title, value, subtitle)
    frame._card_body = body
    frame._card_value = val
    frame._card_sub = sub
    frame._card_accent = accent_bar
    return frame, val, sub


def recolor_card(frame, theme_name="light"):
    p = palette(theme_name)
    try:
        if isinstance(frame, tk.Canvas):
            # Rounded card: the canvas keeps the window background so the
            # rounded corners blend in; the shape redraw picks up the
            # new palette through _card_theme.
            frame._card_theme = theme_name
            frame.configure(bg=p["bg"])
            frame._card_body.configure(bg=p["card_bg"])
            frame.event_generate("<Configure>")
        else:
            frame.configure(bg=p["card_bg"], highlightbackground=p["border"])
            frame._card_body.configure(bg=p["card_bg"])
        frame._card_value.configure(background=p["card_bg"])
        frame._card_sub.configure(background=p["card_bg"])
    except Exception:
        pass


def make_banner(parent, text="", kind="info", theme_name="light"):
    """A full-width coloured banner label. kind: info/success/warning/danger."""
    p = palette(theme_name)
    colours = {"info": (p["info_bg"], p["info"]),
               "success": (p["success_bg"], p["success"]),
               "warning": (p["warning_bg"], p["warning"]),
               "danger": (p["danger_bg"], p["danger"])}
    bg, fg = colours.get(kind, colours["info"])
    lbl = tk.Label(parent, text=text, bg=bg, fg=fg, font=font(11, bold=True),
                   anchor="w", padx=10, pady=6, wraplength=1100,
                   justify="left")
    return lbl


def set_banner(lbl, text, kind="info", theme_name="light"):
    p = palette(theme_name)
    colours = {"info": (p["info_bg"], p["info"]),
               "success": (p["success_bg"], p["success"]),
               "warning": (p["warning_bg"], p["warning"]),
               "danger": (p["danger_bg"], p["danger"])}
    bg, fg = colours.get(kind, colours["info"])
    try:
        lbl.configure(text=text, bg=bg, fg=fg)
    except Exception:
        pass


def section_title(parent, text, theme_name="light"):
    lbl = ttk.Label(parent, text=text, style="Section.TLabel")
    lbl.pack(anchor="w", padx=10, pady=(10, 2))
    return lbl


def big_button(parent, text, command, style_name="Accent.TButton"):
    return ttk.Button(parent, text=text, command=command,
                      style=style_name)


# ---------------------------------------------------------------- status pill
def status_label(parent, text="", kind="info", theme_name="light"):
    """A small pill label in the v6.18 status colour language."""
    fg, bg = status_colors(kind, theme_name)
    return tk.Label(parent, text=text, bg=bg, fg=fg,
                    font=font(10, bold=True), padx=10, pady=3,
                    anchor="center", justify="center")


def set_status(lbl, text, kind=None, theme_name="light"):
    """Update a pill/status label; kind auto-detected from the text."""
    if kind is None:
        kind = status_kind_for(text)
    fg, bg = status_colors(kind, theme_name)
    try:
        lbl.configure(text=text, bg=bg, fg=fg)
    except Exception:
        pass


# ---------------------------------------------------------------- windows
# v6.20: Windows-11 window behaviour — screen-aware default size, a
# sensible minimum, and remembered geometry (size, position and the
# maximized state) so the app reopens exactly how the user left it.
import re as _re

_GEOMETRY_RE = _re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")


def center_window(win, w, h):
    """Centre a window on the screen at the given size (safe no-op)."""
    try:
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
    except Exception:
        pass


def _geometry_ok(geom, sw, sh):
    """A remembered geometry is used only when it still fits the screen
    (a monitor could have been unplugged since it was saved)."""
    m = _GEOMETRY_RE.match(str(geom or ""))
    if not m:
        return False
    w, h, x, y = (int(v) for v in m.groups())
    if w < 700 or h < 450 or w > sw + 400 or h > sh + 300:
        return False
    if x < -100 or y < -100 or x > sw - 60 or y > sh - 60:
        return False
    return True


def setup_main_window(root, db):
    """Size/place the main window and remember its geometry on close.

    First run keeps the old behaviour users know (starts maximized);
    later runs restore the saved size/position and maximized state.
    Everything is wrapped so a bad saved value can never block startup.
    """
    saved = get_ui_pref(db, "ui_geometry", "")
    maximized = get_ui_pref(db, "ui_maximized", "") == "1"
    try:
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
    except Exception:
        sw, sh = 1280, 800
    # v6.21: the minimum must fit the real screen — a 1024x600 minimum
    # is wrong on a 1366x768 laptop once the taskbar takes its share,
    # so cap it below the actual screen size.
    try:
        root.minsize(min(1024, max(sw - 40, 640)),
                     min(600, max(sh - 120, 480)))
    except Exception:
        pass
    placed = False
    if _geometry_ok(saved, sw, sh):
        try:
            root.geometry(saved)
            placed = True
        except Exception:
            placed = False
    if not placed:
        w = min(int(sw * 0.85), 1440)
        h = min(int(sh * 0.85), 900)
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        try:
            root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        except Exception:
            pass
    if maximized or not saved:
        try:
            root.state("zoomed")
        except Exception:
            pass

    def _save_and_close():
        try:
            zoomed = root.state() == "zoomed"
            set_ui_pref(db, "ui_maximized", "1" if zoomed else "0")
            if not zoomed:
                # Only the windowed geometry is worth remembering —
                # a maximized window's geometry is the whole screen.
                set_ui_pref(db, "ui_geometry", root.winfo_geometry())
        except Exception:
            pass
        root.destroy()

    try:
        root.protocol("WM_DELETE_WINDOW", _save_and_close)
    except Exception:
        pass
