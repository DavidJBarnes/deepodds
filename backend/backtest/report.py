"""
Generate REPORT.md (v2) for the carry strategy historical backtest.

Reads sweep results from backtest/results/sweep_results_v2.csv and runs
production-defaults replays to produce the full equity curve, per-year table,
and kill-criteria verdict. Also writes RESULTS_SUMMARY.md.

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
from backtest.sweep import (
    PROD_DEFAULTS, RESULTS_V2_CSV,
    SELECTION_END, SELECTION_START, VALIDATION_START,
)

logger = logging.getLogger("backtest.report")

REPORT_DIR    = Path(__file__).parent
REPORT_MD     = REPORT_DIR / "REPORT.md"
EQUITY_PNG    = REPORT_DIR / "REPORT_equity.png"
SUMMARY_MD    = REPORT_DIR / "RESULTS_SUMMARY.md"

# Kill criteria thresholds
KC1_ROI_THRESHOLD      = 0.05    # ≥ 5%
KC3_DD_THRESHOLD       = -0.10   # ≤ 10% drawdown per year
KC4_FEE_RATIO_CAP      = 0.25    # total fees ≤ 25% of gross funding
KC5_RECENTER_FEE_CAP   = 0.10    # Tier-B recenter fees ≤ 10% of gross funding


def _equity_chart(prod_full, out_path: Path) -> None:
    eq = prod_full.daily_equity
    if eq.empty:
        logger.warning("Empty equity series — skipping chart")
        return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle("Carry v2 — Production Defaults ($8k, 2x lev, 7d trailing, band=3.0)", fontsize=13)

    ax1.plot(eq.index, eq.values, label="Strategy equity", lw=1.5, color="steelblue")
    ax1.axhline(prod_full.capital, color="gray", lw=0.8, ls="--", label="Initial capital")
    val_start = pd.Timestamp(VALIDATION_START, tz="UTC")
    ax1.axvspan(val_start, eq.index[-1], alpha=0.08, color="green", label="Validation period")
    ax1.set_ylabel("Portfolio equity (USD)")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=6))

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


def _kc_verdict(pass_: bool) -> str:
    return "**PASS**" if pass_ else "**FAIL**"


def generate_report() -> None:
    """Run production-defaults replays and write REPORT.md + RESULTS_SUMMARY.md."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print("=== Carry Backtest v2 — Generating Report ===\n")

    frames = load_all()
    prod_cfg_8k = scaled_config(8_000.0, **PROD_DEFAULTS)

    print("Running production-defaults replay ($8k, full period)...")
    prod_full = run_replay(frames, prod_cfg_8k)

    print("Running production-defaults replay ($8k, validation window)...")
    prod_val = run_replay(frames, prod_cfg_8k, start=VALIDATION_START)

    print("Running production-defaults replay ($5k, validation window)...")
    prod_val_5k = run_replay(frames, scaled_config(5_000.0, **PROD_DEFAULTS), start=VALIDATION_START)

    print("Running cost-sensitivity replay ($8k, doubled fees)...")
    prod_costly = run_replay(frames,
        scaled_config(8_000.0, **PROD_DEFAULTS, taker_fee_frac=0.0008, spot_spread_bps=4.0),
        start=VALIDATION_START)

    print("Computing HL vs Binance funding comparison...")
    hl_comp = compare_hl_vs_binance()

    sweep_df = pd.read_csv(RESULTS_V2_CSV) if RESULTS_V2_CSV.exists() else None

    _equity_chart(prod_full, EQUITY_PNG)

    # --- Kill criteria evaluation ---
    kc1 = prod_val.annualized_roi >= KC1_ROI_THRESHOLD
    kc2_liq = prod_full.liquidation_count == 0
    kc2_kill = prod_full.kill_events == 0
    kc2 = kc2_liq and kc2_kill
    kc3_by_year = {yr["year"]: yr["max_drawdown"] >= KC3_DD_THRESHOLD for yr in prod_full.yearly}
    kc3 = all(kc3_by_year.values()) if kc3_by_year else True
    fee_ratio = (prod_full.total_fees / prod_full.gross_funding_collected
                 if prod_full.gross_funding_collected > 0 else float("inf"))
    kc4 = fee_ratio <= KC4_FEE_RATIO_CAP
    recenter_ratio = (prod_full.rebalance_fees_usd / prod_full.gross_funding_collected
                      if prod_full.gross_funding_collected > 0 else 0.0)
    kc5 = recenter_ratio <= KC5_RECENTER_FEE_CAP

    # --- Build report ---
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    a = lines.append

    a("# Carry Strategy Backtest Report (v2 — Two-Tier Rebalancing)")
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
    a("")
    a("**Engine version:** v2 with two-tier leverage rebalancing (Task 1+2)")
    a("- Tier A (fee-free): cash→hl_margin transfer when lev > max_leverage_band")
    a("- Tier B (real fills): close+reopen when Tier A exhausted (cash floor)")
    a("- `halt_on_kill=False` in backtest: kill events counted + resumed, not halting")
    a("")
    a("**Gap counts (price data):**")
    for coin, df in frames.items():
        expected = (df["ts"].iloc[-1] - df["ts"].iloc[0]).total_seconds() / 3600 + 1
        gaps = max(0, int(expected) - len(df))
        a(f"  - {coin}: {gaps} hours dropped")
    a("")

    # 2. Per-calendar-year table
    a("## 2. Per-Calendar-Year Performance (Production Defaults, $8k)\n")
    a("_Config: hurdle=6%, rich=20%, trailing=168h, exit=0%, leverage=2x, band=3.0_\n")
    a("| Year | Ann. ROI | MaxDD | %Deployed | RoundTrips | TopUps | Recenters | Funding$ | Fees$ |")
    a("|------|----------|-------|-----------|------------|--------|-----------|----------|-------|")
    for yr_row in prod_full.yearly:
        a(f"| {yr_row['year']} | {yr_row['roi']*100:.2f}% | "
          f"{yr_row['max_drawdown']*100:.2f}% | "
          f"{yr_row.get('pct_deployed', 0)*100:.1f}% | "
          f"{yr_row.get('round_trips', 0)} | "
          f"{yr_row.get('topups', 0)} | "
          f"{yr_row.get('recenters', 0)} | "
          f"${yr_row.get('funding', 0):.2f} | "
          f"${yr_row.get('fees', 0):.2f} |")
    a("")
    a(f"**Full period:** Net P&L={_fmt_dollar(prod_full.net_pnl)}  "
      f"Ann. ROI={_fmt_pct(prod_full.annualized_roi)}  "
      f"Sharpe={prod_full.sharpe:.3f}  "
      f"MaxDD={_fmt_pct(prod_full.max_drawdown)}  "
      f"Fees={_fmt_dollar(prod_full.total_fees)}  "
      f"Funding={_fmt_dollar(prod_full.gross_funding_collected)}  "
      f"TopUps={prod_full.rebalance_topup_count}  "
      f"Recenters={prod_full.rebalance_recenter_count}  "
      f"RecenterFees={_fmt_dollar(prod_full.rebalance_fees_usd)}  "
      f"KillEvents={prod_full.kill_events}  "
      f"% deployed={prod_full.pct_hours_deployed*100:.1f}%")
    a("")

    # 3. Walk-forward results
    a("## 3. Walk-Forward Results\n")
    a("**Selection window:** 2020-01-01 → 2023-12-31  "
      "**Validation window:** 2024-01-01 → present\n")

    if sweep_df is not None:
        # Top-10 qualified by selection window
        sel = sweep_df[sweep_df["window"] == "selection"].copy()
        sel = sel[(sel["liquidations"] == 0) & (sel["kill_events"] == 0)]
        sel_8k = sel[sel["capital"] == 8000].sort_values("roi_ann", ascending=False).head(10)
        if not sel_8k.empty:
            a("### Top 10 configs (selection window, $8k, zero kill events)\n")
            a("| Hurdle | Rich | Trail(h) | Exit | Band | Ann.ROI | MaxDD | Deploy% |")
            a("|--------|------|----------|------|------|---------|-------|---------|")
            for _, r in sel_8k.iterrows():
                a(f"| {r['hurdle']:.0%} | {r['rich']:.0%} | {r['trail_h']:.0f} | "
                  f"{r['exit']:.0%} | {r['band']:.1f} | "
                  f"{r['roi_ann']:.2f}% | {r['max_dd']:.2f}% | {r['pct_deployed']:.1f}% |")
            a("")

        val = sweep_df[sweep_df["window"].isin(["validation", "prod_default"])].copy()
        val_8k = val[val["capital"] == 8000].sort_values("roi_ann", ascending=False)
        if not val_8k.empty:
            a("### Validation window results ($8k)\n")
            a("| Config | Hurdle | Rich | Trail(h) | Exit | Band | Ann.ROI | MaxDD | Liq | KillEvents |")
            a("|--------|--------|------|----------|------|------|---------|-------|-----|------------|")
            for _, r in val_8k.iterrows():
                a(f"| {r['window']} | {r['hurdle']:.0%} | {r['rich']:.0%} | "
                  f"{r['trail_h']:.0f} | {r['exit']:.0%} | {r['band']:.1f} | "
                  f"{r['roi_ann']:.2f}% | {r['max_dd']:.2f}% | "
                  f"{r['liquidations']:.0f} | {r.get('kill_events', '—')} |")
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
        binance_mean = hl_comp["binance_ann"].mean() * 100
        hl_mean = hl_comp["hl_ann"].mean() * 100
        a(f"**Venue transferability:** Mean Binance ann. {binance_mean:.1f}% vs HL ann. {hl_mean:.1f}% "
          f"(overlap period). HL funding averages {avg_diff:+.2f}pp higher.")
    else:
        a("_(HL funding data unavailable)_")
    a("")

    # 6. Equity chart
    a("## 6. Equity Curve\n")
    a("Production defaults ($8k), full period 2020 → present.\n")
    if EQUITY_PNG.exists():
        a("![Equity curve](REPORT_equity.png)")
    else:
        a("_(Chart not generated)_")
    a("")

    # 7. Kill criteria verdict
    a("## 7. Verdict — Kill Criteria (v2)\n")
    a("Pre-agreed kill criteria, mechanically evaluated. No editorializing.\n")
    a("| # | Criterion | Threshold | Actual | Result |")
    a("|---|-----------|-----------|--------|--------|")

    kc1_actual = f"{prod_val.annualized_roi*100:.2f}% ann. ROI ($8k, validation)"
    a(f"| KC-1 | Validation-window ann. ROI (prod defaults, $8k) | ≥ 5% | {kc1_actual} | {_kc_verdict(kc1)} |")

    kc2_actual = (f"{prod_full.liquidation_count} liquidations, "
                  f"{prod_full.kill_events} kill events (full 2020→present)")
    a(f"| KC-2 | Zero liquidations + zero kill events (full period, 2x lev) | 0 / 0 | {kc2_actual} | {_kc_verdict(kc2)} |")

    kc3_worst = min((yr["max_drawdown"] for yr in prod_full.yearly), default=0.0)
    kc3_worst_yr = min(prod_full.yearly, key=lambda y: y["max_drawdown"], default={}).get("year", "n/a")
    a(f"| KC-3 | Max drawdown ≤ 10% every calendar year | ≤ −10% | Worst: {kc3_worst*100:.2f}% ({kc3_worst_yr}) | {_kc_verdict(kc3)} |")

    a(f"| KC-4 | Total fees ≤ 25% of gross funding | ≤ 25% | "
      f"{fee_ratio*100:.1f}% (${prod_full.total_fees:.2f} / ${prod_full.gross_funding_collected:.2f}) | "
      f"{_kc_verdict(kc4)} |")

    a(f"| KC-5 | Tier-B recenter fees ≤ 10% of gross funding | ≤ 10% | "
      f"{recenter_ratio*100:.1f}% (${prod_full.rebalance_fees_usd:.2f} / ${prod_full.gross_funding_collected:.2f}) | "
      f"{_kc_verdict(kc5)} |")

    a("")
    all_pass = kc1 and kc2 and kc3 and kc4 and kc5
    a("**Overall verdict:** " + ("ALL KILL CRITERIA PASSED." if all_pass
                                  else "ONE OR MORE KILL CRITERIA FAILED — see above."))
    if not kc1:
        a(f"\n- KC-1 FAILED: Validation ROI {prod_val.annualized_roi*100:.2f}% < 5%.")
    if not kc2:
        a(f"\n- KC-2 FAILED: {prod_full.liquidation_count} liquidation(s), {prod_full.kill_events} kill event(s).")
    if not kc3:
        bad = [yr for yr in prod_full.yearly if yr["max_drawdown"] < KC3_DD_THRESHOLD]
        a(f"\n- KC-3 FAILED: {[y['year'] for y in bad]} exceeded −10% drawdown.")
    if not kc4:
        a(f"\n- KC-4 FAILED: Fee ratio {fee_ratio*100:.1f}% > 25%.")
    if not kc5:
        a(f"\n- KC-5 FAILED: Recenter fee ratio {recenter_ratio*100:.1f}% > 10%.")
    a("")

    REPORT_MD.write_text("\n".join(lines) + "\n")
    print(f"\nReport written to: {REPORT_MD}")
    print(f"Equity chart:      {EQUITY_PNG}")
    print("\n=== Kill Criteria Verdict ===")
    print(f"  KC-1 (ROI ≥ 5%):                {'PASS' if kc1 else 'FAIL'} ({prod_val.annualized_roi*100:.2f}%)")
    print(f"  KC-2 (No liq/kill):              {'PASS' if kc2 else 'FAIL'} ({prod_full.liquidation_count} liq, {prod_full.kill_events} kill events)")
    print(f"  KC-3 (MaxDD ≤ 10%/yr):           {'PASS' if kc3 else 'FAIL'} (worst {kc3_worst*100:.2f}%)")
    print(f"  KC-4 (Fees ≤ 25% funding):       {'PASS' if kc4 else 'FAIL'} ({fee_ratio*100:.1f}%)")
    print(f"  KC-5 (Recenter fees ≤ 10%):      {'PASS' if kc5 else 'FAIL'} ({recenter_ratio*100:.1f}%)")
    print(f"\n  Overall: {'ALL PASS' if all_pass else 'FAIL'}")

    # Generate RESULTS_SUMMARY.md (Task 6)
    _generate_summary(
        prod_full=prod_full, prod_val=prod_val, prod_val_5k=prod_val_5k,
        prod_costly=prod_costly, hl_comp=hl_comp, sweep_df=sweep_df,
        kc1=kc1, kc2=kc2, kc3=kc3, kc4=kc4, kc5=kc5,
        kc3_worst=kc3_worst, fee_ratio=fee_ratio, recenter_ratio=recenter_ratio,
        frames=frames,
    )


