import logging
import os
import platform
import shutil
from urllib.parse import urlparse, parse_qs

from flask import Blueprint, request, jsonify
from database import get_db, update_game_data

log = logging.getLogger(__name__)

bp = Blueprint('gog', __name__, url_prefix='/api/gog',
               template_folder='templates',
               static_folder='static',
               static_url_path='/plugins/gog/static')


@bp.route('/status')
def gog_status():
    from .gog import is_connected, get_username
    if not is_connected():
        return jsonify({'connected': False, 'username': None})
    username = get_username()
    return jsonify({'connected': True, 'username': username})


@bp.route('/auth-url')
def gog_auth_url():
    from .gog import get_auth_url
    return jsonify({'url': get_auth_url()})


@bp.route('/callback', methods=['POST'])
def gog_callback():
    raw = ((request.json or {}).get('code') or '').strip()
    if not raw:
        return jsonify({'status': 'error', 'message': 'code is required'}), 400
    if raw.startswith('http'):
        qs   = parse_qs(urlparse(raw).query)
        code = (qs.get('code') or [''])[0].strip()
        if not code:
            return jsonify({'status': 'error', 'message': 'No code= found in that URL'}), 400
    else:
        code = raw
    from .gog import exchange_code
    ok, result = exchange_code(code)
    if ok:
        return jsonify({'status': 'success', 'username': result})
    return jsonify({'status': 'error', 'message': result}), 400


@bp.route('/disconnect', methods=['POST'])
def gog_disconnect():
    from .gog import clear_gog_tokens
    clear_gog_tokens()
    return jsonify({'status': 'success'})


@bp.route('/sync', methods=['POST'])
def gog_sync():
    from .gog import start_library_sync
    result = start_library_sync()
    return jsonify(result)


@bp.route('/sync/status')
def gog_sync_status():
    from .gog import get_sync_state
    return jsonify(get_sync_state())


@bp.route('/sync/cancel', methods=['POST'])
def gog_sync_cancel():
    from .gog import cancel_library_sync
    cancel_library_sync()
    return jsonify({'status': 'ok'})


@bp.route('/sync-metadata', methods=['POST'])
def gog_sync_metadata():
    from .gog import start_meta_sync
    force  = (request.json or {}).get('force', False)
    result = start_meta_sync(force=force)
    return jsonify(result)


@bp.route('/sync-metadata/status')
def gog_sync_metadata_status():
    from .gog import get_meta_sync_state
    return jsonify(get_meta_sync_state())


@bp.route('/bulk-date-import', methods=['POST'])
def gog_bulk_date_import():
    dates = (request.json or {}).get('dates', {})
    if not dates:
        return jsonify({'status': 'error', 'message': 'No dates provided'}), 400

    db   = get_db()
    rows = db.execute(
        "SELECT appid, platform_id FROM games WHERE platform = 'gog'"
    ).fetchall()
    db.close()

    gog_map   = {row['platform_id']: row['appid'] for row in rows}
    updated   = 0
    not_found = 0
    for gog_id, ts in dates.items():
        appid = gog_map.get(str(gog_id))
        if appid is None:
            not_found += 1
            continue
        try:
            update_game_data(appid, date_added=int(ts))
            updated += 1
        except Exception as e:
            log.warning(f'GOG bulk-date-import: failed for gog_id={gog_id}: {e}')

    return jsonify({'status': 'success', 'updated': updated, 'not_found': not_found})


@bp.route('/scrape-single/<int:appid>', methods=['POST'])
def gog_scrape_single(appid):
    from .gog import fetch_gog_metadata, fetch_gog_achievements, get_valid_session, get_galaxy_user_id
    from database import ts_to_date
    from datetime import date

    db  = get_db()
    row = db.execute(
        "SELECT platform_id FROM games WHERE appid = ? AND platform = 'gog'", (appid,)
    ).fetchone()
    db.close()
    if not row:
        return jsonify({'status': 'error', 'message': 'GOG game not found'}), 404

    gog_id = row['platform_id']
    meta   = fetch_gog_metadata(gog_id)
    if meta is None:
        return jsonify({'status': 'error', 'message': 'Metadata fetch failed'}), 502

    meta.pop('_category', None)
    today                = date.today().isoformat()
    meta['meta_fetched'] = today

    session        = get_valid_session()
    galaxy_user_id = get_galaxy_user_id()
    if session and galaxy_user_id:
        ach = fetch_gog_achievements(gog_id, galaxy_user_id, session)
        if ach is not None:
            meta.update(ach)
            meta['cheevos_fetched'] = today

    update_game_data(appid, **meta)

    data_out = dict(meta)
    if data_out.get('release_date'):
        data_out['release_date'] = ts_to_date(data_out['release_date']) or ''
    return jsonify({'status': 'success', 'data': data_out})


@bp.route('/install/<int:appid>', methods=['POST'])
def gog_install(appid):
    from .gog import start_install
    os_pref = (request.json or {}).get('os', 'auto')
    result  = start_install(appid, os_pref=os_pref)
    return jsonify(result)


@bp.route('/install-status/<int:appid>')
def gog_install_status(appid):
    from .gog import get_install_state
    return jsonify(get_install_state(appid))


@bp.route('/active-install')
def gog_active_install():
    from .gog import get_active_install
    return jsonify(get_active_install())


@bp.route('/install/<int:appid>/cancel', methods=['POST'])
def gog_install_cancel(appid):
    from .gog import cancel_install
    cancel_install(appid)
    return jsonify({'status': 'ok'})


@bp.route('/uninstall/<int:appid>', methods=['POST'])
def gog_uninstall(appid):
    db  = get_db()
    row = db.execute(
        'SELECT name, install_path FROM games WHERE appid = ? AND platform = ?',
        (appid, 'gog')
    ).fetchone()
    db.close()

    if not row:
        return jsonify({'status': 'error', 'message': 'GOG game not found'})

    game_name    = row['name']
    install_path = row['install_path']

    install_path = os.path.realpath(install_path) if install_path else None
    if install_path and os.path.isdir(install_path):
        try:
            shutil.rmtree(install_path)
            log.info(f'GOG uninstall: deleted {install_path}')
        except Exception as e:
            log.error(f'GOG uninstall: delete failed for {install_path} — {e}')
            return jsonify({'status': 'error', 'message': f'Failed to delete game files: {e}'})

    update_game_data(
        appid,
        installed           = 0,
        install_path        = None,
        platform_executable = None,
        runner_path         = None,
        wine_prefix         = None,
    )

    log.info(f'GOG uninstall: {game_name!r} uninstalled')
    return jsonify({'status': 'success'})


@bp.route('/proton-versions')
def gog_proton_versions():
    try:
        from runners.proton import find_proton_versions
        return jsonify({
            'status':   'ok',
            'platform': platform.system(),
            'versions': find_proton_versions(),
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/proton-info')
def gog_proton_info():
    try:
        from runners.proton import find_proton_versions
        if platform.system() == 'Windows':
            return jsonify({'text': 'Windows games run natively', 'color': ''})
        versions = find_proton_versions()
        if versions:
            return jsonify({'text': f'Runner: {versions[0]["name"]}', 'color': ''})
        return jsonify({'text': 'No Proton found — Windows games will not run', 'color': 'var(--text-danger)'})
    except Exception:
        return jsonify({'text': '', 'color': ''})


