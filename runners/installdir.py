"""
runners/installdir.py — Shared configurable install-directory helper for
plugins that download/extract games directly (GOG, Humble, itch.io,
IndieGala, ...). Each plugin still stores its own setting under its own
config.json[plugin_id] namespace ('games_dir' key) -- this just provides
the shared get/set/open logic and Flask route registration so the same
"Set Folder" / "Open Folder" pattern (originally IndieGala's) isn't
reimplemented per plugin.
"""

import logging
import os
import subprocess
import sys

from config import load_config, _save_config_data

log = logging.getLogger(__name__)


def get_install_dir(plugin_id, default_dir):
    return (load_config() or {}).get(plugin_id, {}).get('games_dir') or default_dir


def set_install_dir(plugin_id, path):
    cfg = load_config() or {}
    cfg.setdefault(plugin_id, {})['games_dir'] = path
    _save_config_data(cfg)


def check_writable(path):
    """
    Raise RuntimeError if path isn't actually writable -- creates it first
    if it doesn't exist. Does a real write (a temp probe file), not just
    os.access(), since os.access() can be misleading on some filesystems
    (network mounts, permission bits that don't reflect actual effective
    access). Callers should check this both when a user picks a folder
    (immediate feedback beats a failure partway through a download) and
    again right before a download starts (the folder could have become
    unwritable since it was picked -- permissions changed, drive unmounted).
    """
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        log.warning('check_writable: cannot create %r: %s', path, e)
        raise RuntimeError('That folder could not be created.')
    probe = os.path.join(path, '.playdate_write_test')
    try:
        with open(probe, 'wb') as f:
            f.write(b'x')
    except OSError as e:
        log.warning('check_writable: %r not writable: %s', path, e)
        raise RuntimeError('That folder is not writable.')
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass


def open_folder(path):
    """Open path in the OS file manager, creating it first if needed."""
    os.makedirs(path, exist_ok=True)
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])


def register_install_dir_routes(bp, plugin_id, default_dir, on_change=None):
    """
    Register GET/POST /games-dir, GET /games-dir-info, and POST
    /open-folder on the given blueprint. Call once from the plugin's
    routes.py. on_change(path), if given, is called after a successful
    POST /games-dir (e.g. to restart a filesystem watcher on the new path).
    """
    from flask import jsonify, request

    def _get_games_dir():
        return jsonify({'path': get_install_dir(plugin_id, default_dir)})

    def _games_dir_info():
        return jsonify({'text': get_install_dir(plugin_id, default_dir)})

    def _set_games_dir():
        path = ((request.get_json(silent=True) or {}).get('path') or '').strip()
        if not path:
            return jsonify({'error': 'No path provided'}), 400
        try:
            check_writable(path)
        except RuntimeError:
            # check_writable already logged the OS error; keep the response
            # to a fixed, non-revealing message.
            return jsonify({'error': 'That folder cannot be used — pick one that '
                                     'exists and is writable.'}), 400
        set_install_dir(plugin_id, path)
        if on_change:
            on_change(path)
        return jsonify({'status': 'ok', 'path': path})

    def _open_folder_route():
        open_folder(get_install_dir(plugin_id, default_dir))
        return jsonify({'status': 'ok'})

    bp.add_url_rule('/games-dir', endpoint=f'{plugin_id}_get_games_dir',
                     view_func=_get_games_dir, methods=['GET'])
    bp.add_url_rule('/games-dir-info', endpoint=f'{plugin_id}_games_dir_info',
                     view_func=_games_dir_info, methods=['GET'])
    bp.add_url_rule('/games-dir', endpoint=f'{plugin_id}_set_games_dir',
                     view_func=_set_games_dir, methods=['POST'])
    bp.add_url_rule('/open-folder', endpoint=f'{plugin_id}_open_folder',
                     view_func=_open_folder_route, methods=['POST'])
