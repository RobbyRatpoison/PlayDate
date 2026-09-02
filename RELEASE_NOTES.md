# Release Notes

## v1.10.0
### New

- The Home layout editor can now resize a shelf's height or a split row's column widths by dragging, instead of typing numbers only.
- Columns within a split row can now be reordered by dragging; dragging one onto a different row moves that whole row instead.
- Split rows now support up to 15 columns (up from 3), useful for hand-picking and ordering a specific lineup of games.
- A shelf's Games count now auto-adjusts to fit whenever it's resized, so a wider shelf shows more and a narrower one shows fewer, without manually retyping a number.
- Find Library Junk's "No Longer Owned" section can now whitelist a game (keep it, stop suggesting it) instead of only deleting it.

### Improvements

- Home page shelves can now scroll to show shelves that don't fit on one screen. (prompted by feedback from quinnix)
- The Home layout editor warns if the current layout won't fit on one screen.
- Home layout editor buttons now match the rest of the app's look.
- Edit and Remove stay reachable in the shelf layout editor even on very narrow columns.
- "+ Column" is now a toolbar button (click it, then click a row) instead of a per-row button.
- Adding a column to a row now inherits that row's platform visibility instead of showing every platform.
- A newly added platform (e.g. from installing a new plugin) now defaults to hidden on existing Home shelves and in the Library/Pick 6 platform filter, instead of appearing everywhere immediately; toggle-able in the Library modal.
- Blacklist Manager keeps its intro text, search box, and bulk-select controls pinned above the list while scrolling, instead of only the title.
- Blacklist Manager's platform group headers are more visually prominent, easier to scan in a long list.

### Fixes

- A Home shelf using a PAGYWOSG-built saved filter showed no games. (reported by quinnix)
- Clicking a quick preset filter (e.g. Installed) in the Filters modal ignored any platform toggle changes made in that same modal, applying the previously-saved platform selection instead.
- Several modal headers (Plugins, Account, Import Data, Playnite Import, Blacklist Manager, Find Library Junk, Theme Editor, Theme Picker, Emulators) scrolled out of view along with the rest of a tall modal's content instead of staying pinned at the top.
