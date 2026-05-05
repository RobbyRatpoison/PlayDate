# TODO

## Unreleased

- Fixed tkinter window sizing in both install.py and uninstall.py so buttons and content are no longer clipped. Also moved  
  the desktop shortcut checkbox in the installer to only act on user confirmation.
- Fixed a startup crash in the playtime sync that silently discarded all last-played date updates from Steam on every launch.
- Fixed duplicate entry appearing in the saved filters dropdown when replacing a PAGYWOSG filter.
- Added PAGYWOSG Builder shortcut link to the filters modal header.
- Added a filter shortcut to the Pick 6 page showing the active filter name; applying a filter from the Pick 6 modal now correctly stores and displays the filter name.
- HLTB lookups for Steam games now use a community-maintained Steam→HLTB ID map (cached locally, refreshed weekly) to resolve matches directly by ID instead of guessing by name.
- Fixed the edit modal not reopening after saving on the library page.
- Fixed card outlines appearing after saving a game despite being disabled in settings.
- Epic and GOG library sync now adds each game with its metadata and artwork inline rather than as separate passes; sync can be stopped mid-way and resumed later since already-processed games are skipped on the next run. Fixed the stopped-sync summary showing 0 games added when games had already been processed.
- Epic library sync no longer re-fetches catalog data for games already in the library, making re-syncs significantly faster.
- Epic library sync now includes all owned content (DLC, soundtracks, tools) instead of filtering to base games only.
- Improved library and home page load time by consolidating redundant database connections and adding an index on the name column used for default sorting; library page grid now defers rendering so the page chrome appears immediately; scroll image load delay reduced from 200ms to 100ms.
- Added "Import Purchase Dates" button to the Epic Games plugin that fetches acquisition dates from the Epic entitlements API and updates date_added for all matched games.

## User requests and other things that need sorting

- Scrape Minimum / Recommended Specs
- Sort by actual / estimated Size On Disk

## Known Bugs

- none

---

## Improvements

- **Gamepad support** — home page editor buttons, bulk edit modal navigation, text input focus, disable RB/LB while in modals *(partial: `clearSuppression()` added; remaining: modal navigation, text input focus)*; controller support is completely broken on Steam Deck

---

## Small Features

- **Steam Deck installation** — see `STEAMDECK_PLAN.md`

---

## Big Features

- none

---

## Under Consideration

- none
