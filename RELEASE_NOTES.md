# Release Notes

## v1.6.10
### Fixes

- Fixed gamepad input occasionally still controlling PlayDate in the background while navigating the Steam Deck's own Game Mode menus (e.g. installing a game from the Home screen while PlayDate was running).
- Fixed IndieGala library sync repeatedly re-fetching the same first page instead of paging through the rest of the library, so only the first handful of games ever synced. (reported by DarkRainX, who also found and supplied the fix)
