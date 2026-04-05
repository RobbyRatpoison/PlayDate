# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Populate Speed Overhaul — Notes

- Populate runs three concurrent worker pools: 5 art, 1 meta, 2 cheevo
- Meta is 1 worker at 1.5s fixed delay — appdetails hard limit is 200 req/5min (count-based rolling window); 2 workers was the root cause of 429s
- `_fetched` columns (`art_fetched`, `meta_fetched`, `cheevos_fetched`) track per-phase completion; workers skip already-fetched games
- Placeholder cards batch-inserted immediately; per-card live updates as each phase completes; viewport-visible cards prioritized via `/api/populate-priority`
- BLAEO pre-scrape runs concurrently with art/meta after placeholder insert; cheevo workers start after it finishes
- `RateLimitedError` is re-raised in all fetch functions so `_PoolBackoff` triggers correctly

## Pending (Next Release — Not Yet Committed)

- **Renamed `playdate_date_import.user.js` → `steam_date_import.user.js`** — updated README.md and CLAUDE.md references; script version bumped to 1.9
- **Steam account mismatch check in userscript** — reads `HelpWizard.m_steamid` from the Steam help page, fetches new `GET /api/active-steam-id` endpoint, aborts with a banner if the logged-in Steam account doesn't match the active PlayDate account
- **Tampermonkey script detection for bulk date import** — userscript POSTs to new `POST /api/bulk-date-import/ping` on load; frontend auto-cancels with an error message after 5 seconds if no ping received; `script_connected` flag added to `_bulk_date_state` and exposed in `/api/bulk-date-import/status`
- **Bulk edit modal UI** — completion status column now shows a custom dropdown (5 status options) instead of a plain text input; tag/group/genre/category columns now show a pill input with suggestions; `LIST_COLUMNS` extended to include `genres` and `categories`

## To-Do

### Known Bugs
_(none)_

### Short Term
- Library UI polish — bulk edit improvements (an "all games" option, UI lockout during scraping), group-by functionality, reorder dropdown lists
- Bulk rescrape optimization — port populate's concurrent worker pools, `RateLimitedError` handling/backoff, and cancellation support to the bulk rescrape route (currently sequential, blocking, no rate limit recovery)
- Initial config UX — label the Steam API key as "recommended" instead of "optional", and add a brief note explaining what it enables (achievement tracking, more accurate library import via `GetOwnedGames`)

### Long Term
- Non-Steam library support (Epic, GOG, Ubisoft Connect, EA App, emulation)
- Plugin system

### Potential / Under Consideration
- Gamepad support improvements — home page editor buttons, bulk edit modal navigation, text input focus, disable RB/LB while in modals
- HLTB integration (data reliability concerns)
- Extend Playnite import to also import completion status
- Refactor app.py into Flask blueprints by area (library, scraping, config, import tools)

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

`steam_date_import.user.js` is a Tampermonkey MV2 userscript that runs on `help.steampowered.com/*/HelpWithGame` pages. It only activates when the URL contains `?ref=playdate` (set by PlayDate's ↗ link in the edit modal). It scrapes the earliest activation date from `.LineItemRow` spans (or `.account_details` fallback), then POSTs it to PlayDate via `GM_xmlhttpRequest`.

**Single-game mode** (edit modal ↗ link): POSTs to `POST /api/pending-date` → stored in `_pending_dates` dict → edit modal polls `GET /api/pending-date/<appid>` every 250ms for up to 3 seconds after the link is clicked → on receipt, populates the Date Added field with an accent highlight. After sending, userscript polls `GET /api/pending-date/<appid>/peek` (non-destructive) until the modal consumes the date, then closes the tab.

**Bulk mode** (`?bulk=1`, triggered from the bulk edit modal): POSTs to `POST /api/bulk-date-import/submit` (or `/skip` if no date found after 20 attempts) → backend saves directly to DB and returns `next_appid` → userscript navigates the same tab to the next game's URL (500ms delay between games). Frontend polls `GET /api/bulk-date-import/status` every second to update the progress bar. `_bulk_date_state` is a module-level dict tracking the queue, current game, done/failed counts, and active flag.

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
