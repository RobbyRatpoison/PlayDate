import logging
import time
from config import load_state, BUILTIN_FILTERS, resolve_outline_rule_where
from database import get_db
from utils import get_all_unique_groups, get_all_unique_tags
from flask import Blueprint, jsonify, render_template, request, redirect, url_for

log = logging.getLogger(__name__)

library_bp = Blueprint('library', __name__)


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
# Dict values may be a plain string (direction-agnostic) or {'asc': expr, 'desc': expr}
# for columns where ascending and descending use different aggregations.
_HLTB_MIN_EXPR = (
    "CASE WHEN NULLIF(hltb_main, 0) IS NULL AND NULLIF(hltb_extras, 0) IS NULL AND NULLIF(hltb_completionist, 0) IS NULL THEN NULL "
    "ELSE MIN(COALESCE(NULLIF(hltb_main, 0), 999999999), COALESCE(NULLIF(hltb_extras, 0), 999999999), COALESCE(NULLIF(hltb_completionist, 0), 999999999)) "
    "END"
)
# DESC uses MAX so "longest game" means the most content, not just the longest main story.
# COALESCE(NULLIF(col,0), 0) treats zero/null as 0 so they lose to any real value.
_HLTB_MAX_EXPR = (
    "CASE WHEN NULLIF(hltb_main, 0) IS NULL AND NULLIF(hltb_extras, 0) IS NULL AND NULLIF(hltb_completionist, 0) IS NULL THEN NULL "
    "ELSE MAX(COALESCE(NULLIF(hltb_main, 0), 0), COALESCE(NULLIF(hltb_extras, 0), 0), COALESCE(NULLIF(hltb_completionist, 0), 0)) "
    "END"
)
VIRTUAL_SORT_COLS = {
    'hltb_min': {'asc': _HLTB_MIN_EXPR, 'desc': _HLTB_MAX_EXPR},
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
        _vcol = VIRTUAL_SORT_COLS[sort_col]
        if isinstance(_vcol, dict):
            _expr = _vcol['desc'] if sort_ord == 'DESC' else _vcol['asc']
        else:
            _expr = _vcol
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
            tree_sql = build_tree_sql(filter_tree, params)
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
    from utils import get_all_unique_tags, get_all_unique_groups, get_all_unique_genres, get_all_unique_categories, invalidate_unique_cache
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
        return jsonify({"status": "error", "message": f"Column is not editable."}), 400
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
