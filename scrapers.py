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
from flask import Blueprint, jsonify, request
from images import download_vertical, download_horizontal, download_icon, _get_steam_assets, _sgdb_search_game_id, VERTICAL_DIR, HORIZONTAL_DIR, ICONS_DIR
from datetime import datetime, timezone
from config import load_config, get_active_account
from database import batch_insert_placeholder_games, update_game_data, get_db, add_to_blacklist
from utils import get_locally_installed_appids, fetch_local_library, get_acf_names, parse_appinfo

blaeo_bp = Blueprint('blaeo', __name__)

# ── BLAEO background sync state ───────────────────────────────────────────────
_blaeo_sync_state = {'running': False, 'done': False, 'error': None}
_blaeo_sync_lock  = threading.Lock()


class RateLimitedError(Exception):
    """Raised when Steam returns HTTP 429. retry_after (seconds, float) is set
    when the response carried a Retry-After header -- callers prefer this over
    the fixed BACKOFF_DELAYS guess when present."""
    def __init__(self, retry_after=None):
        super().__init__('Rate limited')
        self.retry_after = retry_after


def _parse_retry_after(resp):
    """Parse a 429 response's Retry-After header into seconds (float), or None
    if the header is absent or unparseable. Handles both forms RFC 7231 allows:
    a plain integer, or an HTTP-date."""
    val = resp.headers.get('Retry-After')
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


# Backoff delays in seconds: 15s → 1m → 5m → 1h+15s. Used when a 429 doesn't
# carry a Retry-After header; when it does, that value is honored instead
# (capped at the largest delay here so a bogus/huge value can't stall a pool
# indefinitely).
BACKOFF_DELAYS = [15, 60, 300, 3615]


def _weighted_score(percent, count):
    """Confidence-interval weighted review score: pulls low-count scores toward 50."""
    if count == 0:
        return 0
    p = percent / 100.0
    return round((p - (p - 0.5) * (2 ** (-math.log10(count + 1)))) * 100)


