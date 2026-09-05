"""
runners/windows.py -- Native Windows launcher-detection helpers.

Plugins that need a separate launcher app (EA App, Epic Games, Ubisoft
Connect, Battle.net, Rockstar Games Launcher) each had their own
`_find_native_launcher()` that only guessed standard Program Files paths --
never checked the registry, so a launcher installed to a custom directory
was invisible. `find_installed_exe()` here looks the app up the way
Windows' own "Add or Remove Programs" does: its Uninstall registry entry.
Windows-only; every function here returns None immediately on any other
platform, so it's safe to import and call unconditionally from a plugin's
cross-platform code.
"""

import os
import sys

_UNINSTALL_ROOTS = [
    r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
    r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
]


def find_install_location(display_name):
    """
    Look up an installed Windows app's InstallLocation via its Uninstall
    registry entry, matching by exact DisplayName (what Add/Remove Programs
    shows). Returns the install directory, or None if not found.

    Tries two things per Uninstall root, in both HKLM and HKCU:
      1. A subkey literally named `display_name` -- how simple NSIS-style
         installers (e.g. Rockstar Games Launcher) register themselves;
         confirmed against Galaxy-Plugin-Rockstar's own registry lookup.
      2. Enumerating every subkey and matching its DisplayName value --
         needed for MSI-based installers, which register under a random
         GUID subkey instead (EA app, Ubisoft Connect, Battle.net, Epic
         Games Launcher all install this way).

    Falls back to deriving a directory from DisplayIcon (stripping a
    trailing ",N" icon-index suffix) when InstallLocation is missing or
    blank -- some installers only ever set the former.
    """
    if sys.platform != 'win32':
        return None
    import winreg

    hives = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    for hive in hives:
        for root in _UNINSTALL_ROOTS:
            # Fast path: subkey literally named after the app.
            try:
                with winreg.OpenKey(hive, f'{root}\\{display_name}') as subkey:
                    found = _read_install_dir(winreg, subkey)
                    if found:
                        return found
            except OSError:
                pass

            # Slow path: enumerate subkeys, match DisplayName.
            try:
                key = winreg.OpenKey(hive, root)
            except OSError:
                continue
            try:
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            name, _ = winreg.QueryValueEx(subkey, 'DisplayName')
                            if name != display_name:
                                continue
                            found = _read_install_dir(winreg, subkey)
                            if found:
                                return found
                    except OSError:
                        continue
            finally:
                winreg.CloseKey(key)
    return None


def _read_install_dir(winreg, subkey):
    try:
        loc, _ = winreg.QueryValueEx(subkey, 'InstallLocation')
        loc = (loc or '').strip().strip('"')
        if loc:
            return loc.rstrip('\\')
    except OSError:
        pass
    try:
        icon, _ = winreg.QueryValueEx(subkey, 'DisplayIcon')
        icon = (icon or '').strip().strip('"')
        if icon:
            icon = icon.rsplit(',', 1)[0]  # strip a trailing ",N" icon index
            return os.path.dirname(icon)
    except OSError:
        pass
    return None


def find_installed_exe(display_name, exe_relpaths):
    """
    find_install_location(display_name) + a specific exe relative to it.
    exe_relpaths: a single relative path, or a list to try in order (for an
    app whose exe location varies, e.g. Win64 vs Win32 build directories).
    Returns the full exe path if it exists on disk, else None.
    """
    if sys.platform != 'win32':
        return None
    install_dir = find_install_location(display_name)
    if not install_dir:
        return None
    if isinstance(exe_relpaths, str):
        exe_relpaths = [exe_relpaths]
    for rel in exe_relpaths:
        candidate = os.path.join(install_dir, rel)
        if os.path.isfile(candidate):
            return candidate
    return None
