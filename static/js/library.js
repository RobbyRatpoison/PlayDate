    // ── All game data in one JS array — no per-card script tags ──
    const GAMES = window.GAMES;
    const OUTLINE_COLORS = window.OUTLINE_COLORS;
    const CURRENT_SORT = window.CURRENT_SORT;
    const CURRENT_ORDER = window.CURRENT_ORDER;

    // ── Artwork orientation + card size (restored from state) ────────────────
    const _imgV = Date.now(); // cache-buster: prevents stale 404s from browser negative cache
    const _imgVersions = new Map(); // appid (int) → per-game version after image change
    let _artOrientation = window._artOrientation;
    let _groupBy = window._groupBy;
    const _requireDblClick = !!window._requireDblClick;
    let _cardSizeTimeout = null;

    function _setCardSize(size) {
        // In horizontal mode, scale width so the card height matches the slider value
        const effectiveWidth = _artOrientation === 'horizontal'
            ? Math.round(size * 616 / 353)
            : size;
        document.documentElement.style.setProperty('--card-min-width', effectiveWidth + 'px');
        const btnRem = Math.min(3.5, Math.max(0.8, size * 0.009));
        document.documentElement.style.setProperty('--edit-btn-size', btnRem.toFixed(2) + 'rem');
    }

    (function _initGridPrefs() {
        const slider = document.getElementById('card-size-slider');
        const size   = window._initialCardHeight;
        _setCardSize(size);
        if (slider) {
            slider.value = size;
            const pct = (size - parseInt(slider.min)) / (parseInt(slider.max) - parseInt(slider.min)) * 100;
            slider.style.setProperty('--slider-pct', pct + '%');
        }
        if (_artOrientation === 'list') {
            document.getElementById('game-grid').style.display = 'none';
            const ll = document.getElementById('library-list-layout');
            if (ll) ll.style.display = 'flex';
            const lh = document.querySelector('.library-header');
            if (lh) lh.style.display = 'none';
            document.body.style.overflow = 'hidden';
            const ct = document.querySelector('.container');
            if (ct) { ct.style.overflow = 'hidden'; ct.style.paddingBottom = '0'; }
        }
    })();


    function toggleArtOrientation() {
        if (_artOrientation === 'list') return; // handled by VIEW modal
        _artOrientation = _artOrientation === 'vertical' ? 'horizontal' : 'vertical';
        const isHorizontal = _artOrientation === 'horizontal';
        document.querySelectorAll('.game-grid').forEach(g => g.classList.toggle('horizontal', isHorizontal));
        // Re-apply card size with new orientation's scaling
        _setCardSize(parseInt(document.getElementById('card-size-slider').value));
        // Rebuild cards with correct image paths
        CARD_HTML_CACHE.clear();
        document.querySelectorAll('.game-card').forEach(card => { card.innerHTML = ''; delete card.dataset.populated; });
        observeCards();
        savePreference({ artwork_orientation: _artOrientation });
    }

    function onCardSizeSlider(val) {
        const slider = document.getElementById('card-size-slider');
        _setCardSize(val);
        const pct = (val - parseInt(slider.min)) / (parseInt(slider.max) - parseInt(slider.min)) * 100;
        slider.style.setProperty('--slider-pct', pct + '%');
        clearTimeout(_cardSizeTimeout);
        _cardSizeTimeout = setTimeout(() => savePreference({ card_height: parseInt(val) }), 400);
    }

    // ── Current filter tree from server (may already contain a name condition) ──
    const _serverFilterTree = window._serverFilterTree;
    const _activeFilterName = window._activeFilterName;

    // Strip the search quick-filter (name LIKE) from the top level of the active tree,
    // unwrapping a single wrapped base group if that's all that remains.
    function _baseTree(tree) {
        if (!tree || !tree.items) return tree;
        const items = tree.items.filter(item =>
            !(item.type === 'condition' && item.column === 'name' && item.operator === 'LIKE')
        );
        if (items.length === 1 && items[0].type === 'group') return items[0];
        return { ...tree, items };
    }

    function buildSearchTree(query) {
        const base = _baseTree(_serverFilterTree);
        const hasBase = base && (base.custom_sql || (base.items && base.items.length > 0));
        let result;
        if (!query || !query.trim()) {
            result = base || { type: 'group', logic: 'AND', items: [] };
        } else {
            const nameNode = { type: 'condition', column: 'name', operator: 'LIKE', value: query };
            result = !hasBase
                ? { type: 'group', logic: 'AND', items: [nameNode] }
                : { type: 'group', logic: 'AND', items: [nameNode, base] };
        }
        if (_serverFilterTree?.pagywosg && !result.pagywosg) {
            result = { ...result,
                pagywosg:               _serverFilterTree.pagywosg,
                pagywosg_event:         _serverFilterTree.pagywosg_event,
                pagywosg_verified:      _serverFilterTree.pagywosg_verified,
                pagywosg_personal_cats: _serverFilterTree.pagywosg_personal_cats,
            };
        }
        return result;
    }

    // ── Live incremental search (client-side, no reload) ───────────────────
    // Narrows/widens the already-rendered card set on every keystroke by
    // toggling display — GAMES already holds every game matching the
    // committed server-side filter, so no network round trip is needed.
    let _liveSearchQuery = '';

    function applyLiveSearch(rawQuery) {
        _liveSearchQuery = (rawQuery || '').trim().toLowerCase();

        document.querySelectorAll('.game-card[data-appid], .list-row[data-appid]').forEach(el => {
            const game = _GAME_MAP.get(parseInt(el.dataset.appid, 10));
            const matches = !_liveSearchQuery || (game && (game.name || '').toLowerCase().includes(_liveSearchQuery));
            el.style.display = matches ? '' : 'none';
        });

        // Grid grouped mode: hide groups left with zero matches, update their counts
        document.querySelectorAll('#game-grid .group-section').forEach(section => {
            const cards = [...section.querySelectorAll('.game-card')];
            const visible = cards.filter(c => c.style.display !== 'none').length;
            section.style.display = visible === 0 ? 'none' : '';
            const countEl = section.querySelector('.group-count');
            if (countEl) countEl.textContent = visible;
        });

        // List grouped mode: hide headers whose rows are all filtered out
        document.querySelectorAll('#game-list .list-group-header').forEach(header => {
            let sib = header.nextElementSibling;
            let visible = false;
            while (sib && !sib.classList.contains('list-group-header')) {
                if (sib.classList.contains('list-row') && sib.style.display !== 'none') { visible = true; break; }
                sib = sib.nextElementSibling;
            }
            header.style.display = visible ? '' : 'none';
        });

        const msg = document.getElementById('search-empty-msg');
        if (msg) {
            const anyVisible = !_liveSearchQuery || [...document.querySelectorAll('.game-card[data-appid], .list-row[data-appid]')]
                .some(el => el.style.display !== 'none');
            msg.style.display = anyVisible ? 'none' : 'block';
        }
    }

    // Persists the search into state.json in the background as you type, so
    // it survives navigation/restart without an explicit commit step — and so
    // the FILTERS modal (which reads state.filter_tree) stays accurate. No
    // reload: the visible grid is already kept in sync live by applyLiveSearch.
    let _searchSyncTimeout = null;
    function _syncSearchToState(query) {
        clearTimeout(_searchSyncTimeout);
        _searchSyncTimeout = setTimeout(() => {
            sendStateUpdate({ filter_tree: buildSearchTree(query) }, false);
        }, 400);
    }

    function handleSearch(event, query) {
        if (event.key !== 'Enter') return;
        // Steam Deck's on-screen keyboard synthesizes a real Enter keyup when A
        // dismisses/confirms it — without this guard, pressing A to focus the
        // search box (via gamepad) immediately looks like the user hit Enter
        // and dismisses the keyboard before they've typed anything.
        if (window._inputMgr && window._inputMgr.justGamepadFocusedInput()) return;
        // Flush immediately rather than waiting out the debounce, and dismiss
        // the (on-screen or gamepad) keyboard now that the user is done typing.
        clearTimeout(_searchSyncTimeout);
        sendStateUpdate({ filter_tree: buildSearchTree(query) }, false);
        event.target.blur();
    }

    const _sortDefaultOrder = {
        name:                'ASC',
        playtime_forever:    'DESC',
        release_date:        'DESC',
        last_played:         'DESC',
        date_added:          'DESC',
        review_percentage:   'DESC',
        weighted_percentage: 'DESC',
        hltb_min:            'ASC',
        total_reviews:       'DESC',
    };
    function updateSort(column) {
        const order = _sortDefaultOrder[column] ?? 'ASC';
        sendStateUpdate({ sort: column, order });
    }

    async function clearAndReload() {
        const emptyTree = { type: 'group', logic: 'AND', items: [] };
        await sendStateUpdate({ filter_tree: emptyTree, hidden_platforms: [..._hiddenPlatforms] });
    }

    const _hiddenPlatforms = window._hiddenPlatforms;

    function togglePlatform(platform) {
        if (_hiddenPlatforms.has(platform)) _hiddenPlatforms.delete(platform);
        else _hiddenPlatforms.add(platform);
        sendStateUpdate({ hidden_platforms: [..._hiddenPlatforms] });
    }

    function toggleOrder() {
        const currentOrder = CURRENT_ORDER;
        sendStateUpdate({ order: currentOrder === 'ASC' ? 'DESC' : 'ASC' });
    }

    const filterConfig = {};

    // ── VIRTUAL GRID ──────────────────────────────────────────────
    // Cards are populated when they scroll into a generous viewport margin
    // and unloaded (back to sized placeholder) when they scroll far away.
    // This keeps DOM size bounded regardless of library size.
    //
    // _GAME_MAP provides O(1) appid → game lookups replacing the previous
    // O(n) GAMES.find() calls inside the hot intersection callback path.

    const _GAME_MAP = new Map(GAMES.map(g => [g.appid, g]));
    const CARD_HTML_CACHE = new Map(); // appid → innerHTML string

    function cardInnerHTML(game) {
        if (CARD_HTML_CACHE.has(game.appid)) return CARD_HTML_CACHE.get(game.appid);
        const escaped  = (game.name || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        const isHoriz  = _artOrientation === 'horizontal';
        const v        = _imgVersions.has(game.appid) ? _imgVersions.get(game.appid) : _imgV;
        const src      = isHoriz
            ? `/static/img/library/horizontal/${game.appid}.jpg?v=${v}`
            : `/static/img/library/vertical/${game.appid}.jpg?v=${v}`;
        const fallback = isHoriz
            ? `/static/img/library/vertical/${game.appid}.jpg?v=${v}`
            : '';
        // src is intentionally omitted here — set after a scroll-idle delay
        // by scheduleImgLoad() so fast-scrolling cards never trigger a fetch.
        // Click vs double-click is mutually exclusive (opt-in via View settings,
        // off by default) -- wiring both would fire launchGame twice per click
        // when off, or three times on a real double-click.
        const clickAttr = _requireDblClick
            ? `ondblclick="launchGame(${game.appid})"`
            : `onclick="launchGame(${game.appid})"`;
        const html = `
            <div class="capsule-container" ${clickAttr} style="cursor:pointer;">
                <img data-src="${src}"
                    data-fallback="${fallback}"
                    alt=""
                    class="game-capsule"
                    decoding="async">
                <div class="no-art-name">
                    <span>${escHtml(game.name || '')}</span>
                    <span class="no-art-platform">${escHtml((window._PLAT_LABELS && window._PLAT_LABELS[game.platform]) || game.platform || '')}</span>
                </div>
                ${renderEditButton(game.appid, window.EDIT_BUTTON)}
                ${renderCardBadges(game, window.CARD_BADGES)}
            </div>`;
        CARD_HTML_CACHE.set(game.appid, html);
        return html;
    }

    // ── Fast-scroll position preview (gamepad right stick) ───────────────────
    // Shown/updated/hidden by input.js's right-stick scroll handling — the
    // logic lives here since only this page has the sorted GAMES data needed
    // to know what a given scroll position actually represents.
    let _scrollPreviewHideTimer   = null;
    let _scrollPreviewRandomTimer = null;
    let _scrollPreviewLastUpdate  = 0;

    function _scrollPreviewTopGame() {
        const cards = document.querySelectorAll('.game-card[data-appid], .list-row[data-appid]');
        for (const card of cards) {
            if (card.getBoundingClientRect().bottom > 80) {
                return _GAME_MAP.get(parseInt(card.dataset.appid)) || null;
            }
        }
        return null;
    }

    const _SCROLL_PREVIEW_GLYPHS = '!@#$%^&*?<>{}[]~+=01XYZ¿∞§';
    function _scrollPreviewRandomGlyph() {
        let s = '';
        for (let i = 0; i < 2; i++) {
            s += _SCROLL_PREVIEW_GLYPHS[Math.floor(Math.random() * _SCROLL_PREVIEW_GLYPHS.length)];
        }
        return s;
    }

    function _scrollPreviewText() {
        const game = _scrollPreviewTopGame();
        if (!game) return '';
        switch (CURRENT_SORT) {
            case 'name': {
                const ch = (game.name || '').trim().charAt(0).toUpperCase();
                return /[A-Z0-9]/.test(ch) ? ch : '#';
            }
            case 'release_date':
            case 'last_played':
            case 'date_added': {
                // library.py already converts these to 'YYYY-MM-DD' strings
                // before sending to the browser (ts_to_date()) — not raw
                // Unix timestamps, unlike the DB columns themselves.
                const ts = game[CURRENT_SORT];
                if (!ts) return '—';
                const d = new Date(ts);
                if (isNaN(d.getTime())) return '—';
                return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
            }
            case 'playtime_forever':
                return fmtHours(game.playtime_forever);
            case 'hltb_min': {
                // Not a real column — library.py's ORDER BY computes this on
                // the fly from the three HLTB times (main/extras/completionist),
                // MIN for ascending ("shortest") and MAX for descending
                // ("most content"), treating 0/missing as no data. Mirror that
                // exact logic here since the browser only has the raw fields.
                const real = [game.hltb_main, game.hltb_extras, game.hltb_completionist]
                    .filter(v => v > 0);
                if (!real.length) return '—';
                const mins = CURRENT_ORDER === 'DESC' ? Math.max(...real) : Math.min(...real);
                return fmtHours(mins);
            }
            case 'review_percentage':
            case 'weighted_percentage': {
                const pct = game[CURRENT_SORT];
                return (pct || pct === 0) ? `${pct}%` : '—';
            }
            case 'total_reviews': {
                const n = game.total_reviews || 0;
                return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
            }
            default:
                return '';
        }
    }

    function _scrollPreviewShow() {
        const el = document.getElementById('scroll-preview');
        if (!el) return;
        clearTimeout(_scrollPreviewHideTimer);
        el.classList.add('visible');
        if (CURRENT_SORT === 'random' && !_scrollPreviewRandomTimer) {
            // Cycles on its own clock rather than tracking real position — an
            // honest wink that random order has no "position" to preview.
            _scrollPreviewRandomTimer = setInterval(() => {
                el.textContent = _scrollPreviewRandomGlyph();
            }, 80);
        }
    }

    function _scrollPreviewUpdate() {
        if (CURRENT_SORT === 'random') return; // cycles on its own timer instead
        const el = document.getElementById('scroll-preview');
        if (!el) return;
        const now = Date.now();
        if (now - _scrollPreviewLastUpdate < 120) return; // throttle DOM scans on huge libraries
        _scrollPreviewLastUpdate = now;
        const text = _scrollPreviewText();
        if (text) el.textContent = text;
    }

    function _scrollPreviewHide() {
        const el = document.getElementById('scroll-preview');
        if (!el) return;
        clearTimeout(_scrollPreviewHideTimer);
        _scrollPreviewHideTimer = setTimeout(() => {
            el.classList.remove('visible');
            if (_scrollPreviewRandomTimer) {
                clearInterval(_scrollPreviewRandomTimer);
                _scrollPreviewRandomTimer = null;
            }
        }, 500);
    }

    // Used while the stick is still held at a scroll boundary — _scrollPreviewHide()'s
    // 500ms delayed fade is meant for a one-time call on release, but input.js calls
    // the boundary check every frame, which kept re-scheduling that timer indefinitely
    // (clearTimeout + setTimeout every ~16ms) so it never actually fired.
    function _scrollPreviewHideImmediate() {
        const el = document.getElementById('scroll-preview');
        if (!el) return;
        clearTimeout(_scrollPreviewHideTimer);
        el.classList.remove('visible');
        if (_scrollPreviewRandomTimer) {
            clearInterval(_scrollPreviewRandomTimer);
            _scrollPreviewRandomTimer = null;
        }
    }

    window._scrollPreviewShow          = _scrollPreviewShow;
    window._scrollPreviewUpdate        = _scrollPreviewUpdate;
    window._scrollPreviewHideImmediate = _scrollPreviewHideImmediate;
    window._scrollPreviewHide          = _scrollPreviewHide;

    // On initial page load images are loaded immediately; once the user scrolls,
    // a 100ms delay is applied so cards that pass through during fast scroll
    // never trigger a network fetch or decode.
    let _initialLoad = true;
    window.addEventListener('scroll', () => { _initialLoad = false; }, { once: true, passive: true });

    function _applyArtClasses(img, container) {
        if (!container) return;
        container.classList.remove('no-art');
        container.classList.add('has-art');
        applyBlurArt(img, container, _artOrientation === 'horizontal' ? (616 / 353) : (2 / 3));
    }

    function _doImgLoad(card) {
        const img = card.querySelector('img[data-src]');
        if (!img) return;
        const src      = img.dataset.src;
        const fallback = img.dataset.fallback;
        const container = card.querySelector('.capsule-container');
        const markNoArt = () => {
            if (container) { container.classList.add('no-art'); container.classList.remove('has-art'); }
        };
        img.onload = () => { img.onload = null; _applyArtClasses(img, container); };
        if (fallback) {
            img.onerror = () => {
                img.onerror = () => { img.onerror = null; markNoArt(); };
                img.src = fallback;
                if (container) container.style.backgroundImage = `url('${fallback}')`;
            };
        } else {
            img.onerror = () => { img.onerror = null; markNoArt(); };
        }
        img.src = src;
        if (container) container.style.backgroundImage = `url('${src}')`;
    }

    function scheduleImgLoad(card) {
        clearTimeout(card._imgTimer);
        if (card._imgIdleId) { cancelIdleCallback(card._imgIdleId); card._imgIdleId = null; }
        if (_initialLoad) { _doImgLoad(card); return; }
        if (window.requestIdleCallback) {
            card._imgIdleId = requestIdleCallback(
                () => { card._imgIdleId = null; _doImgLoad(card); },
                { timeout: 500 }
            );
        } else {
            card._imgTimer = setTimeout(() => _doImgLoad(card), 150);
        }
    }

    function openEditModalById(appid) {
        const game = _GAME_MAP.get(appid);
        if (game) openEditModal(game);
    }

    // ── Group-by helpers ─────────────────────────────────────────────────────

    const _GROUP_FIXED_ORDER = {
        installed: ['installed', 'not_installed'],
        completion_status: ['Never Played', 'Unfinished', 'Beaten', 'Completed', "Won't Play"],
        platform: Object.keys(window._PLAT_LABELS),
    };
    const _GROUP_PLAT_LABELS = window._PLAT_LABELS;
    const _GROUP_BY_LABELS = {
        installed: 'Installed', completion_status: 'Completion', release_date: 'Release Year',
        date_added: 'Year Added', review_percentage: 'Review Score',
        weighted_percentage: 'Weighted Score', platform: 'Platform',
    };

    function _getGroupKey(game) {
        switch (_groupBy) {
            case 'installed':         return game.installed ? 'installed' : 'not_installed';
            case 'completion_status': return game.completion_status || 'Never Played';
            case 'release_date':
            case 'date_added':        return game[_groupBy] ? String(game[_groupBy]).substring(0, 4) : null;
            case 'review_percentage':
            case 'weighted_percentage': {
                const s = game[_groupBy];
                if (s == null) return null;
                return Math.floor(Math.min(Number(s), 99) / 10) * 10;
            }
            case 'platform':          return game.platform || 'steam';
            default:                  return null;
        }
    }

    function _getGroupLabel(key) {
        switch (_groupBy) {
            case 'installed':   return key === 'installed' ? 'Installed' : 'Not Installed';
            case 'completion_status': return key;
            case 'release_date':
            case 'date_added':  return key ?? 'Unknown';
            case 'review_percentage':
            case 'weighted_percentage': return key == null ? 'Unknown' : key + 's';
            case 'platform':    return _GROUP_PLAT_LABELS[key] ?? key;
            default:            return String(key);
        }
    }

    function _sortGroupKeys(rawKeys) {
        const fixedOrder = _GROUP_FIXED_ORDER[_groupBy];
        if (fixedOrder) {
            const known   = fixedOrder.filter(k => rawKeys.includes(k));
            const unknown = rawKeys.filter(k => !fixedOrder.includes(k));
            return [...known, ...unknown];
        }
        // Date/score fields: numeric DESC, unknown (null) last
        const nulls = rawKeys.filter(k => k === null);
        const rest  = rawKeys.filter(k => k !== null).sort((a, b) => Number(b) - Number(a));
        return [...rest, ...nulls];
    }

    const _collapsedGroups = new Set();

    function _toggleGroupCollapse(strKey) {
        const section  = document.querySelector(`.group-section[data-group-key="${CSS.escape(strKey)}"]`);
        if (!section) return;
        const inner    = section.querySelector('.group-inner-grid');
        const chevron  = section.querySelector('.group-chevron');
        if (_collapsedGroups.has(strKey)) {
            _collapsedGroups.delete(strKey);
            inner.style.display = '';
            if (chevron) chevron.textContent = '▾';
        } else {
            _collapsedGroups.add(strKey);
            inner.style.display = 'none';
            if (chevron) chevron.textContent = '▸';
        }
    }

    function _makeCard(game) {
        const card = document.createElement('div');
        card.className    = 'game-card';
        card.id           = `card-${game.appid}`;
        card.dataset.appid    = game.appid;
        card.dataset.platform = game.platform || 'steam';
        card.dataset.installed = game.installed ? '1' : '0';
        const outlineColor = OUTLINE_COLORS[String(game.appid)];
        if (outlineColor) card.style.setProperty('--outline-color', outlineColor);
        return card;
    }

    function _updateGroupByHeaderLabel() {
        const el = document.getElementById('group-by-label');
        if (!el) return;
        if (_groupBy) {
            el.textContent = ' \u00b7 Grouped by ' + (_GROUP_BY_LABELS[_groupBy] ?? _groupBy);
            el.style.display = '';
        } else {
            el.style.display = 'none';
        }
    }

    function buildGrid() {
        const grid = document.getElementById('game-grid');
        grid.innerHTML = '';

        if (!_groupBy) {
            grid.className = 'game-grid' + (_artOrientation === 'horizontal' ? ' horizontal' : '');
            const fragment = document.createDocumentFragment();
            GAMES.forEach(game => fragment.appendChild(_makeCard(game)));
            grid.appendChild(fragment);
        } else {
            grid.className = 'grouped-container';

            // Group games by key (preserving server sort order within each group)
            const groupMap = new Map();
            for (const game of GAMES) {
                const rawKey = _getGroupKey(game);
                const strKey = String(rawKey ?? '__null__');
                if (!groupMap.has(strKey)) groupMap.set(strKey, { rawKey, games: [] });
                groupMap.get(strKey).games.push(game);
            }

            const rawKeys    = [...new Set([...groupMap.values()].map(g => g.rawKey))];
            const sortedKeys = _sortGroupKeys(rawKeys);
            const fragment   = document.createDocumentFragment();

            for (const rawKey of sortedKeys) {
                const strKey = String(rawKey ?? '__null__');
                const group  = groupMap.get(strKey);
                if (!group || group.games.length === 0) continue;

                const section   = document.createElement('div');
                section.className = 'group-section';
                section.dataset.groupKey = strKey;

                const labelEl   = document.createElement('div');
                labelEl.className = 'group-label';
                labelEl.innerHTML =
                    `<span class="group-chevron">▾</span>` +
                    `<span class="group-name">${_getGroupLabel(rawKey)}</span>` +
                    `<span class="group-count">${group.games.length}</span>`;
                labelEl.addEventListener('click', () => _toggleGroupCollapse(strKey));

                const innerGrid = document.createElement('div');
                innerGrid.className = 'game-grid group-inner-grid' + (_artOrientation === 'horizontal' ? ' horizontal' : '');
                group.games.forEach(game => innerGrid.appendChild(_makeCard(game)));

                if (_collapsedGroups.has(strKey)) {
                    innerGrid.style.display = 'none';
                    labelEl.querySelector('.group-chevron').textContent = '▸';
                }

                section.appendChild(labelEl);
                section.appendChild(innerGrid);
                fragment.appendChild(section);
            }
            grid.appendChild(fragment);
        }

        observeCards();
        if (_liveSearchQuery) applyLiveSearch(_liveSearchQuery);
    }

    let _observer = null;
    function observeCards() {
        if (_observer) _observer.disconnect();
        _observer = new IntersectionObserver((entries) => {
            // Batch all DOM mutations into a single rAF to avoid a burst of
            // layout recalculations when many cards enter/exit during fast scroll.
            requestAnimationFrame(() => {
                entries.forEach(entry => {
                    const card  = entry.target;
                    const appid = parseInt(card.dataset.appid);

                    if (entry.isIntersecting) {
                        if (!card.dataset.populated) {
                            // First entry: build the card HTML once and keep it forever.
                            const game = _GAME_MAP.get(appid);
                            if (game) {
                                card.innerHTML = cardInnerHTML(game);
                                card.dataset.populated = '1';
                                if (_selectMode) card.addEventListener('click', onCardClick);
                                if (_selectedIds.has(appid)) card.classList.add('selected');
                                if (window._inputMgr?.onCardPopulated) {
                                    window._inputMgr.onCardPopulated(card, appid);
                                }
                            }
                        }
                        // Reload image — handles first entry and re-entry after img was cleared.
                        scheduleImgLoad(card);
                    } else {
                        if (card.dataset.populated) {
                            // Keep the HTML; only clear img.src so the browser can release
                            // the decoded image buffer without destroying the DOM structure.
                            clearTimeout(card._imgTimer);
                            if (card._imgIdleId) { cancelIdleCallback(card._imgIdleId); card._imgIdleId = null; }
                            const img = card.querySelector('img');
                            if (img) img.src = '';
                            const con = card.querySelector('.capsule-container');
                            if (con) con.classList.remove('has-art');
                        }
                    }
                });
            });
        }, {
            rootMargin: '2400px',
            threshold: 0
        });
        document.querySelectorAll('.game-card').forEach(c => _observer.observe(c));
    }

    // Build on load — deferred so the browser can paint the page chrome first
    document.addEventListener('DOMContentLoaded', function() {
        // GAMES always covers the full active filter now (search is no longer
        // baked into the server-side SQL) — restore a previously-committed
        // search's narrowed view client-side once cards exist. buildGrid()/
        // buildListView() reapply _liveSearchQuery themselves once it's set.
        const _initialSearchVal = document.getElementById('library-search')?.value || '';
        if (_initialSearchVal) applyLiveSearch(_initialSearchVal);

        if (_artOrientation === 'list') {
            _adjustListHeight();
            _initListDivider();
            buildListView();
            window.addEventListener('resize', _adjustListHeight);
        } else {
            requestAnimationFrame(() => requestAnimationFrame(() => buildGrid()));
        }

    });

    // ── Live populate updates ─────────────────────────────────────────────────

    // Add placeholder cards for games just inserted by the populate phase 1
    document.addEventListener('populate:new_cards', (e) => {
        const grid = document.getElementById('game-grid');
        if (!grid) return;

        // Build game objects first, skip duplicates
        const newGames = [];
        for (const g of e.detail) {
            if (_GAME_MAP.has(g.appid)) continue;
            const gameObj = {
                appid:             g.appid,
                name:              g.name              || '',
                completion_status: g.completion_status || 'Never Played',
                playtime_forever:  g.playtime_forever  || 0,
                platform:          g.platform          || 'steam',
                installed:         g.installed         || 0,
            };
            GAMES.push(gameObj);
            _GAME_MAP.set(g.appid, gameObj);
            newGames.push(gameObj);
        }
        if (!newGames.length) return;

        if (!_groupBy) {
            const fragment = document.createDocumentFragment();
            newGames.forEach(gameObj => fragment.appendChild(_makeCard(gameObj)));
            grid.appendChild(fragment);
        } else {
            // Slot each new card into its group section; rebuild if a new group appears
            const byKey = new Map();
            for (const gameObj of newGames) {
                const rawKey = _getGroupKey(gameObj);
                const strKey = String(rawKey ?? '__null__');
                if (!byKey.has(strKey)) byKey.set(strKey, { rawKey, games: [] });
                byKey.get(strKey).games.push(gameObj);
            }
            let needsRebuild = false;
            for (const [strKey, { games }] of byKey) {
                const section = grid.querySelector(`.group-section[data-group-key="${CSS.escape(strKey)}"]`);
                if (!section) { needsRebuild = true; break; }
                const innerGrid = section.querySelector('.group-inner-grid');
                const fragment  = document.createDocumentFragment();
                games.forEach(gameObj => fragment.appendChild(_makeCard(gameObj)));
                innerGrid.appendChild(fragment);
            }
            if (needsRebuild) { buildGrid(); return; }
        }

        // Observe newly added cards
        document.querySelectorAll('.game-card:not([data-observed])').forEach(c => {
            c.dataset.observed = '1';
            _observer.observe(c);
        });
    });

    // Patch cards whose metadata just completed
    document.addEventListener('populate:meta_complete', async (e) => {
        for (const appid of e.detail) {
            try {
                const res  = await fetch(`/api/game/${appid}`);
                const data = await res.json();
                if (data.status === 'success') _patchGameCard(data.game);
            } catch (_) {}
        }
    });

    // Bust image cache for cards whose art just completed
    document.addEventListener('populate:art_complete', (e) => {
        const orient = (typeof _artOrientation !== 'undefined' && _artOrientation === 'horizontal')
            ? 'horizontal' : 'vertical';
        for (const appid of e.detail) {
            if (typeof CARD_HTML_CACHE !== 'undefined') CARD_HTML_CACHE.delete(appid);
            const card = document.querySelector(`.game-card[data-appid="${appid}"]`);
            if (!card || !card.dataset.populated) continue;
            const newSrc = `/static/img/library/${orient}/${appid}.jpg?v=${Date.now()}`;
            const img = card.querySelector('.game-capsule');
            const container = card.querySelector('.capsule-container');
            if (img) {
                img.onload = () => { img.onload = null; _applyArtClasses(img, container); };
                img.src = newSrc;
            }
            if (container) container.style.backgroundImage = `url('${newSrc}')`;
        }
    });

    // Remove cards that got blacklisted during populate
    document.addEventListener('populate:blacklist', (e) => {
        for (const appid of e.detail) {
            _GAME_MAP.delete(appid);
            const idx = GAMES.findIndex(g => g.appid === appid);
            if (idx !== -1) GAMES.splice(idx, 1);
            const card = document.getElementById(`card-${appid}`);
            if (card) card.remove();
        }
    });

    // Post visible appids to the priority endpoint every 3 seconds during populate
    let _priorityInterval = null;
    document.addEventListener('populate:started', () => {
        _priorityInterval = setInterval(() => {
            const visible = [];
            document.querySelectorAll('.game-card[data-populated]').forEach(c => {
                visible.push(parseInt(c.dataset.appid));
            });
            if (visible.length > 0) {
                fetch('/api/populate-priority', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ appids: visible }),
                }).catch(() => {});
            }
        }, 3000);
    });
    document.addEventListener('populate:stopped', () => {
        clearInterval(_priorityInterval);
        _priorityInterval = null;
    });

    // ── HOVER DELEGATION ──────────────────────────────────────────
    // - Throttled to one update per animation frame via rAF so rapid
    //   mouse movement can't queue more work than the browser can render.
    // - will-change:transform applied only to the active card (max 1
    //   compositing layer at a time) rather than all populated cards.
    // - Exit is instant (no transition) to prevent stacking scale-down
    //   animations as the mouse sweeps across many cards.
    let _hoveredCard = null;
    let _hoverRafPending = false;
    let _hoverTarget = null;

    function _applyHover() {
        _hoverRafPending = false;
        if (window._inputMgr?.active) return;
        const card = _hoverTarget;
        if (card === _hoveredCard) return;
        if (_hoveredCard) _hoveredCard.classList.remove('hovered');
        _hoveredCard = card;
        if (card) card.classList.add('hovered');
    }

    function _clearHover() {
        if (_hoveredCard) { _hoveredCard.classList.remove('hovered'); _hoveredCard = null; }
        _hoverTarget = null;
    }

    const _grid = document.getElementById('game-grid');
    _grid.addEventListener('mousemove', e => {
        _hoverTarget = e.target.closest('.game-card[data-populated]');
        if (!_hoverRafPending) {
            _hoverRafPending = true;
            requestAnimationFrame(_applyHover);
        }
    });
    _grid.addEventListener('mouseleave', () => {
        _hoverTarget = null;
        if (!_hoverRafPending) {
            _hoverRafPending = true;
            requestAnimationFrame(_applyHover);
        }
    });

    window._clearGameCardHover = _clearHover;

