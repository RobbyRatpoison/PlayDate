# Release Notes

## v1.6.5 — Pending
### New

- Added an "Open Program Folder" button (Data settings) for quick access to PlayDate's data folder.
- Gamepad scrolling (right stick) now speeds up the longer it's held, ramping up to a fast top speed — makes navigating huge libraries much quicker.
- While fast-scrolling the library with a gamepad, a preview popup shows your position: the current letter when sorted by name, month/year for date sorts, or hours/percentage for playtime, review, and HLTB sorts. Sorted randomly shows a cycling symbol instead, since there's no real "position" to preview there.

### Fixes

- Fixed the Steam Deck's built-in controller not being detected at all when running the Flatpak build.
- Fixed the first-run setup screen not supporting gamepad navigation.
- Fixed pressing A on the library search bar sometimes reloading the page unexpectedly.
- Fixed the joystick navigating the page at the same time as the on-screen keyboard.
- Fixed the D-pad simultaneously navigating the page behind an open modal or the hamburger menu, instead of just the modal/menu itself.
- Fixed the update checker (for beta testers) not detecting newer beta builds of the same version.
- Fixed gamepad focus jumping back to the page after using "Check for Updates" in the hamburger menu.
- Fixed the install-update confirmation popup not supporting gamepad navigation.
