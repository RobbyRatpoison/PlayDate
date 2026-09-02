# Release Notes

## v1.10.0 - 2026-09-02
### New

- The Home layout editor can resize a shelf's height or column width by dragging.
- Columns within a split row can be reordered by dragging; dragging one onto a different row moves that whole row.
- Split rows now support up to 15 columns (up from 3).
- A shelf's Games count now auto-adjusts to fit whenever it's resized.
- Find Library Junk's "No Longer Owned" section can now whitelist a game instead of only deleting it.

### Improvements

- Home page shelves can now scroll to show shelves that don't fit on one screen. (prompted by feedback from quinnix)
- The Home layout editor warns if the current layout won't fit on one screen.
- Home layout editor buttons now match the rest of the app's look.
- Edit and Remove stay reachable in the shelf layout editor even on narrow columns.
- "+ Column" is now a toolbar button (click it, then click a row) instead of a per-row button.
- Adding a column now inherits its row's platform visibility instead of showing every platform.
- A newly added platform now defaults to hidden on Home shelves and in the Library/Pick 6 filter, toggle-able in the Library modal.
- Blacklist Manager keeps its search and bulk-select controls pinned above the list while scrolling.
- Blacklist Manager's platform group headers are more visually prominent.
- New shelves and columns no longer default to a placeholder label, leaving more room for the card art.

### Fixes

- A Home shelf using a PAGYWOSG-built saved filter showed no games. (reported by quinnix)
- A quick preset filter (e.g. Installed) ignored unsaved platform toggle changes in the Filters modal.
- Several modal headers scrolled out of view instead of staying pinned at the top.
