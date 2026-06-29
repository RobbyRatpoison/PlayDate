import logging
import os
import re
import sqlite3
from datetime import datetime, timezone

from config import BASE_DIR

log = logging.getLogger(__name__)


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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            appid INTEGER PRIMARY KEY,
            name TEXT
        )
    """)

    cursor.execute("PRAGMA table_info(games)")
    columns = [column[1] for column in cursor.fetchall()]

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
        'platform_ns': 'TEXT',           # Platform-specific namespace (e.g. Epic catalog namespace)
        'platform_appname': 'TEXT',      # Platform-internal app/launch name distinct from store slug (e.g. Epic appName)
        'steam_appid': 'INTEGER',        # Steam AppID resolved via PCGW for non-Steam games (NULL = not yet looked up)
        'install_path': 'TEXT',          # Local install directory (non-Steam games)
        'wine_prefix': 'TEXT',           # Path to Wine/Proton prefix (Windows games)
        'runner_path': 'TEXT',           # Path to Proton binary used for this game
        'platform_executable': 'TEXT',   # Relative path to main exe within install_path
        'duplicate_of': 'TEXT',          # appid of preferred version of this game (e.g. Steam appid for a GOG duplicate); NULL = canonical
        'duplicate_auto': 'INT',         # 1 = set by auto-detection; 0/NULL = manually set
        'name_from_store': 'INT',        # 1 = name confirmed from Steam store API; 0/NULL = from GetOwnedGames or local files
    }

    for column_name, column_type in required_columns.items():
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE games ADD COLUMN {column_name} {column_type}")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_installed         ON games(installed)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_completion_status ON games(completion_status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_last_played       ON games(last_played)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_playtime_forever  ON games(playtime_forever)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_platform          ON games(platform)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_name              ON games(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_duplicate_of      ON games(duplicate_of)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_release_date      ON games(release_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_hltb_fetched      ON games(hltb_fetched)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_meta_fetched      ON games(meta_fetched)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_art_fetched       ON games(art_fetched)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_cheevos_fetched   ON games(cheevos_fetched)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            appid INTEGER PRIMARY KEY,
            name TEXT,
            date_blacklisted TEXT,
            platform_id TEXT
        )
    """)

    try:
        cursor.execute("ALTER TABLE blacklist ADD COLUMN platform_id TEXT")
    except Exception:
        pass  # column already exists

    conn.commit()
    conn.close()

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
        'completion_status', 'installed', 'icon_hash', 'platform',
        'art_fetched', 'meta_fetched', 'cheevos_fetched', 'protondb_fetched', 'hltb_fetched',
    ]
    placeholders = ', '.join('?' * len(cols))
    col_str = ', '.join(cols)
    rows = [
        (
            str(g['appid']), g['name'], g['playtime_forever'], g['last_played'],
            today, g['completion_status'], g['installed'], g.get('icon_hash', ''),
            'steam', '0', '0', '0', '0', '0',
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
        log.error(f"Database update failed: {e}")
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
        log.error(f"Bulk update failed: {e}")
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


import logging as _logging
_log = _logging.getLogger(__name__)

PLATFORM_PRIORITY_DEFAULT = ['steam', 'gog', 'epic_games', 'ea_app', 'ubisoft', 'itch_io']


def next_negative_appid(db):
    """Return the next available negative appid for a non-Steam game."""
    row = db.execute('SELECT MIN(appid) FROM games WHERE appid < 0').fetchone()
    return (row[0] - 1) if (row[0] is not None) else -1


def _normalize_name_for_dup(name):
    name = name.lower()
    name = re.sub(
        r'\s*[-–:]\s*(goty|game of the year|complete edition|deluxe edition|gold edition|'
        r'definitive edition|remastered|remaster|enhanced edition|anniversary edition|'
        r'director\'?s cut|ultimate edition|premium edition)\s*$',
        '', name, flags=re.IGNORECASE
    )
    name = re.sub(r"[^\w\s']", ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def auto_detect_duplicates(platform_priority=None):
    """Match games across platforms by normalized name and set duplicate_of.
    Lower-priority platform versions are marked as duplicates of higher-priority ones.
    Clears previously auto-detected duplicates before re-running.
    Returns count of newly marked duplicates.
    """
    if platform_priority is None:
        platform_priority = PLATFORM_PRIORITY_DEFAULT

    conn = get_db()
    try:
        conn.execute("UPDATE games SET duplicate_of = NULL, duplicate_auto = 0 WHERE duplicate_auto = 1")

        games_by_platform = {}
        for row in conn.execute(
            "SELECT appid, name, platform FROM games WHERE name IS NOT NULL"
        ).fetchall():
            plat = row['platform']
            if plat not in games_by_platform:
                games_by_platform[plat] = {}
            norm = _normalize_name_for_dup(row['name'])
            games_by_platform[plat][norm] = str(row['appid'])

        updated = 0
        for i, high_plat in enumerate(platform_priority):
            if high_plat not in games_by_platform:
                continue
            high_games = games_by_platform[high_plat]
            for low_plat in platform_priority[i + 1:]:
                if low_plat not in games_by_platform:
                    continue
                for norm, low_appid in games_by_platform[low_plat].items():
                    if norm in high_games:
                        conn.execute(
                            "UPDATE games SET duplicate_of = ?, duplicate_auto = 1 WHERE appid = ?",
                            (high_games[norm], low_appid)
                        )
                        _log.info(f'Auto-duplicate ({low_plat}→{high_plat}): appid {low_appid} → {high_games[norm]}')
                        updated += 1

        if updated:
            conn.commit()
        return updated
    finally:
        conn.close()
