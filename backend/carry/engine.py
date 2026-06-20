"""Funding-carry paper engine: funding accrual, funding-gated sizing, margin
top-up, liquidation/kill-switch. Pure-ish functions + a tick orchestrator."""
import logging

from carry.config import CarryConfig
from carry.models import CarryPosition, PaperPortfolio

logger = logging.getLogger("carry.engine")
PERIODS_PER_YEAR = 24 * 365


def build_snapshot(pf: PaperPortfolio, ctx: dict[str, dict],
                   trailing: dict[str, float | None], cfg: CarryConfig) -> dict:
    """Structured, auditable view of portfolio + per-symbol state after a tick.

    Used by both the one-shot runner and the loop's history record so the
    numbers we print and the numbers we persist are identical.
    """
    marks = {s: c["mark"] for s, c in ctx.items() if c.get("mark")}
    syms = {}
    for s in cfg.symbols:
        c = ctx.get(s, {})
        tr = trailing.get(s)
        pos = pf.positions.get(s)
        mark = marks.get(s, pos.entry_perp if pos else None)
        syms[s] = {
            "funding_ann": (c.get("funding") or 0.0) * PERIODS_PER_YEAR,
            "trailing_ann": tr,
            "target": target_notional(tr, cfg),
            "notional": pos.notional(mark) if (pos and mark) else 0.0,
            "margin_ratio": pos.margin_ratio(mark) if (pos and mark) else None,
            "accrued_funding": pos.accrued_funding if pos else 0.0,
        }
    return {
        "ts": pf.last_tick_ts,
        "cash": pf.cash_usd,
        "equity": pf.equity(marks),
        "accrued_funding_total": pf.accrued_funding_total,
        "realized_pnl": pf.realized_pnl,
        "fees_total": pf.fees_total,
        "killed": pf.killed,
        "symbols": syms,
    }


def target_notional(trailing_ann: float | None, cfg: CarryConfig) -> float:
    """Funding-gated target notional for one symbol.

    Flat below the hurdle; ramps linearly to max between hurdle and `rich`.
    This is what keeps us OUT of thin regimes (like the current one).
    """
    if trailing_ann is None or trailing_ann < cfg.min_funding_hurdle_ann:
        return 0.0
    span = max(cfg.rich_funding_ann - cfg.min_funding_hurdle_ann, 1e-9)
    frac = min(1.0, (trailing_ann - cfg.min_funding_hurdle_ann) / span)
    return cfg.max_notional_per_symbol * frac


def accrue_funding(pos: CarryPosition, hourly_rate: float, mark: float, hours: float) -> float:
    """Accrue funding over `hours`. Short RECEIVES when rate>0, pays when <0."""
    cashflow = hourly_rate * pos.notional(mark) * hours
    pos.accrued_funding += cashflow
    return cashflow


def manage_margin(pos: CarryPosition, mark: float, cfg: CarryConfig) -> float:
    """Top up HL margin from reserve when the ratio drops. Returns USDC moved."""
    ratio = pos.margin_ratio(mark)
    if ratio >= cfg.topup_trigger_ratio or pos.reserve <= 0:
        return 0.0
    target_equity = pos.notional(mark) / cfg.target_leverage
    need = target_equity - pos.hl_equity(mark)
    moved = max(0.0, min(need, pos.reserve))
    pos.hl_margin += moved
    pos.reserve -= moved
    return moved


def open_position(pf: PaperPortfolio, symbol: str, mark: float, notional: float, cfg: CarryConfig,
                  fill_perp: float | None = None, fill_spot: float | None = None) -> CarryPosition:
    # Short perp fills at the bid, long spot at the ask (cross the spread).
    fp = fill_perp if fill_perp is not None else mark
    fs = fill_spot if fill_spot is not None else mark
    qty = notional / fs
    margin = notional / cfg.target_leverage
    reserve = notional * cfg.reserve_frac
    fees = notional * cfg.taker_fee_frac * (cfg.legs_per_round_trip / 2)  # open = 2 legs
    committed = qty * fs + margin + reserve + fees
    pos = CarryPosition(
        symbol=symbol, coin_qty=qty, entry_perp=fp, entry_spot=fs,
        hl_margin=margin, reserve=reserve, fees_paid=fees, opened_ts=pf.last_tick_ts,
    )
    pf.cash_usd -= committed
    pf.fees_total += fees
    pf.positions[symbol] = pos
    basis_bps = (fp - fs) / fs * 10_000 if fs else 0.0
    pf.log.append(f"OPEN {symbol} notional=${notional:.0f} qty={qty:.5f} perp@${fp:.2f} spot@${fs:.2f} "
                  f"basis={basis_bps:+.1f}bps (lev {cfg.target_leverage}x)")
    return pos


