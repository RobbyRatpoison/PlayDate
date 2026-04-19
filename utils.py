import os
import platform
import re
import struct
import logging
from database import get_db, update_game_data
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ── Install status change flag ────────────────────────────────────────────────
_install_status_dirty = False

def consume_install_dirty():
    """Return True (and reset) if install status changed since last call."""
    global _install_status_dirty
    dirty = _install_status_dirty
    _install_status_dirty = False
    return dirty

# ── Steamapps filesystem watcher ──────────────────────────────────────────────
_watcher_observer = None


def start_steamapps_watcher(steamapps_path: str):
    """
    Watch the steamapps folder for appmanifest_*.acf changes and automatically
    update installed status in the DB.  Safe to call from any thread.
    Returns the Observer instance (already started), or None if watchdog is
    unavailable or the path doesn't exist.
    """
    global _watcher_observer

    if not steamapps_path or not os.path.isdir(steamapps_path):
        log.warning(f"Steamapps watcher: path not found — {steamapps_path!r}")
        return None

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        log.warning("watchdog not installed — filesystem watcher disabled")
        return None

    class _ManifestHandler(FileSystemEventHandler):
        """Reacts to appmanifest_*.acf create / delete / move events."""

        def _is_manifest(self, path: str) -> bool:
            name = os.path.basename(path)
            return name.startswith("appmanifest_") and name.endswith(".acf")

        def _on_change(self, event_type: str, path: str):
            if self._is_manifest(path):
                log.info(f"Steamapps watcher: {event_type} — {os.path.basename(path)} — syncing install status")
                try:
                    sync_local_install_status()
                except Exception as e:
                    log.error(f"Steamapps watcher: sync failed — {e}")

        def on_created(self, event):
            if not event.is_directory:
                self._on_change("created", event.src_path)

        def on_deleted(self, event):
            if not event.is_directory:
                self._on_change("deleted", event.src_path)

        def on_moved(self, event):
            if not event.is_directory:
                # A move in or out of the folder both matter
                self._on_change("moved", event.dest_path)

    stop_steamapps_watcher()  # stop any previous instance

    observer = Observer()
    observer.schedule(_ManifestHandler(), path=steamapps_path, recursive=False)
    observer.start()
    _watcher_observer = observer
    log.info(f"Steamapps watcher started on: {steamapps_path}")
    return observer


def stop_steamapps_watcher():
    """Stop the running observer, if any."""
    global _watcher_observer
    if _watcher_observer is not None:
        try:
            _watcher_observer.stop()
            _watcher_observer.join(timeout=3)
        except Exception as e:
            log.warning(f"Steamapps watcher stop error: {e}")
        _watcher_observer = None


# ── GOG filesystem watcher ─────────────────────────────────────────────────────
_gog_watcher_observer = None


def sync_gog_install_status():
    """Update installed flags for all GOG games based on whether their install_path exists on disk."""
    global _install_status_dirty
    db = get_db()
    rows = db.execute("SELECT appid, install_path FROM games WHERE platform = 'gog'").fetchall()
    installed_ids = [row['appid'] for row in rows if row['install_path'] and os.path.isdir(row['install_path'])]
    db.execute("UPDATE games SET installed = 0 WHERE platform = 'gog'")
    if installed_ids:
        db.executemany("UPDATE games SET installed = 1 WHERE appid = ?", [(a,) for a in installed_ids])
    db.commit()
    db.close()
    _install_status_dirty = True


def start_gog_watcher(gog_install_base: str):
    """
    Watch the GOG games folder for directory-level changes and automatically
    update installed status in the DB.  Safe to call from any thread.
    Returns the Observer instance (already started), or None if watchdog is
    unavailable or the path doesn't exist.  No-ops if already running.
    """
    global _gog_watcher_observer

    if _gog_watcher_observer is not None:
        return _gog_watcher_observer

    if not gog_install_base or not os.path.isdir(gog_install_base):
        log.warning(f"GOG watcher: path not found — {gog_install_base!r}")
        return None

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        log.warning("watchdog not installed — GOG filesystem watcher disabled")
        return None

    class _GogInstallHandler(FileSystemEventHandler):
        def _on_change(self, event_type: str, path: str):
            log.info(f"GOG watcher: {event_type} — {os.path.basename(path)} — syncing install status")
            try:
                sync_gog_install_status()
            except Exception as e:
                log.error(f"GOG watcher: sync failed — {e}")

        def on_created(self, event):
            if event.is_directory:
                self._on_change("created", event.src_path)

        def on_deleted(self, event):
            if event.is_directory:
                self._on_change("deleted", event.src_path)

        def on_moved(self, event):
            if event.is_directory:
                self._on_change("moved", event.dest_path)

    observer = Observer()
    observer.schedule(_GogInstallHandler(), path=gog_install_base, recursive=False)
    observer.start()
    _gog_watcher_observer = observer
    log.info(f"GOG watcher started on: {gog_install_base}")
    return observer


