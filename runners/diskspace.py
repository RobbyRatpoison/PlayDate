"""
runners/diskspace.py — Pre-flight free-space check for plugin downloads.

Confirmed live: with no check at all, a 118GB game install ran the host
disk down to ~99% full mid-download, crashing the user's browser -- a
completely full disk misbehaves system-wide, not just inside PlayDate, so
this needs to be caught *before* a download starts, not partway through.
"""

import shutil


def check_disk_space(path, needed_bytes, margin_ratio=0.05, min_margin_bytes=2 * 1024**3):
    """
    Raise RuntimeError if the filesystem containing `path` doesn't have
    room for needed_bytes plus headroom. `path` must be an existing
    directory (shutil.disk_usage requires it). margin covers the
    installer's own scratch work (temp extraction, redistributable
    installers, etc.) on top of the download's own size.
    """
    usage  = shutil.disk_usage(path)
    margin = max(min_margin_bytes, int(needed_bytes * margin_ratio))
    if usage.free < needed_bytes + margin:
        raise RuntimeError(
            f'Not enough disk space: need {(needed_bytes + margin) / 1e9:.1f} GB, '
            f'only {usage.free / 1e9:.1f} GB free')
