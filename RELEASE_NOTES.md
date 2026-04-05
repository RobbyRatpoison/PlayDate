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

## v1.2.4 — 2026-04-04

### New
- **Populate overhaul** — art, metadata, and achievement scraping now run as concurrent worker pools. Game cards appear immediately as placeholders and fill in live as each phase completes. Cards visible in the viewport are prioritized.
- **BLAEO pre-scrape** — when populating, PlayDate now runs a BLAEO sync concurrently with the art/metadata workers. Achievement workers start after it finishes and skip any games BLAEO already covered.

### Changes
- Art worker now skips re-downloading images that already exist on disk

