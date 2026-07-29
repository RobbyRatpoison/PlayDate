# Changelog

## v1.6.9 - 2026-07-29
### New

- Added an in-app Tutorial covering many of the features included in PlayDate. Shows automatically on first setup (or once for existing installs), and anytime after from the hamburger menu.
- Added "Copy Link Address" to the right-click menu.

### Fixes

- Fixed the update-install prompt suggesting a backup every time, even right after making one. Now skips it for 24 hours after a backup. (suggested by fernandopa)
- Fixed "Hide duplicate entries" not applying to Home page shelves. (reported by DarkRainX)
- Fixed GOG games' release dates sorting before/after all Steam games instead of by actual date. (reported by DarkRainX)
- Fixed IndieGala library sync stopping after the first page.
- Fixed date imports with "normalize dates" enabled scrambling date sort order.

## v1.6.8 - 2026-07-28
### New

- Play or Pay picks now generate a saved filter automatically, matching how PAGYWOSG results work. (prompted by feedback from Blue™)
- Play or Pay offers to clean up the previous cycle's group tag when a new cycle starts.
- The PAGYWOSG filter builder offers to delete old event filters when you save a new one.

### Improvements

- Plugins that need a newer version of PlayDate now show a "needs update" badge in the Plugins menu instead of silently disappearing.
- Sync/scrape operations that hit Steam's rate limit now wait however long Steam actually asks for, instead of guessing.

### Fixes

- Fixed PAGYWOSG tags showing as one combined line in the library hover tooltip and game-edit qualifications panel instead of a separate line per tag. (reported by Blue™)
- Fixed the Edit Game popup silently failing to open for games that qualify for a PAGYWOSG category, if a SteamGifts username was set in Settings. (reported by Blue™)
- Fixed GOG games showing a blank or incorrect review score.
- Fixed GOG's "Fetch metadata" not actually re-fetching games that were already synced, so review scores and other metadata could get permanently stuck.
- Fixed GOG games removed from your account not being cleaned up on the next library sync.
- Fixed a crash when Steam rate-limits a "Sync Steam Data" request; now shows a clear message instead.
- Fixed the gamepad focus highlight not appearing on the update-install confirmation and What's New popups.

## v1.6.7 - 2026-07-28
### New

- The library search bar now narrows results live as you type instead of waiting for Enter.
- Tag, Group, Genre, and Category filter conditions now hold multiple values in one row as chips, instead of a separate row per value. Older filters convert automatically.
- Auto-generated title-word filter conditions now show a plain description instead of raw SQL.
- PAGYWOSG auto-fill recognizes more category types (release dates, achievement counts/ranges, title patterns, AppID digits, review ratings), so fewer need manual review.
- "Personal categories" in the PAGYWOSG builder now include your own verified games instead of excluding the category entirely, and inherently personal categories can come pre-checked automatically.
- Added a `CONTRIBUTORS.md` crediting everyone who's helped shape PlayDate through bug reports and feedback.

### Fixes

- Fixed the "✕ CLEAR" button staying visible with a hidden platform source even when no filter or search was active.
- Fixed the update checker getting stuck on a broken download link if a release wasn't fully published yet.
- Fixed text selection not lining up with visible text in the filter editor's SQL preview.
- Fixed the hamburger menu looking lopsided when focused with a gamepad by combining its three notification dots into one.
- Fixed the Linux/macOS installer showing "Done" instead of launching PlayDate when setup finished - it now launches automatically like on Windows.

## v1.6.6 - 2026-07-25
### New

