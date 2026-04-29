"""
runners/watcher.py — Reusable filesystem watcher for plugin install directories.
"""

import logging
import os

log = logging.getLogger(__name__)


class PluginInstallWatcher:
    """
    Watches a directory for subdirectory create/delete/move events and calls
    sync_fn() on each change. Used by plugins to keep installed flags current.
    """

    def __init__(self, name, sync_fn):
        self._name     = name
        self._sync_fn  = sync_fn
        self._observer = None

    def start(self, watch_path):
        """Start watching watch_path. No-op if already running or path missing."""
        if self._observer is not None:
            return

        if not watch_path or not os.path.isdir(watch_path):
            log.warning(f'{self._name} watcher: path not found — {watch_path!r}')
            return

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            log.warning(f'watchdog not installed — {self._name} filesystem watcher disabled')
            return

        name     = self._name
        sync_fn  = self._sync_fn

        class _Handler(FileSystemEventHandler):
            def _on_change(self, event_type, path):
                log.info(f'{name} watcher: {event_type} — {os.path.basename(path)} — syncing')
                try:
                    sync_fn()
                except Exception as e:
                    log.error(f'{name} watcher: sync failed — {e}')

            def on_created(self, event):
                if event.is_directory:
                    self._on_change('created', event.src_path)

            def on_deleted(self, event):
                if event.is_directory:
                    self._on_change('deleted', event.src_path)

            def on_moved(self, event):
                if event.is_directory:
                    self._on_change('moved', event.dest_path)

        observer = Observer()
        observer.schedule(_Handler(), path=watch_path, recursive=False)
        observer.start()
        self._observer = observer
        log.info(f'{self._name} watcher started on: {watch_path}')

    def stop(self):
        """Stop the observer if running."""
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=3)
            except Exception as e:
                log.warning(f'{self._name} watcher stop error: {e}')
            self._observer = None
