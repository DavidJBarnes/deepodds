import type { Signal } from "@/api/bot";

const SERIES_SLUGS: Record<string, string> = {
  KXBTC: "bitcoin-range",
  KXBTCD: "bitcoin-price",
  KXETH: "ethereum-range",
  KXETHD: "ethereum-price",
};

function kalshiUrl(ticker: string) {
  const series = ticker.split("-")[0];
  const eventTicker = ticker.substring(0, ticker.lastIndexOf("-")).toLowerCase();
  const slug = SERIES_SLUGS[series];
  if (slug) return `https://kalshi.com/markets/${series.toLowerCase()}/${slug}/${eventTicker}`;
  return `https://kalshi.com/markets/${eventTicker}`;
}

const STATUS_COLORS: Record<string, string> = {
  signaled: "bg-blue-500/20 text-blue-400",
  placed: "bg-amber-500/20 text-amber-400",
  filled: "bg-purple-500/20 text-purple-400",
  settling: "bg-cyan-500/20 text-cyan-400",
  settled_win: "bg-emerald-500/20 text-emerald-400",
  settled_loss: "bg-red-500/20 text-red-400",
  cancelled: "bg-slate-500/20 text-slate-400",
};

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function timeRemaining(closeTime: string | null) {
  if (!closeTime) return null;
  const now = Date.now();
  const close = new Date(closeTime).getTime();
  const diff = close - now;
  if (diff <= 0) return "expired";
  const mins = Math.floor(diff / 60000);
  if (mins >= 1440) return `${Math.floor(mins / 1440)}d`;
  if (mins >= 60) return `${Math.floor(mins / 60)}h ${mins % 60}m`;
  return `${mins}m`;
}

function statusLabel(s: Signal) {
  if (s.status === "settled_win" && s.exit_price_cents != null) return "take profit";
  if (s.status === "filled" && s.close_time && new Date(s.close_time).getTime() < Date.now()) return "settling";
  return s.status.replace("_", " ");
}


export default function SignalTable({ signals }: { signals: Signal[] }) {
  if (signals.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
        <p className="text-slate-400">
          No signals yet. The bot places signals when settlement arb opportunities appear — near-expiry contracts with high sigma distance and market discount.
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
              <th className="text-left px-4 py-2">Contract</th>
              <th className="text-left px-4 py-2">Side</th>
              <th className="text-right px-4 py-2">Win Prob</th>
              <th className="text-right px-4 py-2">Discount</th>
              <th className="text-right px-4 py-2">Entry</th>
              <th className="text-right px-4 py-2">Qty</th>
              <th className="text-right px-4 py-2">Cost</th>
              <th className="text-left px-4 py-2">Status</th>
              <th className="text-right px-4 py-2">Expires</th>
              <th className="text-right px-4 py-2">P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s) => (
              <tr key={s.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                <td className="px-4 py-2 text-slate-400">{formatTime(s.created_at)}</td>
                <td className="px-4 py-2 font-mono text-xs">
                  <a
                    href={kalshiUrl(s.ticker)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-white hover:text-emerald-400 transition-colors"
                  >
                    {s.ticker}
                  </a>
                </td>
                <td className="px-4 py-2">
                  <span className={s.side === "yes" ? "text-emerald-400" : "text-red-400"}>
                    {s.side.toUpperCase()}
                  </span>
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {s.model_prob != null ? `${(s.model_prob * 100).toFixed(1)}%` : "—"}
                </td>
                <td className={`px-4 py-2 text-right font-medium ${
                  s.model_edge_cents != null && s.model_edge_cents >= 0 ? "text-emerald-400" : "text-red-400"
                }`}>
                  {s.model_edge_cents != null ? `${s.model_edge_cents.toFixed(1)}c` : "—"}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {s.fill_price_cents != null ? (
                    <span title={`Limit: ${s.limit_price_cents}c`}>
                      {s.fill_price_cents}c
                      {s.exit_price_cents != null && (
                        <span className="text-slate-500 ml-1">→ {s.exit_price_cents}c</span>
                      )}
                    </span>
                  ) : (
                    <>{s.limit_price_cents}c</>
                  )}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">{s.quantity}</td>
                <td className="px-4 py-2 text-right text-slate-300">
                  ${(s.cost_cents / 100).toFixed(2)}
                </td>
                <td className="px-4 py-2">
                  {(() => {
                    const label = statusLabel(s);
                    const color = STATUS_COLORS[label] || STATUS_COLORS[s.status] || "bg-slate-700 text-slate-400";
                    return (
                      <span className={`text-xs font-medium px-2 py-0.5 rounded ${color}`}>
                        {label}
                      </span>
                    );
                  })()}
                </td>
                <td className="px-4 py-2 text-right text-xs text-slate-400">
                  {s.status.startsWith("settled") ? (
                    <span className="text-slate-600">done</span>
                  ) : (
                    timeRemaining(s.close_time) || "—"
                  )}
                </td>
                <td className="px-4 py-2 text-right">
                  {s.pnl_cents != null ? (
                    <span className={s.pnl_cents >= 0 ? "text-emerald-400" : "text-red-400"}>
                      {s.pnl_cents >= 0 ? "+" : ""}${(s.pnl_cents / 100).toFixed(2)}
                    </span>
                  ) : s.unrealized_pnl_cents != null ? (
                    <span
                      className={`italic ${s.unrealized_pnl_cents >= 0 ? "text-emerald-400/60" : "text-red-400/60"}`}
                      title="Unrealized"
                    >
                      {s.unrealized_pnl_cents >= 0 ? "+" : ""}${(s.unrealized_pnl_cents / 100).toFixed(2)}
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
