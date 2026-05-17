"""
ea.py — EA App (formerly Origin) integration for PlayDate.
Handles OAuth2 authentication, library sync, metadata, and cover art.

EA uses standard OAuth2 bearer tokens (runners/oauth2.py compatible).
Public client credentials from the EA web OAuth flow (documented in community research).
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

# ── EA OAuth2 constants ───────────────────────────────────────────────────────
# Web client credentials — used by the EA website OAuth flow.
EA_CLIENT_ID     = 'EADOTCOM-WEB-SERVER'
EA_CLIENT_SECRET = ''
EA_REDIRECT_URI  = 'https://www.ea.com/login'
EA_TOKEN_URL     = 'https://accounts.ea.com/connect/token'
EA_AUTH_URL      = (
    'https://accounts.ea.com/connect/auth'
    '?response_type=code'
    '&client_id=EADOTCOM-WEB-SERVER'
    '&display=originXWeb/login'
    '&locale=en_US'
    '&redirect_uri=https%3A%2F%2Fwww.ea.com%2Flogin'
)

_IDENTITY_URL    = 'https://gateway.ea.com/proxy/identity/pids/me'
_ENTITLEMENTS_URL_TMPL = 'https://api1.origin.com/ecommerce2/consolidatedentitlements/{pid}?machine_hash=1'
_SUPERCAT_URL_TMPL     = 'https://api2.origin.com/ecommerce2/public/supercat/{offer_id}/en_US'
_STORE_CONTENT_URL     = 'https://api1.origin.com/xsearch/store/en_US/USA/products'

_EA_HEADERS = {
    'Accept':            'application/json',
    'X-Origin-Platform': 'Win32',
    'Origin':            'https://www.ea.com',
}

VERTICAL_DIR   = os.path.join(BASE_DIR, 'static', 'img', 'library', 'vertical')
HORIZONTAL_DIR = os.path.join(BASE_DIR, 'static', 'img', 'library', 'horizontal')


# ── Token storage ─────────────────────────────────────────────────────────────

def load_ea_tokens():
    data = (load_config() or {}).get('ea_app', {})
    if data.get('access_token') and data.get('refresh_token'):
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


def _extract_code(raw):
    """Extract auth code from a raw string, JSON blob, or redirect URL."""
    raw = raw.strip()
    if raw.startswith('{'):
        try:
            obj = json.loads(raw)
            code = obj.get('code') or obj.get('authorization_code') or ''
            if code:
                return code.strip()
        except Exception:
            pass
    if '://' in raw or raw.startswith('http'):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(raw)
        qs = parse_qs(parsed.query)
        code = ((qs.get('code') or [''])[0]).strip()
        if code:
            return code
    if raw and ' ' not in raw:
        return raw
    return ''


def exchange_code(raw_input):
    """
    Exchange an EA authorization code for tokens.
    Returns (True, display_name) on success, (False, error_msg) on failure.
    """
    code = _extract_code(raw_input)
    if not code:
        return False, 'Could not extract an authorization code from the input'

    try:
        resp = requests.post(
            EA_TOKEN_URL,
            data={
                'grant_type':   'authorization_code',
                'code':          code,
                'client_id':     EA_CLIENT_ID,
                'redirect_uri':  EA_REDIRECT_URI,
            },
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
    expires_in    = int(data.get('expires_in', 3600))
    expires_at    = int(time.time()) + expires_in

    if not access_token:
        return False, 'No access token in EA response'

    # Fetch display name from identity endpoint
    display_name = ''
    pid = ''
    try:
        r = requests.get(
            _IDENTITY_URL,
            headers={**_EA_HEADERS, 'Authorization': f'Bearer {access_token}',
                     'X-Expand-Results': 'true'},
            timeout=10,
        )
        if r.status_code == 200:
            profile = r.json().get('pid', {})
            display_name = profile.get('displayName', '') or profile.get('pidId', '')
            pid = str(profile.get('pidId', ''))
    except Exception as e:
        log.warning(f'EA auth: could not fetch profile: {e}')

    cfg = load_config() or {}
    cfg['ea_app'] = {
        'access_token':  access_token,
        'refresh_token': refresh_token,
        'expires_at':    expires_at,
        'display_name':  display_name,
        'pid':           pid,
    }
    _save_config_data(cfg)
    log.info(f'EA auth: connected as {display_name!r} (pid={pid!r})')
    return True, display_name or 'EA Account'


def get_valid_session():
    """Return a requests.Session with a valid EA Bearer token, or None."""
    from runners.oauth2 import get_valid_session as _get_session
    session = _get_session(
        'ea_app', EA_TOKEN_URL, EA_CLIENT_ID, EA_CLIENT_SECRET,
        extra_headers=_EA_HEADERS,
    )
    if session:
        # Also pass the AuthToken header that the Origin API expects
        cfg    = load_config() or {}
        token  = cfg.get('ea_app', {}).get('access_token', '')
        session.headers['AuthToken'] = token
    return session


def _get_pid():
    """Return the stored EA pid (account identifier), or None."""
    tokens = load_ea_tokens()
    return (tokens or {}).get('pid') or None


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

    pid = _get_pid()
    if not pid:
        # Try to fetch it now
        try:
            r = session.get(_IDENTITY_URL, params={'expand': 'true'}, timeout=10)
            if r.status_code == 200:
                profile = r.json().get('pid', {})
                pid = str(profile.get('pidId', ''))
                display_name = profile.get('displayName', '')
                cfg = load_config() or {}
                cfg.setdefault('ea_app', {}).update({'pid': pid, 'display_name': display_name})
                _save_config_data(cfg)
        except Exception as e:
            log.warning(f'EA sync: could not fetch pid: {e}')

    if not pid:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error',
                                'error': 'Could not determine EA account ID — try reconnecting'})
        return

    try:
        url  = _ENTITLEMENTS_URL_TMPL.format(pid=pid)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error',
                                'error': f'Failed to fetch EA library: {e}'})
        return

    # Entitlements response: {"entitlements": {"entitlement": [...]}}
    raw = payload.get('entitlements', {})
    entitlements = raw.get('entitlement', raw) if isinstance(raw, dict) else raw
    if not isinstance(entitlements, list):
        entitlements = []

    # Filter to full-game entitlements (entitlementType == 'DEFAULT' or 'ONLINE_ACCESS')
    # and only PC platform
    games = []
    seen_offer_ids = set()
    for ent in entitlements:
        ent_type = ent.get('entitlementType', '')
        offer_id = str(ent.get('offerId') or ent.get('offerPath') or '').strip()
        if not offer_id or ent_type not in ('DEFAULT', 'ONLINE_ACCESS', ''):
            continue
        if offer_id in seen_offer_ids:
            continue
        seen_offer_ids.add(offer_id)
        games.append(ent)

    log.info(f'EA sync: {len(games)} entitlements after filtering')

    db = get_db()
    try:
        existing = {row['platform_id'] for row in db.execute(
            "SELECT platform_id FROM games WHERE platform = 'ea_app'"
        ).fetchall()}
        blacklisted = {
            row[0] for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()
        }
    finally:
        db.close()

    new_items = [(ent, str(ent.get('offerId') or '')) for ent in games
                 if str(ent.get('offerId') or '') not in existing
                 and str(ent.get('offerId') or '') not in blacklisted
                 and str(ent.get('offerId') or '')]

    total_new = len(new_items)
    log.info(f'EA sync: {total_new} new games (skipped {len(games) - total_new} existing)')

    with _sync_lock:
        _sync_state.update({'phase': 'processing', 'done': 0, 'total': total_new, 'current_game': ''})

    today_ts        = int(datetime.now(timezone.utc).timestamp())
    today           = _date.today().isoformat()
    new_games_count = 0

    db = get_db()
    try:
        for ent, offer_id in new_items:
            if _sync_cancel.is_set():
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'stopped',
                                        'new_games': new_games_count, 'total_games': len(games)})
                return

            name = (ent.get('productName') or ent.get('offerPath') or offer_id).strip()

            with _sync_lock:
                _sync_state['current_game'] = name

            # Purchase date from grantDate
            grant_date_str = ent.get('grantDate') or ent.get('purchaseDate') or ''
            date_ts = today_ts
            if grant_date_str:
                try:
                    from datetime import datetime as _dt
                    dt = _dt.fromisoformat(grant_date_str.replace('Z', '+00:00'))
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
                   VALUES (?, ?, 'ea_app', ?, ?,
                           'Never Played', 0,
                           '0', '0', '0', '0', '0')""",
                (next_appid, name, offer_id, date_ts),
            )
            db.commit()
            log.info(f'EA sync: added {name!r} as appid {next_appid} (offerId {offer_id})')

            # Fetch metadata and art from supercat
            try:
                meta = _fetch_supercat(session, offer_id)
                if meta:
                    if meta.get('name'):
                        name = meta['name']
                        db.execute("UPDATE games SET name = ? WHERE appid = ?", (name, next_appid))
                        db.commit()
                    meta['meta_fetched'] = today
                    _update_game_data(next_appid, **{k: v for k, v in meta.items() if k != 'name'})
            except Exception as e:
                log.warning(f'EA metadata: failed for {name!r}: {e}')

            try:
                if _download_art(session, next_appid, offer_id):
                    _update_game_data(next_appid, art_fetched=today)
            except Exception as e:
                log.warning(f'EA art: failed for {name!r}: {e}')

            new_games_count += 1
            with _sync_lock:
                _sync_state['done'] += 1

            if _sync_cancel.is_set():
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'stopped',
                                        'new_games': new_games_count, 'total_games': len(games)})
                return

            time.sleep(0.4)
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
            'new_games': new_games_count, 'total_games': len(games),
            'duplicates_detected': dupes,
        })


