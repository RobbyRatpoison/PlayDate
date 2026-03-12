from flask import Flask, render_template, redirect, request, url_for, jsonify, send_from_directory
import logging
from logging.handlers import RotatingFileHandler
import os
import sys

# ── Logging Setup — must be first so import errors are captured ───────────────
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'playdate.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=0, encoding='utf-8'),
        logging.StreamHandler()
    ],
    force=True
)
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
from database import get_db, init_db, update_game_data
from migrate_tags import migrate_missing_tags, cancel_migration
import re
import scrapers
import threading
import json


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

    # ── Cancellation state for populate ──────────────────────────────────────
    _populate_cancel  = threading.Event()
    _populate_state   = {"running": False, "last_result": None}

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.route('/pick')
    def pick():
        from config import load_state
        state = load_state()
        has_filters = bool(state.get('filter_tree') and state['filter_tree'].get('items'))
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

    @app.route('/tools')
    def tools():
        from config import load_state
        return render_template('tools.html', state=load_state())

    @app.route('/api/populate-status')
    def populate_status():
        return jsonify({"running": _populate_state["running"], "last_result": _populate_state["last_result"]})

    @app.route('/add-new')
    def add_new():
        _populate_cancel.clear()
        _populate_state["running"] = True
        _populate_state["last_result"] = None
        try:
            result = scrapers.add_new(_populate_cancel)
            _populate_state["last_result"] = result
        finally:
            _populate_state["running"] = False
        return jsonify(result)

    @app.route('/api/cancel-populate', methods=['POST'])
    def cancel_populate():
        _populate_cancel.set()
        return jsonify({"status": "success"})

    @app.route('/update-installed')
    def update_installed():
        try:
            count = sync_local_install_status()
            return jsonify({"status": "success", "count": count})
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

        player_data = fetch_player_data(appid) or {}
        store_data  = fetch_store_data(appid) or {}
        review_data = fetch_review_data(appid) or {}
        cheevo_data = fetch_cheevo_data(appid) or {}
        tag_data    = fetch_tag_data(appid) or {}

        combined_data = {
            "status": "success",
            "data": {
                "name":                   player_data.get('name', ''),
                "playtime_forever":       player_data.get('playtime_forever', ''),
                "last_played":            player_data.get('last_played', ''),
                "developers":             store_data.get('developers', ''),
                "publishers":             store_data.get('publishers', ''),
                "release_date":           store_data.get('release_date', ''),
                "review_score":           review_data.get('review_score', ''),
                "review_percentage":      review_data.get('review_percentage', ''),
                "weighted_percentage":    review_data.get('weighted_percentage', ''),
                "total_reviews":          review_data.get('total_reviews', ''),
                "positive_reviews":       review_data.get('positive_reviews', ''),
                "total_achievements":     cheevo_data.get('total_achievements', 0),
                "unlocked_achievements":  cheevo_data.get('unlocked_achievements', 0),
                "tags":                   tag_data.get('tags', '')
            }
        }
        return jsonify(combined_data)

    @app.route('/api/download-artwork/<int:appid>', methods=['POST'])
    def download_artwork(appid):
        data = request.json
        url = data.get('url', '').strip()
        if not url:
            return jsonify({"status": "error", "message": "No URL provided"}), 400
        from images import download_from_url
        result = download_from_url(appid, url)
        if result == "custom":
            update_game_data(appid, art_source="custom")
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": "Failed to download image. Check the URL and try again."}), 500

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

    @app.route('/api/delete-game/<int:appid>', methods=['DELETE'])
    def delete_game(appid):
        try:
            db = get_db()
            db.execute("DELETE FROM games WHERE appid = ?", (appid,))
            db.commit()
            db.close()
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/import-inspect', methods=['POST'])
    def import_inspect():
        return inspect_database(request.files)

    @app.route('/api/import-execute', methods=['POST'])
    def import_execute():
        return execute_import(request.json)

    @app.route('/sync-blaeo')
    def sync_blaeo():
        try:
            result = scrape_blaeo_games()
            return jsonify(result)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/api/migrate-tags', methods=['POST'])
    def start_tag_migration():
        thread = threading.Thread(target=migrate_missing_tags)
        thread.daemon = True
        thread.start()
        return jsonify({"status": "success", "message": "Migration started."})

    @app.route('/api/cancel-tags', methods=['POST'])
    def stop_tag_migration():
        cancel_migration()
        return jsonify({"status": "success"})

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
                'games.db':    os.path.join(BASE_DIR, 'games.db'),
                'config.json': os.path.join(BASE_DIR, 'config.json'),
                'state.json':  os.path.join(BASE_DIR, 'state.json'),
            }
            for arcname, filepath in core_files.items():
                if os.path.exists(filepath):
                    zf.write(filepath, arcname)

            # Optional: custom artwork
            if include_art:
                art_dir = os.path.join(BASE_DIR, 'static', 'img', 'library')
                if os.path.isdir(art_dir):
                    for fname in os.listdir(art_dir):
                        if fname.lower().endswith('.jpg'):
                            zf.write(
                                os.path.join(art_dir, fname),
                                os.path.join('static', 'img', 'library', fname)
                            )

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
                    'games.db':    os.path.join(BASE_DIR, 'games.db'),
                    'config.json': os.path.join(BASE_DIR, 'config.json'),
                    'state.json':  os.path.join(BASE_DIR, 'state.json'),
                }
                for arcname, filepath in core_files.items():
                    if os.path.exists(filepath):
                        zf.write(filepath, arcname)

                if include_art:
                    art_dir = os.path.join(BASE_DIR, 'static', 'img', 'library')
                    if os.path.isdir(art_dir):
                        for fname in os.listdir(art_dir):
                            if fname.lower().endswith('.jpg'):
                                zf.write(
                                    os.path.join(art_dir, fname),
                                    os.path.join('static', 'img', 'library', fname)
                                )
            size = os.path.getsize(save_path)
            return jsonify({"status": "success", "path": save_path, "size": size})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # ── RESTORE ───────────────────────────────────────────────────────────────
    @app.route('/api/restore', methods=['POST'])
    def restore():
        import zipfile
        import io

        if 'backup_file' not in request.files:
            return jsonify({"status": "error", "message": "No file uploaded."}), 400

        f = request.files['backup_file']
        if not f.filename.endswith('.zip'):
            return jsonify({"status": "error", "message": "File must be a .zip backup."}), 400

        try:
            buf = io.BytesIO(f.read())
            with zipfile.ZipFile(buf, 'r') as zf:
                names = zf.namelist()

                restored = []
                skipped  = []

                # Core files: restore to BASE_DIR
                for arcname in ('games.db', 'config.json', 'state.json'):
                    if arcname in names:
                        dest = os.path.join(BASE_DIR, arcname)
                        with zf.open(arcname) as src, open(dest, 'wb') as dst:
                            dst.write(src.read())
                        restored.append(arcname)
                    else:
                        skipped.append(arcname)

                # Art files: restore to static/img/library/
                art_files = [n for n in names if n.startswith('static/img/library/') and n.endswith('.jpg')]
                if art_files:
                    art_dir = os.path.join(BASE_DIR, 'static', 'img', 'library')
                    os.makedirs(art_dir, exist_ok=True)
                    for arcname in art_files:
                        dest = os.path.join(BASE_DIR, arcname.replace('/', os.sep))
                        with zf.open(arcname) as src, open(dest, 'wb') as dst:
                            dst.write(src.read())
                    restored.append(f"{len(art_files)} cover image(s)")

        except zipfile.BadZipFile:
            return jsonify({"status": "error", "message": "Invalid zip file. Make sure this is a PlayDate backup."}), 400
        except Exception as e:
            return jsonify({"status": "error", "message": f"Restore failed: {str(e)}"}), 500

        return jsonify({
            "status":   "success",
            "restored": restored,
            "skipped":  skipped,
        })

    return app


# ── Backwards compatibility: module-level `app` for running directly ──────────
# `python app.py` or `flask run` still works without needing main.py
app = create_app()

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
