"""
Watches gamescope's GAMESCOPE_FOCUSED_WINDOW X11 root-window property to
detect when Steam's own UI (home screen, quick-access overlay, install-
confirm popups) takes focus over PlayDate under SteamOS/gamescope.

Confirmed on real Steam Deck hardware that neither WebKit's own
document.hasFocus()/hidden nor GTK's is-active property reliably reflect
this -- gamepad input kept driving PlayDate's UI while the Deck's own
home screen was frontmost. gamescope tracks real compositor-level focus
separately via X11 atoms on its embedded Xwayland root window (the same
mechanism Proton itself uses to decide whether to drop input), set via
XChangeProperty whenever its internal focus target changes and watchable
via a standard PropertyNotify event -- no polling needed.

No-ops entirely outside gamescope: XInternAtom with only_if_exists=True
returns 0 when the atom was never created, which is the case for any
ordinary X11/Xwayland session that isn't gamescope.
"""
import ctypes
import ctypes.util
import logging
import threading

logger = logging.getLogger('gamescope_focus')

_PROPERTY_CHANGE_MASK = 1 << 22
_PROPERTY_NOTIFY = 19
_XA_CARDINAL = 6


class _XPropertyEvent(ctypes.Structure):
    _fields_ = [
        ('type', ctypes.c_int),
        ('serial', ctypes.c_ulong),
        ('send_event', ctypes.c_int),
        ('display', ctypes.c_void_p),
        ('window', ctypes.c_ulong),
        ('atom', ctypes.c_ulong),
        ('time', ctypes.c_ulong),
        ('state', ctypes.c_int),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [
        ('type', ctypes.c_int),
        ('xproperty', _XPropertyEvent),
        ('pad', ctypes.c_long * 24),
    ]


def _load_xlib():
    path = ctypes.util.find_library('X11') or 'libX11.so.6'
    x11 = ctypes.CDLL(path)
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
    x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(_XEvent)]
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
    Spawns a daemon thread that watches gamescope's GAMESCOPE_FOCUSED_WINDOW
    root property and calls on_focus_change(bool) once with the current
    state, then again on every change, comparing against own_xid. Silently
    does nothing if libX11 is unavailable, no display can be opened, or the
    atom doesn't exist (i.e. not running under gamescope).
    """
    def _run():
        try:
            x11 = _load_xlib()
        except OSError:
            logger.debug('gamescope focus watch: libX11 unavailable, skipping')
            return

        display = x11.XOpenDisplay(None)
        if not display:
            logger.debug('gamescope focus watch: could not open X display, skipping')
            return

        try:
            root = x11.XDefaultRootWindow(display)
            focused_window_atom = x11.XInternAtom(display, b'GAMESCOPE_FOCUSED_WINDOW', True)
            if not focused_window_atom:
                logger.debug('gamescope focus watch: GAMESCOPE_FOCUSED_WINDOW absent, not gamescope, skipping')
                return

            current = _read_cardinal(x11, display, root, focused_window_atom)
            if current is not None:
                on_focus_change(current == own_xid)

            x11.XSelectInput(display, root, _PROPERTY_CHANGE_MASK)
            event = _XEvent()
            while True:
                x11.XNextEvent(display, ctypes.byref(event))
                if event.type != _PROPERTY_NOTIFY or event.xproperty.atom != focused_window_atom:
                    continue
                value = _read_cardinal(x11, display, root, focused_window_atom)
                if value is not None:
                    on_focus_change(value == own_xid)
        except Exception:
            logger.exception('gamescope focus watch: error, stopping')
        finally:
            x11.XCloseDisplay(display)

    threading.Thread(target=_run, daemon=True, name='gamescope-focus-watch').start()
