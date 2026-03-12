import json
import os
import re
import requests
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from images import download_capsule
from datetime import datetime, timedelta
from config import load_config
from database import add_new_game, update_game_data, get_db
from utils import get_locally_installed_appids, sync_local_install_status

# Add new games with basic info
def parse_steam_date(raw):
    """
    Parses Steam's fuzzy date formats from the public profile page.
    Handles: 'yesterday', 'Feb 28', 'Feb 28, 2023', 'last week', etc.
    Returns a YYYY-MM-DD string or None if unparseable.
    """
    if not raw:
        return None
    raw = raw.strip().lower()
    today = datetime.now()

    if raw == 'yesterday':
        return (today - timedelta(days=1)).strftime('%Y-%m-%d')

    if raw in ('last week', 'a week ago'):
        return (today - timedelta(weeks=1)).strftime('%Y-%m-%d')

    # Try "Feb 28" — assume current year
    try:
        dt = datetime.strptime(raw, '%b %d')
        return dt.replace(year=today.year).strftime('%Y-%m-%d')
    except ValueError:
        pass

    # Try "Feb 28, 2023"
    try:
        dt = datetime.strptime(raw, '%b %d, %Y')
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        pass

    return None


def scrape_games_from_profile(vanity_or_id):
    """
    Scrapes the public Steam profile games page as a fallback
    when no API key is available.
    Returns a list of dicts with appid, name, playtime_forever, last_played.
    Requires the user's profile and game details to be set to Public.
    """
    # Build the profile URL — works with both vanity names and SteamID64
    url = f"https://steamcommunity.com/id/{vanity_or_id}/games?tab=all"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Steam embeds game data as a JS variable: var rgGames = [...]
        script_tags = soup.find_all('script')
        games_json = None
        for script in script_tags:
            if script.string and 'rgGames' in script.string:
                match = re.search(r'var rgGames\s*=\s*(\[.*?\]);', script.string, re.DOTALL)
                if match:
                    games_json = match.group(1)
                    break

        if not games_json:
            print("Could not find game data on Steam profile page. Is the profile public?")
            return None

        games = json.loads(games_json)
        results = []
        for game in games:
            appid = game.get('appid')
            name = game.get('name', '')
            playtime = game.get('hours_forever', '0').replace(',', '')
            try:
                playtime_mins = int(float(playtime) * 60)
            except (ValueError, TypeError):
                playtime_mins = 0

            last_played_raw = game.get('last_played', '')
            last_played = parse_steam_date(last_played_raw)

            results.append({
                'appid': appid,
                'name': name,
                'playtime_forever': playtime_mins,
                'last_played': last_played or '0'
            })

        return results

    except Exception as e:
        print(f"Error scraping Steam profile: {e}")
        return None

