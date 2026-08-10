from flask import Flask, request, jsonify, send_from_directory
import logging
import threading
import time
from logging.handlers import RotatingFileHandler
import os
import sys

# ── Logging Setup — must be first so import errors are captured ───────────────
# Use sys.executable dir when frozen so the log lands next to the .exe, not
# inside the PyInstaller temp bundle (_MEIPASS) where it would be invisible.
# Under Flatpak, /app is read-only at runtime, so the log goes to the same
# writable data dir as everything else (see config.py's BASE_DIR).
if getattr(sys, 'frozen', False):
    _LOG_DIR = os.path.dirname(sys.executable)
elif os.path.exists('/.flatpak-info'):
    _LOG_DIR = os.path.join(
        os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')),
        'playdate')
    os.makedirs(_LOG_DIR, exist_ok=True)
else:
    _LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(_LOG_DIR, 'playdate.log')

_MAX_MSG_LEN = 500

class _TruncatingFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        if len(msg) > _MAX_MSG_LEN:
            msg = msg[:_MAX_MSG_LEN] + f'… [{len(msg) - _MAX_MSG_LEN} chars truncated]'
        return msg

_handler_file   = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=0, encoding='utf-8')
_handler_stream = logging.StreamHandler()
_fmt = _TruncatingFormatter('%(asctime)s [%(levelname)s] %(message)s')
_handler_file.setFormatter(_fmt)
_handler_stream.setFormatter(_fmt)

# Root logger at WARNING — silences urllib3, PIL, werkzeug noise
logging.basicConfig(level=logging.WARNING, handlers=[_handler_file, _handler_stream], force=True)

# PlayDate modules at INFO
for _name in ('__main__', 'app', 'config', 'database', 'library', 'index',
              'scrapers', 'utils', 'images', 'imports', 'pagywosg',
              'date_import', 'system', 'pick', 'backup', 'updater', 'pop_sync',
              'runners.proton', 'runners.launcher_installer', 'plugins'):
    logging.getLogger(_name).setLevel(logging.INFO)

log = logging.getLogger(__name__)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
sys.excepthook = handle_exception

from config import config_bp
from index import index_bp
from library import library_bp
from emulators import emulators_bp
from images import images_bp
from date_import import date_import_bp
from system import system_bp
from pick import pick_bp
from backup import backup_bp
from diagnostics import diagnostics_bp
from updater import updater_bp, _startup_update_check
from notifications import notifications_bp, _startup_notification_check
from scrapers import blaeo_bp
from pagywosg import pagywosg_bp
from pop_sync import pop_bp
from imports import imports_bp
from plugins import plugins_bp
from config import BASE_DIR
import pagywosg
import scrapers

# Module-level cancel event so main.py can signal it on window close.
populate_cancel = threading.Event()


