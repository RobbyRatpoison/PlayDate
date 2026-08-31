# Release Notes

## v1.9.1

### Improvements

- Metadata backfill now covers Steam games, not just non-Steam ones.

### Fixes

- Metadata backfill retries games that were tried before but still have missing fields.
- Renaming a game re-runs its metadata match.
- HowLongToBeat "Confirm all above threshold" no longer freezes partway through when the site is slow.
- Games marked as having no HowLongToBeat page stay that way after a restart.
