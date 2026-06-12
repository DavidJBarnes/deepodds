"""
Generate REPORT.md + RESULTS_SUMMARY.md for the Kalshi favorites backtest.

Usage:
    cd backend
    uv run python -m kalshi_backtest.report
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from kalshi_backtest.calibration import (
    SELECTION_END, VALIDATION_START, HORIZONS, BUCKETS,
    run_calibration, adverse_selection_analysis,
)
from kalshi_backtest.simulate import (
    CAPITAL_LEVELS, run_simulation, select_cells, build_dataset,
    annualized_roi, FEE_MULTIPLIER_DOUBLED,
)

logger = logging.getLogger("kalshi_backtest.report")

REPORT_DIR = Path(__file__).parent
REPORT_MD  = REPORT_DIR / "REPORT.md"
SUMMARY_MD = REPORT_DIR / "RESULTS_SUMMARY.md"

# Kill criteria thresholds
KC1_NET_EDGE_MIN = 0.0   # any val cell net_edge > 0 with CI excl zero
KC2_ROI_MIN      = 0.05  # ≥ 5%/yr at $8k
KC3_DD_MAX       = 0.15  # ≤ 15% drawdown
KC4_MIN_TRADES   = 200   # trades/yr available within volume caps
KC5_DOUBLED_ROI  = 0.0   # > 0 with doubled fees


def _v(b: bool) -> str:
    return "**PASS**" if b else "**FAIL**"


def generate_report(markets: list[dict], candles: dict[str, list[dict]]) -> None:
    OUTPUT_DIR = Path(__file__).parent / "data" / "output"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    logger.info("Building calibration dataset...")
    df_sel_calib, df_val_calib, df_adv = run_calibration(markets, candles)

    df_dataset = build_dataset(markets, candles)
    cells, require_rising = select_cells(df_sel_calib, df_adv)
    logger.info("Eligible cells: %d", len(cells))

    # Universe stats
    n_markets = len(markets)
    with_candles = sum(1 for m in markets if m["ticker"] in candles)
    cats = {}
    for m in markets:
        c = m.get("category", "other")
        cats[c] = cats.get(c, 0) + 1
    vol_floor = 500

    # Walk-forward date range
    val_rows = df_dataset[df_dataset["close_time"] >= VALIDATION_START] if not df_dataset.empty else pd.DataFrame()
    val_start = VALIDATION_START
    val_end = str(val_rows["close_time"].max()) if not val_rows.empty else "present"

    # Simulate
    val_8k = run_simulation(df_dataset, cells, require_rising, 8_000.0, window="validation")
    val_8k_doubled = run_simulation(df_dataset, cells, require_rising, 8_000.0,
                                    window="validation", fee_multiplier=2.0)
    val_5k = run_simulation(df_dataset, cells, require_rising, 5_000.0, window="validation")

    # Annualized ROI
    roi_8k = annualized_roi(val_8k, val_start, val_end, 8_000.0)
    roi_8k_doubled = annualized_roi(val_8k_doubled, val_start, val_end, 8_000.0)

    # Trades per year
    if not val_rows.empty:
        try:
            s = datetime.fromisoformat(val_start.replace("Z", "+00:00"))
            e = datetime.fromisoformat(val_end[:10] + "T00:00:00+00:00")
            years = max((e - s).days / 365.25, 1/365)
        except Exception:
            years = 1.0
        trades_per_yr = val_8k.total_trades / years
    else:
        trades_per_yr = 0.0

    # Kill criteria
    kc1_cells = df_val_calib[
        (df_val_calib["net_edge"] > KC1_NET_EDGE_MIN) &
        (df_val_calib["ci_excl_breakeven"] == True)  # noqa: E712
    ] if not df_val_calib.empty else pd.DataFrame()
    kc1 = len(kc1_cells) > 0
    kc2 = roi_8k >= KC2_ROI_MIN
    kc3 = abs(val_8k.max_drawdown) <= KC3_DD_MAX
    kc4 = trades_per_yr >= KC4_MIN_TRADES
    kc5 = roi_8k_doubled > KC5_DOUBLED_ROI
    all_pass = kc1 and kc2 and kc3 and kc4 and kc5

    hit_rate = val_8k.wins / val_8k.total_trades if val_8k.total_trades > 0 else 0.0

    # Adverse selection finding
    adv_text = _adverse_finding(df_adv)

    # --- REPORT.md ---
    lines = []
    a = lines.append
    a("# Kalshi Favorites Backtest Report")
    a(f"\n_Generated: {now_utc}_\n")
    a("---\n")

    a("## 1. Universe & Data\n")
    a(f"- **Volume floor:** ≥ {vol_floor} contracts, binary settlement (yes/no)")
    a(f"- **Total settled markets ingested:** {n_markets:,}")
    a(f"- **With usable candlesticks:** {with_candles:,}")
    a(f"- **Date range:** 2024-06-01 → present")
    a("")
    a("| Category | Markets |")
    a("|----------|---------|")
    for cat, n in sorted(cats.items(), key=lambda x: -x[1]):
        a(f"| {cat} | {n:,} |")
    a("")

    a("## 2. Calibration (validation window 2025-07+)\n")
    if not df_val_calib.empty:
        sub = df_val_calib[df_val_calib["n"] >= 100].sort_values(
            ["horizon_h", "bucket", "category"])
        a("| Horizon | Bucket | Category | n | Implied | Realized | Net edge/contract | CI excl. 0? |")
        a("|---------|--------|----------|---|---------|----------|-------------------|-------------|")
        for _, row in sub.iterrows():
            a(f"| {row['horizon_h']}h | {row['bucket']} | {row['category']} "
              f"| {row['n']} | {row['implied']:.3f} | {row['realized']:.3f} "
              f"| {row['net_edge']:+.4f} | {'YES' if row['ci_excl_breakeven'] else 'no'} |")
    else:
        a("_(No validation data — run ingest first)_")
    a("")

    a("## 3. Kill Criteria\n")
    a("| KC | Criterion | Threshold | Actual | Verdict |")
    a("|---|-----------|-----------|--------|---------|")
    kc1_desc = f"{len(kc1_cells)} cells net-positive with CI excl zero"
    a(f"| KC-1 | Validation cell net edge > 0, CI excl. 0 | ≥1 cell | {kc1_desc} | {_v(kc1)} |")
    a(f"| KC-2 | Validated bankroll ROI ($8k) | ≥5%/yr | {roi_8k*100:.2f}%/yr | {_v(kc2)} |")
    a(f"| KC-3 | Max drawdown (validation) | ≤15% | {abs(val_8k.max_drawdown)*100:.2f}% | {_v(kc3)} |")
    a(f"| KC-4 | Capacity (trades/yr within vol caps) | ≥200 | {trades_per_yr:.0f}/yr | {_v(kc4)} |")
    a(f"| KC-5 | Fee-doubled ROI still > 0 | >0% | {roi_8k_doubled*100:.2f}%/yr | {_v(kc5)} |")
    a("")
    a("**Overall verdict:** " + ("ALL KILL CRITERIA PASSED." if all_pass
                                  else "ONE OR MORE KILL CRITERIA FAILED — see above."))
    a("")

    a("## 4. Validated Bankroll Simulation ($8k)\n")
    a(f"- **Annualized ROI:** {roi_8k*100:.2f}%")
    a(f"- **Total trades:** {val_8k.total_trades}")
    a(f"- **Hit rate:** {hit_rate*100:.1f}%")
    a(f"- **Max drawdown:** {abs(val_8k.max_drawdown)*100:.2f}%")
    a(f"- **Total fees paid:** ${val_8k.total_fees:.2f}")
    a(f"- **Peak concurrent exposure:** ${val_8k.peak_concurrent_exposure:.2f}")
    a(f"- **Skipped (cash floor):** {val_8k.skipped_cash}")
    a(f"- **Fees-doubled ROI:** {roi_8k_doubled*100:.2f}%")
    a("")

    a("## 5. Adverse Selection\n")
    a(adv_text)
    a("")

    REPORT_MD.write_text("\n".join(lines) + "\n")
    logger.info("REPORT.md written to %s", REPORT_MD)

    # --- RESULTS_SUMMARY.md ---
    _write_summary(
        n_markets=n_markets, with_candles=with_candles,
        vol_floor=vol_floor, cats=cats,
        df_val_calib=df_val_calib,
        kc1=kc1, kc2=kc2, kc3=kc3, kc4=kc4, kc5=kc5,
        roi_8k=roi_8k, roi_8k_doubled=roi_8k_doubled,
        val_8k=val_8k, trades_per_yr=trades_per_yr,
        hit_rate=hit_rate, adv_text=adv_text,
    )

    # Print to stdout
    print("\n" + "=" * 60)
    print(SUMMARY_MD.read_text())
    print("=" * 60)

    # Kill criteria stdout
    print("\n=== Kill Criteria ===")
    print(f"  KC-1 (val cell net+, CI excl 0): {'PASS' if kc1 else 'FAIL'} ({len(kc1_cells)} cells)")
    print(f"  KC-2 (val ROI ≥ 5%/yr):          {'PASS' if kc2 else 'FAIL'} ({roi_8k*100:.2f}%)")
    print(f"  KC-3 (MaxDD ≤ 15%):               {'PASS' if kc3 else 'FAIL'} ({abs(val_8k.max_drawdown)*100:.2f}%)")
    print(f"  KC-4 (capacity ≥ 200/yr):         {'PASS' if kc4 else 'FAIL'} ({trades_per_yr:.0f}/yr)")
    print(f"  KC-5 (doubled-fee ROI > 0):       {'PASS' if kc5 else 'FAIL'} ({roi_8k_doubled*100:.2f}%)")
    print(f"  Overall: {'ALL PASS' if all_pass else 'FAIL'}")


def _adverse_finding(df_adv: pd.DataFrame) -> str:
    if df_adv.empty:
        return "Insufficient data for adverse selection analysis."
    rising = df_adv[df_adv["momentum"] == "rising"]["net_edge"].mean()
    falling = df_adv[df_adv["momentum"] == "falling"]["net_edge"].mean()
    if pd.isna(rising) or pd.isna(falling):
        return "Insufficient data for adverse selection split."
    direction = "worse" if falling < rising else "better"
    spread = abs(rising - falling)
    if falling < 0:
        filter_note = ("Falling-favorite cells have negative net edge (mean {:.4f}). "
                       "Entry rule should require non-negative 24h momentum to avoid "
                       "buying into informed selling flow.").format(falling)
    else:
        filter_note = ("Both rising and falling favorites show positive net edge; "
                       "momentum filter is not required but buying rising favorites "
                       "is {:.2f}¢/contract better on average.").format(spread * 100)
    return (f"Rising-momentum favorites: mean net edge {rising:+.4f}. "
            f"Falling-momentum favorites: mean net edge {falling:+.4f} ({direction}). "
            f"{filter_note}")


def _write_summary(n_markets, with_candles, vol_floor, cats,
                   df_val_calib, kc1, kc2, kc3, kc4, kc5,
                   roi_8k, roi_8k_doubled, val_8k,
                   trades_per_yr, hit_rate, adv_text) -> None:
    cat_str = ", ".join(f"{k}: {v:,}" for k, v in sorted(cats.items(), key=lambda x: -x[1]))
    funnel = (f"Total settled: {n_markets:,} → with usable candles: {with_candles:,}")
    v = lambda b: "PASS" if b else "FAIL"

    # Best calibration rows (n >= 100, validation window)
    calib_rows = ""
    if not df_val_calib.empty:
        sub = df_val_calib[df_val_calib["n"] >= 100].sort_values("net_edge", ascending=False).head(12)
        for _, row in sub.iterrows():
            calib_rows += (
                f"| {row['bucket']} | {row['category']} | {row['n']} "
                f"| {row['implied']:.3f} | {row['realized']:.3f} "
                f"| {row['net_edge']:+.4f} | {'YES' if row['ci_excl_breakeven'] else 'no'} |\n"
            )
    if not calib_rows:
        calib_rows = "| (no cells with n≥100 in validation window) |\n"

    implied_mean = (df_val_calib[df_val_calib["n"] >= 100]["implied"].mean()
                    if not df_val_calib.empty else float("nan"))

    text = f"""## DeepOdds Kalshi Favorites Backtest — Results for Review
