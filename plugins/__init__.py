import importlib
import json
import logging
import os
import re
import time

from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

plugins_bp = Blueprint('plugins', __name__)

_plugins: dict = {}
_fragment_map: dict = {}
_fragment_abs: dict = {}   # slot -> list of absolute file paths (for JS slots)
_plugin_paths: dict = {}
_plugin_manifests: dict = {}

_plugin_update_cache = {}    # keyed by plugin_id: {update_available, latest_version, source, checked_at, error}
_launcher_status_cache = {}  # keyed by platform: {available, detail, checked_at}


def _parse_github_repo(url):
    """Return (owner, repo) from a GitHub URL or 'owner/repo' slug, or (None, None)."""
    url = url.strip().rstrip('/')
    m = re.match(r'(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/?#]+)', url)
    if m:
        return m.group(1), m.group(2).removesuffix('.git')
    m = re.match(r'^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$', url)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _fetch_github_plugin_release(owner, repo):
    """Return (zip_url, tag_name) for the latest release. zip_url may be a release asset or zipball."""
    import requests as _req
    resp = _req.get(
        f'https://api.github.com/repos/{owner}/{repo}/releases/latest',
        headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'PlayDate-App'},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    tag = data.get('tag_name', '?')
    for asset in data.get('assets', []):
        if asset.get('name', '').lower().endswith('.zip'):
            return asset['browser_download_url'], tag
    return data.get('zipball_url'), tag


def _install_plugin_zip(raw_bytes):
    """
    Validate and extract a plugin from raw zip bytes.
    Returns (plugin_id, plugin_name). Raises ValueError with a user-facing message on failure.
    """
    import zipfile, io, json as _json
    buf = io.BytesIO(raw_bytes)
    try:
        zf_obj = zipfile.ZipFile(buf, 'r')
    except zipfile.BadZipFile:
        raise ValueError('File is not a valid zip archive.')
    with zf_obj as zf:
        names = zf.namelist()
        if 'plugin.json' in names:
            prefix = ''
        else:
            top_dirs = {n.split('/')[0] for n in names if '/' in n}
            prefix = None
            for d in top_dirs:
                if f'{d}/plugin.json' in names:
                    prefix = d + '/'
                    break
            if prefix is None:
                raise ValueError('Invalid plugin zip: no plugin.json found.')

        manifest = _json.loads(zf.read(f'{prefix}plugin.json'))
        plugin_id = manifest.get('id', '').strip()
        if not plugin_id or not plugin_id.replace('_', '').isalnum():
            raise ValueError('Invalid or missing plugin id in plugin.json.')

        plugins_dir = os.path.dirname(os.path.abspath(__file__))
        dest = os.path.join(plugins_dir, plugin_id)
        if not os.path.abspath(dest).startswith(os.path.abspath(plugins_dir) + os.sep):
            raise ValueError('Invalid plugin id.')

        os.makedirs(dest, exist_ok=True)
        for member in names:
            if not member.startswith(prefix):
                continue
            rel = member[len(prefix):]
            if not rel:
                continue
            member_dest = os.path.join(dest, rel)
            if not os.path.abspath(member_dest).startswith(os.path.abspath(dest) + os.sep) \
                    and os.path.abspath(member_dest) != os.path.abspath(dest):
                continue
            if member.endswith('/'):
                os.makedirs(member_dest, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(member_dest), exist_ok=True)
                with zf.open(member) as src, open(member_dest, 'wb') as dst:
                    dst.write(src.read())

    return plugin_id, manifest.get('name', plugin_id)


def _startup_launcher_status_check():
    time.sleep(3)
    for p in loaded().values():
        if not hasattr(p, 'launcher_status'):
            continue
        try:
            result = p.launcher_status()
            result['checked_at'] = time.time()
            _launcher_status_cache[p.platform] = result
        except Exception as e:
            log.warning(f"launcher_status failed for {p.platform}: {e}")
            _launcher_status_cache[p.platform] = {'available': False, 'detail': str(e), 'checked_at': time.time()}


def load_all(app):
    """Discover and register all plugins found in this directory."""
    plugins_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(plugins_dir):
        return
    for entry in sorted(os.listdir(plugins_dir)):
        plugin_path    = os.path.join(plugins_dir, entry)
        manifest_path  = os.path.join(plugin_path, 'plugin.json')
        if not os.path.isdir(plugin_path) or not os.path.exists(manifest_path):
            continue
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            mod    = importlib.import_module(f'plugins.{entry}')
            p      = mod.plugin
            p.register(app)
            _plugins[p.id]          = p
            _plugin_paths[p.id]     = plugin_path
            _plugin_manifests[p.id] = manifest
            if hasattr(p, 'fragments'):
                tpl_dir = os.path.join(plugin_path, 'templates')
                for slot, tpl in p.fragments().items():
                    _fragment_map.setdefault(slot, []).append(tpl)
                    abs_path = os.path.join(tpl_dir, tpl)
                    _fragment_abs.setdefault(slot, []).append(abs_path)
            log.info(f"Loaded plugin: {manifest.get('name', entry)} v{manifest.get('version', '?')}")
        except Exception as e:
            log.error(f"Plugin load failed: {entry} — {e}", exc_info=True)


