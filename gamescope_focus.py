"""
Watches gamescope's focus atoms on its Xwayland root window to detect when
Steam's own UI (home screen, quick-access overlay, install-confirm popups)
or another game takes focus over PlayDate under SteamOS/gamescope.

Confirmed on real Steam Deck hardware that neither WebKit's own
document.hasFocus()/hidden nor GTK's is-active property reliably reflect
this -- gamepad input kept driving PlayDate's UI while the Deck's own
home screen was frontmost. gamescope tracks real compositor-level focus
separately via X11 atoms on its embedded Xwayland root window, set via
XChangeProperty whenever its internal focus target changes -- the same
mechanism Proton itself uses to decide whether to drop input.

Two things that a naive implementation gets wrong, both found on hardware
(2026-09-03), both fixed here:

1. Wrong display. SteamOS Game Mode now runs one Xwayland server per app
   (STEAM_MULTIPLE_XWAYLANDS=1), so XOpenDisplay(None) -- i.e. $DISPLAY --
   opens PlayDate's *own* server (":1"), where the focus atoms are never
   set. gamescope only writes them to its primary server (":0"). So we
   probe ":0".. and pick whichever display actually has the atom set.

2. Wrong atom. GAMESCOPE_FOCUSED_WINDOW only changes when a *different
   toplevel window* takes over -- e.g. the full Deck home screen. It does
   NOT move for the Steam-button quick-access overlay, which is the common
   case: that leaves FOCUSED_WINDOW pointing at PlayDate while the overlay
   eats input. GAMESCOPE_FOCUSED_APP flips (to 769 = Steam UI, or to
   another game's AppID) for *both* cases, so we prefer it. Our own AppID
   comes from $SteamAppId (set by Steam for every launched title,
   Game-Mode only); FOCUSED_APP == that means PlayDate is frontmost.
   Falls back to GAMESCOPE_FOCUSED_WINDOW vs own_xid when FOCUSED_APP is
   unavailable (non-Steam-mode gamescope) or $SteamAppId is unset.

Polls on the main GLib loop via GLib.timeout_add rather than a background
thread. Two earlier background-thread versions (one XNextEvent/
PropertyNotify-based, one a plain time.sleep() poll) both worked for their
very first read, then silently never saw another change again -- despite
`xprop -root -spy` on the same X server, at the same moment, clearly
seeing the atom keep changing. That "works once, then nothing" signature
matches Xlib's documented lack of thread-safety without XInitThreads(),
which can't reliably be arranged here: GDK/WebKit already make Xlib calls
on the main thread well before this module's watch() is ever called (it's
wired up from a 'realize' handler, by which point GDK's own X11 connection
already exists), and XInitThreads() must be the first Xlib call in the
whole process to be effective. Running everything on the same thread GDK
already uses sidesteps the problem entirely instead of working around it.

No-ops entirely outside gamescope: none of the GAMESCOPE_* atoms exist on
an ordinary X11/Xwayland session, so the display probe finds nothing and
watch() returns without scheduling anything.
"""
import ctypes
import ctypes.util
import logging
import os

from gi.repository import GLib

logger = logging.getLogger('gamescope_focus')

_XA_CARDINAL = 6
_POLL_INTERVAL_MS = 100
# gamescope's primary Xwayland is :0; per-app servers start at :1. Probe a
# small range rather than trusting $DISPLAY (which is our own per-app one).
_DISPLAY_CANDIDATES = [f':{n}' for n in range(0, 5)]


def _load_xlib():
    path = ctypes.util.find_library('X11') or 'libX11.so.6'
    x11 = ctypes.CDLL(path)
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XGetWindowProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long,
        ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
    ]
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return x11


