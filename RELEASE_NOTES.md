# Release Notes

## v1.5.3 — 2026-05-05

### Epic Games

- Library sync now fetches metadata and artwork for each game as it's added. Sync can be stopped mid-way and picks up where it left off on the next run.
- Re-syncing your library now skips games already in PlayDate, making repeat syncs significantly faster.
- Library sync now includes DLC, soundtracks, and tools alongside base games.
- Added an "Import Purchase Dates" button that fetches acquisition dates from Epic and updates your library.

### GOG

- Library sync now fetches metadata and artwork for each game as it's added. Sync can be stopped mid-way and picks up where it left off.

### HLTB

- How Long to Beat lookups for Steam games now use a community-maintained ID map for faster and more accurate results.

### Library

- Library and home page load faster; the page chrome now appears immediately while the grid loads in the background.
- Added a PAGYWOSG Builder shortcut to the filters modal header.
- Pick 6 now shows the active filter name; applying a filter from the Pick 6 modal correctly saves and displays the filter name.

### General

- PlayDate now shows a "What's New" summary after updating to a new version.

### Fixes

- Fixed a startup issue that silently discarded Steam last-played date updates on every launch.
- Fixed the edit modal not reopening after saving a game.
- Fixed card outlines appearing after saving when they were disabled in settings.
- Fixed a duplicate entry appearing in the saved filters dropdown when replacing a PAGYWOSG filter.

### Installation

- Fixed the installer and uninstaller windows clipping buttons and content on some screen sizes.
- The desktop shortcut checkbox in the installer now only takes effect when you confirm installation.

## v1.5.2 — 2026-04-30

### Appearance

- Added a UI Scale slider under Menu → Appearance. Drag to scale the entire interface up or down (75–150%). Useful for 4K and HiDPI displays where text appears too small.

### Library

- Added a toggle under Menu → Library → Completion Sync to control whether games are automatically promoted from Never Played to Unfinished when Steam shows playtime. Disable this if you use BLAEO to manage Never Played status.
- Quick filters are now grouped into two rows: general filters (All Games, Installed, Not Installed, Never Played / Unfinished, Beaten / Completed) and individual status filters (Never Played, Unfinished, Beaten, Completed, Won't Play).

### Installation

- The Linux prerequisites in the README now include `python3-venv`, `python3-pip`, and `python3-tk` for Debian/Ubuntu.
- The Linux installer now shows the actual error output when virtual environment creation fails, with a targeted hint for Debian/Ubuntu users.

### Fixes

- Fixed a startup crash (`no such column: protondb_fetched`) affecting users upgrading from older database versions.
- Fixed the Won't Play quick filter not working.
- Fixed BLAEO sync silently ignoring Won't Play status — games marked Won't Play on BLAEO will now sync correctly (unless the game is already Beaten or Completed in PlayDate).
