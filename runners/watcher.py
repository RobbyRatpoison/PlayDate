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
    Watches a directory for changes and calls sync_fn() on each one. Used by
    plugins to keep installed flags current -- the same instant, event-driven
    model as the core Steam watcher (utils.start_steamapps_watcher), no
    periodic polling needed.

    Options (all default to the original directory-only, top-level, fire-
    immediately behaviour):

      recursive        watch the whole subtree, not just the top level. Needed
                       when a change that matters happens *below* the watched
                       dir -- e.g. EA's Cleanup.exe guts a game folder
                       (removing __Installer/ and the payload) but leaves the
                       folder itself in place, so a top-level watch sees
                       nothing.
      watch_files      fire on file events too, not just directory events.
      debounce_seconds coalesce a burst of events into a single sync_fn() call
                       this many seconds after the last one. Essential with
                       recursive+watch_files: a game install/uninstall emits
                       thousands of events, and sync_fn() only needs to run
                       once things settle.

    Unlike Steam's steamapps dir (always present once Steam itself is
    installed), a plugin's install-base dir (e.g. EA's "Program Files/EA
    Games") may not exist yet at startup on a prefix with zero games
    installed -- watchdog has nothing to schedule() against in that case.
    start() retries on _RETRY_INTERVAL until the path appears, then attaches
    for good; this is a one-time bring-up concern, not a substitute for
    event-driven detection.
    """

    def __init__(self, name, sync_fn, *, recursive=False, watch_files=False,
                 debounce_seconds=0.0):
        self._name             = name
        self._sync_fn          = sync_fn
        self._recursive        = recursive
        self._watch_files      = watch_files
        self._debounce         = debounce_seconds
        self._observer         = None
        self._retry_timer      = None
        self._debounce_timer   = None
        self._debounce_lock    = threading.Lock()
        self._watch_path       = None

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

        watcher = self

        class _Handler(FileSystemEventHandler):
            def _relevant(self, event):
                return event.is_directory or watcher._watch_files

            def on_created(self, event):
                if self._relevant(event):
                    watcher._schedule_sync('created', event.src_path)

            def on_deleted(self, event):
                if self._relevant(event):
                    watcher._schedule_sync('deleted', event.src_path)

            def on_moved(self, event):
                if self._relevant(event):
                    watcher._schedule_sync('moved', event.dest_path)

        observer = Observer()
        observer.schedule(_Handler(), path=watch_path, recursive=self._recursive)
        observer.start()
        self._observer = observer
        log.info(f'{self._name} watcher started on: {watch_path}')

    def _schedule_sync(self, event_type, path):
        if self._debounce <= 0:
            self._run_sync(event_type, path)
            return
        with self._debounce_lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(
                self._debounce, self._run_sync, args=(event_type, path))
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _run_sync(self, event_type, path):
        log.info(f'{self._name} watcher: {event_type} — {os.path.basename(path)} — syncing')
        try:
            self._sync_fn()
        except Exception as e:
            log.error(f'{self._name} watcher: sync failed — {e}')

    def _retry(self):
        self._retry_timer = None
        self.start(self._watch_path)

    def stop(self):
        """Stop the observer (and any pending bring-up retry / debounced sync)."""
        if self._retry_timer is not None:
            self._retry_timer.cancel()
            self._retry_timer = None
        with self._debounce_lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=3)
            except Exception as e:
                log.warning(f'{self._name} watcher stop error: {e}')
            self._observer = None
