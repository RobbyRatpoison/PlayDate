# Release Notes

## v1.5.4 — 2026-05-07

### Installation

- Added `launch.sh` as a single entry point for Linux and macOS. It handles first-time setup automatically and keeps the desktop shortcut up to date if you move the folder.
- Added a portable Windows zip to release builds — extract anywhere under your user folder and run `PlayDate.exe`.
- Fixed Steam Deck installs failing after a SteamOS update due to PGP signature trust errors.
- Fixed the missing-WebKit2GTK error message not appearing on Linux.

### Fixes

- Fixed a startup crash when upgrading from a version before non-Steam library support was added.