def stop_gog_watcher():
    global _gog_watcher_observer
    if _gog_watcher_observer is not None:
        try:
            _gog_watcher_observer.stop()
            _gog_watcher_observer.join(timeout=3)
        except Exception as e:
            log.warning(f"GOG watcher stop error: {e}")
        _gog_watcher_observer = None


def find_steam_path():
    """Attempts to locate the Steam installation path, prioritizing Linux."""
    defaults = [
        os.path.expanduser("~/.steam/steam/steamapps"),
        os.path.expanduser("~/.local/share/Steam/steamapps"),
        "C:/Program Files (x86)/Steam/steamapps",
        "C:/Program Files/Steam/steamapps",
        os.path.expanduser("~/Library/Application Support/Steam/steamapps"),
    ]

    for path in defaults:
        if os.path.exists(path):
            return path

    if platform.system() == "Windows":
        try:
            import winreg
            for key_path in [r"SOFTWARE\WOW6432Node\Valve\Steam", r"SOFTWARE\Valve\Steam"]:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    path, _ = winreg.QueryValueEx(key, "InstallPath")
                    if path:
                        return os.path.join(path, "steamapps")
        except Exception:
            pass

    return None


def detect_steam_id():
    """
    Detects Steam accounts from the userdata folder.
    Returns a list of {'steam_id': str, 'name': str} sorted by most recently
    used (localconfig.vdf mtime). Names are pulled from loginusers.vdf.
    Returns an empty list if nothing is found.
    """
    import vdf as vdf_lib
    steam_root = find_steam_root()
    if not steam_root:
        return []

    # Build name map from loginusers.vdf (no API key needed)
    names = {}
    loginusers_path = os.path.join(steam_root, 'config', 'loginusers.vdf')
    if os.path.isfile(loginusers_path):
        try:
            with open(loginusers_path, encoding='utf-8', errors='ignore') as f:
                data = vdf_lib.load(f)
            users = data.get('users', data.get('Users', {}))
            for sid64, info in users.items():
                names[sid64] = info.get('PersonaName') or info.get('AccountName') or sid64
        except Exception:
            pass

    userdata = os.path.join(steam_root, 'userdata')
    if not os.path.isdir(userdata):
        return []

    candidates = []
    for subdir in os.listdir(userdata):
        if not subdir.isdigit():
            continue
        lc_path = os.path.join(userdata, subdir, 'config', 'localconfig.vdf')
        if os.path.isfile(lc_path):
            sid64 = str(int(subdir) + 76561197960265728)
            candidates.append({
                'steam_id': sid64,
                'name': names.get(sid64, sid64),
                '_mtime': os.path.getmtime(lc_path),
            })

    candidates.sort(key=lambda x: x['_mtime'], reverse=True)
    for c in candidates:
        del c['_mtime']
    return candidates


def find_steam_root():
    """Returns the Steam installation root directory (parent of steamapps), or None."""
    steamapps = find_steam_path()
    if steamapps:
        return os.path.dirname(steamapps)
    return None


def find_localconfig_path(steam_id=None):
    """
    Locates localconfig.vdf for the given SteamID64.
    If steam_id is not provided (or the derived folder doesn't exist), falls back
    to auto-detecting the account by listing numeric subdirs of userdata/.
    Returns the file path string, or None if not found.
    """
    steam_root = find_steam_root()
    if not steam_root:
        return None

    userdata = os.path.join(steam_root, 'userdata')
    if not os.path.isdir(userdata):
        return None

    # Try the configured account first (SteamID64 → SteamID3)
    if steam_id:
        try:
            steamid3 = str(int(steam_id) - 76561197960265728)
            candidate = os.path.join(userdata, steamid3, 'config', 'localconfig.vdf')
            if os.path.isfile(candidate):
                return candidate
        except (ValueError, TypeError):
            pass

    # Auto-detect: try every numeric subdir and return the first localconfig found
    for subdir in os.listdir(userdata):
        if subdir.isdigit():
            candidate = os.path.join(userdata, subdir, 'config', 'localconfig.vdf')
            if os.path.isfile(candidate):
                return candidate

    return None