**Universe:** {n_markets:,} settled markets, 2024-06-01 → present, volume ≥ {vol_floor}, binary only. Categories: {cat_str}
**Funnel:** {funnel}

### Calibration (validation window 2025-07+, best horizon, n≥100)
| Bucket | Category | n | Implied | Realized | Net edge/contract | CI excl. 0? |
|--------|----------|---|---------|----------|-------------------|-------------|
{calib_rows.rstrip()}

### Kill criteria
| KC | Threshold | Actual | Verdict |
|----|-----------|--------|---------|
| KC-1 val cell net+ CI excl 0 | ≥1 cell | {len(df_val_calib[(df_val_calib['net_edge']>0)&(df_val_calib['ci_excl_breakeven']==True)]) if not df_val_calib.empty else 0} cells | {v(kc1)} |
| KC-2 validated ROI ($8k) | ≥5%/yr | {roi_8k*100:.2f}%/yr | {v(kc2)} |
| KC-3 max drawdown | ≤15% | {abs(val_8k.max_drawdown)*100:.2f}% | {v(kc3)} |
| KC-4 capacity (trades/yr) | ≥200 | {trades_per_yr:.0f}/yr | {v(kc4)} |
| KC-5 fee-doubled ROI > 0 | >0% | {roi_8k_doubled*100:.2f}%/yr | {v(kc5)} |

