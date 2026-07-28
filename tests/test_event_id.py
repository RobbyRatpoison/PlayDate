"""PAGYWOSG event id formula (event 83 = April 2026), via the category scanner's
_current_event_id() — the same anchor pagywosg.py's pagywosg_auto() uses inline."""
import importlib.util
import os
from datetime import date
from types import SimpleNamespace

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope='module')
def scan_tool():
    spec = importlib.util.spec_from_file_location(
        'pagywosg_category_scan',
        os.path.join(_ROOT, 'tools', 'pagywosg_category_scan.py'),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("year,month,expected", [
    (2026, 4, 83),    # the anchor
    (2026, 5, 84),
    (2026, 3, 82),
    (2026, 12, 91),
    (2027, 1, 92),    # year rollover
    (2027, 4, 95),
    (2025, 4, 71),
])
def test_event_id_anchor_and_rollover(scan_tool, monkeypatch, year, month, expected):
    monkeypatch.setattr(scan_tool, 'date',
                        SimpleNamespace(today=lambda: date(year, month, 15)))
    assert scan_tool._current_event_id() == expected
