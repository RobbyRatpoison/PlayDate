# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

PlayDate is a local game library manager. It runs as a Flask web server wrapped in a native OS window via pywebview (no Electron). Users browse their Steam and GOG libraries, apply filters, track completion, and use a "Pick 6" feature to discover what to play next. Non-Steam games use negative integer appids. Non-Steam library sources (GOG, Epic, etc.) are optional plugins; GOG is the reference implementation and ships bundled.

## Running & Building

```bash
python main.py              # development (Flask + pywebview window)
python app.py               # Flask only, browser at localhost:5000
pyinstaller playdate.spec   # Windows exe; then Inno Setup 6 for installer
python install.py           # Linux/macOS GUI installer
```

**Tests:** `pytest tests/` (deps in `requirements-dev.txt`; CI runs them via `.github/workflows/tests.yml` on push/PR to main/dev). The suite covers pure logic only — filter tree → SQL (`build_tree_sql`, `is_safe_sql`), PAGYWOSG category classification (`classify_category`), binary `appinfo.vdf` parsing (`parse_appinfo`, via a synthetic file), review confidence weighting, `review_score_label`, and the PAGYWOSG event-id formula. No Flask routes, DB, or UI are exercised. When touching any of those functions, run the suite; when adding a `classify_category` branch or `OP_REGISTRY` op, add a test case.

**Lint:** `ruff check .` (config in `ruff.toml`, pyflakes rules only — unused imports/vars, undefined names, redefinitions; no style/formatting rules, since this codebase's dense one-liner style doesn't fit pycodestyle's opinions). Runs in CI alongside the test suite. A handful of pre-existing bugs ruff caught but that are out of scope to fix blindly are marked `# noqa: F821` with an explanatory comment (e.g. `plugins/gog/gog.py`'s `_fetch_all_products`/`p` — both silently caught by a surrounding `except Exception`, so the affected fields just never get set).

## Architecture

Flask + pywebview hybrid. Waitress WSGI (8 threads). `main.py` starts Flask in a background thread, opens the pywebview window, then starts filesystem watcher and playtime sync threads.

**Routes live as Flask Blueprints, one per domain module** — each `_bp` is a module-level `Blueprint(...)` defined and registered directly in that domain's own file (not nested in a factory function), following the pattern `config_bp`/`index_bp`/`library_bp` established first. `app.py` itself only holds the app factory (`create_app()`), blueprint registration, static file serving, the CORS/context-processor hooks, and the populate/scrape-new-games routes (kept here because `main.py` imports the shared `populate_cancel` event directly from `app`). When adding a new route, add it to the blueprint whose file already owns that domain's logic; only create a new blueprint module for a genuinely new domain.

