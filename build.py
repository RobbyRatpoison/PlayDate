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
    import zipfile

    version = read_version()
    print(f"PlayDate version: {version}")

    run(["pyinstaller", "playdate.spec", "--noconfirm"])

    iscc = find_iscc()
    run([iscc, f"/DAppVersion={version}", "playdate.iss"])

    # Add portable marker AFTER Inno Setup so the installer build doesn't include it
    dist_dir = os.path.join(ROOT, "dist", "PlayDate")
    portable_marker = os.path.join(dist_dir, "portable.txt")
    with open(portable_marker, "w") as f:
        f.write(f"PlayDate v{version} portable build\n")

    # Zip the dist/PlayDate directory as the portable release asset
    portable_zip = os.path.join(ROOT, "dist", "PlayDate-Windows-Portable.zip")
    print(f"\n>>> Creating portable zip: {portable_zip}\n")
    with zipfile.ZipFile(portable_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _, filenames in os.walk(dist_dir):
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                arcname = os.path.relpath(full, dist_dir)
                zf.write(full, arcname)

    size_mb = os.path.getsize(portable_zip) / 1_048_576
    print(f"Portable zip: {portable_zip} ({size_mb:.1f} MB)")

    print(f"\nBuild complete: PlayDate v{version}")
    print(f"Installer:     {os.path.join(ROOT, 'installer', 'PlayDate-Setup.exe')}")
    print(f"Portable zip:  {portable_zip}")


if __name__ == "__main__":
    main()
