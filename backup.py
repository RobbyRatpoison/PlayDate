"""Backup/restore (full zip of config, DBs, and optionally cover art) and
CSV library export. Restore runs in a background thread and is polled —
see CLAUDE.md's feedback on Flatpak portal-path timeouts for why."""
import logging
import os
import threading

from flask import Blueprint, jsonify, request

from config import BASE_DIR
from database import get_db
from utils import validate_user_path

log = logging.getLogger(__name__)

backup_bp = Blueprint('backup', __name__)

_restore_lock  = threading.Lock()
_restore_state = {'status': 'idle', 'error': None, 'restored': None, 'skipped': None}  # idle|running|success|error


def _extract_backup_zip(raw: bytes, logger):
    """
    Extract a PlayDate backup zip's contents into BASE_DIR / static/img/library.
    Shared by the upload and path-based restore routes. Returns (restored, skipped)
    lists of arcnames. Raises zipfile.BadZipFile or other exceptions on failure.
    """
    import zipfile, io

    buf = io.BytesIO(raw)
    with zipfile.ZipFile(buf, 'r') as zf:
        names = zf.namelist()
        logger.info(f"Restore: zip contains {len(names)} entries: {names[:20]}")

        restored = []
        skipped  = []
        _base_real = os.path.realpath(BASE_DIR)

        def _safe_dest(rel):
            """Resolve a relative ZIP entry path and confirm it stays within BASE_DIR."""
            dest = os.path.realpath(os.path.join(BASE_DIR, rel.replace('/', os.sep)))
            return dest if dest.startswith(_base_real + os.sep) or dest == _base_real else None

        # Core files: restore to BASE_DIR
        for arcname in ('config.json', 'state.json', 'theme.json',
                        'emulators.json', 'santa_gifts.json'):
            if arcname in names:
                dest = _safe_dest(arcname)
                if not dest:
                    continue
                with zf.open(arcname) as src:
                    data = src.read()
                with open(dest, 'wb') as dst:
                    dst.write(data)
                logger.info(f"Restore: wrote {len(data)} bytes -> {dest}")
                restored.append(arcname)
            else:
                logger.warning(f"Restore: {arcname!r} not found in zip -- skipping")
                skipped.append(arcname)

        # Per-account databases: games_*.db
        for arcname in [n for n in names if n.startswith('games_') and n.endswith('.db')]:
            dest = _safe_dest(arcname)
            if not dest:
                continue
            with zf.open(arcname) as src:
                data = src.read()
            with open(dest, 'wb') as dst:
                dst.write(data)
            logger.info(f"Restore: wrote {len(data)} bytes -> {dest}")
            restored.append(arcname)

        # Per-account group sources: group_sources_*.json
        for arcname in [n for n in names if n.startswith('group_sources_') and n.endswith('.json')]:
            dest = _safe_dest(arcname)
            if not dest:
                continue
            with zf.open(arcname) as src:
                data = src.read()
            with open(dest, 'wb') as dst:
                dst.write(data)
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
            logger.info(f"Restore: wrote {len(art_files)} cover image(s)")
            restored.append(f"{len(art_files)} cover image(s)")

    return restored, skipped


def _run_restore_thread(raw: bytes, logger):
    """Runs off the request thread: extract, migrate, and update _restore_state."""
    import zipfile
    try:
        restored, skipped = _extract_backup_zip(raw, logger)
    except zipfile.BadZipFile:
        logger.exception("Restore: bad zip file")
        _restore_state.update({'status': 'error', 'error': 'Invalid zip file. Make sure this is a PlayDate backup.'})
        return
    except Exception as e:
        logger.exception(f"Restore: unexpected error -- {e}")
        _restore_state.update({'status': 'error', 'error': f'Restore failed: {e}'})
        return

    logger.info(f"Restore: complete -- restored={restored}, skipped={skipped}")

    # Run migrations and re-initialise the DB -- the restored data may be
    # from an older version that predates recent schema changes.
    try:
        import migration as _migration
        from database import init_db
        _migration.run()
        init_db()
    except Exception as e:
        logger.warning(f"Restore: post-restore migration failed: {e}", exc_info=True)

    _restore_state.update({'status': 'success', 'error': None, 'restored': restored, 'skipped': skipped})


