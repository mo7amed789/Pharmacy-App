import unittest
from unittest.mock import patch
import firewall

class FirewallScopeTests(unittest.TestCase):
    def test_new_rules_local_subnet_only(self):
        with patch('firewall._run_netsh', return_value=(True,'OK','')) as run:
            self.assertTrue(firewall._add_single_rule('synthetic',8080,'public')[0])
            self.assertIn('remoteip=localsubnet',run.call_args.args[0])

    def test_all_known_existing_names_are_narrowed(self):
        with patch('firewall.is_windows',return_value=True), patch('firewall._rule_info',return_value=(True,{'public'})), patch('firewall._run_netsh',return_value=(True,'OK','')) as run:
            self.assertTrue(firewall.restrict_existing_rules()[0])
            self.assertEqual(5,run.call_count)
            self.assertTrue(all('remoteip=localsubnet' in c.args[0] for c in run.call_args_list))

    def test_failed_scope_update_does_not_report_success(self):
        with patch('firewall.is_windows',return_value=True), patch('firewall._rule_info',return_value=(True,{'public'})), patch('firewall._run_netsh',return_value=(False,'','denied')):
            self.assertFalse(firewall.add_rule()[0])

if __name__=='__main__': unittest.main()
