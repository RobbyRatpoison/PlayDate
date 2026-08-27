"""
runners/watcher.py — Reusable filesystem watcher for plugin install directories.
"""

import logging
import os
import threading

log = logging.getLogger(__name__)

_RETRY_INTERVAL = 30


class PluginInstallWatcher:
    """
    Watches a directory for subdirectory create/delete/move events and calls
    sync_fn() on each change. Used by plugins to keep installed flags current
    -- the same instant, event-driven model as the core Steam watcher
    (utils.start_steamapps_watcher), no periodic polling needed.

    Unlike Steam's steamapps dir (always present once Steam itself is
    installed), a plugin's install-base dir (e.g. EA's "Program Files/EA
    Games") may not exist yet at startup on a prefix with zero games
    installed -- watchdog has nothing to schedule() against in that case.
    start() retries on _RETRY_INTERVAL until the path appears, then attaches
    for good; this is a one-time bring-up concern, not a substitute for
    event-driven detection.
    """

    def __init__(self, name, sync_fn):
        self._name        = name
        self._sync_fn     = sync_fn
        self._observer    = None
        self._retry_timer = None
        self._watch_path  = None

    def start(self, watch_path):
        """Start watching watch_path. No-op if already running or path missing.
        If watch_path doesn't exist yet, retries every _RETRY_INTERVAL seconds
        until it does (see class docstring)."""
        if self._observer is not None:
            return

        self._watch_path = watch_path

        if not watch_path or not os.path.isdir(watch_path):
            log.info(f'{self._name} watcher: path not found yet, will retry — {watch_path!r}')
            self._retry_timer = threading.Timer(_RETRY_INTERVAL, self._retry)
            self._retry_timer.daemon = True
            self._retry_timer.start()
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

    def _retry(self):
        self._retry_timer = None
        self.start(self._watch_path)

    def stop(self):
        """Stop the observer (and any pending bring-up retry) if running."""
        if self._retry_timer is not None:
            self._retry_timer.cancel()
            self._retry_timer = None
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=3)
            except Exception as e:
                log.warning(f'{self._name} watcher stop error: {e}')
            self._observer = None