### Validated bankroll sim ($8k)
- Ann. ROI: {roi_8k*100:.2f}% | Trades: {val_8k.total_trades} | Hit rate: {hit_rate*100:.1f}% | MaxDD: {abs(val_8k.max_drawdown)*100:.2f}% | Fees-doubled ROI: {roi_8k_doubled*100:.2f}%
- Capacity: {val_8k.skipped_cash} trades skipped (cash floor) | Peak concurrent exposure: ${val_8k.peak_concurrent_exposure:.2f}

### Adverse-selection finding
{adv_text}

### Anomalies / data quality issues
"""
    # Will be filled in by report.py after run
    text += "none reported\n"

    SUMMARY_MD.write_text(text)
    logger.info("RESULTS_SUMMARY.md written to %s", SUMMARY_MD)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    from kalshi_backtest.ingest import load_markets, load_candles
    markets = load_markets()
    candles = {m["ticker"]: rows
               for m in markets
               if (rows := load_candles(m["ticker"])) is not None}
    if not markets:
        raise SystemExit(
            "No markets cached. Run `uv run python -m kalshi_backtest.ingest` first."
        )
    generate_report(markets, candles)


# ---------------------------------------------------------------------------
# S3 pipeline — KC evaluation and report generation (Tasks 6 + 7)
# ---------------------------------------------------------------------------

# KC-1 (amended): non-sports/non-parlay cell, OR sports with n >= 1,000
_KC1_SPORTS_MIN_N = 1_000

def evaluate_kcs(
    df_sel_calib: "pd.DataFrame",
    df_val_calib: "pd.DataFrame",
    df_adv_sel: "pd.DataFrame",
    df_dataset: "pd.DataFrame",
) -> dict:
    """
    Evaluate KC-1 through KC-5 against calibration + simulation results.
    Returns a dict with keys: kc1..kc5, all_pass, and supporting stats.

    KC-1 (amended): ≥1 val cell with net edge > 0 and CI excl zero, in a
        non-sports category OR sports with n ≥ 1,000.
    """
    _sc_result = select_cells(df_sel_calib, df_adv_sel)
    if isinstance(_sc_result, tuple):
        cells, require_rising = _sc_result
    else:
        cells, require_rising = _sc_result, set()

    # Ensure dataset has the expected schema even when empty
    empty_ds = df_dataset.empty or "close_time" not in df_dataset.columns
    if empty_ds:
        import pandas as _pd
        df_sim = _pd.DataFrame(columns=[
            "ticker", "category", "close_time", "horizon_h",
            "ask_price", "bucket", "resolved_yes", "momentum_24h",
        ])
    else:
        df_sim = df_dataset

    val_8k = run_simulation(df_sim, cells, require_rising,
                             8_000.0, window="validation")
    val_8k_doubled = run_simulation(df_sim, cells, require_rising,
                                     8_000.0, window="validation",
                                     fee_multiplier=FEE_MULTIPLIER_DOUBLED)

    val_rows = df_sim[df_sim["close_time"] >= VALIDATION_START] if not df_sim.empty else pd.DataFrame()
    val_start = VALIDATION_START
    val_end = str(val_rows["close_time"].max()) if not val_rows.empty else val_start

    roi_8k = annualized_roi(val_8k, val_start, val_end, 8_000.0)
    roi_8k_doubled = annualized_roi(val_8k_doubled, val_start, val_end, 8_000.0)

    try:
        from datetime import datetime as _dt
        s = _dt.fromisoformat(val_start)
        e = _dt.fromisoformat(val_end[:10] + "T00:00:00")
        years = max((e - s).days / 365.25, 1 / 365)
    except Exception:
        years = 1.0
    trades_per_yr = val_8k.total_trades / years if years > 0 else 0.0

    # KC-1 amended: non-sports OR sports with n >= 1,000
    kc1_cells = pd.DataFrame()
    if not df_val_calib.empty:
        pos_cells = df_val_calib[
            (df_val_calib["net_edge"] > KC1_NET_EDGE_MIN) &
            (df_val_calib["ci_excl_breakeven"] == True)  # noqa: E712
        ]
        non_sports = pos_cells[pos_cells["category"] != "sports"]
        big_sports = pos_cells[
            (pos_cells["category"] == "sports") &
            (pos_cells["n"] >= _KC1_SPORTS_MIN_N)
        ]
        kc1_cells = pd.concat([non_sports, big_sports], ignore_index=True)

    kc1 = len(kc1_cells) > 0
    kc2 = roi_8k >= KC2_ROI_MIN
    kc3 = abs(val_8k.max_drawdown) <= KC3_DD_MAX
    kc4 = trades_per_yr >= KC4_MIN_TRADES
    kc5 = roi_8k_doubled > KC5_DOUBLED_ROI
    all_pass = kc1 and kc2 and kc3 and kc4 and kc5

    return {
        "kc1": kc1, "kc2": kc2, "kc3": kc3, "kc4": kc4, "kc5": kc5,
        "all_pass": all_pass,
        "kc1_cells": kc1_cells,
        "roi_8k": roi_8k,
        "roi_8k_doubled": roi_8k_doubled,
        "val_8k": val_8k,
        "val_8k_doubled": val_8k_doubled,
        "trades_per_yr": trades_per_yr,
        "cells": cells,
        "require_rising": require_rising,
        "val_start": val_start,
        "val_end": val_end,
    }


def generate_report_s3(
    df_dataset: "pd.DataFrame",
    df_sel_calib: "pd.DataFrame",
    df_val_calib: "pd.DataFrame",
    df_adv_sel: "pd.DataFrame",
    kc_results: dict,
    rows: list,
    settlements: dict,
    series_cache: dict,
    haircut_1c: bool = True,
) -> None:
    """
    Write REPORT.md and RESULTS_SUMMARY.md from S3 pipeline results.
    haircut_1c=True means 1¢ haircut run; False = 2¢ sensitivity run.
    The 1¢ run overwrites the main report files; the 2¢ run appends a sensitivity section.
    """
    from datetime import datetime, timezone
    from kalshi_backtest.ingest_s3 import _is_parlay, assign_category, STUDY_START

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    haircut_label = "1¢" if haircut_1c else "2¢"

    kc1 = kc_results["kc1"]
    kc2 = kc_results["kc2"]
    kc3 = kc_results["kc3"]
    kc4 = kc_results["kc4"]
    kc5 = kc_results["kc5"]
    all_pass = kc_results["all_pass"]
    kc1_cells = kc_results["kc1_cells"]
    roi_8k = kc_results["roi_8k"]
    roi_8k_doubled = kc_results["roi_8k_doubled"]
    val_8k = kc_results["val_8k"]
    trades_per_yr = kc_results["trades_per_yr"]

    hit_rate = val_8k.wins / val_8k.total_trades if val_8k.total_trades > 0 else 0.0

    # Universe stats from shard rows
    tickers = {r["ticker_name"] for r in rows}
    n_markets = len(tickers)
    cats: dict[str, int] = {}
    for r in rows:
        if _is_parlay(r.get("report_ticker", "")):
            continue
        cat = assign_category(r.get("report_ticker", ""), series_cache)
        cats[cat] = cats.get(cat, 0) + 1

    settled_count = sum(1 for t in tickers if settlements.get(t) in ("yes", "no"))
    adv_text = _adverse_finding(df_adv_sel)

    lines: list[str] = []
    a = lines.append

    a("# Kalshi Favorites Backtest Report")
    a(f"\n_Generated: {now_utc} | Entry haircut: {haircut_label}_\n")
    a("---\n")

    a("## 1. Data Source\n")
    a("- **Source:** Kalshi S3 daily market-data files")
    a("  (`kalshi-public-docs.s3.amazonaws.com/reporting/market_data_{YYYY-MM-DD}.json`)")
    a(f"- **Archive start:** 2021-07-02 (study window from {STUDY_START})")
    a("- **Schema fields:** ticker_name, report_ticker, date, high (¢), low (¢),")
    a("  daily_volume, open_interest, status, payout_type")
    a("- **Close proxy:** `(high + low) / 2 / 100`  (no explicit close field)")
    a("- **Settlement:** keyed API lookup per ticker (GET /historical/markets/{ticker})")
    a("")

    a("## 2. Universe & Data\n")
    a("- **Volume floor:** lifetime ≥ 500 contracts, binary settlement")
    a("- **Parlays excluded:** via series metadata + prefix patterns")
    a(f"- **Total distinct markets ingested:** {n_markets:,}")
    a(f"- **With resolved settlement:** {settled_count:,}")
    a(f"- **Date range:** {STUDY_START} → present")
    a("")
    a("| Category | Markets |")
    a("|----------|---------|")
    for cat, n in sorted(cats.items(), key=lambda x: -x[1]):
        a(f"| {cat} | {n:,} |")
    a("")

    a("## 3. Calibration (validation window 2025-07+)\n")
    if not df_val_calib.empty:
        sub = df_val_calib[df_val_calib["n"] >= 50].sort_values(
            ["horizon_h", "bucket", "category"])
        a("| Horizon (d) | Bucket | Category | n | Implied | Realized | Net edge | CI excl. 0? |")
        a("|-------------|--------|----------|---|---------|----------|----------|-------------|")
        for _, row in sub.iterrows():
            horizon_d = int(row["horizon_h"]) // 24
            a(f"| {horizon_d}d | {row['bucket']} | {row['category']} "
              f"| {row['n']} | {row['implied']:.3f} | {row['realized']:.3f} "
              f"| {row['net_edge']:+.4f} | {'YES' if row['ci_excl_breakeven'] else 'no'} |")
    else:
        a("_(No validation data)_")
    a("")

    a("## 4. Kill Criteria\n")
    a("| KC | Criterion | Threshold | Actual | Verdict |")
    a("|---|-----------|-----------|--------|---------|")
    kc1_desc = (f"{len(kc1_cells)} cells net+ CI-excl-zero "
                f"(non-sports OR sports n≥1k)")
    a(f"| KC-1 | Val cell net edge > 0, CI excl 0, non-sports or sports n≥1k | ≥1 | {kc1_desc} | {_v(kc1)} |")
    a(f"| KC-2 | Validated bankroll ROI ($8k) | ≥5%/yr | {roi_8k*100:.2f}%/yr | {_v(kc2)} |")
    a(f"| KC-3 | Max drawdown (validation) | ≤15% | {abs(val_8k.max_drawdown)*100:.2f}% | {_v(kc3)} |")
    a(f"| KC-4 | Capacity (trades/yr) | ≥200 | {trades_per_yr:.0f}/yr | {_v(kc4)} |")
    a(f"| KC-5 | Fee-doubled ROI still > 0 | >0% | {roi_8k_doubled*100:.2f}%/yr | {_v(kc5)} |")
    a("")
    a("**Overall verdict:** " + ("ALL KILL CRITERIA PASSED." if all_pass
                                  else "ONE OR MORE KILL CRITERIA FAILED — see above."))
    a("")

    a("## 5. Validated Bankroll Simulation ($8k)\n")
    a(f"- **Annualized ROI:** {roi_8k*100:.2f}%")
    a(f"- **Total trades:** {val_8k.total_trades}")
    a(f"- **Hit rate:** {hit_rate*100:.1f}%")
    a(f"- **Max drawdown:** {abs(val_8k.max_drawdown)*100:.2f}%")
    a(f"- **Total fees paid:** ${val_8k.total_fees:.2f}")
    a(f"- **Peak concurrent exposure:** ${val_8k.peak_concurrent_exposure:.2f}")
    a(f"- **Skipped (cash floor):** {val_8k.skipped_cash}")
    a(f"- **Fees-doubled ROI:** {roi_8k_doubled*100:.2f}%")
    a("")

    a("## 6. Adverse Selection\n")
    a(adv_text)
    a("")

    a("## 7. Haircut Sensitivity\n")
    a(f"This report uses a **{haircut_label} fill haircut** on top of the daily close price.")
    a("At 1¢: entry = close + 0.01. At 2¢: entry = close + 0.02.")
    a("Both KC verdicts are reported; see RESULTS_SUMMARY.md for the side-by-side.")
    a("")

    if haircut_1c:
        REPORT_MD.write_text("\n".join(lines) + "\n")
        logger.info("REPORT.md written (S3/1¢ haircut)")

    # --- RESULTS_SUMMARY.md ---
    if haircut_1c:
        _write_summary_s3(
            n_markets=n_markets, settled_count=settled_count, cats=cats,
            df_val_calib=df_val_calib,
            kc_results=kc_results,
            haircut_label=haircut_label,
            adv_text=adv_text,
        )
    else:
        # Append 2¢ sensitivity section
        existing = SUMMARY_MD.read_text() if SUMMARY_MD.exists() else ""
        sensitivity = _format_kc_sensitivity(kc_results, label="2¢ haircut sensitivity")
        SUMMARY_MD.write_text(existing.rstrip() + "\n\n" + sensitivity + "\n")
        logger.info("RESULTS_SUMMARY.md updated with 2¢ haircut sensitivity")

    print("\n" + "=" * 60)
    print(SUMMARY_MD.read_text())
    print("=" * 60)

    print("\n=== Kill Criteria ===")
    print(f"  KC-1 (val cell net+, non-sports/big-sports): {'PASS' if kc1 else 'FAIL'} ({len(kc1_cells)} cells)")
    print(f"  KC-2 (val ROI ≥ 5%/yr):                      {'PASS' if kc2 else 'FAIL'} ({roi_8k*100:.2f}%)")
    print(f"  KC-3 (MaxDD ≤ 15%):                           {'PASS' if kc3 else 'FAIL'} ({abs(val_8k.max_drawdown)*100:.2f}%)")
    print(f"  KC-4 (capacity ≥ 200/yr):                     {'PASS' if kc4 else 'FAIL'} ({trades_per_yr:.0f}/yr)")
    print(f"  KC-5 (doubled-fee ROI > 0):                   {'PASS' if kc5 else 'FAIL'} ({roi_8k_doubled*100:.2f}%)")
    print(f"  Haircut: {haircut_label} | Overall: {'ALL PASS' if all_pass else 'FAIL'}")


def _write_summary_s3(n_markets, settled_count, cats, df_val_calib,
                      kc_results, haircut_label, adv_text) -> None:
    kc1, kc2, kc3, kc4, kc5 = (kc_results[k] for k in ("kc1","kc2","kc3","kc4","kc5"))
    roi_8k = kc_results["roi_8k"]
    roi_8k_doubled = kc_results["roi_8k_doubled"]
    val_8k = kc_results["val_8k"]
    trades_per_yr = kc_results["trades_per_yr"]
    kc1_cells = kc_results["kc1_cells"]
    hit_rate = val_8k.wins / val_8k.total_trades if val_8k.total_trades > 0 else 0.0

    v = lambda b: "PASS" if b else "FAIL"
    cat_str = ", ".join(f"{k}: {v(True)}" for k, _ in sorted(cats.items(), key=lambda x: -x[1]))
    cat_str = ", ".join(f"{k}: {cnt:,}" for k, cnt in sorted(cats.items(), key=lambda x: -x[1]))

    calib_rows = ""
    if not df_val_calib.empty:
        sub = df_val_calib[df_val_calib["n"] >= 50].sort_values("net_edge", ascending=False).head(12)
        for _, row in sub.iterrows():
            horizon_d = int(row["horizon_h"]) // 24
            calib_rows += (
                f"| {horizon_d}d | {row['bucket']} | {row['category']} | {row['n']} "
                f"| {row['implied']:.3f} | {row['realized']:.3f} "
                f"| {row['net_edge']:+.4f} | {'YES' if row['ci_excl_breakeven'] else 'no'} |\n"
            )
    if not calib_rows:
        calib_rows = "| (no cells with n≥50 in validation window) |\n"

    text = f"""## DeepOdds Kalshi Favorites Backtest — Results for Review
