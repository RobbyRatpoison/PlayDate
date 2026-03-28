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

## v1.1.11 — 2026-03-28

### Menu Overhaul
The hamburger menu has been reorganized into two dedicated modals — **Settings** and **Tools** — making it easier to find what you're looking for.

**Settings** brings together account configuration and appearance options in one place. You can now update your Steam ID, Steam API key, and SteamGridDB API key directly from the UI, with password-style fields and reveal toggles for the API keys.

**Tools** groups all library utilities into logical sections: backup/restore and import tools, external sync features (PAGYWOSG and BLAEO), and blacklist management.

### Theme Editor Improvements
The theme editor has been overhauled with more granular control — 18 individual CSS variables across grouped categories (Backgrounds, Text, Accent, Borders, Status) replacing the previous coarser set. Each variable has a per-variable reset button to revert individual colors to default without resetting the whole theme.

The live preview has been updated to better reflect the current state of the app, and is larger and easier to read. Closing the theme editor without clicking **Apply Theme** now discards any unapplied changes.

Built-in presets and a saved themes system let you store, load, rename, and delete named themes.

---
