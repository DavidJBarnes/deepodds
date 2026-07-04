"""Unit tests for the read-only fill-quality report (longshot.fill_diff).

Pure functions over state dicts — no network, no state mutation. Covers fill-rate
and slippage accounting (the gate signal) and the live-vs-paper matched diff.
"""
from longshot.fill_diff import live_fill_quality, matched_diff, report, slippage_by_size


def _live(ticker, ip, isz, ap, fsz, **kw):
    d = {"ticker": ticker, "intended_price": ip, "intended_size": isz,
         "avg_fill_price": ap, "filled_size": fsz}
    d.update(kw)
    return d


def test_fill_quality_clean_full_fills():
    pos = [_live("A", 0.05, 1, 0.05, 1), _live("B", 0.10, 1, 0.10, 1)]
    q = live_fill_quality(pos)
    assert q["n"] == 2
    assert q["fill_rate_orders"] == 1.0
    assert q["fill_rate_contracts"] == 1.0
    assert q["partial_orders"] == 0 and q["zero_fill_orders"] == 0
    assert q["mean_slip_cents"] == 0.0
    assert q["worst_adverse_slip_cents"] == 0.0


def test_fill_quality_adverse_slippage_is_negative():
    # intended sell 0.06, actually sold at 0.04 -> 2c adverse for a seller
    q = live_fill_quality([_live("A", 0.06, 1, 0.04, 1)])
    assert q["mean_slip_cents"] == -2.0
    assert q["worst_adverse_slip_cents"] == -2.0


def test_fill_quality_partial_and_zero_fills():
    pos = [
        _live("full", 0.05, 10, 0.05, 10),
        _live("part", 0.05, 10, 0.05, 4),
        _live("zero", 0.05, 10, 0.05, 0),
    ]
    q = live_fill_quality(pos)
    assert q["n"] == 3
    assert q["partial_orders"] == 1
    assert q["zero_fill_orders"] == 1
    assert q["fill_rate_orders"] == round(1 / 3, 4)
    # contracts: 14 filled of 30 intended
    assert q["fill_rate_contracts"] == round(14 / 30, 4)


def test_fill_quality_skips_records_without_fill_data():
    pos = [_live("A", 0.05, 1, 0.05, 1), {"ticker": "paper-like", "sell_price": 0.05}]
    q = live_fill_quality(pos)
    assert q["n"] == 1


def test_fill_quality_empty():
    assert live_fill_quality([])["n"] == 0


def test_matched_diff_counts_and_price_delta():
    paper = [
        {"ticker": "A", "sell_price": 0.05, "result": "no"},
        {"ticker": "B", "sell_price": 0.10, "result": "yes"},
        {"ticker": "PONLY", "sell_price": 0.03, "result": "no"},
    ]
    live = [
        {"ticker": "A", "sell_price": 0.05, "result": "no"},
        {"ticker": "B", "sell_price": 0.08, "result": "yes"},  # 2c lower entry
        {"ticker": "LONLY", "sell_price": 0.02, "result": "no"},
    ]
    m = matched_diff(paper, live)
    assert m["shared"] == 2
    assert m["paper_only"] == 1 and m["live_only"] == 1
    # deltas: A 0.0c, B -2.0c -> mean -1.0c
    assert m["mean_price_delta_cents"] == -1.0
    assert m["outcome_agreement"] == "2/2"


def test_matched_diff_outcome_disagreement_counts():
    paper = [{"ticker": "A", "sell_price": 0.05, "result": "no"}]
    live = [{"ticker": "A", "sell_price": 0.05, "result": "yes"}]
    m = matched_diff(paper, live)
    assert m["outcome_agreement"] == "0/1"


def test_matched_diff_ignores_unsettled_for_agreement():
    paper = [{"ticker": "A", "sell_price": 0.05, "result": None}]
    live = [{"ticker": "A", "sell_price": 0.05, "result": None}]
    m = matched_diff(paper, live)
    assert m["shared"] == 1
    assert m["outcome_agreement"] is None  # nothing resolved on both sides


def test_slippage_by_size_buckets_and_signs():
    pos = [
        _live("a", 0.05, 1, 0.05, 1),    # 1ct, 0 slip
        _live("b", 0.05, 1, 0.05, 1),    # 1ct, 0 slip
        _live("c", 0.06, 5, 0.04, 5),    # 5ct, -2c adverse
        _live("d", 0.05, 12, 0.05, 12),  # 10-24ct bucket, 0 slip
    ]
    s = slippage_by_size(pos)
    assert s["n"] == 4
    b = {x["size_bucket"]: x for x in s["buckets"]}
    assert b["1-1ct"]["n"] == 2 and b["1-1ct"]["mean_slip_cents"] == 0.0
    assert b["5-9ct"]["n"] == 1 and b["5-9ct"]["worst_adverse_cents"] == -2.0
    assert b["10-24ct"]["n"] == 1


def test_slippage_by_size_ignores_records_without_fill_data():
    assert slippage_by_size([{"ticker": "x", "sell_price": 0.05}])["n"] == 0


def test_report_wires_both_views():
    rep = report(
        {"positions": [_live("A", 0.05, 1, 0.05, 1, result="no", sell_price=0.05)]},
        {"positions": [{"ticker": "A", "sell_price": 0.05, "result": "no"}]},
    )
    assert rep["live_fill_quality"]["n"] == 1
    assert rep["matched"]["shared"] == 1
