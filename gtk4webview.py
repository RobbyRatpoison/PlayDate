"""
GTK4 / WebKit 6.0 renderer for pywebview.

Injected into sys.modules['webview.platforms.gtk'] at startup when
WebKit2GTK (4.0/4.1) is unavailable but WebKit 6.0 (GTK4) is present.
API surface mirrors webview/platforms/gtk.py so pywebview's guilib works
without modification.
"""
import json
import logging
import os
import pathlib
import sys
import webbrowser
from threading import Semaphore, Thread, main_thread
from typing import Any
from uuid import uuid1

from webview import FileDialog, _state, settings, windows
from webview.menu import Menu, MenuAction, MenuSeparator
from webview.models import Request, Response
from webview.screen import Screen
from webview.util import (
    DEFAULT_HTML,
    create_cookie,
    inject_pywebview,
    js_bridge_call,
    parse_file_type,
)
from webview.window import Window

logger = logging.getLogger('pywebview')
os.environ['EGL_LOG_LEVEL'] = 'fatal'

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('WebKit', '6.0')
gi.require_version('Soup', '3.0')

from gi.repository import Gdk, Gio
from gi.repository import GLib as glib
from gi.repository import Gtk as gtk
from gi.repository import WebKit as webkit

renderer = 'gtkwebkit2'
webkit_ver = webkit.get_major_version(), webkit.get_minor_version(), webkit.get_micro_version()

_app = None
_app_actions = {}


