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

## v1.1.16 — 2026-03-31

### New Features
- **Date part filtering** — filter conditions on release date, date added, and last played now support "month is", "day is", and "year is" operators, making it easy to find games released in a specific month or on a particular day without needing a custom SQL expression.
- **AppID filter condition** — AppID is now available as a filterable column in both the filter builder and the PAGYWOSG filter builder.
- **PAGYWOSG filters save as editable trees** — filters saved from the PAGYWOSG builder are now stored as proper filter trees instead of raw SQL, so they can be opened and edited in the advanced filter builder like any other saved filter.

### Improvements
- **Filter modal save/rename/delete** now use an inline dialog instead of browser popups (`prompt`/`confirm`/`alert`), which could hang or misbehave in the desktop window.
- **Ungroup in advanced filter builder** — removing a parent group now promotes its children to the parent level instead of deleting them.
- **Weighted review percentage formula** updated to a continuous confidence-interval approach: scores are pulled toward 50% (neutral) based on review count, with a smooth curve rather than hard thresholds.
- **Library scroll performance** — cards now use a virtual grid with HTML caching, deferred image loading (200ms after scroll, immediate on page load), and paint containment, reducing choppiness when scrolling large libraries.
- **Filter modal height** capped at 82vh with a flexbox fix (`min-height: 0`) so the saved filters row and action buttons are always visible regardless of how many conditions are in the builder.

### Bug Fixes
- Fixed loading a tree-based saved filter in the filter builder not clearing a previously active custom SQL expression, causing the old SQL to silently override the new filter.
- Fixed PAGYWOSG filters with an AppID condition returning 0 results — `appid` was missing from the SQL safety whitelist, causing the entire WHERE clause to be rejected.

---
