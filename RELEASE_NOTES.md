# Release Notes

## v1.7.5
### New

- Expanded the plugin API: plugins can now hook into game launches and library updates, add info to the game detail panel, add right-click menu items, and add Home page widgets. See `PLUGINS.md` for plugin developers.
- Added an opt-in "Require double-click to launch/install" setting for the library grid view (hamburger menu → Library), off by default. Helps avoid accidentally launching or installing a game from a stray click. (suggested by ArchelonGaming)
- Added Delete Game to the game right-click context menu, with the same "just delete or also blacklist" prompt as the edit modal's delete button. (suggested by ArchelonGaming)
- Added Card Badges: small corner icons on game cards for Installed status and/or Platform, configurable per page (Library/Home/Pick 6) from the Appearance menu → Card Badges. Icons are your own uploads (upload one per platform you use), with a text-label fallback for platforms without one. (suggested by ArchelonGaming)
- The edit-pencil button can now be shown on Home and Pick 6, not just Library, and its corner is configurable from Appearance → Edit Button. It shares the same four corners as Card Badges -- whichever one it occupies becomes unavailable to badges, and vice versa.

### Fixes

- Fixed the card-outline eyedropper (color picker) doing nothing on Linux Flatpak installs under Wayland. It needed Tcl/Tk bundled into the Flatpak (the runtime didn't ship it at all) and, separately, a portal-based screenshot fallback -- PIL's screen-grab call can't read a Wayland-composited desktop no matter what permissions are granted.
- Fixed Home's shuffle (🔀) not tracking each game's actual platform, silently treating every shuffled game as Steam.
- Fixed some modal dropdowns (Startup Page, PAGYWOSG refresh interval, etc.) rendering with different, unstyled appearance depending on which page the modal was opened from.
