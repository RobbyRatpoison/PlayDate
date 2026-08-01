import difflib
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from config import BASE_DIR, load_config, _save_config_data
from database import get_db, next_negative_appid, update_game_data
from images import save_as_jpg

log = logging.getLogger(__name__)

LIBRARY_URL    = 'https://www.indiegala.com/library'
VERTICAL_DIR   = os.path.join(BASE_DIR, 'static', 'img', 'library', 'vertical')
HORIZONTAL_DIR = os.path.join(BASE_DIR, 'static', 'img', 'library', 'horizontal')


class SessionExpired(Exception):
    """Raised when a library fetch gets redirected to /login -- the saved
    session cookie is present but no longer valid. Distinct from a plain
    "game not found," which single-game rescrape would otherwise report
    identically (an empty/partial library walk looks the same as a real
    404 unless the redirect is checked and surfaced separately)."""
    pass

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
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }


def connect(cookie):
    cookie = cookie.strip().strip('"')
    try:
        resp = requests.get(LIBRARY_URL, headers=_headers(cookie), timeout=15,
                            allow_redirects=True)
        log.info(f'IndieGala connect: HTTP {resp.status_code}, final_url={resp.url!r}')
        if resp.status_code != 200:
            return False, f'Could not load IndieGala library (HTTP {resp.status_code}).'
        if '/login' in resp.url or 'profile-private-page-library' not in resp.text:
            return False, 'Session cookie appears invalid — log in to IndieGala and try again.'
    except Exception as e:
        log.warning(f'IndieGala connect exception: {e}')
        return False, f'Connection failed: {e}'
    _save_cfg({'session_cookie': cookie, 'username': 'Connected'})
    log.info('IndieGala connected')
    return True, 'Connected'


def disconnect():
    cfg = load_config() or {}
    cfg.pop('indiegala', None)
    _save_config_data(cfg)


# ── Games directory ──────────────────────────────────────────────────────────────

if sys.platform == 'win32':
    _DEFAULT_GAMES_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'PlayDate', 'IndieGala')
elif sys.platform == 'darwin':
    _DEFAULT_GAMES_DIR = os.path.expanduser('~/Library/Application Support/PlayDate/IndieGala')
else:
    _DEFAULT_GAMES_DIR = os.path.expanduser('~/Games/IndieGala')


def get_games_dir():
    return _cfg().get('games_dir') or _DEFAULT_GAMES_DIR


def set_games_dir(path):
    cfg = _cfg()
    cfg['games_dir'] = path
    _save_cfg(cfg)


# ── Install detection ────────────────────────────────────────────────────────────

_FUZZY_THRESHOLD = 0.65


def _normalize_name(name):
    name = name.lower()
    name = re.sub(r'[^\w\s]', ' ', name)
    return re.sub(r'\s+', ' ', name).strip()


def _fuzzy_score(a, b):
    return difflib.SequenceMatcher(None, _normalize_name(a), _normalize_name(b)).ratio()


def _find_best_match(folder_name, candidates):
    """candidates: list of (appid, name). Returns (appid, name) or None."""
    best_score = 0.0
    best = None
    folder_norm = _normalize_name(folder_name)
    for appid, name in candidates:
        score = difflib.SequenceMatcher(None, folder_norm, _normalize_name(name)).ratio()
        if score > best_score:
            best_score = score
            best = (appid, name)
    return best if best_score >= _FUZZY_THRESHOLD else None


