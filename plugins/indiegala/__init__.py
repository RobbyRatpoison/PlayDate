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
                            {'type': 'text', 'content': 'Connect your IndieGala account to import your library.'},
                            {'type': 'button', 'label': 'Connect IndieGala Account', 'action': {
                                'type': 'oauth_popup',
                                'title': 'Connect IndieGala',
                                'url_endpoint': '/api/indiegala/auth-url',
                                'callback_endpoint': '/api/indiegala/connect',
                                'redirect_pattern': 'indiegala.com',
                                'code_js': (
                                    "document.cookie.split(';')"
                                    ".map(function(c){return c.trim();})"
                                    ".filter(function(c){return c.indexOf('sessionid=')===0;})"
                                    ".map(function(c){return c.slice('sessionid='.length);})"
                                    "[0] || ''"
                                ),
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
            ],
        }

    def fragments(self):
        return {
            'tools_scripts': 'indiegala_tools_scripts.html',
        }


plugin = IndieGalaPlugin()
