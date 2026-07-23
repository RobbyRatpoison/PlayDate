/**
 * input.js — Gamepad navigation for PlayDate
 * Loaded globally via base.html. Self-contained IIFE, no exports.
 */
(function () {
    'use strict';

    // ── Crash detection ───────────────────────────────────────────────────────
    window.addEventListener('error', e => {
        console.error('[input.js] Uncaught error:', e.message, 'at', e.filename, e.lineno);
    });
    window.addEventListener('unhandledrejection', e => {
        console.error('[input.js] Unhandled promise rejection:', e.reason);
    });

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            // A focused text field takes priority over closing the modal
            // underneath it — see the identical check in _handleB() for why:
            // gamescope's on-screen keyboard (Steam Deck) dismisses itself on
            // B, and the same press appears here as a synthesized Escape
            // keydown while a text field has focus, not as a gamepad button
            // press picked up by the RAF poll loop. Without this, that one
            // press both closes the keyboard and the modal underneath it.
            if (_isTextEntryFocused()) {
                document.activeElement.blur();
                return;
            }
            // Close dropdown first — must precede modal checks since the modal is still visible underneath
            if (_state.zone === 'dropdown') {
                _closeAnyOpenModal();
                _syncFocus();
                return;
            }
            // Close edit/filter modals (global close fns, checked first)
            const editModal = document.getElementById('editModal');
            if (editModal && editModal.style.display !== 'none') {
                if (_state.zone === 'modal') _popZone();
                if (typeof closeModal === 'function') closeModal();
                return;
            }
            const filterModal = document.getElementById('filterModal');
            if (filterModal && filterModal.style.display !== 'none') {
                if (_state.zone === 'modal') _popZone();
                if (typeof closeFilterModal === 'function') closeFilterModal();
                return;
            }
            const viewModal = document.getElementById('viewModal');
            if (viewModal && viewModal.style.display !== 'none') {
                if (_state.zone === 'modal') _popZone();
                if (typeof closeViewModal === 'function') closeViewModal();
                return;
            }
            // Close any other open modal (tools page, bulk edit, etc.)
            _closeAnyOpenModal();
            return;
        }
        if (e.key === 'ArrowUp' || e.key === 'ArrowDown' || e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
            // Steam Input's default Desktop Mode controller layout binds the
            // D-pad (not the analog stick) to arrow keys, independent of the
            // Gamepad API polling in _pollLoop() below — which already moves
            // modal focus correctly per zone. Without this, the same D-pad
            // press both navigates the modal (via Gamepad API) and scrolls/
            // moves the page behind it (via the synthetic key's default
            // action), since the browser has no idea a modal is covering it.
            // Skipped while a text field has real focus so actual keyboard
            // users can still move the text cursor normally with arrow keys.
            // The hamburger menu isn't in _anyWatchedOpen()'s registry at all —
            // it's tracked as its own 'dropdown' zone, not a registered modal —
            // so it needs an explicit check here too.
            if ((_anyWatchedOpen() || _state.zone === 'dropdown') && !_isTextEntryFocused()) {
                e.preventDefault();
            }
        }
    });

    // ── Page detection ────────────────────────────────────────────────────────
    const PAGE = (() => {
        const p = window.location.pathname;
        if (p === '/' || p === '') return 'home';
        if (p.startsWith('/library')) return 'library';
        if (p.startsWith('/pick')) return 'pick';
        return 'other';
    })();

    const PAGE_URLS = ['/', '/library', '/pick'];

    function _currentPageIdx() {
        const p = window.location.pathname;
        if (p === '/' || p === '') return 0;
        for (let i = 1; i < PAGE_URLS.length; i++) {
            if (p.startsWith(PAGE_URLS[i])) return i;
        }
        return 0;
    }

    // ── State ─────────────────────────────────────────────────────────────────
    const _state = {
        active:           false,
        zone:             'nav',
        prevZone:         'content',
        prevRow:          null,
        prevCol:          null,
        prevModalFocused: null,  // DOM element saved when pushing sub-zone from modal
        row:              0,
        col:              0,
        savedCol:         0,
        subItem:          -1,
        modalFocused:     null,
        focusedAppid:     null,
        activeInput:      null,
        reorderEl:        null,  // <li> currently held for platform-priority reordering
    };

    // Shelf row currently held for gamepad drag-reorder (separate from _state.reorderEl
    // which is only for modal platform-priority <li> reordering).
    let _shelfGpDragEl = null;

    // Expose focusedAppid so library.html's observeCards can re-apply the class
    window._inputMgr = {
        get focusedAppid() { return _state.focusedAppid; },
        get active() { return _state.active; },
        suppressForGame() {
            _gameSuppressed = true;
            _pgrepsDetected = false;
            safeSession.setItem('pd_game_running', '1');
            _clearGamepadState();
            _watchForGameClose();
            document.dispatchEvent(new CustomEvent('gamepad-suppression-change', { detail: { suppressed: true } }));
        },
        clearSuppression() {
            _gameSuppressed = false;
            safeSession.removeItem('pd_game_running');
            _clearGamepadState();
            document.dispatchEvent(new CustomEvent('gamepad-suppression-change', { detail: { suppressed: false } }));
        },
        // Called by main.py's GTK/Win32 focus handler. Only unsuppresses when
        // pgrep-based detection was never available (non-Steam games on Linux),
        // so Steam games aren't accidentally unsuppressed by launcher gaps.
        focusInUnsuppress() {
            if (!_pgrepsDetected) _unsuppressGamepad('focus-in (no pgrep detection)');
        },
        unsuppressGamepad() {
            _unsuppressGamepad('external call');
        },
        setGamepadEnabled(val) {
            _gamepadEnabled = val;
            if (!val && _state.active) _deactivate();
            _clearGamepadState();
        },
        setButtonRemaps(remaps) {
            _userRemap = {};
            if (remaps && typeof remaps === 'object') {
                for (const [k, v] of Object.entries(remaps))
                    _userRemap[parseInt(k, 10)] = v;
            }
        },
        setCapturing(val) { _capturing = val; },
        // Dynamically register a lazily-created modal (e.g. plugin manage modals)
        registerModal(id) {
            if (_MODAL_IDS.includes(id)) return;
            // Insert before plugins-modal so manage modals close innermost-first
            const pluginsIdx = _MODAL_IDS.indexOf('plugins-modal');
            if (pluginsIdx >= 0) _MODAL_IDS.splice(pluginsIdx, 0, id);
            else _MODAL_IDS.push(id);
            _watchModal(id);
        },
    };

    let _gamepadEnabled = window._GAMEPAD_ENABLED !== false;
    let _capturing      = false; // true while remap modal is waiting for a button press

    let _userRemap = {};
    (function() {
        const r = window._BUTTON_REMAPS;
        if (r && typeof r === 'object') {
            for (const [k, v] of Object.entries(r))
                _userRemap[parseInt(k, 10)] = v;
        }
    })();

    // Track whether a gamepad has ever been seen this session (persisted across page loads)
    let _gpEverSeen = safeSession.getItem('pd_gp_seen') === '1';

    // Stamped whenever input.js focuses a text/number input via the gamepad A
    // button. Steam Deck's on-screen keyboard binds its own confirm gesture to
    // A and dismisses/confirms by synthesizing a real, trusted Enter keydown/
    // keyup on the focused element — indistinguishable from the user actually
    // pressing Enter. Any onkeyup="if (e.key==='Enter') ..." handler elsewhere
    // in the app should check window._inputMgr.justGamepadFocusedInput() first
    // so that gaining focus isn't immediately treated as also submitting.
    let _gpTextFocusAt = 0;
    function _stampGpTextFocus() { _gpTextFocusAt = Date.now(); }
    window._inputMgr.justGamepadFocusedInput = () => (Date.now() - _gpTextFocusAt) < 400;

    // ── Game-running suppression ──────────────────────────────────────────────
    // Set when a game launches; persists across the page reload that follows.
    // Cleared only when the user explicitly interacts with PlayDate (click/key).
    // This is the only reliable way to stop gamepad input while a game is running:
    // the gamepad is shared hardware and focus events don't fire in pywebview.
    let _gameSuppressed  = safeSession.getItem('pd_game_running') === '1';
    let _pgrepsDetected  = false; // true once pgrep returns a non-null result this session

    function _clearGamepadState() {
        _gp.prev          = {};
        _gp.heldSince     = {};
        _gp.lastRepeat    = {};
        _gp.stickDir      = null;
        _gp.stickHeld     = 0;
        _gp.stickRepeat   = 0;
        _gp.rStickHeldSince = 0;
    }

    function _unsuppressGamepad(reason) {
        if (!_gameSuppressed) return;
        _gameSuppressed = false;
        safeSession.removeItem('pd_game_running');
        document.dispatchEvent(new CustomEvent('gamepad-suppression-change', { detail: { suppressed: false } }));
    }

    // Two-phase watcher: polls /api/game-running (checks Steam's reaper process on
    // Linux) to detect when a launched game actually closes, then unsuppresses the
    // gamepad and raises the PlayDate window regardless of where the window manager
    // sent focus after the game exited.
    function _watchForGameClose() {
        let gameStarted = false;
        let notRunningStreak = 0;
        let attempts = 0;
        const MAX_ATTEMPTS  = 90;   // 3 minutes at 2s intervals
        const CLOSE_CONFIRM = 1;    // consecutive not-running polls to confirm game closed

        function poll() {
            if (!_gameSuppressed) return; // already cleared by click
            if (++attempts > MAX_ATTEMPTS) {
                _unsuppressGamepad('watcher safety timeout');
                return;
            }
            fetch('/api/game-running')
                .then(r => r.json())
                .then(d => {
                    if (d.running === null) return; // unsupported platform — focusInUnsuppress() handles it
                    _pgrepsDetected = true;
                    if (d.running) {
                        gameStarted = true;
                        notRunningStreak = 0;
                        setTimeout(poll, 2000);
                    } else if (gameStarted) {
                        notRunningStreak++;
                        if (notRunningStreak >= CLOSE_CONFIRM) {
                            fetch('/api/raise-window', { method: 'POST' }).catch(() => {});
                            _unsuppressGamepad('watcher confirmed close');
                        } else {
                            setTimeout(poll, 2000);
                        }
                    } else {
                        // Game hasn't started yet (Steam loading), keep waiting
                        setTimeout(poll, 2000);
                    }
                })
                .catch(() => { notRunningStreak = 0; setTimeout(poll, 3000); });
        }

        setTimeout(poll, 1000);
    }

    // Also start watching if we're resuming suppressed state from a page reload
    if (_gameSuppressed) _watchForGameClose();

    document.addEventListener('mousedown', () => _unsuppressGamepad('mousedown'));

    // ── Gamepad polling state ─────────────────────────────────────────────────
    const _gp = {
        prev:        {},   // button index → bool
        heldSince:   {},   // button index → timestamp when first pressed
        lastRepeat:  {},   // button index → timestamp of last repeat fire
        stickDir:    null, // current stick direction or null
        stickHeld:   0,
        stickRepeat: 0,
        rStickHeldSince: 0, // timestamp the right stick (scroll) last crossed the dead zone, or 0 while released
    };

    const REPEAT_INITIAL  = 400;
    const REPEAT_RATE     = 150;
    const STICK_DEAD      = 0.35;

    // Right-stick scroll ramp: full speed for the first second (matches the
    // existing feel), then grows exponentially so crossing a 10k+ game
    // library is actually achievable without waiting forever, capped so it
    // never becomes totally uncontrollable.
    const SCROLL_BASE_SPEED  = 20;    // px/frame at full deflection, before ramping
    const SCROLL_RAMP_DELAY  = 1000;  // ms held before speed starts increasing
    const SCROLL_RAMP_GROWTH = 1.8;   // multiplier growth per second of ramp
    const SCROLL_RAMP_MAX    = 12;    // cap on the speed multiplier
    const SCROLL_PREVIEW_MIN = 3;     // only show the position preview once ramped to at least this multiple of base speed

    // ── Standard Xbox/standard-mapping button indices ─────────────────────────
    const BTN_IDX = { a:0, b:1, x:2, y:3, lb:4, rb:5, back:8, start:9, up:12, down:13, left:14, right:15 };
    const AXIS_IDX = { lx:0, ly:1, rx:2, ry:3 };

    // ── Platform-specific button overrides ────────────────────────────────────
    // Each entry maps raw button indices to BTN_IDX action names.
    // Steam Deck back paddles (L4=17, R4=18) are not standard-mapping buttons
    // but the Deck exposes them at those indices in desktop mode.
    const PLATFORM_MAPPINGS = [
        {
            detect: id => /valve|steam deck/i.test(id),
            btns: { 17: 'back', 18: 'x' },
        },
    ];
    let _activeMapping = null;
    let _lastGpId = null;

    // ── Focus indicator helpers ───────────────────────────────────────────────
    function _clearFocus() {
        document.querySelectorAll('.gamepad-focus').forEach(el => {
            el.classList.remove('gamepad-focus');
        });
    }

    function _applyFocus(el) {
        if (!el) return;
        _clearFocus();
        el.classList.add('gamepad-focus');
        // Home edit mode: scroll focused edit-bar buttons into view, accounting for the
        // fixed toolbar that blocks the top of the viewport.
        if (PAGE === 'home') {
            if (document.body.classList.contains('edit-mode')) {
                const toolbar = document.querySelector('.edit-toolbar');
                const navH = toolbar ? toolbar.getBoundingClientRect().bottom : 0;
                const r = el.getBoundingClientRect();
                if (r.top < navH) {
                    window.scrollBy({ top: r.top - navH - 8, behavior: 'smooth' });
                } else if (r.bottom > window.innerHeight) {
                    window.scrollBy({ top: r.bottom - window.innerHeight + 8, behavior: 'smooth' });
                }
            }
            // In normal mode, capsules are always clipped by shelf overflow so no scroll needed.
            return;
        }
        const scroller = document.querySelector('.container');
        // First content row → scroll to very top
        const isFirst = _state.zone === 'content' &&
            (_state.row === 0 || (PAGE === 'library' && _state.row === -1));
        if (isFirst && scroller?.firstElementChild) {
            scroller.firstElementChild.scrollIntoView({ behavior: 'smooth', block: 'start' });
            return;
        }
        // Last content row → scroll to very bottom
        const isLast = _state.zone === 'content' && (() => {
            switch (PAGE) {
                case 'library': return _state.row === _libraryNavItems().length - 1;
                case 'pick':    return _state.row === _pickRows().length - 1;
                default: return false;
            }
        })();
        if (isLast) {
            el.scrollIntoView({ behavior: 'smooth', block: 'end' });
            return;
        }
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
    }

    // ── Focusable item queries ────────────────────────────────────────────────

    function _navItems() {
        // In edit mode the regular nav bar is hidden; use the edit toolbar instead
        if (document.body.classList.contains('edit-mode')) {
            return [...document.querySelectorAll('.edit-toolbar .nav-btn')]
                .filter(el => el.offsetParent !== null && !el.disabled);
        }
        return [
            ...document.querySelectorAll('.nav-links a, .nav-links button'),
            document.getElementById('fullscreen-button'),
            document.getElementById('exit-button'),
        ].filter(el => el && el.offsetParent !== null);
    }

    // Home: returns array of { el, items[] } per navigable row.
    // Proportional fallback: map sourceCol/sourceTotal → nearest col in targetLen.
    function _proportionalCol(sourceCol, sourceTotal, targetLen) {
        if (targetLen <= 1) return 0;
        if (sourceTotal <= 1) return 0;
        return Math.round((sourceCol / (sourceTotal - 1)) * (targetLen - 1));
    }

    // Given a target row index, find the best {rowIdx, colIdx} to navigate to.
    // If the target row is one side of a split row, candidates include items from BOTH sides
    // so Up/Down can cross between left and right split sides by X proximity.
    function _findNavTarget(rows, targetIdx, srcItem, srcCol, srcTotal) {
        const targetRow = rows[targetIdx];
        if (!targetRow) return { rowIdx: targetIdx, colIdx: 0 };

        const targetEl = targetRow.el;
        const splitParent = targetEl?.classList?.contains('shelf-split-side')
            ? targetEl.closest?.('.shelf-split-row') : null;

        // Collect candidates — both split sides or just the target row
        const candidates = [];
        if (splitParent) {
            for (let ri = 0; ri < rows.length; ri++) {
                if (rows[ri].el.closest?.('.shelf-split-row') === splitParent) {
                    rows[ri].items.forEach((item, ci) => candidates.push({ item, rowIdx: ri, colIdx: ci }));
                }
            }
        } else {
            targetRow.items.forEach((item, ci) => candidates.push({ item, rowIdx: targetIdx, colIdx: ci }));
        }

        if (!candidates.length) return { rowIdx: targetIdx, colIdx: 0 };

        // X-proximity across all candidates
        if (srcItem) {
            const sr = srcItem.getBoundingClientRect();
            if (sr.width > 0 || sr.height > 0) {
                const srcCx = sr.left + sr.width / 2;
                let best = candidates[0], bestDist = Infinity;
                for (const c of candidates) {
                    const r = c.item.getBoundingClientRect();
                    const cx = r.left + r.width / 2;
                    const dist = Math.abs(cx - srcCx);
                    if (dist < bestDist) { bestDist = dist; best = c; }
                }
                return { rowIdx: best.rowIdx, colIdx: best.colIdx };
            }
        }

        // Fallback: proportional within the directly targeted row
        return { rowIdx: targetIdx, colIdx: _proportionalCol(srcCol, srcTotal, targetRow.items.length) };
    }

    // In normal mode: capsule wraps per shelf. In edit mode: edit-bar buttons per shelf.
    // Split rows are always expanded to their individual .shelf-split-side children.
    function _homeRows() {
        const container = document.getElementById('shelf-container');
        if (!container) return [];
        const editMode = document.body.classList.contains('edit-mode');
        const rows = [];

        for (const child of container.children) {
            if (child.classList.contains('add-shelf-btn')) continue;
            if (child.classList.contains('shelf-split-row')) {
                for (const side of child.querySelectorAll('.shelf-split-side')) {
                    const items = editMode ? _editBarButtons(side) : _visibleCapsules(side);
                    if (items.length > 0) rows.push({ el: side, items });
                }
            } else {
                const items = editMode ? _editBarButtons(child) : _visibleCapsules(child);
                if (items.length > 0) rows.push({ el: child, items });
            }
        }

        // In edit mode, append the "+ ADD SHELF" button as a final virtual row
        if (editMode) {
            const addBtn = container.querySelector('.add-shelf-btn');
            if (addBtn && addBtn.offsetParent !== null) {
                rows.push({ el: addBtn, items: [addBtn] });
            }
        }
        return rows;
    }

    function _editBarButtons(shelfEl) {
        const bar = shelfEl.querySelector('.shelf-edit-bar');
        if (!bar) return [];
        return [...bar.querySelectorAll('span.drag-handle, button.shelf-edit-mini-btn, input[type="number"]')]
            .filter(el => !el.disabled);
    }

    // Returns the _homeRows() index of the row whose el is inside containerEl (a direct
    // child of #shelf-container). Used to re-sync _state.row after a gamepad shelf move.
    function _shelfRowIdxAfterMove(containerEl) {
        const rows = _homeRows();
        for (let i = 0; i < rows.length; i++) {
            if (containerEl === rows[i].el || containerEl.contains(rows[i].el)) return i;
        }
        return _state.row;
    }

    function _visibleCapsules(el) {
        return [...el.querySelectorAll('.shelf-capsule-wrap')].filter(c => {
            return c.style.display !== 'none' && c.offsetParent !== null;
        });
    }

    // Library: returns flat array of .game-card elements (or .list-row in list mode)
    function _libraryCards() {
        if (typeof _artOrientation !== 'undefined' && _artOrientation === 'list') {
            return [...document.querySelectorAll('#game-list .list-row')];
        }
        return [...document.querySelectorAll('.game-card')];
    }

    // In grouped mode, returns headers and visible cards interleaved in DOM order.
    // In list/ungrouped mode, delegates to _libraryCards().
    function _libraryNavItems() {
        if (typeof _artOrientation !== 'undefined' && _artOrientation === 'list') {
            return _libraryCards();
        }
        if (typeof _groupBy !== 'undefined' && _groupBy) {
            return [...document.querySelectorAll('#game-grid .group-label, #game-grid .game-card')]
                .filter(el => {
                    if (el.classList.contains('game-card')) {
                        const inner = el.closest('.group-inner-grid');
                        return !inner || inner.style.display !== 'none';
                    }
                    return true;
                });
        }
        return _libraryCards();
    }

    function _isGroupHeader(el) {
        return el?.classList.contains('group-label') ?? false;
    }

    // Returns the index of the first non-header item, or 0 if none.
    function _libraryFirstCardRow() {
        const items = _libraryNavItems();
        const idx = items.findIndex(el => !_isGroupHeader(el));
        return idx >= 0 ? idx : 0;
    }

    // Returns the column count for the group that contains `card`.
    // In grouped mode, counts only the cards inside the same .group-inner-grid so
    // groups with fewer cards than the grid width don't corrupt the count for other groups.
    function _libraryGroupColCount(card) {
        const innerGrid = card.closest?.('.group-inner-grid');
        return _libraryColCount(innerGrid
            ? [...innerGrid.querySelectorAll('.game-card')]
            : _libraryCards());
    }

    // Step up in _libraryNavItems(): from a header always moves up 1; from a card
    // moves up by cols but lands on any header it crosses instead of skipping it.
    function _libraryStepUp(items, idx) {
        if (_isGroupHeader(items[idx])) return idx - 1; // may be -1 (toolbar)
        const cols = _libraryGroupColCount(items[idx]);
        const target = idx - cols;
        for (let i = idx - 1; i > target && i >= 0; i--) {
            if (_isGroupHeader(items[i])) return i;
        }
        return target; // negative means toolbar
    }

    // Step down in _libraryNavItems(): from a header always moves down 1; from a
    // card moves down by cols but lands on any header it crosses instead of skipping.
    function _libraryStepDown(items, idx) {
        if (_isGroupHeader(items[idx])) return Math.min(idx + 1, items.length - 1);
        const cols = _libraryGroupColCount(items[idx]);
        const target = Math.min(idx + cols, items.length - 1);
        for (let i = idx + 1; i <= target; i++) {
            if (_isGroupHeader(items[i])) return i;
        }
        return target;
    }

    // Library toolbar: search input first, then buttons/selects.
    function _libraryToolbarItems() {
        const search = document.getElementById('library-search');
        const btns = [...document.querySelectorAll(
            '.search-nav-bar button, .search-nav-bar .custom-select'
        )].filter(el => el.offsetParent !== null && !el.disabled);
        return search ? [search, ...btns] : btns;
    }

    function _libraryColCount(cards) {
        // List mode is always single-column
        if (typeof _artOrientation !== 'undefined' && _artOrientation === 'list') return 1;
        // Skip group headers — they span full width and don't represent grid columns
        const gameCards = cards.filter(c => !_isGroupHeader(c));
        if (!gameCards.length) return 1;
        // Use offsetTop which is stable at page load unlike getBoundingClientRect.
        // 10px tolerance handles subpixel rounding differences between cards.
        const firstTop = gameCards[0].offsetTop;
        let cols = 0;
        for (const c of gameCards) {
            if (Math.abs(c.offsetTop - firstTop) < 10) cols++;
            else break;
        }
        return Math.max(cols, 1);
    }

    // Pick: dynamic rows depending on whether weighted panel is open.
    // Returns array of row descriptors: { type, items }
    // type: 'mode' | 'slider' | 'btn' | 'results'
    function _pickRows() {
        const rows = [];

        // Row 0: mode toggle buttons (always present)
        const modeBtns = [...document.querySelectorAll('.mode-toggle button')]
            .filter(el => el.offsetParent !== null);
        if (modeBtns.length) rows.push({ type: 'mode', items: modeBtns });

        // Rows 1..N: sliders and their bound inputs (only when weighted panel is open and not collapsed)
        const panel = document.getElementById('weighted-panel');
        if (panel && panel.classList.contains('open') && !panel.classList.contains('collapsed')) {
            const panelBody = panel.querySelector('.weighted-panel-body');
            [...(panelBody?.children ?? [])].forEach(child => {
                if (child.classList.contains('slider-bound-group')) {
                    const slider = child.querySelector('input[type="range"]');
                    if (slider) rows.push({ type: 'slider', items: [slider] });
                    const boundRow = child.querySelector('.bound-row');
                    const boundInp = boundRow?.querySelector('.bound-input');
                    if (boundInp && boundRow.offsetParent !== null) {
                        rows.push({ type: 'bound', items: [boundInp] });
                    }
                } else if (child.classList.contains('slider-row')) {
                    const slider = child.querySelector('input[type="range"]');
                    if (slider) rows.push({ type: 'slider', items: [slider] });
                }
            });
        }

        // Pick button row (always present)
        const pickBtn = document.querySelector('.pick-btn');

        // Pool toggle row: toggle switch + filter link (always present)
        const poolLabel   = document.querySelector('.toggle-switch');
        const filterLink  = document.getElementById('pick-filter-link');
        const toggleItems = [poolLabel, filterLink].filter(Boolean);
        if (toggleItems.length) rows.push({ type: 'toggle', items: toggleItems });

        // Status filter buttons row
        const statusBtns = [...document.querySelectorAll('.status-btn')];
        if (statusBtns.length) rows.push({ type: 'status', items: statusBtns });

        if (pickBtn) rows.push({ type: 'btn', items: [pickBtn] });

        // Results row (only when visible)
        const resultCards = [...document.querySelectorAll('.result-card')];
        if (resultCards.length && document.querySelector('.result-area.visible')) {
            rows.push({ type: 'results', items: resultCards });
        }

        return rows;
    }

    // Context menu items (excludes labels, disabled, hidden)
    function _ctxItems() {
        return [...document.querySelectorAll('#ctx-menu .ctx-item')].filter(el => {
            return !el.classList.contains('disabled') &&
                   el.offsetParent !== null &&
                   !el.closest('.ctx-sub'); // exclude submenu items from main list
        });
    }

    function _ctxSubItems() {
        return [...document.querySelectorAll('#ctx-completion-sub .ctx-item')].filter(el => {
            return !el.classList.contains('disabled');
        });
    }

    // Returns navigable items in the currently-open dropdown (hamburger menu or custom select panel).
    function _dropdownItems() {
        const hm = document.getElementById('hamburger-menu');
        if (hm?.classList.contains('open')) {
            return [...hm.querySelectorAll('.hamburger-item')].filter(el => el.offsetParent !== null);
        }
        const cs = document.querySelector('.custom-select.open .custom-select-panel');
        if (cs) {
            return [...cs.querySelectorAll('.custom-select-option:not(.disabled)')];
        }
        return [];
    }

    // Modal items: IDs of all modal overlays, checked in priority order.
    // Sub-modals must appear BEFORE their parent so _modalCandidates() hits the innermost first.
    const _MODAL_IDS = [
        '_color-picker-popover', // playdate.js inline color picker — dynamically inserted
        'pd-dialog-overlay',   // base.html confirm/alert — shown via .visible class
        'config-modal',        // first-run required setup (modal_edit.html, needs_config) — no close button, blocks everything else
        'editModal', 'filterModal', 'viewModal',
        // Data modal sub-modals
        'backup-modal', 'bg-modal', 'import-modal',
        // Library bulk modals
        'bulk-edit-modal', 'bulk-rescrape-modal', 'bulk-delete-modal',
        // Tools page expanding modals
        'pagywosg-modal', 'blacklist-modal', 'theme-modal',
        // Sub-modals of hamburger items (before their parents)
        'hltb-modal',          // from library-modal
        'theme-picker-modal',  // from appearance-modal
        'santa-modal',         // from community-modal
        'playnite-modal',      // from data-modal
        'filter-io-modal',     // from data-modal
        'gamepad-remap-modal', // from system-modal
        'gamepad-diag-modal',  // from system-modal
        // Top-level hamburger modals
        'account-modal',
        'appearance-modal',
        'library-modal',
        'plugins-modal',
        'community-modal',
        'data-modal',
        'system-modal',
        // Home page edit mode panels (use style.display)
        'shelf-edit-modal', 'dedup-panel', 'split-picker',
        // List mode detail pane (lowest priority — only active when in list view)
        'detail-content',
    ];

    // Visibility check that handles both inline-style modals and class-toggled ones (.visible)
    function _isModalVisible(el) {
        if (!el) return false;
        if (el.classList.contains('visible')) return true;
        return el.style.display !== 'none' && el.style.display !== '';
    }

    // Returns a flat array of navigable elements in the current modal,
    // sorted top-to-bottom then left-to-right by screen position.
    function _modalCandidates() {
        const picker = document.getElementById('_gp-select-picker');
        if (picker) {
            return [...picker.querySelectorAll('button[data-modal-row]')];
        }
        for (const id of _MODAL_IDS) {
            const el = document.getElementById(id);
            if (el && _isModalVisible(el)) {
                return [...el.querySelectorAll(
                    'button:not(:disabled), a.nav-btn, a.btn-save, a[data-modal-row], input[data-modal-row], textarea[data-modal-row], select[data-modal-row], .custom-select[data-modal-row], div[data-modal-row], li[data-modal-row], span[data-modal-row], label[data-modal-row]'
                )].filter(e => e.offsetParent !== null && !e.disabled && !e.closest('.pill'))
                  .sort((a, b) => {
                      const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
                      const ay = ar.top + ar.height / 2, by = br.top + br.height / 2;
                      if (Math.abs(ay - by) > 4) return ay - by;
                      return (ar.left + ar.width / 2) - (br.left + br.width / 2);
                  });
            }
        }
        return [];
    }

    // Returns the nearest scrollable overflow ancestor of el, or null.
    function _scrollableAncestor(el) {
        let p = el.parentElement;
        while (p && p !== document.body) {
            const { overflowY, overflowX } = getComputedStyle(p);
            if (/(auto|scroll)/.test(overflowY + overflowX) &&
                (p.scrollHeight > p.clientHeight || p.scrollWidth > p.clientWidth)) {
                return p;
            }
            p = p.parentElement;
        }
        return null;
    }

    // Returns the nearest candidate strictly in dir from cur, or null.
    //
    // Primary: approaching edge of target (right edge for LEFT, left edge for RIGHT,
    //          bottom edge for UP, top edge for DOWN) — prevents skipping close elements.
    // Secondary: gap on the perpendicular axis (0 when ranges overlap, else the gap size)
    //            — prefers elements that are directly inline over diagonal ones.
    //
    // Passes (tried in order, first non-empty result wins):
    //   If cur is inside a scrollable container: first two passes are container-scoped,
    //   so focus stays within the scroll area before escaping to elements outside it.
    //   Within each container scope: pass A requires perpendicular overlap, pass B does not.
    function _nearestInDir(dir, cur, candidates) {
        const cr = cur.getBoundingClientRect();
        const cx = cr.left + cr.width / 2, cy = cr.top + cr.height / 2;

        const sc = _scrollableAncestor(cur);
        // [containerFilter, requireOverlap]
        const passes = sc
            ? [[el => sc.contains(el), true],
               [el => sc.contains(el), false],
               [() => true, true],
               [() => true, false]]
            : [[() => true, true],
               [() => true, false]];

        for (const [inContainer, requireOverlap] of passes) {
            let best = null, bestScore = Infinity;
            for (const el of candidates) {
                if (el === cur || !inContainer(el)) continue;
                const er = el.getBoundingClientRect();
                const ex = er.left + er.width / 2, ey = er.top + er.height / 2;
                let primary, secondary;

                if (dir === 'up') {
                    if (er.bottom > cy - 4) continue;
                    const xGap = Math.max(0, Math.max(cr.left, er.left) - Math.min(cr.right, er.right));
                    if (requireOverlap && xGap > 0) continue;
                    primary = cy - er.bottom; secondary = xGap;
                } else if (dir === 'down') {
                    if (er.top < cy + 4) continue;
                    const xGap = Math.max(0, Math.max(cr.left, er.left) - Math.min(cr.right, er.right));
                    if (requireOverlap && xGap > 0) continue;
                    primary = er.top - cy; secondary = xGap;
                } else if (dir === 'left') {
                    if (er.right > cx - 4) continue;
                    const yGap = Math.max(0, Math.max(cr.top, er.top) - Math.min(cr.bottom, er.bottom));
                    if (requireOverlap && yGap > 0) continue;
                    primary = cx - er.right; secondary = yGap;
                } else if (dir === 'right') {
                    if (er.left < cx + 4) continue;
                    const yGap = Math.max(0, Math.max(cr.top, er.top) - Math.min(cr.bottom, er.bottom));
                    if (requireOverlap && yGap > 0) continue;
                    primary = er.left - cx; secondary = yGap;
                } else continue;

                const score = primary + secondary * 2;
                if (score < bestScore) { bestScore = score; best = el; }
            }
            if (best) return best;
        }
        return null;
    }

    // ── Get the currently focused element ────────────────────────────────────
    function _focusedEl() {
        return document.querySelector('.gamepad-focus');
    }

    // ── Apply focus to the element at current state coords ───────────────────
    function _syncFocus() {
        if (!_state.active) return;

        switch (_state.zone) {

            case 'ctx-menu': {
                if (_state.subItem >= 0) {
                    const subs = _ctxSubItems();
                    _applyFocus(subs[Math.min(_state.subItem, subs.length - 1)]);
                } else {
                    const items = _ctxItems();
                    _applyFocus(items[Math.min(_state.col, items.length - 1)]);
                }
                break;
            }

            case 'nav': {
                const items = _navItems();
                _applyFocus(items[Math.min(_state.col, items.length - 1)]);
                break;
            }

            case 'content': {
                switch (PAGE) {

                    case 'home': {
                        const rows = _homeRows();
                        if (!rows.length) break;
                        _state.row = Math.min(_state.row, rows.length - 1);
                        const row  = rows[_state.row];
                        _state.col = Math.min(_state.col, row.items.length - 1);
                        _applyFocus(row.items[_state.col]);
                        break;
                    }

                    case 'library': {
                        if (_state.row === -1) {
                            // Toolbar row
                            const items = _libraryToolbarItems();
                            if (!items.length) break;
                            _state.col = Math.min(Math.max(_state.col, 0), items.length - 1);
                            _applyFocus(items[_state.col]);
                        } else {
                            const items = _libraryNavItems();
                            if (!items.length) break;
                            const idx = Math.min(_state.row, items.length - 1);
                            _state.row = idx;
                            const item = items[idx];
                            _state.focusedAppid = parseInt(item.dataset.appid) || null;
                            _applyFocus(item);
                            const scrollOpts = (typeof _artOrientation !== 'undefined' && _artOrientation === 'list')
                                ? { behavior: 'smooth', block: 'nearest' }
                                : { behavior: 'smooth', block: 'center' };
                            item.scrollIntoView(scrollOpts);
                        }
                        break;
                    }

                    case 'pick': {
                        const rows = _pickRows();
                        if (!rows.length) break;
                        _state.row = Math.min(_state.row, rows.length - 1);
                        const row  = rows[_state.row];
                        _state.col = Math.min(_state.col, row.items.length - 1);
                        _applyFocus(row.items[_state.col]);
                        break;
                    }

                }
                break;
            }

            case 'modal': {
                const candidates = _modalCandidates();
                if (_state.modalFocused && _state.modalFocused.offsetParent !== null && candidates.includes(_state.modalFocused)) {
                    _applyFocus(_state.modalFocused);
                } else {
                    _state.modalFocused = candidates[0] ?? null;
                    if (_state.modalFocused) _applyFocus(_state.modalFocused);
                    else _clearFocus();
                }
                break;
            }

            case 'dropdown': {
                const items = _dropdownItems();
                if (items.length) {
                    _state.col = Math.min(Math.max(_state.col, 0), items.length - 1);
                    _applyFocus(items[_state.col]);
                }
                break;
            }

            case 'text-input':
            case 'number-input': {
                // Native focus is on the input; just keep the gamepad-focus ring on it.
                if (_state.activeInput) _applyFocus(_state.activeInput);
                break;
            }

            default:
                _state.zone = 'nav'; _state.col = 0;
                _syncFocus();
                break;
        }
    }

    // ── Cursor hiding ─────────────────────────────────────────────────────────
    let _cursorHideStyle = null;
    function _hideCursor() {
        if (_cursorHideStyle) return;
        _cursorHideStyle = document.createElement('style');
        _cursorHideStyle.textContent = [
            '* { cursor: none !important; }',
            '.list-row:hover { background: var(--bg-surface) !important; }',
            '.list-group-header:hover { background: var(--bg-raised) !important; }',
        ].join('\n');
        document.head.appendChild(_cursorHideStyle);
    }
    function _showCursor() {
        if (!_cursorHideStyle) return;
        _cursorHideStyle.remove();
        _cursorHideStyle = null;
    }

    // Hamburger menu / custom-select dropdowns aren't in the modal registry
    // (_anyWatchedOpen()) at all — they're tracked as their own 'dropdown'
    // zone via ad-hoc DOM checks instead. Shared here so both _activate() and
    // the post-A-press check below stay in sync.
    function _dropdownIsOpen() {
        const hm = document.getElementById('hamburger-menu');
        if (hm?.classList.contains('open')) return true;
        return !!document.querySelector('.custom-select.open');
    }

    // ── Activation ────────────────────────────────────────────────────────────
    function _activate() {
        if (_state.active) return;
        _state.active = true;
        _hideCursor();
        if (window._clearGameCardHover) window._clearGameCardHover();
        if (window._cancelTooltipReshow) window._cancelTooltipReshow();
        // If a modal is open, enter modal zone at row 0 regardless of previous state
        if (_anyWatchedOpen()) {
            _state.zone         = 'modal';
            _state.modalFocused = null;
            _syncFocus();
            return;
        }
        // Same idea for a dropdown/hamburger menu opened via mouse before the
        // gamepad was ever activated this session — without this, the first
        // direction press (which only silently activates, per _onButton())
        // would leave zone defaulting to 'content' below, so a second press
        // navigates the page behind the still-open menu instead of moving
        // within it.
        if (_dropdownIsOpen()) {
            if (!_isTextEntryFocused() && document.activeElement && document.activeElement !== document.body) {
                document.activeElement.blur();
            }
            _pushZone('dropdown');
            _state.col = 0;
            _syncFocus();
            return;
        }
        _state.zone = 'content';
        if (PAGE === 'library' && _lastMouseCard) {
            const items = _libraryNavItems();
            const idx = items.indexOf(_lastMouseCard);
            _state.row = idx >= 0 ? idx : _libraryFirstCardRow();
        } else {
            _state.row = (PAGE === 'library') ? _libraryFirstCardRow() : 0;
        }
        _state.col      = 0;
        _state.savedCol = 0;
        _syncFocus();
    }

    function _deactivate() {
        _state.active = false;
        _clearFocus();
        _state.focusedAppid = null;
        _showCursor();
    }

    // Deactivate on mouse click so mouse users don't see a lingering focus ring
    document.addEventListener('mousedown', () => {
        if (_state.active) _deactivate();
    });

    // Show cursor and deactivate on meaningful mouse movement (threshold avoids
    // spurious events from controller vibration or system jitter)
    let _lastMousePos = null;
    document.addEventListener('mousemove', e => {
        if (!_state.active) {
            _lastMousePos = { x: e.clientX, y: e.clientY };
            return;
        }
        if (_lastMousePos) {
            const dx = e.clientX - _lastMousePos.x;
            const dy = e.clientY - _lastMousePos.y;
            if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
        }
        _lastMousePos = { x: e.clientX, y: e.clientY };
        _deactivate();
    }, { passive: true });

    // Track last hovered card so gamepad activation can resume from it
    let _lastMouseCard = null;
    document.addEventListener('mouseover', e => {
        const card = e.target.closest('.game-card[data-appid], #game-list .list-row[data-appid]');
        if (card) _lastMouseCard = card;
    }, { passive: true });

    // ── Zone helpers ──────────────────────────────────────────────────────────
    function _pushZone(zone) {
        _state.prevZone         = _state.zone;
        _state.prevRow          = _state.row;
        _state.prevCol          = _state.col;
        _state.prevModalFocused = _state.modalFocused;
        _state.zone          = zone;
        _state.col           = 0;
        _state.subItem       = -1;
        if (zone !== 'dropdown') {
            _state.modalFocused = null;
        }
    }

    function _popZone() {
        const returningToModal = _state.prevZone === 'modal';
        _state.zone    = _state.prevZone;
        _state.row     = _state.prevRow  ?? _state.row;
        _state.col     = _state.prevCol  ?? _state.col;
        if (returningToModal) {
            _state.modalFocused = _state.prevModalFocused ?? _state.modalFocused;
        }
        _state.prevZone         = 'content';
        _state.prevRow          = null;
        _state.prevCol          = null;
        _state.prevModalFocused = null;
        _state.subItem          = -1;
    }

    // ── Direction handlers ────────────────────────────────────────────────────

    function _handleUp() {
        switch (_state.zone) {

            case 'number-input': {
                const inp = _state.activeInput;
                if (!inp) break;
                const step = parseFloat(inp.step) || 1;
                const max  = inp.max !== '' ? parseFloat(inp.max) : Infinity;
                inp.value  = Math.min(max, parseFloat(inp.value || 0) + step);
                inp.dispatchEvent(new Event('input'));
                inp.dispatchEvent(new Event('change'));
                break;
            }

            case 'modal': {
                if (_state.reorderEl) {
                    const prev = _state.reorderEl.previousElementSibling;
                    if (prev) {
                        _state.reorderEl.parentElement.insertBefore(_state.reorderEl, prev);
                        Array.from(_state.reorderEl.parentElement.children).forEach((el, i) => { el.dataset.modalRow = i + 1; });
                        if (typeof _updatePlatRanks === 'function') _updatePlatRanks();
                        _syncFocus();
                    }
                    break;
                }
                const cur = _state.modalFocused;
                if (!cur) break;
                const next = _nearestInDir('up', cur, _modalCandidates());
                if (next) { _state.modalFocused = next; _syncFocus(); }
                break;
            }

            case 'ctx-menu': {
                if (_state.subItem >= 0) {
                    const subs = _ctxSubItems();
                    _state.subItem = (_state.subItem - 1 + subs.length) % subs.length;
                } else {
                    const items = _ctxItems();
                    _state.col = (_state.col - 1 + items.length) % items.length;
                }
                _syncFocus();
                break;
            }

            case 'nav': break; // no-op, already at top

            case 'dropdown': {
                const items = _dropdownItems();
                if (items.length && _state.col > 0) {
                    _state.col--;
                    _syncFocus();
                }
                break;
            }

            case 'content': {
                switch (PAGE) {

                    case 'home': {
                        // Shelf reorder: move held shelf row up one position
                        if (_shelfGpDragEl) {
                            const sc = document.getElementById('shelf-container');
                            const children = Array.from(sc.children).filter(c => !c.classList.contains('add-shelf-btn'));
                            const idx = children.indexOf(_shelfGpDragEl);
                            if (idx > 0) {
                                sc.insertBefore(_shelfGpDragEl, children[idx - 1]);
                                _state.row = _shelfRowIdxAfterMove(_shelfGpDragEl);
                                _syncFocus();
                            }
                            break;
                        }
                        const rows = _homeRows();
                        const editMode = document.body.classList.contains('edit-mode');
                        let prev = _state.row - 1;
                        if (editMode) {
                            // Skip all sibling sides of the same split row
                            const curSplit = rows[_state.row]?.el?.closest?.('.shelf-split-row');
                            if (curSplit) {
                                while (prev >= 0 && rows[prev]?.el?.closest?.('.shelf-split-row') === curSplit) prev--;
                            }
                            // Skip empty rows (don't go below 0)
                            while (prev > 0 && rows[prev]?.items.length === 0) prev--;
                            // If landing in a split row, pick the column closest in X to current item
                            if (prev >= 0) {
                                const prevSplit = rows[prev]?.el?.closest?.('.shelf-split-row');
                                if (prevSplit) {
                                    // Collect all sides of this split row
                                    const srcCx = (() => {
                                        const r = rows[_state.row]?.items[_state.col]?.getBoundingClientRect();
                                        return r ? r.left + r.width / 2 : 0;
                                    })();
                                    let bestRow = prev, bestDist = Infinity;
                                    for (let ri = 0; ri < rows.length; ri++) {
                                        if (rows[ri].el?.closest?.('.shelf-split-row') !== prevSplit) continue;
                                        const item = rows[ri].items[0];
                                        if (!item) continue;
                                        const r = item.getBoundingClientRect();
                                        const cx = r.left + r.width / 2;
                                        const dist = Math.abs(cx - srcCx);
                                        if (dist < bestDist) { bestDist = dist; bestRow = ri; }
                                    }
                                    prev = bestRow;
                                }
                            }
                        } else {
                            // In normal mode, skip the sibling side of the same split row.
                            if (prev >= 0) {
                                const curEl    = rows[_state.row]?.el;
                                const prevEl   = rows[prev]?.el;
                                const curSplit  = curEl?.closest?.('.shelf-split-row');
                                const prevSplit = prevEl?.closest?.('.shelf-split-row');
                                if (curSplit && prevSplit && curSplit === prevSplit) prev--;
                            }
                        }
                        // Skip empty rows (don't go below 0)
                        if (!editMode) while (prev > 0 && rows[prev]?.items.length === 0) prev--;
                        if (prev >= 0 && rows[prev]?.items.length > 0) {
                            if (editMode) {
                                _state.row = prev;
                                _state.col = 0;
                            } else {
                                const srcItem  = rows[_state.row]?.items[_state.col];
                                const srcCol   = _state.col;
                                const srcTotal = rows[_state.row]?.items.length ?? 1;
                                const target   = _findNavTarget(rows, prev, srcItem, srcCol, srcTotal);
                                _state.row = target.rowIdx;
                                _state.col = target.colIdx;
                            }
                        } else {
                            // At top row → go to nav (edit toolbar in edit mode)
                            _state.zone = 'nav';
                            const navItems = _navItems();
                            const activeLink = document.querySelector('.nav-links a.active');
                            _state.col = editMode ? 0 : (activeLink ? navItems.indexOf(activeLink) : 0);
                        }
                        _syncFocus();
                        break;
                    }

                    case 'library': {
                        if (_state.row === -1) {
                            // Toolbar → nav
                            _state.zone = 'nav';
                            const navItems = _navItems();
                            const activeLink = document.querySelector('.nav-links a.active');
                            _state.col = activeLink ? navItems.indexOf(activeLink) : 0;
                        } else {
                            const items = _libraryNavItems();
                            const newIdx = _libraryStepUp(items, _state.row);
                            if (newIdx < 0) {
                                _state.row = -1;
                                _state.col = 0;
                            } else {
                                _state.row = newIdx;
                            }
                        }
                        _syncFocus();
                        break;
                    }

                    case 'pick': {
                        const rows = _pickRows();
                        if (_state.row === 0) {
                            _state.zone = 'nav';
                            const navItems = _navItems();
                            const activeLink = document.querySelector('.nav-links a.active');
                            _state.col = activeLink ? navItems.indexOf(activeLink) : 0;
                        } else {
                            _state.row--;
                            const row = rows[_state.row];
                            _state.col = Math.min(_state.savedCol, row.items.length - 1);
                        }
                        _syncFocus();
                        break;
                    }

                }
                break;
            }
        }
    }

    function _handleDown() {
        switch (_state.zone) {

            case 'number-input': {
                const inp = _state.activeInput;
                if (!inp) break;
                const step = parseFloat(inp.step) || 1;
                const min  = inp.min !== '' ? parseFloat(inp.min) : -Infinity;
                inp.value  = Math.max(min, parseFloat(inp.value || 0) - step);
                inp.dispatchEvent(new Event('input'));
                inp.dispatchEvent(new Event('change'));
                break;
            }

            case 'modal': {
                if (_state.reorderEl) {
                    const next = _state.reorderEl.nextElementSibling;
                    if (next) {
                        _state.reorderEl.parentElement.insertBefore(next, _state.reorderEl);
                        Array.from(_state.reorderEl.parentElement.children).forEach((el, i) => { el.dataset.modalRow = i + 1; });
                        if (typeof _updatePlatRanks === 'function') _updatePlatRanks();
                        _syncFocus();
                    }
                    break;
                }
                const cur = _state.modalFocused;
                if (!cur) break;
                const next = _nearestInDir('down', cur, _modalCandidates());
                if (next) { _state.modalFocused = next; _syncFocus(); }
                break;
            }

            case 'ctx-menu': {
                if (_state.subItem >= 0) {
                    const subs = _ctxSubItems();
                    _state.subItem = (_state.subItem + 1) % subs.length;
                } else {
                    const items = _ctxItems();
                    _state.col = (_state.col + 1) % items.length;
                }
                _syncFocus();
                break;
            }

            case 'nav': {
                // Drop into content — for library, land on toolbar first
                _state.zone     = 'content';
                _state.row      = (PAGE === 'library') ? -1 : 0;
                _state.col      = 0;
                _state.savedCol = 0;
                _syncFocus();
                break;
            }

            case 'dropdown': {
                const items = _dropdownItems();
                if (items.length && _state.col < items.length - 1) {
                    _state.col++;
                    _syncFocus();
                }
                break;
            }

            case 'content': {
                switch (PAGE) {

                    case 'home': {
                        // Shelf reorder: move held shelf row down one position
                        if (_shelfGpDragEl) {
                            const sc = document.getElementById('shelf-container');
                            const children = Array.from(sc.children).filter(c => !c.classList.contains('add-shelf-btn'));
                            const idx = children.indexOf(_shelfGpDragEl);
                            if (idx < children.length - 1) {
                                sc.insertBefore(children[idx + 1], _shelfGpDragEl);
                                _state.row = _shelfRowIdxAfterMove(_shelfGpDragEl);
                                _syncFocus();
                            }
                            break;
                        }
                        const rows = _homeRows();
                        const editMode = document.body.classList.contains('edit-mode');
                        let next = _state.row + 1;
                        if (editMode) {
                            // Skip all sibling sides of the same split row
                            const curSplit = rows[_state.row]?.el?.closest?.('.shelf-split-row');
                            if (curSplit) {
                                while (next < rows.length && rows[next]?.el?.closest?.('.shelf-split-row') === curSplit) next++;
                            }
                        } else {
                            // In normal mode, skip just one sibling side of the same split row.
                            if (next < rows.length) {
                                const curEl  = rows[_state.row]?.el;
                                const nxtEl  = rows[next]?.el;
                                const curSplit = curEl?.closest?.('.shelf-split-row');
                                const nxtSplit = nxtEl?.closest?.('.shelf-split-row');
                                if (curSplit && nxtSplit && curSplit === nxtSplit) next++;
                            }
                        }
                        // Skip empty rows
                        while (next < rows.length && rows[next]?.items.length === 0) next++;
                        if (next < rows.length) {
                            if (editMode) {
                                // If landing in a split row, pick the closest column by X
                                const nxtSplit = rows[next]?.el?.closest?.('.shelf-split-row');
                                if (nxtSplit) {
                                    const srcCx = (() => {
                                        const r = rows[_state.row]?.items[_state.col]?.getBoundingClientRect();
                                        return r ? r.left + r.width / 2 : 0;
                                    })();
                                    let bestRow = next, bestDist = Infinity;
                                    for (let ri = 0; ri < rows.length; ri++) {
                                        if (rows[ri].el?.closest?.('.shelf-split-row') !== nxtSplit) continue;
                                        const item = rows[ri].items[0];
                                        if (!item) continue;
                                        const r = item.getBoundingClientRect();
                                        const cx = r.left + r.width / 2;
                                        const dist = Math.abs(cx - srcCx);
                                        if (dist < bestDist) { bestDist = dist; bestRow = ri; }
                                    }
                                    _state.row = bestRow;
                                } else {
                                    _state.row = next;
                                }
                                _state.col = 0;
                            } else {
                                const srcItem  = rows[_state.row]?.items[_state.col];
                                const srcCol   = _state.col;
                                const srcTotal = rows[_state.row]?.items.length ?? 1;
                                const target   = _findNavTarget(rows, next, srcItem, srcCol, srcTotal);
                                _state.row = target.rowIdx;
                                _state.col = target.colIdx;
                            }
                        }
                        _syncFocus();
                        break;
                    }

                    case 'library': {
                        if (_state.row === -1) {
                            // Toolbar → first grid row
                            _state.row = _libraryFirstCardRow();
                            _state.col = 0;
                        } else {
                            const items = _libraryNavItems();
                            _state.row = _libraryStepDown(items, _state.row);
                        }
                        _syncFocus();
                        break;
                    }

                    case 'pick': {
                        const rows = _pickRows();
                        if (_state.row < rows.length - 1) {
                            _state.row++;
                            const row = rows[_state.row];
                            _state.col = Math.min(_state.savedCol, row.items.length - 1);
                        }
                        _syncFocus();
                        break;
                    }

                }
                break;
            }
        }
    }

    function _handleLeft() {
        switch (_state.zone) {

            case 'modal': {
                const cur = _state.modalFocused;
                if (!cur) break;
                if (cur.tagName === 'INPUT' && cur.type === 'range') {
                    const step = parseFloat(cur.step || 1);
                    const min  = parseFloat(cur.min  ?? 0);
                    cur.value = Math.max(min, parseFloat(cur.value) - step);
                    cur.dispatchEvent(new Event('input'));
                    break;
                }
                const next = _nearestInDir('left', cur, _modalCandidates());
                if (next) { _state.modalFocused = next; _syncFocus(); }
                break;
            }

            case 'ctx-menu': {
                if (_state.subItem >= 0) {
                    // Exit submenu back to parent, remove force-open class
                    document.querySelectorAll('.ctx-sub-open').forEach(el => el.classList.remove('ctx-sub-open'));
                    _state.subItem = -1;
                    _syncFocus();
                }
                break;
            }

            case 'nav': {
                if (_state.col > 0) _state.col--;
                _syncFocus();
                break;
            }

            case 'content': {
                switch (PAGE) {

                    case 'home': {
                        if (_state.col > 0) {
                            _state.col--;
                        } else {
                            // Wrap to end of previous row
                            const rows = _homeRows();
                            let prev = _state.row - 1;
                            while (prev > 0 && rows[prev]?.items.length === 0) prev--;
                            if (prev >= 0 && rows[prev]?.items.length > 0) {
                                _state.row = prev;
                                _state.col = rows[prev].items.length - 1;
                            }
                        }
                        _state.savedCol = _state.col;
                        _syncFocus();
                        break;
                    }

                    case 'library': {
                        if (_state.row === -1) {
                            // Toolbar: move left between toolbar items
                            if (_state.col > 0) _state.col--;
                        } else {
                            const items = _libraryNavItems();
                            // Group headers are full-width; left/right do nothing on them
                            if (!_isGroupHeader(items[_state.row]) && _state.row > 0) {
                                _state.row--;
                            }
                        }
                        _syncFocus();
                        break;
                    }

                    case 'pick': {
                        const rows = _pickRows();
                        const row  = rows[_state.row];
                        if (row?.type === 'slider') {
                            const slider = row.items[0];
                            // Step by 10 to clear the 5-point snap zone around 0
                            slider.value = Math.max(parseInt(slider.min || -100), parseInt(slider.value) - 10);
                            slider.dispatchEvent(new Event('input'));
                        } else if (row?.type === 'bound') {
                            const inp = row.items[0];
                            if (inp) {
                                inp.value = Math.max(parseInt(inp.min ?? 0), parseInt(inp.value || 0) - 1);
                                inp.dispatchEvent(new Event('input'));
                                inp.dispatchEvent(new Event('change'));
                            }
                        } else {
                            if (_state.col > 0) _state.col--;
                            _state.savedCol = _state.col;
                        }
                        _syncFocus();
                        break;
                    }

                }
                break;
            }
        }
    }

    function _handleRight() {
        switch (_state.zone) {

            case 'modal': {
                const cur = _state.modalFocused;
                if (!cur) break;
                if (cur.tagName === 'INPUT' && cur.type === 'range') {
                    const step = parseFloat(cur.step || 1);
                    const max  = parseFloat(cur.max  ?? 100);
                    cur.value = Math.min(max, parseFloat(cur.value) + step);
                    cur.dispatchEvent(new Event('input'));
                    break;
                }
                const next = _nearestInDir('right', cur, _modalCandidates());
                if (next) { _state.modalFocused = next; _syncFocus(); }
                break;
            }

            case 'ctx-menu': {
                // Enter submenu if the focused item has one
                const items = _ctxItems();
                const focused = items[_state.col];
                if (focused && focused.classList.contains('has-sub')) {
                    focused.classList.add('ctx-sub-open');
                    _state.subItem = 0;
                    _syncFocus();
                }
                break;
            }

            case 'nav': {
                const items = _navItems();
                if (_state.col < items.length - 1) _state.col++;
                _syncFocus();
                break;
            }

            case 'content': {
                switch (PAGE) {

                    case 'home': {
                        const rows = _homeRows();
                        const row  = rows[_state.row];
                        if (!row) break;
                        if (_state.col < row.items.length - 1) {
                            _state.col++;
                        } else {
                            // Wrap to start of next row
                            let next = _state.row + 1;
                            while (next < rows.length && rows[next]?.items.length === 0) next++;
                            if (next < rows.length) {
                                _state.row = next;
                                _state.col = 0;
                            }
                        }
                        _state.savedCol = _state.col;
                        _syncFocus();
                        break;
                    }

                    case 'library': {
                        if (_state.row === -1) {
                            // Toolbar: move right between toolbar items
                            const tbItems = _libraryToolbarItems();
                            if (_state.col < tbItems.length - 1) _state.col++;
                        } else if (typeof _artOrientation !== 'undefined' && _artOrientation === 'list') {
                            // List mode: right enters the detail pane
                            const cards = _libraryCards();
                            const card  = cards[_state.row];
                            if (card) {
                                card.click();
                                _pushZone('modal');
                            }
                        } else {
                            const items = _libraryNavItems();
                            // Group headers are full-width; left/right do nothing on them
                            if (!_isGroupHeader(items[_state.row]) && _state.row < items.length - 1) {
                                _state.row++;
                            }
                        }
                        _syncFocus();
                        break;
                    }

                    case 'pick': {
                        const rows = _pickRows();
                        const row  = rows[_state.row];
                        if (row?.type === 'slider') {
                            const slider = row.items[0];
                            // Step by 10 to clear the 5-point snap zone around 0
                            slider.value = Math.min(parseInt(slider.max || 100), parseInt(slider.value) + 10);
                            slider.dispatchEvent(new Event('input'));
                        } else if (row?.type === 'bound') {
                            const inp = row.items[0];
                            if (inp) {
                                inp.value = Math.min(parseInt(inp.max ?? 9999), parseInt(inp.value || 0) + 1);
                                inp.dispatchEvent(new Event('input'));
                                inp.dispatchEvent(new Event('change'));
                            }
                        } else {
                            if (_state.col < row.items.length - 1) _state.col++;
                            _state.savedCol = _state.col;
                        }
                        _syncFocus();
                        break;
                    }

                }
                break;
            }
        }
    }

    // ── Custom SELECT picker (WebKit can't open native <select> programmatically)
    let _selectPickerSource = null;

    function _openSelectPicker(selectEl) {
        if (!selectEl || selectEl.tagName !== 'SELECT') return;

        const overlay = document.createElement('div');
        overlay.id = '_gp-select-picker';
        overlay.className = 'modal-overlay';
        overlay.style.zIndex = '9999';
        overlay.addEventListener('mousedown', e => { if (e.target === overlay) _closeSelectPicker(); });

        const box = document.createElement('div');
        box.style.cssText = [
            'background:var(--bg-surface)',
            'border:1px solid var(--accent)',
            'border-radius:8px',
            'padding:8px',
            'min-width:200px',
            'max-width:360px',
            'max-height:60vh',
            'overflow-y:auto',
            'box-shadow:0 0 20px rgba(102,192,244,0.2)',
        ].join(';');

        const title = document.createElement('div');
        title.style.cssText = 'color:var(--text-secondary);font-size:0.75rem;padding:4px 8px 8px;border-bottom:1px solid var(--border);margin-bottom:6px;';
        title.textContent = selectEl.dataset.pickerTitle || 'Select an option';
        box.appendChild(title);

        Array.from(selectEl.options).forEach((opt, i) => {
            const btn = document.createElement('button');
            btn.className = 'nav-btn';
            btn.dataset.modalRow = i;
            btn.style.cssText = 'width:100%;text-align:left;margin-bottom:4px;justify-content:flex-start;height:auto;padding:8px 12px;';
            btn.textContent = opt.text;
            if (i === selectEl.selectedIndex) {
                btn.style.background = 'var(--accent)';
                btn.style.color = 'var(--on-accent)';
            }
            btn.addEventListener('click', () => {
                selectEl.selectedIndex = i;
                selectEl.dispatchEvent(new Event('change', { bubbles: true }));
                _closeSelectPicker();
            });
            box.appendChild(btn);
        });

        overlay.appendChild(box);
        document.body.appendChild(overlay);
        _selectPickerSource = selectEl;

        _pushZone('modal');
        const pickerBtns = [...overlay.querySelectorAll('button[data-modal-row]')];
        _state.modalFocused = pickerBtns[Math.max(0, selectEl.selectedIndex)] ?? pickerBtns[0] ?? null;
        _syncFocus();
    }

    function _closeSelectPicker() {
        const picker = document.getElementById('_gp-select-picker');
        if (picker) picker.remove();
        _selectPickerSource = null;
        if (_state.zone === 'modal') _popZone();
        _syncFocus();
    }

    // ── Action handlers ───────────────────────────────────────────────────────

    function _handleA() {
        switch (_state.zone) {

            case 'modal': {
                const el = _state.modalFocused;
                if (!el) break;
                if (el.tagName === 'INPUT') {
                    if (el.type === 'checkbox') {
                        el.click();
                    } else if (el.type === 'range') {
                        el.focus();
                    } else if (el.type === 'number') {
                        _state.activeInput = el;
                        _pushZone('number-input');
                        _stampGpTextFocus();
                        el.focus();
                        el.select();
                        _syncFocus();
                    } else {
                        _state.activeInput = el;
                        _pushZone('text-input');
                        _stampGpTextFocus();
                        el.focus();
                        _syncFocus();
                    }
                } else if (el.tagName === 'SELECT') {
                    _openSelectPicker(el);
                } else if (el.tagName === 'TEXTAREA') {
                    _state.activeInput = el;
                    _pushZone('text-input');
                    _stampGpTextFocus();
                    el.focus();
                    _syncFocus();
                } else if (el.classList?.contains('pill-input-box')) {
                    const inp = el.querySelector('.pill-text-input');
                    if (inp) {
                        _state.activeInput = inp;
                        _pushZone('text-input');
                        _stampGpTextFocus();
                        inp.focus();
                        _syncFocus();
                    }
                } else if (el.tagName === 'LI') {
                    const cb = el.querySelector('input[type="checkbox"]');
                    if (cb) {
                        // Dedup toggle and similar checkbox-in-li patterns
                        cb.click();
                    } else if (el.dataset.plat) {
                        // Platform priority reorder: A grabs/drops the item
                        if (_state.reorderEl === el) {
                            el.classList.remove('plat-held');
                            _state.reorderEl = null;
                        } else {
                            if (_state.reorderEl) _state.reorderEl.classList.remove('plat-held');
                            _state.reorderEl = el;
                            el.classList.add('plat-held');
                        }
                    } else {
                        // Generic clickable li (e.g. split-picker list items)
                        el.click();
                        requestAnimationFrame(() => {
                            const candidates = _modalCandidates();
                            if (!_state.modalFocused || _state.modalFocused.offsetParent === null || !candidates.includes(_state.modalFocused)) {
                                const prevRow = _state.modalFocused?.dataset?.modalRow;
                                const sameRow = prevRow != null && candidates.find(c => c.dataset.modalRow === prevRow);
                                _state.modalFocused = sameRow || candidates[0] || null;
                            }
                            _syncFocus();
                        });
                    }
                } else {
                    el.click();
                    // Re-sync in rAF so if the click opened a sub-modal focus lands on its first element.
                    // If the click caused the modal to re-render (removing the focused element), prefer a
                    // candidate with the same data-modal-row before falling back to the first element.
                    requestAnimationFrame(() => {
                        const candidates = _modalCandidates();
                        if (!_state.modalFocused || _state.modalFocused.offsetParent === null || !candidates.includes(_state.modalFocused)) {
                            const prevRow = _state.modalFocused?.dataset?.modalRow;
                            const sameRow = prevRow != null && candidates.find(c => c.dataset.modalRow === prevRow);
                            _state.modalFocused = sameRow || candidates[0] || null;
                        }
                        _syncFocus();
                    });
                }
                break;
            }

            case 'ctx-menu': {
                if (_state.subItem >= 0) {
                    _ctxSubItems()[_state.subItem]?.click();
                } else {
                    const items = _ctxItems();
                    const el = items[_state.col];
                    if (el) {
                        if (el.classList.contains('has-sub')) {
                            // Enter submenu — add class to force it visible via CSS
                            el.classList.add('ctx-sub-open');
                            _state.subItem = 0;
                            _syncFocus();
                        } else {
                            el.click();
                        }
                    }
                }
                break;
            }

            case 'nav': {
                const items = _navItems();
                items[_state.col]?.click();
                break;
            }

            case 'dropdown': {
                const items = _dropdownItems();
                const el = items[_state.col];
                if (el) {
                    if (el.classList.contains('custom-select-option')) {
                        // bubbles:false — prevents bubbling to document mousedown which would deactivate gamepad
                        el.dispatchEvent(new MouseEvent('mousedown', { bubbles: false, cancelable: true }));
                    } else {
                        el.click();
                    }
                    _popZone();
                    _syncFocus();
                }
                return; // skip post-A dropdown detection
            }

            case 'content': {
                switch (PAGE) {

                    case 'home': {
                        const rows = _homeRows();
                        const row  = rows[_state.row];
                        if (!row) break;
                        const cap = row.items[_state.col];
                        if (!cap) break;
                        if (document.body.classList.contains('edit-mode')) {
                            if (cap.classList.contains('drag-handle')) {
                                // Find direct child of #shelf-container to use as the drag unit
                                const sc = document.getElementById('shelf-container');
                                let shelfRow = cap;
                                while (shelfRow && shelfRow.parentElement !== sc) shelfRow = shelfRow.parentElement;
                                if (shelfRow && !shelfRow.classList.contains('add-shelf-btn')) {
                                    if (_shelfGpDragEl === shelfRow) {
                                        shelfRow.classList.remove('shelf-gp-held');
                                        _shelfGpDragEl = null;
                                        if (typeof syncShelvesOrderFromDOM === 'function') syncShelvesOrderFromDOM();
                                    } else {
                                        if (_shelfGpDragEl) _shelfGpDragEl.classList.remove('shelf-gp-held');
                                        _shelfGpDragEl = shelfRow;
                                        shelfRow.classList.add('shelf-gp-held');
                                    }
                                }
                            } else if (cap.tagName === 'INPUT' && cap.type === 'number') {
                                _state.activeInput = cap;
                                _pushZone('number-input');
                                _stampGpTextFocus();
                                cap.focus();
                                cap.select();
                                _syncFocus();
                            } else if (cap.tagName === 'BUTTON') {
                                cap.click();
                            }
                        } else {
                            const appid = parseInt(cap.dataset.appid);
                            if (appid) launchGame(appid);
                        }
                        break;
                    }

                    case 'library': {
                        if (_state.row === -1) {
                            const items = _libraryToolbarItems();
                            const el = items[_state.col];
                            if (el) {
                                if (el.tagName === 'INPUT') {
                                    _state.activeInput = el;
                                    _pushZone('text-input');
                                    _stampGpTextFocus();
                                    el.focus();
                                    _syncFocus();
                                } else if (el.tagName === 'SELECT') {
                                    _openSelectPicker(el);
                                } else {
                                    el.click();
                                }
                            }
                        } else {
                            const items = _libraryNavItems();
                            const item  = items[_state.row];
                            if (!item) break;
                            if (_isGroupHeader(item)) {
                                item.click(); // toggles group collapse
                                requestAnimationFrame(() => {
                                    const newItems = _libraryNavItems();
                                    if (_state.row >= newItems.length) {
                                        _state.row = Math.max(0, newItems.length - 1);
                                    }
                                    _syncFocus();
                                });
                                break;
                            }
                            // In list mode: A opens the detail pane
                            if (typeof _artOrientation !== 'undefined' && _artOrientation === 'list') {
                                item.click();
                                _pushZone('modal');
                                _syncFocus();
                                break;
                            }
                            if (document.body.classList.contains('select-mode')) {
                                item.click(); // toggles selection via onCardClick
                            } else {
                                const appid = parseInt(item.dataset.appid);
                                if (appid) launchGame(appid);
                            }
                        }
                        break;
                    }

                    case 'pick': {
                        const rows = _pickRows();
                        const row  = rows[_state.row];
                        if (!row) break;
                        if (row.type === 'slider') {
                            row.items[0]?.focus();
                        } else if (row.type === 'bound') {
                            const inp = row.items[0];
                            if (inp) {
                                _state.activeInput = inp;
                                _pushZone(inp.type === 'number' ? 'number-input' : 'text-input');
                                _stampGpTextFocus();
                                inp.focus();
                                inp.select();
                                _syncFocus();
                            }
                        } else if (row.type === 'toggle') {
                            const item = row.items[_state.col];
                            if (!item) break;
                            if (item.classList.contains('toggle-switch')) {
                                const cb = item.querySelector('input[type="checkbox"]');
                                if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
                            } else {
                                item.click(); // filter link
                            }
                        } else if (row.type === 'results') {
                            const card  = row.items[_state.col];
                            if (!card) break;
                            const appid = parseInt(card.dataset.appid);
                            if (appid) launchGame(appid);
                        } else {
                            row.items[_state.col]?.click();
                        }
                        break;
                    }

                }
                break;
            }
        }

        // After any A press, enter dropdown zone if a dropdown just opened
        requestAnimationFrame(() => {
            if (_state.zone === 'dropdown' || !_state.active) return;
            // Dropdown/hamburger navigation only moves a CSS focus ring
            // (_applyFocus never calls .focus() outside text/number-input
            // zones), so if the menu was ever opened with a real mouse click
            // the hamburger button itself keeps native DOM focus the whole
            // time gamepad navigation runs. A synthesized Enter from Steam
            // Input's A-button mapping would then hit that stale focus and
            // natively re-trigger the hamburger button instead of whatever
            // item the gamepad ring is actually highlighting.
            if (!_isTextEntryFocused() && document.activeElement && document.activeElement !== document.body) {
                document.activeElement.blur();
            }
            if (_dropdownIsOpen()) {
                _pushZone('dropdown');
                _state.col = 0;
                _syncFocus();
            }
        });
    }

    function _closeCtxMenu() {
        // hideMenu() is inside an IIFE and not globally accessible.
        // Dispatching Escape triggers the document keydown listener that calls it.
        document.querySelectorAll('.ctx-sub-open').forEach(el => el.classList.remove('ctx-sub-open'));
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    }

    function _closeAnyOpenModal() {
        // Close hamburger menu if open
        const hamburgerMenu = document.getElementById('hamburger-menu');
        if (hamburgerMenu?.classList.contains('open')) {
            hamburgerMenu.classList.remove('open');
            if (_state.zone === 'dropdown') _popZone();
            return true;
        }

        // Close open custom select panels
        const openSelect = document.querySelector('.custom-select.open');
        if (openSelect) {
            openSelect.classList.remove('open');
            const p = openSelect.querySelector('.custom-select-panel');
            if (p) p.style.display = 'none';
            if (_state.zone === 'dropdown') _popZone();
            return true;
        }

        // Close custom select picker first
        if (document.getElementById('_gp-select-picker')) { _closeSelectPicker(); return true; }

        // pd-dialog-overlay (confirm/alert) — cancel it
        const dlg = document.getElementById('pd-dialog-overlay');
        if (dlg && _isModalVisible(dlg)) {
            document.getElementById('pd-btn-cancel')?.click();
            return true;
        }

        // Dynamic plugin manage sub-modals (lazily created; scan by ID suffix, innermost first)
        for (const el of document.querySelectorAll('[id$="-manage-oauth-modal"]')) {
            if (_isModalVisible(el)) {
                const id = el.id.replace(/-manage-oauth-modal$/, '');
                if (typeof _closeManageOauth === 'function') _closeManageOauth(id);
                return true;
            }
        }
        for (const el of document.querySelectorAll('[id$="-manage-modal"]')) {
            if (_isModalVisible(el)) {
                const id = el.id.replace(/-manage-modal$/, '');
                if (typeof _closeManageModal === 'function') _closeManageModal(id);
                return true;
            }
        }

        // Try every known close function in priority order.
        // Sub-modals are listed before their parent so B closes innermost first.
        const checks = [
            // color picker popover (dynamically created)
            ['_color-picker-popover', 'closeColorPicker'],
            // library page bulk modals
            ['bulk-edit-modal',       'closeBulkEditModal'],
            ['bulk-rescrape-modal',   'closeBulkRescrapeModal'],
            ['bulk-delete-modal',     'closeBulkDeleteModal'],
            // sub-modals (before their parents)
            ['hltb-modal',            'closeHltbModal'],
            ['theme-picker-modal',    'closeThemePickerModal'],
            ['santa-modal',           'closeSantaModal'],
            ['playnite-modal',        'closePlayniteModal'],
            ['filter-io-modal',       'closeFilterIoModal'],
            ['backup-modal',          'closeBackupModal'],
            ['bg-modal',              'closeBgModal'],
            ['import-modal',          'closeImportModal'],
            ['pagywosg-modal',        'closePagModal'],
            ['theme-modal',           'closeThemeModal'],
            ['gamepad-remap-modal',   'closeGamepadRemap'],
            ['gamepad-diag-modal',    'closeGamepadDiag'],
            // top-level hamburger modals
            ['account-modal',         'closeAccountModal'],
            ['appearance-modal',      'closeAppearanceModal'],
            ['library-modal',         'closeLibraryModal'],
            ['plugins-modal',         'closePluginsModal'],
            ['community-modal',       'closeCommunityModal'],
            ['data-modal',            'closeDataModal'],
            ['system-modal',          'closeSystemModal'],
            ['blacklist-modal',       'closeBlacklistModal'],
            // home page edit mode panels
            ['shelf-edit-modal',      'semClose'],
            ['dedup-panel',           'closeDedupPanel'],
            ['split-picker',          'closeSplitPicker'],
        ];
        for (const [id, fn] of checks) {
            const el = document.getElementById(id);
            if (el && _isModalVisible(el)) {
                if (typeof window[fn] === 'function') window[fn]();
                else {
                    // Fallback: click the ✕ button inside the modal
                    el.querySelector('button[onclick*="close"], button.modal-close')?.click();
                }
                return true;
            }
        }
        return false;
    }

    function _isTextEntryFocused() {
        const el = document.activeElement;
        if (!el) return false;
        if (el.tagName === 'TEXTAREA') return true;
        if (el.tagName === 'INPUT') {
            const t = (el.type || 'text').toLowerCase();
            return t === 'text' || t === 'search' || t === 'number' ||
                   t === 'password' || t === 'email' || t === 'url' || t === 'tel';
        }
        return false;
    }

    function _handleB() {
        // Suppress B while the eyedropper subprocess owns the screen, and for a short
        // cooldown after it exits (the B press that dismissed the subprocess is still
        // in the gamepad state when the next RAF fires).
        if (window._cpEyedropperBusy || window._cpEyedropperCooldown) return;

        // Drop held shelf row
        if (_shelfGpDragEl) {
            _shelfGpDragEl.classList.remove('shelf-gp-held');
            if (typeof syncShelvesOrderFromDOM === 'function') syncShelvesOrderFromDOM();
            _shelfGpDragEl = null;
            return;
        }

        // Drop held platform-priority item
        if (_state.reorderEl) {
            _state.reorderEl.classList.remove('plat-held');
            _state.reorderEl = null;
            return;
        }

        // Exit text-input / number-input zone — blur the input and return to previous zone
        if (_state.zone === 'text-input' || _state.zone === 'number-input') {
            if (_state.activeInput) { _state.activeInput.blur(); _state.activeInput = null; }
            _popZone();
            _syncFocus();
            return;
        }

        // A text field can end up focused without ever entering the text-input
        // zone above — e.g. tapped directly via the Steam Deck touchscreen/
        // trackpad instead of selected with A. Gamescope's on-screen keyboard
        // also binds B to dismiss itself, and there's no web API to detect
        // whether it's open, so the same B press both closes the keyboard and
        // (without this check) falls through to close the modal underneath
        // it. Blur the field first; a second B press then closes the modal.
        if (_isTextEntryFocused()) {
            document.activeElement.blur();
            return;
        }

        // If in dropdown zone, close just the dropdown and return to previous zone
        if (_state.zone === 'dropdown') {
            _closeAnyOpenModal();
            _syncFocus();
            return;
        }

        // If in ctx-menu submenu, exit submenu first
        if (_state.zone === 'ctx-menu' && _state.subItem >= 0) {
            _state.subItem = -1;
            document.querySelectorAll('.ctx-sub-open').forEach(el => el.classList.remove('ctx-sub-open'));
            _syncFocus();
            return;
        }

        // Close context menu
        const ctxMenu = document.getElementById('ctx-menu');
        if (ctxMenu?.classList.contains('visible')) {
            if (_state.zone === 'ctx-menu') _popZone();
            _closeCtxMenu();
            return;
        }

        // Close edit/filter modals (these functions are global)
        const editModal = document.getElementById('editModal');
        if (editModal && editModal.style.display !== 'none') {
            if (_state.zone === 'modal') _popZone();
            if (typeof closeModal === 'function') closeModal();
            _syncFocus();
            return;
        }

        const filterModal = document.getElementById('filterModal');
        if (filterModal && filterModal.style.display !== 'none') {
            if (_state.zone === 'modal') _popZone();
            if (typeof closeFilterModal === 'function') closeFilterModal();
            _syncFocus();
            return;
        }

        const viewModal = document.getElementById('viewModal');
        if (viewModal && viewModal.style.display !== 'none') {
            if (_state.zone === 'modal') _popZone();
            if (typeof closeViewModal === 'function') closeViewModal();
            _syncFocus();
            return;
        }

        // Close any other open modal (bulk edit, tools modals, edit-mode panels)
        if (_closeAnyOpenModal()) return;

        // Exit home page edit mode
        if (PAGE === 'home' && document.body.classList.contains('edit-mode')) {
            if (typeof exitEditMode === 'function') exitEditMode();
            return;
        }

        if (typeof isFullscreen === 'function' && isFullscreen()) {
            if (typeof exitFullscreen === 'function') exitFullscreen();
        }
    }

    function _handleX() {
        // Open context menu on the focused game element
        let gameEl = null;

        if (_state.zone === 'content') {
            switch (PAGE) {
                case 'home': {
                    const rows = _homeRows();
                    gameEl = rows[_state.row]?.items[_state.col] || null;
                    break;
                }
                case 'library': {
                    if (_state.row >= 0) {
                        const item = _libraryNavItems()[_state.row] || null;
                        gameEl = (_isGroupHeader(item)) ? null : item;
                    }
                    break;
                }
                case 'pick': {
                    const rows = _pickRows();
                    const row  = rows[_state.row];
                    if (row?.type === 'results') {
                        gameEl = row.items[_state.col] || null;
                    }
                    break;
                }
            }
        }

        if (!gameEl) return;

        // Save the content position NOW before any zone changes.
        // This is the position we want to return to after closing the ctx-menu
        // OR after closing any modal opened from the ctx-menu (e.g. Edit Game).
        const _returnZone = _state.zone;
        const _returnRow  = _state.row;
        const _returnCol  = _state.col;

        // Position menu at top-right of the focused element
        const rect = gameEl.getBoundingClientRect();
        const evt  = new MouseEvent('contextmenu', {
            bubbles:   true,
            cancelable: true,
            clientX:   rect.right,
            clientY:   rect.top,
        });
        gameEl.dispatchEvent(evt);

        // After the menu is built (async due to status fetch), push ctx-menu zone
        // with the correct return position pre-loaded into prevZone/prevRow/prevCol
        requestAnimationFrame(() => {
            const menu = document.getElementById('ctx-menu');
            if (menu?.classList.contains('visible')) {
                // Manually set up zone stack so return target is content, not whatever zone was
                _state.prevZone = _returnZone;
                _state.prevRow  = _returnRow;
                _state.prevCol  = _returnCol;
                _state.zone     = 'ctx-menu';
                _state.subItem  = -1;
                // Find first non-disabled game-section item
                const items = _ctxItems();
                const firstGame = items.findIndex(el => {
                    return el.id === 'ctx-launch' || el.id === 'ctx-install' ||
                           el.id === 'ctx-store'  || el.id === 'ctx-completion' ||
                           el.id === 'ctx-edit';
                });
                _state.col = firstGame >= 0 ? firstGame : 0;
                _syncFocus();
            }
        });
    }

    function _handleY() {
        // Open edit modal for focused game
        let appid = null;

        if (_state.zone === 'content') {
            switch (PAGE) {
                case 'home': {
                    const rows = _homeRows();
                    const cap  = rows[_state.row]?.items[_state.col];
                    appid = cap ? parseInt(cap.dataset.appid) : null;
                    break;
                }
                case 'library': {
                    if (_state.row >= 0) {
                        const item = _libraryNavItems()[_state.row];
                        appid = (item && !_isGroupHeader(item)) ? parseInt(item.dataset.appid) : null;
                    }
                    break;
                }
                case 'pick': {
                    const rows = _pickRows();
                    const row  = rows[_state.row];
                    if (row?.type === 'results') {
                        const card = row.items[_state.col];
                        appid = card ? parseInt(card.dataset.appid) : null;
                    }
                    break;
                }
            }
        }

        if (!appid) return;

        if (typeof openEditModalById === 'function') {
            openEditModalById(appid);
            _pushZone('modal');
            requestAnimationFrame(() => { if (_state.zone === 'modal') _syncFocus(); });
        } else {
            fetch(`/api/game/${appid}`)
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'success' && typeof openEditModal === 'function') {
                        openEditModal(data.game);
                        _pushZone('modal');
                        requestAnimationFrame(() => { if (_state.zone === 'modal') _syncFocus(); });
                    }
                })
                .catch(() => {});
        }
    }

    function _handleBack() {
        // Don't touch the hamburger while any modal is open — let B handle closing.
        if (_anyWatchedOpen()) return;
        const hm = document.getElementById('hamburger-menu');
        if (!hm) return;
        if (hm.classList.contains('open')) {
            hm.classList.remove('open');
            if (_state.zone === 'dropdown') _popZone();
            _syncFocus();
        } else {
            hm.classList.add('open');
            // Activate if not already — _syncFocus() requires _state.active and
            // _activate() would overwrite the zone we're about to push, so we do
            // the activation steps manually here.
            if (!_state.active) {
                _state.active = true;
                _hideCursor();
                if (window._clearGameCardHover) window._clearGameCardHover();
                if (window._cancelTooltipReshow) window._cancelTooltipReshow();
            }
            _pushZone('dropdown');
            _state.col = 0;
            _syncFocus();
        }
    }

    function _handleStart() {
        // Act like A when focused on a game card (launch the game)
        if (!_state.active) return;
        if (_state.zone === 'content') {
            switch (PAGE) {
                case 'home': {
                    const rows = _homeRows();
                    const cap  = rows[_state.row]?.items[_state.col];
                    const appid = cap ? parseInt(cap.dataset.appid) : null;
                    if (appid) launchGame(appid);
                    break;
                }
                case 'library': {
                    if (_state.row >= 0) {
                        const item = _libraryNavItems()[_state.row];
                        const appid = (item && !_isGroupHeader(item)) ? parseInt(item.dataset.appid) : null;
                        if (appid) launchGame(appid);
                    }
                    break;
                }
                case 'pick': {
                    const rows = _pickRows();
                    const row  = rows[_state.row];
                    if (row?.type === 'results') {
                        const card  = row.items[_state.col];
                        const appid = card ? parseInt(card.dataset.appid) : null;
                        if (appid) launchGame(appid);
                    }
                    break;
                }
            }
        }
    }

    function _handleLB() {
        if (_state.zone === 'modal') return;
        const idx = _currentPageIdx();
        if (idx > 0) window.location.href = PAGE_URLS[idx - 1];
    }

    function _handleRB() {
        if (_state.zone === 'modal') return;
        const idx = _currentPageIdx();
        if (idx < PAGE_URLS.length - 1) window.location.href = PAGE_URLS[idx + 1];
    }

    // ── Button/axis dispatch ──────────────────────────────────────────────────

    // Map button index → handler (standard Xbox / standard-mapping layout)
    const _BTN_HANDLERS = {
        [BTN_IDX.a]:     () => _handleA(),
        [BTN_IDX.b]:     () => _handleB(),
        [BTN_IDX.x]:     () => _handleX(),
        [BTN_IDX.y]:     () => _handleY(),
        [BTN_IDX.back]:  () => _handleBack(),
        [BTN_IDX.start]: () => _handleStart(),
        [BTN_IDX.lb]:    () => _handleLB(),
        [BTN_IDX.rb]:    () => _handleRB(),
        [BTN_IDX.up]:    () => _handleUp(),
        [BTN_IDX.down]:  () => _handleDown(),
        [BTN_IDX.left]:  () => _handleLeft(),
        [BTN_IDX.right]: () => _handleRight(),
    };

    // Buttons that use auto-repeat when held
    const _REPEAT_BTNS = new Set([BTN_IDX.up, BTN_IDX.down, BTN_IDX.left, BTN_IDX.right]);

    // Buttons that fire immediately without needing nav activation first
    const _IMMEDIATE_BTNS = new Set([BTN_IDX.lb, BTN_IDX.rb, BTN_IDX.back]);

    function _onButton(rawIdx, isRepeat) {
        const userAction     = _userRemap[rawIdx];
        const platformAction = !userAction && _activeMapping?.btns[rawIdx];
        const resolvedAction = userAction || platformAction;
        const effectiveIdx   = resolvedAction ? BTN_IDX[resolvedAction] : rawIdx;
        // While a text input has focus, only B is handled (to exit); everything else is typed.
        if (_state.zone === 'text-input' && effectiveIdx !== BTN_IDX.b) return;
        // While a number input has focus, only B/up/down are handled.
        if (_state.zone === 'number-input' && effectiveIdx !== BTN_IDX.b && effectiveIdx !== BTN_IDX.up && effectiveIdx !== BTN_IDX.down) return;
        const handler = _BTN_HANDLERS[effectiveIdx];
        if (!handler) return;
        if (_IMMEDIATE_BTNS.has(effectiveIdx)) {
            handler();
            return;
        }
        if (!_state.active) {
            if (!isRepeat) _activate();
            return;
        }
        handler();
    }

    // ── Gamepad polling ───────────────────────────────────────────────────────
    let _pollCount = 0;
    let _rafId = null;

    function _pollLoop() {
        _rafId = requestAnimationFrame(_pollLoop);
        _pollCount++;

        if (!_gamepadEnabled) return;

        const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
        let gp = null;
        for (const g of gamepads) { if (g) { gp = g; break; } }
        if (!gp) return;

        if (_gameSuppressed) {
            if (gp.buttons.some(b => b.pressed || b.value > 0.5))
                document.dispatchEvent(new CustomEvent('gamepad-suppressed-input'));
            return;
        }

        if (!_gpEverSeen) {
            _gpEverSeen = true;
            safeSession.setItem('pd_gp_seen', '1');
        }

        if (gp.id !== _lastGpId) {
            _lastGpId = gp.id;
            _activeMapping = PLATFORM_MAPPINGS.find(m => m.detect(gp.id)) || null;
        }

        const now = performance.now();

        // ── Buttons ───────────────────────────────────────────────────────────
        // When the remap modal is capturing a button press, keep prev state updated
        // so the remap RAF sees clean edges, but suppress all normal dispatch.
        // Safety net: auto-clear if the remap modal is no longer visible.
        if (_capturing) {
            const remapModal = document.getElementById('gamepad-remap-modal');
            if (!remapModal || remapModal.style.display === 'none') {
                _capturing = false;
            } else {
                gp.buttons.forEach((btn, i) => { _gp.prev[i] = btn.pressed || btn.value > 0.5; });
                return;
            }
        }

        gp.buttons.forEach((btn, i) => {
            const pressed    = btn.pressed || btn.value > 0.5;
            const wasPressed = !!_gp.prev[i];

            if (pressed && !wasPressed) {
                _gp.heldSince[i]  = now;
                _gp.lastRepeat[i] = now;
                _onButton(i, false);
            } else if (pressed && wasPressed && _REPEAT_BTNS.has(i) && _state.active) {
                if (now - _gp.heldSince[i]  > REPEAT_INITIAL &&
                    now - _gp.lastRepeat[i] > REPEAT_RATE) {
                    _gp.lastRepeat[i] = now;
                    _onButton(i, true);
                }
            } else if (!pressed && wasPressed) {
                delete _gp.heldSince[i];
                delete _gp.lastRepeat[i];
            }
            _gp.prev[i] = pressed;
        });

        // Sticks are suppressed while a text field has real focus — Steam Deck's
        // on-screen keyboard also reads stick input for its own key navigation,
        // and without this both the OSK and the page would move at once.
        // Buttons are unaffected (per-button zone guards, e.g. B's exit-text-
        // input handling, still need to fire normally), only continuous stick
        // movement is skipped here.
        if (_isTextEntryFocused()) {
            _gp.stickDir = null;
            if (_gp.rStickHeldSince && typeof window._scrollPreviewHide === 'function') window._scrollPreviewHide();
            _gp.rStickHeldSince = 0;
            return;
        }

        // ── Right stick (scroll) ──────────────────────────────────────────────
        const rsy = gp.axes[AXIS_IDX.ry] || 0;
        if (Math.abs(rsy) > STICK_DEAD) {
            if (!_gp.rStickHeldSince) _gp.rStickHeldSince = now;
            const heldMs = now - _gp.rStickHeldSince;
            let speedMult = 1;
            if (heldMs > SCROLL_RAMP_DELAY) {
                const rampSeconds = (heldMs - SCROLL_RAMP_DELAY) / 1000;
                speedMult = Math.min(SCROLL_RAMP_MAX, Math.pow(SCROLL_RAMP_GROWTH, rampSeconds));
            }
            const _scrollYBefore = window.scrollY;
            window.scrollBy({ top: rsy * SCROLL_BASE_SPEED * speedMult, behavior: 'auto' });
            const atScrollBoundary = window.scrollY === _scrollYBefore;
            // Only once actually ramped up — showing it immediately at base
            // speed would clutter ordinary scrolling, which isn't fast enough
            // to need a position preview at all. Also hidden once the page
            // can't scroll any further (top/bottom reached), since holding
            // the stick there no longer does anything worth previewing.
            if (speedMult >= SCROLL_PREVIEW_MIN && !atScrollBoundary) {
                if (typeof window._scrollPreviewShow === 'function') window._scrollPreviewShow();
                if (typeof window._scrollPreviewUpdate === 'function') window._scrollPreviewUpdate();
            } else if (typeof window._scrollPreviewHide === 'function') {
                window._scrollPreviewHide();
            }
        } else {
            if (_gp.rStickHeldSince && typeof window._scrollPreviewHide === 'function') window._scrollPreviewHide();
            _gp.rStickHeldSince = 0;
        }

        // ── Left stick ────────────────────────────────────────────────────────
        const ax = gp.axes[AXIS_IDX.lx] || 0;
        const ay = gp.axes[AXIS_IDX.ly] || 0;
        let stickDir = null;
        if      (ay < -STICK_DEAD) stickDir = 'up';
        else if (ay >  STICK_DEAD) stickDir = 'down';
        else if (ax < -STICK_DEAD) stickDir = 'left';
        else if (ax >  STICK_DEAD) stickDir = 'right';

        if (stickDir !== _gp.stickDir) {
            _gp.stickDir    = stickDir;
            _gp.stickHeld   = now;
            _gp.stickRepeat = now;
            if (stickDir) {
                if (!_state.active) _activate();
                else _fireStick(stickDir);
            }
        } else if (stickDir && _state.active) {
            if (now - _gp.stickHeld   > REPEAT_INITIAL &&
                now - _gp.stickRepeat > REPEAT_RATE) {
                _gp.stickRepeat = now;
                _fireStick(stickDir);
            }
        }
    }

    function _fireStick(dir) {
        switch (dir) {
            case 'up':    _handleUp();    break;
            case 'down':  _handleDown();  break;
            case 'left':  _handleLeft();  break;
            case 'right': _handleRight(); break;
        }
    }

    window.addEventListener('gamepadconnected', () => {
        if (!_rafId) _rafId = requestAnimationFrame(_pollLoop);
    });
    _rafId = requestAnimationFrame(_pollLoop);

    // ── Pause polling when window loses focus (e.g. a game launched) ─────────
    window.addEventListener('blur', () => {
        if (_rafId) {
            cancelAnimationFrame(_rafId);
            _rafId = null;
        }
        _clearGamepadState();
    });
    window.addEventListener('focus', () => {
        if (!_rafId) _rafId = requestAnimationFrame(_pollLoop);
    });

    // ── Library re-focus hook ─────────────────────────────────────────────────
    // Called by library.html's observeCards after populating a card.
    // Checks if this card is the one the input manager has focused.
    window._inputMgr.onCardPopulated = function (card, appid) {
        if (_state.active && _state.focusedAppid === appid) {
            card.classList.add('gamepad-focus');
        }
    };

    // Move gamepad focus to a specific library card without calling scrollIntoView
    // (used by the dice picker, which handles its own scroll animation).
    window._inputMgr.focusLibraryCard = function (appid) {
        if (!_state.active || PAGE !== 'library') return;
        const items = _libraryNavItems();
        const idx = items.findIndex(el => !_isGroupHeader(el) && parseInt(el.dataset.appid) === appid);
        if (idx < 0) return;
        _state.zone         = 'content';
        _state.row          = idx;
        _state.focusedAppid = appid;
        _clearFocus();
        items[idx].classList.add('gamepad-focus');
    };

    // ── Modal zone cleanup ────────────────────────────────────────────────────
    // Registry of all watched modals — used to decide whether to pop the modal zone
    // when one closes. If any sibling is still open, the zone stays at 'modal'.
    const _watchedEls = [];
    function _anyWatchedOpen() {
        return _watchedEls.some(w => w());
    }

    function _onModalOpen() {
        if (!_state.active) return;
        if (_state.zone !== 'modal') {
            if (_state.zone === 'ctx-menu') {
                document.querySelectorAll('.ctx-sub-open').forEach(el => el.classList.remove('ctx-sub-open'));
                _popZone();
            }
            // Also pop dropdown zone so prevZone is content, not the now-closed hamburger
            if (_state.zone === 'dropdown') _popZone();
            _pushZone('modal');
            requestAnimationFrame(() => { if (_state.zone === 'modal') _syncFocus(); });
        }
    }

    function _onModalClose() {
        if (!_state.active) return;
        if (_state.zone === 'modal') {
            if (!_anyWatchedOpen()) {
                _popZone();
            }
            // Always resync — the just-closed element may have held focus,
            // and a parent modal (if still open) needs its own element focused.
            _syncFocus();
        }
    }

    // Exposed so playdate.js can forcibly re-enter modal zone after eyedropper completes.
    window._gpRefocusModal = function () {
        if (!_state.active) return;
        if (_state.zone !== 'modal') _pushZone('modal');
        _state.modalFocused = null;
        requestAnimationFrame(() => _syncFocus());
    };

    function _watchModal(id) {
        const el = document.getElementById(id);
        if (!el) return;
        const isVisible = () => el.style.display !== 'none' && el.style.display !== '';
        _watchedEls.push(isVisible);
        let _wasVisible = isVisible();
        new MutationObserver(() => {
            const nowVisible = isVisible();
            if (nowVisible === _wasVisible) return;
            _wasVisible = nowVisible;
            if (nowVisible) _onModalOpen(); else _onModalClose();
        }).observe(el, { attributes: true, attributeFilter: ['style'] });
    }

    // Variant for elements shown via CSS class (e.g. pd-dialog-overlay uses .visible)
    function _watchModalByClass(id) {
        const el = document.getElementById(id);
        if (!el) return;
        const isVisible = () => el.classList.contains('visible');
        _watchedEls.push(isVisible);
        let _wasVisible = isVisible();
        new MutationObserver(() => {
            const nowVisible = isVisible();
            if (nowVisible === _wasVisible) return;
            _wasVisible = nowVisible;
            if (nowVisible) _onModalOpen(); else _onModalClose();
        }).observe(el, { attributes: true, attributeFilter: ['class'] });
    }

    // ── DOM-ready observers (modal elements don't exist until DOMContentLoaded) ─
    document.addEventListener('DOMContentLoaded', () => {
        // Context menu zone cleanup
        const _ctxMenuEl = document.getElementById('ctx-menu');
        if (_ctxMenuEl) {
            const _ctxObserver = new MutationObserver(() => {
                if (!_ctxMenuEl.classList.contains('visible') && _state.active) {
                    document.querySelectorAll('.ctx-sub-open').forEach(el => el.classList.remove('ctx-sub-open'));
                    // Always restore to content zone when ctx-menu closes —
                    // even if zone was never pushed (B pressed before rAF fired)
                    if (_state.zone === 'ctx-menu') _popZone();
                    // else zone is already content/nav — just re-sync focus
                    _syncFocus();
                }
            });
            _ctxObserver.observe(_ctxMenuEl, { attributes: true, attributeFilter: ['class'] });
        }

        // pd-dialog-overlay (base.html confirm/alert — visibility via .visible class)
        _watchModalByClass('pd-dialog-overlay');

        // First-run config modal (modal_edit.html, needs_config) — present
        // already-visible via CSS (no JS open/close toggle), so register it
        // even though its inline style never changes after load.
        _watchModal('config-modal');

        // Edit / filter modals (base.html — present on every page)
        _watchModal('editModal');
        _watchModal('filterModal');
        _watchModal('viewModal');

        // Library bulk modals — full zone push/pop so focus enters and returns correctly
        _watchModal('bulk-edit-modal');
        _watchModal('bulk-rescrape-modal');
        _watchModal('bulk-delete-modal');

        // Top-level hamburger modals
        _watchModal('account-modal');
        _watchModal('appearance-modal');
        _watchModal('library-modal');
        _watchModal('plugins-modal');
        _watchModal('community-modal');
        _watchModal('data-modal');
        _watchModal('system-modal');
        _watchModal('blacklist-modal');

        // Sub-modals (also registered so _anyWatchedOpen works correctly for nesting)
        _watchModal('gamepad-remap-modal');
        _watchModal('gamepad-diag-modal');
        _watchModal('hltb-modal');
        _watchModal('theme-picker-modal');
        _watchModal('santa-modal');
        _watchModal('playnite-modal');
        _watchModal('filter-io-modal');
        _watchModal('backup-modal');
        _watchModal('bg-modal');
        _watchModal('import-modal');
        _watchModal('pagywosg-modal');
        _watchModal('theme-modal');

        // Color picker popover — dynamically inserted/removed from document.body
        const _cpPopVisible = () => !!document.getElementById('_color-picker-popover');
        _watchedEls.push(_cpPopVisible);
        let _cpPopWasVisible = false;
        new MutationObserver(() => {
            const nowVisible = _cpPopVisible();
            if (nowVisible !== _cpPopWasVisible) {
                _cpPopWasVisible = nowVisible;
                if (nowVisible) _onModalOpen(); else _onModalClose();
            }
        }).observe(document.body, { childList: true });

        // Home page edit mode panels
        _watchModal('shelf-edit-modal');
        _watchModal('dedup-panel');
        _watchModal('split-picker');
    });

})();
