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
        prevModalRow:     null,
        prevModalCol:     null,
        prevModalRowKey:  null,  // data-modal-row VALUE saved on dropdown push (stable across DOM changes)
        row:              0,
        col:              0,
        savedCol:         0,
        subItem:          -1,
        modalRow:         0,
        modalCol:         0,
        focusedAppid:     null,
    };

    // Expose focusedAppid so library.html's observeCards can re-apply the class
    window._inputMgr = {
        get focusedAppid() { return _state.focusedAppid; },
        suppressForGame() {
            _gameSuppressed = true;
            sessionStorage.setItem('pd_game_running', '1');
            _clearGamepadState();
            _watchForGameClose();
        },
        clearSuppression() {
            _gameSuppressed = false;
            sessionStorage.removeItem('pd_game_running');
            _clearGamepadState();
        },
        unsuppressGamepad() {
            _unsuppressGamepad();
        },
    };

    // Track whether a gamepad has ever been seen this session (persisted across page loads)
    let _gpEverSeen = sessionStorage.getItem('pd_gp_seen') === '1';

    // ── Game-running suppression ──────────────────────────────────────────────
    // Set when a game launches; persists across the page reload that follows.
    // Cleared only when the user explicitly interacts with PlayDate (click/key).
    // This is the only reliable way to stop gamepad input while a game is running:
    // the gamepad is shared hardware and focus events don't fire in pywebview.
    let _gameSuppressed = sessionStorage.getItem('pd_game_running') === '1';

    function _clearGamepadState() {
        _gp.prev        = {};
        _gp.heldSince   = {};
        _gp.lastRepeat  = {};
        _gp.stickDir    = null;
        _gp.stickHeld   = 0;
        _gp.stickRepeat = 0;
    }

    function _unsuppressGamepad() {
        if (!_gameSuppressed) return;
        _gameSuppressed = false;
        sessionStorage.removeItem('pd_game_running');
    }

    // Two-phase watcher: polls /api/game-running (checks Steam's reaper process on
    // Linux) to detect when a launched game actually closes, then unsuppresses the
    // gamepad and raises the PlayDate window regardless of where the window manager
    // sent focus after the game exited.
    function _watchForGameClose() {
        let gameStarted = false;
        let attempts = 0;
        const MAX_ATTEMPTS = 90; // 3 minutes at 2s intervals

        function poll() {
            if (!_gameSuppressed) return; // already cleared by click/key/focus
            if (++attempts > MAX_ATTEMPTS) {
                // Safety timeout — something went wrong, unsuppress anyway
                _unsuppressGamepad();
                return;
            }
            fetch('/api/game-running')
                .then(r => r.json())
                .then(d => {
                    if (d.running === null) return; // unsupported platform, rely on focus events
                    if (d.running) {
                        gameStarted = true;
                        setTimeout(poll, 2000);
                    } else if (gameStarted) {
                        // Game was running, now it's not — it closed
                        fetch('/api/raise-window', { method: 'POST' }).catch(() => {});
                        _unsuppressGamepad();
                    } else {
                        // Game hasn't started yet (Steam loading), keep waiting
                        setTimeout(poll, 2000);
                    }
                })
                .catch(() => setTimeout(poll, 3000));
        }

        setTimeout(poll, 1000);
    }

    // Also start watching if we're resuming suppressed state from a page reload
    if (_gameSuppressed) _watchForGameClose();

    document.addEventListener('mousedown', _unsuppressGamepad);
    document.addEventListener('keydown',   _unsuppressGamepad);

    // ── Gamepad polling state ─────────────────────────────────────────────────
    const _gp = {
        prev:        {},   // button index → bool
        heldSince:   {},   // button index → timestamp when first pressed
        lastRepeat:  {},   // button index → timestamp of last repeat fire
        stickDir:    null, // current stick direction or null
        stickHeld:   0,
        stickRepeat: 0,
    };

    const REPEAT_INITIAL  = 400;
    const REPEAT_RATE     = 150;
    const STICK_DEAD      = 0.35;

    // ── Standard Xbox/standard-mapping button indices ─────────────────────────
    const BTN_IDX = { a:0, b:1, x:2, y:3, lb:4, rb:5, back:8, start:9, up:12, down:13, left:14, right:15 };
    const AXIS_IDX = { lx:0, ly:1, rx:2, ry:3 };

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
        // Home capsules are always fully visible (shelf overflow:hidden clips them anyway)
        // so skip scrollIntoView there — it causes a reflow that flickers the focus ring off.
        if (PAGE !== 'home') {
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
                    case 'library': return _state.row === _libraryCards().length - 1;
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
        return [...bar.querySelectorAll('button.shelf-edit-mini-btn')]
            .filter(el => el.offsetParent !== null && !el.disabled);
    }

    function _visibleCapsules(el) {
        return [...el.querySelectorAll('.shelf-capsule-wrap')].filter(c => {
            return c.style.display !== 'none' && c.offsetParent !== null;
        });
    }

    // Library: returns flat array of .game-card elements and computes column count
    function _libraryCards() {
        return [...document.querySelectorAll('.game-card')];
    }

    // Library toolbar: buttons and select only — the text input is not directly
    // navigated; pressing A on the SEARCH button focuses it for typing instead.
    function _libraryToolbarItems() {
        return [...document.querySelectorAll(
            '.search-nav-bar button, .search-nav-bar .custom-select'
        )].filter(el => el.offsetParent !== null && !el.disabled);
    }

    function _libraryColCount(cards) {
        if (!cards.length) return 1;
        // Use offsetTop which is stable at page load unlike getBoundingClientRect.
        // 10px tolerance handles subpixel rounding differences between cards.
        const firstTop = cards[0].offsetTop;
        let cols = 0;
        for (const c of cards) {
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

        // Rows 1..4: individual sliders (only when weighted panel is open)
        const panel = document.getElementById('weighted-panel');
        if (panel && panel.classList.contains('open')) {
            const sliders = [...panel.querySelectorAll('input[type="range"]')];
            sliders.forEach(s => rows.push({ type: 'slider', items: [s] }));
        }

        // Pick button row (always present)
        const pickBtn = document.querySelector('.pick-btn');

        // Pool toggle row (always present, between sliders/mode and pick button)
        // The checkbox itself is hidden; use the .toggle-switch label as the focusable element
        const poolLabel = document.querySelector('.toggle-switch');
        if (poolLabel) rows.push({ type: 'toggle', items: [poolLabel] });

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

    // Modal items: IDs of all modal overlays, checked in priority order
    const _MODAL_IDS = [
        'pd-dialog-overlay',   // base.html confirm/alert — shown via .visible class
        'editModal', 'filterModal',
        'backup-modal', 'bg-modal', 'import-modal',
        'bulk-edit-modal', 'bulk-rescrape-modal', 'bulk-delete-modal',
        // Tools page expanding modals
        'pagywosg-modal', 'blacklist-modal', 'theme-modal',
        // Home page edit mode panels (use style.display)
        'shelf-edit-modal', 'dedup-panel', 'split-picker',
    ];

    // Visibility check that handles both inline-style modals and class-toggled ones (.visible)
    function _isModalVisible(el) {
        if (!el) return false;
        if (el.classList.contains('visible')) return true;
        return el.style.display !== 'none' && el.style.display !== '';
    }

    // Returns buttons grouped into rows. If any element has data-modal-row, groups
    // by that attribute (sorted by row number). Otherwise returns all as a single row.
    // Includes buttons, nav/save links, and tagged selects. Groups by data-modal-row if present.
    function _modalGrid() {
        // Custom select picker takes priority
        const picker = document.getElementById('_gp-select-picker');
        if (picker) {
            return [...picker.querySelectorAll('button[data-modal-row]')].map(b => [b]);
        }

        for (const id of _MODAL_IDS) {
            const el = document.getElementById(id);
            if (el && _isModalVisible(el)) {
                const candidates = [...el.querySelectorAll(
                    'button:not(:disabled), a.nav-btn, a.btn-save, select[data-modal-row], .custom-select[data-modal-row]'
                )].filter(e => e.offsetParent !== null && !e.disabled
                         // Exclude ✕/× buttons that have no data-modal-row (those are handled by row -1)
                         && !((e.textContent.trim() === '✕' || e.textContent.trim() === '×') && e.dataset.modalRow === undefined)
                         // Never include pill remove buttons (× inside .pill spans)
                         && !e.closest('.pill'));
                const tagged = candidates.filter(e => e.dataset.modalRow !== undefined);
                if (!tagged.length) return candidates.length ? [candidates] : [];
                const map = new Map();
                for (const e of tagged) {
                    const r = parseInt(e.dataset.modalRow);
                    if (!map.has(r)) map.set(r, []);
                    map.get(r).push(e);
                }
                return [...map.keys()].sort((a, b) => a - b).map(r => map.get(r));
            }
        }
        return [];
    }

    // Returns the ✕ close button of the currently visible modal, or null.
    function _modalCloseBtn() {
        for (const id of _MODAL_IDS) {
            const el = document.getElementById(id);
            if (el && _isModalVisible(el)) {
                const btn = [...el.querySelectorAll('button')].find(b => {
                    const t = b.textContent.trim();
                    return (t === '✕' || t === '×') && b.offsetParent !== null && b.dataset.modalRow === undefined && !b.closest('.pill');
                });
                if (btn) return btn;
            }
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
                            const cards = _libraryCards();
                            if (!cards.length) break;
                            const idx = Math.min(_state.row, cards.length - 1);
                            const card = cards[idx];
                            _state.focusedAppid = parseInt(card.dataset.appid) || null;
                            _applyFocus(card);
                            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
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
                if (_state.modalRow === -1) {
                    const closeBtn = _modalCloseBtn();
                    if (closeBtn) { _applyFocus(closeBtn); break; }
                    _state.modalRow = 0; // no close btn, fall through
                }
                const mgrid = _modalGrid();
                if (mgrid.length) {
                    _state.modalRow = Math.min(_state.modalRow, mgrid.length - 1);
                    const row = mgrid[_state.modalRow];
                    _state.modalCol = Math.min(_state.modalCol, row.length - 1);
                    _applyFocus(row[_state.modalCol]);
                } else {
                    _clearFocus();
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

            default:
                _state.zone = 'nav'; _state.col = 0;
                _syncFocus();
                break;
        }
    }

    // ── Activation ────────────────────────────────────────────────────────────
    function _activate() {
        if (_state.active) return;
        _state.active = true;
        _state.zone     = 'content';
        _state.row      = 0;
        _state.col      = 0;
        _state.savedCol = 0;
        _syncFocus();
    }

    function _deactivate() {
        _state.active = false;
        _clearFocus();
        _state.focusedAppid = null;
    }

    // Deactivate on mouse click so mouse users don't see a lingering focus ring
    document.addEventListener('mousedown', () => {
        if (_state.active) _deactivate();
    });

    // ── Zone helpers ──────────────────────────────────────────────────────────
    function _pushZone(zone) {
        _state.prevZone         = _state.zone;
        _state.prevRow          = _state.row;
        _state.prevCol          = _state.col;
        _state.prevModalRow     = _state.modalRow;
        _state.prevModalCol     = _state.modalCol;
        // When entering dropdown from modal, save the data-modal-row VALUE of the focused
        // element so we can restore the correct row even if the DOM changes (e.g. filter
        // modal switching between simple/advanced hides rows and shifts array indices).
        if (zone === 'dropdown' && _state.zone === 'modal') {
            const mgrid = _modalGrid();
            const el = mgrid[_state.modalRow]?.[_state.modalCol];
            _state.prevModalRowKey = el?.dataset?.modalRow ?? null;
        } else {
            _state.prevModalRowKey = null;
        }
        _state.zone          = zone;
        _state.col           = 0;
        _state.subItem       = -1;
        // Don't reset modalRow/Col when entering dropdown — we'll restore them on pop
        if (zone !== 'dropdown') {
            _state.modalRow  = 0;
            _state.modalCol  = 0;
        }
    }

    function _popZone() {
        const returningToModal = _state.prevZone === 'modal';
        _state.zone    = _state.prevZone;
        _state.row     = _state.prevRow  ?? _state.row;
        _state.col     = _state.prevCol  ?? _state.col;
        if (returningToModal) {
            if (_state.prevModalRowKey != null) {
                // Translate the saved data-modal-row VALUE back to an array index.
                // This survives DOM changes (e.g. filter modal switching modes hides rows).
                const mgrid = _modalGrid();
                const idx = mgrid.findIndex(row => row[0]?.dataset?.modalRow === _state.prevModalRowKey);
                _state.modalRow = idx >= 0 ? idx : (_state.prevModalRow ?? 0);
            } else {
                _state.modalRow = _state.prevModalRow ?? _state.modalRow;
            }
            _state.modalCol = _state.prevModalCol ?? _state.modalCol;
        }
        _state.prevZone        = 'content';
        _state.prevRow         = null;
        _state.prevCol         = null;
        _state.prevModalRow    = null;
        _state.prevModalCol    = null;
        _state.prevModalRowKey = null;
        _state.subItem         = -1;
    }

    // ── Direction handlers ────────────────────────────────────────────────────

    function _handleUp() {
        switch (_state.zone) {

            case 'modal': {
                if (_state.modalRow === -1) break; // already at top
                const mgrid = _modalGrid();
                if (_state.modalRow === 0) {
                    if (_modalCloseBtn()) { _state.modalRow = -1; _syncFocus(); }
                    // else: already at top row, true no-op — do not call _syncFocus() to avoid side effects
                    break;
                }
                if (mgrid.length && _state.modalRow > 0) {
                    _state.modalRow--;
                    _state.modalCol = Math.min(_state.modalCol, mgrid[_state.modalRow].length - 1);
                    _syncFocus();
                }
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
                        const rows = _homeRows();
                        const editMode = document.body.classList.contains('edit-mode');
                        let prev = _state.row - 1;
                        // In normal mode, skip the sibling side of the same split row
                        // (both sides are the same visual row). In edit mode each side
                        // has its own edit bar so we navigate them individually.
                        if (!editMode && prev >= 0) {
                            const curEl    = rows[_state.row]?.el;
                            const prevEl   = rows[prev]?.el;
                            const curSplit  = curEl?.closest?.('.shelf-split-row');
                            const prevSplit = prevEl?.closest?.('.shelf-split-row');
                            if (curSplit && prevSplit && curSplit === prevSplit) prev--;
                        }
                        // Skip empty rows (don't go below 0)
                        while (prev > 0 && rows[prev]?.items.length === 0) prev--;
                        if (prev >= 0 && rows[prev]?.items.length > 0) {
                            const srcItem  = rows[_state.row]?.items[_state.col];
                            const srcCol   = _state.col;
                            const srcTotal = rows[_state.row]?.items.length ?? 1;
                            const target   = _findNavTarget(rows, prev, srcItem, srcCol, srcTotal);
                            _state.row = target.rowIdx;
                            _state.col = target.colIdx;
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
                            const cards = _libraryCards();
                            const cols  = _libraryColCount(cards);
                            const newIdx = _state.row - cols;
                            if (newIdx < 0) {
                                // First grid row → toolbar
                                _state.row = -1;
                                _state.col = 0;
                            } else {
                                _state.row = newIdx;
                                _state.col = _state.row % cols;
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

            case 'modal': {
                if (_state.modalRow === -1) {
                    _state.modalRow = 0; _state.modalCol = 0; _syncFocus(); break;
                }
                const mgrid = _modalGrid();
                if (mgrid.length && _state.modalRow < mgrid.length - 1) {
                    _state.modalRow++;
                    _state.modalCol = Math.min(_state.modalCol, mgrid[_state.modalRow].length - 1);
                    _syncFocus();
                }
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
                        const rows = _homeRows();
                        const editMode = document.body.classList.contains('edit-mode');
                        let next = _state.row + 1;
                        // In normal mode, skip the sibling side of the same split row.
                        // In edit mode each side has its own edit bar.
                        if (!editMode && next < rows.length) {
                            const curEl  = rows[_state.row]?.el;
                            const nxtEl  = rows[next]?.el;
                            const curSplit = curEl?.closest?.('.shelf-split-row');
                            const nxtSplit = nxtEl?.closest?.('.shelf-split-row');
                            if (curSplit && nxtSplit && curSplit === nxtSplit) next++;
                        }
                        // Skip empty rows
                        while (next < rows.length && rows[next]?.items.length === 0) next++;
                        if (next < rows.length) {
                            const srcItem  = rows[_state.row]?.items[_state.col];
                            const srcCol   = _state.col;
                            const srcTotal = rows[_state.row]?.items.length ?? 1;
                            const target   = _findNavTarget(rows, next, srcItem, srcCol, srcTotal);
                            _state.row = target.rowIdx;
                            _state.col = target.colIdx;
                        }
                        _syncFocus();
                        break;
                    }

                    case 'library': {
                        if (_state.row === -1) {
                            // Toolbar → first grid row
                            _state.row = 0;
                            _state.col = 0;
                        } else {
                            const cards = _libraryCards();
                            const cols  = _libraryColCount(cards);
                            const newIdx = Math.min(_state.row + cols, cards.length - 1);
                            _state.row = newIdx;
                            _state.col = _state.row % cols;
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
                const mgrid = _modalGrid();
                if (mgrid.length && _state.modalCol > 0) {
                    _state.modalCol--;
                    _syncFocus();
                }
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
                            // Grid: no cross-row wrap
                            if (_state.row > 0) _state.row--;
                            const cards2 = _libraryCards();
                            const cols2  = _libraryColCount(cards2);
                            _state.col = _state.row % cols2;
                        }
                        _state.savedCol = _state.col;
                        _syncFocus();
                        break;
                    }

                    case 'pick': {
                        const rows = _pickRows();
                        const row  = rows[_state.row];
                        if (row?.type === 'slider') {
                            // Left decrements slider value by 5
                            const slider = row.items[0];
                            slider.value = Math.max(parseInt(slider.min || 0), parseInt(slider.value) - 5);
                            slider.dispatchEvent(new Event('input'));
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
                const mgrid = _modalGrid();
                if (mgrid.length) {
                    const row = mgrid[_state.modalRow];
                    if (_state.modalCol < row.length - 1) {
                        _state.modalCol++;
                        _syncFocus();
                    }
                }
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
                        } else {
                            const cards = _libraryCards();
                            if (_state.row < cards.length - 1) _state.row++;
                            const cols3 = _libraryColCount(cards);
                            _state.col = _state.row % cols3;
                        }
                        _state.savedCol = _state.col;
                        _syncFocus();
                        break;
                    }

                    case 'pick': {
                        const rows = _pickRows();
                        const row  = rows[_state.row];
                        if (row?.type === 'slider') {
                            // Right increments slider value by 5
                            const slider = row.items[0];
                            slider.value = Math.min(parseInt(slider.max || 100), parseInt(slider.value) + 5);
                            slider.dispatchEvent(new Event('input'));
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
        _state.modalRow = Math.max(0, selectEl.selectedIndex);
        _state.modalCol = 0;
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
                if (_state.modalRow === -1) {
                    _modalCloseBtn()?.click();
                    break;
                }
                const mgrid = _modalGrid();
                if (mgrid.length) {
                    const el = mgrid[_state.modalRow]?.[_state.modalCol];
                    if (el) {
                        if (el.tagName === 'SELECT') _openSelectPicker(el);
                        else el.click();
                    }
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
                        const appid = parseInt(cap.dataset.appid);
                        if (appid) launchGame(appid);
                        break;
                    }

                    case 'library': {
                        if (_state.row === -1) {
                            const items = _libraryToolbarItems();
                            const el = items[_state.col];
                            if (el) {
                                if (el.tagName === 'SELECT') _openSelectPicker(el);
                                else el.click();
                            }
                        } else {
                            const cards = _libraryCards();
                            const card  = cards[_state.row];
                            if (!card) break;
                            if (document.body.classList.contains('select-mode')) {
                                card.click(); // toggles selection via onCardClick
                            } else {
                                const appid = parseInt(card.dataset.appid);
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
                        } else if (row.type === 'toggle') {
                            // The .toggle-switch label wraps a hidden checkbox
                            const cb = row.items[0]?.querySelector('input[type="checkbox"]');
                            if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
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
            const hm = document.getElementById('hamburger-menu');
            if (hm?.classList.contains('open')) {
                _pushZone('dropdown');
                _state.col = 0;
                _syncFocus();
                return;
            }
            const cs = document.querySelector('.custom-select.open');
            if (cs) {
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

        // Try every known close function in priority order.
        // Also handles page-specific modals (bulk edit, tools modals).
        const checks = [
            // library page bulk modals
            ['bulk-edit-modal',     'closeBulkEditModal'],
            ['bulk-rescrape-modal', 'closeBulkRescrapeModal'],
            ['bulk-delete-modal',   'closeBulkDeleteModal'],
            // tools page modals
            ['backup-modal',     'closeBackupModal'],
            ['bg-modal',         'closeBgModal'],
            ['import-modal',     'closeImportModal'],
            ['pagywosg-modal',   'closePagModal'],
            ['blacklist-modal',  'closeBlacklistModal'],
            ['theme-modal',      'closeThemeModal'],
            // home page edit mode panels
            ['shelf-edit-modal', 'semClose'],
            ['dedup-panel',      'closeDedupPanel'],
            ['split-picker',     'closeSplitPicker'],
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

    function _handleB() {
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
                        gameEl = _libraryCards()[_state.row] || null;
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
                        const card = _libraryCards()[_state.row];
                        appid = card ? parseInt(card.dataset.appid) : null;
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
        // Home page: toggle edit mode
        if (PAGE === 'home') {
            if (document.body.classList.contains('edit-mode')) {
                if (typeof exitEditMode === 'function') exitEditMode();
            } else {
                if (typeof enterEditMode === 'function') enterEditMode();
            }
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
                        const card = _libraryCards()[_state.row];
                        const appid = card ? parseInt(card.dataset.appid) : null;
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
        if (document.getElementById('gamepad-diag-modal')?.style.display !== 'none') return;
        const idx = _currentPageIdx();
        if (idx > 0) window.location.href = PAGE_URLS[idx - 1];
    }

    function _handleRB() {
        if (document.getElementById('gamepad-diag-modal')?.style.display !== 'none') return;
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

    // Buttons that fire immediately without needing activation first
    const _IMMEDIATE_BTNS = new Set([BTN_IDX.lb, BTN_IDX.rb, BTN_IDX.back]);

    function _onButton(i, isRepeat) {
        const handler = _BTN_HANDLERS[i];
        if (!handler) return;
        // LB/RB fire immediately — no activation step needed
        if (_IMMEDIATE_BTNS.has(i)) {
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

        if (_gameSuppressed) return;

        const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
        let gp = null;
        for (const g of gamepads) { if (g) { gp = g; break; } }
        if (!gp) return;

        if (!_gpEverSeen) {
            _gpEverSeen = true;
            sessionStorage.setItem('pd_gp_seen', '1');
        }

        const now = performance.now();

        // ── Buttons ───────────────────────────────────────────────────────────
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

        // ── Right stick (scroll) ──────────────────────────────────────────────
        const rsy = gp.axes[AXIS_IDX.ry] || 0;
        if (Math.abs(rsy) > STICK_DEAD) {
            window.scrollBy({ top: rsy * 20, behavior: 'auto' });
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
    if (!_rafId) _rafId = requestAnimationFrame(_pollLoop);

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

    // ── Modal zone cleanup ────────────────────────────────────────────────────
    function _watchModal(id) {
        const el = document.getElementById(id);
        if (!el) return;
        let _wasVisible = el.style.display !== 'none' && el.style.display !== '';
        new MutationObserver(() => {
            const nowVisible = el.style.display !== 'none' && el.style.display !== '';
            if (nowVisible === _wasVisible) return;
            _wasVisible = nowVisible;
            if (!_state.active) return;
            if (nowVisible && _state.zone !== 'modal') {
                // If opening from ctx-menu, pop it first so prevZone is content not ctx-menu
                if (_state.zone === 'ctx-menu') {
                    document.querySelectorAll('.ctx-sub-open').forEach(el => el.classList.remove('ctx-sub-open'));
                    _popZone();
                }
                _pushZone('modal');
                requestAnimationFrame(() => { if (_state.zone === 'modal') _syncFocus(); });
            } else if (!nowVisible) {
                if (_state.zone === 'modal') _popZone();
                _syncFocus();
            }
        }).observe(el, { attributes: true, attributeFilter: ['style'] });
    }

    // Variant of _watchModal for elements shown via CSS class (e.g. pd-dialog-overlay uses .visible)
    function _watchModalByClass(id) {
        const el = document.getElementById(id);
        if (!el) return;
        let _wasVisible = el.classList.contains('visible');
        new MutationObserver(() => {
            const nowVisible = el.classList.contains('visible');
            if (nowVisible === _wasVisible) return;
            _wasVisible = nowVisible;
            if (!_state.active) return;
            if (nowVisible && _state.zone !== 'modal') {
                if (_state.zone === 'ctx-menu') {
                    document.querySelectorAll('.ctx-sub-open').forEach(el => el.classList.remove('ctx-sub-open'));
                    _popZone();
                }
                _pushZone('modal');
                requestAnimationFrame(() => { if (_state.zone === 'modal') _syncFocus(); });
            } else if (!nowVisible) {
                if (_state.zone === 'modal') _popZone();
                _syncFocus();
            }
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

        // Edit / filter modals (base.html — present on every page)
        _watchModal('editModal');
        _watchModal('filterModal');
        _watchModal('viewModal');

        // Library bulk modals — full zone push/pop so focus enters and returns correctly
        _watchModal('bulk-edit-modal');
        _watchModal('bulk-rescrape-modal');
        _watchModal('bulk-delete-modal');

        // Tools modals — full zone push/pop so focus enters and returns correctly
        _watchModal('gamepad-diag-modal');
        _watchModal('backup-modal');
        _watchModal('bg-modal');
        _watchModal('import-modal');
        _watchModal('pagywosg-modal');
        _watchModal('blacklist-modal');
        _watchModal('theme-modal');

        // Home page edit mode panels
        _watchModal('shelf-edit-modal');
        _watchModal('dedup-panel');
        _watchModal('split-picker');
    });

})();
