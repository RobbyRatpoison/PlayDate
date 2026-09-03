"""Self-update: GitHub release polling and applying the update in place
(Windows installer download, Flatpak bundle reinstall, or source zip
extraction + pip install, depending on how PlayDate is running)."""
import logging
import os
import re
import subprocess
import sys
import threading
import time

from flask import Blueprint, jsonify

from config import BASE_DIR
from runners.sandbox import IN_FLATPAK, host_run, host_popen

log = logging.getLogger(__name__)

updater_bp = Blueprint('updater', __name__)

_update_cache = {}  # available, latest_version, installer_url, zipball_url, checked_at, error
_update_dl_state = {'status': 'idle', 'error': None, 'manual_url': None}  # idle|downloading|error


def _parse_build_version(v):
    """Parse 'X.Y.Z' or 'X.Y.Z-beta.N'/'X.Y.Z-rc.N' into (numeric_tuple, prerelease_num).
    prerelease_num is None for a final release, which ranks above any
    prerelease sharing the same numeric_tuple (so a real v1.6.5 beats
    1.6.5-beta.9, but 1.6.5-beta.2 still beats 1.6.5-beta.1)."""
    v = v.lstrip('v')
    base, _, suffix = v.partition('-')
    try:
        numeric = tuple(int(x) for x in base.split('.'))
    except ValueError:
        numeric = (0, 0, 0)
    if not suffix:
        return (numeric, None)
    m = re.search(r'(\d+)$', suffix)
    return (numeric, int(m.group(1)) if m else 0)


def _build_is_newer(a, b):
    """True if version/tag string a is newer than b (prerelease-aware)."""
    a_num, a_pre = _parse_build_version(a)
    b_num, b_pre = _parse_build_version(b)
    if a_num != b_num:
        return a_num > b_num
    if a_pre is None:
        return b_pre is not None
    if b_pre is None:
        return False
    return a_pre > b_pre


def _do_update_check():
    """Hit the GitHub releases API and populate _update_cache. Thread-safe."""
    from config import __build__, load_state
    try:
        import requests as _req
        if load_state().get('beta_updates', False):
            # Opted into beta: the plain /releases/latest endpoint always
            # excludes prereleases by GitHub's own definition, so beta/rc
            # builds need the full list instead — newest entry first.
            resp = _req.get(
                'https://api.github.com/repos/RobbyRatpoison/PlayDate-Library-Manager/releases',
                headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'PlayDate-App'},
                params={'per_page': 30},
                timeout=10
            )
            releases = resp.json()
            # GitHub's /releases list order is not reliably newest-first (its
            # index lags, and rewriting a tag's commit reshuffles it), so pick
            # the highest version explicitly rather than trusting releases[0].
            data = {}
            if isinstance(releases, list):
                best = None
                for r in releases:
                    # Skip a release whose CI build hasn't attached assets yet
                    # -- picking it would just fail the download.
                    if r.get('draft') or not r.get('assets'):
                        continue
                    tag = (r.get('tag_name') or '').lstrip('v')
                    if best is None or _build_is_newer(tag, best_tag):
                        best, best_tag = r, tag
                data = best or {}
        else:
            resp = _req.get(
                'https://api.github.com/repos/RobbyRatpoison/PlayDate-Library-Manager/releases/latest',
                headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'PlayDate-App'},
                timeout=10
            )
            data = resp.json()
        tag = data.get('tag_name', '')
        latest = tag.lstrip('v')
        available = _build_is_newer(latest, __build__)

        installer_url = None
        flatpak_url = None
        for asset in data.get('assets', []):
            name = asset.get('name', '').lower()
            if name.endswith('.exe'):
                installer_url = asset['browser_download_url']
            elif name.endswith('.flatpak'):
                flatpak_url = asset['browser_download_url']

        _update_cache.update({
            'available': available,
            'latest_version': latest,
            'installer_url': installer_url,
            'flatpak_url': flatpak_url,
            'zipball_url': data.get('zipball_url'),
            'checked_at': time.time(),
            'error': None
        })
        log.info(f"Update check: latest={latest}, current={__build__}, available={available}")
    except Exception as e:
        _update_cache.update({'available': False, 'checked_at': time.time(),
                              'error': 'Update check failed (network or GitHub error).'})
        log.warning(f"Update check failed: {e}")


def _startup_update_check():
    time.sleep(5)
    from config import load_state
    if load_state().get('check_for_updates', True):
        _do_update_check()


