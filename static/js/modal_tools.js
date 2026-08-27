// ── MODAL HELPERS ───────────────────────────────────────────────────────────
function _bgOpacityInput(val) {
    const num = parseFloat(val);
    document.documentElement.style.setProperty('--bg-image-opacity', num);
    document.getElementById('bg-opacity-val').textContent = Math.round(num * 100) + '%';
    const slider = document.getElementById('bg-opacity-slider');
    slider.style.setProperty('--slider-pct', (num * 100) + '%');
}

function openBgModal() {
    document.getElementById('bg-modal').style.display = 'flex';
    const cur = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bg-image-opacity')) || 1;
    const slider = document.getElementById('bg-opacity-slider');
    slider.value = cur;
    slider.style.setProperty('--slider-pct', (cur * 100) + '%');
    document.getElementById('bg-opacity-val').textContent = Math.round(cur * 100) + '%';
}
function closeBgModal() {
    document.getElementById('bg-modal').style.display = 'none';
    document.getElementById('bg-status').textContent = '';
    document.getElementById('bg-filename').style.display = 'none';
    document.getElementById('bg-filename').textContent = '';
    const btn = document.getElementById('bg-upload-btn');
    btn.textContent = 'Save';
    document.getElementById('bg-file-input').value = '';
    _hideBgPreview();
    _bgFile = null;
    _bgFilePath = null;
}

function openBackupModal() {
    document.getElementById('backup-modal').style.display = 'flex';
    setBackupTab('backup');
}
function closeBackupModal() {
    document.getElementById('backup-modal').style.display = 'none';
    document.getElementById('backup-status').textContent = '';
    document.getElementById('restore-status').textContent = '';
    _restoreFile = null;
    _restorePath = null;
    document.getElementById('restore-filename').style.display = 'none';
    const rbtn = document.getElementById('restore-btn');
    rbtn.style.opacity = '0.4';
    rbtn.style.cursor  = 'not-allowed';
    rbtn.textContent   = 'Restore';
}

function setBackupTab(tab) {
    const isBackup = tab === 'backup';
    document.getElementById('backup-tab').style.display    = isBackup ? '' : 'none';
    document.getElementById('restore-tab').style.display   = isBackup ? 'none' : '';
    document.getElementById('backup-tab-btn').style.background  = isBackup ? 'var(--accent)' : 'transparent';
    document.getElementById('backup-tab-btn').style.color        = isBackup ? 'var(--on-accent)' : 'var(--text-secondary)';
    document.getElementById('restore-tab-btn').style.background  = isBackup ? 'transparent' : 'var(--accent)';
    document.getElementById('restore-tab-btn').style.color       = isBackup ? 'var(--text-secondary)' : 'var(--on-accent)';
}

function openSendLogModal() {
    document.getElementById('send-log-modal').style.display = 'flex';
}
function closeSendLogModal() {
    document.getElementById('send-log-modal').style.display = 'none';
    document.getElementById('send-log-message').value = '';
    document.getElementById('send-log-status').textContent = '';
    document.getElementById('send-log-status').className = 'tool-status';
}

function submitLog() {
    const btn     = document.getElementById('send-log-btn');
    const status  = document.getElementById('send-log-status');
    const message = document.getElementById('send-log-message').value;

    btn.disabled = true;
    btn.textContent = 'Sending…';
    status.className = 'tool-status info';
    status.textContent = 'Sending log…';

    fetch('/api/submit-log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message })
    })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            if (!ok || data.status !== 'success') throw new Error(data.message || 'Unknown error');
            status.className = 'tool-status success';
            status.textContent = '✔ Log sent. Thanks for the report!';
            document.getElementById('send-log-message').value = '';
        })
        .catch(err => {
            status.className = 'tool-status error';
            const msg = err.message || 'Something went wrong.';
            status.textContent = `✘ ${msg}${/try again|wait \d/i.test(msg) ? '' : ' Please try again.'}`;
        })
        .finally(() => {
            btn.disabled = false;
            btn.textContent = 'Send Log';
        });
}

function openImportModal() {
    document.getElementById('import-modal').style.display = 'flex';
    resetImport();
}
function closeImportModal() {
    document.getElementById('import-modal').style.display = 'none';
    resetImport();
}

function openPlayniteModal() {
    document.getElementById('playnite-modal').style.display = 'flex';
    document.getElementById('playnite-status').textContent = '';
    document.getElementById('playnite-status').className = 'tool-status';
}
function closePlayniteModal() {
    document.getElementById('playnite-modal').style.display = 'none';
}
async function runPlayniteImport() {
    if (_fileDlgBusy) return;
    _fileDlgBusy = true;
    const status = document.getElementById('playnite-status');
    status.className = 'tool-status info';
    status.textContent = 'Opening file dialog...';
    let path = null;
    try {
        path = await window.pywebview.api.pick_open_path(['ZIP Files (*.zip)']);
    } catch (e) {
        status.textContent = `Error opening file dialog: ${e.message}`;
        status.className = 'tool-status error';
        setTimeout(() => { _fileDlgBusy = false; }, 300);
        return;
    }
    setTimeout(() => { _fileDlgBusy = false; }, 300);
    if (!path) {
        status.textContent = '';
        return;
    }
    status.textContent = 'Parsing backup...';
    try {
        const res = await fetch('/api/import/playnite-dates', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ path }),
        });
        const started = await res.json();
        if (started.status !== 'started') throw new Error(started.message || 'Import failed.');

        // Parsing runs in a background thread server-side (Playnite backups
        // can be several GB) — poll for completion.
        let data;
        while (true) {
            await new Promise(r => setTimeout(r, 700));
            const poll = await fetch('/api/import/playnite-dates-status');
            data = await poll.json();
            if (data.status !== 'running') break;
        }

        if (data.status === 'success') {
            status.textContent = `Done — updated ${data.updated} game${data.updated !== 1 ? 's' : ''} (${data.found} Steam games found in backup).`;
            status.className = 'tool-status success';
        } else {
            status.textContent = `Error: ${data.error}`;
            status.className = 'tool-status error';
        }
    } catch (e) {
        status.textContent = `Error: ${e.name}: ${e.message}`;
        status.className = 'tool-status error';
    }
}

// ── BLAEO ──
let _blaeoHasPreview = false;

async function runBlaeo() {
    const btn    = document.getElementById('blaeo-btn');
    const status = document.getElementById('blaeo-status');
    btn.disabled = true;
    document.getElementById('blaeo-actions').style.display = 'none';
    _blaeoHasPreview = false;
    status.className = 'tool-status info';
    status.textContent = 'Starting BLAEO sync...';
    try {
        const res  = await fetch('/api/blaeo-start', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'started') {
            _hideBlaeoNotification();
            status.textContent = 'Syncing in background — results will load here when done.';
            document.dispatchEvent(new CustomEvent('blaeo:started'));
        } else if (data.status === 'running') {
            status.textContent = 'BLAEO sync already in progress...';
        } else if (data.status === 'pending') {
            status.textContent = 'Loading results...';
            await _loadBlaeoPreview();
        } else {
            status.className = 'tool-status error';
            status.textContent = '✘ ' + (data.message || 'Failed to start sync.');
        }
    } catch (e) {
        status.className = 'tool-status error';
        status.textContent = '✘ Network error.';
    } finally {
        btn.disabled = false;
    }
}

async function _loadBlaeoPreview() {
    const status  = document.getElementById('blaeo-status');
    const actions = document.getElementById('blaeo-actions');
    _blaeoHasPreview = false;
    actions.style.display = 'none';
    try {
        const res  = await fetch('/api/blaeo-preview');
        const data = await res.json();
        if (data.status === 'success') {
            const sc        = data.status_changes || [];
            const renames   = data.renames || [];
            const additions = data.additions || [];
            const removals  = data.removals || [];
            const total = sc.length + renames.length + additions.length + removals.length;
            if (total === 0) {
                status.className = 'tool-status success';
                status.innerHTML = '<div>&#x2714; Nothing to update.</div>';
                fetch('/api/blaeo-discard', { method: 'POST' }).catch(() => {});
            } else {
                status.className = 'tool-status info';
                let html = `<div style="margin-bottom:6px;">Review ${total} proposed change${total !== 1 ? 's' : ''}:</div>`;
                html += _blaeoPreviewSection('sc',  sc,        'status change',  'status changes',
                    c => `<input type="checkbox" checked data-btype="status" data-appid="${c.appid}"> <label>${escHtml(c.name)}: ${escHtml(c.from)} &#x2192; ${escHtml(c.to)}</label>`);
                html += _blaeoPreviewSection('rn',  renames,   'group rename',   'group renames',
                    r => `<input type="checkbox" checked data-btype="rename" data-from="${escHtml(r.from)}" data-to="${escHtml(r.to)}"> <label>&#x201C;${escHtml(r.from)}&#x201D; &#x2192; &#x201C;${escHtml(r.to)}&#x201D;</label>`);
                html += _blaeoPreviewSection('add', additions, 'group addition', 'group additions',
                    a => `<input type="checkbox" checked data-btype="add" data-appid="${a.appid}"> <label>${escHtml(a.name)}: added to ${a.list_names.map(l => `&#x201C;${escHtml(l)}&#x201D;`).join(', ')}</label>`);
                html += _blaeoPreviewSection('rm',  removals,  'group removal',  'group removals',
                    r => `<input type="checkbox" checked data-btype="rem" data-appid="${r.appid}" data-listname="${escHtml(r.list_name)}"> <label>${escHtml(r.name)}: removed from &#x201C;${escHtml(r.list_name)}&#x201D;</label>`);
                status.innerHTML = html;
                _blaeoHasPreview = true;
                actions.style.display = 'flex';
            }
        } else {
            status.className = 'tool-status error';
            status.textContent = '✘ ' + (data.message || 'Sync failed. Check the log.');
        }
    } catch (e) {
        status.className = 'tool-status error';
        status.textContent = '✘ Network error.';
    }
}

function _blaeoPreviewSection(key, items, singular, plural, rowFn) {
    if (!items.length) return '';
    const uid   = 'blaeo-' + key + '-' + Date.now();
    const label = items.length === 1 ? `1 ${singular}` : `${items.length} ${plural}s`;
    let html = `<div class="blaeo-preview-section">`;
    html += `<div class="blaeo-section-header">`;
    html += `<span class="blaeo-toggle" onclick="var d=document.getElementById('${uid}');d.style.display=d.style.display==='none'?'':'none'">${label} &#x25BE;</span>`;
    html += ` <span class="blaeo-select-links">(<span onclick="_blaeoSetAll('${uid}',true)">all</span> / <span onclick="_blaeoSetAll('${uid}',false)">none</span>)</span>`;
    html += `</div>`;
    html += `<div id="${uid}">`;
    items.forEach(item => { html += `<div class="blaeo-item blaeo-details">${rowFn(item)}</div>`; });
    html += '</div></div>';
    return html;
}

function _blaeoSetAll(containerId, checked) {
    document.getElementById(containerId).querySelectorAll('input[type=checkbox]').forEach(cb => { cb.checked = checked; });
}

async function applyBlaeo() {
    if (!_blaeoHasPreview) return;
    const applyBtn  = document.getElementById('blaeo-apply-btn');
    const cancelBtn = document.getElementById('blaeo-cancel-btn');
    const actions   = document.getElementById('blaeo-actions');
    const statusDiv = document.getElementById('blaeo-status');

    const accept_status    = [];
    const accept_additions = [];
    const accept_removals  = [];
    const accept_renames   = [];
    statusDiv.querySelectorAll('input[type=checkbox]:checked').forEach(cb => {
        const t = cb.dataset.btype;
        if      (t === 'status') accept_status.push(parseInt(cb.dataset.appid));
        else if (t === 'add')    accept_additions.push(parseInt(cb.dataset.appid));
        else if (t === 'rem')    accept_removals.push({appid: parseInt(cb.dataset.appid), list_name: cb.dataset.listname});
        else if (t === 'rename') accept_renames.push({from: cb.dataset.from, to: cb.dataset.to});
    });

    _blaeoHasPreview = false;
    actions.style.display = 'none';
    applyBtn.disabled = true;
    cancelBtn.disabled = true;
    statusDiv.className = 'tool-status info';
    statusDiv.textContent = 'Applying...';

    try {
        const res  = await fetch('/api/blaeo-apply', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({accept_status, accept_additions, accept_removals, accept_renames})
        });
        const data = await res.json();
        if (data.status === 'success') {
            statusDiv.className = 'tool-status success';
            statusDiv.innerHTML = _blaeoResultHtml(data);
            if (typeof _hideBlaeoNotification === 'function') _hideBlaeoNotification();
        } else {
            statusDiv.className = 'tool-status error';
            statusDiv.textContent = '&#x2718; ' + (data.message || 'Apply failed. Check the log.');
        }
    } catch (e) {
        statusDiv.className = 'tool-status error';
        statusDiv.textContent = '&#x2718; Network error.';
    } finally {
        applyBtn.disabled = false;
        cancelBtn.disabled = false;
    }
}

function cancelBlaeo() {
    _blaeoHasPreview = false;
    document.getElementById('blaeo-actions').style.display = 'none';
    const s = document.getElementById('blaeo-status');
    s.className = 'tool-status';
    s.innerHTML = '';
    fetch('/api/blaeo-discard', { method: 'POST' }).catch(() => {});
    if (typeof _hideBlaeoNotification === 'function') _hideBlaeoNotification();
}

function _blaeoResultHtml(data) {
    const sc        = data.status_changes || [];
    const renames   = data.renames || [];
    const additions = data.additions || [];
    const removals  = data.removals || [];
    if (!data.updated && !sc.length && !renames.length && !additions.length && !removals.length) {
        return '<div>&#x2714; Nothing applied.</div>';
    }
    let html = `<div>&#x2714; Applied &#x2014; ${data.updated} game${data.updated !== 1 ? 's' : ''} updated.</div>`;
    if (sc.length) {
        const grouped = {};
        sc.forEach(c => {
            const key = c.from + '|' + c.to;
            if (!grouped[key]) grouped[key] = {from: c.from, to: c.to, names: []};
            grouped[key].names.push(c.name);
        });
        const uid = 'blaeo-r-sc-' + Date.now();
        html += `<div><span class="blaeo-toggle" onclick="var d=document.getElementById('${uid}');d.style.display=d.style.display==='none'?'':'none'">${sc.length} status change${sc.length !== 1 ? 's' : ''} &#x25BE;</span>`;
        html += `<div id="${uid}" class="blaeo-details" style="display:none">`;
        Object.values(grouped).forEach(g => {
            html += `<div>${escHtml(g.from)} &#x2192; ${escHtml(g.to)} (${g.names.length}): ${g.names.map(n => escHtml(n)).join(', ')}</div>`;
        });
        html += '</div></div>';
    }
    if (renames.length) {
        const uid = 'blaeo-r-rn-' + Date.now();
        html += `<div><span class="blaeo-toggle" onclick="var d=document.getElementById('${uid}');d.style.display=d.style.display==='none'?'':'none'">${renames.length} group${renames.length !== 1 ? 's' : ''} renamed &#x25BE;</span>`;
        html += `<div id="${uid}" class="blaeo-details" style="display:none">`;
        renames.forEach(r => { html += `<div>&#x201C;${escHtml(r.from)}&#x201D; &#x2192; &#x201C;${escHtml(r.to)}&#x201D;</div>`; });
        html += '</div></div>';
    }
    if (additions.length) {
        const uid = 'blaeo-r-ad-' + Date.now();
        html += `<div><span class="blaeo-toggle" onclick="var d=document.getElementById('${uid}');d.style.display=d.style.display==='none'?'':'none'">${additions.length} group addition${additions.length !== 1 ? 's' : ''} &#x25BE;</span>`;
        html += `<div id="${uid}" class="blaeo-details" style="display:none">`;
        additions.forEach(a => { html += `<div>${escHtml(a.name)}: added to ${a.list_names.map(l => `&#x201C;${escHtml(l)}&#x201D;`).join(', ')}</div>`; });
        html += '</div></div>';
    }
    if (removals.length) {
        const uid = 'blaeo-r-rm-' + Date.now();
        html += `<div><span class="blaeo-toggle" onclick="var d=document.getElementById('${uid}');d.style.display=d.style.display==='none'?'':'none'">${removals.length} group removal${removals.length !== 1 ? 's' : ''} &#x25BE;</span>`;
        html += `<div id="${uid}" class="blaeo-details" style="display:none">`;
        removals.forEach(r => { html += `<div>${escHtml(r.name)}: removed from &#x201C;${escHtml(r.list_name)}&#x201D;</div>`; });
        html += '</div></div>';
    }
    return html;
}

// ── PAGYWOSG ──
let _pagAllTags = [];
let _pagWinsTags = [];
let _pagSelectedAll = new Set();
let _pagSelectedWins = new Set();
let _pagAllAppids  = [];
let _pagWinsAppids = [];
let _pagAllAppidSources  = [];  // [{label, appids}]
let _pagWinsAppidSources = [];
let _pagAllGames   = [];   // [{appid, name, categories}]
let _pagWinsGames  = [];
let _pagEventId    = null;
let _pagEventName  = '';
// _pagSgGroup: string = chosen wins group name; null = no SG wins (omit wins branch); undefined = not yet loaded
let _pagSgGroup    = undefined;
let _pagAllGroups  = [];  // all distinct groups in the library
let _pagPersonalCats = new Set();  // category names marked as personal (auto=true when saving)
let _pagPersonalCandidates = [];   // category names with zero verified appids so far (e.g. upcoming event) that could still become personal

// Columns available for the condition builder
const PAG_COLUMNS = [
    { value: 'name',            label: 'Title' },
    { value: 'release_date',    label: 'Release Date' },
    { value: 'appid',           label: 'AppID' },
    { value: 'developers',      label: 'Developer' },
    { value: 'publishers',      label: 'Publisher' },
    { value: 'playtime_forever',label: 'Playtime (mins)' },
    { value: 'review_score',    label: 'Review Score' },
    { value: 'review_percentage', label: 'Review %' },
    { value: 'groups',          label: 'Groups' },
    { value: 'tags',            label: 'Tags' },
    { value: 'hltb_main',          label: 'HLTB Main (mins)' },
    { value: 'hltb_extras',        label: 'HLTB Main+Extras (mins)' },
    { value: 'hltb_completionist', label: 'HLTB Completionist (mins)' },
];
// Op vocabulary (tree tokens, SQL "kind", dropdown labels) is defined once in
// pagywosg.py's OP_REGISTRY and injected as window._PAG_OPS — these two lists
// just fix the display order for each dropdown context.
const _PAG_OPS_ORDER      = ['contains', 'not_contains', 'equals', 'starts_with', 'ends_with', 'gt', 'lt', 'gte', 'title_word', 'length_eq', 'digit_count_gte', 'consecutive_repeat', 'has_special_char', 'range_incl', 'all_caps', 'contains_all', 'tag_substring', 'tag_count_eq', 'single_word'];
const _PAG_DATE_OPS_ORDER = ['month_is', 'day_is', 'year_is', 'weekday_is', 'gt', 'lt', 'equals', 'nth_weekday'];
const PAG_OPS = _PAG_OPS_ORDER.map(v => ({ value: v, label: window._PAG_OPS[v].manual_ui.general.label }));
// Normalises punctuation to spaces so word-boundary LIKE matches work across subtitles, etc.
const _PAG_TITLE_NORM = "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(name), ':', ' '), '!', ' '), '?', ' '), ',', ' '), '.', ' '), '''', ' '), '(', ' '), ')', ' '), '[', ' '), ']', ' '), '{', ' '), '}', ' '), ';', ' '), '\"', ' ')";
const PAG_DATE_OPS = _PAG_DATE_OPS_ORDER.map(v => ({ value: v, label: window._PAG_OPS[v].manual_ui.date.label }));
const PAG_DATE_COLUMNS = new Set(['release_date', 'date_added', 'last_played']);

function openPagModal() {
    document.getElementById('pagywosg-modal').style.display = 'flex';
    if (!_pagAllTags.length) pagInit();
    _pagRefreshSantaGifts();
    _pagPopulateRefreshSelect();
}

function _pagPopulateRefreshSelect() {
    const sel = document.getElementById('pag-refresh-select');
    if (!sel || !sel._setOptions) return;
    const names = Object.keys(_savedFilters).filter(n => {
        const entry = _savedFilters[n];
        const tree  = (entry && typeof entry === 'object' && 'tree' in entry) ? entry.tree : entry;
        return tree && tree.pagywosg === true;
    });
    sel._setOptions('<option value="">Refresh saved filter…</option>' +
        names.map(n => `<option value="${n.replace(/"/g, '&quot;')}">${n}</option>`).join(''));
}

async function _pagRefreshSantaGifts() {
    try {
        const res  = await fetch('/api/santa-gifts');
        const data = await res.json();
        _pagSantaGifts = data.gifts || [];
        const cb = document.getElementById('pag-santa-cb');
        const label = document.getElementById('pag-santa-label');
        const setup = document.getElementById('pag-santa-setup');
        const santaRow = document.getElementById('pag-santa-row');
        if (_pagSantaGifts.length) {
            document.getElementById('pag-santa-count').textContent = _pagSantaGifts.length;
            cb.disabled = false;
            label.style.opacity = '';
            label.style.cursor = 'pointer';
            setup.style.display = 'none';
            santaRow.dataset.modalRow = 'pag-santa';
        } else {
            cb.disabled = true;
            cb.checked = false;
            label.style.opacity = '0.45';
            label.style.cursor = 'default';
            setup.style.display = '';
            santaRow.removeAttribute('data-modal-row');
        }
        _pagRenumberRows();
    } catch (e) { /* silent */ }
}
function closePagModal() {
    document.getElementById('pagywosg-modal').style.display = 'none';
}

// ── Monthly in a Month ──
let _miamSheetData = null;

function _miamDefaultName() {
    const now = new Date();
    return 'MiaM ' + now.toLocaleDateString('en-US', {month: 'long', year: 'numeric'});
}

async function openMiamModal() {
    document.getElementById('miam-modal').style.display = 'flex';
    document.getElementById('miam-filter-name').value = _miamDefaultName();
    document.getElementById('miam-loading').style.display = 'block';
    document.getElementById('miam-loading').textContent = 'Fetching game list…';
    document.getElementById('miam-stats').style.display = 'none';
    document.getElementById('miam-error').style.display = 'none';
    document.getElementById('miam-save-status').textContent = '';
    document.getElementById('miam-save-status').className = 'tool-status';
    try {
        const res = await fetch('/api/miam-sheet');
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.message || 'Failed to fetch sheet');
        _miamSheetData = data;
        document.getElementById('miam-loading').style.display = 'none';
        miamUpdateStats();
    } catch (e) {
        document.getElementById('miam-loading').style.display = 'none';
        document.getElementById('miam-error').style.display = 'block';
        document.getElementById('miam-error').textContent = 'Error: ' + e.message;
    }
}

function closeMiamModal() {
    document.getElementById('miam-modal').style.display = 'none';
}

function miamUpdateStats() {
    if (!_miamSheetData) return;
    document.getElementById('miam-stat-total').textContent = (_miamSheetData.total || 0).toLocaleString();
    document.getElementById('miam-stat-excluded').textContent = ((_miamSheetData.total || 0) - (_miamSheetData.eligible || 0)).toLocaleString();
    document.getElementById('miam-stat-eligible').textContent = (_miamSheetData.eligible || 0).toLocaleString();
    document.getElementById('miam-stat-library').textContent = (_miamSheetData.in_library || 0).toLocaleString();
    document.getElementById('miam-stats').style.display = 'block';
    const sqlBox = document.getElementById('miam-sql-box');
    if (sqlBox.style.display !== 'none') miamRenderSql();
}

function miamToggleComp(btn) {
    btn.classList.toggle('active');
    miamUpdateStats();
}

function _miamActiveStatuses() {
    return [...document.querySelectorAll('#miam-completion-btns .pag-comp-btn.active')].map(b => b.dataset.val);
}

function miamBuildSql() {
    const appids = (_miamSheetData && _miamSheetData.appids) || [];
    if (!appids.length) return "1=0 /* no eligible games */";
    const preview = appids.length <= 6
        ? appids.join(', ')
        : appids.slice(0, 3).join(', ') + ', … [' + appids.length + ' total]';
    const statuses = _miamActiveStatuses();
    const compClause = statuses.length
        ? '(' + statuses.map(v => `completion_status = '${v.replace(/'/g, "''")}'`).join(' OR ') + ')'
        : '1=0';
    return `platform = 'steam'\nAND ${compClause}\nAND appid IN (${preview})`;
}

function miamRenderSql() {
    sqlHighlightPre(document.getElementById('miam-sql-text'), 'SELECT * FROM games WHERE\n' + miamBuildSql());
}

function miamToggleSql() {
    const box = document.getElementById('miam-sql-box');
    const open = box.style.display === 'none';
    box.style.display = open ? 'block' : 'none';
    document.getElementById('miam-sql-chevron').textContent = open ? '▼' : '▶';
    if (open) miamRenderSql();
}

async function miamSave() {
    const statusEl = document.getElementById('miam-save-status');
    const name = document.getElementById('miam-filter-name').value.trim();
    if (!name) { document.getElementById('miam-filter-name').focus(); return; }
    const appids = (_miamSheetData && _miamSheetData.appids) || [];
    if (!appids.length) {
        statusEl.className = 'tool-status error';
        statusEl.textContent = 'No eligible games found — nothing to save.';
        return;
    }
    const statuses = _miamActiveStatuses();
    if (!statuses.length) {
        statusEl.className = 'tool-status error';
        statusEl.textContent = 'Select at least one completion status.';
        return;
    }
    const compItems = statuses.map(v => ({type: 'condition', column: 'completion_status', operator: '=', value: v}));
    const compNode = compItems.length === 1 ? compItems[0] : {type: 'group', logic: 'OR', items: compItems};

    const tree = {
        type: 'group',
        logic: 'AND',
        miam: true,
        items: [
            {type: 'condition', column: 'platform', operator: '=', value: 'steam'},
            compNode,
            {type: 'appid_list', appids: appids.map(Number)},
        ],
    };

    if (_savedFilters[name]) {
        const replace = await confirmCustom(`A filter named "${escHtml(name)}" already exists.\n\nReplace it, or go back to rename?`, 'Replace', 'Rename');
        if (!replace) {
            document.getElementById('miam-filter-name').select();
            document.getElementById('miam-filter-name').focus();
            return;
        }
    }

    try {
        const res = await fetch('/api/save-filter', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, filter_tree: tree}),
        });
        const data = await res.json();
        if (data.status === 'success') {
            statusEl.className = 'tool-status success';
            statusEl.textContent = '✔ Saved as "' + name + '".';
            const existingEntry = _savedFilters[name];
            const existingId = (existingEntry && typeof existingEntry === 'object' && existingEntry.id) ? existingEntry.id : null;
            _savedFilters[name] = {id: existingId, tree};
            if (typeof renderSavedFilters === 'function') renderSavedFilters();
        } else {
            statusEl.className = 'tool-status error';
            statusEl.textContent = data.message || 'Save failed.';
        }
    } catch (e) {
        statusEl.className = 'tool-status error';
        statusEl.textContent = 'Network error: ' + e.message;
    }
}

// ── Secret Santa / Snowballs ──
let _santaGifts = [];        // [{appid, name, year?}] — year is optional evidence of when the gift was given
let _santaSaved = [];        // snapshot of last-saved state for dirty check
let _santaSaving = false;
let _santaSearchTimer = null;
let _santaSearchCache = [];  // last search results
let _santaGroupPickerOpen = false;

function _santaFingerprint() {
    return _santaGifts.map(g => `${g.appid}:${g.year || ''}`).sort().join(',');
}

