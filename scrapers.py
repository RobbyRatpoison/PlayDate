import json
import os
import re
import requests
import time
from bs4 import BeautifulSoup
from images import download_capsule
from datetime import datetime
from config import load_config
from database import add_new_game, update_game_data, get_db
from utils import get_locally_installed_appids, sync_local_install_status



def add_new(cancel_event=None, progress_cb=None):
    limit = 0  # 0 = unlimited
    config = load_config()
    if not config:
        return {"status": "error", "message": "No config found"}

    api_key = config.get('api_key')
    steam_id = config.get('steam_id')
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    print("Fetching games via Steam API.")
    url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={api_key}&steamid={steam_id}&format=json&include_appinfo=true&include_played_free_games=1&skip_unvetted_apps=false"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 403:
            return {"status": "error", "message": "Steam API: 403 Forbidden. Your API Key may be invalid."}
        response.raise_for_status()
        data = response.json()
        raw_games = data.get('response', {}).get('games', [])
        if not raw_games:
            return {"status": "error", "message": "No games returned. Is your Steam Profile set to Public?"}
        games = [{'appid': g['appid'], 'name': g.get('name', ''), 'playtime_forever': g.get('playtime_forever', 0), 'last_played': datetime.fromtimestamp(g.get('rtime_last_played', 0)).strftime('%Y-%m-%d') if g.get('rtime_last_played', 0) > 0 else '0'} for g in raw_games]
    except requests.exceptions.JSONDecodeError:
        return {"status": "error", "message": "Steam sent invalid data. Try again in a few minutes."}
    except Exception as e:
        return {"status": "error", "message": f"Connection Error: {str(e)}"}

    # Process new games
    db = get_db()
    installed_ids   = get_locally_installed_appids()
    existing_ids    = {row['appid'] for row in db.execute("SELECT appid FROM games").fetchall()}
    blacklisted_ids = {row['appid'] for row in db.execute("SELECT appid FROM blacklist").fetchall()}
    db.close()

    new_games = [g for g in reversed(games) if g['appid'] not in existing_ids and g['appid'] not in blacklisted_ids]
    total_new = len(new_games)

    new_count = 0
    skip_count = 0
    for game in new_games:
        if cancel_event and cancel_event.is_set():
            print(f"Populate cancelled after {new_count} games.")
            return {"status": "cancelled", "added": new_count}

        appid = game['appid']
        if True:
            try:
                if progress_cb:
                    progress_cb(new_count, total_new, game['name'])
                playtime = game['playtime_forever']
                last_played = game['last_played']
                played = "Unfinished" if playtime > 0 else "Never Played"
                today = datetime.now().strftime('%Y-%m-%d')
                artwork_source = download_capsule(appid)

                game_data = {
                    'playtime_forever': playtime,
                    'date_added': today,
                    'completion_status': played,
                    'last_played': last_played,
                    'art_source': artwork_source,
                    'installed': 1 if appid in installed_ids else 0
                }

                store_info = fetch_store_data(appid)
                if store_info:
                    game_data.update(store_info)

                review_info = fetch_review_data(appid)
                if review_info:
                    game_data.update(review_info)

                tag_info = fetch_tag_data(appid)
                if tag_info:
                    game_data.update(tag_info)

                cheevo_info = fetch_cheevo_data(appid)
                if cheevo_info:
                    game_data.update(cheevo_info)

                add_new_game(appid, game['name'])
                update_game_data(appid, **game_data)

                new_count += 1
                if progress_cb:
                    progress_cb(new_count, total_new, game['name'])
                print(f"Scraped data for game #{new_count}: {game['name']}")

            except Exception as e:
                skip_count += 1
                print(f"Error processing {game.get('name', appid)} (AppID {appid}): {e} — skipping.")

            time.sleep(1.2)

            if limit > 0 and new_count >= limit:
                return {"status": "success", "added": new_count}

    if skip_count:
        print(f"Populate complete. Added {new_count}, skipped {skip_count} due to errors.")
    return {"status": "success", "added": new_count}

# Scrape Player API (Name, Playtime, Last Played)
def fetch_player_data(appid):
    config = load_config()
    if not config:
        return None

    api_key = config.get('api_key')
    steam_id = config.get('steam_id')

    if not api_key or not steam_id:
        return None

    # Use the single-game endpoint instead of fetching the entire library
    url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={api_key}&steamid={steam_id}&format=json&include_appinfo=true&include_played_free_games=1&skip_unvetted_apps=false&appids_filter[0]={appid}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        games = response.json().get('response', {}).get('games', [])

        if not games:
            return None

        game = games[0]
        last_played_unix = game.get('rtime_last_played', 0)
        last_played_date = datetime.fromtimestamp(last_played_unix).strftime('%Y-%m-%d') if last_played_unix > 0 else '0'
        return {
            'name': game.get('name'),
            'playtime_forever': game.get('playtime_forever', 0),
            'last_played': last_played_date
        }
    except Exception as e:
        print(f"Error fetching player data for {appid}: {e}")
        return None