def _generate_summary(prod_full, prod_val, prod_val_5k, prod_costly,
                      hl_comp, sweep_df, kc1, kc2, kc3, kc4, kc5,
                      kc3_worst, fee_ratio, recenter_ratio, frames) -> None:
    """Write RESULTS_SUMMARY.md in the exact format requested (Task 6)."""
    first_coin = next(iter(frames.values()))
    data_start = str(first_coin["ts"].iloc[0].date())
    data_end   = str(first_coin["ts"].iloc[-1].date())
    total_gaps = 0
    for df in frames.values():
        expected = (df["ts"].iloc[-1] - df["ts"].iloc[0]).total_seconds() / 3600 + 1
        total_gaps += max(0, int(expected) - len(df))

    # Binance vs HL means
    if not hl_comp.empty:
        b_mean = hl_comp["binance_ann"].mean() * 100
        h_mean = hl_comp["hl_ann"].mean() * 100
    else:
        b_mean = h_mean = float("nan")

    # Walk-forward configs
    wf_rows = ""
    if sweep_df is not None:
        val = sweep_df[sweep_df["window"].isin(["validation", "prod_default"])].copy()
        val_8k = val[val["capital"] == 8000].sort_values("roi_ann", ascending=False)
        # Get selection ROI for the same combos
        sel = sweep_df[sweep_df["window"] == "selection"].copy()
        for _, r in val_8k.iterrows():
            key = (r["hurdle"], r["rich"], r["trail_h"], r["exit"], r["band"])
            sel_match = sel[
                (sel["hurdle"] == r["hurdle"]) &
                (sel["rich"] == r["rich"]) &
                (sel["trail_h"] == r["trail_h"]) &
                (sel["exit"] == r["exit"]) &
                (sel["band"] == r["band"]) &
                (sel["capital"] == 8000)
            ]
            sel_roi = f"{sel_match['roi_ann'].values[0]:.2f}%" if len(sel_match) else "—"
            vf_ratio = (r["fees"] / r["funding_coll"] * 100) if r["funding_coll"] > 0 else float("inf")
            wf_rows += (
                f"| {r['hurdle']:.0%}/{r['rich']:.0%}/{r['trail_h']:.0f}h/"
                f"{r['exit']:.0%}/{r['band']:.1f} "
                f"| {sel_roi} | {r['roi_ann']:.2f}% "
                f"| {r['max_dd']:.2f}% | {vf_ratio:.0f}% |\n"
            )

    # Worst episode (first entry from engine log)
    worst_line = "see engine log"
    for entry in prod_full.portfolio.log:
        if "LIQUIDATION" in entry or "kill" in entry.lower():
            worst_line = entry[:120]
            break

    # Per-year table
    yr_rows = ""
    for yr in prod_full.yearly:
        yr_rows += (
            f"| {yr['year']} "
            f"| {yr['roi']*100:.2f}% "
            f"| {yr['max_drawdown']*100:.2f}% "
            f"| {yr.get('pct_deployed', 0)*100:.1f}% "
            f"| {yr.get('round_trips', 0)} "
            f"| {yr.get('topups', 0)} "
            f"| {yr.get('recenters', 0)} "
            f"| ${yr.get('funding', 0):.2f} "
            f"| ${yr.get('fees', 0):.2f} |\n"
        )

    v = lambda b: "PASS" if b else "FAIL"
    text = f"""## DeepOdds Backtest v2 — Results for Review
**Data:** Binance Vision (perp+spot klines, 8h funding) | {data_start}–{data_end} | BTC,ETH | gaps dropped: {total_gaps}
**Engine:** rebalancing v2, band sweep {{2.5,3.0,3.5}}, leverage 2.0x

### Kill criteria ($8k, production defaults, band=3.0)
| KC | Threshold | Actual | Verdict |
|----|-----------|--------|---------|
| KC-1 validated ROI | ≥5%/yr | {prod_val.annualized_roi*100:.2f}% | {v(kc1)} |
| KC-2 liq/kill events | 0 | {prod_full.liquidation_count}/{prod_full.kill_events} | {v(kc2)} |
| KC-3 worst-year drawdown | ≤10% | {kc3_worst*100:.1f}% | {v(kc3)} |
| KC-4 total fees / funding | ≤25% | {fee_ratio*100:.0f}% | {v(kc4)} |
| KC-5 recenter fees / funding | ≤10% | {recenter_ratio*100:.1f}% | {v(kc5)} |

### Per calendar year ($8k, production defaults, band=3.0)
| Year | ROI | MaxDD | %Deployed | RoundTrips | TopUps | Recenters | Funding$ | Fees$ |
|------|-----|-------|-----------|------------|--------|-----------|----------|-------|
{yr_rows.rstrip()}

### Walk-forward (validation window 2024→present, $8k)
| Config (hurdle/rich/window/exit/band) | Sel. ROI | Val. ROI | Val. MaxDD | Val. fees/funding |
|--------------------------------------|----------|----------|------------|-------------------|
{wf_rows.rstrip()}

### Sensitivity & notes
- Costs doubled → validated ROI: {prod_costly.annualized_roi*100:.2f}%
- $5k capital, production defaults → validated ROI: {prod_val_5k.annualized_roi*100:.2f}%
- Binance vs HL mean funding (overlap, ann.): {b_mean:.1f}% vs {h_mean:.1f}%
- Worst single episode: {worst_line}
- Anomalies/bugs encountered: v1 ghost-position (pct_deployed=99.9%); v1 Binance CSV column-order (rate was at index 2 not 1); 2025+ spot kline microsecond timestamps — all fixed
"""

    SUMMARY_MD.write_text(text)
    print(f"\nResults summary written to: {SUMMARY_MD}")
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)


def main() -> None:
    """CLI entry point."""
    generate_report()


if __name__ == "__main__":
    main()
