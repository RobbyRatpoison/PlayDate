"""
gog.py — GOG Galaxy integration for PlayDate.
Handles OAuth2 authentication, library sync, content-system install, and launch.
"""

import json
import logging
import os
import re
import threading
import time
import zlib
from datetime import datetime, timezone
import requests
from config import load_config, _save_config_data
from database import next_negative_appid
from scrapers import _weighted_score
from utils import review_score_label

log = logging.getLogger(__name__)

# ── GOG OAuth2 constants ──────────────────────────────────────────────────────
# Public credentials shared by lgogdownloader, Heroic Games Launcher, etc.
GOG_CLIENT_ID     = '46899977096215655'
GOG_CLIENT_SECRET = '9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9'
GOG_AUTH_URL      = 'https://auth.gog.com/auth'
GOG_TOKEN_URL     = 'https://auth.gog.com/token'
GOG_REDIRECT_URI  = 'https://embed.gog.com/on_login_success?origin=client'

_HEADERS = {
    'User-Agent': 'GOGGalaxyClient/2.0.45.189 (Windows; 10)',
    'Accept':     'application/json',
}


# ── Config helpers ────────────────────────────────────────────────────────────

# ── Token storage ─────────────────────────────────────────────────────────────

def load_gog_tokens():
    """Return stored GOG tokens dict, or None if not connected."""
    gog = (load_config() or {}).get('gog', {})
    if gog.get('access_token') and gog.get('refresh_token'):
        return gog
    return None


def _save_gog_tokens(access_token, refresh_token, expires_at, username=None, galaxy_user_id=None):
    """Persist GOG tokens (and optionally username / galaxy user ID) to config.json."""
    data = load_config()
    if not data:
        return
    existing = data.get('gog', {})
    data['gog'] = {
        'access_token':   access_token,
        'refresh_token':  refresh_token,
        'expires_at':     expires_at,
        'username':       username       if username       is not None else existing.get('username'),
        'galaxy_user_id': galaxy_user_id if galaxy_user_id is not None else existing.get('galaxy_user_id'),
    }
    _save_config_data(data)


def clear_gog_tokens():
    """Remove all GOG data from config.json."""
    data = load_config() or {}
    data.pop('gog', None)
    _save_config_data(data)


def is_connected():
    """Return True if GOG tokens are stored."""
    return load_gog_tokens() is not None


# ── OAuth2 auth flow ──────────────────────────────────────────────────────────

def get_auth_url():
    """Return the GOG OAuth2 authorization URL for the user to open in a browser."""
    from urllib.parse import urlencode
    params = {
        'client_id':     GOG_CLIENT_ID,
        'redirect_uri':  GOG_REDIRECT_URI,
        'response_type': 'code',
        'layout':        'client2',
    }
    return f'{GOG_AUTH_URL}?{urlencode(params)}'


def exchange_code(code):
    """
    Exchange an authorization code for access + refresh tokens.
    Returns (True, username) on success, (False, error_message) on failure.
    """
    try:
        resp = requests.post(GOG_TOKEN_URL, data={
            'client_id':     GOG_CLIENT_ID,
            'client_secret': GOG_CLIENT_SECRET,
            'grant_type':    'authorization_code',
            'code':          code.strip(),
            'redirect_uri':  GOG_REDIRECT_URI,
        }, headers=_HEADERS, timeout=15)

        if resp.status_code != 200:
            body = resp.text[:200]
            return False, f'Token exchange failed (HTTP {resp.status_code}): {body}'

        data = resp.json()
        access_token  = data['access_token']
        refresh_token = data['refresh_token']
        expires_at    = int(time.time()) + int(data.get('expires_in', 3600))

        username, galaxy_user_id = _fetch_username(access_token)
        _save_gog_tokens(access_token, refresh_token, expires_at, username, galaxy_user_id)
        log.info(f'GOG auth: connected as {username!r} (galaxy_user_id={galaxy_user_id!r})')
        return True, username or ''

    except KeyError as e:
        return False, f'Unexpected token response (missing {e})'
    except Exception as e:
        return False, str(e)


def get_valid_session():
    """
    Return a requests.Session with a valid GOG Bearer token.
    Auto-refreshes if the token has expired. Returns None if not connected.
    """
    from runners.oauth2 import get_valid_session as _get_session
    return _get_session('gog', GOG_TOKEN_URL, GOG_CLIENT_ID, GOG_CLIENT_SECRET,
                        extra_headers=_HEADERS)


# ── User info ─────────────────────────────────────────────────────────────────

def _fetch_username(access_token=None):
    """Fetch the GOG username and galaxy user ID from the API.
    Returns (username, galaxy_user_id) tuple; either may be None on failure."""
    try:
        headers = dict(_HEADERS)
        if access_token:
            headers['Authorization'] = f'Bearer {access_token}'
            resp = requests.get('https://embed.gog.com/userData.json',
                                headers=headers, timeout=10)
        else:
            session = get_valid_session()
            if not session:
                return None, None
            resp = session.get('https://embed.gog.com/userData.json', timeout=10)

        resp.raise_for_status()
        data = resp.json()
        return data.get('username') or data.get('galaxyUserId'), data.get('galaxyUserId')
    except Exception as e:
        log.warning(f'_fetch_username: {e}')
        return None, None


def get_username():
    """Return the cached GOG username, fetching from the API if not stored."""
    tokens = load_gog_tokens()
    if not tokens:
        return None
    cached = tokens.get('username')
    if cached:
        return cached
    username, galaxy_user_id = _fetch_username()
    if username:
        _save_gog_tokens(
            tokens['access_token'],
            tokens['refresh_token'],
            tokens.get('expires_at', 0),
            username,
            galaxy_user_id,
        )
    return username


def get_galaxy_user_id():
    """Return the cached GOG galaxy user ID, or None if not stored/connected."""
    tokens = load_gog_tokens()
    if not tokens:
        return None
    return tokens.get('galaxy_user_id')


# ── Library sync ──────────────────────────────────────────────────────────────

_sync_state = {
    'running': False, 'phase': None,
    'page': 0, 'total_pages': 0,
    'done': 0, 'total': 0, 'current_game': '',
    'new_games': 0, 'total_games': 0, 'duplicates_detected': 0, 'error': None,
}
_sync_lock   = threading.Lock()
_sync_cancel = threading.Event()


def get_sync_state():
    with _sync_lock:
        return dict(_sync_state)


