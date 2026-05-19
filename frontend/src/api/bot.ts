import client from "./client";

export interface BotStatus {
  mode: string;
  enabled: boolean;
  has_kalshi_keys: boolean;
  daily_budget_cents: number;
  daily_spent_cents: number;
  daily_remaining_cents: number;
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
  implied_vol: number | null;
  market_yes_price_cents: number | null;
  spot_price: number | null;
  strike_price: number | null;
  kalshi_order_id: string | null;
  fill_price_cents: number | null;
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

export interface DashboardData {
  bot_status: BotStatus;
  recent_signals: Signal[];
  opportunities: Opportunity[];
  stats: PnLStats;
}

export interface BotConfig {
  mode: string;
  enabled: boolean;
  daily_budget_cents: number;
  min_edge_cents: number;
  min_liquidity: number;
  max_position_cents: number;
  max_contracts_per_signal: number;
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
