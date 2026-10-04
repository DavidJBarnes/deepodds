"""Tests for the Edge Explorer — metrics, robust-z baseline, rules, and the
idempotent ledger/digest tick. No network, no real files: sources are faked."""
import json
import math
from datetime import date, datetime, timedelta, timezone

from explorer import backfill, baseline, metrics as M, observe, rules, sources

NOW = datetime(2026, 7, 15, 2, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _ts(i, days=("2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13")):
    return f"{days[i % len(days)]}T12:00:00+00:00"


def _resolved(n_deep_no=60, n_mid=40, mid_yes=3):
    """Deep 1c tails (Kalshi cheap vs Deribit) + a 3-5c band that resolves YES
    more than it's priced. Engineered so gap_settled<0 and mid-tail underpriced.
    Settlements are spread over 4 days inside the 14d window of NOW."""
    rows = []
    for i in range(n_deep_no):
        rows.append({"ticker": f"D{i}", "result": "no", "kalshi_bid": 0.008,
                     "deribit_fair": 0.012, "sell_ev_vs_deribit": -0.004,
                     "realized_pnl": 0.008, "resolved_ts": _ts(i)})
    for i in range(n_mid):
        yes = i < mid_yes
        rows.append({"ticker": f"M{i}", "result": "yes" if yes else "no",
                     "kalshi_bid": 0.04, "deribit_fair": 0.05, "sell_ev_vs_deribit": -0.01,
                     "realized_pnl": -(1 - 0.04) if yes else 0.04, "resolved_ts": _ts(i)})
    return rows


def _tick(ts, settled, hit, pnl, orders=None, slip=None, fill=None):
    t = {"ts": ts, "settled_positions": settled, "hit_rate_no": hit, "realized_pnl": pnl}
    if orders is not None:
        t["slippage"] = {"orders": orders, "avg_slippage_c": slip, "fill_rate": fill}
    return t


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
    ms = {m.key: m for m in M.oracle_metrics(NOW)}
    assert ms["oracle.tail14d.gap_settled_c"].value < 0          # Kalshi below Deribit
    assert ms["oracle.tail30d.calib_err_mid_c"].value > 0        # mid-tail underpriced
    # 40 mid rows, 3 yes -> 7.5% actual vs 4c charge -> ~3.5c underpriced
    assert ms["oracle.tail30d.calib_err_mid_c"].context["actual_yes_pct"] == 7.5
    assert ms["oracle.tail14d.yes_rate"].context["n_days"] == 4
    assert "oracle.tail14d.gated_ev_c" not in ms                 # nothing clears the gate


def test_oracle_window_is_days_not_rows(monkeypatch):
    """Rows settled before the 14d window, or after `now` (backfill as-of), are excluded."""
    rows = _resolved()
    rows.append({"ticker": "OLD", "result": "yes", "kalshi_bid": 0.02, "deribit_fair": 0.01,
                 "realized_pnl": -0.98, "resolved_ts": "2026-06-20T12:00:00+00:00"})
    rows.append({"ticker": "FUT", "result": "yes", "kalshi_bid": 0.02, "deribit_fair": 0.01,
                 "realized_pnl": -0.98, "resolved_ts": "2026-07-20T12:00:00+00:00"})
    _fake_sources(monkeypatch, resolved=rows)
    ms = {m.key: m for m in M.oracle_metrics(NOW)}
    assert ms["oracle.tail14d.yes_rate"].context["n"] == 100


def test_clustered_se_widens_for_one_bad_day():
    """150 tails on one bad day + 150 clean on another: an iid SE would call the mean
    precise; clustering by day knows it is two observations."""
    pairs = [("d1", -0.5)] * 150 + [("d2", 0.02)] * 150
    m, se, g = M._clustered_mean_se(pairs)
    iid = math.sqrt(sum((x - m) ** 2 for _, x in pairs) / (len(pairs) - 1) / len(pairs))
    assert g == 2 and abs(m - (-0.24)) < 1e-9
    assert se > 10 * iid


def test_gated_ev_uses_entry_edge(monkeypatch):
    rows = _resolved()
    for i in range(40):  # clears the gate (bid - fair = 1c), loses on 2 of 40
        yes = i < 2
        rows.append({"ticker": f"G{i}", "result": "yes" if yes else "no", "kalshi_bid": 0.03,
                     "deribit_fair": 0.02, "sell_ev_vs_deribit": 0.01,
                     "realized_pnl": -0.97 if yes else 0.03, "resolved_ts": _ts(i)})
    _fake_sources(monkeypatch, resolved=rows)
    g = {m.key: m for m in M.oracle_metrics(NOW)}["oracle.tail14d.gated_ev_c"]
    assert g.context["n"] == 40 and g.context["yes_pct"] == 5.0
    assert abs(g.value - (2 * -97 + 38 * 3) / 40) < 1e-3          # -2.0c


def test_longshot_window_is_marginal_not_cumulative(monkeypatch):
    """Since inception: 1000 trades at 97% NO. Last 14 days: 200 more at 94%. The
    cumulative rate barely moves (96.5%); the window must see 94%."""
    live = [_tick("2026-06-01T00:00:00+00:00", 0, None, 0.0, 0, 0.0, 1.0),
            _tick("2026-06-30T00:00:00+00:00", 1000, 0.97, 100.0, 1000, -0.03, 0.998),
            _tick("2026-07-14T23:00:00+00:00", 1200, (970 + 188) / 1200, 60.0, 1200, -0.0, 0.995)]
    paper = [_tick("2026-06-30T00:00:00+00:00", 1000, 0.97, 100.0),
             _tick("2026-07-14T23:00:00+00:00", 1200, (970 + 194) / 1200, 110.0)]
    _fake_sources(monkeypatch, live=live, paper=paper)
    ms = {m.key: m for m in M.longshot_metrics(NOW)}
    assert abs(ms["longshot.live.hit_rate_no_14d"].value - 0.94) < 1e-4
    assert ms["longshot.live.pnl_14d"].value == -40.0
    assert ms["longshot.live.hit_rate_no_14d"].context["n"] == 200
    # slippage over the window's 200 orders: (0*1200 - (-0.03)*1000)/200 = +0.15c
    assert abs(ms["longshot.live.slippage_14d_c"].value - 0.15) < 1e-4
    assert abs(ms["longshot.live.fill_rate_14d"].value - (0.995 * 1200 - 0.998 * 1000) / 200) < 1e-4
    # paper 3% YES vs live 6% YES -> live worse by 0.03
    assert abs(ms["longshot.adverse.paper_minus_live_hit_14d"].value - 0.03) < 1e-4
    assert ms["longshot.live.pnl_30d"].value == 60.0              # 06-01 tick (pnl 0) anchors 30d
    assert ms["longshot.live.pnl_30d"].context["hit_rate_no"] is None   # anchor had no rate


def test_longshot_window_needs_full_history(monkeypatch):
    live = [_tick("2026-07-10T00:00:00+00:00", 10, 0.9, 1.0),
            _tick("2026-07-14T00:00:00+00:00", 20, 0.95, 2.0)]
    _fake_sources(monkeypatch, live=live)
    assert M.longshot_metrics(NOW) == []                          # partial window is not a window


def _chain(captured="2026-07-01T00:00:00+00:00"):
    def opt(exp, k, t, iv):
        return {"instrument_name": f"BTC-{exp}-{k}-{t}", "mark_iv": iv}
    ins = [opt("02JUL26", 60000, "C", 200.0), opt("02JUL26", 60000, "P", 200.0),   # 1.3d: excluded
           opt("03JUL26", 60000, "C", 40.0), opt("03JUL26", 60000, "P", 40.0),     # 2.33d
           opt("10JUL26", 60000, "C", 50.0), opt("10JUL26", 60000, "P", 50.0),     # 9.33d
           opt("10JUL26", 54000, "P", 60.0), opt("10JUL26", 66000, "C", 45.0),
           opt("07AUG26", 60000, "C", 60.0), opt("07AUG26", 60000, "P", 60.0),     # 37.33d
           opt("07AUG26", 54000, "P", 70.0), opt("07AUG26", 66000, "C", 50.0)]
    return [{"currency": "BTC", "index_price": 60000, "captured_ts": captured, "instruments": ins}]


def _cm_iv(t1, v1, t2, v2, tau):
    w = v1 * v1 * t1 + (v2 * v2 * t2 - v1 * v1 * t1) * (tau - t1) / (t2 - t1)
    return math.sqrt(w / tau)


def test_deribit_constant_maturity():
    ms = {m.key: m for m in M.deribit_metrics(chain=_chain())}
    t2, t3, t4 = 2 + 8 / 24, 9 + 8 / 24, 37 + 8 / 24
    iv7, iv30 = _cm_iv(t2, 0.4, t3, 0.5, 7), _cm_iv(t3, 0.5, t4, 0.6, 30)
    assert abs(ms["deribit.BTC.atm_iv_30d"].value - round(iv30, 4)) < 1e-9
    assert abs(ms["deribit.BTC.term_slope_7_30_pts"].value - round((iv30 - iv7) * 100, 3)) < 1e-9
    skew = 0.15 + 0.05 * (30 - t3) / (t4 - t3)                     # 10JUL 15pts -> 07AUG 20pts
    assert abs(ms["deribit.BTC.skew_30d_pts"].value - round(skew * 100, 3)) < 1e-9


def test_deribit_tenor_measured_from_capture_not_run_time():
    """The explorer runs hours after the chain is captured; T must come from captured_ts."""
    a = {m.key: m.value for m in M.deribit_metrics(datetime(2026, 7, 1, 15, tzinfo=timezone.utc), chain=_chain())}
    b = {m.key: m.value for m in M.deribit_metrics(datetime(2026, 7, 1, 1, tzinfo=timezone.utc), chain=_chain())}
    assert a == b


def test_deribit_no_extrapolation():
    chain = _chain()
    chain[0]["instruments"] = [i for i in chain[0]["instruments"] if "07AUG26" not in i["instrument_name"]]
    ms = {m.key for m in M.deribit_metrics(chain=chain)}
    assert not any(k.endswith("_30d") or "7_30" in k for k in ms)


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
    assert z["z"] <= baseline.Z_CAP                               # never unbounded


def test_robust_z_recovery_from_stuck_metric_is_not_a_billion_sigma():
    """Regression: dq.bookrec.populated_frac sat at 0.0 for 15 days (dead recorder), then
    #231 fixed it and it jumped to 1.0. MAD is 0 across a majority-constant baseline, so
    the old epsilon divisor produced z=1e9 and that row owned digest rank 1 for five days.
    A metric going *healthy* must not outrank every real observation."""
    prior = [0.0] * 15 + [0.9991, 0.9994, 1.0, 1.0]
    z = baseline.robust_z(1.0, prior)
    assert z is not None and z["median"] == 0.0 and z["mad"] == 0.0
    assert abs(z["z"]) < rules.Z_THRESHOLD                        # stays out of the digest
    assert rules.deviation_rule(M.Metric("dq.bookrec.populated_frac", 1.0, {}), z) is None


def test_robust_z_still_flags_a_real_outlier_against_a_flat_baseline():
    """The floor must not blunt genuine anomalies: a stuck-at-zero metric that goes
    sharply negative is still a real event and must clear the threshold."""
    prior = [0.0] * 15 + [0.0, 0.0, 0.0, 0.0]
    z = baseline.robust_z(-5.0, prior)
    assert z is not None and z["z"] <= -rules.Z_THRESHOLD
    assert abs(z["z"]) <= baseline.Z_CAP


def test_prior_values_excludes_today():
    hist = [{"date": "2026-07-13", "key": "k", "value": 1.0},
            {"date": "2026-07-14", "key": "k", "value": 2.0},
            {"date": "2026-07-15", "key": "k", "value": 9.0}]
    assert baseline.prior_values(hist, "k", "2026-07-15") == [1.0, 2.0]


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------
def test_structural_obs1_fires_on_inverted_gap():
    m = M.Metric("oracle.tail14d.gap_settled_c", -0.41, {"n": 150, "kalshi_c": 3.18, "deribit_c": 3.59})
    obs = rules.structural_rules(m)
    assert any(o["rule_key"] == "oracle.tail_thesis_inverted" for o in obs)


def _fires(key, v, ctx, rule_key):
    return any(o["rule_key"] == rule_key for o in rules.structural_rules(M.Metric(key, v, ctx)))


def test_blind_sell_needs_clustered_significance():
    """09-03 shape: -16c from one big-move day has a huge clustered SE -> silent.
    A steady -1.5c with a tight SE is a real statement -> fires."""
    k = "oracle.tail14d.blind_sell_ev_c"
    assert not _fires(k, -16.4, {"n": 5000, "n_days": 14, "se_c": 9.0}, "oracle.blind_sell_negative")
    assert _fires(k, -1.5, {"n": 5000, "n_days": 14, "se_c": 0.4}, "oracle.blind_sell_negative")
    assert not _fires(k, -0.3, {"n": 5000, "n_days": 14, "se_c": 0.01}, "oracle.blind_sell_negative")


def test_gate_not_clearing_rule():
    k = "oracle.tail14d.gated_ev_c"
    assert _fires(k, -0.8, {"n": 60, "se_c": 0.5, "yes_pct": 3.0}, "oracle.gate_not_clearing")
    assert not _fires(k, -0.8, {"n": 10}, "oracle.gate_not_clearing")      # too few
    assert not _fires(k, 0.4, {"n": 60}, "oracle.gate_not_clearing")


def test_live_pnl_negative_rule():
    k = "longshot.live.pnl_30d"
    assert _fires(k, -17.1, {"n": 900, "hit_rate_no": 0.951, "per_trade": -0.019}, "longshot.live_pnl_negative")
    assert not _fires(k, 12.0, {"n": 900}, "longshot.live_pnl_negative")
    assert not _fires(k, -5.0, {"n": 40}, "longshot.live_pnl_negative")


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


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------
def test_backfill_rebuilds_as_of_history_idempotently(monkeypatch, tmp_path):
    rows = _resolved()
    _fake_sources(monkeypatch, resolved=rows)
    monkeypatch.setattr(sources, "deribit_chain_for",
                        lambda day: _chain(f"{day}T12:00:00+00:00") if day == "2026-07-01" else [])
    n = backfill.backfill(str(tmp_path), date(2026, 7, 1), date(2026, 7, 14))
    hist = baseline.load_history(str(tmp_path))
    assert n == len(hist) > 0
    keys_by_day = {}
    for r in hist:
        keys_by_day.setdefault(r["date"], set()).add(r["key"])
    assert "deribit.BTC.atm_iv_30d" in keys_by_day["2026-07-01"]
    # as-of: nothing had settled by 07-01..07-09 (first settlement 07-10 12:00)
    assert not any(k.startswith("oracle.") for d in ("2026-07-01", "2026-07-09") for k in keys_by_day.get(d, ()))
    assert "oracle.tail14d.yes_rate" in keys_by_day["2026-07-13"]
    # latest-file families are never backfilled
    assert not any(r["key"] in ("oracle.tail.gap_open_c", "dq.bookrec.populated_frac") for r in hist)
    assert backfill.backfill(str(tmp_path), date(2026, 7, 1), date(2026, 7, 14)) == 0
    # source functions restored after the cached run
    assert not hasattr(sources.resolved_tails, "cache_info")
