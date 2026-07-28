"""Steam/GOG purchase-date import: the Tampermonkey userscript flow (pending
dates from Steam Help pages, bulk GOG orders) and non-Steam plugin API date
fetches. See steam_date_import.user.js and CLAUDE.md's Steam/GOG Date Import
section for the full protocol."""
import logging
import threading

from flask import Blueprint, jsonify, request
from urllib.parse import urlparse

from database import get_db, update_game_data

log = logging.getLogger(__name__)

date_import_bp = Blueprint('date_import', __name__)

# ── Pending dates (set by browser userscript from Steam help pages) ───────────
_pending_dates = {}  # appid (int) → 'YYYY-MM-DD'

# ── Bulk date import state ────────────────────────────────────────────────────
_bulk_date_state = {
    'queue':               [],    # [{appid, name}, …] remaining
    'current':             None,  # {appid, name} being processed
    'done':                0,
    'failed':              0,
    'total':               0,
    'active':              False,
    'script_connected':    False, # True once userscript pings back
    'results':             [],    # [{name, appid, date}, …] newest first; date=None means not found
    'api_threads_running': 0,     # background API date-fetch threads still in progress
    'api_errors':          [],    # error messages from failed API fetch threads
}
_bulk_date_lock = threading.Lock()


def _run_api_date_fetch(plugin, appids, appid_names):
    """Background thread: call plugin.fetch_purchase_dates(appids, on_result) and update state."""
    from database import update_game_data, ts_to_date

    reported = [0]  # track how many appids were reported via callback

    def on_result(appid, ts):
        reported[0] += 1
        name = appid_names.get(appid, '')
        if ts:
            update_game_data(appid, date_added=ts)
            with _bulk_date_lock:
                _bulk_date_state['done'] += 1
                _bulk_date_state['results'].insert(0, {
                    'appid': appid, 'name': name, 'date': ts_to_date(ts) or '',
                })
        else:
            with _bulk_date_lock:
                _bulk_date_state['failed'] += 1
                _bulk_date_state['results'].insert(0, {
                    'appid': appid, 'name': name, 'date': None,
                })

    try:
        plugin.fetch_purchase_dates(appids, on_result)
    except Exception as e:
        log.error(f'API date fetch failed for plugin {plugin.id}: {e}', exc_info=True)
        remaining = len(appids) - reported[0]
        if remaining > 0:
            with _bulk_date_lock:
                _bulk_date_state['failed'] += remaining
                _bulk_date_state['api_errors'].append(str(e))
    finally:
        with _bulk_date_lock:
            if _bulk_date_state['api_threads_running'] > 0:
                _bulk_date_state['api_threads_running'] -= 1
            if (_bulk_date_state['api_threads_running'] == 0
                    and not _bulk_date_state['queue']
                    and not _bulk_date_state['current']
                    and _bulk_date_state['active']):
                _bulk_date_state['active'] = False
                log.info(f"Bulk date import finished: "
                         f"{_bulk_date_state['done']} updated, "
                         f"{_bulk_date_state['failed']} not found")


def _bulk_date_advance():
    if _bulk_date_state['queue']:
        nxt = _bulk_date_state['queue'].pop(0)
        _bulk_date_state['current'] = nxt
        return jsonify({'status': 'ok', 'next_appid': nxt['appid'], 'next_name': nxt['name']})
    _bulk_date_state['current'] = None
    # Stay active if API threads are still running
    if not _bulk_date_state['api_threads_running']:
        _bulk_date_state['active'] = False
        log.info(f"Bulk date import finished: {_bulk_date_state['done']} updated, {_bulk_date_state['failed']} not found")
    return jsonify({'status': 'ok', 'next_appid': None})


@date_import_bp.route('/api/pending-date', methods=['POST', 'OPTIONS'])
def pending_date_set():
    if request.method == 'OPTIONS':
        return ('', 204)
    origin = request.headers.get('Origin', '')
    _o = urlparse(origin)
    if origin and not (_o.scheme == 'https' and _o.hostname == 'help.steampowered.com'):
        return jsonify({'status': 'error', 'message': 'Forbidden'}), 403
    data  = request.json or {}
    appid = data.get('appid')
    date  = data.get('date', '').strip()
    if not appid or not date:
        return jsonify({'status': 'error', 'message': 'Missing appid or date'}), 400
    _pending_dates[int(appid)] = date
    log.info(f"Pending date set for AppID {appid}: {date}")
    return jsonify({'status': 'success'})

@date_import_bp.route('/api/pending-date/<int:appid>')
def pending_date_get(appid):
    log.info(f"Pending date poll for AppID {appid} — stored keys: {list(_pending_dates.keys())}")
    date = _pending_dates.pop(appid, None)
    if date:
        log.info(f"Pending date consumed for AppID {appid}: {date}")
        return jsonify({'status': 'success', 'date': date})
    return jsonify({'status': 'none'})

@date_import_bp.route('/api/pending-date/<int:appid>/peek')
def pending_date_peek(appid):
    return jsonify({'pending': appid in _pending_dates})

