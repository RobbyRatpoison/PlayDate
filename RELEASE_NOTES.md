# Release Notes

## v1.5.8 — Pending

### New Plugins

- **EA App** *(experimental)* — sync your EA library; launch support is implemented but EA App itself does not currently run under Wine on Linux, so install and launch are non-functional there. Windows support is implemented but untested.
- **IndieGala** — sync your IndieGala library, auto-detects installed games from local folders, launch and uninstall support.

### Improvements

- Platform source toggles moved from the View modal to the Filters modal, with a new All/None toggle button.
- Secret Santa / Snowballs gift list: added a group picker to bulk-add all Steam games from a library group at once.
- PAGYWOSG filter builder now auto-detects two new category types: "Games starting with [letter]" (name starts-with filter) and "Games released on a [weekday]" (release date weekday filter).

### Bug Fixes

- Fixed restore-from-path (native file picker) not restoring `theme.json` or `emulators.json`.
- Fixed Pick 6 ignoring platform source toggles when building the candidate pool.
- Fixed Pick 6 including games with no review data when a minimum review score bound was set; same fix applied to release year and HLTB bounds.
- Fixed PAGYWOSG filter builder completion status toggles being read from both the PAGYWOSG and MIAM tools simultaneously, causing statuses to appear twice in the saved filter tree and breaking the filter entirely when enough statuses were selected.
