from flask import Blueprint, jsonify, request

bp = Blueprint('amazon_games', __name__, url_prefix='/api/amazon_games',
               template_folder='templates')


@bp.route('/auth-url')
def auth_url():
    # Start at the gaming portal — Amazon redirects to signin if not logged in,
    # then back to gaming.amazon.com after a successful login.
    return jsonify({'url': 'https://gaming.amazon.com/home'})


@bp.route('/connect', methods=['POST'])
def connect():
    from .amazon_games import connect as _connect
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
    from .amazon_games import disconnect as _disconnect
    _disconnect()
    return jsonify({'status': 'disconnected'})


@bp.route('/status')
def status():
    from .amazon_games import is_connected, get_username, nile_detected
    connected = is_connected()
    return jsonify({
        'connected': connected,
        'username':  get_username() if connected else None,
        'nile':      nile_detected(),
    })


@bp.route('/sync', methods=['POST'])
def sync():
    from .amazon_games import start_library_sync, is_connected
    if not is_connected():
        return jsonify({'error': 'Not connected'}), 401
    data   = request.get_json(silent=True) or {}
    source = data.get('source', 'auto')
    result = start_library_sync(source=source)
    if result.get('status') == 'already_running':
        return jsonify({'status': 'already_running'})
    return jsonify({'status': 'started'})


@bp.route('/sync-status')
def sync_status():
    from .amazon_games import get_sync_state
    return jsonify(get_sync_state())
