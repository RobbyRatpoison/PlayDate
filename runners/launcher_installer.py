"""
runners/launcher_installer.py - Generic Wine-based launcher installer for plugins.

Plugins declare an installer in plugin.json under launcher.installer:
    {
        "url": "https://...",
        "type": "msi" | "exe",
        "winearch": "win64" | "win32"   (default: win64)
    }

exe_name is taken from launcher.exe_name (used to verify success).
prefix/wine_bin come from the user via the UI (defaults applied by caller).
"""

import logging
import os
import subprocess
import tempfile
import threading

import requests

log = logging.getLogger(__name__)

_states: dict = {}
_lock = threading.Lock()

_DEFAULT_PREFIX_BASE = os.path.join(os.path.expanduser('~'), '.local', 'share', 'PlayDate')


def default_prefix(platform_id: str) -> str:
    return os.path.join(_DEFAULT_PREFIX_BASE, platform_id)


def get_state(platform_id: str) -> dict:
    with _lock:
        return dict(_states.get(platform_id, {}))


def start_install(platform_id: str, installer_cfg: dict, prefix: str, wine_bin: str | None = None) -> bool:
    """
    Start a background launcher install. Returns False if one is already running.
    installer_cfg keys: url, type ('msi'/'exe'), winearch, exe_name
    """
    with _lock:
        state = _states.get(platform_id, {})
        if state.get('phase') and not state.get('done') and not state.get('error'):
            return False
        _states[platform_id] = {
            'phase': 'starting', 'detail': 'Starting...', 'done': False, 'error': None,
        }
    threading.Thread(
        target=_run_install,
        args=(platform_id, installer_cfg, prefix, wine_bin),
        daemon=True,
    ).start()
    return True


def _set(platform_id, phase, detail):
    with _lock:
        _states[platform_id].update({'phase': phase, 'detail': detail})


def _fail(platform_id, msg):
    log.error('Launcher install [%s]: %s', platform_id, msg)
    with _lock:
        _states[platform_id].update({'phase': 'error', 'detail': msg, 'done': False, 'error': msg})


def _finish(platform_id, prefix, wine_bin):
    from config import save_launcher_config
    cfg = {'prefix': prefix, 'mode': 'wine'}
    if wine_bin:
        cfg['wine_bin'] = wine_bin
    save_launcher_config(platform_id, cfg)
    with _lock:
        _states[platform_id].update({
            'phase': 'done', 'detail': 'Launcher installed successfully.', 'done': True, 'error': None,
        })


def _run_install(platform_id: str, installer_cfg: dict, prefix: str, wine_bin: str | None):
    import shutil
    from runners.wine import find_wine_binary

    wb = wine_bin or find_wine_binary()
    if not wb:
        _fail(platform_id, 'No Wine binary found. Install Wine first.')
        return

    prefix = os.path.expanduser(prefix)
    winearch       = installer_cfg.get('winearch', 'win64')
    installer_type = installer_cfg.get('type', 'msi')
    url            = installer_cfg.get('url', '')
    exe_name       = installer_cfg.get('exe_name', '')

    if not url:
        _fail(platform_id, 'No installer URL configured for this plugin.')
        return

    # Step 1: Create Wine prefix
    _set(platform_id, 'creating_prefix', 'Creating Wine prefix...')
    try:
        os.makedirs(prefix, exist_ok=True)
        env = {**os.environ, 'WINEPREFIX': prefix, 'WINEARCH': winearch, 'WINEDEBUG': '-all'}
        subprocess.run(
            [wb, 'wineboot', '--init'],
            env=env, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        _fail(platform_id, f'Failed to create Wine prefix: {e}')
        return

    # Step 2: Download installer
    _set(platform_id, 'downloading', 'Downloading installer...')
    tmp_dir = tempfile.mkdtemp(prefix=f'playdate_{platform_id}_')
    ext = '.msi' if installer_type == 'msi' else '.exe'
    installer_path = os.path.join(tmp_dir, f'installer{ext}')
    try:
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        with open(installer_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _fail(platform_id, f'Download failed: {e}')
        return

    # Step 3: Run installer (user interacts with the Wine window)
    _set(platform_id, 'installing', 'Running installer — complete the setup window...')
    try:
        env = {**os.environ, 'WINEPREFIX': prefix, 'WINEDEBUG': '-all'}
        cmd = [wb, 'msiexec', '/i', installer_path] if installer_type == 'msi' else [wb, installer_path]
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.wait()
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _fail(platform_id, f'Installer error: {e}')
        return
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not exe_name:
        _finish(platform_id, prefix, wine_bin)
        return

    # Step 4: Verify exe_name appears somewhere in the prefix
    _set(platform_id, 'verifying', 'Verifying installation...')
    found = any(exe_name in files for _, _, files in os.walk(prefix))
    if not found:
        _fail(platform_id, f'{exe_name} not found after installation. Did the setup complete?')
        return

    _finish(platform_id, prefix, wine_bin)
