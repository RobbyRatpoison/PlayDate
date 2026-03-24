/**
 * playdate.js — shared utilities loaded on every page via base.html
 */

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

function showFilterError(message) {
    const banner = document.getElementById('filter-error-banner');
    if (!banner) { console.error('Filter/state error:', message); return; }
    banner.textContent = '✘ ' + message;
    banner.style.display = 'block';
    clearTimeout(banner._hideTimer);
    banner._hideTimer = setTimeout(() => { banner.style.display = 'none'; }, 8000);
}
