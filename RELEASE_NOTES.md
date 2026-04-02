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

## v1.2.0 — 2026-04-01

### Improvements
- **Uninstaller overhaul** — the uninstaller now defaults to deleting the entire PlayDate folder, which is the behaviour you'd expect from any normal program uninstall. Individual user data files (`config.json`, `state.json`, `theme.json`, `games.db`, `playdate.log`) are still presented as opt-out checkboxes if you want to keep them. `theme.json` was previously missing from the list entirely and has been added. Folder deletion is deferred until after the uninstaller window closes so the script can finish cleanly.
- **Update checker moved to hamburger menu** — the Check for Updates / Install Update button has been moved from the Settings modal to the bottom of the hamburger menu, where it's more accessible. The Auto-check Updates toggle remains in Settings. The notification dot on the hamburger button is now dismissed the first time you open the menu — it alerts you once, then gets out of the way.
- **Linux: missing WebKit2GTK is now caught and explained** — if WebKit2GTK isn't installed, the installer catches it specifically (previously it only checked for the base GObject bindings, which can be present without WebKit). If you skip the installer and run `main.py` directly, a clear error dialog now appears with the exact install command for your distro instead of a cryptic crash.
- **Navbar** — Pick page link renamed to "PICK 6".

---
