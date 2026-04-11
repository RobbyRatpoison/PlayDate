# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Pending (next release)

> When a TODO item is completed, move it here immediately. When releasing, use this section to write release notes, then clear it. Old release notes are deleted from `RELEASE_NOTES.md` on each publish — only the current version's notes are kept.

*(none)*

## Populate Speed Overhaul — Notes

- Populate runs three concurrent worker pools: 5 art, 1 meta, 2 cheevo
- Meta is 1 worker at 1.5s fixed delay — appdetails hard limit is 200 req/5min (count-based rolling window); 2 workers was the root cause of 429s
- `_fetched` columns (`art_fetched`, `meta_fetched`, `cheevos_fetched`) track per-phase completion; workers skip already-fetched games
- Placeholder cards batch-inserted immediately; per-card live updates as each phase completes; viewport-visible cards prioritized via `/api/populate-priority`
- BLAEO pre-scrape runs concurrently with art/meta after placeholder insert; cheevo workers start after it finishes
- `RateLimitedError` is re-raised in all fetch functions so `_PoolBackoff` triggers correctly


## PAGYWOSG Filter Builder

The PAGYWOSG tool (`modal_tools.html`) builds structured filter trees for the monthly PAGYWOSG event on SteamGifts.

**Event ID formula:** event 83 = April 2026; `event_id = 83 + (year - 2026) * 12 + (month - 4)`

**Auto-fill:** `/api/pagywosg-auto` (in `app.py`) fetches `https://pagywosg.xyz/api/events/{id}`, classifies categories by regex (tag, release date, appid pattern, title pattern, gifter), and returns structured data. Accepts `?next=1` for upcoming-month prep. `_PAGYWOSG_SUPPLEMENT_PATH` constant in `app.py` points to a local JSON file (`pagywosg_supplement.json` in `BASE_DIR`) with curated data for subjective categories.

**Supplement file format** (`pagywosg_supplement.json`): top-level keys are `icaio_giveaways` (`[{appid, name}]`), `icaio_wishlist` (`{appid_str: name}`), and numeric event IDs for event-specific data. Event entries are keyed by category ID: `{pool, id_name, developers?, publishers?, appids?, verifiers?}` where `verifiers` is `{appid_str: username}`. The supplement is loaded once before the category loop so icaio data is available during classification.

**icaio category auto-detection:** categories whose name contains `"icaio has made a GA for"` are matched against `icaio_giveaways`; categories containing both `"icaio"` and `"wishlist"` are matched against `icaio_wishlist`. These entries are flagged `auto: true` (suppresses "mod verified" label in the quals panel). Phrase matching is intentionally exact to avoid false matches from similarly-worded categories.

**Pool determination:** categories with both `(win)` and `(backlog)` suffix variants go in the "all" pool; categories with no suffix go in the "wins" pool (wins-only).

**Filter tree structure:** root AND containing an OR of [all-pool branch, AND[steamgifts-won condition, wins-pool branch]], plus completion status exclusions. Also includes `appid IN (...)` for mod-verified games.

**Auto-fill appids response:** `_serialise_pool(pool_dict, tags, conds)` in `pagywosg_auto` returns each game with `in_library: bool` and `redundant: bool`. `in_library` is set via a bulk `SELECT appid FROM games WHERE appid IN (...)`. `redundant` is set via `_redundant_set()`, which checks whether the game would already be caught by the pool's tag conditions (`',' || tags || ','  LIKE ?`) or condition rows (`month_is`, `year_is`, `day_is`, `contains` on comma-separated or text columns). The "additional games" collapsible in `pagUpdateAppidsInfo` filters to `g.in_library && !g.redundant` so only genuinely extra library games are shown.

