"""
Emulator support for PlayDate.

User config: emulators.json (list of configured emulator entries)
Built-in data: known_emulators.py (binary names, platforms, extensions)
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from flask import Blueprint, jsonify, request

from known_emulators import KNOWN_EMULATORS, PLATFORM_NAMES

log = logging.getLogger(__name__)

emulators_bp = Blueprint('emulators', __name__)

# ---------------------------------------------------------------------------

try:
    from config import BASE_DIR
except Exception:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

EMULATORS_FILE = os.path.join(BASE_DIR, 'emulators.json')

FLATPAK_EXPORT_DIRS = [
    os.path.expanduser('~/.local/share/flatpak/exports/bin'),
    '/var/lib/flatpak/exports/bin',
] if sys.platform == 'linux' else []

APPIMAGE_SEARCH_DIRS = [
    os.path.expanduser('~/Applications'),
    os.path.expanduser('~/Downloads'),
    os.path.expanduser('~/.local/bin'),
] if sys.platform == 'linux' else []

WIN_EXE_SEARCH_DIRS = [
    os.path.join(os.path.expanduser('~'), 'Downloads'),
    os.path.join(os.path.expanduser('~'), 'Desktop'),
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs'),
] if sys.platform == 'win32' else []

MAC_APP_DIRS = [
    '/Applications',
    os.path.expanduser('~/Applications'),
] if sys.platform == 'darwin' else []

MAC_BREW_DIRS = [
    '/opt/homebrew/bin',   # Apple Silicon
    '/usr/local/bin',      # Intel
] if sys.platform == 'darwin' else []

if sys.platform == 'win32':
    RETROARCH_CORES_DIRS = [
        os.path.join(os.environ.get('APPDATA', ''), 'RetroArch', 'cores'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'RetroArch', 'cores'),
    ]
elif sys.platform == 'darwin':
    RETROARCH_CORES_DIRS = [
        os.path.expanduser('~/Library/Application Support/RetroArch/cores'),
        os.path.expanduser('~/.config/retroarch/cores'),
        '/Applications/RetroArch.app/Contents/Resources/cores',
    ]
else:
    RETROARCH_CORES_DIRS = [
        os.path.expanduser('~/.config/retroarch/cores'),
        os.path.expanduser('~/.var/app/org.libretro.RetroArch/config/retroarch/cores'),
        '/usr/lib/retroarch/cores',
        '/usr/lib/x86_64-linux-gnu/retroarch/cores',
        '/usr/share/libretro/cores',
    ]

_scan_state = {'running': False, 'status': '', 'added': 0, 'error': None}
_scan_lock  = threading.Lock()


# ── Config ──────────────────────────────────────────────────────────────────

def load_emulators() -> list:
    if not os.path.exists(EMULATORS_FILE):
        return []
    try:
        with open(EMULATORS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log.error(f'emulators: load failed: {e}')
        return []


def _save_emulators(emulators: list):
    tmp = EMULATORS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(emulators, f, indent=2)
    os.replace(tmp, EMULATORS_FILE)


def _get_entry(emu_id: str) -> dict | None:
    return next((e for e in load_emulators() if e.get('id') == emu_id), None)


def _known(emu_id: str) -> dict | None:
    return next((e for e in KNOWN_EMULATORS if e['id'] == emu_id), None)


# ── Flatpak permission helpers ───────────────────────────────────────────────

def _flatpak_app_id(binary: str) -> str | None:
    """Return the Flatpak app ID if binary lives in a Flatpak exports dir, else None."""
    for d in FLATPAK_EXPORT_DIRS:
        if os.path.dirname(binary) == d:
            return os.path.basename(binary)
    return None


def _flatpak_grants(app_id: str) -> list[str]:
    """Return effective filesystem grants for a Flatpak app (manifest + user overrides)."""
    try:
        out = subprocess.run(
            ['flatpak', 'info', '--show-permissions', app_id],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:
        return []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith('filesystems='):
            grants = []
            for entry in line[len('filesystems='):].split(';'):
                entry = re.sub(r':(ro|rw|create)$', '', entry.strip())
                if entry:
                    grants.append(entry)
            return grants
    return []


def _flatpak_path_covered(grants: list[str], path: str) -> bool:
    """Return True if any grant covers the given absolute path."""
    home = os.path.expanduser('~')
    path = os.path.realpath(path)
    for grant in grants:
        if grant in ('host', 'host-os'):
            return True
        if grant == 'home':
            if path == home or path.startswith(home + os.sep):
                return True
            continue
        abs_grant = os.path.realpath(os.path.expanduser(grant))
        if path == abs_grant or path.startswith(abs_grant + os.sep):
            return True
    return False


def check_flatpak_warnings(entry: dict) -> list[dict]:
    """Return a list of {platform, message, fix} for any Flatpak access problems."""
    binary = entry.get('binary', '')
    app_id = _flatpak_app_id(binary)
    if not app_id:
        return []
    grants = _flatpak_grants(app_id)
    warnings = []
    for platform_id in entry.get('platforms', {}):
        for rom_dir in _platform_dirs(entry, platform_id):
            if not os.path.isdir(rom_dir):
                continue
            if not _flatpak_path_covered(grants, rom_dir):
                warnings.append({
                    'platform': platform_id,
                    'message':  f'{app_id} (Flatpak) cannot access this folder.',
                    'fix':      f'flatpak override --user --filesystem={rom_dir} {app_id}',
                })
    return warnings


# ── Binary detection ────────────────────────────────────────────────────────

def auto_detect_binary(emu_id: str) -> str:
    known = _known(emu_id)
    if not known:
        return ''
    for name in known['binary_names']:
        path = shutil.which(name)
        if path:
            return path
    # Flatpak export dirs may not be in PATH in the server process context
    for name in known['binary_names']:
        if '.' not in name:
            continue
        for flatpak_dir in FLATPAK_EXPORT_DIRS:
            candidate = os.path.join(flatpak_dir, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    # AppImage search — scan common locations for files matching known patterns
    patterns = [p.lower() for p in known.get('appimage_names', [])]
    if patterns:
        for search_dir in APPIMAGE_SEARCH_DIRS:
            if not os.path.isdir(search_dir):
                continue
            try:
                for fname in os.listdir(search_dir):
                    if not fname.lower().endswith('.appimage'):
                        continue
                    flower = fname.lower()
                    if any(p in flower for p in patterns):
                        full = os.path.join(search_dir, fname)
                        if not os.access(full, os.X_OK):
                            os.chmod(full, os.stat(full).st_mode | 0o111)
                        return full
            except OSError:
                continue
    # macOS: check Homebrew bin dirs which may not be in the server process PATH
    for brew_dir in MAC_BREW_DIRS:
        for name in known['binary_names']:
            candidate = os.path.join(brew_dir, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    # macOS: search .app bundles in /Applications and ~/Applications
    if MAC_APP_DIRS:
        for app_dir in MAC_APP_DIRS:
            try:
                for bundle in os.listdir(app_dir):
                    if not bundle.endswith('.app'):
                        continue
                    macos_dir = os.path.join(app_dir, bundle, 'Contents', 'MacOS')
                    for name in known['binary_names']:
                        candidate = os.path.join(macos_dir, name)
                        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                            return candidate
            except OSError:
                continue
    # Windows: search common locations for .exe files matching known binary names
    if sys.platform == 'win32':
        exe_names = {n.lower() for n in known['binary_names']}
        exe_names |= {n.lower() + '.exe' for n in known['binary_names'] if not n.lower().endswith('.exe')}
        for search_dir in WIN_EXE_SEARCH_DIRS:
            if not os.path.isdir(search_dir):
                continue
            try:
                for fname in os.listdir(search_dir):
                    if fname.lower() in exe_names:
                        return os.path.join(search_dir, fname)
                    # Also check one level deep (e.g. Downloads/rpcs3/rpcs3.exe)
                    sub = os.path.join(search_dir, fname)
                    if os.path.isdir(sub):
                        for inner in os.listdir(sub):
                            if inner.lower() in exe_names:
                                return os.path.join(sub, inner)
            except OSError:
                continue
    return ''


# ── RetroArch core discovery ─────────────────────────────────────────────────

def list_cores_for_platform(platform_id: str) -> list:
    """Return cores found on disk for the given platform, ordered by preference."""
    known = _known('retroarch')
    if not known:
        return []
    candidates = known.get('cores_search', {}).get(platform_id, [])
    found = []
    seen_names = set()
    for cores_dir in RETROARCH_CORES_DIRS:
        if not os.path.isdir(cores_dir):
            continue
        try:
            entries = os.listdir(cores_dir)
        except OSError:
            continue
        for candidate in candidates:
            if candidate in seen_names:
                continue
            for fname in entries:
                stem = fname
                for ext in ('.so', '.dll', '.dylib'):
                    if fname.lower().endswith(ext):
                        stem = fname[:-len(ext)]
                        break
                if stem == candidate:
                    full_path = os.path.join(cores_dir, fname)
                    found.append({'name': candidate, 'path': full_path})
                    seen_names.add(candidate)
                    break
    return found


# ── Platform dir auto-detection ─────────────────────────────────────────────

def _platform_dir_candidates(binary: str = '') -> dict[str, list[str]]:
    home    = os.path.expanduser('~')
    appdata = os.environ.get('APPDATA', '')
    bin_dir = os.path.dirname(binary) if binary else ''
    return {
        'vita3k_app': [
            os.path.join(home, '.local', 'share', 'Vita3K', 'Vita3K', 'ux0'),                      # Linux native
            os.path.join(home, '.var', 'app', 'org.vita3k.Vita3K', 'data', 'Vita3K', 'ux0'),       # Linux Flatpak
            os.path.join(home, 'Library', 'Application Support', 'Vita3K', 'Vita3K', 'ux0'),       # macOS
            os.path.join(appdata, 'Vita3K', 'Vita3K', 'ux0') if appdata else '',                   # Windows AppData
            os.path.join(bin_dir, 'ux0') if bin_dir else '',                                        # Windows portable (next to exe)
        ],
        'ps3_folder': [
            os.path.join(home, '.config', 'rpcs3', 'dev_hdd0', 'game'),                            # Linux native
            os.path.join(home, '.var', 'app', 'net.rpcs3.RPCS3', 'config', 'rpcs3', 'dev_hdd0', 'game'),  # Linux Flatpak
            os.path.join(home, 'Library', 'Application Support', 'rpcs3', 'dev_hdd0', 'game'),     # macOS
            os.path.join(appdata, 'rpcs3', 'dev_hdd0', 'game') if appdata else '',                 # Windows AppData
            os.path.join(bin_dir, 'dev_hdd0', 'game') if bin_dir else '',                          # Windows portable (next to exe)
        ],
    }


def auto_detect_platform_dir(emu_id: str, platform_id: str, binary: str = '') -> list[str]:
    known = _known(emu_id)
    scan_mode = (known or {}).get('scan_mode', '')
    found = [p for p in _platform_dir_candidates(binary).get(scan_mode, []) if p and os.path.isdir(p)]
    return found


def _platform_dirs(entry: dict, platform_id: str) -> list[str]:
    """Normalize platform dir value (str or list) to a list of non-empty strings."""
    val = entry.get('platforms', {}).get(platform_id, '')
    if isinstance(val, list):
        return [v for v in val if v]
    return [val] if val else []


# ── CRUD ────────────────────────────────────────────────────────────────────

def add_emulator(emu_id: str) -> dict | None:
    known = _known(emu_id)
    if not known:
        return None
    emulators = load_emulators()
    if any(e.get('id') == emu_id for e in emulators):
        return None  # already added
    binary = auto_detect_binary(emu_id)
    entry = {
        'id':      emu_id,
        'binary':  binary,
        'platforms': {p: (auto_detect_platform_dir(emu_id, p, binary) or ['']) for p in known['platforms']},
        'args':    list(known['args']),
        'enabled': True,
    }
    if known.get('cores_search'):
        entry['cores'] = {}
    emulators.append(entry)
    _save_emulators(emulators)
    log.info(f'Emulators: added {known["name"]}')
    return entry


def remove_emulator(emu_id: str):
    emulators = [e for e in load_emulators() if e.get('id') != emu_id]
    _save_emulators(emulators)
    log.info(f'Emulators: removed {emu_id}')


def update_emulator(emu_id: str, binary: str = None,
                    platform_dirs: dict = None, args: list = None,
                    enabled: bool = None, cores: dict = None):
    emulators = load_emulators()
    for e in emulators:
        if e.get('id') != emu_id:
            continue
        if binary is not None:
            e['binary'] = binary
        if platform_dirs is not None:
            e.setdefault('platforms', {}).update(platform_dirs)
        if args is not None:
            e['args'] = args
        if enabled is not None:
            e['enabled'] = enabled
        if cores is not None:
            e.setdefault('cores', {}).update(cores)
        break
    _save_emulators(emulators)


# ── Scan ────────────────────────────────────────────────────────────────────

def get_scan_state() -> dict:
    return dict(_scan_state)


def start_scan(emu_id: str, platform_id: str) -> dict:
    with _scan_lock:
        if _scan_state['running']:
            return {'status': 'already_running'}
        _scan_state.update({'running': True, 'status': 'Starting…', 'added': 0, 'error': None})
    threading.Thread(target=_run_scan, args=(emu_id, platform_id), daemon=True).start()
    return {'status': 'started'}


def start_scan_all() -> dict:
    with _scan_lock:
        if _scan_state['running']:
            return {'status': 'already_running'}
        _scan_state.update({'running': True, 'status': 'Starting…', 'added': 0, 'error': None})
    threading.Thread(target=_run_scan_all, daemon=True).start()
    return {'status': 'started'}


def _extensions_for(emu_id: str, platform_id: str) -> set[str]:
    known = _known(emu_id)
    if known:
        exts = known.get('extensions', {})
        return set(exts.get(platform_id, []) if isinstance(exts, dict) else exts)
    # Custom emulator: fall back to extensions stored in the entry itself
    entry = _get_entry(emu_id)
    if entry:
        exts = entry.get('extensions', {})
        return set(exts.get(platform_id, []) if isinstance(exts, dict) else exts)
    return set()


def add_custom_emulator(name: str, platform_id: str, binary: str = '',
                        args: list = None) -> dict:
    emulators = load_emulators()
    existing_ids = {e['id'] for e in emulators}
    i = 1
    while f'custom_{i}' in existing_ids:
        i += 1
    emu_id = f'custom_{i}'
    # Borrow extensions from any known emulator that supports this platform
    extensions: dict = {}
    for emu in KNOWN_EMULATORS:
        exts = emu.get('extensions', {})
        if isinstance(exts, dict) and platform_id in exts:
            extensions = {platform_id: exts[platform_id]}
            break
    entry: dict = {
        'id':        emu_id,
        'name':      name,
        'binary':    binary,
        'platforms': {platform_id: ''},
        'args':      args or ['{rom}'],
        'enabled':   True,
        'custom':    True,
    }
    if extensions:
        entry['extensions'] = extensions
    emulators.append(entry)
    _save_emulators(emulators)
    log.info(f'Emulators: added custom {name!r} ({platform_id})')
    return entry


def _find_mame_binary() -> str:
    """Return a usable MAME binary path from configured emulators or PATH."""
    entry = _get_entry('mame')
    if entry:
        b = entry.get('binary', '')
        if b and (os.path.isfile(b) or shutil.which(b)):
            return b
    for name in ('mame', 'mame64'):
        found = shutil.which(name)
        if found:
            return found
    known = _known('mame')
    if known:
        for name in known['binary_names']:
            if '.' not in name:
                continue
            for d in FLATPAK_EXPORT_DIRS:
                candidate = os.path.join(d, name)
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate
    return ''


def _mame_lookup_name(binary: str, machine_id: str) -> str | None:
    """Return the human-readable title for a MAME machine ID, or None if unknown."""
    try:
        out = subprocess.run(
            [binary, '-listfull', machine_id],
            capture_output=True, text=True, timeout=10,
        )
        for line in out.stdout.splitlines()[1:]:  # skip header line
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0] == machine_id:
                name = parts[1].strip().strip('"')
                return name if name else None
    except Exception:
        pass
    return None


def _clean_name(filename: str) -> str:
    name = os.path.splitext(filename)[0]
    # Strip region codes, revision tags, disc markers, etc.
    name = re.sub(
        r'\s*[\(\[](USA|EUR|JAP|JPN|PAL|NTSC|World|En|Fr|De|Es|It'
        r'|Rev\s*\w+|v[\d.]+|Disc\s*\d+|!|b\d+|\d{4})[^\)\]]*[\)\]]',
        '', name, flags=re.IGNORECASE,
    )
    name = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]', '', name)
    return name.strip()


def _is_ps3_game_dir(path: str) -> bool:
    return (os.path.isdir(os.path.join(path, 'PS3_GAME')) or
            os.path.isfile(os.path.join(path, 'PS3_DISC.SFB')))


def _read_sfo_title(sfo_path: str) -> str | None:
    """Extract the TITLE string from a param.sfo file."""
    import struct
    try:
        with open(sfo_path, 'rb') as f:
            data = f.read()
        if data[:4] != b'\x00PSF':
            return None
        label_offset = struct.unpack_from('<I', data, 8)[0]
        data_offset  = struct.unpack_from('<I', data, 12)[0]
        num_entries  = struct.unpack_from('<I', data, 16)[0]
        for i in range(num_entries):
            base     = 20 + i * 16
            key_off  = struct.unpack_from('<H', data, base)[0]
            data_len = struct.unpack_from('<I', data, base + 4)[0]
            data_off = struct.unpack_from('<I', data, base + 12)[0]
            key = data[label_offset + key_off:].split(b'\x00')[0].decode('utf-8', errors='replace')
            if key == 'TITLE':
                val = data[data_offset + data_off: data_offset + data_off + data_len]
                title = val.rstrip(b'\x00').decode('utf-8', errors='replace').strip()
                return title or None
    except Exception:
        pass
    return None


def _scan_ps3_folders(platform_id: str, rom_dir: str, db) -> list[tuple[int, str]]:
    """Scan for PS3 folder dumps. Handles Vimm's Lair double-nesting."""
    from database import next_negative_appid

    existing = {
        row['platform_id']
        for row in db.execute(
            "SELECT platform_id FROM games WHERE platform=?", (platform_id,)
        ).fetchall()
    }
    blacklisted = {
        row[0] for row in db.execute(
            "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
        ).fetchall()
    }

    added = []
    try:
        top_entries = sorted(os.scandir(rom_dir), key=lambda e: e.name)
    except OSError:
        return []

    for outer in top_entries:
        if not outer.is_dir():
            continue
        game_dir = None
        if _is_ps3_game_dir(outer.path):
            game_dir = outer.path
        else:
            # One level deeper (Vimm's Lair wraps in an extra folder)
            try:
                for inner in os.scandir(outer.path):
                    if inner.is_dir() and _is_ps3_game_dir(inner.path):
                        game_dir = inner.path
                        break
            except OSError:
                pass
        if not game_dir:
            continue
        if game_dir in existing or game_dir in blacklisted:
            continue
        name  = _clean_name(outer.name)
        appid = next_negative_appid(db)
        db.execute(
            """INSERT OR IGNORE INTO games
               (appid, name, platform, platform_id,
                date_added, completion_status, installed,
                art_fetched, meta_fetched, cheevos_fetched,
                protondb_fetched, hltb_fetched)
               VALUES (?, ?, ?, ?, ?, 'Never Played', 1,
                       '0', '0', '0', '0', '0')""",
            (appid, name, platform_id, game_dir, int(time.time())),
        )
        db.commit()
        existing.add(game_dir)
        added.append((appid, name))
        log.info(f'Emulators: added PS3 {name!r}')
    return added


