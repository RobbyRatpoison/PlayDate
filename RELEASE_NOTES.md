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

## v1.1.2 — 2026-03-22

### Changes
- **Steam API key is now required** — Steam's authentication wall broke unauthenticated access to the games list, which also caused Populate PlayDate to fail for users without a key. The config form now requires an API key upfront, with a direct link to get one free in ~2 minutes.
- **Library populates automatically on startup** — Populate PlayDate runs once per session in the background on launch, and immediately after first-time setup completes.
- **Config modal re-opens for existing users without an API key** — upgrading users are prompted to add their API key, with existing Steam ID and SteamGridDB key pre-filled.
- **Restore from backup added to config screen** — users can skip setup entirely by restoring a previous backup directly from the configuration modal.

### Tools Page
- Reordered: Edit Home Layout → Blacklist Manager → Backup & Restore → Import DB → Background Image → PAGYWOSG → BLAEO Sync → CSV Export → Theme Editor

### Internal
- Removed F9 gamepad debug overlay

---
