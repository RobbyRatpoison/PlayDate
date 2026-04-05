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

## v1.2.6 — 2026-04-05

### New
- **Date import overhaul** — the bulk date import no longer switches tabs for every game. It now stays on a single Steam Help page and fetches each game's date in the background, showing a live per-game log as results come in. The userscript no longer requires Tampermonkey Manifest V2.
- **Auto-complete fix** — games with 100% achievements are now correctly marked Completed on startup, even if the achievement data was imported via BLAEO rather than the Steam API

### Changes
- **Library grid** — edge cards are no longer clipped by the grid's paint boundary
- **Filter modal** — the field selector and value input are now equal width

