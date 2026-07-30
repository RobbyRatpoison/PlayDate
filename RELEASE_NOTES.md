# Release Notes

## v1.6.11
### New

- Secret Santa / Snowballs gifts can now be tagged with the year given, shown in the PAGYWOSG hover tooltip as evidence. Group-add can tag a whole batch at once. (suggested by greatmastermario)
- PAGYWOSG builder now shows the selected tags for each pool (wins/all).
- PAGYWOSG builder now surfaces "personal category" candidates for an upcoming event even before anyone's verified appids yet.

### Fixes

- Fixed the "View on IndieGala" link in the edit panel pointing to a broken, mangled URL. It now links to the game's actual page; re-running "Sync IndieGala Library" will fix games already in your library. (reported by DarkRainX)
- Fixed the per-game "Sync" button doing nothing for IndieGala games — it now re-fetches and corrects that game's link.
- Fixed single-game "Sync" in the edit panel silently reporting success while offline instead of showing an error (Steam, EA App, itch.io).
- Fixed the edit panel's store link not refreshing until you saved and reopened it after syncing a game.
- PAGYWOSG: fixed quoted AppID categories (e.g. `"45" in their Steam AppID`) not being auto-detected. (reported by greatmastermario)
- Secret Santa / Snowballs list: fixed the scrollbar covering the remove button, and titles no longer accidentally remove a game on click.
- PAGYWOSG builder: fixed icaio giveaway/wishlist games no longer counting toward "additional games included."
