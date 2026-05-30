import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone

import requests

from config import load_config, _save_config_data, BASE_DIR
from database import get_db, next_negative_appid, update_game_data

log = logging.getLogger(__name__)

HUMBLE_API   = 'https://www.humblebundle.com/api/v1'
_CACHE_FILE  = os.path.join(BASE_DIR, 'humble_cache.json')

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


_GAME_PLATFORMS = {'windows', 'linux', 'mac', 'android'}

_NON_GAME_KEYWORDS = {
    'soundtrack', ' ost', 'original score', 'music pack',
    'artbook', 'art book', 'digital art', 'wallpaper',
    'comic', 'ebook', 'e-book', 'graphic novel',
    'documentary', 'making of',
}


def _is_game(subproduct):
    has_game_download = any(
        (d.get('platform') or '').lower() in _GAME_PLATFORMS
        for d in subproduct.get('downloads', [])
    )
    if not has_game_download:
        return False
    name = (subproduct.get('human_name') or '').lower()
    return not any(kw in name for kw in _NON_GAME_KEYWORDS)


def connect(cookie):
    from urllib.parse import unquote
    cookie = unquote(cookie.strip()).strip('"')
    resp = requests.get(
        f'{HUMBLE_API}/user/order',
        headers=_headers(cookie),
        timeout=15,
        allow_redirects=False,
    )
    if resp.status_code in (301, 302) or not resp.ok:
        return False, 'Session cookie is invalid or expired — copy it again from your browser DevTools.'
    username = 'Connected'
    try:
        import re
        page = requests.get(
            'https://www.humblebundle.com/home/library',
            headers={**_headers(cookie), 'Accept': 'text/html'},
            timeout=15,
            allow_redirects=False,
        )
        if page.ok:
            m = re.search(r'"username"\s*:\s*"([^"]+)"', page.text)
            if not m:
                m = re.search(r'"email"\s*:\s*"([^"]+)"', page.text)
            if m:
                raw = m.group(1)
                if '@' in raw:
                    local, domain = raw.split('@', 1)
                    visible = local[:2] if len(local) > 2 else local[:1]
                    username = f'{visible}{"*" * max(1, len(local) - 2)}@{domain}'
                else:
                    username = raw
            else:
                log.warning('Humble: could not find username in library page')
        else:
            log.warning(f'Humble library page returned {page.status_code}')
    except Exception as e:
        log.warning(f'Humble username fetch failed: {e}')
    _save_cfg({'session_cookie': cookie, 'username': username})
    log.info(f'Humble Bundle connected as {username!r}')
    return True, username


def disconnect():
    cfg = load_config() or {}
    cfg.pop('humble', None)
    _save_config_data(cfg)
    try:
        os.remove(_CACHE_FILE)
    except FileNotFoundError:
        pass


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


