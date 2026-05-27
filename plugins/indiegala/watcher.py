import logging
import os

from runners.watcher import PluginInstallWatcher

log = logging.getLogger(__name__)


def sync_indiegala_install_status():
    from .indiegala import sync_indiegala_install_status as _sync
    _sync()


_watcher = PluginInstallWatcher('indiegala', sync_indiegala_install_status)


def start_indiegala_watcher(games_dir: str):
    os.makedirs(games_dir, exist_ok=True)
    _watcher.start(games_dir)


def stop_indiegala_watcher():
    _watcher.stop()
