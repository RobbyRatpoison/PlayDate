"""PAGYWOSG event id formula (event 1 = June 2019, the site's actual first
event), via the category scanner's _current_event_id(), which calls the same
pagywosg.pagywosg_event_id() that pagywosg_auto()/pagywosg_quals_data() use."""
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
    (2019, 6, 1),     # the anchor -- actual first event
    (2026, 4, 83),    # cross-checked against the live event history
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