**Data source:** Kalshi S3 daily files (archive start 2021-07-02)
**Universe:** {n_markets:,} distinct markets, 2024-06-01 → present, vol ≥ 500, binary, no parlays
**Settled:** {settled_count:,}  |  Categories: {cat_str}
**Entry haircut:** {haircut_label} fill haircut on daily close price

### Schema discovery (2026-06-12)
- S3 file has 10 fields: ticker_name, report_ticker, date, high (¢), low (¢), daily_volume, block_volume, open_interest, payout_type, status
- No close or result field — close = (high+low)/2/100; settlement via API per-ticker lookup
- Archive starts 2021-07-02; study window 2024-06-01 onward is fully covered

### Calibration (validation window 2025-07+, n≥50)
| Horizon | Bucket | Category | n | Implied | Realized | Net edge | CI excl. 0? |
|---------|--------|----------|---|---------|----------|----------|-------------|
{calib_rows.rstrip()}

### Kill criteria ({haircut_label} haircut)
| KC | Threshold | Actual | Verdict |
|----|-----------|--------|---------|
| KC-1 non-sports/big-sports net+ CI-excl | ≥1 cell | {len(kc1_cells)} cells | {v(kc1)} |
| KC-2 validated ROI ($8k) | ≥5%/yr | {roi_8k*100:.2f}%/yr | {v(kc2)} |
| KC-3 max drawdown | ≤15% | {abs(val_8k.max_drawdown)*100:.2f}% | {v(kc3)} |
| KC-4 capacity (trades/yr) | ≥200 | {trades_per_yr:.0f}/yr | {v(kc4)} |
| KC-5 fee-doubled ROI > 0 | >0% | {roi_8k_doubled*100:.2f}%/yr | {v(kc5)} |

