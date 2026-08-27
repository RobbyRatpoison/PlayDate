# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

PlayDate is a local game library manager. It runs as a Flask web server wrapped in a native OS window via pywebview (no Electron). Users browse their Steam and GOG libraries, apply filters, track completion, and use a "Pick 6" feature to discover what to play next. Non-Steam games use negative integer appids. Non-Steam library sources (GOG, Epic, etc.) are optional plugins. None of them ship as source in this repo, including PlayDate's own first-party ones (GOG, EA App, Epic Games, Humble Bundle, IndieGala, itch.io) — they're published as their own GitHub repos and installed like any third-party plugin (see Plugin System below); GOG is the reference implementation for new plugin authors to study, not something bundled with the app.

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
| `scrapers.py` | Steam API + HTML scraping; `blaeo_bp` — BLAEO sync |
| `utils.py` | Steam path detection, install sync, filesystem watcher, VDF parsing, `validate_user_path()` |
| `images.py` | `images_bp` — cover art: Steam manifest → CDN → SteamGridDB fallback chain |
| `hltb.py` | `hltb_bp` — HowLongToBeat match/select/confirm routes (scraping itself lives in `scrapers.py`) |
| `date_import.py` | `date_import_bp` — pending-date polling + bulk date import queue for `steam_date_import.user.js` |
| `system.py` | `system_bp` — launch games, open paths in the OS file manager, process-running checks |
| `backup.py` | `backup_bp` — full backup/restore zip, CSV export |
| `diagnostics.py` | `diagnostics_bp` — sends `playdate.log` + version/OS summary to a Discord webhook for support triage (`/api/submit-log`) |
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

**Startup playtime sync:** reads `localconfig.vdf`, updates playtime + last_played. For changed playtime, re-fetches achievements; `'Never Played'` → `'Unfinished'` if playtime > 0 (if `auto_promote_unfinished` is enabled). `scrapers._sweep_achievement_completion_status()` then corrects `completion_status` from whatever achievement counts are currently stored, Steam-only, gated by two independent settings (Completion Sync section, Library modal): `auto_complete_on_100pct` (any status → `'Completed'` at 100%, default on) and `auto_downgrade_completed` (`'Completed'` → `'Beaten'` if counts no longer show 100% — e.g. the developer added achievements after a 100% run, default on). Also called after `bulk_rescrape_games()` finishes, since that path refreshes achievement counts too.

**BLAEO sync:** plain `requests` + `BeautifulSoup` HTML scraping, no browser automation. `data-value='-2'` on achievements cell means no Steam achievements — skip.

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

### Wine/Proton Launch Reliability (Linux)
`runners/wine.py`'s `_build_run()` routes wineboot/winetricks/install/launch through `umu-run` (the Steam Runtime container wrapper) whenever both it and a real Proton build (`toolmanifest.vdf` present) are available — a bare Proton `wine_bin` cannot run anything standalone at all (confirmed live: crashes loading `vkd3d`/`wined3d` without the Steam Runtime), and raw Proton wineboot/installer invocations have repeatedly hung/deadlocked independent of which Proton/Wine-GE build is used. Applies to every Wine-based plugin (GOG, Humble, itch.io, IndieGala, Ubisoft, EA App), not just one.