def _fill_backup_zip(zf, include_art):
    import glob as _glob
    for arcname, filepath in {'config.json':      os.path.join(BASE_DIR, 'config.json'),
                               'state.json':       os.path.join(BASE_DIR, 'state.json'),
                               'theme.json':       os.path.join(BASE_DIR, 'theme.json'),
                               'emulators.json':   os.path.join(BASE_DIR, 'emulators.json'),
                               'santa_gifts.json': os.path.join(BASE_DIR, 'santa_gifts.json')}.items():
        if os.path.exists(filepath):
            zf.write(filepath, arcname)
    for db_path in _glob.glob(os.path.join(BASE_DIR, 'games_*.db')):
        zf.write(db_path, os.path.basename(db_path))
    for gs_path in _glob.glob(os.path.join(BASE_DIR, 'group_sources_*.json')):
        zf.write(gs_path, os.path.basename(gs_path))
    if include_art:
        art_dir = os.path.join(BASE_DIR, 'static', 'img', 'library')
        if os.path.isdir(art_dir):
            for dirpath, _, filenames in os.walk(art_dir):
                for fname in filenames:
                    if fname.lower().endswith('.jpg'):
                        full = os.path.join(dirpath, fname)
                        zf.write(full, os.path.relpath(full, BASE_DIR).replace(os.sep, '/'))


def _build_csv_rows(filter_tree=None, columns=None):
    """
    Query the DB and return (header_list, rows_list) for CSV export.
    Applies filter_tree if provided, otherwise exports all games.
    Playtime is converted from minutes to decimal hours.
    Achievements percentage is computed when both fields are present.
    columns: optional list of header names to include (None = all).
    """
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


@backup_bp.route('/api/backup', methods=['POST'])
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

@backup_bp.route('/api/backup-to-path', methods=['POST'])
def backup_to_path():
    """
    Write the backup zip directly to a path chosen via pywebview's native
    Save-As dialog (path is passed in the request body).  Used by the
    pywebview build; the browser fallback still uses /api/backup.
    """
    import zipfile
    data        = request.json or {}
    save_path   = validate_user_path(data.get('path', '').strip())
    include_art = data.get('include_art', False)
    if not save_path:
        return jsonify({"status": "error", "message": "No path provided."}), 400
    try:
        with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            _fill_backup_zip(zf, include_art)
        return jsonify({"status": "success", "path": save_path, "size": os.path.getsize(save_path)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@backup_bp.route('/api/export-csv', methods=['POST'])
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

@backup_bp.route('/api/export-csv-to-path', methods=['POST'])
def export_csv_to_path():
    """Write CSV directly to a user-chosen path (pywebview save-dialog path)."""
    import csv
    data        = request.json or {}
    save_path   = validate_user_path(data.get('path', '').strip())
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

@backup_bp.route('/api/current-filter')
def current_filter():
    """Return the active filter_tree from state — used by the tools page CSV exporter."""
    from config import load_state, resolve_active_filter_tree
    state       = load_state()
    filter_tree = resolve_active_filter_tree(state)
    return jsonify({"status": "success", "filter_tree": filter_tree})

# ── RESTORE ───────────────────────────────────────────────────────────────
# Extraction runs in a background thread and is polled via /api/restore-status
# rather than blocking the request — a large backup (cover art included) can
# take long enough, especially reading through a Flatpak portal-mounted path,
# that the client's HTTP connection gives up before a synchronous response
# would ever be sent.
@backup_bp.route('/api/restore', methods=['POST'])
def restore():
    with _restore_lock:
        if _restore_state['status'] == 'running':
            return jsonify({"status": "error", "message": "A restore is already in progress."}), 409

        if 'backup_file' not in request.files:
            log.warning("Restore: no backup_file in request.files")
            return jsonify({"status": "error", "message": "No file uploaded."}), 400

        f = request.files['backup_file']
        if not f.filename.endswith('.zip'):
            return jsonify({"status": "error", "message": "File must be a .zip backup."}), 400

        raw = f.read()
        log.info(f"Restore: read {len(raw)} bytes from upload")

        _restore_state.update({'status': 'running', 'error': None, 'restored': None, 'skipped': None})
        threading.Thread(target=_run_restore_thread, args=(raw, log), daemon=True).start()
    return jsonify({"status": "started"})

@backup_bp.route('/api/restore-from-path', methods=['POST'])
def restore_from_path():
    path = validate_user_path((request.json or {}).get('path', '').strip())
    if not path or not os.path.isfile(path):
        return jsonify({"status": "error", "message": "File not found."}), 400
    if not path.endswith('.zip'):
        return jsonify({"status": "error", "message": "File must be a .zip backup."}), 400

    def _read_then_restore():
        try:
            with open(path, 'rb') as fh:
                raw = fh.read()
        except Exception as e:
            log.warning(f"Restore-from-path: could not read file: {e}")
            _restore_state.update({'status': 'error', 'error': f'Could not read file: {e}'})
            return
        _run_restore_thread(raw, log)

    with _restore_lock:
        if _restore_state['status'] == 'running':
            return jsonify({"status": "error", "message": "A restore is already in progress."}), 409
        _restore_state.update({'status': 'running', 'error': None, 'restored': None, 'skipped': None})
        threading.Thread(target=_read_then_restore, daemon=True).start()
    return jsonify({"status": "started"})

@backup_bp.route('/api/restore-status')
def restore_status():
    return jsonify(_restore_state)
