# Release Notes

## v1.5.7 — Pending

### Home Page

- Fixed hover grow effect not working on cards in split-row shelves.

### Backup & Restore

- Backup now includes `theme.json`, `emulators.json`, and `santa_gifts.json` in addition to the existing files.
- Backup modal lists all files included in the backup.
- Clicking "Install Update" now opens a confirmation popup with a "Back Up First" button before proceeding.

### Bug Fixes

- Fixed a crash on upgrade where the v1.5.6 migration would fail with `no such column: meta_fetched` on older databases.
- Fixed Windows portable build failing to launch due to missing `Python.Runtime.dll` in the bundle.
- Fixed several modules (`emulators`, `howlongtobeatpy`, `runners.launch`) missing from the Windows PyInstaller bundle.
