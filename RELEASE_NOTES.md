# Release Notes

## v1.5.6 — Pending

### New Plugins

- **itch.io** — sign in to your itch.io account to import your purchased library. Games are downloaded and launched directly. Download progress is shown in the nav bar with a cancel button. Installed games can be uninstalled from the right-click menu.
- **Humble Bundle** — connect with your `_simpleauth_sess` cookie to import your library. Games are downloaded and launched directly. Non-game items (soundtracks, art books, etc.) are filtered out automatically. Installed games can be uninstalled from the right-click menu.

### Emulators

- Added emulator support (Menu → Emulators). Point PlayDate at your ROM folders and it scans them into your library — cover art is fetched from SteamGridDB automatically.
- A wide range of systems and emulators are supported and detected automatically. RetroArch is supported, with per-system core selection. Custom emulators can be added manually.

### Duplicates

- Duplicate images are now shared: if a game marked as a duplicate has no image of its own, the canonical game's image is shown automatically.
- HLTB data is now propagated across duplicate groups: confirming a match for any game in the group applies it to all others. Linking a game as a duplicate of another also copies confirmed HLTB data immediately.
- Duplicate detection now includes all installed plugins automatically, so non-Steam games can be matched against each other without Steam being involved.

### GOG

- On Linux, Windows GOG games now launch via Proton when available, with Wine as a fallback.

### Artwork

- Added a Clear button to each artwork slot in the edit modal (cover, header, icon).
- Fixed an issue where bulk art scraping did not fetch art for non-Steam games.
- Game covers that don't match their container's aspect ratio now show a blurred background fill instead of cropping or stretching.

### Library

- Sort by Random added to the View modal.
- Improved scroll performance in grid and list view.

### Monthly in a Month

- Added a Monthly in a Month filter builder (Menu → Community). It cross-references your library against the community list and saves a filter for eligible unplayed games.
