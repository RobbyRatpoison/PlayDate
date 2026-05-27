"""
ea.py — EA App (formerly Origin) integration for PlayDate.
Handles OAuth2 authentication, library sync, metadata, and cover art.

Auth uses a two-step flow:
  1. Login page via ORIGIN_SPA_ID (response_type=code) — avoids "Service limitations" block
  2. After login redirect, exchange browser cookies for a token via ORIGIN_JS_SDK + prompt=none
Library sync uses the Juno GraphQL API (service-aggregation-layer.juno.ea.com).
"""

import json
import logging
import os
import re
import threading
import time

import requests
from config import BASE_DIR, load_config, _save_config_data
from database import next_negative_appid
from images import save_as_jpg

log = logging.getLogger(__name__)

# ── EA API constants ──────────────────────────────────────────────────────────
# Login page uses ORIGIN_SPA_ID — ORIGIN_JS_SDK direct implicit flow is blocked.
EA_AUTH_URL = (
    'https://accounts.ea.com/connect/auth'
    '?response_type=code'
    '&client_id=ORIGIN_SPA_ID'
    '&display=originXWeb%2Flogin'
    '&locale=en_US'
    '&release_type=prod'
    '&redirect_uri=https%3A%2F%2Fwww.origin.com%2Fviews%2Flogin.html'
)
_EA_LOGIN_DONE_HOSTS = ('www.origin.com', 'origin.com')

_IDENTITY_URL = 'https://gateway.ea.com/proxy/identity/pids/me'
_JUNO_API     = 'https://service-aggregation-layer.juno.ea.com/graphql'
# Supercat used only for single-game metadata rescrape fallback.
_SUPERCAT_URL_TMPL      = 'https://api2.origin.com/ecommerce2/public/supercat/{offer_id}/en_US'


_EA_SLUG_CACHE: dict = {}

def _resolve_ea_store_slug(short_slug):
    """Resolve a Juno gameSlug to the correct ea.com/games/ path.
    Checks the short-slug URL first (1 HEAD request); if 404, probes
    franchise-prefixed variants ('battlefield/battlefield-1') until one
    returns 200. Results are cached in-process to avoid repeat requests."""
    if not short_slug or '/' in short_slug:
        return short_slug
    if short_slug in _EA_SLUG_CACHE:
        return _EA_SLUG_CACHE[short_slug]

    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

    # Build candidates: [original, prefix1/slug, prefix2/slug, ...]
    # Prefixes are formed by progressively removing the trailing hyphen-segment.
    parts = short_slug.split('-')
    candidates = [short_slug] + [
        f"{'-'.join(parts[:i])}/{short_slug}"
        for i in range(len(parts) - 1, 0, -1)
    ]

    result = short_slug
    for candidate in candidates:
        try:
            resp = requests.head(
                f'https://www.ea.com/games/{candidate}',
                timeout=8, allow_redirects=True, headers=headers,
            )
            if resp.status_code == 200:
                result = candidate
                break
        except Exception as e:
            log.debug(f'EA slug probe failed for {candidate!r}: {e}')

    if result != short_slug:
        log.debug(f'EA slug resolved: {short_slug!r} → {result!r}')
    _EA_SLUG_CACHE[short_slug] = result
    return result


_EA_HEADERS = {
    'Accept':            'application/json',
    'X-Origin-Platform': 'Win32',
    'Origin':            'https://www.ea.com',
    'User-Agent':        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 QtWebEngine/5.8.0',
}

VERTICAL_DIR   = os.path.join(BASE_DIR, 'static', 'img', 'library', 'vertical')
HORIZONTAL_DIR = os.path.join(BASE_DIR, 'static', 'img', 'library', 'horizontal')


# ── Token storage ─────────────────────────────────────────────────────────────

def load_ea_tokens():
    data = (load_config() or {}).get('ea_app', {})
    if data.get('access_token'):
        return data
    return None


def is_connected():
    return load_ea_tokens() is not None


