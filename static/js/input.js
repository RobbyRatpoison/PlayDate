/**
 * input.js — Gamepad navigation for PlayDate
 * Loaded globally via base.html. Self-contained IIFE, no exports.
 */
(function () {
    'use strict';

    // ── Crash detection ───────────────────────────────────────────────────────
    console.log('[input.js] IIFE starting');
    window.addEventListener('error', e => {
        console.error('[input.js] Uncaught error:', e.message, 'at', e.filename, e.lineno);
    });
    window.addEventListener('unhandledrejection', e => {
        console.error('[input.js] Unhandled promise rejection:', e.reason);
    });

    // ── Debug overlay (toggle with F9) ────────────────────────────────────────
    let _dbgEl = null;
    const _dbgLog = []; // rolling log of last 12 events

    function _dbgNote(msg) {
        const ts = performance.now().toFixed(0);
        _dbgLog.unshift(`[${ts}] ${msg}`);
        if (_dbgLog.length > 12) _dbgLog.pop();
        _dbgRender();
    }

    function _dbgRender() {
        if (!_dbgEl) return;
        const gp = (() => {
            const pads = navigator.getGamepads ? navigator.getGamepads() : [];
            for (const g of pads) if (g) return g;
            return null;
        })();

        let html = `<div style="font-weight:bold;margin-bottom:4px;color:#66c0f4;">PlayDate Input Debug <span style="font-weight:normal;color:#8f98a0;font-size:0.75em;">(F9 to hide)</span></div>`;

        // State
        html += `<div style="margin-bottom:4px;">zone=<b>${_state.zone}</b> row=<b>${_state.row}</b> col=<b>${_state.col}</b> mRow=<b>${_state.modalRow}</b> mCol=<b>${_state.modalCol}</b> active=<b>${_state.active}</b></div>`;
        html += `<div style="margin-bottom:4px;">prevZone=<b>${_state.prevZone}</b> prevRow=<b>${_state.prevRow}</b> prevCol=<b>${_state.prevCol}</b> gpSeen=<b>${_gpEverSeen}</b></div>`;

        // Modal detail — shown whenever zone=modal OR a modal is open
        const _dbgOpenModal = _MODAL_IDS.find(id => {
            const el = document.getElementById(id);
            return el && el.style.display !== 'none' && el.style.display !== '';
        });
        if (_dbgOpenModal || _state.zone === 'modal') {
            const mgrid = _modalGrid();
            const totalItems = mgrid.reduce((s, r) => s + r.length, 0);
            html += `<div style="color:#f0a030;margin-bottom:2px;">modal open: <b>${_dbgOpenModal || 'none'}</b> | rows: <b>${mgrid.length}</b> items: <b>${totalItems}</b> | zone: <b>${_state.zone}</b></div>`;
            html += `<div style="font-family:monospace;font-size:0.72em;margin-bottom:4px;">`;
            mgrid.forEach((row, ri) => {
                row.forEach((el, ci) => {
                    const active = ri === _state.modalRow && ci === _state.modalCol && _state.zone === 'modal';
                    const text = (el.textContent || '').trim().replace(/\s+/g,' ').slice(0, 22);
                    html += `<div style="color:${active ? '#66c0f4' : '#8f98a0'};${active ? 'font-weight:bold;' : ''}">${active ? '→' : '  '} [${ri},${ci}] &lt;${el.tagName.toLowerCase()}&gt; ${text}</div>`;
                });
            });
            html += `</div>`;
        }

        if (!gp) {
            html += `<div style="color:#ff8080;">No gamepad detected</div>`;
        } else {
            html += `<div style="color:#5c7e10;margin-bottom:4px;word-break:break-all;">GP: ${gp.id}</div>`;
            html += `<div style="margin-bottom:2px;color:#8f98a0;">mapping="${gp.mapping}" btns=${gp.buttons.length} axes=${gp.axes.length}</div>`;

            // Buttons — show ALL, highlight active ones
            html += `<div style="margin-bottom:2px;color:#8f98a0;">Buttons:</div>`;
            html += `<div style="font-family:monospace;font-size:0.75em;margin-bottom:4px;line-height:1.8;">`;
            gp.buttons.forEach((btn, i) => {
                const v = btn.value;
                const p = btn.pressed || v > 0.01;
                const bg = v > 0.5 ? '#66c0f4' : v > 0.01 ? '#f0ad4e' : '#1a2332';
                const fg = v > 0.5 ? '#0e1621' : '#c7d5e0';
                html += `<span style="background:${bg};color:${fg};padding:1px 4px;margin:1px;border-radius:3px;border:1px solid #2a475e;display:inline-block;">${i}:${v.toFixed(2)}</span>`;
            });
            html += `</div>`;

            // Axes — show ALL
            html += `<div style="margin-bottom:2px;color:#8f98a0;">Axes:</div>`;
            html += `<div style="font-family:monospace;font-size:0.75em;margin-bottom:6px;line-height:1.8;">`;
            gp.axes.forEach((v, i) => {
                const abs = Math.abs(v);
                const bg = abs > 0.5 ? '#66c0f4' : abs > 0.1 ? '#f0ad4e' : '#1a2332';
                const fg = abs > 0.5 ? '#0e1621' : '#c7d5e0';
                html += `<span style="background:${bg};color:${fg};padding:1px 4px;margin:1px;border-radius:3px;border:1px solid #2a475e;display:inline-block;">${i}:${v.toFixed(2)}</span>`;
            });
            html += `</div>`;
        }

        // Event log
        html += `<div style="color:#8f98a0;margin-bottom:2px;">Event log:</div>`;
        html += `<div style="font-family:monospace;font-size:0.75em;line-height:1.5;">`;
        _dbgLog.forEach((line, i) => {
            const opacity = 1 - i * 0.07;
            html += `<div style="opacity:${opacity.toFixed(2)}">${line}</div>`;
        });
        html += `</div>`;

        _dbgEl.innerHTML = html;
    }

    // Continuously refresh the gamepad state display (even without input events)
    function _dbgLoop() {
        requestAnimationFrame(_dbgLoop);
        if (_dbgEl) _dbgRender();
    }

    document.addEventListener('DOMContentLoaded', () => {
        _dbgEl = document.createElement('div');
        _dbgEl.id = 'pd-input-debug';
        _dbgEl.style.cssText = [
            'position:fixed', 'bottom:10px', 'right:10px', 'z-index:99999',
            'background:rgba(10,15,25,0.95)', 'border:1px solid #2a475e',
            'border-radius:6px', 'padding:10px 12px', 'font-size:0.78rem',
            'color:#c7d5e0', 'max-width:420px', 'min-width:320px',
            'line-height:1.4', 'display:none', 'pointer-events:none',
        ].join(';');
        document.body.appendChild(_dbgEl);
        requestAnimationFrame(_dbgLoop);
    });

    document.addEventListener('keydown', e => {
        if (e.key === 'F9') {
            if (_dbgEl) _dbgEl.style.display = _dbgEl.style.display === 'none' ? 'block' : 'none';
        }
    });

    // ── Page detection ────────────────────────────────────────────────────────
    const PAGE = (() => {
        const p = window.location.pathname;
        if (p === '/' || p === '') return 'home';
        if (p.startsWith('/library')) return 'library';
        if (p.startsWith('/pick')) return 'pick';
        if (p.startsWith('/tools')) return 'tools';
        return 'other';
    })();

    const PAGE_URLS = ['/', '/library', '/pick', '/tools'];

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
        active:       false,
        zone:         'nav',
        prevZone:     'content',
        prevRow:      null,
        prevCol:      null,
        row:          0,
        col:          0,
        savedCol:     0,
        subItem:      -1,
        modalRow:     0,
        modalCol:     0,
        focusedAppid: null,
    };

    // Expose focusedAppid so library.html's observeCards can re-apply the class
    window._inputMgr = {
        get focusedAppid() { return _state.focusedAppid; }
    };

    // Track whether a gamepad has ever been seen this session (persisted across page loads)
    let _gpEverSeen = sessionStorage.getItem('pd_gp_seen') === '1';

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
    const BTN_IDX = { a:0, b:1, x:2, y:3, lb:4, rb:5, up:12, down:13, left:14, right:15 };
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
        ].filter(Boolean);
    }

    // Home: returns array of { el, items[] } per navigable row.
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
            '.search-nav-bar button, .search-nav-bar select'
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

    // Tools: rows = .tool-card elements, plus individual blacklist entry rows when expanded
    function _toolRows() {
        const rows = [];
        for (const card of document.querySelectorAll('.tool-card')) {
            rows.push(card);
            // Blacklist entries become individual rows navigated with up/down
            const tbody = card.querySelector('#blacklist-tbody');
            if (tbody) {
                for (const tr of tbody.querySelectorAll('tr')) {
                    const btn = tr.querySelector('.bl-remove-btn');
                    if (btn && btn.offsetParent !== null && !btn.disabled) {
                        rows.push(tr);
                    }
                }
            }
        }
        return rows;
    }

    function _toolItems(rowEl) {
        // Blacklist entry row — just the remove button
        if (rowEl.tagName === 'TR') {
            return [...rowEl.querySelectorAll('.bl-remove-btn')]
                .filter(el => el.offsetParent !== null && !el.disabled);
        }
        return [...rowEl.querySelectorAll('button.nav-btn, a.nav-btn')].filter(el => {
            return el.offsetParent !== null && !el.disabled;
        });
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

    // Modal items: IDs of all modal overlays, checked in priority order
    const _MODAL_IDS = [
        'editModal', 'filterModal',
        'backup-modal', 'bg-modal', 'import-modal',
        'bulk-edit-modal', 'bulk-rescrape-modal', 'bulk-delete-modal',
        // Tools page expanding modals
        'pagywosg-modal', 'blacklist-modal', 'theme-modal',
        // Home page edit mode panels (use style.display)
        'shelf-edit-modal', 'dedup-panel', 'split-picker',
    ];

    // Returns buttons grouped into rows. If any element has data-modal-row, groups
    // by that attribute (sorted by row number). Otherwise returns all as a single row.
    // Includes buttons, nav/save links, and tagged selects. Groups by data-modal-row if present.
    function _modalGrid() {
        for (const id of _MODAL_IDS) {
            const el = document.getElementById(id);
            if (el && el.style.display !== 'none' && el.style.display !== '') {
                const candidates = [...el.querySelectorAll(
                    'button:not(:disabled), a.nav-btn, a.btn-save, select[data-modal-row]'
                )].filter(e => e.offsetParent !== null && !e.disabled
                         && e.textContent.trim() !== '✕' && e.textContent.trim() !== '×');
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

                    case 'tools': {
                        const rows = _toolRows();
                        if (!rows.length) break;
                        _state.row = Math.min(_state.row, rows.length - 1);
                        const items = _toolItems(rows[_state.row]);
                        if (!items.length) break;
                        _state.col = Math.min(_state.col, items.length - 1);
                        _applyFocus(items[_state.col]);
                        break;
                    }
                }
                break;
            }

            case 'modal': {
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

            default:
                _dbgNote(`syncFocus: unknown zone "${_state.zone}", resetting`);
                _state.zone = 'nav'; _state.col = 0;
                _syncFocus();
                break;
        }
    }

    // ── Activation ────────────────────────────────────────────────────────────
    function _activate() {
        if (_state.active) return;
        _state.active = true;
        _dbgNote('ACTIVATE');
        // Start on the active nav link for this page
        const navItems = _navItems();
        const activeLink = document.querySelector('.nav-links a.active');
        const startIdx = activeLink ? navItems.indexOf(activeLink) : 0;
        _state.zone = 'nav';
        _state.col  = Math.max(startIdx, 0);
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
        _dbgNote(`pushZone:${zone} (from ${_state.zone} r${_state.row}c${_state.col})`);
        _state.prevZone   = _state.zone;
        _state.prevRow    = _state.row;
        _state.prevCol    = _state.col;
        _state.zone       = zone;
        _state.col        = 0;
        _state.subItem    = -1;
        _state.modalRow   = 0;
        _state.modalCol   = 0;
    }

    function _popZone() {
        _dbgNote(`popZone → ${_state.prevZone} r${_state.prevRow}c${_state.prevCol}`);
        _state.zone    = _state.prevZone;
        _state.row     = _state.prevRow  ?? _state.row;
        _state.col     = _state.prevCol  ?? _state.col;
        _state.prevZone = 'content';
        _state.prevRow  = null;
        _state.prevCol  = null;
        _state.subItem  = -1;
    }

    // ── Direction handlers ────────────────────────────────────────────────────

    function _handleUp() {
        switch (_state.zone) {

            case 'modal': {
                const mgrid = _modalGrid();
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
                            _state.row = prev;
                            _state.col = Math.min(_state.savedCol, rows[prev].items.length - 1);
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

                    case 'tools': {
                        if (_state.row === 0) {
                            _state.zone = 'nav';
                            const navItems = _navItems();
                            const activeLink = document.querySelector('.nav-links a.active');
                            _state.col = activeLink ? navItems.indexOf(activeLink) : 0;
                        } else {
                            _state.row--;
                            const items = _toolItems(_toolRows()[_state.row]);
                            _state.col = Math.min(_state.savedCol, Math.max(items.length - 1, 0));
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
                            _state.row = next;
                            const row  = rows[_state.row];
                            _state.col = Math.min(_state.savedCol, row.items.length - 1);
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

                    case 'tools': {
                        const rows = _toolRows();
                        if (_state.row < rows.length - 1) {
                            _state.row++;
                            const items = _toolItems(rows[_state.row]);
                            _state.col = Math.min(_state.savedCol, Math.max(items.length - 1, 0));
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

                    case 'tools': {
                        if (_state.col > 0) _state.col--;
                        _state.savedCol = _state.col;
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

                    case 'tools': {
                        const rows  = _toolRows();
                        const items = _toolItems(rows[_state.row]);
                        if (_state.col < items.length - 1) _state.col++;
                        _state.savedCol = _state.col;
                        _syncFocus();
                        break;
                    }
                }
                break;
            }
        }
    }

    // ── Action handlers ───────────────────────────────────────────────────────

    function _handleA() {
        switch (_state.zone) {

            case 'modal': {
                const mgrid = _modalGrid();
                if (mgrid.length) {
                    mgrid[_state.modalRow]?.[_state.modalCol]?.click();
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
                                el.click();
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

                    case 'tools': {
                        const rows  = _toolRows();
                        const items = _toolItems(rows[_state.row]);
                        items[_state.col]?.click();
                        break;
                    }
                }
                break;
            }
        }
    }

    function _closeCtxMenu() {
        // hideMenu() is inside an IIFE and not globally accessible.
        // Dispatching Escape triggers the document keydown listener that calls it.
        document.querySelectorAll('.ctx-sub-open').forEach(el => el.classList.remove('ctx-sub-open'));
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    }

    function _closeAnyOpenModal() {
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
            if (el && el.style.display !== 'none') {
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
            _dbgNote(`B: closing editModal zone=${_state.zone}`);
            if (_state.zone === 'modal') _popZone();
            if (typeof closeModal === 'function') closeModal();
            _syncFocus();
            return;
        }

        const filterModal = document.getElementById('filterModal');
        if (filterModal && filterModal.style.display !== 'none') {
            _dbgNote(`B: closing filterModal zone=${_state.zone}`);
            if (_state.zone === 'modal') _popZone();
            if (typeof closeFilterModal === 'function') closeFilterModal();
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

    function _handleLB() {
        const idx = _currentPageIdx();
        if (idx > 0) window.location.href = PAGE_URLS[idx - 1];
    }

    function _handleRB() {
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
    const _IMMEDIATE_BTNS = new Set([BTN_IDX.lb, BTN_IDX.rb]);

    function _onButton(i, isRepeat) {
        const handler = _BTN_HANDLERS[i];
        if (!handler) return;
        if (!isRepeat) _dbgNote(`btn:${i}`);
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

        const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
        let gp = null;
        for (const g of gamepads) { if (g) { gp = g; break; } }
        if (!gp) return;

        if (!_gpEverSeen) {
            _dbgNote('gpEverSeen id=' + gp.id.slice(0, 30));
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
            _dbgNote(`modal:${id} display="${el.style.display}" nowV=${nowVisible} wasV=${_wasVisible} active=${_state.active} zone=${_state.zone}`);
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

        // Edit / filter modals (base.html — present on every page)
        _watchModal('editModal');
        _watchModal('filterModal');

        // Library bulk modals — full zone push/pop so focus enters and returns correctly
        _watchModal('bulk-edit-modal');
        _watchModal('bulk-rescrape-modal');
        _watchModal('bulk-delete-modal');

        // Tools modals — full zone push/pop so focus enters and returns correctly
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