def sync_indiegala_install_status():
    games_dir = get_games_dir()
    db = get_db()
    rows = db.execute(
        "SELECT appid, name, install_path FROM games WHERE platform='indiegala'"
    ).fetchall()

    # Check games that already have install_path set
    already_linked = set()
    for row in rows:
        path = row['install_path'] or ''
        if path and os.path.isdir(path):
            db.execute("UPDATE games SET installed=1 WHERE appid=?", (row['appid'],))
            already_linked.add(path)
        elif path and not os.path.isdir(path):
            db.execute("UPDATE games SET installed=0, install_path='' WHERE appid=?", (row['appid'],))

    # Fuzzy-match unlinked folders against unlinked games
    if os.path.isdir(games_dir):
        unlinked_games = [(row['appid'], row['name']) for row in rows if not (row['install_path'] or '')]
        for entry in os.scandir(games_dir):
            if not entry.is_dir() or entry.path in already_linked:
                continue
            match = _find_best_match(entry.name, unlinked_games)
            if match:
                appid, _ = match
                db.execute(
                    "UPDATE games SET install_path=?, installed=1 WHERE appid=?",
                    (entry.path, appid),
                )
                unlinked_games = [(a, n) for a, n in unlinked_games if a != appid]
                already_linked.add(entry.path)

    db.commit()
    db.close()
    log.info('IndieGala install status synced')


# ── HTML parsing ────────────────────────────────────────────────────────────────

_PROD_ID_RE    = re.compile(r'/products/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/')
_SHOWCASE_RE   = re.compile(r'(https?://(?:www\.)?indiegala\.com/library/showcase/[^\s"\']+)')


_SHOWCASE_ID_RE = re.compile(r"showShowcaseContents\('(\d+)'")


def _parse_page(html):
    """Return list of dicts with prod_id, prod_name, date_str, img_url, showcase_url, store_url."""
    soup  = BeautifulSoup(html, 'html.parser')
    games = []
    for card in soup.find_all('figcaption',
                               class_='profile-private-page-library-title-padding-showcase'):
        title_el = card.find(class_='profile-private-page-library-title')
        if not title_el:
            continue
        title    = title_el.get_text(strip=True)
        date_els = card.find_all(class_='profile-private-page-library-date-showcase')
        date_str = date_els[1].get_text(strip=True) if len(date_els) > 1 else ''

        fig          = card.find_previous_sibling('figure')
        img_url      = ''
        prod_id      = ''
        showcase_url = ''
        store_url = ''
        if fig:
            # The figure or a parent <a> may link directly to the showcase page
            wrap = fig.find_parent('a', href=True) or fig.find('a', href=True)
            if wrap:
                href = wrap['href']
                if '/library/showcase/' in href:
                    showcase_url = href if href.startswith('http') else f'https://www.indiegala.com{href}'

            img = fig.find('img')
            if img:
                # Raw HTML uses data-src (JS swaps to src in browser)
                src = img.get('data-src') or img.get('src') or ''
                img_url = src
                m = _PROD_ID_RE.search(src)
                if m:
                    prod_id = m.group(1)
                    if not showcase_url:
                        showcase_url = f'https://www.indiegala.com/library/showcase/{prod_id}'

            # The public store/info page lives in a separate panel elsewhere on
            # the page, cross-referenced by the numeric id in this card's
            # showShowcaseContents('<id>', ...) onclick handler -- not derivable
            # from the card itself or guessable from the name. Its domain varies
            # by how the game was obtained: freebies.indiegala.com for
            # GalaFreebies picks, a developer's own *.indiegala.com subdomain for
            # dev-made-free games, or other store domains for bundle-sourced
            # games -- so don't hardcode a domain, just exclude links back into
            # IndieGala's own internal library (which just duplicate
            # showcase_url, not a real store page).
            item_li = card.find_parent('li')
            click_a = item_li.find('a', class_='fit-click') if item_li else None
            id_m = _SHOWCASE_ID_RE.search((click_a.get('onclick') or '') if click_a else '')
            if id_m:
                sub = soup.find(id=f'showcase-{id_m.group(1)}')
                title_a = sub.find('a', class_='library-showcase-title', href=True) if sub else None
                if title_a:
                    href = title_a['href']
                    if href.startswith('http') and '/library/showcase/' not in href:
                        store_url = href

        if not prod_id:
            continue
        games.append({'prod_id': prod_id, 'prod_name': title,
                      'date_str': date_str, 'img_url': img_url,
                      'showcase_url': showcase_url, 'store_url': store_url})
    return games