def start_library_sync():
    """Start a background library sync. Returns {status: 'started'|'already_running'}."""
    with _sync_lock:
        if _sync_state['running']:
            return {'status': 'already_running'}
        _sync_cancel.clear()
        _sync_state.update({
            'running': True, 'phase': 'fetching_products', 'page': 0, 'total_pages': 0,
            'done': 0, 'total': 0, 'current_game': '',
            'new_games': 0, 'total_games': 0, 'duplicates_detected': 0, 'error': None,
        })
    threading.Thread(target=_run_sync_library, daemon=True).start()
    return {'status': 'started'}


def cancel_library_sync():
    """Signal the running library sync to stop."""
    _sync_cancel.set()


def _run_sync_library():
    try:
        _do_sync_library()
    except Exception as e:
        log.error(f'GOG library sync thread: {e}', exc_info=True)
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error', 'error': str(e)})


def _do_sync_library():
    from database import get_db, add_to_blacklist, update_game_data as _update_game_data
    from images import download_vertical, download_horizontal, download_icon, _sgdb_search_game_id
    from datetime import datetime, timezone, date as _date

    session        = get_valid_session()
    galaxy_user_id = get_galaxy_user_id()
    if not session:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error',
                                'error': 'Not connected to GOG — please reconnect'})
        return

    # Phase 1: fetch full product list
    products = []
    page     = 1
    while True:
        if _sync_cancel.is_set():
            with _sync_lock:
                _sync_state.update({'running': False, 'phase': 'stopped',
                                    'new_games': 0, 'total_games': 0})
            return
        try:
            resp = session.get(
                'https://embed.gog.com/account/getFilteredProducts',
                params={'mediaType': 1, 'page': page},
                timeout=20,
            )
            if resp.status_code == 401:
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'error',
                                        'error': 'GOG session expired — please reconnect'})
                return
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning(f'GOG library: page {page} fetch failed: {e}')
            break
        total_pages = data.get('totalPages', 1)
        products.extend(data.get('products', []))
        log.info(f'GOG library: page {page}/{total_pages} — {len(data.get("products", []))} products')
        with _sync_lock:
            _sync_state.update({'page': page, 'total_pages': total_pages})
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.3)

    games = [p for p in products if p.get('isGame') and not p.get('isMovie')]
    log.info(f'GOG sync: {len(games)} games from {len(products)} products')

    # Phase 2: process each new game with metadata and art inline
    db = get_db()
    try:
        existing = {
            row[0] for row in db.execute(
                "SELECT platform_id FROM games WHERE platform = 'gog'"
            ).fetchall()
        }
        blacklisted = {
            row[0] for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()
        }

        new_products = [p for p in games
                        if str(p['id']) not in existing and str(p['id']) not in blacklisted]
        total_new = len(new_products)
        log.info(f'GOG sync: {total_new} new games to process (skipping {len(games) - total_new} existing)')

        today_ts       = int(datetime.now(timezone.utc).timestamp())
        today          = _date.today().isoformat()
        new_games_count = 0

        with _sync_lock:
            _sync_state.update({'phase': 'processing', 'done': 0, 'total': total_new, 'current_game': ''})

        for p in new_products:
            if _sync_cancel.is_set():
                with _sync_lock:
                    _sync_state.update({'running': False, 'phase': 'stopped',
                                        'new_games': new_games_count,
                                        'total_games': len(games)})
                return

            gog_id = str(p['id'])
            name   = p.get('title', f'GOG Game {gog_id}')
            slug   = p.get('slug', '')

            with _sync_lock:
                _sync_state['current_game'] = name

            next_appid = next_negative_appid(db)
            db.execute(
                """INSERT OR IGNORE INTO games
                   (appid, name, platform, platform_id, platform_slug, date_added,
                    completion_status, installed,
                    art_fetched, meta_fetched, cheevos_fetched,
                    protondb_fetched, hltb_fetched)
                   VALUES (?, ?, 'gog', ?, ?, ?,
                           'Never Played', 0,
                           '0', '0', '0', '0', '0')""",
                (next_appid, name, gog_id, slug, today_ts),
            )
            db.commit()
            log.info(f'GOG sync: added {name!r} as appid {next_appid}')

            kept = True
            meta = fetch_gog_metadata(gog_id)
            if meta is not None:
                category = meta.pop('_category', None)
                if category is not None and category != 'GAME':
                    db.execute('DELETE FROM games WHERE appid = ?', (next_appid,))
                    db.commit()
                    add_to_blacklist(next_appid, name, platform_id=gog_id)
                    log.info(f'GOG sync: removed non-game {name!r} (category={category})')
                    kept = False
                else:
                    meta['meta_fetched'] = today
                    if session and galaxy_user_id:
                        ach = fetch_gog_achievements(gog_id, galaxy_user_id, session)
                        if ach is not None:
                            meta.update(ach)
                            meta['cheevos_fetched'] = today
                    try:
                        _update_game_data(next_appid, **meta)
                    except Exception as e:
                        log.warning(f'GOG metadata: DB update failed for {name!r}: {e}')

            if kept:
                try:
                    sgdb_id = _sgdb_search_game_id(name)
                    v_src   = download_vertical(next_appid,   sgdb_id=sgdb_id, game_name=name)
                    h_src   = download_horizontal(next_appid, sgdb_id=sgdb_id, game_name=name)
                    i_src   = download_icon(next_appid, '',   sgdb_id=sgdb_id, game_name=name)
                    _update_game_data(next_appid, art_fetched=today,
                                      vertical_art_source=v_src,
                                      horizontal_art_source=h_src,
                                      icon_source=i_src)
                    log.info(f'GOG art: downloaded for {name!r} (appid {next_appid})')
                except Exception as e:
                    log.warning(f'GOG art: failed for {name!r}: {e}')
                new_games_count += 1

            with _sync_lock:
                _sync_state['done'] += 1

            time.sleep(0.3)

    finally:
        db.close()

    from database import auto_detect_duplicates
    from plugins import get_platform_priority
    dupes = auto_detect_duplicates(platform_priority=get_platform_priority())

    with _sync_lock:
        _sync_state.update({
            'running': False, 'phase': 'done',
            'new_games': new_games_count, 'total_games': len(games),
            'duplicates_detected': dupes,
        })


def sync_library():
    """Legacy synchronous wrapper — kept for internal callers."""
    start_library_sync()
    # Wait for completion (used only in non-interactive contexts)
    import time as _time
    while get_sync_state().get('running'):
        _time.sleep(0.5)
    return get_sync_state()




