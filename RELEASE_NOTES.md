# Release Notes

## v1.5.20

### Improvements

- Library grid scrolling is smoother, particularly on large libraries.
- BLAEO sync results now load directly in the Community modal if it remains open during the sync, instead of requiring a click on the hamburger notification. Errors also appear inline.

### Fixes

- Filter modal now closes when clicking the backdrop, and automatically selects the currently active saved filter when opened.
- Opening the Community modal now dismisses the BLAEO sync notification. Closing the modal without making changes discards the sync automatically.
- Completion chart now uses a consistent separator width and black background, with a subtle outline ring.
- Gold star icon for achievement completion now displays correctly in the game card context menu.
- Background image modal now shows a live preview of the selected image before saving.
- Fixed a bug introduced in v1.5.14 where restoring a backup from an older version would leave group membership data incorrect.
- Portable Windows builds no longer launch the installer when an update is available -- clicking the update button opens the GitHub releases page instead.