class BrowserView:
    instances = {}

    class JSBridge:
        def __init__(self, window: Window) -> None:
            self.window = window
            self.uid = uuid1().hex[:8]

        def call(self, func_name: str, param: Any, value_id: str):
            if param == 'undefined':
                param = None
            return js_bridge_call(self.window, func_name, param, value_id)

    def __init__(self, window: Window) -> None:
        global _app

        BrowserView.instances[window.uid] = self
        self.uid = window.uid
        self.pywebview_window = window

        self.is_fullscreen = False
        self.js_results = {}

        self.window = gtk.ApplicationWindow(application=_app)
        self.window.set_title(window.title)
        self.pywebview_window.native = self.window

        self.shown = window.events.shown
        self.loaded = window.events.loaded
        self.localization = window.localization

        self._last_width = window.initial_width
        self._last_height = window.initial_height

        if window.screen:
            self.screen = window.screen.frame
        else:
            display = Gdk.Display.get_default()
            monitors = display.get_monitors()
            monitor = monitors.get_item(0)
            self.screen = monitor.get_geometry() if monitor else None

        self.window.set_default_size(window.initial_width, window.initial_height)
        if not window.resizable:
            self.window.set_resizable(False)
        else:
            self.window.set_size_request(window.min_size[0], window.min_size[1])

        if window.maximized:
            self.window.maximize()

        # GTK4 doesn't support programmatic positioning — initial_x/y are ignored

        self.window.set_resizable(window.resizable)

        style_provider = gtk.CssProvider()
        style_provider.load_from_string(
            f'window {{ background-color: {window.background_color}; }}'
        )
        gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), style_provider, gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        if window.menu:
            logger.warning('Window specific menu is not supported on GTK4')

        scrolled_window = gtk.ScrolledWindow()
        scrolled_window.set_policy(gtk.PolicyType.NEVER, gtk.PolicyType.NEVER)
        self.window.set_child(scrolled_window)

        self.window.connect('close-request', self.close_window)
        self.window.connect('notify::maximized', self.on_window_maximized)
        self.window.connect('notify::default-width', self.on_window_resize_prop)
        self.window.connect('notify::default-height', self.on_window_resize_prop)

        self.js_bridge = BrowserView.JSBridge(window)

        # WebKit 6.0 uses NetworkSession for cookie/storage management
        if _state['private_mode']:
            self._network_session = webkit.NetworkSession.new_ephemeral()
        elif _state['storage_path']:
            storage_path = _state['storage_path']
            if not os.path.exists(storage_path):
                os.makedirs(storage_path)
            data_manager = webkit.WebsiteDataManager(
                base_data_directory=storage_path,
                base_cache_directory=os.path.join(storage_path, 'cache'),
            )
            self._network_session = webkit.NetworkSession.new_with_website_data_manager(data_manager)
        else:
            self._network_session = webkit.NetworkSession.get_default()

        self.cookie_manager = self._network_session.get_cookie_manager()

        if not _state['private_mode']:
            script_name = pathlib.Path(sys.argv[0]).name
            if script_name in ['python', 'python3', '-c', '']:
                script_name = 'pywebview'
            storage_path = _state['storage_path'] or os.path.expanduser(f'~/.cache/{script_name}/')
            self.cookie_manager.set_persistent_storage(
                os.path.join(storage_path, 'cookies'), webkit.CookiePersistentStorage.TEXT
            )

        web_context = webkit.WebContext.get_default()

        if cert:
            web_context.allow_tls_certificate_for_host(cert, '127.0.0.1')

        self.manager = webkit.UserContentManager()
        self.manager.register_script_message_handler('jsBridge')
        self.manager.connect('script-message-received', self.on_js_bridge_call)

        self.request_headers_mutated = False

        self.webview = webkit.WebView(
            web_context=web_context,
            user_content_manager=self.manager,
            network_session=self._network_session,
        )
        self.webview.connect('map', self.on_webview_ready)
        self.webview.connect('load-changed', self.on_load_finish)
        self.webview.connect('web-process-terminated', self._on_web_process_terminated)
        self.webview.connect('decide-policy', self.on_navigation)
        self.webview.connect('resource-load-started', self.on_request)

        if settings['IGNORE_SSL_ERRORS']:
            self._network_session.set_tls_errors_policy(webkit.TLSErrorsPolicy.IGNORE)

        if settings['ALLOW_DOWNLOADS']:
            self._network_session.connect('download-started', self.on_download_started)

        webkit_settings = self.webview.get_settings().props
        user_agent = settings.get('user_agent') or _state['user_agent']
        if user_agent:
            webkit_settings.user_agent = user_agent

        webkit_settings.enable_media_stream = True
        webkit_settings.enable_mediasource = True
        webkit_settings.enable_webaudio = True
        webkit_settings.enable_webgl = True
        webkit_settings.javascript_can_access_clipboard = True
        webkit_settings.allow_file_access_from_file_urls = settings['ALLOW_FILE_URLS']

        if window.frameless:
            self.window.set_decorated(False)

        if window.on_top:
            self.window.set_keep_above(True)

        if _state['debug']:
            webkit_settings.enable_developer_extras = True
            if settings['OPEN_DEVTOOLS_IN_DEBUG']:
                self.webview.get_inspector().show()
        else:
            self.webview.connect('context-menu', lambda a, b, c: True)

        if _state['private_mode']:
            webkit_settings.enable_html5_database = False
            webkit_settings.enable_html5_local_storage = False

        self.webview.set_opacity(0.0)
        scrolled_window.set_child(self.webview)

        # GTK4 has no set_icon_from_file() on windows; icon is compositor-determined
        # via the Wayland app-id / .desktop file. Log it so it's not mysterious.
        if _state['icon']:
            logger.debug(f'GTK4: window icon ({_state["icon"]}) must be set via a .desktop file')

        self.pywebview_window.events.before_show.set()

        if window.fullscreen:
            self.toggle_fullscreen()

        if window.real_url is not None:
            self.webview.load_uri(window.real_url)
        elif window.html:
            self.webview.load_html(window.html, '')
        else:
            self.webview.load_html(DEFAULT_HTML, '')

    def close_window(self, *data):
        should_cancel = self.pywebview_window.events.closing.set()
        if should_cancel:
            return True

        if self.pywebview_window.confirm_close:
            dialog = gtk.MessageDialog(
                transient_for=self.window,
                modal=True,
                message_type=gtk.MessageType.QUESTION,
                text=self.localization['global.quitConfirmation'],
                buttons=gtk.ButtonsType.OK_CANCEL,
            )
            result = dialog.run()
            dialog.destroy()
            if result == gtk.ResponseType.CANCEL:
                return True

        for res in self.js_results.values():
            res['semaphore'].release()

        self.window.destroy()
        del BrowserView.instances[self.uid]

        if self.pywebview_window in windows:
            windows.remove(self.pywebview_window)

        self.pywebview_window.events.closed.set()
        return False

    def on_window_maximized(self, window, param):
        if window.is_maximized():
            self.pywebview_window.events.maximized.set()
        else:
            self.pywebview_window.events.restored.set()

    def on_window_resize_prop(self, window, param):
        w, h = window.get_default_size()
        if w != self._last_width or h != self._last_height:
            self._last_width = w
            self._last_height = h
            self.pywebview_window.events.resized.set(w, h)

    def on_js_bridge_call(self, manager, message):
        body = json.loads(message.to_string())
        if body['funcName'] == '_pywebviewAlert':
            self.message_box(body['params'])
        else:
            js_bridge_call(self.pywebview_window, body['funcName'], body['params'], body['id'])

    def on_webview_ready(self, *args):
        if 'shown' in dir(self):
            self.shown.set()

    def _on_web_process_terminated(self, webview, reason):
        logger.warning(f'WebKit web process terminated ({reason}), reloading')
        url = self.pywebview_window.real_url
        if url:
            glib.timeout_add(500, lambda: webview.load_uri(url) or False)

    def on_response(self, resource, _):
        response = resource.get_response()
        headers = response.get_http_headers()
        original_headers = self._headers_to_dict(headers)
        url = resource.get_uri()
        response_ = Response(url, response.get_status_code(), original_headers)
        self.pywebview_window.events.response_received.set(response_)

    def on_request(self, webview, resource, request):
        if len(self.pywebview_window.events.request_sent) == 0:
            return
        if len(self.pywebview_window.events.response_received) > 0:
            resource.connect('notify::response', self.on_response)
        headers = request.get_http_headers()
        original_headers = self._headers_to_dict(headers)
        url = request.get_uri()
        method = request.get_http_method()
        request_ = Request(url, method, original_headers)
        self.pywebview_window.events.request_sent.set(request_)

        if (
            request_.headers == original_headers
            or not headers
            or self.request_headers_mutated
            or url != self.pywebview_window.real_url
        ):
            return

        missing_headers = {
            k: v for k, v in request_.headers.items()
            if k not in original_headers or original_headers[k] != v
        }
        extra_headers = {
            k: str(v) for k, v in original_headers.items() if k not in request_.headers
        }
        for k, v in missing_headers.items():
            headers.append(k, v)
        for k in extra_headers:
            headers.remove(k)
        webview.stop_loading()
        self.request_headers_mutated = True
        webview.load_request(request)

    def on_load_finish(self, webview, status):
        if not webview.props.opacity:
            glib.idle_add(webview.set_opacity, 1.0)
        if status == webkit.LoadEvent.FINISHED and not self.request_headers_mutated:
            inject_pywebview(renderer, self.js_bridge.window)
        if self.request_headers_mutated:
            self.request_headers_mutated = False

    def on_download_started(self, session, download):
        download.connect('decide-destination', self.on_download_decide_destination)

    def on_download_decide_destination(self, download, suggested_filename):
        destination = self.create_file_dialog(
            FileDialog.SAVE,
            glib.get_user_special_dir(glib.UserDirectory.DIRECTORY_DOWNLOAD),
            False,
            suggested_filename,
            (),
        )
        if destination:
            destination_uri = glib.filename_to_uri(destination[0])
            download.set_destination(destination_uri)
        else:
            download.cancel()

    def on_navigation(self, webview, decision, decision_type):
        if type(decision) == webkit.NavigationPolicyDecision:
            uri = decision.get_navigation_action().get_request().get_uri()
            if decision.get_navigation_action().get_frame_name() == '_blank':
                if settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']:
                    webbrowser.open(uri, 2, True)
                    decision.ignore()
                else:
                    self.load_url(uri)
        elif type(decision) == webkit.ResponsePolicyDecision:
            if not decision.is_mime_type_supported():
                self._download_filename = decision.get_response().get_suggested_filename()
                decision.download()
            else:
                decision.use()

    def show(self):
        self.window.present()

    def hide(self):
        glib.idle_add(self.window.hide)

    def destroy(self):
        self.window.emit('close-request')

    def set_title(self, title):
        self.window.set_title(title)

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self.window.unfullscreen()
        else:
            self.window.fullscreen()
        self.is_fullscreen = not self.is_fullscreen

    def resize(self, width, height, fix_point):
        # GTK4 doesn't support gravity-anchored resizing
        self.window.set_default_size(width, height)

    def move(self, x, y):
        pass  # GTK4 doesn't support programmatic window positioning

    def maximize(self):
        glib.idle_add(self.window.maximize)

    def minimize(self):
        glib.idle_add(self.window.minimize)

    def restore(self):
        def _restore():
            self.window.unmaximize()
            self.window.present()
        glib.idle_add(_restore)

    def create_confirmation_dialog(self, title, message):
        dialog = gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=gtk.MessageType.QUESTION,
            text=title,
            secondary_text=message,
            buttons=gtk.ButtonsType.OK_CANCEL,
        )
        response = dialog.run()
        dialog.destroy()
        return response == gtk.ResponseType.OK

    def build_file_dialog(self, dialog_type, directory, allow_multiple, save_filename, file_types):
        """Create and configure a FileChooserNative; caller must show() and handle response."""
        if dialog_type == FileDialog.FOLDER:
            action = gtk.FileChooserAction.SELECT_FOLDER
            title = self.localization['linux.openFolder']
            accept_label = self.localization['linux.openFolder']
        elif dialog_type == FileDialog.OPEN:
            action = gtk.FileChooserAction.OPEN
            title = self.localization['linux.openFiles'] if allow_multiple else self.localization['linux.openFile']
            accept_label = title
        elif dialog_type == FileDialog.SAVE:
            action = gtk.FileChooserAction.SAVE
            title = self.localization['global.saveFile']
            accept_label = title

        dialog = gtk.FileChooserNative.new(title, None, action, accept_label, None)
        dialog.set_select_multiple(allow_multiple)

        if directory:
            try:
                dialog.set_current_folder(Gio.File.new_for_path(directory))
            except Exception:
                pass

        self._add_file_filters(dialog, file_types)

        if dialog_type == FileDialog.SAVE and save_filename:
            dialog.set_current_name(save_filename)

        return dialog

    def _add_file_filters(self, dialog, file_types):
        for s in file_types:
            description, extensions = parse_file_type(s)
            f = gtk.FileFilter()
            f.set_name(description)
            for e in extensions.split(';'):
                f.add_pattern(e)
            dialog.add_filter(f)

    def clear_cookies(self):
        glib.idle_add(self.cookie_manager.delete_all_cookies)

    def get_cookies(self):
        def _get_cookies():
            self.cookie_manager.get_cookies(self.webview.get_uri(), None, callback, None)

        def callback(source, task, data):
            results = source.get_cookies_finish(task)
            for c in results:
                cookie = create_cookie(c.to_set_cookie_header())
                cookies.append(cookie)
            semaphore.release()

        cookies = []
        semaphore = Semaphore(0)
        glib.idle_add(_get_cookies)
        semaphore.acquire()
        return cookies

    def get_current_url(self):
        uri = self.webview.get_uri()
        return uri if uri != 'about:blank' else None

    def load_url(self, url):
        self.webview.load_uri(url)

    def load_html(self, content, base_uri):
        self.webview.load_html(content, base_uri)

    def evaluate_js(self, script, parse_json):
        def _evaluate_js():
            try:
                self.webview.evaluate_javascript(
                    script=script,
                    length=len(script),
                    world_name=None,
                    source_uri=None,
                    cancellable=None,
                    callback=_callback,
                )
            except Exception:
                logger.exception('Error evaluating JavaScript')
                result_semaphore.release()

        def _callback(webview, task):
            nonlocal result
            try:
                value = webview.evaluate_javascript_finish(task)
                res = self._convert_js_value(value)
                if parse_json and res:
                    try:
                        result = json.loads(res)
                    except Exception:
                        pass
                else:
                    result = res
            except Exception as e:
                logger.exception(e)
            result_semaphore.release()

        result_semaphore = Semaphore(0)
        result = None
        glib.idle_add(_evaluate_js)
        result_semaphore.acquire()
        return result

    def message_box(self, message):
        dialog = gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=gtk.MessageType.INFO,
            buttons=gtk.ButtonsType.OK,
            text=message,
        )
        dialog.run()
        dialog.destroy()

    def _convert_js_value(self, js_value):
        if not js_value or js_value.is_null() or js_value.is_undefined():
            return None
        elif js_value.is_boolean():
            return js_value.to_boolean()
        elif js_value.is_number():
            return js_value.to_double()
        elif js_value.is_string():
            return js_value.to_string()
        elif js_value.is_object():
            return json.loads(js_value.to_json(2))
        else:
            logger.error(f'Unsupported JavaScriptCore.Value type: {js_value}')
            return js_value.to_string()

    def _headers_to_dict(self, headers):
        def _assign(k, v):
            headers_dict[k] = v
        headers_dict = {}
        if headers:
            headers.foreach(_assign)
        return headers_dict


