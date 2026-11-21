# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise v6.15 — UI theme module (stdlib only: Tkinter/ttk).

One place for the whole look: colours, fonts, card/banner helpers and
Treeview striping.  Business logic, database and forecasting are NOT
here — this file only changes how things look.

v6.15 «futuristic» refresh: a deeper night-drive dark palette (the new
default), a cleaner modern light palette, cyan/violet accent family,
flatter buttons, roomier tabs and table rows, themed scrollbars, and
themed tk Text/Listbox defaults so every surface matches the palette.

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


LIGHT = {
    "name": "light",
    "bg": "#EEF1F8",
    "card_bg": "#FFFFFF",
    "header_bg": "#0B3B39",
    "header_bg2": "#082B2A",
    "header_fg": "#FFFFFF",
    "text": "#0F172A",
    "muted": "#64748B",
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
    "border": "#E2E8F0",
    "row_alt": "#F6F8FC",
    "row_bg": "#FFFFFF",
    "selected_bg": "#CFFAFE",
}

DARK = {
    "name": "dark",
    "bg": "#0A0E1A",
    "card_bg": "#121A2E",
    "header_bg": "#0B3B39",
    "header_bg2": "#082B2A",
    "header_fg": "#FFFFFF",
    "text": "#E5ECF5",
    "muted": "#8CA0BE",
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
    "input_bg": "#1B2740",
    "border": "#26334F",
    "row_alt": "#16213B",
    "row_bg": "#121A2E",
    "selected_bg": "#15324B",
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
    style.configure("TButton", padding=(14, 10), font=font(11, bold=True),
                    background=p["card_bg"], foreground=p["text"],
                    bordercolor=p["border"], lightcolor=p["card_bg"],
                    darkcolor=p["card_bg"], focusthickness=0)
    style.map("TButton",
              background=[("active", p["row_alt"]), ("pressed", p["border"])],
              foreground=[("disabled", p["muted"])])
    style.configure("Accent.TButton", background=p["accent"],
                    foreground="#FFFFFF", font=font(12, bold=True),
                    bordercolor=p["accent"], lightcolor=p["accent"],
                    darkcolor=p["accent"], padding=(16, 10))
    style.map("Accent.TButton",
              background=[("active", p["accent_hover"]), ("pressed", p["header_bg2"])])
    style.configure("Success.TButton", background=p["success"],
                    foreground="#FFFFFF", font=font(12, bold=True))
    style.configure("Danger.TButton", background=p["danger"],
                    foreground="#FFFFFF", font=font(11, bold=True))
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
    style.configure("Treeview", font=font(11), rowheight=36,
                    background=p["row_bg"], fieldbackground=p["row_bg"],
                    foreground=p["text"], bordercolor=p["border"],
                    borderwidth=0)
    style.configure("Treeview.Heading", font=font(11, bold=True),
                    background=p["header_bg"], foreground="#FFFFFF",
                    relief="flat", padding=(8, 7))
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
                     highlightthickness=1, padx=16, pady=12)
    accent_bar = tk.Frame(frame, bg=accent, width=4)
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
