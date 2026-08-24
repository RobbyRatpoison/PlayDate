/**
 * playdate.js — shared utilities loaded on every page via base.html
 */

// Safe wrappers for localStorage/sessionStorage — pywebview may not expose them.
const _memLocal   = {};
const _memSession = {};
const safeLocal   = _makeStorage(() => localStorage,   _memLocal);
const safeSession = _makeStorage(() => sessionStorage, _memSession);
function _makeStorage(getter, mem) {
    function _get() { try { return getter(); } catch { return null; } }
    return {
        getItem(k)      { const s = _get(); return s ? s.getItem(k)      : (mem[k] ?? null); },
        setItem(k, v)   { const s = _get(); if (s) s.setItem(k, v);      else mem[k] = v; },
        removeItem(k)   { const s = _get(); if (s) s.removeItem(k);      else delete mem[k]; },
    };
}

// ── Tooltip manager ──────────────────────────────────────────────────────────
(function () {
    const tt = document.createElement('div');
    tt.style.cssText = [
        'position:fixed', 'visibility:hidden', 'opacity:0',
        'background:#1a2233', 'color:#c2c8cc', 'border:1px solid #3a4a5c',
        'border-radius:5px', 'padding:6px 10px', 'font-size:0.75rem',
        'max-width:280px', 'white-space:normal', 'word-wrap:break-word',
        'pointer-events:none', 'z-index:9999', 'transition:opacity 0.15s',
    ].join(';');
    document.addEventListener('DOMContentLoaded', () => document.body.appendChild(tt));

    let _cur = null;

    document.addEventListener('mouseover', function (e) {
        const el = e.target.closest('[data-tooltip]');
        if (!el || !el.dataset.tooltip) return;
        _cur = el;
        tt.textContent = el.dataset.tooltip;
        tt.style.visibility = 'visible';
        requestAnimationFrame(() => {
            if (_cur !== el) return;
            const r  = el.getBoundingClientRect();
            const tw = tt.offsetWidth;
            const th = tt.offsetHeight;
            let top  = r.top - th - 6;
            let left = ('tooltipRight' in el.dataset) ? r.right - tw : r.left;
            if (top < 4)  top  = r.bottom + 6;
            if (left < 4) left = 4;
            if (left + tw > window.innerWidth - 4) left = window.innerWidth - tw - 4;
            tt.style.top  = top  + 'px';
            tt.style.left = left + 'px';
            tt.style.opacity = '1';
        });
    });

    document.addEventListener('mouseout', function (e) {
        const el = e.target.closest('[data-tooltip]');
        if (!el) return;
        if (!el.contains(e.relatedTarget)) {
            _cur = null;
            tt.style.opacity = '0';
            tt.style.visibility = 'hidden';
        }
    });
}());

/** Escape a string for safe insertion into innerHTML. */
function applyBlurArt(img, container, containerRatio) {
    if (!container) return;
    container.style.backgroundImage = `url('${img.src}')`;
    const iw = img.naturalWidth, ih = img.naturalHeight;
    // Use the supplied ratio constant to avoid a forced synchronous layout.
    const cr = containerRatio ?? (container.clientWidth / container.clientHeight);
    const ratioMatch = iw && ih && cr &&
        Math.abs((iw / ih) - cr) / cr < 0.05;
    container.classList.toggle('needs-blur', !ratioMatch);
}

function escHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Format a playtime value (stored as minutes) as a human-readable hours string.
 * e.g. 75 → "1.2 hrs", 12345 → "205.8 hrs"
 */
function fmtHours(minutes) {
    if (!minutes) return '0 hrs';
    const h = minutes / 60;
    const formatted = h >= 1000
        ? h.toLocaleString('en-US', { maximumFractionDigits: 0 })
        : h.toFixed(1);
    return formatted + ' hrs';
}

// ─── SQL Syntax Highlighter ────────────────────────────────────────────────

const _SQL_HL_KEYWORDS = new Set([
    'AND','OR','NOT','IS','NULL','LIKE','IN','BETWEEN','TRUE','FALSE',
    'CASE','WHEN','THEN','ELSE','END','COLLATE','NOCASE',
    'SELECT','FROM','WHERE','ORDER','BY','ASC','DESC','LIMIT','AS','CAST'
]);
const _SQL_HL_COLUMNS = new Set([
    'name','completion_status','tags','groups','installed',
    'release_date','date_added','last_played','playtime_forever',
    'review_percentage','weighted_percentage','review_score',
    'developers','publishers','vertical_art_source','horizontal_art_source',
    'icon_source','unlocked_achievements',
    'total_achievements','appid','positive_reviews','total_reviews'
]);
const _SQL_HL_FUNCTIONS = new Set([
    'LOWER','UPPER','LENGTH','TRIM','SUBSTR','REPLACE','COALESCE',
    'IFNULL','COUNT','MAX','MIN','SUM','AVG','TYPEOF','DATE','STRFTIME'
]);

