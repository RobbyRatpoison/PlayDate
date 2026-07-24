# Release Notes

## v1.6.6
### New

- Gamepad Diagnostics now shows PlayStation-style button glyphs (✕ ○ □ △) with matching brand colors when a PlayStation controller is detected, alongside the existing Xbox-style labels and colors.
- Gamepad Diagnostics now shows the controller's detected mapping type and full raw axis values, useful for troubleshooting unusual controllers.
- Holding B in Gamepad Diagnostics closes the panel; a quick tap (or any other button, including ones bound to a controller's system/menu buttons) no longer does, so every button can actually be tested without cutting the test short.

### Fixes

- Fixed gamepad navigation not moving into modals opened from the hamburger menu — pressing a direction could end up controlling the game library behind the modal instead of the modal itself.
- Fixed the X and Y face buttons being swapped on gamepad controllers.
