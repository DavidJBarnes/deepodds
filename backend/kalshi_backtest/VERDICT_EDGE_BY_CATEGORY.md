# Edge-by-inefficiency — VERDICT: thesis REJECTED, but it surfaced a category map worth real money

_2026-06-25_

## One-line

The "longshot-short edge is fattest in the least-efficient/thinnest markets" thesis
**does not hold as a clean law** (edge vs volume Spearman = **−0.36**, wrong
direction). But running it produced something more useful: a per-category
whitelist/blacklist that (1) **protects the live canary from two money-losing
categories** and (2) **identifies sports as the capacity unlock** for the >$25k
death.

## Per-category longshot-short edge (validation 2025-07+, 1-day, daily-low fill, net fee)

| | category | n | edge¢/ct | CI95 | yes% | sell¢ | medVol | cap_vol |
|--|----------|---|----------|------|------|-------|--------|---------|
|✅| crypto | 248 | **+3.50** | [+2.08,+4.93] | 1.2 | 5.7 | 68 | 0.5M |
|✅| climate | 1397 | +1.39 | [+1.11,+1.68] | 0.3 | 2.7 | 395 | 2.2M |
|✅| sports | 4415 | +0.72 | [+0.33,+1.11] | 1.8 | 3.5 | 117 | **57.6M** |
|· | financials/mentions/economics/sci/entertainment | — | +0.2..+0.85 | crosses 0 | — | — | — | — |
|· | exotics | 2138 | −0.55 | [−1.33,+0.24] | 3.6 | — | — | — |
|❌| politics | 528 | **−2.47** | [−4.19,−0.75] | 4.5 | 3.1 | 9 | 5.1M |
|❌| elections | 261 | **−2.49** | [−4.81,−0.17] | 4.2 | 2.7 | 0 | 0.5M |

## Findings (ranked by actionability)

1. **BLACKLIST politics + elections (robust, n=789).** CI-clean **negative** —
   selling these longshots *loses* money. Political/election longshots resolve YES
   *more* than priced (informed flow + fat tails — the opposite behavioral bias).
   The live canary must never short these.
2. **Sports is the capacity unlock (robust).** +0.72¢ CI-clean, n=4415, **57.6M
   cap-vol ≈ 26× climate's 2.2M.** The strategy's binding constraint is capacity
   (dies >$25k); sports is where the size is. Lower per-ct edge than temp but vastly
   more of it.
3. **Crypto is a LEAD, not a green light.** Fattest measured edge (+3.50¢) but rests
   on **3 YES-losses in 248**, and 133/248 are BTC brackets (KXBTC/KXBTCD) — highly
   correlated; one volatile BTC day could flip many YES at once. The tight CI
   understates tail risk. Needs a **dedicated correlation-aware backtest** before any
   capital. Classic negative-skew small-n trap (cf. longshot verdict caveats).
4. **Climate confirmed** (+1.39¢) — consistent with the original temp edge.

## Thesis verdict

Edge is **category-structural, not efficiency-monotonic.** The volume proxy points
the *wrong* way (−0.36; politics is thin AND negative). The spread proxy gives partial
support (Spearman +0.62 — looser/wider markets carry more premium), but category
identity dominates selection. So: select by **category whitelist**, not by an
efficiency score.

## Recommendation (does NOT touch live code without sign-off)

- Live canary category set → **whitelist {climate, sports}** (both robust, CI-clean),
  **blacklist {politics, elections, exotics}**. Sports adds the capacity to scale.
- **Crypto:** open a separate correlation-aware backtest (independent-event sizing,
  BTC-cluster stress) before trading — promising but unproven.

## SPORTS sub-series drill-down (the "57M unlock" was partly an illusion)

The +0.72¢ sports aggregate hides huge dispersion. Per-series (n≥40, validation):

| | series | n | edge¢ | CI95 | medVol | capVol | note |
|--|--------|---|-------|------|--------|--------|------|
|✅| KXATPMATCH (tennis) | 40 | +5.35 | [+4.56,+6.14] | 2881 | 0.97M | fattest+liquid; n=40/0-hits caveat |
|✅| KXNFLSPREAD | 87 | +4.72 | [+1.51,+7.94] | 60 | 0.13M | |
|✅| KXNFL2TD | 233 | +4.48 | [+3.57,+5.38] | 158 | 0.17M | |
|✅| KXNFLFIRSTTD | 500 | +3.43 | [+2.31,+4.56] | 156 | 0.24M | **intended-but-broken in live (see bug)** |
|✅| KXNCAAMBGAME (NCAA bball) | 110 | +2.70 | [+2.13,+3.27] | 1812 | 0.78M | strong, liquid add |
|✅| KXNCAAFGAME | 187 | +2.01 | [+0.58,+3.44] | 14674 | 10.6M | already live; capacity king |
|❌| KXPGATOUR (golf) | 782 | −0.70 | [−1.36,−0.04] | 500 | **13.1M** | **capacity TRAP — biggest sports book, LOSES** |
| | F1 / illiquid (medVol 0) | — | neg/flat | — | — | — | avoid |

The 57.6M sports cap-vol is dominated by **golf (13M, negative)** + NCAAF (10.6M,
already live). True *addable clean* capacity ≈ **3M** (tennis + NCAA bball + NFL-TD
variants). Select by series, never by "category=sports".

## ⚠️ LIVE CONFIG BUG (money-relevant) — discovered en route

`longshot/config.py` whitelists football as `("KXNFLFIRST","KXNFLATD","KXNCAAFGAME")`.
Two of these **do not exist** in Kalshi's series namespace:
- `KXNFLFIRST` → real series is **`KXNFLFIRSTTD`** (+3.43¢ edge, lost)
- `KXNFLATD`   → real series is **`KXNFLANYTD`** / **`KXNFL2TD`** (+4.48¢, lost)
- `KXNCAAFGAME` ✅ exists (the only working football series)

`/markets?series_ticker=KXNFLFIRST` returns nothing → the canary has been trading
**temp + KXNCAAFGAME only; NFL silently OFF.** Verify against the live API (read-only)
then correct the names. This needs sign-off (protected live strategy) but is a clear
leave-money-on-the-table defect.

## Recommended live whitelist (pending sign-off)

`KXHIGH*` (temp) + `KXNCAAFGAME` + **fix→** `KXNFLFIRSTTD`, `KXNFLANYTD`/`KXNFL2TD`,
`KXNFLSPREAD` + **add→** `KXNCAAMBGAME`, `KXATPMATCH`. Explicit blacklist (never trade):
`KXPGATOUR`, golf/F1, politics, elections.

Tooling: `edge_by_efficiency.py` (+ inline sports/NFL-name drill-downs).
