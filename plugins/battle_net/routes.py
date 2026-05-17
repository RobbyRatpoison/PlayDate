import logging

from flask import Blueprint, request, jsonify
from database import update_game_data

log = logging.getLogger(__name__)

bp = Blueprint('battle_net', __name__, url_prefix='/api/battle_net',
               template_folder='templates')


@bp.route('/status')
def bnet_status():
    from .battle_net import is_connected, get_display_name, credentials_configured
    return jsonify({
        'connected':              is_connected(),
        'username':               get_display_name(),
        'credentials_configured': credentials_configured(),
    })


@bp.route('/credentials-status')
def bnet_credentials_status():
    from .battle_net import credentials_configured, load_credentials
    if credentials_configured():
        creds = load_credentials()
        return jsonify({'text': f'Client ID: {creds["client_id"]}', 'color': 'var(--accent-positive, #5c7e10)'})
    return jsonify({'text': 'No credentials configured', 'color': 'var(--text-secondary)'})


@bp.route('/save-credentials', methods=['POST'])
def bnet_save_credentials():
    data          = request.json or {}
    client_id     = (data.get('client_id') or '').strip()
    client_secret = (data.get('client_secret') or '').strip()
    if not client_id:
        return jsonify({'status': 'error', 'message': 'client_id is required'}), 400
    from .battle_net import save_credentials
    save_credentials(client_id, client_secret)
    return jsonify({'status': 'success'})


@bp.route('/auth-url')
def bnet_auth_url():
    from .battle_net import get_auth_url, credentials_configured
    if not credentials_configured():
        return jsonify({'error': 'credentials not configured'}), 400
    url = get_auth_url()
    return jsonify({'url': url})


@bp.route('/callback', methods=['POST'])
def bnet_callback():
    raw = ((request.json or {}).get('code') or '').strip()
    if not raw:
        return jsonify({'status': 'error', 'message': 'code is required'}), 400
    from .battle_net import exchange_code
    ok, result = exchange_code(raw)
    if ok:
        return jsonify({'status': 'success', 'username': result})
    return jsonify({'status': 'error', 'message': result}), 400


@bp.route('/disconnect', methods=['POST'])
def bnet_disconnect():
    from .battle_net import clear_bnet_tokens
    clear_bnet_tokens()
    return jsonify({'status': 'success'})


@bp.route('/sync', methods=['POST'])
def bnet_sync():
    from .battle_net import start_library_sync
    result = start_library_sync()
    return jsonify(result)


@bp.route('/sync/status')
def bnet_sync_status():
    from .battle_net import get_sync_state
    return jsonify(get_sync_state())


@bp.route('/sync/cancel', methods=['POST'])
def bnet_sync_cancel():
    from .battle_net import cancel_library_sync
    cancel_library_sync()
    return jsonify({'status': 'ok'})


@bp.route('/scrape-single/<int:appid>', methods=['POST'])
def bnet_scrape_single(appid):
    from .battle_net import scrape_single
    meta = scrape_single(appid)
    if meta is None:
        return jsonify({'status': 'error', 'message': 'Game not found'}), 404
    update_game_data(appid, **meta)
    return jsonify({'status': 'success', 'data': meta})
