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

# ── Linux/Wayland fixes — must be set before importing webview ────────────────
os.environ.setdefault("PYWEBVIEW_GUI", "gtk")
os.environ.setdefault("GDK_BACKEND", "x11")
os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")
os.environ.setdefault("GDK_PROGRAM_CLASS", "PlayDate")

# ── Imports ───────────────────────────────────────────────────────────────────
import webview

from app import create_app
from config import BASE_DIR
from database import init_db
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
            if _webview_window.fullscreen:
                _webview_window.restore()
            else:
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
        init_db()
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
    window = webview.create_window(
        title    = "PlayDate",
        url      = URL,
        maximized = True,
        min_size = (1024, 600),
        js_api   = _api,
    )
    _webview_window = window

    # 6. Linux icon fix
    _fix_window_icon(window)

    # 7. Start webview event loop
    log.info("Launching PlayDate window")
    webview.start(debug=False)

    # 8. Clean exit
    log.info("Window closed. PlayDate exiting.")
    stop_steamapps_watcher()
    sys.exit(0)
