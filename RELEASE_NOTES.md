# Release Notes

## v1.5.3 — 2026-05-05

### Epic Games

- Game descriptions now appear in list mode detail pane.
- Library sync now fetches metadata and artwork for each game as it's added. Sync can be stopped mid-way and picks up where it left off on the next run.
- Repeat syncs are significantly faster.
- Library sync now includes DLC, soundtracks, and tools alongside base games.
- Added an "Import Purchase Dates" button that fetches acquisition dates from Epic and updates your library.

### GOG

- Library sync now fetches metadata and artwork for each game as it's added. Sync can be stopped mid-way and picks up where it left off.
- Achievement data is now tracked for existing library games.

### HLTB

- How Long to Beat lookups are now faster and more accurate.

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
- Fixed GOG games being incorrectly marked as Completed at startup based on achievement data.
- Fixed bulk ops "Filtered Games" scope ignoring hidden platforms and failing entirely in list mode.
- Fixed bulk delete and date import also failing in list mode for the same reason.
- Fixed date fields showing a raw timestamp instead of a formatted date after saving in list mode.

### Installation

- Fixed the installer and uninstaller windows clipping buttons and content on some screen sizes.
- The desktop shortcut checkbox in the installer now only takes effect when you confirm installation.
