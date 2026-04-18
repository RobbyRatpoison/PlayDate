import requests
from flask import Blueprint, request, jsonify
import json
import os
import sys
import threading

_state_lock = threading.Lock()

config_bp = Blueprint('config', __name__)

__version__ = "1.4.1"

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
THEME_PATH  = os.path.join(BASE_DIR, 'theme.json')

# ── Theme defaults — single source of truth for all CSS variables ─────────────
DEFAULT_THEME = {
    # Backgrounds
    "--bg-page":          "#0e1419",
    "--bg-surface":       "#1b2838",
    "--bg-raised":        "#1a2332",
    "--bg-input":         "#101822",
    "--bg-card":          "#101822",
    "--bg-nav":           "#171a21",
    # Text
    "--text-primary":     "#c7d5e0",
    "--text-heading":     "#e2eaf0",
    "--text-secondary":   "#8f98a0",
    "--text-input":       "#ffffff",
    "--text-bright":      "#ffffff",
    # Accent
    "--accent":           "#66c0f4",
    "--on-accent":        "#0e1621",
    "--accent-positive":  "#5c7e10",
    # Borders
    "--border":           "#2a475e",
    # Status
    "--color-danger":     "#a32a2a",
    "--text-danger":      "#ff8080",
    "--color-warning":    "#c97c00",
    # Background
    "--bg-image-opacity": "1",
}

def load_theme():
    """Returns the active theme dict, falling back to defaults for any missing keys."""
    theme = dict(DEFAULT_THEME)
    if os.path.exists(THEME_PATH):
        try:
            with open(THEME_PATH, 'r') as f:
                saved = json.load(f)
            for k in DEFAULT_THEME:
                if k in saved:
                    theme[k] = saved[k]
        except Exception:
            pass
    return theme

def save_theme(vars_dict):
    """Persist a theme dict to theme.json. Unknown keys are silently dropped. Preserves saved themes."""
    clean = {k: v for k, v in vars_dict.items() if k in DEFAULT_THEME}
    # Preserve any saved themes already in the file
    saved = {}
    if os.path.exists(THEME_PATH):
        try:
            with open(THEME_PATH, 'r') as f:
                existing = json.load(f)
            saved = existing.get('_saved', {})
        except Exception:
            pass
    if saved:
        clean['_saved'] = saved
    with open(THEME_PATH, 'w') as f:
        json.dump(clean, f, indent=4)

def load_saved_themes():
    """Returns the saved themes dict {name: {vars}}."""
    if not os.path.exists(THEME_PATH):
        return {}
    try:
        with open(THEME_PATH, 'r') as f:
            data = json.load(f)
        return data.get('_saved', {})
    except Exception:
        return {}

def save_named_theme(name, vars_dict):
    """Save a named theme to the _saved section of theme.json."""
    clean = {k: v for k, v in vars_dict.items() if k in DEFAULT_THEME}
    saved = load_saved_themes()
    saved[name] = clean
    # Re-save the whole file preserving active theme
    active = load_theme()
    active['_saved'] = saved
    with open(THEME_PATH, 'w') as f:
        json.dump(active, f, indent=4)

def delete_named_theme(name):
    """Remove a named theme from the _saved section."""
    saved = load_saved_themes()
    saved.pop(name, None)
    active = load_theme()
    active['_saved'] = saved
    with open(THEME_PATH, 'w') as f:
        json.dump(active, f, indent=4)

def rename_named_theme(old_name, new_name):
    """Rename a saved theme."""
    saved = load_saved_themes()
    if old_name not in saved:
        return False
    saved[new_name] = saved.pop(old_name)
    active = load_theme()
    active['_saved'] = saved
    with open(THEME_PATH, 'w') as f:
        json.dump(active, f, indent=4)
    return True

# ── Built-in filter presets — single source of truth for index + library ──────
BUILTIN_FILTERS = {
    "all_games":     {"label": "All Games",      "where": "1=1"},
    "installed":     {"label": "Installed",       "where": "installed = 1"},
    "not_installed": {"label": "Not Installed",   "where": "installed = 0"},
    "never_played":  {"label": "Never Played",    "where": "completion_status = 'Never Played'"},
    "unfinished":    {"label": "Unfinished",      "where": "completion_status = 'Unfinished'"},
    "not_beaten":    {"label": "Not Beaten",      "where": "completion_status IN ('Never Played', 'Unfinished')"},
    "beaten":        {"label": "Beaten",          "where": "completion_status IN ('Beaten', 'Completed')"},
    # Widget presets — no SQL
    "clock":          {"label": "Clock",             "where": None},
    "completion_pie": {"label": "Completion Chart",  "where": None},
}