function _sqlHighlightHtml(sql) {
    if (!sql) return '';
    const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    let out = '', i = 0;
    while (i < sql.length) {
        // Single-quoted string (handle '' escaped quotes)
        if (sql[i] === "'") {
            let j = i + 1;
            while (j < sql.length) {
                if (sql[j] === "'") { j++; if (sql[j] !== "'") break; }
                j++;
            }
            out += `<span class="sql-hl-str">${esc(sql.slice(i, j))}</span>`;
            i = j; continue;
        }
        // Number
        if (/\d/.test(sql[i])) {
            let j = i + 1;
            while (j < sql.length && /[\d.]/.test(sql[j])) j++;
            out += `<span class="sql-hl-num">${esc(sql.slice(i, j))}</span>`;
            i = j; continue;
        }
        // Identifier / keyword / column / function
        if (/[a-zA-Z_]/.test(sql[i])) {
            let j = i + 1;
            while (j < sql.length && /[a-zA-Z0-9_]/.test(sql[j])) j++;
            const word = sql.slice(i, j);
            const up = word.toUpperCase();
            const cls = _SQL_HL_KEYWORDS.has(up)              ? 'sql-hl-kw'
                      : _SQL_HL_COLUMNS.has(word.toLowerCase()) ? 'sql-hl-col'
                      : _SQL_HL_FUNCTIONS.has(up)              ? 'sql-hl-fn'
                      : 'sql-hl-id';
            out += `<span class="${cls}">${esc(word)}</span>`;
            i = j; continue;
        }
        // Two-char operators
        if (i + 1 < sql.length && ['!=','<=','>=','<>','||'].includes(sql.slice(i, i+2))) {
            out += `<span class="sql-hl-op">${esc(sql.slice(i, i+2))}</span>`;
            i += 2; continue;
        }
        // Single-char operators / arithmetic
        if ('<>=!%+-*/'.includes(sql[i])) {
            out += `<span class="sql-hl-op">${esc(sql[i])}</span>`;
            i++; continue;
        }
        // Parentheses
        if ('()'.includes(sql[i])) {
            out += `<span class="sql-hl-paren">${esc(sql[i])}</span>`;
            i++; continue;
        }
        out += esc(sql[i]); i++;
    }
    return out;
}

/**
 * Attach syntax highlighting to an editable textarea.
 * Inserts a <pre> overlay behind the textarea and keeps it in sync.
 * Idempotent — safe to call multiple times on the same element.
 */
function sqlHighlightInit(textarea) {
    if (!textarea || textarea._sqlHlInit) return;
    textarea._sqlHlInit = true;

    const cs = window.getComputedStyle(textarea);

    const wrap = document.createElement('div');
    wrap.className = 'sql-hl-wrap';
    // Transfer background and shape to the wrap so the textarea can go transparent
    wrap.style.background    = cs.backgroundColor;
    wrap.style.borderRadius  = cs.borderRadius;
    wrap.style.width         = '100%';
    wrap.style.boxSizing     = 'border-box';
    textarea.parentNode.insertBefore(wrap, textarea);
    wrap.appendChild(textarea);

    const pre = document.createElement('pre');
    pre.className = 'sql-hl-pre';
    pre.setAttribute('aria-hidden', 'true');
    pre.style.padding    = cs.padding;
    pre.style.fontSize   = cs.fontSize;
    pre.style.fontFamily = cs.fontFamily;
    pre.style.lineHeight = cs.lineHeight;
    wrap.insertBefore(pre, textarea);

    function sync() {
        pre.innerHTML  = _sqlHighlightHtml(textarea.value) + '\n';
        pre.scrollTop  = textarea.scrollTop;
        pre.scrollLeft = textarea.scrollLeft;
    }

    textarea.addEventListener('input',  sync);
    textarea.addEventListener('keyup',  sync);
    textarea.addEventListener('scroll', () => {
        pre.scrollTop  = textarea.scrollTop;
        pre.scrollLeft = textarea.scrollLeft;
    });

    // Keep wrap height matched when the user resizes the textarea
    if (window.ResizeObserver) {
        new ResizeObserver(() => {
            wrap.style.height = textarea.offsetHeight + 'px';
        }).observe(textarea);
    }

    sync();
}

/** Update a read-only <pre> element with syntax-highlighted SQL. */
function sqlHighlightPre(preEl, sql) {
    if (preEl) preEl.innerHTML = _sqlHighlightHtml(sql);
}

/**
 * Recognizes a couple of auto-generated custom_expr SQL shapes (PAGYWOSG's
 * title-word and starts-with name matchers — see pagCondToTree/pagBuildTree
 * in modal_tools.html) and returns a short human-readable description, or
 * null if the SQL doesn't match a known pattern. Mirrors the regexes in
 * _pagExtractConds (modal_edit.html), which extracts the same shapes for the
 * "why does this game qualify" tooltip — kept separate since that function
 * returns structured {col,op,val} data for further evaluation, not a string.
 */