| File | Role |
|------|------|
| `app.py` | App factory, blueprint registration, static file serving, populate/scrape-new-games routes |
| `config.py` | `config_bp` — persistent state: credentials, filters, shelves, theme, background image, account switching |
| `database.py` | SQLite CRUD, schema init, auto-migration, duplicate-game image cache (`get_dup_cache`/`invalidate_dup_cache`) |
| `library.py` | `library_bp` — filter tree → SQL, grid rendering, bulk ops/edit, saved filters, game CRUD, blacklist, bulk rescrape/art/protondb/hltb jobs |
| `index.py` | `index_bp` — home page shelves: queries, deduplication, presets, shuffle/refill |
| `pick.py` | `pick_bp` — Pick 6: `/pick` page and the six-signal scoring engine |
| `scrapers.py` | Steam API + HTML scraping; `blaeo_bp` — BLAEO sync (Selenium/Chrome) |
| `utils.py` | Steam path detection, install sync, filesystem watcher, VDF parsing, `validate_user_path()` |
| `images.py` | `images_bp` — cover art: Steam manifest → CDN → SteamGridDB fallback chain |
| `hltb.py` | `hltb_bp` — HowLongToBeat match/select/confirm routes (scraping itself lives in `scrapers.py`) |
| `date_import.py` | `date_import_bp` — pending-date polling + bulk date import queue for `steam_date_import.user.js` |
| `system.py` | `system_bp` — launch games, open paths in the OS file manager, process-running checks |
| `backup.py` | `backup_bp` — full backup/restore zip, CSV export |
| `updater.py` | `updater_bp` — GitHub release polling and self-update (installer/Flatpak/source zip) |
| `imports.py` | `imports_bp` — Playnite backup import, generic SQLite column mapping |
| `pagywosg.py` | `pagywosg_bp` — PAGYWOSG category classification (`classify_category`, `OP_REGISTRY`), per-user verified-appid tracking, Monthly in a Month sheet check |
| `pop_sync.py` | `pop_bp` — Play or Pay pick sync, evergreen saved filter, stale-cycle group cleanup |
| `plugins/` | Optional non-Steam integrations; `plugins_bp` — install/uninstall/update-check/launcher-status routes; see `PLUGINS.md` |
| `plugins/gog/` | GOG plugin — OAuth2, library sync, metadata/achievements, install/launch |
| `plugins/epic_games/` | Epic Games plugin — OAuth2, library sync, metadata, art, Wine/native launch |
| `runners/proton.py` | GE-Proton/official Proton detection, `proton run` launch |
| `runners/wine.py` | Shared Wine helpers for plugins: `find_wine_binary()`, `list_prefixes()`, `create_prefix()`, `run_in_prefix()`, `launch_protocol_url()` |
| `runners/launcher_installer.py` | Generic Wine-based launcher installer for plugins; reads `launcher.installer` from `plugin.json`; phases: creating_prefix → downloading → installing → verifying → done; saves launcher config on success |
| `uninstall.py` | Standalone tkinter GUI uninstaller (no pip deps beyond stdlib) |
| `steam_date_import.user.js` | Tampermonkey — scrapes activation dates from Steam Help + GOG orders |
| `tools/pagywosg_category_scan.py` | Dev-only CLI (not part of the shipped app), scans PAGYWOSG events for unautomated categories, `--triage` workflow |

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
- **Non-Steam platform columns:** `platform_id` = service-native catalog/item ID (e.g. Epic `catalogItemId`, GOG product ID); `platform_slug` = store URL slug (e.g. `epicgames.com/p/{slug}`); `platform_appname` = internal launch/install name where it differs from the slug (Epic only — `appName` used in protocol URLs and install dirs); `platform_ns` = catalog namespace (Epic only). For Epic, `platform_id` and `platform_appname` are both needed: `platform_id` is used for catalog API calls and dedup; `platform_appname` is used for launching and install detection. Epic's assets API can return multiple records with the same `catalogItemId` but different `appName`s (entitlement vs installable); the sync resolves the correct one via `releaseInfo[*].appId` where `platform` includes `'Windows'`.

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

**Rate limiting:** fetch functions raise `RateLimitedError` on 429, carrying `retry_after` (seconds) parsed from the response's `Retry-After` header when present (`_parse_retry_after()`). Populate and bulk-rescrape workers share a `_PoolBackoff` gate per pool (meta/cheevo/bulk_rescrape): the first 429 in a pool closes a shared gate and every worker waits together, preferring the server's `retry_after` over the fixed `BACKOFF_DELAYS` sequence (`[15, 60, 300, 3615]`) when given, capped at the largest configured delay; after all `BACKOFF_DELAYS` attempts are exhausted the pool aborts. `sync_store_release_dates`/`sync_store_names` (startup migrations) use a simpler pause-and-retry-once, also preferring `retry_after` when present. `/api/scrape_single/<appid>` (single-game "Sync Steam Data") catches `RateLimitedError` and returns a `429` with a clear message instead of crashing.

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

## Plugin System

Non-Steam library sources are optional plugins in `plugins/<id>/`. See `PLUGINS.md` for the full developer guide. Key points:

