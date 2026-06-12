# Release Notes

## v1.5.14 — 2026-06-12
### New Features

- Steam library collections sync to groups at startup. Renaming or removing a collection updates the group on next launch.
- Groups shared between a Steam collection and a BLAEO list are protected — renaming one won't affect the other.
- If you manually add a group with the same name as a Steam collection or BLAEO list, renaming the sync source keeps your original group and adds the new name alongside it.
- Non-Steam games (GOG, EA, Humble, itch.io) now fall back to Steam CDN art when SteamGridDB has no cover.

### Bug Fixes

- IndieGala: sync now shows an error when your session has expired instead of silently reporting 0 games.
- BLAEO sync preview: checkbox layout was broken.