def _parse_total_pages(html):
    """Extract total page count from pagination HTML, default 1."""
    soup = BeautifulSoup(html, 'html.parser')
    # IndieGala pagination links: href="/library?page=N" or similar
    pages = [1]
    for a in soup.select('a[href*="page="]'):
        href = a.get('href', '')
        m = re.search(r'page=(\d+)', href)
        if m:
            pages.append(int(m.group(1)))
    return max(pages)


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
    try:
        db = get_db()
        existing = {
            row['platform_id']: (row['appid'], row['platform_slug'], row['platform_appname'])
            for row in db.execute(
                "SELECT appid, platform_id, platform_slug, platform_appname FROM games WHERE platform='indiegala'"
            ).fetchall()
        }
        blacklisted = {
            row[0]
            for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()
        }

        page        = 1
        added       = 0
        updated     = 0
        fetch_error = None

        # Not driven by _parse_total_pages() -- that trusts the page-number
        # links visible in page 1's own HTML, which undercounts the real
        # total if IndieGala's pagination widget only ever shows a nearby
        # window of pages (e.g. "1 2 3 ... Next") rather than every page
        # number up front (reported: sync stopped after page 1 despite more
        # games existing). Fetching until an empty page comes back doesn't
        # depend on correctly parsing that widget at all. MAX_PAGES is just
        # a runaway-loop safety net, not the real stopping condition.
        MAX_PAGES = 200
        while page <= MAX_PAGES:
            _sync_state['status'] = f'Fetching page {page}…'
            url = LIBRARY_URL if page == 1 else f'{LIBRARY_URL}/showcase/{page}/'
            try:
                resp = requests.get(url, headers=_headers(), timeout=20,
                                    allow_redirects=True)
                if resp.status_code != 200 or '/login' in resp.url:
                    log.warning(f'IndieGala: page {page} returned {resp.status_code} / {resp.url}')
                    if '/login' in resp.url:
                        fetch_error = 'Session expired — please reconnect IndieGala in the Plugins settings.'
                    elif page == 1:
                        fetch_error = f'Could not load IndieGala library (HTTP {resp.status_code}).'
                    break
            except Exception as e:
                log.warning(f'IndieGala: page {page} fetch failed: {e}')
                if page == 1:
                    fetch_error = f'Connection failed: {e}'
                break

            if page == 1:
                log.info(f'IndieGala sync: _parse_total_pages() says {_parse_total_pages(resp.text)} page(s) '
                         f'(informational only -- actual stop condition is an empty page)')

            games = _parse_page(resp.text)
            log.info(f'IndieGala sync: page {page} — {len(games)} games parsed')
            if not games:
                break

            for game in games:
                prod_id = game['prod_id']
                if prod_id in blacklisted:
                    continue

                if prod_id in existing:
                    updated += 1
                    ex_appid, ex_slug, ex_appname = existing[prod_id]
                    fresh_showcase_url = game.get('showcase_url') or ''
                    fresh_store_url = game.get('store_url') or ''
                    # platform_slug used to hold the showcase (download) URL
                    # before it was repointed at the store page -- this
                    # both backfills platform_appname (the actual download
                    # URL launch_game() needs) from any stale rows and
                    # (re)writes platform_slug with the correct store URL.
                    if not ex_appname and fresh_showcase_url:
                        db.execute(
                            "UPDATE games SET platform_appname=? WHERE appid=?",
                            (fresh_showcase_url, ex_appid),
                        )
                    if fresh_store_url and fresh_store_url != ex_slug:
                        db.execute(
                            "UPDATE games SET platform_slug=? WHERE appid=?",
                            (fresh_store_url, ex_appid),
                        )
                    db.commit()
                    continue

                prod_name    = game['prod_name']
                date_ts      = _parse_dt(game['date_str']) or int(time.time())
                showcase_url = game.get('showcase_url') or ''
                store_url = game.get('store_url') or ''
                appid        = next_negative_appid(db)

                db.execute(
                    """INSERT OR IGNORE INTO games
                       (appid, name, platform, platform_id, platform_slug, platform_appname,
                        date_added, completion_status, installed,
                        art_fetched, meta_fetched, cheevos_fetched,
                        protondb_fetched, hltb_fetched)
                       VALUES (?, ?, 'indiegala', ?, ?, ?,
                               ?, 'Never Played', 0,
                               '0', '0', '0', '0', '0')""",
                    (appid, prod_name, prod_id, store_url, showcase_url, date_ts),
                )
                db.commit()
                existing[prod_id] = (appid, store_url, showcase_url)
                added += 1

                if game['img_url']:
                    _download_art(appid, game['img_url'])

            page += 1
            time.sleep(0.5)

        db.close()
        if fetch_error:
            _sync_state.update({
                'running': False,
                'status': '',
                'added': added, 'updated': updated,
                'error': fetch_error,
            })
            log.warning(f'IndieGala sync failed: {fetch_error}')
        else:
            _sync_state.update({
                'running': False,
                'status': f'Done — {added} added, {updated} already in library.',
                'added': added, 'updated': updated,
            })
            log.info(f'IndieGala sync complete: {added} added, {updated} existing')

    except Exception as e:
        log.error(f'IndieGala sync error: {e}', exc_info=True)
        _sync_state.update({'running': False, 'status': '', 'error': str(e)})


