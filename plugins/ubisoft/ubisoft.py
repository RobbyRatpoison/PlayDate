"""
ubisoft.py — Ubisoft Connect integration for PlayDate.
Handles authentication, library sync, metadata, and cover art.

Auth uses Ubisoft's SSO (not standard OAuth2 bearer tokens).
Session tickets use the Ubi_v1 scheme; rememberMeTickets are used for refresh.
"""

import json
import logging
import os
import threading
import time

import requests
from config import CONFIG_PATH, BASE_DIR, load_config, _save_config_data
from database import next_negative_appid
from images import save_as_jpg
from utils import review_score_label

log = logging.getLogger(__name__)

# ── Ubisoft API constants ─────────────────────────────────────────────────────
# Client ID for Ubisoft Connect PC launcher (public, documented in community research)
UBI_APP_ID    = 'f686byxt'
UBI_LOGIN_URL = (
    'https://connect.ubisoft.com/login'
    '?appId=f686byxt&lang=en-US'
    '&nextUrl=https%3A%2F%2Fconnect.ubisoft.com%2Fready'
    '&noAuthRegWall='
)

_SESSIONS_URL  = 'https://public-ubiservices.ubi.com/v3/profiles/sessions'
_INVENTORY_URL = 'https://inventory.api.ubisoft.com/v1/inventories'
_SPACES_URL    = 'https://public-ubiservices.ubi.com/v1/spaces'
_PRODUCTS_URL  = 'https://consumer-product.ubisoft.com/api/product/products'

_UBI_HEADERS = {
    'Ubi-AppId':                 UBI_APP_ID,
    'Ubi-RequestedPlatformType': 'uplay',
    'Ubi-LocaleCode':            'en-US',
    'Content-Type':              'application/json',
    'User-Agent':                'UbiServices_SDK_2022.Release.9_PC64_ansi_static',
}

VERTICAL_DIR   = os.path.join(BASE_DIR, 'static', 'img', 'library', 'vertical')
HORIZONTAL_DIR = os.path.join(BASE_DIR, 'static', 'img', 'library', 'horizontal')


# ── Token storage ─────────────────────────────────────────────────────────────

def load_ubi_tokens():
    data = (load_config() or {}).get('ubisoft', {})
    if data.get('ticket') and data.get('remember_me_ticket'):
        return data
    return None


def is_connected():
    return load_ubi_tokens() is not None


def get_display_name():
    tokens = load_ubi_tokens()
    return tokens.get('username') if tokens else None


def clear_ubi_tokens():
    data = load_config() or {}
    data.pop('ubisoft', None)
    _save_config_data(data)


# ── Auth flow ─────────────────────────────────────────────────────────────────

def get_auth_url():
    return UBI_LOGIN_URL


def _post_sessions(auth_header, body=None):
    """
    POST to Ubisoft sessions endpoint. Returns raw response dict or raises ValueError.
    auth_header: full value of the Authorization header (e.g. 'Ubi_v1 t=...' or 'Basic ...')
    """
    headers = dict(_UBI_HEADERS)
    headers['Authorization'] = auth_header
    resp = requests.post(_SESSIONS_URL, headers=headers, json=body or {}, timeout=15)
    if resp.status_code not in (200, 201):
        raise ValueError(f'Ubisoft sessions failed (HTTP {resp.status_code}): {resp.text[:200]}')
    return resp.json()


def exchange_code(raw_input):
    """
    Exchange a Ubisoft authorization code for session tokens.
    Accepts the raw code or the full redirect URL containing it.
    Returns (True, username) on success, (False, error_msg) on failure.
    """
    code = _extract_code(raw_input)
    if not code:
        return False, 'Could not extract an authorization code from the input'

    import base64
    b64 = base64.b64encode(f'{UBI_APP_ID}:'.encode()).decode()
    try:
        data = _post_sessions(
            f'Basic {b64}',
            {'authorizationCode': code, 'grantType': 'authorization_code'},
        )
    except ValueError as e:
        return False, str(e)

    return _store_session(data)


