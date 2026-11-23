# -*- coding: utf-8 -*-
"""Supabase catalog writer session. Credentials and tokens stay in process memory."""
import json
import threading
import time
import urllib.error
import urllib.request

_lock = threading.Lock()
_session = None


def sign_out():
    global _session
    with _lock:
        _session = None


def is_signed_in():
    with _lock:
        return bool(_session and _session['expires_at'] > time.time() + 30)


def sign_in(email, password):
    """Authenticate with the public project key, never a service role credential."""
    import supabase_client
    global _session
    sign_out()
    url, key = supabase_client.load_config()
    if not url or not key or not supabase_client.browser_safe_key(key):
        raise supabase_client.SupabaseError('Catalog writer requires a public project API key.')
    if not url.startswith('https://'):
        raise supabase_client.SupabaseError('Catalog writer sign-in requires HTTPS.')
    data = json.dumps({'email': email.strip(), 'password': password}).encode('utf-8')
    req = urllib.request.Request(url + '/auth/v1/token?grant_type=password', data=data,
        headers={'apikey': key, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.load(response)
        token = result['access_token']
        expires = int(result['expires_in'])
        if not isinstance(token, str) or not token or expires <= 30:
            raise ValueError('Invalid session')
    except (urllib.error.URLError, ValueError, KeyError, TypeError, OSError):
        raise supabase_client.SupabaseError('Writer sign-in failed. Check the account and connection.') from None
    # Discard refresh token. Expired sessions require explicit sign-in again.
    with _lock:
        _session = {'url': url, 'token': token, 'expires_at': time.time() + expires}


def access_token(url):
    import supabase_client
    with _lock:
        if _session and _session['url'] == url and _session['expires_at'] > time.time() + 30:
            return _session['token']
    raise supabase_client.SupabaseError('Catalog upload requires writer sign-in. Local data is still saved.')
