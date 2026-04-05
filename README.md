# PlayDate

A local Steam library manager for people who take their backlog seriously.

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

---

## What it does

PlayDate pulls your Steam library, enriches it with metadata (tags, reviews, achievements, cover art), and gives you a clean interface for browsing, filtering, tracking completion, and deciding what to play next. Runs entirely locally as a standalone desktop app — no browser, no cloud, no account required beyond your Steam credentials.

---

## Features

### Library
- **Virtual grid renderer** — handles 2000+ games without performance issues
- **Vertical and horizontal card views** — toggle between portrait capsule art and landscape header art; adjustable card size slider
- **Sort and search** — sort by any column, live search by name
- **Filter system** — simple mode (pick a field, operator, value) and advanced mode (nested AND/OR groups with unlimited conditions); date fields support month/day/year part matching; custom SQL expression mode for power users; filters can be saved and reloaded by name
- **Bulk edit** — apply changes to any field across a filtered or manually selected set of games at once
- **In-place editing** — edit any game's metadata, artwork, completion status, tags, groups, and more without leaving the library

### Home Page
- **Configurable shelves** — horizontal rows of game capsules driven by any saved filter or built-in preset (recently played, installed, shuffle, etc.)
- **Layout editor** — add, remove, and reorder shelves; set limits, column widths, and sort order; shelves can be paired side-by-side
- **Widgets** — add a clock or a completion pie chart to your home page alongside your shelves
- **Deduplication** — games already shown on a higher-priority shelf are automatically excluded from lower-priority ones

### Pick 6
- **Random mode** — pick from your full unbeaten library
- **Smart mode** — builds a taste profile from your beaten games using tag cosine similarity, then scores candidates by review quality, staleness, playtime, and release recency
- **Weighted mode** — tune six scoring signals with sliders; toggle individual games in or out of the pool

### Metadata & Artwork
- **Steam scraper** — imports playtime, tags, review scores, achievement counts, release dates, developers, publishers, and genres from Steam's API and store pages; runs concurrent worker pools for art, metadata, and achievements so cards populate live as each phase completes
- **Startup sync** — on every launch, PlayDate reads your local Steam files to update playtime and last-played dates; if playtime changed, it fetches fresh achievement data and automatically promotes completion status (`Never Played` → `Unfinished`, 100% achievements → `Completed`)
- **Cover art pipeline** — downloads vertical capsule art, horizontal header art, and game icons separately; prefers 2x resolution; falls back through multiple Steam CDN paths then SteamGridDB
- **SteamGridDB browser** — search and apply custom artwork for any game from directly within PlayDate
- **BLAEO sync** — imports completion statuses, list tags, and achievement counts from your BLAEO backlog profile

### Import Tools
- **Steam date importer** — a Tampermonkey userscript (`playdate_date_import.user.js`) that scrapes activation dates from Steam help pages and sends them to PlayDate. Works in single-game mode (via the ↗ link in the edit modal) or bulk mode (batch-imports dates for an entire filtered selection). Requires **Tampermonkey with Manifest V2 enabled** — MV3 blocks the cross-origin requests the script depends on
- **Playnite import** — import `date added` values from a Playnite backup ZIP
- **Database import** — migrate columns from an older PlayDate database into your current one, with column mapping and type-mismatch warnings

### Tools
- **PAGYWOSG filter builder** — construct an eligible game pool from the monthly community post criteria and save it as a reusable library filter
- **Theme editor** — customize PlayDate's color scheme with a live preview; save and restore named themes
- **Backup & restore** — export a timestamped zip of your library data and settings (optionally including cover art); restore from any previous backup
- **Account manager** — add, switch between, and remove Steam accounts; each account has its own Steam ID, API key, and label
- **Bulk re-scrape** — refresh Steam metadata for any selection of games

### Other
- **Gamepad & keyboard navigation** — full controller support across all pages with 2D spatial grid navigation, modal zone handling, and a HUD that appears on first input
- **Completion tracking** — five statuses: Never Played, Unfinished, Beaten, Completed, Won't Play; right-click any card for a quick-set context menu
- **Update checker** — PlayDate checks for new releases in the background and notifies you when one is available

