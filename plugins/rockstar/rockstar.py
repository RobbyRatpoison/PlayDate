import logging
import os
import subprocess
import sys
import threading
import time

import requests

from config import load_config, _save_config_data
from database import get_db, next_negative_appid, update_game_data

log = logging.getLogger(__name__)

SC_API = 'https://api.rockstargames.com'

# Fallback map of Rockstar title IDs to display names, used when the API
# does not return a name for a title.
_TITLE_NAMES = {
    '3':  'Grand Theft Auto III – The Definitive Edition',
    '7':  'Grand Theft Auto: Vice City – The Definitive Edition',
    '11': 'Grand Theft Auto: San Andreas – The Definitive Edition',
    '13': 'Grand Theft Auto IV',
    '16': 'Max Payne',
    '17': 'Max Payne 2: The Fall of Max Payne',
    '18': 'Grand Theft Auto V',
    '24': 'Max Payne 3',
    '26': 'Midnight Club: Los Angeles',
    '29': 'GTA Online',
    '31': 'Grand Theft Auto: San Andreas',
    '35': 'L.A. Noire',
    '44': 'Bully: Scholarship Edition',
    '45': 'Manhunt',
    '51': 'Grand Theft Auto: The Trilogy – The Definitive Edition',
    '56': 'Red Dead Online',
    '57': 'Red Dead Redemption 2',
    '58': 'Grand Theft Auto VI',
}

_STORE_SLUGS = {
    '3':  'grand-theft-auto-iii-the-definitive-edition',
    '7':  'grand-theft-auto-vice-city-the-definitive-edition',
    '11': 'grand-theft-auto-san-andreas-the-definitive-edition',
    '13': 'grand-theft-auto-iv-complete-edition',
    '18': 'grand-theft-auto-v',
    '24': 'max-payne-3',
    '35': 'l-a-noire',
    '44': 'bully-scholarship-edition',
    '51': 'grand-theft-auto-the-trilogy-the-definitive-edition',
    '57': 'red-dead-redemption-2',
}

_sync_state = {'running': False, 'status': '', 'added': 0, 'updated': 0, 'error': None}
_sync_lock  = threading.Lock()


# ── Config ──────────────────────────────────────────────────────────────────────

def _cfg():
    return (load_config() or {}).get('rockstar', {})

def _save_cfg(data):
    cfg = load_config() or {}
    cfg['rockstar'] = data
    _save_config_data(cfg)

def is_connected():
    return bool(_cfg().get('auth_token'))

def get_username():
    return _cfg().get('username', 'Connected')


# ── Auth ────────────────────────────────────────────────────────────────────────

def _headers(token=None):
    t = token or _cfg().get('auth_token', '')
    return {
        'Authorization': f'Bearer {t}',
        'x-requested-with': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (compatible; PlayDate)',
        'Accept': 'application/json',
    }


def connect(token):
    token = token.strip().strip('"')
    try:
        resp = requests.get(
            f'{SC_API}/user/profile',
            headers=_headers(token),
            timeout=15,
        )
        if not resp.ok:
            return False, f'Could not connect to Rockstar Social Club (HTTP {resp.status_code}) — check your sc-auth-token.'
        data = resp.json()
        log.debug(f'Rockstar profile response keys: {list(data.keys())}')
    except Exception as e:
        return False, f'Connection failed: {e}'

    accounts = data.get('accounts') or []
    if accounts:
        acct     = accounts[0]
        username = ((acct.get('rockstarAccount') or {}).get('nickname')
                    or acct.get('displayName') or 'Connected')
    else:
        username = data.get('nickname') or data.get('displayName') or 'Connected'

    _save_cfg({'auth_token': token, 'username': username})
    log.info(f'Rockstar connected as {username!r}')
    return True, username


def disconnect():
    cfg = load_config() or {}
    cfg.pop('rockstar', None)
    _save_config_data(cfg)


# ── Library sync ────────────────────────────────────────────────────────────────

def get_sync_state():
    return dict(_sync_state)