async function openSantaModal() {
    document.getElementById('santa-modal').style.display = 'flex';
    document.getElementById('santa-status').textContent = '';
    const res = await fetch('/api/santa-gifts');
    const data = await res.json();
    _santaGifts = data.gifts || [];
    _santaSaved = _santaFingerprint();
    _renderSantaList();
    const inp = document.getElementById('santa-search');
    inp.value = '';
    document.getElementById('santa-search-results').style.display = 'none';
    _closeSantaGroupPicker();
    document.getElementById('santa-group-label').textContent = 'Add all games from a group...';
    document.getElementById('santa-group-year').value = '';
    inp.focus();
    _loadSantaGroups();
}
async function _loadSantaGroups() {
    const picker = document.getElementById('santa-group-picker');
    picker.innerHTML = '<div style="padding:8px 10px; color:var(--text-secondary); font-size:0.85rem;">Loading...</div>';
    try {
        const res = await fetch('/api/games/groups');
        const groups = await res.json();
        if (!groups.length) {
            picker.innerHTML = '<div style="padding:8px 10px; color:var(--text-secondary); font-size:0.85rem;">No groups found.</div>';
            return;
        }
        picker.innerHTML = groups.map(g =>
            `<div style="padding:7px 10px; cursor:pointer; font-size:0.88rem; color:var(--text-primary);"
                onmouseenter="this.style.background='var(--hover-bg)'" onmouseleave="this.style.background=''"
                onclick="_santaAddGroup(${escHtml(JSON.stringify(g))})">
                ${escHtml(g)}
            </div>`
        ).join('');
    } catch (e) {
        picker.innerHTML = '<div style="padding:8px 10px; color:var(--text-secondary); font-size:0.85rem;">Failed to load groups.</div>';
    }
}

function toggleSantaGroupPicker() {
    const picker = document.getElementById('santa-group-picker');
    _santaGroupPickerOpen = picker.style.display === 'none';
    picker.style.display = _santaGroupPickerOpen ? 'block' : 'none';
}

function _closeSantaGroupPicker() {
    document.getElementById('santa-group-picker').style.display = 'none';
    _santaGroupPickerOpen = false;
}

async function _santaAddGroup(group) {
    _closeSantaGroupPicker();
    const status = document.getElementById('santa-status');
    status.style.color = 'var(--text-secondary)';
    status.textContent = 'Fetching group...';
    try {
        const res = await fetch(`/api/games/by-group?group=${encodeURIComponent(group)}`);
        const games = await res.json();
        if (!Array.isArray(games) || !games.length) {
            status.textContent = `No Steam games found in "${group}".`;
            return;
        }
        let added = 0, updated = 0;
        const yearInput = document.getElementById('santa-group-year').value.trim();
        const year = yearInput ? parseInt(yearInput, 10) : null;
        games.forEach(g => {
            const existing = _santaGifts.find(x => x.appid === g.appid);
            if (!existing) {
                const entry = {appid: g.appid, name: g.name};
                if (year) entry.year = year;
                _santaGifts.push(entry);
                added++;
            } else if (year && existing.year !== year) {
                // Already in the list — a year specified for this batch
                // overrides whatever the game had before (or lack thereof).
                existing.year = year;
                updated++;
            }
        });
        _renderSantaList();
        document.getElementById('santa-group-label').textContent = 'Add all games from a group...';
        const parts = [];
        if (added)   parts.push(`added ${added} game${added === 1 ? '' : 's'}`);
        if (updated) parts.push(`updated the year on ${updated} existing game${updated === 1 ? '' : 's'}`);
        status.textContent = parts.length
            ? `${parts.join(', ')} from "${group}"${year ? ` (${year})` : ''}.`
            : `All games from "${group}" are already in the list${year ? ` with year ${year}` : ''}.`;
    } catch (e) {
        status.textContent = 'Failed to fetch group.';
    }
}

function _santaIsDirty() {
    return _santaFingerprint() !== _santaSaved;
}
function closeSantaModal() {
    if (_santaIsDirty()) {
        confirm('You have unsaved changes. Close without saving?').then(ok => {
            if (ok) document.getElementById('santa-modal').style.display = 'none';
        });
        return;
    }
    document.getElementById('santa-modal').style.display = 'none';
}

function _renderSantaList() {
    const el = document.getElementById('santa-list');
    document.getElementById('santa-count').textContent = _santaGifts.length;
    const sorted = _santaGifts.slice().sort((a, b) => a.name.localeCompare(b.name));
    if (!sorted.length) {
        el.innerHTML = '<div style="padding:10px 12px; color:var(--text-secondary); font-size:0.85rem;">No games added yet.</div>';
    } else {
        el.innerHTML = sorted
            .map((g, i) => `<div data-modal-row="${i + 1}" onclick="_santaRemove(${g.appid})" style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:6px 10px; border-bottom:1px solid var(--border); cursor:pointer;">
                <span onclick="event.stopPropagation()" style="font-size:0.88rem; color:var(--text-primary); flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; cursor:default;">${escHtml(g.name)}</span>
                <input type="number" value="${g.year || ''}" placeholder="year"
                    title="Year this gift was given — shown in the PAGYWOSG hover tooltip as evidence"
                    onclick="event.stopPropagation()" onchange="_santaSetYear(${g.appid}, this.value)"
                    style="width:64px; flex-shrink:0; padding:2px 6px; font-size:0.8rem; background:var(--bg-input); color:var(--text-primary); border:1px solid var(--border); border-radius:4px;">
                <span style="color:var(--text-secondary); font-size:0.85rem; padding:0 2px; line-height:1; flex-shrink:0;">&#x2715;</span>
            </div>`)
            .join('');
    }
    const closeRow = sorted.length + 1;
    document.querySelectorAll('#santa-modal .nav-btn').forEach(btn => {
        btn.dataset.modalRow = closeRow;
    });
}

function _santaRemove(appid) {
    _santaGifts = _santaGifts.filter(g => g.appid !== appid);
    _renderSantaList();
}

function _santaSetYear(appid, value) {
    const g = _santaGifts.find(x => x.appid === appid);
    if (!g) return;
    const year = parseInt(value, 10);
    if (value === '' || isNaN(year)) {
        delete g.year;
    } else {
        g.year = year;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const inp = document.getElementById('santa-search');
    const results = document.getElementById('santa-search-results');

    inp.addEventListener('input', () => {
        clearTimeout(_santaSearchTimer);
        const q = inp.value.trim();
        if (!q) { results.style.display = 'none'; return; }
        _santaSearchTimer = setTimeout(async () => {
            const res = await fetch(`/api/games/search?q=${encodeURIComponent(q)}&platform=steam`);
            const games = await res.json();
            if (!games.length) { results.style.display = 'none'; return; }
            _santaSearchCache = games;
            results.innerHTML = games.map((g, i) =>
                `<div data-idx="${i}" style="padding:7px 10px; cursor:pointer; font-size:0.88rem; color:var(--text-primary);"
                    onmouseenter="this.style.background='var(--hover-bg)'" onmouseleave="this.style.background=''"
                    onclick="_santaAddIdx(${i})">
                    ${escHtml(g.name)} <span style="color:var(--text-secondary); font-size:0.78rem;">#${g.appid}</span>
                </div>`
            ).join('');
            results.style.display = 'block';
        }, 200);
    });

    document.addEventListener('click', e => {
        const groupBtn    = document.getElementById('santa-group-btn');
        const groupPicker = document.getElementById('santa-group-picker');
        if (!results.contains(e.target) && e.target !== inp) {
            results.style.display = 'none';
        }
        if (!groupPicker.contains(e.target) && e.target !== groupBtn && !groupBtn.contains(e.target)) {
            _closeSantaGroupPicker();
        }
    });

    inp.addEventListener('keydown', e => {
        if (e.key === 'Escape' && results.style.display !== 'none') {
            e.stopPropagation();
            results.style.display = 'none';
            inp.value = '';
        }
    });
});

function _santaAddIdx(idx) {
    const g = _santaSearchCache[idx];
    if (!g) return;
    if (!_santaGifts.find(x => x.appid === g.appid)) {
        _santaGifts.push({appid: g.appid, name: g.name});
        _renderSantaList();
    }
    document.getElementById('santa-search').value = '';
    document.getElementById('santa-search-results').style.display = 'none';
}

async function saveSantaGifts() {
    if (_santaSaving) return;
    _santaSaving = true;
    const btn = document.getElementById('santa-save-btn');
    const status = document.getElementById('santa-status');
    btn.style.opacity = '0.5';
    status.textContent = '';
    try {
        const res = await fetch('/api/santa-gifts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({gifts: _santaGifts}),
        });
        const data = await res.json();
        if (data.status === 'success') {
            _santaSaved = _santaFingerprint();
            status.style.color = 'var(--text-secondary)';
            status.textContent = 'Saved.';
        } else {
            status.style.color = 'var(--accent)';
            status.textContent = data.message || 'Error saving.';
        }
    } catch (e) {
        status.style.color = 'var(--accent)';
        status.textContent = 'Network error.';
    }
    btn.style.opacity = '';
    _santaSaving = false;
}

let _pagSantaGifts = [];  // [{appid, name, year?}] loaded once on pagInit

let _pagCompDefaults = ['Never Played', 'Unfinished'];

async function pagInit() {
    try {
        const [tagsRes, sgRes, compRes] = await Promise.all([
            fetch('/api/pagywosg-tags'),
            fetch('/api/pagywosg-sg-group'),
            fetch('/api/pagywosg-comp-defaults'),
        ]);
        const tagsData = await tagsRes.json();
        const sgData   = await sgRes.json();
        const compData = await compRes.json();
        _pagCompDefaults = compData.statuses?.length ? compData.statuses : ['Never Played', 'Unfinished'];
        document.querySelectorAll('#pag-completion-btns .pag-comp-btn').forEach(b => {
            b.classList.toggle('active', _pagCompDefaults.includes(b.dataset.val));
        });
        if (tagsData.status !== 'success') throw new Error(tagsData.message);
        _pagAllTags = tagsData.tags;
        _pagWinsTags = tagsData.tags;
        pagRenderTags('all');
        pagRenderTags('wins');
        _pagApplySgGroupData(sgData);
        document.getElementById('pagywosg-loading').style.display = 'none';
        document.getElementById('pag-auto-controls').style.display = 'block';
        document.getElementById('pagywosg-inner').style.display = 'block';
        document.getElementById('pag-footer').style.display = 'block';
    } catch (e) {
        document.getElementById('pagywosg-loading').textContent = '✘ Failed to load tags: ' + e.message;
    }
}

function _pagApplySgGroupData(data) {
    _pagAllGroups = data.groups || [];
    if (!data.unset) {
        // User has previously configured a choice (string or null)
        _pagSgGroup = data.saved;
    } else if (data.default_group) {
        // First visit, "won on steamgifts" exists in library — auto-use it silently
        _pagSgGroup = data.default_group;
    } else {
        // First visit, no match in library — needs user input
        _pagSgGroup = undefined;
    }
    _pagUpdateSgGroupUI();
}

function _pagUpdateSgGroupUI() {
    const notice   = document.getElementById('pag-sg-group-notice');
    const subtitle = document.getElementById('pag-wins-subtitle');
    if (!notice) return;

    if (_pagSgGroup === undefined) {
        // Needs configuration
        const opts = _pagAllGroups.map(g =>
            `<option value="${g.replace(/"/g,'&quot;')}">${g}</option>`
        ).join('');
        notice.style.display = 'block';
        notice.innerHTML = `
            <div style="background:rgba(240,173,78,0.12); border:1px solid rgba(240,173,78,0.45); border-radius:6px; padding:10px 12px; font-size:0.82rem;">
                <div style="color:#F0AD4E; font-weight:bold; margin-bottom:6px;">⚠ No "Won on SteamGifts" group found in your library</div>
                <div style="color:var(--text-secondary); margin-bottom:10px;">The wins branch won't match any games. Choose a substitute group or confirm you have no SteamGifts wins.</div>
                <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                    <select id="pag-sg-group-sel" style="flex:1; min-width:140px; background:var(--bg-input); border:1px solid var(--border); border-radius:4px; color:var(--text-primary); padding:5px 8px; font-size:0.82rem;">
                        ${opts}
                    </select>
                    <button class="nav-btn" style="padding:5px 14px; font-size:0.82rem;" onclick="_pagSaveSgGroup(document.getElementById('pag-sg-group-sel').value)">Use this group</button>
                    <button class="nav-btn" style="padding:5px 14px; font-size:0.82rem; opacity:0.7;" onclick="_pagSaveSgGroup(null)">No SteamGifts wins</button>
                </div>
            </div>`;
        if (subtitle) subtitle.textContent = '(wins branch disabled — configure above)';
    } else if (_pagSgGroup === null) {
        // Explicitly configured: no SG wins
        notice.style.display = 'block';
        notice.innerHTML = `
            <div style="color:var(--text-secondary); font-size:0.8rem;">
                Wins branch disabled (no SteamGifts wins configured).
                <button onclick="_pagShowSgGroupPicker()" style="background:none; border:none; color:var(--accent); cursor:pointer; font-size:0.8rem; padding:0 4px; text-decoration:underline;">Change</button>
            </div>`;
        if (subtitle) subtitle.textContent = '(disabled — no SteamGifts wins)';
    } else if (_pagSgGroup.toLowerCase() !== 'won on steamgifts') {
        // Custom non-default group
        notice.style.display = 'block';
        notice.innerHTML = `
            <div style="color:var(--text-secondary); font-size:0.8rem;">
                Wins group: <strong style="color:var(--text-primary);">${_pagSgGroup}</strong>
                <button onclick="_pagShowSgGroupPicker()" style="background:none; border:none; color:var(--accent); cursor:pointer; font-size:0.8rem; padding:0 4px; text-decoration:underline;">Change</button>
            </div>`;
        if (subtitle) subtitle.textContent = `only applies to games in "${_pagSgGroup}"`;
    } else {
        // Default "won on steamgifts" — no notice needed
        notice.style.display = 'none';
        notice.innerHTML = '';
        if (subtitle) subtitle.textContent = 'only applies to games won on SteamGifts';
    }
    pagUpdateSql();
}

async function _pagSaveSgGroup(group) {
    await fetch('/api/pagywosg-sg-group', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({group}),
    });
    _pagSgGroup = group === undefined ? null : group;
    _pagUpdateSgGroupUI();
}

function _pagShowSgGroupPicker() {
    const notice = document.getElementById('pag-sg-group-notice');
    if (!notice) return;
    const opts = _pagAllGroups.map(g =>
        `<option value="${g.replace(/"/g,'&quot;')}"${g === _pagSgGroup ? ' selected' : ''}>${g}</option>`
    ).join('');
    notice.innerHTML = `
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; font-size:0.82rem;">
            <select id="pag-sg-group-sel" style="flex:1; min-width:140px; background:var(--bg-input); border:1px solid var(--border); border-radius:4px; color:var(--text-primary); padding:5px 8px; font-size:0.82rem;">
                ${opts}
            </select>
            <button class="nav-btn" style="padding:5px 14px; font-size:0.82rem;" onclick="_pagSaveSgGroup(document.getElementById('pag-sg-group-sel').value)">Save</button>
            <button class="nav-btn" style="padding:5px 14px; font-size:0.82rem; opacity:0.7;" onclick="_pagSaveSgGroup(null)">No SteamGifts wins</button>
            <button class="nav-btn" style="padding:5px 14px; font-size:0.82rem; opacity:0.7;" onclick="_pagUpdateSgGroupUI()">Cancel</button>
        </div>`;
}

function _pagRenumberRows() {
    const modal = document.getElementById('pagywosg-modal');
    if (!modal) return;
    const all = [...modal.querySelectorAll('[data-modal-row]')];
    let seq = 0;
    const seen = new Map();
    for (const el of all) {
        const key = el.dataset.modalRow;
        if (!seen.has(key)) seen.set(key, seq++);
    }
    for (const el of all) {
        el.dataset.modalRow = seen.get(el.dataset.modalRow);
    }
}

function pagUpdateSelectedTagsSummary(pool) {
    const el = document.getElementById(`pag-${pool}-selected-tags`);
    if (!el) return;
    const selected = pool === 'all' ? _pagSelectedAll : _pagSelectedWins;
    el.textContent = selected.size
        ? `Selected tags: ${[...selected].sort((a, b) => a.localeCompare(b)).join(', ')}`
        : 'No tags selected';
}

function pagRenderTags(pool) {
    const tags = pool === 'all' ? _pagAllTags : _pagWinsTags;
    const selected = pool === 'all' ? _pagSelectedAll : _pagSelectedWins;
    const search = document.getElementById(`pag-${pool}-search`).value.toLowerCase();
    const container = document.getElementById(`pag-${pool}-tags`);
    container.innerHTML = '';
    tags.forEach(tag => {
        const chip = document.createElement('span');
        chip.className = 'pag-tag-chip' + (selected.has(tag) ? ' selected' : '') + (search && !tag.toLowerCase().includes(search) ? ' hidden' : '');
        chip.textContent = tag;
        chip.dataset.modalRow = 'pag-' + pool + '-tags';
        chip.onclick = () => {
            if (selected.has(tag)) selected.delete(tag);
            else selected.add(tag);
            chip.classList.toggle('selected');
            pagUpdateSelectedTagsSummary(pool);
            pagUpdateSql();
        };
        container.appendChild(chip);
    });
    pagUpdateSelectedTagsSummary(pool);
    _pagRenumberRows();
}

function pagFilterTags(pool) { pagRenderTags(pool); }

let _pagCondIdCounter = 0;

function pagAddCond(pool, opts) {
    const container = document.getElementById(`pag-${pool}-conds`);
    const condRowKey = 'pag-' + pool + '-cond-' + (_pagCondIdCounter++);
    const row = document.createElement('div');
    row.style.cssText = 'display:flex; gap:6px; align-items:center; margin-bottom:6px; margin-left:3px;';

    const sharedSelStyle = 'padding:5px 8px; background-color:var(--bg-input); border:1px solid var(--border); border-radius:4px; color:var(--text-primary); font-size:0.82rem;';

    const colSel = document.createElement('select');
    colSel.style.cssText = sharedSelStyle + 'width:150px;';
    colSel.dataset.modalRow = condRowKey;
    PAG_COLUMNS.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.value; opt.textContent = c.label;
        colSel.appendChild(opt);
    });

    const opSel = document.createElement('select');
    opSel.style.cssText = sharedSelStyle + 'width:150px;';
    opSel.dataset.modalRow = condRowKey;
    PAG_OPS.forEach(o => {
        const opt = document.createElement('option');
        opt.value = o.value; opt.textContent = o.label;
        opSel.appendChild(opt);
    });

    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.placeholder = 'value';
    valInput.style.cssText = 'width:150px; padding:5px 8px; background:var(--bg-input); border:1px solid var(--border); border-radius:4px; color:var(--text-primary); font-size:0.82rem; outline:none;';
    valInput.dataset.modalRow = condRowKey;
    valInput.onfocus = () => valInput.style.borderColor = 'var(--accent)';
    valInput.onblur  = () => valInput.style.borderColor = 'var(--border)';

    const removeBtn = document.createElement('button');
    removeBtn.textContent = '✕';
    removeBtn.style.cssText = 'background:none; border:none; color:var(--text-danger); font-size:1rem; cursor:pointer; padding:0 2px; line-height:1;';
    removeBtn.dataset.modalRow = condRowKey;
    removeBtn.onclick = () => { row.remove(); pagUpdateSql(); _pagRenumberRows(); };

    function pagRefreshOps() {
        const isDate = PAG_DATE_COLUMNS.has(colSel.value);
        const ops = isDate ? PAG_DATE_OPS : PAG_OPS;
        opSel.innerHTML = '';
        ops.forEach(o => {
            const opt = document.createElement('option');
            opt.value = o.value; opt.textContent = o.label;
            opSel.appendChild(opt);
        });
        pagRefreshPlaceholder();
    }

    function pagRefreshPlaceholder() {
        const op = opSel.value;
        if (op === 'month_is')       { valInput.type = 'number'; valInput.placeholder = '1–12'; }
        else if (op === 'day_is')    { valInput.type = 'number'; valInput.placeholder = '1–31'; }
        else if (op === 'year_is')   { valInput.type = 'number'; valInput.placeholder = 'YYYY'; }
        else if (op === 'weekday_is'){ valInput.type = 'number'; valInput.placeholder = '0=Sun 1=Mon … 6=Sat'; }
        else                         { valInput.type = 'text';   valInput.placeholder = 'value'; }
    }

    colSel.onchange = () => { pagRefreshOps(); pagUpdateSql(); };
    opSel.onchange  = () => { pagRefreshPlaceholder(); pagUpdateSql(); };
    valInput.oninput = pagUpdateSql;

    row.appendChild(colSel);
    row.appendChild(opSel);
    row.appendChild(valInput);
    row.appendChild(removeBtn);

    if (opts) {
        if (opts.col) { colSel.value = opts.col; pagRefreshOps(); }
        if (opts.op)  opSel.value = opts.op;
        if (opts.val !== undefined) { valInput.value = String(opts.val); pagRefreshPlaceholder(); }
    }

    container.appendChild(row);
    _pagRenumberRows();
}

// "N identical digits in a row": OR of replace(col, 'DDD..', '') != col for each digit 0-9.
function _pagConsecutiveRepeatSql(col, n) {
    const clauses = [];
    for (let d = 0; d <= 9; d++) clauses.push(`replace(${col}, '${String(d).repeat(n)}', '') != ${col}`);
    return `(${clauses.join(' OR ')})`;
}

// Mirrors pagywosg.py's _strip_alnum_sql — nested replace() chain stripping
// a-z/0-9/space so leftover length > 0 means a "special" character exists.
const _PAG_ALNUM_SPACE_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789 '.split('');
function _pagStripAlnumSql(col) {
    let sql = `lower(${col})`;
    for (const c of _PAG_ALNUM_SPACE_CHARS) sql = `replace(${sql}, '${c}', '')`;
    return sql;
}

