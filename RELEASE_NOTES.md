# Release Notes

## v1.10.1
### Improvements

- Home shelves: build a shelf's filter with the visual filter builder instead of raw SQL.

### Fixes

- Steam Deck (Game Mode): PlayDate no longer fights Steam Input for the controller, which caused doubled or skipped inputs in the Steam overlay and let the D-pad leak through to PlayDate while it was backgrounded. Installing an update now relaunches through Steam instead of just closing.
- Pick 6: cards no longer run off the sides of the page at higher UI scales, and the Weights section is reachable with a gamepad or keyboard.
- Plugins modal: a plugin's launcher status badge updates in place after saving or re-checking, instead of going stale until the modal is reopened.
- Beta channel: "Check for Updates" reliably finds the newest beta.
