"""SteamGifts won-giveaway import.

Cloudflare blocks PlayDate's backend from fetching steamgifts.com directly, so
the Tampermonkey userscript (steam_date_import.user.js) does the page fetches in
the user's own logged-in browser and POSTs each page's raw HTML here. This module
owns the parsing, the per-account ``steamgifts_wins_<id>.json`` store, and the
apply step that writes the "Won on SteamGifts" group.

Two passes:
  * public  ``/user/<name>/giveaways/won``  (25/page) — every field
  * private ``/giveaways/won``              (50/page) — authoritative received
    state for wins the public page left as "Awaiting feedback"; opt-in, and only
    usable while logged in as the matching account.

The private page embeds live Steam keys. Parsing here never selects the key
node, and ``_scrub`` drops any value that still looks like a key.

See CLAUDE.md and the project_steamgifts_wins_userscript design note.
"""
import datetime
import json
import logging
import os
import re
import threading
import time

import requests
from bs4 import BeautifulSoup
from flask import Blueprint, jsonify, request

from config import (BASE_DIR, get_active_account, get_sg_username,
                    gs_add_owner, gs_is_protected, gs_remove_owner,
                    load_config, load_group_sources, save_config_data,
                    save_group_sources)
from database import get_db

log = logging.getLogger(__name__)

steamgifts_bp = Blueprint('steamgifts', __name__)

GROUP_NAME = 'Won on SteamGifts'
SOURCE_ID  = 'steamgifts:won'

PUBLIC_PAGE_SIZE  = 25
PRIVATE_PAGE_SIZE = 50

_CODE_RE = re.compile(r'/giveaway/([0-9A-Za-z]{5})(?:/|$)')
_KEY_RE  = re.compile(r'[A-Za-z0-9]{5}-[A-Za-z0-9]{5}-[A-Za-z0-9]{5}')
_STORE_REF_RE = re.compile(r'/(app|sub)/(\d+)')

_pkg_cache: dict[int, list[int]] = {}   # subid -> [appid, ...] from packagedetails

_sg_state = {
    'active': False, 'phase': None, 'username': None, 'mode': 'full',
    'full_refresh': False, 'pass2': False,
    'public_pages': 0, 'private_pages': 0,
    'wins_total': 0, 'new_wins': 0, 'changed_wins': 0,
    'script_connected': False, 'finished': False, 'error': None, 'summary': None,
}
_sg_lock = threading.Lock()


# ── wins store ───────────────────────────────────────────────────────────────

def _wins_path() -> str:
    acct = get_active_account() or {}
    sid = acct.get('steam_id', '')
    return os.path.join(BASE_DIR, f'steamgifts_wins_{sid}.json' if sid
                        else 'steamgifts_wins.json')


def load_wins() -> dict:
    try:
        p = _wins_path()
        if os.path.exists(p):
            with open(p) as f:
                data = json.load(f)
            data.setdefault('version', 1)
            data.setdefault('wins', [])
            return data
    except Exception as e:
        log.warning(f"[steamgifts] could not read wins file: {e}")
    return {'version': 1, 'username': '', 'wins': [],
            'last_sync_public': None, 'last_sync_private': None}


def save_wins(data: dict):
    p = _wins_path()
    tmp = p + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, p)


# ── parsing ──────────────────────────────────────────────────────────────────

def _scrub(value):
    """Never let a Steam key survive into a stored record."""
    if isinstance(value, str) and _KEY_RE.search(value):
        return None
    return value


def _code_from_href(href: str):
    m = _CODE_RE.search(href or '')
    return m.group(1) if m else None


def _timestamp(el):
    try:
        return int(el['data-timestamp'])
    except (TypeError, KeyError, ValueError):
        return None


def _ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


def _has_next(soup) -> bool:
    return any('next' in a.get_text(strip=True).lower()
               for a in soup.select('.pagination__navigation a'))


