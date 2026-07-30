# Release Notes

## v1.6.11
### Fixes

- Fixed the "View on IndieGala" link in the edit panel pointing to a broken, mangled URL. It now links to the game's actual page; re-running "Sync IndieGala Library" will fix games already in your library. (reported by DarkRainX)
- Fixed the per-game "Sync" button doing nothing for IndieGala games — it now re-fetches and corrects that game's link.
- Fixed single-game "Sync" in the edit panel silently reporting success while offline instead of showing an error (Steam, EA App, itch.io).
- Fixed the edit panel's store link not refreshing until you saved and reopened it after syncing a game.
