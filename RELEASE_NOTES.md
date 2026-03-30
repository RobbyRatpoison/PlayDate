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

## v1.1.14 — 2026-03-30

### New Features
- **Steam date importer userscript** (`playdate_date_import.user.js`) — a Tampermonkey script that automatically scrapes the earliest activation date from a Steam help page and sends it to PlayDate. Requires Tampermonkey in MV2 mode.
- **Single-game mode:** clicking the ↗ link next to Date Added in the edit modal opens the Steam help page; the script sends the date back and the field populates automatically. The tab closes once PlayDate has received it.
- **Bulk date import:** new "Import Dates from Steam" button in the bulk edit modal. Opens a single browser tab that automatically navigates through each selected or filtered game, scrapes its date, saves it to the database, and closes when done. Progress is shown in real time.

---
