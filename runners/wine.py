"""
runners/wine.py — Shared Wine helpers for plugins that need to run Windows executables.
"""

import glob
import logging
import os
import subprocess

log = logging.getLogger(__name__)

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
    """
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
            if os.path.isfile(full) and os.access(full, os.X_OK):
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


def build_proton_env(wine_bin, base_env=None):
    """
    Return an env dict with LD_LIBRARY_PATH and WINEDLLPATH set up for a Proton
    wine binary, mirroring what the Proton script does when launching via Steam.

    wine_bin must be the path to wine64/wine inside a Proton 'files/bin/' directory.
    base_env defaults to os.environ if not provided.
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

    # WINEDLLPATH: vkd3d arch-specific dirs + wine overrides.
    # The x86_64-windows subdirectories are needed so Wine finds native DLLs
    # (libvkd3d-1.dll etc.) when WINEDLLPATH entries are searched.
    dll_extra = [
        os.path.join(lib_dir, 'vkd3d', 'x86_64-windows'),
        os.path.join(lib_dir, 'vkd3d'),
        os.path.join(lib_dir, 'wine', 'x86_64-windows'),
        os.path.join(lib_dir, 'wine'),
    ]
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
        subprocess.run(
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
    env = dict(os.environ)
    env['WINEPREFIX'] = prefix_path
    env['WINEDEBUG'] = '-all'

    log.info(f'Creating Wine prefix at {prefix_path} using {wine_bin}')
    subprocess.run(
        [wine_bin, 'wineboot', '--init'],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_in_prefix(prefix_path, exe, args=None, wine_bin=None, env_extra=None):
    """
    Launch a Windows executable inside a Wine prefix.

    prefix_path : path to the Wine prefix directory
    exe         : absolute path to the .exe to run
    args        : list of extra arguments to pass to the executable
    wine_bin    : path to the wine binary; auto-detected if None
    env_extra   : dict of additional environment variables

    Returns a subprocess.Popen object (caller should not wait -- game runs in background).
    Raises RuntimeError if no Wine binary is available.
    """
    if wine_bin is None:
        wine_bin = find_wine_binary()
        if not wine_bin:
            raise RuntimeError('No Wine binary found. Install Wine to use this plugin.')

    env = build_proton_env(wine_bin) if is_proton_wine(wine_bin) else dict(os.environ)
    env['WINEPREFIX'] = prefix_path
    if env_extra:
        env.update(env_extra)

    cmd = [wine_bin, exe] + (args or [])
    log.info(f'Wine launch: {wine_bin} {exe}  (prefix={prefix_path})')
    return subprocess.Popen(cmd, env=env)


def launch_protocol_url(prefix_path, url, wine_bin=None, env_extra=None):
    """
    Open a Windows protocol URL (e.g. com.epicgames.launcher://...) inside a Wine
    prefix using `wine start <url>`. Returns a subprocess.Popen object.
    Raises RuntimeError if no Wine binary is found.
    """
    if wine_bin is None:
        wine_bin = find_wine_binary()
        if not wine_bin:
            raise RuntimeError('No Wine binary found. Install Wine to use this plugin.')

    env = build_proton_env(wine_bin) if is_proton_wine(wine_bin) else dict(os.environ)
    env['WINEPREFIX'] = prefix_path
    if env_extra:
        env.update(env_extra)

    cmd = [wine_bin, 'start', url]
    log.info(f'Wine protocol launch: {url}  (prefix={prefix_path})')
    return subprocess.Popen(cmd, env=env)
