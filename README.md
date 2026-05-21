# DeepOdds — Late-Stage Settlement Arbitrage Bot

Automated trading bot for Kalshi crypto prediction markets. Uses a **settlement arbitrage** strategy — buying near-certain contracts close to expiry when market makers still price tail risk that can't materialize in the remaining time.

## How It Works

### Strategy: Late-Stage Settlement Arbitrage

Instead of predicting price direction, the bot exploits **temporal decay of the volatility risk premium**:

1. **Scanner** (every 60s) — Fetches all active crypto contracts (BTC, ETH range/price) from Kalshi. For each contract, fetches 1-hour realized volatility from Binance klines.

2. **Sigma Distance** — For each near-expiry contract, computes how many standard deviations of price movement separate the current spot price from the nearest strike boundary:
   ```
   sigma = distance_from_boundary / (realized_vol × √(minutes_left / 525600))
   ```
   - **Sigma distance** (σ): *A measure of how statistically unlikely it is for the price to cross the strike boundary before expiry. 1σ = 84% chance of winning, 2σ = 98%, 3σ = 99.9%. Think of it as "how many standard deviations away from danger."*

3. **Entry Decision** — If sigma ≥ 1.5 (configurable) AND the near-certain side trades below fair probability value by ≥ 5¢ (configurable), the bot buys. No probability model, no directional prediction — pure mechanical edge.

4. **Fee-Aware EV** — Every trade accounts for Kalshi's 7% profit fee (min 2¢/contract). The bot only enters when expected value is positive after fees.

5. **Settlement** — Positions typically resolve within 15-60 minutes. At expiry, the outcome is determined by spot vs strike. The bot tracks win rate, P&L, and ROI.

### Why This Works (and the old BSM model didn't)

The previous approach used Black-Scholes with Deribit implied volatility to compute "fair" probabilities. But implied volatility systematically exceeds realized volatility — option sellers demand a premium for bearing tail risk (the **Volatility Risk Premium**, or VRP). This inflated the model's fair values, creating phantom edges.

The settlement arb strategy inverts this: we don't predict anything. We exploit the fact that market makers price tail risk into every contract, but when there's no time left for the tail to materialize, that premium is pure extractable value.

### Signal Lifecycle

```
signaled → placed (live) / filled (paper) → settled_win / settled_loss
```

- **Paper mode**: Signals start as `signaled`. Fill simulation checks if market ask ≤ limit price → `filled`. Settles at expiry based on spot vs strike.
- **Live mode**: Signal engine calls `kalshi.place_order()`, sets status to `placed`. A sync task checks Kalshi for fill status. Settlement checks actual market result.

### Risk Controls

| Control | Description |
|---------|-------------|
| Max Exposure | Caps total capital in open positions at once |
| Daily Budget | Hard ceiling on new position spend per day |
| Daily Loss Limit | Pauses the bot if realized losses exceed threshold |
| Max Positions/Asset | Limits concurrent positions on BTC or ETH contracts |
| Max Signals/Hour | Rate limits new signals to prevent over-trading |
| Per-Ticker Cooldown | 2-hour pause after a loss on the same contract |
| Kelly-Inspired Sizing | Position size proportional to edge (5-25% of max) |

## Architecture

```
┌─────────────┐    ┌───────────┐    ┌──────────┐
│  React SPA  │───▶│  FastAPI   │───▶│ Postgres │
│  (Vite)     │    │  (async)   │    │   16     │
└─────────────┘    └─────┬─────┘    └──────────┘
                         │
                   ┌─────▼─────┐
                   │  Celery   │───▶ Redis 7 ◀── Binance WS
                   │  Worker   │                  (live prices)
                   └─────┬─────┘
                         │
          ┌──────────┬───▼───────┐
          ▼          ▼           ▼
      Kalshi API  Binance     Deribit
      (contracts) (spot/vol)  (IV — legacy)
```

- **Backend**: FastAPI + async SQLAlchemy + Alembic
- **Tasks**: Celery + Redis, Celery Beat for scheduling
- **Frontend**: React 19 + TypeScript + Vite + Tailwind CSS v4 + Zustand
- **Auth**: JWT (HS256), per-user Kalshi RSA keys stored server-side

## Prerequisites

- Python 3.13+ / uv
- Node.js 20+
- Docker & Docker Compose (PostgreSQL 16 + Redis 7)

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Set: DATABASE_URL, DATABASE_URL_SYNC, JWT_SECRET_KEY, KALSHI_ENV=prod

# 2. Start infrastructure
docker compose up -d postgres redis

# 3. Install & migrate
cd backend && uv sync && alembic upgrade head && cd ..
cd frontend && npm install && cd ..

# 4. Run everything
cd backend && PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
cd frontend && npx vite --host 0.0.0.0 --port 5173 &
cd backend && PYTHONPATH=. celery -A app.celery_app worker --beat --loglevel=info
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
| POST | `/api/v1/signals/archive` | Archive signals → archived_signals table |
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
| `strategy` | settlement_arb | Strategy: settlement_arb, naive_no, model (legacy) |
| `enabled` | false | Bot active |
| `settlement_arb_enabled` | false | Settlement arb active |
| `settlement_arb_max_minutes` | 60 | Max minutes to expiry for consideration |
| `settlement_arb_min_sigma` | 1.5 | Minimum sigma distance from boundary |
| `settlement_arb_min_discount_cents` | 5 | Minimum discount from fair value to enter |
| `settlement_arb_max_position_cents` | 5000 | Max position size per signal ($50) |
| `max_exposure_cents` | 5000 | Max total capital in open positions ($50) |
| `daily_budget_cents` | 0 | Daily spend cap (0 = disabled) |
| `daily_loss_limit_cents` | 2000 | Daily loss circuit breaker ($20) |
| `max_positions_per_asset` | 3 | Max concurrent BTC or ETH positions |
| `max_signals_per_hour` | 20 | Rate limit on new signals |

## Task Chains

1. `scan_markets` (every 60s) — Fetch Kalshi opportunities
2. `evaluate_all_users` — Run strategy for each enabled user
3. `process_paper_positions` — Simulate fills + check take-profit

Settlement (`settle_signals`) runs independently every 5 minutes.

## Project Structure

```
deepodds/
├── .pi/skills/               # Agent skills for AI-assisted development
├── docker-compose.yml        # Postgres 16 + Redis 7
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI entrypoint (auto-runs migrations)
│   │   ├── celery_app.py     # Beat schedule
│   │   ├── core/             # Config, database, auth
│   │   ├── models/           # User, BotConfig, Signal, Opportunity, etc.
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── api/v1/           # REST endpoints
│   │   ├── services/
│   │   │   ├── market_scanner.py    # Kalshi event scanner
│   │   │   ├── signal_engine.py     # Settlement arb + naive + BSM strategies
│   │   │   ├── probability_model.py # BSM N(d2) (legacy, kept for V1 comparison)
│   │   │   ├── binance_client.py    # Spot prices + realized volatility
│   │   │   ├── binance_ws.py        # BTC price websocket → Redis
│   │   │   ├── kalshi_client.py     # RSA-PSS signed API client
│   │   │   └── archive.py           # Signal archival
│   │   └── tasks/             # Celery tasks
│   └── alembic/               # Database migrations
└── frontend/
    └── src/
        ├── api/               # API client + types
        ├── stores/            # Zustand state management
        ├── pages/             # Dashboard, Settings, Login, Register, Resources
        └── components/        # BotStatusBar, StatsCard, SignalTable, etc.
```
