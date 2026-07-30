"""PAGYWOSG event category classification and shared filter-condition vocabulary.

Categories are fetched live from https://pagywosg.xyz — there is no static
catalog of category names to enumerate. `classify_category()` pattern-matches
a category's free-text name into one of a small set of neutral "ops"
(month_is, contains, title_word, ...). OP_REGISTRY is the single source of
truth for what each op means downstream: the saved-filter-tree token it maps
to, the raw-SQL fragment used for the redundant-appid check, and the manual
filter-builder UI label. Everything in app.py and the PAGYWOSG templates that
needs to translate an op should go through this table instead of maintaining
its own copy.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from config import BASE_DIR

log = logging.getLogger(__name__)

pagywosg_bp = Blueprint('pagywosg', __name__)

_pagywosg_quals_cache = {}  # {event_id: (timestamp, data)}

_MIAM_SHEET_URL = ('https://docs.google.com/spreadsheets/d/'
                   '1xBd5rltp8WxQSnG2BVKPzr7quTLJCvCt2MaGCxzs-d8/export?format=csv')
_miam_cache = [None]  # [(timestamp, data)]

SUPPLEMENT_PATH = 'pagywosg_supplement.json'
SANTA_GIFTS_PATH = 'santa_gifts.json'
PERSONAL_DEFAULTS_PATH = 'pagywosg_personal_defaults.json'

_MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
}
_WEEKDAYS = {
    'sunday': 0, 'monday': 1, 'tuesday': 2, 'wednesday': 3, 'thursday': 4, 'friday': 5, 'saturday': 6
}
_WORDNUMS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
}
_ORDINALS = {
    '1st': 1, 'first': 1, '2nd': 2, 'second': 2, '3rd': 3, 'third': 3,
    '4th': 4, 'fourth': 4, '5th': 5, 'fifth': 5,
}
# Steam's own review_score_desc strings — scrapers.py stores this verbatim in
# the review_score column, so matching one of these means a plain equality
# check, not a percentage/count threshold we'd have to reverse-engineer.
_REVIEW_TIERS = [
    'Overwhelmingly Positive', 'Very Positive', 'Mostly Positive', 'Positive',
    'Mixed', 'Mostly Negative', 'Negative', 'Very Negative', 'Overwhelmingly Negative',
]


def _year_start_ts(year):
    return int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())
# Named punctuation characters kept deliberately short and unambiguous —
# words like "period"/"comma"/"dash" are too common in unrelated category
# text (e.g. "released within a specific period") to search for safely.
_PUNCT_NAMES = {
    'question mark': '?', 'exclamation mark': '!', 'exclamation point': '!',
    'apostrophe': "'", 'colon': ':',
}

# Columns whose "contains" semantics mean comma-separated-list membership
# (',' || col || ',' LIKE '%,val,%') rather than a plain substring match.
# Kept independent of library.py's own (narrower) CSV-column handling in
# build_condition_sql — the two already disagree for developers/publishers
# and reconciling them is out of scope here.
COMMA_SEP_COLS = {'tags', 'groups', 'genres', 'categories', 'developers', 'publishers'}

_TITLE_NORM_SQL = (
    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(name),"
    " ':', ' '), '!', ' '), '?', ' '), ',', ' '), '.', ' '),"
    " '''', ' '), '(', ' '), ')', ' '), '[', ' '), ']', ' '),"
    " '{', ' '), '}', ' '), ';', ' '), '\"', ' ')"
)

_ALNUM_SPACE_CHARS = list('abcdefghijklmnopqrstuvwxyz0123456789 ')


def _strip_alnum_sql(expr):
    """Nested replace() chain that strips a-z/0-9/space from a lowercased SQL
    expression — whatever's left over means the source string had a
    "special" (punctuation, symbol, non-Latin script, ...) character in it.
    Same chained-REPLACE idiom as _TITLE_NORM_SQL, since SQLite has no
    REGEXP available and 'instr'/'glob' aren't in library.py's function
    whitelist.
    """
    sql = f'lower({expr})'
    for c in _ALNUM_SPACE_CHARS:
        sql = f"replace({sql}, '{c}', '')"
    return sql

# Neutral op name -> {tree_op, kind, [fmt], manual_ui}
#   tree_op:    the token this op is represented as once it leaves classify_category
#               and reaches the saved filter tree / quals conds / _pagCheckCond.
#   kind:       groups ops that share SQL/JS matching shape (the strftime family
#               collapses month/day/year into one code path).
#   manual_ui:  {general: {label}?, date: {label}?} — which manual condition-builder
#               dropdown(s) this op appears in and its label there (some ops, like
#               gt/lt/equals, appear in both with different copy). Omitted context
#               keys mean "not offered in that dropdown"; an op with neither means
#               it's only ever produced by classify_category / the quals endpoint.
OP_REGISTRY = {
    'month_is':        {'tree_op': 'STRFTIME_MONTH',   'kind': 'strftime',          'fmt': '%m',
                         'manual_ui': {'date': {'label': 'month is (1–12)'}}},
    'day_is':          {'tree_op': 'STRFTIME_DAY',     'kind': 'strftime',          'fmt': '%d',
                         'manual_ui': {'date': {'label': 'day is (1–31)'}}},
    'year_is':         {'tree_op': 'STRFTIME_YEAR',    'kind': 'strftime',          'fmt': '%Y',
                         'manual_ui': {'date': {'label': 'year is (YYYY)'}}},
    'weekday_is':      {'tree_op': 'STRFTIME_WEEKDAY', 'kind': 'strftime_weekday',
                         'manual_ui': {'date': {'label': 'weekday is (0=Sun…6=Sat)'}}},
    'contains':        {'tree_op': 'LIKE',             'kind': 'contains',
                         'manual_ui': {'general': {'label': 'contains'}}},
    'not_contains':    {'tree_op': 'NOT LIKE',         'kind': 'not_contains',
                         'manual_ui': {'general': {'label': 'does not contain'}}},
    'equals':          {'tree_op': '=',                'kind': 'equals',
                         'manual_ui': {'general': {'label': 'equals'}, 'date': {'label': 'on (exact)'}}},
    'starts_with':     {'tree_op': 'STARTS_WITH',      'kind': 'starts_with',
                         'manual_ui': {'general': {'label': 'starts with'}}},
    'starts_with_any': {'tree_op': 'STARTS_WITH_ANY',  'kind': 'starts_with_any',
                         'manual_ui': {}},  # classifier/quals only
    'ends_with':       {'tree_op': 'ENDS_WITH',        'kind': 'ends_with',
                         'manual_ui': {'general': {'label': 'ends with'}}},
    'title_word':      {'tree_op': 'TITLE_WORD',       'kind': 'title_word',
                         'manual_ui': {'general': {'label': 'title word'}}},
    'gt':              {'tree_op': '>',                'kind': 'numeric_gt',
                         'manual_ui': {'general': {'label': '>'}, 'date': {'label': 'after'}}},
    'lt':              {'tree_op': '<',                'kind': 'numeric_lt',
                         'manual_ui': {'general': {'label': '<'}, 'date': {'label': 'before'}}},
    'gte':             {'tree_op': '>=',                'kind': 'numeric_gte',
                         'manual_ui': {'general': {'label': '>='}}},
    'length_eq':       {'tree_op': 'LENGTH_EQ',         'kind': 'title_length',
                         'manual_ui': {'general': {'label': 'length is (characters)'}}},
    'digit_count_gte': {'tree_op': 'DIGIT_COUNT_GTE',   'kind': 'digit_count',
                         'manual_ui': {'general': {'label': 'digit occurs N+ times (format: D:N)'}}},
    'consecutive_repeat': {'tree_op': 'CONSECUTIVE_REPEAT', 'kind': 'consecutive_repeat',
                         'manual_ui': {'general': {'label': 'N identical digits in a row (value = N)'}}},
    'has_special_char': {'tree_op': 'HAS_SPECIAL_CHAR', 'kind': 'has_special_char',
                         'manual_ui': {'general': {'label': 'has a special character (value ignored, type anything)'}}},
    'range_incl':      {'tree_op': 'RANGE_INCL',        'kind': 'numeric_range',
                         'manual_ui': {'general': {'label': 'between (inclusive, format: MIN:MAX)'}}},
    'tag_substring':   {'tree_op': 'TAG_SUBSTRING',      'kind': 'tag_substring',
                         'manual_ui': {'general': {'label': 'any tag containing (substring, not exact)'}}},
    'nth_weekday':     {'tree_op': 'NTH_WEEKDAY',        'kind': 'nth_weekday',
                         'manual_ui': {'date': {'label': 'Nth weekday of month (format: N:W, W=0-6 Sun-Sat)'}}},
    'all_caps':        {'tree_op': 'ALL_CAPS',           'kind': 'all_caps',
                         'manual_ui': {'general': {'label': 'is all-uppercase (value ignored, type anything)'}}},
    'contains_all':    {'tree_op': 'CONTAINS_ALL',       'kind': 'contains_all',
                         'manual_ui': {'general': {'label': 'contains all of these letters (no separators)'}}},
    'tag_count_eq':    {'tree_op': 'TAG_COUNT_EQ',       'kind': 'tag_count',
                         'manual_ui': {'general': {'label': 'has exactly N tags'}}},
    'single_word':     {'tree_op': 'SINGLE_WORD',        'kind': 'single_word',
                         'manual_ui': {'general': {'label': 'is a single word (value ignored, type anything)'}}},
}


def js_op_table():
    """JSON-serializable view of OP_REGISTRY for injection into the page as window._PAG_OPS."""
    return {op: {'tree_op': meta['tree_op'], 'kind': meta['kind'], **({'fmt': meta['fmt']} if 'fmt' in meta else {}),
                 'manual_ui': meta['manual_ui']}
            for op, meta in OP_REGISTRY.items()}


def load_supplements():
    _supplement = {}
    supplement_path = os.path.join(BASE_DIR, SUPPLEMENT_PATH)
    try:
        with open(supplement_path, 'r', encoding='utf-8') as f:
            _supplement = json.load(f)
    except Exception:
        pass
    icaio_ga = {g['appid']: g['name'] for g in _supplement.get('icaio_giveaways', [])}
    icaio_wl = {int(k): v for k, v in _supplement.get('icaio_wishlist', {}).items()}
    santa = {}
    try:
        with open(os.path.join(BASE_DIR, SANTA_GIFTS_PATH), 'r', encoding='utf-8') as f:
            santa = {g['appid']: g['name'] for g in json.load(f)}
    except Exception:
        pass
    return icaio_ga, icaio_wl, santa


def load_personal_defaults(event_id):
    """Base category names the maintainer has curated as "always personal" for
    a given event — bundled/shipped (pagywosg_personal_defaults.json is repo-
    tracked, unlike the other local-only PAGYWOSG state files), reviewed once
    per event via tools/pagywosg_category_scan.py's --triage [p] option.
    """
    try:
        with open(os.path.join(BASE_DIR, PERSONAL_DEFAULTS_PATH), 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return []
    return data.get(str(event_id), [])


def build_verified_by_cat(entries):
    """Group an event's verified entries by category id, tracking which SG
    users each appid was verified *for* (player.sgProfileName) — not who
    verified it, who it was verified for. Lets "personal" categories keep
    only the current user's own verified entries instead of trusting anyone's.

    Returns {cat_id: {appid: {"name": str, "verifiers": set(str)}}}.
    """
    result = {}
    for entry in entries:
        if not entry.get('verified'):
            continue
        cid = str(entry['category']['id'])
        appid = entry['game']['id']
        player = entry.get('player') or {}
        verifier = player.get('sgProfileName') or player.get('profileName')
        bucket = result.setdefault(cid, {}).setdefault(appid, {'name': entry['game']['name'], 'verifiers': set()})
        if verifier:
            bucket['verifiers'].add(verifier)
    return result


def fetch_event(event_id):
    import requests
    r = requests.get(
        f'https://pagywosg.xyz/api/events/{event_id}',
        headers={'User-Agent': 'PlayDate/1.0'},
        timeout=10
    )
    r.raise_for_status()
    return r.json()['event']


def classify_category(base, base_appids, icaio_ga_dict, icaio_wl_dict, santa_gift_dict):
    """Classify one PAGYWOSG category name into action dicts.

    Returns a list (usually one item; title-word categories return one per word):
      {'type': 'tag',   'tag': str,                                    'reason': str}
      {'type': 'cond',  'col': str, 'op': str, 'val': str | list,      'reason': str}
      {'type': 'appids','appids': {appid: name}, 'auto': bool, 'force_wins': bool, 'reason': str}
      {'type': 'skip',                                                 'reason': str}

    op names are keys into OP_REGISTRY (plus the classifier-only 'starts_with_any').

    'reason' identifies which branch produced the result — every value means a
    regex recognized the category, EXCEPT 'verified_fallback' and 'unhandled',
    which mean nothing matched and this fell through to the generic
    mod-verified-appids-or-skip fallback. Tools that want to know whether a
    category is genuinely "automated" (has a pattern) vs just riding on
    SteamGifts' own verified-entry system should key off this, not off
    'type' or the presence of appids alone.
    """
    def _cond(col, op, val, reason):
        return [{'type': 'cond', 'col': col, 'op': op, 'val': val, 'reason': reason}]

    def _title_words(text):
        words = [w.strip() for w in re.split(r',|\bor\b', text, flags=re.I) if w.strip()]
        return [{'type': 'cond', 'col': 'name', 'op': 'title_word', 'val': w, 'reason': 'title_word'} for w in words]

    m = re.match(r'^\s*tag\s+(.+)$', base, re.I)
    if m:
        return [{'type': 'tag', 'tag': m.group(1).strip(), 'reason': 'tag'}]

    # Early events (~13-20) named tag categories "<TagName> tag" instead of
    # today's "Tag <TagName>" — PAGYWOSG changed the naming convention at
    # some point; both forms mean the same thing.
    m = re.match(r'^(.+?)\s+tag$', base, re.I)
    if m:
        return [{'type': 'tag', 'tag': m.group(1).strip(), 'reason': 'tag'}]

    # "Strategy tag (any kind of)" — substring match against any tag's name,
    # not an exact tag lookup, so it also covers "Turn-Based Strategy", "4X"
    # only if "strategy" literally appears in the tag text, "Grand Strategy", etc.
    m = re.match(r'^(.+?)\s+tag\s*\(any(?:\s+kind\s+of)?\)$', base, re.I)
    if m:
        return _cond('tags', 'tag_substring', m.group(1).strip(), 'tag_substring')

    m = re.search(r'released?\s+(?:in|during)\s+(' + '|'.join(_MONTHS) + r')\b', base, re.I)
    if m:
        return _cond('release_date', 'month_is', str(_MONTHS[m.group(1).lower()]), 'date')

    m = re.search(r'released?\s+in\s+(\d{4})\b', base, re.I)
    if m:
        return _cond('release_date', 'year_is', m.group(1), 'date')

    # "released on 2nd Thursday (of any month)" — Nth occurrence of a weekday
    # within its month (day-of-month 1-7 is always the 1st, 8-14 the 2nd, ...).
    # Checked before the plain day_is pattern below since e.g. "2nd Thursday"
    # would otherwise have day_is grab "2" and ignore "Thursday".
    m = re.search(
        r'released?\s+on\s+(?:the\s+)?(1st|2nd|3rd|4th|5th|first|second|third|fourth|fifth)\s+'
        r'(' + '|'.join(_WEEKDAYS) + r')\b',
        base, re.I,
    )
    if m:
        n = _ORDINALS[m.group(1).lower()]
        w = _WEEKDAYS[m.group(2).lower()]
        return _cond('release_date', 'nth_weekday', f'{n}:{w}', 'nth_weekday')

    m = re.search(r'released?\s+on\s+(?:the\s+)?(\d+)(?:st|nd|rd|th)?\b(?:\s*day)?', base, re.I)
    if m:
        return _cond('release_date', 'day_is', m.group(1), 'date')

    m = re.search(r'released?\s+on\s+(?:a\s+)?(' + '|'.join(_WEEKDAYS) + r')\b', base, re.I)
    if m:
        return _cond('release_date', 'weekday_is', str(_WEEKDAYS[m.group(1).lower()]), 'date')

    m = re.search(
        r'\bstart(?:s|ing)\s+with\s+(?:the\s+letters?\s+)?'
        r'([A-Za-z](?:\s*[,/]\s*[A-Za-z])*(?:\s*,?\s*or\s+[A-Za-z])?)',
        base, re.I,
    )
    if m:
        letters = [c.upper() for c in re.findall(r'\b[A-Za-z]\b', m.group(1))]
        if letters:
            return [{'type': 'cond', 'col': 'name', 'op': 'starts_with_any', 'val': letters, 'reason': 'starts_with'}]

    # "two 3s or two 4s in appID" / "3 7s in their steam id" — N occurrences
    # of a digit, one clause per digit, OR'd together. Checked before the
    # plainer appid-contains pattern below since e.g. "3 7s in their steam
    # id" would otherwise be misread as a substring search for "7s".
    if re.search(r'\bin\s+(?:the\s+)?(?:app\s*id|(?:their\s+)?steam\s*(?:app\s*)?id)\b', base, re.I):
        digit_groups = re.findall(r'\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(\d)s\b', base, re.I)
        if digit_groups:
            results = []
            for num_str, digit in digit_groups:
                count = _WORDNUMS.get(num_str.lower(), None)
                count = count if count is not None else int(num_str)
                results.append({'type': 'cond', 'col': 'appid', 'op': 'digit_count_gte',
                                 'val': f'{digit}:{count}', 'reason': 'appid_digit_count'})
            return results

        # "contains a 4 in the app ID" — just a plain substring check.
        m = re.search(r'\bcontains?\s+(?:a\s+)?(\d)\b', base, re.I)
        if m:
            return _cond('appid', 'contains', m.group(1), 'appid')

        # 'Games with "45" in their Steam AppID' — quoted digit-string
        # substring, "with" instead of "contains"; may be more than one digit.
        m = re.search(r'\bwith\s+["“”]?(\d+)["“”]?\s+in\b', base, re.I)
        if m:
            return _cond('appid', 'contains', m.group(1), 'appid')

    m = (re.search(r'steam\s*id\s+containing\s+(\w+)', base, re.I) or
         re.search(r'\b(\w+)\s+in\s+(?:their\s+)?steam\s*(?:app\s*)?id', base, re.I))
    if m:
        return _cond('appid', 'contains', m.group(1), 'appid')

    # "game id's that contain 4" / "game ID has 42" — "id" as the sentence
    # subject rather than trailing "in ... id" phrasing.
    m = re.search(r"\bgame\s+id'?s?\s+(?:that\s+)?(?:contains?|has)\s+(?:the\s+number\s+)?(?:a\s+)?(\w+)\b", base, re.I)
    if m:
        return _cond('appid', 'contains', m.group(1), 'appid')

    # "Games that don't have the number 3 in their ID" — negation of the
    # appid-contains pattern.
    m = re.search(r"\bdon'?t\s+have\s+(?:the\s+number\s+)?(?:a\s+)?(\w+)\s+in\s+(?:their|the)\s+(?:steam\s+)?id\b", base, re.I)
    if m:
        return _cond('appid', 'not_contains', m.group(1), 'appid')

    # "20 or 01 in the ID of game" — a list of substrings, OR'd (unlike the
    # achievements range above, OR is exactly right here since any one match
    # qualifies the game).
    m = re.search(r'^(.+?)\s+in\s+(?:the\s+)?id\s+of\s+(?:the\s+)?game\b', base, re.I)
    if m:
        tokens = [t.strip() for t in re.split(r',|\bor\b', m.group(1), flags=re.I) if t.strip()]
        if tokens:
            return [{'type': 'cond', 'col': 'appid', 'op': 'contains', 'val': t, 'reason': 'appid'} for t in tokens]

    # "AppID has two identical consecutive digits" — a run of N equal digits
    # in a row, not just N occurrences anywhere (that's digit_count_gte above).
    m = re.search(
        r'\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+'
        r'(?:identical\s+consecutive|consecutive\s+identical)\s+digits?\b',
        base, re.I,
    )
    if m:
        num_str = m.group(1).lower()
        n = _WORDNUMS.get(num_str, None)
        n = n if n is not None else int(num_str)
        if n >= 2:
            return _cond('appid', 'consecutive_repeat', str(n), 'appid_consecutive_repeat')

    # "the word "X" in its/the/their title" — the explicit "word" signals a
    # whole-word match, not a plain substring, so this is checked (and thus
    # takes precedence) before the plain quoted-substring title pattern below.
    m = re.search(r'\bword\s+["“”]([^"“”]+)["“”]\s+in\s+(?:the|their|its)\s+title', base, re.I)
    if m:
        return _cond('name', 'title_word', m.group(1).strip(), 'title_quote_word')

    m = re.search(r'["“”]([^"“”]+)["“”]\s+(?:anywhere\s+)?in\s+(?:the|their|its)\s+title', base, re.I)
    if m:
        return _cond('name', 'contains', m.group(1).strip(), 'title_quote')

    # "a 2 in their title" — same idea, no quotes around the digit.
    m = re.search(r'\b(?:a|an)\s+(\d+)\s+in\s+(?:the|their|its)\s+title\b', base, re.I)
    if m:
        return _cond('name', 'contains', m.group(1), 'title_char')

    m = re.search(r'["“”]([^"“”]+)["“”]\s+prefix\b', base, re.I)
    if m:
        return _cond('name', 'starts_with', m.group(1).strip(), 'title_prefix_quote')

    m = re.search(r'exactly\s+(\d+)\s+characters?\b.*?\btitle\b', base, re.I)
    if m:
        return _cond('name', 'length_eq', m.group(1), 'title_length')

    # "special charaters"/"special characters" — the source category name has
    # a typo (missing the second 'c') that's apparently permanent; tolerate
    # both spellings. Verified per-game examples (event 13) show this means
    # any punctuation/symbol/non-Latin character, not a specific set.
    if re.search(r'\bspecial\s+charac?ters?\b', base, re.I):
        return _cond('name', 'has_special_char', '1', 'special_char')

    # "Game names with only capital letters" — every letter in the title is uppercase.
    if re.search(r'\bonly\s+capital\s+letters?\b', base, re.I):
        return _cond('name', 'all_caps', '1', 'all_caps')

    # "Game names with question marks" — a specific named punctuation character.
    m = re.search(r'\b(' + '|'.join(re.escape(k) for k in _PUNCT_NAMES) + r')s?\b', base, re.I)
    if m:
        return _cond('name', 'contains', _PUNCT_NAMES[m.group(1).lower()], 'title_char')

    m = re.search(r'["“”]([^"“”]+)["“”]\s+in\s+(?:the|their|its)\s+(developer|publisher)s?\s+name', base, re.I)
    if m:
        col = 'developers' if m.group(2).lower() == 'developer' else 'publishers'
        return _cond(col, 'contains', m.group(1).strip(), 'dev_pub_quote')

    # "Name/Developer/Publisher including the letters R, U, O and K" — all
    # listed letters must be present (an AND, unlike starts_with_any's OR),
    # so this needs one condition encoding every letter, not separate returns.
    m = re.search(
        r'^(name|developer|publisher)\s+including\s+the\s+letters?\s+'
        r'([A-Za-z](?:\s*,\s*[A-Za-z])*(?:\s*,?\s*and\s+[A-Za-z])?)\b',
        base, re.I,
    )
    if m:
        col_word = m.group(1).lower()
        col = 'name' if col_word == 'name' else 'developers' if col_word == 'developer' else 'publishers'
        parts = [p.strip() for p in re.split(r',|\band\b', m.group(2), flags=re.I) if p.strip()]
        letters_val = ''.join(p.upper() for p in parts if len(p) == 1 and p.isalpha())
        return _cond(col, 'contains_all', letters_val, 'letters_required')

    m = re.match(r'^game\s+title\s+with\s+(.+)$', base, re.I)
    if m:
        return _title_words(m.group(1))

    # "Game with X or Y in the name" — same word-match intent as "game title
    # with X, Y" above, just different phrasing.
    m = re.search(r'\bwith\s+(.+?)\s+in\s+(?:the|its|their)\s+name\b', base, re.I)
    if m:
        return _title_words(m.group(1))

    m = re.search(
        r'(?:'
        r'(?:under|less\s+than|at\s+most|shorter\s+than|below)\s+(?P<h_lt>\d+)\s*h\b'
        r'|(?:over|more\s+than|at\s+least|longer\s+than|above)\s+(?P<h_gt>\d+)\s*h\b'
        r'|(?P<h_plus>\d+)\s*h\+'
        r').*?hltb\s*'
        r'(?P<field>completionist\b|(?:main\s*\+\s*)?extras?\b|main\b)?',
        base, re.I,
    )
    if m:
        hours = int(m.group('h_lt') or m.group('h_gt') or m.group('h_plus'))
        f = (m.group('field') or '').lower()
        op = 'lt' if m.group('h_lt') else 'gte'
        val = str(hours * 60)
        if 'completionist' in f:
            return _cond('hltb_completionist', op, val, 'hltb')
        if 'extra' in f:
            return _cond('hltb_extras', op, val, 'hltb')
        if 'main' in f:
            return _cond('hltb_main', op, val, 'hltb')
        # No specific field named ("any HLTB time") — match on any of the three.
        return [{'type': 'cond', 'col': c, 'op': op, 'val': val, 'reason': 'hltb'}
                for c in ('hltb_main', 'hltb_extras', 'hltb_completionist')]

    # "Games without achievements" / "Games with no achievements" — exactly
    # zero, not "under N" (numeric_lt's SQL treats 0/NULL as "not fetched
    # yet" and deliberately excludes it, so this needs a plain equality check).
    if re.search(r'\b(?:without|with\s+no)\s+achievements?\b', base, re.I):
        return _cond('total_achievements', 'equals', '0', 'achievements')

    # "1 to 12 achievements" — a range needs both bounds in one condition
    # (multiple cond items from one category get OR'd, not AND'd, when the
    # filter tree is built, so this can't be two separate gte/lt returns).
    m = re.search(r'\b(\d+)\s*(?:to|-)\s*(\d+)\s*achievements?\b', base, re.I)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return _cond('total_achievements', 'range_incl', f'{lo}:{hi}', 'achievements_range')

    m = re.search(
        r'(?:'
        r'(?:under|less\s+than|at\s+most|fewer\s+than|below)\s+(?P<a_lt>\d+)\s*achievements?\b'
        r'|(?:over|more\s+than|at\s+least|above)\s+(?P<a_gt>\d+)\s*achievements?\b'
        r'|(?P<a_plus>\d+)\s*\+\s*achievements?\b'
        r')',
        base, re.I,
    )
    if m:
        count = int(m.group('a_lt') or m.group('a_gt') or m.group('a_plus'))
        return _cond('total_achievements', 'lt' if m.group('a_lt') else 'gte', str(count), 'achievements')

    # Bare "5 achievements" (no threshold word at all) — exact count.
    m = re.match(r'^(\d+)\s*achievements?$', base, re.I)
    if m:
        return _cond('total_achievements', 'equals', m.group(1), 'achievements')

    # Bare "5 tags" — exact tag count, comma count + 1 (0 if the field is empty).
    m = re.match(r'^(\d+)\s*tags?$', base, re.I)
    if m:
        return _cond('tags', 'tag_count_eq', m.group(1), 'tag_count')

    # "Title with only one word" — no internal spaces.
    if re.search(r'\btitle\s+with\s+only\s+one\s+word\b', base, re.I):
        return _cond('name', 'single_word', '1', 'single_word')

    # A Steam review-tier label, quoted or not, "rating" or "reviews" wording.
    m = re.search(r'\b(' + '|'.join(re.escape(t) for t in _REVIEW_TIERS) + r')\b', base, re.I)
    if m:
        tier = next(t for t in _REVIEW_TIERS if t.lower() == m.group(1).lower())
        return _cond('review_score', 'equals', tier, 'review_tier')

    m = re.search(r'released?\s+before\s+(\d{4})\b', base, re.I)
    if m:
        return _cond('release_date', 'lt', str(_year_start_ts(int(m.group(1)))), 'date')

    m = re.search(r'released?\s+after\s+(\d{4})\b', base, re.I)
    if m:
        return _cond('release_date', 'gte', str(_year_start_ts(int(m.group(1)) + 1)), 'date')

    if re.search(r'gifter', base, re.I):
        return [{'type': 'skip', 'reason': 'gifter'}]

    if 'icaio has made a GA for' in base:
        if icaio_ga_dict:
            return [{'type': 'appids', 'appids': icaio_ga_dict, 'auto': True, 'force_wins': False, 'reason': 'icaio_ga'}]
        return [{'type': 'skip', 'reason': 'icaio_ga'}]

    if 'icaio' in base and 'wishlist' in base.lower():
        if icaio_wl_dict:
            return [{'type': 'appids', 'appids': icaio_wl_dict, 'auto': True, 'force_wins': False, 'reason': 'icaio_wishlist'}]
        return [{'type': 'skip', 'reason': 'icaio_wishlist'}]

    if re.search(r'snowball|secret.santa', base, re.I):
        if santa_gift_dict:
            return [{'type': 'appids', 'appids': santa_gift_dict, 'auto': True, 'force_wins': True, 'reason': 'santa'}]
        return [{'type': 'skip', 'reason': 'santa'}]

    if base_appids:
        return [{'type': 'appids', 'appids': base_appids, 'auto': False, 'force_wins': False, 'reason': 'verified_fallback'}]
    return [{'type': 'skip', 'reason': 'unhandled'}]


def redundant_where_sql(conds, tags):
    """Build the (WHERE fragment, params) pair used to find library appids already
    matched by a pool's tag/condition criteria, mirroring OP_REGISTRY['kind'] shapes.
    conds: list of {'col', 'op', 'val'} using OP_REGISTRY neutral op names.
    Returns (None, None) if there is nothing to query.
    """
    parts, params = [], []
    for tag in tags:
        parts.append("(',' || tags || ',') LIKE ?")
        params.append(f'%,{tag},%')
    for c in conds:
        col, op, val = c['col'], c['op'], c['val']
        kind = OP_REGISTRY.get(op, {}).get('kind')
        if kind == 'contains':
            if col in COMMA_SEP_COLS:
                parts.append(f"(',' || {col} || ',') LIKE ?")
                params.append(f'%,{val},%')
            elif col == 'name':
                parts.append("name LIKE ?")
                params.append(f'%{val}%')
        elif kind == 'strftime':
            fmt = OP_REGISTRY[op]['fmt']
            parts.append(f"strftime('{fmt}', {col}) = ?")
            params.append(str(val) if fmt == '%Y' else str(int(val)).zfill(2))
        elif kind == 'strftime_weekday':
            parts.append(f"({col} IS NOT NULL AND {col} != 0 AND strftime('%w', datetime({col}, 'unixepoch')) = ?)")
            params.append(str(val))
        elif kind == 'starts_with':
            parts.append(f"{col} LIKE ?")
            params.append(f'{val}%')
        elif kind == 'ends_with':
            parts.append(f"{col} LIKE ?")
            params.append(f'%{val}')
        elif kind == 'title_word':
            w = val.lower()
            parts.append(f"(' ' || {_TITLE_NORM_SQL} || ' ') LIKE ?")
            params.append(f'% {w} %')
        elif kind == 'numeric_gte':
            parts.append(f"{col} >= ?")
            params.append(int(val))
        elif kind == 'numeric_gt':
            parts.append(f"{col} > ?")
            params.append(int(val))
        elif kind == 'numeric_lt':
            parts.append(f"({col} IS NOT NULL AND {col} > 0 AND {col} < ?)")
            params.append(int(val))
        elif kind == 'title_length':
            parts.append(f"length({col}) = ?")
            params.append(int(val))
        elif kind == 'digit_count':
            digit, count = val.split(':')
            parts.append(f"(length({col}) - length(replace({col}, ?, ''))) >= ?")
            params.append(digit)
            params.append(int(count))
        elif kind == 'consecutive_repeat':
            n = int(val)
            sub_parts = []
            for d in '0123456789':
                sub_parts.append(f"replace({col}, ?, '') != {col}")
                params.append(d * n)
            parts.append('(' + ' OR '.join(sub_parts) + ')')
        elif kind == 'has_special_char':
            parts.append(f"length({_strip_alnum_sql(col)}) > 0")
        elif kind == 'numeric_range':
            lo, hi = val.split(':')
            parts.append(f"({col} >= ? AND {col} <= ?)")
            params.append(int(lo))
            params.append(int(hi))
        elif kind == 'equals':
            parts.append(f"{col} = ?")
            params.append(val)
        elif kind == 'tag_substring':
            parts.append(f"{col} LIKE ?")
            params.append(f'%{val}%')
        elif kind == 'nth_weekday':
            n, w = val.split(':')
            lo, hi = (int(n) - 1) * 7 + 1, int(n) * 7
            parts.append(
                f"({col} IS NOT NULL AND {col} != 0 AND "
                f"strftime('%w', datetime({col}, 'unixepoch')) = ? AND "
                f"strftime('%d', {col}, 'unixepoch') BETWEEN ? AND ?)"
            )
            params.append(w)
            params.append(str(lo).zfill(2))
            params.append(str(hi).zfill(2))
        elif kind == 'all_caps':
            parts.append(f"upper({col}) = {col}")
        elif kind == 'contains_all':
            sub_parts = [f"{col} LIKE ?" for _ in val]
            for ch in val:
                params.append(f'%{ch}%')
            parts.append('(' + ' AND '.join(sub_parts) + ')')
        elif kind == 'not_contains':
            if col in COMMA_SEP_COLS:
                parts.append(f"(',' || {col} || ',') NOT LIKE ?")
                params.append(f'%,{val},%')
            else:
                parts.append(f"{col} NOT LIKE ?")
                params.append(f'%{val}%')
        elif kind == 'tag_count':
            parts.append(f"(CASE WHEN {col} = '' OR {col} IS NULL THEN 0 "
                          f"ELSE length({col}) - length(replace({col}, ',', '')) + 1 END) = ?")
            params.append(int(val))
        elif kind == 'single_word':
            parts.append(f"replace(trim({col}), ' ', '') = trim({col})")
    if not parts:
        return None, None
    return ' OR '.join(parts), params


def _resolve_sg_group():
    from config import load_state
    _state = load_state()
    sg = _state.get('pagywosg_sg_group') or None
    if sg:
        return sg
    def _find(node):
        if not node: return None
        if node.get('type') == 'condition' and node.get('column') == 'groups':
            return node.get('value')
        for child in node.get('items', []):
            r = _find(child)
            if r: return r
        return None
    for _candidate in [_state.get('filter_tree')] + [
        v.get('tree') if isinstance(v, dict) and 'tree' in v else v
        for v in _state.get('saved_filters', {}).values()
    ]:
        if isinstance(_candidate, dict) and _candidate.get('pagywosg'):
            sg = _find(_candidate)
            if sg:
                return sg
    return None


# ── Routes ───────────────────────────────────────────────────────────────────

@pagywosg_bp.route('/api/pagywosg-auto')
def pagywosg_auto():
    from database import get_db
    from datetime import date

    # Anchor: event 83 = April 2026
    today = date.today()
    event_id = 83 + (today.year - 2026) * 12 + (today.month - 4)
    if request.args.get('next'):
        event_id += 1

    try:
        event = fetch_event(event_id)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Could not fetch event: {e}"}), 502

    # Validate date range; try adjacent event on boundary days (skip for upcoming)
    today_str = today.isoformat()
    if not request.args.get('next'):
        started, ended = event.get('startedAt', ''), event.get('endedAt', '')
        if started and ended and not (started <= today_str < ended):
            adj = event_id + 1 if today_str >= ended else event_id - 1
            try:
                adj_event = fetch_event(adj)
                s2, e2 = adj_event.get('startedAt', ''), adj_event.get('endedAt', '')
                if s2 <= today_str < e2:
                    event = adj_event
                    event_id = adj
            except Exception:
                pass

    categories = event.get('gameCategories', [])
    entries    = event.get('entries', [])

    # --- Pool determination via (win)/(backlog) suffix ---
    suffix_re = re.compile(r'\s*\((win|backlog)\)\s*$', re.IGNORECASE)

    base_to_cats = {}
    for cat in categories:
        base = suffix_re.sub('', cat['name']).strip()
        base_to_cats.setdefault(base, []).append(cat)

    all_pool_bases = set()
    for base, cats in base_to_cats.items():
        names_lc = [c['name'].lower() for c in cats]
        if any('(win)' in n for n in names_lc) and any('(backlog)' in n for n in names_lc):
            all_pool_bases.add(base)

    # --- Verified appids per category ID, with per-appid verifier attribution ---
    verified_by_cat = build_verified_by_cat(entries)

    tags_wins, tags_all   = [], []
    conds_wins, conds_all = [], []
    appids_wins, appids_all = {}, {}
    skipped = []
    # Categories that fell through to the verified-fallback path but currently
    # have zero verified appids (typically an upcoming event nobody has played
    # yet) — these are real personal-category candidates, just without any
    # games to show yet, so the "Personal categories" UI can't discover them
    # from _pagWinsGames/_pagAllGames alone the way it does once appids exist.
    personal_candidates = set()

    _icaio_ga_dict, _icaio_wl_dict, _santa_gift_dict = load_supplements()

    for base, cats in base_to_cats.items():
        pool = 'all' if base in all_pool_bases else 'wins'

        base_appids = {}      # {appid: name} — feeds classify_category as before
        base_verifiers = {}   # {appid: set(sgProfileName)} — SG-verified-fallback only
        for cat in cats:
            for aid, info in verified_by_cat.get(str(cat['id']), {}).items():
                base_appids[aid] = info['name']
                base_verifiers.setdefault(aid, set()).update(info['verifiers'])

        def _add_tag(tag):
            (tags_all if pool == 'all' else tags_wins).append(tag)

        def _add_cond(col, op, val):
            (conds_all if pool == 'all' else conds_wins).append({'col': col, 'op': op, 'val': val})

        def _add_appids(appid_name_dict, category_name, auto=False, verifiers_by_appid=None):
            target = appids_all if pool == 'all' else appids_wins
            for appid, name in appid_name_dict.items():
                if appid not in target:
                    target[appid] = {"name": name, "categories": []}
                if not any(c["cat"] == category_name for c in target[appid]["categories"]):
                    entry = {"cat": category_name}
                    if auto:
                        entry["auto"] = True
                    if verifiers_by_appid and appid in verifiers_by_appid:
                        entry["verifiers"] = sorted(verifiers_by_appid[appid])
                    target[appid]["categories"].append(entry)

        for r in classify_category(base, base_appids,
                                    _icaio_ga_dict, _icaio_wl_dict, _santa_gift_dict):
            if r['type'] == 'tag':
                _add_tag(r['tag'])
            elif r['type'] == 'cond':
                if r['op'] == 'starts_with_any':
                    for letter in r['val']:
                        _add_cond('name', 'starts_with', letter)
                else:
                    _add_cond(r['col'], r['op'], r['val'])
            elif r['type'] == 'appids':
                # Only the genuine SG-verified-fallback case (auto=False) has
                # real per-user verifier attribution — icaio/santa appids come
                # from bundled supplement files, not mod-verified SG entries.
                vbi = None if r['auto'] else base_verifiers
                if r['force_wins']:
                    _real_pool = pool
                    pool = 'wins'
                    _add_appids(r['appids'], base, auto=r['auto'], verifiers_by_appid=vbi)
                    pool = _real_pool
                else:
                    _add_appids(r['appids'], base, auto=r['auto'], verifiers_by_appid=vbi)
            elif r['type'] == 'skip':
                skipped.append(base)
                if r['reason'] == 'unhandled':
                    personal_candidates.add(base)

    # Scan the whole games table once (fast — user's library is small) and
    # intersect in Python, avoiding a huge IN (?, ?, ...) with 5000+ params.
    _lib_db = get_db()
    _all_library_appids = {r['appid'] for r in _lib_db.execute('SELECT appid FROM games').fetchall()}
    all_appids_combined = set(appids_wins.keys()) | set(appids_all.keys())
    in_library_set = _all_library_appids & all_appids_combined

    def _redundant_set(pool_dict, tags, conds):
        """Return appids already matched by the pool's tag/condition criteria (not needing the explicit appid list)."""
        owned = {aid for aid in pool_dict if aid in in_library_set}
        if not owned:
            return set()
        where, params = redundant_where_sql(conds, tags)
        if not where:
            return set()
        # Query only the tag/condition filter against the whole library,
        # then intersect with owned in Python — no large IN clause needed.
        rows = _lib_db.execute(
            f'SELECT appid FROM games WHERE ({where})',
            params
        ).fetchall()
        return {r['appid'] for r in rows} & owned

    def _serialise_pool(pool_dict, tags, conds):
        redundant = _redundant_set(pool_dict, tags, conds)
        from config import load_config
        sg_username = (load_config() or {}).get('sg_username', '').strip().lower()
        # Group appids by contributing category label for labeled appid_list nodes.
        # Only include appids present in the user's library — no point embedding
        # thousands of unowned game IDs in the saved filter.
        source_map = {}   # {cat_label: {"appids": [...], "auto": bool, "personal_appids": [...]}}
        for aid, v in pool_dict.items():
            if aid not in in_library_set:
                continue
            for cat_entry in v.get("categories", []):
                label = cat_entry.get("cat", "")
                if not label:
                    continue
                if label not in source_map:
                    source_map[label] = {"appids": [], "auto": bool(cat_entry.get("auto")), "personal_appids": []}
                source_map[label]["appids"].append(aid)
                verifiers = cat_entry.get("verifiers") or []
                if sg_username and any(vf.lower() == sg_username for vf in verifiers):
                    source_map[label]["personal_appids"].append(aid)
        appid_sources = [{"label": lbl, "appids": sorted(v["appids"]), "auto": v["auto"],
                          "personal_appids": sorted(v["personal_appids"])}
                         for lbl, v in source_map.items() if v["appids"]]
        return {
            "appids": sorted(aid for aid in pool_dict if aid in in_library_set),
            "appid_sources": appid_sources,
            "games":  sorted(
                [{"appid": aid, "name": v["name"], "categories": v["categories"],
                  "in_library": aid in in_library_set,
                  "redundant":  aid in redundant}
                 for aid, v in pool_dict.items()],
                key=lambda g: g["name"].lower()
            ),
        }

    result = {
        "status": "success",
        "event": {"id": event_id, "name": event.get('name', '')},
        "tags":   {"wins": tags_wins, "all": tags_all},
        "conds":  {"wins": conds_wins, "all": conds_all},
        "wins":   _serialise_pool(appids_wins, tags_wins, conds_wins),
        "all":    _serialise_pool(appids_all,  tags_all,  conds_all),
        "skipped": skipped,
        "personal_candidates": sorted(personal_candidates),
        "default_personal": load_personal_defaults(event_id),
    }
    _lib_db.close()
    return jsonify(result)

