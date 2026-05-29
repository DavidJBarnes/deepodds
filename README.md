# DeepOdds — Kalshi event-contract trading bot

Automated trading bot that scans **Kalshi event contracts** (crypto range markets and climate daily-extreme markets), prices them with venue-specific probability models, and trades when our estimated probability is meaningfully higher than the market's implied probability.

Paper mode and live mode share the same scanning + pricing pipeline; live mode places real Kalshi orders via the user's per-account API key.

## Strategy

**Crypto** — For each Kalshi range contract on BTC / ETH / XRP / SOL, an XGBoost model trained on synthetic contracts generated from historical Binance data estimates *P(price ends in this range at expiry)* using 24h realized vol + drift. We buy when our probability exceeds the market's implied probability by ≥ `min_edge` (default 8%).

**Climate** — For each Kalshi daily-extreme contract (high temp, low temp, rain) we pull Open-Meteo's forecast for the resolution date at the actual NWS station (KSEA, KDFW, KLAX…) and use it as the spot; an XGBoost model estimates *P(strike condition is true)* using forecast-vs-strike in sigma units. Same `min_edge` filter.

Both venues currently run in **paper mode** with `stop_loss_pct=0`, `take_profit_pct=0`, `exit_edge=-50%` — i.e., positions hold to expiry settlement rather than being closed on intraday price movement.

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  React SPA   │───▶│   FastAPI    │───▶│  Postgres    │
│  (Vite)      │    │  (async)     │    │  (RDS prod)  │
└──────────────┘    └───────┬──────┘    └──────────────┘
                            │
                            │  asyncio scheduler (in-process)
                            │
        ┌─────────────┬─────┴─────┬──────────────────┐
        ▼             ▼           ▼                  ▼
    Kalshi REST   Binance     Open-Meteo       XGBoost models
    (markets,    (klines,     (forecast +      (per-venue,
     orders,     spot)         archive)         retrained weekly)
     balance)
```

- **Backend** — FastAPI · async SQLAlchemy · Alembic · native asyncio scheduler (no Celery / Redis)
- **Frontend** — React 19 · TypeScript · Vite · Tailwind CSS · Zustand · Recharts
- **ML** — XGBoost (binary:logistic) trained on synthetic Kalshi-style contracts: crypto from Binance klines, climate from Open-Meteo daily extremes
- **Auth** — JWT (HS256); each user stores their own Kalshi API key + ED25519 private key server-side

## Project layout

```
deepodds/
├── docker-compose.yml             # local Postgres
├── Makefile
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI entrypoint + scheduler startup
│   │   ├── core/
│   │   │   ├── config.py          # pydantic-settings (DATABASE_URL, JWT_SECRET_KEY, …)
│   │   │   ├── database.py        # async engine
│   │   │   ├── scheduler.py       # 7 asyncio loops (scan/exit/sync/retrain × venues)
│   │   │   └── async_util.py
│   │   ├── api/v1/
│   │   │   ├── auth.py            # register, login, me
│   │   │   ├── dashboard.py       # /dashboard, /dashboard/pnl-chart  (venue filter)
│   │   │   ├── signals.py         # paginated signal list
│   │   │   ├── settings.py        # crypto-config, climate-config, kalshi-keys, balance
│   │   │   ├── calibration.py     # calibration chart + retrain trigger
│   │   │   ├── history.py
│   │   │   └── model_training.py  # retrain audit log
│   │   ├── models/                # User, CryptoConfig, ClimateConfig, Signal, History, …
│   │   ├── schemas/               # Pydantic request/response models
│   │   └── services/
│   │       ├── kalshi_client.py           # signed REST client
│   │       ├── kalshi_utils.py            # shared market helpers
│   │       ├── kalshi_fair_value.py       # crypto scanner + exits
│   │       ├── climate_fair_value.py      # climate scanner + exits
│   │       ├── kalshi_live_sync.py        # live order/fill tracking
│   │       ├── binance_client.py          # spot + klines + realized vol
│   │       ├── weather_client.py          # Open-Meteo forecast + history
│   │       ├── probability_model.py       # crypto XGBoost wrapper
│   │       ├── climate_probability_model.py
│   │       ├── train_model.py             # crypto trainer
│   │       └── train_climate_model.py     # climate trainer
│   ├── alembic/                   # migrations
│   └── app/core/xgboost_*.json    # trained models (committed)
└── frontend/
    └── src/
        ├── api/                   # typed client (auth, bot, settings)
        ├── pages/                 # Dashboard, Crypto, Climate, History, Settings, Resources, Login, Register
        ├── components/            # PnLChart, CalibrationChart, SignalTable, BotStatusBar, …
        ├── stores/                # Zustand (auth, bot dashboard)
        └── hooks/
```

## Prerequisites

- Python 3.13+ (with [`uv`](https://docs.astral.sh/uv/))
- Node.js 20+
- Docker + Docker Compose (for local Postgres)

## Quick start

```bash
# 1. Configure
cp .env.example .env
# Set: DATABASE_URL, DATABASE_URL_SYNC, JWT_SECRET_KEY, CORS_ORIGINS

# 2. Start Postgres
docker compose up -d

