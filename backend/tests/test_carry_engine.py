"""Lock the funding-carry money-math: gating, accrual, delta-neutrality,
liquidation, capital conservation, and v2/v3 rebalancing + resize."""
from carry.config import CarryConfig
from carry.engine import (
    accrue_funding, close_position, open_position, rebalance, resize_position,
    target_notional, tick,
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


# ---- Task 4 regression: cash cannot go negative on open ----
def test_cash_cannot_go_negative_on_open():
    """
    Regression for Task 4 engine fix: the old check (pf.cash_usd > tgt) allowed
    cash to go negative at small capital because tgt < committed_capital.
    After the fix (check pf.cash_usd >= committed_estimate), cash must stay ≥ 0.
    """
    # $2,000 capital. At CFG defaults (max_notional_per_symbol=$20k) the engine
    # cannot open ANY position — committed_estimate >> available cash.
    small_cfg = CarryConfig(
        paper_capital_usd=2_000.0,
        max_notional_per_symbol=2_000.0,
        max_total_notional_usd=3_000.0,
    )
    pf = PaperPortfolio(cash_usd=2_000.0)
    # Rich funding → engine WANTS to open
    rich = {"BTC": 0.50, "ETH": 0.50}
    tick(pf, {"BTC": _ctx(0.001, 30000.0), "ETH": _ctx(0.001, 2000.0)},
         rich, small_cfg, now_ts=3600)
    # committed_estimate for BTC: 2000×(1+0.5+0.15) + 2000×0.0004×2 = 3300+1.6 > 2000
    # Engine should NOT open — cash must remain non-negative
    assert pf.cash_usd >= 0.0, f"Cash went negative: ${pf.cash_usd:.4f}"


# ---- v2 rebalancing ----

def _ctx_full(funding, mark, spread_bps=2.0):
    """Context dict with bid/ask sides, as replay.py provides."""
    half = mark * spread_bps / 2 / 10_000
    return {
        "funding": funding, "mark": mark, "oracle": mark,
        "perp_bid": mark - half, "perp_ask": mark + half,
        "spot_bid": mark - half, "spot_ask": mark + half,
    }


def test_rebalance_tier_a_exact_math():
    """Hand-computed Tier-A transfer restores target leverage and respects cash floor."""
    # Entry: BTC at $60k, notional=$20k, 2x leverage
    # hl_margin=$10k, reserve=$3k, coin_qty=1/3
    pf = PaperPortfolio(cash_usd=100_000.0)
    cfg = CarryConfig(max_leverage_band=3.0, cash_floor_frac=0.02, target_leverage=2.0)
    open_position(pf, "BTC", 60_000.0, 20_000.0, cfg)

    # Simulate mark rising to $67.5k: lev = notional/hl_equity
    #   notional = (1/3) × 67500 = $22500
    #   perp_unrealized = (1/3) × (60000 - 67500) = -$2500
    #   hl_equity = 10000 - 2500 = $7500
    #   lev = 22500 / 7500 = 3.0 → exactly at band → no rebalance yet
    mark_at_band = 67_500.0
    pf.positions["BTC"].accrued_funding = 0.0
    ctx = {"BTC": _ctx_full(0.0, mark_at_band)}
    rebalance(pf, ctx, {"BTC": 0.20}, cfg, now_ts=0.0)
    assert pf.rebalance_topup_count == 0  # exactly at band, not above

    # Tiny increment above band: lev > 3.0
    mark_above = 68_000.0
    ctx = {"BTC": _ctx_full(0.0, mark_above)}
    cash_before = pf.cash_usd
    rebalance(pf, ctx, {"BTC": 0.20}, cfg, now_ts=1.0)
    assert pf.rebalance_topup_count == 1

    pos = pf.positions["BTC"]
    hl_eq_after = pos.hl_equity(mark_above)
    notional_after = pos.notional(mark_above)
    lev_after = notional_after / hl_eq_after
    # Leverage should be restored to (approximately) target
    assert lev_after <= cfg.max_leverage_band + 0.001, f"lev_after={lev_after:.4f}"
    # Cash decreased by transfer amount
    assert pf.cash_usd < cash_before
    # Cash floor respected: cash ≥ paper_capital_usd × cash_floor_frac
    cash_floor = cfg.paper_capital_usd * cfg.cash_floor_frac
    assert pf.cash_usd >= cash_floor - 0.01, f"Cash ${pf.cash_usd:.2f} breached floor ${cash_floor:.2f}"
    # Log entry present
    assert any("REBALANCE_TOPUP BTC" in e for e in pf.log)


def test_rebalance_tier_a_exact_transfer_amount():
    """Transfer = notional/target_leverage - hl_equity; resulting lev == target_leverage."""
    pf = PaperPortfolio(cash_usd=100_000.0)
    cfg = CarryConfig(max_leverage_band=3.0, cash_floor_frac=0.0, target_leverage=2.0)
    open_position(pf, "BTC", 60_000.0, 20_000.0, cfg)

    # Manually set hl_margin such that lev = 4.0 (clearly above band)
    pos = pf.positions["BTC"]
    mark = 80_000.0
    # notional = (1/3)×80000 ≈ 26666.67; perp_unrealized = (1/3)×(60000-80000) = -6666.67
    # hl_equity with hl_margin=10000: 10000 - 6666.67 = 3333.33; lev = 26666/3333 = 8.0
    ctx = {"BTC": _ctx_full(0.0, mark)}

    cash_before = pf.cash_usd
    hl_eq_before = pos.hl_equity(mark)
    target_eq = pos.notional(mark) / cfg.target_leverage
    expected_transfer = target_eq - hl_eq_before

    rebalance(pf, ctx, {"BTC": 0.20}, cfg, now_ts=0.0)

    actual_transfer = cash_before - pf.cash_usd
    assert abs(actual_transfer - expected_transfer) < 0.01, (
        f"Transfer {actual_transfer:.4f} ≠ expected {expected_transfer:.4f}"
    )
    hl_eq_after = pos.hl_equity(mark)
    lev_after = pos.notional(mark) / hl_eq_after
    assert abs(lev_after - cfg.target_leverage) < 0.001, f"lev_after={lev_after:.6f}"


def test_rebalance_tier_b_cash_starved():
    """When cash floor prevents Tier-A, Tier-B closes and reopens the position."""
    cfg = CarryConfig(
        max_leverage_band=3.0,
        cash_floor_frac=0.999,   # 99.9% of capital must stay as floor → Tier A transfer ≈ 0
        target_leverage=2.0,
        max_notional_per_symbol=20_000.0,
        max_total_notional_usd=40_000.0,
        paper_capital_usd=100_000.0,
    )
    pf = PaperPortfolio(cash_usd=100_000.0)
    open_position(pf, "BTC", 60_000.0, 20_000.0, cfg)

    # Move price to trigger rebalance (lev >> max_leverage_band)
    mark = 80_000.0
    ctx = {"BTC": _ctx_full(0.0, mark)}
    # Rich trailing → gate allows reopen
    trailing = {"BTC": 0.20}
    fees_before = pf.fees_total

    rebalance(pf, ctx, trailing, cfg, now_ts=0.0)

    assert pf.rebalance_recenter_count == 1, "Expected Tier-B recenter"
    # Fees should have been charged on close+reopen (4 legs)
    assert pf.fees_total > fees_before, "Tier-B must charge fees"
    assert pf.rebalance_fees_usd > 0
    # Log has REBALANCE_RECENTER
    assert any("REBALANCE_RECENTER BTC" in e for e in pf.log)
    # If reopened: leverage is at target; if not (cash still insufficient): flat
    if "BTC" in pf.positions:
        pos = pf.positions["BTC"]
        hl_eq = pos.hl_equity(mark)
        lev = pos.notional(mark) / hl_eq if hl_eq > 0 else float("inf")
        assert lev <= cfg.max_leverage_band + 0.01, f"Reopened position still above band: {lev:.2f}"


def test_halt_on_kill_true_stops_after_liquidation():
    """halt_on_kill=True (default): once kill fires, subsequent ticks are no-ops."""
    pf = PaperPortfolio(cash_usd=100_000.0)
    cfg = CarryConfig()  # halt_on_kill=True by default
    open_position(pf, "BTC", 60_000.0, 20_000.0, cfg)
    # Price doubles: liquidation fires
    tick(pf, {"BTC": _ctx(0.0, 120_000.0)}, {"BTC": 0.25}, cfg, now_ts=3_600)
    assert pf.killed is True
    # Subsequent tick with non-zero funding: portfolio must remain unchanged
    cash_before = pf.cash_usd
    fund_before = pf.accrued_funding_total
    tick(pf, {"BTC": _ctx(0.0001, 120_000.0)}, {"BTC": 0.25}, cfg, now_ts=7_200)
    assert pf.cash_usd == cash_before    # no funding/fee changes
    assert pf.accrued_funding_total == fund_before


def test_halt_on_kill_false_resumes_after_clear():
    """halt_on_kill=False: engine resumes after the kill flag is externally cleared."""
    pf = PaperPortfolio(cash_usd=100_000.0)
    cfg = CarryConfig(halt_on_kill=False)
    open_position(pf, "BTC", 60_000.0, 20_000.0, cfg)
    # Price doubles: liquidation fires
    tick(pf, {"BTC": _ctx(0.0, 120_000.0)}, {"BTC": 0.25}, cfg, now_ts=3_600)
    assert pf.killed is True
    # Simulate replay driver clearing kill + restoring cash
    pf.killed = False
    # Next tick at original price: gate is rich → should re-enter
    tick(pf, {"BTC": _ctx(0.0001, 60_000.0)}, {"BTC": 0.25}, cfg, now_ts=7_200)
    assert "BTC" in pf.positions, "Engine must re-enter after kill cleared with halt_on_kill=False"


def test_build_snapshot_shape():
    pf = PaperPortfolio(cash_usd=100000)
    tick(pf, {"BTC": _ctx(0.00002, 60000.0)}, {"BTC": 0.25, "ETH": 0.01}, CFG, now_ts=3600)
    from carry.engine import build_snapshot
    snap = build_snapshot(pf, {"BTC": _ctx(0.00002, 60000.0), "ETH": _ctx(0.0000001, 3000.0)},
                          {"BTC": 0.25, "ETH": 0.01}, CFG)
    assert snap["symbols"]["BTC"]["notional"] > 0      # opened (rich)
    assert snap["symbols"]["ETH"]["target"] == 0.0      # gated out (thin)
    assert "equity" in snap and "accrued_funding_total" in snap


# ---------------------------------------------------------------------------
# v3 — Symmetric resize (Phase 2A: frozen-notional fix)
# ---------------------------------------------------------------------------

def _scaled_ctx(mark: float, funding: float = 0.0001) -> dict:
    """Full bid/ask context for resize tests."""
    half = 0.0001   # 1bp half-spread
    return {
        "funding": funding, "mark": mark, "oracle": mark,
        "perp_bid": mark * (1 - half), "perp_ask": mark * (1 + half),
        "spot_bid": mark * (1 - half), "spot_ask": mark * (1 + half),
    }


def test_resize_up_fires_when_notional_below_target():
    """
    Regression for the frozen-notional bug.
    Open at trailing barely above hurdle → tiny notional.
    When trailing rises to rich, resize_up must bring notional to target.
    """
    cfg = CarryConfig(
        paper_capital_usd=100_000.0,
        max_notional_per_symbol=20_000.0,
        max_total_notional_usd=40_000.0,
        resize_tolerance=0.25,
        target_leverage=2.0, reserve_frac=0.15,
    )
    pf = PaperPortfolio(cash_usd=100_000.0)
    mark = 50_000.0

    # Open at just-above-hurdle trailing (6.1%) → tiny notional
    trailing_open = 0.061
    tgt_open = target_notional(trailing_open, cfg)  # small fraction of max
    open_position(pf, "BTC", mark, tgt_open, cfg)
    notional_before = pf.positions["BTC"].coin_qty * mark
    assert notional_before < 200, f"Expected tiny open, got ${notional_before:.0f}"

    # Now trailing is rich (25%) → tgt_new >> current
    trailing_rich = 0.25
    tgt_new = target_notional(trailing_rich, cfg)    # should be max_notional_per_symbol
    ctx = _scaled_ctx(mark)

    result = resize_position(pf, "BTC", tgt_new, mark, cfg, {"BTC": mark},
                             fill_perp_bid=ctx["perp_bid"], fill_spot_ask=ctx["spot_ask"],
                             fill_perp_ask=ctx["perp_ask"], fill_spot_bid=ctx["spot_bid"])

    assert result == "resize_up"
    assert pf.resize_up_count == 1
    notional_after = pf.positions["BTC"].coin_qty * mark
    assert abs(notional_after - tgt_new) / tgt_new < 0.01, (
        f"After resize_up, notional ${notional_after:.0f} should be ≈ ${tgt_new:.0f}"
    )


def test_resize_up_accounting_invariant():
    """
    After resize_up, the accounting invariant must hold:
    equity = capital + realized_pnl + sum(open_pnl).
    """
    cfg = CarryConfig(
        paper_capital_usd=100_000.0,
        max_notional_per_symbol=20_000.0,
        max_total_notional_usd=40_000.0,
        resize_tolerance=0.25,
        target_leverage=2.0, reserve_frac=0.15,
    )
    pf = PaperPortfolio(cash_usd=100_000.0)
    mark = 50_000.0

    open_position(pf, "BTC", mark, 500.0, cfg)   # open at tiny notional

    marks = {"BTC": mark}
    tgt_new = 20_000.0
    ctx = _scaled_ctx(mark)
    resize_position(pf, "BTC", tgt_new, mark, cfg, marks,
                    fill_perp_bid=ctx["perp_bid"], fill_spot_ask=ctx["spot_ask"],
                    fill_perp_ask=ctx["perp_ask"], fill_spot_bid=ctx["spot_bid"])

    pos = pf.positions["BTC"]
    # equity() = cash + coin_qty*entry_perp + hl_margin + accrued_funding + reserve
    equity = pf.equity(marks)
    open_pnl = (pos.accrued_funding
                + pos.coin_qty * (pos.entry_perp - mark)
                + pos.coin_qty * (mark - pos.entry_spot)
                - pos.fees_paid)
    expected = cfg.paper_capital_usd + pf.realized_pnl + open_pnl
    assert abs(equity - expected) < 0.01, f"Invariant violated: actual={equity:.4f} expected={expected:.4f}"


def test_resize_down_fires_when_notional_above_target():
    """
    Open at full notional ($20k). Trailing drops: target shrinks to $5k.
    resize_down must reduce position proportionally.
    """
    cfg = CarryConfig(
        paper_capital_usd=100_000.0,
        max_notional_per_symbol=20_000.0,
        max_total_notional_usd=40_000.0,
        resize_tolerance=0.25,
        target_leverage=2.0, reserve_frac=0.15,
    )
    pf = PaperPortfolio(cash_usd=100_000.0)
    mark = 50_000.0

    open_position(pf, "BTC", mark, 20_000.0, cfg)
    notional_before = pf.positions["BTC"].coin_qty * mark

    tgt_new = 5_000.0   # gate wants to shrink the position
    ctx = _scaled_ctx(mark)

    result = resize_position(pf, "BTC", tgt_new, mark, cfg, {"BTC": mark},
                             fill_perp_bid=ctx["perp_bid"], fill_spot_ask=ctx["spot_ask"],
                             fill_perp_ask=ctx["perp_ask"], fill_spot_bid=ctx["spot_bid"])

    assert result == "resize_down"
    assert pf.resize_down_count == 1
    notional_after = pf.positions["BTC"].coin_qty * mark
    assert notional_after < notional_before
    # Should land close to the target
    assert abs(notional_after - tgt_new) / tgt_new < 0.01, (
        f"After resize_down, notional ${notional_after:.0f} should be ≈ ${tgt_new:.0f}"
    )


def test_resize_down_accounting_invariant():
    """After resize_down the accounting invariant holds (equity = capital + pnl)."""
    cfg = CarryConfig(
        paper_capital_usd=100_000.0,
        max_notional_per_symbol=20_000.0,
        max_total_notional_usd=40_000.0,
        resize_tolerance=0.25,
        target_leverage=2.0, reserve_frac=0.15,
    )
    pf = PaperPortfolio(cash_usd=100_000.0)
    mark = 50_000.0

    open_position(pf, "BTC", mark, 20_000.0, cfg)
    # Accrue some funding so pos.accrued_funding > 0
    from carry.engine import accrue_funding
    accrue_funding(pf.positions["BTC"], 0.00002, mark, 100.0)
    pf.accrued_funding_total += pf.positions["BTC"].accrued_funding

    marks = {"BTC": mark}
    tgt_new = 5_000.0
    ctx = _scaled_ctx(mark)
    resize_position(pf, "BTC", tgt_new, mark, cfg, marks,
                    fill_perp_bid=ctx["perp_bid"], fill_spot_ask=ctx["spot_ask"],
                    fill_perp_ask=ctx["perp_ask"], fill_spot_bid=ctx["spot_bid"])

    pos = pf.positions["BTC"]
    equity = pf.equity(marks)
    open_pnl = (pos.accrued_funding
                + pos.coin_qty * (pos.entry_perp - mark)
                + pos.coin_qty * (mark - pos.entry_spot)
                - pos.fees_paid)
    expected = cfg.paper_capital_usd + pf.realized_pnl + open_pnl
    assert abs(equity - expected) < 0.01, f"Invariant violated: actual={equity:.4f} expected={expected:.4f}"


def test_tick_resizes_position_toward_target():
    """
    tick() integration: open at tiny notional, then call tick() with rich trailing.
    Position must be resized up within the tick (no separate call needed).
    """
    cfg = CarryConfig(
        paper_capital_usd=100_000.0,
        max_notional_per_symbol=20_000.0,
        max_total_notional_usd=40_000.0,
        resize_tolerance=0.25,
        target_leverage=2.0, reserve_frac=0.15,
        min_funding_hurdle_ann=0.06,
        rich_funding_ann=0.20,
    )
    pf = PaperPortfolio(cash_usd=100_000.0)
    mark = 50_000.0

    # Open at tiny notional (just above hurdle)
    tgt_small = target_notional(0.061, cfg)
    open_position(pf, "BTC", mark, tgt_small, cfg)
    notional_after_open = pf.positions["BTC"].coin_qty * mark

    ctx = _scaled_ctx(mark, funding=0.00003)   # rich instantaneous rate
    pf.last_tick_ts = 0.0  # first tick

    # One tick with 25% trailing (well above rich band)
    tick(pf, {"BTC": ctx}, {"BTC": 0.25}, cfg, now_ts=3_600)

    notional_after_tick = pf.positions["BTC"].coin_qty * mark
    assert notional_after_tick > notional_after_open, (
        "tick() must upsize position when trailing is rich"
    )
    assert pf.resize_up_count >= 1
