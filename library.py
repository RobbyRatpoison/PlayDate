import json
import logging
import os
import re
import threading
import time
from config import load_state, BASE_DIR, BUILTIN_FILTERS, resolve_outline_rule_where
from database import get_db, add_to_blacklist, remove_from_blacklist, get_blacklist
from utils import get_all_unique_groups, get_all_unique_tags, validate_user_path
from flask import Blueprint, jsonify, render_template, request

log = logging.getLogger(__name__)

library_bp = Blueprint('library', __name__)

# ── Cancellation + progress state for bulk operations (rescrape/art/protondb/hltb) ──
_bulk_op_state  = {'running': False, 'op': None, 'total': 0, 'done': 0,
                   'failed': 0, 'rate_limit_hit': False, 'aborted': False, 'result': None}
_bulk_op_lock   = threading.Lock()
_bulk_op_cancel = threading.Event()


def _track_manual_groups(appid: int, old_groups_str: str, new_groups_str: str):
    """Update group_sources.json when a game's groups are edited manually."""
    from config import load_group_sources, save_group_sources, gs_add_owner, gs_remove_owner
    old = {g.strip() for g in (old_groups_str or '').split(',') if g.strip()}
    new = {g.strip() for g in (new_groups_str or '').split(',') if g.strip()}
    added   = new - old
    removed = old - new
    if not added and not removed:
        return
    gs = load_group_sources()
    for group in added:
        gs_add_owner(gs, appid, group, 'manual')
    for group in removed:
        gs_remove_owner(gs, appid, group, 'manual')
    save_group_sources(gs)


def _compute_outline_colors(games, state):
    """Return {appid: color} for the highest-priority matching outline rule per game."""
    outlines = state.get('card_outlines', {})
    rules = sorted(outlines.get('rules', []), key=lambda r: r.get('priority', 999))
    if not rules:
        return {}

    _t0 = time.monotonic()
    saved_filters = state.get('saved_filters', {})
    appid_ints = [g['appid'] for g in games]
    if not appid_ints:
        return {}
    placeholders = ','.join('?' * len(appid_ints))

    # Build a single CASE WHEN query -- one round-trip instead of one per rule.
    # CASE evaluates in order so priority is preserved (first match wins).
    case_whens = []
    for rule in rules:
        color = rule.get('color')
        if not color:
            continue
        where = resolve_outline_rule_where(rule, saved_filters)
        if not where or where == '1=0':
            continue
        case_whens.append((where, color.replace("'", "''")))

    if not case_whens:
        return {}

    case_sql = 'CASE ' + ' '.join(f"WHEN ({w}) THEN '{c}'" for w, c in case_whens) + ' END'
    result = {}
    db = get_db()
    try:
        rows = db.execute(
            f"SELECT appid, {case_sql} FROM games WHERE appid IN ({placeholders})",
            appid_ints
        ).fetchall()
        for row in rows:
            if row[1] is not None:
                result[str(row[0])] = row[1]
    finally:
        db.close()
    log.info("_compute_outline_colors: %.1fms (%d rules, %d games)",
             (time.monotonic() - _t0) * 1000, len(rules), len(games))
    return result

# ── SQL builder ─────────────────────────────────────────────────────────────

SAFE_COLUMNS = {
    'appid', 'name', 'completion_status', 'installed', 'release_date', 'date_added',
    'last_played', 'playtime_forever', 'review_percentage', 'weighted_percentage',
    'review_score', 'vertical_art_source', 'horizontal_art_source', 'icon_source',
    'groups', 'tags', 'developers', 'publishers',
    'total_reviews', 'positive_reviews', 'unlocked_achievements', 'total_achievements',
    'genres', 'categories', 'is_free',
    'protondb_tier', 'protondb_confidence',
    'hltb_main', 'hltb_extras', 'hltb_completionist',
    'platform', 'platform_id', 'duplicate_of',
}

# Virtual sort columns: names that expand to SQL expressions.
# Games with no data (expr IS NULL) are always sorted last regardless of direction.
# Each maps to a single expression — ASC/DESC just reorders it, it doesn't change
# which expression runs (unlike the old combined hltb_min/max toggle).
_HLTB_MIN_EXPR = (
    "CASE WHEN NULLIF(hltb_main, 0) IS NULL AND NULLIF(hltb_extras, 0) IS NULL AND NULLIF(hltb_completionist, 0) IS NULL THEN NULL "
    "ELSE MIN(COALESCE(NULLIF(hltb_main, 0), 999999999), COALESCE(NULLIF(hltb_extras, 0), 999999999), COALESCE(NULLIF(hltb_completionist, 0), 999999999)) "
    "END"
)
# "Longest game" means the most content, not just the longest main story.
_HLTB_MAX_EXPR = (
    "CASE WHEN NULLIF(hltb_main, 0) IS NULL AND NULLIF(hltb_extras, 0) IS NULL AND NULLIF(hltb_completionist, 0) IS NULL THEN NULL "
    "ELSE MAX(COALESCE(NULLIF(hltb_main, 0), 0), COALESCE(NULLIF(hltb_extras, 0), 0), COALESCE(NULLIF(hltb_completionist, 0), 0)) "
    "END"
)
# Games with no achievements at all (total_achievements 0/NULL) have nothing
# meaningful to sort by here, so they're excluded the same way HLTB's no-data
# games are -- always last, regardless of direction. CAST guards against a
# handful of rows storing '' instead of NULL/0: SQLite ranks TEXT above any
# INTEGER, so a bare "total_achievements > 0" treats '' as satisfying it.
_ACHIEVEMENT_PERCENT_EXPR = "CASE WHEN CAST(total_achievements AS INTEGER) > 0 THEN (100.0 * CAST(unlocked_achievements AS INTEGER) / CAST(total_achievements AS INTEGER)) ELSE NULL END"
_ACHIEVEMENT_REMAINING_EXPR = "CASE WHEN CAST(total_achievements AS INTEGER) > 0 THEN (CAST(total_achievements AS INTEGER) - CAST(unlocked_achievements AS INTEGER)) ELSE NULL END"

VIRTUAL_SORT_COLS = {
    'hltb_main': "NULLIF(hltb_main, 0)",
    'hltb_extras': "NULLIF(hltb_extras, 0)",
    'hltb_completionist': "NULLIF(hltb_completionist, 0)",
    'hltb_min': _HLTB_MIN_EXPR,
    'hltb_max': _HLTB_MAX_EXPR,
    'achievement_percent': _ACHIEVEMENT_PERCENT_EXPR,
    'achievement_remaining': _ACHIEVEMENT_REMAINING_EXPR,
}

import re as _re

# ── SQL whitelist validator ──────────────────────────────────────────────────
# Tokens allowed in a user-supplied WHERE clause. Anything outside this set
# is rejected so only read-only filter expressions can be entered.
_SQL_ALLOWED_KEYWORDS = {
    'and', 'or', 'not', 'in', 'like', 'ilike', 'between', 'is', 'null',
    'true', 'false', 'exists', 'case', 'when', 'then', 'else', 'end',
    'order', 'by', 'asc', 'desc', 'limit', 'where',
    'as', 'text', 'integer', 'real', 'blob', 'numeric',
}
_SQL_ALLOWED_FUNCTIONS = {
    'lower', 'upper', 'trim', 'length', 'substr', 'replace',
    'coalesce', 'ifnull', 'nullif', 'abs', 'round', 'date', 'strftime',
    'cast',
}

_INTEGER_COLUMNS = {
    'appid', 'installed', 'unlocked_achievements', 'total_achievements',
    'review_percentage', 'weighted_percentage', 'total_reviews',
    'positive_reviews', 'is_free',
}

