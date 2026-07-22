"""
runners/sandbox.py — Host process execution helpers for running inside Flatpak.

Wine, Proton, winetricks, and 7z need to run in the *host's* mount/pid
namespace, not the Flatpak sandbox's — otherwise they'd see the runtime's
/usr instead of the host's, miss the real GPU driver stack, and any game
they launch would inherit the sandbox too. `flatpak-spawn --host` re-executes
a command on the host; outside Flatpak, these functions are thin passthroughs
to the normal subprocess/shutil/os calls so behavior is unchanged.
"""

import os
import shutil
import subprocess

IN_FLATPAK = os.path.exists('/.flatpak-info')


def _host_spawn_prefix(env=None, cwd=None):
    """Build the flatpak-spawn --host prefix.

    Callers typically build env as {**os.environ, 'WINEPREFIX': ..., ...} —
    forwarding that whole dict via --env would push the *sandbox's* PATH,
    LD_LIBRARY_PATH, etc. onto the host process and break it. The host
    process already gets a normal host environment (DISPLAY, PATH, HOME...)
    on its own, so only forward keys that are new or actually overridden
    relative to this process's own environment.
    """
    prefix = ['flatpak-spawn', '--host']
    if cwd:
        prefix.append(f'--directory={cwd}')
    if env:
        for k, v in env.items():
            if os.environ.get(k) != v:
                prefix.append(f'--env={k}={v}')
    return prefix


def _host_test(flag, path) -> bool:
    try:
        r = subprocess.run(
            ['flatpak-spawn', '--host', 'test', flag, path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except Exception:
        return False


def host_exists(path) -> bool:
    """os.path.exists, but checked against the host filesystem when sandboxed."""
    if not IN_FLATPAK:
        return os.path.exists(path)
    return _host_test('-e', path)


def host_is_executable(path) -> bool:
    """os.path.isfile + os.access(X_OK), checked against the host when sandboxed."""
    if not IN_FLATPAK:
        return os.path.isfile(path) and os.access(path, os.X_OK)
    return _host_test('-x', path)


def host_which(name) -> str | None:
    """shutil.which, but resolved against the host's PATH when sandboxed."""
    if not IN_FLATPAK:
        return shutil.which(name)
    try:
        r = subprocess.run(
            ['flatpak-spawn', '--host', 'sh', '-c', f'command -v {name}'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        out = r.stdout.decode('utf-8', errors='replace').strip()
        return out or None
    except Exception:
        return None


def host_popen(cmd, env=None, cwd=None, **kwargs) -> subprocess.Popen:
    """subprocess.Popen, running on the host when sandboxed.

    env entries are forwarded explicitly via --env=KEY=VALUE since
    flatpak-spawn does not inherit the sandbox's environment by default.
    """
    if not IN_FLATPAK:
        return subprocess.Popen(cmd, env=env, cwd=cwd, **kwargs)
    full_cmd = _host_spawn_prefix(env=env, cwd=cwd) + list(cmd)
    return subprocess.Popen(full_cmd, **kwargs)


def host_run(cmd, env=None, cwd=None, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run, running on the host when sandboxed. See host_popen."""
    if not IN_FLATPAK:
        return subprocess.run(cmd, env=env, cwd=cwd, **kwargs)
    full_cmd = _host_spawn_prefix(env=env, cwd=cwd) + list(cmd)
    return subprocess.run(full_cmd, **kwargs)