- **Auto-discovery:** any folder under `plugins/` with a `plugin.json` is loaded at startup via `plugins/__init__.py`.
- **`min_core_version` field in `plugin.json`** — optional; if set and newer than the running `config.__version__`, `load_all()` skips importing/registering the plugin (fails safe instead of crashing on a missing method/field a newer plugin version assumes). Recorded in `_incompatible_plugins`, exposed via `GET /api/plugins/incompatible`, and rendered in the Plugins modal with a "needs PlayDate X.Y.Z" badge; still uninstallable via the normal uninstall flow (falls back to the standard `plugins/<id>/` path since it was never registered).
- **Jinja2 globals:** `has_plugin(id)`, `plugin_fragments(slot)`, `platform_labels()`, `plugin_js_api()` — available in all templates.
- **`window._PLAT_LABELS`** — injected in `base.html`; maps platform key → display label. Use this instead of hardcoded dicts. Core provides `steam`, `epic_games`, `ea_app`, `ubisoft`; plugins add their own.
- **`window._PLUGIN_API`** — injected in `base.html`; maps platform key → `{uninstall_url, scrape_url, scrape_method, store_url, store_label, appid_label, sync_label}`. Core templates use this for per-platform behavior; no platform-specific branches in core code.
- **Management UI:** hamburger → Plugins; install via zip or GitHub URL, uninstall with optional game removal, restart-required notice.
- **GitHub install:** `POST /api/plugins/install-from-github` accepts `{url}` (any `github.com/owner/repo` form), fetches the latest release zip asset (falls back to zipball), and installs via the shared `_install_plugin_zip(raw_bytes)` helper.
- **Update checking:** `GET /api/plugins/check-updates` checks GitHub for each plugin whose `plugin.json` has `"source": "github:owner/repo"`; compares semver against installed `version`; 6-hour per-plugin cache in `_plugin_update_cache`. Fires automatically when the Plugins modal opens; shows a one-click update link on cards with newer releases.
- **`launch_game(appid)`** — plugin lifecycle method; core `/api/launch/<appid>` dispatches non-Steam platforms to `plugin.launch_game(appid)` by matching the `platform` column. Returns 501 if no plugin claims the platform. When a game needs to install before launching, return `{"status": "installing", "install_poller": "<js_fn_name>", "message": "…"}` — core calls `window[install_poller](appid)` if that function exists. Do not use platform-named flags like `gog_install`.
- **`rescrape(appid) -> dict | None`** — optional; called by `bulk_rescrape_games` for any non-Steam game whose platform has a plugin with this method. Must return a dict ready to pass to `update_game_data(**meta)` (including `meta_fetched`, `cheevos_fetched` if applicable), or `None` on failure. Replaces direct plugin imports in `scrapers.py`.
- **`fetch_description(appid, platform_id) -> str | None`** — optional; called by `/api/game-description/<appid>` for non-Steam platforms. Return a plain-text description string, or `None` if unavailable. Core falls back to the Steam store API when no plugin implements this.
- **`date_import_url` (class attribute, str)** — optional; declare this if the platform has an external orders/activation page that the Tampermonkey date-import script should open. Core collects these from all plugins whose games are in the selection and returns them as `date_import_urls: [{url, label}]` from the bulk date import start endpoint. The frontend opens each URL in a new tab generically.
- **`launcher` field in `plugin.json`** — declares whether a plugin needs a separate launcher process (`"launcher": {"required": true, "name": "...", "exe_name": "..."}` or `{"required": false}`). Core reads this to drive launcher config UI; no code changes needed in the plugin.
- **Launcher config:** `GET/POST /api/launcher-config/<platform_id>` stores `{wine_bin, prefix, mode}` under `config.json["launchers"]`. GET also returns `wine_bin_detected` from `runners.wine.find_wine_binary()`.
- **`launcher_status()`** — optional plugin method returning `{"available": bool, "detail": str}`. Called at startup (3s delay) for all plugins that implement it; result cached in `_launcher_status_cache`. `GET /api/plugins/launcher-status` returns the full cache; `POST /api/plugins/launcher-status/<platform_id>` re-runs on demand.
- **Launcher UI:** plugin cards in the Plugins modal show a green "Launcher ready" badge or amber warning + "Configure Launcher" button when `launcher.required` is true. The inline config panel auto-populates Wine binary from saved config or `find_wine_binary()`.
- **`manage_ui()` button actions:** `type: 'call'` invokes a JS function by name; `type: 'post'` POSTs to an endpoint; `type: 'open_url'` opens a URL in the system browser. The rendered `onclick` attribute is built with `JSON.stringify`, so it must be passed through `escHtml()` before insertion into HTML — this is handled by `_buildManageBlockHtml` in `modal_tools.html`. Do not bypass it.
- **Duplicate detection:** `auto_detect_duplicates(platform_priority=None)` lives in `database.py` and works across all platforms. The generic endpoint is `POST /api/detect-duplicates`. Plugins must not add their own per-platform duplicate detection routes.
- **Platform validation:** `hidden_platforms` and `platform_priority` entries are validated with the regex `^[a-z][a-z0-9_]*$` — no hardcoded allowlists. Any platform string matching this pattern is accepted (values come from the DB and plugin registrations, so injection is not a practical concern). `_plat_order` for sorting available platforms is derived from `platform_labels()` which merges core + plugin labels.
- **Steam is not a plugin.** It is the core.

## Frontend JS