def _scan_vita3k_app(platform_id: str, rom_dir: str, db) -> list[tuple[int, str]]:
    """Scan Vita3K app directory for installed title IDs."""
    import re as _re
    from database import next_negative_appid

    # Accept either the ux0 root or the app subdir itself
    app_dir = os.path.join(rom_dir, 'app')
    if not os.path.isdir(app_dir):
        app_dir = rom_dir

    existing = {
        row['platform_id']
        for row in db.execute(
            "SELECT platform_id FROM games WHERE platform=?", (platform_id,)
        ).fetchall()
    }
    blacklisted = {
        row[0] for row in db.execute(
            "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
        ).fetchall()
    }

    title_id_re = _re.compile(r'^[A-Z]{4}\d{5}$')
    added = []
    try:
        entries = sorted(os.scandir(app_dir), key=lambda e: e.name)
    except OSError:
        return []

    for entry in entries:
        if not entry.is_dir() or not title_id_re.match(entry.name):
            continue
        title_id = entry.name
        if title_id in existing or title_id in blacklisted:
            continue
        sfo_path = os.path.join(entry.path, 'sce_sys', 'param.sfo')
        name = _read_sfo_title(sfo_path) or title_id
        appid = next_negative_appid(db)
        db.execute(
            """INSERT OR IGNORE INTO games
               (appid, name, platform, platform_id,
                date_added, completion_status, installed,
                art_fetched, meta_fetched, cheevos_fetched,
                protondb_fetched, hltb_fetched)
               VALUES (?, ?, ?, ?, ?, 'Never Played', 1,
                       '0', '0', '0', '0', '0')""",
            (appid, name, platform_id, title_id, int(time.time())),
        )
        db.commit()
        existing.add(title_id)
        added.append((appid, name))
        log.info(f'Emulators: added Vita3K {title_id!r} as {name!r}')
    return added


