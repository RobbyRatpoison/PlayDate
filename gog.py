"""
gog.py — GOG Galaxy integration for PlayDate.
Handles OAuth2 authentication, library sync, content-system install, and launch.
"""

import copy
import json
import logging
import math
import os
import re
import threading
import time
import zlib
import requests
from config import CONFIG_PATH

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

def _load_cfg():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cfg(data):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(data, f, indent=4)


# ── Token storage ─────────────────────────────────────────────────────────────

def load_gog_tokens():
    """Return stored GOG tokens dict, or None if not connected."""
    gog = _load_cfg().get('gog', {})
    if gog.get('access_token') and gog.get('refresh_token'):
        return gog
    return None


def _save_gog_tokens(access_token, refresh_token, expires_at, username=None, galaxy_user_id=None):
    """Persist GOG tokens (and optionally username / galaxy user ID) to config.json."""
    data = _load_cfg()
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
    _save_cfg(data)


def clear_gog_tokens():
    """Remove all GOG data from config.json."""
    data = _load_cfg()
    data.pop('gog', None)
    _save_cfg(data)


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


def _refresh_tokens():
    """Use the stored refresh_token to obtain a new access_token. Returns True on success."""
    tokens = load_gog_tokens()
    if not tokens:
        return False
    try:
        resp = requests.post(GOG_TOKEN_URL, data={
            'client_id':     GOG_CLIENT_ID,
            'client_secret': GOG_CLIENT_SECRET,
            'grant_type':    'refresh_token',
            'refresh_token': tokens['refresh_token'],
        }, headers=_HEADERS, timeout=15)

        if resp.status_code != 200:
            log.warning(f'GOG token refresh failed: HTTP {resp.status_code}')
            return False

        data       = resp.json()
        expires_at = int(time.time()) + int(data.get('expires_in', 3600))
        _save_gog_tokens(
            data['access_token'],
            data.get('refresh_token', tokens['refresh_token']),
            expires_at,
        )
        return True

    except Exception as e:
        log.error(f'GOG token refresh error: {e}')
        return False


def get_valid_session():
    """
    Return a requests.Session with a valid GOG Bearer token.
    Auto-refreshes if the token has expired. Returns None if not connected.
    """
    tokens = load_gog_tokens()
    if not tokens:
        return None

    # Refresh if expired or within 60 s of expiry
    if int(time.time()) >= tokens.get('expires_at', 0) - 60:
        if not _refresh_tokens():
            return None
        tokens = load_gog_tokens()
        if not tokens:
            return None

    session = requests.Session()
    session.headers.update(_HEADERS)
    session.headers['Authorization'] = f'Bearer {tokens["access_token"]}'
    return session


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

def _next_negative_appid(db):
    """Return the next available negative appid."""
    row = db.execute('SELECT MIN(appid) FROM games WHERE appid < 0').fetchone()
    return (row[0] - 1) if (row[0] is not None) else -1


