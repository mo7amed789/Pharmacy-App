import io
import json
import unittest
from unittest.mock import patch
import catalog_writer
import supabase_client


class WriterTests(unittest.TestCase):
    def tearDown(self):
        catalog_writer.sign_out()

    def test_no_anonymous_fallback_for_catalog_writes(self):
        c = supabase_client.SupabaseClient(url='https://test.supabase.co', key='sb_publishable_fake')
        with patch('urllib.request.urlopen') as call:
            with self.assertRaises(supabase_client.SupabaseError):
                c.upsert_products([{'trade_en': 'Synthetic'}])
            with self.assertRaises(supabase_client.SupabaseError):
                c.delete_product(1)
            call.assert_not_called()

    def test_sign_in_uses_session_only_and_same_project(self):
        response = io.BytesIO(json.dumps({'access_token':'fake-owner-session','expires_in':3600,
                                         'refresh_token':'discard-this'}).encode())
        with patch('supabase_client.load_config', return_value=('https://test.supabase.co','sb_publishable_fake')):
            with patch('urllib.request.urlopen', return_value=response):
                catalog_writer.sign_in('owner@example.invalid','synthetic-password')
        self.assertTrue(catalog_writer.is_signed_in())
        self.assertEqual(catalog_writer.access_token('https://test.supabase.co'),'fake-owner-session')
        with self.assertRaises(supabase_client.SupabaseError):
            catalog_writer.access_token('https://different.supabase.co')
        c = supabase_client.SupabaseClient(url='https://test.supabase.co', key='sb_publishable_fake')
        empty = io.BytesIO(b'')
        empty.headers = {}
        with patch('urllib.request.urlopen', return_value=empty) as call:
            c.upsert_products([{'trade_en':'Synthetic'}])
            self.assertEqual(call.call_args.args[0].get_header('Authorization'),'Bearer fake-owner-session')
        catalog_writer.sign_out()
        self.assertFalse(catalog_writer.is_signed_in())

    def test_plain_http_or_privileged_key_cannot_sign_in(self):
        for url,key in [('http://test.supabase.co','sb_publishable_fake'),
                        ('https://test.supabase.co','sb_secret_fake')]:
            with patch('supabase_client.load_config', return_value=(url,key)):
                with self.assertRaises(supabase_client.SupabaseError):
                    catalog_writer.sign_in('owner@example.invalid','fake')

    def test_expired_session_rejected(self):
        with patch('catalog_writer._session', {'url':'https://test.supabase.co','token':'fake','expires_at':0}):
            self.assertFalse(catalog_writer.is_signed_in())
            with self.assertRaises(supabase_client.SupabaseError):
                catalog_writer.access_token('https://test.supabase.co')

if __name__ == '__main__':
    unittest.main()

class WriterLauncherTests(unittest.TestCase):
    def test_launcher_preserves_availability_extension_and_clears_session(self):
        import sys
        import types
        fake = types.ModuleType('availability_launcher')
        fake.main = unittest.mock.Mock()
        with patch.dict(sys.modules, {'availability_launcher': fake}):
            import importlib.util
            from pathlib import Path
            spec = importlib.util.spec_from_file_location('writer_launcher_test', str(Path(__file__).parents[1] / 'catalog_writer_launcher.py'))
            launcher = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(launcher)
            with patch('builtins.input', return_value='owner@example.invalid'), patch('getpass.getpass', return_value='synthetic'), patch('catalog_writer.sign_in') as sign_in, patch('catalog_writer.sign_out') as sign_out:
                launcher.run()
                sign_in.assert_called_once()
                fake.main.assert_called_once()
                sign_out.assert_called_once()
