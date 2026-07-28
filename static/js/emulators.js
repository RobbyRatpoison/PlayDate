// ── Emulators modal ──────────────────────────────────────────────────────────

function openEmulatorsModal() {
    document.getElementById('emulators-modal').style.display = 'flex';
    _emuRender();
}
function closeEmulatorsModal() {
    document.getElementById('emulators-modal').style.display = 'none';
    _emuStopScanPoll();
}

var _emuScanPollIv = null;

function _emuStopScanPoll() {
    if (_emuScanPollIv) { clearInterval(_emuScanPollIv); _emuScanPollIv = null; }
}

function _emuRender(expandId) {
    var body = document.getElementById('emu-list-body');
    body.innerHTML = '<div style="color:var(--text-secondary);font-size:0.85rem;padding:8px 0;">Loading…</div>';
    fetch('/api/emulators')
        .then(function(r) { return r.json(); })
        .then(function(emulators) {
            if (!emulators.length) {
                body.innerHTML = '<div style="color:var(--text-secondary);font-size:0.85rem;padding:8px 0;">No emulators configured. Click <strong>+ Add Emulator</strong> to get started.</div>';
                return;
            }
            body.innerHTML = emulators.map(function(e) { return _emuCardHtml(e, e.id === expandId); }).join('');
        })
        .catch(function(err) {
            body.innerHTML = '<div style="color:#c74747;font-size:0.85rem;">Failed to load: ' + escHtml(err.message) + '</div>';
        });
}

function _emuFlatpakWarnHtml(w) {
    return '<div style="margin-top:4px;padding:5px 8px;background:rgba(210,140,0,0.12);border:1px solid rgba(210,140,0,0.35);border-radius:3px;font-size:0.75rem;color:#c9920a;">'
        + '<strong>Flatpak permission needed</strong> — ' + escHtml(w.message) + '<br>'
        + 'Run: <code style="font-size:0.72rem;background:rgba(0,0,0,0.2);padding:1px 4px;border-radius:2px;user-select:all;">' + escHtml(w.fix) + '</code>'
        + '</div>';
}

