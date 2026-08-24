"""Standalone eyedropper: takes a screenshot, shows a fullscreen tkinter overlay,
prints the picked hex color to stdout, or exits with code 1 on cancel/error."""
import os
import sys
import threading
import tkinter as tk
from PIL import Image, ImageTk, ImageGrab

DEAD_ZONE = 8000   # evdev axis dead zone (out of ±32767)
SPEED_MAX = 12     # pixels per tick at full stick deflection
TICK_MS   = 16     # ~60 fps gamepad poll interval


def _grab_via_portal():
    """Screen grab via the XDG Desktop Portal Screenshot API -- the only way
    to capture the screen under Wayland. ImageGrab.grab() calls XGetImage()
    on the X11 root window, which XWayland does not back with real
    composited screen content (confirmed on a real KDE Plasma Wayland
    session: X connects fine, but the grab itself fails with X error 8,
    BadMatch) -- granting more X11 access can't fix this, it's not a
    permissions problem. Requires PyGObject, already a hard dependency of
    this app's Linux renderer (main.py/gtk4webview.py)."""
    import time
    import gi
    gi.require_version('Gio', '2.0')
    gi.require_version('GLib', '2.0')
    from gi.repository import Gio, GLib
    from urllib.parse import unquote, urlparse

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    sender = bus.get_unique_name()[1:].replace('.', '_')
    token = f'playdate_shot_{int(time.time() * 1000)}'
    request_path = f'/org/freedesktop/portal/desktop/request/{sender}/{token}'

    loop = GLib.MainLoop()
    result = {}

    def on_response(_conn, _sender, _path, _iface, _signal, params, *_args):
        code, results = params.unpack()
        result['code'] = code
        result['results'] = results
        loop.quit()

    sub_id = bus.signal_subscribe(
        'org.freedesktop.portal.Desktop', 'org.freedesktop.portal.Request', 'Response',
        request_path, None, Gio.DBusSignalFlags.NONE, on_response,
    )
    try:
        bus.call_sync(
            'org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
            'org.freedesktop.portal.Screenshot', 'Screenshot',
            GLib.Variant('(sa{sv})', ('', {
                'handle_token': GLib.Variant('s', token),
                'interactive': GLib.Variant('b', False),
            })),
            None, Gio.DBusCallFlags.NONE, -1, None,
        )
        GLib.timeout_add_seconds(30, loop.quit)
        loop.run()
    finally:
        bus.signal_unsubscribe(sub_id)

    if result.get('code') != 0:
        raise RuntimeError('Screenshot portal request failed or was cancelled')
    uri = (result.get('results') or {}).get('uri')
    if not uri:
        raise RuntimeError('Screenshot portal returned no uri')

    path = unquote(urlparse(uri).path)
    img = Image.open(path)
    img.load()  # force full decode now -- the backing file may be temporary/portal-managed
    try:
        os.remove(path)
    except OSError:
        pass
    return img


