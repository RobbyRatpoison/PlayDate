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

## v1.3.1 — 2026-04-11

### New
- **PAGYWOSG qualification tooltip** — when a PAGYWOSG filter is active on the library page, hovering over any game card shows a tooltip listing its qualifying categories (with win/backlog label and mod-verified attribution) and its HLTB minimum time.
- **PAGYWOSG wins group configuration** — the filter builder now detects whether your library contains a "Won on SteamGifts" group. If not, a warning prompts you to choose a substitute group from your existing groups or confirm you have no SteamGifts wins (which omits the wins branch from the filter). Your choice is saved to `state.json` and pre-filled on all future builds. The quals panel in the edit modal reads the group name from the saved filter tree rather than assuming "Won on SteamGifts".
- **HLTB tool in Tools menu** — HLTB Review has moved from the Bulk Ops modal to a dedicated panel in the Tools menu (hamburger nav), accessible from all pages. The panel now has four collapsible sections: above-threshold unconfirmed, below-threshold unconfirmed, no match found, and confirmed below threshold. No-match games are shown with a search button to find an alternative match.
- **Startup HLTB catch-up scrape** — on launch, after the playtime sync completes, a background pass silently scrapes HLTB data for any games that have never been fetched (does not retry `no_match` games automatically).

### Fixes
- **Home page editor cancel** — clicking "✕ CANCEL" in the home layout editor now fully restores the layout to what it was when editing began. Previously, structural operations (filter changes, splits, unsplits, shelf removal) that auto-saved mid-session were not reverted on cancel.



