"""
runners/wine.py — Shared Wine helpers for plugins that need to run Windows executables.
"""

import logging
import os
import subprocess
import threading

from runners.sandbox import IN_FLATPAK, host_is_executable, host_popen, host_run, host_which

log = logging.getLogger(__name__)

_prefix_locks = {}
_prefix_locks_guard = threading.Lock()


def _get_prefix_lock(prefix_path):
    """One lock per prefix (by absolute path), created on first use. Guards
    the already-running-session check/kill/relaunch decision in
    launch_protocol_url() and run_in_prefix() -- confirmed live that without
    this, rapid repeated launch clicks let multiple Flask request threads
    race through that logic concurrently against the same prefix, each
    acting on stale state: multiple umu-run containers ended up fighting
    over the same prefix simultaneously, leaving stuck wineserver instances
    behind and even crashing pressure-vessel itself with an internal
    assertion failure (_srt_architecture_read_elf) from two containers
    racing for the same resources. The lock only needs to hold for the
    synchronous decide-and-dispatch step, not the launched process's whole
    lifetime -- host_popen() returns immediately either way."""
    with _prefix_locks_guard:
        key = os.path.abspath(prefix_path)
        lock = _prefix_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _prefix_locks[key] = lock
        return lock

_WINE_CANDIDATES = [
    'wine64',
    'wine',
]

_WINE_PATHS = [
    '/usr/bin',
    '/usr/local/bin',
    '/opt/wine/bin',
    '/opt/wine-stable/bin',
    '/opt/wine-staging/bin',
    '/opt/wine-devel/bin',
]


def find_wine_binary():
    """
    Return the absolute path to a wine binary, or None if not found.
    Prefers wine64; falls back to wine. Searches PATH first, then common distro paths.

    Under Flatpak, this process's own PATH/filesystem view is the sandbox's,
    not the host's, so binaries at e.g. /usr/bin/wine64 are checked against
    the host via host_which()/host_is_executable() instead.
    """
    for candidate in _WINE_CANDIDATES:
        found = host_which(candidate)
        if found:
            return found

    search_dirs = []
    path_env = os.environ.get('PATH', '')
    if path_env:
        search_dirs.extend(path_env.split(os.pathsep))
    for d in _WINE_PATHS:
        if d not in search_dirs:
            search_dirs.append(d)

    for candidate in _WINE_CANDIDATES:
        for d in search_dirs:
            full = os.path.join(d, candidate)
            if host_is_executable(full):
                return full
    return None


def find_proton_wine():
    """
    Return the wine64 (or wine) binary from the best available Proton install, or None.
    Prefers GE-Proton over official Proton (same priority order as runners/proton.py).
    """
    try:
        from runners.proton import find_proton_versions
    except ImportError:
        return None
    for version in find_proton_versions():
        proton_dir = os.path.dirname(os.path.abspath(version['path']))
        bin_dir = os.path.join(proton_dir, 'files', 'bin')
        for candidate in ('wine64', 'wine'):
            wb = os.path.join(bin_dir, candidate)
            if os.path.isfile(wb) and os.access(wb, os.X_OK):
                return wb
    return None


def is_proton_wine(wine_bin):
    """Return True if wine_bin is the wine binary from inside a Proton install."""
    return wine_bin is not None and (
        'GE-Proton' in wine_bin
        or 'Proton' in wine_bin
        or '/files/bin/wine' in wine_bin
    )


def wine_user_dir(prefix):
    """Resolve the prefix's real Windows user profile directory. Proton
    prefixes always use 'steamuser'; vanilla Wine uses the real Unix
    username. Falls back to scanning drive_c/users/ for whichever single
    real profile exists, skipping the fixed system entries Wine always
    creates."""
    users_dir = os.path.join(prefix, 'drive_c', 'users')
    for candidate in ('steamuser', os.environ.get('USER', '')):
        if candidate and os.path.isdir(os.path.join(users_dir, candidate)):
            return os.path.join(users_dir, candidate)
    skip = {'Public', 'Default User', 'Default', 'All Users'}
    try:
        for name in os.listdir(users_dir):
            if name not in skip and os.path.isdir(os.path.join(users_dir, name)):
                return os.path.join(users_dir, name)
    except OSError:
        pass
    return None


