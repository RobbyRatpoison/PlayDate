from flask import Blueprint, jsonify, request

bp = Blueprint('humble', __name__, url_prefix='/api/humble',
               template_folder='templates')


@bp.route('/auth-url')
def auth_url():
    return jsonify({'url': 'https://www.humblebundle.com/home/library'})


@bp.route('/connect', methods=['POST'])
def connect():
    from .humble import connect as _connect
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
    from .humble import disconnect as _disconnect
    _disconnect()
    return jsonify({'status': 'disconnected'})


@bp.route('/status')
def status():
    from .humble import is_connected, get_username
    connected = is_connected()
    return jsonify({
        'connected': connected,
        'username':  get_username() if connected else None,
    })


@bp.route('/sync', methods=['POST'])
def sync():
    from .humble import start_library_sync, is_connected
    if not is_connected():
        return jsonify({'error': 'Not connected'}), 401
    result = start_library_sync()
    if result.get('status') == 'already_running':
        return jsonify({'status': 'already_running'})
    return jsonify({'status': 'started'})


@bp.route('/sync-status')
def sync_status():
    from .humble import get_sync_state
    return jsonify(get_sync_state())


@bp.route('/download-status/<int:appid>')
def download_status(appid):
    from .humble import get_download_state
    return jsonify(get_download_state(appid))


@bp.route('/uninstall/<int:appid>', methods=['POST'])
def uninstall(appid):
    from .humble import uninstall_game
    ok, msg = uninstall_game(appid)
    if ok:
        return jsonify({'status': 'success', 'message': msg})
    return jsonify({'status': 'error', 'message': msg}), 500


@bp.route('/set-test-limit', methods=['POST'])
def set_test_limit():
    from .humble import _load_cache, _save_cache
    data  = request.get_json(silent=True) or {}
    limit = data.get('limit')
    cache = _load_cache()
    if limit:
        cache['test_limit'] = int(limit)
    else:
        cache.pop('test_limit', None)
    _save_cache(cache)
    return jsonify({'status': 'ok', 'test_limit': cache.get('test_limit')})
