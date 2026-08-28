# Release Notes

## v1.9.0
### New

- Non-Steam games can backfill missing metadata (tags, reviews, genres, dev/publisher, release date) from their Steam page via PCGamingWiki; itch.io exclusives fall back to their itch store page. Runs automatically in the background after launch, or on demand from Bulk Tools > Re-scrape.
- "Find Steam Junk" is now "Find Library Junk": title scan covers every platform, plus a Deep Plugin Scan for store DLC and non-game apps.

### Improvements

- HLTB "Confirm all above threshold" runs as a background job that survives leaving the page.

### Fixes

- HowLongToBeat lookups work again after their search API changed.
- An unreachable HowLongToBeat no longer wipes a game's stored match.
- Cleaner plugin imports: Humble skips mobile-only games and bundled software, Epic skips browsers and dev kits, Humble Monthly/Choice games show their real developer.
