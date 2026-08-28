# Release Notes

## v1.9.0
### New

- Non-Steam games (EA, Ubisoft, Epic, GOG, etc.) can now fill in missing metadata — tags, review score, genres, developer/publisher, release date — from the matching Steam page, found via PCGamingWiki. Runs as part of a bulk rescrape, or per-game from the edit window. An exact name match on Steam is now always preferred, PCGamingWiki pages are looked up by title first (more reliable than its search), and games that were delisted from Steam still get developer/genre/release info from PCGamingWiki instead of a wrong guess.

- The Blacklist Manager's "Find Steam Junk" is now "Find Library Junk": the title-pattern scan (betas, demos, prototypes, soundtracks, dev kits, source-code drops) covers every platform, not just Steam, and a new "Deep Plugin Scan" button asks each store plugin to re-check its own library for DLC and non-game apps that slipped in before its import filter existed.

### Fixed

- HowLongToBeat lookups had stopped working entirely after HLTB changed their search API. Updated the HLTB library so matching, confirming, and pasting a game ID or URL all work again.
- When HowLongToBeat is unreachable, confirming or re-scraping a match no longer silently wipes the existing match and files the game under "no match". The stored match is kept and you get a clear "couldn't reach HowLongToBeat" message instead.
- "Confirm all above threshold" in the HLTB Data window now runs as a background job. It keeps going if you close the window or move to another page, shows progress in the top-bar job indicator, and reports how many were confirmed, had no time data, or failed.
