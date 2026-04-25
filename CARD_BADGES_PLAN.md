# Card Badges — Implementation Plan

Show up to 3 colored dot badges across the bottom of game cards, driven by saved filters. User-configurable -- any saved filter can be assigned a color and shown as a badge.

## Data (`state.json`)

- Saved filters gain an `id` field (UUID). Auto-migrated on load: bare filter trees get wrapped as `{ "id": "...", "tree": {...} }`.
- New top-level `card_badges` array. Each entry: `{ "id", "filter_id", "color", "priority", "show_on": { "library", "home", "pick6" } }`.

## Behavior

- Up to 3 badges shown per card, in priority order (lowest priority number = highest priority).
- Evaluated server-side by reusing the existing filter→SQL pipeline -- badge-matching appids are computed alongside the grid query.
- Rendered as CSS colored dots (`border-radius: 50%`) in a row along the bottom of the card.
- `show_on` flags control which of the three card surfaces display badges: Library grid, Home page shelves, Pick 6.

## UI (Card Settings section in Settings page)

- List of badge rules: saved filter name (resolved from `filter_id`) → color picker → page toggles (Library / Home / Pick 6) → drag-to-reorder priority → delete button.
- "Add Rule" button -- opens a picker for an existing saved filter + color.
- When deleting a saved filter that has one or more badge rules referencing it, show a warning.