def add_new(cancel_event=None):
    config = load_config()
    if not config:
        return {"status": "error", "message": "No config found"}

    api_key = config.get('api_key')
    steam_id = config.get('steam_id')
    vanity_name = config.get('vanity_name') or steam_id
    has_api_key = bool(api_key)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Fetch game list via API or public profile scraper
    if has_api_key:
        print("Fetching games via Steam API.")
        url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={api_key}&steamid={steam_id}&format=json&include_appinfo=true&include_played_free_games=1"
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
    else:
        print("No API key — falling back to public profile scraper.")
        games = scrape_games_from_profile(vanity_name)
        if not games:
            return {"status": "error", "message": "Could not load games from your Steam profile. Make sure your profile and game details are set to Public."}

    # Process new games
    db = get_db()
    installed_ids = get_locally_installed_appids()
    existing_ids = [row['appid'] for row in db.execute("SELECT appid FROM games").fetchall()]
    db.close()

    new_count = 0
    for game in reversed(games):
        if cancel_event and cancel_event.is_set():
            print(f"Populate cancelled after {new_count} games.")
            return {"status": "cancelled", "added": new_count}

        appid = game['appid']
        if appid not in existing_ids:
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

            if has_api_key:
                cheevo_info = fetch_cheevo_data(appid)
                if cheevo_info:
                    game_data.update(cheevo_info)

            add_new_game(appid, game['name'])
            update_game_data(appid, **game_data)

            new_count += 1
            print(f"Scraped data for game #{new_count}: {game['name']}")
            time.sleep(1.2)

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

    def _parse_game(game):
        last_played_unix = game.get('rtime_last_played', 0)
        last_played_date = datetime.fromtimestamp(last_played_unix).strftime('%Y-%m-%d') if last_played_unix > 0 else '0'
        return {
            'name': game.get('name', ''),
            'playtime_forever': game.get('playtime_forever', 0),
            'last_played': last_played_date
        }

    base = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={api_key}&steamid={steam_id}&format=json&include_appinfo=true"

    try:
        # Fast path: filtered single-game fetch (works for paid games)
        resp = requests.get(f"{base}&appids_filter[0]={appid}", timeout=10)
        resp.raise_for_status()
        games = resp.json().get('response', {}).get('games', [])
        if games:
            return _parse_game(games[0])

        # appids_filter silently drops free games even with include_played_free_games=1.
        # Fall back to full library fetch and find the game there.
        print(f"appids_filter returned nothing for {appid} — retrying with full library (likely a free game)")
        resp2 = requests.get(f"{base}&include_played_free_games=1", timeout=15)
        resp2.raise_for_status()
        match = next((g for g in resp2.json().get('response', {}).get('games', []) if g.get('appid') == appid), None)
        if match:
            return _parse_game(match)

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
        response = requests.get(url, timeout=10)
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
    # purchase_type=all is required — the default ('steam') only counts purchasers,
    # so free-to-play games return an empty summary. cc+l ensure consistent responses.
    url = f"https://store.steampowered.com/appreviews/{appid}?json=1&purchase_type=all&cc=us&l=english"

    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()

        if response.status_code == 200:
            data = response.json()
            summary = data.get('query_summary', {})
            total = summary.get('total_reviews', 0)
            positive = summary.get('total_positive', 0)
            score = summary.get('review_score_desc', 'No Reviews') if total >= 10 else 'Not Enough Reviews'

            # Using your old working percentage calculation
            percent = int((positive / total) * 100) if total > 0 else 0

            if total < 20:
                weighted = 0
            elif total < 100:
                weighted = int(percent * total / 100)
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

    url = f"https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/?appid={appid}&key={api_key}&steamid={steam_id}"

    try:
        response = requests.get(url)
        # Steam returns HTTP 400 for games with no achievements — don't raise, parse the body instead
        json_data = response.json()

        playerstats = json_data.get('playerstats', {})
        if not playerstats.get('success'):
            print(f"No achievement data found for {appid} (game has no achievements)")
            return {'total_achievements': 0, 'unlocked_achievements': 0}

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
    except Exception:
        return {
            "status": "error",
            "message": "Chrome not found. Please install Google Chrome to use BLAEO sync."
        }

    # Map BLAEO CSS class suffixes to PlayDate completion statuses.
    # Keys are the raw string after stripping 'game-' from the class name.
    status_map = {
        "never-played": "Never Played",
        "wont-play":    "Won't Play",
        "unfinished":   "Unfinished",
        "beaten":       "Beaten",
        "completed":    "Completed",
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
                raw_status = None
                for c in classes:
                    if c.startswith("game-") and c != "game":
                        raw_status = c.replace("game-", "")
                        break

                clean_status = status_map.get(raw_status)
                if not clean_status:
                    print(f"Unknown BLAEO status class '{raw_status}' for appid {appid} — skipping status update")
                    clean_status = None

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

                    if clean_status:
                        cursor.execute(
                            "UPDATE games SET completion_status = ?, groups = ? WHERE appid = ?",
                            (clean_status, new_groups_str, appid)
                        )
                    else:
                        cursor.execute(
                            "UPDATE games SET groups = ? WHERE appid = ?",
                            (new_groups_str, appid)
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
