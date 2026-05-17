r"""
watcher.py — Install status watcher for Ubisoft Connect games.

Ubisoft Connect stores manifests in:
  Windows: %ProgramData%\Ubisoft\Ubisoft Game Launcher\games.json  (or per-game dirs)
  Wine:    {prefix}/drive_c/ProgramData/Ubisoft/Ubisoft Game Launcher/
"""

import json
import logging
import os
import sys
import threading

from runners.watcher import PluginInstallWatcher

log = logging.getLogger(__name__)

_UBI_DATA_SUBPATH = os.path.join(
    'drive_c', 'ProgramData', 'Ubisoft', 'Ubisoft Game Launcher'
)
_UBI_GAMES_SUBPATH = os.path.join(
    'drive_c', 'Program Files (x86)', 'Ubisoft', 'Ubisoft Game Launcher', 'games'
)

_MANIFEST_DIRS_WINDOWS = [
    os.path.join(os.environ.get('PROGRAMDATA', r'C:\ProgramData'),
                 'Ubisoft', 'Ubisoft Game Launcher'),
]
_MANIFEST_DIR_MAC = None  # No macOS Ubisoft Connect launcher

_POLL_INTERVAL = 30
_poll_timer    = None
_poll_lock     = threading.Lock()


def _get_wine_prefix():
    try:
        from config import CONFIG_PATH
        with open(CONFIG_PATH, 'r') as f:
            cfg = json.load(f)
        return cfg.get('launchers', {}).get('ubisoft', {}).get('prefix', '').strip() or None
    except Exception:
        return None


def _get_ubi_data_dir():
    """Return path to Ubisoft Game Launcher data dir (manifests/configs)."""
    if sys.platform == 'win32':
        for d in _MANIFEST_DIRS_WINDOWS:
            if os.path.isdir(d):
                return d
        return None
    prefix = _get_wine_prefix()
    return os.path.join(prefix, _UBI_DATA_SUBPATH) if prefix else None


def _get_wine_install_base():
    prefix = _get_wine_prefix()
    return os.path.join(prefix, _UBI_GAMES_SUBPATH) if prefix else None


def _read_installed_space_ids(data_dir):
    """
    Parse Ubisoft launcher data dir to find installed game spaceIds.
    Ubisoft stores a 'configurations' folder with per-game JSON or an 'games' registry.
    Returns a set of spaceId strings.
    """
    installed = set()

    # Try configurations directory (each file is a spaceId.json)
    configs_dir = os.path.join(data_dir, 'configurations')
    if os.path.isdir(configs_dir):
        for entry in os.scandir(configs_dir):
            if entry.name.endswith('.json'):
                space_id = entry.name[:-5]
                try:
                    with open(entry.path, 'r', encoding='utf-8', errors='replace') as f:
                        data = json.load(f)
                    if data.get('root', {}).get('installer', {}).get('game_identifier'):
                        installed.add(space_id)
                except Exception:
                    pass

    # Fallback: settings.yaml / settings.json that may list installed games
    for fname in ('settings.json', 'settings.yaml'):
        path = os.path.join(data_dir, fname)
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    data = json.load(f)
                for game in data.get('games', []):
                    sid = str(game.get('spaceId') or game.get('space_id') or '')
                    if sid:
                        installed.add(sid)
            except Exception:
                pass

    return installed


def _read_installed_from_dirs(install_base):
    """
    Scan the Ubisoft games install directory for subdirectories.
    Returns a set of directory names (game folder names, not spaceIds).
    Used as a last-resort fallback.
    """
    try:
        return {e.name for e in os.scandir(install_base) if e.is_dir()}
    except Exception:
        return set()


def sync_ubisoft_install_status():
    """Update installed flags for all Ubisoft games."""
    from database import get_db

    db = get_db()
    try:
        db.execute("UPDATE games SET installed = 0 WHERE platform = 'ubisoft'")

        rows = db.execute(
            "SELECT appid, platform_id FROM games WHERE platform = 'ubisoft'"
        ).fetchall()
        space_map = {row['platform_id']: row['appid'] for row in rows if row['platform_id']}

        if not space_map:
            db.commit()
            return

        data_dir = _get_ubi_data_dir()
        if data_dir and os.path.isdir(data_dir):
            installed_ids = _read_installed_space_ids(data_dir)
            for space_id, appid in space_map.items():
                if space_id in installed_ids:
                    db.execute("UPDATE games SET installed = 1 WHERE appid = ?", (appid,))

        db.commit()
    finally:
        db.close()


# ── Periodic polling ──────────────────────────────────────────────────────────

def _schedule_poll():
    global _poll_timer
    with _poll_lock:
        _poll_timer = threading.Timer(_POLL_INTERVAL, _poll_tick)
        _poll_timer.daemon = True
        _poll_timer.start()


def _poll_tick():
    try:
        sync_ubisoft_install_status()
    except Exception as e:
        log.warning(f'Ubisoft periodic install sync failed: {e}')
    _schedule_poll()


def start_periodic_sync():
    _schedule_poll()
    log.info(f'Ubisoft install status polling started (every {_POLL_INTERVAL}s)')


def stop_periodic_sync():
    global _poll_timer
    with _poll_lock:
        if _poll_timer:
            _poll_timer.cancel()
            _poll_timer = None


_watcher = PluginInstallWatcher('ubisoft', sync_ubisoft_install_status)


def start_ubisoft_watcher(watch_path: str):
    _watcher.start(watch_path)


def stop_ubisoft_watcher():
    _watcher.stop()