def get_display_name():
    tokens = load_ea_tokens()
    return tokens.get('display_name') if tokens else None


def clear_ea_tokens():
    data = load_config() or {}
    data.pop('ea_app', None)
    _save_config_data(data)


# ── Auth flow ─────────────────────────────────────────────────────────────────

def get_auth_url():
    return EA_AUTH_URL


def _get_token_silent(cookies_dict):
    """
    Exchange browser session cookies for an EA access token using prompt=none.
    Returns parsed JSON dict on success, None on failure.
    """
    try:
        resp = requests.get(
            'https://accounts.ea.com/connect/auth',
            params={
                'client_id':    'ORIGIN_JS_SDK',
                'response_type': 'token',
                'redirect_uri':  'nucleus:rest',
                'prompt':        'none',
            },
            cookies=cookies_dict,
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        log.warning(f'EA silent token exchange HTTP {resp.status_code}: {resp.text[:200]}')
    except Exception as e:
        log.warning(f'EA silent token exchange failed: {e}')
    return None


def _save_implicit_token(access_token, expires_in):
    """
    Persist an implicit-grant access token and fetch profile.
    Returns (True, display_name) on success, (False, error_msg) on failure.
    """
    expires_at   = int(time.time()) + int(expires_in or 3600)
    display_name = ''
    pid          = ''
    try:
        r = requests.get(
            _IDENTITY_URL,
            headers={**_EA_HEADERS, 'Authorization': f'Bearer {access_token}',
                     'X-Expand-Results': 'true'},
            timeout=10,
        )
        if r.status_code == 200:
            profile      = r.json().get('pid', {})
            display_name = profile.get('displayName', '')
            pid          = str(profile.get('pidId', ''))
    except Exception as e:
        log.warning(f'EA auth: could not fetch profile: {e}')

    # Identity endpoint omits displayName; fetch it via the personas endpoint.
    if not display_name and pid:
        try:
            auth_hdr = {**_EA_HEADERS, 'Authorization': f'Bearer {access_token}'}
            r = requests.get(
                f'https://gateway.ea.com/proxy/identity/pids/{pid}/personas',
                headers=auth_hdr, timeout=10,
            )
            if r.status_code == 200:
                uris = r.json().get('personas', {}).get('personaUri', [])
                if uris:
                    r2 = requests.get(
                        f'https://gateway.ea.com/proxy/identity{uris[0]}',
                        headers=auth_hdr, timeout=10,
                    )
                    if r2.status_code == 200:
                        display_name = r2.json().get('persona', {}).get('displayName', '')
        except Exception as e:
            log.warning(f'EA auth: could not fetch persona display name: {e}')

    if not display_name:
        display_name = pid

    cfg = load_config() or {}
    cfg['ea_app'] = {
        'access_token':  access_token,
        'refresh_token': '',
        'expires_at':    expires_at,
        'display_name':  display_name,
        'pid':           pid,
    }
    _save_config_data(cfg)
    log.info(f'EA auth: connected as {display_name!r} (pid={pid!r})')
    return True, display_name or 'EA Account'


def exchange_code(raw_input):
    """
    Accept a raw token string pasted by the user (fallback manual path).
    Returns (True, display_name) on success, (False, error_msg) on failure.
    """
    raw = (raw_input or '').strip()
    # Accept bare access token or JSON {"access_token": "..."}
    token = raw
    if raw.startswith('{'):
        try:
            obj   = json.loads(raw)
            token = obj.get('access_token') or ''
        except Exception:
            pass
    if not token or ' ' in token:
        return False, 'Could not extract an access token from the input'
    return _save_implicit_token(token, 3600)


# ── Browser-based login (Selenium Chrome) ─────────────────────────────────────

_browser_login_state = {
    'status': 'idle',   # idle | opening | waiting | success | error | cancelled
    'message': '',
    'username': '',
}
_browser_login_lock   = threading.Lock()
_browser_login_cancel = threading.Event()
_browser_login_driver = None


def get_browser_login_state():
    with _browser_login_lock:
        return dict(_browser_login_state)


def cancel_browser_login():
    _browser_login_cancel.set()
    global _browser_login_driver
    with _browser_login_lock:
        drv = _browser_login_driver
    if drv:
        try:
            drv.quit()
        except Exception:
            pass


def start_browser_login():
    with _browser_login_lock:
        if _browser_login_state['status'] in ('opening', 'waiting'):
            return {'status': 'already_running'}
        _browser_login_cancel.clear()
        _browser_login_state.update({
            'status': 'opening', 'message': 'Opening browser...', 'username': '',
        })
    threading.Thread(target=_run_browser_login, daemon=True).start()
    return {'status': 'started'}


def _run_browser_login():
    global _browser_login_driver
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from urllib.parse import urlparse

    def _set(status, message='', username=''):
        with _browser_login_lock:
            _browser_login_state.update({'status': status, 'message': message, 'username': username})

    opts = Options()
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--window-size=1024,768')
    opts.add_experimental_option('excludeSwitches', ['enable-automation'])
    opts.add_experimental_option('useAutomationExtension', False)

    try:
        svc    = Service()
        driver = webdriver.Chrome(service=svc, options=opts)
        driver.execute_cdp_cmd(
            'Page.addScriptToEvaluateOnNewDocument',
            {'source': "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )
    except Exception as e:
        _set('error', f'Could not launch Chrome: {e}')
        return

    with _browser_login_lock:
        _browser_login_driver = driver

    try:
        _set('waiting', 'Log in to EA — this window will close automatically.')
        driver.get(EA_AUTH_URL)

        deadline = time.time() + 300
        last_url = ''
        while time.time() < deadline:
            if _browser_login_cancel.is_set():
                _set('cancelled', 'Login cancelled.')
                return

            try:
                current = driver.current_url
            except Exception:
                _set('error', 'Browser window was closed.')
                return

            if current != last_url:
                log.info('EA browser login: URL → %s', current[:200])
                last_url = current

            # Detect successful login: EA redirects to origin.com/views/login.html
            try:
                host = urlparse(current).netloc.lower()
            except Exception:
                host = ''
            if any(host == h or host.endswith('.' + h) for h in _EA_LOGIN_DONE_HOSTS):
                _set('waiting', 'Exchanging token...')
                try:
                    # CDP gives us all cookies from all domains in the session.
                    all_cookies_data = driver.execute_cdp_cmd('Network.getAllCookies', {})
                    cookies = {c['name']: c['value'] for c in all_cookies_data.get('cookies', [])}
                except Exception as e:
                    log.warning(f'EA browser login: could not get cookies via CDP: {e}')
                    cookies = {c['name']: c['value'] for c in driver.get_cookies()}

                token_data = _get_token_silent(cookies)
                if token_data and token_data.get('access_token'):
                    ok, result = _save_implicit_token(
                        token_data['access_token'],
                        token_data.get('expires_in', 3600),
                    )
                    if ok:
                        _set('success', 'Connected successfully.', username=result)
                    else:
                        _set('error', result)
                else:
                    _set('error', 'Could not retrieve access token — try again.')
                return

            time.sleep(0.3)

        _set('error', 'Login timed out (5 minutes). Please try again.')

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        with _browser_login_lock:
            _browser_login_driver = None


def get_valid_session():
    """Return a requests.Session with a valid EA Bearer token, or None."""
    tokens = load_ea_tokens()
    if not tokens or not tokens.get('access_token'):
        return None

    # Implicit-flow tokens have no refresh_token; reconnect required when expired.
    if not tokens.get('refresh_token'):
        if int(time.time()) >= tokens.get('expires_at', 0) - 60:
            log.warning('EA access token expired — reconnect required')
            return None
        session = requests.Session()
        session.headers.update(_EA_HEADERS)
        token = tokens['access_token']
        session.headers['Authorization'] = f'Bearer {token}'
        session.headers['AuthToken']      = token
        session.headers['X-AuthToken']    = token
        return session

    from runners.oauth2 import get_valid_session as _get_session
    session = _get_session(
        'ea_app', 'https://accounts.ea.com/connect/token', 'ORIGIN_JS_SDK', '',
        extra_headers=_EA_HEADERS,
    )
    if session:
        token = (load_config() or {}).get('ea_app', {}).get('access_token', '')
        session.headers['AuthToken']   = token
        session.headers['X-AuthToken'] = token
    return session


def _get_pid():
    tokens = load_ea_tokens()
    return (tokens or {}).get('pid') or None


# ── Juno GraphQL helpers ──────────────────────────────────────────────────────

def _juno_query(session, query, variables=None):
    resp = session.post(
        _JUNO_API,
        json={'query': query, 'variables': variables or {}},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if 'errors' in data:
        log.warning(f'Juno API errors: {data["errors"]}')
    return data.get('data', {})


_ENTITLEMENTS_QUERY = '''
query getEntitlements($limit: Int, $next: String) {
    me {
        ownedGameProducts(
            locale: "DEFAULT"
            entitlementEnabled: true
            storefronts: [EA]
            type: [DIGITAL_FULL_GAME, PACKAGED_FULL_GAME]
            platforms: [PC]
            paging: { limit: $limit, next: $next }
        ) {
            next
            items {
                originOfferId
                product {
                    baseItem { gameType }
                }
            }
        }
    }
}'''

_GAMES_QUERY = '''
query getOffers($offerIds: [String!]!) {
    legacyOffers(offerIds: $offerIds, locale: "DEFAULT") {
        offerId: id
        contentId
    }
    gameProducts(offerIds: $offerIds, locale: "DEFAULT") {
        items {
            id
            originOfferId
            gameSlug
            baseItem {
                title
                keyArt  { largestImage { path } }
                packArt { largestImage { path } }
            }
        }
    }
}'''


def _fetch_entitlements(session):
    """Return list of offer IDs for owned PC base games via Juno GraphQL."""
    offer_ids = []
    variables  = {'limit': 100, 'next': None}
    while True:
        data     = _juno_query(session, _ENTITLEMENTS_QUERY, variables)
        products = (data.get('me') or {}).get('ownedGameProducts') or {}
        items    = products.get('items') or []
        for item in items:
            if not item.get('originOfferId'):
                continue
            game_type = ((item.get('product') or {}).get('baseItem') or {}).get('gameType', '')
            if game_type == 'BASE_GAME':
                offer_ids.append(item['originOfferId'])
        variables['next'] = products.get('next')
        if not variables['next']:
            break
    return offer_ids


def _fetch_games_detail(session, offer_ids, chunk_size=100):
    """Fetch name, slug, and art URLs for a list of offer IDs via Juno GraphQL."""
    results = []
    for i in range(0, len(offer_ids), chunk_size):
        chunk = offer_ids[i:i + chunk_size]
        try:
            data      = _juno_query(session, _GAMES_QUERY, {'offerIds': chunk})
            legacy    = data.get('legacyOffers') or []
            products  = (data.get('gameProducts') or {}).get('items') or []
            by_offer  = {p.get('originOfferId'): p for p in products if p.get('originOfferId')}
            by_id     = {p.get('id'): p for p in products if p.get('id')}

            for lo in legacy:
                if not isinstance(lo, dict):
                    continue
                offer_id   = lo.get('offerId') or ''
                content_id = lo.get('contentId') or ''
                product    = by_offer.get(offer_id) or by_id.get(content_id) or by_id.get(offer_id) or {}
                if not product:
                    continue
                base  = product.get('baseItem') or {}
                results.append({
                    'offer_id':     offer_id,
                    'content_id':   content_id,
                    'name':         base.get('title', '').strip() or offer_id,
                    'slug':         product.get('gameSlug', '').strip(),
                    'horiz_url':    ((base.get('keyArt')  or {}).get('largestImage') or {}).get('path', ''),
                    'vert_url':     ((base.get('packArt') or {}).get('largestImage') or {}).get('path', ''),
                })
        except Exception as e:
            log.warning(f'Juno game detail fetch failed for chunk: {e}')
    return results


# ── Entitlement dates ─────────────────────────────────────────────────────────

def _fetch_entitlement_dates(session, pid):
    """EA's entitlements REST API is not accessible via the implicit-flow token. Returns {}."""
    return {}

    log.info(f'EA entitlement dates (Juno): fetched {len(dates)} grant dates')
    return dates


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
        log.error(f'EA library sync thread: {e}', exc_info=True)
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error', 'error': str(e)})


def _do_sync_library():
    from database import get_db, update_game_data as _update_game_data
    from datetime import datetime, timezone, date as _date

    session = get_valid_session()
    if not session:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error',
                                'error': 'Not connected to EA — please reconnect'})
        return

    # Fetch owned game offer IDs via Juno GraphQL
    try:
        with _sync_lock:
            _sync_state['status'] = 'Fetching library…'
        offer_ids = _fetch_entitlements(session)
    except Exception as e:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error',
                                'error': f'Failed to fetch EA library: {e}'})
        return

    log.info(f'EA sync: {len(offer_ids)} owned game offer IDs')

    # Fetch grant dates from nucleus entitlements API
    entitlement_dates = _fetch_entitlement_dates(session, _get_pid())

    db = get_db()
    try:
        existing_rows = db.execute(
            "SELECT appid, platform_id FROM games WHERE platform = 'ea_app'"
        ).fetchall()
        existing    = {row['platform_id'] for row in existing_rows}
        blacklisted = {row[0] for row in db.execute(
            "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
        ).fetchall()}

        # Backfill grant dates for games already in the library
        if entitlement_dates:
            for row in existing_rows:
                grant_ts = entitlement_dates.get(row['platform_id'])
                if grant_ts:
                    db.execute(
                        "UPDATE games SET date_added=? WHERE appid=? AND date_added > ?",
                        (grant_ts, row['appid'], grant_ts),
                    )
            db.commit()
    finally:
        db.close()

    new_offer_ids = [oid for oid in offer_ids if oid not in existing and oid not in blacklisted]
    log.info(f'EA sync: {len(new_offer_ids)} new games')

    # Fetch game details for new games
    game_details = _fetch_games_detail(session, new_offer_ids) if new_offer_ids else []
    # Index by offer_id; fall back to bare offer_id for games not in detail response
    detail_map = {g['offer_id']: g for g in game_details}

    total_new = len(new_offer_ids)
    with _sync_lock:
        _sync_state.update({'phase': 'processing', 'done': 0, 'total': total_new})

    today_ts        = int(datetime.now(timezone.utc).timestamp())
    today           = _date.today().isoformat()
    new_games_count = 0

    db = get_db()
    try:
        for offer_id in new_offer_ids:
            if _sync_cancel.is_set():
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'stopped',
                                        'new_games': new_games_count, 'total_games': len(offer_ids)})
                return

            detail = detail_map.get(offer_id) or {}
            name   = detail.get('name') or offer_id
            slug   = detail.get('slug') or ''

            with _sync_lock:
                _sync_state['current_game'] = name

            next_appid = next_negative_appid(db)
            date_added = entitlement_dates.get(offer_id) or today_ts
            db.execute(
                """INSERT OR IGNORE INTO games
                   (appid, name, platform, platform_id, platform_slug, date_added,
                    completion_status, installed,
                    art_fetched, meta_fetched, cheevos_fetched,
                    protondb_fetched, hltb_fetched)
                   VALUES (?, ?, 'ea_app', ?, ?, ?,
                           'Never Played', 0,
                           '0', '0', '0', '0', '0')""",
                (next_appid, name, offer_id, slug, date_added),
            )
            db.commit()
            log.info(f'EA sync: added {name!r} as appid {next_appid} (offerId {offer_id})')

            # Download art: SGDB first, Juno CDN fallback
            try:
                if _download_art_from_urls(next_appid, detail.get('vert_url', ''),
                                           detail.get('horiz_url', ''), name=name):
                    _update_game_data(next_appid, art_fetched=today)
            except Exception as e:
                log.warning(f'EA art: failed for {name!r}: {e}')

            if slug:
                _update_game_data(next_appid, platform_slug=_resolve_ea_store_slug(slug), meta_fetched=today)

            new_games_count += 1
            with _sync_lock:
                _sync_state['done'] += 1

            if _sync_cancel.is_set():
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'stopped',
                                        'new_games': new_games_count, 'total_games': len(offer_ids)})
                return

            time.sleep(0.3)
    finally:
        db.close()

    try:
        from .watcher import sync_ea_install_status
        sync_ea_install_status()
    except Exception as e:
        log.warning(f'EA sync: install status refresh failed: {e}')

    from database import auto_detect_duplicates
    from plugins import get_platform_priority
    dupes = auto_detect_duplicates(platform_priority=get_platform_priority())

    with _sync_lock:
        _sync_state.update({
            'running': False, 'phase': 'done',
            'new_games': new_games_count, 'total_games': len(offer_ids),
            'duplicates_detected': dupes,
        })


