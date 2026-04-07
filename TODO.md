# TODO

## Known Bugs

- **Artwork source columns not set** — `vertical_art_source`, `horizontal_art_source`, `icon_source` are unset for existing games; likely broken during the populate speed overhaul

---

## Short Term

- **Library UI polish** — bulk edit improvements (an "all games" option, UI lockout during scraping), group-by functionality, reorder dropdown lists
- **Bulk rescrape optimization** — port populate's concurrent worker pools, `RateLimitedError` handling/backoff, and cancellation support to the bulk rescrape route (currently sequential, blocking, no rate limit recovery)
- **Initial config UX** — label the Steam API key as "recommended" instead of "optional", and add a brief note explaining what it enables (achievement tracking, more accurate library import via `GetOwnedGames`)
- **Sync Store button auto-complete** — if `unlocked_achievements == total_achievements` after a sync, automatically set `completion_status` to `'Completed'`

---

## Long Term

- **Non-Steam library support** — Epic, GOG, Ubisoft Connect, EA App, emulation
- **Plugin system**

---

## Potential / Under Consideration

- **Gamepad support improvements** — home page editor buttons, bulk edit modal navigation, text input focus, disable RB/LB while in modals
- **HLTB integration** — data reliability concerns
- **Extend Playnite import** — also import completion status
- **Refactor app.py into Flask blueprints** — by area (library, scraping, config, import tools)

---

## Planned Features (with implementation notes)

### Card Badges

Show up to 3 colored dot badges across the bottom of game cards, driven by saved filters. User-configurable — any saved filter can be assigned a color and shown as a badge.

**Data (`state.json`):**
- Saved filters gain an `id` field (UUID). Auto-migrated on load: bare filter trees get wrapped as `{ "id": "...", "tree": {...} }`.
- New top-level `card_badges` array. Each entry: `{ "id", "filter_id", "color", "priority", "show_on": { "library", "home", "pick6" } }`.

**Behavior:**
- Up to 3 badges shown per card, in priority order (lowest priority number = highest priority).
- Evaluated server-side by reusing the existing filter→SQL pipeline — badge-matching appids are computed alongside the grid query.
- Rendered as CSS colored dots (`border-radius: 50%`) in a row along the bottom of the card.
- `show_on` flags control which of the three card surfaces display badges: Library grid, Home page shelves, Pick 6.

**UI (Card Settings section in Settings page):**
- List of badge rules: saved filter name (resolved from `filter_id`) → color picker → page toggles (Library / Home / Pick 6) → drag-to-reorder priority → delete button.
- "Add Rule" button — opens a picker for an existing saved filter + color.
- When deleting a saved filter that has one or more badge rules referencing it, show a warning.
