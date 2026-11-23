"""Launcher/admin extension smoke test without starting billing or network."""
import os
import unittest
from unittest.mock import Mock,patch
try:
 import tkinter
 import availability_launcher as launcher
except ImportError:
 launcher=None

@unittest.skipIf(launcher is None,'Tkinter unavailable')
class LauncherTests(unittest.TestCase):
 def test_default_launcher_subclasses_base_app(self):
  import main
  self.assertTrue(issubclass(launcher.AvailabilityApp,main.App))
 def test_worker_uses_separate_sidecar(self):
  app=launcher.AvailabilityApp.__new__(launcher.AvailabilityApp)
  app.db=Mock(path='synthetic.db')
  with patch.object(launcher.base.App,'__init__',return_value=None),patch('availability_sync.start_worker') as worker:
   launcher.AvailabilityApp.__init__(app)
   worker.assert_called_once_with('synthetic.db','synthetic.db.availability.sqlite3')
