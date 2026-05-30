// ==UserScript==
// @name         PlayDate Date Importer
// @namespace    playdate
// @version      2.7
// @description  Imports Steam activation dates, GOG purchase dates, and EA purchase dates into PlayDate
// @match        https://help.steampowered.com/*
// @match        https://www.gog.com/en/account/settings/orders*
// @match        https://myaccount.ea.com/am/ui/payment-wallet/order-history*
// @updateURL    https://raw.githubusercontent.com/RobbyRatpoison/PlayDate/main/steam_date_import.user.js
// @downloadURL  https://raw.githubusercontent.com/RobbyRatpoison/PlayDate/main/steam_date_import.user.js
// @license      MIT
// @grant        GM_xmlhttpRequest
// @connect      localhost
// ==/UserScript==

(function () {
    'use strict';

    // EA activates by path only — the auth redirect strips ?ref=playdate
    if (window.location.hostname === 'myaccount.ea.com' &&
        window.location.pathname.includes('/payment-wallet/order-history')) {
        runEA();
        return;
    }

    const params = new URLSearchParams(window.location.search);
    if (params.get('ref') !== 'playdate') return;

    // =========================================================================
    // GOG Orders page — scrape purchase dates from all order history pages
    // =========================================================================
    if (window.location.hostname === 'www.gog.com') {
        runGog();
        return;
    }

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

    // =========================================================================
    // GOG — scrape all order history pages and send purchase dates to PlayDate
    // =========================================================================
    async function runGog() {
        // ── Overlay ───────────────────────────────────────────────────────────
        const gogOverlay = document.createElement('div');
        Object.assign(gogOverlay.style, {
            position: 'fixed', inset: '0', background: 'rgba(10,15,25,0.93)',
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', zIndex: '99999', color: '#c7d5e0',
            fontFamily: "'Segoe UI', sans-serif", gap: '12px',
        });
        gogOverlay.innerHTML = `
            <div style="font-size:1.05rem;font-weight:600;color:#66c0f4;letter-spacing:0.02em;">
                PlayDate — Importing GOG Dates
            </div>
            <div id="pd-gog-status" style="font-size:0.85rem;color:#8f98a0;max-width:420px;text-align:center;">
                Reading order history…
            </div>
            <div style="width:320px;background:#1a2332;border-radius:4px;height:6px;overflow:hidden;">
                <div id="pd-gog-bar" style="background:#66c0f4;height:100%;width:0%;transition:width 0.35s;"></div>
            </div>
            <div id="pd-gog-label" style="font-size:0.78rem;color:#8f98a0;"></div>
        `;
        document.body.appendChild(gogOverlay);

        const setStatus = (msg, pct, label) => {
            document.getElementById('pd-gog-status').textContent = msg;
            if (pct !== undefined) document.getElementById('pd-gog-bar').style.width = pct + '%';
            if (label !== undefined) document.getElementById('pd-gog-label').textContent = label;
        };
        const setError = (msg) => {
            const el = document.getElementById('pd-gog-status');
            el.textContent = msg;
            el.style.color = '#ff4d4d';
        };

        // ── Parse gogData JSON from an HTML/script string ─────────────────────
        // gogData ends with "};\nvar " or "};\n</", so }; is unique as a terminator.
        function parseGogData(src) {
            const m = src.match(/var gogData = (\{[\s\S]*?\});\s*(?:var |<\/)/);
            if (!m) return null;
            try { return JSON.parse(m[1]); } catch (e) { return null; }
        }
        function ordersFromData(data) {
            return data && data.ordersLog && data.ordersLog.orders
                ? data.ordersLog.orders
                : null;
        }

        // ── Page 1: parse gogData from inline <script> tags ───────────────────
        let totalPages = 1;
        let gogOrdersData = null;
        const dateMap = {};   // gog_id (string) → earliest Unix timestamp

        function processOrders(orders) {
            for (const order of orders) {
                const ts = order.date;
                if (!ts || order.status === 'refund') continue;
                for (const product of (order.products || [])) {
                    const id = String(product.id);
                    if (!dateMap[id] || ts < dateMap[id]) dateMap[id] = ts;
                }
            }
        }

        try {
            for (const s of document.querySelectorAll('script:not([src])')) {
                const d = parseGogData(s.textContent);
                if (d) { gogOrdersData = ordersFromData(d); break; }
            }
            // Fallback: parse from full page HTML (handles minified/inline cases)
            if (!gogOrdersData) {
                const d = parseGogData(document.documentElement.innerHTML);
                if (d) gogOrdersData = ordersFromData(d);
            }
            if (!gogOrdersData) {
                setError('Could not read GOG order data. Make sure you are logged in and on the orders page.');
                return;
            }
            totalPages = gogOrdersData.totalPages || 1;
            processOrders(gogOrdersData.orders || []);
        } catch (e) {
            setError('Error reading page 1 order data: ' + e.message);
            return;
        }

        // ── Pages 2-N: use the JSON /data endpoint that Angular calls ────────
        // GOG's UI fetches paginated orders from /account/settings/orders/data
        // with the default filter params.  This returns JSON directly.
        function fetchOrderPageJson(page) {
            const url = `https://www.gog.com/account/settings/orders/data`
                      + `?canceled=0&completed=1&in_progress=1&not_redeemed=1`
                      + `&page=${page}&pending=1&redeemed=1`;
            return new Promise((resolve, reject) => {
                GM_xmlhttpRequest({
                    method:  'GET',
                    url,
                    headers: { 'Accept': 'application/json, text/plain, */*' },
                    onload:  r => {
                        try { resolve(JSON.parse(r.responseText)); }
                        catch (e) { reject(new Error(`page ${page}: invalid JSON — ${r.responseText.slice(0, 120)}`)); }
                    },
                    onerror: reject, ontimeout: reject,
                });
            });
        }

        // Normalise the /data response: accepts {orders:[...]}, {orders:{orders:[...]}},
        // or a bare array — returns the flat orders array or null.
        function extractOrders(data) {
            if (!data) return null;
            if (Array.isArray(data)) return data;
            const inner = data.orders;
            if (Array.isArray(inner)) return inner;
            if (inner && Array.isArray(inner.orders)) return inner.orders;
            return null;
        }

        let totalOrdersFound = (gogOrdersData.orders || []).length;

        for (let page = 2; page <= totalPages; page++) {
            setStatus(`Reading order history…`, Math.round((page - 1) / totalPages * 80), `Page ${page - 1} / ${totalPages} — ${totalOrdersFound} orders so far`);
            try {
                const data   = await fetchOrderPageJson(page);
                const orders = extractOrders(data);
                if (orders && orders.length > 0) {
                    processOrders(orders);
                    totalOrdersFound += orders.length;
                } else {
                    console.warn(`[PlayDate] GOG orders page ${page}: empty or unrecognised response`, data);
                }
            } catch (e) {
                setError(`Failed to fetch page ${page}: ${e.message}`);
                return;
            }
            await new Promise(r => setTimeout(r, 300));
        }

        const total = Object.keys(dateMap).length;
        if (total === 0) {
            setError('No purchase dates found in order history.');
            return;
        }

        setStatus(`Sending ${total} dates to PlayDate…`, 90, '');

        // ── POST all dates to PlayDate ─────────────────────────────────────────
        try {
            const res  = await new Promise((resolve, reject) => {
                GM_xmlhttpRequest({
                    method: 'POST',
                    url: 'http://localhost:5000/api/gog/bulk-date-import',
                    headers: { 'Content-Type': 'application/json' },
                    data: JSON.stringify({ dates: dateMap }),
                    onload: resolve, onerror: reject, ontimeout: reject,
                });
            });
            const data = JSON.parse(res.responseText);
            if (data.status === 'success') {
                setStatus(
                    `Done — ${data.updated} date${data.updated !== 1 ? 's' : ''} imported, ${data.not_found} product${data.not_found !== 1 ? 's' : ''} not in library`,
                    100, ''
                );
                document.getElementById('pd-gog-status').style.color = '#66c0f4';
            } else {
                setError('PlayDate error: ' + (data.message || 'unknown'));
            }
        } catch (e) {
            setError('Could not reach PlayDate. Make sure it is running.');
        }
    }

    // =========================================================================
    // EA — scrape order history from myaccount.ea.com and send to PlayDate
    // Activates on /payment-wallet/order-history after user switches to "All"
    // =========================================================================
    function runEA() {
        const btn = document.createElement('button');
        btn.textContent = 'Import Dates → PlayDate';
        Object.assign(btn.style, {
            position: 'fixed', bottom: '20px', right: '20px', zIndex: '99999',
            background: '#1a7f4b', color: '#fff', border: 'none', borderRadius: '6px',
            padding: '10px 16px', fontSize: '0.88rem', cursor: 'pointer',
            boxShadow: '0 4px 16px rgba(0,0,0,0.5)', fontFamily: "'Segoe UI', sans-serif",
        });
        btn.title = 'Switch the time filter to "All" first, then click this button';
        document.body.appendChild(btn);

        function showResult(msg, ok) {
            btn.remove();
            const el = document.createElement('div');
            el.textContent = msg;
            Object.assign(el.style, {
                position: 'fixed', bottom: '20px', right: '20px', zIndex: '99999',
                background: '#1a2332', border: `1px solid ${ok ? '#1a7f4b' : '#c97c00'}`,
                color: '#c7d5e0', padding: '10px 16px', borderRadius: '8px',
                fontSize: '0.88rem', maxWidth: '380px', boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
                fontFamily: "'Segoe UI', sans-serif",
            });
            document.body.appendChild(el);
        }

        // Scrape one page by finding date spans directly, then extracting title from same <td>
        function scrapePage(titles) {
            const dateRe   = /\b(\d{4}-\d{2}-\d{2})\b/;
            const statusRe = /^(Completed|Failed|Cancelled|Processing|Payment pending|Pre-ordered|Refunded|Empty)$/i;
            const orderRe  = /^Order\s*#/i;
            const priceRe  = /^\$[\d.,]+$/;

            const dateSpans = [...document.querySelectorAll('span')].filter(s =>
                s.children.length === 0 && dateRe.test(s.textContent.trim())
            );

            for (const dateSpan of dateSpans) {
                const dateMatch = dateSpan.textContent.match(dateRe);
                const ts = Math.floor(Date.parse(dateMatch[1]) / 1000);
                if (isNaN(ts * 1000)) continue;

                const td = dateSpan.closest('td') || dateSpan.parentElement;
                if (!td) continue;

                const titleSpan = [...td.querySelectorAll('span')].find(s => {
                    const t = s.textContent.trim();
                    return s.children.length === 0 && t &&
                        !dateRe.test(t) && !statusRe.test(t) &&
                        !orderRe.test(t) && !priceRe.test(t);
                });
                if (!titleSpan) continue;
                const title = titleSpan.textContent.trim();
                if (!title || title === 'Description not available') continue;
                if (!titles[title] || ts < titles[title]) titles[title] = ts;
            }

            return dateSpans.length;
        }

        // Click the next page number button; return false if not found
        async function nextPage(current) {
            const label = String(current + 1);
            const candidate = [...document.querySelectorAll('button, [role="button"], a')]
                .find(el => el.textContent.trim() === label && !el.disabled);
            if (!candidate) return false;
            candidate.click();
            await new Promise(r => setTimeout(r, 1500));
            return true;
        }

        btn.addEventListener('click', async () => {
            btn.textContent = 'Reading orders…';
            btn.disabled = true;

            const titles = {};
            let page = 1;
            let totalSpans = 0;

            while (true) {
                const spansFound = scrapePage(titles);
                totalSpans += spansFound;
                btn.textContent = `Page ${page} — ${Object.keys(titles).length} orders…`;
                const more = await nextPage(page);
                if (!more) break;
                page++;
            }

            if (Object.keys(titles).length === 0) {
                showResult(
                    totalSpans === 0
                        ? 'No order rows found — make sure the time filter is set to "All" and orders are visible.'
                        : `Found ${totalSpans} date spans but could not extract titles — open DevTools console and report what you see.`,
                    false
                );
                return;
            }

            const total = Object.keys(titles).length;
            btn.textContent = `Sending ${total} dates…`;

            try {
                const res = await new Promise((resolve, reject) => {
                    GM_xmlhttpRequest({
                        method: 'POST',
                        url: 'http://localhost:5000/api/ea_app/bulk-date-import',
                        headers: { 'Content-Type': 'application/json' },
                        data: JSON.stringify({ titles }),
                        onload: resolve, onerror: reject, ontimeout: reject,
                    });
                });
                const d = JSON.parse(res.responseText);
                if (d.status === 'success') {
                    showResult(`Done — ${d.updated} date${d.updated !== 1 ? 's' : ''} imported, ${d.not_found} not matched`, true);
                } else {
                    showResult('PlayDate error: ' + (d.message || 'unknown'), false);
                }
            } catch (e) {
                showResult('Could not reach PlayDate — make sure it is running.', false);
            }
        });
    }

})();
