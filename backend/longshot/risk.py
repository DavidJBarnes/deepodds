"""Risk gate for live longshot trading. Fail-closed: every order must pass
`RiskGate.check()` first, and any breach of the daily-loss limit trips the kill
switch (which halts all new orders until manually cleared).

Pure-ish: the only side effect is writing/reading the kill sentinel file, so the
allow/deny logic is unit-testable without a broker or network.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from longshot.config import LongshotConfig

logger = logging.getLogger("longshot.risk")


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def is_killed(cfg: LongshotConfig) -> bool:
    """Kill switch is on if the sentinel file exists OR LONGSHOT_KILL is truthy."""
    return _env_truthy("LONGSHOT_KILL") or os.path.exists(cfg.kill_file)


def trip_kill(cfg: LongshotConfig, reason: str) -> None:
    """Write the kill sentinel. Idempotent. Halts new orders until removed."""
    try:
        os.makedirs(os.path.dirname(cfg.kill_file) or ".", exist_ok=True)
        with open(cfg.kill_file, "w") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {reason}\n")
        logger.error("KILL SWITCH TRIPPED: %s", reason)
    except Exception:
        logger.exception("failed to write kill file %s", cfg.kill_file)


@dataclass
class Decision:
    allow: bool
    reason: str = ""


@dataclass
class PortfolioRisk:
    """Snapshot of current live exposure, passed in by the caller (built from
    Kalshi truth in live mode)."""
    deployed_collateral: float
    open_positions: int
    realized_pnl_today: float
    available_balance: float | None = None   # real Kalshi cash; None in paper
    # Collateral locked by orders filled EARLIER IN THIS TICK. `available_balance` is
    # read once at the start of the tick and is not re-read per order, so it does not
    # yet reflect these fills — this is the running correction. Reset to 0 each tick.
    deployed_this_tick: float = 0.0
    # Account value (free cash + open collateral), captured ONCE at the start of the
    # tick. Placing an order moves cash into collateral 1:1 and leaves equity unchanged,
    # so it is never updated mid-tick (the #224 class). None when Kalshi is unreachable.
    equity: float | None = None


class RiskGate:
    def __init__(self, cfg: LongshotConfig):
        self.cfg = cfg

    def deployed_cap(self, pr: PortfolioRisk) -> float:
        """Effective total-exposure cap. A fixed dollar cap goes stale the moment the
        account grows — by deposit or by P&L — and then silently gates new capital
        (2026-09-12: $450 bound on 73/168 ticks at $624 equity). With a fraction set it
        tracks equity; the absolute stays as the ceiling and the no-equity fallback."""
        cap = self.cfg.max_deployed_collateral
        if self.cfg.max_deployed_frac > 0 and pr.equity is not None:
            cap = min(cap, self.cfg.max_deployed_frac * pr.equity)
        return cap

    def daily_loss_cap(self, pr: PortfolioRisk) -> float:
        """Effective circuit-breaker threshold (a positive number of dollars).

        Realized losses come out of the balance, so live equity falls through a bad
        day; a fraction of live equity would move the line toward you as you lose.
        Adding today's realized P&L back gives start-of-day equity, which holds still."""
        cap = abs(self.cfg.max_daily_loss)
        if self.cfg.max_daily_loss_frac > 0 and pr.equity is not None:
            start_of_day = pr.equity - pr.realized_pnl_today
            cap = min(cap, self.cfg.max_daily_loss_frac * start_of_day)
        return cap

    def pretick(self, pr: PortfolioRisk) -> Decision:
        """Run once per tick before discovering/placing anything. A daily-loss
        breach trips the kill switch so it persists across ticks."""
        if is_killed(self.cfg):
            return Decision(False, "kill switch engaged")
        loss_cap = self.daily_loss_cap(pr)
        if pr.realized_pnl_today <= -loss_cap:
            trip_kill(self.cfg, f"daily loss {pr.realized_pnl_today:.2f} <= -{loss_cap:.2f}")
            return Decision(False, "daily loss limit hit — kill tripped")
        return Decision(True)

    def check_order(self, pr: PortfolioRisk, *, contracts: int, collateral: float) -> Decision:
        """Per-order gate. `pr` reflects exposure INCLUDING orders already placed
        this tick (caller updates it incrementally).

        The per-trade test REJECTS; it does not trim. Live trims oversized clips to the
        cap before calling this (live_run.trim_to_cap), so here it is only a backstop."""
        if is_killed(self.cfg):
            return Decision(False, "kill switch engaged")
        if contracts < 1:
            return Decision(False, "zero contracts")
        if contracts > self.cfg.max_per_trade_contracts:
            return Decision(False, f"per-trade {contracts} > cap {self.cfg.max_per_trade_contracts}")
        if pr.open_positions >= self.cfg.max_open_positions:
            return Decision(False, f"open {pr.open_positions} >= cap {self.cfg.max_open_positions}")
        cap = self.deployed_cap(pr)
        if pr.deployed_collateral + collateral > cap:
            return Decision(False,
                            f"deployed {pr.deployed_collateral + collateral:.2f} > cap {cap:.2f}")
        # Never try to deploy more collateral than the real account actually holds.
        #
        # `available_balance` is Kalshi's FREE CASH — selling a short moves cash into
        # collateral 1:1, so the balance already excludes every open position's
        # collateral (this is exactly why live_snapshot reconstructs equity as
        # balance + deployed_collateral). Testing `deployed_collateral + collateral`
        # against it therefore charged the whole open book to free cash a second time,
        # and the gate tightened as the book grew: it deferred 45% of all live entries
        # (79% by 2026-08) to a later tick, ~10h late on average. Those deferrals cost
        # 1.16c/contract of decayed premium for ZERO risk reduction (YES rate identical
        # at 2.50% early vs late, n=480 paired) — about $35 of forgone premium against
        # $26.61 of realized P&L. Same double-count class as #224, one layer down.
        #
        # The affordability question is only ever about THIS order plus what this tick
        # has already spent. Total exposure stays capped by the deployed cap above.
        if pr.available_balance is not None and \
                pr.deployed_this_tick + collateral > pr.available_balance:
            return Decision(False,
                            f"this-tick {pr.deployed_this_tick + collateral:.2f} > free balance "
                            f"{pr.available_balance:.2f}")
        return Decision(True)
