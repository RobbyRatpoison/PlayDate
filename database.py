from config import BASE_DIR
import sqlite3
import os

DB_FILE = os.path.join(BASE_DIR, "games.db")

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    # Auto-init if the games table is missing (e.g. DB was deleted while running)
    try:
        conn.execute("SELECT 1 FROM games LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        init_db()
        conn = sqlite3.connect(DB_FILE, timeout=10)
        conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database and ensures all columns exist."""
    conn = sqlite3.connect(DB_FILE, timeout=10)
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
        'art_source': 'TEXT',            # Where the artwork came from
        'weighted_percentage': 'INT',    # Scaling penalties for total_reviews under 100
        'total_reviews': 'INT',
        'positive_reviews': 'INT',
        'groups': 'TEXT'
    }

    for column_name, column_type in required_columns.items():
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE games ADD COLUMN {column_name} {column_type}")

    conn.commit()
    conn.close()
    """Inserts a basic game record if it doesn't exist."""

def add_new_game(appid, name):
    if not os.path.exists(DB_FILE):
        init_db()
    conn = sqlite3.connect(DB_FILE, timeout=10)
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

    conn = sqlite3.connect(DB_FILE, timeout=10)
    cursor = conn.cursor()

    # Create the 'SET column1 = ?, column2 = ?' part of the query
    columns = ", ".join([f"{key} = ?" for key in kwargs.keys()])
    values = list(kwargs.values())
    values.append(appid) # Append appid for the WHERE clause

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

    conn = sqlite3.connect(DB_FILE, timeout=10)
    cursor = conn.cursor()

    # 1. Create the (?, ?, ?) placeholders for the IN clause
    placeholders = ", ".join(["?"] * len(appids))

    # 2. Build the query.
    # Note: Column names must be injected directly as they can't be parameterized.
    query = f"UPDATE games SET {column} = ? WHERE appid IN ({placeholders})"

    # 3. Combine the 'value' and the 'appids' into a single list of parameters
    params = [value] + list(appids)

    try:
        cursor.execute(query, params)
        conn.commit()
        #print(f"Bulk updated {len(appids)} games: {column} set to {value}")
    except sqlite3.Error as e:
        print(f"Bulk update failed: {e}")
    finally:
        conn.close()
