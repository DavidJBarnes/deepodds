"""
Generate REPORT.md for the carry strategy historical backtest.

Reads sweep results from backtest/results/sweep_results.csv and runs the
production-defaults replay to produce the full equity curve and per-year table.
Writes REPORT.md and REPORT_equity.png alongside this file.

Usage:
    cd backend
    uv run python -m backtest.report
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # headless
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

from backtest.data_ingest import compare_hl_vs_binance, load_all
from backtest.replay import run_replay
from backtest.scaling import TOTAL_NOTIONAL_RATIO, PER_SYMBOL_NOTIONAL_RATIO, scaled_config
from backtest.sweep import PROD_DEFAULTS, RESULTS_CSV, SELECTION_END, SELECTION_START, VALIDATION_START

logger = logging.getLogger("backtest.report")

REPORT_DIR = Path(__file__).parent
REPORT_MD   = REPORT_DIR / "REPORT.md"
EQUITY_PNG  = REPORT_DIR / "REPORT_equity.png"

# Kill criteria (evaluated mechanically — no editorializing)
KC1_ROI_THRESHOLD  = 0.05   # ≥ 5% annualized ROI after all costs
KC3_DD_THRESHOLD   = -0.10  # ≤ 10% max drawdown per calendar year
KC4_FEE_RATIO_CAP  = 0.25   # total fees ≤ 25% of gross funding collected


def _equity_chart(prod_full: "ReplayResult", out_path: Path) -> None:
    """
    Equity curve for production defaults, full period, $8k.
    Top panel: equity (strategy vs flat cash).
    Bottom panel: % of hours deployed.
    """
    eq = prod_full.daily_equity
    if eq.empty:
        logger.warning("Empty equity series — skipping chart")
        return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle("Carry Strategy — Production Defaults ($8k, 2x leverage, 7d trailing)", fontsize=13)

    # Top: equity
    ax1.plot(eq.index, eq.values, label="Strategy equity", lw=1.5, color="steelblue")
    ax1.axhline(prod_full.capital, color="gray", lw=0.8, ls="--", label="Initial capital")
    ax1.set_ylabel("Portfolio equity (USD)")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=6))

    # Shade validation period
    val_start = pd.Timestamp(VALIDATION_START, tz="UTC")
    ax1.axvspan(val_start, eq.index[-1], alpha=0.08, color="green", label="Validation period")
    ax1.legend(loc="upper left", fontsize=9)

    # Bottom: drawdown
    peak = eq.cummax()
    dd = (eq - peak) / peak * 100
    ax2.fill_between(dd.index, dd.values, 0, color="tomato", alpha=0.6)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Date")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=6))

    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved equity chart to %s", out_path)


def _fmt_pct(v: float) -> str:
    return f"{v*100:.2f}%"


def _fmt_dollar(v: float) -> str:
    return f"${v:,.2f}"


def generate_report() -> None:
    """Run the production-defaults replay and write REPORT.md + equity PNG."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print("=== Carry Backtest — Generating Report ===\n")

    frames = load_all()

    # Production defaults at $8k — full period
    prod_cfg_8k = scaled_config(8_000.0, **PROD_DEFAULTS)
    print("Running production-defaults replay ($8k, full period)...")
    prod_full = run_replay(frames, prod_cfg_8k)

    # Production defaults at $8k — validation window only
    print("Running production-defaults replay ($8k, validation window)...")
    prod_val = run_replay(frames, prod_cfg_8k, start=VALIDATION_START)

    # Production defaults at $8k — cost sensitivity (fees + spreads doubled)
    print("Running cost-sensitivity replay ($8k, doubled fees)...")
    prod_costly_cfg = scaled_config(
        8_000.0, **PROD_DEFAULTS, taker_fee_frac=0.0008, spot_spread_bps=4.0
    )
    prod_costly = run_replay(frames, prod_costly_cfg, start=VALIDATION_START)

    # HL cross-check
    print("Computing HL vs Binance funding comparison...")
    hl_comp = compare_hl_vs_binance()

    # Read sweep results if available
    sweep_df = None
    if RESULTS_CSV.exists():
        sweep_df = pd.read_csv(RESULTS_CSV)

    # Equity chart
    _equity_chart(prod_full, EQUITY_PNG)

    # --- Kill criteria evaluation ---
    kc1 = prod_val.annualized_roi >= KC1_ROI_THRESHOLD
    kc2 = prod_full.liquidation_count == 0 and not prod_full.kill_switch_fired
    kc3_by_year = {yr["year"]: yr["max_drawdown"] >= KC3_DD_THRESHOLD
                   for yr in prod_full.yearly}
    kc3 = all(kc3_by_year.values())
    fee_ratio = (prod_full.total_fees / prod_full.gross_funding_collected
                 if prod_full.gross_funding_collected > 0 else float("inf"))
    kc4 = fee_ratio <= KC4_FEE_RATIO_CAP

    # --- Build report lines ---
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    a = lines.append

    a("# Carry Strategy Backtest Report")
    a(f"\n_Generated: {now_utc}_")
    a("\n---\n")

    # 1. Data provenance
    a("## 1. Data Provenance\n")
    for coin, df in frames.items():
        a(f"**{coin}** — {len(df):,} hourly rows  "
          f"[{df['ts'].iloc[0].date()} → {df['ts'].iloc[-1].date()}]")
    a("")
    a("| Source | Purpose | Coverage |")
    a("|--------|---------|----------|")
    a("| Binance Vision bulk archives | Funding rates (8h settlements) + 1h perp klines | 2020-01 → last complete month |")
    a("| Binance Vision spot archives | 1h spot klines | 2020-01 → last complete month |")
    a("| Hyperliquid info API | Funding cross-check (hourly) | 2023-07 → present |")
    a("| Bybit v5 REST | Funding fallback (if Binance Vision unreachable) | — |")
    a("")
    a("**Funding unit-conversion verification:**  ")
    a("Binance settles funding every 8 hours. The engine's `accrue_funding()` expects a per-hour rate.  ")
    a("Conversion: `funding_hourly = funding_rate_8h / 8.0`  ")
    a("Proof: constant 0.01%/8h rate → hourly = 0.0001/8 = 0.0000125 → annualized = 0.0000125 × 8760 = **10.95%**  ")
    a("(See `test_backtest_ingest.py::test_funding_unit_conversion` for the enforced invariant.)")
    a("")

    # Gap counts
    a("**Gap counts (price data):**")
    for coin, df in frames.items():
        expected_hours = (df["ts"].iloc[-1] - df["ts"].iloc[0]).total_seconds() / 3600 + 1
        actual = len(df)
        gaps = max(0, int(expected_hours) - actual)
        a(f"  - {coin}: {gaps} hours dropped (missing price data)")
    a("")

    # 2. Per-calendar-year table
    a("## 2. Per-Calendar-Year Performance (Production Defaults, $8k)\n")
    a("_Config: hurdle=6%, rich=20%, trailing=168h (7d), exit=0%, leverage=2x_\n")
    a("| Year | Ann. ROI | Max Drawdown | Start Equity | End Equity |")
    a("|------|----------|-------------|--------------|------------|")
    for yr_row in prod_full.yearly:
        a(f"| {yr_row['year']} | {yr_row['roi']*100:.2f}% | "
          f"{yr_row['max_drawdown']*100:.2f}% | "
          f"${yr_row['start_equity']:,.2f} | ${yr_row['end_equity']:,.2f} |")
    a("")
    a(f"**Full period:** Net P&L={_fmt_dollar(prod_full.net_pnl)}  "
      f"Ann. ROI={_fmt_pct(prod_full.annualized_roi)}  "
      f"Sharpe={prod_full.sharpe:.3f}  "
      f"MaxDD={_fmt_pct(prod_full.max_drawdown)}  "
      f"Fees={_fmt_dollar(prod_full.total_fees)}  "
      f"Funding collected={_fmt_dollar(prod_full.gross_funding_collected)}  "
      f"Funding paid={_fmt_dollar(prod_full.gross_negative_funding_paid)}  "
      f"Round trips={prod_full.round_trips}  "
      f"% deployed={prod_full.pct_hours_deployed*100:.1f}%")
    a("")

    # 3. Walk-forward results
    a("## 3. Walk-Forward Results\n")
    a("**Selection window:** 2020-01-01 → 2023-12-31 (in-sample only — used to rank configs)")
    a("**Validation window:** 2024-01-01 → present (headline numbers — used for kill criteria)\n")

    if sweep_df is not None:
        # Selection top-10 by ROI (qualified only)
        sel = sweep_df[sweep_df["window"] == "selection"].copy()
        sel = sel[(sel["liquidations"] == 0) & (sel["kill_switch"] == False)]
        sel_8k = sel[sel["capital"] == 8000].sort_values("roi_ann", ascending=False).head(10)
        if not sel_8k.empty:
            a("### Top 10 configs (selection window, $8k, qualified)\n")
            a("| Hurdle | Rich | Trail(h) | Exit | Ann.ROI | Sharpe | MaxDD | Deploy% |")
            a("|--------|------|----------|------|---------|--------|-------|---------|")
            for _, r in sel_8k.iterrows():
                a(f"| {r['hurdle']:.0%} | {r['rich']:.0%} | {r['trail_h']:.0f} | {r['exit']:.0%} | "
                  f"{r['roi_ann']:.2f}% | {r['sharpe']:.3f} | {r['max_dd']:.2f}% | {r['pct_deployed']:.1f}% |")
            a("")

        # Validation results
        val = sweep_df[sweep_df["window"].isin(["validation", "prod_default"])].copy()
        val_8k = val[val["capital"] == 8000].sort_values("roi_ann", ascending=False)
        if not val_8k.empty:
            a("### Validation window results ($8k)\n")
            a("| Config | Hurdle | Rich | Trail(h) | Exit | Ann.ROI | Sharpe | MaxDD | Liquidations |")
            a("|--------|--------|------|----------|------|---------|--------|-------|-------------|")
            for _, r in val_8k.iterrows():
                a(f"| {r['window']} | {r['hurdle']:.0%} | {r['rich']:.0%} | {r['trail_h']:.0f} | "
                  f"{r['exit']:.0%} | {r['roi_ann']:.2f}% | {r['sharpe']:.3f} | "
                  f"{r['max_dd']:.2f}% | {r['liquidations']:.0f} |")
            a("")
    else:
        a("_(Sweep results not found — run `uv run python -m backtest.sweep` first)_\n")

    # 4. Cost sensitivity
    a("## 4. Cost Sensitivity\n")
    a("Production defaults ($8k), validation window, with all fees + spreads doubled:")
    a(f"  - Baseline ROI: **{prod_val.annualized_roi*100:.2f}%**")
    a(f"  - Doubled-cost ROI: **{prod_costly.annualized_roi*100:.2f}%**")
    roi_delta = prod_costly.annualized_roi - prod_val.annualized_roi
    a(f"  - ROI delta: **{roi_delta*100:+.2f}pp**")
    a(f"  - Baseline fees: ${prod_val.total_fees:.2f}  |  Doubled-cost fees: ${prod_costly.total_fees:.2f}")
    a("")

    # 5. HL vs Binance comparison
    a("## 5. Binance vs Hyperliquid Funding Comparison\n")
    if not hl_comp.empty:
        a("Mean annualized funding per calendar quarter (decimal → %):\n")
        a("| Quarter | Coin | Binance Ann | HL Ann | Diff (pp) |")
        a("|---------|------|------------|--------|-----------|")
        for _, r in hl_comp.iterrows():
            a(f"| {r['quarter']} | {r['coin']} | {r['binance_ann']*100:.2f}% | "
              f"{r['hl_ann']*100:.2f}% | {r['diff_pp']:+.2f}pp |")
        a("")
        avg_diff = hl_comp["diff_pp"].mean()
        a(f"**Venue transferability:** HL and Binance show mean funding difference of {avg_diff:+.2f}pp "
          f"across overlapping quarters. "
          f"{'HL funding is higher, suggesting Binance history understates potential HL income.' if avg_diff > 0 else 'Binance history overstates expected HL income — apply a discount when projecting HL returns.'} "
          f"Quarterly variance is {'moderate' if hl_comp['diff_pp'].abs().max() < 5 else 'substantial'}, "
          f"so Binance-derived conclusions should be treated as approximate for HL-specific deployments.")
    else:
        a("_(HL funding data unavailable — cross-check skipped)_")
    a("")

    # 6. Equity chart reference
    a("## 6. Equity Curve\n")
    a("Production defaults ($8k), full period 2020 → present.\n")
    if EQUITY_PNG.exists():
        a(f"![Equity curve](REPORT_equity.png)")
    else:
        a("_(Chart not generated — run report.py to produce it)_")
    a("")

    # 7. Verdict
    a("## 7. Verdict — Kill Criteria\n")
    a("Pre-agreed kill criteria, mechanically evaluated. No editorializing.\n")
    a("| # | Criterion | Threshold | Actual | Result |")
    a("|---|-----------|-----------|--------|--------|")

    kc1_actual = f"{prod_val.annualized_roi*100:.2f}% ann. ROI ($8k, validation)"
    a(f"| KC-1 | Validation-window ann. ROI (production-default config, $8k) | ≥ 5% | {kc1_actual} | {'**PASS**' if kc1 else '**FAIL**'} |")

    kc2_actual = f"{prod_full.liquidation_count} liquidations, kill-switch={'YES' if prod_full.kill_switch_fired else 'NO'}"
    a(f"| KC-2 | Zero liquidations + zero kill-switch events (full 2020→present, 2x leverage) | 0 / 0 | {kc2_actual} | {'**PASS**' if kc2 else '**FAIL**'} |")

    kc3_worst = min((yr["max_drawdown"] for yr in prod_full.yearly), default=0.0)
    kc3_worst_yr = min(prod_full.yearly, key=lambda y: y["max_drawdown"], default={}).get("year", "n/a")
    a(f"| KC-3 | Max drawdown ≤ 10% in every calendar year | ≤ −10% | Worst: {kc3_worst*100:.2f}% ({kc3_worst_yr}) | {'**PASS**' if kc3 else '**FAIL**'} |")

    a(f"| KC-4 | Total fees ≤ 25% of gross funding collected | ≤ 25% | {fee_ratio*100:.1f}% (${prod_full.total_fees:.2f} / ${prod_full.gross_funding_collected:.2f}) | {'**PASS**' if kc4 else '**FAIL**'} |")

    a("")
    all_pass = kc1 and kc2 and kc3 and kc4
    a("**Overall verdict:** " + ("ALL KILL CRITERIA PASSED." if all_pass
                                  else "ONE OR MORE KILL CRITERIA FAILED — see above."))
    if not kc1:
        a(f"\n- KC-1 FAILED: Validation-window ROI {prod_val.annualized_roi*100:.2f}% < 5% threshold.")
    if not kc2:
        a(f"\n- KC-2 FAILED: {prod_full.liquidation_count} liquidation(s) or kill-switch tripped.")
    if not kc3:
        failed_yrs = [yr for yr in prod_full.yearly if yr["max_drawdown"] < KC3_DD_THRESHOLD]
        a(f"\n- KC-3 FAILED: {[y['year'] for y in failed_yrs]} exceeded −10% drawdown threshold.")
    if not kc4:
        a(f"\n- KC-4 FAILED: Fee ratio {fee_ratio*100:.1f}% exceeds 25% cap.")
    a("")

    # Write report
    REPORT_MD.write_text("\n".join(lines) + "\n")
    print(f"\nReport written to: {REPORT_MD}")
    print(f"Equity chart:      {EQUITY_PNG}")
    print("\n=== Kill Criteria Verdict ===")
    print(f"  KC-1 (ROI ≥ 5%):          {'PASS' if kc1 else 'FAIL'} ({prod_val.annualized_roi*100:.2f}%)")
    print(f"  KC-2 (No liquidation):     {'PASS' if kc2 else 'FAIL'} ({kc2_actual})")
    print(f"  KC-3 (MaxDD ≤ 10%/yr):    {'PASS' if kc3 else 'FAIL'} (worst {kc3_worst*100:.2f}%)")
    print(f"  KC-4 (Fees ≤ 25% funding): {'PASS' if kc4 else 'FAIL'} ({fee_ratio*100:.1f}%)")
    print(f"\n  Overall: {'ALL PASS' if all_pass else 'FAIL'}")


def main() -> None:
    """CLI entry point."""
    generate_report()


if __name__ == "__main__":
    main()
