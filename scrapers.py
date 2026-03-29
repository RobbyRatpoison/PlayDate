import json
import logging
import os
import re
import requests
import time

log = logging.getLogger(__name__)
from bs4 import BeautifulSoup
from images import download_vertical, download_horizontal, download_icon, _get_steam_assets
from datetime import datetime
from config import load_config, get_active_account
from database import add_new_game, update_game_data, get_db, add_to_blacklist
from utils import get_locally_installed_appids, sync_local_install_status, fetch_local_library, get_acf_names, parse_appinfo


class RateLimitedError(Exception):
    """Raised when Steam returns HTTP 429 and the retry also fails."""
    pass



def add_new(cancel_event=None, progress_cb=None):
    limit = 0  # 0 = unlimited
    account = get_active_account()
    if not account:
        return {"status": "error", "message": "No account configured"}

    api_key = account.get('api_key')
    steam_id = account.get('steam_id')

    if api_key:
        # ── API key path: fetch full library from Steam ────────────────────────
        log.info("Fetching games via Steam API.")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
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
            games = [{'appid': g['appid'], 'name': g.get('name', ''), 'playtime_forever': g.get('playtime_forever', 0), 'last_played': datetime.fromtimestamp(g.get('rtime_last_played', 0)).strftime('%Y-%m-%d') if g.get('rtime_last_played', 0) > 0 else '0', 'icon_hash': g.get('img_icon_url', '')} for g in raw_games]
        except requests.exceptions.JSONDecodeError:
            return {"status": "error", "message": "Steam sent invalid data. Try again in a few minutes."}
        except Exception as e:
            return {"status": "error", "message": f"Connection Error: {str(e)}"}
    else:
        # ── No API key path: read library from local Steam files ───────────────
        log.info("No API key — reading library from localconfig.vdf.")
        local_games = fetch_local_library(steam_id)
        if not local_games:
            return {"status": "error", "message": "Could not read library from local Steam files. Make sure Steam is installed and has been launched at least once. If this is a fresh install, try re-running install.py to ensure all dependencies are up to date."}
        acf_names  = get_acf_names()
        appinfo_db = parse_appinfo()  # offline name + type from Steam's local cache
        games = [{
            'appid':            g['appid'],
            # name priority: ACF manifest → appinfo.vdf cache → filled from Store API below
            'name':             acf_names.get(g['appid']) or appinfo_db.get(g['appid'], {}).get('name', ''),
            'playtime_forever': g['playtime_forever'],
            'last_played':      g['last_played'],
            'icon_hash':        '',
        } for g in local_games]

    # No-key path: appinfo_db already loaded above.
    # API key path: GetOwnedGames can still return DLC/mods/advertising entries,
    # so load appinfo for pre-filtering to keep the progress counter accurate.
    if api_key:
        appinfo_db = parse_appinfo()

    # Process new games
    db = get_db()
    installed_ids   = get_locally_installed_appids()
    existing_ids    = {row['appid'] for row in db.execute("SELECT appid FROM games").fetchall()}
    blacklisted_ids = {row['appid'] for row in db.execute("SELECT appid FROM blacklist").fetchall()}
    db.close()

    new_games = [g for g in reversed(games) if g['appid'] not in existing_ids and g['appid'] not in blacklisted_ids
                 and appinfo_db.get(g['appid'], {}).get('type', 'game').lower() == 'game']
    total_new = len(new_games)

    new_count = 0
    skip_count = 0
    for game in new_games:
        if cancel_event and cancel_event.is_set():
            log.info(f"Populate cancelled after {new_count} games.")
            return {"status": "cancelled", "added": new_count}

        appid = game['appid']
        rate_limit_attempts = 0

        while True:
            try:
                name = game['name']
                playtime = game['playtime_forever']
                last_played = game['last_played']
                played = "Unfinished" if playtime > 0 else "Never Played"
                today = datetime.now().strftime('%Y-%m-%d')
                icon_hash  = game.get('icon_hash', '')

                # Types to auto-blacklist (add more once identified via logs)
                AUTO_BLACKLIST_TYPES = set()

                store_info = fetch_store_data(appid)
                if store_info:
                    app_type = store_info.pop('type', '')
                    if app_type in AUTO_BLACKLIST_TYPES:
                        log.info(f"Skipping AppID {appid} ({name!r}) — store type '{app_type}' is blacklisted. Auto-blacklisting.")
                        add_to_blacklist(appid, name or f"AppID {appid}")
                        skip_count += 1
                        total_new -= 1
                        break
                    if app_type:
                        log.info(f"Adding AppID {appid} ({name!r}) — store type '{app_type}'")
                elif not name:
                    # No store data and no local name — off-store runtime/tool, skip it
                    log.info(f"Skipping AppID {appid} — not on Steam store and no local name found. Auto-blacklisting.")
                    add_to_blacklist(appid, f"AppID {appid}")
                    skip_count += 1
                    total_new -= 1
                    break

                if progress_cb:
                    progress_cb(new_count, total_new, name or f"AppID {appid}")

                assets            = _get_steam_assets(appid)
                vertical_source   = download_vertical(appid, assets=assets)
                horizontal_source = download_horizontal(appid, assets=assets)
                icon_source       = download_icon(appid, icon_hash)

                game_data = {
                    'playtime_forever':      playtime,
                    'date_added':            today,
                    'completion_status':     played,
                    'last_played':           last_played,
                    'vertical_art_source':   vertical_source,
                    'horizontal_art_source': horizontal_source,
                    'icon_source':           icon_source,
                    'icon_hash':             icon_hash,
                    'installed':             1 if appid in installed_ids else 0,
                    'unlocked_achievements': 0,
                    'total_achievements':    0,
                }

                if store_info:
                    # Use store name as fallback when local sources didn't have one
                    if not name:
                        name = store_info.pop('name', '') or f"AppID {appid}"
                    else:
                        store_info.pop('name', None)
                    game_data.update(store_info)

                review_info = fetch_review_data(appid)
                if review_info:
                    game_data.update(review_info)

                tag_info = fetch_tag_data(appid)
                if tag_info:
                    game_data.update(tag_info)

                if api_key:
                    cheevo_info = fetch_cheevo_data(appid)
                    if cheevo_info:
                        game_data.update(cheevo_info)

                add_new_game(appid, name)
                update_game_data(appid, **game_data)

                new_count += 1
                log.info(f"Added game #{new_count}: {name} (AppID {appid})")
                if progress_cb:
                    progress_cb(new_count, total_new, name)
                log.info(f"Added game #{new_count}: {name} (AppID {appid})")
                break

            except RateLimitedError:
                rate_limit_attempts += 1
                if rate_limit_attempts == 1:
                    log.warning(f"Rate limited by Steam on AppID {appid}. Pausing 15s before retry...")
                    if progress_cb:
                        progress_cb(new_count, total_new, "Rate limited — pausing 15s...")
                    time.sleep(15)
                    # loop back and retry this game
                else:
                    log.warning("Rate limit persists after retry. Aborting populate.")
                    return {
                        "status": "error",
                        "message": "Steam is rate limiting requests. Try again in a few minutes.",
                        "added": new_count
                    }

            except Exception as e:
                skip_count += 1
                log.error(f"Error processing {game.get('name', '') or appid} (AppID {appid}): {e} — skipping.")
                break

        time.sleep(0.5)

        if limit > 0 and new_count >= limit:
            return {"status": "success", "added": new_count}

    if skip_count:
        log.info(f"Populate complete. Added {new_count}, skipped {skip_count}.")
    return {"status": "success", "added": new_count}

