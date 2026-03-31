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

## v1.1.15 — 2026-03-31

### New Features
- **Startup playtime sync now updates achievements and completion status** — when playtime has changed since the last launch, PlayDate fetches fresh achievement data (requires API key) and automatically promotes games from `Never Played` → `Unfinished` or any status → `Completed` on 100% unlock. `Beaten` is never downgraded.
- **BLAEO sync now imports achievement data** — syncing with BLAEO now also saves unlocked and total achievement counts from the BLAEO games page, no API key required.

### Bug Fixes
- Fixed single-game refresh (edit modal) not fetching achievements for users with multiple Steam accounts configured — it was reading the API key from the wrong place.

### Improvements
- Saving a filter in the PAGYWOSG Filter Builder now immediately adds it to the saved filters dropdown without requiring a page reload.

---
