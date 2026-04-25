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

## v1.4.4 — 2026-04-25

### Library

- Added **List view** as a third display mode alongside Vertical and Horizontal. Switch to it via the VIEW modal — the art orientation toggle is now a three-button group. List view shows a scrollable game list on the left with a resizable divider and a detail panel on the right. The detail panel shows cover art, an on-demand game description, and all editable fields from the edit modal. Group-by is supported with collapsible section headers. Rows outside the viewport are unloaded so performance stays consistent regardless of library size. Right-clicking a row opens the standard context menu. The last selected game is remembered when navigating away and back.

### Fixes

- Fixed update download silently hanging on SSL certificate verification failures; now retries with verification disabled, and shows an error with a manual download link if the retry also fails.
- Fixed games with no release date falsely matching date-based filter conditions (month, day, year).
- Fixed account modal API key tooltip being clipped by the modal edge.

### Other

- Gamepad navigation is temporarily disabled while it is reworked. It will return in a future update.