def find_umu_run():
    """Return the umu-run binary path if installed on the host, else None."""
    return host_which('umu-run')


def _proton_root(wine_bin):
    """
    Given a Proton wine64/wine binary (.../<ProtonDir>/files/bin/wine64),
    return the Proton install root umu-run needs as PROTONPATH, or None if
    wine_bin isn't actually a Proton install (no toolmanifest.vdf next to it).
    """
    if not is_proton_wine(wine_bin):
        return None
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(wine_bin))))
    if os.path.isfile(os.path.join(root, 'toolmanifest.vdf')):
        return root
    return None


def _build_run(prefix_path, wine_bin, env_extra=None):
    """
    Return (cmd_prefix, env) for invoking wine -- preferring umu-run's Steam
    Runtime container over a raw Proton wine64 invocation when both umu-run
    and a real Proton build (with toolmanifest.vdf) are available. Confirmed
    live that a raw `wine wineboot --init` can hang indefinitely (stuck in
    wine.inf's InstallHinfSection, 0% CPU) regardless of which Proton/Wine-GE
    build was used, while the identical operation through umu-run completes
    cleanly -- this isn't about which wine build, it's the container umu-run
    sets up around it. cmd_prefix is prepended to the target exe/args; env
    already has WINEPREFIX and WINEDEBUG set.
    """
    umu = find_umu_run()
    proton_root = _proton_root(wine_bin) if umu else None
    if umu and proton_root:
        env = dict(os.environ)
        env['WINEPREFIX'] = prefix_path
        env['WINEDEBUG']  = '-all'
        env['GAMEID']     = 'umu-default'
        env['PROTONPATH'] = proton_root
        if env_extra:
            env.update(env_extra)
        return [umu], env

    env = build_proton_env(wine_bin) if is_proton_wine(wine_bin) else _prefer_native_wayland(dict(os.environ))
    env['WINEPREFIX'] = prefix_path
    env['WINEDEBUG']  = '-all'
    if env_extra:
        env.update(env_extra)
    return [wine_bin], env


def _prefer_native_wayland(env):
    """On a Wayland session, drop DISPLAY so Wine selects its native Wayland
    driver instead of falling back to XWayland compatibility. Confirmed live
    (KDE Plasma Wayland) that a self-contained, non-Proton Wine build left a
    Chromium-based app's window slow and blank-white with clicks not
    registering under XWayland, while native Wayland rendered and responded
    correctly. Proton builds already force native Wayland internally
    regardless of DISPLAY, so this only matters for plain wine invocations."""
    if env.get('WAYLAND_DISPLAY') and 'DISPLAY' in env:
        env = dict(env)
        del env['DISPLAY']
    return env


def _pe_arch_dir(exe_path):
    """Return 'x86_64-windows' or 'i386-windows' for a PE exe's own bitness
    (read from the COFF header Machine field), or None if it can't be
    determined. Used to pick the one WINEDLLPATH vkd3d/wine dir that actually
    matches the process being launched -- see build_proton_env()."""
    try:
        with open(exe_path, 'rb') as f:
            dos_header = f.read(64)
            if len(dos_header) < 64 or dos_header[:2] != b'MZ':
                return None
            pe_offset = int.from_bytes(dos_header[60:64], 'little')
            f.seek(pe_offset)
            pe_header = f.read(6)
            if len(pe_header) < 6 or pe_header[:4] != b'PE\x00\x00':
                return None
            machine = int.from_bytes(pe_header[4:6], 'little')
    except OSError:
        return None
    if machine == 0x8664:   # IMAGE_FILE_MACHINE_AMD64
        return 'x86_64-windows'
    if machine == 0x014c:   # IMAGE_FILE_MACHINE_I386
        return 'i386-windows'
    return None


