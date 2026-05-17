import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import requests

from config import load_config, _save_config_data
from database import get_db, next_negative_appid, update_game_data

log = logging.getLogger(__name__)

HUMBLE_API = 'https://www.humblebundle.com/api/v1'

_sync_state = {'running': False, 'status': '', 'added': 0, 'updated': 0, 'error': None}
_sync_lock  = threading.Lock()


# ── Config ──────────────────────────────────────────────────────────────────────

def _cfg():
    return (load_config() or {}).get('humble', {})

def _save_cfg(data):
    cfg = load_config() or {}
    cfg['humble'] = data
    _save_config_data(cfg)

def is_connected():
    return bool(_cfg().get('session_cookie'))

def get_username():
    return _cfg().get('username', 'Connected')


# ── Auth ────────────────────────────────────────────────────────────────────────

def _headers(cookie=None):
    c = cookie or _cfg().get('session_cookie', '')
    return {
        'Cookie': f'_simpleauth_sess={c}',
        'User-Agent': 'Mozilla/5.0 (compatible; PlayDate)',
        'Accept': 'application/json',
    }


def connect(cookie):
    cookie = cookie.strip().strip('"')
    resp = requests.get(
        f'{HUMBLE_API}/user/order',
        headers=_headers(cookie),
        timeout=15,
        allow_redirects=False,
    )
    if resp.status_code in (301, 302) or not resp.ok:
        return False, 'Session cookie is invalid or expired — copy it again from your browser DevTools.'
    _save_cfg({'session_cookie': cookie, 'username': 'Connected'})
    log.info('Humble Bundle connected')
    return True, 'Connected'


def disconnect():
    cfg = load_config() or {}
    cfg.pop('humble', None)
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
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            return int(datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return None


def _run_sync():
    global _sync_state
    try:
        _sync_state['status'] = 'Fetching order list…'
        resp = requests.get(
            f'{HUMBLE_API}/user/order',
            headers=_headers(),
            timeout=20,
            allow_redirects=False,
        )
        if resp.status_code in (301, 302) or not resp.ok:
            raise RuntimeError('Session expired — please reconnect.')
        gamekeys = [item['gamekey'] for item in resp.json()]
        total = len(gamekeys)
        log.info(f'Humble: {total} orders to process')

        db = get_db()
        existing = {
            row['platform_id']: row['appid']
            for row in db.execute(
                "SELECT appid, platform_id FROM games WHERE platform='humble'"
            ).fetchall()
        }
        blacklisted = {
            row[0]
            for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()
        }

        seen    = set()
        added   = 0
        updated = 0

        for i, gamekey in enumerate(gamekeys):
            _sync_state['status'] = f'Processing order {i + 1} of {total}…'
            try:
                ord_resp = requests.get(
                    f'{HUMBLE_API}/order/{gamekey}',
                    headers=_headers(),
                    timeout=20,
                    allow_redirects=False,
                )
                if not ord_resp.ok:
                    log.warning(f'Humble: order {gamekey} returned {ord_resp.status_code}')
                    time.sleep(0.3)
                    continue
                order = ord_resp.json()
            except Exception as e:
                log.warning(f'Humble: failed to fetch order {gamekey}: {e}')
                time.sleep(0.5)
                continue

            order_date = _parse_dt(order.get('created')) or int(time.time())

            for sub in order.get('subproducts', []):
                machine_name = (sub.get('machine_name') or '').strip()
                if not machine_name or machine_name in seen:
                    continue
                seen.add(machine_name)

                if machine_name in blacklisted:
                    continue

                name = (sub.get('human_name') or machine_name).strip()
                slug = (sub.get('human_url') or '').strip()
                dev  = ((sub.get('payee') or {}).get('human_name') or '').strip()

                if machine_name in existing:
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
                           VALUES (?, ?, 'humble', ?, ?,
                                   ?, 'Never Played', 0,
                                   ?, ?,
                                   '0', '0', '0', '0', '0')""",
                        (appid, name, machine_name, slug,
                         order_date, dev, dev),
                    )
                    db.commit()
                    existing[machine_name] = appid
                    added += 1

            time.sleep(0.2)

        db.close()
        _sync_state.update({
            'running': False,
            'status': f'Done — {added} added, {updated} already in library.',
            'added': added, 'updated': updated,
        })
        log.info(f'Humble sync complete: {added} added, {updated} existing')

    except Exception as e:
        log.error(f'Humble sync error: {e}', exc_info=True)
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
        log.warning(f'Humble: failed to open browser: {e}')


def launch_game(appid):
    db  = get_db()
    row = db.execute("SELECT platform_slug FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    slug = (row['platform_slug'] if row else '') or ''
    url  = (f'https://www.humblebundle.com/home/library/{slug}' if slug
            else 'https://www.humblebundle.com/home/library')
    _open_browser(url)
    return {'status': 'success'}