def _load_cache():
    try:
        with open(_CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_cache(data):
    try:
        with open(_CACHE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        log.warning(f'Humble: cache save failed: {e}')


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
        all_gamekeys = [item['gamekey'] for item in resp.json()]
        cache = _load_cache()
        # gamekeys_map: {gamekey: [machine_name, ...]} — tracks which games each order produced
        # so orders with deleted (non-blacklisted) games get re-processed on next sync.
        # Migrate old flat-list cache: treat those orders as fully synced (contents unknown).
        gamekeys_map = cache.get('gamekeys_map', {})

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

        def _needs_sync(gamekey):
            names = gamekeys_map.get(gamekey)
            if names is None:
                return True
            return any(n not in existing and n not in blacklisted for n in names)

        gamekeys = [k for k in all_gamekeys if _needs_sync(k)]
        if cache.get('test_limit'):
            gamekeys = gamekeys[:cache['test_limit']]
        total = len(gamekeys)
        log.info(f'Humble: {len(all_gamekeys)} orders total, {total} to process')

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

            order_machine_names = []
            for sub in order.get('subproducts', []):
                if not _is_game(sub):
                    continue
                machine_name = (sub.get('machine_name') or '').strip()
                if not machine_name:
                    continue
                order_machine_names.append(machine_name)
                if machine_name in seen:
                    continue
                seen.add(machine_name)

                if machine_name in blacklisted:
                    continue

                name = (sub.get('human_name') or machine_name).strip()
                # platform_slug stores gamekey/machine_name for the download URL
                slug = f'{gamekey}/{machine_name}'
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
                    try:
                        from images import download_vertical, download_horizontal, download_icon, _sgdb_search_game_id
                        from datetime import date
                        sgdb_id = _sgdb_search_game_id(name)
                        download_vertical(appid, sgdb_id=sgdb_id)
                        download_horizontal(appid, sgdb_id=sgdb_id)
                        download_icon(appid, '', sgdb_id=sgdb_id)
                        update_game_data(appid, art_fetched=str(date.today()))
                    except Exception as _e:
                        log.warning(f'Humble art: failed for {name!r}: {_e}')

            gamekeys_map[gamekey] = order_machine_names
            time.sleep(0.2)

        db.close()
        _save_cache({'gamekeys_map': gamekeys_map})
        _sync_state.update({
            'running': False,
            'status': f'Done — {added} added, {updated} already in library.',
            'added': added, 'updated': updated,
        })
        log.info(f'Humble sync complete: {added} added, {updated} existing')

    except Exception as e:
        log.error(f'Humble sync error: {e}', exc_info=True)
        _sync_state.update({'running': False, 'status': '', 'error': str(e)})


# ── Purchase date re-fetch ───────────────────────────────────────────────────────

def fetch_dates_for_appids(appids, on_result):
    """
    Re-fetch purchase dates for specific appids, calling on_result(appid, ts_or_None)
    after each order is fetched so the caller sees incremental progress.
    Uses platform_slug (format: "gamekey/machine_name") to target only the orders needed.
    """
    if not is_connected():
        raise RuntimeError('Humble account not connected')

    db   = get_db()
    rows = db.execute(
        f'SELECT appid, platform_slug FROM games WHERE appid IN ({",".join("?" * len(appids))})',
        appids,
    ).fetchall()
    db.close()

    gamekey_to_appids = {}
    no_slug_appids    = []
    for row in rows:
        slug  = row['platform_slug'] or ''
        parts = slug.split('/', 1)
        if len(parts) == 2 and parts[0]:
            gamekey_to_appids.setdefault(parts[0], []).append(row['appid'])
        else:
            no_slug_appids.append(row['appid'])

    for gamekey, game_appids in gamekey_to_appids.items():
        ts = None
        try:
            resp = requests.get(
                f'{HUMBLE_API}/order/{gamekey}',
                headers=_headers(),
                timeout=20,
                allow_redirects=False,
            )
            if resp.status_code in (301, 302) or not resp.ok:
                raise RuntimeError('Humble session expired — please reconnect')
            ts = _parse_dt(resp.json().get('created'))
        except RuntimeError:
            raise
        except Exception as e:
            log.warning(f'Humble date re-fetch failed for order {gamekey}: {e}')
        for appid in game_appids:
            on_result(appid, ts)
        time.sleep(0.3)

    for appid in no_slug_appids:
        on_result(appid, None)


# ── Download & launch ───────────────────────────────────────────────────────────

if sys.platform == 'win32':
    HUMBLE_DOWNLOAD_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'PlayDate', 'Humble')
elif sys.platform == 'darwin':
    HUMBLE_DOWNLOAD_DIR = os.path.expanduser('~/Library/Application Support/PlayDate/Humble')
else:
    HUMBLE_DOWNLOAD_DIR = os.path.expanduser('~/Games/Humble')

_dl_state = {}   # appid -> {status, filename, received, total, error}
_dl_lock  = threading.Lock()


def _platform_pref():
    if sys.platform == 'win32':
        return ['windows', 'linux', 'mac', 'android']
    if sys.platform == 'darwin':
        return ['mac', 'linux', 'windows', 'android']
    return ['linux', 'windows', 'mac', 'android']


def get_download_url(appid):
    """Fetch a fresh signed download URL. Returns (url, filename) or (None, None)."""
    db  = get_db()
    row = db.execute("SELECT platform_slug FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    slug = (row['platform_slug'] if row else '') or ''
    if not slug or '/' not in slug:
        return None, None
    gamekey, machine_name = slug.split('/', 1)
    try:
        resp = requests.get(
            f'{HUMBLE_API}/order/{gamekey}',
            headers=_headers(),
            timeout=15,
            allow_redirects=False,
        )
        if not resp.ok:
            return None, None
        order = resp.json()
    except Exception as e:
        log.warning(f'Humble: failed to fetch order {gamekey}: {e}')
        return None, None

    for sub in order.get('subproducts', []):
        if sub.get('machine_name') != machine_name:
            continue
        downloads = {d['platform']: d for d in sub.get('downloads', [])}
        for plat in _platform_pref():
            dl = downloads.get(plat)
            if not dl:
                continue
            for struct in dl.get('download_struct', []):
                url = (struct.get('url') or {}).get('web') or ''
                if url:
                    from urllib.parse import urlparse
                    filename = os.path.basename(urlparse(url).path) or struct.get('name', 'download')
                    return url, filename
    return None, None


def get_download_state(appid):
    with _dl_lock:
        return dict(_dl_state.get(appid, {}))


def _safe_dirname(name):
    return re.sub(r'[^\w\s\-.]', '', name).strip()[:80] or 'game'


def _run_download(appid, url, filename, game_dir):
    os.makedirs(game_dir, exist_ok=True)
    dest = os.path.join(game_dir, filename)
    with _dl_lock:
        _dl_state[appid] = {'status': 'downloading', 'filename': filename, 'received': 0, 'total': 0, 'error': None}
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            with _dl_lock:
                _dl_state[appid]['total'] = total
            received = 0
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        received += len(chunk)
                        with _dl_lock:
                            _dl_state[appid]['received'] = received
        if filename.lower().endswith('.zip'):
            with _dl_lock:
                _dl_state[appid]['status'] = 'extracting'
            try:
                with zipfile.ZipFile(dest) as zf:
                    zf.extractall(game_dir)
                os.remove(dest)
                log.info(f'Humble: extracted {filename!r} into {game_dir}')
            except Exception as ze:
                log.warning(f'Humble: zip extraction failed for {filename!r}: {ze}')
        with _dl_lock:
            _dl_state[appid]['status'] = 'done'
        log.info(f'Humble: downloaded {filename!r} to {game_dir}')
        try:
            from .watcher import sync_humble_install_status
            sync_humble_install_status()
        except Exception as _se:
            log.warning(f'Humble: post-download sync failed: {_se}')
    except Exception as e:
        with _dl_lock:
            _dl_state[appid].update({'status': 'error', 'error': str(e)})
        log.error(f'Humble: download failed for appid {appid}: {e}')


_SKIP_EXE_PREFIXES = ('setup', 'install', 'unins', 'uninst', 'redist')

_HELPER_EXE_NAMES = {
    'unitycrashhandler64', 'unitycrashhandler32', 'unitycrashhandler',
    'unityplayer',
    'dxsetup', 'dxwebsetup',
    'vcredist_x64', 'vcredist_x86', 'vc_redist.x64', 'vc_redist.x86',
    'dotnetfx', 'dotnet',
}


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


def _find_executable(game_dir):
    """
    Walk game_dir and return (absolute_path, is_windows_exe).
    Priority: AppImage > native ELF/Mach-O/script > .exe.
    Returns (None, False) if nothing launchable is found.
    """
    is_windows = sys.platform == 'win32'
    is_mac     = sys.platform == 'darwin'
    is_linux   = sys.platform == 'linux'

    # macOS: check for .app bundles first
    if is_mac:
        for entry in os.listdir(game_dir):
            if entry.endswith('.app'):
                app_path = os.path.join(game_dir, entry)
                if os.path.isdir(app_path):
                    macos_dir = os.path.join(app_path, 'Contents', 'MacOS')
                    if os.path.isdir(macos_dir):
                        for candidate in os.listdir(macos_dir):
                            inner = os.path.join(macos_dir, candidate)
                            if os.path.isfile(inner) and os.access(inner, os.X_OK):
                                return inner, False
                    return app_path, False

    appimages, natives, scripts, winexes = [], [], [], []

    for dirpath, dirs, filenames in os.walk(game_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in filenames:
            if fname.startswith('.'):
                continue
            fpath = os.path.join(dirpath, fname)
            ext   = os.path.splitext(fname)[1].lower()
            stem  = os.path.splitext(fname.lower())[0]
            depth = fpath.count(os.sep)

            if ext == '.appimage':
                appimages.append((depth, fpath))
            elif ext in ('.x86_64', '.x86', '.amd64', '.arm64', '.linux'):
                natives.append((depth, fpath))
            elif ext == '.sh' and not is_windows:
                scripts.append((depth, fpath))
            elif not ext and not is_windows and (_is_elf(fpath) or (is_mac and _is_macho(fpath))):
                natives.append((depth, fpath))
            elif ext == '.exe':
                if any(stem.startswith(p) for p in _SKIP_EXE_PREFIXES):
                    continue
                if stem in _HELPER_EXE_NAMES:
                    continue
                winexes.append((depth, fpath))

    for group in (appimages, natives, scripts):
        if group:
            return sorted(group)[0][1], False
    if winexes:
        return sorted(winexes)[0][1], True
    return None, False


def _open_folder(path):
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])


def launch_game(appid):
    is_windows = sys.platform == 'win32'

    db  = get_db()
    row = db.execute(
        "SELECT name, installed, install_path, platform_executable FROM games WHERE appid=?",
        (appid,)
    ).fetchone()
    db.close()
    if row and row['installed']:
        game_dir = row['install_path'] or ''
        if not game_dir or not os.path.isdir(game_dir):
            return {'status': 'error', 'message': 'Game folder not found — it may have been moved or deleted.'}

        cached = row['platform_executable']
        cached_abs = os.path.join(game_dir, cached) if cached else None
        if cached and (os.path.isfile(cached_abs) or (cached_abs.endswith('.app') and os.path.isdir(cached_abs))):
            exe_abs  = cached_abs
            is_win   = cached.lower().endswith('.exe')
        else:
            exe_abs, is_win = _find_executable(game_dir)
            if exe_abs:
                exe_rel = os.path.relpath(exe_abs, game_dir)
                update_game_data(appid, platform_executable=exe_rel)

        if not exe_abs:
            _open_folder(game_dir)
            return {'status': 'launched'}

        from runners.launch import check_launch, popen_checked

        # macOS .app bundle: use `open` command
        if not is_win and exe_abs.endswith('.app') and os.path.isdir(exe_abs):
            try:
                subprocess.Popen(['open', exe_abs])
            except Exception as e:
                return {'status': 'error', 'message': str(e)}
            update_game_data(appid, last_played=int(time.time()))
            return {'status': 'launched'}

        if is_win and not is_windows:
            exe_rel = os.path.relpath(exe_abs, game_dir)
            prefix  = os.path.join(HUMBLE_DOWNLOAD_DIR, '.prefixes', str(appid))
            from runners.proton import launch_game as _proton_launch, get_default_proton
            p = get_default_proton()
            proc = None
            if p:
                try:
                    proc = _proton_launch(game_dir, exe_rel, prefix, proton_path=p['path'])
                except Exception as e:
                    log.warning(f'Humble: Proton launch failed ({e}), falling back to Wine')
                    proc = None
            if proc is None:
                try:
                    from runners.wine import run_in_prefix
                    log.info(f'Humble: launching via Wine: {exe_abs}')
                    proc = run_in_prefix(prefix_path=prefix, exe=exe_abs)
                except Exception as e:
                    log.error(f'Humble: Wine launch failed for {exe_abs!r}: {e}')
                    return {'status': 'error', 'message': str(e)}
            if proc:
                err = check_launch(proc)
                if err:
                    log.error(f'Humble: {err["message"]}')
                    return err
        else:
            try:
                os.chmod(exe_abs, os.stat(exe_abs).st_mode | 0o111)
                _, err = popen_checked([exe_abs], cwd=os.path.dirname(exe_abs))
                if err:
                    log.error(f'Humble: {err["message"]}')
                    return err
            except Exception as e:
                log.error(f'Humble: launch failed for {exe_abs!r}: {e}')
                return {'status': 'error', 'message': str(e)}

        update_game_data(appid, last_played=int(time.time()))
        return {'status': 'launched'}

    url, filename = get_download_url(appid)
    if not url:
        return {'status': 'error', 'message': 'Could not fetch download link — try reconnecting your Humble account.'}

    name = row['name'] if row else 'game'
    with _dl_lock:
        existing = _dl_state.get(appid, {})
    if existing.get('status') == 'downloading':
        return {'status': 'installing', 'install_poller': 'humbleDownloadPoller',
                'message': f'Already downloading {name}…'}

    game_dir = os.path.join(HUMBLE_DOWNLOAD_DIR, _safe_dirname(name))
    update_game_data(appid, install_path=game_dir)
    threading.Thread(target=_run_download, args=(appid, url, filename, game_dir), daemon=True).start()
    return {'status': 'installing', 'install_poller': 'humbleDownloadPoller',
            'message': f'Downloading {name}…'}


def uninstall_game(appid):
    db  = get_db()
    row = db.execute("SELECT name, install_path FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    if not row:
        return False, 'Game not found'
    path = row['install_path'] or ''
    if path and os.path.isdir(path):
        import shutil
        try:
            shutil.rmtree(path)
        except Exception as e:
            return False, str(e)
    update_game_data(appid, installed=0, install_path='')
    return True, 'Uninstalled'
