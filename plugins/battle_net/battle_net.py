"""
battle_net.py — Battle.net integration for PlayDate.

Auth uses Blizzard's official OAuth2 API (develop.battle.net).
Users must register a free Battle.net API client and supply their own
client_id + client_secret. Tokens stored under config.json["battle_net"].
Credentials stored under config.json["battle_net_credentials"].

Redirect URI to configure in the Battle.net developer portal: http://localhost/
"""

import logging
import os
import threading
import time

import requests
from config import CONFIG_PATH, BASE_DIR, load_config, _save_config_data
from database import next_negative_appid

log = logging.getLogger(__name__)

# ── Battle.net API constants ──────────────────────────────────────────────────
BNET_AUTH_BASE  = 'https://oauth.battle.net'
BNET_TOKEN_URL  = 'https://oauth.battle.net/token'
BNET_REDIRECT   = 'http://localhost/'

# Default to US; API calls use the same token regardless of region
BNET_API_BASE   = 'https://us.api.blizzard.com'

# Known product code → display name mapping
BNET_PRODUCTS = {
    'WoW':   'World of Warcraft',
    'WoWC':  'WoW Classic',
    'WoWCE': 'WoW Classic Era',
    'D4':    'Diablo IV',
    'D3':    'Diablo III',
    'D2':    'Diablo II: Resurrected',
    'D1':    'Diablo',
    'OSI':   'Diablo (Classic)',
    'S2':    'StarCraft II',
    'S1':    'StarCraft Remastered',
    'SC':    'StarCraft',
    'HS1':   'StarCraft (Classic)',
    'W3':    'Warcraft III: Reforged',
    'W2':    'Warcraft II: BattleNet Edition',
    'W1':    'Warcraft: Orcs & Humans',
    'Pro':   'Overwatch 2',
    'WTCG':  'Hearthstone',
    'Hero':  'Heroes of the Storm',
    'Bots':  'Call of Duty: Black Ops Cold War',
    'VIPR':  'Call of Duty: Vanguard',
    'ODIN':  'Call of Duty: Modern Warfare',
    'LAZR':  'Call of Duty: Black Ops 4',
    'FORE':  'Call of Duty 4: Modern Warfare Remastered',
    'ZEUS':  'Call of Duty: Modern Warfare Remastered',
    'WLBY':  "Crash Bandicoot 4: It's About Time",
}

# Genres/tags for known products (best effort)
BNET_GENRES = {
    'WoW':   'MMO,RPG', 'WoWC': 'MMO,RPG', 'WoWCE': 'MMO,RPG',
    'D4':    'Action,RPG', 'D3': 'Action,RPG', 'D2': 'Action,RPG',
    'D1':    'Action,RPG', 'OSI': 'Action,RPG',
    'S2':    'Strategy,RTS', 'S1': 'Strategy,RTS', 'SC': 'Strategy,RTS',
    'HS1':   'Strategy,RTS',
    'W3':    'Strategy,RTS', 'W2': 'Strategy,RTS', 'W1': 'Strategy,RTS',
    'Pro':   'Action,FPS,Multiplayer',
    'WTCG':  'Card Game,Strategy',
    'Hero':  'MOBA,Action',
    'Bots':  'Action,FPS,Multiplayer',
    'VIPR':  'Action,FPS,Multiplayer',
    'ODIN':  'Action,FPS,Multiplayer',
    'LAZR':  'Action,FPS,Multiplayer',
    'FORE':  'Action,FPS,Multiplayer',
    'ZEUS':  'Action,FPS,Multiplayer',
}

BNET_PUBLISHERS = 'Blizzard Entertainment'

VERTICAL_DIR   = os.path.join(BASE_DIR, 'static', 'img', 'library', 'vertical')
HORIZONTAL_DIR = os.path.join(BASE_DIR, 'static', 'img', 'library', 'horizontal')


# ── Credential storage ────────────────────────────────────────────────────────

def load_credentials():
    """Return {'client_id': ..., 'client_secret': ...} or None."""
    data = (load_config() or {}).get('battle_net_credentials', {})
    if data.get('client_id'):
        return data
    return None


def save_credentials(client_id, client_secret):
    cfg = load_config() or {}
    cfg['battle_net_credentials'] = {
        'client_id':     client_id.strip(),
        'client_secret': client_secret.strip(),
    }
    _save_config_data(cfg)


def credentials_configured():
    return load_credentials() is not None


# ── Token storage ─────────────────────────────────────────────────────────────

def load_bnet_tokens():
    data = (load_config() or {}).get('battle_net', {})
    if data.get('access_token') and data.get('refresh_token'):
        return data
    return None


def is_connected():
    return load_bnet_tokens() is not None


def get_display_name():
    tokens = load_bnet_tokens()
    return (tokens or {}).get('battletag') or (tokens or {}).get('display_name')


