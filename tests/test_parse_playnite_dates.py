"""Playnite backup date extraction (imports.parse_playnite_dates) against a synthetic
LiteDB-shaped games.db. No real Playnite backup was available to test against, so this
validates the proximity-matching logic on its own terms (byte offsets, window boundary,
nearest-neighbor selection) rather than against a real export.
"""
import struct
import zipfile
from datetime import datetime, timezone

import imports

WINDOW = 8192


def _bson_gameid(value):
    b = value.encode() + b'\x00'
    return b'\x02GameId\x00' + struct.pack('<i', len(b)) + b


def _bson_added(date_str):
    dt = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    ms = int(dt.timestamp() * 1000)
    return b'\x09Added\x00' + struct.pack('<q', ms)


def _bson_added_ms(ms):
    return b'\x09Added\x00' + struct.pack('<q', ms)


def _zip_with_games_db(tmp_path, blob, arcname='library/games.db'):
    zip_path = tmp_path / 'backup.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr(arcname, blob)
    return str(zip_path)


def test_pairs_gameid_with_nearby_added(tmp_path):
    blob = (
        b'\x00' * 100
        + _bson_gameid('440')
        + b'\x00' * 50
        + _bson_added('2020-06-15')
        + b'\x00' * 100
        + _bson_gameid('1000')
        + b'\x00' * 50
        + _bson_added('2021-01-02')
    )
    result = imports.parse_playnite_dates(_zip_with_games_db(tmp_path, blob))
    assert result == {440: '2020-06-15', 1000: '2021-01-02'}


def test_picks_nearest_added_when_multiple_candidates(tmp_path):
    # Added2 (100 bytes away) is nearer than Added1 (200 bytes away) — GameId should
    # pair with Added2 regardless of which one appears first in the file.
    blob = (
        _bson_added('1999-01-01')                 # far Added, appears first
        + b'\x00' * 200
        + _bson_gameid('55')
        + b'\x00' * 100
        + _bson_added('2022-03-03')                # near Added, appears after
    )
    result = imports.parse_playnite_dates(_zip_with_games_db(tmp_path, blob))
    assert result == {55: '2022-03-03'}


def test_added_outside_window_is_not_paired(tmp_path):
    blob = (
        _bson_gameid('77')
        + b'\x00' * (WINDOW + 500)
        + _bson_added('2020-01-01')
    )
    result = imports.parse_playnite_dates(_zip_with_games_db(tmp_path, blob))
    assert result == {}


def test_non_digit_gameid_is_ignored(tmp_path):
    # Non-Steam plugin GameIds (GOG/Epic GUIDs etc.) aren't plain digits.
    blob = (
        _bson_gameid('a1b2c3d4-guid')
        + b'\x00' * 50
        + _bson_added('2020-01-01')
    )
    result = imports.parse_playnite_dates(_zip_with_games_db(tmp_path, blob))
    assert result == {}


def test_out_of_range_added_is_ignored(tmp_path):
    blob = (
        _bson_gameid('99')
        + b'\x00' * 50
        + _bson_added_ms(-5000)  # negative ms fails the sanity check
    )
    result = imports.parse_playnite_dates(_zip_with_games_db(tmp_path, blob))
    assert result == {}


def test_backslash_zip_path_is_matched(tmp_path):
    blob = _bson_gameid('440') + b'\x00' * 50 + _bson_added('2020-06-15')
    result = imports.parse_playnite_dates(
        _zip_with_games_db(tmp_path, blob, arcname='library\\games.db')
    )
    assert result == {440: '2020-06-15'}


def test_missing_games_db_returns_empty(tmp_path):
    zip_path = tmp_path / 'backup.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('unrelated/file.txt', b'nothing here')
    assert imports.parse_playnite_dates(str(zip_path)) == {}
