from config import BASE_DIR
import sqlite3
import os
import re
from datetime import datetime, timezone


def date_to_ts(date_str):
    """'YYYY-MM-DD' string → Unix timestamp int, or None."""
    if not date_str:
        return None
    try:
        return int(datetime.strptime(str(date_str)[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError):
        return None


def ts_to_date(ts):
    """Unix timestamp int → 'YYYY-MM-DD' string, or None.
    If already a 'YYYY-MM-DD' string, returns it as-is (handles GOG date strings)."""
    if not ts:
        return None
    if isinstance(ts, str) and len(ts) >= 10 and ts[4:5] == '-':
        return ts[:10]
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%Y-%m-%d')
    except (ValueError, OSError, TypeError):
        return None


def _db():
    """Returns the active account's database file path."""
    from config import get_active_db_path
    return get_active_db_path()


def _open_conn(db_file, timeout=30):
    conn = sqlite3.connect(db_file, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_db():
    db_file = _db()
    conn = _open_conn(db_file)
    # Auto-init if the games table is missing (e.g. DB was deleted while running)
    try:
        conn.execute("SELECT 1 FROM games LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        init_db()
        conn = _open_conn(db_file)
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
        'last_played': 'INTEGER',        # Last played — Unix timestamp
        'date_added': 'INTEGER',         # Date added — Unix timestamp
        'developers': 'TEXT',            # Developer metadata
        'publishers': 'TEXT',            # Publisher metadata
        'completion_status': 'TEXT',     # e.g., "Not Played", "Completed"
        'tags': 'TEXT',                  # Genres/Tags
        'release_date': 'INTEGER',       # Game release date — Unix timestamp
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
        'is_free': 'INT',                # 1 if free to play, 0 otherwise
        'art_fetched': 'TEXT',           # '0' = never fetched, YYYY-MM-DD = date last fetched
        'meta_fetched': 'TEXT',          # '0' = never fetched, YYYY-MM-DD = date last fetched
        'cheevos_fetched': 'TEXT',       # '0' = never fetched, YYYY-MM-DD = date last fetched
        'protondb_tier': 'TEXT',         # platinum/gold/silver/bronze/borked or NULL
        'protondb_confidence': 'TEXT',   # strong/good/weak or NULL
        'protondb_fetched': 'TEXT',      # '0' = never fetched, YYYY-MM-DD = date last fetched
        'hltb_main': 'INT',              # Main story time in minutes
        'hltb_extras': 'INT',            # Main + extras time in minutes
        'hltb_completionist': 'INT',     # Completionist time in minutes
        'hltb_id': 'INT',               # HLTB game ID (for direct URL)
        'hltb_matched_name': 'TEXT',     # HLTB game name as returned by search
        'hltb_match_score': 'INT',       # 0-100 name similarity score
        'hltb_fetched': 'TEXT',          # '0' = pending, YYYY-MM-DD = confirmed, 'unconfirmed' = below threshold
        'platform': 'TEXT',              # 'steam' (default), 'gog', 'egs', 'ea_app', 'ubisoft'
        'platform_id': 'TEXT',           # Service-native ID used for launching (GOG ID, EGS appName, etc.)
        'platform_slug': 'TEXT',         # Platform store slug for building store URLs (e.g. GOG slug 'the_witcher_3_wild_hunt')
        'steam_appid': 'INTEGER',        # Steam AppID resolved via PCGW for non-Steam games (NULL = not yet looked up)
        'install_path': 'TEXT',          # Local install directory (non-Steam games)
        'wine_prefix': 'TEXT',           # Path to Wine/Proton prefix (Windows games)
        'runner_path': 'TEXT',           # Path to Proton binary used for this game
        'platform_executable': 'TEXT',   # Relative path to main exe within install_path
        'duplicate_of': 'TEXT',          # appid of preferred version of this game (e.g. Steam appid for a GOG duplicate); NULL = canonical
        'duplicate_auto': 'INT',         # 1 = set by auto-detection; 0/NULL = manually set
    }

    for column_name, column_type in required_columns.items():
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE games ADD COLUMN {column_name} {column_type}")

    # ── Migrate YYYY-MM-DD date strings to Unix timestamps ────────────────────
    def _migrate_date_col(col):
        rows = cursor.execute(
            f"SELECT rowid, {col} FROM games WHERE {col} IS NOT NULL"
        ).fetchall()
        updates, nulls = [], []
        for rowid, val in rows:
            if isinstance(val, str):
                ts = date_to_ts(val)
                if ts is not None:
                    updates.append((ts, rowid))
                else:
                    nulls.append((rowid,))
        if updates:
            cursor.executemany(f"UPDATE games SET {col} = ? WHERE rowid = ?", updates)
        if nulls:
            cursor.executemany(f"UPDATE games SET {col} = NULL WHERE rowid = ?", nulls)

    _migrate_date_col('last_played')
    _migrate_date_col('date_added')
    _migrate_date_col('release_date')

    # ── Promote date columns from TEXT to INTEGER affinity ────────────────────
    # These columns were originally TEXT; the migration above stored integer
    # timestamps into them but SQLite's TEXT affinity coerced them back to
    # strings, breaking numeric sort order. Rename→re-add→copy→drop converts
    # the stored values to true integers. Requires SQLite 3.35+ for DROP COLUMN.
    #
    # Indexes on a column must be dropped before that column can be dropped;
    # we drop them here and let the CREATE INDEX block at the bottom recreate
    # them. Also handles a previously-interrupted migration where a _txt_bak
    # column was left behind.
    def _drop_indexes_referencing(col_name):
        """Drop any index on the games table whose SQL mentions col_name."""
        pat = re.compile(r'\b' + re.escape(col_name) + r'\b')
        rows = cursor.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='games'"
        ).fetchall()
        for idx_name, idx_sql in rows:
            if idx_sql and pat.search(idx_sql):
                cursor.execute(f"DROP INDEX IF EXISTS {idx_name}")

    cursor.execute("PRAGMA table_info(games)")
    col_info = {row[1]: row[2].upper() for row in cursor.fetchall()}
    for _dc in ('last_played', 'date_added', 'release_date'):
        _tmp = f"{_dc}_txt_bak"
        # Promote to INTEGER affinity if still TEXT.
        if col_info.get(_dc, 'INTEGER') not in ('INTEGER', 'INT'):
            _drop_indexes_referencing(_dc)
            cursor.execute(f"ALTER TABLE games RENAME COLUMN {_dc} TO {_tmp}")
            cursor.execute(f"ALTER TABLE games ADD COLUMN {_dc} INTEGER")
            cursor.execute(f"UPDATE games SET {_dc} = CAST({_tmp} AS INTEGER) WHERE {_tmp} IS NOT NULL")
            cursor.execute(f"ALTER TABLE games DROP COLUMN {_tmp}")
            cursor.execute("PRAGMA table_info(games)")
            col_info = {row[1]: row[2].upper() for row in cursor.fetchall()}

    # ── Migrate existing games into the _fetched tracking system ─────────────
    # Infers fetched status from existing data; remaining NULLs become '0' so
    # populate treats them as pending. All statements are no-ops on current DBs.
    today = datetime.now().strftime('%Y-%m-%d')
    # meta: game has tags or review data → already scraped
    cursor.execute("""
        UPDATE games SET meta_fetched = ?
        WHERE meta_fetched IS NULL
        AND (
            (tags IS NOT NULL AND tags != '')
            OR (review_score IS NOT NULL AND review_score != '')
        )
    """, (today,))
    # art: game has a non-missing art source → already downloaded
    cursor.execute("""
        UPDATE games SET art_fetched = ?
        WHERE art_fetched IS NULL
        AND (
            (vertical_art_source IS NOT NULL AND vertical_art_source NOT IN ('', 'missing'))
            OR (horizontal_art_source IS NOT NULL AND horizontal_art_source NOT IN ('', 'missing'))
        )
    """, (today,))
    # cheevos: total_achievements is not NULL → fetch was attempted (0 = no achievements is valid)
    cursor.execute("""
        UPDATE games SET cheevos_fetched = ?
        WHERE cheevos_fetched IS NULL
        AND total_achievements IS NOT NULL
    """, (today,))
    # remaining NULLs → mark as pending so populate will fetch them
    cursor.execute("UPDATE games SET meta_fetched    = '0' WHERE meta_fetched    IS NULL")
    cursor.execute("UPDATE games SET art_fetched     = '0' WHERE art_fetched     IS NULL")
    cursor.execute("UPDATE games SET cheevos_fetched = '0' WHERE cheevos_fetched IS NULL")

    # protondb_fetched: NULL means column was just added — mark all as pending ('0').
    # Also reset any games that were marked fetched but have no tier data (caused by
    # the failed bulk-download path that stored NULL tier for all games).
    cursor.execute("UPDATE games SET protondb_fetched = '0' WHERE protondb_fetched IS NULL")
    cursor.execute("UPDATE games SET hltb_fetched = '0' WHERE hltb_fetched IS NULL")
    # Games fetched before the 'no_match' sentinel existed: date stored but no hltb_id.
    cursor.execute(
        "UPDATE games SET hltb_fetched = 'no_match'"
        " WHERE hltb_fetched NOT IN ('0', 'unconfirmed', 'no_match') AND hltb_id IS NULL"
    )
    # Games stored as confirmed but with all-NULL times: the confirm endpoint previously
    # marked these as confirmed even when the ID lookup failed (times_available=False).
    # Reset to no_match so they surface in the HLTB review tab and can be re-scraped.
    cursor.execute("""
        UPDATE games
        SET hltb_fetched = 'no_match', hltb_id = NULL,
            hltb_matched_name = NULL, hltb_match_score = NULL
        WHERE hltb_fetched NOT IN ('0', 'no_match', 'unconfirmed')
        AND   hltb_fetched IS NOT NULL
        AND   hltb_main IS NULL AND hltb_extras IS NULL AND hltb_completionist IS NULL
    """)
    cursor.execute(
        "UPDATE games SET protondb_fetched = '0'"
        " WHERE protondb_fetched != '0' AND protondb_tier IS NULL"
    )

    # Backfill platform = 'steam' for all pre-existing rows
    cursor.execute("UPDATE games SET platform = 'steam' WHERE platform IS NULL")

    # ── Backfill art source columns for games stuck with art_fetched set but ──
    # all three source columns NULL.  This happens when the art worker took the
    # "files already exist on disk" shortcut without recording sources (fixed in
    # the populate speed overhaul).  Uses conservative defaults; 'capsule' and
    # 'header' are the most common Steam sources, and icon_source is guessed
    # from whether an icon_hash is recorded.
    cursor.execute("""
        UPDATE games
        SET vertical_art_source   = 'capsule',
            horizontal_art_source = 'header',
            icon_source           = CASE
                                        WHEN icon_hash IS NOT NULL AND icon_hash != '' THEN 'steam'
                                        ELSE 'sgdb_icon'
                                    END
        WHERE art_fetched IS NOT NULL
        AND   art_fetched != '0'
        AND   vertical_art_source   IS NULL
        AND   horizontal_art_source IS NULL
        AND   icon_source           IS NULL
    """)

    # Indexes on frequently filtered/sorted columns
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_installed         ON games(installed)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_completion_status ON games(completion_status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_last_played       ON games(last_played)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_playtime_forever  ON games(playtime_forever)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_platform          ON games(platform)")

    # Blacklist table — appids that should be skipped by Populate / sync
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            appid INTEGER PRIMARY KEY,
            name TEXT,
            date_blacklisted TEXT,
            platform_id TEXT
        )
    """)
    # Migrate: add platform_id if an older DB doesn't have it
    try:
        cursor.execute("ALTER TABLE blacklist ADD COLUMN platform_id TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists

    # ── Migrate pre-duplicate_auto GOG→Steam entries ─────────────────────────
    # Before duplicate_auto existed, auto_detect_duplicates() only marked GOG
    # games as duplicates of Steam games and left duplicate_auto NULL.
    # Mark these as auto-detected so priority-aware re-detection can replace them.
    legacy = cursor.execute(
        "SELECT COUNT(*) FROM games "
        "WHERE platform = 'gog' AND duplicate_auto IS NULL "
        "AND duplicate_of IS NOT NULL AND duplicate_of != '' "
        "AND CAST(duplicate_of AS INTEGER) > 0"
    ).fetchone()[0]
    if legacy:
        cursor.execute(
            "UPDATE games SET duplicate_auto = 1 "
            "WHERE platform = 'gog' AND duplicate_auto IS NULL "
            "AND duplicate_of IS NOT NULL AND duplicate_of != '' "
            "AND CAST(duplicate_of AS INTEGER) > 0"
        )

    conn.commit()
    conn.close()
    return bool(legacy)

def add_new_game(appid, name):
    conn = get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO games (appid, name) VALUES (?, ?)", (int(appid), name))
        conn.commit()
    finally:
        conn.close()

def batch_insert_placeholder_games(games, today):
    """
    Batch-inserts placeholder rows for a list of new games in a single transaction.
    Each game dict must have: appid, name, playtime_forever, last_played, completion_status,
    installed, icon_hash. Phase columns are initialised to '0'.
    Games already in the DB are skipped (INSERT OR IGNORE).
    """
    if not games:
        return
    cols = [
        'appid', 'name', 'playtime_forever', 'last_played', 'date_added',
        'completion_status', 'installed', 'icon_hash',
        'art_fetched', 'meta_fetched', 'cheevos_fetched', 'protondb_fetched', 'hltb_fetched',
    ]
    placeholders = ', '.join('?' * len(cols))
    col_str = ', '.join(cols)
    rows = [
        (
            str(g['appid']), g['name'], g['playtime_forever'], g['last_played'],
            today, g['completion_status'], g['installed'], g.get('icon_hash', ''),
            '0', '0', '0', '0', '0',
        )
        for g in games
    ]
    conn = get_db()
    try:
        conn.executemany(f"INSERT OR IGNORE INTO games ({col_str}) VALUES ({placeholders})", rows)
        conn.commit()
    finally:
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

def add_to_blacklist(appid, name, platform_id=None):
    """Add an appid to the blacklist. Safe to call if already present.
    Pass platform_id for non-Steam games so re-sync skips them."""
    conn = sqlite3.connect(_db(), timeout=10)
    conn.execute(
        "INSERT OR REPLACE INTO blacklist (appid, name, date_blacklisted, platform_id) VALUES (?, ?, ?, ?)",
        (int(appid), name, datetime.now().strftime('%Y-%m-%d'), platform_id)
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
    try:
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
    finally:
        conn.close()
    log.info("[migrate_image_files] Migration complete.")
