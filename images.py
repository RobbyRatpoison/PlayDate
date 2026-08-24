import logging
import os
import io
import requests
from urllib.parse import quote as url_quote, urlparse
from urllib.request import url2pathname
from PIL import Image
from config import BASE_DIR, load_config
from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

images_bp = Blueprint('images', __name__)

LIBRARY_DIR    = os.path.join(BASE_DIR, 'static', 'img', 'library')
VERTICAL_DIR   = os.path.join(LIBRARY_DIR, 'vertical')
HORIZONTAL_DIR = os.path.join(LIBRARY_DIR, 'horizontal')
ICONS_DIR      = os.path.join(LIBRARY_DIR, 'icons')
BADGES_DIR     = os.path.join(BASE_DIR, 'static', 'img', 'badges')

BADGE_ICON_SIZE     = 64
BADGE_UPLOAD_MAX_BYTES = 5 * 1024 * 1024


def _ensure_dirs():
    for d in (VERTICAL_DIR, HORIZONTAL_DIR, ICONS_DIR):
        os.makedirs(d, exist_ok=True)


def save_badge_icon(image_bytes, save_path):
    """
    Normalizes a user-uploaded corner-badge icon to a fixed-size RGBA PNG.
    Unlike save_as_jpg(), keeps the alpha channel -- badges overlay on top of
    cover art, so a JPEG's forced-opaque background would show as a visible
    square patch. Returns True on success, False on failure.
    """
    tmp_path = save_path + '.tmp'
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        img = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
        img = img.resize((BADGE_ICON_SIZE, BADGE_ICON_SIZE), Image.LANCZOS)
        img.save(tmp_path, 'PNG')
        os.replace(tmp_path, save_path)
        return True
    except Exception as e:
        log.warning(f"save_badge_icon: conversion failed: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


def save_as_jpg(image_bytes, save_path):
    """
    Converts any image format (PNG, WEBP, etc.) to JPG and saves it.
    Creates parent directories if needed. Returns True on success, False on failure.
    """
    tmp_path = save_path + '.tmp'
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        img.save(tmp_path, 'JPEG', quality=95)
        os.replace(tmp_path, save_path)
        return True
    except Exception as e:
        log.warning(f"save_as_jpg: conversion failed: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


def _get_sgdb_key():
    config = load_config()
    return config.get('sgdb_key') if config else None


def _get_steam_assets(appid):
    """
    Fetches the full asset manifest for a game via IStoreBrowseService.
    Returns a dict mapping asset name → full URL, or empty dict on failure.
    e.g. {'library_capsule_2x': 'https://...', 'library_hero': 'https://...', ...}
    """
    try:
        import urllib.parse
        params = urllib.parse.urlencode({'input_json': (
            f'{{"ids":[{{"appid":{appid}}}],"context":{{"language":"english",'
            f'"country_code":"US","steam_realm":1}},"data_request":{{"include_assets":true}}}}'
        )})
        res = requests.get(
            f'https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?{params}',
            timeout=8
        )
        if res.status_code != 200:
            return {}
        items = res.json().get('response', {}).get('store_items', [])
        if not items:
            return {}
        assets = items[0].get('assets', {})
        fmt = assets.get('asset_url_format', '')
        if not fmt:
            return {}
        base = f'https://shared.fastly.steamstatic.com/store_item_assets/{fmt}'
        result = {}
        for key, val in assets.items():
            if key in ('asset_url_format',) or not isinstance(val, str):
                continue
            result[key] = base.replace('${FILENAME}', val)
        return result
    except Exception as e:
        log.warning(f"_get_steam_assets {appid}: {e}")
        return {}


def _sgdb_get(endpoint, sgdb_key):
    """Makes a SteamGridDB API request. Returns parsed JSON or None."""
    try:
        res = requests.get(
            f'https://www.steamgriddb.com/api/v2/{endpoint}',
            headers={'Authorization': f'Bearer {sgdb_key}'},
            timeout=5
        )
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        log.warning(f"_sgdb_get {endpoint}: {e}")
    return None


def _sgdb_search_game_id(name):
    """Search SteamGridDB for a game by name. Returns SGDB game ID (int) or None."""
    sgdb_key = _get_sgdb_key()
    if not sgdb_key or not name:
        return None
    try:
        data = _sgdb_get(f'search/autocomplete/{url_quote(name)}', sgdb_key)
        if data and data.get('success') and data.get('data'):
            return data['data'][0]['id']
    except Exception as e:
        log.warning(f"_sgdb_search_game_id {name!r}: {e}")
    return None


def _steam_search_appid(name):
    """Search the Steam store for a game by name. Returns Steam appid (int) or None."""
    try:
        res = requests.get(
            'https://store.steampowered.com/api/storesearch/',
            params={'term': name, 'l': 'english', 'cc': 'US'},
            timeout=5
        )
        if res.status_code == 200:
            items = res.json().get('items', [])
            if items:
                return items[0]['id']
    except Exception as e:
        log.warning(f"_steam_search_appid {name!r}: {e}")
    return None


def download_vertical(appid, assets=None, source='auto', sgdb_id=None, game_name=None):
    """
    Downloads vertical capsule art for a game.
    source: 'auto' (Steam → SGDB fallback), 'steam' (Steam only), 'sgdb' (SGDB only)
    Pass pre-fetched assets dict to avoid a redundant API call.
    Pass sgdb_id for non-Steam games to query SGDB by its game ID instead of Steam appid.
    Pass game_name to enable Steam CDN fallback when SGDB has no images.
    """
    _ensure_dirs()
    save_path = os.path.join(VERTICAL_DIR, f'{appid}.jpg')
    sgdb_key  = _get_sgdb_key()

    if source != 'sgdb' and not sgdb_id:
        # 1. Asset manifest (covers new games with content-hash URLs)
        if assets is None:
            assets = _get_steam_assets(appid)
        for key in ('library_capsule_2x', 'library_capsule'):
            url = assets.get(key)
            if url:
                try:
                    res = requests.get(url, timeout=5)
                    if res.status_code == 200 and save_as_jpg(res.content, save_path):
                        return 'capsule_2x' if '2x' in key else 'capsule'
                except Exception as e:
                    log.warning(f"download_vertical: asset manifest error for {appid}: {e}")

        # 2. Legacy CDN (older games without content-hash URLs)
        for url, cdn_source in [
            (f'https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg', 'capsule_2x'),
            (f'https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg',    'capsule'),
        ]:
            try:
                res = requests.get(url, timeout=5)
                if res.status_code == 200 and save_as_jpg(res.content, save_path):
                    return cdn_source
            except Exception as e:
                log.warning(f"download_vertical: CDN error for {appid}: {e}")

    if source != 'steam':
        # 3. SteamGridDB grid — fetch all, filter to portrait orientation client-side
        # (SGDB returns 400 for ?dimensions=600x900,1200x1800)
        if sgdb_key:
            endpoint = f'grids/game/{sgdb_id}' if sgdb_id else f'grids/steam/{appid}'
            data = _sgdb_get(endpoint, sgdb_key)
            if data and data.get('success') and data.get('data'):
                for item in data['data']:
                    if item.get('animated'):
                        continue
                    w, h = item.get('width', 0), item.get('height', 0)
                    if w and h and w >= h:  # skip landscape/square grids
                        continue
                    try:
                        img_res = requests.get(item['url'], timeout=5)
                        if img_res.status_code == 200 and save_as_jpg(img_res.content, save_path):
                            return 'sgdb_grid'
                    except Exception as e:
                        log.warning(f"download_vertical: SGDB grid download error for {appid}: {e}")
                    break

    # 4. Steam CDN fallback for non-Steam games — find matching Steam appid by name
    if game_name:
        steam_appid = _steam_search_appid(game_name)
        if steam_appid:
            steam_assets = _get_steam_assets(steam_appid)
            for key in ('library_capsule_2x', 'library_capsule'):
                url = steam_assets.get(key)
                if url:
                    try:
                        res = requests.get(url, timeout=5)
                        if res.status_code == 200 and save_as_jpg(res.content, save_path):
                            return 'capsule_2x_steam' if '2x' in key else 'capsule_steam'
                    except Exception as e:
                        log.warning(f"download_vertical: Steam fallback asset error for {appid}: {e}")
            for url, cdn_source in [
                (f'https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_appid}/library_600x900_2x.jpg', 'capsule_2x_steam'),
                (f'https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_appid}/library_600x900.jpg',    'capsule_steam'),
            ]:
                try:
                    res = requests.get(url, timeout=5)
                    if res.status_code == 200 and save_as_jpg(res.content, save_path):
                        return cdn_source
                except Exception as e:
                    log.warning(f"download_vertical: Steam fallback CDN error for {appid}: {e}")

    return 'missing'


def download_horizontal(appid, assets=None, source='auto', sgdb_id=None, game_name=None):
    """
    Downloads horizontal header art for a game.
    source: 'auto' (Steam → SGDB fallback), 'steam' (Steam only), 'sgdb' (SGDB only)
    Pass pre-fetched assets dict to avoid a redundant API call.
    Pass sgdb_id for non-Steam games to query SGDB by its game ID instead of Steam appid.
    Pass game_name to enable Steam CDN fallback when SGDB has no images.
    """
    _ensure_dirs()
    save_path = os.path.join(HORIZONTAL_DIR, f'{appid}.jpg')
    sgdb_key  = _get_sgdb_key()

    if source != 'sgdb' and not sgdb_id:
        # 1. Asset manifest (covers new games with content-hash URLs)
        if assets is None:
            assets = _get_steam_assets(appid)
        url = assets.get('header_image') or assets.get('main_capsule')
        if url:
            try:
                res = requests.get(url, timeout=5)
                if res.status_code == 200 and save_as_jpg(res.content, save_path):
                    return 'header'
            except Exception as e:
                log.warning(f"download_horizontal: asset manifest error for {appid}: {e}")

        # 2. Legacy CDN fallback
        try:
            res = requests.get(
                f'https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg',
                timeout=5
            )
            if res.status_code == 200 and save_as_jpg(res.content, save_path):
                return 'header'
        except Exception as e:
            log.warning(f"download_horizontal: CDN error for {appid}: {e}")

    if source != 'steam':
        # 3. SteamGridDB wide grid (header style, non-animated)
        if sgdb_key:
            endpoint = (f'grids/game/{sgdb_id}?dimensions=460x215,920x430'
                        if sgdb_id else f'grids/steam/{appid}?dimensions=460x215,920x430')
            data = _sgdb_get(endpoint, sgdb_key)
            if data and data.get('success') and data.get('data'):
                for item in data['data']:
                    if item.get('animated'):
                        continue
                    try:
                        img_res = requests.get(item['url'], timeout=5)
                        if img_res.status_code == 200 and save_as_jpg(img_res.content, save_path):
                            return 'sgdb_grid_wide'
                    except Exception as e:
                        log.warning(f"download_horizontal: SGDB wide grid download error for {appid}: {e}")
                    break

    # 4. Steam CDN fallback for non-Steam games — find matching Steam appid by name
    if game_name:
        steam_appid = _steam_search_appid(game_name)
        if steam_appid:
            steam_assets = _get_steam_assets(steam_appid)
            url = steam_assets.get('header_image') or steam_assets.get('main_capsule')
            if url:
                try:
                    res = requests.get(url, timeout=5)
                    if res.status_code == 200 and save_as_jpg(res.content, save_path):
                        return 'header_steam'
                except Exception as e:
                    log.warning(f"download_horizontal: Steam fallback asset error for {appid}: {e}")
            try:
                res = requests.get(
                    f'https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_appid}/header.jpg',
                    timeout=5
                )
                if res.status_code == 200 and save_as_jpg(res.content, save_path):
                    return 'header_steam'
            except Exception as e:
                log.warning(f"download_horizontal: Steam fallback CDN error for {appid}: {e}")

    return 'missing'


def download_icon(appid, icon_hash, source='auto', sgdb_id=None, game_name=None):
    """
    Downloads the game icon.
    source: 'auto' (SGDB first, then Steam fallback), 'steam' (Steam only), 'sgdb' (SGDB only)
    icon_hash is required for Steam source; ignored for SGDB-only.
    Pass sgdb_id for non-Steam games to query SGDB by its game ID instead of Steam appid.
    Pass game_name to enable SGDB icon lookup via Steam appid when the SGDB game id yields nothing.
    """
    _ensure_dirs()
    save_path = os.path.join(ICONS_DIR, f'{appid}.jpg')
    sgdb_key  = _get_sgdb_key()

    if source != 'steam':
        # 1. SteamGridDB icon (higher quality, non-animated)
        if sgdb_key:
            endpoint = f'icons/game/{sgdb_id}' if sgdb_id else f'icons/steam/{appid}'
            data = _sgdb_get(endpoint, sgdb_key)
            if data and data.get('success') and data.get('data'):
                for item in data['data']:
                    if item.get('animated'):
                        continue
                    try:
                        img_res = requests.get(item['url'], timeout=5)
                        if img_res.status_code == 200 and save_as_jpg(img_res.content, save_path):
                            return 'sgdb_icon'
                    except Exception as e:
                        log.warning(f"download_icon: SGDB icon download error for {appid}: {e}")
                    break

    if source != 'sgdb' and icon_hash:
        # 2. Steam icon — try 2x first, fall back to standard
        base_url = f'https://media.steampowered.com/steamcommunity/public/images/apps/{appid}'
        for icon_url in (f'{base_url}/{icon_hash}_2x.jpg', f'{base_url}/{icon_hash}.jpg'):
            try:
                res = requests.get(icon_url, timeout=5)
                if res.status_code == 200 and save_as_jpg(res.content, save_path):
                    return 'steam'
            except Exception as e:
                log.warning(f"download_icon: Steam icon error for {appid}: {e}")
                break

    # 3. SGDB icon via Steam appid fallback for non-Steam games
    if game_name and sgdb_key:
        steam_appid = _steam_search_appid(game_name)
        if steam_appid:
            data = _sgdb_get(f'icons/steam/{steam_appid}', sgdb_key)
            if data and data.get('success') and data.get('data'):
                for item in data['data']:
                    if item.get('animated'):
                        continue
                    try:
                        img_res = requests.get(item['url'], timeout=5)
                        if img_res.status_code == 200 and save_as_jpg(img_res.content, save_path):
                            return 'sgdb_icon_steam'
                    except Exception as e:
                        log.warning(f"download_icon: SGDB icon via Steam fallback error for {appid}: {e}")
                    break

    return 'missing'


def download_from_url(appid, url, orientation):
    """
    Saves an image for the given orientation ('vertical', 'horizontal', or
    'icon') from a user-supplied source: an http(s) URL is downloaded, while
    a local filesystem path or file:// URL is read directly off disk.
    Returns 'custom' on success, 'missing' on failure.
    """
    _ensure_dirs()
    dir_map = {
        'vertical':   VERTICAL_DIR,
        'horizontal': HORIZONTAL_DIR,
        'icon':       ICONS_DIR,
    }
    save_dir = dir_map.get(orientation, VERTICAL_DIR)
    save_path = os.path.join(save_dir, f'{appid}.jpg')

    parsed = urlparse(url)
    if parsed.scheme in ('', 'file'):
        from utils import validate_user_path
        raw_path   = url2pathname(parsed.path) if parsed.scheme == 'file' else url
        local_path = validate_user_path(raw_path)
        log.info(f"download_from_url: {orientation} art for {appid} from local path {local_path}")
        if not local_path or not os.path.isfile(local_path):
            log.warning(f"download_from_url: local path not found for {appid}: {local_path}")
            return 'missing'
        try:
            with open(local_path, 'rb') as f:
                image_bytes = f.read()
            if save_as_jpg(image_bytes, save_path):
                return 'custom'
        except Exception as e:
            log.warning(f"download_from_url: local read failed for {appid}: {e}")
        return 'missing'

    log.info(f"download_from_url: {orientation} art for {appid} from {url}")
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200 and save_as_jpg(res.content, save_path):
            return 'custom'
        log.warning(f"download_from_url: HTTP {res.status_code} for {appid}")
    except Exception as e:
        log.warning(f"download_from_url: exception for {appid}: {e}")
    return 'missing'


def fetch_sgdb_options(appid, artwork_type):
    """
    Fetches available artwork options from SteamGridDB without downloading.
    artwork_type: 'vertical', 'horizontal', or 'icon'
    Returns a list of {url, thumb, width, height} dicts (non-animated only),
    or an empty list if no key configured or request fails.
    """
    sgdb_key = _get_sgdb_key()
    if not sgdb_key:
        return []

    endpoint_map = {
        'vertical':   f'grids/steam/{appid}',
        'horizontal': f'grids/steam/{appid}?dimensions=460x215,920x430',
        'icon':       f'icons/steam/{appid}',
    }
    endpoint = endpoint_map.get(artwork_type)
    if not endpoint:
        return []

    data = _sgdb_get(endpoint, sgdb_key)
    if not data or not data.get('success') or not data.get('data'):
        return []

    results = []
    for item in data['data']:
        if item.get('animated'):
            continue
        results.append({
            'url':    item.get('url', ''),
            'thumb':  item.get('thumb', ''),
            'width':  item.get('width', 0),
            'height': item.get('height', 0),
        })
    return results


def search_sgdb_games(term):
    """
    Searches SteamGridDB for games matching a name.
    Returns a list of {id, name, verified} dicts, or empty list on failure.
    """
    sgdb_key = _get_sgdb_key()
    if not sgdb_key or not term:
        return []
    data = _sgdb_get(f'search/autocomplete/{url_quote(term)}', sgdb_key)
    if not data or not data.get('success') or not data.get('data'):
        return []
    return [
        {'id': g['id'], 'name': g['name'], 'verified': g.get('verified', False)}
        for g in data['data']
    ]


def fetch_sgdb_options_by_id(sgdb_id, artwork_type):
    """
    Fetches artwork options from SteamGridDB using a SGDB game ID.
    Used when the Steam appid lookup returns no results.
    """
    sgdb_key = _get_sgdb_key()
    if not sgdb_key:
        return []

    endpoint_map = {
        'vertical':   f'grids/game/{sgdb_id}',
        'horizontal': f'grids/game/{sgdb_id}?dimensions=460x215,920x430',
        'icon':       f'icons/game/{sgdb_id}',
    }
    endpoint = endpoint_map.get(artwork_type)
    if not endpoint:
        return []

    data = _sgdb_get(endpoint, sgdb_key)
    if not data or not data.get('success') or not data.get('data'):
        return []

    results = []
    for item in data['data']:
        if item.get('animated'):
            continue
        results.append({
            'url':    item.get('url', ''),
            'thumb':  item.get('thumb', ''),
            'width':  item.get('width', 0),
            'height': item.get('height', 0),
        })
    return results


# ── Routes ───────────────────────────────────────────────────────────────────

@images_bp.route('/api/download-artwork/<int:appid>', methods=['POST'])
def download_artwork(appid):
    from database import update_game_data
    data        = request.json or {}
    url         = data.get('url', '').strip()
    orientation = data.get('orientation', 'vertical')
    if not url:
        return jsonify({"status": "error", "message": "No URL or file path provided"}), 400
    if orientation not in ('vertical', 'horizontal', 'icon'):
        return jsonify({"status": "error", "message": "Invalid orientation"}), 400
    result = download_from_url(appid, url, orientation)
    if result == 'custom':
        col_map = {
            'vertical':   'vertical_art_source',
            'horizontal': 'horizontal_art_source',
            'icon':       'icon_source',
        }
        sgdb_source_map = {
            'vertical':   'sgdb_grid',
            'horizontal': 'sgdb_grid_wide',
            'icon':       'sgdb_icon',
        }
        _u = urlparse(url)
        source = sgdb_source_map[orientation] if (_u.hostname and (_u.hostname == 'steamgriddb.com' or _u.hostname.endswith('.steamgriddb.com'))) else 'custom'
        update_game_data(appid, **{col_map[orientation]: source})
        return jsonify({"status": "success", "source": source})
    return jsonify({"status": "error", "message": "Failed to load image. Check the URL or file path and try again."}), 500

@images_bp.route('/api/sgdb-options/<int:appid>/<artwork_type>')
def sgdb_options(appid, artwork_type):
    if artwork_type not in ('vertical', 'horizontal', 'icon'):
        return jsonify({"status": "error", "message": "Invalid artwork type"}), 400
    options = fetch_sgdb_options(appid, artwork_type)
    return jsonify({"status": "success", "options": options})

@images_bp.route('/api/sgdb-search')
def sgdb_search():
    term = request.args.get('term', '').strip()
    if not term:
        return jsonify({"status": "error", "message": "No search term"}), 400
    results = search_sgdb_games(term)
    return jsonify({"status": "success", "results": results})

@images_bp.route('/api/sgdb-options-by-id/<int:sgdb_id>/<artwork_type>')
def sgdb_options_by_id(sgdb_id, artwork_type):
    if artwork_type not in ('vertical', 'horizontal', 'icon'):
        return jsonify({"status": "error", "message": "Invalid artwork type"}), 400
    options = fetch_sgdb_options_by_id(sgdb_id, artwork_type)
    return jsonify({"status": "success", "options": options})

@images_bp.route('/api/artwork/save-sgdb', methods=['POST'])
def save_sgdb_artwork(appid=None):
    from database import update_game_data
    data        = request.json or {}
    appid       = data.get('appid')
    url         = data.get('url', '').strip()
    orientation = data.get('orientation')
    if not appid or not url or orientation not in ('vertical', 'horizontal', 'icon'):
        return jsonify({"status": "error", "message": "Missing or invalid parameters"}), 400
    col_map = {
        'vertical':   'vertical_art_source',
        'horizontal': 'horizontal_art_source',
        'icon':       'icon_source',
    }
    source_map = {
        'vertical':   'sgdb_grid',
        'horizontal': 'sgdb_grid_wide',
        'icon':       'sgdb_icon',
    }
    result = download_from_url(int(appid), url, orientation)
    if result == 'custom':
        update_game_data(int(appid), **{col_map[orientation]: source_map[orientation]})
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Failed to download image."}), 500

@images_bp.route('/api/artwork/clear', methods=['POST'])
def clear_artwork():
    from database import update_game_data
    data        = request.json or {}
    appid       = data.get('appid')
    orientation = data.get('orientation')
    if not appid or orientation not in ('vertical', 'horizontal', 'icon'):
        return jsonify({'status': 'error', 'message': 'Missing or invalid parameters'}), 400
    appid   = int(appid)
    dir_map = {'vertical': 'vertical', 'horizontal': 'horizontal', 'icon': 'icons'}
    path    = os.path.join(BASE_DIR, 'static', 'img', 'library', dir_map[orientation], f'{appid}.jpg')
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    src_col = {'vertical': 'vertical_art_source', 'horizontal': 'horizontal_art_source', 'icon': 'icon_source'}
    update_game_data(appid, **{src_col[orientation]: None})
    return jsonify({'status': 'success'})

@images_bp.route('/api/artwork/rescrape', methods=['POST'])
def rescrape_artwork():
    from database import update_game_data, get_db
    from datetime import datetime
    data        = request.json or {}
    appid       = data.get('appid')
    orientation = data.get('orientation')
    if not appid or orientation not in ('vertical', 'horizontal', 'icon'):
        return jsonify({"status": "error", "message": "Missing or invalid parameters"}), 400
    appid = int(appid)
    today = datetime.now().strftime('%Y-%m-%d')
    db    = get_db()
    row   = db.execute("SELECT name, icon_hash FROM games WHERE appid = ?", (appid,)).fetchone()
    db.close()
    is_non_steam = appid < 0
    game_name    = (row['name'] if row else None) if is_non_steam else None
    sgdb_id      = _sgdb_search_game_id(game_name) if game_name else None
    if orientation == 'vertical':
        source = download_vertical(appid, sgdb_id=sgdb_id, game_name=game_name)
        update_game_data(appid, vertical_art_source=source, art_fetched=today)
    elif orientation == 'horizontal':
        source = download_horizontal(appid, sgdb_id=sgdb_id, game_name=game_name)
        update_game_data(appid, horizontal_art_source=source, art_fetched=today)
    else:
        icon_hash = row['icon_hash'] if row else None
        source = download_icon(appid, icon_hash, sgdb_id=sgdb_id, game_name=game_name)
        update_game_data(appid, icon_source=source, art_fetched=today)
    return jsonify({"status": "success", "source": source})

@images_bp.route('/api/protondb/<int:appid>', methods=['POST'])
def rescrape_protondb(appid):
    from database import update_game_data
    from scrapers import fetch_protondb_data
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    info  = fetch_protondb_data(appid)
    game_data = {'protondb_fetched': today}
    if info:
        game_data.update(info)
    else:
        game_data['protondb_tier']       = None
        game_data['protondb_confidence'] = None
    update_game_data(appid, **game_data)
    return jsonify({'status': 'success', 'tier': info.get('protondb_tier') if info else None,
                    'confidence': info.get('protondb_confidence') if info else None})

# ── Card badge icons ────────────────────────────────────────────────────────
# User-uploaded, not bundled -- avoids shipping trademarked platform logos.
# One icon for 'installed'; one per platform value for 'platform'.

def _save_badge_icon_bytes(kind, data, platform_id=None):
    """Shared core for both upload paths below. Returns the new filename, or
    None on a decode/processing failure."""
    os.makedirs(BADGES_DIR, exist_ok=True)
    import time
    filename = f"{platform_id if kind == 'platform' else 'installed'}_{int(time.time() * 1000)}.png"
    save_path = os.path.join(BADGES_DIR, filename)
    if not save_badge_icon(data, save_path):
        return None

    from config import _state_lock, _load_state_unlocked, _write_state_atomic
    with _state_lock:
        state = _load_state_unlocked()
        badges = state.setdefault('card_badges', {})
        icons = badges.setdefault('icons', {'installed': None, 'platform': {}})
        if kind == 'installed':
            old = icons.get('installed')
            icons['installed'] = filename
        else:
            old = icons.setdefault('platform', {}).get(platform_id)
            icons['platform'][platform_id] = filename
        _write_state_atomic(state)
    if old and old != filename:
        try:
            os.remove(os.path.join(BADGES_DIR, old))
        except OSError:
            pass
    return filename

def _upload_badge_icon(kind, platform_id=None):
    """Browser-mode path: a real multipart file upload."""
    if 'icon' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file uploaded.'}), 400
    f = request.files['icon']
    if not f.filename:
        return jsonify({'status': 'error', 'message': 'Empty filename.'}), 400
    data = f.read()
    if len(data) > BADGE_UPLOAD_MAX_BYTES:
        return jsonify({'status': 'error', 'message': 'File too large (max 5MB).'}), 400
    filename = _save_badge_icon_bytes(kind, data, platform_id)
    if not filename:
        return jsonify({'status': 'error', 'message': 'Could not process image.'}), 400
    return jsonify({'status': 'success', 'filename': filename})

def _upload_badge_icon_from_path(kind, platform_id=None):
    """pywebview-mode path: window.pywebview.api.pick_open_path() returns a
    local file path rather than a File object -- input[type=file].click()
    triggered from a gamepad button press doesn't open the native dialog in
    pywebview, so the frontend calls this route instead when that API is
    available (see chooseBgFile() for the established pattern)."""
    from utils import validate_user_path
    body = request.get_json(force=True) or {}
    path = validate_user_path((body.get('path') or '').strip())
    if not path or not os.path.isfile(path):
        return jsonify({'status': 'error', 'message': 'File not found.'}), 400
    if os.path.getsize(path) > BADGE_UPLOAD_MAX_BYTES:
        return jsonify({'status': 'error', 'message': 'File too large (max 5MB).'}), 400
    with open(path, 'rb') as fh:
        data = fh.read()
    filename = _save_badge_icon_bytes(kind, data, platform_id)
    if not filename:
        return jsonify({'status': 'error', 'message': 'Could not process image.'}), 400
    return jsonify({'status': 'success', 'filename': filename})

def _clear_badge_icon(kind, platform_id=None):
    from config import _state_lock, _load_state_unlocked, _write_state_atomic
    with _state_lock:
        state = _load_state_unlocked()
        badges = state.setdefault('card_badges', {})
        icons = badges.setdefault('icons', {'installed': None, 'platform': {}})
        if kind == 'installed':
            old = icons.get('installed')
            icons['installed'] = None
        else:
            old = icons.setdefault('platform', {}).pop(platform_id, None)
        _write_state_atomic(state)
    if old:
        try:
            os.remove(os.path.join(BADGES_DIR, old))
        except OSError:
            pass
    return jsonify({'status': 'success'})

@images_bp.route('/api/badge-icon/installed', methods=['POST'])
def upload_badge_icon_installed():
    return _upload_badge_icon('installed')

@images_bp.route('/api/badge-icon/installed/from-path', methods=['POST'])
def upload_badge_icon_installed_from_path():
    return _upload_badge_icon_from_path('installed')

@images_bp.route('/api/badge-icon/installed/clear', methods=['POST'])
def clear_badge_icon_installed():
    return _clear_badge_icon('installed')

@images_bp.route('/api/badge-icon/platform/<platform_id>', methods=['POST'])
def upload_badge_icon_platform(platform_id):
    import re
    if not re.match(r'^[a-z][a-z0-9_]*$', platform_id or ''):
        return jsonify({'status': 'error', 'message': 'Invalid platform id.'}), 400
    return _upload_badge_icon('platform', platform_id)

@images_bp.route('/api/badge-icon/platform/<platform_id>/from-path', methods=['POST'])
def upload_badge_icon_platform_from_path(platform_id):
    import re
    if not re.match(r'^[a-z][a-z0-9_]*$', platform_id or ''):
        return jsonify({'status': 'error', 'message': 'Invalid platform id.'}), 400
    return _upload_badge_icon_from_path('platform', platform_id)

@images_bp.route('/api/badge-icon/platform/<platform_id>/clear', methods=['POST'])
def clear_badge_icon_platform(platform_id):
    import re
    if not re.match(r'^[a-z][a-z0-9_]*$', platform_id or ''):
        return jsonify({'status': 'error', 'message': 'Invalid platform id.'}), 400
    return _clear_badge_icon('platform', platform_id)
