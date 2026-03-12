# PlayDate

A local Steam library manager for people who take their backlog seriously.

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

---

## What it does

PlayDate pulls your Steam library, enriches it with metadata (tags, reviews, achievements, cover art), and gives you a clean interface for browsing, filtering, tracking completion, and deciding what to play next. Runs entirely locally as a standalone desktop app — no browser, no cloud, no account required.

---

## Features

- **Library grid** — virtual renderer handles 2000+ games without performance issues. Sort, search, and filter by any column.
- **Filter system** — simple and advanced modes (nested AND/OR groups), custom SQL mode, and saved named filters.
- **Home page shelves** — configurable rows of games (recently added, installed, shuffle, etc.). Drag to reorder, set limits, col widths, and dedup priority across shelves.
- **Pick 6** — randomly or intelligently pick games from your library. Smart and Weighted modes build a taste profile from your completion history.
- **Metadata scraping** — pulls tags, review scores, playtime, achievements, release dates, developers, and cover art from Steam. SteamGridDB supported for custom artwork.
- **BLAEO sync** — imports completion statuses and list tags from your BLAEO backlog profile.
- **PAGYWOSG filter builder** — build this month's eligible pool from the monthly post criteria and save it as a library filter.
- **Backup & restore** — export a timestamped zip of your library data and settings, with optional cover art. Restore from any previous backup.
- **Database import tool** — copy columns from an older PlayDate database into your current library, with column mapping and type-mismatch warnings.
- **Gamepad & keyboard navigation** — full controller support with spatial grid navigation and a HUD that appears on first input.
- **Tools page** — tag migration, BLAEO sync, layout editor, backup/restore, and database import all in one place.

---

## Installation

### Windows

Download **PlayDate-Setup.exe** from the [latest release](https://github.com/your-username/playdate/releases/latest) and run it. The installer handles everything — no Python required.

### Linux

```bash
chmod +x install.sh && ./install.sh
```

Requires Python 3.10+ and `python3-gi` (WebKit/GTK):
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

This removes the launcher, virtual environment, and app launcher entry. Your data files (games.db, config.json, state.json) are left in place by default — the uninstaller asks before removing them.

---

## First-time setup

On first launch you'll be prompted for:

- **Steam ID** — your SteamID64 or vanity URL name (find it at [steamid.io](https://steamid.io))
- **Steam Web API Key** — from [steamcommunity.com/dev/apikey](https://steamcommunity.com/dev/apikey)
- **SteamGridDB API Key** — *(optional — enables custom artwork from SteamGridDB)*

Then hit **Populate PlayDate** to import your library and fetch metadata.

---

## Controls

PlayDate supports gamepads and keyboard navigation — useful for couch / TV setups.

| Input | Action |
|---|---|
| D-pad / Left stick / Arrow keys / WASD | Navigate |
| A / Enter | Confirm / launch focused game |
| B / Escape | Back / close modal |
| X / Square | Open edit modal (Library) |
| Y / Triangle / F | Open filters (Library) |
| LB / RB | Previous / next page |
| Start | Launch focused game |
| 1 / 2 / 3 / 4 | Jump to Home / Library / Pick / Tools |

The controller HUD appears in the bottom-right corner on first gamepad or keyboard nav input.

---

## Stack

| | |
|---|---|
| Python / Flask | Backend server and API routes |
| Waitress | Production WSGI server |
| pywebview | Native desktop window (no browser needed) |
| SQLite | Local database (`games.db`) |
| Jinja2 | Server-side HTML templating |
| Vanilla JS / CSS3 | All frontend logic — no frameworks |
| requests + BeautifulSoup | Steam metadata scraping |
| Selenium | BLAEO scraper (requires Chrome) |

---

## Building from source (Windows)

Requires Python 3.11, [PyInstaller](https://pyinstaller.org), and [Inno Setup 6](https://jrsoftware.org/isinfo.php).

```bash
pip install -r requirements.txt pyinstaller
pyinstaller playdate.spec
```

Then open `playdate.iss` in Inno Setup to produce `installer/PlayDate-Setup.exe`.

Releases are built automatically via GitHub Actions on version tag push:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

---

## Data files

All user data lives next to the executable (or in the project folder when running from source):

| File | Contents |
|---|---|
| `games.db` | Your game library |
| `config.json` | Steam credentials and settings |
| `state.json` | Filters, sort order, shelf layout |
| `playdate.log` | Application log |
| `static/img/library/` | Downloaded cover art |
