"""Edge Explorer — a daily curiosity engine with a memory.

Reads the data DeepOdds already banks (the Deribit-oracle settlement record, the
longshot harness history, the Deribit option chain) and each day surfaces a short,
ranked list of *observations worth investigating* — NOT trade signals. The value is
insight delivered, not mined: every observation carries what / why-notable / next-step
/ caveat, and lands in a durable ledger tracked to a verdict.

Design contract (see plan foamy-stirring-llama.md):
  - Observations, not signals. The failure mode is wasted attention, not lost capital.
  - Flag against each metric's OWN trailing baseline (robust z), never an absolute line,
    plus a few hand-authored structural/threshold rules for known-meaningful metrics.
  - Persistence = a free out-of-sample test: rank by surprise x persistence (streak),
    so one-off noise sinks and repeat surprises float.
  - Honest about data limits: book-depth microstructure is deferred (the Kalshi depth
    endpoint is dead); a data-quality rule surfaces that rather than faking it.
"""
