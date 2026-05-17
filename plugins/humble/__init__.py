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
        pass

    def on_shutdown(self):
        pass

    def on_uninstall(self):
        from .humble import disconnect
        disconnect()

    def launch_game(self, appid):
        from .humble import launch_game
        return launch_game(appid)

    def js_api(self):
        return {
            'uninstall_url':  None,
            'scrape_url':     None,
            'scrape_method':  'POST',
            'store_url':      'https://www.humblebundle.com/home/library/{slug}',
            'store_label':    'View on Humble Bundle ↗',
            'appid_label':    'Humble ID:',
            'sync_label':     'Sync Humble Library',
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
                                'redirect_pattern': 'humblebundle.com',
                                'code_js': (
                                    "document.cookie.split(';')"
                                    ".map(function(c){return c.trim();})"
                                    ".filter(function(c){return c.indexOf('_simpleauth_sess=')===0;})"
                                    ".map(function(c){return c.slice('_simpleauth_sess='.length);})"
                                    "[0] || ''"
                                ),
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
