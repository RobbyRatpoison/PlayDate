# Release Notes

## v1.5.5 — 2026-05-11

### Home Page

- Fixed shuffle shelves ignoring per-shelf platform filters (e.g. a Steam-only shelf could return Epic games on reshuffle).
- Adding a column to a shelf row now creates a new blank column directly instead of requiring an existing shelf to be combined.

### Library

- Fixed the dice button not working in list/details view.

### PAGYWOSG

- The completion status toggles (Never Played, Unfinished, Beaten, Completed) now remember your last selection across sessions.

### Gamepad

- Full gamepad controls are now enabled across the entire app — library, modals, settings, plugins, and Pick 6.
- Added a "Pause gamepad input when launching a game" option in Tools → Gamepad (on by default).
- Fixed a grey circle appearing in the corner of the window when a game closed (KDE/Wayland).

### GOG

- GOG games that use DOSBox now launch correctly via the system dosbox binary instead of failing silently.

### Steam Deck

- Fixed the install script hanging after a SteamOS update.