def _read_cardinal(x11, display, window, atom):
    """Reads a single CARDINAL(32) property value, or None if unset."""
    if not atom:
        return None
    actual_type = ctypes.c_ulong()
    actual_format = ctypes.c_int()
    nitems = ctypes.c_ulong()
    bytes_after = ctypes.c_ulong()
    prop = ctypes.POINTER(ctypes.c_ubyte)()
    x11.XGetWindowProperty(
        display, window, atom, 0, 1, False, _XA_CARDINAL,
        ctypes.byref(actual_type), ctypes.byref(actual_format),
        ctypes.byref(nitems), ctypes.byref(bytes_after), ctypes.byref(prop),
    )
    if not prop or nitems.value < 1:
        return None
    try:
        # format=32 properties are delivered as native `long` slots (8 bytes
        # on 64-bit), each holding a 32-bit value in the low bits.
        return ctypes.cast(prop, ctypes.POINTER(ctypes.c_ulong))[0] & 0xFFFFFFFF
    finally:
        x11.XFree(prop)


def _find_gamescope_display(x11):
    """
    Probes the candidate X displays for gamescope's focus atoms and returns
    (display_ptr, root, app_atom, window_atom, prefer_app) for the first one
    that actually has a value set, or None if none do (not gamescope).

    prefer_app is True when GAMESCOPE_FOCUSED_APP carries a usable value --
    the signal that also catches the quick-access overlay.
    """
    for name in _DISPLAY_CANDIDATES:
        display = x11.XOpenDisplay(name.encode())
        if not display:
            continue
        root = x11.XDefaultRootWindow(display)
        app_atom = x11.XInternAtom(display, b'GAMESCOPE_FOCUSED_APP', True)
        window_atom = x11.XInternAtom(display, b'GAMESCOPE_FOCUSED_WINDOW', True)
        app_val = _read_cardinal(x11, display, root, app_atom)
        window_val = _read_cardinal(x11, display, root, window_atom)
        if app_val is not None or window_val is not None:
            logger.info(f'gamescope focus watch: using display {name} '
                        f'(FOCUSED_APP={app_val} FOCUSED_WINDOW={window_val})')
            return display, root, app_atom, window_atom, app_val is not None
        x11.XCloseDisplay(display)
    return None


def watch(own_xid, on_focus_change):
    """
    Polls gamescope's focus atoms every 100ms on the main GLib loop and
    calls on_focus_change(bool) once with the current state, then again on
    every change. Must be called from the main thread. Silently does
    nothing if libX11 is unavailable or no gamescope display is found.
    """
    logger.info(f'gamescope focus watch: entering watch(), own_xid={own_xid} '
                f'SteamAppId={os.environ.get("SteamAppId")}')
    try:
        x11 = _load_xlib()
    except Exception as e:
        logger.info(f'gamescope focus watch: libX11 unavailable, skipping ({e})')
        return

    found = _find_gamescope_display(x11)
    if found is None:
        logger.info('gamescope focus watch: no GAMESCOPE_FOCUSED_* atom on any display, not gamescope, skipping')
        return
    display, root, app_atom, window_atom, prefer_app = found

    own_app = None
    if prefer_app:
        try:
            own_app = int(os.environ['SteamAppId'])
        except (KeyError, ValueError):
            # No $SteamAppId: snapshot whatever's focused now (we launch focused).
            own_app = _read_cardinal(x11, display, root, app_atom)
        logger.info(f'gamescope focus watch: tracking GAMESCOPE_FOCUSED_APP, own_app={own_app}')
    else:
        logger.info(f'gamescope focus watch: tracking GAMESCOPE_FOCUSED_WINDOW, own_xid={own_xid}')

    def _is_focused():
        if prefer_app and own_app is not None:
            return _read_cardinal(x11, display, root, app_atom) == own_app
        return _read_cardinal(x11, display, root, window_atom) == own_xid

    state = {'focused': _is_focused()}
    logger.info(f'gamescope focus watch: started (main-loop polling), initial focused={state["focused"]}')
    on_focus_change(state['focused'])

    def _poll():
        try:
            focused = _is_focused()
        except Exception:
            logger.exception('gamescope focus watch: error, stopping')
            x11.XCloseDisplay(display)
            return False
        if focused != state['focused']:
            logger.info(f'gamescope focus watch: focused -> {focused}')
            state['focused'] = focused
            on_focus_change(focused)
        return True

    GLib.timeout_add(_POLL_INTERVAL_MS, _poll)
