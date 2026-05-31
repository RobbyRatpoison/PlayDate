# Release Notes

## v1.5.9 — 2026-05-30

### Bug Fixes

- Fixed PAGYWOSG filter builder not saving completion status toggles when building and saving a filter — the gamepad row-numbering pass was overwriting the attribute used to identify the completion status buttons, so they were invisible to all read and write operations.

## v1.5.8 — 2026-05-30

### New Plugins

- **EA App** *(experimental)* — sync your EA library; launch support is implemented but EA App itself does not currently run under Wine on Linux, so install and launch are non-functional there. Windows support is implemented but untested.
- **IndieGala** — sync your IndieGala library, auto-detects installed games from local folders, launch and uninstall support.

### Improvements

- Platform source toggles moved from the View modal to the Filters modal, with a new All/None toggle button.
- Secret Santa / Snowballs gift list: added a group picker to bulk-add all Steam games from a library group at once.
- PAGYWOSG filter builder now auto-detects two new category types: "Games starting with [letter]" (name starts-with filter) and "Games released on a [weekday]" (release date weekday filter).
- Bulk date import now fetches purchase dates directly from Humble Bundle, Epic Games, and itch.io via their APIs — no Tampermonkey interaction needed for these platforms.
- Date importer Tampermonkey script now supports EA App: scrapes purchase dates from the EA order history page and sends them to PlayDate.
- Wine prefix can now be removed from the Plugins panel — the launcher config card includes an "Uninstall Launcher" button that deletes the prefix and clears the saved config.
- Epic Games Wine launcher: required graphics libraries are now automatically installed into the Wine prefix after the Epic launcher installer completes.

### Bug Fixes

- Fixed restore-from-path (native file picker) not restoring the theme and emulator configuration.
- Fixed Pick 6 ignoring platform source toggles when building the candidate pool.
- Fixed Pick 6 including games with no review data when a minimum review score bound was set; same fix applied to release year and HLTB bounds.
- Fixed PAGYWOSG filter builder completion status toggles being read from both the PAGYWOSG and MIAM tools simultaneously, causing statuses to appear twice in the saved filter tree and breaking the filter entirely when enough statuses were selected.
- Fixed bulk date import showing a "Tampermonkey script not detected" error when the queue contained only non-Steam games.
