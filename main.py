"""
main.py — PlayDate standalone launcher
Uses pywebview (native OS webview, no browser required) + waitress (production WSGI server).
"""

import logging
import os
import sys
import threading
import time

# ── PyInstaller frozen-path fix ───────────────────────────────────────────────
# When running as a bundled .exe, sys._MEIPASS points to the folder where
# PyInstaller extracted everything. We need Flask to find templates and static
# files from there, not from __file__ (which no longer exists meaningfully).
if getattr(sys, 'frozen', False):
    _BUNDLE_DIR = sys._MEIPASS
    _APP_DIR    = os.path.dirname(sys.executable)  # folder next to the .exe
else:
    _BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    _APP_DIR    = _BUNDLE_DIR

# ── Logging ───────────────────────────────────────────────────────────────────
# Log file goes next to the .exe (or script), not inside the bundle
LOG_PATH = os.path.join(_APP_DIR, 'playdate.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
        logging.StreamHandler(),
    ],
    force=True,
)
log = logging.getLogger(__name__)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_exception

# ── Linux WebKit check — friendly error before pywebview blows up ─────────────
if sys.platform == "linux" and not getattr(sys, 'frozen', False):
    try:
        import gi
        gi.require_version('WebKit2', '4.0')
        from gi.repository import WebKit2  # noqa
    except Exception:
        import subprocess, shutil
        distro_id = ""
        try:
            with open("/etc/os-release") as _f:
                for _line in _f:
                    if _line.startswith("ID_LIKE=") or _line.startswith("ID="):
                        distro_id = _line.split("=", 1)[1].strip().strip('"').lower()
                        break
        except Exception:
            pass
        if any(d in distro_id for d in ("debian", "ubuntu")):
            cmd = "sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.0"
        elif any(d in distro_id for d in ("fedora", "rhel", "centos")):
            cmd = "sudo dnf install python3-gobject webkit2gtk4.0"
        elif "arch" in distro_id:
            cmd = "sudo pacman -S python-gobject webkit2gtk"
        else:
            cmd = "See README.md for your distribution's install command."
        msg = (
            "PlayDate requires WebKit2GTK to display its interface.\n\n"
            f"Install it with:\n\n    {cmd}\n\n"
            "Then re-run PlayDate."
        )
        log.critical(msg)
        # Show a plain tkinter dialog if possible, otherwise just print
        try:
            import tkinter as _tk
            from tkinter import messagebox as _mb
            _r = _tk.Tk(); _r.withdraw()
            _mb.showerror("Missing dependency — WebKit2GTK", msg)
            _r.destroy()
        except Exception:
            print(msg)
        sys.exit(1)

# ── Linux/Wayland fixes — must be set before importing webview ────────────────
os.environ.setdefault("PYWEBVIEW_GUI", "gtk")
os.environ.setdefault("GDK_BACKEND", "x11")
os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")
os.environ.setdefault("GDK_PROGRAM_CLASS", "PlayDate")

# ── Imports ───────────────────────────────────────────────────────────────────
import webview

from app import create_app
from config import BASE_DIR, migrate_to_multi_account
from database import init_db, migrate_image_files
from utils import find_steam_path, start_steamapps_watcher, stop_steamapps_watcher

# ── Config ────────────────────────────────────────────────────────────────────
PORT      = 5000
HOST      = "127.0.0.1"
URL       = f"http://{HOST}:{PORT}/"
ICON_PATH = os.path.join(BASE_DIR, "static", "img", "favicon.png")

# ── Flask server thread ────────────────────────────────────────────────────────
def _run_flask(flask_app):
    from waitress import serve
    log.info(f"Starting waitress on {HOST}:{PORT}")
    serve(flask_app, host=HOST, port=PORT, threads=8, _quiet=True)

# ── GTK icon patch (Linux only) ───────────────────────────────────────────────
def _fix_window_icon(window):
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, GLib, GdkPixbuf

        def apply_icon():
            try:
                app = Gtk.Application.get_default()
                if app:
                    app.set_application_id('playdate')
                for gtk_window in Gtk.Window.list_toplevels():
                    gtk_window.set_wmclass('playdate', 'PlayDate')
                    gtk_window.set_role('PlayDate')
                    if os.path.exists(ICON_PATH):
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file(ICON_PATH)
                        gtk_window.set_icon(pixbuf)
            except Exception as e:
                log.warning(f"Icon patch failed: {e}")

        window.events.loaded += lambda: apply_icon()
        apply_icon()
    except Exception:
        pass

