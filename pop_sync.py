import json
import logging
import os
import threading
from datetime import datetime, timezone

import requests
from flask import Blueprint, jsonify, request

from config import BASE_DIR, get_active_account
from database import get_db
from library import bulk_edit_games

log = logging.getLogger(__name__)

pop_bp = Blueprint('pop', __name__)

POP_API_BASE = "https://playorpaysg.com/api"
POP_FILTER_NAME = "Play or Pay"

_sync_lock = threading.Lock()


def _pop_sync_path(steam_id):
    return os.path.join(BASE_DIR, f'pop_sync_{steam_id}.json')


def _load_sync_state(steam_id):
    path = _pop_sync_path(steam_id)
    try:
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get('events'), dict):
                    return data
    except Exception:
        pass
    return {'events': {}}


def _save_sync_state(steam_id, data):
    path = _pop_sync_path(steam_id)
    tmp = path + '.tmp'
    with _sync_lock:
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)


def _fetch_events():
    r = requests.get(f"{POP_API_BASE}/events", timeout=15)
    r.raise_for_status()
    return r.json()['data']


def _fetch_event(uuid):
    r = requests.get(f"{POP_API_BASE}/events/{uuid}", timeout=15)
    r.raise_for_status()
    return r.json()['data']


def _active_events_for_today(events):
    today = datetime.now(timezone.utc).date()
    active = []
    for event in events:
        try:
            period = event['activePeriod']
            start = datetime.fromisoformat(period['startDate'].replace('Z', '+00:00')).date()
            end = datetime.fromisoformat(period['endDate'].replace('Z', '+00:00')).date()
        except Exception:
            continue
        if start <= today <= end:
            active.append(event)
    return active


def _sanitize_tag(name):
    return ' '.join((name or '').replace(',', '').split())


def _extract_steam_picks(event_detail, steam_id):
    """Return (appids, name_map) for the given steam_id's picks in this event."""
    participant = next((p for p in event_detail.get('participants', []) if p.get('user') == steam_id), None)
    if participant is None:
        return None, {}

    appids = []
    for picker in participant.get('pickers', []):
        for pick in picker.get('picks', []):
            game = pick.get('game') or ''
            if not game:
                continue
            store_id, _, local_id = game.partition(':')
            if store_id != '10' or not local_id:
                continue
            try:
                appids.append(int(local_id))
            except ValueError:
                continue

    name_map = {}
    for game in event_detail.get('games', []):
        if game.get('storeId') == 10:
            try:
                name_map[int(game['localId'])] = game.get('name', '')
            except (TypeError, ValueError):
                continue

    return appids, name_map


def _existing_appids(appids):
    if not appids:
        return set()
    db = get_db()
    placeholders = ','.join('?' * len(appids))
    rows = db.execute(f"SELECT appid FROM games WHERE appid IN ({placeholders})", appids).fetchall()
    db.close()
    return {row['appid'] for row in rows}


def _sync_pop_filter(tags):
    """Keep a single evergreen "Play or Pay" saved filter matching the union of
    every tag currently tracked in sync_state, rather than one filter per event
    cycle. tags=[] removes the filter (nothing currently tracked)."""
    from config import _state_lock, _load_state_unlocked, _write_state_atomic, _compact_shared_ids
    import uuid as _uuid
    with _state_lock:
        state = _load_state_unlocked()
        saved = state.setdefault('saved_filters', {})
        if not tags:
            saved.pop(POP_FILTER_NAME, None)
        else:
            existing = saved.get(POP_FILTER_NAME, {})
            existing_id = existing.get('id') if isinstance(existing, dict) else None
            saved[POP_FILTER_NAME] = {
                'id': existing_id or str(_uuid.uuid4()),
                'tree': {
                    'type': 'group',
                    'logic': 'AND',
                    'items': [
                        {'type': 'condition', 'column': 'groups', 'operator': 'LIKE', 'value': sorted(tags)},
                    ],
                },
            }
        _compact_shared_ids(state)
        _write_state_atomic(state)


