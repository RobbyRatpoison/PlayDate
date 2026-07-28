"""HowLongToBeat matching/lookup routes. See CLAUDE.md's HLTB Integration section
for the hltb_fetched state machine; the actual scraping lives in scrapers.py."""
import logging

from flask import Blueprint, jsonify, request

from database import get_db, update_game_data

log = logging.getLogger(__name__)

hltb_bp = Blueprint('hltb', __name__)


def _propagate_hltb(canonical_appid, hltb_data, db):
    """Copy confirmed HLTB data to all games in the same duplicate group."""
    duplicates = db.execute(
        "SELECT appid FROM games WHERE duplicate_of = ? AND appid != ?",
        (str(canonical_appid), canonical_appid)
    ).fetchall()
    for row in duplicates:
        update_game_data(row['appid'], **hltb_data)


@hltb_bp.route('/api/hltb/matches', methods=['GET'])
def hltb_matches():
    db   = get_db()
    rows = db.execute("""
        SELECT appid, name, hltb_id, hltb_matched_name, hltb_match_score,
               hltb_main, hltb_extras, hltb_completionist, hltb_fetched
        FROM games
        WHERE hltb_id IS NOT NULL
        ORDER BY name COLLATE NOCASE
    """).fetchall()
    no_match_rows = db.execute(
        "SELECT appid, name FROM games WHERE hltb_fetched = 'no_match' ORDER BY name COLLATE NOCASE"
    ).fetchall()
    unfetched = db.execute(
        "SELECT COUNT(*) FROM games WHERE hltb_fetched = '0' OR hltb_fetched IS NULL"
    ).fetchone()[0]
    db.close()
    return jsonify({
        'matches':        [dict(r) for r in rows],
        'no_match_games': [dict(r) for r in no_match_rows],
        'unfetched_count': unfetched,
    })

@hltb_bp.route('/api/hltb/<int:appid>/search', methods=['GET'])
def hltb_search(appid):
    from scrapers import search_hltb_results
    db  = get_db()
    row = db.execute("SELECT name FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    if not row:
        return jsonify({'status': 'error', 'message': 'Game not found'}), 404
    name = request.args.get('q', '').strip() or row['name']
    results = search_hltb_results(name)
    return jsonify({'status': 'success', 'results': results})

@hltb_bp.route('/api/hltb/<int:appid>/select', methods=['POST'])
def select_hltb(appid):
    data     = request.json or {}
    hltb_id  = data.get('hltb_id')
    if not hltb_id:
        return jsonify({'status': 'error', 'message': 'hltb_id required'}), 400
    from scrapers import fetch_hltb_by_id
    from datetime import datetime
    db  = get_db()
    row = db.execute("SELECT name FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    if not row:
        return jsonify({'status': 'error', 'message': 'Game not found'}), 404
    today  = datetime.now().strftime('%Y-%m-%d')
    result = fetch_hltb_by_id(row['name'], hltb_id)
    if result is None:
        return jsonify({'status': 'error', 'message': 'Could not reach HLTB'}), 500
    times_available = result.pop('times_available', True)
    score = data.get('hltb_match_score')
    if times_available:
        update_game_data(appid, hltb_fetched=today, hltb_id=hltb_id,
                         hltb_match_score=score, **result)
        return jsonify({'status': 'success', 'times_available': True,
                        'data': {**result, 'hltb_id': hltb_id,
                                 'hltb_match_score': score, 'hltb_fetched': today}})
    else:
        # ID exists in HLTB DB but times couldn't be retrieved — don't confirm
        return jsonify({'status': 'error', 'message': 'Could not fetch times for this ID'}), 500

@hltb_bp.route('/api/hltb/<int:appid>', methods=['POST'])
def rescrape_hltb(appid):
    from scrapers import fetch_hltb_data
    from config import load_state
    db   = get_db()
    row  = db.execute("SELECT name FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    if not row:
        return jsonify({'status': 'error', 'message': 'Game not found'}), 404
    threshold = load_state().get('hltb_match_threshold', 75)
    info = fetch_hltb_data(row['name'], threshold=threshold)
    if info:
        update_game_data(appid, **info)
    else:
        update_game_data(appid, hltb_fetched='no_match', hltb_id=None,
                         hltb_main=None, hltb_extras=None,
                         hltb_completionist=None, hltb_match_score=None)
    return jsonify({'status': 'success', 'data': info})

@hltb_bp.route('/api/hltb/<int:appid>/confirm', methods=['POST'])
def confirm_hltb(appid):
    from scrapers import fetch_hltb_by_id
    from datetime import datetime
    db  = get_db()
    row = db.execute("SELECT name, hltb_id FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    if not row:
        return jsonify({'status': 'error', 'message': 'Game not found'}), 404
    today  = datetime.now().strftime('%Y-%m-%d')
    result = fetch_hltb_by_id(row['name'], row['hltb_id']) if row['hltb_id'] else None
    if result is None:
        return jsonify({'status': 'error', 'message': 'No HLTB ID stored'}), 400
    times_available = result.pop('times_available', True)
    if times_available:
        hltb_data = {**result, 'hltb_fetched': today}
        update_game_data(appid, **hltb_data)
        db2 = get_db()
        canonical_appid = db2.execute(
            "SELECT COALESCE(duplicate_of, appid) FROM games WHERE appid=?", (appid,)
        ).fetchone()[0]
        _propagate_hltb(canonical_appid, hltb_data, db2)
        db2.close()
        return jsonify({'status': 'success', 'data': hltb_data})
    else:
        # ID lookup failed — clear to no_match so the game surfaces in the review tab
        cleared = {'hltb_fetched': 'no_match', 'hltb_id': None,
                   'hltb_matched_name': None, 'hltb_match_score': None,
                   'hltb_main': None, 'hltb_extras': None, 'hltb_completionist': None}
        update_game_data(appid, **cleared)
        return jsonify({'status': 'success', 'data': cleared})

@hltb_bp.route('/api/hltb/<int:appid>', methods=['DELETE'])
def delete_hltb(appid):
    update_game_data(appid, hltb_fetched='0', hltb_id=None, hltb_main=None,
                     hltb_extras=None, hltb_completionist=None, hltb_match_score=None)
    return jsonify({'status': 'success'})
