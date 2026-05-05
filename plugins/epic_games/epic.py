"""
epic.py — Epic Games Store integration for PlayDate.
Handles OAuth2 authentication, library sync, metadata, and cover art.
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

# ── Epic OAuth2 constants ─────────────────────────────────────────────────────
# Public credentials documented in Legendary and EpicResearch.
EPIC_CLIENT_ID     = '34a02cf8f4414e29b15921876da36f9a'
EPIC_CLIENT_SECRET = 'daafbccc737745039dffe53d94fc76cf'
EPIC_TOKEN_URL     = 'https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token'
EPIC_AUTH_REDIRECT = (
    'https://www.epicgames.com/id/login'
    '?redirectUrl=https%3A%2F%2Fwww.epicgames.com%2Fid%2Fapi%2Fredirect'
    '%3FclientId%3D34a02cf8f4414e29b15921876da36f9a%26responseType%3Dcode'
)

_ASSETS_URL         = 'https://launcher-public-service-prod06.ol.epicgames.com/launcher/api/public/assets/Windows?label=Live'
_CATALOG_URL_TMPL   = 'https://catalog-public-service-prod06.ol.epicgames.com/catalog/api/shared/namespace/{ns}/bulk/items'
_STORE_GRAPHQL_URL  = 'https://store.epicgames.com/graphql'
_STORE_GQL_HEADERS  = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Content-Type': 'application/json',
    'Referer': 'https://store.epicgames.com/',
    'Origin': 'https://store.epicgames.com',
}

_RATINGS_QUERY = """
query getProductResult($sandboxId: String!, $locale: String!) {
  RatingsPolls {
    getProductResult(sandboxId: $sandboxId, locale: $locale) {
      averageRating
      pollResult { id total }
    }
  }
}
"""

_SEARCH_STORE_QUERY = """
query searchStoreQuery($namespace: String, $country: String!, $locale: String) {
  Catalog {
    searchStore(namespace: $namespace, country: $country, locale: $locale) {
      elements { productSlug urlSlug description tags { id } }
    }
  }
}
"""

_CATALOG_TAGS_QUERY = """
query catalogTags($namespace: String!) {
  Catalog {
    tags(namespace: $namespace, start: 0, count: 999) {
      elements { id name }
    }
  }
}
"""

# In-process cache of Epic tag id -> name, populated on first use
_tag_name_cache: dict = {}
_tag_cache_lock = threading.Lock()

VERTICAL_DIR   = os.path.join(BASE_DIR, 'static', 'img', 'library', 'vertical')
HORIZONTAL_DIR = os.path.join(BASE_DIR, 'static', 'img', 'library', 'horizontal')


# ── Token storage ─────────────────────────────────────────────────────────────

def load_epic_tokens():
    """Return stored Epic tokens dict, or None if not connected."""
    epic = (load_config() or {}).get('epic_games', {})
    if epic.get('access_token') and epic.get('refresh_token'):
        return epic
    return None


def is_connected():
    return load_epic_tokens() is not None


def get_display_name():
    tokens = load_epic_tokens()
    return tokens.get('display_name') if tokens else None


def clear_epic_tokens():
    """Remove all Epic data from config.json."""
    data = load_config() or {}
    data.pop('epic_games', None)
    _save_config_data(data)


# ── Auth flow ─────────────────────────────────────────────────────────────────

def get_auth_url():
    return EPIC_AUTH_REDIRECT


def _extract_auth_code(raw: str) -> str:
    """
    Accept any of the three formats a user might paste from the Epic auth page:
      - the raw hex code ("2cf717db…")
      - the JSON body  ({"authorizationCode":"2cf717db…",…})
      - the redirectUrl ("https://localhost/launcher/authorized?code=2cf717db…")
    Returns the bare authorization code, or '' if nothing was found.
    """
    raw = raw.strip()
    if raw.startswith('{'):
        try:
            obj = json.loads(raw)
            return (obj.get('authorizationCode') or obj.get('code') or '').strip()
        except Exception:
            pass
    if 'code=' in raw:
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(raw).query)
        return ((qs.get('code') or [''])[0]).strip()
    return raw


def exchange_code(code):
    """
    Exchange an authorization code for Epic tokens.
    Returns (True, display_name) on success, (False, error_message) on failure.
    """
    code = _extract_auth_code(code)
    if not code:
        return False, 'Could not extract an authorization code from the input'
    from runners.oauth2 import exchange_authorization_code
    try:
        data = exchange_authorization_code(
            EPIC_TOKEN_URL, EPIC_CLIENT_ID, EPIC_CLIENT_SECRET,
            code, use_basic_auth=True,
        )
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)

    try:
        access_token  = data['access_token']
        refresh_token = data['refresh_token']
        expires_at    = int(time.time()) + int(data.get('expires_in', 7200))
        account_id    = data.get('account_id', '')
        display_name  = data.get('displayName', '')

        cfg = load_config() or {}
        cfg['epic_games'] = {
            'access_token':  access_token,
            'refresh_token': refresh_token,
            'expires_at':    expires_at,
            'account_id':    account_id,
            'display_name':  display_name,
        }
        _save_config_data(cfg)
        log.info(f'Epic auth: connected as {display_name!r} (account_id={account_id!r})')
        return True, display_name
    except KeyError as e:
        return False, f'Unexpected token response (missing {e})'


def get_valid_session():
    """Return a requests.Session with a valid Epic Bearer token, or None."""
    from runners.oauth2 import get_valid_session as _get_session
    return _get_session(
        'epic_games', EPIC_TOKEN_URL, EPIC_CLIENT_ID, EPIC_CLIENT_SECRET,
        use_basic_auth=True,
    )


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
    """Start a background library sync. Returns {status: 'started'|'already_running'}."""
    with _sync_lock:
        if _sync_state['running']:
            return {'status': 'already_running'}
        _sync_cancel.clear()
        _sync_state.update({
            'running': True, 'phase': 'fetching_assets', 'done': 0, 'total': 0,
            'current_game': '', 'new_games': 0, 'total_games': 0,
            'duplicates_detected': 0, 'error': None,
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
        log.error(f'Epic library sync thread: {e}', exc_info=True)
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error', 'error': str(e)})


def _do_sync_library():
    from database import get_db, update_game_data as _update_game_data
    from datetime import datetime, timezone, date as _date

    session = get_valid_session()
    if not session:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error',
                                'error': 'Not connected to Epic — please reconnect'})
        return

    try:
        resp = session.get(_ASSETS_URL, timeout=20)
        resp.raise_for_status()
        assets = resp.json()
    except Exception as e:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'error',
                                'error': f'Failed to fetch Epic library: {e}'})
        return

    assets = [a for a in assets if a.get('namespace') not in ('ue',)]
    if not assets:
        with _sync_lock:
            _sync_state.update({'running': False, 'phase': 'done', 'new_games': 0, 'total_games': 0})
        return

    log.info(f'Epic sync: {len(assets)} assets to process')

    # Load existing/blacklisted cids up front so we can skip catalog API calls
    # for games already in the DB -- avoids fetching 50+ batches on every re-sync.
    db = get_db()
    try:
        existing = {row['platform_id'] for row in db.execute(
            "SELECT platform_id FROM games WHERE platform = 'epic_games'"
        ).fetchall()}
        blacklisted = {
            row[0]
            for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()
        }
    finally:
        db.close()

    # Collect all appNames per catalogItemId -- Epic often has multiple asset records
    # for the same game (entitlement + installable). We need to pick the right one.
    # Installable assets have a non-empty buildVersion; entitlement records do not.
    cid_appnames = {}  # catalogItemId -> [(appName, buildVersion), ...]
    by_ns = {}
    for a in assets:
        ns    = a.get('namespace', 'fn')
        cid   = a.get('catalogItemId', '')
        aname = a.get('appName', '')
        if cid and aname and cid not in existing and cid not in blacklisted:
            cid_appnames.setdefault(cid, []).append((aname, a.get('buildVersion', '')))
            by_ns.setdefault(ns, []).append((cid, aname))

    # Resolve best appName per cid before the main loop.
    cid_best_appname = {}
    for cid, entries in cid_appnames.items():
        with_build = [aname for aname, bv in entries if bv]
        best = with_build[0] if with_build else entries[0][0]
        cid_best_appname[cid] = best
        if len(entries) > 1:
            all_names = [a for a, _ in entries]
            log.debug(f'Epic sync: {cid} has {len(entries)} appNames {all_names!r}, chose {best!r}')

    total_new = len(cid_appnames)
    log.info(f'Epic sync: {total_new} new games to process (skipped {len(assets) - total_new} existing)')

    with _sync_lock:
        _sync_state.update({'phase': 'processing', 'done': 0, 'total': total_new, 'current_game': ''})

    today_ts       = int(datetime.now(timezone.utc).timestamp())
    today          = _date.today().isoformat()
    new_games_count = 0
    seen_cids      = set()

    # Per-namespace cache for store/ratings API calls (same ns = same data)
    store_cache   = {}
    ratings_cache = {}

    db = get_db()
    try:
        for ns, items in by_ns.items():
            cids = [cid for cid, _ in items]
            url  = _CATALOG_URL_TMPL.format(ns=ns)

            for i in range(0, len(cids), 50):
                if _sync_cancel.is_set():
                    with _sync_lock:
                        _sync_state.update({'running': False, 'phase': 'stopped',
                                            'new_games': new_games_count,
                                            'total_games': len(assets)})
                    return

                batch = cids[i:i + 50]
                params = [('id', cid) for cid in batch]
                params += [('country', 'US'), ('locale', 'en'), ('includeDLCDetails', 'false')]
                catalog_batch = {}
                try:
                    r = session.get(url, params=params, timeout=20)
                    if r.status_code == 200:
                        catalog_batch = r.json()
                    else:
                        log.warning(f'Epic catalog batch [{ns}]: HTTP {r.status_code}')
                except Exception as e:
                    log.warning(f'Epic catalog batch fetch failed [{ns}]: {e}')

                for cid in batch:
                    if cid in seen_cids or cid in existing or cid in blacklisted:
                        continue
                    seen_cids.add(cid)

                    entry    = catalog_batch.get(cid, {})
                    app_name = cid_best_appname.get(cid, '')
                    name     = entry.get('title') or app_name
                    url_slug = entry.get('urlSlug', '')

                    with _sync_lock:
                        _sync_state['current_game'] = name

                    next_appid = next_negative_appid(db)
                    db.execute(
                        """INSERT OR IGNORE INTO games
                           (appid, name, platform, platform_id, platform_slug, platform_appname,
                            platform_ns, date_added,
                            completion_status, installed,
                            art_fetched, meta_fetched, cheevos_fetched,
                            protondb_fetched, hltb_fetched)
                           VALUES (?, ?, 'epic_games', ?, ?, ?, ?, ?,
                                   'Never Played', 0,
                                   '0', '0', '0', '0', '0')""",
                        (next_appid, name, cid, url_slug, app_name, ns, today_ts),
                    )
                    db.commit()
                    log.info(f'Epic sync: added {name!r} as appid {next_appid}')

                    # Metadata from catalog entry + store/ratings API
                    meta = _extract_metadata(entry)
                    if ns not in store_cache:
                        store_cache[ns] = _fetch_epic_store_data(ns)
                    if ns not in ratings_cache:
                        ratings_cache[ns] = _fetch_epic_ratings(ns)
                    meta.update(store_cache[ns])
                    meta.update(ratings_cache[ns])
                    meta['meta_fetched'] = today
                    try:
                        _update_game_data(next_appid, **meta)
                    except Exception as e:
                        log.warning(f'Epic metadata: DB update failed for {name!r}: {e}')

                    # Art from Epic CDN
                    key_images = entry.get('keyImages', [])
                    try:
                        _download_epic_art(next_appid, key_images)
                        _update_game_data(next_appid, art_fetched=today)
                        log.info(f'Epic art: downloaded for {name!r} (appid {next_appid})')
                    except Exception as e:
                        log.warning(f'Epic art: failed for {name!r}: {e}')

                    new_games_count += 1
                    with _sync_lock:
                        _sync_state['done'] += 1

                    if _sync_cancel.is_set():
                        with _sync_lock:
                            _sync_state.update({'running': False, 'phase': 'stopped',
                                                'new_games': new_games_count,
                                                'total_games': len(assets)})
                        return

                time.sleep(0.3)
    finally:
        db.close()

    # Re-run install detection now that platform_appname is correct for all records
    try:
        from .watcher import sync_epic_install_status
        sync_epic_install_status()
    except Exception as e:
        log.warning(f'Epic sync: install status refresh failed: {e}')

    from database import auto_detect_duplicates
    dupes = auto_detect_duplicates()

    if new_games_count > 0:
        try:
            import_purchase_dates()
        except Exception as e:
            log.warning(f'Epic sync: post-sync date import failed: {e}')

    with _sync_lock:
        _sync_state.update({
            'running': False, 'phase': 'done',
            'new_games': new_games_count, 'total_games': len(assets),
            'duplicates_detected': dupes,
        })


def _fetch_art_for_games(games):
    """Download Epic CDN art for newly-added games (runs in background)."""
    for g in games:
        appid      = g['appid']
        name       = g['name']
        key_images = g.get('key_images', [])
        try:
            _download_epic_art(appid, key_images)
            log.info(f'Epic art: downloaded for {name!r} (appid {appid})')
        except Exception as e:
            log.warning(f'Epic art: failed for {name!r}: {e}')
        time.sleep(0.3)


def _fetch_meta_for_new_games(games):
    """Fetch metadata and ratings for newly-added games (runs in background).
    Reuses catalog entries already in memory from the library sync."""
    from database import update_game_data
    from datetime import date
    today = date.today().isoformat()
    for g in games:
        appid = g['appid']
        name  = g['name']
        entry = g.get('entry') or {}
        ns    = g.get('ns') or ''
        try:
            meta = _extract_metadata(entry)
            meta['meta_fetched'] = today
            if ns:
                store = _fetch_epic_store_data(ns)
                meta.update(store)
                meta.update(_fetch_epic_ratings(ns))
            update_game_data(appid, **meta)
            log.info(f'Epic meta: fetched for {name!r} (appid {appid})')
        except Exception as e:
            log.warning(f'Epic meta: failed for {name!r}: {e}')
        time.sleep(0.5)


def _get_tag_name_cache():
    """Return the in-process tag id->name map, fetching from Epic if empty."""
    with _tag_cache_lock:
        if _tag_name_cache:
            return _tag_name_cache
    try:
        resp = requests.post(
            _STORE_GRAPHQL_URL,
            headers=_STORE_GQL_HEADERS,
            json={'query': _CATALOG_TAGS_QUERY, 'variables': {'namespace': 'epic'}},
            timeout=15,
        )
        if resp.status_code == 200:
            elements = ((resp.json().get('data') or {})
                        .get('Catalog', {}).get('tags', {}).get('elements', []))
            with _tag_cache_lock:
                for el in elements:
                    if el.get('id') and el.get('name'):
                        _tag_name_cache[el['id']] = el['name']
            log.info(f'Epic tag cache: loaded {len(_tag_name_cache)} tags')
        else:
            log.warning(f'Epic tag cache: HTTP {resp.status_code}')
    except Exception as e:
        log.warning(f'Epic tag cache fetch failed: {e}')
    return _tag_name_cache


def _fetch_epic_store_data(namespace):
    """Fetch store tags and product slug for a game by namespace via GraphQL.
    Returns {'tags': 'comma,separated', 'platform_slug': 'slug'} with only populated keys."""
    try:
        resp = requests.post(
            _STORE_GRAPHQL_URL,
            headers=_STORE_GQL_HEADERS,
            json={'query': _SEARCH_STORE_QUERY,
                  'variables': {'namespace': namespace, 'country': 'US', 'locale': 'en-US'}},
            timeout=10,
        )
        if resp.status_code != 200:
            log.warning(f'Epic store data HTTP {resp.status_code} for {namespace!r}')
            return {}
        elements = ((resp.json().get('data') or {})
                    .get('Catalog', {}).get('searchStore', {}).get('elements', []))
        if not elements:
            return {}
        el = elements[0]
        result = {}
        tag_ids = [t['id'] for t in (el.get('tags') or []) if t.get('id')]
        if tag_ids:
            tag_map = _get_tag_name_cache()
            names = [tag_map[tid] for tid in tag_ids if tid in tag_map]
            if names:
                result['tags'] = ','.join(names)
                log.info(f'Epic store tags for {namespace!r}: {names}')
        slug = (el.get('productSlug') or el.get('urlSlug') or '').strip()
        if slug:
            result['platform_slug'] = slug
        desc = (el.get('description') or '').strip()
        if desc:
            result['_description'] = desc
        return result
    except Exception as e:
        log.warning(f'Epic store data fetch failed for {namespace!r}: {e}')
        return {}


def fetch_description(appid, platform_id):
    """Fetch a short description for an Epic game via the store GraphQL API."""
    from database import get_db
    db  = get_db()
    row = db.execute(
        "SELECT platform_ns FROM games WHERE appid = ? AND platform = 'epic_games'",
        (appid,)
    ).fetchone()
    db.close()
    if not row or not row['platform_ns']:
        return None
    data = _fetch_epic_store_data(row['platform_ns'])
    return data.get('_description') or None


def _fetch_epic_ratings(namespace):
    """Fetch user ratings via Epic store GraphQL (no auth required). Returns partial meta dict or {}."""
    import math
    try:
        resp = requests.post(
            _STORE_GRAPHQL_URL,
            headers=_STORE_GQL_HEADERS,
            json={'query': _RATINGS_QUERY, 'variables': {'sandboxId': namespace, 'locale': 'en-US'}},
            timeout=10,
        )
        log.info(f'Epic ratings HTTP {resp.status_code} for {namespace!r}: {resp.text[:300]}')
        if resp.status_code != 200:
            return {}
        result = ((resp.json().get('data') or {})
                  .get('RatingsPolls', {})
                  .get('getProductResult')) or {}
        avg = result.get('averageRating')
        if avg is None:
            log.info(f'Epic ratings: no averageRating for {namespace!r}')
            return {}
        pct   = round(avg / 5 * 100)
        total = sum(p.get('total', 0) for p in (result.get('pollResult') or []))
        p     = avg / 5
        weighted = round((p - (p - 0.5) * (2 ** (-math.log10(total + 1)))) * 100)
        return {
            'review_percentage':  pct,
            'review_score':       review_score_label(pct, total),
            'total_reviews':      total,
            'weighted_percentage': weighted,
        }
    except Exception as e:
        log.warning(f'Epic ratings fetch failed for {namespace!r}: {e}')
        return {}


def _extract_metadata(entry):
    """
    Pull the useful fields from a catalog entry dict.
    Returns a meta dict ready for update_game_data (without meta_fetched).
    """
    from datetime import datetime
    meta = {}

    # customAttributes holds developerName/publisherName/genres as typed values;
    # the top-level developer/publisher fields are often empty.
    custom = {k: (v.get('value') or '') for k, v in entry.get('customAttributes', {}).items()}

    devs = (custom.get('developerName') or custom.get('developerDisplayName')
            or entry.get('developer', '')).strip()
    if devs:
        meta['developers'] = devs

    publisher = (custom.get('publisherName') or custom.get('publisherDisplayName')
                 or entry.get('publisher', '') or devs).strip()
    if publisher:
        meta['publishers'] = publisher

    genres_str = custom.get('genres', '').strip()
    if genres_str:
        # Epic stores as "Action,Adventure" -- matches our comma-separated convention
        meta['genres'] = genres_str

    url_slug = entry.get('urlSlug', '').strip()
    if url_slug:
        meta['platform_slug'] = url_slug


    # Use first releaseInfo dateAdded; fall back to creationDate
    release_date_str = ''
    release_info = entry.get('releaseInfo', [])
    if release_info and release_info[0].get('dateAdded'):
        release_date_str = release_info[0]['dateAdded']
    if not release_date_str:
        release_date_str = entry.get('creationDate', '')
    if release_date_str:
        try:
            dt = datetime.fromisoformat(release_date_str.replace('Z', '+00:00'))
            meta['release_date'] = int(dt.timestamp())
        except Exception:
            pass

    return meta


def _download_epic_art(appid, key_images):
    """Download vertical and horizontal art from Epic keyImages list."""
    type_map = {
        'DieselGameBoxTall': os.path.join(VERTICAL_DIR, f'{appid}.jpg'),
        'DieselGameBox':     os.path.join(HORIZONTAL_DIR, f'{appid}.jpg'),
    }
    for img_entry in key_images:
        img_type = img_entry.get('type', '')
        url      = img_entry.get('url', '')
        dest     = type_map.get(img_type)
        if dest and url and not os.path.exists(dest):
            try:
                resp = requests.get(url, timeout=20)
                resp.raise_for_status()
                save_as_jpg(resp.content, dest)
            except Exception as e:
                log.warning(f'Epic art [{img_type}] download failed: {e}')


# ── Metadata scrape ───────────────────────────────────────────────────────────

def _fetch_catalog_entry(session, platform_id, namespace):
    """Fetch a single catalog entry. Returns dict or None."""
    try:
        url    = _CATALOG_URL_TMPL.format(ns=namespace)
        params = [('id', platform_id), ('country', 'US'), ('locale', 'en'),
                  ('includeDLCDetails', 'false')]
        resp = session.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json().get(platform_id)
        log.warning(f'Epic catalog fetch failed for {platform_id}: HTTP {resp.status_code}')
    except Exception as e:
        log.warning(f'Epic catalog fetch failed for {platform_id}: {e}')
    return None


def scrape_single(appid):
    """
    Re-fetch metadata and art for a single Epic game.
    Returns a dict of updated fields, or None on failure.
    """
    session = get_valid_session()
    if not session:
        return None

    from database import get_db
    db  = get_db()
    row = db.execute(
        "SELECT platform_id, platform_slug, platform_ns FROM games WHERE appid = ? AND platform = 'epic_games'",
        (appid,)
    ).fetchone()
    db.close()
    if not row or not row['platform_ns']:
        return None

    entry = _fetch_catalog_entry(session, row['platform_id'], row['platform_ns'])
    if not entry:
        return None

    from datetime import date
    ns   = row['platform_ns']
    meta = _extract_metadata(entry)
    meta['meta_fetched'] = date.today().isoformat()
    meta.update(_fetch_epic_store_data(ns))
    meta.update(_fetch_epic_ratings(ns))

    # Re-fetch art if files are missing
    key_images  = entry.get('keyImages', [])
    vert_path   = os.path.join(VERTICAL_DIR, f'{appid}.jpg')
    horiz_path  = os.path.join(HORIZONTAL_DIR, f'{appid}.jpg')
    if not os.path.exists(vert_path) or not os.path.exists(horiz_path):
        try:
            _download_epic_art(appid, key_images)
        except Exception as e:
            log.warning(f'Epic scrape-single: art re-fetch failed for appid {appid}: {e}')

    return meta


# ── Metadata sync (background) ────────────────────────────────────────────────

_meta_state = {'running': False, 'total': 0, 'done': 0, 'updated': 0, 'errors': 0}
_meta_lock  = threading.Lock()


def get_meta_sync_state():
    with _meta_lock:
        return dict(_meta_state)


def start_meta_sync(force=False):
    """Start background metadata sync. Poll get_meta_sync_state() for progress."""
    with _meta_lock:
        if _meta_state['running']:
            return {'status': 'already_running'}
        _meta_state.update({'running': True, 'total': 0, 'done': 0, 'updated': 0, 'errors': 0})

    def _run():
        try:
            _sync_metadata(force=force)
        except Exception as e:
            log.error(f'Epic meta sync thread: {e}', exc_info=True)
        finally:
            with _meta_lock:
                _meta_state['running'] = False

    threading.Thread(target=_run, daemon=True).start()
    return {'status': 'started'}


def import_purchase_dates():
    """
    Fetch Epic entitlements and update date_added for all matched library games.
    Returns {'updated': int, 'not_found': int} or {'error': str}.
    """
    from database import get_db, update_game_data
    from datetime import datetime

    tokens = load_epic_tokens()
    if not tokens:
        return {'error': 'Epic account not connected'}

    account_id = tokens.get('account_id', '')
    if not account_id:
        return {'error': 'No account ID stored'}

    session = get_valid_session()
    if not session:
        return {'error': 'Could not refresh Epic token'}

    try:
        r = session.get(
            f'https://entitlement-public-service-prod08.ol.epicgames.com'
            f'/entitlement/api/account/{account_id}/entitlements',
            params={'count': 5000},
            timeout=30,
        )
        r.raise_for_status()
        entitlements = r.json()
    except Exception as e:
        log.warning(f'Epic import-dates: entitlements fetch failed: {e}')
        return {'error': f'Failed to fetch entitlements: {e}'}

    if not isinstance(entitlements, list):
        return {'error': 'Unexpected entitlements response format'}

    log.info(f'Epic import-dates: {len(entitlements)} entitlements received')

    # Assets API and entitlements API use different catalogItemIds for the same game,
    # but both share the same namespace. Match by namespace; catalogItemId as fallback.
    # Exclude the top-level 'epic' namespace (platform-wide items, not individual games).
    ns_date_map  = {}
    cid_date_map = {}
    for ent in entitlements:
        ns  = ent.get('namespace', '')
        cid = ent.get('catalogItemId', '')
        raw_date = ent.get('grantDate') or ent.get('createdDate') or ent.get('created')
        if not raw_date:
            continue
        try:
            ts = int(datetime.fromisoformat(raw_date.replace('Z', '+00:00')).timestamp())
        except Exception:
            continue
        if ns and ns != 'epic':
            if ns not in ns_date_map or ts < ns_date_map[ns]:
                ns_date_map[ns] = ts
        if cid:
            if cid not in cid_date_map or ts < cid_date_map[cid]:
                cid_date_map[cid] = ts

    db   = get_db()
    rows = db.execute(
        "SELECT appid, platform_id, platform_ns FROM games WHERE platform = 'epic_games'"
    ).fetchall()
    db.close()

    updated   = 0
    not_found = 0
    for row in rows:
        appid       = row['appid']
        platform_id = row['platform_id'] or ''
        platform_ns = row['platform_ns'] or ''
        ts = cid_date_map.get(platform_id) or ns_date_map.get(platform_ns)
        if ts is None:
            not_found += 1
            continue
        try:
            update_game_data(appid, date_added=ts)
            updated += 1
        except Exception as e:
            log.warning(f'Epic import-dates: DB update failed for {platform_id}: {e}')

    log.info(f'Epic import-dates: {updated} updated, {not_found} not in library')
    return {'updated': updated, 'not_found': not_found}


def _sync_metadata(force=False):
    session = get_valid_session()
    if not session:
        return

    from database import get_db
    from datetime import date

    db = get_db()
    try:
        if force:
            rows = db.execute(
                "SELECT appid, platform_id, platform_ns, name FROM games WHERE platform = 'epic_games'"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT appid, platform_id, platform_ns, name FROM games "
                "WHERE platform = 'epic_games' AND (meta_fetched IS NULL OR meta_fetched = '0')"
            ).fetchall()

        updated = 0
        errors  = 0
        today   = date.today().isoformat()

        with _meta_lock:
            _meta_state['total'] = len(rows)

        from database import update_game_data
        for row in rows:
            appid       = row['appid']
            platform_id = row['platform_id']
            platform_ns = row['platform_ns'] or ''
            name        = row['name']

            if not platform_ns:
                errors += 1
                with _meta_lock:
                    _meta_state.update({'done': _meta_state['done'] + 1,
                                        'updated': updated, 'errors': errors})
                continue

            entry = _fetch_catalog_entry(session, platform_id, platform_ns)
            if entry is None:
                try:
                    update_game_data(appid, meta_fetched=today)
                except Exception:
                    pass
                errors += 1
            else:
                meta = _extract_metadata(entry)
                meta['meta_fetched'] = today
                meta.update(_fetch_epic_store_data(platform_ns))
                meta.update(_fetch_epic_ratings(platform_ns))

                try:
                    update_game_data(appid, **meta)
                    log.info(f'Epic metadata: updated {name!r} (appid {appid})')
                    updated += 1
                except Exception as e:
                    log.error(f'Epic metadata: DB update failed for {name!r}: {e}')
                    errors += 1

            with _meta_lock:
                _meta_state.update({'done': _meta_state['done'] + 1,
                                    'updated': updated, 'errors': errors})
            time.sleep(0.5)

    finally:
        db.close()

    log.info(f'Epic metadata sync complete: {updated} updated, {errors} errors')
