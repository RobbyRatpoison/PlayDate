# Release Notes

## v1.10.2
### Improvements

- Wine/Proton game launches can now pass extra command-line arguments and a custom working directory, for plugins that need it.

### Fixes

- Restore now stops any bulk jobs before replacing the database.
- Confirming an HLTB match in the edit modal no longer reverts to the old time/match on reopen; it now stays in sync without needing a page refresh.
- The Battle.net plugin now works on Linux — library sync, install, launch, and uninstall — with no sign-in required; connecting your account adds purchase dates and your full owned-games list on top. It's moved from the beta Plugin Catalog section to the regular one.
- The Amazon Games plugin's account connection and library sync now work, using Amazon's real login flow instead of a fragile cookie scrape. Install/launch/uninstall have been rewritten too, but are still unverified against an actual owned game — if you own games on Amazon, please give it a try and report back.
