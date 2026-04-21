# TODO

## Pending (next release)

- none

## User requests and other things that need sorting

- none

## Known Bugs

- **Ghost tooltip circle on secondary monitor** — a gray circle appears in the top-left corner of the secondary monitor. When hovering over elements in PlayDate, the tooltip renders at the circle's position first before snapping into the window. Likely caused by the tooltip div being positioned relative to a wrong coordinate origin on multi-monitor setups. Potentially fixed but I am leaving it here until I feel confident that the fix worked.
- **PlayDate on Steam Deck** — controller support is completely broken

---

## Improvements

- **Gamepad support** — home page editor buttons, bulk edit modal navigation, text input focus, disable RB/LB while in modals *(partial: `clearSuppression()` added; remaining: modal navigation, text input focus)*
- **Simplify code** — files remaining: library.py, uninstall.py, images.py, playdate.js, input.js, style.css, and all html files

---

## Small Features

- **PAGYWOSG Snowballs / Secret Santa support** — Snowballs and Secret Santa are PAGYWOSG/POP gift events. The filter builder and quals panel should recognise their pool/criteria structure the same way the main PAGYWOSG event does.
- **Cross-platform duplicate priority order** — when a game is owned on multiple platforms, the duplicate hider should show the version from whichever platform ranks highest in a user-configurable priority list. Currently it always prefers Steam (GOG copies are hidden if the same game exists on Steam). Should support drag-to-reorder platform priority in Settings.
- **Steam Deck installation** — see Implementation Plans

---

## Big Features

