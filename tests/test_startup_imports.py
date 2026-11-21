# -*- coding: utf-8 -*-
"""اختبار انحدار v6.18 hotfix — كل وحدة تُستخدم باسمها يجب أن تكون مستوردة.

الخطأ الذي يصيده هذا الاختبار: v6.18 استوردت ui_dialogs بالاسم المستعار
فقط (import ui_dialogs as messagebox) ثم استخدمت ui_dialogs.set_theme —
فتحطم البرنامج عند الإقلاع بـ NameError لم تلتقطه الاختبارات الهيكلية
ولا py_compile (خطأ وقت التشغيل، ليس نحوياً).

الفحص: لكل استخدام attribute جذره اسم وحدة محلية موجودة كملف .py في
جذر المشروع (مثل ui_dialogs.set_theme)، يجب أن يكون الاسم نفسه مرتبطاً
باستيراد في أي نقطة من الملف — الاسم المستعار وحده لا يكفي.

التشغيل: py tests/test_startup_imports.py
"""

import ast
import os
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(BASE, "main.py")

# الوحدات المحلية: ملفات .py في جذر المشروع.
LOCAL_MODULES = {
    os.path.splitext(f)[0]
    for f in os.listdir(BASE)
    if f.endswith(".py") and os.path.isfile(os.path.join(BASE, f))
}


def imported_names(tree):
    """Every name bound by any import, at any scope (alias or plain)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)
    return names


def used_module_roots(tree):
    """Root names of attribute chains that match a local module file."""
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in LOCAL_MODULES:
                roots.add(root.id)
    return roots


class TestStartupImports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(MAIN, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)

    def test_every_used_local_module_is_imported_by_its_own_name(self):
        bound = imported_names(self.tree)
        used = used_module_roots(self.tree)
        self.assertIn("ui_dialogs", used)  # sanity: the check has teeth
        missing = sorted(used - bound)
        self.assertEqual(missing, [],
                         "modules used but never imported by name: %s"
                         % ", ".join(missing))

    def test_ui_dialogs_plain_import_present(self):
        # import ui_dialogs as messagebox يقيّد الاسم messagebox فقط —
        # السطر الصريح إلزامي لأن main.py يستدعي ui_dialogs.set_theme.
        self.assertTrue(
            any(isinstance(n, ast.Import)
                and any(a.name == "ui_dialogs" and a.asname is None
                        for a in n.names)
                for n in ast.walk(self.tree)),
            "main.py must contain a plain `import ui_dialogs`")

    def test_messagebox_alias_still_present(self):
        # 180 موضع messagebox.* يعتمد على الاسم المستعار.
        self.assertIn("import ui_dialogs as messagebox", self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
