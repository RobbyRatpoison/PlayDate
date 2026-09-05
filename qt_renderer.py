"""Optional Qt/QtWebEngine renderer (Linux, source installs only): on-demand
install of PyQt6 + PyQt6-WebEngine, background thread + polling in the same
shape as updater.py's self-update flow."""
import logging
import os
import platform
import subprocess
import sys
import threading

from flask import Blueprint, jsonify

from config import BASE_DIR, IN_FLATPAK, save_state

log = logging.getLogger(__name__)

qt_bp = Blueprint('qt_renderer', __name__)

_qt_install_state = {'status': 'idle', 'error': None}  # idle|installing|done|error


def _qt_toggle_available():
    return (not IN_FLATPAK
            and not getattr(sys, 'frozen', False)
            and platform.system() == 'Linux')


def _pip_cmd():
    venv_pip = os.path.join(BASE_DIR, '.venv', 'bin', 'pip')
    if os.path.exists(venv_pip):
        return [venv_pip]
    return [sys.executable, '-m', 'pip']


def _do_install():
    _qt_install_state.update({'status': 'installing', 'error': None})
    try:
        # --force-reinstall is required, not optional: this project's venv is
        # --system-site-packages (needed for the GTK/WebKit bindings), so on
        # a distro that already ships a system PyQt6 (e.g. Arch/CachyOS), a
        # plain "pip install pywebview[qt6]" sees PyQt6 as already satisfied
        # and only pulls PyQt6-WebEngine from PyPI -- which bundles its own,
        # separately-built Qt6 libraries. Mixing distro-linked PyQt6 core
        # with a PyPI-wheel QtWebEngine is an ABI mismatch that crashes
        # (confirmed live: SIGTRAP deep inside QWebEngineProfile's
        # constructor, with no Python-level exception at all) the instant
        # QtWebEngine is used. Forcing a matching PyQt6 wheel into the venv's
        # own site-packages (which take priority over the system ones) fixes
        # it -- both PyQt6 core and PyQt6-WebEngine then come from the same
        # build family.
        result = subprocess.run(
            _pip_cmd() + ['install', '--force-reinstall', 'PyQt6', 'PyQt6-WebEngine', 'QtPy'],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            log.error(f"qt_renderer install: pip failed: {result.stderr.strip()}")
            _qt_install_state.update({'status': 'error', 'error': 'Install failed — see playdate.log.'})
            return

        probe = subprocess.run(
            [sys.executable, '-c', 'from qtpy.QtWebEngineWidgets import QWebEngineView'],
            capture_output=True, text=True, timeout=60,
        )
        if probe.returncode != 0:
            log.error(f"qt_renderer install: import probe failed: {probe.stderr.strip()}")
            _qt_install_state.update({'status': 'error', 'error': 'Installed but failed to import — see playdate.log.'})
            return

        save_state({'renderer': 'qt'})
        _qt_install_state.update({'status': 'done', 'error': None})
    except Exception as e:
        log.error(f"qt_renderer install: {e}")
        _qt_install_state.update({'status': 'error', 'error': str(type(e).__name__)})


@qt_bp.route('/api/qt-renderer/install', methods=['POST'])
def install_qt_renderer():
    if not _qt_toggle_available():
        return jsonify({'status': 'error', 'message': 'Not available on this build.'}), 400
    if _qt_install_state['status'] == 'installing':
        return jsonify({'status': 'ok'})
    threading.Thread(target=_do_install, daemon=True).start()
    return jsonify({'status': 'ok'})


@qt_bp.route('/api/qt-renderer/status')
def qt_renderer_status():
    return jsonify(_qt_install_state)


@qt_bp.route('/api/qt-renderer/uninstall', methods=['POST'])
def uninstall_qt_renderer():
    save_state({'renderer': 'gtk'})
    _qt_install_state.update({'status': 'idle', 'error': None})
    return jsonify({'status': 'ok'})


def _other_flatpak_app_id(app_id):
    return app_id[:-len('.Qt')] if app_id.endswith('.Qt') else app_id + '.Qt'


def _fetch(url, dest):
    """Download url to dest, retrying without SSL verification on SSL
    errors (mirrors updater.py's own _fetch, kept local to avoid reaching
    into that module's perform_update() closure)."""
    import ssl
    import urllib.request
    try:
        urllib.request.urlretrieve(url, dest)
    except ssl.SSLError as exc:
        log.warning(f"SSL error downloading flatpak bundle ({exc}), retrying without verification")
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(url, context=ctx) as r, open(dest, 'wb') as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)


