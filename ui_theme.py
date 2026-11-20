# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise v3 — UI theme module (stdlib only: Tkinter/ttk).

One place for the whole look: colours, fonts, card/banner helpers and
Treeview striping.  Business logic, database and forecasting are NOT
here — this file only changes how things look.

Windows fonts first (Segoe UI), with Tahoma / DejaVu Sans as fallbacks
so the same file also renders on Linux during smoke tests.
"""
import tkinter as tk
from tkinter import ttk

FONT_FAMILY = "Segoe UI"
FALLBACK_FAMILIES = ("Segoe UI", "Tahoma", "DejaVu Sans")
# v5.9: font-size scale (0=normal, 2=large, 4=extra large) added to every font().
FONT_DELTA = 0
FONT_SCALES = {"normal": 0, "large": 2, "xlarge": 4}
FONT_SCALE_LABELS = {"normal": "عادي", "large": "كبير", "xlarge": "كبير جداً"}
ACCENTS = {
    "teal":  {"label": "تركوازي (افتراضي)", "accent": "#0F766E", "hover": "#0D9488", "header": "#0F766E", "header2": "#115E59"},
    "blue":  {"label": "أزرق", "accent": "#1D4ED8", "hover": "#2563EB", "header": "#1E40AF", "header2": "#1E3A8A"},
    "green": {"label": "أخضر", "accent": "#15803D", "hover": "#16A34A", "header": "#166534", "header2": "#14532D"},
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


LIGHT = {
    "name": "light",
    "bg": "#F2F5F7",
    "card_bg": "#FFFFFF",
    "header_bg": "#0F766E",      # deep teal
    "header_bg2": "#115E59",
    "header_fg": "#FFFFFF",
    "text": "#1F2937",
    "muted": "#6B7280",
    "accent": "#0F766E",
    "accent_hover": "#0D9488",
    "success": "#15803D",
    "success_bg": "#DCFCE7",
    "warning": "#B45309",
    "warning_bg": "#FEF3C7",
    "danger": "#B91C1C",
    "danger_bg": "#FEE2E2",
    "info": "#1D4ED8",
    "info_bg": "#DBEAFE",
    "input_bg": "#FFFFFF",
    "border": "#D1D5DB",
    "row_alt": "#F3F4F6",
    "row_bg": "#FFFFFF",
    "selected_bg": "#CCFBF1",
}

DARK = {
    "name": "dark",
    "bg": "#111827",
    "card_bg": "#1F2937",
    "header_bg": "#0F766E",
    "header_bg2": "#115E59",
    "header_fg": "#FFFFFF",
    "text": "#F9FAFB",
    "muted": "#9CA3AF",
    "accent": "#14B8A6",
    "accent_hover": "#2DD4BF",
    "success": "#4ADE80",
    "success_bg": "#14532D",
    "warning": "#FBBF24",
    "warning_bg": "#451A03",
    "danger": "#F87171",
    "danger_bg": "#450A0A",
    "info": "#60A5FA",
    "info_bg": "#172554",
    "input_bg": "#374151",
    "border": "#4B5563",
    "row_alt": "#273244",
    "row_bg": "#1F2937",
    "selected_bg": "#134E4A",
}

PALETTES = {"light": LIGHT, "dark": DARK}


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
    """Theme persisted in the settings table; default is light."""
    try:
        row = db.conn.execute(
            "SELECT value FROM settings WHERE key='ui_theme'").fetchone()
        if row and row["value"] in PALETTES:
            return row["value"]
    except Exception:
        pass
    return "light"


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
    style.configure("Header.TLabel", font=font(18, bold=True),
                    foreground=p["text"])
    style.configure("Section.TLabel", font=font(13, bold=True),
                    foreground=p["accent"])
    style.configure("Muted.TLabel", font=font(10), foreground=p["muted"])
    style.configure("Total.TLabel", font=font(18, bold=True),
                    foreground=p["success"])
    style.configure("Huge.TLabel", font=font(28, bold=True),
                    foreground=p["success"])
    style.configure("CardTitle.TLabel", font=font(11, bold=True),
                    foreground=p["muted"], background=p["card_bg"])
    style.configure("CardValue.TLabel", font=font(24, bold=True),
                    foreground=p["text"], background=p["card_bg"])
    style.configure("CardSub.TLabel", font=font(10),
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
    style.configure("TButton", padding=(12, 9), font=font(11, bold=True))
    style.configure("Accent.TButton", background=p["accent"],
                    foreground="#FFFFFF", font=font(12, bold=True))
    style.map("Accent.TButton",
              background=[("active", p["accent_hover"]), ("pressed", p["header_bg2"])])
    style.configure("Success.TButton", background=p["success"],
                    foreground="#FFFFFF", font=font(12, bold=True))
    style.configure("Danger.TButton", background=p["danger"],
                    foreground="#FFFFFF", font=font(11, bold=True))
    style.configure("Big.TButton", padding=(16, 12), font=font(14, bold=True))
    style.configure("TEntry", font=font(12), fieldbackground=p["input_bg"],
                    foreground=p["text"])
    style.configure("TCombobox", font=font(11),
                    fieldbackground=p["input_bg"], foreground=p["text"])
    style.configure("TRadiobutton", background=p["bg"],
                    foreground=p["text"], font=font(11))
    style.configure("TNotebook", background=p["bg"], tabposition="n")
    style.configure("TNotebook.Tab", padding=(14, 9), font=font(11, bold=True))
    style.map("TNotebook.Tab",
              background=[("selected", p["card_bg"]), ("!selected", p["bg"])],
              foreground=[("selected", p["accent"]), ("!selected", p["text"])])
    style.configure("Treeview", font=font(11), rowheight=34,
                    background=p["row_bg"], fieldbackground=p["row_bg"],
                    foreground=p["text"], bordercolor=p["border"])
    style.configure("Treeview.Heading", font=font(11, bold=True),
                    background=p["header_bg"], foreground="#FFFFFF",
                    relief="flat")
    style.map("Treeview", background=[("selected", p["selected_bg"])],
              foreground=[("selected", p["text"])])
    style.configure("TSeparator", background=p["border"])
    style.configure("TLabelframe", background=p["bg"], foreground=p["text"])
    style.configure("TLabelframe.Label", font=font(12, bold=True),
                    foreground=p["accent"], background=p["bg"])
    return p


def style_treeview(tree, theme_name="light"):
    """Striping + status tags for one Treeview. Call after each refresh."""
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
    except Exception:
        pass


def stripe_rows(tree, theme_name="light"):
    """Re-apply even/odd tags, preserving any status tag already set."""
    style_treeview(tree, theme_name)
    try:
        for idx, iid in enumerate(tree.get_children()):
            tags = [t for t in tree.item(iid, "tags")
                    if t in ("crit", "high", "ok", "warn",
                             "danger_text", "warn_text")]
            if not tags:
                tags = ["even" if idx % 2 == 0 else "odd"]
            tree.item(iid, tags=tuple(tags))
    except Exception:
        pass


def status_tag_for_urgency(urgency):
    return {"حرجة": "crit", "عالية": "high", "عادية": "ok",
            "مستقرة": "ok"}.get(str(urgency), "odd")


# ---------------------------------------------------------------- widgets
def make_card(parent, title, value, subtitle="", accent="#0F766E",
              theme_name="light"):
    """A summary card (tk.Frame so it keeps its own background).

    Returns (frame, value_label, subtitle_label) so the caller can
    update the numbers later without rebuilding the card.
    """
    p = palette(theme_name)
    frame = tk.Frame(parent, bg=p["card_bg"], highlightbackground=p["border"],
                     highlightthickness=1, padx=14, pady=10)
    accent_bar = tk.Frame(frame, bg=accent, width=5)
    accent_bar.pack(side="left", fill="y", padx=(0, 10))
    body = tk.Frame(frame, bg=p["card_bg"])
    body.pack(side="left", fill="both", expand=True)
    ttk.Label(body, text=title, style="CardTitle.TLabel").pack(anchor="w")
    val = ttk.Label(body, text=value, style="CardValue.TLabel")
    val.pack(anchor="w", pady=(2, 0))
    sub = ttk.Label(body, text=subtitle, style="CardSub.TLabel")
    sub.pack(anchor="w")
    frame._card_body = body
    frame._card_value = val
    frame._card_sub = sub
    frame._card_accent = accent_bar
    return frame, val, sub


def recolor_card(frame, theme_name="light"):
    p = palette(theme_name)
    try:
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
