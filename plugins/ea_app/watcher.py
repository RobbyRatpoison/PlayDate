import json
import logging
import os
import sys
import threading

from runners.watcher import PluginInstallWatcher

log = logging.getLogger(__name__)

# EA App stores install manifests in:
#   Windows: %PROGRAMDATA%\EA\EA Desktop\InstallData\
#   Wine:    {prefix}/drive_c/ProgramData/EA/EA Desktop/InstallData/
_EA_INSTALL_DATA_SUBPATH = os.path.join(
    'drive_c', 'ProgramData', 'EA', 'EA Desktop', 'InstallData'
)
_EA_GAMES_SUBPATH = os.path.join(
    'drive_c', 'Program Files', 'EA Games'
)

_MANIFEST_DIRS_WINDOWS = [
    os.path.join(os.environ.get('PROGRAMDATA', r'C:\ProgramData'),
                 'EA', 'EA Desktop', 'InstallData'),
]

_POLL_INTERVAL = 30
_poll_timer    = None
_poll_lock     = threading.Lock()


def _get_wine_prefix():
    try:
        from config import CONFIG_PATH
        with open(CONFIG_PATH, 'r') as f:
            cfg = json.load(f)
        return cfg.get('launchers', {}).get('ea_app', {}).get('prefix', '').strip() or None
    except Exception:
        return None


def _get_install_data_dir():
    if sys.platform == 'win32':
        for d in _MANIFEST_DIRS_WINDOWS:
            if os.path.isdir(d):
                return d
        return None
    prefix = _get_wine_prefix()
    return os.path.join(prefix, _EA_INSTALL_DATA_SUBPATH) if prefix else None


def _get_wine_install_base():
    prefix = _get_wine_prefix()
    return os.path.join(prefix, _EA_GAMES_SUBPATH) if prefix else None


def _read_installed_offer_ids(install_data_dir):
    """
    Parse EA App InstallData manifests to find installed game offerIds.
    Each subdirectory under InstallData is an offerId; presence = installed.
    """
    installed = set()
    try:
        for entry in os.scandir(install_data_dir):
            if not entry.is_dir():
                continue
            # Directory name is the offerId
            offer_id = entry.name.strip()
            if offer_id:
                installed.add(offer_id)
            # Also check for a __Installer or manifest JSON for confirmation
            manifest = os.path.join(entry.path, 'installerdata.xml')
            if not os.path.exists(manifest):
                manifest = os.path.join(entry.path, 'manifest.json')
            # Directory presence alone is sufficient signal
    except Exception as e:
        log.warning(f'EA watcher: could not scan InstallData dir {install_data_dir}: {e}')
    return installed


def sync_ea_install_status():
    """Update installed flags for all EA App games."""
    from database import get_db

    db = get_db()
    try:
        db.execute("UPDATE games SET installed = 0 WHERE platform = 'ea_app'")

        rows = db.execute(
            "SELECT appid, platform_id FROM games WHERE platform = 'ea_app'"
        ).fetchall()
        offer_map = {row['platform_id']: row['appid'] for row in rows if row['platform_id']}

        if not offer_map:
            db.commit()
            return

        install_data_dir = _get_install_data_dir()
        if install_data_dir and os.path.isdir(install_data_dir):
            installed_ids = _read_installed_offer_ids(install_data_dir)
            for offer_id, appid in offer_map.items():
                if offer_id in installed_ids:
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
        sync_ea_install_status()
    except Exception as e:
        log.warning(f'EA periodic install sync failed: {e}')
    _schedule_poll()


def start_periodic_sync():
    _schedule_poll()
    log.info(f'EA App install status polling started (every {_POLL_INTERVAL}s)')


def stop_periodic_sync():
    global _poll_timer
    with _poll_lock:
        if _poll_timer:
            _poll_timer.cancel()
            _poll_timer = None


_watcher = PluginInstallWatcher('ea_app', sync_ea_install_status)


def start_ea_watcher(watch_path: str):
    _watcher.start(watch_path)


def stop_ea_watcher():
    _watcher.stop()
