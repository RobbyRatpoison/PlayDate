import logging

log = logging.getLogger(__name__)


class ItchIoPlugin:
    id       = 'itch_io'
    name     = 'itch.io'
    label    = 'itch.io'
    platform = 'itch_io'

    def register(self, app):
        from .routes import bp
        app.register_blueprint(bp)
        log.info('itch.io plugin registered')

    def on_startup(self):
        try:
            from .itch_io import sync_install_status, start_install_watcher
            sync_install_status()
            start_install_watcher()
            log.info('itch.io install status synced and watcher started')
        except Exception as e:
            log.warning(f'itch.io startup failed: {e}')

    def resync_installed(self):
        from .itch_io import sync_install_status
        sync_install_status()

    def on_shutdown(self):
        try:
            from .itch_io import stop_install_watcher
            stop_install_watcher()
        except Exception:
            pass

    def sync(self):
        from .itch_io import start_library_sync
        return start_library_sync()

    def fetch_purchase_dates(self, appids, on_result):
        from .itch_io import fetch_dates_for_appids
        fetch_dates_for_appids(appids, on_result)

    def launch_game(self, appid):
        from .itch_io import launch_game
        return launch_game(appid)

    def rescrape(self, appid):
        from .itch_io import rescrape_game
        return rescrape_game(appid)

    def fetch_description(self, appid, platform_id):
        from .itch_io import fetch_description
        return fetch_description(platform_id)

    def on_uninstall(self):
        from .itch_io import disconnect
        disconnect()

    def js_api(self):
        return {
            'scrape_url':       '/api/itch_io/scrape-single/{appid}',
            'scrape_method':    'POST',
            'store_url':        '{slug}',
            'store_label':      'View on itch.io ↗',
            'appid_label':      'itch.io ID:',
            'sync_label':       'Sync itch.io Library',
            'uninstall_url':    '/api/itch_io/uninstall/{appid}',
            'uninstall_confirm': 'Uninstall this itch.io game?\n\nThis will delete the game files from disk.',
        }

    def manage_ui(self):
        return {
            'sections': [
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/itch_io/status',
                        'disconnected': [
                            {'type': 'text', 'content': 'Sign in to your itch.io account to import your library.'},
                            {'type': 'button', 'label': 'Sign In to itch.io', 'action': {
                                'type': 'oauth_popup',
                                'title': 'Connect itch.io',
                                'url_endpoint': '/api/itch_io/auth-url',
                                'callback_endpoint': '/api/itch_io/connect',
                                'redirect_pattern': 'itch.io/user/settings/api-keys',
                                'code_js': (
                                    '(function(){'
                                    # Full key in an input or standalone token (no spaces, no ellipsis, 32-64 chars)
                                    'var els=document.querySelectorAll("input,textarea,code,pre,span,td,div");'
                                    'for(var i=0;i<els.length;i++){'
                                    'var v=(els[i].tagName==="INPUT"||els[i].tagName==="TEXTAREA"?els[i].value:els[i].childNodes.length===1?els[i].textContent:"").trim();'
                                    'if(v&&v.length>=32&&v.length<=64&&!v.includes(".")&&!v.includes(" ")&&/^[a-zA-Z0-9_-]+$/.test(v))return v;'
                                    '}'
                                    # No key visible yet — click the first "View" link to navigate to the full-key page
                                    'var links=document.querySelectorAll("a");'
                                    'for(var i=0;i<links.length;i++){'
                                    'if((links[i].textContent||"").trim()==="View"){links[i].click();break;}'
                                    '}'
                                    'return "";'
                                    '})()'
                                ),
                                'instructions': [
                                    'Log in to itch.io. The window will open on your API keys page.',
                                    'Click <strong>Generate new API key</strong>.',
                                    'If not auto-detected, copy the key and paste it below.',
                                    'If the popup gets stuck on a "Just a moment..." verification page: '
                                    'itch.io is behind Cloudflare, which sometimes blocks PlayDate\'s embedded '
                                    'browser outright. Sign in at '
                                    '<a href="https://itch.io/user/settings/api-keys" target="_blank">itch.io/user/settings/api-keys</a> '
                                    'in your regular browser instead, generate a key there, and paste it below.',
                                ],
                                'input_placeholder': 'Paste your API key here...',
                                'open_label': 'Open itch.io Login',
                                'submit_label': 'Connect',
                            }},
                            {'type': 'button', 'label': 'Paste API key manually', 'variant': 'muted', 'action': {
                                'type': 'oauth_paste',
                                'title': 'Connect itch.io',
                                'url_endpoint': '/api/itch_io/auth-url',
                                'callback_endpoint': '/api/itch_io/connect',
                                'instructions': [],
                                'input_placeholder': '',
                                'open_label': '',
                                'submit_label': 'Connect',
                            }},
                        ],
                        'connected': [
                            {'type': 'connected_label'},
                            {'type': 'buttons', 'items': [
                                {'label': 'Sync Library',
                                 'action': {'type': 'call', 'fn': 'itchIoSync'}},
                                {'label': 'Disconnect', 'variant': 'muted',
                                 'action': {'type': 'post', 'endpoint': '/api/itch_io/disconnect',
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
            'tools_scripts':    'itch_io_tools_scripts.html',
            'base_nav_items':   'itch_io_base_nav_items.html',
            'base_head_styles': 'itch_io_base_head_styles.html',
        }


plugin = ItchIoPlugin()
