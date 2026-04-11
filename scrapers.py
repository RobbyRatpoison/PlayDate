import json
import logging
import math
import os
import queue
import re
import requests
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait

log = logging.getLogger(__name__)
from bs4 import BeautifulSoup
from images import download_vertical, download_horizontal, download_icon, _get_steam_assets, VERTICAL_DIR, HORIZONTAL_DIR, ICONS_DIR
from datetime import datetime
from config import load_config, get_active_account
from database import add_new_game, batch_insert_placeholder_games, update_game_data, get_db, add_to_blacklist
from utils import get_locally_installed_appids, sync_local_install_status, fetch_local_library, get_acf_names, parse_appinfo


class RateLimitedError(Exception):
    """Raised when Steam returns HTTP 429."""
    pass


# Backoff delays in seconds: 15s → 1m → 5m → 1h+15s
BACKOFF_DELAYS = [15, 60, 300, 3615]


class _PoolBackoff:
    """
    Per-pool rate-limit gate. When any worker in the pool hits a 429 it calls
    on_rate_limited(), which closes the gate and sleeps for the next delay in
    the sequence. All other workers in the pool block on wait_ready() until the
    gate reopens. After BACKOFF_DELAYS is exhausted the pool is marked aborted.
    """

    def __init__(self, name):
        self.name    = name
        self._gate   = threading.Event()
        self._gate.set()          # open = workers can proceed
        self._attempt = 0
        self._lock    = threading.Lock()
        self.aborted  = False

    def on_rate_limited(self, cancel_event=None):
        """
        Called by the worker that received the 429.
        Returns True if the pool should keep running, False if all retries are
        exhausted (caller should exit the worker).
        """
        with self._lock:
            if self.aborted:
                return False
            if not self._gate.is_set():
                # Another worker already triggered backoff; just wait for it.
                return True
            if self._attempt >= len(BACKOFF_DELAYS):
                self.aborted = True
                log.warning(f"[{self.name}] All backoff attempts exhausted — aborting pool.")
                return False
            delay = BACKOFF_DELAYS[self._attempt]
            self._attempt += 1
            self._gate.clear()

        log.warning(
            f"[{self.name}] Rate limited. Waiting {delay}s "
            f"(attempt {self._attempt}/{len(BACKOFF_DELAYS)})..."
        )
        deadline = time.time() + delay
        while time.time() < deadline:
            if cancel_event and cancel_event.is_set():
                with self._lock:
                    self._gate.set()
                return False
            time.sleep(min(1.0, deadline - time.time()))

        with self._lock:
            if not self.aborted:
                self._gate.set()
        return True

    def wait_ready(self, cancel_event=None):
        """
        Block until the gate is open (pool not in backoff).
        Returns False if the pool was aborted or cancelled.
        """
        while not self._gate.wait(timeout=1.0):
            if cancel_event and cancel_event.is_set():
                return False
        return not self.aborted


def _next(priority_q, normal_q, timeout=0.5):
    """Pull from priority queue first, fall back to normal queue."""
    try:
        return priority_q.get_nowait()
    except queue.Empty:
        pass
    try:
        return normal_q.get(timeout=timeout)
    except queue.Empty:
        return None


# ── Worker functions ──────────────────────────────────────────────────────────

def _art_worker(normal_q, priority_q, cancel_event, icon_hash_map, today, progress_cb):
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0'
    while True:
        if cancel_event and cancel_event.is_set():
            return
        appid = _next(priority_q, normal_q)
        if appid is None:
            return
        # Skip if already fetched (priority queue may contain duplicates)
        db  = get_db()
        row = db.execute(
            "SELECT art_fetched, vertical_art_source, horizontal_art_source, icon_source FROM games WHERE appid=?",
            (appid,)
        ).fetchone()
        db.close()
        if row and row['art_fetched'] != '0':
            continue
        # Skip if image files already exist on disk (e.g. after a DB reset),
        # but backfill any source columns that were never recorded.
        v_path = os.path.join(VERTICAL_DIR,   f"{appid}.jpg")
        h_path = os.path.join(HORIZONTAL_DIR, f"{appid}.jpg")
        i_path = os.path.join(ICONS_DIR,      f"{appid}.jpg")
        if os.path.exists(v_path) or os.path.exists(h_path) or os.path.exists(i_path):
            src_updates = {}
            if os.path.exists(v_path) and not (row and row['vertical_art_source']):
                src_updates['vertical_art_source'] = 'capsule'
            if os.path.exists(h_path) and not (row and row['horizontal_art_source']):
                src_updates['horizontal_art_source'] = 'header'
            if os.path.exists(i_path) and not (row and row['icon_source']):
                src_updates['icon_source'] = 'steam' if icon_hash_map.get(appid) else 'sgdb_icon'
            update_game_data(appid, art_fetched=today, **src_updates)
            if progress_cb:
                progress_cb('art', appid, None)
            continue
        try:
            assets  = _get_steam_assets(appid)
            v_src   = download_vertical(appid, assets=assets)
            h_src   = download_horizontal(appid, assets=assets)
            i_src   = download_icon(appid, icon_hash_map.get(appid, ''))
            update_game_data(appid,
                vertical_art_source=v_src,
                horizontal_art_source=h_src,
                icon_source=i_src,
                art_fetched=today,
            )
            if progress_cb:
                progress_cb('art', appid, None)
        except Exception as e:
            log.error(f"[art] Error for {appid}: {e}")


