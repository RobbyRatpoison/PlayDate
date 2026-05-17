import logging

log = logging.getLogger(__name__)


class AmazonGamesPlugin:
    id       = 'amazon_games'
    name     = 'Amazon Games'
    platform = 'amazon_games'
    label    = 'Amazon Games'

    def register(self, app):
        from .routes import bp
        app.register_blueprint(bp)
        log.info('Amazon Games plugin registered')

    def on_startup(self):
        from .amazon_games import nile_detected, find_nile_library
        if nile_detected():
            log.info(f'Amazon Games: Nile library detected at {find_nile_library()}')

    def on_shutdown(self):
        pass

    def on_uninstall(self):
        from .amazon_games import disconnect
        disconnect()

    def launch_game(self, appid):
        from .amazon_games import launch_game
        return launch_game(appid)

    def js_api(self):
        return {
            'uninstall_url':  None,
            'scrape_url':     None,
            'scrape_method':  'POST',
            'store_url':      'https://gaming.amazon.com/home',
            'store_label':    'View on Amazon Games ↗',
            'appid_label':    'Amazon Game ID:',
            'sync_label':     'Sync Amazon Library',
        }

    def manage_ui(self):
        from .amazon_games import nile_detected
        nile = nile_detected()

        sections = []

        if nile:
            sections.append({
                'title': 'Heroic / Nile',
                'items': [
                    {
                        'type': 'text',
                        'content': (
                            'Nile library detected from Heroic Games Launcher. '
                            'Sync will import your library directly from local files — no login needed.'
                        ),
                    },
                    {'type': 'button', 'label': 'Sync Library', 'action': {'type': 'call', 'fn': 'amazonGamesSync'}},
                    {'type': 'status_output', 'key': 'main'},
                ],
            })

        sections.append({
            'title': 'Amazon Account' if not nile else 'Amazon Account (Alternative)',
            'auth': {
                'endpoint': '/api/amazon_games/status',
                'disconnected': [
                    {
                        'type': 'text',
                        'content': (
                            'Connect your Amazon account by pasting your session cookie. '
                            'Sign in at <strong>amazon.com</strong>, then open '
                            'DevTools (F12) → Application → Cookies → amazon.com '
                            'and copy the value of <code>at-main</code>.'
                        ),
                    },
                    {'type': 'button', 'label': 'Connect Amazon Account', 'action': {
                        'type': 'oauth_paste',
                        'title': 'Connect Amazon Games',
                        'url_endpoint': '/api/amazon_games/auth-url',
                        'callback_endpoint': '/api/amazon_games/connect',
                        'instructions': [
                            'Click <strong>Open Amazon Sign In</strong> — your browser opens the login page.',
                            'Sign in to your Amazon account.',
                            'Open DevTools (F12) → Application → Cookies → amazon.com.',
                            'Find <code>at-main</code> and copy its <strong>Value</strong>, then paste it below.',
                        ],
                        'input_placeholder': 'Paste your at-main cookie value here…',
                        'open_label': 'Open Amazon Sign In',
                        'submit_label': 'Connect',
                    }},
                ] if not nile else [
                    {
                        'type': 'text',
                        'content': 'Already using Nile above. Optionally connect via Amazon API for a fresh library fetch.',
                    },
                ],
                'connected': [
                    {'type': 'connected_label'},
                    {'type': 'buttons', 'items': [
                        {'label': 'Sync Library',
                         'action': {'type': 'call', 'fn': 'amazonGamesSync'}},
                        {'label': 'Disconnect', 'variant': 'muted',
                         'action': {'type': 'post', 'endpoint': '/api/amazon_games/disconnect',
                                    'on_success': 'refresh_auth'}},
                    ]},
                    {'type': 'status_output', 'key': 'main'},
                ],
            },
        })

        return {'sections': sections}

    def fragments(self):
        return {
            'tools_scripts': 'amazon_games_tools_scripts.html',
        }


plugin = AmazonGamesPlugin()
