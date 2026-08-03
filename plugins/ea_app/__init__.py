import logging
import os
import sys

log = logging.getLogger(__name__)


def _find_native_launcher():
    """Return path to EADesktop.exe on Windows, or None."""
    if sys.platform == 'win32':
        candidates = []
        for env in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432', 'LOCALAPPDATA'):
            base = os.environ.get(env, '')
            if base:
                candidates.append(os.path.join(base, 'Electronic Arts', 'EA Desktop', 'EADesktop.exe'))
                candidates.append(os.path.join(base, 'EA Desktop', 'EADesktop.exe'))
        for path in candidates:
            if os.path.isfile(path):
                return path
    return None


def _find_wine_exe(prefix, exe_name):
    """
    Return the path to exe_name inside the EA Desktop Wine prefix dir.
    Prefers the non-versioned 'EA Desktop/EA Desktop/' path for EALauncher.exe,
    then searches versioned subdirectories (excluding compatibility32).
    """
    ea_base = os.path.join(prefix, 'drive_c', 'Program Files', 'Electronic Arts', 'EA Desktop')
    if not os.path.isdir(ea_base):
        return None
    preferred = os.path.join(ea_base, 'EA Desktop', exe_name)
    if os.path.isfile(preferred):
        return preferred
    for root, dirs, files in os.walk(ea_base):
        dirs[:] = [d for d in dirs if d.lower() != 'compatibility32']
        if exe_name in files:
            return os.path.join(root, exe_name)
    return None


def _find_wine_launcher_exe(prefix):
    return _find_wine_exe(prefix, 'EALauncher.exe')


def _is_ea_desktop_running():
    """Return True if EALocalHostSvc has bound port 3216 (EA Desktop is up and ready)."""
    import subprocess
    result = subprocess.run(['ss', '-tlnp'], capture_output=True, text=True)
    return ':3216' in result.stdout


