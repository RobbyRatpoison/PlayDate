# Contributors

People who've helped make PlayDate better - bug reports, feature suggestions, testing, and other contributions outside the commit history.

**86maylin**
- BLAEO sync not populating Won't Play; idled-for-cards games misreported as Unfinished
- Confusing duplicate "Beaten" quick filter buttons
- BLAEO confirmation list too long to use, not scrollable
- Feedback prompted running BLAEO sync in the background with a ready notification
- Steam Collections sync only picking up Favorites (21 of 31 games)
- Suggested syncing Steam Collections into groups, merged with BLAEO lists by name

**ArchelonGaming**
- Reported grid-view games launching/installing from accidental clicks (mousedown, drag off the card and back, release) while scrolling and syncing - led to an opt-in double-click-to-launch/install setting
- Suggested blacklisting a game directly from the right-click menu - led to a Delete Game context-menu item instead, using the existing delete-and-optionally-blacklist prompt
- Suggested platform and installed-status badges on game cards - led to the Card Badges feature (Appearance menu)
- Requested Amazon Games and LegacyGames.com support (Amazon skipped for now - already a stuck effort; LegacyGames.com noted as a future research item)

**Blue™**
- Couldn't find where to view/filter games synced from Play or Pay - led to Play or Pay generating a saved filter automatically, matching how PAGYWOSG does it
- PAGYWOSG tags showing as one combined line in the tooltip/game-edit panel instead of one line per tag
- Edit Game popup silently failing to open for some games (PAGYWOSG-qualifying games with an SG username set)
- A PAGYWOSG filter with a multi-group condition breaking the edit panel and the hover match display

**bluemoon55127**
- Suggested type-ahead jump-to-letter navigation in filter dropdowns

**CrabdaddyLonglegs**
- `protondb_fetched` crash on update
- `duplicate_auto` crash on every reboot
- 100%-achievement games not auto-marked Completed
- Helped test/confirm a migration crash fix

**DarkRainX**
- Gentoo install failing to detect WebKitGTK 6.0/GTK4; also pointed at the fix
- Secondary Steam library games not recognized as installed; suggested reading `libraryfolders.vdf`
- Date filter "on (exact)" / "matches pattern" broken
- "Hide duplicate entries" not applying to Home page shelves
- GOG games' release dates sorting before/after all Steam games instead of interleaving chronologically
- IndieGala library sync only fetching the first page
- IndieGala library sync still stuck re-fetching page one after the previous fix; found and supplied the actual URL fix
- IndieGala's "View on IndieGala" link pointing to a broken, merged URL
- IndieGala store links only working for GalaFreebies picks, not games made free directly by developers

**devonrv**
- Pointed out the name collision with the Playdate handheld console

**Fluffster**
- Suggested "Playground" or "Playtime" as alternative names

**fernandopa**
- Right-click context menu cropping near screen edges
- Helped test/confirm a launch-crash fix live
- Suggested the dice button and a fixed/sticky library toolbar
- Suggested achievement-based filtering and a completion overlay (not implemented)
- Update-install confirmation suggesting a backup every time, even right after making one - led to a 24-hour cooldown after a completed backup

**hallak65**
- Installer defaulting to AppData, causing errors
- Requested HLTB times and Steam library sync
- Suggested "Steam Playtime Manager" / "Steam Game Manager" as names

**ImpAtience**
- itch.io and IndieGala sign-in popups closing before completing login on the Windows portable build

**inmate66**
- Riffed "SCP-3" off the S-CPE name suggestion

**kiseli**
- Populate failing entirely on Windows with no log output
- Custom-named SG wins group not recognized as default
- PAGYWOSG tooltip missing reasons for two category types
- Suggested an API-key test button in Settings (not implemented)
- Suggested PAGYWOSG filter export/import
- Suggested a PAGYWOSG hover tooltip and a configurable SG-wins group name
- Suggested a persistent bulk-operation progress indicator

