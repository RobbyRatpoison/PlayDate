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

## v1.2.7 — 2026-04-07

### New
- **PAGYWOSG filter builder Auto-fill** — PAGYWOSG Filter Builder can now populate itself from the current event via the PAGYWOSG API, detecting tags, date conditions, appid/title patterns, and mod-verified games. An "Auto-fill from Upcoming Event" button is also available for next-month prep. A collapsible "additional games included" section shows mod-verified library games that wouldn't already qualify through the filter's other criteria.
- **PAGYWOSG qualifications panel** — the edit modal now shows which PAGYWOSG categories a game qualifies for when a PAGYWOSG filter is active, including pool labels (`(win)` for wins-only, `(win)`/`(backlog)` for all-games based on SteamGifts win status). Mod-verified entries show the original submitter so you can cite their entry as proof.
- **PAGYWOSG icaio category support** — categories like "Any game icaio has made a GA for" are automatically populated using icaio's giveaway history and wishlist, bundled with the app.
- **PAGYWOSG filter name** — auto-populated with the event name (e.g. "PAGYWOSG April 2026")

### Changes
- **PAGYWOSG filter modal** — restructured with fixed header/footer with scrollable middle so the Save/Close buttons are always accessible without scrolling.

