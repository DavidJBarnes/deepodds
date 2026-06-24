"""Order execution for live longshot trading.

Replicates the paper harness's fill assumption — *take* the current best YES bid —
with a real **marketable limit SELL YES** order, but records what ACTUALLY happened
(fill count, price, fee), not what we hoped. This is the module that turns the
backtest into a P&L statement, and the place where the paper->live gap lives.

Safety invariants:
  - Deterministic `client_order_id` per (ticker, tick) => a retried/replayed tick
    never double-submits.
  - Order POST is never auto-retried. On an ambiguous failure (timeout) we CONFIRM
    by looking the order up by client_order_id before deciding anything.
  - Partial fills are normal; we cancel the unfilled remainder and book only what
    filled.
  - dry_run places nothing — it logs the exact order it WOULD send (Phase 1).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict

import httpx

from longshot.kalshi_client import KalshiClient, kalshi_fee_per_contract

logger = logging.getLogger("longshot.execution")

_FILL_POLL_ATTEMPTS = 4
_FILL_POLL_DELAY = 0.5


@dataclass
class FillResult:
    client_order_id: str
    ticker: str
    status: str                 # filled | partial | unfilled | dryrun | error
    intended_count: int
    intended_price: float       # dollars (the bid we aimed to hit)
    filled_count: int = 0
    avg_price: float = 0.0      # dollars, actual VWAP
    fee: float = 0.0            # dollars, actual (or formula fallback)
    order_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class Executor:
    def __init__(self, client: KalshiClient, order_prefix: str, dry_run: bool = False):
        self.client = client
        self.prefix = order_prefix
        self.dry_run = dry_run

    def client_order_id(self, ticker: str, tick_epoch: int) -> str:
        """Idempotency key: same (ticker, tick) -> same id -> no double-submit."""
        return f"{self.prefix}-{ticker}-{tick_epoch}"

    def place_short(self, *, ticker: str, sell_price: float, count: int,
                    tick_epoch: int) -> FillResult:
        """Sell `count` YES contracts at the current bid (`sell_price`, dollars)
        as a marketable IOC ask: take what's resting now, auto-cancel the rest."""
        coid = self.client_order_id(ticker, tick_epoch)
        base = FillResult(client_order_id=coid, ticker=ticker, status="error",
                          intended_count=count, intended_price=sell_price)

        if self.dry_run:
            logger.info("DRY-RUN would SELL %-34s %d @ %.0fc (coid=%s)",
                        ticker, count, sell_price * 100, coid)
            base.status = "dryrun"
            return base

        # --- place (never auto-retried) ------------------------------------
        try:
            resp = self.client.create_order(
                ticker=ticker, side="ask", count=count, price=sell_price,
                client_order_id=coid, time_in_force="immediate_or_cancel")
            order = resp.get("order", resp)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            # Ambiguous: the order MAY have landed. Confirm before doing anything.
            logger.warning("create_order ambiguous (%s); confirming by client_order_id", e)
            order = self.client.find_order_by_client_id(coid)
            if order is None:
                base.error = f"unconfirmed after timeout: {e}"
                return base
        except httpx.HTTPStatusError as e:
            base.error = f"rejected: {e.response.status_code} {e.response.text[:200]}"
            logger.warning("order rejected %s: %s", ticker, base.error)
            return base

        order_id = order.get("order_id") or order.get("id")
        base.order_id = order_id

        # V2 returns the fill inline (IOC auto-cancels any unfilled remainder).
        # Fee is the REAL per-contract amount (not ceil-to-cent like our formula).
        if order.get("fill_count") is not None:
            filled = int(float(order["fill_count"]))
            avg_px = float(order.get("average_fill_price") or sell_price)
            fee = round(float(order.get("average_fee_paid") or 0) * filled, 4)
        else:
            # timeout-confirmed orders may lack inline fill — poll fills.
            filled, avg_px, fee = self._settle_order(order_id, ticker)
        base.filled_count = filled
        base.avg_price = round(avg_px, 4) if filled else 0.0
        base.fee = fee
        base.status = "filled" if filled >= count else ("partial" if filled > 0 else "unfilled")
        logger.info("LIVE SELL %-34s intended %d @ %.2f -> filled %d @ %.4f fee %.2f [%s]",
                    ticker, count, sell_price, filled, avg_px, fee, base.status)
        return base

    def _settle_order(self, order_id: str | None, ticker: str) -> tuple[int, float, float]:
        """Poll fills for this order; return (count, vwap_dollars, total_fee_dollars).
        Falls back to the fee formula if Kalshi doesn't return a per-fill fee."""
        if not order_id:
            return 0, 0.0, 0.0
        for i in range(_FILL_POLL_ATTEMPTS):
            try:
                fills = self.client.get_fills(order_id=order_id).get("fills", [])
            except Exception:
                fills = []
            if fills:
                count = sum(int(f.get("count", 0)) for f in fills)
                if count <= 0:
                    break
                # yes_price in cents; weight by count
                num = sum(int(f.get("count", 0)) * int(f.get("yes_price", 0)) for f in fills)
                vwap = (num / count) / 100.0
                fee = sum(float(f["fee"]) for f in fills if f.get("fee") is not None) / 100.0 \
                    if any(f.get("fee") is not None for f in fills) \
                    else kalshi_fee_per_contract(vwap, count)
                return count, round(vwap, 4), round(fee, 4)
            time.sleep(_FILL_POLL_DELAY)
        return 0, 0.0, 0.0