**Already-running-session gotcha:** a *second* `umu-run` invocation against a prefix that already has a live session deadlocks (`do_lock_file_wait` on the existing session's startup lock) instead of joining it — `umu-run`'s own `UMU_CONTAINER_NSENTER=1` container-reentry feature looked like the fix but did not hold up under verification (see PLUGINS_STATUS.md's Ubisoft Connect entry, 2026-08-26 part 2). `launch_protocol_url()` and `run_in_prefix()` both check `_prefix_has_running_process()` first: for a self-contained (non-Proton) `wine_bin` they signal the live session directly with a plain `wine`/`wine start` call (no container, no deadlock risk); for a Proton `wine_bin` they end the existing session first (`end_prefix_session()` → `wineserver -k`, wait up to 10s) before bootstrapping a fresh `umu-run` launch — this is the only combination confirmed reliable across multiple Proton builds (GE-Proton, official Proton, `UMU-Proton`) and alternate Wine builds (system Wine renders/behaves correctly but has no GPU-rendering setup without umu-run's Steam Runtime; Wine-GE-Custom's last-ever release is too old to render a modern Chromium-based launcher UI at all). `run_in_prefix()` got this fix later than `launch_protocol_url()` (2026-08-27) — found live via EA's native launch path: launching a game natively while EA Desktop's own session was already up in the same prefix spawned a second wineserver that sat in `do_lock_file_wait` forever, silently doing nothing (no error, no window). Any plugin calling `run_in_prefix()` to launch an already-installed game (GOG, Ubisoft, Humble, itch.io, IndieGala, EA App) was exposed to this whenever its own client/launcher process was already running in the same prefix.

**Concurrent-request race on top of the above (2026-08-27):** the already-running-session check/kill/relaunch sequence in both functions was not thread-safe against itself — rapid repeated clicks on Launch/Install (Waitress runs 8 request threads) let multiple Flask requests race through it concurrently for the *same* prefix, each acting on stale state. Confirmed live: three overlapping Epic Games launch clicks spawned three separate `umu-run` containers fighting over the same prefix, left multiple orphaned `wineserver` processes behind, and even crashed `pressure-vessel` itself with an internal `_srt_architecture_read_elf` assertion failure from two containers racing for the same resources. Fixed with `_get_prefix_lock(prefix_path)` — one `threading.Lock` per absolute prefix path (created on first use, guarded by a small dict lock), held around the whole check-kill-relaunch decision in both `launch_protocol_url()` and `run_in_prefix()`. The lock only wraps that synchronous decision, not the launched process's lifetime, so it doesn't block anything long-term — a second concurrent request now just waits for the first's decision to finish (up to the ~10s `end_prefix_session()` wait, worst case) instead of racing it.

**`WINEPREFIX` for a real launched game is `<prefix>/pfx`, not `<prefix>`** — Proton always runs the actual game under a `pfx` subdirectory of the compat-data root PlayDate passes as `prefix_path` (Steam's standard `compatdata/<id>/pfx/` layout). `list_prefix_processes(prefix_path)` (the shared process-enumeration helper other running-game/session checks are built on) matches both paths; missing this made a plugin's own "is a game currently running" check blind to actual games (found via Ubisoft's kill-and-relaunch safety check).

**Wayland:** `_prefer_native_wayland()` drops `DISPLAY` when `WAYLAND_DISPLAY` is set, for plain (non-Proton) Wine invocations only — Proton builds already force native Wayland internally regardless of `DISPLAY`. A self-contained Wine build left without this fell back to XWayland compatibility rendering under KDE Plasma Wayland, causing slow/unregistered clicks on an otherwise-working window.

## Plugin System

Non-Steam library sources are optional plugins in `<id>/` subdirectories. See `PLUGINS.md` for the full developer guide. Key points:

- **Plugin storage:** installed plugins live in a writable directory (`plugins._user_plugins_dir()` = `BASE_DIR/plugins/`), separate from the legacy bundled `plugins/` folder next to `plugins/__init__.py`. For a source checkout these are literally the same physical directory (`BASE_DIR` is the project root there), but for Flatpak/frozen builds the writable one survives an update while the bundled one doesn't — `flatpak install --reinstall` swaps `/app` wholesale, and even the Windows/source update paths never delete a file they didn't ship in the first place, so a plugin someone already had "just works" across updates either way. `load_all()` scans both directories, migrates anything still sitting in the legacy bundled location into the writable one (self-terminating — see `_migrate_legacy_plugin_dirs`), and is safe to call more than once: it skips any id already in `_plugins`, so a later call only registers what's actually new.
- **Official plugins:** GOG, EA App, Epic Games, Humble Bundle, IndieGala, and itch.io don't ship as source here — they're published as their own GitHub repos (`plugins.OFFICIAL_PLUGINS`, each `{id, name, source, platform_status}`) and installed the same way as a third-party plugin. `reinstall_configured_official_plugins()` runs once at startup, *before* the first `load_all()`/`register_blueprint` (must — Flask refuses new blueprint registrations once the app has served a request, which a background-thread version of this hit immediately in testing), and re-fetches any of these missing from disk *only if* there's evidence of prior configuration — a saved auth token (`config.json[plugin_id]`) or launcher config (`config.json['launchers'][plugin_id]`), both of which a real uninstall clears via `on_uninstall()`/the uninstall route, so this can never resurrect one that was deliberately removed. It deliberately does not install something nobody ever configured — that's opt-in via the Plugin Catalog.
- **Beta plugins:** `plugins.BETA_PLUGINS` (Ubisoft Connect, Amazon Games, Battle.net, Rockstar) — unfinished/unconfirmed, published the same way as OFFICIAL_PLUGINS but **never** touched by `reinstall_configured_official_plugins()` regardless of saved config; purely opt-in via the catalog. Kept as a separate list from `OFFICIAL_PLUGINS` specifically so that scoping holds even though both feed the same catalog UI.
- **`platform_status`:** each `OFFICIAL_PLUGINS`/`BETA_PLUGINS` entry carries `{windows, linux, mac} -> 'working' | 'untested' | 'broken'`, based on real reports (this project's own Linux testing, or user reports for Windows) — not "should work in theory". `GET /api/plugins/catalog` resolves this against `_current_platform_key()` (the OS PlayDate is actually running on, via `sys.platform`) and returns only that one status per entry, bucketed for the Plugins modal's expandable Working/Untested/Broken sections. Mirrored into each plugin's own `plugin.json` for anyone browsing that repo directly, but `plugins/__init__.py`'s copy is what core actually reads.
- **Auto-discovery:** any folder with a `plugin.json`, in either directory above, is loaded at startup via `plugins/__init__.py`'s `load_all()`.
- **`min_core_version` field in `plugin.json`** — optional; if set and newer than the running `config.__version__`, `load_all()` skips importing/registering the plugin (fails safe instead of crashing on a missing method/field a newer plugin version assumes). Recorded in `_incompatible_plugins`, exposed via `GET /api/plugins/incompatible`, and rendered in the Plugins modal with a "needs PlayDate X.Y.Z" badge; still uninstallable via the normal uninstall flow (checks both the writable and legacy bundled locations since it was never registered into `_plugin_paths`).
- **Only raise a plugin's `min_core_version` together with a bump to that plugin's own `version`, never alone.** A plugin whose code hasn't changed already works fine on whatever core it was last released against; raising `min_core_version` in isolation retroactively marks that same, already-shipped version incompatible for every existing user still on an older PlayDate build, even though nothing about their setup changed. "This plugin would merely *benefit* from a same-day core fix it already depended on the same way before" is not grounds for gating — only a genuinely new plugin release that assumes new core behavior is (confirmed 2026-08-27: EA App/Ubisoft/Epic Games legitimately got both bumped together since their own code changed; GOG/Humble/itch.io/IndieGala's `min_core_version` bump was reverted after being applied with no accompanying version bump).
- **`min_core_version` is also enforced at install/update time, not just at load time** — `_install_plugin_zip()` (shared by manual zip upload, `POST /api/plugins/install-from-github`, and the Plugins-modal Update button, which all funnel through it) rejects a plugin outright if its `min_core_version` exceeds the relevant PlayDate version, raising a user-facing `ValueError` surfaced directly in the modal. Before this, nothing blocked the install itself — a user could click Update, have it report success, and only discover next restart that the plugin silently vanished with a "needs PlayDate X.Y.Z" badge instead of the working plugin they had a moment earlier. The one nuance: `_install_plugin_zip()` takes an optional `target_core_version` param, used only by the "update PlayDate and plugins together" flow (`_doInstallUpdateWithPlugins()` in `base.html`) — that flow installs plugin updates *before* the core update actually happens, so comparing against the still-old running `config.__version__` would wrongly reject a plugin update released alongside the same PlayDate version; it passes the target PlayDate version instead. `GET /api/plugins/check-updates` mirrors this distinction: it never suppresses `update_available` for a `min_core_version` mismatch (that would also hide the plugin from the bundled-update flow, where it's a legitimate offer) — it annotates the response with a `requires_core` field instead, and the actual gate stays entirely at install time. The Plugins modal (`_checkPluginUpdates` in `modal_tools.js`) consumes `requires_core`: a gated plugin still goes into `window._pendingPluginUpdates` (so "Update PlayDate & Plugins" in `base.html`, which passes `target_core_version`, still updates it), but its per-plugin line renders a non-clickable "vX.Y.Z · needs PlayDate A.B.C" note instead of the standalone update link, and it lights only the Plugins-section dot, not the global hamburger update dot (that one's reserved for directly-actionable updates; a core update lights it on its own anyway).
- **Jinja2 globals:** `has_plugin(id)`, `plugin_fragments(slot)`, `platform_labels()`, `plugin_js_api()` — available in all templates.
- **`window._PLAT_LABELS`** — injected in `base.html`; maps platform key → display label. Use this instead of hardcoded dicts. Core provides `steam`, `epic_games`, `ea_app`, `ubisoft`; plugins add their own.
- **`window._PLUGIN_API`** — injected in `base.html`; maps platform key → `{uninstall_url, scrape_url, scrape_method, store_url, store_label, appid_label, sync_label}`. Core templates use this for per-platform behavior; no platform-specific branches in core code.
- **Management UI:** hamburger → Plugins; install via zip, GitHub URL, or one-click from the Plugin Catalog (anything in `OFFICIAL_PLUGINS`/`BETA_PLUGINS` not currently loaded — `GET /api/plugins/catalog`); uninstall with optional game removal, restart-required notice. `uninstall_plugin()` also clears the in-memory `_plugins`/`_plugin_paths`/`_plugin_manifests` entries, not just the files on disk, so a freshly-uninstalled plugin stops showing as loaded immediately rather than until the next restart.
- **GitHub install:** `POST /api/plugins/install-from-github` accepts `{url}` (any `github.com/owner/repo` form), fetches the latest release zip asset (falls back to zipball), and installs via the shared `_install_plugin_zip(raw_bytes)` helper.
- **Update checking:** `GET /api/plugins/check-updates` checks GitHub for each plugin whose `plugin.json` has `"source": "github:owner/repo"`; compares semver against installed `version`; 6-hour per-plugin cache in `_plugin_update_cache`. Fires automatically when the Plugins modal opens; shows a one-click update link on cards with newer releases.
- **`launch_game(appid)`** — plugin lifecycle method; core `/api/launch/<appid>` dispatches non-Steam platforms to `plugin.launch_game(appid)` by matching the `platform` column. Returns 501 if no plugin claims the platform. When a game needs to install before launching, return `{"status": "installing", "install_poller": "<js_fn_name>", "message": "…"}` — core calls `window[install_poller](appid)` if that function exists. Do not use platform-named flags like `gog_install`.
- **`rescrape(appid) -> dict | None`** — optional; called by `bulk_rescrape_games` for any non-Steam game whose platform has a plugin with this method. Must return a dict ready to pass to `update_game_data(**meta)` (including `meta_fetched`, `cheevos_fetched` if applicable), or `None` on failure. Replaces direct plugin imports in `scrapers.py`.
- **`resync_installed()`** — optional; re-checks installed-flag/install_path for every game on the plugin's platform (each plugin already implements this for its own startup sync and `PluginInstallWatcher` callback). `bulk_rescrape_games()` calls it once, after the sweep, for every non-Steam platform it touched (2026-08-27) — metadata a rescrape just fetched (e.g. a content_id needed for install matching) can newly make detection succeed for a game the plugin couldn't match before, and that's not a filesystem event `PluginInstallWatcher` would ever see on its own. Also called by `backup.py` after a restore.
- **`runners.watcher.PluginInstallWatcher`** — the instant, event-driven install-status watcher shared by every Wine-based plugin (same model as Steam's own `steamapps` watcher in `utils.py`; no periodic polling needed). If `start(watch_path)` is called before `watch_path` exists yet (a fresh prefix with zero games installed), it retries every 30s until the path appears, then attaches for good (2026-08-27) — without this, a plugin whose install-base directory doesn't exist at first startup would never get instant detection at all, since `watchdog` has nothing to `schedule()` against until the directory exists.
- **`fetch_description(appid, platform_id) -> str | None`** — optional; called by `/api/game-description/<appid>` for non-Steam platforms. Return a plain-text description string, or `None` if unavailable. Core falls back to the Steam store API when no plugin implements this.
- **`date_import_url` (class attribute, str)** — optional; declare this if the platform has an external orders/activation page that the Tampermonkey date-import script should open. Core collects these from all plugins whose games are in the selection and returns them as `date_import_urls: [{url, label}]` from the bulk date import start endpoint. The frontend opens each URL in a new tab generically.
- **`launcher` field in `plugin.json`** — declares whether a plugin needs a separate launcher process (`"launcher": {"required": true, "name": "...", "exe_name": "..."}` or `{"required": false}`). Core reads this to drive launcher config UI; no code changes needed in the plugin.
- **Launcher config:** `GET/POST /api/launcher-config/<platform_id>` stores `{wine_bin, prefix, mode}` under `config.json["launchers"]`. GET also returns `wine_bin_detected` from `runners.wine.find_wine_binary()`.
- **`launcher_status()`** — optional plugin method returning `{"available": bool, "detail": str}`. Called at startup (3s delay) for all plugins that implement it; result cached in `_launcher_status_cache`. `GET /api/plugins/launcher-status` returns the full cache; `POST /api/plugins/launcher-status/<platform_id>` re-runs on demand.
- **Launcher UI:** plugin cards in the Plugins modal show a green "Launcher ready" badge or amber warning + "Configure Launcher" button when `launcher.required` is true. The inline config panel auto-populates Wine binary from saved config or `find_wine_binary()`.
- **`manage_ui()` button actions:** `type: 'call'` invokes a JS function by name; `type: 'post'` POSTs to an endpoint; `type: 'open_url'` opens a URL in the system browser; `type: 'oauth_popup'` opens `main.py`'s `open_auth_popup()` (an in-app WebKit login window); `type: 'oauth_paste'` skips straight to a paste-a-value modal with no popup attempt. The rendered `onclick` attribute is built with `JSON.stringify`, so it must be passed through `escHtml()` before insertion into HTML — this is handled by `_buildManageBlockHtml` in `modal_tools.html`. Do not bypass it.
- **Login popup blocked by site-side bot detection:** several plugins' `oauth_popup` config (Amazon Games, Rockstar, itch.io, Epic Games) pairs the popup with a second `oauth_paste` button plus an in-instructions note, for when the embedded WebKit popup itself gets stuck on a Cloudflare/captcha verification page and never reaches the real login form — sign in in a real browser instead, then paste the resulting code/key/cookie value manually. Both paths funnel through the same `callback_endpoint`, so no backend changes are needed to add the fallback to a plugin that only has the popup today. Confirmed live (itch.io, Epic Games) that this class of failure is a real, not just theoretical, risk — don't assume `oauth_popup`-only is sufficient for a new plugin behind Cloudflare. EA App abandoned `oauth_popup` entirely (it used Selenium/headless Chrome, not the in-app WebKit popup) in favor of `oauth_paste`-only: the user opens EA's token URL in their real browser and pastes the `access_token` back.
- **EA App install/launch/uninstall are deliberately minimal — just open EA App itself, same as Lutris.** A from-scratch native downloader, a native LSX launch bypass with OOA/Denuvo licensing, and an offerId-keyed `origin2://` protocol hand-off to EA Desktop were all tried and removed (2026-08-27, see PLUGINS_STATUS.md) — each hit a launcher-specific dead end (legacy pre-DIP manifests with no resolvable exe; EA Desktop itself rejecting the offerId hand-off for reissued classic titles with a "belongs to another user" error, unrelated to actual ownership). Install-status *detection* (`manifest.find_manifest_path_by_content_id()`/`find_install_dir_by_name()`, driving the "Installed" badge/filter) is unaffected and stays. Do not resurrect the native-launch/OOA approach without re-reading that history first.
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

**Grid mode** (default): `library.html` uses IntersectionObserver (`rootMargin: '2400px'`) + `CARD_HTML_CACHE`. Images use `data-src`, loaded via `requestIdleCallback` (500ms timeout, 150ms `setTimeout` fallback) after scroll settles (0ms on initial load). Cover art responses set a 1-year `Cache-Control` max-age (`app.py`'s `serve_library_image`) since URLs are cache-busted client-side with a `?v=` timestamp bumped per-appid on actual art changes (`_imgVersions`, see `_patchGameCard`), so a stale browser cache isn't possible. `_patchGameCard` evicts from `CARD_HTML_CACHE` so edits show fresh data.

**Every page that renders `/static/img/library/{vertical,horizontal,icons}/{appid}.jpg` must append its own `?v=` cache-buster** (a page-load-time `const _imgV = Date.now()` is sufficient, matching `library.js`'s own pattern) — the 1-year `Cache-Control` header above means a browser that already cached a stale image for an appid will never re-fetch it on that page again otherwise, no matter how the underlying file changes. `index.html` (home shelves) and `pick.html` (Pick 6) both shipped without this and had to be retrofitted (found live: art updates showed correctly on the library page but stayed stuck on stale images on Home/Pick 6 indefinitely); `modal_edit.html`'s initial art-panel load (`_loadArtPanel` calls on modal open, not its post-edit refresh which already had one) had the same gap.

**List mode**: split-pane layout (`#library-list-layout`) with `#list-pane` (scrollable rows, 20% width, resizable) and `#detail-pane` (game detail + inline edit form). Activated via the VIEW modal; stored as `artwork_orientation: 'list'` in `state.json`. On activation, `#game-grid` and `.library-header` are hidden, `body` and `.container` overflow is locked to `hidden`, and `_adjustListHeight()` sizes `#library-list-layout` to fill the remaining viewport. A `_listObserver` (IntersectionObserver) loads icons as rows scroll into view.

## HLTB Integration

Times stored in minutes. `hltb_fetched` states: `NULL`/`'0'` = never fetched; `'unconfirmed'` = matched below threshold (times NULL); `'no_match'` = no results; `YYYY-MM-DD` = confirmed. Startup catch-up only fetches `NULL`/`'0'` — does not retry `no_match` automatically.

## In-App Tutorial

`templates/modal_tutorial.html` (included from `base.html` on every page) + `static/js/tutorial.js` - a table-of-contents modal covering every part of the app, built on the same step-show pattern as the Emulators "Add Emulator" wizard (`_tutShowSection(id, stepIndex)` hides/shows step divs; `_tutNext`/`_tutBack` walk the index). No dedicated gamepad zone: it reuses the existing `'modal'` zone in `input.js` (registered in `_MODAL_IDS`, `_watchModal()`, and `_closeAnyOpenModal()`'s checks list) since every interactive element is a plain `data-modal-row` button. ToC and the step view are mutually exclusive, so both are full-width flex siblings rather than grid columns; a fixed-track CSS grid would auto-place whichever one is visible into the first track, a real bug hit during development.

Content lives entirely in `TUTORIAL_SECTIONS` (`tutorial.js`) as trusted static copy (assigned via `innerHTML`, not `escHtml()`), no screenshots by design: embedding real screenshots would mean shipping a maintainer's personal library/account state to every user.

**Auto-show:** `config.json`'s `tutorial_seen` bool (same one-shot pattern as `last_seen_version`/What's New, see `/api/tutorial/seen`, `/api/whats-new`), exposed via `inject_config_status()` as `window._TUTORIAL_SEEN`. A brand-new account and an existing account upgrading to the version that added this both start with no key, so one flag covers "show after first-run setup" and "show once for existing users" with no special-casing. Sequenced after What's New's own dismiss (or immediately if there's nothing to show) so the two never fight for the screen on an upgrade that ships both at once.

## Update Confirmation Backup Cooldown

`update-confirm-overlay` (base.html)'s "Back Up First" button is hidden, and its hint text swapped, whenever `GET /api/backup-status` (`backup.py`) reports a backup completed within `BACKUP_COOLDOWN_SECONDS` (24h). `last_backup_at` (a `state.json` unix-timestamp float) is written by both `/api/backup` and `/api/backup-to-path` on success. Checked fresh via fetch every time `handleUpdateBtn()` opens the modal, not injected at page load - completing a backup doesn't reload the page, so a stale server-rendered flag would still nag immediately after backing up, which is the exact complaint this fixes.

## Log Submission

System modal → Support → "Send Log to Developer" (`send-log-modal` in `modal_tools.html`, `submitLog()` in `modal_tools.js`) posts `playdate.log` (last 1MB, matching the `RotatingFileHandler` cap) plus version/OS/install-channel and an optional user message to `POST /api/submit-log` (`diagnostics.py`), which forwards it to a Cloudflare Worker relay (`tools/log-relay/`), which in turn posts it to Discord. Only the log file is sent — never `config.json`/`state.json`, so no API keys or account tokens leave the machine. Server-side cooldown (`SUBMIT_COOLDOWN_SECONDS`, 5 min, tracked via `state.json`'s `last_log_submit_at`) prevents spam-resubmission from the app itself.

`RELAY_URL` in `diagnostics.py` is a plain constant (not an env var) because it needs to be baked into the shipped binary for every user, not configured per-install. If it's ever blank, the route 501s instead of erroring. Because it ships inside public source/binaries, it's discoverable and postable-to by anyone — but unlike the raw Discord webhook URL this constant used to hold directly (found and abused via public git history, see `tools/log-relay/README.md`), the relay only ever forwards a fixed message template and never lets a direct caller inject raw content/mentions/embeds, so finding this URL doesn't hand out a "post anything to our Discord" credential the way the old constant did. The real Discord webhook now lives only as a secret on the relay (never in source), with its own KV-backed per-IP rate limiting as a second backstop.

## PAGYWOSG Filter Builder

The PAGYWOSG tool (`modal_tools.html`) builds structured filter trees for the monthly PAGYWOSG event on SteamGifts. Categories are fetched live from `pagywosg.xyz`: there's no static catalog of category names.

**`pagywosg.py`** is the single source of truth for category classification and the operator vocabulary. `classify_category(base, base_appids, icaio_ga, icaio_wl, santa)` pattern-matches a live category name into a neutral op (`OP_REGISTRY` key: `month_is`, `contains`, `title_word`, `digit_count_gte`, `has_special_char`, `range_incl`, `nth_weekday`, `contains_all`, etc.) or falls through to the mod-verified appid list (`reason: 'verified_fallback'`/`'unhandled'` mark this as *not* automated; see the category scanner below). Each `OP_REGISTRY` entry carries: the SQL "kind" (dispatches `redundant_where_sql()`'s redundant-appid pre-check, and the JS `pagCondToTree`/`pagCondToSql`/`_pagCheckCond` in modal_tools.html/modal_edit.html), the saved-tree `tree_op` token, and the manual condition-builder dropdown label. `window._PAG_OPS` injects the whole registry into every page (same pattern as `window._PLAT_LABELS`/`_PLUGIN_API`, see Plugin System) so the frontend never hardcodes op behavior. Adding a category that reuses an existing op is one new regex branch in `classify_category()`; a genuinely new op needs an `OP_REGISTRY` entry plus all three SQL/JS consumers.

**Event ID formula:** `pagywosg.pagywosg_event_id(year, month)` — events are numbered sequentially, one per month, anchored at event 1 = June 2019, the site's actual first event (`PAGYWOSG_EPOCH_*` constants in `pagywosg.py`); every id is just an offset in months from that anchor. Verified against the live API (events 1-87, 2026-08-24) with zero skipped months across the whole history. Single source of truth reused by `pagywosg_auto()`, `pagywosg_quals_data()`, and the category scanner's `_current_event_id()`.

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

`release.py` (gitignored, local-only) also checks the six official plugins' local `plugin.json` versions against their published GitHub releases (`check_official_plugin_updates()`) as part of both `main()` and `main_beta()`, and offers to push+tag+release any that are ahead (`publish_plugin_update()`). Non-blocking — a plugin repo being behind doesn't stop a PlayDate release — and only finds anything to do if the maintainer has one of the six checked out locally with unpublished changes, since fixing a bundled-turned-catalog plugin no longer ships automatically with the next PlayDate release the way it did when the source lived in this repo.
