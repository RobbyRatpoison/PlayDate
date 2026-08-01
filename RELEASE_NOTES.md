# Release Notes

## v1.6.12 - 2026-08-01
### New

- Added a "Send Log to Developer" option (System settings) to send your log file straight to the developer for troubleshooting, without needing a GitHub account.
- itch.io and Epic Games account connection now offers a manual fallback for when the sign-in window gets stuck on a site verification page: sign in in your regular browser instead, then paste the resulting key/code directly.

### Fixes

- Fixed backups becoming permanently corrupted ("Invalid zip file" when restoring) if PlayDate was closed while a backup -- especially a large one with cover art included -- was still being saved. The app now waits briefly for an in-progress backup or restore to finish before closing, and shows a warning while a backup is being created telling you not to close PlayDate yet. (reported by PapaSmok)
- Fixed itch.io and IndieGala sign-in popups closing before completing login on the Windows portable build. (reported by ImpAtience)
- Removed the "View on Humble Bundle" link in the edit panel -- it never pointed at a specific game, only your full library page, since Humble doesn't expose a per-game store URL for owned games.
- Fixed "Sync" for IndieGala, Humble, EA App, and Epic Games showing a generic, misleading error (indistinguishable from the game just not being found) when the real problem was your account session expiring -- now clearly tells you to reconnect. itch.io's "Sync" now does the same when a saved API key gets rejected, rather than silently reporting success with nothing actually refreshed.
- Fixed itch.io "Sync" reporting success with nothing actually updated when no itch.io account was connected -- it now clearly says to connect an account.
- Fixed Epic Games store links breaking for some games. New syncs are cleaned up automatically; for games already in your library, use the new "Fix Store Links" button in the Epic Games plugin settings.
