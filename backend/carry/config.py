"""Funding-carry strategy config. Defaults reflect the 2026-06-10 validation:
conservative 2x leverage (liquidation-safe over the real path), funding-gated
sizing (flat when thin, scale in when rich), BTC/ETH only."""
from dataclasses import dataclass, field


@dataclass
class CarryConfig:
    # Universe — the two assets with reliable multi-year funding history.
    symbols: list[str] = field(default_factory=lambda: ["BTC", "ETH"])

    # Capital (paper).
    paper_capital_usd: float = 100_000.0
    max_notional_per_symbol: float = 20_000.0   # cap carry notional per coin

    # Leverage / margin (HL short leg). 2x validated liquidation-safe.
    target_leverage: float = 2.0
    maint_margin_frac: float = 0.012             # conservative HL maintenance
    reserve_frac: float = 0.15                   # extra USDC buffer beyond initial margin
    topup_trigger_ratio: float = 0.20            # top up when margin_ratio < this (target 1/lev=0.5)

    # Funding gate (annualized, decimal). Below hurdle -> flat; scale to full at `rich`.
    # Hurdle clears T-bill + a risk premium for counterparty/liquidation tail.
    min_funding_hurdle_ann: float = 0.06
    rich_funding_ann: float = 0.20
    trailing_window_hours: int = 24 * 7          # 7d trailing funding drives the gate
    exit_funding_ann: float = 0.0                # exit if trailing funding falls below this

    # Costs (for paper P&L realism).
    taker_fee_frac: float = 0.0004               # per fill, per leg
    legs_per_round_trip: int = 4                 # open+close spot & perp
    spot_spread_bps: float = 2.0                 # modeled spot half-spread when no live quote

    # Risk / kill-switch.
    max_total_notional_usd: float = 40_000.0     # portfolio-wide HL exposure cap
    kill_on_liquidation: bool = True
