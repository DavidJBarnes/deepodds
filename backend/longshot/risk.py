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


class RiskGate:
    def __init__(self, cfg: LongshotConfig):
        self.cfg = cfg

    def pretick(self, pr: PortfolioRisk) -> Decision:
        """Run once per tick before discovering/placing anything. A daily-loss
        breach trips the kill switch so it persists across ticks."""
        if is_killed(self.cfg):
            return Decision(False, "kill switch engaged")
        if pr.realized_pnl_today <= -abs(self.cfg.max_daily_loss):
            trip_kill(self.cfg, f"daily loss {pr.realized_pnl_today:.2f} <= -{self.cfg.max_daily_loss:.2f}")
            return Decision(False, "daily loss limit hit — kill tripped")
        return Decision(True)

    def check_order(self, pr: PortfolioRisk, *, contracts: int, collateral: float) -> Decision:
        """Per-order gate. `pr` reflects exposure INCLUDING orders already placed
        this tick (caller updates it incrementally)."""
        if is_killed(self.cfg):
            return Decision(False, "kill switch engaged")
        if contracts < 1:
            return Decision(False, "zero contracts")
        if contracts > self.cfg.max_per_trade_contracts:
            return Decision(False, f"per-trade {contracts} > cap {self.cfg.max_per_trade_contracts}")
        if pr.open_positions >= self.cfg.max_open_positions:
            return Decision(False, f"open {pr.open_positions} >= cap {self.cfg.max_open_positions}")
        if pr.deployed_collateral + collateral > self.cfg.max_deployed_collateral:
            return Decision(False,
                            f"deployed {pr.deployed_collateral + collateral:.2f} > cap "
                            f"{self.cfg.max_deployed_collateral:.2f}")
        return Decision(True)
