# Release Notes

## v1.5.2 — 2026-04-30

### Appearance

- Added a UI Scale slider under Menu → Appearance. Drag to scale the entire interface up or down (75–150%). Useful for 4K and HiDPI displays where text appears too small.

### Library

- Added a toggle under Menu → Library → Completion Sync to control whether games are automatically promoted from Never Played to Unfinished when Steam shows playtime. Disable this if you use BLAEO to manage Never Played status.
- Quick filters are now grouped into two rows: general filters (All Games, Installed, Not Installed, Never Played / Unfinished, Beaten / Completed) and individual status filters (Never Played, Unfinished, Beaten, Completed, Won't Play).

### Installation

- The Linux prerequisites in the README now include `python3-venv`, `python3-pip`, and `python3-tk` for Debian/Ubuntu.
- The Linux installer now shows the actual error output when virtual environment creation fails, with a targeted hint for Debian/Ubuntu users.

### Fixes

- Fixed a startup crash (`no such column: protondb_fetched`) affecting users upgrading from older database versions.
- Fixed the Won't Play quick filter not working.
- Fixed BLAEO sync silently ignoring Won't Play status — games marked Won't Play on BLAEO will now sync correctly (unless the game is already Beaten or Completed in PlayDate).
