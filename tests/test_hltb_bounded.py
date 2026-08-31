import time

import pytest

import scrapers


def test_returns_value():
    assert scrapers._hltb_bounded(lambda: 42) == 42


def test_passes_args():
    assert scrapers._hltb_bounded(lambda a, b: a + b, 2, 3) == 5


def test_propagates_exception():
    with pytest.raises(ValueError, match="boom"):
        scrapers._hltb_bounded(lambda: (_ for _ in ()).throw(ValueError("boom")))


def test_deadline_raises_timeout(monkeypatch):
    monkeypatch.setattr(scrapers, "_HLTB_CALL_DEADLINE", 0.3)
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        scrapers._hltb_bounded(lambda: time.sleep(5))
    assert time.monotonic() - start < 2  # returned promptly, didn't wait out the sleep
