# DeepOdds — Late-Stage Settlement Arbitrage Bot

Automated trading bot for Kalshi crypto prediction markets. Uses a **settlement arbitrage** strategy — buying near-certain contracts close to expiry when market makers still price tail risk that can't materialize in the remaining time.

## How It Works

### Strategy: Late-Stage Settlement Arbitrage

Instead of predicting price direction, the bot exploits **temporal decay of the volatility risk premium**:

1. **Scanner** (every 30s) — Fetches all active crypto contracts (BTC, ETH, SOL, XRP, DOGE, GOLD, SILVER) from Kalshi. For each contract, fetches 1-hour realized volatility from Binance klines.

2. **Sigma Distance** — For each near-expiry contract, computes how many standard deviations of price movement separate the current spot price from the nearest strike boundary:
   ```
   sigma = distance_from_boundary / (realized_vol × √(minutes_left / 525600))
   ```
   - **Sigma distance** (σ): *A measure of how statistically unlikely it is for the price to cross the strike boundary before expiry. 1σ = 84% chance of winning, 2σ = 98%, 3σ = 99.9%.*

3. **Entry Decision** — If sigma ≥ 2.0 (configurable) AND the near-certain side trades below fair probability value by ≥ 5¢ (configurable), the bot buys. No probability model, no directional prediction — pure mechanical edge.

4. **Fee-Aware EV** — Every trade accounts for Kalshi's 7% profit fee (min 2¢/contract). The bot only enters when expected value is positive after fees.

5. **Settlement** — Positions typically resolve within 15-60 minutes. Settlement uses Kalshi's published market result (authoritative), never spot price guesswork.

### Signal Lifecycle

```
signaled → placed (live) / filled (paper) → settled_win / settled_loss
```

### Risk Controls

| Control | Description |
|---------|-------------|
| Max Exposure | Caps total capital in open positions |
| Daily Budget | Hard ceiling on new position spend per day |
| Daily Loss Limit | Pauses the bot if realized losses exceed threshold |
| Max Positions/Asset | Limits concurrent positions per underlying |
| Max Signals/Hour | Rate limits new signals |
| Per-Ticker Cooldown | 2-hour pause after a loss on the same contract |
| Kelly-Inspired Sizing | Position size proportional to edge (5-25% of max) |
| Portfolio Risk Gating | Caps correlated exposure on a single underlying |
| Regime Filter | Pauses during extreme fear (Fear & Greed < threshold) |

## Architecture

```
┌─────────────┐    ┌───────────┐    ┌──────────┐
│  React SPA  │───▶│  FastAPI   │───▶│ Postgres │
│  (Vite)     │    │  (async)   │    │   16     │
└─────────────┘    └─────┬─────┘    └──────────┘
                         │
                         │ Native asyncio scheduler
                         │ (scan 30s, settle 5m, sync 1m)
                         │
            ┌────────────▼───────────┐
            ▼                        ▼
        Kalshi API               Binance
        (contracts)          (spot prices + vol)
```

- **Backend**: FastAPI + async SQLAlchemy + Alembic
- **Scheduler**: Native asyncio loops (no Celery, no Redis)
- **Frontend**: React 19 + TypeScript + Vite + Tailwind CSS v4 + Zustand
- **Auth**: JWT (HS256), per-user Kalshi RSA keys stored server-side

## Prerequisites

- Python 3.13+ / uv
- Node.js 20+
- Docker & Docker Compose (PostgreSQL 16)

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Set: DATABASE_URL, DATABASE_URL_SYNC, JWT_SECRET_KEY, KALSHI_ENV=prod

# 2. Start infrastructure
docker compose up -d

# 3. Install & migrate
cd backend && uv sync && PYTHONPATH=. uv run alembic upgrade head && cd ..
cd frontend && npm install && cd ..

