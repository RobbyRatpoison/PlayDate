"""
metadata.py — `metadata_bp`: fill metadata gaps for non-Steam games by
cross-referencing their Steam counterpart.

Non-Steam plugins (EA, Ubisoft, Epic, GOG, ...) can only provide what their
own store API exposes — usually name, maybe genres/dev/pub/release date, and
never Steam-style tags, review scores, or categories. This module resolves a
game to a Steam AppID and borrows the rest from the existing Steam scraper
pipeline (`scrapers.fetch_store_data` / `fetch_review_data` / `fetch_tag_data`).

Resolution order:
  1. PCGamingWiki — search for the page, parse `|steam appid` out of the
     Infobox game template wikitext. Authoritative when it has an entry.
  2. Steam store search — `store/api/storesearch`, best result gated by a
     stdlib difflib name-similarity ratio. >= HIGH → treated as confirmed;
     LOW..HIGH → stored as `unconfirmed` (needs a manual confirm before
     anything is written); below LOW → no match.

Only ever *fills gaps* — a field the plugin already populated is left alone.
Never touches name, achievements, playtime, or art. The resolved Steam AppID
is cached in `games.steam_appid`; `games.meta_backfill_fetched` records the
outcome ('0'/NULL = never, YYYY-MM-DD = done, 'no_match', 'unconfirmed').
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
_SIM_CONFIRMED = 0.90   # Steam-search: apply immediately
_SIM_MAYBE     = 0.72   # Steam-search: store as 'unconfirmed', wait for the user

_TM_RE          = re.compile(r'[™®©℠]')          # ™ ® © ℠
_YEAR_SUFFIX_RE = re.compile(r'\s*\((?:19|20)\d{2}\)\s*$')
_NONWORD_RE     = re.compile(r'[^\w\s]', re.UNICODE)
_WS_RE          = re.compile(r'\s+')


def _clean_query(name):
    """Light cleanup for search terms: drop trademark glyphs and a trailing
    (YYYY) disambiguator, collapse whitespace. Keeps case and inner
    punctuation — search engines want those."""
    n = _YEAR_SUFFIX_RE.sub('', _TM_RE.sub('', name or ''))
    return _WS_RE.sub(' ', n).strip()


def _norm(name):
    """Normalise a title for comparison: drop trademark glyphs and a trailing
    (YYYY) disambiguator, flatten punctuation to spaces, lowercase. Deliberately
    keeps edition words ('Ultimate', 'Legendary') — those are real, distinct
    products and shouldn't collapse together."""
    n = _TM_RE.sub('', name or '')
    n = _YEAR_SUFFIX_RE.sub('', n)
    n = _NONWORD_RE.sub(' ', n)
    return _WS_RE.sub(' ', n).strip().lower()


def _similar(a, b):
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


# ── PCGamingWiki ─────────────────────────────────────────────────────────────

_PCGW_API = 'https://www.pcgamingwiki.com/w/api.php'
# `|steam appid = 12345` in the Infobox game template. `steam appid side` (DLC /
# alternate editions) uses the same prefix, so require the `=` right after.
_INFOBOX_APPID_RE = re.compile(r'\|\s*steam[ _]?appid\s*=\s*(\d+)', re.I)
_REDIRECT_RE = re.compile(r'^\s*#redirect\s*\[\[\s*([^\]|#]+)', re.I)

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
    """Best-matching PCGamingWiki page title for `name`, None if no good match,
    or _PCGW_UNAVAILABLE if PCGW couldn't be reached."""
    data = _pcgw_get(session, {
        'action': 'query', 'list': 'search', 'format': 'json',
        'srsearch': _clean_query(name), 'srlimit': 6, 'srprop': '',
    })
    if data is _PCGW_UNAVAILABLE:
        return _PCGW_UNAVAILABLE
    hits = data.get('query', {}).get('search', [])
    if not hits:
        return None
    best = max(hits, key=lambda h: _similar(name, h['title']))
    return best['title'] if _similar(name, best['title']) >= _SIM_PCGW else None


def _pcgw_section0_wikitext(title, session):
    data = _pcgw_get(session, {
        'action': 'parse', 'page': title, 'prop': 'wikitext',
        'section': 0, 'format': 'json',
    })
    if data is _PCGW_UNAVAILABLE:
        return _PCGW_UNAVAILABLE
    return data.get('parse', {}).get('wikitext', {}).get('*', '')


