"""
Build script for PlayDate Windows release.

Reads __version__ from config.py and passes it to both PyInstaller and
Inno Setup, so the exe and installer always carry the same version string.

Usage:
    python build.py

Requires:
    - PyInstaller on PATH  (pip install pyinstaller)
    - Inno Setup 6 installed at its default location
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

ISCC_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def read_version():
    config = os.path.join(ROOT, "config.py")
    with open(config, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not m:
        print("ERROR: __version__ not found in config.py")
        sys.exit(1)
    return m.group(1)


def find_iscc():
    for path in ISCC_PATHS:
        if os.path.isfile(path):
            return path
    return "ISCC.exe"


def run(cmd, **kwargs):
    print(f"\n>>> {' '.join(str(c) for c in cmd)}\n")
    result = subprocess.run(cmd, cwd=ROOT, **kwargs)
    if result.returncode != 0:
        print(f"\nERROR: command exited with code {result.returncode}")
        sys.exit(result.returncode)


def main():
    version = read_version()
    print(f"PlayDate version: {version}")

    run(["pyinstaller", "playdate.spec", "--noconfirm"])

    iscc = find_iscc()
    run([iscc, f"/DAppVersion={version}", "playdate.iss"])

    print(f"\nBuild complete: PlayDate v{version}")
    print(f"Installer: {os.path.join(ROOT, 'installer', 'PlayDate-Setup.exe')}")


if __name__ == "__main__":
    main()
