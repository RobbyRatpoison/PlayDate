# Release Notes

## v1.6.1 — 2026-07-22
### Fixes

- Flatpak installs can now update themselves, both through the in-app updater and via `flatpak update` / GNOME Software / Discover. Self-update didn't work correctly when Flatpak packaging was introduced in v1.6.0.
- Fixed restoring a backup, or importing a Playnite library backup, failing on large files when running as a Flatpak.
- Fixed the on-screen keyboard's Back button also closing the modal underneath it on Steam Deck.

## v1.6.0 — 2026-07-22
### New

- PlayDate is now available as a self-hosted Flatpak for Linux, built and published automatically on every release alongside the Windows installer. Runs on the GTK4/WebKit6 renderer, and supports GOG/Epic Wine-based installs and launches by running Wine/Proton on the host system rather than inside the sandbox.