def _fetch_art_for_games(games):
    """Download SGDB art for a list of newly-added GOG games (runs in background)."""
    from images import download_vertical, download_horizontal, download_icon, _sgdb_search_game_id
    from database import update_game_data
    from datetime import date

    for g in games:
        appid = g['appid']
        name  = g['name']
        try:
            sgdb_id = _sgdb_search_game_id(name)
            v_src   = download_vertical(appid,   sgdb_id=sgdb_id, game_name=name)
            h_src   = download_horizontal(appid, sgdb_id=sgdb_id, game_name=name)
            i_src   = download_icon(appid, '',   sgdb_id=sgdb_id, game_name=name)
            update_game_data(appid, art_fetched=date.today().isoformat(),
                             vertical_art_source=v_src,
                             horizontal_art_source=h_src,
                             icon_source=i_src)
            log.info(f'GOG art: downloaded for {name!r} (appid {appid})')
        except Exception as e:
            log.warning(f'GOG art: failed for {name!r}: {e}')
        time.sleep(0.3)


# ── Metadata scraper ─────────────────────────────────────────────────────────

_V2_GAMES_URL    = 'https://api.gog.com/v2/games/{gog_id}'
_RATINGS_URL     = 'https://reviews.gog.com/v1/products/{gog_id}/averageRating'
_ACHIEVEMENTS_URL = 'https://gameplay.gog.com/clients/{gog_id}/users/{galaxy_user_id}/achievements'


def fetch_gog_metadata(gog_id):
    """
    Fetch product metadata for a GOG game. Uses two endpoints (both public, no auth):
      - api.gog.com/v2/games/{id}  — developer, publisher, tags, genres, release date
      - reviews.gog.com/v1/products/{id}/averageRating  — rating (0-5 stars) + count

    Rating is multiplied by 20 to get a 0-100 scale matching Steam's review_percentage,
    then weighted with the same confidence-interval formula used for Steam games.

    Returns a dict of DB column values to update, or None if the v2 call fails entirely.
    """
    # ── v2 games endpoint ─────────────────────────────────────────────────────
    try:
        resp = requests.get(_V2_GAMES_URL.format(gog_id=gog_id),
                            headers=_HEADERS, timeout=15)
        if resp.status_code == 404:
            # Not in the v2 games catalog — extras, goodies packs, etc.
            log.info(f'GOG metadata: {gog_id} not in v2 catalog (404) — marking as non-game')
            return {'_category': None}
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.warning(f'GOG metadata: v2 fetch failed for {gog_id}: {e}')
        return None

    result  = {}
    emb     = data.get('_embedded', {})
    product = emb.get('product', {})

    # Extract store slug from _links.store.href (e.g. '.../game/the_witcher_3_wild_hunt')
    store_href = data.get('_links', {}).get('store', {}).get('href', '')
    if '/game/' in store_href:
        result['platform_slug'] = store_href.split('/game/')[-1].rstrip('/')

    # Always include category so sync_gog_metadata can filter non-games.
    # Prefixed with _ so it gets popped before the DB update.
    # None means the v2 API has no record of this product — treat as non-game.
    result['_category'] = product.get('category')

    devs = [d['name'] for d in (emb.get('developers') or []) if d.get('name')]
    if devs:
        result['developers'] = ','.join(devs)

    pub = (emb.get('publisher') or {}).get('name', '').strip()
    if pub:
        result['publishers'] = pub

    # games.release_date is INTEGER (Unix timestamp) -- this used to store
    # str(release_date)[:10] (a "YYYY-MM-DD" string) directly, which SQLite's
    # type affinity can't losslessly coerce into that column's storage class.
    # A column with a mix of INTEGER (Steam) and TEXT (GOG) values sorts by
    # storage class first (NULL < INTEGER/REAL < TEXT), not by date -- ORDER
    # BY release_date grouped every GOG game before/after every Steam game
    # instead of interleaving them by actual date.
    release_date = product.get('globalReleaseDate') or product.get('gogReleaseDate')
    if release_date:
        try:
            dt = datetime.fromisoformat(str(release_date).replace('Z', '+00:00'))
            # A date-only value (no offset/Z) parses as naive, and naive
            # .timestamp() falls back to the local system timezone rather
            # than UTC -- forced explicitly here to match date_to_ts() and
            # every other plugin's date parsing in this codebase.
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            result['release_date'] = int(dt.timestamp())
        except ValueError:
            pass

    # tags = official genre classifications (Role-playing, Action, Fantasy…)
    genre_list = [t['name'] for t in (emb.get('tags') or []) if t.get('name')]
    if genre_list:
        result['genres'] = ','.join(genre_list)

    # properties = descriptive labels similar to Steam user tags (Open World, Story Rich…)
    prop_list = [p['name'] for p in (emb.get('properties') or []) if p.get('name')]
    if prop_list:
        result['tags'] = ','.join(prop_list)

    # ── ratings endpoint ──────────────────────────────────────────────────────
    try:
        r = requests.get(_RATINGS_URL.format(gog_id=gog_id),
                         headers=_HEADERS, timeout=10)
        if r.status_code == 200:
            rdata   = r.json()
            value   = float(rdata.get('value') or 0)
            count   = int(rdata.get('count') or 0)
            percent = round(value * 20)   # 0-5 stars → 0-100

            result['review_percentage']   = percent
            result['weighted_percentage'] = _weighted_score(percent, count)
            result['total_reviews']       = count
            result['positive_reviews']    = round(percent / 100 * count)
            result['review_score']        = review_score_label(percent, count)
    except Exception as e:
        log.warning(f'GOG metadata: ratings fetch failed for {gog_id}: {e}')

    return result or None


def fetch_gog_achievements(gog_id, galaxy_user_id, session):
    """
    Fetch achievement data for a GOG game from the Galaxy gameplay API.
    Returns {'unlocked_achievements': int, 'total_achievements': int} or None on failure.
    A 404 means the game has no achievements — returns zeros rather than None.
    """
    try:
        url  = _ACHIEVEMENTS_URL.format(gog_id=gog_id, galaxy_user_id=galaxy_user_id)
        resp = session.get(url, timeout=15)
        if resp.status_code == 404:
            return {'unlocked_achievements': 0, 'total_achievements': 0}
        resp.raise_for_status()
        data     = resp.json()
        total    = int(data.get('total_count') or 0)
        items    = data.get('items') or []
        unlocked = sum(1 for item in items if item.get('date_unlocked'))
        return {'unlocked_achievements': unlocked, 'total_achievements': total}
    except Exception as e:
        log.warning(f'GOG achievements: fetch failed for gog_id={gog_id}: {e}')
        return None


