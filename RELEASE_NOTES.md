# Release Notes

## v1.6.13
### New

- "Open Store Page" in the right-click menu now supports non-Steam games.
- GOG, EA App, Epic Games, Humble Bundle, IndieGala, and itch.io are no longer bundled with PlayDate -- they install automatically if you already had one set up, or via the new "Official Plugins" list in Plugins settings otherwise.

### Fixes

- Fixed IndieGala store links not working for developer-made-free or bundle games. (reported by DarkRainX)
- Fixed Epic Games Launcher getting stuck in an infinite update loop on Linux, which could freeze the system.
- Fixed EA App launcher installs failing after a Proton/Wine update.
- Fixed "Reinstall Launcher" (EA App, Epic Games) sometimes not clearing the old install.
- Fixed uninstalling a plugin not actually sticking -- it would silently come back on the next update.
- Restoring a backup now re-checks installed status and launcher/emulator paths.
- Fixed emulated games' installed status never updating after the initial scan.
