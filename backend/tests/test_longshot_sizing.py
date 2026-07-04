"""Coverage for scaling the live canary beyond 1 contract (fill-at-size test).

Guards the two levers we turn: trade_fraction (drives contract count) and the
per-trade cap on the risk gate. Ensures multi-contract sizing is depth-governed
(thin books still get sized DOWN) and that the gate admits sizes up to its cap but
rejects above it — so we never silently place more than intended.
"""
from datetime import datetime, timezone

from longshot.config import LongshotConfig
from longshot.paper_run import size_candidate
from longshot.risk import RiskGate, PortfolioRisk

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
CLOSE = "2030-01-01T10:00:00Z"


def _market(bid_size, yb=0.05):
    return {"ticker": "KXHIGHNY-30JAN01-T80", "yes_ask_dollars": yb,
            "yes_bid_dollars": yb, "yes_bid_size_fp": bid_size, "close_time": CLOSE,
            "open_interest_fp": 500.0}


def _cfg(trade_fraction):
    c = LongshotConfig()
    c.trade_fraction = trade_fraction
    return c


def test_trade_fraction_drives_multi_contract():
    # 0.02 * $1000 / (1-0.05) = ~21 contracts when the book is deep enough
    c = size_candidate(_cfg(0.02), _market(bid_size=1000), "KXHIGHNY", NOW, 1000.0, 0.0)
    assert c is not None
    assert c["size"] == int(1000 * 0.02 / 0.95)  # 21
    assert c["size"] > 1


def test_depth_cap_sizes_thin_books_down():
    # thin bid (8) -> capped at 25% of standing bid = 2, NOT the 21 fraction would want
    c = size_candidate(_cfg(0.02), _market(bid_size=8), "KXHIGHNY", NOW, 1000.0, 0.0)
    assert c is not None
    assert c["size"] == int(0.25 * 8)  # 2
    assert c["collateral"] == round((1 - 0.05) * 2, 2)


def test_small_fraction_still_one_contract():
    # the old throttle: 0.005 * $222 / 0.95 < 1 -> floor to 1
    c = size_candidate(_cfg(0.005), _market(bid_size=1000), "KXHIGHNY", NOW, 222.0, 0.0)
    assert c is not None and c["size"] == 1


def test_gate_admits_up_to_cap_rejects_above(tmp_path):
    g = RiskGate(LongshotConfig(max_per_trade_contracts=10, max_deployed_collateral=200.0,
                                max_open_positions=120, max_daily_loss=25.0,
                                kill_file=str(tmp_path / "KILL")))
    pr = PortfolioRisk(0, 0, 0)
    assert g.check_order(pr, contracts=5, collateral=4.75).allow      # within cap
    assert g.check_order(pr, contracts=10, collateral=9.5).allow      # at cap
    assert not g.check_order(pr, contracts=11, collateral=10.4).allow  # above cap -> rejected


def test_daily_loss_kill_still_binds_at_size(tmp_path):
    # scaling size must NOT weaken the $25 daily-loss governor: pretick trips the
    # kill switch when the day's realized loss reaches the cap.
    g = RiskGate(LongshotConfig(max_per_trade_contracts=10, max_deployed_collateral=200.0,
                                max_open_positions=120, max_daily_loss=25.0,
                                kill_file=str(tmp_path / "KILL")))
    ok = g.pretick(PortfolioRisk(0, 0, realized_pnl_today=-24.0))
    assert ok.allow                                                   # under the cap
    tripped = g.pretick(PortfolioRisk(0, 0, realized_pnl_today=-25.0))
    assert not tripped.allow                                          # at cap -> blocked + kill tripped
    assert (tmp_path / "KILL").exists()