def _extract_code(raw):
    """Extract auth code from a raw string, JSON blob, or redirect URL."""
    raw = raw.strip()
    # JSON blob: {"code": "..."} or {"authorizationCode": "..."}
    if raw.startswith('{'):
        try:
            obj = json.loads(raw)
            code = obj.get('authorizationCode') or obj.get('code') or ''
            if code:
                return code.strip()
        except Exception:
            pass
    # URL with code= parameter or fragment
    if '://' in raw or raw.startswith('http'):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(raw)
        qs = parse_qs(parsed.query)
        code = ((qs.get('code') or [''])[0]).strip()
        if code:
            return code
        # Also check fragment (some flows use #code=...)
        frag_qs = parse_qs(parsed.fragment)
        code = ((frag_qs.get('code') or [''])[0]).strip()
        if code:
            return code
    # Bare code
    if raw and ' ' not in raw:
        return raw
    return ''


def _store_session(data):
    """Persist session data from a /v3/profiles/sessions response."""
    ticket          = data.get('ticket', '')
    rmt             = data.get('rememberMeTicket', '')
    user_id         = data.get('userId', '')
    username        = data.get('nameOnPlatform', '') or data.get('username', '')
    expires_in      = int(data.get('expiration', 10800))  # default 3h
    expires_at      = int(time.time()) + expires_in

    if not ticket:
        return False, 'No ticket in Ubisoft response'

    cfg = load_config() or {}
    existing = cfg.get('ubisoft', {})
    existing.update({
        'ticket':            ticket,
        'ticket_expires_at': expires_at,
        'user_id':           user_id,
        'username':          username,
    })
    if rmt:
        existing['remember_me_ticket'] = rmt
    cfg['ubisoft'] = existing
    _save_config_data(cfg)
    log.info(f'Ubisoft auth: connected as {username!r} (userId={user_id!r})')
    return True, username


# ── Session management ────────────────────────────────────────────────────────

def get_valid_session():
    """
    Return a requests.Session with a valid Ubisoft ticket, or None if not connected.
    Auto-refreshes using rememberMeTicket when the session ticket is near expiry.
    """
    cfg    = load_config() or {}
    tokens = cfg.get('ubisoft', {})
    if not tokens.get('ticket') or not tokens.get('remember_me_ticket'):
        return None

    if int(time.time()) >= tokens.get('ticket_expires_at', 0) - 60:
        rmt = tokens['remember_me_ticket']
        try:
            data = _post_sessions(f'Ubi_v1 t={rmt}')
        except ValueError as e:
            log.warning(f'Ubisoft token refresh failed: {e}')
            return None

        ok, result = _store_session(data)
        if not ok:
            return None

        cfg    = load_config() or {}
        tokens = cfg.get('ubisoft', {})

    session = requests.Session()
    session.headers.update(_UBI_HEADERS)
    session.headers['Authorization'] = f'Ubi_v1 t={tokens["ticket"]}'
    return session


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
        log.error(f'Ubisoft library sync thread: {e}', exc_info=True)
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error', 'error': str(e)})