def build_proton_env(wine_bin, base_env=None, exe_path=None):
    """
    Return an env dict with LD_LIBRARY_PATH and WINEDLLPATH set up for a Proton
    wine binary, mirroring what the Proton script does when launching via Steam.

    wine_bin must be the path to wine64/wine inside a Proton 'files/bin/' directory.
    base_env defaults to os.environ if not provided.
    exe_path : the .exe actually being launched, if known. When its bitness
        can be read, the vkd3d WINEDLLPATH dir is skipped entirely rather
        than picking the matching-arch one -- confirmed live (2026-09-04,
        GTA: San Andreas, a 32-bit game) that even the *correct*-arch
        libvkd3d-utils-1.dll from Proton's own files/lib/vkd3d/ is a
        different build than the one already paired with this prefix's own
        wined3d.dll in system32/syswow64 (itself provisioned by the same
        umu-run/Proton bootstrap every plugin prefix goes through), and
        forcing the mismatched pair aborts with "unimplemented function
        libvkd3d-utils-1.dll.vkd3d_utils_set_log_callback" -- Wine's normal
        DLL search already resolves vkd3d correctly from the prefix itself
        once WINEDLLPATH doesn't shadow it. (Listing the wrong-arch dir
        unconditionally, the previous bug here, failed even harder: an
        outright STATUS_INVALID_IMAGE_FORMAT / c000007b load failure that
        doesn't fall through to try another WINEDLLPATH entry, cascading
        into wined3d.dll / DDRAW.dll never loading at all.) Omit exe_path
        (or pass an exe whose bitness can't be read) to fall back to the
        previous both-arch-dirs behavior, kept for callers with no single
        target exe (e.g. launch_protocol_url, an installer run) where this
        fix hasn't been verified.
    """
    env = dict(base_env if base_env is not None else os.environ)

    # Derive the Proton files/ root: files/bin/wine64 → files/
    files_dir = os.path.dirname(os.path.dirname(os.path.abspath(wine_bin)))
    lib_dir   = os.path.join(files_dir, 'lib')

    # Linux shared libraries Proton wine needs at runtime
    ld_extra = [
        os.path.join(lib_dir, 'x86_64-linux-gnu'),
        os.path.join(lib_dir, 'i386-linux-gnu'),
        lib_dir,
    ]
    existing_ld = env.get('LD_LIBRARY_PATH', '')
    env['LD_LIBRARY_PATH'] = ':'.join(p for p in ld_extra if os.path.isdir(p)) + (
        (':' + existing_ld) if existing_ld else ''
    )

    # WINEDLLPATH: wine overrides, plus a vkd3d fallback dir only when we
    # don't know the target exe's bitness -- see the exe_path note above.
    arch_dir = _pe_arch_dir(exe_path) if exe_path else None
    dll_extra = []
    if arch_dir:
        dll_extra += [os.path.join(lib_dir, 'wine', arch_dir), os.path.join(lib_dir, 'wine')]
    else:
        arch_dirs = ['x86_64-windows', 'i386-windows']
        dll_extra += [os.path.join(lib_dir, 'vkd3d', d) for d in arch_dirs]
        dll_extra.append(os.path.join(lib_dir, 'vkd3d'))
        dll_extra += [os.path.join(lib_dir, 'wine', d) for d in arch_dirs]
        dll_extra.append(os.path.join(lib_dir, 'wine'))
    existing_dll = env.get('WINEDLLPATH', '')
    env['WINEDLLPATH'] = ':'.join(p for p in dll_extra if os.path.isdir(p)) + (
        (':' + existing_dll) if existing_dll else ''
    )

    return env