def _fetch_all_products(session):
    """Fetch every product (game or otherwise) in the user's GOG library, paginated.
    Same endpoint/shape as _do_sync_library's Phase 1. Returns (products, total_pages)."""
    products = []
    page = 1
    total_pages = 1
    while True:
        resp = session.get(
            'https://embed.gog.com/account/getFilteredProducts',
            params={'mediaType': 1, 'page': page},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        total_pages = data.get('totalPages', 1)
        products.extend(data.get('products', []))
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.3)
    return products, total_pages


def sync_gog_metadata(force=False):
    """
    Fetch and store GOG product metadata for GOG games.

    force=False (default): only processes games where meta_fetched is NULL or '0'
                           (i.e. never successfully fetched yet)
    force=True:            re-fetches all GOG games regardless of meta_fetched state;
                           use this for explicit user-triggered syncs

    Runs synchronously; intended to be called in a background thread.
    Returns {'updated': int, 'errors': int, 'deleted': int}.
    """
    from database import get_db, update_game_data
    from datetime import date

    # Build a set of GOG IDs that are real games (have a store URL).
    # Any DB entry whose platform_id is NOT in this set gets deleted.
    valid_gog_ids  = None
    galaxy_user_id = get_galaxy_user_id()
    session        = get_valid_session()
    if session:
        try:
            all_products, _ = _fetch_all_products(session)
            valid_gog_ids   = {
                str(p['id']) for p in (all_products or [])
                if p.get('url') and not p.get('isMovie')
            } if all_products is not None else None
        except Exception as e:
            log.warning(f'GOG metadata: library pre-fetch failed — {e}')
            valid_gog_ids = None

    db = get_db()
    try:
        if force:
            rows = db.execute(
                "SELECT appid, platform_id, name, meta_fetched FROM games WHERE platform = 'gog'"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT appid, platform_id, name, meta_fetched FROM games "
                "WHERE platform = 'gog'"
                "  AND (meta_fetched IS NULL OR meta_fetched = '0'"
                "       OR cheevos_fetched IS NULL OR cheevos_fetched = '0')"
            ).fetchall()

        updated = 0
        errors  = 0
        deleted = 0
        today   = date.today().isoformat()

        if not rows:
            return {'updated': updated, 'errors': errors, 'deleted': deleted}

        with _meta_lock:
            _meta_state['total'] = len(rows)

        from database import add_to_blacklist
        for row in rows:
            appid           = row['appid']
            gog_id          = row['platform_id']
            name            = row['name']
            has_meta        = row['meta_fetched'] and row['meta_fetched'] != '0'

            if has_meta and not force:
                # Metadata already fetched — only missing achievements
                if not (session and galaxy_user_id):
                    time.sleep(0.5)
                    continue
                ach = fetch_gog_achievements(gog_id, galaxy_user_id, session)
                if ach is not None:
                    try:
                        update_game_data(appid, cheevos_fetched=today, **ach)
                        log.info(f'GOG metadata: fetched achievements for {name!r}')
                        updated += 1
                    except Exception as e:
                        log.error(f'GOG metadata: achievement update failed for {name!r}: {e}')
                        errors += 1
                time.sleep(0.5)
                continue

            meta = fetch_gog_metadata(gog_id)
            if meta is None:
                # v2 API failed entirely — mark attempted to avoid hammering on next startup sync
                try:
                    update_game_data(appid, meta_fetched=today)
                except Exception:
                    pass
                errors += 1
                time.sleep(0.5)
                continue

            # Deletion logic:
            #   category=None (v2 404) + not in valid_gog_ids (url='') → non-game extra, delete
            #   category=None + in valid_gog_ids → free/delisted game with no v2 entry, keep
            #   category='GAME' → real game, update metadata
            #   category=anything else → DLC/pack/etc., delete
            category      = meta.pop('_category', None)
            has_store_url = (valid_gog_ids is None or str(gog_id) in valid_gog_ids)
            is_non_game   = (category is None and not has_store_url) or \
                            (category is not None and category != 'GAME')
            if is_non_game:
                try:
                    db.execute('DELETE FROM games WHERE appid = ?', (appid,))
                    db.commit()
                    add_to_blacklist(appid, name, platform_id=gog_id)
                    log.info(f'GOG metadata: deleted + blacklisted non-game {name!r} (category={category})')
                    deleted += 1
                except Exception as e:
                    log.error(f'GOG metadata: delete failed for {name!r}: {e}')
                    errors += 1
                time.sleep(0.5)
                continue

            meta['meta_fetched'] = today

            # Fetch achievements if we have a valid session and galaxy user ID
            if session and galaxy_user_id:
                ach = fetch_gog_achievements(gog_id, galaxy_user_id, session)
                if ach is not None:
                    meta.update(ach)
                    meta['cheevos_fetched'] = today

            try:
                update_game_data(appid, **meta)
                log.info(f'GOG metadata: updated {name!r} (appid {appid})')
                updated += 1
            except Exception as e:
                log.error(f'GOG metadata: DB update failed for {name!r}: {e}')
                errors += 1

            with _meta_lock:
                _meta_state.update({'done': _meta_state['done'] + 1,
                                    'updated': updated, 'deleted': deleted, 'errors': errors})
            time.sleep(0.5)

    finally:
        db.close()

    log.info(f'GOG metadata sync complete: {updated} updated, {deleted} deleted, {errors} errors')
    return {'updated': updated, 'errors': errors, 'deleted': deleted}


# ── Metadata sync state ───────────────────────────────────────────────────────

_meta_state = {'running': False, 'total': 0, 'done': 0,
               'updated': 0, 'deleted': 0, 'errors': 0}
_meta_lock  = threading.Lock()


def get_meta_sync_state():
    with _meta_lock:
        return dict(_meta_state)


