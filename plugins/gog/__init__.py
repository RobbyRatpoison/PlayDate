import logging

log = logging.getLogger(__name__)


class GogPlugin:
    id       = 'gog'
    name     = 'GOG'
    platform = 'gog'

    def register(self, app):
        from .routes import bp
        app.register_blueprint(bp)
        log.info("GOG plugin registered")

    def on_startup(self):
        from .gog import GOG_INSTALL_BASE
        from .watcher import start_gog_watcher, sync_gog_install_status
        start_gog_watcher(GOG_INSTALL_BASE)
        try:
            sync_gog_install_status()
            log.info("GOG install status synced on startup")
        except Exception as e:
            log.warning(f"Startup GOG install sync failed: {e}")

    def on_shutdown(self):
        from .watcher import stop_gog_watcher
        stop_gog_watcher()

    def sync(self):
        from .gog import sync_library
        return sync_library()

    date_import_url = 'https://www.gog.com/en/account/settings/orders?ref=playdate'

    def launch_game(self, appid):
        from .gog import launch_gog_game, start_install, get_install_state
        from database import get_db
        db = get_db()
        row = db.execute(
            "SELECT name, installed FROM games WHERE appid = ?", (appid,)
        ).fetchone()
        db.close()
        if row and row['installed']:
            return launch_gog_game(appid)
        game_name = row['name'] if row else ''
        start_install(appid)
        return {
            'status':        'installing',
            'install_poller': '_startGogInstallPoller',
            'message':        f'Installing {game_name}…',
        }

    def rescrape(self, appid):
        from datetime import datetime
        from .gog import fetch_gog_metadata, fetch_gog_achievements, get_valid_session, get_galaxy_user_id
        from database import get_db
        today = datetime.now().strftime('%Y-%m-%d')
        db = get_db()
        row = db.execute("SELECT platform_id FROM games WHERE appid = ?", (appid,)).fetchone()
        db.close()
        if not row:
            return None
        gog_id = row['platform_id'] or str(abs(appid))
        meta = fetch_gog_metadata(gog_id)
        if meta is None:
            return None
        meta.pop('_category', None)
        meta['meta_fetched'] = today
        session        = get_valid_session()
        galaxy_user_id = get_galaxy_user_id()
        if session and galaxy_user_id:
            ach = fetch_gog_achievements(gog_id, galaxy_user_id, session)
            if ach is not None:
                meta.update(ach)
                meta['cheevos_fetched'] = today
        return meta

    def fetch_description(self, appid, platform_id):
        import re, requests
        gog_id = platform_id or str(abs(appid))
        try:
            resp = requests.get(f'https://api.gog.com/products/{gog_id}?expand=description', timeout=10)
            if resp.ok:
                d    = resp.json()
                desc = (d.get('description') or {}).get('lead') or (d.get('description') or {}).get('full', '')
                desc = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', desc)).strip()
                return desc or None
        except Exception:
            pass
        return None

    def on_uninstall(self):
        from .gog import clear_gog_tokens
        clear_gog_tokens()

    def js_api(self):
        return {
            'uninstall_url':     '/api/gog/uninstall/{appid}',
            'uninstall_confirm': 'Uninstall this GOG game?\n\nThis will delete the game files from disk.',
            'scrape_url':        '/api/gog/scrape-single/{appid}',
            'scrape_method':     'POST',
            'store_url':         'https://www.gog.com/en/game/{slug}',
            'store_label':       'View on GOG Store ↗',
            'appid_label':       'GOG ID:',
            'sync_label':        'Sync GOG Data',
        }

    def manage_ui(self):
        return {
            'sections': [
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/gog/status',
                        'disconnected': [
                            {'type': 'text', 'content': 'Connect your GOG account to import your library.'},
                            {'type': 'button', 'label': 'Connect GOG Account', 'action': {
                                'type': 'oauth_paste',
                                'title': 'Connect GOG Account',
                                'url_endpoint': '/api/gog/auth-url',
                                'callback_endpoint': '/api/gog/callback',
                                'instructions': [
                                    'Click <strong>Open GOG Login</strong> — your browser opens the GOG login page.',
                                    'Log in to your GOG account.',
                                    "You'll land on a blank page — copy the full URL from the address bar and paste it below.",
                                ],
                                'input_placeholder': 'https://embed.gog.com/on_login_success?origin=client&code=…',
                                'open_label': 'Open GOG Login',
                                'submit_label': 'Connect',
                            }},
                        ],
                        'connected': [
                            {'type': 'connected_label'},
                            {'type': 'info_endpoint', 'endpoint': '/api/gog/proton-info'},
                            {'type': 'buttons', 'items': [
                                {'label': 'Sync Library', 'action': {'type': 'call', 'fn': 'gogSync'}},
                                {'label': 'Import Purchase Dates', 'action': {'type': 'open_url', 'url': 'https://www.gog.com/en/account/settings/orders?ref=playdate'}},
                                {'label': 'Detect Duplicates', 'action': {'type': 'call', 'fn': 'gogDetectDuplicates'}},
                                {'label': 'Disconnect', 'variant': 'muted', 'action': {'type': 'post', 'endpoint': '/api/gog/disconnect', 'on_success': 'refresh_auth'}},
                            ]},
                            {'type': 'status_output', 'key': 'main'},
                        ],
                    },
                },
            ],
        }

    def fragments(self):
        return {
            'base_head_styles': 'gog_base_head_styles.html',
            'base_nav_items':   'gog_base_nav_items.html',
            'base_body_scripts': 'gog_base_scripts.html',
            'tools_scripts':     'gog_tools_scripts.html',
        }


plugin = GogPlugin()
