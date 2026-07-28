"""Whitelist validator for user-supplied WHERE clauses (library.is_safe_sql)."""
import pytest

from library import is_safe_sql, _auto_cast_int_division


ACCEPTED = [
    "playtime_forever > 60",
    "completion_status = 'Beaten' AND review_percentage >= 80",
    "lower(name) LIKE '%portal%'",
    "name = 'Won''t Play'",                       # escaped quote inside literal
    "release_date IS NOT NULL AND release_date != 0",
    "strftime('%Y', release_date, 'unixepoch') = '2019'",
    "coalesce(hltb_main, 0) BETWEEN 60 AND 600",
    "(tags LIKE '%,Action,%' OR tags LIKE '%,Indie,%')",
    "CAST(unlocked_achievements AS REAL) / total_achievements >= 0.5",
    "name = 'DROP TABLE games'",                  # dangerous text inside a literal is fine
    "total_reviews > 100 AND NOT is_free",
]

REJECTED = [
    "",
    "   ",
    "DROP TABLE games",
    "DELETE FROM games",
    "name = 'a'; DROP TABLE games",               # semicolon
    "name = 'a' UNION SELECT * FROM games",       # union/select/from
    "SELECT * FROM games",
    "randomblob(1000000) IS NOT NULL",            # non-whitelisted function
    "load_extension('evil')",
    "sneaky_column = 1",                          # unknown column
    "ATTACH DATABASE 'x' AS y",
    "PRAGMA journal_mode",
    '"name" = \'x\'',                             # double-quoted identifier
    "appid GLOB '1*'",                            # glob not whitelisted
]


@pytest.mark.parametrize("sql", ACCEPTED)
def test_accepts_safe_expressions(sql):
    assert is_safe_sql(sql) is True


@pytest.mark.parametrize("sql", REJECTED)
def test_rejects_unsafe_expressions(sql):
    assert is_safe_sql(sql) is False


def test_auto_cast_int_division_casts_integer_columns():
    out = _auto_cast_int_division("unlocked_achievements / total_achievements >= 0.5")
    assert out.startswith("CAST(unlocked_achievements AS REAL) /")


def test_auto_cast_int_division_leaves_other_columns_alone():
    sql = "hltb_main / 60 > 5"
    assert _auto_cast_int_division(sql) == sql