def _meta_worker(normal_q, priority_q, backoff, cancel_event, total, today, progress_cb):
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    AUTO_BLACKLIST_TYPES = set()

    while True:
        if cancel_event and cancel_event.is_set():
            return
        if not backoff.wait_ready(cancel_event):
            return

        appid = _next(priority_q, normal_q)
        if appid is None:
            return

        db  = get_db()
        row = db.execute("SELECT meta_fetched, name FROM games WHERE appid=?", (appid,)).fetchone()
        db.close()
        if row and row['meta_fetched'] != '0':
            continue

        name = (row['name'] or '') if row else ''

        try:
            store_info = fetch_store_data(appid, session=session)

            if not store_info and not name:
                # Off-store entry with no local name — blacklist and remove placeholder
                add_to_blacklist(appid, f"AppID {appid}")
                db = get_db()
                db.execute("DELETE FROM games WHERE appid=?", (appid,))
                db.commit()
                db.close()
                if progress_cb:
                    progress_cb('blacklist', appid, total)
                time.sleep(0.5)
                continue

            if store_info:
                app_type = store_info.pop('type', '')
                if app_type in AUTO_BLACKLIST_TYPES:
                    add_to_blacklist(appid, name or f"AppID {appid}")
                    db = get_db()
                    db.execute("DELETE FROM games WHERE appid=?", (appid,))
                    db.commit()
                    db.close()
                    if progress_cb:
                        progress_cb('blacklist', appid, total)
                    time.sleep(0.5)
                    continue

            game_data = {'meta_fetched': today}

            if store_info:
                if not name:
                    # Name not provided by GetOwnedGames or local files — use store name
                    new_name = store_info.pop('name', '') or f"AppID {appid}"
                    db = get_db()
                    db.execute("UPDATE games SET name=? WHERE appid=?", (new_name, appid))
                    db.commit()
                    db.close()
                else:
                    store_info.pop('name', None)
                game_data.update(store_info)

            review_info = fetch_review_data(appid, session=session)
            if review_info:
                game_data.update(review_info)

            tag_info = fetch_tag_data(appid, session=session)
            if tag_info:
                game_data.update(tag_info)

            update_game_data(appid, **game_data)
            log.info(f"[meta] Done: {name or appid} ({appid})")
            if progress_cb:
                progress_cb('meta', appid, total)
            time.sleep(1.5)

        except RateLimitedError:
            if progress_cb:
                attempt = backoff._attempt + 1
                delay   = BACKOFF_DELAYS[min(backoff._attempt, len(BACKOFF_DELAYS) - 1)]
                progress_cb('rate_limit_hit', {'pool': 'meta', 'attempt': attempt, 'delay': delay}, total)
            priority_q.put(appid)   # re-queue for retry after backoff
            if not backoff.on_rate_limited(cancel_event):
                return
        except Exception as e:
            log.error(f"[meta] Error for {appid}: {e}")
            time.sleep(0.1)


def _cheevo_worker(normal_q, priority_q, backoff, cancel_event, today, progress_cb):
    while True:
        if cancel_event and cancel_event.is_set():
            return
        if not backoff.wait_ready(cancel_event):
            return

        appid = _next(priority_q, normal_q)
        if appid is None:
            return

        db  = get_db()
        row = db.execute("SELECT cheevos_fetched FROM games WHERE appid=?", (appid,)).fetchone()
        db.close()
        if row and row['cheevos_fetched'] != '0':
            continue

        try:
            cheevo_info = fetch_cheevo_data(appid)
            game_data   = {'cheevos_fetched': today}
            if cheevo_info:
                game_data.update(cheevo_info)
            update_game_data(appid, **game_data)
            if progress_cb:
                progress_cb('cheevo', appid, None)
        except RateLimitedError:
            if progress_cb:
                attempt = backoff._attempt + 1
                delay   = BACKOFF_DELAYS[min(backoff._attempt, len(BACKOFF_DELAYS) - 1)]
                progress_cb('rate_limit_hit', {'pool': 'cheevo', 'attempt': attempt, 'delay': delay}, total)
            priority_q.put(appid)
            if not backoff.on_rate_limited(cancel_event):
                return
        except Exception as e:
            log.error(f"[cheevo] Error for {appid}: {e}")


# ── ProtonDB fetch functions ──────────────────────────────────────────────────

def fetch_protondb_data(appid, session=None):
    """
    Fetch ProtonDB summary for a single appid.
    Returns {'protondb_tier': str, 'protondb_confidence': str} or None.
    'pending' tier (no reports) is normalised to None so the caller stores NULL.
    """
    url = f'https://www.protondb.com/api/v1/reports/summaries/{appid}.json'
    try:
        if session:
            r = session.get(url, timeout=10)
        else:
            r = requests.get(url, timeout=10)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        tier = data.get('tier', '')
        if not tier or tier == 'pending':
            return None
        return {
            'protondb_tier':       tier,
            'protondb_confidence': data.get('confidence'),
        }
    except Exception as e:
        log.warning(f"[protondb] fetch failed for {appid}: {e}")
        return None


def _protondb_worker(normal_q, priority_q, cancel_event, today, progress_cb):
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0'
    while True:
        if cancel_event and cancel_event.is_set():
            return

        appid = _next(priority_q, normal_q)
        if appid is None:
            return

        db  = get_db()
        row = db.execute("SELECT protondb_fetched FROM games WHERE appid=?", (appid,)).fetchone()
        db.close()
        if row and row['protondb_fetched'] != '0':
            continue

        try:
            info = fetch_protondb_data(appid, session=session)
            game_data = {'protondb_fetched': today}
            if info:
                game_data.update(info)
            else:
                # No data / pending — clear stale tier in case this is a re-fetch
                game_data['protondb_tier']       = None
                game_data['protondb_confidence'] = None
            update_game_data(appid, **game_data)
            if progress_cb:
                progress_cb('protondb', appid, None)
        except Exception as e:
            log.error(f"[protondb] Error for {appid}: {e}")


# ── HLTB fetch functions ──────────────────────────────────────────────────────

def _hltb_clean_name(name):
    """
    Normalize a Steam game title for HLTB search queries.
    Strips symbols and all punctuation so differences like trailing periods,
    semicolons, or colon-vs-dash separators don't prevent a match.
    """
    import re
    name = re.sub(r'[®™©]', '', name)            # trademark/IP symbols
    name = re.sub(r'\s*\(\d{4}\)\s*$', '', name)  # trailing year, e.g. "(2010)"
    name = re.sub(r'[^\w\s]', ' ', name)           # all remaining punctuation → space
    name = re.sub(r'\bsokpop\s+s\d+\b', '', name, flags=re.IGNORECASE)  # Sokpop S07 series prefix
    name = re.sub(r'\s{2,}', ' ', name)            # collapse whitespace
    return name.strip()


