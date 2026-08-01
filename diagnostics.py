"""Lets a user send playdate.log (plus a short version/OS summary) straight to
a Discord webhook for support triage, without needing a GitHub account.
Only the log file and an optional user-typed message are sent -- never
config.json/state.json, so no API keys or account tokens leave the machine."""
import json
import logging
import os
import platform
import sys
import threading
import time

import requests
from flask import Blueprint, jsonify, request

from config import BASE_DIR, IN_FLATPAK, IS_PORTABLE, __version__, load_state, save_state

log = logging.getLogger(__name__)

diagnostics_bp = Blueprint('diagnostics', __name__)

# Fill this in with your own Discord webhook URL to enable in-app log
# submission (Channel Settings -> Integrations -> Webhooks -> New Webhook ->
# Copy URL). Left blank, /api/submit-log just reports itself unavailable.
#
# NOTE: this ships inside the built app and public source, so it is
# discoverable and postable-to by anyone, not just PlayDate's UI. Discord's
# per-webhook rate limits are the only real backstop against abuse; if it
# ever gets spammed, delete and regenerate the webhook (this constant is the
# only place that needs updating).
DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/1532973217566687413/Wlr847Tgl_h1lDs3vkMgjZl85OcqepGl83moVtlVQOAtCbtzASupkgyQvLY0aC8n4x67'

MAX_LOG_BYTES        = 1024 * 1024  # matches the RotatingFileHandler cap (app.py)
SUBMIT_COOLDOWN_SECONDS = 5 * 60
MAX_MESSAGE_CHARS    = 1000

_submit_lock = threading.Lock()


def _install_channel():
    if IN_FLATPAK:
        return 'flatpak'
    if IS_PORTABLE:
        return 'portable'
    if getattr(sys, 'frozen', False):
        return 'installer'
    return 'source'


@diagnostics_bp.route('/api/submit-log', methods=['POST'])
def submit_log():
    if not DISCORD_WEBHOOK_URL:
        return jsonify({"status": "error", "message": "Log submission isn't configured for this build."}), 501

    if not _submit_lock.acquire(blocking=False):
        return jsonify({"status": "error", "message": "A submission is already in progress."}), 409
    try:
        state = load_state()
        last  = state.get('last_log_submit_at')
        if last and time.time() - last < SUBMIT_COOLDOWN_SECONDS:
            wait = int(SUBMIT_COOLDOWN_SECONDS - (time.time() - last))
            return jsonify({"status": "error", "message": f"Please wait {wait}s before submitting again."}), 429

        message = ((request.json or {}).get('message') or '').strip()[:MAX_MESSAGE_CHARS]

        log_path = os.path.join(BASE_DIR, 'playdate.log')
        try:
            with open(log_path, 'rb') as f:
                log_bytes = f.read()
        except OSError as e:
            return jsonify({"status": "error", "message": f"Could not read log file: {e}"}), 500
        if len(log_bytes) > MAX_LOG_BYTES:
            log_bytes = log_bytes[-MAX_LOG_BYTES:]

        content = (
            f"**PlayDate log submission**\n"
            f"Version: {__version__} ({_install_channel()})\n"
            f"OS: {platform.system()} {platform.release()}\n"
        )
        if message:
            content += f"Message: {message}\n"

        try:
            resp = requests.post(
                DISCORD_WEBHOOK_URL,
                data={'payload_json': json.dumps({'content': content})},
                files={'file': ('playdate.log', log_bytes, 'text/plain')},
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning(f"Log submission failed: {e}")
            return jsonify({"status": "error", "message": "Could not reach the report server. Try again later."}), 502

        save_state({'last_log_submit_at': time.time()})
        return jsonify({"status": "success"})
    finally:
        _submit_lock.release()