def main():
    try:
        screenshot = ImageGrab.grab()
    except Exception:
        screenshot = _grab_via_portal()
    sw, sh = screenshot.size

    result  = [None]
    gp_pos  = [sw // 2, sh // 2]  # virtual cursor tracked by gamepad
    stick   = [0, 0]               # left-stick [x, y] raw evdev values

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.geometry(f'{sw}x{sh}+0+0')

    canvas = tk.Canvas(root, width=sw, height=sh, highlightthickness=0,
                       cursor='none', bg='black')
    canvas.pack()

    photo = ImageTk.PhotoImage(screenshot)
    canvas.create_image(0, 0, anchor='nw', image=photo)

    MAG_PIXELS = 15
    MAG_ZOOM   = 8
    MAG_SIZE   = MAG_PIXELS * MAG_ZOOM
    OFFSET     = 24
    state      = {'items': [], 'mag_photo': None}

    def _redraw(x, y):
        px = max(0, min(int(x), sw - 1))
        py = max(0, min(int(y), sh - 1))
        r, g, b = screenshot.getpixel((px, py))[:3]
        hex_color = f'#{r:02x}{g:02x}{b:02x}'

        half = MAG_PIXELS // 2
        x1 = max(0, px - half); y1 = max(0, py - half)
        x2 = min(sw, x1 + MAG_PIXELS); y2 = min(sh, y1 + MAG_PIXELS)
        region = screenshot.crop((x1, y1, x2, y2)).resize(
            (MAG_SIZE, MAG_SIZE), Image.NEAREST)

        mx = px + OFFSET
        my = py + OFFSET
        if mx + MAG_SIZE + 4 > sw:
            mx = px - MAG_SIZE - OFFSET
        if my + MAG_SIZE + 26 > sh:
            my = py - MAG_SIZE - OFFSET - 22

        for item in state['items']:
            canvas.delete(item)
        items = []

        mag_photo = ImageTk.PhotoImage(region)
        state['mag_photo'] = mag_photo

        items.append(canvas.create_rectangle(
            mx - 2, my - 2, mx + MAG_SIZE + 2, my + MAG_SIZE + 2,
            fill='black', outline='white', width=2))
        items.append(canvas.create_image(mx, my, anchor='nw', image=mag_photo))

        cx = mx + MAG_SIZE // 2
        cy = my + MAG_SIZE // 2
        items.append(canvas.create_line(cx, my, cx, my + MAG_SIZE, fill='white', width=1))
        items.append(canvas.create_line(mx, cy, mx + MAG_SIZE, cy, fill='white', width=1))

        lx = mx + MAG_SIZE // 2
        ly = my + MAG_SIZE + 4
        items.append(canvas.create_rectangle(
            mx - 2, ly - 2, mx + MAG_SIZE + 2, ly + 20,
            fill='black', outline=''))
        items.append(canvas.create_text(
            lx, ly + 8, text=hex_color,
            fill='white', font=('monospace', 12, 'bold')))

        CH = 10
        items.append(canvas.create_line(px - CH, py, px - 2, py, fill='white', width=1))
        items.append(canvas.create_line(px + 2, py, px + CH, py, fill='white', width=1))
        items.append(canvas.create_line(px, py - CH, px, py - 2, fill='white', width=1))
        items.append(canvas.create_line(px, py + 2, px, py + CH, fill='white', width=1))

        state['items'] = items

    def _pick(x, y):
        px = max(0, min(int(x), sw - 1))
        py = max(0, min(int(y), sh - 1))
        r, g, b = screenshot.getpixel((px, py))[:3]
        result[0] = f'#{r:02x}{g:02x}{b:02x}'
        root.quit()

    def _on_motion(event):
        gp_pos[0] = event.x
        gp_pos[1] = event.y
        _redraw(event.x, event.y)

    def _on_click(event):
        _pick(event.x, event.y)

    def _stick_delta(v):
        """Exponential speed curve: zero in dead zone, smooth acceleration to SPEED_MAX."""
        if abs(v) <= DEAD_ZONE:
            return 0.0
        ratio = (abs(v) - DEAD_ZONE) / (32767 - DEAD_ZONE)
        return (ratio ** 1.5) * SPEED_MAX * (1 if v > 0 else -1)

    def _gp_tick():
        dx = _stick_delta(stick[0])
        dy = _stick_delta(stick[1])
        if dx or dy:
            gp_pos[0] = max(0, min(sw - 1, gp_pos[0] + dx))
            gp_pos[1] = max(0, min(sh - 1, gp_pos[1] + dy))
            _redraw(gp_pos[0], gp_pos[1])
        root.after(TICK_MS, _gp_tick)

    # ── Event bindings ────────────────────────────────────────────────────
    canvas.bind('<Motion>',   _on_motion)
    canvas.bind('<Button-1>', _on_click)
    canvas.bind('<Button-3>', lambda _e: root.quit())   # right-click → cancel
    root.bind('<Escape>',     lambda _e: root.quit())

    # ── Gamepad thread (evdev) ────────────────────────────────────────────
    def _gp_thread():
        try:
            import evdev
            from evdev import ecodes
            candidates = [evdev.InputDevice(p) for p in evdev.list_devices()]
            # Prefer the first device that has BTN_SOUTH (Xbox A button)
            dev = next(
                (d for d in candidates
                 if ecodes.BTN_SOUTH in (d.capabilities().get(ecodes.EV_KEY) or [])),
                None,
            )
            if not dev:
                return
            for event in dev.read_loop():
                if event.type == ecodes.EV_ABS:
                    if event.code == ecodes.ABS_X:
                        stick[0] = event.value
                    elif event.code == ecodes.ABS_Y:
                        stick[1] = event.value
                elif event.type == ecodes.EV_KEY and event.value == 1:  # key-down only
                    if event.code == ecodes.BTN_SOUTH:    # A → pick
                        root.after(0, lambda: _pick(gp_pos[0], gp_pos[1]))
                    elif event.code == ecodes.BTN_EAST:   # B → cancel
                        root.after(0, root.quit)
        except Exception:
            pass

    threading.Thread(target=_gp_thread, daemon=True).start()
    root.after(TICK_MS, _gp_tick)

    root.focus_force()
    _redraw(gp_pos[0], gp_pos[1])  # initial crosshair at screen centre
    root.mainloop()
    root.destroy()

    if result[0]:
        print(result[0])
        sys.exit(0)
    sys.exit(1)


if __name__ == '__main__':
    main()