function _emuCardHtml(e, expanded) {
    var warnMap = {};
    (e.flatpak_warnings || []).forEach(function(w) { warnMap[w.platform] = w; });

    var platRows = Object.entries(e.platforms).map(function(kv) {
        var pid = kv[0], info = kv[1];
        var dirs = (info.dirs && info.dirs.length) ? info.dirs : [''];
        var multi = dirs.length > 1;
        var dirRowsHtml = dirs.map(function(dir) {
            return '<div style="display:flex;align-items:center;gap:6px;">'
                + '<input type="text" value="' + escHtml(dir) + '" placeholder="ROM folder…"'
                + ' style="flex:1;font-size:0.78rem;padding:3px 6px;background:var(--bg-primary);border:1px solid var(--border);border-radius:3px;color:var(--text-primary);"'
                + ' onchange="_emuSavePlatformDirs(\'' + escHtml(e.id) + '\',\'' + escHtml(pid) + '\')">'
                + '<button class="nav-btn" style="font-size:0.75rem;padding:2px 8px;" onclick="_emuBrowseDir(\'' + escHtml(e.id) + '\',\'' + escHtml(pid) + '\',this)">Browse</button>'
                + '<button class="nav-btn emu-dir-remove" style="font-size:0.75rem;padding:2px 6px;' + (multi ? '' : 'display:none;') + '" onclick="_emuRemoveDirRow(this,\'' + escHtml(e.id) + '\',\'' + escHtml(pid) + '\')">&#8722;</button>'
                + '</div>';
        }).join('');
        var coreRow = '';
        if (e.has_cores) {
            var corePath = info.core || '';
            coreRow = '<div style="display:flex;align-items:center;gap:6px;margin-top:4px;">'
                + '<span style="font-size:0.75rem;color:var(--text-secondary);width:130px;flex-shrink:0;padding-left:12px;">Core</span>'
                + '<input type="text" id="emu-core-' + escHtml(e.id) + '-' + escHtml(pid) + '" value="' + escHtml(corePath) + '" placeholder="Core (.so) path…"'
                + ' style="flex:1;font-size:0.78rem;padding:3px 6px;background:var(--bg-primary);border:1px solid var(--border);border-radius:3px;color:var(--text-primary);"'
                + ' onchange="_emuSetCore(\'' + escHtml(e.id) + '\',\'' + escHtml(pid) + '\',this.value)">'
                + '<button class="nav-btn" style="font-size:0.75rem;padding:2px 8px;" onclick="_emuDetectCore(\'' + escHtml(e.id) + '\',\'' + escHtml(pid) + '\',this)">Detect</button>'
                + '</div>';
        }
        var warnHtml = warnMap[pid] ? _emuFlatpakWarnHtml(warnMap[pid]) : '';
        return '<div style="margin-top:8px;">'
            + '<div style="display:flex;align-items:flex-start;gap:6px;">'
            + '<span style="font-size:0.8rem;color:var(--text-secondary);width:130px;flex-shrink:0;padding-top:4px;">' + escHtml(info.label) + ' games</span>'
            + '<div style="flex:1;display:flex;flex-direction:column;gap:4px;" id="emu-dirs-' + escHtml(e.id) + '-' + escHtml(pid) + '">'
            + dirRowsHtml
            + '<button class="nav-btn" style="font-size:0.73rem;padding:1px 6px;align-self:flex-start;" onclick="_emuAddDirRow(\'' + escHtml(e.id) + '\',\'' + escHtml(pid) + '\')">+ Add folder</button>'
            + '</div>'
            + '<button class="nav-btn" style="font-size:0.75rem;padding:2px 8px;margin-top:2px;" onclick="_emuScan(\'' + escHtml(e.id) + '\',\'' + escHtml(pid) + '\')">Scan</button>'
            + '</div>'
            + '<div id="emu-flatpak-warn-' + escHtml(e.id) + '-' + escHtml(pid) + '">' + warnHtml + '</div>'
            + coreRow
            + '</div>';
    }).join('');

    var bodyDisplay = expanded ? 'block' : 'none';
    var chevron = expanded ? '&#9650;' : '&#9660;';
    return '<div class="hub-section" id="emu-card-' + escHtml(e.id) + '" style="padding:0;border:1px solid var(--border);border-radius:6px;background:var(--bg-surface);">'
        + '<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;cursor:pointer;border-radius:6px;" onmouseenter="this.style.background=\'var(--hover-bg)\'" onmouseleave="this.style.background=\'\'" onclick="_emuToggleCard(\'' + escHtml(e.id) + '\')">'
        + '<div style="display:flex;align-items:center;gap:8px;">'
        + '<span id="emu-chevron-' + escHtml(e.id) + '" style="font-size:0.6rem;color:var(--text-secondary);">' + chevron + '</span>'
        + '<span style="font-size:0.95rem;font-weight:600;color:var(--text-primary);">' + escHtml(e.name) + '</span>'
        + '</div>'
        + '<button class="nav-btn" style="font-size:0.75rem;background:rgba(199,71,71,0.15);border-color:rgba(199,71,71,0.4);color:#c74747;" onclick="event.stopPropagation();_emuRemove(\'' + escHtml(e.id) + '\')">Remove</button>'
        + '</div>'
        + '<div id="emu-body-' + escHtml(e.id) + '" style="display:' + bodyDisplay + ';padding:10px 12px 12px;border-top:1px solid var(--border);">'
        + '<div style="display:flex;align-items:center;gap:6px;">'
        + '<span style="font-size:0.8rem;color:var(--text-secondary);width:130px;flex-shrink:0;">Emulator</span>'
        + '<input type="text" id="emu-binary-' + escHtml(e.id) + '" value="' + escHtml(e.binary) + '" placeholder="Path to emulator binary…"'
        + ' style="flex:1;font-size:0.78rem;padding:3px 6px;background:var(--bg-primary);border:1px solid var(--border);border-radius:3px;color:var(--text-primary);"'
        + ' onchange="_emuSetBinary(\'' + escHtml(e.id) + '\',this.value)">'
        + (!e.custom ? '<button class="nav-btn" style="font-size:0.75rem;padding:2px 8px;" onclick="_emuDetect(\'' + escHtml(e.id) + '\')">Auto-detect</button>' : '')
        + '</div>'
        + platRows
        + '</div>'
        + '</div>';
}

