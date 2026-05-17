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
                            {
                                'type': 'text',
                                'content': (
                                    'Connect your Humble Bundle account by pasting your session cookie. '
                                    'Open <strong>humblebundle.com</strong> in your browser, then open '
                                    'DevTools (F12) → Application → Cookies → humblebundle.com '
                                    'and copy the value of <code>_simpleauth_sess</code>.'
                                ),
                            },
                            {'type': 'button', 'label': 'Connect Humble Account', 'action': {
                                'type': 'oauth_paste',
                                'title': 'Connect Humble Bundle',
                                'url_endpoint': '/api/humble/auth-url',
                                'callback_endpoint': '/api/humble/connect',
                                'instructions': [
                                    'Click <strong>Open Humble Bundle</strong> — your browser opens the library page.',
                                    'Open DevTools (F12) → Application → Cookies → humblebundle.com.',
                                    'Find <code>_simpleauth_sess</code> and copy its <strong>Value</strong>.',
                                    'Paste it in the box below and click Connect.',
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
