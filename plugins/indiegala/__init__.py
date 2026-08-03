import logging

log = logging.getLogger(__name__)


class IndieGalaPlugin:
    id       = 'indiegala'
    name     = 'IndieGala'
    platform = 'indiegala'
    label    = 'IndieGala'

    def register(self, app):
        from .routes import bp
        app.register_blueprint(bp)
        log.info('IndieGala plugin registered')

    def on_startup(self):
        from .indiegala import get_games_dir, sync_indiegala_install_status
        from .watcher import start_indiegala_watcher
        sync_indiegala_install_status()
        start_indiegala_watcher(get_games_dir())

    def resync_installed(self):
        from .indiegala import sync_indiegala_install_status
        sync_indiegala_install_status()

    def on_shutdown(self):
        from .watcher import stop_indiegala_watcher
        stop_indiegala_watcher()

    def on_uninstall(self):
        from .indiegala import disconnect
        disconnect()

    def fetch_purchase_dates(self, appids, on_result):
        from .indiegala import fetch_dates_for_appids
        for appid, ts in fetch_dates_for_appids(appids).items():
            on_result(appid, ts)

    def launch_game(self, appid):
        from .indiegala import launch_game
        return launch_game(appid)

    def rescrape(self, appid):
        from .indiegala import rescrape
        return rescrape(appid)

    def js_api(self):
        return {
            'uninstall_url':  '/api/indiegala/uninstall/{appid}',
            'scrape_url':     '/api/indiegala/scrape-single/{appid}',
            'scrape_method':  'POST',
            'store_url':      '{slug}',
            'store_label':    'View on IndieGala ↗',
            'appid_label':    'IndieGala ID:',
            'sync_label':     'Sync IndieGala Data',
        }

    def manage_ui(self):
        return {
            'sections': [
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/indiegala/status',
                        'disconnected': [
                            {'type': 'text', 'content': 'Connect your IndieGala account to import your library.'},
                            {'type': 'button', 'label': 'Connect IndieGala Account', 'action': {
                                'type': 'oauth_popup',
                                'title': 'Connect IndieGala',
                                'url_endpoint': '/api/indiegala/auth-url',
                                'callback_endpoint': '/api/indiegala/connect',
                                'redirect_pattern': 'indiegala.com',
                                'cookie_name': 'sessionid',
                                'instructions': [
                                    'Sign in to your IndieGala account in the popup.',
                                    'PlayDate will connect automatically once you are logged in.',
                                    'If it does not connect automatically, open DevTools (F12) in the popup → Application → Cookies → indiegala.com, copy the value of <code>sessionid</code>, and paste it below.',
                                ],
                                'input_placeholder': 'Paste your sessionid cookie value here…',
                                'open_label': 'Open IndieGala',
                                'submit_label': 'Connect',
                            }},
                        ],
                        'connected': [
                            {'type': 'connected_label'},
                            {'type': 'buttons', 'items': [
                                {'label': 'Sync Library',
                                 'action': {'type': 'call', 'fn': 'indiegalaSync'}},
                                {'label': 'Disconnect', 'variant': 'muted',
                                 'action': {'type': 'post', 'endpoint': '/api/indiegala/disconnect',
                                            'on_success': 'refresh_auth'}},
                            ]},
                            {'type': 'status_output', 'key': 'main'},
                        ],
                    },
                },
                {
                    'title': 'Games Folder',
                    'items': [
                        {'type': 'text', 'content': 'Point PlayDate to the folder where you place downloaded IndieGala games. Each game should be in its own subfolder. PlayDate will open that subfolder when you launch an uninstalled game so you can drop files in.'},
                        {'type': 'info_endpoint', 'endpoint': '/api/indiegala/games-dir-info'},
                        {'type': 'buttons', 'items': [
                            {'label': 'Set Folder…',
                             'action': {'type': 'call', 'fn': 'indiegalaPickFolder'}},
                            {'label': 'Open Folder',
                             'action': {'type': 'call', 'fn': 'indiegalaOpenFolder'}},
                            {'label': 'Scan Now',
                             'action': {'type': 'call', 'fn': 'indiegalaScan'}},
                        ]},
                        {'type': 'status_output', 'key': 'folder'},
                    ],
                },
            ],
        }

    def fragments(self):
        return {
            'tools_scripts': 'indiegala_tools_scripts.html',
        }


plugin = IndieGalaPlugin()