function pagCondToSql(row) {
    const col = row.children[0].value;
    const op  = row.children[1].value;
    const val = row.children[2].value.trim().replace(/'/g, "''");
    if (!val) return null;
    switch (op) {
        case 'contains':     return `${col} LIKE '%${val}%'`;
        case 'not_contains': return `${col} NOT LIKE '%${val}%'`;
        case 'equals':       return `${col} = '${val}'`;
        case 'starts_with':  return `${col} LIKE '${val}%'`;
        case 'ends_with':    return `${col} LIKE '%${val}'`;
        case 'gt':           return `${col} > '${val}'`;
        case 'lt':           return `${col} < '${val}'`;
        case 'gte':          return `${col} >= ${val}`;
        case 'title_word': { const wl = val.toLowerCase().replace(/'/g,"''"); return `(' ' || ${_PAG_TITLE_NORM} || ' ') LIKE '% ${wl} %'`; }
        default: {
            const kind = window._PAG_OPS[op]?.kind;
            if (kind === 'strftime') {
                const fmt = window._PAG_OPS[op].fmt;
                const v = fmt === '%Y' ? val : String(val).padStart(2, '0');
                return `strftime('${fmt}', ${col}) = '${v}'`;
            }
            if (kind === 'strftime_weekday') return `strftime('%w', datetime(${col}, 'unixepoch')) = '${val}'`;
            if (kind === 'title_length') return `length(${col}) = ${parseInt(val, 10)}`;
            if (kind === 'digit_count') {
                const [digit, count] = val.split(':');
                return `(length(${col}) - length(replace(${col}, '${digit}', ''))) >= ${parseInt(count, 10)}`;
            }
            if (kind === 'consecutive_repeat') return _pagConsecutiveRepeatSql(col, parseInt(val, 10));
            if (kind === 'has_special_char') return `length(${_pagStripAlnumSql(col)}) > 0`;
            if (kind === 'numeric_range') {
                const [lo, hi] = val.split(':');
                return `(${col} >= ${parseInt(lo, 10)} AND ${col} <= ${parseInt(hi, 10)})`;
            }
            if (kind === 'tag_substring') return `${col} LIKE '%${val}%'`;
            if (kind === 'nth_weekday') {
                const [n, w] = val.split(':').map(x => parseInt(x, 10));
                const lo = String((n - 1) * 7 + 1).padStart(2, '0'), hi = String(n * 7).padStart(2, '0');
                return `(strftime('%w', datetime(${col}, 'unixepoch')) = '${w}' AND strftime('%d', ${col}, 'unixepoch') BETWEEN '${lo}' AND '${hi}')`;
            }
            if (kind === 'all_caps') return `upper(${col}) = ${col}`;
            if (kind === 'contains_all') {
                return `(${val.split('').map(l => `${col} LIKE '%${l}%'`).join(' AND ')})`;
            }
            if (kind === 'tag_count') {
                return `(CASE WHEN ${col} = '' OR ${col} IS NULL THEN 0 ELSE length(${col}) - length(replace(${col}, ',', '')) + 1 END) = ${parseInt(val, 10)}`;
            }
            if (kind === 'single_word') return `replace(trim(${col}), ' ', '') = trim(${col})`;
            return null;
        }
    }
}

function pagCondToTree(row) {
    const col = row.children[0].value;
    const op  = row.children[1].value;
    const val = row.children[2].value.trim();
    if (!val) return null;
    const esc = val.replace(/'/g, "''");
    const kind = window._PAG_OPS[op]?.kind;
    if (kind === 'starts_with')  return { type: 'custom_expr', sql: `${col} LIKE '${esc}%'` };
    if (kind === 'ends_with')    return { type: 'custom_expr', sql: `${col} LIKE '%${esc}'` };
    if (kind === 'title_word') { const wl = esc.toLowerCase(); return { type: 'custom_expr', sql: `(' ' || ${_PAG_TITLE_NORM} || ' ') LIKE '% ${wl} %'` }; }
    if (kind === 'title_length') return { type: 'custom_expr', sql: `length(${col}) = ${parseInt(val, 10)}` };
    if (kind === 'digit_count') {
        const [digit, count] = val.split(':');
        return { type: 'custom_expr', sql: `(length(${col}) - length(replace(${col}, '${digit}', ''))) >= ${parseInt(count, 10)}` };
    }
    if (kind === 'consecutive_repeat') {
        return { type: 'custom_expr', sql: _pagConsecutiveRepeatSql(col, parseInt(val, 10)) };
    }
    if (kind === 'has_special_char') {
        return { type: 'custom_expr', sql: `length(${_pagStripAlnumSql(col)}) > 0` };
    }
    if (kind === 'numeric_range') {
        const [lo, hi] = val.split(':');
        return { type: 'custom_expr', sql: `(${col} >= ${parseInt(lo, 10)} AND ${col} <= ${parseInt(hi, 10)})` };
    }
    if (kind === 'tag_substring') return { type: 'custom_expr', sql: `${col} LIKE '%${esc}%'` };
    if (kind === 'nth_weekday') {
        const [n, w] = val.split(':').map(x => parseInt(x, 10));
        const lo = String((n - 1) * 7 + 1).padStart(2, '0'), hi = String(n * 7).padStart(2, '0');
        return { type: 'custom_expr', sql: `(strftime('%w', datetime(${col}, 'unixepoch')) = '${w}' AND strftime('%d', ${col}, 'unixepoch') BETWEEN '${lo}' AND '${hi}')` };
    }
    if (kind === 'all_caps') return { type: 'custom_expr', sql: `upper(${col}) = ${col}` };
    if (kind === 'contains_all') {
        return { type: 'custom_expr', sql: `(${esc.split('').map(l => `${col} LIKE '%${l}%'`).join(' AND ')})` };
    }
    if (kind === 'tag_count') {
        return { type: 'custom_expr', sql: `(CASE WHEN ${col} = '' OR ${col} IS NULL THEN 0 ELSE length(${col}) - length(replace(${col}, ',', '')) + 1 END) = ${parseInt(val, 10)}` };
    }
    if (kind === 'single_word') {
        return { type: 'custom_expr', sql: `replace(trim(${col}), ' ', '') = trim(${col})` };
    }
    return { type: 'condition', column: col, operator: window._PAG_OPS[op]?.tree_op || '=', value: val };
}

function pagBuildTree() {
    const allTags  = [..._pagSelectedAll];
    const winsTags = [..._pagSelectedWins];

    const _toAppidListNodes = (sources, fallbackAppids) => {
        if (sources.length) {
            return sources
                .map(s => {
                    // Personal: verified-for-someone-else entries don't apply to
                    // you, so only the subset verified specifically for your own
                    // sg_username counts, not the whole category's appid list.
                    const appids = _pagPersonalCats.has(s.label) ? (s.personal_appids || []) : s.appids;
                    return appids.length ? { type: 'appid_list', appids, label: s.label, auto: s.auto } : null;
                })
                .filter(Boolean);
        }
        return fallbackAppids.length ? [{ type: 'appid_list', appids: fallbackAppids }] : [];
    };
    const allExtraItems  = [
        ...Array.from(document.querySelectorAll('#pag-all-conds > div')).map(pagCondToTree).filter(Boolean),
        ..._toAppidListNodes(_pagAllAppidSources,  _pagAllAppids)
    ];
    const winsExtraItems = [
        ...Array.from(document.querySelectorAll('#pag-wins-conds > div')).map(pagCondToTree).filter(Boolean),
        ..._toAppidListNodes(_pagWinsAppidSources, _pagWinsAppids)
    ];

    // More than one tag collapses into a single list-valued condition node
    // (one condition compiling to a parenthesized OR) instead of N separate
    // OR'd nodes — keeps saved PAGYWOSG trees from ballooning with dozens of
    // near-identical tag conditions.
    const allTagItems  = allTags.length > 1
        ? [{ type: 'condition', column: 'tags', operator: 'LIKE', value: allTags }]
        : allTags.map(t => ({ type: 'condition', column: 'tags', operator: 'LIKE', value: t }));
    const winsTagItems = winsTags.length > 1
        ? [{ type: 'condition', column: 'tags', operator: 'LIKE', value: winsTags }]
        : winsTags.map(t => ({ type: 'condition', column: 'tags', operator: 'LIKE', value: t }));

    const compVals = Array.from(document.querySelectorAll('#pag-completion-btns .pag-comp-btn.active')).map(b => b.dataset.val);

    const mainParts = [];

    // SG wins block: (wins_qualifier) AND (tags OR extra_conds)
    // wins_qualifier is groups = sg_group alone, or OR[groups, santa_appid_list] when santa gifts included.
    // Omitted entirely when _pagSgGroup is null and no santa gifts checked.
    const santaChecked = document.getElementById('pag-santa-cb')?.checked && _pagSantaGifts.length;
    const santaNode = santaChecked
        ? { type: 'appid_list', appids: _pagSantaGifts.map(g => g.appid), label: 'Secret Santa / Snowballs', auto: true }
        : null;
    const winsConds = [...winsTagItems, ...winsExtraItems];
    const hasWinsBlock = winsConds.length && (_pagSgGroup || santaNode);
    if (hasWinsBlock) {
        const winsInner = winsConds.length === 1 ? winsConds[0] : { type: 'group', logic: 'OR', items: winsConds };
        let winsQualifier;
        if (_pagSgGroup && santaNode) {
            winsQualifier = { type: 'group', logic: 'OR', items: [
                { type: 'condition', column: 'groups', operator: 'LIKE', value: _pagSgGroup },
                santaNode
            ]};
        } else if (_pagSgGroup) {
            winsQualifier = { type: 'condition', column: 'groups', operator: 'LIKE', value: _pagSgGroup };
        } else {
            winsQualifier = santaNode;
        }
        mainParts.push({ type: 'group', logic: 'AND', items: [winsQualifier, winsInner] });
    }

    // All games block: tags OR extra_conds
    const allConds = [...allTagItems, ...allExtraItems];
    if (allConds.length) {
        mainParts.push(allConds.length === 1 ? allConds[0] : { type: 'group', logic: 'OR', items: allConds });
    }

    const rootItems = [];
    if (mainParts.length === 1)      rootItems.push(mainParts[0]);
    else if (mainParts.length > 1)   rootItems.push({ type: 'group', logic: 'OR', items: mainParts });

    if (compVals.length > 0 && compVals.length < 5) {
        const compItems = compVals.map(v => ({ type: 'condition', column: 'completion_status', operator: '=', value: v }));
        rootItems.push(compItems.length === 1 ? compItems[0] : { type: 'group', logic: 'OR', items: compItems });
    }

    // PAGYWOSG is Steam-only
    rootItems.unshift({ type: 'condition', column: 'platform', operator: '=', value: 'steam' });

    return { type: 'group', logic: 'AND', items: rootItems };
}

function pagToggleComp(btn) {
    btn.classList.toggle('active');
    pagUpdateSql();
    _pagCompDefaults = [...document.querySelectorAll('#pag-completion-btns .pag-comp-btn.active')].map(b => b.dataset.val);
    fetch('/api/pagywosg-comp-defaults', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({statuses: _pagCompDefaults}),
    });
}

function pagBuildWhere() {
    const allTags  = [..._pagSelectedAll];
    const winsTags = [..._pagSelectedWins];

    // Extra conditions from condition builders
    const allCondRows  = document.querySelectorAll('#pag-all-conds > div');
    const winsCondRows = document.querySelectorAll('#pag-wins-conds > div');
    const allExtraSql  = Array.from(allCondRows).map(pagCondToSql).filter(Boolean);
    const winsExtraSql = Array.from(winsCondRows).map(pagCondToSql).filter(Boolean);

    // All-games conditions
    const allConds = [
        ...allTags.map(t => `tags LIKE '%${t.replace(/'/g,"''")}%'`),
        ...allExtraSql,
        ...(_pagAllAppids.length ? [_pagAllAppids.length <= 6 ? `appid IN (${_pagAllAppids.join(', ')})` : `appid IN (${_pagAllAppids.slice(0,3).join(', ')}, … [${_pagAllAppids.length} total])`] : [])
    ];

    // Wins-only conditions
    const winsConds = [
        ...winsTags.map(t => `tags LIKE '%${t.replace(/'/g,"''")}%'`),
        ...winsExtraSql,
        ...(_pagWinsAppids.length ? [_pagWinsAppids.length <= 6 ? `appid IN (${_pagWinsAppids.join(', ')})` : `appid IN (${_pagWinsAppids.slice(0,3).join(', ')}, … [${_pagWinsAppids.length} total])`] : [])
    ];

    // Completion filter
    const compVals = Array.from(document.querySelectorAll('#pag-completion-btns .pag-comp-btn.active')).map(b => b.dataset.val);
    let compClause = '';
    if (compVals.length > 0 && compVals.length < 5) {
        compClause = '(' + compVals.map(v => `completion_status = '${v.replace(/'/g,"''")}'`).join(' OR ') + ')';
    }

    const parts = [];
    if (allConds.length)  parts.push(`(${allConds.join('\n    OR ')})`);
    if (winsConds.length && _pagSgGroup) {
        const sgEsc = _pagSgGroup.replace(/'/g, "''");
        parts.push(`(','||groups||',' LIKE '%,${sgEsc},%'\n    AND (${winsConds.join('\n    OR ')}))`);
    }

    if (!parts.length && !compClause) return '1=1';
    let where = parts.join('\nOR ');
    if (parts.length && compClause) where = `(\n${where}\n)\nAND ${compClause}`;
    else if (compClause)            where = compClause;
    return `platform = 'steam'\nAND (\n${where}\n)`;
}

function pagUpdateSql() {
    const box = document.getElementById('pag-sql-box');
    if (box.style.display !== 'none') {
        sqlHighlightPre(document.getElementById('pag-sql-text'), `SELECT * FROM games WHERE\n${pagBuildWhere()}`);
    }
}

function pagToggleSql() {
    const box = document.getElementById('pag-sql-box');
    const chevron = document.getElementById('pag-sql-chevron');
    const open = box.style.display === 'none';
    box.style.display = open ? 'block' : 'none';
    chevron.textContent = open ? '▼' : '▶';
    if (open) sqlHighlightPre(document.getElementById('pag-sql-text'), `SELECT * FROM games WHERE\n${pagBuildWhere()}`);
}

async function pagConfirmSave() {
    const saveStatus = document.getElementById('pag-save-status');
    const where = pagBuildWhere();
    if (where === '1=1') {
        saveStatus.className = 'tool-status error';
        saveStatus.textContent = 'No criteria selected — please pick at least one tag or add a condition.';
        return;
    }
    const name = document.getElementById('pag-filter-name').value.trim();
    if (!name) { document.getElementById('pag-filter-name').focus(); return; }
    if (_savedFilters[name]) {
        const replace = await confirmCustom(`A filter named "${name}" already exists.\n\nReplace it, or go back to rename?`, 'Replace', 'Rename');
        if (!replace) {
            const nameInput = document.getElementById('pag-filter-name');
            nameInput.select();
            nameInput.focus();
            return;
        }
    }
    const tree = pagBuildTree();
    tree.pagywosg = true;
    if (_pagEventId) tree.pagywosg_event = {id: _pagEventId, name: _pagEventName};
    tree.pagywosg_personal_cats = [..._pagPersonalCats].sort();
    // Build verified lookup: {appid_str: [{cat, pool}]}
    const _sgUsername = (_serverSgUsername || '').toLowerCase();
    const verifiedLookup = {};
    [
        ..._pagWinsGames.filter(g => g.in_library).map(g => ({...g, pool: 'wins'})),
        ..._pagAllGames.filter(g => g.in_library).map(g => ({...g, pool: 'all'}))
    ].forEach(({appid, categories, pool}) => {
        const key = String(appid);
        if (!verifiedLookup[key]) verifiedLookup[key] = [];
        categories.forEach(({cat, verifiers, auto}) => {
            if (_pagPersonalCats.has(cat)) {
                // Personal: a verified entry only counts if it was verified
                // specifically for the current sg_username, not just anyone.
                if (!_sgUsername || !(verifiers || []).some(v => v.toLowerCase() === _sgUsername)) return;
            }
            if (!verifiedLookup[key].some(e => e.cat === cat && e.pool === pool)) {
                const entry = {cat, pool};
                if (verifiers && verifiers.length) entry.verifiers = verifiers;
                if (auto) entry.auto = true;
                verifiedLookup[key].push(entry);
            }
        });
    });
    if (document.getElementById('pag-santa-cb')?.checked && _pagSantaGifts.length) {
        const santaCat = 'Secret Santa / Snowballs';
        _pagSantaGifts.forEach(({appid, name, year}) => {
            const key = String(appid);
            if (!verifiedLookup[key]) verifiedLookup[key] = [];
            if (!verifiedLookup[key].some(e => e.cat === santaCat && e.pool === 'wins')) {
                const entry = {cat: santaCat, pool: 'wins', auto: true};
                if (year) entry.year = year;
                verifiedLookup[key].push(entry);
            }
        });
    }
    tree.pagywosg_verified = verifiedLookup;
    try {
        const res = await fetch('/api/save-filter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, filter_tree: tree })
        });
        const data = await res.json();
        if (data.status === 'success') {
            saveStatus.className = 'tool-status success';
            saveStatus.textContent = `✔ Saved as "${name}".`;
            const existingEntry = _savedFilters[name];
            const existingId = (existingEntry && typeof existingEntry === 'object' && existingEntry.id) ? existingEntry.id : null;
            _savedFilters[name] = {id: existingId, tree};
            const selectEl = document.getElementById('saved-filters-select');
            if (selectEl && selectEl._addOption && !existingEntry) selectEl._addOption(name, name);
            await _pagOfferOldFilterCleanup(name, selectEl, saveStatus);
        } else {
            saveStatus.className = 'tool-status error';
            saveStatus.textContent = '✘ Could not save: ' + data.message;
        }
    } catch (e) {
        saveStatus.className = 'tool-status error';
        saveStatus.textContent = '✘ Network error.';
    }
}

async function _pagOfferOldFilterCleanup(justSavedName, selectEl, saveStatus) {
    // Only offer cleanup when we know which event this save belongs to — without
    // that we can't tell "old" from "current" and would risk deleting the wrong one.
    if (!_pagEventId) return;
    const oldNames = Object.keys(_savedFilters).filter(n => {
        if (n === justSavedName) return false;
        const t = _savedFilters[n]?.tree;
        return t?.pagywosg === true && t?.pagywosg_event?.id && t.pagywosg_event.id !== _pagEventId;
    });
    if (!oldNames.length) return;

    const label = oldNames.length === 1 ? `"${oldNames[0]}"` : `these filters: ${oldNames.map(n => `"${n}"`).join(', ')}`;
    const remove = await confirmCustom(`Delete ${label} from previous PAGYWOSG events?`, 'Delete', 'Keep');
    if (!remove) return;

    let removed = 0;
    for (const n of oldNames) {
        try {
            const r = await fetch('/api/delete-filter', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: n })
            });
            const d = await r.json();
            if (d.status === 'success') {
                delete _savedFilters[n];
                const opt = selectEl && selectEl._getOption ? selectEl._getOption(n) : null;
                if (opt) opt.remove();
                removed++;
            }
        } catch (e) {}
    }
    if (removed) {
        saveStatus.textContent = `✔ Saved as "${justSavedName}" — removed ${removed} old filter${removed !== 1 ? 's' : ''}.`;
    }
}

function pagUpdateAppidsInfo(pool) {
    const el = document.getElementById(`pag-${pool}-appids-info`);
    if (!el) return;
    const allGames = pool === 'wins' ? _pagWinsGames : _pagAllGames;
    // A game counts as included unless every one of its categories is a
    // verified_fallback category the user has toggled personal (and thus
    // conditionally excluded). Auto categories (icaio/santa) are never
    // personal-toggleable and always count — `auto` here only means "don't
    // show a mod-verified label," not "requires personal restriction."
    const games = allGames.filter(g => g.in_library && !g.redundant &&
        g.categories.some(c => c.auto || !_pagPersonalCats.has(c.cat)));
    if (!games.length) { el.style.display = 'none'; el.innerHTML = ''; return; }

    const listId = `pag-${pool}-appids-list`;
    el.style.display = '';
    el.innerHTML = `
        <span data-modal-row="pag-${pool}-appids-toggle" style="cursor:pointer; user-select:none; margin-left:3px;" onclick="
            const l=document.getElementById('${listId}');
            const open=l.style.display==='none';
            l.style.display=open?'':'none';
            this.querySelector('.pag-chevron').textContent=open?'▼':'▶';
        ">
            <span class="pag-chevron">▶</span>
            ✓ ${games.length} additional game${games.length !== 1 ? 's' : ''} included
        </span>
        <div id="${listId}" style="display:none; margin-top:4px; padding-left:12px; font-size:0.76rem; color:var(--text-secondary); max-height:120px; overflow-y:auto;">
            ${games.map(g =>
                `<div style="padding:1px 0;">${g.name} <span style="opacity:0.6;">— ${g.categories.map(c =>
                    (c.verifiers && c.verifiers.length) ? `${c.cat} <span style="opacity:0.7;">(via ${c.verifiers.join(', ')})</span>` : c.cat
                ).join(', ')}</span></div>`
            ).join('')}
        </div>`;
    _pagRenumberRows();
    pagRenderPersonalCats();
}

function pagRenderPersonalCats() {
    const section = document.getElementById('pag-personal-cats-section');
    if (!section) return;
    const cats = new Set();
    [..._pagWinsGames, ..._pagAllGames].forEach(g => {
        (g.categories || []).forEach(({cat, auto}) => { if (!auto) cats.add(cat); });
    });
    // Categories with zero verified appids so far (e.g. an upcoming event
    // nobody has played yet) never show up via the games loop above — surface
    // them too so they can be pre-toggled ahead of any verifications landing.
    _pagPersonalCandidates.forEach(cat => cats.add(cat));
    if (!cats.size) { section.style.display = 'none'; section.innerHTML = ''; return; }
    const sorted = [...cats].sort();
    pagRenderPersonalCats._list = sorted;
    let html = `<div style="border-top:1px solid var(--border); padding-top:14px; margin-bottom:16px;">
        <div style="font-size:0.78rem; font-weight:bold; text-transform:uppercase; letter-spacing:0.06em; color:var(--text-secondary); margin-bottom:4px;">Personal categories</div>
        <div style="font-size:0.76rem; color:var(--text-secondary); margin-bottom:8px; line-height:1.4;">Categories where eligibility depends on your own history. Checking one restricts its games to entries verified specifically for your own SG username (set in Settings) — a verified entry for someone else doesn&rsquo;t apply to you.</div>`;
    sorted.forEach((cat, i) => {
        const checked = _pagPersonalCats.has(cat) ? ' checked' : '';
        html += `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;cursor:pointer;" onclick="pagTogglePersonalCat(${i})">
            <input type="checkbox" style="width:auto;margin:0;flex-shrink:0;"${checked} onclick="event.stopPropagation();pagTogglePersonalCat(${i})">
            <span style="font-size:0.82rem;color:var(--text-primary);">${escHtml(cat)}</span>
        </div>`;
    });
    html += '</div>';
    section.innerHTML = html;
    section.style.display = '';
    _pagRenumberRows();
}

function pagTogglePersonalCat(idx) {
    const cat = (pagRenderPersonalCats._list || [])[idx];
    if (!cat) return;
    if (_pagPersonalCats.has(cat)) _pagPersonalCats.delete(cat);
    else _pagPersonalCats.add(cat);
    pagRenderPersonalCats();
}

async function pagAutoFill(next = false) {
    const btn     = document.getElementById('pag-auto-btn');
    const nextBtn = document.getElementById('pag-auto-next-btn');
    btn.disabled = nextBtn.disabled = true;
    (next ? nextBtn : btn).textContent = 'Loading…';
    document.getElementById('pag-auto-status').textContent = '';
    try {
        const res  = await fetch('/api/pagywosg-auto' + (next ? '?next=1' : ''));
        const data = await res.json();
        if (data.status !== 'success') {
            const _s = document.getElementById('pag-auto-status');
            _s.textContent = '✘ ' + data.message;
            _s.style.color = 'var(--accent-negative)';
            return;
        }

        pagClearAll();

        _pagPersonalCandidates = data.personal_candidates || [];

        // Pre-check categories the maintainer has curated as always-personal
        // for this event — still individually toggle-able from here.
        (data.default_personal || []).forEach(cat => _pagPersonalCats.add(cat));

        // Select tags (case-insensitive match against local tag list)
        data.tags.wins.forEach(tag => {
            const match = _pagAllTags.find(t => t.toLowerCase() === tag.toLowerCase());
            if (match) _pagSelectedWins.add(match);
        });
        data.tags.all.forEach(tag => {
            const match = _pagAllTags.find(t => t.toLowerCase() === tag.toLowerCase());
            if (match) _pagSelectedAll.add(match);
        });
        pagRenderTags('wins');
        pagRenderTags('all');

        // Add condition rows
        data.conds.wins.forEach(c => pagAddCond('wins', c));
        data.conds.all.forEach(c  => pagAddCond('all',  c));

        // Set verified appids + game info
        _pagWinsAppids        = data.wins.appids;
        _pagAllAppids         = data.all.appids;
        _pagWinsAppidSources  = data.wins.appid_sources || [];
        _pagAllAppidSources   = data.all.appid_sources  || [];
        _pagWinsGames         = data.wins.games;
        _pagAllGames          = data.all.games;
        pagUpdateAppidsInfo('wins');
        pagUpdateAppidsInfo('all');

        pagUpdateSql();

        _pagEventId   = data.event.id;
        _pagEventName = data.event.name;
        document.getElementById('pag-auto-event-name').textContent = data.event.name;
        document.getElementById('pag-auto-status').textContent = '✔ Auto-filled';

        // Auto-populate filter name: "PAGYWOSG April 2026" from "April 2026 - ..."
        const monthYear = data.event.name.split(' - ')[0].trim();
        const nameInput = document.getElementById('pag-filter-name');
        if (!nameInput.value) nameInput.value = `PAGYWOSG ${monthYear}`;
        const inner = document.getElementById('pagywosg-inner');
        if (inner) inner.scrollTop = inner.scrollHeight;
    } catch (e) {
        document.getElementById('pag-auto-status').textContent = '✘ ' + e.message;
        document.getElementById('pag-auto-status').style.color = 'var(--accent-negative)';
    } finally {
        btn.disabled = nextBtn.disabled = false;
        btn.textContent     = 'Auto-fill Current Event';
        nextBtn.textContent = 'Auto-fill Upcoming Event';
    }
}

function pagClearAll() {
    _pagSelectedAll.clear();
    _pagSelectedWins.clear();
    _pagAllAppids         = [];
    _pagWinsAppids        = [];
    _pagAllAppidSources   = [];
    _pagWinsAppidSources  = [];
    _pagAllGames          = [];
    _pagWinsGames         = [];
    _pagPersonalCats.clear();
    _pagPersonalCandidates = [];
    pagUpdateAppidsInfo('all');
    pagUpdateAppidsInfo('wins');
    pagRenderTags('all');
    pagRenderTags('wins');
    document.getElementById('pag-all-conds').innerHTML = '';
    document.getElementById('pag-wins-conds').innerHTML = '';
    document.querySelectorAll('#pag-completion-btns .pag-comp-btn').forEach(b => {
        b.classList.toggle('active', _pagCompDefaults.includes(b.dataset.val));
    });
    _pagEventId   = null;
    _pagEventName = '';
    document.getElementById('pag-filter-name').value = '';
    const _autoStatus = document.getElementById('pag-auto-status');
    _autoStatus.textContent = '';
    _autoStatus.style.color = 'var(--accent-positive)';
    document.getElementById('pag-save-status').textContent = '';
    document.getElementById('pag-save-status').className = 'tool-status';
    document.getElementById('pag-auto-event-name').textContent = '';
    pagUpdateSql();
}

function _pagWalkTreeNodes(node, visit) {
    if (!node || typeof node !== 'object') return;
    visit(node);
    if (node.type === 'group' && Array.isArray(node.items)) node.items.forEach(c => _pagWalkTreeNodes(c, visit));
}

function _pagExtractCompletionStatuses(tree) {
    const vals = [];
    _pagWalkTreeNodes(tree, n => { if (n.type === 'condition' && n.column === 'completion_status') vals.push(n.value); });
    return vals;
}

function _pagExtractSantaChecked(tree) {
    let found = false;
    _pagWalkTreeNodes(tree, n => { if (n.type === 'appid_list' && n.auto && n.label === 'Secret Santa / Snowballs') found = true; });
    return found;
}

async function pagRefreshSelectedFilter() {
    const sel  = document.getElementById('pag-refresh-select');
    const name = sel && sel.value;
    if (!name) return;

    const entry     = _savedFilters[name];
    const savedTree = (entry && typeof entry === 'object' && 'tree' in entry) ? entry.tree : entry;
    if (!savedTree || !savedTree.pagywosg) return;

    const savedEventId      = savedTree.pagywosg_event?.id ?? null;
    const savedEventName    = savedTree.pagywosg_event?.name ?? 'an unknown event';
    const savedPersonalCats = new Set(savedTree.pagywosg_personal_cats || []);
    const savedCompStatuses = _pagExtractCompletionStatuses(savedTree);
    const savedSantaChecked = _pagExtractSantaChecked(savedTree);
    const statusEl = document.getElementById('pag-auto-status');

    // Current event is the dominant case; fall back to "upcoming" for a
    // filter built ahead of an event that hasn't started yet.
    await pagAutoFill(false);
    if (savedEventId && _pagEventId !== savedEventId) await pagAutoFill(true);
    if (savedEventId && _pagEventId !== savedEventId) {
        statusEl.textContent = `✘ "${name}" was built for ${savedEventName}, which is neither the current nor upcoming event — rebuild it manually instead.`;
        statusEl.style.color = 'var(--accent-negative)';
        return;
    }

    // Overlay the saved judgment calls on top of the freshly auto-filled
    // state (pagAutoFill()'s internal pagClearAll() wiped these, and its
    // own auto-generated name, so restore them now).
    document.getElementById('pag-filter-name').value = name;
    _pagPersonalCats = savedPersonalCats;
    pagUpdateAppidsInfo('wins');
    pagUpdateAppidsInfo('all');

    document.querySelectorAll('#pag-completion-btns .pag-comp-btn').forEach(b => {
        b.classList.toggle('active', savedCompStatuses.length ? savedCompStatuses.includes(b.dataset.val) : true);
    });

    const santaCb = document.getElementById('pag-santa-cb');
    if (santaCb && !santaCb.disabled) santaCb.checked = savedSantaChecked;

    pagUpdateSql();
    statusEl.textContent = `✔ Refreshed "${name}" from live data — review below, then Save.`;
    statusEl.style.color = 'var(--accent-positive)';
}

// ── DB IMPORTER ──
let _dbMeta = null; // { tables, table_columns, table_column_types, local_columns, local_column_types }

function setImportStep(n) {
    [1,2,3].forEach(i => {
        document.getElementById(`import-step-${i}`).classList.toggle('active', i === n);
        const ind = document.getElementById(`step-ind-${i}`);
        ind.className = i < n ? 'done' : i === n ? 'active' : '';
    });
}

async function chooseDbFile() {
    if (_fileDlgBusy) return;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_open_path) {
        _fileDlgBusy = true;
        let path;
        try {
            path = await window.pywebview.api.pick_open_path(['Database Files (*.db)']);
        } finally {
            setTimeout(() => { _fileDlgBusy = false; }, 300);
        }
        if (!path) return;
        const status = document.getElementById('upload-status');
        status.className = 'tool-status info';
        status.textContent = 'Reading database…';
        try {
            const res  = await fetch('/api/import-inspect-path', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path })
            });
            const data = await res.json();
            if (data.status !== 'success') {
                status.className = 'tool-status error';
                status.textContent = '✘ ' + data.message;
                return;
            }
            _dbMeta = data;
            buildStep2();
            setImportStep(2);
        } catch (e) {
            status.className = 'tool-status error';
            status.textContent = '✘ Failed to read database.';
        }
    } else {
        document.getElementById('db-file-input').click();
    }
}

async function uploadDatabase(input) {
    const file = input.files[0];
    if (!file) return;
    const status = document.getElementById('upload-status');
    status.className = 'tool-status info';
    status.textContent = `Uploading ${file.name}...`;

    const formData = new FormData();
    formData.append('external_db', file);

    try {
        const res = await fetch('/api/import-inspect', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.status !== 'success') {
            status.className = 'tool-status error';
            status.textContent = '✘ ' + data.message;
            return;
        }
        _dbMeta = data;
        buildStep2();
        setImportStep(2);
    } catch (e) {
        status.className = 'tool-status error';
        status.textContent = '✘ Upload failed.';
    }
}

function buildStep2() {
    const tableSelect = document.getElementById('source-table');
    tableSelect._clearOptions();
    _dbMeta.tables.forEach(t => tableSelect._addOption(t, t, t.toLowerCase() === 'games'));
    onTableChange();
}

function onTableChange() {
    const table = document.getElementById('source-table').value;
    const cols = _dbMeta.table_columns[table] || [];

    const appidSel = document.getElementById('appid-col');
    appidSel._clearOptions();
    cols.forEach(c => appidSel._addOption(c, c, c.toLowerCase() === 'appid'));
    appidSel.addEventListener('change', onAppidColChange);

    document.getElementById('mapping-rows').innerHTML = '';
    addMappingRow();
    refreshTypeWarnings();
}

function onAppidColChange() {
    const appidCol = document.getElementById('appid-col').value;
    document.querySelectorAll('#mapping-rows .mapping-row').forEach(row => {
        const srcSel = row.querySelector('[data-role="source"]');
        if (!srcSel) return;
        const cur = srcSel.value;
        const table = document.getElementById('source-table').value;
        const allCols = _dbMeta.table_columns[table] || [];
        srcSel._setOptions(allCols.filter(c => c !== appidCol).map(c =>
            `<option value="${c}"${c === cur ? ' selected' : ''}>${c}</option>`
        ).join(''));
    });
}

function addMappingRow() {
    const table = document.getElementById('source-table').value;
    const appidCol = document.getElementById('appid-col').value;
    const sourceCols = (_dbMeta.table_columns[table] || []).filter(c => c !== appidCol);
    const targetCols = (_dbMeta.local_columns || []).filter(c => c.toLowerCase() !== 'appid');
    const srcTypes = _dbMeta.table_column_types?.[table] || {};
    const tgtTypes = _dbMeta.local_column_types || {};

    const row = document.createElement('div');
    row.className = 'mapping-row';

    const srcSel = buildColSelect(sourceCols, 'source');
    const arrow = document.createElement('div');
    arrow.className = 'mapping-arrow';
    const tgtSel = buildColSelect(targetCols, 'target');
    const removeBtn = document.createElement('button');
    removeBtn.className = 'mapping-remove';
    removeBtn.textContent = '✕';
    removeBtn.onclick = () => { row.remove(); refreshTypeWarnings(); };

    function isNumeric(t) { return /INT|NUM|REAL|FLOAT/.test((t||'').toUpperCase()); }

    function updateArrow() {
        const sType = srcTypes[srcSel.value] || '';
        const tType = tgtTypes[tgtSel.value] || '';
        if (sType && tType && isNumeric(sType) !== isNumeric(tType)) {
            arrow.textContent = '⚠';
            arrow.title = `Type mismatch: ${sType} → ${tType}`;
            arrow.style.color = 'var(--color-warning)';
        } else {
            arrow.textContent = '→';
            arrow.title = sType && tType ? `${sType} → ${tType}` : '';
            arrow.style.color = 'var(--text-secondary)';
        }
        refreshTypeWarnings();
    }

    srcSel.addEventListener('change', updateArrow);
    tgtSel.addEventListener('change', updateArrow);
    updateArrow();

    row.appendChild(srcSel);
    row.appendChild(arrow);
    row.appendChild(tgtSel);
    row.appendChild(removeBtn);
    document.getElementById('mapping-rows').appendChild(row);
}