function _emuToggleCard(id) {
    var body    = document.getElementById('emu-body-' + id);
    var chevron = document.getElementById('emu-chevron-' + id);
    if (!body) return;
    var open = body.style.display === 'none';
    body.style.display    = open ? 'block' : 'none';
    chevron.innerHTML     = open ? '&#9650;' : '&#9660;';
}

var _emuByPlatform = null;

function _emuToggleAddPanel() {
    var panel = document.getElementById('emu-add-panel');
    if (panel.style.display !== 'none') { _emuCloseAddPanel(); return; }
    document.getElementById('emu-custom-form').style.display = 'none';
    panel.style.display = 'block';
    _emuShowStep1();
    if (_emuByPlatform) { _emuRenderPlatformGrid(); return; }
    fetch('/api/emulators/by-platform')
        .then(function(r) { return r.json(); })
        .then(function(data) { _emuByPlatform = data; _emuRenderPlatformGrid(); });
}

function _emuCloseAddPanel() {
    document.getElementById('emu-add-panel').style.display = 'none';
    _emuShowStep1();
}

function _emuShowStep1() {
    document.getElementById('emu-add-step1').style.display = 'block';
    document.getElementById('emu-add-step2').style.display = 'none';
}

function _emuRenderPlatformGrid() {
    var grid = document.getElementById('emu-platform-grid');
    var btnBase = 'padding:4px 10px;font-size:0.78rem;cursor:pointer;border:1px solid var(--border);border-radius:4px;background:var(--bg-surface);color:var(--text-primary);';
    grid.innerHTML = (_emuByPlatform || []).map(function(p) {
        return '<button style="' + btnBase + '" onclick="_emuSelectPlatform(\'' + escHtml(p.id) + '\')">'
            + escHtml(p.label) + '</button>';
    }).join('')
    + '<button style="' + btnBase + 'color:var(--text-secondary);" onclick="_emuShowCustomForm(\'\',\'\')">'
    + 'Other…</button>';
}

function _emuSelectPlatform(platId) {
    var plat = (_emuByPlatform || []).find(function(p) { return p.id === platId; });
    if (!plat) return;
    document.getElementById('emu-add-step1').style.display = 'none';
    document.getElementById('emu-add-step2').style.display = 'block';
    document.getElementById('emu-add-plat-label').textContent = plat.label;
    var rowStyle = 'display:flex;align-items:center;justify-content:space-between;padding:7px 10px;background:var(--bg-surface);border-radius:4px;';
    document.getElementById('emu-emulator-list').innerHTML = plat.emulators.map(function(e) {
        return '<div style="' + rowStyle + '">'
            + '<span style="font-size:0.85rem;color:var(--text-primary);">' + escHtml(e.name) + '</span>'
            + (e.added
                ? '<span style="font-size:0.75rem;color:var(--text-secondary);">Already added</span>'
                : '<button class="nav-btn" style="font-size:0.75rem;padding:2px 10px;" onclick="_emuAdd(\'' + escHtml(e.id) + '\')">Add</button>')
            + '</div>';
    }).join('')
    + '<div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border);text-align:right;">'
    + '<button class="nav-btn" style="font-size:0.75rem;color:var(--text-secondary);" '
    + 'onclick="_emuShowCustomForm(\'' + escHtml(platId) + '\',\'' + escHtml(plat.label) + '\')">Custom emulator for ' + escHtml(plat.label) + '…</button>'
    + '</div>';
}

function _emuAddBack() {
    _emuShowStep1();
}

function _emuShowCustomForm(platId, platLabel) {
    document.getElementById('emu-add-panel').style.display = 'none';
    document.getElementById('emu-custom-form').style.display = 'block';
    var platInput = document.getElementById('emu-custom-platform');
    platInput.value = platId || '';
    platInput.readOnly = !!platId;
    platInput.style.opacity = platId ? '0.6' : '';
    document.getElementById('emu-custom-name').focus();
}

function _emuHideCustomForm() {
    document.getElementById('emu-custom-form').style.display = 'none';
    document.getElementById('emu-custom-platform').readOnly = false;
    document.getElementById('emu-custom-platform').style.opacity = '';
    document.getElementById('emu-custom-name').value = '';
    document.getElementById('emu-custom-binary').value = '';
    document.getElementById('emu-custom-args').value = '{rom}';
}

