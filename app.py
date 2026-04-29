from flask import Flask, render_template, redirect, request, url_for, jsonify, send_from_directory
import logging
import time
from logging.handlers import RotatingFileHandler
import os
import sys

# ── Logging Setup — must be first so import errors are captured ───────────────
# Use sys.executable dir when frozen so the log lands next to the .exe, not
# inside the PyInstaller temp bundle (_MEIPASS) where it would be invisible.
if getattr(sys, 'frozen', False):
    _LOG_DIR = os.path.dirname(sys.executable)
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
              'scrapers', 'utils', 'images', 'imports', 'runners.proton', 'plugins'):
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
from utils import sync_local_install_status, record_launch
from config import BASE_DIR
from imports import inspect_database, execute_import
from scrapers import scrape_blaeo_games
from database import get_db, init_db, update_game_data, add_to_blacklist, remove_from_blacklist, get_blacklist
import re
import scrapers
import threading
import json
import subprocess
import platform
import shutil
from urllib.parse import urlparse


# ── Pending dates (set by browser userscript from Steam help pages) ───────────
_pending_dates = {}  # appid (int) → 'YYYY-MM-DD'

# ── Bulk date import state ────────────────────────────────────────────────────
_bulk_date_state = {
    'queue':            [],    # [{appid, name}, …] remaining
    'current':          None,  # {appid, name} being processed
    'done':             0,
    'failed':           0,
    'total':            0,
    'active':           False,
    'script_connected': False, # True once userscript pings back
    'results':          [],    # [{name, appid, date}, …] newest first; date=None means not found
}

# ── Update checking ───────────────────────────────────────────────────────────
_update_cache = {}  # available, latest_version, installer_url, zipball_url, checked_at, error
_plugin_update_cache = {}  # keyed by plugin_id: {update_available, latest_version, source, checked_at, error}
_launcher_status_cache = {}  # keyed by platform: {available, detail, checked_at}
_update_dl_state = {'status': 'idle', 'error': None, 'manual_url': None}  # idle|downloading|error

def _validate_user_path(path: str) -> str | None:
    """Return the resolved absolute path, or None if it looks malicious."""
    if not path or '\x00' in path:
        return None
    resolved = os.path.realpath(path)
    if not os.path.isabs(resolved):
        return None
    return resolved

def _do_update_check():
    """Hit the GitHub releases API and populate _update_cache. Thread-safe."""
    from config import __version__
    import time
    try:
        import requests as _req
        resp = _req.get(
            'https://api.github.com/repos/RobbyRatpoison/PlayDate/releases/latest',
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'PlayDate-App'},
            timeout=10
        )
        data = resp.json()
        tag = data.get('tag_name', '')
        latest = tag.lstrip('v')

        def _parse(v):
            try: return tuple(int(x) for x in v.split('.'))
            except: return (0, 0, 0)

        available = _parse(latest) > _parse(__version__)

        installer_url = None
        for asset in data.get('assets', []):
            if asset.get('name', '').lower().endswith('.exe'):
                installer_url = asset['browser_download_url']
                break

        _update_cache.update({
            'available': available,
            'latest_version': latest,
            'installer_url': installer_url,
            'zipball_url': data.get('zipball_url'),
            'checked_at': time.time(),
            'error': None
        })
        log.info(f"Update check: latest={latest}, current={__version__}, available={available}")
    except Exception as e:
        _update_cache.update({'available': False, 'checked_at': time.time(), 'error': str(e)})
        log.warning(f"Update check failed: {e}")


def _parse_github_repo(url):
    """Return (owner, repo) from a GitHub URL or 'owner/repo' slug, or (None, None)."""
    import re
    url = url.strip().rstrip('/')
    m = re.match(r'(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/?#]+)', url)
    if m:
        return m.group(1), m.group(2).removesuffix('.git')
    m = re.match(r'^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$', url)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _fetch_github_plugin_release(owner, repo):
    """Return (zip_url, tag_name) for the latest release. zip_url may be a release asset or zipball."""
    import requests as _req
    resp = _req.get(
        f'https://api.github.com/repos/{owner}/{repo}/releases/latest',
        headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'PlayDate-App'},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    tag = data.get('tag_name', '?')
    for asset in data.get('assets', []):
        if asset.get('name', '').lower().endswith('.zip'):
            return asset['browser_download_url'], tag
    return data.get('zipball_url'), tag