# ── Art download ──────────────────────────────────────────────────────────────

def _download_art_from_urls(appid, vert_url, horiz_url, name=''):
    """
    Download art for an EA game. Tries SGDB first (by name), falls back to Juno CDN URLs.
    Returns True on any success.
    """
    from images import _sgdb_search_game_id, download_vertical, download_horizontal
    vert_path  = os.path.join(VERTICAL_DIR,   f'{appid}.jpg')
    horiz_path = os.path.join(HORIZONTAL_DIR, f'{appid}.jpg')
    success    = False

    # SGDB first
    sgdb_id = _sgdb_search_game_id(name) if name else None
    if sgdb_id:
        if not os.path.exists(vert_path):
            if download_vertical(appid, sgdb_id=sgdb_id):
                success = True
        if not os.path.exists(horiz_path):
            if download_horizontal(appid, sgdb_id=sgdb_id):
                success = True
        if success:
            return True

    # Juno CDN fallback
    for url, dest in [(vert_url, vert_path), (horiz_url, horiz_path)]:
        if not url or os.path.exists(dest):
            continue
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200 and len(r.content) > 1000:
                save_as_jpg(r.content, dest)
                success = True
        except Exception as e:
            log.warning(f'EA art download failed [{dest}]: {e}')
    return success


def _download_art(session, appid, offer_id):
    """
    Download art for a game via supercat fallback (used during rescrape).
    Returns True on any success.
    """
    vert_path  = os.path.join(VERTICAL_DIR,   f'{appid}.jpg')
    horiz_path = os.path.join(HORIZONTAL_DIR, f'{appid}.jpg')
    if os.path.exists(vert_path) and os.path.exists(horiz_path):
        return True

    try:
        url  = _SUPERCAT_URL_TMPL.format(offer_id=offer_id)
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return False

        offer      = resp.json()
        offer      = offer.get('offerGroup') or offer.get('offer') or offer
        image_sets = offer.get('imageSets') or {}
        if isinstance(image_sets, list):
            image_sets = {img.get('type', ''): img for img in image_sets}

        type_map = {
            'packageArtLarge':             vert_path,
            'packageArtSmall':             vert_path,
            'heroArtLarge':                horiz_path,
            'backgroundImageAboveTheFold': horiz_path,
            'image':                       horiz_path,
        }
        downloaded = set()
        success    = False
        for img_type, dest in type_map.items():
            if dest in downloaded or os.path.exists(dest):
                continue
            img_data = image_sets.get(img_type, {})
            url = (img_data.get('url') or img_data.get('imageUrl') or
                   img_data.get('imagePath') or '').strip()
            if not url:
                continue
            try:
                r = requests.get(url, timeout=20)
                if r.status_code == 200 and len(r.content) > 1000:
                    save_as_jpg(r.content, dest)
                    downloaded.add(dest)
                    success = True
            except Exception as e:
                log.warning(f'EA art download failed for {offer_id} [{img_type}]: {e}')
        return success

    except Exception as e:
        log.warning(f'EA art fetch failed for offerId {offer_id}: {e}')
        return False


