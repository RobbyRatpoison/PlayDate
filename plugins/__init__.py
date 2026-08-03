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

# Plugins whose plugin.json declares a min_core_version newer than this build --
# not imported/registered, just recorded here so the Plugins modal can explain
# why they're missing and still offer to remove the folder.
_incompatible_plugins: dict = {}

# Plugins that used to ship as source directly in this repo (plugins/<id>/).
# No longer bundled -- installed on first run (and re-offered any time after
# an uninstall) from their own GitHub release, the same mechanism any
# third-party plugin uses. This is what makes "uninstall" actually stick
# across a PlayDate update: there's no bundled copy left for an update to
# silently reintroduce.
OFFICIAL_PLUGINS = [
    {'id': 'ea_app',     'name': 'EA App',        'source': 'RobbyRatpoison/playdate-plugin-ea-app'},
    {'id': 'epic_games', 'name': 'Epic Games',    'source': 'RobbyRatpoison/playdate-plugin-epic-games'},
    {'id': 'gog',        'name': 'GOG',           'source': 'RobbyRatpoison/playdate-plugin-gog'},
    {'id': 'humble',     'name': 'Humble Bundle', 'source': 'RobbyRatpoison/playdate-plugin-humble'},
    {'id': 'indiegala',  'name': 'IndieGala',     'source': 'RobbyRatpoison/playdate-plugin-indiegala'},
    {'id': 'itch_io',    'name': 'itch.io',       'source': 'RobbyRatpoison/playdate-plugin-itch-io'},
]


def _user_plugins_dir() -> str:
    """
    Writable directory for installed plugins -- separate from the bundled
    plugins/ directory next to this file, which is read-only at runtime
    under Flatpak (and gets wholesale-replaced by every update on every
    platform). BASE_DIR already resolves correctly per-platform (Flatpak's
    XDG data dir, exe-adjacent for a frozen build, or the project dir when
    running from source), so reusing it here needs no platform-specific
    logic of its own.
    """
    from config import BASE_DIR
    d = os.path.join(BASE_DIR, 'plugins')
    os.makedirs(d, exist_ok=True)
    return d


def _migrate_legacy_plugin_dirs(bundled_dir: str, user_dir: str):
    """
    One-time, self-terminating migration: anything sitting directly in the
    bundled plugins/ directory -- a leftover of the old flat layout, where
    both shipped and user-installed plugins lived in the same place -- moves
    into the writable user_dir. Covers both a plugin that used to ship
    bundled (now removed from the repo, so an old checkout/install still has
    its files on disk) and a third-party plugin someone zip-installed before
    this split existed. Never raises; a failure here shouldn't block startup.
    """
    import shutil
    if os.path.abspath(bundled_dir) == os.path.abspath(user_dir):
        # Running from source: BASE_DIR is the project root, so the writable
        # dir and the bundled dir next to this file are literally the same
        # path. Nothing to migrate -- it's already "in" the writable location.
        return
    try:
        entries = os.listdir(bundled_dir)
    except OSError:
        return
    for entry in entries:
        src = os.path.join(bundled_dir, entry)
        if not os.path.isdir(src) or not os.path.exists(os.path.join(src, 'plugin.json')):
            continue
        dest = os.path.join(user_dir, entry)
        if os.path.exists(dest):
            log.warning(
                f"Plugin migration: {entry} already exists in the writable plugins "
                f"directory, leaving the old copy at {src} in place"
            )
            continue
        try:
            shutil.move(src, dest)
            log.info(f"Plugin migration: moved {entry} to the writable plugins directory")
        except Exception as e:
            log.warning(f"Plugin migration: failed to move {entry}: {e}")


def _plugin_on_disk(plugin_id: str) -> bool:
    """Check the filesystem directly, not the in-memory _plugins registry --
    this has to run before the first load_all() ever populates it."""
    for d in (_user_plugins_dir(), os.path.dirname(os.path.abspath(__file__))):
        if os.path.exists(os.path.join(d, plugin_id, 'plugin.json')):
            return True
    return False


