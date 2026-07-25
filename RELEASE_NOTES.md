# Release Notes

## v1.6.6
### New

- Gamepad Diagnostics now shows PlayStation-style button glyphs (✕ ○ □ △) with matching brand colors when a PlayStation controller is detected, alongside the existing Xbox-style labels and colors.
- Gamepad Diagnostics now shows the controller's detected mapping type and full raw axis values, useful for troubleshooting unusual controllers.
- Holding B in Gamepad Diagnostics closes the panel; a quick tap (or any other button, including ones bound to a controller's system/menu buttons) no longer does, so every button can actually be tested without cutting the test short.
- Added a Play or Pay sync tool (Community menu): tags your currently assigned picks for the active PoP event with a group label so they're easy to find and filter to in your library.
- Added an Appearance setting to choose which page (Home, Library, or Pick 6) opens when PlayDate starts.

### Fixes

- Fixed gamepad navigation not moving into modals opened from the hamburger menu — pressing a direction could end up controlling the game library behind the modal instead of the modal itself.
- Fixed the X and Y face buttons being swapped on gamepad controllers.
- Fixed PAGYWOSG and Monthly in a Month event data sometimes failing to load with a certificate error.
- Fixed garbled special characters (e.g. apostrophes) showing up in a few account-connection status messages.
- Fixed Monthly in a Month's saved filter only including games already in your library at save time, so newly eligible games you added later never showed up until you rebuilt the filter.
- Fixed the update checker getting stuck on a stale result (most noticeable after switching Beta Updates on or off) until the app was restarted. Switching Beta Updates on now also checks for a new build right away.
- Fixed a failed update check's error message disappearing after a few seconds, making a real failure look like nothing had happened.
- Fixed the background image preview endpoint being reachable from any other page open in your browser while PlayDate is running, not just PlayDate itself.
- Fixed the What's New dialog not reappearing when updating between beta builds of the same version.
