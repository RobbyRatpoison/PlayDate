import logging
import re
import sqlite3
from flask import Blueprint, jsonify, render_template, request
from config import load_state, get_default_shelves, BUILTIN_FILTERS
from database import get_db

log = logging.getLogger(__name__)

index_bp = Blueprint('index', __name__)

# FILTER_QUERIES is now BUILTIN_FILTERS in config.py — aliased here for compatibility
FILTER_QUERIES = BUILTIN_FILTERS

SORT_COLUMNS = {
    "name":                "Alphabetical",
    "playtime_forever":    "Hours Played",
    "last_played":         "Recently Played",
    "release_date":        "Release Date",
    "date_added":          "Date Added",
    "review_percentage":   "Review Score",
    "weighted_percentage": "Weighted Score",
    "hltb_main":           "HLTB: Main Story",
    "hltb_extras":         "HLTB: Main + Extras",
    "hltb_completionist":  "HLTB: Completionist",
    "hltb_min":            "HLTB: Shortest",
    "hltb_max":            "HLTB: Longest",
    "achievement_percent":   "Achievement %",
    "achievement_remaining": "Achievements Remaining",
    "total_reviews":       "Total Reviews",
    "RANDOM()":            "Random",
}

from library import is_safe_sql, build_tree_sql, VIRTUAL_SORT_COLS


def achievement_bucket(unlocked, total):
    """Map an achievement unlock count to a quartile label for the achievement chart widget."""
    pct = (unlocked or 0) / total * 100
    if pct <= 25:
        return '0-25%'
    if pct <= 50:
        return '26-50%'
    if pct <= 75:
        return '51-75%'
    return '76-100%'


def _filter_tree_to_sql(tree):
    """Convert a saved filter tree to an inline SQL WHERE string (values escaped)."""
    if not tree:
        return '1=1'
    params = []
    sql = build_tree_sql(tree, params)
    # Inline params safely — only string values, single-quotes escaped
    for p in params:
        escaped = str(p).replace("'", "''")
        sql = sql.replace('?', f"'{escaped}'", 1)
    return sql or '1=1'


def _build_shelf_query(shelf, saved_filters, state):
    """Returns (where_clause, order_clause) or (None, None) for special widgets."""
    filter_key = shelf.get('filter_key') or shelf.get('preset', 'all_games')

    # Widget presets have no SQL
    if filter_key in ('clock', 'completion_pie', 'achievement_pie'):
        return None, None
    # Also handle legacy preset field pointing to a widget
    if shelf.get('preset') in ('clock', 'completion_pie', 'achievement_pie') and filter_key not in FILTER_QUERIES:
        return None, None

    # Resolve WHERE clause
    custom = (shelf.get('custom_sql') or '').strip()
    if custom:
        if not is_safe_sql(custom):
            return '1=0', 'name ASC'
        where = re.sub(r'\s*\bORDER\s+BY\s+.+$', '', custom, flags=re.IGNORECASE).strip()
        where = re.sub(r'(?i)^\s*WHERE\s+', '', where).strip()
    elif filter_key in FILTER_QUERIES:
        where = FILTER_QUERIES[filter_key]['where']
    elif filter_key in saved_filters:
        sf = saved_filters[filter_key]
        where = _filter_tree_to_sql(sf['tree'] if isinstance(sf, dict) and 'tree' in sf else sf)
    else:
        where = '1=1'

    # Same condition library.py's grid query applies -- shelves had no
    # equivalent at all, so "Hide duplicate entries" was only ever honored
    # on the Library page, not Home.
    if state.get('hide_duplicates', True):
        dup_cond = "(duplicate_of IS NULL OR duplicate_of = '')"
        where = dup_cond if where == '1=1' else f"({where}) AND {dup_cond}"

    # Platform filter — values are validated to prevent SQL injection
    shelf_hidden = [p for p in (shelf.get('hidden_platforms') or []) if re.match(r'^[a-z][a-z0-9_]*$', p or '')]
    if shelf_hidden:
        plat_conds = []
        if 'steam' in shelf_hidden:
            plat_conds.append("platform != 'steam'")
        non_steam = [p for p in shelf_hidden if p != 'steam']
        if non_steam:
            inlist = ','.join(f"'{p}'" for p in non_steam)
            plat_conds.append(f"platform NOT IN ({inlist})")
        plat_sql = ' AND '.join(plat_conds)
        where = plat_sql if where == '1=1' else f"({where}) AND ({plat_sql})"

    # Sort order
    sort_col = shelf.get('sort_col')
    sort_dir = shelf.get('sort_dir') or 'DESC'
    if sort_col and sort_col in SORT_COLUMNS:
        if sort_col == 'RANDOM()':
            order = 'RANDOM()'
        elif sort_col in VIRTUAL_SORT_COLS:
            expr = VIRTUAL_SORT_COLS[sort_col]
            order = f"({expr}) {sort_dir}"
        else:
            order = f"{sort_col} {sort_dir}"
    else:
        order = 'name ASC'

    return where, order