_HLTB_EDITION_RE = None

def _hltb_strip_edition(name):
    """
    Strip common trailing edition/remaster qualifiers that Steam adds but HLTB omits.
    Returns the stripped name, or the original if nothing was removed.
    """
    import re
    global _HLTB_EDITION_RE
    if _HLTB_EDITION_RE is None:
        qualifiers = '|'.join([
            r'definitive', r'remastered', r'hd remaster', r'hd edition',
            r'game of the year', r'goty', r'complete', r'ultimate', r'enhanced',
            r'special', r'anniversary', r'directors? cut', r'deluxe', r'gold',
            r'platinum', r'standard', r'extended', r'legendary',
        ])
        # optionally preceded by a separator word or space, followed by optional "edition/version/cut"
        _HLTB_EDITION_RE = re.compile(
            r'\s+(?:' + qualifiers + r')(?:\s+(?:edition|version|cut))?\s*$',
            re.IGNORECASE
        )
    stripped = _HLTB_EDITION_RE.sub('', name).strip()
    return stripped if stripped != name else name


def fetch_hltb_data(name, threshold=75):
    """
    Fetch HowLongToBeat data for a game by name.
    If the best match score >= threshold, returns full data including times.
    If below threshold, returns only hltb_id + hltb_match_score with
    hltb_fetched='unconfirmed' and no times (NULL) so bad data isn't stored.
    Returns None on no results or failure.
    Times are stored in minutes (HLTB returns hours as floats).
    """
    try:
        from howlongtobeatpy import HowLongToBeat

        def _search(query):
            results = HowLongToBeat(0.0).search(query, similarity_case_sensitive=False)
            if not results:
                return None, 0
            b = max(results, key=lambda r: r.similarity)
            return b, int(round(b.similarity * 100))

        import re
        cleaned = _hltb_clean_name(name)
        best, score = _search(cleaned)
        parens_fallback_used = False

        # Single secondary pass: try edition-stripped and paren-stripped variants
        # together, picking whichever yields the best effective score. Paren-stripped
        # results are penalised by 15 pts since removing brackets loses information.
        if not best or score < threshold:
            seen = {cleaned}
            candidates = []

            shorter = _hltb_strip_edition(cleaned)
            if shorter not in seen:
                seen.add(shorter)
                candidates.append((shorter, False))

            no_parens = _hltb_clean_name(re.sub(r'\s*[\(\[][^\)\]]*[\)\]]\s*', ' ', name))
            if no_parens and no_parens not in seen:
                candidates.append((no_parens, True))

            best_effective = score
            for query, penalised in candidates:
                alt_best, alt_score = _search(query)
                effective = alt_score - (15 if penalised else 0)
                if alt_best and effective > best_effective:
                    best, score, parens_fallback_used = alt_best, alt_score, penalised
                    best_effective = effective

        if not best:
            return None

        def _hours_to_minutes(val):
            if val is None or val < 0:
                return None
            return int(round(val * 60))

        effective_score = score - 15 if parens_fallback_used else score
        if effective_score < threshold:
            return {
                'hltb_id':            best.game_id,
                'hltb_matched_name':  best.game_name,
                'hltb_match_score':   score,
                'hltb_main':          None,
                'hltb_extras':        None,
                'hltb_completionist': None,
                'hltb_fetched':       'unconfirmed',
            }

        today = datetime.now().strftime('%Y-%m-%d')
        return {
            'hltb_id':            best.game_id,
            'hltb_matched_name':  best.game_name,
            'hltb_main':          _hours_to_minutes(best.main_story),
            'hltb_extras':        _hours_to_minutes(best.main_extra),
            'hltb_completionist': _hours_to_minutes(best.completionist),
            'hltb_match_score':   score,
            'hltb_fetched':       today,
        }
    except Exception as e:
        log.warning(f"[hltb] fetch failed for '{name}': {e}")
        return None


def fetch_hltb_by_id(name, hltb_id):
    """
    Fetch HLTB data for a specific game ID. Tries search_from_id first (direct
    lookup, works for compilations), falls back to name search if that fails.
    Returns dict with hltb_matched_name + times, or None on total failure.
    """
    from howlongtobeatpy import HowLongToBeat

    def _hours_to_minutes(val):
        if val is None or val < 0:
            return None
        return int(round(val * 60))

    # Try direct lookup first — works for compilations and anything not in search
    try:
        match = HowLongToBeat().search_from_id(hltb_id)
        if match:
            return {
                'hltb_matched_name':  match.game_name,
                'hltb_main':          _hours_to_minutes(match.main_story),
                'hltb_extras':        _hours_to_minutes(match.main_extra),
                'hltb_completionist': _hours_to_minutes(match.completionist),
                'times_available':    True,
            }
    except Exception as e:
        log.warning(f"[hltb] search_from_id failed for id={hltb_id}: {e}")

    # Fall back to name search (in case search_from_id is unreliable for some entries)
    try:
        results = HowLongToBeat(0.0).search(name, similarity_case_sensitive=False)
        match = next((r for r in (results or []) if r.game_id == hltb_id), None)
        if match:
            return {
                'hltb_matched_name':  match.game_name,
                'hltb_main':          _hours_to_minutes(match.main_story),
                'hltb_extras':        _hours_to_minutes(match.main_extra),
                'hltb_completionist': _hours_to_minutes(match.completionist),
                'times_available':    True,
            }
    except Exception as e:
        log.warning(f"[hltb] name search fallback failed for '{name}' id={hltb_id}: {e}")

    log.info(f"[hltb] id={hltb_id} not found by any method; storing ID only")
    return {
        'hltb_matched_name':  None,
        'hltb_main':          None,
        'hltb_extras':        None,
        'hltb_completionist': None,
        'times_available':    False,
    }