// ── SELECT MODE ──────────────────────────────────────────────────
let _selectMode = false;
let _selectedIds = new Set();

function _updateSelectBadge() {
    const badge = document.getElementById('select-badge');
    const count = document.getElementById('select-badge-count');
    const n = _selectedIds.size;
    badge.style.display = _selectMode ? '' : 'none';
    count.textContent = n;
}

function _enterSelectMode() {
    if (_selectMode) return;
    _selectMode = true;
    document.body.classList.add('select-mode');
    _updateSelectBadge();
    document.querySelectorAll('.game-card[data-populated]').forEach(card => {
        card.addEventListener('click', onCardClick);
    });
    // Clear the active list row highlight so it doesn't look pre-selected
    document.querySelectorAll('.list-row.selected').forEach(r => r.classList.remove('selected'));
}

function _filteredAppids() {
    return Array.from(document.querySelectorAll('.game-card[data-appid], .list-row[data-appid]'))
               .map(c => parseInt(c.dataset.appid));
}

function _exitSelectMode() {
    if (!_selectMode) return;
    _selectMode = false;
    document.body.classList.remove('select-mode');
    _selectedIds.clear();
    document.querySelectorAll('.game-card.selected, .list-row.selected').forEach(c => c.classList.remove('selected'));
    _updateSelectBadge();
    document.querySelectorAll('.game-card[data-populated]').forEach(card => {
        card.removeEventListener('click', onCardClick);
    });
}

