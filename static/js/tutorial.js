// -- Tutorial modal --------------------------------------------------------
// Table of contents + per-section step cards. Content authored here is trusted
// static copy (not user/API data), so step bodies are assigned via innerHTML
// to allow basic formatting rather than run through escHtml().

const TUTORIAL_SECTIONS = [
    {
        id: 'getting-started',
        title: 'Getting Started',
        steps: [
            {
                title: 'Welcome to PlayDate',
                body: `<p>PlayDate is a local game library manager for your Steam collection, with optional support for GOG, Epic, and other non-Steam launchers through plugins.</p>
                       <p>This tutorial is a quick tour of everything - jump to any section from the list, or work through it top to bottom. You can reopen it anytime from the hamburger menu (☰) → Tutorial.</p>`,
            },
            {
                title: 'Three main pages',
                body: `<p>The nav bar at the top always has three pages:</p>
                       <ul>
                         <li><strong>Home</strong> - curated shelves of games (Recently Played, Unfinished, and whatever else you set up).</li>
                         <li><strong>Library</strong> - your full collection, with filters and bulk tools.</li>
                         <li><strong>Pick 6</strong> - a "what should I play next" picker.</li>
                       </ul>
                       <p>Everything else - settings, plugins, emulators, backups - lives behind the hamburger button (☰) in the top-left.</p>`,
            },
            {
                title: 'Gamepad friendly',
                body: `<p>Every menu, modal, and library view in PlayDate can be driven entirely with a gamepad - this app is built with Steam Deck in mind. D-pad/stick to move, A to confirm, B to back out.</p>
                       <p>Gamepad support can be toggled, remapped, or diagnosed from the hamburger menu → System.</p>`,
            },
        ],
    },
    {
        id: 'home-shelves',
        title: 'Home & Shelves',
        steps: [
            {
                title: 'What are shelves?',
                body: `<p>The Home page shows your library as a set of horizontal shelves - each one a filtered, sorted row of games, like "Unfinished," "Recently Added," or a random pick.</p>`,
            },
            {
                title: 'Editing the layout',
                body: `<p>Hamburger menu → <strong>Edit Home Layout</strong> lets you add, remove, and reorder shelves, choose what each one shows (a saved filter or a built-in one), how it's sorted, and whether two shelves sit side by side.</p>`,
            },
            {
                title: 'Random shelves',
                body: `<p>Set a shelf's sort to <strong>Random</strong> to get a fresh random set of games. A shelf sorted this way shows a shuffle icon (↻) next to its title - click it to reroll that shelf without leaving the page.</p>`,
            },
        ],
    },
    {
        id: 'library-filters',
        title: 'Library & Filters',
        steps: [
            {
                title: 'Grid or list view',
                body: `<p>The Library page defaults to a scrolling grid of cover art. Switch to <strong>list view</strong> from the VIEW menu for a compact, split-pane layout - a scrollable row list on the left and a detail/edit pane on the right, good for quickly working through a lot of games.</p>`,
            },
            {
                title: 'Building a filter',
                body: `<p>The filter builder lets you combine conditions - tags, genres, completion status, release date, playtime, and more - into AND/OR groups. Save a filter once you've built it, and it becomes available as a shelf, or reusable anytime from the Library page.</p>`,
            },
            {
                title: 'Bulk operations',
                body: `<p>Select multiple games in the grid (or list view) and use <strong>Bulk Ops</strong> to edit tags/status across all of them at once, or re-scrape metadata and cover art in bulk.</p>`,
            },
        ],
    },
    {
        id: 'date-import',
        title: 'Importing Purchase Dates',
        steps: [
            {
                title: 'Why import dates?',
                body: `<p>Steam and GOG don't expose accurate purchase/activation dates through their APIs, so PlayDate can pull them from your account's own history pages instead, using a companion browser userscript (needs the Tampermonkey extension). Install it from <a href="https://github.com/RobbyRatpoison/PlayDate-Library-Manager/raw/refs/heads/main/steam_date_import.user.js" target="_blank">GitHub</a>.</p>`,
            },
            {
                title: 'Single game or bulk',
                body: `<p>Click the ↗ next to <strong>Date Added</strong> in a game's edit panel to import one game's date, or use the Library page's Bulk Ops → <strong>Date Importer</strong> tab to fetch dates for many games at once.</p>`,
            },
        ],
    },
    {
        id: 'pick6',
        title: 'Pick 6',
        steps: [
            {
                title: 'What Pick 6 does',
                body: `<p>Pick 6 answers "what should I play next?" - it weighs six signals (how similar a game's tags are to what you've enjoyed before, review score, how long it's been sitting unplayed, completion history, playtime, and release age) and surfaces six games weighted by that score, not just a strict top list.</p>`,
            },
            {
                title: 'Rerolling and filtering',
                body: `<p>Not feeling any of the six? Reroll for a new set. You can also apply a filter first (e.g. only GOG games, or only under 10 hours) to narrow the pool Pick 6 draws from.</p>`,
            },
        ],
    },
    {
        id: 'pagywosg',
        title: 'PAGYWOSG',
        steps: [
            {
                title: 'What is PAGYWOSG?',
                body: `<p>PAGYWOSG ("Play A Game You Won on SteamGifts") is a monthly community event on SteamGifts. Each event has its own set of category rules - PlayDate can read those live and build a matching filter for you automatically, instead of you checking your library against each category by hand.</p>`,
            },
            {
                title: 'Set your SteamGifts username',
                body: `<p>Some categories only count games <em>verified</em> for a specific player. Set your SteamGifts username in Settings so PlayDate can tell which verified entries are actually yours.</p>`,
            },
            {
                title: 'Building a filter',
                body: `<p>Open the PAGYWOSG tool from the hamburger menu's <strong>Community Tools</strong> section, pick the event, and PlayDate assembles and saves a filter matching that month's rules - ready to use like any other saved filter.</p>`,
            },
        ],
    },
    {
        id: 'plugins',
        title: 'Plugins',
        steps: [
            {
                title: 'Beyond Steam',
                body: `<p>Steam is built into PlayDate directly. Everything else comes from plugins - and PlayDate ships with a handful already built in: GOG, Epic Games, EA App, Ubisoft Connect, Humble Bundle, itch.io, Amazon Games, Battle.net, IndieGala, and Rockstar Games. No separate download needed to use any of them.</p>`,
            },
            {
                title: 'Installing and managing plugins',
                body: `<p>Hamburger menu → <strong>Plugins</strong> shows everything bundled in, and also lets you install additional third-party plugins from a zip file or a GitHub URL, check for updates, and uninstall (with the option to remove that platform's games too).</p>`,
            },
            {
                title: 'Duplicate detection',
                body: `<p>Own the same game on two platforms? PlayDate can detect duplicates across all your connected platforms and let you pick which copy stays visible in your library.</p>`,
            },
        ],
    },
    {
        id: 'emulators',
        title: 'Emulators',
        steps: [
            {
                title: 'Tracking emulated games',
                body: `<p>Games you play through an emulator (retro consoles, handhelds, anything outside Steam/GOG/etc.) can be added to PlayDate too, so they show up in your library, shelves, and Pick 6 alongside everything else.</p>`,
            },
            {
                title: 'Adding an emulator',
                body: `<p>Hamburger menu → <strong>Emulators</strong> - pick a platform from the list to use a common preset, or add a custom entry pointing at your own emulator binary.</p>`,
            },
        ],
    },
    {
        id: 'gamepad-settings',
        title: 'Gamepad & Settings',
        steps: [
            {
                title: 'Controls',
                body: `<p>D-pad or the left stick moves focus, A confirms/activates, B backs out or closes a menu. This works the same way everywhere - home shelves, the library grid, every modal.</p>`,
            },
            {
                title: 'Configuring gamepad input',
                body: `<p>Hamburger menu → <strong>System</strong> has the gamepad toggle, button remapping, and a diagnostics view if a controller isn't behaving the way you expect.</p>`,
            },
            {
                title: 'More settings',
                body: `<p>Also worth knowing about: <strong>Appearance</strong> (theme colors, background image) and <strong>Data</strong> (backup/restore, CSV export, imports), both in the hamburger menu.</p>`,
            },
        ],
    },
];