def close_position(pf: PaperPortfolio, symbol: str, mark: float, cfg: CarryConfig, reason: str,
                   exit_perp: float | None = None, exit_spot: float | None = None) -> None:
    pos = pf.positions.pop(symbol)
    # Buy back perp at the ask, sell spot at the bid.
    ep = exit_perp if exit_perp is not None else mark
    es = exit_spot if exit_spot is not None else mark
    close_fees = pos.coin_qty * es * cfg.taker_fee_frac * (cfg.legs_per_round_trip / 2)
    # Realized P&L with actual exit fills: spot + perp legs + funding - all fees.
    spot_pnl = pos.coin_qty * (es - pos.entry_spot)
    perp_pnl = pos.coin_qty * (pos.entry_perp - ep)
    realized = spot_pnl + perp_pnl + pos.accrued_funding - (pos.fees_paid + close_fees)
    returned = pos.coin_qty * es + (pos.hl_margin + pos.accrued_funding + perp_pnl) + pos.reserve - close_fees
    pf.cash_usd += returned
    pf.realized_pnl += realized
    pf.fees_total += close_fees
    pf.log.append(f"CLOSE {symbol} ({reason}) pnl=${realized:.2f} funding=${pos.accrued_funding:.4f}")


def rebalance(pf: PaperPortfolio, ctx: dict[str, dict],
              trailing: dict[str, float | None], cfg: CarryConfig, now_ts: float) -> None:
    """Two-tier leverage rebalancing for all open positions.

    Called once per tick after funding accrual and manage_margin, before the
    liquidation check. Fires when effective leverage exceeds cfg.max_leverage_band
    (typically triggered by an adverse price move on the perp short).

    Tier A (fee-free): transfer cash from pf.cash_usd into pos.hl_margin to
    restore target leverage. Respects cfg.cash_floor_frac × paper_capital_usd as
    a minimum free-cash floor.

    Tier B (real fills): if Tier A cannot fully restore the band (cash floor hit),
    close the position via close_position() and, if the funding gate still warrants
    deployment, reopen via open_position(). All four legs incur taker fees.

    Appends REBALANCE_TOPUP / REBALANCE_RECENTER entries to pf.log.
    Increments pf.rebalance_topup_count, pf.rebalance_recenter_count, and
    pf.rebalance_fees_usd (Tier-B only).
    """
    if not pf.positions:
        return
    cash_floor = cfg.paper_capital_usd * cfg.cash_floor_frac
    marks = {s: c["mark"] for s, c in ctx.items() if c.get("mark")}

    for sym in list(pf.positions.keys()):
        pos = pf.positions.get(sym)
        if pos is None:
            continue
        c = ctx.get(sym)
        if not c or c.get("mark") is None:
            continue
        mark = c["mark"]

        hl_eq = pos.hl_equity(mark)
        if hl_eq <= 0:
            continue  # negative equity: liquidation check handles it
        lev = pos.notional(mark) / hl_eq
        if lev <= cfg.max_leverage_band:
            continue

        lev_before = lev

        # Tier A: fee-free cash → hl_margin injection
        target_eq = pos.notional(mark) / cfg.target_leverage
        needed = target_eq - hl_eq
        available = pf.cash_usd - cash_floor
        transfer = min(needed, max(0.0, available))
        if transfer > 0:
            pos.hl_margin += transfer
            pf.cash_usd -= transfer
            hl_eq = pos.hl_equity(mark)
            lev = pos.notional(mark) / hl_eq if hl_eq > 0 else float("inf")
            pf.rebalance_topup_count += 1
            pf.log.append(
                f"REBALANCE_TOPUP {sym} transfer=${transfer:.4f} "
                f"lev={lev_before:.3f}→{lev:.3f} ts={now_ts:.0f}"
            )

        if lev <= cfg.max_leverage_band:
            continue  # Tier A was sufficient

        # Tier B: close + conditionally reopen at target size
        fees_before = pf.fees_total
        close_position(pf, sym, mark, cfg, "rebalance recenter",
                       exit_perp=c.get("perp_ask"), exit_spot=c.get("spot_bid"))
        tgt = target_notional(trailing.get(sym), cfg)
        if tgt > 0:
            committed_estimate = (
                tgt * (1 + 1 / cfg.target_leverage + cfg.reserve_frac)
                + tgt * cfg.taker_fee_frac * (cfg.legs_per_round_trip / 2)
            )
            if (pf.total_notional(marks) + tgt <= cfg.max_total_notional_usd
                    and pf.cash_usd >= committed_estimate):
                open_position(pf, sym, mark, tgt, cfg,
                              fill_perp=c.get("perp_bid"), fill_spot=c.get("spot_ask"))
        recenter_fees = pf.fees_total - fees_before
        pf.rebalance_fees_usd += recenter_fees
        pf.rebalance_recenter_count += 1
        pf.log.append(
            f"REBALANCE_RECENTER {sym} lev_before={lev_before:.3f} "
            f"fees=${recenter_fees:.4f} ts={now_ts:.0f}"
        )