DEFAULT_SHELVES = [
    # ── Row 1: Recently Added + Clock + Recently Released (top_row split) ──
    {
        "id": "recently_added",
        "label": "RECENTLY ADDED",
        "preset": "not_beaten",
        "filter_key": "not_beaten",
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
        "preset": "not_beaten",
        "filter_key": "not_beaten",
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
        "limit": 7,
        "row_height": 38,
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
        "preset": "not_beaten",
        "filter_key": "not_beaten",
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
    "saved_filters": {},
    "shelves": DEFAULT_SHELVES,
    "artwork_orientation": "vertical",
    "card_height": 200,
    "check_for_updates": True,
    "window_state": None,
    "hltb_match_threshold": 99
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
    """Injects config state into all templates."""
    config = load_config() or {}
    active_id = config.get('active_account')
    accounts  = config.get('accounts', {})
    active    = accounts.get(active_id, {})
    needs_config = not is_configured() or not active_id or active_id not in accounts
    state = load_state()
    accounts_list = [
        {**v, 'active': k == active_id}
        for k, v in accounts.items()
    ]
    return dict(
        config_exists=is_configured(),
        needs_config=needs_config,
        existing_steam_id=active.get('steam_id', ''),
        existing_api_key=active.get('api_key', ''),
        existing_sgdb_key=config.get('sgdb_key', ''),
        existing_sg_username=config.get('sg_username', ''),
        accounts_list=accounts_list,
        active_steam_id=active_id or '',
        initial_fullscreen=state.get('fullscreen', False),
        hltb_match_threshold=state.get('hltb_match_threshold', 99),
        hide_duplicates=state.get('hide_duplicates', True),
        app_version=__version__,
    )

def load_config():
    """Returns the current configuration data from config.json."""
    if is_configured():
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return None

def is_configured():
    return os.path.exists(CONFIG_PATH)

def get_active_account():
    """Returns the active account dict {steam_id, api_key, label}, or None."""
    config = load_config()
    if not config:
        return None
    active_id = config.get('active_account', '')
    return config.get('accounts', {}).get(active_id)

def get_active_db_path():
    """Returns the path to the active account's database file."""
    config = load_config()
    if config:
        active_id = config.get('active_account', '')
        if active_id:
            return os.path.join(BASE_DIR, f'games_{active_id}.db')
    return os.path.join(BASE_DIR, 'games_default.db')

def migrate_to_multi_account():
    """
    One-time migration from flat {steam_id, api_key, sgdb_key} config to the
    multi-account structure {active_account, sgdb_key, accounts: {...}}.
    Renames games.db → games_<steamid>.db.  Idempotent — safe to call on every launch.
    """
    if not os.path.exists(CONFIG_PATH):
        return  # Fresh install — nothing to migrate

    with open(CONFIG_PATH, 'r') as f:
        data = json.load(f)

    if 'accounts' in data:
        return  # Already migrated

    steam_id = data.get('steam_id', '').strip()
    api_key  = data.get('api_key', '').strip()
    sgdb_key = data.get('sgdb_key', '').strip()

    if not steam_id:
        # Partial legacy config with no steam_id
        new_config = {'active_account': None, 'sgdb_key': sgdb_key, 'accounts': {}}
        with open(CONFIG_PATH, 'w') as f:
            json.dump(new_config, f, indent=4)
        return

    # Rename games.db → games_<steamid>.db if the old file still exists
    old_db = os.path.join(BASE_DIR, 'games.db')
    new_db = os.path.join(BASE_DIR, f'games_{steam_id}.db')
    if os.path.exists(old_db) and not os.path.exists(new_db):
        os.rename(old_db, new_db)

    new_config = {
        'active_account': steam_id,
        'sgdb_key': sgdb_key,
        'accounts': {
            steam_id: {
                'steam_id': steam_id,
                'api_key': api_key,
                'label': steam_id,
            }
        }
    }
    with open(CONFIG_PATH, 'w') as f:
        json.dump(new_config, f, indent=4)

@config_bp.route('/api/detect-steam-id')
def detect_steam_id_route():
    from utils import detect_steam_id
    accounts = detect_steam_id()
    if not accounts:
        return jsonify({"status": "not_found"})
    if len(accounts) == 1:
        return jsonify({"status": "success", "steam_id": accounts[0]['steam_id'], "name": accounts[0]['name']})
    return jsonify({"status": "multiple", "accounts": accounts})


@config_bp.route('/save-config', methods=['POST'])
def save_config():
    data       = request.json
    api_key    = (data.get('api_key')  or '').strip()
    raw_id     = (data.get('steam_id') or '').strip()
    sgdb_key   = data.get('sgdb_key')   # None means "don't touch"
    label      = (data.get('label')    or '').strip()
    set_active = bool(data.get('_set_active', False))

    # Load existing multi-account config or start fresh
    if is_configured():
        with open(CONFIG_PATH, 'r') as f:
            config_data = json.load(f)
        if 'accounts' not in config_data:
            config_data = {'active_account': None, 'sgdb_key': config_data.get('sgdb_key', ''), 'accounts': {}}
    else:
        config_data = {'active_account': None, 'sgdb_key': '', 'accounts': {}}

    # sgdb_key-only update (no steam_id required)
    if sgdb_key is not None and not raw_id:
        config_data['sgdb_key'] = sgdb_key.strip()
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config_data, f, indent=4)
        return jsonify({"status": "success"})

    if not raw_id:
        return jsonify({"status": "error", "message": "Steam ID is required."}), 400

    if api_key:
        resolved_id = resolve_vanity_url(api_key, raw_id)
        is_valid, message = validate_steam_creds(api_key, resolved_id)
        if not is_valid:
            return jsonify({"status": "error", "message": message}), 400
    else:
        if not raw_id.isdigit():
            return jsonify({"status": "error", "message": "A numeric SteamID64 is required when no API key is provided. Vanity names can only be resolved with an API key."}), 400
        resolved_id = raw_id

    if sgdb_key is not None:
        config_data['sgdb_key'] = sgdb_key.strip()

    is_new = resolved_id not in config_data['accounts']
    existing_account = config_data['accounts'].get(resolved_id, {})
    config_data['accounts'][resolved_id] = {
        'steam_id': resolved_id,
        'api_key':  api_key,
        'label':    label or existing_account.get('label', resolved_id),
    }

    # Switch to this account when: it's new, explicitly requested, updating current active, or no active set
    if is_new or set_active or config_data.get('active_account') == resolved_id or not config_data.get('active_account'):
        config_data['active_account'] = resolved_id

    with open(CONFIG_PATH, 'w') as f:
        json.dump(config_data, f, indent=4)

    return jsonify({"status": "success"})

def get_default_shelves():
    import copy
    return copy.deepcopy(DEFAULT_SHELVES)

def _write_state_atomic(state):
    """Write state to a temp file then rename — prevents corruption on crash mid-write."""
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=4)
    os.replace(tmp, STATE_PATH)

