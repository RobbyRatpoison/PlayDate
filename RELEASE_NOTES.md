# Release Notes

## v1.5.13

### Improvements

- BLAEO sync: when a game is removed from a BLAEO list, the list name is now removed from the game's groups on the next sync. Previously groups could only be added, never removed.
- BLAEO sync: adding a game to a BLAEO list now appears in the sync result summary alongside status changes, renames, and removals. All group changes are expandable with per-game detail.
- Games installed to secondary Steam library locations are now recognized as installed. Previously only the default library path was scanned.
- Linux: the installer and startup error dialog now include the correct install command for more distributions, including Gentoo, openSUSE, Void, Alpine, and other distros detected via package manager.
- Linux: the window icon now appears correctly in KDE Plasma 6 titlebar and taskbar when running under native Wayland.
- Linux: experimental support for GTK4/WebKit 6.0 (webkit-gtk:6 on Gentoo). Enabled automatically when only WebKit 6.0 is available.
