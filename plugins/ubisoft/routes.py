import logging

from flask import Blueprint, request, jsonify
from database import get_db, update_game_data

log = logging.getLogger(__name__)

bp = Blueprint('ubisoft', __name__, url_prefix='/api/ubisoft',
               template_folder='templates')


@bp.route('/status')
def ubi_status():
    from .ubisoft import is_connected, get_display_name
    if not is_connected():
        return jsonify({'connected': False, 'username': None})
    return jsonify({'connected': True, 'username': get_display_name()})


@bp.route('/auth-url')
def ubi_auth_url():
    from .ubisoft import get_auth_url
    return jsonify({'url': get_auth_url()})


@bp.route('/callback', methods=['POST'])
def ubi_callback():
    raw = ((request.json or {}).get('code') or '').strip()
    if not raw:
        return jsonify({'status': 'error', 'message': 'code is required'}), 400
    from .ubisoft import exchange_code
    ok, result = exchange_code(raw)
    if ok:
        return jsonify({'status': 'success', 'username': result})
    return jsonify({'status': 'error', 'message': result}), 400


@bp.route('/disconnect', methods=['POST'])
def ubi_disconnect():
    from .ubisoft import clear_ubi_tokens
    clear_ubi_tokens()
    return jsonify({'status': 'success'})


@bp.route('/sync', methods=['POST'])
def ubi_sync():
    from .ubisoft import start_library_sync
    result = start_library_sync()
    return jsonify(result)


@bp.route('/sync/status')
def ubi_sync_status():
    from .ubisoft import get_sync_state
    return jsonify(get_sync_state())


@bp.route('/sync/cancel', methods=['POST'])
def ubi_sync_cancel():
    from .ubisoft import cancel_library_sync
    cancel_library_sync()
    return jsonify({'status': 'ok'})


@bp.route('/scrape-single/<int:appid>', methods=['POST'])
def ubi_scrape_single(appid):
    from .ubisoft import scrape_single
    from database import ts_to_date

    meta = scrape_single(appid)
    if meta is None:
        return jsonify({'status': 'error', 'message': 'Metadata fetch failed'}), 502

    update_game_data(appid, **meta)

    data_out = dict(meta)
    if data_out.get('release_date'):
        data_out['release_date'] = ts_to_date(data_out['release_date']) or ''
    data_out.pop('_description', None)
    return jsonify({'status': 'success', 'data': data_out})
