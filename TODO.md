# TODO

## Known Bugs

*(none)*

---

## Improvements

- **Gamepad support** — home page editor buttons, bulk edit modal navigation, text input focus, disable RB/LB while in modals
- **Pick 6 smart length limits** — currently uses scoring bias only; medium-length games still appear when the library has many of them. Idea: find the tightest hourly cutoff (starting at 1hr, stepping up) that keeps at least 12 games and 1% of the eligible pool, then hard-exclude games outside it. Open questions: thresholds vs filtered pool or full library; step size (30min vs 1hr); behavior when even 10hr cap doesn't hit thresholds; whether to surface the applied cutoff to the user.

---

## Small Features

- **Library group-by** — sort games into sections by a chosen field (e.g. installed status, completion status, ProtonDB tier); each section sorted by the active sort column and direction. Implementation approach for non-obvious grouping fields TBD. Group-by installed (installed games first) is the most-wanted specific case.
- **PAGYWOSG Snowballs / Secret Santa support** — Snowballs and Secret Santa are PAGYWOSG/POP gift events. The filter builder and quals panel should recognise their pool/criteria structure the same way the main PAGYWOSG event does.

---

## Big Features

- **Non-Steam library support** — see Implementation Plans
- **Card badges** — see Implementation Plans
- **Plugin system**

---

## Potential / Under Consideration

- **BLAEO sync downgrade prevention** — BLAEO sync unconditionally overwrites `completion_status` with whatever BLAEO reports, which can downgrade e.g. `Beaten` → `Unfinished`. Options: a hard guard matching `sync_recent_playtime` logic (never downgrade Beaten/Completed), a per-direction setting (e.g. "allow BLAEO to downgrade from Beaten"), or a setting toggle for each status transition. Direction of travel: probably a settings option since some users may want BLAEO to be authoritative.
- **Sort by total reviews** — sort by `total_reviews` to surface popular games or find obscure ones. Already in `SAFE_COLUMNS`, just needs a dropdown option.
- **Extend Playnite import** — also import completion status
- **Refactor app.py into Flask blueprints** — by area (library, scraping, config, import tools)

---

## Implementation Plans

### Non-Steam Library Support

Add games from other launchers and eventually DRM-free/emulated titles alongside Steam games.

**ID scheme:** Non-Steam games use negative integer appids (-1, -2, -3 ...). Steam never uses negatives. `config.json` gains `next_nonsteam_id: -1`, decremented on each add. Art files stored as `static/img/library/vertical/-1.jpg` etc. All existing Flask routes using `<int:appid>` accept negatives without changes.

**New DB columns:**
- `platform` TEXT — `'steam'` (backfilled on migration), `'gog'`, `'epic'`, `'ubisoft'`, `'ea'`, `'lutris'`, `'drm_free'`, `'emulated'`
- `platform_id` TEXT — platform-native game ID (used for launch URI and manifest matching)
- `game_path` TEXT — exe or ROM path (drm_free / emulated only)
- `emulator` TEXT — emulator name/command (emulated only)

**Phase 1 — Launcher games:**

*Linux:* Import from Lutris (`~/.local/share/lutris/pga.db` — SQLite). Launch via `lutris lutris:rungameid/{id}`. Lutris covers native, Wine, GOG, and Epic games in one integration.

*Windows/Mac:* Read each launcher's install manifests to detect installed games:
- **GOG:** `%PROGRAMDATA%\GOG.com\Galaxy\storage\` (SQLite)
- **Epic:** `%PROGRAMDATA%\Epic\EpicGamesLauncher\Data\Manifests\*.item` (JSON)
- **EA App:** `%PROGRAMDATA%\EA Desktop\EA Desktop\` manifests
- **Ubisoft:** Registry + `%PROGRAMFILES%\Ubisoft\Ubisoft Game Launcher\games\`

Launch via OS-registered URI schemes: `goggalaxy://openGame/{id}`, `com.epicgames.launcher://apps/{name}?action=launch`, `uplay://launch/{id}/0`, `origin://LaunchGame/{id}`. Use `webbrowser.open()` or `subprocess` depending on OS.

**Art:** Skip Steam CDN. New `_sgdb_get_by_name(name, sgdb_key)` helper: `GET /api/v1/search/autocomplete/{name}` → first result ID → grid/icon endpoints. `download_vertical/horizontal/icon` in `images.py` check `platform != 'steam'` to use name-based SGDB path.

**Edit modal:** `game.appid < 0` hides Steam-specific fields: AppID, Steam Store link, ProtonDB row, Achievements link, Sync Store Data button.

**Install status:** Scope `sync_local_install_status()` Steam reset to `WHERE platform = 'steam' OR platform IS NULL`. Launcher-based games: re-check manifest on startup to detect installs/uninstalls.

**Populate / scraping:** `add_new()` skips non-Steam games entirely. No metadata scraping — edit modal only.

**Filters:** `platform` added to `SAFE_COLUMNS` and `FM_FILTER_CONFIG` as text equality.

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
