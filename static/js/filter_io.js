function openFilterIoModal() {
    document.getElementById('filter-io-modal').style.display = 'flex';
    document.getElementById('filter-export-status').textContent = '';
    document.getElementById('filter-import-status').textContent = '';
    document.getElementById('filter-import-rename').style.display = 'none';
    _filterImportPending = null;
    _populateFilterExportSelect();
}
function closeFilterIoModal() {
    document.getElementById('filter-io-modal').style.display = 'none';
}

// ── Filter Import / Export ────────────────────────────────────────────────────
let _filterImportPending = null; // { name, tree } awaiting a rename

function _populateFilterExportSelect() {
    const sel = document.getElementById('tools-filter-select');
    if (!sel || !sel._setOptions) return;
    const names = Object.keys(typeof _savedFilters !== 'undefined' ? _savedFilters : {});
    const opts  = names.map(n => `<option value="${n.replace(/"/g, '&quot;')}">${n}</option>`).join('');
    sel._setOptions('<option value="">Select a filter…</option>' + opts);
}

async function exportSelectedFilter() {
    const sel    = document.getElementById('tools-filter-select');
    const status = document.getElementById('filter-export-status');
    const name   = sel ? sel.value : '';
    if (!name) {
        status.textContent = 'Select a filter to export.';
        status.className   = 'tool-status error';
        return;
    }
    const entry = (typeof _savedFilters !== 'undefined' ? _savedFilters : {})[name];
    const tree = (entry && typeof entry === 'object' && 'tree' in entry) ? entry.tree : entry;
    if (!tree) {
        status.textContent = 'Filter not found.';
        status.className   = 'tool-status error';
        return;
    }
    const payload       = JSON.stringify({ playdate_filter: { name, tree } }, null, 2);
    const suggestedName = `playdate-filter-${name.replace(/[^a-z0-9_-]/gi, '_')}.json`;

    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_save_path) {
        if (_fileDlgBusy) return;
        _fileDlgBusy = true;
        let path;
        try {
            path = await window.pywebview.api.pick_save_path(suggestedName, ['JSON Files (*.json)']);
        } finally {
            setTimeout(() => { _fileDlgBusy = false; }, 300);
        }
        if (!path) return;
        status.textContent = 'Saving…';
        status.className   = 'tool-status info';
        try {
            const res  = await fetch('/api/export-filter', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path, name, tree })
            });
            const data = await res.json();
            if (data.status === 'success') {
                status.textContent = `✔ Exported "${name}".`;
                status.className   = 'tool-status success';
            } else {
                status.textContent = data.message || 'Export failed.';
                status.className   = 'tool-status error';
            }
        } catch (e) {
            status.textContent = `Error: ${e.message}`;
            status.className   = 'tool-status error';
        }
        return;
    }
    // Fallback: blob download
    const blob = new Blob([payload], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url; a.download = suggestedName;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    status.textContent = `✔ Exported "${name}".`;
    status.className   = 'tool-status success';
}

async function importFilter() {
    const status = document.getElementById('filter-import-status');
    document.getElementById('filter-import-rename').style.display = 'none';
    _filterImportPending = null;

    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_open_path) {
        if (_fileDlgBusy) return;
        _fileDlgBusy = true;
        let path;
        try {
            path = await window.pywebview.api.pick_open_path(['JSON Files (*.json)']);
        } catch (e) {
            status.textContent = `Error opening file dialog: ${e.message}`;
            status.className   = 'tool-status error';
            setTimeout(() => { _fileDlgBusy = false; }, 300);
            return;
        }
        setTimeout(() => { _fileDlgBusy = false; }, 300);
        if (!path) return;
        status.textContent = 'Reading…';
        status.className   = 'tool-status info';
        try {
            const res  = await fetch('/api/read-filter-file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path })
            });
            const data = await res.json();
            if (data.status !== 'success') {
                status.textContent = data.message || 'Failed to read file.';
                status.className   = 'tool-status error';
                return;
            }
            _doFilterImport(data.name, data.tree);
        } catch (e) {
            status.textContent = `Error: ${e.message}`;
            status.className   = 'tool-status error';
        }
        return;
    }
    // Fallback: file input
    const input  = document.createElement('input');
    input.type   = 'file';
    input.accept = '.json,application/json';
    input.onchange = () => {
        const file = input.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = e => {
            try {
                const data = JSON.parse(e.target.result);
                const pf   = data.playdate_filter || {};
                const name = (pf.name || '').trim();
                const tree = pf.tree;
                if (!name || !tree) {
                    status.textContent = 'Invalid filter file.';
                    status.className   = 'tool-status error';
                    return;
                }
                _doFilterImport(name, tree);
            } catch {
                status.textContent = 'Could not parse file.';
                status.className   = 'tool-status error';
            }
        };
        reader.readAsText(file);
    };
    document.body.appendChild(input); input.click(); document.body.removeChild(input);
}

function _doFilterImport(name, tree) {
    const status = document.getElementById('filter-import-status');
    if ((typeof _savedFilters !== 'undefined' ? _savedFilters : {})[name]) {
        _filterImportPending = { name, tree };
        document.getElementById('filter-import-rename-msg').textContent =
            `A filter named "${name}" already exists. Enter a new name:`;
        const inp = document.getElementById('filter-import-new-name');
        inp.value = '';
        document.getElementById('filter-import-rename').style.display = '';
        status.textContent = ''; status.className = 'tool-status';
        setTimeout(() => inp.focus(), 50);
    } else {
        _saveImportedFilter(name, tree);
    }
}

async function confirmFilterImport() {
    if (!_filterImportPending) return;
    const newName = document.getElementById('filter-import-new-name').value.trim();
    if (!newName) { document.getElementById('filter-import-new-name').focus(); return; }
    if ((typeof _savedFilters !== 'undefined' ? _savedFilters : {})[newName]) {
        document.getElementById('filter-import-rename-msg').textContent =
            `"${newName}" also already exists. Try another name:`;
        return;
    }
    const { tree } = _filterImportPending;
    document.getElementById('filter-import-rename').style.display = 'none';
    _filterImportPending = null;
    _saveImportedFilter(newName, tree);
}

function cancelFilterImport() {
    document.getElementById('filter-import-rename').style.display = 'none';
    _filterImportPending = null;
    const status = document.getElementById('filter-import-status');
    status.textContent = 'Import cancelled.'; status.className = 'tool-status';
}

async function _saveImportedFilter(name, tree) {
    const status = document.getElementById('filter-import-status');
    status.textContent = 'Saving…'; status.className = 'tool-status info';
    try {
        const res  = await fetch('/api/save-filter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, filter_tree: tree })
        });
        const data = await res.json();
        if (data.status === 'success') {
            if (typeof _savedFilters !== 'undefined') _savedFilters[name] = {id: null, tree};
            _populateFilterExportSelect();
            const filterSel = document.getElementById('saved-filters-select');
            if (filterSel && filterSel._addOption) filterSel._addOption(name, name);
            status.textContent = `✔ Imported "${name}".`;
            status.className   = 'tool-status success';
        } else {
            status.textContent = data.message || 'Save failed.';
            status.className   = 'tool-status error';
        }
    } catch (e) {
        status.textContent = `Error: ${e.message}`;
        status.className   = 'tool-status error';
    }
}