function describeCustomExprSql(sql) {
    if (!sql) return null;
    const titleWordMatch = sql.match(/\(' ' \|\| .*? \|\| ' '\) LIKE '% (.+?) %'$/);
    if (titleWordMatch) return `Title contains the word "${titleWordMatch[1]}"`;
    const startsWithMatch = sql.match(/^(\w+) LIKE '([^']*)%'$/i);
    if (startsWithMatch) {
        const col = startsWithMatch[1] === 'name' ? 'Title' : startsWithMatch[1];
        return `${col} starts with "${startsWithMatch[2]}"`;
    }
    return null;
}

// Fire-and-forget preference save — keepalive survives page navigation
function savePreference(payload) {
    fetch('/api/update_state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        keepalive: true
    }).catch(() => {});
}

async function sendStateUpdate(payload, reload = true) {
    try {
        const response = await fetch('/api/update_state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            if (reload) window.location.reload();
        } else {
            let message = `Server error ${response.status}`;
            try { const d = await response.json(); if (d.message) message = d.message; } catch {}
            showFilterError(message);
        }
    } catch (err) {
        showFilterError('Network error — could not reach the server.');
        console.error('sendStateUpdate failed:', err);
    }
}

// Shared two-step delete confirmation (remove from library, then optionally
// blacklist) used by the edit modal, list-mode detail pane, and the game
// context menu -- all three want the identical prompt/endpoint, just
// different pre/post UI handling around it.
async function confirmDeleteGamePrompt(name) {
    const label = name || 'this game';
    if (!await confirm(`Remove "${label}" from your PlayDate library?\n\nThis deletes the game's database entry and cover image. It will not affect Steam or uninstall the game.`)) {
        return null;
    }
    const blacklist = await confirmCustom(
        `Blacklist "${label}"?\n\n` +
        `Blacklisted games are permanently skipped by "Populate PlayDate" so they won't be re-added to your library in the future.`,
        'Blacklist and Delete',
        'Delete'
    );
    return { blacklist };
}

async function submitDeleteGame(appid, name, blacklist) {
    try {
        const res = await fetch(`/api/delete-game/${appid}`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ blacklist, name })
        });
        const result = await res.json();
        return { success: result.status === 'success', message: result.message };
    } catch (err) {
        return { success: false, message: 'Network error during delete.' };
    }
}

function showFilterError(message) {
    const banner = document.getElementById('filter-error-banner');
    if (!banner) { console.error('Filter/state error:', message); return; }
    banner.textContent = '✘ ' + message;
    banner.style.display = 'block';
    clearTimeout(banner._hideTimer);
    banner._hideTimer = setTimeout(() => { banner.style.display = 'none'; }, 8000);
}

// ── Custom select dropdown ─────────────────────────────────────────────────
/**
 * Replaces a native <select> with a custom div-based dropdown that closes
 * when the window loses focus (fixing the pywebview/WebKit float-over bug).
 *
 * The returned div exposes: .value (get/set), .selectedIndex (get/set),
 * .options (array of proxies), ._setOptions(html), ._addOption(v,t,sel),
 * ._clearOptions(), ._getOption(value). Fires 'change' events on selection.
 */
