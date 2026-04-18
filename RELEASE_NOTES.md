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

## v1.4.1 — 2026-04-18

### New

- **Gamepad Diagnostics** — Settings > Testing now has a "Gamepad Diagnostics" button. The panel shows whether a controller is detected, whether input suppression is stuck (with a one-click Clear button to fix it), and a live view of every button and both analog sticks. Useful for diagnosing controller issues on Steam Deck and other gamepad setups.
- **UI scales with window size** — All text, buttons, inputs, and modals now scale proportionally with the window width. The interface looks correct from small windows up to large ultrawide displays, including Steam Deck's 1280×800 screen.
- **Resize to Steam Deck button** — Settings > Testing has a button to snap the window to 1280×800 for testing the Steam Deck layout on desktop.
- **Library random pick** — New dice button (🎲) in the library toolbar picks a random game from your current filtered list and smoothly scrolls to it with a glow highlight.
- **Library platform filter** — New "PLATFORMS" button in the library toolbar lets you show or hide games from specific platforms. Only appears when you have games from more than one platform.
- **Per-shelf platform filter** — In home page edit mode, each shelf now has platform toggle buttons so you can control which platforms appear on individual shelves.
- **Pick 6 minimum/maximum bounds** — Weighted mode now shows a threshold input next to each active slider. Positive weights get a minimum bound (e.g. review score ≥ 70); negative weights get a maximum bound (e.g. HLTB ≤ 3 hours). Games outside the bounds are excluded from the pick. Smart mode automatically applies a review score floor of 70%.
- **GOG install progress in navbar** — When a GOG game is installing, a progress bar appears in the hamburger menu showing the game name, MB downloaded, and percentage. Clicking it cancels the install.
- **CSV column picker** — The CSV export now has a collapsible column picker. All 17 columns are selected by default; uncheck any you don't want.

### Fixes

- **BLAEO sync no longer downgrades completion** — Syncing BLAEO will not overwrite a higher completion status with a lower one (e.g. "Beaten" will not be replaced by "Unfinished"). "Won't Play" is never touched by BLAEO sync.
- **GOG install status auto-syncs** — The GOG games folder is now watched for changes. Installed/uninstalled status updates automatically without needing a manual sync.
- **Launching a game no longer reloads the page** — After launching, the library card updates in place and recently-played shelves refresh in the background.
- **Completion pie stays circular** — The completion pie widget on the home page now stays a circle in narrow or wide split-row shelf configurations.
- **Cover art change persists after scrolling** — Updating a game's cover art in the edit modal now stays visible if you scroll away and back.
- **PAGYWOSG tooltip hides on mouse leave** — The qualification tooltip now dismisses when the mouse leaves the browser window.
- **PAGYWOSG quals preserved while searching** — Applying a search in the library no longer strips PAGYWOSG qualification data from the active filter.
- **PAGYWOSG quals panel cleanup** — The name search condition is no longer shown in the qualifications panel or hover tooltip.

### Changed

- **Pick 6 result cards** — Each result card now shows the game's name and a short explanation of why it was picked (top scoring factors: tags, review score, staleness, release year, HLTB length).
- **Pick 6 weights panel collapsed by default** — The sliders panel starts collapsed; clicking Pick 6 also collapses it so result cards have more room.
- **Library select mode** — The standalone SELECT button has been removed. Select mode is now entered via the "Pick games →" scope option inside the Bulk Ops and Delete modals. Active selections show as a badge next to the BULK OPS button.
- **Duplicate hide setting moved** — The toggle for hiding duplicate games has moved from the library toolbar to the Library section of Settings.
- **Bulk edit date fields** — Date columns in bulk edit (Date Added, Release Date, Last Played) now accept YYYY-MM-DD input.