function refreshTypeWarnings() {
    const table = document.getElementById('source-table').value;
    const srcTypes = _dbMeta.table_column_types?.[table] || {};
    const tgtTypes = _dbMeta.local_column_types || {};
    const rows = document.querySelectorAll('#mapping-rows .mapping-row');
    const warnings = [];

    function isNumeric(t) { return /INT|NUM|REAL|FLOAT/.test((t||'').toUpperCase()); }

    rows.forEach(row => {
        const src = row.querySelector('[data-role="source"]').value;
        const tgt = row.querySelector('[data-role="target"]').value;
        const sType = srcTypes[src] || '';
        const tType = tgtTypes[tgt] || '';
        if (sType && tType && isNumeric(sType) !== isNumeric(tType)) {
            warnings.push(`<strong>${escHtml(src)}</strong> (${escHtml(sType)}) → <strong>${escHtml(tgt)}</strong> (${escHtml(tType)}): values will be imported as-is and may not sort correctly`);
        }
    });

    const warnDiv = document.getElementById('import-type-warning');
    if (warnings.length) {
        warnDiv.style.display = 'block';
        warnDiv.innerHTML = '<strong>⚠ Type mismatches detected:</strong><br>' + warnings.map(w => `• ${w}`).join('<br>');
    } else {
        warnDiv.style.display = 'none';
    }
}

function buildColSelect(cols, role) {
    const native = document.createElement('select');
    native.dataset.role = role;
    cols.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c;
        opt.textContent = c;
        native.appendChild(opt);
    });
    return initCustomSelect(native);
}

async function executeImport() {
    const status = document.getElementById('import-status');
    const table = document.getElementById('source-table').value;
    const appidCol = document.getElementById('appid-col').value;
    const normalizeDates = document.getElementById('normalize-dates').checked;

    const rows = document.querySelectorAll('#mapping-rows .mapping-row');
    const mappings = Array.from(rows).map(row => ({
        source: row.querySelector('[data-role="source"]').value,
        target: row.querySelector('[data-role="target"]').value,
    }));

    if (mappings.length === 0) {
        status.className = 'tool-status error';
        status.textContent = 'Add at least one column mapping.';
        return;
    }

    status.className = 'tool-status info';
    status.textContent = 'Importing...';

    try {
        const res = await fetch('/api/import-execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ table, appid_column: appidCol, mappings, normalize_dates: normalizeDates })
        });
        const data = await res.json();
        if (data.status === 'success') {
            const warnings = data.type_warnings || [];
            const warnHtml = warnings.length
                ? `<div style="margin-top:10px; color:var(--color-warning); font-size:0.8rem;"><strong>⚠ Type warnings:</strong><br>${warnings.map(w => `• ${w}`).join('<br>')}</div>`
                : '';
            document.getElementById('import-result').innerHTML = `
                <div style="color:var(--accent-positive); font-size: 1rem; margin-bottom: 8px;">✔ Import complete</div>
                <div>Updated: <strong>${data.updated}</strong> games</div>
                <div>Skipped (no match or empty): <strong>${data.skipped}</strong> games</div>
                ${warnHtml}
            `;
            setImportStep(3);
        } else {
            status.className = 'tool-status error';
            status.textContent = '✘ ' + data.message;
        }
    } catch (e) {
        status.className = 'tool-status error';
        status.textContent = '✘ Network error.';
    }
}

function resetImport() {
    _dbMeta = null;
    document.getElementById('db-file-input').value = '';
    document.getElementById('upload-status').textContent = '';
    document.getElementById('mapping-rows').innerHTML = '';
    document.getElementById('import-result').innerHTML = '';
    document.getElementById('import-status').textContent = '';
    setImportStep(1);
}

// ── BACKUP ──────────────────────────────────────────────────────────────────
async function runBackup() {
    if (_fileDlgBusy) return;
    const btn        = document.getElementById('backup-btn');
    const status     = document.getElementById('backup-status');
    const includeArt = document.getElementById('backup-include-art').checked;

    const now = new Date();
    const ts  = now.getFullYear().toString()
        + String(now.getMonth()+1).padStart(2,'0')
        + String(now.getDate()).padStart(2,'0')
        + '_' + String(now.getHours()).padStart(2,'0')
        + String(now.getMinutes()).padStart(2,'0')
        + String(now.getSeconds()).padStart(2,'0');
    const suggestedName = `playdate_backup_${ts}.zip`;

    _fileDlgBusy = true;
    btn.disabled = true;
    btn.textContent = 'Creating backup…';
    status.className = 'tool-status info';
    status.innerHTML = (includeArt
        ? 'Building backup (including cover art — this may take a moment)…'
        : 'Building backup…')
        + '<br><strong style="color:var(--color-warning);">⚠ Do not close PlayDate until this finishes.</strong>';

    try {
        // ── Path 1: pywebview native Save-As dialog ──────────────────────────
        if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_save_path) {
            const chosenPath = await window.pywebview.api.pick_save_path(suggestedName);
            if (!chosenPath) {
                status.textContent = 'Backup cancelled.';
                return;
            }

            const res = await fetch('/api/backup-to-path', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ include_art: includeArt, path: chosenPath })
            });
            const data = await res.json();
            if (data.status === 'success') {
                const sizeKB = Math.round((data.size || 0) / 1024);
                const sizeTxt = sizeKB > 1024 ? `${(sizeKB/1024).toFixed(1)} MB` : `${sizeKB} KB`;
                status.className = 'tool-status success';
                status.textContent = `✔ Backup saved (${sizeTxt}) → ${chosenPath}`;
            } else {
                throw new Error(data.message || 'Unknown error');
            }
            return;
        }

        // ── Path 2: browser fallback (download) ──────────────────────────────
        const res = await fetch('/api/backup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ include_art: includeArt })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.message || `Server error ${res.status}`);
        }

        const disposition = res.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="?([^"]+)"?/);
        const filename = match ? match[1] : suggestedName;
        const blob = await res.blob();

        const url = URL.createObjectURL(blob);
        const a   = document.createElement('a');
        a.href     = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        const sizeKB = Math.round(blob.size / 1024);
        const sizeTxt = sizeKB > 1024 ? `${(sizeKB/1024).toFixed(1)} MB` : `${sizeKB} KB`;
        status.className = 'tool-status success';
        status.textContent = `✔ Backup downloaded as ${filename}  (${sizeTxt})`;

    } catch (e) {
        status.className = 'tool-status error';
        status.textContent = '✘ ' + e.message;
    } finally {
        setTimeout(() => { _fileDlgBusy = false; }, 300);
        btn.disabled = false;
        btn.textContent = 'Download Backup';
    }
}

// ── RESTORE ─────────────────────────────────────────────────────────────────
let _restoreFile = null;
let _restorePath = null;

async function chooseRestoreFile() {
    if (_fileDlgBusy) return;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_open_path) {
        _fileDlgBusy = true;
        let path;
        try {
            path = await window.pywebview.api.pick_open_path(['ZIP Files (*.zip)']);
        } finally {
            setTimeout(() => { _fileDlgBusy = false; }, 300);
        }
        if (!path) return;
        _restorePath = path;
        _restoreFile = null;
        const label = document.getElementById('restore-filename');
        label.textContent = `Selected: ${path.split(/[\\/]/).pop()}`;
        label.style.display = 'block';
        const btn = document.getElementById('restore-btn');
        btn.style.opacity = '1';
        btn.style.cursor  = 'pointer';
        document.getElementById('restore-status').textContent = '';
    } else {
        document.getElementById('restore-file-input').click();
    }
}

function restoreDragOver(e) {
    e.preventDefault();
    const zone = document.getElementById('restore-drop-zone');
    zone.style.borderColor = 'var(--accent)';
    zone.style.background  = 'rgba(102,192,244,0.05)';
}

function restoreDragLeave(e) {
    const zone = document.getElementById('restore-drop-zone');
    zone.style.borderColor = 'var(--border)';
    zone.style.background  = '';
}

function restoreDrop(e) {
    e.preventDefault();
    restoreDragLeave(e);
    const file = e.dataTransfer.files[0];
    if (file) setRestoreFile(file);
}

function restoreFileSelected(input) {
    if (input.files[0]) setRestoreFile(input.files[0]);
}

function setRestoreFile(file) {
    if (!file.name.endsWith('.zip')) {
        const status = document.getElementById('restore-status');
        status.className = 'tool-status error';
        status.textContent = '✘ Please select a .zip file.';
        return;
    }
    _restoreFile = file;
    _restorePath = null;

    const label = document.getElementById('restore-filename');
    label.textContent = `Selected: ${file.name}  (${(file.size / 1024).toFixed(0)} KB)`;
    label.style.display = 'block';

    const btn = document.getElementById('restore-btn');
    btn.style.opacity = '1';
    btn.style.cursor  = 'pointer';

    document.getElementById('restore-status').textContent = '';
}

// Shared by the Settings modal's Backup/Restore tab (this file) and the
// first-run Configuration modal's "Restore from Backup" button
// (modal_edit.html's configRunRestore) — both hit the same backend restore
// flow, so the client-side polling/status logic only needs to exist once.
// statusEl is required; btn (disabled/relabeled while running) and
// confirmMessage (skipped entirely when omitted -- the first-run modal has
// nothing of the user's to overwrite yet, so it doesn't ask) are optional.
async function runBackupRestore(source, { statusEl, btn = null, confirmMessage = null, reloadDelay = 1200 }) {
    if (confirmMessage) {
        const confirmed = await confirm(confirmMessage);
        if (!confirmed) return;
    }

    if (btn) {
        btn.style.opacity = '0.4';
        btn.style.cursor  = 'not-allowed';
        btn.textContent   = 'Restoring…';
    }
    statusEl.className   = 'tool-status info';
    statusEl.textContent = 'Restoring — please wait…';

    try {
        let res;
        if (source.path) {
            res = await fetch('/api/restore-from-path', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: source.path })
            });
        } else {
            const formData = new FormData();
            formData.append('backup_file', source.file);
            res = await fetch('/api/restore', { method: 'POST', body: formData });
        }
        const started = await res.json();
        if (started.status !== 'started') throw new Error(started.message || 'Restore failed.');

        // Extraction runs in a background thread on the server (a large backup
        // can take a while, especially over a Flatpak portal-mounted path) —
        // poll for completion instead of waiting on the original request.
        let data;
        while (true) {
            await new Promise(r => setTimeout(r, 700));
            const poll = await fetch('/api/restore-status');
            data = await poll.json();
            if (data.status !== 'running') break;
        }

        if (data.status !== 'success') throw new Error(data.error || 'Restore failed.');

        statusEl.className   = 'tool-status success';
        statusEl.textContent = `✔ Restored: ${data.restored.join(', ')}. Reloading…`;

        setTimeout(() => window.location.reload(), reloadDelay);
    } catch (e) {
        statusEl.className   = 'tool-status error';
        statusEl.textContent = '✘ ' + e.message;
        if (btn) {
            btn.style.opacity = '1';
            btn.style.cursor  = 'pointer';
            btn.textContent   = 'Restore';
        }
    }
}

async function runRestore() {
    if (!_restoreFile && !_restorePath) return;

    const name   = _restoreFile ? _restoreFile.name : _restorePath.split(/[\\/]/).pop();
    const source = _restorePath ? { path: _restorePath } : { file: _restoreFile };

    await runBackupRestore(source, {
        statusEl: document.getElementById('restore-status'),
        btn: document.getElementById('restore-btn'),
        confirmMessage:
            `Restore from "${name}"?\n\n` +
            `This will overwrite your current games.db, config.json, and state.json.\n` +
            `The page will reload after restore completes.`,
        reloadDelay: 1500,
    });
}

// ── BACKGROUND CHANGER ──────────────────────────────────────────────────────
let _bgFile = null;
let _bgFilePath = null;
let _bgObjectUrl = null;

function _showBgPreview(url) {
    const img  = document.getElementById('bg-preview-img');
    const wrap = document.getElementById('bg-preview-wrap');
    img.src = url;
    wrap.style.display = 'block';
}
async function _showBgPreviewFromPath(path) {
    try {
        const resp = await fetch('/api/preview-bg-from-path?path=' + encodeURIComponent(path), {
            headers: { 'X-PlayDate-Internal': '1' }
        });
        if (!resp.ok) throw new Error('preview failed');
        const blob = await resp.blob();
        if (_bgObjectUrl) URL.revokeObjectURL(_bgObjectUrl);
        _bgObjectUrl = URL.createObjectURL(blob);
        _showBgPreview(_bgObjectUrl);
    } catch (e) {
        _hideBgPreview();
    }
}
function _hideBgPreview() {
    if (_bgObjectUrl) { URL.revokeObjectURL(_bgObjectUrl); _bgObjectUrl = null; }
    const wrap = document.getElementById('bg-preview-wrap');
    const img  = document.getElementById('bg-preview-img');
    wrap.style.display = 'none';
    img.src = '';
}

async function chooseBgFile() {
    if (_fileDlgBusy) return;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_open_path) {
        _fileDlgBusy = true;
        let path;
        try {
            path = await window.pywebview.api.pick_open_path();
        } finally {
            setTimeout(() => { _fileDlgBusy = false; }, 300);
        }
        if (!path) return;
        _bgFile = null;
        _bgFilePath = path;
        const label = document.getElementById('bg-filename');
        label.textContent = `Selected: ${path.split(/[\\/]/).pop()}`;
        label.style.display = 'block';
        document.getElementById('bg-status').textContent = '';
        _hideBgPreview();
        _showBgPreviewFromPath(path);
    } else {
        document.getElementById('bg-file-input').click();
    }
}

function bgDragOver(e) {
    e.preventDefault();
    const zone = document.getElementById('bg-drop-zone');
    zone.style.borderColor = 'var(--accent)';
    zone.style.background  = 'rgba(102,192,244,0.05)';
}

function bgDragLeave(e) {
    const zone = document.getElementById('bg-drop-zone');
    zone.style.borderColor = 'var(--border)';
    zone.style.background  = '';
}

function bgDrop(e) {
    e.preventDefault();
    bgDragLeave(e);
    const file = e.dataTransfer.files[0];
    if (file) setBgFile(file);
}

function bgFileSelected(input) {
    if (input.files[0]) setBgFile(input.files[0]);
}

function setBgFile(file) {
    const allowed = ['image/jpeg', 'image/png', 'image/webp'];
    const status  = document.getElementById('bg-status');
    if (!allowed.includes(file.type)) {
        status.className = 'tool-status error';
        status.textContent = '✘ Unsupported format. Use JPG, PNG, or WebP.';
        return;
    }
    _bgFile = file;
    _bgFilePath = null;
    const label = document.getElementById('bg-filename');
    label.textContent = `Selected: ${file.name}  (${(file.size / 1024).toFixed(0)} KB)`;
    label.style.display = 'block';
    status.textContent = '';
    if (_bgObjectUrl) { URL.revokeObjectURL(_bgObjectUrl); }
    _bgObjectUrl = URL.createObjectURL(file);
    _showBgPreview(_bgObjectUrl);
}

async function runSetBackground() {
    const btn    = document.getElementById('bg-upload-btn');
    const status = document.getElementById('bg-status');
    const opacity = parseFloat(document.getElementById('bg-opacity-slider').value);

    btn.disabled    = true;
    btn.textContent = 'Saving…';
    status.className   = 'tool-status info';
    status.textContent = 'Saving…';

    try {
        // Always save opacity
        await fetch('/api/theme', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme: { '--bg-image-opacity': String(opacity) } })
        });

        // Upload new image if one was selected
        if (_bgFilePath) {
            const res  = await fetch('/api/set-background-from-path', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: _bgFilePath })
            });
            const data = await res.json();
            if (data.status !== 'success') throw new Error(data.message || 'Upload failed');
            status.className   = 'tool-status success';
            status.textContent = '✔ Background updated. Reloading…';
            setTimeout(() => window.location.reload(), 800);
        } else if (_bgFile) {
            const formData = new FormData();
            formData.append('background', _bgFile);
            const res  = await fetch('/api/set-background', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.status !== 'success') throw new Error(data.message || 'Upload failed');
            status.className   = 'tool-status success';
            status.textContent = '✔ Background updated. Reloading…';
            setTimeout(() => window.location.reload(), 800);
        } else {
            status.className   = 'tool-status success';
            status.textContent = '✔ Saved.';
            btn.disabled    = false;
            btn.textContent = 'Save';
            setTimeout(() => { status.textContent = ''; status.className = 'tool-status'; }, 2000);
        }
    } catch (e) {
        status.className   = 'tool-status error';
        status.textContent = '✘ ' + e.message;
        btn.disabled    = false;
        btn.textContent = 'Save';
    }
}

async function runResetBackground() {
    const status = document.getElementById('bg-status');
    if (!await confirm('Reset the background to the default image?')) return;
    const btn = document.getElementById('bg-reset-btn');
    btn.disabled    = true;
    btn.textContent = 'Resetting…';
    status.className   = 'tool-status info';
    status.textContent = 'Resetting…';
    try {
        const res  = await fetch('/api/reset-background', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            status.className   = 'tool-status success';
            status.textContent = '✔ Background reset. Reloading…';
            setTimeout(() => window.location.reload(), 800);
        } else {
            throw new Error(data.message || 'Unknown error');
        }
    } catch (e) {
        status.className   = 'tool-status error';
        status.textContent = '✘ ' + e.message;
    } finally {
        btn.disabled    = false;
        btn.textContent = 'Reset to Default';
    }
}

// ── BLACKLIST MANAGER ────────────────────────────────────────────────────────
let _blacklistLoaded = false;
let _blEntries = [];

function openBlacklistModal() {
    document.getElementById('blacklist-modal').style.display = 'flex';
    if (!_blacklistLoaded) _loadBlacklist();
}
function closeBlacklistModal() {
    document.getElementById('blacklist-modal').style.display = 'none';
    const s = document.getElementById('blacklist-search');
    s.value = '';
    _filterBlacklist('');
}

function _blPlatLabel(platform) {
    if (!platform) return 'Unknown';
    return (window._PLAT_LABELS && window._PLAT_LABELS[platform]) || platform;
}

function _blRenderGroups(entries) {
    const groups = document.getElementById('blacklist-groups');
    const byPlat = {};
    entries.forEach(e => {
        const key = e.platform || 'unknown';
        (byPlat[key] = byPlat[key] || []).push(e);
    });
    const platKeys = Object.keys(byPlat).sort((a, b) => {
        if (a === 'steam') return -1;
        if (b === 'steam') return 1;
        return _blPlatLabel(a).localeCompare(_blPlatLabel(b));
    });

    const showGroupSelectAll = platKeys.length > 1;
    groups.innerHTML = platKeys.map(plat => `
        <div class="bl-group" data-plat="${plat}">
            <div style="display:flex; justify-content:space-between; align-items:center; margin:14px 0 6px;">
                <div style="color:var(--text-secondary); font-size:0.78rem; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;">${escHtml(_blPlatLabel(plat))} (${byPlat[plat].length})</div>
                ${showGroupSelectAll ? `
                <div data-modal-row="bl-selectall-${plat}" onclick="var cb=this.querySelector('input');cb.checked=!cb.checked;_blToggleGroup('${plat}',cb.checked);" style="display:flex; align-items:center; gap:5px; cursor:pointer;">
                    <input type="checkbox" class="bl-group-cb" data-plat="${plat}" style="width:auto;margin:0;" onclick="event.stopPropagation();_blToggleGroup('${plat}',this.checked)">
                    <label style="color:var(--text-secondary); font-size:0.78rem; cursor:pointer;">Select All</label>
                </div>` : ''}
            </div>
            <table style="width:100%; border-collapse:collapse;">
                <tbody>
                    ${byPlat[plat].map(e => `
                        <tr id="bl-row-${e.appid}" class="bl-row" data-name="${escHtml((e.name || '').toLowerCase())}" style="border-bottom:1px solid var(--border);">
                            <td style="padding:9px 6px; width:1%;">
                                <div data-modal-row="bl-${e.appid}" onclick="var cb=this.querySelector('input');cb.checked=!cb.checked;" style="display:inline-flex;cursor:pointer;padding:4px;">
                                    <input type="checkbox" class="bl-cb" data-appid="${e.appid}" style="width:auto;margin:0;" onclick="event.stopPropagation()">
                                </div>
                            </td>
                            <td style="padding:9px 10px; color:var(--text-primary); font-size:0.88rem;">${escHtml(e.name || '—')}</td>
                            <td style="padding:9px 10px; color:var(--text-secondary); font-size:0.82rem; font-family:monospace;">${e.appid}</td>
                            <td style="padding:9px 10px; color:var(--text-secondary); font-size:0.82rem;">${e.date_blacklisted || '—'}</td>
                            <td style="padding:9px 10px; text-align:right;">
                                <button onclick="removeFromBlacklist(${e.appid}, this)" class="bl-remove-btn" data-modal-row="bl-${e.appid}"
                                    style="background:none; border:1px solid var(--color-danger); color:var(--text-danger); border-radius:4px; padding:3px 10px; font-size:0.78rem; cursor:pointer; transition:background 0.15s;"
                                    onmouseover="this.style.background='rgba(163,42,42,0.2)'"
                                    onmouseout="this.style.background='none'">Remove</button>
                            </td>
                        </tr>`).join('')}
                </tbody>
            </table>
        </div>`).join('');
}

async function _loadBlacklist() {
    const status = document.getElementById('blacklist-status');
    const empty  = document.getElementById('blacklist-empty');
    const bulkbar = document.getElementById('blacklist-bulkbar');

    status.className = 'tool-status info';
    status.textContent = 'Loading…';

    try {
        const res  = await fetch('/api/blacklist');
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.message);

        status.textContent = '';
        _blacklistLoaded = true;
        _blEntries = data.entries || [];

        if (_blEntries.length === 0) {
            empty.style.display = 'block';
            bulkbar.style.display = 'none';
            document.getElementById('blacklist-groups').innerHTML = '';
            return;
        }

        document.getElementById('blacklist-search').style.display = 'block';
        empty.style.display = 'none';
        bulkbar.style.display = 'flex';
        document.getElementById('blacklist-select-all').checked = false;
        _blRenderGroups(_blEntries);
    } catch (e) {
        status.className = 'tool-status error';
        status.textContent = '✘ ' + e.message;
    }
}

function _filterBlacklist(query) {
    const q = query.trim().toLowerCase();
    const rows = document.querySelectorAll('#blacklist-groups .bl-row');
    let visible = 0;
    rows.forEach(row => {
        const show = !q || (row.dataset.name || '').includes(q);
        row.style.display = show ? '' : 'none';
        if (show) visible++;
    });
    document.querySelectorAll('#blacklist-groups .bl-group').forEach(group => {
        const anyVisible = [...group.querySelectorAll('.bl-row')].some(r => r.style.display !== 'none');
        group.style.display = anyVisible ? '' : 'none';
    });
    document.getElementById('blacklist-no-results').style.display = (visible === 0 && _blEntries.length > 0) ? 'block' : 'none';
}

function _blToggleAll(checked) {
    document.getElementById('blacklist-select-all').checked = checked;
    document.querySelectorAll('#blacklist-groups .bl-row').forEach(row => {
        if (row.style.display === 'none') return;
        const cb = row.querySelector('.bl-cb');
        if (cb) cb.checked = checked;
    });
    document.querySelectorAll('#blacklist-groups .bl-group-cb').forEach(cb => cb.checked = checked);
}

function _blToggleGroup(plat, checked) {
    const group = document.querySelector(`#blacklist-groups .bl-group[data-plat="${plat}"]`);
    if (!group) return;
    const groupCb = group.querySelector('.bl-group-cb');
    if (groupCb) groupCb.checked = checked;
    group.querySelectorAll('.bl-row').forEach(row => {
        if (row.style.display === 'none') return;
        const cb = row.querySelector('.bl-cb');
        if (cb) cb.checked = checked;
    });

    // Keep the global Select All in sync: checked only if every visible row everywhere is checked.
    const allRows = [...document.querySelectorAll('#blacklist-groups .bl-row')].filter(r => r.style.display !== 'none');
    const allChecked = allRows.length > 0 && allRows.every(r => r.querySelector('.bl-cb')?.checked);
    document.getElementById('blacklist-select-all').checked = allChecked;
}

async function removeFromBlacklist(appid, btn) {
    btn.disabled = true;
    btn.textContent = '…';
    try {
        const res  = await fetch('/api/blacklist/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ appid })
        });
        const data = await res.json();
        if (data.status === 'success') {
            _blRemoveRowsFromState([appid]);
        } else {
            btn.disabled = false;
            btn.textContent = 'Remove';
            alert('Failed: ' + data.message);
        }
    } catch (e) {
        btn.disabled = false;
        btn.textContent = 'Remove';
        alert('Network error.');
    }
}

async function _blBulkRemove() {
    const selected = [...document.querySelectorAll('#blacklist-groups .bl-cb:checked')]
        .map(cb => parseInt(cb.dataset.appid, 10));
    if (selected.length === 0) {
        alert('No games selected.');
        return;
    }
    const ok = await confirmCustom(`Remove ${selected.length} selected game(s) from the blacklist?`, 'Remove', 'Cancel');
    if (!ok) return;

    const status = document.getElementById('blacklist-status');
    status.className = 'tool-status info';
    status.textContent = 'Removing…';
    try {
        const res  = await fetch('/api/blacklist/bulk-remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ appids: selected })
        });
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.message);
        status.className = 'tool-status success';
        status.textContent = `✔ Removed ${data.count}.`;
        _blRemoveRowsFromState(selected);
    } catch (e) {
        status.className = 'tool-status error';
        status.textContent = '✘ ' + e.message;
    }
}

function _blRemoveRowsFromState(appids) {
    const removedSet = new Set(appids);
    _blEntries = _blEntries.filter(e => !removedSet.has(e.appid));
    if (_blEntries.length === 0) {
        document.getElementById('blacklist-groups').innerHTML = '';
        document.getElementById('blacklist-bulkbar').style.display = 'none';
        document.getElementById('blacklist-empty').style.display = 'block';
    } else {
        _blRenderGroups(_blEntries);
        _filterBlacklist(document.getElementById('blacklist-search').value || '');
    }
}

// ── STEAM JUNK FINDER ────────────────────────────────────────────────────────
let _sjunkCandidates      = [];  // title-pattern matches only
let _sjunkOwnedCandidates = [];  // no-longer-owned matches only

function openSteamJunkModal() {
    document.getElementById('steam-junk-modal').style.display = 'flex';
    _loadSteamJunkScan();
}
function closeSteamJunkModal() {
    document.getElementById('steam-junk-modal').style.display = 'none';
}

