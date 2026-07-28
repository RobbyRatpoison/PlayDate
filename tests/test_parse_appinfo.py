"""Binary appinfo.vdf (v29) parsing (utils.parse_appinfo) against a synthetic file."""
import struct

import utils

MAGIC = 0x07564429

# String pool order defines the key ids the records reference.
KEYS = ['appinfo', 'common', 'name', 'type', 'steam_release_date']
KID = {k: i for i, k in enumerate(KEYS)}


def _vdf(name, app_type, release_ts=None):
    b = b'\x00' + struct.pack('<I', KID['appinfo'])          # nested dict: appinfo
    b += b'\x00' + struct.pack('<I', KID['common'])          # nested dict: common
    b += b'\x01' + struct.pack('<I', KID['name']) + name.encode() + b'\x00'
    b += b'\x01' + struct.pack('<I', KID['type']) + app_type.encode() + b'\x00'
    if release_ts is not None:
        b += b'\x02' + struct.pack('<I', KID['steam_release_date']) + struct.pack('<i', release_ts)
    b += b'\x08'                                             # end common
    b += b'\x08'                                             # end appinfo
    b += b'\x08'                                             # end record
    return b


def _record(appid, vdf):
    # Layout: [4 appid][4 size][60 metadata][vdf]; size covers metadata + vdf.
    # Metadata must be non-zero so the 'appinfo' opener scan (5 zero bytes,
    # starting at record offset 48) doesn't false-match inside it.
    meta = b'\x01' * 60
    return struct.pack('<I', appid) + struct.pack('<I', 60 + len(vdf)) + meta + vdf


def _build_appinfo_file(records):
    body = b''.join(records) + struct.pack('<II', 0, 0)      # records + terminator
    kt_offset = 16 + len(body)
    header = struct.pack('<IIII', MAGIC, 1, kt_offset, 0)
    key_table = b'BT\x00\x00' + b''.join(k.encode() + b'\x00' for k in KEYS)
    return header + body + key_table


def _install(tmp_path, monkeypatch, blob):
    (tmp_path / 'appcache').mkdir()
    (tmp_path / 'appcache' / 'appinfo.vdf').write_bytes(blob)
    monkeypatch.setattr(utils, 'find_steam_root', lambda: str(tmp_path))


def test_parses_names_types_and_release_dates(tmp_path, monkeypatch):
    blob = _build_appinfo_file([
        _record(440, _vdf('Half-Life', 'game', release_ts=1191988800)),
        _record(1000, _vdf('Some Soundtrack', 'music')),
    ])
    _install(tmp_path, monkeypatch, blob)

    result = utils.parse_appinfo()

    assert result[440]['name'] == 'Half-Life'
    assert result[440]['type'] == 'game'
    assert result[440]['steam_release_date'] == 1191988800
    assert result[1000]['name'] == 'Some Soundtrack'
    assert result[1000]['type'] == 'music'
    assert result[1000]['steam_release_date'] is None


def test_wrong_magic_returns_empty(tmp_path, monkeypatch):
    blob = _build_appinfo_file([_record(440, _vdf('Half-Life', 'game'))])
    _install(tmp_path, monkeypatch, b'\xde\xad\xbe\xef' + blob[4:])
    assert utils.parse_appinfo() == {}


def test_truncated_file_returns_empty(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch, struct.pack('<I', MAGIC))
    assert utils.parse_appinfo() == {}


def test_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, 'find_steam_root', lambda: str(tmp_path))
    assert utils.parse_appinfo() == {}


def test_no_steam_root_returns_empty(monkeypatch):
    monkeypatch.setattr(utils, 'find_steam_root', lambda: None)
    assert utils.parse_appinfo() == {}


def test_corrupt_record_does_not_break_others(tmp_path, monkeypatch):
    good = _record(440, _vdf('Half-Life', 'game'))
    # Record whose VDF is garbage — parser should skip it and keep going.
    bad = _record(666, b'\xff' * 30)
    blob = _build_appinfo_file([bad, good])
    _install(tmp_path, monkeypatch, blob)

    result = utils.parse_appinfo()
    assert 440 in result
    assert 666 not in result
