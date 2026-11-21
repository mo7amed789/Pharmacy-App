"""Auto-update cadence, snooze and action gates. No network/real installs."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from database import DB
import updater
try:
    import main
except ImportError:
    main = None


class SnoozeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DB(os.path.join(self.tmp.name, 'test.db'))
        self.result = dict(status='update_available', latest=dict(sha='abc',message='demo'))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_snooze_persists_and_expires(self):
        self.assertTrue(updater.notification_due(self.db,self.result,100))
        updater.snooze_update(self.db,'abc',100)
        self.db.close();self.db=DB(os.path.join(self.tmp.name,'test.db'),init=False)
        self.assertFalse(updater.notification_due(self.db,self.result,101))
        self.assertFalse(updater.notification_due(self.db,self.result,100+86400-1))
        self.assertTrue(updater.notification_due(self.db,self.result,100+86400))
        self.assertTrue(updater.notification_due(self.db,dict(status='update_available',latest=dict(sha='def')),101))
        self.assertFalse(updater.notification_due(self.db,dict(status='error'),101))
        self.assertFalse(updater.notification_due(self.db,dict(status='up_to_date'),101))
        self.db.set_setting(updater.K_SNOOZE_UNTIL,'nan')
        self.assertTrue(updater.notification_due(self.db,self.result,101))


@unittest.skipIf(main is None,'Tkinter not installed')
class UpdateFlowTests(SnoozeTests):
    def app(self):
        app=main.App.__new__(main.App)
        app.root=MagicMock()
        app.root.after.return_value='timer'
        app.db=self.db
        app._pending_update=None
        app._update_check_busy=False
        app._update_installing=False
        app._update_restart_required=False
        app.is_admin=True
        app._ui_post=lambda fn:fn()
        app._show_update_notice=MagicMock()
        app.show_banner=MagicMock()
        app.cart=[];app.purchase_lines=[];app.mobile_server=None
        return app

    def background(self,work,done):
        try: result=work()
        except Exception as e:done(None,e)
        else:done(result,None)

    def test_hourly_schedule_and_no_auto_install(self):
        app=self.app()
        with patch('cloud_sync.run_in_background',side_effect=self.background),patch.object(updater,'check_for_update',return_value=self.result),patch.object(updater,'apply_update') as install:
            app._startup_update_check()
            app.root.after.assert_called_once_with(3600000,app._startup_update_check)
            app._show_update_notice.assert_called_once()
            install.assert_not_called()
            updater.snooze_update(self.db,'abc')
            app._show_update_notice.reset_mock()
            app._startup_update_check()
            app._show_update_notice.assert_not_called()
            app.update_check_now()
            app._show_update_notice.assert_called_once()
            install.assert_not_called()

    def test_offline_is_quiet_and_next_check_scheduled(self):
        app=self.app()
        with patch('cloud_sync.run_in_background',side_effect=self.background),patch.object(updater,'check_for_update',return_value=dict(status='error',error='offline')),patch.object(main.messagebox,'showerror') as error:
            app._startup_update_check()
            error.assert_not_called()
            app._show_update_notice.assert_not_called()
            self.assertFalse(app._update_check_busy)
            app.root.after.assert_called_once()

    def test_overlapping_check_and_install_are_blocked(self):
        app=self.app();app._update_check_busy=True
        with patch('cloud_sync.run_in_background') as run:
            app._run_update_check()
            run.assert_not_called()
        app._update_check_busy=False;app._update_installing=True
        with patch('cloud_sync.run_in_background') as run:
            app._run_update_check()
            run.assert_not_called()

    def test_no_install_on_cancel_and_guard_unsaved_work(self):
        app=self.app();app._pending_update=self.result['latest']
        with patch('cloud_sync.run_in_background') as run,patch.object(main.messagebox,'askyesno',return_value=False):
            app.update_apply_now()
            run.assert_not_called()
        app.cart=[1]
        with patch('cloud_sync.run_in_background') as run,patch.object(main.messagebox,'showinfo'):
            app.update_apply_now()
            run.assert_not_called()
        app.cart=[];app.mobile_server=SimpleNamespace(running=True)
        with patch('cloud_sync.run_in_background') as run,patch.object(main.messagebox,'showinfo'):
            app.update_apply_now()
            run.assert_not_called()

    def test_notice_does_not_require_lazy_settings(self):
        app=self.app();app._pending_update=self.result['latest']
        with patch('cloud_sync.run_in_background',side_effect=self.background),patch.object(main.messagebox,'askyesno',return_value=True),patch.object(main.messagebox,'showinfo'),patch.object(updater,'apply_update',return_value=(2,None)) as install:
            app.update_apply_now()
            self.assertEqual(install.call_count,1)
            self.assertEqual(install.call_args.args[2],'abc')
            self.assertTrue(app._update_restart_required)
            self.assertIsNone(app._pending_update)

    def test_install_failure_keeps_retry_target(self):
        app=self.app();app._pending_update=self.result['latest']
        with patch('cloud_sync.run_in_background',side_effect=self.background),patch.object(main.messagebox,'askyesno',return_value=True),patch.object(main.messagebox,'showerror'),patch.object(updater,'apply_update',side_effect=updater.UpdateError('offline')):
            app.update_apply_now()
            self.assertFalse(app._update_installing)
            self.assertEqual(app._pending_update['sha'],'abc')
            self.assertFalse(app._update_restart_required)

    def test_settings_refresh_keeps_pending(self):
        app=self.app();app._pending_update=self.result['latest'];app.btn_update_apply=MagicMock()
        app._refresh_update_ui()
        self.assertEqual(app._pending_update['sha'],'abc')
        app.btn_update_apply.config.assert_called_with(state='normal')

if __name__=='__main__':unittest.main()
