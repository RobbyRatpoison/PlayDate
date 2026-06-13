import logging
import os
import sys

log = logging.getLogger(__name__)


def _find_native_launcher():
    """Return path to UbisoftConnect.exe on Windows, or None."""
    if sys.platform == 'win32':
        candidates = []
        for env in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432'):
            base = os.environ.get(env, '')
            if base:
                candidates.append(os.path.join(
                    base, 'Ubisoft', 'Ubisoft Game Launcher', 'UbisoftConnect.exe'))
                candidates.append(os.path.join(
                    base, 'Ubisoft Game Launcher', 'UbisoftConnect.exe'))
        for path in candidates:
            if os.path.isfile(path):
                return path
    return None


class UbisoftPlugin:
    id       = 'ubisoft'
    name     = 'Ubisoft Connect'
    platform = 'ubisoft'
    label    = 'Ubisoft Connect'

    date_import_url = 'https://www.ubisoft.com/en-us/account/orders'

    def register(self, app):
        from .routes import bp
        app.register_blueprint(bp)
        log.info('Ubisoft Connect plugin registered')

    def on_startup(self):
        from .watcher import sync_ubisoft_install_status, start_periodic_sync
        try:
            sync_ubisoft_install_status()
            log.info('Ubisoft install status synced on startup')
        except Exception as e:
            log.warning(f'Startup Ubisoft install sync failed: {e}')
        start_periodic_sync()

    def on_shutdown(self):
        from .watcher import stop_periodic_sync, stop_ubisoft_watcher
        stop_periodic_sync()
        stop_ubisoft_watcher()

    def on_uninstall(self):
        from .ubisoft import clear_ubi_tokens
        clear_ubi_tokens()

    def launch_game(self, appid):
        import time
        from database import get_db, ts_to_date, update_game_data

        db  = get_db()
        row = db.execute(
            "SELECT platform_id, installed FROM games WHERE appid = ?", (appid,)
        ).fetchone()
        db.close()

        if not row:
            return {'status': 'error', 'message': 'Ubisoft game not found'}

        space_id = (row['platform_id'] or '').strip()
        if not space_id:
            return {'status': 'error', 'message': 'Game has no space ID — try re-syncing'}

        if row['installed']:
            url = f'uplay://launch/{space_id}/0'
        else:
            url = f'uplay://install/{space_id}'

        try:
            if sys.platform == 'win32':
                os.startfile(url)
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.Popen(['open', url])
            else:  # Linux — Wine
                import json
                from config import CONFIG_PATH
                try:
                    with open(CONFIG_PATH, 'r') as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
                launcher_cfg = cfg.get('launchers', {}).get('ubisoft', {})
                prefix   = launcher_cfg.get('prefix', '').strip()
                wine_bin = launcher_cfg.get('wine_bin', '').strip() or None

                if not prefix:
                    return {
                        'status':  'error',
                        'message': 'Ubisoft Connect not configured. Open Plugins → Manage to set up Wine.',
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
                return {'available': True, 'detail': 'Launcher detected'}
            return {'available': False, 'detail': 'Ubisoft Connect not installed'}

        # Linux: require Wine prefix with UbisoftConnect.exe
        import json
        from config import CONFIG_PATH
        try:
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        launcher_cfg = cfg.get('launchers', {}).get('ubisoft', {})
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
            if 'UbisoftConnect.exe' in files:
                return {'available': True, 'detail': 'Launcher ready'}

        return {
            'available': False,
            'detail': 'UbisoftConnect.exe not found in prefix — install Ubisoft Connect in Wine',
        }

    def js_api(self):
        native = sys.platform == 'win32'
        return {
            'uninstall_url':     None,
            'scrape_url':        '/api/ubisoft/scrape-single/{appid}',
            'scrape_method':     'POST',
            'store_url':         'https://www.ubisoft.com/en-us/game/{slug}',
            'store_label':       'View on Ubisoft Store ↗',
            'appid_label':       'Ubisoft Space ID:',
            'sync_label':        'Sync Ubisoft Library',
        }

    def manage_ui(self):
        native = _find_native_launcher()
        if native:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Ubisoft Connect is installed — no additional setup needed.'},
                ],
            }
        elif sys.platform == 'win32':
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Ubisoft Connect is not installed.'},
                    {'type': 'button', 'label': 'Download Ubisoft Connect', 'action': {
                        'type': 'open_url', 'url': 'https://www.ubisoft.com/en-us/ubisoft-connect/download',
                    }},
                ],
            }
        else:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Set the Wine binary and prefix where Ubisoft Connect is installed.'},
                    {'type': 'launcher_config'},
                ],
            }

        return {
            'sections': [
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/ubisoft/status',
                        'disconnected': [
                            {'type': 'button', 'label': 'Connect Ubisoft Account', 'action': {
                                'type': 'oauth_popup',
                                'title': 'Connect Ubisoft Connect',
                                'url_endpoint': '/api/ubisoft/auth-url',
                                'callback_endpoint': '/api/ubisoft/connect',
                                'redirect_pattern': 'ubisoft.com',
                                'intercept_js': (
                                    # Intercept XHR/fetch in the login popup to capture the session ticket.
                                    # Matches any ubisoft/ubi.com response with a ticket field — needed
                                    # because 2FA uses a different URL than the initial login endpoint.
                                    "(function(){"
                                    "var _KEY='_pd_ubi_sess';"
                                    "function _store(text){"
                                    "try{if(text)localStorage.setItem(_KEY,text);}catch(e){}"
                                    "try{if(text)window.name=text;}catch(e){}"
                                    # Cookie fallback: window.name may not survive cross-origin navigations.
                                    "try{"
                                    "if(text){"
                                    "var o=JSON.parse(text);"
                                    "if(o&&o.ticket){"
                                    "document.cookie='_pd_ubi_tk='+encodeURIComponent(o.ticket.substring(0,3000))+'; path=/; SameSite=Lax';"
                                    "document.cookie='_pd_ubi_rm='+encodeURIComponent((o.rememberMeTicket||'').substring(0,3000))+'; path=/; SameSite=Lax';"
                                    "}"
                                    "}"
                                    "}catch(e){}"
                                    "}"
                                    "function _try(text,url){"
                                    "var u=url||'';"
                                    "if(u.indexOf('ubisoft')===-1&&u.indexOf('ubi.com')===-1)return;"
                                    "try{var o=JSON.parse(text);if(o&&(o.ticket||o.rememberMeTicket))_store(text);}catch(e){}"
                                    "}"
                                    "var _oOpen=XMLHttpRequest.prototype.open,_oSend=XMLHttpRequest.prototype.send;"
                                    "XMLHttpRequest.prototype.open=function(m,u){this._pdu=u||'';return _oOpen.apply(this,arguments);};"
                                    "XMLHttpRequest.prototype.send=function(){"
                                    "var x=this;"
                                    "x.addEventListener('load',function(){if(x.status>=200&&x.status<300)_try(x.responseText,x._pdu);});"
                                    "return _oSend.apply(this,arguments);"
                                    "};"
                                    "var _oFetch=window.fetch;"
                                    "if(typeof _oFetch==='function'){"
                                    "window.fetch=function(input,init){"
                                    "var u=typeof input==='string'?input:(input&&input.url)||'';"
                                    "var p=_oFetch.apply(this,arguments);"
                                    "p.then(function(r){if(r&&r.ok)r.clone().text().then(function(t){_try(t,u);}).catch(function(){});}).catch(function(){});"
                                    "return p;"
                                    "};"
                                    "}"
                                    "})()"
                                ),
                                'code_js': (
                                    "(function(){"
                                    "try{"
                                    # 1) URL fragment — Ubisoft may pass ticket in hash after form POST redirect.
                                    "var h=window.location.hash.slice(1);"
                                    "if(h){"
                                    "var ps={};"
                                    "h.split('&').forEach(function(p){"
                                    "var kv=p.split('=');"
                                    "if(kv.length>=2)ps[decodeURIComponent(kv[0])]=decodeURIComponent(kv.slice(1).join('='));"
                                    "});"
                                    "if(ps.ticket||ps.rememberMeTicket)return JSON.stringify(ps);"
                                    "}"
                                    # 2) window.name (set by intercept_js if login used XHR/fetch)
                                    "var wn=window.name||'';"
                                    "if(wn){try{var wo=JSON.parse(wn);if(wo&&(wo.ticket||wo.rememberMeTicket)){return wn;}}catch(e){}}"
                                    # 3) localStorage/sessionStorage — deep search for ticket-like objects
                                    "var stores=[localStorage,sessionStorage];"
                                    "for(var s=0;s<stores.length;s++){"
                                    "try{"
                                    "for(var i=0;i<stores[s].length;i++){"
                                    "var v=stores[s].getItem(stores[s].key(i));"
                                    "try{"
                                    "var o=JSON.parse(v);"
                                    # Direct: {ticket, rememberMeTicket}
                                    "if(o&&(o.ticket||o.rememberMeTicket))return v;"
                                    # Nested one level: {loginData: {ticket, ...}} or similar
                                    "if(o&&typeof o==='object'){"
                                    "for(var nk in o){"
                                    "var nv=o[nk];"
                                    "if(nv&&typeof nv==='object'&&(nv.ticket||nv.rememberMeTicket))return JSON.stringify(nv);"
                                    "}"
                                    "}"
                                    "}catch(e){}"
                                    "}"
                                    "}catch(e){}"
                                    "}"
                                    # 4) Cookie set by intercept_js if XHR/fetch was intercepted
                                    "var tk='',rm='';"
                                    "var ck=document.cookie.split(';');"
                                    "for(var j=0;j<ck.length;j++){"
                                    "var p=ck[j].trim();"
                                    "if(p.indexOf('_pd_ubi_tk=')===0)tk=decodeURIComponent(p.slice(11));"
                                    "if(p.indexOf('_pd_ubi_rm=')===0)rm=decodeURIComponent(p.slice(11));"
                                    "}"
                                    "if(tk)return JSON.stringify({ticket:tk,rememberMeTicket:rm||null});"
                                    # 5) Diagnostic — ONLY on the change_domain/ redirect page.
                                    #    On the login or 2FA page, return '' so the popup stays open.
                                    "var href=window.location.href;"
                                    "if(href.indexOf('change_domain')!==-1){"
                                    "var lsItems={};"
                                    "try{"
                                    "for(var li=0;li<localStorage.length;li++){"
                                    "var lk=localStorage.key(li);"
                                    "lsItems[lk]=(localStorage.getItem(lk)||'').substring(0,400);"
                                    "}"
                                    "}catch(e){}"
                                    "var ssItems={};"
                                    "try{"
                                    "for(var si=0;si<sessionStorage.length;si++){"
                                    "var sk=sessionStorage.key(si);"
                                    "ssItems[sk]=(sessionStorage.getItem(sk)||'').substring(0,400);"
                                    "}"
                                    "}catch(e){}"
                                    "return JSON.stringify({_pd_diag:1,href:href,ck:document.cookie,ls:lsItems,ss:ssItems});"
                                    "}"
                                    # Not on change_domain — stay open (login/2FA page)
                                    "}catch(e){}"
                                    "return '';"
                                    "})()"
                                ),
                                'instructions': [
                                    'Sign in to your Ubisoft account in the popup.',
                                    'PlayDate will connect automatically once you are logged in.',
                                    'If it does not connect automatically: in the popup, open DevTools (F12) '
                                    '→ Application → Local Storage → connect.ubisoft.com, '
                                    'find <code>loginData</code>, copy its value, and paste it below.',
                                ],
                                'input_placeholder': 'Paste loginData JSON value here…',
                                'open_label': 'Open Ubisoft Sign In',
                                'submit_label': 'Connect',
                            }},
                        ],
                        'connected': [
                            {'type': 'connected_label'},
                            {'type': 'button', 'label': 'Sync Library', 'action': {'type': 'call', 'fn': 'ubisoftSync'}},
                            {'type': 'button', 'label': 'Disconnect', 'variant': 'muted', 'action': {
                                'type': 'post', 'endpoint': '/api/ubisoft/disconnect',
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
        from .ubisoft import fetch_description
        return fetch_description(appid, platform_id)

    def rescrape(self, appid):
        from .ubisoft import scrape_single
        return scrape_single(appid) or None

    def fragments(self):
        return {
            'base_head_styles': 'ubisoft_base_head_styles.html',
            'tools_scripts':    'ubisoft_tools_scripts.html',
        }


plugin = UbisoftPlugin()