def create_state(force=False):
    """Creates state.json with defaults if it doesn't exist. Caller must hold _state_lock."""
    if not os.path.exists(STATE_PATH) or force:
        import copy
        state = copy.deepcopy(DEFAULT_STATE)
        _write_state_atomic(state)
        return state
    return _load_state_unlocked()

def _load_state_unlocked():
    """Read and migrate state from disk. Caller must hold _state_lock."""
    if not os.path.exists(STATE_PATH):
        return create_state()
    with open(STATE_PATH, 'r') as f:
        try:
            state = json.load(f)
        except json.JSONDecodeError:
            return create_state(force=True)
    dirty = False
    if 'shelves' not in state:
        state['shelves'] = get_default_shelves()
        dirty = True
    if 'artwork_orientation' not in state:
        state['artwork_orientation'] = 'vertical'
        dirty = True
    if 'card_height' not in state:
        state['card_height'] = 200
        dirty = True
    if 'hide_duplicates' not in state:
        state['hide_duplicates'] = True
        dirty = True
    if dirty:
        _write_state_atomic(state)
    return state

def load_state():
    """Loads the current state or creates it if missing."""
    with _state_lock:
        return _load_state_unlocked()

def save_state(updates):
    with _state_lock:
        state = _load_state_unlocked()

        if "filter_tree" in updates:
            state["filter_tree"] = updates["filter_tree"]

        if "sort" in updates: state["sort"] = updates["sort"]
        if "order" in updates: state["order"] = updates["order"]
        if "artwork_orientation" in updates: state["artwork_orientation"] = updates["artwork_orientation"]
        if "card_height" in updates: state["card_height"] = updates["card_height"]
        if "check_for_updates" in updates: state["check_for_updates"] = updates["check_for_updates"]
        if "window_state" in updates: state["window_state"] = updates["window_state"]
        if "fullscreen" in updates: state["fullscreen"] = updates["fullscreen"]
        if "hltb_match_threshold" in updates: state["hltb_match_threshold"] = int(updates["hltb_match_threshold"])
        if "pagywosg_sg_group" in updates: state["pagywosg_sg_group"] = updates["pagywosg_sg_group"]
        if "hide_duplicates" in updates: state["hide_duplicates"] = bool(updates["hide_duplicates"])
        if "hidden_platforms" in updates:
            safe = {'steam', 'gog', 'epic_games', 'ea_app', 'ubisoft'}
            state["hidden_platforms"] = [p for p in (updates["hidden_platforms"] or []) if p in safe]

        if "shelves" in updates:
            state["shelves"] = updates["shelves"]

        _write_state_atomic(state)
        return state

