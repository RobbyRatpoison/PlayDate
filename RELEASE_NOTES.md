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

## v1.1.5 — 2026-03-24

### New Features
- **Horizontal card view.** The library page now supports a horizontal image layout. Toggle between vertical and horizontal with the new button in the toolbar.
- **Adjustable card size.** A slider in the library toolbar lets you resize game cards to your preference.
- **Icon scraping.** Game icons are now downloaded and stored alongside cover art.
- **Horizontal cover art.** Horizontal images are now fetched and stored separately from vertical capsule art.
- **Hi-res cover art.** PlayDate now prefers 2x resolution images where available, falling back to standard resolution.
- **Improved SteamGridDB browser.** The artwork browser now searches by game name automatically when Steam lookup returns no results. You can also manually search any game name to pull artwork from SteamGridDB's full catalog.

---
