import logging
import requests
from flask import Blueprint, request, jsonify
import html as _html
import json
import os
import re
import sys
import threading
import uuid

log = logging.getLogger(__name__)

_state_lock = threading.Lock()

config_bp = Blueprint('config', __name__)

__version__ = "1.6.1"

IN_FLATPAK = os.path.exists('/.flatpak-info')

if getattr(sys, 'frozen', False):
    BASE_DIR    = os.path.dirname(sys.executable)
    _BUNDLE_DIR = sys._MEIPASS
elif IN_FLATPAK:
    # /app is read-only at runtime; user data lives under XDG_DATA_HOME,
    # which Flatpak already isolates to ~/.var/app/<id>/data per-app.
    _BUNDLE_DIR = '/app/share/playdate'
    BASE_DIR = os.path.join(
        os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')),
        'playdate')
    os.makedirs(BASE_DIR, exist_ok=True)
else:
    BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
    _BUNDLE_DIR = BASE_DIR

IS_PORTABLE = getattr(sys, 'frozen', False) and os.path.isfile(os.path.join(BASE_DIR, 'portable.txt'))

CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
STATE_PATH  = os.path.join(BASE_DIR, 'state.json')
THEME_PATH  = os.path.join(BASE_DIR, 'theme.json')

_gs_lock = threading.Lock()


def get_group_sources_path() -> str:
    """Return the group_sources JSON path for the active account."""
    cfg = load_config()
    steam_id = (cfg or {}).get('active_account', '')
    if steam_id:
        return os.path.join(BASE_DIR, f'group_sources_{steam_id}.json')
    return os.path.join(BASE_DIR, 'group_sources.json')


def load_group_sources() -> dict:
    """Load group_sources JSON for the active account. Returns empty structure if missing."""
    path = get_group_sources_path()
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return {'version': 1, 'sources': {}, 'assignments': {}}


def save_group_sources(data: dict):
    """Atomically save group_sources JSON for the active account."""
    path = get_group_sources_path()
    tmp = path + '.tmp'
    with _gs_lock:
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)


def gs_is_protected(gs: dict, appid: int, group_name: str, excluding_source: str) -> bool:
    """Return True if any source other than excluding_source owns group_name on appid."""
    owners = gs.get('assignments', {}).get(str(appid), {}).get(group_name, [])
    return any(s != excluding_source for s in owners)


def gs_add_owner(gs: dict, appid: int, group_name: str, source_id: str):
    """Add source_id as owner of group_name on appid. No-op if already present."""
    game = gs.setdefault('assignments', {}).setdefault(str(appid), {})
    owners = game.setdefault(group_name, [])
    if source_id not in owners:
        owners.append(source_id)


def gs_remove_owner(gs: dict, appid: int, group_name: str, source_id: str):
    """Remove source_id as owner of group_name on appid. Cleans up empty entries."""
    assignments = gs.get('assignments', {})
    game = assignments.get(str(appid), {})
    owners = game.get(group_name, [])
    if source_id in owners:
        owners.remove(source_id)
    if not owners:
        game.pop(group_name, None)
    if not game:
        assignments.pop(str(appid), None)

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
    if not os.path.exists(THEME_PATH):
        return {}
    try:
        with open(THEME_PATH, 'r') as f:
            data = json.load(f)
        return data.get('_saved', {})
    except Exception:
        return {}

def save_named_theme(name, vars_dict):
    clean = {k: v for k, v in vars_dict.items() if k in DEFAULT_THEME}
    saved = load_saved_themes()
    saved[name] = clean
    # Re-save the whole file preserving active theme
    active = load_theme()
    active['_saved'] = saved
    with open(THEME_PATH, 'w') as f:
        json.dump(active, f, indent=4)

def delete_named_theme(name):
    saved = load_saved_themes()
    saved.pop(name, None)
    active = load_theme()
    active['_saved'] = saved
    with open(THEME_PATH, 'w') as f:
        json.dump(active, f, indent=4)

def rename_named_theme(old_name, new_name):
    saved = load_saved_themes()
    if old_name not in saved:
        return False
    saved[new_name] = saved.pop(old_name)
    active = load_theme()
    active['_saved'] = saved
    with open(THEME_PATH, 'w') as f:
        json.dump(active, f, indent=4)
    return True

def _cond(column, value):
    return {"type": "condition", "column": column, "operator": "=", "value": value}

