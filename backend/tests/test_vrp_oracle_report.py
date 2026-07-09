"""Tests for the oracle gate report — the gated/rejected/all split + pnl math."""
import json

from vrp.oracle_report import _pnl, summarize, load


def test_pnl_win_and_loss():
    assert _pnl(0.05, "no") == 0.05
    assert _pnl(0.10, "yes") == -0.90


def test_summarize_splits_gated_vs_rejected():
    rows = [
        {"gap": 0.02, "bid": 0.02, "fair": 0.00, "result": "no"},    # gated, win
        {"gap": 0.01, "bid": 0.03, "fair": 0.02, "result": "no"},    # gated, win
        {"gap": 0.00, "bid": 0.04, "fair": 0.07, "result": "yes"},   # rejected, loss
        {"gap": -0.02, "bid": 0.05, "fair": 0.09, "result": "yes"},  # rejected, loss
    ]
    r = summarize(rows, min_edge=0.005)
    assert r["all"]["n"] == 4
    assert r["gated"]["n"] == 2 and r["gated"]["yes_pct"] == 0.0
    assert r["gated"]["net_c"] == 2.5           # (0.02+0.03)/2 *100
    assert r["rejected"]["n"] == 2 and r["rejected"]["yes_pct"] == 100.0
    assert r["rejected"]["net_c"] < 0           # losses


def test_summarize_empty():
    assert summarize([])["all"] == {"n": 0}


def test_load_joins_resolved_to_first_snapshot(tmp_path):
    # two snapshots of the same ticker; load takes the FIRST as entry
    snaps = [
        {"ticker": "KXBTCD-x-T1", "gap": 0.02, "kalshi_bid": 0.02, "deribit_fair": 0.00},
        {"ticker": "KXBTCD-x-T1", "gap": 0.05, "kalshi_bid": 0.05, "deribit_fair": 0.00},  # later, ignored
        {"ticker": "KXBTCD-x-T2", "gap": 0.00, "kalshi_bid": 0.04, "deribit_fair": 0.07},
    ]
    (tmp_path / "oracle_20260709.jsonl").write_text("\n".join(json.dumps(s) for s in snaps))
    (tmp_path / "resolved.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"ticker": "KXBTCD-x-T1", "result": "no"},
        {"ticker": "KXBTCD-x-T2", "result": "yes"},
    ]))
    rows = load(str(tmp_path))
    assert len(rows) == 2
    t1 = next(x for x in rows if x["bid"] == 0.02)   # first snapshot's bid, not 0.05
    assert t1["gap"] == 0.02 and t1["result"] == "no"
