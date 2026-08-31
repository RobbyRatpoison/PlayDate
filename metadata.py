"""
metadata.py — `metadata_bp`: fill metadata gaps for any game (non-Steam games
by cross-referencing their Steam counterpart; Steam games straight from their
own store page plus a PCGamingWiki fallback for what Steam itself is missing).

Non-Steam plugins (EA, Ubisoft, Epic, GOG, ...) can only provide what their
own store API exposes — usually name, maybe genres/dev/pub/release date, and
never Steam-style tags, review scores, or categories. This module resolves a
game to a Steam AppID and borrows the rest from the existing Steam scraper
pipeline (`scrapers.fetch_store_data` / `fetch_review_data` / `fetch_tag_data`).

Steam games are handled too: a Steam game that a populate/rescrape left with
missing developer / genres / tags is re-fetched from its own store page, and
anything still blank (a delisted game whose store page is gone, say) is
gap-filled from PCGamingWiki by name.

Resolution order:
  1. PCGamingWiki — search for the page, parse the {{Infobox game}} wikitext.
     If it has a `|steam appid`, use that (best case → full Steam data below).
     Otherwise still keep what the infobox has: developers, publishers,
     genres, modes (→ Single-player / Multi-player categories), and the
     earliest release date. This is what covers store-exclusive classics
     that were never on Steam at all.
  2. Steam store search — `store/api/storesearch`, best result gated by a
     stdlib difflib name-similarity ratio. >= _SIM_CONFIRMED → confirmed;
     _SIM_MAYBE.._SIM_CONFIRMED → `unconfirmed` (needs a manual confirm before
     anything is written); below → no match.

When a Steam AppID is resolved, `scrapers.fetch_store_data / fetch_review_data
/ fetch_tag_data` provide the metadata (tags + reviews included); the PCGW box
only backfills whatever Steam happened to be missing.

Only ever *fills gaps* — a field the plugin (or Steam populate) already
populated is left alone. Never touches name, achievements, playtime, or art.
The resolved Steam AppID is cached in `games.steam_appid`;
`games.meta_backfill_fetched` records the outcome ('0'/NULL = never,
YYYY-MM-DD = done, 'no_match', 'unconfirmed').

`meta_backfill_fetched` gates only the automatic startup sweep — any explicit
user action (the "Backfill Missing Metadata" bulk op, a bulk re-scrape, the
edit modal's "Fill from Steam", or renaming a game) re-attempts regardless,
gated purely on whether core fields are still empty. Renaming a game clears
its `meta_backfill_fetched` and stale `steam_appid` so the next sweep
re-resolves from the new name (see `library.update_game`).
"""

import difflib
import logging
import re
import threading
import time

import requests
from flask import Blueprint, jsonify, request

from database import get_db, update_game_data

log = logging.getLogger(__name__)

metadata_bp = Blueprint('metadata', __name__)

_UA = ('PlayDate/1.9 (game library manager; '
       'https://github.com/RobbyRatpoison/PlayDate-Library-Manager)')

# Similarity thresholds (difflib ratio, 0..1).
_SIM_PCGW      = 0.72   # min title match to trust a PCGamingWiki page
# Infobox fields worth preferring over a weak Steam name-guess.
_USEFUL_BOX_KEYS = ('developers', 'publishers', 'genres', 'categories', 'release_date')
_SIM_CONFIRMED = 0.90   # Steam-search: apply immediately
_SIM_MAYBE     = 0.72   # Steam-search: store as 'unconfirmed', wait for the user

_TM_RE          = re.compile(r'[™®©℠]')          # ™ ® © ℠
_YEAR_SUFFIX_RE = re.compile(r'\s*\((?:19|20)\d{2}\)\s*$')
_NONWORD_RE     = re.compile(r'[^\w\s]', re.UNICODE)
_WS_RE          = re.compile(r'\s+')
# Distribution-channel noise Humble/GOG append to a title (not part of the real
# name): "Aragami DRM-free", "Foo (DRM-Free)", "Bar - DRM-free build",
# "Baz Windows DRM-Free", "Gunmetal Arcadia Zero (Humble Original)".
_DIST_NOISE_RE  = re.compile(
    r'\s*[\-–(]?\s*'
    r'(?:(?:windows|win32|win64|macos|mac|osx|linux)\s+)?'
    r'(?:drm[\s\-]?free(?:\s+build)?|humble(?:\s+bundle)?\s+original)'
    r'\s*\)?\s*$', re.I)


