import client from "./client";

export interface CarryHeartbeat {
  wall_ts: number;
  tick_ts: number;
  status: string;
  equity: number;
  killed: boolean;
  error: string | null;
}

export interface CarrySymbol {
  funding_ann: number | null;
  trailing_ann: number | null;
  target: number;
  notional: number;
  margin_ratio: number | null;
  accrued_funding: number;
}

export interface CarryLatest {
  ts: number;
  cash: number;
  equity: number;
  accrued_funding_total: number;
  realized_pnl: number;
  fees_total: number;
  killed: boolean;
  symbols: { [sym: string]: CarrySymbol };
}

export interface CarrySeriesPoint {
  ts: number;
  equity: number;
  accrued_funding: number;
}

export interface CarryPosition {
  coin_qty: number;
  entry_perp: number;
  entry_spot: number;
  hl_margin: number;
  reserve: number;
  accrued_funding: number;
}

export interface CarryStatus {
  heartbeat: CarryHeartbeat | null;
  latest: CarryLatest | null;
  series: CarrySeriesPoint[];
  positions: { [sym: string]: CarryPosition };
}

export async function getCarryStatus() {
  const { data } = await client.get<CarryStatus>("/carry/status", {
    params: { _t: Date.now() },
  });
  return data;
}
