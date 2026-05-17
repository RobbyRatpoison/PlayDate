import json
import logging
import os
import sys
import threading

from runners.watcher import PluginInstallWatcher

log = logging.getLogger(__name__)

# Battle.net stores install data at:
#   Windows: %PROGRAMDATA%\Battle.net\Agent\data\
#   Wine:    {prefix}/drive_c/ProgramData/Battle.net/Agent/data/
_AGENT_DATA_SUBPATH = os.path.join('drive_c', 'ProgramData', 'Battle.net', 'Agent', 'data')
_BNET_INSTALL_SUBPATH = os.path.join('drive_c', 'Program Files (x86)')

_MANIFEST_DIR_WINDOWS = os.path.join(
    os.environ.get('PROGRAMDATA', r'C:\ProgramData'),
    'Battle.net', 'Agent', 'data'
)

_POLL_INTERVAL = 60
_poll_timer    = None
_poll_lock     = threading.Lock()


def _get_wine_prefix():
    try:
        from config import CONFIG_PATH
        with open(CONFIG_PATH, 'r') as f:
            cfg = json.load(f)
        return cfg.get('launchers', {}).get('battle_net', {}).get('prefix', '').strip() or None
    except Exception:
        return None


def _get_agent_data_dir():
    if sys.platform == 'win32':
        if os.path.isdir(_MANIFEST_DIR_WINDOWS):
            return _MANIFEST_DIR_WINDOWS
        return None
    prefix = _get_wine_prefix()
    return os.path.join(prefix, _AGENT_DATA_SUBPATH) if prefix else None


def _read_installed_product_codes(agent_data_dir):
    """
    Parse Battle.net Agent data directory for installed products.
    Agent stores per-product JSON files named after the product code.
    Returns a set of product code strings for installed games.
    """
    installed = set()
    try:
        for entry in os.scandir(agent_data_dir):
            if not entry.is_dir():
                continue
            # Each subdir is a product code; presence means installed (or installable)
            # Check for a 'config.json' or 'product.db' inside to confirm install
            conf = os.path.join(entry.path, 'config.json')
            db   = os.path.join(entry.path, 'product.db')
            if os.path.isfile(conf) or os.path.isfile(db):
                installed.add(entry.name)
    except Exception as e:
        log.warning(f'Battle.net watcher: could not scan agent data dir: {e}')
    return installed


def sync_bnet_install_status():
    """Update installed flags for all Battle.net games."""
    from database import get_db

    db = get_db()
    try:
        db.execute("UPDATE games SET installed = 0 WHERE platform = 'battle_net'")

        rows = db.execute(
            "SELECT appid, platform_id FROM games WHERE platform = 'battle_net'"
        ).fetchall()
        code_map = {row['platform_id']: row['appid'] for row in rows if row['platform_id']}

        if not code_map:
            db.commit()
            return

        agent_dir = _get_agent_data_dir()
        if agent_dir and os.path.isdir(agent_dir):
            installed_codes = _read_installed_product_codes(agent_dir)
            for code, appid in code_map.items():
                if code in installed_codes:
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
        sync_bnet_install_status()
    except Exception as e:
        log.warning(f'Battle.net periodic install sync failed: {e}')
    _schedule_poll()


def start_periodic_sync():
    _schedule_poll()
    log.info(f'Battle.net install status polling started (every {_POLL_INTERVAL}s)')


def stop_periodic_sync():
    global _poll_timer
    with _poll_lock:
        if _poll_timer:
            _poll_timer.cancel()
            _poll_timer = None


_watcher = PluginInstallWatcher('battle_net', sync_bnet_install_status)


def start_bnet_watcher(watch_path: str):
    _watcher.start(watch_path)


def stop_bnet_watcher():
    _watcher.stop()
