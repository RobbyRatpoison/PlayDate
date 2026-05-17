# Release Notes

## v1.5.6 — Pending

### New Plugins

- **Humble Bundle** — connect with your `_simpleauth_sess` session cookie to import your Humble library. Games open in your browser on the Humble library page.
- **IndieGala** — connect with your `sessionid` cookie to import your IndieGala showcase. Games open in your browser on the IndieGala store page.
- **Rockstar Games** — connect with your `sc-auth-token` cookie to import your Rockstar Games library. Games open in your browser on the Rockstar store page.
- **Amazon Games** — if you use Heroic Games Launcher with Nile, your Amazon library is detected automatically with no login needed. Alternatively, connect with your `at-main` cookie from amazon.com. Games launch via Nile if available, or fall back to the browser.

### itch.io Plugin

- Added an itch.io plugin. Connect with an API key (Menu → Plugins → itch.io) to import your purchased library.
- Games are downloaded and launched directly — no itch.io app required. Windows games are launched via Proton if available, with Wine as a fallback.
- Download progress is shown in the nav bar with a cancel button.
- Cover art is fetched from SteamGridDB, with the itch.io game cover used as a fallback for any slots not found.
- Installed itch.io games can be uninstalled from the right-click context menu.

### Duplicates

- Duplicate images are now shared: if a game marked as a duplicate has no image of its own, the canonical game's image is shown automatically.
- HLTB data is now propagated across duplicate groups: confirming a match for any game in the group applies it to all others. Linking a game as a duplicate of another also copies confirmed HLTB data immediately.
- Duplicate detection now includes all installed plugins automatically, so non-Steam games can be matched against each other without Steam being involved.

### Artwork

- Added a Clear button to each artwork slot in the edit modal (cover, header, icon). Clearing removes the cached image so the next rescrape or manual upload starts fresh.

### Library

- Sort by Random added to the View modal.
- Improved scroll performance in grid and list view.

### Monthly in a Month

- Added a Monthly in a Month filter builder (Menu → Community → Monthly in a Month Filter Builder). It fetches the community game list, cross-references your Steam library, and saves a filter for eligible games you haven't started. Games already marked Beaten or Completed are excluded automatically, with an option to also exclude Won't Play games.