**Limbert**
- Steam Collections not syncing to groups at all; traced to the wrong Steam `userdata` account folder being auto-detected on a PC where more than one Steam account had logged in

**liquidlazor**
- Startup crash from an unconditional selenium import
- Populate failing with an empty library when no API key was set
- Couldn't return to the API key screen after skipping it in setup
- "Save Changes" silently discarding a typed group/tag if Enter/comma wasn't pressed first
- New custom groups not appearing as filter options
- Suggested reordering the Tools page so niche tools sit lower
- Suggested custom categories (play priority, co-op, AAA, etc.) - already covered by Groups
- Suggested excluding free-to-play games with in-app purchases
- Suggested surfacing player counts for dead multiplayer games (not implemented)
- Brainstormed the List view (list + detail pane, "like how Steam looks")
- Suggested showing game names above/below cover art (not implemented)
- Suggested moving API keys into Settings, editable after initial setup
- Repeated manual-update hassle prompted the in-app update checker

**Meneldur**
- Startup crash from a missing plugins folder after downgrade/upgrade
- `ModuleNotFoundError: runners.watcher` crash from missing PyInstaller bundle modules

**Nexal**
- Suggested "Steam Cross Platform Environment" (S-CPE) as a name

**greatmastermario**
- Reported missing Linux install dependencies on Ubuntu 24.04 (`python3-venv`, `python3-pip`, `python3-tk`), leading to an updated README and a clearer installer error/hint
- Quoted-substring PAGYWOSG AppID categories not being auto-detected
- Suggested tagging Secret Santa/Snowballs gifts with the year given, as evidence for mod verification
- Suggested splitting HLTB library sort into separate Main Story/Main + Extras/Completionist options

**onegoodleg**
- Suggested a completion-status rosette on cards - directly inspired the card-outline feature
- Suggested configurable CSV export columns

**PapaSmok**
- "Pick a random game" not working in List view
- Portable build's update button launching the installer instead of updating in place
- Requested a portable (non-installer) version
- Suggested auto-including Beaten games in PAGYWOSG results
- Requested support for other SteamGifts monthly events - led to the Monthly in a Month tool
- Backup files silently becoming permanently corrupted if PlayDate was closed before a backup finished saving

**Propane BLUNTZ**
- Early pre-release testing on Windows, before the project's git history began
- Suggested a background dimming/transparency slider in settings
- Suggested background scaling options (stretch/fit/tile), similar to Windows desktop background settings (not implemented)
- Suggested splitting the Tools page into Settings (appearance/account) and Tools (library utilities only)
- Reported a Windows Defender false-positive flag on the PyInstaller build (self-resolved; no code fix, a known PyInstaller/code-signing limitation)

**quinnix**
- Epic Games plugin showing "launcher not installed"; login stuck on a blank page
- PAGYWOSG/Monthly in a Month failing with an SSL certificate error
- Suggested surfacing BLAEO/PAGYWOSG more prominently for new users (not implemented)
- Home page shelves not scrolling, hiding any shelves that didn't fit on screen
- A PAGYWOSG saved filter used as a Home shelf showing no games

**samwise84**
- Crash on the installer build after updating to v1.5.6, traced to a missing `meta_fetched` column
- Portable build failing to launch (`Python.Runtime.dll` and other modules missing from the bundle)
- In-place update over an old install erroring, needing a full reinstall
- Suggested bulk-adding a whole BLAEO list to Secret Santa/Snowballs, instead of one game at a time

**zpangwin**
- Contributed a Steam-appid-to-HLTB-id mapping dataset (~3,000 entries), bundled directly into the app
- Linux `install.py` GUI cutting off its bottom buttons
- Pick 6 confusion from a leftover "installed only" filter
- Suggested a PAGYWOSG builder shortcut in the filters dialog
- Suggested filtering by system requirements and by installed storage size (not implemented)
- Suggested "pygamelauncher," an animal-themed name, or "whattoplay"/"wtp"