def search_hltb_results(name):
    """
    Search HLTB by name and return the top results for user selection.
    Returns a list of dicts: {hltb_id, hltb_matched_name, hltb_match_score,
    hltb_main, hltb_extras, hltb_completionist} (times in minutes).
    """
    try:
        from howlongtobeatpy import HowLongToBeat
        cleaned = _hltb_clean_name(name)
        results = HowLongToBeat(0.0).search(cleaned, similarity_case_sensitive=False)
        # Fall back to punctuation-stripped query if the cleaned name found nothing
        if not results:
            stripped = _hltb_strip_punctuation(cleaned)
            if stripped != cleaned:
                results = HowLongToBeat(0.0).search(stripped, similarity_case_sensitive=False)
        if not results:
            return []

        def _hours_to_minutes(val):
            if val is None or val < 0:
                return None
            return int(round(val * 60))

        out = []
        for r in sorted(results, key=lambda x: x.similarity, reverse=True)[:8]:
            out.append({
                'hltb_id':            r.game_id,
                'hltb_matched_name':  r.game_name,
                'hltb_match_score':   int(round(r.similarity * 100)),
                'hltb_main':          _hours_to_minutes(r.main_story),
                'hltb_extras':        _hours_to_minutes(r.main_extra),
                'hltb_completionist': _hours_to_minutes(r.completionist),
            })
        return out
    except Exception as e:
        log.warning(f"[hltb] search failed for '{name}': {e}")
        return []


def _hltb_worker(normal_q, priority_q, cancel_event, today, threshold, progress_cb):
    while True:
        if cancel_event and cancel_event.is_set():
            return

        appid = _next(priority_q, normal_q)
        if appid is None:
            return

        db  = get_db()
        row = db.execute("SELECT name, hltb_fetched FROM games WHERE appid=?", (appid,)).fetchone()
        db.close()
        if not row or row['hltb_fetched'] not in ('0', 'no_match', None):
            continue

        try:
            info = fetch_hltb_data(row['name'], threshold=threshold)
            if info:
                update_game_data(appid, **info)
            else:
                update_game_data(appid, hltb_fetched='no_match', hltb_id=None,
                                 hltb_main=None, hltb_extras=None,
                                 hltb_completionist=None, hltb_match_score=None)
            if progress_cb:
                progress_cb('hltb', appid, None)
        except Exception as e:
            log.error(f"[hltb] Error for {appid}: {e}")
        time.sleep(0.5)


# ── Main populate entry point ─────────────────────────────────────────────────

