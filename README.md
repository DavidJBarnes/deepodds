# DeepOdds — Automated Crypto Trading Platform

Automated trading platform combining Kalshi crypto prediction markets with BTC spot "buy the dip" trading. Uses a Black-Scholes probability model with Deribit implied volatility for prediction market signals, and Binance real-time websocket streaming with configurable dip detection for spot BTC execution via Coinbase.

## How It Works

### Spot BTC — Buy the Dip

A parallel trading engine that buys BTC during price dips and sells on recovery:

1. **Price Streaming** — A persistent Binance websocket connection streams real-time BTC trades. Each price is written to Redis along with a rolling 1-hour high watermark.

2. **Dip Detection** (every 10s) — Celery Beat triggers `check_spot_signals`, which:
   - Reads current price and 1h high from Redis
   - For each user with `spot_enabled=True`, calculates: `dip_pct = (high_1h - price) / high_1h × 100`
   - If dip ≥ `spot_dip_pct` threshold (default 3%), no buy in last `spot_cooldown_minutes` (default 60), and position < `spot_max_position_usd` (default $500): **buy**
   - Paper mode: creates `SpotTrade(status="filled")` at current price, updates `SpotPosition` with weighted-average entry
   - Live mode: calls Coinbase Advanced Trade API `create_market_order("BUY", "BTC-USD", amount)`

3. **Exit Logic** — Same 10s cycle checks open positions:
   - **Take profit**: if `(price - entry) / entry × 100 ≥ spot_take_profit_pct` (default 2%) → sell
   - **Stop loss**: if `(price - entry) / entry × 100 ≤ -spot_stop_loss_pct` (default 5%) → sell
   - Closes position, records P&L on the sell trade

4. **Dollar-Cost Averaging** — If BTC keeps dropping and the cooldown expires, the bot buys again (up to max position). Entry price becomes the weighted average across all buys, improving the breakeven point.

### Kalshi Prediction Markets — Signal Detection Loop

1. **Scanner** (every 60s) — Celery Beat triggers `scan_markets`, which fetches all active crypto contracts from Kalshi's events API for series `KXBTC`, `KXBTCD`, `KXETH`, `KXETHD`. For each contract it pulls the current spot price (Binance), implied volatility (Deribit DVOL surface + Binance realized vol), and computes a model probability using Black-Scholes N(d2).

2. **Edge Calculation** — For each opportunity the scanner computes:
   - `model_fair_cents` = model probability × 100 (what the contract should be worth)
   - `model_edge_cents` = fair − ask price (positive = YES is cheap, negative = NO is cheap)

3. **Signal Engine** (runs after each scan) — For every user with an enabled `BotConfig`, evaluates all opportunities:
   - Edge must exceed `min_edge_cents` (default 8¢)
   - Liquidity must exceed `min_liquidity` (default 10)
   - No existing open signal on same ticker
   - 2-hour cooldown after a loss on the same ticker
   - YES bets restricted to high-probability only (model_prob > 50%)
   - Range contracts: skip 10-30¢ dead zone (0% historical win rate)
   - Daily spend must not exceed `daily_budget_cents` (default $50)
   - Computes side (yes if edge > 0, no if edge < 0), limit price, quantity (capped by `max_position_cents` and `max_contracts_per_signal`)
   - Creates a `Signal` record (paper mode) or places a live Kalshi order (live mode)

4. **Paper Fill Simulation** (runs after signal evaluation) — Checks `signaled` paper orders against current market ask prices. If ask ≤ limit price, marks the signal as `filled` with the actual ask as `fill_price_cents` and records `filled_at` timestamp. This simulates realistic order fills rather than assuming instant execution.

5. **Take-Profit Monitor** (runs after fill simulation) — Checks `filled` paper positions against current market bid prices (what you could sell at). If unrealized profit per contract ≥ the user's `take_profit_cents` threshold, exits early: sets `status = "settled_win"`, records `exit_price_cents`, and computes P&L net of Kalshi fees.

6. **Settlement** (every 5 min) — Finds signals past their close time that haven't already been closed by take-profit. Compares final spot price vs strike to determine winner. P&L uses actual `fill_price_cents` when available (not the limit price). Wins are net of estimated Kalshi fees.

### Fee Model

P&L accounting includes estimated Kalshi transaction fees:
- **Fee rate**: 7% of profit per contract
- **Minimum fee**: 2¢ per contract
- Fees only apply to winning trades (Kalshi charges on profit, not on losses)
- Formula: `net_pnl = gross_pnl - max(2, floor(profit_per_contract × 0.07)) × quantity`

### Signal Lifecycle

