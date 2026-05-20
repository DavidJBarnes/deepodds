import type { PnLStats, SpotPnLStats } from "@/api/bot";

export default function StatsCard({ stats, spotStats }: { stats: PnLStats; spotStats?: SpotPnLStats | null }) {
  const kalshiPnlCents = stats.total_pnl_cents;
  const spotPnlUsd = spotStats ? spotStats.realized_pnl_usd + spotStats.unrealized_pnl_usd : 0;
  const combinedPnlCents = kalshiPnlCents + Math.round(spotPnlUsd * 100);
  const pnlPositive = combinedPnlCents >= 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Signals</p>
          <p className="text-2xl font-bold text-white mt-1">{stats.total_signals}</p>
          <p className="text-xs text-slate-500 mt-1">
            {stats.settled_count} settled{stats.open_positions > 0 && ` · ${stats.open_positions} open`}
          </p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Win Rate</p>
          <p className="text-2xl font-bold text-white mt-1">
            {stats.settled_count > 0 ? `${stats.win_rate.toFixed(1)}%` : "—"}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            {stats.wins}W / {stats.losses}L
          </p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Total P&L</p>
          <p className={`text-2xl font-bold mt-1 ${pnlPositive ? "text-emerald-400" : "text-red-400"}`}>
            {pnlPositive ? "+" : ""}${(combinedPnlCents / 100).toFixed(2)}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            ${(stats.total_cost_cents / 100).toFixed(2)} invested
            {stats.unrealized_pnl_cents !== 0 && (
              <span className={stats.unrealized_pnl_cents >= 0 ? "text-emerald-400/60" : "text-red-400/60"}>
                {" "}({stats.unrealized_pnl_cents >= 0 ? "+" : ""}${(stats.unrealized_pnl_cents / 100).toFixed(2)} open)
              </span>
            )}
          </p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide">ROI</p>
          <p className={`text-2xl font-bold mt-1 ${stats.roi_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {stats.roi_pct >= 0 ? "+" : ""}{stats.roi_pct.toFixed(1)}%
          </p>
        </div>
      </div>
      {spotStats && spotStats.total_trades > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="bg-slate-900 border border-blue-500/20 rounded-xl p-4">
            <p className="text-xs text-blue-400 uppercase tracking-wide">Spot Trades</p>
            <p className="text-2xl font-bold text-white mt-1">{spotStats.total_trades}</p>
            {spotStats.open_position_btc > 0 && (
              <p className="text-xs text-slate-500 mt-1">{spotStats.open_position_btc.toFixed(6)} BTC open</p>
            )}
          </div>
          <div className="bg-slate-900 border border-blue-500/20 rounded-xl p-4">
            <p className="text-xs text-blue-400 uppercase tracking-wide">Spot P&L</p>
            <p className={`text-2xl font-bold mt-1 ${spotStats.realized_pnl_usd >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {spotStats.realized_pnl_usd >= 0 ? "+" : ""}${spotStats.realized_pnl_usd.toFixed(2)}
            </p>
            {spotStats.unrealized_pnl_usd !== 0 && (
              <p className="text-xs text-slate-500 mt-1">
                <span className={spotStats.unrealized_pnl_usd >= 0 ? "text-emerald-400/60" : "text-red-400/60"}>
                  {spotStats.unrealized_pnl_usd >= 0 ? "+" : ""}${spotStats.unrealized_pnl_usd.toFixed(2)} open
                </span>
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