async function _loadSteamJunkScan() {
    const status      = document.getElementById('sjunk-status');
    const empty       = document.getElementById('sjunk-empty');
    const results     = document.getElementById('sjunk-results');
    const list        = document.getElementById('sjunk-list');
    const ownedSection = document.getElementById('sjunk-owned-section');
    const ownedEmpty   = document.getElementById('sjunk-owned-empty');
    const ownedResults = document.getElementById('sjunk-owned-results');
    const ownedList     = document.getElementById('sjunk-owned-list');
    const ownNote       = document.getElementById('sjunk-owned-note');

    status.className = 'tool-status info';
    status.textContent = 'Scanning…';
    results.style.display = 'none';
    empty.style.display = 'none';
    ownedSection.style.display = 'none';
    ownedResults.style.display = 'none';
    ownedEmpty.style.display = 'none';
    ownNote.style.display = 'none';
    document.getElementById('sjunk-action-status').textContent = '';

    try {
        const res  = await fetch('/api/steam-junk-scan');
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.message);

        status.textContent = '';
        _sjunkCandidates      = data.pattern_candidates || [];
        _sjunkOwnedCandidates = data.owned_candidates || [];

        // ── No Longer Owned section ──
        const ownership = data.ownership || {};
        if (ownership.checked) {
            ownedSection.style.display = 'block';
            if (_sjunkOwnedCandidates.length === 0) {
                ownedEmpty.style.display = 'block';
            } else {
                document.getElementById('sjunk-owned-select-all').checked = false;
                ownedList.innerHTML = _sjunkOwnedCandidates.map((c, i) => `
                    <div data-modal-row="sjunk-owned-${i}" onclick="var cb=this.querySelector('.sjunk-owned-cb');cb.checked=!cb.checked;"
                        style="display:flex; align-items:center; gap:8px; padding:6px 4px; cursor:pointer; border-bottom:1px solid var(--border);">
                        <input type="checkbox" class="sjunk-owned-cb" data-appid="${c.appid}" style="width:auto;margin:0;flex-shrink:0;" onclick="event.stopPropagation()">
                        <span style="color:var(--text-primary); font-size:0.85rem; flex:1;">${escHtml(c.name)}</span>
                        <span style="color:var(--text-secondary); font-size:0.75rem; font-family:monospace;">${c.appid}</span>
                    </div>`).join('');
                ownedResults.style.display = 'block';
            }
        } else if (ownership.error) {
            ownedSection.style.display = 'block';
            ownNote.style.display = 'block';
            ownNote.style.color = 'var(--color-warning)';
            ownNote.textContent = `Couldn't check current Steam ownership: ${ownership.error}`;
        } else {
            ownedSection.style.display = 'block';
            ownNote.style.display = 'block';
            ownNote.style.color = 'var(--text-secondary)';
            ownNote.textContent = 'Needs a Steam API key configured (Steam Account settings) to run this check.';
        }

        // ── Title-Pattern Matches section ──
        if (_sjunkCandidates.length === 0) {
            empty.style.display = 'block';
            return;
        }

        document.getElementById('sjunk-select-all').checked = false;
        list.innerHTML = _sjunkCandidates.map((c, i) => `
            <div data-modal-row="sjunk-${i}" onclick="var cb=this.querySelector('.sjunk-cb');cb.checked=!cb.checked;"
                style="display:flex; align-items:center; gap:8px; padding:6px 4px; cursor:pointer; border-bottom:1px solid var(--border);">
                <input type="checkbox" class="sjunk-cb" data-appid="${c.appid}" style="width:auto;margin:0;flex-shrink:0;" onclick="event.stopPropagation()">
                <span style="color:var(--text-primary); font-size:0.85rem; flex:1;">${escHtml(c.name)}</span>
                <span style="color:var(--text-secondary); font-size:0.75rem; font-family:monospace;">${c.appid}</span>
                <span style="color:var(--text-secondary); font-size:0.72rem; white-space:nowrap;">[${c.reasons.map(escHtml).join(', ')}]</span>
            </div>`).join('');
        results.style.display = 'block';
    } catch (e) {
        status.className = 'tool-status error';
        status.textContent = '✘ ' + e.message;
    }
}

function _sjunkToggleAll(checked) {
    document.getElementById('sjunk-select-all').checked = checked;
    document.querySelectorAll('#sjunk-list .sjunk-cb').forEach(cb => cb.checked = checked);
}

function _sjunkOwnedToggleAll(checked) {
    document.getElementById('sjunk-owned-select-all').checked = checked;
    document.querySelectorAll('#sjunk-owned-list .sjunk-owned-cb').forEach(cb => cb.checked = checked);
}

async function _sjunkAction(action) {
    const selected = [...document.querySelectorAll('#sjunk-list .sjunk-cb:checked')]
        .map(cb => parseInt(cb.dataset.appid, 10));
    if (selected.length === 0) {
        alert('No games selected.');
        return;
    }
    const verb = action === 'blacklist' ? 'blacklist' : 'whitelist';
    const ok = await confirmCustom(
        `${verb === 'blacklist' ? 'Delete and blacklist' : 'Whitelist (dismiss)'} ${selected.length} selected game(s)?`,
        'Confirm', 'Cancel'
    );
    if (!ok) return;

    const status = document.getElementById('sjunk-action-status');
    status.className = 'tool-status info';
    status.textContent = 'Working…';
    try {
        const res  = await fetch(`/api/steam-junk-scan/${action}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ appids: selected })
        });
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.message);

        status.className = 'tool-status success';
        status.textContent = `✔ ${verb === 'blacklist' ? 'Blacklisted' : 'Whitelisted'} ${data.count}.`;
        _sjunkCandidates = _sjunkCandidates.filter(c => !selected.includes(c.appid));
        if (_sjunkCandidates.length === 0) {
            document.getElementById('sjunk-results').style.display = 'none';
            document.getElementById('sjunk-empty').style.display = 'block';
        } else {
            selected.forEach(appid => {
                document.querySelector(`#sjunk-list .sjunk-cb[data-appid="${appid}"]`)?.closest('[data-modal-row]')?.remove();
            });
        }
        if (action === 'blacklist') _blacklistLoaded = false; // force reload next time Blacklist Manager is opened
    } catch (e) {
        status.className = 'tool-status error';
        status.textContent = '✘ ' + e.message;
    }
}

async function _sjunkOwnedDelete() {
    const selected = [...document.querySelectorAll('#sjunk-owned-list .sjunk-owned-cb:checked')]
        .map(cb => parseInt(cb.dataset.appid, 10));
    if (selected.length === 0) {
        alert('No games selected.');
        return;
    }
    const ok = await confirmCustom(
        `Delete ${selected.length} selected game(s) from PlayDate? They're no longer on your Steam account, so this won't blacklist them -- there's nothing left for "Populate PlayDate" to re-add.`,
        'Delete', 'Cancel'
    );
    if (!ok) return;

    const status = document.getElementById('sjunk-action-status');
    status.className = 'tool-status info';
    status.textContent = 'Working…';
    try {
        const res  = await fetch('/api/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ appids: selected })
        });
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.message);

        status.className = 'tool-status success';
        status.textContent = `✔ Deleted ${data.deleted}.`;
        _sjunkOwnedCandidates = _sjunkOwnedCandidates.filter(c => !selected.includes(c.appid));
        if (_sjunkOwnedCandidates.length === 0) {
            document.getElementById('sjunk-owned-results').style.display = 'none';
            document.getElementById('sjunk-owned-empty').style.display = 'block';
        } else {
            selected.forEach(appid => {
                document.querySelector(`#sjunk-owned-list .sjunk-owned-cb[data-appid="${appid}"]`)?.closest('[data-modal-row]')?.remove();
            });
        }
    } catch (e) {
        status.className = 'tool-status error';
        status.textContent = '✘ ' + e.message;
    }
}

// ── Theme Preview Tab Switcher ───────────────────────────────────────────────
function tpSwitchTab(btn, paneId) {
    btn.closest('.tp-tabs').querySelectorAll('.tp-tab').forEach(t => t.classList.remove('active'));
    btn.closest('.theme-preview-panel').querySelectorAll('.tp-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(paneId).classList.add('active');
}

// ── Theme Editor ─────────────────────────────────────────────────────────────

const THEME_VAR_META = [
    // ── Backgrounds ──
    { key: '--bg-page',          group: 'Backgrounds', label: 'Page Background',    desc: 'Window body behind all surfaces' },
    { key: '--bg-surface',       group: 'Backgrounds', label: 'Surface',            desc: 'Primary UI surface — toolbars, panels' },
    { key: '--bg-raised',        group: 'Backgrounds', label: 'Raised Surface',     desc: 'Modals, dropdowns, context menus' },
    { key: '--bg-input',         group: 'Backgrounds', label: 'Input Background',   desc: 'Text fields and inset areas' },
    { key: '--bg-card',          group: 'Backgrounds', label: 'Card Background',    desc: 'Game cards in grids and shelves' },
    { key: '--bg-nav',           group: 'Backgrounds', label: 'Nav Background',     desc: 'Top navigation bar' },
    // ── Text ──
    { key: '--text-primary',     group: 'Text',        label: 'Body Text',          desc: 'Main readable text throughout the app' },
    { key: '--text-heading',     group: 'Text',        label: 'Heading Text',       desc: 'Page headings and shelf titles' },
    { key: '--text-secondary',   group: 'Text',        label: 'Secondary Text',     desc: 'Captions, labels, subdued text' },
    { key: '--text-input',       group: 'Text',        label: 'Input Text',         desc: 'Text typed inside fields and selects' },
    { key: '--text-bright',      group: 'Text',        label: 'Bright Text',        desc: 'High-contrast text on colored surfaces' },
    // ── Accent ──
    { key: '--accent',           group: 'Accent',      label: 'Accent',             desc: 'Links, focus rings, active highlights' },
    { key: '--on-accent',        group: 'Accent',      label: 'On Accent',          desc: 'Text on accent-colored surfaces' },
    { key: '--accent-positive',  group: 'Accent',      label: 'Positive',           desc: 'Save buttons and success indicators' },
    // ── Borders ──
    { key: '--border',           group: 'Borders',     label: 'Border',             desc: 'All panel and input borders' },
    // ── Status ──
    { key: '--color-danger',     group: 'Status',      label: 'Danger',             desc: 'Exit, delete, and destructive action surfaces' },
    { key: '--text-danger',      group: 'Status',      label: 'Danger Text',        desc: 'Red warning and error text' },
    { key: '--color-warning',    group: 'Status',      label: 'Warning',            desc: 'Amber caution indicators' },
];

let _themeVars    = {};   // currently displayed values (may be unsaved)
let _themeDefs    = {};   // server-side defaults
let _themeApplied = {};   // last-saved snapshot — restored on modal close without Apply

function openThemeModal() {
    document.getElementById('theme-modal').style.display = 'flex';
    if (Object.keys(_themeVars).length === 0) {
        _themeLoad();
    }
}
function closeThemeModal() {
    _themeRevert();
    document.getElementById('theme-modal').style.display = 'none';
}

function _themeRevert() {
    // Restore every known CSS var to its last-applied value (or default), discarding unsaved edits
    for (const meta of THEME_VAR_META) {
        const val = _themeApplied[meta.key] || _themeDefs[meta.key];
        if (val) {
            _applyVarToDocument(meta.key, val);
        } else {
            document.documentElement.style.removeProperty(meta.key);
        }
    }
    _themeVars = Object.assign({}, _themeApplied);
}

async function _themeLoad() {
    const panel = document.getElementById('theme-vars-panel');
    panel.innerHTML = '<div style="color:var(--text-secondary);font-size:0.88rem;">Loading…</div>';
    try {
        const res  = await fetch('/api/theme');
        const data = await res.json();
        _themeVars    = Object.assign({}, data.theme);
        _themeDefs    = Object.assign({}, data.defaults);
        _themeApplied = Object.assign({}, data.theme);
        _themeRenderPanel();
        _loadSavedThemes();
    } catch (e) {
        panel.innerHTML = '<div style="color:var(--text-danger);font-size:0.88rem;">Failed to load theme.</div>';
    }
}

function _themeRenderPanel() {
    const panel = document.getElementById('theme-vars-panel');
    panel.innerHTML = '';

    let currentGroup = null;
    for (let i = 0; i < THEME_VAR_META.length; i++) {
        const meta = THEME_VAR_META[i];
        if (meta.group !== currentGroup) {
            currentGroup = meta.group;
            const header = document.createElement('div');
            header.style.cssText = 'font-size:0.7rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.08em;margin:10px 0 4px;padding-bottom:4px;border-bottom:1px solid var(--border);';
            if (panel.children.length === 0) header.style.marginTop = '0';
            header.textContent = currentGroup;
            panel.appendChild(header);
        }

        const rawVal = _themeVars[meta.key] || _themeApplied[meta.key] || _themeDefs[meta.key] || '#000000';
        const hexVal = _cssValueToHex(rawVal);
        const appliedVal = _cssValueToHex(_themeApplied[meta.key] || _themeDefs[meta.key] || '#000000');
        const isDefault = _cssValueToHex(_themeVars[meta.key] || '#000000') === appliedVal;
        const safeKey = meta.key.replace('--', '');

        const row = document.createElement('div');
        row.className = 'theme-var-row';
        row.innerHTML = `
            <div id="thpick-${safeKey}"
                 style="width:32px;height:32px;border-radius:6px;border:1px solid var(--border);background:${hexVal};cursor:pointer;flex-shrink:0;"
                 data-tooltip="Pick color" data-modal-row="${i + 1}"></div>
            <div class="theme-var-label">
                <strong>${meta.label}</strong>
                <span>${meta.desc}</span>
            </div>
            <input type="text" class="theme-var-hex"
                   id="thhex-${safeKey}"
                   value="${hexVal}" maxlength="9"
                   data-modal-row="${i + 1}"
                   oninput="themeHexChange('${meta.key}', this.value)"
                   onblur="themeHexBlur('${meta.key}', this.value)">
            <button data-tooltip="Reset to active theme" onclick="themeResetVar('${meta.key}')"
                    style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:0.9rem;padding:0 2px;opacity:${isDefault ? '0.25' : '1'};transition:opacity 0.15s;"
                    id="threset-${safeKey}" data-modal-row="${i + 1}">↺</button>
        `;
        panel.appendChild(row);
        const swatchEl = row.querySelector(`#thpick-${safeKey}`);
        swatchEl.addEventListener('click', () => {
            openColorPicker(swatchEl, swatchEl.style.background, hex => {
                swatchEl.style.background = hex;
                const hexEl = document.getElementById('thhex-' + safeKey);
                if (hexEl) hexEl.value = hex;
                themePickerChange(meta.key, hex);
            });
        });
    }
}

function _cssValueToHex(val) {
    if (/^#[0-9a-fA-F]{3,8}$/.test(val.trim())) return val.trim();
    const m = val.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (m) {
        return '#' + [m[1], m[2], m[3]].map(n => parseInt(n).toString(16).padStart(2, '0')).join('');
    }
    return '#000000';
}

function _applyVarToDocument(key, val) {
    document.documentElement.style.setProperty(key, val);
}

function _updateResetBtn(key, hex) {
    const safeKey = key.replace('--', '');
    const resetBtn = document.getElementById(`threset-${safeKey}`);
    if (resetBtn) {
        const appliedVal = _cssValueToHex(_themeApplied[key] || _themeDefs[key] || '#000000');
        resetBtn.style.opacity = (hex.toLowerCase() === appliedVal.toLowerCase()) ? '0.25' : '1';
    }
}

function themePickerChange(key, hex) {
    _themeVars[key] = hex;
    const safeKey = key.replace('--', '');
    const hexInput = document.getElementById(`thhex-${safeKey}`);
    if (hexInput) hexInput.value = hex;
    _applyVarToDocument(key, hex);
    _updateResetBtn(key, hex);
    _themeSetStatus('');
}

function themeHexChange(key, raw) {
    const clean = raw.trim();
    if (/^#[0-9a-fA-F]{6}$/.test(clean) || /^#[0-9a-fA-F]{3}$/.test(clean)) {
        _themeVars[key] = clean;
        const safeKey = key.replace('--', '');
        const picker = document.getElementById(`thpick-${safeKey}`);
        if (picker) picker.style.background = clean;
        _applyVarToDocument(key, clean);
        _updateResetBtn(key, clean);
        _themeSetStatus('');
    }
}

function themeHexBlur(key, raw) {
    const clean = raw.trim();
    if (!/^#[0-9a-fA-F]{3,8}$/.test(clean)) {
        const safeKey = key.replace('--', '');
        const hexInput = document.getElementById(`thhex-${safeKey}`);
        if (hexInput) hexInput.value = _cssValueToHex(_themeVars[key] || '#000000');
    }
}

function themeResetVar(key) {
    const defVal = _cssValueToHex(_themeApplied[key] || _themeDefs[key] || '#000000');
    _themeVars[key] = defVal;
    const safeKey = key.replace('--', '');
    const picker = document.getElementById(`thpick-${safeKey}`);
    const hexInput = document.getElementById(`thhex-${safeKey}`);
    const resetBtn = document.getElementById(`threset-${safeKey}`);
    if (picker) picker.style.background = defVal;
    if (hexInput) hexInput.value = defVal;
    if (resetBtn) resetBtn.style.opacity = '0.25';
    _applyVarToDocument(key, defVal);
    _themeSetStatus('');
}


async function themeExport() {
    if (Object.keys(_themeVars).length === 0) {
        _themeSetStatus('✘ Open the theme editor first to load a theme.', 'error');
        return;
    }
    if (_fileDlgBusy) return;
    _fileDlgBusy = true;

    const now = new Date();
    const ts  = now.getFullYear().toString()
        + String(now.getMonth()+1).padStart(2,'0')
        + String(now.getDate()).padStart(2,'0');
    const suggestedName = `playdate-theme-${ts}.json`;

    // ── Path 1: pywebview native Save-As dialog ──────────────────────────────
    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_save_path) {
        let chosenPath;
        try {
            chosenPath = await window.pywebview.api.pick_save_path(
                suggestedName, ['JSON Files (*.json)']
            );
        } finally {
            setTimeout(() => { _fileDlgBusy = false; }, 300);
        }
        if (!chosenPath) {
            _themeSetStatus('Export cancelled.', '');
            return;
        }
        try {
            const res  = await fetch('/api/theme-to-path', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme: _themeVars, path: chosenPath })
            });
            const data = await res.json();
            if (data.status === 'success') {
                _themeSetStatus(`✔ Theme saved → ${chosenPath}`, 'success');
            } else {
                _themeSetStatus('✘ ' + (data.message || 'Save failed.'), 'error');
            }
        } catch (e) {
            _themeSetStatus('✘ Network error.', 'error');
        }
        return;
    }
    setTimeout(() => { _fileDlgBusy = false; }, 300);

    // ── Path 2: browser blob download fallback ───────────────────────────────
    const payload = JSON.stringify({ playdate_theme: _themeVars }, null, 2);
    const blob = new Blob([payload], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = suggestedName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    _themeSetStatus('✔ Theme exported.', 'success');
}

// ── CSV EXPORT ───────────────────────────────────────────────────────────────

function toggleCsvColPicker() {
    const picker = document.getElementById('csv-col-picker');
    picker.style.display = picker.style.display === 'none' ? 'block' : 'none';
}

function csvColAll(state) {
    document.querySelectorAll('.csv-col-cb').forEach(cb => cb.checked = state);
}

function _csvSelectedCols() {
    const cbs = [...document.querySelectorAll('.csv-col-cb')];
    const checked = cbs.filter(cb => cb.checked).map(cb => cb.value);
    return checked.length === cbs.length ? null : checked; // null = all
}

let _fileDlgBusy = false;

async function runCsvExport() {
    if (_fileDlgBusy) return;
    _fileDlgBusy = true;
    try {
        const status  = document.getElementById('csv-export-status');
        const columns = _csvSelectedCols();
        if (columns && columns.length === 0) {
            status.className   = 'tool-status error';
            status.textContent = '✘ Select at least one column.';
            return;
        }
        status.className = 'tool-status info';
        status.textContent = 'Preparing export…';

        const now = new Date();
        const ts  = now.getFullYear().toString()
            + String(now.getMonth()+1).padStart(2,'0')
            + String(now.getDate()).padStart(2,'0')
            + '_' + String(now.getHours()).padStart(2,'0')
            + String(now.getMinutes()).padStart(2,'0');
        const suggestedName = `playdate_library_${ts}.csv`;

        // ── Path 1: pywebview native Save-As dialog ──────────────────────────────
        if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_save_path) {
            const chosenPath = await window.pywebview.api.pick_save_path(
                suggestedName, ['CSV Files (*.csv)']
            );
            if (!chosenPath) {
                status.textContent = 'Export cancelled.';
                status.className   = 'tool-status';
                return;
            }
            try {
                const res  = await fetch('/api/export-csv-to-path', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: chosenPath, filter_tree: null, columns })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const sizeKB = Math.round((data.size || 0) / 1024);
                    status.className   = 'tool-status success';
                    status.textContent = `✔ Exported ${data.count} games (${sizeKB} KB) → ${chosenPath}`;
                } else {
                    throw new Error(data.message || 'Export failed.');
                }
            } catch (e) {
                status.className   = 'tool-status error';
                status.textContent = '✘ ' + e.message;
            }
            return;
        }

        // ── Path 2: browser blob download fallback ───────────────────────────────
        try {
            const res = await fetch('/api/export-csv', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filter_tree: null, columns })
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.message || `Server error ${res.status}`);
            }
            const blob     = await res.blob();
            const url      = URL.createObjectURL(blob);
            const a        = document.createElement('a');
            a.href         = url;
            a.download     = suggestedName;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            const sizeKB = Math.round(blob.size / 1024);
            status.className   = 'tool-status success';
            status.textContent = `✔ Export downloaded (${sizeKB} KB)`;
        } catch (e) {
            status.className   = 'tool-status error';
            status.textContent = '✘ ' + e.message;
        }
    } finally {
        setTimeout(() => { _fileDlgBusy = false; }, 300);
    }
}

async function themeImportOpen() {
    if (_fileDlgBusy) return;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_open_path) {
        _fileDlgBusy = true;
        try {
            const path = await window.pywebview.api.pick_open_path(['PlayDate Theme (*.json)']);
            if (path) {
                const res = await fetch('/api/read-theme-file', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) });
                const data = await res.json();
                if (data.status !== 'success') { _themeSetStatus('✘ Could not read file.', 'error'); }
                else _themeImportText(data.text);
            }
        } catch (e) { _themeSetStatus('✘ Could not open file.', 'error'); }
        setTimeout(() => { _fileDlgBusy = false; }, 300);
    } else {
        document.getElementById('theme-import-input').click();
    }
}

function _themeImportText(text) {
    try {
        const parsed = JSON.parse(text);
        if (!parsed.playdate_theme || typeof parsed.playdate_theme !== 'object') {
            _themeSetStatus('✘ Not a valid PlayDate theme file.', 'error');
            return;
        }
        const incoming = parsed.playdate_theme;
        const knownKeys = new Set(THEME_VAR_META.map(m => m.key));
        let loaded = 0;
        const merged = Object.assign({}, _themeVars);
        for (const [k, v] of Object.entries(incoming)) {
            if (!knownKeys.has(k)) continue;
            const hex = _cssValueToHex(String(v));
            if (hex === '#000000' && !String(v).match(/^#?0{3,6}$|black/i)) continue;
            merged[k] = hex;
            loaded++;
        }
        if (loaded === 0) { _themeSetStatus('✘ No valid color values found in file.', 'error'); return; }
        _themeVars = merged;
        for (const [k, v] of Object.entries(_themeVars)) _applyVarToDocument(k, v);
        _themeRenderPanel();
        _themeSetStatus(`✔ Theme imported — ${loaded} color${loaded !== 1 ? 's' : ''} loaded. Name it and Save as… to keep it.`, 'success');
    } catch (err) {
        _themeSetStatus('✘ Could not parse file. Make sure it is a valid JSON theme.', 'error');
    }
}

function themeImport(input) {
    const file = input.files[0];
    input.value = '';
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => _themeImportText(e.target.result);
    reader.readAsText(file);
}

function _themeSetStatus(msg, cls) {
    const el = document.getElementById('theme-status');
    if (!el) return;
    el.textContent = msg;
    el.className = 'tool-status' + (cls ? ' ' + cls : '');
}

// ── PRESETS ───────────────────────────────────────────────────────────────────
const THEME_PRESETS = [
    {
        name: 'Steam Dark',
        vars: { '--bg-page':'#0e1419', '--bg-surface':'#1b2838', '--bg-raised':'#1a2332', '--bg-input':'#101822', '--bg-card':'#101822', '--bg-nav':'#171a21', '--text-primary':'#c7d5e0', '--text-heading':'#e2eaf0', '--text-secondary':'#8f98a0', '--text-input':'#ffffff', '--text-bright':'#ffffff', '--accent':'#66c0f4', '--on-accent':'#0e1621', '--accent-positive':'#5c7e10', '--border':'#2a475e', '--color-danger':'#a32a2a', '--text-danger':'#ff8080', '--color-warning':'#c97c00' }
    },
    {
        name: 'OLED Black',
        vars: { '--bg-page':'#000000', '--bg-surface':'#0d0d0d', '--bg-raised':'#141414', '--bg-input':'#050505', '--bg-card':'#111111', '--bg-nav':'#000000', '--text-primary':'#d0d8e0', '--text-heading':'#eef2f5', '--text-secondary':'#7a8590', '--text-input':'#ffffff', '--text-bright':'#ffffff', '--accent':'#58b4f0', '--on-accent':'#000000', '--accent-positive':'#4a7a08', '--border':'#222222', '--color-danger':'#8a1a1a', '--text-danger':'#ff6060', '--color-warning':'#a06000' }
    },
    {
        name: 'Slate',
        vars: { '--bg-page':'#0d1117', '--bg-surface':'#161b22', '--bg-raised':'#1c2128', '--bg-input':'#0d1117', '--bg-card':'#21262d', '--bg-nav':'#0d1117', '--text-primary':'#c9d1d9', '--text-heading':'#f0f6fc', '--text-secondary':'#8b949e', '--text-input':'#f0f6fc', '--text-bright':'#ffffff', '--accent':'#58a6ff', '--on-accent':'#0d1117', '--accent-positive':'#3fb950', '--border':'#30363d', '--color-danger':'#8b1a1a', '--text-danger':'#ff7b72', '--color-warning':'#d29922' }
    },
    {
        name: 'Warm',
        vars: { '--bg-page':'#120c08', '--bg-surface':'#1e1510', '--bg-raised':'#261a12', '--bg-input':'#120c08', '--bg-card':'#2a1e16', '--bg-nav':'#0e0a06', '--text-primary':'#e0cfc0', '--text-heading':'#f0e5d8', '--text-secondary':'#9a8070', '--text-input':'#f5ede0', '--text-bright':'#ffffff', '--accent':'#e8925a', '--on-accent':'#120c08', '--accent-positive':'#6a9a20', '--border':'#3e2a1a', '--color-danger':'#a03030', '--text-danger':'#ff8060', '--color-warning':'#c08020' }
    },
    {
        name: 'Midnight',
        vars: { '--bg-page':'#080810', '--bg-surface':'#0f0f1e', '--bg-raised':'#131322', '--bg-input':'#080812', '--bg-card':'#16162a', '--bg-nav':'#06060e', '--text-primary':'#c8cce8', '--text-heading':'#e8eaf8', '--text-secondary':'#8888aa', '--text-input':'#f0f0ff', '--text-bright':'#ffffff', '--accent':'#8888ff', '--on-accent':'#080810', '--accent-positive':'#44aa44', '--border':'#2a2a50', '--color-danger':'#882222', '--text-danger':'#ff8888', '--color-warning':'#cc8800' }
    },
];


// ── SAVED THEMES ──────────────────────────────────────────────────────────────
let _savedThemes = {};

async function _loadSavedThemes() {
    try {
        const res = await fetch('/api/theme/saved');
        const data = await res.json();
        _savedThemes = data.saved || {};
        _renderSettingsThemes();
    } catch (e) {}
}

function _renderSettingsThemes() {
    const content = document.getElementById('theme-picker-modal-content');
    if (!content) return;
    content.innerHTML = '';

    const btnStyle = 'display:block;width:100%;text-align:left;padding:10px 14px;background:none;border:none;border-radius:5px;color:var(--text-primary);font-size:0.9rem;cursor:pointer;';
    const labelStyle = 'font-size:0.72rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px;';

    let _rowIdx = 0;

    // Presets
    const presetsLabel = document.createElement('div');
    presetsLabel.style.cssText = labelStyle;
    presetsLabel.textContent = 'Presets';
    content.appendChild(presetsLabel);

    for (const preset of THEME_PRESETS) {
        const btn = document.createElement('button');
        btn.style.cssText = btnStyle;
        btn.dataset.modalRow = _rowIdx++;
        btn.textContent = preset.name;
        btn.onmouseover = () => btn.style.background = 'var(--bg-input)';
        btn.onmouseout  = () => btn.style.background = 'none';
        btn.onclick = () => { settingsApplyTheme(preset.vars); closeThemePickerModal(); };
        content.appendChild(btn);
    }

    // Saved themes
    const savedNames = Object.keys(_savedThemes);
    if (savedNames.length) {
        const sep = document.createElement('div');
        sep.style.cssText = 'border-top:1px solid var(--border);margin:14px 0 12px;';
        content.appendChild(sep);

        const savedLabel = document.createElement('div');
        savedLabel.style.cssText = labelStyle;
        savedLabel.textContent = 'Saved Themes';
        content.appendChild(savedLabel);

        for (const name of savedNames) {
            const row = document.createElement('div');
            row.style.cssText = 'display:flex;align-items:center;gap:4px;';

            const btn = document.createElement('button');
            btn.style.cssText = btnStyle + 'flex:1;';
            btn.dataset.modalRow = _rowIdx;
            btn.textContent = name;
            btn.onmouseover = () => btn.style.background = 'var(--bg-input)';
            btn.onmouseout  = () => btn.style.background = 'none';
            btn.onclick = () => { settingsApplyTheme(_savedThemes[name]); closeThemePickerModal(); };

            const del = document.createElement('button');
            del.style.cssText = 'background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:0.85rem;padding:4px 8px;flex-shrink:0;transition:color 0.15s;';
            del.dataset.modalRow = _rowIdx++;
            del.title = 'Delete';
            del.textContent = '✕';
            let _delTimer = null;
            del.onclick = () => {
                if (del.dataset.confirm === '1') {
                    clearTimeout(_delTimer);
                    themeDeleteNamed(name);
                } else {
                    del.dataset.confirm = '1';
                    del.textContent = 'Delete?';
                    del.style.color = 'var(--text-danger)';
                    _delTimer = setTimeout(() => {
                        del.dataset.confirm = '';
                        del.textContent = '✕';
                        del.style.color = 'var(--text-secondary)';
                    }, 3000);
                }
            };

            row.appendChild(btn);
            row.appendChild(del);
            content.appendChild(row);
        }
    }
}

function openThemePickerModal() {
    _loadSavedThemes().then(_renderSettingsThemes);
    document.getElementById('theme-picker-modal').style.display = 'flex';
}
function closeThemePickerModal() {
    document.getElementById('theme-picker-modal').style.display = 'none';
}

async function settingsApplyTheme(vars) {
    try {
        await fetch('/api/theme', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme: vars })
        });
    } catch (e) {}
    // Apply live regardless of network result
    for (const meta of THEME_VAR_META) {
        const val = vars[meta.key] || _themeDefs[meta.key];
        if (val) _applyVarToDocument(meta.key, val);
    }
    _themeApplied = Object.assign({}, vars);
    _themeVars    = {}; // force editor to reload from server next open
}