def parse_won_public(html: str) -> dict:
    """Parse a public ``/user/<name>/giveaways/won`` page.

    Returns ``{wins, total, last_page, logged_in_as}``. ``wins`` items:
    ``{code, name, steam_ref, won_ts, gifter, points, received}`` where
    ``received`` is ``True`` / ``False`` / ``None`` (awaiting / unknown).
    """
    soup = BeautifulSoup(html, 'html.parser')
    wins = []

    for row in soup.select('div.giveaway__row-outer-wrap'):
        heading = row.select_one('a.giveaway__heading__name')
        if not heading:
            continue
        name = _scrub(heading.get_text(strip=True))
        code = _code_from_href(heading.get('href'))

        steam_ref = None
        icon = row.select_one('a.giveaway__icon[href*="store.steampowered.com"]')
        if icon:
            m = _STORE_REF_RE.search(icon.get('href') or '')
            if m:
                steam_ref = f'{m.group(1)}/{m.group(2)}'

        points = None
        thin = row.select_one('span.giveaway__heading__thin')
        if thin:
            m = re.search(r'(\d+)', thin.get_text())
            if m:
                points = int(m.group(1))

        cols = row.select_one('div.giveaway__columns')
        if not cols:
            continue
        cells = cols.find_all('div', recursive=False)

        won_ts = None
        if cells:
            won_ts = _timestamp(cells[0].select_one('span[data-timestamp]'))

        # Feedback cell is the one right after "Ended": positive / negative
        # class, or a plain <div> reading "Awaiting feedback".
        received = None
        if len(cells) > 1:
            fb = cells[1]
            fb_classes = fb.get('class') or []
            if 'giveaway__column--positive' in fb_classes:
                received = True
            elif 'giveaway__column--negative' in fb_classes:
                received = False
            # plain div ("Awaiting feedback") -> stays None

        gifter = None
        g = cols.select_one('div.giveaway__column--width-fill a.giveaway__username')
        if g:
            gifter = _scrub(g.get_text(strip=True))

        wins.append({
            'code': code, 'name': name, 'steam_ref': steam_ref,
            'won_ts': won_ts, 'gifter': gifter, 'points': points,
            'received': received,
        })

    total = None
    results = soup.select_one('.pagination__results')
    if results:
        m = re.search(r'of\s*(?:<strong>)?\s*([\d,]+)', str(results))
        if m:
            total = int(m.group(1).replace(',', ''))
    if total is None:
        # Real pages show only "Displaying 1 to 25" with no total; fall back to
        # the featured-table "Gifts Won" count (a link to the won page whose
        # text is the number).
        for a in soup.select('a[href*="/giveaways/won"]'):
            txt = a.get_text(strip=True).replace(',', '')
            if txt.isdigit():
                total = int(txt)
                break

    # SteamGifts' pagination nav is a sliding window (current ±1, First/Next,
    # ellipses) — it never carries the true last page. Derive the page count
    # from the total; otherwise fall back to "is there a Next link".
    pages = _ceil_div(total, PUBLIC_PAGE_SIZE) if total else None
    has_next = _has_next(soup)

    logged_in_as = None
    avatar = soup.select_one('a.nav__avatar-outer-wrap[href^="/user/"]')
    if avatar:
        logged_in_as = avatar['href'].split('/user/', 1)[1].strip('/') or None

    return {'wins': wins, 'total': total, 'pages': pages, 'has_next': has_next,
            'logged_in_as': logged_in_as}


def parse_won_private(html: str) -> dict:
    """Parse a private ``/giveaways/won`` page for received state only.

    Returns ``{rows, last_page}`` with rows ``{code, ended_ts, received}``.
    ``received`` is ``True`` only for the green check; everything else
    (awaiting, not received, legacy blank) is ``False``. The key column is
    deliberately never read.
    """
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    for row in soup.select('div.table__row-outer-wrap'):
        head = row.select_one('a.table__column__heading')
        if not head:
            continue
        code = _code_from_href(head.get('href'))
        ended_ts = _timestamp(
            row.select_one('.table__column--width-fill span[data-timestamp]'))
        icon = row.select_one('.table__column--width-xsmall i')
        received = bool(icon and {'fa-check-circle', 'icon-green'}
                        <= set(icon.get('class') or []))
        rows.append({'code': code, 'ended_ts': ended_ts, 'received': received})

    return {'rows': rows, 'has_next': _has_next(soup)}


