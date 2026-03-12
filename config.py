import requests
from flask import Blueprint, request, jsonify
import json
import os
import sys

config_bp = Blueprint('config', __name__)

# ── BASE_DIR: works both as a plain Python script and inside a PyInstaller .exe
#
# When frozen (running as PlayDate.exe), sys.executable is the .exe itself and
# sys._MEIPASS is the temp/bundle folder where PyInstaller extracts the code.
# We want BASE_DIR to be the folder *next to* the .exe so that user data files
# (config.json, state.json, games.db, playdate.log) are written there and
# survive upgrades/reinstalls — not inside the bundle which gets replaced.
#
# When running normally as `python main.py`, __file__ gives us the script folder.
# ─────────────────────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    # Running as a PyInstaller bundle
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Running as a plain Python script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
STATE_PATH  = os.path.join(BASE_DIR, 'state.json')

DEFAULT_SHELVES = [
    # ── Row 1: Recently Added + Clock + Recently Released (top_row split) ──
    {
        "id": "recently_added",
        "label": "RECENTLY ADDED",
        "preset": "all_games",
        "filter_key": "all_games",
        "custom_sql": None,
        "limit": 4,
        "row_height": 30,
        "col_width": 2,
        "split_group": "top_row",
        "sort_col": "date_added", "sort_dir": None,
        "dedup": True,
        "dedup_priority": 1,
        "visible": True
    },
    {
        "id": "clock",
        "label": "Clock [Widget]",
        "preset": "clock",
        "filter_key": "clock",
        "custom_sql": None,
        "limit": 0,
        "row_height": 30,
        "col_width": 0.5,
        "split_group": "top_row",
        "sort_col": None, "sort_dir": None,
        "dedup": False,
        "dedup_priority": 99,
        "visible": True
    },
    {
        "id": "recently_released",
        "label": "RECENTLY RELEASED",
        "preset": "all_games",
        "filter_key": "all_games",
        "custom_sql": None,
        "limit": 4,
        "row_height": 30,
        "col_width": 2,
        "split_group": "top_row",
        "sort_col": "release_date", "sort_dir": None,
        "dedup": True,
        "dedup_priority": 2,
        "visible": True
    },
    # ── Row 2: Installed ──
    {
        "id": "installed",
        "label": "INSTALLED",
        "preset": "installed",
        "filter_key": "installed",
        "custom_sql": None,
        "limit": 10,
        "row_height": 39,
        "col_width": None,
        "split_group": None,
        "sort_col": "last_played", "sort_dir": None,
        "dedup": True,
        "dedup_priority": 0,
        "visible": True
    },
    # ── Row 3: Shuffle ──
    {
        "id": "discovery",
        "label": "SHUFFLE",
        "preset": "all_games",
        "filter_key": "all_games",
        "custom_sql": None,
        "limit": 15,
        "row_height": 22,
        "col_width": None,
        "split_group": None,
        "sort_col": "RANDOM()", "sort_dir": None,
        "dedup": True,
        "dedup_priority": 3,
        "visible": True
    }
]

DEFAULT_STATE = {
    "sort": "name",
    "order": "ASC",
    "active_filters": [],
    "saved_filters": {},
    "shelves": DEFAULT_SHELVES
}

def validate_steam_creds(api_key, steam_id):
    """
    Returns (True, "Success") or (False, "Error Message")
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    url = f"http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={api_key}&steamids={steam_id}"

    try:
        response = requests.get(url, headers=headers, timeout=5)

        if response.status_code == 403:
            return False, "Invalid API Key (403 Forbidden)"

        response.raise_for_status()
        data = response.json()

        players = data.get('response', {}).get('players', [])
        if not players:
            return False, "API Key is valid, but Steam ID was not found."

        return True, "Valid"

    except Exception as e:
        return False, f"Connection Failed: {str(e)}"

def resolve_vanity_url(api_key, steam_id):
    """Converts vanity name to SteamID64. Returns original ID if already numerical."""
    if steam_id.isdigit():
        return steam_id

    url = f"http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/?key={api_key}&vanityurl={steam_id}"
    try:
        response = requests.get(url).json()
        if response.get('response', {}).get('success') == 1:
            return response['response']['steamid']
    except Exception:
        pass
    return steam_id

@config_bp.app_context_processor
def inject_config_status():
    """This makes 'config_exists' available in all your HTML files automatically."""
    return dict(config_exists=is_configured())

def load_config():
    """Returns the current configuration data from config.json."""
    if is_configured():
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return None

def is_configured():
    return os.path.exists(CONFIG_PATH)

@config_bp.route('/save-config', methods=['POST'])
def save_config():
    data = request.json
    api_key = (data.get('api_key') or '').strip()
    raw_id = (data.get('steam_id') or '').strip()
    sgdb_key = data.get('sgdb_key')

    if not raw_id:
        return jsonify({"status": "error", "message": "Steam ID or Vanity Name is required."}), 400

    if api_key:
        resolved_id = resolve_vanity_url(api_key, raw_id)
        is_valid, message = validate_steam_creds(api_key, resolved_id)
        if not is_valid:
            return jsonify({"status": "error", "message": message}), 400
    else:
        resolved_id = raw_id

    config_data = {
        "api_key": api_key,
        "steam_id": resolved_id,
        "sgdb_key": sgdb_key,
        "vanity_name": raw_id if not raw_id.isdigit() else None
    }

    with open(CONFIG_PATH, 'w') as f:
        json.dump(config_data, f, indent=4)

    return jsonify({"status": "success"})

def get_default_shelves():
    import copy
    return copy.deepcopy(DEFAULT_SHELVES)

def create_state(force=False):
    """Creates state.json with defaults if it doesn't exist."""
    if not os.path.exists(STATE_PATH) or force:
        with open(STATE_PATH, 'w') as f:
            json.dump(DEFAULT_STATE, f, indent=4)
        return DEFAULT_STATE
    return load_state()

def load_state():
    """Loads the current state or creates it if missing."""
    if not os.path.exists(STATE_PATH):
        return create_state()
    with open(STATE_PATH, 'r') as f:
        try:
            state = json.load(f)
        except json.JSONDecodeError:
            return create_state(force=True)
    if 'shelves' not in state:
        state['shelves'] = get_default_shelves()
        with open(STATE_PATH, 'w') as f:
            json.dump(state, f, indent=4)
    return state

def save_state(updates):
    state = load_state()

    if "filter_tree" in updates:
        state["filter_tree"] = updates["filter_tree"]
        state["active_filters"] = []

    if "filter_update" in updates:
        new_filter = updates["filter_update"]
        state["active_filters"] = [f for f in state["active_filters"] if f["column"] != new_filter["column"]]
        if new_filter.get("value", "").strip():
            state["active_filters"].append(new_filter)

    if "active_filters" in updates and "filter_tree" not in updates:
        state["active_filters"] = updates["active_filters"]
        state["filter_tree"] = None

    if "sort" in updates: state["sort"] = updates["sort"]
    if "order" in updates: state["order"] = updates["order"]

    if "shelves" in updates:
        state["shelves"] = updates["shelves"]

    with open(STATE_PATH, 'w') as f:
        json.dump(state, f, indent=4)
    return state

@config_bp.route('/api/update_state', methods=['POST'])
def update_state_api():
    new_data = request.json
    save_state(new_data)
    return jsonify({"status": "success"})
