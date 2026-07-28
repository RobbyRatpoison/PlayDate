"""System integration routes: launching games, opening paths in the OS file
manager/browser, checking whether a game process is running, and other
small host-level utilities that don't belong to any single feature area."""
import logging
import os
import platform
import re
import subprocess

from flask import Blueprint, jsonify, request

from config import BASE_DIR
from database import get_db
from utils import find_steam_path, sync_local_install_status, record_launch, consume_install_dirty

log = logging.getLogger(__name__)

system_bp = Blueprint('system', __name__)


@system_bp.route('/update-installed')
def update_installed():
    try:
        count = sync_local_install_status()
        return jsonify({"status": "success", "count": count})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@system_bp.route('/api/open-url', methods=['POST'])
def open_url_route():
    url = (request.json or {}).get('url', '')
    if not url:
        return jsonify({"status": "error", "message": "No URL provided"}), 400
    if not (url.startswith('http://') or url.startswith('https://') or url.startswith('steam://')):
        return jsonify({"status": "error", "message": "Scheme not allowed"}), 400
    try:
        os_name = platform.system()
        if os_name == 'Darwin':
            subprocess.Popen(['open', url])
        elif os_name == 'Linux':
            subprocess.Popen(['xdg-open', url])
        else:
            subprocess.Popen(['cmd', '/c', 'start', '', url])
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@system_bp.route('/api/open-install-dir/<appid>', methods=['POST'])
def open_install_dir(appid):
    db = get_db()
    try:
        row = db.execute("SELECT platform, install_path FROM games WHERE appid = ?", (appid,)).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Game not found"}), 404

        game_platform, install_path = row[0], row[1]
    finally:
        db.close()

    path = None
    if game_platform == 'steam' or not game_platform:
        steam_path = find_steam_path()
        if steam_path:
            acf = os.path.join(steam_path, f'appmanifest_{appid}.acf')
            if os.path.exists(acf):
                with open(acf, encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                m = re.search(r'"installdir"\s+"([^"]+)"', content)
                if m:
                    candidate = os.path.join(steam_path, 'common', m.group(1))
                    if os.path.isdir(candidate):
                        path = candidate
    else:
        if install_path and os.path.isdir(install_path):
            path = install_path
        elif install_path and os.path.isfile(install_path):
            path = os.path.dirname(install_path)

    if not path:
        return jsonify({"status": "not_found", "message": "Install directory not found"}), 404

    try:
        os_name = platform.system()
        if os_name == 'Darwin':
            subprocess.Popen(['open', path])
        elif os_name == 'Linux':
            subprocess.Popen(['xdg-open', path])
        else:
            subprocess.Popen(['explorer', path])
        return jsonify({"status": "success", "path": path})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@system_bp.route('/api/open-base-dir', methods=['POST'])
def open_base_dir():
    try:
        os_name = platform.system()
        if os_name == 'Darwin':
            subprocess.Popen(['open', BASE_DIR])
        elif os_name == 'Linux':
            subprocess.Popen(['xdg-open', BASE_DIR])
        else:
            subprocess.Popen(['explorer', BASE_DIR])
        return jsonify({"status": "success", "path": BASE_DIR})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@system_bp.route('/api/launch/<appid>', methods=['POST'])
def launch_game(appid):
    try:
        appid_int = int(appid)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid appid"}), 400

    os_name = platform.system()

    # Look up platform and install status for this game
    db = get_db()
    row = db.execute(
        "SELECT name, platform, platform_id, installed FROM games WHERE appid = ?", (appid_int,)
    ).fetchone()
    db.close()
    game_name     = row['name'] if row else ''
    game_platform = (row['platform'] or 'steam') if row else 'steam'

    if game_platform == 'steam':
        # Steam launch via steam:// URI (handles install too if not installed)
        url = f'steam://run/{appid_int}'
        try:
            if os_name == 'Darwin':
                subprocess.Popen(['open', url])
            elif os_name == 'Linux':
                subprocess.Popen(['xdg-open', url])
            elif os_name == 'Windows':
                subprocess.Popen(['cmd', '/c', 'start', '', url])
            log.info(f"Launched Steam appid {appid_int}")
        except Exception as e:
            log.error(f"Failed to launch Steam appid {appid_int}: {e}")
    else:
        import emulators as _emu
        if _emu.is_emulation_platform(game_platform):
            result = _emu.launch_game(appid_int)
            if result.get('status') == 'success':
                new_ts = record_launch(appid_int)
                if new_ts:
                    from database import ts_to_date
                    return jsonify({'status': 'success', 'last_played': ts_to_date(new_ts)})
            return jsonify(result)
        import plugins as _plugin_registry
        plugin_obj = next(
            (p for p in _plugin_registry.loaded().values() if p.platform == game_platform),
            None,
        )
        if plugin_obj and hasattr(plugin_obj, 'launch_game'):
            log.info(f"Dispatching launch for appid {appid_int} ({game_name!r}) to {game_platform} plugin")
            result = plugin_obj.launch_game(appid_int)
            log.info(f"Launch result for appid {appid_int}: {result}")
            return jsonify(result)
        log.warning(f"No launch handler for platform {game_platform!r} (appid {appid_int})")
        return jsonify({"status": "not_supported",
                        "message": "Launch not yet supported for this platform"}), 501

    # Record the launch date only if the game is marked installed
    new_ts = record_launch(appid_int)
    if new_ts:
        from database import ts_to_date
        return jsonify({"status": "success", "last_played": ts_to_date(new_ts)})
    else:
        return jsonify({"status": "launched", "message": "Game launched but not marked installed — date not updated"})

@system_bp.route('/api/game-running')
def game_running():
    """
    Check whether a Steam game is currently running.
    Uses Steam's 'reaper' process wrapper, which is present for all Steam game
    launches on Linux (Proton and native). Returns {'running': bool} on Linux,
    {'running': null} on other platforms (caller should fall back to focus events).
    """
    if platform.system() != 'Linux':
        return jsonify({'running': None})
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'reaper SteamLaunch'],
            capture_output=True, timeout=3
        )
        return jsonify({'running': result.returncode == 0})
    except Exception:
        return jsonify({'running': None})

