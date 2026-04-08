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
              'scrapers', 'utils', 'images', 'imports'):
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
from database import get_db, init_db, migrate_image_files, update_game_data, add_to_blacklist, remove_from_blacklist, get_blacklist
import re
import scrapers
import threading
import json
import subprocess


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
        import time
        _update_cache.update({'available': False, 'checked_at': time.time(), 'error': str(e)})
        log.warning(f"Update check failed: {e}")


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
        if origin.startswith('https://help.steampowered.com'):
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
    @app.route('/static/img/library/<path:filename>')
    def serve_library_image(filename):
        return send_from_directory(
            os.path.join(BASE_DIR, 'static', 'img', 'library'), filename
        )

    @app.route('/static/img/backgrounds/<path:filename>')
    def serve_background_image(filename):
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
        import sys as _sys
        return dict(
            background_ts=ts,
            builtin_filters=BUILTIN_FILTERS,
            theme_vars=load_theme(),
            unique_tags=get_all_unique_tags(),
            unique_groups=get_all_unique_groups(),
            unique_genres=get_all_unique_genres(),
            unique_categories=get_all_unique_categories(),
            is_windows=_sys.platform == 'win32',
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

    @app.route('/pick')
    def pick():
        from config import load_state
        state = load_state()
        has_filters = bool(state.get('filter_tree') and (
            state['filter_tree'].get('items') or state['filter_tree'].get('custom_sql')
        ))
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
        w_tags       = float(data.get('w_tags',      65))
        w_review     = float(data.get('w_review',    35))
        w_staleness  = float(data.get('w_staleness',  0))
        w_completion = float(data.get('w_completion', 0))
        w_playtime   = float(data.get('w_playtime',   0))
        w_recency    = float(data.get('w_recency',    0))

        state  = load_state()
        db     = get_db()
        params = []
        where  = '1=1'

        if use_filtered:
            filter_tree = state.get('filter_tree')
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
                        ts = datetime.strptime(lp[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()
                        return min((now - ts) / 86400, 730) / 730.0
                    except Exception:
                        return 0.5
                return 1.0

            def completion_bias_score(g):
                cs = g.get('completion_status', '')
                return 1.0 if cs == 'Never Played' else 0.5

            def playtime_score(g):
                pt = float(g.get('playtime_forever') or 0)
                return 1.0 - min(pt, 3000) / 3000.0

            def recency_score(g):
                rd = g.get('release_date') or ''
                try:
                    import re as _re
                    year = int(_re.search(r'\d{4}', rd).group())
                    from datetime import datetime
                    age_years = max(datetime.now().year - year, 0)
                    return 1.0 - min(age_years, 10) / 10.0
                except Exception:
                    return 0.5

            def score_game(g):
                if mode == 'weighted':
                    total_w = (w_tags + w_review + w_staleness + w_completion + w_playtime + w_recency) or 1.0
                    wt  = w_tags       / total_w
                    wr  = w_review     / total_w
                    ws  = w_staleness  / total_w
                    wc  = w_completion / total_w
                    wpl = w_playtime   / total_w
                    wrc = w_recency    / total_w
                else:
                    wt, wr, ws, wc, wpl, wrc = 0.65, 0.35, 0.0, 0.0, 0.0, 0.0

                sim, matched = tag_similarity(g)
                rev  = review_score(g)
                stal = staleness_score(g)
                comp = completion_bias_score(g)
                play = playtime_score(g)
                rec  = recency_score(g)

                if rev is None:
                    leftover = wr
                    denom = (wt + ws + wc + wpl + wrc + leftover) or 1.0
                    final = ((wt + leftover) * sim + ws * stal + wc * comp + wpl * play + wrc * rec) / denom
                else:
                    final = wt * sim + wr * rev + ws * stal + wc * comp + wpl * play + wrc * rec

                return final, sim, matched

            remaining = list(games)
            for _ in range(min(NUM_PICKS, len(remaining))):
                scored = [(score_game(g), g) for g in remaining]
                total  = sum(s[0] for s, _ in scored)

                if total == 0:
                    game = random.choice(remaining)
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

                if matched:
                    top_tags = ", ".join(matched[:3])
                    if rev is not None and rev >= 0.75:
                        reason = f"Matches {profile_desc} on {top_tags} — and it's well reviewed."
                    else:
                        reason = f"Matches {profile_desc} on {top_tags}."
                elif rev is not None:
                    reason = f"No tag overlap found, but solid reviews ({int(rev * 100)}%)."
                else:
                    reason = "Picked based on your library — no tag or review data available."

                if cs == 'Unfinished':
                    reason += " You've started this one before."

                picks.append({"game": game, "reason": reason})
                remaining = [g for g in remaining if g['appid'] != game['appid']]

        else:
            db.close()
            for g in random.sample(games, min(NUM_PICKS, len(games))):
                picks.append({"game": g, "reason": None})

        return jsonify({
            "status":    "success",
            "picks":     picks,
            "pool_size": len(games)
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
        import subprocess, platform
        url = (request.json or {}).get('url', '')
        if not url:
            return jsonify({"status": "error", "message": "No URL provided"}), 400
        # Only allow http/https/steam schemes
        if not (url.startswith('http://') or url.startswith('https://') or url.startswith('steam://')):
            return jsonify({"status": "error", "message": "Scheme not allowed"}), 400
        try:
            sys = platform.system()
            if sys == 'Darwin':
                subprocess.Popen(['open', url])
            elif sys == 'Linux':
                subprocess.Popen(['xdg-open', url])
            else:
                subprocess.Popen(f'start "" "{url}"', shell=True)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/launch/<int:appid>', methods=['POST'])
    def launch_game(appid):
        import subprocess
        import platform

        # Always attempt to open the game via Steam
        try:
            if platform.system() == 'Darwin':
                subprocess.Popen(['open', f'steam://run/{appid}'])
            elif platform.system() == 'Linux':
                subprocess.Popen(['xdg-open', f'steam://run/{appid}'])
            elif platform.system() == 'Windows':
                subprocess.Popen(['cmd', '/c', f'start steam://run/{appid}'])
            print(f"Launched AppID: {appid}")
        except Exception as e:
            print(f"Failed to launch AppID {appid}: {e}")

        # Record the launch date only if the game is marked installed
        new_date = record_launch(appid)
        if new_date:
            return jsonify({"status": "success", "last_played": new_date})
        else:
            return jsonify({"status": "launched", "message": "Game launched but not marked installed — date not updated"})

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
            source = sgdb_source_map[orientation] if 'steamgriddb.com' in url else 'custom'
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
            bg_path = os.path.join(BASE_DIR, 'static', 'img', 'backgrounds', 'background.jpg')
            if os.path.exists(bg_path):
                os.remove(bg_path)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/pending-date', methods=['POST', 'OPTIONS'])
    def pending_date_set():
        if request.method == 'OPTIONS':
            return ('', 204)
        origin = request.headers.get('Origin', '')
        if origin and not origin.startswith('https://help.steampowered.com'):
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
        appids = data.get('appids', [])
        if not appids:
            return jsonify({'status': 'error', 'message': 'No games provided.'}), 400
        db  = get_db()
        ph  = ','.join('?' * len(appids))
        rows = db.execute(f'SELECT appid, name FROM games WHERE appid IN ({ph})', appids).fetchall()
        db.close()
        queue = [{'appid': r['appid'], 'name': r['name']} for r in rows]
        if not queue:
            return jsonify({'status': 'ok', 'total': 0, 'first_appid': None})
        _bulk_date_state.update({'queue': queue[1:], 'current': queue[0],
                                 'done': 0, 'failed': 0, 'total': len(queue),
                                 'active': True, 'script_connected': False,
                                 'results': []})
        log.info(f"Bulk date import started: {len(queue)} games queued")
        return jsonify({'status': 'ok', 'first_appid': queue[0]['appid'],
                        'first_name': queue[0]['name'], 'total': len(queue)})

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
        current = _bulk_date_state.get('current') or {}
        update_game_data(appid, date_added=date)
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

    @app.route('/api/game/<int:appid>')
    def get_game(appid):
        try:
            db  = get_db()
            row = db.execute("SELECT * FROM games WHERE appid = ?", (appid,)).fetchone()
            db.close()
            if row:
                return jsonify({"status": "success", "game": dict(row)})
            return jsonify({"status": "error", "message": "Game not found"}), 404
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

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

    @app.route('/api/bulk-rescrape', methods=['POST'])
    def bulk_rescrape():
        """
        Re-scrape Steam metadata for a list of appids.
        Runs synchronously and streams a JSON result when done.
        Called in chunks from the frontend to show progress.
        """
        from scrapers import fetch_store_data, fetch_tag_data, fetch_review_data, fetch_cheevo_data
        from config import get_active_account
        from datetime import datetime
        _account  = get_active_account() or {}
        _has_key  = bool(_account.get('api_key'))

        data   = request.json or {}
        appids = data.get('appids', [])
        if not appids:
            return jsonify({"status": "error", "message": "No appids provided."}), 400

        today   = datetime.now().strftime('%Y-%m-%d')
        updated = 0
        failed  = 0
        for appid in appids:
            try:
                store_data  = fetch_store_data(appid)  or {}
                store_data.pop('name', None)  # don't overwrite existing game names on rescrape
                store_data.pop('type', None)  # no type column in DB
                review_data = fetch_review_data(appid) or {}
                tag_data    = fetch_tag_data(appid)    or {}
                cheevo_data = fetch_cheevo_data(appid) or {} if _has_key else {}

                game_data = {}
                game_data.update(store_data)
                game_data.update(review_data)
                game_data.update(tag_data)
                game_data.update(cheevo_data)
                if store_data or review_data or tag_data:
                    game_data['meta_fetched'] = today
                if cheevo_data:
                    game_data['cheevos_fetched'] = today

                if game_data:
                    update_game_data(appid, **game_data)
                    updated += 1
                else:
                    failed += 1

            except Exception as e:
                log.warning(f"bulk_rescrape: failed for appid {appid}: {e}")
                failed += 1

        return jsonify({"status": "success", "updated": updated, "failed": failed})

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
                where = _filter_tree_to_sql(saved_filters[filter_key])
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
            return jsonify({'status': 'success', 'games': games})
        except Exception as e:
            log.exception(f"shuffle_shelf error for {shelf_id}: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/bulk-art-scrape', methods=['POST'])
    def bulk_art_scrape():
        import time
        from images import download_vertical, download_horizontal, download_icon, _get_steam_assets
        from datetime import datetime
        data   = request.json or {}
        appids = data.get('appids', [])
        types  = data.get('types', ['vertical', 'horizontal', 'icon'])
        source = data.get('source', 'auto')  # 'auto', 'steam', or 'sgdb'

        if not appids:
            return jsonify({"status": "error", "message": "No appids provided."}), 400

        today   = datetime.now().strftime('%Y-%m-%d')
        updated = 0
        failed  = 0
        for appid in appids:
            try:
                updates = {}
                # Fetch Steam asset manifest once and share between vertical + horizontal
                # to avoid two identical API calls per game.
                assets = _get_steam_assets(appid) if source != 'sgdb' else {}
                if 'vertical' in types:
                    result = download_vertical(appid, assets=assets, source=source)
                    if result != 'missing':
                        updates['vertical_art_source'] = result
                    time.sleep(1.2)
                if 'horizontal' in types:
                    result = download_horizontal(appid, assets=assets, source=source)
                    if result != 'missing':
                        updates['horizontal_art_source'] = result
                    time.sleep(1.2)
                if 'icon' in types:
                    db  = get_db()
                    row = db.execute("SELECT icon_hash FROM games WHERE appid = ?", (appid,)).fetchone()
                    db.close()
                    icon_hash = row['icon_hash'] if row else None
                    result = download_icon(appid, icon_hash, source=source)
                    if result != 'missing':
                        updates['icon_source'] = result
                    time.sleep(1.2)
                if updates:
                    updates['art_fetched'] = today
                    update_game_data(int(appid), **updates)
                    updated += 1
            except Exception as e:
                log.warning(f"bulk_art_scrape: failed for appid {appid}: {e}")
                failed += 1

        return jsonify({"status": "success", "updated": updated, "failed": failed})

    @app.route('/api/bulk-edit', methods=['POST'])
    def bulk_edit():
        from library import bulk_edit_games
        return bulk_edit_games(request.json)

    @app.route('/api/save-filter', methods=['POST'])
    def save_filter():
        from config import load_state, STATE_PATH
        data = request.json
        name = (data.get('name') or '').strip()
        tree = data.get('filter_tree')
        if not name:
            return jsonify({"status": "error", "message": "Name cannot be empty."}), 400
        if not tree:
            return jsonify({"status": "error", "message": "No filter to save."}), 400
        state = load_state()
        if 'saved_filters' not in state:
            state['saved_filters'] = {}
        state['saved_filters'][name] = tree
        with open(STATE_PATH, 'w') as f:
            json.dump(state, f, indent=4)
        return jsonify({"status": "success"})

    @app.route('/api/delete-filter', methods=['POST'])
    def delete_filter():
        from config import load_state, STATE_PATH
        name = (request.json.get('name') or '').strip()
        if not name:
            return jsonify({"status": "error", "message": "Name required."}), 400
        state = load_state()
        state.get('saved_filters', {}).pop(name, None)
        with open(STATE_PATH, 'w') as f:
            json.dump(state, f, indent=4)
        return jsonify({"status": "success"})

    @app.route('/api/rename-filter', methods=['POST'])
    def rename_filter():
        from config import load_state, STATE_PATH
        old_name = (request.json.get('old_name') or '').strip()
        new_name = (request.json.get('new_name') or '').strip()
        if not old_name or not new_name:
            return jsonify({"status": "error", "message": "Both names required."}), 400
        state = load_state()
        filters = state.get('saved_filters', {})
        if old_name not in filters:
            return jsonify({"status": "error", "message": "Filter not found."}), 404
        if new_name in filters:
            return jsonify({"status": "error", "message": f'A filter named "{new_name}" already exists.'}), 400
        filters[new_name] = filters.pop(old_name)
        state['saved_filters'] = filters
        with open(STATE_PATH, 'w') as f:
            json.dump(state, f, indent=4)
        return jsonify({"status": "success"})

    @app.route('/api/export-filter', methods=['POST'])
    def export_filter_file():
        data = request.json
        path = (data.get('path') or '').strip()
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
        path = (request.json.get('path') or '').strip()
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
            # Delete DB entry
            db = get_db()
            db.execute("DELETE FROM games WHERE appid = ?", (appid,))
            db.commit()
            db.close()

            # Delete all cached images
            for subdir in ('vertical', 'horizontal', 'icons'):
                img_path = os.path.join(BASE_DIR, 'static', 'img', 'library', subdir, f'{appid}.jpg')
                if os.path.exists(img_path):
                    os.remove(img_path)

            # Optionally blacklist
            if blacklist:
                add_to_blacklist(appid, name)

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
                for subdir in ('vertical', 'horizontal', 'icons'):
                    img_path = os.path.join(BASE_DIR, 'static', 'img', 'library', subdir, f'{appid}.jpg')
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
        zip_path = data.get('path', '').strip()
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
        db = get_db()
        updated = 0
        for appid, date_str in date_map.items():
            cursor = db.execute(
                "UPDATE games SET date_added = ? WHERE appid = ?",
                (date_str, appid)
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

    @app.route('/api/pagywosg-auto')
    def pagywosg_auto():
        import re
        import json
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
        _icaio_ga_dict = {g['appid']: g['name'] for g in _supplement.get('icaio_giveaways', [])}
        _icaio_wl_dict = {int(k): v for k, v in _supplement.get('icaio_wishlist', {}).items()}

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

            # Everything else: use verified appids if available
            if base_appids:
                _add_appids(base_appids, base)
            else:
                skipped.append(base)

        # --- Supplement JSON (event-specific entries) ---
        supplement_loaded = False
        if _supplement:
            try:
                supplement = _supplement
                db = get_db()
                for _cat_id, sdata in supplement.get(str(event_id), {}).items():
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

        # Determine which appids are in the user's library
        all_appids_combined = list(appids_wins.keys()) + list(appids_all.keys())
        in_library_set = set()
        if all_appids_combined:
            from database import get_db
            db = get_db()
            placeholders = ','.join('?' * len(all_appids_combined))
            rows = db.execute(
                f'SELECT appid FROM games WHERE appid IN ({placeholders})',
                all_appids_combined
            ).fetchall()
            in_library_set = {r['appid'] for r in rows}

        _COMMA_SEP_COLS = {'tags', 'groups', 'genres', 'categories', 'developers', 'publishers'}

        def _redundant_set(pool_dict, tags, conds):
            """Return appids already matched by the pool's tag/condition criteria (not needing the explicit appid list)."""
            owned = [aid for aid in pool_dict if aid in in_library_set]
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
            ph = ','.join('?' * len(owned))
            where = ' OR '.join(parts)
            db = get_db()
            rows = db.execute(
                f'SELECT appid FROM games WHERE appid IN ({ph}) AND ({where})',
                owned + params
            ).fetchall()
            return {r['appid'] for r in rows}

        def _serialise_pool(pool_dict, tags, conds):
            redundant = _redundant_set(pool_dict, tags, conds)
            return {
                "appids": sorted(pool_dict.keys()),
                "games":  sorted(
                    [{"appid": aid, "name": v["name"], "categories": v["categories"],
                      "in_library": aid in in_library_set,
                      "redundant":  aid in redundant}
                     for aid, v in pool_dict.items()],
                    key=lambda g: g["name"].lower()
                ),
            }

        return jsonify({
            "status": "success",
            "event": {"id": event_id, "name": event.get('name', '')},
            "tags":   {"wins": tags_wins, "all": tags_all},
            "conds":  {"wins": conds_wins, "all": conds_all},
            "wins":   _serialise_pool(appids_wins, tags_wins, conds_wins),
            "all":    _serialise_pool(appids_all,  tags_all,  conds_all),
            "skipped": skipped,
            "supplement_loaded": supplement_loaded,
        })

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
    @app.route('/api/backup', methods=['POST'])
    def backup():
        import zipfile
        import io
        from datetime import datetime
        from flask import send_file

        data        = request.json or {}
        include_art = data.get('include_art', False)

        buf = io.BytesIO()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Core data files — always included
            core_files = {
                'config.json': os.path.join(BASE_DIR, 'config.json'),
                'state.json':  os.path.join(BASE_DIR, 'state.json'),
            }
            for arcname, filepath in core_files.items():
                if os.path.exists(filepath):
                    zf.write(filepath, arcname)
            # All per-account databases
            import glob as _glob
            for db_path in _glob.glob(os.path.join(BASE_DIR, 'games_*.db')):
                zf.write(db_path, os.path.basename(db_path))

            # Optional: custom artwork (recurse into vertical/, horizontal/, icons/)
            if include_art:
                art_dir = os.path.join(BASE_DIR, 'static', 'img', 'library')
                if os.path.isdir(art_dir):
                    for dirpath, _, filenames in os.walk(art_dir):
                        for fname in filenames:
                            if fname.lower().endswith('.jpg'):
                                full = os.path.join(dirpath, fname)
                                arcname = os.path.relpath(full, BASE_DIR).replace(os.sep, '/')
                                zf.write(full, arcname)

        buf.seek(0)
        return send_file(
            buf,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'playdate_backup_{timestamp}.zip'
        )

    @app.route('/api/backup-to-path', methods=['POST'])
    def backup_to_path():
        """
        Write the backup zip directly to a path chosen via pywebview's native
        Save-As dialog (path is passed in the request body).  Used by the
        pywebview build; the browser fallback still uses /api/backup.
        """
        import zipfile
        data        = request.json or {}
        save_path   = data.get('path', '').strip()
        include_art = data.get('include_art', False)

        if not save_path:
            return jsonify({"status": "error", "message": "No path provided."}), 400

        try:
            with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                core_files = {
                    'config.json': os.path.join(BASE_DIR, 'config.json'),
                    'state.json':  os.path.join(BASE_DIR, 'state.json'),
                }
                for arcname, filepath in core_files.items():
                    if os.path.exists(filepath):
                        zf.write(filepath, arcname)
                import glob as _glob
                for db_path in _glob.glob(os.path.join(BASE_DIR, 'games_*.db')):
                    zf.write(db_path, os.path.basename(db_path))

                if include_art:
                    art_dir = os.path.join(BASE_DIR, 'static', 'img', 'library')
                    if os.path.isdir(art_dir):
                        for dirpath, _, filenames in os.walk(art_dir):
                            for fname in filenames:
                                if fname.lower().endswith('.jpg'):
                                    full = os.path.join(dirpath, fname)
                                    arcname = os.path.relpath(full, BASE_DIR).replace(os.sep, '/')
                                    zf.write(full, arcname)
            size = os.path.getsize(save_path)
            return jsonify({"status": "success", "path": save_path, "size": size})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # ── CSV EXPORT ────────────────────────────────────────────────────────────

    def _build_csv_rows(filter_tree=None):
        """
        Query the DB and return (header_list, rows_list) for CSV export.
        Applies filter_tree if provided, otherwise exports all games.
        Playtime is converted from minutes to decimal hours.
        Achievements percentage is computed when both fields are present.
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
                from library import build_tree_sql
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
                r['last_played']        or '',
                r['date_added']         or '',
                'Yes' if r['installed'] else 'No',
                r['review_score']       or '',
                r['review_percentage']  if r['review_percentage'] is not None else '',
                r['developers']         or '',
                r['publishers']         or '',
                r['release_date']       or '',
                unlocked,
                total,
                cheevo_pct,
            ])
        return headers, out

    @app.route('/api/export-csv', methods=['POST'])
    def export_csv():
        """Stream a CSV file as a download (browser/fallback path)."""
        import csv, io
        from flask import send_file
        data        = request.json or {}
        filter_tree = data.get('filter_tree')
        try:
            headers, rows = _build_csv_rows(filter_tree)
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
        save_path   = data.get('path', '').strip()
        filter_tree = data.get('filter_tree')
        if not save_path:
            return jsonify({"status": "error", "message": "No path provided."}), 400
        try:
            headers, rows = _build_csv_rows(filter_tree)
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
        from config import load_state
        state       = load_state()
        filter_tree = state.get('filter_tree')
        return jsonify({"status": "success", "filter_tree": filter_tree})

    @app.route('/api/theme-to-path', methods=['POST'])
    def theme_to_path():
        """Write a theme JSON directly to a user-chosen path."""
        from config import DEFAULT_THEME
        data      = request.json or {}
        save_path = data.get('path', '').strip()
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

                # Core files: restore to BASE_DIR
                for arcname in ('config.json', 'state.json'):
                    if arcname in names:
                        dest = os.path.join(BASE_DIR, arcname)
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
                    dest = os.path.join(BASE_DIR, arcname)
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
                        dest = os.path.join(BASE_DIR, arcname.replace('/', os.sep))
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
            import time, tempfile, urllib.request
            time.sleep(0.5)  # let the HTTP response send first
            try:
                if getattr(sys, 'frozen', False):
                    # Windows frozen exe: download installer and launch it
                    url = _update_cache.get('installer_url')
                    if not url:
                        log.error("perform-update: no installer URL cached")
                        return
                    tmp = os.path.join(tempfile.gettempdir(), 'PlayDate-Setup.exe')
                    log.info(f"Downloading installer: {url}")
                    urllib.request.urlretrieve(url, tmp)
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
                        return
                    tmp_zip = os.path.join(tempfile.gettempdir(), 'playdate-update.zip')
                    log.info(f"Downloading source zip: {url}")
                    urllib.request.urlretrieve(url, tmp_zip)
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
                return
            os._exit(0)

        threading.Thread(target=_do_update, daemon=True).start()
        return jsonify({'status': 'ok'})

    # ── Background update check on startup ───────────────────────────────────
    def _startup_update_check():
        import time
        time.sleep(5)
        from config import load_state
        if load_state().get('check_for_updates', True):
            _do_update_check()

    threading.Thread(target=_startup_update_check, daemon=True).start()

    return app


# ── Backwards compatibility: module-level `app` for running directly ──────────
# Only create at module level when running as the entry point, not when imported
# by main.py (which calls create_app() itself, avoiding a double startup).
if __name__ == '__main__' or os.environ.get('FLASK_APP') == 'app':
    app = create_app()

if __name__ == '__main__':
    from config import migrate_to_multi_account
    migrate_to_multi_account()
    init_db()
    migrate_image_files()
    app.run(debug=True, port=5000)