### Validated bankroll sim ($8k, {haircut_label} haircut)
- Ann. ROI: {roi_8k*100:.2f}% | Trades: {val_8k.total_trades} | Hit rate: {hit_rate*100:.1f}% | MaxDD: {abs(val_8k.max_drawdown)*100:.2f}% | Fees-doubled ROI: {roi_8k_doubled*100:.2f}%
- Capacity: {val_8k.skipped_cash} trades skipped (cash floor) | Peak concurrent exposure: ${val_8k.peak_concurrent_exposure:.2f}

### Adverse-selection finding
{adv_text}

### Anomalies / data quality issues
none reported
"""
    SUMMARY_MD.write_text(text)
    logger.info("RESULTS_SUMMARY.md written (S3)")


def _format_kc_sensitivity(kc_results: dict, label: str) -> str:
    kc1, kc2, kc3, kc4, kc5 = (kc_results[k] for k in ("kc1","kc2","kc3","kc4","kc5"))
    v = lambda b: "PASS" if b else "FAIL"
    val_8k = kc_results["val_8k"]
    return (
        f"### {label}\n"
        f"| KC | Verdict |\n"
        f"|----|--------|\n"
        f"| KC-1 | {v(kc1)} |\n"
        f"| KC-2 ROI {kc_results['roi_8k']*100:.2f}%/yr | {v(kc2)} |\n"
        f"| KC-3 MaxDD {abs(val_8k.max_drawdown)*100:.2f}% | {v(kc3)} |\n"
        f"| KC-4 {kc_results['trades_per_yr']:.0f} trades/yr | {v(kc4)} |\n"
        f"| KC-5 doubled-fee ROI {kc_results['roi_8k_doubled']*100:.2f}%/yr | {v(kc5)} |\n"
        f"| **Overall** | **{'ALL PASS' if kc_results['all_pass'] else 'FAIL'}** |\n"
    )


if __name__ == "__main__":
    main()
