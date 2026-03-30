// ==UserScript==
// @name         PlayDate Date Importer
// @namespace    playdate
// @version      1.8
// @description  Sends the earliest game activation date from a Steam help page to PlayDate's edit modal
// @match        https://help.steampowered.com/*
// @include      https://help.steampowered.com/*
// @grant        GM_xmlhttpRequest
// @connect      localhost
// ==/UserScript==

(function () {
    'use strict';

    // ── Only run on HelpWithGame pages opened by PlayDate ─────────────────────
    if (!window.location.pathname.includes('HelpWithGame')) return;

    const params  = new URLSearchParams(window.location.search);
    if (params.get('ref') !== 'playdate') return;

    const appid = parseInt(params.get('appid'));
    if (!appid) return;

    const isBulk = params.get('bulk') === '1';

    // ── Parse a date string like "Oct 1, 2017" or "Mar 25" → "2017-10-01" ────
    function parseDate(str) {
        str = str.trim();
        // If no 4-digit year present, append the current year
        if (!/\d{4}/.test(str)) str = `${str}, ${new Date().getFullYear()}`;
        const d = new Date(str);
        if (isNaN(d.getTime())) return null;
        const yyyy = d.getFullYear();
        const mm   = String(d.getMonth() + 1).padStart(2, '0');
        const dd   = String(d.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    // ── Find the earliest date ────────────────────────────────────────────────
    function findEarliestDate() {
        const dates = [];

        // Primary: .LineItemRow spans — "Oct 1, 2017 - Activated as part of: ..."
        document.querySelectorAll('.LineItemRow span:first-child').forEach(el => {
            const text = el.textContent.replace(/\u00a0/g, ' ').split('-')[0].trim();
            const parsed = parseDate(text);
            if (parsed) dates.push(parsed);
        });

        // Fallback: "Activated: Oct 1, 2017" in .account_details
        if (dates.length === 0) {
            document.querySelectorAll('.account_details .help_highlight_text').forEach(el => {
                if (el.textContent.trim() === 'Activated:') {
                    const val = el.nextElementSibling;
                    if (val) {
                        const parsed = parseDate(val.textContent);
                        if (parsed) dates.push(parsed);
                    }
                }
            });
        }

        if (dates.length === 0) return null;
        return dates.sort()[0]; // earliest
    }

    // ── Navigate to the next bulk game or close ───────────────────────────────
    function handleBulkNext(res) {
        let data;
        try { data = JSON.parse(res.responseText); } catch (e) { data = {}; }
        if (data.next_appid) {
            setTimeout(() => {
                window.location.href =
                    `https://help.steampowered.com/en/wizard/HelpWithGame/?appid=${data.next_appid}&ref=playdate&bulk=1`;
            }, 500);
        } else {
            showBanner('All done — closing.', '#1a7f4b');
            setTimeout(() => window.close(), 1500);
        }
    }

    // ── Single-game: poll peek endpoint until modal consumes date, then close ─
    function waitForConsumptionThenClose() {
        let checks = 0;
        const maxChecks = 40; // 10 seconds at 250ms
        const poll = setInterval(() => {
            GM_xmlhttpRequest({
                method: 'GET',
                url: `http://localhost:5000/api/pending-date/${appid}/peek`,
                onload: function (res) {
                    let data;
                    try { data = JSON.parse(res.responseText); } catch (e) { data = {}; }
                    if (!data.pending || ++checks >= maxChecks) {
                        clearInterval(poll);
                        window.close();
                    }
                },
                onerror: function () { clearInterval(poll); window.close(); }
            });
        }, 250);
    }

    // ── Send date to PlayDate ─────────────────────────────────────────────────
    function sendDate(date) {
        if (isBulk) {
            GM_xmlhttpRequest({
                method:  'POST',
                url:     'http://localhost:5000/api/bulk-date-import/submit',
                headers: { 'Content-Type': 'application/json' },
                data:    JSON.stringify({ appid, date }),
                onload:  handleBulkNext,
                onerror: function () { showBanner('Could not reach PlayDate.', '#c97c00'); }
            });
        } else {
            GM_xmlhttpRequest({
                method:  'POST',
                url:     'http://localhost:5000/api/pending-date',
                headers: { 'Content-Type': 'application/json' },
                data:    JSON.stringify({ appid, date }),
                onload: function (res) {
                    if (res.status === 200) {
                        showBanner(`Date sent: ${date} — waiting for PlayDate…`, '#1a7f4b');
                        waitForConsumptionThenClose();
                    } else {
                        showBanner(`PlayDate error: ${res.responseText}`, '#c97c00');
                    }
                },
                onerror: function () { showBanner('Could not reach PlayDate. Make sure it is running.', '#c97c00'); }
            });
        }
    }

    // ── Skip this game (bulk mode only) ──────────────────────────────────────
    function skipGame() {
        GM_xmlhttpRequest({
            method:  'POST',
            url:     'http://localhost:5000/api/bulk-date-import/skip',
            headers: { 'Content-Type': 'application/json' },
            data:    JSON.stringify({ appid }),
            onload:  handleBulkNext,
            onerror: function () { showBanner('Could not reach PlayDate.', '#c97c00'); }
        });
    }

    // ── Inject a small banner into the page ──────────────────────────────────
    function showBanner(msg, color) {
        const existing = document.getElementById('pd-banner');
        if (existing) existing.remove();
        const banner = document.createElement('div');
        banner.id = 'pd-banner';
        banner.textContent = msg;
        Object.assign(banner.style, {
            position:   'fixed', bottom: '20px', right: '20px',
            background: '#1a2332', border: `1px solid ${color}`,
            color: '#c7d5e0', padding: '10px 16px', borderRadius: '8px',
            fontSize: '0.88rem', zIndex: '99999', maxWidth: '340px',
            boxShadow: '0 4px 16px rgba(0,0,0,0.5)'
        });
        document.body.appendChild(banner);
        setTimeout(() => banner.remove(), 6000);
    }

    // ── Wait for dynamic content, then auto-send ─────────────────────────────
    let _attempts = 0;
    function tryRun() {
        _attempts++;
        const date = findEarliestDate();
        if (date) {
            sendDate(date);
            return;
        }
        if (_attempts < 20) {
            setTimeout(tryRun, 500);
        } else {
            if (isBulk) {
                skipGame();
            } else {
                showBanner('No activation date found on this page.', '#c97c00');
            }
        }
    }
    tryRun();

})();
