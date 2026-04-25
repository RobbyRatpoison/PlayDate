# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

PlayDate is a local game library manager. It runs as a Flask web server wrapped in a native OS window via pywebview (no Electron). Users browse their Steam and GOG libraries, apply filters, track completion, and use a "Pick 6" feature to discover what to play next. Non-Steam games use negative integer appids; GOG integration includes OAuth2 auth, library sync, metadata/achievement scraping, content-system v2 install/download, and Proton-based launch.

## Running & Building

```bash
python main.py              # development (Flask + pywebview window)
python app.py               # Flask only, browser at localhost:5000
pyinstaller playdate.spec   # Windows exe; then Inno Setup 6 for installer
python install.py           # Linux/macOS GUI installer
```

No automated tests or linting configs.

## Architecture

Flask + pywebview hybrid. Waitress WSGI (8 threads). `main.py` starts Flask in a background thread, opens the pywebview window, then starts filesystem watcher and playtime sync threads.

| File | Role |
|------|------|
| `app.py` | Flask routes and API endpoints |
| `config.py` | Persistent state: credentials, filters, shelves, theme |
| `database.py` | SQLite CRUD, schema init, auto-migration |
| `library.py` | Filter tree → SQL, grid rendering, bulk ops |
| `index.py` | Home page shelves — queries, deduplication, presets |
| `scrapers.py` | Steam API + HTML scraping; BLAEO sync (Selenium/Chrome) |
| `utils.py` | Steam path detection, install sync, filesystem watcher, VDF parsing |
| `images.py` | Cover art: Steam manifest → CDN → SteamGridDB fallback chain |
| `imports.py` | Playnite backup import, generic SQLite column mapping |
| `gog.py` | GOG OAuth2, library sync, metadata/achievements, install/launch |
| `runners/proton.py` | GE-Proton/official Proton detection, `proton run` launch |
| `uninstall.py` | Standalone tkinter GUI uninstaller (no pip deps beyond stdlib) |
| `steam_date_import.user.js` | Tampermonkey — scrapes activation dates from Steam Help + GOG orders |

**Frontend:** Vanilla JS + CSS3, Jinja2 templates. No build step, no framework.

## Data Persistence

All user data lives next to the exe (or project root when running from source). Always use `BASE_DIR` from `config.py` for data paths.

| File | Contents |
|------|----------|
| `games.db` | SQLite — `games` and `blacklist` tables |
| `config.json` | Accounts (`active_account`, `sgdb_key`, `accounts` dict), GOG tokens under `"gog"` key. Use `get_active_account()` for the active API key. |
| `state.json` | Active filters, shelf layout, sort order, saved filters, art orientation, `hide_duplicates`, `pagywosg_sg_group` |
| `theme.json` | CSS variable overrides (non-default keys only) |
| `playdate.log` | RotatingFileHandler, 1MB cap, no backups |
| `static/img/library/{vertical,horizontal,icons}/{appid}.jpg` | Cached art |

`database.py` auto-adds missing columns on startup — no manual migrations needed.

## Database Schema Notes

- `completion_status`: `'Never Played'`, `'Unfinished'`, `'Beaten'`, `'Completed'`, `"Won't Play"`
- Comma-separated columns (`tags`, `groups`, `developers`, `publishers`): no spaces after commas
- Dates as Unix timestamps (INTEGER): `date_added`, `last_played`, `release_date`
- `platform`: `'steam'`, `'gog'`, `'epic_games'`, `'ea_app'`, `'ubisoft'`
- `duplicate_of`: TEXT appid of canonical version; `NOT NULL` = excluded from library by default
- **GOG appids are negative integers.** Flask uses `SignedIntConverter` (`r'-?\d+'`) for routes; `appid_list` validation allows zero/negative.
- `blacklist` table prevents repopulation of removed games

## PyInstaller Path Handling (Critical)

- **Bundle assets** (templates, static): `sys._MEIPASS` when frozen
- **User data**: `os.path.dirname(sys.executable)` when frozen, `__file__` dir otherwise

User data lives *next to* the .exe so it survives upgrades. Never use bare `__file__` for runtime paths — always use `BASE_DIR`.

## Filter System

Recursive JSON tree compiled to SQL by `library.build_tree_sql()`.

