import re
import sqlite3
from flask import Blueprint, render_template, request
from config import load_state, get_default_shelves, BUILTIN_FILTERS
from database import get_db

index_bp = Blueprint('index', __name__)

# FILTER_QUERIES is now BUILTIN_FILTERS in config.py — aliased here for compatibility
FILTER_QUERIES = BUILTIN_FILTERS

SORT_COLUMNS = {
    "name":                "Name",
    "playtime_forever":    "Hours Played",
    "last_played":         "Last Played",
    "release_date":        "Release Date",
    "date_added":          "Date Added",
    "review_percentage":   "Review Score",
    "weighted_percentage": "Weighted Score",
    "RANDOM()":            "Random",
}

from library import is_safe_sql, build_tree_sql


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


def _build_shelf_query(shelf, saved_filters):
    """Returns (where_clause, order_clause) or (None, None) for special widgets."""
    filter_key = shelf.get('filter_key') or shelf.get('preset', 'all_games')

    # Widget presets have no SQL
    if filter_key in ('clock', 'completion_pie'):
        return None, None
    # Also handle legacy preset field pointing to a widget
    if shelf.get('preset') in ('clock', 'completion_pie') and filter_key not in FILTER_QUERIES:
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
        where = _filter_tree_to_sql(saved_filters[filter_key])
    else:
        where = '1=1'

    # Platform filter — values are whitelisted so safe to inline
    _safe_platforms = {'steam', 'gog', 'epic_games', 'ea_app', 'ubisoft'}
    shelf_hidden = [p for p in (shelf.get('hidden_platforms') or []) if p in _safe_platforms]
    if shelf_hidden:
        plat_conds = []
        if 'steam' in shelf_hidden:
            plat_conds.append("NOT (platform IS NULL OR platform = '' OR platform = 'steam')")
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
        order = 'RANDOM()' if sort_col == 'RANDOM()' else f"{sort_col} {sort_dir}"
    elif not custom:
        order = 'name ASC'
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
        where, order = _build_shelf_query(shelf, saved_filters)
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

    db.close()

    # Completion counts for pie widget
    db2 = get_db()
    db2.row_factory = sqlite3.Row
    completion_counts = {}
    try:
        rows = db2.execute(
            "SELECT completion_status, COUNT(*) as cnt FROM games "
            "WHERE completion_status IS NOT NULL "
            "GROUP BY completion_status"
        ).fetchall()
        for row in rows:
            key = row['completion_status']
            if key is not None:
                completion_counts[str(key)] = row['cnt']
    except Exception:
        pass
    db2.close()

    db3 = get_db()
    db3.row_factory = sqlite3.Row
    _plat_order = ['steam', 'gog', 'epic_games', 'ea_app', 'ubisoft']
    try:
        _plat_rows = db3.execute(
            "SELECT DISTINCT COALESCE(NULLIF(platform,''),'steam') as p FROM games ORDER BY p"
        ).fetchall()
        available_platforms = sorted(
            {r['p'] for r in _plat_rows},
            key=lambda p: _plat_order.index(p) if p in _plat_order else 99
        )
    except Exception:
        available_platforms = ['steam']
    db3.close()

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
        edit_mode=edit_mode,
        available_platforms=available_platforms,
    )
