# -*- coding: utf-8 -*-
"""اختبارات هيكلية لإصدار v6.22 — لا زر إجراء خارج الشاشة في أي نافذة.

بدون Tkinter: فحص AST ونص — وجود fit_dialog و dialog_form_area، تغطية
كل Toplevel في البرنامج (إما fit_dialog أو dialog_form_area أو نمط
تمرير خاص)، ونافذة إضافة الدواء بالذات: قصّ على الشاشة + نموذج يُمرَّر
+ زر الحفظ في تذييل ثابت.

التشغيل: py tests/test_dialog_fit_v622.py
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


class TestHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(THEME, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)

    def test_fit_dialog_caps_and_centres(self):
        seg = func_source(self.tree, self.src, "fit_dialog")
        self.assertIn("winfo_screenwidth", seg)
        self.assertIn("min(int(w)", seg)       # لا يكبر عن الطلب
        self.assertIn("sw - margin_x", seg)    # ولا يبقى أكبر من الشاشة
        self.assertIn("except Exception", seg)  # لا يعطّل فتح النافذة أبداً

    def test_dialog_form_area_footer_first(self):
        seg = func_source(self.tree, self.src, "dialog_form_area")
        # التذييل يُحزم أولاً side=bottom حتى لا يزاح خارجاً أبداً
        self.assertLess(seg.find("footer.pack"), seg.find("canvas.pack"))
        self.assertIn('side="bottom"', seg)
        self.assertIn("scrollregion", seg)
        self.assertIn("MouseWheel", seg)

    def test_wheel_binding_does_not_unbind_others(self):
        seg = func_source(self.tree, self.src, "dialog_form_area")
        self.assertNotIn(".unbind_all(", seg)  # لا إزالة لارتباطات التبويبات
        self.assertIn("winfo_exists", seg)  # الحارس بدل unbind_all


class TestDrugDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(MAIN, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)
        cls.seg = func_source(cls.tree, cls.src, "drug_dialog")

    def test_no_fixed_tall_geometry(self):
        self.assertNotIn('geometry("480x900")', self.seg)
        self.assertIn("ui_theme.fit_dialog(win, 480, 900)", self.seg)

    def test_scrollable_form_plus_footer(self):
        self.assertIn("dialog_form_area(win, self.theme_name)", self.seg)
        self.assertIn("_footer, text=\"💾 حفظ\"", self.seg)
        # الحقول داخل جسم النموذج لا النافذة مباشرة
        self.assertIn("ttk.Entry(_form,", self.seg)
        self.assertIn("ttk.Label(_form,", self.seg)

    def test_minsize_fits_small_screens(self):
        m = re.search(r"win\.minsize\((\d+), (\d+)\)", self.seg)
        self.assertIsNotNone(m)
        self.assertLessEqual(int(m.group(2)), 400)  # كان 600 — يخنق 768


class TestEveryDialogCovered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(MAIN, encoding='utf-8').read()
        cls.tree = ast.parse(cls.src)

    def test_no_bare_fixed_geometry_left(self):
        # لا geometry("WxH") ثابتة على أي Toplevel بعد الآن.
        leftovers = re.findall(r'win\.geometry\("\d+x\d+"\)', self.src)
        self.assertEqual(leftovers, [])

    def test_known_tall_dialogs_use_form_area(self):
        for fn in ("drug_dialog", "barcode_label_dialog_for"):
            seg = func_source(self.tree, self.src, fn)
            self.assertIn("dialog_form_area(", seg, fn)

    def test_text_dump_windows_capped(self):
        for fn in ("show_shortages", "show_expiry", "customer_history_dialog",
                   "show_inventory_value", "_open_receipt_window",
                   "mobile_show_all"):
            seg = func_source(self.tree, self.src, fn)
            self.assertIn("fit_dialog(", seg, fn)

    def test_every_toplevel_has_a_fit_or_scroll(self):
        # كل دالة تفتح Toplevel يجب أن تمر عبر fit_dialog أو
        # dialog_form_area أو center_window أو نمط تمرير خاص.
        uncovered = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            seg = ast.get_source_segment(self.src, node) or ""
            if "tk.Toplevel" not in seg:
                continue
            if any(k in seg for k in ("fit_dialog(", "dialog_form_area(",
                                      "center_window(", "update_idletasks")):
                continue
            uncovered.append(node.name)
        self.assertEqual(uncovered, [])

    def test_version_bumped(self):
        self.assertIn("Pharmacy Enterprise v6.28", self.src)
        self.assertIn("نظام إدارة الصيدلية — v6.28", self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
