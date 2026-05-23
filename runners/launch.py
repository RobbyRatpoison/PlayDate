"""
Shared launch helpers for plugins and emulators.
"""

import subprocess
import time


def check_launch(proc: subprocess.Popen) -> dict | None:
    """
    Check whether a just-started process died within 1 second with a non-zero
    exit code.  Returns an error dict if so, None if the process is still
    running (or exited cleanly with code 0).
    """
    time.sleep(1.0)
    ret = proc.poll()
    if ret is not None and ret != 0:
        stderr_out = ''
        if proc.stderr:
            stderr_out = proc.stderr.read().decode('utf-8', errors='replace').strip()
        msg = f'Game exited immediately (code {ret})'
        if stderr_out:
            msg += f': {stderr_out[:300]}'
        return {'status': 'error', 'message': msg}
    return None


def popen_checked(cmd: list, **kwargs) -> tuple[subprocess.Popen, dict | None]:
    """
    subprocess.Popen wrapper that runs check_launch automatically.
    stderr is captured unless the caller overrides it.
    Returns (proc, error_dict_or_None).
    """
    kwargs.setdefault('stderr', subprocess.PIPE)
    proc = subprocess.Popen(cmd, **kwargs)
    return proc, check_launch(proc)