@pagywosg_bp.route('/api/pagywosg-quals')
def pagywosg_quals_data():
    from datetime import date, datetime as _datetime

    today     = date.today()
    event_id  = 83 + (today.year - 2026) * 12 + (today.month - 4)

    cached = _pagywosg_quals_cache.get(event_id)
    if cached:
        ts, data = cached
        if _datetime.now().timestamp() - ts < 3600:
            return jsonify({**data, 'sg_group': _resolve_sg_group()})

    try:
        event = fetch_event(event_id)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 502

    month_label = today.strftime('%B %Y')

    categories = event.get('gameCategories', [])
    entries    = event.get('entries', [])

    suffix_re = re.compile(r'\s*\((win|backlog)\)\s*$', re.IGNORECASE)
    base_to_cats = {}
    for cat in categories:
        base = suffix_re.sub('', cat['name']).strip()
        base_to_cats.setdefault(base, []).append(cat)

    all_pool_bases = set()
    for base, cats in base_to_cats.items():
        names_lc = [c['name'].lower() for c in cats]
        if any('(win)' in n for n in names_lc) and any('(backlog)' in n for n in names_lc):
            all_pool_bases.add(base)

    verified_by_cat = build_verified_by_cat(entries)

    _icaio_ga_dict, _icaio_wl_dict, _santa_gift_dict = load_supplements()
    _default_personal = set(load_personal_defaults(event_id))
    from config import load_config
    sg_username = (load_config() or {}).get('sg_username', '').strip().lower()

    conds    = []
    verified = {}

    def _add_v(appid_name_dict, cat_label, pool, auto=False, verifiers_by_appid=None):
        # This endpoint has no per-user toggle state (it's the live preview
        # before any filter is saved) — personal categories are scoped by
        # the dev-curated bundled list instead of a client-side checkbox.
        is_personal = cat_label in _default_personal
        for appid, name in appid_name_dict.items():
            if is_personal:
                verifiers = (verifiers_by_appid or {}).get(appid, set())
                if not (sg_username and any(vf.lower() == sg_username for vf in verifiers)):
                    continue
            key = str(appid)
            if key not in verified:
                verified[key] = []
            if not any(e['cat'] == cat_label and e['pool'] == pool for e in verified[key]):
                entry = {'cat': cat_label, 'pool': pool}
                if auto:
                    entry['auto'] = True
                if verifiers_by_appid and appid in verifiers_by_appid:
                    entry['verifiers'] = sorted(verifiers_by_appid[appid])
                verified[key].append(entry)

    for base, cats in base_to_cats.items():
        pool = 'all' if base in all_pool_bases else 'wins'
        base_appids = {}
        base_verifiers = {}
        for cat in cats:
            for aid, info in verified_by_cat.get(str(cat['id']), {}).items():
                base_appids[aid] = info['name']
                base_verifiers.setdefault(aid, set()).update(info['verifiers'])

        for r in classify_category(base, base_appids,
                                    _icaio_ga_dict, _icaio_wl_dict, _santa_gift_dict):
            if r['type'] == 'tag':
                conds.append({'col': 'tags', 'op': 'LIKE', 'val': r['tag'], 'pool': pool})
            elif r['type'] == 'cond':
                mapped_op = OP_REGISTRY.get(r['op'], {}).get('tree_op', r['op'])
                conds.append({'col': r['col'], 'op': mapped_op, 'val': r['val'], 'pool': pool})
            elif r['type'] == 'appids':
                vbi = None if r['auto'] else base_verifiers
                _add_v(r['appids'], base, 'wins' if r['force_wins'] else pool, auto=r['auto'], verifiers_by_appid=vbi)
            # skip: do nothing

    sg_group = _resolve_sg_group()

    result = {
        'status':   'success',
        'event':    {'id': event_id, 'name': event.get('name', ''), 'month_label': month_label},
        'conds':    conds,
        'verified': verified,
    }
    _pagywosg_quals_cache[event_id] = (_datetime.now().timestamp(), result)
    return jsonify({**result, 'sg_group': sg_group})

