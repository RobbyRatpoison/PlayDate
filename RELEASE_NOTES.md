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

## v1.1.6 — 2026-03-25

### New Features
- **New values added via pill fields are immediately available.** After saving a game, any new tags, groups, genres, or categories you entered are instantly available in both the edit modal's autocomplete suggestions and the filter builder — no reload required.

### Bug Fixes
- **Dropdown menus no longer stay open when switching programs.** All dropdown lists have been replaced with custom-built menus that respect window focus — they close immediately when you switch to another app.
- **Horizontal grid no longer shows the wrong image after saving.** Editing a game while in horizontal view previously reloaded the card with the vertical image. It now uses whichever orientation is active.

### Improvements
- **Horizontal card size slider now works consistently.** The card size slider previously made horizontal game cards much smaller than vertical ones at the same setting. The slider now controls card height uniformly across both orientations.
- **Populate no longer refreshes the page unnecessarily.** The page only reloads after a populate run if at least one new game was added.
- **Pill input fields now show how to add values.** Tags, groups, genres, and categories fields display a hint explaining that you can type a value and press Enter to add it.

---