def sync_pop_picks(confirm_cleanup=None):
    """confirm_cleanup: None = ask if a cleanup decision is needed (returns
    status 'confirm_cleanup' without changing anything); True = remove groups
    for cycles the user is no longer part of; False = leave old groups in
    place for this run (caller already asked and the user declined)."""
    account = get_active_account()
    steam_id = (account or {}).get('steam_id', '').strip()
    if not steam_id:
        return {'status': 'info', 'message': 'No active Steam account configured.'}

    events = _fetch_events()
    candidates = _active_events_for_today(events)
    if not candidates:
        return {'status': 'info', 'message': 'No active PoP event found.'}

    sync_state = _load_sync_state(steam_id)
    participating_events = []
    for event in candidates:
        detail = _fetch_event(event['uuid'])
        appids, name_map = _extract_steam_picks(detail, steam_id)
        if appids is None:
            continue
        participating_events.append((detail, appids, name_map))

    if not participating_events:
        return {'status': 'info', 'message': "You're not signed up for the current PoP cycle."}

    known_uuids = set(sync_state['events'].keys())
    current_uuids = {detail['uuid'] for detail, _, _ in participating_events}
    newly_seen = current_uuids - known_uuids
    stale_uuids = known_uuids - current_uuids

    if newly_seen and stale_uuids and confirm_cleanup is None:
        stale_tags = [sync_state['events'][u].get('tag') for u in stale_uuids if sync_state['events'][u].get('tag')]
        return {'status': 'confirm_cleanup', 'stale_tags': stale_tags}

    if confirm_cleanup and stale_uuids:
        for u in stale_uuids:
            old = sync_state['events'].pop(u, {})
            old_tag, old_appids = old.get('tag'), old.get('appids') or []
            if old_tag and old_appids:
                bulk_edit_games({'column': 'groups', 'mode': 'remove', 'value': old_tag, 'appids': old_appids})

    summaries = []
    for detail, appids, name_map in participating_events:
        uuid = detail['uuid']
        tag = _sanitize_tag(detail.get('name', 'PoP'))

        prior = sync_state['events'].get(uuid, {})
        prior_tag = prior.get('tag')
        prior_appids = set(prior.get('appids', []))

        new_appids_set = set(appids)
        if prior_tag == tag:
            stale = list(prior_appids - new_appids_set)
        else:
            stale = list(prior_appids)

        if stale:
            bulk_edit_games({'column': 'groups', 'mode': 'remove', 'value': prior_tag or tag, 'appids': stale})

        if appids:
            bulk_edit_games({'column': 'groups', 'mode': 'append', 'value': tag, 'appids': appids})

        sync_state['events'][uuid] = {'tag': tag, 'appids': appids}

        matched = _existing_appids(appids)
        missing_names = [name_map.get(a, str(a)) for a in appids if a not in matched]

        summaries.append({
            'event': detail.get('name', ''),
            'tag': tag,
            'total_picks': len(appids),
            'matched': len(matched),
            'missing': missing_names,
        })

    _save_sync_state(steam_id, sync_state)
    _sync_pop_filter({v['tag'] for v in sync_state['events'].values() if v.get('tag')})

    parts = []
    for s in summaries:
        part = f"{s['tag']}: tagged {s['matched']}/{s['total_picks']} game(s)"
        if s['missing']:
            part += f" ({len(s['missing'])} not in library: {', '.join(s['missing'])})"
        parts.append(part)

    return {'status': 'ok', 'message': '; '.join(parts), 'events': summaries}


@pop_bp.route('/api/pop-sync', methods=['POST'])
def pop_sync():
    try:
        data = request.get_json(silent=True) or {}
        confirm_cleanup = data.get('confirm_cleanup')
        result = sync_pop_picks(confirm_cleanup=confirm_cleanup)
        return jsonify(result)
    except Exception as e:
        log.error(f"pop-sync failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500