@pagywosg_bp.route('/api/pagywosg-sg-group', methods=['GET', 'POST'])
def pagywosg_sg_group():
    from config import load_state, save_state
    from utils import get_all_unique_groups
    if request.method == 'POST':
        data = request.json or {}
        # 'group' may be a non-empty string (chosen group) or None (no SG wins)
        grp = data.get('group')
        save_state({'pagywosg_sg_group': grp})
        return jsonify({'status': 'success'})
    # GET
    state = load_state()
    saved = state.get('pagywosg_sg_group', '__unset__')
    groups = get_all_unique_groups()
    default_group = next((g for g in groups if g.lower() == 'won on steamgifts'), None)
    return jsonify({
        'saved': None if saved == '__unset__' else saved,
        'unset': saved == '__unset__',
        'default_group': default_group,
        'groups': groups,
    })

@pagywosg_bp.route('/api/pagywosg-comp-defaults', methods=['GET', 'POST'])
def pagywosg_comp_defaults():
    from config import load_state, save_state
    _valid = {'Never Played', 'Unfinished', 'Beaten', 'Completed', "Won't Play"}
    if request.method == 'POST':
        data = request.json or {}
        statuses = [s for s in (data.get('statuses') or []) if s in _valid]
        save_state({'pagywosg_comp_defaults': statuses})
        return jsonify({'status': 'success'})
    state = load_state()
    saved = state.get('pagywosg_comp_defaults')
    return jsonify({'statuses': saved if saved else ['Never Played', 'Unfinished']})

