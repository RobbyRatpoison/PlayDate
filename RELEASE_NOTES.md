# Release Notes

## v1.10.1
### Improvements

- Home shelves: the raw SQL box for a shelf's filter is replaced with the visual filter builder.

### Fixes

- Steam Deck (Game Mode): PlayDate no longer fights Steam Input for the controller, which caused doubled inputs in the Steam overlay and let controller input leak through to PlayDate while it was backgrounded. Installing an update now relaunches through Steam instead of just closing.
- Pick 6: cards no longer run off the sides of the page at higher UI scales, and the Weights section is reachable with a gamepad or keyboard.
- Plugins modal: a plugin's launcher status badge updates in place after saving and re-checking its launcher config.
- Beta channel: fixed Check for Updates not finding beta builds released after beta.9.
