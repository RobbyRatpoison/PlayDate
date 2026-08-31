import threading

import scrapers


def _run(monkeypatch, results, **kw):
    calls = []
    seen_kw = []
    monkeypatch.setattr('metadata.backfill_metadata',
                        lambda appid, **_kw: (seen_kw.append(_kw), results.get(appid))[1])
    monkeypatch.setattr(scrapers, 'update_game_data', lambda appid, **d: calls.append(appid))
    ev = kw.pop('cancel_event', threading.Event())
    out = scrapers._backfill_batch(list(results), ev, None, inter_delay=0, **kw)
    _run.last_kw = seen_kw
    return out, calls


def test_counts(monkeypatch):
    out, calls = _run(monkeypatch, {1: {'meta_backfill_fetched': 'x'}, 2: None,
                                    3: {'tags': 't', 'meta_backfill_fetched': 'x'}})
    assert out['done'] == 2 and out['failed'] == 1 and out['attempted'] == 3
    assert calls == [1, 3] and out['capped'] is False


def test_per_session_cap(monkeypatch):
    out, _ = _run(monkeypatch, {i: {'meta_backfill_fetched': 'x'} for i in range(10)},
                  per_session_cap=4)
    assert out['attempted'] == 4 and out['capped'] is True


def test_rerun_forwarded(monkeypatch):
    _run(monkeypatch, {1: {'meta_backfill_fetched': 'x'}}, rerun=True)
    assert _run.last_kw == [{'rerun': True}]
    _run(monkeypatch, {1: {'meta_backfill_fetched': 'x'}})
    assert _run.last_kw == [{'rerun': False}]


def test_cancel(monkeypatch):
    ev = threading.Event()
    ev.set()
    out, calls = _run(monkeypatch, {i: {'meta_backfill_fetched': 'x'} for i in range(5)},
                      cancel_event=ev)
    assert out['attempted'] == 0 and calls == []