function toggleSelectMode() {
    if (_selectMode) _exitSelectMode(); else _enterSelectMode();
}

function onCardClick(e) {
    const card = e.currentTarget;
    const appid = parseInt(card.id.replace('card-', ''));
    if (_selectedIds.has(appid)) {
        _selectedIds.delete(appid);
        card.classList.remove('selected');
    } else {
        _selectedIds.add(appid);
        card.classList.add('selected');
    }
    _updateSelectBadge();
}

// ── BULK EDIT ──────────────────────────────────────────────────
const LIST_COLUMNS    = new Set(['tags', 'groups', 'genres', 'categories']);
const STATUS_OPTIONS  = ['Never Played', 'Unfinished', 'Beaten', 'Completed', "Won't Play"];
const BULK_PILL_SUGGESTIONS = window.BULK_PILL_SUGGESTIONS;
const _BULK_FILTER_TREE = window._BULK_FILTER_TREE;
const BULK_GAME_COUNT = window.BULK_GAME_COUNT;

const ALL_GAME_COUNT = window.ALL_GAME_COUNT;

let _currentBulkTab     = 'edit';
let _bulkOpPollInterval = null;

// ── Tab management ──────────────────────────────────────────────────────────
function switchBulkTab(tab) {
    document.querySelectorAll('.bulk-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('[id^="bulk-pane-"]').forEach(p => p.style.display = 'none');
    document.getElementById('bulk-tab-btn-' + tab).classList.add('active');
    document.getElementById('bulk-pane-' + tab).style.display = '';
    _currentBulkTab = tab;
}

function openBulkEditModal(tab = 'edit') {
    const hasSelection = _selectedIds.size > 0;
    const defaultScope = hasSelection ? 'selected' : 'filtered';

    // Set scope radios for each tab
    ['scope', 'brs-scope', 'bdi-scope'].forEach(prefix => {
        const el = document.getElementById(prefix + '-' + defaultScope);
        if (el) el.checked = true;
    });
    onBulkScopeChange();
    onBulkRescrapeScopeChange();
    onBulkDateImportScopeChange();

    // Reset edit tab
    document.getElementById('bulk-status').textContent = '';
    document.getElementById('bulk-status').className = '';
    document.getElementById('bulk-value-text').value = '';
    onBulkColumnChange();

    // Reset rescrape tab (only if not running)
    if (!_bulkOpPollInterval) {
        document.getElementById('brs-status').textContent = '';
        document.getElementById('brs-status').className = '';
        document.getElementById('brs-progress').style.display = 'none';
        document.getElementById('brs-stop-btn').style.display = 'none';
        document.getElementById('brs-start-meta-btn').disabled = false;
        document.getElementById('brs-start-art-btn').disabled  = false;
        const _pdbBtn = document.getElementById('brs-start-protondb-btn');
        if (_pdbBtn) _pdbBtn.disabled = false;
    }

    // Reset date tab (only if not running)
    if (!_bdiPollInterval) {
        document.getElementById('bdi-status').textContent = '';
        document.getElementById('bdi-status').className = '';
        document.getElementById('bdi-progress').style.display = 'none';
        document.getElementById('bdi-stop-btn').style.display = 'none';
        document.getElementById('bdi-start-btn').disabled = false;
    }

    switchBulkTab(tab);
    document.getElementById('bulk-edit-modal').style.display = 'flex';
}

function closeBulkEditModal() {
    document.getElementById('bulk-edit-modal').style.display = 'none';
}

// Thin wrappers so old call sites still work
function openBulkRescrapeModal()   { openBulkEditModal('rescrape'); }
function openBulkArtScrapeModal()  { openBulkEditModal('rescrape'); }
function openBulkDateImportModal() { openBulkEditModal('dates'); }

// ── EDIT TAB ─────────────────────────────────────────────────────────────────
function _buildBulkScopePayload() {
    const scope = document.querySelector('input[name="bulk-scope"]:checked')?.value || 'filtered';
    const payload = {};
    if (scope === 'selected') {
        payload.appids = Array.from(_selectedIds);
    } else if (scope === 'filtered') {
        payload.filter_tree = _BULK_FILTER_TREE;
        if (_hiddenPlatforms.size) payload.hidden_platforms = Array.from(_hiddenPlatforms);
    }
    return payload;
}

let _removeSuggestionsAbort = null;

async function _loadRemoveSuggestions() {
    const col = document.getElementById('bulk-column').value;
    if (!LIST_COLUMNS.has(col)) return;
    if (_removeSuggestionsAbort) _removeSuggestionsAbort.abort();
    _removeSuggestionsAbort = new AbortController();
    try {
        const res = await fetch('/api/bulk-edit/distinct-values', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ column: col, ..._buildBulkScopePayload() }),
            signal: _removeSuggestionsAbort.signal
        });
        const data = await res.json();
        if (data.values) PILL_SUGGESTIONS['bulk-pills-hidden'] = data.values;
    } catch (e) {
        if (e.name !== 'AbortError')
            PILL_SUGGESTIONS['bulk-pills-hidden'] = BULK_PILL_SUGGESTIONS[col] || [];
    }
}

