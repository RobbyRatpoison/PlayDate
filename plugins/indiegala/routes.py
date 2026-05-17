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
