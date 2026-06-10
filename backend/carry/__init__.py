"""Crypto perpetual funding-rate carry strategy (paper harness).

Delta-neutral carry: long spot (Coinbase/Kraken) + short perp (Hyperliquid),
sized in coin units so the hedge self-neutralizes (total value = const +
cumulative funding). Harvests the funding shorts receive when funding > 0.

Validated 2026-06-10 (see memory/project-funding-carry): edge survives costs
(~0.2% one-time vs double-digit annual carry in rich regimes), liquidation-safe
at <=2x over the real BTC/ETH price path, but regime-dependent (thin now,
~3-5%/yr; 3yr avg ~15-22%/yr). Hence funding-GATED sizing: stay flat when
funding is thin, scale in when it richens.
"""