# Scrape Storefront API (Devs, Pubs, Release Date)
def fetch_store_data(appid):
    """
    Fetches rich metadata from the Steam Store API for a single appid.
    Returns a dictionary of data or None if the request fails.
    """
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        json_data = response.json()

        # The API returns data keyed by the appid string
        if not json_data or not json_data.get(str(appid), {}).get('success'):
            print(f"Could not find store data for {appid}")
            return None

        data = json_data[str(appid)]['data']
        date_value = data.get('release_date', {}).get('date', '')
        for fmt in ("%b %d, %Y", "%d %b, %Y"):
            try:
                date_value = datetime.strptime(date_value, fmt).strftime("%Y-%m-%d")
                break
            except (ValueError, TypeError):
                continue

        # Extract and format the specific fields we want
        extracted = {
            'developers': ", ".join(data.get('developers', [])), #TEXT
            'publishers': ", ".join(data.get('publishers', [])), #TEXT
            'release_date': date_value #TEXT
        }

        return extracted

    except Exception as e:
        print(f"Error fetching store data for {appid}")
        return None


# Scrape Reviews API (Percentage, Description)
def fetch_review_data(appid):
    # Re-adding the num_per_page=0 from your old working version
    url = f"https://store.steampowered.com/appreviews/{appid}?json=1"

    try:
        # Adding a timeout like your old code had to prevent hanging
        response = requests.get(url, timeout=20)

        # Checking for 200 status code specifically as your old code did
        if response.status_code == 200:
            data = response.json()
            summary = data.get('query_summary', {})
            total = summary.get('total_reviews', 0)
            positive = summary.get('total_positive', 0)
            score = summary.get('review_score_desc', 'No Reviews') if total >= 10 else 'Not Enough Reviews'

            # Using your old working percentage calculation
            percent = int((positive / total) * 100) if total > 0 else 0

            if total == 0:
                weighted = 0
            elif total < 10:
                weighted = int(percent * 0.25)
            elif total < 100:
                factor = 0.5 + 0.5 * (total - 10) / 90
                weighted = int(percent * factor)
            else:
                weighted = percent

            return {
                'review_score': score, #TEXT
                'review_percentage': percent, #INT
                'weighted_percentage': weighted, #INT
                'total_reviews': total, #INT
                'positive_reviews': positive #INT
            }
        else:
            print(f"Steam Review API returned status: {response.status_code}")
            return None

    except Exception as e:
        print(f"Error fetching review data for {appid}")
        return None


# Scrape Achievements API (Total, Unlocked)
def fetch_cheevo_data(appid):
    config = load_config()
    if not config:
        return None

    api_key = config['api_key']
    steam_id = config['steam_id']

    url = f"https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/?appid={appid}&key={api_key}&steamid={steam_id}&include_played_free_games=1&skip_unvetted_apps=false"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        json_data = response.json()

        playerstats = json_data.get('playerstats', {})
        if not playerstats.get('success'):
            print(f"No achievement data found for {appid} (Game might not have them)")
            return None

        achievements = playerstats.get('achievements', [])

        # Calculate the numbers for DB columns
        total = len(achievements)
        unlocked = sum(1 for a in achievements if a.get('achieved') == 1)

        if total > 0 and unlocked == total:
                    return {
                        'total_achievements': total, #INT
                        'unlocked_achievements': unlocked, #INT
                        'completion_status': "Completed" #TEXT
                    }
        return {
            'total_achievements': total, #INT
            'unlocked_achievements': unlocked #INT
        }

    except Exception as e:
        print(f"Error fetching achievement data for AppID: {appid}")
        return None