# ── merge ────────────────────────────────────────────────────────────────────

def _win_key(rec: dict):
    """Dedup identity: the giveaway code, or (steam_ref, won_ts) when the code
    was stripped (invite-only viewed as a non-winner)."""
    if rec.get('code'):
        return ('code', rec['code'])
    return ('anon', rec.get('steam_ref'), rec.get('won_ts'))


def merge_public_page(store: dict, parsed_wins: list) -> tuple[int, int]:
    """Merge one public page into the store. Returns (new, changed)."""
    index = {_win_key(w): w for w in store['wins']}
    new = changed = 0
    for rec in parsed_wins:
        k = _win_key(rec)
        cur = index.get(k)
        if cur is None:
            rec.setdefault('appid', None)
            store['wins'].append(rec)
            index[k] = rec
            new += 1
            continue
        # Refresh mutable fields (received can resolve over time); keep a
        # previously-resolved appid.
        before = (cur.get('received'), cur.get('gifter'), cur.get('points'))
        cur.update({
            'name': rec['name'], 'steam_ref': rec['steam_ref'],
            'won_ts': rec['won_ts'], 'gifter': rec['gifter'],
            'points': rec['points'], 'received': rec['received'],
        })
        if (cur.get('received'), cur.get('gifter'), cur.get('points')) != before:
            changed += 1
    return new, changed


def apply_private_rows(store: dict, rows: list) -> int:
    """Promote 'awaiting' public wins to received using the private page's
    authoritative per-row state. Returns how many flipped to received."""
    by_code = {w['code']: w for w in store['wins'] if w.get('code')}
    flipped = 0
    for r in rows:
        w = by_code.get(r['code'])
        if w and r['received'] and w.get('received') is not True:
            w['received'] = True
            flipped += 1
    return flipped


def pending_pass2_pages(store: dict) -> list[int]:
    """Private page numbers that hold a win whose received state is still
    unknown (public said 'awaiting'). Both the computed page and the next are
    returned to absorb ordering drift between the two views."""
    ordered = sorted(
        (w for w in store['wins'] if w.get('code')),
        key=lambda w: (w.get('won_ts') or 0), reverse=True)
    max_page = _ceil_div(len(ordered), PRIVATE_PAGE_SIZE) or 1
    pages = set()
    for i, w in enumerate(ordered):
        if w.get('received') is not True:
            p = i // PRIVATE_PAGE_SIZE + 1
            pages.add(p)
            pages.add(min(p + 1, max_page))
    return sorted(pages)


# ── apply to library ─────────────────────────────────────────────────────────

def _package_apps(subid: int, session) -> list[int]:
    if subid in _pkg_cache:
        return _pkg_cache[subid]
    apps = []
    try:
        r = session.get(
            f'https://store.steampowered.com/api/packagedetails?packageids={subid}',
            timeout=10)
        entry = (r.json() or {}).get(str(subid), {})
        if entry.get('success'):
            apps = [a['id'] for a in entry['data'].get('apps', []) if a.get('id')]
    except Exception as e:
        log.warning(f"[steamgifts] packagedetails {subid} failed: {e}")
    _pkg_cache[subid] = apps
    return apps


def _resolve_ref(ref: str, name: str, lib_appids: set, session):
    """Map a stored ``app/N`` / ``sub/N`` giveaway ref to a single library
    appid, or None. For a package: the one owned app, else the best name match
    among owned apps, else the lowest owned appid (usually the base game)."""
    kind, _, sid = (ref or '').partition('/')
    if kind not in ('app', 'sub') or not sid.isdigit():
        return None
    sid = int(sid)
    if kind == 'app':
        return sid if sid in lib_appids else None
    owned = [a for a in _package_apps(sid, session) if a in lib_appids]
    if not owned:
        return None
    if len(owned) == 1:
        return owned[0]
    from metadata import _similar
    best = max(owned, key=lambda a: _similar(name or '', _app_name(a)))
    if _similar(name or '', _app_name(best)) >= 0.5:
        return best
    return min(owned)