**`playdate.js`** — loaded globally on every page. Shared utilities: `escHtml(s)` (HTML-escape for safe `innerHTML` use), `fmtHours(minutes)`, SQL syntax highlighter, `safeLocal`/`safeSession` (storage wrappers). Always use `escHtml()` instead of manual `replace()` chains when inserting user/API data into `innerHTML`.

**Custom dropdowns:** Never add a native `<select>` without calling `initCustomSelect()` on it. Native selects create OS-level popups that stay visible when pywebview loses focus.

**`confirm()` returns a Promise.** In async DOM listeners, use `.then()` chains over `await` — pywebview's event dispatch doesn't wait for async handlers.

**`localStorage` and `sessionStorage` are not available as globals in pywebview's WebKit2GTK context.** Always use `safeLocal` / `safeSession` from `playdate.js` instead. These fall back to in-memory objects when the native APIs are unavailable.

**`input.js`** — zone-based state machine (`nav`, `content`, `modal`, `ctx-menu`). Modal buttons need `data-modal-row`. Gamepad: XB layout, 400ms initial / 150ms repeat, 0.35 dead zone. `input[type=range][data-modal-row]` is gamepad-navigable: left/right adjusts by the slider's `step` attribute. For checkboxes, use `div[data-modal-row]` with an onclick toggle (`var cb=this.querySelector('input');cb.checked=!cb.checked;`) and `onclick="event.stopPropagation()"` on the inner checkbox. **Never use the HTML `disabled` attribute on buttons that need gamepad navigation** — `disabled` excludes them from `_modalGrid()`; use CSS `opacity` + a JS guard in the handler instead.

**File dialogs in pywebview:** `input[type=file].click()` is silently blocked when called from a gamepad RAF handler (non-user-gesture context). Use `window.pywebview.api.pick_open_path(filters)` instead, with a fallback to `.click()` for browser mode. After any native file dialog closes, WebKit2GTK fires a spurious click on the focused element, which reopens the dialog. Guard every file dialog function with `_fileDlgBusy` (a shared flag, 300ms `setTimeout` to clear) to absorb it.

## Home Page Shelves

Shelf fields: `filter_key` (builtin or saved filter name), `sort_col` (`'RANDOM()'` for shuffle), `dedup` + `dedup_priority` (lower priority = processed first; appids excluded from later shelves), `split_group` (same key = side-by-side flex row).

**Edit mode cancel:** `_initEditBackup()` saves to `sessionStorage` once on entry (not on `saveAndReload` reloads). Cancel restores via POST before navigating away. Save/reset call `_clearEditBackup()`.

## Library Views

**Grid mode** (default): `library.html` uses IntersectionObserver (`rootMargin: '1200px'`) + `CARD_HTML_CACHE`. Images use `data-src` with 200ms delay after scroll (0ms on initial load). `_patchGameCard` evicts from cache so edits show fresh data.

**List mode**: split-pane layout (`#library-list-layout`) with `#list-pane` (scrollable rows, 20% width, resizable) and `#detail-pane` (game detail + inline edit form). Activated via the VIEW modal; stored as `artwork_orientation: 'list'` in `state.json`. On activation, `#game-grid` and `.library-header` are hidden, `body` and `.container` overflow is locked to `hidden`, and `_adjustListHeight()` sizes `#library-list-layout` to fill the remaining viewport. A `_listObserver` (IntersectionObserver) loads icons as rows scroll into view.

## HLTB Integration

Times stored in minutes. `hltb_fetched` states: `NULL`/`'0'` = never fetched; `'unconfirmed'` = matched below threshold (times NULL); `'no_match'` = no results; `YYYY-MM-DD` = confirmed. Startup catch-up only fetches `NULL`/`'0'` — does not retry `no_match` automatically.

## PAGYWOSG Filter Builder

The PAGYWOSG tool (`modal_tools.html`) builds structured filter trees for the monthly PAGYWOSG event on SteamGifts. Categories are fetched live from `pagywosg.xyz`: there's no static catalog of category names.

