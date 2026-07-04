"""Unit tests for the Deribit chain collector (vrp.capture). No network — the
Deribit call is monkeypatched. Verifies snapshot shaping + the append/idempotency
behavior that makes the forward dataset trustworthy."""
import json

import vrp.capture as cap


def _fake_get(path, **params):
    if path == "get_book_summary_by_currency":
        return [
            {"instrument_name": "BTC-5JUL26-52000-C", "mark_price": 0.001, "mark_iv": 49.0,
             "bid_price": 0.0009, "ask_price": 0.0012, "mid_price": 0.00105,
             "open_interest": 100.0, "volume": 5.0, "underlying_price": 62000.0,
             "underlying_index": "SYN.BTC-5JUL26", "extra_field": "dropped"},
        ]
    if path == "get_index_price":
        return {"index_price": 62345.6}
    raise AssertionError(path)


def test_snapshot_shape_keeps_needed_fields(monkeypatch):
    monkeypatch.setattr(cap, "_get", _fake_get)
    snap = cap.snapshot_currency("BTC")
    assert snap["currency"] == "BTC"
    assert snap["index_price"] == 62345.6
    assert snap["n_instruments"] == 1
    inst = snap["instruments"][0]
    assert inst["mark_iv"] == 49.0 and inst["open_interest"] == 100.0
    assert "extra_field" not in inst          # trimmed to bound file growth


def test_index_failure_is_tolerated(monkeypatch):
    def g(path, **p):
        if path == "get_index_price":
            raise RuntimeError("down")
        return _fake_get(path, **p)
    monkeypatch.setattr(cap, "_get", g)
    snap = cap.snapshot_currency("BTC")
    assert snap["index_price"] is None        # snapshot still succeeds
    assert snap["n_instruments"] == 1


def test_capture_appends_and_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(cap, "_get", _fake_get)
    path, n = cap.capture(["BTC", "ETH"], str(tmp_path))
    assert n == 2                              # 1 instrument * 2 currencies
    lines = open(path).read().strip().splitlines()
    assert len(lines) == 2
    # a second run appends (never overwrites) — the record must never shrink
    path2, n2 = cap.capture(["BTC"], str(tmp_path))
    assert path2 == path
    assert len(open(path).read().strip().splitlines()) == 3
    rec = json.loads(lines[0])
    assert rec["captured_ts"] and rec["currency"] == "BTC"
