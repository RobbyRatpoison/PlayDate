# Release Notes

## New tools

**Theme Editor** — Customize the look of PlayDate with a CSS variable editor. Adjust colors for backgrounds, text, accents, and more. Live preview panel shows a portrait-aspect game card at 1.75× zoom so you can see changes before applying. Save to `theme.json` or export to a file.

**Background Image** — Upload a custom background image for the home page. Reset button returns to the default gradient.

**Blacklist Manager** — View and manage your blacklist. When deleting a game via the edit modal, you can now opt to blacklist it so it's never re-added by Populate. Existing entries can be removed from the manager.

**Export Library to CSV** — Export your full library (or current filtered view) to a CSV file.

## Library

- **Bulk Rescrape** — Re-fetch metadata for all filtered games or just selected games. New button in the library toolbar alongside Bulk Edit.
- **Bulk Delete** — Permanently remove filtered or selected games from your library (cover images included). Requires confirmation.

## Filter modal

- **SQL syntax highlighting** in the custom SQL editor
- **Column-vs-column conditions** — compare two library columns directly in the filter builder
- **Custom expression** condition type for free-form SQL fragments

## Gamepad support

`input.js` is entirely new. PlayDate now has full gamepad and keyboard navigation suitable for couch/TV/Steam Deck setups.

- **2D spatial grid navigation** across all pages — D-pad, left stick, arrow keys, and WASD move between game cards and interactive elements in a proper row/column grid
- **A** — confirm, click focused element, or launch the focused game card
- **B** — go back / close open modal
- **X** — open the context menu for the focused game (equivalent to right-click)
- **Y** — open the edit modal for the focused game
- **LB / RB** — previous / next page
- **Start** — launch the focused game
- **Back** — toggle home page edit mode on/off (home page only)
- **Right stick** — scroll up and down
- **Modal zone navigation** — focus is trapped inside open modals; navigates rows and columns of interactive elements
- **Custom SELECT picker overlay** — pressing A on any dropdown opens a gamepad-navigable option list (WebKit can't open native dropdowns programmatically)
- **Confirm dialog support** — the reset/confirm popup receives gamepad focus automatically
- **Controller HUD** — appears in the bottom-right corner on first gamepad or keyboard nav input
- **Home page Up/Down alignment** — navigating between rows targets the nearest card by horizontal screen position, including across split rows

## Modals

- PAGYWOSG builder, Blacklist Manager, and Theme Editor are modal overlays (no longer embedded page sections)
- **Escape key** closes any open modal
- **Click outside** closes any open modal
- **X close buttons** added to all modals that were missing them

## Weighted review percentage

- Fixed scoring cutoff — games with ≤10 reviews now correctly score 0 (was miscalculated)
- Revised scoring curve: less punishing, starts at 0.5 factor at 10 reviews

## Search bar

- Fixed: searching no longer drops the active saved/builtin filter context
- Fixed: search bar pre-populates from an active name LIKE condition in the filter tree on page load
- Fixed: search query no longer wraps in extra wildcards on repeated use

## Fixes (since last release)

- Fixed game launching
- Fixed edit modal
- Fixed free-to-play game scraping
- Fixed achievement syncing
- Fixed fullscreen behavior
- Fixed backup save dialog
- Fixed custom sort dropdown
