"""Monkeypatches pywebview's stock QWebEngineView-based BrowserView with a
scaled-up mouse wheel delta.

QtWebEngine/Chromium's default per-notch scroll amount feels noticeably
slower than WebKitGTK's on the same page -- confirmed live comparing the
GTK and Qt renderers on PlayDate's own library grid. No Chromium flag or
QWebEngineSettings controls this; the fix has to happen at the Qt widget
level, on the actual QWheelEvent, before it reaches Chromium. Mirrors
gtk3webview_patch.py's approach: patch pywebview's real platform module in
place rather than forking/duplicating its BrowserView implementation.
"""
import logging

logger = logging.getLogger('pywebview')

# Multiplier applied to the wheel event's delta before Chromium processes
# it. 3x still felt slower than WebKitGTK on live testing -- adjust further
# if needed.
_WHEEL_SCROLL_MULTIPLIER = 5


def install(qt_module):
    """Patches qt_module.BrowserView.WebView.wheelEvent in place."""
    try:
        from qtpy.QtGui import QWheelEvent
    except Exception:
        logger.warning('qt_webview_patch: QWheelEvent unavailable, wheel-scroll multiplier disabled')
        return

    WebView = qt_module.BrowserView.WebView
    orig_wheel_event = WebView.wheelEvent

    def patched_wheel_event(self, event):
        try:
            # source/device aren't readable back off a real QWheelEvent
            # instance at runtime despite appearing as constructor params
            # in the stubs -- both default sanely, so just omit them.
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
            return orig_wheel_event(self, event)
        return orig_wheel_event(self, scaled)

    WebView.wheelEvent = patched_wheel_event
    logger.info(f'qt_webview_patch: installed wheel-scroll multiplier x{_WHEEL_SCROLL_MULTIPLIER}')
