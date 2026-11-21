# -*- coding: utf-8 -*-
"""اختبارات هيكلية للثيم المستقبلي (v6.15) — بدون Tkinter.

ui_theme.py يستورد tkinter فلا يمكن استيراده بدون شاشة، لذا نفحص
الملفات بالـ AST ونقيّم القواميس حرفياً: تطابق مفاتيح اللوحتين، صيغة
الألوان، اكتمال الأكسنتات، والوضع الافتراضي.

التشغيل: py tests/test_theme.py
"""

import ast
import os
import re
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(BASE, "ui_theme.py")
MAIN = os.path.join(BASE, "main.py")

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

PALETTE_KEYS = {
    "name", "bg", "card_bg", "header_bg", "header_bg2", "header_fg",
    "text", "muted", "accent", "accent_hover", "success", "success_bg",
    "warning", "warning_bg", "danger", "danger_bg", "info", "info_bg",
    "input_bg", "border", "row_alt", "row_bg", "selected_bg",
}
COLOR_KEYS = PALETTE_KEYS - {"name"}


def literal_dict(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(name + " not found")


class TestTheme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(open(THEME, encoding="utf-8").read())
        cls.src = open(THEME, encoding="utf-8").read()
        cls.main_src = open(MAIN, encoding="utf-8").read()

    def test_palettes_have_identical_complete_keys(self):
        light = literal_dict(self.tree, "LIGHT")
        dark = literal_dict(self.tree, "DARK")
        self.assertEqual(set(light), set(dark))
        self.assertEqual(set(light), PALETTE_KEYS)

    def test_all_palette_colors_are_hex(self):
        for name in ("LIGHT", "DARK"):
            pal = literal_dict(self.tree, name)
            for key in COLOR_KEYS:
                self.assertRegex(pal[key], HEX, "%s.%s" % (name, key))

    def test_accents_complete_and_valid(self):
        accents = literal_dict(self.tree, "ACCENTS")
        self.assertIn("teal", accents)
        self.assertIn("violet", accents)  # الأكسنت المستقبلي الجديد
        for key, a in accents.items():
            for field in ("label", "accent", "hover", "header", "header2"):
                self.assertIn(field, a, "%s.%s" % (key, field))
            for field in ("accent", "hover", "header", "header2"):
                self.assertRegex(a[field], HEX, "%s.%s" % (key, field))

    def test_dark_is_the_default(self):
        tree = self.tree
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_theme_name":
                seg = ast.get_source_segment(self.src, node)
                self.assertIn('return "dark"', seg)
                break
        else:
            self.fail("get_theme_name not found")

    def test_scrollbar_and_plain_widget_theming_present(self):
        self.assertIn("Vertical.TScrollbar", self.src)
        self.assertIn("*Text.Background", self.src)
        self.assertIn("*TCombobox*Listbox.Background", self.src)

    def test_treeview_rowheight_roomier(self):
        m = re.search(r'rowheight=(\d+)', self.src)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 36)

    def test_version_bumped(self):
        self.assertIn("Pharmacy Enterprise v6.29", self.main_src)
        self.assertNotIn("Pharmacy Enterprise v6.14", self.main_src)

    def test_login_uses_saved_theme(self):
        self.assertIn("ui_theme.get_theme_name(db)", self.main_src)
        self.assertNotIn('apply_theme(self.root, _style, "light")', self.main_src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
