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
        pass

    def on_shutdown(self):
        pass

    def on_uninstall(self):
        from .indiegala import disconnect
        disconnect()

    def launch_game(self, appid):
        from .indiegala import launch_game
        return launch_game(appid)

    def js_api(self):
        return {
            'uninstall_url':  None,
            'scrape_url':     None,
            'scrape_method':  'POST',
            'store_url':      'https://www.indiegala.com/store/game/{slug}',
            'store_label':    'View on IndieGala ↗',
            'appid_label':    'IndieGala ID:',
            'sync_label':     'Sync IndieGala Library',
        }

    def manage_ui(self):
        return {
            'sections': [
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/indiegala/status',
                        'disconnected': [
                            {
                                'type': 'text',
                                'content': (
                                    'Connect your IndieGala account by pasting your session cookie. '
                                    'Open <strong>indiegala.com</strong> in your browser, then open '
                                    'DevTools (F12) → Application → Cookies → indiegala.com '
                                    'and copy the value of <code>sessionid</code>.'
                                ),
                            },
                            {'type': 'button', 'label': 'Connect IndieGala Account', 'action': {
                                'type': 'oauth_paste',
                                'title': 'Connect IndieGala',
                                'url_endpoint': '/api/indiegala/auth-url',
                                'callback_endpoint': '/api/indiegala/connect',
                                'instructions': [
                                    'Click <strong>Open IndieGala</strong> — your browser opens the library page.',
                                    'Open DevTools (F12) → Application → Cookies → indiegala.com.',
                                    'Find <code>sessionid</code> and copy its <strong>Value</strong>.',
                                    'Paste it in the box below and click Connect.',
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
            ],
        }

    def fragments(self):
        return {
            'tools_scripts': 'indiegala_tools_scripts.html',
        }


plugin = IndieGalaPlugin()
