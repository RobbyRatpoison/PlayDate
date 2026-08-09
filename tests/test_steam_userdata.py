"""Steam userdata account-folder targeting (utils.find_localconfig_path,
utils.read_steam_collections, utils.fetch_local_library) against a synthetic
multi-account userdata tree.

Modeled on a real report: a PC with more than one Steam account's userdata
folder ("0" -- Steam's anonymous placeholder -- the real configured account,
and an unrelated second account). The actual defect wasn't in account
selection when the configured account's files are present and correct (that
already worked) -- it was that when the configured account's own folder/file
couldn't be found, the old code silently fell back to reading a *different*
account's data instead of returning nothing. Verified against the pre-fix
code (git show 727c5ac^:utils.py) before writing these as regression tests:
with the configured account's folder missing entirely, the old
find_localconfig_path/read_steam_collections returned the *other* account's
playtime and collections instead of None/{}.
"""
import json

import vdf

import utils

# Real report: SteamID64 76561198020831227 -> SteamID3 60565499.
STEAM_ID64 = 76561198020831227
STEAMID3 = '60565499'
OTHER_STEAMID3 = '216730178'


def _write_account(root, id3, apps=None, collections=None):
    cfg_dir = root / 'userdata' / id3 / 'config'
    cfg_dir.mkdir(parents=True)

    if apps is not None:
        data = {'UserLocalConfigStore': {'Software': {'Valve': {'Steam': {'apps': apps}}}}}
        (cfg_dir / 'localconfig.vdf').write_text(vdf.dumps(data, pretty=True))

    if collections is not None:
        cloud_dir = cfg_dir / 'cloudstorage'
        cloud_dir.mkdir()
        entries = [
            [f'user-collections.{c["id"]}', {'is_deleted': False, 'value': json.dumps(c)}]
            for c in collections
        ]
        (cloud_dir / 'cloud-storage-namespace-1.json').write_text(json.dumps(entries))


def _install(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, 'find_steam_root', lambda: str(tmp_path))


def test_targets_configured_account_among_multiple(tmp_path, monkeypatch):
    """With all three accounts present and correct, the configured account's
    own data must win -- not "0"'s, not the unrelated second account's."""
    _write_account(tmp_path, '0', apps={})  # anonymous placeholder: present, empty
    _write_account(
        tmp_path, STEAMID3,
        apps={'440': {'Playtime': '120', 'LastPlayed': '1700000000'}},
        collections=[{'id': 'fav', 'name': 'Favorites', 'added': [440, 10]}],
    )
    _write_account(tmp_path, OTHER_STEAMID3, apps={'570': {'Playtime': '999'}})
    _install(tmp_path, monkeypatch)

    assert utils.find_localconfig_path(STEAM_ID64) == \
        str(tmp_path / 'userdata' / STEAMID3 / 'config' / 'localconfig.vdf')
    assert utils.fetch_local_library(STEAM_ID64) == \
        [{'appid': 440, 'playtime_forever': 120, 'last_played': 1700000000}]
    assert utils.read_steam_collections(STEAM_ID64) == \
        {'fav': {'name': 'Favorites', 'added': [440, 10]}}


def test_account_folder_missing_does_not_fall_back_to_another_account(tmp_path, monkeypatch):
    """The bug: configured account's folder doesn't exist at all. The old
    code fell through to auto-detect and silently returned "0" or, as here,
    a completely different real account's playtime/collections. Confirmed
    this against the pre-fix utils.py -- it returned 216730178's data for a
    request made with STEAM_ID64."""
    _write_account(tmp_path, '0', apps={})
    _write_account(tmp_path, OTHER_STEAMID3, apps={'570': {'Playtime': '999'}},
                    collections=[{'id': 'wl', 'name': 'Wishlist', 'added': [570]}])
    _install(tmp_path, monkeypatch)

    assert utils.find_localconfig_path(STEAM_ID64) is None
    assert utils.fetch_local_library(STEAM_ID64) == []
    assert utils.read_steam_collections(STEAM_ID64) == {}


def test_account_folder_exists_but_localconfig_missing_does_not_fall_back(tmp_path, monkeypatch):
    """Folder exists (so it's not a total stranger to this PC) but has no
    localconfig.vdf -- plausible if Steam hasn't fully synced/logged that
    account in on this particular install. "0" has a real (near-empty) file
    that must not be silently substituted."""
    (tmp_path / 'userdata' / STEAMID3 / 'config').mkdir(parents=True)  # dir only, no localconfig.vdf
    _write_account(tmp_path, '0', apps={})
    _install(tmp_path, monkeypatch)

    assert utils.find_localconfig_path(STEAM_ID64) is None
    assert utils.fetch_local_library(STEAM_ID64) == []


def test_account_folder_exists_but_collections_file_missing_does_not_fall_back(tmp_path, monkeypatch):
    """Matches the exact log line from the report: the account folder is
    found, but cloud-storage-namespace-1.json isn't there (Steam Cloud off,
    or never synced) -- should return no collections, not another account's."""
    _write_account(tmp_path, STEAMID3, apps={'440': {'Playtime': '5'}})  # no collections=...
    _write_account(tmp_path, OTHER_STEAMID3, apps={},
                    collections=[{'id': 'wl', 'name': 'Wishlist', 'added': [570]}])
    _install(tmp_path, monkeypatch)

    assert utils.read_steam_collections(STEAM_ID64) == {}


def test_no_steam_id_still_auto_detects(tmp_path, monkeypatch):
    """Callers with no configured account at all still get the old
    best-effort auto-detect behavior (single-account machines, etc.)."""
    _write_account(tmp_path, STEAMID3, apps={'440': {'Playtime': '5'}},
                    collections=[{'id': 'fav', 'name': 'Favorites', 'added': [440]}])
    _install(tmp_path, monkeypatch)

    assert utils.find_localconfig_path(None) is not None
    assert utils.read_steam_collections(None) == {'fav': {'name': 'Favorites', 'added': [440]}}
