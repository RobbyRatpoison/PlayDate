"""Filter tree → SQL compilation (library.build_tree_sql / build_condition_sql)."""
import sqlite3

import pytest

from library import build_tree_sql, build_condition_sql


def cond(column, operator, value, **extra):
    return {'type': 'condition', 'column': column, 'operator': operator, 'value': value, **extra}


def group(logic, *items):
    return {'type': 'group', 'logic': logic, 'items': list(items)}


# ── SQL shape ────────────────────────────────────────────────────────────────

def test_like_condition():
    params = []
    sql = build_tree_sql(cond('name', 'LIKE', 'portal'), params)
    assert sql == "name LIKE ?"
    assert params == ['%portal%']


def test_equals_is_case_insensitive():
    params = []
    sql = build_tree_sql(cond('completion_status', '=', 'Beaten'), params)
    assert sql == "completion_status = ? COLLATE NOCASE"
    assert params == ['Beaten']


def test_unknown_column_is_neutralized():
    params = []
    assert build_tree_sql(cond('evil; DROP TABLE games', '=', 'x'), params) == '1=1'
    assert params == []


def test_empty_value_is_neutralized():
    params = []
    assert build_tree_sql(cond('name', 'LIKE', ''), params) == '1=1'
    assert params == []


def test_comma_list_column_uses_exact_item_match():
    params = []
    sql = build_tree_sql(cond('tags', 'LIKE', 'Action'), params)
    assert sql == "',' || tags || ',' LIKE ?"
    assert params == ['%,Action,%']


def test_multi_value_chip_list_ors_items():
    params = []
    sql = build_tree_sql(cond('tags', 'LIKE', ['Action', 'Indie']), params)
    assert sql == "(',' || tags || ',' LIKE ? OR ',' || tags || ',' LIKE ?)"
    assert params == ['%,Action,%', '%,Indie,%']


def test_multi_value_chip_list_not_like_ands_items():
    params = []
    sql = build_tree_sql(cond('tags', 'NOT LIKE', ['Action', 'Indie']), params)
    assert sql == "(',' || tags || ',' NOT LIKE ? AND ',' || tags || ',' NOT LIKE ?)"
    assert params == ['%,Action,%', '%,Indie,%']


def test_multi_value_list_rejected_for_non_list_columns():
    params = []
    assert build_tree_sql(cond('name', 'LIKE', ['a', 'b']), params) == '1=1'


def test_column_vs_column_comparison():
    params = []
    sql = build_tree_sql(cond('unlocked_achievements', '=', '', value_col='total_achievements'), params)
    assert sql == "unlocked_achievements = total_achievements"
    assert params == []


def test_column_vs_column_rejects_unsafe_target():
    params = []
    assert build_tree_sql(cond('appid', '=', '', value_col='(SELECT 1)'), params) == '1=1'


def test_date_equals_expands_to_day_range():
    params = []
    sql = build_tree_sql(cond('release_date', '=', '2024-01-01'), params)
    assert sql == "(release_date >= ? AND release_date < ?)"
    assert params[1] - params[0] == 86400


def test_strftime_month_zero_pads():
    params = []
    sql = build_tree_sql(cond('release_date', 'STRFTIME_MONTH', '3'), params)
    assert "strftime('%m', release_date, 'unixepoch') = ?" in sql
    assert params == ['03']


def test_is_null_on_date_treats_zero_as_null():
    params = []
    assert build_tree_sql(cond('release_date', 'IS NULL', ''), params) == \
        "(release_date IS NULL OR release_date = 0)"


def test_is_null_on_text_treats_empty_as_null():
    params = []
    assert build_tree_sql(cond('developers', 'IS NULL', ''), params) == \
        "(developers IS NULL OR developers = '')"


def test_group_and_or_nesting():
    params = []
    tree = group(
        'AND',
        cond('platform', '=', 'steam'),
        group('OR', cond('completion_status', '=', 'Beaten'),
                    cond('completion_status', '=', 'Completed')),
    )
    sql = build_tree_sql(tree, params)
    assert sql == ("(platform = ? COLLATE NOCASE AND "
                   "(completion_status = ? COLLATE NOCASE OR completion_status = ? COLLATE NOCASE))")
    assert params == ['steam', 'Beaten', 'Completed']


def test_group_with_single_effective_item_has_no_parens():
    params = []
    tree = group('AND', cond('name', 'LIKE', 'a'), cond('bogus_col', '=', 'x'))
    assert build_tree_sql(tree, params) == "name LIKE ?"


def test_empty_group_is_neutral():
    assert build_tree_sql(group('OR'), []) == '1=1'


def test_invalid_logic_falls_back_to_and():
    params = []
    tree = group('EVIL', cond('name', 'LIKE', 'a'), cond('appid', '>', '10'))
    assert ' AND ' in build_tree_sql(tree, params)


def test_appid_list_drops_non_integers():
    params = []
    node = {'type': 'appid_list', 'appids': [10, 'DROP TABLE', 20, None, 3.5]}
    assert build_tree_sql(node, params) == "appid IN (10,20)"
    assert params == []


def test_appid_list_empty_is_neutral():
    assert build_tree_sql({'type': 'appid_list', 'appids': ['x']}, []) == '1=1'


def test_custom_expr_safe_passes_through():
    params = []
    sql = build_tree_sql({'type': 'custom_expr', 'sql': 'playtime_forever > 60'}, params)
    assert sql == "(playtime_forever > 60)"


def test_custom_expr_unsafe_is_neutralized():
    params = []
    assert build_tree_sql({'type': 'custom_expr', 'sql': 'DROP TABLE games'}, params) == '1=1'


def test_unknown_node_type_is_neutral():
    assert build_tree_sql({'type': 'mystery'}, []) == '1=1'


# ── Execution against a real SQLite schema ───────────────────────────────────

@pytest.fixture
def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE games (
            appid INTEGER PRIMARY KEY, name TEXT, tags TEXT,
            completion_status TEXT, playtime_forever INTEGER,
            release_date INTEGER, unlocked_achievements INTEGER,
            total_achievements INTEGER, platform TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (1, 'Portal',      'Action,Puzzle',     'Beaten',       300, 1191988800, 10, 15, 'steam'),
            (2, 'Actionball',  'Action RPG,Casual', 'Never Played', 0,   1600000000, 0,  10, 'steam'),
            (3, 'Slay the Ire','Roguelike',         'Unfinished',   50,  1500000000, 5,  10, 'gog'),
        ],
    )
    yield conn
    conn.close()


def run_tree(db, tree):
    params = []
    where = build_tree_sql(tree, params)
    rows = db.execute(f"SELECT appid FROM games WHERE {where}", params).fetchall()
    return sorted(r['appid'] for r in rows)


def test_exec_tag_item_match_ignores_partial_matches(db):
    # 'Action' must not match the 'Action RPG' tag.
    assert run_tree(db, cond('tags', 'LIKE', 'Action')) == [1]


def test_exec_or_group(db):
    tree = group('OR', cond('completion_status', '=', 'Beaten'),
                       cond('platform', '=', 'gog'))
    assert run_tree(db, tree) == [1, 3]


def test_exec_custom_expr_auto_casts_integer_division(db):
    # 5/10 must compare as 0.5, not integer-divide to 0.
    tree = {'type': 'custom_expr',
            'sql': 'unlocked_achievements / total_achievements >= 0.5 AND total_achievements > 0'}
    assert run_tree(db, tree) == [1, 3]
