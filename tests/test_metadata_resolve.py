"""Pure helpers behind the non-Steam metadata backfill (metadata.py).

Network paths (PCGamingWiki, Steam search, the Steam scrapers) aren't
exercised -- only name normalisation, the similarity gate, and the two
wikitext regexes.
"""
import pytest

from metadata import (
    _norm,
    _clean_query,
    _similar,
    _INFOBOX_APPID_RE,
    _REDIRECT_RE,
    _SIM_PCGW,
)


@pytest.mark.parametrize("raw,expected", [
    ("Dragon Age™: Origins",        "dragon age origins"),
    ("Mass Effect™ 2 (2010)",       "mass effect 2"),
    ("Peggle®",                     "peggle"),
    ("Dead Space™ (2008)",          "dead space"),
    ("Tom Clancy's EndWar",         "tom clancy s endwar"),
    ("Command & Conquer™ Generals", "command conquer generals"),
    ("  spaced   out  ",            "spaced out"),
])
def test_norm(raw, expected):
    assert _norm(raw) == expected


def test_norm_keeps_edition_words():
    # 'Legendary Edition' is a distinct product -- must not collapse to the base game
    assert _norm("Mass Effect Legendary Edition") == "mass effect legendary edition"
    assert _similar("Mass Effect", "Mass Effect Legendary Edition") < 0.9


@pytest.mark.parametrize("raw,expected", [
    ("Mass Effect™ 2 (2010)",  "Mass Effect 2"),      # ™ + (YYYY) gone
    ("Peggle®",                "Peggle"),
    ("Prince of Persia: The Sands of Time™", "Prince of Persia: The Sands of Time"),  # inner ':' kept
    ("Far Cry® 3",             "Far Cry 3"),
])
def test_clean_query(raw, expected):
    assert _clean_query(raw) == expected


def test_similar_bounds():
    assert _similar("Far Cry 3", "Far Cry 3") == 1.0
    # roman-numeral vs digit variant should still clear the PCGW gate
    assert _similar("Dragon Age 2", "Dragon Age II") >= _SIM_PCGW
    # an unrelated game that merely shares a word must not clear the gate
    assert _similar("Syndicate (1993)", "Steampunk Syndicate") < _SIM_PCGW
    assert _similar("Theme Hospital", "FREE Hospital Theme Pack") < _SIM_PCGW


@pytest.mark.parametrize("line,appid", [
    ("|steam appid  = 1238040",          "1238040"),
    ("|steam appid=47810",               "47810"),
    ("| steam_appid = 220240",           "220240"),
    ("|Steam AppID = 13570\n|foo=bar",   "13570"),
])
def test_infobox_appid_match(line, appid):
    m = _INFOBOX_APPID_RE.search(line)
    assert m and m.group(1) == appid


def test_infobox_appid_ignores_side_field():
    # 'steam appid side' is DLC / alternate editions -- must not match it
    assert _INFOBOX_APPID_RE.search("|steam appid side  = 1238050,47900") is None
    # but a real appid later in the same blob still matches
    m = _INFOBOX_APPID_RE.search("|steam appid side = 1,2\n|steam appid = 999")
    assert m and m.group(1) == "999"


@pytest.mark.parametrize("wikitext,target", [
    ("#REDIRECT [[Dragon Age II]]",              "Dragon Age II"),
    ("#redirect [[Mass Effect 2]]",              "Mass Effect 2"),
    ("  #REDIRECT   [[ Peggle ]]",               "Peggle "),  # leading ws eaten by the regex; caller .strip()s the rest
    ("#REDIRECT [[Foo#Section]]",                "Foo"),
    ("#REDIRECT [[Foo|display]]",                "Foo"),
])
def test_redirect_match(wikitext, target):
    m = _REDIRECT_RE.match(wikitext)
    assert m and m.group(1) == target


def test_redirect_no_match_on_real_page():
    assert _REDIRECT_RE.match("{{Infobox game\n|title = Real Page\n}}") is None
