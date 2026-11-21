# -*- coding: utf-8 -*-
"""اختبارات هيكلية لإصدار v6.21 — ملاءمة الشاشة وDPI.

بدون Tkinter: فحص AST ونص — وعي DPI قبل إنشاء أي نافذة، كل تبويب
قابل للتمرير، المحتوى القصير يتمدد والطويل يمرَّر، والحد الأدنى
يُقصّ على حجم الشاشة الحقيقي.

التشغيل: py tests/test_screen_fit_v621.py
"""

import ast
import os
import re
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(BASE, "main.py")
THEME = os.path.join(BASE, "ui_theme.py")


def func_source(tree, src, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node)
    raise AssertionError(name + " not found")


class TestDpiAwareness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(MAIN, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)

    def test_dpi_helper_exists(self):
        seg = func_source(self.tree, self.src, "_enable_dpi_awareness")
        self.assertIn("SetProcessDpiAwareness(2)", seg)   # per-monitor
        self.assertIn("SetProcessDPIAware()", seg)         # fallback
        self.assertIn("except Exception", seg)             # غير ويندوز يتخطى

    def test_dpi_set_before_any_window(self):
        # الاستدعاء أول سطر داخل main() — قبل LoginWindow وأي Tk().
        main_seg = func_source(self.tree, self.src, "main")
        call_at = main_seg.find("_enable_dpi_awareness()")
        login_at = main_seg.find("LoginWindow(")
        self.assertGreaterEqual(call_at, 0)
        self.assertGreater(login_at, call_at)

    def test_stdlib_only(self):
        self.assertIn("import ctypes", self.src)


class TestScrollableTabs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(MAIN, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)

    def test_every_tab_builder_scrollable(self):
        # التبويبات العشرة كلها تمر عبر _scrollable_tab (بناة مباشرة أو
        # عبر نمطها الخاص في الموبايل).
        for builder in ("build_dashboard", "build_pos", "build_inventory",
                        "build_purchases", "build_customers", "build_reports",
                        "build_cash", "build_ai", "build_settings"):
            seg = func_source(self.tree, self.src, builder)
            self.assertIn("_scrollable_tab(", seg, builder)
        # الموبايل: نمط التمرير الخاص به منذ v4.4 (canvas + scrollbar).
        mobile = func_source(self.tree, self.src, "build_mobile")
        self.assertIn("Scrollbar", mobile)
        self.assertIn("scrollregion", mobile)

    def test_short_content_still_stretches(self):
        seg = func_source(self.tree, self.src, "_scrollable_tab")
        self.assertIn("winfo_reqheight", seg)
        self.assertIn("max(canvas.winfo_height()", seg)

    def test_scroll_region_and_mousewheel(self):
        seg = func_source(self.tree, self.src, "_scrollable_tab")
        self.assertIn("scrollregion", seg)
        self.assertIn("MouseWheel", seg)


class TestScreenAwareSizes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(THEME, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)
        cls.main_src = open(MAIN, encoding="utf-8").read()

    def test_minsize_capped_by_screen(self):
        seg = func_source(self.tree, self.src, "setup_main_window")
        self.assertIn("min(1024, max(sw - 40, 640))", seg)
        self.assertIn("min(600, max(sh - 120, 480))", seg)

    def test_saved_geometry_still_validated(self):
        seg = func_source(self.tree, self.src, "_geometry_ok")
        self.assertIn("return False", seg)

    def test_version_bumped(self):
        self.assertIn("Pharmacy Enterprise v6.23", self.main_src)
        self.assertIn("نظام إدارة الصيدلية — v6.23", self.main_src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
