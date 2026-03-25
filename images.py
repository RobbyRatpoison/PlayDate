import os
import io
import requests
from urllib.parse import quote as url_quote
from PIL import Image
from config import BASE_DIR, load_config
from flask import Blueprint

images_bp = Blueprint('images', __name__)

LIBRARY_DIR    = os.path.join(BASE_DIR, 'static', 'img', 'library')
VERTICAL_DIR   = os.path.join(LIBRARY_DIR, 'vertical')
HORIZONTAL_DIR = os.path.join(LIBRARY_DIR, 'horizontal')
ICONS_DIR      = os.path.join(LIBRARY_DIR, 'icons')


def _ensure_dirs():
    for d in (VERTICAL_DIR, HORIZONTAL_DIR, ICONS_DIR):
        os.makedirs(d, exist_ok=True)


def save_as_jpg(image_bytes, save_path):
    """
    Converts any image format (PNG, WEBP, etc.) to JPG and saves it.
    Returns True on success, False on failure.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        img.save(save_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"[save_as_jpg] Conversion failed: {e}")
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
        print(f"[_get_steam_assets] {appid}: {e}")
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
        print(f"[_sgdb_get] {endpoint}: {e}")
    return None


def download_vertical(appid, assets=None, source='auto'):
    """
    Downloads vertical capsule art for a game.
    source: 'auto' (Steam → SGDB fallback), 'steam' (Steam only), 'sgdb' (SGDB only)
    Pass pre-fetched assets dict to avoid a redundant API call.
    """
    _ensure_dirs()
    save_path = os.path.join(VERTICAL_DIR, f'{appid}.jpg')
    sgdb_key  = _get_sgdb_key()

    if source != 'sgdb':
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
                    print(f"[download_vertical] asset manifest error for {appid}: {e}")

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
                print(f"[download_vertical] CDN error for {appid}: {e}")

    if source != 'steam':
        # 3. SteamGridDB grid — fetch all, filter to portrait orientation client-side
        # (SGDB returns 400 for ?dimensions=600x900,1200x1800)
        if sgdb_key:
            data = _sgdb_get(f'grids/steam/{appid}', sgdb_key)
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
                        print(f"[download_vertical] SGDB grid download error for {appid}: {e}")
                    break

    return 'missing'


def download_horizontal(appid, assets=None, source='auto'):
    """
    Downloads horizontal header art for a game.
    source: 'auto' (Steam → SGDB fallback), 'steam' (Steam only), 'sgdb' (SGDB only)
    Pass pre-fetched assets dict to avoid a redundant API call.
    """
    _ensure_dirs()
    save_path = os.path.join(HORIZONTAL_DIR, f'{appid}.jpg')
    sgdb_key  = _get_sgdb_key()

    if source != 'sgdb':
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
                print(f"[download_horizontal] asset manifest error for {appid}: {e}")

        # 2. Legacy CDN fallback
        try:
            res = requests.get(
                f'https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg',
                timeout=5
            )
            if res.status_code == 200 and save_as_jpg(res.content, save_path):
                return 'header'
        except Exception as e:
            print(f"[download_horizontal] CDN error for {appid}: {e}")

    if source != 'steam':
        # 3. SteamGridDB wide grid (header style, non-animated)
        if sgdb_key:
            data = _sgdb_get(f'grids/steam/{appid}?dimensions=460x215,920x430', sgdb_key)
            if data and data.get('success') and data.get('data'):
                for item in data['data']:
                    if item.get('animated'):
                        continue
                    try:
                        img_res = requests.get(item['url'], timeout=5)
                        if img_res.status_code == 200 and save_as_jpg(img_res.content, save_path):
                            return 'sgdb_grid_wide'
                    except Exception as e:
                        print(f"[download_horizontal] SGDB wide grid download error for {appid}: {e}")
                    break

    return 'missing'


def download_icon(appid, icon_hash, source='auto'):
    """
    Downloads the game icon.
    source: 'auto' (SGDB first, then Steam fallback), 'steam' (Steam only), 'sgdb' (SGDB only)
    icon_hash is required for Steam source; ignored for SGDB-only.
    """
    _ensure_dirs()
    save_path = os.path.join(ICONS_DIR, f'{appid}.jpg')
    sgdb_key  = _get_sgdb_key()

    if source != 'steam':
        # 1. SteamGridDB icon (higher quality, non-animated)
        if sgdb_key:
            data = _sgdb_get(f'icons/steam/{appid}', sgdb_key)
            if data and data.get('success') and data.get('data'):
                for item in data['data']:
                    if item.get('animated'):
                        continue
                    try:
                        img_res = requests.get(item['url'], timeout=5)
                        if img_res.status_code == 200 and save_as_jpg(img_res.content, save_path):
                            return 'sgdb_icon'
                    except Exception as e:
                        print(f"[download_icon] SGDB icon download error for {appid}: {e}")
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
                print(f"[download_icon] Steam icon error for {appid}: {e}")
                break

    return 'missing'


def download_from_url(appid, url, orientation):
    """
    Downloads an image from a user-supplied URL and saves it for the given
    orientation ('vertical', 'horizontal', or 'icon').
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

    print(f"[download_from_url] Downloading {orientation} art for {appid} from: {url}")
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200 and save_as_jpg(res.content, save_path):
            return 'custom'
        print(f"[download_from_url] Failed: HTTP {res.status_code}")
    except Exception as e:
        print(f"[download_from_url] Exception for {appid}: {e}")
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
