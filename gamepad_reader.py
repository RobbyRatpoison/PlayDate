"""
gamepad_reader.py -- direct evdev gamepad reader for the Steam Deck.

Only used when PlayDate runs as a Steam shortcut on a Deck
(config._is_steam_deck_session()). There, WebKit's own gamepad support
(libmanette) is blocked from the built-in controller's hidraw node (see
flatpak/libnohidraw.c) so it can't fight Steam Input over lizard mode --
which means WebKit's Gamepad API sees nothing. Steam still exposes a
plain virtual XInput pad as an evdev device ("Microsoft X-Box 360 pad"),
and that one has no hidraw/lizard-mode entanglement at all. We read it
directly here and push a W3C-"standard"-shaped gamepad object into the
page as window._pdPad, which input.js consumes exactly like a real
navigator.getGamepads() entry.

No external deps: raw struct/fcntl/select on /dev/input/event*, same as
Steam/SDL do it. Handles the pad not existing yet and hot (re)plug by
re-scanning on any read error.
"""
import glob
import logging
import os
import select
import struct
import threading
import time

log = logging.getLogger('gamepad_reader')

# linux/input-event-codes.h
_EV_SYN, _EV_KEY, _EV_ABS = 0x00, 0x01, 0x03
_BTN_SOUTH = 0x130            # 304; presence of this = "it's a gamepad"

# evdev button code -> the button index input.js expects (its BTN_IDX:
# {a:0, b:1, y:2, x:3, lb:4, rb:5, back:8, start:9, up:12..right:15}).
_BTN_MAP = {
    0x130: 0,   # BTN_SOUTH   A
    0x131: 1,   # BTN_EAST    B
    0x133: 2,   # BTN_NORTH   Y  (top)
    0x134: 3,   # BTN_WEST    X  (left)
    0x136: 4,   # BTN_TL      LB
    0x137: 5,   # BTN_TR      RB
    0x13a: 8,   # BTN_SELECT  view/back
    0x13b: 9,   # BTN_START   menu/start
    0x13d: 10,  # BTN_THUMBL
    0x13e: 11,  # BTN_THUMBR
    0x13c: 16,  # BTN_MODE    guide
}
# some pads report the triggers as buttons too
_BTN_LT, _BTN_RT = 0x138, 0x139   # BTN_TL2 / BTN_TR2

# absolute-axis code -> (standard axis index or None, kind)
_ABS_X, _ABS_Y, _ABS_Z = 0x00, 0x01, 0x02
_ABS_RX, _ABS_RY, _ABS_RZ = 0x03, 0x04, 0x05
_ABS_HAT0X, _ABS_HAT0Y = 0x10, 0x11

_EVIOCGNAME_256 = (2 << 30) | (ord('E') << 8) | 0x06 | (256 << 16)
_STICK_MAX = 32767.0
_TRIG_MAX = 255.0
_TRIG_ON = 0.30
_POLL_HZ = 90