def _group(logic, *conds):
    return {"type": "group", "logic": logic, "items": list(conds)}

BUILTIN_FILTERS = {
    "all_games":     {"label": "All Games",               "where": "1=1",                                                    "group": "general"},
    "installed":     {"label": "Installed",               "where": "installed = 1",                                          "group": "general",
                      "tree": _group("AND", _cond("installed", "1"))},
    "not_installed": {"label": "Not Installed",           "where": "installed = 0",                                          "group": "general",
                      "tree": _group("AND", _cond("installed", "0"))},
    "not_beaten":    {"label": "Never Played / Unfinished", "where": "completion_status IN ('Never Played', 'Unfinished')",  "group": "general",
                      "tree": _group("OR", _cond("completion_status", "Never Played"), _cond("completion_status", "Unfinished"))},
    "beaten":        {"label": "Beaten / Completed",      "where": "completion_status IN ('Beaten', 'Completed')",           "group": "general",
                      "tree": _group("OR", _cond("completion_status", "Beaten"), _cond("completion_status", "Completed"))},
    # Individual completion statuses
    "never_played":  {"label": "Never Played",            "where": "completion_status = 'Never Played'",                    "group": "status",
                      "tree": _group("AND", _cond("completion_status", "Never Played"))},
    "unfinished":    {"label": "Unfinished",              "where": "completion_status = 'Unfinished'",                      "group": "status",
                      "tree": _group("AND", _cond("completion_status", "Unfinished"))},
    "beaten_only":   {"label": "Beaten",                  "where": "completion_status = 'Beaten'",                          "group": "status",
                      "tree": _group("AND", _cond("completion_status", "Beaten"))},
    "completed":     {"label": "Completed",               "where": "completion_status = 'Completed'",                       "group": "status",
                      "tree": _group("AND", _cond("completion_status", "Completed"))},
    "wont_play":     {"label": "Won't Play",              "where": "completion_status = 'Won''t Play'",                     "group": "status",
                      "tree": _group("AND", _cond("completion_status", "Won't Play"))},
    # Widget presets — no SQL
    "clock":          {"label": "Clock",                  "where": None},
    "completion_pie": {"label": "Completion Chart",       "where": None},
}

DEFAULT_CARD_OUTLINES = {
    "enabled": {"library": True, "home": True, "pick6": True},
    "rules": [
        {"id": None, "label": "Completed",    "color": "#5BC0DE", "priority": 0,
         "filter": {"type": "preset", "preset_key": "completed"}},
        {"id": None, "label": "Beaten",       "color": "#5CB85C", "priority": 1,
         "filter": {"type": "preset", "preset_key": "beaten_only"}},
        {"id": None, "label": "Unfinished",   "color": "#F0AD4E", "priority": 2,
         "filter": {"type": "preset", "preset_key": "unfinished"}},
        {"id": None, "label": "Won't Play",   "color": "#D9534F", "priority": 3,
         "filter": {"type": "preset", "preset_key": "wont_play"}},
        {"id": None, "label": "Never Played", "color": "#EEEEEE", "priority": 4,
         "filter": {"type": "preset", "preset_key": "never_played"}},
    ]
}


def resolve_outline_rule_where(rule, saved_filters):
    """Return a SQL WHERE string for a card outline rule, or None if unresolvable."""
    f = rule.get('filter', {})
    ftype = f.get('type')
    if ftype == 'preset':
        entry = BUILTIN_FILTERS.get(f.get('preset_key', ''))
        if entry and entry.get('where'):
            return entry['where']
    elif ftype == 'saved':
        fid = f.get('filter_id')
        for name, sf in saved_filters.items():
            wrapped = sf if isinstance(sf, dict) and 'tree' in sf else {'tree': sf}
            if wrapped.get('id') == fid:
                from index import _filter_tree_to_sql
                return _filter_tree_to_sql(wrapped['tree'])
    elif ftype == 'custom':
        tree = f.get('tree')
        if tree:
            from index import _filter_tree_to_sql
            return _filter_tree_to_sql(tree)
    return None

DEFAULT_SHELVES = [
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
    "hltb_match_threshold": 99,
    "group_by": None,
    "ui_scale": 100,
    "auto_promote_unfinished": True,
}

def validate_steam_creds(api_key, steam_id):
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