```
Paper mode:
  signaled → filled (sim) → settled_win (take-profit or expiry)
                           → settled_loss (expiry)

Live mode:
  signaled → placed → filled → settled_win / settled_loss
```

- **Paper mode**: Signals start as `signaled`. Fill simulation checks each cycle if the market ask ≤ limit price → `filled`. Take-profit monitor checks if bid − fill ≥ threshold → early `settled_win`. Otherwise settles at expiry based on spot vs strike.
- **Live mode**: Signal engine calls `kalshi.place_order()`, sets status to `placed`. Settlement checks actual market result.

### Probability Model

Binary option pricing via Black-Scholes N(d2), with support for above/below/between (range) contracts:

- **Inputs**: spot price (Binance), strike price (from contract), time to expiry, blended volatility, risk-free rate
- **Volatility Blending**: Deribit IV surface (options-implied) is blended with Binance realized volatility (4h 1-minute klines). For short-term contracts (<6h), realized vol is weighted 60%; for 6-24h, 30%; beyond 24h, Deribit IV only. This captures recent price action that the options market may lag.
- **Contract types**: `prob_above` (spot > strike), `prob_below` (spot < strike), `prob_between` (floor < spot < cap)
- **Output**: Probability → fair value in cents → edge vs market ask price

### Signal Archive

Signals are preserved for historical analysis. Instead of deleting, the archive system moves settled signals to `archived_signals` with a `run_id` tag for grouping. The archive is queryable via API (`GET /api/v1/signals/archive`) and filterable by run.

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/signals/archive` | Archive current user's signals (returns run_id) |
| `GET /api/v1/signals/archive` | List archived signals (filter by run_id) |

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
          ┌──────────┬───┼───────┬──────────┐
          ▼          ▼   ▼       ▼          ▼
      Kalshi API  Deribit Binance  Coinbase
      (contracts) (IV)   (spot)   (spot orders)
```

- **Backend**: FastAPI + async SQLAlchemy (asyncpg) + Alembic
- **Tasks**: Celery + Redis, Celery Beat for scheduling
- **Streaming**: Binance websocket → Redis price cache (sub-second updates)
- **Frontend**: React 19 + TypeScript + Vite + Tailwind CSS v4 + Zustand
- **Auth**: JWT (HS256), per-user Kalshi RSA + Coinbase HMAC keys stored server-side

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
| GET | `/api/v1/dashboard` | Full dashboard: bot status, signals, opportunities, Kalshi + spot stats |
| GET | `/api/v1/signals` | Paginated signals (filter by status) |
| POST | `/api/v1/signals/archive` | Archive signals → archived_signals table |
| GET | `/api/v1/signals/archive` | Browse archived signals (filter by run_id) |
| GET | `/api/v1/settings/bot-config` | Get bot config (Kalshi + spot settings) |
| PUT | `/api/v1/settings/bot-config` | Update bot config |
| PUT | `/api/v1/settings/kalshi-keys` | Save Kalshi API keys |
| GET | `/api/v1/settings/kalshi-keys` | Key status |
| DELETE | `/api/v1/settings/kalshi-keys` | Remove keys |
| PUT | `/api/v1/settings/coinbase-keys` | Save Coinbase API keys |
| GET | `/api/v1/settings/coinbase-keys` | Key status |
| DELETE | `/api/v1/settings/coinbase-keys` | Remove keys |
| GET | `/api/v1/spot/price` | Current BTC price + 1h high from Redis |
| GET | `/api/v1/spot/price/stream` | SSE stream of price updates (1s interval) |
| GET | `/api/v1/spot/trades` | List spot trades for current user |
| GET | `/api/v1/spot/position` | Current open spot position (or null) |
| GET | `/api/v1/spot/stats` | Spot P&L summary |

## Project Structure

