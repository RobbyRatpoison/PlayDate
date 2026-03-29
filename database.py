from config import BASE_DIR
import sqlite3
import os


def _db():
    """Returns the active account's database file path."""
    from config import get_active_db_path
    return get_active_db_path()


def get_db():
    db_file = _db()
    conn = sqlite3.connect(db_file, timeout=10)
    conn.row_factory = sqlite3.Row
    # Auto-init if the games table is missing (e.g. DB was deleted while running)
    try:
        conn.execute("SELECT 1 FROM games LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        init_db()
        conn = sqlite3.connect(db_file, timeout=10)
        conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database and ensures all columns exist."""
    db_file = _db()
    conn = sqlite3.connect(db_file, timeout=10)
    cursor = conn.cursor()

    # Create table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            appid INTEGER PRIMARY KEY,
            name TEXT
        )
    """)

    cursor.execute("PRAGMA table_info(games)")
    columns = [column[1] for column in cursor.fetchall()]

    # One-time migration: rename art_source → vertical_art_source
    if 'art_source' in columns and 'vertical_art_source' not in columns:
        cursor.execute("ALTER TABLE games RENAME COLUMN art_source TO vertical_art_source")
        columns = [c if c != 'art_source' else 'vertical_art_source' for c in columns]

    # Dictionary of all required columns for the current version of PlayDate
    required_columns = {
        'playtime_forever': 'INT',       # Total playtime in minutes
        'installed': 'INT',              # 1 for yes, 0 for no
        'last_played': 'TEXT',           # Last played timestamp
        'date_added': 'TEXT',            # Date added to library
        'developers': 'TEXT',            # Developer metadata
        'publishers': 'TEXT',            # Publisher metadata
        'completion_status': 'TEXT',     # e.g., "Not Played", "Completed"
        'tags': 'TEXT',                  # Genres/Tags
        'release_date': 'TEXT',          # Game release date
        'unlocked_achievements': 'INT',  # Achievements earned
        'total_achievements': 'INT',     # Total achievements available
        'review_score': 'TEXT',          # e.g., 'Very Positive'
        'review_percentage': 'INT',      # 0-100 score
        'vertical_art_source': 'TEXT',   # Source of vertical capsule art
        'horizontal_art_source': 'TEXT', # Source of horizontal header art
        'icon_source': 'TEXT',           # Source of game icon
        'icon_hash': 'TEXT',             # Steam icon hash for re-downloading
        'weighted_percentage': 'INT',    # Scaling penalties for total_reviews under 100
        'total_reviews': 'INT',
        'positive_reviews': 'INT',
        'groups': 'TEXT',
        'genres': 'TEXT',                # Comma-separated Steam genres (e.g. Action,RPG)
        'categories': 'TEXT',            # Comma-separated Steam categories (e.g. Single-player,Co-op)
        'is_free': 'INT'                 # 1 if free to play, 0 otherwise
    }

    for column_name, column_type in required_columns.items():
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE games ADD COLUMN {column_name} {column_type}")

    # Blacklist table — appids that should be skipped by Populate
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            appid INTEGER PRIMARY KEY,
            name TEXT,
            date_blacklisted TEXT
        )
    """)

    conn.commit()
    conn.close()

def add_new_game(appid, name):
    db_file = _db()
    if not os.path.exists(db_file):
        init_db()
    conn = sqlite3.connect(db_file, timeout=10)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO games (appid, name) VALUES (?, ?)", (str(appid), name))
    conn.commit()
    conn.close()

def update_game_data(appid, **kwargs):
    """
    Updates specific columns for a game in the database.
    Example: update_game_data('123', completion_status='played', rating=5)
    """
    if not kwargs:
        return

    conn = sqlite3.connect(_db(), timeout=10)
    cursor = conn.cursor()

    columns = ", ".join([f"{key} = ?" for key in kwargs.keys()])
    values = list(kwargs.values())
    values.append(appid)

    query = f"UPDATE games SET {columns} WHERE appid = ?"

    try:
        cursor.execute(query, values)
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database update failed: {e}")
    finally:
        conn.close()

def bulk_update_column(appids, column, value):
    """
    Updates a single column to a specific value for a list of appids.
    Example: bulk_update_column([10, 20, 30], 'installed', 1)
    """
    if not appids:
        return

    conn = sqlite3.connect(_db(), timeout=10)
    cursor = conn.cursor()

    placeholders = ", ".join(["?"] * len(appids))
    query = f"UPDATE games SET {column} = ? WHERE appid IN ({placeholders})"
    params = [value] + list(appids)

    try:
        cursor.execute(query, params)
        conn.commit()
    except sqlite3.Error as e:
        print(f"Bulk update failed: {e}")
    finally:
        conn.close()

# ── Blacklist helpers ──────────────────────────────────────────────────────────

def get_blacklist():
    """Return all blacklisted entries sorted by date_blacklisted DESC."""
    conn = sqlite3.connect(_db(), timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT appid, name, date_blacklisted FROM blacklist ORDER BY date_blacklisted DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_to_blacklist(appid, name):
    """Add an appid to the blacklist. Safe to call if already present."""
    from datetime import datetime
    conn = sqlite3.connect(_db(), timeout=10)
    conn.execute(
        "INSERT OR REPLACE INTO blacklist (appid, name, date_blacklisted) VALUES (?, ?, ?)",
        (int(appid), name, datetime.now().strftime('%Y-%m-%d'))
    )
    conn.commit()
    conn.close()

def remove_from_blacklist(appid):
    """Remove an appid from the blacklist."""
    conn = sqlite3.connect(_db(), timeout=10)
    conn.execute("DELETE FROM blacklist WHERE appid = ?", (int(appid),))
    conn.commit()
    conn.close()

def get_blacklisted_appids():
    """Return a set of blacklisted appids for fast membership testing."""
    conn = sqlite3.connect(_db(), timeout=10)
    rows = conn.execute("SELECT appid FROM blacklist").fetchall()
    conn.close()
    return {row[0] for row in rows}


def migrate_image_files():
    """
    One-time migration: moves flat library/{appid}.jpg files into
    library/vertical/ or library/horizontal/ subfolders.

    Games that had art_source='header' (now vertical_art_source='header')
    have a horizontal image stored as their vertical cover — those get moved
    to horizontal/ and their DB record is corrected.

    Skipped entirely if the vertical/ subfolder is non-empty.
    """
    import logging
    log = logging.getLogger(__name__)

    from config import BASE_DIR
    library_dir  = os.path.join(BASE_DIR, 'static', 'img', 'library')
    vertical_dir = os.path.join(library_dir, 'vertical')

    log.info(f"[migrate_image_files] library_dir = {library_dir}")

    if os.path.exists(vertical_dir) and os.listdir(vertical_dir):
        log.info("[migrate_image_files] Already migrated — skipping.")
        return

    log.info("[migrate_image_files] Starting image file migration...")

    horizontal_dir = os.path.join(library_dir, 'horizontal')
    icons_dir      = os.path.join(library_dir, 'icons')
    for d in (vertical_dir, horizontal_dir, icons_dir):
        os.makedirs(d, exist_ok=True)
        log.info(f"[migrate_image_files] Created directory: {d}")

    # Find games whose "vertical" file is actually a horizontal header image
    conn = sqlite3.connect(_db(), timeout=10)
    rows = conn.execute(
        "SELECT appid FROM games WHERE vertical_art_source = 'header'"
    ).fetchall()
    header_appids = {row[0] for row in rows}
    log.info(f"[migrate_image_files] Games with header source (→ horizontal/): {len(header_appids)}")

    # Move all flat .jpg files to the appropriate subfolder
    moved = 0
    skipped = 0
    try:
        for filename in os.listdir(library_dir):
            if not filename.endswith('.jpg'):
                continue
            src = os.path.join(library_dir, filename)
            if not os.path.isfile(src):
                continue
            try:
                appid = int(filename.replace('.jpg', ''))
            except ValueError:
                skipped += 1
                continue
            dest_dir = horizontal_dir if appid in header_appids else vertical_dir
            dest = os.path.join(dest_dir, filename)
            os.rename(src, dest)
            moved += 1
    except Exception as e:
        log.error(f"[migrate_image_files] Error moving files: {e}", exc_info=True)

    log.info(f"[migrate_image_files] Moved {moved} files, skipped {skipped}.")

    # Fix DB records for games that had a horizontal image as their vertical cover
    if header_appids:
        placeholders = ', '.join('?' * len(header_appids))
        conn.execute(
            f"UPDATE games SET vertical_art_source = 'missing', horizontal_art_source = 'header' "
            f"WHERE appid IN ({placeholders})",
            list(header_appids)
        )
        conn.commit()
        log.info(f"[migrate_image_files] Updated DB for {len(header_appids)} header-source games.")

    conn.close()
    log.info("[migrate_image_files] Migration complete.")