def _dispatch_scan(emu_id: str, platform_id: str, rom_dir: str, db) -> list[tuple[int, str]]:
    known     = _known(emu_id)
    scan_mode = (known or {}).get('scan_mode')
    if scan_mode == 'ps3_folder':
        return _scan_ps3_folders(platform_id, rom_dir, db)
    if scan_mode == 'vita3k_app':
        return _scan_vita3k_app(platform_id, rom_dir, db)
    return _scan_dir(emu_id, platform_id, rom_dir, db)


def _scan_dir(emu_id: str, platform_id: str, rom_dir: str, db) -> list[tuple[int, str]]:
    """Scan a single directory; returns list of (appid, name) pairs added."""
    from database import next_negative_appid

    extensions = _extensions_for(emu_id, platform_id)
    if not extensions:
        log.warning(f'emulators: no extensions for {emu_id}/{platform_id}')
        return []

    existing = {
        row['platform_id']
        for row in db.execute(
            "SELECT platform_id FROM games WHERE platform=?", (platform_id,)
        ).fetchall()
    }
    blacklisted = {
        row[0] for row in db.execute(
            "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
        ).fetchall()
    }

    entry        = _get_entry(emu_id)
    binary       = (entry or {}).get('binary', '')
    uses_mame_ids = emu_id in ('mame', 'fbneo')
    mame_binary  = binary if emu_id == 'mame' else (_find_mame_binary() if emu_id == 'fbneo' else '')

    added = []
    for fname in sorted(os.listdir(rom_dir)):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in extensions:
            continue
        rom_path = os.path.join(rom_dir, fname)
        if rom_path in existing or rom_path in blacklisted:
            continue
        machine_id = os.path.splitext(fname)[0]
        if uses_mame_ids and mame_binary:
            name = _mame_lookup_name(mame_binary, machine_id) or machine_id
        else:
            name = _clean_name(fname)
        appid = next_negative_appid(db)
        db.execute(
            """INSERT OR IGNORE INTO games
               (appid, name, platform, platform_id,
                date_added, completion_status, installed,
                art_fetched, meta_fetched, cheevos_fetched,
                protondb_fetched, hltb_fetched)
               VALUES (?, ?, ?, ?, ?, 'Never Played', 1,
                       '0', '0', '0', '0', '0')""",
            (appid, name, platform_id, rom_path, int(time.time())),
        )
        db.commit()
        existing.add(rom_path)
        added.append((appid, name))
        log.info(f'Emulators: added {name!r} ({platform_id})')
    return added