# 4. Run (scheduler runs inside the backend process)
cd backend && PYTHONPATH=. uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
cd frontend && npx vite --host 0.0.0.0 --port 5173 &
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Register |
| POST | `/api/v1/auth/login` | Login → JWT |
| GET | `/api/v1/auth/me` | Current user |
| GET | `/api/v1/dashboard` | Full dashboard: bot status, signals, opportunities, stats |
| GET | `/api/v1/dashboard/pnl-chart` | 30-day P&L chart data |
| GET | `/api/v1/signals` | Paginated signals (filter by status) |
| POST | `/api/v1/signals/archive` | Archive signals |
| GET | `/api/v1/signals/archive` | Browse archived signals |
| GET | `/api/v1/settings/bot-config` | Get bot config |
| PUT | `/api/v1/settings/bot-config` | Update bot config |
| PUT | `/api/v1/settings/kalshi-keys` | Save Kalshi API keys |
| GET | `/api/v1/settings/kalshi-keys` | Key status |
| DELETE | `/api/v1/settings/kalshi-keys` | Remove keys |
| GET | `/api/v1/settings/kalshi-balance` | Kalshi account balance |

## Bot Config Defaults

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | paper | paper or live |
| `strategy` | settlement_arb | settlement_arb, naive_no, or model (legacy) |
| `enabled` | false | Bot active |
| `settlement_arb_enabled` | true | Settlement arb active |
| `settlement_arb_max_minutes` | 60 | Max minutes to expiry |
| `settlement_arb_min_sigma` | 2.0 | Minimum sigma distance |
| `settlement_arb_min_discount_cents` | 5 | Minimum discount from fair value |
| `settlement_arb_max_position_cents` | 5000 | Max position size per signal |
| `settlement_arb_regime_filter` | false | Pause during extreme fear |
| `settlement_arb_min_fear_greed` | 25 | Fear & Greed threshold |
| `max_exposure_cents` | 5000 | Max capital in open positions |
| `daily_budget_cents` | 0 | Daily spend cap (0 = disabled) |
| `daily_loss_limit_cents` | 2000 | Daily loss circuit breaker |
| `max_portfolio_risk_cents` | 0 | Correlated risk cap (0 = disabled) |
| `max_positions_per_asset` | 3 | Max concurrent positions per underlying |
| `max_signals_per_hour` | 20 | Rate limit on new signals |

## Scheduler

The scheduler runs inside the FastAPI process as 3 asyncio background loops:

| Loop | Interval | What it does |
|------|----------|--------------|
| Scan | 30s | Fetch Kalshi opportunities, evaluate all users, process paper fills |
| Settle | 5m | Settle expired signals using Kalshi's published results, prune stale opportunities |
| Sync Live | 1m | Check live order statuses on Kalshi |

## Project Structure

```
deepodds/
├── .pi/skills/               # Agent skills
├── docker-compose.yml        # PostgreSQL 16
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI entrypoint + scheduler startup
│   │   ├── core/             # Config, database, auth, async_util, scheduler
│   │   ├── models/           # User, BotConfig, Signal, Opportunity
│   │   ├── schemas/          # Pydantic models
│   │   ├── api/v1/           # REST endpoints
│   │   └── services/
│   │       ├── market_scanner.py    # Kalshi event scanner + prune
│   │       ├── signal_engine.py     # Settlement arb + naive + BSM strategies
│   │       ├── probability_model.py # BSM N(d2) (legacy)
│   │       ├── binance_client.py    # Spot prices + realized volatility
│   │       ├── kalshi_client.py     # RSA-PSS signed API client
│   │       └── archive.py           # Signal archival
│   └── alembic/               # Database migrations
└── frontend/
    └── src/
        ├── api/               # API client + types
        ├── stores/            # Zustand state management
        ├── pages/             # Dashboard, Settings, Login, Register, Resources
        └── components/        # BotStatusBar, StatsCard, SignalTable, PnLChart, etc.
```
