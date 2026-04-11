// ==UserScript==
// @name         PlayDate Date Importer
// @namespace    playdate
// @version      2.0
// @description  Imports Steam activation dates into PlayDate — bulk mode fetches pages in the background without tab switching
// @match        https://help.steampowered.com/*
// @updateURL    https://raw.githubusercontent.com/RobbyRatpoison/PlayDate/main/steam_date_import.user.js
// @downloadURL  https://raw.githubusercontent.com/RobbyRatpoison/PlayDate/main/steam_date_import.user.js
// @license      MIT
// @grant        GM_xmlhttpRequest
// @connect      localhost
// ==/UserScript==

(function () {
    'use strict';

    const params = new URLSearchParams(window.location.search);
    if (params.get('ref') !== 'playdate') return;

    const PLAYDATE = 'http://localhost:5000';
    const isBulk   = params.get('bulk') === '1';

    // GM_xmlhttpRequest bypasses the page's Content Security Policy, which
    // blocks fetch() to localhost.  Use this for all PlayDate API calls.
    // fetch() is still used for same-origin Steam Help page requests.
    function pdFetch(method, path, body) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method,
                url: PLAYDATE + path,
                headers: { 'Content-Type': 'application/json' },
                data: body !== undefined ? JSON.stringify(body) : undefined,
                onload:   resolve,
                onerror:  reject,
                ontimeout: reject,
            });
        });
    }

    // ── Parse "Oct 1, 2017" or "Mar 25" → "2017-10-01" ──────────────────────
    function parseDate(str) {
        str = str.trim();
        if (!/\d{4}/.test(str)) str = `${str}, ${new Date().getFullYear()}`;
        const d = new Date(str);
        if (isNaN(d.getTime())) return null;
        return [
            d.getFullYear(),
            String(d.getMonth() + 1).padStart(2, '0'),
            String(d.getDate()).padStart(2, '0'),
        ].join('-');
    }

    // ── Find earliest activation date in a DOM document ───────────────────────
    function parseDateFromDoc(doc) {
        const dates = [];
        doc.querySelectorAll('.LineItemRow span:first-child').forEach(el => {
            const text   = el.textContent.replace(/\u00a0/g, ' ').split('-')[0].trim();
            const parsed = parseDate(text);
            if (parsed) dates.push(parsed);
        });
        if (dates.length === 0) {
            doc.querySelectorAll('.account_details .help_highlight_text').forEach(el => {
                if (el.textContent.trim() === 'Activated:') {
                    const val = el.nextElementSibling;
                    if (val) {
                        const parsed = parseDate(val.textContent);
                        if (parsed) dates.push(parsed);
                    }
                }
            });
        }
        return dates.length ? dates.sort()[0] : null;
    }

    // ── Small status banner (single-game mode) ────────────────────────────────
    function showBanner(msg, color) {
        const existing = document.getElementById('pd-banner');
        if (existing) existing.remove();
        const banner = document.createElement('div');
        banner.id = 'pd-banner';
        banner.textContent = msg;
        Object.assign(banner.style, {
            position: 'fixed', bottom: '20px', right: '20px',
            background: '#1a2332', border: `1px solid ${color}`,
            color: '#c7d5e0', padding: '10px 16px', borderRadius: '8px',
            fontSize: '0.88rem', zIndex: '99999', maxWidth: '340px',
            boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
        });
        document.body.appendChild(banner);
        setTimeout(() => banner.remove(), 6000);
    }

    // =========================================================================
    // Single-game mode (edit modal ↗ link)
    // =========================================================================
    if (!isBulk) {
        if (!window.location.pathname.includes('HelpWithGame')) return;
        const appid = parseInt(params.get('appid'));
        if (!appid) return;

        async function checkAccountThenRun() {
            let pageSteamId = null;
            try {
                if (window.HelpWizard && window.HelpWizard.m_steamid)
                    pageSteamId = String(window.HelpWizard.m_steamid);
            } catch (e) {}

            if (pageSteamId) {
                try {
                    const r = await pdFetch('GET', '/api/active-steam-id');
                    const d = JSON.parse(r.responseText);
                    if (d.steam_id && String(d.steam_id) !== pageSteamId) {
                        showBanner(
                            `Account mismatch — Steam is logged in as ${pageSteamId} but PlayDate is configured for ${d.steam_id}. Import aborted.`,
                            '#c97c00'
                        );
                        return;
                    }
                } catch (e) { /* PlayDate unreachable — proceed */ }
            }
            tryRun();
        }

        let _attempts = 0;
        function tryRun() {
            _attempts++;
            const date = parseDateFromDoc(document);
            if (date) { sendSingleDate(date); return; }
            if (_attempts < 20) setTimeout(tryRun, 500);
            else showBanner('No activation date found on this page.', '#c97c00');
        }

        async function sendSingleDate(date) {
            try {
                const res = await pdFetch('POST', '/api/pending-date', { appid, date });
                if (res.status === 200) {
                    showBanner(`Date sent: ${date}`, '#1a7f4b');
                } else {
                    showBanner(`PlayDate error: ${res.status}`, '#c97c00');
                }
            } catch (e) {
                showBanner('Could not reach PlayDate. Make sure it is running.', '#c97c00');
            }
        }

        checkAccountThenRun();
        return;
    }

    // =========================================================================
    // Bulk mode — stay on this tab, fetch each game's Help page in the background
    // =========================================================================

    // ── Full-page overlay ─────────────────────────────────────────────────────
    const overlay = document.createElement('div');
    overlay.id = 'pd-bulk-overlay';
    Object.assign(overlay.style, {
        position: 'fixed', inset: '0', background: 'rgba(10,15,25,0.93)',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', zIndex: '99999', color: '#c7d5e0',
        fontFamily: "'Segoe UI', sans-serif", gap: '12px',
    });
    overlay.innerHTML = `
        <div style="font-size:1.05rem;font-weight:600;color:#66c0f4;letter-spacing:0.02em;">
            PlayDate — Importing Dates
        </div>
        <div id="pd-game-name" style="font-size:0.85rem;color:#8f98a0;max-width:420px;text-align:center;">
            Starting…
        </div>
        <div style="width:320px;background:#1a2332;border-radius:4px;height:6px;overflow:hidden;">
            <div id="pd-bar" style="background:#66c0f4;height:100%;width:0%;transition:width 0.35s;"></div>
        </div>
        <div id="pd-label" style="font-size:0.78rem;color:#8f98a0;"></div>
        <div id="pd-hint" style="font-size:0.72rem;color:#3a4a5a;margin-top:6px;">Don't close this tab</div>
    `;
    document.body.appendChild(overlay);

    function setOverlay(gameName, done, total) {
        document.getElementById('pd-game-name').textContent = gameName || '…';
        document.getElementById('pd-bar').style.width = total > 0 ? (done / total * 100) + '%' : '0%';
        document.getElementById('pd-label').textContent = total > 0 ? `${done} / ${total}` : '';
    }

    function finishOverlay(imported, notFound) {
        document.getElementById('pd-game-name').textContent =
            `Done — ${imported} date${imported !== 1 ? 's' : ''} imported, ${notFound} not found`;
        document.getElementById('pd-game-name').style.color = '#66c0f4';
        document.getElementById('pd-bar').style.width = '100%';
        document.getElementById('pd-label').textContent = '';
        const hint = overlay.querySelector('#pd-hint');
        if (hint) hint.remove();
    }

    async function runBulk() {
        // Ping PlayDate to signal the script is alive
        try {
            await pdFetch('POST', '/api/bulk-date-import/ping', {});
        } catch (e) {
            document.getElementById('pd-game-name').textContent =
                'Could not reach PlayDate. Make sure it is running.';
            document.getElementById('pd-game-name').style.color = '#ff4d4d';
            return;
        }

        // Get the initial queue state from PlayDate
        let status;
        try {
            const r = await pdFetch('GET', '/api/bulk-date-import/status');
            status = JSON.parse(r.responseText);
        } catch (e) {
            document.getElementById('pd-game-name').textContent = 'Failed to fetch import state.';
            return;
        }

        const total   = status.total;
        let current   = status.current;           // {appid, name}
        let processed = status.done + status.failed;

        while (current) {
            setOverlay(current.name, processed, total);

            // ── Fetch the Steam Help page for this game ──────────────────────
            let date = null;
            try {
                const pageRes = await fetch(
                    `https://help.steampowered.com/en/wizard/HelpWithGame/?appid=${current.appid}`,
                    { credentials: 'include' }
                );
                const html = await pageRes.text();
                const doc  = new DOMParser().parseFromString(html, 'text/html');
                date = parseDateFromDoc(doc);
            } catch (e) { /* network error — treat as not found */ }

            // ── Report result to PlayDate ────────────────────────────────────
            let next;
            try {
                const endpoint = date ? 'submit' : 'skip';
                const body     = date ? { appid: current.appid, date } : { appid: current.appid };
                const res = await pdFetch('POST', `/api/bulk-date-import/${endpoint}`, body);
                next = JSON.parse(res.responseText);
            } catch (e) { break; }

            processed++;
            current = next.next_appid
                ? { appid: next.next_appid, name: next.next_name }
                : null;

            // Brief pause between requests so we don't hammer Steam
            if (current) await new Promise(r => setTimeout(r, 600));
        }

        // Get final counts from PlayDate and show summary
        try {
            const r = await pdFetch('GET', '/api/bulk-date-import/status');
            const s = JSON.parse(r.responseText);
            finishOverlay(s.done, s.failed);
        } catch (e) {
            finishOverlay(processed, 0);
        }
    }

    runBulk();
})();