def _fetch_art_for_rom(appid: int, name: str):
    """Search SGDB by name and download all three art types for a ROM game."""
    from images import download_vertical, download_horizontal, download_icon, _sgdb_search_game_id
    from database import update_game_data
    from datetime import datetime
    today   = datetime.now().strftime('%Y-%m-%d')
    sgdb_id = _sgdb_search_game_id(name) if name else None
    v = download_vertical(appid, sgdb_id=sgdb_id)
    h = download_horizontal(appid, sgdb_id=sgdb_id)
    i = download_icon(appid, '', sgdb_id=sgdb_id)
    update_game_data(appid, vertical_art_source=v, horizontal_art_source=h,
                     icon_source=i, art_fetched=today)


def _run_scan(emu_id: str, platform_id: str):
    global _scan_state
    try:
        from database import get_db
        entry = _get_entry(emu_id)
        if not entry:
            raise RuntimeError(f'Emulator {emu_id!r} not configured')
        rom_dirs = [d for d in _platform_dirs(entry, platform_id) if os.path.isdir(d)]
        if not rom_dirs:
            raise RuntimeError(f'No valid ROM folder configured for {platform_id}')
        db    = get_db()
        added = []
        for rom_dir in rom_dirs:
            _scan_state['status'] = f'Scanning {os.path.basename(rom_dir)}…'
            added.extend(_dispatch_scan(emu_id, platform_id, rom_dir, db))
        db.close()
        plat_label = PLATFORM_NAMES.get(platform_id, platform_id)
        n = len(added)
        _scan_state.update({
            'running': False,
            'status':  f'{plat_label}: {n} game{"s" if n != 1 else ""} added.',
            'added':   n,
        })
        for appid, name in added:
            try:
                _fetch_art_for_rom(appid, name)
                time.sleep(0.5)
            except Exception as e:
                log.warning(f'Emulators: art fetch failed for {name!r}: {e}')
    except Exception as e:
        log.error(f'emulators scan error: {e}', exc_info=True)
        _scan_state.update({'running': False, 'status': '', 'error': 'Scan failed. Check playdate.log for details.'})