async function themeSaveNamed() {
    const input = document.getElementById('theme-save-name');
    const name = input.value.trim();
    if (!name) { _themeSetStatus('Enter a name first.', 'error'); return; }
    try {
        const res = await fetch('/api/theme/saved', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, theme: _themeVars })
        });
        const data = await res.json();
        if (data.status === 'success') {
            _savedThemes[name] = Object.assign({}, _themeVars);
            _renderSettingsThemes();
            input.value = '';
            _themeSetStatus(`✔ Saved as "${name}".`, 'success');
        } else {
            _themeSetStatus('✘ ' + (data.message || 'Save failed.'), 'error');
        }
    } catch (e) {
        _themeSetStatus('✘ Network error.', 'error');
    }
}

async function themeDeleteNamed(name) {
    try {
        await fetch(`/api/theme/saved/${encodeURIComponent(name)}`, { method: 'DELETE' });
        delete _savedThemes[name];
        _renderSettingsThemes();
    } catch (e) {}
}

let _apEditButtonCornerSelect = null;

document.addEventListener('DOMContentLoaded', () => {
    initCustomSelect(document.getElementById('source-table'));
    initCustomSelect(document.getElementById('appid-col'));
    initCustomSelect(document.getElementById('tools-filter-select'));
    initCustomSelect(document.getElementById('startup-page-select'));
    initCustomSelect(document.getElementById('pag-refresh-select'));
    _pagSlowScroll(document.getElementById('pag-wins-tags'));
    _pagSlowScroll(document.getElementById('pag-all-tags'));
    const editBtnCornerNative = document.getElementById('ap-editbtn-corner');
    if (editBtnCornerNative) _apEditButtonCornerSelect = initCustomSelect(editBtnCornerNative) || editBtnCornerNative;
});

// Tag pill boxes are short (a couple lines tall) but hold many tags — a
// full-speed wheel tick can jump past several lines at once. Scale the
// delta down so one scroll gesture moves roughly half a line instead.
function _pagSlowScroll(el, factor = 0.35) {
    if (!el) return;
    el.addEventListener('wheel', e => {
        e.preventDefault();
        el.scrollTop += e.deltaY * factor;
    }, { passive: false });
}

// ── ACCOUNT SETTINGS ─────────────────────────────────────────────────────────
let _cfgAccounts = window._cfgAccounts;
let _cfgActiveId = window._cfgActiveId;
let _cfgRemoveStep = 0, _cfgRemoveTimer = null;

function toggleCfgKeyVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    btn.style.opacity = show ? '1' : '0.5';
}

function _renderAccountList() {
    const container = document.getElementById('cfg-account-list');
    if (_cfgAccounts.length <= 1) { container.innerHTML = ''; return; }
    const frag = document.createDocumentFragment();
    const label = document.createElement('div');
    label.style.cssText = 'font-size:0.78rem; color:var(--text-secondary); margin-bottom:6px;';
    label.textContent = 'Switch account:';
    frag.appendChild(label);
    const row = document.createElement('div');
    row.style.cssText = 'display:flex; gap:6px; flex-wrap:wrap;';
    for (const acct of _cfgAccounts) {
        const btn = document.createElement('button');
        btn.className = 'nav-btn';
        btn.dataset.modalRow = '0';
        btn.textContent = acct.label || acct.steam_id;
        if (acct.active) btn.style.cssText = 'background:var(--accent); color:var(--on-accent);';
        btn.disabled = acct.active;
        btn.onclick = () => switchAccount(acct.steam_id);
        row.appendChild(btn);
    }
    frag.appendChild(row);
    container.innerHTML = '';
    container.appendChild(frag);
}

async function switchAccount(steamId) {
    try {
        const res = await fetch('/api/account/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ steam_id: steamId })
        });
        const data = await res.json();
        if (data.status === 'success') {
            window.location.reload();
        }
    } catch (e) {}
}

async function _runDetect(steamIdInputId, pickerDivId, statusEl, labelInputId) {
    const picker = document.getElementById(pickerDivId);
    picker.style.display = 'none';
    picker.innerHTML = '';
    statusEl.textContent = 'Detecting…';
    statusEl.className = 'tool-status info';
    try {
        const res = await fetch('/api/detect-steam-id');
        const data = await res.json();
        if (data.status === 'success') {
            document.getElementById(steamIdInputId).value = data.steam_id;
            if (labelInputId) {
                const lbl = document.getElementById(labelInputId);
                if (lbl && !lbl.value) lbl.value = data.name;
            }
            statusEl.textContent = `✔ Detected: ${data.name}`;
            statusEl.className = 'tool-status success';
        } else if (data.status === 'multiple') {
            statusEl.textContent = 'Multiple accounts found — choose one:';
            statusEl.className = 'tool-status info';
            picker.style.display = 'flex';
            for (const acct of data.accounts) {
                const btn = document.createElement('button');
                btn.className = 'nav-btn';
                btn.style.cssText = 'text-align:left; font-size:0.82rem;';
                btn.textContent = acct.name;
                btn.onclick = () => {
                    document.getElementById(steamIdInputId).value = acct.steam_id;
                    if (labelInputId) {
                        const lbl = document.getElementById(labelInputId);
                        if (lbl && !lbl.value) lbl.value = acct.name;
                    }
                    statusEl.textContent = `✔ Selected: ${acct.name}`;
                    statusEl.className = 'tool-status success';
                    picker.style.display = 'none';
                    picker.innerHTML = '';
                };
                picker.appendChild(btn);
            }
        } else {
            statusEl.textContent = '✘ Could not detect Steam ID automatically.';
            statusEl.className = 'tool-status error';
        }
    } catch (e) {
        statusEl.textContent = '✘ Detection failed.';
        statusEl.className = 'tool-status error';
    }
    setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'tool-status'; }, 4000);
}

function detectSteamId() {
    _runDetect('cfg-steam-id', 'cfg-account-picker', document.getElementById('cfg-status'), 'cfg-label');
}
function detectSteamIdNew() {
    _runDetect('cfg-new-steam-id', 'cfg-new-account-picker', document.getElementById('cfg-add-status'), 'cfg-new-label');
}

async function saveAccountSettings() {
    const status = document.getElementById('cfg-status');
    const steamId = document.getElementById('cfg-steam-id').value.trim();
    const apiKey  = document.getElementById('cfg-api-key').value.trim();
    const label   = document.getElementById('cfg-label').value.trim();

    if (!steamId) {
        status.textContent = '✘ Steam ID is required.';
        status.className = 'tool-status error';
        return;
    }

    status.textContent = 'Saving…';
    status.className = 'tool-status info';
    try {
        const res = await fetch('/save-config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ steam_id: steamId, api_key: apiKey, label })
        });
        const data = await res.json();
        if (data.status === 'success') {
            status.textContent = '✔ Saved.';
            status.className = 'tool-status success';
            // Update local cache label
            const acct = _cfgAccounts.find(a => a.active);
            if (acct) { acct.label = label || acct.steam_id; acct.steam_id = steamId; _renderAccountList(); }
        } else {
            status.textContent = '✘ ' + (data.message || 'Save failed.');
            status.className = 'tool-status error';
        }
    } catch (e) {
        status.textContent = '✘ Network error.';
        status.className = 'tool-status error';
    }
    setTimeout(() => { status.textContent = ''; status.className = 'tool-status'; }, 5000);
}

async function saveSgdbKey() {
    const status = document.getElementById('cfg-sgdb-status');
    const sgdbKey = document.getElementById('cfg-sgdb-key').value.trim();
    status.textContent = 'Saving…';
    status.className = 'tool-status info';
    try {
        const res = await fetch('/save-config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sgdb_key: sgdbKey })
        });
        const data = await res.json();
        if (data.status === 'success') {
            status.textContent = '✔ Saved.';
            status.className = 'tool-status success';
        } else {
            status.textContent = '✘ ' + (data.message || 'Save failed.');
            status.className = 'tool-status error';
        }
    } catch (e) {
        status.textContent = '✘ Network error.';
        status.className = 'tool-status error';
    }
    setTimeout(() => { status.textContent = ''; status.className = 'tool-status'; }, 5000);
}

async function saveSgUsername() {
    const status = document.getElementById('cfg-sg-status');
    const username = document.getElementById('cfg-sg-username').value.trim();
    status.textContent = 'Saving…';
    status.className = 'tool-status info';
    try {
        const res = await fetch('/api/save-sg-username', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sg_username: username })
        });
        const data = await res.json();
        if (data.status === 'success') {
            status.textContent = '✔ Saved.';
            status.className = 'tool-status success';
        } else {
            status.textContent = '✘ ' + (data.message || 'Save failed.');
            status.className = 'tool-status error';
        }
    } catch (e) {
        status.textContent = '✘ Network error.';
        status.className = 'tool-status error';
    }
    setTimeout(() => { status.textContent = ''; status.className = 'tool-status'; }, 5000);
}

function removeAccount() {
    const btn = document.getElementById('cfg-remove-btn');
    if (_cfgAccounts.length <= 1) {
        const status = document.getElementById('cfg-status');
        status.textContent = '✘ Cannot remove the only account.';
        status.className = 'tool-status error';
        setTimeout(() => { status.textContent = ''; status.className = 'tool-status'; }, 3000);
        return;
    }
    if (_cfgRemoveStep === 0) {
        _cfgRemoveStep = 1;
        btn.textContent = 'Remove?';
        btn.style.color = 'var(--text-danger)';
        _cfgRemoveTimer = setTimeout(() => {
            _cfgRemoveStep = 0;
            btn.textContent = 'Remove Account';
            btn.style.color = 'var(--text-secondary)';
        }, 3000);
    } else {
        clearTimeout(_cfgRemoveTimer);
        _cfgRemoveStep = 0;
        btn.textContent = 'Remove Account';
        btn.style.color = 'var(--text-secondary)';
        _doRemoveAccount();
    }
}

async function _doRemoveAccount() {
    const status = document.getElementById('cfg-status');
    status.textContent = 'Removing…';
    status.className = 'tool-status info';
    try {
        const res = await fetch('/api/account/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ steam_id: _cfgActiveId })
        });
        const data = await res.json();
        if (data.status === 'success') {
            window.location.reload();
        } else {
            status.textContent = '✘ ' + (data.message || 'Remove failed.');
            status.className = 'tool-status error';
        }
    } catch (e) {
        status.textContent = '✘ Network error.';
        status.className = 'tool-status error';
    }
}

function showAddAccountForm() {
    document.getElementById('cfg-add-form').style.display = 'block';
    document.getElementById('cfg-new-steam-id').value = '';
    document.getElementById('cfg-new-label').value = '';
    document.getElementById('cfg-add-status').textContent = '';
}
function hideAddAccountForm() {
    document.getElementById('cfg-add-form').style.display = 'none';
}

async function addAccount() {
    const status = document.getElementById('cfg-add-status');
    const steamId = document.getElementById('cfg-new-steam-id').value.trim();
    const label   = document.getElementById('cfg-new-label').value.trim();
    if (!steamId) {
        status.textContent = '✘ Steam ID is required.';
        status.className = 'tool-status error';
        return;
    }
    status.textContent = 'Adding…';
    status.className = 'tool-status info';
    try {
        const res = await fetch('/save-config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ steam_id: steamId, label, _set_active: true })
        });
        const data = await res.json();
        if (data.status === 'success') {
            window.location.reload();
        } else {
            status.textContent = '✘ ' + (data.message || 'Failed.');
            status.className = 'tool-status error';
        }
    } catch (e) {
        status.textContent = '✘ Network error.';
        status.className = 'tool-status error';
    }
}

// Init account list on load
document.addEventListener('DOMContentLoaded', () => {
    _renderAccountList();
    // Populate label field with active account's label
    const active = _cfgAccounts.find(a => a.active);
    if (active) document.getElementById('cfg-label').value = active.label || '';
});

// ── SECTION MODALS ────────────────────────────────────────────────────────────
function openAccountModal() {
    document.getElementById('account-modal').style.display = 'flex';
}
function closeAccountModal() {
    document.getElementById('account-modal').style.display = 'none';
}
function openAppearanceModal() {
    document.getElementById('appearance-modal').style.display = 'flex';
    _apLoadOutlines().then(() => _apSyncOutlineButtons(_apOutlineEnabled));
    _apLoadBadges().then(() => _apSyncBadgesButtons(_apBadgesEnabled));
    _apLoadEditButton().then(() => _apSyncEditButtonButtons(_apEditButtonEnabled, _apEditButtonCorner));
}
function closeAppearanceModal() {
    document.getElementById('appearance-modal').style.display = 'none';
}

function _onUiScaleSlider(el) {
    document.getElementById('ui-scale-val').textContent = el.value + '%';
    document.getElementById('ui-scale-style').textContent = 'html { zoom: ' + el.value + '%; }';
    const pct = (el.value - el.min) / (el.max - el.min) * 100;
    el.style.setProperty('--slider-pct', pct + '%');
}

(function _initUiScaleSlider() {
    const el = document.getElementById('ui-scale-slider');
    if (!el) return;
    const pct = (el.value - el.min) / (el.max - el.min) * 100;
    el.style.setProperty('--slider-pct', pct + '%');
})();
function saveUiScale() {
    const val = parseInt(document.getElementById('ui-scale-slider').value, 10);
    const status = document.getElementById('ui-scale-status');
    savePreference({ ui_scale: val });
    status.textContent = 'Saved.';
    setTimeout(() => { status.textContent = ''; }, 2000);
}
function resetUiScale() {
    const slider = document.getElementById('ui-scale-slider');
    slider.value = 100;
    _onUiScaleSlider(slider);
    savePreference({ ui_scale: 100 });
    const status = document.getElementById('ui-scale-status');
    status.textContent = 'Reset to 100%.';
    setTimeout(() => { status.textContent = ''; }, 2000);
}

let _apOutlineEnabled = null;

async function _apLoadOutlines() {
    if (_apOutlineEnabled !== null) return;
    try {
        const r = await fetch('/api/card-outlines').then(r => r.json());
        if (r.status === 'success') {
            _apOutlineEnabled = r.card_outlines.enabled || {library: true, home: true, pick6: true};
        }
    } catch (e) { /* ignore */ }
    if (!_apOutlineEnabled) _apOutlineEnabled = {library: true, home: true, pick6: true};
}

function _apSyncOutlineButtons(enabled) {
    ['library', 'home', 'pick6'].forEach(k => {
        const btn = document.getElementById('ap-outline-' + k);
        if (btn) btn.classList.toggle('ap-outline-on', !!enabled[k]);
    });
}

async function apToggleOutline(key) {
    if (!_apOutlineEnabled) _apOutlineEnabled = {library: true, home: true, pick6: true};
    _apOutlineEnabled[key] = !_apOutlineEnabled[key];
    _apSyncOutlineButtons(_apOutlineEnabled);
    try {
        const current = await fetch('/api/card-outlines').then(r => r.json());
        const outlines = current.card_outlines || {};
        outlines.enabled = _apOutlineEnabled;
        await fetch('/api/card-outlines', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({card_outlines: outlines}),
        });
    } catch (e) { /* ignore */ }
}

let _apBadgesEnabled = null;

async function _apLoadBadges() {
    if (_apBadgesEnabled !== null) return;
    try {
        const r = await fetch('/api/card-badges').then(r => r.json());
        if (r.status === 'success') {
            _apBadgesEnabled = r.card_badges.enabled || {library: true, home: true, pick6: true};
        }
    } catch (e) { /* ignore */ }
    if (!_apBadgesEnabled) _apBadgesEnabled = {library: true, home: true, pick6: true};
}

function _apSyncBadgesButtons(enabled) {
    ['library', 'home', 'pick6'].forEach(k => {
        const btn = document.getElementById('ap-badges-' + k);
        if (btn) btn.classList.toggle('ap-outline-on', !!enabled[k]);
    });
}

async function apToggleBadges(key) {
    if (!_apBadgesEnabled) _apBadgesEnabled = {library: true, home: true, pick6: true};
    _apBadgesEnabled[key] = !_apBadgesEnabled[key];
    _apSyncBadgesButtons(_apBadgesEnabled);
    try {
        const current = await fetch('/api/card-badges').then(r => r.json());
        const badges = current.card_badges || {};
        badges.enabled = _apBadgesEnabled;
        await fetch('/api/card-badges', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({card_badges: badges}),
        });
    } catch (e) { /* ignore */ }
}

let _apEditButtonEnabled = null;
let _apEditButtonCorner = null;

async function _apLoadEditButton() {
    if (_apEditButtonEnabled !== null) return;
    try {
        const r = await fetch('/api/edit-button').then(r => r.json());
        if (r.status === 'success') {
            _apEditButtonEnabled = r.edit_button.pages || {library: true, home: false, pick6: false};
            _apEditButtonCorner  = r.edit_button.corner || 'top_right';
        }
    } catch (e) { /* ignore */ }
    if (!_apEditButtonEnabled) _apEditButtonEnabled = {library: true, home: false, pick6: false};
    if (!_apEditButtonCorner) _apEditButtonCorner = 'top_right';
}

function _apSyncEditButtonButtons(enabled, corner) {
    ['library', 'home', 'pick6'].forEach(k => {
        const btn = document.getElementById('ap-editbtn-' + k);
        if (btn) btn.classList.toggle('ap-outline-on', !!enabled[k]);
    });
    const sel = _apEditButtonCornerSelect || document.getElementById('ap-editbtn-corner');
    if (sel) sel.value = corner;
}

async function apToggleEditButton(key) {
    if (!_apEditButtonEnabled) _apEditButtonEnabled = {library: true, home: false, pick6: false};
    _apEditButtonEnabled[key] = !_apEditButtonEnabled[key];
    _apSyncEditButtonButtons(_apEditButtonEnabled, _apEditButtonCorner || 'top_right');
    await _apSaveEditButton();
}

async function apSetEditButtonCorner(corner) {
    _apEditButtonCorner = corner;
    await _apSaveEditButton();
}

async function _apSaveEditButton() {
    try {
        await fetch('/api/edit-button', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({edit_button: {
                pages: _apEditButtonEnabled || {library: true, home: false, pick6: false},
                corner: _apEditButtonCorner || 'top_right',
            }}),
        });
    } catch (e) { /* ignore */ }
}

const _PLAT_PRIORITY_LABELS = window._PLAT_LABELS;
let _platPriority = window._platPriority;
let _platPriorityDragSrc = null, _platPriorityHover = null;

function openLibraryModal() {
    document.getElementById('library-modal').style.display = 'flex';
    _renderPlatformPriorityList();
}
function closeLibraryModal() {
    document.getElementById('library-modal').style.display = 'none';
}

// ── Plugin manage modal system ────────────────────────────────────────────────
const _manageSpecs = {}; // {plugin_id: {name, spec}}

const _manageOnOpen = {};  // id -> [callbacks] run each time the manage modal opens

function _openManageModal(id) {
    const entry = _manageSpecs[id];
    if (!entry) return;
    let modal = document.getElementById(`${id}-manage-modal`);
    if (!modal) {
        const frag = _buildManageModalHtml(id, entry.name, entry.spec);
        document.body.insertAdjacentHTML('beforeend', frag);
        modal = document.getElementById(`${id}-manage-modal`);
    }
    modal.style.display = 'flex';
    window._inputMgr?.registerModal?.(`${id}-manage-modal`);
    _manageRefreshAuth(id);
    _manageLoadLauncherConfig(id);
    for (const cb of (_manageOnOpen[id] || [])) cb();
}

function _closeManageModal(id) {
    const modal = document.getElementById(`${id}-manage-modal`);
    if (modal) modal.style.display = 'none';
}

async function _manageRefreshAuth(id) {
    const entry = _manageSpecs[id];
    if (!entry) return;
    for (const section of (entry.spec.sections || [])) {
        if (!section.auth) continue;
        try {
            const r = await fetch(section.auth.endpoint);
            const d = await r.json();
            const disconnEl = document.getElementById(`${id}-manage-disconnected`);
            const connEl    = document.getElementById(`${id}-manage-connected`);
            const userEl    = document.getElementById(`${id}-manage-username`);
            if (disconnEl) disconnEl.style.display = d.connected ? 'none' : '';
            if (connEl)    connEl.style.display    = d.connected ? ''     : 'none';
            if (userEl)    userEl.textContent       = d.username || '';
            if (d.connected) _manageLoadInfoBlocks(id, section.auth.connected || []);
        } catch (_) {}
    }
}

async function _manageLoadInfoBlocks(id, items) {
    let idx = 0;
    for (const block of items) {
        if (block.type === 'info_endpoint') {
            try {
                const r = await fetch(block.endpoint);
                const d = await r.json();
                const el = document.getElementById(`${id}-manage-info-${idx}`);
                if (el) {
                    el.textContent = d.text || '';
                    el.style.color = d.color || 'var(--text-secondary)';
                }
            } catch (_) {}
            idx++;
        }
    }
}

async function _managePost(id, endpoint, onSuccess) {
    try {
        await fetch(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}});
        if (onSuccess === 'refresh_auth') _manageRefreshAuth(id);
    } catch (_) {}
}

async function _manageLoadLauncherConfig(id) {
    const wineBinEl   = document.getElementById(`${id}-manage-launcher-wine-bin`);
    const prefixEl    = document.getElementById(`${id}-manage-launcher-prefix`);
    const installWrap = document.getElementById(`${id}-manage-launcher-install-wrap`);
    if (!wineBinEl || !prefixEl) return;
    try {
        const r = await fetch(`/api/launcher-config/${encodeURIComponent(id)}`);
        const d = await r.json();
        const cfg = d.config || {};
        wineBinEl.value = cfg.wine_bin || d.wine_bin_detected || '';
        prefixEl.value  = cfg.prefix   || d.default_prefix || `~/.wine-${id}`;
        if (installWrap) installWrap.style.display = d.installer_available ? '' : 'none';
        if (d.installer_available) _manageLauncherInstallResume(id);
    } catch(_) {}
}

async function _manageSaveLauncher(id) {
    const wine_bin = document.getElementById(`${id}-manage-launcher-wine-bin`)?.value.trim();
    const prefix   = document.getElementById(`${id}-manage-launcher-prefix`)?.value.trim();
    const msgEl    = document.getElementById(`${id}-manage-launcher-msg`);
    try {
        const r = await fetch(`/api/launcher-config/${encodeURIComponent(id)}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({wine_bin, prefix, mode: 'wine'}),
        });
        const d = await r.json();
        if (msgEl) {
            msgEl.style.display = '';
            msgEl.style.color   = d.status === 'success' ? '#6dc46d' : '#c74747';
            msgEl.textContent   = d.status === 'success' ? 'Saved.' : (d.message || 'Save failed.');
            setTimeout(() => { msgEl.style.display = 'none'; }, 2000);
        }
    } catch(e) {
        if (msgEl) { msgEl.style.display = ''; msgEl.style.color = '#c74747'; msgEl.textContent = 'Save failed.'; }
    }
}

async function _manageLauncherReinstall(id) {
    confirm('Delete the Wine prefix and reinstall the launcher?').then(async ok => {
        if (!ok) return;
        const stEl = document.getElementById(`${id}-manage-launcher-install-status`);
        if (stEl) { stEl.style.color = 'var(--text-secondary)'; stEl.textContent = 'Removing existing prefix...'; }
        try {
            const r = await fetch(`/api/launcher-uninstall/${encodeURIComponent(id)}`, {method: 'POST'});
            const d = await r.json();
            if (d.status !== 'success') {
                if (stEl) { stEl.style.color = 'var(--text-danger)'; stEl.textContent = d.message || 'Uninstall failed.'; }
                return;
            }
        } catch(e) {
            if (stEl) { stEl.style.color = 'var(--text-danger)'; stEl.textContent = `Error: ${e.message}`; }
            return;
        }
        _manageLauncherInstall(id);
    });
}

async function _manageLauncherRemove(id) {
    confirm('Delete the Wine prefix and remove the launcher configuration?').then(async ok => {
        if (!ok) return;
        const msgEl = document.getElementById(`${id}-manage-launcher-msg`);
        if (msgEl) { msgEl.style.display = ''; msgEl.style.color = 'var(--text-secondary)'; msgEl.textContent = 'Removing...'; }
        try {
            const r = await fetch(`/api/launcher-uninstall/${encodeURIComponent(id)}`, {method: 'POST'});
            const d = await r.json();
            if (msgEl) {
                msgEl.style.display = '';
                msgEl.style.color   = d.status === 'success' ? '#6dc46d' : '#c74747';
                msgEl.textContent   = d.status === 'success' ? 'Launcher removed.' : (d.message || 'Remove failed.');
            }
            if (d.status === 'success') {
                const wineBinEl = document.getElementById(`${id}-manage-launcher-wine-bin`);
                const prefixEl  = document.getElementById(`${id}-manage-launcher-prefix`);
                if (wineBinEl) wineBinEl.value = '';
                if (prefixEl)  prefixEl.value  = '';
                fetch(`/api/plugins/launcher-status/${encodeURIComponent(id)}`, {method: 'POST'}).catch(() => {});
            }
        } catch(e) {
            if (msgEl) { msgEl.style.display = ''; msgEl.style.color = '#c74747'; msgEl.textContent = `Error: ${e.message}`; }
        }
    });
}

async function _manageRecheckLauncher(id) {
    const msgEl = document.getElementById(`${id}-manage-launcher-msg`);
    if (msgEl) { msgEl.style.display = ''; msgEl.style.color = 'var(--text-secondary)'; msgEl.textContent = 'Checking...'; }
    try {
        const r = await fetch(`/api/plugins/launcher-status/${encodeURIComponent(id)}`, {method: 'POST'});
        const d = await r.json();
        if (msgEl && d.status === 'success') {
            const ls = d.launcher_status;
            msgEl.style.display = '';
            msgEl.style.color   = ls.available ? '#6dc46d' : '#ffa500';
            msgEl.textContent   = ls.available ? 'Launcher ready.' : (ls.detail || 'Launcher unavailable.');
        }
    } catch(e) {
        if (msgEl) { msgEl.style.display = ''; msgEl.style.color = '#c74747'; msgEl.textContent = 'Check failed.'; }
    }
}

const _launcherInstallPolls = {};

async function _manageLauncherInstall(id) {
    const stEl = document.getElementById(`${id}-manage-launcher-install-status`);
    if (stEl) { stEl.style.color = 'var(--text-secondary)'; stEl.textContent = 'Starting...'; }
    const wine_bin = document.getElementById(`${id}-manage-launcher-wine-bin`)?.value.trim() || '';
    const prefix   = document.getElementById(`${id}-manage-launcher-prefix`)?.value.trim() || '';
    try {
        const r = await fetch(`/api/launcher-install/${encodeURIComponent(id)}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({wine_bin, prefix}),
        });
        const d = await r.json();
        if (d.status === 'error') {
            if (stEl) { stEl.style.color = 'var(--text-danger)'; stEl.textContent = d.message || 'Failed to start.'; }
            return;
        }
    } catch (e) {
        if (stEl) { stEl.style.color = 'var(--text-danger)'; stEl.textContent = `Error: ${e.message}`; }
        return;
    }
    _manageLauncherInstallPoll(id);
}

