import logging
import os

from runners.watcher import PluginInstallWatcher

log = logging.getLogger(__name__)


def sync_gog_install_status():
    """Update installed flags for all GOG games based on whether their install_path exists on disk."""
    from database import get_db
    db = get_db()
    rows = db.execute("SELECT appid, install_path FROM games WHERE platform = 'gog'").fetchall()
    installed_ids = [row['appid'] for row in rows if row['install_path'] and os.path.isdir(row['install_path'])]
    db.execute("UPDATE games SET installed = 0 WHERE platform = 'gog'")
    if installed_ids:
        db.executemany("UPDATE games SET installed = 1 WHERE appid = ?", [(a,) for a in installed_ids])
    db.commit()
    db.close()


_watcher = PluginInstallWatcher('gog', sync_gog_install_status)


def start_gog_watcher(gog_install_base: str):
    """Watch the GOG games folder for directory-level changes and automatically
    update installed status in the DB."""
    _watcher.start(gog_install_base)


def stop_gog_watcher():
    _watcher.stop()