def _run_scan_all():
    global _scan_state
    try:
        from database import get_db
        db        = get_db()
        all_added = []
        emulators = load_emulators()
        for entry in emulators:
            if not entry.get('enabled', True):
                continue
            emu_id = entry['id']
            for platform_id in entry.get('platforms', {}):
                plat_label = PLATFORM_NAMES.get(platform_id, platform_id)
                for rom_dir in _platform_dirs(entry, platform_id):
                    if not os.path.isdir(rom_dir):
                        continue
                    _scan_state['status'] = f'Scanning {plat_label}…'
                    all_added.extend(_dispatch_scan(emu_id, platform_id, rom_dir, db))
        db.close()
        n = len(all_added)
        _scan_state.update({
            'running': False,
            'status':  f'Done — {n} game{"s" if n != 1 else ""} added.',
            'added':   n,
        })
        for appid, name in all_added:
            try:
                _fetch_art_for_rom(appid, name)
                time.sleep(0.5)
            except Exception as e:
                log.warning(f'Emulators: art fetch failed for {name!r}: {e}')
    except Exception as e:
        log.error(f'emulators scan all error: {e}', exc_info=True)
        _scan_state.update({'running': False, 'status': '', 'error': 'Scan failed. Check playdate.log for details.'})


# ── Launch ──────────────────────────────────────────────────────────────────