@index_bp.route('/')
def index():
    edit_mode = request.args.get('edit') == '1'
    state = load_state()
    db = get_db()
    db.row_factory = sqlite3.Row

    saved_filters = state.get('saved_filters', {})
    shelves_config = state.get('shelves') or get_default_shelves()
    visible_shelves = [s for s in shelves_config if s.get('visible', True)]

    # Fetch in dedup-priority order
    dedup_order = sorted(
        visible_shelves,
        key=lambda s: s.get('dedup_priority', 999) if s.get('dedup', True) else 9999
    )

    used_ids = set()
    shelf_games = {}

    for shelf in dedup_order:
        where, order = _build_shelf_query(shelf, saved_filters, state)
        if where is None:
            shelf_games[shelf['id']] = []
            continue

        limit = int(shelf.get('limit', 10))
        uses_dedup = shelf.get('dedup', True)
        try:
            rows = db.execute(
                f"SELECT * FROM games WHERE {where} ORDER BY {order}"
            ).fetchall()
        except Exception:
            shelf_games[shelf['id']] = []
            continue

        games = []
        for row in rows:
            game = dict(row)
            if uses_dedup and game['appid'] in used_ids:
                continue
            games.append(game)
            if uses_dedup:
                used_ids.add(game['appid'])
            if len(games) >= limit:
                break
        shelf_games[shelf['id']] = games

    completion_counts = {}
    try:
        rows = db.execute(
            "SELECT completion_status, COUNT(*) as cnt FROM games "
            "WHERE completion_status IS NOT NULL AND platform = 'steam' "
            "GROUP BY completion_status"
        ).fetchall()
        for row in rows:
            key = row['completion_status']
            if key is not None:
                completion_counts[str(key)] = row['cnt']
    except Exception:
        pass

    achievement_counts = {}
    try:
        rows = db.execute(
            "SELECT unlocked_achievements, total_achievements FROM games "
            "WHERE platform = 'steam' AND total_achievements > 0"
        ).fetchall()
        for row in rows:
            bucket = achievement_bucket(row['unlocked_achievements'], row['total_achievements'])
            achievement_counts[bucket] = achievement_counts.get(bucket, 0) + 1
    except Exception:
        pass

    from plugins import platform_labels as _platform_labels
    _plat_order = list(_platform_labels().keys())
    try:
        _plat_rows = db.execute(
            "SELECT DISTINCT platform as p FROM games ORDER BY p"
        ).fetchall()
        available_platforms = sorted(
            {r['p'] for r in _plat_rows},
            key=lambda p: _plat_order.index(p) if p in _plat_order else 99
        )
    except Exception:
        available_platforms = ['steam']

    db.close()

    # Restore display order and attach games
    ordered_shelves = [
        {**s, 'games': shelf_games.get(s['id'], [])}
        for s in visible_shelves
    ]

    # Group shelves into rows by split_group, preserving display order.
    # Members don't need to be consecutive — collect all with the same group key,
    # then emit the row at the position of the first member encountered.
    rows = []
    seen_groups = set()
    for s in ordered_shelves:
        group = s.get('split_group')
        if group:
            if group in seen_groups:
                continue  # already emitted as part of this group's row
            members = [m for m in ordered_shelves if m.get('split_group') == group]
            rows.append({'type': 'split', 'shelves': members, 'row_height': members[0]['row_height']})
            seen_groups.add(group)
        else:
            rows.append({'type': 'single', 'shelf': s})

    # Compute outline colors for all games on the page
    from library import _compute_outline_colors
    all_shelf_games = [g for games in shelf_games.values() for g in games]
    outlines_cfg = state.get('card_outlines', {})
    outline_colors = (
        _compute_outline_colors(all_shelf_games, state)
        if all_shelf_games and outlines_cfg.get('enabled', {}).get('home', True)
        else {}
    )

    return render_template(
        'index.html',
        state=state,
        shelves=ordered_shelves,
        rows=rows,
        all_shelves_config=shelves_config,
        filter_options=FILTER_QUERIES,
        saved_filters=saved_filters,
        sort_columns=SORT_COLUMNS,
        completion_counts=completion_counts,
        achievement_counts=achievement_counts,
        edit_mode=edit_mode,
        available_platforms=available_platforms,
        outline_colors=outline_colors,
    )