def _active_platform_priority(state):
    """Return platform_priority for platforms that exist in the DB.

    Starts from the user-saved order (falling back to the dynamic default),
    then appends any DB-present platforms not yet in the list so newly
    installed plugins show up without requiring a manual save.
    """
    try:
        from plugins import get_platform_priority
        default = get_platform_priority()
    except Exception:
        from database import PLATFORM_PRIORITY_DEFAULT
        default = PLATFORM_PRIORITY_DEFAULT
    priority = state.get('platform_priority') or default
    try:
        from database import get_db
        db = get_db()
        rows = db.execute("SELECT DISTINCT platform AS p FROM games").fetchall()
        db.close()
        present = {r['p'] for r in rows}
        ordered = [p for p in priority if p in present]
        for p in default:
            if p in present and p not in ordered:
                ordered.append(p)
        return ordered
    except Exception:
        return priority


@config_bp.app_context_processor
def inject_config_status():
    config = load_config()
    config_exists = config is not None
    config = config or {}
    active_id = config.get('active_account')
    accounts  = config.get('accounts', {})
    active    = accounts.get(active_id, {})
    needs_config = not config_exists or not active_id or active_id not in accounts
    state = load_state()
    accounts_list = [
        {**v, 'active': k == active_id}
        for k, v in accounts.items()
    ]
    return dict(
        config_exists=config_exists,
        needs_config=needs_config,
        existing_steam_id=active.get('steam_id', ''),
        existing_api_key=active.get('api_key', ''),
        existing_sgdb_key=config.get('sgdb_key', ''),
        existing_sg_username=config.get('sg_username', ''),
        accounts_list=accounts_list,
        active_steam_id=active_id or '',
        initial_fullscreen=state.get('fullscreen', False),
        gamepad_enabled=state.get('gamepad_enabled', True),
        gamepad_suppress_on_launch=state.get('gamepad_suppress_on_launch', True),
        button_remaps=state.get('button_remaps', {}),
        hltb_match_threshold=state.get('hltb_match_threshold', 99),
        hide_duplicates=state.get('hide_duplicates', True),
        ui_scale=state.get('ui_scale', 100),
        auto_promote_unfinished=state.get('auto_promote_unfinished', True),
        platform_priority=_active_platform_priority(state),
        app_version=__version__,
    )

def load_config():
    if is_configured():
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return None

def is_configured():
    return os.path.exists(CONFIG_PATH)

def _save_config_data(data):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(data, f, indent=4)

def get_active_account():
    """Returns the active account dict {steam_id, api_key, label}, or None."""
    config = load_config()
    if not config:
        return None
    active_id = config.get('active_account', '')
    return config.get('accounts', {}).get(active_id)