def _auto_cast_int_division(sql):
    """Rewrite `int_col / expr` to `CAST(int_col AS REAL) / expr` so that
    division against integer columns produces a float result in SQLite."""
    def _replace(m):
        col = m.group(1)
        if col.lower() in _INTEGER_COLUMNS:
            return f'CAST({col} AS REAL) /'
        return m.group(0)
    return _re.sub(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*/', _replace, sql)

def is_safe_sql(sql: str) -> bool:
    """
    Whitelist validator for user-supplied WHERE clauses.
    Returns True only if every token in the expression is a known-safe
    column name, SQL keyword, operator, function, or literal.
    """
    if not sql or not sql.strip():
        return False

    # Strip string literals (single-quoted) and numeric literals before tokenising
    # so their contents don't trip up the keyword check.
    # Handle escaped single quotes ('') inside literals (e.g. 'Won''t Play').
    scrubbed = _re.sub(r"'[^']*(?:''[^']*)*'", 'STRING', sql)
    scrubbed = _re.sub(r'\b\d+(\.\d+)?\b', 'NUMBER', scrubbed)

    # Tokenise: split on whitespace and punctuation, keep tokens only
    tokens = _re.findall(r'[A-Za-z_][A-Za-z0-9_]*|[^\s\w]', scrubbed)

    for tok in tokens:
        t = tok.lower()
        # Allow: known columns, keywords, functions, operators, parens, commas, wildcards
        if (t in SAFE_COLUMNS
                or t in _SQL_ALLOWED_KEYWORDS
                or t in _SQL_ALLOWED_FUNCTIONS
                or t in {'string', 'number'}   # our literal placeholders
                or _re.fullmatch(r'[=<>!%()\[\],.*?+\-/|]', tok)):
            continue
        return False
    return True



def _strip_sql_wrapper(sql):
    """Strip SELECT...WHERE prefix and ORDER BY suffix if user pasted a full query."""
    sql = sql[:10000]
    upper = sql.upper()
    where_idx = upper.find(' WHERE ')
    if where_idx >= 0:
        sql = sql[where_idx + 7:]
    order_idx = sql.upper().rfind(' ORDER BY ')
    if order_idx >= 0:
        sql = sql[:order_idx]
    return sql.strip()

def _strip_search_condition(node):
    """Remove a top-level 'name LIKE' condition (the quick-search bar) from a
    filter tree before building SQL, so the games sent to the client always
    cover the full active filter — the live search bar in library.html then
    narrows/widens client-side against that full set instead of being capped
    by whatever a previously-committed search already excluded server-side.
    Mirrors _baseTree() in library.html exactly."""
    if not isinstance(node, dict) or not node.get('items'):
        return node
    items = [item for item in node['items']
             if not (item.get('type') == 'condition' and item.get('column') == 'name' and item.get('operator') == 'LIKE')]
    if len(items) == 1 and items[0].get('type') == 'group':
        return items[0]
    return {**node, 'items': items}


DATE_COLUMNS = {'release_date', 'date_added', 'last_played'}

def build_condition_sql(cond, params):
    """Turn a single condition dict into a SQL fragment + append to params."""
    col = cond.get('column', '')
    op  = cond.get('operator', '=')
    val = cond.get('value', '')

    if col not in SAFE_COLUMNS:
        return '1=1'

    # Column vs column comparison (no value parameterisation needed)
    val_col = cond.get('value_col', '')
    if val_col:
        if val_col not in SAFE_COLUMNS:
            return '1=1'
        if op in ('=', '!=', '<', '>', '<=', '>='):
            return f"{col} {op} {val_col}"
        return '1=1'

    # Multi-value condition (chip input) — one condition node standing in for
    # what used to be N separate OR'd (or NOT-LIKE AND'd) condition nodes.
    # Only meaningful for the comma-list columns' item-match operators.
    if isinstance(val, list):
        if col not in ('tags', 'groups', 'genres', 'categories') or op not in ('LIKE', 'NOT LIKE', '=', '!='):
            return '1=1'
        items = [str(v).strip() for v in val if str(v).strip()]
        if not items:
            return '1=1'
        if op in ('LIKE', '='):
            parts = []
            for item in items:
                params.append(f"%,{item},%")
                parts.append(f"',' || {col} || ',' LIKE ?")
            return parts[0] if len(parts) == 1 else f"({' OR '.join(parts)})"
        else:  # NOT LIKE, != — excludes the game if it has ANY of the listed values
            parts = []
            for item in items:
                params.append(f"%,{item},%")
                parts.append(f"',' || {col} || ',' NOT LIKE ?")
            return parts[0] if len(parts) == 1 else f"({' AND '.join(parts)})"

    if val == '' and op not in ('IS NULL', 'IS NOT NULL'):
        return '1=1'

    # Comma-separated list columns — exact item match
    if col in ('tags', 'groups', 'genres', 'categories'):
        if op in ('LIKE', '='):
            params.append(f"%,{val},%")
            return f"',' || {col} || ',' LIKE ?"
        else:  # NOT LIKE, !=
            params.append(f"%,{val},%")
            return f"',' || {col} || ',' NOT LIKE ?"

    if op == '=':
        if col in DATE_COLUMNS:
            from database import date_to_ts
            ts = date_to_ts(val)
            if ts is None:
                return '1=1'
            params.extend([ts, ts + 86400])
            return f"({col} >= ? AND {col} < ?)"
        params.append(val)
        return f"{col} = ? COLLATE NOCASE"
    elif op == '!=':
        if col in DATE_COLUMNS:
            from database import date_to_ts
            ts = date_to_ts(val)
            if ts is None:
                return '1=1'
            params.extend([ts, ts + 86400])
            return f"({col} < ? OR {col} >= ?)"
        params.append(val)
        return f"{col} != ? COLLATE NOCASE"
    elif op == 'LIKE':
        if col in DATE_COLUMNS:
            params.append(val if '%' in val else f"{val}%")
            return f"({col} IS NOT NULL AND {col} != 0 AND strftime('%Y-%m-%d', {col}, 'unixepoch') LIKE ?)"
        params.append(f"%{val}%")
        return f"{col} LIKE ?"
    elif op == 'NOT LIKE':
        if col in DATE_COLUMNS:
            params.append(val if '%' in val else f"{val}%")
            return f"({col} IS NOT NULL AND {col} != 0 AND strftime('%Y-%m-%d', {col}, 'unixepoch') NOT LIKE ?)"
        params.append(f"%{val}%")
        return f"{col} NOT LIKE ?"
    elif op == 'STARTS_WITH':
        params.append(f"{val}%")
        return f"{col} LIKE ?"
    elif op in ('>', '<', '>=', '<='):
        if col in DATE_COLUMNS:
            from database import date_to_ts
            ts = date_to_ts(val)
            if ts is None:
                return '1=1'
            # > means strictly after that day; <= means through end of that day
            if op == '>':
                params.append(ts + 86400)
                return f"{col} >= ?"
            elif op == '<=':
                params.append(ts + 86400)
                return f"{col} < ?"
            else:  # < and >= use midnight directly
                params.append(ts)
                return f"{col} {op} ?"
        else:
            params.append(val)
        return f"{col} {op} ?"
    elif op == 'STRFTIME_MONTH':
        params.append(val.zfill(2))
        return f"({col} IS NOT NULL AND {col} != 0 AND strftime('%m', {col}, 'unixepoch') = ?)"
    elif op == 'STRFTIME_DAY':
        params.append(val.zfill(2))
        return f"({col} IS NOT NULL AND {col} != 0 AND strftime('%d', {col}, 'unixepoch') = ?)"
    elif op == 'STRFTIME_YEAR':
        params.append(val)
        return f"({col} IS NOT NULL AND {col} != 0 AND strftime('%Y', {col}, 'unixepoch') = ?)"
    elif op == 'STRFTIME_WEEKDAY':
        params.append(str(val))
        return f"({col} IS NOT NULL AND {col} != 0 AND strftime('%w', datetime({col}, 'unixepoch')) = ?)"
    elif op == 'IS NULL':
        if col in DATE_COLUMNS:
            return f"({col} IS NULL OR {col} = 0)"
        return f"({col} IS NULL OR {col} = '')"
    elif op == 'IS NOT NULL':
        if col in DATE_COLUMNS:
            return f"({col} IS NOT NULL AND {col} != 0)"
        return f"({col} IS NOT NULL AND {col} != '')"
    else:
        params.append(val)
        return f"{col} = ?"

def build_tree_sql(node, params):
    """Recursively build SQL from a filter tree node."""
    node_type = node.get('type', 'condition')

    if node_type == 'condition':
        return build_condition_sql(node, params)

    if node_type == 'appid_list':
        raw = node.get('appids', [])
        safe = [a for a in raw if isinstance(a, int)]
        if not safe:
            return '1=1'
        return f"appid IN ({','.join(str(a) for a in safe)})"

    if node_type == 'appid_list_ref':
        from config import _get_supplement_source_appids
        appids = sorted(_get_supplement_source_appids().get(node.get('source', ''), frozenset()))
        if not appids:
            return '1=1'
        return f"appid IN ({','.join(str(a) for a in appids)})"

    if node_type == 'custom_expr':
        sql = node.get('sql', '').strip()
        if sql and is_safe_sql(sql):
            return f"({_auto_cast_int_division(sql)})"
        return '1=1'

    if node_type == 'group':
        items = node.get('items', [])
        logic = node.get('logic', 'AND').upper()
        if logic not in ('AND', 'OR'):
            logic = 'AND'

        parts = []
        for item in items:
            sql = build_tree_sql(item, params)
            if sql and sql != '1=1':
                parts.append(sql)

        if not parts:
            return '1=1'
        joined = f" {logic} ".join(parts)
        return f"({joined})" if len(parts) > 1 else joined

    return '1=1'

# ── Routes ───────────────────────────────────────────────────────────────────

@library_bp.route('/library')
def library():
    db = get_db()
    state = load_state()

    sort_col = state.get('sort', 'name')
    sort_ord = state.get('order', 'ASC')
    if sort_ord not in ('ASC', 'DESC'):
        sort_ord = 'ASC'
    # Virtual sort columns expand to expressions; NULLs always sort last
    if sort_col == 'random':
        sort_col = 'RANDOM()'
        sort_ord = ''
    elif sort_col in VIRTUAL_SORT_COLS:
        _expr = VIRTUAL_SORT_COLS[sort_col]
        sort_col = f"CASE WHEN ({_expr}) IS NULL THEN 1 ELSE 0 END, ({_expr})"
    elif sort_col not in SAFE_COLUMNS:
        sort_col = 'name'

    params = []
    where = "1=1"

    from config import resolve_active_filter_tree, _expand_appid_list_refs
    _ft_raw = state.get('filter_tree')
    active_filter_name = _ft_raw.get('saved_filter') if isinstance(_ft_raw, dict) and 'saved_filter' in _ft_raw else None
    filter_tree = resolve_active_filter_tree(state)
    state['filter_tree'] = filter_tree  # template sees resolved tree

    if filter_tree:
        # Custom SQL override — user typed their own WHERE clause
        custom_sql = _strip_sql_wrapper(filter_tree.get('custom_sql', ''))
        if custom_sql:
            if not is_safe_sql(custom_sql):
                where = '1=0'
            else:
                where = _auto_cast_int_division(custom_sql)
        else:
            tree_sql = build_tree_sql(_strip_search_condition(filter_tree), params)
            if tree_sql and tree_sql != '1=1':
                where = tree_sql

    if state.get('hide_duplicates', True):
        dup_cond = "(duplicate_of IS NULL OR duplicate_of = '')"
        where = dup_cond if where == '1=1' else f"({where}) AND {dup_cond}"

    import re as _re
    hidden_platforms = [p for p in state.get('hidden_platforms', []) if _re.match(r'^[a-z][a-z0-9_]*$', p or '')]
    if hidden_platforms:
        plat_conds = []
        if 'steam' in hidden_platforms:
            plat_conds.append("platform != 'steam'")
        non_steam = [p for p in hidden_platforms if p != 'steam']
        if non_steam:
            placeholders = ','.join('?' for _ in non_steam)
            plat_conds.append(f"platform NOT IN ({placeholders})")
            params.extend(non_steam)
        plat_cond = ' AND '.join(plat_conds)
        where = plat_cond if where == '1=1' else f"({where}) AND ({plat_cond})"

    query = f"SELECT * FROM games WHERE {where} ORDER BY {sort_col} {sort_ord}".rstrip()

    sql_error = None
    try:
        rows = db.execute(query, params).fetchall()
        games = [dict(row) for row in rows]
    except Exception as e:
        sql_error = str(e)
        try:
            rows = db.execute(f"SELECT * FROM games ORDER BY {sort_col} {sort_ord}".rstrip()).fetchall()
            games = [dict(row) for row in rows]
        except Exception:
            games = []

    total_games  = db.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    hidden_dupes = db.execute(
        "SELECT COUNT(*) FROM games WHERE duplicate_of IS NOT NULL AND duplicate_of != ''"
    ).fetchone()[0]
    _plat_rows = db.execute("SELECT DISTINCT platform as p FROM games ORDER BY p").fetchall()

    _grp_rows = db.execute("SELECT groups FROM games WHERE groups IS NOT NULL").fetchall()
    _tag_rows = db.execute("SELECT tags   FROM games WHERE tags   IS NOT NULL").fetchall()
    db.close()

    groups = sorted({v.strip() for row in _grp_rows for v in (row['groups'] or '').split(',') if v.strip()}, key=str.casefold)
    tags   = sorted({v.strip() for row in _tag_rows for v in (row['tags']   or '').split(',') if v.strip()}, key=str.casefold)

    _outlines_cfg = state.get('card_outlines', {})
    outline_colors = (
        _compute_outline_colors(games, state)
        if _outlines_cfg.get('enabled', {}).get('library', True)
        else {}
    )

    # Drop icon_hash — it's a raw Steam hash used only server-side during scraping,
    # never referenced in browser JS, so no need to ship it to every page load.
    from database import ts_to_date
    for g in games:
        g.pop('icon_hash', None)
        for col in ('last_played', 'date_added', 'release_date'):
            if g.get(col):
                g[col] = ts_to_date(g[col])

    from plugins import platform_labels as _platform_labels
    _plat_order = list(_platform_labels().keys())
    available_platforms = sorted(
        {r['p'] for r in _plat_rows},
        key=lambda p: _plat_order.index(p) if p in _plat_order else 99
    )

    # Expand appid_list_ref nodes in saved filters before sending to browser.
    # state.json stores refs for compactness; the JS filter tree builder only handles appid_list.
    raw_saved = state.get('saved_filters', {})
    expanded_saved = {}
    for fname, entry in raw_saved.items():
        if isinstance(entry, dict) and 'tree' in entry:
            expanded_saved[fname] = {**entry, 'tree': _expand_appid_list_refs(entry['tree'])}
        elif isinstance(entry, dict):
            expanded_saved[fname] = _expand_appid_list_refs(entry)
        else:
            expanded_saved[fname] = entry
    state = {**state, 'saved_filters': expanded_saved}

    return render_template('library.html', games=games, state=state,
                           unique_tags=tags, unique_groups=groups,
                           sql_error=sql_error, builtin_filters=BUILTIN_FILTERS,
                           total_games=total_games, hidden_dupes=hidden_dupes,
                           available_platforms=available_platforms,
                           hidden_platforms=hidden_platforms,
                           group_by=state.get('group_by'),
                           outline_colors=outline_colors,
                           active_filter_name=active_filter_name)


@library_bp.route('/update_game', methods=['POST'])
def update_game():
    data = request.form.to_dict()
    appid = data.pop('edit-appid')
    if 'installed' in data:
        data['installed'] = 1 if data['installed'] == '1' else 0
    from database import update_game_data, date_to_ts
    for col in ('last_played', 'date_added', 'release_date'):
        if col in data:
            data[col] = date_to_ts(data[col]) if data[col] else None
    from utils import get_all_unique_genres, get_all_unique_categories, invalidate_unique_cache
    try:
        old_groups_str = None
        if 'groups' in data:
            db = get_db()
            old_row = db.execute("SELECT groups FROM games WHERE appid = ?", (appid,)).fetchone()
            db.close()
            old_groups_str = (old_row['groups'] if old_row else None) or ''
        update_game_data(appid, **data)
        invalidate_unique_cache()
        if 'groups' in data:
            _track_manual_groups(int(appid), old_groups_str, data['groups'] or '')
        db = get_db()
        row = db.execute("SELECT * FROM games WHERE appid = ?", (appid,)).fetchone()
        db.close()
        game = dict(row) if row else {"appid": appid}
        from database import ts_to_date
        for col in ('last_played', 'date_added', 'release_date'):
            if game.get(col):
                game[col] = ts_to_date(game[col])
        state = load_state()
        _outlines_cfg = state.get('card_outlines', {})
        outline_map = (
            _compute_outline_colors([game], state)
            if _outlines_cfg.get('enabled', {}).get('library', True)
            else {}
        )
        return jsonify({
            "status": "success",
            "game": game,
            "outline_color": outline_map.get(str(appid)),
            "unique_tags":       get_all_unique_tags(),
            "unique_groups":     get_all_unique_groups(),
            "unique_genres":     get_all_unique_genres(),
            "unique_categories": get_all_unique_categories(),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def bulk_edit_games(data):
    from flask import jsonify
    column = data.get('column', '').strip()
    mode   = data.get('mode', 'replace')
    value  = data.get('value', '').strip()
    filter_tree = data.get('filter_tree')
    appids = data.get('appids')   # list of ints — takes priority over filter_tree

    allowed_columns = {c: c for c in (
        'completion_status', 'tags', 'groups', 'developers', 'publishers',
        'release_date', 'review_score', 'review_percentage', 'weighted_percentage',
        'total_reviews', 'positive_reviews', 'playtime_forever', 'date_added',
        'installed', 'vertical_art_source', 'horizontal_art_source', 'icon_source',
        'unlocked_achievements', 'total_achievements',
        'genres', 'categories', 'is_free'
    )}
    column = allowed_columns.get(column)
    if not column:
        return jsonify({"status": "error", "message": "Column is not editable."}), 400
    if not value and mode not in ('replace', 'remove'):
        return jsonify({"status": "error", "message": "Value cannot be empty."}), 400

    # Build WHERE clause
    params = []
    where = "1=1"

    if appids is not None:
        # Explicit appid list — ignore filter_tree entirely
        if not appids:
            return jsonify({"status": "error", "message": "No games selected."}), 400
        placeholders = ','.join('?' * len(appids))
        where = f"appid IN ({placeholders})"
        params = list(appids)
    elif filter_tree:
        custom_sql = _strip_sql_wrapper(filter_tree.get('custom_sql', ''))
        if custom_sql:
            if is_safe_sql(custom_sql):
                where = _auto_cast_int_division(custom_sql)
        else:
            tree_sql = build_tree_sql(filter_tree, params)
            if tree_sql and tree_sql != '1=1':
                where = tree_sql

    hidden_platforms = [p for p in (data.get('hidden_platforms') or []) if _re.match(r'^[a-z][a-z0-9_]*$', p or '')]
    if hidden_platforms:
        plat_conds = []
        if 'steam' in hidden_platforms:
            plat_conds.append("platform != 'steam'")
        non_steam = [p for p in hidden_platforms if p != 'steam']
        if non_steam:
            placeholders = ','.join('?' for _ in non_steam)
            plat_conds.append(f"platform NOT IN ({placeholders})")
            params.extend(non_steam)
        plat_cond = ' AND '.join(plat_conds)
        where = plat_cond if where == '1=1' else f"({where}) AND ({plat_cond})"

    DATE_COLUMNS = {'date_added', 'last_played', 'release_date'}
    if column in DATE_COLUMNS and value:
        from database import date_to_ts
        value = date_to_ts(value)
        if value is None:
            return jsonify({"status": "error", "message": "Invalid date format. Use YYYY-MM-DD."}), 400

    try:
        db = get_db()

        if mode == 'replace':
            if column == 'groups':
                games = db.execute(f"SELECT appid, groups FROM games WHERE {where}", params).fetchall()
                db.execute(f"UPDATE games SET {column} = ? WHERE {where}", [value if value else None] + params)
                updated = db.execute("SELECT changes()").fetchone()[0]
                db.commit()
                db.close()
                for game in games:
                    _track_manual_groups(game['appid'], game['groups'] or '', value or '')
            else:
                db.execute(f"UPDATE games SET {column} = ? WHERE {where}", [value if value else None] + params)
                updated = db.execute("SELECT changes()").fetchone()[0]
                db.commit()
                db.close()
            return jsonify({"status": "success", "updated": updated})

        elif mode == 'append':
            games = db.execute(f"SELECT appid, {column} FROM games WHERE {where}", params).fetchall()
            updated = 0
            for game in games:
                appid = game['appid']
                existing = game[column] or ''
                existing_list = [v.strip() for v in existing.split(',') if v.strip()]
                existing_lower = {v.lower() for v in existing_list}
                new_vals = [v.strip() for v in value.split(',') if v.strip()]
                added = False
                for v in new_vals:
                    if v.lower() not in existing_lower:
                        existing_list.append(v)
                        existing_lower.add(v.lower())
                        added = True
                if added:
                    db.execute(f"UPDATE games SET {column} = ? WHERE appid = ?",
                               (','.join(existing_list), appid))
                    if column == 'groups':
                        _track_manual_groups(appid, existing, ','.join(existing_list))
                    updated += 1
            db.commit()
            db.close()
            return jsonify({"status": "success", "updated": updated})

        elif mode == 'remove':
            games = db.execute(f"SELECT appid, {column} FROM games WHERE {where}", params).fetchall()
            updated = 0
            remove_vals = {v.strip().lower() for v in value.split(',') if v.strip()}
            for game in games:
                appid = game['appid']
                existing = game[column] or ''
                existing_list = [v.strip() for v in existing.split(',') if v.strip()]
                new_list = [v for v in existing_list if v.lower() not in remove_vals]
                if len(new_list) != len(existing_list):
                    db.execute(f"UPDATE games SET {column} = ? WHERE appid = ?",
                               (','.join(new_list), appid))
                    if column == 'groups':
                        _track_manual_groups(appid, existing, ','.join(new_list))
                    updated += 1
            db.commit()
            db.close()
            return jsonify({"status": "success", "updated": updated})

        db.close()
        return jsonify({"status": "error", "message": "Invalid mode."}), 400

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def bulk_distinct_values(data):
    from flask import jsonify
    column = data.get('column', '').strip()
    if column not in {'tags', 'groups', 'genres', 'categories'}:
        return jsonify({"status": "error", "message": "Column not allowed."}), 400

    params = []
    where = "1=1"
    appids = data.get('appids')
    filter_tree = data.get('filter_tree')

    if appids is not None:
        if not appids:
            return jsonify({"values": []})
        placeholders = ','.join('?' * len(appids))
        where = f"appid IN ({placeholders})"
        params = list(appids)
    elif filter_tree:
        custom_sql = _strip_sql_wrapper(filter_tree.get('custom_sql', ''))
        if custom_sql:
            if is_safe_sql(custom_sql):
                where = _auto_cast_int_division(custom_sql)
        else:
            tree_sql = build_tree_sql(filter_tree, params)
            if tree_sql and tree_sql != '1=1':
                where = tree_sql

    hidden_platforms = [p for p in (data.get('hidden_platforms') or []) if _re.match(r'^[a-z][a-z0-9_]*$', p or '')]
    if hidden_platforms:
        plat_conds = []
        if 'steam' in hidden_platforms:
            plat_conds.append("platform != 'steam'")
        non_steam = [p for p in hidden_platforms if p != 'steam']
        if non_steam:
            placeholders = ','.join('?' for _ in non_steam)
            plat_conds.append(f"platform NOT IN ({placeholders})")
            params.extend(non_steam)
        plat_cond = ' AND '.join(plat_conds)
        where = plat_cond if where == '1=1' else f"({where}) AND ({plat_cond})"

    try:
        db = get_db()
        rows = db.execute(
            f"SELECT {column} FROM games WHERE ({where}) AND {column} IS NOT NULL AND {column} != ''",
            params
        ).fetchall()
        db.close()
        seen = set()
        for row in rows:
            for v in row[column].split(','):
                v = v.strip()
                if v:
                    seen.add(v)
        return jsonify({"values": sorted(seen, key=str.lower)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Additional routes ────────────────────────────────────────────────────────

@library_bp.route('/api/scrape_single/<int:appid>', methods=['GET', 'POST'])
def scrape_single(appid):
    import requests
    from scrapers import fetch_store_data, fetch_tag_data, fetch_player_data, fetch_review_data, fetch_cheevo_data, RateLimitedError
    from utils import fetch_local_library, get_acf_names, parse_appinfo
    from config import load_config as _load_config, get_active_account as _get_active_account
    _cfg     = _load_config() or {}
    _account = _get_active_account() or {}

    # The fetch_* helpers below all swallow connection errors into a plain
    # None/{} the same way they swallow "Steam has no data for this appid",
    # so a real network outage otherwise looks identical to a harmless empty
    # result and this route reports fake success. Probe first so we can
    # tell the user their internet is down instead of silently no-oping.
    try:
        requests.head('https://store.steampowered.com/', timeout=8)
    except requests.exceptions.RequestException:
        return jsonify({"status": "error",
                         "message": "Could not reach Steam — check your internet connection."}), 503

    try:
        player_data = fetch_player_data(appid) or {}
        store_data  = fetch_store_data(appid) or {}
        review_data = fetch_review_data(appid) or {}
        cheevo_data = fetch_cheevo_data(appid) or {} if _account.get('api_key') else {}
        tag_data    = fetch_tag_data(appid) or {}
    except RateLimitedError as e:
        retry_after = round(e.retry_after) if e.retry_after else None
        message = (f"Steam is rate-limiting requests — try again in {retry_after}s."
                   if retry_after else "Steam is rate-limiting requests — try again shortly.")
        return jsonify({"status": "error", "message": message, "retry_after": retry_after}), 429

    data_out = {
        "developers":             store_data.get('developers', ''),
        "publishers":             store_data.get('publishers', ''),
        "release_date":           store_data.get('release_date', ''),
        "genres":                 store_data.get('genres', ''),
        "categories":             store_data.get('categories', ''),
        "is_free":                store_data.get('is_free', 0),
        "review_score":           review_data.get('review_score', ''),
        "review_percentage":      review_data.get('review_percentage', ''),
        "weighted_percentage":    review_data.get('weighted_percentage', ''),
        "total_reviews":          review_data.get('total_reviews', ''),
        "positive_reviews":       review_data.get('positive_reviews', ''),
        "total_achievements":     cheevo_data.get('total_achievements', 0),
        "unlocked_achievements":  cheevo_data.get('unlocked_achievements', 0),
        "tags":                   tag_data.get('tags', '')
    }

    # Playtime, last_played, name: prefer API, fall back to local Steam files
    local_entry = next((g for g in fetch_local_library(_cfg.get('steam_id')) if g['appid'] == appid), None)

    playtime   = player_data.get('playtime_forever')
    last_played = player_data.get('last_played') or None
    name        = player_data.get('name') or None

    if playtime is None and local_entry:
        playtime = local_entry.get('playtime_forever')
    if not last_played and local_entry:
        lp = local_entry.get('last_played', '0')
        last_played = lp if lp and lp != '0' else None
    if not name:
        name = get_acf_names().get(appid) or parse_appinfo().get(appid, {}).get('name') or None

    if playtime is not None:
        data_out['playtime_forever'] = playtime
    if last_played:
        data_out['last_played'] = last_played
    if name:
        data_out['name'] = name

    # Convert timestamps to date strings for the frontend form
    from database import ts_to_date
    for col in ('last_played', 'release_date'):
        if data_out.get(col) is not None:
            data_out[col] = ts_to_date(data_out[col]) or ''

    return jsonify({"status": "success", "data": data_out})

@library_bp.route('/api/games/search')
def search_games():
    q        = request.args.get('q', '').strip()
    platform = request.args.get('platform', '')
    if not q:
        return jsonify([])
    try:
        db = get_db()
        if platform:
            rows = db.execute(
                "SELECT appid, name, platform FROM games WHERE name LIKE ? AND platform = ? "
                "ORDER BY name LIMIT 20",
                (f'%{q}%', platform)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT appid, name, platform FROM games WHERE name LIKE ? ORDER BY name LIMIT 20",
                (f'%{q}%',)
            ).fetchall()
        db.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@library_bp.route('/api/game/<int:appid>/set-duplicate', methods=['POST'])
def set_duplicate(appid):
    """Set or clear the duplicate_of field for a game."""
    from database import update_game_data, invalidate_dup_cache
    data         = request.json or {}
    duplicate_of = data.get('duplicate_of')   # appid string, or null/'' to clear
    try:
        db = get_db()
        db.execute(
            "UPDATE games SET duplicate_of = ?, duplicate_auto = 0 WHERE appid = ?",
            (str(duplicate_of) if duplicate_of else None, appid)
        )
        db.commit()
        if duplicate_of:
            canonical = db.execute(
                "SELECT hltb_fetched, hltb_id, hltb_matched_name, hltb_match_score, "
                "hltb_main, hltb_extras, hltb_completionist FROM games WHERE appid=?",
                (str(duplicate_of),)
            ).fetchone()
            if canonical and canonical['hltb_fetched'] not in (None, '0', 'unconfirmed', 'no_match'):
                hltb_data = {k: canonical[k] for k in
                             ('hltb_fetched', 'hltb_id', 'hltb_matched_name', 'hltb_match_score',
                              'hltb_main', 'hltb_extras', 'hltb_completionist')}
                update_game_data(appid, **hltb_data)
        db.close()
        invalidate_dup_cache()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@library_bp.route('/api/game/<int:appid>')
def get_game(appid):
    try:
        from database import ts_to_date
        db  = get_db()
        row = db.execute("SELECT * FROM games WHERE appid = ?", (appid,)).fetchone()
        db.close()
        if row:
            game = dict(row)
            for col in ('last_played', 'date_added', 'release_date'):
                if game.get(col):
                    game[col] = ts_to_date(game[col])
            return jsonify({"status": "success", "game": game})
        return jsonify({"status": "error", "message": "Game not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@library_bp.route('/api/game-description/<int:appid>')
def game_description(appid):
    import plugins as _plugins
    import requests as _r
    db = get_db()
    row = db.execute("SELECT platform, platform_id FROM games WHERE appid = ?", (appid,)).fetchone()
    db.close()
    if not row:
        return jsonify({'status': 'error', 'message': 'Game not found'}), 404
    platform = row['platform'] or 'steam'
    try:
        plugin = _plugins.get_for_platform(platform)
        if plugin is not None and hasattr(plugin, 'fetch_description'):
            desc = plugin.fetch_description(appid, row['platform_id'])
            if desc:
                return jsonify({'status': 'success', 'description': desc})
        elif platform == 'steam':
            resp = _r.get(
                f'https://store.steampowered.com/api/appdetails?appids={appid}',
                timeout=10
            )
            if resp.ok:
                d = resp.json()
                app_data = d.get(str(appid), {})
                if app_data.get('success'):
                    desc = app_data.get('data', {}).get('short_description', '')
                    return jsonify({'status': 'success', 'description': desc})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    return jsonify({'status': 'error', 'message': 'No description available'})

@library_bp.route('/api/game-extra-info/<int:appid>')
def game_extra_info(appid):
    import plugins as _plugins
    db = get_db()
    row = db.execute("SELECT platform, platform_id FROM games WHERE appid = ?", (appid,)).fetchone()
    db.close()
    if not row:
        return jsonify({'status': 'error', 'message': 'Game not found'}), 404
    platform = row['platform'] or 'steam'
    items = _plugins.collect_extra_info(appid, platform, row['platform_id'])
    return jsonify({'status': 'success', 'items': items})

@library_bp.route('/api/set-completion/<int:appid>', methods=['POST'])
def set_completion(appid):
    from database import update_game_data
    status = (request.json or {}).get('status', '').strip()
    allowed = {'Never Played', 'Unfinished', 'Beaten', 'Completed', "Won't Play"}
    if status not in allowed:
        return jsonify({"status": "error", "message": f"Invalid status: {status!r}"}), 400
    try:
        update_game_data(appid, completion_status=status)
        return jsonify({"status": "success", "completion_status": status})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@library_bp.route('/api/bulk-op/start', methods=['POST'])
def bulk_op_start():
    if _bulk_op_state['running']:
        return jsonify({'status': 'error', 'message': 'Already running'}), 400

    data   = request.json or {}
    op     = data.get('op')            # 'rescrape' or 'art'
    scope  = data.get('scope', 'filtered')
    appids = data.get('appids', [])
    types  = data.get('types', ['vertical', 'horizontal', 'icon'])
    source = data.get('source', 'auto')

    if op not in ('rescrape', 'art', 'protondb', 'hltb', 'hltb_confirm', 'metadata'):
        return jsonify({'status': 'error', 'message': 'Invalid op'}), 400

    if scope == 'all':
        db     = get_db()
        rows   = db.execute("SELECT appid FROM games").fetchall()
        db.close()
        appids = [r['appid'] for r in rows]
    elif scope == 'no_match' and op == 'hltb':
        db     = get_db()
        rows   = db.execute("SELECT appid FROM games WHERE hltb_fetched = 'no_match'").fetchall()
        db.close()
        appids = [r['appid'] for r in rows]
    elif op == 'hltb_confirm':
        try:
            threshold = int(data.get('threshold', 75))
        except (TypeError, ValueError):
            threshold = 75
        db     = get_db()
        rows   = db.execute(
            "SELECT appid FROM games WHERE hltb_fetched = 'unconfirmed' "
            "AND hltb_id IS NOT NULL AND COALESCE(hltb_match_score, 0) >= ?",
            (threshold,)
        ).fetchall()
        db.close()
        appids = [r['appid'] for r in rows]
    elif op == 'metadata':
        # Honour the scope selector, then narrow to games that actually still
        # need a backfill pass (non-Steam, not already done). 'all' = every
        # pending non-Steam game; 'filtered'/'selected' = the passed appids
        # intersected with that pending set.
        from scrapers import _METADATA_PENDING_SQL, _METADATA_PENDING_WHERE
        db = get_db()
        if scope == 'all':
            rows = db.execute(_METADATA_PENDING_SQL).fetchall()
        else:
            ids = [int(a) for a in appids]
            if ids:
                ph   = ','.join('?' * len(ids))
                rows = db.execute(
                    f"SELECT appid FROM games WHERE {_METADATA_PENDING_WHERE} "
                    f"AND appid IN ({ph}) ORDER BY appid", ids
                ).fetchall()
            else:
                rows = []
        db.close()
        appids = [r['appid'] for r in rows]

    appids = [int(a) for a in appids]
    if not appids:
        return jsonify({'status': 'error', 'message': 'No games to process'}), 400

    _bulk_op_cancel.clear()
    with _bulk_op_lock:
        if _bulk_op_state['running']:   # re-check under the lock (startup catch-up may have grabbed the slot)
            return jsonify({'status': 'error', 'message': 'Already running'}), 400
        _bulk_op_state.update(running=True, op=op, total=len(appids),
                              done=0, failed=0, rate_limit_hit=False,
                              aborted=False, result=None)

    def _progress(event, _data, _total):
        with _bulk_op_lock:
            if event == 'done':
                _bulk_op_state['done'] += 1
            elif event == 'failed':
                _bulk_op_state['failed'] += 1
            elif event == 'rate_limit':
                _bulk_op_state['rate_limit_hit'] = True

    def _run():
        from scrapers import (bulk_rescrape_games, bulk_art_scrape_games,
                              bulk_protondb_scrape_games, bulk_hltb_scrape_games,
                              bulk_hltb_confirm_matches, bulk_backfill_metadata)
        try:
            if op == 'rescrape':
                result = bulk_rescrape_games(appids, _bulk_op_cancel, _progress)
            elif op == 'art':
                result = bulk_art_scrape_games(appids, types, source, _bulk_op_cancel, _progress)
            elif op == 'protondb':
                result = bulk_protondb_scrape_games(appids, _bulk_op_cancel, _progress)
            elif op == 'hltb_confirm':
                result = bulk_hltb_confirm_matches(appids, _bulk_op_cancel, _progress)
            elif op == 'metadata':
                result = bulk_backfill_metadata(appids, _bulk_op_cancel, _progress)
            else:
                result = bulk_hltb_scrape_games(appids, _bulk_op_cancel, _progress)
            with _bulk_op_lock:
                _bulk_op_state['result']  = result
                _bulk_op_state['aborted'] = result.get('aborted', False)
        except Exception as e:
            log.exception(f"bulk_op_start ({op}): {e}")
            with _bulk_op_lock:
                _bulk_op_state['result'] = {'error': str(e)}
        finally:
            with _bulk_op_lock:
                _bulk_op_state['running'] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'success', 'total': len(appids)})

@library_bp.route('/api/bulk-op/status', methods=['GET'])
def bulk_op_status():
    with _bulk_op_lock:
        return jsonify(dict(_bulk_op_state))

@library_bp.route('/api/bulk-op/cancel', methods=['POST'])
def bulk_op_cancel_route():
    _bulk_op_cancel.set()
    return jsonify({'status': 'success'})

@library_bp.route('/api/bulk-edit', methods=['POST'])
def bulk_edit():
    return bulk_edit_games(request.json)

@library_bp.route('/api/bulk-edit/distinct-values', methods=['POST'])
def bulk_edit_distinct_values():
    return bulk_distinct_values(request.json)

@library_bp.route('/api/save-filter', methods=['POST'])
def save_filter():
    from config import _state_lock, _load_state_unlocked, _write_state_atomic, _compact_tree_pv, _compact_appid_list_refs, _compact_shared_ids
    data = request.json
    name = (data.get('name') or '').strip()
    tree = data.get('filter_tree')
    if not name:
        return jsonify({"status": "error", "message": "Name cannot be empty."}), 400
    if not tree:
        return jsonify({"status": "error", "message": "No filter to save."}), 400
    tree = _compact_tree_pv(_compact_appid_list_refs(tree))
    with _state_lock:
        state = _load_state_unlocked()
        if 'saved_filters' not in state:
            state['saved_filters'] = {}
        existing = state['saved_filters'].get(name, {})
        existing_id = existing.get('id') if isinstance(existing, dict) else None
        import uuid as _uuid
        state['saved_filters'][name] = {
            'id': existing_id or str(_uuid.uuid4()),
            'tree': tree,
        }
        _compact_shared_ids(state)
        _write_state_atomic(state)
    return jsonify({"status": "success"})

@library_bp.route('/api/delete-filter', methods=['POST'])
def delete_filter():
    from config import _state_lock, _load_state_unlocked, _write_state_atomic
    name = (request.json.get('name') or '').strip()
    if not name:
        return jsonify({"status": "error", "message": "Name required."}), 400
    with _state_lock:
        state = _load_state_unlocked()
        state.get('saved_filters', {}).pop(name, None)
        ft = state.get('filter_tree')
        if isinstance(ft, dict) and ft.get('saved_filter') == name:
            state['filter_tree'] = None
        _write_state_atomic(state)
    return jsonify({"status": "success"})

@library_bp.route('/api/rename-filter', methods=['POST'])
def rename_filter():
    from config import _state_lock, _load_state_unlocked, _write_state_atomic
    old_name = (request.json.get('old_name') or '').strip()
    new_name = (request.json.get('new_name') or '').strip()
    if not old_name or not new_name:
        return jsonify({"status": "error", "message": "Both names required."}), 400
    with _state_lock:
        state = _load_state_unlocked()
        filters = state.get('saved_filters', {})
        if old_name not in filters:
            return jsonify({"status": "error", "message": "Filter not found."}), 404
        if new_name in filters:
            return jsonify({"status": "error", "message": f'A filter named "{new_name}" already exists.'}), 400
        filters[new_name] = filters.pop(old_name)
        state['saved_filters'] = filters
        ft = state.get('filter_tree')
        if isinstance(ft, dict) and ft.get('saved_filter') == old_name:
            state['filter_tree'] = {'saved_filter': new_name}
        _write_state_atomic(state)
    return jsonify({"status": "success"})

@library_bp.route('/api/card-outlines', methods=['GET'])
def get_card_outlines():
    state = load_state()
    outlines = state.get('card_outlines', {})
    saved_filters = state.get('saved_filters', {})
    saved_list = [
        {'id': v['id'], 'name': k}
        for k, v in saved_filters.items()
        if isinstance(v, dict) and v.get('id')
    ]
    return jsonify({'status': 'success', 'card_outlines': outlines, 'saved_filters': saved_list})

@library_bp.route('/api/card-outlines', methods=['POST'])
def save_card_outlines():
    from config import _state_lock, _load_state_unlocked, _write_state_atomic
    import uuid as _uuid
    data = request.json or {}
    outlines = data.get('card_outlines')
    if outlines is None:
        return jsonify({'status': 'error', 'message': 'Missing card_outlines'}), 400
    # Assign UUIDs to any new rules missing them
    for rule in outlines.get('rules', []):
        if not rule.get('id'):
            rule['id'] = str(_uuid.uuid4())
    with _state_lock:
        state = _load_state_unlocked()
        state['card_outlines'] = outlines
        _write_state_atomic(state)
    return jsonify({'status': 'success'})

@library_bp.route('/api/card-badges', methods=['GET'])
def get_card_badges():
    state = load_state()
    return jsonify({'status': 'success', 'card_badges': state.get('card_badges', {})})

@library_bp.route('/api/card-badges', methods=['POST'])
def save_card_badges():
    from config import _state_lock, _load_state_unlocked, _write_state_atomic
    data = request.json or {}
    badges = data.get('card_badges')
    if badges is None:
        return jsonify({'status': 'error', 'message': 'Missing card_badges'}), 400
    # Each feature may only occupy one slot -- defensively re-enforce here too
    # (the UI already auto-vacates), keeping the first occurrence in a fixed
    # corner order and clearing any later duplicate.
    seen = set()
    for corner in ('top_left', 'top_right', 'bottom_left', 'bottom_right'):
        feature = (badges.get('slots') or {}).get(corner)
        if feature and feature in seen:
            badges['slots'][corner] = None
        elif feature:
            seen.add(feature)
    with _state_lock:
        state = _load_state_unlocked()
        # The edit button's corner always wins -- defensively clear a badge
        # slot there too, in case this request predates a corner move the
        # client hasn't caught up to yet.
        eb_corner = state.get('edit_button', {}).get('corner')
        if eb_corner and (badges.get('slots') or {}).get(eb_corner):
            badges['slots'][eb_corner] = None
        state['card_badges'] = badges
        _write_state_atomic(state)
    return jsonify({'status': 'success'})

@library_bp.route('/api/edit-button', methods=['GET'])
def get_edit_button():
    state = load_state()
    return jsonify({'status': 'success', 'edit_button': state.get('edit_button', {})})

@library_bp.route('/api/edit-button', methods=['POST'])
def save_edit_button():
    from config import _state_lock, _load_state_unlocked, _write_state_atomic
    data = request.json or {}
    eb = data.get('edit_button')
    if eb is None:
        return jsonify({'status': 'error', 'message': 'Missing edit_button'}), 400
    if eb.get('corner') not in ('top_left', 'top_right', 'bottom_left', 'bottom_right'):
        return jsonify({'status': 'error', 'message': 'Invalid corner'}), 400
    with _state_lock:
        state = _load_state_unlocked()
        # Claiming this corner evicts whatever badge feature was there.
        corner = eb['corner']
        badges = state.get('card_badges') or {}
        if (badges.get('slots') or {}).get(corner):
            badges['slots'][corner] = None
            state['card_badges'] = badges
        state['edit_button'] = eb
        _write_state_atomic(state)
    return jsonify({'status': 'success'})

@library_bp.route('/api/available-platforms')
def get_available_platforms():
    """Platforms actually present in the library right now -- distinct from
    platform_labels(), which lists every core/plugin platform whether or not
    any games use it (e.g. an installed-but-unused emulator platform). Used
    by the Card Badges modal so the platform icon list isn't cluttered with
    dozens of irrelevant emulator entries."""
    from plugins import platform_labels as _platform_labels
    db = get_db()
    rows = db.execute("SELECT DISTINCT platform as p FROM games").fetchall()
    db.close()
    plat_order = list(_platform_labels().keys())
    platforms = sorted(
        {r['p'] for r in rows if r['p']},
        key=lambda p: plat_order.index(p) if p in plat_order else 99
    )
    return jsonify({'status': 'success', 'platforms': platforms})

@library_bp.route('/api/pick-screen-color')
def pick_screen_color():
    """Fullscreen eyedropper overlay. Spawns color_picker.py as a subprocess
    so each invocation gets a clean Tk instance."""
    import subprocess, sys
    if getattr(sys, 'frozen', False):
        script = os.path.join(sys._MEIPASS, 'color_picker.py')
    else:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'color_picker.py')
    log.info('pick_screen_color: launching %s', script)
    try:
        r = subprocess.run([sys.executable, script],
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        log.warning('pick_screen_color: timed out')
        return jsonify({'cancelled': True})
    except Exception:
        log.exception('pick_screen_color: subprocess error')
        return jsonify({'error': 'picker failed'}), 500
    log.info('pick_screen_color: exit=%d stdout=%r stderr=%r',
                    r.returncode, r.stdout.strip(), r.stderr.strip()[:200])
    color = r.stdout.strip()
    if r.returncode == 0 and color:
        return jsonify({'color': color})
    return jsonify({'cancelled': True})

@library_bp.route('/api/export-filter', methods=['POST'])
def export_filter_file():
    data = request.json
    path = validate_user_path((data.get('path') or '').strip())
    name = (data.get('name') or '').strip()
    tree = data.get('tree')
    if not path or not name or not tree:
        return jsonify({'status': 'error', 'message': 'Missing fields.'}), 400
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'playdate_filter': {'name': name, 'tree': tree}}, f, indent=2)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@library_bp.route('/api/read-filter-file', methods=['POST'])
def read_filter_file():
    path = validate_user_path((request.json.get('path') or '').strip())
    if not path or not os.path.exists(path):
        return jsonify({'status': 'error', 'message': 'File not found.'}), 400
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        pf   = data.get('playdate_filter', {})
        name = (pf.get('name') or '').strip()
        tree = pf.get('tree')
        if not name or not tree:
            return jsonify({'status': 'error', 'message': 'Invalid filter file.'}), 400
        return jsonify({'status': 'success', 'name': name, 'tree': tree})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Could not read file: {e}'}), 500

@library_bp.route('/api/delete-game/<int:appid>', methods=['DELETE'])
def delete_game(appid):
    data      = request.json or {}
    blacklist = data.get('blacklist', False)
    name      = data.get('name', '')
    try:
        # Look up platform/platform_id before deleting (needed for blacklist)
        db = get_db()
        row = db.execute(
            "SELECT platform, platform_id FROM games WHERE appid = ?", (appid,)
        ).fetchone()
        platform    = row['platform'] if row else None
        platform_id = row['platform_id'] if row else None

        # Delete DB entry
        db.execute("DELETE FROM games WHERE appid = ?", (appid,))
        db.commit()
        db.close()
        from utils import invalidate_unique_cache
        invalidate_unique_cache()

        # Delete all cached images
        safe_id = str(int(appid))
        for subdir in ('vertical', 'horizontal', 'icons'):
            img_path = os.path.join(BASE_DIR, 'static', 'img', 'library', subdir, safe_id + '.jpg')
            if os.path.exists(img_path):
                os.remove(img_path)

        # Optionally blacklist
        if blacklist:
            add_to_blacklist(appid, name, platform_id=platform_id, platform=platform)

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@library_bp.route('/api/bulk-delete', methods=['POST'])
def bulk_delete():
    data    = request.json or {}
    appids  = data.get('appids', [])
    if not appids:
        return jsonify({"status": "error", "message": "No appids provided."}), 400
    try:
        placeholders = ','.join('?' * len(appids))
        db = get_db()
        db.execute(f"DELETE FROM games WHERE appid IN ({placeholders})", appids)
        db.commit()
        db.close()

        # Delete all cached images
        deleted_imgs = 0
        for appid in appids:
            safe_id = str(int(appid))
            for subdir in ('vertical', 'horizontal', 'icons'):
                img_path = os.path.join(BASE_DIR, 'static', 'img', 'library', subdir, safe_id + '.jpg')
                if os.path.exists(img_path):
                    os.remove(img_path)
                    deleted_imgs += 1

        return jsonify({"status": "success", "deleted": len(appids), "images_removed": deleted_imgs})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@library_bp.route('/api/store-names-pending', methods=['GET'])
def store_names_pending():
    pending_path = os.path.join(BASE_DIR, 'store_names_pending.json')
    if not os.path.exists(pending_path):
        return jsonify({'items': []})
    try:
        with open(pending_path) as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        log.error(f"store_names_pending: {e}")
        return jsonify({'items': []})

@library_bp.route('/api/store-names-apply', methods=['POST'])
def store_names_apply():
    from database import update_game_data
    body = request.get_json(silent=True) or {}
    appids_to_apply = {int(a) for a in body.get('appids', [])}
    dismiss_all = body.get('dismiss', False)
    pending_path = os.path.join(BASE_DIR, 'store_names_pending.json')
    try:
        if not os.path.exists(pending_path):
            return jsonify({'ok': True, 'remaining': 0})
        with open(pending_path) as f:
            data = json.load(f)
        items = data.get('items', [])
        for item in items:
            if item['appid'] in appids_to_apply:
                update_game_data(item['appid'], name=item['new_name'])
        if dismiss_all:
            os.remove(pending_path)
            return jsonify({'ok': True, 'remaining': 0})
        remaining = [item for item in items if item['appid'] not in appids_to_apply]
        if remaining:
            with open(pending_path, 'w') as f:
                json.dump({'items': remaining}, f, indent=2)
        else:
            os.remove(pending_path)
        return jsonify({'ok': True, 'remaining': len(remaining)})
    except Exception as e:
        log.error(f"store_names_apply: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@library_bp.route('/api/blacklist', methods=['GET'])
def blacklist_get():
    try:
        return jsonify({"status": "success", "entries": get_blacklist()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@library_bp.route('/api/blacklist/add', methods=['POST'])
def blacklist_add():
    data  = request.json or {}
    appid = data.get('appid')
    name  = data.get('name', '')
    if not appid:
        return jsonify({"status": "error", "message": "No appid provided."}), 400
    try:
        add_to_blacklist(appid, name)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@library_bp.route('/api/blacklist/remove', methods=['POST'])
def blacklist_remove():
    data  = request.json or {}
    appid = data.get('appid')
    if not appid:
        return jsonify({"status": "error", "message": "No appid provided."}), 400
    try:
        remove_from_blacklist(appid)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@library_bp.route('/api/blacklist/bulk-remove', methods=['POST'])
def blacklist_bulk_remove():
    data   = request.json or {}
    appids = data.get('appids') or []
    if not appids:
        return jsonify({"status": "error", "message": "No appids provided."}), 400
    try:
        for appid in appids:
            remove_from_blacklist(appid)
        return jsonify({"status": "success", "count": len(appids)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Steam gives no structured signal for this (Store API `type` and appinfo.vdf's
# common.type both just say "Game" for beta clients, movie entries, etc. -- confirmed
# by hand against real examples), so title text is the only lever. Matching is
# intentionally broad since results are only ever a human-reviewed suggestion list,
# never auto-applied.
# Title patterns that flag a library entry as probably-not-a-real-game. Applied
# to every platform (Steam betas, Humble sneak-peek/prototype drops, plugin
# soundtrack/dev-kit entries), so the scan is name-only and each hit is
# reviewed before removal.
_JUNK_PATTERNS = [
    (re.compile(r'\bbeta\b', re.I), 'beta'),
    (re.compile(r'\balpha\b', re.I), 'alpha'),
    (re.compile(r'\b(public|closed|open)\s+test(ing)?\b', re.I), 'public/closed test'),
    (re.compile(r'\bunstable\b', re.I), 'unstable/test branch'),
    (re.compile(r'\bplayable\s+teaser\b', re.I), 'playable teaser'),
    (re.compile(r"\bfriend'?s\s+pass\b", re.I), "friend's pass"),
    (re.compile(r'\bkey\s+only\b', re.I), 'key-only bundle placeholder'),
    (re.compile(r'-\s*multiplayer\s*$', re.I), 'multiplayer-only companion app'),
    (re.compile(r'\bthe\s+movie\b', re.I), 'documentary/movie'),
    (re.compile(r'\bdemo\b', re.I), 'demo'),
    (re.compile(r'\btrial\b', re.I), 'trial'),
    (re.compile(r'\bprototype\b', re.I), 'prototype'),
    (re.compile(r'\bsneak\s?peek\b', re.I), 'sneak peek'),
    (re.compile(r'\bsource\s?code\b', re.I), 'source code'),
    (re.compile(r'\b(dev|mod)\s?kit\b', re.I), 'dev/mod kit'),
    (re.compile(r'\bSDK\b'), 'SDK'),
    (re.compile(r'\bsoundtrack\b', re.I), 'soundtrack'),
    (re.compile(r'\b(art\s?book|artbook)\b', re.I), 'artbook'),
    (re.compile(r'\bOST\b'), 'soundtrack (OST)'),
]

# Back-compat alias for older state.
_STEAM_JUNK_PATTERNS = _JUNK_PATTERNS


def _junk_match_reasons(name):
    return [label for pat, label in _JUNK_PATTERNS if pat.search(name or '')]


@library_bp.route('/api/steam-junk-scan', methods=['GET'])
def steam_junk_scan():
    from scrapers import fetch_owned_appids
    from config import get_active_account
    try:
        state     = load_state()
        dismissed = {int(a) for a in (state.get('steam_junk_whitelist') or [])}
        db = get_db()
        try:
            blacklisted = {row[0] for row in db.execute(
                "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
            ).fetchall()}
            rows = db.execute(
                "SELECT appid, name, platform, is_free, playtime_forever FROM games ORDER BY name"
            ).fetchall()
        finally:
            db.close()

        steam_rows = [r for r in rows if (r['platform'] or 'steam') == 'steam']
        not_owned_ids = set()

        # Step 1: ownership check against the Steam Web API (Steam only; skipped,
        # not errored, when no API key is configured -- same "optional key"
        # convention as populate).
        ownership = {'checked': False, 'error': None}
        account = get_active_account()
        if account and account.get('api_key'):
            result = fetch_owned_appids()
            if result['status'] == 'success':
                ownership['checked'] = True
                owned = result['appids']
                for row in steam_rows:
                    appid = row['appid']
                    if str(appid) in blacklisted or appid in dismissed:
                        continue
                    if appid in owned:
                        continue
                    # The bulk call excludes free-to-play games below Valve's
                    # undocumented "played enough to list" threshold even when
                    # genuinely owned, so absence alone isn't reliable for
                    # them -- only trust it once there's enough locally-known
                    # playtime that a still-missing entry is more likely a
                    # real removal than an under-threshold visibility gap.
                    # (No live playtime exists for an absent appid -- this is
                    # the only data source available for that case.)
                    if row['is_free'] and (row['playtime_forever'] or 0) <= 5:
                        continue
                    not_owned_ids.add(appid)
            else:
                ownership['error'] = result['message']

        owned_candidates = [{'appid': r['appid'], 'name': r['name']} for r in steam_rows if r['appid'] in not_owned_ids]

        # Step 2: local title-pattern heuristics, every platform (always
        # available). A game already flagged as no-longer-owned doesn't also
        # need blacklisting -- it can't be re-added by Populate since it's off
        # the account entirely -- so it's excluded here rather than double-listed.
        pattern_candidates = []
        for row in rows:
            appid = row['appid']
            if str(appid) in blacklisted or appid in dismissed or appid in not_owned_ids:
                continue
            reasons = _junk_match_reasons(row['name'])
            if reasons:
                pattern_candidates.append({
                    'appid': appid, 'name': row['name'],
                    'platform': row['platform'] or 'steam', 'reasons': reasons,
                })

        return jsonify({
            'status': 'success',
            'owned_candidates': owned_candidates,
            'pattern_candidates': pattern_candidates,
            'ownership': ownership,
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@library_bp.route('/api/steam-junk-scan/blacklist', methods=['POST'])
def steam_junk_scan_blacklist():
    data   = request.json or {}
    appids = data.get('appids') or []
    if not appids:
        return jsonify({"status": "error", "message": "No appids provided."}), 400
    try:
        placeholders = ','.join('?' * len(appids))
        db   = get_db()
        rows = db.execute(
            f"SELECT appid, name, platform, platform_id FROM games WHERE appid IN ({placeholders})", appids
        ).fetchall()
        info_by_id = {r['appid']: r for r in rows}
        db.execute(f"DELETE FROM games WHERE appid IN ({placeholders})", appids)
        db.commit()
        db.close()

        for appid in appids:
            safe_id = str(int(appid))
            for subdir in ('vertical', 'horizontal', 'icons'):
                img_path = os.path.join(BASE_DIR, 'static', 'img', 'library', subdir, safe_id + '.jpg')
                if os.path.exists(img_path):
                    os.remove(img_path)
            info = info_by_id.get(appid)
            add_to_blacklist(appid, info['name'] if info else '',
                              platform_id=info['platform_id'] if info else None,
                              platform=info['platform'] if info else None)

        from utils import invalidate_unique_cache
        invalidate_unique_cache()
        return jsonify({"status": "success", "count": len(appids)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@library_bp.route('/api/steam-junk-scan/whitelist', methods=['POST'])
def steam_junk_scan_whitelist():
    from config import _state_lock, _load_state_unlocked, _write_state_atomic
    data   = request.json or {}
    appids = data.get('appids') or []
    if not appids:
        return jsonify({"status": "error", "message": "No appids provided."}), 400
    try:
        with _state_lock:
            state = _load_state_unlocked()
            existing = {int(a) for a in (state.get('steam_junk_whitelist') or [])}
            existing.update(int(a) for a in appids)
            state['steam_junk_whitelist'] = sorted(existing)
            _write_state_atomic(state)
        return jsonify({"status": "success", "count": len(appids)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@library_bp.route('/api/steam-junk-scan/deep', methods=['GET'])
def library_junk_deep_scan():
    """Ask each plugin that implements scan_junk() which of its own games its
    filters would now reject (DLC, soundtracks, non-game apps, dev kits) --
    catches clean-named junk the title patterns can't. Each plugin call may hit
    its store API, so this is opt-in (a button), not part of the fast scan."""
    import plugins as _plugins
    state     = load_state()
    dismissed = {int(a) for a in (state.get('steam_junk_whitelist') or [])}

    db = get_db()
    try:
        blacklisted = {row[0] for row in db.execute(
            "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
        ).fetchall()}
    finally:
        db.close()

    results, errors = [], []
    for pid, plugin in _plugins.loaded().items():
        fn = getattr(plugin, 'scan_junk', None)
        if not callable(fn):
            continue
        try:
            for item in (fn() or []):
                appid = int(item['appid'])
                if appid in dismissed or str(appid) in blacklisted:
                    continue
                results.append({
                    'appid': appid,
                    'name': item.get('name') or '',
                    'platform': getattr(plugin, 'platform', pid),
                    'reason': item.get('reason') or 'not a game',
                })
        except Exception as e:
            log.warning(f"scan_junk ({pid}): {e}")
            errors.append({'platform': getattr(plugin, 'platform', pid), 'error': str(e)})

    results.sort(key=lambda r: (r['platform'], r['name'].lower()))
    return jsonify({'status': 'success', 'results': results, 'errors': errors})

@library_bp.route('/api/detect-duplicates', methods=['POST'])
def detect_duplicates():
    try:
        from database import auto_detect_duplicates, invalidate_dup_cache
        from plugins import get_platform_priority
        saved    = load_state().get('platform_priority') or []
        dynamic  = get_platform_priority()
        priority = saved + [p for p in dynamic if p not in saved]
        count = auto_detect_duplicates(platform_priority=priority)
        invalidate_dup_cache()
        return jsonify({'status': 'ok', 'detected': count})
    except Exception as e:
        log.error(f"detect-duplicates failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500
