import logging

log = logging.getLogger(__name__)


class HumblePlugin:
    id       = 'humble'
    name     = 'Humble Bundle'
    platform = 'humble'
    label    = 'Humble Bundle'

    def register(self, app):
        from .routes import bp
        app.register_blueprint(bp)
        log.info('Humble Bundle plugin registered')

    def on_startup(self):
        from .humble import HUMBLE_DOWNLOAD_DIR
        from .watcher import start_humble_watcher, sync_humble_install_status
        sync_humble_install_status()
        start_humble_watcher(HUMBLE_DOWNLOAD_DIR)

    def resync_installed(self):
        from .watcher import sync_humble_install_status
        sync_humble_install_status()

    def on_shutdown(self):
        from .watcher import stop_humble_watcher
        stop_humble_watcher()

    def on_uninstall(self):
        from .humble import disconnect
        disconnect()

    def fetch_purchase_dates(self, appids, on_result):
        from .humble import fetch_dates_for_appids
        fetch_dates_for_appids(appids, on_result)

    def launch_game(self, appid):
        from .humble import launch_game
        return launch_game(appid)

    def rescrape(self, appid):
        from .humble import rescrape
        return rescrape(appid)

    def js_api(self):
        return {
            'uninstall_url':  '/api/humble/uninstall/{appid}',
            'scrape_url':     '/api/humble/scrape-single/{appid}',
            'scrape_method':  'POST',
            'appid_label':    'Humble ID:',
            'sync_label':     'Sync Humble Data',
        }

    def manage_ui(self):
        return {
            'sections': [
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/humble/status',
                        'disconnected': [
                            {'type': 'text', 'content': 'Connect your Humble Bundle account to import your library.'},
                            {'type': 'button', 'label': 'Connect Humble Account', 'action': {
                                'type': 'oauth_popup',
                                'title': 'Connect Humble Bundle',
                                'url_endpoint': '/api/humble/auth-url',
                                'callback_endpoint': '/api/humble/connect',
                                'redirect_pattern': 'humblebundle.com/home',
                                'cookie_name': '_simpleauth_sess',
                                'instructions': [
                                    'Sign in to your Humble Bundle account in the popup.',
                                    'PlayDate will connect automatically once you are logged in.',
                                    'If it does not connect automatically, open DevTools (F12) in the popup → Application → Cookies → humblebundle.com, copy the value of <code>_simpleauth_sess</code>, and paste it below.',
                                ],
                                'input_placeholder': 'Paste your _simpleauth_sess cookie value here…',
                                'open_label': 'Open Humble Bundle',
                                'submit_label': 'Connect',
                            }},
                        ],
                        'connected': [
                            {'type': 'connected_label'},
                            {'type': 'buttons', 'items': [
                                {'label': 'Sync Library',
                                 'action': {'type': 'call', 'fn': 'humbleSync'}},
                                {'label': 'Disconnect', 'variant': 'muted',
                                 'action': {'type': 'post', 'endpoint': '/api/humble/disconnect',
                                            'on_success': 'refresh_auth'}},
                            ]},
                            {'type': 'status_output', 'key': 'main'},
                        ],
                    },
                },
            ],
        }

    def fragments(self):
        return {
            'tools_scripts': 'humble_tools_scripts.html',
        }


plugin = HumblePlugin()
