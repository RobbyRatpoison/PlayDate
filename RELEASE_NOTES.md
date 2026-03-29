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

## v1.1.13 — 2026-03-29

### Bug Fixes
- Re-scrape Steam Data in bulk edit modal now works (was silently failing every time due to a bad column reference and broken API key lookup)
- Populate PlayDate progress counter no longer includes DLC, mods, advertising, and other non-game entries in the total
- Non-game entries are now auto-blacklisted on first populate so they're permanently excluded from future runs
- Fixed inability to type spaces in the custom SQL filter input
- Review scores now correctly show for "Profile Features Limited" games
- "No Reviews" now correctly distinguished from "Not Enough Reviews"
- Update check no longer fires twice on startup
- Newly added games now default to 0/0 achievements instead of NULL

### Improvements
- Logging overhauled: third-party library noise suppressed; all PlayDate scraper output now goes to `playdate.log`; long lines truncated; log rotation keeps one backup
- Store type is logged when a game is added, to help identify Proton/tool app types for future filtering
- Art downloads are skipped for non-game entries (was fetching art before checking type)
- Review API now uses `language=all` and `purchase_type=all` for accurate counts

### UI
- "Cancel" → "Close" on bulk edit, bulk re-scrape, bulk artwork, and bulk delete modals
- Delete game dialog now shows "Delete" and "Blacklist and Delete" instead of "Cancel" and "OK"
- Date Added label in edit modal has a "↗" link to the Steam support page for that game
- Filter modal now includes Total Reviews and Positive Reviews as filterable fields

---
