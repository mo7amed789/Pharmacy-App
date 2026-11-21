# -*- coding: utf-8 -*-
"""اختبارات هيكلية لتلميع الواجهة v6.18 — بدون Tkinter.

v6.18 تضيف: هرمية أزرار واحدة (primary/success/danger/warning/secondary)
بحالات hover/pressed لكل نوع، لغة ألوان حالات موحّدة (STATUS_KINDS +
STATUS_WORDS + وسوم Treeview)، ورسائل منبثقة مثيمة (ui_dialogs) بدل
صناديق النظام الافتراضية.

ui_theme.py وui_dialogs.py يستوردان tkinter فلا يمكن استيرادهما بدون
شاشة، لذا نفحص بالـ AST والمصدر حرفياً، ونقيّم القواميس بـ literal_eval.

التشغيل: py tests/test_ui_polish_v618.py
"""

import ast
import os
import re
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(BASE, "ui_theme.py")
DIALOGS = os.path.join(BASE, "ui_dialogs.py")
MAIN = os.path.join(BASE, "main.py")

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

# ألوان الثيم الفاتح القديمة كانت منقوشة يدوياً في main.py — v6.18
# تنقلها كلها للوحة الألوان، فلا يجب أن يبقى أي منها.
LEGACY_HEXES = ["#B45309", "#B91C1C", "#9CA3AF", "#0F766E", "#15803D",
                "#1D4ED8", "#6D28D9", "#b00020"]