**Saved filter keys:** PAGYWOSG filters are stamped with extra keys on save: `pagywosg: true`, `pagywosg_event: {id, name}`, `pagywosg_verified: {appid: [{cat, pool, verifier?, auto?}]}`. These are preserved when applying a saved filter via `modal_filters.html` using `_loadedSavedTree`. `verifier` is the SteamGifts username of the person who submitted the game for mod verification (cited as proof by others); `auto: true` marks entries sourced from the scraper rather than a human submission.

**Qualifications panel:** `modal_edit.html` shows a `#pag-quals-section` when `_serverFilterTree.pagywosg` is true. `_pagRenderQuals(game)` walks the filter tree via `_pagExtractConds()` (detects wins branch by presence of a `groups` condition in any AND group) and checks each condition against the game. Pool labels: `(win)` for wins pool (only shown if game has the configured SG wins group), `(win)` or `(backlog)` for all pool based on groups. Mod-verified entries show "mod verified — see [username]'s entry"; entries with `auto: true` show no verification label.

**SG wins group configuration:** `_pagExtractSgGroup(tree)` (in `modal_edit.html`) extracts the `groups` condition value from the filter tree's wins-branch AND group — this is the actual group name used when the filter was built. `_pagSgGroup` in `modal_tools.html` holds the current working group name (string = chosen group, `null` = no SG wins, `undefined` = not yet loaded). `GET /api/pagywosg-sg-group` returns `{saved, unset, default_group, groups}`; `POST` saves to `state.json` as `pagywosg_sg_group`. On init, if `unset` and `default_group` is null, a warning UI prompts the user to choose a substitute or confirm no SG wins. The choice persists and pre-fills future builds.

**PAGYWOSG hover tooltip:** `library.html` has an IIFE that activates only when `_serverFilterTree?.pagywosg` is true. It uses event delegation on `#game-grid` with `mouseover`, calls `_pagExtractConds` / `_pagCheckCond` / `_pagLabel` / `_pagExtractSgGroup` (all available from `modal_edit.html` via `base.html`), and shows quals + HLTB min (formatted with `fmtHours()`) in a fixed tooltip div `#pag-hover-tooltip`.

## HLTB Integration

HowLongToBeat data is scraped via `howlongtobeatpy` in `scrapers.py`. Times are stored in minutes.

**`hltb_fetched` column states:** `NULL` or `'0'` = never fetched; `'unconfirmed'` = matched but below threshold (times stored as NULL); `'no_match'` = search returned no results; `YYYY-MM-DD` = confirmed match date.

**During populate:** `_hltb_worker` pool (2 workers) runs after BLAEO pre-scrape. Games already confirmed are skipped via `hltb_fetched` check.

**Startup catch-up:** `sync_hltb_unfetched()` in `scrapers.py` runs after `sync_recent_playtime()` in `_run_playtime_sync` (`main.py`). Fetches only `hltb_fetched = '0' OR NULL` — does not retry `no_match` games automatically.

**HLTB Review tool:** lives in `modal_tools.html` (accessible from Tools menu on all pages). Four collapsible sections: above-threshold unconfirmed, below-threshold unconfirmed, no-match, confirmed-below-threshold. `_hltbSectionCollapsed` dict controls collapse state; `_hltbToggleSection(key)` does direct DOM manipulation to avoid re-rendering open alt-results panels. Listens for `populate:hltb_done` custom event to refresh when populate finishes.

**`hltb_min` sort:** `library.py` defines `_HLTB_MIN_EXPR` / `_HLTB_MAX_EXPR` as SQL CASE expressions under `VIRTUAL_SORT_COLS['hltb_min']`; games with all NULL/zero times sort last.

## To-Do

See [TODO.md](TODO.md).

## What This Project Is

PlayDate is a local Steam library manager. It runs as a Flask web server wrapped in a native OS window via pywebview (no Electron). Users browse their Steam library, apply filters, track completion, and use a "Pick 6" feature to discover what to play next.

## Planned: Project Rename + Install Folder Migration

