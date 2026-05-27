import logging

from flask import Blueprint, request, jsonify
from database import get_db, update_game_data

log = logging.getLogger(__name__)

bp = Blueprint('ea_app', __name__, url_prefix='/api/ea_app',
               template_folder='templates')


@bp.route('/status')
def ea_status():
    from .ea import is_connected, get_display_name
    if not is_connected():
        return jsonify({'connected': False, 'username': None})
    return jsonify({'connected': True, 'username': get_display_name()})


@bp.route('/auth-url')
def ea_auth_url():
    from .ea import get_auth_url
    return jsonify({'url': get_auth_url()})


@bp.route('/token-url')
def ea_token_url():
    return jsonify({'url': (
        'https://accounts.ea.com/connect/auth'
        '?client_id=ORIGIN_JS_SDK'
        '&response_type=token'
        '&redirect_uri=nucleus%3Arest'
        '&prompt=none'
    )})


@bp.route('/callback', methods=['POST'])
def ea_callback():
    raw = ((request.json or {}).get('code') or '').strip()
    if not raw:
        return jsonify({'status': 'error', 'message': 'code is required'}), 400
    from .ea import exchange_code
    ok, result = exchange_code(raw)
    if ok:
        return jsonify({'status': 'success', 'username': result})
    return jsonify({'status': 'error', 'message': result}), 400


@bp.route('/disconnect', methods=['POST'])
def ea_disconnect():
    from .ea import clear_ea_tokens
    clear_ea_tokens()
    return jsonify({'status': 'success'})


@bp.route('/sync', methods=['POST'])
def ea_sync():
    from .ea import start_library_sync
    result = start_library_sync()
    return jsonify(result)


@bp.route('/sync/status')
def ea_sync_status():
    from .ea import get_sync_state
    return jsonify(get_sync_state())


@bp.route('/sync/cancel', methods=['POST'])
def ea_sync_cancel():
    from .ea import cancel_library_sync
    cancel_library_sync()
    return jsonify({'status': 'ok'})


@bp.route('/open-browser-login', methods=['POST'])
def ea_open_browser_login():
    from .ea import start_browser_login
    result = start_browser_login()
    return jsonify(result)


@bp.route('/browser-login-status')
def ea_browser_login_status():
    from .ea import get_browser_login_state
    return jsonify(get_browser_login_state())


@bp.route('/cancel-browser-login', methods=['POST'])
def ea_cancel_browser_login():
    from .ea import cancel_browser_login
    cancel_browser_login()
    return jsonify({'status': 'ok'})


@bp.route('/bulk-date-import', methods=['POST'])
def ea_bulk_date_import():
    import re
    data   = request.get_json() or {}
    titles = data.get('titles', {})   # {game_title: unix_timestamp}
    if not titles:
        return jsonify({'status': 'error', 'message': 'No titles provided'}), 400

    def norm(s):
        return re.sub(r'[^a-z0-9]', '', s.lower())

    # Strip common suffixes before a second-pass lookup
    _SUFFIXES = re.compile(
        r'\s*(deluxe edition|standard edition|special edition|complete edition'
        r'|definitive edition|gold edition|premium edition'
        r'|origin game time|beta|trial|demo'
        r'|\(\d{4}\))\s*$',
        re.IGNORECASE,
    )

    def norm_stripped(s):
        # Strip suffixes repeatedly (e.g. "Game™ (2008) Deluxe Edition")
        prev = None
        while prev != s:
            prev = s
            s = _SUFFIXES.sub('', s).strip()
        return norm(s)

    db   = get_db()
    rows = db.execute("SELECT appid, name FROM games WHERE platform='ea_app'").fetchall()
    db.close()

    name_map         = {norm(row['name']): row['appid'] for row in rows}
    name_map_stripped = {norm_stripped(row['name']): row['appid'] for row in rows}

    updated = not_found = 0
    for title, ts in titles.items():
        appid = name_map.get(norm(title)) or name_map_stripped.get(norm_stripped(title))
        if appid and ts:
            update_game_data(appid, date_added=int(ts))
            updated += 1
        else:
            not_found += 1

    log.info(f'EA bulk date import: {updated} updated, {not_found} not found')
    return jsonify({'status': 'success', 'updated': updated, 'not_found': not_found})