@pagywosg_bp.route('/api/santa-gifts', methods=['GET', 'POST'])
def santa_gifts():
    path = os.path.join(BASE_DIR, SANTA_GIFTS_PATH)
    if request.method == 'POST':
        data = request.json or {}
        gifts = data.get('gifts', [])
        if not isinstance(gifts, list):
            return jsonify({'status': 'error', 'message': 'Invalid data.'}), 400
        validated = []
        for g in gifts:
            if not (isinstance(g, dict) and 'appid' in g and 'name' in g):
                continue
            entry = {'appid': int(g['appid']), 'name': str(g['name'])}
            # Year the gift was given — evidence for mod verification of Secret
            # Santa/Snowball entries, shown in the PAGYWOSG hover tooltip.
            year = g.get('year')
            if year not in (None, ''):
                try:
                    entry['year'] = int(year)
                except (TypeError, ValueError):
                    pass
            validated.append(entry)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(validated, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error('Failed to save gifts: %s', e)
            return jsonify({'status': 'error', 'message': 'Failed to save gifts'}), 500
        return jsonify({'status': 'success'})
    try:
        with open(path, 'r', encoding='utf-8') as f:
            gifts = json.load(f)
    except Exception:
        gifts = []
    return jsonify({'status': 'success', 'gifts': gifts})

@pagywosg_bp.route('/api/games/by-group')
def games_by_group():
    from database import get_db
    group = request.args.get('group', '').strip()
    if not group:
        return jsonify([])
    try:
        db = get_db()
        rows = db.execute(
            "SELECT appid, name FROM games "
            "WHERE platform = 'steam' AND duplicate_of IS NULL "
            "AND ',' || groups || ',' LIKE ? ORDER BY name",
            (f'%,{group},%',)
        ).fetchall()
        db.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@pagywosg_bp.route('/api/games/groups')
def games_groups():
    try:
        from utils import get_all_unique_groups
        return jsonify(get_all_unique_groups())
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@pagywosg_bp.route('/api/pagywosg-tags')
def pagywosg_tags():
    from database import get_db
    try:
        db = get_db()
        rows = db.execute("SELECT tags FROM games WHERE tags IS NOT NULL AND tags != ''").fetchall()
        db.close()
        tag_set = set()
        for row in rows:
            for tag in [t.strip() for t in row['tags'].split(',') if t.strip()]:
                tag_set.add(tag)
        return jsonify({"status": "success", "tags": sorted(tag_set, key=str.lower)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@pagywosg_bp.route('/api/pagywosg-pick', methods=['POST'])
def pagywosg_pick():
    import random
    from database import get_db
    from library import is_safe_sql
    data = request.json or {}
    where = (data.get('where') or '').strip()
    if not where or where == '1=1':
        return jsonify({"status": "error", "message": "No criteria selected — please pick at least one tag or condition."})
    if not is_safe_sql(where):
        return jsonify({"status": "error", "message": "Invalid SQL in filter."}), 400
    try:
        db = get_db()
        rows = db.execute(f"SELECT appid, name FROM games WHERE {where}").fetchall()
        db.close()
    except Exception as e:
        return jsonify({"status": "error", "message": f"Query error: {e}"}), 400
    games = [dict(r) for r in rows]
    if not games:
        return jsonify({"status": "error", "message": "No games matched the selected criteria."})
    picks = random.sample(games, min(6, len(games)))
    return jsonify({"status": "success", "picks": picks, "pool_size": len(games)})

# ── Monthly in a Month ────────────────────────────────────────────────────

@pagywosg_bp.route('/api/miam-sheet')
def miam_sheet_data():
    import csv, io, requests
    from database import get_db
    from datetime import datetime as _datetime2
    cache = _miam_cache[0]
    now = _datetime2.now().timestamp()
    if cache and now - cache[0] < 3600:
        return jsonify(cache[1])
    try:
        resp = requests.get(_MIAM_SHEET_URL, timeout=15)
        resp.raise_for_status()
        content = resp.text
        reader = csv.DictReader(io.StringIO(content))
        eligible = []
        total = 0
        for row in reader:
            app_id_raw = (row.get('App ID') or '').strip()
            can_do = (row.get('Can do? (Y/N)') or '').strip()
            if not app_id_raw or not app_id_raw.startswith('app/'):
                continue
            try:
                appid = int(app_id_raw[4:])
            except ValueError:
                continue
            total += 1
            if can_do in ('N', 'N?'):
                continue
            eligible.append(appid)
        db = get_db()
        in_library = set()
        if eligible:
            rows = db.execute(
                f"SELECT appid FROM games "
                f"WHERE appid IN ({','.join('?'*len(eligible))}) AND platform = 'steam'",
                eligible
            ).fetchall()
            in_library = {r['appid'] for r in rows}
        db.close()
        data = {
            'status': 'success',
            'total': total,
            'eligible': len(eligible),
            'in_library': len(in_library),
            'appids': eligible,
        }
        _miam_cache[0] = (now, data)
        return jsonify(data)
    except Exception as e:
        log.exception('MiaM sheet fetch failed')
        return jsonify({'status': 'error', 'message': str(e)}), 500
