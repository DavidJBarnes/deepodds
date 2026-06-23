import client from "./client";

// ---------------------------------------------------------------------------
// Longshot-short paper harness
// ---------------------------------------------------------------------------

export interface LongshotHeartbeat {
  wall_ts: number;
  tick_ts: string | null;
  status: string;
  equity: number | null;
  open_positions: number | null;
  error: string | null;
}

export interface LongshotSlippage {
  orders: number;
  fill_rate: number | null;
  avg_slippage_c: number | null;
}

export interface LongshotLatest {
  ts: string;
  equity: number;
  realized_pnl: number;
  open_positions: number;
  settled_positions: number;
  opened_this_tick: number;
  settled_this_tick: number;
  hit_rate_no: number | null;
  roi_on_settled_collateral: number | null;
  deployed_collateral: number;
  // live-mode only (undefined for paper)
  mode?: string;
  balance?: number | null;
  killed?: boolean;
  dry_run?: boolean;
  slippage?: LongshotSlippage;
}

export interface LongshotSeriesPoint {
  ts: string;
  equity: number;
  settled: number | null;
  hit_rate_no: number | null;
}

export interface LongshotPosition {
  ticker: string;
  series: string;
  entry_ts: string;
  close_time: string;
  sell_price: number;
  size: number;
  fee: number;
  collateral: number;
  bid_depth_at_entry: number;
  status: string;
  result: string | null;
  pnl: number | null;
}

export interface LongshotStatus {
  heartbeat: LongshotHeartbeat | null;
  latest: LongshotLatest | null;
  series: LongshotSeriesPoint[];
  open_positions: LongshotPosition[];
  settled_positions: LongshotPosition[];
}

export async function getLongshotStatus() {
  const { data } = await client.get<LongshotStatus>("/longshot/status", {
    params: { _t: Date.now() },
  });
  return data;
}

export async function getLongshotLiveStatus() {
  const { data } = await client.get<LongshotStatus>("/longshot/live/status", {
    params: { _t: Date.now() },
  });
  return data;
}
