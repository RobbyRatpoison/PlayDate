# TODO

## Pending (next release)

- none

## User requests and other things that need sorting

- none

## Known Bugs

- **Ghost tooltip circle on secondary monitor** — a gray circle appears in the top-left corner of the secondary monitor. When hovering over elements in PlayDate, the tooltip renders at the circle's position first before snapping into the window. Multiple fix attempts failed.
- **PlayDate on Steam Deck** — controller support is completely broken

---

## Improvements

- **Gamepad support** — home page editor buttons, bulk edit modal navigation, text input focus, disable RB/LB while in modals *(partial: `clearSuppression()` added; remaining: modal navigation, text input focus)*
- **Simplify code** — files remaining: library.py, uninstall.py, images.py, playdate.js, input.js, style.css, and all html files

---

## Small Features

- **PAGYWOSG Snowballs / Secret Santa support** — Snowballs and Secret Santa are PAGYWOSG/POP gift events. The filter builder and quals panel should recognise their pool/criteria structure the same way the main PAGYWOSG event does.
- **Cross-platform duplicate priority order** — when a game is owned on multiple platforms, the duplicate hider should show the version from whichever platform ranks highest in a user-configurable priority list. Currently it always prefers Steam (GOG copies are hidden if the same game exists on Steam). Should support drag-to-reorder platform priority in Settings.
- **Steam Deck installation** — see `STEAMDECK_PLAN.md`

---

## Big Features

- **Plugin system / non-Steam library support** — see `PLUGIN_SYSTEM_PLAN.md`

---

## Potential / Under Consideration

- **Sort by total reviews** — sort by `total_reviews` to surface popular games or find obscure ones. Already in `SAFE_COLUMNS`, just needs a dropdown option.
- **Extend Playnite import** — also import completion status
