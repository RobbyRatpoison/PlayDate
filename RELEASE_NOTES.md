# Release Notes

## Installation

### Windows
1. Download **PlayDate-Setup.exe** below
2. Run it and follow the installer wizard
3. PlayDate will appear in your Start Menu

**Requirements:** Windows 10 or 11 (64-bit). Microsoft Edge WebView2 Runtime is required — it comes pre-installed on Windows 10/11.

### Linux
```bash
chmod +x install.sh && ./install.sh
```

**Requirements:** Python 3.10+ and the WebKit/GTK bindings for your distro:
```bash
# Debian / Ubuntu
sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.0

# Fedora
sudo dnf install python3-gobject webkit2gtk4.0
```

### macOS
```bash
chmod +x install.sh && ./install.sh
```

**Requirements:** Python 3.10+. pywebview should work out of the box on recent macOS versions. macOS support is present but not yet fully tested.

---

## v1.1.1 — 2026-03-22

### Bug Fixes
- **Fixed startup crash on Windows** — selenium was imported unconditionally at module load, causing a `ModuleNotFoundError` on startup for users who don't have selenium installed. Imports are now deferred inside `scrape_blaeo_games()` so they only load when BLAEO sync is triggered.
- **Improved BLAEO sync error message** — if Chrome is not installed, users now see a clear explanation and a link to download it, instead of a raw `WebDriverException`.

---