function initCustomSelect(nativeSelect) {
    if (!nativeSelect) return null;

    function parseFromEl(sel) {
        const items = [];
        for (const child of sel.children) {
            if (child.tagName === 'OPTGROUP') {
                items.push({ type: 'group', label: child.label });
                for (const opt of child.children) {
                    if (opt.tagName === 'OPTION') {
                        items.push({ type: 'opt', value: opt.value, text: opt.text.trim(),
                            disabled: opt.disabled, selected: opt.selected,
                            style: opt.getAttribute('style') || '' });
                    }
                }
            } else if (child.tagName === 'OPTION') {
                items.push({ type: 'opt', value: child.value, text: child.text.trim(),
                    disabled: child.disabled, selected: child.selected,
                    style: child.getAttribute('style') || '' });
            }
        }
        return items;
    }

    let _items = parseFromEl(nativeSelect);
    let _value = nativeSelect.value || _items.find(i => i.type === 'opt')?.value || '';

    const div = document.createElement('div');
    div.id = nativeSelect.id;
    const extraClass = nativeSelect.className.trim();
    div.className = 'custom-select' + (extraClass ? ' ' + extraClass : '');
    if (nativeSelect.getAttribute('style')) div.setAttribute('style', nativeSelect.getAttribute('style'));
    for (const attr of nativeSelect.attributes) {
        if (attr.name.startsWith('data-') || attr.name === 'title') div.setAttribute(attr.name, attr.value);
    }
    div.setAttribute('tabindex', '0');

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'custom-select-btn';

    const panel = document.createElement('div');
    panel.className = 'custom-select-panel';
    panel.style.display = 'none';

    const _hasSearch = _items.filter(i => i.type === 'opt').length > 20;
    let _searchInput = null;
    let _searchQuery = '';
    if (_hasSearch) {
        _searchInput = document.createElement('input');
        _searchInput.type = 'text';
        _searchInput.className = 'custom-select-search';
        _searchInput.placeholder = 'Search…';
        _searchInput.addEventListener('input', () => {
            _searchQuery = _searchInput.value.toLowerCase();
            renderPanel();
        });
        _searchInput.addEventListener('mousedown', e => e.stopPropagation());
        _searchInput.addEventListener('keydown', e => {
            if (e.key === 'Escape') { closePanel(); return; }
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                const visible = Array.from(panel.querySelectorAll('.custom-select-option:not(.hidden):not(.disabled)'));
                if (!visible.length) return;
                const focused = panel.querySelector('.custom-select-option.kb-focus');
                let idx = focused ? visible.indexOf(focused) : -1;
                if (focused) focused.classList.remove('kb-focus');
                idx = e.key === 'ArrowDown' ? Math.min(idx + 1, visible.length - 1) : Math.max(idx - 1, 0);
                visible[idx].classList.add('kb-focus');
                visible[idx].scrollIntoView({ block: 'nearest' });
            }
            if (e.key === 'Enter') {
                const focused = panel.querySelector('.custom-select-option.kb-focus');
                if (focused) focused.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
            }
        });
        panel.appendChild(_searchInput);
    }

    div.appendChild(btn);
    div.appendChild(panel);

    const _opts = () => _items.filter(i => i.type === 'opt');
    const _find = v => _items.find(i => i.type === 'opt' && i.value === String(v));

    function renderBtn() {
        const opt = _find(_value);
        btn.textContent = (opt && opt.text) ? opt.text : '\u00A0';
        if (_hiddenInput) _hiddenInput.value = _value;
    }

    function renderPanel() {
        // Remove all non-search children, keep search input in place
        Array.from(panel.children).forEach(c => { if (c !== _searchInput) c.remove(); });
        if (_opts().length === 0) {
            const d = document.createElement('div');
            d.className = 'custom-select-option disabled';
            d.textContent = '\u00A0';
            panel.appendChild(d);
        }
        _items.forEach(item => {
            if (item.type === 'group') {
                const g = document.createElement('div');
                g.className = 'custom-select-optgroup';
                g.textContent = item.label;
                panel.appendChild(g);
            } else {
                const hidden = _searchQuery && !item.text.toLowerCase().includes(_searchQuery);
                const d = document.createElement('div');
                d.className = 'custom-select-option'
                    + (item.value === _value ? ' selected' : '')
                    + (item.disabled ? ' disabled' : '')
                    + (hidden ? ' hidden' : '');
                d.textContent = item.text;
                if (item.style) d.setAttribute('style', item.style);
                if (!item.disabled) {
                    d.addEventListener('mousedown', e => {
                        e.preventDefault();
                        _value = item.value;
                        _searchQuery = '';
                        if (_searchInput) _searchInput.value = '';
                        renderBtn();
                        renderPanel();
                        closePanel();
                        div.dispatchEvent(new Event('change', { bubbles: true }));
                    });
                }
                panel.appendChild(d);
            }
        });
    }

    function openPanel() {
        document.querySelectorAll('.custom-select.open').forEach(el => {
            if (el !== div) {
                el.classList.remove('open');
                el.querySelector('.custom-select-panel').style.display = 'none';
            }
        });
        div.classList.add('open');
        // Position fixed so the panel escapes overflow:hidden ancestors
        const rect = btn.getBoundingClientRect();
        panel.style.position = 'fixed';
        panel.style.top = rect.bottom + 'px';
        panel.style.left = rect.left + 'px';
        panel.style.width = rect.width + 'px';
        panel.style.display = 'block';
        if (_searchInput) {
            _searchInput.value = '';
            _searchQuery = '';
            renderPanel();
            requestAnimationFrame(() => _searchInput.focus());
        }
    }
    function closePanel() {
        div.classList.remove('open');
        panel.style.display = 'none';
    }

    btn.addEventListener('click', e => {
        e.stopPropagation();
        div.classList.contains('open') ? closePanel() : openPanel();
    });
    // Programmatic / gamepad click lands on the div itself
    div.addEventListener('click', e => { if (e.target === div) btn.click(); });

    Object.defineProperty(div, 'value', {
        get: () => _value,
        set: v => { _value = String(v); renderBtn(); renderPanel(); },
        configurable: true,
    });
    Object.defineProperty(div, 'selectedIndex', {
        get: () => _opts().findIndex(o => o.value === _value),
        set: i => { const o = _opts()[i]; if (o) { _value = o.value; renderBtn(); renderPanel(); } },
        configurable: true,
    });
    Object.defineProperty(div, 'options', {
        get: () => _opts().map(opt => ({
            get value()        { return opt.value; },
            set value(v)       { if (_value === opt.value) _value = String(v); opt.value = String(v); renderBtn(); renderPanel(); },
            get text()         { return opt.text; },
            set text(v)        { opt.text = String(v); renderBtn(); renderPanel(); },
            get textContent()  { return opt.text; },
            set textContent(v) { opt.text = String(v); renderBtn(); renderPanel(); },
            get disabled()     { return opt.disabled; },
            set disabled(v)    { opt.disabled = !!v; renderPanel(); },
            get selected()     { return opt.value === _value; },
            remove()           {
                const idx = _items.indexOf(opt);
                if (idx >= 0) _items.splice(idx, 1);
                if (_value === opt.value) _value = _opts()[0]?.value ?? '';
                renderBtn(); renderPanel();
            },
        })),
        configurable: true,
    });

    div._setOptions = html => {
        const tmp = document.createElement('select');
        tmp.innerHTML = html;
        _items = parseFromEl(tmp);
        const sel = _items.find(i => i.type === 'opt' && i.selected);
        _value = sel?.value ?? _items.find(i => i.type === 'opt')?.value ?? '';
        renderBtn(); renderPanel();
    };
    div._addOption = (value, text, selected = false) => {
        const isFirst = _opts().length === 0;
        _items.push({ type: 'opt', value: String(value), text: String(text), disabled: false, selected, style: '' });
        if (selected || isFirst) _value = String(value);
        renderBtn(); renderPanel();
    };
    div._clearOptions = () => { _items = []; _value = ''; renderBtn(); renderPanel(); };
    div._getOption = value => {
        const opt = _find(value);
        if (!opt) return null;
        return {
            get value()        { return opt.value; },
            set value(v)       { if (_value === opt.value) _value = String(v); opt.value = String(v); renderBtn(); renderPanel(); },
            get textContent()  { return opt.text; },
            set textContent(v) { opt.text = String(v); renderBtn(); renderPanel(); },
            get disabled()     { return opt.disabled; },
            set disabled(v)    { opt.disabled = !!v; renderPanel(); },
            remove()           {
                const idx = _items.indexOf(opt);
                if (idx >= 0) _items.splice(idx, 1);
                if (_value === opt.value) _value = _opts()[0]?.value ?? '';
                renderBtn(); renderPanel();
            },
        };
    };

    if (nativeSelect.onchange) {
        const handler = nativeSelect.onchange;
        div.addEventListener('change', function(e) { handler.call(div, e); });
    }

    // If the native select was a named form field, keep a hidden input so FormData still works
    let _hiddenInput = null;
    if (nativeSelect.name) {
        _hiddenInput = document.createElement('input');
        _hiddenInput.type = 'hidden';
        _hiddenInput.name = nativeSelect.name;
        _hiddenInput.value = _value;
    }

    renderBtn();
    renderPanel();

    if (nativeSelect.parentNode) {
        nativeSelect.parentNode.replaceChild(div, nativeSelect);
        if (_hiddenInput) div.parentNode.insertBefore(_hiddenInput, div.nextSibling);
    }
    return div;
}