def _appdetails_lite(appid: int, session, cache: dict) -> dict:
    """Cached, minimal Steam appdetails lookup used only to explain why a win
    didn't match. Returns {ok, type, name, fullgame_name}; ok=False means the
    store page is gone (delisted/removed)."""
    key = str(appid)
    if key in cache:
        return cache[key]
    out = {'ok': False, 'type': None, 'name': None, 'fullgame_name': None}
    try:
        r = session.get(
            f'https://store.steampowered.com/api/appdetails?appids={appid}&l=english',
            timeout=10)
        entry = (r.json() or {}).get(key, {})
        if entry.get('success'):
            d = entry['data']
            out.update(ok=True, type=d.get('type'), name=d.get('name'))
            fg = d.get('fullgame') or {}
            if fg.get('name'):
                out['fullgame_name'] = fg['name']
    except Exception as e:
        log.warning(f"[steamgifts] appdetails {appid} failed: {e}")
        out['error'] = True
    cache[key] = out
    time.sleep(1.0)   # Steam appdetails rate-limits; only hit for unmatched wins
    return out


def _classify_unmatched(rec: dict, session, cache: dict) -> str:
    """One short user-facing reason a win isn't in the library. The library is
    built from Steam's GetOwnedGames, so 'not there' means Steam no longer
    reports the game as owned — delisted, or removed from the account."""
    ref = rec.get('steam_ref')
    if not ref:
        return 'No Steam store page (gift card or non-Steam reward)'
    kind, _, sid = ref.partition('/')
    if not sid.isdigit():
        return 'Unrecognised Steam link'
    sid = int(sid)
    if kind == 'sub':
        apps = _package_apps(sid, session)
        if not apps:
            return 'Steam package could not be read (likely delisted)'
        return 'Steam package — none of its games are in your library'
    info = _appdetails_lite(sid, session, cache)
    if info.get('error'):
        return 'Could not check Steam (try again later)'
    if not info['ok']:
        return 'Delisted, or removed from your Steam account'
    t = (info.get('type') or '').lower()
    if t and t != 'game':
        label = {'dlc': 'DLC', 'music': 'Soundtrack', 'demo': 'Demo',
                 'application': 'Application'}.get(t, t.title())
        base = info.get('fullgame_name')
        return f'{label} for {base}' if base else f'{label}, not a base game'
    return 'Not in your Steam library (delisted, or removed from your account)'


_app_name_cache: dict[int, str] = {}


def _app_name(appid: int) -> str:
    if appid not in _app_name_cache:
        db = get_db()
        row = db.execute("SELECT name FROM games WHERE appid = ?", (appid,)).fetchone()
        db.close()
        _app_name_cache[appid] = (row['name'] if row else '') or ''
    return _app_name_cache[appid]