def get_active_db_path():
    config = load_config()
    if config:
        active_id = config.get('active_account', '')
        if active_id:
            return os.path.join(BASE_DIR, f'games_{active_id}.db')
    return os.path.join(BASE_DIR, 'games_default.db')

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
        _save_config_data(config_data)
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

    _save_config_data(config_data)
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
    for key, val in [('artwork_orientation', 'vertical'), ('card_height', 200), ('hide_duplicates', True)]:
        if key not in state:
            state[key] = val
            dirty = True
    if 'shelves' not in state:
        state['shelves'] = get_default_shelves()
        dirty = True

    # Migrate saved filters: wrap bare trees as {id, tree} and assign missing UUIDs
    saved = state.get('saved_filters', {})
    for name, val in list(saved.items()):
        if not isinstance(val, dict) or 'tree' not in val:
            saved[name] = {'id': str(uuid.uuid4()), 'tree': val}
            dirty = True
        elif not val.get('id'):
            val['id'] = str(uuid.uuid4())
            dirty = True

    # Trim pagywosg_verified to library appids only — removes non-owned games stored by older builds
    def _pv_bloated(tree):
        return isinstance(tree, dict) and len(tree.get('pagywosg_verified') or {}) > 200

    _needs_pv_trim = _pv_bloated(state.get('filter_tree') or {}) or any(
        _pv_bloated(sf.get('tree') if isinstance(sf, dict) else sf)
        for sf in state.get('saved_filters', {}).values()
    )
    if _needs_pv_trim:
        try:
            from database import get_db as _get_db_cfg
            _db_cfg = _get_db_cfg()
            _lib_ids = {str(r[0]) for r in _db_cfg.execute("SELECT appid FROM games").fetchall()}
            _db_cfg.close()

            def _trim_pv(tree):
                pv = tree.get('pagywosg_verified') if isinstance(tree, dict) else None
                if not pv:
                    return tree, False
                trimmed = {k: v for k, v in pv.items() if k in _lib_ids}
                if len(trimmed) == len(pv):
                    return tree, False
                return {**tree, 'pagywosg_verified': trimmed}, True

            ft = state.get('filter_tree')
            if ft:
                ft2, ch = _trim_pv(ft)
                if ch:
                    state['filter_tree'] = ft2
                    dirty = True

            for _sname, _sf in list(state.get('saved_filters', {}).items()):
                _tree = _sf.get('tree') if isinstance(_sf, dict) else _sf
                if isinstance(_tree, dict):
                    _tree2, _ch = _trim_pv(_tree)
                    if _ch:
                        state['saved_filters'][_sname] = {**_sf, 'tree': _tree2}
                        dirty = True
        except Exception:
            pass  # Skip if DB not ready yet; will retry on next load

    # Compact pagywosg_verified and appid_list_ref in saved filters
    for _sname, _sf in list(state.get('saved_filters', {}).items()):
        _stree = _sf.get('tree') if isinstance(_sf, dict) and 'tree' in _sf else None
        if _stree:
            _stree2 = _compact_tree_pv(_compact_appid_list_refs(_stree))
            if _stree2 is not _stree:
                state['saved_filters'][_sname] = {**_sf, 'tree': _stree2}
                dirty = True

    # Lift duplicate _c id lists to shared storage
    if _compact_shared_ids(state):
        dirty = True

    # Replace full filter_tree with a saved_filter sentinel when it duplicates a saved filter
    ft = state.get('filter_tree')
    if isinstance(ft, dict) and 'saved_filter' not in ft:
        for _sname, _sf in state.get('saved_filters', {}).items():
            _stree = _sf.get('tree') if isinstance(_sf, dict) and 'tree' in _sf else _sf
            if isinstance(_stree, dict) and ft == _stree:
                state['filter_tree'] = {'saved_filter': _sname}
                dirty = True
                break

    # Seed card_outlines with defaults on first run
    if 'card_outlines' not in state:
        import copy
        outline_defaults = copy.deepcopy(DEFAULT_CARD_OUTLINES)
        for rule in outline_defaults['rules']:
            rule['id'] = str(uuid.uuid4())
        state['card_outlines'] = outline_defaults
        dirty = True

    if dirty:
        _write_state_atomic(state)
    return state

def _compact_pv(pv):
    """Compact pagywosg_verified by grouping appids with identical entry lists under _c key."""
    if not isinstance(pv, dict) or '_c' in pv or len(pv) < 5:
        return pv
    by_sig = {}
    for appid, entries in pv.items():
        sig = json.dumps(sorted(entries, key=lambda e: json.dumps(e, sort_keys=True)), sort_keys=True, separators=(',', ':'))
        if sig not in by_sig:
            by_sig[sig] = {'entries': entries, 'appids': []}
        by_sig[sig]['appids'].append(appid)
    compact = []
    flat = {}
    for sig, group in by_sig.items():
        if len(group['appids']) >= 5:
            compact.append({'e': group['entries'], 'ids': sorted(int(a) for a in group['appids'])})
        else:
            for appid in group['appids']:
                flat[appid] = pv[appid]
    if not compact:
        return pv
    return {**flat, '_c': compact}


def _expand_pv(pv, shared_ids=None):
    """Expand compact pagywosg_verified back to a flat {appid_str: entries} dict.
    shared_ids: optional {key: [ids]} from state['_shared_ids'] for resolving 'r' refs."""
    if not isinstance(pv, dict) or '_c' not in pv:
        return pv
    result = {k: v for k, v in pv.items() if k != '_c'}
    for group in pv['_c']:
        entries = group['e']
        ids = (shared_ids or {}).get(group['r']) if 'r' in group else group.get('ids', [])
        for appid in (ids or []):
            key = str(appid)
            existing = result.get(key)
            if existing:
                result[key] = existing + [e for e in entries if e not in existing]
            else:
                result[key] = entries
    return result


_SOURCE_NAMES = {
    'icaio_ga': 'icaio GA matches',
    'icaio_wl': 'icaio wishlist matches',
}

def _name_for_ids(ids):
    """Return a descriptive key for an id list by matching against supplement sources."""
    id_set = frozenset(ids)
    for source, source_ids in _get_supplement_source_appids().items():
        if source_ids and id_set <= source_ids:
            return _SOURCE_NAMES.get(source, source)
    return None


