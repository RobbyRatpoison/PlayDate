# Release Notes

## v1.10.2
### Improvements

- Wine/Proton game launches can now pass extra command-line arguments and a custom working directory, for plugins that need it.
- EA App, Epic Games, Ubisoft Connect, Battle.net, and Rockstar Games now detect a native Windows install via the real system registry entry first, instead of only guessing standard install folders — catches a launcher installed to a custom location.
- Epic Games and Ubisoft Connect gained "Start Launcher" / "Open Folder" buttons, matching EA App and Battle.net.
- The Rockstar Games plugin has been substantially rebuilt: Configure Launcher now installs the real Rockstar Games Launcher under Wine, library sync reads directly from the signed-in launcher's own files (no account connection needed), and install/launch/uninstall all work through the launcher itself. The old account-connection popup remains but is still non-functional — use the launcher-based path instead.
- When PlayDate can't confidently tell which file in a freshly-installed itch.io, Humble, or IndieGala game is the one to launch, it now asks instead of silently guessing. This can also be changed anytime afterward via right-click → Change Executable on the game.

### Fixes

- Restore now stops any bulk jobs before replacing the database.
- Confirming an HLTB match in the edit modal no longer reverts to the old time/match on reopen; it now stays in sync without needing a page refresh.
- The Battle.net plugin now works on Linux — library sync, install, launch, and uninstall — with no sign-in required; connecting your account adds purchase dates and your full owned-games list on top. It's moved from the beta Plugin Catalog section to the regular one.
- The Amazon Games plugin's account connection and library sync now work, using Amazon's real login flow instead of a fragile cookie scrape. Install/launch/uninstall have been rewritten too, but are still unverified against an actual owned game — if you own games on Amazon, please give it a try and report back.
- Fixed a bug where launching a 32-bit Windows game through Wine/Proton (common for older titles) could crash before it even started, from loading a mismatched graphics library. Affects every Wine-based plugin.
- Fixed itch.io, IndieGala, and GOG occasionally picking a 32-bit Linux binary over a 64-bit one for the same game when both existed — the 32-bit one doesn't run at all under the Flatpak build. Humble already had this fix.
- Fixed EA App's "Start Launcher" button not working under the Flatpak build.
