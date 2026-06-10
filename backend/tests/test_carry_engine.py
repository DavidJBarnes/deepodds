"""Lock the funding-carry money-math: gating, accrual, delta-neutrality,
liquidation, and capital conservation."""
from carry.config import CarryConfig
from carry.engine import (
    accrue_funding, close_position, open_position, target_notional, tick,
)
from carry.models import CarryPosition, PaperPortfolio

CFG = CarryConfig()
PER_YEAR = 24 * 365


def _ctx(funding, mark):
    return {"funding": funding, "mark": mark, "oracle": mark}


# ---- funding gate ----
def test_gate_flat_below_hurdle():
    assert target_notional(0.03, CFG) == 0.0          # 3%/yr < 6% hurdle
    assert target_notional(None, CFG) == 0.0


def test_gate_full_when_rich():
    assert target_notional(0.25, CFG) == CFG.max_notional_per_symbol  # >= 20% rich


def test_gate_ramps_in_middle():
    mid = target_notional(0.13, CFG)  # halfway 6%->20%
    assert 0 < mid < CFG.max_notional_per_symbol
    assert abs(mid - CFG.max_notional_per_symbol * 0.5) < CFG.max_notional_per_symbol * 0.05


# ---- accrual ----
def test_accrue_positive_funding_credits_short():
    pos = CarryPosition("BTC", coin_qty=1.0, entry_perp=60000, entry_spot=60000,
                        hl_margin=30000, reserve=0)
    cf = accrue_funding(pos, hourly_rate=0.0001, mark=60000, hours=1.0)
    assert abs(cf - 0.0001 * 60000) < 1e-6
    assert pos.accrued_funding == cf


def test_accrue_negative_funding_debits():
    pos = CarryPosition("BTC", 1.0, 60000, 60000, 30000, 0)
    cf = accrue_funding(pos, -0.0002, 60000, 1.0)
    assert cf < 0 and pos.accrued_funding < 0


# ---- delta-neutrality: pnl independent of price ----
def test_pnl_is_funding_not_price():
    pos = CarryPosition("BTC", 1.0, 60000, 60000, 30000, 5000)
    pos.accrued_funding = 123.45
    # price doubles -> spot +60k, perp -60k, nets to ~funding
    assert abs(pos.realized_pnl() - pos.accrued_funding) < 1e-6   # entry basis 0, no fees
    # equity contribution is price-invariant up to funding
    assert abs(pos.hl_equity(120000) - (30000 + 123.45 - 60000)) < 1e-6


# ---- liquidation + kill-switch ----
def test_liquidation_on_big_up_move_kills_and_closes():
    pf = PaperPortfolio(cash_usd=100000)
    open_position(pf, "BTC", 60000, 20000, CFG)   # 2x: margin 10k + reserve 3k absorbs ~65% move
    # price doubles (+100%): short loses the full notional, far beyond margin+reserve
    big = 60000 * 2.0
    tick(pf, {"BTC": _ctx(0.0, big)}, {"BTC": 0.10}, CFG, now_ts=pf.last_tick_ts + 3600)
    assert pf.killed is True
    assert "BTC" not in pf.positions


def test_no_liquidation_within_buffer():
    pf = PaperPortfolio(cash_usd=100000)
    open_position(pf, "BTC", 60000, 20000, CFG)
    # +10% move: well within 2x cushion -> survives
    tick(pf, {"BTC": _ctx(0.00005, 60000 * 1.10)}, {"BTC": 0.10}, CFG, now_ts=pf.last_tick_ts + 3600)
    assert pf.killed is False
    assert "BTC" in pf.positions


# ---- capital conservation: open then close flat ~ returns capital minus fees ----
def test_open_close_round_trip_conserves_capital():
    pf = PaperPortfolio(cash_usd=100000)
    open_position(pf, "BTC", 60000, 20000, CFG)
    pf.positions["BTC"].accrued_funding = 50.0   # collected some funding
    close_position(pf, "BTC", 60000, CFG, "test")
    # cash back to ~100k + funding - fees; equity preserved
    assert abs(pf.cash_usd - (100000 + 50.0 - pf.fees_total)) < 1.0
    assert abs(pf.realized_pnl - (50.0 - pf.fees_total)) < 1.0


