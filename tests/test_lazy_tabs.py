# -*- coding: utf-8 -*-
"""اختبارات هيكلية لتحميل التبويبات الكسول (v6.14) — بدون Tkinter.

الواجهة نفسها لا تُختبر بدون شاشة، لكن نتحقق statically من العقد:
كل تبويب غير الرئيسية له builder مسجل، كل builder يقبل frame خارجياً،
وكل دالة refresh عبر التبويبات محمية بـ hasattr حتى لا تنهار قبل البناء.

التشغيل: py tests/test_lazy_tabs.py
"""

import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "main.py")


def app_class(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "App":
            return node
    raise AssertionError("App class not found")


def methods(cls):
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


class TestLazyTabs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(open(MAIN, encoding="utf-8").read())
        cls.cls = app_class(cls.tree)
        cls.methods = methods(cls.cls)
        cls.src = open(MAIN, encoding="utf-8").read()

    def test_ensure_tab_exists(self):
        self.assertIn("_ensure_tab", self.methods)

    def test_nine_lazy_builders_registered(self):
        init_src = ast.get_source_segment(self.src, self.methods["__init__"])
        for builder in ("self.build_pos", "self.build_inventory",
                        "self.build_purchases", "self.build_customers",
                        "self.build_reports", "self.build_cash",
                        "self.build_settings", "self.build_ai",
                        "self.build_mobile"):
            self.assertIn(builder, init_src, builder)

    def test_builders_accept_external_frame(self):
        for name, param in (("build_pos", "tab"),
                            ("build_inventory", "tab"),
                            ("build_purchases", "tab"),
                            ("build_customers", "tab"),
                            ("build_reports", "tab"),
                            ("build_cash", "tab"),
                            ("build_ai", "outer"),
                            ("build_mobile", "tab"),
                            ("build_settings", "outer")):
            fn = self.methods[name]
            args = [a.arg for a in fn.args.args]
            self.assertIn(param, args, name)

    def test_cross_tab_refreshes_are_guarded(self):
        guards = {"inv_refresh": "tree_inv", "pos_search_refresh": "list_search",
                  "cust_refresh": "tree_cust", "reports_refresh": "tree_best",
                  "cash_refresh": "lbl_shift", "pur_search_refresh": "list_pur",
                  "audit_refresh": "txt_audit"}
        for name, attr in guards.items():
            seg = ast.get_source_segment(self.src, self.methods[name])
            self.assertIn('hasattr(self, "%s")' % attr, seg, name)

    def test_goto_and_tab_change_ensure_first(self):
        for name in ("goto_tab", "_on_tab_changed"):
            seg = ast.get_source_segment(self.src, self.methods[name])
            self.assertIn("self._ensure_tab", seg, name)

    def test_dashboard_ai_is_background(self):
        seg = ast.get_source_segment(self.src, self.methods["refresh_dashboard"])
        self.assertNotIn("generate_reorder_list", seg)  # لا حساب متزامن
        self.assertIn("_kick_dash_ai", seg)
        kick = ast.get_source_segment(self.src, self.methods["_kick_dash_ai"])
        self.assertIn("run_in_background", kick)
        self.assertIn("init=False", kick)  # اتصال خاص بالخيط

    def test_startup_backup_is_threaded(self):
        main_fn = [n for n in ast.walk(self.tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "main"][0]
        seg = ast.get_source_segment(self.src, main_fn)
        self.assertIn("_startup_backup_async", seg)
        self.assertIn("threading.Thread", seg)
        # لا نسخ متزامن على اتصال الواجهة في مسار الفتح
        self.assertNotIn("        db.backup()", seg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