def _install_plugin_zip(raw_bytes):
    """
    Validate and extract a plugin from raw zip bytes.
    Returns (plugin_id, plugin_name). Raises ValueError with a user-facing message on failure.
    """
    import zipfile, io, json as _json
    buf = io.BytesIO(raw_bytes)
    try:
        zf_obj = zipfile.ZipFile(buf, 'r')
    except zipfile.BadZipFile:
        raise ValueError('File is not a valid zip archive.')
    with zf_obj as zf:
        names = zf.namelist()
        if 'plugin.json' in names:
            prefix = ''
        else:
            top_dirs = {n.split('/')[0] for n in names if '/' in n}
            prefix = None
            for d in top_dirs:
                if f'{d}/plugin.json' in names:
                    prefix = d + '/'
                    break
            if prefix is None:
                raise ValueError('Invalid plugin zip: no plugin.json found.')

        manifest = _json.loads(zf.read(f'{prefix}plugin.json'))
        plugin_id = manifest.get('id', '').strip()
        if not plugin_id or not plugin_id.replace('_', '').isalnum():
            raise ValueError('Invalid or missing plugin id in plugin.json.')

        plugins_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'plugins')
        dest = os.path.join(plugins_dir, plugin_id)
        if not os.path.abspath(dest).startswith(os.path.abspath(plugins_dir) + os.sep):
            raise ValueError('Invalid plugin id.')

        os.makedirs(dest, exist_ok=True)
        for member in names:
            if not member.startswith(prefix):
                continue
            rel = member[len(prefix):]
            if not rel:
                continue
            member_dest = os.path.join(dest, rel)
            if not os.path.abspath(member_dest).startswith(os.path.abspath(dest) + os.sep) \
                    and os.path.abspath(member_dest) != os.path.abspath(dest):
                continue
            if member.endswith('/'):
                os.makedirs(member_dest, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(member_dest), exist_ok=True)
                with zf.open(member) as src, open(member_dest, 'wb') as dst:
                    dst.write(src.read())

    return plugin_id, manifest.get('name', plugin_id)


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

    # ── CORS for Tampermonkey userscript (runs on help.steampowered.com) ─────
    # Adds CORS + Private Network Access headers to every response when the
    # request originates from the Steam help domain.  Covers both simple GETs
    # and preflight OPTIONS requests without needing per-route handling.
    @app.after_request
    def _userscript_cors(response):
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
    _SAFE_FILENAME_RE = re.compile(r'^[\w\-./]+$')

    @app.route('/static/img/library/<path:filename>')
    def serve_library_image(filename):
        if not _SAFE_FILENAME_RE.match(filename):
            return '', 400
        return send_from_directory(
            os.path.join(BASE_DIR, 'static', 'img', 'library'), filename
        )

    @app.route('/static/img/backgrounds/<path:filename>')
    def serve_background_image(filename):
        if not _SAFE_FILENAME_RE.match(filename):
            return '', 400
        bg_dir = os.path.join(BASE_DIR, 'static', 'img', 'backgrounds')
        if os.path.exists(os.path.join(bg_dir, filename)):
            return send_from_directory(bg_dir, filename)
        # Fall back to the bundled default
        return app.send_static_file(f'img/backgrounds/{filename}')

    # ── Inject background timestamp and builtin filters into every template ──────
    @app.context_processor
    def inject_globals():
        from config import BUILTIN_FILTERS, load_theme
        from utils import get_all_unique_tags, get_all_unique_groups, get_all_unique_genres, get_all_unique_categories
        bg_path = os.path.join(BASE_DIR, 'static', 'img', 'backgrounds', 'background.jpg')
        ts = int(os.path.getmtime(bg_path)) if os.path.exists(bg_path) else None
        return dict(
            background_ts=ts,
            builtin_filters=BUILTIN_FILTERS,
            theme_vars=load_theme(),
            unique_tags=get_all_unique_tags(),
            unique_groups=get_all_unique_groups(),
            unique_genres=get_all_unique_genres(),
            unique_categories=get_all_unique_categories(),
            is_windows=sys.platform == 'win32',
        )

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

    # ── Cancellation + progress state for bulk operations ────────────────────
    _bulk_op_state  = {'running': False, 'op': None, 'total': 0, 'done': 0,
                       'failed': 0, 'rate_limit_hit': False, 'aborted': False, 'result': None}
    _bulk_op_lock   = threading.Lock()
    _bulk_op_cancel = threading.Event()

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.route('/pick')
    def pick():
        from config import load_state, resolve_active_filter_tree
        state = load_state()
        ft = resolve_active_filter_tree(state)
        has_filters = bool(ft and (ft.get('items') or ft.get('custom_sql')))
        return render_template('pick.html', state=state, has_filters=has_filters)

    @app.route('/api/pick-game', methods=['POST'])
    def pick_game():
        import random
        from config import load_state
        from database import get_db
        from library import build_tree_sql, _strip_sql_wrapper, is_safe_sql

        data         = request.json or {}
        mode         = data.get('mode', 'random')
        use_filtered = data.get('use_filtered', False)
        statuses     = data.get('statuses', None)  # None means all statuses
        w_tags      = float(data.get('w_tags',      65))
        w_review    = float(data.get('w_review',    35))
        w_staleness = float(data.get('w_staleness',  0))
        w_recency   = float(data.get('w_recency',    0))
        w_hltb      = float(data.get('w_hltb',       0))

        def _parse_bound(key):
            v = data.get(key)
            return float(v) if v is not None else None

        b_review    = _parse_bound('b_review')
        b_staleness = _parse_bound('b_staleness')
        b_recency   = _parse_bound('b_recency')
        b_hltb      = _parse_bound('b_hltb')

        state  = load_state()
        db     = get_db()
        params = []
        where  = '1=1'

        if use_filtered:
            from config import resolve_active_filter_tree
            filter_tree = resolve_active_filter_tree(state)
            if filter_tree:
                custom_sql = _strip_sql_wrapper(filter_tree.get('custom_sql', ''))
                if custom_sql:
                    where = custom_sql if is_safe_sql(custom_sql) else '1=0'
                else:
                    tree_sql = build_tree_sql(filter_tree, params)
                    if tree_sql and tree_sql != '1=1':
                        where = tree_sql

        if statuses is not None:
            placeholders = ','.join('?' * len(statuses))
            where = f"({where}) AND completion_status IN ({placeholders})"
            params = list(params) + list(statuses)

        # Smart mode auto-bounds: apply a minimum review floor automatically.
        if mode == 'smart' and b_review is None:
            b_review = 70.0

        smart_where = where
        if mode in ('smart', 'weighted'):
            smart_where = f"({where}) AND completion_status NOT IN ('Beaten', 'Completed')"

        try:
            rows = db.execute(f"SELECT * FROM games WHERE {smart_where}", params).fetchall()
        except Exception as e:
            db.close()
            return jsonify({"status": "error", "message": f"Filter error: {e}"}), 400

        games = [dict(r) for r in rows]

        if not games:
            db.close()
            return jsonify({"status": "error", "message": "No games matched the current filters."})

        NUM_PICKS = 6
        picks = []
        any_relaxed = False
        bounded_pool_size = len(games)

        if mode in ('smart', 'weighted'):
            profile_rows = db.execute(
                "SELECT tags, playtime_forever FROM games "
                "WHERE completion_status IN ('Beaten', 'Completed') "
                "AND tags IS NOT NULL AND tags != ''"
            ).fetchall()

            using_fallback = False
            if not profile_rows:
                using_fallback = True
                profile_rows = db.execute(
                    "SELECT tags, playtime_forever FROM games "
                    "WHERE tags IS NOT NULL AND tags != '' "
                    "ORDER BY playtime_forever DESC LIMIT 50"
                ).fetchall()

            db.close()

            tag_weights: dict[str, float] = {}
            for row in profile_rows:
                weight = max(float(row['playtime_forever'] or 0), 1.0)
                for tag in [t.strip() for t in (row['tags'] or '').split(',') if t.strip()]:
                    tag_weights[tag] = tag_weights.get(tag, 0.0) + weight

            profile_norm = sum(v * v for v in tag_weights.values()) ** 0.5 or 1.0

            def tag_similarity(g):
                candidate_tags = [t.strip() for t in (g.get('tags') or '').split(',') if t.strip()]
                if not candidate_tags:
                    return 0.0, []
                dot    = sum(tag_weights.get(t, 0.0) for t in candidate_tags)
                c_norm = len(candidate_tags) ** 0.5
                sim    = dot / (profile_norm * c_norm) if (profile_norm * c_norm) else 0.0
                matched = sorted([t for t in candidate_tags if t in tag_weights],
                                 key=lambda t: tag_weights[t], reverse=True)
                return sim, matched

            def review_score(g):
                wp = g.get('weighted_percentage')
                rp = g.get('review_percentage')
                if wp is not None and wp != '': return float(wp) / 100.0
                if rp is not None and rp != '': return float(rp) / 100.0
                return None

            def staleness_score(g):
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc).timestamp()
                lp = g.get('last_played')
                if lp:
                    try:
                        return min((now - float(lp)) / 86400, 730) / 730.0
                    except Exception:
                        return 0.5
                return 1.0

            def hltb_length_score(g):
                # Returns [0,1] where 1 = longest, or None if no data.
                # sqrt curve concentrates probability at the extremes so moderate
                # lengths don't crowd out clearly short/long games.
                import math
                times = [v for v in [g.get('hltb_main'), g.get('hltb_extras'), g.get('hltb_completionist')] if v]
                if not times:
                    return None  # handled as low (not neutral) by sig() via unknown_val
                if w_hltb >= 0:
                    # Prefer long: max time, floor at 10hrs, scale over 100hrs above floor.
                    # 10hr → 0, 35hr → 0.5, 110hr+ → 1.0
                    val = max(times)
                    return math.sqrt(max(0.0, min(float(val) - 600.0, 6000.0) / 6000.0)
)
                else:
                    # Prefer short: min time, cap at 10hrs.
                    # 0hr → 0, 2.5hr → 0.5, 10hr+ → 1.0
                    val = min(times)
                    return math.sqrt(min(float(val), 600.0) / 600.0)

            def recency_score(g):
                rd = g.get('release_date')
                if not rd:
                    return 0.5
                try:
                    from datetime import datetime, timezone
                    year = datetime.fromtimestamp(float(rd), tz=timezone.utc).year
                    age_years = max(datetime.now().year - year, 0)
                    return 1.0 - min(age_years, 10) / 10.0
                except Exception:
                    return 0.5

            def score_game(g, relax_factor=0.0):
                sim, matched = tag_similarity(g)
                rev  = review_score(g)
                stal = staleness_score(g)
                rec  = recency_score(g)
                hltb = hltb_length_score(g)

                if relax_factor < 1.0:
                    w_rev_dir = w_review if mode == 'weighted' else 35.0
                    if b_review is not None and rev is not None:
                        rev_pct = rev * 100
                        if w_rev_dir >= 0:
                            if rev_pct < b_review * (1 - relax_factor):
                                return None
                        else:
                            if rev_pct > b_review + (100 - b_review) * relax_factor:
                                return None
                    if b_staleness is not None:
                        from datetime import datetime, timezone as _tzb
                        _now = datetime.now(_tzb.utc).timestamp()
                        _lp  = g.get('last_played')
                        _days = (_now - float(_lp)) / 86400 if _lp else 999999.0
                        if w_staleness >= 0:
                            if _days < b_staleness * (1 - relax_factor):
                                return None
                        else:
                            if _days > b_staleness * (1 + 9 * relax_factor):
                                return None
                    if b_recency is not None:
                        _rd = g.get('release_date')
                        if _rd:
                            try:
                                from datetime import datetime, timezone as _tzc
                                _yr = datetime.fromtimestamp(float(_rd), tz=_tzc.utc).year
                                if w_recency >= 0:
                                    if _yr < b_recency - relax_factor * (b_recency - 1970):
                                        return None
                                else:
                                    _cur_yr = datetime.now(_tzc.utc).year
                                    if _yr > b_recency + relax_factor * (_cur_yr - b_recency):
                                        return None
                            except Exception:
                                pass
                    if b_hltb is not None:
                        _times = [v for v in [g.get('hltb_main'), g.get('hltb_extras'), g.get('hltb_completionist')] if v]
                        if _times:
                            if w_hltb >= 0:
                                if max(_times) / 60 < b_hltb * (1 - relax_factor):
                                    return None
                            else:
                                if min(_times) / 60 > b_hltb * (1 + 9 * relax_factor):
                                    return None

                if mode == 'weighted':
                    total_w = (abs(w_tags) + abs(w_review) + abs(w_staleness) + abs(w_recency) + abs(w_hltb)) or 1.0
                    def sig(w_raw, score, unknown_val=0.5):
                        # Apply signal: direction flips score if negative.
                        # unknown_val controls contribution when score is None (missing data).
                        if w_raw == 0:
                            return 0.0
                        s = unknown_val if score is None else score
                        norm = abs(w_raw) / total_w
                        return norm * s if w_raw > 0 else norm * (1.0 - s)
                    final = (sig(w_tags, sim) + sig(w_review, rev, unknown_val=0.1) + sig(w_staleness, stal)
                             + sig(w_recency, rec, unknown_val=0.1) + sig(w_hltb, hltb, unknown_val=0.1))
                else:
                    final = 0.65 * sim + 0.35 * (rev if rev is not None else 0.1)

                return final, sim, matched

            has_bounds = any(b is not None for b in [b_review, b_staleness, b_recency, b_hltb])
            if has_bounds:
                bounded_pool_size = sum(1 for g in games if score_game(g) is not None)
            remaining = list(games)
            for _ in range(min(NUM_PICKS, len(remaining))):
                scored = []
                for g in remaining:
                    result = score_game(g)
                    if result is not None:
                        scored.append((result, g))
                this_relaxed = False
                if not scored and has_bounds:
                    for step in range(1, 21):
                        f = step * 0.05
                        scored = []
                        for g in remaining:
                            result = score_game(g, relax_factor=f)
                            if result is not None:
                                scored.append((result, g))
                        if scored:
                            this_relaxed = True
                            any_relaxed = True
                            break
                if not scored:
                    break
                total  = sum(s[0] for s, _ in scored)

                if total == 0:
                    game = random.choice([g for _, g in scored])
                    final, sim, matched = 0.0, 0.0, []
                else:
                    r          = random.random() * total
                    cumulative = 0.0
                    game       = scored[-1][1]
                    final, sim, matched = scored[-1][0]
                    for (f, s, m), g in scored:
                        cumulative += f
                        if r <= cumulative:
                            game, final, sim, matched = g, f, s, m
                            break

                rev = review_score(game)
                cs  = game.get('completion_status', '')
                profile_desc = "your most-played games" if using_fallback else "games you've beaten"

                # Determine factor order: weighted mode uses slider values; smart uses fixed weights.
                if mode == 'weighted':
                    factor_order = sorted([
                        ('tags', w_tags), ('review', w_review), ('staleness', w_staleness),
                        ('recency', w_recency), ('hltb', w_hltb),
                    ], key=lambda x: abs(x[1]), reverse=True)
                else:
                    factor_order = [('tags', 65.0), ('review', 35.0)]

                from datetime import datetime, timezone as _tz
                phrases = []
                for _key, _w in factor_order:
                    if _w == 0 or len(phrases) >= 3:
                        continue
                    _p = None
                    if _key == 'tags':
                        if _w > 0 and matched:
                            _p = f"matches {profile_desc} on {', '.join(matched[:3])}"
                    elif _key == 'review':
                        if rev is not None:
                            _pct = int(rev * 100)
                            _p = f"well reviewed ({_pct}%)" if _w > 0 else f"low-reviewed ({_pct}%)"
                    elif _key == 'staleness':
                        _lp = game.get('last_played')
                        if _lp:
                            _days = (datetime.now(_tz.utc).timestamp() - float(_lp)) / 86400
                            if _w > 0:
                                if _days >= 365:
                                    _p = f"last played {_days / 365:.0f}yr ago"
                                elif _days >= 30:
                                    _p = f"last played {int(_days / 30)}mo ago"
                                else:
                                    _p = f"last played {int(_days)}d ago"
                        elif _w > 0:
                            _p = "never played"
                    elif _key == 'recency':
                        _rd = game.get('release_date')
                        if _rd:
                            try:
                                _year = datetime.fromtimestamp(float(_rd), tz=_tz.utc).year
                                _p = f"{_year} release"
                            except Exception:
                                pass
                    elif _key == 'hltb':
                        _times = [v for v in [game.get('hltb_main'), game.get('hltb_extras'),
                                              game.get('hltb_completionist')] if v]
                        if _times:
                            _hrs = round((max(_times) if _w > 0 else min(_times)) / 60)
                            _p = f"~{_hrs}h to beat"
                    if _p:
                        phrases.append(_p)

                if phrases:
                    reason = '; '.join(phrases).capitalize() + '.'
                elif rev is not None:
                    reason = f"Solid reviews ({int(rev * 100)}%)."
                else:
                    reason = "Picked based on your library."

                if cs == 'Unfinished':
                    reason += " You've started this one before."

                picks.append({"game": game, "reason": reason, "bounds_relaxed": this_relaxed})
                remaining = [g for g in remaining if g['appid'] != game['appid']]

        else:
            db.close()
            for g in random.sample(games, min(NUM_PICKS, len(games))):
                picks.append({"game": g, "reason": None})

        from library import _compute_outline_colors
        _outlines_cfg = state.get('card_outlines', {})
        pick_games = [p['game'] for p in picks]
        outline_map = _compute_outline_colors(pick_games, state) if _outlines_cfg.get('enabled', {}).get('pick6', True) else {}
        for p in picks:
            p['outline_color'] = outline_map.get(str(p['game']['appid']))

        return jsonify({
            "status":                "success",
            "picks":                 picks,
            "pool_size":             len(games),
            "bounded_pool_size":     bounded_pool_size,
            "bounds_relaxed":        any_relaxed,
        })

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

    @app.route('/update-installed')
    def update_installed():
        try:
            count = sync_local_install_status()
            return jsonify({"status": "success", "count": count})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/open-url', methods=['POST'])
    def open_url_route():
        url = (request.json or {}).get('url', '')
        if not url:
            return jsonify({"status": "error", "message": "No URL provided"}), 400
        if not (url.startswith('http://') or url.startswith('https://') or url.startswith('steam://')):
            return jsonify({"status": "error", "message": "Scheme not allowed"}), 400
        try:
            os_name = platform.system()
            if os_name == 'Darwin':
                subprocess.Popen(['open', url])
            elif os_name == 'Linux':
                subprocess.Popen(['xdg-open', url])
            else:
                subprocess.Popen(['cmd', '/c', 'start', '', url])
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/launch/<appid>', methods=['POST'])
    def launch_game(appid):
        try:
            appid_int = int(appid)
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid appid"}), 400

        os_name = platform.system()

        # Look up platform and install status for this game
        db = get_db()
        row = db.execute(
            "SELECT name, platform, platform_id, installed FROM games WHERE appid = ?", (appid_int,)
        ).fetchone()
        db.close()
        game_name     = row['name'] if row else ''
        game_platform = (row['platform'] or 'steam') if row else 'steam'
        platform_id   = row['platform_id'] if row else None
        is_installed  = bool(row['installed']) if row else False

        if game_platform == 'steam':
            # Steam launch via steam:// URI (handles install too if not installed)
            url = f'steam://run/{appid_int}'
            try:
                if os_name == 'Darwin':
                    subprocess.Popen(['open', url])
                elif os_name == 'Linux':
                    subprocess.Popen(['xdg-open', url])
                elif os_name == 'Windows':
                    subprocess.Popen(['cmd', '/c', 'start', '', url])
                log.info(f"Launched Steam appid {appid_int}")
            except Exception as e:
                log.error(f"Failed to launch Steam appid {appid_int}: {e}")
        else:
            import plugins as _plugin_registry
            plugin_obj = next(
                (p for p in _plugin_registry.loaded().values() if p.platform == game_platform),
                None,
            )
            if plugin_obj and hasattr(plugin_obj, 'launch_game'):
                result = plugin_obj.launch_game(appid_int)
                return jsonify(result)
            return jsonify({"status": "not_supported",
                            "message": "Launch not yet supported for this platform"}), 501

        # Record the launch date only if the game is marked installed
        new_ts = record_launch(appid_int)
        if new_ts:
            from database import ts_to_date
            return jsonify({"status": "success", "last_played": ts_to_date(new_ts)})
        else:
            return jsonify({"status": "launched", "message": "Game launched but not marked installed — date not updated"})

    @app.route('/api/game-running')
    def game_running():
        """
        Check whether a Steam game is currently running.
        Uses Steam's 'reaper' process wrapper, which is present for all Steam game
        launches on Linux (Proton and native). Returns {'running': bool} on Linux,
        {'running': null} on other platforms (caller should fall back to focus events).
        """
        if platform.system() != 'Linux':
            return jsonify({'running': None})
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'reaper SteamLaunch'],
                capture_output=True, timeout=3
            )
            return jsonify({'running': result.returncode == 0})
        except Exception:
            return jsonify({'running': None})

    @app.route('/api/raise-window', methods=['POST'])
    def raise_window_route():
        """Raise and focus the PlayDate window via GTK (Linux only)."""
        try:
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk, GLib
            for win in Gtk.Window.list_toplevels():
                GLib.idle_add(win.present)
        except Exception:
            pass
        return jsonify({'ok': True})

    @app.route('/api/scrape_single/<int:appid>', methods=['GET', 'POST'])
    def scrape_single(appid):
        from scrapers import fetch_store_data, fetch_tag_data, fetch_player_data, fetch_review_data, fetch_cheevo_data
        from utils import fetch_local_library, get_acf_names, parse_appinfo
        from config import load_config as _load_config, get_active_account as _get_active_account
        _cfg     = _load_config() or {}
        _account = _get_active_account() or {}

        player_data = fetch_player_data(appid) or {}
        store_data  = fetch_store_data(appid) or {}
        review_data = fetch_review_data(appid) or {}
        cheevo_data = fetch_cheevo_data(appid) or {} if _account.get('api_key') else {}
        tag_data    = fetch_tag_data(appid) or {}

        data_out = {
            "developers":             store_data.get('developers', ''),
            "publishers":             store_data.get('publishers', ''),
            "release_date":           store_data.get('release_date', ''),
            "genres":                 store_data.get('genres', ''),
            "categories":             store_data.get('categories', ''),
            "is_free":                store_data.get('is_free', 0),
            "review_score":           review_data.get('review_score', ''),
            "review_percentage":      review_data.get('review_percentage', ''),
            "weighted_percentage":    review_data.get('weighted_percentage', ''),
            "total_reviews":          review_data.get('total_reviews', ''),
            "positive_reviews":       review_data.get('positive_reviews', ''),
            "total_achievements":     cheevo_data.get('total_achievements', 0),
            "unlocked_achievements":  cheevo_data.get('unlocked_achievements', 0),
            "tags":                   tag_data.get('tags', '')
        }

        # Playtime, last_played, name: prefer API, fall back to local Steam files
        local_entry = next((g for g in fetch_local_library(_cfg.get('steam_id')) if g['appid'] == appid), None)

        playtime   = player_data.get('playtime_forever')
        last_played = player_data.get('last_played') or None
        name        = player_data.get('name') or None

        if playtime is None and local_entry:
            playtime = local_entry.get('playtime_forever')
        if not last_played and local_entry:
            lp = local_entry.get('last_played', '0')
            last_played = lp if lp and lp != '0' else None
        if not name:
            name = get_acf_names().get(appid) or parse_appinfo().get(appid, {}).get('name') or None

        if playtime is not None:
            data_out['playtime_forever'] = playtime
        if last_played:
            data_out['last_played'] = last_played
        if name:
            data_out['name'] = name

        # Convert timestamps to date strings for the frontend form
        from database import ts_to_date
        for col in ('last_played', 'release_date'):
            if data_out.get(col) is not None:
                data_out[col] = ts_to_date(data_out[col]) or ''

        return jsonify({"status": "success", "data": data_out})

    @app.route('/api/download-artwork/<int:appid>', methods=['POST'])
    def download_artwork(appid):
        from images import download_from_url
        data        = request.json or {}
        url         = data.get('url', '').strip()
        orientation = data.get('orientation', 'vertical')
        if not url:
            return jsonify({"status": "error", "message": "No URL provided"}), 400
        if orientation not in ('vertical', 'horizontal', 'icon'):
            return jsonify({"status": "error", "message": "Invalid orientation"}), 400
        result = download_from_url(appid, url, orientation)
        if result == 'custom':
            col_map = {
                'vertical':   'vertical_art_source',
                'horizontal': 'horizontal_art_source',
                'icon':       'icon_source',
            }
            sgdb_source_map = {
                'vertical':   'sgdb_grid',
                'horizontal': 'sgdb_grid_wide',
                'icon':       'sgdb_icon',
            }
            _u = urlparse(url)
            source = sgdb_source_map[orientation] if (_u.hostname and (_u.hostname == 'steamgriddb.com' or _u.hostname.endswith('.steamgriddb.com'))) else 'custom'
            update_game_data(appid, **{col_map[orientation]: source})
            return jsonify({"status": "success", "source": source})
        return jsonify({"status": "error", "message": "Failed to download image. Check the URL and try again."}), 500

    @app.route('/api/sgdb-options/<int:appid>/<artwork_type>')
    def sgdb_options(appid, artwork_type):
        from images import fetch_sgdb_options
        if artwork_type not in ('vertical', 'horizontal', 'icon'):
            return jsonify({"status": "error", "message": "Invalid artwork type"}), 400
        options = fetch_sgdb_options(appid, artwork_type)
        return jsonify({"status": "success", "options": options})

    @app.route('/api/sgdb-search')
    def sgdb_search():
        from images import search_sgdb_games
        term = request.args.get('term', '').strip()
        if not term:
            return jsonify({"status": "error", "message": "No search term"}), 400
        results = search_sgdb_games(term)
        return jsonify({"status": "success", "results": results})

    @app.route('/api/sgdb-options-by-id/<int:sgdb_id>/<artwork_type>')
    def sgdb_options_by_id(sgdb_id, artwork_type):
        from images import fetch_sgdb_options_by_id
        if artwork_type not in ('vertical', 'horizontal', 'icon'):
            return jsonify({"status": "error", "message": "Invalid artwork type"}), 400
        options = fetch_sgdb_options_by_id(sgdb_id, artwork_type)
        return jsonify({"status": "success", "options": options})

    @app.route('/api/artwork/save-sgdb', methods=['POST'])
    def save_sgdb_artwork(appid=None):
        from images import download_from_url
        data        = request.json or {}
        appid       = data.get('appid')
        url         = data.get('url', '').strip()
        orientation = data.get('orientation')
        if not appid or not url or orientation not in ('vertical', 'horizontal', 'icon'):
            return jsonify({"status": "error", "message": "Missing or invalid parameters"}), 400
        col_map = {
            'vertical':   'vertical_art_source',
            'horizontal': 'horizontal_art_source',
            'icon':       'icon_source',
        }
        source_map = {
            'vertical':   'sgdb_grid',
            'horizontal': 'sgdb_grid_wide',
            'icon':       'sgdb_icon',
        }
        result = download_from_url(int(appid), url, orientation)
        if result == 'custom':
            update_game_data(int(appid), **{col_map[orientation]: source_map[orientation]})
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": "Failed to download image."}), 500

    @app.route('/api/artwork/rescrape', methods=['POST'])
    def rescrape_artwork():
        from images import download_vertical, download_horizontal, download_icon
        from datetime import datetime
        data        = request.json or {}
        appid       = data.get('appid')
        orientation = data.get('orientation')
        if not appid or orientation not in ('vertical', 'horizontal', 'icon'):
            return jsonify({"status": "error", "message": "Missing or invalid parameters"}), 400
        appid = int(appid)
        today = datetime.now().strftime('%Y-%m-%d')
        if orientation == 'vertical':
            source = download_vertical(appid)
            update_game_data(appid, vertical_art_source=source, art_fetched=today)
        elif orientation == 'horizontal':
            source = download_horizontal(appid)
            update_game_data(appid, horizontal_art_source=source, art_fetched=today)
        else:
            db  = get_db()
            row = db.execute("SELECT icon_hash FROM games WHERE appid = ?", (appid,)).fetchone()
            db.close()
            icon_hash = row['icon_hash'] if row else None
            source = download_icon(appid, icon_hash)
            update_game_data(appid, icon_source=source, art_fetched=today)
        return jsonify({"status": "success", "source": source})

    @app.route('/api/protondb/<int:appid>', methods=['POST'])
    def rescrape_protondb(appid):
        from scrapers import fetch_protondb_data
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        info  = fetch_protondb_data(appid)
        game_data = {'protondb_fetched': today}
        if info:
            game_data.update(info)
        else:
            game_data['protondb_tier']       = None
            game_data['protondb_confidence'] = None
        update_game_data(appid, **game_data)
        return jsonify({'status': 'success', 'tier': info.get('protondb_tier') if info else None,
                        'confidence': info.get('protondb_confidence') if info else None})

    @app.route('/api/hltb/matches', methods=['GET'])
    def hltb_matches():
        db   = get_db()
        rows = db.execute("""
            SELECT appid, name, hltb_id, hltb_matched_name, hltb_match_score,
                   hltb_main, hltb_extras, hltb_completionist, hltb_fetched
            FROM games
            WHERE hltb_id IS NOT NULL
            ORDER BY name COLLATE NOCASE
        """).fetchall()
        no_match_rows = db.execute(
            "SELECT appid, name FROM games WHERE hltb_fetched = 'no_match' ORDER BY name COLLATE NOCASE"
        ).fetchall()
        unfetched = db.execute(
            "SELECT COUNT(*) FROM games WHERE hltb_fetched = '0' OR hltb_fetched IS NULL"
        ).fetchone()[0]
        db.close()
        return jsonify({
            'matches':        [dict(r) for r in rows],
            'no_match_games': [dict(r) for r in no_match_rows],
            'unfetched_count': unfetched,
        })

    @app.route('/api/hltb/<int:appid>/search', methods=['GET'])
    def hltb_search(appid):
        from scrapers import search_hltb_results
        db  = get_db()
        row = db.execute("SELECT name FROM games WHERE appid=?", (appid,)).fetchone()
        db.close()
        if not row:
            return jsonify({'status': 'error', 'message': 'Game not found'}), 404
        name = request.args.get('q', '').strip() or row['name']
        results = search_hltb_results(name)
        return jsonify({'status': 'success', 'results': results})

    @app.route('/api/hltb/<int:appid>/select', methods=['POST'])
    def select_hltb(appid):
        data     = request.json or {}
        hltb_id  = data.get('hltb_id')
        if not hltb_id:
            return jsonify({'status': 'error', 'message': 'hltb_id required'}), 400
        from scrapers import fetch_hltb_by_id
        from datetime import datetime
        db  = get_db()
        row = db.execute("SELECT name FROM games WHERE appid=?", (appid,)).fetchone()
        db.close()
        if not row:
            return jsonify({'status': 'error', 'message': 'Game not found'}), 404
        today  = datetime.now().strftime('%Y-%m-%d')
        result = fetch_hltb_by_id(row['name'], hltb_id)
        if result is None:
            return jsonify({'status': 'error', 'message': 'Could not reach HLTB'}), 500
        times_available = result.pop('times_available', True)
        score = data.get('hltb_match_score')
        if times_available:
            update_game_data(appid, hltb_fetched=today, hltb_id=hltb_id,
                             hltb_match_score=score, **result)
            return jsonify({'status': 'success', 'times_available': True,
                            'data': {**result, 'hltb_id': hltb_id,
                                     'hltb_match_score': score, 'hltb_fetched': today}})
        else:
            # ID exists in HLTB DB but times couldn't be retrieved — don't confirm
            return jsonify({'status': 'error', 'message': 'Could not fetch times for this ID'}), 500

    @app.route('/api/hltb/<int:appid>', methods=['POST'])
    def rescrape_hltb(appid):
        from scrapers import fetch_hltb_data
        from config import load_state
        db   = get_db()
        row  = db.execute("SELECT name FROM games WHERE appid=?", (appid,)).fetchone()
        db.close()
        if not row:
            return jsonify({'status': 'error', 'message': 'Game not found'}), 404
        threshold = load_state().get('hltb_match_threshold', 75)
        info = fetch_hltb_data(row['name'], threshold=threshold)
        if info:
            update_game_data(appid, **info)
        else:
            update_game_data(appid, hltb_fetched='no_match', hltb_id=None,
                             hltb_main=None, hltb_extras=None,
                             hltb_completionist=None, hltb_match_score=None)
        return jsonify({'status': 'success', 'data': info})

    @app.route('/api/hltb/<int:appid>/confirm', methods=['POST'])
    def confirm_hltb(appid):
        from scrapers import fetch_hltb_by_id
        from datetime import datetime
        db  = get_db()
        row = db.execute("SELECT name, hltb_id FROM games WHERE appid=?", (appid,)).fetchone()
        db.close()
        if not row:
            return jsonify({'status': 'error', 'message': 'Game not found'}), 404
        today  = datetime.now().strftime('%Y-%m-%d')
        result = fetch_hltb_by_id(row['name'], row['hltb_id']) if row['hltb_id'] else None
        if result is None:
            return jsonify({'status': 'error', 'message': 'No HLTB ID stored'}), 400
        times_available = result.pop('times_available', True)
        if times_available:
            update_game_data(appid, hltb_fetched=today, **result)
            return jsonify({'status': 'success', 'data': {**result, 'hltb_fetched': today}})
        else:
            # ID lookup failed — clear to no_match so the game surfaces in the review tab
            cleared = {'hltb_fetched': 'no_match', 'hltb_id': None,
                       'hltb_matched_name': None, 'hltb_match_score': None,
                       'hltb_main': None, 'hltb_extras': None, 'hltb_completionist': None}
            update_game_data(appid, **cleared)
            return jsonify({'status': 'success', 'data': cleared})

    @app.route('/api/hltb/<int:appid>', methods=['DELETE'])
    def delete_hltb(appid):
        update_game_data(appid, hltb_fetched='0', hltb_id=None, hltb_main=None,
                         hltb_extras=None, hltb_completionist=None, hltb_match_score=None)
        return jsonify({'status': 'success'})

    @app.route('/api/set-background', methods=['POST'])
    def set_background():
        if 'background' not in request.files:
            return jsonify({"status": "error", "message": "No file uploaded."}), 400
        f = request.files['background']
        if not f.filename:
            return jsonify({"status": "error", "message": "Empty filename."}), 400
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
            return jsonify({"status": "error", "message": "Unsupported format. Use JPG, PNG, or WebP."}), 400
        try:
            bg_dir  = os.path.join(BASE_DIR, 'static', 'img', 'backgrounds')
            os.makedirs(bg_dir, exist_ok=True)
            bg_path = os.path.join(bg_dir, 'background.jpg')
            # Convert/copy via Pillow so we always write a JPEG regardless of input format
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(f.read())).convert('RGB')
            img.save(bg_path, 'JPEG', quality=92)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/reset-background', methods=['POST'])
    def reset_background():
        try:
            os.remove(os.path.join(BASE_DIR, 'static', 'img', 'backgrounds', 'background.jpg'))
        except FileNotFoundError:
            pass
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        return jsonify({"status": "success"})

    @app.route('/api/pending-date', methods=['POST', 'OPTIONS'])
    def pending_date_set():
        if request.method == 'OPTIONS':
            return ('', 204)
        origin = request.headers.get('Origin', '')
        _o = urlparse(origin)
        if origin and not (_o.scheme == 'https' and _o.hostname == 'help.steampowered.com'):
            return jsonify({'status': 'error', 'message': 'Forbidden'}), 403
        data  = request.json or {}
        appid = data.get('appid')
        date  = data.get('date', '').strip()
        if not appid or not date:
            return jsonify({'status': 'error', 'message': 'Missing appid or date'}), 400
        _pending_dates[int(appid)] = date
        log.info(f"Pending date set for AppID {appid}: {date}")
        return jsonify({'status': 'success'})

    @app.route('/api/pending-date/<int:appid>')
    def pending_date_get(appid):
        log.info(f"Pending date poll for AppID {appid} — stored keys: {list(_pending_dates.keys())}")
        date = _pending_dates.pop(appid, None)
        if date:
            log.info(f"Pending date consumed for AppID {appid}: {date}")
            return jsonify({'status': 'success', 'date': date})
        return jsonify({'status': 'none'})

    @app.route('/api/pending-date/<int:appid>/peek')
    def pending_date_peek(appid):
        return jsonify({'pending': appid in _pending_dates})

    @app.route('/api/active-steam-id')
    def active_steam_id():
        from config import get_active_account
        account = get_active_account() or {}
        return jsonify({'steam_id': account.get('steam_id', '')})

    @app.route('/api/install-changed')
    def install_changed():
        from utils import consume_install_dirty
        if not consume_install_dirty():
            return jsonify({'changed': False})
        db = get_db()
        rows = db.execute("SELECT appid FROM games WHERE installed = 1").fetchall()
        db.close()
        return jsonify({'changed': True, 'installed_appids': [r['appid'] for r in rows]})

    # ── Bulk date import ──────────────────────────────────────────────────────

    @app.route('/api/bulk-date-import/start', methods=['POST'])
    def bulk_date_import_start():
        data   = request.json or {}
        scope  = data.get('scope', 'selected')
        appids = data.get('appids', [])
        db  = get_db()
        if scope == 'all':
            rows = db.execute('SELECT appid, name, platform FROM games ORDER BY name').fetchall()
        elif appids:
            ph   = ','.join('?' * len(appids))
            rows = db.execute(f'SELECT appid, name, platform FROM games WHERE appid IN ({ph})', appids).fetchall()
        else:
            db.close()
            return jsonify({'status': 'error', 'message': 'No games provided.'}), 400
        db.close()

        import plugins as _plugins
        # Steam games go through the per-page Help flow; plugins with date_import_url
        # (e.g. GOG) are handled via their external orders page + Tampermonkey script.
        steam_rows = [r for r in rows if (r['platform'] or 'steam') == 'steam']

        seen_urls      = set()
        date_import_urls = []
        for r in rows:
            plat   = r['platform'] or 'steam'
            plugin = _plugins.get(plat)
            if plugin and hasattr(plugin, 'date_import_url'):
                url = plugin.date_import_url
                if url not in seen_urls:
                    seen_urls.add(url)
                    date_import_urls.append({'url': url, 'label': getattr(plugin, 'label', plugin.name)})

        queue = [{'appid': r['appid'], 'name': r['name']} for r in steam_rows]
        if queue:
            _bulk_date_state.update({'queue': queue[1:], 'current': queue[0],
                                     'done': 0, 'failed': 0, 'total': len(queue),
                                     'active': True, 'script_connected': False,
                                     'results': []})
            log.info(f"Bulk date import started: {len(queue)} Steam games queued")

        return jsonify({
            'status':           'ok',
            'first_appid':      queue[0]['appid'] if queue else None,
            'first_name':       queue[0]['name']  if queue else None,
            'total':            len(queue),
            'date_import_urls': date_import_urls,
        })

    def _bulk_date_advance():
        if _bulk_date_state['queue']:
            nxt = _bulk_date_state['queue'].pop(0)
            _bulk_date_state['current'] = nxt
            return jsonify({'status': 'ok', 'next_appid': nxt['appid'], 'next_name': nxt['name']})
        _bulk_date_state.update({'active': False, 'current': None})
        log.info(f"Bulk date import finished: {_bulk_date_state['done']} updated, {_bulk_date_state['failed']} not found")
        return jsonify({'status': 'ok', 'next_appid': None})

    @app.route('/api/bulk-date-import/submit', methods=['POST', 'OPTIONS'])
    def bulk_date_import_submit():
        if request.method == 'OPTIONS':
            return ('', 204)
        data  = request.json or {}
        appid = int(data.get('appid', 0))
        date  = data.get('date', '').strip()
        if not appid or not date:
            return jsonify({'status': 'error', 'message': 'Missing appid or date'}), 400
        from database import date_to_ts
        current = _bulk_date_state.get('current') or {}
        update_game_data(appid, date_added=date_to_ts(date))
        log.info(f"Bulk date import: saved {date} for AppID {appid}")
        _bulk_date_state['done'] += 1
        _bulk_date_state['results'].insert(0, {'appid': appid, 'name': current.get('name', ''), 'date': date})
        return _bulk_date_advance()

    @app.route('/api/bulk-date-import/skip', methods=['POST', 'OPTIONS'])
    def bulk_date_import_skip():
        if request.method == 'OPTIONS':
            return ('', 204)
        data  = request.json or {}
        appid = int(data.get('appid', 0))
        current = _bulk_date_state.get('current') or {}
        log.info(f"Bulk date import: no date found for AppID {appid}")
        _bulk_date_state['failed'] += 1
        _bulk_date_state['results'].insert(0, {'appid': appid, 'name': current.get('name', ''), 'date': None})
        return _bulk_date_advance()

    @app.route('/api/bulk-date-import/ping', methods=['POST', 'OPTIONS'])
    def bulk_date_import_ping():
        if request.method == 'OPTIONS':
            return ('', 204)
        _bulk_date_state['script_connected'] = True
        return jsonify({'status': 'ok'})

    @app.route('/api/bulk-date-import/status')
    def bulk_date_import_status():
        s = _bulk_date_state
        return jsonify({
            'active': s['active'], 'done': s['done'], 'failed': s['failed'],
            'total': s['total'], 'current': s['current'],
            'script_connected': s['script_connected'],
            'results': s['results'][:50],
        })

    @app.route('/api/bulk-date-import/cancel', methods=['POST'])
    def bulk_date_import_cancel():
        _bulk_date_state.update({'queue': [], 'active': False, 'current': None, 'script_connected': False})
        log.info("Bulk date import cancelled")
        return jsonify({'status': 'ok'})

    @app.route('/api/games/search')
    def search_games():
        q        = request.args.get('q', '').strip()
        platform = request.args.get('platform', '')
        if not q:
            return jsonify([])
        try:
            db = get_db()
            if platform:
                rows = db.execute(
                    "SELECT appid, name, platform FROM games WHERE name LIKE ? AND platform = ? "
                    "ORDER BY name LIMIT 20",
                    (f'%{q}%', platform)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT appid, name, platform FROM games WHERE name LIKE ? ORDER BY name LIMIT 20",
                    (f'%{q}%',)
                ).fetchall()
            db.close()
            return jsonify([dict(r) for r in rows])
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/game/<int:appid>/set-duplicate', methods=['POST'])
    def set_duplicate(appid):
        """Set or clear the duplicate_of field for a game."""
        data         = request.json or {}
        duplicate_of = data.get('duplicate_of')   # appid string, or null/'' to clear
        try:
            db = get_db()
            db.execute(
                "UPDATE games SET duplicate_of = ?, duplicate_auto = 0 WHERE appid = ?",
                (str(duplicate_of) if duplicate_of else None, appid)
            )
            db.commit()
            db.close()
            return jsonify({'status': 'ok'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/game/<int:appid>')
    def get_game(appid):
        try:
            from database import ts_to_date
            db  = get_db()
            row = db.execute("SELECT * FROM games WHERE appid = ?", (appid,)).fetchone()
            db.close()
            if row:
                game = dict(row)
                for col in ('last_played', 'date_added', 'release_date'):
                    if game.get(col):
                        game[col] = ts_to_date(game[col])
                return jsonify({"status": "success", "game": game})
            return jsonify({"status": "error", "message": "Game not found"}), 404
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/game-description/<int:appid>')
    def game_description(appid):
        import plugins as _plugins
        import requests as _r
        db = get_db()
        row = db.execute("SELECT platform, platform_id FROM games WHERE appid = ?", (appid,)).fetchone()
        db.close()
        if not row:
            return jsonify({'status': 'error', 'message': 'Game not found'}), 404
        platform = row['platform'] or 'steam'
        try:
            plugin = _plugins.get(platform)
            if plugin is not None and hasattr(plugin, 'fetch_description'):
                desc = plugin.fetch_description(appid, row['platform_id'])
                if desc:
                    return jsonify({'status': 'success', 'description': desc})
            else:
                resp = _r.get(
                    f'https://store.steampowered.com/api/appdetails?appids={appid}',
                    timeout=10
                )
                if resp.ok:
                    d = resp.json()
                    app_data = d.get(str(appid), {})
                    if app_data.get('success'):
                        desc = app_data.get('data', {}).get('short_description', '')
                        return jsonify({'status': 'success', 'description': desc})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500
        return jsonify({'status': 'error', 'message': 'No description available'})

    @app.route('/api/set-completion/<int:appid>', methods=['POST'])
    def set_completion(appid):
        status = (request.json or {}).get('status', '').strip()
        allowed = {'Never Played', 'Unfinished', 'Beaten', 'Completed', "Won't Play"}
        if status not in allowed:
            return jsonify({"status": "error", "message": f"Invalid status: {status!r}"}), 400
        try:
            update_game_data(appid, completion_status=status)
            return jsonify({"status": "success", "completion_status": status})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/bulk-op/start', methods=['POST'])
    def bulk_op_start():
        if _bulk_op_state['running']:
            return jsonify({'status': 'error', 'message': 'Already running'}), 400

        data   = request.json or {}
        op     = data.get('op')            # 'rescrape' or 'art'
        scope  = data.get('scope', 'filtered')
        appids = data.get('appids', [])
        types  = data.get('types', ['vertical', 'horizontal', 'icon'])
        source = data.get('source', 'auto')

        if op not in ('rescrape', 'art', 'protondb', 'hltb'):
            return jsonify({'status': 'error', 'message': 'Invalid op'}), 400

        if scope == 'all':
            db     = get_db()
            rows   = db.execute("SELECT appid FROM games").fetchall()
            db.close()
            appids = [r['appid'] for r in rows]
        elif scope == 'no_match' and op == 'hltb':
            db     = get_db()
            rows   = db.execute("SELECT appid FROM games WHERE hltb_fetched = 'no_match'").fetchall()
            db.close()
            appids = [r['appid'] for r in rows]

        appids = [int(a) for a in appids]
        if not appids:
            return jsonify({'status': 'error', 'message': 'No games to process'}), 400

        _bulk_op_cancel.clear()
        with _bulk_op_lock:
            _bulk_op_state.update(running=True, op=op, total=len(appids),
                                  done=0, failed=0, rate_limit_hit=False,
                                  aborted=False, result=None)

        def _progress(event, _data, _total):
            with _bulk_op_lock:
                if event == 'done':
                    _bulk_op_state['done'] += 1
                elif event == 'failed':
                    _bulk_op_state['failed'] += 1
                elif event == 'rate_limit':
                    _bulk_op_state['rate_limit_hit'] = True

        def _run():
            from scrapers import bulk_rescrape_games, bulk_art_scrape_games, bulk_protondb_scrape_games, bulk_hltb_scrape_games
            try:
                if op == 'rescrape':
                    result = bulk_rescrape_games(appids, _bulk_op_cancel, _progress)
                elif op == 'art':
                    result = bulk_art_scrape_games(appids, types, source, _bulk_op_cancel, _progress)
                elif op == 'protondb':
                    result = bulk_protondb_scrape_games(appids, _bulk_op_cancel, _progress)
                else:
                    result = bulk_hltb_scrape_games(appids, _bulk_op_cancel, _progress)
                with _bulk_op_lock:
                    _bulk_op_state['result']  = result
                    _bulk_op_state['aborted'] = result.get('aborted', False)
            except Exception as e:
                log.exception(f"bulk_op_start ({op}): {e}")
                with _bulk_op_lock:
                    _bulk_op_state['result'] = {'error': str(e)}
            finally:
                with _bulk_op_lock:
                    _bulk_op_state['running'] = False

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({'status': 'success', 'total': len(appids)})

    @app.route('/api/bulk-op/status', methods=['GET'])
    def bulk_op_status():
        with _bulk_op_lock:
            return jsonify(dict(_bulk_op_state))

    @app.route('/api/bulk-op/cancel', methods=['POST'])
    def bulk_op_cancel_route():
        _bulk_op_cancel.set()
        return jsonify({'status': 'success'})

    @app.route('/api/shuffle-shelf/<shelf_id>')
    def shuffle_shelf(shelf_id):
        try:
            from database import get_db
            from config import load_state, BUILTIN_FILTERS
            state = load_state()
            shelves = state.get('shelves', [])
            shelf = next((s for s in shelves if s['id'] == shelf_id), None)
            if not shelf:
                return jsonify({'status': 'error', 'message': 'Shelf not found'}), 404

            # Resolve WHERE clause
            custom = (shelf.get('custom_sql') or '').strip()
            filter_key = shelf.get('filter_key') or shelf.get('preset', 'all_games')
            saved_filters = state.get('saved_filters', {})

            if custom:
                import re
                where = re.sub(r'\s*\bORDER\s+BY\s+.+$', '', custom, flags=re.IGNORECASE).strip()
                where = re.sub(r'(?i)^\s*WHERE\s+', '', where).strip() or '1=1'
            elif filter_key in BUILTIN_FILTERS and BUILTIN_FILTERS[filter_key]['where']:
                where = BUILTIN_FILTERS[filter_key]['where']
            elif filter_key in saved_filters:
                from index import _filter_tree_to_sql
                sf = saved_filters[filter_key]
                where = _filter_tree_to_sql(sf['tree'] if isinstance(sf, dict) and 'tree' in sf else sf)
            else:
                where = '1=1'

            limit = shelf.get('limit', 10)
            db = get_db()
            rows = db.execute(
                f"SELECT appid, name, installed, completion_status FROM games "
                f"WHERE {where} ORDER BY RANDOM() LIMIT ?",
                (limit,)
            ).fetchall()
            db.close()
            games = [{'appid': r[0], 'name': r[1], 'installed': r[2] or 0, 'completion_status': r[3] or ''} for r in rows]
            from library import _compute_outline_colors
            _outlines_cfg = state.get('card_outlines', {})
            outline_map = (
                _compute_outline_colors(games, state)
                if _outlines_cfg.get('enabled', {}).get('home', True)
                else {}
            )
            for g in games:
                g['outline_color'] = outline_map.get(str(g['appid']))
            return jsonify({'status': 'success', 'games': games})
        except Exception as e:
            log.exception(f"shuffle_shelf error for {shelf_id}: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500


    @app.route('/api/refill-shelf/<shelf_id>', methods=['POST'])
    def refill_shelf(shelf_id):
        try:
            from database import get_db
            from config import load_state
            from index import _build_shelf_query
            data = request.json or {}
            exclude_appids = [int(a) for a in data.get('exclude_appids', [])]

            state = load_state()
            shelves = state.get('shelves', [])
            shelf = next((s for s in shelves if s['id'] == shelf_id), None)
            if not shelf:
                return jsonify({'status': 'error', 'message': 'Shelf not found'}), 404

            saved_filters = state.get('saved_filters', {})
            where, order = _build_shelf_query(shelf, saved_filters)
            if where is None:
                return jsonify({'status': 'success', 'games': []})

            limit = int(shelf.get('limit', 10))
            db = get_db()
            if exclude_appids:
                placeholders = ','.join('?' * len(exclude_appids))
                rows = db.execute(
                    f"SELECT appid, name, installed, completion_status, platform FROM games "
                    f"WHERE ({where}) AND appid NOT IN ({placeholders}) ORDER BY {order} LIMIT ?",
                    (*exclude_appids, limit)
                ).fetchall()
            else:
                rows = db.execute(
                    f"SELECT appid, name, installed, completion_status, platform FROM games "
                    f"WHERE {where} ORDER BY {order} LIMIT ?",
                    (limit,)
                ).fetchall()
            db.close()
            games = [{'appid': r[0], 'name': r[1], 'installed': r[2] or 0, 'completion_status': r[3] or '', 'platform': r[4] or 'steam'} for r in rows]
            return jsonify({'status': 'success', 'games': games})
        except Exception as e:
            log.exception(f"refill_shelf error for {shelf_id}: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/bulk-edit', methods=['POST'])
    def bulk_edit():
        from library import bulk_edit_games
        return bulk_edit_games(request.json)

    @app.route('/api/save-filter', methods=['POST'])
    def save_filter():
        from config import _state_lock, _load_state_unlocked, _write_state_atomic, _compact_tree_pv, _compact_appid_list_refs, _compact_shared_ids
        data = request.json
        name = (data.get('name') or '').strip()
        tree = data.get('filter_tree')
        if not name:
            return jsonify({"status": "error", "message": "Name cannot be empty."}), 400
        if not tree:
            return jsonify({"status": "error", "message": "No filter to save."}), 400
        tree = _compact_tree_pv(_compact_appid_list_refs(tree))
        with _state_lock:
            state = _load_state_unlocked()
            if 'saved_filters' not in state:
                state['saved_filters'] = {}
            existing = state['saved_filters'].get(name, {})
            existing_id = existing.get('id') if isinstance(existing, dict) else None
            import uuid as _uuid
            state['saved_filters'][name] = {
                'id': existing_id or str(_uuid.uuid4()),
                'tree': tree,
            }
            _compact_shared_ids(state)
            _write_state_atomic(state)
        return jsonify({"status": "success"})

    @app.route('/api/delete-filter', methods=['POST'])
    def delete_filter():
        from config import _state_lock, _load_state_unlocked, _write_state_atomic
        name = (request.json.get('name') or '').strip()
        if not name:
            return jsonify({"status": "error", "message": "Name required."}), 400
        with _state_lock:
            state = _load_state_unlocked()
            state.get('saved_filters', {}).pop(name, None)
            ft = state.get('filter_tree')
            if isinstance(ft, dict) and ft.get('saved_filter') == name:
                state['filter_tree'] = None
            _write_state_atomic(state)
        return jsonify({"status": "success"})

    @app.route('/api/rename-filter', methods=['POST'])
    def rename_filter():
        from config import _state_lock, _load_state_unlocked, _write_state_atomic
        old_name = (request.json.get('old_name') or '').strip()
        new_name = (request.json.get('new_name') or '').strip()
        if not old_name or not new_name:
            return jsonify({"status": "error", "message": "Both names required."}), 400
        with _state_lock:
            state = _load_state_unlocked()
            filters = state.get('saved_filters', {})
            if old_name not in filters:
                return jsonify({"status": "error", "message": "Filter not found."}), 404
            if new_name in filters:
                return jsonify({"status": "error", "message": f'A filter named "{new_name}" already exists.'}), 400
            filters[new_name] = filters.pop(old_name)
            state['saved_filters'] = filters
            ft = state.get('filter_tree')
            if isinstance(ft, dict) and ft.get('saved_filter') == old_name:
                state['filter_tree'] = {'saved_filter': new_name}
            _write_state_atomic(state)
        return jsonify({"status": "success"})

    @app.route('/api/card-outlines', methods=['GET'])
    def get_card_outlines():
        from config import load_state
        state = load_state()
        outlines = state.get('card_outlines', {})
        saved_filters = state.get('saved_filters', {})
        saved_list = [
            {'id': v['id'], 'name': k}
            for k, v in saved_filters.items()
            if isinstance(v, dict) and v.get('id')
        ]
        return jsonify({'status': 'success', 'card_outlines': outlines, 'saved_filters': saved_list})

    @app.route('/api/card-outlines', methods=['POST'])
    def save_card_outlines():
        from config import _state_lock, _load_state_unlocked, _write_state_atomic
        import uuid as _uuid
        data = request.json or {}
        outlines = data.get('card_outlines')
        if outlines is None:
            return jsonify({'status': 'error', 'message': 'Missing card_outlines'}), 400
        # Assign UUIDs to any new rules missing them
        for rule in outlines.get('rules', []):
            if not rule.get('id'):
                rule['id'] = str(_uuid.uuid4())
        with _state_lock:
            state = _load_state_unlocked()
            state['card_outlines'] = outlines
            _write_state_atomic(state)
        return jsonify({'status': 'success'})

    @app.route('/api/pick-screen-color')
    def pick_screen_color():
        """Fullscreen eyedropper overlay. Spawns color_picker.py as a subprocess
        so each invocation gets a clean Tk instance."""
        import subprocess, sys, os
        if getattr(sys, 'frozen', False):
            script = os.path.join(sys._MEIPASS, 'color_picker.py')
        else:
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'color_picker.py')
        app.logger.info('pick_screen_color: launching %s', script)
        try:
            r = subprocess.run([sys.executable, script],
                               capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            app.logger.warning('pick_screen_color: timed out')
            return jsonify({'cancelled': True})
        except Exception:
            app.logger.exception('pick_screen_color: subprocess error')
            return jsonify({'error': 'picker failed'}), 500
        app.logger.info('pick_screen_color: exit=%d stdout=%r stderr=%r',
                        r.returncode, r.stdout.strip(), r.stderr.strip()[:200])
        color = r.stdout.strip()
        if r.returncode == 0 and color:
            return jsonify({'color': color})
        return jsonify({'cancelled': True})

    @app.route('/api/export-filter', methods=['POST'])
    def export_filter_file():
        data = request.json
        path = _validate_user_path((data.get('path') or '').strip())
        name = (data.get('name') or '').strip()
        tree = data.get('tree')
        if not path or not name or not tree:
            return jsonify({'status': 'error', 'message': 'Missing fields.'}), 400
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'playdate_filter': {'name': name, 'tree': tree}}, f, indent=2)
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/read-filter-file', methods=['POST'])
    def read_filter_file():
        path = _validate_user_path((request.json.get('path') or '').strip())
        if not path or not os.path.exists(path):
            return jsonify({'status': 'error', 'message': 'File not found.'}), 400
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            pf   = data.get('playdate_filter', {})
            name = (pf.get('name') or '').strip()
            tree = pf.get('tree')
            if not name or not tree:
                return jsonify({'status': 'error', 'message': 'Invalid filter file.'}), 400
            return jsonify({'status': 'success', 'name': name, 'tree': tree})
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Could not read file: {e}'}), 500

    @app.route('/api/delete-game/<int:appid>', methods=['DELETE'])
    def delete_game(appid):
        data      = request.json or {}
        blacklist = data.get('blacklist', False)
        name      = data.get('name', '')
        try:
            # Look up platform_id before deleting (needed for non-Steam blacklist)
            db = get_db()
            row = db.execute(
                "SELECT platform_id FROM games WHERE appid = ?", (appid,)
            ).fetchone()
            platform_id = row['platform_id'] if row else None

            # Delete DB entry
            db.execute("DELETE FROM games WHERE appid = ?", (appid,))
            db.commit()
            db.close()

            # Delete all cached images
            safe_id = str(int(appid))
            for subdir in ('vertical', 'horizontal', 'icons'):
                img_path = os.path.join(BASE_DIR, 'static', 'img', 'library', subdir, safe_id + '.jpg')
                if os.path.exists(img_path):
                    os.remove(img_path)

            # Optionally blacklist
            if blacklist:
                add_to_blacklist(appid, name, platform_id=platform_id)

            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/bulk-delete', methods=['POST'])
    def bulk_delete():
        data    = request.json or {}
        appids  = data.get('appids', [])
        if not appids:
            return jsonify({"status": "error", "message": "No appids provided."}), 400
        try:
            placeholders = ','.join('?' * len(appids))
            db = get_db()
            db.execute(f"DELETE FROM games WHERE appid IN ({placeholders})", appids)
            db.commit()
            db.close()

            # Delete all cached images
            deleted_imgs = 0
            for appid in appids:
                safe_id = str(int(appid))
                for subdir in ('vertical', 'horizontal', 'icons'):
                    img_path = os.path.join(BASE_DIR, 'static', 'img', 'library', subdir, safe_id + '.jpg')
                    if os.path.exists(img_path):
                        os.remove(img_path)
                        deleted_imgs += 1

            return jsonify({"status": "success", "deleted": len(appids), "images_removed": deleted_imgs})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/blacklist', methods=['GET'])
    def blacklist_get():
        try:
            return jsonify({"status": "success", "entries": get_blacklist()})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/blacklist/add', methods=['POST'])
    def blacklist_add():
        data  = request.json or {}
        appid = data.get('appid')
        name  = data.get('name', '')
        if not appid:
            return jsonify({"status": "error", "message": "No appid provided."}), 400
        try:
            add_to_blacklist(appid, name)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/blacklist/remove', methods=['POST'])
    def blacklist_remove():
        data  = request.json or {}
        appid = data.get('appid')
        if not appid:
            return jsonify({"status": "error", "message": "No appid provided."}), 400
        try:
            remove_from_blacklist(appid)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/import-inspect', methods=['POST'])
    def import_inspect():
        return inspect_database(request.files)

    @app.route('/api/import-execute', methods=['POST'])
    def import_execute():
        return execute_import(request.json)

    @app.route('/api/import/playnite-dates', methods=['POST'])
    def import_playnite_dates():
        from imports import parse_playnite_dates
        data = request.json or {}
        zip_path = _validate_user_path(data.get('path', '').strip())
        app.logger.info(f"Playnite import: request received, path={zip_path!r}")
        if not zip_path or not os.path.isfile(zip_path):
            app.logger.warning(f"Playnite import: file not found at {zip_path!r}")
            return jsonify({"status": "error", "message": "File not found."}), 400
        try:
            date_map = parse_playnite_dates(zip_path)
            app.logger.info(f"Playnite import: parsed {len(date_map)} appid→date pairs")
        except Exception as e:
            app.logger.exception("Playnite import: parse failed")
            return jsonify({"status": "error", "message": f"Failed to parse backup: {e}"}), 500
        if not date_map:
            app.logger.warning("Playnite import: no Steam games with dates found")
            return jsonify({"status": "error", "message": "No Steam games with dates found in the backup."}), 400
        from database import date_to_ts
        db = get_db()
        updated = 0
        for appid, date_str in date_map.items():
            cursor = db.execute(
                "UPDATE games SET date_added = ? WHERE appid = ?",
                (date_to_ts(date_str), appid)
            )
            updated += cursor.rowcount
        db.commit()
        db.close()
        app.logger.info(f"Playnite import: updated {updated} games")
        return jsonify({"status": "success", "updated": updated, "found": len(date_map)})

    @app.route('/sync-blaeo')
    def sync_blaeo():
        try:
            result = scrape_blaeo_games()
            return jsonify(result)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500


    # Path to local supplement JSON file, relative to BASE_DIR.
    # Leave empty to skip supplement loading.
    _PAGYWOSG_SUPPLEMENT_PATH = 'pagywosg_supplement.json'
    _SANTA_GIFTS_PATH = 'santa_gifts.json'

    @app.route('/api/pagywosg-auto')
    def pagywosg_auto():
        import urllib.request
        from datetime import date

        # Anchor: event 83 = April 2026
        today = date.today()
        event_id = 83 + (today.year - 2026) * 12 + (today.month - 4)
        if request.args.get('next'):
            event_id += 1

        def _fetch_event(eid):
            req = urllib.request.Request(
                f'https://pagywosg.xyz/api/events/{eid}',
                headers={'User-Agent': 'PlayDate/1.0'}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())['event']

        try:
            event = _fetch_event(event_id)
        except Exception as e:
            return jsonify({"status": "error", "message": f"Could not fetch event: {e}"}), 502

        # Validate date range; try adjacent event on boundary days (skip for upcoming)
        today_str = today.isoformat()
        if not request.args.get('next'):
            started, ended = event.get('startedAt', ''), event.get('endedAt', '')
            if started and ended and not (started <= today_str < ended):
                adj = event_id + 1 if today_str >= ended else event_id - 1
                try:
                    adj_event = _fetch_event(adj)
                    s2, e2 = adj_event.get('startedAt', ''), adj_event.get('endedAt', '')
                    if s2 <= today_str < e2:
                        event = adj_event
                        event_id = adj
                except Exception:
                    pass

        categories = event.get('gameCategories', [])
        entries    = event.get('entries', [])

        # --- Pool determination via (win)/(backlog) suffix ---
        suffix_re = re.compile(r'\s*\((win|backlog)\)\s*$', re.IGNORECASE)

        base_to_cats = {}
        for cat in categories:
            base = suffix_re.sub('', cat['name']).strip()
            base_to_cats.setdefault(base, []).append(cat)

        all_pool_bases = set()
        for base, cats in base_to_cats.items():
            names_lc = [c['name'].lower() for c in cats]
            if any('(win)' in n for n in names_lc) and any('(backlog)' in n for n in names_lc):
                all_pool_bases.add(base)

        # --- Verified appids per category ID: {cat_id: {appid: game_name}} ---
        verified_by_cat = {}
        for entry in entries:
            if entry.get('verified'):
                cid = str(entry['category']['id'])
                verified_by_cat.setdefault(cid, {})[entry['game']['id']] = entry['game']['name']

        # --- Category name classifiers ---
        MONTHS = {
            'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
            'july':7,'august':8,'september':9,'october':10,'november':11,'december':12
        }
        month_pat    = re.compile(r'released?\s+in\s+(' + '|'.join(MONTHS) + r')\b', re.I)
        year_pat     = re.compile(r'released?\s+in\s+(\d{4})\b', re.I)
        day_pat      = re.compile(r'released?\s+on\s+(?:the\s+)?(\d+)(?:st|nd|rd|th)?\s*day', re.I)
        steamid_pat1 = re.compile(r'steam\s+id\s+containing\s+(\w+)', re.I)
        steamid_pat2 = re.compile(r'\b(\w+)\s+in\s+their\s+steam\s+(?:app\s+)?id', re.I)
        title_pat    = re.compile(r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]\s+in\s+(?:the|their)\s+title', re.I)
        tag_pat      = re.compile(r'^\s*tag\s+(.+)$', re.I)

        tags_wins, tags_all   = [], []
        conds_wins, conds_all = [], []
        # {appid: {"name": str, "categories": [str]}} for each pool
        appids_wins, appids_all = {}, {}
        skipped = []

        # --- Load supplement early so icaio data is available during category loop ---
        _supplement = {}
        if _PAGYWOSG_SUPPLEMENT_PATH:
            try:
                with open(os.path.join(BASE_DIR, _PAGYWOSG_SUPPLEMENT_PATH), 'r', encoding='utf-8') as f:
                    _supplement = json.load(f)
            except Exception:
                pass
        _icaio_ga_dict  = {g['appid']: g['name'] for g in _supplement.get('icaio_giveaways', [])}
        _icaio_wl_dict  = {int(k): v for k, v in _supplement.get('icaio_wishlist', {}).items()}
        _santa_gift_dict = {}
        try:
            with open(os.path.join(BASE_DIR, _SANTA_GIFTS_PATH), 'r', encoding='utf-8') as _sf:
                _santa_gift_dict = {g['appid']: g['name'] for g in json.load(_sf)}
        except Exception:
            pass

        for base, cats in base_to_cats.items():
            pool = 'all' if base in all_pool_bases else 'wins'

            # Collect all verified {appid: name} for this logical category group
            base_appids = {}
            for cat in cats:
                base_appids.update(verified_by_cat.get(str(cat['id']), {}))

            def _add_tag(tag):
                (tags_all if pool == 'all' else tags_wins).append(tag)

            def _add_cond(col, op, val):
                (conds_all if pool == 'all' else conds_wins).append({'col': col, 'op': op, 'val': val})

            def _add_appids(appid_name_dict, category_name, verifiers=None, auto=False):
                target = appids_all if pool == 'all' else appids_wins
                for appid, name in appid_name_dict.items():
                    if appid not in target:
                        target[appid] = {"name": name, "categories": []}
                    if not any(c["cat"] == category_name for c in target[appid]["categories"]):
                        entry = {"cat": category_name}
                        if verifiers and str(appid) in verifiers:
                            entry["verifier"] = verifiers[str(appid)]
                        if auto:
                            entry["auto"] = True
                        target[appid]["categories"].append(entry)

            # Tag
            m = tag_pat.match(base)
            if m:
                _add_tag(m.group(1).strip())
                continue

            # Month release
            m = month_pat.search(base)
            if m:
                _add_cond('release_date', 'month_is', str(MONTHS[m.group(1).lower()]))
                continue

            # Year release (after month so "2001" doesn't match month pattern)
            m = year_pat.search(base)
            if m:
                _add_cond('release_date', 'year_is', m.group(1))
                continue

            # Day release
            m = day_pat.search(base)
            if m:
                _add_cond('release_date', 'day_is', m.group(1))
                continue

            # Steam ID containing (two phrasings)
            m = steamid_pat1.search(base) or steamid_pat2.search(base)
            if m:
                _add_cond('appid', 'contains', m.group(1))
                continue

            # Title contains
            m = title_pat.search(base)
            if m:
                _add_cond('name', 'contains', m.group(1).strip())
                continue

            # Gifter Steam ID — not trackable in our DB
            if re.search(r'gifter', base, re.I):
                skipped.append(base)
                continue

            # icaio giveaway categories — matched by exact copy-pasted phrase
            if 'icaio has made a GA for' in base:
                if _icaio_ga_dict:
                    _add_appids(_icaio_ga_dict, base, auto=True)
                else:
                    skipped.append(base)
                continue

            # icaio wishlist categories
            if 'icaio' in base and 'wishlist' in base.lower():
                if _icaio_wl_dict:
                    _add_appids(_icaio_wl_dict, base, auto=True)
                else:
                    skipped.append(base)
                continue

            # Secret Santa / Snowballs Discord gift categories — always wins pool
            if re.search(r'snowball|secret.santa', base, re.I):
                if _santa_gift_dict:
                    # Force wins pool regardless of suffix logic
                    _real_pool = pool
                    pool = 'wins'
                    _add_appids(_santa_gift_dict, base, auto=True)
                    pool = _real_pool
                else:
                    skipped.append(base)
                continue

            # Everything else: use verified appids if available
            if base_appids:
                _add_appids(base_appids, base)
            else:
                skipped.append(base)

        # --- Supplement JSON (event-specific entries) ---
        supplement_loaded = False
        if _supplement:
            try:
                db = get_db()
                for _cat_id, sdata in _supplement.get(str(event_id), {}).items():
                    s_pool    = sdata.get('pool', 'wins')
                    cat_label = sdata.get('id_name', f'Category {_cat_id}')
                    target_conds  = conds_all  if s_pool == 'all' else conds_wins
                    target_appids = appids_all if s_pool == 'all' else appids_wins
                    for dev in sdata.get('developers', []):
                        target_conds.append({'col': 'developers', 'op': 'contains', 'val': dev})
                    for pub in sdata.get('publishers', []):
                        target_conds.append({'col': 'publishers', 'op': 'contains', 'val': pub})
                    s_verifiers = sdata.get('verifiers', {})
                    for appid in sdata.get('appids', []):
                        row = db.execute("SELECT name FROM games WHERE appid = ?", (appid,)).fetchone()
                        name = row['name'] if row else f"App {appid}"
                        if appid not in target_appids:
                            target_appids[appid] = {"name": name, "categories": []}
                        if not any(c["cat"] == cat_label for c in target_appids[appid]["categories"]):
                            entry = {"cat": cat_label}
                            if str(appid) in s_verifiers:
                                entry["verifier"] = s_verifiers[str(appid)]
                            target_appids[appid]["categories"].append(entry)
                db.close()
                supplement_loaded = True
            except Exception:
                pass

        # Scan the whole games table once (fast — user's library is small) and
        # intersect in Python, avoiding a huge IN (?, ?, ...) with 5000+ params.
        _lib_db = get_db()
        _all_library_appids = {r['appid'] for r in _lib_db.execute('SELECT appid FROM games').fetchall()}
        all_appids_combined = set(appids_wins.keys()) | set(appids_all.keys())
        in_library_set = _all_library_appids & all_appids_combined

        _COMMA_SEP_COLS = {'tags', 'groups', 'genres', 'categories', 'developers', 'publishers'}

        def _redundant_set(pool_dict, tags, conds):
            """Return appids already matched by the pool's tag/condition criteria (not needing the explicit appid list)."""
            owned = {aid for aid in pool_dict if aid in in_library_set}
            if not owned:
                return set()
            parts, params = [], []
            for tag in tags:
                parts.append("(',' || tags || ',') LIKE ?")
                params.append(f'%,{tag},%')
            for c in conds:
                col, op, val = c['col'], c['op'], c['val']
                if op == 'contains':
                    if col in _COMMA_SEP_COLS:
                        parts.append(f"(',' || {col} || ',') LIKE ?")
                        params.append(f'%,{val},%')
                    elif col == 'name':
                        parts.append("name LIKE ?")
                        params.append(f'%{val}%')
                elif op == 'month_is':
                    parts.append(f"strftime('%m', {col}) = ?")
                    params.append(str(int(val)).zfill(2))
                elif op == 'year_is':
                    parts.append(f"strftime('%Y', {col}) = ?")
                    params.append(str(val))
                elif op == 'day_is':
                    parts.append(f"strftime('%d', {col}) = ?")
                    params.append(str(int(val)).zfill(2))
            if not parts:
                return set()
            # Query only the tag/condition filter against the whole library,
            # then intersect with owned in Python — no large IN clause needed.
            where = ' OR '.join(parts)
            rows = _lib_db.execute(
                f'SELECT appid FROM games WHERE ({where})',
                params
            ).fetchall()
            return {r['appid'] for r in rows} & owned

        def _serialise_pool(pool_dict, tags, conds):
            redundant = _redundant_set(pool_dict, tags, conds)
            # Group appids by contributing category label for labeled appid_list nodes.
            # Only include appids present in the user's library — no point embedding
            # thousands of unowned game IDs in the saved filter.
            source_map = {}   # {cat_label: {"appids": [...], "auto": bool}}
            for aid, v in pool_dict.items():
                if aid not in in_library_set:
                    continue
                for cat_entry in v.get("categories", []):
                    label = cat_entry.get("cat", "")
                    if not label:
                        continue
                    if label not in source_map:
                        source_map[label] = {"appids": [], "auto": bool(cat_entry.get("auto"))}
                    source_map[label]["appids"].append(aid)
            appid_sources = [{"label": lbl, "appids": sorted(v["appids"]), "auto": v["auto"]}
                             for lbl, v in source_map.items() if v["appids"]]
            return {
                "appids": sorted(aid for aid in pool_dict if aid in in_library_set),
                "appid_sources": appid_sources,
                "games":  sorted(
                    [{"appid": aid, "name": v["name"], "categories": v["categories"],
                      "in_library": aid in in_library_set,
                      "redundant":  aid in redundant}
                     for aid, v in pool_dict.items()],
                    key=lambda g: g["name"].lower()
                ),
            }

        result = {
            "status": "success",
            "event": {"id": event_id, "name": event.get('name', '')},
            "tags":   {"wins": tags_wins, "all": tags_all},
            "conds":  {"wins": conds_wins, "all": conds_all},
            "wins":   _serialise_pool(appids_wins, tags_wins, conds_wins),
            "all":    _serialise_pool(appids_all,  tags_all,  conds_all),
            "skipped": skipped,
            "supplement_loaded": supplement_loaded,
        }
        _lib_db.close()
        return jsonify(result)

    @app.route('/api/pagywosg-sg-group', methods=['GET', 'POST'])
    def pagywosg_sg_group():
        from config import load_state, save_state
        from utils import get_all_unique_groups
        if request.method == 'POST':
            data = request.json or {}
            # 'group' may be a non-empty string (chosen group) or None (no SG wins)
            grp = data.get('group')
            save_state({'pagywosg_sg_group': grp})
            return jsonify({'status': 'success'})
        # GET
        state = load_state()
        saved = state.get('pagywosg_sg_group', '__unset__')
        groups = get_all_unique_groups()
        default_group = next((g for g in groups if g.lower() == 'won on steamgifts'), None)
        return jsonify({
            'saved': None if saved == '__unset__' else saved,
            'unset': saved == '__unset__',
            'default_group': default_group,
            'groups': groups,
        })

    @app.route('/api/santa-gifts', methods=['GET', 'POST'])
    def santa_gifts():
        path = os.path.join(BASE_DIR, _SANTA_GIFTS_PATH)
        if request.method == 'POST':
            data = request.json or {}
            gifts = data.get('gifts', [])
            if not isinstance(gifts, list):
                return jsonify({'status': 'error', 'message': 'Invalid data.'}), 400
            validated = [
                {'appid': int(g['appid']), 'name': str(g['name'])}
                for g in gifts
                if isinstance(g, dict) and 'appid' in g and 'name' in g
            ]
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(validated, f, indent=2, ensure_ascii=False)
            except Exception as e:
                app.logger.error('Failed to save gifts: %s', e)
                return jsonify({'status': 'error', 'message': 'Failed to save gifts'}), 500
            return jsonify({'status': 'success'})
        try:
            with open(path, 'r', encoding='utf-8') as f:
                gifts = json.load(f)
        except Exception:
            gifts = []
        return jsonify({'status': 'success', 'gifts': gifts})

    @app.route('/api/pagywosg-tags')
    def pagywosg_tags():
        try:
            db = get_db()
            rows = db.execute("SELECT tags FROM games WHERE tags IS NOT NULL AND tags != ''").fetchall()
            db.close()
            tag_set = set()
            for row in rows:
                for tag in [t.strip() for t in row['tags'].split(',') if t.strip()]:
                    tag_set.add(tag)
            return jsonify({"status": "success", "tags": sorted(tag_set, key=str.lower)})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/pagywosg-pick', methods=['POST'])
    def pagywosg_pick():
        import random
        from library import is_safe_sql
        data = request.json or {}
        where = (data.get('where') or '').strip()
        if not where or where == '1=1':
            return jsonify({"status": "error", "message": "No criteria selected — please pick at least one tag or condition."})
        if not is_safe_sql(where):
            return jsonify({"status": "error", "message": "Invalid SQL in filter."}), 400
        try:
            db = get_db()
            rows = db.execute(f"SELECT appid, name FROM games WHERE {where}").fetchall()
            db.close()
        except Exception as e:
            return jsonify({"status": "error", "message": f"Query error: {e}"}), 400
        games = [dict(r) for r in rows]
        if not games:
            return jsonify({"status": "error", "message": "No games matched the selected criteria."})
        picks = random.sample(games, min(6, len(games)))
        return jsonify({"status": "success", "picks": picks, "pool_size": len(games)})

    @app.route('/api/shelves', methods=['POST'])
    def save_shelves():
        from config import save_state
        try:
            shelves = request.json.get('shelves')
            if not isinstance(shelves, list):
                return jsonify({"status": "error", "message": "Invalid shelves data."}), 400
            save_state({"shelves": shelves})
            return jsonify({"status": "success"})
        except Exception as e:
            app.logger.exception("Failed to save shelves")
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/shelves/reset', methods=['POST'])
    def reset_shelves():
        from config import save_state, get_default_shelves
        try:
            save_state({"shelves": get_default_shelves()})
            return jsonify({"status": "success"})
        except Exception as e:
            app.logger.exception("Failed to reset shelves")
            return jsonify({"status": "error", "message": str(e)}), 500

    # ── BACKUP ────────────────────────────────────────────────────────────────
    def _fill_backup_zip(zf, include_art):
        import glob as _glob
        for arcname, filepath in {'config.json':    os.path.join(BASE_DIR, 'config.json'),
                                   'state.json':     os.path.join(BASE_DIR, 'state.json'),
                                   'santa_gifts.json': os.path.join(BASE_DIR, 'santa_gifts.json')}.items():
            if os.path.exists(filepath):
                zf.write(filepath, arcname)
        for db_path in _glob.glob(os.path.join(BASE_DIR, 'games_*.db')):
            zf.write(db_path, os.path.basename(db_path))
        if include_art:
            art_dir = os.path.join(BASE_DIR, 'static', 'img', 'library')
            if os.path.isdir(art_dir):
                for dirpath, _, filenames in os.walk(art_dir):
                    for fname in filenames:
                        if fname.lower().endswith('.jpg'):
                            full = os.path.join(dirpath, fname)
                            zf.write(full, os.path.relpath(full, BASE_DIR).replace(os.sep, '/'))

    @app.route('/api/backup', methods=['POST'])
    def backup():
        import zipfile, io
        from datetime import datetime
        from flask import send_file

        data        = request.json or {}
        include_art = data.get('include_art', False)
        buf         = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            _fill_backup_zip(zf, include_art)
        buf.seek(0)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        return send_file(buf, mimetype='application/zip', as_attachment=True,
                         download_name=f'playdate_backup_{ts}.zip')

    @app.route('/api/backup-to-path', methods=['POST'])
    def backup_to_path():
        """
        Write the backup zip directly to a path chosen via pywebview's native
        Save-As dialog (path is passed in the request body).  Used by the
        pywebview build; the browser fallback still uses /api/backup.
        """
        import zipfile
        data        = request.json or {}
        save_path   = _validate_user_path(data.get('path', '').strip())
        include_art = data.get('include_art', False)
        if not save_path:
            return jsonify({"status": "error", "message": "No path provided."}), 400
        try:
            with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                _fill_backup_zip(zf, include_art)
            return jsonify({"status": "success", "path": save_path, "size": os.path.getsize(save_path)})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # ── CSV EXPORT ────────────────────────────────────────────────────────────

    def _build_csv_rows(filter_tree=None, columns=None):
        """
        Query the DB and return (header_list, rows_list) for CSV export.
        Applies filter_tree if provided, otherwise exports all games.
        Playtime is converted from minutes to decimal hours.
        Achievements percentage is computed when both fields are present.
        columns: optional list of header names to include (None = all).
        """
        import csv, io
        from library import build_tree_sql, _strip_sql_wrapper, is_safe_sql

        params = []
        where  = '1=1'
        if filter_tree:
            custom_sql = _strip_sql_wrapper(filter_tree.get('custom_sql', ''))
            if custom_sql:
                where = custom_sql if is_safe_sql(custom_sql) else '1=0'
            else:
                tree_sql = build_tree_sql(filter_tree, params)
                if tree_sql and tree_sql != '1=1':
                    where = tree_sql

        db   = get_db()
        rows = db.execute(
            f"SELECT name, appid, completion_status, tags, groups, "
            f"playtime_forever, last_played, date_added, installed, "
            f"review_score, review_percentage, developers, publishers, "
            f"release_date, unlocked_achievements, total_achievements "
            f"FROM games WHERE {where} ORDER BY name ASC",
            params
        ).fetchall()
        db.close()

        headers = [
            'Name', 'AppID', 'Completion Status', 'Tags', 'Groups',
            'Playtime (hrs)', 'Last Played', 'Date Added', 'Installed',
            'Review Score', 'Review %', 'Developers', 'Publishers',
            'Release Date', 'Achievements Unlocked', 'Achievements Total',
            'Achievement %'
        ]

        from database import ts_to_date
        out = []
        for r in rows:
            pt_mins = r['playtime_forever'] or 0
            pt_hrs  = round(pt_mins / 60, 1) if pt_mins else 0
            unlocked = r['unlocked_achievements'] or 0
            total    = r['total_achievements']    or 0
            cheevo_pct = f"{round(unlocked / total * 100, 1)}%" if total else ''
            out.append([
                r['name']               or '',
                r['appid'],
                r['completion_status']  or '',
                r['tags']               or '',
                r['groups']             or '',
                pt_hrs,
                ts_to_date(r['last_played'])   or '',
                ts_to_date(r['date_added'])    or '',
                'Yes' if r['installed'] else 'No',
                r['review_score']       or '',
                r['review_percentage']  if r['review_percentage'] is not None else '',
                r['developers']         or '',
                r['publishers']         or '',
                ts_to_date(r['release_date'])  or '',
                unlocked,
                total,
                cheevo_pct,
            ])

        if columns:
            indices = [i for i, h in enumerate(headers) if h in columns]
            headers = [headers[i] for i in indices]
            out     = [[row[i] for i in indices] for row in out]

        return headers, out

    @app.route('/api/export-csv', methods=['POST'])
    def export_csv():
        """Stream a CSV file as a download (browser/fallback path)."""
        import csv, io
        from flask import send_file
        data        = request.json or {}
        filter_tree = data.get('filter_tree')
        columns     = data.get('columns') or None
        try:
            headers, rows = _build_csv_rows(filter_tree, columns)
            buf = io.StringIO()
            w   = csv.writer(buf)
            w.writerow(headers)
            w.writerows(rows)
            buf.seek(0)
            byte_buf = io.BytesIO(buf.getvalue().encode('utf-8-sig'))  # utf-8-sig for Excel compat
            from datetime import datetime
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            return send_file(byte_buf, mimetype='text/csv', as_attachment=True,
                             download_name=f'playdate_library_{ts}.csv')
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/export-csv-to-path', methods=['POST'])
    def export_csv_to_path():
        """Write CSV directly to a user-chosen path (pywebview save-dialog path)."""
        import csv
        data        = request.json or {}
        save_path   = _validate_user_path(data.get('path', '').strip())
        filter_tree = data.get('filter_tree')
        columns     = data.get('columns') or None
        if not save_path:
            return jsonify({"status": "error", "message": "No path provided."}), 400
        try:
            headers, rows = _build_csv_rows(filter_tree, columns)
            with open(save_path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(headers)
                w.writerows(rows)
            size = os.path.getsize(save_path)
            return jsonify({"status": "success", "path": save_path,
                            "size": size, "count": len(rows)})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/current-filter')
    def current_filter():
        """Return the active filter_tree from state — used by the tools page CSV exporter."""
        from config import load_state, resolve_active_filter_tree
        state       = load_state()
        filter_tree = resolve_active_filter_tree(state)
        return jsonify({"status": "success", "filter_tree": filter_tree})

    @app.route('/api/theme-to-path', methods=['POST'])
    def theme_to_path():
        """Write a theme JSON directly to a user-chosen path."""
        from config import DEFAULT_THEME
        data      = request.json or {}
        save_path = _validate_user_path(data.get('path', '').strip())
        theme     = data.get('theme', {})
        if not save_path:
            return jsonify({"status": "error", "message": "No path provided."}), 400
        clean = {k: v for k, v in theme.items() if k in DEFAULT_THEME}
        if not clean:
            return jsonify({"status": "error", "message": "No valid theme data."}), 400
        try:
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump({"playdate_theme": clean}, f, indent=2)
            return jsonify({"status": "success", "path": save_path})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # ── RESTORE ───────────────────────────────────────────────────────────────
    @app.route('/api/restore', methods=['POST'])
    def restore():
        import zipfile
        import io

        app.logger.info("Restore: request received")

        if 'backup_file' not in request.files:
            app.logger.warning("Restore: no backup_file in request.files")
            return jsonify({"status": "error", "message": "No file uploaded."}), 400

        f = request.files['backup_file']
        app.logger.info(f"Restore: file received — name={f.filename!r}, content_type={f.content_type!r}")

        if not f.filename.endswith('.zip'):
            return jsonify({"status": "error", "message": "File must be a .zip backup."}), 400

        try:
            raw = f.read()
            app.logger.info(f"Restore: read {len(raw)} bytes from upload")
            buf = io.BytesIO(raw)
            with zipfile.ZipFile(buf, 'r') as zf:
                names = zf.namelist()
                app.logger.info(f"Restore: zip contains {len(names)} entries: {names[:20]}")

                restored = []
                skipped  = []
                _base_real = os.path.realpath(BASE_DIR)

                def _safe_dest(rel):
                    """Resolve a relative ZIP entry path and confirm it stays within BASE_DIR."""
                    dest = os.path.realpath(os.path.join(BASE_DIR, rel.replace('/', os.sep)))
                    return dest if dest.startswith(_base_real + os.sep) or dest == _base_real else None

                # Core files: restore to BASE_DIR
                for arcname in ('config.json', 'state.json', 'santa_gifts.json'):
                    if arcname in names:
                        dest = _safe_dest(arcname)
                        if not dest:
                            continue
                        with zf.open(arcname) as src:
                            data = src.read()
                        with open(dest, 'wb') as dst:
                            dst.write(data)
                        app.logger.info(f"Restore: wrote {len(data)} bytes → {dest}")
                        restored.append(arcname)
                    else:
                        app.logger.warning(f"Restore: {arcname!r} not found in zip — skipping")
                        skipped.append(arcname)

                # Per-account databases: games_*.db
                db_entries = [n for n in names if n.startswith('games_') and n.endswith('.db')]
                for arcname in db_entries:
                    dest = _safe_dest(arcname)
                    if not dest:
                        continue
                    with zf.open(arcname) as src:
                        data = src.read()
                    with open(dest, 'wb') as dst:
                        dst.write(data)
                    app.logger.info(f"Restore: wrote {len(data)} bytes → {dest}")
                    restored.append(arcname)

                # Art files: restore to static/img/library/ (including subdirs)
                art_files = [n for n in names if n.startswith('static/img/library/') and n.endswith('.jpg')]
                if art_files:
                    for arcname in art_files:
                        dest = _safe_dest(arcname)
                        if not dest:
                            continue
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with zf.open(arcname) as src, open(dest, 'wb') as dst:
                            dst.write(src.read())
                    app.logger.info(f"Restore: wrote {len(art_files)} cover image(s)")
                    restored.append(f"{len(art_files)} cover image(s)")

        except zipfile.BadZipFile:
            app.logger.exception("Restore: bad zip file")
            return jsonify({"status": "error", "message": "Invalid zip file. Make sure this is a PlayDate backup."}), 400
        except Exception as e:
            app.logger.exception(f"Restore: unexpected error — {e}")
            return jsonify({"status": "error", "message": f"Restore failed: {str(e)}"}), 500

        app.logger.info(f"Restore: complete — restored={restored}, skipped={skipped}")

        # Run migrations and re-initialise the DB — the restored data may be
        # from an older version that predates recent schema changes.
        try:
            import migration as _migration
            _migration.run()
            init_db()
        except Exception as e:
            app.logger.warning(f"Restore: post-restore migration failed: {e}", exc_info=True)

        return jsonify({
            "status":   "success",
            "restored": restored,
            "skipped":  skipped,
        })

    # ── Update checking endpoints ─────────────────────────────────────────────
    @app.route('/api/update-status')
    def update_status():
        from config import load_state, __version__
        state = load_state()
        return jsonify({
            'current_version': __version__,
            'auto_check': state.get('check_for_updates', True),
            'update_available': _update_cache.get('available', False),
            'latest_version': _update_cache.get('latest_version'),
            'checked': bool(_update_cache),
            'error': _update_cache.get('error'),
        })

    @app.route('/api/check-update', methods=['POST'])
    def check_update():
        from config import __version__
        _do_update_check()
        return jsonify({
            'update_available': _update_cache.get('available', False),
            'latest_version': _update_cache.get('latest_version'),
            'current_version': __version__,
            'error': _update_cache.get('error'),
        })

    @app.route('/api/perform-update', methods=['POST'])
    def perform_update():
        if not _update_cache.get('available'):
            return jsonify({'status': 'error', 'message': 'No update available'}), 400

        def _do_update():
            import time, tempfile, urllib.request, ssl
            time.sleep(0.5)  # let the HTTP response send first

            def _fetch(url, dest):
                """Download url to dest, retrying without SSL verification on SSL errors."""
                try:
                    urllib.request.urlretrieve(url, dest)
                except ssl.SSLError as exc:
                    log.warning(f"SSL error downloading update ({exc}), retrying without verification")
                    ctx = ssl._create_unverified_context()
                    with urllib.request.urlopen(url, context=ctx) as r, open(dest, 'wb') as f:
                        while True:
                            chunk = r.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)

            _update_dl_state['status'] = 'downloading'
            _update_dl_state['error'] = None
            try:
                if getattr(sys, 'frozen', False):
                    # Windows frozen exe: download installer and launch it
                    url = _update_cache.get('installer_url')
                    if not url:
                        log.error("perform-update: no installer URL cached")
                        _update_dl_state.update({'status': 'error', 'error': 'No installer URL cached', 'manual_url': None})
                        return
                    tmp = os.path.join(tempfile.gettempdir(), 'PlayDate-Setup.exe')
                    log.info(f"Downloading installer: {url}")
                    _update_dl_state['manual_url'] = url
                    _fetch(url, tmp)
                    log.info(f"Launching installer: {tmp}")
                    subprocess.Popen(
                        [tmp],
                        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                    )
                else:
                    # Linux/macOS from source: download zip, extract over BASE_DIR, pip, restart
                    import zipfile
                    url = _update_cache.get('zipball_url')
                    if not url:
                        log.error("perform-update: no zipball URL cached")
                        _update_dl_state.update({'status': 'error', 'error': 'No zipball URL cached', 'manual_url': None})
                        return
                    tmp_zip = os.path.join(tempfile.gettempdir(), 'playdate-update.zip')
                    log.info(f"Downloading source zip: {url}")
                    _update_dl_state['manual_url'] = url
                    _fetch(url, tmp_zip)
                    log.info(f"Extracting to {BASE_DIR}")
                    with zipfile.ZipFile(tmp_zip) as zf:
                        members = zf.namelist()
                        prefix = members[0].split('/')[0] + '/' if members else ''
                        for member in members:
                            rel = member[len(prefix):]
                            if not rel:
                                continue
                            target = os.path.join(BASE_DIR, rel)
                            if member.endswith('/'):
                                os.makedirs(target, exist_ok=True)
                            else:
                                os.makedirs(os.path.dirname(target), exist_ok=True)
                                with zf.open(member) as src, open(target, 'wb') as dst:
                                    dst.write(src.read())

                    venv_pip = os.path.join(BASE_DIR, '.venv', 'bin', 'pip')
                    if os.path.exists(venv_pip):
                        log.info("Running pip install -r requirements.txt")
                        subprocess.run(
                            [venv_pip, 'install', '-r', os.path.join(BASE_DIR, 'requirements.txt')],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )

                    launcher = os.path.join(BASE_DIR, 'playdate-launch.sh')
                    if os.path.exists(launcher):
                        subprocess.Popen([launcher], start_new_session=True)
                    else:
                        subprocess.Popen(
                            [sys.executable, os.path.join(BASE_DIR, 'main.py')],
                            start_new_session=True
                        )
            except Exception as e:
                log.error(f"perform-update failed: {e}", exc_info=True)
                _update_dl_state.update({'status': 'error', 'error': str(e)})
                return
            os._exit(0)

        threading.Thread(target=_do_update, daemon=True).start()
        return jsonify({'status': 'ok'})

    @app.route('/api/update-dl-status')
    def update_dl_status():
        return jsonify(_update_dl_state)

    # ── Plugin management ─────────────────────────────────────────────────────
    @app.route('/api/plugins')
    def list_plugins():
        import plugins as _plugins
        db = get_db()
        result = []
        for pid, p in _plugins.loaded().items():
            manifest = _plugins.plugin_manifest(pid)
            row = db.execute(
                'SELECT COUNT(*) FROM games WHERE platform = ?', (p.platform,)
            ).fetchone()
            result.append({
                'id':         pid,
                'name':       p.name,
                'version':    manifest.get('version', '?'),
                'platform':   p.platform,
                'game_count': row[0] if row else 0,
                'source':     manifest.get('source', ''),
                'launcher':   manifest.get('launcher', {}),
                'manage_ui':  p.manage_ui() if hasattr(p, 'manage_ui') else None,
            })
        return jsonify(result)

    @app.route('/api/plugins/install', methods=['POST'])
    def install_plugin():
        if 'plugin_file' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file uploaded.'}), 400
        f = request.files['plugin_file']
        if not f.filename.lower().endswith('.zip'):
            return jsonify({'status': 'error', 'message': 'File must be a .zip archive.'}), 400
        try:
            plugin_id, name = _install_plugin_zip(f.read())
            return jsonify({'status': 'success', 'plugin_id': plugin_id, 'name': name})
        except ValueError as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
        except Exception as e:
            log.error(f"Plugin install failed: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/plugins/install-from-github', methods=['POST'])
    def install_plugin_from_github():
        import requests as _req
        data = request.get_json(silent=True) or {}
        url = data.get('url', '').strip()
        if not url:
            return jsonify({'status': 'error', 'message': 'No URL provided.'}), 400
        raw_url = url.removeprefix('github:')
        owner, repo = _parse_github_repo(raw_url)
        if not owner:
            return jsonify({'status': 'error', 'message': 'Could not parse a GitHub owner/repo from that URL.'}), 400
        try:
            zip_url, tag = _fetch_github_plugin_release(owner, repo)
            if not zip_url:
                return jsonify({'status': 'error', 'message': 'No downloadable zip found in the latest release.'}), 400
            resp = _req.get(zip_url, timeout=60)
            resp.raise_for_status()
            plugin_id, name = _install_plugin_zip(resp.content)
            _plugin_update_cache.pop(plugin_id, None)
            return jsonify({'status': 'success', 'plugin_id': plugin_id, 'name': name, 'tag': tag})
        except ValueError as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
        except Exception as e:
            log.error(f"Plugin install from GitHub failed: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/plugins/check-updates')
    def check_plugin_updates():
        import time
        import plugins as _plugins
        import concurrent.futures

        TTL = 6 * 3600

        def _check_one(pid):
            manifest = _plugins.plugin_manifest(pid)
            source = manifest.get('source', '')
            if not source:
                return None
            raw_url = source.removeprefix('github:')
            owner, repo = _parse_github_repo(raw_url)
            if not owner:
                return {'id': pid, 'source': source, 'update_available': False, 'latest_version': None, 'error': 'Invalid source in plugin.json'}

            cached = _plugin_update_cache.get(pid, {})
            if cached.get('checked_at') and (time.time() - cached['checked_at']) < TTL:
                return {'id': pid, 'source': source, **{k: cached[k] for k in ('update_available', 'latest_version', 'error')}}

            try:
                _, tag = _fetch_github_plugin_release(owner, repo)
                latest = tag.lstrip('v')
                installed = manifest.get('version', '0')

                def _semver(v):
                    try:
                        return tuple(int(x) for x in v.split('.'))
                    except Exception:
                        return (0, 0, 0)

                available = _semver(latest) > _semver(installed)
                entry = {
                    'update_available': available,
                    'latest_version': latest,
                    'error': None,
                    'checked_at': time.time(),
                }
                _plugin_update_cache[pid] = entry
                return {'id': pid, 'source': source, 'update_available': available, 'latest_version': latest, 'error': None}
            except Exception as e:
                entry = {'update_available': False, 'latest_version': None, 'error': str(e), 'checked_at': time.time()}
                _plugin_update_cache[pid] = entry
                return {'id': pid, 'source': source, 'update_available': False, 'latest_version': None, 'error': str(e)}

        pids = list(_plugins.loaded().keys())
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(_check_one, pid) for pid in pids]
            for fut in concurrent.futures.as_completed(futures, timeout=15):
                try:
                    r = fut.result()
                    if r:
                        results.append(r)
                except Exception:
                    pass

        return jsonify(results)

    @app.route('/api/plugins/launcher-status', methods=['GET'])
    def get_launcher_status():
        return jsonify(_launcher_status_cache)

    @app.route('/api/plugins/launcher-status/<platform_id>', methods=['POST'])
    def recheck_launcher_status(platform_id):
        import plugins as _plugin_registry
        plugin_obj = next(
            (p for p in _plugin_registry.loaded().values() if p.platform == platform_id),
            None,
        )
        if not plugin_obj or not hasattr(plugin_obj, 'launcher_status'):
            return jsonify({'status': 'error', 'message': 'Plugin not found or does not support launcher_status'}), 404
        try:
            result = plugin_obj.launcher_status()
            result['checked_at'] = time.time()
            _launcher_status_cache[platform_id] = result
            return jsonify({'status': 'success', 'launcher_status': result})
        except Exception as e:
            log.error(f"launcher_status failed for {platform_id}: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/plugins/<plugin_id>/uninstall', methods=['POST'])
    def uninstall_plugin(plugin_id):
        import shutil
        import plugins as _plugins
        p = _plugins.get(plugin_id)
        if not p:
            return jsonify({'status': 'error', 'message': 'Plugin not found'}), 404
        path = _plugins.plugin_path(plugin_id)
        if not path or not os.path.isdir(path):
            return jsonify({'status': 'error', 'message': 'Plugin folder not found'}), 404
        data = request.get_json(silent=True) or {}
        try:
            if hasattr(p, 'on_uninstall'):
                p.on_uninstall()
            if data.get('remove_games'):
                db = get_db()
                db.execute('DELETE FROM games WHERE platform = ?', (p.platform,))
                db.commit()
            if data.get('remove_launcher'):
                from config import get_launcher_config
                lc = get_launcher_config(p.platform)
                prefix = lc.get('prefix', '').strip()
                if prefix:
                    prefix_path = os.path.expanduser(prefix)
                    # Safety: must be absolute, exist as a dir, and have enough depth
                    if (os.path.isabs(prefix_path) and
                            os.path.isdir(prefix_path) and
                            len(prefix_path.strip('/').split('/')) >= 2):
                        shutil.rmtree(prefix_path, ignore_errors=True)
            # Always clean up launcher config entry
            try:
                from config import load_config, _save_config_data
                cfg = load_config()
                if cfg and 'launchers' in cfg and p.platform in cfg['launchers']:
                    del cfg['launchers'][p.platform]
                    _save_config_data(cfg)
            except Exception:
                pass
            shutil.rmtree(path)
            return jsonify({'status': 'success'})
        except Exception as e:
            log.error(f"Plugin uninstall failed: {plugin_id} — {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/detect-duplicates', methods=['POST'])
    def detect_duplicates():
        try:
            from database import auto_detect_duplicates
            from config import load_state
            priority = load_state().get('platform_priority')
            count = auto_detect_duplicates(platform_priority=priority)
            return jsonify({'status': 'ok', 'detected': count})
        except Exception as e:
            log.error(f"detect-duplicates failed: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': str(e)}), 500

    # ── Background update check on startup ───────────────────────────────────
    def _startup_update_check():
        import time
        time.sleep(5)
        from config import load_state
        if load_state().get('check_for_updates', True):
            _do_update_check()

    threading.Thread(target=_startup_update_check, daemon=True).start()

    import plugins as _plugins
    _plugins.load_all(app)

    # Set INFO on all plugin sub-modules so their logs are captured
    for _pid, _p in _plugins.loaded().items():
        _mod_prefix = f'plugins.{_pid}'
        for _mname in list(sys.modules):
            if _mname == _mod_prefix or _mname.startswith(_mod_prefix + '.'):
                logging.getLogger(_mname).setLevel(logging.INFO)

    def _startup_launcher_status_check():
        import time as _time
        _time.sleep(3)
        for p in _plugins.loaded().values():
            if not hasattr(p, 'launcher_status'):
                continue
            try:
                result = p.launcher_status()
                result['checked_at'] = _time.time()
                _launcher_status_cache[p.platform] = result
            except Exception as e:
                log.warning(f"launcher_status failed for {p.platform}: {e}")
                _launcher_status_cache[p.platform] = {'available': False, 'detail': str(e), 'checked_at': _time.time()}

    threading.Thread(target=_startup_launcher_status_check, daemon=True).start()
    app.jinja_env.globals['has_plugin']        = _plugins.has
    app.jinja_env.globals['plugin_fragments']  = _plugins.fragments
    app.jinja_env.globals['platform_labels']   = _plugins.platform_labels
    app.jinja_env.globals['plugin_js_api']     = _plugins.plugin_js_api

    return app


# ── Backwards compatibility: module-level `app` for running directly ──────────
# Only create at module level when running as the entry point, not when imported
# by main.py (which calls create_app() itself, avoiding a double startup).
if __name__ == '__main__' or os.environ.get('FLASK_APP') == 'app':
    app = create_app()

if __name__ == '__main__':
    import migration
    migration.run()
    init_db()
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1', port=5000)
