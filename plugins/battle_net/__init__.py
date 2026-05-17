import logging
import os
import sys

log = logging.getLogger(__name__)

# Product code -> battlenet:// protocol slug (some differ from the product code)
_LAUNCH_SLUGS = {
    'WoW':   'WoW',
    'WoWC':  'WoW',       # Classic uses the same launcher, game selection inside
    'WoWCE': 'WoW',
    'D4':    'D4',
    'D3':    'D3',
    'D2':    'D2',
    'D1':    'D1',
    'OSI':   'OSI',
    'S2':    'S2',
    'S1':    'S1',
    'SC':    'SC',
    'HS1':   'HS1',
    'W3':    'W3',
    'W2':    'W2',
    'W1':    'W1',
    'Pro':   'Pro',
    'WTCG':  'WTCG',
    'Hero':  'Hero',
    'Bots':  'Bots',
    'VIPR':  'VIPR',
    'ODIN':  'ODIN',
    'LAZR':  'LAZR',
    'FORE':  'FORE',
    'ZEUS':  'ZEUS',
    'WLBY':  'WLBY',
}


def _find_native_launcher():
    if sys.platform == 'win32':
        candidates = []
        for env in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432'):
            base = os.environ.get(env, '')
            if base:
                candidates.append(os.path.join(base, 'Battle.net', 'Battle.net.exe'))
                candidates.append(os.path.join(base, 'Blizzard Entertainment', 'Battle.net', 'Battle.net.exe'))
        for path in candidates:
            if os.path.isfile(path):
                return path
    return None


class BattleNetPlugin:
    id       = 'battle_net'
    name     = 'Battle.net'
    platform = 'battle_net'
    label    = 'Battle.net'

    def register(self, app):
        from .routes import bp
        app.register_blueprint(bp)
        log.info('Battle.net plugin registered')

    def on_startup(self):
        from .watcher import sync_bnet_install_status, start_periodic_sync
        try:
            sync_bnet_install_status()
            log.info('Battle.net install status synced on startup')
        except Exception as e:
            log.warning(f'Startup Battle.net install sync failed: {e}')
        start_periodic_sync()

    def on_shutdown(self):
        from .watcher import stop_periodic_sync, stop_bnet_watcher
        stop_periodic_sync()
        stop_bnet_watcher()

    def on_uninstall(self):
        from .battle_net import clear_bnet_tokens
        clear_bnet_tokens()
        from config import CONFIG_PATH, load_config, _save_config_data
        cfg = load_config() or {}
        cfg.pop('battle_net_credentials', None)
        _save_config_data(cfg)

    def launch_game(self, appid):
        import time
        from database import get_db, ts_to_date, update_game_data

        db  = get_db()
        row = db.execute(
            "SELECT platform_id, installed FROM games WHERE appid = ?", (appid,)
        ).fetchone()
        db.close()

        if not row:
            return {'status': 'error', 'message': 'Battle.net game not found'}

        product_code = (row['platform_id'] or '').strip()
        if not product_code:
            return {'status': 'error', 'message': 'Game has no product code — try re-syncing'}

        slug = _LAUNCH_SLUGS.get(product_code, product_code)
        url  = f'battlenet://{slug}'

        try:
            if sys.platform == 'win32':
                os.startfile(url)
            else:  # Linux — Wine (no native Battle.net for Linux/macOS)
                import json
                from config import CONFIG_PATH
                try:
                    with open(CONFIG_PATH, 'r') as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
                launcher_cfg = cfg.get('launchers', {}).get('battle_net', {})
                prefix   = launcher_cfg.get('prefix', '').strip()
                wine_bin = launcher_cfg.get('wine_bin', '').strip() or None

                if not prefix:
                    return {
                        'status':  'error',
                        'message': 'Battle.net not configured. Open Plugins → Manage to set up Wine.',
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
                return {'available': True, 'detail': 'Battle.net launcher detected'}
            return {'available': False, 'detail': 'Battle.net not installed'}

        import json
        from config import CONFIG_PATH
        try:
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        launcher_cfg = cfg.get('launchers', {}).get('battle_net', {})
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
            if 'Battle.net.exe' in files:
                return {'available': True, 'detail': 'Launcher ready'}

        return {
            'available': False,
            'detail': 'Battle.net.exe not found in prefix — install Battle.net in Wine',
        }

    def js_api(self):
        return {
            'uninstall_url':  None,
            'scrape_url':     '/api/battle_net/scrape-single/{appid}',
            'scrape_method':  'POST',
            'store_url':      None,
            'store_label':    None,
            'appid_label':    'Battle.net Product:',
            'sync_label':     'Sync Battle.net Library',
        }

    def manage_ui(self):
        native = _find_native_launcher()
        if native:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Battle.net is installed — no additional setup needed.'},
                ],
            }
        elif sys.platform == 'win32':
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Battle.net is not installed.'},
                    {'type': 'button', 'label': 'Download Battle.net', 'action': {
                        'type': 'open_url', 'url': 'https://www.blizzard.com/en-us/apps/battle.net/desktop',
                    }},
                ],
            }
        else:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Set the Wine binary and prefix where Battle.net is installed.'},
                    {'type': 'launcher_config'},
                ],
            }

        return {
            'sections': [
                {
                    'title': 'API Credentials',
                    'items': [
                        {'type': 'text', 'content':
                            'Create a free API client at '
                            '<a href="https://develop.battle.net" target="_blank">develop.battle.net</a>. '
                            'Set the redirect URI to <code>http://localhost/</code>.'},
                        {'type': 'info_endpoint', 'endpoint': '/api/battle_net/credentials-status'},
                        {'type': 'button', 'label': 'Enter Client Credentials',
                         'action': {'type': 'call', 'fn': 'battlenetSetCredentials'}},
                    ],
                },
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/battle_net/status',
                        'disconnected': [
                            {'type': 'text', 'content': 'Connect your Battle.net account after entering credentials above.'},
                            {'type': 'button', 'label': 'Connect Battle.net Account', 'action': {
                                'type': 'oauth_popup',
                                'title': 'Connect Battle.net Account',
                                'url_endpoint': '/api/battle_net/auth-url',
                                'callback_endpoint': '/api/battle_net/callback',
                                'redirect_pattern': 'localhost',
                                'code_js': '',
                                'instructions': [
                                    'Click <strong>Open Battle.net Login</strong> — your browser opens the Blizzard login page.',
                                    'Log in to your Battle.net account.',
                                    'After login, your browser will redirect to <code>http://localhost/</code> (which may show an error — that\'s expected).',
                                    'Copy the full URL from your browser\'s address bar and paste it below.',
                                ],
                                'input_placeholder': 'Paste the redirect URL (http://localhost/?code=...)',
                                'open_label': 'Open Battle.net Login',
                                'submit_label': 'Connect',
                            }},
                        ],
                        'connected': [
                            {'type': 'connected_label'},
                            {'type': 'button', 'label': 'Sync Library',
                             'action': {'type': 'call', 'fn': 'battlenetSync'}},
                            {'type': 'button', 'label': 'Disconnect', 'variant': 'muted', 'action': {
                                'type': 'post', 'endpoint': '/api/battle_net/disconnect',
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
        return None

    def rescrape(self, appid):
        from .battle_net import scrape_single
        return scrape_single(appid) or None

    def fragments(self):
        return {
            'base_head_styles': 'battle_net_base_head_styles.html',
            'tools_scripts':    'battle_net_tools_scripts.html',
        }


plugin = BattleNetPlugin()
