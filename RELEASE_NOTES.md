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

## v1.1.9 — 2026-03-28

### Steam API Key Now Optional
PlayDate no longer requires a Steam Web API key to import your library. Without one, your library is read directly from local Steam files — played games and playtime from `localconfig.vdf`, names from installed game manifests and Steam's local metadata cache. Store metadata, reviews, and tags are still fetched from the web as before. Achievements require an API key.

### Other Improvements
- Startup playtime sync now reads from local Steam files instead of requiring an API key
- Rate limiting detection: if Steam returns a rate limit response during import, PlayDate pauses and retries automatically. If the rate limit persists, the import stops and alerts you rather than silently skipping games
- Home page "Recently Added" and "Recently Released" shelves now show unbeaten games instead of only never-played games, so they populate correctly for users with small libraries
- Edit modal now shows a "Browse SGDB ↗" link when no SteamGridDB key is configured, making it easy to find and paste a custom image URL
- Images pasted from SteamGridDB in the edit modal are now saved with the correct source label
- Fixed single-game rescrape overwriting the game name, playtime, and last played date with empty values when no API key is present
- Layout editor "Exit Editor" button renamed to "Cancel" and now correctly discards unsaved changes

---
