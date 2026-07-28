"""
runners/proton.py — Detect and launch Proton for Windows GOG games.
"""

import glob
import logging
import os

from runners.sandbox import host_popen

log = logging.getLogger(__name__)

# Glob patterns for finding Proton installs.  Checked in order; first found wins
# for _get_default, but all are returned by find_proton_versions().
_PROTON_GLOBS = [
    # GE-Proton in both common Steam locations (prefer GE for better compatibility)
    '~/.local/share/Steam/compatibilitytools.d/GE-Proton*/proton',
    '~/.steam/steam/compatibilitytools.d/GE-Proton*/proton',
    # Official Proton
    '~/.steam/steam/steamapps/common/Proton */proton',
    '~/.local/share/Steam/steamapps/common/Proton */proton',
]


def find_proton_versions():
    """
    Return all installed Proton versions as a list of dicts:
        [{'name': str, 'path': str}]
    Sorted newest-first within each category (GE-Proton before official).
    """
    seen  = set()   # resolved real paths to avoid symlink duplicates
    found = []
    for pattern in _PROTON_GLOBS:
        for path in sorted(glob.glob(os.path.expanduser(pattern)), reverse=True):
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            name = os.path.basename(os.path.dirname(path))
            found.append({'name': name, 'path': path})
    return found


def get_default_proton():
    """
    Return the best available Proton dict, or None if nothing is installed.
    Prefers GE-Proton (first in _PROTON_GLOBS) for broader compatibility.
    """
    versions = find_proton_versions()
    return versions[0] if versions else None


def _find_steam_root(proton_path):
    """Walk up from proton_path until we find a directory that contains 'steamapps'."""
    d = os.path.dirname(os.path.abspath(proton_path))
    while d and d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, 'steamapps')):
            return d
        d = os.path.dirname(d)
    # Hard-coded fallback
    for candidate in ('~/.steam/steam', '~/.local/share/Steam'):
        expanded = os.path.expanduser(candidate)
        if os.path.isdir(expanded):
            return expanded
    return os.path.expanduser('~/.steam/steam')


def launch_game(install_path, executable, wine_prefix, proton_path=None, env_extra=None):
    """
    Launch a Windows game via Proton.

    install_path  : directory where the game is installed
    executable    : relative path to the .exe within install_path
    wine_prefix   : directory for the Wine/Proton prefix (created automatically if absent)
    proton_path   : absolute path to the 'proton' script; auto-detected if None
    env_extra     : dict of extra environment variables to set

    Returns the Popen object (caller should not wait — game runs in background).
    Raises RuntimeError if no Proton is found.
    """
    if proton_path is None:
        p = get_default_proton()
        if not p:
            raise RuntimeError(
                'No Proton installation found. '
                'Install Proton via Steam (Tools section) or GE-Proton.'
            )
        proton_path = p['path']

    os.makedirs(wine_prefix, exist_ok=True)

    steam_root = _find_steam_root(proton_path)
    env = dict(os.environ)
    env['STEAM_COMPAT_DATA_PATH']           = wine_prefix
    env['STEAM_COMPAT_CLIENT_INSTALL_PATH'] = steam_root
    if env_extra:
        env.update(env_extra)

    exe_abs = os.path.join(install_path, executable)
    cmd     = [proton_path, 'run', exe_abs]
    log.info(f'Proton launch: {cmd[0]} run {executable}  (prefix={wine_prefix})')
    return host_popen(cmd, env=env, cwd=install_path)
