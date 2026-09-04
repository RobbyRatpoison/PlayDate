# Release Notes

## v1.10.2
### Fixes

- Restore now stops the metadata backfill and any other bulk job before replacing the database, instead of letting it run against files being swapped out.
