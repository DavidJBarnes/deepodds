import type { Signal } from "@/api/bot";

const STATUS_COLORS: Record<string, string> = {
  signaled: "bg-blue-500/20 text-blue-400",
  placed: "bg-amber-500/20 text-amber-400",
  filled: "bg-purple-500/20 text-purple-400",
  settled_win: "bg-emerald-500/20 text-emerald-400",
  settled_loss: "bg-red-500/20 text-red-400",
};

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function SignalTable({ signals }: { signals: Signal[] }) {
  if (signals.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
        <p className="text-slate-400">No signals yet. The bot will generate signals when it finds mispriced markets.</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-white">Recent Signals</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 uppercase tracking-wide border-b border-slate-800">
              <th className="text-left px-4 py-2">Time</th>
              <th className="text-left px-4 py-2">Ticker</th>
              <th className="text-left px-4 py-2">Side</th>
              <th className="text-right px-4 py-2">Edge</th>
              <th className="text-right px-4 py-2">Price</th>
              <th className="text-right px-4 py-2">Qty</th>
              <th className="text-right px-4 py-2">Cost</th>
              <th className="text-left px-4 py-2">Status</th>
              <th className="text-right px-4 py-2">P&L</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s) => (
              <tr key={s.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                <td className="px-4 py-2 text-slate-400">{formatTime(s.created_at)}</td>
                <td className="px-4 py-2 text-white font-mono text-xs">{s.ticker}</td>
                <td className="px-4 py-2">
                  <span className={s.side === "yes" ? "text-emerald-400" : "text-red-400"}>
                    {s.side.toUpperCase()}
                  </span>
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {s.model_edge_cents != null ? `${s.model_edge_cents.toFixed(1)}c` : "—"}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {s.limit_price_cents}c
                </td>
                <td className="px-4 py-2 text-right text-slate-300">{s.quantity}</td>
                <td className="px-4 py-2 text-right text-slate-300">
                  ${(s.cost_cents / 100).toFixed(2)}
                </td>
                <td className="px-4 py-2">
                  <span className={`text-xs font-medium px-2 py-0.5 rounded ${STATUS_COLORS[s.status] || "bg-slate-700 text-slate-400"}`}>
                    {s.status.replace("_", " ")}
                  </span>
                </td>
                <td className="px-4 py-2 text-right">
                  {s.pnl_cents != null ? (
                    <span className={s.pnl_cents >= 0 ? "text-emerald-400" : "text-red-400"}>
                      {s.pnl_cents >= 0 ? "+" : ""}${(s.pnl_cents / 100).toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-slate-600">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