def start_meta_sync(force=False):
    """
    Start sync_gog_metadata in a background thread. Returns immediately.
    Poll get_meta_sync_state() for progress.
    """
    with _meta_lock:
        if _meta_state['running']:
            return {'status': 'already_running'}
        _meta_state.update({'running': True, 'total': 0, 'done': 0,
                            'updated': 0, 'deleted': 0, 'errors': 0})

    def _run():
        try:
            sync_gog_metadata(force=force)
        except Exception as e:
            log.error(f'GOG meta sync thread: {e}', exc_info=True)
        finally:
            with _meta_lock:
                _meta_state['running'] = False

    threading.Thread(target=_run, daemon=True).start()
    return {'status': 'started'}


# ── GOG content system install ────────────────────────────────────────────────

GOG_INSTALL_BASE = os.path.expanduser('~/Games/GOG')
_CS_BASE         = 'https://content-system.gog.com'

# Per-appid install state, polled by the frontend
_install_states  = {}   # appid (int) → dict
_install_lock    = threading.Lock()
_install_cancels = {}   # appid (int) → threading.Event


def _zlib_decomp(data):
    """Decompress GOG manifest data — tries both standard and raw deflate."""
    for wbits in (15, -15, 47):
        try:
            return zlib.decompress(data, wbits)
        except zlib.error:
            continue
    raise ValueError('Could not decompress data (tried zlib/deflate/gzip)')


def _get_secure_link_urls(gog_id, session):
    """
    Fetch a time-limited set of CDN download URL templates via the secure_link
    endpoint (replaces the deprecated /token endpoint).

    Returns the 'urls' list from the response — each entry has 'url_format'
    and 'parameters' (including 'path' pointing at the product's CDN store
    directory, and 'expires_at').
    """
    url  = f'{_CS_BASE}/products/{gog_id}/secure_link?generation=2&path=/&_version=2'
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    urls = data.get('urls', [])
    if not urls:
        raise ValueError(f'secure_link response missing urls: {list(data.keys())}')
    log.debug(f'GOG secure_link acquired for product {gog_id}')
    return urls


def _build_cdn_url(cdn_urls, rel_path):
    """Build a CDN download URL for a given relative path using secure_link URL templates.

    Works for both depot manifests and chunk files — appends the given path to
    the secure_link ``parameters['path']`` and substitutes all placeholders.
    """
    src    = cdn_urls[0]
    params = {**src['parameters'], 'path': src['parameters'].get('path', '').rstrip('/') + '/' + rel_path}
    url    = src['url_format']
    for key, value in params.items():
        url = url.replace('{' + key + '}', str(value))
    return url


def _build_chunk_url(cdn_urls, compressed_md5):
    """
    Build a CDN download URL for a single chunk using the secure_link URL templates.
    """
    chunk_path = f'{compressed_md5[:2]}/{compressed_md5[2:4]}/{compressed_md5}'
    return _build_cdn_url(cdn_urls, chunk_path)


def _fetch_manifest(url, session):
    """Download and decompress a GOG manifest. Tries plain JSON first, then zlib/deflate/gzip."""
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    # CDN URLs sometimes return uncompressed JSON directly rather than zlib-wrapped data.
    # Try plain JSON first — if it succeeds, we're done.
    try:
        return json.loads(resp.content)
    except (json.JSONDecodeError, ValueError):
        pass
    # Not plain JSON — assume zlib/deflate/gzip compressed.
    return json.loads(_zlib_decomp(resp.content))


def _get_builds(gog_id, os_name, session):
    """Return the builds list for a GOG product + OS, newest first. Returns [] on 404."""
    url = f'{_CS_BASE}/products/{gog_id}/os/{os_name}/builds?generation=2'
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json().get('items', [])
    except Exception as e:
        log.warning(f'_get_builds({gog_id}, {os_name}): {e}')
        return []


def _get_info_candidates(install_path, product_id):
    candidates = [os.path.join(install_path, f'goggame-{product_id}.info')]
    try:
        candidates += [
            os.path.join(install_path, f)
            for f in os.listdir(install_path)
            if f.startswith('goggame-') and f.endswith('.info')
            and f != f'goggame-{product_id}.info'
        ]
    except Exception:
        pass
    return candidates


def _get_dosbox_launch(install_path, product_id):
    """
    If the game's primary play task runs DOSBox, return (dosbox_bin, args_list, cwd).
    Returns False if this is not a DOSBox game, None if dosbox binary not found.

    Conf file paths are returned as absolute paths.
    cwd is set to the app/ subdirectory when present so that relative mount
    paths in [autoexec] (e.g. "mount c ..") resolve to the install root.
    """
    import shlex, shutil

    dosbox_task = None
    for info_path in _get_info_candidates(install_path, product_id):
        if not os.path.isfile(info_path):
            continue
        try:
            with open(info_path, 'r', encoding='utf-8', errors='ignore') as f:
                info = json.load(f)
            tasks = sorted(info.get('playTasks', []),
                           key=lambda t: (not t.get('isPrimary', False),))
            for task in tasks:
                if task.get('type') == 'FileTask':
                    p = (task.get('path') or '').replace('\\', '/').lower()
                    if 'dosbox' in os.path.basename(p) and p.endswith('.exe'):
                        dosbox_task = task
                        break
        except Exception:
            pass
        if dosbox_task:
            break

    if not dosbox_task:
        return False  # not a DOSBox game

    dosbox_bin = None
    for candidate in ('dosbox', 'dosbox-staging', 'dosbox-x', 'dosbox-svn'):
        dosbox_bin = shutil.which(candidate)
        if dosbox_bin:
            break
    if not dosbox_bin:
        log.warning('_get_dosbox_launch: no dosbox binary found in PATH')
        return None  # DOSBox game but binary not installed

    raw_args = dosbox_task.get('arguments', '')
    work_dir  = dosbox_task.get('workingDirectory', '').replace('\\', '/')
    try:
        parts = shlex.split(raw_args)
    except Exception:
        parts = raw_args.split()

    # Search dirs for conf files: one level up from workingDir, then app/, then install root
    search_dirs = []
    if work_dir:
        search_dirs.append(
            os.path.normpath(os.path.join(install_path, work_dir, '..')))
    search_dirs += [os.path.join(install_path, 'app'), install_path]

    resolved = []
    i = 0
    while i < len(parts):
        if parts[i].lower() == '-conf' and i + 1 < len(parts):
            conf_name = os.path.basename(parts[i + 1].replace('\\', '/'))
            found = None
            for d in search_dirs:
                c = os.path.join(d, conf_name)
                if os.path.isfile(c):
                    found = c  # absolute path
                    break
            if found:
                resolved += ['-conf', found]
            i += 2
        else:
            resolved.append(parts[i])
            i += 1

    # Run from app/ if it exists so "mount c .." in [autoexec] resolves to install root
    app_dir = os.path.join(install_path, 'app')
    cwd = app_dir if os.path.isdir(app_dir) else install_path

    return dosbox_bin, resolved, cwd


