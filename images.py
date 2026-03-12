import os
import io
import requests
from PIL import Image
from config import BASE_DIR, load_config
from flask import Blueprint

images_bp = Blueprint('images', __name__)
LOCAL_COVERS_DIR = os.path.join(BASE_DIR, "static/img/library")

def save_as_jpg(image_bytes, save_path):
    """
    Converts any image format (PNG, WEBP, etc.) to JPG and saves it.
    Returns True on success, False on failure.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Convert to RGB — necessary for PNG/WEBP which may have alpha channels
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        img.save(save_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"[save_as_jpg] Conversion failed: {e}")
        return False

def download_from_url(appid, url):
    """
    Downloads an image from a user-supplied URL, converts to JPG,
    and saves it as the game's capsule.
    Returns "custom" on success, "error" on failure.
    """
    if not os.path.exists(LOCAL_COVERS_DIR):
        os.makedirs(LOCAL_COVERS_DIR)

    print(f"[download_from_url] Downloading artwork for {appid} from: {url}")

    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            save_path = os.path.join(LOCAL_COVERS_DIR, f"{appid}.jpg")
            print(f"[download_from_url] Saving to: {save_path}")

            if save_as_jpg(res.content, save_path):
                print(f"[download_from_url] Success! Saved as JPG.")
                return "custom"
            else:
                return "error"
        else:
            print(f"[download_from_url] Failed: HTTP {res.status_code}")
            return "error"
    except Exception as e:
        print(f"[download_from_url] Exception for {appid}: {e}")
        return "error"

def download_capsule(appid):
    config = load_config()
    if not config:
        return "error"
    sgdb_key = config.get('sgdb_key')

    if not os.path.exists(LOCAL_COVERS_DIR):
        os.makedirs(LOCAL_COVERS_DIR)

    save_path = os.path.join(LOCAL_COVERS_DIR, f"{appid}.jpg")

    # 1. Primary: Steam Vertical Capsule
    steam_capsule_url = f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg"

    try:
        res = requests.get(steam_capsule_url, timeout=5)
        if res.status_code == 200:
            if save_as_jpg(res.content, save_path):
                return "capsule"

        # 2. Secondary: SteamGridDB
        if sgdb_key:
            sgdb_url = f"https://www.steamgriddb.com/api/v2/grids/steam/{appid}?dimensions=600x900"
            headers = {'Authorization': f'Bearer {sgdb_key}'}
            sgdb_res = requests.get(sgdb_url, headers=headers, timeout=5)
            if sgdb_res.status_code == 200:
                sgdb_data = sgdb_res.json()
                if sgdb_data.get('success') and sgdb_data.get('data'):
                    img_url = sgdb_data['data'][0]['url']
                    img_res = requests.get(img_url, timeout=5)
                    if img_res.status_code == 200:
                        if save_as_jpg(img_res.content, save_path):
                            return "sgdb_capsule"

        # 3. Tertiary Fallback: Steam Header
        steam_header_url = f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
        res = requests.get(steam_header_url, timeout=5)
        if res.status_code == 200:
            if save_as_jpg(res.content, save_path):
                return "header"

        return "missing"

    except Exception as e:
        print(f"Error in image chain for {appid}: {e}")
        return "error"
