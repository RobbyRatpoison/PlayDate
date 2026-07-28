import logging
import os

from flask import Blueprint, jsonify, request
from database import get_db, update_game_data

log = logging.getLogger(__name__)

bp = Blueprint('itch_io', __name__, url_prefix='/api/itch_io',
               template_folder='templates')


@bp.route('/status')
def status():
    from .itch_io import is_connected, get_username
    return jsonify({'connected': is_connected(), 'username': get_username() or ''})


@bp.route('/auth-url')
def auth_url():
    return jsonify({'url': 'https://itch.io/login?return_to=%2Fuser%2Fsettings%2Fapi-keys'})


@bp.route('/connect', methods=['POST'])
def connect():
    data    = request.get_json(silent=True) or {}
    api_key = (data.get('code') or '').strip()
    if not api_key:
        return jsonify({'status': 'error', 'message': 'No API key provided'}), 400
    from .itch_io import verify_and_connect
    try:
        username = verify_and_connect(api_key)
        return jsonify({'status': 'success', 'username': username})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400


@bp.route('/login', methods=['POST'])
def login():
    data     = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'status': 'error', 'message': 'Username and password required'}), 400
    from .itch_io import login_with_credentials
    try:
        uname = login_with_credentials(username, password)
        return jsonify({'status': 'success', 'username': uname})
    except ValueError as e:
        msg = str(e)
        if msg.startswith('TOTP_REQUIRED|'):
            token = msg.split('|', 1)[1]
            return jsonify({'status': 'totp_required', 'token': token})
        return jsonify({'status': 'error', 'message': msg}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400


@bp.route('/totp', methods=['POST'])
def totp():
    data  = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    code  = (data.get('code') or '').strip()
    if not token or not code:
        return jsonify({'status': 'error', 'message': 'Token and code required'}), 400
    from .itch_io import verify_totp
    try:
        uname = verify_totp(token, code)
        return jsonify({'status': 'success', 'username': uname})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400


@bp.route('/disconnect', methods=['POST'])
def disconnect():
    from .itch_io import disconnect as _disconnect
    _disconnect()
    return jsonify({'status': 'success'})


@bp.route('/sync', methods=['POST'])
def sync():
    from .itch_io import start_library_sync
    return jsonify(start_library_sync())


@bp.route('/sync/status')
def sync_status():
    from .itch_io import get_sync_state
    return jsonify(get_sync_state())


@bp.route('/sync/cancel', methods=['POST'])
def sync_cancel():
    from .itch_io import cancel_library_sync
    cancel_library_sync()
    return jsonify({'status': 'ok'})


@bp.route('/install/<int:appid>', methods=['POST'])
def install(appid):
    from .itch_io import start_install
    return jsonify(start_install(appid))


@bp.route('/install-status/<int:appid>')
def install_status(appid):
    from .itch_io import get_install_state
    return jsonify(get_install_state(appid))


@bp.route('/install/<int:appid>/cancel', methods=['POST'])
def install_cancel(appid):
    from .itch_io import cancel_install
    cancel_install(appid)
    return jsonify({'status': 'ok'})


@bp.route('/uninstall/<int:appid>', methods=['POST'])
def uninstall(appid):
    import shutil
    from database import update_game_data
    db  = get_db()
    row = db.execute(
        'SELECT name, install_path FROM games WHERE appid=? AND platform=?',
        (appid, 'itch_io')
    ).fetchone()
    db.close()
    if not row:
        return jsonify({'status': 'error', 'message': 'Game not found'}), 404
    install_path = row['install_path']
    if install_path and os.path.isdir(install_path):
        try:
            shutil.rmtree(install_path)
            log.info(f'itch.io uninstall: deleted {install_path}')
        except Exception as e:
            log.error(f'itch.io uninstall: delete failed — {e}')
    update_game_data(appid, installed=0, install_path=None, platform_executable=None)
    log.info(f'itch.io uninstall: {row["name"]!r} uninstalled')
    return jsonify({'status': 'success'})


@bp.route('/scrape-single/<int:appid>', methods=['POST'])
def scrape_single(appid):
    from .itch_io import rescrape_game
    meta = rescrape_game(appid)
    if not meta:
        return jsonify({'status': 'error', 'message': 'Failed to fetch metadata'}), 400
    update_game_data(appid, **meta)
    return jsonify({'status': 'success'})
