import client from "./client";

export interface BotStatus {
  mode: string;
  strategy: string;
  enabled: boolean;
  has_kalshi_keys: boolean;
  kalshi_keys_valid: boolean;
  max_exposure_cents: number;
  current_exposure_cents: number;
  exposure_remaining_cents: number;
  daily_budget_cents: number;
  daily_spent_cents: number;
  signals_today: number;
  active_signals: number;
  settlement_arb_enabled: boolean;
  settlement_arb_max_minutes: number;
  settlement_arb_min_sigma: number;
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
  market_yes_price_cents: number | null;
  spot_price: number | null;
  strike_price: number | null;
  cap_strike: number | null;
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
  cap_strike: number | null;
  spot_price: number | null;
  yes_price: number | null;
  no_price: number | null;
  yes_ask: number | null;
  no_ask: number | null;
  model_prob: number | null;
  model_fair_cents: number | null;
  model_edge_cents: number | null;
  liquidity: number;
  close_time: string | null;
  strike_type: string | null;
  sigma_distance: number | null;
  discount_cents: number | null;
  would_signal: boolean;
}

export interface DashboardData {
  bot_status: BotStatus;
  recent_signals: Signal[];
  opportunities: Opportunity[];
  stats: PnLStats;
  scanner_health: ScannerHealth | null;
}

export interface ScannerHealth {
  last_scan: string;
  opportunities: number;
  keys_valid: boolean;
  error: string | null;
}

export interface BotConfig {
  mode: string;
  strategy: string;
  enabled: boolean;
  max_exposure_cents: number;
  daily_budget_cents: number;
  min_edge_cents: number;
  min_liquidity: number;
  max_positions_per_asset: number;
  max_signals_per_hour: number;
  daily_loss_limit_cents: number;
  settlement_arb_enabled: boolean;
  settlement_arb_max_minutes: number;
  settlement_arb_min_sigma: number;
  settlement_arb_min_discount_cents: number;
  settlement_arb_max_position_cents: number;
  settlement_arb_regime_filter: boolean;
  settlement_arb_min_fear_greed: number;
  max_portfolio_risk_cents: number;
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