def clear_bnet_tokens():
    data = load_config() or {}
    data.pop('battle_net', None)
    _save_config_data(data)


# ── Auth flow ─────────────────────────────────────────────────────────────────

def get_auth_url():
    creds = load_credentials()
    if not creds:
        return None
    from urllib.parse import urlencode
    params = urlencode({
        'client_id':     creds['client_id'],
        'scope':         'openid',
        'redirect_uri':  BNET_REDIRECT,
        'response_type': 'code',
    })
    return f'{BNET_AUTH_BASE}/authorize?{params}'


def _extract_code(raw):
    raw = raw.strip()
    if '://' in raw or raw.startswith('http'):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(raw).query)
        code = ((qs.get('code') or [''])[0]).strip()
        if code:
            return code
    if raw and ' ' not in raw:
        return raw
    return ''


def exchange_code(raw_input):
    """
    Exchange a Battle.net authorization code for tokens.
    Returns (True, battletag) on success, (False, error_msg) on failure.
    """
    code = _extract_code(raw_input)
    if not code:
        return False, 'Could not extract an authorization code from the input'

    creds = load_credentials()
    if not creds:
        return False, 'Battle.net credentials not configured'

    try:
        resp = requests.post(
            BNET_TOKEN_URL,
            data={
                'grant_type':   'authorization_code',
                'code':          code,
                'redirect_uri':  BNET_REDIRECT,
            },
            auth=(creds['client_id'], creds['client_secret']),
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        if resp.status_code != 200:
            return False, f'Token exchange failed (HTTP {resp.status_code}): {resp.text[:200]}'
        data = resp.json()
    except Exception as e:
        return False, str(e)

    access_token  = data.get('access_token', '')
    refresh_token = data.get('refresh_token', '')
    expires_in    = int(data.get('expires_in', 86400))
    expires_at    = int(time.time()) + expires_in
    sub           = data.get('sub', '')

    if not access_token:
        return False, 'No access token in Battle.net response'

    # Fetch battletag from userinfo
    battletag = ''
    try:
        r = requests.get(
            f'{BNET_AUTH_BASE}/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10,
        )
        if r.status_code == 200:
            info = r.json()
            battletag = info.get('battletag', '') or info.get('sub', '')
    except Exception as e:
        log.warning(f'Battle.net: could not fetch userinfo: {e}')

    cfg = load_config() or {}
    cfg['battle_net'] = {
        'access_token':  access_token,
        'refresh_token': refresh_token,
        'expires_at':    expires_at,
        'battletag':     battletag,
        'sub':           sub,
    }
    _save_config_data(cfg)
    log.info(f'Battle.net auth: connected as {battletag!r}')
    return True, battletag or 'Battle.net Account'


def get_valid_session():
    """Return a requests.Session with a valid Battle.net Bearer token, or None."""
    creds = load_credentials()
    if not creds:
        return None
    from runners.oauth2 import get_valid_session as _get_session
    return _get_session(
        'battle_net', BNET_TOKEN_URL, creds['client_id'], creds['client_secret'],
        use_basic_auth=True,
    )


# ── Library sync ──────────────────────────────────────────────────────────────

_sync_state = {
    'running': False, 'phase': None, 'done': 0, 'total': 0, 'current_game': '',
    'new_games': 0, 'total_games': 0, 'duplicates_detected': 0, 'error': None,
}
_sync_lock   = threading.Lock()
_sync_cancel = threading.Event()


def get_sync_state():
    with _sync_lock:
        return dict(_sync_state)


def start_library_sync():
    with _sync_lock:
        if _sync_state['running']:
            return {'status': 'already_running'}
        _sync_cancel.clear()
        _sync_state.update({
            'running': True, 'phase': 'fetching_library', 'done': 0, 'total': 0,
            'current_game': '', 'new_games': 0, 'total_games': 0,
            'duplicates_detected': 0, 'error': None,
        })
    threading.Thread(target=_run_sync_library, daemon=True).start()
    return {'status': 'started'}


def cancel_library_sync():
    _sync_cancel.set()


def _run_sync_library():
    try:
        _do_sync_library()
    except Exception as e:
        log.error(f'Battle.net library sync thread: {e}', exc_info=True)
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error', 'error': str(e)})


def _fetch_licenses(session):
    """
    Fetch owned game licenses from Battle.net.
    Returns list of license dicts or None on error.
    """
    try:
        resp = session.get(f'{BNET_API_BASE}/account/user/licenses', timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('licenses', data) if isinstance(data, dict) else data
        log.warning(f'Battle.net licenses HTTP {resp.status_code}: {resp.text[:200]}')
    except Exception as e:
        log.warning(f'Battle.net licenses fetch failed: {e}')
    return None


def _do_sync_library():
    from database import get_db, update_game_data as _update_game_data
    from datetime import datetime, timezone, date as _date

    session = get_valid_session()
    if not session:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error',
                                'error': 'Not connected to Battle.net — please reconnect'})
        return

    licenses = _fetch_licenses(session)
    if licenses is None:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error',
                                'error': 'Failed to fetch Battle.net licenses'})
        return

    log.info(f'Battle.net sync: {len(licenses)} licenses received')

    db = get_db()
    try:
        existing = {row['platform_id'] for row in db.execute(
            "SELECT platform_id FROM games WHERE platform = 'battle_net'"
        ).fetchall()}
        blacklisted = {
            row[0] for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()
        }
    finally:
        db.close()

    # Each license has a productCode; filter to known products and skip existing
    new_items = []
    seen = set()
    for lic in licenses:
        product_code = (lic.get('productCode') or lic.get('product') or '').strip()
        if not product_code or product_code in seen:
            continue
        seen.add(product_code)
        # Only import games we have a name for; skip engine/SDK/other licenses
        if product_code not in existing and product_code not in blacklisted:
            new_items.append((product_code, lic))

    total_new = len(new_items)
    log.info(f'Battle.net sync: {total_new} new games (skipped {len(licenses) - total_new} existing/duplicate)')

    with _sync_lock:
        _sync_state.update({'phase': 'processing', 'done': 0, 'total': total_new, 'current_game': ''})

    today_ts        = int(datetime.now(timezone.utc).timestamp())
    today           = _date.today().isoformat()
    new_games_count = 0

    db = get_db()
    try:
        for product_code, lic in new_items:
            if _sync_cancel.is_set():
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'stopped',
                                        'new_games': new_games_count, 'total_games': len(licenses)})
                return

            name = BNET_PRODUCTS.get(product_code, product_code)

            with _sync_lock:
                _sync_state['current_game'] = name

            # Purchase/grant date if available
            date_str = (lic.get('createdAt') or lic.get('grantedAt') or
                        lic.get('purchaseDate') or '').strip()
            date_ts = today_ts
            if date_str:
                try:
                    from datetime import datetime as _dt
                    dt = _dt.fromisoformat(date_str.replace('Z', '+00:00'))
                    date_ts = int(dt.timestamp())
                except Exception:
                    pass

            next_appid = next_negative_appid(db)
            db.execute(
                """INSERT OR IGNORE INTO games
                   (appid, name, platform, platform_id, date_added,
                    completion_status, installed,
                    art_fetched, meta_fetched, cheevos_fetched,
                    protondb_fetched, hltb_fetched)
                   VALUES (?, ?, 'battle_net', ?, ?,
                           'Never Played', 0,
                           '0', '0', '0', '0', '0')""",
                (next_appid, name, product_code, date_ts),
            )
            db.commit()

            meta = _build_metadata(product_code)
            meta['meta_fetched'] = today
            try:
                _update_game_data(next_appid, **meta)
            except Exception as e:
                log.warning(f'Battle.net metadata update failed for {name!r}: {e}')

            log.info(f'Battle.net sync: added {name!r} as appid {next_appid} ({product_code})')
            new_games_count += 1
            with _sync_lock:
                _sync_state['done'] += 1

            if _sync_cancel.is_set():
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'stopped',
                                        'new_games': new_games_count, 'total_games': len(licenses)})
                return
    finally:
        db.close()

    try:
        from .watcher import sync_bnet_install_status
        sync_bnet_install_status()
    except Exception as e:
        log.warning(f'Battle.net sync: install status refresh failed: {e}')

    from database import auto_detect_duplicates
    from plugins import get_platform_priority
    dupes = auto_detect_duplicates(platform_priority=get_platform_priority())

    with _sync_lock:
        _sync_state.update({
            'running': False, 'phase': 'done',
            'new_games': new_games_count, 'total_games': len(licenses),
            'duplicates_detected': dupes,
        })


def _build_metadata(product_code):
    """Build a metadata dict from our local knowledge of the product."""
    meta = {
        'publishers': BNET_PUBLISHERS,
        'developers': BNET_PUBLISHERS,
    }
    if product_code in BNET_GENRES:
        meta['genres'] = BNET_GENRES[product_code]
    return meta


# ── Single-game rescrape ──────────────────────────────────────────────────────

def scrape_single(appid):
    """Rebuild metadata for one Battle.net game from our local table. Returns dict or None."""
    from database import get_db
    db  = get_db()
    row = db.execute(
        "SELECT platform_id FROM games WHERE appid = ? AND platform = 'battle_net'",
        (appid,)
    ).fetchone()
    db.close()

    if not row or not row['platform_id']:
        return None

    from datetime import date
    meta = _build_metadata(row['platform_id'])
    meta['meta_fetched'] = date.today().isoformat()
    return meta


def fetch_description(appid, platform_id):
    """Battle.net has no public description API; return None to fall through to Steam."""
    return None
