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
# Debian, Ubuntu, Mint, Pop!_OS, etc.
sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.0

# Fedora, Nobara, Ultramarine, etc.
sudo dnf install python3-gobject webkit2gtk4.0

# Arch, Manjaro, EndeavourOS, CachyOS, Garuda, etc.
sudo pacman -S python-gobject webkit2gtk

# openSUSE
sudo zypper install python3-gobject typelib-1_0-WebKit2-4_0
```

### macOS
```bash
chmod +x install.sh && ./install.sh
```

**Requirements:** Python 3.10+. pywebview should work out of the box on recent macOS versions. macOS support is present but not yet fully tested.

---

## v1.4.3 — 2026-04-21

### Menu

- The hamburger menu now has direct entries for **Accounts**, **Appearance**, **Library**, **Community**, **Data**, **System**, and **Manage**, replacing the old Settings and Tools buttons. Each opens a focused modal for that area.

### Pick 6

- Added soft bound relaxation: if the active filters produce a pool smaller than 12 games, bounds loosen in 5% steps until at least 6 games are available. A warning is shown when this happens.

### Fixes

- Context menu completion status submenu no longer goes off the right edge or bottom of the screen.
- Right-clicking an area with no menu options now closes any open context menu.
- Release date migration no longer restarts on every launch after completing.


