import type { Signal } from "@/api/bot";

const TIER_STYLES: Record<string, { label: string; className: string }> = {
  elite: { label: "ELITE", className: "bg-emerald-500/20 text-emerald-400" },
  high: { label: "HIGH", className: "bg-amber-500/20 text-amber-400" },
  moderate: { label: "MOD", className: "bg-blue-500/20 text-blue-400" },
  speculative: { label: "SPEC", className: "bg-slate-500/20 text-slate-400" },
};

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
  settled_win: "bg-emerald-500/20 text-emerald-400",
  settled_loss: "bg-red-500/20 text-red-400",
};

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function statusLabel(s: Signal) {
  if (s.status === "settled_win" && s.exit_price_cents != null) return "take profit";
  return s.status.replace("_", " ");
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
              <th className="text-left px-4 py-2">Created</th>
              <th className="text-left px-4 py-2">Ticker</th>
              <th className="text-left px-4 py-2">Side</th>
              <th className="text-right px-4 py-2">Edge</th>
              <th className="text-left px-4 py-2">Tier</th>
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
                  {s.model_edge_cents != null ? `${Number(s.model_edge_cents.toFixed(1))}c` : "—"}
                </td>
                <td className="px-4 py-2">
                  {s.edge_tier && TIER_STYLES[s.edge_tier] ? (
                    <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${TIER_STYLES[s.edge_tier].className}`}>
                      {TIER_STYLES[s.edge_tier].label}
                    </span>
                  ) : (
                    <span className="text-slate-600">—</span>
                  )}
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
                  <span className={`text-xs font-medium px-2 py-0.5 rounded ${STATUS_COLORS[s.status] || "bg-slate-700 text-slate-400"}`}>
                    {statusLabel(s)}
                  </span>
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