def _do_sync_library():
    from database import get_db, update_game_data as _update_game_data
    from datetime import datetime, timezone, date as _date

    session = get_valid_session()
    if not session:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error',
                                'error': 'Not connected to Ubisoft — please reconnect'})
        return

    try:
        resp = session.get(_INVENTORY_URL, params={'withOwnership': 'true'}, timeout=20)
        resp.raise_for_status()
        inventory = resp.json()
    except Exception as e:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error',
                                'error': f'Failed to fetch Ubisoft library: {e}'})
        return

    # inventories is a list of {spaceId, productId, ownership: {...}, ...}
    items = inventory if isinstance(inventory, list) else inventory.get('inventoryItems', [])
    if not items:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'done', 'new_games': 0, 'total_games': 0})
        return

    log.info(f'Ubisoft sync: {len(items)} inventory items')

    db = get_db()
    try:
        existing = {row['platform_id'] for row in db.execute(
            "SELECT platform_id FROM games WHERE platform = 'ubisoft'"
        ).fetchall()}
        blacklisted = {
            row[0] for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()
        }
    finally:
        db.close()

    # Deduplicate by spaceId; skip games already in the DB
    space_ids = []
    seen = set()
    for item in items:
        space_id = str(item.get('spaceId') or item.get('productId') or '')
        if not space_id or space_id in seen:
            continue
        seen.add(space_id)
        if space_id not in existing and space_id not in blacklisted:
            space_ids.append((space_id, item))

    total_new = len(space_ids)
    log.info(f'Ubisoft sync: {total_new} new games (skipped {len(items) - total_new} existing)')

    with _sync_lock:
        _sync_state.update({'phase': 'processing', 'done': 0, 'total': total_new, 'current_game': ''})

    today_ts        = int(datetime.now(timezone.utc).timestamp())
    today           = _date.today().isoformat()
    new_games_count = 0

    db = get_db()
    try:
        for space_id, item in space_ids:
            if _sync_cancel.is_set():
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'stopped',
                                        'new_games': new_games_count, 'total_games': len(items)})
                return

            # Use cached product name if available; will be filled by metadata fetch
            name = item.get('name') or item.get('productName') or space_id

            with _sync_lock:
                _sync_state['current_game'] = name

            next_appid = next_negative_appid(db)
            db.execute(
                """INSERT OR IGNORE INTO games
                   (appid, name, platform, platform_id, date_added,
                    completion_status, installed,
                    art_fetched, meta_fetched, cheevos_fetched,
                    protondb_fetched, hltb_fetched)
                   VALUES (?, ?, 'ubisoft', ?, ?,
                           'Never Played', 0,
                           '0', '0', '0', '0', '0')""",
                (next_appid, name, space_id, today_ts),
            )
            db.commit()
            log.info(f'Ubisoft sync: added {name!r} as appid {next_appid} (spaceId {space_id})')

            # Fetch metadata and art
            try:
                meta = _fetch_product_metadata(session, space_id)
                if meta:
                    if meta.get('name'):
                        name = meta['name']
                        db.execute("UPDATE games SET name = ? WHERE appid = ?", (name, next_appid))
                        db.commit()
                    meta['meta_fetched'] = today
                    _update_game_data(next_appid, **{k: v for k, v in meta.items() if k != 'name'})
            except Exception as e:
                log.warning(f'Ubisoft metadata: failed for {name!r}: {e}')

            try:
                art_meta = _download_art(session, next_appid, space_id)
                if art_meta:
                    _update_game_data(next_appid, art_fetched=today)
            except Exception as e:
                log.warning(f'Ubisoft art: failed for {name!r}: {e}')

            new_games_count += 1
            with _sync_lock:
                _sync_state['done'] += 1

            if _sync_cancel.is_set():
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'stopped',
                                        'new_games': new_games_count, 'total_games': len(items)})
                return

            time.sleep(0.4)
    finally:
        db.close()

    try:
        from .watcher import sync_ubisoft_install_status
        sync_ubisoft_install_status()
    except Exception as e:
        log.warning(f'Ubisoft sync: install status refresh failed: {e}')

    from database import auto_detect_duplicates
    from plugins import get_platform_priority
    dupes = auto_detect_duplicates(platform_priority=get_platform_priority())

    with _sync_lock:
        _sync_state.update({
            'running': False, 'phase': 'done',
            'new_games': new_games_count, 'total_games': len(items),
            'duplicates_detected': dupes,
        })


# ── Metadata ──────────────────────────────────────────────────────────────────