def add_new(cancel_event=None, progress_cb=None):
    account = get_active_account()
    if not account:
        return {"status": "error", "message": "No account configured"}

    api_key  = account.get('api_key')
    steam_id = account.get('steam_id')

    # ── Phase 1a: fetch game list ─────────────────────────────────────────────
    if api_key:
        log.info("Fetching games via Steam API.")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        url = (
            f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
            f"?key={api_key}&steamid={steam_id}&format=json"
            f"&include_appinfo=true&include_played_free_games=1&skip_unvetted_apps=false"
        )
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 403:
                return {"status": "error", "message": "Steam API: 403 Forbidden. Your API Key may be invalid."}
            response.raise_for_status()
            data      = response.json()
            raw_games = data.get('response', {}).get('games', [])
            if not raw_games:
                return {"status": "error", "message": "No games returned. Is your Steam Profile set to Public?"}
            games = [{
                'appid':            g['appid'],
                'name':             g.get('name', ''),
                'playtime_forever': g.get('playtime_forever', 0),
                'last_played':      g.get('rtime_last_played') or None,
                'icon_hash':        g.get('img_icon_url', ''),
            } for g in raw_games]
        except requests.exceptions.JSONDecodeError:
            return {"status": "error", "message": "Steam sent invalid data. Try again in a few minutes."}
        except Exception as e:
            return {"status": "error", "message": f"Connection Error: {str(e)}"}
    else:
        log.info("No API key — reading library from localconfig.vdf.")
        local_games = fetch_local_library(steam_id)
        if not local_games:
            return {"status": "error", "message": (
                "Could not read library from local Steam files. Make sure Steam is installed "
                "and has been launched at least once."
            )}
        acf_names  = get_acf_names()
        appinfo_db = parse_appinfo()
        games = [{
            'appid':            g['appid'],
            'name':             acf_names.get(g['appid']) or appinfo_db.get(g['appid'], {}).get('name', ''),
            'playtime_forever': g['playtime_forever'],
            'last_played':      g['last_played'],
            'icon_hash':        '',
        } for g in local_games]

    if api_key:
        appinfo_db = parse_appinfo()

    # ── Phase 1b: filter to new games ─────────────────────────────────────────
    db              = get_db()
    existing_ids    = {row['appid'] for row in db.execute("SELECT appid FROM games").fetchall()}
    blacklisted_ids = {row['appid'] for row in db.execute("SELECT appid FROM blacklist").fetchall()}
    db.close()

    installed_ids = get_locally_installed_appids()
    from datetime import timezone as _tz
    today         = int(datetime.now(_tz.utc).timestamp())

    new_games = []
    for g in reversed(games):
        appid = g['appid']
        if appid in existing_ids or appid in blacklisted_ids:
            continue
        if appinfo_db.get(appid, {}).get('type', 'game').lower() != 'game':
            continue
        playtime = g['playtime_forever']
        new_games.append({
            'appid':            appid,
            'name':             g['name'],
            'playtime_forever': playtime,
            'last_played':      g['last_played'],
            'icon_hash':        g.get('icon_hash', ''),
            'completion_status': 'Unfinished' if playtime > 0 else 'Never Played',
            'installed':        1 if appid in installed_ids else 0,
        })

    total = len(new_games)
    if total == 0:
        return {"status": "success", "added": 0}

    # ── Phase 1c: batch insert placeholders ───────────────────────────────────
    batch_insert_placeholder_games(new_games, today)
    log.info(f"Inserted {total} placeholder game(s).")
    for g in new_games:
        if progress_cb:
            progress_cb('placeholder', g, total)

    if cancel_event and cancel_event.is_set():
        return {"status": "cancelled", "added": 0}

    # ── Phases 2/3/4: concurrent worker pools ────────────────────────────────
    appid_list    = [g['appid'] for g in new_games]
    icon_hash_map = {g['appid']: g.get('icon_hash', '') for g in new_games}

    # Two queues per pool: priority (for viewport-visible games) and normal
    art_nq,      art_pq      = queue.Queue(), queue.Queue()
    meta_nq,     meta_pq     = queue.Queue(), queue.Queue()
    cheevo_nq,   cheevo_pq   = queue.Queue(), queue.Queue()
    protondb_nq, protondb_pq = queue.Queue(), queue.Queue()
    hltb_nq,     hltb_pq     = queue.Queue(), queue.Queue()

    for appid in appid_list:
        art_nq.put(appid)
        meta_nq.put(appid)
        if api_key:
            cheevo_nq.put(appid)
        protondb_nq.put(appid)
        hltb_nq.put(appid)

    art_backoff    = _PoolBackoff('art')
    meta_backoff   = _PoolBackoff('meta')
    cheevo_backoff = _PoolBackoff('cheevo')
    # Expose priority queues so /api/populate-priority can feed them
    if progress_cb:
        progress_cb('workers_starting', {
            'art_pq':      art_pq,
            'meta_pq':     meta_pq,
            'cheevo_pq':   cheevo_pq,
            'protondb_pq': protondb_pq,
            'hltb_pq':     hltb_pq,
        }, total)

    ART_WORKERS      = 5
    META_WORKERS     = 1
    CHEEVO_WORKERS   = 2
    PROTONDB_WORKERS = 2
    HLTB_WORKERS     = 2

    # ── Phase 1d: BLAEO pre-scrape (concurrent with art + meta workers) ───────
    # Only worthwhile when there are enough games needing cheevo data.
    # Runs after placeholder insert so new games exist in the DB.
    # Cheevo workers are started after BLAEO finishes so they skip covered games.
    def _run_blaeo():
        try:
            db = get_db()
            needs_cheevos = db.execute(
                "SELECT COUNT(*) FROM games WHERE cheevos_fetched = '0' OR cheevos_fetched IS NULL"
            ).fetchone()[0]
            db.close()
            if needs_cheevos < 50:
                log.info(f"[populate] BLAEO pre-scrape skipped ({needs_cheevos} games need cheevos, threshold 50).")
                return
            blaeo_result = scrape_blaeo_games(today=today)
            if blaeo_result.get('status') == 'success':
                log.info(f"[populate] BLAEO pre-scrape updated {blaeo_result['updated']} game(s).")
            else:
                log.info(f"[populate] BLAEO pre-scrape skipped: {blaeo_result.get('message', 'no account')}")
        except Exception as e:
            log.warning(f"[populate] BLAEO pre-scrape failed (non-fatal): {e}")

    from config import load_state
    hltb_threshold = load_state().get('hltb_match_threshold', 99)

    n_workers = ART_WORKERS + META_WORKERS + (CHEEVO_WORKERS if api_key else 0) + PROTONDB_WORKERS + HLTB_WORKERS
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        # Art and meta start immediately
        futures = []
        for _ in range(ART_WORKERS):
            futures.append(executor.submit(
                _art_worker, art_nq, art_pq, cancel_event, icon_hash_map, today, progress_cb
            ))
        for _ in range(META_WORKERS):
            futures.append(executor.submit(
                _meta_worker, meta_nq, meta_pq, meta_backoff, cancel_event, total, today, progress_cb
            ))
        for _ in range(PROTONDB_WORKERS):
            futures.append(executor.submit(
                _protondb_worker, protondb_nq, protondb_pq, cancel_event, today, progress_cb
            ))
        for _ in range(HLTB_WORKERS):
            futures.append(executor.submit(
                _hltb_worker, hltb_nq, hltb_pq, cancel_event, today, hltb_threshold, progress_cb
            ))

        # BLAEO runs concurrently; cheevo workers start after it finishes
        if api_key:
            blaeo_thread = threading.Thread(target=_run_blaeo, daemon=True)
            blaeo_thread.start()
            blaeo_thread.join()
            for _ in range(CHEEVO_WORKERS):
                futures.append(executor.submit(
                    _cheevo_worker, cheevo_nq, cheevo_pq, cheevo_backoff, cancel_event, today, progress_cb
                ))

        futures_wait(futures)

    # ── Check if all rate-limitable pools aborted ─────────────────────────────
    meta_aborted   = meta_backoff.aborted
    cheevo_aborted = cheevo_backoff.aborted if api_key else True
    if meta_aborted and cheevo_aborted:
        if progress_cb:
            progress_cb('rate_limit_abort', None, total)

    if cancel_event and cancel_event.is_set():
        return {"status": "cancelled", "added": total}

    return {"status": "success", "added": total}



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
        return {
            'name': game.get('name'),
            'playtime_forever': game.get('playtime_forever', 0),
            'last_played': last_played_unix or None,
        }
    except Exception as e:
        log.error(f"Error fetching player data for {appid}: {e}")
        return None

# Scrape Storefront API (Devs, Pubs, Release Date)
def fetch_store_data(appid, session=None):
    """
    Fetches rich metadata from the Steam Store API for a single appid.
    Returns a dictionary of data or None if the request fails.
    Pass a requests.Session for connection reuse across multiple calls.
    """
    _http = session or requests
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english"

    try:
        response = _http.get(url, timeout=15)
        if response.status_code == 429:
            raise RateLimitedError()
        response.raise_for_status()
        json_data = response.json()

        # The API returns data keyed by the appid string
        if not json_data or not json_data.get(str(appid), {}).get('success'):
            log.info(f"Could not find store data for {appid}")
            return None

        data = json_data[str(appid)]['data']
        from datetime import timezone as _tz
        raw_date = data.get('release_date', {}).get('date', '')
        date_value = None
        for fmt in ("%b %d, %Y", "%d %b, %Y"):
            try:
                date_value = int(datetime.strptime(raw_date, fmt).replace(tzinfo=_tz.utc).timestamp())
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

    except RateLimitedError:
        raise
    except Exception as e:
        log.error(f"Error fetching store data for {appid}")
        return None


