"""Standard launcher plus the optional availability settings extension.

The base application and its billing paths are unchanged. No network on import.
Running main.py directly still starts the base app without this extension.
"""
import main as base
from tkinter import ttk


class AvailabilityApp(base.App):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from availability_sync import start_worker
        self._availability_stop = start_worker(
            self.db.path, self.db.path + '.availability.sqlite3')

    def build_settings(self, outer=None):
        if outer is None:
            outer = ttk.Frame(self.notebook)
            self.notebook.add(outer, text='⚙️ الإعدادات')
        if self.is_admin:
            from availability_ui import open_settings
            header = ttk.Frame(outer)
            header.pack(side='top', fill='x', padx=14, pady=5)
            ttk.Button(header, text='مزامنة توفر الأدوية - إعداد ومراجعة',
                       command=lambda: open_settings(self)).pack(anchor='e')
        super().build_settings(outer)


def main():
    # Explicit launcher extension point; no changes to sales/database modules.
    base.App = AvailabilityApp
    base.main()


if __name__ == '__main__':
    main()
