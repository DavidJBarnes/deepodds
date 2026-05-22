import client from "./client";

export interface BotStatus {
  mode: string;
  enabled: boolean;
  has_coinbase_keys: boolean;
  coinbase_keys_valid: boolean;
  pairs: string;
  open_positions: number;
  max_open_positions: number;
  entry_z_score: number;
  exit_z_score: number;
  stop_loss_pct: number;
}

export interface PnLStats {
  total_signals: number;
  settled_count: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl_usd: number;
  total_cost_usd: number;
  roi_pct: number;
  unrealized_pnl_usd: number;
  open_positions: number;
}

export interface Signal {
  id: string;
  pair: string;
  side: string;
  signal_type: string;
  status: string;
  entry_price: number;
  quantity: number;
  cost_usd: number;
  z_score: number | null;
  vwap: number | null;
  coinbase_order_id: string | null;
  fill_price: number | null;
  fill_quantity: number | null;
  filled_at: string | null;
  exit_price: number | null;
  exit_z_score: number | null;
  pnl_usd: number | null;
  pnl_pct: number | null;
  unrealized_pnl_usd: number | null;
  created_at: string;
  resolved_at: string | null;
}

export interface MarketSnapshot {
  pair: string;
  price: number;
  vwap: number;
  z_score: number;
  std_dev: number;
  would_signal: boolean;
}

export interface DashboardData {
  bot_status: BotStatus;
  recent_signals: Signal[];
  markets: MarketSnapshot[];
  stats: PnLStats;
  scanner_health: ScannerHealth | null;
}

export interface ScannerHealth {
  last_scan: string;
  status: string;
  error?: string;
}

export interface BotConfig {
  mode: string;
  enabled: boolean;
  pairs: string;
  lookback_periods: number;
  entry_z_score: number;
  exit_z_score: number;
  position_size_usd: number;
  max_open_positions: number;
  stop_loss_pct: number;
  daily_loss_limit_usd: number;
  max_signals_per_hour: number;
}

export interface DailyPnLPoint {
  date: string;
  pnl_usd: number;
  cumulative_pnl_usd: number;
  signals_count: number;
  wins: number;
  losses: number;
}

export interface PnLChartData {
  daily: DailyPnLPoint[];
  total_pnl_usd: number;
  best_day_usd: number;
  worst_day_usd: number;
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
