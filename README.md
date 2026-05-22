# DeepOdds — Crypto Mean-Reversion Trading Bot

Automated trading bot for Coinbase crypto markets. Uses a **VWAP mean-reversion** strategy — buying when price drops significantly below its volume-weighted average, then selling when it reverts back.

## How It Works

### Strategy: VWAP Z-Score Mean Reversion

The bot exploits the tendency for prices to revert to their average after sharp moves:

1. **Scanner** (every 60s) — Fetches 15-minute candles from Coinbase for each configured pair (default: BTC-USD, ETH-USD).

2. **VWAP & Std Dev** — Computes the Volume-Weighted Average Price and standard deviation over a lookback window (default 16 bars = 4 hours).

3. **Z-Score** — Measures how far the current price is from VWAP in standard deviations:
   ```
   z = (price - vwap) / std_dev
   ```
   - z = 0 → price is at the average
   - z = -2.0 → price is 2 std devs below average (oversold)
   - z = +1.0 → price is 1 std dev above average (overbought)

4. **Entry** — If z-score drops below -2.0 (configurable) and no position is open for that pair, the bot buys.

5. **Exit** — Two conditions: (1) z-score rises back above 0.0 (price reverted to average), or (2) stop-loss triggers at -3% (configurable).

### Signal Lifecycle

```
signaled → placed (live) / filled (paper) → settled_win / settled_loss
```

### Risk Controls

| Control | Default | Description |
|---------|---------|-------------|
| Position Size | $25 | Fixed dollar amount per trade |
| Max Open Positions | 3 | Caps concurrent positions across all pairs |
| Stop Loss | 3% | Closes position if unrealized loss exceeds threshold |
| Daily Loss Limit | $50 | Pauses the bot for the day if realized losses exceed threshold |
| Max Signals/Hour | 5 | Rate limits new entries |

## Architecture

```
┌─────────────┐    ┌───────────┐    ┌──────────┐
│  React SPA  │───▶│  FastAPI   │───▶│ Postgres │
│  (Vite)     │    │  (async)   │    │   16     │
└─────────────┘    └─────┬─────┘    └──────────┘
                         │
                         │ Native asyncio scheduler
                         │ (scan+exits 60s, live sync 30s)
                         │
              ┌──────────▼──────────┐
              ▼                     ▼
         Coinbase API          Binance API
     (candles, orders)       (price feeds)
```

- **Backend**: FastAPI + async SQLAlchemy + Alembic
- **Scheduler**: Native asyncio loops (no Celery, no Redis)
- **Frontend**: React 19 + TypeScript + Vite + Tailwind CSS v4 + Zustand
- **Auth**: JWT (HS256), per-user Coinbase CDP API keys (ES256) stored server-side

## Prerequisites

- Python 3.13+ / uv
- Node.js 20+
- Docker & Docker Compose (PostgreSQL 16)

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Set: DATABASE_URL, DATABASE_URL_SYNC, JWT_SECRET_KEY

# 2. Start infrastructure
docker compose up -d

# 3. Install & migrate
cd backend && uv sync && PYTHONPATH=. uv run alembic upgrade head && cd ..
cd frontend && npm install && cd ..

# 4. Run everything (scheduler runs inside the backend process)
make dev
```

Or manually:

```bash
cd backend && PYTHONPATH=. uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
cd frontend && npx vite --host 0.0.0.0 --port 5173 &
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Register |
| POST | `/api/v1/auth/login` | Login → JWT |
| GET | `/api/v1/auth/me` | Current user |
| GET | `/api/v1/dashboard` | Bot status, signals, market snapshots, stats |
| GET | `/api/v1/dashboard/pnl-chart` | Daily P&L chart data |
| GET | `/api/v1/signals` | Paginated signals (filter by status) |
| POST | `/api/v1/signals/archive` | Archive signals |
| GET | `/api/v1/signals/archive` | Browse archived signals |
| GET | `/api/v1/settings/bot-config` | Get bot config |
| PUT | `/api/v1/settings/bot-config` | Update bot config |
| PUT | `/api/v1/settings/coinbase-keys` | Save Coinbase CDP API keys |
| GET | `/api/v1/settings/coinbase-keys` | Key status + validation |
| DELETE | `/api/v1/settings/coinbase-keys` | Remove keys |

## Bot Config

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | paper | `paper` or `live` |
| `enabled` | false | Bot active |
| `pairs` | BTC-USD,ETH-USD | Comma-separated Coinbase product IDs |
| `lookback_periods` | 16 | Number of 15-min candles for VWAP (16 = 4 hours) |
| `entry_z_score` | -2.0 | Buy when z-score drops below this |
| `exit_z_score` | 0.0 | Sell when z-score rises above this |
| `position_size_usd` | 25.0 | Dollar amount per trade |
| `max_open_positions` | 3 | Max concurrent positions |
| `stop_loss_pct` | 3.0 | Stop-loss percentage |
| `daily_loss_limit_usd` | 50.0 | Daily loss circuit breaker |
| `max_signals_per_hour` | 5 | Rate limit |

## Scheduler

The scheduler runs inside the FastAPI process as asyncio background tasks:

| Loop | Interval | What it does |
|------|----------|--------------|
| Scan + Exits | 60s | Fetch candles, evaluate z-scores, generate entry signals, check exit conditions |
| Live Sync | 30s | Check placed order statuses on Coinbase, detect fills |

## Project Structure

```
deepodds/
├── docker-compose.yml          # PostgreSQL 16
├── Makefile                    # dev, migrate, restart, lint, test
├── scripts/                    # restart.sh, start-backend.sh, start-frontend.sh
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI entrypoint + scheduler startup
│   │   ├── core/               # Config, database, auth, async_util, scheduler
│   │   ├── models/             # User, BotConfig, Signal, ArchivedSignal
│   │   ├── schemas/            # Pydantic request/response models
│   │   ├── api/v1/             # REST endpoints (auth, dashboard, signals, settings)
│   │   └── services/
│   │       ├── coinbase_client.py  # Coinbase CDP API client (JWT/ES256 auth)
│   │       ├── mean_reversion.py   # VWAP z-score strategy (entry, exit, sync)
│   │       ├── binance_client.py   # Public price feeds
│   │       └── archive.py          # Signal archival
│   └── alembic/                # Database migrations
└── frontend/
    └── src/
        ├── api/                # Typed API client (auth, bot, settings)
        ├── stores/             # Zustand (auth state)
        ├── pages/              # Dashboard, Settings, Resources, Login, Register
        └── components/         # BotStatusBar, SignalTable, MarketView, StatsCard, PnLChart
```
