import json
import logging
import os
import shutil
import sys
import threading

from runners.watcher import PluginInstallWatcher

log = logging.getLogger(__name__)

_EPIC_INSTALL_SUBPATH = os.path.join('drive_c', 'Program Files', 'Epic Games')
_WINE_MANIFESTS_SUBPATH = os.path.join('drive_c', 'ProgramData', 'Epic',
                                       'EpicGamesLauncher', 'Data', 'Manifests')

# Native manifest directories where Epic stores .item JSON files per installed game
_MANIFEST_DIRS_WINDOWS = [
    os.path.join(os.environ.get('PROGRAMDATA', r'C:\ProgramData'),
                 'Epic', 'EpicGamesLauncher', 'Data', 'Manifests'),
]
_MANIFEST_DIR_MAC = os.path.expanduser(
    '~/Library/Application Support/Epic/EpicGamesLauncher/Data/Manifests'
)

_POLL_INTERVAL = 15  # seconds between periodic install-status syncs
_poll_timer = None
_poll_lock  = threading.Lock()


def _get_native_manifest_dir():
    """Return the Epic manifest directory for native (non-Wine) installs, or None."""
    if sys.platform == 'win32':
        for d in _MANIFEST_DIRS_WINDOWS:
            if os.path.isdir(d):
                return d
    elif sys.platform == 'darwin':
        if os.path.isdir(_MANIFEST_DIR_MAC):
            return _MANIFEST_DIR_MAC
    return None


def _get_wine_prefix():
    """Return the configured Wine prefix path, or None."""
    try:
        from config import CONFIG_PATH
        with open(CONFIG_PATH, 'r') as f:
            cfg = json.load(f)
        return cfg.get('launchers', {}).get('epic_games', {}).get('prefix', '').strip() or None
    except Exception:
        return None


def _get_wine_install_base():
    """Return the Epic Games install directory inside the configured Wine prefix, or None."""
    prefix = _get_wine_prefix()
    return os.path.join(prefix, _EPIC_INSTALL_SUBPATH) if prefix else None


def _get_wine_manifests_dir():
    """Return the Epic manifest directory inside the configured Wine prefix, or None."""
    prefix = _get_wine_prefix()
    return os.path.join(prefix, _WINE_MANIFESTS_SUBPATH) if prefix else None


def _get_install_base():
    """Return the Epic Games install directory to watch (Wine prefix path), or None."""
    return _get_wine_install_base()