# ── Quit handler ──────────────────────────────────────────────────────────────
def _destroy_window():
    try:
        for w in webview.windows:
            w.destroy()
    except Exception as e:
        log.warning(f"Window destroy failed: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
# Module-level window reference so Flask routes can call pywebview APIs
_webview_window = None


class PyWebviewAPI:
    """JS-callable API exposed to the webview via js_api."""

    def toggle_fullscreen(self):
        """Toggle native fullscreen on the pywebview window."""
        if _webview_window is None:
            return
        try:
            _webview_window.toggle_fullscreen()
        except Exception as e:
            log.warning(f"Fullscreen toggle failed: {e}")

    def open_url(self, url):
        """Open a URL in the system default browser, bringing it to the foreground."""
        import subprocess, platform
        try:
            sys = platform.system()
            if sys == 'Darwin':
                subprocess.Popen(['open', url])
            elif sys == 'Linux':
                subprocess.Popen(['xdg-open', url])
            else:  # Windows
                subprocess.Popen(f'start "" "{url}"', shell=True)
        except Exception as e:
            log.warning(f"open_url failed for {url!r}: {e}")

    def pick_open_path(self, file_types=None):
        """
        Open a native Open-File dialog and return the chosen path string,
        or None if the user cancelled.
        file_types: list of strings like ['ZIP Files (*.zip)'].
        """
        if _webview_window is None:
            return None
        if file_types is None:
            file_types = ('All Files (*.*)',)
        try:
            paths = _webview_window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=tuple(file_types),
            )
            if paths:
                path = paths[0] if isinstance(paths, (list, tuple)) else paths
                return str(path)
        except Exception as e:
            log.warning(f"Open dialog failed: {e}")
        return None

    def pick_save_path(self, suggested_name, file_types=None):
        """
        Open a native Save-As dialog and return the chosen path string,
        or None if the user cancelled.
        file_types: list of strings like ['ZIP Files (*.zip)'], defaults to ZIP.
        """
        if _webview_window is None:
            return None
        if file_types is None:
            file_types = ('ZIP Files (*.zip)',)
        try:
            paths = _webview_window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=suggested_name,
                file_types=tuple(file_types),
            )
            if paths:
                path = paths[0] if isinstance(paths, (list, tuple)) else paths
                return str(path)
        except Exception as e:
            log.warning(f"Save dialog failed: {e}")
        return None


def _load_window_state():
    """Return create_window kwargs derived from saved state, with off-screen safety."""
    from config import load_state
    state = load_state()
    ws        = state.get('window_state') or {}
    fullscreen = state.get('fullscreen', False)
    maximized = ws.get('maximized', True)
    width     = ws.get('width', 1280)
    height    = ws.get('height', 800)

    if fullscreen:
        return dict(fullscreen=True, maximized=False, width=width, height=height, x=None, y=None)

    if maximized or not ws.get('x') is not None:
        return dict(fullscreen=False, maximized=True, width=width, height=height, x=None, y=None)

    x, y = ws['x'], ws['y']

    # Validate the saved position against current screens
    try:
        screens = webview.screens
        saved_screen = ws.get('screen')  # fingerprint: {x, y, width, height}

        # Check the fingerprinted monitor still exists
        screen_ok = not saved_screen or any(
            s.x == saved_screen['x'] and s.y == saved_screen['y'] and
            s.width == saved_screen['width'] and s.height == saved_screen['height']
            for s in screens
        )

        # Check the window centre is on some screen
        cx, cy = x + width // 2, y + height // 2
        on_screen = any(
            s.x <= cx <= s.x + s.width and s.y <= cy <= s.y + s.height
            for s in screens
        )

        if not screen_ok or not on_screen:
            log.info("Saved window position invalid (screen gone or off-screen) — restoring maximized")
            return dict(maximized=True, width=width, height=height, x=None, y=None)
    except Exception as e:
        log.warning(f"Screen validation failed: {e} — using saved state as-is")

    return dict(fullscreen=False, maximized=False, width=width, height=height, x=x, y=y)


def _save_window_state(tracked):
    """Persist the already-tracked window state dict to state.json.
    No window property reads here — safe to call from the closing event."""
    from config import save_state
    try:
        save_state({'window_state': dict(tracked)})
        log.info(f"Window state saved: {tracked}")
    except Exception as e:
        log.warning(f"Failed to save window state: {e}")


