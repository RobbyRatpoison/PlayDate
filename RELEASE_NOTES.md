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

## v1.2.3 — 2026-04-03

### New
- **Filter Import / Export** — save any filter to a `.json` file and import it on another machine or share it with others. Available under Tools → Filter Import / Export.

### Bug fixes
- **Fixed: populate failing on Windows for some users** — ACF manifest files containing game names with non-ASCII characters (e.g. Japanese, Chinese) caused a `UnicodeDecodeError` that crashed the entire populate operation.
- **Fixed: fullscreen state not saving on exit** — toggling fullscreen and then closing the app would revert to fullscreen on next launch. The state is now saved reliably on close.
