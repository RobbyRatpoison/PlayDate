"""
Monkeypatches pywebview's stock GTK3/WebKit2GTK BrowserView with the same
gamescope focus watch gtk4webview.py has natively.

Needed because gtk4webview.py (WebKit 6.0/GTK4) is only swapped in as a
fallback when legacy WebKit2GTK 4.0/4.1 isn't found -- confirmed via
/proc/<pid>/maps on a real Steam Deck Flatpak install that WebKit2GTK 4.1
is what's actually loaded there, meaning gtk4webview.py's own fix (and
the GTK is-active handling before it) never executed on that hardware at
all. This patches the module pywebview actually uses in that case instead
of forking/duplicating its ~1000-line BrowserView implementation.

Mirrors gtk4webview.py's on_window_realize / _set_native_window_active /
on_window_active_changed, adapted for GTK3 API differences: Gdk.Window
instead of Gdk.Surface, GdkX11.X11Window instead of GdkX11.X11Surface.
"""
import logging

import gi
from gi.repository import GLib as glib

import gamescope_focus

logger = logging.getLogger('pywebview')

try:
    gi.require_version('GdkX11', '3.0')
    from gi.repository import GdkX11
    logger.info('gtk3webview_patch: GdkX11 typelib loaded')
except (ValueError, ImportError) as e:
    GdkX11 = None
    logger.info(f'gtk3webview_patch: GdkX11 typelib unavailable, gamescope focus watch disabled: {e}')


def install(gtk_module):
    """Patches gtk_module.BrowserView in place to add the focus watch."""
    BrowserView = gtk_module.BrowserView
    orig_init = BrowserView.__init__

    def _set_native_window_active(self, active):
        js = f'window._nativeWindowActive = {"true" if active else "false"};'
        try:
            self.webview.evaluate_javascript(js, len(js), None, None, None, None)
            logger.info(f'pushed window._nativeWindowActive = {active}')
        except Exception:
            logger.exception('Failed to push native window-active state to JS')

    def _on_window_active_changed(self, window, param):
        _set_native_window_active(self, bool(window.get_property('is-active')))

    def _on_gamescope_focus_change(self, focused):
        # Called from gamescope_focus's watcher thread, not the GTK main
        # thread -- must marshal back via idle_add before touching GTK/WebKit.
        glib.idle_add(_set_native_window_active, self, focused)

    def _on_window_realize(self, window):
        if GdkX11 is None:
            logger.info('gamescope focus watch: GdkX11 unavailable, not starting')
            return
        gdk_window = window.get_window()
        if not isinstance(gdk_window, GdkX11.X11Window):
            logger.info(f'gamescope focus watch: window is {type(gdk_window).__name__}, not X11Window, not starting')
            return
        xid = GdkX11.X11Window.get_xid(gdk_window)
        logger.info(f'gamescope focus watch: own XID is {xid}, starting watch')
        gamescope_focus.watch(xid, lambda focused: _on_gamescope_focus_change(self, focused))

    def patched_init(self, window):
        orig_init(self, window)
        self.window.connect('notify::is-active', lambda w, p: _on_window_active_changed(self, w, p))
        self.window.connect('realize', lambda w: _on_window_realize(self, w))

    BrowserView.__init__ = patched_init
    logger.info('gtk3webview_patch: installed on stock GTK3/WebKit2GTK BrowserView')
