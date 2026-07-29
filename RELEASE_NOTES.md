# Release Notes

## v1.6.9
### New

- Added an in-app Tutorial, covering every part of PlayDate: Getting Started, Home & Shelves, Library & Filters, Pick 6, PAGYWOSG, Plugins, Emulators, and Gamepad & Settings. Shows automatically the first time you finish setup (and once for existing installs updating to this version), and is available anytime afterward from the hamburger menu.

### Fixes

- Fixed the update-install confirmation suggesting a backup every single time, even seconds after you'd just made one. Now skips that nudge for 24 hours after a completed backup. (suggested by fernandopa)
- Fixed "Hide duplicate entries" not applying to Home page shelves; only the Library page was actually honoring it. (reported by DarkRainX)
- Fixed GOG games' release dates sorting incorrectly - GOG games would cluster before or after every Steam game instead of interleaving by actual date. (reported by DarkRainX)
- Improved IndieGala library sync to no longer stop after the first page for larger libraries.
- Fixed importing a library backup with "normalize dates" enabled potentially scrambling date-added/release-date sort order, the same underlying issue as the GOG date fix above.