def sync_library():
    """
    Fetch all owned GOG games and insert new ones into the DB.
    Downloads art for new games via SGDB.
    Returns {'new_games': int, 'total_games': int, 'errors': [str]}.
    """
    session = get_valid_session()
    if not session:
        return {'error': 'Not connected to GOG — please reconnect'}

    errors       = []
    all_products = []
    page         = 1

    # Paginate through all owned products
    while True:
        try:
            resp = session.get(
                'https://embed.gog.com/account/getFilteredProducts',
                params={'mediaType': 1, 'page': page},
                timeout=20,
            )
            if resp.status_code == 401:
                return {'error': 'GOG session expired — please reconnect'}
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            errors.append(f'Page {page}: {e}')
            break

        products = data.get('products', [])
        all_products.extend(products)
        log.info(f'GOG sync: page {page}/{data.get("totalPages", "?")} — {len(products)} products')

        if page >= data.get('totalPages', 1):
            break
        page += 1
        time.sleep(0.3)

    # Only real games, not movies or non-game products
    games = [p for p in all_products if p.get('isGame') and not p.get('isMovie')]
    log.info(f'GOG sync: {len(games)} games from {len(all_products)} products')

    if not games:
        return {'new_games': 0, 'total_games': 0, 'errors': errors}

    from database import get_db
    from datetime import datetime, timezone

    db = get_db()
    try:
        existing = {
            row[0]
            for row in db.execute(
                "SELECT platform_id FROM games WHERE platform = 'gog'"
            ).fetchall()
        }
        blacklisted = {
            row[0]
            for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()
        }

        new_games = []
        today_ts  = int(datetime.now(timezone.utc).timestamp())

        for p in games:
            gog_id = str(p['id'])
            if gog_id in existing or gog_id in blacklisted:
                continue

            next_appid = _next_negative_appid(db)
            name       = p.get('title', f'GOG Game {gog_id}')
            slug       = p.get('slug', '')

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
            new_games.append({'appid': next_appid, 'name': name, 'slug': slug})
            log.info(f'GOG sync: added {name!r} as appid {next_appid}')

        db.commit()
    finally:
        db.close()

    # Download art for new games in the background
    if new_games:
        threading.Thread(
            target=_fetch_art_for_games, args=(new_games,), daemon=True
        ).start()

    result = {
        'new_games':   len(new_games),
        'total_games': len(games),
        'errors':      errors,
    }

    # Auto-detect duplicates for all unlinked GOG games (cheap DB scan, catches
    # cases where a matching Steam game was added after the GOG sync ran)
    result['duplicates_detected'] = auto_detect_duplicates()

    return result