def _compact_shared_ids(state):
    """Lift duplicate _c id lists across saved filters into state['_shared_ids'].
    Returns True if state was modified."""
    dirty = False
    # Collect all _c groups with inline ids lists across all saved filter trees
    all_groups = []
    for sf in state.get('saved_filters', {}).values():
        tree = sf.get('tree') if isinstance(sf, dict) and 'tree' in sf else None
        pv = tree.get('pagywosg_verified') if isinstance(tree, dict) else None
        if not isinstance(pv, dict):
            continue
        for group in pv.get('_c', []):
            if 'ids' in group:
                all_groups.append(group)

    # Find lists appearing more than once
    sig_to_ids = {}
    sig_counts = {}
    for group in all_groups:
        sig = json.dumps(group['ids'], separators=(',', ':'))
        sig_to_ids[sig] = group['ids']
        sig_counts[sig] = sig_counts.get(sig, 0) + 1

    shared_sigs = {sig for sig, count in sig_counts.items() if count > 1}
    if not shared_sigs:
        return False

    existing = state.get('_shared_ids', {})
    # Build reverse map: sig -> existing key
    existing_by_sig = {json.dumps(ids, separators=(',', ':')): key for key, ids in existing.items()}

    for group in all_groups:
        sig = json.dumps(group['ids'], separators=(',', ':'))
        if sig not in shared_sigs:
            continue
        # Reuse existing key or assign a new descriptive one
        key = existing_by_sig.get(sig) or _name_for_ids(group['ids']) or f"s{len(existing)}"
        if key not in existing or existing[key] != group['ids']:
            existing = {**existing, key: group['ids']}
            existing_by_sig[sig] = key
            dirty = True
        group.pop('ids')
        group['r'] = key
        dirty = True

    if dirty:
        state['_shared_ids'] = existing
    return dirty


def _compact_tree_pv(tree):
    """Compact pagywosg_verified inside a filter tree dict, if present."""
    if not isinstance(tree, dict) or 'pagywosg_verified' not in tree:
        return tree
    pv2 = _compact_pv(tree['pagywosg_verified'])
    return tree if pv2 is tree['pagywosg_verified'] else {**tree, 'pagywosg_verified': pv2}


_supplement_appids_cache = None  # {source: frozenset(appids)}

def _get_supplement_source_appids():
    """Return cached {source_key: frozenset} for known supplement appid lists."""
    global _supplement_appids_cache
    if _supplement_appids_cache is not None:
        return _supplement_appids_cache
    result = {}
    try:
        path = os.path.join(BASE_DIR, 'pagywosg_supplement.json')
        with open(path) as f:
            sup = json.load(f)
        result['icaio_ga'] = frozenset(g['appid'] for g in sup.get('icaio_giveaways', []))
        result['icaio_wl'] = frozenset(int(k) for k in sup.get('icaio_wishlist', {}))
    except Exception:
        pass
    _supplement_appids_cache = result
    return result


def _compact_appid_list_refs(tree):
    """Replace auto appid_list nodes with appid_list_ref when appids are a subset of a supplement source."""
    if not isinstance(tree, dict):
        return tree
    if tree.get('type') == 'appid_list' and tree.get('auto'):
        node_ids = frozenset(a for a in tree.get('appids', []) if isinstance(a, int))
        for source, source_ids in _get_supplement_source_appids().items():
            if source_ids and node_ids <= source_ids:
                return {'type': 'appid_list_ref', 'label': tree.get('label', ''), 'source': source}
    if tree.get('type') == 'group':
        new_items = [_compact_appid_list_refs(item) for item in tree.get('items', [])]
        if new_items != tree.get('items', []):
            return {**tree, 'items': new_items}
    return tree


def _expand_appid_list_refs(tree):
    """Replace appid_list_ref nodes with full appid_list nodes using supplement data.
    Used before sending saved filter trees to the browser."""
    if not isinstance(tree, dict):
        return tree
    if tree.get('type') == 'appid_list_ref':
        source = tree.get('source', '')
        appids = sorted(_get_supplement_source_appids().get(source, frozenset()))
        return {'type': 'appid_list', 'appids': appids, 'label': tree.get('label', ''), 'auto': True}
    if tree.get('type') == 'group':
        new_items = [_expand_appid_list_refs(item) for item in tree.get('items', [])]
        if new_items != tree.get('items', []):
            return {**tree, 'items': new_items}
    return tree


