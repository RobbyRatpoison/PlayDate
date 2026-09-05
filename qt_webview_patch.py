"""Monkeypatches pywebview's stock QWebEngineView-based BrowserView with a
scaled-up mouse wheel delta.

QtWebEngine/Chromium's default per-notch scroll amount feels noticeably
slower than WebKitGTK's on the same page -- confirmed live comparing the
GTK and Qt renderers on PlayDate's own library grid. No Chromium flag or
QWebEngineSettings controls this. Mirrors gtk3webview_patch.py's approach:
patch pywebview's real platform module in place rather than forking/
duplicating its BrowserView implementation.

First attempt (overriding WebView.wheelEvent() directly) had zero effect
at any multiplier, confirmed live up to 50x -- overriding QWebEngineView's
own wheelEvent() doesn't intercept real scroll input at all. QtWebEngine's
actual Chromium rendering surface is a separate native child widget
(RenderWidgetHostViewQt) that receives wheel/mouse/keyboard events
directly; Qt's normal event propagation to the parent QWidget's own
virtual methods never enters into it. Confirmed independently by multiple
real QtWebEngine-based projects hitting the exact same thing (Qt Forum
reports, qutebrowser). The real fix, matching QupZilla's own
webview.cpp (their comment literally calls it "Hack to find widget that
receives input events"): install an event filter on view.focusProxy() --
but focusProxy() isn't valid immediately at construction; it only becomes
the real render widget once QWebEngineView's internal QStackedLayout
swaps it in, asynchronously, once Chromium's compositor is ready.
"""
import logging

logger = logging.getLogger('pywebview')

# Multiplier applied to the wheel event's delta before Chromium processes
# it. Confirm this actually has an effect now before fine-tuning the value
# -- the previous approach (patching wheelEvent directly) silently did
# nothing at all, up to 50x.
_WHEEL_SCROLL_MULTIPLIER = 5


def install(qt_module):
    """Patches qt_module.BrowserView.WebView.__init__ to attach a wheel
    event filter to the view's focus proxy once it's actually available."""
    try:
        from qtpy.QtCore import QEvent, QObject, QTimer
        from qtpy.QtGui import QWheelEvent
        from qtpy.QtWidgets import QApplication, QStackedLayout
    except Exception:
        logger.warning('qt_webview_patch: required Qt classes unavailable, wheel-scroll multiplier disabled')
        return

    class _WheelFilter(QObject):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._reinjecting = False

        def eventFilter(self, obj, event):
            if event.type() != QEvent.Type.Wheel:
                return False
            if self._reinjecting:
                # QApplication.sendEvent() below re-enters Qt's normal event
                # delivery for `obj`, which passes back through this same
                # filter (it's installed on obj) -- without this guard, the
                # scaled event gets scaled again, and again, compounding
                # exponentially into an enormous delta from a single wheel
                # click. Confirmed live: 5x alone scrolled through thousands
                # of cards.
                return False
            try:
                scaled = QWheelEvent(
                    event.position(),
                    event.globalPosition(),
                    event.pixelDelta() * _WHEEL_SCROLL_MULTIPLIER,
                    event.angleDelta() * _WHEEL_SCROLL_MULTIPLIER,
                    event.buttons(),
                    event.modifiers(),
                    event.phase(),
                    event.inverted(),
                )
            except Exception:
                logger.exception('qt_webview_patch: failed to scale wheel event, passing through unmodified')
                return False
            self._reinjecting = True
            try:
                QApplication.sendEvent(obj, scaled)
            finally:
                self._reinjecting = False
            return True  # consume the original, unscaled event

    WebView = qt_module.BrowserView.WebView
    orig_init = WebView.__init__

    def patched_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        # Parented to self so its lifetime is tied to the view -- also keeps
        # a live Python reference so it isn't garbage-collected out from
        # under the C++-side event filter registration.
        self._pd_wheel_filter = _WheelFilter(self)

        # Confirmed live (this Qt/PyQt6 version): WebView.layout() is a plain
        # QVBoxLayout, not the QStackedLayout QupZilla's (older) code keyed
        # off of -- so there's no signal to wait for here. Poll instead,
        # since focusProxy() is reliably None immediately after construction
        # and only becomes the real render widget once Chromium's compositor
        # is ready, on an unpredictable timeline. Keeps retrying (bounded)
        # rather than a couple of fixed-delay guesses that could miss a slow
        # first load.
        state = {'attempts': 0, 'attached': False}
        MAX_ATTEMPTS = 40  # ~10s at 250ms apart

        def _attach():
            if state['attached']:
                return  # e.g. both the QStackedLayout signal and the poll below fired
            proxy = self.focusProxy()
            if proxy:
                proxy.installEventFilter(self._pd_wheel_filter)
                state['attached'] = True
                logger.info(f"qt_webview_patch: wheel filter attached to focus proxy after {state['attempts']} attempt(s)")
                return
            state['attempts'] += 1
            if state['attempts'] >= MAX_ATTEMPTS:
                logger.warning('qt_webview_patch: focus proxy never became available, wheel-scroll multiplier not applied')
                return
            QTimer.singleShot(250, _attach)

        layout = self.layout()
        if isinstance(layout, QStackedLayout):
            # If some Qt version *does* expose this, use it as a faster
            # first signal -- still falls through to the same polling
            # _attach() if focusProxy() isn't valid the instant it fires.
            layout.currentChanged.connect(lambda _i: _attach())
        QTimer.singleShot(0, _attach)

    WebView.__init__ = patched_init
    logger.info(f'qt_webview_patch: installed wheel-scroll multiplier x{_WHEEL_SCROLL_MULTIPLIER}')