def _find_gog_executable(install_path, product_id):
    """
    Parse goggame-{product_id}.info for the primary play task executable.
    Returns a forward-slash relative path string (or the system dosbox binary
    path for DOSBox games), or None.

    On Linux native builds the .info file may be absent or use a different
    convention, so the fallback scans for any executable file in the install root.
    """
    for info_path in _get_info_candidates(install_path, product_id):
        if not os.path.isfile(info_path):
            continue
        try:
            with open(info_path, 'r', encoding='utf-8', errors='ignore') as f:
                info = json.load(f)
            tasks = info.get('playTasks', [])
            # Primary task first, then first FileTask
            ordered = sorted(tasks, key=lambda t: (not t.get('isPrimary', False),))
            for task in ordered:
                if task.get('type') == 'FileTask' and task.get('path'):
                    path = task['path'].replace('\\', '/')
                    # Some .info files store a WorkingDir-relative path; try to
                    # resolve it against the install directory if the file doesn't
                    # exist at the literal path.
                    if os.path.isfile(os.path.join(install_path, path)):
                        return path
                    # Try resolving relative to the workingDirectory if present
                    work_dir = task.get('workingDirectory', '')
                    if work_dir:
                        combined = os.path.join(work_dir, path).replace('\\', '/').lstrip('/')
                        if os.path.isfile(os.path.join(install_path, combined)):
                            return combined
                    # DOSBox game: the bundled dosbox.exe won't exist on Linux;
                    # return the system binary so install code skips Proton setup.
                    if ('dosbox' in os.path.basename(path).lower()
                            and path.lower().endswith('.exe')):
                        import shutil
                        for _db in ('dosbox', 'dosbox-staging', 'dosbox-x', 'dosbox-svn'):
                            _found = shutil.which(_db)
                            if _found:
                                return _found
                        return None  # DOSBox game but no dosbox installed
        except Exception as e:
            log.warning(f'_find_gog_executable: {e}')

    # Known Linux script names (explicit list first)
    for name in ('start.sh', 'game.sh', 'launch.sh', 'run.sh'):
        if os.path.isfile(os.path.join(install_path, name)):
            return name

    # Generic fallback: scan the install root for any executable file.
    # Skip known non-executables, hidden files, and directories.
    SKIP_EXTENSIONS = {'.txt', '.md', '.cfg', '.ini', '.conf', '.json', '.log',
                       '.sh.bak', '.bak', '.orig', '.py', '.xml', '.html', '.htm',
                       '.css', '.js', '.desktop', '.png', '.jpg', '.svg', '.ico'}

    def _is_elf(path):
        try:
            with open(path, 'rb') as _f:
                return _f.read(4) == b'\x7fELF'
        except Exception:
            return False

    try:
        executables = []
        for entry in os.scandir(install_path):
            if entry.is_file() and not entry.name.startswith('.'):
                _, ext = os.path.splitext(entry.name)
                if ext.lower() in SKIP_EXTENSIONS:
                    continue
                if os.access(entry.path, os.X_OK) or _is_elf(entry.path):
                    executables.append(entry.name)
        if executables:
            # Prefer known script-like extensions, then alphabetically first.
            script_exts = {'.sh', '.bash', '.run', '.bin'}
            scripts = [e for e in executables
                       if os.path.splitext(e)[1].lower() in script_exts]
            if scripts:
                return sorted(scripts)[0]
            return sorted(executables)[0]
    except Exception as e:
        log.warning(f'_find_gog_executable: generic scan failed: {e}')

    return None


def _cleanup_failed_install(install_path):
    """Delete a partially-created install directory on failure (non-cancelled errors)."""
    if not install_path or not os.path.isdir(install_path):
        return
    try:
        import shutil
        shutil.rmtree(install_path)
        log.info(f'GOG install: cleaned up partial install at {install_path}')
    except Exception as e:
        log.warning(f'GOG install: failed to clean up {install_path} — {e} (user may need to delete manually)')