@bp.route('/debug-juno/<int:appid>')
def ea_debug_juno(appid):
    """Query Juno GraphQL for all available fields on a game — diagnostic tool."""
    from .ea import get_valid_session, _JUNO_API
    db  = get_db()
    row = db.execute("SELECT platform_id, name FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    if not row:
        return jsonify({'error': 'game not found'}), 404
    offer_id = row['platform_id']
    session  = get_valid_session()
    if not session:
        return jsonify({'error': 'not connected to EA — connect first then retry'}), 401
    # Probe schema by trying one unknown field at a time on top of the known-working query.
    # Each candidate gets its own request; fields that cause errors don't exist.
    base_items   = 'id originOfferId gameSlug baseItem { title }'
    base_legacy  = 'offerId: id contentId'
    candidates = {}
    probes = [
        ('gp_storeUri',      f'query($o:[String!]!){{gameProducts(offerIds:$o,locale:"DEFAULT"){{items{{{base_items} storeUri}}}}}}'),
        ('gp_pdpPath',       f'query($o:[String!]!){{gameProducts(offerIds:$o,locale:"DEFAULT"){{items{{{base_items} pdpPath}}}}}}'),
        ('gp_slug',          f'query($o:[String!]!){{gameProducts(offerIds:$o,locale:"DEFAULT"){{items{{{base_items} slug}}}}}}'),
        ('gp_canonicalSlug', f'query($o:[String!]!){{gameProducts(offerIds:$o,locale:"DEFAULT"){{items{{{base_items} canonicalSlug}}}}}}'),
        ('gp_series',        f'query($o:[String!]!){{gameProducts(offerIds:$o,locale:"DEFAULT"){{items{{{base_items} series{{slug title}}}}}}}}'),
        ('gp_franchise',     f'query($o:[String!]!){{gameProducts(offerIds:$o,locale:"DEFAULT"){{items{{{base_items} franchise{{slug title}}}}}}}}'),
        ('lo_gdpUrl',        f'query($o:[String!]!){{legacyOffers(offerIds:$o,locale:"DEFAULT"){{{base_legacy} gdpUrl}}}}'),
        ('lo_storeUri',      f'query($o:[String!]!){{legacyOffers(offerIds:$o,locale:"DEFAULT"){{{base_legacy} storeUri}}}}'),
        ('lo_slug',          f'query($o:[String!]!){{legacyOffers(offerIds:$o,locale:"DEFAULT"){{{base_legacy} slug}}}}'),
        ('lo_pdpPath',       f'query($o:[String!]!){{legacyOffers(offerIds:$o,locale:"DEFAULT"){{{base_legacy} pdpPath}}}}'),
        ('lo_canonicalSlug', f'query($o:[String!]!){{legacyOffers(offerIds:$o,locale:"DEFAULT"){{{base_legacy} canonicalSlug}}}}'),
    ]
    for label, q in probes:
        try:
            r = session.post(_JUNO_API, json={'query': q, 'variables': {'o': [offer_id]}}, timeout=15)
            j = r.json()
            candidates[label] = 'ERROR' if j.get('errors') else j.get('data')
        except Exception as e:
            candidates[label] = f'EXCEPTION: {e}'
    return jsonify({'offer_id': offer_id, 'name': row['name'], 'candidates': candidates})


@bp.route('/fix-slugs', methods=['POST'])
def ea_fix_slugs():
    """Resolve platform_slug for all EA games via ea.com HEAD probes. No auth needed."""
    from .ea import _resolve_ea_store_slug
    db   = get_db()
    rows = db.execute(
        "SELECT appid, platform_slug FROM games WHERE platform='ea_app' AND platform_slug IS NOT NULL AND platform_slug != ''"
    ).fetchall()
    db.close()
    updated = 0
    for row in rows:
        resolved = _resolve_ea_store_slug(row['platform_slug'])
        if resolved != row['platform_slug']:
            update_game_data(row['appid'], platform_slug=resolved)
            updated += 1
    log.info(f'EA fix-slugs: checked {len(rows)} games, updated {updated}')
    return jsonify({'status': 'success', 'checked': len(rows), 'updated': updated})


@bp.route('/scrape-single/<int:appid>', methods=['POST'])
def ea_scrape_single(appid):
    from .ea import scrape_single
    from database import ts_to_date

    meta = scrape_single(appid)
    if meta is None:
        return jsonify({'status': 'error', 'message': 'Metadata fetch failed'}), 502

    update_game_data(appid, **meta)

    data_out = dict(meta)
    if data_out.get('release_date'):
        data_out['release_date'] = ts_to_date(data_out['release_date']) or ''
    data_out.pop('_description', None)
    return jsonify({'status': 'success', 'data': data_out})