# ---- multi-tick: accrual matches rate*notional*hours; equity conserved ----
def test_multi_tick_accrual_and_equity_conservation():
    pf = PaperPortfolio(cash_usd=100000)
    rate, mark = 0.00002, 60000.0           # +0.002%/hr funding
    rich = {"BTC": 0.25}                     # rich -> opens full max_notional
    # tick 0: opens (hours=0, no accrual)
    tick(pf, {"BTC": _ctx(rate, mark)}, rich, CFG, now_ts=3600)
    notional = pf.positions["BTC"].notional(mark)
    assert abs(notional - CFG.max_notional_per_symbol) < 1e-6
    # 10 hourly ticks at constant mark -> accrual = 10 * rate * notional
    for k in range(1, 11):
        tick(pf, {"BTC": _ctx(rate, mark)}, rich, CFG, now_ts=3600 * (k + 1))
    expected = 10 * rate * notional
    assert abs(pf.accrued_funding_total - expected) < 1e-6
    # equity == initial - fees + accrued (capital conservation, price flat)
    eq = pf.equity({"BTC": mark})
    assert abs(eq - (100000 - pf.fees_total + pf.accrued_funding_total)) < 1e-6


def test_equity_price_invariant_delta_neutral():
    pf = PaperPortfolio(cash_usd=100000)
    tick(pf, {"BTC": _ctx(0.0, 60000.0)}, {"BTC": 0.25}, CFG, now_ts=3600)
    eq_flat = pf.equity({"BTC": 60000.0})
    # price +25% with zero funding: spot gain == perp loss -> equity unchanged
    tick(pf, {"BTC": _ctx(0.0, 75000.0)}, {"BTC": 0.25}, CFG, now_ts=7200)
    eq_up = pf.equity({"BTC": 75000.0})
    assert abs(eq_up - eq_flat) < 1e-6


def test_open_fills_capture_basis_and_spread():
    pf = PaperPortfolio(cash_usd=100000)
    # short perp at bid 61804, long spot at ask 61767 -> favorable +basis
    open_position(pf, "BTC", mark=61800, notional=20000, cfg=CFG,
                  fill_perp=61804, fill_spot=61767)
    pos = pf.positions["BTC"]
    assert pos.entry_perp == 61804 and pos.entry_spot == 61767
    assert pos.coin_qty == 20000 / 61767                  # bought spot at ask
    # close flat at same fills reversed: pnl reflects spread cost + favorable basis
    pf.positions["BTC"].accrued_funding = 0.0
    close_position(pf, "BTC", mark=61800, cfg=CFG, reason="t", exit_perp=61805, exit_spot=61766)
    # spot: sell 61766 vs bought 61767 (-1); perp: short 61804 buy 61805 (-1); minus fees
    assert pf.realized_pnl < 0     # round-trip spread + fees with no funding -> small loss
    assert pf.realized_pnl > -50   # but bounded/small (tight books)


def test_build_snapshot_shape():
    pf = PaperPortfolio(cash_usd=100000)
    tick(pf, {"BTC": _ctx(0.00002, 60000.0)}, {"BTC": 0.25, "ETH": 0.01}, CFG, now_ts=3600)
    from carry.engine import build_snapshot
    snap = build_snapshot(pf, {"BTC": _ctx(0.00002, 60000.0), "ETH": _ctx(0.0000001, 3000.0)},
                          {"BTC": 0.25, "ETH": 0.01}, CFG)
    assert snap["symbols"]["BTC"]["notional"] > 0      # opened (rich)
    assert snap["symbols"]["ETH"]["target"] == 0.0      # gated out (thin)
    assert "equity" in snap and "accrued_funding_total" in snap
