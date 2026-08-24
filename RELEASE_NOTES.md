# Release Notes

## v1.7.5
### New

- Expanded the plugin API: plugins can hook into launches and library updates, add info to the game detail panel, add right-click menu items, and add Home page widgets. See `PLUGINS.md`.
- Added an opt-in "Require double-click to launch/install" setting (Library → Launching), covering Library, Home, and Pick 6. (suggested by ArchelonGaming)
- Added Delete Game to the right-click context menu, with the same delete-or-blacklist prompt as the edit modal. (suggested by ArchelonGaming)
- Added Card Badges: configurable corner icons on game cards for Installed status and/or Platform, using your own uploaded icons. (suggested by ArchelonGaming)
- The edit-pencil button can now show on Home and Pick 6, and its corner is configurable (shares corners with Card Badges).

### Fixes

- Fixed the card-outline eyedropper doing nothing on Linux Flatpak under Wayland.
- Fixed Home's shuffle (🔀) not tracking each game's actual platform.
- Fixed some modal dropdowns rendering inconsistently depending on which page the modal was opened from.
