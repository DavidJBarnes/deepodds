"""
Parameter sweep + walk-forward validation for the carry strategy.

Grid:
  min_funding_hurdle_ann: 0.04, 0.06, 0.08, 0.10
  rich_funding_ann:       0.15, 0.20, 0.30
  trailing_window_hours:  72, 168, 336
  exit_funding_ann:       0.00, 0.02, 0.04

Walk-forward protocol:
  Selection window:  2020-01-01 → 2023-12-31
  Validation window: 2024-01-01 → end of data

Invalid combos (rich ≤ hurdle OR exit ≥ hurdle) are skipped.
Leverage is fixed at 2.0x for all configs.

All results saved to backtest/results/sweep_results.csv (gitignored).

Usage:
    cd backend
    uv run python -m backtest.sweep
"""
import csv
import itertools
import logging
from pathlib import Path

import pandas as pd

from backtest.data_ingest import load_all
from backtest.replay import _build_price_index, _precompute_trailing, run_replay
from backtest.scaling import scaled_config
from carry.config import CarryConfig

logger = logging.getLogger("backtest.sweep")

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_CSV = RESULTS_DIR / "sweep_results.csv"        # v1 (kept for reference)
RESULTS_V2_CSV = RESULTS_DIR / "sweep_results_v2.csv"  # v2 with rebalancing + band sweep

SELECTION_START = "2020-01-01"
SELECTION_END   = "2023-12-31"
VALIDATION_START = "2024-01-01"

CAPITAL_LEVELS = [5_000.0, 8_000.0]

# Production defaults (for separate validation run + cost sensitivity)
PROD_DEFAULTS = dict(
    min_funding_hurdle_ann=0.06,
    rich_funding_ann=0.20,
    trailing_window_hours=168,
    exit_funding_ann=0.00,
    max_leverage_band=3.0,
)

GRID = dict(
    min_funding_hurdle_ann=[0.04, 0.06, 0.08, 0.10],
    rich_funding_ann=[0.15, 0.20, 0.30],
    trailing_window_hours=[72, 168, 336],
    exit_funding_ann=[0.00, 0.02, 0.04],
    max_leverage_band=[2.5, 3.0, 3.5],
)


def _valid_combo(hurdle: float, rich: float, exit_: float) -> bool:
    """Skip combinations where rich ≤ hurdle or exit ≥ hurdle. Band is always valid."""
    return rich > hurdle and exit_ < hurdle


def _disqualified(sel_results: list[dict]) -> bool:
    """
    Disqualify a config from selection if it had:
      - any liquidation
      - any kill-switch event
      - negative P&L in 2 or more calendar years
    """
    if sel_results[0]["liquidations"] > 0:
        return True
    if sel_results[0]["kill_switch"]:
        return True
    negative_years = sum(1 for yr in sel_results[0].get("yearly", []) if yr["roi"] < 0)
    return negative_years >= 2


def _row_from_result(result, capital: float, hurdle: float, rich: float,
                     window: int, exit_: float, band: float, window_label: str) -> dict:
    """Convert a ReplayResult into a flat CSV row."""
    return {
        "window": window_label,
        "capital": capital,
        "hurdle": hurdle,
        "rich": rich,
        "trail_h": window,
        "exit": exit_,
        "band": band,
        "roi_ann": round(result.annualized_roi * 100, 3),
        "sharpe": round(result.sharpe, 3),
        "max_dd": round(result.max_drawdown * 100, 3),
        "pct_deployed": round(result.pct_hours_deployed * 100, 1),
        "round_trips": result.round_trips,
        "fees": round(result.total_fees, 2),
        "funding_coll": round(result.gross_funding_collected, 2),
        "funding_paid": round(result.gross_negative_funding_paid, 2),
        "liquidations": result.liquidation_count,
        "kill_switch": result.kill_switch_fired,
        "kill_events": result.kill_events,
        "topup_count": result.rebalance_topup_count,
        "recenter_count": result.rebalance_recenter_count,
        "recenter_fees": round(result.rebalance_fees_usd, 4),
        "net_pnl": round(result.net_pnl, 2),
        "yearly": result.yearly,
    }


