# -*- coding: utf-8 -*-
"""اختبارات هيكلية لإصدار v6.20 — مظهر Windows 11 Fluent + أحجام النوافذ.

بدون Tkinter (لا شاشة في بيئة الاختبار): نفحص ui_theme.py و main.py
بالـ AST والنص — سلسلة الخطوط، مقياس الأحجام، البطاقات المدوّرة مع
بديل آمن، لوحتا الألوان الحياديتان، وحفظ/استعادة أبعاد النافذة.

التشغيل: py tests/test_win11_fluent_v620.py
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


def literal_dict(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(name + " not found")


def func_source(tree, src, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node)
    raise AssertionError(name + " not found")


def _lum(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class TestFluentTypography(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(THEME, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)

    def test_segoe_ui_variable_preferred(self):
        fams = literal_dict(self.tree, "FONT_FAMILIES_PREFERRED")
        self.assertEqual(fams[0], "Segoe UI Variable Text")
        self.assertIn("Segoe UI", fams)
        self.assertIn("Tahoma", fams)

    def test_resolve_font_family_safe(self):
        seg = func_source(self.tree, self.src, "resolve_font_family")
        self.assertIn("tkfont.families", seg)
        self.assertIn("except Exception", seg)  # لا فشل بدون شاشة/خط

    def test_apply_theme_resolves_family(self):
        seg = func_source(self.tree, self.src, "apply_theme")
        self.assertIn("resolve_font_family(root)", seg)

    def test_type_scale_defined(self):
        scale = literal_dict(self.tree, "TYPE_SCALE")
        for key in ("caption", "body", "subtitle", "title", "display"):
            self.assertIn(key, scale)
        self.assertLess(scale["caption"], scale["body"])
        self.assertLess(scale["body"], scale["title"])
        self.assertLess(scale["title"], scale["display"])


class TestFluentPalettes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(open(THEME, encoding="utf-8").read())

    def test_win11_neutral_surfaces(self):
        light = literal_dict(self.tree, "LIGHT")
        dark = literal_dict(self.tree, "DARK")
        self.assertEqual(light["bg"], "#F3F3F3")   # Win11 light mica
        self.assertEqual(dark["bg"], "#202020")    # Win11 dark charcoal
        self.assertEqual(dark["card_bg"], "#2C2C2C")

    def test_borders_are_subtle(self):
        # الحدود قريبة درجياً من الخلفية — hairline وليست إطاراً ثقيلاً.
        for name in ("LIGHT", "DARK"):
            pal = literal_dict(self.tree, name)
            gap = abs(_lum(pal["border"]) - _lum(pal["card_bg"]))
            self.assertLess(gap, 60, "%s border too strong" % name)

    def test_status_language_untouched(self):
        for name in ("LIGHT", "DARK"):
            pal = literal_dict(self.tree, name)
            for key in ("success", "warning", "danger", "info"):
                self.assertRegex(pal[key], HEX)


class TestRoundedCards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(THEME, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)

    def test_round_rect_helper(self):
        self.assertIn("def _round_rect(", self.src)
        self.assertIn("create_polygon", self.src)
        self.assertIn("smooth=True", self.src)

    def test_card_radius_defined(self):
        self.assertRegex(self.src, r"CARD_RADIUS\s*=\s*\d+")

    def test_make_card_uses_rounded_with_safe_fallback(self):
        seg = func_source(self.tree, self.src, "make_card")
        self.assertIn("_make_rounded_card", seg)
        self.assertIn("except Exception", seg)
        self.assertIn("_make_flat_card", seg)

    def test_rounded_card_reacts_to_recolor(self):
        seg = func_source(self.tree, self.src, "recolor_card")
        self.assertIn("tk.Canvas", seg)
        self.assertIn("_card_theme", seg)

    def test_canvas_requests_content_size(self):
        # الـ canvas لا يحسب عناصر النافذة في حجمه المطلوب — بدون هذا
        # تنكمش البطاقة إلى شريط رفيع.
        seg = func_source(self.tree, self.src, "_make_rounded_card")
        self.assertIn("winfo_reqheight", seg)
        self.assertIn("cv.configure", seg)

    def test_headings_are_quiet(self):
        seg = func_source(self.tree, self.src, "apply_theme")
        i = seg.find('"Treeview.Heading"')
        self.assertGreaterEqual(i, 0)
        block = seg[i:i + 320]
        self.assertIn('p["row_alt"]', block)
        self.assertIn('p["muted"]', block)
        self.assertNotIn('p["header_bg"]', block)


class TestWindowSizing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(THEME, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)
        cls.main_src = open(MAIN, encoding="utf-8").read()

    def test_setup_main_window_helper(self):
        seg = func_source(self.tree, self.src, "setup_main_window")
        self.assertIn("minsize(min(1024, max(sw - 40, 640))", seg)  # v6.21: capped by the real screen
        self.assertIn("ui_geometry", seg)
        self.assertIn("ui_maximized", seg)
        self.assertIn("winfo_screenwidth", seg)     # حجم افتراضي يفهم الشاشة
        self.assertIn('state("zoomed")', seg)        # أول تشغيل كما كان: مكبّرة
        self.assertIn("WM_DELETE_WINDOW", seg)       # الحفظ عند الإغلاق

    def test_geometry_validation_exists(self):
        seg = func_source(self.tree, self.src, "_geometry_ok")
        self.assertIn("return False", seg)  # يرفض أبعاداً خارج الشاشة

    def test_app_uses_setup_main_window(self):
        self.assertIn("ui_theme.setup_main_window(root, db)", self.main_src)
        self.assertNotIn('root.geometry("1280x800")', self.main_src)
        self.assertNotIn("root.minsize(1100, 650)", self.main_src)

    def test_login_centered(self):
        self.assertIn("ui_theme.center_window(self.root, 430, 400)",
                      self.main_src)

    def test_center_window_helper(self):
        self.assertIn("def center_window(", self.src)

    def test_version_bumped(self):
        self.assertIn("Pharmacy Enterprise v6.28", self.main_src)
        self.assertIn("نظام إدارة الصيدلية — v6.28", self.main_src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
