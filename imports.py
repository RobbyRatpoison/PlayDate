import bisect
import os
import re
import struct
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from flask import jsonify, request
from database import get_db
from config import BASE_DIR

TEMP_DB_PATH = os.path.join(BASE_DIR, "temp_import.db")

# ── Step 1: Upload DB and return its tables + columns ──
def inspect_database(request_files):
    if 'external_db' not in request_files:
        return jsonify({"status": "error", "message": "No file uploaded"})

    file = request_files['external_db']
    if os.path.exists(TEMP_DB_PATH):
        os.remove(TEMP_DB_PATH)
    file.save(TEMP_DB_PATH)

    try:
        ext_conn = sqlite3.connect(TEMP_DB_PATH)
        ext_cur = ext_conn.cursor()

        # Get all tables
        tables = [row[0] for row in ext_cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]

        if not tables:
            ext_conn.close()
            os.remove(TEMP_DB_PATH)
            return jsonify({"status": "error", "message": "No tables found in this database."})

        # Get columns and types for each table
        table_columns = {}
        table_column_types = {}
        for table in tables:
            pragma = ext_cur.execute(f"PRAGMA table_info({table})").fetchall()
            table_columns[table] = [row[1] for row in pragma]
            table_column_types[table] = {row[1]: row[2].upper() for row in pragma}

        ext_conn.close()

        # Get local DB columns and types
        local_db = get_db()
        local_pragma = local_db.execute("PRAGMA table_info(games)").fetchall()
        local_cols = [row[1] for row in local_pragma]
        local_col_types = {row[1]: row[2].upper() for row in local_pragma}
        local_db.close()

        return jsonify({
            "status": "success",
            "tables": tables,
            "table_columns": table_columns,
            "table_column_types": table_column_types,
            "local_columns": local_cols,
            "local_column_types": local_col_types
        })

    except Exception as e:
        if os.path.exists(TEMP_DB_PATH):
            os.remove(TEMP_DB_PATH)
        return jsonify({"status": "error", "message": f"Could not read database: {str(e)}"})


def _types_compatible(src_type, tgt_type):
    """
    Returns (compatible: bool, warning: str|None).
    SQLite is loosely typed, so we only warn on INT<->TEXT mismatches
    where data loss is likely, not block the import entirely.
    """
    # Normalize — SQLite types can be things like "INTEGER", "INT", "TEXT", "REAL"
    def bucket(t):
        t = t.upper()
        if any(x in t for x in ('INT', 'NUM', 'REAL', 'FLOAT')):
            return 'numeric'
        return 'text'

    sb, tb = bucket(src_type), bucket(tgt_type)
    if sb != tb:
        return False, f"Type mismatch: source is {src_type}, target is {tgt_type}. Values will be imported as-is — numeric columns may receive text data."
    return True, None