def get(plugin_id: str):
    return _plugins.get(plugin_id)


def loaded() -> dict:
    return dict(_plugins)


def has(plugin_id: str) -> bool:
    return plugin_id in _plugins


def fragments(slot: str) -> list:
    return _fragment_map.get(slot, [])


def fragment_js(slot: str) -> str:
    """Return combined JS content for a slot, stripping any <script> wrappers.

    Plugins that mistakenly wrap their tools_scripts content in <script> tags
    still work; a warning is logged so the author can fix it.
    """
    parts = []
    for path in _fragment_abs.get(slot, []):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            if re.search(r'<script[\s>]', content, re.IGNORECASE):
                plugin_name = os.path.basename(os.path.dirname(os.path.dirname(path)))
                log.warning(
                    f"Plugin '{plugin_name}': {os.path.basename(path)} contains <script> tags "
                    f"but is included inside an existing script block — tags stripped automatically. "
                    f"Remove <script>/<\/script> from the template to silence this warning."
                )
                content = re.sub(r'</?script[^>]*>', '', content, flags=re.IGNORECASE)
            parts.append(content)
        except Exception as e:
            log.error(f"fragment_js: could not read {path}: {e}")
    return '\n'.join(parts)


# Platforms without a plugin yet; overridden if a plugin claims the same key.
_CORE_PLATFORM_LABELS = {
    'steam':       'Steam',
    'epic_games':  'Epic Games',
    'ea_app':      'EA App',
    'ubisoft':     'Ubisoft',
}


def plugin_path(plugin_id: str) -> str | None:
    return _plugin_paths.get(plugin_id)


def plugin_manifest(plugin_id: str) -> dict:
    return _plugin_manifests.get(plugin_id, {})


def plugin_js_api() -> dict:
    """Return JS API descriptors for all plugins that provide them."""
    return {p.platform: p.js_api() for p in _plugins.values() if hasattr(p, 'js_api')}


def platform_labels() -> dict:
    """Return display labels for all known platforms (core + plugins + emulation)."""
    from known_emulators import PLATFORM_NAMES
    labels = dict(_CORE_PLATFORM_LABELS)
    labels.update(PLATFORM_NAMES)
    for p in _plugins.values():
        labels[p.platform] = getattr(p, 'label', p.name)
    return labels


def get_platform_priority() -> list:
    """Return the full duplicate-detection priority list.

    Merges the user's saved order with the hardcoded default, then appends
    any registered plugin platforms not already present. This ensures:
    - User's custom ordering is respected
    - Newly installed plugins are included at lowest priority automatically
    """
    from database import PLATFORM_PRIORITY_DEFAULT
    try:
        from config import load_state
        saved = load_state().get('platform_priority') or []
    except Exception:
        saved = []
    base   = saved + [p for p in PLATFORM_PRIORITY_DEFAULT if p not in saved]
    result = list(base)
    for p in _plugins.values():
        if p.platform not in result:
            result.append(p.platform)
    return result


# ── Routes ───────────────────────────────────────────────────────────────────

@plugins_bp.route('/api/plugins')
def list_plugins():
    from database import get_db
    db = get_db()
    result = []
    for pid, p in loaded().items():
        manifest = plugin_manifest(pid)
        row = db.execute(
            'SELECT COUNT(*) FROM games WHERE platform = ?', (p.platform,)
        ).fetchone()
        result.append({
            'id':         pid,
            'name':       p.name,
            'version':    manifest.get('version', '?'),
            'platform':   p.platform,
            'game_count': row[0] if row else 0,
            'source':     manifest.get('source', ''),
            'launcher':   manifest.get('launcher', {}),
            'manage_ui':  p.manage_ui() if hasattr(p, 'manage_ui') else None,
        })
    return jsonify(result)

