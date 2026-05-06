# TODO

## Unreleased

- Fixed Steam Deck install failing after SteamOS system updates due to PGP signature trust errors
- Added `launch.sh` as a single entry point for Linux and macOS — handles setup automatically on first run and keeps the desktop shortcut/app bundle up to date if the folder is moved
- Added portable Windows zip to GitHub Actions release builds
- Fixed missing WebKit2GTK not showing a friendly error message on Linux

## User requests and other things that need sorting

- Scrape Minimum / Recommended Specs
- Sort by actual / estimated Size On Disk

## Known Bugs

- none

---

## Improvements

- **Gamepad support** — home page editor buttons, bulk edit modal navigation, text input focus, disable RB/LB while in modals *(partial: `clearSuppression()` added; remaining: modal navigation, text input focus)*; controller support is completely broken on Steam Deck

---

## Small Features

- **Steam Deck installation** — see `STEAMDECK_PLAN.md`

---

## Big Features

- none

---

## Under Consideration

- none