```
deepodds/
├── .env                         # Config (project root, not backend/)
├── .skills/                     # Agent skills (Claude Code custom agents)
│   ├── crypto-trading-expert/   # Trading strategy & P&L analysis
│   └── performance-auditor/     # Performance & optimization review
├── docker-compose.yml           # Postgres 16 (port 5433) + Redis 7
├── Makefile
│
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint
│   │   ├── celery_app.py        # Beat schedule: scan 60s, settle 300s, paper sim chained
│   │   ├── core/                # Config, database, auth deps
│   │   ├── models/
│   │   │   ├── user.py              # User + Kalshi/Coinbase API keys
│   │   │   ├── opportunity.py       # Scanner results (upserted each cycle)
│   │   │   ├── bot_config.py        # Per-user config (Kalshi + spot settings)
│   │   │   ├── signal.py            # Kalshi trade signals + P&L
│   │   │   ├── spot_trade.py        # Spot BTC trade records
│   │   │   ├── spot_position.py     # Open/closed spot BTC positions
│   │   │   └── archived_signal.py   # Historical signal archive
│   │   ├── schemas/             # Pydantic request/response (incl. spot.py)
│   │   ├── api/v1/              # auth, dashboard, settings, signals, spot
│   │   ├── services/
│   │   │   ├── market_scanner.py    # Kalshi event scanner + vol blending
│   │   │   ├── signal_engine.py     # Edge detection, fill sim, take-profit, settlement
│   │   │   ├── probability_model.py # Black-Scholes N(d2) (above/below/between)
│   │   │   ├── deribit_client.py    # IV surface (free, no auth)
│   │   │   ├── binance_client.py    # Spot prices + realized vol (binance.us)
│   │   │   ├── binance_ws.py        # Persistent BTC price websocket → Redis
│   │   │   ├── coinbase_client.py   # Coinbase Advanced Trade API (HMAC-signed)
│   │   │   ├── spot_engine.py       # Dip detection, buy/sell logic, TP/SL exits
│   │   │   ├── kalshi_client.py     # RSA-PSS signed requests
│   │   │   └── archive.py          # Signal archival (sync + async)
│   │   └── tasks/
│   │       ├── scanner.py       # scan → evaluate → paper sim (chained)
│   │       ├── signals.py       # evaluate, settle, process_paper_positions tasks
│   │       └── spot.py          # spot signal check (10s), binance stream startup
│   └── alembic/
│
└── frontend/
    └── src/
        ├── api/                 # client, auth, settings, bot
        ├── stores/              # authStore, botStore (60s polling + 2s spot price)
        ├── pages/               # Dashboard, Settings, Login, Register, Resources
        └── components/          # BotStatusBar, StatsCard, SignalTable, SpotTab, etc.
```

## Bot Config Defaults

### Kalshi Prediction Markets

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | paper | paper or live |
| `enabled` | true | Bot active |
| `daily_budget_cents` | 5000 ($50) | Max daily spend |
| `min_edge_cents` | 8.0 | Minimum edge to trigger signal |
| `min_liquidity` | 10.0 | Minimum market liquidity |
| `max_position_cents` | 500 ($5) | Max cost per trade |
| `max_contracts_per_signal` | 10 | Max contracts per signal |
| `take_profit_cents` | 15 | Exit when profit/contract ≥ this (0 = disabled) |

### Spot BTC Trading

| Parameter | Default | Description |
|-----------|---------|-------------|
| `spot_enabled` | false | Spot trading active |
| `spot_mode` | paper | paper or live |
| `spot_dip_pct` | 3.0 | Buy when price drops this % from 1h high |
| `spot_take_profit_pct` | 2.0 | Sell when price rises this % from entry |
| `spot_stop_loss_pct` | 5.0 | Sell when price drops this % from entry |
| `spot_buy_amount_usd` | 50 | USD to spend per dip buy |
| `spot_max_position_usd` | 500 | Max total USD in BTC |
| `spot_cooldown_minutes` | 60 | Min time between buys |

## Task Chains

### Kalshi (every 30s)

1. `scan_markets` — Fetch opportunities from Kalshi, Deribit, Binance
2. `evaluate_all_users` — Generate signals for each user based on their config
3. `process_paper_positions` — Simulate fills + check take-profit thresholds

Settlement (`settle_signals`) runs independently every 5 minutes.

### Spot BTC (every 10s)

1. `check_spot_signals` — Read BTC price from Redis, check dip thresholds, check TP/SL exits

### Persistent

- `start_binance_stream` — Launched on worker startup, maintains websocket connection to Binance, writes prices to Redis

## External API Notes

### Kalshi

- **Signing**: RSA-PSS with `DIGEST_LENGTH` salt, SHA256, message = `{timestamp_ms}{METHOD}{path_without_query}`
- **Base URL**: `https://api.elections.kalshi.com/trade-api/v2` (prod)
- **Auth path**: Full path `/trade-api/v2{endpoint}` must be used for signing

### Coinbase Advanced Trade

- **Signing**: HMAC-SHA256, message = `{timestamp}{METHOD}{path}{body}`
- **Base URL**: `https://api.coinbase.com/api/v3/brokerage`
- **Order type**: Market IOC (immediate-or-cancel) with `quote_size` in USD

### Binance Websocket

- **Primary**: `wss://fstream.binance.com/ws/btcusdt@trade` (futures stream, globally accessible)
- **Fallbacks**: `wss://stream.binance.com:9443/...` (global, may be geo-blocked), `wss://stream.binance.us:9443/...` (US)
- **Auto-selection**: On worker startup, tests each endpoint and uses the first that responds
