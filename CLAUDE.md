# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

PlayDate is a local Steam library manager. It runs as a Flask web server wrapped in a native OS window via pywebview (no Electron). Users browse their Steam library, apply filters, track completion, and use a "Pick 6" feature to discover what to play next.

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
| `utils.py` | Steam path detection, install status sync, filesystem watcher |
| `images.py` | Cover art download: vertical capsule, horizontal header, and icon — each with Steam asset manifest → CDN → SteamGridDB fallback chain |
| `imports.py` | Old-database migration tool |
| `install.py` / `uninstall.py` | Cross-platform GUI installer/uninstaller (tkinter) |

**Frontend:** Vanilla JS + CSS3 in `static/`, Jinja2 templates in `templates/`. No build step, no framework.

## Data Persistence

All user data lives next to the executable (or project root when running from source):

| File | Contents |
|------|----------|
| `games.db` | SQLite — `games` and `blacklist` tables |
| `config.json` | Steam API key + SteamID |
| `state.json` | Active filters, shelf layout, sort order, saved filters, artwork orientation, card height |
| `theme.json` | CSS variable overrides (only non-default keys stored) |
| `playdate.log` | Application logs (RotatingFileHandler, 1MB cap) |
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
- **Comma-separated fields** (tags, groups, developers): use `',' || column || ',' LIKE ?` wrapping to prevent partial matches
- **SQL safety:** All user-supplied SQL passes through `is_safe_sql()` in `library.py`, which uses column/keyword/function whitelists and rejects all DML/DDL. Parameterized queries are used everywhere else.

## Key Patterns

### Threading & Cancellation
Long-running operations (library import, BLAEO sync) run in daemon threads with `threading.Event` for cancellation (`_populate_cancel` in `app.py`). Progress is tracked in a shared dict (`_populate_state`) polled by the frontend via `/api/populate-status` every second.

### Scrapers
`scrapers.py` pulls from multiple Steam endpoints per game: `GetOwnedGames` (playtime), Store API (metadata), `appreviews` (review stats), BeautifulSoup tag scraping (birthtime cookie bypasses age gate), and `GetPlayerAchievements`. The **1.2s delay** between API calls is mandatory — don't remove it.

**Review confidence weighting:** raw review percentage is scaled by total review count — <10 reviews gets 25% weight, 10-99 gets 50–100%, 100+ gets full weight. Stored as `weighted_percentage`.

### Cover Art Pipeline
`images.py` handles three image types separately — vertical capsule, horizontal header, and icon. For each, `_get_steam_assets(appid)` fetches the full asset manifest from `IStoreBrowseService/GetItems`, which returns content-hash URLs for newer games. During populate, assets are fetched once and passed to all three download functions to avoid redundant API calls.

- **Vertical**: `library_capsule_2x` → `library_capsule` (manifest) → `library_600x900_2x.jpg` / `library_600x900.jpg` (CDN) → SteamGridDB grid (600x900 or 1200x1800)
- **Horizontal**: `header_image` / `main_capsule` (manifest) → `header.jpg` (CDN) → SteamGridDB wide grid (460x215 or 920x430)
- **Icon**: SteamGridDB icon → Steam `{hash}_2x.jpg` / `{hash}.jpg`

All saved as JPEG 95 quality; RGBA/PNG/WEBP converted to RGB first. Once cached locally, images are not re-fetched unless manually deleted.

### Graceful Degradation
No API key → public profile HTML scraper. No SteamGridDB key → Steam covers. Missing watchdog → continues without filesystem watcher. All external calls have try/except returning None/empty on failure.

### Filesystem Watcher
`utils.py` watches the steamapps folder for `appmanifest_*.acf` changes. On trigger, `sync_local_install_status()` resets all `installed` flags to 0 then bulk-sets found appids to 1. Proton, SteamLinuxRuntime, and Steamworks Shared entries are filtered out by reading .acf content.

### Pick 6 Scoring
Six weighted signals combined in `app.py`: tag cosine similarity (against a playtime-weighted taste profile built from beaten games), review score, staleness (days since last played, capped at 730), completion bias, playtime (capped at 3000 min), and release recency (capped at 10 years). If no beaten games, profile falls back to top 50 most-played. Selection uses weighted random sampling, not sorted top-N.

## Home Page Shelves

Shelves are defined in `state.json` and rendered by `index.py`. Key fields per shelf:
- `filter_key`: points to a builtin filter or saved filter name
- `sort_col`: can be `'RANDOM()'` for shuffle shelves
- `dedup` + `dedup_priority`: shelves with lower priority numbers are processed first; their appids are excluded from later shelves
- `split_group`: shelves sharing the same group key render side-by-side in a flex row

## Frontend JS

**`static/js/input.js`** (~1400 lines, IIFE) handles all gamepad and keyboard navigation:
- Zone-based state machine: `'nav'` (navbar), `'content'` (page grid), `'modal'`, `'ctx-menu'`
- 2D grid navigation per zone; gamepad buttons mapped to standard XB layout (A/B/X/Y, bumpers, D-pad)
- Repeat timing: 400ms initial delay, 150ms repeat; stick dead zone: 0.35
- Modal buttons must have `data-modal-row` attribute for grid-based row grouping
- Home page split-row shelves require X-proximity matching when navigating between sides

**`static/js/playdate.js`** — shared utilities: SQL syntax highlighter overlay (`sqlHighlightInit()`), state update helper (`sendStateUpdate(payload, reload=true)`), fire-and-forget preference save (`savePreference(payload)` — uses `fetch` with `keepalive:true`, no page reload), 8-second auto-hide error banners.

## Database Schema Notes

- `completion_status` values: `'Never Played'`, `'Unfinished'`, `'Beaten'`, `'Completed'`, `"Won't Play"`
- Comma-separated string columns: `tags`, `groups`, `developers`, `publishers` — no spaces after commas
- Dates stored as `'YYYY-MM-DD'` strings, not Unix timestamps
- `installed`: 0/1 integer
- `vertical_art_source`: `'capsule_2x'`, `'capsule'`, `'sgdb_grid'`, `'custom'`, `'missing'`
- `horizontal_art_source`: `'header'`, `'sgdb_grid_wide'`, `'custom'`, `'missing'`
- `icon_source`: `'sgdb_icon'`, `'steam'`, `'custom'`, `'missing'`
- `blacklist` table prevents repopulation of removed games
