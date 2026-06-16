# Release Notes

## v1.5.18 — Pending

### Improvements

- BLAEO sync now runs in the background. Start a sync from Community Tools and continue using the app while it scrapes. A notification dot and menu item appear in the hamburger menu when results are ready (or failed); clicking it opens the BLAEO review panel to confirm or discard changes.
- Active library search is now preserved when applying or changing filters from the filter modal. CLEAR ALL + Apply correctly clears both the search and the filters together.
- Saving a filter with an existing name now prompts for confirmation before overwriting.
- Applying a built-in filter preset (Installed, Never Played, Beaten, etc.) now stores editable filter tree conditions instead of raw SQL. Reopening the filter modal after applying a preset shows editable rows rather than the custom SQL box.
- Clearing filters (✕ CLEAR in the library bar, or CLEAR ALL in the filter modal) no longer resets platform source toggles.