function openTutorialModal(sectionId) {
    document.getElementById('tutorial-modal').style.display = 'flex';
    if (!window._TUTORIAL_SEEN) {
        window._TUTORIAL_SEEN = true;
        fetch('/api/tutorial/seen', { method: 'POST' }).catch(() => {});
    }
    // Always render the ToC first (and size the modal to it, see
    // _tutShowToc()) even when opening straight into a section, so the
    // locked height is always the ToC's own natural height.
    _tutShowToc();
    if (sectionId) {
        _tutShowSection(sectionId, 0);
    }
}

function closeTutorialModal() {
    document.getElementById('tutorial-modal').style.display = 'none';
}

let _tutSection = null;
let _tutStep = 0;

function _tutShowToc() {
    _tutSection = null;
    _tutStep = 0;
    document.getElementById('tutorial-section-view').style.display = 'none';
    document.getElementById('tutorial-toc').style.display = 'block';
    _tutRenderToc();

    // Lock the modal to whatever height the ToC naturally takes up, so
    // switching to a step view (text length varies a lot between steps)
    // never resizes the modal or moves the Back/Sections/Next row.
    // Re-measured every time in case the section count ever changes.
    const modalContent = document.getElementById('tutorial-modal-content');
    modalContent.style.height = 'auto';
    const h = modalContent.getBoundingClientRect().height;
    modalContent.style.height = h + 'px';
}

function _tutRenderToc() {
    const toc = document.getElementById('tutorial-toc');
    toc.innerHTML = TUTORIAL_SECTIONS.map((s, i) =>
        `<button class="settings-item" data-modal-row="${i}" onclick="_tutShowSection('${s.id}')" style="justify-content:center; text-align:center;">${escHtml(s.title)}</button>`
    ).join('');
}

function _tutShowSection(sectionId, stepIndex) {
    const section = TUTORIAL_SECTIONS.find(s => s.id === sectionId);
    if (!section) return;
    _tutSection = section;
    _tutStep = Math.max(0, Math.min(stepIndex || 0, section.steps.length - 1));

    document.getElementById('tutorial-toc').style.display = 'none';
    document.getElementById('tutorial-section-view').style.display = 'flex';

    _tutRenderStep();
}

function _tutRenderStep() {
    const section = _tutSection;
    const step = section.steps[_tutStep];

    document.getElementById('tutorial-step-progress').textContent =
        `${section.title} - Step ${_tutStep + 1} of ${section.steps.length}`;
    document.getElementById('tutorial-step-title').textContent = step.title;
    document.getElementById('tutorial-step-body').innerHTML = step.body;

    document.getElementById('tutorial-next-btn').textContent =
        _tutStep === section.steps.length - 1 ? 'Done' : 'Next';
}

function _tutNext() {
    if (!_tutSection) return;
    if (_tutStep < _tutSection.steps.length - 1) {
        _tutStep++;
        _tutRenderStep();
    } else {
        _tutShowToc();
    }
}

function _tutBack() {
    if (!_tutSection) return;
    if (_tutStep > 0) {
        _tutStep--;
        _tutRenderStep();
    } else {
        _tutShowToc();
    }
}
