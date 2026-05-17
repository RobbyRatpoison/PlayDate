import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import requests

from config import load_config, _save_config_data
from database import get_db, next_negative_appid

log = logging.getLogger(__name__)

SHOWCASE_URL = 'https://www.indiegala.com/api/showcase/get-user-showcase'

_sync_state = {'running': False, 'status': '', 'added': 0, 'updated': 0, 'error': None}
_sync_lock  = threading.Lock()


# ── Config ──────────────────────────────────────────────────────────────────────

def _cfg():
    return (load_config() or {}).get('indiegala', {})

def _save_cfg(data):
    cfg = load_config() or {}
    cfg['indiegala'] = data
    _save_config_data(cfg)

def is_connected():
    return bool(_cfg().get('session_cookie'))

def get_username():
    return _cfg().get('username', 'Connected')


# ── Auth ────────────────────────────────────────────────────────────────────────

def _headers(cookie=None):
    c = cookie or _cfg().get('session_cookie', '')
    return {
        'Cookie': f'sessionid={c}',
        'User-Agent': 'Mozilla/5.0 (compatible; PlayDate)',
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
    }


def connect(cookie):
    cookie = cookie.strip().strip('"')
    try:
        resp = requests.get(
            SHOWCASE_URL,
            params={'page': 1},
            headers=_headers(cookie),
            timeout=15,
        )
        if not resp.ok:
            return False, f'Could not connect to IndieGala (HTTP {resp.status_code}) — check your session cookie.'
        data = resp.json()
        if data.get('status') != 'ok':
            return False, 'Session cookie appears invalid — log in to IndieGala and copy the sessionid cookie again.'
    except Exception as e:
        return False, f'Connection failed: {e}'
    _save_cfg({'session_cookie': cookie, 'username': 'Connected'})
    log.info('IndieGala connected')
    return True, 'Connected'


def disconnect():
    cfg = load_config() or {}
    cfg.pop('indiegala', None)
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


def _parse_dt(s):
    if not s:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return int(datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return None


def _run_sync():
    global _sync_state
    try:
        db = get_db()
        existing = {
            row['platform_id']: row['appid']
            for row in db.execute(
                "SELECT appid, platform_id FROM games WHERE platform='indiegala'"
            ).fetchall()
        }
        blacklisted = {
            row[0]
            for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()
        }

        page    = 1
        added   = 0
        updated = 0

        while True:
            _sync_state['status'] = f'Fetching page {page}…'
            try:
                resp = requests.get(
                    SHOWCASE_URL,
                    params={'page': page},
                    headers=_headers(),
                    timeout=20,
                )
                if not resp.ok:
                    log.warning(f'IndieGala: page {page} returned {resp.status_code}')
                    break
                data = resp.json()
            except Exception as e:
                log.warning(f'IndieGala: page {page} fetch failed: {e}')
                break

            if data.get('status') != 'ok':
                log.warning(f'IndieGala: unexpected status on page {page}: {data.get("status")}')
                break

            content     = (data.get('showcase_content') or {}).get('content') or {}
            games       = content.get('games') or []
            total_pages = int(content.get('pages_num') or 1)

            for game in games:
                prod_id = str(game.get('prod_id') or '').strip()
                if not prod_id:
                    continue

                prod_name = (game.get('prod_name') or prod_id).strip()
                prod_slug = (game.get('prod_slug') or '').strip()
                prod_dev  = (game.get('prod_dev') or '').strip()
                added_on  = _parse_dt(game.get('added_on')) or int(time.time())

                if prod_id in blacklisted:
                    continue

                if prod_id in existing:
                    updated += 1
                else:
                    appid = next_negative_appid(db)
                    db.execute(
                        """INSERT OR IGNORE INTO games
                           (appid, name, platform, platform_id, platform_slug,
                            date_added, completion_status, installed,
                            developers, publishers,
                            art_fetched, meta_fetched, cheevos_fetched,
                            protondb_fetched, hltb_fetched)
                           VALUES (?, ?, 'indiegala', ?, ?,
                                   ?, 'Never Played', 0,
                                   ?, ?,
                                   '0', '0', '0', '0', '0')""",
                        (appid, prod_name, prod_id, prod_slug,
                         added_on, prod_dev, prod_dev),
                    )
                    db.commit()
                    existing[prod_id] = appid
                    added += 1

            if page >= total_pages:
                break
            page += 1
            time.sleep(0.5)

        db.close()
        _sync_state.update({
            'running': False,
            'status': f'Done — {added} added, {updated} already in library.',
            'added': added, 'updated': updated,
        })
        log.info(f'IndieGala sync complete: {added} added, {updated} existing')

    except Exception as e:
        log.error(f'IndieGala sync error: {e}', exc_info=True)
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
        log.warning(f'IndieGala: failed to open browser: {e}')


def launch_game(appid):
    from database import get_db
    db  = get_db()
    row = db.execute("SELECT platform_slug FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    slug = (row['platform_slug'] if row else '') or ''
    url  = (f'https://www.indiegala.com/store/game/{slug}' if slug
            else 'https://www.indiegala.com/library')
    _open_browser(url)
    return {'status': 'success'}