def create_app(template_folder=None, static_folder=None):
    """
    Flask application factory.

    When running normally:   create_app() — uses Flask defaults
    When frozen by PyInstaller: create_app(template_folder=..., static_folder=...)
      so Flask can find templates and static files inside the bundle.
    """
    kwargs = {}
    if template_folder:
        kwargs['template_folder'] = template_folder
    if static_folder:
        kwargs['static_folder'] = static_folder

    app = Flask(__name__, **kwargs)

    # Register a signed-int converter so routes like /api/game/-1 work for GOG games
    from werkzeug.routing.converters import IntegerConverter
    class SignedIntConverter(IntegerConverter):
        regex = r'-?\d+'
    app.url_map.converters['int'] = SignedIntConverter

    app.register_blueprint(config_bp)
    app.register_blueprint(index_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(emulators_bp)
    app.register_blueprint(images_bp)
    app.register_blueprint(date_import_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(pick_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(diagnostics_bp)
    app.register_blueprint(updater_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(blaeo_bp)
    app.register_blueprint(pagywosg_bp)
    app.register_blueprint(pop_bp)
    app.register_blueprint(imports_bp)
    app.register_blueprint(plugins_bp)

    # ── CORS for Tampermonkey userscript (runs on help.steampowered.com) ─────
    # Adds CORS + Private Network Access headers to every response when the
    # request originates from the Steam help domain.  Covers both simple GETs
    # and preflight OPTIONS requests without needing per-route handling.
    @app.after_request
    def _userscript_cors(response):
        from urllib.parse import urlparse
        origin = request.headers.get('Origin', '')
        _o = urlparse(origin)
        if _o.scheme == 'https' and _o.hostname == 'help.steampowered.com':
            response.headers['Access-Control-Allow-Origin']          = origin
            response.headers['Access-Control-Allow-Headers']         = 'Content-Type'
            response.headers['Access-Control-Allow-Methods']         = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Private-Network'] = 'true'
        return response

    # ── User-data static files ────────────────────────────────────────────────
    # When frozen by PyInstaller, Flask's static_folder points into the bundle
    # (sys._MEIPASS), but downloaded covers and the user background are written
    # to BASE_DIR (next to the .exe).  These routes serve those files from the
    # correct location so they're visible on Windows builds.
    import re
    _SAFE_FILENAME_RE = re.compile(r'^[\w\-./]+$')

    # Cover art URLs are cache-busted client-side via a ?v= timestamp query
    # param (bumped per-appid in _patchGameCard/_imgVersions whenever art
    # actually changes -- see library.js), so a long browser cache here can't
    # go stale: any URL the browser has cached is guaranteed to still be
    # correct, and a changed image gets a brand new URL instead.
    _LIBRARY_IMG_MAX_AGE = 31536000  # 1 year

    @app.route('/static/img/library/<path:filename>')
    def serve_library_image(filename):
        from database import get_dup_cache
        if not _SAFE_FILENAME_RE.match(filename):
            return '', 400
        lib_dir = os.path.join(BASE_DIR, 'static', 'img', 'library')
        if os.path.exists(os.path.join(lib_dir, filename)):
            return send_from_directory(lib_dir, filename, max_age=_LIBRARY_IMG_MAX_AGE)
        # If the file is missing, check whether this game is a duplicate and
        # serve the canonical game's image instead.
        parts = filename.split('/')  # e.g. ['vertical', '-12345.jpg']
        if len(parts) == 2:
            stem = parts[1].rsplit('.', 1)[0]
            try:
                req_appid = int(stem)
                dup_of = get_dup_cache().get(req_appid)
                if dup_of:
                    canon_file = f"{parts[0]}/{dup_of}.{parts[1].rsplit('.', 1)[1]}"
                    if os.path.exists(os.path.join(lib_dir, canon_file)):
                        return send_from_directory(lib_dir, canon_file, max_age=_LIBRARY_IMG_MAX_AGE)
            except (ValueError, Exception):
                pass
        return send_from_directory(lib_dir, filename)  # let Flask return 404

    @app.route('/static/img/backgrounds/<path:filename>')
    def serve_background_image(filename):
        if not _SAFE_FILENAME_RE.match(filename):
            return '', 400
        bg_dir = os.path.join(BASE_DIR, 'static', 'img', 'backgrounds')
        if os.path.exists(os.path.join(bg_dir, filename)):
            return send_from_directory(bg_dir, filename)
        # Fall back to the bundled default — a distinct filename from the
        # user-override path above so the two never collide on source installs,
        # where BASE_DIR and the bundle's static folder are the same directory.
        return app.send_static_file('img/backgrounds/playdate_default_background.jpg')

    # ── Inject background timestamp and builtin filters into every template ──────
    @app.context_processor
    def inject_globals():
        import time as _time
        _t0 = _time.monotonic()
        from config import BUILTIN_FILTERS, load_theme
        from utils import get_all_unique_tags, get_all_unique_groups, get_all_unique_genres, get_all_unique_categories, get_all_unique_platforms, unique_cache_info
        _cache_hit, _cache_age = unique_cache_info()
        from plugins import platform_labels as _platform_labels
        bg_path = os.path.join(BASE_DIR, 'static', 'img', 'backgrounds', 'background.jpg')
        if os.path.exists(bg_path):
            ts = int(os.path.getmtime(bg_path))
        else:
            default_bg_path = os.path.join(app.static_folder, 'img', 'backgrounds', 'playdate_default_background.jpg')
            ts = int(os.path.getmtime(default_bg_path)) if os.path.exists(default_bg_path) else None
        _plat_list = get_all_unique_platforms()
        _labels = _platform_labels()
        result = dict(
            background_ts=ts,
            builtin_filters=BUILTIN_FILTERS,
            theme_vars=load_theme(),
            unique_tags=get_all_unique_tags(),
            unique_groups=get_all_unique_groups(),
            unique_genres=get_all_unique_genres(),
            unique_categories=get_all_unique_categories(),
            available_platforms=_plat_list,
            available_platform_options={p: _labels.get(p, p) for p in _plat_list},
            is_windows=sys.platform == 'win32',
        )
        log.info("inject_globals: %.1fms (%s, age=%.1fs)",
                 (_time.monotonic() - _t0) * 1000,
                 "hit" if _cache_hit else "miss",
                 _cache_age)
        return result

    # ── Cancellation + progress state for populate ───────────────────────────
    _populate_cancel = populate_cancel   # module-level event; main.py sets it on close
    _recent_lock     = threading.Lock()
    _populate_state  = {
        "running":          False,
        "last_result":      None,
        "total":            0,
        "meta_done":        0,
        "art_done":         0,
        "cheevo_done":      0,
        "protondb_done":    0,
        "hltb_done":        0,
        "started_at":       None,
        "eta_seconds":      None,
        "new_placeholders": [],   # game dicts just inserted — cleared each poll
        "recently_meta":    [],   # appids that just got metadata — cleared each poll
        "recently_art":     [],   # appids that just got art — cleared each poll
        "recently_blacklist": [], # appids removed via blacklist — cleared each poll
        "rate_limit_aborted": False,
        "rate_limit_hits":    0,        # total 429s received across all pools
        "rate_limit_last":    None,     # {pool, attempt, delay} for most recent hit
        "_priority_queues": None, # set when workers start; used by /api/populate-priority
    }

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.route('/api/populate-status')
    def populate_status():
        with _recent_lock:
            new_ph   = list(_populate_state["new_placeholders"])
            r_meta   = list(_populate_state["recently_meta"])
            r_art    = list(_populate_state["recently_art"])
            r_bl     = list(_populate_state["recently_blacklist"])
            _populate_state["new_placeholders"].clear()
            _populate_state["recently_meta"].clear()
            _populate_state["recently_art"].clear()
            _populate_state["recently_blacklist"].clear()
        return jsonify({
            "running":            _populate_state["running"],
            "last_result":        _populate_state["last_result"],
            "total":              _populate_state["total"],
            "meta_done":          _populate_state["meta_done"],
            "art_done":           _populate_state["art_done"],
            "cheevo_done":        _populate_state["cheevo_done"],
            "protondb_done":      _populate_state["protondb_done"],
            "hltb_done":          _populate_state["hltb_done"],
            "eta_seconds":        _populate_state["eta_seconds"],
            "new_placeholders":   new_ph,
            "recently_meta":      r_meta,
            "recently_art":       r_art,
            "recently_blacklist": r_bl,
            "rate_limit_aborted": _populate_state["rate_limit_aborted"],
            "rate_limit_hits":    _populate_state["rate_limit_hits"],
            "rate_limit_last":    _populate_state["rate_limit_last"],
        })

    @app.route('/add-new')
    def add_new():
        _populate_cancel.clear()
        with _recent_lock:
            _populate_state["running"]            = True
            _populate_state["last_result"]        = None
            _populate_state["total"]              = 0
            _populate_state["meta_done"]          = 0
            _populate_state["art_done"]           = 0
            _populate_state["cheevo_done"]        = 0
            _populate_state["protondb_done"]      = 0
            _populate_state["hltb_done"]          = 0
            _populate_state["started_at"]         = None
            _populate_state["eta_seconds"]        = None
            _populate_state["new_placeholders"]   = []
            _populate_state["recently_meta"]      = []
            _populate_state["recently_art"]       = []
            _populate_state["recently_blacklist"] = []
            _populate_state["rate_limit_aborted"] = False
            _populate_state["rate_limit_hits"]    = 0
            _populate_state["rate_limit_last"]    = None
            _populate_state["_priority_queues"]   = None

        def _progress(event_type, data, total):
            now = time.time()
            with _recent_lock:
                if event_type == 'placeholder':
                    _populate_state["total"] = total
                    _populate_state["new_placeholders"].append(data)
                elif event_type == 'workers_starting':
                    _populate_state["started_at"]       = now
                    _populate_state["_priority_queues"] = data
                elif event_type == 'meta':
                    _populate_state["meta_done"] += 1
                    _populate_state["recently_meta"].append(data)
                    done  = _populate_state["meta_done"]
                    total_ = _populate_state["total"]
                    if done > 0 and _populate_state["started_at"] and total_ > done:
                        elapsed = now - _populate_state["started_at"]
                        _populate_state["eta_seconds"] = round((elapsed / done) * (total_ - done))
                    elif done >= total_:
                        _populate_state["eta_seconds"] = 0
                elif event_type == 'art':
                    _populate_state["art_done"] += 1
                    _populate_state["recently_art"].append(data)
                elif event_type == 'cheevo':
                    _populate_state["cheevo_done"] += 1
                elif event_type == 'protondb':
                    _populate_state["protondb_done"] += 1
                elif event_type == 'hltb':
                    _populate_state["hltb_done"] += 1
                elif event_type == 'blacklist':
                    _populate_state["recently_blacklist"].append(data)
                elif event_type == 'rate_limit_hit':
                    _populate_state["rate_limit_hits"] += 1
                    _populate_state["rate_limit_last"]  = data
                elif event_type == 'rate_limit_abort':
                    _populate_state["rate_limit_aborted"] = True

        try:
            result = scrapers.add_new(_populate_cancel, progress_cb=_progress)
            _populate_state["last_result"] = result
        finally:
            _populate_state["running"] = False
            from utils import invalidate_unique_cache
            invalidate_unique_cache()
            import plugins as _plugins
            _plugins.notify_library_updated()
        return jsonify(result)

    @app.route('/api/cancel-populate', methods=['POST'])
    def cancel_populate():
        _populate_cancel.set()
        return jsonify({"status": "success"})

    @app.route('/api/populate-priority', methods=['POST'])
    def populate_priority():
        """
        Receives a list of visible appids from the library page and pushes them
        to the front of each worker pool's priority queue so they are processed
        before off-screen games.
        """
        if not _populate_state["running"]:
            return jsonify({"status": "ok"})
        queues = _populate_state.get("_priority_queues")
        if not queues:
            return jsonify({"status": "ok"})
        appids = request.json.get("appids", [])
        for appid in appids:
            for q in queues.values():
                q.put(appid)
        return jsonify({"status": "ok"})

    # ── Background update check on startup ───────────────────────────────────
    threading.Thread(target=_startup_update_check, daemon=True).start()
    threading.Thread(target=_startup_notification_check, daemon=True).start()

    import plugins as _plugins
    # Must run (and finish) before load_all()/register_blueprint below --
    # Flask refuses new blueprint registrations once the app has handled its
    # first request, which happens well before a background thread doing
    # GitHub round-trips would ever finish. Only reinstalls a plugin that's
    # both missing from disk AND shows evidence of prior configuration (a
    # saved auth token or launcher config) -- see
    # plugins.reinstall_configured_official_plugins for why. Every other
    # startup is a fast, local-only no-op.
    try:
        _plugins.reinstall_configured_official_plugins()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Official plugin reinstall check failed: {e}")

    _plugins.load_all(app)

    # Set INFO on all plugin sub-modules so their logs are captured
    for _pid, _p in _plugins.loaded().items():
        _mod_prefix = f'plugins.{_pid}'
        for _mname in list(sys.modules):
            if _mname == _mod_prefix or _mname.startswith(_mod_prefix + '.'):
                logging.getLogger(_mname).setLevel(logging.INFO)

    threading.Thread(target=_plugins._startup_launcher_status_check, daemon=True).start()

    app.jinja_env.globals['has_plugin']        = _plugins.has
    app.jinja_env.globals['plugin_fragments']  = _plugins.fragments
    app.jinja_env.globals['plugin_fragment_js'] = _plugins.fragment_js
    app.jinja_env.globals['platform_labels']   = _plugins.platform_labels
    app.jinja_env.globals['plugin_js_api']     = _plugins.plugin_js_api
    app.jinja_env.globals['plugin_home_widgets']    = _plugins.home_widgets
    app.jinja_env.globals['plugin_widget_fragment'] = _plugins.widget_fragment
    app.jinja_env.globals['pagywosg_op_table'] = pagywosg.js_op_table

    return app


# ── Backwards compatibility: module-level `app` for running directly ──────────
# Only create at module level when running as the entry point, not when imported
# by main.py (which calls create_app() itself, avoiding a double startup).
if __name__ == '__main__' or os.environ.get('FLASK_APP') == 'app':
    app = create_app()

if __name__ == '__main__':
    import migration
    from database import init_db
    migration.run()
    init_db()
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1', port=5000)