@date_import_bp.route('/api/bulk-date-import/start', methods=['POST'])
def bulk_date_import_start():
    data   = request.json or {}
    scope  = data.get('scope', 'selected')
    appids = data.get('appids', [])
    db  = get_db()
    if scope == 'all':
        rows = db.execute('SELECT appid, name, platform FROM games ORDER BY name').fetchall()
    elif appids:
        ph   = ','.join('?' * len(appids))
        rows = db.execute(f'SELECT appid, name, platform FROM games WHERE appid IN ({ph})', appids).fetchall()
    else:
        db.close()
        return jsonify({'status': 'error', 'message': 'No games provided.'}), 400
    db.close()

    import plugins as _plugins
    # Steam games go through the per-page Help flow; plugins with date_import_url
    # (e.g. GOG) are handled via their external orders page + Tampermonkey script.
    # Plugins with fetch_purchase_dates are handled via direct API calls.
    steam_rows = [r for r in rows if (r['platform'] or 'steam') == 'steam']

    seen_urls        = set()
    date_import_urls = []
    api_by_platform  = {}  # plat -> [row, …] for plugins with fetch_purchase_dates
    for r in rows:
        plat   = r['platform'] or 'steam'
        plugin = _plugins.get(plat)
        if not plugin:
            continue
        if hasattr(plugin, 'date_import_url'):
            url = plugin.date_import_url
            if url not in seen_urls:
                seen_urls.add(url)
                date_import_urls.append({'url': url, 'label': getattr(plugin, 'label', plugin.name)})
        elif hasattr(plugin, 'fetch_purchase_dates'):
            api_by_platform.setdefault(plat, []).append(r)

    appid_names = {r['appid']: r['name'] for r in rows}
    queue       = [{'appid': r['appid'], 'name': r['name']} for r in steam_rows]
    api_total   = sum(len(v) for v in api_by_platform.values())

    if queue or api_by_platform:
        _bulk_date_state.update({
            'queue':               queue[1:] if queue else [],
            'current':             queue[0]  if queue else None,
            'done':                0,
            'failed':              0,
            'total':               len(queue) + api_total,
            'active':              True,
            'script_connected':    False,
            'results':             [],
            'api_threads_running': len(api_by_platform),
            'api_errors':          [],
        })
        if queue:
            log.info(f"Bulk date import started: {len(queue)} Steam games queued")
        for plat, plat_rows in api_by_platform.items():
            plugin  = _plugins.get(plat)
            appids  = [r['appid'] for r in plat_rows]
            log.info(f"Bulk date import: queuing {len(appids)} {plat} games for API fetch")
            threading.Thread(
                target=_run_api_date_fetch,
                args=(plugin, appids, appid_names),
                daemon=True,
            ).start()

    return jsonify({
        'status':           'ok',
        'first_appid':      queue[0]['appid'] if queue else None,
        'first_name':       queue[0]['name']  if queue else None,
        'total':            len(queue) + api_total,
        'date_import_urls': date_import_urls,
    })

@date_import_bp.route('/api/bulk-date-import/submit', methods=['POST', 'OPTIONS'])
def bulk_date_import_submit():
    if request.method == 'OPTIONS':
        return ('', 204)
    data  = request.json or {}
    appid = int(data.get('appid', 0))
    date  = data.get('date', '').strip()
    if not appid or not date:
        return jsonify({'status': 'error', 'message': 'Missing appid or date'}), 400
    from database import date_to_ts
    current = _bulk_date_state.get('current') or {}
    update_game_data(appid, date_added=date_to_ts(date))
    log.info(f"Bulk date import: saved {date} for AppID {appid}")
    _bulk_date_state['done'] += 1
    _bulk_date_state['results'].insert(0, {'appid': appid, 'name': current.get('name', ''), 'date': date})
    return _bulk_date_advance()

@date_import_bp.route('/api/bulk-date-import/skip', methods=['POST', 'OPTIONS'])
def bulk_date_import_skip():
    if request.method == 'OPTIONS':
        return ('', 204)
    data  = request.json or {}
    appid = int(data.get('appid', 0))
    current = _bulk_date_state.get('current') or {}
    log.info(f"Bulk date import: no date found for AppID {appid}")
    _bulk_date_state['failed'] += 1
    _bulk_date_state['results'].insert(0, {'appid': appid, 'name': current.get('name', ''), 'date': None})
    return _bulk_date_advance()

@date_import_bp.route('/api/bulk-date-import/ping', methods=['POST', 'OPTIONS'])
def bulk_date_import_ping():
    if request.method == 'OPTIONS':
        return ('', 204)
    _bulk_date_state['script_connected'] = True
    return jsonify({'status': 'ok'})

@date_import_bp.route('/api/bulk-date-import/status')
def bulk_date_import_status():
    s = _bulk_date_state
    return jsonify({
        'active': s['active'], 'done': s['done'], 'failed': s['failed'],
        'total': s['total'], 'current': s['current'],
        'script_connected': s['script_connected'],
        'results': s['results'][:50],
        'api_errors': s.get('api_errors', []),
    })

@date_import_bp.route('/api/bulk-date-import/cancel', methods=['POST'])
def bulk_date_import_cancel():
    with _bulk_date_lock:
        _bulk_date_state.update({'queue': [], 'active': False, 'current': None,
                                 'script_connected': False, 'api_threads_running': 0,
                                 'api_errors': []})
    log.info("Bulk date import cancelled")
    return jsonify({'status': 'ok'})
