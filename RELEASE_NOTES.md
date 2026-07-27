# Release Notes

## v1.6.7
### New

- The library search bar now narrows results live as you type, and widens back as you delete — no more waiting for the page to reload.
- Tag, Group, Genre, and Category filter conditions can now hold multiple values in a single row — type to add or remove values as chips instead of adding a separate row for each one. Filters saved with the old one-row-per-value format are automatically converted when opened for editing.
- Auto-generated title-word filter conditions (used by PAGYWOSG filters) now show a plain description instead of raw SQL in the filter editor.
- PAGYWOSG auto-fill recognizes many more category types now, including release dates, achievement counts and ranges, title patterns, AppID digit patterns, and review ratings, so fewer categories need manual review each month.
- "Personal categories" in the PAGYWOSG builder now include games verified specifically for your own SteamGifts username (set in Settings) instead of excluding the category's verified games entirely. Categories that are inherently personal can also come pre-checked automatically based on maintainer review.

### Fixes

- Fixed the "✕ CLEAR" button staying visible on the library page whenever a platform source was hidden, even with no active filter or search.
- Fixed the update checker getting stuck showing "Install Update" with the same broken download link after a release wasn't fully published yet — going back and retrying now checks for updates again instead of reusing the stale result.
- Fixed text selection not lining up with the visible text when copying SQL from the filter editor's preview box.