---

## Installation

### Windows

Download **PlayDate-Setup.exe** from the [latest release](https://github.com/RobbyRatpoison/PlayDate/releases/latest) and run it. The installer handles everything — no Python required.

### Linux

```bash
chmod +x install.sh && ./install.sh
```

Requires Python 3.10+ and the WebKit/GTK bindings for your distro:

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

> macOS support is present but not yet fully tested. pywebview should work out of the box on recent macOS versions.

---

## Uninstallation

### Windows
Use **Add or Remove Programs** — PlayDate registers a standard uninstaller. You'll be asked whether to delete your library data.

### Linux / macOS
```bash
./uninstall.sh
```

Removes the launcher, virtual environment, app launcher entry, and by default the entire PlayDate folder. Individual data files (`config.json`, `state.json`, `theme.json`, `games.db`, `playdate.log`) can be unchecked if you want to keep them, and the full folder deletion can be unchecked to do a partial uninstall.

---

## First-time setup

On first launch you'll be prompted for:

- **Steam ID** — your SteamID64 or vanity URL name (find it at [steamid.io](https://steamid.io))
- **Steam Web API Key** — from [steamcommunity.com/dev/apikey](https://steamcommunity.com/dev/apikey) *(optional — without it PlayDate reads your library from local Steam files instead; achievements will not be fetched)*
- **SteamGridDB API Key** — from [steamgriddb.com/profile/preferences/api](https://www.steamgriddb.com/profile/preferences/api) *(optional — enables custom artwork)*

Then hit **Populate PlayDate** in the navbar to import your library and fetch metadata. Game cards appear immediately as placeholders and fill in live as art, metadata, and achievements are fetched in parallel. First-run time depends on library size and Steam's API rate limits.

Additional Steam accounts can be added at any time via **Tools → Account**.

---

## Controls

PlayDate supports gamepads and keyboard navigation — useful for couch / TV setups.

| Input | Action |
|---|---|
| D-pad / Left stick / Arrow keys / WASD | Navigate |
| A / Enter | Confirm / open focused game |
| B / Escape | Back / close modal |
| X / Square | Context menu for focused game |
| Y / Triangle | Edit focused game |
| LB / RB | Previous / next page |
| Start | Launch focused game in Steam |
| Back / Select | Toggle shelf edit mode (Home) |

The controller HUD appears in the bottom-right corner on first gamepad or keyboard input.

---

## Data files

All user data lives next to the executable (or in the project folder when running from source):

| File / Folder | Contents |
|---|---|
| `games.db` | SQLite database — your game library and blacklist |
| `config.json` | Steam accounts (`active_account`, per-account Steam ID and API key), SteamGridDB key |
| `state.json` | Active filters, sort order, shelf layout, saved filters, artwork orientation, card size |
| `theme.json` | CSS variable overrides for custom theming |
| `playdate.log` | Application log (1MB cap, auto-rotated) |
| `static/img/library/vertical/` | Cached vertical capsule art |
| `static/img/library/horizontal/` | Cached horizontal header art |
| `static/img/library/icons/` | Cached game icons |

Data files survive upgrades — they are never overwritten by the installer.

---

## Stack

| | |
|---|---|
| Python / Flask | Backend server and API routes |
| Waitress | Production WSGI server (8 threads) |
| pywebview | Native desktop window — no browser required |
| SQLite | Local game database |
| Jinja2 | Server-side HTML templating |
| Vanilla JS / CSS3 | All frontend logic — no frameworks, no build step |
| requests + BeautifulSoup | Steam metadata, tag scraping, and BLAEO sync |

---

## Building from source (Windows)

Requires Python 3.11, [PyInstaller](https://pyinstaller.org), and [Inno Setup 6](https://jrsoftware.org/isinfo.php).

```bash
pip install -r requirements.txt pyinstaller
pyinstaller playdate.spec
```

Then open `playdate.iss` in Inno Setup to produce `installer/PlayDate-Setup.exe`.

Releases are built automatically via GitHub Actions on version tag push.