function _manageLauncherInstallResume(id) {
    fetch(`/api/launcher-install/${encodeURIComponent(id)}/status`)
        .then(r => r.json())
        .then(d => {
            if (d.phase && !d.done && !d.error) _manageLauncherInstallPoll(id);
        })
        .catch(() => {});
}

function _manageLauncherInstallPoll(id) {
    if (_launcherInstallPolls[id]) return;
    const stEl = document.getElementById(`${id}-manage-launcher-install-status`);
    _launcherInstallPolls[id] = setInterval(async () => {
        try {
            const r = await fetch(`/api/launcher-install/${encodeURIComponent(id)}/status`);
            const d = await r.json();
            if (stEl) {
                if (d.error) {
                    stEl.style.color = 'var(--text-danger)';
                    stEl.textContent = d.error;
                } else {
                    stEl.style.color = d.done ? 'var(--accent-positive, #5c7e10)' : 'var(--text-secondary)';
                    stEl.textContent = d.detail || d.phase || '';
                }
            }
            if (d.done || d.error) {
                clearInterval(_launcherInstallPolls[id]);
                delete _launcherInstallPolls[id];
                if (d.done) setTimeout(() => location.reload(), 1500);
            }
        } catch (_) {}
    }, 1500);
}

function _manageOpenUrl(url) {
    const a = document.createElement('a');
    a.href = url; a.target = '_blank';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
}

function _manageOpenOauth(id) {
    const modal = document.getElementById(`${id}-manage-oauth-modal`);
    if (!modal) return;
    document.getElementById(`${id}-manage-oauth-input`).value = '';
    document.getElementById(`${id}-manage-oauth-status`).textContent = '';
    modal.style.display = 'flex';
    window._inputMgr?.registerModal?.(`${id}-manage-oauth-modal`);
}

function _closeManageOauth(id) {
    const modal = document.getElementById(`${id}-manage-oauth-modal`);
    if (modal) modal.style.display = 'none';
}

// Called by pywebview after open_auth_popup() completes (success or failure).
window._authPopupDone = function(result) {
    const id = window._authPopupPendingId;
    if (!id) return;
    window._authPopupPendingId = null;
    const st = document.getElementById(`${id}-manage-popup-status`);
    if (result.status === 'success') {
        if (st) { st.style.color = 'var(--accent-positive, #5c7e10)'; st.textContent = `Connected as ${result.username || 'unknown'}`; }
        setTimeout(() => _manageRefreshAuth(id), 1000);
    } else {
        if (st) { st.style.color = 'var(--text-danger)'; st.textContent = result.message || 'Connection failed'; }
    }
};

async function _manageOpenAuthPopup(id) {
    const entry = _manageSpecs[id];
    if (!entry) return;
    let action = null;
    for (const section of (entry.spec.sections || [])) {
        for (const block of (section.auth ? section.auth.disconnected : section.items || [])) {
            if (block.type === 'button' && block.action && block.action.type === 'oauth_popup') {
                action = block.action;
            }
        }
    }
    if (!action) return;

    // Fallback: no pywebview — open paste modal instead
    if (!window.pywebview) {
        _manageOpenOauth(id);
        return;
    }

    const st = document.getElementById(`${id}-manage-popup-status`);
    if (st) { st.style.color = 'var(--text-secondary)'; st.textContent = 'Opening login window...'; }

    let loginUrl;
    try {
        const r = await fetch(action.url_endpoint);
        const d = await r.json();
        loginUrl = d.url;
        if (!loginUrl) {
            if (st) { st.style.color = 'var(--text-danger)'; st.textContent = d.error || 'Login URL not available — check credentials first'; }
            return;
        }
    } catch (e) {
        if (st) { st.style.color = 'var(--text-danger)'; st.textContent = 'Failed to get login URL'; }
        return;
    }

    window._authPopupPendingId = id;
    if (st) { st.style.color = 'var(--text-secondary)'; st.textContent = 'Waiting for login...'; }

    try {
        window.pywebview.api.open_auth_popup(
            loginUrl,
            action.redirect_pattern,
            action.code_js,
            action.callback_endpoint,
            action.cookie_name || null,
            action.intercept_js || null,
        );
    } catch (e) {
        window._authPopupPendingId = null;
        if (st) { st.style.color = 'var(--text-danger)'; st.textContent = `Error: ${e.message}`; }
    }
}

async function _manageOauthOpenUrl(id) {
    const entry = _manageSpecs[id];
    if (!entry) return;
    let urlEndpoint = null;
    for (const section of (entry.spec.sections || [])) {
        for (const block of (section.auth ? section.auth.disconnected : section.items || [])) {
            if (block.type === 'button' && block.action &&
                    (block.action.type === 'oauth_paste' || block.action.type === 'oauth_popup')) {
                urlEndpoint = block.action.url_endpoint;
            }
        }
    }
    if (!urlEndpoint) return;
    try {
        const r = await fetch(urlEndpoint);
        const d = await r.json();
        _manageOpenUrl(d.url);
    } catch (e) {
        const st = document.getElementById(`${id}-manage-oauth-status`);
        if (st) st.textContent = 'Failed to get auth URL';
    }
}

async function _manageOauthSubmit(id) {
    const entry = _manageSpecs[id];
    if (!entry) return;
    let callbackEndpoint = null;
    for (const section of (entry.spec.sections || [])) {
        for (const block of (section.auth ? section.auth.disconnected : section.items || [])) {
            if (block.type === 'button' && block.action &&
                    (block.action.type === 'oauth_paste' || block.action.type === 'oauth_popup')) {
                callbackEndpoint = block.action.callback_endpoint;
            }
        }
    }
    if (!callbackEndpoint) return;
    const input = document.getElementById(`${id}-manage-oauth-input`);
    const st    = document.getElementById(`${id}-manage-oauth-status`);
    const code  = input ? input.value.trim() : '';
    if (!code) return;
    if (st) { st.style.color = 'var(--text-secondary)'; st.textContent = 'Connecting...'; }
    try {
        const r = await fetch(callbackEndpoint, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({code}),
        });
        const d = await r.json();
        if (d.status === 'success') {
            if (st) { st.style.color = 'var(--accent-positive, #5c7e10)'; st.textContent = `Connected as ${d.username || 'unknown'}`; }
            setTimeout(() => { _closeManageOauth(id); _manageRefreshAuth(id); }, 1200);
        } else {
            if (st) { st.style.color = 'var(--text-danger)'; st.textContent = d.message || 'Connection failed'; }
        }
    } catch (e) {
        if (st) { st.style.color = 'var(--text-danger)'; st.textContent = 'Network error'; }
    }
}

function _buildManageBlockHtml(id, block, infoIdx, rowCtr) {
    const eid = escHtml(id);
    switch (block.type) {
        case 'text':
            return `<div style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:8px;">${block.content}</div>`;
        case 'connected_label':
            return `<div style="font-size:0.85rem;color:var(--text-primary);margin-bottom:8px;">Connected as <span id="${eid}-manage-username" style="color:var(--accent);"></span></div>`;
        case 'info_endpoint':
            return `<div id="${eid}-manage-info-${infoIdx}" style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:8px;"></div>`;
        case 'button': {
            const a = block.action || {};
            let onclick = '';
            if (a.type === 'call')        onclick = `${escHtml(a.fn)}()`;
            else if (a.type === 'open_url')    onclick = `_manageOpenUrl(${JSON.stringify(a.url)})`;
            else if (a.type === 'oauth_paste') onclick = `_manageOpenOauth('${eid}')`;
            else if (a.type === 'oauth_popup') onclick = `_manageOpenAuthPopup('${eid}')`;
            else if (a.type === 'post')        onclick = `_managePost('${eid}',${JSON.stringify(a.endpoint)},${JSON.stringify(a.on_success || '')})`;
            const row = rowCtr.r++;
            const colorStyle = block.variant === 'muted' ? 'color:var(--text-secondary);' : '';
            const popupStatus = a.type === 'oauth_popup'
                ? `<div id="${eid}-manage-popup-status" class="tool-status" style="margin-top:6px;"></div>`
                : '';
            return `<button class="nav-btn" data-modal-row="${row}" style="display:block;width:100%;margin-bottom:6px;${colorStyle}" onclick="${escHtml(onclick)}">${escHtml(block.label)}</button>${popupStatus}`;
        }
        case 'buttons': {
            const row = rowCtr.r++;
            const btns = (block.items || []).map(btn => {
                const a = btn.action || {};
                let onclick = '';
                if (a.type === 'call')        onclick = `${escHtml(a.fn)}()`;
                else if (a.type === 'open_url')    onclick = `_manageOpenUrl(${JSON.stringify(a.url)})`;
                else if (a.type === 'post')         onclick = `_managePost('${eid}',${JSON.stringify(a.endpoint)},${JSON.stringify(a.on_success || '')})`;
                const muted = btn.variant === 'muted' ? ' style="color:var(--text-secondary);"' : '';
                return `<button class="nav-btn" data-modal-row="${row}"${muted} onclick="${escHtml(onclick)}">${escHtml(btn.label)}</button>`;
            }).join('');
            return `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px;">${btns}</div>`;
        }
        case 'status_output':
            return `<div id="${eid}-manage-status-${escHtml(block.key)}" class="tool-status"></div>`;
        case 'input':
        case 'password': {
            const row = rowCtr.r++;
            const inputStyle = 'width:100%;box-sizing:border-box;margin-top:3px;padding:5px 8px;font-size:0.8rem;background:var(--bg-input);border:1px solid var(--border);border-radius:3px;color:var(--text-primary);';
            const itype = block.type === 'password' ? 'password' : 'text';
            const ph = escHtml(block.placeholder || '');
            const lbl = escHtml(block.label || '');
            return `<label style="display:block;color:var(--text-secondary);font-size:0.8rem;margin-bottom:8px;">${lbl}<input type="${itype}" id="${eid}-manage-input-${escHtml(block.key)}" data-modal-row="${row}" style="${inputStyle}" placeholder="${ph}" autocomplete="${itype === 'password' ? 'current-password' : 'username'}"></label>`;
        }
        case 'launcher_config': {
            const inputStyle = 'width:100%;box-sizing:border-box;margin-top:3px;padding:5px 8px;font-size:0.8rem;background:var(--bg-input);border:1px solid var(--border);border-radius:3px;color:var(--text-primary);';
            const rWine = rowCtr.r++;
            const rPrefix = rowCtr.r++;
            const rSave = rowCtr.r++;
            const rInstall = rowCtr.r++;
            return `<div style="display:flex;flex-direction:column;gap:8px;">
            <label style="display:block;color:var(--text-primary);font-size:0.82rem;">Wine binary
                <input type="text" id="${eid}-manage-launcher-wine-bin" data-modal-row="${rWine}" style="${inputStyle}" placeholder="e.g. /usr/bin/wine64">
            </label>
            <label style="display:block;color:var(--text-primary);font-size:0.82rem;">Wine prefix path
                <input type="text" id="${eid}-manage-launcher-prefix" data-modal-row="${rPrefix}" style="${inputStyle}" placeholder="e.g. ~/.wine-${eid}">
            </label>
            <div id="${eid}-manage-launcher-msg" style="display:none;font-size:0.78rem;"></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <button class="nav-btn" style="font-size:0.75rem;" data-modal-row="${rSave}" onclick="_manageSaveLauncher('${eid}')">Save</button>
                <button class="nav-btn" style="font-size:0.75rem;" data-modal-row="${rSave}" onclick="_manageRecheckLauncher('${eid}')">Re-check status</button>
            </div>
            <div id="${eid}-manage-launcher-install-wrap" style="display:none;">
                <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px;">
                    <button class="nav-btn" style="font-size:0.75rem;" data-modal-row="${rInstall}" onclick="_manageLauncherInstall('${eid}')">Install launcher</button>
                    <button class="nav-btn" style="font-size:0.75rem;" data-modal-row="${rInstall}" onclick="_manageLauncherReinstall('${eid}')">Reinstall launcher</button>
                    <button class="nav-btn" style="font-size:0.75rem;color:var(--text-danger,#c74747);" data-modal-row="${rInstall}" onclick="_manageLauncherRemove('${eid}')">Remove launcher</button>
                </div>
                <div id="${eid}-manage-launcher-install-status" class="tool-status"></div>
            </div>
        </div>`;
        }
    }
    return '';
}

function _buildManageSectionItems(id, items, rowCtr) {
    let html = '';
    let infoIdx = 0;
    for (const block of (items || [])) {
        html += _buildManageBlockHtml(id, block, infoIdx, rowCtr);
        if (block.type === 'info_endpoint') infoIdx++;
    }
    return html;
}

function _buildManageOauthHtml(id, action) {
    const eid  = escHtml(id);
    const instructions = (action.instructions || []).map((s, i) => `<li>${s}</li>`).join('');
    const closeStyle = 'background:none;border:none;color:var(--text-secondary);font-size:1.3rem;cursor:pointer;padding:0 4px;line-height:1;';
    return `
<div id="${eid}-manage-oauth-modal" class="modal-overlay sub-modal" style="display:none;" onclick="if(event.target===this)_closeManageOauth('${eid}')">
  <div class="modal-content" style="width:420px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <h2 style="margin:0;color:var(--text-primary);">${escHtml(action.title || 'Connect')}</h2>
      <button onclick="_closeManageOauth('${eid}')" style="${closeStyle}">&#x2715;</button>
    </div>
    <ol style="font-size:0.85rem;color:var(--text-secondary);padding-left:1.2em;margin:0 0 14px;line-height:1.7;">${instructions}</ol>
    <button class="nav-btn" data-modal-row="0" style="margin-bottom:14px;" onclick="_manageOauthOpenUrl('${eid}')">${escHtml(action.open_label || 'Open Login')}</button>
    <div style="margin-bottom:8px;">
      <label style="font-size:0.78rem;color:var(--text-secondary);display:block;margin-bottom:3px;">Paste the URL from the address bar</label>
      <input id="${eid}-manage-oauth-input" type="text" data-modal-row="1" placeholder="${escHtml(action.input_placeholder || '')}"
        style="width:100%;box-sizing:border-box;padding:7px 10px;background:var(--bg-input);border:1px solid var(--border);border-radius:5px;color:var(--text-primary);font-size:0.85rem;outline:none;"
        onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'"
        onkeydown="if(event.key==='Enter')_manageOauthSubmit('${eid}')">
    </div>
    <div style="display:flex;align-items:center;gap:10px;">
      <button class="nav-btn" data-modal-row="2" onclick="_manageOauthSubmit('${eid}')">${escHtml(action.submit_label || 'Connect')}</button>
      <div id="${eid}-manage-oauth-status" class="tool-status" style="margin:0;"></div>
    </div>
  </div>
</div>`;
}

function _buildManageModalHtml(id, name, spec) {
    const eid = escHtml(id);
    const closeStyle = 'background:none;border:none;color:var(--text-secondary);font-size:1.3rem;cursor:pointer;padding:0 4px;line-height:1;';
    let sectionsHtml = '';
    let oauthHtml    = '';
    const rowCtr = {r: 0};

    for (const section of (spec.sections || [])) {
        let bodyHtml = '';
        if (section.auth) {
            const disconnHtml = _buildManageSectionItems(id, section.auth.disconnected, rowCtr);
            const connHtml    = _buildManageSectionItems(id, section.auth.connected, rowCtr);
            bodyHtml = `
      <div id="${eid}-manage-disconnected"><div style="padding:8px 10px;">${disconnHtml}</div></div>
      <div id="${eid}-manage-connected" style="display:none;"><div style="padding:8px 10px;">${connHtml}</div></div>`;

            let _oauthModalBuilt = false;
            for (const block of (section.auth.disconnected || [])) {
                if (block.type === 'button' && block.action &&
                        (block.action.type === 'oauth_paste' || block.action.type === 'oauth_popup')) {
                    if (!_oauthModalBuilt) {
                        oauthHtml += _buildManageOauthHtml(id, block.action);
                        _oauthModalBuilt = true;
                    }
                }
            }
        } else {
            bodyHtml = `<div style="padding:8px 10px;">${_buildManageSectionItems(id, section.items, rowCtr)}</div>`;
        }

        const titleHtml = section.title
            ? `<div class="hub-section-label">${escHtml(section.title)}</div>`
            : '';
        sectionsHtml += `<div class="hub-section">${titleHtml}${bodyHtml}</div>`;
    }

    return `
<div id="${eid}-manage-modal" class="modal-overlay sub-modal" style="display:none;" onclick="if(event.target===this)_closeManageModal('${eid}')">
  <div class="modal-content" style="width:380px;max-height:90vh;overflow-y:auto;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <h2 style="margin:0;color:var(--text-primary);">${escHtml(name)}</h2>
      <button onclick="_closeManageModal('${eid}')" style="${closeStyle}">&#x2715;</button>
    </div>
    ${sectionsHtml}
  </div>
</div>
${oauthHtml}`;
}

function openPluginsModal() {
    document.getElementById('plugins-modal').style.display = 'flex';
    _renderPluginsList().then(() => _checkPluginUpdates());
    _renderPluginCatalog();
}
function closePluginsModal() {
    document.getElementById('plugins-modal').style.display = 'none';
    document.getElementById('plugin-install-status').style.display = 'none';
    document.getElementById('plugin-github-row').style.display = 'none';
    document.getElementById('plugin-github-url').value = '';
}
function _toggleGithubInput() {
    const row = document.getElementById('plugin-github-row');
    const visible = row.style.display !== 'none';
    row.style.display = visible ? 'none' : '';
    if (!visible) document.getElementById('plugin-github-url').focus();
}

async function _renderPluginsList() {
    const body = document.getElementById('plugins-list-body');
    body.innerHTML = '<div style="color:var(--text-secondary);font-size:0.85rem;">Loading...</div>';
    try {
        const [pluginsResp, statusResp, incompatResp] = await Promise.all([
            fetch('/api/plugins'),
            fetch('/api/plugins/launcher-status'),
            fetch('/api/plugins/incompatible'),
        ]);
        const plugins = await pluginsResp.json();
        const launcherStatus = await statusResp.json();
        const incompatible = await incompatResp.json();
        if (!plugins.length && !incompatible.length) {
            body.innerHTML = '<div style="color:var(--text-secondary);font-size:0.85rem;">No plugins installed.</div>';
            return;
        }
        const incompatibleHtml = incompatible.map((p, idx) => {
            const pluginRow = plugins.length + idx + 2;
            return `
            <div class="hub-section" id="plugin-row-${escHtml(p.id)}">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div>
                        <div style="font-size:0.95rem;color:var(--text-primary);font-weight:600;">${escHtml(p.name)}</div>
                        <div style="font-size:0.75rem;color:#8f98a0;margin-top:2px;">v${escHtml(p.version)} &middot; platform: ${escHtml(p.platform)}${p.game_count ? ` &middot; ${p.game_count} game${p.game_count !== 1 ? 's' : ''}` : ''}</div>
                    </div>
                    <div style="display:flex;flex-shrink:0;margin-left:12px;gap:6px;">
                        <button class="nav-btn" id="plugin-uninstall-btn-${escHtml(p.id)}" style="font-size:0.78rem;"
                                data-modal-row="${pluginRow}"
                                onclick="_showUninstallConfirm('${escHtml(p.id)}',${p.game_count},this)">
                            Uninstall
                        </button>
                    </div>
                </div>
                <div style="margin-top:6px;font-size:0.78rem;color:#ffa500;">&#9888; Needs PlayDate ${escHtml(p.min_core_version)} or newer (this build is ${escHtml(p.current_version)}) — not loaded</div>
                <div id="plugin-confirm-${escHtml(p.id)}" style="display:none;margin-top:10px;padding:10px 12px;background:rgba(199,71,71,0.1);border:1px solid rgba(199,71,71,0.3);border-radius:4px;font-size:0.82rem;">
                    <div style="color:var(--text-primary);margin-bottom:8px;">Delete the <strong>${escHtml(p.name)}</strong> plugin folder?</div>
                    ${p.game_count > 0 ? `
                    <label style="display:flex;align-items:center;gap:8px;color:var(--text-primary);cursor:pointer;margin-bottom:8px;">
                        <input type="checkbox" id="uninstall-rm-games-${escHtml(p.id)}" style="width:auto;margin:0;">
                        Also remove ${p.game_count} game${p.game_count !== 1 ? 's' : ''} from library
                    </label>` : ''}
                    <div style="display:flex;gap:8px;">
                        <button class="nav-btn" style="font-size:0.78rem;background:rgba(199,71,71,0.8);border-color:rgba(199,71,71,0.8);" data-modal-row="${pluginRow}"
                                onclick="_doUninstallPlugin('${escHtml(p.id)}',${p.game_count})">Confirm</button>
                        <button class="nav-btn" style="font-size:0.78rem;" data-modal-row="${pluginRow}"
                                onclick="_hideUninstallConfirm('${escHtml(p.id)}')">Cancel</button>
                    </div>
                </div>
            </div>`;
        }).join('');
        const compatibleHtml = plugins.map((p, pluginIdx) => {
            const pluginRow = pluginIdx + 2;
            const needsLauncher = p.launcher && p.launcher.required;
            const lstatus = launcherStatus[p.platform];
            let launcherBadge = '';
            if (needsLauncher) {
                if (!lstatus) {
                    launcherBadge = `<div style="margin-top:6px;font-size:0.78rem;color:#ffa500;">&#9888; Launcher not yet checked</div>`;
                } else if (lstatus.available) {
                    launcherBadge = `<div style="margin-top:6px;font-size:0.78rem;color:#6dc46d;">&#10003; Launcher ready</div>`;
                } else {
                    launcherBadge = `<div style="margin-top:6px;font-size:0.78rem;color:#ffa500;">&#9888; ${escHtml(lstatus.detail || 'Launcher unavailable')}</div>`;
                }
            }
            if (p.manage_ui) _manageSpecs[p.id] = {name: p.name, spec: p.manage_ui};
            const manageBtn = p.manage_ui
                ? `<button class="nav-btn" style="font-size:0.78rem;flex-shrink:0;margin-left:8px;" data-modal-row="${pluginRow}" onclick="_openManageModal('${escHtml(p.id)}')">Manage</button>`
                : '';
            return `
            <div class="hub-section" id="plugin-row-${escHtml(p.id)}">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div>
                        <div style="font-size:0.95rem;color:var(--text-primary);font-weight:600;">${escHtml(p.name)}</div>
                        <div style="font-size:0.75rem;color:#8f98a0;margin-top:2px;">v${escHtml(p.version)} &middot; platform: ${escHtml(p.platform)} &middot; ${p.game_count} game${p.game_count !== 1 ? 's' : ''}${p.source ? `<span id="plugin-update-${escHtml(p.id)}"></span>` : ''}</div>
                    </div>
                    <div style="display:flex;flex-shrink:0;margin-left:12px;gap:6px;">
                        ${manageBtn}
                        <button class="nav-btn" id="plugin-uninstall-btn-${escHtml(p.id)}" style="font-size:0.78rem;"
                                data-modal-row="${pluginRow}"
                                onclick="_showUninstallConfirm('${escHtml(p.id)}',${p.game_count},this)">
                            Uninstall
                        </button>
                    </div>
                </div>
                ${launcherBadge}
                <div id="plugin-confirm-${escHtml(p.id)}" style="display:none;margin-top:10px;padding:10px 12px;background:rgba(199,71,71,0.1);border:1px solid rgba(199,71,71,0.3);border-radius:4px;font-size:0.82rem;">
                    <div style="color:var(--text-primary);margin-bottom:8px;">Delete the <strong>${escHtml(p.name)}</strong> plugin folder?</div>
                    ${p.game_count > 0 ? `
                    <label style="display:flex;align-items:center;gap:8px;color:var(--text-primary);cursor:pointer;margin-bottom:8px;">
                        <input type="checkbox" id="uninstall-rm-games-${escHtml(p.id)}" style="width:auto;margin:0;">
                        Also remove ${p.game_count} game${p.game_count !== 1 ? 's' : ''} from library
                    </label>` : ''}
                    ${p.launcher && p.launcher.required ? `
                    <label style="display:flex;align-items:center;gap:8px;color:var(--text-primary);cursor:pointer;margin-bottom:8px;">
                        <input type="checkbox" id="uninstall-rm-launcher-${escHtml(p.id)}" style="width:auto;margin:0;" checked>
                        Also delete launcher and installed games
                    </label>` : ''}
                    <div style="display:flex;gap:8px;">
                        <button class="nav-btn" style="font-size:0.78rem;background:rgba(199,71,71,0.8);border-color:rgba(199,71,71,0.8);" data-modal-row="${pluginRow}"
                                onclick="_doUninstallPlugin('${escHtml(p.id)}',${p.game_count})">Confirm</button>
                        <button class="nav-btn" style="font-size:0.78rem;" data-modal-row="${pluginRow}"
                                onclick="_hideUninstallConfirm('${escHtml(p.id)}')">Cancel</button>
                    </div>
                </div>
            </div>`;
        }).join('');
        body.innerHTML = compatibleHtml + incompatibleHtml;
    } catch(e) {
        const msg = (e && e.message) ? e.message : String(e);
        body.innerHTML = `<div style="color:#c74747;font-size:0.85rem;">Failed to load plugins: ${escHtml(msg)}</div>`;
        fetch('/api/log-js-error', {method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({context:'_renderPluginsList', error: msg, stack: e && e.stack ? e.stack : ''})
        }).catch(function(){});
    }
}

// Row indices start well above anything _renderPluginsList() could ever
// produce (plugins.length + incompatible.length + 2, realistically single
// digits) -- this section always renders below that list, so a fixed high
// offset keeps gamepad nav order correct without coordinating live counts
// between two independently-rendered sections. Assigned sequentially
// top-to-bottom (section headers included) as the catalog is built, so
// nav order always matches visual order regardless of which sections have
// anything in them this time.
const CATALOG_ROW_BASE = 100;
const CATALOG_STATUS_LABELS = {working: 'Working', untested: 'Untested', broken: 'Broken'};
const CATALOG_PLATFORM_LABELS = {windows: 'Windows', linux: 'Linux', mac: 'Mac'};
// Which buckets start expanded -- Working is the actionable one, Untested/
// Broken stay tucked away since most users won't care to look.
let _catalogExpanded = {working: true, untested: false, broken: false};

async function _renderPluginCatalog() {
    const section = document.getElementById('plugin-catalog-section');
    const body    = document.getElementById('plugin-catalog-body');
    try {
        const r = await fetch('/api/plugins/catalog');
        const data = await r.json();
        const entries = data.plugins || [];
        if (!entries.length) { section.style.display = 'none'; return; }
        section.style.display = '';

        const buckets = {working: [], untested: [], broken: []};
        for (const p of entries) (buckets[p.status] || buckets.untested).push(p);

        const platformLabel = CATALOG_PLATFORM_LABELS[data.platform] || data.platform;
        let row = CATALOG_ROW_BASE;
        let html = `<div class="hub-section-label">Plugin Catalog `
                  + `<span style="font-weight:normal;color:#8f98a0;">(status shown is for ${escHtml(platformLabel)})</span></div>`;

        for (const key of ['working', 'untested', 'broken']) {
            const list = buckets[key];
            if (!list.length) continue;
            const expanded = _catalogExpanded[key];
            html += `
            <div class="hub-section" style="padding:8px 12px;cursor:pointer;" data-modal-row="${row++}"
                 onclick="_toggleCatalogSection('${key}')">
                <span id="catalog-toggle-${key}">${expanded ? '▾' : '▸'}</span>
                ${CATALOG_STATUS_LABELS[key]} (${list.length})
            </div>
            <div id="catalog-list-${key}" style="display:${expanded ? '' : 'none'};">`;
            for (const p of list) {
                html += `
                <div class="hub-section" id="catalog-plugin-row-${escHtml(p.id)}" style="display:flex;justify-content:space-between;align-items:center;margin-left:12px;">
                    <div>
                        <div style="font-size:0.9rem;color:var(--text-primary);">${escHtml(p.name)}${p.beta ? ' <span style="font-size:0.72rem;color:#8f98a0;">(beta)</span>' : ''}</div>
                        ${p.note ? `<div style="font-size:0.75rem;color:#8f98a0;margin-top:2px;">${escHtml(p.note)}</div>` : ''}
                    </div>
                    <button class="nav-btn" style="font-size:0.78rem;flex-shrink:0;margin-left:12px;"
                            data-modal-row="${row++}"
                            onclick="_installCatalogPlugin('${escHtml(p.source)}',this)">Install</button>
                </div>`;
            }
            html += `</div>`;
        }
        body.innerHTML = html;
    } catch (e) {
        section.style.display = 'none';
    }
}

