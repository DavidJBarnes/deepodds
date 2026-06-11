"""
Derive a CarryConfig scaled to a specific capital amount.

The default CarryConfig assumes $100k capital with $20k max notional per symbol.
This module derives per-symbol and total notional caps proportionally so the
strategy deploys roughly the same fraction of capital at any size.

Usage:
    from backtest.scaling import scaled_config
    cfg = scaled_config(8_000)
"""
from carry.config import CarryConfig

# Each $1 of notional commits approximately:
#   $1   spot leg (on-exchange)
#   $0.50  HL margin at 2x leverage (1 / target_leverage)
#   $0.15  reserve buffer (reserve_frac)
#   ~$0.001  fees (tiny, typically < $2 per $1k notional)
# Total committed ≈ $1.65 per $1 notional at 2x / 15% reserve.
#
# To keep committed capital ≈ 91% of wallet at full two-symbol deployment:
#   total_notional_ratio × 1.65 ≈ 0.91  →  total_notional_ratio ≈ 0.55
# Per-symbol cap at 30% leaves room for both symbols without exceeding the total.
PER_SYMBOL_NOTIONAL_RATIO = 0.30
TOTAL_NOTIONAL_RATIO = 0.55


def scaled_config(capital_usd: float, **overrides) -> CarryConfig:
    """
    Return a CarryConfig scaled to `capital_usd`, with any keyword overrides applied.

    Derived values (everything else inherits CarryConfig defaults):
      paper_capital_usd         = capital_usd
      max_notional_per_symbol   = capital_usd × PER_SYMBOL_NOTIONAL_RATIO (0.30)
      max_total_notional_usd    = capital_usd × TOTAL_NOTIONAL_RATIO (0.55)

    At full two-symbol deployment, committed capital ≈ 91% of wallet at 2x / 15% reserve.

    Example:
        cfg = scaled_config(8_000)
        # paper_capital_usd=8000, max_notional_per_symbol=2400, max_total_notional_usd=4400
    """
    params = dict(
        paper_capital_usd=capital_usd,
        max_notional_per_symbol=round(capital_usd * PER_SYMBOL_NOTIONAL_RATIO, 2),
        max_total_notional_usd=round(capital_usd * TOTAL_NOTIONAL_RATIO, 2),
    )
    params.update(overrides)
    return CarryConfig(**params)
