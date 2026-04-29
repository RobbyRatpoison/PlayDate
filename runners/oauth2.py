"""
runners/oauth2.py — Generic OAuth2 helpers for PlayDate plugins.

Supports both form-body credentials (e.g. GOG) and HTTP Basic auth (e.g. Epic).
Token storage convention: config.json[config_key] must contain
  access_token, refresh_token, expires_at (Unix timestamp).
Other keys in config.json[config_key] are preserved on token refresh.
"""

import base64
import json
import logging
import time

import requests

log = logging.getLogger(__name__)


def _load_cfg():
    from config import CONFIG_PATH
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cfg(data):
    from config import CONFIG_PATH
    with open(CONFIG_PATH, 'w') as f:
        json.dump(data, f, indent=4)


def exchange_authorization_code(token_url, client_id, client_secret, code,
                                 redirect_uri=None, extra_headers=None,
                                 use_basic_auth=False):
    """
    Exchange an authorization code for access + refresh tokens.

    Returns the raw token response dict on success.
    Raises ValueError with an error message on failure.
    """
    headers = {'Accept': 'application/json'}
    if extra_headers:
        headers.update(extra_headers)

    data = {'grant_type': 'authorization_code', 'code': code}
    if redirect_uri:
        data['redirect_uri'] = redirect_uri

    if use_basic_auth:
        creds = base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()
        headers['Authorization'] = f'Basic {creds}'
    else:
        data['client_id'] = client_id
        data['client_secret'] = client_secret

    resp = requests.post(token_url, data=data, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise ValueError(f'Token exchange failed (HTTP {resp.status_code}): {resp.text[:200]}')
    return resp.json()


def refresh_access_token(token_url, client_id, client_secret, refresh_token,
                         extra_headers=None, use_basic_auth=False):
    """
    Use a refresh token to obtain a new access token.

    Returns the raw token response dict on success.
    Raises ValueError with an error message on failure.
    """
    headers = {'Accept': 'application/json'}
    if extra_headers:
        headers.update(extra_headers)

    data = {'grant_type': 'refresh_token', 'refresh_token': refresh_token}

    if use_basic_auth:
        creds = base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()
        headers['Authorization'] = f'Basic {creds}'
    else:
        data['client_id'] = client_id
        data['client_secret'] = client_secret

    resp = requests.post(token_url, data=data, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise ValueError(f'Token refresh failed (HTTP {resp.status_code}): {resp.text[:200]}')
    return resp.json()


def get_valid_session(config_key, token_url, client_id, client_secret,
                      extra_headers=None, use_basic_auth=False):
    """
    Return a requests.Session with a valid Bearer token for config_key.

    Reads config.json[config_key] for stored tokens. Auto-refreshes if the
    token has expired or is within 60 seconds of expiry. Writes updated tokens
    back to config.json[config_key] (other keys in that section are preserved).

    Returns None if not connected or if refresh fails.
    """
    cfg = _load_cfg()
    tokens = cfg.get(config_key, {})
    if not tokens.get('access_token') or not tokens.get('refresh_token'):
        return None

    if int(time.time()) >= tokens.get('expires_at', 0) - 60:
        try:
            new_tokens = refresh_access_token(
                token_url, client_id, client_secret, tokens['refresh_token'],
                extra_headers=extra_headers, use_basic_auth=use_basic_auth,
            )
        except ValueError as e:
            log.warning(f'oauth2 [{config_key}]: token refresh failed — {e}')
            return None
        except Exception as e:
            log.error(f'oauth2 [{config_key}]: unexpected refresh error — {e}')
            return None

        expires_at = int(time.time()) + int(new_tokens.get('expires_in', 3600))
        cfg = _load_cfg()
        existing = cfg.get(config_key, {})
        existing['access_token']  = new_tokens['access_token']
        existing['refresh_token'] = new_tokens.get('refresh_token', tokens['refresh_token'])
        existing['expires_at']    = expires_at
        cfg[config_key] = existing
        _save_cfg(cfg)

        tokens = existing

    session = requests.Session()
    if extra_headers:
        session.headers.update(extra_headers)
    session.headers['Authorization'] = f'Bearer {tokens["access_token"]}'
    return session
