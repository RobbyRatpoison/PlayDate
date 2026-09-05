"""
runners/native_exe.py -- shared "which file do I launch" scanner for plugins
whose games ship with no authoritative manifest (Humble, itch.io, IndieGala;
also GOG's fallback path when no goggame-<id>.info matches).

This consolidates what were four independently-drifted copies of the same
scan/rank/pick logic. Two of those copies (itch.io, IndieGala) were found
carrying a real bug this one copy (originally Humble's) had already fixed:
a naive alphabetical sort picks a 32-bit `Foo.x86` over a 64-bit
`Foo.x86_64` for the same game, and the 32-bit binary can't even execute
under the Flatpak build's 64-bit-only runtime.

All paths returned here are relative to install_path, matching
`games.platform_executable`'s documented contract (database.py) -- callers
join with their own install_path when they need an absolute path.
"""

import os
import sys

_SKIP_EXE_PREFIXES = ('setup', 'install', 'unins', 'uninst', 'redist')
_HELPER_EXE_NAMES = {
    'unitycrashhandler64', 'unitycrashhandler32', 'unitycrashhandler',
    'unityplayer',
    'dxsetup', 'dxwebsetup',
    'vcredist_x64', 'vcredist_x86', 'vc_redist.x64', 'vc_redist.x86',
    'dotnetfx', 'dotnet',
}


