# Release Notes

## v1.9.2 - 2026-08-31
### New

- Import your SteamGifts wins into a "Won on SteamGifts" group, using the Date Importer userscript. Captures win date, gifter and point cost, and checks received status.
- Manually add a SteamGifts win to your library when Steam no longer lists the game as owned.

### Fixes

- Scrape New Games no longer fails with "Could not reach Steam" when a Steam API key is set.
- Sync Steam Data handles delisted games: it keeps their existing details instead of blanking them, and fills release date and playtime from local Steam files.
- PAGYWOSG "personal" categories now follow the active account when more than one Steam account shares a PC.
- A PAGYWOSG filter with a multi-group condition no longer stops the edit panel from opening or the hover match from showing.
