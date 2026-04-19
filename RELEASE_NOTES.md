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

## v1.4.2 — 2026-04-19

### Library

- Restored the **✕ CLEAR** button in the library toolbar. It appears whenever a filter or platform filter is active and clears both in one click.

### Filters

- Filter modal dropdowns with more than 20 options now show a search input at the top; type to filter the list, arrow keys to navigate, Enter to select.
- Boolean fields (Installed, Free to Play) now default to "Yes" when adding a new condition row.

### View Options

- Added a **VIEW** button to the library toolbar. Opens a modal with sort order, grid size, grid orientation (vertical/horizontal), group-by, and platform visibility.
- **Group by** option groups games by Installed status, Completion, Release Year, Year Added, Review Score, Weighted Score, or Platform. Groups are collapsible and sorted by the active sort column.

### Release Dates

- Release dates are now read from the local Steam `appinfo.vdf` file. The previous method used the Steam Store API, which returns the Steam launch date — this didn't match the date shown on the store page for games that were released elsewhere first. A one-time background migration corrects existing library entries; progress is tracked and resumes if interrupted.