def _expand_tree_pv(tree):
    """Expand compact pagywosg_verified inside a filter tree dict, if present."""
    if not isinstance(tree, dict) or 'pagywosg_verified' not in tree:
        return tree
    pv2 = _expand_pv(tree['pagywosg_verified'])
    return tree if pv2 is tree['pagywosg_verified'] else {**tree, 'pagywosg_verified': pv2}


def _expand_tree_pv_with_shared(tree, shared_ids):
    """Expand compact pagywosg_verified (including shared-id refs) inside a filter tree dict."""
    if not isinstance(tree, dict) or 'pagywosg_verified' not in tree:
        return tree
    pv2 = _expand_pv(tree['pagywosg_verified'], shared_ids)
    return tree if pv2 is tree['pagywosg_verified'] else {**tree, 'pagywosg_verified': pv2}


def resolve_active_filter_tree(state):
    """Resolve a {saved_filter: name} sentinel to the actual tree, or return tree as-is.
    Always expands compact pagywosg_verified and appid_list_ref nodes before returning."""
    shared_ids = state.get('_shared_ids', {})
    ft = state.get('filter_tree')
    if isinstance(ft, dict) and 'saved_filter' in ft:
        name = ft['saved_filter']
        sf = state.get('saved_filters', {}).get(name)
        if sf:
            tree = sf.get('tree') if isinstance(sf, dict) and 'tree' in sf else sf
            return _expand_appid_list_refs(_expand_tree_pv_with_shared(tree, shared_ids))
        return None  # referenced filter was deleted/renamed
    return _expand_appid_list_refs(_expand_tree_pv_with_shared(ft, shared_ids))


def load_state():
    """Loads the current state or creates it if missing."""
    with _state_lock:
        return _load_state_unlocked()

def save_state(updates):
    with _state_lock:
        state = _load_state_unlocked()

        _PASSTHROUGH = {"filter_tree", "sort", "order", "artwork_orientation", "card_height",
                        "check_for_updates", "window_state", "fullscreen",
                        "pagywosg_sg_group", "shelves", "group_by",
                        "card_outlines"}
        for key in _PASSTHROUGH:
            if key in updates:
                val = updates[key]
                if key == 'filter_tree' and isinstance(val, dict) and 'saved_filter' not in val:
                    val = _compact_tree_pv(_compact_appid_list_refs(val))
                state[key] = val
        if "hltb_match_threshold" in updates:
            state["hltb_match_threshold"] = int(updates["hltb_match_threshold"])
        if "ui_scale" in updates:
            state["ui_scale"] = max(75, min(200, int(updates["ui_scale"])))
        if "auto_promote_unfinished" in updates:
            state["auto_promote_unfinished"] = bool(updates["auto_promote_unfinished"])
        if "hide_duplicates" in updates:
            state["hide_duplicates"] = bool(updates["hide_duplicates"])
        if "platform_priority" in updates:
            import re as _re
            _plat_re = _re.compile(r'^[a-z][a-z0-9_]*$')
            incoming = [p for p in (updates["platform_priority"] or []) if _plat_re.match(p or '')]
            # Append any DB platforms not already present (keeps the list complete)
            try:
                from database import get_db as _get_db
                _db = _get_db()
                _known = [r[0] for r in _db.execute(
                    "SELECT DISTINCT platform FROM games WHERE platform IS NOT NULL AND platform != ''"
                ).fetchall()]
                _db.close()
            except Exception:
                _known = []
            for p in ['steam'] + _known:
                if p and p not in incoming:
                    incoming.append(p)
            state["platform_priority"] = incoming
        if "hidden_platforms" in updates:
            import re as _re
            _plat_re = _re.compile(r'^[a-z][a-z0-9_]*$')
            state["hidden_platforms"] = [p for p in (updates["hidden_platforms"] or []) if _plat_re.match(p or '')]
        if "pagywosg_comp_defaults" in updates:
            _valid_cs = {'Never Played', 'Unfinished', 'Beaten', 'Completed', "Won't Play"}
            state["pagywosg_comp_defaults"] = [s for s in (updates["pagywosg_comp_defaults"] or []) if s in _valid_cs]
        if "gamepad_enabled" in updates:
            state["gamepad_enabled"] = bool(updates["gamepad_enabled"])
        if "gamepad_suppress_on_launch" in updates:
            state["gamepad_suppress_on_launch"] = bool(updates["gamepad_suppress_on_launch"])
        if "button_remaps" in updates:
            _valid_actions = {'a','b','x','y','lb','rb','back','start','up','down','left','right'}
            remaps = updates["button_remaps"]
            if isinstance(remaps, dict):
                state["button_remaps"] = {
                    str(k): v for k, v in remaps.items()
                    if str(k).lstrip('-').isdigit() and v in _valid_actions
                }
            else:
                state["button_remaps"] = {}

        _compact_shared_ids(state)
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
    config_data = load_config()
    if not config_data:
        return jsonify({'status': 'error', 'message': 'Not configured'}), 400
    if steam_id not in config_data.get('accounts', {}):
        return jsonify({'status': 'error', 'message': 'Account not found'}), 404
    config_data['active_account'] = steam_id
    _save_config_data(config_data)
    return jsonify({'status': 'success'})