def _key_caps(fd):
    import fcntl
    buf = bytearray(96)
    try:
        fcntl.ioctl(fd, (2 << 30) | (ord('E') << 8) | (0x20 + _EV_KEY) | (96 << 16), buf)
    except OSError:
        return set()
    return {i for i in range(96 * 8) if buf[i // 8] >> (i % 8) & 1}


def find_gamepad():
    """Return (path, name) of the first evdev node that looks like a gamepad."""
    best = None
    for path in sorted(glob.glob('/dev/input/event*'),
                       key=lambda s: int(s.rsplit('event', 1)[1] or 0)):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            import fcntl
            nb = bytearray(256)
            try:
                fcntl.ioctl(fd, _EVIOCGNAME_256, nb)
                name = bytes(nb).split(b'\x00')[0].decode(errors='replace')
            except OSError:
                name = ''
            if _BTN_SOUTH in _key_caps(fd):
                # Prefer Steam's virtual pad if several match.
                if 'X-Box' in name or 'Xbox' in name or 'X-Box 360' in name:
                    return path, name
                if best is None:
                    best = (path, name)
        finally:
            os.close(fd)
    return best if best else (None, None)


class GamepadReader(threading.Thread):
    def __init__(self, on_state):
        super().__init__(daemon=True, name='gamepad-reader')
        self._on_state = on_state
        self._stop = threading.Event()
        self._btn = {}     # standard index -> bool
        self._abs = {}     # evdev abs code -> raw int
        self._trig = {_ABS_Z: 0, _ABS_RZ: 0}

    def stop(self):
        self._stop.set()

    def _emit(self):
        ax = self._abs
        buttons = [{'pressed': False, 'value': 0.0} for _ in range(17)]
        for idx, down in self._btn.items():
            if 0 <= idx < 17:
                buttons[idx] = {'pressed': bool(down), 'value': 1.0 if down else 0.0}
        lt = self._trig[_ABS_Z] / _TRIG_MAX
        rt = self._trig[_ABS_RZ] / _TRIG_MAX
        buttons[6] = {'pressed': lt > _TRIG_ON, 'value': round(lt, 3)}
        buttons[7] = {'pressed': rt > _TRIG_ON, 'value': round(rt, 3)}
        hx, hy = ax.get(_ABS_HAT0X, 0), ax.get(_ABS_HAT0Y, 0)
        for i, on in ((12, hy < 0), (13, hy > 0), (14, hx < 0), (15, hx > 0)):
            buttons[i] = {'pressed': bool(on), 'value': 1.0 if on else 0.0}
        axes = [
            round(ax.get(_ABS_X, 0) / _STICK_MAX, 3),
            round(ax.get(_ABS_Y, 0) / _STICK_MAX, 3),
            round(ax.get(_ABS_RX, 0) / _STICK_MAX, 3),
            round(ax.get(_ABS_RY, 0) / _STICK_MAX, 3),
        ]
        self._on_state({
            'id': 'Steam Deck (evdev event10)',
            'mapping': 'standard',
            'connected': True,
            'buttons': buttons,
            'axes': axes,
            'timestamp': round(time.time() * 1000),
        })

    def run(self):
        fmt = 'llHHi'
        sz = struct.calcsize(fmt)
        while not self._stop.is_set():
            path, name = find_gamepad()
            if not path:
                if self._btn or self._abs:
                    self._btn.clear(); self._abs.clear()
                    self._trig = {_ABS_Z: 0, _ABS_RZ: 0}
                    try:
                        self._on_state({'connected': False})
                    except Exception:
                        pass
                self._stop.wait(2.0)
                continue
            log.info('gamepad reader: using %s (%s)', path, name)
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                self._stop.wait(2.0)
                continue
            last_emit = 0.0
            dirty = False
            try:
                while not self._stop.is_set():
                    r, _, _ = select.select([fd], [], [], 0.2)
                    if r:
                        try:
                            data = os.read(fd, sz * 64)
                        except OSError:
                            break  # device went away -> re-scan
                        for i in range(0, len(data) - sz + 1, sz):
                            _s, _us, typ, code, val = struct.unpack(fmt, data[i:i+sz])
                            if typ == _EV_KEY:
                                if code in _BTN_MAP:
                                    self._btn[_BTN_MAP[code]] = val != 0
                                    dirty = True
                                elif code == _BTN_LT:
                                    self._trig[_ABS_Z] = 255 if val else 0; dirty = True
                                elif code == _BTN_RT:
                                    self._trig[_ABS_RZ] = 255 if val else 0; dirty = True
                            elif typ == _EV_ABS:
                                if code in (_ABS_Z, _ABS_RZ):
                                    self._trig[code] = val; dirty = True
                                elif code in (_ABS_X, _ABS_Y, _ABS_RX, _ABS_RY,
                                              _ABS_HAT0X, _ABS_HAT0Y):
                                    self._abs[code] = val; dirty = True
                    now = time.time()
                    if dirty and now - last_emit >= 1.0 / _POLL_HZ:
                        try:
                            self._emit()
                        except Exception:
                            log.exception('gamepad reader: emit failed')
                        last_emit = now
                        dirty = False
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
