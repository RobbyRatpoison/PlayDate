import os
import platform
import re
import logging
from database import get_db, update_game_data
from datetime import datetime

log = logging.getLogger(__name__)

# ── Steamapps filesystem watcher ──────────────────────────────────────────────
_watcher_observer = None


def start_steamapps_watcher(steamapps_path: str):
    """
    Watch the steamapps folder for appmanifest_*.acf changes and automatically
    update installed status in the DB.  Safe to call from any thread.
    Returns the Observer instance (already started), or None if watchdog is
    unavailable or the path doesn't exist.
    """
    global _watcher_observer

    if not steamapps_path or not os.path.isdir(steamapps_path):
        log.warning(f"Steamapps watcher: path not found — {steamapps_path!r}")
        return None

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileDeletedEvent, FileMovedEvent
    except ImportError:
        log.warning("watchdog not installed — filesystem watcher disabled")
        return None

    class _ManifestHandler(FileSystemEventHandler):
        """Reacts to appmanifest_*.acf create / delete / move events."""

        def _is_manifest(self, path: str) -> bool:
            name = os.path.basename(path)
            return name.startswith("appmanifest_") and name.endswith(".acf")

        def _on_change(self, event_type: str, path: str):
            if self._is_manifest(path):
                log.info(f"Steamapps watcher: {event_type} — {os.path.basename(path)} — syncing install status")
                try:
                    sync_local_install_status()
                except Exception as e:
                    log.error(f"Steamapps watcher: sync failed — {e}")

        def on_created(self, event):
            if not event.is_directory:
                self._on_change("created", event.src_path)

        def on_deleted(self, event):
            if not event.is_directory:
                self._on_change("deleted", event.src_path)

        def on_moved(self, event):
            if not event.is_directory:
                # A move in or out of the folder both matter
                self._on_change("moved", event.dest_path)

    stop_steamapps_watcher()  # stop any previous instance

    observer = Observer()
    observer.schedule(_ManifestHandler(), path=steamapps_path, recursive=False)
    observer.start()
    _watcher_observer = observer
    log.info(f"Steamapps watcher started on: {steamapps_path}")
    return observer


def stop_steamapps_watcher():
    """Stop the running observer, if any."""
    global _watcher_observer
    if _watcher_observer is not None:
        try:
            _watcher_observer.stop()
            _watcher_observer.join(timeout=3)
        except Exception as e:
            log.warning(f"Steamapps watcher stop error: {e}")
        _watcher_observer = None

def find_steam_path():
    """Attempts to locate the Steam installation path, prioritizing Linux."""

    # 1. LINUX & COMMON DEFAULTS (Priority)
    # We check the Linux hidden folder first as requested.
    defaults = [
        os.path.expanduser("~/.steam/steam/steamapps"),             # Standard Linux
        os.path.expanduser("~/.local/share/Steam/steamapps"),      # Flatpak/Other Linux
        "C:/Program Files (x86)/Steam/steamapps",                  # Windows Default
        "C:/Program Files/Steam/steamapps",                        # Windows Alt
        os.path.expanduser("~/Library/Application Support/Steam/steamapps") # macOS
    ]

    for path in defaults:
        if os.path.exists(path):
            return path

    # 2. WINDOWS REGISTRY (Secondary Fallback)
    # If the common paths fail and we are on Windows, ask the OS directly.
    if platform.system() == "Windows":
        try:
            import winreg
            for key_path in [r"SOFTWARE\WOW6432Node\Valve\Steam", r"SOFTWARE\Valve\Steam"]:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    path, _ = winreg.QueryValueEx(key, "InstallPath")
                    if path:
                        return os.path.join(path, "steamapps")
        except:
            pass

    return None

def get_locally_installed_appids():
    """
    Scans the Steam library for manifest files to find truly installed games.
    Common path: C:/Program Files (x86)/Steam/steamapps
    """
    installed_ids = []

    # Check if the path exists
    steam_path = find_steam_path()
    if not steam_path or not os.path.exists(steam_path):
        print("Steam path not found. Skipping local scan.")
        return []

    # Steam stores every installed game as 'appmanifest_XXXXX.acf'
    for filename in os.listdir(steam_path):
        file_path = os.path.join(steam_path, filename)
        if filename.startswith("appmanifest_") and filename.endswith(".acf"):
            if is_real_game(file_path):
                # Extract the ID from the filename using regex
                match = re.search(r"appmanifest_(\d+)\.acf", filename)
                if match:
                    installed_ids.append(int(match.group(1)))

    #total_installed = len(installed_ids)
    #print(f"There are {total_installed} games installed.")
    return installed_ids

def is_real_game(file_path):
    with open(file_path, 'r') as f:
        content = f.read()

    # Check for UserConfig - most tools don't have this
    if '"UserConfig"' not in content:
        return False

    # Check for known non-game directory patterns
    if any(term in content for term in ['Steamworks Shared', 'Proton', 'SteamLinuxRuntime']):
        return False

    return True

def sync_local_install_status():
    # 1. Get the real IDs from your hard drive
    local_ids = get_locally_installed_appids()

    # 2. Reset everything in DB to 0 (Uninstalled)
    db = get_db()
    db.execute("UPDATE games SET installed = 0")
    db.commit()
    db.close() # Close to allow bulk_update to open its own connection

    if local_ids:
        # 3. Bulk update the ones we actually found
        from database import bulk_update_column
        bulk_update_column(local_ids, 'installed', 1)
        return len(local_ids)
    return 0

def record_launch(appid):
    db = get_db()
    game = db.execute("SELECT installed, completion_status FROM games WHERE appid=?", (appid,)).fetchone()
    db.close()
    if game and game['installed'] == 1:
        now = datetime.now().strftime("%Y-%m-%d")
        if game['completion_status'] == "Never Played":
            update_game_data(appid, last_played=now, completion_status="Unfinished")
        else:
            update_game_data(appid, last_played=now)
        print(f"Recorded launch for Installed AppID: {appid}")
        return now
    print(f"Launch ignored for AppID {appid}: Not marked as installed.")
    return None

def get_all_unique_groups():
    db = get_db()
    rows = db.execute("SELECT groups FROM games WHERE groups IS NOT NULL").fetchall()
    db.close()
    all_groups = set()
    for row in rows:
        if row['groups']:
            # Split by comma, strip whitespace, and add to set
            parts = [g.strip() for g in row['groups'].split(',') if g.strip()]
            all_groups.update(parts)
    return sorted(list(all_groups))

def get_all_unique_tags():
    db = get_db()
    rows = db.execute("SELECT tags FROM games WHERE tags IS NOT NULL").fetchall()
    db.close()
    all_tags = set()
    for row in rows:
        if row['tags']:
            parts = [g.strip() for g in row['tags'].split(',') if g.strip()]
            all_tags.update(parts)
    return sorted(list(all_tags))

def get_all_unique_genres():
    db = get_db()
    rows = db.execute("SELECT genres FROM games WHERE genres IS NOT NULL").fetchall()
    db.close()
    all_genres = set()
    for row in rows:
        if row['genres']:
            parts = [g.strip() for g in row['genres'].split(',') if g.strip()]
            all_genres.update(parts)
    return sorted(list(all_genres))

def get_all_unique_categories():
    db = get_db()
    rows = db.execute("SELECT categories FROM games WHERE categories IS NOT NULL").fetchall()
    db.close()
    all_categories = set()
    for row in rows:
        if row['categories']:
            parts = [c.strip() for c in row['categories'].split(',') if c.strip()]
            all_categories.update(parts)
    return sorted(list(all_categories))