def _is_elf(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'\x7fELF'
    except OSError:
        return False


def _is_macho(path):
    try:
        with open(path, 'rb') as f:
            magic = f.read(4)
            return magic in (b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf',
                             b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe',
                             b'\xca\xfe\xba\xbe')
    except OSError:
        return False


def _elf_bits(path):
    """Return 32 or 64 for an ELF binary, else None (non-ELF / unreadable)."""
    try:
        with open(path, 'rb') as f:
            head = f.read(5)
        if head[:4] != b'\x7fELF':
            return None
        return {1: 32, 2: 64}.get(head[4])
    except OSError:
        return None


def _native_rank(fpath):
    """Sort priority for a native Linux candidate (lower = preferred).

    Unity ships `Foo.x86` (32-bit) right next to `Foo.x86_64`; a naive
    alphabetical sort picks `Foo.x86`, and a 32-bit binary can't be exec'd at
    all under the 64-bit-only Flatpak runtime (its interpreter
    /lib/ld-linux.so.2 isn't there) -- it fails with a misleading ENOENT on a
    file that plainly exists. Prefer 64-bit; fall back to the .x86/.x86_64
    extension convention when the file isn't a readable ELF. fpath must be a
    directly openable (e.g. absolute) path.
    """
    bits = _elf_bits(fpath)
    if bits == 64:
        return 0
    if bits == 32:
        return 2
    ext = os.path.splitext(fpath)[1].lower()
    if ext in ('.x86_64', '.amd64', '.arm64'):
        return 0
    if ext == '.x86':
        return 2
    return 1


def scan_candidates(install_path):
    """
    Walk install_path and group every plausible launch candidate.

    Returns {'appimages': [rel, ...], 'natives': [(rank, depth, rel), ...],
             'scripts': [rel, ...], 'winexes': [rel, ...]}
    -- all paths relative to install_path. 'natives' entries carry a rank
    from _native_rank() (0 = best, i.e. confirmed or likely 64-bit).
    """
    is_windows = sys.platform == 'win32'
    is_mac     = sys.platform == 'darwin'

    appimages, natives, scripts, winexes = [], [], [], []

    for dirpath, dirs, filenames in os.walk(install_path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in filenames:
            if fname.startswith('.'):
                continue
            fpath = os.path.join(dirpath, fname)
            rel   = os.path.relpath(fpath, install_path)
            ext   = os.path.splitext(fname)[1].lower()
            stem  = os.path.splitext(fname.lower())[0]
            depth = rel.count(os.sep)

            if ext == '.appimage':
                appimages.append(rel)
            elif ext in ('.x86_64', '.x86', '.amd64', '.arm64', '.linux'):
                natives.append((_native_rank(fpath), depth, rel))
            elif ext == '.sh' and not is_windows:
                scripts.append(rel)
            elif not ext and not is_windows and (_is_elf(fpath) or (is_mac and _is_macho(fpath))):
                natives.append((_native_rank(fpath), depth, rel))
            elif ext == '.exe':
                if any(stem.startswith(p) for p in _SKIP_EXE_PREFIXES):
                    continue
                if stem in _HELPER_EXE_NAMES:
                    continue
                winexes.append((depth, rel))

    return {'appimages': appimages, 'natives': natives,
            'scripts': scripts, 'winexes': winexes}


def find_mac_app_bundle(install_path):
    """macOS only: top-level .app bundle's inner executable, or the bundle
    itself if none is found inside Contents/MacOS. Relative to install_path,
    or None. Checked before scan_candidates() -- a .app bundle always wins."""
    if sys.platform != 'darwin':
        return None
    for entry in os.listdir(install_path):
        if not entry.endswith('.app'):
            continue
        app_path = os.path.join(install_path, entry)
        if not os.path.isdir(app_path):
            continue
        macos_dir = os.path.join(app_path, 'Contents', 'MacOS')
        if os.path.isdir(macos_dir):
            for candidate in os.listdir(macos_dir):
                inner = os.path.join(macos_dir, candidate)
                if os.path.isfile(inner) and os.access(inner, os.X_OK):
                    return os.path.relpath(inner, install_path)
        return entry
    return None


def pick_executable(install_path):
    """
    Full pick: mac .app bundle first, then scan_candidates() with priority
    appimages > natives > scripts > winexes.

    Returns {'path': rel|None, 'is_windows': bool, 'ambiguous': bool,
             'candidates': [rel, ...]}.

    'ambiguous' is True when the winning group has more than one candidate
    tied for the best rank/depth -- i.e. the heuristic has a favorite but
    can't actually tell them apart (two same-depth 64-bit native ELFs, two
    same-depth AppImages, etc). 'path' is still the best guess even when
    ambiguous, so callers that ignore the flag keep working exactly as
    before; 'candidates' lists every option in the winning group for a
    picker UI to offer, not just the runners-up.
    """
    mac_app = find_mac_app_bundle(install_path)
    if mac_app:
        return {'path': mac_app, 'is_windows': False, 'ambiguous': False,
                'candidates': [mac_app]}

    c = scan_candidates(install_path)

    if c['appimages']:
        group = sorted(c['appimages'])
        best_depth = group[0].count(os.sep)
        tied = [p for p in group if p.count(os.sep) == best_depth]
        return {'path': group[0], 'is_windows': False,
                'ambiguous': len(tied) > 1, 'candidates': tied}

    if c['natives']:
        group = sorted(c['natives'])  # (rank, depth, rel)
        best_rank, best_depth = group[0][0], group[0][1]
        tied = [rel for rank, depth, rel in group if rank == best_rank and depth == best_depth]
        return {'path': group[0][2], 'is_windows': False,
                'ambiguous': len(tied) > 1, 'candidates': tied}

    if c['scripts']:
        group = sorted(c['scripts'])
        best_depth = group[0].count(os.sep)
        tied = [p for p in group if p.count(os.sep) == best_depth]
        return {'path': group[0], 'is_windows': False,
                'ambiguous': len(tied) > 1, 'candidates': tied}

    if c['winexes']:
        group = sorted(c['winexes'])  # (depth, rel)
        best_depth = group[0][0]
        tied = [rel for depth, rel in group if depth == best_depth]
        return {'path': group[0][1], 'is_windows': True,
                'ambiguous': len(tied) > 1, 'candidates': tied}

    return {'path': None, 'is_windows': False, 'ambiguous': False, 'candidates': []}
