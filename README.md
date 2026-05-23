# PlayDate

A local game library manager for people who take their backlog seriously.

Pulls your Steam library and any connected platforms, enriches games with metadata, cover art, and HowLongToBeat times, and gives you a clean interface for browsing, filtering, tracking completion, and deciding what to play next. Runs entirely locally as a standalone desktop app.

---

## Features

- **Library** — grid and list views with live search, sorting, and a powerful filter system (simple dropdowns or nested AND/OR groups with custom SQL). Bulk edit any field across a selection of games.
- **Home page** — configurable shelves driven by any saved filter or built-in preset. Add widgets, pair shelves side-by-side, and set per-shelf limits and sort order.
- **Pick 6** — find something to play. Random mode picks from your full unbeaten library. Smart mode builds a taste profile from your beaten games and scores candidates by tags, reviews, playtime, staleness, and release date.
- **Non-Steam libraries** — connect GOG, itch.io, Humble Bundle, and more via the Plugins menu. Games from all sources appear alongside your Steam library.
- **Emulators** — point PlayDate at your ROM folders and it scans them into your library with automatic cover art.
- **Metadata** — Steam tags, reviews, achievements, release info, and HowLongToBeat times. Playtime and last-played stay in sync with your local Steam files on every launch.
- **Artwork** — vertical capsule art, horizontal headers, and icons; falls back through Steam CDN paths to SteamGridDB. Browse and apply custom art from within PlayDate.
- **Completion tracking** — Never Played, Unfinished, Beaten, Completed, Won't Play. Right-click any card for a quick-set menu.
- **Gamepad support** — full controller navigation across all pages.

---

## Installation

### Windows

Download **PlayDate-Setup.exe** from the [latest release](https://github.com/RobbyRatpoison/PlayDate/releases/latest) and run it. No Python required.

Prefer portable? Download **PlayDate-Windows-Portable.zip**, extract anywhere, and run `PlayDate.exe`.

**Requirements:** Windows 10 or 11 (64-bit). Microsoft Edge WebView2 Runtime is required — it ships pre-installed on Windows 10/11.

### Linux

Install the WebKit/GTK system dependencies for your distro first:

```bash
# Debian, Ubuntu, Mint, Pop!_OS, etc.
sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.0 python3-venv python3-pip python3-tk

# Fedora, Nobara, Ultramarine, etc.
sudo dnf install python3-gobject webkit2gtk4.0

# Arch, Manjaro, EndeavourOS, CachyOS, Garuda, etc.
sudo pacman -S python-gobject webkit2gtk

# openSUSE
sudo zypper install python3-gobject typelib-1_0-WebKit2-4_0
```

Then run:

```bash
chmod +x launch.sh && ./launch.sh
```

On first run, `launch.sh` sets up a virtual environment, installs Python dependencies, and registers a desktop entry so PlayDate appears in your app launcher. After that it just launches. Re-running it after moving the folder keeps the desktop entry up to date.

### Steam Deck

Set a sudo password first if you haven't already:

```bash
passwd
```

Then run:

```bash
chmod +x install_steamdeck.sh && ./install_steamdeck.sh
```

This installs the required system packages and runs the setup. If PlayDate stops launching after a SteamOS system update, re-run `install_steamdeck.sh` — it's safe to run multiple times.

### macOS

```bash
chmod +x launch.sh && ./launch.sh
```

On first run, `launch.sh` sets up the virtual environment and creates a `PlayDate.app` bundle in `~/Applications`. Re-running it after moving the folder keeps the bundle up to date.

---

## Uninstallation

### Windows
Use **Add or Remove Programs** — PlayDate registers a standard uninstaller.

### Linux / macOS
```bash
./uninstall.sh
```