@index_bp.route('/api/shuffle-shelf/<shelf_id>')
def shuffle_shelf(shelf_id):
    try:
        state = load_state()
        shelves = state.get('shelves', [])
        shelf = next((s for s in shelves if s['id'] == shelf_id), None)
        if not shelf:
            return jsonify({'status': 'error', 'message': 'Shelf not found'}), 404

        saved_filters = state.get('saved_filters', {})
        where, _ = _build_shelf_query(shelf, saved_filters, state)
        if where is None:
            return jsonify({'status': 'error', 'message': 'Widget shelf'}), 400

        limit = shelf.get('limit', 10)
        db = get_db()
        rows = db.execute(
            f"SELECT appid, name, installed, completion_status, platform FROM games "
            f"WHERE {where} ORDER BY RANDOM() LIMIT ?",
            (limit,)
        ).fetchall()
        db.close()
        games = [{'appid': r[0], 'name': r[1], 'installed': r[2] or 0, 'completion_status': r[3] or '', 'platform': r[4] or 'steam'} for r in rows]
        from library import _compute_outline_colors
        _outlines_cfg = state.get('card_outlines', {})
        outline_map = (
            _compute_outline_colors(games, state)
            if _outlines_cfg.get('enabled', {}).get('home', True)
            else {}
        )
        for g in games:
            g['outline_color'] = outline_map.get(str(g['appid']))
        return jsonify({'status': 'success', 'games': games})
    except Exception as e:
        log.exception(f"shuffle_shelf error for {shelf_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@index_bp.route('/api/refill-shelf/<shelf_id>', methods=['POST'])
def refill_shelf(shelf_id):
    try:
        data = request.json or {}
        exclude_appids = [int(a) for a in data.get('exclude_appids', [])]

        state = load_state()
        shelves = state.get('shelves', [])
        shelf = next((s for s in shelves if s['id'] == shelf_id), None)
        if not shelf:
            return jsonify({'status': 'error', 'message': 'Shelf not found'}), 404

        saved_filters = state.get('saved_filters', {})
        where, order = _build_shelf_query(shelf, saved_filters, state)
        if where is None:
            return jsonify({'status': 'success', 'games': []})

        limit = int(shelf.get('limit', 10))
        db = get_db()
        if exclude_appids:
            placeholders = ','.join('?' * len(exclude_appids))
            rows = db.execute(
                f"SELECT appid, name, installed, completion_status, platform FROM games "
                f"WHERE ({where}) AND appid NOT IN ({placeholders}) ORDER BY {order} LIMIT ?",
                (*exclude_appids, limit)
            ).fetchall()
        else:
            rows = db.execute(
                f"SELECT appid, name, installed, completion_status, platform FROM games "
                f"WHERE {where} ORDER BY {order} LIMIT ?",
                (limit,)
            ).fetchall()
        db.close()
        games = [{'appid': r[0], 'name': r[1], 'installed': r[2] or 0, 'completion_status': r[3] or '', 'platform': r[4] or 'steam'} for r in rows]
        return jsonify({'status': 'success', 'games': games})
    except Exception as e:
        log.exception(f"refill_shelf error for {shelf_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@index_bp.route('/api/shelves', methods=['POST'])
def save_shelves():
    from config import save_state
    try:
        shelves = request.json.get('shelves')
        if not isinstance(shelves, list):
            return jsonify({"status": "error", "message": "Invalid shelves data."}), 400
        save_state({"shelves": shelves})
        return jsonify({"status": "success"})
    except Exception as e:
        log.exception("Failed to save shelves")
        return jsonify({"status": "error", "message": str(e)}), 500

@index_bp.route('/api/shelves/reset', methods=['POST'])
def reset_shelves():
    from config import save_state, get_default_shelves as _get_default_shelves
    try:
        save_state({"shelves": _get_default_shelves()})
        return jsonify({"status": "success"})
    except Exception as e:
        log.exception("Failed to reset shelves")
        return jsonify({"status": "error", "message": str(e)}), 500