# ── Purchase date re-fetch ───────────────────────────────────────────────────

def fetch_dates_for_appids(appids):
    """
    Re-scrape IndieGala library pages to find purchase dates for the given appids.
    Returns {appid: unix_ts_or_None}.
    """
    db   = get_db()
    rows = db.execute(
        f'SELECT appid, platform_id FROM games WHERE appid IN ({",".join("?" * len(appids))})',
        appids,
    ).fetchall()
    db.close()

    prod_id_to_appid = {row['platform_id']: row['appid'] for row in rows if row['platform_id']}
    still_needed     = set(prod_id_to_appid)
    result           = {appid: None for appid in appids}

    page = 1
    # See _run_sync()'s comment: not bounded by _parse_total_pages(), which
    # undercounts if IndieGala's pagination widget only shows a nearby
    # window of page numbers. Stops on an empty page instead.
    MAX_PAGES = 200
    while page <= MAX_PAGES and still_needed:
        url = LIBRARY_URL if page == 1 else f'{LIBRARY_URL}/showcase/{page}/'
        try:
            resp = requests.get(url, headers=_headers(), timeout=20, allow_redirects=True)
            if resp.status_code != 200 or '/login' in resp.url:
                break
        except Exception as e:
            log.warning(f'IndieGala date re-fetch page {page} failed: {e}')
            break

        games = _parse_page(resp.text)
        if not games:
            break

        for game in games:
            pid = game['prod_id']
            if pid in still_needed:
                ts = _parse_dt(game['date_str'])
                result[prod_id_to_appid[pid]] = ts
                still_needed.discard(pid)

        page += 1
        time.sleep(0.5)

    return result


# ── Single/bulk metadata re-fetch ────────────────────────────────────────────────

# IndieGala has no per-product API -- the only source for a game's
# store/showcase links is the same paginated library listing _run_sync()
# walks. Cached briefly so a bulk-rescrape batch touching several IndieGala
# games shares one walk instead of each game re-walking the whole library
# from page 1 (bulk_rescrape_games calls plugin.rescrape() once per appid).
_rescrape_cache     = {'ts': 0, 'games': {}}
_rescrape_lock      = threading.Lock()
_RESCRAPE_CACHE_TTL = 120  # seconds


def _fetch_full_library():
    """Walk every library page, returning {prod_id: game_dict}."""
    games_by_id = {}
    page = 1
    MAX_PAGES = 200
    while page <= MAX_PAGES:
        url = LIBRARY_URL if page == 1 else f'{LIBRARY_URL}/showcase/{page}/'
        try:
            resp = requests.get(url, headers=_headers(), timeout=20, allow_redirects=True)
            if '/login' in resp.url:
                raise SessionExpired('IndieGala session expired')
            if resp.status_code != 200:
                break
        except SessionExpired:
            raise
        except Exception as e:
            log.warning(f'IndieGala rescrape: page {page} fetch failed: {e}')
            break

        games = _parse_page(resp.text)
        if not games:
            break
        for game in games:
            games_by_id[game['prod_id']] = game

        page += 1
        time.sleep(0.5)

    return games_by_id