function onBulkScopeChange() {
    const scope = document.querySelector('input[name="bulk-scope"]:checked')?.value;
    if (!scope) return;
    if (scope === 'selected' && _selectedIds.size === 0) {
        document.getElementById('scope-filtered').checked = true;
        closeBulkEditModal();
        _enterSelectMode();
        return;
    }
    document.getElementById('bulk-all-info').style.display      = scope === 'all'      ? 'block' : 'none';
    document.getElementById('bulk-filtered-info').style.display = scope === 'filtered' ? 'block' : 'none';
    document.getElementById('bulk-selected-info').style.display = scope === 'selected' ? 'block' : 'none';
    if (scope === 'all') {
        document.getElementById('bulk-all-info').textContent = `${ALL_GAME_COUNT} game${ALL_GAME_COUNT !== 1 ? 's' : ''} in library`;
        _exitSelectMode();
    } else if (scope === 'filtered') {
        document.getElementById('bulk-filtered-info').textContent = `${BULK_GAME_COUNT} game${BULK_GAME_COUNT !== 1 ? 's' : ''} currently shown`;
        _exitSelectMode();
    } else {
        document.getElementById('bulk-selected-info').textContent = `${_selectedIds.size} game${_selectedIds.size !== 1 ? 's' : ''} selected`;
    }
    onBulkModeChange();
    const _col = document.getElementById('bulk-column').value;
    if (document.getElementById('bulk-mode').value === 'remove' && LIST_COLUMNS.has(_col))
        _loadRemoveSuggestions();
}

function onBulkColumnChange() {
    const col       = document.getElementById('bulk-column').value;
    const modeSelect = document.getElementById('bulk-mode');
    const appendOpt  = modeSelect._getOption('append');
    const removeOpt  = modeSelect._getOption('remove');
    const isList     = LIST_COLUMNS.has(col);
    const isStatus   = col === 'completion_status';
    const isPills    = isList;

    appendOpt.disabled = !isList;
    removeOpt.disabled = !isList;

    if (!isList && (modeSelect.value === 'append' || modeSelect.value === 'remove')) {
        modeSelect.value = 'replace';
    }

    // Swap the value input widget
    document.getElementById('bulk-value-text-wrap').style.display   = (!isStatus && !isPills) ? '' : 'none';
    document.getElementById('bulk-value-status-wrap').style.display  = isStatus  ? '' : 'none';
    document.getElementById('bulk-value-pills-wrap').style.display   = isPills   ? '' : 'none';

    if (isPills) {
        PILL_SUGGESTIONS['bulk-pills-hidden'] = BULK_PILL_SUGGESTIONS[col] || [];
        _pillSync('bulk-pills-hidden', []);
        _pillRender('bulk-pills-hidden', 'bulk-pills-box');
        if (modeSelect.value === 'remove') _loadRemoveSuggestions();
    }

    const isDate = ['date_added', 'release_date', 'last_played'].includes(col);
    document.getElementById('bulk-value-text').placeholder = isDate ? 'YYYY-MM-DD' : 'Enter value…';

    onBulkModeChange();
}

function onBulkModeChange() {
    const mode = document.getElementById('bulk-mode').value;
    const col = document.getElementById('bulk-column').value;
    const hint = document.getElementById('bulk-mode-hint');
    const valHint = document.getElementById('bulk-value-hint');
    const warning = document.getElementById('bulk-warning');
    const scope = document.querySelector('input[name="bulk-scope"]:checked')?.value || 'filtered';
    const count = scope === 'selected' ? _selectedIds.size : scope === 'all' ? ALL_GAME_COUNT : BULK_GAME_COUNT;
    const colLabel = document.getElementById('bulk-column').options[document.getElementById('bulk-column').selectedIndex].text;

    if (mode === 'replace') {
        hint.textContent = 'Overwrites the entire value for every matching game.';
        valHint.textContent = 'Leave the value empty to clear this field for all matching games.';
        warning.style.display = 'block';
        warning.style.borderColor = '#c97c00';
        warning.style.background = 'rgba(193,120,0,0.12)';
        warning.style.color = '#c97c00';
        warning.innerHTML = `⚠ <strong>${count} game${count !== 1 ? 's' : ''}</strong> will have their <strong>${colLabel}</strong> completely overwritten. This cannot be undone.`;
    } else if (mode === 'append') {
        hint.textContent = 'Adds the value to the list if not already present. Existing values are kept. Duplicates are skipped.';
        valHint.textContent = 'You can enter multiple values separated by commas.';
        warning.style.display = 'block';
        warning.innerHTML = `ℹ <strong>${count} game${count !== 1 ? 's' : ''}</strong> will have values appended to <strong>${colLabel}</strong>.`;
        warning.style.borderColor = '#2a6496';
        warning.style.background = 'rgba(42,100,150,0.12)';
        warning.style.color = '#7ab8d9';
    } else if (mode === 'remove') {
        hint.textContent = 'Removes the value from the list. Other values are kept.';
        valHint.textContent = 'Suggestions show values present in the current scope.';
        warning.style.display = 'block';
        warning.innerHTML = `ℹ <strong>${count} game${count !== 1 ? 's' : ''}</strong> will have values removed from <strong>${colLabel}</strong> where present.`;
        warning.style.borderColor = '#2a6496';
        warning.style.background = 'rgba(42,100,150,0.12)';
        warning.style.color = '#7ab8d9';
    }

    const _mCol = document.getElementById('bulk-column').value;
    if (LIST_COLUMNS.has(_mCol)) {
        if (mode === 'remove') {
            _loadRemoveSuggestions();
        } else {
            PILL_SUGGESTIONS['bulk-pills-hidden'] = BULK_PILL_SUGGESTIONS[_mCol] || [];
        }
    }
}

function getBulkValue() {
    const col = document.getElementById('bulk-column').value;
    if (col === 'completion_status') {
        return document.getElementById('bulk-status-select').value;
    }
    if (LIST_COLUMNS.has(col)) {
        return document.getElementById('bulk-pills-hidden').value.trim();
    }
    return document.getElementById('bulk-value-text').value.trim();
}

async function runBulkEdit() {
    const column = document.getElementById('bulk-column').value;
    const mode   = document.getElementById('bulk-mode').value;
    const value  = getBulkValue();
    const scope  = document.querySelector('input[name="bulk-scope"]:checked').value;
    const status = document.getElementById('bulk-status');

    if (!value && column !== 'completion_status' && mode !== 'remove' && mode !== 'replace') {
        status.className = 'bulk-status-error';
        status.textContent = 'Please enter a value.';
        return;
    }
    if (scope === 'selected' && _selectedIds.size === 0) {
        status.className = 'bulk-status-error';
        status.textContent = 'No games selected. Use SELECT mode to pick games first.';
        return;
    }

    const btn = document.getElementById('bulk-apply-btn');
    btn.disabled = true; btn.textContent = 'Applying…';
    status.className = ''; status.textContent = '';

    const payload = { column, mode, value, ..._buildBulkScopePayload() };
    // scope === 'all': no appids and no filter_tree → backend uses WHERE 1=1

    try {
        const res = await fetch('/api/bulk-edit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'success') {
            status.className = 'bulk-status-success';
            status.textContent = `✔ Updated ${data.updated} game${data.updated !== 1 ? 's' : ''}.`;
            _exitSelectMode();
            setTimeout(() => { closeBulkEditModal(); window.location.reload(); }, 900);
        } else {
            status.className = 'bulk-status-error';
            status.textContent = '✘ ' + data.message;
        }
    } catch (e) {
        status.className = 'bulk-status-error';
        status.textContent = '✘ Network error.';
    } finally {
        btn.disabled = false; btn.textContent = 'Apply';
    }
}

// ── RE-SCRAPE TAB ───────────────────────────────────────────────────────────
function onBulkRescrapeScopeChange() {
    const scope = document.querySelector('input[name="brs-scope"]:checked')?.value;
    if (!scope) return;
    if (scope === 'selected' && _selectedIds.size === 0) {
        document.getElementById('brs-scope-filtered').checked = true;
        closeBulkEditModal();
        _enterSelectMode();
        return;
    }
    document.getElementById('brs-all-info').style.display      = scope === 'all'      ? 'block' : 'none';
    document.getElementById('brs-filtered-info').style.display = scope === 'filtered' ? 'block' : 'none';
    document.getElementById('brs-selected-info').style.display = scope === 'selected' ? 'block' : 'none';
    if (scope === 'all') {
        document.getElementById('brs-all-info').textContent = `${ALL_GAME_COUNT} game${ALL_GAME_COUNT !== 1 ? 's' : ''} in library`;
        _exitSelectMode();
    } else if (scope === 'filtered') {
        document.getElementById('brs-filtered-info').textContent = `${BULK_GAME_COUNT} game${BULK_GAME_COUNT !== 1 ? 's' : ''} currently shown`;
        _exitSelectMode();
    } else {
        document.getElementById('brs-selected-info').textContent = `${_selectedIds.size} game${_selectedIds.size !== 1 ? 's' : ''} selected`;
    }
}

