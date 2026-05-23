import logging
import os

from runners.watcher import PluginInstallWatcher

log = logging.getLogger(__name__)


def sync_humble_install_status():
    """Update installed flags for all Humble games based on whether their download file exists."""
    from database import get_db
    db = get_db()
    rows = db.execute("SELECT appid, install_path FROM games WHERE platform = 'humble'").fetchall()
    installed_ids = [row['appid'] for row in rows if row['install_path'] and os.path.exists(row['install_path'])]
    db.execute("UPDATE games SET installed = 0 WHERE platform = 'humble'")
    if installed_ids:
        db.executemany("UPDATE games SET installed = 1 WHERE appid = ?", [(a,) for a in installed_ids])
    db.commit()
    db.close()


class _HumbleWatcher(PluginInstallWatcher):
    """Extends PluginInstallWatcher to fire on file events in addition to directory events."""

    def start(self, watch_path):
        if self._observer is not None:
            return
        os.makedirs(watch_path, exist_ok=True)
        if not os.path.isdir(watch_path):
            log.warning(f'humble watcher: path not found — {watch_path!r}')
            return
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            log.warning('watchdog not installed — humble filesystem watcher disabled')
            return

        sync_fn = self._sync_fn
        name    = self._name

        class _Handler(FileSystemEventHandler):
            def _on_change(self, event_type, path):
                log.info(f'{name} watcher: {event_type} — {os.path.basename(path)} — syncing')
                try:
                    sync_fn()
                except Exception as e:
                    log.error(f'{name} watcher: sync failed — {e}')

            def on_created(self, event):
                if not event.is_directory:
                    self._on_change('created', event.src_path)

            def on_deleted(self, event):
                if not event.is_directory:
                    self._on_change('deleted', event.src_path)

            def on_moved(self, event):
                if not event.is_directory:
                    self._on_change('moved', event.dest_path)

        observer = Observer()
        observer.schedule(_Handler(), path=watch_path, recursive=True)
        observer.start()
        self._observer = observer
        log.info(f'humble watcher started on: {watch_path}')


_watcher = _HumbleWatcher('humble', sync_humble_install_status)


def start_humble_watcher(download_dir: str):
    _watcher.start(download_dir)


def stop_humble_watcher():
    _watcher.stop()
