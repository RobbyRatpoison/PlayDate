# Release Notes

## v1.10.2
### Fixes

- Restoring a backup now stops the automatic metadata backfill (and any other bulk job) first, instead of letting it keep running against the database as it's being swapped out.