# ── Metadata ──────────────────────────────────────────────────────────────────

def _fetch_supercat(session, offer_id):
    """Fetch game details from EA's supercat endpoint. Returns partial meta dict or None."""
    try:
        url  = _SUPERCAT_URL_TMPL.format(offer_id=offer_id)
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            log.warning(f'EA supercat HTTP {resp.status_code} for offerId {offer_id}')
            return None

        data = resp.json()
        # Response may be wrapped: {"offerGroup": {...}} or directly a game object
        offer = (data.get('offerGroup') or data.get('offer') or data)

        meta = {}

        name = (offer.get('displayName') or offer.get('i18n', {}).get('displayName', '')
                or offer.get('masterTitle', '')).strip()
        if name:
            meta['name'] = name

        # Publisher/developer
        publisher = (offer.get('publisherName') or offer.get('softwareList', {})
                     .get('software', [{}])[0].get('publisher', '') if isinstance(
                         offer.get('softwareList', {}).get('software', ''), list) else '').strip()
        if publisher:
            meta['publishers'] = publisher

        # Genres
        genres = offer.get('genres') or []
        if isinstance(genres, list) and genres:
            meta['genres'] = ','.join(
                g.get('genreName', g) if isinstance(g, dict) else g
                for g in genres
            )

        # Release date
        release_str = offer.get('platforms', [{}])[0].get('releaseDate', '') if isinstance(
            offer.get('platforms', ''), list) else ''
        if not release_str:
            release_str = offer.get('offerReleaseDate') or offer.get('releaseDate') or ''
        if release_str:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(release_str.replace('Z', '+00:00'))
                meta['release_date'] = int(dt.timestamp())
            except Exception:
                pass

        # Slug for store URL
        slug = (offer.get('slug') or offer.get('i18n', {}).get('slug', '') or '').strip()
        if slug:
            meta['platform_slug'] = slug

        # Description
        desc = (offer.get('shortDescription') or offer.get('i18n', {})
                .get('shortDescription', '')).strip()
        if desc:
            meta['_description'] = desc

        return meta or None

    except Exception as e:
        log.warning(f'EA supercat failed for offerId {offer_id}: {e}')
        return None


