import glob
import json
import logging
import os
import re
import sqlite3

from config import BASE_DIR, CONFIG_PATH

log = logging.getLogger(__name__)

CURRENT_VERSION    = 9
BACKGROUND_VERSION = 10

_migrations:            dict[int, callable] = {}
_background_migrations: dict[int, callable] = {}


def migration(version: int):
    def decorator(fn):
        _migrations[version] = fn
        return fn
    return decorator


def background_migration(version: int):
    def decorator(fn):
        _background_migrations[version] = fn
        return fn
    return decorator


def needs_background(version: int) -> bool:
    """Return True if the given background migration has not yet completed."""
    if not os.path.exists(CONFIG_PATH):
        return False
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        return False
    return (cfg.get('background_migration_version') or 0) < version


def mark_background_done(version: int):
    """Advance background_migration_version to version in config.json."""
    if not os.path.exists(CONFIG_PATH):
        return
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    if (cfg.get('background_migration_version') or 0) < version:
        cfg['background_migration_version'] = version
        with open(CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=4)
        log.info(f"Background migration v{version} marked complete")


def _all_db_files():
    """Return paths of all games_*.db files in BASE_DIR."""
    return glob.glob(os.path.join(BASE_DIR, 'games_*.db'))


def run():
    """Run all pending migrations. Called once at startup before init_db()."""
    if not os.path.exists(CONFIG_PATH):
        return  # fresh install — no migrations needed

    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}

    prev = cfg.get('migration_version') or 0
    if prev >= CURRENT_VERSION:
        return

    for v in sorted(k for k in _migrations if k > prev):
        log.info(f"Running migration v{v}: {_migrations[v].__name__}")
        try:
            _migrations[v]()
        except Exception as e:
            log.error(f"Migration v{v} failed: {e}", exc_info=True)
            raise  # abort — do not advance version past a failed migration

    cfg['migration_version'] = CURRENT_VERSION
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=4)
    log.info(f"Migrations complete — version {prev} → {CURRENT_VERSION}")


# ── Migrations ────────────────────────────────────────────────────────────────

@migration(1)
def _m1_multi_account():
    """Flat {steam_id, api_key} config → multi-account structure."""
    if not os.path.exists(CONFIG_PATH):
        return

    with open(CONFIG_PATH) as f:
        data = json.load(f)

    if 'accounts' in data:
        return  # already migrated

    steam_id = data.get('steam_id', '').strip()
    api_key  = data.get('api_key',  '').strip()
    sgdb_key = data.get('sgdb_key', '').strip()

    if not steam_id:
        new_config = {'active_account': None, 'sgdb_key': sgdb_key, 'accounts': {}}
        with open(CONFIG_PATH, 'w') as f:
            json.dump(new_config, f, indent=4)
        return

    old_db = os.path.join(BASE_DIR, 'games.db')
    new_db = os.path.join(BASE_DIR, f'games_{steam_id}.db')
    if os.path.exists(old_db) and not os.path.exists(new_db):
        os.rename(old_db, new_db)

    new_config = {
        'active_account': steam_id,
        'sgdb_key': sgdb_key,
        'accounts': {
            steam_id: {
                'steam_id': steam_id,
                'api_key':  api_key,
                'label':    steam_id,
            }
        }
    }
    with open(CONFIG_PATH, 'w') as f:
        json.dump(new_config, f, indent=4)


@migration(2)
def _m2_art_source_rename():
    """Rename games.art_source column → vertical_art_source."""
    for db_path in _all_db_files():
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(games)")
            cols = [row[1] for row in cursor.fetchall()]
            if 'art_source' in cols and 'vertical_art_source' not in cols:
                cursor.execute("ALTER TABLE games RENAME COLUMN art_source TO vertical_art_source")
                conn.commit()
        finally:
            conn.close()


@migration(3)
def _m3_dates_to_timestamps():
    """Convert YYYY-MM-DD date strings → Unix integer timestamps."""
    from database import date_to_ts

    def _migrate_col(cursor, col):
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

    for db_path in _all_db_files():
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(games)")
            cols = [row[1] for row in cursor.fetchall()]
            for dc in ('last_played', 'date_added', 'release_date'):
                if dc in cols:
                    _migrate_col(cursor, dc)
            conn.commit()
        finally:
            conn.close()