- **Non-Steam library support** — see Implementation Plans
- **Card badges** — see Implementation Plans
- **Library list/details view** — alternative to grid mode: scrollable game list on the left, detail panel on the right (similar to Steam's layout). Detail panel combines the two edit modal panels (metadata + edit fields) and adds a game description. Descriptions are not currently scraped -- would need a new column and a scrape step (Steam store `appdetails` already returns `short_description` and `detailed_description`). Open questions: whether the list column shows cover art thumbnails or just text rows; whether the detail panel is read-only or doubles as an inline editor; how to handle the description field in populate (scrape alongside existing meta worker or separate phase).
- **Plugin system**

---

## Potential / Under Consideration

- **Sort by total reviews** — sort by `total_reviews` to surface popular games or find obscure ones. Already in `SAFE_COLUMNS`, just needs a dropdown option.
- **Extend Playnite import** — also import completion status

---

## Implementation Plans

### Non-Steam Library Support

Add games from other launchers and eventually DRM-free/emulated titles alongside Steam games.

**ID scheme:** Non-Steam games use negative integer appids (-1, -2, -3 ...). Steam never uses negatives. `config.json` gains `next_nonsteam_id: -1`, decremented on each add. Art files stored as `static/img/library/vertical/-1.jpg` etc. Flask uses a `SignedIntConverter` (regex `r'-?\d+'`) so routes accept negatives. `appid_list` validation allows zero/negative values.

**Implemented columns (v1.4.0):**
- `platform` TEXT — `'steam'` (default/backfilled), `'gog'`, `'epic_games'`, `'ea_app'`, `'ubisoft'`
- `platform_id` TEXT — platform-native game ID (e.g. GOG product ID)
- `platform_slug` TEXT — GOG store URL slug
- `install_path` TEXT — game install directory
- `wine_prefix` TEXT — Proton wine prefix path
- `runner_path` TEXT — Proton runner path
- `platform_executable` TEXT — path to primary executable
- `duplicate_of` TEXT — appid of the canonical (preferred) version; games with `duplicate_of IS NOT NULL` are hidden from library by default; toggle via "DUPES: OFF/ON"
- `meta_fetched`, `cheevos_fetched` — per-phase completion tracking

**Filesystem watching (per-platform install status):** Each platform needs equivalent watching to Steam's `appmanifest_*.acf` watcher. Pattern: watch the platform's games root for directory creates/deletes/moves, sync `installed` flags on change. GOG done (`start_gog_watcher` / `sync_gog_install_status` in `utils.py`). Other platforms: implement when integrated.

**GOG integration (done — v1.4.0):**
- OAuth2 auth (auth-code flow, public GOG client credentials)
- Library sync via `embed.gog.com/account/getFilteredProducts` (paginated)
- Metadata via `api.gog.com/v2/games/{id}` — developers, publishers, genres, tags, release date, platform_slug
- Achievements via `gameplay.gog.com/clients/{gog_id}/users/{galaxy_user_id}/achievements`
- Content-system v2 install: builds → meta manifest → depot manifests → zlib chunk downloads
- Launch: Windows games via Proton (`runners/proton.py`), Linux native directly
- Proton detection across `~/.steam/steam` and `~/.local/share/Steam` (GE-Proton + official)
- Auto duplicate detection: GOG games matched to Steam by normalized name
- Purchase date import via Tampermonkey on GOG orders page (v2.4)
- Settings UI: Connect/Disconnect, Sync Library, Sync Metadata, Detect Duplicates, Import Purchase Dates

**Art:** SteamGridDB name search via `_sgdb_search_game_id(name)` — returns SGDB internal game ID, passed as `sgdb_id` to skip Steam CDN and query `grids/game/{sgdb_id}` directly. When a Steam counterpart exists (via PCGW), Steam CDN art is used instead.

**Metadata via PCGW + Steam:** PCGamingWiki's Cargo API (`https://www.pcgamingwiki.com/w/api.php?action=cargoquery`) is public and keyless. Query by game name to get Steam ID if one exists. If found, scrape metadata from Steam Store API as for Steam games. Non-Steam games with no Steam counterpart fall back to platform-native APIs (GOG API) or edit-modal-only metadata.

**Duplicate suppression (cross-platform dedup):** Implemented via `duplicate_of` column (not the originally planned `canonical_appid`). When PCGW returns a Steam ID for a non-Steam game, `duplicate_of` is set to that Steam appid. Library query excludes `duplicate_of IS NOT NULL` by default. Edit modal shows a "Duplicate of:" row with searchable Steam library lookup and unlink button. Auto-detection runs after GOG library sync; manually re-runnable via "Detect Duplicates". User-configurable global priority order is not yet implemented — current logic always prefers the Steam version.

**Populate / scraping:** `bulk_rescrape_games()` routes GOG games to `fetch_gog_metadata()` + `fetch_gog_achievements()`; Steam games use existing scrapers. Rate limiting only applies to Steam workers. Inter-game delay: 0.5s.

**Filters:** `platform` added to `SAFE_COLUMNS` and `FM_FILTER_CONFIG` as select-type filter with options: Steam, GOG, Epic Games, EA App, Ubisoft.

**Phase 1 — Remaining launchers (not yet started):**

*Windows/Mac:* Read each launcher's install manifests to detect installed games:
- **GOG:** `%PROGRAMDATA%\GOG.com\Galaxy\storage\` (SQLite) — *partially superseded by direct GOG API integration*
- **Epic:** `%PROGRAMDATA%\Epic\EpicGamesLauncher\Data\Manifests\*.item` (JSON)
- **EA App:** `%PROGRAMDATA%\EA Desktop\EA Desktop\` manifests
- **Ubisoft:** Registry + `%PROGRAMFILES%\Ubisoft\Ubisoft Game Launcher\games\`
- **Rockstar:** `%PROGRAMFILES%\Rockstar Games\Launcher\` + registry entries under `HKLM\SOFTWARE\WOW6432Node\Rockstar Games\`; launch via `rockstar://` URI scheme or direct exe

Launch via OS-registered URI schemes: `goggalaxy://openGame/{id}`, `com.epicgames.launcher://apps/{name}?action=launch`, `uplay://launch/{id}/0`, `origin://LaunchGame/{id}`, `rockstar://`. Use `webbrowser.open()` or `subprocess` depending on OS.

**Phase 2 — DRM-free + emulated:** Manual "Add game" dialog (Name, Type, Path via `pywebview.api.pick_open_path`). Install status checked by whether `game_path` file exists on disk.

**Phase 3 — itch.io:** Import from itch.io desktop app database (`%APPDATA%\itch\db\butler.db` on Windows, `~/.config/itch/db/butler.db` on Linux — SQLite). Tables: `games` (id, title, cover_url, url), `caves` (game_id, install_folder_path, installed). Launch via `itch://games/{id}` URI scheme or directly via `butler` daemon. itch.io has no DRM layer so games can also be launched directly from `install_folder_path`. API: `https://itch.io/api/1/{api_key}/...` (optional, for metadata enrichment). Note: itch.io game IDs are integers; art fetched from `cover_url` stored in game record.

### Steam Deck Installation

Support first-class Steam Deck installation with a dedicated script and a graceful error message when deps are wiped by a SteamOS update.

**`install_steamdeck.sh`:**
- Check if a sudo password is set; if not, print a message telling the user to run `passwd` and exit
- `sudo steamos-readonly disable`
- `sudo pacman-key --init && sudo pacman-key --populate archlinux`
- `sudo pacman -S --noconfirm python-gobject webkit2gtk`
- Run `install.sh`
- `sudo steamos-readonly enable`
- Script doubles as repair script -- safe to re-run after a SteamOS update wipes the packages

**`main.py` import guard:**
- Wrap the pywebview import in a try/except ImportError
- Check `/etc/os-release` for `ID=steamos` to tailor the message
- SteamOS: show a tkinter messagebox telling the user to re-run `install_steamdeck.sh`
- Other Linux: show a generic "reinstall dependencies" message pointing to the README
- Use tkinter (same as uninstaller) so it works without pywebview

**README:**
- Add a Steam Deck subsection under Linux
- Cover: set a password first (`passwd`), run `install_steamdeck.sh`, note that packages are wiped on SteamOS updates and the script should be re-run to restore them

**Release notes:**
- Brief mention of Steam Deck support, point to README for details

---

### Card Badges

Show up to 3 colored dot badges across the bottom of game cards, driven by saved filters. User-configurable — any saved filter can be assigned a color and shown as a badge.

**Data (`state.json`):**
- Saved filters gain an `id` field (UUID). Auto-migrated on load: bare filter trees get wrapped as `{ "id": "...", "tree": {...} }`.
- New top-level `card_badges` array. Each entry: `{ "id", "filter_id", "color", "priority", "show_on": { "library", "home", "pick6" } }`.

**Behavior:**
- Up to 3 badges shown per card, in priority order (lowest priority number = highest priority).
- Evaluated server-side by reusing the existing filter→SQL pipeline — badge-matching appids are computed alongside the grid query.
- Rendered as CSS colored dots (`border-radius: 50%`) in a row along the bottom of the card.
- `show_on` flags control which of the three card surfaces display badges: Library grid, Home page shelves, Pick 6.

**UI (Card Settings section in Settings page):**
- List of badge rules: saved filter name (resolved from `filter_id`) → color picker → page toggles (Library / Home / Pick 6) → drag-to-reorder priority → delete button.
- "Add Rule" button — opens a picker for an existing saved filter + color.
- When deleting a saved filter that has one or more badge rules referencing it, show a warning.