- Gamepad Diagnostics now shows PlayStation-style button glyphs (✕ ○ □ △) with matching brand colors when a PlayStation controller is detected, alongside the existing Xbox-style labels and colors.
- Gamepad Diagnostics now shows the controller's detected mapping type and full raw axis values, useful for troubleshooting unusual controllers.
- Holding B in Gamepad Diagnostics closes the panel; a quick tap (or any other button, including ones bound to a controller's system/menu buttons) no longer does, so every button can actually be tested without cutting the test short.
- Added a Play or Pay sync tool (Community menu): tags your currently assigned picks for the active PoP event with a group label so they're easy to find and filter to in your library.
- Added an Appearance setting to choose which page (Home, Library, or Pick 6) opens when PlayDate starts.

### Fixes

- Fixed gamepad navigation not moving into modals opened from the hamburger menu - pressing a direction could end up controlling the game library behind the modal instead of the modal itself.
- Fixed the X and Y face buttons being swapped on gamepad controllers.
- Fixed PAGYWOSG and Monthly in a Month event data sometimes failing to load with a certificate error. (reported by quinnix)
- Fixed garbled special characters (e.g. apostrophes) showing up in a few account-connection status messages.
- Fixed Monthly in a Month's saved filter only including games already in your library at save time, so newly eligible games you added later never showed up until you rebuilt the filter.
- Fixed the update checker getting stuck on a stale result (most noticeable after switching Beta Updates on or off) until the app was restarted. Switching Beta Updates on now also checks for a new build right away.
- Fixed a failed update check's error message disappearing after a few seconds, making a real failure look like nothing had happened.
- Fixed the background image preview endpoint being reachable from any other page open in your browser while PlayDate is running, not just PlayDate itself.
- Fixed the What's New dialog not reappearing when updating between beta builds of the same version.

## v1.6.5 - 2026-07-24
### New

- Added an "Open Program Folder" button (Data settings) for quick access to PlayDate's data folder.
- Gamepad scrolling (right stick) now speeds up the longer it's held, ramping up to a fast top speed - makes navigating huge libraries much quicker.
- While fast-scrolling the library with a gamepad, a preview popup shows your position: the current letter when sorted by name, month/year for date sorts, or hours/percentage for playtime, review, and HLTB sorts. Sorted randomly shows a cycling symbol instead, since there's no real "position" to preview there.

### Fixes

- Fixed the Steam Deck's built-in controller not being detected at all when running the Flatpak build.
- Fixed the first-run setup screen not supporting gamepad navigation.
- Fixed pressing A on the library search bar sometimes reloading the page unexpectedly.
- Fixed the joystick navigating the page at the same time as the on-screen keyboard.
- Fixed the D-pad simultaneously navigating the page behind an open modal or the hamburger menu, instead of just the modal/menu itself.
- Fixed the update checker (for beta testers) not detecting newer beta builds of the same version.
- Fixed gamepad focus jumping back to the page after using "Check for Updates" in the hamburger menu.
- Fixed the install-update confirmation popup not supporting gamepad navigation.
- Fixed the Flatpak build's window showing a generic icon in the titlebar and taskbar instead of PlayDate's own.
- Fixed PlayDate's icon not showing up correctly in Flatpak-aware software centers (e.g. Shelly, GNOME Software), showing a placeholder instead.
- Fixed the in-app updater always installing to the per-user Flatpak location even if PlayDate was originally installed system-wide, which could leave two separate copies installed side by side. It now always updates whichever copy is actually running.

## v1.6.4 - 2026-07-23
### New

- PlayDate now ships with a default background image, used automatically until you set your own from the Appearance menu.
- Added an opt-in "Beta updates" toggle (System settings) for testers who want early access to pre-release builds before they're promoted to a full release.

### Improvements

- The Flatpak build is now recommended as the primary way to install PlayDate on Steam Deck, with updated install/uninstall instructions in the README.

## v1.6.3 - 2026-07-23
### Fixes

- Fixed restoring a backup from the first-run setup screen failing on large files (cover art included) - it now uses the same native file picker as the Settings restore flow instead of always uploading the whole file.
- Fixed the Steam Deck on-screen keyboard's Back button also closing the modal underneath a focused text field, in cases the previous fix didn't cover.

## v1.6.2 - 2026-07-23
### Fixes

- Fixed installing the Flatpak failing with "runtime ... not found" on systems without the GNOME runtime already present (e.g. a stock Steam Deck) - it's now fetched automatically during install.

## v1.6.1 - 2026-07-22
### Fixes

- Flatpak installs can now update themselves, both through the in-app updater and via `flatpak update` / GNOME Software / Discover. Self-update didn't work correctly when Flatpak packaging was introduced in v1.6.0.
- Fixed restoring a backup, or importing a Playnite library backup, failing on large files when running as a Flatpak.
- Fixed the on-screen keyboard's Back button also closing the modal underneath it on Steam Deck.

## v1.6.0 - 2026-07-22
### New

- PlayDate is now available as a self-hosted Flatpak for Linux, built and published automatically on every release alongside the Windows installer. Runs on the GTK4/WebKit6 renderer, and supports GOG/Epic Wine-based installs and launches by running Wine/Proton on the host system rather than inside the sandbox.

## v1.5.21 - 2026-07-03
### Fixes

- Fixed PAGYWOSG hover tooltips not showing a matching title-word condition for some games.
- Fixed platform filter toggles (library page and home screen shelves) disappearing once only one platform remains in your library, which could leave a platform hidden with no way to show it again.

## v1.5.20 - 2026-06-30
### Improvements

- Library grid scrolling is smoother, particularly on large libraries.
- BLAEO sync results now load directly in the Community modal if it remains open during the sync, instead of requiring a click on the hamburger notification. Errors also appear inline.

### Fixes

- Filter modal now closes when clicking the backdrop, and automatically selects the currently active saved filter when opened.
- Opening the Community modal now dismisses the BLAEO sync notification. Closing the modal without making changes discards the sync automatically.
- Completion chart now uses a consistent separator width and black background, with a subtle outline ring.
- Gold star icon for achievement completion now displays correctly in the game card context menu.
- Background image modal now shows a live preview of the selected image before saving.
- Fixed a bug introduced in v1.5.14 where restoring a backup from an older version would leave group membership data incorrect.
- Portable Windows builds no longer launch the installer when an update is available -- clicking the update button opens the GitHub releases page instead. (reported by PapaSmok)

## v1.5.19 - 2026-06-29
### Improvements

- Name searches now appear as editable conditions in the filter modal, alongside any other active filters. They can be removed or modified from there like any other condition.
- The filter header now shows the active search term alongside the filter name.
- Applying filters now strips empty groups from the tree, keeping saved filters clean.
- Right-clicking a Steam game card now shows links to the game's Achievements page and Community Hub.
- PAGYWOSG auto-fill now detects and handles two additional category types: "game title with [word]" categories (matched as whole words, with all variants matched exactly as the API specifies) and HLTB time threshold categories ("under 5h HLTB main", "20h+ HLTB completionist", etc.) for main, main+extras, and completionist fields.

## v1.5.18 - 2026-06-16

### Fixes

- Epic Games: fixed false "launcher not installed" warning when Epic is installed to a non-default folder. (reported by quinnix)
- Epic Games: fixed login getting stuck on a blank page on Windows. (reported by quinnix)

### Improvements

- BLAEO sync now runs in the background. A dot appears in the menu when results are ready; click it to review and apply changes. (prompted by feedback from 86maylin)
- Searches by name now populate in the filter modal.
- Saving a filter that already exists now asks for confirmation before overwriting it.
- Built-in filter presets now populate in the filter modal.
- Clearing filters no longer resets your platform source toggles.

## v1.5.17 - 2026-06-13

### Bug Fixes

- Fixed date filters (last played, date added, release date) producing missing or nonsensical results. (reported by DarkRainX)

## v1.5.16 - 2026-06-12
### Bug Fixes

- Steam collections sync now picks up all user-created collections, not just those with the legacy `uc-` ID format used by older Steam clients. (reported by 86maylin)

## v1.5.15 - 2026-06-12
### Bug Fixes

- PAGYWOSG quals panel: fixed wrong month label when a new event starts at the end of the prior month.
- PAGYWOSG quals panel: title-letter and weekday-release categories are now auto-detected.
- PAGYWOSG quals panel: win/backlog labels now correct when no PAGYWOSG filter is active.
- Filter modal: Platform dropdown now only lists platforms present in your library.
- BLAEO sync: proposed changes list is now scrollable, so the Apply button stays visible with large change sets. (reported by 86maylin)

## v1.5.14 - 2026-06-12
### New Features

- Steam library collections sync to groups at startup. Renaming or removing a collection updates the group on next launch. (suggested by 86maylin)
- Groups shared between a Steam collection and a BLAEO list are protected - renaming one won't affect the other. (suggested by 86maylin)
- If you manually add a group with the same name as a Steam collection or BLAEO list, renaming the sync source keeps your original group and adds the new name alongside it.
- Non-Steam games (GOG, EA, Humble, itch.io) now fall back to Steam CDN art when SteamGridDB has no cover.

### Bug Fixes

- IndieGala: sync now shows an error when your session has expired instead of silently reporting 0 games.
- BLAEO sync preview: checkbox layout was broken.

## v1.5.13 - 2026-06-07

### Improvements

- BLAEO sync: when a game is removed from a BLAEO list, the list name is now removed from the game's groups on the next sync. Previously groups could only be added, never removed.
- BLAEO sync: adding a game to a BLAEO list now appears in the sync result summary alongside status changes, renames, and removals. All group changes are expandable with per-game detail.
- Games installed to secondary Steam library locations are now recognized as installed. Previously only the default library path was scanned. (reported by DarkRainX, who also pointed at `libraryfolders.vdf` as the fix)
- Linux: the installer and startup error dialog now include the correct install command for more distributions, including Gentoo, openSUSE, Void, Alpine, and other distros detected via package manager.
- Linux: the window icon now appears correctly in KDE Plasma 6 titlebar and taskbar when running under native Wayland.
- Linux: experimental support for GTK4/WebKit 6.0 (webkit-gtk:6 on Gentoo). Enabled automatically when only WebKit 6.0 is available. (reported by DarkRainX)

## v1.5.12 - 2026-06-06

### Improvements

- Game names can now be updated to match Steam's store display name, which sometimes differs from the internal name. After the first launch, any differences are flagged in the hamburger menu. Clicking the notification opens a review list where you can pick which names to update - nothing changes automatically. Keeping names in sync is important for PAGYWOSG, since category sorting uses the store display name.
- PAGYWOSG filter builder: after auto-filling an event, a Personal categories section lists all categories that have a mod-verified game list. Checking a category marks it as personal - games verified for another user in those categories are excluded from the filter and qualifications panel entirely, since eligibility depends on your own history (e.g. "won in June").
- BLAEO sync: completion status downgrades are no longer blocked - if your status on BLAEO differs from PlayDate, BLAEO now wins.
- BLAEO sync: renaming a list on BLAEO will now automatically rename it in your PlayDate library on the next sync instead of creating a duplicate.
- BLAEO sync: the result now shows a breakdown of what changed - which games had their status updated and any lists that were renamed. Details are expandable, and everything is also written to the log.
- Bulk operations (re-scrape, art, ProtonDB, HLTB, date import) now show a progress indicator in the hamburger menu while running. Navigating away and back will resume the progress display and prevent accidentally starting a second operation. (suggested by kiseli)
- Blacklist Manager now has a search box to filter by game name.

### Bug Fixes

- Games with no Steam achievements no longer show blank achievement counts after a full library scan. Existing games with blank achievement counts or playtime will be corrected automatically on first launch.
- Games with no playtime are now imported with 0 minutes instead of blank.
- Populate progress counter no longer overshoots the total when games with unfetched metadata are visible in the library during a populate run.
- Populate no longer gets stuck in a running state when the library contains games added by plugins that have not yet had metadata fetched.

## v1.5.11 - 2026-06-01

### Bug Fixes

- PAGYWOSG quals: "game name starts with" and "released on a specific weekday" categories now correctly display the qualifying reason in the library tooltip and edit modal. (reported by kiseli)

## v1.5.10 - 2026-06-01

### Bug Fixes

- Fixed a startup crash on reboot ("no such column: duplicate_auto") that forced a full reinstall to recover. The column is now added before migration 9 queries it.

### Improvements

- Bulk edit: replace mode now accepts an empty value to clear the field (set to null) for all matching games.
- Bulk edit: remove mode now populates pill suggestions from the values actually present in the current scope, rather than the full library.

## v1.5.9 - 2026-05-30

### Bug Fixes

- Fixed PAGYWOSG filter builder not saving completion status toggles when building and saving a filter.

## v1.5.8 - 2026-05-30

### New Plugins

- **EA App** *(experimental)* - sync your EA library; launch support is implemented but EA App itself does not currently run under Wine on Linux, so install and launch are non-functional there. Windows support is implemented but untested.
- **IndieGala** - sync your IndieGala library, auto-detects installed games from local folders, launch and uninstall support.

### Improvements

- Platform source toggles moved from the View modal to the Filters modal, with a new All/None toggle button.
- Secret Santa / Snowballs gift list: added a group picker to bulk-add all Steam games from a library group at once. (suggested by samwise84)
- PAGYWOSG filter builder now auto-detects two new category types: "Games starting with [letter]" (name starts-with filter) and "Games released on a [weekday]" (release date weekday filter).
- Bulk date import now fetches purchase dates directly from Humble Bundle, Epic Games, and itch.io via their APIs - no Tampermonkey interaction needed for these platforms.
- Date importer Tampermonkey script now supports EA App: scrapes purchase dates from the EA order history page and sends them to PlayDate.
- Wine prefix can now be removed from the Plugins panel - the launcher config card includes an "Uninstall Launcher" button that deletes the prefix and clears the saved config.
- Epic Games Wine launcher: required graphics libraries are now automatically installed into the Wine prefix after the Epic launcher installer completes.

### Bug Fixes

- Fixed restore-from-path (native file picker) not restoring the theme and emulator configuration.
- Fixed Pick 6 ignoring platform source toggles when building the candidate pool.
- Fixed Pick 6 including games with no review data when a minimum review score bound was set; same fix applied to release year and HLTB bounds.
- Fixed PAGYWOSG filter builder completion status toggles being read from both the PAGYWOSG and MIAM tools simultaneously, causing statuses to appear twice in the saved filter tree and breaking the filter entirely when enough statuses were selected.
- Fixed bulk date import showing a "Tampermonkey script not detected" error when the queue contained only non-Steam games.

## v1.5.7 - 2026-05-25

### Home Page

- Fixed hover grow effect not working on cards in split-row shelves.

### Backup & Restore

- Backup now includes `theme.json`, `emulators.json`, and `santa_gifts.json` in addition to the existing files.
- Backup modal lists all files included in the backup.
- Clicking "Install Update" now opens a confirmation popup with a "Back Up First" button before proceeding.

### Bug Fixes

- Fixed a crash on upgrade where the v1.5.6 migration would fail with `no such column: meta_fetched` on older databases. (reported by samwise84)
- Fixed Windows portable build failing to launch due to missing `Python.Runtime.dll` in the bundle. (reported by samwise84)
- Fixed several modules (`emulators`, `howlongtobeatpy`, `runners.launch`) missing from the Windows PyInstaller bundle. (reported by samwise84)

## v1.5.6 - 2026-05-23

### New Plugins

- **itch.io** - sign in to your itch.io account to import your purchased library. Games are downloaded and launched directly. Download progress is shown in the nav bar with a cancel button. Installed games can be uninstalled from the right-click menu.
- **Humble Bundle** - connect with your `_simpleauth_sess` cookie to import your library. Games are downloaded and launched directly. Non-game items (soundtracks, art books, etc.) are filtered out automatically. Installed games can be uninstalled from the right-click menu.

### Emulators

- Added emulator support (Menu → Emulators). Point PlayDate at your ROM folders and it scans them into your library - cover art is fetched from SteamGridDB automatically.
- A wide range of systems and emulators are supported and detected automatically. RetroArch is supported, with per-system core selection. Custom emulators can be added manually.

### Duplicates

- Duplicate images are now shared: if a game marked as a duplicate has no image of its own, the canonical game's image is shown automatically.
- HLTB data is now propagated across duplicate groups: confirming a match for any game in the group applies it to all others. Linking a game as a duplicate of another also copies confirmed HLTB data immediately.
- Duplicate detection now includes all installed plugins automatically, so non-Steam games can be matched against each other without Steam being involved.

### GOG

- On Linux, Windows GOG games now launch via Proton when available, with Wine as a fallback.

### Artwork

- Added a Clear button to each artwork slot in the edit modal (cover, header, icon).
- Fixed an issue where bulk art scraping did not fetch art for non-Steam games.
- Game covers that don't match their container's aspect ratio now show a blurred background fill instead of cropping or stretching.

### Library

- Sort by Random added to the View modal.
- Improved scroll performance in grid and list view.

### Monthly in a Month

- Added a Monthly in a Month filter builder (Menu → Community). It cross-references your library against the community list and saves a filter for eligible unplayed games. (prompted by feedback from PapaSmok)

## v1.5.5 - 2026-05-14

### Home Page

- Fixed shuffle shelves ignoring per-shelf platform filters (e.g. a Steam-only shelf could return Epic games on reshuffle).
- Adding a column to a shelf row now creates a new blank column directly instead of requiring an existing shelf to be combined.

### Library

- Fixed the dice button not working in list/details view. (reported by PapaSmok)

### PAGYWOSG

- The completion status toggles (Never Played, Unfinished, Beaten, Completed) now remember your last selection across sessions. (prompted by feedback from PapaSmok)

### Gamepad

- Full gamepad controls are now enabled across the entire app - library, modals, settings, plugins, and Pick 6.
- Added a "Pause gamepad input when launching a game" option in Menu → System (on by default).
- Added a Gamepad Controls screen (Menu → System → Gamepad Controls) to remap any action to a different physical button. Default layout: A=Confirm, B=Back, X=Context Menu, Y=Filter/Search, LB=Previous Page, RB=Next Page, Back=Open Menu, Start=System, D-pad=Navigate.
- Fixed a grey circle appearing in the corner of the window when a game closed (KDE/Wayland).

### GOG

- GOG games that use DOSBox now launch correctly via the system dosbox binary instead of failing silently.

### Steam Deck

- Fixed the install script hanging after a SteamOS update.

## v1.5.4 - 2026-05-07

### Installation

- Added `launch.sh` as a single entry point for Linux and macOS. It handles first-time setup automatically and keeps the desktop shortcut up to date if you move the folder.
- Added a portable Windows zip to release builds - extract anywhere under your user folder and run `PlayDate.exe`. (requested by PapaSmok)
- Fixed Steam Deck installs failing after a SteamOS update due to PGP signature trust errors.
- Fixed the missing-WebKit2GTK error message not appearing on Linux.

### Fixes

- Fixed a startup crash when upgrading from a version before non-Steam library support was added. (fernandopa helped test the fix)

## v1.5.3 - 2026-05-05

### Epic Games

- Game descriptions now appear in list mode detail pane.
- Library sync now fetches metadata and artwork for each game as it's added. Sync can be stopped mid-way and picks up where it left off on the next run.
- Repeat syncs are significantly faster.
- Library sync now includes DLC, soundtracks, and tools alongside base games.
- Added an "Import Purchase Dates" button that fetches acquisition dates from Epic and updates your library.

### GOG

- Library sync now fetches metadata and artwork for each game as it's added. Sync can be stopped mid-way and picks up where it left off.
- Achievement data is now tracked for existing library games.

### HLTB

- How Long to Beat lookups are now faster and more accurate. (uses a Steam-to-HLTB mapping dataset contributed by zpangwin)

### Library

- Library and home page load faster; the page chrome now appears immediately while the grid loads in the background.
- Added a PAGYWOSG Builder shortcut to the filters modal header. (suggested by zpangwin)
- Pick 6 now shows the active filter name; applying a filter from the Pick 6 modal correctly saves and displays the filter name. (prompted by feedback from zpangwin)

### General

- PlayDate now shows a "What's New" summary after updating to a new version.

### Fixes

- Fixed a startup issue that silently discarded Steam last-played date updates on every launch.
- Fixed the edit modal not reopening after saving a game.
- Fixed card outlines appearing after saving when they were disabled in settings.
- Fixed a duplicate entry appearing in the saved filters dropdown when replacing a PAGYWOSG filter.
- Fixed GOG games being incorrectly marked as Completed at startup based on achievement data.
- Fixed bulk ops "Filtered Games" scope ignoring hidden platforms and failing entirely in list mode.
- Fixed bulk delete and date import also failing in list mode for the same reason.
- Fixed date fields showing a raw timestamp instead of a formatted date after saving in list mode.

### Installation

- Fixed the installer and uninstaller windows clipping buttons and content on some screen sizes. (reported by zpangwin)
- The desktop shortcut checkbox in the installer now only takes effect when you confirm installation.

## v1.5.2 - 2026-04-30

### Appearance

- Added a UI Scale slider under Menu → Appearance. Drag to scale the entire interface up or down (75–150%). Useful for 4K and HiDPI displays where text appears too small.

### Library

- Added a toggle under Menu → Library → Completion Sync to control whether games are automatically promoted from Never Played to Unfinished when Steam shows playtime. Disable this if you use BLAEO to manage Never Played status.
- Quick filters are now grouped into two rows: general filters (All Games, Installed, Not Installed, Never Played / Unfinished, Beaten / Completed) and individual status filters (Never Played, Unfinished, Beaten, Completed, Won't Play).

### Installation

- The Linux prerequisites in the README now include `python3-venv`, `python3-pip`, and `python3-tk` for Debian/Ubuntu. (reported by greatmastermario)
- The Linux installer now shows the actual error output when virtual environment creation fails, with a targeted hint for Debian/Ubuntu users. (reported by greatmastermario)

### Fixes

- Fixed a startup crash (`no such column: protondb_fetched`) affecting users upgrading from older database versions. (reported by CrabdaddyLonglegs)
- Fixed the Won't Play quick filter not working.
- Fixed BLAEO sync silently ignoring Won't Play status - games marked Won't Play on BLAEO will now sync correctly (unless the game is already Beaten or Completed in PlayDate). (reported by 86maylin)

## v1.5.1 - 2026-04-30

### Fixes

- Fixed a crash on startup when the plugins folder was missing, which affected fresh installs and users who had downgraded. (reported by Meneldur)
- Fixed several modules (`runners.oauth2`, `runners.watcher`, `runners.proton`, `runners.wine`, `watchdog`) missing from the Windows PyInstaller bundle, causing GOG/Epic login crashes and silently disabling filesystem watching. (reported by Meneldur)

---

## v1.5.0 - 2026-04-29

### Plugins

- GOG support is now an optional plugin. The GOG and Epic Games plugins are included and update automatically from GitHub.
- Additional plugins can be installed via zip file or GitHub URL.
- Hamburger → Plugins manages installed plugins. An orange dot appears when plugin updates are available.

### Epic Games

- Connect your Epic Games account via Plugins → Epic Games → Manage. Sync your library to import games, cover art, tags, ratings, and store metadata.
- Games launch via the Epic Games Launcher - natively on Windows/Mac, or via a Wine prefix on Linux.
- On Linux, games can be uninstalled directly from PlayDate. On Windows/Mac, use the Epic Games Launcher to uninstall.

### Library

- New sort option: Total Reviews.

### Fixes

- PAGYWOSG & BLAEO renamed from "Community" in the hamburger menu.

---

## v1.4.5 - 2026-04-26

### Card Outlines

- Game cards can now display coloured outlines driven by configurable rules. Each rule pairs a colour with a filter (built-in preset, saved filter, or custom). The highest-priority matching rule wins per card. (inspired by a suggestion from onegoodleg)
- Default rules ship pre-configured with BLAEO completion status colours.
- Per-page toggles let you enable or disable outlines independently on Library, Home, and Pick 6.
- The dice button in the Library glows with the picked game's outline colour.
- The native colour picker (broken in this environment) has been replaced with a custom one: hue/saturation/value controls, hex input, palette swatches, and a screen eyedropper.

### Edit Modal

- Stats is now the first tab and opens by default; Info is second.
- HLTB times now appear in both the Stats and Info tabs.
- Stats tab fields reorganised into a cleaner grid layout.
- Fixed: 0 playtime now shows as 0.0 hours instead of a blank field.

### Community

- New **Secret Santa / Snowballs** gift list - track games received as Discord event gifts. The PAGYWOSG filter builder gains an option to include these gifts as wins in the generated filter.

### Library

- Duplicate detection platform priority is now configurable via a drag-to-reorder list in the Library modal (Duplicates section).

### Fixes

- Fixed GOG game descriptions not loading in List view.
- Fixed tooltips throughout the app being clipped or mispositioned (particularly the API key tooltip in the account modal).
- Reduced likelihood of a phantom window appearing on secondary monitors when launching games.

## v1.4.4 - 2026-04-25

### Library

- Added **List view** as a third display mode alongside Vertical and Horizontal. Switch to it via the VIEW modal - the art orientation toggle is now a three-button group. List view shows a scrollable game list on the left with a resizable divider and a detail panel on the right. The detail panel shows cover art, an on-demand game description, and all editable fields from the edit modal. Group-by is supported with collapsible section headers. Rows outside the viewport are unloaded so performance stays consistent regardless of library size. Right-clicking a row opens the standard context menu. The last selected game is remembered when navigating away and back. (suggested by liquidlazor)

### Fixes

- Fixed update download silently hanging on SSL certificate verification failures; now retries with verification disabled, and shows an error with a manual download link if the retry also fails.
- Fixed games with no release date falsely matching date-based filter conditions (month, day, year).
- Fixed account modal API key tooltip being clipped by the modal edge.

### Other

- Gamepad navigation is temporarily disabled while it is reworked. It will return in a future update.

## v1.4.3 - 2026-04-21

### Menu

- The hamburger menu now has direct entries for **Accounts**, **Appearance**, **Library**, **Community**, **Data**, **System**, and **Manage**, replacing the old Settings and Tools buttons. Each opens a focused modal for that area.

### Pick 6

- Added soft bound relaxation: if the active filters produce a pool smaller than 12 games, bounds loosen in 5% steps until at least 6 games are available. A warning is shown when this happens.

### Library

- The library toolbar (search, VIEW, FILTERS, etc.) now stays fixed at the top of the page while scrolling, instead of scrolling out of view. (suggested by fernandopa)

### Fixes

- Context menu completion status submenu no longer goes off the right edge or bottom of the screen. (reported by fernandopa)
- Right-clicking an area with no menu options now closes any open context menu.
- Release date migration no longer restarts on every launch after completing.

## v1.4.2 - 2026-04-19

### Library

- Restored the **✕ CLEAR** button in the library toolbar. It appears whenever a filter or platform filter is active and clears both in one click.

### Filters

- Filter modal dropdowns with more than 20 options now show a search input at the top; type to filter the list, arrow keys to navigate, Enter to select. (suggested by bluemoon55127)
- Boolean fields (Installed, Free to Play) now default to "Yes" when adding a new condition row.

### View Options

- Added a **VIEW** button to the library toolbar. Opens a modal with sort order, grid size, grid orientation (vertical/horizontal), group-by, and platform visibility.
- **Group by** option groups games by Installed status, Completion, Release Year, Year Added, Review Score, Weighted Score, or Platform. Groups are collapsible and sorted by the active sort column.

### Release Dates

- Release dates are now read from the local Steam `appinfo.vdf` file. The previous method used the Steam Store API, which returns the Steam launch date - this didn't match the date shown on the store page for games that were released elsewhere first. A one-time background migration corrects existing library entries; progress is tracked and resumes if interrupted.

## v1.4.1 - 2026-04-18

### New

- **Gamepad Diagnostics** - Settings > Testing now has a "Gamepad Diagnostics" button. The panel shows whether a controller is detected, whether input suppression is stuck (with a one-click Clear button to fix it), and a live view of every button and both analog sticks. Useful for diagnosing controller issues on Steam Deck and other gamepad setups.
- **UI scales with window size** - All text, buttons, inputs, and modals now scale proportionally with the window width. The interface looks correct from small windows up to large ultrawide displays, including Steam Deck's 1280×800 screen.
- **Resize to Steam Deck button** - Settings > Testing has a button to snap the window to 1280×800 for testing the Steam Deck layout on desktop.
- **Library random pick** - New dice button (🎲) in the library toolbar picks a random game from your current filtered list and smoothly scrolls to it with a glow highlight. (suggested by fernandopa)
- **Library platform filter** - New "PLATFORMS" button in the library toolbar lets you show or hide games from specific platforms. Only appears when you have games from more than one platform.
- **Per-shelf platform filter** - In home page edit mode, each shelf now has platform toggle buttons so you can control which platforms appear on individual shelves.
- **Pick 6 minimum/maximum bounds** - Weighted mode now shows a threshold input next to each active slider. Positive weights get a minimum bound (e.g. review score ≥ 70); negative weights get a maximum bound (e.g. HLTB ≤ 3 hours). Games outside the bounds are excluded from the pick. Smart mode automatically applies a review score floor of 70%.
- **GOG install progress in navbar** - When a GOG game is installing, a progress bar appears in the hamburger menu showing the game name, MB downloaded, and percentage. Clicking it cancels the install.
- **CSV column picker** - The CSV export now has a collapsible column picker. All 17 columns are selected by default; uncheck any you don't want. (suggested by onegoodleg)

### Fixes

- **BLAEO sync no longer downgrades completion** - Syncing BLAEO will not overwrite a higher completion status with a lower one (e.g. "Beaten" will not be replaced by "Unfinished"). "Won't Play" is never touched by BLAEO sync.
- **GOG install status auto-syncs** - The GOG games folder is now watched for changes. Installed/uninstalled status updates automatically without needing a manual sync.
- **Launching a game no longer reloads the page** - After launching, the library card updates in place and recently-played shelves refresh in the background.
- **Completion pie stays circular** - The completion pie widget on the home page now stays a circle in narrow or wide split-row shelf configurations.
- **Cover art change persists after scrolling** - Updating a game's cover art in the edit modal now stays visible if you scroll away and back.
- **PAGYWOSG tooltip hides on mouse leave** - The qualification tooltip now dismisses when the mouse leaves the browser window.
- **PAGYWOSG quals preserved while searching** - Applying a search in the library no longer strips PAGYWOSG qualification data from the active filter.
- **PAGYWOSG quals panel cleanup** - The name search condition is no longer shown in the qualifications panel or hover tooltip.

### Changed

- **Pick 6 result cards** - Each result card now shows the game's name and a short explanation of why it was picked (top scoring factors: tags, review score, staleness, release year, HLTB length).
- **Pick 6 weights panel collapsed by default** - The sliders panel starts collapsed; clicking Pick 6 also collapses it so result cards have more room.
- **Library select mode** - The standalone SELECT button has been removed. Select mode is now entered via the "Pick games →" scope option inside the Bulk Ops and Delete modals. Active selections show as a badge next to the BULK OPS button.
- **Duplicate hide setting moved** - The toggle for hiding duplicate games has moved from the library toolbar to the Library section of Settings.
- **Bulk edit date fields** - Date columns in bulk edit (Date Added, Release Date, Last Played) now accept YYYY-MM-DD input.

## v1.4.0 - 2026-04-14

### New

- **GOG Galaxy integration** - Full GOG support alongside Steam. Connect your GOG account via OAuth2 (auth-code flow with step-by-step instructions), sync your GOG library, and manage everything from a new GOG panel in Settings. GOG games are auto-matched to Steam games by normalized name with automatic duplicate detection.
  - Library sync via GOG's paginated `getFilteredProducts` API
  - Metadata fetch via `api.gog.com/v2/games/{id}` (developers, publishers, genres, tags, release date, platform slug)
  - Achievement fetch via `gameplay.gog.com` (counts unlocked achievements)
  - GOG store link support in the edit modal (`gog.com/en/game/{slug}`)
  - Purchase date import via Tampermonkey script on GOG orders page (page 1 parsed from inline `gogData`, pages 2-N fetched via Angular XHR API)
- **GOG game install & launch** - Download and install GOG games directly through PlayDate. The GOG content-system v2 fetches builds → meta manifest → depot manifests → downloads and decompresses zlib chunks into the final file layout. Prefers Linux builds, falls back to Windows. Windows games get a Proton prefix auto-configured. Windows games launch via Proton; Linux native games launch directly. Install progress shows MB downloaded in a toast and is cancellable. Background threading with `threading.Event` cancel support.
- **Proton detection** - `runners/proton.py` detects GE-Proton and official Proton across both `~/.steam/steam` and `~/.local/share/Steam` (deduped via `os.path.realpath`). `launch_game()` sets `STEAM_COMPAT_DATA_PATH` + `STEAM_COMPAT_CLIENT_INSTALL_PATH` and spawns `proton run {exe}`. Active Proton runner displayed in Settings.
- **Duplicate detection & hiding** - New `duplicate_of` column links non-Steam games to their Steam counterpart. Library excludes duplicates by default; toggle via "DUPES: OFF/ON" button. Library header shows "N duplicates hidden" when any exist. Edit modal shows a "Duplicate of:" row for non-Steam games with a searchable Steam library lookup, link button, and unlink button. Auto-detection runs after every GOG library sync; manually re-runnable via "Detect Duplicates" in the GOG Tools panel. Search endpoint: `GET /api/games/search?q=&platform=`.
- **Platform filter** - New `platform` column added to the database (backfilled to `'steam'` for all existing rows). Filter modal supports platform as a select-type filter with options: Steam, GOG, Epic Games, EA App, Ubisoft. PAGYWOSG filter builder automatically prepends `platform = 'steam'`. All game cards carry `data-platform` attribute for platform-aware context menus and launch behavior. Platform navbar dropdown removed - platform is now a filter condition only.
- **Sort direction auto-set** - Changing the sort column now auto-sets direction: name ASC; playtime, release date, date added, review scores DESC; HLTB ASC.
- **Background image opacity control** - Background moved from `body` to `body::before` pseudo-element so opacity can be controlled independently via `--bg-image-opacity` CSS variable. Theme settings now have an Opacity slider (0–100%) alongside the file picker. Default is 1 (fully opaque). (suggested by Propane BLUNTZ)
- **Inter-game delay reduced** - Populate loop delay reduced from 1s to 0.5s (meta worker stays at 1.5s to respect the Steam appdetails rate limit of 200 req/5min).
- **Tampermonkey script v2.4** - GOG orders page support added. Script now matches `https://www.gog.com/en/account/settings/orders*` alongside Steam Help pages. Bulk date import opens the appropriate page(s) based on which platforms are in scope.

### Fixes

- **Context menu "Select All"** now correctly scopes to the right-clicked input field instead of selecting the entire page.
- **Base HTML refactored** - Custom alert/confirm dialog extracted to `_dialog.html`, context menu extracted to `_ctx_menu.html`. `base.html` reduced from 1280 to 646 lines.
- **Modal tools refactored** - HLTB modal extracted to `_modal_hltb.html`. `modal_tools.html` reduced from 4162 to 3631 lines.
- **Negative appid support** - Flask `SignedIntConverter` registered so routes like `/api/game/-1` work for GOG games (which use negative appids). `appid_list` validation now allows zero/negative appids.
- **Install status sync** now scopes Steam install reset to `WHERE platform = 'steam' OR platform IS NULL` - non-Steam install state is managed separately by each platform.
- **`ts_to_date()`** now handles GOG date strings that are already in `'YYYY-MM-DD'` format (returns as-is instead of trying to parse as Unix timestamp).
- **CSS path fix** - Background URL fixed from `/static/img//backgrounds/` (double slash) to `/static/img/backgrounds/`.
- **Gamepad state clearing** - `clearSuppression()` method added to gamepad input manager.

### Changed

- **Edit modal** - The "Steam AppID" row now stays visible for GOG games. Label toggles between "AppID:" (Steam) and "GOG ID:" (GOG), and the display shows `platform_id` for GOG games. Steam store link is hidden for GOG; GOG store link is shown when `platform_slug` is available. "Sync Steam Data" button relabeled to "Sync Data" or "Sync GOG Data" based on platform. Steam-specific fields (Steam Help link, Achievements link, ProtonDB) are hidden for non-Steam games.
- **Bulk date import** - Now handles both Steam and GOG games. The start endpoint splits the queue by platform: Steam games go through the per-page Help flow, GOG games are flagged via `has_gog: true` so the frontend routes them to the GOG orders-page Tampermonkey script. "STEAM DATA" section header renamed to "STORE DATA".
- **PAGYWOSG filter editing** - Opening the filter modal on an already-active PAGYWOSG filter now seeds the tree from the server so editing and re-applying preserves `pagywosg`, `pagywosg_event`, and `pagywosg_verified` keys.
- **Image downloads** - SteamGridDB search by game name (`_sgdb_search_game_id()`) enables art lookups for non-Steam games via SGDB's internal game ID instead of relying on Steam appid. When `sgdb_id` is provided, Steam CDN is skipped and SGDB is queried directly.
- **Library query** - Excludes `duplicate_of IS NOT NULL` by default. `hide_duplicates` boolean in state defaults to `true`.

## v1.3.1 - 2026-04-11

### New
- **PAGYWOSG qualification tooltip** - when a PAGYWOSG filter is active on the library page, hovering over any game card shows a tooltip listing its qualifying categories (with win/backlog label and mod-verified attribution) and its HLTB minimum time. (suggested by kiseli)
- **PAGYWOSG wins group configuration** - the filter builder now detects whether your library contains a "Won on SteamGifts" group. If not, a warning prompts you to choose a substitute group from your existing groups or confirm you have no SteamGifts wins (which omits the wins branch from the filter). Your choice is saved to `state.json` and pre-filled on all future builds. The quals panel in the edit modal reads the group name from the saved filter tree rather than assuming "Won on SteamGifts". (suggested by kiseli)
- **HLTB tool in Tools menu** - HLTB Review has moved from the Bulk Ops modal to a dedicated panel in the Tools menu (hamburger nav), accessible from all pages. The panel now has four collapsible sections: above-threshold unconfirmed, below-threshold unconfirmed, no match found, and confirmed below threshold. No-match games are shown with a search button to find an alternative match.
- **Startup HLTB catch-up scrape** - on launch, after the playtime sync completes, a background pass silently scrapes HLTB data for any games that have never been fetched (does not retry `no_match` games automatically).

### Fixes
- **Home page editor cancel** - clicking "✕ CANCEL" in the home layout editor now fully restores the layout to what it was when editing began. Previously, structural operations (filter changes, splits, unsplits, shelf removal) that auto-saved mid-session were not reverted on cancel.

## v1.3.0 - 2026-04-10

### New
- **HowLongToBeat integration** - Main Story, +Extras, and Completionist times are now scraped and stored per game (in minutes). During populate, games are matched by name against HLTB; matches above the auto-confirm threshold are confirmed automatically, matches below are flagged as unconfirmed. A new HLTB Review tab in Bulk Operations shows unconfirmed matches sorted by score, with a threshold slider, "Confirm all above" button, and "Scrape unfetched / unmatched" to process the rest. The edit modal shows times with Confirm / Other match / Clear / Re-scrape actions and an alt-results panel for manual ID selection. All three time columns are available as filter conditions; a `hltb_min` sort column sorts by the shortest available time, with unscraped games last. (requested by hallak65)

### Fixes
- **Gamepad suppression during gameplay** - gamepad input is now correctly suppressed when a game is launched, preventing unintended inputs in-game and on return to PlayDate. On Linux, a background poller detects when the game process exits and automatically re-enables input; alt-tabbing back also re-enables it. Falls back to click/keypress detection on other platforms.
- **Startup install status flash** - `sync_local_install_status()` committed the reset-to-zero step as a separate transaction before re-setting installed games, creating a window where the home page could see everything as uninstalled. Both steps now run in a single transaction.
- **State file concurrent write corruption** - concurrent Waitress threads could corrupt `state.json` on simultaneous writes. All reads/writes are now guarded with a threading lock and use atomic temp-file replacement.

### Changes
- **Bulk Operations** - button renamed from "BULK EDIT" to "BULK OPS"; tab strip spreads evenly across the header; modal widened to 720px.
- **SQL indexes** - indexes added on `installed`, `completion_status`, `last_played`, and `playtime_forever` for faster filter and sort queries on large libraries. Created automatically on startup.
- **Static asset cache busting** - `style.css`, `playdate.js`, and `input.js` now include the app version as a cache-busting query parameter, ensuring fresh assets are loaded after an upgrade.

## v1.2.8 - 2026-04-08

### New
- **ProtonDB integration** - Linux compatibility ratings are now fetched from ProtonDB. Tier (platinum/gold/silver/bronze/borked) and confidence (strong/good/weak) are stored per game. The edit modal shows a coloured tier badge with a link to the ProtonDB page and a Refresh button; hidden on Windows. ProtonDB data can be fetched for your full library via the Re-scrape tab in Bulk Operations, or for individual games via the Refresh button. Both `protondb_tier` and `protondb_confidence` are available as filter conditions.
- **Bulk Operations modal** - the four separate bulk modals (bulk edit, re-scrape, art scrape, date import) have been replaced by a single tabbed Bulk Operations modal with Edit, Re-scrape, and Date Importer tabs. The Re-scrape tab has separate sub-sections for Steam data and artwork. Closing the modal while a scrape is running no longer blocks it; operations continue in the background.
- **Install status live update** - the home page polls for install status changes every 5 seconds and updates shelf visibility without a full page reload.
- **HLTB search link** - a "Search HLTB ↗" link appears in the edit modal next to the AppID, pre-filled with the game name.
- **Achievements link** - a "↗" link appears inline with the Achievements label in the edit modal, opening your Steam achievement page for that game. Hidden if no Steam ID is configured.
- **Sync Store auto-complete** - syncing store data in the edit modal automatically sets completion status to Completed when achievement counts show 100%.
- **PAGYWOSG quals self-verifier** - a SteamGifts username field has been added to account settings. When a game in the qualifications panel was submitted for mod verification by you, it shows "mod verified - already submitted" instead of directing you to someone else's entry.

### Fixes
- **Startup install status sync** - games uninstalled while PlayDate was closed are now corrected automatically on launch.

### Changes
- **Filter conditions** - artwork source filters moved to the bottom of the condition list. ProtonDB tier and confidence added.
- **Artwork cache busting** - library grid cards and home page shelf capsules update immediately after any artwork save without requiring a page reload.
- **Art source backfill** - games with art marked as fetched but missing source columns are now backfilled on startup.
- **Initial config modal** - renamed to "Configuration"; API key label updated from "Optional" to "Recommended" with an explanation of what each mode provides.
- **Account settings** - Steam API key "(recommended)" label now shows a tooltip describing what the key enables.
- **PAGYWOSG filter performance** - large appid pools use a dedicated node type instead of raw SQL, significantly improving filter build and apply speed for events with thousands of verified games.
- **PAGYWOSG filter builder** - duplicate filter name check on save prompts Replace or Rename. Self-verifier label shown in qualifications panel.

## v1.2.7 - 2026-04-07

### New
- **PAGYWOSG filter builder Auto-fill** - PAGYWOSG Filter Builder can now populate itself from the current event via the PAGYWOSG API, detecting tags, date conditions, appid/title patterns, and mod-verified games. An "Auto-fill from Upcoming Event" button is also available for next-month prep. A collapsible "additional games included" section shows mod-verified library games that wouldn't already qualify through the filter's other criteria.
- **PAGYWOSG qualifications panel** - the edit modal now shows which PAGYWOSG categories a game qualifies for when a PAGYWOSG filter is active, including pool labels (`(win)` for wins-only, `(win)`/`(backlog)` for all-games based on SteamGifts win status). Mod-verified entries show the original submitter so you can cite their entry as proof.
- **PAGYWOSG icaio category support** - categories like "Any game icaio has made a GA for" are automatically populated using icaio's giveaway history and wishlist, bundled with the app.
- **PAGYWOSG filter name** - auto-populated with the event name (e.g. "PAGYWOSG April 2026")

### Changes
- **PAGYWOSG filter modal** - restructured with fixed header/footer with scrollable middle so the Save/Close buttons are always accessible without scrolling.

## v1.2.6 - 2026-04-05

### New
- **Date import overhaul** - the bulk date import no longer switches tabs for every game. It now stays on a single Steam Help page and fetches each game's date in the background, showing a live per-game log as results come in. The userscript no longer requires Tampermonkey Manifest V2.
- **Auto-complete fix** - games with 100% achievements are now correctly marked Completed on startup, even if the achievement data was imported via BLAEO rather than the Steam API (reported by CrabdaddyLonglegs)

### Changes
- **Library grid** - edge cards are no longer clipped by the grid's paint boundary
- **Filter modal** - the field selector and value input are now equal width

## v1.2.5 - 2026-04-05

### New
- **Steam account mismatch check** - the date import userscript now reads the logged-in Steam account from the help page and compares it against the active PlayDate account. If they don't match, the import is aborted with a clear error banner.
- **Tampermonkey script detection** - when starting a bulk date import, PlayDate now waits up to 5 seconds for the userscript to ping back. If no ping is received, the import is automatically cancelled with an error message telling you to install the script or enable Manifest V2.

### Changes
- **Userscript renamed** - `playdate_date_import.user.js` is now `steam_date_import.user.js`
- **Bulk edit modal** - the completion status field now shows a dropdown with all five valid statuses instead of a plain text input; tag, group, genre, and category fields now show a pill input with autocomplete suggestions
- **Filter fix** - custom SQL expressions that divide integer columns (e.g. `unlocked_achievements / total_achievements`) now automatically cast to real arithmetic so the result is a decimal instead of always 0

## v1.2.4 - 2026-04-04

### New
- **Populate overhaul** - art, metadata, and achievement scraping now run as concurrent worker pools. Game cards appear immediately as placeholders and fill in live as each phase completes. Cards visible in the viewport are prioritized.
- **BLAEO pre-scrape** - when populating, PlayDate now runs a BLAEO sync concurrently with the art/metadata workers. Achievement workers start after it finishes and skip any games BLAEO already covered.

### Changes
- Art worker now skips re-downloading images that already exist on disk

## v1.2.3 - 2026-04-03

### New
- **Filter Import / Export** - save any filter to a `.json` file and import it on another machine or share it with others. Available under Tools → Filter Import / Export. (suggested by kiseli)

### Bug fixes
- **Fixed: populate failing on Windows for some users** - ACF manifest files containing game names with non-ASCII characters (e.g. Japanese, Chinese) caused a `UnicodeDecodeError` that crashed the entire populate operation. (reported by kiseli)
- **Fixed: fullscreen state not saving on exit** - toggling fullscreen and then closing the app would revert to fullscreen on next launch. The state is now saved reliably on close.

## v1.2.2 - 2026-04-02

### Bug fixes
- **Fixed: application log not being written on Windows** - `playdate.log` was being written into the PyInstaller temporary extraction folder instead of next to the `.exe`, making it invisible. Errors during populate and other operations were silently disappearing as a result. The log now correctly appears in the install folder. (reported by kiseli)
- **Fixed: gamepad inputs leaking out of launched games into PlayDate** - PlayDate continued polling the gamepad while a game was running, causing buttons pressed in-game to register as PlayDate inputs (launching additional games in the background). The gamepad poller now pauses when the PlayDate window loses focus and resumes cleanly when you return to it.

### Improvements
- **Windows installer now defaults to `C:\Users\<you>\PlayDate`** - previously defaulted to a folder inside AppData which caused errors for some users. You can still choose any location during install. (reported by hallak65)

## v1.2.1 - 2026-04-01

### Bug fixes
- **Linux: fixed false "WebKit2GTK missing" error on Fedora/Nobara** - the startup check introduced in v1.2.0 used a hardcoded version string (`4.0`) that doesn't match what Fedora ships (`4.1`), causing PlayDate to refuse to launch on a working system. The check now tests by importing pywebview directly, which is the actual requirement.

---

## v1.2.0 - 2026-04-01

### Improvements
- **Uninstaller overhaul** - the uninstaller now defaults to deleting the entire PlayDate folder, which is the behaviour you'd expect from any normal program uninstall. Individual user data files (`config.json`, `state.json`, `theme.json`, `games.db`, `playdate.log`) are still presented as opt-out checkboxes if you want to keep them. `theme.json` was previously missing from the list entirely and has been added. Folder deletion is deferred until after the uninstaller window closes so the script can finish cleanly.
- **Update checker moved to hamburger menu** - the Check for Updates / Install Update button has been moved from the Settings modal to the bottom of the hamburger menu, where it's more accessible. The Auto-check Updates toggle remains in Settings. The notification dot on the hamburger button is now dismissed the first time you open the menu - it alerts you once, then gets out of the way.
- **Linux: missing WebKit2GTK is now caught and explained** - if WebKit2GTK isn't installed, the installer catches it specifically (previously it only checked for the base GObject bindings, which can be present without WebKit). If you skip the installer and run `main.py` directly, a clear error dialog now appears with the exact install command for your distro instead of a cryptic crash.
- **Navbar** - Pick page link renamed to "PICK 6".

---

## v1.1.18 - 2026-04-01

### Improvements
- **Edit modal reorganized** - fields are now arranged in three columns (game info, stats/metadata, artwork) for a more compact, balanced layout. Tags, Groups, Categories, and Genres scroll independently within fixed height limits so the modal stays a consistent size regardless of how many pills are present.

---

## v1.1.17 - 2026-04-01

### Improvements
- **BLAEO sync no longer requires Chrome** - the scraper now uses cursor-based HTTP pagination instead of Selenium, removing the Google Chrome dependency entirely. Sync is also significantly faster.
- **BLAEO error handling** - syncing without a BLAEO account now surfaces a clear error message instead of silently reporting 0 games updated.

---

## v1.1.16 - 2026-03-31

### New Features
- **Date part filtering** - filter conditions on release date, date added, and last played now support "month is", "day is", and "year is" operators, making it easy to find games released in a specific month or on a particular day without needing a custom SQL expression.
- **AppID filter condition** - AppID is now available as a filterable column in both the filter builder and the PAGYWOSG filter builder.
- **PAGYWOSG filters save as editable trees** - filters saved from the PAGYWOSG builder are now stored as proper filter trees instead of raw SQL, so they can be opened and edited in the advanced filter builder like any other saved filter.

### Improvements
- **Filter modal save/rename/delete** now use an inline dialog instead of browser popups (`prompt`/`confirm`/`alert`), which could hang or misbehave in the desktop window.
- **Ungroup in advanced filter builder** - removing a parent group now promotes its children to the parent level instead of deleting them.
- **Weighted review percentage formula** updated to a continuous confidence-interval approach: scores are pulled toward 50% (neutral) based on review count, with a smooth curve rather than hard thresholds.
- **Library scroll performance** - cards now use a virtual grid with HTML caching, deferred image loading (200ms after scroll, immediate on page load), and paint containment, reducing choppiness when scrolling large libraries.
- **Filter modal height** capped at 82vh with a flexbox fix (`min-height: 0`) so the saved filters row and action buttons are always visible regardless of how many conditions are in the builder.

### Bug Fixes
- Fixed loading a tree-based saved filter in the filter builder not clearing a previously active custom SQL expression, causing the old SQL to silently override the new filter.
- Fixed PAGYWOSG filters with an AppID condition returning 0 results - `appid` was missing from the SQL safety whitelist, causing the entire WHERE clause to be rejected.

---

## v1.1.15 - 2026-03-31

### New Features
- **Startup playtime sync now updates achievements and completion status** - when playtime has changed since the last launch, PlayDate fetches fresh achievement data (requires API key) and automatically promotes games from `Never Played` → `Unfinished` or any status → `Completed` on 100% unlock. `Beaten` is never downgraded.
- **BLAEO sync now imports achievement data** - syncing with BLAEO now also saves unlocked and total achievement counts from the BLAEO games page, no API key required.

### Bug Fixes
- Fixed single-game refresh (edit modal) not fetching achievements for users with multiple Steam accounts configured - it was reading the API key from the wrong place.

### Improvements
- Saving a filter in the PAGYWOSG Filter Builder now immediately adds it to the saved filters dropdown without requiring a page reload.

---

## v1.1.14 - 2026-03-30

### New Features
- **Steam date importer userscript** (`playdate_date_import.user.js`) - a Tampermonkey script that automatically scrapes the earliest activation date from a Steam help page and sends it to PlayDate. Requires Tampermonkey in MV2 mode.
- **Single-game mode:** clicking the ↗ link next to Date Added in the edit modal opens the Steam help page; the script sends the date back and the field populates automatically. The tab closes once PlayDate has received it.
- **Bulk date import:** new "Import Dates from Steam" button in the bulk edit modal. Opens a single browser tab that automatically navigates through each selected or filtered game, scrapes its date, saves it to the database, and closes when done. Progress is shown in real time.

---

## v1.1.13 - 2026-03-29

### Bug Fixes
- Re-scrape Steam Data in bulk edit modal now works (was silently failing every time due to a bad column reference and broken API key lookup)
- Populate PlayDate progress counter no longer includes DLC, mods, advertising, and other non-game entries in the total
- Non-game entries are now auto-blacklisted on first populate so they're permanently excluded from future runs
- Fixed inability to type spaces in the custom SQL filter input
- Review scores now correctly show for "Profile Features Limited" games
- "No Reviews" now correctly distinguished from "Not Enough Reviews"
- Update check no longer fires twice on startup
- Newly added games now default to 0/0 achievements instead of NULL

### Improvements
- Logging overhauled: third-party library noise suppressed; all PlayDate scraper output now goes to `playdate.log`; long lines truncated; log rotation keeps one backup
- Store type is logged when a game is added, to help identify Proton/tool app types for future filtering
- Art downloads are skipped for non-game entries (was fetching art before checking type)
- Review API now uses `language=all` and `purchase_type=all` for accurate counts

### UI
- "Cancel" → "Close" on bulk edit, bulk re-scrape, bulk artwork, and bulk delete modals
- Delete game dialog now shows "Delete" and "Blacklist and Delete" instead of "Cancel" and "OK"
- Date Added label in edit modal has a "↗" link to the Steam support page for that game
- Filter modal now includes Total Reviews and Positive Reviews as filterable fields

---

## v1.1.12 - 2026-03-28

### Multiple Steam Accounts
PlayDate now supports multiple Steam accounts. Each account gets its own separate library database, so switching between them never mixes your data.

Account management lives in **Settings → Account**: edit your Steam ID, API key, and nickname label; add additional accounts; or remove ones you no longer need. The Detect button reads your local Steam installation and presents any accounts it finds by persona name - no API key required.

Backup and restore now includes all account databases, and the migration from single-account to multi-account happens automatically on first launch - your existing library is preserved.

### Settings UI
The Account section in Settings is now a dedicated sub-modal, consistent with how Background Image and Theme work. The SteamGridDB key is shared across all accounts and lives in the same modal.

---

## v1.1.11 - 2026-03-28

### Menu Overhaul
The hamburger menu has been reorganized into two dedicated modals - **Settings** and **Tools** - making it easier to find what you're looking for. (suggested by Propane BLUNTZ)

**Settings** brings together account configuration and appearance options in one place. You can now update your Steam ID, Steam API key, and SteamGridDB API key directly from the UI, with password-style fields and reveal toggles for the API keys. (suggested by liquidlazor)

**Tools** groups all library utilities into logical sections: backup/restore and import tools, external sync features (PAGYWOSG and BLAEO), and blacklist management.

### Theme Editor Improvements
The theme editor has been overhauled with more granular control - 18 individual CSS variables across grouped categories (Backgrounds, Text, Accent, Borders, Status) replacing the previous coarser set. Each variable has a per-variable reset button to revert individual colors to default without resetting the whole theme.

The live preview has been updated to better reflect the current state of the app, and is larger and easier to read. Closing the theme editor without clicking **Apply Theme** now discards any unapplied changes.

Built-in presets and a saved themes system let you store, load, rename, and delete named themes.

---

## v1.1.10 - 2026-03-28

### Import Date Added from Playnite
If you're migrating from Playnite, you can now import your "date added" history into PlayDate. Point it at a Playnite backup ZIP and it will match games by Steam AppID, filling in your library's date added field for any games it finds. Games not already in your PlayDate library are skipped.

---

## v1.1.9 - 2026-03-28

### Steam API Key Now Optional
PlayDate no longer requires a Steam Web API key to import your library. Without one, your library is read directly from local Steam files - played games and playtime from `localconfig.vdf`, names from installed game manifests and Steam's local metadata cache. Store metadata, reviews, and tags are still fetched from the web as before. Achievements require an API key.

### Other Improvements
- Startup playtime sync now reads from local Steam files instead of requiring an API key
- Rate limiting detection: if Steam returns a rate limit response during import, PlayDate pauses and retries automatically. If the rate limit persists, the import stops and alerts you rather than silently skipping games
- Home page "Recently Added" and "Recently Released" shelves now show unbeaten games instead of only never-played games, so they populate correctly for users with small libraries
- Edit modal now shows a "Browse SGDB ↗" link when no SteamGridDB key is configured, making it easy to find and paste a custom image URL
- Images pasted from SteamGridDB in the edit modal are now saved with the correct source label
- Fixed single-game rescrape overwriting the game name, playtime, and last played date with empty values when no API key is present
- Layout editor "Exit Editor" button renamed to "Cancel" and now correctly discards unsaved changes

---

## v1.1.8 - 2026-03-25

### Auto-Updates
PlayDate can now check for new versions automatically on startup. When an update is available, a dot appears on the **☰** menu button. Click **Install Update** from the menu to apply it - on Windows the new installer runs automatically; on Linux/macOS the update is extracted in place and the app restarts. Automatic checking can be toggled off from the menu. (prompted by feedback from liquidlazor)

---

## v1.1.7 - 2026-03-25

### Settings Menu
The Tools page has been removed. All tools are now accessible from a **☰** dropdown in the nav bar, styled to match the HOME / LIBRARY / PICK 6 links.

### Improved Gamepad Navigation
Modals and dropdown lists now have improved gamepad support. Dropdown lists (saved filters, custom selects, the settings menu) can be opened, navigated, and confirmed or dismissed with the controller. Focus is better preserved when entering and exiting dropdowns, and navigation boundaries are more reliably enforced.

---

## v1.1.6 - 2026-03-25

### New Features
- **New values added via pill fields are immediately available.** After saving a game, any new tags, groups, genres, or categories you entered are instantly available in both the edit modal's autocomplete suggestions and the filter builder - no reload required. (reported by liquidlazor)

### Bug Fixes
- **Dropdown menus no longer stay open when switching programs.** All dropdown lists have been replaced with custom-built menus that respect window focus - they close immediately when you switch to another app.
- **Horizontal grid no longer shows the wrong image after saving.** Editing a game while in horizontal view previously reloaded the card with the vertical image. It now uses whichever orientation is active.

### Improvements
- **Horizontal card size slider now works consistently.** The card size slider previously made horizontal game cards much smaller than vertical ones at the same setting. The slider now controls card height uniformly across both orientations.
- **Populate no longer refreshes the page unnecessarily.** The page only reloads after a populate run if at least one new game was added.
- **Pill input fields now show how to add values.** Tags, groups, genres, and categories fields display a hint explaining that you can type a value and press Enter to add it. (reported by liquidlazor)

---

## v1.1.5 - 2026-03-24

### New Features
- **Horizontal card view.** The library page now supports a horizontal image layout. Toggle between vertical and horizontal with the new button in the toolbar.
- **Adjustable card size.** A slider in the library toolbar lets you resize game cards to your preference.
- **Icon scraping.** Game icons are now downloaded and stored alongside cover art.
- **Horizontal cover art.** Horizontal images are now fetched and stored separately from vertical capsule art.
- **Hi-res cover art.** PlayDate now prefers 2x resolution images where available, falling back to standard resolution.
- **Improved SteamGridDB browser.** The artwork browser now searches by game name automatically when Steam lookup returns no results. You can also manually search any game name to pull artwork from SteamGridDB's full catalog.

---

## v1.1.4 - 2026-03-23

### Bug Fix
- **Windows: game card images now display correctly.** Cover art was being saved next to the `.exe` but Flask was serving static files from inside the PyInstaller bundle - a different directory. Added explicit routes so covers and the custom background image are served from the correct location.

---

## v1.1.3 - 2026-03-23

### New Metadata Fields
- **Genres, Categories, and Free to Play** are now scraped from Steam and stored for every game. Existing games can be updated via Sync Steam Data in the edit modal, or by re-scraping from the bulk edit toolbar. (prompted by feedback from liquidlazor)
- All three fields are available as filter conditions in the Library filter builder and custom SQL, and can be edited via the edit modal and bulk edit.

### Edit Modal
- **Pill inputs** replace plain text fields for Tags, Genres, Categories, and Groups - values display as removable chips, new values are added by typing and pressing Enter or comma, and autocomplete suggestions are drawn from your existing library data across all pages.
- **Layout redesign** - fields are reorganised into clearer groups: identity info (title, developer, publisher, release date, free to play) and user tracking (status, installed, dates, playtime, achievements, reviews) in the two columns, with Tags, Genres, Categories, and Groups below.

### Bulk Re-scrape
- **Stop button** - long bulk re-scrape operations can now be cancelled mid-run. The stop button appears during scraping and halts after the current game finishes. The modal also blocks accidental closure while a scrape is in progress.

---

## v1.1.2 - 2026-03-22

### Changes
- **Steam API key is now required** - Steam's authentication wall broke unauthenticated access to the games list, which also caused Populate PlayDate to fail for users without a key. The config form now requires an API key upfront, with a direct link to get one free in ~2 minutes. (reported by liquidlazor)
- **Library populates automatically on startup** - Populate PlayDate runs once per session in the background on launch, and immediately after first-time setup completes. (suggested by liquidlazor)
- **Config modal re-opens for existing users without an API key** - upgrading users are prompted to add their API key, with existing Steam ID and SteamGridDB key pre-filled. (reported by liquidlazor)
- **Restore from backup added to config screen** - users can skip setup entirely by restoring a previous backup directly from the configuration modal.

### Tools Page
- Reordered: Edit Home Layout → Blacklist Manager → Backup & Restore → Import DB → Background Image → PAGYWOSG → BLAEO Sync → CSV Export → Theme Editor (prompted by feedback from liquidlazor)

### Internal
- Removed F9 gamepad debug overlay

---

## v1.1.1 - 2026-03-22

### Bug Fixes
- **Fixed startup crash on Windows** - selenium was imported unconditionally at module load, causing a `ModuleNotFoundError` on startup for users who don't have selenium installed. Imports are now deferred inside `scrape_blaeo_games()` so they only load when BLAEO sync is triggered. (reported by liquidlazor)
- **Improved BLAEO sync error message** - if Chrome is not installed, users now see a clear explanation and a link to download it, instead of a raw `WebDriverException`.

---

## v1.0.0 - 2026-03-12

### New Features

- Initial release for Windows.
- Steam library sync: scan your Steam library and import games automatically.
- Cover art fetched from Steam CDN and SteamGridDB.
- Completion tracking: Never Played, Unfinished, Beaten, Completed, Won't Play.
- Pick 6: weighted random game picker based on your taste profile.
- Filter builder: build and save complex library filters.
- Home page shelves: customizable shelves with saved filters and sort options.
- BLAEO sync: import completion status from your BLAEO profile.
- ProtonDB ratings for Linux compatibility.
- SGDB API key support for expanded cover art.
