# VERDICT: the longshot backtest data source is cheap-selection-biased

**Date:** 2026-07-04. **Severity:** high — re-anchors the entire longshot edge estimate.

## What we found

Reconciling why the live-forward OI split disagreed with backtest #209, we uncovered a
selection bias in the backtest's data source itself (`s3_markets_low`).

| measure | value |
|---|---|
| KXHIGH temp YES rate — full settlement cache (all brackets) | **8.0%** (222 / 2,773) |
| KXHIGH temp YES rate — backtest's band-selected records | **0.0%** (0 / 1,271) |
| KXHIGH markets priced >12¢ on last active day → resolved YES | **0 of 709** |
| KXHIGH temp YES rate — LIVE canary (real, forward) | **4.3%** |

A calibrated market priced at 1–12¢ must resolve YES ~1–12% of the time. The backtest
showing **0.0%** — and 709 markets that were *expensive* near settlement all resolving
NO — is impossible for real calibrated markets. It's an artifact.

## Root cause

`s3_markets_low` is a **cheap-selected ingest** (it pulled only markets trading in the
low band). A longshot bracket that is actually heading to YES **rises in price** as it
approaches a hit, so it leaves the cheap band and drops out of the shard histories. The
settlement cache (full universe) still records those YES outcomes — hence 8% overall —
but the price histories the backtest builds its dataset from **systematically omit the
YES-bound brackets.** The surviving sample is almost all NO-resolving markets.

## Consequences

1. **The longshot-short edge was overstated.** VERDICT_LONGSHOT's +0.4→+2.6¢/ct rested
   on a NO-biased sample. The honest edge is what the LIVE canary shows: **~break-even,
   currently +0.22¢/ct** (n≈276). Live is not underperforming a real +1.9¢ — the +1.9¢
   was never real.
2. **The #209 OI signal is an artifact for this regime.** With ~0% losses in the data,
   "low-OI wins" only ranked fatter premium (2.9¢ vs 1.9¢ sell); it never tested
   loss-avoidance because there were no losses to avoid. So #209 cannot adjudicate the OI
   question in either direction.
3. **Live-forward is the only unbiased evidence.** It has real losses (4.3% YES) and says
   the OPPOSITE of #209: **HIGH open interest is the safer bucket** (within-book, two
   independent books agree): YES 1.3% vs 4.7%, +3.2¢ vs −1.0¢ per contract.

## Actions taken

- **Re-baselined expectations:** live ~break-even is the true edge, not a shortfall.
- **Flipped the paper-oi A/B arm from LOW-OI to HIGH-OI** (`LONGSHOT_OI_KEEP_HIGH=true`)
  to forward-test the inverted thesis where losses are actually observable. Control stays
  unfiltered; live untouched.
- **This doc** so no future strategy is validated on `s3_markets_low` without correcting
  the cheap-selection bias first.

## Open follow-ups (backtest-first, not yet done)

- Rebuild a longshot dataset from a **settlement-complete universe** (start from the
  settlement cache / a full-book ingest, then look up entry prices) so the YES-bound
  brackets are present. Re-run the edge + OI question on that. Until then, **trust
  live-forward over the backtest** for anything loss-sensitive.
- Re-check whether the FAVORITES verdict and any other longshot-era conclusion drawn from
  `s3_markets_*` share this bias.

Related: [[project_kalshi_longshot]], [[project_longshot_live]], VERDICT_DEPTH.md,
VERDICT_LONGSHOT.md.