def setup_app():
    def set_menubar(app):
        app.set_menubar(app_menu)

    global _app
    if _app is not None:
        return

    _app = gtk.Application.new(None, 0)

    if _state['menu']:
        app_menu = create_menu(_state['menu'])
        _app.connect('startup', set_menubar)


def create_window(window):
    global _app

    def create():
        browser = BrowserView(window)
        browser.show()

    def create_master_callback(app):
        create()

    if window.uid == 'master':
        main_thread().pydev_do_not_trace = True
        _app.connect('activate', create_master_callback)
        _app.run()
        _app = None
    else:
        glib.idle_add(create)


def set_title(title, uid):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.set_title, title)


def destroy_window(uid):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.close_window)


def toggle_fullscreen(uid):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.toggle_fullscreen)


def add_tls_cert(certfile):
    global cert
    cert = Gio.TlsCertificate.new_from_file(certfile)


def set_on_top(uid, top):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.window.set_keep_above, top)


def resize(width, height, uid, fix_point):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.resize, width, height, fix_point)


def move(x, y, uid):
    pass  # not supported in GTK4


def hide(uid):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.hide)


def show(uid):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.show)


def maximize(uid):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.maximize)


def minimize(uid):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.minimize)


def restore(uid):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.restore)


def clear_cookies(uid):
    i = BrowserView.instances.get(uid)
    if i:
        i.clear_cookies()