The project name "PlayDate" conflicts with other projects (notably Panic's handheld console). A rename is planned once a new name is decided.

**When the new name is chosen, things to update:**
- `playdate.iss` and `playdate.spec` — filenames and internal references
- `config.py` — app name strings, log filename (`playdate.log`)
- `steam_date_import.user.js` — script name and internal references
- `install.py` / `uninstall.py` — hardcoded "PlayDate" strings in the GUI
- `templates/` — page titles and branding text
- `static/` — any branding in CSS/JS
- GitHub repo name
- `DefaultDirName` in `playdate.iss` (keep `AppId` GUID unchanged — it ties installers together for upgrades)

**Install folder migration strategy (for the rename update):**

The installer should copy the old install folder to the new location, then delete the old one only after the copy succeeds. This applies to all users regardless of where they installed:

1. In the Inno Setup `[Code]` Pascal script, read the previous install path from the registry (stored under `AppId`)
2. Pre-fill the directory page with the new default path (`{userprofile}\<NewName>`)
3. The user can accept the new default or choose any path they prefer
4. Before installing, if the old path differs from the chosen new path: copy everything (app files + user data) from old → new, install to new path, then delete the old folder after success
5. If the copy fails, abort and leave the old install untouched
6. If the delete fails after a successful copy, show a message telling the user they can safely delete the old folder manually — the new install is fully working

User data (`config.json`, `games.db`, `state.json`, `theme.json`, `playdate.log`, cover art) all live next to the exe and must be included in the copy. `CloseApplications=yes` should be set in `[Setup]` so the app is not running during migration.

## Running & Building

**Run in development:**
```bash
python main.py
```

**Run Flask only (no native window, browser at localhost:5000):**
```bash
python app.py
```

**Build Windows executable:**
```bash
pyinstaller playdate.spec
# Then use Inno Setup 6 with playdate.iss to create the installer
```

**Install from source (Linux/macOS):**
```bash
python install.py   # GUI wizard
# or
chmod +x install.sh && ./install.sh
```

There are no automated tests or linting configs in this repo.

## Architecture

The app uses a hybrid architecture: Flask serves HTML/JSON over localhost, and pywebview creates a native OS window pointed at it. Waitress is the WSGI server (8 threads).

```
main.py → starts Flask (background thread) + pywebview window
         → starts filesystem watcher thread (utils.py)
         → starts playtime sync thread (scrapers.py)
```

**Key modules and responsibilities:**

| File | Role |
|------|------|
| `app.py` | Flask app factory, all HTTP routes and API endpoints |
| `config.py` | Persistent state: Steam credentials, filters, shelves, theme |
| `database.py` | SQLite CRUD, schema init, auto-migration of missing columns |
| `library.py` | Filter tree → SQL builder, grid rendering, bulk operations |
| `index.py` | Home page shelves — queries, deduplication, widget presets |
| `scrapers.py` | Steam API + HTML scraping for library/metadata import; BLAEO sync via Selenium (requires Chrome) |
| `utils.py` | Steam path detection, install status sync, filesystem watcher, local Steam file parsing |
| `images.py` | Cover art download: vertical capsule, horizontal header, and icon — each with Steam asset manifest → CDN → SteamGridDB fallback chain |
| `imports.py` | Data import tools: generic SQLite column mapping (`inspect_database`, `execute_import`) and Playnite backup import (`parse_playnite_dates`) |
| `install.py` / `uninstall.py` | Cross-platform GUI installer/uninstaller (tkinter) |
| `steam_date_import.user.js` | Tampermonkey userscript — scrapes activation dates from Steam help pages and sends them to PlayDate |

**Frontend:** Vanilla JS + CSS3 in `static/`, Jinja2 templates in `templates/`. No build step, no framework.

## Data Persistence

All user data lives next to the executable (or project root when running from source):

| File | Contents |
|------|----------|
| `games.db` | SQLite — `games` and `blacklist` tables |
| `config.json` | Multi-account config: `active_account` (steam_id key), `sgdb_key`, `accounts` dict (`steam_id → {steam_id, api_key, label}`). Use `get_active_account()` from `config.py` to get the active account's API key. |
| `state.json` | Active filters, shelf layout, sort order, saved filters, artwork orientation, card height |
| `theme.json` | CSS variable overrides (only non-default keys stored) |
| `playdate.log` | Application logs (RotatingFileHandler, 1MB cap, no backup copies) |
| `static/img/library/vertical/{appid}.jpg` | Cached vertical capsule art |
| `static/img/library/horizontal/{appid}.jpg` | Cached horizontal header art |
| `static/img/library/icons/{appid}.jpg` | Cached game icons |

`database.py` auto-adds missing columns on startup — no manual migrations needed.

## PyInstaller Path Handling (Critical)

All path resolution must check `sys.frozen` to distinguish running as script vs. frozen exe:

- **Bundle assets** (templates, static): `sys._MEIPASS` when frozen
- **User data** (config.json, games.db, etc.): `os.path.dirname(sys.executable)` when frozen, `__file__` dir otherwise

User data intentionally lives *next to* the .exe (not inside the bundle) so it survives upgrades. `config.py` sets `BASE_DIR` correctly; always use `BASE_DIR` for data files. Never use bare `__file__` for runtime paths.

## Filter System

Filters are a recursive JSON tree of AND/OR groups with conditions. They get compiled to SQL `WHERE` clauses by `library.build_tree_sql()`.

- **Node types**: `'condition'` (column op value), `'group'` (AND/OR container), `'custom_expr'` (raw SQL)
- **Comma-separated fields** (tags, groups, genres, categories): use `',' || column || ',' LIKE ?` wrapping to prevent partial matches
- **Date operators**: `STRFTIME_MONTH`, `STRFTIME_DAY`, `STRFTIME_YEAR` compile to `strftime('%m'/'%d'/'%Y', col) = ?`; value is zero-padded for month/day
- **SQL safety:** All user-supplied SQL passes through `is_safe_sql()` in `library.py`, which uses column/keyword/function whitelists and rejects all DML/DDL. Whitelisted columns include `appid`; whitelisted functions include `strftime`, `cast`; whitelisted keywords include `as`, `text`, `integer`, `real`, `blob`, `numeric`. Parameterized queries are used everywhere else.
- **PAGYWOSG filters** are saved as proper tree structures (not raw `custom_sql`) via `pagBuildTree()` in `modal_tools.html`, so they are editable in the filter builder. When `populateModalFromTree` loads a tree without `custom_sql`, it explicitly clears the custom SQL textbox to prevent stale SQL from bleeding into the applied filter.
- **Preserving custom filter keys:** `modal_filters.html` stores the original saved tree in `_loadedSavedTree` when a saved filter is loaded. `applyFilters()` copies `pagywosg`, `pagywosg_event`, and `pagywosg_verified` from `_loadedSavedTree` onto the freshly built tree before sending to the server, preventing those keys from being stripped by the UI rebuild.

## Key Patterns

### Threading & Cancellation
Long-running operations (library import, BLAEO sync) run in daemon threads with `threading.Event` for cancellation (`_populate_cancel` in `app.py`). Progress is tracked in a shared dict (`_populate_state`) polled by the frontend via `/api/populate-status` every second.

### Scrapers
`scrapers.py` pulls from multiple Steam endpoints per game: `GetOwnedGames` (playtime), Store API (metadata), `appreviews` (review stats), BeautifulSoup tag scraping (birthtime cookie bypasses age gate), and `GetPlayerAchievements`. There is a **0.5s delay** between games in the populate loop.

**Startup playtime sync:** `sync_recent_playtime()` runs in a background thread on launch. It reads `localconfig.vdf` directly (no API key needed) and updates `playtime_forever` and `last_played` in the DB for all games that exist in the library. For games where `playtime_forever` changed, it also fetches achievements via `fetch_cheevo_data()` (skipped if no API key) and updates `completion_status`: `'Never Played'` → `'Unfinished'` if playtime > 0; any status → `'Completed'` if 100% achievements unlocked. `'Beaten'` is never downgraded; `"Won't Play"` is only changed if 100% achievements.

**Rate limiting:** Each fetch function raises `RateLimitedError` on HTTP 429. The populate loop catches it, pauses 15 seconds, and retries the current game once. If the retry is also rate limited, populate aborts immediately and surfaces an error to the user. `RateLimitedError` is defined in `scrapers.py`.

**API key is optional.** Without one, `add_new()` reads the game list from local Steam files instead of `GetOwnedGames`: `fetch_local_library()` parses `localconfig.vdf` for played games + playtime, `get_acf_names()` reads ACF manifests for installed game names, and `parse_appinfo()` reads the binary `appinfo.vdf` cache for names and types. Achievements (`GetPlayerAchievements`) are skipped without a key. The Store API, reviews API, and tag scraping work without a key.

**`parse_appinfo()`** in `utils.py` parses Steam's binary `appcache/appinfo.vdf` (v29 format, magic `0x07564429`). It reads the string pool key table from the end of the file, then iterates app records to extract `name` and `type` from each app's `common` section. Returns `{appid: {'name': str, 'type': str}}`. Used for type pre-filtering (skipping non-games before any network calls) and name lookup. The `vdf` package (text VDF only) is used for `localconfig.vdf`; `appinfo.vdf` is parsed with custom binary struct code.

**BLAEO sync:** `scrape_blaeo_games()` uses Selenium (headless Chrome) to load the user's BLAEO games page, scroll to load all entries, then parse with BeautifulSoup. Per row it extracts: completion status (from `tr` class e.g. `game-never-played`), group tags (`a.list-tag`), and achievement counts (`td.achievements` → second `<span>` text `(X of Y)`). `data-value='-2'` on the achievements cell means the game has no Steam achievements — those are skipped. Updates `completion_status`, `groups`, `unlocked_achievements`, and `total_achievements` in the DB; games not in the local DB are logged and skipped.

**Review confidence weighting:** continuous confidence-interval formula: `weighted = round((p - (p - 0.5) × 2^(-log₁₀(total + 1))) × 100)` where `p = percent / 100`. Low review counts are pulled toward 50 (neutral); at ~10 reviews roughly half the gap is closed; at ~1000 reviews the score is nearly raw. Stored as `weighted_percentage`.

### Cover Art Pipeline
`images.py` handles three image types separately — vertical capsule, horizontal header, and icon. For each, `_get_steam_assets(appid)` fetches the full asset manifest from `IStoreBrowseService/GetItems`, which returns content-hash URLs for newer games. During populate, assets are fetched once and passed to all three download functions to avoid redundant API calls.

- **Vertical**: `library_capsule_2x` → `library_capsule` (manifest) → `library_600x900_2x.jpg` / `library_600x900.jpg` (CDN) → SteamGridDB grid (600x900 or 1200x1800)
- **Horizontal**: `header_image` / `main_capsule` (manifest) → `header.jpg` (CDN) → SteamGridDB wide grid (460x215 or 920x430)
- **Icon**: SteamGridDB icon → Steam `{hash}_2x.jpg` / `{hash}.jpg`

All saved as JPEG 95 quality; RGBA/PNG/WEBP converted to RGB first. Once cached locally, images are not re-fetched unless manually deleted.

### Graceful Degradation
No API key → reads library from local Steam files (`localconfig.vdf`, ACF manifests, `appinfo.vdf`). No SteamGridDB key → Steam covers; edit modal shows a "Browse SGDB ↗" link to the game's SGDB page so users can paste a direct image URL manually. Missing watchdog → continues without filesystem watcher. All external calls have try/except returning None/empty on failure.

### Filesystem Watcher
`utils.py` watches the steamapps folder for `appmanifest_*.acf` changes. On trigger, `sync_local_install_status()` resets all `installed` flags to 0 then bulk-sets found appids to 1. Proton, SteamLinuxRuntime, and Steamworks Shared entries are filtered out by reading .acf content.

### Steam Help Page Date Import

`steam_date_import.user.js` is a Tampermonkey userscript that runs on `help.steampowered.com/*` pages. It only activates when the URL contains `?ref=playdate`. It scrapes the earliest activation date from `.LineItemRow` spans (or `.account_details` fallback) using `DOMParser` on fetched HTML. All PlayDate API calls use `GM_xmlhttpRequest` (bypasses Steam's CSP, which blocks `fetch()` to localhost); same-origin Steam Help page fetches use regular `fetch()`.

**Single-game mode** (edit modal ↗ link): parses date from the current page DOM → POSTs to `POST /api/pending-date` → stored in `_pending_dates` dict → edit modal polls `GET /api/pending-date/<appid>` every 250ms for up to 3 seconds after the link is clicked → on receipt, populates the Date Added field with an accent highlight. After sending, userscript polls `GET /api/pending-date/<appid>/peek` (non-destructive) until the modal consumes the date, then closes the tab.

**Bulk mode** (`?bulk=1`, triggered from the bulk edit modal): stays on the trigger page and shows a full-screen progress overlay. Pings `POST /api/bulk-date-import/ping`, reads the queue from `GET /api/bulk-date-import/status`, then loops: `fetch()`es each game's HelpWithGame page, parses the date, POSTs to `POST /api/bulk-date-import/submit` (or `/skip`), gets `next_appid` from response, 600ms delay between games. Frontend polls `/api/bulk-date-import/status` every second to update the progress bar and per-game results log. `_bulk_date_state` tracks queue, current game, done/failed counts, active flag, and a `results` list (newest first, capped at 50) exposed by the status endpoint.

**pywebview `window.open()` does not open the system browser.** Use a programmatic `<a target="_blank">` click instead: create an `<a>` element, set `href` and `target='_blank'`, append to body, `.click()`, then remove. This matches how pywebview handles real link clicks.

### Playnite Import
`imports.py` → `parse_playnite_dates(zip_path)` extracts `date_added` values from a Playnite backup ZIP. Playnite stores its library in a LiteDB binary file (`library/games.db` inside the ZIP) — not SQLite. The parser reads the raw binary and uses proximity matching (±8KB) between `GameId` (BSON string, `\x02GameId\x00`) and `Added` (BSON datetime, `\x09Added\x00`) fields to pair them. This is necessary because LiteDB documents span non-contiguous 8KB pages, so full document parsing isn't possible without a LiteDB reader. Returns `{appid_int: 'YYYY-MM-DD'}`.

The import is triggered via the native file dialog (`pywebview.api.pick_open_path`) — not a file upload — because Playnite backups include all artwork and can be several GB. The route `/api/import/playnite-dates` receives the local file path and reads it directly. Currently only imports `date_added`; intended to be extended to other fields (completion status, playtime, etc.) in the future.

### Pick 6 Scoring
Six weighted signals combined in `app.py`: tag cosine similarity (against a playtime-weighted taste profile built from beaten games), review score, staleness (days since last played, capped at 730), completion bias, playtime (capped at 3000 min), and release recency (capped at 10 years). If no beaten games, profile falls back to top 50 most-played. Selection uses weighted random sampling, not sorted top-N.

## Home Page Shelves

Shelves are defined in `state.json` and rendered by `index.py`. Key fields per shelf:
- `filter_key`: points to a builtin filter or saved filter name
- `sort_col`: can be `'RANDOM()'` for shuffle shelves
- `dedup` + `dedup_priority`: shelves with lower priority numbers are processed first; their appids are excluded from later shelves
- `split_group`: shelves sharing the same group key render side-by-side in a flex row

**Edit mode cancel/restore:** on entering edit mode (via hamburger "Edit Home Layout" or E key), `_initEditBackup()` saves `_shelves` to `sessionStorage` under `editModeBackup` (only once — not on `saveAndReload` reloads, which persist to state.json and reload to `/?edit=1`). `exitEditMode()` (Cancel) restores the backup via POST to `/api/shelves` before navigating to `/`. `saveLayout()` and `resetLayout()` call `_clearEditBackup()` so an intentional save doesn't restore the old state.

### Library Virtual Grid
`library.html` uses an IntersectionObserver to lazy-load card content. Key details:
- Cards start as empty placeholders with a shimmer animation (`data-populated` absent)
- `CARD_HTML_CACHE` (Map keyed by appid) stores rendered card HTML to avoid re-generating on scroll-back
- Images use `data-src` (not `src`) and `decoding="async"`; loaded via `scheduleImgLoad()` with a 200ms delay after scroll (0ms on initial page load) to keep scrolling smooth
- `rootMargin: '1200px'` pre-loads cards well before they enter the viewport
- `_initialLoad` flag is true until first scroll event; on initial load images are applied immediately
- When `_patchGameCard` updates a card after an edit, it evicts the card from `CARD_HTML_CACHE` so the next repopulation picks up fresh data
- `.game-grid` has `contain: layout style paint` for paint performance

## Frontend JS

**`static/js/input.js`** (~1400 lines, IIFE) handles all gamepad and keyboard navigation:
- Zone-based state machine: `'nav'` (navbar), `'content'` (page grid), `'modal'`, `'ctx-menu'`
- 2D grid navigation per zone; gamepad buttons mapped to standard XB layout (A/B/X/Y, bumpers, D-pad)
- Repeat timing: 400ms initial delay, 150ms repeat; stick dead zone: 0.35
- Modal buttons must have `data-modal-row` attribute for grid-based row grouping
- Home page split-row shelves require X-proximity matching when navigating between sides

**`static/js/playdate.js`** — shared utilities: SQL syntax highlighter overlay (`sqlHighlightInit()`), state update helper (`sendStateUpdate(payload, reload=true)`), fire-and-forget preference save (`savePreference(payload)` — uses `fetch` with `keepalive:true`, no page reload), 8-second auto-hide error banners, and `initCustomSelect(nativeSelect)` — the custom dropdown widget (see below).

**Custom dropdowns — `initCustomSelect()`:** All `<select>` elements must be replaced with custom div-based dropdowns using `initCustomSelect()`. Native selects create OS-level popups that stay visible when the pywebview window loses focus. `initCustomSelect()` reads the native select, replaces it in the DOM with a `.custom-select` div, and exposes `.value`, `.selectedIndex`, `.options`, `._setOptions(html)`, `._addOption()`, `._clearOptions()`, `._getOption()`, and fires `change` events. If the native select had a `name` attribute, a hidden `<input>` is automatically inserted so `FormData` still works. Panels use `position:fixed` with coordinates from `getBoundingClientRect()` to escape `overflow:hidden` ancestors. Never add a new native `<select>` without immediately passing it to `initCustomSelect()`.

## Database Schema Notes

- `completion_status` values: `'Never Played'`, `'Unfinished'`, `'Beaten'`, `'Completed'`, `"Won't Play"`
- Comma-separated string columns: `tags`, `groups`, `developers`, `publishers` — no spaces after commas
- Dates stored as `'YYYY-MM-DD'` strings, not Unix timestamps
- `installed`: 0/1 integer
- `vertical_art_source`: `'capsule_2x'`, `'capsule'`, `'sgdb_grid'`, `'custom'`, `'missing'`
- `horizontal_art_source`: `'header'`, `'sgdb_grid_wide'`, `'custom'`, `'missing'`
- `icon_source`: `'sgdb_icon'`, `'steam'`, `'custom'`, `'missing'`
- `blacklist` table prevents repopulation of removed games