def _plugin_was_configured(plugin_id: str) -> bool:
    """
    Evidence the user actually set this plugin up: a saved auth token
    (config.json[plugin_id]) or a launcher config entry
    (config.json['launchers'][plugin_id]). Both get cleared -- the token by
    the plugin's own on_uninstall(), the launcher entry by the uninstall
    route itself -- so this reads False again immediately after a real
    uninstall, not just whenever the plugin happens to be missing.
    Deliberately does not look at whether games exist for this platform:
    plugin uninstall doesn't delete games unless remove_games was explicitly
    requested, so leftover games alone don't mean the user still wants the
    plugin reinstalled.
    """
    from config import load_config
    cfg = load_config() or {}
    if cfg.get(plugin_id):
        return True
    if cfg.get('launchers', {}).get(plugin_id):
        return True
    return False


def reinstall_configured_official_plugins():
    """
    Re-fetch and reinstall any OFFICIAL_PLUGINS entry that's missing from
    disk but shows evidence of prior configuration (see
    _plugin_was_configured). This is the only case that actually needs
    fixing: Windows and source installs never lose an existing plugin's
    files across an update in the first place (neither update mechanism
    deletes files outside what it ships), so migration alone is enough for
    them. Flatpak is the exception -- `flatpak install --reinstall` swaps
    /app wholesale rather than leaving extra files alone, so an update can
    genuinely wipe a plugin someone already had working. Deliberately does
    NOT install a plugin nobody has ever configured -- that's what the
    Official Plugins catalog in the Plugins modal is for, on request, not
    automatically.

    Must run (and finish) before the first load_all()/register_blueprint --
    see the call site in app.py for why. Only ever does real network work
    for a plugin that's both missing AND previously configured; every other
    startup is a fast, local-only no-op.
    """
    import requests as _req
    for entry in OFFICIAL_PLUGINS:
        pid = entry['id']
        if _plugin_on_disk(pid) or not _plugin_was_configured(pid):
            continue
        owner, repo = _parse_github_repo(entry['source'])
        if not owner:
            continue
        try:
            zip_url, _tag = _fetch_github_plugin_release(owner, repo)
            if not zip_url:
                log.warning(f"Official plugin {entry['name']}: no downloadable release found")
                continue
            resp = _req.get(zip_url, timeout=15)
            resp.raise_for_status()
            _install_plugin_zip(resp.content)
            log.info(f"Reinstalled previously-configured official plugin: {entry['name']}")
        except _req.exceptions.ConnectionError as e:
            log.warning(f"Official plugin reinstall: no network connection, skipping the rest ({e})")
            break
        except Exception as e:
            log.warning(f"Could not reinstall official plugin {entry['name']}: {e}")


def _semver(v):
    """Parse 'X.Y.Z'-ish into a comparable tuple. Non-numeric/missing parts -> 0."""
    try:
        return tuple(int(x) for x in str(v).split('.'))
    except Exception:
        return (0, 0, 0)


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

        plugins_dir = _user_plugins_dir()
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
    """
    Discover and register plugins from the writable user-plugins directory
    and the bundled plugins/ directory next to this file (legacy layout --
    nothing ships there anymore, but a not-yet-migrated or manually-dropped-in
    plugin is still found). Safe to call more than once: anything already in
    _plugins is skipped, so a later call (after reinstall_configured_official_plugins()
    fetches something new) only registers what's actually new.
    """
    from config import __version__ as core_version

    bundled_dir = os.path.dirname(os.path.abspath(__file__))
    user_dir    = _user_plugins_dir()
    _migrate_legacy_plugin_dirs(bundled_dir, user_dir)

    # importlib.import_module('plugins.<id>') only finds a submodule inside
    # this package's own search path -- user_dir lives elsewhere entirely
    # (BASE_DIR, not next to this file), so it has to be added to __path__
    # for a plugin installed there to import at all, let alone resolve its
    # own relative imports (from . import X) correctly as a real submodule
    # of the plugins package rather than a standalone loose file.
    if user_dir not in __path__:
        __path__.append(user_dir)

    search_dirs = [user_dir] if user_dir == bundled_dir else [user_dir, bundled_dir]
    claimed = set()
    for plugins_dir in search_dirs:
        if not os.path.isdir(plugins_dir):
            continue
        for entry in sorted(os.listdir(plugins_dir)):
            if entry in claimed:
                continue  # already loaded from a higher-priority directory
            plugin_path    = os.path.join(plugins_dir, entry)
            manifest_path  = os.path.join(plugin_path, 'plugin.json')
            if not os.path.isdir(plugin_path) or not os.path.exists(manifest_path):
                continue
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)

                manifest_id = manifest.get('id', entry)
                claimed.add(entry)
                if manifest_id in _plugins:
                    continue

                min_core = manifest.get('min_core_version')
                if min_core and _semver(min_core) > _semver(core_version):
                    _incompatible_plugins[manifest_id] = {
                        'id':               manifest_id,
                        'name':             manifest.get('name', entry),
                        'version':          manifest.get('version', '?'),
                        'platform':         manifest.get('platform', ''),
                        'min_core_version': min_core,
                        'current_version':  core_version,
                    }
                    log.warning(
                        f"Plugin {manifest.get('name', entry)!r} needs PlayDate >= {min_core}, "
                        f"this build is {core_version} — not loaded"
                    )
                    continue

                mod    = importlib.import_module(f'plugins.{entry}')
                p      = mod.plugin
                p.register(app)
                _plugins[p.id]          = p
                _plugin_paths[p.id]     = plugin_path
                _plugin_manifests[p.id] = manifest
                _incompatible_plugins.pop(p.id, None)
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