# 3. Backend
cd backend
uv sync
PYTHONPATH=. uv run alembic upgrade head
PYTHONPATH=. uv run uvicorn app.main:app --reload --port 8000
# (in another shell)
cd frontend
npm install
npm run dev
```

Or `make dev` from the root.

## API endpoints

All under `/api/v1`. `venue` parameter is one of `all | kalshi_crypto | kalshi_climate` (or `kalshi_crypto | kalshi_climate` only, for endpoints that don't aggregate).

| Method | Endpoint | Notes |
|---|---|---|
| `POST` | `/auth/register` | Returns JWT |
| `POST` | `/auth/login` | Returns JWT |
| `GET` | `/auth/me` | Current user |
| `GET` | `/dashboard?venue=` | Stats, recent signals, market opportunities, scanner health |
| `GET` | `/dashboard/pnl-chart?venue=&days=` | Daily P&L for charting |
| `GET` | `/signals?venue=&date=&statuses=` | Paginated signals |
| `GET` | `/calibration?venue=` | Calibration bins + Brier score |
| `POST` | `/calibration/retrain` | Manual retrain of both models |
| `GET` | `/model-training-history` | Retrain audit log (manual + scheduled) |
| `GET` | `/history` | Per-user History entries |
| `GET` `PUT` | `/settings/crypto-config` | Crypto bot config |
| `GET` `PUT` | `/settings/climate-config` | Climate bot config |
| `GET` `PUT` `DELETE` | `/settings/kalshi-keys` | Kalshi platform credentials |
| `GET` | `/settings/kalshi-balance` | Live Kalshi account balance (cached) |
| `POST` | `/settings/reset-data` | Truncate signals for the current user |

## Scheduler

Seven asyncio loops run inside the FastAPI process:

| Loop | Interval | What it does |
|---|---|---|
| `kalshi_scan` | 30 s | Discover crypto markets, price with `probability_model`, create signals when edge ≥ `min_edge` |
| `kalshi_exit` | 15 s | Check exit conditions on filled crypto positions (stops / take-profit / edge-lost / post-expiry) |
| `kalshi_sync_live` | 30 s | Track live Kalshi order status, detect fills, sync settlements |
| `kalshi_retrain` | weekly | Regenerate synthetic training data, retrain crypto XGBoost, reload in-process |
| `climate_scan` | 30 s | Same as `kalshi_scan` but for climate markets via Open-Meteo forecasts |
| `climate_exit` | 15 s | Same as `kalshi_exit` for climate; settles paper positions against actual NWS daily extremes |
| `climate_retrain` | weekly | Retrain climate XGBoost across all supported NWS stations |

## Bot config

Per-venue (`crypto_configs` and `climate_configs` tables). Both schemas share most knobs:

| Parameter | Default (crypto / climate) | Description |
|---|---|---|
| `mode` | `paper` | `paper` or `live` |
| `enabled` | `false` | Bot active |
| `series_tickers` | `KXBTC,KXETH,KXXRP,KXSOL` / `KXHIGHTSFO,KXHIGHTATL,…` | Kalshi series to scan |
| `min_volume_24h` | 50 / 20 | Skip illiquid markets |
| `min_price` / `max_price` | 0.05 – 0.80 | Price-range gate |
| `min_hours_to_expiry` | 2 | Minimum time to settlement at entry |
| `min_edge` | 0.08 | Required edge before signaling |
| `contracts_per_signal` | 50 / 25 | Position sizing |
| `max_cost_per_signal` | $25 | Per-position cap |
| `max_open_positions` | 5 / 3 | Concurrent open positions |
| `max_positions_per_event` | 1 | Diversification (enforced by unique partial index) |
| `stop_loss_pct` | 0 | `0` disables stops → **hold to resolution** |
| `take_profit_pct` | 0 | `0` disables early take-profit |
| `exit_edge` | −50 | `-50` disables edge-loss exit |
| `daily_loss_limit_usd` | $25 / $15 | Daily circuit breaker |
| `max_signals_per_hour` | 3 | Rate limit |
| `min_hold_minutes` | 10 / 15 | Floor on hold time when stops are on |

### Hold-to-resolution mode

Set `stop_loss_pct = 0`, `take_profit_pct = 0`, `exit_edge = -50` to disable all price-based exit logic. Positions then ride to natural settlement (Kalshi auto-settles live; the scheduler settles paper positions against the actual underlying — NWS reports for climate, market settlement for crypto). Use this for clean calibration data: every exit corresponds to an observed outcome.

## Model retraining

Both models retrain on a weekly cron inside the scheduler. To trigger manually:

- Settings page → SOTA Machine Learning Model → **Retrain Models Now** (takes ~90 s)
- Or `POST /api/v1/calibration/retrain`

Outcomes (success, model file sizes, trigger source) land in `model_train_history` and are surfaced under "Training Runs" on the Settings page.

## Calibration

The dashboard shows two per-venue calibration charts (crypto, climate) with bin-wise comparison of model probability vs actual win rate, plus a Brier score. The query filters to *real* settlements only: `exit_price IN (0, 1)` OR position held > 2 hours. Take-profit / edge-exit closes are excluded because we don't observe the underlying outcome on those.

## Deployment notes

- Backend deploys as an ECR Docker image to a single EC2 instance via GitHub Actions + SSM Run Command
- Frontend deploys the same way to its own container
- Both fronted by a host-level Nginx (gateway) terminating TLS via Let's Encrypt (auto-renew systemd timer)
- Database: Amazon RDS Postgres
- Compute Savings Plan covers EC2; Database Savings Plan covers RDS
