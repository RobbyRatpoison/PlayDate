# Release Notes

## v1.8.0 - 2026-08-25
### New

- Library sort by HLTB time now has separate options for Main Story, Main + Extras, Completionist, Shortest, and Longest. (suggested by greatmastermario)
- Library sort by Achievement % and Achievements Remaining.
- Two new Card Badges: Achievement % and Review Score (raw or weighted, your choice), both with custom color thresholds you set yourself (Appearance → Card Badges → Configure).
- A third new Card Badge: HLTB Time, showing whichever HowLongToBeat time you pick (Main Story, Main + Extras, Completionist, Shortest, or Longest).
- Pick 6 greys out completion-status toggles that wouldn't return any games.
- Pick 6's completion-status toggles now remember your last choice.
- Detects games no longer at 100% achievements (e.g. the developer added more after you'd completed it) and downgrades them from Completed to Beaten.

### Improvements

- Pick 6's completion-status toggles now default to Never Played, Unfinished, Beaten, and Completed (previously just the first two).
- Auto-marking games Completed at 100% achievements can now be turned off (Library → Completion Sync).

### Fixes

- Fixed Pick 6's Smart and Weighted modes always excluding Beaten and Completed games regardless of the status toggles.
- Fixed Pick 6 ignoring the "Hide Duplicates" setting.
