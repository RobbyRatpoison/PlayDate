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
- Added a "Pause gamepad input when launching a game" option in Menu → System (on by default).
- Added a Gamepad Controls screen (Menu → System → Gamepad Controls) to remap any action to a different physical button. Default layout: A=Confirm, B=Back, X=Context Menu, Y=Filter/Search, LB=Previous Page, RB=Next Page, Back=Open Menu, Start=System, D-pad=Navigate.
- Fixed a grey circle appearing in the corner of the window when a game closed (KDE/Wayland).

### GOG

- GOG games that use DOSBox now launch correctly via the system dosbox binary instead of failing silently.

### Steam Deck

- Fixed the install script hanging after a SteamOS update.
