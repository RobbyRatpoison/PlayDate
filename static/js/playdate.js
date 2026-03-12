/**
 * playdate.js — shared utilities loaded on every page via base.html
 */

async function sendStateUpdate(payload) {
    try {
        const response = await fetch('/api/update_state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            window.location.reload();
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
