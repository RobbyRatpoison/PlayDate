# Release Notes

## v1.10.1
### Improvements

- Home shelves can build their filter with the visual filter builder instead of raw SQL.

### Fixes

- Steam Deck (Game Mode): PlayDate no longer fights Steam Input for the controller, which caused doubled or skipped inputs in the Steam overlay and library and let PlayDate react to the D-pad while it was in the background.
- Steam Deck (Game Mode): installing an update now relaunches PlayDate through Steam, and the update prompts tell you it will close first, instead of just disappearing.
- Pick 6: game cards no longer run off the sides of the page at higher UI scales.
- Pick 6: in Weighted mode, the Weights section can now be collapsed and expanded with a gamepad or keyboard.
- Plugins modal: a plugin's launcher status badge now updates in place after saving or re-checking its launcher config, instead of staying stale until the modal is reopened.
- Beta channel: "Check for Updates" now reliably finds the newest beta instead of occasionally missing one.