# Scrape Player API (Name, Playtime, Last Played)
def fetch_player_data(appid):
    account = get_active_account()
    if not account:
        return None

    api_key = account.get('api_key')
    steam_id = account.get('steam_id')

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
        log.error(f"Error fetching player data for {appid}: {e}")
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
        if response.status_code == 429:
            raise RateLimitedError()
        response.raise_for_status()
        json_data = response.json()

        # The API returns data keyed by the appid string
        if not json_data or not json_data.get(str(appid), {}).get('success'):
            log.info(f"Could not find store data for {appid}")
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
            'name':         data.get('name', ''),
            'type':         data.get('type', ''),
            'developers':   ", ".join(data.get('developers', [])),
            'publishers':   ", ".join(data.get('publishers', [])),
            'release_date': date_value,
            'genres':      ",".join(g['description'] for g in data.get('genres', [])),
            'categories':  ",".join(c['description'] for c in data.get('categories', [])),
            'is_free':     1 if data.get('is_free') else 0,
        }

        return extracted

    except Exception as e:
        log.error(f"Error fetching store data for {appid}")
        return None


# Scrape Reviews API (Percentage, Description)
def fetch_review_data(appid):
    # Re-adding the num_per_page=0 from your old working version
    url = f"https://store.steampowered.com/appreviews/{appid}?json=1&language=all&num_per_page=0&purchase_type=all"

    try:
        # Adding a timeout like your old code had to prevent hanging
        response = requests.get(url, timeout=20)
        if response.status_code == 429:
            raise RateLimitedError()

        # Checking for 200 status code specifically as your old code did
        if response.status_code == 200:
            data = response.json()
            summary = data.get('query_summary', {})
            total = summary.get('total_reviews', 0)
            positive = summary.get('total_positive', 0)
            if total == 0:
                score = 'No Reviews'
            elif total < 10:
                score = 'Not Enough Reviews'
            else:
                score = summary.get('review_score_desc', 'No Reviews')

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
            log.warning(f"Steam Review API returned status: {response.status_code}")
            return None

    except Exception as e:
        log.error(f"Error fetching review data for {appid}")
        return None