def install_dxvk(prefix_path, wine_bin):
    """
    Copy DXVK DLLs from a Proton bundle into a Wine prefix's system32/syswow64,
    and set DLL overrides in the prefix registry so Wine uses them.

    No-op if DXVK is already installed (detected by checking dxgi.dll size --
    DXVK's dxgi.dll is much larger than Wine's stub).
    Raises RuntimeError if Proton's DXVK bundle cannot be found.
    """
    files_dir = os.path.dirname(os.path.dirname(os.path.abspath(wine_bin)))
    dxvk64    = os.path.join(files_dir, 'lib', 'wine', 'dxvk', 'x86_64-windows')
    dxvk32    = os.path.join(files_dir, 'lib', 'wine', 'dxvk', 'i386-windows')
    vkd3d64   = os.path.join(files_dir, 'lib', 'vkd3d', 'x86_64-windows')
    vkd3d32   = os.path.join(files_dir, 'lib', 'vkd3d', 'i386-windows')

    if not os.path.isdir(dxvk64):
        raise RuntimeError(f'DXVK bundle not found in Proton at {dxvk64}')

    sys32  = os.path.join(prefix_path, 'drive_c', 'windows', 'system32')
    syswow = os.path.join(prefix_path, 'drive_c', 'windows', 'syswow64')

    # Check if already installed (DXVK dxgi.dll is >500KB; Wine's stub is <100KB)
    dxgi_dest = os.path.join(sys32, 'dxgi.dll')
    if os.path.isfile(dxgi_dest) and os.path.getsize(dxgi_dest) > 200_000:
        log.info(f'DXVK already installed in prefix {prefix_path}')
        return

    dxvk_dlls = ['d3d9.dll', 'd3d10core.dll', 'd3d11.dll', 'dxgi.dll']
    vkd3d_dlls = ['libvkd3d-1.dll', 'libvkd3d-shader-1.dll']

    import shutil
    for dll in dxvk_dlls:
        src = os.path.join(dxvk64, dll)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(sys32, dll))
        src32 = os.path.join(dxvk32, dll)
        if os.path.isdir(syswow) and os.path.isfile(src32):
            shutil.copy2(src32, os.path.join(syswow, dll))

    for dll in vkd3d_dlls:
        src = os.path.join(vkd3d64, dll)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(sys32, dll))
        src32 = os.path.join(vkd3d32, dll)
        if os.path.isdir(syswow) and os.path.isfile(src32):
            shutil.copy2(src32, os.path.join(syswow, dll))

    log.info(f'DXVK installed into prefix {prefix_path}')

    # Set DLL overrides so Wine uses these native DLLs
    env = build_proton_env(wine_bin)
    env['WINEPREFIX'] = prefix_path
    env['WINEDEBUG']  = '-all'
    overrides = {'dxgi': 'native,builtin', 'd3d9': 'native,builtin',
                 'd3d10core': 'native,builtin', 'd3d11': 'native,builtin'}
    for dll, value in overrides.items():
        host_run(
            [wine_bin, 'reg', 'add',
             r'HKEY_CURRENT_USER\Software\Wine\DllOverrides',
             '/v', dll, '/t', 'REG_SZ', '/d', value, '/f'],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def list_prefixes(search_dirs):
    """
    Return a list of Wine prefix paths found under the given directories.
    A directory is considered a prefix if it contains a 'drive_c' subdirectory.

    search_dirs : list of directory paths to search (one level deep)
    """
    prefixes = []
    for base in search_dirs:
        base = os.path.expanduser(base)
        if not os.path.isdir(base):
            continue
        try:
            for entry in os.scandir(base):
                if entry.is_dir() and os.path.isdir(os.path.join(entry.path, 'drive_c')):
                    prefixes.append(entry.path)
        except PermissionError:
            pass
    return prefixes


def create_prefix(prefix_path, wine_bin=None):
    """
    Initialise a Wine prefix at prefix_path.
    Runs `WINEPREFIX=<prefix_path> wine wineboot --init` and waits for it to finish.
    Raises RuntimeError if wine_bin is None and no wine binary can be found.
    """
    if wine_bin is None:
        wine_bin = find_wine_binary()
        if not wine_bin:
            raise RuntimeError('No Wine binary found. Install Wine to use this plugin.')

    os.makedirs(prefix_path, exist_ok=True)
    cmd_prefix, env = _build_run(prefix_path, wine_bin)

    log.info(f'Creating Wine prefix at {prefix_path} using {wine_bin}'
             + (' via umu-run' if cmd_prefix[0] != wine_bin else ''))
    host_run(
        cmd_prefix + ['wineboot', '--init'],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_in_prefix(prefix_path, exe, args=None, wine_bin=None, env_extra=None, cwd=None,
                  restart_session_if_running=False):
    """
    Launch a Windows executable inside a Wine prefix.

    prefix_path : path to the Wine prefix directory
    exe         : absolute path to the .exe to run
    args        : list of extra arguments to pass to the executable
    wine_bin    : path to the wine binary; auto-detected if None
    env_extra   : dict of additional environment variables
    cwd         : working directory for the process; defaults to the exe's
                  own directory (what a real launcher does -- confirmed live
                  that omitting this breaks a real game, which failed to
                  find its own relative-path data files when the process
                  inherited PlayDate's cwd instead)
    restart_session_if_running : see launch_protocol_url(). Default False --
                  a live session here is usually another running game that
                  must not be killed. Pass True only when this call is meant
                  to replace a specific launcher client whose session is safe
                  to end first (Ubisoft Connect).

    Returns a subprocess.Popen object (caller should not wait -- game runs in background).
    Raises RuntimeError if no Wine binary is available.
    """
    if wine_bin is None:
        wine_bin = find_wine_binary()
        if not wine_bin:
            raise RuntimeError('No Wine binary found. Install Wine to use this plugin.')

    if cwd is None:
        cwd = os.path.dirname(exe)

    with _get_prefix_lock(prefix_path):
        already_running = _prefix_has_running_process(prefix_path)
        proton = is_proton_wine(wine_bin)

        if not already_running:
            cmd_prefix, env = _build_run(prefix_path, wine_bin, env_extra)
            log.info(f'Wine launch: {" ".join(cmd_prefix)} {exe}  (prefix={prefix_path}, cwd={cwd})')
        elif restart_session_if_running and proton:
            log.info(f'Wine launch: {exe} -- ending the existing Proton session for '
                     f'{prefix_path} first, then cold-starting')
            end_prefix_session(prefix_path, wine_bin)
            cmd_prefix, env = _build_run(prefix_path, wine_bin, env_extra)
        else:
            # Live session, caller does not want it killed (default). For a
            # plain game prefix that live session is another running game --
            # never kill it. Add this process to the session with a plain
            # `wine` call (no container). PROVISIONAL for Proton: verify the
            # exe actually runs/renders joined to a umu-started session
            # without the Steam Runtime around it; if not, that caller needs
            # restart_session_if_running=True. exe_path=exe lets
            # build_proton_env() pick the WINEDLLPATH vkd3d/wine dir matching
            # this exe's own bitness -- see its docstring.
            env = build_proton_env(wine_bin, exe_path=exe) if proton else _prefer_native_wayland(dict(os.environ))
            env['WINEPREFIX'] = prefix_path
            if env_extra:
                env.update(env_extra)
            cmd_prefix = [wine_bin]
            log.info(f'Wine launch: {exe}  (prefix={prefix_path}, cwd={cwd}) '
                     f'direct into live session (proton={proton})')

        cmd = cmd_prefix + [exe] + (args or [])
        return host_popen(cmd, env=env, cwd=cwd)


def launch_protocol_url(prefix_path, url, wine_bin=None, env_extra=None,
                        restart_session_if_running=False):
    """
    Open a Windows protocol URL (e.g. com.epicgames.launcher://...) inside a Wine
    prefix using `wine start <url>`. Returns a subprocess.Popen object.
    Raises RuntimeError if no Wine binary is found.

    restart_session_if_running: when a Wine session is already live for this
        prefix AND it's a Proton wine_bin, end that session and cold-start a
        fresh one before delivering the URL. Default False -- most launchers
        (Epic, EA) accept a deep link into the running instance via a plain
        `wine start`, and for a plain game prefix a live session is another
        running game that must not be killed. Set True only for a launcher
        confirmed not to accept deep links while running (Ubisoft Connect).
    """
    if wine_bin is None:
        wine_bin = find_wine_binary()
        if not wine_bin:
            raise RuntimeError('No Wine binary found. Install Wine to use this plugin.')

    with _get_prefix_lock(prefix_path):
        already_running = _prefix_has_running_process(prefix_path)
        proton = is_proton_wine(wine_bin)

        if not already_running:
            # Cold start -- full container (umu-run for Proton).
            cmd_prefix, env = _build_run(prefix_path, wine_bin, env_extra)
            cmd = cmd_prefix + ['start', url]
            log.info(f'Wine protocol launch: {url}  (prefix={prefix_path})'
                     + (' via umu-run' if cmd_prefix[0] != wine_bin else ''))
        elif restart_session_if_running and proton:
            # Ubisoft Connect's Chromium UI: confirmed live that delivering a
            # deep link to an already-running Proton session does not work by
            # any lightweight means (bare `wine start` can't signal it, a fresh
            # umu-run invocation deadlocks in do_lock_file_wait joining the live
            # session). Ending the old session and cold-starting is the only
            # reliable path -- and correct here, since Ubisoft re-forwards the
            # link to the fresh launcher on startup.
            log.info(f'Wine protocol launch: {url} -- ending the existing Proton session for '
                     f'{prefix_path} first, then cold-starting')
            end_prefix_session(prefix_path, wine_bin)
            cmd_prefix, env = _build_run(prefix_path, wine_bin, env_extra)
            cmd = cmd_prefix + ['start', url]
        else:
            # A session is already live and the caller does NOT want it killed
            # (default -- Epic/EA don't need a restart to receive a deep link,
            # and for a plain game prefix a "running session" is another game
            # that must not be killed). Signal the live session directly with a
            # lightweight `wine start` -- no container. For Proton this uses
            # build_proton_env for the DLL/lib paths but does not go through
            # umu-run (which would deadlock).
            # PROVISIONAL for Proton: `wine start <url>` is IPC to the running
            # wineserver and shouldn't need the Steam Runtime the way a real
            # standalone launch does -- but verify live that the deep link
            # actually reaches the running launcher. If it doesn't, that
            # plugin should pass restart_session_if_running=True.
            env = build_proton_env(wine_bin) if proton else _prefer_native_wayland(dict(os.environ))
            env['WINEPREFIX'] = prefix_path
            if env_extra:
                env.update(env_extra)
            cmd = [wine_bin, 'start', url]
            log.info(f'Wine protocol launch: {url}  (prefix={prefix_path}) '
                     f'direct into live session (proton={proton})')

        proc = host_popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _log_output_async(proc, f'Wine protocol launch ({url})')
        return proc


def list_prefix_processes(prefix_path):
    """Return [(pid, argv0), ...] for every running process whose WINEPREFIX
    matches this prefix. argv0 is that process's own first argv entry (its
    executable path, Windows-style backslashes for a Wine-hosted process).

    Matches both prefix_path itself and prefix_path/pfx -- confirmed live
    that a game launched through Proton/umu-run ends up with
    WINEPREFIX=<prefix_path>/pfx/ (Steam's standard compatdata/<id>/pfx/
    layout), distinct from the bare prefix_path PlayDate itself passes to
    umu-run for the client/launcher process. Missing this match meant a
    running game's own exe was invisible to the scan entirely.

    Inside Flatpak the scan reads the *host's* /proc via flatpak-spawn
    --host: Wine runs host-side in a separate PID namespace (see
    runners/sandbox.py), so the sandbox's own /proc only ever contains
    PlayDate itself. Without this the whole already-running-session /
    running-game detection silently no-ops under Flatpak."""
    abs_prefix = os.path.abspath(prefix_path)
    abs_prefix_pfx = os.path.join(abs_prefix, 'pfx')
    if IN_FLATPAK:
        return _list_prefix_processes_host(abs_prefix, abs_prefix_pfx)
    return _scan_proc_for_prefix('/proc', abs_prefix, abs_prefix_pfx)


def _scan_proc_for_prefix(proc_root, abs_prefix, abs_prefix_pfx):
    """Walk a /proc tree, matching each process's WINEPREFIX env var."""
    results = []
    try:
        for pid in os.listdir(proc_root):
            if not pid.isdigit():
                continue
            try:
                with open(f'{proc_root}/{pid}/environ', 'rb') as f:
                    environ = f.read()
            except OSError:
                continue
            matched = False
            for entry in environ.split(b'\0'):
                if entry.startswith(b'WINEPREFIX='):
                    try:
                        proc_prefix = os.path.abspath(
                            entry[len(b'WINEPREFIX='):].decode('utf-8', 'replace'))
                        matched = proc_prefix in (abs_prefix, abs_prefix_pfx)
                    except OSError:
                        matched = False
                    break
            if not matched:
                continue
            try:
                with open(f'{proc_root}/{pid}/cmdline', 'rb') as f:
                    argv = f.read().split(b'\0')
                argv0 = argv[0].decode('utf-8', 'replace') if argv and argv[0] else ''
            except OSError:
                argv0 = ''
            results.append((int(pid), argv0))
    except OSError:
        pass
    return results


def _list_prefix_processes_host(abs_prefix, abs_prefix_pfx):
    """Flatpak: scan the host's /proc via flatpak-spawn --host. Emits one
    `<pid>\\t<argv0>` line per matching process. Prefix values are passed as
    positional args ($1/$2) so paths with spaces need no escaping."""
    script = (
        'for e in /proc/[0-9]*/environ; do '
        '[ -r "$e" ] || continue; '
        'd=${e%/environ}; pid=${d#/proc/}; '
        'wp=$(tr "\\0" "\\n" 2>/dev/null < "$e" | sed -n "s/^WINEPREFIX=//p" | head -n1); '
        'wp=${wp%/}; '
        '[ "$wp" = "$1" ] || [ "$wp" = "$2" ] || continue; '
        'a=$(tr "\\0" "\\n" 2>/dev/null < "$d/cmdline" | head -n1); '
        'printf "%s\\t%s\\n" "$pid" "$a"; '
        'done'
    )
    try:
        r = subprocess.run(
            ['flatpak-spawn', '--host', 'sh', '-c', script, 'sh', abs_prefix, abs_prefix_pfx],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
        )
    except Exception as e:
        log.warning(f'list_prefix_processes: host /proc scan failed: {e}')
        return []
    results = []
    for line in r.stdout.decode('utf-8', 'replace').splitlines():
        pid, _, argv0 = line.partition('\t')
        if pid.isdigit():
            results.append((int(pid), argv0))
    return results


def _prefix_has_running_process(prefix_path):
    """True if a Wine session is already live for this prefix."""
    return bool(list_prefix_processes(prefix_path))


def end_prefix_session(prefix_path, wine_bin=None):
    """Cleanly end whatever Wine session is running for this prefix (e.g. an
    idle launcher window) via the standard `wineserver -k -w` shutdown, which
    kills every process in the session and blocks until the server itself has
    exited. Needed before:
      - bootstrapping a fresh umu-run launch against a Proton prefix that
        already has a live session (umu-run cannot safely join one -- see
        launch_protocol_url), and
      - deleting or re-bootstrapping a prefix (launcher uninstall/reinstall):
        rmtree/wineboot over files a live wineserver still holds open leaves a
        corrupt prefix behind.

    `-w` is what makes this reliable inside Flatpak, where the process poll
    below can't see host-side Wine processes (separate PID namespace)."""
    import time
    if wine_bin is None:
        wine_bin = find_wine_binary() or ''
    wineserver_bin = os.path.join(os.path.dirname(wine_bin), 'wineserver') if wine_bin else ''
    if not wineserver_bin or not host_is_executable(wineserver_bin):
        wineserver_bin = host_which('wineserver') or 'wineserver'
    env = dict(os.environ)
    env['WINEPREFIX'] = prefix_path
    try:
        host_run([wineserver_bin, '-k', '-w'], env=env, timeout=20,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log.warning(f'wineserver -k -w failed for {prefix_path}: {e}')
    for _ in range(10):
        if not _prefix_has_running_process(prefix_path):
            return
        time.sleep(0.5)
    log.warning(f'Wine session for {prefix_path} still shows processes after wineserver -k -w')


def _log_output_async(proc, label):
    """Drain a fire-and-forget subprocess's stdout/stderr in the background
    and log it once it exits, so callers that can't block on the Popen (e.g.
    launch_protocol_url, invoked from a request thread) still get visibility
    into failures instead of the output silently vanishing."""
    import threading

    def _drain():
        try:
            out, err = proc.communicate()
        except Exception:
            return
        if out and out.strip():
            log.info(f'{label}: stdout: {out.decode("utf-8", errors="replace")[:2000]}')
        if err and err.strip():
            log.warning(f'{label}: stderr: {err.decode("utf-8", errors="replace")[:2000]}')

    threading.Thread(target=_drain, daemon=True).start()