def install_game(appid, os_pref='auto', progress_cb=None, cancel_ev=None):
    """
    Download and install a GOG game via the content system v2.

    appid      : negative PlayDate integer appid
    os_pref    : 'linux', 'windows', or 'auto' (try Linux first)
    progress_cb: callable(bytes_done, bytes_total) or None
    cancel_ev  : threading.Event — set it to abort mid-install

    Returns {'status': 'success'|'error'|'cancelled', 'install_path': str, 'os': str,
             'message': str, 'platform_executable': str|None}
    """
    from database import get_db, update_game_data

    log.info(f'GOG install started: appid={appid}')
    session = get_valid_session()
    if not session:
        return {'status': 'error', 'message': 'Not connected to GOG — please reconnect'}

    db  = get_db()
    row = db.execute(
        'SELECT name, platform_id FROM games WHERE appid = ?', (appid,)
    ).fetchone()
    db.close()
    if not row:
        return {'status': 'error', 'message': f'Game not found (appid {appid})'}
    log.debug(f'GOG install: game={row["name"]!r}, gog_id={row["platform_id"]}')

    game_name  = row['name']
    gog_id     = row['platform_id']

    # Choose OS — on Windows hosts prefer Windows builds; on Linux prefer Linux
    import platform as _plat
    _host_win = _plat.system() == 'Windows'
    if os_pref == 'auto':
        os_order = ['windows', 'linux'] if _host_win else ['linux', 'windows']
    else:
        os_order = [os_pref]
    chosen_os = None
    builds    = []
    for os_name in os_order:
        b = _get_builds(gog_id, os_name, session)
        log.debug(f'GOG install: _get_builds({gog_id}, {os_name}) → {len(b)} builds')
        if b:
            chosen_os = os_name
            builds    = b
            break

    if not builds:
        return {'status': 'error', 'message': f'No downloadable builds found for {game_name!r}'}

    build = builds[0]
    log.debug(f'GOG install: {game_name!r} — {chosen_os} build')

    # ── Acquire CDN download URL templates ───────────────────────────────────
    try:
        cdn_urls = _get_secure_link_urls(gog_id, session)
    except Exception as e:
        log.warning(f'GOG install: CDN token acquisition failed: {e}')
        return {'status': 'error', 'message': f'CDN token acquisition failed: {e}'}

    # ── Fetch meta manifest ───────────────────────────────────────────────────
    try:
        meta = _fetch_manifest(build['link'], session)
    except Exception as e:
        log.warning(f'GOG install: meta manifest failed: {e}')
        return {'status': 'error', 'message': f'Meta manifest failed: {e}'}

    install_dir  = meta.get('installDirectory') or re.sub(r'[^\w\s-]', '', game_name).strip()
    install_path = os.path.join(GOG_INSTALL_BASE, install_dir)
    os.makedirs(install_path, exist_ok=True)

    # ── Collect files from all relevant depots ────────────────────────────────
    all_files  = []
    total_size = 0

    for depot in meta.get('depots', []):
        manifest_id = depot.get('manifest')
        if not manifest_id:
            log.debug(f'GOG install: depot has no manifest id, skipping. depot keys: {list(depot.keys())}')
            continue
        langs = depot.get('languages') or ['*']
        # Accept language sub-tags: 'en-US' should match 'en'
        has_matching_lang = ('*' in langs or
                             any(l.startswith('en') for l in langs))
        if not has_matching_lang:
            log.debug(f'GOG install: depot {manifest_id} language mismatch: {langs}')
            continue

        # Depot manifests are fetched from the CDN with Bearer token auth,
        # same hash-based path format as meta manifests.
        depot_path   = f'/content-system/v2/meta/{manifest_id[:2]}/{manifest_id[2:4]}/{manifest_id}'
        manifest_url = f'https://gog-cdn-fastly.gog.com{depot_path}'
        try:
            dep_resp = session.get(manifest_url, timeout=30)
            dep_resp.raise_for_status()
            try:
                dm = json.loads(dep_resp.content)
            except (json.JSONDecodeError, ValueError):
                dm = json.loads(_zlib_decomp(dep_resp.content))
            log.debug(f'GOG install: depot {manifest_id} — {len(dm.get("depot", {}).get("items", []))} items')
        except Exception as e:
            log.error(f'GOG install: depot {manifest_id} manifest failed — {e}', exc_info=True)
            continue

        for item in dm.get('depot', {}).get('items', []):
            chunks = item.get('chunks')
            if not chunks:
                continue
            flags = item.get('flags', [])
            all_files.append({
                'path':       item['path'],
                'chunks':     chunks,
                'executable': 'executable' in flags,
            })
            total_size += sum(c.get('size', 0) for c in chunks)

    log.info(f'GOG install: {len(all_files)} files, {total_size / 1e6:.1f} MB — {game_name!r}')

    if not all_files:
        _cleanup_failed_install(install_path)
        return {'status': 'error', 'message': 'No files found in depot manifests', 'install_path': install_path}

    # ── Download and write files ──────────────────────────────────────────────
    done_bytes = 0
    for file_info in all_files:
        if cancel_ev and cancel_ev.is_set():
            _cleanup_failed_install(install_path)
            return {'status': 'cancelled', 'message': 'Install cancelled'}

        rel_path  = file_info['path'].lstrip('/').replace('\\', '/')
        dest_path = os.path.join(install_path, rel_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        try:
            with open(dest_path, 'wb') as fh:
                for chunk in file_info['chunks']:
                    if cancel_ev and cancel_ev.is_set():
                        raise InterruptedError('cancelled')

                    cmd5 = chunk['compressedMd5']
                    url  = _build_chunk_url(cdn_urls, cmd5)

                    resp = session.get(url, timeout=60)
                    resp.raise_for_status()
                    raw  = _zlib_decomp(resp.content)
                    fh.seek(chunk.get('offset', fh.tell()))
                    fh.write(raw)

                    done_bytes += chunk.get('size', len(raw))
                    if progress_cb:
                        progress_cb(done_bytes, total_size)

        except InterruptedError:
            _cleanup_failed_install(install_path)
            return {'status': 'cancelled', 'message': 'Install cancelled'}
        except Exception as e:
            log.error(f'GOG install: chunk download failed for {rel_path} — {e}')
            _cleanup_failed_install(install_path)
            return {'status': 'error',
                    'message': f'Download failed for {rel_path}: {e}',
                    'install_path': install_path}

        if file_info['executable']:
            try:
                os.chmod(dest_path, 0o755)
            except Exception:
                pass

    # ── Determine executable + runner ─────────────────────────────────────────
    platform_executable = _find_gog_executable(install_path, gog_id)
    runner_path         = None
    wine_prefix         = None

    import platform as _plat
    _exe_lower = (platform_executable or '').lower()
    _is_dosbox_exe = 'dosbox' in os.path.basename(_exe_lower) and not _exe_lower.endswith('.exe')
    if chosen_os == 'windows' and platform_executable and _plat.system() != 'Windows' and not _is_dosbox_exe:
        # Linux host running a Windows GOG game — needs Proton
        from runners.proton import get_default_proton
        proton = get_default_proton()
        if proton:
            runner_path = proton['path']
        wine_prefix = os.path.join(install_path, 'prefix')
        os.makedirs(wine_prefix, exist_ok=True)
        log.info(f'GOG install: Windows game on Linux — Proton={runner_path!r}')
    elif _is_dosbox_exe:
        log.info(f'GOG install: DOSBox game — using system dosbox={platform_executable!r}')
    elif chosen_os == 'linux' and platform_executable:
        exe_abs = os.path.join(install_path, platform_executable)
        if os.path.isfile(exe_abs):
            os.chmod(exe_abs, 0o755)

    # ── Persist to DB ─────────────────────────────────────────────────────────
    update_game_data(
        appid,
        install_path        = install_path,
        installed           = 1,
        platform_executable = platform_executable,
        runner_path         = runner_path,
        wine_prefix         = wine_prefix,
    )

    log.info(f'GOG install complete: {game_name!r} → {install_path}')

    # Ensure the watcher is running — it may not have started if this was the first install
    try:
        from utils import start_gog_watcher
        start_gog_watcher(GOG_INSTALL_BASE)
    except Exception:
        pass

    return {
        'status':               'success',
        'install_path':         install_path,
        'os':                   chosen_os,
        'platform_executable':  platform_executable,
        'message':              f'Installed to {install_path}',
    }


# ── Background install management ─────────────────────────────────────────────

def start_install(appid, os_pref='auto'):
    """
    Start a GOG game install in a background thread.
    Returns immediately with {'status': 'started'} or {'status': 'already_running'}.
    Poll get_install_state(appid) for progress.
    """
    log.info(f'GOG start_install: appid={appid}, os_pref={os_pref}')
    from database import get_db as _get_db
    _db = _get_db()
    _row = _db.execute('SELECT name FROM games WHERE appid = ?', (appid,)).fetchone()
    _db.close()
    game_name = _row['name'] if _row else 'Unknown'

    with _install_lock:
        if _install_states.get(appid, {}).get('status') == 'running':
            return {'status': 'already_running'}
        cancel_ev = threading.Event()
        _install_cancels[appid] = cancel_ev
        _install_states[appid]  = {'status': 'running', 'done': 0, 'total': 0,
                                    'name': game_name, 'message': 'Starting download...'}

    def _progress(done, total):
        with _install_lock:
            _install_states[appid].update({'done': done, 'total': total})

    def _run():
        try:
            result = install_game(appid, os_pref=os_pref,
                                  progress_cb=_progress, cancel_ev=cancel_ev)
            with _install_lock:
                _install_states[appid] = {**result, 'name': game_name}
        except Exception as e:
            log.error(f'GOG start_install thread: {e}', exc_info=True)
            with _install_lock:
                _install_states[appid] = {'status': 'error', 'message': str(e), 'name': game_name}
        finally:
            _install_cancels.pop(appid, None)

    threading.Thread(target=_run, daemon=True).start()
    return {'status': 'started'}


def cancel_install(appid):
    """Signal a running install to stop."""
    ev = _install_cancels.get(appid)
    if ev:
        ev.set()


def get_install_state(appid):
    """Return current install state dict for appid."""
    with _install_lock:
        return dict(_install_states.get(appid, {'status': 'not_started'}))


def get_active_install():
    """Return state dict (with appid key) for any running install, or {'appid': None}."""
    with _install_lock:
        for appid, state in _install_states.items():
            if state.get('status') == 'running':
                return {'appid': appid, **state}
    return {'appid': None}


# ── Launch ────────────────────────────────────────────────────────────────────

def launch_gog_game(appid):
    """
    Launch an installed GOG game.
    Returns a dict with 'status' key suitable for the launch API endpoint.
    """
    from database import get_db, update_game_data
    from datetime import datetime, timezone

    db  = get_db()
    row = db.execute(
        'SELECT name, install_path, platform_executable, runner_path, wine_prefix, platform_id '
        'FROM games WHERE appid = ?', (appid,)
    ).fetchone()
    db.close()

    if not row or not row['install_path']:
        return {'status': 'error', 'message': 'Game is not installed'}

    install_path        = row['install_path']
    platform_executable = row['platform_executable']
    runner_path         = row['runner_path']
    wine_prefix         = row['wine_prefix']
    game_name           = row['name']

    if not platform_executable:
        platform_executable = _find_gog_executable(install_path, row['platform_id'] or '')

    if not platform_executable:
        return {'status': 'error',
                'message': f'Cannot find executable for {game_name!r} — please set it manually'}

    import platform as _plat
    _host_win = _plat.system() == 'Windows'
    _is_exe   = platform_executable and platform_executable.lower().endswith('.exe')

    try:
        from runners.launch import check_launch, popen_checked
        # DOSBox game: check .info regardless of what's stored in platform_executable,
        # so games installed before this fix also launch correctly.
        # _get_dosbox_launch returns: (bin, args) = found, None = not found, False = not a dosbox game
        _dosbox = False
        if not _host_win:
            _dosbox = _get_dosbox_launch(install_path, row['platform_id'] or '')

        if _dosbox is None:
            return {'status': 'error',
                    'message': (f'{game_name!r} requires DOSBox but no dosbox binary was found. '
                                'Install dosbox or dosbox-staging.')}
        elif _dosbox:
            dosbox_bin, dosbox_args, dosbox_cwd = _dosbox
            log.info(f'GOG launch (DOSBox): {dosbox_bin} {dosbox_args} (cwd={dosbox_cwd})')
            _, err = popen_checked([dosbox_bin] + dosbox_args, cwd=dosbox_cwd)
            if err:
                log.error(f'GOG: {err["message"]}')
                return err
            proc = None
        elif _is_exe and _host_win:
            # Windows host, Windows game — run the exe directly
            exe_abs = os.path.join(install_path, platform_executable.replace('/', os.sep))
            _, err = popen_checked([exe_abs], cwd=install_path)
            if err:
                log.error(f'GOG: {err["message"]}')
                return err
            proc = None
        elif _is_exe and not _host_win:
            # Linux host, Windows game — Proton preferred, Wine fallback
            prefix = wine_prefix or os.path.join(install_path, 'prefix')
            os.makedirs(prefix, exist_ok=True)
            exe_abs = os.path.join(install_path, platform_executable.replace('/', os.sep))
            from runners.proton import launch_game as _proton_launch, get_default_proton
            _proton = get_default_proton()
            if _proton:
                proc = _proton_launch(install_path, platform_executable, prefix,
                                      proton_path=runner_path or _proton['path'])
            else:
                log.info(f'GOG: no Proton found, falling back to Wine for {game_name!r}')
                from runners.wine import run_in_prefix
                proc = run_in_prefix(prefix_path=prefix, exe=exe_abs)
            err = check_launch(proc)
            if err:
                log.error(f'GOG: {err["message"]}')
                return err
        else:
            # Linux native (or macOS)
            exe_abs = os.path.join(install_path, platform_executable)
            if not os.path.isfile(exe_abs):
                return {'status': 'error', 'message': f'Executable not found: {exe_abs}'}
            if not _host_win:
                os.chmod(exe_abs, 0o755)
            _, err = popen_checked([exe_abs], cwd=install_path)
            if err:
                log.error(f'GOG: {err["message"]}')
                return err
            proc = None

        if proc:
            log.info(f'GOG launch: {game_name!r} (pid {proc.pid})')

        # Update last_played + completion_status
        now_ts = int(datetime.now(timezone.utc).timestamp())
        update_game_data(appid, last_played=now_ts)

        from database import ts_to_date
        return {'status': 'success', 'last_played': ts_to_date(now_ts)}

    except RuntimeError as e:
        return {'status': 'error', 'message': str(e)}
    except Exception as e:
        log.error(f'GOG launch failed: {e}', exc_info=True)
        return {'status': 'error', 'message': str(e)}