def _normalize_name_for_dup(name):
    """Normalize a game name for duplicate detection (case-insensitive, edition-stripped)."""
    name = name.lower()
    # Strip common edition suffixes that differ between stores
    name = re.sub(
        r'\s*[-–:]\s*(goty|game of the year|complete edition|deluxe edition|gold edition|'
        r'definitive edition|remastered|remaster|enhanced edition|anniversary edition|'
        r'director\'?s cut|ultimate edition|premium edition)\s*$',
        '', name, flags=re.IGNORECASE
    )
    # Remove punctuation except apostrophes, collapse whitespace
    name = re.sub(r"[^\w\s']", ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def auto_detect_duplicates():
    """
    Match GOG games to Steam games by normalized name and set duplicate_of.
    Only sets duplicate_of on GOG games that don't already have it set.
    Returns count of newly marked duplicates.
    """
    from database import get_db
    db = get_db()
    try:
        steam_by_norm = {}
        for row in db.execute(
            "SELECT appid, name FROM games WHERE platform = 'steam' AND name IS NOT NULL"
        ).fetchall():
            norm = _normalize_name_for_dup(row['name'])
            steam_by_norm[norm] = str(row['appid'])

        gog_games = db.execute(
            "SELECT appid, name FROM games WHERE platform = 'gog' "
            "AND (duplicate_of IS NULL OR duplicate_of = '') AND name IS NOT NULL"
        ).fetchall()

        updated = 0
        for row in gog_games:
            norm = _normalize_name_for_dup(row['name'])
            if norm in steam_by_norm:
                db.execute(
                    "UPDATE games SET duplicate_of = ? WHERE appid = ?",
                    (steam_by_norm[norm], row['appid'])
                )
                log.info(f'GOG duplicate: {row["name"]!r} → Steam appid {steam_by_norm[norm]}')
                updated += 1

        if updated:
            db.commit()
        return updated
    finally:
        db.close()


def _fetch_art_for_games(games):
    """Download SGDB art for a list of newly-added GOG games (runs in background)."""
    from images import download_vertical, download_horizontal, download_icon, _sgdb_search_game_id

    for g in games:
        appid = g['appid']
        name  = g['name']
        try:
            sgdb_id = _sgdb_search_game_id(name)
            download_vertical(appid,   sgdb_id=sgdb_id)
            download_horizontal(appid, sgdb_id=sgdb_id)
            download_icon(appid, '',   sgdb_id=sgdb_id)
            log.info(f'GOG art: downloaded for {name!r} (appid {appid})')
        except Exception as e:
            log.warning(f'GOG art: failed for {name!r}: {e}')
        time.sleep(0.3)


# ── Metadata scraper ─────────────────────────────────────────────────────────

_V2_GAMES_URL    = 'https://api.gog.com/v2/games/{gog_id}'
_RATINGS_URL     = 'https://reviews.gog.com/v1/products/{gog_id}/averageRating'
_ACHIEVEMENTS_URL = 'https://gameplay.gog.com/clients/{gog_id}/users/{galaxy_user_id}/achievements'


def _gog_review_score(percent, total):
    """
    Map a 0-100 percentage + review count to a Steam-style review label.
    Mirrors the threshold logic of Steam's review_score_desc.
    """
    if total == 0:
        return 'No Reviews'
    if total < 10:
        return 'Not Enough Reviews'
    if percent >= 95 and total >= 500:
        return 'Overwhelmingly Positive'
    if percent >= 80 and total >= 50:
        return 'Very Positive'
    if percent >= 80:
        return 'Positive'
    if percent >= 70:
        return 'Mostly Positive'
    if percent >= 40:
        return 'Mixed'
    if percent >= 20:
        return 'Mostly Negative'
    if total >= 500:
        return 'Overwhelmingly Negative'
    if total >= 50:
        return 'Very Negative'
    return 'Negative'


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

    release_date = product.get('globalReleaseDate') or product.get('gogReleaseDate')
    if release_date:
        result['release_date'] = str(release_date)[:10]

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
            p       = percent / 100.0

            weighted = 0 if count == 0 else round(
                (p - (p - 0.5) * (2 ** (-math.log10(count + 1)))) * 100
            )

            result['review_percentage']   = percent
            result['weighted_percentage'] = weighted
            result['total_reviews']       = count
            result['positive_reviews']    = round(p * count)
            result['review_score']        = _gog_review_score(percent, count)
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
            valid_gog_ids = set()
            page = 1
            while True:
                resp = session.get(
                    'https://embed.gog.com/account/getFilteredProducts',
                    params={'mediaType': 1, 'page': page}, timeout=20,
                )
                data = resp.json()
                for p in data.get('products', []):
                    if p.get('url') and not p.get('isMovie'):
                        valid_gog_ids.add(str(p['id']))
                if page >= data.get('totalPages', 1):
                    break
                page += 1
                time.sleep(0.3)
        except Exception as e:
            log.warning(f'GOG metadata: library pre-fetch failed — {e}')
            valid_gog_ids = None

    db = get_db()
    try:
        if force:
            rows = db.execute(
                "SELECT appid, platform_id, name FROM games WHERE platform = 'gog'"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT appid, platform_id, name FROM games "
                "WHERE platform = 'gog' AND (meta_fetched IS NULL OR meta_fetched = '0')"
            ).fetchall()
    finally:
        db.close()

    updated = 0
    errors  = 0
    deleted = 0
    today   = date.today().isoformat()

    if not rows:
        return {'updated': updated, 'errors': errors, 'deleted': deleted}

    with _meta_lock:
        _meta_state['total'] = len(rows)

    for row in rows:
        appid  = row['appid']
        gog_id = row['platform_id']
        name   = row['name']

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
        has_store_url = (valid_gog_ids is None or
                         str(row['platform_id']) in valid_gog_ids)
        is_non_game   = (category is None and not has_store_url) or \
                        (category is not None and category != 'GAME')
        if is_non_game:
            try:
                db = get_db()
                db.execute('DELETE FROM games WHERE appid = ?', (appid,))
                db.commit()
                db.close()
                from database import add_to_blacklist
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
    endpoint = copy.deepcopy(cdn_urls[0])
    endpoint['parameters']['path'] = (
        endpoint['parameters'].get('path', '').rstrip('/') + '/' + rel_path
    )
    url = endpoint['url_format']
    for key, value in endpoint['parameters'].items():
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


def _find_gog_executable(install_path, product_id):
    """
    Parse goggame-{product_id}.info for the primary play task executable.
    Returns a forward-slash relative path string, or None.

    On Linux native builds the .info file may be absent or use a different
    convention, so the fallback scans for any executable file in the install root.
    """
    # Look for the canonical file, then any goggame-*.info
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

    for info_path in candidates:
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
    try:
        executables = []
        for entry in os.scandir(install_path):
            if entry.is_file() and not entry.name.startswith('.'):
                _, ext = os.path.splitext(entry.name)
                if ext.lower() in SKIP_EXTENSIONS:
                    continue
                if os.access(entry.path, os.X_OK):
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

    log.info(f'===== GOG install_game called: appid={appid} =====')
    session = get_valid_session()
    if not session:
        log.info('GOG install: session is None')
        return {'status': 'error', 'message': 'Not connected to GOG — please reconnect'}
    log.info('GOG install: session OK')

    db  = get_db()
    row = db.execute(
        'SELECT name, platform_id FROM games WHERE appid = ?', (appid,)
    ).fetchone()
    db.close()
    if not row:
        log.info(f'GOG install: game not found in DB, appid={appid}')
        return {'status': 'error', 'message': f'Game not found (appid {appid})'}
    log.info(f'GOG install: found game {row["name"]!r}, gog_id={row["platform_id"]}')

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
    log.info(f'GOG install: trying OS order={os_order}')
    for os_name in os_order:
        b = _get_builds(gog_id, os_name, session)
        log.info(f'GOG install: _get_builds({gog_id}, {os_name}) returned {len(b)} builds')
        if b:
            chosen_os = os_name
            builds    = b
            break

    if not builds:
        log.info(f'GOG install: no builds found for any OS')
        return {'status': 'error', 'message': f'No downloadable builds found for {game_name!r}'}

    build = builds[0]
    log.info(f'GOG install: {game_name!r} — {chosen_os} build, link={build.get("link", "?")[:120]}')

    # ── Acquire CDN download URL templates ───────────────────────────────────
    try:
        cdn_urls = _get_secure_link_urls(gog_id, session)
        log.info(f'GOG install: got {len(cdn_urls)} CDN URL templates, url_format={cdn_urls[0]["url_format"][:120]}')
    except Exception as e:
        log.info(f'GOG install: CDN token acquisition failed: {e}')
        return {'status': 'error', 'message': f'CDN token acquisition failed: {e}'}

    # ── Fetch meta manifest ───────────────────────────────────────────────────
    log.info(f'GOG install: fetching meta manifest from {build["link"][:120]}')
    try:
        meta = _fetch_manifest(build['link'], session)
        log.info(f'GOG install: meta manifest parsed, keys: {list(meta.keys())}, depots: {len(meta.get("depots", []))}')
    except Exception as e:
        log.info(f'GOG install: meta manifest failed: {e}')
        return {'status': 'error', 'message': f'Meta manifest failed: {e}'}

    install_dir  = meta.get('installDirectory') or re.sub(r'[^\w\s-]', '', game_name).strip()
    install_path = os.path.join(GOG_INSTALL_BASE, install_dir)
    os.makedirs(install_path, exist_ok=True)

    # Depot manifest credentials from the meta manifest
    client_id     = meta.get('clientId', '')
    client_secret = meta.get('clientSecret', '')
    if client_id and client_secret:
        log.info(f'GOG install: got depot credentials — client_id={client_id[:12]}...')

    # ── Collect files from all relevant depots ────────────────────────────────
    all_files  = []
    total_size = 0

    for depot in meta.get('depots', []):
        manifest_id = depot.get('manifest')
        if not manifest_id:
            log.info(f'GOG install: depot has no manifest id, skipping. depot keys: {list(depot.keys())}')
            continue
        langs = depot.get('languages') or ['*']
        # Accept language sub-tags: 'en-US' should match 'en'
        has_matching_lang = ('*' in langs or
                             any(l.startswith('en') for l in langs))
        if not has_matching_lang:
            log.info(f'GOG install: depot {manifest_id} language mismatch: {langs}')
            continue

        # Depot manifests are fetched from the CDN with Bearer token auth,
        # same hash-based path format as meta manifests.
        depot_path = f'/content-system/v2/meta/{manifest_id[:2]}/{manifest_id[2:4]}/{manifest_id}'
        manifest_url = f'https://gog-cdn-fastly.gog.com{depot_path}'
        log.info(f'GOG install: fetching depot manifest {manifest_id} from {manifest_url}')
        try:
            dep_resp = session.get(manifest_url, timeout=30)
            log.info(f'GOG install: depot manifest {manifest_id} — status={dep_resp.status_code}, '
                      f'content-type={dep_resp.headers.get("content-type", "?")}, size={len(dep_resp.content)}')
            raw_preview = dep_resp.content[:300]
            log.info(f'GOG install: depot manifest {manifest_id} — raw bytes (first 300): {raw_preview}')
            dep_resp.raise_for_status()

            # Try plain JSON first, then decompress
            try:
                dm = json.loads(dep_resp.content)
                log.info(f'GOG install: depot manifest {manifest_id} parsed as plain JSON, keys: {list(dm.keys())}')
            except (json.JSONDecodeError, ValueError) as je:
                log.info(f'GOG install: depot manifest {manifest_id} not plain JSON ({je}), trying decompression')
                dm = json.loads(_zlib_decomp(dep_resp.content))
                log.info(f'GOG install: depot manifest {manifest_id} parsed after decompression, keys: {list(dm.keys())}')

            depot_items = dm.get('depot', {}).get('items', [])
            log.info(f'GOG install: depot manifest {manifest_id} — {len(depot_items)} items')
            for itm in depot_items[:3]:
                log.info(f'  item: path={itm.get("path")}, chunks={len(itm.get("chunks", []))}, flags={itm.get("flags")}')

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

    log.info(f'GOG install: {len(all_files)} files, {total_size / 1e6:.1f} MB uncompressed')
    log.info(f'GOG install: meta manifest depots: {len(meta.get("depots", []))}')
    for dep in meta.get('depots', []):
        log.info(f'  depot: {list(dep.keys())}')

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
    if chosen_os == 'windows' and platform_executable and _plat.system() != 'Windows':
        # Linux host running a Windows GOG game — needs Proton
        from runners.proton import get_default_proton
        proton = get_default_proton()
        if proton:
            runner_path = proton['path']
        wine_prefix = os.path.join(install_path, 'prefix')
        os.makedirs(wine_prefix, exist_ok=True)
        log.info(f'GOG install: Windows game on Linux — Proton={runner_path!r}')
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
    log.info(f'===== start_install called: appid={appid}, os_pref={os_pref} =====')
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
        'SELECT name, install_path, platform_executable, runner_path, wine_prefix '
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

    # Re-detect executable if not stored (shouldn't normally happen)
    if not platform_executable:
        from database import get_db as _gdb
        _db = _gdb()
        gog_id = _db.execute('SELECT platform_id FROM games WHERE appid = ?', (appid,)).fetchone()
        _db.close()
        gog_id = gog_id['platform_id'] if gog_id else ''
        platform_executable = _find_gog_executable(install_path, gog_id)

    if not platform_executable:
        return {'status': 'error',
                'message': f'Cannot find executable for {game_name!r} — please set it manually'}

    import platform as _plat
    import subprocess
    _host_win = _plat.system() == 'Windows'
    _is_exe   = platform_executable and platform_executable.lower().endswith('.exe')

    try:
        if _is_exe and _host_win:
            # Windows host, Windows game — run the exe directly
            exe_abs = os.path.join(install_path, platform_executable.replace('/', os.sep))
            proc = subprocess.Popen([exe_abs], cwd=install_path)
        elif _is_exe and not _host_win:
            # Linux host, Windows game — use Proton
            prefix = wine_prefix or os.path.join(install_path, 'prefix')
            os.makedirs(prefix, exist_ok=True)
            from runners.proton import launch_game as _proton_launch
            proc = _proton_launch(install_path, platform_executable, prefix,
                                  proton_path=runner_path or None)
        else:
            # Linux native (or macOS)
            exe_abs = os.path.join(install_path, platform_executable)
            if not os.path.isfile(exe_abs):
                return {'status': 'error', 'message': f'Executable not found: {exe_abs}'}
            if not _host_win:
                os.chmod(exe_abs, 0o755)
            proc = subprocess.Popen([exe_abs], cwd=install_path)

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
