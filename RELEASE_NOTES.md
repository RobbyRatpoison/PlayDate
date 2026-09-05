# Release Notes

## v1.10.2
### Improvements

- Wine/Proton game launches can now pass extra command-line arguments and a custom working directory, for plugins that need it.
- EA App, Epic Games, Ubisoft Connect, Battle.net, and Rockstar Games now detect a native Windows install via the system registry, catching custom install locations.
- Epic Games and Ubisoft Connect gained Start Launcher / Open Folder buttons, matching EA App and Battle.net.
- The Rockstar Games plugin now installs the real launcher under Wine, syncs your library from it directly (no account needed), and handles install/launch/uninstall through it. The account-connection popup is still non-functional.
- When PlayDate can't confidently pick which file to launch for an itch.io, Humble, or IndieGala game, it now asks — changeable anytime via right-click → Change Executable.

### Fixes

- Restore now stops any bulk jobs before replacing the database.
- Confirming an HLTB match in the edit modal no longer reverts to the old time/match on reopen; it now stays in sync without needing a page refresh.
- The Battle.net plugin now works on Linux — library sync, install, launch, and uninstall — with no sign-in required; connecting your account adds purchase dates and your full owned-games list on top. It's moved from the beta Plugin Catalog section to the regular one.
- The Amazon Games plugin's account connection and library sync now work, using Amazon's real login flow instead of a fragile cookie scrape. Install/launch/uninstall have been rewritten too, but are still unverified against an actual owned game — if you own games on Amazon, please give it a try and report back.
- Fixed 32-bit Windows games crashing on launch under Wine/Proton from a mismatched graphics library — affects every Wine-based plugin.
- Fixed itch.io, IndieGala, and GOG sometimes picking a 32-bit Linux binary over 64-bit, which doesn't run under the Flatpak build.
- Fixed EA App's Start Launcher button not working under the Flatpak build.
