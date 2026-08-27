"""
runners/launcher_installer.py - Generic Wine-based launcher installer for plugins.

Plugins declare an installer in plugin.json under launcher.installer -- see
PLUGINS.md's "launcher.installer field" section for the full schema
(url, type: msi/exe/extract, winearch, win_version, winetricks,
post_install_files, post_install_dlls, install_path, env).

exe_name is taken from launcher.exe_name if not also set on installer itself
(used to verify success). prefix/wine_bin come from the user via the UI
(defaults applied by caller).
"""

import logging
import os
import subprocess
import tempfile
import threading

import requests

from runners.sandbox import IN_FLATPAK, host_is_executable, host_popen, host_run, host_which

log = logging.getLogger(__name__)

_states: dict = {}
_lock = threading.Lock()

_DEFAULT_PREFIX_BASE = os.path.join(os.path.expanduser('~'), '.local', 'share', 'PlayDate')


def default_prefix(platform_id: str) -> str:
    return os.path.join(_DEFAULT_PREFIX_BASE, platform_id)


def get_state(platform_id: str) -> dict:
    with _lock:
        return dict(_states.get(platform_id, {}))


def start_install(platform_id: str, installer_cfg: dict, prefix: str, wine_bin: str | None = None) -> bool:
    """
    Start a background launcher install. Returns False if one is already running.
    installer_cfg keys: url, type ('msi'/'exe'), winearch, exe_name
    """
    with _lock:
        state = _states.get(platform_id, {})
        if state.get('phase') and not state.get('done') and not state.get('error'):
            return False
        _states[platform_id] = {
            'phase': 'starting', 'detail': 'Starting...', 'done': False, 'error': None,
        }
    threading.Thread(
        target=_run_install,
        args=(platform_id, installer_cfg, prefix, wine_bin),
        daemon=True,
    ).start()
    return True


def _set(platform_id, phase, detail):
    with _lock:
        _states[platform_id].update({'phase': phase, 'detail': detail})


def _fail(platform_id, msg):
    log.error('Launcher install [%s]: %s', platform_id, msg)
    with _lock:
        _states[platform_id].update({'phase': 'error', 'detail': msg, 'done': False, 'error': msg})


def _finish(platform_id, prefix, wine_bin):
    from config import save_launcher_config
    cfg = {'prefix': prefix, 'mode': 'wine'}
    if wine_bin:
        cfg['wine_bin'] = wine_bin
    save_launcher_config(platform_id, cfg)

    # Optional plugin fixup of the freshly-installed launcher in its prefix --
    # e.g. Epic applies a launcher self-update the MSI staged but can't run
    # itself under Wine, which otherwise loops the launcher on first start.
    try:
        import plugins
        plugin = plugins.get_for_platform(platform_id)
        if plugin is not None and hasattr(plugin, 'on_launcher_installed'):
            _set(platform_id, 'verifying', 'Finalizing launcher setup...')
            plugin.on_launcher_installed(prefix, wine_bin)
    except Exception as e:
        log.warning('Launcher install [%s]: on_launcher_installed hook failed: %s', platform_id, e)

    with _lock:
        _states[platform_id].update({
            'phase': 'done', 'detail': 'Launcher installed successfully.', 'done': True, 'error': None,
        })


def _copy_post_install_dlls(platform_id: str, installer_cfg: dict, wb: str, prefix: str):
    import shutil
    dlls = installer_cfg.get('post_install_dlls', [])
    if not dlls:
        return
    # Derive Proton files/ root from wine binary path: .../files/bin/wine64 -> .../files
    proton_root = os.path.dirname(os.path.dirname(os.path.abspath(wb)))
    system32 = os.path.join(prefix, 'drive_c', 'windows', 'system32')
    for rel in dlls:
        src = os.path.join(proton_root, rel)
        dst = os.path.join(system32, os.path.basename(rel))
        if not os.path.isfile(src):
            log.warning('Launcher install [%s]: post_install_dll not found, skipping: %s', platform_id, src)
            continue
        try:
            shutil.copy2(src, dst)
            log.info('Launcher install [%s]: copied %s -> %s', platform_id, src, dst)
        except Exception as e:
            log.warning('Launcher install [%s]: failed to copy %s: %s', platform_id, src, e)


