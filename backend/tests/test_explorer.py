"""Tests for the Edge Explorer — metrics, robust-z baseline, rules, and the
idempotent ledger/digest tick. No network, no real files: sources are faked."""
import json
from datetime import datetime, timezone

from explorer import baseline, metrics as M, observe, rules, sources

NOW = datetime(2026, 7, 15, 2, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _resolved(n_deep_no=60, n_mid=40, mid_yes=3):
    """Deep 1c tails (Kalshi cheap vs Deribit) + a 3-5c band that resolves YES
    more than it's priced. Engineered so gap_settled<0 and mid-tail underpriced."""
    rows = []
    for i in range(n_deep_no):
        rows.append({"ticker": f"D{i}", "result": "no", "kalshi_bid": 0.008,
                     "deribit_fair": 0.012, "realized_pnl": 0.008})
    for i in range(n_mid):
        yes = i < mid_yes
        rows.append({"ticker": f"M{i}", "result": "yes" if yes else "no",
                     "kalshi_bid": 0.04, "deribit_fair": 0.05,
                     "realized_pnl": -(1 - 0.04) if yes else 0.04})
    return rows


def _fake_sources(monkeypatch, resolved=None, snaps=None, paper=None, live=None,
                  chain=None, book=None):
    _paper, _live = paper or [], live or []
    monkeypatch.setattr(sources, "resolved_tails", lambda: resolved or [])
    monkeypatch.setattr(sources, "open_tail_snapshots", lambda: snaps or [])
    monkeypatch.setattr(sources, "longshot_history",
                        lambda live=False: _live if live else _paper)
    monkeypatch.setattr(sources, "deribit_chain_latest", lambda: chain or [])
    monkeypatch.setattr(sources, "bookrec_latest_stats",
                        lambda: book or {"file": "book_x.jsonl", "total": 100, "populated": 0})


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def test_oracle_metrics_compute(monkeypatch):
    _fake_sources(monkeypatch, resolved=_resolved())
    ms = {m.key: m for m in M.oracle_metrics()}
    assert ms["oracle.tail.gap_settled_c"].value < 0          # Kalshi below Deribit
    assert ms["oracle.tail.calib_err_mid_c"].value > 0        # mid-tail underpriced
    # 40 mid rows, 3 yes -> 7.5% actual vs 4c charge -> ~3.5c underpriced
    assert ms["oracle.tail.calib_err_mid_c"].context["actual_yes_pct"] == 7.5


def test_longshot_adverse_selection_proxy(monkeypatch):
    _fake_sources(monkeypatch,
                  paper=[{"ts": "t", "hit_rate_no": 0.96, "roi_on_settled_collateral": 0.01}],
                  live=[{"ts": "t", "hit_rate_no": 0.90, "realized_pnl": 1.0,
                         "slippage": {"orders": 100, "fill_rate": 0.99, "avg_slippage_c": -0.04}}])
    ms = {m.key: m for m in M.longshot_metrics()}
    # paper 4% YES vs live 10% YES -> live worse by 0.06
    assert abs(ms["longshot.adverse.paper_minus_live_hit"].value - 0.06) < 1e-9


def test_deribit_metrics_surface(monkeypatch):
    chain = [{"currency": "BTC", "index_price": 60000, "instruments": [
        {"instrument_name": "BTC-10JUL26-60000-C", "mark_iv": 50.0},
        {"instrument_name": "BTC-10JUL26-60000-P", "mark_iv": 55.0},
        {"instrument_name": "BTC-10JUL26-54000-P", "mark_iv": 60.0},
        {"instrument_name": "BTC-10JUL26-66000-C", "mark_iv": 45.0},
        {"instrument_name": "BTC-10AUG26-60000-C", "mark_iv": 52.0},
    ]}]
    monkeypatch.setattr(sources, "deribit_chain_latest", lambda: chain)
    now = datetime(2026, 7, 5, tzinfo=timezone.utc)
    ms = {m.key: m for m in M.deribit_metrics(now)}
    assert abs(ms["deribit.BTC.atm_iv"].value - 0.525) < 1e-6      # avg call/put ATM
    assert abs(ms["deribit.BTC.skew_pts"].value - 15.0) < 1e-6     # put 60 - call 45
    assert abs(ms["deribit.BTC.term_slope_pts"].value - (-0.5)) < 1e-6


def test_dataquality_flags_empty_book(monkeypatch):
    _fake_sources(monkeypatch, book={"file": "book_x.jsonl", "total": 690, "populated": 0})
    ms = {m.key: m for m in M.dataquality_metrics()}
    assert ms["dq.bookrec.populated_frac"].value == 0.0


# ---------------------------------------------------------------------------
# baseline / robust-z
# ---------------------------------------------------------------------------
def test_robust_z_gate_and_value():
    assert baseline.robust_z(5.0, [1.0, 1.0]) is None            # < MIN_HISTORY
    z = baseline.robust_z(10.0, [1.0, 1.0, 1.0, 1.0])            # median 1, mad 0 -> floored
    assert z is not None and z["z"] > 0 and z["median"] == 1.0


def test_prior_values_excludes_today():
    hist = [{"date": "2026-07-13", "key": "k", "value": 1.0},
            {"date": "2026-07-14", "key": "k", "value": 2.0},
            {"date": "2026-07-15", "key": "k", "value": 9.0}]
    assert baseline.prior_values(hist, "k", "2026-07-15") == [1.0, 2.0]


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------
def test_structural_obs1_fires_on_inverted_gap():
    m = M.Metric("oracle.tail.gap_settled_c", -0.41, {"n": 150, "kalshi_c": 3.18, "deribit_c": 3.59})
    obs = rules.structural_rules(m)
    assert any(o["rule_key"] == "oracle.tail_thesis_inverted" for o in obs)


def test_deviation_rule_needs_threshold():
    m = M.Metric("x.y", 10.0, {})
    assert rules.deviation_rule(m, {"z": 1.0, "median": 0, "mad": 1, "n": 5}) is None
    hit = rules.deviation_rule(m, {"z": 3.2, "median": 0, "mad": 1, "n": 5})
    assert hit and hit["kind"] == "deviation" and hit["surprise"] == 3.2


# ---------------------------------------------------------------------------
# observe — idempotent tick, ledger, digest
# ---------------------------------------------------------------------------
def test_generate_observations_fires_and_is_idempotent(monkeypatch, tmp_path):
    _fake_sources(monkeypatch, resolved=_resolved())
    r1 = observe.generate_observations(str(tmp_path), NOW)
    assert r1["n_observations"] >= 3 and r1["n_new_ledger"] == r1["n_observations"]

    ledger = [json.loads(ln) for ln in (tmp_path / "observations.jsonl").read_text().splitlines()]
    rk = {o["rule_key"]: o for o in ledger}
    assert "oracle.tail_thesis_inverted" in rk
    assert rk["oracle.tail_thesis_inverted"]["status"] == "investigate"   # seeded status
    assert rk["dq.bookrec_broken"]["kind"] == "data_quality"

    digest = json.loads((tmp_path / f"digest_{NOW.date().isoformat()}.json").read_text())
    scores = [o["score"] for o in digest["observations"]]
    assert scores == sorted(scores, reverse=True)                          # ranked

    # second run, same day -> no new ledger rows, ledger unchanged
    r2 = observe.generate_observations(str(tmp_path), NOW)
    assert r2["n_new_ledger"] == 0
    ledger2 = (tmp_path / "observations.jsonl").read_text().splitlines()
    assert len(ledger2) == len(ledger)


def test_resolution_drops_from_digest_but_keeps_history(monkeypatch, tmp_path):
    _fake_sources(monkeypatch, resolved=_resolved())
    observe.generate_observations(str(tmp_path), NOW)          # day 1: fires normally
    n_obs_before = json.loads((tmp_path / f"digest_{NOW.date().isoformat()}.json").read_text())["n_observations"]

    # mark the tail-thesis observation resolved
    (tmp_path / "resolutions.json").write_text(json.dumps({
        "oracle.tail_thesis_inverted": {"status": "resolved", "note": "de-bias falsified"}}))
    ledger_lines_before = len((tmp_path / "observations.jsonl").read_text().splitlines())

    day2 = datetime(2026, 7, 16, 2, 0, tzinfo=timezone.utc)
    r = observe.generate_observations(str(tmp_path), day2)      # day 2: resolved rule excluded
    digest = json.loads((tmp_path / "digest_2026-07-16.json").read_text())
    keys = [o["rule_key"] for o in digest["observations"]]
    assert "oracle.tail_thesis_inverted" not in keys           # gone from active digest
    assert digest["n_resolved"] >= 1
    assert r["n_observations"] == n_obs_before - 1             # one fewer active
    # no new ledger row for the resolved rule on day 2
    day2_rows = [json.loads(ln) for ln in (tmp_path / "observations.jsonl").read_text().splitlines()
                 if json.loads(ln)["date"] == "2026-07-16"]
    assert all(o["rule_key"] != "oracle.tail_thesis_inverted" for o in day2_rows)
    assert len((tmp_path / "observations.jsonl").read_text().splitlines()) > ledger_lines_before  # other rules still logged


def test_streak_increments_across_days(monkeypatch, tmp_path):
    _fake_sources(monkeypatch, resolved=_resolved())
    day1 = datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 7, 15, 2, 0, tzinfo=timezone.utc)
    observe.generate_observations(str(tmp_path), day1)
    observe.generate_observations(str(tmp_path), day2)
    ledger = [json.loads(ln) for ln in (tmp_path / "observations.jsonl").read_text().splitlines()]
    d2 = [o for o in ledger if o["date"] == "2026-07-15" and o["rule_key"] == "oracle.tail_thesis_inverted"]
    assert d2 and d2[0]["streak"] == 2                                     # consecutive days