def _clean_query(name):
    """Light cleanup for search terms: drop trademark glyphs, a trailing (YYYY)
    disambiguator, and Humble/GOG distribution suffixes ("DRM-free", "Humble
    Original"); collapse whitespace. Keeps case and inner punctuation — search
    engines want those."""
    n = _DIST_NOISE_RE.sub('', _YEAR_SUFFIX_RE.sub('', _TM_RE.sub('', name or '')))
    return _WS_RE.sub(' ', n).strip()


def _norm(name):
    """Normalise a title for comparison: drop trademark glyphs, a trailing
    (YYYY) disambiguator, and Humble/GOG distribution suffixes, flatten
    punctuation to spaces, lowercase. Deliberately keeps edition words
    ('Ultimate', 'Legendary') — those are real, distinct products and shouldn't
    collapse together."""
    n = _TM_RE.sub('', name or '')
    n = _YEAR_SUFFIX_RE.sub('', n)
    n = _DIST_NOISE_RE.sub('', n)
    n = _NONWORD_RE.sub(' ', n)
    return _WS_RE.sub(' ', n).strip().lower()


def _similar(a, b):
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


# ── PCGamingWiki ─────────────────────────────────────────────────────────────

_PCGW_API = 'https://www.pcgamingwiki.com/w/api.php'
# Fields inside the {{Infobox game}} template wikitext. `steam appid side` (DLC /
# alternate editions) shares the prefix, so `steam appid` needs the `=` right after.
_INFOBOX_APPID_RE = re.compile(r'\|\s*steam[ _]?appid\s*=\s*(\d+)', re.I)
_GOGID_RE         = re.compile(r'\|\s*gogcom id\s*=\s*(\d+)', re.I)
_REDIRECT_RE      = re.compile(r'^\s*#redirect\s*\[\[\s*([^\]|#]+)', re.I)
# {{Infobox game/row/developer|Name}} / {{...publisher|Name|note}} -- first param
_DEV_ROW_RE  = re.compile(r'\{\{\s*Infobox game/row/developer\s*\|\s*([^}|]+?)\s*(?:\||\}\})', re.I)
_PUB_ROW_RE  = re.compile(r'\{\{\s*Infobox game/row/publisher\s*\|\s*([^}|]+?)\s*(?:\||\}\})', re.I)
# {{Infobox game/row/taxonomy/genres | A, B }} -- one comma-separated param
_TAX_GENRES_RE = re.compile(r'\{\{\s*Infobox game/row/taxonomy/genres\s*\|\s*([^}]*?)\s*\}\}', re.I)
_TAX_MODES_RE  = re.compile(r'\{\{\s*Infobox game/row/taxonomy/modes\s*\|\s*([^}]*?)\s*\}\}', re.I)
# {{Infobox game/row/date|Platform|Date string|wrapper=...}} -- second param
_DATE_ROW_RE = re.compile(r'\{\{\s*Infobox game/row/date\s*\|\s*[^|]+\|\s*([^}|]+?)\s*(?:\||\}\})', re.I)

# PCGamingWiki's "modes" taxonomy -> the closest Steam category label.
_MODE_TO_CATEGORY = {'singleplayer': 'Single-player', 'multiplayer': 'Multi-player'}

# PCGamingWiki throttles hard -- confirmed live it 429s after ~20 quick hits.
# Serialise our requests with a minimum gap, and on a 429 stand down entirely
# for a cooldown (a bulk backfill then just uses the Steam-search fallback for
# the rest of the run and picks PCGW back up next time).
_PCGW_MIN_INTERVAL = 1.5
_PCGW_COOLDOWN     = 180
_pcgw_lock          = threading.Lock()
_pcgw_last_request  = 0.0
_pcgw_blocked_until  = 0.0

# Sentinel: PCGamingWiki couldn't answer (throttled / errored), as distinct
# from "answered, no Steam AppID". Callers avoid locking in a weak fallback
# guess when this comes back, and retry PCGW later instead.
_PCGW_UNAVAILABLE = object()


def _mw_session():
    s = requests.Session()
    s.headers['User-Agent'] = _UA
    return s