@config_bp.route('/api/account/remove', methods=['POST'])
def remove_account():
    steam_id = ((request.json or {}).get('steam_id') or '').strip()
    if not steam_id:
        return jsonify({'status': 'error', 'message': 'steam_id required'}), 400
    config_data = load_config()
    if not config_data:
        return jsonify({'status': 'error', 'message': 'Not configured'}), 400
    config_data.get('accounts', {}).pop(steam_id, None)
    if config_data.get('active_account') == steam_id:
        remaining = list(config_data.get('accounts', {}).keys())
        config_data['active_account'] = remaining[0] if remaining else None
    _save_config_data(config_data)
    return jsonify({'status': 'success', 'new_active': config_data.get('active_account')})

@config_bp.route('/api/save-sg-username', methods=['POST'])
def save_sg_username():
    username = ((request.json or {}).get('sg_username') or '').strip()
    config_data = load_config()
    if not config_data:
        return jsonify({'status': 'error', 'message': 'Not configured'}), 400
    config_data['sg_username'] = username
    _save_config_data(config_data)
    return jsonify({'status': 'success'})


# ── Launcher config ───────────────────────────────────────────────────────────

def get_launcher_config(platform_id):
    """Return launcher config dict for platform_id, or {} if not set."""
    config = load_config() or {}
    return config.get('launchers', {}).get(platform_id, {})


def save_launcher_config(platform_id, cfg):
    """Persist launcher config for platform_id into config.json['launchers']."""
    config_data = load_config()
    if not config_data:
        config_data = {'active_account': None, 'sgdb_key': '', 'accounts': {}}
    launchers = config_data.setdefault('launchers', {})
    launchers[platform_id] = cfg
    _save_config_data(config_data)


@config_bp.route('/api/launcher-config/<platform_id>', methods=['GET'])
def get_launcher_config_route(platform_id):
    import plugins
    from runners.wine import find_wine_binary, find_proton_wine
    from runners.launcher_installer import default_prefix
    cfg = get_launcher_config(platform_id)
    manifest = plugins.plugin_manifest(platform_id)
    installer_cfg = manifest.get('launcher', {}).get('installer')
    detected = find_proton_wine() or find_wine_binary()
    return jsonify({
        'status':              'success',
        'config':              cfg,
        'wine_bin_detected':   detected,
        'installer_available': installer_cfg is not None,
        'default_prefix':      default_prefix(platform_id),
    })


@config_bp.route('/api/launcher-config/<platform_id>', methods=['POST'])
def save_launcher_config_route(platform_id):
    data = request.get_json(silent=True) or {}
    allowed = {'wine_bin', 'prefix', 'mode'}
    cfg = {k: v for k, v in data.items() if k in allowed}
    save_launcher_config(platform_id, cfg)
    return jsonify({'status': 'success'})


@config_bp.route('/api/launcher-install/<platform_id>', methods=['POST'])
def start_launcher_install_route(platform_id):
    import plugins
    from runners.launcher_installer import start_install, default_prefix
    manifest = plugins.plugin_manifest(platform_id)
    launcher = manifest.get('launcher', {})
    installer_cfg = launcher.get('installer')
    if not installer_cfg:
        return jsonify({'status': 'error', 'message': 'No installer configured for this plugin'}), 400
    installer_cfg = dict(installer_cfg)
    if 'exe_name' not in installer_cfg and launcher.get('exe_name'):
        installer_cfg['exe_name'] = launcher['exe_name']
    data     = request.get_json(silent=True) or {}
    prefix   = (data.get('prefix') or '').strip() or default_prefix(platform_id)
    wine_bin = (data.get('wine_bin') or '').strip() or None
    started = start_install(platform_id, installer_cfg, prefix, wine_bin)
    return jsonify({'status': 'started' if started else 'already_running'})