function _emuCustomBrowseBinary() {
    if (_fileDlgBusy) return;
    _fileDlgBusy = true;
    setTimeout(function() { _fileDlgBusy = false; }, 300);
    if (window.pywebview) {
        window.pywebview.api.pick_open_path([]).then(function(path) {
            if (path) document.getElementById('emu-custom-binary').value = path;
        });
    }
}

function _emuSubmitCustom() {
    var name     = document.getElementById('emu-custom-name').value.trim();
    var platform = document.getElementById('emu-custom-platform').value.trim();
    var binary   = document.getElementById('emu-custom-binary').value.trim();
    var argsRaw  = document.getElementById('emu-custom-args').value.trim();
    var args     = argsRaw ? argsRaw.match(/(?:[^\s"]+|"[^"]*")+/g) : ['{rom}'];
    if (!name)     { alert('Please enter a name.');     return; }
    if (!platform) { alert('Please enter a platform.'); return; }
    fetch('/api/emulators/add-custom', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name, platform: platform, binary: binary, args: args}),
    })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.error) { alert(d.error); return; }
            _emuByPlatform = null;
            _emuHideCustomForm();
            _emuRender(d.entry && d.entry.id);
        });
}

function _emuAdd(id) {
    fetch('/api/emulators/add', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: id})})
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.error) { alert(d.error); return; }
            _emuByPlatform = null;
            _emuCloseAddPanel();
            _emuRender(id);
        });
}

function _emuRemove(id) {
    confirm('Remove this emulator from PlayDate? (Your games will stay in the library.)').then(function(ok) {
        if (!ok) return;
        fetch('/api/emulators/remove', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: id})})
            .then(function() { _emuRender(); });
    });
}

function _emuSetBinary(id, value) {
    fetch('/api/emulators/update', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({id: id, binary: value})})
        .then(function(r) { return r.json(); })
        .then(function(d) { _emuApplyFlatpakWarnings(id, d.flatpak_warnings || []); });
}

function _emuDetect(id) {
    fetch('/api/emulators/detect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: id})})
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var inp = document.getElementById('emu-binary-' + id);
            if (inp) inp.value = d.path || '';
            if (!d.path) alert('Could not auto-detect binary — enter the path manually.');
        });
}

function _emuApplyFlatpakWarnings(emuId, warnings) {
    var card = document.getElementById('emu-card-' + emuId);
    if (!card) return;
    card.querySelectorAll('[id^="emu-flatpak-warn-' + emuId + '-"]').forEach(function(el) { el.innerHTML = ''; });
    warnings.forEach(function(w) {
        var el = document.getElementById('emu-flatpak-warn-' + emuId + '-' + w.platform);
        if (el) el.innerHTML = _emuFlatpakWarnHtml(w);
    });
}

function _emuSavePlatformDirs(emuId, platformId) {
    var container = document.getElementById('emu-dirs-' + emuId + '-' + platformId);
    if (!container) return;
    var dirs = Array.from(container.querySelectorAll('div > input[type=text]'))
        .map(function(i) { return i.value.trim(); }).filter(Boolean);
    var payload = {}; payload[platformId] = dirs;
    fetch('/api/emulators/update', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({id: emuId, platform_dirs: payload})})
        .then(function(r) { return r.json(); })
        .then(function(d) { _emuApplyFlatpakWarnings(emuId, d.flatpak_warnings || []); });
}

function _emuAddDirRow(emuId, platformId) {
    var container = document.getElementById('emu-dirs-' + emuId + '-' + platformId);
    if (!container) return;
    container.querySelectorAll('.emu-dir-remove').forEach(function(b) { b.style.display = ''; });
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:6px;';
    row.innerHTML = '<input type="text" value="" placeholder="ROM folder…"'
        + ' style="flex:1;font-size:0.78rem;padding:3px 6px;background:var(--bg-primary);border:1px solid var(--border);border-radius:3px;color:var(--text-primary);"'
        + ' onchange="_emuSavePlatformDirs(\'' + escHtml(emuId) + '\',\'' + escHtml(platformId) + '\')">'
        + '<button class="nav-btn" style="font-size:0.75rem;padding:2px 8px;" onclick="_emuBrowseDir(\'' + escHtml(emuId) + '\',\'' + escHtml(platformId) + '\',this)">Browse</button>'
        + '<button class="nav-btn emu-dir-remove" style="font-size:0.75rem;padding:2px 6px;" onclick="_emuRemoveDirRow(this,\'' + escHtml(emuId) + '\',\'' + escHtml(platformId) + '\')">&#8722;</button>';
    var addBtn = container.querySelector(':scope > button');
    container.insertBefore(row, addBtn);
}

