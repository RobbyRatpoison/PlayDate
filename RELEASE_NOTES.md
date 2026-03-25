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

## v1.1.7 — 2026-03-25

### Settings Menu
The Tools page has been removed. All tools are now accessible from a **☰** dropdown in the nav bar, styled to match the HOME / LIBRARY / PICK 6 links.

### Improved Gamepad Navigation
Modals and dropdown lists now have improved gamepad support. Dropdown lists (saved filters, custom selects, the settings menu) can be opened, navigated, and confirmed or dismissed with the controller. Focus is better preserved when entering and exiting dropdowns, and navigation boundaries are more reliably enforced.

---