def resize_position(pf: PaperPortfolio, symbol: str, new_notional: float,
                    mark: float, cfg: CarryConfig, marks: dict[str, float],
                    fill_perp_bid: float, fill_spot_ask: float,
                    fill_perp_ask: float, fill_spot_bid: float) -> str | None:
    """Adjust an open position's notional toward new_notional.

    Resize UP  (new > current): fee-bearing additional perp short + spot buy.
                Weighted-average entry prices updated; proportional margin+reserve
                drawn from cash. Respects cash_floor_frac and max_total_notional_usd.
    Resize DOWN (new < current): proportional partial close at exit fills.
                Realized P&L, fees, and returned cash are booked correctly.
                Does NOT close to zero — exit gate handles full exit.

    Returns 'resize_up', 'resize_down', or None if no adjustment made.
    Increments pf.resize_up_count / pf.resize_down_count / pf.resize_fees_usd.
    """
    pos = pf.positions.get(symbol)
    if pos is None:
        return None

    current_notional = pos.coin_qty * mark
    delta = new_notional - current_notional

    if delta > 0:
        # --- Resize UP ---
        add_notional = delta
        add_qty = add_notional / fill_spot_ask
        add_margin = add_notional / cfg.target_leverage
        add_reserve = add_notional * cfg.reserve_frac
        fees = add_notional * cfg.taker_fee_frac * (cfg.legs_per_round_trip / 2)
        committed = add_qty * fill_spot_ask + add_margin + add_reserve + fees
        cash_floor = cfg.paper_capital_usd * cfg.cash_floor_frac

        if pf.cash_usd - committed < cash_floor:
            return None  # insufficient free cash
        if pf.total_notional(marks) + add_notional > cfg.max_total_notional_usd:
            return None  # would exceed portfolio notional cap

        # Weighted-average entry prices
        old_qty = pos.coin_qty
        new_qty = old_qty + add_qty
        pos.entry_perp = (old_qty * pos.entry_perp + add_qty * fill_perp_bid) / new_qty
        pos.entry_spot = (old_qty * pos.entry_spot + add_qty * fill_spot_ask) / new_qty
        pos.coin_qty = new_qty
        pos.hl_margin += add_margin
        pos.reserve += add_reserve
        pos.fees_paid += fees
        pf.cash_usd -= committed
        pf.fees_total += fees
        pf.resize_fees_usd += fees
        pf.resize_up_count += 1
        pf.log.append(
            f"RESIZE_UP {symbol} notional=${current_notional:.0f}→${new_notional:.0f} "
            f"add_qty={add_qty:.6f} fees=${fees:.4f}"
        )
        return "resize_up"

    elif delta < 0:
        # --- Resize DOWN ---
        remove_frac = -delta / current_notional
        if remove_frac >= 0.999:
            return None  # effectively full exit — let the exit gate close cleanly

        remove_qty = pos.coin_qty * remove_frac
        perp_pnl = remove_qty * (pos.entry_perp - fill_perp_ask)
        spot_pnl = remove_qty * (fill_spot_bid - pos.entry_spot)
        funding_portion = pos.accrued_funding * remove_frac
        fees_open_portion = pos.fees_paid * remove_frac
        close_fees = remove_qty * fill_spot_bid * cfg.taker_fee_frac * (cfg.legs_per_round_trip / 2)

        realized = spot_pnl + perp_pnl + funding_portion - fees_open_portion - close_fees
        returned = (
            remove_qty * fill_spot_bid
            + (pos.hl_margin + pos.accrued_funding) * remove_frac
            + perp_pnl
            + pos.reserve * remove_frac
            - close_fees
        )

        # Scale the position down in place (all attributes proportional)
        scale = 1 - remove_frac
        pos.coin_qty        *= scale
        pos.hl_margin       *= scale
        pos.reserve         *= scale
        pos.accrued_funding *= scale
        pos.fees_paid       *= scale

        pf.cash_usd       += returned
        pf.realized_pnl   += realized
        pf.fees_total     += close_fees
        pf.resize_fees_usd += close_fees
        pf.resize_down_count += 1
        pf.log.append(
            f"RESIZE_DOWN {symbol} notional=${current_notional:.0f}→${new_notional:.0f} "
            f"frac={remove_frac:.3f} fees=${close_fees:.4f}"
        )
        return "resize_down"

    return None


