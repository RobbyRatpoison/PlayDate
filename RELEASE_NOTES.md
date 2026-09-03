# Release Notes

## v1.10.1
### Improvements

- Home shelves can build their filter with the visual filter builder instead of raw SQL.

### Fixes

- Steam Deck (Game Mode): PlayDate no longer fights Steam Input for the controller. It reads Steam's own gamepad directly instead of grabbing the hardware, which fixes the doubled/skipped inputs in the Steam overlay and library, and PlayDate reacting to the D-pad while it's in the background.
- Steam Deck (Game Mode): installing an update now relaunches PlayDate through Steam, and the update prompts tell you it will close first, instead of just disappearing.
- Plugins modal: a plugin's launcher status badge now updates in place after saving or re-checking its launcher config, instead of staying stale until the modal is reopened.
