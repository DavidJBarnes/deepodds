# Kalshi Longshot-Short — VERDICT: PROMISING (first survivor; graduate to small live test)

_2026-06-20_

## One-line

Selling overpriced 1–12¢ longshots at the 1-day horizon is the **first Kalshi
strategy to survive realistic fills + fees + a collateral-aware sim**. It's a
real edge for a **small account ($5–15k)**, but concentrated in a few categories
and gated by one untested risk: can you actually get filled at the bid 1 day out?

## Data

Cheap-band (1–25¢) re-ingest (favorites ingest had hard-filtered to mid≥75¢),
validation window 2025-07 → 2025-12. **~55k randomly-resolved settled markets**
(de-biased — first 21.7k were insertion-ordered, so a random sample was added).

## Edge (net-of-fee, sell YES at daily-low = pessimistic bid fill)

1-day horizon, CI-clean from 1¢ through 12¢:

| Bucket | n | realized-yes | net edge/contract | CI95-lo |
|--------|---|--------------|-------------------|---------|
| 1–3¢ | 5239 | 0.69% | +0.42¢ | +0.20 |
| 3–5¢ | 2063 | 1.70% | +0.95¢ | +0.39 |
| 5–8¢ | 2298 | 2.83% | +1.57¢ | +0.89 |
| 8–12¢ | 2122 | 4.24% | **+2.64¢** | +1.78 |

**7-day horizon mostly collapses** → the edge is near-settlement. This is the
opposite of favorites, which went negative at realistic fills.

## Kill-criteria gate

| KC | Threshold | Result | Verdict |
|----|-----------|--------|---------|
| KC-1 net-of-fee edge CI-excl-0 | ≥1 cell | 4 buckets + 4 categories | PASS |
| KC-2 validated ROI ($8k) | ≥5%/yr | +100%/yr @ tf=0.5% | PASS |
| KC-3 MaxDD | ≤15% | 10.6% @ tf=0.5% (34% @ tf=2%) | PASS (size-dependent) |
| KC-4 capacity | small-acct viable | thousands of trades; dies >$25k | PASS (small only) |
| KC-5 fee-doubled ROI | >0 | +35%/yr | PASS |
| KC-6 category breadth | broad | 4/10 series only (temp+football) | PARTIAL |
| KC-7 live-fill confirmation | fillable at bid | UNTESTED | OPEN |

## Why it's "promising," not "confirmed"

1. **Category concentration.** Driven by temperature (KXHIGH) + football
   (NFL/NCAA). Largest category KXMVEN not significant; golf/F1/Trump flat-to-
   negative. Trade a **category whitelist**, not a blanket band.
2. **Liquidity is the unprovable risk.** Daily OHLC can't tell us if a standing
   bid exists at the daily low when we want to sell, 1 day before settlement.
   The temperature edge (realized-yes ≈ 0) is *selling already-dead brackets* —
   who's the buyer? This is the one thing the backtest cannot resolve.
3. **Small capacity.** ~$840/day sellable (25% depth). Real for $5–15k, dead at
   fund size (−11%/yr at $100k).
4. **Negative skew + window.** Rare longshot-hit clusters; annualized from a
   5-month window that overlaps NFL season (seasonality unproven off-season).

## Recommended next step

Graduate to a **live test at tiny size**, category-whitelisted (temp + NFL/NCAA),
tf≈0.5%. The sole goal: confirm KC-7 — that you can actually get filled selling
these at/near the bid 1 day out. If fills are real, scale to the $5–8k account.
If you can't get filled, it dies here regardless of the backtest.

Tooling: `ingest_low.py` (cheap-band ingest), `resolve_low.py` (de-biased
resolve), `short_sim.py` (collateral-aware sim).