def _read_native_installed_appnames(manifest_dir):
    """Parse .item manifest files; return set of AppName strings for installed games."""
    installed = set()
    try:
        for entry in os.scandir(manifest_dir):
            if not entry.name.endswith('.item'):
                continue
            try:
                with open(entry.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                app_name = data.get('AppName', '')
                if app_name:
                    installed.add(app_name)
            except Exception:
                pass
    except Exception as e:
        log.warning(f'Epic watcher: could not read manifest dir {manifest_dir}: {e}')
    return installed


def _read_wine_installed_dirnames(install_base):
    """Return set of subdirectory names under the Wine Epic install directory."""
    try:
        return {e.name for e in os.scandir(install_base) if e.is_dir()}
    except Exception as e:
        log.warning(f'Epic watcher: could not scan install dir: {e}')
        return set()


def sync_epic_install_status():
    """Update installed flags for all Epic games based on install dir / manifests."""
    from database import get_db

    db = get_db()
    try:
        db.execute("UPDATE games SET installed = 0 WHERE platform = 'epic_games'")

        rows = db.execute(
            "SELECT appid, platform_appname, platform_slug FROM games WHERE platform = 'epic_games'"
        ).fetchall()
        appname_map = {}
        for row in rows:
            name = (row['platform_appname'] or row['platform_slug'] or '').strip()
            if name:
                appname_map[name] = row['appid']

        if not appname_map:
            db.commit()
            return

        native_dir = _get_native_manifest_dir()
        if native_dir:
            installed_names = _read_native_installed_appnames(native_dir)
        else:
            # Prefer Wine manifests dir (.item files have AppName matching platform_appname)
            wine_manifests = _get_wine_manifests_dir()
            if wine_manifests and os.path.isdir(wine_manifests):
                installed_names = _read_native_installed_appnames(wine_manifests)
            else:
                # Fall back to install directory name scanning
                install_base = _get_wine_install_base()
                installed_names = (
                    _read_wine_installed_dirnames(install_base)
                    if install_base and os.path.isdir(install_base)
                    else set()
                )

        for appname, appid in appname_map.items():
            if appname in installed_names:
                db.execute("UPDATE games SET installed = 1 WHERE appid = ?", (appid,))

        db.commit()
    finally:
        db.close()


def find_manifest_for_game(platform_appname):
    """
    Find the .item manifest file for a game by matching the AppName field.
    Returns (manifest_path, data) or (None, None) if not found.
    """
    native_dir = _get_native_manifest_dir()
    manifests_dir = native_dir or _get_wine_manifests_dir()
    if not manifests_dir or not os.path.isdir(manifests_dir):
        return None, None

    try:
        for entry in os.scandir(manifests_dir):
            if not entry.name.endswith('.item'):
                continue
            try:
                with open(entry.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if data.get('AppName') == platform_appname:
                    return entry.path, data
            except Exception:
                pass
    except Exception as e:
        log.warning(f'Epic: could not scan manifests dir: {e}')
    return None, None


def _get_launcher_installed_path():
    """Return the path to LauncherInstalled.dat, or None."""
    if sys.platform == 'win32':
        return os.path.join(os.environ.get('PROGRAMDATA', r'C:\ProgramData'),
                            'Epic', 'UnrealEngineLauncher', 'LauncherInstalled.dat')
    if sys.platform == 'darwin':
        return os.path.expanduser(
            '~/Library/Application Support/Epic/UnrealEngineLauncher/LauncherInstalled.dat')
    prefix = _get_wine_prefix()
    if prefix:
        return os.path.join(prefix, 'drive_c', 'ProgramData', 'Epic',
                            'UnrealEngineLauncher', 'LauncherInstalled.dat')
    return None


def _remove_from_launcher_installed(platform_appname):
    """Remove a game's entry from LauncherInstalled.dat so the launcher stops tracking it."""
    path = _get_launcher_installed_path()
    if not path or not os.path.isfile(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        original = data.get('InstallationList', [])
        filtered = [e for e in original if e.get('AppName') != platform_appname]
        if len(filtered) == len(original):
            return
        data['InstallationList'] = filtered
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        log.info(f'Epic uninstall: removed {platform_appname!r} from LauncherInstalled.dat')
    except Exception as e:
        log.warning(f'Epic uninstall: could not update LauncherInstalled.dat: {e}')


def uninstall_game_files(platform_appname):
    """
    Delete the game's install directory, manifest file, and LauncherInstalled.dat entry.
    Returns (ok: bool, message: str).
    """
    manifest_path, manifest_data = find_manifest_for_game(platform_appname)

    if manifest_data:
        raw_loc = manifest_data.get('InstallLocation', '')
        # Convert Windows path to host path when running under Wine
        if raw_loc and not os.path.isabs(raw_loc):
            raw_loc = ''
        if raw_loc and not os.path.isdir(raw_loc):
            # Translate C:\ path to Wine prefix path
            prefix = _get_wine_prefix()
            if prefix and raw_loc.startswith(('C:\\', 'C:/')):
                rel = raw_loc[3:].replace('\\', os.sep)
                raw_loc = os.path.join(prefix, 'drive_c', rel)

        dir_ok = True
        if raw_loc and os.path.isdir(raw_loc):
            try:
                shutil.rmtree(raw_loc)
                log.info(f'Epic uninstall: removed install dir {raw_loc!r}')
            except Exception as e:
                log.warning(f'Epic uninstall: could not remove {raw_loc!r}: {e}')
                dir_ok = False

        try:
            os.remove(manifest_path)
            log.info(f'Epic uninstall: removed manifest {manifest_path!r}')
        except Exception as e:
            log.warning(f'Epic uninstall: could not remove manifest: {e}')

        _remove_from_launcher_installed(platform_appname)
        if not dir_ok:
            return False, 'Game files could not be deleted — the Epic Launcher may be holding them open, or administrator rights may be required'
        return True, 'Uninstalled'
    else:
        # No manifest found -- game may already be partially uninstalled;
        # fall back to removing the install dir by name if it exists
        install_base = _get_wine_install_base()
        if install_base:
            candidate = os.path.join(install_base, platform_appname)
            if os.path.isdir(candidate):
                try:
                    shutil.rmtree(candidate)
                    log.info(f'Epic uninstall: removed install dir {candidate!r} (no manifest)')
                    _remove_from_launcher_installed(platform_appname)
                    return True, 'Uninstalled (no manifest found)'
                except Exception as e:
                    return False, f'Could not remove install directory: {e}'
        _remove_from_launcher_installed(platform_appname)
        return False, 'Game files not found — may already be uninstalled'


# ── Periodic polling ──────────────────────────────────────────────────────────

def _schedule_poll():
    global _poll_timer
    with _poll_lock:
        _poll_timer = threading.Timer(_POLL_INTERVAL, _poll_tick)
        _poll_timer.daemon = True
        _poll_timer.start()


def _poll_tick():
    try:
        sync_epic_install_status()
    except Exception as e:
        log.warning(f'Epic periodic install sync failed: {e}')
    _schedule_poll()


def start_periodic_sync():
    """Start the periodic install-status polling loop."""
    _schedule_poll()
    log.info(f'Epic install status polling started (every {_POLL_INTERVAL}s)')


def stop_periodic_sync():
    global _poll_timer
    with _poll_lock:
        if _poll_timer:
            _poll_timer.cancel()
            _poll_timer = None


_watcher = PluginInstallWatcher('epic_games', sync_epic_install_status)


def start_epic_watcher(install_base: str):
    _watcher.start(install_base)


def stop_epic_watcher():
    _watcher.stop()