def apply_wins(store: dict, *, full_refresh: bool) -> dict:
    """Resolve refs to appids and write the "Won on SteamGifts" group for every
    game with at least one *received* win. Additive unless full_refresh, which
    also prunes games this source added that no longer qualify (respecting
    other group sources via gs_is_protected)."""
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'

    db = get_db()
    cur = db.cursor()
    lib_appids = {r['appid'] for r in cur.execute("SELECT appid FROM games").fetchall()}

    for rec in store['wins']:
        if rec.get('appid') in lib_appids:
            continue
        rec['appid'] = _resolve_ref(rec.get('steam_ref'), rec.get('name'),
                                    lib_appids, session)

    # Explain every win that didn't land in the library.
    det_cache = store.setdefault('appdetails_cache', {})
    unmatched = []
    for rec in store['wins']:
        if rec.get('appid') in lib_appids:
            continue
        unmatched.append({
            'code': rec.get('code'), 'name': rec.get('name'),
            'steam_ref': rec.get('steam_ref'), 'won_ts': rec.get('won_ts'),
            'gifter': rec.get('gifter'), 'received': rec.get('received'),
            'reason': _classify_unmatched(rec, session, det_cache),
        })
    store['unmatched'] = unmatched
    unresolved = len(unmatched)

    received_by_appid: dict[int, bool] = {}
    for rec in store['wins']:
        aid = rec.get('appid')
        if not aid:
            continue
        received_by_appid[aid] = received_by_appid.get(aid, False) or (rec.get('received') is True)

    gs = load_group_sources()
    prev_members = set(gs.get('sources', {}).get(SOURCE_ID, {}).get('members', []))
    members = set() if full_refresh else set(prev_members)
    added = removed = 0

    def _set_groups(appid, groups):
        cur.execute("UPDATE games SET groups = ? WHERE appid = ?",
                    (','.join(sorted(groups)), appid))

    for aid, has_received in received_by_appid.items():
        row = cur.execute("SELECT groups FROM games WHERE appid = ?", (aid,)).fetchone()
        if not row:
            continue
        existing = {g.strip() for g in (row['groups'] or '').split(',') if g.strip()}
        if has_received:
            members.add(aid)
            if GROUP_NAME not in existing:
                existing.add(GROUP_NAME)
                _set_groups(aid, existing)
                added += 1
            gs_add_owner(gs, aid, GROUP_NAME, SOURCE_ID)
        elif full_refresh:
            members.discard(aid)
            if GROUP_NAME in existing and not gs_is_protected(gs, aid, GROUP_NAME, SOURCE_ID):
                existing.discard(GROUP_NAME)
                _set_groups(aid, existing)
                removed += 1
            gs_remove_owner(gs, aid, GROUP_NAME, SOURCE_ID)

    if full_refresh:
        for aid in prev_members - members:
            row = cur.execute("SELECT groups FROM games WHERE appid = ?", (aid,)).fetchone()
            if row:
                existing = {g.strip() for g in (row['groups'] or '').split(',') if g.strip()}
                if GROUP_NAME in existing and not gs_is_protected(gs, aid, GROUP_NAME, SOURCE_ID):
                    existing.discard(GROUP_NAME)
                    _set_groups(aid, existing)
                    removed += 1
            gs_remove_owner(gs, aid, GROUP_NAME, SOURCE_ID)

    gs.setdefault('sources', {})[SOURCE_ID] = {
        'type': 'steamgifts', 'name': GROUP_NAME, 'members': sorted(members)}

    db.commit()
    db.close()
    save_group_sources(gs)

    return {
        'games_in_group': len(members), 'groups_added': added,
        'groups_removed': removed, 'unresolved_refs': unresolved,
        'wins_total': len(store['wins']),
        'unmatched': unmatched,
    }


# ── routes ───────────────────────────────────────────────────────────────────

def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


@steamgifts_bp.route('/api/steamgifts/wins/session', methods=['POST', 'OPTIONS'])
def sg_session():
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.json or {}
    logged_in_as = (data.get('logged_in_as') or '').strip()
    viewing      = (data.get('viewing') or '').strip()

    username = get_sg_username()
    # Auto-resolve: first time, adopt whoever the browser is logged in as.
    if not username and logged_in_as:
        cfg = load_config() or {}
        active_id = cfg.get('active_account', '')
        acct = cfg.get('accounts', {}).get(active_id)
        if acct is not None:
            acct['sg_username'] = logged_in_as
            cfg.pop('sg_username', None)
            save_config_data(cfg)
            username = logged_in_as

    if not username:
        username = viewing or logged_in_as
    if not username:
        return jsonify({'status': 'error',
                        'message': 'No SteamGifts username configured.'}), 400

    mode = 'full' if (logged_in_as and logged_in_as.lower() == username.lower()) else 'degraded'

    with _sg_lock:
        _sg_state.update({
            'active': True, 'phase': 'public', 'username': username, 'mode': mode,
            'full_refresh': bool(data.get('full_refresh')),
            'pass2': bool(data.get('pass2')) and mode == 'full',
            'public_pages': 0, 'private_pages': 0,
            'wins_total': 0, 'new_wins': 0, 'changed_wins': 0,
            'script_connected': True, 'finished': False, 'error': None, 'summary': None,
        })

    return jsonify({
        'status': 'ok', 'username': username, 'mode': mode,
        'pass2': _sg_state['pass2'], 'full_refresh': _sg_state['full_refresh'],
        'public_url': f'/user/{username}/giveaways/won',
        'public_page_size': PUBLIC_PAGE_SIZE,
    })


