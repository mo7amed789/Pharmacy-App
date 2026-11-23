"""Synthetic key classification, never real credentials or network."""
import base64,json,unittest
from supabase_client import browser_safe_key
class PublicKeyBoundary(unittest.TestCase):
 def test_public_key_forms_only(self):
  def jwt(role):
   payload=base64.urlsafe_b64encode(json.dumps({'role':role}).encode()).decode().rstrip('=')
   return 'synthetic.'+payload+'.not-a-signature'
  self.assertTrue(browser_safe_key('sb_publishable_synthetic-test'))
  self.assertTrue(browser_safe_key(jwt('anon')))
  for value in [jwt('service_role'),jwt('authenticated'),'sb_secret_synthetic-test','malformed',None,'']:
   self.assertFalse(browser_safe_key(value))
 def test_mobile_handler_refuses_privileged_configuration(self):
  from pathlib import Path
  source=(Path(__file__).resolve().parents[1]/'mobile_server.py').read_text(encoding='utf-8')
  start=source.index('        def _api_cloud_config(');end=source.index('        def _api_drugs(',start)
  self.assertIn('browser_safe_key(key)',source[start:end])
