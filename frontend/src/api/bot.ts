import client from "./client";

export interface BotStatus {
  mode: string;
  enabled: boolean;
  has_kalshi_keys: boolean;
  has_coinbase_keys: boolean;
  spot_enabled: boolean;
  spot_mode: string;
  spot_dip_pct: number;
  spot_take_profit_pct: number;
  spot_stop_loss_pct: number;
  max_exposure_cents: number;
  current_exposure_cents: number;
  exposure_remaining_cents: number;
  daily_budget_cents: number;
  daily_spent_cents: number;
  signals_today: number;
  active_signals: number;
}

export interface PnLStats {
  total_signals: number;
  settled_count: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl_cents: number;
  total_cost_cents: number;
  roi_pct: number;
  unrealized_pnl_cents: number;
  open_positions: number;
}

export interface Signal {
  id: string;
  ticker: string;
  side: string;
  action: string;
  limit_price_cents: number;
  quantity: number;
  cost_cents: number;
  signal_type: string;
  status: string;
  model_prob: number | null;
  model_fair_cents: number | null;
  model_edge_cents: number | null;
  edge_tier: string | null;
  implied_vol: number | null;
  market_yes_price_cents: number | null;
  spot_price: number | null;
  strike_price: number | null;
  kalshi_order_id: string | null;
  fill_price_cents: number | null;
  exit_price_cents: number | null;
  filled_at: string | null;
  unrealized_pnl_cents: number | null;
  pnl_cents: number | null;
  settled_side: string | null;
  close_time: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface Opportunity {
  ticker: string;
  asset: string;
  title: string;
  strike_price: number | null;
  spot_price: number | null;
  yes_price: number | null;
  model_fair_cents: number | null;
  model_edge_cents: number | null;
  implied_vol: number | null;
  liquidity: number;
  close_time: string | null;
  quality: string;
}

export interface SpotPnLStats {
  total_trades: number;
  open_position_btc: number;
  open_position_usd: number;
  unrealized_pnl_usd: number;
  realized_pnl_usd: number;
}

export interface SpotTrade {
  id: string;
  side: string;
  price_usd: number;
  quantity_btc: number;
  amount_usd: number;
  trigger: string;
  status: string;
  coinbase_order_id: string | null;
  pnl_usd: number | null;
  created_at: string;
}

export interface SpotPosition {
  id: string;
  entry_price_usd: number;
  quantity_btc: number;
  cost_basis_usd: number;
  status: string;
  unrealized_pnl_usd: number | null;
  opened_at: string;
  closed_at: string | null;
}

export interface SpotPrice {
  price: number | null;
  high_1h: number | null;
  high_4h: number | null;
  dip_pct: number | null;
  dip_pct_4h: number | null;
  updated: number | null;
}

export interface DashboardData {
  bot_status: BotStatus;
  recent_signals: Signal[];
  opportunities: Opportunity[];
  stats: PnLStats;
  spot_stats: SpotPnLStats | null;
}

export interface BotConfig {
  mode: string;
  enabled: boolean;
  max_exposure_cents: number;
  daily_budget_cents: number;
  min_edge_cents: number;
  min_liquidity: number;
  max_position_cents: number;
  max_contracts_per_signal: number;
  max_position_cents_moderate: number;
  max_contracts_moderate: number;
  max_position_cents_high: number;
  max_contracts_high: number;
  max_position_cents_elite: number;
  max_contracts_elite: number;
  take_profit_cents: number;
  stop_loss_cents: number;
  daily_loss_limit_cents: number;
  max_signals_per_hour: number;
  tier_budget_pct_elite: number;
  tier_budget_pct_high: number;
  max_positions_per_asset: number;
  min_yes_prob: number;
  expiry_exit_minutes: number;
  spot_enabled: boolean;
  spot_mode: string;
  spot_dip_pct: number;
  spot_take_profit_pct: number;
  spot_stop_loss_pct: number;
  spot_buy_amount_usd: number;
  spot_max_position_usd: number;
  spot_cooldown_minutes: number;
}

export interface DailyPnLPoint {
  date: string;
  pnl_cents: number;
  cumulative_pnl_cents: number;
  signals_count: number;
  wins: number;
  losses: number;
}

export interface PnLChartData {
  daily: DailyPnLPoint[];
  total_pnl_cents: number;
  best_day_cents: number;
  worst_day_cents: number;
  winning_days: number;
  losing_days: number;
}

export async function getPnLChart(days = 30) {
  const { data } = await client.get<PnLChartData>("/dashboard/pnl-chart", { params: { days } });
  return data;
}

export async function getDashboard() {
  const { data } = await client.get<DashboardData>("/dashboard");
  return data;
}

export async function getBotConfig() {
  const { data } = await client.get<BotConfig>("/settings/bot-config");
  return data;
}

export async function updateBotConfig(updates: Partial<BotConfig>) {
  const { data } = await client.put<BotConfig>("/settings/bot-config", updates);
  return data;
}

export async function getSignals(params: { status?: string; limit?: number; offset?: number }) {
  const { data } = await client.get<{ items: Signal[]; total: number }>("/signals", { params });
  return data;
}

export async function getSpotTrades() {
  const { data } = await client.get<SpotTrade[]>("/spot/trades");
  return data;
}

export async function getSpotPosition() {
  const { data } = await client.get<SpotPosition | null>("/spot/position");
  return data;
}

export async function getSpotPrice() {
  const { data } = await client.get<SpotPrice>("/spot/price");
  return data;
}

export async function getSpotStats() {
  const { data } = await client.get<SpotPnLStats>("/spot/stats");
  return data;
}
