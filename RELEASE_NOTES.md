# Release Notes

## v1.8.2
### Improvements

- Simplified connecting a Ubisoft account — it's optional and rarely needed, since most Ubisoft Connect features now work without signing in.

### Fixes

- Fixed some Wine-based plugin installs hanging indefinitely during setup.
- Fixed some Wine-based plugin installs never finishing after the installer itself had already completed.
- Fixed winetricks dependency installation failing for some Proton-based Wine installs.
- Fixed Ubisoft Connect games failing to install or launch entirely.
- Fixed installing or launching a different Ubisoft game while one was already open doing nothing.
- Fixed the Ubisoft "Sync" button always failing without a fully signed-in account.
- Fixed some owned Ubisoft games never appearing in the library.
- Fixed some Ubisoft games showing a garbled placeholder name.
- Fixed uninstalling a Ubisoft game from PlayDate doing nothing.
- Ubisoft games only owned through a linked Steam account are no longer imported, since Ubisoft Connect can't actually install or launch them itself.
- Fixed cover art on the Home and Pick 6 pages not refreshing after art changes until a full cache clear.
- Fixed non-Steam games with a separate launcher client (Ubisoft Connect, EA App) silently failing to launch when that client was already running in the background, with no error shown.
- Fixed clicking Launch or Install multiple times in quick succession on a non-Steam game potentially leaving that platform's Wine setup in a broken state until the launcher process was manually closed.
- Fixed EA/Ubisoft install status sometimes not updating right after a bulk rescrape.
- Fixed "Reinstall Launcher" for a plugin sometimes leaving the launcher in a broken restart loop; the old Wine session is now shut down before the prefix is deleted or rebuilt.
- A plugin update that needs a newer PlayDate version is now marked as such in the Plugins list instead of appearing as a normal update that fails when clicked; it can still be installed via "Update PlayDate & Plugins".
- EA App games now install, launch, and uninstall by simply opening EA App itself, same as Lutris — fixes a "you don't have access" error EA Desktop threw for some classic titles when PlayDate tried to trigger them directly.