def _pcgw_get(session, params):
    """Rate-limited PCGamingWiki GET. Returns the parsed JSON dict, or
    _PCGW_UNAVAILABLE on throttle/error (which also starts a cooldown)."""
    global _pcgw_last_request, _pcgw_blocked_until
    with _pcgw_lock:
        if time.time() < _pcgw_blocked_until:
            return _PCGW_UNAVAILABLE
        wait = _PCGW_MIN_INTERVAL - (time.time() - _pcgw_last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            r = session.get(_PCGW_API, params=params, timeout=10)
            _pcgw_last_request = time.time()
            if r.status_code == 429:
                _pcgw_blocked_until = time.time() + _PCGW_COOLDOWN
                log.warning('PCGW 429 -- standing down for %ds', _PCGW_COOLDOWN)
                return _PCGW_UNAVAILABLE
            r.raise_for_status()
            return r.json()
        except Exception as e:
            _pcgw_last_request = time.time()
            log.warning('PCGW request failed (%s): %s', params.get('action'), e)
            return _PCGW_UNAVAILABLE


def _pcgw_find_page(name, session):
    """(page title, section-0 wikitext) for the best PCGamingWiki match, or
    (None, None) if no good match, or _PCGW_UNAVAILABLE if PCGW couldn't be
    reached."""
    clean = _clean_query(name)

    # 1. Exact page title. PCGW article titles usually match the game name, and
    #    its fulltext search regularly buries the real page under partial-title
    #    hits ("Syndicate" -> "Steampunk Syndicate", "Crash Time 4: The
    #    Syndicate", ...). A direct title hit with an {{Infobox game}} is
    #    authoritative.
    wt = _pcgw_section0_wikitext(clean, session)
    if wt is _PCGW_UNAVAILABLE:
        return _PCGW_UNAVAILABLE
    if wt and '{{infobox game' in wt.lower():
        return clean, wt

    # 2. Fulltext search fallback.
    data = _pcgw_get(session, {
        'action': 'query', 'list': 'search', 'format': 'json',
        'srsearch': clean, 'srlimit': 6, 'srprop': '',
    })
    if data is _PCGW_UNAVAILABLE:
        return _PCGW_UNAVAILABLE
    hits = data.get('query', {}).get('search', [])
    if not hits:
        return None, None
    best = max(hits, key=lambda h: _similar(name, h['title']))
    if _similar(name, best['title']) < _SIM_PCGW:
        return None, None
    wt = _pcgw_section0_wikitext(best['title'], session)
    if wt is _PCGW_UNAVAILABLE:
        return _PCGW_UNAVAILABLE
    return best['title'], wt


def _pcgw_section0_wikitext(title, session):
    data = _pcgw_get(session, {
        'action': 'parse', 'page': title, 'prop': 'wikitext',
        'section': 0, 'format': 'json',
    })
    if data is _PCGW_UNAVAILABLE:
        return _PCGW_UNAVAILABLE
    return data.get('parse', {}).get('wikitext', {}).get('*', '')


def _pcgw_parse_date(s):
    """PCGamingWiki dates come at varying precision ('March 28, 1997',
    'September 1995', '1994'). Return a UTC unix timestamp for the start of
    that period, or None."""
    from datetime import datetime, timezone
    s = re.sub(r'<ref.*', '', s or '', flags=re.S).strip().strip(',').strip()
    for fmt in ('%B %d, %Y', '%b %d, %Y', '%B %Y', '%b %Y', '%Y'):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return None


def _pcgw_infobox(name, session):
    """Parsed {{Infobox game}} for `name` -- a dict with any of
    `steam_appid`, `gog_id`, `developers`, `publishers`, `genres`,
    `categories`, `release_date` that PCGamingWiki has (comma-joined, no
    spaces, matching the DB convention). None if there's no matching page;
    _PCGW_UNAVAILABLE if PCGW couldn't answer."""
    found = _pcgw_find_page(name, session)
    if found is _PCGW_UNAVAILABLE:
        return _PCGW_UNAVAILABLE
    title, wt = found
    if not title:
        return None
    # Name variants ("Dragon Age 2", "Dragon Age Origins") are redirect stubs.
    redir = _REDIRECT_RE.match(wt)
    if redir:
        title = redir.group(1).strip()
        wt = _pcgw_section0_wikitext(title, session)
        if wt is _PCGW_UNAVAILABLE:
            return _PCGW_UNAVAILABLE

    box = {'_title': title}

    m = _INFOBOX_APPID_RE.search(wt)
    if m:
        box['steam_appid'] = int(m.group(1))
    m = _GOGID_RE.search(wt)
    if m:
        box['gog_id'] = m.group(1)

    devs = list(dict.fromkeys(d.strip() for d in _DEV_ROW_RE.findall(wt) if d.strip()))
    pubs = list(dict.fromkeys(p.strip() for p in _PUB_ROW_RE.findall(wt) if p.strip()))
    if devs:
        box['developers'] = ','.join(devs)
    if pubs:
        box['publishers'] = ','.join(pubs)

    gm = _TAX_GENRES_RE.search(wt)
    if gm and gm.group(1).strip():
        box['genres'] = ','.join(g.strip() for g in gm.group(1).split(',') if g.strip())
    mm = _TAX_MODES_RE.search(wt)
    if mm and mm.group(1).strip():
        cats = list(dict.fromkeys(
            c for c in (_MODE_TO_CATEGORY.get(x.strip().lower()) for x in mm.group(1).split(','))
            if c))
        if cats:
            box['categories'] = ','.join(cats)

    dates = [d for d in (_pcgw_parse_date(x) for x in _DATE_ROW_RE.findall(wt)) if d]
    if dates:
        box['release_date'] = min(dates)  # earliest platform = original release

    log.info('PCGW: %r -> %s  %s', name, title,
             {k: v for k, v in box.items() if k != '_title'} or '(page found, no infobox data)')
    return box


# ── Steam store search ──────────────────────────────────────────────────────

def _steam_search_candidates(name, session):
    try:
        r = session.get('https://store.steampowered.com/api/storesearch/',
                        params={'term': _clean_query(name), 'l': 'english', 'cc': 'US'}, timeout=8)
        r.raise_for_status()
        return [i for i in r.json().get('items', [])
                if i.get('type') == 'app' and i.get('id') and i.get('name')]
    except Exception as e:
        log.warning('Steam search %r: %s', name, e)
        return []


def _resolve(name):
    """(steam_appid | None, confidence, pcgw_box | None).

    confidence: 'pcgw' | 'confirmed' | 'maybe' | 'none' | 'retry'.
      pcgw       -- Steam AppID straight from a PCGamingWiki infobox
      confirmed  -- Steam search, name matches closely (>= _SIM_CONFIRMED)
      maybe      -- Steam search, partial name match (park as 'unconfirmed')
      none       -- nothing found (PCGW may still return a box with dev/pub/etc.)
      retry      -- PCGW was throttled and Steam only had a weak guess

    pcgw_box carries whatever PCGamingWiki had (dev/pub/genres/modes/release),
    used to gap-fill a game that has a PCGW page but no Steam counterpart.
    """
    if not name or not name.strip():
        return None, 'none', None
    session = _mw_session()

    box = _pcgw_infobox(name, session)
    pcgw_down = box is _PCGW_UNAVAILABLE
    if pcgw_down:
        box = None
    if box and box.get('steam_appid'):
        return box['steam_appid'], 'pcgw', box

    candidates = _steam_search_candidates(name, session)
    if candidates:
        # An exact normalised-name match wins outright, wherever Steam ranked it
        # (its search often buries the real game under sequels/DLC/soundtracks).
        want = _norm(name)
        exact = next((c for c in candidates if _norm(c['name']) == want), None)
        if exact:
            log.info('Steam search: %r -> exact %r (%s)', name, exact['name'], exact['id'])
            return exact['id'], 'confirmed', box
        best = max(candidates, key=lambda c: _similar(name, c['name']))
        score = _similar(name, best['name'])
        log.info('Steam search: %r -> %r (%s) score %.2f', name, best['name'], best['id'], score)
        if score >= _SIM_CONFIRMED:
            return best['id'], 'confirmed', box
        if not pcgw_down and score >= _SIM_MAYBE:
            # A PCGW page carrying real metadata beats a weak, differently-named
            # Steam guess (delisted classics: "Syndicate (1993)" -> "Pizza
            # Syndicate"): take the PCGW data, drop the maybe.
            if box and any(box.get(k) for k in _USEFUL_BOX_KEYS):
                return None, 'none', box
            return best['id'], 'maybe', box

    if pcgw_down and not box:
        return None, 'retry', None
    return None, 'none', box


def resolve_steam_appid(name):
    """(appid | None, confidence) -- see _resolve()."""
    appid, confidence, _ = _resolve(name)
    return appid, confidence


# ── Backfill ────────────────────────────────────────────────────────────────

def _empty(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _store_page_metadata(platform, slug):
    """Ask the platform's plugin to scrape genre/tags/release from its own store
    page (only itch.io implements store_page_metadata). Returns {} otherwise."""
    if not slug:
        return {}
    try:
        import plugins as _plugins
        plugin = _plugins.get(platform)
        fn = getattr(plugin, 'store_page_metadata', None) if plugin else None
        return (fn(slug) or {}) if callable(fn) else {}
    except Exception as e:
        log.warning('store_page_metadata(%s): %s', platform, e)
        return {}


def backfill_metadata(appid, *, force=False, rerun=False):
    """Fill missing metadata for one game.

    Non-Steam games are resolved to a Steam counterpart (PCGamingWiki, then
    Steam search); Steam games use their own AppID directly and fall back to
    PCGamingWiki for whatever their store page couldn't provide.

    Returns a dict ready for `update_game_data(**dict)` (always carrying
    `meta_backfill_fetched`, and `steam_appid` once resolved for a non-Steam
    game), or None if the game isn't found. Raises `scrapers.RateLimitedError`
    if Steam throttles — callers handle it (bulk_rescrape re-queues; the route
    returns 429).

    `rerun=True` re-attempts a game already stamped done / no_match / unconfirmed
    (the automatic sweep never passes it — it filters on the column itself;
    explicit user actions pass it). `force=True` additionally applies a 'maybe'
    (fuzzy) Steam-search match instead of parking it as 'unconfirmed', and
    implies `rerun`.
    """
    from datetime import date

    if force:
        rerun = True

    db = get_db()
    row = db.execute(
        "SELECT name, platform, platform_slug, steam_appid, meta_backfill_fetched, "
        "developers, publishers, genres, categories, tags, release_date, "
        "review_score, is_free "
        "FROM games WHERE appid = ?", (appid,)
    ).fetchone()
    db.close()
    if not row:
        return None
    is_steam = (row['platform'] or 'steam') == 'steam'
    if row['meta_backfill_fetched'] and row['meta_backfill_fetched'] not in ('0', 'unconfirmed') and not rerun:
        return None  # already done

    today = date.today().isoformat()
    steam_appid = row['steam_appid']
    pcgw_box = None
    if is_steam:
        steam_appid = appid  # it is its own Steam counterpart
    elif not steam_appid or force or row['meta_backfill_fetched'] == 'unconfirmed':
        # Re-resolve from the (possibly just-renamed) name. An 'unconfirmed' row
        # is re-resolved every run rather than trusting its parked candidate id,
        # so a bulk re-run never silently applies a fuzzy match.
        steam_appid, confidence, pcgw_box = _resolve(row['name'])
        if confidence == 'retry':
            return None  # PCGW throttled -- leave it for the next run
        if confidence == 'maybe' and not force:
            # Remember the candidate but don't write anything from it yet.
            return {'steam_appid': steam_appid, 'meta_backfill_fetched': 'unconfirmed'}

    def _gap(field):
        return _empty(row[field])

    out = {'meta_backfill_fetched': today}
    # A forced re-resolve that no longer lands on a Steam page must clear the
    # stale candidate id (e.g. a parked 'maybe' that PCGW has since overridden).
    if not is_steam and row['steam_appid'] and not steam_appid:
        out['steam_appid'] = None

    if steam_appid:
        # A real Steam page -- richest source (tags + reviews + the rest).
        if not is_steam:
            out['steam_appid'] = steam_appid
        from scrapers import fetch_store_data, fetch_review_data, fetch_tag_data
        store   = fetch_store_data(steam_appid) or {}
        store.pop('type', None)
        store.pop('name', None)
        reviews = fetch_review_data(steam_appid) or {}
        tags    = fetch_tag_data(steam_appid) or {}

        for field in ('developers', 'publishers', 'genres', 'categories'):
            if _gap(field) and not _empty(store.get(field)):
                out[field] = store[field]
        if _gap('tags') and not _empty(tags.get('tags')):
            out['tags'] = tags['tags']
        if row['release_date'] is None and store.get('release_date') is not None:
            out['release_date'] = store['release_date']
        if row['is_free'] is None and 'is_free' in store:
            out['is_free'] = store['is_free']
        # Review set is a group, only if the game has no score at all.
        if _gap('review_score') and reviews.get('total_reviews'):
            out.update(reviews)
        # Anything the Steam page still didn't have, take from PCGamingWiki.
        # For a non-Steam game we may already hold a box from _resolve(); for a
        # Steam game (or a non-Steam game with a pre-stored appid) fetch one now
        # if any infobox-covered field is still blank -- this is the whole point
        # of running a backfill on a Steam game (delisted store pages, etc).
        _box_fields = ('developers', 'publishers', 'genres', 'categories')
        if pcgw_box is None and any(f not in out and _gap(f) for f in _box_fields):
            pcgw_box = _pcgw_infobox(row['name'], _mw_session())
            if pcgw_box is _PCGW_UNAVAILABLE:
                pcgw_box = None
        if pcgw_box:
            for field in _box_fields:
                if field not in out and _gap(field) and pcgw_box.get(field):
                    out[field] = pcgw_box[field]
            if 'release_date' not in out and row['release_date'] is None and pcgw_box.get('release_date'):
                out['release_date'] = pcgw_box['release_date']

    elif pcgw_box:
        # No Steam page, but PCGamingWiki has the game -- fill dev/pub/genres/
        # modes/release from the infobox. No tags or review score to be had.
        for field in ('developers', 'publishers', 'genres', 'categories'):
            if _gap(field) and pcgw_box.get(field):
                out[field] = pcgw_box[field]
        if row['release_date'] is None and pcgw_box.get('release_date'):
            out['release_date'] = pcgw_box['release_date']

    # Last tier: the platform's own store page (itch.io implements this). Only
    # when there's no Steam page -- Steam tags/genres are always richer. Gap-
    # fills whatever's still missing, including after a PCGW-only match (PCGW
    # never carries tags). itch exclusives have no other source at all.
    if not steam_appid:
        page = _store_page_metadata(row['platform'], row['platform_slug'])
        for field in ('genres', 'categories', 'tags'):
            if field not in out and _gap(field) and page.get(field):
                out[field] = page[field]
        if 'release_date' not in out and row['release_date'] is None and page.get('release_date'):
            out['release_date'] = page['release_date']

    filled = [k for k in out if k not in ('steam_appid', 'meta_backfill_fetched')]
    if not filled and not steam_appid:
        # Reached nothing usable anywhere -- record as no_match so we don't keep
        # re-fetching it.
        return {'meta_backfill_fetched': 'no_match',
                **({'steam_appid': None} if row['steam_appid'] else {})}
    log.info('backfill %s (%s): filled %s', appid,
             f'steam {steam_appid}' if steam_appid else 'pcgw/page-only',
             filled or '(nothing new)')
    return out


# ── Routes ──────────────────────────────────────────────────────────────────

@metadata_bp.route('/api/metadata/backfill/<int:appid>', methods=['POST'])
def backfill_route(appid):
    from scrapers import RateLimitedError
    from database import ts_to_date

    force = bool((request.get_json(silent=True) or {}).get('force'))
    try:
        result = backfill_metadata(appid, force=force)
    except RateLimitedError:
        return jsonify({'status': 'error', 'message': 'Steam is rate-limiting requests — try again in a minute.'}), 429
    except Exception as e:
        log.error('backfill_route %s: %s', appid, e, exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

    if result is None:
        return jsonify({'status': 'error', 'message': 'Not a non-Steam game, or already filled (use force).'}), 400

    update_game_data(appid, **result)

    outcome = result.get('meta_backfill_fetched')
    filled  = [k for k in result if k not in ('steam_appid', 'meta_backfill_fetched')]

    db = get_db()
    game_row = db.execute("SELECT * FROM games WHERE appid = ?", (appid,)).fetchone()
    db.close()
    game = dict(game_row) if game_row else {}
    if game.get('release_date'):
        game['release_date'] = ts_to_date(game['release_date'])

    msg = {
        'no_match':    'No matching Steam game found.',
        'unconfirmed': 'Found a possible Steam match — confirm it to fill the data.',
    }.get(outcome, f'Filled {len(filled)} field(s) from Steam.' if filled else 'Steam match found, but nothing was missing.')

    return jsonify({'status': 'success', 'outcome': outcome, 'filled': filled,
                    'message': msg, 'data': game})
