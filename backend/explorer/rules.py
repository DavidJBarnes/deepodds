"""Observation rules — the analyst layer that turns a metric into insight.

Two kinds:
  * STRUCTURAL rules (hand-authored) fire when a known-meaningful metric crosses a
    line that carries a specific, explainable meaning. Each writes real framing:
    what happened / why it's notable / the next thing to investigate / the caveat.
    Observation #1 (the crypto-tail thesis inversion) is one of these — it fires on
    the real settled data, it is not hard-coded.
  * The DEVIATION rule is generic: any metric whose value is a robust-z outlier vs its
    own trailing baseline becomes a templated "unusual move, worth a look" observation.

An observation is a plain dict: {rule_key, metric_key, value, what, why_notable,
next_step, caveat, kind, surprise}. `rule_key` is stable — it drives the streak counter
and the idempotent ledger id. `surprise` feeds the surprise x persistence ranking.
"""
from __future__ import annotations

Z_THRESHOLD = 2.5           # |robust z| above which a generic deviation is notable
STRUCTURAL_SALIENCE = 3.0   # base surprise for a fired structural rule


def _obs(rule_key, metric, *, what, why, nxt, caveat, surprise, kind="structural") -> dict:
    return {"rule_key": rule_key, "metric_key": metric.key, "value": metric.value,
            "what": what, "why_notable": why, "next_step": nxt, "caveat": caveat,
            "kind": kind, "surprise": round(float(surprise), 3)}


def structural_rules(metric) -> list[dict]:
    k, v, c = metric.key, metric.value, metric.context
    out: list[dict] = []

    # -- Observation #1: founding crypto-tail thesis has inverted in settled data ----
    if k == "oracle.tail.gap_settled_c" and v < -0.2:
        out.append(_obs("oracle.tail_thesis_inverted", metric,
            what=(f"Over the last {c.get('n','?')} settled BTC/ETH tails, Kalshi sold at "
                  f"{c.get('kalshi_c','?')}c vs Deribit-fair {c.get('deribit_c','?')}c — "
                  f"Kalshi is priced BELOW Deribit ({v:+.2f}c)."),
            why=("The founding crypto-tails thesis was the exact opposite: Kalshi OVER-prices "
                 "tails (+1.18c snapshot, 2026-07-08). In forward settlement that unconditional "
                 "edge has inverted — the same snapshot-bias error class that burned favorites, "
                 "longshot, and climate."),
            nxt=("Compare gated (Kalshi>Deribit) EV vs blind EV over the same window: is the +1c "
                 "edge alive only in the gated subset, or dead? Downweight the crypto-tails arm "
                 "if gated no longer clears."),
            caveat=("Tail outcomes are correlated (one BTC move settles many YES together); short "
                    "forward window; Deribit N(d2) fair is an approximation."),
            surprise=STRUCTURAL_SALIENCE + min(abs(v), 3.0)))

    # -- mid-tail (3-5c) underpriced vs realized -----------------------------------
    if k == "oracle.tail.calib_err_mid_c" and v > 2.0:
        out.append(_obs("oracle.mid_tail_underpriced", metric,
            what=(f"Kalshi 3-5c tails resolved YES {c.get('actual_yes_pct','?')}% but charge only "
                  f"{c.get('charge_c','?')}c — underpriced by {v:.1f}c (n={c.get('n','?')})."),
            why=("Selling this band is a structural loser and the single worst pocket for a tail "
                 "seller — realized frequency runs well above the price."),
            nxt="Verify the sell gate excludes this band; quantify its share of blind-sell loss.",
            caveat="n is modest; tail outcomes are correlated.",
            surprise=STRUCTURAL_SALIENCE + min(v / 2, 3.0)))

    # -- blind tail selling is a net loser -----------------------------------------
    if k == "oracle.tail.blind_sell_ev_c" and v < -0.5:
        out.append(_obs("oracle.blind_sell_negative", metric,
            what=f"Blind-selling every captured tail at bid returns {v:.2f}c/contract over the last {c.get('n','?')}.",
            why="Confirms the crypto-tail edge is entirely in selection (the gate), not in tails broadly.",
            nxt="Track gated-only EV separately to confirm selection still adds value.",
            caveat="Short window; correlated outcomes.",
            surprise=STRUCTURAL_SALIENCE + min(abs(v), 2.0)))

    # -- live longshot fills adversely selected vs paper twin -----------------------
    if k == "longshot.adverse.paper_minus_live_hit" and v > 0.02:
        out.append(_obs("longshot.adverse_selection", metric,
            what=(f"Live longshot fills resolve YES {c.get('live_yes_pct','?')}% vs the paper twin's "
                  f"{c.get('paper_yes_pct','?')}% — live is getting the worse brackets."),
            why=("Classic adverse selection: we get filled disproportionately on brackets that go on "
                 "to resolve YES. This is the exact paper->live gap that killed the favorites strategy."),
            nxt="Break live YES-rate down by OI / time-of-day / quote-distance to localise the leak.",
            caveat="Live n is small; a few YES settlements swing this. Watch persistence.",
            surprise=STRUCTURAL_SALIENCE + min(v * 20, 3.0)))

    # -- live slippage creeping ----------------------------------------------------
    if k == "longshot.live.avg_slippage_c" and v > 0.5:
        out.append(_obs("longshot.slippage_creep", metric,
            what=f"Live avg slippage is {v:.2f}c over {c.get('orders','?')} orders.",
            why="Slippage eats the thin longshot edge directly; the clean-fill assumption is drifting.",
            nxt="Diff intended vs actual fills this week; check if it's size- or hour-driven.",
            caveat="Sign convention: negative = price improvement, positive = paying up.",
            surprise=STRUCTURAL_SALIENCE + min(v, 2.0)))

    # -- data quality: bookrec is banking nulls ------------------------------------
    if k == "dq.bookrec.populated_frac" and v < 0.01:
        out.append(_obs("dq.bookrec_broken", metric,
            what=(f"bookrec captured {c.get('populated',0)}/{c.get('total',0)} populated books in "
                  f"{c.get('file','?')} — {v:.0%} usable."),
            why=("The order-book recorder is banking nulls: Kalshi migrated the depth endpoint to "
                 "orderbook_fp {yes_dollars,no_dollars} and it returns null even for 700k-OI markets. "
                 "Days of captures are unusable and every book-microstructure metric is blind."),
            nxt=("Re-point bookrec to store market top-of-book (yes_bid_dollars / yes_ask_dollars / "
                 "oi_fp), which the market-list endpoint DOES return, then build spread/liquidity metrics."),
            caveat="Data-quality flag, not a market signal.",
            surprise=STRUCTURAL_SALIENCE, kind="data_quality"))

    return out


def deviation_rule(metric, z_info: dict | None) -> dict | None:
    """Generic: any metric that is a robust-z outlier vs its own trailing baseline."""
    if z_info is None:
        return None
    z = z_info["z"]
    if abs(z) < Z_THRESHOLD:
        return None
    direction = "up" if z > 0 else "down"
    return _obs(f"deviation:{metric.key}", metric,
        what=(f"{metric.key} moved {direction} to {metric.value} "
              f"({z:+.1f}sigma vs its {z_info['n']}-day baseline of {round(z_info['median'], 4)})."),
        why="A statistically unusual shift for this metric versus its own recent history — worth a look at what changed.",
        nxt=f"Inspect the underlying rows behind {metric.key} for the run date.",
        caveat=f"Baseline is only {z_info['n']} days; z is provisional. Persistence over further days is the real test.",
        surprise=abs(z), kind="deviation")