@system_bp.route('/api/raise-window', methods=['POST'])
def raise_window_route():
    """Raise and focus the PlayDate window via GTK (Linux only)."""
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, GLib
        main_win = getattr(_webview_window, 'native', None)  # noqa: F821 -- pre-existing bug: _webview_window is never imported here, so this route no-ops (NameError swallowed by the except below); preserved as-is during the app.py blueprint split, not introduced by it
        for win in Gtk.Window.list_toplevels():
            # Only raise the main window — presenting WebKit internal windows
            # (offscreen renderer, etc.) causes KDE to briefly show them as
            # visible top-level windows (the grey circle bug).
            if main_win is not None and win is not main_win:
                continue
            GLib.idle_add(win.present)
    except Exception:
        pass
    return jsonify({'ok': True})

@system_bp.route('/api/log-js-error', methods=['POST'])
def log_js_error():
    data = request.get_json(silent=True) or {}
    ctx   = data.get('context', 'unknown')
    msg   = data.get('error', '')
    stack = data.get('stack', '')
    log.error(f'JS error [{ctx}]: {msg}')
    if stack:
        log.error(f'JS stack [{ctx}]: {stack}')
    return jsonify({'ok': True})

@system_bp.route('/api/install-changed')
def install_changed():
    if not consume_install_dirty():
        return jsonify({'changed': False})
    db = get_db()
    rows = db.execute("SELECT appid FROM games WHERE installed = 1").fetchall()
    db.close()
    return jsonify({'changed': True, 'installed_appids': [r['appid'] for r in rows]})
