# -*- coding: utf-8 -*-
"""
Pharmacy Enterprise v6.18 — themed message dialogs (stdlib Tkinter only).

A drop-in replacement for tkinter.messagebox: the same function names
and signatures (showinfo / showwarning / showerror / askyesno), but the
dialogs are small themed windows in the app's palette — a coloured
severity strip, an icon, Arabic buttons in the v6.18 button hierarchy —
instead of the default OS message box.

Behaviour contract (never broken):
- showinfo/showwarning/showerror show a modal dialog with an «حسناً»
  button and return "ok" (like messagebox).
- askyesno shows «نعم» / «لا» and returns True/False; Escape or closing
  the window means «لا» (False), matching messagebox's safe default.
- Any failure while building the themed dialog falls back to the real
  tkinter.messagebox, so the user always sees the message.

The active theme is pushed with set_theme(theme_name, accent) whenever
the app applies its theme; before that the dark default is used.
"""
import tkinter as tk
from tkinter import messagebox as _mb
from tkinter import ttk

import ui_theme

_THEME_NAME = "dark"
_ACCENT = "teal"


def set_theme(theme_name, accent=None):
    """Called by the app after every apply_theme so dialogs follow it."""
    global _THEME_NAME, _ACCENT
    if theme_name in ui_theme.PALETTES:
        _THEME_NAME = theme_name
    if accent in ui_theme.ACCENTS:
        _ACCENT = accent


# kind → (icon, status colour kind, OK button kind)
_KIND_META = {
    "info": ("ℹ️", "info", "primary"),
    "success": ("✅", "success", "success"),
    "warning": ("⚠️", "warning", "warning"),
    "error": ("⛔", "danger", "danger"),
    "question": ("❓", "warning", "primary"),
}


def _run_dialog(title, message, kind, parent, buttons):
    """Build and run the modal themed dialog.

    buttons: list of (text, result, button_kind).  Returns the chosen
    result, or None when the window was closed without choosing.
    Raises on any construction problem — callers fall back to the real
    messagebox, so a theme glitch can never hide a message.
    """
    root = parent or tk._default_root
    if root is None:
        raise RuntimeError("no Tk root for themed dialog")
    pal = ui_theme.palette(_THEME_NAME, _ACCENT)
    icon, col_kind, _ok_kind = _KIND_META.get(kind, _KIND_META["info"])
    fg, bg = ui_theme.status_colors(col_kind, _THEME_NAME, _ACCENT)

    win = tk.Toplevel(root)
    win.withdraw()
    win.title(str(title))
    win.configure(bg=pal["card_bg"])
    win.resizable(False, False)
    ui_theme.apply_win11_window_style(win, _THEME_NAME, _ACCENT)
    try:
        win.transient(root)
    except Exception:
        pass

    result = {"value": None}

    def choose(value):
        result["value"] = value
        try:
            win.destroy()
        except Exception:
            pass

    # Coloured severity strip on top.
    tk.Frame(win, bg=fg, height=5).pack(fill="x")

    head = tk.Frame(win, bg=pal["card_bg"])
    head.pack(fill="x", padx=16, pady=(12, 0))
    tk.Label(head, text=icon, bg=pal["card_bg"], fg=fg,
             font=(ui_theme.FONT_FAMILY, 20)).pack(side="left")
    tk.Label(head, text=str(title), bg=pal["card_bg"], fg=pal["text"],
             font=ui_theme.font(13, bold=True),
             wraplength=380, justify="left").pack(side="left", padx=10)

    btns = tk.Frame(win, bg=pal["card_bg"])
    btns.pack(side="bottom", pady=(8, 14))
    first = None
    for text, value, bkind in buttons:
        b = ttk.Button(btns, text=text,
                       style=ui_theme.button_style_for(bkind),
                       command=lambda v=value: choose(v))
        b.pack(side="left", padx=6)
        if first is None:
            first = b

    # Long messages (previews, details) scroll inside a bounded box so the buttons always stay
    # reachable on small screens. The buttons are packed first, at the bottom.
    msg = str(message)
    try:
        sh = root.winfo_screenheight()
    except Exception:
        sh = 768
    max_lines = max(6, min(18, (sh - 360) // 22))
    if msg.count("\n") + 1 > max_lines or len(msg) > 1100:
        box = tk.Frame(win, bg=bg)
        box.pack(fill="both", expand=True, padx=16, pady=(10, 4))
        sb = ttk.Scrollbar(box, orient="vertical")
        txt = tk.Text(box, bg=bg, fg=pal["text"], font=ui_theme.font(11), wrap="word",
                      width=52, height=max_lines, relief="flat", yscrollcommand=sb.set,
                      padx=12, pady=8, highlightthickness=0)
        sb.config(command=txt.yview)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", msg)
        txt.config(state="disabled")
    else:
        tk.Label(win, text=str(message), bg=bg, fg=pal["text"],
                 font=ui_theme.font(11), wraplength=420, justify="left",
                 anchor="w", padx=12, pady=8).pack(fill="x", padx=16, pady=(10, 4))

    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.bind("<Escape>", lambda e: win.destroy())
    if first is not None:
        win.bind("<Return>", lambda e: first.invoke())

    # Centre over the parent/root window.
    win.update_idletasks()
    try:
        rw = root.winfo_width()
        rh = root.winfo_height()
        rx = root.winfo_rootx()
        ry = root.winfo_rooty()
        ww = win.winfo_reqwidth()
        wh = win.winfo_reqheight()
        if rw > 1 and rh > 1:
            win.geometry("+%d+%d" % (rx + max(0, (rw - ww) // 2),
                                     ry + max(0, (rh - wh) // 3)))
    except Exception:
        pass
    win.deiconify()
    if first is not None:
        first.focus_set()
    try:
        win.grab_set()
    except Exception:
        pass
    root.wait_window(win)
    return result["value"]


_FALLBACK = {"info": _mb.showinfo, "success": _mb.showinfo,
             "warning": _mb.showwarning, "error": _mb.showerror}


def _show(kind, title, message, parent=None, **kw):
    _icon, _col, ok_kind = _KIND_META.get(kind, _KIND_META["info"])
    try:
        _run_dialog(title, message, kind, parent,
                    [("حسناً", "ok", ok_kind)])
        return "ok"
    except Exception:
        try:
            _FALLBACK.get(kind, _mb.showinfo)(title, message,
                                              parent=parent, **kw)
        except Exception:
            pass
        return "ok"


def showinfo(title, message, parent=None, **kw):
    return _show("info", title, message, parent=parent, **kw)


def showwarning(title, message, parent=None, **kw):
    return _show("warning", title, message, parent=parent, **kw)


def showerror(title, message, parent=None, **kw):
    return _show("error", title, message, parent=parent, **kw)


def askyesno(title, message, parent=None, **kw):
    """Themed نعم/لا dialog.  Escape/close = لا (False), like messagebox."""
    try:
        return bool(_run_dialog(
            title, message, "question", parent,
            [("نعم", True, "primary"), ("لا", False, "secondary")]))
    except Exception:
        try:
            return bool(_mb.askyesno(title, message, parent=parent, **kw))
        except Exception:
            return False
