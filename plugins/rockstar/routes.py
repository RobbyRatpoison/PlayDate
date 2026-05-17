from flask import Blueprint, jsonify, request

bp = Blueprint('rockstar', __name__, url_prefix='/api/rockstar',
               template_folder='templates')


@bp.route('/auth-url')
def auth_url():
    return jsonify({'url': 'https://www.rockstargames.com/signin'})


@bp.route('/connect', methods=['POST'])
def connect():
    from .rockstar import connect as _connect
    data  = request.get_json(silent=True) or {}
    token = (data.get('code') or data.get('token') or '').strip()
    if not token:
        return jsonify({'error': 'No token provided'}), 400
    ok, msg = _connect(token)
    if not ok:
        return jsonify({'error': msg}), 401
    return jsonify({'status': 'connected', 'username': msg})


@bp.route('/disconnect', methods=['POST'])
def disconnect():
    from .rockstar import disconnect as _disconnect
    _disconnect()
    return jsonify({'status': 'disconnected'})


@bp.route('/status')
def status():
    from .rockstar import is_connected, get_username
    connected = is_connected()
    return jsonify({
        'connected': connected,
        'username':  get_username() if connected else None,
    })


@bp.route('/sync', methods=['POST'])
def sync():
    from .rockstar import start_library_sync, is_connected
    if not is_connected():
        return jsonify({'error': 'Not connected'}), 401
    result = start_library_sync()
    if result.get('status') == 'already_running':
        return jsonify({'status': 'already_running'})
    return jsonify({'status': 'started'})


@bp.route('/sync-status')
def sync_status():
    from .rockstar import get_sync_state
    return jsonify(get_sync_state())
