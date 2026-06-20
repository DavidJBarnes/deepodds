"""
On-chain crypto intelligence strategy for DeepOdds.

Signal: BTC exchange net-flow z-score.
  - When coins flow OUT of exchanges (net_flow_z < -1): holders accumulating → long.
  - When coins flow IN to exchanges (net_flow_z > +1): holders distributing → flat.

Phase 0-1 (backtest) live in onchain/backtest/.
Phase 2 (live paper harness) is built only after the backtest passes all gate criteria.
See the plan for exact gate thresholds.

Data source: Glassnode (exchange flows) + CoinGecko (prices).
"""
