# Release Notes

## v1.6.8
### New

- Play or Pay picks now generate a saved filter automatically, matching how PAGYWOSG results work. (prompted by feedback from Blue™)
- Play or Pay offers to clean up the previous cycle's group tag when a new cycle starts.
- The PAGYWOSG filter builder offers to delete old event filters when you save a new one.

### Improvements

- Plugins that need a newer version of PlayDate now show a "needs update" badge in the Plugins menu instead of silently disappearing.
- Sync/scrape operations that hit Steam's rate limit now wait however long Steam actually asks for, instead of guessing.

### Fixes

- Fixed PAGYWOSG tags showing as one combined line in the library hover tooltip and game-edit qualifications panel instead of a separate line per tag. (reported by Blue™)
- Fixed the Edit Game popup silently failing to open for games that qualify for a PAGYWOSG category, if a SteamGifts username was set in Settings. (reported by Blue™)
- Fixed GOG games showing a blank or incorrect review score.
- Fixed GOG's "Fetch metadata" not actually re-fetching games that were already synced, so review scores and other metadata could get permanently stuck.
- Fixed GOG games removed from your account not being cleaned up on the next library sync.
- Fixed a crash when Steam rate-limits a "Sync Steam Data" request; now shows a clear message instead.
- Fixed the gamepad focus highlight not appearing on the update-install confirmation and What's New popups.
