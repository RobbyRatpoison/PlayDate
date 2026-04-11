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

## v1.3.0 — 2026-04-10

### New
- **HowLongToBeat integration** — Main Story, +Extras, and Completionist times are now scraped and stored per game (in minutes). During populate, games are matched by name against HLTB; matches above the auto-confirm threshold are confirmed automatically, matches below are flagged as unconfirmed. A new HLTB Review tab in Bulk Operations shows unconfirmed matches sorted by score, with a threshold slider, "Confirm all above" button, and "Scrape unfetched / unmatched" to process the rest. The edit modal shows times with Confirm / Other match / Clear / Re-scrape actions and an alt-results panel for manual ID selection. All three time columns are available as filter conditions; a `hltb_min` sort column sorts by the shortest available time, with unscraped games last.

### Fixes
- **Gamepad suppression during gameplay** — gamepad input is now correctly suppressed when a game is launched, preventing unintended inputs in-game and on return to PlayDate. On Linux, a background poller detects when the game process exits and automatically re-enables input; alt-tabbing back also re-enables it. Falls back to click/keypress detection on other platforms.
- **Startup install status flash** — `sync_local_install_status()` committed the reset-to-zero step as a separate transaction before re-setting installed games, creating a window where the home page could see everything as uninstalled. Both steps now run in a single transaction.
- **State file concurrent write corruption** — concurrent Waitress threads could corrupt `state.json` on simultaneous writes. All reads/writes are now guarded with a threading lock and use atomic temp-file replacement.

### Changes
- **Bulk Operations** — button renamed from "BULK EDIT" to "BULK OPS"; tab strip spreads evenly across the header; modal widened to 720px.
- **SQL indexes** — indexes added on `installed`, `completion_status`, `last_played`, and `playtime_forever` for faster filter and sort queries on large libraries. Created automatically on startup.
- **Static asset cache busting** — `style.css`, `playdate.js`, and `input.js` now include the app version as a cache-busting query parameter, ensuring fresh assets are loaded after an upgrade.


