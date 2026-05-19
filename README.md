# DeepOdds — Automated Kalshi Crypto Trading Bot

Automated signal detection and execution engine for Kalshi crypto prediction markets. Uses a Black-Scholes probability model with Deribit implied volatility to identify mispriced contracts, then generates paper or live trades.

## How It Works

### Signal Detection Loop

1. **Scanner** (every 60s) — Celery Beat triggers `scan_markets`, which fetches all active crypto contracts from Kalshi's events API for series `KXBTC`, `KXBTCD`, `KXETH`, `KXETHD`. For each contract it pulls the current spot price (Binance), implied volatility (Deribit DVOL surface), and computes a model probability using Black-Scholes N(d2).

2. **Edge Calculation** — For each opportunity the scanner computes:
   - `model_fair_cents` = model probability × 100 (what the contract should be worth)
   - `model_edge_cents` = model_fair_cents − market_yes_price (positive = market is underpriced)

3. **Signal Engine** (runs after each scan) — For every user with an enabled `BotConfig`, evaluates all opportunities:
   - Edge must exceed `min_edge_cents` (default 8¢)
   - Liquidity must exceed `min_liquidity` (default 10)
   - No existing open signal on same ticker
   - Daily spend must not exceed `daily_budget_cents` (default $50)
   - Computes side (yes if edge > 0, no if edge < 0), limit price, quantity (capped by `max_position_cents` and `max_contracts_per_signal`)
   - Creates a `Signal` record (paper mode) or places a live Kalshi order (live mode)

4. **Settlement** (every 5 min) — Finds signals past their close time. Compares final spot price vs strike to determine winner. P&L: win = (100 − price) × qty, loss = −(price × qty).

### Signal Lifecycle

```
signaled → placed → filled → settled_win / settled_loss
                              (or cancelled on error)
```

- **Paper mode**: Signals go straight to `signaled` and settle based on spot vs strike.
- **Live mode**: Signal engine calls `kalshi.place_order()`, sets status to `placed`. Settlement checks actual market result.

### Probability Model

Binary option pricing via Black-Scholes N(d2):

- **Inputs**: spot price (Binance), strike price (from contract ticker), time to expiry, implied volatility (Deribit), risk-free rate
- **Deribit IV**: Free public API — fetches DVOL index and full IV surface by expiry. Interpolates IV for the contract's time horizon.
- **Output**: Probability that spot > strike at expiry → fair value in cents → edge vs market price

## Architecture

```
┌─────────────┐    ┌───────────┐    ┌──────────┐
│  React SPA  │───▶│  FastAPI   │───▶│ Postgres │
│  (Vite)     │    │  (async)   │    │   16     │
└─────────────┘    └─────┬─────┘    └──────────┘
                         │
                   ┌─────▼─────┐
                   │  Celery   │───▶ Redis 7
                   │  Worker   │
                   └─────┬─────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
          Kalshi API  Deribit    Binance
          (orders)    (IV)      (spot)
```

- **Backend**: FastAPI + async SQLAlchemy (asyncpg) + Alembic
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
make db-up

# 3. Install & migrate
cd backend && uv sync && cd ..
cd frontend && npm install && cd ..
make migrate

# 4. Run everything
make dev
# Or individually:
make dev-backend    # API at http://localhost:8000
make dev-frontend   # UI at http://localhost:5174
# Celery worker + beat (required for scanning):
cd backend && PYTHONPATH=. celery -A app.celery_app worker --beat --loglevel=info
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Register |
| POST | `/api/v1/auth/login` | Login → JWT |
| GET | `/api/v1/auth/me` | Current user |
| GET | `/api/v1/dashboard` | Full dashboard: bot status, signals, opportunities, stats |
| GET | `/api/v1/signals` | Paginated signals (filter by status) |
| GET | `/api/v1/settings/bot-config` | Get bot config |
| PUT | `/api/v1/settings/bot-config` | Update bot config |
| PUT | `/api/v1/settings/kalshi-keys` | Save Kalshi API keys |
| GET | `/api/v1/settings/kalshi-keys` | Key status |
| DELETE | `/api/v1/settings/kalshi-keys` | Remove keys |

## Project Structure

```
deepodds/
├── .env                         # Config (project root, not backend/)
├── docker-compose.yml           # Postgres 16 (port 5433) + Redis 7
├── Makefile
│
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint
│   │   ├── celery_app.py        # Beat schedule: scan 60s, settle 300s
│   │   ├── core/                # Config, database, auth deps
│   │   ├── models/
│   │   │   ├── user.py          # User + encrypted Kalshi keys
│   │   │   ├── opportunity.py   # Scanner results (upserted each cycle)
│   │   │   ├── bot_config.py    # Per-user trading config
│   │   │   └── signal.py        # Trade signals + P&L
│   │   ├── schemas/             # Pydantic request/response
│   │   ├── api/v1/              # auth, dashboard, settings, signals
│   │   ├── services/
│   │   │   ├── market_scanner.py    # Kalshi event scanner
│   │   │   ├── signal_engine.py     # Edge detection + order logic
│   │   │   ├── probability_model.py # Black-Scholes N(d2)
│   │   │   ├── deribit_client.py    # IV surface (free, no auth)
│   │   │   ├── binance_client.py    # Spot prices (binance.us)
│   │   │   └── kalshi_client.py     # RSA-PSS signed requests
│   │   └── tasks/
│   │       ├── scanner.py       # scan_markets → evaluate_all_users
│   │       └── signals.py       # evaluate + settle tasks
│   └── alembic/
│
└── frontend/
    └── src/
        ├── api/                 # client, auth, settings, bot
        ├── stores/              # authStore, botStore (30s polling)
        ├── pages/               # Dashboard, Settings, Login, Register
        └── components/          # BotStatusBar, StatsCard, SignalTable, etc.
```

## Bot Config Defaults

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | paper | paper or live |
| `enabled` | true | Bot active |
| `daily_budget_cents` | 5000 ($50) | Max daily spend |
| `min_edge_cents` | 8.0 | Minimum edge to trigger signal |
| `min_liquidity` | 10.0 | Minimum market liquidity |
| `max_position_cents` | 500 ($5) | Max cost per trade |
| `max_contracts_per_signal` | 10 | Max contracts per signal |

## Kalshi API Notes

- **Signing**: RSA-PSS with `DIGEST_LENGTH` salt, SHA256, message = `{timestamp_ms}{METHOD}{path_without_query}`
- **Base URL**: `https://api.elections.kalshi.com/trade-api/v2` (prod)
- **Auth path**: Full path `/trade-api/v2{endpoint}` must be used for signing