def fetch_tag_data(appid):
    """
    Scrapes the top user-defined tags from the Steam store page.
    Returns a dictionary containing a comma-separated string of tags.
    """
    url = f"https://store.steampowered.com/app/{appid}/?l=english"
    # We include a birthtime cookie to bypass the mature content age-gate
    headers = {
        'Cookie': 'birthtime=283993201; lastagecheckage=1-0-1979',
        'User-Agent': 'Mozilla/5.0'
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            # User tags are in <a> tags with the class 'app_tag'
            tag_elements = soup.find_all('a', class_='app_tag')

            # Clean up whitespace and filter out the '+' button tag if it exists
            tags = [tag.get_text().strip() for tag in tag_elements if tag.get_text().strip() != "+"]

            if tags:
                return {'tags': ",".join(tags)}
    except Exception as e:
        print(f"Error scraping tags for {appid}: {e}")

    return None

def scrape_blaeo_games():
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import WebDriverException
    config = load_config()
    # Ensure we use the URL from config, or build it if missing
    blaeo_url = config.get('blaeo_url')
    if not blaeo_url:
        steam_id = config.get('steam_id')
        blaeo_url = f"https://www.backlog-assassins.net/users/+{steam_id}/games"

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    try:
        driver = webdriver.Chrome(options=chrome_options)
    except WebDriverException:
        raise RuntimeError(
            "BLAEO sync requires Google Chrome to be installed. "
            "Please install Chrome from https://www.google.com/chrome and try again."
        )

    # BLAEO classes are lowercase. 'game-never-played' becomes 'Never-played'
    # after your .replace().capitalize() logic.
    status_map = {
        "Never-played": "Never Played",
        "Wont-play": "Won't Play",
        "Unfinished": "Unfinished",
        "Beaten": "Beaten",
        "Completed": "Completed"
    }

    try:
        print(f"Opening BLAEO: {blaeo_url}")
        driver.get(blaeo_url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "game-table"))
        )

        # We scroll down, wait, and check if the page height increased.
        last_height = driver.execute_script("return document.body.scrollHeight")

        while True:
            # Scroll to the bottom
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            # Wait for new games to trigger and load
            time.sleep(2)

            # Calculate new scroll height and compare with last scroll height
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                # If heights match, we've hit the absolute bottom
                break
            last_height = new_height
            print("Scrolling to load more games...")

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.select("table.game-table tbody tr.game")

        db = get_db()
        cursor = db.cursor()
        updated_count = 0

        for row in rows:
            try:
                steam_link = row.select_one("a.steam")
                if not steam_link:
                    continue

                href = steam_link.get('href', '')
                appid_match = re.search(r'/app/(\d+)', href)
                if not appid_match:
                    continue
                appid = int(appid_match.group(1)) # Convert to int to match DB type

                # Extract status from class (e.g., class="game game-never-played")
                classes = row.get('class', [])
                raw_status = "Unknown"
                for c in classes:
                    if c.startswith("game-") and c != "game":
                        # c.replace("game-", "") -> "never-played"
                        # .capitalize() -> "Never-played"
                        raw_status = c.replace("game-", "").capitalize()

                clean_status = status_map.get(raw_status, raw_status)

                # Extract Group Tags
                tag_elements = row.select("a.list-tag")
                blaeo_groups = [tag.get_text(strip=True) for tag in tag_elements]

                # Match against the DB
                cursor.execute("SELECT groups FROM games WHERE appid = ?", (appid,))
                db_row = cursor.fetchone()

                if db_row:
                    existing_groups_str = db_row['groups'] if db_row['groups'] else ""
                    existing_groups_set = set(g.strip() for g in existing_groups_str.split(',') if g.strip())

                    updated_groups_set = existing_groups_set.union(set(blaeo_groups))
                    new_groups_str = ",".join(sorted(updated_groups_set))

                    cursor.execute(
                        "UPDATE games SET completion_status = ?, groups = ? WHERE appid = ?",
                        (clean_status, new_groups_str, appid)
                    )
                    updated_count += 1
                else:
                    # This helps you see if the scraper found games you haven't added yet
                    print(f"Game found on BLAEO but not in local DB: AppID {appid}")

            except Exception as e:
                print(f"Skipping a row due to error: {e}")
                continue

        db.commit()
        db.close()
        print(f"Successfully synced {updated_count} games from BLAEO.")
        return {"status": "success", "updated": updated_count}

    except Exception as e:
        print(f"General Scraper Error: {e}")
        return {"status": "error", "message": str(e)}

    finally:
        driver.quit()

def sync_recent_playtime():
    """
    On startup: fetch GetRecentlyPlayedGames (up to 100 games, last 2 weeks)
    and update playtime_forever + last_played for any that exist in the DB.
    Runs in a background thread — safe to call without blocking startup.
    Requires an API key; silently skips if unconfigured.
    """
    import logging
    log = logging.getLogger(__name__)

    try:
        config = load_config()
        if not config:
            return
        api_key  = config.get('api_key', '').strip()
        steam_id = config.get('steam_id', '').strip()
        if not api_key or not steam_id:
            log.info("sync_recent_playtime: no API key configured, skipping.")
            return

        url = (
            f"https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v1/"
            f"?key={api_key}&steamid={steam_id}&count=100&format=json"
        )
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        recent = data.get('response', {}).get('games', [])
        if not recent:
            log.info("sync_recent_playtime: no recently played games returned.")
            return

        db = get_db()
        # Build a set of appids we actually have in the DB to avoid unnecessary updates
        existing = {
            row[0]
            for row in db.execute("SELECT appid FROM games").fetchall()
        }

        updated = 0
        for g in recent:
            appid    = g.get('appid')
            playtime = g.get('playtime_forever', 0)
            rtime    = g.get('rtime_last_played', 0)
            if appid not in existing:
                continue
            last_played = (
                datetime.fromtimestamp(rtime).strftime('%Y-%m-%d')
                if rtime and rtime > 0 else None
            )
            if last_played:
                db.execute(
                    "UPDATE games SET playtime_forever = ?, last_played = ? WHERE appid = ?",
                    (playtime, last_played, appid)
                )
            else:
                db.execute(
                    "UPDATE games SET playtime_forever = ? WHERE appid = ?",
                    (playtime, appid)
                )
            updated += 1

        db.commit()
        db.close()
        log.info(f"sync_recent_playtime: updated {updated} games.")

    except Exception as e:
        logging.getLogger(__name__).warning(f"sync_recent_playtime failed: {e}")