# ── Metadata ──────────────────────────────────────────────────────────────────

def _fetch_supercat(session, offer_id):
    """Fetch game metadata via supercat (fallback for rescrape). Returns partial meta dict or None."""
    try:
        url  = _SUPERCAT_URL_TMPL.format(offer_id=offer_id)
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            log.warning(f'EA supercat HTTP {resp.status_code} for offerId {offer_id}')
            return None

        data  = resp.json()
        offer = data.get('offerGroup') or data.get('offer') or data
        meta  = {}

        name = (offer.get('displayName') or offer.get('i18n', {}).get('displayName', '')
                or offer.get('masterTitle', '')).strip()
        if name:
            meta['name'] = name

        genres = offer.get('genres') or []
        if isinstance(genres, list) and genres:
            meta['genres'] = ','.join(
                g.get('genreName', g) if isinstance(g, dict) else g for g in genres
            )

        release_str = ''
        if isinstance(offer.get('platforms', ''), list) and offer['platforms']:
            release_str = offer['platforms'][0].get('releaseDate', '')
        if not release_str:
            release_str = offer.get('offerReleaseDate') or offer.get('releaseDate') or ''
        if release_str:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(release_str.replace('Z', '+00:00'))
                meta['release_date'] = int(dt.timestamp())
            except Exception:
                pass

        slug = (offer.get('slug') or offer.get('i18n', {}).get('slug', '') or '').strip()
        if slug:
            meta['platform_slug'] = slug

        desc = (offer.get('shortDescription') or offer.get('i18n', {})
                .get('shortDescription', '')).strip()
        if desc:
            meta['_description'] = desc

        return meta or None

    except Exception as e:
        log.warning(f'EA supercat failed for offerId {offer_id}: {e}')
        return None