function _toggleCatalogSection(key) {
    _catalogExpanded[key] = !_catalogExpanded[key];
    const list   = document.getElementById(`catalog-list-${key}`);
    const toggle = document.getElementById(`catalog-toggle-${key}`);
    if (list)   list.style.display = _catalogExpanded[key] ? '' : 'none';
    if (toggle) toggle.textContent = _catalogExpanded[key] ? '▾' : '▸';
}

async function _installCatalogPlugin(source, btn) {
    btn.disabled = true;
    btn.textContent = 'Installing...';
    try {
        const r = await fetch('/api/plugins/install-from-github', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: source}),
        });
        const d = await r.json();
        if (d.status === 'success') {
            btn.textContent = 'Installed — restart to activate';
            document.getElementById('plugins-restart-notice').style.display = '';
        } else {
            btn.disabled = false;
            btn.textContent = 'Install';
            alert(d.message || 'Install failed.');
        }
    } catch (e) {
        btn.disabled = false;
        btn.textContent = 'Install';
        alert('Install failed.');
    }
}

function _showUninstallConfirm(id, gameCount, btn) {
    document.getElementById(`plugin-confirm-${id}`).style.display = '';
    btn.style.display = 'none';
}
function _hideUninstallConfirm(id) {
    document.getElementById(`plugin-confirm-${id}`).style.display = 'none';
    const btn = document.getElementById(`plugin-uninstall-btn-${id}`);
    if (btn) btn.style.display = '';
}

async function _doUninstallPlugin(id, gameCount) {
    const removeGames = gameCount > 0 && document.getElementById(`uninstall-rm-games-${id}`)?.checked;
    const removeLauncher = document.getElementById(`uninstall-rm-launcher-${id}`)?.checked || false;
    try {
        const r = await fetch(`/api/plugins/${encodeURIComponent(id)}/uninstall`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({remove_games: removeGames, remove_launcher: removeLauncher}),
        });
        const d = await r.json();
        if (d.status === 'success') {
            const row = document.getElementById(`plugin-row-${id}`);
            if (row) row.innerHTML = `<div style="font-size:0.85rem;color:#8f98a0;">${escHtml(id)} uninstalled.</div>`;
            document.getElementById('plugins-restart-notice').style.display = '';
        } else {
            alert(d.message || 'Uninstall failed.');
        }
    } catch(e) {
        alert('Uninstall failed.');
    }
}

async function _installPluginFromFile(input) {
    const file = input.files[0];
    input.value = '';
    if (!file) return;
    _showPluginStatus(`Installing ${escHtml(file.name)}...`, 'loading');
    const formData = new FormData();
    formData.append('plugin_file', file);
    try {
        const r = await fetch('/api/plugins/install', { method: 'POST', body: formData });
        const d = await r.json();
        if (d.status === 'success') {
            _showPluginStatus(`${escHtml(d.name)} installed. Restart to load it.`, 'success');
            document.getElementById('plugins-restart-notice').style.display = '';
        } else {
            _showPluginStatus(d.message || 'Install failed.', 'error');
        }
    } catch(e) {
        _showPluginStatus('Install failed.', 'error');
    }
}

function _showPluginStatus(msg, type) {
    const statusEl = document.getElementById('plugin-install-status');
    statusEl.style.display = '';
    const styles = {
        loading: ['rgba(100,100,100,0.15)', '1px solid rgba(100,100,100,0.3)', 'var(--text-secondary)'],
        success: ['rgba(100,200,100,0.1)',  '1px solid rgba(100,200,100,0.3)', '#6dc46d'],
        error:   ['rgba(199,71,71,0.1)',    '1px solid rgba(199,71,71,0.3)',   '#c74747'],
    };
    const [bg, border, color] = styles[type] || styles.loading;
    statusEl.style.background = bg;
    statusEl.style.border = border;
    statusEl.style.color = color;
    statusEl.textContent = msg;
}

async function _doGithubInstall(url) {
    _showPluginStatus('Fetching release from GitHub...', 'loading');
    try {
        const r = await fetch('/api/plugins/install-from-github', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url}),
        });
        const d = await r.json();
        if (d.status === 'success') {
            _showPluginStatus(`${escHtml(d.name)} (${escHtml(d.tag)}) installed. Restart to load it.`, 'success');
            document.getElementById('plugins-restart-notice').style.display = '';
        } else {
            _showPluginStatus(d.message || 'Install failed.', 'error');
        }
    } catch(e) {
        _showPluginStatus('Install failed.', 'error');
    }
}

async function _installPluginFromGithub() {
    const url = document.getElementById('plugin-github-url').value.trim();
    if (!url) return;
    document.getElementById('plugin-github-row').style.display = 'none';
    document.getElementById('plugin-github-url').value = '';
    await _doGithubInstall(url);
}

async function _updatePlugin(id, source) {
    const updateEl = document.getElementById(`plugin-update-${id}`);
    if (updateEl) updateEl.textContent = ' · updating...';
    await _doGithubInstall(source.replace('github:', ''));
    await _renderPluginsList();
    _checkPluginUpdates();
}

async function _checkPluginUpdates() {
    try {
        const r = await fetch('/api/plugins/check-updates');
        const updates = await r.json();
        let anyStandalone = false;  // installable on its own right now
        let anyGated = false;       // update exists but needs a newer core first
        window._pendingPluginUpdates = [];
        for (const u of updates) {
            if (!u.update_available) continue;
            if (u.requires_core) anyGated = true; else anyStandalone = true;
            // Keep gated updates in the pending list: the "Update PlayDate &
            // Plugins" flow installs them against the target core version, which
            // clears their min_core_version requirement. Only the standalone
            // update link is gated -- installing it on its own would fail the
            // install-time min_core_version check.
            window._pendingPluginUpdates.push({ id: u.id, source: u.source, latest_version: u.latest_version, requires_core: u.requires_core || null });
            const el = document.getElementById(`plugin-update-${u.id}`);
            if (!el) continue;
            if (u.requires_core) {
                el.innerHTML = ` &middot; <span style="color:#ffa500;" title="Update PlayDate to at least ${escHtml(u.requires_core)} to get this. The &quot;Update PlayDate &amp; Plugins&quot; button on the update prompt does both at once.">v${escHtml(u.latest_version)} &middot; needs PlayDate ${escHtml(u.requires_core)}</span>`;
            } else {
                el.innerHTML = ` &middot; <a href="#" style="color:var(--accent);" onclick="event.preventDefault();_updatePlugin('${escHtml(u.id)}','${escHtml(u.source || '')}')">v${escHtml(u.latest_version)} available</a>`;
            }
        }
        if (anyStandalone || anyGated) {
            document.getElementById('plugin-update-dot')?.style.setProperty('visibility', 'visible');
        }
        // The global hamburger dot only for updates the user can act on directly.
        // A gated plugin update is surfaced through the PlayDate-update prompt
        // instead (which lights this dot on its own when a core update exists);
        // lighting it here too would be a dead end when no core update is available.
        if (anyStandalone) {
            document.getElementById('update-dot')?.classList.add('visible');
        }
    } catch(e) { /* silent */ }
}

function _renderPlatformPriorityList() {
    const list = document.getElementById('platform-priority-list');
    list.innerHTML = '';
    _platPriority.forEach((plat, i) => {
        const li = document.createElement('li');
        li.dataset.plat = plat;
        li.dataset.modalRow = i + 1;
        li.innerHTML = `<span class="plat-rank">${i + 1}</span><span style="pointer-events:none;">⠿</span><span style="flex:1; pointer-events:none;">${escHtml(_PLAT_PRIORITY_LABELS[plat] || plat)}</span>`;
        li.addEventListener('mousedown', e => { e.preventDefault(); _platBeginDrag(li); });
        list.appendChild(li);
    });
}

function _platBeginDrag(li) {
    const list = document.getElementById('platform-priority-list');
    _platPriorityDragSrc = li;
    li.classList.add('plat-dragging');
    document.body.classList.add('plat-priority-dragging');

    function onMove(e) {
        list.querySelectorAll('.plat-drag-over').forEach(el => el.classList.remove('plat-drag-over'));
        _platPriorityHover = null;
        const items = Array.from(list.querySelectorAll('li:not(.plat-dragging)'));
        for (const item of items) {
            const r = item.getBoundingClientRect();
            if (e.clientY >= r.top && e.clientY <= r.bottom) {
                item.classList.add('plat-drag-over');
                _platPriorityHover = item;
                break;
            }
        }
        if (!_platPriorityHover && items.length) {
            const last = items[items.length - 1];
            if (e.clientY > last.getBoundingClientRect().bottom) {
                last.classList.add('plat-drag-over');
                _platPriorityHover = last;
            }
        }
    }

    function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        li.classList.remove('plat-dragging');
        document.body.classList.remove('plat-priority-dragging');
        list.querySelectorAll('.plat-drag-over').forEach(el => el.classList.remove('plat-drag-over'));
        if (_platPriorityHover && _platPriorityHover !== li) {
            const kids = Array.from(list.children);
            if (kids.indexOf(li) < kids.indexOf(_platPriorityHover))
                list.insertBefore(li, _platPriorityHover.nextSibling);
            else
                list.insertBefore(li, _platPriorityHover);
        }
        _platPriorityDragSrc = null;
        _platPriorityHover = null;
        _updatePlatRanks();
    }

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

function _updatePlatRanks() {
    Array.from(document.getElementById('platform-priority-list').children).forEach((li, i) => {
        li.querySelector('.plat-rank').textContent = i + 1;
    });
}

async function savePlatformPriority() {
    const order = Array.from(document.getElementById('platform-priority-list').children).map(li => li.dataset.plat);
    const status = document.getElementById('plat-priority-status');
    status.textContent = 'Saving…';
    try {
        const r1 = await fetch('/api/update_state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platform_priority: order })
        });
        if (!r1.ok) { status.textContent = '✘ Save failed'; return; }
        _platPriority = order;
        status.textContent = 'Redetecting…';
        const r2 = await fetch('/api/detect-duplicates', { method: 'POST' });
        const d = await r2.json();
        if (r2.ok) {
            status.textContent = `Saved — ${d.detected ?? 0} duplicate${d.detected !== 1 ? 's' : ''} detected`;
            window.location.reload();
        } else {
            status.textContent = '✘ Detection failed';
        }
    } catch (e) {
        status.textContent = '✘ Error: ' + e.message;
    }
}
async function detectDuplicates() {
    const status = document.getElementById('plat-priority-status');
    status.textContent = 'Detecting…';
    try {
        const r = await fetch('/api/detect-duplicates', { method: 'POST' });
        const d = await r.json();
        if (r.ok) {
            status.textContent = `${d.detected ?? 0} duplicate${d.detected !== 1 ? 's' : ''} detected`;
            if ((d.detected ?? 0) > 0) setTimeout(() => window.location.reload(), 1200);
        } else {
            status.textContent = '✘ Detection failed';
        }
    } catch (e) {
        status.textContent = '✘ Error: ' + e.message;
    }
}
async function runPopSync(confirmCleanup) {
    const status = document.getElementById('pop-sync-status');
    status.textContent = confirmCleanup === undefined ? 'Syncing…' : 'Updating…';
    try {
        const body = confirmCleanup === undefined ? {} : { confirm_cleanup: confirmCleanup };
        const r = await fetch('/api/pop-sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const d = await r.json();
        if (d.status === 'confirm_cleanup') {
            const tags = d.stale_tags || [];
            const label = tags.length === 1 ? `the "${tags[0]}" group` : `these groups: ${tags.join(', ')}`;
            const remove = await confirmCustom(
                `New Play or Pay cycle detected.\n\nRemove ${label} from previously picked games?`,
                'Remove', 'Keep'
            );
            return runPopSync(remove);
        }
        if (r.ok && d.status !== 'error') {
            status.textContent = d.message || 'Done.';
        } else {
            status.textContent = '✘ ' + (d.message || 'Sync failed');
        }
    } catch (e) {
        status.textContent = '✘ Error: ' + e.message;
    }
}

async function openCommunityModal() {
    document.getElementById('community-modal').style.display = 'flex';
    try {
        const res   = await fetch('/api/blaeo-status');
        const state = await res.json();
        const status = document.getElementById('blaeo-status');
        if (state.done) {
            _hideBlaeoNotification();
            status.className = 'tool-status info';
            status.textContent = 'Loading results...';
            await _loadBlaeoPreview();
        } else if (state.running) {
            status.className = 'tool-status info';
            status.textContent = 'BLAEO sync in progress...';
        } else if (state.error) {
            status.className = 'tool-status error';
            status.textContent = '✘ ' + state.error;
        }
    } catch(e) {}
}
function closeCommunityModal() {
    document.getElementById('community-modal').style.display = 'none';
}
function openDataModal() {
    document.getElementById('data-modal').style.display = 'flex';
}
function closeDataModal() {
    document.getElementById('data-modal').style.display = 'none';
}
let _openBaseDirBusy = false;
function openBaseDir() {
    if (_openBaseDirBusy) return;
    _openBaseDirBusy = true;
    fetch('/api/open-base-dir', { method: 'POST' }).catch(() => {});
    setTimeout(() => { _openBaseDirBusy = false; }, 1000);
}
function openSystemModal() {
    document.getElementById('system-modal').style.display = 'flex';
}
function closeSystemModal() {
    document.getElementById('system-modal').style.display = 'none';
}
function _onHltbSlider(el) {
    document.getElementById('hltb-threshold-val').textContent = el.value;
    const pct = (el.value - el.min) / (el.max - el.min) * 100;
    el.style.setProperty('--slider-pct', pct + '%');
}

function saveHltbThreshold() {
    const val = parseInt(document.getElementById('hltb-threshold-slider').value, 10);
    const status = document.getElementById('hltb-threshold-status');
    savePreference({ hltb_match_threshold: val });
    status.textContent = 'Saved.';
    setTimeout(() => { status.textContent = ''; }, 2000);
}

(function _initHltbSlider() {
    const el = document.getElementById('hltb-threshold-slider');
    if (!el) return;
    const pct = (el.value - el.min) / (el.max - el.min) * 100;
    el.style.setProperty('--slider-pct', pct + '%');
})();

function resizeToSteamDeck() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.resize_window) {
        window.pywebview.api.resize_window(1280, 800);
    }
}

// ── Gamepad Diagnostics ────────────────────────────────────────────────────

// Indices 2/3 are swapped relative to the W3C Standard Gamepad spec (buttons[2]
// should be X, buttons[3] should be Y) to match what's actually reported for
// the physical X/Y buttons — see the matching note on BTN_IDX in input.js.
const BTN_LABELS = {
    0:'A', 1:'B', 2:'Y', 3:'X',
    4:'LB', 5:'RB', 6:'LT', 7:'RT',
    8:'Back', 9:'Start',
    10:'L3', 11:'R3',
    12:'Up', 13:'Down', 14:'Left', 15:'Right',
    16:'Guide',
};

// Same physical button positions, PlayStation naming/glyphs — used instead of
// BTN_LABELS when a PlayStation-family pad is detected (see _isPlayStationPad).
const BTN_LABELS_PS = {
    0:'✕', 1:'○', 2:'△', 3:'□', // Cross, Circle, Triangle, Square
    4:'L1', 5:'R1', 6:'L2', 7:'R2',
    8:'Share', 9:'Options',
    10:'L3', 11:'R3',
    12:'Up', 13:'Down', 14:'Left', 15:'Right',
    16:'PS',
};

// Sony's USB vendor ID (054c) appears in gp.id on every browser/platform this
// app runs on; name substrings cover cases where the id string omits it.
function _isPlayStationPad(id) {
    return /054c|dualshock|dualsense|playstation/i.test(id || '');
}

function _activeBtnLabels(gpId) {
    return _isPlayStationPad(gpId) ? BTN_LABELS_PS : BTN_LABELS;
}

// Standard face-button brand colors, keyed by the same swapped raw indices as
// BTN_LABELS/BTN_LABELS_PS. Applied as a border, not a fill, so it doesn't
// compete with the pressed/unpressed background that's the primary signal.
const FACE_BTN_COLORS_XBOX = { 0:'#3bb143', 1:'#e0393e', 2:'#f4c20d', 3:'#3a7bd5' }; // A green, B red, Y yellow, X blue
const FACE_BTN_COLORS_PS   = { 0:'#3a7bd5', 1:'#e0393e', 2:'#3bb143', 3:'#e05fa0' }; // Cross blue, Circle red, Triangle green, Square pink

function _faceButtonColor(physIdx, gpId) {
    const colors = _isPlayStationPad(gpId) ? FACE_BTN_COLORS_PS : FACE_BTN_COLORS_XBOX;
    return colors[physIdx] || null;
}

function _firstConnectedGamepadId() {
    const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    for (const g of gamepads) { if (g) return g.id; }
    return '';
}

let _gpdRafId = null;

function openGamepadDiag() {
    document.getElementById('gamepad-diag-modal').style.display = 'flex';
    _gpdRefreshStatic();
    _gpdStartPoll();
}

function closeGamepadDiag() {
    document.getElementById('gamepad-diag-modal').style.display = 'none';
    _gpdStopPoll();
}

function _gpdRefreshStatic() {
    // Suppression
    const suppressed = safeSession.getItem('pd_game_running') === '1';
    const supEl = document.getElementById('gpd-suppression');
    const clearBtn = document.getElementById('gpd-clear-btn');
    if (suppressed) {
        supEl.textContent = 'Active — gamepad input is blocked';
        supEl.style.color = 'var(--text-danger)';
        clearBtn.style.display = '';
    } else {
        supEl.textContent = 'Not active';
        supEl.style.color = 'var(--accent-positive)';
        clearBtn.style.display = 'none';
    }
}

function gpdClearSuppression() {
    if (window._inputMgr) window._inputMgr.clearSuppression();
    _gpdRefreshStatic();
}

function _gpdStartPoll() {
    if (_gpdRafId) return;
    function poll() {
        _gpdRafId = requestAnimationFrame(poll);

        const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
        let gp = null;
        for (const g of gamepads) { if (g) { gp = g; break; } }

        // Controller
        const ctrlEl = document.getElementById('gpd-controller');
        ctrlEl.textContent = gp ? gp.id : 'None detected';
        ctrlEl.style.color = gp ? 'var(--text-primary)' : 'var(--text-danger)';

        // Navigation active
        const activeEl = document.getElementById('gpd-active');
        const isActive = window._inputMgr
            ? (safeSession.getItem('pd_game_running') !== '1')
            : false;
        activeEl.textContent = isActive ? 'Ready' : 'Suppressed or unavailable';
        activeEl.style.color = isActive ? 'var(--accent-positive)' : 'var(--text-danger)';

        // Mapping
        const mapEl = document.getElementById('gpd-mapping');
        if (gp) {
            const mapping = gp.mapping || '(none)';
            mapEl.textContent = `mapping: ${mapping}`;
            mapEl.style.color = gp.mapping === 'standard' ? 'var(--text-secondary)' : 'var(--text-danger)';
        } else {
            mapEl.textContent = '';
        }

        if (!gp) {
            document.getElementById('gpd-buttons').innerHTML = '';
            document.getElementById('gpd-lstick').textContent = 'x: --  y: --';
            document.getElementById('gpd-rstick').textContent = 'x: --  y: --';
            document.getElementById('gpd-axes-raw').textContent = '--';
            return;
        }

        // Buttons — face buttons render in reading order (A B X Y) rather than
        // raw index order (0,1,2,3 = A,B,Y,X after the index swap); everything
        // else follows in natural ascending order, so nothing raw is hidden.
        const btnEl = document.getElementById('gpd-buttons');
        const labels = _activeBtnLabels(gp.id);
        const displayOrder = [0, 1, 3, 2, ...gp.buttons.map((_, i) => i).filter(i => i > 3)];
        let btnHtml = '';
        displayOrder.forEach(i => {
            const btn = gp.buttons[i];
            if (!btn) return;
            const pressed = btn.pressed || btn.value > 0.5;
            const label = labels[i] || i;
            const bg = pressed ? 'var(--accent)' : 'rgba(255,255,255,0.07)';
            const color = pressed ? 'var(--on-accent)' : 'var(--text-secondary)';
            const faceColor = _faceButtonColor(i, gp.id);
            const border = faceColor ? `2px solid ${faceColor}` : '2px solid transparent';
            btnHtml += `<span style="box-sizing:border-box;padding:1px 7px;border-radius:4px;font-size:0.78rem;background:${bg};color:${color};border:${border};transition:background 0.08s;">${label}</span>`;
        });
        btnEl.innerHTML = btnHtml;

        // Sticks
        const fmt = v => (v >= 0 ? ' ' : '') + v.toFixed(2);
        document.getElementById('gpd-lstick').textContent =
            `x: ${fmt(gp.axes[0] || 0)}  y: ${fmt(gp.axes[1] || 0)}`;
        document.getElementById('gpd-rstick').textContent =
            `x: ${fmt(gp.axes[2] || 0)}  y: ${fmt(gp.axes[3] || 0)}`;

        // Full raw axes array — a leaked hat switch (unmapped D-pad) shows up here
        // as extra axes beyond the two known sticks (indices 0-3).
        document.getElementById('gpd-axes-raw').textContent =
            gp.axes.map((v, i) => `[${i}] ${fmt(v)}`).join('   ');
    }
    _gpdRafId = requestAnimationFrame(poll);
}

function _gpdStopPoll() {
    if (_gpdRafId) { cancelAnimationFrame(_gpdRafId); _gpdRafId = null; }
}

// ── Gamepad Remap ─────────────────────────────────────────────────────────────
const _REMAP_ACTIONS = [
    { action: 'a',     defaultBtn: 0,  label: 'Confirm / Select' },
    { action: 'b',     defaultBtn: 1,  label: 'Back / Cancel' },
    { action: 'x',     defaultBtn: 3,  label: 'Context Menu' },
    { action: 'y',     defaultBtn: 2,  label: 'Filter / Search' },
    { action: 'lb',    defaultBtn: 4,  label: 'Previous Page' },
    { action: 'rb',    defaultBtn: 5,  label: 'Next Page' },
    { action: 'back',  defaultBtn: 8,  label: 'Open Menu' },
    { action: 'start', defaultBtn: 9,  label: 'System' },
    { action: 'up',    defaultBtn: 12, label: 'Navigate Up' },
    { action: 'down',  defaultBtn: 13, label: 'Navigate Down' },
    { action: 'left',  defaultBtn: 14, label: 'Navigate Left' },
    { action: 'right', defaultBtn: 15, label: 'Navigate Right' },
];

// Map<action, physicalBtnIdx> — UI working state
let _remapState = new Map();
let _captureAction = null;
let _grmRafId = null;
let _grmPrevBtns = {};

function _grmBtnLabel(physIdx) {
    const labels = _activeBtnLabels(_firstConnectedGamepadId());
    return labels[physIdx] !== undefined ? labels[physIdx] : String(physIdx);
}

function _grmBuildState() {
    _remapState = new Map();
    const saved = window._BUTTON_REMAPS || {};
    // saved format: {physIdx: actionName} -- invert to Map<action, physIdx>
    const inverted = {};
    for (const [k, v] of Object.entries(saved)) inverted[v] = parseInt(k, 10);
    for (const { action, defaultBtn } of _REMAP_ACTIONS) {
        _remapState.set(action, inverted[action] !== undefined ? inverted[action] : defaultBtn);
    }
}

function _grmStateToStorage() {
    const out = {};
    for (const { action, defaultBtn } of _REMAP_ACTIONS) {
        const assigned = _remapState.get(action);
        if (assigned !== defaultBtn) out[String(assigned)] = action;
    }
    return out;
}

function _grmRenderRows() {
    const container = document.getElementById('grm-rows');
    if (!container) return;
    let html = '';
    const gpId = _firstConnectedGamepadId();
    for (const { action, label } of _REMAP_ACTIONS) {
        const physIdx = _remapState.get(action);
        const btnLabel = _grmBtnLabel(physIdx);
        const faceColor = _faceButtonColor(physIdx, gpId);
        const badgeBorder = faceColor ? `2px solid ${faceColor}` : '2px solid transparent';
        const isCapturing = _captureAction === action;
        html += `<div style="display:flex; align-items:center; gap:10px; padding:6px 8px; border-radius:6px; background:rgba(255,255,255,0.04);">
            <div style="flex:1; font-size:0.88rem; color:var(--text-primary);">${escHtml(label)}</div>
            ${isCapturing
                ? `<span style="font-size:0.8rem; color:var(--accent); font-style:italic;">Press any button...</span>
                   <button class="nav-btn" data-modal-row="${_REMAP_ACTIONS.findIndex(a=>a.action===action)}" onclick="grmCancelCapture()" style="font-size:0.78rem; padding:3px 10px;">Cancel</button>`
                : `<span style="box-sizing:border-box; display:inline-block; min-width:38px; text-align:center; padding:1px 7px; border-radius:4px; background:rgba(255,255,255,0.1); font-size:0.8rem; color:var(--text-primary); border:${badgeBorder};">${escHtml(btnLabel)}</span>
                   <button class="nav-btn" data-modal-row="${_REMAP_ACTIONS.findIndex(a=>a.action===action)}" onclick="grmStartCapture('${action}')" style="font-size:0.78rem; padding:3px 10px;">Change</button>`
            }
        </div>`;
    }
    container.innerHTML = html;
}

function _grmSave() {
    const storage = _grmStateToStorage();
    window._BUTTON_REMAPS = storage;
    savePreference({ button_remaps: storage });
    if (window._inputMgr) window._inputMgr.setButtonRemaps(storage);
}

function openGamepadRemap() {
    _grmBuildState();
    _captureAction = null;
    _grmPrevBtns = {};
    document.getElementById('gamepad-remap-modal').style.display = 'flex';
    _grmRenderRows();
    _grmStartPoll();
}

function closeGamepadRemap() {
    _captureAction = null;
    if (window._inputMgr) window._inputMgr.setCapturing(false);
    _grmStopPoll();
    document.getElementById('gamepad-remap-modal').style.display = 'none';
}

function grmStartCapture(action) {
    _captureAction = action;
    _grmPrevBtns = {};
    const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    for (const g of gamepads) {
        if (g) { g.buttons.forEach((b, i) => { _grmPrevBtns[i] = b.pressed || b.value > 0.5; }); break; }
    }
    if (window._inputMgr) window._inputMgr.setCapturing(true);
    _grmRenderRows();
}

function grmCancelCapture() {
    if (!_captureAction) return;
    _captureAction = null;
    if (window._inputMgr) window._inputMgr.setCapturing(false);
    _grmRenderRows();
}

function grmResetDefaults() {
    _grmBuildState();
    // Defaults are already set; clear storage
    window._BUTTON_REMAPS = {};
    savePreference({ button_remaps: {} });
    if (window._inputMgr) window._inputMgr.setButtonRemaps({});
    _captureAction = null;
    _grmRenderRows();
}

function _grmStartPoll() {
    if (_grmRafId) return;
    function poll() {
        _grmRafId = requestAnimationFrame(poll);

        const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
        let gp = null;
        for (const g of gamepads) { if (g) { gp = g; break; } }

        const ctrlEl = document.getElementById('grm-controller');
        if (ctrlEl) {
            ctrlEl.textContent = gp ? gp.id : 'No controller detected';
            ctrlEl.style.color = gp ? 'var(--text-secondary)' : 'var(--text-danger)';
        }

        if (!gp || !_captureAction) return;

        gp.buttons.forEach((btn, i) => {
            const pressed = btn.pressed || btn.value > 0.5;
            const wasPressed = !!_grmPrevBtns[i];
            if (pressed && !wasPressed) {
                // Assign this physical button to _captureAction; swap if already taken
                const target = _captureAction;
                const newPhys = i;
                const oldPhys = _remapState.get(target);
                // Find if newPhys is already used by another action
                for (const [act, phys] of _remapState) {
                    if (phys === newPhys && act !== target) {
                        _remapState.set(act, oldPhys); // swap
                        break;
                    }
                }
                _remapState.set(target, newPhys);
                _captureAction = null;
                if (window._inputMgr) window._inputMgr.setCapturing(false);
                _grmSave();
                _grmRenderRows();
            }
            _grmPrevBtns[i] = pressed;
        });
    }
    _grmRafId = requestAnimationFrame(poll);
}

function _grmStopPoll() {
    if (_grmRafId) { cancelAnimationFrame(_grmRafId); _grmRafId = null; }
}

