# Release Notes

## v1.9.0
### New

- Non-Steam games (EA, Ubisoft, Epic, GOG, etc.) can fill in missing metadata — tags, review score, genres, developer, publisher, release date — from their Steam page, found via PCGamingWiki. Runs during a bulk rescrape or per-game from the edit window.
- "Find Steam Junk" is now "Find Library Junk": the title scan (betas, demos, prototypes, soundtracks, dev kits) covers every platform, plus a Deep Plugin Scan that asks each store for DLC and non-game apps.

### Improvements

- HLTB "Confirm all above threshold" runs as a background job that keeps going if you leave the page.

### Fixes

- HowLongToBeat lookups work again after their search API changed; pasting a game ID or full URL both work.
- An unreachable HowLongToBeat no longer wipes a game's stored HLTB match.