def start_library_sync():
    with _sync_lock:
        if _sync_state['running']:
            return {'status': 'already_running'}
        _sync_state.update({
            'running': True, 'status': 'Starting…',
            'added': 0, 'updated': 0, 'error': None,
        })
    threading.Thread(target=_run_sync, daemon=True).start()
    return {'status': 'started'}


def _run_sync():
    global _sync_state
    try:
        _sync_state['status'] = 'Fetching library…'
        resp = requests.get(
            f'{SC_API}/user/profile',
            params={'includeTitleInfo': 'true'},
            headers=_headers(),
            timeout=20,
        )
        if not resp.ok:
            raise RuntimeError(f'API error (HTTP {resp.status_code}) — try reconnecting.')
        data = resp.json()
        log.debug(f'Rockstar profile/titleInfo response keys: {list(data.keys())}')

        # The API may nest title info under different keys depending on endpoint version.
        # Try several locations and log what we find for debugging.
        title_list = (
            data.get('titleInfo')
            or data.get('titleStates')
            or data.get('titles')
            or []
        )

        if not title_list:
            log.warning(f'Rockstar sync: no title list found. Top-level keys: {list(data.keys())}')
            raise RuntimeError(
                'No game titles returned. The API may require a different endpoint — '
                'check playdate.log for the response structure.'
            )

        log.info(f'Rockstar: {len(title_list)} titles in response')

        db = get_db()
        existing = {
            row['platform_id']: row['appid']
            for row in db.execute(
                "SELECT appid, platform_id FROM games WHERE platform='rockstar'"
            ).fetchall()
        }
        blacklisted = {
            row[0]
            for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()
        }

        added   = 0
        updated = 0

        for title in title_list:
            # Skip titles the user doesn't own (some endpoints include all titles)
            if title.get('owned') is False:
                continue

            title_id = str(title.get('titleId') or title.get('id') or '').strip()
            if not title_id:
                continue

            name = (
                title.get('titleName')
                or title.get('name')
                or _TITLE_NAMES.get(title_id)
                or f'Rockstar Title {title_id}'
            )
            slug = (
                title.get('slug')
                or title.get('titleSlug')
                or _STORE_SLUGS.get(title_id)
                or ''
            )

            _sync_state['status'] = f'Processing {name}…'

            if title_id in blacklisted:
                continue

            if title_id in existing:
                updated += 1
            else:
                appid = next_negative_appid(db)
                db.execute(
                    """INSERT OR IGNORE INTO games
                       (appid, name, platform, platform_id, platform_slug,
                        date_added, completion_status, installed,
                        art_fetched, meta_fetched, cheevos_fetched,
                        protondb_fetched, hltb_fetched)
                       VALUES (?, ?, 'rockstar', ?, ?,
                               ?, 'Never Played', 0,
                               '0', '0', '0', '0', '0')""",
                    (appid, name, title_id, slug, int(time.time())),
                )
                db.commit()
                existing[title_id] = appid
                added += 1
                log.info(f'Rockstar sync: added {name!r} (titleId={title_id})')

        db.close()
        _sync_state.update({
            'running': False,
            'status': f'Done — {added} added, {updated} already in library.',
            'added': added, 'updated': updated,
        })
        log.info(f'Rockstar sync complete: {added} added, {updated} existing')

    except Exception as e:
        log.error(f'Rockstar sync error: {e}', exc_info=True)
        _sync_state.update({'running': False, 'status': '', 'error': str(e)})


# ── Launch ──────────────────────────────────────────────────────────────────────

def _open_browser(url):
    try:
        if sys.platform == 'win32':
            os.startfile(url)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', url])
        else:
            subprocess.Popen(['xdg-open', url])
    except Exception as e:
        log.warning(f'Rockstar: failed to open browser: {e}')


def launch_game(appid):
    db  = get_db()
    row = db.execute("SELECT platform_id, platform_slug FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    title_id = (row['platform_id'] if row else '') or ''
    slug     = (row['platform_slug'] if row else '') or _STORE_SLUGS.get(title_id, '')
    url      = (f'https://store.rockstargames.com/game/{slug}' if slug
                else 'https://www.rockstargames.com/games')
    _open_browser(url)
    return {'status': 'success'}
