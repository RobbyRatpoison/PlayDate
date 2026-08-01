from flask import Blueprint, jsonify, request

bp = Blueprint('indiegala', __name__, url_prefix='/api/indiegala',
               template_folder='templates')


@bp.route('/auth-url')
def auth_url():
    return jsonify({'url': 'https://www.indiegala.com/library'})


@bp.route('/connect', methods=['POST'])
def connect():
    from .indiegala import connect as _connect
    data   = request.get_json(silent=True) or {}
    cookie = (data.get('code') or data.get('cookie') or '').strip()
    if not cookie:
        return jsonify({'error': 'No cookie provided'}), 400
    ok, msg = _connect(cookie)
    if not ok:
        return jsonify({'error': msg}), 401
    return jsonify({'status': 'connected', 'username': msg})


@bp.route('/disconnect', methods=['POST'])
def disconnect():
    from .indiegala import disconnect as _disconnect
    _disconnect()
    return jsonify({'status': 'disconnected'})


@bp.route('/status')
def status():
    from .indiegala import is_connected, get_username
    connected = is_connected()
    return jsonify({
        'connected': connected,
        'username':  get_username() if connected else None,
    })


@bp.route('/sync', methods=['POST'])
def sync():
    from .indiegala import start_library_sync, is_connected
    if not is_connected():
        return jsonify({'error': 'Not connected'}), 401
    result = start_library_sync()
    if result.get('status') == 'already_running':
        return jsonify({'status': 'already_running'})
    return jsonify({'status': 'started'})


@bp.route('/sync-status')
def sync_status():
    from .indiegala import get_sync_state
    return jsonify(get_sync_state())


@bp.route('/games-dir', methods=['GET'])
def get_games_dir():
    from .indiegala import get_games_dir as _get
    return jsonify({'path': _get()})


@bp.route('/games-dir-info')
def games_dir_info():
    from .indiegala import get_games_dir as _get
    return jsonify({'text': _get()})


@bp.route('/games-dir', methods=['POST'])
def set_games_dir():
    from .indiegala import set_games_dir as _set
    from .watcher import start_indiegala_watcher, stop_indiegala_watcher
    data = request.get_json(silent=True) or {}
    path = (data.get('path') or '').strip()
    if not path:
        return jsonify({'error': 'No path provided'}), 400
    _set(path)
    stop_indiegala_watcher()
    start_indiegala_watcher(path)
    return jsonify({'status': 'ok', 'path': path})


@bp.route('/open-folder', methods=['POST'])
def open_folder():
    from .indiegala import get_games_dir as _get, _open_folder
    import os
    path = _get()
    os.makedirs(path, exist_ok=True)
    _open_folder(path)
    return jsonify({'status': 'ok'})


@bp.route('/scan', methods=['POST'])
def scan():
    from .indiegala import sync_indiegala_install_status
    try:
        sync_indiegala_install_status()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/scrape-single/<int:appid>', methods=['POST'])
def scrape_single(appid):
    from .indiegala import rescrape, is_connected, SessionExpired
    from database import update_game_data

    if not is_connected():
        return jsonify({'status': 'error', 'message': 'Not connected to IndieGala — connect it in Plugins settings'}), 502

    try:
        meta = rescrape(appid)
    except SessionExpired:
        return jsonify({'status': 'error', 'message': 'Session expired — please reconnect IndieGala in the Plugins settings.'}), 502

    if meta is None:
        return jsonify({'status': 'error', 'message': 'Could not find this game in your IndieGala library'}), 502

    update_game_data(appid, **meta)
    return jsonify({'status': 'success', 'data': meta})


@bp.route('/uninstall/<int:appid>', methods=['POST'])
def uninstall(appid):
    from .indiegala import uninstall_game
    ok, msg = uninstall_game(appid)
    if ok:
        return jsonify({'status': 'success', 'message': msg})
    return jsonify({'status': 'error', 'message': msg}), 500


@bp.route('/link-folder', methods=['POST'])
def link_folder():
    from .indiegala import link_folder as _link
    data   = request.get_json(silent=True) or {}
    appid  = data.get('appid')
    path   = (data.get('path') or '').strip()
    if not appid or not path:
        return jsonify({'error': 'appid and path required'}), 400
    ok, msg = _link(int(appid), path)
    if ok:
        return jsonify({'status': 'ok'})
    return jsonify({'error': msg}), 400