# Scrape Reviews API (Percentage, Description)
def fetch_review_data(appid, session=None):
    _http = session or requests
    url = f"https://store.steampowered.com/appreviews/{appid}?json=1&language=all&num_per_page=0&purchase_type=all"

    try:
        response = _http.get(url, timeout=20)
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
            else:
                p = percent / 100.0
                weighted = round((p - (p - 0.5) * (2 ** (-math.log10(total + 1)))) * 100)

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

    except RateLimitedError:
        raise
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

    except RateLimitedError:
        raise
    except Exception as e:
        log.error(f"Error fetching achievement data for AppID: {appid}")
        return None

def fetch_tag_data(appid, session=None):
    """
    Scrapes the top user-defined tags from the Steam store page.
    Returns a dictionary containing a comma-separated string of tags.
    """
    _http = session or requests
    url = f"https://store.steampowered.com/app/{appid}/?l=english"
    # We include a birthtime cookie to bypass the mature content age-gate
    headers = {
        'Cookie': 'birthtime=283993201; lastagecheckage=1-0-1979',
        'User-Agent': 'Mozilla/5.0'
    }

    try:
        response = _http.get(url, headers=headers, timeout=10)
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
    except RateLimitedError:
        raise
    except Exception as e:
        log.error(f"Error scraping tags for {appid}: {e}")

    return None

