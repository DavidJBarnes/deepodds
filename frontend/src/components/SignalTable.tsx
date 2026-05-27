import type { Signal } from "@/api/bot";
import CountdownCell from "./CountdownCell";

const STATUS_COLORS: Record<string, string> = {
  signaled: "bg-blue-500/20 text-blue-400",
  placed: "bg-amber-500/20 text-amber-400",
  filled: "bg-purple-500/20 text-purple-400",
  settled_win: "bg-emerald-500/20 text-emerald-400",
  settled_loss: "bg-red-500/20 text-red-400",
  cancelled: "bg-slate-500/20 text-slate-400",
};

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function SignalTable({ signals }: { signals: Signal[] }) {
  if (signals.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
        <p className="text-slate-400">
          No signals yet.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-white">Signals</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 uppercase tracking-wide border-b border-slate-800">
              <th className="text-left px-4 py-2">Time</th>
              <th className="text-left px-4 py-2">Market</th>
              <th className="text-right px-4 py-2">Expiry</th>
              <th className="text-right px-4 py-2">Entry</th>
              <th className="text-right px-4 py-2">Live</th>
              <th className="text-right px-4 py-2">Qty</th>
              <th className="text-right px-4 py-2">Size</th>
              <th className="text-left px-4 py-2">Status</th>
              <th className="text-right px-4 py-2">Exit</th>
              <th className="text-right px-4 py-2">P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s) => (
              <tr key={s.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                <td className="px-4 py-2 text-slate-400">{formatTime(s.created_at)}</td>
                <td className="px-4 py-2 font-mono text-xs">
                  {s.event_ticker ? (
                    <a
                      href={`https://kalshi.com/events/${s.event_ticker}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sky-400 hover:text-sky-300 underline"
                    >
                      {s.market_ticker || s.pair}
                    </a>
                  ) : (
                    <span className="text-white">{s.market_ticker || s.pair}</span>
                  )}
                </td>
                <td className="px-4 py-2 text-right">
                  <CountdownCell target={s.expiry_time} status={s.status} />
                </td>
                <td className="px-4 py-2 text-right text-slate-300 tabular-nums">
                  ${(s.fill_price || s.entry_price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {s.live_market_prob != null ? (
                    <span className={s.live_market_prob >= (s.fill_price || s.entry_price) ? "text-emerald-400" : "text-red-400"}>
                      {s.live_market_prob.toLocaleString(undefined, { style: "percent", minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                    </span>
                  ) : (
                    <span className="text-slate-600">—</span>
                  )}
                </td>
                <td className="px-4 py-2 text-right text-slate-300 tabular-nums">
                  {s.quantity}
                </td>
                <td className="px-4 py-2 text-right text-slate-300 tabular-nums">
                  ${s.cost_usd.toFixed(2)}
                </td>
                <td className="px-4 py-2">
                  <span className={`text-xs font-medium px-2 py-0.5 rounded ${STATUS_COLORS[s.status] || "bg-slate-700 text-slate-400"}`}>
                    {s.status.replace("_", " ")}
                  </span>
                </td>
                <td className="px-4 py-2 text-right text-slate-300 tabular-nums">
                  {s.exit_price != null
                    ? `$${s.exit_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                    : "—"}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {s.pnl_usd != null ? (
                    <span className={s.pnl_usd >= 0 ? "text-emerald-400" : "text-red-400"}>
                      {s.pnl_usd >= 0 ? "+" : ""}${s.pnl_usd.toFixed(2)}
                      {s.pnl_pct != null && (
                        <span
                          className="text-xs ml-1 opacity-60"
                          title={s.pnl_pct < -100 ? "Loss exceeds 100% of position cost due to Kalshi fees" : undefined}
                        >
                          ({Math.max(s.pnl_pct, -100).toFixed(1)}%{s.pnl_pct < -100 ? "+" : ""})
                        </span>
                      )}
                    </span>
                  ) : s.unrealized_pnl_usd != null ? (
                    <span
                      className={`italic ${s.unrealized_pnl_usd >= 0 ? "text-emerald-400/60" : "text-red-400/60"}`}
                      title="Unrealized"
                    >
                      {s.unrealized_pnl_usd >= 0 ? "+" : ""}${s.unrealized_pnl_usd.toFixed(2)}
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
