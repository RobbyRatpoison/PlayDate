"""PAGYWOSG category name → op classification (pagywosg.classify_category)."""
import pagywosg
from pagywosg import classify_category, _year_start_ts


def clf(base, base_appids=None, ga=None, wl=None, santa=None):
    return classify_category(base, base_appids or {}, ga or {}, wl or {}, santa or {})


def one(base, **kw):
    results = clf(base, **kw)
    assert len(results) == 1, results
    return results[0]


def assert_cond(res, col, op, val):
    assert res['type'] == 'cond'
    assert res['col'] == col
    assert res['op'] == op
    assert res['val'] == val


# ── Tags ─────────────────────────────────────────────────────────────────────

def test_tag_modern_naming():
    assert one('Tag Roguelike') == {'type': 'tag', 'tag': 'Roguelike', 'reason': 'tag'}


def test_tag_legacy_naming():
    assert one('Roguelike tag') == {'type': 'tag', 'tag': 'Roguelike', 'reason': 'tag'}


def test_tag_substring_any_kind():
    assert_cond(one('Strategy tag (any kind of)'), 'tags', 'tag_substring', 'Strategy')


def test_exact_tag_count():
    assert_cond(one('5 tags'), 'tags', 'tag_count_eq', '5')


# ── Release dates ────────────────────────────────────────────────────────────

def test_released_in_month():
    assert_cond(one('Games released in March'), 'release_date', 'month_is', '3')


def test_released_in_year():
    assert_cond(one('Games released in 2019'), 'release_date', 'year_is', '2019')


def test_released_on_day():
    assert_cond(one('Games released on the 25th'), 'release_date', 'day_is', '25')


def test_released_on_weekday():
    assert_cond(one('Games released on a Friday'), 'release_date', 'weekday_is', '5')


def test_released_on_nth_weekday_takes_precedence_over_day():
    assert_cond(one('Games released on the 2nd Thursday'), 'release_date', 'nth_weekday', '2:4')


def test_released_before_year():
    assert_cond(one('Games released before 2010'),
                'release_date', 'lt', str(_year_start_ts(2010)))


def test_released_after_year():
    assert_cond(one('Games released after 2015'),
                'release_date', 'gte', str(_year_start_ts(2016)))


# ── Titles ───────────────────────────────────────────────────────────────────

def test_starts_with_letter_list():
    res = one('Games starting with the letter A, B or C')
    assert res['op'] == 'starts_with_any'
    assert res['val'] == ['A', 'B', 'C']


def test_quoted_word_in_title_is_whole_word():
    assert_cond(one('Games with the word "war" in their title'), 'name', 'title_word', 'war')


def test_quoted_substring_in_title():
    assert_cond(one('Games with "star" in their title'), 'name', 'contains', 'star')


def test_digit_in_title():
    assert_cond(one('Games with a 2 in their title'), 'name', 'contains', '2')


def test_quoted_prefix():
    assert_cond(one('Games with a "Super" prefix'), 'name', 'starts_with', 'Super')


def test_title_exact_length():
    assert_cond(one('Games with exactly 10 characters in the title'), 'name', 'length_eq', '10')


def test_special_characters_tolerates_source_typo():
    assert_cond(one('Games with special charaters'), 'name', 'has_special_char', '1')
    assert_cond(one('Games with special characters'), 'name', 'has_special_char', '1')


def test_all_caps():
    assert_cond(one('Game names with only capital letters'), 'name', 'all_caps', '1')


def test_named_punctuation():
    assert_cond(one('Game names with question marks'), 'name', 'contains', '?')


def test_single_word_title():
    assert_cond(one('Title with only one word'), 'name', 'single_word', '1')


def test_title_word_list_splits_on_commas_and_or():
    results = clf('Game title with Winter, Snow or Ice')
    assert [r['val'] for r in results] == ['Winter', 'Snow', 'Ice']
    assert all(r['op'] == 'title_word' for r in results)


def test_word_in_title_phrasing_is_whole_word():
    assert_cond(one('Game with Book in the title'), 'name', 'title_word', 'Book')
    assert_cond(one('Game with Library in the title'), 'name', 'title_word', 'Library')


def test_word_in_name_phrasing_is_whole_word():
    assert_cond(one('Game with Dragon in the name'), 'name', 'title_word', 'Dragon')


def test_letters_all_required():
    assert_cond(one('Name including the letters R, U, O and K'),
                'name', 'contains_all', 'RUOK')


# ── Developers / publishers ──────────────────────────────────────────────────

def test_quoted_developer_substring():
    assert_cond(one('Games with "Valve" in their developer name'),
                'developers', 'contains', 'Valve')


# ── AppID ────────────────────────────────────────────────────────────────────

def test_appid_contains_digit():
    assert_cond(one('Games that contain a 4 in the app ID'), 'appid', 'contains', '4')


def test_appid_contains_number_via_steam_id_phrasing():
    assert_cond(one('Games with 42 in their steam ID'), 'appid', 'contains', '42')


