"""Standard launcher plus the optional availability settings extension (Qt Fluent)."""
import main as base
from qfluentwidgets import PushButton


class AvailabilityApp(base.App):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from availability_sync import start_worker
        self._availability_stop = start_worker(
            self.db.path, self.db.path + ".availability.sqlite3"
        )

    def build_settings(self, outer=None):
        super().build_settings(outer)
        if self.is_admin and hasattr(self, "_settings_layout"):
            from availability_ui import open_settings
            btn = PushButton("مزامنة توفر الأدوية - إعداد ومراجعة")
            btn.clicked.connect(lambda: open_settings(self))
            self._settings_layout.insertWidget(1, btn)

    def _cloud_status_text(self):
        import catalog_writer
        text = super()._cloud_status_text()
        if catalog_writer.is_signed_in():
            return "Catalog writer session active; upload depends on server authorization.\n" + text
        return (
            "Catalog upload paused. Use catalog_writer_launcher.py to sign in. "
            "Local changes remain saved; catalog downloads still work.\n"
            + text.replace(
                "المزامنة مفعّلة — أي صنف جديد أو معدّل يُرفع للسحابة تلقائياً.",
                "قراءة الكتالوج مفعّلة؛ الرفع يحتاج جلسة محرر.",
            )
        )


def main():
    base.App = AvailabilityApp
    base.main()


if __name__ == "__main__":
    main()