def get_cookies(uid):
    i = BrowserView.instances.get(uid)
    if i:
        return i.get_cookies()


def get_current_url(uid):
    def _get_current_url():
        result['url'] = i.get_current_url()
        semaphore.release()

    result = {}
    semaphore = Semaphore(0)
    i = BrowserView.instances.get(uid)
    if not i:
        return
    glib.idle_add(_get_current_url)
    semaphore.acquire()
    return result['url']


def load_url(url, uid):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.load_url, url)


def load_html(content, base_uri, uid):
    i = BrowserView.instances.get(uid)
    if i:
        glib.idle_add(i.load_html, content, base_uri)


def create_confirmation_dialog(title, message, uid):
    def _create():
        nonlocal result
        result = i.create_confirmation_dialog(title, message)
        result_semaphore.release()

    i = BrowserView.instances.get(uid)
    result_semaphore = Semaphore(0)
    result = -1
    if i:
        glib.idle_add(_create)
        result_semaphore.acquire()
    return result


def create_menu(app_menu_list):
    def action_callback(action, parameter):
        function = _app_actions.get(action.get_name())
        if function is None:
            return
        Thread(target=function).start()

    def create_submenu(title, line_items, supermenu, action_prepend=''):
        m = Gio.Menu.new()
        current_section = Gio.Menu.new()
        action_prepend = f'{action_prepend}_{title}'
        for menu_line_item in line_items:
            if isinstance(menu_line_item, MenuSeparator):
                m.append_section(None, current_section)
                current_section = Gio.Menu.new()
            elif isinstance(menu_line_item, MenuAction):
                action_label = f'{action_prepend}_{menu_line_item.title}'.replace(' ', '_')
                while action_label in _app_actions.keys():
                    action_label += '_'
                _app_actions[action_label] = menu_line_item.function
                new_action = Gio.SimpleAction.new(action_label, None)
                new_action.connect('activate', action_callback)
                _app.add_action(new_action)
                current_section.append(menu_line_item.title, 'app.' + action_label)
            elif isinstance(menu_line_item, Menu):
                create_submenu(menu_line_item.title, menu_line_item.items, current_section, action_prepend=action_prepend)
        m.append_section(None, current_section)
        supermenu.append_submenu(title, m)

    menubar = Gio.Menu()
    for app_menu in app_menu_list:
        if app_menu.title == '__app__':
            continue
        create_submenu(app_menu.title, app_menu.items, menubar)
    return menubar