def _write_post_install_files(platform_id: str, installer_cfg: dict, prefix: str):
    """Write config files into the prefix after install, e.g. to pre-disable
    a launcher's overlay before its first run. installer_cfg['post_install_files']
    entries: {'path': path relative to the user profile dir, 'content': str}."""
    entries = installer_cfg.get('post_install_files', [])
    if not entries:
        return
    from runners.wine import wine_user_dir
    user_dir = wine_user_dir(prefix)
    if not user_dir:
        log.warning('Launcher install [%s]: could not resolve Wine user profile dir for post_install_files', platform_id)
        return
    for entry in entries:
        dst = os.path.join(user_dir, entry['path'].replace('\\', os.sep))
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'w', encoding='utf-8') as f:
                f.write(entry['content'])
            log.info('Launcher install [%s]: wrote %s', platform_id, dst)
        except Exception as e:
            log.warning('Launcher install [%s]: failed to write %s: %s', platform_id, dst, e)


def _run_install(platform_id: str, installer_cfg: dict, prefix: str, wine_bin: str | None):
    import shutil
    from runners.wine import find_wine_binary

    from runners.wine import build_proton_env, find_proton_wine, is_proton_wine, _build_run, find_umu_run, _proton_root
    if wine_bin and not host_is_executable(wine_bin):
        log.warning('Launcher install [%s]: saved wine_bin no longer exists on host (%s), re-detecting',
                    platform_id, wine_bin)
        wine_bin = None
    wb = wine_bin or find_proton_wine() or find_wine_binary()
    if not wb:
        _fail(platform_id, 'No Wine binary found. Install Wine or GE-Proton via Steam.')
        return

    prefix = os.path.expanduser(prefix)
    winearch       = installer_cfg.get('winearch', 'win64')
    installer_type = installer_cfg.get('type', 'msi')
    url            = installer_cfg.get('url', '')
    exe_name       = installer_cfg.get('exe_name', '')
    win_version    = installer_cfg.get('win_version', '')
    extra_env      = installer_cfg.get('env', {})
    winetricks_verbs = installer_cfg.get('winetricks', [])

    if is_proton_wine(wb):
        extra_env = {'WINEFSYNC': '1', 'WINEESYNC': '1', **extra_env}
        log.info('Launcher install [%s]: Proton wine detected, adding WINEFSYNC/WINEESYNC', platform_id)
    log.info('Launcher install [%s]: wine=%s prefix=%s arch=%s win_version=%r extra_env=%s',
             platform_id, wb, prefix, winearch, win_version, list(extra_env.keys()))

    if not url:
        _fail(platform_id, 'No installer URL configured for this plugin.')
        return

    # Step 1: Create Wine prefix
    # Prefer umu-run's Steam Runtime container over a raw Proton wineboot
    # invocation when both umu-run and a real Proton build are available --
    # confirmed live that raw `wine wineboot --init` can hang indefinitely
    # (stuck in wine.inf's InstallHinfSection, 0% CPU) regardless of which
    # Proton/Wine-GE build is used, while the same operation through umu-run
    # completes cleanly every time. See runners.wine._build_run.
    _set(platform_id, 'creating_prefix', 'Creating Wine prefix...')
    try:
        if os.path.isdir(prefix):
            # A leftover Wine session (launcher still running, or a prior
            # install that looped) holding this prefix open would make the
            # wineboot below run against a half-live prefix. Clear it first.
            try:
                from runners.wine import end_prefix_session
                end_prefix_session(prefix, wb)
            except Exception as e:
                log.warning('Launcher install [%s]: could not end stale Wine session: %s', platform_id, e)
        os.makedirs(prefix, exist_ok=True)
        cmd_prefix, env = _build_run(prefix, wb, extra_env)
        env['WINEARCH'] = winearch
        via_umu = cmd_prefix[0] != wb
        r = host_run(
            cmd_prefix + ['wineboot', '--init'],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        log.info('Launcher install [%s]: wineboot exit=%d%s', platform_id, r.returncode,
                 ' (via umu-run)' if via_umu else '')
        if r.returncode != 0:
            err = r.stderr.decode('utf-8', errors='replace')[:1000]
            _fail(platform_id, f'Failed to create Wine prefix (wineboot exit {r.returncode}): {err}')
            return
        if win_version:
            r2 = host_run(
                [wb, 'reg', 'add', r'HKCU\Software\Wine', '/v', 'Version',
                 '/d', win_version, '/f'],
                env={**(build_proton_env(wb) if is_proton_wine(wb) else dict(os.environ)),
                     'WINEPREFIX': prefix, 'WINEARCH': winearch, 'WINEDEBUG': '-all', **extra_env},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            log.info('Launcher install [%s]: set win_version=%s exit=%d', platform_id, win_version, r2.returncode)
    except Exception as e:
        _fail(platform_id, f'Failed to create Wine prefix: {e}')
        return

    # Step 2: Winetricks dependencies
    if winetricks_verbs:
        wt = host_which('winetricks')
        if not wt:
            _fail(platform_id, 'winetricks is required but not found — install it (e.g. sudo dnf install winetricks)')
            return
        # Proton wine binaries require the Steam runtime to run standalone and
        # are incompatible with winetricks on their own. umu-run supplies
        # that runtime directly (confirmed live: `umu-run winetricks
        # --unattended <verb>` works with no extra WINE= substitution
        # needed); without umu-run, fall back to system wine for this step
        # as before -- it can install DLLs into a Proton prefix just fine.
        umu_proton_root = _proton_root(wb) if find_umu_run() else None
        wt_wine = wb
        if not umu_proton_root and is_proton_wine(wb):
            system_wine = host_which('wine')
            if system_wine:
                log.info('Launcher install [%s]: Proton detected — using system wine (%s) for winetricks', platform_id, system_wine)
                wt_wine = system_wine
            else:
                log.warning('Launcher install [%s]: Proton detected but no system wine found — winetricks may fail', platform_id)
        for verb in winetricks_verbs:
            _set(platform_id, 'winetricks', f'Installing {verb} via winetricks...')
            if umu_proton_root:
                # Bare command name, not wt's absolute host path: Proton's own
                # winetricks handling re-execs this inside the pressure-vessel
                # container, which doesn't bind-mount /usr/bin at the host's
                # path -- confirmed live that the absolute path 404s inside
                # the container while the bare name resolves correctly.
                cmd = [find_umu_run(), 'winetricks', '--unattended', verb]
                env = {**os.environ, 'WINEPREFIX': prefix, 'WINEARCH': winearch, 'WINEDEBUG': '-all',
                       'GAMEID': 'umu-default', 'PROTONPATH': umu_proton_root}
            else:
                cmd = [wt, '--unattended', verb]
                env = {**os.environ, 'WINEPREFIX': prefix, 'WINEARCH': winearch,
                       'WINE': wt_wine, 'WINEDEBUG': '-all'}
            try:
                r = host_run(
                    cmd,
                    env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                log.info('Launcher install [%s]: winetricks %s exit=%d', platform_id, verb, r.returncode)
                if r.returncode != 0:
                    err = r.stderr.decode('utf-8', errors='replace')[:500]
                    log.warning('Launcher install [%s]: winetricks %s stderr: %s', platform_id, verb, err)
            except Exception as e:
                _fail(platform_id, f'winetricks {verb} failed: {e}')
                return

    # Pre-seed config files (e.g. disabling an overlay) before the installer
    # runs, since some installers auto-launch the app once on completion --
    # writing this after install would be too late to affect that first run.
    _write_post_install_files(platform_id, installer_cfg, prefix)

    # Step 3: Download installer
    _set(platform_id, 'downloading', 'Downloading installer...')
    # Under Flatpak, wine/7z run on the host via flatpak-spawn --host and can't
    # see the sandbox's private /tmp — use a dir under $HOME instead, which is
    # bind-mounted identically in both namespaces.
    if IN_FLATPAK:
        _tmp_base = os.path.join(os.path.expanduser('~/.cache/playdate/tmp'))
        os.makedirs(_tmp_base, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(prefix=f'playdate_{platform_id}_', dir=_tmp_base)
    else:
        tmp_dir = tempfile.mkdtemp(prefix=f'playdate_{platform_id}_')
    ext = '.msi' if installer_type == 'msi' else '.exe'
    installer_path = os.path.join(tmp_dir, f'installer{ext}')
    try:
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        size = 0
        with open(installer_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                size += len(chunk)
        log.info('Launcher install [%s]: downloaded %d bytes to %s', platform_id, size, installer_path)
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _fail(platform_id, f'Download failed: {e}')
        return

    # Step 4: Install
    if installer_type == 'extract':
        # Extract the archive directly into the prefix using 7z, bypassing Wine UAC.
        # Used for installers (e.g. NSIS) that refuse to run without requireAdministrator.
        install_path = installer_cfg.get('install_path', '')
        if not install_path:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _fail(platform_id, 'install_path required for extract-type installer')
            return
        dest = os.path.join(prefix, 'drive_c', install_path.replace('\\', os.sep))
        os.makedirs(dest, exist_ok=True)
        _set(platform_id, 'installing', 'Extracting files...')
        try:
            r = host_run(
                ['7z', 'e', installer_path, f'-o{dest}', '-y'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            log.info('Launcher install [%s]: 7z exit=%d dest=%s', platform_id, r.returncode, dest)
            if r.returncode not in (0, 1):  # 7z returns 1 for warnings (acceptable)
                err = r.stderr.decode('utf-8', errors='replace')[:500]
                shutil.rmtree(tmp_dir, ignore_errors=True)
                _fail(platform_id, f'Extraction failed (7z exit {r.returncode}): {err}')
                return
        except FileNotFoundError:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _fail(platform_id, '7z not found — install p7zip (e.g. sudo dnf install p7zip p7zip-plugins)')
            return
        except Exception as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _fail(platform_id, f'Extraction error: {e}')
            return
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        # Run installer interactively in Wine (user completes the setup window).
        # stdout/stderr go to real files, not PIPE: some installers (e.g. EA's)
        # hand off to a persistent background service that inherits the pipe's
        # write end, so a PIPE + communicate() never sees EOF and hangs forever
        # even after the installer itself has long since exited. wait() only
        # cares about our direct child's own exit, not who still holds the fds.
        _set(platform_id, 'installing', 'Running installer — complete the setup window...')
        out_path = os.path.join(tmp_dir, 'stdout.log')
        err_path = os.path.join(tmp_dir, 'stderr.log')
        try:
            if installer_type == 'msi':
                # msiexec is a Wine built-in name, not a real path -- umu-run's
                # exe-vs-unix-path detection is unverified for that case, so
                # this stays on the direct wine_bin invocation.
                base_env = build_proton_env(wb) if is_proton_wine(wb) else dict(os.environ)
                env = {**base_env, 'WINEPREFIX': prefix, 'WINEDEBUG': '-all', **extra_env}
                cmd = [wb, 'msiexec', '/i', installer_path]
            else:
                # PROTON_VERB=run, not umu-run's default waitforexitandrun --
                # the latter waits for the *entire* Wine session's process
                # tree to empty, not just the installer's own process.
                # Confirmed live: an installer whose last step auto-launches
                # the newly-installed app (e.g. EA Desktop, left running for
                # the user) then never lets this wait return on its own, since
                # that app is *meant* to stay open -- this isn't occasional,
                # it happens on every install that ends in an auto-launch.
                # 'run' just waits for the installer's own process to exit,
                # like runners/proton.py's regular 'proton run' launches do.
                cmd_prefix, env = _build_run(prefix, wb, {**extra_env, 'PROTON_VERB': 'run'})
                cmd = cmd_prefix + [installer_path]
            log.info('Launcher install [%s]: running %s', platform_id, cmd)
            with open(out_path, 'wb') as out_f, open(err_path, 'wb') as err_f:
                proc = host_popen(cmd, env=env, stdout=out_f, stderr=err_f)
                try:
                    proc.wait(timeout=600)
                    log.info('Launcher install [%s]: installer exit code %d', platform_id, proc.returncode)
                except subprocess.TimeoutExpired:
                    log.warning('Launcher install [%s]: installer did not exit within 600s — '
                                'proceeding to verification anyway', platform_id)
            if proc.returncode not in (None, 0):
                err = open(err_path, 'rb').read()
                out = open(out_path, 'rb').read()
                if err:
                    log.warning('Launcher install [%s]: installer stderr: %s',
                                platform_id, err.decode('utf-8', errors='replace')[:2000])
                if out:
                    log.warning('Launcher install [%s]: installer stdout: %s',
                                platform_id, out.decode('utf-8', errors='replace')[:2000])
        except Exception as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _fail(platform_id, f'Installer error: {e}')
            return
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if not exe_name:
        _copy_post_install_dlls(platform_id, installer_cfg, wb, prefix)
        _finish(platform_id, prefix, wine_bin)
        return

    # Step 5: Verify exe_name appears somewhere in the prefix
    _set(platform_id, 'verifying', 'Verifying installation...')
    found_exes = []
    for dirpath, _dirs, files in os.walk(prefix):
        for f in files:
            if f.endswith('.exe'):
                found_exes.append(os.path.join(dirpath, f))
    log.info('Launcher install [%s]: found %d .exe files in prefix', platform_id, len(found_exes))
    for p in found_exes:
        if exe_name in p:
            log.info('Launcher install [%s]: found target exe at %s', platform_id, p)
    found = any(exe_name in fp for fp in found_exes)
    if not found:
        non_wine = [p for p in found_exes if 'windows' not in p.lower() and 'system32' not in p.lower()]
        log.warning('Launcher install [%s]: %s not found; non-system exes: %s',
                    platform_id, exe_name, non_wine[:20])
        _fail(platform_id, f'{exe_name} not found after installation. Did the setup complete?')
        return

    _copy_post_install_dlls(platform_id, installer_cfg, wb, prefix)
    _finish(platform_id, prefix, wine_bin)
