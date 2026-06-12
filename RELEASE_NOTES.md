# Release Notes

## v1.5.14

### New Features

- GOG, EA, Humble, and itch.io games now fall back to Steam CDN art when SteamGridDB has no cover art.
- Steam library collections are now synced to groups at startup. Games in a collection get the collection name added as a group; removing a game from a collection removes the group on next launch. The Favorites collection is included; Hidden is not.
- If a Steam collection and a BLAEO list share the same name, they merge into one group. Removing a game from one source only removes the group if the other source no longer claims it too.

### Bug Fixes

- IndieGala: sync now reports an error when the session cookie has expired, instead of silently reporting 0 games added.
- BLAEO: renaming a list no longer affects games that have the same group name from a different source (e.g. a Steam collection).
