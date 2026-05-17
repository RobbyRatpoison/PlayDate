import logging
import os
import sys

log = logging.getLogger(__name__)


def _find_native_launcher():
    """Return path to EADesktop.exe on Windows, or None."""
    if sys.platform == 'win32':
        candidates = []
        for env in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432', 'LOCALAPPDATA'):
            base = os.environ.get(env, '')
            if base:
                candidates.append(os.path.join(base, 'Electronic Arts', 'EA Desktop', 'EADesktop.exe'))
                candidates.append(os.path.join(base, 'EA Desktop', 'EADesktop.exe'))
        for path in candidates:
            if os.path.isfile(path):
                return path
    return None


class EAAppPlugin:
    id       = 'ea_app'
    name     = 'EA App'
    platform = 'ea_app'
    label    = 'EA App'

    date_import_url = 'https://www.ea.com/orders'

    def register(self, app):
        from .routes import bp
        app.register_blueprint(bp)
        log.info('EA App plugin registered')

    def on_startup(self):
        from .watcher import sync_ea_install_status, start_periodic_sync
        try:
            sync_ea_install_status()
            log.info('EA App install status synced on startup')
        except Exception as e:
            log.warning(f'Startup EA App install sync failed: {e}')
        start_periodic_sync()

    def on_shutdown(self):
        from .watcher import stop_periodic_sync, stop_ea_watcher
        stop_periodic_sync()
        stop_ea_watcher()

    def on_uninstall(self):
        from .ea import clear_ea_tokens
        clear_ea_tokens()

    def launch_game(self, appid):
        import time
        from database import get_db, ts_to_date, update_game_data

        db  = get_db()
        row = db.execute(
            "SELECT platform_id, installed FROM games WHERE appid = ?", (appid,)
        ).fetchone()
        db.close()

        if not row:
            return {'status': 'error', 'message': 'EA game not found'}

        offer_id = (row['platform_id'] or '').strip()
        if not offer_id:
            return {'status': 'error', 'message': 'Game has no offer ID — try re-syncing'}

        if row['installed']:
            # New EA App protocol; falls back to origin2:// if not handled
            url = f'eadesktop://library/launch?offerId={offer_id}'
        else:
            url = f'eadesktop://library/install?offerId={offer_id}'

        try:
            if sys.platform == 'win32':
                os.startfile(url)
            else:  # Linux — Wine (EA App has no macOS version)
                import json
                from config import CONFIG_PATH
                try:
                    with open(CONFIG_PATH, 'r') as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
                launcher_cfg = cfg.get('launchers', {}).get('ea_app', {})
                prefix   = launcher_cfg.get('prefix', '').strip()
                wine_bin = launcher_cfg.get('wine_bin', '').strip() or None

                if not prefix:
                    return {
                        'status':  'error',
                        'message': 'EA App not configured. Open Plugins → Manage to set up Wine.',
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
                return {'available': True, 'detail': 'EA App detected'}
            return {'available': False, 'detail': 'EA App not installed'}

        # Linux: require Wine prefix with EADesktop.exe
        import json
        from config import CONFIG_PATH
        try:
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        launcher_cfg = cfg.get('launchers', {}).get('ea_app', {})
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
            if 'EADesktop.exe' in files:
                return {'available': True, 'detail': 'Launcher ready'}

        return {
            'available': False,
            'detail': 'EADesktop.exe not found in prefix — install EA App in Wine',
        }

    def js_api(self):
        return {
            'uninstall_url':  None,
            'scrape_url':     '/api/ea_app/scrape-single/{appid}',
            'scrape_method':  'POST',
            'store_url':      'https://www.ea.com/games/library/{slug}',
            'store_label':    'View on EA App ↗',
            'appid_label':    'EA Offer ID:',
            'sync_label':     'Sync EA Library',
        }

    def manage_ui(self):
        native = _find_native_launcher()
        if native:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'EA App is installed — no additional setup needed.'},
                ],
            }
        elif sys.platform == 'win32':
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'EA App is not installed.'},
                    {'type': 'button', 'label': 'Download EA App', 'action': {
                        'type': 'open_url', 'url': 'https://www.ea.com/ea-app',
                    }},
                ],
            }
        else:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Set the Wine binary and prefix where EA App is installed.'},
                    {'type': 'launcher_config'},
                ],
            }

        return {
            'sections': [
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/ea_app/status',
                        'disconnected': [
                            {'type': 'text', 'content': 'Connect your EA account to import your library.'},
                            {'type': 'button', 'label': 'Connect EA Account', 'action': {
                                'type': 'oauth_popup',
                                'title': 'Connect EA Account',
                                'url_endpoint': '/api/ea_app/auth-url',
                                'callback_endpoint': '/api/ea_app/callback',
                                'redirect_pattern': 'ea.com/login',
                                'code_js': '',
                                'instructions': [
                                    'Click <strong>Open EA Login</strong> — your browser opens the EA login page.',
                                    'Log in to your EA account.',
                                    "After login you'll be redirected to <code>www.ea.com/login?code=...</code>. "
                                    "Copy the full URL from your browser's address bar and paste it below.",
                                ],
                                'input_placeholder': 'Paste the redirect URL (ea.com/login?code=...)',
                                'open_label': 'Open EA Login',
                                'submit_label': 'Connect',
                            }},
                        ],
                        'connected': [
                            {'type': 'connected_label'},
                            {'type': 'button', 'label': 'Sync Library', 'action': {'type': 'call', 'fn': 'eaSync'}},
                            {'type': 'button', 'label': 'Disconnect', 'variant': 'muted', 'action': {
                                'type': 'post', 'endpoint': '/api/ea_app/disconnect',
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
        from .ea import fetch_description
        return fetch_description(appid, platform_id)

    def rescrape(self, appid):
        from .ea import scrape_single
        return scrape_single(appid) or None

    def fragments(self):
        return {
            'base_head_styles': 'ea_app_base_head_styles.html',
            'tools_scripts':    'ea_app_tools_scripts.html',
        }


plugin = EAAppPlugin()