async function startBulkOp(op) {
    if (_bulkOpPollInterval) return;

    const scope  = document.querySelector('input[name="brs-scope"]:checked')?.value || 'filtered';
    const status = document.getElementById('brs-status');

    let appids = [];
    if (scope === 'selected') {
        appids = Array.from(_selectedIds);
        if (!appids.length) {
            status.className = 'bulk-status-error';
            status.textContent = 'No games selected.';
            return;
        }
    } else if (scope === 'filtered') {
        appids = _filteredAppids();
    }

    const displayCount = scope === 'all' ? ALL_GAME_COUNT : appids.length;
    const payload = { op, scope };
    if (scope !== 'all') payload.appids = appids;

    if (op === 'art') {
        const types = [];
        if (document.getElementById('brs-type-vertical').checked)   types.push('vertical');
        if (document.getElementById('brs-type-horizontal').checked) types.push('horizontal');
        if (document.getElementById('brs-type-icon').checked)       types.push('icon');
        if (!types.length) {
            status.className = 'bulk-status-error';
            status.textContent = 'Select at least one artwork type.';
            return;
        }
        payload.types  = types;
        payload.source = document.querySelector('input[name="brs-source"]:checked')?.value || 'auto';
    }

    const opLabel = op === 'rescrape' ? 'Re-scrape store data' : op === 'protondb' ? 'Fetch ProtonDB data' : op === 'hltb' ? 'Fetch HLTB data' : 'Scrape artwork';
    const suffix  = scope === 'all' ? '\n\nThis will process your entire library and may take a long time.' : '';
    if (!await confirm(`${opLabel} for ${displayCount} game${displayCount !== 1 ? 's' : ''}?${suffix}`)) return;

    document.getElementById('brs-start-meta-btn').disabled = true;
    document.getElementById('brs-start-art-btn').disabled  = true;
    const protondbBtn = document.getElementById('brs-start-protondb-btn');
    if (protondbBtn) protondbBtn.disabled = true;
    const hltbBtn = document.getElementById('brs-start-hltb-btn');
    if (hltbBtn) hltbBtn.disabled = true;
    const stopBtn = document.getElementById('brs-stop-btn');
    stopBtn.style.display = '';
    stopBtn.disabled = false;
    stopBtn.textContent = 'Stop';
    status.className = ''; status.textContent = '';

    const progress      = document.getElementById('brs-progress');
    const progressBar   = document.getElementById('brs-progress-bar');
    const progressLabel = document.getElementById('brs-progress-label');
    progress.style.display = 'block';
    progressBar.style.width = '0%';
    progressLabel.textContent = `0 / ${displayCount}`;

    try {
        const res  = await fetch('/api/bulk-op/start', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (d.status !== 'success') {
            status.className = 'bulk-status-error';
            status.textContent = '✘ ' + (d.message || 'Failed to start.');
            document.getElementById('brs-start-meta-btn').disabled = false;
            document.getElementById('brs-start-art-btn').disabled  = false;
            stopBtn.style.display = 'none';
            return;
        }
        progressLabel.textContent = `0 / ${d.total}`;
    } catch (e) {
        status.className = 'bulk-status-error';
        status.textContent = '✘ Network error.';
        document.getElementById('brs-start-meta-btn').disabled = false;
        document.getElementById('brs-start-art-btn').disabled  = false;
        const _pdbBtn = document.getElementById('brs-start-protondb-btn');
        if (_pdbBtn) _pdbBtn.disabled = false;
        const _hltbBtn2 = document.getElementById('brs-start-hltb-btn');
        if (_hltbBtn2) _hltbBtn2.disabled = false;
        stopBtn.style.display = 'none';
        return;
    }

    document.dispatchEvent(new CustomEvent('bulkop:started'));
    _pollBulkOp();
}

async function stopBulkOp() {
    document.getElementById('brs-stop-btn').disabled = true;
    document.getElementById('brs-stop-btn').textContent = 'Stopping…';
    await fetch('/api/bulk-op/cancel', { method: 'POST' }).catch(() => {});
}

function _pollBulkOp() {
    _bulkOpPollInterval = setInterval(async () => {
        try {
            const r = await fetch('/api/bulk-op/status');
            const d = await r.json();
            const done = d.done + d.failed;
            const pct  = d.total > 0 ? Math.round((done / d.total) * 100) : 0;
            document.getElementById('brs-progress-bar').style.width = pct + '%';
            document.getElementById('brs-progress-label').textContent =
                `${done} / ${d.total}${d.rate_limit_hit ? ' — rate limited, waiting…' : ''}`;

            if (d.op === 'hltb' && d.done > 0) _hltbLoadMatches(true);

            if (!d.running) {
                clearInterval(_bulkOpPollInterval);
                _bulkOpPollInterval = null;
                if (d.op === 'hltb') _hltbLoadMatches(false);
                const status = document.getElementById('brs-status');
                if (d.result?.error) {
                    status.className = 'bulk-status-error';
                    status.textContent = '✘ Error: ' + d.result.error;
                } else {
                    status.className = d.done > 0 ? 'bulk-status-success' : '';
                    status.textContent = `✔ Done — ${d.done} updated${d.failed ? `, ${d.failed} failed` : ''}${d.aborted ? ' (rate limit exhausted)' : ''}.`;
                }
                document.getElementById('brs-start-meta-btn').disabled = false;
                document.getElementById('brs-start-art-btn').disabled  = false;
                document.getElementById('brs-stop-btn').style.display  = 'none';
            }
        } catch (e) { /* ignore */ }
    }, 1000);
}

// ── BULK DELETE ────────────────────────────────────────────────
function openBulkDeleteModal() {
    closeBulkEditModal();
    const hasSelection = _selectedIds.size > 0;
    const scopeFiltered = document.getElementById('bd-scope-filtered');
    const scopeSelected = document.getElementById('bd-scope-selected');
    if (hasSelection) {
        scopeSelected.checked = true;
    } else {
        scopeFiltered.checked = true;
    }
    onBulkDeleteScopeChange();
    document.getElementById('bulk-delete-modal').style.display = 'flex';
    document.getElementById('bd-status').textContent = '';
    document.getElementById('bd-status').className = '';
}

function closeBulkDeleteModal() {
    document.getElementById('bulk-delete-modal').style.display = 'none';
}

function onBulkDeleteScopeChange() {
    const scope    = document.querySelector('input[name="bd-scope"]:checked').value;
    const selInfo  = document.getElementById('bd-selected-info');
    const filtInfo = document.getElementById('bd-filtered-info');
    const warning  = document.getElementById('bd-warning');
    if (scope === 'selected') {
        if (_selectedIds.size === 0) {
            document.getElementById('bd-scope-filtered').checked = true;
            closeBulkDeleteModal();
            _enterSelectMode();
            return;
        }
        filtInfo.style.display = 'none';
        selInfo.style.display  = 'block';
        selInfo.textContent    = `${_selectedIds.size} game${_selectedIds.size !== 1 ? 's' : ''} selected`;
        warning.innerHTML = `⚠ <strong>${_selectedIds.size} game${_selectedIds.size !== 1 ? 's' : ''}</strong> will be permanently removed from your library. Cover images will also be deleted. This cannot be undone.`;
    } else {
        selInfo.style.display  = 'none';
        filtInfo.style.display = 'block';
        filtInfo.textContent   = `${BULK_GAME_COUNT} game${BULK_GAME_COUNT !== 1 ? 's' : ''} currently shown`;
        warning.innerHTML = `⚠ <strong>${BULK_GAME_COUNT} game${BULK_GAME_COUNT !== 1 ? 's' : ''}</strong> will be permanently removed from your library. Cover images will also be deleted. This cannot be undone.`;
        _exitSelectMode();
    }
}

async function runBulkDelete() {
    const scope  = document.querySelector('input[name="bd-scope"]:checked').value;
    const status = document.getElementById('bd-status');

    if (scope === 'selected' && _selectedIds.size === 0) {
        status.className = 'bulk-status-error';
        status.textContent = 'No games selected. Use SELECT mode to pick games first.';
        return;
    }

    const count = scope === 'selected' ? _selectedIds.size : BULK_GAME_COUNT;
    if (!await confirm(`Permanently delete ${count} game${count !== 1 ? 's' : ''} from your PlayDate library?\n\nThis removes their database entries and cover images. This cannot be undone.`)) return;

    const btn = document.getElementById('bd-apply-btn');
    btn.disabled = true;
    btn.textContent = 'Deleting…';
    status.className = '';
    status.textContent = '';

    const appids = scope === 'selected'
        ? Array.from(_selectedIds)
        : _filteredAppids();

    try {
        const res = await fetch('/api/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ appids })
        });
        const data = await res.json();
        if (data.status === 'success') {
            status.className = 'bulk-status-success';
            status.textContent = `✔ Deleted ${data.deleted} game${data.deleted !== 1 ? 's' : ''}.`;
            _exitSelectMode();
            setTimeout(() => { closeBulkDeleteModal(); window.location.reload(); }, 900);
        } else {
            status.className = 'bulk-status-error';
            status.textContent = '✘ ' + data.message;
            btn.disabled = false; btn.textContent = 'Delete';
        }
    } catch (e) {
        status.className = 'bulk-status-error';
        status.textContent = '✘ Network error.';
        btn.disabled = false; btn.textContent = 'Delete';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initCustomSelect(document.getElementById('sort-dropdown'));
    initCustomSelect(document.getElementById('group-by-dropdown'));
    initCustomSelect(document.getElementById('bulk-column'));
    initCustomSelect(document.getElementById('bulk-mode'));
    initCustomSelect(document.getElementById('bulk-status-select'));
});

// Resume bulk op / date import UI if an operation is already running when the page loads
(async () => {
    try {
        const [opRes, dateRes] = await Promise.all([
            fetch('/api/bulk-op/status'),
            fetch('/api/bulk-date-import/status')
        ]);
        const op = await opRes.json();
        const dt = await dateRes.json();

        if (op.running) {
            const done = op.done + op.failed;
            const pct  = op.total > 0 ? Math.round((done / op.total) * 100) : 0;
            document.getElementById('brs-progress').style.display = 'block';
            document.getElementById('brs-progress-bar').style.width = pct + '%';
            document.getElementById('brs-progress-label').textContent = `${done} / ${op.total}`;
            document.getElementById('brs-start-meta-btn').disabled = true;
            document.getElementById('brs-start-art-btn').disabled  = true;
            const pdbBtn  = document.getElementById('brs-start-protondb-btn');
            if (pdbBtn)  pdbBtn.disabled  = true;
            const hltbBtn = document.getElementById('brs-start-hltb-btn');
            if (hltbBtn) hltbBtn.disabled = true;
            const stopBtn = document.getElementById('brs-stop-btn');
            stopBtn.style.display = '';
            stopBtn.disabled = false;
            stopBtn.textContent = 'Stop';
            _pollBulkOp();
        }

        if (dt.active) {
            const done = dt.done + dt.failed;
            const pct  = dt.total > 0 ? Math.round((done / dt.total) * 100) : 0;
            document.getElementById('bdi-progress').style.display = 'block';
            document.getElementById('bdi-progress-bar').style.width = pct + '%';
            document.getElementById('bdi-progress-label').textContent =
                `${done} / ${dt.total} — ${dt.done} imported, ${dt.failed} not found`;
            document.getElementById('bdi-current-game').textContent = dt.current ? dt.current.name : '…';
            document.getElementById('bdi-start-btn').disabled = true;
            const stopBtn = document.getElementById('bdi-stop-btn');
            stopBtn.style.display = '';
            stopBtn.disabled = false;
            _bdiLastResultCount = (dt.results || []).length;
            _pollBulkDateImport();
        }
    } catch(e) {}
})();

// ── DATE IMPORTER TAB ───────────────────────────────────────────────────────
function closeBulkDateImportModal() {
    if (_bdiPollInterval) { clearInterval(_bdiPollInterval); _bdiPollInterval = null; }
    closeBulkEditModal();
}

function onBulkDateImportScopeChange() {
    const scope = document.querySelector('input[name="bdi-scope"]:checked')?.value;
    if (!scope) return;
    if (scope === 'selected' && _selectedIds.size === 0) {
        document.getElementById('bdi-scope-filtered').checked = true;
        closeBulkEditModal();
        _enterSelectMode();
        return;
    }
    document.getElementById('bdi-all-info').style.display      = scope === 'all'      ? 'block' : 'none';
    document.getElementById('bdi-filtered-info').style.display = scope === 'filtered' ? 'block' : 'none';
    document.getElementById('bdi-selected-info').style.display = scope === 'selected' ? 'block' : 'none';
    if (scope === 'all') {
        document.getElementById('bdi-all-info').textContent = `${ALL_GAME_COUNT} game${ALL_GAME_COUNT !== 1 ? 's' : ''} in library`;
        _exitSelectMode();
    } else if (scope === 'filtered') {
        document.getElementById('bdi-filtered-info').textContent = `${BULK_GAME_COUNT} game${BULK_GAME_COUNT !== 1 ? 's' : ''} currently shown`;
        _exitSelectMode();
    } else {
        document.getElementById('bdi-selected-info').textContent = `${_selectedIds.size} game${_selectedIds.size !== 1 ? 's' : ''} selected`;
    }
}

let _bdiPollInterval = null;
let _bdiScriptCheckTimeout = null;
let _bdiLastResultCount = 0;