def fetch_local_library(steam_id=None):
    """
    Parses localconfig.vdf and returns a list of dicts for every game that has
    been launched at least once:
        {'appid': int, 'playtime_forever': int (minutes), 'last_played': int (Unix ts) or None}
    Returns an empty list if the file cannot be found or parsed.
    """
    try:
        import vdf
    except ImportError:
        log.error("fetch_local_library: 'vdf' package not installed. Run: pip install vdf")
        return []

    path = find_localconfig_path(steam_id)
    if not path:
        log.warning("fetch_local_library: localconfig.vdf not found")
        return []

    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            data = vdf.load(f)
    except Exception as e:
        log.error(f"fetch_local_library: failed to parse {path} — {e}")
        return []

    try:
        store  = data.get('UserLocalConfigStore', data.get('userlocalconfigstore', {}))
        valve  = store.get('Software', store.get('software', {})).get('Valve', {})
        steam  = valve.get('Steam', valve.get('steam', {}))
        apps   = steam.get('apps', steam.get('Apps', {}))
    except Exception as e:
        log.error(f"fetch_local_library: unexpected VDF structure — {e}")
        return []

    games = []
    for appid_str, info in apps.items():
        if not appid_str.isdigit() or not isinstance(info, dict):
            continue
        try:
            playtime = int(info.get('Playtime', info.get('playtime', 0)))
        except (ValueError, TypeError):
            playtime = 0
        try:
            ts = int(info.get('LastPlayed', info.get('lastplayed', 0)))
            last_played = ts if ts > 0 else None
        except (ValueError, TypeError):
            last_played = None

        games.append({
            'appid':            int(appid_str),
            'playtime_forever': playtime,
            'last_played':      last_played,
        })

    log.info(f"fetch_local_library: found {len(games)} entries in localconfig.vdf")
    return games


def get_acf_names():
    """
    Reads every appmanifest_*.acf file in the steamapps folder and returns a
    dict mapping appid (int) → game name (str) for all installed real games.
    """
    names = {}
    steam_path = find_steam_path()
    if not steam_path or not os.path.isdir(steam_path):
        return names

    for filename in os.listdir(steam_path):
        if not (filename.startswith('appmanifest_') and filename.endswith('.acf')):
            continue
        match = re.search(r'appmanifest_(\d+)\.acf', filename)
        if not match:
            continue
        file_path = os.path.join(steam_path, filename)
        try:
            with open(file_path, encoding='utf-8', errors='ignore') as f:
                content = f.read()
            if not is_real_game(file_path, content):
                continue
            name_match = re.search(r'"name"\s+"([^"]+)"', content)
            if name_match:
                names[int(match.group(1))] = name_match.group(1)
        except Exception:
            pass

    return names

def get_locally_installed_appids():
    """Scans the Steam library for manifest files to find truly installed games."""
    steam_path = find_steam_path()
    if not steam_path or not os.path.exists(steam_path):
        log.warning("Steam path not found. Skipping local scan.")
        return []

    installed_ids = []
    for filename in os.listdir(steam_path):
        if not (filename.startswith("appmanifest_") and filename.endswith(".acf")):
            continue
        match = re.search(r"appmanifest_(\d+)\.acf", filename)
        if match and is_real_game(os.path.join(steam_path, filename)):
            installed_ids.append(int(match.group(1)))
    return installed_ids

def is_real_game(file_path, content=None):
    if content is None:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    # Check for UserConfig - most tools don't have this
    if '"UserConfig"' not in content:
        return False
    if any(term in content for term in ['Steamworks Shared', 'Proton', 'SteamLinuxRuntime', 'EasyAntiCheat', 'Redistributable']):
        return False
    return True

