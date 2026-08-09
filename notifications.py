"""Dev-to-user broadcast notifications: ad-hoc messages pushed between
releases, fetched once at startup from a JSON file in the PlayDate
GitHub repo. Distinct from updater.py (version-availability) and
config.py's What's New (per-release changelog)."""
import logging
import time

from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

notifications_bp = Blueprint('notifications', __name__)

_notif_cache = {}  # notifications (list), checked_at, error

_SEVERITY_RANK = {'critical': 0, 'warning': 1, 'info': 2}

_NOTIFICATIONS_URL = (
    'https://raw.githubusercontent.com/RobbyRatpoison/'
    'PlayDate-Library-Manager/main/notifications.json'
)


def _do_notif_check():
    """Fetch notifications.json and populate _notif_cache. Never raises --
    a missing file, network blip, or malformed JSON all degrade to an
    empty notification list rather than surfacing an error to the user."""
    try:
        import requests as _req
        resp = _req.get(_NOTIFICATIONS_URL, headers={'User-Agent': 'PlayDate-App'}, timeout=10)
        if resp.status_code == 404:
            _notif_cache.update({'notifications': [], 'checked_at': time.time(), 'error': None})
            return
        resp.raise_for_status()
        data = resp.json()
        notifications = data.get('notifications', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        if not isinstance(notifications, list):
            notifications = []
        _notif_cache.update({'notifications': notifications, 'checked_at': time.time(), 'error': None})
        log.info(f"Notification check: {len(notifications)} entries fetched")
    except Exception as e:
        # Broad on purpose: bad JSON, network failure, unexpected shape --
        # none of these should ever crash a background thread or block startup.
        _notif_cache.update({'notifications': [], 'checked_at': time.time(), 'error': str(e)})
        log.warning(f"Notification check failed: {e}")


def _startup_notification_check():
    time.sleep(5)
    from config import load_state
    if load_state().get('check_for_notifications', True):
        _do_notif_check()


@notifications_bp.route('/api/notifications/status')
def notifications_status():
    from config import __build__, load_config
    from updater import _parse_build_version

    notifications = _notif_cache.get('notifications', [])
    if not notifications:
        return jsonify({'show': False})

    config_data = load_config() or {}
    dismissed = set(config_data.get('dismissed_notifications', []))

    build_num, _ = _parse_build_version(__build__)
    candidates = []
    for n in notifications:
        if not isinstance(n, dict):
            continue
        nid = n.get('id')
        if not nid or nid in dismissed:
            continue
        min_v, max_v = n.get('min_version'), n.get('max_version')
        if min_v and build_num < _parse_build_version(min_v)[0]:
            continue
        if max_v and build_num > _parse_build_version(max_v)[0]:
            continue
        candidates.append(n)

    if not candidates:
        return jsonify({'show': False})

    candidates.sort(key=lambda n: _SEVERITY_RANK.get(n.get('severity'), 99))
    best = candidates[0]
    return jsonify({
        'show': True,
        'id': best.get('id'),
        'severity': best.get('severity', 'info'),
        'message': best.get('message', ''),
        'url': best.get('url'),
        'url_label': best.get('url_label'),
    })


@notifications_bp.route('/api/notifications/dismiss', methods=['POST'])
def dismiss_notification():
    from config import is_configured, load_config, _save_config_data
    if not is_configured():
        return jsonify({'status': 'ok'})
    nid = (request.get_json(silent=True) or {}).get('id')
    if not nid:
        return jsonify({'status': 'ok'})
    config_data = load_config() or {}
    dismissed = config_data.get('dismissed_notifications', [])
    if nid not in dismissed:
        dismissed.append(nid)
        config_data['dismissed_notifications'] = dismissed
        _save_config_data(config_data)
    return jsonify({'status': 'ok'})


# Debug/support only -- not wired to any UI element. Speeds up the
# edit-notifications.json-and-verify loop without waiting on the 5s
# startup delay or a restart.
@notifications_bp.route('/api/notifications/check', methods=['POST'])
def check_notifications():
    _do_notif_check()
    return jsonify({'status': 'ok', 'count': len(_notif_cache.get('notifications', []))})


@notifications_bp.route('/api/notifications/reset-cache', methods=['POST'])
def reset_notif_cache():
    _notif_cache.clear()
    return jsonify({'status': 'ok'})