@migration(4)
def _m4_date_column_affinity():
    """Re-create date columns with INTEGER affinity (was TEXT)."""
    def _drop_indexes_referencing(cursor, col_name):
        pat = re.compile(r'\b' + re.escape(col_name) + r'\b')
        rows = cursor.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='games'"
        ).fetchall()
        for idx_name, idx_sql in rows:
            if idx_sql and pat.search(idx_sql):
                cursor.execute(f"DROP INDEX IF EXISTS {idx_name}")

    for db_path in _all_db_files():
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(games)")
            col_info = {row[1]: row[2].upper() for row in cursor.fetchall()}
            for dc in ('last_played', 'date_added', 'release_date'):
                tmp = f"{dc}_txt_bak"
                if col_info.get(dc, 'INTEGER') not in ('INTEGER', 'INT'):
                    _drop_indexes_referencing(cursor, dc)
                    cursor.execute(f"ALTER TABLE games RENAME COLUMN {dc} TO {tmp}")
                    cursor.execute(f"ALTER TABLE games ADD COLUMN {dc} INTEGER")
                    cursor.execute(f"UPDATE games SET {dc} = CAST({tmp} AS INTEGER) WHERE {tmp} IS NOT NULL")
                    cursor.execute(f"ALTER TABLE games DROP COLUMN {tmp}")
                    cursor.execute("PRAGMA table_info(games)")
                    col_info = {row[1]: row[2].upper() for row in cursor.fetchall()}
                elif tmp in col_info:
                    # Clean up a leftover backup column from a previously interrupted run
                    cursor.execute(f"ALTER TABLE games DROP COLUMN {tmp}")
                    cursor.execute("PRAGMA table_info(games)")
                    col_info = {row[1]: row[2].upper() for row in cursor.fetchall()}
            conn.commit()
        finally:
            conn.close()