**`pagywosg.py`** is the single source of truth for category classification and the operator vocabulary. `classify_category(base, base_appids, icaio_ga, icaio_wl, santa)` pattern-matches a live category name into a neutral op (`OP_REGISTRY` key: `month_is`, `contains`, `title_word`, `digit_count_gte`, `has_special_char`, `range_incl`, `nth_weekday`, `contains_all`, etc.) or falls through to the mod-verified appid list (`reason: 'verified_fallback'`/`'unhandled'` mark this as *not* automated; see the category scanner below). Each `OP_REGISTRY` entry carries: the SQL "kind" (dispatches `redundant_where_sql()`'s redundant-appid pre-check, and the JS `pagCondToTree`/`pagCondToSql`/`_pagCheckCond` in modal_tools.html/modal_edit.html), the saved-tree `tree_op` token, and the manual condition-builder dropdown label. `window._PAG_OPS` injects the whole registry into every page (same pattern as `window._PLAT_LABELS`/`_PLUGIN_API`, see Plugin System) so the frontend never hardcodes op behavior. Adding a category that reuses an existing op is one new regex branch in `classify_category()`; a genuinely new op needs an `OP_REGISTRY` entry plus all three SQL/JS consumers.

**Event ID formula:** event 83 = April 2026; `event_id = 83 + (year - 2026) * 12 + (month - 4)`

**Pool rules:** categories with both `(win)` and `(backlog)` suffix variants → "all" pool; no suffix → "wins" pool.

**Filter tree structure:** root AND with `platform = 'steam'` first, then OR of [all-pool branch, AND[steamgifts-won condition, wins-pool branch]], plus completion status exclusions and `appid IN (...)` for mod-verified games.

**icaio detection:** phrases matched exactly — `"icaio has made a GA for"` → giveaways list; both `"icaio"` + `"wishlist"` → wishlist. Exact matching is intentional to avoid false positives. These entries get `auto: true` (suppresses "mod verified" label).

**Supplement file** (`pagywosg_supplement.json`): top-level keys `icaio_giveaways` (list of `{appid, name}`) and `icaio_wishlist` (dict of `{appid_str: name}`).

**Personal categories & per-user verification:** every verified PAGYWOSG entry carries the verifying player's `sgProfileName` (`pagywosg.build_verified_by_cat()`). A category checked "personal" in the builder only includes appids verified for the current `sg_username` (config.json setting, set via the settings modal): `/api/pagywosg-auto`'s `appid_sources` carries both the full `appids` list and a `personal_appids` subset per label (computed server-side regardless of which categories are marked personal client-side; the client picks which to use). `pagywosg_personal_defaults.json` (repo-tracked, *not* gitignored, ships with releases unlike the other PAGYWOSG state files) holds `{event_id: [base_category_name, ...]}`: maintainer-curated categories that default to personal for every install. `pagAutoFill()` pre-checks these but they stay individually toggle-able. `/api/pagywosg-quals` (the live pre-save preview) has no per-user toggle state, so it applies the bundled default-personal list directly instead of a client-side checkbox.

**Saved filter keys:** PAGYWOSG filters carry `pagywosg: true`, `pagywosg_event: {id, name}`, `pagywosg_verified: {appid: [{cat, pool, verifiers?, auto?}]}` (`verifiers` is a list of SG usernames, since a category can be independently verified for multiple players, not a single name). These must be preserved when re-applying — `modal_filters.html` copies them from `_loadedSavedTree` onto the rebuilt tree. `openFilterModal()` also seeds `_loadedSavedTree` from the server tree when `pagywosg: true` and it isn't already set, so editing an active filter preserves these keys.

**SG wins group:** `_pagSgGroup` in `modal_tools.html` is `string` = chosen group, `null` = no SG wins, `undefined` = not yet loaded. Stored as `pagywosg_sg_group` in `state.json`. On init, if unset and no default, a warning prompts the user to configure.

**Quals panel:** shown in `modal_edit.html` when `_serverFilterTree.pagywosg` is true. Wins branch detected by presence of a `groups` condition in any AND group.

**Hover tooltip:** IIFE in `library.html`, activates only when `_serverFilterTree?.pagywosg` is true, uses event delegation on `#game-grid`.

**Category gap scanner** (`tools/pagywosg_category_scan.py`, dev-only: not imported by the app or packaged): `python tools/pagywosg_category_scan.py [--event N | --events A-B | --next] [--all] [--triage]` fetches live/historical events and buckets each category as automated vs not-automated (fell through to the verified-appid fallback). `--triage` walks the not-automated list interactively: `[n]` marks non-automatable (local, `pagywosg_scan_decisions.json`, gitignored), `[p]` marks always-personal (repo-tracked, writes `pagywosg_personal_defaults.json`, needs committing to actually ship), `[s]` skips.

## Release Workflow

At release, distill completed work into user-facing notes for `RELEASE_NOTES.md`.