async function startBulkDateImport() {
    if (_bdiPollInterval) return;

    const scope    = document.querySelector('input[name="bdi-scope"]:checked').value;
    const status   = document.getElementById('bdi-status');
    const startBtn = document.getElementById('bdi-start-btn');
    const stopBtn  = document.getElementById('bdi-stop-btn');

    if (scope === 'selected' && _selectedIds.size === 0) {
        status.className = 'bulk-status-error';
        status.textContent = 'No games selected.';
        return;
    }

    const payload = { scope };
    if (scope === 'selected') {
        payload.appids = Array.from(_selectedIds);
    } else if (scope === 'filtered') {
        payload.appids = _filteredAppids();
    }

    startBtn.disabled = true;
    status.className = '';
    status.textContent = 'Starting…';

    let data;
    try {
        const res = await fetch('/api/bulk-date-import/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        data = await res.json();
    } catch (e) {
        status.className = 'bulk-status-error';
        status.textContent = 'Failed to start: ' + e.message;
        startBtn.disabled = false;
        return;
    }

    if (data.status !== 'ok') {
        status.className = 'bulk-status-error';
        status.textContent = data.message || 'Failed to start.';
        startBtn.disabled = false;
        return;
    }

    const _dateUrls = data.date_import_urls || [];
    if (data.total === 0 && !_dateUrls.length) {
        status.className = 'bulk-status-success';
        status.textContent = 'No games to process.';
        startBtn.disabled = false;
        return;
    }

    // Open external date import pages (e.g. GOG orders) for any plugin that provides one
    for (const {url} of _dateUrls) {
        const _e = document.createElement('a');
        _e.href = url; _e.target = '_blank'; _e.rel = 'noopener';
        document.body.appendChild(_e); _e.click(); document.body.removeChild(_e);
    }

    // Open Steam Help page only when there are Steam games in the queue
    if (data.first_appid != null) {
        const _a = document.createElement('a');
        _a.href = `https://help.steampowered.com/en/wizard/HelpWithGame/?appid=${data.first_appid}&ref=playdate&bulk=1`;
        _a.target = '_blank';
        _a.rel = 'noopener';
        document.body.appendChild(_a);
        _a.click();
        document.body.removeChild(_a);
    }

    // If only plugin-handled games (no Steam queue), show status and stop
    if (data.total === 0) {
        status.className = 'bulk-status-success';
        const _labels = _dateUrls.map(u => u.label).join(', ');
        status.textContent = _labels
            ? `${_labels} orders page opened — check that tab for results.`
            : 'No games to process.';
        startBtn.disabled = false;
        return;
    }

    status.textContent = '';
    const logEl = document.getElementById('bdi-log');
    logEl.innerHTML = '';
    document.getElementById('bdi-progress').style.display = 'block';
    document.getElementById('bdi-progress-bar').style.width = '0%';
    document.getElementById('bdi-progress-label').textContent = `0 / ${data.total}`;
    document.getElementById('bdi-current-game').textContent = data.first_name || '';
    stopBtn.style.display = '';
    stopBtn.disabled = false;

    // Auto-cancel if the Tampermonkey script hasn't pinged back within 15 seconds
    // (only needed when there are Steam games in the queue)
    if (data.first_appid != null) {
        _bdiScriptCheckTimeout = setTimeout(async () => {
            try {
                const r = await fetch('/api/bulk-date-import/status');
                const d = await r.json();
                if (!d.script_connected) {
                    await fetch('/api/bulk-date-import/cancel', { method: 'POST' }).catch(() => {});
                    clearInterval(_bdiPollInterval); _bdiPollInterval = null;
                    stopBtn.style.display = 'none';
                    startBtn.disabled = false;
                    status.className = 'bulk-status-error';
                    status.textContent = 'Tampermonkey script not detected. Install steam_date_import.user.js and ensure Tampermonkey is enabled.';
                    document.getElementById('bdi-progress').style.display = 'none';
                }
            } catch (e) { /* ignore */ }
        }, 15000);
    }

    document.dispatchEvent(new CustomEvent('dateimport:started'));
    _bdiLastResultCount = 0;
    _pollBulkDateImport();
}

function _pollBulkDateImport() {
    _bdiPollInterval = setInterval(async () => {
        try {
            const r = await fetch('/api/bulk-date-import/status');
            const d = await r.json();
            const done = d.done + d.failed;
            const pct  = d.total > 0 ? Math.round((done / d.total) * 100) : 0;
            document.getElementById('bdi-progress-bar').style.width = pct + '%';
            document.getElementById('bdi-progress-label').textContent =
                `${done} / ${d.total} — ${d.done} imported, ${d.failed} not found`;
            document.getElementById('bdi-current-game').textContent =
                d.current ? d.current.name : (d.active ? '…' : 'Done');

            // Append any new log entries (results are newest-first)
            const logEl   = document.getElementById('bdi-log');
            const results = d.results || [];
            if (results.length > _bdiLastResultCount) {
                const newEntries = results.slice(0, results.length - _bdiLastResultCount);
                newEntries.reverse().forEach(entry => {
                    const row = document.createElement('div');
                    row.style.cssText = `padding:2px 0; border-bottom:1px solid #1a2e3e; color:${entry.date ? '#c2c8cc' : '#4a5a6a'};`;
                    row.textContent = entry.date
                        ? `${entry.name} — ${entry.date}`
                        : `${entry.name} — not found`;
                    logEl.insertBefore(row, logEl.firstChild);
                });
                _bdiLastResultCount = results.length;
            }

            if (!d.active) {
                clearTimeout(_bdiScriptCheckTimeout); _bdiScriptCheckTimeout = null;
                clearInterval(_bdiPollInterval); _bdiPollInterval = null;
                document.getElementById('bdi-start-btn').disabled = false;
                document.getElementById('bdi-stop-btn').style.display = 'none';
                const errs = (d.api_errors || []);
                const status = document.getElementById('bdi-status');
                status.className = errs.length ? 'bulk-status-error' : 'bulk-status-success';
                status.textContent = `Done — ${d.done} date${d.done !== 1 ? 's' : ''} imported, ${d.failed} not found.`
                    + (errs.length ? ' ' + errs.join(' ') : '');
            }
        } catch (e) { /* ignore poll errors */ }
    }, 1000);
}

async function stopBulkDateImport() {
    await fetch('/api/bulk-date-import/cancel', { method: 'POST' }).catch(() => {});
    clearTimeout(_bdiScriptCheckTimeout); _bdiScriptCheckTimeout = null;
    clearInterval(_bdiPollInterval); _bdiPollInterval = null;
    _bdiLastResultCount = 0;
    document.getElementById('bdi-stop-btn').style.display = 'none';
    document.getElementById('bdi-start-btn').disabled = false;
    document.getElementById('bdi-status').className = '';
    document.getElementById('bdi-status').textContent = 'Cancelled.';
}

// ── PAGYWOSG hover tooltip ────────────────────────────────────────────────────
(function() {
    if (!_serverFilterTree?.pagywosg) return;

    const tooltip        = document.getElementById('pag-hover-tooltip');
    const gpTooltip      = document.getElementById('pag-gamepad-tooltip');
    const grid           = document.getElementById('game-grid');
    const sgGroup        = _pagExtractSgGroup(_serverFilterTree);

    function _hltbMin(game) {
        const vals = [game.hltb_main, game.hltb_extras, game.hltb_completionist]
            .filter(v => v && v > 0);
        return vals.length ? Math.min(...vals) : null;
    }

    function _buildTooltip(game) {
        const isWin = sgGroup ? _pagCsvContains(game.groups, sgGroup) : false;
        const isSantaGift = (_serverFilterTree.pagywosg_verified?.[String(game.appid)] || []).some(e => e.auto && e.pool === 'wins');

        const results = [];
        _pagExtractConds(_serverFilterTree).forEach(cond => {
            if (cond.pool === 'wins' && !isWin && !isSantaGift) return;
            const desc = _pagCheckCond(cond, game);
            if (desc) {
                const label = (cond.pool === 'wins' && !isWin && isSantaGift)
                    ? '(santa/snowball)' : _pagLabel(cond.pool, game, sgGroup);
                (Array.isArray(desc) ? desc : [desc]).forEach(d => results.push({ desc: d, label, verified: false }));
            }
        });
        (_serverFilterTree.pagywosg_verified?.[String(game.appid)] || []).forEach(({ cat, pool, verifiers, auto, year }) => {
            // Santa/snowball entries carry a `year` (evidence of when the gift
            // was given) — always show those as their own line even though
            // they're otherwise auto+wins, which is normally suppressed below
            // in favor of the "(santa/snowball)" relabeling of other matched
            // wins-pool conditions further up.
            if (auto && pool === 'wins' && !year) return;
            if (pool === 'wins' && !isWin && !year) return;
            const label = year ? `(santa/snowball, ${year})` : _pagLabel(pool, game, sgGroup);
            results.push({ desc: cat, label, verified: !auto, verifiers: verifiers || [] });
        });

        const hltbMin = _hltbMin(game);
        if (!results.length && hltbMin === null) return null;

        let html = results.map(r => {
            const verifPart = r.verified
                ? ` <span style="color:var(--text-secondary);">— mod verified${r.verifiers.length ? ` (${r.verifiers.join(', ')})` : ''}</span>`
                : '';
            return `<div><span style="color:var(--accent-positive);">✓</span> ${r.desc} <span style="color:var(--text-secondary);">${r.label}${verifPart}</span></div>`;
        }).join('');

        if (hltbMin !== null) {
            if (results.length) html += `<div style="margin-top:5px; border-top:1px solid var(--border); padding-top:5px;">`;
            html += `<span style="color:var(--text-secondary);">HLTB min:</span> <strong>${fmtHours(hltbMin)}</strong>`;
            if (results.length) html += `</div>`;
        }

        return html;
    }

    let _hoveredAppid = null;
    let _hideOnStopTimer = null;

    function _hideTooltip() {
        tooltip.style.display = 'none';
        tooltip.style.transform = '';
        tooltip.style.visibility = '';
        tooltip.style.opacity = '0';
        tooltip.innerHTML = '';
        _hoveredAppid = null;
    }

    let _gpTooltipCard = null;
    let _gpTrackingRaf = null;

    function _hideGpTooltip() {
        cancelAnimationFrame(_gpTrackingRaf);
        _gpTrackingRaf = null;
        _gpTooltipCard = null;
        gpTooltip.style.display = 'none';
        gpTooltip.innerHTML = '';
    }

    function _positionTooltipBelowCard(el, card) {
        const rect = card.getBoundingClientRect();
        const pad = 8;
        const tw = el.offsetWidth;
        const th = el.offsetHeight;
        let x = rect.left + (rect.width - tw) / 2;
        // Decide above vs below by card position, not tooltip size, so all cards
        // in the same row flip together rather than based on individual tooltip height.
        const showAbove = rect.top > window.innerHeight / 2;
        let y = showAbove ? rect.top - th - pad : rect.bottom + pad;
        if (x + tw > window.innerWidth - pad) x = window.innerWidth - tw - pad;
        if (x < pad) x = pad;
        if (y < pad) y = pad;
        if (y + th > window.innerHeight - pad) y = window.innerHeight - th - pad;
        return { x: Math.round(x), y: Math.round(y) };
    }

    function _positionGpTooltip(card) {
        const { x, y } = _positionTooltipBelowCard(gpTooltip, card);
        gpTooltip.style.left = x + 'px';
        gpTooltip.style.top  = y + 'px';
    }

    function _positionHoverTooltip(card) {
        const { x, y } = _positionTooltipBelowCard(tooltip, card);
        tooltip.style.transform = `translate(${x}px,${y}px)`;
    }

    function _showGpTooltip(card) {
        const appid = parseInt(card.dataset.appid);
        if (!appid || !card.dataset.populated) { _hideGpTooltip(); return; }
        const game = _GAME_MAP.get(appid);
        if (!game) { _hideGpTooltip(); return; }
        const html = _buildTooltip(game);
        if (!html) { _hideGpTooltip(); return; }

        gpTooltip.innerHTML = html;
        gpTooltip.style.display = 'block';
        _positionGpTooltip(card);

        // Track card position each frame so the tooltip follows the scroll animation.
        _gpTooltipCard = card;
        cancelAnimationFrame(_gpTrackingRaf);
        let prevTop = null, prevLeft = null;
        function _track() {
            if (_gpTooltipCard !== card) return;
            const rect = card.getBoundingClientRect();
            if (rect.top !== prevTop || rect.left !== prevLeft) {
                prevTop = rect.top; prevLeft = rect.left;
                _positionGpTooltip(card);
            }
            _gpTrackingRaf = requestAnimationFrame(_track);
        }
        _gpTrackingRaf = requestAnimationFrame(_track);
    }

    // MutationObserver: show immediately — tooltip tracks the card's scroll position via rAF.
    const _gpFocusObserver = new MutationObserver(mutations => {
        for (const m of mutations) {
            if (m.type !== 'attributes' || m.attributeName !== 'class') continue;
            const card = m.target;
            if (!card.classList.contains('game-card')) continue;
            if (card.classList.contains('gamepad-focus')) {
                _showGpTooltip(card);
            } else {
                if (!grid.querySelector('.game-card.gamepad-focus')) _hideGpTooltip();
            }
        }
    });
    _gpFocusObserver.observe(grid, { subtree: true, attributes: true, attributeFilter: ['class'] });

    grid.addEventListener('mouseover', e => {
        if (window._inputMgr?.active) return;
        const card = e.target.closest('.game-card[data-appid]');
        const appid = card ? parseInt(card.dataset.appid) : null;
        if (appid === _hoveredAppid) return;
        clearTimeout(_hideOnStopTimer);
        _hoveredAppid = appid;
        if (!appid || !card.dataset.populated) { _hideTooltip(); return; }
        const game = _GAME_MAP.get(appid);
        if (!game) { _hideTooltip(); return; }
        const html = _buildTooltip(game);
        if (!html) { _hideTooltip(); return; }
        tooltip.style.display = 'block';
        tooltip.innerHTML = html;
        _positionHoverTooltip(card);
        tooltip.style.visibility = '';
        tooltip.style.opacity = '1';
        _hoveredAppid = appid;
    });

    grid.addEventListener('mouseleave', () => _hideTooltip());
    document.addEventListener('pointerleave', () => _hideTooltip());

    let _lastMouseX = 0, _lastMouseY = 0, _scrollReshowTimer = null;

    document.addEventListener('mousemove', e => {
        if (window._inputMgr?.active) { _hideTooltip(); return; }
        _lastMouseX = e.clientX; _lastMouseY = e.clientY;
        clearTimeout(_hideOnStopTimer);
        if (e.clientY >= window.innerHeight - 4) {
            _hideOnStopTimer = setTimeout(() => _hideTooltip(), 150);
        }
    });

    window._cancelTooltipReshow = () => { clearTimeout(_scrollReshowTimer); _hideTooltip(); };

    let _scrollBlurTimer = null;
    window.addEventListener('scroll', () => {
        document.body.classList.add('is-scrolling');
        clearTimeout(_scrollBlurTimer);
        _scrollBlurTimer = setTimeout(() => document.body.classList.remove('is-scrolling'), 150);
        _hideTooltip();
        clearTimeout(_scrollReshowTimer);
        _scrollReshowTimer = setTimeout(() => {
            if (window._inputMgr?.active) return;
            const el = document.elementFromPoint(_lastMouseX, _lastMouseY);
            const card = el && el.closest('.game-card[data-appid]');
            if (!card) return;
            const appid = parseInt(card.dataset.appid);
            if (!appid || !card.dataset.populated) return;
            const game = _GAME_MAP.get(appid);
            if (!game) return;
            const html = _buildTooltip(game);
            if (!html) return;
            tooltip.style.display = 'block';
            tooltip.innerHTML = html;
            _positionHoverTooltip(card);
            tooltip.style.visibility = '';
            tooltip.style.opacity = '1';
            _hoveredAppid = appid;
        }, 150);
    }, { passive: true });
})();

function _preloadCardsInArea(scrollTop) {
    const vh = window.innerHeight;
    const lo = scrollTop - 175;
    const hi = scrollTop + vh + 100;
    document.querySelectorAll('.game-card:not([data-populated])').forEach(card => {
        if (card.offsetTop < lo || card.offsetTop > hi) return;
        const appid = parseInt(card.dataset.appid);
        const game  = GAMES.find(g => g.appid === appid);
        if (!game) return;
        card.innerHTML = cardInnerHTML(game);
        card.dataset.populated = '1';
        const img = card.querySelector('img[data-src]');
        if (!img) return;
        const fallback = img.dataset.fallback;
        if (fallback) img.onerror = () => { img.onerror = null; img.src = fallback; };
        else          img.onerror = () => { img.onerror = null; };
        img.src = img.dataset.src;
    });
}

function pickRandomGame() {
    if (!GAMES.length) return;
    const game = GAMES[Math.floor(Math.random() * GAMES.length)];

    if (_artOrientation === 'list') {
        openDetailPane(game);
        return;
    }

    const card = document.querySelector(`.game-card[data-appid="${game.appid}"]`);
    if (!card) return;

    window._inputMgr?.focusLibraryCard(game.appid);

    document.querySelectorAll('.game-card.dice-picked').forEach(c => c.classList.remove('dice-picked'));

    const startGlow = () => {
        card.classList.remove('dice-picked');
        void card.offsetWidth;
        const outlineColor = OUTLINE_COLORS[String(game.appid)];
        if (outlineColor) {
            card.style.setProperty('--dice-glow', outlineColor);
        } else {
            card.style.removeProperty('--dice-glow');
        }
        card.classList.add('dice-picked');
        card.addEventListener('animationend', () => card.classList.remove('dice-picked'), { once: true });
    };

    const rect = card.getBoundingClientRect();
    if (rect.top >= 0 && rect.bottom <= window.innerHeight) {
        startGlow();
        return;
    }

    const vh = window.innerHeight;
    const cardTop = card.getBoundingClientRect().top + window.scrollY;
    const targetScroll = Math.max(0, cardTop - vh / 2 + card.offsetHeight / 2);
    const direction = targetScroll > window.scrollY ? 1 : -1;
    const maxScroll = document.documentElement.scrollHeight - vh;
    const jumpTo = Math.max(0, Math.min(maxScroll, targetScroll - direction * 2 * vh));

    _preloadCardsInArea(jumpTo);
    _preloadCardsInArea(targetScroll);

    window.scrollTo({ top: jumpTo, behavior: 'instant' });

    // Manual slow scroll — browser smooth is too fast to control
    requestAnimationFrame(() => requestAnimationFrame(() => {
        const scrollStart = window.scrollY;
        const scrollDist  = targetScroll - scrollStart;
        const duration    = 4000;
        const t0          = performance.now();
        const step = (now) => {
            const p    = Math.min((now - t0) / duration, 1);
            const ease = 1 - Math.pow(1 - p, 3); // ease-out cubic
            window.scrollTo({ top: scrollStart + scrollDist * ease, behavior: 'instant' });
            if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    }));

    const observer = new IntersectionObserver((entries, obs) => {
        if (entries[0].isIntersecting) {
            obs.disconnect();
            startGlow();
        }
    }, { threshold: 0.3 });
    observer.observe(card);
}

    // ── LIST MODE ──────────────────────────────────────────────────────────────

    let _dpCurrentGame = null;
    let _dpCurrentAppid = null;
    let _dpDescLoaded = new Set(); // appids whose description is already shown
    let _dpExtraInfoLoaded = new Set(); // appids whose plugin extra-info is already shown

    const _DP_SESSION_KEY = 'pd_list_selected_appid';
    function _dpSaveSelection(appid) { safeSession.setItem(_DP_SESSION_KEY, String(appid)); }
    function _dpRestoreSelection() {
        const saved = safeSession.getItem(_DP_SESSION_KEY);
        return saved ? _GAME_MAP.get(parseInt(saved, 10)) || null : null;
    }

    function _adjustListHeight() {
        const ll = document.getElementById('library-list-layout');
        if (!ll || ll.style.display === 'none') return;
        const top = ll.getBoundingClientRect().top;
        ll.style.height = (window.innerHeight - top - 2) + 'px';
    }

    function _initListDivider() {
        const divider  = document.getElementById('list-divider');
        const listPane = document.getElementById('list-pane');
        const layout   = document.getElementById('library-list-layout');
        if (!divider || !listPane || !layout) return;
        let dragging = false, startX = 0, startW = 0;
        divider.addEventListener('mousedown', e => {
            dragging = true; startX = e.clientX; startW = listPane.offsetWidth;
            divider.classList.add('dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
        document.addEventListener('mousemove', e => {
            if (!dragging) return;
            const totalW  = layout.offsetWidth;
            const newW    = startW + (e.clientX - startX);
            const minW    = 200;
            const maxW    = Math.floor(totalW * 0.5);
            listPane.style.width = Math.min(Math.max(newW, minW), maxW) + 'px';
            listPane.style.flex  = 'none';
        });
        document.addEventListener('mouseup', () => {
            if (!dragging) return;
            dragging = false;
            divider.classList.remove('dragging');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        });
    }

    // Creates a placeholder row — content is filled lazily by observeListRows()
    function _makeListRow(game) {
        const row = document.createElement('div');
        row.className = 'list-row';
        row.dataset.appid     = game.appid;
        row.dataset.name      = game.name      || '';
        row.dataset.status    = game.completion_status || '';
        row.dataset.platform  = game.platform  || 'steam';
        row.dataset.installed = game.installed ? '1' : '0';
        // Resolve via _GAME_MAP at click time so edits are always reflected
        row.addEventListener('click', () => {
            if (_selectMode) {
                const appid = game.appid;
                if (_selectedIds.has(appid)) { _selectedIds.delete(appid); row.classList.remove('selected'); }
                else                         { _selectedIds.add(appid);    row.classList.add('selected'); }
                _updateSelectBadge();
            } else {
                const g = _GAME_MAP.get(game.appid); if (g) openDetailPane(g);
            }
        });
        row.addEventListener('dblclick', () => { if (!_selectMode) launchGame(game.appid); });
        return row;
    }

    function _populateListRow(row) {
        const appid = parseInt(row.dataset.appid, 10);
        const game  = _GAME_MAP.get(appid);
        if (!game) return;
        row.innerHTML = `<img class="list-icon" alt="" src="/static/img/library/icons/${game.appid}.jpg?v=${_imgV}" onerror="this.style.display='none'"><span class="list-name">${escHtml(game.name || '')}</span><span class="list-status-badge">${escHtml(game.completion_status || '')}</span>`;
        row.dataset.populated = '1';
        if (_selectedIds.has(appid)) row.classList.add('selected');
    }

    let _listObserver = null;
    function observeListRows() {
        if (_listObserver) _listObserver.disconnect();
        const gameList = document.getElementById('game-list');
        if (!gameList) return;
        _listObserver = new IntersectionObserver((entries) => {
            requestAnimationFrame(() => {
                entries.forEach(entry => {
                    if (entry.isIntersecting && !entry.target.dataset.populated) {
                        _populateListRow(entry.target);
                        _listObserver.unobserve(entry.target);
                    }
                });
            });
        }, { root: gameList, rootMargin: '800px', threshold: 0 });
        gameList.querySelectorAll('.list-row').forEach(r => _listObserver.observe(r));
    }

    function buildListView() {
        const listEl = document.getElementById('game-list');
        if (!listEl) return;
        listEl.innerHTML = '';
        const fragment = document.createDocumentFragment();

        if (_groupBy) {
            // Group games by key, preserving server sort order within each group
            const groupMap = new Map();
            GAMES.forEach(game => {
                const key = String(_getGroupKey(game) ?? 'null');
                if (!groupMap.has(key)) groupMap.set(key, []);
                groupMap.get(key).push(game);
            });
            const sortedKeys = _sortGroupKeys([...groupMap.keys()].map(k => k === 'null' ? null : k))
                .map(k => String(k ?? 'null'));
            sortedKeys.forEach(strKey => {
                const games = groupMap.get(strKey);
                if (!games?.length) return;
                const rawKey = strKey === 'null' ? null : strKey;
                const collapsed = _collapsedGroups.has(strKey);

                const header = document.createElement('div');
                header.className = 'list-group-header';
                header.dataset.groupKey = strKey;

                const chevron = document.createElement('span');
                chevron.className = 'group-chevron';
                chevron.textContent = collapsed ? '▸' : '▾';
                header.appendChild(chevron);
                header.appendChild(document.createTextNode(_getGroupLabel(rawKey)));
                fragment.appendChild(header);

                const rows = games.map(game => {
                    const row = _makeListRow(game);
                    if (collapsed) row.style.display = 'none';
                    return row;
                });
                rows.forEach(r => fragment.appendChild(r));

                header.addEventListener('click', () => {
                    const isNowCollapsed = _collapsedGroups.has(strKey);
                    if (isNowCollapsed) {
                        _collapsedGroups.delete(strKey);
                        chevron.textContent = '▾';
                        rows.forEach(r => r.style.display = '');
                    } else {
                        _collapsedGroups.add(strKey);
                        chevron.textContent = '▸';
                        rows.forEach(r => r.style.display = 'none');
                    }
                });
            });
        } else {
            GAMES.forEach(game => fragment.appendChild(_makeListRow(game)));
        }

        listEl.appendChild(fragment);
        observeListRows();
        if (_liveSearchQuery) applyLiveSearch(_liveSearchQuery);

        // Show last-selected (from safeSession), in-memory current, or first visible row
        const _firstVisibleGame = () => {
            const row = listEl.querySelector('.list-row:not([style*="display: none"]):not([style*="display:none"])');
            return row ? _GAME_MAP.get(parseInt(row.dataset.appid, 10)) || null : GAMES[0];
        };
        const first = _dpCurrentGame
            ? (_GAME_MAP.get(_dpCurrentGame.appid) || _firstVisibleGame())
            : (_dpRestoreSelection() || _firstVisibleGame());
        if (first) openDetailPane(first);

        // Register with input manager for gamepad
        if (window._inputMgr?.onListBuilt) window._inputMgr.onListBuilt();
    }

    function _patchListRow(game) {
        const row = document.querySelector(`.list-row[data-appid="${game.appid}"]`);
        if (!row) return;
        const nameEl   = row.querySelector('.list-name');
        const statusEl = row.querySelector('.list-status-badge');
        if (nameEl)   nameEl.textContent   = game.name || '';
        if (statusEl) statusEl.textContent = game.completion_status || '';
        // Keep context menu data attributes in sync
        if (row) {
            row.dataset.name      = game.name      || '';
            row.dataset.status    = game.completion_status || '';
            row.dataset.installed = game.installed ? '1' : '0';
        }
        // Refresh in GAMES array
        const existing = _GAME_MAP.get(game.appid);
        if (existing) Object.assign(existing, game);
    }

    const _PLAT_LABELS = window._PLAT_LABELS;

    function openDetailPane(game) {
        _dpCurrentGame   = game;
        _dpCurrentAppid  = game.appid;
        _dpSaveSelection(game.appid);

        // Highlight list row
        document.querySelectorAll('.list-row').forEach(r => r.classList.remove('selected'));
        const row = document.querySelector(`.list-row[data-appid="${game.appid}"]`);
        if (row) {
            row.classList.add('selected');
            const gameList = document.getElementById('game-list');
            if (gameList) {
                const listRect = gameList.getBoundingClientRect();
                const rowRect  = row.getBoundingClientRect();
                const rowH     = row.offsetHeight;
                const listH    = gameList.clientHeight;
                const target   = Math.max(0, gameList.scrollTop + rowRect.top - listRect.top - (listH - rowH) / 2);
                const start    = gameList.scrollTop;
                const dist     = target - start;
                const duration = 1000;
                const t0       = performance.now();
                const step = (now) => {
                    const p    = Math.min((now - t0) / duration, 1);
                    const ease = 1 - Math.pow(1 - p, 3);
                    gameList.scrollTop = start + dist * ease;
                    if (p < 1) requestAnimationFrame(step);
                };
                requestAnimationFrame(step);
            } else {
                row.scrollIntoView({ block: 'nearest' });
            }
        }

        // Vertical cover art (right sidebar)
        const coverEl = document.getElementById('detail-cover-art');
        if (coverEl) {
            coverEl.src = `/static/img/library/vertical/${game.appid}.jpg?v=${_imgV}`;
            coverEl.style.display = '';
            coverEl.onerror = () => { coverEl.style.display = 'none'; };
        }

        // Header
        const iconEl = document.getElementById('detail-header-icon');
        if (iconEl) {
            iconEl.src = `/static/img/library/icons/${game.appid}.jpg?v=${_imgV}`;
            iconEl.onerror = () => { iconEl.style.display = 'none'; };
            iconEl.style.display = '';
        }
        const titleEl = document.getElementById('detail-title');
        if (titleEl) titleEl.textContent = game.name || '';
        const platEl = document.getElementById('detail-plat-badge');
        if (platEl) platEl.textContent = _PLAT_LABELS[game.platform] || game.platform || 'Steam';
        const storeLink = document.getElementById('detail-store-link');
        if (storeLink) {
            if (game.platform === 'steam' || (!game.platform && game.appid >= 0)) {
                storeLink.href = `https://store.steampowered.com/app/${game.appid}/`;
                storeLink.style.display = '';
            } else {
                storeLink.style.display = 'none';
            }
        }

        // Description (load lazily)
        const descText    = document.getElementById('detail-desc-text');
        const descLoading = document.getElementById('detail-desc-loading');
        if (!_dpDescLoaded.has(game.appid)) {
            if (descText)    descText.textContent = '';
            if (descLoading) descLoading.style.display = '';
            _dpLoadDescription(game.appid);
        }

        // Plugin extra-info (load lazily)
        if (!_dpExtraInfoLoaded.has(game.appid)) {
            const extraSection = document.getElementById('detail-extra-info-section');
            const extraList    = document.getElementById('detail-extra-info-list');
            if (extraSection) extraSection.style.display = 'none';
            if (extraList)    extraList.innerHTML = '';
            _dpLoadExtraInfo(game.appid);
        }

        // Form fields
        function dpSet(id, val) {
            const el = document.getElementById(id);
            if (el) el.value = val ?? '';
        }
        dpSet('dp-appid',          game.appid);
        dpSet('dp-name',           game.name);
        dpSet('dp-dev',            game.developers);
        dpSet('dp-pub',            game.publishers);
        dpSet('dp-rel',            game.release_date);
        dpSet('dp-review-score',   game.review_score);
        dpSet('dp-review-pct',     game.review_percentage ?? '');
        dpSet('dp-total-reviews',  game.total_reviews ?? '');
        dpSet('dp-last-played',    game.last_played);
        dpSet('dp-date-added',     game.date_added);
        dpSet('dp-playtime',       game.playtime_forever ?? '');
        dpSet('dp-unlocked-ach',   game.unlocked_achievements ?? '');
        dpSet('dp-total-ach',      game.total_achievements ?? '');

        const isFreeEl    = document.getElementById('dp-is-free');
        const statusEl    = document.getElementById('dp-status');
        const installedEl = document.getElementById('dp-installed');
        if (isFreeEl)    isFreeEl.value    = String(game.is_free ?? 0);
        if (statusEl)    statusEl.value    = game.completion_status || 'Never Played';
        if (installedEl) installedEl.value = String(game.installed ?? 0);

        if (typeof pillInputSet === 'function') {
            pillInputSet('dp-tags',       'dp-tags-box',       game.tags       || '');
            pillInputSet('dp-genres',     'dp-genres-box',     game.genres     || '');
            pillInputSet('dp-categories', 'dp-categories-box', game.categories || '');
            pillInputSet('dp-groups',     'dp-groups-box',     game.groups     || '');
        }

        // Show content
        document.getElementById('detail-empty').style.display   = 'none';
        document.getElementById('detail-content').style.display = 'flex';

        // Reset save button
        const saveBtn = document.getElementById('dp-save-btn');
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save'; }

        _renderListPagQuals(game);
    }

    function _renderListPagQuals(game) {
        const section = document.getElementById('list-pag-quals');
        const list    = document.getElementById('list-pag-quals-list');
        const header  = document.getElementById('list-pag-quals-header');
        if (!section || !list) return;

        const ft = (typeof _serverFilterTree !== 'undefined' ? _serverFilterTree : null);
        const useFilter = ft?.pagywosg;
        const source = useFilter ? null : (window._pagCurrentQuals || null);

        if (!useFilter && !source) { section.style.display = 'none'; return; }

        let conds, verified, sgGroup, monthLabel;
        if (useFilter) {
            conds      = _pagExtractConds(ft);
            verified   = ft.pagywosg_verified;
            sgGroup    = _pagExtractSgGroup(ft);
            monthLabel = _pagEventMonthLabel(ft.pagywosg_event?.id) || 'PAGYWOSG';
        } else {
            conds      = source.conds || [];
            verified   = source.verified || {};
            sgGroup    = source.sg_group || null;
            monthLabel = source.event?.month_label || 'PAGYWOSG';
        }

        if (header) header.textContent = `PAGYWOSG - ${monthLabel} QUALIFICATIONS`;

        const results = _buildPagQualResults(game, conds, verified, sgGroup);
        list.innerHTML = _pagQualResultsHtml(results);
        section.style.display = 'block';
    }

    async function _dpLoadDescription(appid) {
        try {
            const res  = await fetch(`/api/game-description/${appid}`);
            const data = await res.json();
            if (_dpCurrentAppid !== appid) return; // user selected different game
            const descText    = document.getElementById('detail-desc-text');
            const descLoading = document.getElementById('detail-desc-loading');
            if (descLoading) descLoading.style.display = 'none';
            if (descText) {
                descText.textContent = (data.status === 'success' && data.description)
                    ? data.description : '';
            }
            _dpDescLoaded.add(appid);
        } catch (_) {
            const descLoading = document.getElementById('detail-desc-loading');
            if (descLoading) descLoading.style.display = 'none';
        }
    }

    async function _dpLoadExtraInfo(appid) {
        try {
            const res  = await fetch(`/api/game-extra-info/${appid}`);
            const data = await res.json();
            if (_dpCurrentAppid !== appid) return; // user selected different game
            const section = document.getElementById('detail-extra-info-section');
            const list     = document.getElementById('detail-extra-info-list');
            const items = (data.status === 'success' && Array.isArray(data.items)) ? data.items : [];
            if (list) {
                list.innerHTML = items.map(item => {
                    const value = item.url
                        ? `<a href="${escHtml(item.url)}" target="_blank">${escHtml(item.value ?? '')}</a>`
                        : escHtml(item.value ?? '');
                    return `<div class="dp-extra-info-row"><span class="dp-extra-info-label">${escHtml(item.label ?? '')}:</span> <span>${value}</span></div>`;
                }).join('');
            }
            if (section) section.style.display = items.length ? '' : 'none';
            _dpExtraInfoLoaded.add(appid);
        } catch (_) {
            // silently leave the section hidden on failure
        }
    }

    async function dpSaveGame() {
        const appid = _dpCurrentAppid;
        if (!appid) return;

        // The pill hidden inputs are kept in sync by _pillSync; FormData picks them up directly.
        const fd = new FormData(document.getElementById('dp-form'));
        // custom selects emit a hidden input via initCustomSelect; pill hiddens are in the form
        const saveBtn = document.getElementById('dp-save-btn');
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';
        try {
            const res    = await fetch('/update_game', { method: 'POST', body: fd });
            const result = await res.json();
            if (result.status === 'success') {
                _patchGameCard(result.game);
                _patchListRow(result.game);
                _dpCurrentGame = result.game;
                if (result.unique_tags)       { PILL_SUGGESTIONS['dp-tags']       = result.unique_tags;       PILL_SUGGESTIONS['edit-tags']       = result.unique_tags;       }
                if (result.unique_groups)     { PILL_SUGGESTIONS['dp-groups']     = result.unique_groups;     PILL_SUGGESTIONS['edit-groups']     = result.unique_groups;     }
                if (result.unique_genres)     { PILL_SUGGESTIONS['dp-genres']     = result.unique_genres;     PILL_SUGGESTIONS['edit-genres']     = result.unique_genres;     }
                if (result.unique_categories) { PILL_SUGGESTIONS['dp-categories'] = result.unique_categories; PILL_SUGGESTIONS['edit-categories'] = result.unique_categories; }
                saveBtn.textContent = 'Saved ✓';
                setTimeout(() => { saveBtn.disabled = false; saveBtn.textContent = 'Save'; }, 1800);
            } else {
                saveBtn.disabled = false;
                saveBtn.textContent = '✘ ' + (result.message || 'Failed');
                setTimeout(() => { saveBtn.textContent = 'Save'; }, 3000);
            }
        } catch (_) {
            saveBtn.disabled = false;
            saveBtn.textContent = '✘ Network error';
            setTimeout(() => { saveBtn.textContent = 'Save'; }, 3000);
        }
    }

    function dpCancelEdit() {
        if (_dpCurrentGame) openDetailPane(_dpCurrentGame);
    }

    async function dpSyncData() {
        const appid = _dpCurrentAppid;
        if (!appid) return;
        const game    = _dpCurrentGame;
        const platform = game?.platform || 'steam';
        const api     = window._PLUGIN_API?.[platform];
        const btn     = document.querySelector('#detail-footer button[onclick="dpSyncData()"]');
        if (btn) { btn.disabled = true; btn.textContent = 'Syncing...'; }
        const url    = api?.scrape_url ? api.scrape_url.replace('{appid}', appid) : `/api/scrape_single/${appid}`;
        const method = api?.scrape_method || 'GET';
        try {
            const res    = await fetch(url, { method });
            const data   = await res.json();
            if (data.status === 'success' && data.data) {
                const g = data.data;
                if (_dpCurrentAppid === appid) {
                    openDetailPane({ ..._dpCurrentGame, ...g });
                    _dpDescLoaded.delete(appid); // refresh description too
                    _dpExtraInfoLoaded.delete(appid); // refresh plugin extra-info too
                }
                if (btn) { btn.textContent = 'Done'; setTimeout(() => { btn.disabled = false; btn.textContent = 'Sync'; }, 1500); }
            } else if (btn) {
                btn.textContent = data.message || 'Failed';
                setTimeout(() => { btn.disabled = false; btn.textContent = 'Sync'; }, 2500);
            }
        } catch (_) {
            if (btn) { btn.disabled = false; btn.textContent = 'Sync'; }
        }
    }

    async function dpDeleteGame() {
        const appid = _dpCurrentAppid;
        if (!appid) return;
        const name = _dpCurrentGame?.name || `AppID ${appid}`;
        const choice = await confirmDeleteGamePrompt(name);
        if (!choice) return;
        const result = await submitDeleteGame(appid, name, choice.blacklist);
        if (result.success) window.location.reload();
        else alert('Delete failed: ' + result.message);
    }

    function dpOpenArtEditor() {
        const game = _dpCurrentGame;
        if (!game) return;
        openEditModal(game);
    }

    // Keep dp- pill suggestions in sync with edit- suggestions
    document.addEventListener('DOMContentLoaded', function() {
        if (typeof PILL_SUGGESTIONS !== 'undefined') {
            ['tags', 'genres', 'categories', 'groups'].forEach(k => {
                PILL_SUGGESTIONS['dp-' + k] = PILL_SUGGESTIONS['edit-' + k] || [];
            });
        }
        // Init custom selects for detail pane
        ['dp-is-free', 'dp-status', 'dp-installed'].forEach(id => {
            const el = document.getElementById(id);
            if (el && typeof initCustomSelect === 'function') initCustomSelect(el);
        });
    });

    // Handle new cards added during populate in list mode
    document.addEventListener('populate:new_cards', (e) => {
        if (_artOrientation !== 'list') return;
        const listEl = document.getElementById('game-list');
        if (!listEl) return;
        for (const g of e.detail) {
            if (_GAME_MAP.has(g.appid)) continue;
            const gameObj = { appid: g.appid, name: g.name || '', completion_status: g.completion_status || 'Never Played', platform: g.platform || 'steam' };
            GAMES.push(gameObj);
            _GAME_MAP.set(g.appid, gameObj);
            const row = _makeListRow(gameObj);
            listEl.appendChild(row);
            _listObserver?.observe(row);
        }
    });
