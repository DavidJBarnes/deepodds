"""Position + portfolio state for the funding-carry paper harness.

Invariant (delta-neutral coin-unit hedge): portfolio P&L = accrued_funding
+ entry_basis - fees, INDEPENDENT of mark price. Liquidation of the short is
the only thing that breaks neutrality.
"""
from dataclasses import dataclass, field


@dataclass
class CarryPosition:
    symbol: str
    coin_qty: float          # X: long X spot, short X perp
    entry_perp: float        # perp price at short entry
    entry_spot: float        # spot price at long entry
    hl_margin: float         # USDC margin currently in the HL short account
    reserve: float           # USDC buffer held to top up margin
    accrued_funding: float = 0.0
    fees_paid: float = 0.0
    opened_ts: float = 0.0

    def notional(self, mark: float) -> float:
        return self.coin_qty * mark

    def perp_unrealized(self, mark: float) -> float:
        # Short: gains when price falls.
        return self.coin_qty * (self.entry_perp - mark)

    def hl_equity(self, mark: float) -> float:
        return self.hl_margin + self.accrued_funding + self.perp_unrealized(mark)

    def maint_margin(self, mark: float, maint_frac: float) -> float:
        return self.notional(mark) * maint_frac

    def margin_ratio(self, mark: float) -> float:
        n = self.notional(mark)
        return self.hl_equity(mark) / n if n > 0 else 0.0

    def is_liquidated(self, mark: float, maint_frac: float) -> bool:
        # Liquidated only if equity falls below maintenance AND the reserve
        # buffer is exhausted (engine tops up from reserve before this).
        return (self.hl_equity(mark) + self.reserve) <= self.maint_margin(mark, maint_frac)

    def realized_pnl(self) -> float:
        # On close, price legs net out; what's left is funding + entry basis - fees.
        basis = self.coin_qty * (self.entry_perp - self.entry_spot)
        return self.accrued_funding + basis - self.fees_paid

    def capital_committed(self) -> float:
        return self.coin_qty * self.entry_spot + self.hl_margin + self.reserve


@dataclass
class PaperPortfolio:
    cash_usd: float
    positions: dict[str, CarryPosition] = field(default_factory=dict)
    realized_pnl: float = 0.0
    accrued_funding_total: float = 0.0
    fees_total: float = 0.0
    killed: bool = False
    last_tick_ts: float = 0.0
    log: list[str] = field(default_factory=list)

    def total_notional(self, marks: dict[str, float]) -> float:
        return sum(p.notional(marks.get(s, p.entry_perp)) for s, p in self.positions.items())

    # Rebalancing counters (incremented by engine.rebalance())
    rebalance_topup_count: int = 0
    rebalance_recenter_count: int = 0
    rebalance_fees_usd: float = 0.0

    def equity(self, marks: dict[str, float]) -> float:
        """Cash + committed capital + unrealized (== cash + committed + accrued funding)."""
        held = sum(
            p.coin_qty * marks.get(s, p.entry_spot) + p.hl_equity(marks.get(s, p.entry_perp)) + p.reserve
            for s, p in self.positions.items()
        )
        return self.cash_usd + held
