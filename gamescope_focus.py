"""
Watches gamescope's GAMESCOPE_FOCUSED_WINDOW X11 root-window property to
detect when Steam's own UI (home screen, quick-access overlay, install-
confirm popups) takes focus over PlayDate under SteamOS/gamescope.

Confirmed on real Steam Deck hardware that neither WebKit's own
document.hasFocus()/hidden nor GTK's is-active property reliably reflect
this -- gamepad input kept driving PlayDate's UI while the Deck's own
home screen was frontmost. gamescope tracks real compositor-level focus
separately via X11 atoms on its embedded Xwayland root window, set via
XChangeProperty whenever its internal focus target changes -- the same
mechanism Proton itself uses to decide whether to drop input.

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

No-ops entirely outside gamescope: XInternAtom with only_if_exists=True
returns 0 when the atom was never created, which is the case for any
ordinary X11/Xwayland session that isn't gamescope.
"""
import ctypes
import ctypes.util
import logging

from gi.repository import GLib

logger = logging.getLogger('gamescope_focus')

_XA_CARDINAL = 6
_POLL_INTERVAL_MS = 100


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


def watch(own_xid, on_focus_change):
    """
    Polls gamescope's GAMESCOPE_FOCUSED_WINDOW root property every 100ms on
    the main GLib loop and calls on_focus_change(bool) once with the
    current state, then again on every change, comparing against own_xid.
    Must be called from the main thread. Silently does nothing if libX11 is
    unavailable, no display can be opened, or the atom doesn't exist (i.e.
    not running under gamescope).
    """
    try:
        x11 = _load_xlib()
    except OSError as e:
        logger.info(f'gamescope focus watch: libX11 unavailable, skipping ({e})')
        return

    display = x11.XOpenDisplay(None)
    if not display:
        logger.info('gamescope focus watch: could not open X display, skipping')
        return

    root = x11.XDefaultRootWindow(display)
    focused_window_atom = x11.XInternAtom(display, b'GAMESCOPE_FOCUSED_WINDOW', True)
    if not focused_window_atom:
        logger.info('gamescope focus watch: GAMESCOPE_FOCUSED_WINDOW absent, not gamescope, skipping')
        x11.XCloseDisplay(display)
        return

    state = {'last': _read_cardinal(x11, display, root, focused_window_atom)}
    logger.info(f'gamescope focus watch: started (main-loop polling), '
                f'own_xid={own_xid} initial focused_window={state["last"]}')
    if state['last'] is not None:
        on_focus_change(state['last'] == own_xid)

    def _poll():
        try:
            value = _read_cardinal(x11, display, root, focused_window_atom)
        except Exception:
            logger.exception('gamescope focus watch: error, stopping')
            x11.XCloseDisplay(display)
            return False
        if value is not None and value != state['last']:
            logger.info(f'gamescope focus watch: focused_window changed to {value} (own_xid={own_xid})')
            state['last'] = value
            on_focus_change(value == own_xid)
        return True

    GLib.timeout_add(_POLL_INTERVAL_MS, _poll)