- **Node types**: `'condition'`, `'group'` (AND/OR), `'custom_expr'` (raw SQL)
- **Comma-separated fields** (tags, groups, genres, categories): use `',' || column || ',' LIKE ?` to prevent partial matches
- **Date operators**: `STRFTIME_MONTH/DAY/YEAR` compile to `strftime(...)` with zero-padded values
- **SQL safety:** `is_safe_sql()` in `library.py` uses column/keyword/function whitelists, rejects all DML/DDL. Parameterized queries everywhere else.
- **PAGYWOSG filters** save as full tree structures (not raw SQL) so they're editable. `populateModalFromTree` explicitly clears the custom SQL box when no `custom_sql` key is present, to prevent stale SQL bleed.
- **Preserving PAGYWOSG keys:** `applyFilters()` copies `pagywosg`, `pagywosg_event`, `pagywosg_verified` from `_loadedSavedTree` onto the rebuilt tree.

## Key Patterns

### Threading & Cancellation
Long-running operations run in daemon threads with `threading.Event` (`_populate_cancel`). Progress tracked in `_populate_state`, polled via `/api/populate-status` every second.

### Scrapers

**Rate limiting:** fetch functions raise `RateLimitedError` on 429 → populate pauses 15s and retries once → if retry also 429, populate aborts. `RateLimitedError` is defined in `scrapers.py`.

**API key optional:** without one, `add_new()` reads from local Steam files (`localconfig.vdf` for playtime, ACF manifests for names, `appinfo.vdf` for names/types). Achievements skipped without key; Store API, reviews, and tag scraping work without one.

**`parse_appinfo()`** in `utils.py` parses Steam's binary `appinfo.vdf` (v29, magic `0x07564429`) with custom struct code — the `vdf` package only handles text VDF.

**Startup playtime sync:** reads `localconfig.vdf`, updates playtime + last_played. For changed playtime, re-fetches achievements and updates `completion_status`: `'Never Played'` → `'Unfinished'` if playtime > 0; any → `'Completed'` if 100% achievements. `'Beaten'` is never downgraded; `"Won't Play"` only changes on 100%.

**BLAEO sync:** uses Selenium (headless Chrome). `data-value='-2'` on achievements cell means no Steam achievements — skip.

**Review confidence weighting:** `weighted = round((p - (p - 0.5) × 2^(-log₁₀(total + 1))) × 100)`. Pulls low-count scores toward 50 (neutral).

### Cover Art Pipeline
Three types: vertical capsule, horizontal header, icon. Steam asset manifest fetched once per game and passed to all three. Non-Steam: `_sgdb_search_game_id(name)` → SGDB game ID → query directly.

- **Vertical**: manifest → CDN `library_600x900` → SGDB grid
- **Horizontal**: manifest → CDN `header.jpg` → SGDB wide
- **Icon**: SGDB icon → Steam hash

All JPEG 95; RGBA/WEBP converted to RGB. Cached locally; not re-fetched unless deleted.

### Filesystem Watcher
On ACF change, resets all Steam `installed` flags to 0 then bulk-sets found appids to 1. Filters out Proton/SteamLinuxRuntime/Steamworks entries by reading ACF content.

### Steam/GOG Date Import (`steam_date_import.user.js`)

**Critical:** All PlayDate API calls must use `GM_xmlhttpRequest` — Steam's CSP blocks `fetch()` to localhost.

**`window.open()` does not open the system browser in pywebview.** Use a programmatic `<a target="_blank">` click: create element, set href + target, append to body, `.click()`, remove.

**GOG bulk mode:** pages 2-N must use the XHR JSON endpoint (`/account/settings/orders/data?page=N`) — the SSR `?page=N` URL returns page 1 HTML for all N.

**Single-game flow:** userscript POSTs date → `_pending_dates` dict → edit modal polls `GET /api/pending-date/<appid>` every 250ms for 3s. Userscript polls `/peek` (non-destructive) until consumed, then closes tab.

### Playnite Import
Playnite uses LiteDB (not SQLite). `parse_playnite_dates()` uses proximity matching (±8KB) between `\x02GameId\x00` and `\x09Added\x00` BSON markers — full document parsing isn't possible without a LiteDB reader since documents span non-contiguous 8KB pages. Import uses native file dialog (not upload) because backups can be several GB.

### Pick 6 Scoring
Six signals: tag cosine similarity (playtime-weighted taste profile from beaten games), review score, staleness (capped 730d), completion bias, playtime (capped 3000min), release recency (capped 10yr). Falls back to top-50-most-played if no beaten games. Weighted random sampling, not sorted top-N.

## Frontend JS

**Custom dropdowns:** Never add a native `<select>` without calling `initCustomSelect()` on it. Native selects create OS-level popups that stay visible when pywebview loses focus.

