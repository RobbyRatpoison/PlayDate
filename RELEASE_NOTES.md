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

## v1.1.12 — 2026-03-28

### Multiple Steam Accounts
PlayDate now supports multiple Steam accounts. Each account gets its own separate library database, so switching between them never mixes your data.

Account management lives in **Settings → Account**: edit your Steam ID, API key, and nickname label; add additional accounts; or remove ones you no longer need. The Detect button reads your local Steam installation and presents any accounts it finds by persona name — no API key required.

Backup and restore now includes all account databases, and the migration from single-account to multi-account happens automatically on first launch — your existing library is preserved.

### Settings UI
The Account section in Settings is now a dedicated sub-modal, consistent with how Background Image and Theme work. The SteamGridDB key is shared across all accounts and lives in the same modal.

---
