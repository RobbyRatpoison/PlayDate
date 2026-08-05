# Release Notes

## v1.7.3 - 2026-08-05
### New

- GOG, Humble Bundle, and itch.io now let you choose where games get installed, matching what IndieGala already offered.

### Improvements

- itch.io's default install folder moved to match GOG/Humble Bundle/IndieGala's convention. Any existing itch.io installs are moved automatically the first time you open this version.

### Fixes

- Installs for GOG, Humble Bundle, itch.io, and IndieGala now check that there's enough free disk space, and that the install folder is actually writable, before starting.
- Installing or updating a plugin that needs a newer PlayDate version than you're running is now blocked.
- Fixed the Uninstall button in the Plugins modal staying hidden after clicking Cancel.
