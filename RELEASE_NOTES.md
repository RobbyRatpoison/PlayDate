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

## v1.2.5 — 2026-04-05

### New
- **Steam account mismatch check** — the date import userscript now reads the logged-in Steam account from the help page and compares it against the active PlayDate account. If they don't match, the import is aborted with a clear error banner.
- **Tampermonkey script detection** — when starting a bulk date import, PlayDate now waits up to 5 seconds for the userscript to ping back. If no ping is received, the import is automatically cancelled with an error message telling you to install the script or enable Manifest V2.

### Changes
- **Userscript renamed** — `playdate_date_import.user.js` is now `steam_date_import.user.js`
- **Bulk edit modal** — the completion status field now shows a dropdown with all five valid statuses instead of a plain text input; tag, group, genre, and category fields now show a pill input with autocomplete suggestions
- **Filter fix** — custom SQL expressions that divide integer columns (e.g. `unlocked_achievements / total_achievements`) now automatically cast to real arithmetic so the result is a decimal instead of always 0

