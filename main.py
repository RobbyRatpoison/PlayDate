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
        import gi as _gi
        _webkit_ok = False
        for _v in ('4.1', '4.0', '6.0'):
            try:
                _gi.require_version('WebKit2', _v)
                from gi.repository import WebKit2 as _wk2  # noqa
                _webkit_ok = True
                break
            except Exception:
                pass
        if not _webkit_ok:
            raise ImportError("WebKit2GTK not found")
    except Exception:
        import subprocess
        distro_id = ""
        try:
            with open("/etc/os-release") as _f:
                for _line in _f:
                    if _line.startswith("ID_LIKE=") or _line.startswith("ID="):
                        distro_id = _line.split("=", 1)[1].strip().strip('"').lower()
                        break
        except Exception:
            pass
        if "steamos" in distro_id:
            msg = (
                "PlayDate requires WebKit2GTK, which was removed by a SteamOS system update.\n\n"
                "Re-run install_steamdeck.sh (in the PlayDate folder) to reinstall it."
            )
        elif any(d in distro_id for d in ("debian", "ubuntu")):
            cmd = "sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.0"
            msg = (
                "PlayDate requires WebKit2GTK to display its interface.\n\n"
                f"Install it with:\n\n    {cmd}\n\nThen re-run PlayDate."
            )
        elif any(d in distro_id for d in ("fedora", "rhel", "centos")):
            cmd = "sudo dnf install python3-gobject webkit2gtk4.0"
            msg = (
                "PlayDate requires WebKit2GTK to display its interface.\n\n"
                f"Install it with:\n\n    {cmd}\n\nThen re-run PlayDate."
            )
        elif "arch" in distro_id:
            cmd = "sudo pacman -S python-gobject webkit2gtk"
            msg = (
                "PlayDate requires WebKit2GTK to display its interface.\n\n"
                f"Install it with:\n\n    {cmd}\n\nThen re-run PlayDate."
            )
        else:
            msg = (
                "PlayDate requires WebKit2GTK to display its interface.\n\n"
                "See README.md for your distribution's install command.\n\n"
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

import migration
from app import create_app, populate_cancel
from config import BASE_DIR
from database import init_db
from utils import (find_steam_path, start_steamapps_watcher, stop_steamapps_watcher,
                   sync_local_install_status)

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
                main_gtk_win = getattr(window, 'native', None)
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(ICON_PATH) if os.path.exists(ICON_PATH) else None
                for gtk_window in Gtk.Window.list_toplevels():
                    # Only touch the main window — skip WebKit offscreen windows,
                    # GtkTooltipWindows, etc.
                    if main_gtk_win is not None and gtk_window is not main_gtk_win:
                        continue
                    gtk_window.set_role('PlayDate')
                    if pixbuf:
                        gtk_window.set_icon(pixbuf)
            except Exception as e:
                log.warning(f"Icon patch failed: {e}")

        window.events.loaded += lambda: apply_icon()
        apply_icon()
    except Exception:
        pass

# ── Gamepad focus handler ─────────────────────────────────────────────────────
# Re-enables gamepad input the instant the OS gives PlayDate focus again after
# a game was running. Mirrors WPF's Application.Activated used by Playnite.
def _setup_focus_handler(webview_window):
    import platform as _platform
    _os = _platform.system()

    if _os == 'Linux':
        # GTK: connect to focus-in-event on the native window.
        # Fires immediately on alt-tab — no click required.
        try:
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk

            _connected = set()

            def _on_gtk_focus_in(gtk_win, event):
                # For Steam games the JS watcher handles unsuppression via pgrep.
                # focusInUnsuppress() is a no-op once pgrep has fired, so this
                # only takes effect for non-Steam games where pgrep never detects
                # anything and focus-in is the only reliable close signal.
                def _do():
                    try:
                        webview_window.evaluate_js(_UNSUPPRESS_GAMEPAD_JS)
                    except Exception:
                        pass
                threading.Thread(target=_do, daemon=True).start()
                return False  # don't consume the event

            def _connect_focus():
                for gtk_win in Gtk.Window.list_toplevels():
                    if id(gtk_win) not in _connected:
                        gtk_win.connect('focus-in-event', _on_gtk_focus_in)
                        _connected.add(id(gtk_win))

            webview_window.events.loaded += lambda: _connect_focus()
            _connect_focus()
        except Exception as e:
            log.warning(f"GTK focus handler setup failed: {e}")

    elif _os == 'Windows':
        # Win32: poll the foreground window every 500ms.
        # When PlayDate regains foreground, unsuppress gamepad.
        import ctypes
        import time as _time

        _user32 = ctypes.windll.user32

        def _get_window_title(hwnd):
            length = _user32.GetWindowTextLengthW(hwnd)
            if not length:
                return ''
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value

        def _focus_poll():
            was_foreground = True  # assume foreground at start
            while True:
                _time.sleep(0.5)
                try:
                    hwnd      = _user32.GetForegroundWindow()
                    title     = _get_window_title(hwnd)
                    is_pd     = 'PlayDate' in title
                    if is_pd and not was_foreground:
                        webview_window.evaluate_js(_UNSUPPRESS_GAMEPAD_JS)
                    was_foreground = is_pd
                except Exception:
                    pass

        t = threading.Thread(target=_focus_poll, daemon=True)
        t.start()


# ── Quit handler ──────────────────────────────────────────────────────────────
def _destroy_window():
    try:
        for w in webview.windows:
            w.destroy()
    except Exception as e:
        log.warning(f"Window destroy failed: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
# Module-level window reference so Flask routes can call pywebview APIs
_UNSUPPRESS_GAMEPAD_JS = (
    'if(window._inputMgr && window._inputMgr.focusInUnsuppress)'
    ' window._inputMgr.focusInUnsuppress();'
)

_webview_window = None
_fullscreen      = False  # tracked here so _on_closing can persist it reliably


class PyWebviewAPI:
    """JS-callable API exposed to the webview via js_api."""

    def resize_window(self, width, height):
        """Resize the pywebview window to the given dimensions."""
        if _webview_window is None:
            return
        try:
            _webview_window.resize(width, height)
        except Exception as e:
            log.warning(f"resize_window failed: {e}")

    def toggle_fullscreen(self):
        """Toggle native fullscreen on the pywebview window."""
        global _fullscreen
        if _webview_window is None:
            return
        try:
            _webview_window.toggle_fullscreen()
            _fullscreen = not _fullscreen
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

    def read_clipboard(self):
        """Read text from the system clipboard. Returns string or None."""
        import platform
        sys_name = platform.system()
        if sys_name == 'Linux':
            # Use GTK clipboard directly — works on both X11 and Wayland,
            # and is always available since pywebview already depends on GTK.
            try:
                from gi.repository import Gtk, Gdk
                clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                text = clipboard.wait_for_text()
                return text  # may be None if clipboard has no text
            except Exception as e:
                log.warning(f"read_clipboard (gtk) failed: {e}")
        elif sys_name == 'Darwin':
            try:
                import subprocess
                r = subprocess.run(['pbpaste'], capture_output=True, text=True, timeout=2)
                if r.returncode == 0:
                    return r.stdout
            except Exception as e:
                log.warning(f"read_clipboard (pbpaste) failed: {e}")
        elif sys_name == 'Windows':
            try:
                import subprocess
                r = subprocess.run(
                    ['powershell', '-noprofile', '-command', 'Get-Clipboard'],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    return r.stdout.rstrip('\r\n')
            except Exception as e:
                log.warning(f"read_clipboard (powershell) failed: {e}")
        return None

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
                webview.FileDialog.OPEN,
                file_types=tuple(file_types),
            )
            if paths:
                path = paths[0] if isinstance(paths, (list, tuple)) else paths
                return str(path)
        except Exception as e:
            log.warning(f"Open dialog failed: {e}")
        return None

    def pick_folder(self):
        """Open a native folder-picker dialog and return the chosen path, or None."""
        if _webview_window is None:
            return None
        try:
            paths = _webview_window.create_file_dialog(webview.FileDialog.FOLDER)
            if paths:
                path = paths[0] if isinstance(paths, (list, tuple)) else paths
                return str(path)
        except Exception as e:
            log.warning(f'Folder dialog failed: {e}')
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
                webview.FileDialog.SAVE,
                save_filename=suggested_name,
                file_types=tuple(file_types),
            )
            if paths:
                path = paths[0] if isinstance(paths, (list, tuple)) else paths
                return str(path)
        except Exception as e:
            log.warning(f"Save dialog failed: {e}")
        return None

    def open_auth_popup(self, url, redirect_pattern, code_js, callback_endpoint, cookie_name=None):
        """
        Open a popup window for OAuth login.
        Monitors navigation; when redirect_pattern appears in the URL, extracts the
        authorization code, POSTs it to callback_endpoint, then calls
        window._authPopupDone({status, username, message}) on the main window.
        Returns immediately -- result arrives via the _authPopupDone JS callback.

        Code extraction strategy (tried in order):
        1. URL query param 'code=' via _on_loaded -- works for GOG and standard
           OAuth redirects where the code appears in the redirect URL.
        2. On Linux/GTK: WebKit isolated-world evaluate_javascript via _on_loaded --
           reads document.body.innerText in an isolated JS world that bypasses CSP.
           Used for Epic's /id/api/redirect which blocks eval() via CSP but returns
           the authorizationCode as JSON in the response body.
        3. On Linux/GTK: WebKit decide-policy hook -- intercepts navigation
           before connection is attempted, only when code is in the URL.
           Handles redirects to unreachable hosts like https://localhost.
        """
        import threading
        import requests as _requests

        def _run():
            import json
            result   = {'status': 'error', 'message': 'Login window closed'}
            notified = threading.Event()

            def _notify_main():
                if notified.is_set():
                    return
                notified.set()
                if _webview_window is None:
                    return
                js = f'window._authPopupDone && window._authPopupDone({json.dumps(result)})'
                try:
                    _webview_window.evaluate_js(js)
                except Exception as e:
                    log.warning(f'open_auth_popup: notify main failed: {e}')

            def _exchange_and_close(code):
                if notified.is_set():
                    return
                if not code:
                    result.update({'status': 'error', 'message': 'Empty authorization code'})
                    try:
                        popup_ref[0].destroy()
                    except Exception:
                        pass
                    return
                try:
                    resp = _requests.post(
                        f'http://127.0.0.1:{PORT}{callback_endpoint}',
                        json={'code': code},
                        timeout=15,
                    )
                    data = resp.json()
                    if data.get('status') in ('success', 'connected'):
                        result.update({'status': 'success',
                                       'username': data.get('username', '')})
                    else:
                        result.update({'status': 'error',
                                       'message': data.get('message', 'Connection failed')})
                except Exception as e:
                    result.update({'status': 'error', 'message': f'Exchange failed: {e}'})
                try:
                    popup_ref[0].destroy()
                except Exception:
                    pass

            def _code_from_url(uri):
                from urllib.parse import urlparse, parse_qs
                return parse_qs(urlparse(uri).query).get('code', [''])[0]

            def _on_loaded():
                if notified.is_set():
                    return
                w = popup_ref[0]
                if w is None:
                    return
                try:
                    current = w.get_current_url() or ''
                except Exception:
                    return
                log.info(f'open_auth_popup: page loaded — {current!r}')
                # Match against scheme+host+path only, not query string.
                # Prevents false positives when redirect_pattern appears as an
                # encoded query parameter in the initial login URL.
                from urllib.parse import urlparse as _urlparse
                _p = _urlparse(current)
                base_url = _p.scheme + '://' + _p.netloc + _p.path
                if redirect_pattern not in base_url:
                    log.info(f'open_auth_popup: no match for pattern {redirect_pattern!r}, skipping')
                    return
                log.info(f'open_auth_popup: redirect_pattern matched, running code_js')
                # Strategy 1: code in URL query params (GOG and standard OAuth)
                code = _code_from_url(current)
                if code:
                    threading.Thread(target=_exchange_and_close, args=(code,),
                                     daemon=True).start()
                    return
                try:
                    from gi.repository import GLib, Gtk
                except ImportError:
                    log.warning('open_auth_popup: gi not available, cannot read body')
                    _exchange_and_close('')
                    return

                if cookie_name:
                    # Strategy 2a: native cookie manager — reads HttpOnly cookies
                    # that document.cookie cannot access.
                    def _gtk_read_cookie():
                        from urllib.parse import urlparse as _up
                        wk = None
                        for win in Gtk.Window.list_toplevels():
                            candidate = _find_webkit_in_widget(win)
                            if candidate is None:
                                continue
                            try:
                                uri = candidate.get_uri() or ''
                                pp = _up(uri)
                                base = pp.scheme + '://' + pp.netloc + pp.path
                                if redirect_pattern in base:
                                    wk = candidate
                                    break
                            except Exception:
                                pass
                        if wk is None:
                            log.warning('open_auth_popup: no WebKit view for cookie lookup')
                            return False
                        try:
                            cm2 = wk.get_website_data_manager().get_cookie_manager()
                            def _cookie_cb(mgr, result, *_):
                                try:
                                    cookies = mgr.get_cookies_finish(result)
                                    val = ''
                                    for c in (cookies or []):
                                        if c.get_name() == cookie_name:
                                            val = c.get_value()
                                            break
                                    log.info(f'open_auth_popup: native cookie {cookie_name!r} = {len(val)} chars')
                                    if val:
                                        threading.Thread(target=_exchange_and_close,
                                                         args=(val,), daemon=True).start()
                                    else:
                                        log.info('open_auth_popup: native cookie empty — keeping popup open')
                                except Exception as _e:
                                    log.warning(f'open_auth_popup: native cookie cb: {_e}')
                            cm2.get_cookies(current, None, _cookie_cb)
                        except Exception as _e:
                            log.warning(f'open_auth_popup: native cookie lookup failed: {_e}')
                        return False
                    GLib.idle_add(_gtk_read_cookie)
                    return

                # Strategy 2b: isolated-world evaluate_javascript (bypasses CSP).
                # pywebview's evaluate_js wraps in eval() which CSP blocks;
                # WebKit's isolated world runs directly in the engine.
                body_js = code_js or 'document.body.innerText'

                def _gtk_run_js():
                    from urllib.parse import urlparse as _up
                    wk = None
                    for win in Gtk.Window.list_toplevels():
                        candidate = _find_webkit_in_widget(win)
                        if candidate is None:
                            continue
                        try:
                            uri = candidate.get_uri() or ''
                            pp = _up(uri)
                            base = pp.scheme + '://' + pp.netloc + pp.path
                            if redirect_pattern in base:
                                wk = candidate
                                break
                        except Exception:
                            pass
                    if wk is None:
                        log.warning('open_auth_popup: no WebKit view found for isolated JS')
                        threading.Thread(target=_exchange_and_close, args=('',),
                                         daemon=True).start()
                        return False

                    def _cb(wkview, async_result, *_):
                        extracted = ''
                        try:
                            val = wkview.evaluate_javascript_finish(async_result)
                            raw = (val.to_string() if val else '') or ''
                            raw = raw.strip()
                            log.info(f'open_auth_popup: code_js raw result ({len(raw)} chars): {raw[:2000]!r}')
                            if raw.startswith('{'):
                                import json as _json
                                data = _json.loads(raw)
                                # If the JSON has our localStorage envelope {d,r}, pass
                                # it through as-is so the callback can parse it.
                                # Otherwise try to extract a bare OAuth code.
                                if 'd' in data or 'r' in data:
                                    extracted = raw
                                else:
                                    extracted = (data.get('authorizationCode')
                                                 or data.get('code') or '')
                            if not extracted:
                                extracted = raw
                        except Exception as e:
                            log.warning(f'open_auth_popup: isolated JS cb: {e}')
                        if extracted:
                            log.info(f'open_auth_popup: code_js extracted {len(extracted)}-char code')
                            threading.Thread(target=_exchange_and_close, args=(extracted,),
                                             daemon=True).start()
                        elif code_js:
                            # code_js was provided but returned empty — keep popup open so
                            # the user can interact with the page (e.g. generate a key) and
                            # the next navigation will trigger another extraction attempt.
                            log.info('open_auth_popup: code_js returned empty — keeping popup open for retry')
                        else:
                            threading.Thread(target=_exchange_and_close, args=('',),
                                             daemon=True).start()

                    # Custom code_js runs in the main world so it has access to
                    # localStorage, sessionStorage, and other page APIs.
                    # The isolated world ('PlayDateAuth') is only used for the
                    # default document.body.innerText fallback, which needs to
                    # bypass CSP on pages like Epic's /id/api/redirect.
                    world = None if code_js else 'PlayDateAuth'
                    try:
                        wk.evaluate_javascript(body_js, -1, world,
                                               None, None, _cb)
                    except Exception as e:
                        log.warning(f'open_auth_popup: evaluate_javascript: {e}')
                        threading.Thread(target=_exchange_and_close, args=('',),
                                         daemon=True).start()
                    return False

                # Delay code_js by 1.5s so async XHR calls (e.g. Ubisoft
                # sessions API on change_domain) complete before we read.
                GLib.timeout_add(1500, _gtk_run_js)

            def _on_closed():
                _notify_main()

            popup_ref = [None]
            try:
                # Open with about:blank so we can configure WebKit before the real
                # page loads. Sites like Ubisoft run a cookie/storage capability
                # check on first load and immediately redirect on failure -- faster
                # than our GTK setup timers would fire.
                popup = webview.create_window(
                    'Login',
                    'about:blank',
                    width=900,
                    height=680,
                    resizable=True,
                )
                popup_ref[0] = popup
                popup.events.loaded += _on_loaded
                popup.events.closed += _on_closed
            except Exception as e:
                result.update({'status': 'error', 'message': f'Could not open login window: {e}'})
                _notify_main()
                return

            # Configure the popup WebKit view (UA, cookie policy, anti-bot script)
            # before navigating to the real login URL.  All setup happens in one
            # GLib idle callback so everything is in place for the first page load.
            try:
                from gi.repository import GLib as _GLib, Gtk as _Gtk, WebKit2 as _WK2
                _ANTI_BOT_JS = """
(function() {
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'vendor', {get: () => 'Google Inc.'});
    Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    Object.defineProperty(navigator, 'cookieEnabled', {get: () => true});
    if (!window.chrome) {
        window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
    }
    // Remove WebKit2GTK-specific globals that fingerprint the embedded browser.
    try { Object.defineProperty(window, 'webkit', {get: () => undefined, configurable: true}); } catch(e) {}
    try { Object.defineProperty(window, 'WebKitPoint', {get: () => undefined, configurable: true}); } catch(e) {}
    try { Object.defineProperty(window, 'WebKitCSSMatrix', {get: () => undefined, configurable: true}); } catch(e) {}
    // Polyfill localStorage in case the WebKit context returns a broken implementation.
    (function() {
        var _ok = false;
        try { localStorage.setItem('__t__','1'); localStorage.removeItem('__t__'); _ok = true; } catch(e) {}
        if (_ok) return;
        var _s = {};
        var _ls = {
            setItem: function(k,v) { _s[k] = String(v); },
            getItem: function(k) { return Object.prototype.hasOwnProperty.call(_s,k) ? _s[k] : null; },
            removeItem: function(k) { delete _s[k]; },
            clear: function() { _s = {}; },
            get length() { return Object.keys(_s).length; },
            key: function(i) { return Object.keys(_s)[i] || null; }
        };
        try { Object.defineProperty(window, 'localStorage',   {get: () => _ls, configurable: true}); } catch(e) {}
        try { Object.defineProperty(window, 'sessionStorage', {get: () => _ls, configurable: true}); } catch(e) {}
    })();
    // Intercept XHR and fetch calls to Ubisoft's sessions API so we can capture
    // the ticket that the login page itself fetches, then store it in localStorage
    // for code_js to read after navigation to change_domain.
    (function() {
        var _NEEDLE = 'profiles/sessions';
        var _KEY    = '_pd_ubi_sess';
        function _store(text) {
            try { if (text) localStorage.setItem(_KEY, text); } catch(e) {}
        }
        var _oOpen = XMLHttpRequest.prototype.open;
        var _oSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.open = function(m, u) {
            this._pdu = (u || '').indexOf(_NEEDLE) !== -1;
            return _oOpen.apply(this, arguments);
        };
        XMLHttpRequest.prototype.send = function() {
            if (this._pdu) {
                var x = this;
                x.addEventListener('load', function() {
                    if (x.status >= 200 && x.status < 300) _store(x.responseText);
                });
            }
            return _oSend.apply(this, arguments);
        };
        var _oFetch = window.fetch;
        if (typeof _oFetch === 'function') {
            window.fetch = function(input, init) {
                var u = typeof input === 'string' ? input : (input && input.url) || '';
                var p = _oFetch.apply(this, arguments);
                if (u.indexOf(_NEEDLE) !== -1) {
                    p.then(function(r) {
                        if (r && r.ok) r.clone().text().then(_store).catch(function(){});
                    }).catch(function(){});
                }
                return p;
            };
        }
    })();
})();
"""
                _main_wk = _find_webkit_in_widget(
                    getattr(_webview_window, 'native', None)
                ) if _webview_window else None

                def _setup_and_navigate():
                    for _win in _Gtk.Window.list_toplevels():
                        _wk = _find_webkit_in_widget(_win)
                        if _wk is None or _wk is _main_wk:
                            continue
                        try:
                            _s = _wk.get_settings()
                            _s.set_user_agent(
                                'Mozilla/5.0 (X11; Linux x86_64) '
                                'AppleWebKit/537.36 (KHTML, like Gecko) '
                                'Chrome/124.0.0.0 Safari/537.36'
                            )
                        except Exception as _e:
                            log.warning(f'open_auth_popup: set UA failed: {_e}')
                        try:
                            mgr = _wk.get_user_content_manager()
                            script = _WK2.UserScript(
                                _ANTI_BOT_JS,
                                _WK2.UserContentInjectedFrames.ALL_FRAMES,
                                _WK2.UserScriptInjectionTime.START,
                                None, None,
                            )
                            mgr.add_script(script)
                            log.info('open_auth_popup: anti-bot script injected')
                        except Exception as _e:
                            log.warning(f'open_auth_popup: anti-bot inject failed: {_e}')
                        try:
                            cm = _wk.get_website_data_manager().get_cookie_manager()
                            cm.set_accept_policy(_WK2.CookieAcceptPolicy.ALWAYS)
                            log.info('open_auth_popup: cookie policy set to ALWAYS')
                        except Exception as _e:
                            log.warning(f'open_auth_popup: cookie policy failed: {_e}')
                        try:
                            def _on_load_changed(wkview, event, *_):
                                uri = wkview.get_uri() or ''
                                log.info(f'open_auth_popup: load-changed {event.value_name!r} — {uri!r}')
                            _wk.connect('load-changed', _on_load_changed)
                        except Exception as _e:
                            log.warning(f'open_auth_popup: load-changed hook failed: {_e}')
                        try:
                            _wk.load_uri(url)
                            log.info(f'open_auth_popup: navigating to {url!r}')
                        except Exception as _e:
                            log.warning(f'open_auth_popup: load_uri failed: {_e}')
                    return False

                _GLib.timeout_add(150, _setup_and_navigate)
            except ImportError:
                pass

            # Strategy 3 (Linux/GTK only): hook WebKit's decide-policy signal to
            # intercept navigation to unreachable hosts before the connection fails.
            _install_gtk_nav_interceptor(popup_ref, redirect_pattern,
                                         _code_from_url, _exchange_and_close)

        threading.Thread(target=_run, daemon=True).start()
        return {'status': 'started'}


def _find_webkit_in_widget(widget):
    """Recursively search a GTK widget tree for a WebKit2.WebView."""
    try:
        from gi.repository import WebKit2
        if isinstance(widget, WebKit2.WebView):
            return widget
        if hasattr(widget, 'get_children'):
            for child in widget.get_children():
                found = _find_webkit_in_widget(child)
                if found is not None:
                    return found
    except Exception:
        pass
    return None


def _install_gtk_nav_interceptor(popup_ref, redirect_pattern, code_from_url, exchange_and_close):
    """
    On Linux/GTK, connect WebKit's decide-policy signal to intercept navigation attempts
    before a connection is made -- including attempts to unreachable hosts like
    https://localhost used by Epic's auth flow.

    We connect to EVERY WebKit view we can find (main window + popup) so we don't
    miss the popup regardless of how pywebview structures its internals. The main
    window's view won't match redirect_pattern so the handler is a no-op there.
    We scan every 150ms for up to 3 seconds to catch the popup as it appears.
    """
    import sys
    if sys.platform != 'linux':
        return
    try:
        from gi.repository import GLib, WebKit2, Gtk
    except ImportError:
        return

    import threading
    connected_views = []   # list of (WebKit2.WebView, handler_id)
    done = threading.Event()

    def _on_decide_policy(view, decision, decision_type):
        if decision_type == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = (decision.get_navigation_action().get_request().get_uri() or '')
            if redirect_pattern in uri:
                code = code_from_url(uri)
                if code:
                    # Code is in the URL (e.g. redirect to unreachable localhost).
                    # Intercept before connection attempt.
                    done.set()
                    decision.ignore()
                    for v, hid in connected_views:
                        try:
                            v.disconnect(hid)
                        except Exception:
                            pass
                    threading.Thread(target=exchange_and_close, args=(code,), daemon=True).start()
                    return True
                # No code in URL — let the navigation proceed so the page loads
                # and _on_loaded can read the code from the response body.
        decision.use()
        return True

    def _attempt(remaining):
        if done.is_set():
            return False
        try:
            for win in Gtk.Window.list_toplevels():
                wk = _find_webkit_in_widget(win)
                if wk is None:
                    continue
                if any(v is wk for v, _ in connected_views):
                    continue
                hid = wk.connect('decide-policy', _on_decide_policy)
                connected_views.append((wk, hid))
                log.info(f'open_auth_popup: GTK interceptor connected ({win.get_title()!r})')
        except Exception as e:
            log.warning(f'open_auth_popup: GTK interceptor scan error: {e}')
        if not connected_views and remaining == 0:
            log.warning('open_auth_popup: GTK interceptor: no WebKit views found after all retries')
        if remaining > 0 and not done.is_set():
            GLib.timeout_add(150, _attempt, remaining - 1)
        return False

    GLib.timeout_add(150, _attempt, 20)


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

    if maximized or ws.get('x') is None:
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
    """Persist window state and fullscreen flag to state.json.
    No window property reads here — safe to call from the closing event."""
    from config import save_state
    try:
        save_state({'window_state': dict(tracked), 'fullscreen': _fullscreen})
        log.info(f"Window state saved: {tracked}, fullscreen={_fullscreen}")
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
        migration.run()
        init_db()
    except Exception as e:
        log.critical(f"Database initialization failed: {e}", exc_info=True)
        raise

    # 2b. Start filesystem watchers + sync install status on launch
    _steamapps_path = find_steam_path()
    if _steamapps_path:
        start_steamapps_watcher(_steamapps_path)
    else:
        log.warning("Steam path not found — steamapps watcher not started")

    import plugins
    for _p in plugins.loaded().values():
        _p.on_startup()

    def _run_install_sync():
        try:
            count = sync_local_install_status()
            log.info(f"Steam install status synced on startup: {count} games installed")
        except Exception as e:
            log.warning(f"Startup Steam install sync failed: {e}")

    threading.Thread(target=_run_install_sync, daemon=True).start()

    # 2c. Sync recent playtime from Steam API in background, then fetch any
    #     unfetched HLTB data and migrate store release dates silently in the same thread.
    def _run_playtime_sync():
        from scrapers import sync_recent_playtime, sync_hltb_unfetched, sync_store_release_dates
        sync_recent_playtime()
        sync_hltb_unfetched()
        sync_store_release_dates()

    threading.Thread(target=_run_playtime_sync, daemon=True).start()
    log.info("Playtime sync started in background.")

    # 2d. Snapshot MiaM achievement data for filter builder.
    def _run_miam_snapshot():
        try:
            from app import take_miam_snapshot
            take_miam_snapshot()
            log.info("MiaM achievement snapshot taken.")
        except Exception as e:
            log.warning(f"MiaM snapshot failed: {e}")

    threading.Thread(target=_run_miam_snapshot, daemon=True).start()

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
    _fullscreen = _ws.get('fullscreen', False)

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
        populate_cancel.set()   # stop any running populate before the process exits
        from scrapers import _store_date_migration_cancel
        _store_date_migration_cancel.set()
        _save_window_state(_tracked)

    window.events.maximized += _on_maximized
    window.events.restored  += _on_restored
    window.events.moved     += _on_moved
    window.events.resized   += _on_resized
    window.events.shown     += _on_shown
    window.events.closing   += _on_closing

    # 6. Linux icon fix + GTK focus handler
    _fix_window_icon(window)
    _setup_focus_handler(window)

    # 7. Start webview event loop
    log.info("Launching PlayDate window")
    webview.start(debug=False, storage_path=os.path.join(BASE_DIR, 'webview_storage'))

    # 8. Clean exit
    log.info("Window closed. PlayDate exiting.")
    stop_steamapps_watcher()
    for _p in plugins.loaded().values():
        _p.on_shutdown()
    os._exit(0)  # hard kill — sys.exit() waits for non-daemon threads (e.g. populate workers)
