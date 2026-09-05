# Release Notes

## v1.10.2
### Improvements

- Wine/Proton game launches can now pass extra command-line arguments and a custom working directory, for plugins that need it.
- EA App, Epic Games, Ubisoft Connect, Battle.net, and Rockstar Games now detect a native Windows install via the system registry, catching custom install locations.
- Epic Games and Ubisoft Connect gained Start Launcher / Open Folder buttons, matching EA App and Battle.net.
- When PlayDate can't confidently pick which file to launch for an itch.io, Humble, or IndieGala game, it now asks — changeable anytime via right-click → Change Executable.

### Fixes

- Restore now stops any bulk jobs before replacing the database.
- Confirming an HLTB match in the edit modal no longer reverts on reopen.
- The Battle.net plugin now works on Linux — library sync, install, launch, and uninstall, no sign-in required. Moved from the beta Plugin Catalog section to the regular one.
- The Amazon Games plugin's account connection and library sync now work. Install/launch/uninstall were rewritten too but are unverified against an owned game — please report back if you have one.
- The Rockstar Games plugin now installs the real launcher under Wine and syncs your library from it directly (no account needed), with install/launch/uninstall handled through it. Only tested against one game so far — please report back what you see.
- Fixed 32-bit Windows games crashing on launch under Wine/Proton from a mismatched graphics library — affects every Wine-based plugin.
- Fixed itch.io, IndieGala, and GOG sometimes picking a 32-bit Linux binary over 64-bit, which doesn't run under the Flatpak build.
- Fixed EA App's Start Launcher button not working under the Flatpak build.