def run_sweep(frames: dict | None = None, verbose: bool = True) -> pd.DataFrame:
    """
    Run the full parameter sweep + walk-forward validation.

    Returns a DataFrame of all results (selection + validation windows).
    Also writes RESULTS_CSV.
    """
    if frames is None:
        frames = load_all()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Pre-build shared price index and trailing series (expensive, done once)
    logger.info("Pre-building price index and trailing series cache...")
    price_idx = _build_price_index(frames)
    trailing_cache: dict = {}
    for window in set(GRID["trailing_window_hours"]):
        for coin in frames:
            dummy_cfg = CarryConfig(trailing_window_hours=window)
            from backtest.replay import _precompute_trailing as _pt
            series = _pt(frames, dummy_cfg)
            trailing_cache[(coin, window)] = series[coin]
    logger.info("Cache built.")

    # Build full grid of valid parameter combos (includes band dimension)
    combos = [
        (hurdle, rich, window, exit_, band)
        for hurdle, rich, window, exit_, band in itertools.product(
            GRID["min_funding_hurdle_ann"],
            GRID["rich_funding_ann"],
            GRID["trailing_window_hours"],
            GRID["exit_funding_ann"],
            GRID["max_leverage_band"],
        )
        if _valid_combo(hurdle, rich, exit_)
    ]
    logger.info("Grid: %d valid configs × %d capital levels = %d total replays",
                len(combos), len(CAPITAL_LEVELS), len(combos) * len(CAPITAL_LEVELS))

    all_rows: list[dict] = []
    selection_by_capital: dict[float, list[tuple[tuple, dict]]] = {c: [] for c in CAPITAL_LEVELS}

    total = len(combos) * len(CAPITAL_LEVELS)
    done = 0

    for hurdle, rich, window, exit_, band in combos:
        for capital in CAPITAL_LEVELS:
            cfg = scaled_config(
                capital,
                min_funding_hurdle_ann=hurdle,
                rich_funding_ann=rich,
                trailing_window_hours=window,
                exit_funding_ann=exit_,
                max_leverage_band=band,
            )
            try:
                sel = run_replay(frames, cfg, start=SELECTION_START, end=SELECTION_END,
                                 _price_idx=price_idx, _trailing_cache=trailing_cache)
            except Exception as e:
                logger.warning("Replay failed (sel) %s: %s",
                               (hurdle, rich, window, exit_, band, capital), e)
                done += 1
                continue

            row = _row_from_result(sel, capital, hurdle, rich, window, exit_, band, "selection")
            all_rows.append(row)
            selection_by_capital[capital].append(((hurdle, rich, window, exit_, band), row))

            done += 1
            if verbose and done % 50 == 0:
                logger.info("  %d/%d selection replays done", done, total)

    # --- Walk-forward: top-3 per capital + production defaults + cost sensitivity ---
    logger.info("Running validation window for top-3 configs + production defaults...")

    for capital in CAPITAL_LEVELS:
        sel_rows = selection_by_capital[capital]

        # Sort by ROI, disqualify per criteria
        qualified = [(combo, row) for combo, row in sel_rows if not _disqualified([row])]
        qualified.sort(key=lambda x: x[1]["roi_ann"], reverse=True)
        top3 = qualified[:3]

        # Add production defaults (always include, band=3.0)
        prod_combo = (
            PROD_DEFAULTS["min_funding_hurdle_ann"],
            PROD_DEFAULTS["rich_funding_ann"],
            PROD_DEFAULTS["trailing_window_hours"],
            PROD_DEFAULTS["exit_funding_ann"],
            PROD_DEFAULTS["max_leverage_band"],
        )
        top3_combos = {combo for combo, _ in top3}
        val_targets = list(top3_combos | {prod_combo})

        for combo in val_targets:
            hurdle, rich, window, exit_, band = combo
            cfg = scaled_config(
                capital,
                min_funding_hurdle_ann=hurdle,
                rich_funding_ann=rich,
                trailing_window_hours=window,
                exit_funding_ann=exit_,
                max_leverage_band=band,
            )
            label = "prod_default" if combo == prod_combo and combo not in top3_combos else "validation"
            try:
                val = run_replay(frames, cfg, start=VALIDATION_START,
                                 _price_idx=price_idx, _trailing_cache=trailing_cache)
                row = _row_from_result(val, capital, hurdle, rich, window, exit_, band, label)
                all_rows.append(row)
            except Exception as e:
                logger.warning("Validation replay failed %s: %s", combo, e)

        # Cost sensitivity: production defaults at $8k, fees + spreads doubled
        if capital == 8_000.0:
            logger.info("Running cost-sensitivity replay ($8k, doubled fees)...")
            cfg_costly = scaled_config(
                8_000.0,
                min_funding_hurdle_ann=PROD_DEFAULTS["min_funding_hurdle_ann"],
                rich_funding_ann=PROD_DEFAULTS["rich_funding_ann"],
                trailing_window_hours=PROD_DEFAULTS["trailing_window_hours"],
                exit_funding_ann=PROD_DEFAULTS["exit_funding_ann"],
                max_leverage_band=PROD_DEFAULTS["max_leverage_band"],
                taker_fee_frac=0.0008,   # doubled
                spot_spread_bps=4.0,      # doubled
            )
            try:
                val_costly = run_replay(frames, cfg_costly, start=VALIDATION_START,
                                        _price_idx=price_idx, _trailing_cache=trailing_cache)
                row_costly = _row_from_result(
                    val_costly, 8_000.0,
                    PROD_DEFAULTS["min_funding_hurdle_ann"],
                    PROD_DEFAULTS["rich_funding_ann"],
                    PROD_DEFAULTS["trailing_window_hours"],
                    PROD_DEFAULTS["exit_funding_ann"],
                    PROD_DEFAULTS["max_leverage_band"],
                    "cost_sensitivity",
                )
                all_rows.append(row_costly)
            except Exception as e:
                logger.warning("Cost-sensitivity replay failed: %s", e)

    # Save to CSV (exclude yearly column — it's a list)
    if all_rows:
        flat_rows = [{k: v for k, v in r.items() if k != "yearly"} for r in all_rows]
        with open(RESULTS_V2_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(flat_rows[0].keys()))
            writer.writeheader()
            writer.writerows(flat_rows)
        logger.info("Saved %d rows to %s", len(flat_rows), RESULTS_V2_CSV)

    # Build and return DataFrame (include all rows with yearly as string)
    df = pd.DataFrame(all_rows)
    return df


def main() -> None:
    """Run the full sweep and print top-10 validation results."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print("=== Carry Backtest — Parameter Sweep ===\n")
    df = run_sweep(verbose=True)

    val = df[df["window"].isin(["validation", "prod_default"])]
    if not val.empty:
        print("\nTop validation results ($8k):")
        sub = val[val["capital"] == 8000].sort_values("roi_ann", ascending=False)
        print(sub[["window", "hurdle", "rich", "trail_h", "exit", "band", "roi_ann",
                    "sharpe", "max_dd", "liquidations", "kill_events"]].head(10).to_string(index=False))
    print(f"\nAll results saved to: {RESULTS_V2_CSV}")


if __name__ == "__main__":
    main()