def scrape_blaeo_games(today=None):
    import requests as req
    if today is None:
        today = datetime.now().strftime('%Y-%m-%d')
    config = load_config()
    account = get_active_account()
    blaeo_url = config.get('blaeo_url')
    if not blaeo_url:
        steam_id = (account or {}).get('steam_id')
        blaeo_url = f"https://www.backlog-assassins.net/users/+{steam_id}/games"

    base_url = blaeo_url.rstrip('/')

    status_map = {
        "Never-played": "Never Played",
        "Wont-play": "Won't Play",
        "Unfinished": "Unfinished",
        "Beaten": "Beaten",
        "Completed": "Completed"
    }

    try:
        session = req.Session()
        session.headers['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'

        all_rows = []
        url = base_url
        page = 1

        while url:
            log.info(f"Fetching BLAEO page {page}: {url}")
            r = session.get(url, timeout=15)
            if r.status_code == 404:
                raise RuntimeError("BLAEO profile not found. You may not have a BLAEO account.")
            if r.status_code != 200:
                raise RuntimeError(f"BLAEO may be down (HTTP {r.status_code}).")

            soup = BeautifulSoup(r.text, 'html.parser')

            if page == 1 and not soup.select_one("table.game-table"):
                raise RuntimeError("No BLAEO game list found. You may not have a BLAEO account.")

            rows = soup.select("table.game-table tbody tr.game")
            if not rows:
                break

            all_rows.extend(rows)
            last_cursor = rows[-1].get('data-item')
            if not last_cursor:
                break

            url = f"{base_url}?start_at={last_cursor}"
            page += 1
            time.sleep(0.5)

        log.info(f"Fetched {len(all_rows)} games from BLAEO across {page} page(s)")

        db = get_db()
        cursor = db.cursor()
        updated_count = 0

        for row in all_rows:
            try:
                steam_link = row.select_one("a.steam")
                if not steam_link:
                    continue

                href = steam_link.get('href', '')
                appid_match = re.search(r'/app/(\d+)', href)
                if not appid_match:
                    continue
                appid = int(appid_match.group(1))

                # Extract status from class (e.g., class="game game-never-played")
                classes = row.get('class', [])
                raw_status = "Unknown"
                for c in classes:
                    if c.startswith("game-") and c != "game":
                        raw_status = c.replace("game-", "").capitalize()

                clean_status = status_map.get(raw_status, raw_status)

                # Extract Group Tags
                tag_elements = row.select("a.list-tag")
                blaeo_groups = [tag.get_text(strip=True) for tag in tag_elements]

                # Extract achievement counts from "(X of Y)" span; skip if no achievements
                unlocked_ach = None
                total_ach = None
                ach_td = row.select_one("td.achievements")
                if ach_td and ach_td.get('data-value', '-2') != '-2':
                    spans = ach_td.select('span')
                    if len(spans) >= 2:
                        ach_match = re.search(r'\((\d+) of (\d+)\)', spans[1].get_text())
                        if ach_match:
                            unlocked_ach = int(ach_match.group(1))
                            total_ach    = int(ach_match.group(2))

                # Match against the DB
                cursor.execute("SELECT groups FROM games WHERE appid = ?", (appid,))
                db_row = cursor.fetchone()

                if db_row:
                    existing_groups_str = db_row['groups'] if db_row['groups'] else ""
                    existing_groups_set = set(g.strip() for g in existing_groups_str.split(',') if g.strip())

                    updated_groups_set = existing_groups_set.union(set(blaeo_groups))
                    new_groups_str = ",".join(sorted(updated_groups_set))

                    if unlocked_ach is not None:
                        cursor.execute(
                            "UPDATE games SET completion_status = ?, groups = ?, unlocked_achievements = ?, total_achievements = ?, cheevos_fetched = ? WHERE appid = ?",
                            (clean_status, new_groups_str, unlocked_ach, total_ach, today, appid)
                        )
                    else:
                        cursor.execute(
                            "UPDATE games SET completion_status = ?, groups = ? WHERE appid = ?",
                            (clean_status, new_groups_str, appid)
                        )
                    updated_count += 1
                else:
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

def sync_recent_playtime():
    """
    On startup: update playtime_forever + last_played for all played games by
    reading localconfig.vdf directly. No API key required. Runs in a background
    thread — safe to call without blocking startup.

    For games where playtime_forever increased, also fetches achievements (if an
    API key is configured) and updates completion_status:
      - Never Played + playtime > 0  → Unfinished
      - 100% achievements unlocked   → Completed (any status)
      - Won't Play                   → only changed if 100% achievements
      - Beaten                       → never downgraded; upgraded to Completed if 100%
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
                'last_played':      g['last_played'],
            }
            for g in fetch_local_library(steam_id)
        ]

        if not recent:
            log.info("sync_recent_playtime: no games to sync.")
            return

        db = get_db()
        existing = {
            row[0]: {'playtime_forever': row[1], 'completion_status': row[2]}
            for row in db.execute("SELECT appid, playtime_forever, completion_status FROM games").fetchall()
        }

        updated = 0
        for g in recent:
            appid = g['appid']
            if appid not in existing:
                continue

            old_playtime = existing[appid]['playtime_forever'] or 0
            new_playtime = g['playtime_forever']
            current_status = existing[appid]['completion_status']
            playtime_changed = new_playtime != old_playtime

            if g['last_played']:
                db.execute(
                    "UPDATE games SET playtime_forever = ?, last_played = ? WHERE appid = ?",
                    (new_playtime, g['last_played'], appid)
                )
            else:
                db.execute(
                    "UPDATE games SET playtime_forever = ? WHERE appid = ?",
                    (new_playtime, appid)
                )
            updated += 1

            if not playtime_changed:
                continue

            # Fetch achievements for games with new playtime (requires API key)
            time.sleep(0.5)
            cheevo = fetch_cheevo_data(appid)
            if cheevo:
                db.execute(
                    "UPDATE games SET unlocked_achievements = ?, total_achievements = ? WHERE appid = ?",
                    (cheevo.get('unlocked_achievements', 0), cheevo.get('total_achievements', 0), appid)
                )

            hundred_pct = (
                cheevo
                and cheevo.get('total_achievements', 0) > 0
                and cheevo.get('unlocked_achievements', 0) == cheevo.get('total_achievements', 0)
            )

            if hundred_pct:
                new_status = 'Completed'
            elif current_status == 'Never Played' and new_playtime > 0:
                new_status = 'Unfinished'
            else:
                new_status = None  # Beaten / Won't Play (without 100%) / Unfinished left alone

            if new_status and new_status != current_status:
                db.execute(
                    "UPDATE games SET completion_status = ? WHERE appid = ?",
                    (new_status, appid)
                )

        # Sweep: any game whose stored achievement counts already show 100%
        # should be Completed, regardless of how the counts got there (e.g.
        # BLAEO sync set cheevos_fetched and skipped the cheevo worker, or
        # the cheevo worker ran but the status wasn't updated).
        result = db.execute(
            "UPDATE games SET completion_status = 'Completed'"
            " WHERE total_achievements > 0"
            "   AND unlocked_achievements = total_achievements"
            "   AND completion_status != 'Completed'"
        )
        if result.rowcount:
            log.info(f"sync_recent_playtime: promoted {result.rowcount} game(s) to Completed via achievement sweep.")

        db.commit()
        db.close()
        log.info(f"sync_recent_playtime: updated {updated} games.")

    except Exception as e:
        logging.getLogger(__name__).warning(f"sync_recent_playtime failed: {e}")


# ── Bulk concurrent operations ────────────────────────────────────────────────

def bulk_rescrape_games(appids, cancel_event, progress_cb):
    """
    Concurrent metadata re-scrape for a list of appids.
    Uses _PoolBackoff for rate limiting; respects cancel_event.
    3 concurrent workers with 1s inter-game delay.
    """
    backoff  = _PoolBackoff('bulk_rescrape')
    today    = datetime.now().strftime('%Y-%m-%d')
    _account = get_active_account() or {}
    has_key  = bool(_account.get('api_key'))

    q = queue.Queue()
    for appid in appids:
        q.put(appid)
    total = len(appids)

    counts = {'done': 0, 'failed': 0}
    lock   = threading.Lock()

    def worker():
        while True:
            if cancel_event and cancel_event.is_set():
                return
            if not backoff.wait_ready(cancel_event):
                return
            try:
                appid = q.get_nowait()
            except queue.Empty:
                return
            try:
                store_data  = fetch_store_data(appid)  or {}
                store_data.pop('name', None)
                store_data.pop('type', None)
                review_data = fetch_review_data(appid) or {}
                tag_data    = fetch_tag_data(appid)    or {}
                cheevo_data = fetch_cheevo_data(appid) or {} if has_key else {}

                game_data = {}
                game_data.update(store_data)
                game_data.update(review_data)
                game_data.update(tag_data)
                game_data.update(cheevo_data)
                if store_data or review_data or tag_data:
                    game_data['meta_fetched'] = today
                if cheevo_data:
                    game_data['cheevos_fetched'] = today

                if game_data:
                    update_game_data(appid, **game_data)
                    with lock:
                        counts['done'] += 1
                else:
                    with lock:
                        counts['failed'] += 1

                if progress_cb:
                    progress_cb('done', appid, total)
                time.sleep(0.5)

            except RateLimitedError:
                q.put(appid)   # re-queue for retry after backoff
                if progress_cb:
                    attempt = backoff._attempt + 1
                    delay   = BACKOFF_DELAYS[min(backoff._attempt, len(BACKOFF_DELAYS) - 1)]
                    progress_cb('rate_limit', {'attempt': attempt, 'delay': delay}, total)
                if not backoff.on_rate_limited(cancel_event):
                    with lock:
                        counts['failed'] += 1
                    return
            except Exception as e:
                log.error(f"[bulk_rescrape] Error for {appid}: {e}")
                with lock:
                    counts['failed'] += 1
                if progress_cb:
                    progress_cb('failed', appid, total)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures_wait([pool.submit(worker) for _ in range(3)])

    counts['aborted'] = backoff.aborted
    return counts


def bulk_art_scrape_games(appids, types, source, cancel_event, progress_cb):
    """
    Concurrent artwork scrape for a list of appids.
    3 concurrent workers with 0.8s inter-game delay.
    """
    today = datetime.now().strftime('%Y-%m-%d')

    if appids:
        db   = get_db()
        rows = db.execute(
            f"SELECT appid, icon_hash FROM games WHERE appid IN ({','.join('?' * len(appids))})",
            appids
        ).fetchall()
        db.close()
        icon_hash_map = {r['appid']: r['icon_hash'] or '' for r in rows}
    else:
        icon_hash_map = {}

    q = queue.Queue()
    for appid in appids:
        q.put(appid)
    total = len(appids)

    counts = {'done': 0, 'failed': 0}
    lock   = threading.Lock()

    def worker():
        while True:
            if cancel_event and cancel_event.is_set():
                return
            try:
                appid = q.get_nowait()
            except queue.Empty:
                return
            try:
                updates = {}
                assets  = _get_steam_assets(appid) if source != 'sgdb' else {}
                if 'vertical' in types:
                    updates['vertical_art_source']   = download_vertical(appid, assets=assets, source=source)
                if 'horizontal' in types:
                    updates['horizontal_art_source'] = download_horizontal(appid, assets=assets, source=source)
                if 'icon' in types:
                    updates['icon_source']            = download_icon(appid, icon_hash_map.get(appid, ''), source=source)
                updates['art_fetched'] = today
                update_game_data(appid, **updates)

                with lock:
                    counts['done'] += 1
                if progress_cb:
                    progress_cb('done', appid, total)
                time.sleep(0.8)

            except Exception as e:
                log.error(f"[bulk_art_scrape] Error for {appid}: {e}")
                with lock:
                    counts['failed'] += 1
                if progress_cb:
                    progress_cb('failed', appid, total)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures_wait([pool.submit(worker) for _ in range(3)])

    return counts


def bulk_protondb_scrape_games(appids, cancel_event, progress_cb):
    """
    Fetch ProtonDB tier + confidence for a list of appids via per-game API.
    2 concurrent workers, no artificial delay (ProtonDB has no documented rate limit).
    """
    today = datetime.now().strftime('%Y-%m-%d')

    q = queue.Queue()
    for appid in appids:
        q.put(appid)
    total = len(appids)

    counts = {'done': 0, 'failed': 0}
    lock   = threading.Lock()

    def worker():
        session = requests.Session()
        session.headers['User-Agent'] = 'Mozilla/5.0'
        while True:
            if cancel_event and cancel_event.is_set():
                return
            try:
                appid = q.get_nowait()
            except queue.Empty:
                return
            try:
                info = fetch_protondb_data(appid, session=session)
                game_data = {'protondb_fetched': today}
                if info:
                    game_data.update(info)
                else:
                    game_data['protondb_tier']       = None
                    game_data['protondb_confidence'] = None
                update_game_data(appid, **game_data)

                with lock:
                    counts['done'] += 1
                if progress_cb:
                    progress_cb('done', appid, total)
            except Exception as e:
                log.error(f"[bulk_protondb] Error for {appid}: {e}")
                with lock:
                    counts['failed'] += 1
                if progress_cb:
                    progress_cb('failed', appid, total)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures_wait([pool.submit(worker) for _ in range(2)])

    return counts


_startup_hltb_cancel = threading.Event()


def sync_hltb_unfetched():
    """
    On startup: silently fetch HLTB data for all games with hltb_fetched = '0' or NULL.
    Runs after sync_recent_playtime() in the same daemon thread. Logs only, no UI progress.
    Skips no_match games — those require manual retry via the HLTB tool.
    """
    from config import load_state
    state     = load_state()
    threshold = state.get('hltb_match_threshold', 99)

    db    = get_db()
    rows  = db.execute(
        "SELECT appid, name FROM games WHERE hltb_fetched = '0' OR hltb_fetched IS NULL"
    ).fetchall()
    db.close()

    if not rows:
        log.info("sync_hltb_unfetched: nothing to fetch.")
        return

    total = len(rows)
    log.info(f"sync_hltb_unfetched: fetching HLTB data for {total} game(s).")

    q = queue.Queue()
    for row in rows:
        q.put((row['appid'], row['name']))

    counts = {'done': 0, 'failed': 0}
    lock   = threading.Lock()

    def worker():
        while True:
            if _startup_hltb_cancel.is_set():
                return
            try:
                appid, name = q.get_nowait()
            except queue.Empty:
                return
            try:
                info = fetch_hltb_data(name, threshold=threshold)
                if info:
                    update_game_data(appid, **info)
                else:
                    update_game_data(appid, hltb_fetched='no_match', hltb_id=None,
                                     hltb_matched_name=None, hltb_match_score=None,
                                     hltb_main=None, hltb_extras=None,
                                     hltb_completionist=None)
                with lock:
                    counts['done'] += 1
            except Exception as e:
                log.error(f"[sync_hltb_unfetched] Error for appid {appid}: {e}")
                with lock:
                    counts['failed'] += 1
            time.sleep(0.5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures_wait([pool.submit(worker) for _ in range(2)])

    log.info(f"sync_hltb_unfetched: done={counts['done']} failed={counts['failed']} / {total}")


def bulk_hltb_scrape_games(appids, cancel_event, progress_cb):
    """
    Fetch HLTB data for a list of appids by game name.
    2 concurrent workers. Uses the match threshold from state.json.
    """
    from config import load_state
    state     = load_state()
    threshold = state.get('hltb_match_threshold', 99)

    db    = get_db()
    names = {row['appid']: row['name'] for row in db.execute(
        f"SELECT appid, name FROM games WHERE appid IN ({','.join('?'*len(appids))})",
        appids
    ).fetchall()}
    db.close()

    q = queue.Queue()
    for appid in appids:
        q.put(appid)
    total = len(appids)

    counts = {'done': 0, 'failed': 0}
    lock   = threading.Lock()

    def worker():
        while True:
            if cancel_event and cancel_event.is_set():
                return
            try:
                appid = q.get_nowait()
            except queue.Empty:
                return
            name = names.get(appid)
            if not name:
                with lock:
                    counts['failed'] += 1
                if progress_cb:
                    progress_cb('failed', appid, total)
                continue
            try:
                info = fetch_hltb_data(name, threshold=threshold)
                if info:
                    update_game_data(appid, **info)
                else:
                    update_game_data(appid, hltb_fetched='no_match', hltb_id=None,
                                     hltb_matched_name=None, hltb_match_score=None,
                                     hltb_main=None, hltb_extras=None,
                                     hltb_completionist=None)
                with lock:
                    counts['done'] += 1
                if progress_cb:
                    progress_cb('done', appid, total)
            except Exception as e:
                log.error(f"[bulk_hltb] Error for {appid}: {e}")
                with lock:
                    counts['failed'] += 1
                if progress_cb:
                    progress_cb('failed', appid, total)
            time.sleep(0.5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures_wait([pool.submit(worker) for _ in range(2)])

    return counts
