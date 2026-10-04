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
    if k == "oracle.tail14d.gap_settled_c" and v < -0.2:
        out.append(_obs("oracle.tail_thesis_inverted", metric,
            what=(f"Over {c.get('n','?')} BTC/ETH tails settled in the last 14 days, Kalshi sold at "
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
    if k == "oracle.tail30d.calib_err_mid_c" and v > 2.0:
        out.append(_obs("oracle.mid_tail_underpriced", metric,
            what=(f"Kalshi 3-5c tails resolved YES {c.get('actual_yes_pct','?')}% but charge only "
                  f"{c.get('charge_c','?')}c over the last 30 days — underpriced by {v:.1f}c (n={c.get('n','?')})."),
            why=("Selling this band is a structural loser and the single worst pocket for a tail "
                 "seller — realized frequency runs well above the price."),
            nxt="Verify the sell gate excludes this band; quantify its share of blind-sell loss.",
            caveat="n is modest; tail outcomes are correlated.",
            surprise=STRUCTURAL_SALIENCE + min(v / 2, 3.0)))

    # -- blind tail selling is a net loser -----------------------------------------
    # Day-clustered: one big BTC/ETH move settles hundreds of tails YES together, so a
    # single bad day used to fire this at -16c. Only a loss that survives the clustered
    # SE (v + 2se < 0) is a statement about blind selling rather than about one move.
    se = c.get("se_c")
    if (k == "oracle.tail14d.blind_sell_ev_c" and v < -0.5
            and (se is None or v + 2 * se < 0)):
        out.append(_obs("oracle.blind_sell_negative", metric,
            what=(f"Blind-selling every captured tail at bid returned {v:.2f}c/contract over the last "
                  f"14 days (n={c.get('n','?')} over {c.get('n_days','?')} days, day-clustered SE {se}c)."),
            why="Confirms the crypto-tail edge is entirely in selection (the gate), not in tails broadly.",
            nxt="Compare against oracle.tail14d.gated_ev_c over the same window.",
            caveat="Outcomes cluster by settlement day; the SE is clustered, but 14 days is still few clusters.",
            surprise=STRUCTURAL_SALIENCE + min(abs(v), 2.0)))

    # -- the oracle gate itself is not clearing ------------------------------------
    if k == "oracle.tail14d.gated_ev_c" and v < 0 and c.get("n", 0) >= 30:
        out.append(_obs("oracle.gate_not_clearing", metric,
            what=(f"Tails the oracle gate would sell (entry bid >= Deribit fair + {c.get('min_edge_c','?')}c) "
                  f"returned {v:.2f}c/contract over the last 14 days (n={c.get('n','?')}, "
                  f"{c.get('yes_pct','?')}% YES, day-clustered SE {c.get('se_c')}c)."),
            why=("The crypto-tail case rests on selection: blind selling loses, the gate is supposed "
                 "to win. A negative gated EV means the selection isn't paying in the current regime."),
            nxt=("Check persistence first. If it holds, split gated tails by OTM distance and hours-to-"
                 "close — the 2026-07-10 loss was all near-money tails the OTM floor now excludes, and "
                 "this proxy has no OTM floor."),
            caveat=("Proxy, not the live arm: uses entry bid (stricter than the live mid test) and no "
                    "OTM floor. Few independent days."),
            surprise=STRUCTURAL_SALIENCE + min(abs(v), 2.0)))

    # -- live longshot fills adversely selected vs paper twin -----------------------
    if k == "longshot.adverse.paper_minus_live_hit_14d" and v > 0.02:
        out.append(_obs("longshot.adverse_selection", metric,
            what=(f"Live longshot fills resolve YES {c.get('live_yes_pct','?')}% vs the paper twin's "
                  f"{c.get('paper_yes_pct','?')}% over the last 14 days — live is getting the worse brackets."),
            why=("Classic adverse selection: we get filled disproportionately on brackets that go on "
                 "to resolve YES. This is the exact paper->live gap that killed the favorites strategy."),
            nxt="Break live YES-rate down by OI / time-of-day / quote-distance to localise the leak.",
            caveat="Live n is small; a few YES settlements swing this. Watch persistence.",
            surprise=STRUCTURAL_SALIENCE + min(v * 20, 3.0)))

    # -- live slippage creeping ----------------------------------------------------
    if k == "longshot.live.slippage_14d_c" and v > 0.5:
        out.append(_obs("longshot.slippage_creep", metric,
            what=f"Live avg slippage is {v:.2f}c over the last 14 days ({c.get('orders','?')} orders).",
            why="Slippage eats the thin longshot edge directly; the clean-fill assumption is drifting.",
            nxt="Diff intended vs actual fills this week; check if it's size- or hour-driven.",
            caveat="Sign convention: negative = price improvement, positive = paying up.",
            surprise=STRUCTURAL_SALIENCE + min(v, 2.0)))

    # -- live longshot net-negative over a month -------------------------------------
    if k == "longshot.live.pnl_30d" and v < 0 and c.get("n", 0) >= 100:
        out.append(_obs("longshot.live_pnl_negative", metric,
            what=(f"Live longshot realized ${v:.2f} over the last 30 days on {c.get('n','?')} settled "
                  f"positions (NO hit rate {c.get('hit_rate_no','?')}, ${c.get('per_trade','?')}/trade)."),
            why=("The live edge was re-baselined at ~break-even (+0.22c/ct); a month net-negative is the "
                 "edge sitting at or below zero, not one bad settlement day."),
            nxt=("Do NOT retune live from this — take it to the scheduled longshot review. Split the window "
                 "by category and by pre/post sizing changes; compare the paper twin over the same window."),
            caveat=("Dollar P&L scales with position size, so windows straddling a sizing change aren't "
                    "comparable; the hit rate is size-independent."),
            surprise=STRUCTURAL_SALIENCE + min(abs(v) / 50, 2.0)))

    # -- data quality: bookrec is banking nulls ------------------------------------
    if k == "dq.bookrec.populated_frac" and v < 0.01:
        out.append(_obs("dq.bookrec_broken", metric,
            what=(f"bookrec captured {c.get('populated',0)}/{c.get('total',0)} populated books in "
                  f"{c.get('file','?')} — {v:.0%} usable."),
            why=("The order-book recorder is banking nulls, so every book-microstructure metric "
                 "is blind. This fired once before (2026-07-29) as a client-side key mismatch: "
                 "Kalshi renamed the depth payload orderbook -> orderbook_fp {yes_dollars,no_dollars} "
                 "and bookrec kept reading the old key. The endpoint itself was healthy throughout."),
            nxt=("Check the raw response keys FIRST — curl /markets/{ticker}/orderbook on a high-OI "
                 "market and compare against what snapshot() reads. Assume a rename before assuming "
                 "a dead endpoint; the depth is worth far more than the top-of-book fallback."),
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
