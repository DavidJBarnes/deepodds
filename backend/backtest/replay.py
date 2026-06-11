"""
Historical replay driver for the carry engine.

Drives carry.engine.tick() over a pre-assembled hourly DataFrame, producing
a ReplayResult with full metrics. The engine code is NOT modified — only the
market context is built from historical data instead of live API calls.

Usage:
    from backtest.data_ingest import load_all
    from backtest.scaling import scaled_config
    from backtest.replay import run_replay

    frames = load_all()
    cfg = scaled_config(8_000)
    result = run_replay(frames, cfg, start="2024-01-01", end="2026-05-31")
    result.print_summary()
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dataclasses import replace as _dc_replace

import pandas as pd

from carry.config import CarryConfig
from carry.engine import build_snapshot, close_position, tick
from carry.models import PaperPortfolio

logger = logging.getLogger("backtest.replay")

PERIODS_PER_YEAR = 24 * 365  # hourly, matching engine convention
RISK_FREE_ANNUAL = 0.04       # 4% risk-free rate for Sharpe calculation


@dataclass
class ReplayResult:
    """Metrics from a single historical replay run."""
    portfolio: PaperPortfolio
    daily_equity: pd.Series            # index=date, values=equity USD
    capital: float                     # initial capital (paper_capital_usd)

    # Derived metrics (computed by run_replay, stored here for reporting)
    net_pnl: float = 0.0
    annualized_roi: float = 0.0        # net_pnl / capital / years
    sharpe: float = 0.0                # annualized Sharpe on daily returns (rf=4%)
    max_drawdown: float = 0.0          # largest peak-to-trough on equity curve
    pct_hours_deployed: float = 0.0    # fraction of hours with ≥1 open position
    round_trips: int = 0               # completed open+close pairs (per symbol)
    total_fees: float = 0.0
    gross_funding_collected: float = 0.0
    gross_negative_funding_paid: float = 0.0
    liquidation_count: int = 0
    kill_switch_fired: bool = False     # True if any kill event fired (even after resume)
    worst_trade_pnl: float = 0.0       # worst single closed-trade P&L (from log)

    # Rebalancing metrics (v2)
    rebalance_topup_count: int = 0     # Tier-A fee-free cash transfers
    rebalance_recenter_count: int = 0  # Tier-B close+reopen events
    rebalance_fees_usd: float = 0.0    # fees from Tier-B only
    kill_events: int = 0               # number of kill-switch trips (cleared + resumed each time)

    # Calendar-year breakdown rows, filled by run_replay
    yearly: list[dict] = field(default_factory=list)

    def print_summary(self) -> None:
        """Print a human-readable summary of replay metrics."""
        print(f"  Net P&L:          ${self.net_pnl:,.2f}")
        print(f"  Annualized ROI:   {self.annualized_roi*100:.2f}%")
        print(f"  Sharpe (rf=4%):   {self.sharpe:.3f}")
        print(f"  Max drawdown:     {self.max_drawdown*100:.2f}%")
        print(f"  % time deployed:  {self.pct_hours_deployed*100:.1f}%")
        print(f"  Round trips:      {self.round_trips}")
        print(f"  Total fees:       ${self.total_fees:.2f}")
        print(f"  Funding coll.:    ${self.gross_funding_collected:.2f}")
        print(f"  Funding paid:     ${self.gross_negative_funding_paid:.2f}")
        print(f"  Liquidations:     {self.liquidation_count}")
        print(f"  Kill-switch:      {self.kill_switch_fired}")
        print(f"  Worst trade P&L:  ${self.worst_trade_pnl:.2f}")


def _build_hourly_index(df_by_symbol: dict[str, pd.DataFrame],
                        start: str | datetime | None,
                        end: str | datetime | None) -> pd.DatetimeIndex:
    """Compute the union of all hourly timestamps across symbols, clamped to [start, end]."""
    all_ts: set = set()
    for df in df_by_symbol.values():
        all_ts.update(df["ts"].tolist())
    idx = pd.DatetimeIndex(sorted(all_ts))
    if start:
        start_ts = pd.Timestamp(start, tz="UTC")
        idx = idx[idx >= start_ts]
    if end:
        end_ts = pd.Timestamp(end, tz="UTC")
        idx = idx[idx <= end_ts]
    return idx


def _precompute_trailing(df_by_symbol: dict[str, pd.DataFrame],
                         cfg: CarryConfig) -> dict[str, pd.Series]:
    """
    Precompute the trailing annualized funding series for each symbol.

    Vectorized rolling mean over cfg.trailing_window_hours, × PERIODS_PER_YEAR.
    Uses min_periods=1 (non-None from the very first hour), matching the live
    trailing_funding_ann() behavior of returning None only on empty data.

    Called once per config; indexed by ts for O(1) lookup per tick.
    """
    result: dict[str, pd.Series] = {}
    for coin, df in df_by_symbol.items():
        s = df.set_index("ts")["funding_hourly"]
        trailing = s.rolling(cfg.trailing_window_hours, min_periods=1).mean() * PERIODS_PER_YEAR
        result[coin] = trailing
    return result


def _build_ctx(ts: pd.Timestamp, df_by_symbol: dict[str, pd.DataFrame],
               price_idx: dict[str, pd.DataFrame],
               cfg: CarryConfig) -> dict[str, dict]:
    """
    Build the per-symbol context dict for engine.tick(), matching execution.market_ctx() shape.

    Fills are modeled with symmetric half-spreads:
      perp_bid = perp_close × (1 − perp_half_spread)
      perp_ask = perp_close × (1 + perp_half_spread)
      spot_bid = spot_close × (1 − spot_half_spread)
      spot_ask = spot_close × (1 + spot_half_spread)

    The engine's open_position() short-sells the perp at perp_bid and buys spot at spot_ask.
    The engine's close_position() buys back the perp at perp_ask and sells spot at spot_bid.
    """
    perp_half = cfg.spot_spread_bps / 2 / 10_000   # reuse spot_spread_bps as modeled spread
    spot_half = cfg.spot_spread_bps / 2 / 10_000

    ctx: dict[str, dict] = {}
    for coin, idx in price_idx.items():
        row = idx.get(ts)
        if row is None:
            continue
        perp = row["perp_close"]
        spot = row["spot_close"]
        funding = row["funding_hourly"]
        ctx[coin] = {
            "funding": funding,
            "mark": perp,
            "oracle": spot,
            "perp_bid": perp * (1 - perp_half),
            "perp_ask": perp * (1 + perp_half),
            "spot_bid": spot * (1 - spot_half),
            "spot_ask": spot * (1 + spot_half),
        }
    return ctx


def _parse_round_trips_and_worst(log: list[str]) -> tuple[int, float]:
    """Extract round trip count and worst single closed-trade P&L from engine log."""
    round_trips = 0
    worst = 0.0
    for line in log:
        if line.startswith("CLOSE"):
            round_trips += 1
            # parse "pnl=$-12.34" from log line
            for part in line.split():
                if part.startswith("pnl=$"):
                    try:
                        pnl = float(part[5:])
                        if pnl < worst:
                            worst = pnl
                    except ValueError:
                        pass
    return round_trips, worst


def _max_drawdown(equity: pd.Series) -> float:
    """Largest peak-to-trough ratio on the equity curve (negative number)."""
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(dd.min())


def _sharpe(equity: pd.Series, rf_annual: float = RISK_FREE_ANNUAL) -> float:
    """Annualized Sharpe ratio on daily equity returns."""
    if len(equity) < 2:
        return float("nan")
    daily_ret = equity.pct_change().dropna()
    if daily_ret.std() == 0:
        return float("nan")
    rf_daily = rf_annual / 365
    excess = daily_ret - rf_daily
    return float(excess.mean() / excess.std() * (365 ** 0.5))


def _yearly_breakdown(daily_equity: pd.Series, pf: PaperPortfolio,
                      capital: float,
                      year_stats: dict[int, dict] | None = None) -> list[dict]:
    """Per-calendar-year ROI / drawdown from the daily equity series.

    year_stats is the per-year accumulator built in run_replay; merged in when
    present so the yearly rows include funding, fees, and rebalance counts.
    """
    result = []
    for yr in sorted(daily_equity.index.year.unique()):
        mask = daily_equity.index.year == yr
        sub = daily_equity[mask]
        if len(sub) < 2:
            continue
        start_eq = float(sub.iloc[0])
        end_eq = float(sub.iloc[-1])
        roi = (end_eq - start_eq) / capital
        mdd = _max_drawdown(sub)
        ys = (year_stats or {}).get(yr, {})
        total = ys.get("total", 1)
        row = {
            "year": yr,
            "roi": roi,
            "max_drawdown": mdd,
            "start_equity": start_eq,
            "end_equity": end_eq,
            "pct_deployed": ys.get("deployed", 0) / total if total else 0.0,
            "round_trips": ys.get("round_trips", 0),
            "topups": ys.get("topups", 0),
            "recenters": ys.get("recenters", 0),
            "funding": ys.get("funding", 0.0),
            "fees": ys.get("fees", 0.0),
        }
        result.append(row)
    return result


def _build_price_index(df_by_symbol: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """
    Build a fast timestamp → row lookup for price data.
    Much faster than iterrows() per tick.
    """
    price_idx: dict[str, dict] = {}
    for coin, df in df_by_symbol.items():
        sub = df.copy()
        sub["ts"] = pd.to_datetime(sub["ts"], utc=True)
        # Use vectorized dict construction instead of slow iterrows
        records = sub.to_dict("records")
        price_idx[coin] = {r["ts"]: r for r in records}
    return price_idx


def run_replay(df_by_symbol: dict[str, pd.DataFrame],
               cfg: CarryConfig,
               start: str | datetime | None = None,
               end: str | datetime | None = None,
               _price_idx: dict | None = None,
               _trailing_cache: dict | None = None) -> ReplayResult:
    """
    Drive carry.engine.tick() over hourly historical data.

    Args:
        df_by_symbol: {coin: DataFrame(ts, funding_hourly, perp_close, spot_close)}
        cfg: CarryConfig (use scaling.scaled_config() for small capital)
        start: inclusive start timestamp (UTC string or datetime)
        end: inclusive end timestamp (UTC string or datetime)
        _price_idx: pre-built price index (pass from sweep to avoid rebuilding per config)
        _trailing_cache: pre-built trailing series cache keyed by (coin, window)

    Returns:
        ReplayResult with all metrics computed.
    """
    # Backtest always runs with halt_on_kill=False so kill events can be counted
    # and measured without halting the simulation permanently.
    cfg = _dc_replace(cfg, halt_on_kill=False)

    # Build time index
    hourly_idx = _build_hourly_index(df_by_symbol, start, end)
    if len(hourly_idx) == 0:
        raise ValueError("No hourly timestamps in range")

    # Use pre-built price index if provided, else build it
    price_idx = _price_idx if _price_idx is not None else _build_price_index(df_by_symbol)

    # Use pre-built trailing series if provided (keyed by (coin, window))
    if _trailing_cache is not None:
        trailing_series = {
            coin: _trailing_cache[(coin, cfg.trailing_window_hours)]
            for coin in df_by_symbol
            if (coin, cfg.trailing_window_hours) in _trailing_cache
        }
    else:
        # Pre-compute trailing series (vectorized) — O(N×W) once, not per tick
        trailing_series = _precompute_trailing(df_by_symbol, cfg)

    # Initialize portfolio
    pf = PaperPortfolio(cash_usd=cfg.paper_capital_usd)

    daily_equity: dict[pd.Timestamp, float] = {}
    deployed_hours = 0
    total_hours = 0
    tick_count = 0
    kill_events = 0
    ever_killed = False

    # Per-year tracking: funding, fees, rebalance counts, deployed hours, round trips
    year_stats: dict[int, dict] = {}

    for ts in hourly_idx:
        ctx = _build_ctx(ts, df_by_symbol, price_idx, cfg)
        if not ctx:
            continue

        # Look up pre-computed trailing value per coin
        trailing: dict[str, float | None] = {}
        for coin in cfg.symbols:
            series = trailing_series.get(coin)
            if series is None or ts not in series.index:
                trailing[coin] = None
            else:
                val = series[ts]
                trailing[coin] = None if pd.isna(val) else float(val)

        marks = {s: c["mark"] for s, c in ctx.items() if c.get("mark")}

        # Warn on tick gaps > 24h. The engine clamps to 24h internally, so
        # processing continues safely; missing hours are rare data outages.
        if pf.last_tick_ts > 0:
            gap_hours = (ts.timestamp() - pf.last_tick_ts) / 3600
            if gap_hours > 24.0:
                logger.debug("Tick gap %.1fh at %s — engine clamps to 24h", gap_hours, ts)

        # Snapshot pre-tick state for per-year delta tracking
        fund_before = pf.accrued_funding_total
        fees_before = pf.fees_total
        topup_before = pf.rebalance_topup_count
        recenter_before = pf.rebalance_recenter_count
        log_len_before = len(pf.log)

        tick(pf, ctx, trailing, cfg, ts.timestamp())

        # Kill-event handling: force-close ghost positions, increment counter, clear flag.
        # halt_on_kill=False means the engine does not halt permanently; the replay clears
        # pf.killed between ticks so measurement continues after each kill event.
        if pf.killed and pf.positions:
            for sym in list(pf.positions.keys()):
                c = ctx.get(sym)
                if c and c.get("mark"):
                    close_position(pf, sym, c["mark"], cfg, "kill-switch unwind",
                                   exit_perp=c.get("perp_ask"), exit_spot=c.get("spot_bid"))
                else:
                    pf.positions.pop(sym, None)
        if pf.killed:
            kill_events += 1
            ever_killed = True
            pf.killed = False  # clear so next tick runs normally

        # Assert no negative cash (Task 4 regression guard)
        assert pf.cash_usd >= -0.01, f"Negative cash ${pf.cash_usd:.4f} at {ts}"

        total_hours += 1
        if pf.positions and not pf.killed:
            deployed_hours += 1

        # Per-year accumulation
        yr = ts.year
        if yr not in year_stats:
            year_stats[yr] = {
                "funding": 0.0, "fees": 0.0,
                "topups": 0, "recenters": 0,
                "deployed": 0, "total": 0, "round_trips": 0,
            }
        ys = year_stats[yr]
        ys["funding"] += pf.accrued_funding_total - fund_before
        ys["fees"]    += pf.fees_total - fees_before
        ys["topups"]  += pf.rebalance_topup_count - topup_before
        ys["recenters"] += pf.rebalance_recenter_count - recenter_before
        ys["total"]   += 1
        if pf.positions and not pf.killed:
            ys["deployed"] += 1
        new_entries = pf.log[log_len_before:]
        ys["round_trips"] += sum(1 for e in new_entries if e.startswith("CLOSE"))

        tick_count += 1
        if tick_count % 24 == 0:
            eq = pf.equity(marks)
            daily_equity[ts] = eq

    # Final equity snapshot
    if hourly_idx[-1] not in daily_equity:
        final_marks = {coin: price_idx[coin][hourly_idx[-1]]["perp_close"]
                       for coin in cfg.symbols if hourly_idx[-1] in price_idx.get(coin, {})}
        daily_equity[hourly_idx[-1]] = pf.equity(final_marks)

    equity_series = pd.Series(daily_equity).sort_index()
    equity_series.index = pd.DatetimeIndex(equity_series.index)

    final_equity = float(equity_series.iloc[-1]) if len(equity_series) else cfg.paper_capital_usd

    gross_funding_collected = max(0.0, pf.accrued_funding_total)
    gross_negative_paid = abs(min(0.0, pf.accrued_funding_total))

    years = len(hourly_idx) / PERIODS_PER_YEAR
    net_pnl = final_equity - cfg.paper_capital_usd
    roi = net_pnl / cfg.paper_capital_usd / years if years > 0 else 0.0

    round_trips, worst_trade = _parse_round_trips_and_worst(pf.log)
    liquidations = sum(1 for line in pf.log if "LIQUIDATION" in line)

    result = ReplayResult(
        portfolio=pf,
        daily_equity=equity_series,
        capital=cfg.paper_capital_usd,
        net_pnl=net_pnl,
        annualized_roi=roi,
        sharpe=_sharpe(equity_series),
        max_drawdown=_max_drawdown(equity_series) if len(equity_series) >= 2 else 0.0,
        pct_hours_deployed=deployed_hours / total_hours if total_hours else 0.0,
        round_trips=round_trips,
        total_fees=pf.fees_total,
        gross_funding_collected=gross_funding_collected,
        gross_negative_funding_paid=gross_negative_paid,
        liquidation_count=liquidations,
        kill_switch_fired=ever_killed,
        worst_trade_pnl=worst_trade,
        rebalance_topup_count=pf.rebalance_topup_count,
        rebalance_recenter_count=pf.rebalance_recenter_count,
        rebalance_fees_usd=pf.rebalance_fees_usd,
        kill_events=kill_events,
    )
    result.yearly = _yearly_breakdown(equity_series, pf, cfg.paper_capital_usd, year_stats)
    return result


def main() -> None:
    """Run a single replay (production defaults, $8k capital, full period) and print summary."""
    import argparse
    from backtest.data_ingest import load_all
    from backtest.scaling import scaled_config

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    ap = argparse.ArgumentParser(description="Run a single carry strategy replay")
    ap.add_argument("--capital", type=float, default=8_000.0)
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    frames = load_all()
    cfg = scaled_config(args.capital)
    print(f"\nRunning replay: ${args.capital:,.0f} capital, {args.start} → {args.end or 'latest'}")
    result = run_replay(frames, cfg, start=args.start, end=args.end)
    result.print_summary()


if __name__ == "__main__":
    main()