def rescrape(appid):
    """
    Re-fetch store/showcase links for a single IndieGala game.
    Returns an update dict ready for update_game_data(), or None if the game
    can't be found or the library can't be reached.
    """
    db  = get_db()
    row = db.execute(
        "SELECT platform_id FROM games WHERE appid=? AND platform='indiegala'", (appid,)
    ).fetchone()
    db.close()
    if not row or not row['platform_id']:
        return None
    prod_id = row['platform_id']

    with _rescrape_lock:
        if time.time() - _rescrape_cache['ts'] > _RESCRAPE_CACHE_TTL:
            _rescrape_cache['games'] = _fetch_full_library()
            _rescrape_cache['ts']    = time.time()
        game = _rescrape_cache['games'].get(prod_id)

    if not game:
        return None

    meta = {'meta_fetched': datetime.now(timezone.utc).date().isoformat()}
    if game.get('store_url'):
        meta['platform_slug'] = game['store_url']
    if game.get('showcase_url'):
        meta['platform_appname'] = game['showcase_url']
    return meta


# ── Art ─────────────────────────────────────────────────────────────────────────

def _download_art(appid, img_url):
    vert_path = os.path.join(VERTICAL_DIR, f'{appid}.jpg')
    if os.path.exists(vert_path):
        return
    try:
        r = requests.get(img_url, timeout=15)
        if r.status_code == 200 and len(r.content) > 500:
            save_as_jpg(r.content, vert_path)
            log.info(f'IndieGala art saved for appid {appid}')
    except Exception as e:
        log.warning(f'IndieGala art download failed for appid {appid}: {e}')



# ── Launch ───────────────────────────────────────────────────────────────────────

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


