# Release Notes

## v1.5.12

### Improvements

- Game names can now be updated to match Steam's store display name, which sometimes differs from the internal name. After the first launch, any differences are flagged in the hamburger menu. Clicking the notification opens a review list where you can pick which names to update — nothing changes automatically. Keeping names in sync is important for PAGYWOSG, since category sorting uses the store display name.
- PAGYWOSG filter builder: after auto-filling an event, a Personal categories section lists all categories that have a mod-verified game list. Checking a category marks it as personal — games verified for another user in those categories are excluded from the filter and qualifications panel entirely, since eligibility depends on your own history (e.g. "won in June").
- BLAEO sync: completion status downgrades are no longer blocked — if your status on BLAEO differs from PlayDate, BLAEO now wins.
- BLAEO sync: renaming a list on BLAEO will now automatically rename it in your PlayDate library on the next sync instead of creating a duplicate.
- BLAEO sync: the result now shows a breakdown of what changed — which games had their status updated and any lists that were renamed. Details are expandable, and everything is also written to the log.
- Bulk operations (re-scrape, art, ProtonDB, HLTB, date import) now show a progress indicator in the hamburger menu while running. Navigating away and back will resume the progress display and prevent accidentally starting a second operation.
- Blacklist Manager now has a search box to filter by game name.

### Bug Fixes

- Games with no Steam achievements no longer show blank achievement counts after a full library scan.
- Populate progress counter no longer overshoots the total when games with unfetched metadata are visible in the library during a populate run.
- Populate no longer gets stuck in a running state when the library contains games added by plugins that have not yet had metadata fetched.