def test_appid_contains_quoted_multidigit_via_with_phrasing():
    assert_cond(one('Games with "45" in their Steam AppID'), 'appid', 'contains', '45')


def test_appid_not_contains():
    assert_cond(one("Games that don't have the number 3 in their ID"),
                'appid', 'not_contains', '3')


def test_appid_digit_counts_or_grouped():
    results = clf('Games with two 3s or two 4s in appID')
    assert [(r['op'], r['val']) for r in results] == \
        [('digit_count_gte', '3:2'), ('digit_count_gte', '4:2')]


def test_appid_consecutive_identical_digits():
    assert_cond(one('AppID has two identical consecutive digits'),
                'appid', 'consecutive_repeat', '2')


# ── HLTB ─────────────────────────────────────────────────────────────────────

def test_hltb_under_hours_specific_field():
    assert_cond(one('Games under 10h HLTB main'), 'hltb_main', 'lt', '600')


def test_hltb_plus_hours_no_field_matches_all_three():
    results = clf('Games with 20h+ on HLTB')
    assert [(r['col'], r['op'], r['val']) for r in results] == [
        ('hltb_main', 'gte', '1200'),
        ('hltb_extras', 'gte', '1200'),
        ('hltb_completionist', 'gte', '1200'),
    ]


# ── Achievements ─────────────────────────────────────────────────────────────

def test_without_achievements_is_exact_zero():
    assert_cond(one('Games without achievements'), 'total_achievements', 'equals', '0')


def test_achievement_range_single_condition():
    assert_cond(one('Games with 1 to 12 achievements'),
                'total_achievements', 'range_incl', '1:12')


def test_achievement_range_normalizes_reversed_bounds():
    assert_cond(one('Games with 12 to 1 achievements'),
                'total_achievements', 'range_incl', '1:12')


def test_achievements_at_least():
    assert_cond(one('Games with at least 30 achievements'), 'total_achievements', 'gte', '30')


def test_achievements_fewer_than():
    assert_cond(one('Games with fewer than 10 achievements'), 'total_achievements', 'lt', '10')


def test_bare_achievement_count_is_exact():
    assert_cond(one('5 achievements'), 'total_achievements', 'equals', '5')


# ── Review tiers ─────────────────────────────────────────────────────────────

def test_review_tier_prefers_longest_match():
    # 'Very Positive' must not be misread as the shorter 'Positive' tier.
    assert_cond(one('Games with a Very Positive rating'),
                'review_score', 'equals', 'Very Positive')


# ── Special cases and fallbacks ──────────────────────────────────────────────

def test_gifter_categories_are_skipped():
    assert one('Chosen by gifter')['type'] == 'skip'


def test_icaio_giveaways_with_supplement():
    res = one('icaio has made a GA for this game', ga={10: 'Game A'})
    assert res['type'] == 'appids'
    assert res['auto'] is True
    assert res['force_wins'] is False
    assert res['appids'] == {10: 'Game A'}


def test_icaio_giveaways_without_supplement_skips():
    assert one('icaio has made a GA for this game')['type'] == 'skip'


def test_icaio_wishlist():
    res = one('A game from icaio wishlist', wl={20: 'Game B'})
    assert res['type'] == 'appids'
    assert res['auto'] is True


def test_santa_forces_wins_pool():
    res = one('Secret Santa gift', santa={30: 'Game C'})
    assert res['type'] == 'appids'
    assert res['force_wins'] is True


def test_unrecognized_with_verified_entries_falls_back():
    res = one('Completely unrecognizable category', base_appids={1: 'X'})
    assert res['type'] == 'appids'
    assert res['auto'] is False
    assert res['reason'] == 'verified_fallback'


def test_unrecognized_without_entries_skips():
    res = one('Completely unrecognizable category')
    assert res == {'type': 'skip', 'reason': 'unhandled'}


def test_every_cond_op_exists_in_registry():
    """Any op produced by the classifier must be in OP_REGISTRY (the shared
    vocabulary that SQL and JS consumers dispatch on)."""
    samples = [
        'Tag X', 'Strategy tag (any kind of)', 'Games released in March',
        'Games released in 2019', 'Games released on the 25th',
        'Games released on a Friday', 'Games released on the 2nd Thursday',
        'Games starting with the letter A or B', 'Games with a "Super" prefix',
        'Games with the word "war" in their title', 'Games with "star" in their title',
        'Games with exactly 10 characters in the title', 'Games with special characters',
        'Game names with only capital letters', 'Game names with question marks',
        'Title with only one word', 'Name including the letters A and B',
        'Games that contain a 4 in the app ID', "Games that don't have the number 3 in their ID",
        'Games with two 3s in appID', 'AppID has two identical consecutive digits',
        'Games under 10h HLTB main', 'Games without achievements',
        'Games with 1 to 12 achievements', 'Games with at least 30 achievements',
        '5 achievements', '5 tags', 'Games with a Very Positive rating',
        'Games released before 2010', 'Games released after 2015',
    ]
    for base in samples:
        for res in clf(base):
            if res['type'] == 'cond':
                assert res['op'] in pagywosg.OP_REGISTRY, (base, res['op'])