def _do_flatpak_swap():
    import shutil
    from runners.sandbox import host_run, host_popen
    from updater import _running_flatpak_app_id, _update_cache, _do_update_check

    _qt_install_state.update({'status': 'installing', 'error': None})
    try:
        own_app_id = _running_flatpak_app_id()
        other_app_id = _other_flatpak_app_id(own_app_id)

        # The swap-toggle is the only sanctioned way to switch variants, so
        # this always fetches fresh rather than trusting whatever the last
        # background update-check happened to cache.
        _do_update_check()
        bundle_url = _update_cache.get('flatpak_url_other_variant')
        if not bundle_url:
            _qt_install_state.update({'status': 'error', 'error': f'No release asset found for {other_app_id}.'})
            return

        bundle_path = os.path.join(BASE_DIR, 'playdate-renderer-swap.flatpak')
        log.info(f"Downloading {other_app_id} bundle: {bundle_url}")
        _fetch(bundle_url, bundle_path)

        # Data continuity: the two variants are separate Flatpak app-IDs, so
        # each gets its own isolated ~/.var/app/<id>/data by default. Copy
        # this variant's data across before switching -- overwrite semantics,
        # the variant being switched *from* wins. Both manifests already
        # grant --filesystem=home, so this process can read/write the other
        # app-ID's data dir directly. See
        # project_qtwebengine_rendering_investigation for why a shared path
        # was rejected in favor of this copy-on-switch approach.
        target_data_dir = os.path.expanduser(f'~/.var/app/{other_app_id}/data/playdate')
        log.info(f"Copying data dir {BASE_DIR} -> {target_data_dir}")
        os.makedirs(os.path.dirname(target_data_dir), exist_ok=True)
        if os.path.isdir(target_data_dir):
            shutil.rmtree(target_data_dir)
        shutil.copytree(BASE_DIR, target_data_dir)

        # Install into whichever scope this variant already lives in (same
        # logic as updater.py's self-update flow).
        user_check = host_run(['flatpak', 'info', '--user', own_app_id], capture_output=True, text=True)
        scope = '--user' if user_check.returncode == 0 else '--system'

        log.info(f"Installing {other_app_id} ({scope}): {bundle_path}")
        result = host_run(
            ['flatpak', 'install', scope, '-y', '--reinstall', bundle_path],
            capture_output=True, text=True
        )
        try:
            os.remove(bundle_path)
        except OSError:
            pass
        if result.returncode != 0:
            log.error(f"flatpak-swap: install failed: {result.stderr.strip()}")
            _qt_install_state.update({'status': 'error', 'error': f'flatpak install failed: {result.stderr.strip()}'})
            return

        _qt_install_state.update({'status': 'done', 'error': None})

        # Same Steam Deck Game Mode consideration as updater.py's self-update:
        # a bare `flatpak run` gets no window surface there, so ask Steam to
        # relaunch the shortcut instead when running under one.
        from config import _is_steam_deck_session
        _sgid = os.environ.get('SteamGameId', '')
        try:
            if _is_steam_deck_session() and _sgid.isdigit():
                host_popen(['sh', '-c', f'sleep 2; exec steam "steam://rungameid/{_sgid}"'],
                           start_new_session=True)
            else:
                host_popen(['flatpak', 'run', other_app_id], start_new_session=True)
        except Exception as re_err:
            log.warning(f"flatpak-swap: relaunch failed, user must reopen manually: {re_err}")
    except Exception as e:
        log.error(f"flatpak-swap failed: {e}", exc_info=True)
        _qt_install_state.update({'status': 'error', 'error': 'Switch failed. Check playdate.log for details.'})
        return
    os._exit(0)


@qt_bp.route('/api/qt-renderer/flatpak-swap', methods=['POST'])
def flatpak_swap_renderer():
    if not IN_FLATPAK:
        return jsonify({'status': 'error', 'message': 'Not available on this build.'}), 400
    if _qt_install_state['status'] == 'installing':
        return jsonify({'status': 'ok'})
    threading.Thread(target=_do_flatpak_swap, daemon=True).start()
    return jsonify({'status': 'ok'})
