# Release Notes

## v1.8.2 - 2026-08-27
### Improvements

- Simplified connecting a Ubisoft account — it's optional and rarely needed, since most Ubisoft Connect features now work without signing in.

### Fixes

- Fixed some Wine-based plugin installs hanging indefinitely during setup.
- Fixed some Wine-based plugin installs never finishing after the installer itself had already completed.
- Fixed winetricks dependency installation failing for some Proton-based Wine installs.
- The Ubisoft Connect plugin now works on Linux — library sync, install, launch, and uninstall — with no sign-in required. It likely works on Windows too and is ready for testing there. Games owned only through a linked Steam account are skipped, since Ubisoft Connect can't install or launch those itself.
- Fixed cover art on the Home and Pick 6 pages not refreshing after art changes until a full cache clear.
- Fixed EA/Ubisoft install status sometimes not updating right after a bulk rescrape.
- Fixed "Reinstall Launcher" for a plugin sometimes leaving the launcher in a broken restart loop; the old Wine session is now shut down before the prefix is deleted or rebuilt.
- A plugin update that needs a newer PlayDate version is now marked as such in the Plugins list instead of appearing as a normal update that fails when clicked; it can still be installed via "Update PlayDate & Plugins".
- "Check for Updates" now reports available plugin updates too, instead of only saying "up to date" when a plugin update is waiting.
- EA App games now install, launch, and uninstall by opening EA App itself, the same approach Lutris uses.
- Updated a bundled networking library (used for HowLongToBeat lookups) to pick up security fixes.