@config_bp.route('/api/launcher-install/<platform_id>/status', methods=['GET'])
def get_launcher_install_status_route(platform_id):
    from runners.launcher_installer import get_state
    return jsonify(get_state(platform_id))


@config_bp.route('/api/launcher-uninstall/<platform_id>', methods=['POST'])
def launcher_uninstall_route(platform_id):
    import shutil
    cfg = get_launcher_config(platform_id)
    prefix = os.path.expanduser(cfg.get('prefix', '').strip())
    removed = False
    if prefix:
        try:
            if os.path.isdir(prefix):
                shutil.rmtree(prefix)
                removed = True
                log.info('Launcher uninstall [%s]: deleted prefix %s', platform_id, prefix)
        except Exception as e:
            log.error('Launcher uninstall [%s]: failed to delete prefix %s: %s', platform_id, prefix, e)
            return jsonify({'status': 'error', 'message': f'Failed to delete prefix: {e}'}), 500
    config_data = load_config() or {}
    launchers = config_data.get('launchers', {})
    launchers.pop(platform_id, None)
    config_data['launchers'] = launchers
    _save_config_data(config_data)
    log.info('Launcher uninstall [%s]: cleared config (prefix_deleted=%s)', platform_id, removed)
    return jsonify({'status': 'success', 'prefix_deleted': removed})


# ── What's New ────────────────────────────────────────────────────────────────

def _parse_version_tuple(v):
    v = v.lstrip('v')
    try:
        return tuple(int(x) for x in v.split('.'))
    except ValueError:
        return (0, 0, 0)


def _build_whats_new_html(since_version=None):
    notes_path = os.path.join(_BUNDLE_DIR, 'CHANGELOG.md')
    if not os.path.exists(notes_path):
        return ''
    with open(notes_path, 'r', encoding='utf-8') as f:
        content = f.read()

    since_tuple = _parse_version_tuple(since_version) if since_version else None
    sections = re.split(r'\n(?=## v)', content)
    parts = []

    for section in sections:
        m = re.match(r'^## (v[\d.]+)(?:\s*[—\-]+\s*(.+))?', section.strip())
        if not m:
            continue
        ver_str, date = m.group(1), (m.group(2) or '').strip()
        ver_tuple = _parse_version_tuple(ver_str)
        if since_tuple and ver_tuple <= since_tuple:
            continue

        out = (f'<div class="wn-version">'
               f'<h3>{_html.escape(ver_str)}'
               f' <span class="wn-date">{_html.escape(date)}</span></h3>')

        rest = section[m.end():].strip()
        for sub in re.split(r'\n(?=### )', rest):
            sm = re.match(r'^### (.+)\n', sub)
            if not sm:
                continue
            sub_name = sm.group(1).strip()
            items = [ln[2:].strip() for ln in sub[sm.end():].split('\n') if ln.startswith('- ')]
            if not items:
                continue
            out += f'<div class="wn-section"><h4>{_html.escape(sub_name)}</h4><ul>'
            for item in items:
                escaped = _html.escape(item)
                escaped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
                escaped = re.sub(r'\*(.+?)\*',     r'<em>\1</em>',         escaped)
                out += f'<li>{escaped}</li>'
            out += '</ul></div>'

        out += '</div>'
        parts.append(out)

    return ''.join(parts)


@config_bp.route('/api/whats-new', methods=['GET'])
def get_whats_new():
    if not is_configured():
        return jsonify({'show': False})
    config_data = load_config() or {}
    last_seen = config_data.get('last_seen_version')
    if last_seen == __version__:
        return jsonify({'show': False})
    notes_html = _build_whats_new_html(since_version=last_seen)
    if not notes_html:
        return jsonify({'show': False})
    return jsonify({'show': True, 'html': notes_html, 'version': __version__})


@config_bp.route('/api/whats-new/dismiss', methods=['POST'])
def dismiss_whats_new():
    if not is_configured():
        return jsonify({'status': 'ok'})
    config_data = load_config() or {}
    config_data['last_seen_version'] = __version__
    _save_config_data(config_data)
    return jsonify({'status': 'ok'})
