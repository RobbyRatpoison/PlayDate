from config import load_state, BUILTIN_FILTERS
from database import get_db
from utils import get_all_unique_groups, get_all_unique_tags
from flask import Blueprint, jsonify, render_template, request, redirect, url_for

library_bp = Blueprint('library', __name__)

# ── SQL builder ─────────────────────────────────────────────────────────────

SAFE_COLUMNS = {
    'appid', 'name', 'completion_status', 'installed', 'release_date', 'date_added',
    'last_played', 'playtime_forever', 'review_percentage', 'weighted_percentage',
    'review_score', 'vertical_art_source', 'horizontal_art_source', 'icon_source',
    'groups', 'tags', 'developers', 'publishers',
    'total_reviews', 'positive_reviews', 'unlocked_achievements', 'total_achievements',
    'genres', 'categories', 'is_free'
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
    # so their contents don't trip up the keyword check
    scrubbed = _re.sub(r"'[^']*'", 'STRING', sql)
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
    sql = _re.sub(r'(?i)^\s*SELECT\s+\*\s+FROM\s+\w+\s+WHERE\s+', '', sql)
    sql = _re.sub(r'(?i)\s+ORDER\s+BY\s+.+$', '', sql)
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

    # Date columns with LIKE — user provides their own pattern (e.g. %-03-%)
    if col in DATE_COLUMNS and op == 'LIKE':
        params.append(val)  # pass raw, user owns wildcards
        return f"{col} LIKE ?"

    if op == '=':
        params.append(val)
        return f"{col} = ? COLLATE NOCASE"
    elif op == '!=':
        params.append(val)
        return f"{col} != ? COLLATE NOCASE"
    elif op == 'LIKE':
        params.append(f"%{val}%")
        return f"{col} LIKE ?"
    elif op == 'NOT LIKE':
        params.append(f"%{val}%")
        return f"{col} NOT LIKE ?"
    elif op in ('>', '<', '>=', '<='):
        params.append(val)
        return f"{col} {op} ?"
    elif op == 'STRFTIME_MONTH':
        params.append(val.zfill(2))
        return f"strftime('%m', {col}) = ?"
    elif op == 'STRFTIME_DAY':
        params.append(val.zfill(2))
        return f"strftime('%d', {col}) = ?"
    elif op == 'STRFTIME_YEAR':
        params.append(val)
        return f"strftime('%Y', {col}) = ?"
    elif op == 'IS NULL':
        return f"({col} IS NULL OR {col} = '')"
    elif op == 'IS NOT NULL':
        return f"({col} IS NOT NULL AND {col} != '')"
    else:
        params.append(val)
        return f"{col} = ?"

def build_tree_sql(node, params):
    """Recursively build SQL from a filter tree node."""
    node_type = node.get('type', 'condition')

    if node_type == 'condition':
        return build_condition_sql(node, params)

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
    # Whitelist sort column
    if sort_col not in SAFE_COLUMNS:
        sort_col = 'name'
    if sort_ord not in ('ASC', 'DESC'):
        sort_ord = 'ASC'

    params = []
    where = "1=1"

    filter_tree = state.get('filter_tree')

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

    query = f"SELECT * FROM games WHERE {where} ORDER BY {sort_col} {sort_ord}"

    sql_error = None
    try:
        rows = db.execute(query, params).fetchall()
        games = [dict(row) for row in rows]
    except Exception as e:
        sql_error = str(e)
        try:
            rows = db.execute(f"SELECT * FROM games ORDER BY {sort_col} {sort_ord}").fetchall()
            games = [dict(row) for row in rows]
        except Exception:
            games = []
    db.close()

    # Drop icon_hash — it's a raw Steam hash used only server-side during scraping,
    # never referenced in browser JS, so no need to ship it to every page load.
    for g in games:
        g.pop('icon_hash', None)

    groups = get_all_unique_groups()
    tags   = get_all_unique_tags()

    return render_template('library.html', games=games, state=state,
                           unique_tags=tags, unique_groups=groups,
                           sql_error=sql_error, builtin_filters=BUILTIN_FILTERS)


@library_bp.route('/update_game', methods=['POST'])
def update_game():
    data = request.form.to_dict()
    appid = data.pop('edit-appid')
    if 'installed' in data:
        data['installed'] = 1 if data['installed'] == '1' else 0
    from database import update_game_data
    from utils import get_all_unique_tags, get_all_unique_groups, get_all_unique_genres, get_all_unique_categories
    try:
        update_game_data(appid, **data)
        db = get_db()
        row = db.execute("SELECT * FROM games WHERE appid = ?", (appid,)).fetchone()
        db.close()
        game = dict(row) if row else {"appid": appid}
        return jsonify({
            "status": "success",
            "game": game,
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

    allowed_columns = {
        'completion_status', 'tags', 'groups', 'developers', 'publishers',
        'release_date', 'review_score', 'review_percentage', 'weighted_percentage',
        'total_reviews', 'positive_reviews', 'playtime_forever', 'date_added',
        'installed', 'vertical_art_source', 'horizontal_art_source', 'icon_source',
        'unlocked_achievements', 'total_achievements',
        'genres', 'categories', 'is_free'
    }
    if column not in allowed_columns:
        return jsonify({"status": "error", "message": f"Column '{column}' is not editable."}), 400
    if not value and mode != 'remove':
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

    try:
        db = get_db()

        if mode == 'replace':
            db.execute(f"UPDATE games SET {column} = ? WHERE {where}", [value] + params)
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
                    updated += 1
            db.commit()
            db.close()
            return jsonify({"status": "success", "updated": updated})

        db.close()
        return jsonify({"status": "error", "message": "Invalid mode."}), 400

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
