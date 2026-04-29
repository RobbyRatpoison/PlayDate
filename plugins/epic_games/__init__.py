import logging
import os
import sys
import time

log = logging.getLogger(__name__)


def _find_native_launcher():
    """Return path to EpicGamesLauncher executable on Windows/Mac, or None."""
    if sys.platform == 'win32':
        candidates = []
        for env in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432'):
            base = os.environ.get(env, '')
            if base:
                candidates.append(os.path.join(
                    base, 'Epic Games', 'Launcher', 'Portal', 'Binaries', 'Win64',
                    'EpicGamesLauncher.exe'))
                candidates.append(os.path.join(
                    base, 'Epic Games', 'Launcher', 'Portal', 'Binaries', 'Win32',
                    'EpicGamesLauncher.exe'))
        for path in candidates:
            if os.path.isfile(path):
                return path
    elif sys.platform == 'darwin':
        candidate = '/Applications/Epic Games Launcher.app/Contents/MacOS/EpicGamesLauncher'
        if os.path.isfile(candidate):
            return candidate
    return None


class EpicGamesPlugin:
    id       = 'epic_games'
    name     = 'Epic Games'
    platform = 'epic_games'
    label    = 'Epic Games'

    def register(self, app):
        from .routes import bp
        app.register_blueprint(bp)
        log.info('Epic Games plugin registered')

    def on_startup(self):
        from .watcher import (start_epic_watcher, start_periodic_sync,
                               sync_epic_install_status, _get_install_base)
        try:
            sync_epic_install_status()
            log.info('Epic install status synced on startup')
        except Exception as e:
            log.warning(f'Startup Epic install sync failed: {e}')
        start_periodic_sync()
        # File watcher only needed on Linux (Wine prefix); native platforms handle their own events
        if sys.platform not in ('win32', 'darwin'):
            install_base = _get_install_base()
            if install_base:
                start_epic_watcher(install_base)

    def on_shutdown(self):
        from .watcher import stop_epic_watcher, stop_periodic_sync
        stop_periodic_sync()
        stop_epic_watcher()

    def on_uninstall(self):
        from .epic import clear_epic_tokens
        clear_epic_tokens()

    def launch_game(self, appid):
        import json
        from config import CONFIG_PATH
        from database import get_db
        from database import ts_to_date

        db  = get_db()
        row = db.execute(
            "SELECT platform_appname, platform_slug, installed FROM games WHERE appid = ?", (appid,)
        ).fetchone()
        db.close()

        if not row:
            return {'status': 'error', 'message': 'Epic game not found'}

        # platform_appname is the launch identifier; fall back to platform_slug for records
        # synced before the platform_appname column was added
        slug = (row['platform_appname'] or row['platform_slug'] or '').strip()
        if not slug:
            return {'status': 'error', 'message': 'Epic game has no app name — try re-syncing'}

        try:
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        launcher_cfg = cfg.get('launchers', {}).get('epic_games', {})
        prefix   = launcher_cfg.get('prefix', '').strip()
        wine_bin = launcher_cfg.get('wine_bin', '').strip() or None

        if row['installed']:
            url = f'com.epicgames.launcher://apps/{slug}?action=launch&silent=true'
        else:
            url = f'com.epicgames.launcher://apps/{slug}?action=install'
        try:
            if sys.platform == 'win32':
                os.startfile(url)
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.Popen(['open', url])
            else:  # Linux / Wine
                if not prefix:
                    return {
                        'status':  'error',
                        'message': 'Epic launcher not configured. Open Plugins → Manage to set up Wine.',
                    }
                from runners.wine import launch_protocol_url
                launch_protocol_url(prefix, url, wine_bin=wine_bin, env_extra={
                    'WINEDEBUG': '-all',
                    'WINEDLLOVERRIDES': 'winegstreamer=',
                })
        except RuntimeError as e:
            return {'status': 'error', 'message': str(e)}
        except Exception as e:
            return {'status': 'error', 'message': f'Launch failed: {e}'}

        if row['installed']:
            now_ts = int(time.time())
            from database import update_game_data
            update_game_data(appid, last_played=now_ts)
            return {'status': 'success', 'last_played': ts_to_date(now_ts)}

        return {'status': 'success'}

    def launcher_status(self):
        import json
        from config import CONFIG_PATH

        # Native Windows/Mac: check for installed launcher directly
        if sys.platform in ('win32', 'darwin'):
            native = _find_native_launcher()
            if native:
                return {'available': True, 'detail': 'Launcher detected'}
            return {'available': False, 'detail': 'Epic Games Launcher not installed'}

        # Linux: require Wine + prefix with launcher installed
        try:
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        launcher_cfg = cfg.get('launchers', {}).get('epic_games', {})
        prefix   = launcher_cfg.get('prefix', '').strip()
        wine_bin = launcher_cfg.get('wine_bin', '').strip()

        from runners.wine import find_wine_binary
        if not wine_bin:
            wine_bin = find_wine_binary()

        if not wine_bin:
            return {'available': False, 'detail': 'No Wine binary found'}

        if not prefix:
            return {'available': False, 'detail': 'Wine prefix not configured'}

        if not os.path.isdir(prefix):
            return {'available': False, 'detail': f'Prefix not found: {prefix}'}

        for _dirpath, _dirs, files in os.walk(prefix):
            if 'EpicGamesLauncher.exe' in files:
                return {'available': True, 'detail': 'Launcher ready'}

        return {
            'available': False,
            'detail': 'EpicGamesLauncher.exe not found in prefix — install Epic launcher in Wine',
        }

    def js_api(self):
        native = sys.platform in ('win32', 'darwin')
        return {
            'uninstall_url':     None if native else '/api/epic_games/uninstall/{appid}',
            'uninstall_confirm': (
                'Uninstall this Epic game?\n\n'
                'Game files will be deleted. The game will remain in your PlayDate library.'
            ),
            'uninstall_native':  native,
            'scrape_url':    '/api/epic_games/scrape-single/{appid}',
            'scrape_method': 'POST',
            'store_url':     'https://store.epicgames.com/p/{slug}',
            'store_label':   'View on Epic Store ↗',
            'appid_label':   'Epic Catalog ID:',
            'sync_label':    'Sync Epic Data',
        }

    def manage_ui(self):
        native = _find_native_launcher()
        if native:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Epic Games Launcher is installed — no additional setup needed.'},
                ],
            }
        elif sys.platform in ('win32', 'darwin'):
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Epic Games Launcher is not installed.'},
                    {'type': 'button', 'label': 'Download Epic Games Launcher', 'action': {
                        'type': 'open_url', 'url': 'https://store.epicgames.com/en-US/download',
                    }},
                ],
            }
        else:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Set the Wine binary and prefix where Epic Games Launcher is installed.'},
                    {'type': 'launcher_config'},
                ],
            }

        return {
            'sections': [
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/epic_games/status',
                        'disconnected': [
                            {'type': 'text', 'content': 'Connect your Epic Games account to import your library.'},
                            {'type': 'button', 'label': 'Connect Epic Account', 'action': {
                                'type': 'oauth_paste',
                                'title': 'Connect Epic Account',
                                'url_endpoint': '/api/epic_games/auth-url',
                                'callback_endpoint': '/api/epic_games/callback',
                                'instructions': [
                                    'Click <strong>Open Epic Login</strong> — your browser opens the Epic login page.',
                                    'Log in to your Epic Games account.',
                                    "You'll land on a page showing a JSON warning. That warning is about sharing your code with strangers — PlayDate only uses it locally on your computer.",
                                    'Copy everything on that page and paste it below (or just the <code>authorizationCode</code> value).',
                                ],
                                'input_placeholder': 'Paste the page content or just the authorizationCode value',
                                'open_label': 'Open Epic Login',
                                'submit_label': 'Connect',
                            }},
                        ],
                        'connected': [
                            {'type': 'connected_label'},
                            {'type': 'buttons', 'items': [
                                {'label': 'Sync Library', 'action': {'type': 'call', 'fn': 'epicSync'}},
                                {'label': 'Sync Metadata', 'action': {'type': 'call', 'fn': 'epicSyncMetadata'}},
                                {'label': 'Detect Duplicates', 'action': {'type': 'call', 'fn': 'epicDetectDuplicates'}},
                                {'label': 'Disconnect', 'variant': 'muted', 'action': {
                                    'type': 'post', 'endpoint': '/api/epic_games/disconnect',
                                    'on_success': 'refresh_auth',
                                }},
                            ]},
                            {'type': 'status_output', 'key': 'main'},
                        ],
                    },
                },
                launcher_section,
            ],
        }

    def rescrape(self, appid):
        from .epic import scrape_single
        return scrape_single(appid) or None

    def fragments(self):
        return {
            'base_head_styles': 'epic_games_base_head_styles.html',
            'tools_scripts':    'epic_games_tools_scripts.html',
        }


plugin = EpicGamesPlugin()