def _fetch_product_metadata(session, space_id):
    """
    Fetch product details for a spaceId. Returns a partial meta dict or None.
    Uses Ubisoft's product catalog API.
    """
    try:
        # Products endpoint: list of spaceIds as query params
        resp = session.get(
            _PRODUCTS_URL,
            params={'spaceIds': space_id, 'locale': 'en-US'},
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning(f'Ubisoft products HTTP {resp.status_code} for spaceId {space_id}')
            return None

        products = resp.json()
        if not products:
            return None

        # Response is a list of product objects
        product = products[0] if isinstance(products, list) else products

        meta = {}

        name = (product.get('name') or product.get('localizedName') or '').strip()
        if name:
            meta['name'] = name

        desc = (product.get('description') or product.get('localizedDescription') or '').strip()
        if desc:
            meta['_description'] = desc

        publisher = (product.get('publisherName') or '').strip()
        if publisher:
            meta['publishers'] = publisher

        developer = (product.get('developerName') or '').strip()
        if developer:
            meta['developers'] = developer

        genres = product.get('genres') or []
        if isinstance(genres, list) and genres:
            meta['genres'] = ','.join(g.get('name', g) if isinstance(g, dict) else g for g in genres)

        # Release date
        release_str = product.get('releaseDate') or product.get('releaseDateStr') or ''
        if release_str:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(release_str.replace('Z', '+00:00'))
                meta['release_date'] = int(dt.timestamp())
            except Exception:
                pass

        # Store slug
        slug = (product.get('slug') or product.get('urlSlug') or '').strip()
        if slug:
            meta['platform_slug'] = slug

        return meta or None

    except Exception as e:
        log.warning(f'Ubisoft product metadata failed for {space_id}: {e}')
        return None


def _download_art(session, appid, space_id):
    """Download cover art from Ubisoft CDN for a game. Returns True on any success."""
    # Ubisoft CDN image URL pattern (from product catalog)
    # We try the products endpoint for image URLs
    vert_path  = os.path.join(VERTICAL_DIR, f'{appid}.jpg')
    horiz_path = os.path.join(HORIZONTAL_DIR, f'{appid}.jpg')

    if os.path.exists(vert_path) and os.path.exists(horiz_path):
        return True

    try:
        resp = session.get(
            _PRODUCTS_URL,
            params={'spaceIds': space_id, 'locale': 'en-US'},
            timeout=15,
        )
        if resp.status_code != 200:
            return False

        products = resp.json()
        product  = products[0] if isinstance(products, list) else products

        images = product.get('images') or product.get('keyImages') or []
        success = False

        # Look for portrait/vertical and landscape/horizontal images
        vertical_url   = None
        horizontal_url = None

        for img in images:
            img_type = (img.get('type') or img.get('format') or '').lower()
            url      = img.get('url') or img.get('uri') or ''
            if not url:
                continue
            if any(k in img_type for k in ('portrait', 'vertical', 'packshot', 'cover', 'keyart_portrait')):
                vertical_url = vertical_url or url
            if any(k in img_type for k in ('landscape', 'horizontal', 'header', 'banner', 'background')):
                horizontal_url = horizontal_url or url

        # Fallback: try known CDN patterns
        if not vertical_url:
            vertical_url = f'https://xmedia-cf.ubi.com/ubiservices/v1/public/spaces/{space_id}/products/{space_id}/images/portrait'
        if not horizontal_url:
            horizontal_url = f'https://xmedia-cf.ubi.com/ubiservices/v1/public/spaces/{space_id}/products/{space_id}/images/landscape'

        for url, dest in [(vertical_url, vert_path), (horizontal_url, horiz_path)]:
            if url and not os.path.exists(dest):
                try:
                    r = requests.get(url, timeout=20)
                    if r.status_code == 200 and len(r.content) > 1000:
                        save_as_jpg(r.content, dest)
                        success = True
                except Exception as e:
                    log.warning(f'Ubisoft art download failed for {space_id}: {e}')

        return success

    except Exception as e:
        log.warning(f'Ubisoft art fetch failed for spaceId {space_id}: {e}')
        return False


# ── Single-game rescrape ──────────────────────────────────────────────────────

def scrape_single(appid):
    """
    Re-fetch metadata and art for one Ubisoft game.
    Returns a dict of updated fields, or None on failure.
    """
    session = get_valid_session()
    if not session:
        return None

    from database import get_db
    db  = get_db()
    row = db.execute(
        "SELECT platform_id FROM games WHERE appid = ? AND platform = 'ubisoft'",
        (appid,)
    ).fetchone()
    db.close()

    if not row or not row['platform_id']:
        return None

    space_id = row['platform_id']
    meta = _fetch_product_metadata(session, space_id) or {}

    from datetime import date
    meta['meta_fetched'] = date.today().isoformat()

    vert_path  = os.path.join(VERTICAL_DIR, f'{appid}.jpg')
    horiz_path = os.path.join(HORIZONTAL_DIR, f'{appid}.jpg')
    if not os.path.exists(vert_path) or not os.path.exists(horiz_path):
        try:
            _download_art(session, appid, space_id)
        except Exception as e:
            log.warning(f'Ubisoft scrape-single: art re-fetch failed for appid {appid}: {e}')

    return meta


def fetch_description(appid, platform_id):
    """Return a plain-text description for a Ubisoft game, or None."""
    session = get_valid_session()
    if not session:
        return None
    meta = _fetch_product_metadata(session, platform_id)
    return (meta or {}).get('_description') or None