// Close all open custom selects when the window loses focus or user clicks outside
function _closeAllCustomSelects(exceptEl) {
    document.querySelectorAll('.custom-select.open').forEach(el => {
        if (el === exceptEl) return;
        el.classList.remove('open');
        const p = el.querySelector('.custom-select-panel');
        if (p) p.style.display = 'none';
    });
}
window.addEventListener('blur', () => _closeAllCustomSelects(null));
function _closeOutsideHandler(e) {
    document.querySelectorAll('.custom-select.open').forEach(el => {
        if (!el.contains(e.target)) {
            el.classList.remove('open');
            const p = el.querySelector('.custom-select-panel');
            if (p) p.style.display = 'none';
        }
    });
}
document.addEventListener('mousedown', _closeOutsideHandler);
document.addEventListener('click', _closeOutsideHandler);

// ─── Custom colour picker ──────────────────────────────────────────────────
// Replaces <input type="color"> which is broken in pywebview/WebKit2GTK.
// Usage: openColorPicker(anchorEl, '#rrggbb', hex => { /* called on change */ })

const _CP_PALETTE = [
    '#FFFFFF','#C7D5E0','#8F98A0','#555555','#222222','#000000',
    '#5BC0DE','#66C0F4','#4A90D9','#1A5C8C','#0D3B5C','#071828',
    '#5CB85C','#5C7E10','#3A7A3A','#1A4A1A','#D9534F','#A32A2A',
    '#F0AD4E','#C97C00','#F5D76E','#E8A020','#9B59B6','#6C3483',
];

let _cpEl = null, _cpOnChange = null, _cpAnchor = null;
let _cpH = 0, _cpS = 1, _cpV = 1; // working HSV state
window._cpEyedropperBusy     = false;  // true while the eyedropper subprocess is running
window._cpEyedropperCooldown = false;  // true for 500ms after it exits (absorbs stale B press)

function _cpRgbToHsv(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
    let h = 0;
    const s = max === 0 ? 0 : d / max, v = max;
    if (d !== 0) {
        switch (max) {
            case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
            case g: h = ((b - r) / d + 2) / 6; break;
            case b: h = ((r - g) / d + 4) / 6; break;
        }
    }
    return [h * 360, s, v];
}

function _cpHsvToRgb(h, s, v) {
    const i = Math.floor(h / 60) % 6;
    const f = h / 60 - Math.floor(h / 60);
    const p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
    const [r, g, b] = [[v,t,p],[q,v,p],[p,v,t],[p,q,v],[t,p,v],[v,p,q]][i];
    return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

function _cpHexToRgb(hex) {
    const h = hex.replace('#', '');
    return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)];
}

function _cpRgbToHex(r, g, b) {
    return '#' + [r, g, b].map(v => Math.round(v).toString(16).padStart(2,'0')).join('');
}

