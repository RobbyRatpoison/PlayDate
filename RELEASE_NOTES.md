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

## v1.2.8 — 2026-04-08

### New
- **ProtonDB integration** — Linux compatibility ratings are now fetched from ProtonDB. Tier (platinum/gold/silver/bronze/borked) and confidence (strong/good/weak) are stored per game. The edit modal shows a coloured tier badge with a link to the ProtonDB page and a Refresh button; hidden on Windows. ProtonDB data can be fetched for your full library via the Re-scrape tab in Bulk Operations, or for individual games via the Refresh button. Both `protondb_tier` and `protondb_confidence` are available as filter conditions.
- **Bulk Operations modal** — the four separate bulk modals (bulk edit, re-scrape, art scrape, date import) have been replaced by a single tabbed Bulk Operations modal with Edit, Re-scrape, and Date Importer tabs. The Re-scrape tab has separate sub-sections for Steam data and artwork. Closing the modal while a scrape is running no longer blocks it; operations continue in the background.
- **Install status live update** — the home page polls for install status changes every 5 seconds and updates shelf visibility without a full page reload.
- **HLTB search link** — a "Search HLTB ↗" link appears in the edit modal next to the AppID, pre-filled with the game name.
- **Achievements link** — a "↗" link appears inline with the Achievements label in the edit modal, opening your Steam achievement page for that game. Hidden if no Steam ID is configured.
- **Sync Store auto-complete** — syncing store data in the edit modal automatically sets completion status to Completed when achievement counts show 100%.
- **PAGYWOSG quals self-verifier** — a SteamGifts username field has been added to account settings. When a game in the qualifications panel was submitted for mod verification by you, it shows "mod verified — already submitted" instead of directing you to someone else's entry.

### Fixes
- **Startup install status sync** — games uninstalled while PlayDate was closed are now corrected automatically on launch.

### Changes
- **Filter conditions** — artwork source filters moved to the bottom of the condition list. ProtonDB tier and confidence added.
- **Artwork cache busting** — library grid cards and home page shelf capsules update immediately after any artwork save without requiring a page reload.
- **Art source backfill** — games with art marked as fetched but missing source columns are now backfilled on startup.
- **Initial config modal** — renamed to "Configuration"; API key label updated from "Optional" to "Recommended" with an explanation of what each mode provides.
- **Account settings** — Steam API key "(recommended)" label now shows a tooltip describing what the key enables.
- **PAGYWOSG filter performance** — large appid pools use a dedicated node type instead of raw SQL, significantly improving filter build and apply speed for events with thousands of verified games.
- **PAGYWOSG filter builder** — duplicate filter name check on save prompts Replace or Rename. Self-verifier label shown in qualifications panel.

