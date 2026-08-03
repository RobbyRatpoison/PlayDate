# Release Notes

## v1.7.0
### New

- "Open Store Page" in the right-click menu now supports non-Steam games.
- GOG, EA App, Epic Games, Humble Bundle, IndieGala, and itch.io are no longer bundled with PlayDate -- they install automatically if you already had one set up, or via the new Plugin Catalog in Plugins settings otherwise.
- Ubisoft Connect, Amazon Games, Battle.net, and Rockstar Games are now available as beta plugins from the Plugin Catalog -- unfinished and not confirmed working everywhere, but feedback (especially from Windows users) is welcome.
- The Plugin Catalog now shows whether each plugin is known to work, untested, or broken on your OS.

### Fixes

- Fixed IndieGala store links not working for developer-made-free or bundle games. (reported by DarkRainX)
- Fixed Epic Games Launcher getting stuck in an infinite update loop on Linux, which could freeze the system.
- Fixed EA App launcher installs failing after a Proton/Wine update.
- Fixed "Reinstall Launcher" (EA App, Epic Games) sometimes not clearing the old install.
- Fixed uninstalling a plugin not actually sticking -- it would silently come back on the next update.
- Restoring a backup now re-checks which of your games are actually installed, plus launcher and emulator paths.
- Fixed emulated games' installed status never updating after the initial scan.