function _cpCurrentHex() {
    const [r, g, b] = _cpHsvToRgb(_cpH, _cpS, _cpV);
    return _cpRgbToHex(r, g, b);
}

function openColorPicker(anchor, currentHex, onChange) {
    closeColorPicker();
    _cpOnChange = onChange;
    _cpAnchor = anchor;

    // Parse initial hex → HSV
    const initHex = /^#[0-9a-fA-F]{6}$/.test((currentHex||'').trim())
        ? currentHex.trim() : '#ff0000';
    const [ir, ig, ib] = _cpHexToRgb(initHex);
    [_cpH, _cpS, _cpV] = _cpRgbToHsv(ir, ig, ib);

    // Slider refs populated after creation; used by _cpFullUpdate closure below.
    let _hueSlider = null, _satSlider = null, _valSlider = null;

    const pop = document.createElement('div');
    pop.id = '_color-picker-popover';
    pop.style.cssText = 'position:fixed;z-index:99999;background:#1b2838;border:1px solid #2a3f55;' +
        'border-radius:0.5rem;padding:0.625rem;box-shadow:0 4px 24px rgba(0,0,0,0.7);' +
        'display:flex;flex-direction:column;gap:0.5rem;width:220px;user-select:none;';

    // ── SV box ────────────────────────────────────────────────────────────
    const svBox = document.createElement('div');
    svBox.style.cssText = 'position:relative;width:100%;height:130px;border-radius:4px;cursor:crosshair;flex-shrink:0;overflow:hidden;';

    const svBg = document.createElement('div');  // hue background
    svBg.style.cssText = 'position:absolute;inset:0;';

    const svWhite = document.createElement('div'); // white→transparent
    svWhite.style.cssText = 'position:absolute;inset:0;background:linear-gradient(to right,#fff,transparent);';

    const svBlack = document.createElement('div'); // transparent→black
    svBlack.style.cssText = 'position:absolute;inset:0;background:linear-gradient(to bottom,transparent,#000);';

    const svCursor = document.createElement('div');
    svCursor.style.cssText = 'position:absolute;width:12px;height:12px;border-radius:50%;' +
        'border:2px solid #fff;box-shadow:0 0 0 1px #000;transform:translate(-50%,-50%);pointer-events:none;';

    svBox.append(svBg, svWhite, svBlack, svCursor);

    function _svUpdateBg() {
        svBg.style.background = `hsl(${_cpH},100%,50%)`;
    }
    function _svUpdateCursor() {
        svCursor.style.left = (_cpS * 100) + '%';
        svCursor.style.top  = ((1 - _cpV) * 100) + '%';
    }

    function _svPick(e) {
        const r = svBox.getBoundingClientRect();
        _cpS = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
        _cpV = Math.max(0, Math.min(1, 1 - (e.clientY - r.top) / r.height));
        _svUpdateCursor();
        if (_satSlider) _satSlider.value = Math.round(_cpS * 100);
        if (_valSlider) _valSlider.value = Math.round(_cpV * 100);
        _cpEmit();
    }
    let _svDrag = false;
    svBox.addEventListener('mousedown', e => { e.preventDefault(); _svDrag = true; _svPick(e); });
    document.addEventListener('mousemove', e => { if (_svDrag) _svPick(e); });
    document.addEventListener('mouseup',   () => { _svDrag = false; });

    pop.appendChild(svBox);

    // ── Hue slider ────────────────────────────────────────────────────────
    const hueTrack = document.createElement('div');
    hueTrack.style.cssText = 'position:relative;height:12px;border-radius:6px;cursor:pointer;flex-shrink:0;' +
        'background:linear-gradient(to right,#f00,#ff0,#0f0,#0ff,#00f,#f0f,#f00);';

    const hueThumb = document.createElement('div');
    hueThumb.style.cssText = 'position:absolute;top:50%;width:14px;height:14px;border-radius:50%;' +
        'border:2px solid #fff;box-shadow:0 0 0 1px #000;transform:translate(-50%,-50%);pointer-events:none;';
    hueTrack.appendChild(hueThumb);

    function _hueUpdateThumb() {
        hueThumb.style.left = (_cpH / 360 * 100) + '%';
    }
    function _huePick(e) {
        const r = hueTrack.getBoundingClientRect();
        _cpH = Math.max(0, Math.min(360, (e.clientX - r.left) / r.width * 360));
        _hueUpdateThumb();
        _svUpdateBg();
        if (_hueSlider) _hueSlider.value = Math.round(_cpH);
        _cpEmit();
    }
    let _hueDrag = false;
    hueTrack.addEventListener('mousedown', e => { e.preventDefault(); _hueDrag = true; _huePick(e); });
    document.addEventListener('mousemove', e => { if (_hueDrag) _huePick(e); });
    document.addEventListener('mouseup',   () => { _hueDrag = false; });

    pop.appendChild(hueTrack);

    // ── H / S / V sliders (gamepad-navigable) ────────────────────────────
    const hsvSection = document.createElement('div');
    hsvSection.style.cssText = 'display:flex;flex-direction:column;gap:4px;';
    const _sliderRowStyle = 'display:flex;align-items:center;gap:6px;';
    const _sliderLblStyle = 'width:10px;font-size:0.72rem;color:#8f98a0;flex-shrink:0;text-align:right;font-family:monospace;';
    const _sliderStyle    = 'flex:1;cursor:pointer;';
    function _cpSliderFill(sl) {
        const pct = (sl.value - sl.min) / (sl.max - sl.min) * 100;
        sl.style.setProperty('--slider-pct', pct.toFixed(1) + '%');
    }
    [[0, 'H', 0, 360], [1, 'S', 0, 100], [2, 'V', 0, 100]].forEach(([row, lbl, min, max]) => {
        const r = document.createElement('div');
        r.style.cssText = _sliderRowStyle;
        const l = document.createElement('span');
        l.textContent = lbl;
        l.style.cssText = _sliderLblStyle;
        const sl = document.createElement('input');
        sl.type = 'range'; sl.min = min; sl.max = max; sl.step = '1';
        sl.dataset.modalRow = row;
        sl.style.cssText = _sliderStyle;
        if (lbl === 'H') { _hueSlider = sl; sl.value = Math.round(_cpH); sl.addEventListener('input', () => { _cpH = +sl.value; _cpSliderFill(sl); _svUpdateBg(); _hueUpdateThumb(); _cpEmit(); }); }
        if (lbl === 'S') { _satSlider = sl; sl.value = Math.round(_cpS * 100); sl.addEventListener('input', () => { _cpS = sl.value / 100; _cpSliderFill(sl); _svUpdateCursor(); _cpEmit(); }); }
        if (lbl === 'V') { _valSlider = sl; sl.value = Math.round(_cpV * 100); sl.addEventListener('input', () => { _cpV = sl.value / 100; _cpSliderFill(sl); _svUpdateCursor(); _cpEmit(); }); }
        _cpSliderFill(sl);
        r.append(l, sl);
        hsvSection.appendChild(r);
    });
    pop.appendChild(hsvSection);

    // ── Bottom row: eyedropper + preview + hex ────────────────────────────
    const bottomRow = document.createElement('div');
    bottomRow.style.cssText = 'display:flex;align-items:center;gap:0.375rem;';

    const dropBtn = document.createElement('button');
    dropBtn.title = 'Pick colour from screen';
    dropBtn.dataset.modalRow = 3;
    dropBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 22l5-5M14.5 2.5l7 7-10 10-7-7 10-10z"/><path d="M7 17l-5 5"/></svg>';
    dropBtn.style.cssText = 'width:2rem;height:2rem;flex-shrink:0;background:#2a3f55;border:1px solid #3a5f7a;' +
        'color:#c7d5e0;border-radius:0.25rem;cursor:pointer;font-size:1rem;line-height:1;padding:0;display:flex;align-items:center;justify-content:center;';
    dropBtn.addEventListener('click', async e => {
        e.stopPropagation();
        if ('EyeDropper' in window) {
            try {
                const result = await new EyeDropper().open();
                const hex = result.sRGBHex;
                const [r, g, b] = _cpHexToRgb(hex);
                [_cpH, _cpS, _cpV] = _cpRgbToHsv(r, g, b);
                _cpFullUpdate();
            } catch (_) {}
            return;
        }
        // Fallback: ask Python backend to open native system color dialog.
        // Hide all visible modals and the colour picker popup so the screenshot
        // shows the clean app window behind them.
        window._cpEyedropperBusy = true;
        const _hidden = [];
        document.querySelectorAll('.modal-overlay').forEach(el => {
            if (el.style.display !== 'none') {
                _hidden.push({ el, display: el.style.display });
                el.style.display = 'none';
            }
        });
        const _cpPopEl = document.getElementById('_color-picker-popover');
        if (_cpPopEl) { _cpPopEl.style.visibility = 'hidden'; }
        // Wait two frames so pywebview repaints before the subprocess grabs the screen.
        await new Promise(res => requestAnimationFrame(() => requestAnimationFrame(res)));
        let _pickedColor = null;
        try {
            const resp = await fetch('/api/pick-screen-color');
            if (resp.ok) {
                const data = await resp.json();
                if (data.color) _pickedColor = data.color;
            }
        } catch (_) {}
        window._cpEyedropperBusy = false;
        window._cpEyedropperCooldown = true;
        setTimeout(() => { window._cpEyedropperCooldown = false; }, 500);
        // Restore hidden elements to their exact previous display value.
        _hidden.forEach(({ el, display }) => { el.style.display = display; });
        if (_cpPopEl) { _cpPopEl.style.visibility = ''; }
        if (_pickedColor) {
            const [r, g, b] = _cpHexToRgb(_pickedColor);
            [_cpH, _cpS, _cpV] = _cpRgbToHsv(r, g, b);
            _cpFullUpdate();
        }
        // Re-enter modal zone so gamepad focus returns to the color picker.
        if (typeof window._gpRefocusModal === 'function') window._gpRefocusModal();
    });
    bottomRow.appendChild(dropBtn);

    const preview = document.createElement('div');
    preview.style.cssText = 'width:2rem;height:2rem;flex-shrink:0;border-radius:0.25rem;border:1px solid #444;';

    const hexInput = document.createElement('input');
    hexInput.type = 'text';
    hexInput.maxLength = 7;
    hexInput.dataset.modalRow = 3;
    hexInput.style.cssText = 'flex:1;height:2rem;background:#101822;border:1px solid #2a3f55;color:#fff;' +
        'border-radius:0.25rem;font-size:0.82rem;padding:0 0.375rem;font-family:monospace;min-width:0;';
    hexInput.addEventListener('input', () => {
        let v = hexInput.value.trim();
        if (!v.startsWith('#')) v = '#' + v;
        if (/^#[0-9a-fA-F]{6}$/.test(v)) {
            const [r, g, b] = _cpHexToRgb(v);
            [_cpH, _cpS, _cpV] = _cpRgbToHsv(r, g, b);
            _svUpdateBg(); _svUpdateCursor(); _hueUpdateThumb();
            if (_hueSlider) _hueSlider.value = Math.round(_cpH);
            if (_satSlider) _satSlider.value = Math.round(_cpS * 100);
            if (_valSlider) _valSlider.value = Math.round(_cpV * 100);
            preview.style.background = v;
            _cpOnChange && _cpOnChange(v);
        }
    });
    hexInput.addEventListener('keydown', e => { if (e.key === 'Enter') closeColorPicker(); });

    bottomRow.append(preview, hexInput);
    pop.appendChild(bottomRow);

    // ── Palette ───────────────────────────────────────────────────────────
    const palette = document.createElement('div');
    palette.style.cssText = 'display:grid;grid-template-columns:repeat(6,1fr);gap:3px;';
    _CP_PALETTE.forEach((hex, idx) => {
        const sw = document.createElement('div');
        sw.dataset.modalRow = 4 + Math.floor(idx / 6);
        sw.style.cssText = `aspect-ratio:1;border-radius:3px;background:${hex};cursor:pointer;` +
            'border:1px solid rgba(255,255,255,0.1);box-sizing:border-box;';
        sw.title = hex;
        sw.addEventListener('mousedown', e => e.stopPropagation());
        sw.addEventListener('click', e => {
            e.stopPropagation();
            const [r, g, b] = _cpHexToRgb(hex);
            [_cpH, _cpS, _cpV] = _cpRgbToHsv(r, g, b);
            _cpFullUpdate();
        });
        palette.appendChild(sw);
    });
    pop.appendChild(palette);

    // ── Done button ───────────────────────────────────────────────────────
    const doneBtn = document.createElement('button');
    doneBtn.textContent = 'Done';
    doneBtn.dataset.modalRow = 8;
    doneBtn.style.cssText = 'width:100%;padding:5px 0;background:#2a3f55;border:1px solid #3a5f7a;' +
        'color:#c7d5e0;border-radius:0.25rem;cursor:pointer;font-size:0.8rem;';
    doneBtn.addEventListener('click', closeColorPicker);
    pop.appendChild(doneBtn);

    document.body.appendChild(pop);
    _cpEl = pop;

    function _cpEmit() {
        const hex = _cpCurrentHex();
        preview.style.background = hex;
        hexInput.value = hex.toUpperCase();
        _cpOnChange && _cpOnChange(hex);
    }

    function _cpFullUpdate() {
        _svUpdateBg(); _svUpdateCursor(); _hueUpdateThumb();
        if (_hueSlider) { _hueSlider.value = Math.round(_cpH); _cpSliderFill(_hueSlider); }
        if (_satSlider) { _satSlider.value = Math.round(_cpS * 100); _cpSliderFill(_satSlider); }
        if (_valSlider) { _valSlider.value = Math.round(_cpV * 100); _cpSliderFill(_valSlider); }
        _cpEmit();
    }

    // Initial render
    _svUpdateBg(); _svUpdateCursor(); _hueUpdateThumb();
    const initOut = _cpCurrentHex();
    preview.style.background = initOut;
    hexInput.value = initOut.toUpperCase();

    // Position
    const rect = anchor.getBoundingClientRect();
    const popW = 220, popH = 280;
    let top = rect.bottom + 4, left = rect.left;
    if (left + popW > window.innerWidth - 8) left = window.innerWidth - popW - 8;
    if (left < 8) left = 8;
    if (top + popH > window.innerHeight - 8) top = rect.top - popH - 4;
    pop.style.top = top + 'px';
    pop.style.left = left + 'px';

    hexInput.focus(); hexInput.select();

    setTimeout(() => {
        document.addEventListener('mousedown', _cpOutside, { capture: true });
    }, 0);
}

function closeColorPicker() {
    if (window._cpEyedropperBusy) return;
    if (_cpEl) { _cpEl.remove(); _cpEl = null; }
    document.removeEventListener('mousedown', _cpOutside, { capture: true });
}

function _cpOutside(e) {
    if (_cpEl && !_cpEl.contains(e.target) && e.target !== _cpAnchor) {
        closeColorPicker();
    }
}

