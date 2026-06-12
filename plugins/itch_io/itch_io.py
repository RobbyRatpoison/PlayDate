"""
itch_io.py -- itch.io integration for PlayDate.
Handles API key auth, library sync, install detection via butler.db, and launch.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import requests
from datetime import datetime, timezone, date as _date

from config import load_config, _save_config_data
from database import get_db, next_negative_appid, update_game_data

log = logging.getLogger(__name__)

ITCH_API      = 'https://itch.io/api/1'
ITCH_API_NEW  = 'https://api.itch.io'


# ── Config helpers ─────────────────────────────────────────────────────────────

def _load_cfg():
    return (load_config() or {}).get('itch_io', {})

def _save_cfg(data):
    cfg = load_config() or {}
    cfg['itch_io'] = data
    _save_config_data(cfg)

def is_connected():
    return bool(_load_cfg().get('api_key'))

def get_username():
    return _load_cfg().get('username')

def _api_key():
    return _load_cfg().get('api_key')


# ── Auth ───────────────────────────────────────────────────────────────────────

def verify_and_connect(api_key):
    """Verify an API key and store credentials. Returns username or raises ValueError."""
    r = requests.get(f'{ITCH_API}/{api_key}/me', timeout=10)
    if r.status_code in (401, 403, 404):
        raise ValueError('Invalid API key')
    r.raise_for_status()
    data = r.json()
    if 'errors' in data:
        raise ValueError(', '.join(data['errors']))
    user     = data.get('user', {})
    username = user.get('username') or user.get('display_name') or 'itch.io user'
    _save_cfg({'api_key': api_key, 'username': username})
    log.info(f'itch.io connected as {username!r}')
    return username


def login_with_credentials(username, password):
    """
    Log in with itch.io username/email + password.
    Returns the username string on success, raises ValueError on failure.
    If 2FA is required, raises ValueError with a message asking for the TOTP code,
    including the session token as a suffix separated by '|'.
    """
    r = requests.post(f'{ITCH_API}/login',
                      data={'username': username, 'password': password, 'source': 'desktop'},
                      timeout=10)
    data = r.json()
    errors = data.get('errors') or []

    if data.get('totp_needed') or any('two factor' in e.lower() or 'totp' in e.lower() for e in errors):
        token = data.get('token', '')
        raise ValueError(f'TOTP_REQUIRED|{token}')

    if errors:
        raise ValueError(errors[0])

    key_obj  = data.get('key') or {}
    api_key  = key_obj.get('key') or data.get('api_key')
    if not api_key:
        raise ValueError('Login succeeded but no API key was returned')

    user     = data.get('user') or {}
    uname    = user.get('username') or user.get('display_name') or username
    _save_cfg({'api_key': api_key, 'username': uname})
    log.info(f'itch.io connected as {uname!r}')
    return uname


def verify_totp(totp_token, totp_code):
    """
    Complete a 2FA login. totp_token is the session token from the initial login response.
    Returns the username string on success, raises ValueError on failure.
    """
    r = requests.post(f'{ITCH_API}/totp/verify',
                      json={'token': totp_token, 'code': totp_code},
                      timeout=10)
    data   = r.json()
    errors = data.get('errors') or []
    if errors:
        raise ValueError(errors[0])

    key_obj = data.get('key') or {}
    api_key = key_obj.get('key') or data.get('api_key')
    if not api_key:
        raise ValueError('TOTP verification succeeded but no API key returned')

    user   = data.get('user') or {}
    uname  = user.get('username') or user.get('display_name') or 'itch.io user'
    _save_cfg({'api_key': api_key, 'username': uname})
    log.info(f'itch.io connected (TOTP) as {uname!r}')
    return uname


def disconnect():
    cfg = load_config() or {}
    cfg.pop('itch_io', None)
    _save_config_data(cfg)


# ── Library sync ───────────────────────────────────────────────────────────────

_sync_state = {
    'running': False, 'phase': None,
    'page': 0, 'done': 0, 'total': 0, 'current_game': '',
    'new_games': 0, 'total_games': 0, 'error': None,
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
            'running': True, 'phase': 'fetching_library', 'page': 0,
            'done': 0, 'total': 0, 'current_game': '',
            'new_games': 0, 'total_games': 0, 'error': None,
        })
    threading.Thread(target=_run_sync, daemon=True).start()
    return {'status': 'started'}


def cancel_library_sync():
    _sync_cancel.set()


def _run_sync():
    try:
        _do_sync()
    except Exception as e:
        log.error(f'itch.io sync thread: {e}', exc_info=True)
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error', 'error': str(e)})


def _parse_date(s):
    if not s:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S'):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return None


def _do_sync():
    from images import download_vertical, download_horizontal, download_icon, _sgdb_search_game_id

    key = _api_key()
    if not key:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error', 'error': 'Not connected'})
        return

    # Phase 1: fetch all pages of owned keys
    owned = []
    page = 1
    while True:
        if _sync_cancel.is_set():
            with _sync_lock:
                _sync_state.update({'running': False, 'phase': 'stopped', 'new_games': 0, 'total_games': 0})
            return
        try:
            r = requests.get(
                f'{ITCH_API_NEW}/profile/owned-keys',
                params={'page': page},
                headers={'Authorization': f'Bearer {key}'},
                timeout=20,
            )
            if r.status_code == 401:
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'error',
                                        'error': 'API key rejected — please reconnect'})
                return
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            log.warning(f'itch.io library: page {page} fetch failed: {e}')
            break

        if 'errors' in data:
            with _sync_lock:
                _sync_state.update({'running': False, 'phase': 'error',
                                    'error': ', '.join(data['errors'])})
            return

        keys = data.get('owned_keys', [])
        log.info(f'itch.io library: page {page} — {len(keys)} keys')
        owned.extend(keys)

        per_page = data.get('per_page', 10)
        if not keys or len(keys) < per_page:
            break
        page += 1
        with _sync_lock:
            _sync_state['page'] = page
        time.sleep(0.3)

    # Filter to games only (exclude assets, comics, soundtracks, etc.)
    games = [e for e in owned if (e.get('game') or {}).get('classification') in
             ('game', 'tool', None, '')]
    log.info(f'itch.io sync: {len(games)} games from {len(owned)} owned items')

    # Phase 2: process new games
    db = get_db()
    try:
        existing = {
            row[0] for row in db.execute(
                "SELECT platform_id FROM games WHERE platform = 'itch_io'"
            ).fetchall()
        }
        blacklisted = {
            row[0] for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()
        }

        new_entries = [e for e in games
                       if str(e['game']['id']) not in existing
                       and str(e['game']['id']) not in blacklisted]
        total_new = len(new_entries)
        log.info(f'itch.io sync: {total_new} new games to process')

        today = _date.today().isoformat()
        new_count = 0

        with _sync_lock:
            _sync_state.update({'phase': 'processing', 'done': 0, 'total': total_new})

        for entry in new_entries:
            if _sync_cancel.is_set():
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'stopped',
                                        'new_games': new_count, 'total_games': len(games)})
                return

            game    = entry['game']
            game_id = str(game['id'])
            name    = game.get('title') or f'itch.io game {game_id}'
            url     = game.get('url', '')

            with _sync_lock:
                _sync_state['current_game'] = name

            date_added   = _parse_date(entry.get('created_at')) or int(time.time())
            release_date = _parse_date(game.get('published_at'))
            user         = game.get('user') or {}
            creator      = user.get('display_name') or user.get('username') or ''

            download_key_id = str(entry.get('id') or '')
            next_appid = next_negative_appid(db)
            db.execute(
                """INSERT OR IGNORE INTO games
                   (appid, name, platform, platform_id, platform_slug, platform_appname,
                    date_added, completion_status, installed,
                    developers, publishers, release_date,
                    art_fetched, meta_fetched, cheevos_fetched,
                    protondb_fetched, hltb_fetched)
                   VALUES (?, ?, 'itch_io', ?, ?, ?, ?,
                           'Never Played', 0,
                           ?, ?, ?,
                           '0', '0', '0', '0', '0')""",
                (next_appid, name, game_id, url, download_key_id, date_added,
                 creator, creator, release_date),
            )
            db.commit()
            log.info(f'itch.io sync: added {name!r} as appid {next_appid}')

            # Art: try SGDB, fill any missing slots from itch.io cover
            cover_url = game.get('still_cover_url') or game.get('cover_url')
            try:
                sgdb_id   = _sgdb_search_game_id(name)
                got_vert  = download_vertical(next_appid,   sgdb_id=sgdb_id, game_name=name)
                got_horiz = download_horizontal(next_appid, sgdb_id=sgdb_id, game_name=name)
                if cover_url and (got_vert == 'missing' or got_horiz == 'missing'):
                    _download_itch_cover(cover_url, next_appid,
                                         vertical=got_vert == 'missing',
                                         horizontal=got_horiz == 'missing')
                got_icon = download_icon(next_appid, '', sgdb_id=sgdb_id, game_name=name)
                update_game_data(next_appid, art_fetched=today,
                                 vertical_art_source=got_vert,
                                 horizontal_art_source=got_horiz,
                                 icon_source=got_icon)
            except Exception as e:
                log.warning(f'itch.io art: failed for {name!r}: {e}')
                if cover_url:
                    try:
                        _download_itch_cover(cover_url, next_appid)
                        update_game_data(next_appid, art_fetched=today)
                    except Exception:
                        pass

            update_game_data(next_appid, meta_fetched=today)
            new_count += 1

            with _sync_lock:
                _sync_state['done'] += 1

            time.sleep(0.3)

    finally:
        db.close()

    dupes = 0
    if new_count > 0:
        from database import auto_detect_duplicates
        from plugins import get_platform_priority
        dupes = auto_detect_duplicates(platform_priority=get_platform_priority())
    log.info(f'itch.io sync: {new_count} new games, {dupes} duplicates detected')

    with _sync_lock:
        _sync_state.update({
            'running': False, 'phase': 'done',
            'new_games': new_count, 'total_games': len(games),
            'duplicates_detected': dupes,
        })


def _download_itch_cover(cover_url, appid, vertical=True, horizontal=True):
    """Download itch.io cover image, save as vertical and/or horizontal art."""
    from PIL import Image
    import io as _io
    from config import BASE_DIR

    r = requests.get(cover_url, timeout=15)
    r.raise_for_status()
    img = Image.open(_io.BytesIO(r.content))
    if img.mode in ('RGBA', 'P', 'LA'):
        img = img.convert('RGB')
    base = os.path.join(BASE_DIR, 'static', 'img', 'library')
    if vertical:
        d = os.path.join(base, 'vertical')
        os.makedirs(d, exist_ok=True)
        img.save(os.path.join(d, f'{appid}.jpg'), 'JPEG', quality=95)
    if horizontal:
        d = os.path.join(base, 'horizontal')
        os.makedirs(d, exist_ok=True)
        img.save(os.path.join(d, f'{appid}.jpg'), 'JPEG', quality=95)


# ── Purchase date re-fetch ─────────────────────────────────────────────────────

def fetch_dates_for_appids(appids, on_result):
    """
    Re-fetch purchase dates for specific appids from the itch.io owned-keys API.
    Calls on_result(appid, ts_or_None) for each appid as it is found or exhausted.
    """
    key = _api_key()
    if not key:
        raise RuntimeError('itch.io account not connected')

    db   = get_db()
    rows = db.execute(
        f'SELECT appid, platform_id FROM games WHERE appid IN ({",".join("?" * len(appids))})',
        appids,
    ).fetchall()
    db.close()

    game_id_to_appid = {row['platform_id']: row['appid'] for row in rows if row['platform_id']}
    still_needed     = set(game_id_to_appid)
    page             = 1

    while still_needed:
        try:
            r = requests.get(
                f'{ITCH_API_NEW}/profile/owned-keys',
                params={'page': page},
                headers={'Authorization': f'Bearer {key}'},
                timeout=20,
            )
            if r.status_code == 401:
                raise RuntimeError('itch.io API key invalid — please reconnect')
            r.raise_for_status()
            data = r.json()
        except RuntimeError:
            raise
        except Exception as e:
            log.warning(f'itch.io date re-fetch page {page} failed: {e}')
            break

        owned    = data.get('owned_keys') or []
        per_page = data.get('per_page', 10)

        for entry in owned:
            game    = entry.get('game') or {}
            game_id = str(game.get('id') or '')
            if game_id in still_needed:
                ts = _parse_date(entry.get('created_at'))
                on_result(game_id_to_appid[game_id], ts)
                still_needed.discard(game_id)

        if not owned or len(owned) < per_page:
            break
        page += 1
        time.sleep(0.3)

    for game_id in still_needed:
        on_result(game_id_to_appid[game_id], None)


# ── Install detection via butler.db ───────────────────────────────────────────

def _butler_db_path():
    candidates = [
        os.path.expanduser('~/.config/itch/db/butler.db'),
        os.path.expanduser('~/Library/Application Support/itch/db/butler.db'),
    ]
    appdata = os.environ.get('APPDATA', '')
    if appdata:
        candidates.append(os.path.join(appdata, 'itch', 'db', 'butler.db'))
    return next((p for p in candidates if os.path.exists(p)), None)


def sync_install_status():
    """Sync installed flags for all itch.io games.

    - Games we installed: check install_path directory still exists.
    - Games installed via itch app: check butler.db caves table.
    """
    # Collect butler.db game IDs (platform_id values)
    butler_ids = set()
    db_path = _butler_db_path()
    if db_path:
        import sqlite3
        try:
            butler = sqlite3.connect(db_path)
            butler_ids = {
                str(row[0])
                for row in butler.execute("SELECT game_id FROM caves").fetchall()
            }
            butler.close()
        except Exception as e:
            log.warning(f'itch.io: failed to read butler.db: {e}')

    db = get_db()
    try:
        rows = db.execute(
            "SELECT appid, platform_id, install_path FROM games WHERE platform='itch_io'"
        ).fetchall()
        for row in rows:
            if row['install_path']:
                # We manage this install -- check the directory
                should_be = 1 if os.path.isdir(row['install_path']) else 0
            else:
                # itch app install -- check butler.db
                should_be = 1 if row['platform_id'] in butler_ids else 0
            db.execute("UPDATE games SET installed=? WHERE appid=?", (should_be, row['appid']))
        db.commit()
    finally:
        db.close()

    log.info(f'itch.io: install status synced ({len(butler_ids)} in butler.db)')


_itch_watcher_observer = None


def start_install_watcher():
    """Watch ITCH_INSTALL_BASE for directory changes and sync install status."""
    global _itch_watcher_observer

    os.makedirs(ITCH_INSTALL_BASE, exist_ok=True)

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        log.warning('itch.io: watchdog not installed — install watcher disabled')
        return None

    class _InstallHandler(FileSystemEventHandler):
        def _on_change(self, path):
            if os.path.dirname(os.path.abspath(path)) == os.path.abspath(ITCH_INSTALL_BASE):
                log.info(f'itch.io: install dir change detected — syncing install status')
                try:
                    sync_install_status()
                except Exception as e:
                    log.error(f'itch.io: install status sync failed — {e}')

        def on_created(self, event):
            if event.is_directory:
                self._on_change(event.src_path)

        def on_deleted(self, event):
            if event.is_directory:
                self._on_change(event.src_path)

        def on_moved(self, event):
            if event.is_directory:
                self._on_change(event.dest_path)

    stop_install_watcher()

    observer = Observer()
    observer.schedule(_InstallHandler(), path=ITCH_INSTALL_BASE, recursive=False)
    observer.start()
    _itch_watcher_observer = observer
    log.info(f'itch.io: install watcher started on {ITCH_INSTALL_BASE}')
    return observer


def stop_install_watcher():
    global _itch_watcher_observer
    if _itch_watcher_observer is not None:
        try:
            _itch_watcher_observer.stop()
            _itch_watcher_observer.join(timeout=3)
        except Exception as e:
            log.warning(f'itch.io: install watcher stop error: {e}')
        _itch_watcher_observer = None


# ── Launch ─────────────────────────────────────────────────────────────────────

def _find_cave_verdict(game_id):
    """Return the verdict dict for game_id from butler.db, or None."""
    db_path = _butler_db_path()
    if not db_path:
        return None
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        row  = conn.execute(
            "SELECT verdict FROM caves WHERE game_id=? AND verdict IS NOT NULL",
            (int(game_id),),
        ).fetchone()
        conn.close()
        if not row or not row[0]:
            return None
        return json.loads(row[0])
    except Exception as e:
        log.warning(f'itch.io: butler.db lookup failed: {e}')
        return None


def _pick_executable(verdict):
    """Return (flavor, abs_path) for the best runnable candidate in a butler verdict, or (None, None)."""
    base       = verdict.get('basePath', '')
    candidates = verdict.get('candidates', [])
    if not base or not candidates:
        return None, None

    if sys.platform == 'darwin':
        flavor_pref = ('osx', 'appimage', 'script', 'linux')
    elif sys.platform == 'win32':
        flavor_pref = ('windows',)
    else:
        flavor_pref = ('linux', 'appimage', 'script')

    for flavor in flavor_pref:
        for c in candidates:
            if c.get('flavor') == flavor:
                path = os.path.join(base, c['path'])
                if os.path.exists(path):
                    return flavor, path

    # Fallback: first candidate regardless of flavor
    c    = candidates[0]
    path = os.path.join(base, c['path'])
    if os.path.exists(path):
        return c.get('flavor', 'unknown'), path

    return None, None


# ── Install ────────────────────────────────────────────────────────────────────

import re as _re
import zipfile
import tarfile

if sys.platform == 'win32':
    ITCH_INSTALL_BASE = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'PlayDate', 'itch')
elif sys.platform == 'darwin':
    ITCH_INSTALL_BASE = os.path.expanduser('~/Library/Application Support/PlayDate/itch')
else:
    ITCH_INSTALL_BASE = os.path.expanduser('~/.local/share/playdate-itch')

_install_states  = {}
_install_lock    = threading.Lock()
_install_cancels = {}


def get_game_uploads(game_id, download_key_id=None):
    """Return list of upload dicts for a game, or raise on error.

    Uses download-key endpoint when available (required for paid games).
    """
    key = _api_key()
    if not key:
        raise ValueError('Not connected')
    if download_key_id:
        url = f'{ITCH_API}/{key}/download-key/{download_key_id}/uploads'
    else:
        url = f'{ITCH_API}/{key}/game/{game_id}/uploads'
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    if 'errors' in data:
        raise ValueError(', '.join(data['errors']))
    uploads = data.get('uploads', [])
    # Fall back to game endpoint if download-key returned nothing
    if not uploads and download_key_id:
        log.debug(f'itch.io: download-key uploads empty for game {game_id}, trying game endpoint')
        r2 = requests.get(f'{ITCH_API}/{key}/game/{game_id}/uploads', timeout=15)
        if r2.ok:
            uploads = r2.json().get('uploads', [])
    return uploads


def _get_download_url(upload_id, download_key_id=None):
    """Return a time-limited download URL for an upload."""
    key    = _api_key()
    params = {'download_key_id': download_key_id} if download_key_id else {}
    r = requests.get(f'{ITCH_API}/{key}/upload/{upload_id}/download',
                     params=params, allow_redirects=False, timeout=15)
    if r.status_code in (301, 302, 303, 307, 308):
        return r.headers.get('Location', '')
    r.raise_for_status()
    data = r.json()
    log.debug(f'itch.io download URL response: {data}')
    return data.get('url', '')


def _pick_upload(uploads):
    """Pick the most suitable upload for the current OS."""
    import platform as _plat
    system = _plat.system()

    # Prefer 'default' type uploads; fall back to all
    candidates = [u for u in uploads if u.get('type') == 'default'] or uploads

    def _first(platform_key):
        for u in candidates:
            if (u.get('platforms') or {}).get(platform_key):
                return u
        return None

    # Native platform first, then Windows as cross-platform fallback (Wine), then any
    if system == 'Linux':
        return _first('linux') or _first('windows') or candidates[0] if candidates else None
    if system == 'Darwin':
        return _first('osx') or _first('windows') or candidates[0] if candidates else None
    if system == 'Windows':
        return _first('windows') or candidates[0] if candidates else None

    return candidates[0] if candidates else None


def _is_elf(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'\x7fELF'
    except Exception:
        return False


def _is_macho(path):
    try:
        with open(path, 'rb') as f:
            magic = f.read(4)
            return magic in (b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf',
                             b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe',
                             b'\xca\xfe\xba\xbe')
    except Exception:
        return False


def _find_itch_executable(install_path):
    """Walk install_path and return a relative path to the best executable."""
    is_windows = sys.platform == 'win32'
    is_mac     = sys.platform == 'darwin'

    # macOS: look for .app bundles at top level first
    if is_mac:
        for entry in os.listdir(install_path):
            if entry.endswith('.app') and os.path.isdir(os.path.join(install_path, entry)):
                return entry

    SKIP_EXT = {'.txt', '.md', '.cfg', '.ini', '.conf', '.json', '.log',
                '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.xml',
                '.html', '.htm', '.css', '.js', '.py', '.bak', '.desktop',
                '.so', '.dll', '.dylib', '.pdb'}

    appimages, native, scripts, winexes = [], [], [], []

    for root, dirs, files in os.walk(install_path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in files:
            if fname.startswith('.'):
                continue
            fpath = os.path.join(root, fname)
            rel   = os.path.relpath(fpath, install_path)
            _, ext = os.path.splitext(fname)
            ext = ext.lower()
            if ext in SKIP_EXT:
                continue
            if ext == '.appimage':
                appimages.append(rel)
            elif ext in ('.x86_64', '.x86', '.amd64', '.arm64', '.linux'):
                native.append(rel)
            elif ext == '.sh' and not is_windows:
                scripts.append(rel)
            elif not ext and not is_windows and (_is_elf(fpath) or (is_mac and _is_macho(fpath))):
                native.append(rel)
            elif ext == '.exe':
                winexes.append(rel)

    _HELPER_EXE_NAMES = {
        'unitycrashhandler64', 'unitycrashhandler32', 'unitycrashhandler',
        'unityplayer',
        'dxsetup', 'dxwebsetup',
        'vcredist_x64', 'vcredist_x86', 'vc_redist.x64', 'vc_redist.x86',
        'dotnetfx', 'dotnet',
    }

    def _exe_sort_key(p):
        stem = os.path.splitext(os.path.basename(p))[0].lower()
        return (p.count(os.sep), stem in _HELPER_EXE_NAMES, p)

    for group in (appimages, native, scripts, winexes):
        if group:
            # Prefer shallower paths; within same depth, deprioritize known helper exes
            return sorted(group, key=_exe_sort_key)[0]

    return None


def install_game(appid, progress_cb=None, cancel_ev=None):
    """Download and install an itch.io game. Returns a status dict."""
    db  = get_db()
    row = db.execute(
        "SELECT name, platform_id, platform_appname FROM games WHERE appid=?", (appid,)
    ).fetchone()
    db.close()
    if not row:
        return {'status': 'error', 'message': 'Game not found'}

    game_id         = row['platform_id']
    game_name       = row['name']
    download_key_id = row['platform_appname'] or None

    try:
        uploads = get_game_uploads(game_id, download_key_id=download_key_id)
    except Exception as e:
        return {'status': 'error', 'message': f'Failed to list downloads: {e}'}

    upload = _pick_upload(uploads)
    if not upload:
        return {'status': 'error', 'message': 'No downloads available.'}

    try:
        download_url = _get_download_url(upload['id'], download_key_id=download_key_id)
    except Exception as e:
        return {'status': 'error', 'message': f'Failed to get download URL: {e}'}

    if not download_url:
        return {'status': 'error', 'message': 'Empty download URL returned'}

    safe_name    = _re.sub(r'[^\w-]', '_', game_name).strip('_')
    install_path = os.path.join(ITCH_INSTALL_BASE, f'{safe_name}_{game_id}')
    os.makedirs(install_path, exist_ok=True)

    filename = upload.get('filename', 'game.zip')
    tmp_path = os.path.join(install_path, f'_dl_{filename}')

    # Download
    try:
        r = requests.get(download_url, stream=True, timeout=60)
        r.raise_for_status()
        total = int(r.headers.get('content-length', 0))
        done  = 0
        with open(tmp_path, 'wb') as fh:
            for chunk in r.iter_content(65536):
                if cancel_ev and cancel_ev.is_set():
                    try: os.unlink(tmp_path)
                    except Exception: pass
                    return {'status': 'cancelled', 'message': 'Install cancelled'}
                fh.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    except Exception as e:
        try: os.unlink(tmp_path)
        except Exception: pass
        import shutil; shutil.rmtree(install_path, ignore_errors=True)
        return {'status': 'error', 'message': f'Download failed: {e}'}

    # Extract
    try:
        fn_lower = filename.lower()
        if fn_lower.endswith('.zip'):
            with zipfile.ZipFile(tmp_path) as zf:
                # If all entries share a single top-level dir, extract directly
                tops = {n.split('/')[0] for n in zf.namelist() if n.strip('/')}
                if len(tops) == 1:
                    zf.extractall(install_path)
                    single = os.path.join(install_path, tops.pop())
                    if os.path.isdir(single):
                        for item in os.listdir(single):
                            os.rename(os.path.join(single, item),
                                      os.path.join(install_path, item))
                        os.rmdir(single)
                else:
                    zf.extractall(install_path)
        elif fn_lower.endswith(('.tar.gz', '.tgz', '.tar.bz2', '.tar.xz')):
            with tarfile.open(tmp_path) as tf:
                tf.extractall(install_path)
        else:
            # Treat as a raw binary/AppImage
            dest = os.path.join(install_path, filename)
            os.rename(tmp_path, dest)
            os.chmod(dest, 0o755)
            tmp_path = None
    except Exception as e:
        import shutil; shutil.rmtree(install_path, ignore_errors=True)
        return {'status': 'error', 'message': f'Extraction failed: {e}'}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.unlink(tmp_path)
            except Exception: pass

    # Fix executable permissions on all files that look like binaries
    for root, _, files in os.walk(install_path):
        for fname in files:
            _, ext = os.path.splitext(fname)
            if ext.lower() in ('.sh', '.x86_64', '.x86', '.amd64', '.linux', '.appimage', ''):
                fpath = os.path.join(root, fname)
                try:
                    os.chmod(fpath, os.stat(fpath).st_mode | 0o111)
                except Exception:
                    pass

    platform_executable = _find_itch_executable(install_path)
    update_game_data(appid, install_path=install_path, installed=1,
                     platform_executable=platform_executable)
    log.info(f'itch.io install complete: {game_name!r} → {install_path} (exe: {platform_executable!r})')
    return {'status': 'success', 'install_path': install_path,
            'platform_executable': platform_executable}


def start_install(appid):
    """Start a background install. Returns immediately."""
    db  = get_db()
    row = db.execute('SELECT name FROM games WHERE appid=?', (appid,)).fetchone()
    db.close()
    game_name = row['name'] if row else 'Unknown'

    with _install_lock:
        if _install_states.get(appid, {}).get('status') == 'running':
            return {'status': 'already_running'}
        cancel_ev = threading.Event()
        _install_cancels[appid] = cancel_ev
        _install_states[appid]  = {
            'status': 'running', 'done': 0, 'total': 0,
            'name': game_name, 'message': 'Starting download...',
        }

    def _progress(done, total):
        with _install_lock:
            _install_states[appid].update({'done': done, 'total': total})

    def _run():
        try:
            result = install_game(appid, progress_cb=_progress, cancel_ev=cancel_ev)
            with _install_lock:
                _install_states[appid] = {**result, 'name': game_name}
        except Exception as e:
            log.error(f'itch.io install thread: {e}', exc_info=True)
            with _install_lock:
                _install_states[appid] = {'status': 'error', 'message': str(e), 'name': game_name}
        finally:
            _install_cancels.pop(appid, None)

    threading.Thread(target=_run, daemon=True).start()
    return {'status': 'started'}


def get_install_state(appid):
    with _install_lock:
        return dict(_install_states.get(appid, {'status': 'not_started'}))


def cancel_install(appid):
    ev = _install_cancels.get(appid)
    if ev:
        ev.set()


# ── Launch ─────────────────────────────────────────────────────────────────────

if sys.platform == 'win32':
    ITCH_PREFIX_BASE = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'PlayDate', 'itch-prefixes')
elif sys.platform == 'darwin':
    ITCH_PREFIX_BASE = os.path.expanduser('~/Library/Application Support/PlayDate/itch-prefixes')
else:
    ITCH_PREFIX_BASE = os.path.expanduser('~/.local/share/playdate-itch/prefixes')


def _launch_exe(appid, exe_path, cwd):
    """Launch exe_path, using Proton for .exe files on non-Windows."""
    from runners.launch import check_launch, popen_checked
    is_windows = sys.platform == 'win32'

    # macOS .app bundle
    if exe_path.endswith('.app') and os.path.isdir(exe_path):
        try:
            subprocess.Popen(['open', exe_path])
        except Exception as e:
            return str(e)
        return None

    if exe_path.lower().endswith('.exe') and not is_windows:
        prefix = os.path.join(ITCH_PREFIX_BASE, str(appid))
        os.makedirs(prefix, exist_ok=True)
        from runners.proton import launch_game as proton_launch, get_default_proton
        p = get_default_proton()
        proc = None
        if p:
            try:
                log.info(f'itch.io: launching via Proton ({p["name"]}): {exe_path}')
                proc = proton_launch(
                    install_path=cwd,
                    executable=os.path.relpath(exe_path, cwd),
                    wine_prefix=prefix,
                    proton_path=p['path'],
                )
            except Exception as e:
                log.warning(f'itch.io: Proton launch failed ({e}), falling back to Wine')
        if proc is None:
            try:
                from runners.wine import run_in_prefix
                log.info(f'itch.io: launching via Wine: {exe_path}')
                proc = run_in_prefix(prefix_path=prefix, exe=exe_path)
            except Exception as e:
                return str(e)
        if proc:
            err = check_launch(proc)
            if err:
                return err['message']
        return None
    else:
        try:
            os.chmod(exe_path, os.stat(exe_path).st_mode | 0o111)
        except Exception:
            pass
        try:
            _, err = popen_checked([exe_path], cwd=cwd)
            if err:
                return err['message']
        except Exception as e:
            return str(e)
        return None


def launch_game(appid):
    """Launch an itch.io game, starting install first if needed."""
    db  = get_db()
    row = db.execute(
        "SELECT platform_id, name, installed, install_path, platform_executable FROM games WHERE appid=?",
        (appid,)
    ).fetchone()
    db.close()
    if not row:
        return {'status': 'error', 'message': 'Game not found'}

    game_id   = row['platform_id']
    game_name = row['name']

    # Not installed -- start download
    if not row['installed']:
        start_install(appid)
        return {
            'status':         'installing',
            'install_poller': '_startItchInstallPoller',
            'message':        f'Downloading {game_name}...',
        }

    def _do_launch(exe_path, cwd):
        err = _launch_exe(appid, exe_path, cwd)
        if err:
            return {'status': 'error', 'message': err}
        now = int(time.time())
        update_game_data(appid, last_played=now)
        from database import ts_to_date
        return {'status': 'success', 'last_played': ts_to_date(now)}

    # Try stored install path
    if row['install_path'] and os.path.isdir(row['install_path']):
        exe_rel = row['platform_executable'] or _find_itch_executable(row['install_path'])
        if exe_rel:
            exe_abs = os.path.join(row['install_path'], exe_rel)
            if os.path.isfile(exe_abs) or (exe_abs.endswith('.app') and os.path.isdir(exe_abs)):
                return _do_launch(exe_abs, row['install_path'])

    # Try butler.db (itch app installed games)
    verdict = _find_cave_verdict(game_id)
    if verdict:
        flavor, exe_path = _pick_executable(verdict)
        if exe_path:
            return _do_launch(exe_path, os.path.dirname(exe_path))

    # Files present but no launchable executable found -- unsupported format
    if row['install_path'] and os.path.isdir(row['install_path']):
        return {
            'status':  'error',
            'message': f'No supported executable found in {game_name}.',
        }

    # Nothing on disk -- reset and re-download
    update_game_data(appid, installed=0, install_path=None, platform_executable=None)
    start_install(appid)
    return {
        'status':         'installing',
        'install_poller': '_startItchInstallPoller',
        'message':        f'Re-downloading {game_name}...',
    }


# ── Metadata ───────────────────────────────────────────────────────────────────

def rescrape_game(appid):
    """Re-fetch metadata for an itch.io game. Returns update dict or None."""
    from images import download_vertical, download_horizontal, download_icon, _sgdb_search_game_id

    key = _api_key()
    db  = get_db()
    row = db.execute("SELECT platform_id, name FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    if not row:
        return None

    game_id   = row['platform_id']
    game_name = row['name']
    today     = _date.today().isoformat()
    result    = {'meta_fetched': today, 'cheevos_fetched': today}

    # Try itch.io API for fresh metadata
    cover_url = None
    if key:
        try:
            r = requests.get(f'{ITCH_API}/{key}/game/{game_id}', timeout=10)
            if r.ok:
                game = r.json().get('game', {})
                if game:
                    result['platform_slug'] = game.get('url', '')
                    result['name']          = game.get('title', game_name)
                    cover_url               = game.get('still_cover_url') or game.get('cover_url')
                    user    = game.get('user') or {}
                    creator = user.get('display_name') or user.get('username') or ''
                    if creator:
                        result['developers'] = creator
                        result['publishers'] = creator
                    release_date = _parse_date(game.get('published_at'))
                    if release_date:
                        result['release_date'] = release_date
        except Exception as e:
            log.warning(f'itch.io rescrape: API call failed for {game_id}: {e}')

    # Art
    try:
        sgdb_id   = _sgdb_search_game_id(game_name)
        got_vert  = download_vertical(appid,   sgdb_id=sgdb_id, game_name=game_name)
        got_horiz = download_horizontal(appid, sgdb_id=sgdb_id, game_name=game_name)
        if cover_url and (got_vert == 'missing' or got_horiz == 'missing'):
            _download_itch_cover(cover_url, appid,
                                 vertical=got_vert == 'missing',
                                 horizontal=got_horiz == 'missing')
        got_icon = download_icon(appid, '', sgdb_id=sgdb_id, game_name=game_name)
        result['art_fetched'] = today
        result['vertical_art_source']   = got_vert
        result['horizontal_art_source'] = got_horiz
        result['icon_source']           = got_icon
    except Exception as e:
        log.warning(f'itch.io rescrape art: failed for {game_name!r}: {e}')
        if cover_url:
            try:
                _download_itch_cover(cover_url, appid)
                result['art_fetched'] = today
            except Exception:
                pass

    return result or None


def fetch_description(platform_id):
    """Fetch game description from itch.io API."""
    key = _api_key()
    if not key:
        return None
    try:
        r = requests.get(f'{ITCH_API}/{key}/game/{platform_id}', timeout=10)
        if r.ok:
            game = r.json().get('game', {})
            return game.get('short_text') or None
    except Exception:
        pass
    return None