@config_bp.route('/api/update_state', methods=['POST'])
def update_state_api():
    new_data = request.json
    save_state(new_data)
    return jsonify({"status": "success"})

@config_bp.route('/api/theme', methods=['GET'])
def get_theme():
    return jsonify({"status": "success", "theme": load_theme(), "defaults": DEFAULT_THEME})

@config_bp.route('/api/theme', methods=['POST'])
def post_theme():
    data = request.json or {}
    if data.get('reset'):
        saved = load_saved_themes()
        if os.path.exists(THEME_PATH):
            os.remove(THEME_PATH)
        # Re-write saved themes if any existed
        if saved:
            with open(THEME_PATH, 'w') as f:
                json.dump({'_saved': saved}, f, indent=4)
        return jsonify({"status": "success", "theme": dict(DEFAULT_THEME)})
    vars_dict = data.get('theme', {})
    if not vars_dict:
        return jsonify({"status": "error", "message": "No theme data provided."}), 400
    save_theme(vars_dict)
    return jsonify({"status": "success", "theme": load_theme()})

@config_bp.route('/api/theme/saved', methods=['GET'])
def get_saved_themes():
    return jsonify({"status": "success", "saved": load_saved_themes()})

@config_bp.route('/api/theme/saved', methods=['POST'])
def post_saved_theme():
    data = request.json or {}
    name = (data.get('name') or '').strip()
    vars_dict = data.get('theme', {})
    if not name:
        return jsonify({"status": "error", "message": "Name is required."}), 400
    if not vars_dict:
        return jsonify({"status": "error", "message": "No theme data provided."}), 400
    save_named_theme(name, vars_dict)
    return jsonify({"status": "success"})

@config_bp.route('/api/theme/saved/<name>', methods=['DELETE'])
def delete_saved_theme_route(name):
    delete_named_theme(name)
    return jsonify({"status": "success"})

@config_bp.route('/api/theme/saved/<name>', methods=['PATCH'])
def rename_saved_theme_route(name):
    data = request.json or {}
    new_name = (data.get('name') or '').strip()
    if not new_name:
        return jsonify({"status": "error", "message": "New name is required."}), 400
    ok = rename_named_theme(name, new_name)
    if not ok:
        return jsonify({"status": "error", "message": "Theme not found."}), 404
    return jsonify({"status": "success"})

# ── Account management routes ─────────────────────────────────────────────────

@config_bp.route('/api/accounts', methods=['GET'])
def get_accounts():
    config    = load_config() or {}
    active_id = config.get('active_account')
    accounts  = config.get('accounts', {})
    return jsonify({
        'status':         'success',
        'accounts':       [{**v, 'active': k == active_id} for k, v in accounts.items()],
        'active_account': active_id,
        'sgdb_key':       config.get('sgdb_key', ''),
    })

@config_bp.route('/api/account/switch', methods=['POST'])
def switch_account():
    steam_id = ((request.json or {}).get('steam_id') or '').strip()
    if not steam_id:
        return jsonify({'status': 'error', 'message': 'steam_id required'}), 400
    if not is_configured():
        return jsonify({'status': 'error', 'message': 'Not configured'}), 400
    with open(CONFIG_PATH, 'r') as f:
        config_data = json.load(f)
    if steam_id not in config_data.get('accounts', {}):
        return jsonify({'status': 'error', 'message': 'Account not found'}), 404
    config_data['active_account'] = steam_id
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config_data, f, indent=4)
    return jsonify({'status': 'success'})

@config_bp.route('/api/account/remove', methods=['POST'])
def remove_account():
    steam_id = ((request.json or {}).get('steam_id') or '').strip()
    if not steam_id:
        return jsonify({'status': 'error', 'message': 'steam_id required'}), 400
    if not is_configured():
        return jsonify({'status': 'error', 'message': 'Not configured'}), 400
    with open(CONFIG_PATH, 'r') as f:
        config_data = json.load(f)
    config_data.get('accounts', {}).pop(steam_id, None)
    if config_data.get('active_account') == steam_id:
        remaining = list(config_data.get('accounts', {}).keys())
        config_data['active_account'] = remaining[0] if remaining else None
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config_data, f, indent=4)
    return jsonify({'status': 'success', 'new_active': config_data.get('active_account')})

@config_bp.route('/api/save-sg-username', methods=['POST'])
def save_sg_username():
    username = ((request.json or {}).get('sg_username') or '').strip()
    if not is_configured():
        return jsonify({'status': 'error', 'message': 'Not configured'}), 400
    with open(CONFIG_PATH, 'r') as f:
        config_data = json.load(f)
    config_data['sg_username'] = username
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config_data, f, indent=4)
    return jsonify({'status': 'success'})
