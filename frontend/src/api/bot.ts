import client from "./client";

export interface KalshiStatus {
  mode: string;
  enabled: boolean;
  has_keys: boolean;
  series_tickers: string;
  open_positions: number;
  max_open_positions: number;
  min_edge: number;
  exit_edge: number;
  current_exposure_usd: number;
  max_payout_usd: number;
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
  venue: string;
  pair: string;
  side: string;
  signal_type: string;
  status: string;
  entry_price: number;
  quantity: number;
  cost_usd: number;
  model_prob: number | null;
  market_prob: number | null;
  edge: number | null;
  floor_strike: number | null;
  cap_strike: number | null;
  strike_type: string | null;
  underlying_price: number | null;
  realized_vol: number | null;
  exchange_order_id: string | null;
  fill_price: number | null;
  fill_quantity: number | null;
  filled_at: string | null;
  exit_price: number | null;
  pnl_usd: number | null;
  pnl_pct: number | null;
  unrealized_pnl_usd: number | null;
  market_ticker: string | null;
  event_ticker: string | null;
  expiry_time: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface KalshiMarketSnapshot {
  ticker: string;
  series: string;
  title: string;
  price: number;
  model_prob: number;
  edge: number;
  floor_strike: number | null;
  cap_strike: number | null;
  strike_type: string;
  underlying_price: number;
  realized_vol: number;
  volume_24h: number;
  hours_to_expiry: number;
  expiry_time: string | null;
  would_signal: boolean;
}

export interface KalshiFilteredMarket {
  ticker: string;
  series: string;
  title: string;
  price: number;
  volume_24h: number;
  hours_to_expiry: number | null;
  filter_reason: string;
}

export interface DashboardData {
  kalshi_status: KalshiStatus | null;
  recent_signals: Signal[];
  kalshi_markets: KalshiMarketSnapshot[];
  kalshi_filtered: KalshiFilteredMarket[];
  stats: PnLStats;
  scanner_health: ScannerHealth | null;
}

export interface ScannerHealth {
  last_scan: string;
  status: string;
  error?: string;
}

export interface KalshiConfig {
  mode: string;
  enabled: boolean;
  series_tickers: string;
  min_volume_24h: number;
  min_price: number;
  max_price: number;
  min_hours_to_expiry: number;
  min_edge: number;
  vol_lookback_hours: number;
  vol_interval: string;
  exit_edge: number;
  contracts_per_signal: number;
  max_cost_per_signal: number;
  max_open_positions: number;
  max_positions_per_event: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  daily_loss_limit_usd: number;
  max_signals_per_hour: number;
  min_hold_minutes: number;
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

export async function getKalshiConfig() {
  const { data } = await client.get<KalshiConfig>("/settings/kalshi-config");
  return data;
}

export async function updateKalshiConfig(updates: Partial<KalshiConfig>) {
  const { data } = await client.put<KalshiConfig>("/settings/kalshi-config", updates);
  return data;
}

export interface PairConfig {
  venue: string;
  pair: string;
  contracts_per_signal: number | null;
  stop_loss_pct: number | null;
  min_edge: number | null;
  exit_edge: number | null;
}

export interface BacktestResult {
  signals_count: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_pnl_usd: number;
  total_pnl_usd: number;
  avg_hold_bars: number;
  data_points: number;
}

export async function getPairConfigs() {
  const { data } = await client.get<PairConfig[]>("/settings/pair-configs");
  return data;
}

export async function updatePairConfig(venue: string, pair: string, updates: Partial<PairConfig>) {
  const { data } = await client.put<PairConfig>(`/settings/pair-configs/${venue}/${pair}`, updates);
  return data;
}

export async function deletePairConfig(venue: string, pair: string) {
  await client.delete(`/settings/pair-configs/${venue}/${pair}`);
}

export async function runBacktestPreview(params: {
  venue: string;
  pair: string;
  stop_loss_pct: number;
  contracts_per_signal?: number;
  min_edge?: number;
  exit_edge?: number;
  vol_lookback_hours?: number;
}) {
  const { data } = await client.post<BacktestResult>("/settings/backtest-preview", params);
  return data;
}

export async function getSignals(params: { statuses?: string; date?: string; limit?: number; offset?: number }) {
  const { data } = await client.get<{ items: Signal[]; total: number }>("/signals", { params });
  return data;
}