def _pcgw_steam_appid(name, session):
    """Steam AppID (int) from the PCGamingWiki infobox for `name`; None if PCGW
    has the game but no Steam AppID; _PCGW_UNAVAILABLE if PCGW couldn't answer."""
    title = _pcgw_find_page(name, session)
    if title is _PCGW_UNAVAILABLE:
        return _PCGW_UNAVAILABLE
    if not title:
        return None
    wikitext = _pcgw_section0_wikitext(title, session)
    if wikitext is _PCGW_UNAVAILABLE:
        return _PCGW_UNAVAILABLE
    # Many name variants ("Dragon Age 2", "Dragon Age Origins") are redirect
    # stubs -- follow one hop to the real page.
    redir = _REDIRECT_RE.match(wikitext)
    if redir:
        title = redir.group(1).strip()
        wikitext = _pcgw_section0_wikitext(title, session)
        if wikitext is _PCGW_UNAVAILABLE:
            return _PCGW_UNAVAILABLE
    m = _INFOBOX_APPID_RE.search(wikitext)
    if m:
        log.info('PCGW: %r -> %s (steam appid %s)', name, title, m.group(1))
        return int(m.group(1))
    return None


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


def resolve_steam_appid(name):
    """(appid | None, confidence) where confidence is
    'pcgw' | 'confirmed' | 'maybe' | 'none' | 'retry'.

    'retry' -- PCGamingWiki was unreachable and Steam search only had a weak
    guess; don't record anything, try again on the next run.
    """
    if not name or not name.strip():
        return None, 'none'
    session = _mw_session()

    pcgw = _pcgw_steam_appid(name, session)
    if isinstance(pcgw, int):
        return pcgw, 'pcgw'
    pcgw_down = pcgw is _PCGW_UNAVAILABLE

    candidates = _steam_search_candidates(name, session)
    if not candidates:
        return (None, 'retry') if pcgw_down else (None, 'none')
    best = max(candidates, key=lambda c: _similar(name, c['name']))
    score = _similar(name, best['name'])
    log.info('Steam search: %r -> %r (%s) score %.2f', name, best['name'], best['id'], score)
    if score >= _SIM_CONFIRMED:
        return best['id'], 'confirmed'
    if pcgw_down:
        # A fuzzy Steam guess isn't worth locking in while PCGW (the better
        # source) is just temporarily throttled.
        return None, 'retry'
    if score >= _SIM_MAYBE:
        return best['id'], 'maybe'
    return None, 'none'


# ── Backfill ────────────────────────────────────────────────────────────────

def _empty(v):
    return v is None or (isinstance(v, str) and not v.strip())


def backfill_metadata(appid, *, force=False):
    """Fill missing metadata for one non-Steam game from its Steam counterpart.

    Returns a dict ready for `update_game_data(**dict)` (always carrying
    `meta_backfill_fetched`, and `steam_appid` once resolved), or None if the
    game isn't found / is a Steam game. Raises `scrapers.RateLimitedError` if
    Steam throttles — callers handle it (bulk_rescrape re-queues; the route
    returns 429).

    `force=True` applies a 'maybe' (fuzzy) match instead of parking it as
    'unconfirmed', and re-runs even if already backfilled.
    """
    from datetime import date

    db = get_db()
    row = db.execute(
        "SELECT name, platform, steam_appid, meta_backfill_fetched, developers, "
        "publishers, genres, categories, tags, release_date, review_score, is_free "
        "FROM games WHERE appid = ?", (appid,)
    ).fetchone()
    db.close()
    if not row or (row['platform'] or 'steam') == 'steam':
        return None
    if row['meta_backfill_fetched'] and row['meta_backfill_fetched'] not in ('0', 'unconfirmed') and not force:
        return None  # already done

    today = date.today().isoformat()
    steam_appid = row['steam_appid']
    if not steam_appid or force:
        steam_appid, confidence = resolve_steam_appid(row['name'])
        if confidence == 'retry':
            return None  # PCGW throttled -- leave it for the next run
        if not steam_appid:
            return {'meta_backfill_fetched': 'no_match'}
        if confidence == 'maybe' and not force:
            # Remember the candidate but don't write anything from it yet.
            return {'steam_appid': steam_appid, 'meta_backfill_fetched': 'unconfirmed'}

    from scrapers import fetch_store_data, fetch_review_data, fetch_tag_data
    store   = fetch_store_data(steam_appid) or {}
    store.pop('type', None)
    store.pop('name', None)
    reviews = fetch_review_data(steam_appid) or {}
    tags    = fetch_tag_data(steam_appid) or {}

    out = {'steam_appid': steam_appid, 'meta_backfill_fetched': today}

    for field in ('developers', 'publishers', 'genres', 'categories'):
        if _empty(row[field]) and not _empty(store.get(field)):
            out[field] = store[field]
    if _empty(row['tags']) and not _empty(tags.get('tags')):
        out['tags'] = tags['tags']
    if row['release_date'] is None and store.get('release_date') is not None:
        out['release_date'] = store['release_date']
    if row['is_free'] is None and 'is_free' in store:
        out['is_free'] = store['is_free']
    # The review set only makes sense as a group, and only if the game has no
    # score at all — a plugin that provided one (GOG) keeps it.
    if _empty(row['review_score']) and reviews.get('total_reviews'):
        out.update(reviews)

    filled = [k for k in out if k not in ('steam_appid', 'meta_backfill_fetched')]
    log.info('backfill %s (steam %s): filled %s', appid, steam_appid, filled or '(nothing — all fields already set)')
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
