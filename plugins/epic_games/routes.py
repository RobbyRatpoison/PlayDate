import logging

from flask import Blueprint, request, jsonify
from database import get_db, update_game_data

log = logging.getLogger(__name__)

bp = Blueprint('epic_games', __name__, url_prefix='/api/epic_games',
               template_folder='templates')


@bp.route('/status')
def epic_status():
    from .epic import is_connected, get_display_name
    if not is_connected():
        return jsonify({'connected': False, 'username': None})
    return jsonify({'connected': True, 'username': get_display_name()})


@bp.route('/auth-url')
def epic_auth_url():
    from .epic import get_auth_url
    return jsonify({'url': get_auth_url()})


@bp.route('/callback', methods=['POST'])
def epic_callback():
    raw = ((request.json or {}).get('code') or '').strip()
    if not raw:
        return jsonify({'status': 'error', 'message': 'code is required'}), 400
    from .epic import exchange_code
    ok, result = exchange_code(raw)
    if ok:
        return jsonify({'status': 'success', 'username': result})
    return jsonify({'status': 'error', 'message': result}), 400


@bp.route('/disconnect', methods=['POST'])
def epic_disconnect():
    from .epic import clear_epic_tokens
    clear_epic_tokens()
    return jsonify({'status': 'success'})


@bp.route('/sync', methods=['POST'])
def epic_sync():
    from .epic import start_library_sync
    result = start_library_sync()
    return jsonify(result)


@bp.route('/sync/status')
def epic_sync_status():
    from .epic import get_sync_state
    return jsonify(get_sync_state())


@bp.route('/sync/cancel', methods=['POST'])
def epic_sync_cancel():
    from .epic import cancel_library_sync
    cancel_library_sync()
    return jsonify({'status': 'ok'})


@bp.route('/sync-metadata', methods=['POST'])
def epic_sync_metadata():
    from .epic import start_meta_sync
    force  = (request.json or {}).get('force', False)
    result = start_meta_sync(force=force)
    return jsonify(result)


@bp.route('/sync-metadata/status')
def epic_sync_metadata_status():
    from .epic import get_meta_sync_state
    return jsonify(get_meta_sync_state())


@bp.route('/scrape-single/<int:appid>', methods=['POST'])
def epic_scrape_single(appid):
    from .epic import scrape_single
    from database import ts_to_date

    meta = scrape_single(appid)
    if meta is None:
        return jsonify({'status': 'error', 'message': 'Metadata fetch failed'}), 502

    update_game_data(appid, **meta)

    data_out = dict(meta)
    if data_out.get('release_date'):
        data_out['release_date'] = ts_to_date(data_out['release_date']) or ''
    return jsonify({'status': 'success', 'data': data_out})


@bp.route('/uninstall/<int:appid>', methods=['POST'])
def epic_uninstall(appid):
    db  = get_db()
    row = db.execute(
        "SELECT name, platform_appname, platform_slug FROM games "
        "WHERE appid = ? AND platform = 'epic_games'", (appid,)
    ).fetchone()
    db.close()

    if not row:
        return jsonify({'status': 'error', 'message': 'Epic game not found'})

    platform_appname = (row['platform_appname'] or row['platform_slug'] or '').strip()

    ok, message = False, 'No app name — cannot locate game files'
    if platform_appname:
        from .watcher import uninstall_game_files
        ok, message = uninstall_game_files(platform_appname)

    # Mark as uninstalled in PlayDate regardless of whether file deletion succeeded
    db2 = get_db()
    db2.execute("UPDATE games SET installed = 0 WHERE appid = ?", (appid,))
    db2.commit()
    db2.close()

    log.info(f"Epic uninstall: {row['name']!r} (appid {appid}): {message}")
    return jsonify({'status': 'success' if ok else 'warning', 'message': message})


@bp.route('/import-dates', methods=['POST'])
def epic_import_dates():
    from .epic import import_purchase_dates
    result = import_purchase_dates()
    if 'error' in result:
        return jsonify({'status': 'error', 'message': result['error']}), 400
    return jsonify({'status': 'success', 'updated': result['updated'], 'not_found': result['not_found']})
