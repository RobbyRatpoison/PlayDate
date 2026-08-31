"""SteamGifts won-page parsing (steamgifts.parse_won_public / parse_won_private)
against the synthetic fixtures in tests/fixtures/steamgifts/."""
import os

import pytest

import steamgifts as sg

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'steamgifts')


def _fx(name):
    with open(os.path.join(FIX, name)) as f:
        return f.read()


@pytest.fixture
def public1():
    return sg.parse_won_public(_fx('won_public_page1.html'))


@pytest.fixture
def public2():
    return sg.parse_won_public(_fx('won_public_page2.html'))


@pytest.fixture
def private1():
    return sg.parse_won_private(_fx('won_private_page1.html'))


# ── public page ──────────────────────────────────────────────────────────────

def test_public_row_count_and_pagination(public1, public2):
    assert len(public1['wins']) == 6
    assert public1['total'] == 9
    assert public1['has_next'] is True     # page 1 → more to come
    assert public2['has_next'] is False    # page 2 is the last
    assert public1['logged_in_as'] == 'SampleWinner'


def test_pages_derived_from_total_not_nav():
    # SteamGifts' nav only ever shows current ±1, so page count must come from
    # the total. 313 wins / 25 per page = 13 pages.
    assert sg._ceil_div(313, sg.PUBLIC_PAGE_SIZE) == 13
    assert sg._ceil_div(313, sg.PRIVATE_PAGE_SIZE) == 7


def test_public_normal_app_received(public1):
    w = next(w for w in public1['wins'] if w['code'] == 'AAAA1')
    assert w == {
        'code': 'AAAA1', 'name': 'Example Game One', 'steam_ref': 'app/100010',
        'won_ts': 1704067200, 'gifter': 'GifterAlpha', 'points': 15,
        'received': True,
    }


def test_public_sub_package(public1):
    w = next(w for w in public1['wins'] if w['code'] == 'BBBB2')
    assert w['steam_ref'] == 'sub/200020'
    assert w['received'] is True


def test_public_awaiting_feedback_is_none(public1):
    w = next(w for w in public1['wins'] if w['code'] == 'CCCC3')
    assert w['received'] is None
    assert w['gifter'] == 'GifterCharlie'


def test_public_not_received_is_false(public1):
    w = next(w for w in public1['wins'] if w['code'] == 'DDDD4')
    assert w['received'] is False


def test_public_no_store_giftcard(public1):
    w = next(w for w in public1['wins'] if w['code'] == 'EEEE5')
    assert w['steam_ref'] is None
    assert w['name'] == '$25 Example Gift Card'


def test_public_invite_only_stripped_href_no_code(public1):
    # sixth row: heading has no href, so no code, but appid link survives
    anon = [w for w in public1['wins'] if w['code'] is None]
    assert len(anon) == 1
    assert anon[0]['steam_ref'] == 'app/100060'


def test_public_page2_deleted_and_missing_gifter(public2):
    codes = {w['code'] for w in public2['wins']}
    assert codes == {'FFFF6', 'GGGG7', 'HHHH8'}
    assert next(w for w in public2['wins'] if w['code'] == 'GGGG7')['gifter'] == 'Deleted-1234567'
    assert next(w for w in public2['wins'] if w['code'] == 'HHHH8')['gifter'] is None


# ── private page ─────────────────────────────────────────────────────────────

def test_private_received_states(private1):
    by_code = {r['code']: r for r in private1['rows']}
    assert by_code['AAAA1']['received'] is True
    assert by_code['CCCC3']['received'] is False   # question-circle
    assert by_code['DDDD4']['received'] is False   # times-circle
    assert by_code['BBBB2']['received'] is True
    assert by_code['AAAA1']['ended_ts'] == 1704067200


def test_private_never_exposes_a_key(private1):
    blob = repr(private1)
    assert 'AAAAA-' not in blob
    for r in private1['rows']:
        assert all('-' not in str(v) or not sg._KEY_RE.search(str(v))
                   for v in r.values())


# ── merge + pass-2 planning ──────────────────────────────────────────────────

def test_merge_public_then_private_promotes_awaiting():
    store = {'version': 1, 'wins': []}
    p1 = sg.parse_won_public(_fx('won_public_page1.html'))
    new, changed = sg.merge_public_page(store, p1['wins'])
    assert new == 6 and changed == 0
    assert next(w for w in store['wins'] if w['code'] == 'CCCC3')['received'] is None

    priv = sg.parse_won_private(_fx('won_private_page1.html'))
    # CCCC3 stays not-received on the private fixture, DDDD4 likewise
    flipped = sg.apply_private_rows(store, priv['rows'])
    assert flipped == 0

    # a re-merge of the same public page is a no-op
    new2, changed2 = sg.merge_public_page(store, p1['wins'])
    assert new2 == 0 and changed2 == 0


def test_merge_keeps_resolved_appid_on_refresh():
    store = {'version': 1, 'wins': []}
    p1 = sg.parse_won_public(_fx('won_public_page1.html'))
    sg.merge_public_page(store, p1['wins'])
    w = next(w for w in store['wins'] if w['code'] == 'AAAA1')
    w['appid'] = 100010
    sg.merge_public_page(store, p1['wins'])
    assert next(w for w in store['wins'] if w['code'] == 'AAAA1')['appid'] == 100010


def test_resolve_ref_parses_stored_slashless_format():
    # steam_ref is stored as "app/N" / "sub/N" (no leading slash); the resolver
    # must parse that form, not re-run a URL regex against it.
    lib = {100010, 100040}
    assert sg._resolve_ref('app/100010', 'x', lib, None) == 100010
    assert sg._resolve_ref('app/999999', 'x', lib, None) is None
    assert sg._resolve_ref(None, 'x', lib, None) is None
    assert sg._resolve_ref('', 'x', lib, None) is None
    # a real store URL is NOT the stored form and must not resolve here
    assert sg._resolve_ref('https://store.steampowered.com/app/100010', 'x', lib, None) is None


def test_classify_unmatched_offline_branches(monkeypatch):
    # no store link
    assert 'gift card' in sg._classify_unmatched(
        {'steam_ref': None}, None, {}).lower()
    # package whose apps we can see, none owned
    monkeypatch.setattr(sg, '_package_apps', lambda sid, s: [10, 20])
    r = sg._classify_unmatched({'steam_ref': 'sub/900'}, None, {})
    assert 'package' in r.lower() and 'library' in r.lower()
    # appdetails says DLC -> reason names the base game (cache short-circuits network)
    cache = {'777': {'ok': True, 'type': 'dlc', 'name': 'X DLC', 'fullgame_name': 'Base Game'}}
    r = sg._classify_unmatched({'steam_ref': 'app/777'}, None, cache)
    assert r == 'DLC for Base Game'
    # appdetails failed to load (delisted / removed) -> cache marks ok False
    cache = {'888': {'ok': False, 'type': None, 'name': None, 'fullgame_name': None}}
    r = sg._classify_unmatched({'steam_ref': 'app/888'}, None, cache)
    assert 'Delisted' in r or 'removed' in r


def test_pending_pass2_pages_targets_only_unknown_pages():
    store = {'version': 1, 'wins': [
        {'code': f'C{i:04d}', 'won_ts': 10_000 - i,
         'received': (None if i in (60, 130) else True)}
        for i in range(200)
    ]}
    pages = sg.pending_pass2_pages(store)
    # index 60 -> page 2 (+3), index 130 -> page 3 (+4)
    assert pages == [2, 3, 4]