@steamgifts_bp.route('/api/steamgifts/wins/page', methods=['POST', 'OPTIONS'])
def sg_page():
    if request.method == 'OPTIONS':
        return ('', 204)
    data  = request.json or {}
    phase = data.get('phase')
    page  = int(data.get('page') or 1)
    html  = data.get('html') or ''
    if phase not in ('public', 'private') or not html:
        return jsonify({'status': 'error', 'message': 'bad request'}), 400

    store = load_wins()
    store['username'] = _sg_state.get('username') or store.get('username', '')

    if phase == 'public':
        parsed = parse_won_public(html)
        new, changed = merge_public_page(store, parsed['wins'])
        store['last_sync_public'] = _now_iso()
        if parsed['total']:
            store['total'] = parsed['total']
        save_wins(store)

        # Incremental stop: a full page we've already seen, nothing new/changed,
        # not a full refresh.
        page_all_known = new == 0 and changed == 0 and len(parsed['wins']) > 0
        incremental_stop = (page_all_known and not _sg_state.get('full_refresh')
                            and page > 1)
        # Stop on: an empty page, the incremental cutoff, or once we're past the
        # total-derived page count AND there's no Next link (the total can lag
        # SteamGifts' real count, so Next keeps us honest).
        if not parsed['wins']:
            more = False
        elif incremental_stop:
            more = False
        else:
            within_total = bool(parsed['pages']) and page < parsed['pages']
            more = within_total or parsed['has_next']

        with _sg_lock:
            _sg_state['public_pages'] = max(_sg_state['public_pages'], page)
            _sg_state['new_wins'] += new
            _sg_state['changed_wins'] += changed
            _sg_state['wins_total'] = len(store['wins'])

        return jsonify({'status': 'ok', 'parsed': len(parsed['wins']),
                        'new': new, 'changed': changed, 'more': more,
                        'pages': parsed['pages'], 'total': parsed['total']})

    # private
    parsed = parse_won_private(html)
    flipped = apply_private_rows(store, parsed['rows'])
    store['last_sync_private'] = _now_iso()
    save_wins(store)
    with _sg_lock:
        _sg_state['private_pages'] = max(_sg_state['private_pages'], page)
        _sg_state['changed_wins'] += flipped
    return jsonify({'status': 'ok', 'parsed': len(parsed['rows']), 'flipped': flipped})


@steamgifts_bp.route('/api/steamgifts/wins/pass2-plan')
def sg_pass2_plan():
    if not _sg_state.get('pass2'):
        return jsonify({'status': 'ok', 'enabled': False, 'pages': []})
    store = load_wins()
    pages = pending_pass2_pages(store)
    with _sg_lock:
        _sg_state['phase'] = 'private'
    return jsonify({'status': 'ok', 'enabled': True, 'pages': pages,
                    'private_url': '/giveaways/won',
                    'private_page_size': PRIVATE_PAGE_SIZE})


@steamgifts_bp.route('/api/steamgifts/wins/finish', methods=['POST', 'OPTIONS'])
def sg_finish():
    if request.method == 'OPTIONS':
        return ('', 204)
    store = load_wins()
    try:
        summary = apply_wins(store, full_refresh=bool(_sg_state.get('full_refresh')))
    except Exception as e:
        log.error(f"[steamgifts] apply failed: {e}", exc_info=True)
        with _sg_lock:
            _sg_state.update({'active': False, 'finished': True,
                              'error': 'Apply failed. Check playdate.log.'})
        return jsonify({'status': 'error',
                        'message': 'Apply failed. Check playdate.log.'}), 500
    save_wins(store)
    summary['new_wins'] = _sg_state.get('new_wins', 0)
    summary['changed_wins'] = _sg_state.get('changed_wins', 0)
    with _sg_lock:
        _sg_state.update({'active': False, 'finished': True, 'summary': summary})
    log.info(f"[steamgifts] sync done: {summary}")
    return jsonify({'status': 'ok', 'summary': summary})


