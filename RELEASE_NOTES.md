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

## v1.1.3 — 2026-03-23

### New Metadata Fields
- **Genres, Categories, and Free to Play** are now scraped from Steam and stored for every game. Existing games can be updated via Sync Steam Data in the edit modal, or by re-scraping from the bulk edit toolbar.
- All three fields are available as filter conditions in the Library filter builder and custom SQL, and can be edited via the edit modal and bulk edit.

### Edit Modal
- **Pill inputs** replace plain text fields for Tags, Genres, Categories, and Groups — values display as removable chips, new values are added by typing and pressing Enter or comma, and autocomplete suggestions are drawn from your existing library data across all pages.
- **Layout redesign** — fields are reorganised into clearer groups: identity info (title, developer, publisher, release date, free to play) and user tracking (status, installed, dates, playtime, achievements, reviews) in the two columns, with Tags, Genres, Categories, and Groups below.

### Bulk Re-scrape
- **Stop button** — long bulk re-scrape operations can now be cancelled mid-run. The stop button appears during scraping and halts after the current game finishes. The modal also blocks accidental closure while a scrape is in progress.

---