function _emuRemoveDirRow(btn, emuId, platformId) {
    var container = document.getElementById('emu-dirs-' + emuId + '-' + platformId);
    if (!container) return;
    btn.closest('div').remove();
    var removeButtons = container.querySelectorAll('.emu-dir-remove');
    if (removeButtons.length === 1) removeButtons[0].style.display = 'none';
    _emuSavePlatformDirs(emuId, platformId);
}

function _emuSetCore(emuId, platformId, value) {
    var cores = {}; cores[platformId] = value;
    fetch('/api/emulators/update', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({id: emuId, cores: cores})});
}

function _emuDetectCore(emuId, platformId, btn) {
    btn.disabled = true;
    btn.textContent = '…';
    fetch('/api/emulators/retroarch-cores', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({platform: platformId})})
        .then(function(r) { return r.json(); })
        .then(function(cores) {
            btn.disabled = false;
            btn.textContent = 'Detect';
            if (!cores.length) {
                alert('No cores found for this platform. Install the core via RetroArch\'s online updater and try again.');
                return;
            }
            var inp = document.getElementById('emu-core-' + emuId + '-' + platformId);
            if (cores.length === 1) {
                if (inp) inp.value = cores[0].path;
                _emuSetCore(emuId, platformId, cores[0].path);
                return;
            }
            // Multiple candidates — show a small inline picker
            var existing = document.getElementById('emu-core-picker-' + emuId + '-' + platformId);
            if (existing) { existing.remove(); return; }
            var picker = document.createElement('div');
            picker.id = 'emu-core-picker-' + emuId + '-' + platformId;
            picker.style.cssText = 'position:absolute;z-index:200;background:var(--bg-secondary);border:1px solid var(--border);border-radius:4px;min-width:260px;box-shadow:0 4px 12px rgba(0,0,0,0.4);margin-top:2px;';
            cores.forEach(function(c) {
                var item = document.createElement('div');
                item.style.cssText = 'padding:7px 12px;cursor:pointer;font-size:0.82rem;color:var(--text-primary);';
                item.textContent = c.name;
                item.onmouseenter = function() { this.style.background = 'var(--hover-bg)'; };
                item.onmouseleave = function() { this.style.background = ''; };
                item.onclick = function() {
                    if (inp) inp.value = c.path;
                    _emuSetCore(emuId, platformId, c.path);
                    picker.remove();
                };
                picker.appendChild(item);
            });
            btn.parentNode.style.position = 'relative';
            btn.parentNode.appendChild(picker);
            document.addEventListener('click', function _cp(ev) {
                if (!picker.contains(ev.target) && ev.target !== btn) {
                    picker.remove();
                    document.removeEventListener('click', _cp);
                }
            });
        })
        .catch(function() {
            btn.disabled = false;
            btn.textContent = 'Detect';
        });
}

function _emuBrowseDir(emuId, platformId, btn) {
    if (_fileDlgBusy) return;
    _fileDlgBusy = true;
    setTimeout(function() { _fileDlgBusy = false; }, 300);
    if (window.pywebview) {
        window.pywebview.api.pick_folder().then(function(path) {
            if (!path) return;
            var row = btn.closest('div');
            var inp = row.querySelector('input[type=text]');
            if (inp) { inp.value = path; _emuSavePlatformDirs(emuId, platformId); }
        });
    }
}

function _emuScan(emuId, platformId) {
    var statusEl = document.getElementById('emu-scan-status');
    if (statusEl) statusEl.textContent = 'Starting scan…';
    fetch('/api/emulators/scan', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({id: emuId, platform: platformId})})
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.status === 'already_running') {
                if (statusEl) statusEl.textContent = 'Scan already running.';
                return;
            }
            _emuPollScan(statusEl);
        });
}

function _emuScanAll() {
    var statusEl = document.getElementById('emu-scan-status');
    if (statusEl) statusEl.textContent = 'Starting scan…';
    fetch('/api/emulators/scan-all', {method:'POST'})
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.status === 'already_running') {
                if (statusEl) statusEl.textContent = 'Scan already running.';
                return;
            }
            _emuPollScan(statusEl);
        });
}