@updater_bp.route('/api/update-status')
def update_status():
    from config import load_state, __version__, IS_PORTABLE
    state = load_state()
    return jsonify({
        'current_version': __version__,
        'auto_check': state.get('check_for_updates', True),
        'beta_updates': state.get('beta_updates', False),
        'update_available': _update_cache.get('available', False),
        'latest_version': _update_cache.get('latest_version'),
        'checked': bool(_update_cache),
        'error': _update_cache.get('error'),
        'is_portable': IS_PORTABLE,
    })

@updater_bp.route('/api/check-update', methods=['POST'])
def check_update():
    from config import __version__, IS_PORTABLE
    _do_update_check()
    return jsonify({
        'update_available': _update_cache.get('available', False),
        'latest_version': _update_cache.get('latest_version'),
        'current_version': __version__,
        'error': _update_cache.get('error'),
        'is_portable': IS_PORTABLE,
    })

@updater_bp.route('/api/reset-update-cache', methods=['POST'])
def reset_update_cache():
    _update_cache.clear()
    return jsonify({'status': 'ok'})

@updater_bp.route('/api/perform-update', methods=['POST'])
def perform_update():
    from config import IS_PORTABLE
    if IS_PORTABLE:
        return jsonify({'status': 'error', 'message': 'Portable builds update manually — download the new zip from GitHub.'}), 400
    if not _update_cache.get('available'):
        return jsonify({'status': 'error', 'message': 'No update available'}), 400

    def _do_update():
        import tempfile, urllib.request, ssl
        time.sleep(0.5)  # let the HTTP response send first

        def _fetch(url, dest):
            """Download url to dest, retrying without SSL verification on SSL errors."""
            try:
                urllib.request.urlretrieve(url, dest)
            except ssl.SSLError as exc:
                log.warning(f"SSL error downloading update ({exc}), retrying without verification")
                ctx = ssl._create_unverified_context()
                with urllib.request.urlopen(url, context=ctx) as r, open(dest, 'wb') as f:
                    while True:
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)

        _update_dl_state['status'] = 'downloading'
        _update_dl_state['error'] = None
        try:
            if IN_FLATPAK:
                # Flatpak: download the new bundle under $HOME (a
                # flatpak-spawn --host process can't see the sandbox's
                # private /tmp), install it via the host's flatpak, then
                # relaunch. /app stays mounted to the old version for the
                # life of this process, so a fresh process is required.
                url = _update_cache.get('flatpak_url')
                if not url:
                    log.error("perform-update: no flatpak URL cached")
                    # Invalidate the cache — a missing asset URL usually means CI
                    # hadn't finished building it when we checked. Without this,
                    # "Go Back" (a page reload) re-reads the same stale cache and
                    # lands right back on "Install Update", replaying the same
                    # failure even after the asset shows up on GitHub.
                    _update_cache.clear()
                    _update_dl_state.update({'status': 'error', 'error': 'No flatpak bundle URL cached', 'manual_url': None})
                    return
                bundle_path = os.path.join(BASE_DIR, 'playdate-update.flatpak')
                log.info(f"Downloading flatpak bundle: {url}")
                _update_dl_state['manual_url'] = url
                _fetch(url, bundle_path)

                app_id = 'io.github.robbyratpoison.PlayDate'

                # Reinstall into whichever scope this install already
                # lives in, rather than always trying --user first. That
                # blind "--user, fall back to --system on failure" logic
                # could succeed at creating a brand new --user copy
                # alongside an existing --system one (or vice versa)
                # instead of updating the copy actually running — since
                # we're IN_FLATPAK right now, the app is guaranteed to be
                # installed in at least one of the two scopes already.
                user_check = host_run(['flatpak', 'info', '--user', app_id], capture_output=True, text=True)
                scope = '--user' if user_check.returncode == 0 else '--system'

                log.info(f"Installing flatpak bundle ({scope}): {bundle_path}")
                result = host_run(
                    ['flatpak', 'install', scope, '-y', '--reinstall', bundle_path],
                    capture_output=True, text=True
                )
                try:
                    os.remove(bundle_path)
                except OSError:
                    pass
                if result.returncode != 0:
                    log.error(f"perform-update: flatpak install failed: {result.stderr.strip()}")
                    _update_dl_state.update({'status': 'error', 'error': f'flatpak install failed: {result.stderr.strip()}'})
                    return

                # In Steam Deck Game Mode a bare `flatpak run` gets no window
                # surface -- gamescope only composites what Steam launched, so
                # the app would just vanish. Ask Steam to relaunch the shortcut
                # instead ($SteamGameId is the rungameid, set in the launched
                # env). Falls back to `flatpak run` off-Deck / if it's unset.
                from config import _is_steam_deck_session
                _sgid = os.environ.get('SteamGameId', '')
                try:
                    if _is_steam_deck_session() and _sgid.isdigit():
                        # `steam steam://rungameid/<id>` forwards to the running
                        # Steam and relaunches the shortcut. `xdg-open` for the
                        # same URL does NOT reach Steam from a flatpak-spawn
                        # --host context (confirmed on a Deck) -- it goes
                        # through a desktop-file lookup that doesn't forward.
                        # The sleep lets this process fully exit first, so Steam
                        # doesn't see the shortcut as still-running and no-op.
                        log.info("Relaunching via Steam (rungameid %s)", _sgid)
                        host_popen(['sh', '-c', f'sleep 2; exec steam "steam://rungameid/{_sgid}"'],
                                   start_new_session=True)
                    else:
                        log.info("Relaunching via flatpak run")
                        host_popen(['flatpak', 'run', app_id], start_new_session=True)
                except Exception as _re:
                    # The update itself is already installed -- a relaunch
                    # hiccup shouldn't report the whole thing as failed.
                    log.warning("perform-update: relaunch failed, user must reopen manually: %s", _re)
            elif getattr(sys, 'frozen', False):
                # Windows frozen exe: download installer and launch it
                url = _update_cache.get('installer_url')
                if not url:
                    log.error("perform-update: no installer URL cached")
                    _update_cache.clear()  # see flatpak branch above for why
                    _update_dl_state.update({'status': 'error', 'error': 'No installer URL cached', 'manual_url': None})
                    return
                tmp = os.path.join(tempfile.gettempdir(), 'PlayDate-Setup.exe')
                log.info(f"Downloading installer: {url}")
                _update_dl_state['manual_url'] = url
                _fetch(url, tmp)
                log.info(f"Launching installer: {tmp}")
                subprocess.Popen(
                    [tmp],
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                # Linux/macOS from source: download zip, extract over BASE_DIR, pip, restart
                import zipfile
                url = _update_cache.get('zipball_url')
                if not url:
                    log.error("perform-update: no zipball URL cached")
                    _update_cache.clear()  # see flatpak branch above for why
                    _update_dl_state.update({'status': 'error', 'error': 'No zipball URL cached', 'manual_url': None})
                    return
                tmp_zip = os.path.join(tempfile.gettempdir(), 'playdate-update.zip')
                log.info(f"Downloading source zip: {url}")
                _update_dl_state['manual_url'] = url
                _fetch(url, tmp_zip)
                log.info(f"Extracting to {BASE_DIR}")
                with zipfile.ZipFile(tmp_zip) as zf:
                    members = zf.namelist()
                    prefix = members[0].split('/')[0] + '/' if members else ''
                    for member in members:
                        rel = member[len(prefix):]
                        if not rel:
                            continue
                        target = os.path.join(BASE_DIR, rel)
                        if member.endswith('/'):
                            os.makedirs(target, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(target), exist_ok=True)
                            with zf.open(member) as src, open(target, 'wb') as dst:
                                dst.write(src.read())

                venv_pip = os.path.join(BASE_DIR, '.venv', 'bin', 'pip')
                if os.path.exists(venv_pip):
                    log.info("Running pip install -r requirements.txt")
                    subprocess.run(
                        [venv_pip, 'install', '-r', os.path.join(BASE_DIR, 'requirements.txt')],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )

                launcher = os.path.join(BASE_DIR, 'playdate-launch.sh')
                if os.path.exists(launcher):
                    subprocess.Popen([launcher], start_new_session=True)
                else:
                    subprocess.Popen(
                        [sys.executable, os.path.join(BASE_DIR, 'main.py')],
                        start_new_session=True
                    )
        except Exception as e:
            log.error(f"perform-update failed: {e}", exc_info=True)
            _update_dl_state.update({'status': 'error',
                                    'error': 'Update failed. Check playdate.log for details.'})
            return
        os._exit(0)

    threading.Thread(target=_do_update, daemon=True).start()
    return jsonify({'status': 'ok'})

@updater_bp.route('/api/update-dl-status')
def update_dl_status():
    return jsonify(_update_dl_state)