def literal_dict(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(name + " not found")


def func_names(tree):
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


class TestStatusLanguage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(THEME, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)

    def test_status_kinds_complete(self):
        kinds = literal_dict(self.tree, "STATUS_KINDS")
        self.assertEqual(set(kinds),
                         {"success", "warning", "danger", "info", "muted"})

    def test_status_words_map_to_known_kinds(self):
        kinds = set(literal_dict(self.tree, "STATUS_KINDS"))
        words = literal_dict(self.tree, "STATUS_WORDS")
        self.assertGreaterEqual(len(words), 15)
        for word, kind in words.items():
            self.assertIn(kind, kinds, "%s -> %s" % (word, kind))

    def test_negative_phrases_come_before_positive_substrings(self):
        # «غير مفعّلة» تحتوي «مفعّلة» — يجب أن تسبقها حتى لا تلوَّن
        # غير المفعّلة بالأخضر.
        words = list(literal_dict(self.tree, "STATUS_WORDS"))
        self.assertLess(words.index("غير مفعّلة"), words.index("مفعّلة"))

    def test_status_helpers_exist(self):
        names = func_names(self.tree)
        for fn in ("status_colors", "status_kind_for", "status_label",
                   "set_status"):
            self.assertIn(fn, names)

    def test_status_colors_use_palette_pairs(self):
        self.assertIn('"success_bg"', self.src)
        self.assertIn('"warning_bg"', self.src)
        self.assertIn('"danger_bg"', self.src)
        self.assertIn('"info_bg"', self.src)


class TestButtonHierarchy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(THEME, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)

    def test_button_kinds_map_to_styles(self):
        kinds = literal_dict(self.tree, "BUTTON_KINDS")
        for semantic in ("primary", "success", "danger", "warning",
                         "secondary"):
            self.assertIn(semantic, kinds)
        for style_name in set(kinds.values()):
            self.assertTrue(style_name.endswith("TButton"), style_name)

    def test_all_solid_variants_configured_with_state_maps(self):
        # كل نوع له style.configure وstyle.map (hover/pressed).
        for style_name in ("Accent.TButton", "Success.TButton",
                           "Danger.TButton", "Warning.TButton",
                           "Info.TButton"):
            self.assertIn('"%s"' % style_name, self.src)
        # الخمسة الصلبة تُبنى عبر _solid_button مع خريطة حالات.
        for style_name in ("Accent.TButton", "Success.TButton",
                           "Danger.TButton", "Warning.TButton",
                           "Info.TButton"):
            self.assertIn('_solid_button("%s"' % style_name, self.src)
        self.assertIn('("active"', self.src)
        self.assertIn('("pressed"', self.src)
        self.assertIn("_shade(base, 0.72)", self.src)
        self.assertIn("_shade(base, 1.18)", self.src)

    def test_button_helpers_exist(self):
        names = func_names(self.tree)
        for fn in ("button_style_for", "styled_button", "_shade"):
            self.assertIn(fn, names)

    def test_shade_logic(self):
        # نعيد تنفيذ منطق _shade (لا يمكن استيراد ui_theme بدون شاشة).
        def shade(hex_color, factor):
            h = hex_color.lstrip("#")
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
            return "#%02X%02X%02X" % (r, g, b)
        self.assertEqual(shade("#000000", 1.0), "#000000")
        self.assertEqual(shade("#FFFFFF", 0.5), "#7F7F7F")
        self.assertEqual(shade("#14B8A6", 0.72), "#0E8477")
        self.assertRegex(shade("#14B8A6", 1.18), HEX)


class TestTreeviewStatusTags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(THEME, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)

    def test_status_tags_defined(self):
        tags = literal_dict(self.tree, "STATUS_TAGS")
        for tag in ("held", "paid", "due", "failed", "synced"):
            self.assertIn(tag, tags)

    def test_style_treeview_configures_new_tags(self):
        for tag in ("held", "paid", "due", "failed", "synced"):
            self.assertIn('"%s"' % tag, self.src)

    def test_stripe_rows_preserves_status_tags(self):
        self.assertIn("if t in STATUS_TAGS", self.src)


class TestThemedDialogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(DIALOGS, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)

    def test_messagebox_api_functions_exist(self):
        names = func_names(self.tree)
        for fn in ("showinfo", "showwarning", "showerror", "askyesno",
                   "set_theme"):
            self.assertIn(fn, names)

    def test_every_public_function_falls_back_to_real_messagebox(self):
        # أي عطل في الحوار المثيم يرجع لـ tkinter.messagebox — الرسالة
        # لا تضيع أبداً.
        self.assertIn("from tkinter import messagebox as _mb", self.src)
        self.assertIn("_FALLBACK", self.src)
        self.assertIn("_mb.askyesno", self.src)
        for fn in ("showinfo", "showwarning", "showerror"):
            self.assertIn("_mb.%s" % fn, self.src)

    def test_askyesno_returns_bool_and_cancel_is_no(self):
        self.assertIn("return bool(_run_dialog(", self.src)
        # Escape والإغلاق = لا
        self.assertIn('("<Escape>"', self.src)
        self.assertIn('("نعم", True, "primary")', self.src)
        self.assertIn('("لا", False, "secondary")', self.src)

    def test_dialog_is_modal_and_themed(self):
        self.assertIn("grab_set", self.src)
        self.assertIn("wait_window", self.src)
        self.assertIn("ui_theme.status_colors", self.src)
        self.assertIn("ui_theme.button_style_for", self.src)


class TestMainWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(MAIN, encoding="utf-8").read()

    def test_messagebox_aliased_to_ui_dialogs(self):
        self.assertIn("import ui_dialogs as messagebox", self.src)
        # السطر القديم لا يستورد messagebox الخام بعد الآن.
        self.assertNotIn("from tkinter import ttk, messagebox", self.src)
        self.assertNotIn("import messagebox\n", self.src)

    def test_dialog_theme_pushed_after_apply_theme(self):
        self.assertGreaterEqual(self.src.count("ui_dialogs.set_theme("), 2)

    def test_no_legacy_hardcoded_hexes(self):
        for hex_color in LEGACY_HEXES:
            self.assertNotIn('"%s"' % hex_color, self.src)
        self.assertNotIn('foreground="red"', self.src)

    def test_status_labels_use_palette_colors(self):
        # حالات السيرفر والهوت سبوت والمزامنة تتلوّن من اللوحة.
        self.assertIn('foreground=self.pal["success"]', self.src)
        self.assertIn('foreground=self.pal["danger"]', self.src)
        self.assertIn('foreground=self.pal["warning"]', self.src)
        self.assertIn("_cloud_refresh_label", self.src)

    def test_version_bumped(self):
        self.assertIn("Pharmacy Enterprise v6.19", self.src)
        self.assertIn("نظام إدارة الصيدلية — v6.19", self.src)

    def test_button_hierarchy_applied_to_visible_actions(self):
        # الحذف والمسح والمرتجع بألوانهم الدلالية.
        self.assertIn('style="Danger.TButton"', self.src)
        self.assertIn('style="Warning.TButton"', self.src)

    def test_shortcuts_and_commands_untouched(self):
        # السلوك: الأوامر نفسها، تغيّر الشكل فقط.
        for cmd in ("command=self.pos_remove_line",
                    "command=self.pos_restore_line",
                    "command=self.pos_clear_cart",
                    "command=self.pos_complete_sale",
                    "command=self.pur_save"):
            self.assertIn(cmd, self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