def _wait_for_ea_local_svc(timeout=25):
    """Poll until EALocalHostSvc binds port 3216, or timeout."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_ea_desktop_running():
            return True
        time.sleep(1)
    return False


class EAAppPlugin:
    id       = 'ea_app'
    name     = 'EA App'
    platform = 'ea_app'
    label    = 'EA App'

    def register(self, app):
        from .routes import bp
        app.register_blueprint(bp)
        log.info('EA App plugin registered')

    def on_startup(self):
        from .watcher import sync_ea_install_status, start_periodic_sync, start_ea_watcher, _get_install_data_dir
        try:
            sync_ea_install_status()
            log.info('EA App install status synced on startup')
        except Exception as e:
            log.warning(f'Startup EA App install sync failed: {e}')
        start_periodic_sync()
        if sys.platform != 'win32':
            install_data_dir = _get_install_data_dir()
            if install_data_dir:
                start_ea_watcher(install_data_dir)

    def resync_installed(self):
        from .watcher import sync_ea_install_status
        sync_ea_install_status()

    def on_shutdown(self):
        from .watcher import stop_periodic_sync, stop_ea_watcher
        stop_periodic_sync()
        stop_ea_watcher()

    def on_uninstall(self):
        from .ea import clear_ea_tokens
        clear_ea_tokens()

    def launch_game(self, appid):
        import time
        from database import get_db, ts_to_date, update_game_data

        db  = get_db()
        row = db.execute(
            "SELECT name, platform_id, installed FROM games WHERE appid = ?", (appid,)
        ).fetchone()
        db.close()

        if not row:
            log.error(f'EA launch: appid {appid} not found in DB')
            return {'status': 'error', 'message': 'EA game not found'}

        offer_id = (row['platform_id'] or '').strip()
        if not offer_id:
            log.error(f'EA launch: appid {appid} ({row["name"]!r}) has no platform_id')
            return {'status': 'error', 'message': 'Game has no offer ID — try re-syncing'}

        installed = bool(row['installed'])
        if installed:
            url = f'origin2://game/launch?offerIds={offer_id}&autolaunch=true'
        else:
            url = f'origin2://game/install?offerIds={offer_id}'

        log.info(f'EA launch: appid {appid} ({row["name"]!r}) installed={installed} url={url}')

        try:
            if sys.platform == 'win32':
                log.info('EA launch: using os.startfile on Windows')
                os.startfile(url)
            else:  # Linux — Wine (EA App has no macOS version)
                import json
                import subprocess as _sp
                from config import CONFIG_PATH
                try:
                    with open(CONFIG_PATH, 'r') as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
                launcher_cfg = cfg.get('launchers', {}).get('ea_app', {})
                prefix   = launcher_cfg.get('prefix', '').strip()
                wine_bin = launcher_cfg.get('wine_bin', '').strip() or None

                log.info(f'EA launch: prefix={prefix!r} wine_bin={wine_bin!r}')

                if not prefix:
                    log.warning('EA launch: no Wine prefix configured')
                    return {
                        'status':  'error',
                        'message': 'EA App not configured. Open Plugins → Manage to set up Wine.',
                    }
                if not os.path.isdir(prefix):
                    log.warning(f'EA launch: prefix does not exist: {prefix!r}')
                    return {
                        'status':  'error',
                        'message': f'Wine prefix not found: {prefix}',
                    }
                from runners.wine import build_proton_env, find_wine_binary, find_proton_wine, is_proton_wine, install_dxvk
                if not wine_bin:
                    wine_bin = find_proton_wine() or find_wine_binary()
                    log.info(f'EA launch: auto-detected wine_bin={wine_bin!r}')
                if not wine_bin:
                    log.warning('EA launch: no Wine binary found')
                    return {'status': 'error', 'message': 'No Wine or Proton binary found'}

                ea_desktop_exe   = _find_wine_exe(prefix, 'EADesktop.exe')
                ea_launch_helper = _find_wine_exe(prefix, 'EALaunchHelper.exe')
                if not ea_desktop_exe:
                    log.warning(f'EA launch: EADesktop.exe not found in prefix {prefix!r}')
                    return {'status': 'error', 'message': 'EA App not installed in Wine prefix'}
                log.info(f'EA launch: EADesktop={ea_desktop_exe!r} EALaunchHelper={ea_launch_helper!r}')

                if is_proton_wine(wine_bin):
                    try:
                        install_dxvk(prefix, wine_bin)
                    except Exception as e:
                        log.warning(f'EA launch: DXVK install skipped: {e}')

                env_extra = {
                    'WINEDEBUG':         '-all',
                    'EAX_LAUNCH_CLIENT': '0',
                    # Disable winegstreamer to avoid aborting on unimplemented
                    # winegstreamer_create_color_converter under Wine/Proton.
                    'WINEDLLOVERRIDES':  'winegstreamer=',
                    # DXVK tuning for CEF GPU process stability.
                    'DXVK_ASYNC':        '1',
                    'DXVK_LOG_LEVEL':    'none',
                }
                if is_proton_wine(wine_bin):
                    env_extra.update({'WINEFSYNC': '1', 'WINEESYNC': '1'})
                # Explicitly select NVIDIA Vulkan ICD if available, to ensure
                # DXVK uses the discrete GPU rather than a software fallback.
                nvidia_icd = '/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json'
                if os.path.exists(nvidia_icd):
                    env_extra['VK_ICD_FILENAMES'] = nvidia_icd
                env = build_proton_env(wine_bin) if is_proton_wine(wine_bin) else dict(os.environ)
                env['WINEPREFIX'] = prefix
                env.update(env_extra)

                if not _is_ea_desktop_running():
                    log.info('EA launch: EADesktop not running, starting in virtual desktop mode')
                    _sp.Popen(
                        [wine_bin, 'explorer', '/desktop=EAApp,1920x1080',
                         ea_desktop_exe, '-ls=Launcher'],
                        env=env, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                    )
                    if not _wait_for_ea_local_svc(timeout=25):
                        log.warning('EA launch: EALocalHostSvc did not bind port 3216 in time')
                    else:
                        log.info('EA launch: EADesktop ready (port 3216 bound)')

                # Pass the URL to the running EADesktop instance.
                if ea_launch_helper:
                    log.info(f'EA launch: sending URL via EALaunchHelper: {url}')
                    _sp.Popen([wine_bin, ea_launch_helper, url],
                              env=env, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                else:
                    launcher_exe = _find_wine_launcher_exe(prefix)
                    if not launcher_exe:
                        log.warning('EA launch: neither EALaunchHelper nor EALauncher found')
                        return {'status': 'error', 'message': 'EA App not installed properly in Wine prefix'}
                    log.info(f'EA launch: sending URL via EALauncher: {url}')
                    _sp.Popen([wine_bin, launcher_exe, url],
                              env=env, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        except RuntimeError as e:
            log.error(f'EA launch: RuntimeError: {e}')
            return {'status': 'error', 'message': str(e)}
        except Exception as e:
            log.error(f'EA launch: unexpected error: {e}', exc_info=True)
            return {'status': 'error', 'message': f'Launch failed: {e}'}

        if installed:
            now_ts = int(time.time())
            update_game_data(appid, last_played=now_ts)
            return {'status': 'success', 'last_played': ts_to_date(now_ts)}

        return {'status': 'success'}

    def launcher_status(self):
        if sys.platform == 'win32':
            native = _find_native_launcher()
            if native:
                return {'available': True, 'detail': 'EA App detected'}
            return {'available': False, 'detail': 'EA App not installed'}

        # Linux: require Wine prefix with EADesktop.exe
        import json
        from config import CONFIG_PATH
        try:
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        launcher_cfg = cfg.get('launchers', {}).get('ea_app', {})
        prefix   = launcher_cfg.get('prefix', '').strip()
        wine_bin = launcher_cfg.get('wine_bin', '').strip()

        from runners.wine import find_wine_binary, find_proton_wine
        if not wine_bin:
            wine_bin = find_proton_wine() or find_wine_binary()

        if not wine_bin:
            return {'available': False, 'detail': 'No Wine or Proton binary found'}
        if not prefix:
            return {'available': False, 'detail': 'Wine prefix not configured'}
        if not os.path.isdir(prefix):
            return {'available': False, 'detail': f'Prefix not found: {prefix}'}

        if _find_wine_exe(prefix, 'EADesktop.exe'):
            return {'available': True, 'detail': 'Launcher ready'}

        return {
            'available': False,
            'detail': 'EADesktop.exe not found in prefix — install EA App in Wine',
        }

    def js_api(self):
        return {
            'uninstall_url':  None,
            'scrape_url':     '/api/ea_app/scrape-single/{appid}',
            'scrape_method':  'POST',
            'store_url':      'https://www.ea.com/games/{slug}',
            'store_label':    'View on EA App ↗',
            'appid_label':    'EA Offer ID:',
            'sync_label':     'Sync EA Library',
        }

    def manage_ui(self):
        native = _find_native_launcher()
        if native:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'EA App is installed — no additional setup needed.'},
                ],
            }
        elif sys.platform == 'win32':
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'EA App is not installed.'},
                    {'type': 'button', 'label': 'Download EA App', 'action': {
                        'type': 'open_url', 'url': 'https://www.ea.com/ea-app',
                    }},
                ],
            }
        else:
            launcher_section = {
                'title': 'Launcher',
                'items': [
                    {'type': 'text', 'content': 'Set the Wine binary and prefix where EA App is installed.'},
                    {'type': 'launcher_config'},
                ],
            }

        return {
            'sections': [
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/ea_app/status',
                        'disconnected': [
                            {'type': 'text', 'content': 'Connect your EA account to import your library.'},
                            {'type': 'button', 'label': 'Connect EA Account', 'action': {
                                'type': 'oauth_paste',
                                'title': 'Connect EA Account',
                                'url_endpoint': '/api/ea_app/token-url',
                                'callback_endpoint': '/api/ea_app/callback',
                                'instructions': [
                                    'Click <strong>Open EA Token Page</strong> — your browser opens.',
                                    'If you are already logged in to EA, you will see a JSON response. Copy the value of <code>access_token</code> and paste it below.',
                                    'If you are not logged in, sign in at <a href="https://www.ea.com" target="_blank">ea.com</a> first, then click Open again.',
                                ],
                                'input_placeholder': 'Paste access_token value here',
                                'open_label': 'Open EA Token Page',
                                'submit_label': 'Connect',
                            }},
                        ],
                        'connected': [
                            {'type': 'connected_label'},
                            {'type': 'button', 'label': 'Sync Library', 'action': {'type': 'call', 'fn': 'eaSync'}},
                            {'type': 'button', 'label': 'Disconnect', 'variant': 'muted', 'action': {
                                'type': 'post', 'endpoint': '/api/ea_app/disconnect',
                                'on_success': 'refresh_auth',
                            }},
                            {'type': 'status_output', 'key': 'main'},
                        ],
                    },
                },
                launcher_section,
                {
                    'title': 'Library',
                    'items': [
                        {'type': 'text', 'content': 'Fix store page links for games where the URL does not resolve correctly. Does not require an EA account.'},
                        {'type': 'button', 'label': 'Fix Store Links', 'action': {
                            'type': 'call', 'fn': 'eaFixSlugs',
                        }},
                    ],
                },
            ],
        }

    date_import_url = 'https://myaccount.ea.com/am/ui/payment-wallet/order-history'

    def fetch_description(self, appid, platform_id):
        from .ea import fetch_description
        return fetch_description(appid, platform_id)

    def rescrape(self, appid):
        from .ea import scrape_single
        return scrape_single(appid) or None

    def fragments(self):
        return {
            'base_head_styles': 'ea_app_base_head_styles.html',
            'tools_scripts':    'ea_app_tools_scripts.html',
        }


plugin = EAAppPlugin()
