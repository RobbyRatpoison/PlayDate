# Release Notes

## v1.6.7
### New

- The library search bar now narrows results live as you type instead of waiting for Enter.
- Tag, Group, Genre, and Category filter conditions now hold multiple values in one row as chips, instead of a separate row per value. Older filters convert automatically.
- Auto-generated title-word filter conditions now show a plain description instead of raw SQL.
- PAGYWOSG auto-fill recognizes more category types (release dates, achievement counts/ranges, title patterns, AppID digits, review ratings), so fewer need manual review.
- "Personal categories" in the PAGYWOSG builder now include your own verified games instead of excluding the category entirely, and inherently personal categories can come pre-checked automatically.
- Added a `CONTRIBUTORS.md` crediting everyone who's helped shape PlayDate through bug reports and feedback.

### Fixes

- Fixed the "✕ CLEAR" button staying visible with a hidden platform source even when no filter or search was active.
- Fixed the update checker getting stuck on a broken download link if a release wasn't fully published yet.
- Fixed text selection not lining up with visible text in the filter editor's SQL preview.
- Fixed the hamburger menu looking lopsided when focused with a gamepad by combining its three notification dots into one.
- Fixed the Linux/macOS installer showing "Done" instead of launching PlayDate when setup finished - it now launches automatically like on Windows.
