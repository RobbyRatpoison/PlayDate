# Release Notes

## v1.5.10 — Pending

### Bug Fixes

- Fixed a startup crash on reboot ("no such column: duplicate_auto") that forced a full reinstall to recover. The column is now added before migration 9 queries it.

### Improvements

- Bulk edit: replace mode now accepts an empty value to clear the field (set to null) for all matching games.
- Bulk edit: remove mode now populates pill suggestions from the values actually present in the current scope, rather than the full library.
