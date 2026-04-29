# Release Notes

## v1.5.0 — 2026-04-29

### Plugins

- GOG support is now an optional plugin. The GOG and Epic Games plugins are included and update automatically from GitHub.
- Additional plugins can be installed via zip file or GitHub URL.
- Hamburger → Plugins manages installed plugins. An orange dot appears when plugin updates are available.

### Epic Games

- Connect your Epic Games account via Plugins → Epic Games → Manage. Sync your library to import games, cover art, tags, ratings, and store metadata.
- Games launch via the Epic Games Launcher — natively on Windows/Mac, or via a Wine prefix on Linux.
- On Linux, games can be uninstalled directly from PlayDate. On Windows/Mac, use the Epic Games Launcher to uninstall.

### Library

- New sort option: Total Reviews.

### Fixes

- PAGYWOSG & BLAEO renamed from "Community" in the hamburger menu.

---

## v1.4.5 — 2026-04-26

### Card Outlines

- Game cards can now display coloured outlines driven by configurable rules. Each rule pairs a colour with a filter (built-in preset, saved filter, or custom). The highest-priority matching rule wins per card.
- Default rules ship pre-configured with BLAEO completion status colours.
- Per-page toggles let you enable or disable outlines independently on Library, Home, and Pick 6.
- The dice button in the Library glows with the picked game's outline colour.
- The native colour picker (broken in this environment) has been replaced with a custom one: hue/saturation/value controls, hex input, palette swatches, and a screen eyedropper.

### Edit Modal

- Stats is now the first tab and opens by default; Info is second.
- HLTB times now appear in both the Stats and Info tabs.
- Stats tab fields reorganised into a cleaner grid layout.
- Fixed: 0 playtime now shows as 0.0 hours instead of a blank field.

### Community

- New **Secret Santa / Snowballs** gift list — track games received as Discord event gifts. The PAGYWOSG filter builder gains an option to include these gifts as wins in the generated filter.

### Library

- Duplicate detection platform priority is now configurable via a drag-to-reorder list in the Library modal (Duplicates section).

### Fixes

- Fixed GOG game descriptions not loading in List view.
- Fixed tooltips throughout the app being clipped or mispositioned (particularly the API key tooltip in the account modal).
- Reduced likelihood of a phantom window appearing on secondary monitors when launching games.