# ── Single-game rescrape ──────────────────────────────────────────────────────

def scrape_single(appid):
    """Re-fetch metadata and art for one EA game. Returns dict or None."""
    session = get_valid_session()
    if not session:
        return None

    from database import get_db
    db  = get_db()
    row = db.execute(
        "SELECT platform_id FROM games WHERE appid = ? AND platform = 'ea_app'",
        (appid,)
    ).fetchone()
    db.close()

    if not row or not row['platform_id']:
        return None

    offer_id = row['platform_id']

    # Try Juno for art URLs first
    detail_list = _fetch_games_detail(session, [offer_id])
    detail      = detail_list[0] if detail_list else {}

    # Supercat for rich metadata (genres, release date, description)
    meta = _fetch_supercat(session, offer_id) or {}

    vert_path  = os.path.join(VERTICAL_DIR,   f'{appid}.jpg')
    horiz_path = os.path.join(HORIZONTAL_DIR, f'{appid}.jpg')
    if not os.path.exists(vert_path) or not os.path.exists(horiz_path):
        game_name = detail.get('name') or meta.get('name') or ''
        try:
            _download_art_from_urls(appid, detail.get('vert_url', ''),
                                    detail.get('horiz_url', ''), name=game_name)
        except Exception as e:
            log.warning(f'EA scrape-single: art re-fetch failed for appid {appid}: {e}')
    if detail.get('name') and not meta.get('name'):
        meta['name'] = detail['name']
    if detail.get('slug') and not meta.get('platform_slug'):
        meta['platform_slug'] = _resolve_ea_store_slug(detail['slug'])

    from datetime import date
    meta['meta_fetched'] = date.today().isoformat()
    return meta


def fetch_description(appid, platform_id):
    """Return a plain-text description for an EA game, or None."""
    session = get_valid_session()
    if not session:
        return None
    meta = _fetch_supercat(session, platform_id)
    return (meta or {}).get('_description') or None