def tick(pf: PaperPortfolio, ctx: dict[str, dict], trailing: dict[str, float | None],
         cfg: CarryConfig, now_ts: float) -> None:
    """One engine tick on live data. ctx[sym]={funding,mark}; trailing[sym]=ann funding."""
    # cfg.halt_on_kill=True (live default) permanently halts after a kill event.
    # cfg.halt_on_kill=False (backtest) allows the replay driver to clear pf.killed
    # between ticks so measurement continues after a kill event.
    if pf.killed and cfg.halt_on_kill:
        return
    hours = (now_ts - pf.last_tick_ts) / 3600 if pf.last_tick_ts else 0.0
    hours = max(0.0, min(hours, 24.0))  # clamp (cold start / long gaps)

    # 1. Accrue funding + manage existing margin (no liquidation check yet).
    for sym, pos in list(pf.positions.items()):
        c = ctx.get(sym)
        if not c or c["mark"] is None:
            continue
        mark = c["mark"]
        cf = accrue_funding(pos, c["funding"], mark, hours)
        pf.accrued_funding_total += cf
        manage_margin(pos, mark, cfg)

    # 2. Two-tier rebalancing: called after accrual, before liquidation check.
    rebalance(pf, ctx, trailing, cfg, now_ts)

    # 3. Liquidation check: with rebalancing in place, this should be unreachable
    #    under normal conditions; left in as a final safety net.
    for sym, pos in list(pf.positions.items()):
        c = ctx.get(sym)
        if not c or c["mark"] is None:
            continue
        mark = c["mark"]
        if pos.is_liquidated(mark, cfg.maint_margin_frac):
            pf.log.append(f"LIQUIDATION {sym} @ ${mark:.2f} margin_ratio={pos.margin_ratio(mark):.3f}")
            if cfg.kill_on_liquidation:
                pf.killed = True
            close_position(pf, sym, mark, cfg, "liquidated",
                           exit_perp=c.get("perp_ask"), exit_spot=c.get("spot_bid"))

    # A liquidation during step 3 trips the kill-switch — halt all new entries this tick.
    if pf.killed:
        pf.last_tick_ts = now_ts
        return

    # 4. Apply the funding gate: open when rich, close when thin; resize to track target.
    marks = {s: c["mark"] for s, c in ctx.items() if c.get("mark")}
    for sym in cfg.symbols:
        c = ctx.get(sym)
        if not c or c["mark"] is None:
            continue
        mark = c["mark"]
        tgt = target_notional(trailing.get(sym), cfg)
        held = sym in pf.positions

        if held and trailing.get(sym) is not None and trailing[sym] < cfg.exit_funding_ann:
            close_position(pf, sym, mark, cfg, "funding below exit",
                           exit_perp=c.get("perp_ask"), exit_spot=c.get("spot_bid"))

        elif not held and tgt > 0:
            # Estimate total cash committed per dollar of notional: spot + margin(1/lev) + reserve + open fees.
            committed_estimate = (
                tgt * (1 + 1 / cfg.target_leverage + cfg.reserve_frac)
                + tgt * cfg.taker_fee_frac * (cfg.legs_per_round_trip / 2)
            )
            if (pf.total_notional(marks) + tgt <= cfg.max_total_notional_usd
                    and pf.cash_usd >= committed_estimate):
                open_position(pf, sym, mark, tgt, cfg,
                              fill_perp=c.get("perp_bid"), fill_spot=c.get("spot_ask"))

        elif held and tgt > 0 and cfg.resize_tolerance < 1.0:
            # Symmetric resize: adjust existing position toward gate target.
            pos = pf.positions.get(sym)
            if pos is not None:
                current_notional = pos.coin_qty * mark
                max_n = max(tgt, current_notional)
                if max_n > 0 and abs(tgt - current_notional) / max_n > cfg.resize_tolerance:
                    resize_position(
                        pf, sym, tgt, mark, cfg, marks,
                        fill_perp_bid=c.get("perp_bid", mark),
                        fill_spot_ask=c.get("spot_ask", mark),
                        fill_perp_ask=c.get("perp_ask", mark),
                        fill_spot_bid=c.get("spot_bid", mark),
                    )

    pf.last_tick_ts = now_ts
