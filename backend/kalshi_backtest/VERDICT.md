# Kalshi Favorites Hypothesis — VERDICT: DEAD (not tradeable)

_2026-06-18_

## Summary

The favorites-longshot calibration signal is **real as a statistic but not
tradeable**. The apparent edge lives entirely in the gap between the daily
mid-price and the price you would actually pay as a taker. Fill at a realistic
worst-case (daily high) and the edge is negative in every bucket.

## How we got here

- Bulk S3 ingest delivered the data the API never could: **36,383 settled
  markets, 22,774-row dataset**, validation window 2025-07 → 2025-12.
- Calibration (entry = daily mid + 1¢ haircut) showed favorites in 80–97¢
  realizing above their implied price, CI excluding zero, 14 cells. Looked like
  a clean OOS edge.
- The bankroll sim originally printed 8590%/yr — a per-trade compounding bug
  (`simulate.py` released capital in the same loop iteration it opened it).
  **Fixed**: rewrote the engine event-driven, capital locked entry→settlement,
  settlements applied in calendar order. ROI dropped to 1078%/yr but was still
  implausible — pointing at the edge itself, not the sim.

## The kill test — fill basis (1d horizon, validation window)

| Bucket | n@mid | net edge @ daily **mid** | net edge @ daily **high** |
|--------|------:|--------------------------|---------------------------|
| 80–84¢ | 2224  | +0.064 (CI lo +0.051)    | **−0.021** (CI lo −0.044) |
| 85–89¢ | 1879  | +0.066 (CI lo +0.054)    | **−0.011** (CI lo −0.031) |
| 90–93¢ | 1579  | +0.042 (CI lo +0.032)    | **−0.003** (CI lo −0.020) |
| 94–97¢ | 1941  | +0.024 (CI lo +0.017)    | **−0.003** (CI lo −0.012) |

Mid is not an achievable fill for a market drifting toward YES — you pay the
ask, which sits at/above mid and near the daily high on up-moves. The "+6%" is
the spread/intraday drift, not alpha. As a price-taker we eat it.

## Conclusion

Do not trade Kalshi favorites. The edge is a measurement artifact of the
mid-price entry assumption. Reinforced by KC-3: a ~96.7% hit-rate book with rare
−90¢ losses also fails the drawdown criterion (16.9% @1¢, 23.1% @2¢) even on the
(inflated) mid-price equity curve — bad tail risk for no real edge.

This is a tradeability kill (fill basis), distinct from the earlier
data-availability kill. The S3 pipeline and event-driven sim are sound and
reusable; the hypothesis is not.