if __name__ == '__main__':
    # 1. Create Flask app — pass bundle dir so it finds templates/static
    #    when frozen; falls back to normal behaviour when running as script
    flask_app = create_app(
        template_folder=os.path.join(_BUNDLE_DIR, 'templates'),
        static_folder=os.path.join(_BUNDLE_DIR, 'static'),
    )

    # Patch quit route onto the app instance
    @flask_app.route('/api/quit', methods=['POST'])
    def quit_program():
        from flask import jsonify
        log.info("Quit requested — destroying webview window")
        threading.Timer(0.2, _destroy_window).start()
        return jsonify({"status": "success"})

    # 2. Initialise DB
    try:
        migrate_to_multi_account()
        init_db()
        migrate_image_files()
    except Exception as e:
        log.critical(f"Database initialization failed: {e}", exc_info=True)
        raise

    # 2b. Start steamapps filesystem watcher
    _steamapps_path = find_steam_path()
    if _steamapps_path:
        start_steamapps_watcher(_steamapps_path)
    else:
        log.warning("Steam path not found — steamapps watcher not started")

    # 2c. Sync recent playtime from Steam API in background
    def _run_playtime_sync():
        from scrapers import sync_recent_playtime
        sync_recent_playtime()

    threading.Thread(target=_run_playtime_sync, daemon=True).start()
    log.info("Playtime sync started in background.")

    # 3. Start Flask in a background thread
    flask_thread = threading.Thread(target=_run_flask, args=(flask_app,), daemon=True)
    flask_thread.start()

    # 4. Wait for Flask to be ready
    for _ in range(20):
        try:
            import urllib.request
            urllib.request.urlopen(URL, timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        log.warning("Flask did not respond in time — opening window anyway")

    # 5. Create pywebview window
    _api = PyWebviewAPI()
    _ws = _load_window_state()
    _window_maximized = _ws['maximized']

    window = webview.create_window(
        title            = "PlayDate",
        url              = URL,
        min_size         = (1024, 600),
        js_api           = _api,
        background_color = '#1b2838',
        **_ws,
    )
    _webview_window = window

    # Track window state via events — no property reads at close time (GTK deadlock risk)
    _tracked = {
        'maximized': _ws['maximized'],
        'x': _ws.get('x'), 'y': _ws.get('y'),
        'width': _ws.get('width', 1280), 'height': _ws.get('height', 800),
        'screen': None,
    }

    def _update_screen():
        try:
            x, y, w, h = _tracked['x'], _tracked['y'], _tracked['width'], _tracked['height']
            if None in (x, y): return
            cx, cy = x + w // 2, y + h // 2
            for s in webview.screens:
                if s.x <= cx <= s.x + s.width and s.y <= cy <= s.y + s.height:
                    _tracked['screen'] = {'x': s.x, 'y': s.y, 'width': s.width, 'height': s.height}
                    return
        except Exception: pass

    def _read_pos_bg():
        # Read position off the GTK main thread to avoid idle_add deadlock
        def _do():
            try:
                _tracked.update({'x': window.x, 'y': window.y})
                _update_screen()
            except Exception: pass
        threading.Thread(target=_do, daemon=True).start()

    def _read_size_bg():
        def _do():
            try:
                _tracked.update({'width': window.width, 'height': window.height})
            except Exception: pass
        threading.Thread(target=_do, daemon=True).start()

    def _on_maximized():
        _tracked['maximized'] = True

    def _on_restored():
        _tracked['maximized'] = False
        _read_pos_bg()
        _read_size_bg()

    def _on_moved():
        if not _tracked['maximized']:
            _read_pos_bg()

    def _on_resized():
        if not _tracked['maximized']:
            _read_size_bg()

    def _on_shown():
        # Restore position here — GTK/X11 ignores x/y before window is mapped.
        # Skip on Wayland: the compositor owns placement and move() causes an offset.
        _wayland = bool(os.environ.get('WAYLAND_DISPLAY'))
        if not _wayland and not _ws['maximized'] and _ws.get('x') is not None:
            try:
                window.move(_ws['x'], _ws['y'])
            except Exception as e:
                log.warning(f"Window move failed: {e}")

    def _on_closing():
        _save_window_state(_tracked)

    window.events.maximized += _on_maximized
    window.events.restored  += _on_restored
    window.events.moved     += _on_moved
    window.events.resized   += _on_resized
    window.events.shown     += _on_shown
    window.events.closing   += _on_closing

    # 6. Linux icon fix
    _fix_window_icon(window)

    # 7. Start webview event loop
    log.info("Launching PlayDate window")
    webview.start(debug=False)

    # 8. Clean exit
    log.info("Window closed. PlayDate exiting.")
    stop_steamapps_watcher()
    sys.exit(0)
