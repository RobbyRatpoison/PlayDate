import os
import platform
import re
from database import get_db, update_game_data
from datetime import datetime

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
            # Split by comma, strip whitespace, and add to set
            parts = [g.strip() for g in row['tags'].split(',') if g.strip()]
            all_tags.update(parts)
    return sorted(list(all_tags))
