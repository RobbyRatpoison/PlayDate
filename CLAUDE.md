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
| `scrapers.py` | Steam API + HTML scraping for library/metadata import |
| `utils.py` | Steam path detection, install status sync, filesystem watcher |
| `images.py` | Cover art download chain (Steam capsule → SteamGridDB → header) |
| `imports.py` | Old-database migration tool |
| `install.py` | Cross-platform GUI installer (tkinter) |

**Frontend:** Vanilla JS + CSS3 in `static/`, Jinja2 templates in `templates/`. No build step, no framework.

## Data Persistence

All user data lives next to the executable (or project root when running from source):

| File | Contents |
|------|----------|
| `games.db` | SQLite — `games` and `blacklist` tables |
| `config.json` | Steam API key + SteamID |
| `state.json` | Active filters, shelf layout, sort order |
| `theme.json` | CSS variable overrides |
| `playdate.log` | Application logs |
| `static/img/library/{appid}.jpg` | Cached cover art |

`database.py` auto-adds missing columns on startup — no manual migrations needed.

## Filter System

Filters are a recursive JSON tree of AND/OR groups with conditions. They get compiled to SQL `WHERE` clauses by `library.build_tree_sql()`.

**SQL safety:** All user-supplied SQL passes through `is_safe_sql()` in `library.py`, which uses column/keyword/function whitelists and rejects all DML/DDL. Parameterized queries are used everywhere else.

## Key Patterns

- **Long-running operations** (library import, scraping) run in daemon threads with `threading.Event` for cancellation (`_populate_cancel` in `app.py`). Progress is reported via a callback that updates a shared dict polled by the frontend.
- **PyInstaller compatibility:** Use `sys.frozen` / `sys._MEIPASS` checks (already in `main.py` and `config.py`) whenever resolving file paths — don't use `__file__` for runtime assets.
- **Steam rate limiting:** `scrapers.py` enforces a 1.2s delay between API calls. Don't remove this.
- **Graceful degradation:** No API key → public profile HTML scraper. No SteamGridDB key → Steam covers. Missing watchdog → continues without filesystem watcher.
- **Pick 6 scoring:** Six weighted signals (tag similarity, reviews, staleness, completion bias, playtime, recency) are combined in `app.py`; beaten games build a taste profile used for tag cosine similarity.