@migration(5)
def _m5_backfill_fetched_columns():
    """Infer meta_fetched / art_fetched / cheevos_fetched from existing data."""
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')

    for db_path in _all_db_files():
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            cursor = conn.cursor()
            # Ensure columns exist before backfilling — init_db() runs after migrations
            for col in ('meta_fetched', 'art_fetched', 'cheevos_fetched',
                        'protondb_fetched', 'protondb_tier', 'protondb_confidence',
                        'hltb_fetched', 'hltb_id', 'hltb_matched_name', 'hltb_match_score',
                        'hltb_main', 'hltb_extras', 'hltb_completionist'):
                try:
                    cursor.execute(f"ALTER TABLE games ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass  # column already exists
            cursor.execute("""
                UPDATE games SET meta_fetched = ?
                WHERE meta_fetched IS NULL
                AND (
                    (tags IS NOT NULL AND tags != '')
                    OR (review_score IS NOT NULL AND review_score != '')
                )
            """, (today,))
            cursor.execute("""
                UPDATE games SET art_fetched = ?
                WHERE art_fetched IS NULL
                AND (
                    (vertical_art_source IS NOT NULL AND vertical_art_source NOT IN ('', 'missing'))
                    OR (horizontal_art_source IS NOT NULL AND horizontal_art_source NOT IN ('', 'missing'))
                )
            """, (today,))
            cursor.execute("""
                UPDATE games SET cheevos_fetched = ?
                WHERE cheevos_fetched IS NULL
                AND total_achievements IS NOT NULL
            """, (today,))
            cursor.execute("UPDATE games SET meta_fetched    = '0' WHERE meta_fetched    IS NULL")
            cursor.execute("UPDATE games SET art_fetched     = '0' WHERE art_fetched     IS NULL")
            cursor.execute("UPDATE games SET cheevos_fetched = '0' WHERE cheevos_fetched IS NULL")
            cursor.execute("UPDATE games SET protondb_fetched = '0' WHERE protondb_fetched IS NULL")
            cursor.execute("UPDATE games SET hltb_fetched = '0' WHERE hltb_fetched IS NULL")
            cursor.execute(
                "UPDATE games SET hltb_fetched = 'no_match'"
                " WHERE hltb_fetched NOT IN ('0', 'unconfirmed', 'no_match') AND hltb_id IS NULL"
            )
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
            conn.commit()
        finally:
            conn.close()


@migration(6)
def _m6_backfill_platform():
    """Set platform = 'steam' for all pre-plugin rows."""
    for db_path in _all_db_files():
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(games)").fetchall()]
            if 'platform' not in cols:
                conn.execute("ALTER TABLE games ADD COLUMN platform TEXT")
            conn.execute("UPDATE games SET platform = 'steam' WHERE platform IS NULL")
            conn.commit()
        finally:
            conn.close()


@migration(7)
def _m7_backfill_art_sources():
    """Backfill vertical/horizontal/icon_source for games missing all three."""
    for db_path in _all_db_files():
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            conn.execute("""
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
            conn.commit()
        finally:
            conn.close()


@migration(8)
def _m8_image_subdirectories():
    """Move flat library/{appid}.jpg files into vertical/, horizontal/, icons/."""
    library_dir  = os.path.join(BASE_DIR, 'static', 'img', 'library')
    vertical_dir = os.path.join(library_dir, 'vertical')

    if os.path.exists(vertical_dir) and os.listdir(vertical_dir):
        log.info("_m8_image_subdirectories: already migrated — skipping")
        return

    horizontal_dir = os.path.join(library_dir, 'horizontal')
    icons_dir      = os.path.join(library_dir, 'icons')
    for d in (vertical_dir, horizontal_dir, icons_dir):
        os.makedirs(d, exist_ok=True)

    header_appids = set()
    for db_path in _all_db_files():
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            rows = conn.execute(
                "SELECT appid FROM games WHERE vertical_art_source = 'header'"
            ).fetchall()
            header_appids.update(row[0] for row in rows)
        finally:
            conn.close()

    moved = skipped = 0
    if os.path.exists(library_dir):
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
            os.rename(src, os.path.join(dest_dir, filename))
            moved += 1
    log.info(f"_m8_image_subdirectories: moved {moved} files, skipped {skipped}")

    if header_appids:
        placeholders = ', '.join('?' * len(header_appids))
        for db_path in _all_db_files():
            conn = sqlite3.connect(db_path, timeout=10)
            try:
                conn.execute(
                    f"UPDATE games SET vertical_art_source = 'missing', horizontal_art_source = 'header' "
                    f"WHERE appid IN ({placeholders})",
                    list(header_appids)
                )
                conn.commit()
            finally:
                conn.close()


@migration(9)
def _m9_auto_detect_duplicates():
    """Run duplicate auto-detection on first launch after plugin system landed."""
    found_legacy = False
    for db_path in _all_db_files():
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            legacy = conn.execute(
                "SELECT COUNT(*) FROM games "
                "WHERE platform = 'gog' AND duplicate_auto IS NULL "
                "AND duplicate_of IS NOT NULL AND duplicate_of != '' "
                "AND CAST(duplicate_of AS INTEGER) > 0"
            ).fetchone()[0]
            if legacy:
                conn.execute(
                    "UPDATE games SET duplicate_auto = 1 "
                    "WHERE platform = 'gog' AND duplicate_auto IS NULL "
                    "AND duplicate_of IS NOT NULL AND duplicate_of != '' "
                    "AND CAST(duplicate_of AS INTEGER) > 0"
                )
                conn.commit()
                found_legacy = True
        finally:
            conn.close()

    if found_legacy:
        try:
            from database import auto_detect_duplicates
            from config import load_state
            priority = load_state().get('platform_priority')
            auto_detect_duplicates(platform_priority=priority)
        except Exception as e:
            log.warning(f"_m9_auto_detect_duplicates: auto-detection failed: {e}")


# ── Background migrations ─────────────────────────────────────────────────────

@background_migration(10)
def _bm10_store_release_dates():
    """Re-scrape Steam store release dates to get original release dates.

    Replaces Steam API launch dates with store-page dates (which reflect the
    game's original release, e.g. a prior itch.io release). Long-running;
    runs in the startup background thread. Progress is tracked in
    release_date_migration.json so the job can resume across restarts.
    Implemented in scrapers.sync_store_release_dates.
    """