@steamgifts_bp.route('/api/steamgifts/wins/status')
def sg_status():
    s = dict(_sg_state)
    s['status'] = 'ok'
    s['configured_username'] = get_sg_username()
    store = load_wins()
    s['stored_wins'] = len(store.get('wins', []))
    s['last_sync_public'] = store.get('last_sync_public')
    s['last_sync_private'] = store.get('last_sync_private')
    s['unmatched_count'] = len(store.get('unmatched', []))
    return jsonify(s)


@steamgifts_bp.route('/api/steamgifts/wins/unmatched')
def sg_unmatched():
    """The wins from the last apply that aren't in the library, each with a
    one-line reason. Sorted by reason then name for a readable list.
    ``adoptable`` marks a row the user can force-add (a delisted game they may
    still own) vs. one that's genuinely not a game (DLC, gift card)."""
    store = load_wins()
    rows = sorted(store.get('unmatched', []),
                  key=lambda r: (r.get('reason', ''), (r.get('name') or '').lower()))
    for r in rows:
        ref = r.get('steam_ref') or ''
        reason = r.get('reason', '')
        r['adoptable'] = (
            ref.startswith(('app/', 'sub/'))
            and ('Delisted' in reason or 'removed' in reason
                 or reason.startswith('Not in your Steam library'))
        )
    return jsonify({'status': 'ok', 'unmatched': rows,
                    'last_sync_public': store.get('last_sync_public')})