def _hours_to_minutes(val):
    if val is None or val < 0:
        return None
    return int(round(val * 60))


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

    def on_rate_limited(self, cancel_event=None, retry_after=None):
        """
        Called by the worker that received the 429. retry_after (seconds), if
        given, comes from the response's Retry-After header and is preferred
        over the fixed BACKOFF_DELAYS guess for this wait -- capped at the
        largest configured delay so a bogus/huge value can't stall the pool.
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
            delay = min(retry_after, BACKOFF_DELAYS[-1]) if retry_after else BACKOFF_DELAYS[self._attempt]
            self._attempt += 1
            self._gate.clear()

        log.warning(
            f"[{self.name}] Rate limited. Waiting {delay:.0f}s "
            f"(attempt {self._attempt}/{len(BACKOFF_DELAYS)}"
            f"{', server-requested' if retry_after else ''})..."
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
        v_exists, h_exists, i_exists = os.path.exists(v_path), os.path.exists(h_path), os.path.exists(i_path)
        if v_exists or h_exists or i_exists:
            src_updates = {}
            if v_exists and not (row and row['vertical_art_source']):
                src_updates['vertical_art_source'] = 'capsule'
            if h_exists and not (row and row['horizontal_art_source']):
                src_updates['horizontal_art_source'] = 'header'
            if i_exists and not (row and row['icon_source']):
                src_updates['icon_source'] = 'steam' if icon_hash_map.get(appid) else 'sgdb_icon'
            update_game_data(appid, art_fetched=today, **src_updates)
            if progress_cb:
                progress_cb('art', appid, None)
            continue
        try:
            if appid < 0:
                db2 = get_db()
                game_row = db2.execute("SELECT name FROM games WHERE appid=?", (appid,)).fetchone()
                db2.close()
                name    = game_row['name'] if game_row else ''
                sgdb_id = _sgdb_search_game_id(name) if name else None
                v_src   = download_vertical(appid, sgdb_id=sgdb_id, game_name=name)
                h_src   = download_horizontal(appid, sgdb_id=sgdb_id, game_name=name)
                i_src   = download_icon(appid, '', sgdb_id=sgdb_id, game_name=name)
            else:
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


def _meta_worker(normal_q, priority_q, backoff, cancel_event, total, today, progress_cb, batch_appids=None):
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

    while True:
        if cancel_event and cancel_event.is_set():
            return
        if not backoff.wait_ready(cancel_event):
            return

        appid = _next(priority_q, normal_q)
        if appid is None:
            return

        # Priority queue may receive arbitrary visible appids from /api/populate-priority;
        # skip anything outside the current batch to avoid processing unrelated games.
        if batch_appids is not None and appid not in batch_appids:
            continue

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
                store_info.pop('type', None)

            game_data = {'meta_fetched': today}

            if store_info:
                store_name = store_info.pop('name', '')
                # Always prefer the store name — GetOwnedGames returns internal names
                # (e.g. "Sokpop S09: Grey Scout") that differ from the display name.
                new_name = store_name or name or f"AppID {appid}"
                db = get_db()
                db.execute("UPDATE games SET name=? WHERE appid=?", (new_name, appid))
                db.commit()
                db.close()
                game_data['name_from_store'] = 1
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

        except RateLimitedError as e:
            if progress_cb:
                attempt = backoff._attempt + 1
                delay   = min(e.retry_after, BACKOFF_DELAYS[-1]) if e.retry_after else BACKOFF_DELAYS[min(backoff._attempt, len(BACKOFF_DELAYS) - 1)]
                progress_cb('rate_limit_hit', {'pool': 'meta', 'attempt': attempt, 'delay': delay}, total)
            priority_q.put(appid)   # re-queue for retry after backoff
            if not backoff.on_rate_limited(cancel_event, retry_after=e.retry_after):
                return
        except Exception as e:
            log.error(f"[meta] Error for {appid}: {e}")
            time.sleep(0.1)


def _cheevo_worker(normal_q, priority_q, backoff, cancel_event, today, progress_cb, batch_appids=None):
    while True:
        if cancel_event and cancel_event.is_set():
            return
        if not backoff.wait_ready(cancel_event):
            return

        appid = _next(priority_q, normal_q)
        if appid is None:
            return

        if batch_appids is not None and appid not in batch_appids:
            continue

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
        except RateLimitedError as e:
            if progress_cb:
                attempt = backoff._attempt + 1
                delay   = min(e.retry_after, BACKOFF_DELAYS[-1]) if e.retry_after else BACKOFF_DELAYS[min(backoff._attempt, len(BACKOFF_DELAYS) - 1)]
                progress_cb('rate_limit_hit', {'pool': 'cheevo', 'attempt': attempt, 'delay': delay}, None)
            priority_q.put(appid)
            if not backoff.on_rate_limited(cancel_event, retry_after=e.retry_after):
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

_STEAM_HLTB_MAP = None  # {steam_appid_str: hltb_id_int}

def _load_steam_hltb_map():
    """
    Load and cache the Steam→HLTB ID mapping from zpangwin/sg-data on GitHub.
    Cached locally for 7 days; refreshed on startup.
    """
    global _STEAM_HLTB_MAP
    if _STEAM_HLTB_MAP is not None:
        return _STEAM_HLTB_MAP

    from config import BASE_DIR
    cache_path = os.path.join(BASE_DIR, 'steam_hltb_map.json')
    url = 'https://raw.githubusercontent.com/zpangwin/sg-data/master/steam-to-hltb-mappings/steam-to-hltb-map.min.json'

    try:
        age = time.time() - os.path.getmtime(cache_path) if os.path.exists(cache_path) else float('inf')
        if age > 7 * 86400:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(resp.text)
            log.info('[hltb] steam_hltb_map refreshed from GitHub')
        with open(cache_path, 'r', encoding='utf-8') as f:
            _STEAM_HLTB_MAP = json.load(f)
    except Exception as e:
        log.warning(f'[hltb] could not load steam_hltb_map: {e}')
        _STEAM_HLTB_MAP = {}

    return _STEAM_HLTB_MAP


def _hltb_clean_name(name):
    """
    Normalize a Steam game title for HLTB search queries.
    Strips symbols and all punctuation so differences like trailing periods,
    semicolons, or colon-vs-dash separators don't prevent a match.
    """
    name = name[:500]
    name = re.sub(r'[®™©]', '', name)            # trademark/IP symbols
    name = name.rstrip()                                   # trailing year, e.g. "(2010)"
    if name.endswith(')') and len(name) >= 6 and name[-6] == '(' and name[-5:-1].isdigit():
        name = name[:-6].rstrip()
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
            stripped = _hltb_strip_edition(cleaned)
            if stripped != cleaned:
                results = HowLongToBeat(0.0).search(stripped, similarity_case_sensitive=False)
        if not results:
            return []

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
    _populate_idle.clear()
    try:
        return _add_new(cancel_event=cancel_event, progress_cb=progress_cb)
    finally:
        _populate_idle.set()


def fetch_owned_appids():
    """Fetch the current set of Steam appids owned by the active account, via
    the same GetOwnedGames endpoint _add_new() uses for populate. Returns
    {"status": "success", "appids": set(...)} or {"status": "error", "message": ...}
    -- never raises."""
    account = get_active_account()
    if not account or not account.get('api_key'):
        return {"status": "error", "message": "No Steam API key configured."}
    api_key, steam_id = account['api_key'], account.get('steam_id')
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    url = (
        f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
        f"?key={api_key}&steamid={steam_id}&format=json"
        f"&include_appinfo=false&include_played_free_games=1&skip_unvetted_apps=false"
    )
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 403:
            return {"status": "error", "message": "Steam API: 403 Forbidden. Your API Key may be invalid."}
        if response.status_code == 429:
            raise RateLimitedError(_parse_retry_after(response))
        response.raise_for_status()
        data = response.json()
        raw_games = data.get('response', {}).get('games', [])
        if not raw_games:
            return {"status": "error", "message": "No games returned. Is your Steam Profile set to Public?"}
        return {"status": "success", "appids": {g['appid'] for g in raw_games}}
    except RateLimitedError as e:
        wait = f" Try again in {int(e.retry_after)}s." if e.retry_after else ""
        return {"status": "error", "message": f"Steam API rate-limited.{wait}"}
    except requests.exceptions.JSONDecodeError:
        return {"status": "error", "message": "Steam sent invalid data. Try again in a few minutes."}
    except Exception as e:
        return {"status": "error", "message": f"Connection Error: {str(e)}"}


def _add_new(cancel_event=None, progress_cb=None):
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
    today_ts = int(datetime.now(timezone.utc).timestamp())
    today    = datetime.now().strftime('%Y-%m-%d')

    new_games = []
    for g in reversed(games):
        appid = g['appid']
        if appid in existing_ids or appid in blacklisted_ids:
            continue
        if appinfo_db.get(appid, {}).get('type', 'game').lower() != 'game':
            continue
        playtime = g['playtime_forever'] or 0
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
    batch_insert_placeholder_games(new_games, today_ts)
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
                sc_count = len(blaeo_result.get('status_changes', []))
                rn_count = len(blaeo_result.get('renames', []))
                ad_count = len(blaeo_result.get('additions', []))
                rm_count = len(blaeo_result.get('removals', []))
                log.info(f"[populate] BLAEO pre-scrape updated {blaeo_result['updated']} game(s)"
                         + (f", {sc_count} status change(s)" if sc_count else "")
                         + (f", {rn_count} group rename(s)" if rn_count else "")
                         + (f", {ad_count} group addition(s)" if ad_count else "")
                         + (f", {rm_count} group removal(s)" if rm_count else "") + ".")
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
        batch = set(appid_list)
        for _ in range(META_WORKERS):
            futures.append(executor.submit(
                _meta_worker, meta_nq, meta_pq, meta_backoff, cancel_event, total, today, progress_cb, batch
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
                    _cheevo_worker, cheevo_nq, cheevo_pq, cheevo_backoff, cancel_event, today, progress_cb, batch
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

def _parse_steam_date(raw):
    """Parse a Steam date string to a Unix timestamp, trying multiple formats. Returns None on failure."""
    for fmt in ("%b %d, %Y", "%d %b, %Y", "%B %d, %Y"):
        try:
            return int(datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).timestamp())
        except (ValueError, TypeError):
            continue
    return None


_appinfo_cache = None

def _get_appinfo():
    global _appinfo_cache
    if _appinfo_cache is None:
        _appinfo_cache = parse_appinfo()
    return _appinfo_cache


def _scrape_store_page_date(appid, session=None):
    """
    Scrape the release date displayed on the Steam store page.
    Returns a Unix timestamp or None. Preferred over the API date because the
    API returns the Steam launch date; the store page shows the original release date.
    """
    _http = session or requests
    url = f"https://store.steampowered.com/app/{appid}/?l=english"
    try:
        resp = _http.get(
            url, timeout=15,
            cookies={'birthtime': '0', 'mature_content': '1'},
            allow_redirects=True,
        )
        if resp.status_code == 429:
            raise RateLimitedError(_parse_retry_after(resp))
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        date_div = soup.select_one('.release_date .date')
        if not date_div:
            return None
        return _parse_steam_date(date_div.get_text(strip=True))
    except RateLimitedError:
        raise
    except Exception as e:
        log.debug(f"_scrape_store_page_date({appid}): {e}")
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
            raise RateLimitedError(_parse_retry_after(response))
        response.raise_for_status()
        json_data = response.json()

        # The API returns data keyed by the appid string
        if not json_data or not json_data.get(str(appid), {}).get('success'):
            log.info(f"Could not find store data for {appid}")
            return None

        data = json_data[str(appid)]['data']

        # Prefer local appinfo.vdf dates (no HTTP): original_release_date matches
        # the store page display date; steam_release_date is the Steam launch date.
        # Fall back to scraping the store page only when neither is available.
        vdf_entry = _get_appinfo().get(int(appid), {})
        vdf_date = vdf_entry.get('original_release_date') or vdf_entry.get('steam_release_date')

        if vdf_date is not None:
            release_date = vdf_date
        else:
            api_date = _parse_steam_date(data.get('release_date', {}).get('date', ''))
            try:
                store_date = _scrape_store_page_date(appid, session)
            except RateLimitedError:
                raise
            except Exception:
                store_date = None
            release_date = store_date if store_date is not None else api_date

        extracted = {
            'name':         data.get('name', ''),
            'type':         data.get('type', ''),
            'developers':   ",".join(data.get('developers', [])),
            'publishers':   ",".join(data.get('publishers', [])),
            'release_date': release_date,
            'genres':       ",".join(g['description'] for g in data.get('genres', [])),
            'categories':   ",".join(c['description'] for c in data.get('categories', [])),
            'is_free':      1 if data.get('is_free') else 0,
        }

        return extracted

    except RateLimitedError:
        raise
    except Exception:
        log.error(f"Error fetching store data for {appid}")
        return None


# Scrape Reviews API (Percentage, Description)
def fetch_review_data(appid, session=None):
    _http = session or requests
    url = f"https://store.steampowered.com/appreviews/{appid}?json=1&language=all&num_per_page=0&purchase_type=all"

    try:
        response = _http.get(url, timeout=20)
        if response.status_code == 429:
            raise RateLimitedError(_parse_retry_after(response))
        response.raise_for_status()

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

        percent = int((positive / total) * 100) if total > 0 else 0

        weighted = _weighted_score(percent, total)

        return {
            'review_score':       score,
            'review_percentage':  percent,
            'weighted_percentage': weighted,
            'total_reviews':      total,
            'positive_reviews':   positive,
        }

    except RateLimitedError:
        raise
    except Exception:
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
            raise RateLimitedError(_parse_retry_after(response))
        if response.status_code == 400:
            return {'total_achievements': 0, 'unlocked_achievements': 0}
        response.raise_for_status()
        json_data = response.json()

        playerstats = json_data.get('playerstats', {})
        if not playerstats.get('success'):
            log.info(f"No achievement data for {appid} (game may not have achievements)")
            return {'total_achievements': 0, 'unlocked_achievements': 0}

        achievements = playerstats.get('achievements', [])

        # Calculate the numbers for DB columns
        total = len(achievements)
        unlocked = sum(1 for a in achievements if a.get('achieved') == 1)

        if total > 0 and unlocked == total:
            return {
                'total_achievements':   total,
                'unlocked_achievements': unlocked,
                'completion_status':    'Completed',
            }
        return {
            'total_achievements':   total,
            'unlocked_achievements': unlocked,
        }

    except RateLimitedError:
        raise
    except Exception:
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
            raise RateLimitedError(_parse_retry_after(response))
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

_blaeo_preview_cache = None


def _blaeo_scrape_and_compute(today=None):
    """Scrape BLAEO and compute proposed changes without writing to the database."""
    if today is None:
        today = datetime.now().strftime('%Y-%m-%d')
    config_data = load_config()
    account = get_active_account()
    blaeo_url = config_data.get('blaeo_url')
    if not blaeo_url:
        steam_id = (account or {}).get('steam_id')
        if not steam_id:
            return {"status": "skipped", "message": "No BLAEO account configured."}
        blaeo_url = f"https://www.backlog-assassins.net/users/+{steam_id}/games"

    base_url = blaeo_url.rstrip('/')
    status_map = {
        "Never-played": "Never Played",
        "Wont-play":    "Won't Play",
        "Unfinished":   "Unfinished",
        "Beaten":       "Beaten",
        "Completed":    "Completed",
    }

    session = requests.Session()
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

    current_lists = {}
    for row in all_rows:
        for tag in row.select("a.list-tag"):
            href = tag.get('href', '')
            m = re.search(r'/lists/(\w+)', href)
            if m:
                current_lists[m.group(1)] = tag.get_text(strip=True)

    from config import load_group_sources
    gs = load_group_sources()

    stored = {sid[len('blaeo:'):]: sdata['name']
              for sid, sdata in gs.get('sources', {}).items()
              if sdata.get('type') == 'blaeo'}

    renames = []
    for list_id, new_name in current_lists.items():
        old_name = stored.get(list_id)
        if old_name and old_name != new_name:
            renames.append({"id": list_id, "from": old_name, "to": new_name})

    rename_map = {r['from']: r['to'] for r in renames}

    db = get_db()
    cursor = db.cursor()

    _PLAYDATE_STATUSES = {"Never Played", "Unfinished", "Beaten", "Completed", "Won't Play"}
    status_changes = []
    current_members = set()
    row_data = []

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

            classes = row.get('class', [])
            raw_status = "Unknown"
            for c in classes:
                if c.startswith("game-") and c != "game":
                    raw_status = c.replace("game-", "").capitalize()
            clean_status = status_map.get(raw_status, raw_status)

            tag_elements = row.select("a.list-tag")
            blaeo_groups = [tag.get_text(strip=True) for tag in tag_elements]
            for tag in tag_elements:
                m = re.search(r'/lists/(\w+)', tag.get('href', ''))
                if m:
                    current_members.add((appid, m.group(1)))

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

            row_data.append((appid, clean_status, blaeo_groups, unlocked_ach, total_ach))
        except Exception as e:
            log.error(f"Skipping a BLAEO row due to error: {e}")
            continue

    stored_members = {(appid, sid[len('blaeo:'):])
                      for sid, sdata in gs.get('sources', {}).items()
                      if sdata.get('type') == 'blaeo'
                      for appid in sdata.get('members', [])}
    removed_members = stored_members - current_members

    removals = []
    for appid, list_id in removed_members:
        list_name = stored.get(list_id) or current_lists.get(list_id)
        if not list_name:
            continue
        cursor.execute("SELECT name, groups FROM games WHERE appid = ?", (appid,))
        db_row = cursor.fetchone()
        if not db_row:
            continue
        # Simulate pending renames when checking membership
        existing = {rename_map.get(g, g) for g in
                    (g.strip() for g in (db_row['groups'] or '').split(',') if g.strip())}
        effective_list_name = rename_map.get(list_name, list_name)
        if effective_list_name in existing:
            removals.append({"appid": appid, "name": db_row['name'], "list_name": effective_list_name, "list_id": list_id})

    additions = []
    for appid, clean_status, blaeo_groups, unlocked_ach, total_ach in row_data:
        cursor.execute("SELECT groups, completion_status, name FROM games WHERE appid = ?", (appid,))
        db_row = cursor.fetchone()
        if not db_row:
            continue

        # Simulate pending renames so additions aren't counted for renamed groups
        existing_groups_set = {rename_map.get(g, g) for g in
                               (g.strip() for g in (db_row['groups'] or '').split(',') if g.strip())}
        newly_added = set(blaeo_groups) - existing_groups_set
        if newly_added:
            additions.append({"appid": appid, "name": db_row['name'], "list_names": sorted(newly_added)})

        old_status = db_row['completion_status'] or 'Never Played'
        effective_status = clean_status if clean_status in _PLAYDATE_STATUSES else old_status
        if effective_status != old_status:
            status_changes.append({"from": old_status, "to": effective_status,
                                   "name": db_row['name'], "appid": appid})

    db.close()

    return {
        "status":         "success",
        "row_data":       row_data,
        "current_members": current_members,
        "current_lists":  current_lists,
        "stored_lists":   stored,
        "status_changes": status_changes,
        "renames":        renames,
        "additions":      additions,
        "removals":       removals,
        "today":          today,
    }


def _rebuild_blaeo_sources(gs, current_lists, current_members, cursor):
    """Rebuild BLAEO sources in gs from the current scraped state and mark
    any untracked DB groups as manual. cursor must be open; caller commits."""
    from config import gs_add_owner
    # Strip all existing BLAEO ownership from assignments
    for sid in [s for s in list(gs.get('sources', {})) if s.startswith('blaeo:')]:
        for game in gs.get('assignments', {}).values():
            for group in list(game.keys()):
                if sid in game[group]:
                    game[group].remove(sid)
                if not game[group]:
                    del game[group]
        del gs['sources'][sid]
    gs['assignments'] = {k: v for k, v in gs.get('assignments', {}).items() if v}

    for list_id, name in current_lists.items():
        source_id = f'blaeo:{list_id}'
        members   = sorted({appid for appid, lid in current_members if lid == list_id})
        gs.setdefault('sources', {})[source_id] = {'type': 'blaeo', 'name': name, 'members': members}
        for appid in members:
            gs_add_owner(gs, appid, name, source_id)

    for db_row in cursor.execute(
        "SELECT appid, groups FROM games WHERE groups IS NOT NULL AND groups != ''"
    ).fetchall():
        appid_str = str(db_row['appid'])
        for group in (g.strip() for g in db_row['groups'].split(',') if g.strip()):
            if group not in gs.get('assignments', {}).get(appid_str, {}):
                gs_add_owner(gs, db_row['appid'], group, 'manual')


def _rebuild_steam_sources(gs, current_collections, current_members, cursor):
    """Rebuild Steam collection sources in gs and mark untracked DB groups as manual."""
    from config import gs_add_owner
    for sid in [s for s in list(gs.get('sources', {})) if s.startswith('steam:')]:
        for game in gs.get('assignments', {}).values():
            for group in list(game.keys()):
                if sid in game[group]:
                    game[group].remove(sid)
                if not game[group]:
                    del game[group]
        del gs['sources'][sid]
    gs['assignments'] = {k: v for k, v in gs.get('assignments', {}).items() if v}

    for col_id, col_data in current_collections.items():
        source_id = f'steam:{col_id}'
        members   = sorted({appid for appid, cid in current_members if cid == col_id})
        gs.setdefault('sources', {})[source_id] = {'type': 'steam', 'name': col_data['name'], 'members': members}
        for appid in members:
            gs_add_owner(gs, appid, col_data['name'], source_id)

    for db_row in cursor.execute(
        "SELECT appid, groups FROM games WHERE groups IS NOT NULL AND groups != ''"
    ).fetchall():
        appid_str = str(db_row['appid'])
        for group in (g.strip() for g in db_row['groups'].split(',') if g.strip()):
            if group not in gs.get('assignments', {}).get(appid_str, {}):
                gs_add_owner(gs, db_row['appid'], group, 'manual')


def _blaeo_apply_all(data):
    """Write all proposed BLAEO changes to the database. Used by the populate flow."""
    from config import load_group_sources, save_group_sources, gs_is_protected
    today           = data['today']
    row_data        = data['row_data']
    current_members = data['current_members']
    current_lists   = data['current_lists']
    renames         = data['renames']
    removals        = data['removals']
    additions       = data['additions']
    status_changes  = data['status_changes']

    db = get_db()
    cursor = db.cursor()
    updated_count = 0

    gs = load_group_sources()

    for r in renames:
        log.info(f"BLAEO list renamed: '{r['from']}' -> '{r['to']}'")
        source_id = f'blaeo:{r["id"]}'
        for appid, lid in current_members:
            if lid != r['id']:
                continue
            row = cursor.execute("SELECT groups FROM games WHERE appid = ?", (appid,)).fetchone()
            if not row:
                continue
            existing = {g.strip() for g in (row['groups'] or '').split(',') if g.strip()}
            if r['from'] not in existing:
                continue
            if not gs_is_protected(gs, appid, r['from'], source_id):
                existing.discard(r['from'])
            existing.add(r['to'])
            cursor.execute("UPDATE games SET groups = ? WHERE appid = ?",
                           (','.join(sorted(existing)), appid))

    for r in removals:
        source_id = f'blaeo:{r["list_id"]}'
        if gs_is_protected(gs, r['appid'], r['list_name'], source_id):
            log.info(f"[BLAEO] Kept '{r['list_name']}' on {r['name']} — still owned by another source")
            continue
        db_row = cursor.execute("SELECT groups FROM games WHERE appid = ?", (r['appid'],)).fetchone()
        if db_row:
            existing = {g.strip() for g in (db_row['groups'] or '').split(',') if g.strip()}
            existing.discard(r['list_name'])
            cursor.execute("UPDATE games SET groups = ? WHERE appid = ?",
                           (','.join(sorted(existing)), r['appid']))
            log.info(f"[BLAEO] Removed '{r['list_name']}' from groups for {r['name']} (appid={r['appid']})")

    _PLAYDATE_STATUSES = {"Never Played", "Unfinished", "Beaten", "Completed", "Won't Play"}

    for appid, clean_status, blaeo_groups, unlocked_ach, total_ach in row_data:
        try:
            db_row = cursor.execute(
                "SELECT groups, completion_status, name FROM games WHERE appid = ?", (appid,)
            ).fetchone()
            if not db_row:
                log.info(f"Game found on BLAEO but not in local DB: AppID {appid}")
                continue

            existing_groups_set = {g.strip() for g in (db_row['groups'] or '').split(',') if g.strip()}
            updated_groups_set  = existing_groups_set.union(set(blaeo_groups))
            new_groups_str      = ','.join(sorted(updated_groups_set))

            old_status       = db_row['completion_status'] or 'Never Played'
            effective_status = clean_status if clean_status in _PLAYDATE_STATUSES else old_status

            if unlocked_ach is not None:
                cursor.execute(
                    "UPDATE games SET completion_status = ?, groups = ?, "
                    "unlocked_achievements = ?, total_achievements = ?, cheevos_fetched = ? "
                    "WHERE appid = ?",
                    (effective_status, new_groups_str, unlocked_ach, total_ach, today, appid)
                )
            else:
                cursor.execute(
                    "UPDATE games SET completion_status = ?, groups = ? WHERE appid = ?",
                    (effective_status, new_groups_str, appid)
                )
            updated_count += 1
        except Exception as e:
            log.error(f"Skipping a BLAEO row during update: {e}")
            continue

    db.commit()

    _rebuild_blaeo_sources(gs, current_lists, current_members, cursor)
    db.close()
    save_group_sources(gs)

    log.info(f"Successfully synced {updated_count} games from BLAEO.")
    for sc in status_changes:
        log.info(f"[BLAEO] Status change: {sc['name']} (appid={sc['appid']}): {sc['from']} -> {sc['to']}")
    for r in renames:
        log.info(f"[BLAEO] Group renamed: '{r['from']}' -> '{r['to']}'")
    for a in additions:
        for ln in a['list_names']:
            log.info(f"[BLAEO] Added '{ln}' to groups for {a['name']} (appid={a['appid']})")

    return {
        "status":         "success",
        "updated":        updated_count,
        "status_changes": status_changes,
        "renames":        renames,
        "additions":      additions,
        "removals":       removals,
    }


def sync_steam_collections(steam_id=None):
    """
    Reads Steam library collections and syncs them to the groups column.
    Mirrors the BLAEO pattern: renames scoped to collection members, removals
    protected by BLAEO cross-check (won't remove a group that a BLAEO list also owns).
    """
    from utils import read_steam_collections

    current_collections = read_steam_collections(steam_id)
    if not current_collections:
        log.info("[SteamCollections] No collections found — sync skipped.")
        return {'status': 'skipped', 'message': 'No collections found.'}

    from config import load_group_sources, save_group_sources, gs_is_protected

    db = get_db()
    cursor = db.cursor()

    gs = load_group_sources()

    stored = {sid[len('steam:'):]: sdata['name']
              for sid, sdata in gs.get('sources', {}).items()
              if sdata.get('type') == 'steam'}
    stored_members = {(appid, sid[len('steam:'):])
                      for sid, sdata in gs.get('sources', {}).items()
                      if sdata.get('type') == 'steam'
                      for appid in sdata.get('members', [])}

    # Build current members, limited to appids present in the games table
    db_appids = {r['appid'] for r in cursor.execute("SELECT appid FROM games").fetchall()}
    current_members = {
        (appid, col_id)
        for col_id, col_data in current_collections.items()
        for appid in col_data['added']
        if appid in db_appids
    }

    renames = [
        {'id': col_id, 'from': stored[col_id], 'to': col_data['name']}
        for col_id, col_data in current_collections.items()
        if col_id in stored and stored[col_id] != col_data['name']
    ]

    added_members   = current_members - stored_members
    removed_members = stored_members  - current_members

    game_names = {r['appid']: r['name'] for r in cursor.execute("SELECT appid, name FROM games").fetchall()}

    added = [
        {'appid': appid, 'name': game_names.get(appid, str(appid)),
         'collection_id': col_id, 'collection_name': current_collections[col_id]['name']}
        for appid, col_id in added_members
    ]
    removed = [
        {'appid': appid, 'name': game_names.get(appid, str(appid)),
         'collection_id': col_id, 'collection_name': stored[col_id]}
        for appid, col_id in removed_members
        if col_id in stored
    ]

    for r in renames:
        member_appids = [appid for appid, col_id in current_members if col_id == r['id']]
        if not member_appids:
            continue
        log.info(f"[SteamCollections] Renamed '{r['from']}' -> '{r['to']}'")
        source_id = f'steam:{r["id"]}'
        for appid in member_appids:
            row = cursor.execute("SELECT groups FROM games WHERE appid = ?", (appid,)).fetchone()
            if not row:
                continue
            existing = {g.strip() for g in (row['groups'] or '').split(',') if g.strip()}
            if r['from'] not in existing:
                continue
            if not gs_is_protected(gs, appid, r['from'], source_id):
                existing.discard(r['from'])
            existing.add(r['to'])
            cursor.execute("UPDATE games SET groups = ? WHERE appid = ?",
                           (','.join(sorted(existing)), appid))

    for r in removed:
        source_id = f'steam:{r["collection_id"]}'
        if gs_is_protected(gs, r['appid'], r['collection_name'], source_id):
            log.info(f"[SteamCollections] Kept '{r['collection_name']}' on {r['name']} — still owned by another source")
            continue
        row = cursor.execute("SELECT groups FROM games WHERE appid = ?", (r['appid'],)).fetchone()
        if row:
            existing = {g.strip() for g in (row['groups'] or '').split(',') if g.strip()}
            existing.discard(r['collection_name'])
            cursor.execute("UPDATE games SET groups = ? WHERE appid = ?",
                           (','.join(sorted(existing)), r['appid']))
            log.info(f"[SteamCollections] Removed '{r['collection_name']}' from {r['name']} (appid={r['appid']})")

    from config import gs_add_owner as _gs_add_owner
    for a in added:
        row = cursor.execute("SELECT groups FROM games WHERE appid = ?", (a['appid'],)).fetchone()
        if row:
            existing = {g.strip() for g in (row['groups'] or '').split(',') if g.strip()}
            if a['collection_name'] in existing:
                # Group pre-existed before this Steam collection claimed it — treat as manual co-owner
                _gs_add_owner(gs, a['appid'], a['collection_name'], 'manual')
            existing.add(a['collection_name'])
            cursor.execute("UPDATE games SET groups = ? WHERE appid = ?",
                           (','.join(sorted(existing)), a['appid']))
            log.info(f"[SteamCollections] Added '{a['collection_name']}' to {a['name']} (appid={a['appid']})")

    db.commit()

    _rebuild_steam_sources(gs, current_collections, current_members, cursor)
    db.close()
    save_group_sources(gs)

    log.info(f"[SteamCollections] Sync complete: {len(renames)} rename(s), "
             f"{len(added)} addition(s), {len(removed)} removal(s)")
    return {'status': 'success', 'renames': len(renames), 'additions': len(added), 'removals': len(removed)}


def scrape_blaeo_games(today=None):
    try:
        data = _blaeo_scrape_and_compute(today)
        if data.get('status') != 'success':
            return data
        return _blaeo_apply_all(data)
    except Exception as e:
        log.error(f"BLAEO scraper error: {e}")
        return {"status": "error", "message": str(e)}


def get_blaeo_preview(today=None):
    """Scrape BLAEO and cache proposed changes for user review. Call apply_blaeo_changes() to commit."""
    global _blaeo_preview_cache
    try:
        data = _blaeo_scrape_and_compute(today)
        if data.get('status') != 'success':
            return data
        _blaeo_preview_cache = data
        return {
            "status":         "success",
            "status_changes": data['status_changes'],
            "renames":        data['renames'],
            "additions":      data['additions'],
            "removals":       data['removals'],
        }
    except Exception as e:
        log.error(f"BLAEO preview error: {e}")
        return {"status": "error", "message": str(e)}


def apply_blaeo_changes(selections):
    """Apply a user-selected subset of the cached BLAEO preview. Clears the cache when done."""
    global _blaeo_preview_cache
    if not _blaeo_preview_cache:
        return {"status": "error", "message": "No preview data. Run Sync first."}

    data           = _blaeo_preview_cache
    today          = data['today']
    row_data       = data['row_data']
    current_members = data['current_members']
    current_lists  = data['current_lists']
    renames        = data['renames']

    accept_status_set   = set(int(a) for a in selections.get('accept_status', []))
    accept_additions_set = set(int(a) for a in selections.get('accept_additions', []))
    accept_removals_set = {(int(r['appid']), r['list_name']) for r in selections.get('accept_removals', [])}
    accept_renames_set  = {(r['from'], r['to']) for r in selections.get('accept_renames', [])}

    db = get_db()
    cursor = db.cursor()
    updated_count = 0

    from config import load_group_sources, save_group_sources, gs_is_protected
    gs = load_group_sources()

    for r in renames:
        if (r['from'], r['to']) in accept_renames_set:
            log.info(f"[BLAEO] Applying rename: '{r['from']}' -> '{r['to']}'")
            source_id = f'blaeo:{r["id"]}'
            for appid, lid in current_members:
                if lid != r['id']:
                    continue
                row = cursor.execute("SELECT groups FROM games WHERE appid = ?", (appid,)).fetchone()
                if not row:
                    continue
                existing = {g.strip() for g in (row['groups'] or '').split(',') if g.strip()}
                if r['from'] not in existing:
                    continue
                if not gs_is_protected(gs, appid, r['from'], source_id):
                    existing.discard(r['from'])
                existing.add(r['to'])
                cursor.execute("UPDATE games SET groups = ? WHERE appid = ?",
                               (','.join(sorted(existing)), appid))

    applied_removals = []
    for r in data['removals']:
        if (r['appid'], r['list_name']) in accept_removals_set:
            source_id = f'blaeo:{r["list_id"]}'
            if gs_is_protected(gs, r['appid'], r['list_name'], source_id):
                log.info(f"[BLAEO] Kept '{r['list_name']}' on {r['name']} — still owned by another source")
                continue
            db_row = cursor.execute("SELECT groups FROM games WHERE appid = ?", (r['appid'],)).fetchone()
            if db_row:
                existing = {g.strip() for g in (db_row['groups'] or '').split(',') if g.strip()}
                existing.discard(r['list_name'])
                cursor.execute("UPDATE games SET groups = ? WHERE appid = ?",
                               (','.join(sorted(existing)), r['appid']))
                applied_removals.append(r)
                log.info(f"[BLAEO] Removed '{r['list_name']}' from groups for {r['name']} (appid={r['appid']})")

    _PLAYDATE_STATUSES = {"Never Played", "Unfinished", "Beaten", "Completed", "Won't Play"}
    applied_status_changes = []
    applied_additions = []

    for appid, clean_status, blaeo_groups, unlocked_ach, total_ach in row_data:
        try:
            cursor.execute("SELECT groups, completion_status, name FROM games WHERE appid = ?", (appid,))
            db_row = cursor.fetchone()
            if not db_row:
                continue

            existing_groups_str = db_row['groups'] if db_row['groups'] else ""
            existing_groups_set = set(g.strip() for g in existing_groups_str.split(',') if g.strip())

            old_status = db_row['completion_status'] or 'Never Played'
            effective_status = clean_status if clean_status in _PLAYDATE_STATUSES else old_status

            apply_status   = appid in accept_status_set and effective_status != old_status
            newly_added    = set(blaeo_groups) - existing_groups_set
            apply_addition = appid in accept_additions_set and bool(newly_added)

            if not apply_status and not apply_addition:
                continue

            new_groups_set = existing_groups_set.union(set(blaeo_groups)) if apply_addition else existing_groups_set
            new_groups_str = ",".join(sorted(new_groups_set))
            final_status   = effective_status if apply_status else old_status

            if apply_status:
                applied_status_changes.append({"appid": appid, "name": db_row['name'],
                                               "from": old_status, "to": effective_status})
                log.info(f"[BLAEO] Status: {db_row['name']} ({appid}): {old_status} -> {effective_status}")
            if apply_addition:
                applied_additions.append({"appid": appid, "name": db_row['name'],
                                          "list_names": sorted(newly_added)})
                for ln in sorted(newly_added):
                    log.info(f"[BLAEO] Added '{ln}' to groups for {db_row['name']} (appid={appid})")

            if unlocked_ach is not None:
                cursor.execute(
                    "UPDATE games SET completion_status = ?, groups = ?, unlocked_achievements = ?, total_achievements = ?, cheevos_fetched = ? WHERE appid = ?",
                    (final_status, new_groups_str, unlocked_ach, total_ach, today, appid)
                )
            else:
                cursor.execute(
                    "UPDATE games SET completion_status = ?, groups = ? WHERE appid = ?",
                    (final_status, new_groups_str, appid)
                )
            updated_count += 1
        except Exception as e:
            log.error(f"Skipping a BLAEO row during selective apply: {e}")
            continue

    db.commit()

    _rebuild_blaeo_sources(gs, current_lists, current_members, cursor)
    db.close()
    save_group_sources(gs)
    _blaeo_preview_cache = None

    applied_renames = [r for r in renames if (r['from'], r['to']) in accept_renames_set]
    log.info(f"[BLAEO] Selective apply: {updated_count} game(s) updated.")

    return {
        "status":         "success",
        "updated":        updated_count,
        "status_changes": applied_status_changes,
        "renames":        applied_renames,
        "additions":      applied_additions,
        "removals":       applied_removals,
    }

def get_blaeo_cached_result():
    """Return the cached preview data without re-scraping, or None if no cache."""
    if not _blaeo_preview_cache:
        return None
    return {
        "status":         "success",
        "status_changes": _blaeo_preview_cache['status_changes'],
        "renames":        _blaeo_preview_cache['renames'],
        "additions":      _blaeo_preview_cache['additions'],
        "removals":       _blaeo_preview_cache['removals'],
    }


def clear_blaeo_cache():
    global _blaeo_preview_cache
    _blaeo_preview_cache = None


def sync_recent_playtime():
    """
    On startup: update playtime_forever + last_played for all played games by
    reading localconfig.vdf directly. No API key required. Runs in a background
    thread — safe to call without blocking startup.

    For games where playtime_forever increased, also fetches achievements (if an
    API key is configured) and updates completion_status:
      - Never Played + playtime > 0  → Unfinished (if auto_promote_unfinished is enabled)
      - 100% achievements unlocked   → Completed (any status)
      - Won't Play                   → only changed if 100% achievements
      - Beaten                       → never downgraded; upgraded to Completed if 100%
    """
    from config import load_state
    try:
        account = get_active_account()
        if not account:
            return
        steam_id = account.get('steam_id', '').strip()
        if not steam_id:
            return

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
            elif current_status == 'Never Played' and new_playtime > 0 and load_state().get('auto_promote_unfinished', True):
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
            "   AND (platform = 'steam' OR platform IS NULL)"
        )
        if result.rowcount:
            log.info(f"sync_recent_playtime: promoted {result.rowcount} game(s) to Completed via achievement sweep.")

        db.commit()
        db.close()
        log.info(f"sync_recent_playtime: updated {updated} games.")

    except Exception as e:
        log.warning(f"sync_recent_playtime failed: {e}")


# ── Bulk concurrent operations ────────────────────────────────────────────────

def bulk_rescrape_games(appids, cancel_event, progress_cb):
    """
    Concurrent metadata re-scrape for a list of appids.
    Non-Steam platforms are routed to their plugin's rescrape() method.
    Uses _PoolBackoff for rate limiting on Steam games; respects cancel_event.
    3 concurrent workers with 0.5s inter-game delay.
    """
    import plugins as _plugins_mod

    backoff  = _PoolBackoff('bulk_rescrape')
    today    = datetime.now().strftime('%Y-%m-%d')
    _account = get_active_account() or {}
    has_key  = bool(_account.get('api_key'))

    db = get_db()
    rows = db.execute(
        f"SELECT appid, platform FROM games WHERE appid IN ({','.join('?' * len(appids))})",
        appids,
    ).fetchall()
    db.close()
    platform_map = {row['appid']: (row['platform'] or 'steam') for row in rows}

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

            platform = platform_map.get(appid, 'steam')
            try:
                plugin = _plugins_mod.get_for_platform(platform)
                if plugin is not None and hasattr(plugin, 'rescrape'):
                    # ── Plugin-handled game ───────────────────────────────────
                    meta = plugin.rescrape(appid)
                    if meta:
                        update_game_data(appid, **meta)
                        with lock:
                            counts['done'] += 1
                        if progress_cb:
                            progress_cb('done', appid, total)
                    else:
                        with lock:
                            counts['failed'] += 1
                        if progress_cb:
                            progress_cb('failed', appid, total)
                    time.sleep(0.5)

                else:
                    # ── Steam game ────────────────────────────────────────────
                    if not backoff.wait_ready(cancel_event):
                        return

                    store_data  = fetch_store_data(appid)  or {}
                    store_data.pop('type', None)
                    review_data = fetch_review_data(appid) or {}
                    tag_data    = fetch_tag_data(appid)    or {}
                    cheevo_data = fetch_cheevo_data(appid) or {} if has_key else {}

                    game_data = {}
                    if store_data:
                        game_data['name_from_store'] = 1
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

            except RateLimitedError as e:
                q.put(appid)   # re-queue for retry after backoff
                if progress_cb:
                    attempt = backoff._attempt + 1
                    delay   = min(e.retry_after, BACKOFF_DELAYS[-1]) if e.retry_after else BACKOFF_DELAYS[min(backoff._attempt, len(BACKOFF_DELAYS) - 1)]
                    progress_cb('rate_limit', {'attempt': attempt, 'delay': delay}, total)
                if not backoff.on_rate_limited(cancel_event, retry_after=e.retry_after):
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
            f"SELECT appid, name, icon_hash FROM games WHERE appid IN ({','.join('?' * len(appids))})",
            appids
        ).fetchall()
        db.close()
        icon_hash_map = {r['appid']: r['icon_hash'] or '' for r in rows}
        name_map      = {r['appid']: r['name'] or '' for r in rows if r['appid'] < 0}
    else:
        icon_hash_map = {}
        name_map      = {}

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
                if appid < 0:
                    name    = name_map.get(appid, '')
                    sgdb_id = _sgdb_search_game_id(name) if name else None
                    if 'vertical' in types:
                        updates['vertical_art_source']   = download_vertical(appid, sgdb_id=sgdb_id, game_name=name)
                    if 'horizontal' in types:
                        updates['horizontal_art_source'] = download_horizontal(appid, sgdb_id=sgdb_id, game_name=name)
                    if 'icon' in types:
                        updates['icon_source']           = download_icon(appid, '', sgdb_id=sgdb_id, game_name=name)
                else:
                    assets = _get_steam_assets(appid) if source != 'sgdb' else {}
                    if 'vertical' in types:
                        updates['vertical_art_source']   = download_vertical(appid, assets=assets, source=source)
                    if 'horizontal' in types:
                        updates['horizontal_art_source'] = download_horizontal(appid, assets=assets, source=source)
                    if 'icon' in types:
                        updates['icon_source']           = download_icon(appid, icon_hash_map.get(appid, ''), source=source)
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
_store_date_migration_cancel = threading.Event()
_store_name_migration_cancel = threading.Event()
_populate_idle = threading.Event()
_populate_idle.set()  # set = no populate running; cleared while add_new() is running


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

    steam_hltb_map = _load_steam_hltb_map()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

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
                hltb_id = steam_hltb_map.get(str(appid))
                if hltb_id:
                    info = fetch_hltb_by_id(name, hltb_id)
                    info.pop('times_available', None)
                    update_game_data(appid, hltb_id=hltb_id, hltb_fetched=today,
                                     hltb_match_score=100, **info)
                else:
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


def sync_store_release_dates():
    """
    One-time startup migration: re-scrape release dates from Steam store pages
    so that original release dates (e.g. prior itch.io releases) replace the
    Steam launch dates previously stored from the API.

    Progress is tracked in release_date_migration.json so the migration can
    resume if interrupted. Once all games are processed the file is deleted and
    background migration v10 is marked done so this never runs again.
    """
    import migration
    from config import BASE_DIR

    if not migration.needs_background(10):
        return

    progress_path = os.path.join(BASE_DIR, 'release_date_migration.json')
    try:
        with open(progress_path, 'r', encoding='utf-8') as f:
            done_ids = set(json.load(f).get('done', []))
    except FileNotFoundError:
        done_ids = set()
    except Exception as e:
        log.warning(f"sync_store_release_dates: could not read progress file — {e}")
        done_ids = set()

    db   = get_db()
    rows = db.execute(
        "SELECT appid FROM games WHERE platform = 'steam'"
    ).fetchall()
    db.close()

    pending = [str(r['appid']) for r in rows if str(r['appid']) not in done_ids]

    if not pending:
        migration.mark_background_done(10)
        try:
            os.remove(progress_path)
        except FileNotFoundError:
            pass
        log.info("sync_store_release_dates: already complete.")
        return

    log.info(f"sync_store_release_dates: migrating {len(pending)} game(s).")

    session     = requests.Session()
    failed      = 0
    batch_count = 0

    def _save_progress():
        try:
            with open(progress_path, 'w', encoding='utf-8') as f:
                json.dump({'done': list(done_ids)}, f)
        except Exception as e:
            log.warning(f"sync_store_release_dates: could not save progress — {e}")

    for appid_str in pending:
        if _store_date_migration_cancel.is_set():
            log.info("sync_store_release_dates: cancelled.")
            break

        appid = int(appid_str)
        for attempt in range(2):
            try:
                ts = _scrape_store_page_date(appid, session)
                if ts is not None:
                    update_game_data(appid, release_date=ts)
                done_ids.add(appid_str)
                break
            except RateLimitedError as e:
                if attempt == 0:
                    delay = min(e.retry_after, 300) if e.retry_after else 30
                    log.warning(f"sync_store_release_dates: rate limited at appid {appid}, pausing {delay:.0f}s.")
                    time.sleep(delay)
                else:
                    log.error(f"sync_store_release_dates: retry failed for {appid} — rate limited again")
                    failed += 1
                    done_ids.add(appid_str)
            except Exception as e:
                log.error(f"sync_store_release_dates: error for {appid} — {e}")
                failed += 1
                done_ids.add(appid_str)
                break

        batch_count += 1
        if batch_count % 10 == 0:
            _save_progress()

        time.sleep(1)

    _save_progress()

    remaining = [a for a in pending if a not in done_ids]
    if not remaining:
        migration.mark_background_done(10)
        try:
            os.remove(progress_path)
        except FileNotFoundError:
            pass
        log.info(f"sync_store_release_dates: complete. failed={failed}")
    else:
        log.info(f"sync_store_release_dates: paused with {len(remaining)} remaining, failed={failed}")


def sync_store_names():
    """
    One-time startup migration: fetch the store display name from appdetails for
    all Steam games where name_from_store is 0 or NULL (names sourced from
    GetOwnedGames or local files, which can differ from the store page name).

    Uses background migration v11. Runs 1 request/second to avoid rate limiting.
    Name differences are written to store_names_pending.json for user review
    rather than applied automatically.
    """
    import migration
    from config import BASE_DIR

    if not migration.needs_background(11):
        return

    db   = get_db()
    rows = db.execute(
        "SELECT appid, name FROM games "
        "WHERE platform = 'steam' AND (name_from_store IS NULL OR name_from_store = 0) "
        "AND meta_fetched IS NOT NULL AND meta_fetched != '0'"
    ).fetchall()
    db.close()

    if not rows:
        migration.mark_background_done(11)
        log.info("sync_store_names: nothing to update.")
        return

    log.info(f"sync_store_names: checking names for {len(rows)} game(s).")
    session = requests.Session()
    failed  = 0
    pending = []

    for row in rows:
        if _store_name_migration_cancel.is_set():
            log.info("sync_store_names: cancelled.")
            return

        # Pause while populate is running to avoid competing for the Steam API
        if not _populate_idle.is_set():
            log.info("sync_store_names: waiting for populate to finish.")
            _populate_idle.wait()

        appid = row['appid']
        try:
            store_info = fetch_store_data(appid, session=session)
            if store_info:
                store_name = store_info.get('name', '') or row['name']
                update_game_data(appid, name_from_store=1)
                if store_name != row['name']:
                    pending.append({'appid': appid, 'old_name': row['name'], 'new_name': store_name})
            else:
                update_game_data(appid, name_from_store=1)
        except RateLimitedError as e:
            delay = min(e.retry_after, 300) if e.retry_after else 30
            log.warning(f"sync_store_names: rate limited at appid {appid}, pausing {delay:.0f}s.")
            time.sleep(delay)
            try:
                store_info = fetch_store_data(appid, session=session)
                if store_info:
                    store_name = store_info.get('name', '') or row['name']
                    update_game_data(appid, name_from_store=1)
                    if store_name != row['name']:
                        pending.append({'appid': appid, 'old_name': row['name'], 'new_name': store_name})
                else:
                    update_game_data(appid, name_from_store=1)
            except Exception as e:
                log.error(f"sync_store_names: retry failed for {appid} — {e}")
                failed += 1
        except Exception as e:
            log.error(f"sync_store_names: error for {appid} — {e}")
            failed += 1

        time.sleep(1)

    if pending:
        pending_path = os.path.join(BASE_DIR, 'store_names_pending.json')
        with open(pending_path, 'w') as f:
            json.dump({'items': pending}, f, indent=2)
        log.info(f"sync_store_names: {len(pending)} name(s) differ — written to store_names_pending.json for review.")

    migration.mark_background_done(11)
    log.info(f"sync_store_names: complete. diffs={len(pending)}, failed={failed}")


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

    steam_hltb_map = _load_steam_hltb_map()
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')

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
                hltb_id = steam_hltb_map.get(str(appid))
                if hltb_id:
                    info = fetch_hltb_by_id(name, hltb_id)
                    info.pop('times_available', None)
                    update_game_data(appid, hltb_id=hltb_id, hltb_fetched=today_str,
                                     hltb_match_score=100, **info)
                else:
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


# ── Routes ───────────────────────────────────────────────────────────────────

@blaeo_bp.route('/sync-blaeo')
def sync_blaeo():
    try:
        result = scrape_blaeo_games()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@blaeo_bp.route('/api/blaeo-start', methods=['POST'])
def blaeo_start():
    with _blaeo_sync_lock:
        if _blaeo_sync_state['running']:
            return jsonify({'status': 'running', 'message': 'Sync already in progress'})
        if _blaeo_sync_state['done']:
            return jsonify({'status': 'pending'})
        _blaeo_sync_state['running'] = True
        _blaeo_sync_state['done']    = False
        _blaeo_sync_state['error']   = None

    def _run():
        try:
            result = get_blaeo_preview()
            with _blaeo_sync_lock:
                if result.get('status') == 'success':
                    _blaeo_sync_state['running'] = False
                    _blaeo_sync_state['done']    = True
                    _blaeo_sync_state['error']   = None
                else:
                    _blaeo_sync_state['running'] = False
                    _blaeo_sync_state['done']    = False
                    _blaeo_sync_state['error']   = result.get('message', 'Sync failed')
        except Exception as e:
            with _blaeo_sync_lock:
                _blaeo_sync_state['running'] = False
                _blaeo_sync_state['done']    = False
                _blaeo_sync_state['error']   = str(e)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'started'})

@blaeo_bp.route('/api/blaeo-status')
def blaeo_status_route():
    return jsonify(dict(_blaeo_sync_state))

@blaeo_bp.route('/api/blaeo-preview')
def blaeo_preview():
    if _blaeo_sync_state.get('done'):
        cached = get_blaeo_cached_result()
        if cached:
            return jsonify(cached)
    try:
        result = get_blaeo_preview()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@blaeo_bp.route('/api/blaeo-apply', methods=['POST'])
def blaeo_apply():
    try:
        selections = request.get_json() or {}
        result = apply_blaeo_changes(selections)
        if result.get('status') == 'success':
            with _blaeo_sync_lock:
                _blaeo_sync_state['done'] = False
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@blaeo_bp.route('/api/blaeo-discard', methods=['POST'])
def blaeo_discard():
    with _blaeo_sync_lock:
        _blaeo_sync_state['running'] = False
        _blaeo_sync_state['done']    = False
        _blaeo_sync_state['error']   = None
    clear_blaeo_cache()
    return jsonify({'status': 'ok'})

