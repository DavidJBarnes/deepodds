---
name: performance-auditor
description: Systematic trading system auditor for finding bugs and performance issues.
---

# Performance Auditor

Use this skill when reviewing trading code or when trading performance is poor, to systematically audit the system for bugs, bottlenecks, and risk management flaws.

## Audit Checklist

- Identify bugs, latency bottlenecks, unrealistic cost assumptions, slippage errors, and risk management flaws in spot and futures code
- Provide prioritized tweaks (low/medium/high effort) with expected impact on Sharpe ratio and drawdown
- Explain diagnostics including: transaction cost drag, basis convergence, funding rate erosion, signal decay
- Requires Python 3.10+, access to trading logs or backtest outputs

## Approach

1. Start by understanding the full trade lifecycle — from signal generation to execution
2. Profile for latency and compute bottlenecks
3. Audit cost models for realism (slippage, fees, funding)
4. Stress-test risk management logic
5. Prioritize findings by expected impact on risk-adjusted returns
