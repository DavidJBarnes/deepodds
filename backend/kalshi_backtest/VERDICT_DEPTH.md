# Depth-as-safety backtest — VERDICT

**Trigger:** live canary at n=133 (2026-06-29) ran **-1.89¢/ct** while the paper twin
ran +0.57¢ on the *identical 133 markets*. The 9 YES losers all had thin bid depth and
got sized ~1ct in paper's depth-proportional sizing — suggesting "depth = safety, size
by depth" as the fix. Backtest-first before touching live.

Data: cheap-band (1-12¢) 1-day shorts, validation window (settle ≥ 2025-07-01),
daily-low fill, deduped per ticker, **n=12,034**. Proxies for bid depth = entry-day
**volume** and **open interest** (instantaneous bid depth isn't in the shards).

## Result 1 — the naive "size/select by depth" fix is FALSIFIED ❌

Filtering FOR more liquidity *destroys* the edge:

| min entry_vol | kept | YES% | net ¢/ct |
|---|---|---|---|
| 0 (all) | 100% | 2.1% | **+0.40 CLEAN+** |
| ≥1,000 | 23% | 3.0% | **−1.25** |
| ≥5,000 | 9% | 2.6% | **−1.35** |

More volume → *higher* YES rate (Spearman vol-vs-YES **+0.26**). Preferring deep books
would have made things WORSE. **Do NOT evolve the canary to depth-weighted sizing.**
The live observation (losers had thin bids) does not generalize — at n=9 it was either
noise or a within-temp microstructure effect, not a tradable rule.

## Result 2 — Open Interest IS a clean, robust selection signal ✅ (about PREMIUM, not safety)

Low-OI longshots carry **fatter premium** at similar YES rates → much better edge.
Spearman OI-vs-pnl **−0.40**.

| OI quintile | YES% | avg sell | net ¢/ct |
|---|---|---|---|
| lowest (thin) | 1.4% | **5.13¢** | **+2.76 CLEAN+** |
| … | | | |
| highest (thick) | 1.7% | 2.14¢ | −0.52 CLEAN− |

Mechanism: it's not "low-OI is safer" (YES rates are flat ~1-2%) — it's **low-OI markets
stay mispriced fatter** (5.1¢ premium vs 2.1¢) because few sophisticated players are in
them. Holds *within* nearly every category (low-OI half beats high-OI half): climate
+1.85 vs +0.94, crypto +5.15 vs +1.86, other +1.84 vs +0.63, exotics +0.90 vs −2.00.
**Actionable: prefer LOW open-interest entries.** This ~doubles temp edge and is the real
lever — but it's a SELECTION filter, not a sizing change.

## Result 3 — the live canary's actual problem: a YES-rate blowout ⚠️

Historical cheap-band **climate/temp YES rate = 0.3%** (≈4 of 1,397), net **+1.39¢**, and
even the high-OI half is +0.94¢ positive. **Live temp YES rate = 6.8% (9/133) — ~20× the
historical base rate.** That, not fills (100%, ~0 slip) and not sizing, is why live is red.

Most likely a **selection/seasonal mismatch**: the backtest's 1-12¢ *price* band captures
genuine deep-tail brackets (almost never hit), but the live canary sells the 1-12¢ *YES
bid* on active **summer** temp markets, which includes near-money B-brackets that are
truly 5-10% likely when a heat wave widens the distribution. Same nominal price, very
different true risk. Can't fully separate seasonal-heat vs bracket-selection until the
book diversifies past summer-temp-only (sports return Sept).

## Result 4 — end-to-end bankroll sim: low-OI filter is a big, clean win ✅

Same canonical `run_short_sim` (cap=$8k, hz=1d, collateral/depth/capital-aware), pre-
filtered by OI:

| variant | trades | per-ct net edge | annROI* | **MaxDD** |
|---|---|---|---|---|
| ALL (baseline) | 6,056 | +0.40¢ CLEAN+ | +87% | **33.9%** |
| OI ≤ median | 4,076 | +1.13¢ CLEAN+ | +246% | 22.9% |
| **OI bottom 40%** | 3,453 | **+1.77¢ CLEAN+** | +339% | **4.8%** |
| OI bottom 20% | 1,939 | +2.76¢ CLEAN+ | +93%† | 1.2% |

\*ROI is the negative-skew/fee-batching optic we distrust — read it as directional only.
†bottom-20% under-deploys capital (too few trades), so ROI falls despite the best edge.

**Sweet spot = OI bottom ~40%:** ~4× the per-contract edge (+0.40→+1.77¢, CI-clean) AND
**MaxDD 33.9%→4.8%** — the fat-tail YES losses largely disappear because low-OI markets are
also the fattest-premium-for-risk. Bonus: it *lowers* YES rate (2.1%→1.7%), which is exactly
the direction the live blowout needs.

## Bottom line

- Backtesting saved us from the wrong fix (depth-weighting would hurt). ✅ standing rule.
- Real lever found: **low-OI selection filter** (clean, cross-category, ~2× temp edge).
- Real problem identified: **live summer-temp YES rate is 20× the historical base** — a
  selection/seasonal effect a low-OI filter helps but won't fully cure.
- **Low-OI filter validated end-to-end** (Result 4): OI-bottom-40% ~4× edge + MaxDD
  34%→5%, CI-clean. This is a real, tested SELECTION lever for the longshot strategy.

**Next (respecting the standing rules — never alter live longshot without heavy coverage):**
1. Add an OI cap as a config-gated entry filter in discovery (`size_candidate`/discover),
   default OFF, with unit tests.
2. Ship to the PAPER container first; run paper-with-filter vs paper-without as an A/B for
   ~1-2 weeks. Only promote to live after the paper A/B confirms.
3. Independent of OI: keep watching whether the live summer-temp YES blowout (6.8% vs 0.3%)
   is seasonal as the book diversifies into sports (Sept).

Reusable: `depth_backtest.py` (`build_records` carries entry_vol + entry_oi + dates;
`by_category_oi()` within-category cut; `end_to_end()` bankroll sim with OI filter).