@plugins_bp.route('/api/plugins/install', methods=['POST'])
def install_plugin():
    if 'plugin_file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file uploaded.'}), 400
    f = request.files['plugin_file']
    if not f.filename.lower().endswith('.zip'):
        return jsonify({'status': 'error', 'message': 'File must be a .zip archive.'}), 400
    try:
        plugin_id, name = _install_plugin_zip(f.read())
        return jsonify({'status': 'success', 'plugin_id': plugin_id, 'name': name})
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    except Exception as e:
        log.error(f"Plugin install failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@plugins_bp.route('/api/plugins/install-from-github', methods=['POST'])
def install_plugin_from_github():
    import requests as _req
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'status': 'error', 'message': 'No URL provided.'}), 400
    raw_url = url.removeprefix('github:')
    owner, repo = _parse_github_repo(raw_url)
    if not owner:
        return jsonify({'status': 'error', 'message': 'Could not parse a GitHub owner/repo from that URL.'}), 400
    try:
        zip_url, tag = _fetch_github_plugin_release(owner, repo)
        if not zip_url:
            return jsonify({'status': 'error', 'message': 'No downloadable zip found in the latest release.'}), 400
        resp = _req.get(zip_url, timeout=60)
        resp.raise_for_status()
        plugin_id, name = _install_plugin_zip(resp.content)
        _plugin_update_cache.pop(plugin_id, None)
        return jsonify({'status': 'success', 'plugin_id': plugin_id, 'name': name, 'tag': tag})
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    except Exception as e:
        log.error(f"Plugin install from GitHub failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@plugins_bp.route('/api/plugins/check-updates')
def check_plugin_updates():
    import concurrent.futures

    TTL = 6 * 3600

    def _check_one(pid):
        manifest = plugin_manifest(pid)
        source = manifest.get('source', '')
        if not source:
            return None
        raw_url = source.removeprefix('github:')
        owner, repo = _parse_github_repo(raw_url)
        if not owner:
            return {'id': pid, 'source': source, 'update_available': False, 'latest_version': None, 'error': 'Invalid source in plugin.json'}

        cached = _plugin_update_cache.get(pid, {})
        if cached.get('checked_at') and (time.time() - cached['checked_at']) < TTL:
            return {'id': pid, 'source': source, **{k: cached[k] for k in ('update_available', 'latest_version', 'error')}}

        try:
            _, tag = _fetch_github_plugin_release(owner, repo)
            latest = tag.lstrip('v')
            installed = manifest.get('version', '0')

            def _semver(v):
                try:
                    return tuple(int(x) for x in v.split('.'))
                except Exception:
                    return (0, 0, 0)

            available = _semver(latest) > _semver(installed)
            entry = {
                'update_available': available,
                'latest_version': latest,
                'error': None,
                'checked_at': time.time(),
            }
            _plugin_update_cache[pid] = entry
            return {'id': pid, 'source': source, 'update_available': available, 'latest_version': latest, 'error': None}
        except Exception as e:
            entry = {'update_available': False, 'latest_version': None, 'error': str(e), 'checked_at': time.time()}
            _plugin_update_cache[pid] = entry
            return {'id': pid, 'source': source, 'update_available': False, 'latest_version': None, 'error': str(e)}

    pids = list(loaded().keys())
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(_check_one, pid) for pid in pids]
        for fut in concurrent.futures.as_completed(futures, timeout=15):
            try:
                r = fut.result()
                if r:
                    results.append(r)
            except Exception:
                pass

    return jsonify(results)

@plugins_bp.route('/api/plugins/launcher-status', methods=['GET'])
def get_launcher_status():
    return jsonify(_launcher_status_cache)

@plugins_bp.route('/api/plugins/launcher-status/<platform_id>', methods=['POST'])
def recheck_launcher_status(platform_id):
    plugin_obj = next(
        (p for p in loaded().values() if p.platform == platform_id),
        None,
    )
    if not plugin_obj or not hasattr(plugin_obj, 'launcher_status'):
        return jsonify({'status': 'error', 'message': 'Plugin not found or does not support launcher_status'}), 404
    try:
        result = plugin_obj.launcher_status()
        result['checked_at'] = time.time()
        _launcher_status_cache[platform_id] = result
        return jsonify({'status': 'success', 'launcher_status': result})
    except Exception as e:
        log.error(f"launcher_status failed for {platform_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@plugins_bp.route('/api/plugins/<plugin_id>/uninstall', methods=['POST'])
def uninstall_plugin(plugin_id):
    import shutil
    p = get(plugin_id)
    if not p:
        return jsonify({'status': 'error', 'message': 'Plugin not found'}), 404
    path = plugin_path(plugin_id)
    if not path or not os.path.isdir(path):
        return jsonify({'status': 'error', 'message': 'Plugin folder not found'}), 404
    data = request.get_json(silent=True) or {}
    try:
        if hasattr(p, 'on_uninstall'):
            p.on_uninstall()
        if data.get('remove_games'):
            from database import get_db
            db = get_db()
            db.execute('DELETE FROM games WHERE platform = ?', (p.platform,))
            db.commit()
        if data.get('remove_launcher'):
            from config import get_launcher_config
            lc = get_launcher_config(p.platform)
            prefix = lc.get('prefix', '').strip()
            if prefix:
                prefix_path = os.path.expanduser(prefix)
                # Safety: must be absolute, exist as a dir, and have enough depth
                if (os.path.isabs(prefix_path) and
                        os.path.isdir(prefix_path) and
                        len(prefix_path.strip('/').split('/')) >= 2):
                    shutil.rmtree(prefix_path, ignore_errors=True)
        # Always clean up launcher config entry
        try:
            from config import load_config, _save_config_data
            cfg = load_config()
            if cfg and 'launchers' in cfg and p.platform in cfg['launchers']:
                del cfg['launchers'][p.platform]
                _save_config_data(cfg)
        except Exception:
            pass
        shutil.rmtree(path)
        return jsonify({'status': 'success'})
    except Exception as e:
        log.error(f"Plugin uninstall failed: {plugin_id} — {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500