@steamgifts_bp.route('/api/steamgifts/wins/adopt', methods=['POST'])
def sg_adopt():
    """Manually add an unmatched win to the library. For a game GetOwnedGames
    won't return (delisted) that the user confirms they still own — creates the
    row from appinfo.vdf and drops it in the "Won on SteamGifts" group."""
    code = ((request.json or {}).get('code') or '').strip()
    if not code:
        return jsonify({'status': 'error', 'message': 'Missing giveaway code'}), 400

    store = load_wins()
    rec = next((w for w in store['wins'] if w.get('code') == code), None)
    if not rec:
        return jsonify({'status': 'error', 'message': 'Unknown win'}), 404

    ref = rec.get('steam_ref') or ''
    kind, _, sid = ref.partition('/')
    if kind == 'app' and sid.isdigit():
        appid = int(sid)
    elif kind == 'sub' and sid.isdigit():
        session = requests.Session()
        session.headers['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        apps = _package_apps(int(sid), session)
        appid = min(apps) if apps else None
    else:
        appid = None
    if appid is None:
        return jsonify({'status': 'error',
                        'message': 'No usable Steam AppID on this win'}), 400

    db = get_db()
    try:
        if db.execute("SELECT 1 FROM games WHERE appid = ?", (appid,)).fetchone():
            group_added = _adopt_into_group(appid, db)
            db.commit()
            return jsonify({'status': 'ok', 'appid': appid, 'already_present': True,
                            'group_added': group_added})
        from database import batch_insert_placeholder_games, update_game_data
        # Steam's own local files still know this game even when GetOwnedGames
        # doesn't: appinfo.vdf for name + release date, localconfig.vdf for
        # playtime / last played, the ACF manifests for installed state.
        info = local = installed_ids = None
        try:
            from utils import (parse_appinfo, fetch_local_library,
                               get_locally_installed_appids)
            info = parse_appinfo().get(appid, {})
            acct = get_active_account() or {}
            local = next((g for g in fetch_local_library(acct.get('steam_id'))
                          if g['appid'] == appid), None)
            installed_ids = get_locally_installed_appids()
        except Exception as e:
            log.warning(f"[steamgifts] adopt: local Steam file read failed: {e}")
        info = info or {}
        name = info.get('name') or rec.get('name') or f'App {appid}'
        playtime = (local or {}).get('playtime_forever') or 0
        import time as _t
        batch_insert_placeholder_games([{
            'appid': appid, 'name': name, 'playtime_forever': playtime,
            'last_played': (local or {}).get('last_played'),
            'completion_status': 'Unfinished' if playtime > 0 else 'Never Played',
            'installed': 1 if installed_ids and appid in installed_ids else 0,
            'icon_hash': '',
        }], int(_t.time()))
        fields = {}
        rd = info.get('steam_release_date') or info.get('original_release_date')
        if rd:
            fields['release_date'] = rd
        # Achievement counts still come from the Web API for a delisted game —
        # GetPlayerAchievements is keyed by appid, not by store listing.
        try:
            from scrapers import fetch_cheevo_data
            cheevo = fetch_cheevo_data(appid) or {}
            if cheevo.get('total_achievements'):
                fields['total_achievements'] = cheevo['total_achievements']
                fields['unlocked_achievements'] = cheevo.get('unlocked_achievements', 0)
                fields['cheevos_fetched'] = _t.strftime('%Y-%m-%d')
                if cheevo.get('completion_status') and playtime > 0:
                    fields['completion_status'] = cheevo['completion_status']
        except Exception as e:
            log.warning(f"[steamgifts] adopt: achievement fetch failed: {e}")
        if fields:
            update_game_data(appid, **fields)
        db = get_db()
        _adopt_into_group(appid, db)
        db.commit()
    finally:
        db.close()

    # Cover art in the background — the Steam CDN and SteamGridDB still serve
    # art by appid/name for a delisted game even when the store page is gone.
    threading.Thread(target=_fetch_adopted_art, args=(appid, name), daemon=True).start()

    rec['appid'] = appid
    save_wins(store)
    log.info(f"[steamgifts] adopted win {code} -> appid {appid} ({name}), playtime {playtime}m")
    return jsonify({'status': 'ok', 'appid': appid, 'name': name, 'added': True,
                    'playtime_forever': playtime})


def _fetch_adopted_art(appid: int, name: str):
    try:
        from datetime import date
        from database import update_game_data
        from images import (download_vertical, download_horizontal, download_icon,
                            _get_steam_assets, _sgdb_search_game_id)
        assets  = _get_steam_assets(appid)
        sgdb_id = _sgdb_search_game_id(name) if name else None
        v = download_vertical(appid, assets=assets, sgdb_id=sgdb_id, game_name=name)
        h = download_horizontal(appid, assets=assets, sgdb_id=sgdb_id, game_name=name)
        i = download_icon(appid, '', sgdb_id=sgdb_id, game_name=name)
        update_game_data(appid, vertical_art_source=v, horizontal_art_source=h,
                         icon_source=i, art_fetched=date.today().isoformat())
        log.info(f"[steamgifts] adopt art {appid}: v={v} h={h} i={i}")
    except Exception as e:
        log.warning(f"[steamgifts] adopt art fetch failed for {appid}: {e}")


def _adopt_into_group(appid: int, db) -> bool:
    """Add GROUP_NAME to a game's groups + record the source. Returns True if
    the group tag was newly added."""
    row = db.execute("SELECT groups FROM games WHERE appid = ?", (appid,)).fetchone()
    existing = {g.strip() for g in ((row['groups'] if row else '') or '').split(',') if g.strip()}
    added = GROUP_NAME not in existing
    if added:
        existing.add(GROUP_NAME)
        db.execute("UPDATE games SET groups = ? WHERE appid = ?",
                   (','.join(sorted(existing)), appid))
    gs = load_group_sources()
    gs_add_owner(gs, appid, GROUP_NAME, SOURCE_ID)
    src = gs.setdefault('sources', {}).setdefault(
        SOURCE_ID, {'type': 'steamgifts', 'name': GROUP_NAME, 'members': []})
    if appid not in src['members']:
        src['members'] = sorted(set(src['members']) | {appid})
    save_group_sources(gs)
    return added


@steamgifts_bp.route('/api/steamgifts/wins/cancel', methods=['POST', 'OPTIONS'])
def sg_cancel():
    if request.method == 'OPTIONS':
        return ('', 204)
    with _sg_lock:
        _sg_state.update({'active': False, 'phase': None, 'script_connected': False})
    return jsonify({'status': 'ok'})