def _download_art(session, appid, offer_id):
    """Download cover art from EA CDN. Returns True on any success."""
    vert_path  = os.path.join(VERTICAL_DIR, f'{appid}.jpg')
    horiz_path = os.path.join(HORIZONTAL_DIR, f'{appid}.jpg')

    if os.path.exists(vert_path) and os.path.exists(horiz_path):
        return True

    success = False
    try:
        url  = _SUPERCAT_URL_TMPL.format(offer_id=offer_id)
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return False

        offer = resp.json()
        offer = offer.get('offerGroup') or offer.get('offer') or offer

        # EA CDN image URLs are in imageSets
        image_sets = offer.get('imageSets') or {}
        if isinstance(image_sets, list):
            image_sets = {img.get('type', ''): img for img in image_sets}

        # Map EA image types to our vertical/horizontal outputs
        # Common EA types: packageArtLarge (portrait), backgroundImageAboveTheFold (landscape)
        type_map = {
            'packageArtLarge':              vert_path,
            'packageArtSmall':              vert_path,
            'heroArtLarge':                 horiz_path,
            'backgroundImageAboveTheFold':  horiz_path,
            'image':                        horiz_path,
        }
        downloaded = set()
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

    except Exception as e:
        log.warning(f'EA art fetch failed for offerId {offer_id}: {e}')

    return success


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
    meta = _fetch_supercat(session, offer_id) or {}

    from datetime import date
    meta['meta_fetched'] = date.today().isoformat()

    vert_path  = os.path.join(VERTICAL_DIR, f'{appid}.jpg')
    horiz_path = os.path.join(HORIZONTAL_DIR, f'{appid}.jpg')
    if not os.path.exists(vert_path) or not os.path.exists(horiz_path):
        try:
            _download_art(session, appid, offer_id)
        except Exception as e:
            log.warning(f'EA scrape-single: art re-fetch failed for appid {appid}: {e}')

    return meta


def fetch_description(appid, platform_id):
    """Return a plain-text description for an EA game, or None."""
    session = get_valid_session()
    if not session:
        return None
    meta = _fetch_supercat(session, platform_id)
    return (meta or {}).get('_description') or None