@plugins_bp.route('/api/plugins/incompatible')
def list_incompatible_plugins():
    """Plugins present on disk but not loaded because plugin.json's min_core_version
    is newer than this build. Separate from /api/plugins so that endpoint's shape
    (loaded plugins only) stays stable for existing callers."""
    from database import get_db
    db = get_db()
    result = []
    for pid, entry in _incompatible_plugins.items():
        row = db.execute(
            'SELECT COUNT(*) FROM games WHERE platform = ?', (entry['platform'],)
        ).fetchone() if entry['platform'] else None
        result.append({**entry, 'game_count': row[0] if row else 0})
    db.close()
    return jsonify(result)

@plugins_bp.route('/api/plugins/official')
def list_official_plugins():
    """
    OFFICIAL_PLUGINS entries not currently loaded -- lets the Plugins modal
    offer a one-click install for someone trying one for the first time.
    This is separate from reinstall_configured_official_plugins() (which
    only runs automatically at startup, and only for a plugin with evidence
    of prior configuration): that covers "Flatpak wiped something you
    already had," this covers "I've never used this and want to try it."
    """
    return jsonify([e for e in OFFICIAL_PLUGINS if not has(e['id'])])

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
    p            = get(plugin_id)
    incompatible = _incompatible_plugins.get(plugin_id)
    if not p and not incompatible:
        return jsonify({'status': 'error', 'message': 'Plugin not found'}), 404
    # Incompatible plugins were never registered, so _plugin_paths has no entry --
    # fall back to checking both the writable and (legacy) bundled locations.
    path = plugin_path(plugin_id)
    if not path:
        for candidate_dir in (_user_plugins_dir(), os.path.dirname(os.path.abspath(__file__))):
            candidate = os.path.join(candidate_dir, plugin_id)
            if os.path.isdir(candidate):
                path = candidate
                break
    if not path or not os.path.isdir(path):
        return jsonify({'status': 'error', 'message': 'Plugin folder not found'}), 404
    platform = p.platform if p else incompatible.get('platform')
    data = request.get_json(silent=True) or {}
    try:
        if p and hasattr(p, 'on_uninstall'):
            p.on_uninstall()
        if data.get('remove_games') and platform:
            from database import get_db
            db = get_db()
            db.execute('DELETE FROM games WHERE platform = ?', (platform,))
            db.commit()
        if data.get('remove_launcher') and platform:
            from config import get_launcher_config
            lc = get_launcher_config(platform)
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
            if cfg and platform and 'launchers' in cfg and platform in cfg['launchers']:
                del cfg['launchers'][platform]
                _save_config_data(cfg)
        except Exception:
            pass
        shutil.rmtree(path)
        _plugins.pop(plugin_id, None)
        _plugin_paths.pop(plugin_id, None)
        _plugin_manifests.pop(plugin_id, None)
        _incompatible_plugins.pop(plugin_id, None)
        return jsonify({'status': 'success'})
    except Exception as e:
        log.error(f"Plugin uninstall failed: {plugin_id} — {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500
