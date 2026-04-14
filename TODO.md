# TODO

## Known Bugs

- **GOG install: executable not found after install** — `_find_gog_executable` fails to locate the primary executable, resulting in a "Cannot find executable for '{game name}' — Please set it manually" toast. Likely causes: (1) `goggame-{product_id}.info` is absent or has no `playTasks` of type `FileTask`; (2) the `.info` file uses a `WorkingDir`-relative path that doesn't resolve correctly; (3) Linux native builds don't follow the `goggame-*.info` convention and none of the fallback shell script names (`start.sh`, `game.sh`, etc.) match. Fix: surface the install path in the toast so the user can browse to it; improve the Linux fallback to scan for any executable file in the install root.
- **GOG install: meta manifest decompression fails** — `_fetch_manifest(build['link'], session)` raises "Could not decompress data (tried zlib/deflate/gzip)". Likely causes: (1) `build['link']` is now a pre-signed CDN URL that returns uncompressed JSON rather than zlib-wrapped data, so `_zlib_decomp` has nothing to do; or (2) the URL requires CDN auth (the secure_link `cdn_urls`) not just Bearer session auth, so the response is an error page rather than the manifest. Fix: try `json.loads(resp.content)` first and fall back to decompression; and if 403, try constructing the manifest URL via `_build_chunk_url`/secure_link. This surfaces after the CDN token fix (switched from deprecated `/token` endpoint to `secure_link`).
- **GOG install: partial install directory left on failure** — When a chunk download fails (e.g. 403), the install aborts immediately but leaves the `~/Games/GOG/{game}/` directory behind with whatever files were opened before the failure. Files are created with `open(dest_path, 'wb')` before the chunk fetch, so they exist on disk as 0-byte stubs (observed: only `goggame-{id}.script` files present after a failed install — these happen to be the first files processed). Fix: on any non-cancelled error return, delete the install directory (or at minimum log its path so the user knows to clean it up manually).
- **Cross-platform duplicate hiding** — `duplicate_of` column exists and GOG↔Steam auto-detection works by normalized name, but the implementation is limited to GOG. Epic/EA/Ubisoft integration (when added) will need the same matching logic. Manual linking via the edit modal works for any non-Steam game.
- **Non-Steam metadata limited to PCGW-matched games** — `sync_lutris_meta` resolves a Steam AppID via PCGamingWiki and then uses the existing Steam scrape pipeline. Games with no PCGW entry (niche or unlisted titles) get `meta_fetched = 'no_match'` and remain without tags, genres, or review scores.

---

## Improvements

- **Gamepad support** — home page editor buttons, bulk edit modal navigation, text input focus, disable RB/LB while in modals *(partial: `clearSuppression()` added; remaining: modal navigation, text input focus)*
- **Pick 6 factor range limits** — allow optional min/max hard limits on each scoring factor, hard-excluding games outside the range before scoring. Factors: HLTB length (min/max hours), playtime (min/max hours recorded), review score (min/max %), staleness (min/max days since last played), release recency (earliest/latest year). Limits apply before the scoring pool is built, so weights still operate on a clean candidate set. Open questions: UI placement (inline with weights, or a separate "filters" row); whether to enforce a minimum pool size and warn/relax when limits are too tight; how to handle games with missing data for a limited factor (exclude vs treat as unconstrained).

---

## Small Features

- **Library group-by** — sort games into sections by a chosen field (e.g. installed status, completion status, ProtonDB tier); each section sorted by the active sort column and direction. Implementation approach for non-obvious grouping fields TBD. Group-by installed (installed games first) is the most-wanted specific case.
- **PAGYWOSG Snowballs / Secret Santa support** — Snowballs and Secret Santa are PAGYWOSG/POP gift events. The filter builder and quals panel should recognise their pool/criteria structure the same way the main PAGYWOSG event does.

---

## Big Features

- **Non-Steam library support** — see Implementation Plans
- **Card badges** — see Implementation Plans
- **Library list/details view** — alternative to grid mode: scrollable game list on the left, detail panel on the right (similar to Steam's layout). Detail panel combines the two edit modal panels (metadata + edit fields) and adds a game description. Descriptions are not currently scraped -- would need a new column and a scrape step (Steam store `appdetails` already returns `short_description` and `detailed_description`). Open questions: whether the list column shows cover art thumbnails or just text rows; whether the detail panel is read-only or doubles as an inline editor; how to handle the description field in populate (scrape alongside existing meta worker or separate phase).
- **Plugin system**

---

## Potential / Under Consideration

- **BLAEO sync downgrade prevention** — BLAEO sync unconditionally overwrites `completion_status` with whatever BLAEO reports, which can downgrade e.g. `Beaten` → `Unfinished`. Options: a hard guard matching `sync_recent_playtime` logic (never downgrade Beaten/Completed), a per-direction setting (e.g. "allow BLAEO to downgrade from Beaten"), or a setting toggle for each status transition. Direction of travel: probably a settings option since some users may want BLAEO to be authoritative.
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

*Linux:* Import from Lutris (`~/.local/share/lutris/pga.db` — SQLite). Launch via `lutris lutris:rungameid/{id}`. Lutris covers native, Wine, GOG, and Epic games in one integration.

*Windows/Mac:* Read each launcher's install manifests to detect installed games:
- **GOG:** `%PROGRAMDATA%\GOG.com\Galaxy\storage\` (SQLite) — *partially superseded by direct GOG API integration*
- **Epic:** `%PROGRAMDATA%\Epic\EpicGamesLauncher\Data\Manifests\*.item` (JSON)
- **EA App:** `%PROGRAMDATA%\EA Desktop\EA Desktop\` manifests
- **Ubisoft:** Registry + `%PROGRAMFILES%\Ubisoft\Ubisoft Game Launcher\games\`

Launch via OS-registered URI schemes: `goggalaxy://openGame/{id}`, `com.epicgames.launcher://apps/{name}?action=launch`, `uplay://launch/{id}/0`, `origin://LaunchGame/{id}`. Use `webbrowser.open()` or `subprocess` depending on OS.

**Phase 2 — DRM-free + emulated:** Manual "Add game" dialog (Name, Type, Path via `pywebview.api.pick_open_path`). Install status checked by whether `game_path` file exists on disk.

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
