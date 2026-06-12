# Release Notes

## v1.5.14

### New Features

- GOG, EA, Humble, and itch.io games now fall back to Steam CDN art when SteamGridDB has no cover art.
- Steam library collections are now synced to groups at startup. Games in a collection get the collection name added as a group; removing a game from a collection removes the group on next launch. The Favorites collection is included; Hidden is not.
- If a Steam collection and a BLAEO list share the same name, they merge into one group. Removing a game from one source only removes the group if the other source no longer claims it too.
- Manually created PlayDate groups are now tracked alongside sync sources. If a manually created group shares its name with a Steam collection or BLAEO list, renaming the sync source keeps the original group name on the game and adds the new name alongside it.
- Group ownership data is now included in backups and restored with the rest of your library.

### Bug Fixes

- IndieGala: sync now reports an error when the session cookie has expired, instead of silently reporting 0 games added.
- BLAEO: renaming a list no longer affects games that have the same group name from a different source (e.g. a Steam collection).
- BLAEO sync preview: checkbox layout was broken (checkbox appeared centred, text overflowed the modal).
