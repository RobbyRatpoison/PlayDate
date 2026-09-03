"""
Temporary beta-only remote-eval bridge for diagnosing Steam Deck UI bugs
over SSH (input.js polls GET /api/debug/eval, runs the JS, POSTs the
result to /api/debug/eval/result). Beta builds only. Delete before the
stable release along with the input.js hook and the app.py registration.
"""
from collections import deque

from flask import Blueprint, jsonify, request

from config import __build__

debug_bp = Blueprint('debug', __name__)

_ENABLED = 'beta' in __build__
_QUEUE = deque()
_RESULTS = deque(maxlen=200)
_seq = 0


@debug_bp.route('/api/debug/eval', methods=['GET', 'POST'])
def debug_eval():
    global _seq
    if not _ENABLED:
        return jsonify(ok=False), 404
    if request.method == 'POST':
        _seq += 1
        _QUEUE.append({'id': _seq, 'js': (request.get_json(silent=True) or {}).get('js', '')})
        return jsonify(ok=True, id=_seq)
    pending = list(_QUEUE)
    _QUEUE.clear()
    return jsonify(ok=True, pending=pending, results=list(_RESULTS))


@debug_bp.route('/api/debug/eval/result', methods=['POST'])
def debug_eval_result():
    if not _ENABLED:
        return jsonify(ok=False), 404
    data = request.get_json(silent=True) or {}
    _RESULTS.append({'id': data.get('id'), 'out': str(data.get('out'))[:4000]})
    return jsonify(ok=True)
