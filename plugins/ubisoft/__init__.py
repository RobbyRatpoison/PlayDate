import logging
import os
import sys

log = logging.getLogger(__name__)


def _find_native_launcher():
    """Return path to UbisoftConnect.exe on Windows, or None."""
    if sys.platform == 'win32':
        candidates = []
        for env in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432'):
            base = os.environ.get(env, '')
            if base:
                candidates.append(os.path.join(
                    base, 'Ubisoft', 'Ubisoft Game Launcher', 'UbisoftConnect.exe'))
                candidates.append(os.path.join(
                    base, 'Ubisoft Game Launcher', 'UbisoftConnect.exe'))
        for path in candidates:
            if os.path.isfile(path):
                return path
    return None


class UbisoftPlugin:
    id       = 'ubisoft'
    name     = 'Ubisoft Connect'
    platform = 'ubisoft'
    label    = 'Ubisoft Connect'

    date_import_url = 'https://www.ubisoft.com/en-us/account/orders'

    def register(self, app):
        from .routes import bp
        app.register_blueprint(bp)
        log.info('Ubisoft Connect plugin registered')

    def on_startup(self):
        from .watcher import sync_ubisoft_install_status, start_periodic_sync
        try:
            sync_ubisoft_install_status()
            log.info('Ubisoft install status synced on startup')
        except Exception as e:
            log.warning(f'Startup Ubisoft install sync failed: {e}')
        start_periodic_sync()

    def on_shutdown(self):
        from .watcher import stop_periodic_sync, stop_ubisoft_watcher
        stop_periodic_sync()
        stop_ubisoft_watcher()

    def on_uninstall(self):
        from .ubisoft import clear_ubi_tokens
        clear_ubi_tokens()

    def launch_game(self, appid):
        import time
        from database import get_db, ts_to_date, update_game_data

        db  = get_db()
        row = db.execute(
            "SELECT platform_id, installed FROM games WHERE appid = ?", (appid,)
        ).fetchone()
        db.close()

        if not row:
            return {'status': 'error', 'message': 'Ubisoft game not found'}

        space_id = (row['platform_id'] or '').strip()
        if not space_id:
            return {'status': 'error', 'message': 'Game has no space ID — try re-syncing'}

        if row['installed']:
            url = f'uplay://launch/{space_id}/0'
        else:
            url = f'uplay://install/{space_id}'

        try:
            if sys.platform == 'win32':
                os.startfile(url)
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.Popen(['open', url])
            else:  # Linux — Wine
                import json
                from config import CONFIG_PATH
                try:
                    with open(CONFIG_PATH, 'r') as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
                launcher_cfg = cfg.get('launchers', {}).get('ubisoft', {})
                prefix   = launcher_cfg.get('prefix', '').strip()
                wine_bin = launcher_cfg.get('wine_bin', '').strip() or None

                if not prefix:
                    return {
                        'status':  'error',
                        'message': 'Ubisoft Connect not configured. Open Plugins → Manage to set up Wine.',
                    }
                from runners.wine import launch_protocol_url
                launch_protocol_url(prefix, url, wine_bin=wine_bin, env_extra={'WINEDEBUG': '-all'})
        except RuntimeError as e:
            return {'status': 'error', 'message': str(e)}
        except Exception as e:
            return {'status': 'error', 'message': f'Launch failed: {e}'}

        if row['installed']:
            now_ts = int(time.time())
            update_game_data(appid, last_played=now_ts)
            return {'status': 'success', 'last_played': ts_to_date(now_ts)}

        return {'status': 'success'}

    def launcher_status(self):
        if sys.platform == 'win32':
            native = _find_native_launcher()
            if native:
                return {'available': True, 'detail': 'Launcher detected'}
            return {'available': False, 'detail': 'Ubisoft Connect not installed'}

        # Linux: require Wine prefix with UbisoftConnect.exe
        import json
        from config import CONFIG_PATH
        try:
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        launcher_cfg = cfg.get('launchers', {}).get('ubisoft', {})
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
            if 'UbisoftConnect.exe' in files:
                return {'available': True, 'detail': 'Launcher ready'}

        return {
            'available': False,
            'detail': 'UbisoftConnect.exe not found in prefix — install Ubisoft Connect in Wine',
        }

    def js_api(self):
        native = sys.platform == 'win32'
        return {
            'uninstall_url':     None,
            'scrape_url':        '/api/ubisoft/scrape-single/{appid}',
            'scrape_method':     'POST',
            'store_url':         'https://www.ubisoft.com/en-us/game/{slug}',
            'store_label':       'View on Ubisoft Store ↗',
            'appid_label':       'Ubisoft Space ID:',
            'sync_label':        'Sync Ubisoft Library',
        }

    def manage_ui(self):
        native = _find_native_launcher()
        if native:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Ubisoft Connect is installed — no additional setup needed.'},
                ],
            }
        elif sys.platform == 'win32':
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Ubisoft Connect is not installed.'},
                    {'type': 'button', 'label': 'Download Ubisoft Connect', 'action': {
                        'type': 'open_url', 'url': 'https://www.ubisoft.com/en-us/ubisoft-connect/download',
                    }},
                ],
            }
        else:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Set the Wine binary and prefix where Ubisoft Connect is installed.'},
                    {'type': 'launcher_config'},
                ],
            }

        return {
            'sections': [
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/ubisoft/status',
                        'disconnected': [
                            {'type': 'text', 'content': 'Connect your Ubisoft account to import your library.'},
                            {'type': 'button', 'label': 'Connect Ubisoft Account', 'action': {
                                'type': 'oauth_popup',
                                'title': 'Connect Ubisoft Account',
                                'url_endpoint': '/api/ubisoft/auth-url',
                                'callback_endpoint': '/api/ubisoft/callback',
                                'redirect_pattern': 'connect.ubisoft.com/ready',
                                'code_js': '',
                                'instructions': [
                                    'Click <strong>Open Ubisoft Login</strong> — your browser opens the Ubisoft login page.',
                                    'Log in to your Ubisoft account.',
                                    "After login you'll land on a <code>connect.ubisoft.com/ready</code> page. "
                                    "Copy the full URL from your browser's address bar and paste it below.",
                                ],
                                'input_placeholder': 'Paste the redirect URL (connect.ubisoft.com/ready?code=...)',
                                'open_label': 'Open Ubisoft Login',
                                'submit_label': 'Connect',
                            }},
                        ],
                        'connected': [
                            {'type': 'connected_label'},
                            {'type': 'button', 'label': 'Sync Library', 'action': {'type': 'call', 'fn': 'ubisoftSync'}},
                            {'type': 'button', 'label': 'Disconnect', 'variant': 'muted', 'action': {
                                'type': 'post', 'endpoint': '/api/ubisoft/disconnect',
                                'on_success': 'refresh_auth',
                            }},
                            {'type': 'status_output', 'key': 'main'},
                        ],
                    },
                },
                launcher_section,
            ],
        }

    def fetch_description(self, appid, platform_id):
        from .ubisoft import fetch_description
        return fetch_description(appid, platform_id)

    def rescrape(self, appid):
        from .ubisoft import scrape_single
        return scrape_single(appid) or None

    def fragments(self):
        return {
            'base_head_styles': 'ubisoft_base_head_styles.html',
            'tools_scripts':    'ubisoft_tools_scripts.html',
        }


plugin = UbisoftPlugin()
