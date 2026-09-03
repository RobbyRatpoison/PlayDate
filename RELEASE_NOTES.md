# Release Notes

## v1.10.1
### Improvements

- Home shelves can build their filter with the visual filter builder instead of raw SQL.

### Fixes

- Steam Deck: gamepad input no longer leaks between PlayDate and the Steam overlay/home screen. PlayDate now tracks gamescope's real focus and hands the controller back to Steam whenever it's in the background, fixing both the background navigation and the doubled button presses in the Steam overlay.
- Plugins modal: a plugin's launcher status badge now updates in place after saving or re-checking its launcher config, instead of staying stale until the modal is reopened.
