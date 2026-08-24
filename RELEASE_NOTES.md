# Release Notes

## v1.7.5
### New

- Expanded the plugin API: plugins can now hook into game launches and library updates, add info to the game detail panel, add right-click menu items, and add Home page widgets. See `PLUGINS.md` for plugin developers.
- Added an opt-in "Require double-click to launch/install" setting for the library grid view (hamburger menu → Library), off by default. Helps avoid accidentally launching or installing a game from a stray click. (suggested by ArchelonGaming)
- Added Delete Game to the game right-click context menu, with the same "just delete or also blacklist" prompt as the edit modal's delete button. (suggested by ArchelonGaming)

### Fixes

- Fixed the card-outline eyedropper (color picker) doing nothing on Linux Flatpak installs under Wayland. It needed Tcl/Tk bundled into the Flatpak (the runtime didn't ship it at all) and, separately, a portal-based screenshot fallback -- PIL's screen-grab call can't read a Wayland-composited desktop no matter what permissions are granted.