def is_emulation_platform(platform_id: str) -> bool:
    return platform_id in PLATFORM_NAMES


def sync_emulated_install_status() -> int:
    """
    Re-verify `installed` for every emulated game by checking its ROM file
    (stored as platform_id) still exists on disk. Unlike Steam/plugin installs,
    nothing else ever re-checks this after the initial scan -- a deleted or
    moved ROM leaves the game showing installed forever otherwise, and a
    cross-machine backup restore is the most common way for every ROM path to
    go stale at once. Returns the number of rows whose flag changed.
    """
    from database import get_db
    if not PLATFORM_NAMES:
        return 0
    db = get_db()
    placeholders = ','.join('?' * len(PLATFORM_NAMES))
    rows = db.execute(
        f"SELECT appid, platform_id, installed FROM games WHERE platform IN ({placeholders})",
        list(PLATFORM_NAMES.keys()),
    ).fetchall()
    changed = 0
    for row in rows:
        rom_path = row['platform_id'] or ''
        now_installed = 1 if (rom_path and os.path.isfile(rom_path)) else 0
        if row['installed'] != now_installed:
            db.execute("UPDATE games SET installed = ? WHERE appid = ?", (now_installed, row['appid']))
            changed += 1
    db.commit()
    db.close()
    return changed


def resync_emulator_binaries() -> bool:
    """
    Re-detect any configured emulator binary that no longer exists at its
    stored path (e.g. after a cross-machine restore, or the binary was moved/
    reinstalled elsewhere). Only applies to known emulators -- custom ones have
    no registry entry to re-detect from, so a stale custom binary is left as-is
    for the user to fix manually rather than silently blanked. Returns whether
    any entry was updated.
    """
    entries = load_emulators()
    changed = False
    for entry in entries:
        binary = entry.get('binary', '')
        if binary and os.path.isfile(binary) and os.access(binary, os.X_OK):
            continue
        if entry.get('custom'):
            continue
        redetected = auto_detect_binary(entry['id'])
        if redetected and redetected != binary:
            entry['binary'] = redetected
            changed = True
            log.info(f"emulators: re-detected binary for {entry['id']}: {redetected}")
    if changed:
        _save_emulators(entries)
    return changed


