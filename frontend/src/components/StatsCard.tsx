import type { PnLStats } from "@/api/bot";

export default function StatsCard({ stats }: { stats: PnLStats }) {
  const pnlPositive = stats.total_pnl_usd >= 0;

  return (
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
        <p className="text-xs text-slate-500 uppercase tracking-wide">Total P&amp;L</p>
        <p className={`text-2xl font-bold mt-1 ${pnlPositive ? "text-emerald-400" : "text-red-400"}`}>
          {pnlPositive ? "+" : ""}${stats.total_pnl_usd.toFixed(2)}
        </p>
        <p className="text-xs text-slate-500 mt-1">
          ${stats.total_cost_usd.toFixed(2)} invested
          {stats.unrealized_pnl_usd !== 0 && (
            <span className={stats.unrealized_pnl_usd >= 0 ? "text-emerald-400/60" : "text-red-400/60"}>
              {" "}({stats.unrealized_pnl_usd >= 0 ? "+" : ""}${stats.unrealized_pnl_usd.toFixed(2)} open)
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
  );
}