function _emuPollScan(statusEl) {
    _emuStopScanPoll();
    _emuScanPollIv = setInterval(function() {
        fetch('/api/emulators/scan-status')
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (statusEl) {
                    if (d.error) statusEl.textContent = 'Error: ' + d.error;
                    else statusEl.textContent = d.status || '';
                }
                if (!d.running) {
                    clearInterval(_emuScanPollIv);
                    _emuScanPollIv = null;
                }
            })
            .catch(function() { clearInterval(_emuScanPollIv); _emuScanPollIv = null; });
    }, 1500);
}

// ── Store name review ─────────────────────────────────────────────────────────

var _storeNameItems = [];

function openStoreNamesModal() {
    fetch('/api/store-names-pending')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            _storeNameItems = data.items || [];
            _renderStoreNamesList();
            document.getElementById('store-names-modal').style.display = 'flex';
        })
        .catch(function() {});
}

function closeStoreNamesModal() {
    document.getElementById('store-names-modal').style.display = 'none';
}

function _renderStoreNamesList() {
    var list = document.getElementById('store-names-list');
    if (!_storeNameItems.length) {
        list.innerHTML = '<div style="color:var(--text-secondary);font-size:0.9rem;padding:8px 0;">No pending name changes.</div>';
        return;
    }
    var html = '';
    for (var i = 0; i < _storeNameItems.length; i++) {
        var item = _storeNameItems[i];
        html += '<div class="sn-row" data-idx="' + i + '" onclick="var cb=this.querySelector(\'.sn-cb\');cb.checked=!cb.checked;" style="display:flex;align-items:flex-start;gap:10px;padding:7px 4px;border-bottom:1px solid var(--border-color,#2a3f55);cursor:pointer;">';
        html += '<input type="checkbox" class="sn-cb" style="width:auto;margin:2px 0 0;flex-shrink:0;" onclick="event.stopPropagation()">';
        html += '<div style="min-width:0;">';
        html += '<div style="color:var(--text-secondary);font-size:0.78rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + escHtml(item.old_name) + '">' + escHtml(item.old_name) + '</div>';
        html += '<div style="color:var(--text-primary);font-size:0.88rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + escHtml(item.new_name) + '">→ ' + escHtml(item.new_name) + '</div>';
        html += '</div></div>';
    }
    list.innerHTML = html;
}

function storeNamesSelectAll(checked) {
    var cbs = document.querySelectorAll('#store-names-list .sn-cb');
    for (var i = 0; i < cbs.length; i++) cbs[i].checked = checked;
}

function applyStoreNames() {
    var cbs = document.querySelectorAll('#store-names-list .sn-cb');
    var appids = [];
    for (var i = 0; i < cbs.length; i++) {
        if (cbs[i].checked && _storeNameItems[i]) appids.push(_storeNameItems[i].appid);
    }
    var btn = document.getElementById('store-names-apply-btn');
    btn.disabled = true;
    btn.textContent = 'Applying…';
    fetch('/api/store-names-apply', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({appids: appids})
    }).then(function(r) { return r.json(); })
    .then(function(data) {
        btn.disabled = false;
        btn.textContent = 'Apply Selected';
        if (data.remaining > 0) {
            var appliedSet = new Set(appids);
            _storeNameItems = _storeNameItems.filter(function(it) { return !appliedSet.has(it.appid); });
            _renderStoreNamesList();
            var n = _storeNameItems.length;
            document.getElementById('store-names-btn-label').textContent =
                n + ' game name' + (n === 1 ? '' : 's') + ' differ from Steam store';
        } else {
            _clearStoreNamesNotification();
            closeStoreNamesModal();
        }
    }).catch(function() {
        btn.disabled = false;
        btn.textContent = 'Apply Selected';
    });
}

function dismissStoreNames() {
    fetch('/api/store-names-apply', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({appids: [], dismiss: true})
    }).then(function() {
        _clearStoreNamesNotification();
        closeStoreNamesModal();
    }).catch(function() { closeStoreNamesModal(); });
}

function _clearStoreNamesNotification() {
    document.getElementById('store-names-btn').style.display = 'none';
    document.getElementById('store-names-dot').classList.remove('visible');
}