# Scrape Achievements API (Total, Unlocked)
def fetch_cheevo_data(appid):
    account = get_active_account()
    if not account:
        return None

    api_key = account.get('api_key', '').strip()
    steam_id = account.get('steam_id', '').strip()

    if not api_key or not steam_id:
        return None

    url = f"https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/?appid={appid}&key={api_key}&steamid={steam_id}&include_played_free_games=1&skip_unvetted_apps=false"

    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 429:
            raise RateLimitedError()
        response.raise_for_status()
        json_data = response.json()

        playerstats = json_data.get('playerstats', {})
        if not playerstats.get('success'):
            log.info(f"No achievement data for {appid} (game may not have achievements)")
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
        log.error(f"Error fetching achievement data for AppID: {appid}")
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
        if response.status_code == 429:
            raise RateLimitedError()
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            # User tags are in <a> tags with the class 'app_tag'
            tag_elements = soup.find_all('a', class_='app_tag')

            # Clean up whitespace and filter out the '+' button tag if it exists
            tags = [tag.get_text().strip() for tag in tag_elements if tag.get_text().strip() != "+"]

            if tags:
                return {'tags': ",".join(tags)}
    except Exception as e:
        log.error(f"Error scraping tags for {appid}: {e}")

    return None

def scrape_blaeo_games():
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import WebDriverException
    config = load_config()
    account = get_active_account()
    # Ensure we use the URL from config, or build it if missing
    blaeo_url = config.get('blaeo_url')
    if not blaeo_url:
        steam_id = (account or {}).get('steam_id')
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
        log.info(f"Opening BLAEO: {blaeo_url}")
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
            log.info("Scrolling to load more BLAEO games...")

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
                    log.info(f"Game found on BLAEO but not in local DB: AppID {appid}")

            except Exception as e:
                log.error(f"Skipping a BLAEO row due to error: {e}")
                continue

        db.commit()
        db.close()
        log.info(f"Successfully synced {updated_count} games from BLAEO.")
        return {"status": "success", "updated": updated_count}

    except Exception as e:
        log.error(f"BLAEO scraper error: {e}")
        return {"status": "error", "message": str(e)}

    finally:
        driver.quit()

def sync_recent_playtime():
    """
    On startup: update playtime_forever + last_played for all played games by
    reading localconfig.vdf directly. No API key required. Runs in a background
    thread — safe to call without blocking startup.
    """
    import logging
    log = logging.getLogger(__name__)

    try:
        account = get_active_account()
        if not account:
            return
        steam_id = account.get('steam_id', '').strip()
        if not steam_id:
            return

        from utils import fetch_local_library
        recent = [
            {
                'appid':            g['appid'],
                'playtime_forever': g['playtime_forever'],
                'last_played':      g['last_played'] if g['last_played'] != '0' else None,
            }
            for g in fetch_local_library(steam_id)
        ]

        if not recent:
            log.info("sync_recent_playtime: no games to sync.")
            return

        db = get_db()
        existing = {row[0] for row in db.execute("SELECT appid FROM games").fetchall()}

        updated = 0
        for g in recent:
            appid = g['appid']
            if appid not in existing:
                continue
            if g['last_played']:
                db.execute(
                    "UPDATE games SET playtime_forever = ?, last_played = ? WHERE appid = ?",
                    (g['playtime_forever'], g['last_played'], appid)
                )
            else:
                db.execute(
                    "UPDATE games SET playtime_forever = ? WHERE appid = ?",
                    (g['playtime_forever'], appid)
                )
            updated += 1

        db.commit()
        db.close()
        log.info(f"sync_recent_playtime: updated {updated} games.")

    except Exception as e:
        logging.getLogger(__name__).warning(f"sync_recent_playtime failed: {e}")