def launch_game(appid: int) -> dict:
    from database import get_db
    db  = get_db()
    row = db.execute(
        "SELECT platform, platform_id FROM games WHERE appid=?", (appid,)
    ).fetchone()
    db.close()
    if not row:
        return {'status': 'error', 'message': 'Game not found'}

    platform_id = row['platform']
    rom_path    = row['platform_id']

    # Find a configured emulator that handles this platform
    entry = next(
        (e for e in load_emulators()
         if platform_id in e.get('platforms', {}) and e.get('enabled', True)),
        None,
    )
    if not entry:
        return {'status': 'error', 'message': f'No emulator configured for {PLATFORM_NAMES.get(platform_id, platform_id)}'}

    known_def = _known(entry['id'])
    scan_mode = (known_def or {}).get('scan_mode')

    if scan_mode == 'ps3_folder':
        if not rom_path or not os.path.isdir(rom_path):
            return {'status': 'error', 'message': 'Game folder not found'}
    elif scan_mode == 'vita3k_app':
        if not rom_path:
            return {'status': 'error', 'message': 'Title ID not set'}
    else:
        if not rom_path or not os.path.isfile(rom_path):
            return {'status': 'error', 'message': 'ROM file not found'}

    binary = entry.get('binary', '')
    if not binary or not os.path.isfile(binary):
        binary = shutil.which(binary or '') or ''
    if not binary:
        return {'status': 'error', 'message': f'Emulator binary not found: {entry.get("binary", "")}'}

    raw_args = entry.get('args', ['{rom}'])
    core_path = ''
    if any('{core}' in a for a in raw_args):
        core_path = entry.get('cores', {}).get(platform_id, '')
        if not core_path or not os.path.isfile(core_path):
            return {'status': 'error', 'message': f'No core configured for {PLATFORM_NAMES.get(platform_id, platform_id)} — set one in Emulators settings'}
    rom_dir  = os.path.dirname(rom_path) if os.sep in rom_path else ''
    rom_name = os.path.splitext(os.path.basename(rom_path))[0] if os.sep in rom_path else rom_path
    args = [
        a.replace('{rom}', rom_path)
         .replace('{core}', core_path)
         .replace('{rom_dir}', rom_dir)
         .replace('{rom_name}', rom_name)
        for a in raw_args
    ]
    cmd  = [binary] + args

    app_id = _flatpak_app_id(binary)
    if app_id and scan_mode != 'vita3k_app':
        grants = _flatpak_grants(app_id)
        check_path = rom_path if scan_mode != 'ps3_folder' else rom_path
        if not _flatpak_path_covered(grants, check_path):
            fix = f'flatpak override --user --filesystem={os.path.dirname(check_path)} {app_id}'
            return {'status': 'flatpak_error', 'message': f'{app_id} cannot access this file.', 'fix': fix}

    try:
        from runners.launch import popen_checked
        _, err = popen_checked(cmd)
        if err:
            log.error(f'Emulators: {err["message"]}')
            return err
        log.info(f'Emulators: launched {rom_path!r} via {binary}')
        return {'status': 'success'}
    except Exception as e:
        log.error(f'Emulators: launch failed: {e}', exc_info=True)
        return {'status': 'error', 'message': 'Launch failed. Check playdate.log for details.'}


# ── Routes ───────────────────────────────────────────────────────────────────

