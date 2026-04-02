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

## v1.2.2 — 2026-04-02

### Bug fixes
- **Fixed: application log not being written on Windows** — `playdate.log` was being written into the PyInstaller temporary extraction folder instead of next to the `.exe`, making it invisible. Errors during populate and other operations were silently disappearing as a result. The log now correctly appears in the install folder.
- **Fixed: gamepad inputs leaking out of launched games into PlayDate** — PlayDate continued polling the gamepad while a game was running, causing buttons pressed in-game to register as PlayDate inputs (launching additional games in the background). The gamepad poller now pauses when the PlayDate window loses focus and resumes cleanly when you return to it.

### Improvements
- **Windows installer now defaults to `C:\Users\<you>\PlayDate`** — previously defaulted to a folder inside AppData which caused errors for some users. You can still choose any location during install.