# ── Step 2: Execute the import with user-specified column mappings ──
def normalize_date(value):
    """Try to parse a date value into YYYY-MM-DD. Returns original if unparseable."""
    if not value:
        return value
    value = str(value).strip()

    # Already correct format
    if re.match(r'^\d{4}-\d{2}-\d{2}$', value):
        return value

    # Unix timestamp (integer seconds)
    if re.match(r'^\d{9,11}$', value):
        try:
            return datetime.utcfromtimestamp(int(value)).strftime('%Y-%m-%d')
        except Exception:
            pass

    formats = [
        '%d %b %Y',     # 15 Jan 2020
        '%b %d, %Y',    # Jan 15, 2020
        '%B %d, %Y',    # January 15, 2020
        '%d/%m/%Y',     # 15/01/2020
        '%m/%d/%Y',     # 01/15/2020
        '%d-%m-%Y',     # 15-01-2020
        '%Y/%m/%d',     # 2020/01/15
        '%d.%m.%Y',     # 15.01.2020
        '%Y%m%d',       # 20200115
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return value  # return as-is if nothing matched


def execute_import(data):
    """
    data = {
        "table": "games",                          # source table name
        "appid_column": "appid",                   # source column to match on appid
        "mappings": [                              # list of {source, target} column pairs
            {"source": "date_added", "target": "date_added"},
            {"source": "status",     "target": "completion_status"}
        ],
        "normalize_dates": true                    # whether to try date normalization
    }
    """
    if not os.path.exists(TEMP_DB_PATH):
        return jsonify({"status": "error", "message": "No uploaded database found. Please upload again."})

    table = data.get("table")
    appid_col = data.get("appid_column", "appid")
    mappings = data.get("mappings", [])
    normalize_dates = data.get("normalize_dates", False)

    if not table or not mappings:
        return jsonify({"status": "error", "message": "Table and at least one column mapping are required."})

    try:
        ext_conn = sqlite3.connect(TEMP_DB_PATH)
        ext_conn.row_factory = sqlite3.Row
        ext_cur = ext_conn.cursor()

        # Build type maps for warning generation
        src_pragma = {row[1]: row[2].upper() for row in ext_cur.execute(f"PRAGMA table_info({table})").fetchall()}

        local_db_check = get_db()
        tgt_pragma = {row[1]: row[2].upper() for row in local_db_check.execute("PRAGMA table_info(games)").fetchall()}
        local_db_check.close()

        # Check type compatibility for all mappings and collect warnings
        type_warnings = []
        for mapping in mappings:
            src_col = mapping["source"]
            tgt_col = mapping["target"]
            src_type = src_pragma.get(src_col, 'TEXT')
            tgt_type = tgt_pragma.get(tgt_col, 'TEXT')
            compatible, warning = _types_compatible(src_type, tgt_type)
            if warning:
                type_warnings.append(f"{src_col} → {tgt_col}: {warning}")

        source_cols = [appid_col] + [m["source"] for m in mappings if m["source"] != appid_col]
        col_list = ", ".join(source_cols)
        rows = ext_cur.execute(f"SELECT {col_list} FROM {table}").fetchall()
        ext_conn.close()

        local_db = get_db()
        updated_count = 0
        skipped_count = 0

        for row in rows:
            row = dict(row)
            appid = row.get(appid_col)
            if not appid:
                skipped_count += 1
                continue

            update_kwargs = {}
            for mapping in mappings:
                src = mapping["source"]
                tgt = mapping["target"]
                val = row.get(src)
                if val is None or str(val).strip() == '':
                    continue
                if normalize_dates:
                    val = normalize_date(val)
                update_kwargs[tgt] = val

            if not update_kwargs:
                skipped_count += 1
                continue

            set_clause = ", ".join(f"{k} = ?" for k in update_kwargs)
            values = list(update_kwargs.values()) + [appid]
            cursor = local_db.execute(
                f"UPDATE games SET {set_clause} WHERE appid = ?", values
            )
            if cursor.rowcount > 0:
                updated_count += 1
            else:
                skipped_count += 1

        local_db.commit()
        local_db.close()

        # Clean up temp file
        os.remove(TEMP_DB_PATH)

        return jsonify({
            "status": "success",
            "updated": updated_count,
            "skipped": skipped_count,
            "type_warnings": type_warnings
        })

    except Exception as e:
        if os.path.exists(TEMP_DB_PATH):
            os.remove(TEMP_DB_PATH)
        return jsonify({"status": "error", "message": f"Import error: {str(e)}"})


def parse_playnite_dates(zip_path):
    """
    Extracts 'date added' values for Steam games from a Playnite backup ZIP.
    Playnite stores its library in a LiteDB binary file (library/games.db inside the ZIP).
    Uses proximity matching between GameId and Added BSON fields (±8KB window) to pair them.
    Returns {appid_int: 'YYYY-MM-DD'} dict.
    """
    # Extract the LiteDB games.db from the ZIP to a temp file
    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = zf.namelist()
        games_db_entry = next(
            (n for n in names if n.replace('\\', '/').lower().endswith('library/games.db')),
            None
        )
        if not games_db_entry:
            return {}
        with tempfile.NamedTemporaryFile(delete=False, suffix='.litedb') as tmp:
            tmp_path = tmp.name
            tmp.write(zf.read(games_db_entry))

    try:
        with open(tmp_path, 'rb') as f:
            data = f.read()
    finally:
        os.unlink(tmp_path)

    # Extract all GameId string field positions and values.
    # BSON string: type=0x02, key="GameId\x00", then int32 length + bytes + null.
    gameids = []
    for m in re.finditer(b'\x02GameId\x00', data):
        pos = m.end()
        if pos + 4 > len(data):
            continue
        slen = struct.unpack_from('<i', data, pos)[0]
        if slen < 1 or slen > 20:
            continue
        val = data[pos + 4:pos + 4 + slen - 1].decode('utf-8', errors='replace')
        if val.isdigit():
            gameids.append((m.start(), int(val)))

    # Extract all Added datetime field positions and values.
    # BSON datetime: type=0x09, key="Added\x00", then int64 ms since Unix epoch.
    added_map = {}
    for m in re.finditer(b'\x09Added\x00', data):
        pos = m.end()
        if pos + 8 > len(data):
            continue
        ms = struct.unpack_from('<q', data, pos)[0]
        if 0 < ms < 4102444800000:  # sanity: between 1970 and 2100
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
            added_map[m.start()] = dt

    added_positions = sorted(added_map.keys())

    # Pair each GameId with its nearest Added field within ±8KB.
    # Documents span LiteDB 8KB pages, so large documents (with long descriptions) have their
    # fields split across non-contiguous file regions. However, GameId and Added are both short
    # metadata fields that typically land in the same page segment, keeping them within 8KB.
    WINDOW = 8192
    results = {}
    for gpos, appid in gameids:
        idx = bisect.bisect_left(added_positions, gpos)
        best_pos = None
        best_dist = WINDOW + 1
        for i in (idx - 1, idx):
            if 0 <= i < len(added_positions):
                apos = added_positions[i]
                dist = abs(apos - gpos)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = apos
        if best_pos is not None:
            results[appid] = added_map[best_pos]

    return results