@emulators_bp.route('/api/emulators')
def emulators_list():
    entries  = load_emulators()
    known_map = {e['id']: e for e in KNOWN_EMULATORS}
    result = []
    for entry in entries:
        known     = known_map.get(entry['id'], {})
        has_cores = bool(known.get('cores_search'))
        stored_cores = entry.get('cores', {})
        result.append({
            'id':       entry['id'],
            'name':     known.get('name') or entry.get('name') or entry['id'],
            'binary':   entry.get('binary', ''),
            'enabled':  entry.get('enabled', True),
            'args':     entry.get('args', ['{rom}']),
            'has_cores': has_cores,
            'custom':   entry.get('custom', False),
            'platforms': {
                p: {
                    'dirs':  _platform_dirs(entry, p),
                    'label': PLATFORM_NAMES.get(p, p),
                    'core':  stored_cores.get(p, '') if has_cores else None,
                }
                for p in known.get('platforms', list(entry.get('platforms', {}).keys()))
            },
            'flatpak_warnings': check_flatpak_warnings(entry),
        })
    return jsonify(result)

@emulators_bp.route('/api/emulators/known')
def emulators_known():
    configured_ids = {e.get('id') for e in load_emulators()}
    return jsonify([
        {
            'id':       e['id'],
            'name':     e['name'],
            'platforms': [PLATFORM_NAMES.get(p, p) for p in e['platforms']],
            'added':    e['id'] in configured_ids,
        }
        for e in KNOWN_EMULATORS
    ])

@emulators_bp.route('/api/emulators/add', methods=['POST'])
def emulators_add():
    emu_id = (request.get_json(silent=True) or {}).get('id', '')
    entry  = add_emulator(emu_id)
    if entry is None:
        return jsonify({'error': 'Unknown emulator or already added'}), 400
    return jsonify({'status': 'ok', 'entry': entry})

@emulators_bp.route('/api/emulators/remove', methods=['POST'])
def emulators_remove():
    emu_id = (request.get_json(silent=True) or {}).get('id', '')
    remove_emulator(emu_id)
    return jsonify({'status': 'ok'})

@emulators_bp.route('/api/emulators/update', methods=['POST'])
def emulators_update():
    data         = request.get_json(silent=True) or {}
    emu_id       = data.get('id', '')
    binary       = data.get('binary')
    platform_dirs = data.get('platform_dirs')
    args         = data.get('args')
    enabled      = data.get('enabled')
    cores = data.get('cores')
    update_emulator(emu_id, binary=binary, platform_dirs=platform_dirs,
                    args=args, enabled=enabled, cores=cores)
    entry = _get_entry(emu_id)
    warnings = check_flatpak_warnings(entry) if entry else []
    return jsonify({'status': 'ok', 'flatpak_warnings': warnings})

@emulators_bp.route('/api/emulators/platforms')
def emulators_platforms():
    return jsonify([{'id': k, 'label': v} for k, v in PLATFORM_NAMES.items()])

@emulators_bp.route('/api/emulators/by-platform')
def emulators_by_platform():
    configured = {e.get('id') for e in load_emulators()}
    plat_map = {pid: {'id': pid, 'label': label, 'emulators': []}
                for pid, label in PLATFORM_NAMES.items()}
    for emu in KNOWN_EMULATORS:
        for pid in emu.get('platforms', []):
            if pid in plat_map:
                plat_map[pid]['emulators'].append({
                    'id':    emu['id'],
                    'name':  emu['name'],
                    'added': emu['id'] in configured,
                })
    result = sorted(plat_map.values(), key=lambda p: p['label'])
    return jsonify(result)

@emulators_bp.route('/api/emulators/add-custom', methods=['POST'])
def emulators_add_custom():
    data     = request.get_json(silent=True) or {}
    name     = (data.get('name') or '').strip()
    platform = (data.get('platform') or '').strip()
    binary   = (data.get('binary') or '').strip()
    args     = data.get('args') or ['{rom}']
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if not platform:
        return jsonify({'error': 'Platform is required'}), 400
    entry = add_custom_emulator(name, platform, binary=binary, args=args)
    return jsonify({'status': 'ok', 'entry': entry})

@emulators_bp.route('/api/emulators/detect', methods=['POST'])
def emulators_detect():
    emu_id = (request.get_json(silent=True) or {}).get('id', '')
    path   = auto_detect_binary(emu_id)
    if path:
        update_emulator(emu_id, binary=path)
    return jsonify({'path': path})

@emulators_bp.route('/api/emulators/retroarch-cores', methods=['POST'])
def emulators_retroarch_cores():
    platform_id = (request.get_json(silent=True) or {}).get('platform', '')
    return jsonify(list_cores_for_platform(platform_id))

@emulators_bp.route('/api/emulators/scan', methods=['POST'])
def emulators_scan():
    data        = request.get_json(silent=True) or {}
    emu_id      = data.get('id', '')
    platform_id = data.get('platform', '')
    result      = start_scan(emu_id, platform_id)
    return jsonify(result)

@emulators_bp.route('/api/emulators/scan-all', methods=['POST'])
def emulators_scan_all():
    return jsonify(start_scan_all())

@emulators_bp.route('/api/emulators/scan-status')
def emulators_scan_status():
    return jsonify(get_scan_state())
