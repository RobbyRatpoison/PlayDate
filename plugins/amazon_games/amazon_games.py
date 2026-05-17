"""
Amazon Games plugin for PlayDate.

Sync sources (tried in order):
  1. Nile JSON files  -- written by Heroic Games Launcher / Nile client; zero auth needed.
  2. Amazon GraphQL API -- requires 'at-main' session cookie from amazon.com.

Only imports games that play through the Amazon Games Launcher itself (productLine
"Twitch:FuelGame").  Games that are just Steam/GOG/etc. keys are skipped since
those belong to those platforms' libraries.
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import requests

from config import load_config, _save_config_data
from database import get_db, next_negative_appid, update_game_data

log = logging.getLogger(__name__)

GRAPHQL_URL = 'https://gaming.amazon.com/graphql'
HOME_URL    = 'https://gaming.amazon.com/home'

# Nile (Heroic backend) library file locations
NILE_PATHS = [
    os.path.expanduser('~/.config/nile/library.json'),
    os.path.expanduser('~/.config/heroic/nile_config/nile/library.json'),
    os.path.expanduser('~/.var/app/com.heroicgameslauncher.hgl/config/heroic/nile_config/nile/library.json'),
]
NILE_INSTALLED_PATHS = [
    os.path.expanduser('~/.config/nile/installed.json'),
    os.path.expanduser('~/.config/heroic/nile_config/nile/installed.json'),
    os.path.expanduser('~/.var/app/com.heroicgameslauncher.hgl/config/heroic/nile_config/nile/installed.json'),
]

_sync_state = {'running': False, 'status': '', 'added': 0, 'updated': 0, 'error': None, 'source': None}
_sync_lock  = threading.Lock()


# ── Config ──────────────────────────────────────────────────────────────────────

def _cfg():
    return (load_config() or {}).get('amazon_games', {})

def _save_cfg(data):
    cfg = load_config() or {}
    cfg['amazon_games'] = data
    _save_config_data(cfg)

def is_connected():
    return bool(_cfg().get('at_token')) or bool(find_nile_library())

def get_username():
    return _cfg().get('username', 'Connected')

def find_nile_library():
    for p in NILE_PATHS:
        if os.path.isfile(p):
            return p
    return None

def find_nile_installed():
    for p in NILE_INSTALLED_PATHS:
        if os.path.isfile(p):
            return p
    return None

def nile_detected():
    return find_nile_library() is not None


# ── Auth ────────────────────────────────────────────────────────────────────────

def _req_headers(at_token=None, csrf_token=''):
    t = at_token or _cfg().get('at_token', '')
    h = {
        'Cookie': f'at-main={t}',
        'User-Agent': 'Mozilla/5.0 (compatible; PlayDate)',
        'Accept': 'application/json',
    }
    if csrf_token:
        h['x-amz-csrf-token'] = csrf_token
    return h


def _fetch_csrf(at_token):
    """GET gaming.amazon.com/home and extract the CSRF token."""
    try:
        resp = requests.get(
            HOME_URL,
            headers={
                'Cookie': f'at-main={at_token}',
                'User-Agent': 'Mozilla/5.0 (compatible; PlayDate)',
            },
            timeout=15,
        )
        csrf = resp.headers.get('x-amz-csrf-token', '')
        if not csrf:
            m = re.search(r'"csrf[_-]?[Tt]oken"\s*:\s*"([^"]+)"', resp.text)
            if m:
                csrf = m.group(1)
        if not csrf:
            m = re.search(r'csrfToken\s*=\s*[\'"]([^\'"]+)[\'"]', resp.text)
            if m:
                csrf = m.group(1)
        return csrf
    except Exception as e:
        log.warning(f'Amazon: CSRF fetch failed: {e}')
        return ''


def connect(at_token):
    at_token = at_token.strip().strip('"')
    csrf = _fetch_csrf(at_token)
    if not csrf:
        log.warning('Amazon: could not extract CSRF token — will attempt API without it')

    result = _graphql_query(at_token, csrf, page_size=1)
    if result is None:
        return False, 'Could not connect to Amazon Games — check your at-main cookie.'
    username = 'Connected'
    _save_cfg({'at_token': at_token, 'username': username})
    log.info('Amazon Games connected via API')
    return True, username


def disconnect():
    cfg = load_config() or {}
    cfg.pop('amazon_games', None)
    _save_config_data(cfg)


# ── GraphQL ─────────────────────────────────────────────────────────────────────

_LIBRARY_QUERY = """
query GetOwnershipData($pageSize: Int, $nextToken: String) {
    getOwnershipData(input: {pageSize: $pageSize, nextToken: $nextToken}) {
        ... on GetOwnershipDataSuccessful {
            owned {
                id
                benefit {
                    id
                    title
                    isIGC
                    productLine
                    assets {
                        type
                        purpose
                        url
                    }
                }
            }
            nextToken
        }
        ... on GetOwnershipDataFailed {
            reason
        }
    }
}
"""


def _graphql_query(at_token, csrf_token, page_size=50, next_token=None):
    """Execute one page of the ownership GraphQL query. Returns data dict or None."""
    variables = {'pageSize': page_size}
    if next_token:
        variables['nextToken'] = next_token
    try:
        resp = requests.post(
            GRAPHQL_URL,
            json={'query': _LIBRARY_QUERY, 'variables': variables},
            headers=_req_headers(at_token, csrf_token),
            timeout=20,
        )
        if not resp.ok:
            log.warning(f'Amazon GraphQL HTTP {resp.status_code}')
            return None
        data = resp.json()
        log.debug(f'Amazon GraphQL response keys: {list(data.keys())}')
        return data
    except Exception as e:
        log.warning(f'Amazon GraphQL error: {e}')
        return None


# ── Library sync ────────────────────────────────────────────────────────────────

def get_sync_state():
    return dict(_sync_state)


def start_library_sync(source='auto'):
    with _sync_lock:
        if _sync_state['running']:
            return {'status': 'already_running'}
        _sync_state.update({
            'running': True, 'status': 'Starting…',
            'added': 0, 'updated': 0, 'error': None, 'source': source,
        })
    threading.Thread(target=_run_sync, args=(source,), daemon=True).start()
    return {'status': 'started'}


def _run_sync(source):
    global _sync_state
    try:
        nile_path = find_nile_library()
        if source == 'auto':
            source = 'nile' if nile_path else 'api'

        if source == 'nile' and nile_path:
            _sync_from_nile(nile_path)
        else:
            _sync_from_api()
    except Exception as e:
        log.error(f'Amazon sync error: {e}', exc_info=True)
        _sync_state.update({'running': False, 'status': '', 'error': str(e)})


def _sync_from_nile(library_path):
    global _sync_state
    _sync_state['status'] = 'Reading Nile library…'
    log.info(f'Amazon: syncing from Nile at {library_path}')

    try:
        with open(library_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        raise RuntimeError(f'Could not read Nile library file: {e}')

    # Nile library.json is a list of game objects
    if isinstance(raw, dict):
        games = raw.get('library', raw.get('games', []))
    else:
        games = raw

    # Load installed info for install flags
    installed_ids = set()
    nile_inst = find_nile_installed()
    if nile_inst:
        try:
            with open(nile_inst, 'r', encoding='utf-8') as f:
                inst_raw = json.load(f)
            if isinstance(inst_raw, list):
                installed_ids = {g.get('id') or g.get('appName', '') for g in inst_raw}
            elif isinstance(inst_raw, dict):
                installed_ids = set(inst_raw.keys())
        except Exception as e:
            log.warning(f'Amazon: could not read Nile installed.json: {e}')

    db = get_db()
    existing = {
        row['platform_id']: row['appid']
        for row in db.execute(
            "SELECT appid, platform_id FROM games WHERE platform='amazon_games'"
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

    for game in games:
        # Nile entries can be nested under 'product' or flat
        product = game.get('product') or game
        game_id = (
            game.get('id')
            or product.get('id')
            or product.get('asin')
            or ''
        )
        game_id = str(game_id).strip()
        if not game_id:
            continue

        name = (
            product.get('title')
            or (product.get('productDetail') or {}).get('palatinateTitle')
            or game_id
        ).strip()

        slug = (
            product.get('productSlug')
            or product.get('slug')
            or ''
        ).strip()

        if game_id in blacklisted:
            continue

        installed = 1 if game_id in installed_ids else 0

        if game_id in existing:
            update_game_data(existing[game_id], installed=installed)
            updated += 1
        else:
            appid = next_negative_appid(db)
            db.execute(
                """INSERT OR IGNORE INTO games
                   (appid, name, platform, platform_id, platform_slug,
                    date_added, completion_status, installed,
                    art_fetched, meta_fetched, cheevos_fetched,
                    protondb_fetched, hltb_fetched)
                   VALUES (?, ?, 'amazon_games', ?, ?,
                           ?, 'Never Played', ?,
                           '0', '0', '0', '0', '0')""",
                (appid, name, game_id, slug, int(time.time()), installed),
            )
            db.commit()
            existing[game_id] = appid
            added += 1
            log.info(f'Amazon (Nile): added {name!r}')

    db.close()
    _sync_state.update({
        'running': False,
        'status': f'Done (via Nile) — {added} added, {updated} updated.',
        'added': added, 'updated': updated,
    })
    log.info(f'Amazon Nile sync complete: {added} added, {updated} updated')


def _sync_from_api():
    global _sync_state
    at_token = _cfg().get('at_token', '')
    if not at_token:
        raise RuntimeError('Not connected — please connect your Amazon account first.')

    _sync_state['status'] = 'Fetching CSRF token…'
    csrf = _fetch_csrf(at_token)

    db = get_db()
    existing = {
        row['platform_id']: row['appid']
        for row in db.execute(
            "SELECT appid, platform_id FROM games WHERE platform='amazon_games'"
        ).fetchall()
    }
    blacklisted = {
        row[0]
        for row in db.execute(
            "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
        ).fetchall()
    }

    added      = 0
    updated    = 0
    next_token = None
    page       = 1

    while True:
        _sync_state['status'] = f'Fetching library page {page}…'
        data = _graphql_query(at_token, csrf, page_size=50, next_token=next_token)
        if data is None:
            raise RuntimeError('API request failed — try reconnecting.')

        ownership = (
            (data.get('data') or {}).get('getOwnershipData')
            or data.get('getOwnershipData')
            or {}
        )

        if 'reason' in ownership:
            raise RuntimeError(f'API returned failure: {ownership["reason"]}')

        if not ownership:
            log.warning(f'Amazon API: unexpected response shape. Keys: {list(data.keys())}')
            break

        owned_list = ownership.get('owned') or []
        log.info(f'Amazon API page {page}: {len(owned_list)} items')

        for entry in owned_list:
            benefit    = entry.get('benefit') or {}
            product_line = benefit.get('productLine', '')

            # Only import games that require the Amazon launcher, not external keys
            if product_line and product_line not in ('Twitch:FuelGame', 'IGC', ''):
                log.debug(f'Amazon: skipping productLine={product_line!r}')
                continue

            game_id = str(entry.get('id') or benefit.get('id') or '').strip()
            if not game_id:
                continue

            name = (benefit.get('title') or game_id).strip()
            slug = ''

            if game_id in blacklisted:
                continue

            if game_id in existing:
                updated += 1
            else:
                appid = next_negative_appid(db)
                db.execute(
                    """INSERT OR IGNORE INTO games
                       (appid, name, platform, platform_id, platform_slug,
                        date_added, completion_status, installed,
                        art_fetched, meta_fetched, cheevos_fetched,
                        protondb_fetched, hltb_fetched)
                       VALUES (?, ?, 'amazon_games', ?, ?,
                               ?, 'Never Played', 0,
                               '0', '0', '0', '0', '0')""",
                    (appid, name, game_id, slug, int(time.time())),
                )
                db.commit()
                existing[game_id] = appid
                added += 1
                log.info(f'Amazon API: added {name!r}')

        next_token = ownership.get('nextToken')
        if not next_token or not owned_list:
            break
        page += 1
        time.sleep(0.5)

    db.close()
    _sync_state.update({
        'running': False,
        'status': f'Done (via API) — {added} added, {updated} already in library.',
        'added': added, 'updated': updated,
    })
    log.info(f'Amazon API sync complete: {added} added, {updated} existing')


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
        log.warning(f'Amazon: failed to open browser: {e}')


def launch_game(appid):
    db  = get_db()
    row = db.execute("SELECT platform_id FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    game_id = (row['platform_id'] if row else '') or ''
    # Try Heroic/Nile launch if available
    if _try_nile_launch(game_id):
        return {'status': 'success'}
    # Fall back to opening the Prime Gaming library in the browser
    _open_browser('https://gaming.amazon.com/home')
    return {'status': 'success'}


def _try_nile_launch(game_id):
    """Attempt to launch via Nile CLI if installed. Returns True on success."""
    if not game_id:
        return False
    for nile_bin in ['nile', os.path.expanduser('~/.local/bin/nile')]:
        try:
            subprocess.Popen([nile_bin, 'launch', game_id])
            log.info(f'Amazon: launched {game_id!r} via Nile')
            return True
        except FileNotFoundError:
            continue
        except Exception as e:
            log.warning(f'Amazon: Nile launch failed: {e}')
    return False