_SKIP_EXE_PREFIXES = ('setup', 'install', 'unins', 'uninst', 'redist')
_HELPER_EXE_NAMES  = {
    'unitycrashhandler64', 'unitycrashhandler32', 'unitycrashhandler', 'unityplayer',
    'dxsetup', 'dxwebsetup', 'vcredist_x64', 'vcredist_x86', 'vc_redist.x64', 'vc_redist.x86',
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
    is_windows = sys.platform == 'win32'
    is_mac     = sys.platform == 'darwin'

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


def _safe_dirname(name):
    return re.sub(r'[^\w\s\-.]', '', name).strip()[:80] or 'game'


def _maybe_unzip(game_dir):
    """If game_dir has zip files but no executable, extract them in place.

    Normalizes Windows-style backslash paths in zip entries so they extract
    as proper subdirectories on Linux rather than files with backslashes in
    their names.
    """
    import zipfile
    has_exe = bool(_find_executable(game_dir)[0])
    if has_exe:
        return
    for fname in os.listdir(game_dir):
        if not fname.lower().endswith('.zip'):
            continue
        zpath = os.path.join(game_dir, fname)
        try:
            with zipfile.ZipFile(zpath) as zf:
                for member in zf.infolist():
                    # Normalize Windows backslashes to forward slashes
                    normalized = member.filename.replace('\\', '/')
                    dest = os.path.join(game_dir, normalized)
                    if member.is_dir() or normalized.endswith('/'):
                        os.makedirs(dest, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with zf.open(member) as src, open(dest, 'wb') as dst:
                            dst.write(src.read())
            os.remove(zpath)
            log.info(f'IndieGala: extracted {fname!r} in {game_dir}')
        except Exception as e:
            log.warning(f'IndieGala: zip extraction failed for {fname!r}: {e}')


def launch_game(appid):
    is_windows = sys.platform == 'win32'

    db  = get_db()
    row = db.execute(
        "SELECT name, platform_id, platform_appname, installed, install_path, platform_executable "
        "FROM games WHERE appid=?", (appid,)
    ).fetchone()
    db.close()

    if row and row['installed']:
        game_dir = row['install_path'] or ''
        if not game_dir or not os.path.isdir(game_dir):
            return {'status': 'error', 'message': 'Game folder not found — it may have been moved or deleted.'}

        _maybe_unzip(game_dir)

        cached     = row['platform_executable']
        cached_abs = os.path.join(game_dir, cached) if cached else None
        if cached and (os.path.isfile(cached_abs) or (cached_abs.endswith('.app') and os.path.isdir(cached_abs))):
            exe_abs = cached_abs
            is_win  = cached.lower().endswith('.exe')
        else:
            exe_abs, is_win = _find_executable(game_dir)
            if exe_abs:
                update_game_data(appid, platform_executable=os.path.relpath(exe_abs, game_dir))

        if not exe_abs:
            _open_folder(game_dir)
            return {'status': 'launched'}

        from runners.launch import check_launch, popen_checked

        if not is_win and exe_abs.endswith('.app') and os.path.isdir(exe_abs):
            try:
                subprocess.Popen(['open', exe_abs])
            except Exception as e:
                return {'status': 'error', 'message': str(e)}
            update_game_data(appid, last_played=int(time.time()))
            return {'status': 'launched'}

        if is_win and not is_windows:
            from runners.proton import launch_game as _proton_launch, get_default_proton
            prefix = os.path.join(get_games_dir(), '.prefixes', str(appid))
            p      = get_default_proton()
            proc   = None
            if p:
                try:
                    proc = _proton_launch(game_dir, os.path.relpath(exe_abs, game_dir),
                                         prefix, proton_path=p['path'])
                except Exception as e:
                    log.warning(f'IndieGala: Proton launch failed ({e}), falling back to Wine')
                    proc = None
            if proc is None:
                try:
                    from runners.wine import run_in_prefix
                    proc = run_in_prefix(prefix_path=prefix, exe=exe_abs)
                except Exception as e:
                    return {'status': 'error', 'message': str(e)}
            if proc:
                err = check_launch(proc)
                if err:
                    return err
        else:
            try:
                os.chmod(exe_abs, os.stat(exe_abs).st_mode | 0o111)
                _, err = popen_checked([exe_abs], cwd=os.path.dirname(exe_abs))
                if err:
                    return err
            except Exception as e:
                return {'status': 'error', 'message': str(e)}

        update_game_data(appid, last_played=int(time.time()))
        return {'status': 'launched'}

    # Not installed — create the game subfolder and open it so the user can drop files in
    name     = (row['name'] if row else '') or 'game'
    game_dir = os.path.join(get_games_dir(), _safe_dirname(name))
    os.makedirs(game_dir, exist_ok=True)
    update_game_data(appid, install_path=game_dir)
    _open_folder(game_dir)

    showcase_url = (row['platform_appname'] if row else '') or ''
    if not showcase_url and row and row['platform_id']:
        showcase_url = f'https://www.indiegala.com/library/showcase/{row["platform_id"]}'
    if showcase_url:
        _open_browser(showcase_url)

    return {
        'status':  'not_installed',
        'message': 'Game folder opened — drop the downloaded files in, then launch again.',
    }


# ── Uninstall & folder management ────────────────────────────────────────────────

def uninstall_game(appid):
    db  = get_db()
    row = db.execute("SELECT name, install_path FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    if not row:
        return False, 'Game not found'
    path = row['install_path'] or ''
    if path and os.path.isdir(path):
        try:
            shutil.rmtree(path)
        except Exception as e:
            return False, str(e)
    update_game_data(appid, installed=0, install_path='', platform_executable='')
    return True, 'Uninstalled'


def link_folder(appid, folder_path):
    if not os.path.isdir(folder_path):
        return False, 'Folder does not exist'
    update_game_data(appid, install_path=folder_path, installed=1, platform_executable='')
    return True, 'Linked'