def get_active_window():
    try:
        active_window = _app.get_active_window()
    except Exception:
        return None
    if not active_window:
        return None
    active_id = active_window.get_id()
    for uid, bv in BrowserView.instances.items():
        if bv.window.get_id() == active_id:
            return bv.pywebview_window
    return None


def create_file_dialog(dialog_type, directory, allow_multiple, save_filename, file_types, uid):
    i = BrowserView.instances.get(uid)
    semaphore = Semaphore(0)
    file_names = []

    def on_response(dialog, response):
        try:
            if response == gtk.ResponseType.ACCEPT:
                if dialog_type == FileDialog.SAVE:
                    f = dialog.get_file()
                    file_names.append((f.get_path(),) if f else None)
                else:
                    files = dialog.get_files()
                    paths = [files.get_item(j).get_path() for j in range(files.get_n_items())]
                    file_names.append(paths if paths else None)
            else:
                file_names.append(None)
        finally:
            dialog.destroy()
            semaphore.release()

    def _create():
        # Build dialog on GTK main thread, connect response, show without blocking.
        # The calling thread (held on semaphore) unblocks when response fires.
        try:
            dialog = i.build_file_dialog(dialog_type, directory, allow_multiple, save_filename, file_types)
            dialog.connect('response', on_response)
            dialog.show()
        except Exception as e:
            logger.error(f'GTK4 file dialog setup failed: {e}')
            file_names.append(None)
            semaphore.release()

    glib.idle_add(_create)
    semaphore.acquire()
    return file_names[0] if file_names else None


def evaluate_js(script, uid, parse_json=True):
    i = BrowserView.instances.get(uid)
    if i:
        return i.evaluate_js(script, parse_json)


def get_position(uid):
    # GTK4 doesn't expose window position to applications
    return (0, 0)


def get_size(uid):
    def _get_size():
        result['size'] = i.window.get_default_size()
        semaphore.release()

    i = BrowserView.instances.get(uid)
    if not i:
        return
    result = {}
    semaphore = Semaphore(0)
    glib.idle_add(_get_size)
    semaphore.acquire()
    return result['size']


def get_screens():
    display = Gdk.Display.get_default()
    monitors = display.get_monitors()
    screens = []
    for i in range(monitors.get_n_items()):
        monitor = monitors.get_item(i)
        geom = monitor.get_geometry()
        screens.append(Screen(geom.x, geom.y, geom.width, geom.height, geom))
    return screens


cert = None
