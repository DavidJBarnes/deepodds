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


def open_position(pf: PaperPortfolio, symbol: str, mark: float, notional: float, cfg: CarryConfig) -> CarryPosition:
    qty = notional / mark
    margin = notional / cfg.target_leverage
    reserve = notional * cfg.reserve_frac
    fees = notional * cfg.taker_fee_frac * (cfg.legs_per_round_trip / 2)  # open = 2 legs
    committed = qty * mark + margin + reserve + fees
    pos = CarryPosition(
        symbol=symbol, coin_qty=qty, entry_perp=mark, entry_spot=mark,
        hl_margin=margin, reserve=reserve, fees_paid=fees, opened_ts=pf.last_tick_ts,
    )
    pf.cash_usd -= committed
    pf.fees_total += fees
    pf.positions[symbol] = pos
    pf.log.append(f"OPEN {symbol} notional=${notional:.0f} qty={qty:.5f} @ ${mark:.2f} (lev {cfg.target_leverage}x)")
    return pos


def close_position(pf: PaperPortfolio, symbol: str, mark: float, cfg: CarryConfig, reason: str) -> None:
    pos = pf.positions.pop(symbol)
    close_fees = pos.notional(mark) * cfg.taker_fee_frac * (cfg.legs_per_round_trip / 2)
    pos.fees_paid += close_fees
    # Return committed capital (spot proceeds + HL equity + reserve), realize pnl.
    returned = pos.coin_qty * mark + pos.hl_equity(mark) + pos.reserve - close_fees
    pf.cash_usd += returned
    pf.realized_pnl += pos.realized_pnl()
    pf.fees_total += close_fees
    pf.log.append(f"CLOSE {symbol} ({reason}) pnl=${pos.realized_pnl():.2f} funding=${pos.accrued_funding:.2f}")


def tick(pf: PaperPortfolio, ctx: dict[str, dict], trailing: dict[str, float | None],
         cfg: CarryConfig, now_ts: float) -> None:
    """One engine tick on live data. ctx[sym]={funding,mark}; trailing[sym]=ann funding."""
    if pf.killed:
        return
    hours = (now_ts - pf.last_tick_ts) / 3600 if pf.last_tick_ts else 0.0
    hours = max(0.0, min(hours, 24.0))  # clamp (cold start / long gaps)

    # 1. Accrue + manage existing positions; check liquidation.
    for sym, pos in list(pf.positions.items()):
        c = ctx.get(sym)
        if not c or c["mark"] is None:
            continue
        mark = c["mark"]
        cf = accrue_funding(pos, c["funding"], mark, hours)
        pf.accrued_funding_total += cf
        manage_margin(pos, mark, cfg)
        if pos.is_liquidated(mark, cfg.maint_margin_frac):
            pf.log.append(f"LIQUIDATION {sym} @ ${mark:.2f} margin_ratio={pos.margin_ratio(mark):.3f}")
            if cfg.kill_on_liquidation:
                pf.killed = True
            close_position(pf, sym, mark, cfg, "liquidated")

    # A liquidation during step 1 trips the kill-switch — halt all new entries.
    if pf.killed:
        pf.last_tick_ts = now_ts
        return

    # 2. Apply the funding gate: open when rich, close when thin.
    marks = {s: c["mark"] for s, c in ctx.items() if c.get("mark")}
    for sym in cfg.symbols:
        c = ctx.get(sym)
        if not c or c["mark"] is None:
            continue
        mark = c["mark"]
        tgt = target_notional(trailing.get(sym), cfg)
        held = sym in pf.positions
        if held and trailing.get(sym) is not None and trailing[sym] < cfg.exit_funding_ann:
            close_position(pf, sym, mark, cfg, "funding below exit")
        elif not held and tgt > 0:
            # portfolio-wide exposure cap
            if pf.total_notional(marks) + tgt <= cfg.max_total_notional_usd and pf.cash_usd > tgt:
                open_position(pf, sym, mark, tgt, cfg)

    pf.last_tick_ts = now_ts