**`confirm()` returns a Promise.** In async DOM listeners, use `.then()` chains over `await` — pywebview's event dispatch doesn't wait for async handlers.

**`input.js`** — zone-based state machine (`nav`, `content`, `modal`, `ctx-menu`). Modal buttons need `data-modal-row`. Gamepad: XB layout, 400ms initial / 150ms repeat, 0.35 dead zone.

## Home Page Shelves

Shelf fields: `filter_key` (builtin or saved filter name), `sort_col` (`'RANDOM()'` for shuffle), `dedup` + `dedup_priority` (lower priority = processed first; appids excluded from later shelves), `split_group` (same key = side-by-side flex row).

**Edit mode cancel:** `_initEditBackup()` saves to `sessionStorage` once on entry (not on `saveAndReload` reloads). Cancel restores via POST before navigating away. Save/reset call `_clearEditBackup()`.

## Library Views

**Grid mode** (default): `library.html` uses IntersectionObserver (`rootMargin: '1200px'`) + `CARD_HTML_CACHE`. Images use `data-src` with 200ms delay after scroll (0ms on initial load). `_patchGameCard` evicts from cache so edits show fresh data.

**List mode**: split-pane layout (`#library-list-layout`) with `#list-pane` (scrollable rows, 20% width, resizable) and `#detail-pane` (game detail + inline edit form). Activated via the VIEW modal; stored as `artwork_orientation: 'list'` in `state.json`. On activation, `#game-grid` and `.library-header` are hidden, `body` and `.container` overflow is locked to `hidden`, and `_adjustListHeight()` sizes `#library-list-layout` to fill the remaining viewport. A `_listObserver` (IntersectionObserver) loads icons as rows scroll into view.

## HLTB Integration

Times stored in minutes. `hltb_fetched` states: `NULL`/`'0'` = never fetched; `'unconfirmed'` = matched below threshold (times NULL); `'no_match'` = no results; `YYYY-MM-DD` = confirmed. Startup catch-up only fetches `NULL`/`'0'` — does not retry `no_match` automatically.

## PAGYWOSG Filter Builder

The PAGYWOSG tool (`modal_tools.html`) builds structured filter trees for the monthly PAGYWOSG event on SteamGifts.

**Event ID formula:** event 83 = April 2026; `event_id = 83 + (year - 2026) * 12 + (month - 4)`

**Pool rules:** categories with both `(win)` and `(backlog)` suffix variants → "all" pool; no suffix → "wins" pool.

**Filter tree structure:** root AND with `platform = 'steam'` first, then OR of [all-pool branch, AND[steamgifts-won condition, wins-pool branch]], plus completion status exclusions and `appid IN (...)` for mod-verified games.

**icaio detection:** phrases matched exactly — `"icaio has made a GA for"` → giveaways list; both `"icaio"` + `"wishlist"` → wishlist. Exact matching is intentional to avoid false positives. These entries get `auto: true` (suppresses "mod verified" label).

**Supplement file** (`pagywosg_supplement.json`): top-level keys `icaio_giveaways`, `icaio_wishlist`, and numeric event IDs. Event entries keyed by category ID: `{pool, id_name, developers?, publishers?, appids?, verifiers?}` where `verifiers` is `{appid_str: username}`.

**Saved filter keys:** PAGYWOSG filters carry `pagywosg: true`, `pagywosg_event: {id, name}`, `pagywosg_verified: {appid: [{cat, pool, verifier?, auto?}]}`. These must be preserved when re-applying — `modal_filters.html` copies them from `_loadedSavedTree` onto the rebuilt tree. `openFilterModal()` also seeds `_loadedSavedTree` from the server tree when `pagywosg: true` and it isn't already set, so editing an active filter preserves these keys.

**SG wins group:** `_pagSgGroup` in `modal_tools.html` is `string` = chosen group, `null` = no SG wins, `undefined` = not yet loaded. Stored as `pagywosg_sg_group` in `state.json`. On init, if unset and no default, a warning prompts the user to configure.

**Quals panel:** shown in `modal_edit.html` when `_serverFilterTree.pagywosg` is true. Wins branch detected by presence of a `groups` condition in any AND group.

**Hover tooltip:** IIFE in `library.html`, activates only when `_serverFilterTree?.pagywosg` is true, uses event delegation on `#game-grid`.

## Release Workflow

Completed work goes in the **Pending** section of `TODO.md`. At release, distill it into user-facing notes for `RELEASE_NOTES.md`, then delete the section.

## To-Do

See [TODO.md](TODO.md).
