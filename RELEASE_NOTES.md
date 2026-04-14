# Release Notes

## Installation

### Windows
1. Download **PlayDate-Setup.exe** below
2. Run it and follow the installer wizard
3. PlayDate will appear in your Start Menu

**Requirements:** Windows 10 or 11 (64-bit). Microsoft Edge WebView2 Runtime is required — it comes pre-installed on Windows 10/11.

### Linux
```bash
chmod +x install.sh && ./install.sh
```

**Requirements:** Python 3.10+ and the WebKit/GTK bindings for your distro:
```bash
# Debian / Ubuntu
sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.0

# Fedora
sudo dnf install python3-gobject webkit2gtk4.0
```

### macOS
```bash
chmod +x install.sh && ./install.sh
```

**Requirements:** Python 3.10+. pywebview should work out of the box on recent macOS versions. macOS support is present but not yet fully tested.

---

## v1.4.0 — 2026-04-14

### New

- **GOG Galaxy integration** — Full GOG support alongside Steam. Connect your GOG account via OAuth2 (auth-code flow with step-by-step instructions), sync your GOG library, and manage everything from a new GOG panel in Settings. GOG games are auto-matched to Steam games by normalized name with automatic duplicate detection.
  - Library sync via GOG's paginated `getFilteredProducts` API
  - Metadata fetch via `api.gog.com/v2/games/{id}` (developers, publishers, genres, tags, release date, platform slug)
  - Achievement fetch via `gameplay.gog.com` (counts unlocked achievements)
  - GOG store link support in the edit modal (`gog.com/en/game/{slug}`)
  - Purchase date import via Tampermonkey script on GOG orders page (page 1 parsed from inline `gogData`, pages 2-N fetched via Angular XHR API)
- **GOG game install & launch** — Download and install GOG games directly through PlayDate. The GOG content-system v2 fetches builds → meta manifest → depot manifests → downloads and decompresses zlib chunks into the final file layout. Prefers Linux builds, falls back to Windows. Windows games get a Proton prefix auto-configured. Windows games launch via Proton; Linux native games launch directly. Install progress shows MB downloaded in a toast and is cancellable. Background threading with `threading.Event` cancel support.
- **Proton detection** — `runners/proton.py` detects GE-Proton and official Proton across both `~/.steam/steam` and `~/.local/share/Steam` (deduped via `os.path.realpath`). `launch_game()` sets `STEAM_COMPAT_DATA_PATH` + `STEAM_COMPAT_CLIENT_INSTALL_PATH` and spawns `proton run {exe}`. Active Proton runner displayed in Settings.
- **Duplicate detection & hiding** — New `duplicate_of` column links non-Steam games to their Steam counterpart. Library excludes duplicates by default; toggle via "DUPES: OFF/ON" button. Library header shows "N duplicates hidden" when any exist. Edit modal shows a "Duplicate of:" row for non-Steam games with a searchable Steam library lookup, link button, and unlink button. Auto-detection runs after every GOG library sync; manually re-runnable via "Detect Duplicates" in the GOG Tools panel. Search endpoint: `GET /api/games/search?q=&platform=`.
- **Platform filter** — New `platform` column added to the database (backfilled to `'steam'` for all existing rows). Filter modal supports platform as a select-type filter with options: Steam, GOG, Epic Games, EA App, Ubisoft. PAGYWOSG filter builder automatically prepends `platform = 'steam'`. All game cards carry `data-platform` attribute for platform-aware context menus and launch behavior. Platform navbar dropdown removed — platform is now a filter condition only.
- **Sort direction auto-set** — Changing the sort column now auto-sets direction: name ASC; playtime, release date, date added, review scores DESC; HLTB ASC.
- **Background image opacity control** — Background moved from `body` to `body::before` pseudo-element so opacity can be controlled independently via `--bg-image-opacity` CSS variable. Theme settings now have an Opacity slider (0–100%) alongside the file picker. Default is 1 (fully opaque).
- **Inter-game delay reduced** — Populate loop delay reduced from 1s to 0.5s (meta worker stays at 1.5s to respect the Steam appdetails rate limit of 200 req/5min).
- **Tampermonkey script v2.4** — GOG orders page support added. Script now matches `https://www.gog.com/en/account/settings/orders*` alongside Steam Help pages. Bulk date import opens the appropriate page(s) based on which platforms are in scope.

### Fixes

- **Context menu "Select All"** now correctly scopes to the right-clicked input field instead of selecting the entire page.
- **Base HTML refactored** — Custom alert/confirm dialog extracted to `_dialog.html`, context menu extracted to `_ctx_menu.html`. `base.html` reduced from 1280 to 646 lines.
- **Modal tools refactored** — HLTB modal extracted to `_modal_hltb.html`. `modal_tools.html` reduced from 4162 to 3631 lines.
- **Negative appid support** — Flask `SignedIntConverter` registered so routes like `/api/game/-1` work for GOG games (which use negative appids). `appid_list` validation now allows zero/negative appids.
- **Install status sync** now scopes Steam install reset to `WHERE platform = 'steam' OR platform IS NULL` — non-Steam install state is managed separately by each platform.
- **`ts_to_date()`** now handles GOG date strings that are already in `'YYYY-MM-DD'` format (returns as-is instead of trying to parse as Unix timestamp).
- **CSS path fix** — Background URL fixed from `/static/img//backgrounds/` (double slash) to `/static/img/backgrounds/`.
- **Gamepad state clearing** — `clearSuppression()` method added to gamepad input manager.

### Changed

- **Edit modal** — The "Steam AppID" row now stays visible for GOG games. Label toggles between "AppID:" (Steam) and "GOG ID:" (GOG), and the display shows `platform_id` for GOG games. Steam store link is hidden for GOG; GOG store link is shown when `platform_slug` is available. "Sync Steam Data" button relabeled to "Sync Data" or "Sync GOG Data" based on platform. Steam-specific fields (Steam Help link, Achievements link, ProtonDB) are hidden for non-Steam games.
- **Bulk date import** — Now handles both Steam and GOG games. The start endpoint splits the queue by platform: Steam games go through the per-page Help flow, GOG games are flagged via `has_gog: true` so the frontend routes them to the GOG orders-page Tampermonkey script. "STEAM DATA" section header renamed to "STORE DATA".
- **PAGYWOSG filter editing** — Opening the filter modal on an already-active PAGYWOSG filter now seeds the tree from the server so editing and re-applying preserves `pagywosg`, `pagywosg_event`, and `pagywosg_verified` keys.
- **Image downloads** — SteamGridDB search by game name (`_sgdb_search_game_id()`) enables art lookups for non-Steam games via SGDB's internal game ID instead of relying on Steam appid. When `sgdb_id` is provided, Steam CDN is skipped and SGDB is queried directly.
- **Library query** — Excludes `duplicate_of IS NOT NULL` by default. `hide_duplicates` boolean in state defaults to `true`.