def sync_local_install_status():
    global _install_status_dirty
    local_ids = get_locally_installed_appids()

    # Reset and re-set in a single transaction so there is no window
    # where the DB shows everything as uninstalled.
    # Scope to Steam games only — non-Steam install state is managed separately.
    db = get_db()
    db.execute("UPDATE games SET installed = 0 WHERE platform = 'steam' OR platform IS NULL")
    if local_ids:
        db.executemany("UPDATE games SET installed = 1 WHERE appid = ?",
                       [(a,) for a in local_ids])
    db.commit()
    db.close()

    _install_status_dirty = True
    return len(local_ids) if local_ids else 0

def record_launch(appid):
    db = get_db()
    game = db.execute("SELECT installed, completion_status FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    if game and game['installed'] == 1:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if game['completion_status'] == "Never Played":
            update_game_data(appid, last_played=now_ts, completion_status="Unfinished")
        else:
            update_game_data(appid, last_played=now_ts)
        log.info(f"Recorded launch for appid {appid}")
        return now_ts
    log.debug(f"Launch ignored for appid {appid}: not installed")
    return None

def _get_unique_csv_column(column):
    db = get_db()
    rows = db.execute(f"SELECT {column} FROM games WHERE {column} IS NOT NULL").fetchall()
    db.close()
    values = set()
    for row in rows:
        if row[column]:
            values.update(v.strip() for v in row[column].split(',') if v.strip())
    return sorted(values, key=str.casefold)

def get_all_unique_groups():
    return _get_unique_csv_column('groups')

def get_all_unique_tags():
    return _get_unique_csv_column('tags')

def get_all_unique_genres():
    return _get_unique_csv_column('genres')

def get_all_unique_categories():
    return _get_unique_csv_column('categories')


def parse_appinfo():
    """
    Parses Steam's binary appinfo.vdf (v29) and returns a dict mapping
    appid (int) → {'name': str, 'type': str} for every app in the cache.

    File layout (v29, magic 0x07564429):
      bytes 0-3:  magic
      bytes 4-7:  universe
      bytes 8-11: key_table_offset  (offset of the string-pool key table)
      bytes 12-15: unknown (always 0)
      bytes 16+:  app records, each:
        [4] appid
        [4] size  (bytes following size field through end of record = 60 + VDF bytes)
        [60] metadata (state, timestamps, checksums, change_number)
        [?] VDF binary data keyed by 4-byte IDs into the key table

    Returns {} on any error (file not found, wrong format, etc.).
    """
    steam_root = find_steam_root()
    if not steam_root:
        log.debug("parse_appinfo: Steam root not found")
        return {}

    path = os.path.join(steam_root, 'appcache', 'appinfo.vdf')
    if not os.path.isfile(path):
        log.debug(f"parse_appinfo: {path} not found")
        return {}

    try:
        with open(path, 'rb') as f:
            data = f.read()
    except Exception as e:
        log.error(f"parse_appinfo: read error — {e}")
        return {}

    if len(data) < 16:
        return {}

    magic = struct.unpack('<I', data[0:4])[0]
    if magic != 0x07564429:
        log.warning(f"parse_appinfo: unexpected magic 0x{magic:08x}")
        return {}

    # ── Build key table (string pool at end of file) ───────────────────────
    kt_offset = struct.unpack('<I', data[8:12])[0]
    if kt_offset >= len(data):
        return {}

    keys = {}
    pos = kt_offset + 4  # skip 'BT\x00\x00' marker
    idx = 0
    while pos < len(data):
        end = data.find(b'\x00', pos)
        if end == -1:
            break
        keys[idx] = data[pos:end].decode('utf-8', errors='replace')
        idx += 1
        pos = end + 1

    # Reverse map for the keys we care about
    KEY_APPINFO = None
    KEY_COMMON  = None
    KEY_NAME    = None
    KEY_TYPE    = None
    KEY_STEAM_RELEASE_DATE    = None
    KEY_ORIGINAL_RELEASE_DATE = None
    for kid, kname in keys.items():
        if kname == 'appinfo':                KEY_APPINFO = kid
        elif kname == 'common':               KEY_COMMON = kid
        elif kname == 'name':                 KEY_NAME   = kid
        elif kname == 'type':                 KEY_TYPE   = kid
        elif kname == 'steam_release_date':   KEY_STEAM_RELEASE_DATE = kid
        elif kname == 'original_release_date': KEY_ORIGINAL_RELEASE_DATE = kid

    VALID_TYPES = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07}
    max_key = len(keys)

    def _read_vdf(buf, off, depth=0):
        """Read key-value pairs until end-marker (0x08) or buffer end.
        Returns (dict, new_offset). Nested dicts recurse up to depth 5."""
        result = {}
        while off < len(buf):
            t = buf[off]; off += 1
            if t == 0x08:
                break
            if off + 4 > len(buf):
                break
            kid = struct.unpack('<I', buf[off:off+4])[0]; off += 4
            if kid >= max_key:
                break
            k = keys[kid]
            if t == 0x00:  # nested dict
                if depth < 5:
                    val, off = _read_vdf(buf, off, depth + 1)
                else:
                    # skip past the nested block
                    nest = 1
                    while off < len(buf) and nest > 0:
                        bt = buf[off]; off += 1
                        if bt == 0x00:
                            off += 4  # skip key id
                            nest += 1
                        elif bt == 0x08:
                            nest -= 1
                        elif bt == 0x01:
                            end = buf.find(b'\x00', off)
                            off = (end + 1) if end != -1 else len(buf)
                        elif bt == 0x02:
                            off += 4
                        elif bt == 0x07:
                            off += 8
                        else:
                            off = len(buf)
                    val = {}
            elif t == 0x01:  # inline string
                end = buf.find(b'\x00', off)
                if end == -1: break
                val = buf[off:end].decode('utf-8', errors='replace')
                off = end + 1
            elif t == 0x02:  # int32
                if off + 4 > len(buf): break
                val = struct.unpack('<i', buf[off:off+4])[0]; off += 4
            elif t == 0x07:  # uint64
                if off + 8 > len(buf): break
                val = struct.unpack('<Q', buf[off:off+8])[0]; off += 8
            else:
                break  # unknown type — stop parsing this block
            result[k] = val
        return result, off

    # ── Iterate app records ────────────────────────────────────────────────
    # Record layout: [4 appid][4 size][metadata bytes][VDF data]
    # size = bytes from after size-field to end of record
    # next record at: rec_pos + 4 + 4 + size
    #
    # VDF data always starts with type=0x00 (nested dict) + 4-byte key_id for
    # 'appinfo' (key_id=0 → bytes \x00\x00\x00\x00). Scan for this marker
    # within the first 128 bytes of each record so we don't hardcode the
    # metadata size (which could differ across Steam versions).
    # VDF always starts with type=0x00 (nested dict) + 4-byte key_id for 'appinfo'.
    # Since 'appinfo' is key_id=0, the opener is five zero bytes.
    # The record metadata contains 8 zero bytes for the access_token starting at
    # rec_pos+16, so we begin the scan at rec_pos+48 (past access_token + SHA1_text)
    # to avoid false matches in the metadata region.
    APPINFO_OPENER  = b'\x00' + struct.pack('<I', KEY_APPINFO if KEY_APPINFO is not None else 0)
    SCAN_START_OFF  = 48   # skip fixed metadata (access_token zeros + SHA1 text)
    SCAN_END_OFF    = 128  # metadata is never this large

    result = {}
    rec_pos = 16  # first record

    while rec_pos + 8 <= kt_offset:
        appid = struct.unpack('<I', data[rec_pos:rec_pos+4])[0]
        size  = struct.unpack('<I', data[rec_pos+4:rec_pos+8])[0]
        if appid == 0 and size == 0:
            break  # terminator

        next_pos = rec_pos + 8 + size

        # Locate VDF start by scanning for the 'appinfo' nested-dict opener
        scan_from = rec_pos + SCAN_START_OFF
        scan_to   = min(rec_pos + SCAN_END_OFF, next_pos)
        vdf_start = data.find(APPINFO_OPENER, scan_from, scan_to)

        if vdf_start != -1 and next_pos <= kt_offset:
            try:
                vdf, _ = _read_vdf(data, vdf_start)
                common = vdf.get('appinfo', {}).get('common', {})
                name   = common.get('name', '')
                app_type = common.get('type', '')
                if name or app_type:
                    result[appid] = {
                        'name': name,
                        'type': app_type,
                        'steam_release_date':    common.get('steam_release_date'),
                        'original_release_date': common.get('original_release_date'),
                    }
            except Exception:
                pass

        rec_pos = next_pos

    log.info(f"parse_appinfo: parsed {len(result)} entries from appinfo.vdf")
    return result
