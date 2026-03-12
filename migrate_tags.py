import time
import threading
from database import get_db, update_game_data
from scrapers import fetch_tag_data

# Shared cancellation event
_cancel_event = threading.Event()

def cancel_migration():
    _cancel_event.set()

def migrate_missing_tags():
    _cancel_event.clear()
    db = get_db()
    games = db.execute("SELECT appid, name FROM games WHERE tags IS NULL OR tags = ''").fetchall()
    db.close()
    total = len(games)
    updated = 0

    print(f"Found {total} games missing tags. Starting migration...")

    for game in games:
        if _cancel_event.is_set():
            print(f"Tag migration cancelled after {updated} games.")
            return {"status": "cancelled", "updated": updated, "total": total}

        appid = game['appid']
        name = game['name']
        print(f"Fetching tags for: {name} ({appid})...")
        tag_info = fetch_tag_data(appid)

        if tag_info:
            update_game_data(appid, **tag_info)
            print(f"  > Success: {tag_info['tags'][:40]}")
        else:
            print(f"  > No tags found for {name}.")

        updated += 1
        if updated % 10 == 0:
            print(f"Updated {updated} of {total}...")
        time.sleep(1.2)

    print("Tag migration complete!")
    return {"status": "complete", "updated": updated, "total": total}

if __name__ == "__main__":
    migrate_missing_tags()
